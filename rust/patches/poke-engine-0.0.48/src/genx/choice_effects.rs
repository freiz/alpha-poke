use super::abilities::Abilities;
use super::damage_calc::type_effectiveness_modifier;
use super::generate_instructions::{add_remove_status_instructions, apply_boost_instruction};
use super::items::{get_choice_move_disable_instructions, room_service, Items};
use super::state::{PokemonVolatileStatus, Terrain, Weather};
use crate::choices::{
    Boost, Choice, Choices, Effect, Heal, MoveCategory, MoveTarget, Secondary, StatBoosts,
};
use crate::instruction::{
    ApplyVolatileStatusInstruction, BoostInstruction, ChangeItemInstruction,
    ChangeSideConditionInstruction, ChangeStatusInstruction, ChangeSubsituteHealthInstruction,
    ChangeTerrain, ChangeType, ChangeVolatileStatusDurationInstruction, ChangeWeather,
    ChangeWishInstruction, DamageInstruction, HealInstruction, Instruction,
    RemoveVolatileStatusInstruction, SetFutureSightInstruction, SetSleepTurnsInstruction,
    StateInstructions, ToggleTrickRoomInstruction,
};
use crate::pokemon::PokemonName;
use crate::state::{
    pokemon_index_iter, LastUsedMove, Pokemon, PokemonBoostableStat, PokemonSideCondition,
    PokemonStatus, PokemonType, Side, SideReference, State,
};
use std::cmp;

const CHOICE_THAWS_USER: [Choices; 10] = [
    Choices::FLAMEWHEEL,
    Choices::SACREDFIRE,
    Choices::FLAREBLITZ,
    Choices::FUSIONFLARE,
    Choices::SCALD,
    Choices::STEAMERUPTION,
    Choices::BURNUP,
    Choices::PYROBALL,
    Choices::SCORCHINGSANDS,
    Choices::MATCHAGOTCHA,
];

// L71: Beat Up's hitters, in party order (the user, and the allies neither fainted nor statused)
pub fn beat_up_allies(side: &Side) -> Vec<&Pokemon> {
    let active = side.active_index;
    let mut out = vec![];
    for i in pokemon_index_iter() {
        let p = &side.pokemon[i];
        if i == active || (p.hp > 0 && p.status == PokemonStatus::NONE) {
            out.push(p);
        }
    }
    out
}

pub fn modify_choice(
    state: &State,
    attacker_choice: &mut Choice,
    defender_choice: &Choice,
    attacking_side_ref: &SideReference,
) {
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);
    match attacker_choice.move_id {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L2a / L2b): Curse by a Ghost type
        // curses the target (no boosts; fails on a cursed target) and costs the user half of its
        // max HP (Showdown's curse onTryHit / onHit); by any other type it only boosts (the data's
        // "curse" volatile on the user is removed: it has no effect in Showdown)
        Choices::CURSE => {
            if attacking_side
                .get_active_immutable()
                .has_type(&PokemonType::GHOST)
            {
                attacker_choice.boost = None;
                if defending_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::CURSE)
                {
                    attacker_choice.volatile_status = None;
                } else {
                    attacker_choice.volatile_status = Some(crate::choices::VolatileStatus {
                        target: MoveTarget::Opponent,
                        volatile_status: PokemonVolatileStatus::CURSE,
                    });
                    attacker_choice.heal = Some(Heal {
                        target: MoveTarget::User,
                        amount: -0.5,
                    });
                }
            } else {
                attacker_choice.volatile_status = None;
            }
        }
        Choices::ROOST => {
            let attacker = attacking_side.get_active_immutable();
            if attacker.hp == attacker.maxhp {
                attacker_choice.volatile_status = None
            }
        }
        Choices::ELECTROSHOT => {
            if state.weather_is_active(&Weather::RAIN) {
                attacker_choice.flags.charge = false;
            }
        }
        #[cfg(not(feature = "champions"))]
        Choices::DIRECLAW => {
            // percentages are a hack and are incorrect in situations
            // where one or more status effects are not possible
            attacker_choice.add_or_create_secondaries(Secondary {
                chance: 16.67,
                target: MoveTarget::Opponent,
                effect: Effect::Status(PokemonStatus::POISON),
            });
            attacker_choice.add_or_create_secondaries(Secondary {
                chance: 20.00,
                target: MoveTarget::Opponent,
                effect: Effect::Status(PokemonStatus::PARALYZE),
            });
            attacker_choice.add_or_create_secondaries(Secondary {
                chance: 25.0,
                target: MoveTarget::Opponent,
                effect: Effect::Status(PokemonStatus::SLEEP),
            });
        }
        #[cfg(feature = "champions")]
        Choices::DIRECLAW => {
            // percentages are a hack and are incorrect in situations
            // where one or more status effects are not possible
            attacker_choice.add_or_create_secondaries(Secondary {
                chance: 10.00,
                target: MoveTarget::Opponent,
                effect: Effect::Status(PokemonStatus::POISON),
            });
            attacker_choice.add_or_create_secondaries(Secondary {
                chance: 11.125,
                target: MoveTarget::Opponent,
                effect: Effect::Status(PokemonStatus::PARALYZE),
            });
            attacker_choice.add_or_create_secondaries(Secondary {
                chance: 12.25,
                target: MoveTarget::Opponent,
                effect: Effect::Status(PokemonStatus::SLEEP),
            });
        }
        Choices::DOUBLESHOCK => {
            if !attacking_side
                .get_active_immutable()
                .has_type(&PokemonType::ELECTRIC)
            {
                attacker_choice.remove_all_effects();
            }
        }
        Choices::BURNUP => {
            if !attacking_side
                .get_active_immutable()
                .has_type(&PokemonType::FIRE)
            {
                attacker_choice.remove_all_effects();
            }
        }
        Choices::REVERSAL => {
            let attacker = attacking_side.get_active_immutable();
            let hp_ratio = attacker.hp as f32 / attacker.maxhp as f32;
            if hp_ratio >= 0.688 {
                attacker_choice.base_power = 20.0;
            } else if hp_ratio >= 0.354 {
                attacker_choice.base_power = 40.0;
            } else if hp_ratio >= 0.208 {
                attacker_choice.base_power = 80.0;
            } else if hp_ratio >= 0.104 {
                attacker_choice.base_power = 100.0;
            } else if hp_ratio >= 0.042 {
                attacker_choice.base_power = 150.0;
            } else {
                attacker_choice.base_power = 200.0;
            }
        }
        Choices::AURAWHEEL => {
            if attacking_side.get_active_immutable().id == PokemonName::MORPEKOHANGRY {
                attacker_choice.move_type = PokemonType::DARK;
            }
        }
        Choices::IVYCUDGEL => {
            let attacker = attacking_side.get_active_immutable();
            match attacker.item {
                Items::WELLSPRINGMASK => {
                    attacker_choice.move_type = PokemonType::WATER;
                }
                Items::HEARTHFLAMEMASK => {
                    attacker_choice.move_type = PokemonType::FIRE;
                }
                Items::CORNERSTONEMASK => {
                    attacker_choice.move_type = PokemonType::ROCK;
                }
                _ => {}
            }
        }
        Choices::RAGINGBULL => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L27): the screens are broken before
            // the damage now (generate_instructions::screen_break_instructions); the doubled power
            // that stood in for it (vs Reflect / Aurora Veil) would count twice
            match attacking_side.get_active_immutable().id {
                PokemonName::TAUROSPALDEACOMBAT => {
                    attacker_choice.move_type = PokemonType::FIGHTING;
                }
                PokemonName::TAUROSPALDEABLAZE => {
                    attacker_choice.move_type = PokemonType::FIRE;
                }
                PokemonName::TAUROSPALDEAAQUA => {
                    attacker_choice.move_type = PokemonType::WATER;
                }
                _ => {}
            }
        }
        Choices::BOLTBEAK | Choices::FISHIOUSREND => {
            if attacker_choice.first_move {
                attacker_choice.base_power *= 2.0;
            }
        }
        Choices::HARDPRESS => {
            let defender = defending_side.get_active_immutable();
            // L34: Showdown's basePowerCallback, its integer steps
            let (hp, maxhp) = (defender.hp as i64, defender.maxhp.max(1) as i64);
            let bp = ((100 * (100 * (hp * 4096 / maxhp)) + 2047) / 4096) / 100;
            attacker_choice.base_power = bp.max(1) as f32;
        }
        Choices::LASTRESPECTS => {
            // Technically not correct because of reviving moves but good enough
            let mut bp_boost = 1.0;
            bp_boost += 1.0 * attacking_side.num_fainted_pkmn() as f32;
            attacker_choice.base_power *= bp_boost
        }
        Choices::CLANGOROUSSOUL => {
            let attacker = attacking_side.get_active_immutable();
            if attacker.hp > attacker.maxhp / 3 {
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::User,
                    amount: -0.33,
                });
                attacker_choice.boost = Some(Boost {
                    target: MoveTarget::User,
                    boosts: StatBoosts {
                        attack: 1,
                        defense: 1,
                        special_attack: 1,
                        special_defense: 1,
                        speed: 1,
                        accuracy: 0,
                    },
                });
            }
        }
        Choices::EXPANDINGFORCE => {
            if state.terrain.terrain_type == Terrain::PSYCHICTERRAIN {
                attacker_choice.base_power *= 1.5;
            }
        }
        Choices::FILLETAWAY => {
            let attacker = attacking_side.get_active_immutable();
            if attacker.hp > attacker.maxhp / 2 {
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::User,
                    amount: -0.5,
                });
                attacker_choice.boost = Some(Boost {
                    target: MoveTarget::User,
                    boosts: StatBoosts {
                        attack: 2,
                        defense: 0,
                        special_attack: 2,
                        special_defense: 0,
                        speed: 2,
                        accuracy: 0,
                    },
                });
            }
        }
        Choices::FAKEOUT | Choices::FIRSTIMPRESSION => match attacking_side.last_used_move {
            LastUsedMove::Move(_) => attacker_choice.remove_all_effects(),
            _ => {}
        },
        Choices::GROWTH => {
            // as of writing this, growth should fail in champions if mega-sol is active
            // not that the 2x boost fails to activate, it literally fails to do anything
            // a) that's probably a bug?
            // b) can only have this happen with some skill swap shenanigans
            // so I won't bother implementing
            if state.weather_is_active(&Weather::SUN) {
                attacker_choice.boost = Some(Boost {
                    target: MoveTarget::User,
                    boosts: StatBoosts {
                        attack: 2,
                        defense: 0,
                        special_attack: 2,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    },
                });
            }
        }
        Choices::HEX => {
            if defending_side.get_active_immutable().status != PokemonStatus::NONE {
                attacker_choice.base_power *= 2.0;
            }
        }
        Choices::HYDROSTEAM => {
            if state.weather_is_active(&Weather::SUN) {
                attacker_choice.base_power *= 3.0; // 1.5x for being in sun, 2x for cancelling out rain debuff
            }
        }
        Choices::JUDGMENT => {
            attacker_choice.move_type = attacking_side.get_active_immutable().types.0;
        }
        Choices::MULTIATTACK => {
            attacker_choice.move_type = attacking_side.get_active_immutable().types.0;
        }
        Choices::MISTYEXPLOSION => {
            if state.terrain.terrain_type == Terrain::MISTYTERRAIN {
                attacker_choice.base_power *= 1.5;
            }
        }
        #[cfg(feature = "gen4")]
        Choices::EXPLOSION | Choices::SELFDESTRUCT => {
            attacker_choice.base_power *= 2.0;
        }

        Choices::MORNINGSUN | Choices::MOONLIGHT | Choices::SYNTHESIS => {
            if attacking_side.get_active_immutable().ability == Abilities::MEGASOL {
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::User,
                    amount: 0.667,
                })
            } else {
                match state.weather.weather_type {
                    Weather::SUN => {
                        attacker_choice.heal = Some(Heal {
                            target: MoveTarget::User,
                            amount: 0.667,
                        })
                    }
                    Weather::NONE => {}
                    _ => {
                        attacker_choice.heal = Some(Heal {
                            target: MoveTarget::User,
                            amount: 0.25,
                        })
                    }
                }
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L68): Healing Wish / Lunar Dance fail
        // without a mon to switch in (Showdown's canSwitch: the user does not faint)
        Choices::HEALINGWISH | Choices::LUNARDANCE => {
            if attacking_side.visible_alive_pkmn() <= 1 {
                attacker_choice.heal = None;
                attacker_choice.side_condition = None;
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L73): Spit Up's 100 power a layer,
        // Swallow's 25 / 50 / 100% (no layers: they fail); the layers end in choice_special_effect
        Choices::SPITUP => {
            attacker_choice.base_power =
                100.0 * attacking_side.volatile_status_durations.stockpile as f32;
        }
        Choices::SWALLOW => {
            attacker_choice.heal = match attacking_side.volatile_status_durations.stockpile {
                1 => Some(Heal {
                    target: MoveTarget::User,
                    amount: 0.25,
                }),
                2 => Some(Heal {
                    target: MoveTarget::User,
                    amount: 0.5,
                }),
                n if n >= 3 => Some(Heal {
                    target: MoveTarget::User,
                    amount: 1.0,
                }),
                _ => None,
            };
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L71): Beat Up, a hit for the user and
        // each ally neither fainted nor statused, of 5 + its base Attack / 10: their mean power
        // here, their number of hits in generate_instructions (beat_up_hits)
        Choices::BEATUP => {
            let powers: Vec<f32> = beat_up_allies(attacking_side)
                .iter()
                .map(|p| 5.0 + (p.id.base_stats().1 / 10) as f32)
                .collect();
            attacker_choice.base_power = powers.iter().sum::<f32>() / powers.len().max(1) as f32;
        }
        Choices::NORETREAT => {
            if attacking_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::NORETREAT)
            {
                attacker_choice.boost = None;
            }
        }
        Choices::POLTERGEIST => {
            if defending_side.get_active_immutable().item == Items::NONE {
                attacker_choice.base_power = 0.0;
            }
        }
        Choices::PSYBLADE => {
            if state.terrain.terrain_type == Terrain::ELECTRICTERRAIN {
                attacker_choice.base_power *= 1.5;
            }
        }
        Choices::PURSUIT => {
            if defender_choice.category == MoveCategory::Switch {
                attacker_choice.base_power *= 2.0;
            }
        }
        Choices::REVELATIONDANCE => {
            if attacking_side.get_active_immutable().terastallized {
                attacker_choice.move_type = attacking_side.get_active_immutable().tera_type;
            } else {
                attacker_choice.move_type = attacking_side.get_active_immutable().types.0;
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L33): 2 x against a grounded target
        // (Showdown's onBasePower; was 1.5 x against any)
        Choices::RISINGVOLTAGE => {
            if state.terrain.terrain_type == Terrain::ELECTRICTERRAIN
                && (defending_side.get_active_immutable().is_grounded()
                    || super::damage_calc::grounded_by_effect(
                        defending_side,
                        defending_side.get_active_immutable(),
                    ))
            {
                attacker_choice.base_power *= 2.0;
            }
        }
        Choices::SHOREUP => {
            if state.weather_is_active(&Weather::SAND) {
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::User,
                    amount: 0.667,
                });
            }
        }
        Choices::STEELROLLER => {
            if state.terrain.terrain_type == Terrain::NONE {
                attacker_choice.base_power = 0.0;
            }
        }
        Choices::STRENGTHSAP => {
            attacker_choice.boost = Some(Boost {
                target: MoveTarget::Opponent,
                boosts: StatBoosts {
                    attack: -1,
                    defense: 0,
                    special_attack: 0,
                    special_defense: 0,
                    speed: 0,
                    accuracy: 0,
                },
            });
            if defending_side.attack_boost != -6 {
                let defender_attack =
                    defending_side.calculate_boosted_stat(PokemonBoostableStat::Attack);
                let attacker_maxhp = attacking_side.get_active_immutable().maxhp;

                if defending_side.get_active_immutable().ability == Abilities::LIQUIDOOZE {
                    attacker_choice.heal = Some(Heal {
                        target: MoveTarget::User,
                        amount: -1.0 * defender_attack as f32 / attacker_maxhp as f32,
                    });
                } else {
                    attacker_choice.heal = Some(Heal {
                        target: MoveTarget::User,
                        amount: defender_attack as f32 / attacker_maxhp as f32,
                    });
                }
            }
        }
        Choices::TERABLAST => {
            let active = attacking_side.get_active_immutable();
            if active.terastallized {
                attacker_choice.move_type = active.tera_type;
                if attacking_side.calculate_boosted_stat(PokemonBoostableStat::Attack)
                    > attacking_side.calculate_boosted_stat(PokemonBoostableStat::SpecialAttack)
                {
                    attacker_choice.category = MoveCategory::Physical;
                }
                if active.tera_type == PokemonType::STELLAR {
                    attacker_choice.add_or_create_secondaries(Secondary {
                        chance: 100.0,
                        target: MoveTarget::User,
                        effect: Effect::Boost(StatBoosts {
                            attack: -1,
                            defense: 0,
                            special_attack: -1,
                            special_defense: 0,
                            speed: 0,
                            accuracy: 0,
                        }),
                    })
                }
            }
        }
        Choices::PHOTONGEYSER => {
            if attacking_side.calculate_boosted_stat(PokemonBoostableStat::Attack)
                > attacking_side.calculate_boosted_stat(PokemonBoostableStat::SpecialAttack)
            {
                attacker_choice.category = MoveCategory::Physical;
            }
        }
        Choices::TERRAINPULSE => match state.terrain.terrain_type {
            Terrain::ELECTRICTERRAIN => {
                attacker_choice.move_type = PokemonType::ELECTRIC;
                attacker_choice.base_power *= 2.0;
            }
            Terrain::GRASSYTERRAIN => {
                attacker_choice.move_type = PokemonType::GRASS;
                attacker_choice.base_power *= 2.0;
            }
            Terrain::MISTYTERRAIN => {
                attacker_choice.move_type = PokemonType::FAIRY;
                attacker_choice.base_power *= 2.0;
            }
            Terrain::PSYCHICTERRAIN => {
                attacker_choice.move_type = PokemonType::PSYCHIC;
                attacker_choice.base_power *= 2.0;
            }
            Terrain::NONE => {}
        },
        Choices::TOXIC => {
            if attacking_side
                .get_active_immutable()
                .has_type(&PokemonType::POISON)
            {
                attacker_choice.accuracy = 100.0;
            }
        }
        Choices::WEATHERBALL => {
            if attacking_side.get_active_immutable().ability == Abilities::MEGASOL {
                attacker_choice.base_power = 100.0;
                attacker_choice.move_type = PokemonType::FIRE;
            } else {
                match state.weather.weather_type {
                    Weather::SUN | Weather::HARSHSUN => {
                        attacker_choice.base_power = 100.0;
                        attacker_choice.move_type = PokemonType::FIRE;
                    }
                    Weather::RAIN | Weather::HEAVYRAIN => {
                        attacker_choice.base_power = 100.0;
                        attacker_choice.move_type = PokemonType::WATER;
                    }
                    Weather::SAND => {
                        attacker_choice.base_power = 100.0;
                        attacker_choice.move_type = PokemonType::ROCK;
                    }
                    Weather::HAIL | Weather::SNOW => {
                        attacker_choice.base_power = 100.0;
                        attacker_choice.move_type = PokemonType::ICE;
                    }
                    Weather::NONE => {}
                }
            }
        }
        Choices::SOLARBEAM | Choices::SOLARBLADE => {
            if state.weather_is_active(&Weather::SUN) || state.weather_is_active(&Weather::HARSHSUN)
            {
                attacker_choice.flags.charge = false;
            } else if !state.weather_is_active(&Weather::SUN)
                && state.weather.weather_type != Weather::NONE
            {
                attacker_choice.base_power /= 2.0;
            }
        }
        Choices::BLIZZARD => {
            if state.weather_is_active(&Weather::HAIL) {
                attacker_choice.accuracy = 100.0;
            }
        }
        Choices::HURRICANE | Choices::THUNDER => {
            if state.weather_is_active(&Weather::RAIN)
                || state.weather_is_active(&Weather::HEAVYRAIN)
            {
                attacker_choice.accuracy = 100.0;
            } else if state.weather_is_active(&Weather::SUN)
                || state.weather_is_active(&Weather::HARSHSUN)
            {
                attacker_choice.accuracy = 50.0;
            }
        }

        #[cfg(any(
            feature = "gen6",
            feature = "gen7",
            feature = "gen8",
            feature = "gen9",
            feature = "champions"
        ))]
        Choices::KNOCKOFF => {
            // Bonus damage still applies if substitute is hit
            let defender = defending_side.get_active_immutable();
            if !defender.item_is_permanent() && defender.item != Items::NONE {
                attacker_choice.base_power *= 1.5;
            }
        }

        Choices::ACROBATICS => {
            if attacking_side.get_active_immutable().item == Items::NONE {
                attacker_choice.base_power *= 2.0;
            }
        }
        Choices::FOCUSPUNCH => {
            if (defending_side.damage_dealt.move_category == MoveCategory::Physical
                || defending_side.damage_dealt.move_category == MoveCategory::Special)
                && !defending_side.damage_dealt.hit_substitute
                && defending_side.damage_dealt.damage > 0
            {
                attacker_choice.remove_all_effects();
            }
        }
        Choices::ELECTROBALL => {
            let attacker_speed = attacking_side.calculate_boosted_stat(PokemonBoostableStat::Speed);
            let defender_speed = defending_side.calculate_boosted_stat(PokemonBoostableStat::Speed);
            let speed_ratio = attacker_speed as f32 / defender_speed as f32;
            if speed_ratio >= 4.0 {
                attacker_choice.base_power = 150.0;
            } else if speed_ratio >= 3.0 {
                attacker_choice.base_power = 120.0;
            } else if speed_ratio >= 2.0 {
                attacker_choice.base_power = 80.0;
            } else if speed_ratio >= 1.0 {
                attacker_choice.base_power = 60.0;
            } else {
                attacker_choice.base_power = 40.0;
            }
        }
        Choices::GYROBALL => {
            let attacker_speed = attacking_side.calculate_boosted_stat(PokemonBoostableStat::Speed);
            let defender_speed = defending_side.calculate_boosted_stat(PokemonBoostableStat::Speed);

            // (L34: floored as Showdown's basePowerCallback)
            attacker_choice.base_power =
                ((25.0 * defender_speed as f32 / attacker_speed as f32).floor() + 1.0).min(150.0);
        }
        Choices::AVALANCHE => {
            if !attacker_choice.first_move && defending_side.damage_dealt.damage > 0 {
                attacker_choice.base_power *= 2.0;
            }
        }

        #[cfg(feature = "gen4")]
        Choices::PAYBACK => {
            if !attacker_choice.first_move {
                attacker_choice.base_power *= 2.0;
            }
        }

        #[cfg(any(
            feature = "gen5",
            feature = "gen6",
            feature = "gen7",
            feature = "gen8",
            feature = "gen9",
            feature = "champions"
        ))]
        Choices::PAYBACK => {
            if !attacker_choice.first_move && defender_choice.category != MoveCategory::Switch {
                attacker_choice.base_power *= 2.0;
            }
        }

        Choices::FACADE => {
            if attacking_side.get_active_immutable().status != PokemonStatus::NONE {
                attacker_choice.base_power *= 2.0;
            }
        }
        Choices::STOREDPOWER | Choices::POWERTRIP => {
            let total_boosts = attacking_side.attack_boost.max(0)
                + attacking_side.defense_boost.max(0)
                + attacking_side.special_attack_boost.max(0)
                + attacking_side.special_defense_boost.max(0)
                + attacking_side.speed_boost.max(0)
                + attacking_side.accuracy_boost.max(0)
                + attacking_side.evasion_boost.max(0);
            if total_boosts > 0 {
                attacker_choice.base_power += 20.0 * total_boosts as f32;
            }
        }
        Choices::BARBBARRAGE => {
            let defending_pkmn_status = defending_side.get_active_immutable().status;
            if defending_pkmn_status == PokemonStatus::POISON
                || defending_pkmn_status == PokemonStatus::TOXIC
            {
                attacker_choice.base_power *= 2.0;
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L34): Freeze-Dry's Water weakness in
        // damage_calc's effectiveness stages (was 4 x on the base power)
        Choices::ERUPTION | Choices::WATERSPOUT | Choices::DRAGONENERGY => {
            let attacker = attacking_side.get_active_immutable();
            let hp_ratio = attacker.hp as f32 / attacker.maxhp as f32;
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L34): floored, at least 1
            // (Showdown's clampIntRange of the callback's fraction)
            attacker_choice.base_power = (attacker_choice.base_power * hp_ratio).floor().max(1.0);
        }
        Choices::SUCKERPUNCH | Choices::THUNDERCLAP => {
            if !attacker_choice.first_move || defender_choice.category == MoveCategory::Status {
                attacker_choice.base_power = 0.0;
            }
        }
        Choices::UPPERHAND => {
            if !(attacker_choice.first_move && defender_choice.priority > 0) {
                attacker_choice.remove_all_effects()
            }
        }
        Choices::COLLISIONCOURSE | Choices::ELECTRODRIFT => {
            let defender_active = defending_side.get_active_immutable();
            if type_effectiveness_modifier(&attacker_choice.move_type, &defender_active) > 1.0 {
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Choices::GRASSKNOT | Choices::LOWKICK => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Float Stone halves the weight
            let weight = effective_weight(defending_side.get_active_immutable());
            if weight < 10.0 {
                attacker_choice.base_power = 20.0;
            } else if weight < 25.0 {
                attacker_choice.base_power = 40.0;
            } else if weight < 50.0 {
                attacker_choice.base_power = 60.0;
            } else if weight < 100.0 {
                attacker_choice.base_power = 80.0;
            } else if weight < 200.0 {
                attacker_choice.base_power = 100.0;
            } else {
                attacker_choice.base_power = 120.0;
            }
        }
        Choices::HEATCRASH | Choices::HEAVYSLAM => {
            let attacker = attacking_side.get_active_immutable();
            let defender = defending_side.get_active_immutable();
            let weight_ratio = effective_weight(defender) / effective_weight(attacker);
            if weight_ratio > 0.5 {
                attacker_choice.base_power = 40.0;
            } else if weight_ratio > 0.3335 {
                attacker_choice.base_power = 60.0;
            } else if weight_ratio >= 0.2501 {
                attacker_choice.base_power = 80.0;
            } else if weight_ratio >= 0.2001 {
                attacker_choice.base_power = 100.0;
            } else {
                attacker_choice.base_power = 120.0;
            }
        }
        _ => {}
    }
}

pub fn choice_after_damage_hit(
    state: &mut State,
    choice: &Choice,
    attacking_side_ref: &SideReference,
    instructions: &mut StateInstructions,
    hit_sub: bool,
) {
    let (attacking_side, defending_side) = state.get_both_sides(attacking_side_ref);
    let attacker_active = attacking_side.get_active();
    if choice.flags.recharge {
        let instruction = Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
            side_ref: attacking_side_ref.clone(),
            volatile_status: PokemonVolatileStatus::MUSTRECHARGE,
        });
        instructions.instruction_list.push(instruction);
        attacking_side
            .volatile_statuses
            .insert(PokemonVolatileStatus::MUSTRECHARGE);

    // Recharging and truant are mutually exclusive, with recharge taking priority
    } else if attacker_active.ability == Abilities::TRUANT {
        let instruction = Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
            side_ref: attacking_side_ref.clone(),
            volatile_status: PokemonVolatileStatus::TRUANT,
        });
        instructions.instruction_list.push(instruction);
        attacking_side
            .volatile_statuses
            .insert(PokemonVolatileStatus::TRUANT);
    }
    match choice.move_id {
        Choices::DOUBLESHOCK => {
            let attacker_active = attacking_side.get_active_immutable();
            let instruction = if attacker_active.types.0 == PokemonType::ELECTRIC {
                Some(Instruction::ChangeType(ChangeType {
                    side_ref: *attacking_side_ref,
                    new_types: (PokemonType::TYPELESS, attacker_active.types.1),
                    old_types: attacker_active.types,
                }))
            } else if attacker_active.types.1 == PokemonType::ELECTRIC {
                Some(Instruction::ChangeType(ChangeType {
                    side_ref: *attacking_side_ref,
                    new_types: (attacker_active.types.0, PokemonType::TYPELESS),
                    old_types: attacker_active.types,
                }))
            } else {
                None
            };
            if let Some(typechange_instruction) = instruction {
                if !attacking_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::TYPECHANGE)
                {
                    instructions
                        .instruction_list
                        .push(Instruction::ApplyVolatileStatus(
                            ApplyVolatileStatusInstruction {
                                side_ref: attacking_side_ref.clone(),
                                volatile_status: PokemonVolatileStatus::TYPECHANGE,
                            },
                        ));
                    attacking_side
                        .volatile_statuses
                        .insert(PokemonVolatileStatus::TYPECHANGE);
                }
                state.apply_one_instruction(&typechange_instruction);
                instructions.instruction_list.push(typechange_instruction);
            }
        }
        Choices::BURNUP => {
            let attacker_active = attacking_side.get_active_immutable();
            let instruction = if attacker_active.types.0 == PokemonType::FIRE {
                Some(Instruction::ChangeType(ChangeType {
                    side_ref: *attacking_side_ref,
                    new_types: (PokemonType::TYPELESS, attacker_active.types.1),
                    old_types: attacker_active.types,
                }))
            } else if attacker_active.types.1 == PokemonType::FIRE {
                Some(Instruction::ChangeType(ChangeType {
                    side_ref: *attacking_side_ref,
                    new_types: (attacker_active.types.0, PokemonType::TYPELESS),
                    old_types: attacker_active.types,
                }))
            } else {
                None
            };
            if let Some(typechange_instruction) = instruction {
                if !attacking_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::TYPECHANGE)
                {
                    instructions
                        .instruction_list
                        .push(Instruction::ApplyVolatileStatus(
                            ApplyVolatileStatusInstruction {
                                side_ref: attacking_side_ref.clone(),
                                volatile_status: PokemonVolatileStatus::TYPECHANGE,
                            },
                        ));
                    attacking_side
                        .volatile_statuses
                        .insert(PokemonVolatileStatus::TYPECHANGE);
                }
                state.apply_one_instruction(&typechange_instruction);
                instructions.instruction_list.push(typechange_instruction);
            }
        }
        // alpha-poke patch (2026-10-16, L27): Raging Bull's screen break is before the hit now
        // (generate_instructions::screen_break_instructions); it was here, after its damage
        Choices::KNOCKOFF => {
            let defender_active = defending_side.get_active();
            if defender_active.item_can_be_removed()
                && defender_active.item != Items::NONE
                && !hit_sub
            {
                let instruction = Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: attacking_side_ref.get_other_side(),
                    current_item: defender_active.item,
                    new_item: Items::NONE,
                });
                instructions.instruction_list.push(instruction);
                defender_active.item = Items::NONE;
            }
        }
        Choices::THIEF => {
            let attacker_active = attacking_side.get_active();
            let defender_active = defending_side.get_active();
            if defender_active.item_can_be_removed()
                && defender_active.item != Items::NONE
                && attacker_active.item == Items::NONE
                && !hit_sub
            {
                let defender_item = defender_active.item;

                let instruction = Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: attacking_side_ref.get_other_side(),
                    current_item: defender_item,
                    new_item: Items::NONE,
                });
                instructions.instruction_list.push(instruction);
                defender_active.item = Items::NONE;

                let instruction = Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: *attacking_side_ref,
                    current_item: Items::NONE,
                    new_item: defender_item,
                });
                instructions.instruction_list.push(instruction);
                attacker_active.item = defender_item;
            }
        }
        Choices::CLEARSMOG => {
            state.reset_boosts(
                &attacking_side_ref.get_other_side(),
                &mut instructions.instruction_list,
            );
        }
        Choices::ICESPINNER => {
            if state.terrain.terrain_type != Terrain::NONE && state.terrain.turns_remaining > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeTerrain(ChangeTerrain {
                        new_terrain: Terrain::NONE,
                        new_terrain_turns_remaining: 0,
                        previous_terrain: state.terrain.terrain_type,
                        previous_terrain_turns_remaining: state.terrain.turns_remaining,
                    }));
                state.terrain.terrain_type = Terrain::NONE;
                state.terrain.turns_remaining = 0;
            }
        }
        _ => {}
    }
}

#[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
fn destinybond_before_move(
    attacking_side: &mut Side,
    attacking_side_ref: &SideReference,
    choice: &Choice,
    instructions: &mut StateInstructions,
) {
    // gens 2-6 destinybond is only removed if you are not using destinybond
    // destinybond is preserved, even if used twice in a row
    if choice.move_id != Choices::DESTINYBOND
        && attacking_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::DESTINYBOND)
    {
        instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: *attacking_side_ref,
                    volatile_status: PokemonVolatileStatus::DESTINYBOND,
                },
            ));
        attacking_side
            .volatile_statuses
            .remove(&PokemonVolatileStatus::DESTINYBOND);
    }
}

#[cfg(any(
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
fn destinybond_before_move(
    attacking_side: &mut Side,
    attacking_side_ref: &SideReference,
    choice: &mut Choice,
    instructions: &mut StateInstructions,
) {
    // gens 7+ destinybond cannot be used if destinybond is active
    if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::DESTINYBOND)
    {
        instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: *attacking_side_ref,
                    volatile_status: PokemonVolatileStatus::DESTINYBOND,
                },
            ));
        attacking_side
            .volatile_statuses
            .remove(&PokemonVolatileStatus::DESTINYBOND);
        if choice.move_id == Choices::DESTINYBOND {
            choice.remove_all_effects();
        }
    }
}

pub fn choice_before_move(
    state: &mut State,
    choice: &mut Choice,
    attacking_side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let (attacking_side, defending_side) = state.get_both_sides(attacking_side_ref);

    destinybond_before_move(attacking_side, attacking_side_ref, choice, instructions);

    if attacking_side.get_active_immutable().status == PokemonStatus::FREEZE
        && CHOICE_THAWS_USER.contains(&choice.move_id)
    {
        add_remove_status_instructions(
            instructions,
            attacking_side.active_index,
            *attacking_side_ref,
            attacking_side,
        );
    }

    let attacker = attacking_side.get_active();
    let defender = defending_side.get_active_immutable();

    match choice.move_id {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L56): Doom Desire is a future move too
        // (it hit at once)
        Choices::FUTURESIGHT | Choices::DOOMDESIRE => {
            choice.remove_all_effects();
            if attacking_side.future_sight.0 == 0 {
                instructions
                    .instruction_list
                    .push(Instruction::SetFutureSight(SetFutureSightInstruction {
                        side_ref: *attacking_side_ref,
                        pokemon_index: attacking_side.active_index,
                        previous_pokemon_index: attacking_side.future_sight.1,
                    }));
                attacking_side.future_sight = (3, attacking_side.active_index);
            }
        }
        Choices::EXPLOSION | Choices::SELFDESTRUCT | Choices::MISTYEXPLOSION
            if defender.ability != Abilities::DAMP =>
        {
            let damage_amount = attacker.hp;
            instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *attacking_side_ref,
                    damage_amount,
                }));
            attacker.hp = 0;
        }
        Choices::MINDBLOWN if defender.ability != Abilities::DAMP => {
            let damage_amount = cmp::min(attacker.maxhp / 2, attacker.hp);
            instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *attacking_side_ref,
                    damage_amount,
                }));
            attacker.hp -= damage_amount;
        }
        Choices::METEORBEAM | Choices::ELECTROSHOT if choice.flags.charge => {
            apply_boost_instruction(
                attacking_side,
                &PokemonBoostableStat::SpecialAttack,
                &1,
                attacking_side_ref,
                attacking_side_ref,
                instructions,
            );
        }
        _ => {}
    }
    let attacking_side = state.get_side(attacking_side_ref);
    let attacker = attacking_side.get_active();
    if choice.flags.charge
        && attacker.item == Items::POWERHERB
        && choice.move_id != Choices::SKYDROP
    {
        let instruction = Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *attacking_side_ref,
            current_item: Items::POWERHERB,
            new_item: Items::NONE,
        });
        attacker.item = Items::NONE;
        choice.flags.charge = false;
        instructions.instruction_list.push(instruction);
    }
    if let Some(choice_volatile_status) = &choice.volatile_status {
        if choice_volatile_status.volatile_status == PokemonVolatileStatus::LOCKEDMOVE
            && choice_volatile_status.target == MoveTarget::User
        {
            let ins =
                get_choice_move_disable_instructions(attacker, attacking_side_ref, &choice.move_id);
            for i in ins {
                state.apply_one_instruction(&i);
                instructions.instruction_list.push(i);
            }
        }
    }
}

pub fn choice_hazard_clear(
    state: &mut State,
    choice: &Choice,
    attacking_side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    // L59: a move Protect blocked clears nothing (Rapid Spin, Mortal Spin, Defog)
    if choice.protected {
        return;
    }
    let (attacking_side, defending_side) = state.get_both_sides(attacking_side_ref);
    match choice.move_id {
        Choices::COURTCHANGE => {
            let mut instruction_list = vec![];
            let courtchange_swaps = [
                PokemonSideCondition::Stealthrock,
                PokemonSideCondition::Spikes,
                PokemonSideCondition::ToxicSpikes,
                PokemonSideCondition::StickyWeb,
                PokemonSideCondition::Reflect,
                PokemonSideCondition::LightScreen,
                PokemonSideCondition::AuroraVeil,
                PokemonSideCondition::Tailwind,
            ];

            for side in [SideReference::SideOne, SideReference::SideTwo] {
                for side_condition in courtchange_swaps {
                    let side_condition_num = state
                        .get_side_immutable(&side)
                        .get_side_condition(side_condition);
                    if side_condition_num > 0 {
                        instruction_list.push(Instruction::ChangeSideCondition(
                            ChangeSideConditionInstruction {
                                side_ref: side,
                                side_condition: side_condition,
                                amount: -1 * side_condition_num,
                            },
                        ));
                        instruction_list.push(Instruction::ChangeSideCondition(
                            ChangeSideConditionInstruction {
                                side_ref: side.get_other_side(),
                                side_condition: side_condition,
                                amount: side_condition_num,
                            },
                        ));
                    }
                }
            }
            state.apply_instructions(&instruction_list);
            for i in instruction_list {
                instructions.instruction_list.push(i)
            }
        }
        Choices::DEFOG
            if defending_side.get_active_immutable().ability != Abilities::GOODASGOLD =>
        {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L1): the target's evasion -1 first,
            // unless a substitute blocks it (Showdown's defog onHit; the engine's StatBoosts have
            // no evasion, so the move's data could not say it)
            // (L1b: a Defog Magic Bounce reflected targets its user: choice.target is User)
            let target_ref = if choice.target == MoveTarget::User {
                *attacking_side_ref
            } else {
                attacking_side_ref.get_other_side()
            };
            let target_side = state.get_side(&target_ref);
            if !target_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE)
            {
                apply_boost_instruction(
                    target_side,
                    &PokemonBoostableStat::Evasion,
                    &-1,
                    attacking_side_ref,
                    &target_ref,
                    instructions,
                );
            }
            if state.terrain.terrain_type != Terrain::NONE {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeTerrain(ChangeTerrain {
                        new_terrain: Terrain::NONE,
                        new_terrain_turns_remaining: 0,
                        previous_terrain: state.terrain.terrain_type,
                        previous_terrain_turns_remaining: state.terrain.turns_remaining,
                    }));
                state.terrain.terrain_type = Terrain::NONE;
                state.terrain.turns_remaining = 0;
            }
            let side_condition_clears = [
                PokemonSideCondition::Stealthrock,
                PokemonSideCondition::Spikes,
                PokemonSideCondition::ToxicSpikes,
                PokemonSideCondition::StickyWeb,
                PokemonSideCondition::Reflect,
                PokemonSideCondition::LightScreen,
                PokemonSideCondition::AuroraVeil,
            ];

            for side in [SideReference::SideOne, SideReference::SideTwo] {
                for side_condition in side_condition_clears {
                    let side_condition_num = state
                        .get_side_immutable(&side)
                        .get_side_condition(side_condition);
                    if side_condition_num > 0 {
                        let i = Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                            side_ref: side,
                            side_condition: side_condition,
                            amount: -1 * side_condition_num,
                        });
                        state.apply_one_instruction(&i);
                        instructions.instruction_list.push(i)
                    }
                }
            }
        }
        Choices::TIDYUP => {
            let side_condition_clears = [
                PokemonSideCondition::Stealthrock,
                PokemonSideCondition::Spikes,
                PokemonSideCondition::ToxicSpikes,
                PokemonSideCondition::StickyWeb,
            ];

            for side in [SideReference::SideOne, SideReference::SideTwo] {
                for side_condition in side_condition_clears {
                    let side_condition_num = state
                        .get_side_immutable(&side)
                        .get_side_condition(side_condition);
                    if side_condition_num > 0 {
                        let i = Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                            side_ref: side,
                            side_condition: side_condition,
                            amount: -1 * side_condition_num,
                        });
                        state.apply_one_instruction(&i);
                        instructions.instruction_list.push(i)
                    }
                }
            }
            if state
                .side_one
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE)
            {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSubstituteHealth(
                        ChangeSubsituteHealthInstruction {
                            side_ref: SideReference::SideOne,
                            health_change: -1 * state.side_one.substitute_health,
                        },
                    ));
                instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: SideReference::SideOne,
                            volatile_status: PokemonVolatileStatus::SUBSTITUTE,
                        },
                    ));
                state.side_one.substitute_health = 0;
                state
                    .side_one
                    .volatile_statuses
                    .remove(&PokemonVolatileStatus::SUBSTITUTE);
            }
            if state
                .side_two
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE)
            {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSubstituteHealth(
                        ChangeSubsituteHealthInstruction {
                            side_ref: SideReference::SideTwo,
                            health_change: -1 * state.side_two.substitute_health,
                        },
                    ));
                instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: SideReference::SideTwo,
                            volatile_status: PokemonVolatileStatus::SUBSTITUTE,
                        },
                    ));
                state.side_two.substitute_health = 0;
                state
                    .side_two
                    .volatile_statuses
                    .remove(&PokemonVolatileStatus::SUBSTITUTE);
            }
        }
        Choices::RAPIDSPIN | Choices::MORTALSPIN => {
            if attacking_side.side_conditions.stealth_rock > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: *attacking_side_ref,
                            side_condition: PokemonSideCondition::Stealthrock,
                            amount: -1 * attacking_side.side_conditions.stealth_rock,
                        },
                    ));
                attacking_side.side_conditions.stealth_rock = 0;
            }
            if attacking_side.side_conditions.spikes > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: *attacking_side_ref,
                            side_condition: PokemonSideCondition::Spikes,
                            amount: -1 * attacking_side.side_conditions.spikes,
                        },
                    ));
                attacking_side.side_conditions.spikes = 0;
            }
            if attacking_side.side_conditions.toxic_spikes > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: *attacking_side_ref,
                            side_condition: PokemonSideCondition::ToxicSpikes,
                            amount: -1 * attacking_side.side_conditions.toxic_spikes,
                        },
                    ));
                attacking_side.side_conditions.toxic_spikes = 0;
            }
            if attacking_side.side_conditions.sticky_web > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: *attacking_side_ref,
                            side_condition: PokemonSideCondition::StickyWeb,
                            amount: -1 * attacking_side.side_conditions.sticky_web,
                        },
                    ));
                attacking_side.side_conditions.sticky_web = 0;
            }
        }
        _ => {}
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L14): the fixed damage of Seismic Toss /
// Night Shade (the user's level), Super Fang / Nature's Madness / Ruination (half the target's HP,
// rounded down, at least 1) and Endeavor (the target's HP down to the user's), dealt as a damaging
// move's (generate_instructions_from_move: the accuracy, Protect, a Substitute, Sturdy / Endure);
// before, choice_special_effect took it off the target's HP before any of them (a miss, a Protect
// and a Substitute did not stop it). Some(0): no effect (an immune target, a failed Endeavor);
// None: not one of them, or blocked (Protect: a Status choice).
pub fn fixed_damage(
    state: &State,
    choice: &Choice,
    attacking_side_ref: &SideReference,
) -> Option<i16> {
    if choice.category == MoveCategory::Status {
        return None;
    }
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);
    let attacker = attacking_side.get_active_immutable();
    let defender = defending_side.get_active_immutable();
    let amount = match choice.move_id {
        Choices::SEISMICTOSS | Choices::NIGHTSHADE => attacker.level as i16,
        Choices::SUPERFANG | Choices::NATURESMADNESS | Choices::RUINATION => {
            cmp::max(defender.hp / 2, 1)
        }
        Choices::ENDEAVOR => cmp::max(defender.hp - attacker.hp, 0),
        _ => return None,
    };
    if type_effectiveness_modifier(&choice.move_type, defender) == 0.0 {
        return Some(0);
    }
    Some(amount)
}

fn effective_weight(pkmn: &Pokemon) -> f32 {
    if pkmn.item == Items::FLOATSTONE {
        pkmn.weight_kg / 2.0
    } else {
        pkmn.weight_kg
    }
}

pub fn choice_special_effect(
    state: &mut State,
    choice: &mut Choice,
    attacking_side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L73): Stockpile's layer (at most 3) and its
    // Defense / Sp. Def +1; Spit Up / Swallow use the layers up with their boosts
    if matches!(
        choice.move_id,
        Choices::STOCKPILE | Choices::SPITUP | Choices::SWALLOW
    ) {
        let side = state.get_side(attacking_side_ref);
        let layers = side.volatile_status_durations.stockpile;
        let (change, boost) = match choice.move_id {
            Choices::STOCKPILE if layers < 3 => (1, 1),
            Choices::STOCKPILE => (0, 0),
            _ => (-layers, -layers),
        };
        if change != 0 {
            side.volatile_status_durations.stockpile += change;
            instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: *attacking_side_ref,
                        volatile_status: PokemonVolatileStatus::STOCKPILE,
                        amount: change,
                    },
                ));
            for stat in [
                PokemonBoostableStat::Defense,
                PokemonBoostableStat::SpecialDefense,
            ] {
                apply_boost_instruction(
                    side,
                    &stat,
                    &boost,
                    attacking_side_ref,
                    attacking_side_ref,
                    instructions,
                );
            }
            if layers + change == 0
                && side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::STOCKPILE)
            {
                side.volatile_statuses
                    .remove(&PokemonVolatileStatus::STOCKPILE);
                instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: *attacking_side_ref,
                            volatile_status: PokemonVolatileStatus::STOCKPILE,
                        },
                    ));
            }
        }
        if choice.move_id == Choices::STOCKPILE && layers >= 3 {
            choice.volatile_status = None;
        }
    }
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L36): Transform (no effect before)
    if choice.move_id == Choices::TRANSFORM {
        super::generate_instructions::transform_into(state, attacking_side_ref, instructions);
        return;
    }
    let (attacking_side, defending_side) = state.get_both_sides(attacking_side_ref);
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L16b): a move Protect blocks does nothing
    // here either (Pain Split, Trick / Switcheroo, Counter / Mirror Coat, ...); before, these
    // effects went through it
    if choice.flags.protect
        && [
            PokemonVolatileStatus::PROTECT,
            PokemonVolatileStatus::SPIKYSHIELD,
            PokemonVolatileStatus::BANEFULBUNKER,
            PokemonVolatileStatus::BURNINGBULWARK,
            PokemonVolatileStatus::SILKTRAP,
        ]
        .iter()
        .any(|v| defending_side.volatile_statuses.contains(v))
    {
        return;
    }
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L20): nor does a status move Good as Gold
    // blocks (ability_modify_attack_against removes a move's data effects, not these): the ones
    // here aimed at the target -- Trick / Switcheroo, Pain Split; not the field moves (Trick
    // Room, weather, Haze, Perish Song), whose data target is "Opponent" too (the first version
    // blocked Trick Room: test_control_trick_room_against_good_as_gold). The same conditions as
    // there: no Mold Breaker-like ability, no Neutralizing Gas
    let attacker = attacking_side.get_active_immutable();
    let breaks_ability = matches!(
        attacker.ability,
        Abilities::MOLDBREAKER
            | Abilities::TERAVOLT
            | Abilities::TURBOBLAZE
            | Abilities::MYCELIUMMIGHT
            | Abilities::NEUTRALIZINGGAS
    );
    if defending_side.get_active_immutable().ability == Abilities::GOODASGOLD
        && !breaks_ability
        && matches!(
            choice.move_id,
            Choices::TRICK | Choices::SWITCHEROO | Choices::PAINSPLIT
        )
    {
        return;
    }
    match choice.move_id {
        Choices::BELLYDRUM => {
            let boost_amount = 6 - attacking_side.attack_boost;
            let attacker = attacking_side.get_active();
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L49): fails at +6 too
            if attacker.hp > attacker.maxhp / 2 && boost_amount > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: *attacking_side_ref,
                        damage_amount: attacker.maxhp / 2,
                    }));
                instructions
                    .instruction_list
                    .push(Instruction::Boost(BoostInstruction {
                        side_ref: *attacking_side_ref,
                        stat: PokemonBoostableStat::Attack,
                        amount: boost_amount,
                    }));
                attacker.hp -= attacker.maxhp / 2;
                attacking_side.attack_boost = 6;
            }
        }
        Choices::COUNTER => {
            if defending_side.damage_dealt.move_category == MoveCategory::Physical
                && !defending_side
                    .get_active_immutable()
                    .has_type(&PokemonType::GHOST)
            {
                let damage_amount = cmp::min(
                    defending_side.damage_dealt.damage * 2,
                    defending_side.get_active_immutable().hp,
                );
                if damage_amount > 0 {
                    instructions
                        .instruction_list
                        .push(Instruction::Damage(DamageInstruction {
                            side_ref: attacking_side_ref.get_other_side(),
                            damage_amount: damage_amount,
                        }));
                    defending_side.get_active().hp -= damage_amount;
                }
            }
        }
        Choices::MIRRORCOAT => {
            if defending_side.damage_dealt.move_category == MoveCategory::Special
                && !defending_side
                    .get_active_immutable()
                    .has_type(&PokemonType::DARK)
            {
                let damage_amount = cmp::min(
                    defending_side.damage_dealt.damage * 2,
                    defending_side.get_active_immutable().hp,
                );
                if damage_amount > 0 {
                    instructions
                        .instruction_list
                        .push(Instruction::Damage(DamageInstruction {
                            side_ref: attacking_side_ref.get_other_side(),
                            damage_amount: damage_amount,
                        }));
                    defending_side.get_active().hp -= damage_amount;
                }
            }
        }
        Choices::METALBURST | Choices::COMEUPPANCE => {
            if defending_side.damage_dealt.move_category != MoveCategory::Status
                && !defending_side.damage_dealt.hit_substitute
                && !choice.first_move
            {
                let damage_amount = cmp::min(
                    (defending_side.damage_dealt.damage * 3) / 2,
                    defending_side.get_active_immutable().hp,
                );
                if damage_amount > 0 {
                    instructions
                        .instruction_list
                        .push(Instruction::Damage(DamageInstruction {
                            side_ref: attacking_side_ref.get_other_side(),
                            damage_amount: damage_amount,
                        }));
                    defending_side.get_active().hp -= damage_amount;
                }
            }
        }
        Choices::WISH => {
            if attacking_side.wish.0 == 0 {
                let previous_wish_amount = attacking_side.wish.1;
                instructions.instruction_list.push(Instruction::ChangeWish(
                    ChangeWishInstruction {
                        side_ref: *attacking_side_ref,
                        wish_amount_change: attacking_side.get_active_immutable().maxhp / 2
                            - previous_wish_amount,
                    },
                ));
                attacking_side.wish = (2, attacking_side.get_active_immutable().maxhp / 2);
            }
        }
        // (L66: Take Heart cures its status too)
        Choices::REFRESH | Choices::TAKEHEART => {
            let active_index = attacking_side.active_index;
            let active_pkmn = attacking_side.get_active();
            if active_pkmn.status != PokemonStatus::NONE {
                add_remove_status_instructions(
                    instructions,
                    active_index,
                    *attacking_side_ref,
                    attacking_side,
                );
            }
        }
        Choices::HEALBELL | Choices::AROMATHERAPY => {
            for pkmn_index in pokemon_index_iter() {
                if attacking_side.pokemon[pkmn_index].status != PokemonStatus::NONE {
                    add_remove_status_instructions(
                        instructions,
                        pkmn_index,
                        *attacking_side_ref,
                        attacking_side,
                    );
                }
            }
        }
        Choices::HAZE => {
            state.reset_boosts(&SideReference::SideOne, &mut instructions.instruction_list);
            state.reset_boosts(&SideReference::SideTwo, &mut instructions.instruction_list);
        }
        Choices::REST => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L38): Showdown's onTry (fails at
            // full HP, asleep, Insomnia / Vital Spirit / Comatose) and setStatus (Electric /
            // Misty Terrain on a grounded user, Purifying Salt, Sweet Veil, Leaf Guard in sun);
            // before, only asleep and Electric Terrain
            let sleep_terrain = state.terrain_is_active(&Terrain::ELECTRICTERRAIN)
                || state.terrain_is_active(&Terrain::MISTYTERRAIN);
            let sun = state.weather_is_active(&Weather::SUN)
                || state.weather_is_active(&Weather::HARSHSUN);
            let attacking_side = state.get_side(attacking_side_ref);
            let active_index = attacking_side.active_index;
            let active_pkmn = attacking_side.get_active();
            let blocked = active_pkmn.hp >= active_pkmn.maxhp
                || (sleep_terrain && active_pkmn.is_grounded())
                || matches!(
                    active_pkmn.ability,
                    Abilities::INSOMNIA
                        | Abilities::VITALSPIRIT
                        | Abilities::COMATOSE
                        | Abilities::PURIFYINGSALT
                        | Abilities::SWEETVEIL
                )
                || (active_pkmn.ability == Abilities::LEAFGUARD && sun);
            if active_pkmn.status != PokemonStatus::SLEEP && !blocked {
                let heal_amount = active_pkmn.maxhp - active_pkmn.hp;
                instructions
                    .instruction_list
                    .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: *attacking_side_ref,
                        pokemon_index: active_index,
                        old_status: active_pkmn.status,
                        new_status: PokemonStatus::SLEEP,
                    }));
                instructions
                    .instruction_list
                    .push(Instruction::SetRestTurns(SetSleepTurnsInstruction {
                        side_ref: *attacking_side_ref,
                        pokemon_index: active_index,
                        new_turns: 3,
                        previous_turns: active_pkmn.rest_turns,
                    }));
                instructions
                    .instruction_list
                    .push(Instruction::Heal(HealInstruction {
                        side_ref: *attacking_side_ref,
                        heal_amount,
                    }));
                active_pkmn.hp = active_pkmn.maxhp;
                active_pkmn.status = PokemonStatus::SLEEP;
                active_pkmn.rest_turns = 3;
                super::items::rest_berry(attacking_side_ref, attacking_side, instructions);
            }
        }
        Choices::TRICKROOM => {
            let new_turns_remaining;
            if state.trick_room.active {
                new_turns_remaining = 0;
            } else {
                new_turns_remaining = 5;
            }
            instructions
                .instruction_list
                .push(Instruction::ToggleTrickRoom(ToggleTrickRoomInstruction {
                    currently_active: state.trick_room.active,
                    new_trickroom_turns_remaining: new_turns_remaining,
                    previous_trickroom_turns_remaining: state.trick_room.turns_remaining,
                }));
            state.trick_room.active = !state.trick_room.active;
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Room Service on either side
            room_service(state, attacking_side_ref, instructions);
            room_service(state, &attacking_side_ref.get_other_side(), instructions);
        }
        Choices::FINALGAMBIT => {
            let (attacking_side, defending_side) = state.get_both_sides(attacking_side_ref);
            let attacker = attacking_side.get_active();
            let defender = defending_side.get_active();

            if type_effectiveness_modifier(&PokemonType::NORMAL, &defender) == 0.0 {
                return;
            }

            let damage_amount = attacker.hp;
            instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: attacking_side_ref.get_other_side(),
                    damage_amount: damage_amount,
                }));
            defender.hp -= damage_amount;

            instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *attacking_side_ref,
                    damage_amount: attacker.hp,
                }));
            attacker.hp = 0;
        }
        Choices::PAINSPLIT => {
            if !defending_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE)
            {
                let target_hp = (attacking_side.get_active_immutable().hp
                    + defending_side.get_active_immutable().hp)
                    / 2;
                // alpha-poke patch (2026-10-16, doc/engine-diff.md L16a): each at most its max HP
                // (Showdown's sethp); before, the user could go above it
                let user_hp = cmp::min(target_hp, attacking_side.get_active_immutable().maxhp);
                let foe_hp = cmp::min(target_hp, defending_side.get_active_immutable().maxhp);
                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: *attacking_side_ref,
                        damage_amount: attacking_side.get_active_immutable().hp - user_hp,
                    }));
                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: attacking_side_ref.get_other_side(),
                        damage_amount: defending_side.get_active_immutable().hp - foe_hp,
                    }));

                attacking_side.get_active().hp = user_hp;
                defending_side.get_active().hp = foe_hp;
            }
        }
        Choices::SUBSTITUTE | Choices::SHEDTAIL => {
            if attacking_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE)
            {
                return;
            }
            let sub_current_health = attacking_side.substitute_health;
            let active_pkmn = attacking_side.get_active();
            let sub_target_health = active_pkmn.maxhp / 4;
            let pkmn_health_reduction = if choice.move_id == Choices::SHEDTAIL {
                active_pkmn.maxhp / 2
            } else {
                sub_target_health
            };
            if active_pkmn.hp > pkmn_health_reduction {
                if choice.move_id == Choices::SHEDTAIL {
                    choice.flags.pivot = true;
                }

                let damage_instruction = Instruction::Damage(DamageInstruction {
                    side_ref: attacking_side_ref.clone(),
                    damage_amount: pkmn_health_reduction,
                });
                let set_sub_health_instruction =
                    Instruction::ChangeSubstituteHealth(ChangeSubsituteHealthInstruction {
                        side_ref: attacking_side_ref.clone(),
                        health_change: sub_target_health - sub_current_health,
                    });
                let apply_vs_instruction =
                    Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
                        side_ref: attacking_side_ref.clone(),
                        volatile_status: PokemonVolatileStatus::SUBSTITUTE,
                    });
                active_pkmn.hp -= pkmn_health_reduction;
                attacking_side.substitute_health = sub_target_health;
                attacking_side
                    .volatile_statuses
                    .insert(PokemonVolatileStatus::SUBSTITUTE);
                instructions.instruction_list.push(damage_instruction);
                instructions
                    .instruction_list
                    .push(set_sub_health_instruction);
                instructions.instruction_list.push(apply_vs_instruction);
            }
        }
        Choices::PERISHSONG => {
            for side_ref in [SideReference::SideOne, SideReference::SideTwo] {
                let side = state.get_side(&side_ref);
                let pkmn = side.get_active();
                if pkmn.hp != 0
                    && pkmn.ability != Abilities::SOUNDPROOF
                    && !(side
                        .volatile_statuses
                        .contains(&PokemonVolatileStatus::PERISH4)
                        || side
                            .volatile_statuses
                            .contains(&PokemonVolatileStatus::PERISH3)
                        || side
                            .volatile_statuses
                            .contains(&PokemonVolatileStatus::PERISH2)
                        || side
                            .volatile_statuses
                            .contains(&PokemonVolatileStatus::PERISH1))
                {
                    instructions
                        .instruction_list
                        .push(Instruction::ApplyVolatileStatus(
                            ApplyVolatileStatusInstruction {
                                side_ref: side_ref,
                                volatile_status: PokemonVolatileStatus::PERISH4,
                            },
                        ));
                    side.volatile_statuses
                        .insert(PokemonVolatileStatus::PERISH4);
                }
            }
        }
        Choices::TRICK | Choices::SWITCHEROO => {
            let defender_has_sub = defending_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE);
            let attacker = attacking_side.get_active();
            let defender = defending_side.get_active();
            let attacker_item = attacker.item;
            let defender_item = defender.item;
            if attacker_item == defender_item || !defender.item_can_be_removed() || defender_has_sub
            {
                return;
            }
            let change_attacker_item_instruction = Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: *attacking_side_ref,
                current_item: attacker_item,
                new_item: defender_item,
            });
            let change_defender_item_instruction = Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: attacking_side_ref.get_other_side(),
                current_item: defender_item,
                new_item: attacker_item,
            });
            attacker.item = defender_item;
            defender.item = attacker_item;
            instructions
                .instruction_list
                .push(change_attacker_item_instruction);
            instructions
                .instruction_list
                .push(change_defender_item_instruction);
        }
        Choices::SUNNYDAY => {
            if state.weather.weather_type != Weather::SUN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::SUN,
                        new_weather_turns_remaining: 5,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::SUN;
                state.weather.turns_remaining = 5;
            }
        }
        Choices::RAINDANCE => {
            if state.weather.weather_type != Weather::RAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::RAIN,
                        new_weather_turns_remaining: 5,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::RAIN;
                state.weather.turns_remaining = 5;
            }
        }
        Choices::SANDSTORM => {
            if state.weather.weather_type != Weather::SAND {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::SAND,
                        new_weather_turns_remaining: 5,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::SAND;
                state.weather.turns_remaining = 5;
            }
        }
        Choices::HAIL => {
            if state.weather.weather_type != Weather::HAIL {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::HAIL,
                        new_weather_turns_remaining: 5,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::HAIL;
                state.weather.turns_remaining = 5;
            }
        }
        Choices::SNOWSCAPE | Choices::CHILLYRECEPTION => {
            if state.weather.weather_type != Weather::SNOW {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::SNOW,
                        new_weather_turns_remaining: 5,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::SNOW;
                state.weather.turns_remaining = 5;
            }
        }
        _ => {}
    }
}

pub fn charge_choice_to_volatile(choice: &Choices) -> PokemonVolatileStatus {
    match choice {
        Choices::BOUNCE => PokemonVolatileStatus::BOUNCE,
        Choices::DIG => PokemonVolatileStatus::DIG,
        Choices::DIVE => PokemonVolatileStatus::DIVE,
        Choices::FLY => PokemonVolatileStatus::FLY,
        Choices::FREEZESHOCK => PokemonVolatileStatus::FREEZESHOCK,
        Choices::GEOMANCY => PokemonVolatileStatus::GEOMANCY,
        Choices::ICEBURN => PokemonVolatileStatus::ICEBURN,
        Choices::METEORBEAM => PokemonVolatileStatus::METEORBEAM,
        Choices::ELECTROSHOT => PokemonVolatileStatus::ELECTROSHOT,
        Choices::PHANTOMFORCE => PokemonVolatileStatus::PHANTOMFORCE,
        Choices::RAZORWIND => PokemonVolatileStatus::RAZORWIND,
        Choices::SHADOWFORCE => PokemonVolatileStatus::SHADOWFORCE,
        Choices::SKULLBASH => PokemonVolatileStatus::SKULLBASH,
        Choices::SKYATTACK => PokemonVolatileStatus::SKYATTACK,
        Choices::SKYDROP => PokemonVolatileStatus::SKYDROP,
        Choices::SOLARBEAM => PokemonVolatileStatus::SOLARBEAM,
        Choices::SOLARBLADE => PokemonVolatileStatus::SOLARBLADE,
        _ => {
            panic!("Invalid choice for charge: {:?}", choice)
        }
    }
}
