use super::abilities::{
    ability_after_damage_hit, ability_before_move, ability_end_of_turn,
    ability_modify_attack_against, ability_modify_attack_being_used, ability_on_switch_in,
    ability_on_switch_out, Abilities,
};
use super::choice_effects::{
    charge_choice_to_volatile, choice_after_damage_hit, choice_before_move, choice_hazard_clear,
    choice_special_effect, fixed_damage, modify_choice,
};
use crate::choices::{
    Boost, Choices, Effect, Heal, MoveTarget, MultiHitMove, Secondary, SideCondition, StatBoosts,
    Status, VolatileStatus, MOVES,
};
use crate::instruction::EnableMoveInstruction;
use crate::instruction::{
    ApplyVolatileStatusInstruction, BoostInstruction, ChangeDamageDealtDamageInstruction,
    ChangeDamageDealtMoveCategoryInstruction, ChangeItemInstruction,
    ChangeSideConditionInstruction, ChangeTerrain, ChangeType,
    ChangeVolatileStatusDurationInstruction, ChangeWeather, DecrementRestTurnsInstruction,
    DecrementWishInstruction, HealInstruction, RemoveVolatileStatusInstruction,
    SetSecondMoveSwitchOutMoveInstruction, SetSleepTurnsInstruction, ToggleBatonPassingInstruction,
    ToggleDamageDealtHitSubstituteInstruction, ToggleMegaEvolvedInstruction,
    ToggleShedTailingInstruction, ToggleTrickRoomInstruction,
};
use crate::instruction::{ChangeAbilityInstruction, ToggleTerastallizedInstruction};
use crate::instruction::{ChangeMoveInstruction, ChangeStatInstruction, DisableMoveInstruction};
use crate::instruction::{DecrementFutureSightInstruction, FormeChangeInstruction};
use crate::instruction::{DecrementPPInstruction, SetLastUsedMoveInstruction};

use super::damage_calc::calculate_futuresight_damage;
use super::damage_calc::{
    calculate_damage, damage_rolls, type_effectiveness_modifier, DamageRolls,
};
use super::items::{
    is_berry, item_before_move, item_end_of_turn, item_modify_attack_against,
    item_modify_attack_being_used, item_on_switch_in, set_last_item, Items,
};
use super::state::{MoveChoice, PokemonVolatileStatus, Terrain, Weather};
use crate::choices::{Choice, MoveCategory};
use crate::instruction::{
    ChangeStatusInstruction, DamageInstruction, Instruction, StateInstructions, SwitchInstruction,
};
use crate::pokemon::PokemonName;
use crate::state::{
    LastUsedMove, PokemonBoostableStat, PokemonIndex, PokemonMoveIndex, PokemonSideCondition,
    PokemonStatus, PokemonType, Side, SideMovesFirst, SideReference, State,
};
use std::cmp;

#[cfg(feature = "terastallization")]
use crate::choices::MultiAccuracyMove;

#[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
pub const BASE_CRIT_CHANCE: f32 = 1.0 / 16.0;

#[cfg(any(
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const BASE_CRIT_CHANCE: f32 = 1.0 / 24.0;

#[cfg(any(feature = "gen4"))]
pub const MAX_SLEEP_TURNS: i8 = 4;

#[cfg(any(
    feature = "gen5",
    feature = "gen6",
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
))]
pub const MAX_SLEEP_TURNS: i8 = 3;

#[cfg(feature = "champions")]
pub const MAX_SLEEP_TURNS: i8 = 2;

#[cfg(not(feature = "champions"))]
pub const THAW_CHANCE: f32 = 0.20;

#[cfg(feature = "champions")]
pub const THAW_CHANCE: f32 = 0.25;

#[cfg(not(feature = "champions"))]
pub const FULLY_PARALYZED_CHANCE: f32 = 0.25;

#[cfg(feature = "champions")]
pub const FULLY_PARALYZED_CHANCE: f32 = 0.125;

#[cfg(any(
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const HIT_SELF_IN_CONFUSION_CHANCE: f32 = 1.0 / 3.0;

#[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
pub const HIT_SELF_IN_CONFUSION_CHANCE: f32 = 1.0 / 2.0;

#[cfg(any(
    feature = "gen5",
    feature = "gen6",
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const CONSECUTIVE_PROTECT_CHANCE: f32 = 1.0 / 3.0;

#[cfg(any(feature = "gen4"))]
pub const CONSECUTIVE_PROTECT_CHANCE: f32 = 1.0 / 2.0;

#[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
pub const PARALYSIS_SPEED_MULTIPLIER: f32 = 0.25;

#[cfg(any(
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const PARALYSIS_SPEED_MULTIPLIER: f32 = 0.5;

#[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
pub const BURN_RESIDUAL_DAMAGE_PCT: f32 = 0.125;

#[cfg(any(
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const BURN_RESIDUAL_DAMAGE_PCT: f32 = 0.0625;

#[cfg(any(feature = "gen4", feature = "gen5"))]
pub const PARTIALLY_TRAPPED_DAMAGE_PCT: f32 = 0.0625;

#[cfg(any(
    feature = "gen6",
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const PARTIALLY_TRAPPED_DAMAGE_PCT: f32 = 0.125;

#[cfg(not(feature = "champions"))]
pub const SALT_CURE_DAMAGE_DIVISOR: f32 = 8.0;

#[cfg(feature = "champions")]
pub const SALT_CURE_DAMAGE_DIVISOR: f32 = 16.0;

pub const SIDE_CONDITION_DURATION: i8 = 5;
pub const TAILWIND_DURATION: i8 = 4;

const PROTECT_VOLATILES: [PokemonVolatileStatus; 6] = [
    PokemonVolatileStatus::PROTECT,
    PokemonVolatileStatus::BANEFULBUNKER,
    PokemonVolatileStatus::BURNINGBULWARK,
    PokemonVolatileStatus::SPIKYSHIELD,
    PokemonVolatileStatus::SILKTRAP,
    PokemonVolatileStatus::ENDURE,
];

/// alpha-poke patch: the chance a confusion with ``confused_attempts`` confused move attempts
/// so far has ended at this attempt (1-4 confused attempts, uniform: 0, 1/4, 1/3, 1/2, 1).
fn confusion_end_chance(confused_attempts: i8) -> f32 {
    match confused_attempts {
        0 => 0.0,
        1..=3 => 1.0 / (5 - confused_attempts) as f32,
        _ => 1.0,
    }
}

#[cfg(not(feature = "champions"))]
fn chance_to_wake_up(turns_asleep: i8) -> f32 {
    if turns_asleep == 0 {
        0.0
    } else {
        1.0 / (1 + MAX_SLEEP_TURNS - turns_asleep) as f32
    }
}

#[cfg(feature = "champions")]
fn chance_to_wake_up(turns_asleep: i8) -> f32 {
    match turns_asleep {
        0 => 0.0,
        1 => 0.333,
        2 => 1.0,
        _ => panic!("turns_asleep should never be above 2 when calculating wake up chance"),
    }
}

fn set_last_used_move_as_switch(
    side: &mut Side,
    new_pokemon_index: PokemonIndex,
    switching_side_ref: SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    incoming_instructions
        .instruction_list
        .push(Instruction::SetLastUsedMove(SetLastUsedMoveInstruction {
            side_ref: switching_side_ref,
            last_used_move: LastUsedMove::Switch(new_pokemon_index),
            previous_last_used_move: side.last_used_move,
        }));
    side.last_used_move = LastUsedMove::Switch(new_pokemon_index);
}

fn set_last_used_move_as_move(
    side: &mut Side,
    used_move: PokemonMoveIndex,
    switching_side_ref: SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::FLINCH)
    {
        // if we were flinched after just switching in we don't want our last used move to be switch
        // this makes sure fakeout/firstimpression can't be used on the following turn
        if matches!(side.last_used_move, LastUsedMove::Switch(_)) {
            incoming_instructions
                .instruction_list
                .push(Instruction::SetLastUsedMove(SetLastUsedMoveInstruction {
                    side_ref: switching_side_ref,
                    last_used_move: LastUsedMove::None,
                    previous_last_used_move: side.last_used_move,
                }));
            side.last_used_move = LastUsedMove::None;
        }
        return;
    }
    match side.last_used_move {
        LastUsedMove::Move(last_used_move) => {
            if last_used_move == used_move {
                return;
            }
        }
        _ => {}
    }
    incoming_instructions
        .instruction_list
        .push(Instruction::SetLastUsedMove(SetLastUsedMoveInstruction {
            side_ref: switching_side_ref,
            last_used_move: LastUsedMove::Move(used_move),
            previous_last_used_move: side.last_used_move,
        }));
    side.last_used_move = LastUsedMove::Move(used_move);
}

fn generate_instructions_from_switch(
    state: &mut State,
    new_pokemon_index: PokemonIndex,
    switching_side_ref: SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    let should_last_used_move = state.use_last_used_move;

    let (side, opposite_side) = state.get_both_sides(&switching_side_ref);
    if side.force_switch {
        side.force_switch = false;
        match switching_side_ref {
            SideReference::SideOne => {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ToggleSideOneForceSwitch);
            }
            SideReference::SideTwo => {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ToggleSideTwoForceSwitch);
            }
        }
    }

    let mut baton_passing = false;
    if side.baton_passing {
        baton_passing = true;
        side.baton_passing = false;
        match switching_side_ref {
            SideReference::SideOne => {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ToggleBatonPassing(
                        ToggleBatonPassingInstruction {
                            side_ref: SideReference::SideOne,
                        },
                    ));
            }
            SideReference::SideTwo => {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ToggleBatonPassing(
                        ToggleBatonPassingInstruction {
                            side_ref: SideReference::SideTwo,
                        },
                    ));
            }
        }
    }

    let mut shed_tailing = false;
    if side.shed_tailing {
        shed_tailing = true;
        side.shed_tailing = false;
        match switching_side_ref {
            SideReference::SideOne => {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ToggleShedTailing(
                        ToggleShedTailingInstruction {
                            side_ref: SideReference::SideOne,
                        },
                    ));
            }
            SideReference::SideTwo => {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ToggleShedTailing(
                        ToggleShedTailingInstruction {
                            side_ref: SideReference::SideTwo,
                        },
                    ));
            }
        }
    }

    #[cfg(feature = "gen5")]
    if side.get_active_immutable().status == PokemonStatus::SLEEP {
        let current_active_index = side.active_index;
        let active = side.get_active();
        if active.rest_turns > 0 {
            let current_rest_turns = active.rest_turns;
            incoming_instructions
                .instruction_list
                .push(Instruction::SetRestTurns(SetSleepTurnsInstruction {
                    side_ref: switching_side_ref,
                    pokemon_index: current_active_index,
                    new_turns: 3,
                    previous_turns: current_rest_turns,
                }));
            active.rest_turns = 3
        } else {
            let current_sleep_turns = active.sleep_turns;
            incoming_instructions
                .instruction_list
                .push(Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                    side_ref: switching_side_ref,
                    pokemon_index: current_active_index,
                    new_turns: 0,
                    previous_turns: current_sleep_turns,
                }));
            active.sleep_turns = 0
        }
    }

    if opposite_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PARTIALLYTRAPPED)
    {
        incoming_instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: switching_side_ref.get_other_side(),
                    volatile_status: PokemonVolatileStatus::PARTIALLYTRAPPED,
                },
            ));
        opposite_side
            .volatile_statuses
            .remove(&PokemonVolatileStatus::PARTIALLYTRAPPED);
        // alpha-poke patch (2026-10-16): its turn count ends with it
        let elapsed = opposite_side.volatile_status_durations.partiallytrapped;
        if elapsed != 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: switching_side_ref.get_other_side(),
                        volatile_status: PokemonVolatileStatus::PARTIALLYTRAPPED,
                        amount: -elapsed,
                    },
                ));
            opposite_side.volatile_status_durations.partiallytrapped = 0;
        }
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L107): the trapper leaves, its Mean Look
    // / Block on the opponent ends
    let opposite_side = state.get_side(&switching_side_ref.get_other_side());
    if opposite_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::TRAPPED)
    {
        opposite_side
            .volatile_statuses
            .remove(&PokemonVolatileStatus::TRAPPED);
        incoming_instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: switching_side_ref.get_other_side(),
                    volatile_status: PokemonVolatileStatus::TRAPPED,
                },
            ));
    }

    state.re_enable_disabled_moves(
        &switching_side_ref,
        &mut incoming_instructions.instruction_list,
    );
    state.remove_volatile_statuses_on_switch(
        &switching_side_ref,
        &mut incoming_instructions.instruction_list,
        baton_passing,
        shed_tailing,
    );
    state.reset_toxic_count(
        &switching_side_ref,
        &mut incoming_instructions.instruction_list,
    );
    if !baton_passing {
        state.reset_boosts(
            &switching_side_ref,
            &mut incoming_instructions.instruction_list,
        );
    }

    ability_on_switch_out(state, &switching_side_ref, incoming_instructions);

    let switch_instruction = Instruction::Switch(SwitchInstruction {
        side_ref: switching_side_ref,
        previous_index: state.get_side(&switching_side_ref).active_index,
        next_index: new_pokemon_index,
    });

    let side = state.get_side(&switching_side_ref);
    side.active_index = new_pokemon_index;
    incoming_instructions
        .instruction_list
        .push(switch_instruction);

    if should_last_used_move {
        set_last_used_move_as_switch(
            side,
            new_pokemon_index,
            switching_side_ref,
            incoming_instructions,
        );
    }

    if side.side_conditions.healing_wish > 0 {
        #[cfg(any(feature = "gen8", feature = "gen9", feature = "champions"))]
        let mut healing_wish_consumed = false;

        #[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6", feature = "gen7"))]
        let mut healing_wish_consumed = true;

        let switched_in_pkmn = side.get_active();
        if switched_in_pkmn.hp < switched_in_pkmn.maxhp {
            let heal_amount = switched_in_pkmn.maxhp - switched_in_pkmn.hp;
            let heal_instruction = Instruction::Heal(HealInstruction {
                side_ref: switching_side_ref,
                heal_amount,
            });
            incoming_instructions
                .instruction_list
                .push(heal_instruction);
            switched_in_pkmn.hp += heal_amount;
            healing_wish_consumed = true;
        }
        if switched_in_pkmn.status != PokemonStatus::NONE {
            add_remove_status_instructions(
                incoming_instructions,
                new_pokemon_index,
                switching_side_ref,
                side,
            );
            healing_wish_consumed = true;
        }

        if healing_wish_consumed {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: switching_side_ref,
                        side_condition: PokemonSideCondition::HealingWish,
                        amount: -1 * side.side_conditions.healing_wish,
                    },
                ));
            side.side_conditions.healing_wish = 0;
        }
    }

    let active = side.get_active_immutable();
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L96): a grounded Poison type absorbs Toxic
    // Spikes with Heavy-Duty Boots too (Showdown checks the type before the boots)
    if active.item == Items::HEAVYDUTYBOOTS
        && side.side_conditions.toxic_spikes > 0
        && active.is_grounded()
        && active.has_type(&PokemonType::POISON)
    {
        let i = Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
            side_ref: switching_side_ref,
            side_condition: PokemonSideCondition::ToxicSpikes,
            amount: -1 * side.side_conditions.toxic_spikes,
        });
        state.apply_one_instruction(&i);
        incoming_instructions.instruction_list.push(i);
    }
    let side = state.get_side(&switching_side_ref);
    let active = side.get_active_immutable();
    if active.item != Items::HEAVYDUTYBOOTS {
        let switched_in_pkmn = side.get_active_immutable();
        if side.side_conditions.sticky_web == 1 && switched_in_pkmn.is_grounded() {
            // a pkmn switching in doesn't have any other speed drops,
            // so no need to check for going below -6
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L76): the foe's drop (Clear Body
            // stops it, Defiant answers it); was its own
            apply_boost_instruction(
                side,
                &PokemonBoostableStat::Speed,
                &-1,
                &switching_side_ref.get_other_side(),
                &switching_side_ref,
                incoming_instructions,
            );
        }

        let side = state.get_side_immutable(&switching_side_ref);
        let switched_in_pkmn = side.get_active_immutable();
        let mut toxic_spike_instruction: Option<Instruction> = None;
        if side.side_conditions.toxic_spikes > 0 && switched_in_pkmn.is_grounded() {
            if !immune_to_status(
                &state,
                &MoveTarget::User,
                &switching_side_ref,
                &PokemonStatus::POISON,
            ) {
                if side.side_conditions.toxic_spikes == 1 {
                    toxic_spike_instruction =
                        Some(Instruction::ChangeStatus(ChangeStatusInstruction {
                            side_ref: switching_side_ref,
                            pokemon_index: side.active_index,
                            old_status: switched_in_pkmn.status,
                            new_status: PokemonStatus::POISON,
                        }))
                } else if side.side_conditions.toxic_spikes == 2 {
                    toxic_spike_instruction =
                        Some(Instruction::ChangeStatus(ChangeStatusInstruction {
                            side_ref: switching_side_ref,
                            pokemon_index: side.active_index,
                            old_status: switched_in_pkmn.status,
                            new_status: PokemonStatus::TOXIC,
                        }))
                }
            } else if switched_in_pkmn.has_type(&PokemonType::POISON) {
                toxic_spike_instruction = Some(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: switching_side_ref,
                        side_condition: PokemonSideCondition::ToxicSpikes,
                        amount: -1 * side.side_conditions.toxic_spikes,
                    },
                ))
            }

            if let Some(i) = toxic_spike_instruction {
                state.apply_one_instruction(&i);
                incoming_instructions.instruction_list.push(i);
            }
        }

        let side = state.get_side(&switching_side_ref);
        let active = side.get_active_immutable();
        if active.ability != Abilities::MAGICGUARD {
            if side.side_conditions.stealth_rock == 1 {
                let switched_in_pkmn = side.get_active();
                let multiplier = type_effectiveness_modifier(&PokemonType::ROCK, &switched_in_pkmn);

                let dmg_amount = cmp::min(
                    (switched_in_pkmn.maxhp as f32 * multiplier / 8.0) as i16,
                    switched_in_pkmn.hp,
                );
                let stealth_rock_dmg_instruction = Instruction::Damage(DamageInstruction {
                    side_ref: switching_side_ref,
                    damage_amount: dmg_amount,
                });
                switched_in_pkmn.hp -= dmg_amount;
                incoming_instructions
                    .instruction_list
                    .push(stealth_rock_dmg_instruction);
            }

            let switched_in_pkmn = side.get_active_immutable();
            if side.side_conditions.spikes > 0 && switched_in_pkmn.is_grounded() {
                // alpha-poke patch (2026-10-16): 1/8, 1/6, 1/4 of max HP for 1-3 layers (as
                // Showdown's 3, 4, 6 24ths); before, layers/8
                let layers = cmp::min(side.side_conditions.spikes, 3) as usize;
                let dmg_amount = cmp::min(
                    cmp::max(
                        (switched_in_pkmn.maxhp as i32 * [0, 3, 4, 6][layers] / 24) as i16,
                        1,
                    ),
                    switched_in_pkmn.hp,
                );
                let spikes_dmg_instruction = Instruction::Damage(DamageInstruction {
                    side_ref: switching_side_ref,
                    damage_amount: dmg_amount,
                });
                side.get_active().hp -= dmg_amount;
                incoming_instructions
                    .instruction_list
                    .push(spikes_dmg_instruction);
            }
        }
    }

    let from = incoming_instructions.instruction_list.len();
    ability_on_switch_in(state, &switching_side_ref, incoming_instructions);
    extend_field_durations(state, &switching_side_ref, incoming_instructions, from);
    item_on_switch_in(state, &switching_side_ref, incoming_instructions);
}

fn generate_instructions_from_increment_side_condition(
    state: &mut State,
    side_condition: &SideCondition,
    attacking_side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    let affected_side_ref;
    match side_condition.target {
        MoveTarget::Opponent => affected_side_ref = attacking_side_reference.get_other_side(),
        MoveTarget::User => affected_side_ref = *attacking_side_reference,
    }

    let max_layers = match side_condition.condition {
        PokemonSideCondition::Spikes => 3,
        PokemonSideCondition::ToxicSpikes => 2,
        _ => 1,
    };

    let affected_side = state.get_side(&affected_side_ref);
    if affected_side.get_side_condition(side_condition.condition) < max_layers {
        let ins = Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
            side_ref: affected_side_ref,
            side_condition: side_condition.condition,
            amount: 1,
        });
        affected_side.update_side_condition(side_condition.condition, 1);
        incoming_instructions.instruction_list.push(ins);
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L24): the duration items. A weather or terrain
// its holder sets (a switch-in ability, a move, Sand Spit / Seed Sower) lasts 8 turns with the
// matching rock or a Terrain Extender (Showdown's durationCallback), else 5: the instructions from
// `from` on that set one for 5 turns get 8, and the state with them
pub fn extend_field_durations(
    state: &mut State,
    holder: &SideReference,
    instructions: &mut StateInstructions,
    from: usize,
) {
    let item = state.get_side_immutable(holder).get_active_immutable().item;
    for ins in instructions.instruction_list[from..].iter_mut() {
        match ins {
            Instruction::ChangeWeather(w) if w.new_weather_turns_remaining == 5 => {
                let rock = match w.new_weather {
                    Weather::RAIN => Items::DAMPROCK,
                    Weather::SUN => Items::HEATROCK,
                    Weather::SAND => Items::SMOOTHROCK,
                    Weather::SNOW | Weather::HAIL => Items::ICYROCK,
                    _ => continue,
                };
                if item == rock {
                    w.new_weather_turns_remaining = 8;
                    if state.weather.weather_type == w.new_weather {
                        state.weather.turns_remaining = 8;
                    }
                }
            }
            Instruction::ChangeTerrain(t)
                if t.new_terrain_turns_remaining == 5
                    && t.new_terrain != Terrain::NONE
                    && item == Items::TERRAINEXTENDER =>
            {
                t.new_terrain_turns_remaining = 8;
                if state.terrain.terrain_type == t.new_terrain {
                    state.terrain.turns_remaining = 8;
                }
            }
            _ => {}
        }
    }
}

fn generate_instructions_from_duration_side_conditions(
    state: &mut State,
    side_condition: &SideCondition,
    attacking_side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
    duration: i8,
) {
    let affected_side_ref = match side_condition.target {
        MoveTarget::Opponent => attacking_side_reference.get_other_side(),
        MoveTarget::User => *attacking_side_reference,
    };
    if side_condition.condition == PokemonSideCondition::AuroraVeil
        && !state.weather_is_active(&Weather::HAIL)
        && !state.weather_is_active(&Weather::SNOW)
    {
        return;
    }
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): the user's Light Clay makes a screen
    // last 8 turns (Showdown's durationCallback)
    let mut duration = duration;
    if matches!(
        side_condition.condition,
        PokemonSideCondition::Reflect
            | PokemonSideCondition::LightScreen
            | PokemonSideCondition::AuroraVeil
    ) && state
        .get_side_immutable(attacking_side_reference)
        .get_active_immutable()
        .item
        == Items::LIGHTCLAY
    {
        duration = 8;
    }
    let affected_side = state.get_side(&affected_side_ref);
    if affected_side.get_side_condition(side_condition.condition) == 0 {
        let ins = Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
            side_ref: affected_side_ref,
            side_condition: side_condition.condition,
            amount: duration,
        });
        affected_side.update_side_condition(side_condition.condition, duration);
        incoming_instructions.instruction_list.push(ins);
    }
}

fn generate_instructions_from_side_conditions(
    state: &mut State,
    side_condition: &SideCondition,
    attacking_side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    match side_condition.condition {
        PokemonSideCondition::AuroraVeil
        | PokemonSideCondition::LightScreen
        | PokemonSideCondition::Reflect
        | PokemonSideCondition::Safeguard
        | PokemonSideCondition::Mist => {
            generate_instructions_from_duration_side_conditions(
                state,
                side_condition,
                attacking_side_reference,
                incoming_instructions,
                SIDE_CONDITION_DURATION,
            );
        }
        PokemonSideCondition::Tailwind => {
            generate_instructions_from_duration_side_conditions(
                state,
                side_condition,
                attacking_side_reference,
                incoming_instructions,
                TAILWIND_DURATION,
            );
        }
        _ => generate_instructions_from_increment_side_condition(
            state,
            side_condition,
            attacking_side_reference,
            incoming_instructions,
        ),
    }
}

fn get_instructions_from_volatile_statuses(
    state: &mut State,
    attacker_choice: &Choice,
    volatile_status: &VolatileStatus,
    attacking_side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    let target_side: SideReference;
    match volatile_status.target {
        MoveTarget::Opponent => target_side = attacking_side_reference.get_other_side(),
        MoveTarget::User => target_side = *attacking_side_reference,
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L70): Disable stops the target's last move
    // (fails without one, or when it is on already), for 4 turns: 5 if the target had moved
    if volatile_status.volatile_status == PokemonVolatileStatus::DISABLE {
        let moved = target_side == *attacking_side_reference || !attacker_choice.first_move;
        let side = state.get_side(&target_side);
        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::DISABLE)
        {
            return;
        }
        let slot = match side.last_used_move {
            LastUsedMove::Move(i) => i,
            _ => return,
        };
        side.volatile_statuses
            .insert(PokemonVolatileStatus::DISABLE);
        incoming_instructions
            .instruction_list
            .push(Instruction::ApplyVolatileStatus(
                ApplyVolatileStatusInstruction {
                    side_ref: target_side,
                    volatile_status: PokemonVolatileStatus::DISABLE,
                },
            ));
        let active = side.get_active();
        if !active.moves[&slot].disabled {
            active.moves[&slot].disabled = true;
            incoming_instructions
                .instruction_list
                .push(Instruction::DisableMove(DisableMoveInstruction {
                    side_ref: target_side,
                    move_index: slot,
                }));
        }
        let value = slot as i8 * 8 + if moved { 0 } else { 1 };
        let amount = value - side.volatile_status_durations.disable;
        if amount != 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: target_side,
                        volatile_status: PokemonVolatileStatus::DISABLE,
                        amount,
                    },
                ));
            side.volatile_status_durations.disable = value;
        }
        return;
    }

    if volatile_status.volatile_status == PokemonVolatileStatus::YAWN
        && immune_to_status(
            state,
            &MoveTarget::Opponent,
            &target_side,
            &PokemonStatus::SLEEP,
        )
    {
        return;
    }
    let side = state.get_side(&target_side);
    let affected_pkmn = side.get_active_immutable();
    if affected_pkmn.volatile_status_can_be_applied(
        &volatile_status.volatile_status,
        &side.volatile_statuses,
        attacker_choice.first_move,
    ) {
        let ins = Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
            side_ref: target_side,
            volatile_status: volatile_status.volatile_status,
        });

        side.volatile_statuses
            .insert(volatile_status.volatile_status);
        incoming_instructions.instruction_list.push(ins);
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L89): Encore ends at its third end of
        // turn, its fourth if the target had moved (Showdown's duration 3, + 1): the count starts
        // at 0 / -1
        // (L90: Taunt too, though not for a target that came in this turn: Showdown's activeTurns)
        if matches!(
            volatile_status.volatile_status,
            PokemonVolatileStatus::ENCORE | PokemonVolatileStatus::TAUNT
        ) {
            let v = volatile_status.volatile_status;
            let came_in = matches!(side.last_used_move, LastUsedMove::Switch(_));
            let moved = (target_side == *attacking_side_reference || !attacker_choice.first_move)
                && !(v == PokemonVolatileStatus::TAUNT && came_in);
            let value: i8 = if moved { -1 } else { 0 };
            let current = if v == PokemonVolatileStatus::ENCORE {
                &mut side.volatile_status_durations.encore
            } else {
                &mut side.volatile_status_durations.taunt
            };
            let amount = value - *current;
            if amount != 0 {
                *current = value;
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: target_side,
                            volatile_status: v,
                            amount,
                        },
                    ),
                );
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Destiny Knot, the holder's
        // infatuation goes to the foe that caused it too
        if volatile_status.volatile_status == PokemonVolatileStatus::ATTRACT
            && target_side != *attacking_side_reference
            && side.get_active_immutable().item == Items::DESTINYKNOT
        {
            let source = state.get_side(attacking_side_reference);
            if !source
                .volatile_statuses
                .contains(&PokemonVolatileStatus::ATTRACT)
                && source.get_active_immutable().ability != Abilities::OBLIVIOUS
            {
                source
                    .volatile_statuses
                    .insert(PokemonVolatileStatus::ATTRACT);
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ApplyVolatileStatus(
                        ApplyVolatileStatusInstruction {
                            side_ref: *attacking_side_reference,
                            volatile_status: PokemonVolatileStatus::ATTRACT,
                        },
                    ));
            }
        }
    }
}

pub fn add_remove_status_instructions(
    incoming_instructions: &mut StateInstructions,
    pokemon_index: PokemonIndex,
    side_reference: SideReference,
    side: &mut Side,
) {
    /*
    Single place to check for status removals, add the necessary instructions, and update the pokemon's status

    This is necessary because of some side effects to removing statuses
    i.e. a pre-mature wake-up from rest must set rest_turns to 0
    */
    let pkmn = &mut side.pokemon[pokemon_index];
    incoming_instructions
        .instruction_list
        .push(Instruction::ChangeStatus(ChangeStatusInstruction {
            side_ref: side_reference,
            pokemon_index: pokemon_index,
            old_status: pkmn.status,
            new_status: PokemonStatus::NONE,
        }));
    match pkmn.status {
        PokemonStatus::SLEEP => {
            if pkmn.rest_turns > 0 {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::SetRestTurns(SetSleepTurnsInstruction {
                        side_ref: side_reference,
                        pokemon_index,
                        new_turns: 0,
                        previous_turns: pkmn.rest_turns,
                    }));
                pkmn.rest_turns = 0;
            } else if pkmn.sleep_turns > 0 {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                        side_ref: side_reference,
                        pokemon_index,
                        new_turns: 0,
                        previous_turns: pkmn.sleep_turns,
                    }));
                pkmn.sleep_turns = 0;
            }
        }
        PokemonStatus::TOXIC => {
            if side.side_conditions.toxic_count != 0 {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: side_reference,
                            side_condition: PokemonSideCondition::ToxicCount,
                            amount: -1 * side.side_conditions.toxic_count,
                        },
                    ));
                side.side_conditions.toxic_count = 0;
            }
        }
        _ => {}
    }
    pkmn.status = PokemonStatus::NONE;
}

pub fn immune_to_status(
    state: &State,
    status_target: &MoveTarget,
    target_side_ref: &SideReference,
    status: &PokemonStatus,
) -> bool {
    let (target_side, attacking_side) = state.get_both_sides_immutable(target_side_ref);
    let target_pkmn = target_side.get_active_immutable();
    let attacking_pkmn = attacking_side.get_active_immutable();
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L80): the other active's Neutralizing Gas
    // suppresses an ability (not through an Ability Shield; Comatose / Shields Down it cannot)
    let gassed = |gas: &crate::state::Pokemon, holder: &crate::state::Pokemon| {
        gas.ability == Abilities::NEUTRALIZINGGAS && holder.item != Items::ABILITYSHIELD
    };
    let ability = if gassed(attacking_pkmn, target_pkmn) {
        Abilities::NONE
    } else {
        target_pkmn.ability
    };
    let attacker_ability = if gassed(target_pkmn, attacking_pkmn) {
        Abilities::NONE
    } else {
        attacking_pkmn.ability
    };

    // General Status Immunity
    match target_pkmn.ability {
        Abilities::SHIELDSDOWN => return target_pkmn.hp > target_pkmn.maxhp / 2,
        Abilities::COMATOSE => return true,
        _ => {}
    }
    match ability {
        Abilities::PURIFYINGSALT => return true,
        Abilities::LEAFGUARD => return state.weather_is_active(&Weather::SUN),
        _ => {}
    }

    if target_pkmn.status != PokemonStatus::NONE || target_pkmn.hp <= 0 {
        true
    } else if state.terrain.terrain_type == Terrain::MISTYTERRAIN && target_pkmn.is_grounded() {
        true
    } else if (target_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::SUBSTITUTE)
        || target_side.side_conditions.safeguard > 0)
        && status_target == &MoveTarget::Opponent
    // substitute/safeguard don't block if the target is yourself (eg. rest)
    {
        true
    } else {
        // Specific status immunity
        match status {
            PokemonStatus::BURN => {
                target_pkmn.has_type(&PokemonType::FIRE)
                    || [
                        Abilities::WATERVEIL,
                        Abilities::WATERBUBBLE,
                        Abilities::THERMALEXCHANGE,
                    ]
                    .contains(&ability)
            }
            PokemonStatus::FREEZE => {
                target_pkmn.has_type(&PokemonType::ICE)
                    || ability == Abilities::MAGMAARMOR
                    || state.weather_is_active(&Weather::SUN)
                    || state.weather_is_active(&Weather::HARSHSUN)
            }
            PokemonStatus::SLEEP => {
                (state.terrain.terrain_type == Terrain::ELECTRICTERRAIN
                    && target_pkmn.is_grounded())
                    || [
                        Abilities::INSOMNIA,
                        Abilities::SWEETVEIL,
                        Abilities::VITALSPIRIT,
                    ]
                    .contains(&ability)
                    || (status_target == &MoveTarget::Opponent
                        && target_side.has_alive_non_rested_sleeping_pkmn())
                // sleep clause
            }

            #[cfg(any(
                feature = "gen6",
                feature = "gen7",
                feature = "gen8",
                feature = "gen9",
                feature = "champions"
            ))]
            PokemonStatus::PARALYZE => {
                target_pkmn.has_type(&PokemonType::ELECTRIC) || ability == Abilities::LIMBER
            }

            #[cfg(any(feature = "gen4", feature = "gen5"))]
            PokemonStatus::PARALYZE => ability == Abilities::LIMBER,

            PokemonStatus::POISON | PokemonStatus::TOXIC => {
                ((target_pkmn.has_type(&PokemonType::POISON)
                    || target_pkmn.has_type(&PokemonType::STEEL))
                    && attacker_ability != Abilities::CORROSION)
                    || [Abilities::IMMUNITY, Abilities::PASTELVEIL].contains(&ability)
            }
            _ => false,
        }
    }
}

fn get_instructions_from_status_effects(
    state: &mut State,
    status: &Status,
    attacking_side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
    hit_sub: bool,
) {
    let target_side_ref: SideReference;
    match status.target {
        MoveTarget::Opponent => target_side_ref = attacking_side_reference.get_other_side(),
        MoveTarget::User => target_side_ref = *attacking_side_reference,
    }

    if hit_sub || immune_to_status(state, &status.target, &target_side_ref, &status.status) {
        return;
    }

    // (L102: not when the target is unnerved)
    let unnerve = super::items::unnerved(state, &target_side_ref);
    let target_side = state.get_side(&target_side_ref);
    let target_side_active = target_side.active_index;
    let target_pkmn = target_side.get_active();

    let instruction = if target_pkmn.item == Items::LUMBERRY && !unnerve {
        target_pkmn.item = Items::NONE;
        // (L57: used up)
        set_last_item(
            target_pkmn,
            target_side_ref,
            Items::LUMBERRY,
            incoming_instructions,
        );
        Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: target_side_ref,
            current_item: Items::LUMBERRY,
            new_item: Items::NONE,
        })
    } else if target_pkmn.item == Items::CHESTOBERRY
        && status.status == PokemonStatus::SLEEP
        && !unnerve
    {
        target_pkmn.item = Items::NONE;
        // (L57: used up)
        set_last_item(
            target_pkmn,
            target_side_ref,
            Items::CHESTOBERRY,
            incoming_instructions,
        );
        Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: target_side_ref,
            current_item: Items::CHESTOBERRY,
            new_item: Items::NONE,
        })
    } else {
        let old_status = target_pkmn.status;
        target_pkmn.status = status.status;
        Instruction::ChangeStatus(ChangeStatusInstruction {
            side_ref: target_side_ref,
            pokemon_index: target_side_active,
            old_status,
            new_status: status.status,
        })
    };
    let applied = matches!(instruction, Instruction::ChangeStatus(_));
    let poisoned = applied && matches!(status.status, PokemonStatus::POISON | PokemonStatus::TOXIC);
    incoming_instructions.instruction_list.push(instruction);

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L46): Synchronize, a poison / burn /
    // paralysis from the foe (its move, or its ability through a secondary on the user: Static,
    // Flame Body, ...) goes back to the foe (Showdown's onAfterSetStatus; the foe's immunities,
    // not its Substitute)
    // (L80: not under the foe's Neutralizing Gas)
    let holder_synchronizes = {
        let holder = state
            .get_side_immutable(&target_side_ref)
            .get_active_immutable();
        let foe = state
            .get_side_immutable(&target_side_ref.get_other_side())
            .get_active_immutable();
        holder.ability == Abilities::SYNCHRONIZE
            && !(foe.ability == Abilities::NEUTRALIZINGGAS && holder.item != Items::ABILITYSHIELD)
    };
    if applied
        && holder_synchronizes
        && matches!(
            status.status,
            PokemonStatus::POISON
                | PokemonStatus::TOXIC
                | PokemonStatus::BURN
                | PokemonStatus::PARALYZE
        )
    {
        let foe_ref = target_side_ref.get_other_side();
        if !immune_to_status(state, &MoveTarget::User, &foe_ref, &status.status) {
            let foe_side = state.get_side(&foe_ref);
            let index = foe_side.active_index;
            let foe = foe_side.get_active();
            let old_status = foe.status;
            foe.status = status.status;
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: foe_ref,
                    pokemon_index: index,
                    old_status,
                    new_status: status.status,
                }));
        }
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L40): Poison Puppeteer, the foe its
    // holder's move poisons is confused too (Showdown's onAnyAfterSetStatus; Own Tempo, Misty
    // Terrain on a grounded target and an existing confusion stop it)
    let misty = state.terrain_is_active(&Terrain::MISTYTERRAIN);
    let (attacking_side, target_side) = state.get_both_sides(attacking_side_reference);
    if poisoned
        && target_side_ref != *attacking_side_reference
        && attacking_side.get_active_immutable().ability == Abilities::POISONPUPPETEER
    {
        let target = target_side.get_active_immutable();
        if target.ability != Abilities::OWNTEMPO
            && !(misty && target.is_grounded())
            && !target_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::CONFUSION)
        {
            target_side
                .volatile_statuses
                .insert(PokemonVolatileStatus::CONFUSION);
            incoming_instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref: target_side_ref,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                    },
                ));
        }
    }
}

pub fn get_boost_amount(side: &Side, boost: &PokemonBoostableStat, amount: i8) -> i8 {
    /*
    returns that amount that can actually be applied from the attempted boost amount
        e.g. using swordsdance at +5 attack would result in a +1 boost instead of +2
    */
    let current_boost = side.get_boost_from_boost_enum(boost);

    if amount > 0 {
        return cmp::min(6 - current_boost, amount);
    } else if amount < 0 {
        return cmp::max(-6 - current_boost, amount);
    }
    0
}

pub fn apply_boost_instruction(
    target_side: &mut Side,
    stat: &PokemonBoostableStat,
    boost: &i8,
    attacking_side_ref: &SideReference,
    target_side_ref: &SideReference,
    instructions: &mut StateInstructions,
) -> bool {
    // Single point for checking whether a boost can be applied to a pokemon
    // along with side effects that that boost
    // applies the boost & side effects if applicable
    // returns whether the requested boost was actually applied
    let mut boost_was_applied = false;
    let target_pkmn = target_side.get_active_immutable();
    let target_pkmn_ability = target_pkmn.ability;

    if boost != &0
        && !(target_side_ref != attacking_side_ref
            && target_pkmn
                .immune_to_stats_lowered_by_opponent(&stat, &target_side.volatile_statuses))
        && target_pkmn.hp != 0
    {
        let mut boost_amount = *boost;
        if target_pkmn_ability == Abilities::CONTRARY {
            boost_amount *= -1;
        }
        boost_amount = get_boost_amount(target_side, &stat, boost_amount);
        if boost_amount != 0 {
            boost_was_applied = true;
            match stat {
                PokemonBoostableStat::Attack => target_side.attack_boost += boost_amount,
                PokemonBoostableStat::Defense => target_side.defense_boost += boost_amount,
                PokemonBoostableStat::SpecialAttack => {
                    target_side.special_attack_boost += boost_amount
                }
                PokemonBoostableStat::SpecialDefense => {
                    target_side.special_defense_boost += boost_amount
                }
                PokemonBoostableStat::Speed => target_side.speed_boost += boost_amount,
                PokemonBoostableStat::Evasion => target_side.evasion_boost += boost_amount,
                PokemonBoostableStat::Accuracy => target_side.accuracy_boost += boost_amount,
            }
            instructions
                .instruction_list
                .push(Instruction::Boost(BoostInstruction {
                    side_ref: *target_side_ref,
                    stat: *stat,
                    amount: boost_amount,
                }));

            if boost_amount < 0 {
                if target_pkmn_ability == Abilities::DEFIANT
                    && attacking_side_ref != target_side_ref
                    && target_side.attack_boost < 6
                {
                    let defiant_boost_amount = cmp::min(6 - target_side.attack_boost, 2);
                    target_side.attack_boost += defiant_boost_amount;
                    instructions
                        .instruction_list
                        .push(Instruction::Boost(BoostInstruction {
                            side_ref: *target_side_ref,
                            stat: PokemonBoostableStat::Attack,
                            amount: defiant_boost_amount,
                        }));
                } else if target_pkmn_ability == Abilities::COMPETITIVE
                    && attacking_side_ref != target_side_ref
                    && target_side.special_attack_boost < 6
                {
                    let competitive_boost_amount =
                        cmp::min(6 - target_side.special_attack_boost, 2);
                    target_side.special_attack_boost += competitive_boost_amount;
                    instructions
                        .instruction_list
                        .push(Instruction::Boost(BoostInstruction {
                            side_ref: *target_side_ref,
                            stat: PokemonBoostableStat::SpecialAttack,
                            amount: competitive_boost_amount,
                        }));
                }
            }
        }
    }
    boost_was_applied
}

fn get_instructions_from_boosts(
    state: &mut State,
    boosts: &Boost,
    attacking_side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    let target_side_ref: SideReference;
    match boosts.target {
        MoveTarget::Opponent => target_side_ref = attacking_side_reference.get_other_side(),
        MoveTarget::User => target_side_ref = *attacking_side_reference,
    }
    let boostable_stats = boosts.boosts.get_as_pokemon_boostable();
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L21): Mirror Armor reflects the opponent's
    // stat drops back onto it (the holder as their source: Defiant / Competitive answer them)
    let mirror = boosts.target == MoveTarget::Opponent
        && state
            .get_side_immutable(&target_side_ref)
            .get_active_immutable()
            .ability
            == Abilities::MIRRORARMOR
        && !matches!(
            state
                .get_side_immutable(attacking_side_reference)
                .get_active_immutable()
                .ability,
            Abilities::MOLDBREAKER | Abilities::TERAVOLT | Abilities::TURBOBLAZE
        );
    for (pkmn_boostable_stat, boost) in boostable_stats.iter().filter(|(_, b)| b != &0) {
        if mirror && *boost < 0 {
            let side = state.get_side(attacking_side_reference);
            apply_boost_instruction(
                side,
                pkmn_boostable_stat,
                boost,
                &target_side_ref,
                attacking_side_reference,
                incoming_instructions,
            );
            continue;
        }
        let side = state.get_side(&target_side_ref);
        apply_boost_instruction(
            side,
            pkmn_boostable_stat,
            boost,
            attacking_side_reference,
            &target_side_ref,
            incoming_instructions,
        );
    }
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Mirror Herb copies the foe's raises of
    // its own stats once (used up)
    let foe_ref = target_side_ref.get_other_side();
    if target_side_ref == *attacking_side_reference
        && state
            .get_side_immutable(&foe_ref)
            .get_active_immutable()
            .item
            == Items::MIRRORHERB
        && boostable_stats.iter().any(|(_, b)| *b > 0)
    {
        for (stat, boost) in boostable_stats.iter().filter(|(_, b)| *b > 0) {
            apply_boost_instruction(
                state.get_side(&foe_ref),
                stat,
                boost,
                &foe_ref,
                &foe_ref,
                incoming_instructions,
            );
        }
        incoming_instructions
            .instruction_list
            .push(Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: foe_ref,
                current_item: Items::MIRRORHERB,
                new_item: Items::NONE,
            }));
        state.get_side(&foe_ref).get_active().item = Items::NONE;
    }
}

fn compare_health_with_damage_multiples(max_damage: i16, health: i16) -> (i16, i16) {
    let max_damage_f32 = max_damage as f32;
    let health_f32 = health as f32;

    let mut total_less_than = 0;
    let mut num_less_than = 0;
    let mut num_greater_than = 0;
    let increment = max_damage as f32 * 0.01;
    let mut damage = max_damage_f32 * 0.85;
    for _ in 0..16 {
        if damage < health_f32 {
            total_less_than += damage as i16;
            num_less_than += 1;
        } else if damage > health_f32 {
            num_greater_than += 1;
        }
        damage += increment;
    }

    (total_less_than / num_less_than, num_greater_than)
}

fn get_instructions_from_secondaries(
    state: &mut State,
    attacker_choice: &Choice,
    secondaries: &Vec<Secondary>,
    side_reference: &SideReference,
    incoming_instructions: StateInstructions,
    hit_sub: bool,
) -> Vec<StateInstructions> {
    let mut return_instruction_list = Vec::with_capacity(4);
    return_instruction_list.push(incoming_instructions);

    for secondary in secondaries {
        if secondary.target == MoveTarget::Opponent && hit_sub {
            continue;
        }
        let secondary_percent_hit = (secondary.chance / 100.0).min(1.0);

        let mut i = 0;
        while i < return_instruction_list.len() {
            let mut secondary_hit_instructions = return_instruction_list.remove(i);

            if secondary_percent_hit < 1.0 {
                let mut secondary_miss_instructions = secondary_hit_instructions.clone();
                secondary_miss_instructions.update_percentage(1.0 - secondary_percent_hit);
                return_instruction_list.insert(i, secondary_miss_instructions);
                i += 1;
            }

            if secondary_percent_hit > 0.0 {
                secondary_hit_instructions.update_percentage(secondary_percent_hit);

                state.apply_instructions(&secondary_hit_instructions.instruction_list);
                match &secondary.effect {
                    Effect::VolatileStatus(volatile_status) => {
                        get_instructions_from_volatile_statuses(
                            state,
                            attacker_choice,
                            &VolatileStatus {
                                target: secondary.target.clone(),
                                volatile_status: volatile_status.clone(),
                            },
                            side_reference,
                            &mut secondary_hit_instructions,
                        );
                    }
                    Effect::Boost(boost) => {
                        get_instructions_from_boosts(
                            state,
                            &Boost {
                                target: secondary.target.clone(),
                                boosts: boost.clone(),
                            },
                            side_reference,
                            &mut secondary_hit_instructions,
                        );
                    }
                    Effect::Status(status) => {
                        get_instructions_from_status_effects(
                            state,
                            &Status {
                                target: secondary.target.clone(),
                                status: status.clone(),
                            },
                            side_reference,
                            &mut secondary_hit_instructions,
                            hit_sub,
                        );
                    }
                    Effect::Heal(heal_amount) => {
                        get_instructions_from_heal(
                            state,
                            &Heal {
                                target: secondary.target.clone(),
                                amount: *heal_amount,
                            },
                            side_reference,
                            &mut secondary_hit_instructions,
                        );
                    }
                    Effect::RemoveItem => {
                        let secondary_target_side_ref: SideReference;
                        match secondary.target {
                            MoveTarget::Opponent => {
                                secondary_target_side_ref = side_reference.get_other_side();
                            }
                            MoveTarget::User => {
                                secondary_target_side_ref = *side_reference;
                            }
                        }
                        let target_pkmn = state.get_side(&secondary_target_side_ref).get_active();
                        secondary_hit_instructions
                            .instruction_list
                            .push(Instruction::ChangeItem(ChangeItemInstruction {
                                side_ref: secondary_target_side_ref,
                                current_item: target_pkmn.item.clone(),
                                new_item: Items::NONE,
                            }));
                        target_pkmn.item = Items::NONE;
                    }
                }
                state.reverse_instructions(&secondary_hit_instructions.instruction_list);
                return_instruction_list.insert(i, secondary_hit_instructions);
                i += 1; // Increment i only if we didn't remove an element
            }
        }
    }

    return_instruction_list
}

fn get_instructions_from_heal(
    state: &mut State,
    heal: &Heal,
    attacking_side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    let target_side_ref: SideReference;
    match heal.target {
        MoveTarget::Opponent => target_side_ref = attacking_side_reference.get_other_side(),
        MoveTarget::User => target_side_ref = *attacking_side_reference,
    }

    let target_pkmn = state.get_side(&target_side_ref).get_active();

    let mut health_recovered = (heal.amount * target_pkmn.maxhp as f32) as i16;
    let final_health = target_pkmn.hp + health_recovered;
    if final_health > target_pkmn.maxhp {
        health_recovered -= final_health - target_pkmn.maxhp;
    } else if final_health < 0 {
        health_recovered -= final_health;
    }

    if health_recovered != 0 {
        let ins = Instruction::Heal(HealInstruction {
            side_ref: target_side_ref,
            heal_amount: health_recovered,
        });
        target_pkmn.hp += health_recovered;
        incoming_instructions.instruction_list.push(ins);
    }
}

fn boosted_accuracy(accuracy_boost: i8) -> f32 {
    if accuracy_boost < 0 {
        3.0 / (3.0 - accuracy_boost as f32)
    } else {
        (3.0 + accuracy_boost as f32) / 3.0
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L22 / L23): the instructions that end a locking
// move's lock (Outrage, Petal Dance, ...): the volatile and its count go, the other moves can be
// used again (unless a choice item locks them anyway), and with `confuse` the user is confused
// (the lock ran out). Showdown renews the lock only on a hit, so a locked move that misses, hits
// an immune target, has no effect or is protected against ends it at once, unconfused (L22);
// the engine never ended it early, and never gave the other moves back (L23).
fn lock_end_instructions(
    state: &State,
    side_ref: &SideReference,
    confuse: bool,
) -> Vec<Instruction> {
    let side = state.get_side_immutable(side_ref);
    let mut out = vec![];
    if !side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::LOCKEDMOVE)
    {
        return out;
    }
    let count = side.volatile_status_durations.lockedmove;
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L61): on its last turn (the engine's locks
    // last 3: a count of 2) it confuses however it ends (Showdown's onEnd, by trueDuration)
    let confuse = confuse || count >= 2;
    if count != 0 {
        out.push(Instruction::ChangeVolatileStatusDuration(
            ChangeVolatileStatusDurationInstruction {
                side_ref: *side_ref,
                volatile_status: PokemonVolatileStatus::LOCKEDMOVE,
                amount: -count,
            },
        ));
    }
    out.push(Instruction::RemoveVolatileStatus(
        RemoveVolatileStatusInstruction {
            side_ref: *side_ref,
            volatile_status: PokemonVolatileStatus::LOCKEDMOVE,
        },
    ));
    let active = side.get_active_immutable();
    if !matches!(
        active.item,
        Items::CHOICEBAND | Items::CHOICESPECS | Items::CHOICESCARF
    ) {
        let mut iter = active.moves.into_iter();
        while let Some(m) = iter.next() {
            if m.disabled {
                out.push(Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: *side_ref,
                    move_index: iter.pokemon_move_index,
                }));
            }
        }
    }
    if confuse
        && !side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::CONFUSION)
    {
        out.push(Instruction::ApplyVolatileStatus(
            ApplyVolatileStatusInstruction {
                side_ref: *side_ref,
                volatile_status: PokemonVolatileStatus::CONFUSION,
            },
        ));
    }
    out
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L27): Brick Break, Psychic Fangs and Raging
// Bull break the target side's screens before they hit (Showdown's onTryHit: their damage is not
// halved, a miss leaves them); the instructions that remove them
fn screen_break_instructions(
    state: &State,
    choice: &Choice,
    attacker: &SideReference,
) -> Vec<Instruction> {
    if !matches!(
        choice.move_id,
        Choices::BRICKBREAK | Choices::PSYCHICFANGS | Choices::RAGINGBULL
    ) || choice.category == MoveCategory::Status
    {
        return vec![];
    }
    let target = attacker.get_other_side();
    let sc = &state.get_side_immutable(&target).side_conditions;
    [
        (PokemonSideCondition::Reflect, sc.reflect),
        (PokemonSideCondition::LightScreen, sc.light_screen),
        (PokemonSideCondition::AuroraVeil, sc.aurora_veil),
    ]
    .iter()
    .filter(|(_, turns)| *turns > 0)
    .map(|(side_condition, turns)| {
        Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
            side_ref: target,
            side_condition: *side_condition,
            amount: -turns,
        })
    })
    .collect()
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Big Root's heal, Showdown's chainModify
// [5324, 4096] (rounded half down)
pub fn big_root(amount: i16) -> i16 {
    ((amount as i32 * 5324 + 2047) / 4096) as i16
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Starf Berry, eaten when a hit takes its
// holder to 1/4 HP or less (Showdown's onUpdate; at 1/2 with Gluttony): a random stat of the
// five not at +6 gets +2, so each outcome from `from` on splits into one per such stat, with an
// equal share of its chance
fn starf_berry_branches(
    state: &mut State,
    final_instructions: &mut Vec<StateInstructions>,
    from: usize,
) {
    let new: Vec<StateInstructions> = final_instructions.drain(from..).collect();
    for si in new {
        state.apply_instructions(&si.instruction_list);
        let mut branches = vec![si.clone()];
        for side_ref in [SideReference::SideOne, SideReference::SideTwo] {
            let side = state.get_side_immutable(&side_ref);
            let active = side.get_active_immutable();
            let low = active.hp <= active.maxhp / 4
                || (active.ability == Abilities::GLUTTONY && active.hp <= active.maxhp / 2);
            if active.item != Items::STARFBERRY
                || active.hp == 0
                || !low
                || super::items::unnerved(state, &side_ref)
            {
                continue;
            }
            let stats: Vec<(PokemonBoostableStat, i8)> = [
                (PokemonBoostableStat::Attack, side.attack_boost),
                (PokemonBoostableStat::Defense, side.defense_boost),
                (
                    PokemonBoostableStat::SpecialAttack,
                    side.special_attack_boost,
                ),
                (
                    PokemonBoostableStat::SpecialDefense,
                    side.special_defense_boost,
                ),
                (PokemonBoostableStat::Speed, side.speed_boost),
            ]
            .iter()
            .copied()
            .filter(|(_, b)| *b < 6)
            .collect();
            let eat = Instruction::ChangeItem(ChangeItemInstruction {
                side_ref,
                current_item: Items::STARFBERRY,
                new_item: Items::NONE,
            });
            let mut next = vec![];
            for b in branches {
                if stats.is_empty() {
                    let mut c = b.clone();
                    c.instruction_list.push(eat.clone());
                    next.push(c);
                    continue;
                }
                for (stat, current) in stats.iter() {
                    let mut c = b.clone();
                    c.update_percentage(1.0 / stats.len() as f32);
                    c.instruction_list
                        .push(Instruction::Boost(BoostInstruction {
                            side_ref,
                            stat: *stat,
                            amount: cmp::min(2, 6 - current),
                        }));
                    c.instruction_list.push(eat.clone());
                    next.push(c);
                }
            }
            branches = next;
        }
        state.reverse_instructions(&si.instruction_list);
        final_instructions.extend(branches);
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L24 / L28): the crit chance of Showdown's crit
// stage: the move's (+1 for a high-crit one), Scope Lens / Razor Claw +1, Super Luck +1, Focus
// Energy +2 (1/24, 1/8, 1/2, then sure); before, only the move's
fn crit_stage_chance(state: &State, attacking_side: &SideReference, choice: &Choice) -> f32 {
    let side = state.get_side_immutable(attacking_side);
    let attacker = side.get_active_immutable();
    let stage = i32::from(choice.move_id.increased_crit_ratio())
        + i32::from(matches!(attacker.item, Items::SCOPELENS | Items::RAZORCLAW))
        + i32::from(attacker.ability == Abilities::SUPERLUCK)
        + 2 * i32::from(
            side.volatile_statuses
                .contains(&PokemonVolatileStatus::FOCUSENERGY),
        );
    match stage {
        0 => BASE_CRIT_CHANCE,
        1 => 1.0 / 8.0,
        2 => 1.0 / 2.0,
        _ => 1.0,
    }
}

// alpha-poke patch (2026-10-16, L30): a hit's crit chance against the defender (Battle / Shell
// Armor: none; a guaranteed crit: sure)
fn hit_crit_chance(state: &State, attacking_side: &SideReference, choice: &Choice) -> f32 {
    let defender = state
        .get_side_immutable(&attacking_side.get_other_side())
        .get_active_immutable();
    if defender.ability == Abilities::BATTLEARMOR || defender.ability == Abilities::SHELLARMOR {
        0.0
    } else if choice.move_id.guaranteed_crit() {
        1.0
    } else {
        crit_stage_chance(state, attacking_side, choice)
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L30): the chance that hits with these rolls
// knock out a target with `hp`, each hit rolling one of its 16 on its own (L34: the exact rolls),
// and the average total when they do not: the distribution of the total by convolution, totals
// of `hp` or more pooled
fn multi_hit_kill(per_hit_rolls: &[[i16; 16]], hp: i32) -> (f32, f32) {
    let cap = hp.max(1) as usize;
    let mut dist = vec![0.0f32; cap + 1];
    dist[0] = 1.0;
    for rolls in per_hit_rolls {
        let mut next = vec![0.0f32; cap + 1];
        for (total, p) in dist.iter().enumerate() {
            if *p == 0.0 {
                continue;
            }
            if total == cap {
                next[cap] += p;
                continue;
            }
            for roll in rolls {
                let t = cmp::min(total + *roll as usize, cap);
                next[t] += p / 16.0;
            }
        }
        dist = next;
    }
    let kill = dist[cap];
    let alive: f32 = dist[..cap].iter().sum();
    let mean = if alive > 0.0 {
        dist[..cap]
            .iter()
            .enumerate()
            .map(|(t, p)| t as f32 * p)
            .sum::<f32>()
            / alive
    } else {
        0.0
    };
    (kill, mean)
}

fn check_move_hit_or_miss(
    state: &mut State,
    choice: &Choice,
    attacking_side_ref: &SideReference,
    damage: Option<(i16, i16)>,
    incoming_instructions: &mut StateInstructions,
    frozen_instructions: &mut Vec<StateInstructions>,
) {
    /*
    Checks whether a move can miss

    If the move can miss - adds it to `frozen_instructions`, signifying that the rest of the
    half-turn will not run.

    Otherwise, update the incoming instructions' percent_hit to reflect the chance of the move hitting
    */
    let target_item = state
        .get_side_immutable(&attacking_side_ref.get_other_side())
        .get_active_immutable()
        .item;
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Micle Berry's boost goes with the next
    // move aimed at the target (x 4915 / 4096 when it can miss)
    let mut micle = false;
    if choice.target == MoveTarget::Opponent {
        let side = state.get_side(attacking_side_ref);
        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::MICLEBERRY)
        {
            micle = !choice.move_id.always_hits();
            side.volatile_statuses
                .remove(&PokemonVolatileStatus::MICLEBERRY);
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *attacking_side_ref,
                        volatile_status: PokemonVolatileStatus::MICLEBERRY,
                    },
                ));
            let count = side.volatile_status_durations.micleberry;
            if count != 0 {
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *attacking_side_ref,
                            volatile_status: PokemonVolatileStatus::MICLEBERRY,
                            amount: -count,
                        },
                    ),
                );
                side.volatile_status_durations.micleberry = 0;
            }
        }
    }
    let attacking_side = state.get_side(attacking_side_ref);
    let attacking_pokemon = attacking_side.get_active_immutable();

    let mut percent_hit =
        (choice.accuracy / 100.0) * boosted_accuracy(attacking_side.accuracy_boost);
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Bright Powder (the target's, x
    // 3686 / 4096) and Zoom Lens (the user's, moving after the target, x 4915 / 4096) on a move
    // aimed at the target that can miss
    if choice.target == MoveTarget::Opponent && !choice.move_id.always_hits() {
        if attacking_pokemon.item == Items::ZOOMLENS && !choice.first_move {
            percent_hit *= 4915.0 / 4096.0;
        }
        if target_item == Items::BRIGHTPOWDER {
            percent_hit *= 3686.0 / 4096.0;
        }
        if micle {
            percent_hit *= 4915.0 / 4096.0;
        }
    }
    let mut percent_hit = percent_hit.min(1.0);
    if Some((0, 0)) == damage {
        percent_hit = 0.0;
    }

    if percent_hit < 1.0 {
        let mut move_missed_instruction = incoming_instructions.clone();
        move_missed_instruction.update_percentage(1.0 - percent_hit);
        if let Some(crash_fraction) = choice.crash {
            let crash_amount = (attacking_pokemon.maxhp as f32 * crash_fraction) as i16;
            let crash_instruction = Instruction::Damage(DamageInstruction {
                side_ref: *attacking_side_ref,
                damage_amount: cmp::min(crash_amount, attacking_pokemon.hp),
            });

            move_missed_instruction
                .instruction_list
                .push(crash_instruction);
        }

        if Items::BLUNDERPOLICY == attacking_pokemon.item {
            let boost_amount = get_boost_amount(attacking_side, &PokemonBoostableStat::Speed, 2);
            move_missed_instruction
                .instruction_list
                .push(Instruction::Boost(BoostInstruction {
                    side_ref: *attacking_side_ref,
                    stat: PokemonBoostableStat::Speed,
                    amount: boost_amount,
                }));
            move_missed_instruction
                .instruction_list
                .push(Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: *attacking_side_ref,
                    current_item: Items::BLUNDERPOLICY,
                    new_item: Items::NONE,
                }));
        }

        // L22: the lock ends (the frozen branch's instructions are not applied here, as the
        // crash's above)
        move_missed_instruction
            .instruction_list
            .extend(lock_end_instructions(state, attacking_side_ref, false));
        frozen_instructions.push(move_missed_instruction);
    }
    incoming_instructions.update_percentage(percent_hit);
}

fn get_instructions_from_drag(
    state: &mut State,
    attacking_side_reference: &SideReference,
    incoming_instructions: StateInstructions,
    frozen_instructions: &mut Vec<StateInstructions>,
) {
    let defending_side = state.get_side(&attacking_side_reference.get_other_side());
    if defending_side.get_active_immutable().hp == 0 {
        state.reverse_instructions(&incoming_instructions.instruction_list);
        frozen_instructions.push(incoming_instructions);
        return;
    }

    let defending_side_alive_reserve_indices = defending_side.get_alive_pkmn_indices();

    state.reverse_instructions(&incoming_instructions.instruction_list);

    let num_alive_reserve = defending_side_alive_reserve_indices.len();
    if num_alive_reserve == 0 {
        frozen_instructions.push(incoming_instructions);
        return;
    }

    for pkmn_id in defending_side_alive_reserve_indices {
        let mut cloned_instructions = incoming_instructions.clone();
        state.apply_instructions(&cloned_instructions.instruction_list);
        generate_instructions_from_switch(
            state,
            pkmn_id,
            attacking_side_reference.get_other_side(),
            &mut cloned_instructions,
        );
        state.reverse_instructions(&cloned_instructions.instruction_list);
        cloned_instructions.update_percentage(1.0 / num_alive_reserve as f32);
        frozen_instructions.push(cloned_instructions);
    }
}

fn reset_damage_dealt(
    side: &Side,
    side_reference: &SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    // This creates instructions but does not modify the side
    // because this function is called before the state applies the instructions

    if side.damage_dealt.damage != 0 {
        incoming_instructions
            .instruction_list
            .push(Instruction::ChangeDamageDealtDamage(
                ChangeDamageDealtDamageInstruction {
                    side_ref: *side_reference,
                    damage_change: 0 - side.damage_dealt.damage,
                },
            ));
    }
    if side.damage_dealt.move_category != MoveCategory::Physical {
        incoming_instructions
            .instruction_list
            .push(Instruction::ChangeDamageDealtMoveCatagory(
                ChangeDamageDealtMoveCategoryInstruction {
                    side_ref: *side_reference,
                    move_category: MoveCategory::Physical,
                    previous_move_category: side.damage_dealt.move_category,
                },
            ));
    }
    if side.damage_dealt.hit_substitute {
        incoming_instructions
            .instruction_list
            .push(Instruction::ToggleDamageDealtHitSubstitute(
                ToggleDamageDealtHitSubstituteInstruction {
                    side_ref: *side_reference,
                },
            ));
    }
}

fn set_damage_dealt(
    attacking_side: &mut Side,
    attacking_side_ref: &SideReference,
    damage_dealt: i16,
    choice: &Choice,
    hit_substitute: bool,
    incoming_instructions: &mut StateInstructions,
) {
    if attacking_side.damage_dealt.damage != damage_dealt {
        incoming_instructions
            .instruction_list
            .push(Instruction::ChangeDamageDealtDamage(
                ChangeDamageDealtDamageInstruction {
                    side_ref: *attacking_side_ref,
                    damage_change: damage_dealt - attacking_side.damage_dealt.damage,
                },
            ));
        attacking_side.damage_dealt.damage = damage_dealt;
    }

    if attacking_side.damage_dealt.move_category != choice.category {
        incoming_instructions
            .instruction_list
            .push(Instruction::ChangeDamageDealtMoveCatagory(
                ChangeDamageDealtMoveCategoryInstruction {
                    side_ref: *attacking_side_ref,
                    move_category: choice.category,
                    previous_move_category: attacking_side.damage_dealt.move_category,
                },
            ));
        attacking_side.damage_dealt.move_category = choice.category;
    }

    if attacking_side.damage_dealt.hit_substitute != hit_substitute {
        incoming_instructions
            .instruction_list
            .push(Instruction::ToggleDamageDealtHitSubstitute(
                ToggleDamageDealtHitSubstituteInstruction {
                    side_ref: *attacking_side_ref,
                },
            ));
        attacking_side.damage_dealt.hit_substitute = hit_substitute;
    }
}

fn generate_instructions_from_damage(
    mut state: &mut State,
    choice: &mut Choice,
    calculated_damage: i16,
    attacking_side_ref: &SideReference,
    mut incoming_instructions: &mut StateInstructions,
) -> bool {
    /*
    TODO:
        - arbitrary other after_move as well from the old engine (triggers on hit OR miss)
            - dig/dive/bounce/fly volatilestatus
    */
    let mut hit_sub = false;
    let attacking_side = state.get_side(attacking_side_ref);
    let attacking_pokemon = attacking_side.get_active();

    if calculated_damage <= 0 {
        if let Some(crash_fraction) = choice.crash {
            let crash_amount = (attacking_pokemon.maxhp as f32 * crash_fraction) as i16;
            let damage_taken = cmp::min(crash_amount, attacking_pokemon.hp);
            let crash_instruction = Instruction::Damage(DamageInstruction {
                side_ref: *attacking_side_ref,
                damage_amount: damage_taken,
            });
            attacking_pokemon.hp -= damage_taken;
            incoming_instructions
                .instruction_list
                .push(crash_instruction);
        }
        return hit_sub;
    }

    let percent_hit = (choice.accuracy / 100.0).min(1.0);

    if percent_hit > 0.0 {
        let should_use_damage_dealt = state.use_damage_dealt;
        let (attacking_side, defending_side) = state.get_both_sides(attacking_side_ref);
        let attacking_pokemon = attacking_side.get_active();
        let mut damage_dealt;
        if defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SUBSTITUTE)
            && !choice.flags.sound
            && attacking_pokemon.ability != Abilities::INFILTRATOR
        {
            damage_dealt = cmp::min(calculated_damage, defending_side.substitute_health);
            let substitute_damage_dealt = cmp::min(calculated_damage, damage_dealt);
            let substitute_instruction = Instruction::DamageSubstitute(DamageInstruction {
                side_ref: attacking_side_ref.get_other_side(),
                damage_amount: substitute_damage_dealt,
            });
            defending_side.substitute_health -= substitute_damage_dealt;
            incoming_instructions
                .instruction_list
                .push(substitute_instruction);
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L44): a hit on the Substitute pops
            // an Air Balloon too (Showdown's onAfterSubDamage)
            if defending_side.get_active_immutable().item == Items::AIRBALLOON {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ChangeItem(ChangeItemInstruction {
                        side_ref: attacking_side_ref.get_other_side(),
                        current_item: Items::AIRBALLOON,
                        new_item: Items::NONE,
                    }));
                defending_side.get_active().item = Items::NONE;
            }

            if should_use_damage_dealt {
                set_damage_dealt(
                    attacking_side,
                    attacking_side_ref,
                    damage_dealt,
                    choice,
                    true,
                    &mut incoming_instructions,
                );
            }

            if defending_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE)
                && defending_side.substitute_health == 0
            {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: attacking_side_ref.get_other_side(),
                            volatile_status: PokemonVolatileStatus::SUBSTITUTE,
                        },
                    ));
                defending_side
                    .volatile_statuses
                    .remove(&PokemonVolatileStatus::SUBSTITUTE);
            }

            hit_sub = true;
        } else {
            let has_endure = defending_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::ENDURE);
            let attacking_pokemon = attacking_side.get_active();
            let defending_pokemon = defending_side.get_active();
            let mut knocked_out = false;
            damage_dealt = cmp::min(calculated_damage, defending_pokemon.hp);
            if damage_dealt != 0 {
                // alpha-poke patch (2026-10-16, doc/engine-diff.md L17): only a hit that would
                // knock it out leaves 1 HP, and a Focus Sash that does it is used up (Showdown:
                // Endure, then Sturdy, then the sash); before, any hit at full HP did 1 less
                // and the sash stayed
                let full = defending_pokemon.maxhp == defending_pokemon.hp;
                let sturdy = defending_pokemon.ability == Abilities::STURDY && full;
                let sash = defending_pokemon.item == Items::FOCUSSASH && full;
                if damage_dealt >= defending_pokemon.hp && (has_endure || sturdy || sash) {
                    damage_dealt -= 1;
                    if !has_endure && !sturdy {
                        incoming_instructions
                            .instruction_list
                            .push(Instruction::ChangeItem(ChangeItemInstruction {
                                side_ref: attacking_side_ref.get_other_side(),
                                current_item: Items::FOCUSSASH,
                                new_item: Items::NONE,
                            }));
                        defending_pokemon.item = Items::NONE;
                    }
                }

                if damage_dealt >= defending_pokemon.hp {
                    knocked_out = true;
                }

                let damage_instruction = Instruction::Damage(DamageInstruction {
                    side_ref: attacking_side_ref.get_other_side(),
                    damage_amount: damage_dealt,
                });
                defending_pokemon.hp -= damage_dealt;
                incoming_instructions
                    .instruction_list
                    .push(damage_instruction);

                if knocked_out
                    && defending_side
                        .volatile_statuses
                        .contains(&PokemonVolatileStatus::DESTINYBOND)
                {
                    let damage_instruction = Instruction::Damage(DamageInstruction {
                        side_ref: *attacking_side_ref,
                        damage_amount: attacking_pokemon.hp,
                    });
                    attacking_pokemon.hp = 0;
                    incoming_instructions
                        .instruction_list
                        .push(damage_instruction);
                }

                if should_use_damage_dealt {
                    set_damage_dealt(
                        attacking_side,
                        attacking_side_ref,
                        damage_dealt,
                        choice,
                        false,
                        &mut incoming_instructions,
                    );
                }

                let from = incoming_instructions.instruction_list.len();
                ability_after_damage_hit(
                    &mut state,
                    choice,
                    attacking_side_ref,
                    damage_dealt,
                    &mut incoming_instructions,
                );
                // (Sand Spit / Seed Sower: the defender sets it)
                extend_field_durations(
                    &mut state,
                    &attacking_side_ref.get_other_side(),
                    &mut incoming_instructions,
                    from,
                );
                // L75: the defender's HP berries at once -- unless Knock Off / Thief take the
                // berry first (their onAfterHit comes before the berry's onUpdate)
                let defender = state
                    .get_side_immutable(&attacking_side_ref.get_other_side())
                    .get_active_immutable();
                let removable = defender.item != Items::NONE && defender.item_can_be_removed();
                let taken = match choice.move_id {
                    Choices::KNOCKOFF => removable,
                    Choices::THIEF => {
                        removable
                            && state
                                .get_side_immutable(attacking_side_ref)
                                .get_active_immutable()
                                .item
                                == Items::NONE
                    }
                    _ => false,
                };
                if !taken {
                    super::items::berry_on_damage(
                        &mut state,
                        &attacking_side_ref.get_other_side(),
                        &mut incoming_instructions,
                    );
                }
            }
        }

        let attacking_pokemon = state.get_side(attacking_side_ref).get_active();
        if let Some(drain_fraction) = choice.drain {
            let mut drain_amount = (damage_dealt as f32 * drain_fraction) as i16;
            // alpha-poke patch (2026-10-16, L24): Big Root
            if attacking_pokemon.item == Items::BIGROOT {
                drain_amount = big_root(drain_amount);
            }
            let heal_amount =
                cmp::min(drain_amount, attacking_pokemon.maxhp - attacking_pokemon.hp);
            if heal_amount != 0 {
                let drain_instruction = Instruction::Heal(HealInstruction {
                    side_ref: *attacking_side_ref,
                    heal_amount: heal_amount,
                });
                attacking_pokemon.hp += heal_amount;
                incoming_instructions
                    .instruction_list
                    .push(drain_instruction);
            }
        }

        let attacking_pokemon = state.get_side(attacking_side_ref).get_active();
        if let Some(recoil_fraction) = choice.recoil {
            let recoil_amount = (damage_dealt as f32 * recoil_fraction) as i16;
            let damage_amount = cmp::min(recoil_amount, attacking_pokemon.hp);
            let recoil_instruction = Instruction::Damage(DamageInstruction {
                side_ref: *attacking_side_ref,
                damage_amount: damage_amount,
            });
            attacking_pokemon.hp -= damage_amount;
            incoming_instructions
                .instruction_list
                .push(recoil_instruction);
        }
        choice_after_damage_hit(
            &mut state,
            &choice,
            attacking_side_ref,
            &mut incoming_instructions,
            hit_sub,
        );
    }
    hit_sub
}

fn move_has_no_effect(state: &State, choice: &Choice, attacking_side_ref: &SideReference) -> bool {
    let (_attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);
    let defender = defending_side.get_active_immutable();

    #[cfg(not(any(feature = "gen4", feature = "gen5")))]
    if choice.flags.powder
        && choice.target == MoveTarget::Opponent
        && defender.has_type(&PokemonType::GRASS)
    {
        return true;
    }

    // alpha-poke patch (2026-10-13): Safety Goggles block powder moves
    if choice.flags.powder
        && choice.target == MoveTarget::Opponent
        && defender.item == Items::SAFETYGOGGLES
    {
        return true;
    }

    if choice.move_type == PokemonType::ELECTRIC
        && choice.target == MoveTarget::Opponent
        && defender.has_type(&PokemonType::GROUND)
    {
        return true;
    } else if choice.move_id == Choices::ENCORE {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L69): the side it lands on (its user's
        // when Magic Bounce reflects it), and it fails on an Encore (Encore cannot encore Encore)
        let target = if choice.target == MoveTarget::User {
            *attacking_side_ref
        } else {
            attacking_side_ref.get_other_side()
        };
        // (L101: nor on the other moves it cannot repeat -- Showdown's failencore -- or at 0 PP)
        let side = state.get_side_immutable(&target);
        return match side.last_used_move {
            LastUsedMove::None => true,
            LastUsedMove::Move(i) => {
                let m = &side.get_active_immutable().moves[&i];
                matches!(
                    m.id,
                    Choices::ENCORE
                        | Choices::SLEEPTALK
                        | Choices::COPYCAT
                        | Choices::METRONOME
                        | Choices::MIMIC
                        | Choices::SKETCH
                        | Choices::STRUGGLE
                        | Choices::TRANSFORM
                ) || m.pp <= 0
            }
            LastUsedMove::Switch(_) => true,
        };
    } else if state.terrain_is_active(&Terrain::PSYCHICTERRAIN)
        && defender.is_grounded()
        && choice.target == MoveTarget::Opponent
        && choice.priority > 0
    {
        return true;
    }
    false
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L41): Gen 9 Protean / Libero, once per entry
// (the typechange volatile), when the move starts (Showdown's onPrepareHit: not when it cannot
// move, not when the move's onTry fails: Sucker Punch, Poltergeist, ...), to the move's type
// unless the user is exactly that type already (Showdown compares getTypes().join(); before,
// only a user without the type, in ability_before_move: also when frozen / asleep / paralyzed)
#[cfg(any(feature = "gen9", feature = "champions"))]
fn protean_type_change(
    state: &mut State,
    choice: &Choice,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let (side, other) = state.get_both_sides(side_ref);
    let gassed = other.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS;
    let used = side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::TYPECHANGE);
    let active = side.get_active();
    if !matches!(active.ability, Abilities::PROTEAN | Abilities::LIBERO)
        || (gassed && active.item != Items::ABILITYSHIELD)
        || used
        || active.terastallized
        || choice.move_type == PokemonType::TYPELESS
    {
        return;
    }
    let failed = matches!(
        choice.move_id,
        Choices::SUCKERPUNCH | Choices::THUNDERCLAP | Choices::POLTERGEIST | Choices::UPPERHAND
    ) && choice.base_power == 0.0;
    let new_types = (choice.move_type, PokemonType::TYPELESS);
    if failed || active.types == new_types {
        return;
    }
    instructions
        .instruction_list
        .push(Instruction::ChangeType(ChangeType {
            side_ref: *side_ref,
            new_types,
            old_types: active.types,
        }));
    active.types = new_types;
    instructions
        .instruction_list
        .push(Instruction::ApplyVolatileStatus(
            ApplyVolatileStatusInstruction {
                side_ref: *side_ref,
                volatile_status: PokemonVolatileStatus::TYPECHANGE,
            },
        ));
    side.volatile_statuses
        .insert(PokemonVolatileStatus::TYPECHANGE);
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L60): Ogerpon terastallizing into its mask's
// type takes the Tera forme's Embody Aspect and its +1 (Showdown: the forme change, the ability's
// onStart); before, the old ability stayed
fn embody_aspect_on_tera(
    state: &mut State,
    side_ref: SideReference,
    instructions: &mut StateInstructions,
) {
    let side = state.get_side(&side_ref);
    let active = side.get_active();
    let (ability, stat, tera) = match active.id {
        PokemonName::OGERPON | PokemonName::OGERPONTEALTERA => (
            Abilities::EMBODYASPECTTEAL,
            PokemonBoostableStat::Speed,
            PokemonType::GRASS,
        ),
        PokemonName::OGERPONWELLSPRING | PokemonName::OGERPONWELLSPRINGTERA => (
            Abilities::EMBODYASPECTWELLSPRING,
            PokemonBoostableStat::SpecialDefense,
            PokemonType::WATER,
        ),
        PokemonName::OGERPONHEARTHFLAME | PokemonName::OGERPONHEARTHFLAMETERA => (
            Abilities::EMBODYASPECTHEARTHFLAME,
            PokemonBoostableStat::Attack,
            PokemonType::FIRE,
        ),
        PokemonName::OGERPONCORNERSTONE | PokemonName::OGERPONCORNERSTONETERA => (
            Abilities::EMBODYASPECTCORNERSTONE,
            PokemonBoostableStat::Defense,
            PokemonType::ROCK,
        ),
        _ => return,
    };
    if active.tera_type != tera {
        return;
    }
    if active.ability != ability {
        instructions
            .instruction_list
            .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
                side_ref,
                ability_change: ability as i16 - active.ability as i16,
            }));
        active.ability = ability;
    }
    apply_boost_instruction(side, &stat, &1, &side_ref, &side_ref, instructions);
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L36): Transform / Imposter (Showdown's
// transformInto): the target's types (its own, not its tera type), stats but HP, ability, boosts
// and moves (5 PP each); fails into a Substitute or a transformed target, or when transformed
pub fn transform_into(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let (side, foe) = state.get_both_sides(side_ref);
    let target = foe.get_active_immutable().clone();
    if target.hp == 0
        || side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::TRANSFORM)
        || foe
            .volatile_statuses
            .contains(&PokemonVolatileStatus::TRANSFORM)
        || foe
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SUBSTITUTE)
    {
        return;
    }
    let foe_boosts = [
        (PokemonBoostableStat::Attack, foe.attack_boost),
        (PokemonBoostableStat::Defense, foe.defense_boost),
        (
            PokemonBoostableStat::SpecialAttack,
            foe.special_attack_boost,
        ),
        (
            PokemonBoostableStat::SpecialDefense,
            foe.special_defense_boost,
        ),
        (PokemonBoostableStat::Speed, foe.speed_boost),
        (PokemonBoostableStat::Accuracy, foe.accuracy_boost),
        (PokemonBoostableStat::Evasion, foe.evasion_boost),
    ];
    let list = &mut instructions.instruction_list;
    let active = side.get_active();
    if active.types != target.types {
        list.push(Instruction::ChangeType(ChangeType {
            side_ref: *side_ref,
            new_types: target.types,
            old_types: active.types,
        }));
        active.types = target.types;
    }
    let stats = [
        (target.attack - active.attack, 0),
        (target.defense - active.defense, 1),
        (target.special_attack - active.special_attack, 2),
        (target.special_defense - active.special_defense, 3),
        (target.speed - active.speed, 4),
    ];
    for (amount, k) in stats {
        if amount == 0 {
            continue;
        }
        let c = ChangeStatInstruction {
            side_ref: *side_ref,
            amount,
        };
        list.push(match k {
            0 => Instruction::ChangeAttack(c),
            1 => Instruction::ChangeDefense(c),
            2 => Instruction::ChangeSpecialAttack(c),
            3 => Instruction::ChangeSpecialDefense(c),
            _ => Instruction::ChangeSpeed(c),
        });
    }
    active.attack = target.attack;
    active.defense = target.defense;
    active.special_attack = target.special_attack;
    active.special_defense = target.special_defense;
    active.speed = target.speed;
    if active.ability != target.ability {
        list.push(Instruction::ChangeAbility(ChangeAbilityInstruction {
            side_ref: *side_ref,
            ability_change: target.ability as i16 - active.ability as i16,
        }));
        active.ability = target.ability;
    }
    for index in [
        PokemonMoveIndex::M0,
        PokemonMoveIndex::M1,
        PokemonMoveIndex::M2,
        PokemonMoveIndex::M3,
    ] {
        let new = target.moves[&index].id;
        let m = &mut active.moves[&index];
        if m.id != new {
            list.push(Instruction::ChangeMove(ChangeMoveInstruction {
                side_ref: *side_ref,
                move_index: index,
                move_change: new as i16 - m.id as i16,
            }));
            m.id = new;
            m.choice = MOVES.get(&new).unwrap().to_owned();
        }
        let pp = if new == Choices::NONE { 0 } else { 5 };
        if m.pp != pp {
            list.push(Instruction::DecrementPP(DecrementPPInstruction {
                side_ref: *side_ref,
                move_index: index,
                amount: m.pp - pp,
            }));
            m.pp = pp;
        }
    }
    for (stat, b) in foe_boosts {
        let own = side.get_boost_from_boost_enum(&stat);
        if own != b {
            list.push(Instruction::Boost(BoostInstruction {
                side_ref: *side_ref,
                stat,
                amount: b - own,
            }));
            match stat {
                PokemonBoostableStat::Attack => side.attack_boost = b,
                PokemonBoostableStat::Defense => side.defense_boost = b,
                PokemonBoostableStat::SpecialAttack => side.special_attack_boost = b,
                PokemonBoostableStat::SpecialDefense => side.special_defense_boost = b,
                PokemonBoostableStat::Speed => side.speed_boost = b,
                PokemonBoostableStat::Accuracy => side.accuracy_boost = b,
                PokemonBoostableStat::Evasion => side.evasion_boost = b,
            }
        }
    }
    // (TYPECHANGE: the types go back on a switch, and the harness compares changed types so)
    for v in [
        PokemonVolatileStatus::TYPECHANGE,
        PokemonVolatileStatus::TRANSFORM,
    ] {
        if !side.volatile_statuses.contains(&v) {
            side.volatile_statuses.insert(v);
            list.push(Instruction::ApplyVolatileStatus(
                ApplyVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: v,
                },
            ));
        }
    }
}

fn cannot_use_move(state: &State, choice: &Choice, attacking_side_ref: &SideReference) -> bool {
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);

    // If the opponent has 0 hp, you can't use a non-status move
    if defending_side.get_active_immutable().hp == 0 && choice.category != MoveCategory::Status {
        return true;
    }

    // If you were taunted, you can't use a Physical/Special move
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L90): the move's own category (an attack
    // into Water Absorb, Volt Absorb, ... is a status move by now)
    if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::TAUNT)
        && MOVES
            .get(&choice.move_id)
            .map_or(choice.category, |m| m.category)
            == MoveCategory::Status
    {
        return true;
    } else if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::FLINCH)
    {
        return true;
    } else if choice.flags.heal
        && attacking_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::HEALBLOCK)
    {
        return true;
    } else if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::DISABLE)
        && choice.category != MoveCategory::Switch
        && choice.move_index as i8 == attacking_side.volatile_status_durations.disable / 8
    {
        // alpha-poke patch (L70): disabled after it chose it (Showdown's onBeforeMove)
        return true;
    }
    false
}

#[cfg(feature = "terastallization")]
fn terastallized_base_power_floor(
    state: &mut State,
    choice: &mut Choice,
    attacking_side: &SideReference,
) {
    let attacker = state
        .get_side_immutable(attacking_side)
        .get_active_immutable();

    if attacker.terastallized
        && choice.move_type == attacker.tera_type
        && choice.base_power < 60.0
        && choice.priority <= 0
        && choice.multi_hit() == MultiHitMove::None
        && choice.multi_accuracy() == MultiAccuracyMove::None
    {
        choice.base_power = 60.0;
    }
}

// alpha-poke patch: pub (was private)
pub fn before_move(
    state: &mut State,
    choice: &mut Choice,
    defender_choice: &Choice,
    attacking_side: &SideReference,
    incoming_instructions: &mut StateInstructions,
) {
    #[cfg(feature = "terastallization")]
    terastallized_base_power_floor(state, choice, attacking_side);

    ability_before_move(state, choice, attacking_side, incoming_instructions);
    item_before_move(state, choice, attacking_side, incoming_instructions);
    choice_before_move(state, choice, attacking_side, incoming_instructions);

    modify_choice(state, choice, defender_choice, attacking_side);

    ability_modify_attack_being_used(state, choice, defender_choice, attacking_side);
    ability_modify_attack_against(state, choice, defender_choice, attacking_side);

    item_modify_attack_being_used(state, choice, attacking_side);
    item_modify_attack_against(state, choice, attacking_side);

    /*
        TODO: this needs to be here because from_drag is called after the substitute volatilestatus
            has already been removed
    */
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side);
    if defending_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::SUBSTITUTE)
        && choice.category != MoveCategory::Status
    {
        choice.flags.drag = false;
    }

    // Update Choice for `charge` moves
    if choice.flags.charge {
        let charge_volatile_status = charge_choice_to_volatile(&choice.move_id);
        if !attacking_side
            .volatile_statuses
            .contains(&charge_volatile_status)
        {
            choice.remove_all_effects();
            choice.volatile_status = Some(VolatileStatus {
                target: MoveTarget::User,
                volatile_status: charge_volatile_status,
            });
        }
    }

    // modify choice if defender has protect active
    if (defending_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PROTECT)
        || defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SPIKYSHIELD)
        || defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::BANEFULBUNKER)
        || defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::BURNINGBULWARK)
        || defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SILKTRAP))
        && choice.flags.protect
    {
        choice.remove_effects_for_protect();
        if choice.crash.is_some() {
            choice.accuracy = 0.0;
        }

        if defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SPIKYSHIELD)
            && choice.flags.contact
        {
            choice.heal = Some(Heal {
                target: MoveTarget::User,
                amount: -0.125,
            })
        } else if defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::BANEFULBUNKER)
            && choice.flags.contact
        {
            choice.status = Some(Status {
                target: MoveTarget::User,
                status: PokemonStatus::POISON,
            })
        } else if defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::BURNINGBULWARK)
            && choice.flags.contact
        {
            choice.status = Some(Status {
                target: MoveTarget::User,
                status: PokemonStatus::BURN,
            })
        } else if defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SILKTRAP)
            && choice.flags.contact
        {
            choice.boost = Some(Boost {
                target: MoveTarget::User,
                boosts: StatBoosts {
                    attack: 0,
                    defense: 0,
                    special_attack: 0,
                    special_defense: 0,
                    speed: -1,
                    accuracy: 0,
                },
            })
        }
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L101): a branch where the mon cannot move
// (asleep, frozen, fully paralyzed, hitting itself in confusion) has not used its move (Showdown
// sets lastMove only when the move is used): this move's SetLastUsedMove undone in that branch
// (a Switch becomes None, as for a flinch: Fake Out / First Impression stay off)
fn undo_last_used_move(side_ref: &SideReference, ins: &mut StateInstructions) {
    let found = ins.instruction_list.iter().rev().find_map(|i| match i {
        Instruction::SetLastUsedMove(s) if s.side_ref == *side_ref => {
            Some((s.last_used_move, s.previous_last_used_move))
        }
        _ => None,
    });
    if let Some((now, before)) = found {
        if !matches!(now, LastUsedMove::Move(_)) {
            return;
        }
        let back = match before {
            LastUsedMove::Switch(_) => LastUsedMove::None,
            x => x,
        };
        if back != now {
            ins.instruction_list
                .push(Instruction::SetLastUsedMove(SetLastUsedMoveInstruction {
                    side_ref: *side_ref,
                    last_used_move: back,
                    previous_last_used_move: now,
                }));
        }
    }
}

fn generate_instructions_from_existing_status_conditions(
    state: &mut State,
    attacking_side_ref: &SideReference,
    attacker_choice: &Choice,
    incoming_instructions: &mut StateInstructions,
    final_instructions: &mut Vec<StateInstructions>,
) {
    let (attacking_side, _defending_side) = state.get_both_sides(attacking_side_ref);
    let current_active_index = attacking_side.active_index;
    let attacker_active = attacking_side.get_active();
    match attacker_active.status {
        PokemonStatus::PARALYZE => {
            // Fully-Paralyzed Branch
            let mut fully_paralyzed_instruction = incoming_instructions.clone();
            fully_paralyzed_instruction.update_percentage(FULLY_PARALYZED_CHANCE);
            undo_last_used_move(attacking_side_ref, &mut fully_paralyzed_instruction);
            final_instructions.push(fully_paralyzed_instruction);

            // Non-Paralyzed Branch
            incoming_instructions.update_percentage(1.0 - FULLY_PARALYZED_CHANCE);
        }
        PokemonStatus::FREEZE => {
            let mut still_frozen_instruction = incoming_instructions.clone();
            still_frozen_instruction.update_percentage(1.0 - THAW_CHANCE);
            undo_last_used_move(attacking_side_ref, &mut still_frozen_instruction);
            final_instructions.push(still_frozen_instruction);

            incoming_instructions.update_percentage(THAW_CHANCE);
            attacker_active.status = PokemonStatus::NONE;
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: attacking_side_ref.clone(),
                    pokemon_index: current_active_index,
                    old_status: PokemonStatus::FREEZE,
                    new_status: PokemonStatus::NONE,
                }));
        }
        PokemonStatus::SLEEP => {
            match attacker_active.rest_turns {
                // Pokemon is not asleep because of Rest.
                0 => {
                    let current_sleep_turns = attacker_active.sleep_turns;
                    // alpha-poke patch (2026-10-13): Early Bird's counter runs twice as fast
                    // (wakes on the first attempt 1/3, else on the second)
                    let chance_to_wake = if attacker_active.ability == Abilities::EARLYBIRD {
                        chance_to_wake_up(cmp::min(3, 2 * current_sleep_turns + 1))
                    } else {
                        chance_to_wake_up(current_sleep_turns)
                    };
                    if chance_to_wake == 1.0 {
                        attacker_active.status = PokemonStatus::NONE;
                        attacker_active.sleep_turns = 0;
                        incoming_instructions
                            .instruction_list
                            .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                                side_ref: *attacking_side_ref,
                                pokemon_index: current_active_index,
                                old_status: PokemonStatus::SLEEP,
                                new_status: PokemonStatus::NONE,
                            }));
                        incoming_instructions
                            .instruction_list
                            .push(Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                                side_ref: *attacking_side_ref,
                                pokemon_index: current_active_index,
                                new_turns: 0,
                                previous_turns: current_sleep_turns,
                            }));
                    } else if chance_to_wake == 0.0 {
                        if attacker_choice.move_id == Choices::SLEEPTALK {
                            // if we are using sleeptalk we want to continue using this move
                            incoming_instructions.instruction_list.push(
                                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    new_turns: current_sleep_turns + 1,
                                    previous_turns: current_sleep_turns,
                                }),
                            );
                        } else {
                            let mut still_asleep_instruction = incoming_instructions.clone();
                            still_asleep_instruction.update_percentage(1.0);
                            still_asleep_instruction.instruction_list.push(
                                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    new_turns: current_sleep_turns + 1,
                                    previous_turns: current_sleep_turns,
                                }),
                            );
                            undo_last_used_move(attacking_side_ref, &mut still_asleep_instruction);
                            final_instructions.push(still_asleep_instruction);
                            incoming_instructions.update_percentage(0.0);
                        }
                    } else {
                        // This code deals with the situation where there is a chance to wake up
                        // as well as a chance to stay asleep.
                        // This logic will branch the state and one branch will represent where
                        // nothing happens and the other will represent where something happens
                        // Normally "nothing happens" means you stay asleep and "something happens"
                        // means you wake up. If the move is sleeptalk these are reversed.
                        let do_nothing_percentage;
                        let mut do_nothing_instructions = incoming_instructions.clone();
                        if attacker_choice.move_id == Choices::SLEEPTALK {
                            do_nothing_percentage = chance_to_wake;
                            do_nothing_instructions.instruction_list.push(
                                Instruction::ChangeStatus(ChangeStatusInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    old_status: PokemonStatus::SLEEP,
                                    new_status: PokemonStatus::NONE,
                                }),
                            );
                            do_nothing_instructions.instruction_list.push(
                                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    new_turns: 0,
                                    previous_turns: current_sleep_turns,
                                }),
                            );
                            incoming_instructions.instruction_list.push(
                                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    new_turns: current_sleep_turns + 1,
                                    previous_turns: current_sleep_turns,
                                }),
                            );
                            attacker_active.sleep_turns += 1;
                        } else {
                            do_nothing_percentage = 1.0 - chance_to_wake;
                            do_nothing_instructions.instruction_list.push(
                                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    new_turns: current_sleep_turns + 1,
                                    previous_turns: current_sleep_turns,
                                }),
                            );
                            incoming_instructions
                                .instruction_list
                                .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    old_status: PokemonStatus::SLEEP,
                                    new_status: PokemonStatus::NONE,
                                }));
                            incoming_instructions.instruction_list.push(
                                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                                    side_ref: *attacking_side_ref,
                                    pokemon_index: current_active_index,
                                    new_turns: 0,
                                    previous_turns: current_sleep_turns,
                                }),
                            );
                            attacker_active.status = PokemonStatus::NONE;
                            attacker_active.sleep_turns = 0;
                        }
                        do_nothing_instructions.update_percentage(do_nothing_percentage);
                        incoming_instructions.update_percentage(1.0 - do_nothing_percentage);
                        if attacker_choice.move_id != Choices::SLEEPTALK {
                            undo_last_used_move(attacking_side_ref, &mut do_nothing_instructions);
                        }
                        final_instructions.push(do_nothing_instructions);
                    }
                }
                // Pokemon is asleep because of Rest, and will wake up this turn
                1 => {
                    attacker_active.status = PokemonStatus::NONE;
                    attacker_active.rest_turns -= 1;
                    incoming_instructions
                        .instruction_list
                        .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                            side_ref: *attacking_side_ref,
                            pokemon_index: current_active_index,
                            old_status: PokemonStatus::SLEEP,
                            new_status: PokemonStatus::NONE,
                        }));
                    incoming_instructions
                        .instruction_list
                        .push(Instruction::DecrementRestTurns(
                            DecrementRestTurnsInstruction {
                                side_ref: *attacking_side_ref,
                            },
                        ));
                }
                // Pokemon is asleep because of Rest, and will stay asleep this turn
                2 | 3 => {
                    attacker_active.rest_turns -= 1;
                    incoming_instructions
                        .instruction_list
                        .push(Instruction::DecrementRestTurns(
                            DecrementRestTurnsInstruction {
                                side_ref: *attacking_side_ref,
                            },
                        ));
                }
                _ => panic!("Invalid rest_turns value: {}", attacker_active.rest_turns),
            }
        }
        _ => {}
    }

    // alpha-poke patch (2026-10-11): confusion ends. Gen 9: 1-4 confused move attempts (uniform),
    // then the next attempt snaps out and acts normally; ``volatile_status_durations.confusion``
    // = confused attempts so far (the engine never counted it: confusion lasted until a switch).
    // One continuing branch per attempt (before_move's structure): the attempt counts, and the
    // self-hit chance is 1/3 of the chance the confusion has not ended yet at this attempt
    // (exact for the first attempt of a search, approximate later); after 4 it ends for sure.
    let mut confusion_self_hit = HIT_SELF_IN_CONFUSION_CHANCE;
    if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::CONFUSION)
    {
        let confused_attempts = attacking_side.volatile_status_durations.confusion;
        if confused_attempts >= 4 {
            attacking_side
                .volatile_statuses
                .remove(&PokemonVolatileStatus::CONFUSION);
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *attacking_side_ref,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                    },
                ));
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: *attacking_side_ref,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: -confused_attempts,
                    },
                ));
            attacking_side.volatile_status_durations.confusion = 0;
        } else {
            confusion_self_hit *= 1.0 - confusion_end_chance(confused_attempts);
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: *attacking_side_ref,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ));
            attacking_side.volatile_status_durations.confusion += 1;
        }
    }
    if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::CONFUSION)
        && confusion_self_hit > 0.0
    {
        let mut hit_yourself_instruction = incoming_instructions.clone();
        hit_yourself_instruction.update_percentage(confusion_self_hit);

        let attacking_stat = attacking_side.calculate_boosted_stat(PokemonBoostableStat::Attack);
        let defending_stat = attacking_side.calculate_boosted_stat(PokemonBoostableStat::Defense);

        let attacker_active = attacking_side.get_active();
        let mut damage_dealt = 2.0 * attacker_active.level as f32;
        damage_dealt = damage_dealt.floor() / 5.0;
        damage_dealt = damage_dealt.floor() + 2.0;
        damage_dealt = damage_dealt.floor() * 40.0; // 40 is the base power of confusion damage
        damage_dealt = damage_dealt * attacking_stat as f32 / defending_stat as f32;
        damage_dealt = damage_dealt.floor() / 50.0;
        damage_dealt = damage_dealt.floor() + 2.0;
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L54): Showdown's getConfusionDamage,
        // a roll (the 16 rolls' mean here) and no burn halving; before, the max roll, halved
        // when burned
        let base = damage_dealt as i32;
        let mean = (85..=100).map(|r| (base * r / 100).max(1)).sum::<i32>() / 16;

        let damage_dealt = cmp::min(mean as i16, attacker_active.hp);
        let damage_instruction = Instruction::Damage(DamageInstruction {
            side_ref: *attacking_side_ref,
            damage_amount: damage_dealt,
        });
        hit_yourself_instruction
            .instruction_list
            .push(damage_instruction);

        undo_last_used_move(attacking_side_ref, &mut hit_yourself_instruction);
        final_instructions.push(hit_yourself_instruction);

        incoming_instructions.update_percentage(1.0 - confusion_self_hit);
    }

    if attacking_side.side_conditions.protect > 0 {
        if let Some(vs) = &attacker_choice.volatile_status {
            if PROTECT_VOLATILES.contains(&vs.volatile_status) {
                let protect_success_chance =
                    CONSECUTIVE_PROTECT_CHANCE.powi(attacking_side.side_conditions.protect as i32);
                let mut protect_fail_instruction = incoming_instructions.clone();
                protect_fail_instruction.update_percentage(1.0 - protect_success_chance);
                final_instructions.push(protect_fail_instruction);
                incoming_instructions.update_percentage(protect_success_chance);
            }
        }
    }
}

pub fn generate_instructions_from_move(
    state: &mut State,
    choice: &mut Choice,
    defender_choice: &Choice,
    attacking_side: SideReference,
    mut incoming_instructions: StateInstructions,
    mut final_instructions: &mut Vec<StateInstructions>,
    branch_on_damage: bool,
) {
    if state.use_damage_dealt {
        reset_damage_dealt(
            state.get_side(&attacking_side),
            &attacking_side,
            &mut incoming_instructions,
        );
    }

    let attacker_side = state.get_side(&attacking_side);

    if choice.move_id == Choices::NONE {
        if attacker_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::MUSTRECHARGE)
        {
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: attacking_side,
                        volatile_status: PokemonVolatileStatus::MUSTRECHARGE,
                    },
                ));
        }
        final_instructions.push(incoming_instructions);
        return;
    }

    if attacker_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::TRUANT)
    {
        incoming_instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: attacking_side,
                    volatile_status: PokemonVolatileStatus::TRUANT,
                },
            ));
        final_instructions.push(incoming_instructions);
        return;
    }

    // TODO: test first-turn dragontail missing - it should not trigger this early return
    if !choice.first_move && defender_choice.flags.drag {
        final_instructions.push(incoming_instructions);
        return;
    }

    state.apply_instructions(&incoming_instructions.instruction_list);

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L8c): Glaive Rush's drawback ends when its
    // user moves again (Showdown: onBeforeMove, before anything else)
    let side = state.get_side(&attacking_side);
    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::GLAIVERUSH)
    {
        side.volatile_statuses
            .remove(&PokemonVolatileStatus::GLAIVERUSH);
        incoming_instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: attacking_side,
                    volatile_status: PokemonVolatileStatus::GLAIVERUSH,
                },
            ));
    }

    let side = state.get_side(&attacking_side);
    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::ENCORE)
    {
        match side.last_used_move {
            LastUsedMove::Move(last_used_move) => {
                if choice.move_index != last_used_move {
                    *choice = MOVES
                        .get(&side.get_active_immutable().moves[&last_used_move].id)
                        .unwrap()
                        .clone();
                    choice.move_index = last_used_move;
                }
            }
            _ => panic!("Encore should not be active when last used move is not a move"),
        }

        // alpha-poke patch (2026-10-16, doc/engine-diff.md L89): Encore's count is its ends of
        // turn (add_end_of_turn_instructions), not the encored moves
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L90): Taunt's count is its ends of turn
    // (add_end_of_turn_instructions), not the taunted moves

    // alpha-poke patch (2026-10-11): ejected (Eject Button) by the first move before moving: the
    // holder switches out instead of moving
    if !choice.first_move && state.get_side(&attacking_side).force_switch {
        state.reverse_instructions(&incoming_instructions.instruction_list);
        final_instructions.push(incoming_instructions);
        return;
    }

    if !choice.first_move
        && state
            .get_side(&attacking_side.get_other_side())
            .force_switch
    {
        state
            .get_side(&attacking_side)
            .switch_out_move_second_saved_move = choice.move_id;
        state.reverse_instructions(&incoming_instructions.instruction_list);
        final_instructions.push(incoming_instructions);
        return;
    }

    if state
        .get_side_immutable(&attacking_side)
        .get_active_immutable()
        .hp
        == 0
    {
        state.reverse_instructions(&incoming_instructions.instruction_list);
        final_instructions.push(incoming_instructions);
        return;
    }

    // If the move is a charge move, remove the volatile status if damage was done
    if choice.flags.charge {
        let side = state.get_side(&attacking_side);
        let volatile_status = charge_choice_to_volatile(&choice.move_id);
        if side.volatile_statuses.contains(&volatile_status) {
            choice.flags.charge = false;
            let instruction = Instruction::RemoveVolatileStatus(RemoveVolatileStatusInstruction {
                side_ref: attacking_side,
                volatile_status: volatile_status,
            });
            incoming_instructions.instruction_list.push(instruction);
            side.volatile_statuses.remove(&volatile_status);
        }
    }

    before_move(
        state,
        choice,
        defender_choice,
        &attacking_side,
        &mut incoming_instructions,
    );
    if incoming_instructions.percentage == 0.0 {
        state.reverse_instructions(&incoming_instructions.instruction_list);
        return;
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Metronome, the same move again counts
    // (Showdown's numConsecutive: 0 the first time, then 1, 2, ...), its damage x 4915 / 4096 per
    // count up to 2; another move or a switch starts over
    if state.use_last_used_move
        && state
            .get_side_immutable(&attacking_side)
            .get_active_immutable()
            .item
            == Items::METRONOME
    {
        let side = state.get_side(&attacking_side);
        let same = side.last_used_move == LastUsedMove::Move(choice.move_index);
        let count = side.volatile_status_durations.metronome;
        let new = if same { cmp::min(count + 1, 5) } else { 0 };
        if new != count {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: attacking_side,
                        volatile_status: PokemonVolatileStatus::METRONOME,
                        amount: new - count,
                    },
                ));
            side.volatile_status_durations.metronome = new;
        }
        let on = side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::METRONOME);
        if new > 0 && !on {
            incoming_instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref: attacking_side,
                        volatile_status: PokemonVolatileStatus::METRONOME,
                    },
                ));
            side.volatile_statuses
                .insert(PokemonVolatileStatus::METRONOME);
        } else if new == 0 && on {
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: attacking_side,
                        volatile_status: PokemonVolatileStatus::METRONOME,
                    },
                ));
            side.volatile_statuses
                .remove(&PokemonVolatileStatus::METRONOME);
        }
        if choice.category != MoveCategory::Status {
            choice.base_power *=
                [4096.0, 4915.0, 5734.0, 6553.0, 7372.0, 8192.0][new as usize] / 4096.0;
        }
    }

    if state.use_last_used_move {
        set_last_used_move_as_move(
            state.get_side(&attacking_side),
            choice.move_index,
            attacking_side,
            &mut incoming_instructions,
        );
    }

    if cannot_use_move(state, &choice, &attacking_side) {
        state.reverse_instructions(&incoming_instructions.instruction_list);
        final_instructions.push(incoming_instructions);
        return;
    }

    // alpha-poke patch (2026-10-13): Charge ends with the Electric move it powers (Gen 9); before,
    // it lasted until a switch. Its doubling goes into the base power here (damage_calc doubles
    // only while the volatile is on)
    if choice.move_type == PokemonType::ELECTRIC
        && choice.category != MoveCategory::Status
        && state
            .get_side_immutable(&attacking_side)
            .volatile_statuses
            .contains(&PokemonVolatileStatus::CHARGE)
    {
        choice.base_power *= 2.0;
        state
            .get_side(&attacking_side)
            .volatile_statuses
            .remove(&PokemonVolatileStatus::CHARGE);
        incoming_instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: attacking_side,
                    volatile_status: PokemonVolatileStatus::CHARGE,
                },
            ));
    }

    // most of the time pp decrement doesn't matter and just adds another instruction
    // so we only decrement pp if the move is at 10 or less pp since that is when it starts
    // to matter
    let unnerve = super::items::unnerved(state, &attacking_side);
    let (attacker_side, defender_side) = state.get_both_sides(&attacking_side);
    let active = attacker_side.get_active();
    if active.moves[&choice.move_index].pp < 10 {
        let pp_decrement_amount = if choice.target == MoveTarget::Opponent
            && defender_side.get_active_immutable().ability == Abilities::PRESSURE
        {
            2
        } else {
            1
        };
        incoming_instructions
            .instruction_list
            .push(Instruction::DecrementPP(DecrementPPInstruction {
                side_ref: attacking_side,
                move_index: choice.move_index,
                amount: pp_decrement_amount,
            }));
        active.moves[&choice.move_index].pp -= pp_decrement_amount;
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Leppa Berry, 10 PP back to a move
        // at 0, at most its max
        if active.item == Items::LEPPABERRY && active.moves[&choice.move_index].pp <= 0 && !unnerve
        {
            let back = cmp::min(10, choice.move_id.max_pp_below_10().unwrap_or(10))
                - active.moves[&choice.move_index].pp;
            incoming_instructions
                .instruction_list
                .push(Instruction::DecrementPP(DecrementPPInstruction {
                    side_ref: attacking_side,
                    move_index: choice.move_index,
                    amount: -back,
                }));
            active.moves[&choice.move_index].pp += back;
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: attacking_side,
                    current_item: Items::LEPPABERRY,
                    new_item: Items::NONE,
                }));
            active.item = Items::NONE;
            set_last_item(
                active,
                attacking_side,
                Items::LEPPABERRY,
                &mut incoming_instructions,
            );
        }
    }

    if !choice.sleep_talk_move {
        generate_instructions_from_existing_status_conditions(
            state,
            &attacking_side,
            &choice,
            &mut incoming_instructions,
            &mut final_instructions,
        );
    }
    let attacker = state
        .get_side_immutable(&attacking_side)
        .get_active_immutable();
    if choice.move_id == Choices::SLEEPTALK && attacker.status == PokemonStatus::SLEEP {
        let new_choices = attacker.get_sleep_talk_choices();
        state.reverse_instructions(&incoming_instructions.instruction_list);
        let num_choices = new_choices.len() as f32;
        for mut new_choice in new_choices {
            new_choice.sleep_talk_move = true;
            let mut sleep_talk_instructions = incoming_instructions.clone();
            sleep_talk_instructions.update_percentage(1.0 / num_choices);
            generate_instructions_from_move(
                state,
                &mut new_choice,
                defender_choice,
                attacking_side,
                sleep_talk_instructions,
                &mut final_instructions,
                false,
            );
        }
        return;
    } else if attacker.status == PokemonStatus::SLEEP && !choice.sleep_talk_move {
        state.reverse_instructions(&incoming_instructions.instruction_list);
        if incoming_instructions.percentage > 0.0 {
            undo_last_used_move(&attacking_side, &mut incoming_instructions);
            final_instructions.push(incoming_instructions);
        }
        return;
    }

    // alpha-poke patch (2026-10-14): the move starts (a marker for the search's history)
    incoming_instructions
        .instruction_list
        .push(Instruction::Acted(attacking_side));
    #[cfg(any(feature = "gen9", feature = "champions"))]
    protean_type_change(state, choice, &attacking_side, &mut incoming_instructions);

    if move_has_no_effect(state, &choice, &attacking_side) {
        // L22: a locked move without effect ends the lock
        let lock_end = lock_end_instructions(state, &attacking_side, false);
        // L50: a crash move into an immune target crashes (Showdown's onMoveFail)
        let crash = choice.crash.map(|f| {
            let user = state
                .get_side_immutable(&attacking_side)
                .get_active_immutable();
            cmp::min((user.maxhp as f32 * f) as i16, user.hp)
        });
        state.reverse_instructions(&incoming_instructions.instruction_list);
        incoming_instructions.instruction_list.extend(lock_end);
        if let Some(amount) = crash.filter(|a| *a > 0) {
            incoming_instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: attacking_side,
                    damage_amount: amount,
                }));
        }
        final_instructions.push(incoming_instructions);
        return;
    }
    let from = incoming_instructions.instruction_list.len();
    choice_special_effect(state, choice, &attacking_side, &mut incoming_instructions);
    extend_field_durations(state, &attacking_side, &mut incoming_instructions, from);
    // alpha-poke patch (2026-10-16, L14): a fixed damage (Seismic Toss, Ruination, ...) is dealt
    // as any damaging move's, without the rolls and the crits
    let fixed = fixed_damage(state, choice, &attacking_side);
    // L27: a screen breaker's damage without the screens it breaks (removed for the
    // calculation only: a miss keeps them)
    let screen_break = screen_break_instructions(state, choice, &attacking_side);
    state.apply_instructions(&screen_break);
    let damage = match fixed {
        Some(amount) => Some((amount, amount)),
        None => calculate_damage(state, &attacking_side, &choice, DamageRolls::Max),
    };
    state.reverse_instructions(&screen_break);
    check_move_hit_or_miss(
        state,
        &choice,
        &attacking_side,
        damage,
        &mut incoming_instructions,
        &mut final_instructions,
    );

    if incoming_instructions.percentage == 0.0 {
        state.reverse_instructions(&incoming_instructions.instruction_list);
        return;
    }

    // L27: it hit: the screens break
    for ins in screen_break {
        state.apply_one_instruction(&ins);
        incoming_instructions.instruction_list.push(ins);
    }

    // L22: a locked move Protect blocked (its effects removed by remove_effects_for_protect, the
    // lock's renewal with them) ends the lock
    let renews_lock = |c: &Choice| {
        c.volatile_status
            .as_ref()
            .is_some_and(|v| v.volatile_status == PokemonVolatileStatus::LOCKEDMOVE)
    };
    if !renews_lock(choice) && MOVES.get(&choice.move_id).is_some_and(|m| renews_lock(m)) {
        for ins in lock_end_instructions(state, &attacking_side, false) {
            state.apply_one_instruction(&ins);
            incoming_instructions.instruction_list.push(ins);
        }
    }

    // start multi-hit
    let hit_count;
    match choice.multi_hit() {
        MultiHitMove::None => {
            hit_count = 1;
        }
        MultiHitMove::DoubleHit => {
            hit_count = 2;
        }
        MultiHitMove::TripleHit => {
            hit_count = 3;
        }
        MultiHitMove::TwoToFiveHits => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L30): a branch per hit count below
            // (0 here); before, 3 (Loaded Dice 4)
            hit_count =
                if state.get_side(&attacking_side).get_active().ability == Abilities::SKILLLINK {
                    5
                } else {
                    0
                };
        }
        MultiHitMove::PopulationBomb => {
            // population bomb checks accuracy each time but lets approximate
            hit_count = if state.get_side(&attacking_side).get_active().item == Items::WIDELENS {
                9
            } else {
                6
            };
        }
        MultiHitMove::TripleAxel => {
            // triple axel checks accuracy each time but until multi-accuracy is implemented this
            // is the best we can do
            hit_count = 3
        }
    }

    // L30: 2-5 hits, 2 / 3 / 4 / 5 at 35 / 35 / 15 / 15% (Loaded Dice: 4 or 5, half each; Showdown's
    // sample); each count finishes the move in a branch of its own (finish_move reverses the
    // state, so a later one applies its instructions again; each gets the move as it was)
    let mut counts: Vec<(i8, f32, f32)> = if hit_count != 0 {
        vec![(hit_count, 1.0, 1.0)]
    } else if state
        .get_side_immutable(&attacking_side)
        .get_active_immutable()
        .item
        == Items::LOADEDDICE
    {
        vec![(4, 0.5, 1.0), (5, 0.5, 1.0)]
    } else {
        vec![
            (2, 0.35, 1.0),
            (3, 0.35, 1.0),
            (4, 0.15, 1.0),
            (5, 0.15, 1.0),
        ]
    };
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L58): Triple Axel / Triple Kick, each hit
    // checks accuracy and the move stops at a miss (the first check is check_move_hit_or_miss's):
    // k hits of the first hit's power x 1, 2, ..., k, as k hits of its mean (Showdown's 20 / 40
    // / 60 and 10 / 20 / 30; the engine's data: one power for all); Skill Link: one check
    if choice.multi_hit() == MultiHitMove::TripleAxel
        && state.get_side(&attacking_side).get_active().ability != Abilities::SKILLLINK
        && fixed.is_none()
    {
        let first = if choice.move_id == Choices::TRIPLEAXEL {
            20.0
        } else {
            10.0
        };
        let data = MOVES.get(&choice.move_id).map_or(first, |m| m.base_power);
        let a = (choice.accuracy / 100.0).min(1.0);
        counts = (1..=3)
            .map(|k| {
                let p = if k < 3 {
                    a.powi(k - 1) * (1.0 - a)
                } else {
                    a * a
                };
                (k as i8, p, first * (k + 1) as f32 / (2.0 * data))
            })
            .filter(|(_, p, _)| *p > 0.0)
            .collect();
    }
    // L58: Population Bomb, 10 hits each checking accuracy, stopping at a miss (Loaded Dice: one
    // check, 4-10 hits; Skill Link: 10); in four bands of counts (1-3, 4-6, 7-9, 10), each as its
    // mean count, for the branches (each count also splits by its crits); before, 6 hits
    if choice.multi_hit() == MultiHitMove::PopulationBomb && fixed.is_none() {
        let active = state.get_side(&attacking_side).get_active();
        let (ability, item) = (active.ability, active.item);
        let mut p = [0.0f32; 11];
        if ability == Abilities::SKILLLINK {
            p[10] = 1.0;
        } else if item == Items::LOADEDDICE {
            for k in 4..=10 {
                p[k] = 1.0 / 7.0;
            }
        } else {
            let a = (choice.accuracy / 100.0 * if item == Items::WIDELENS { 1.1 } else { 1.0 })
                .min(1.0);
            for k in 1..10 {
                p[k] = a.powi(k as i32 - 1) * (1.0 - a);
            }
            p[10] = a.powi(9);
        }
        counts = vec![(2i8, 1..4), (5, 4..7), (8, 7..10), (10, 10..11)]
            .into_iter()
            .map(|(n, band)| (n, band.map(|k| p[k]).sum::<f32>(), 1.0))
            .filter(|(_, q, _)| *q > 0.0)
            .collect();
    }
    // L71: Beat Up, a hit per hitter (its power the hitters' mean: modify_choice)
    if choice.move_id == Choices::BEATUP && fixed.is_none() {
        let n = super::choice_effects::beat_up_allies(state.get_side_immutable(&attacking_side))
            .len() as i8;
        counts = vec![(n.max(1), 1.0, 1.0)];
    }
    // L8b: Fickle Beam's double power, 30% (Showdown's onBasePower): a power branch
    if choice.move_id == Choices::FICKLEBEAM && fixed.is_none() {
        counts = vec![(1, 0.7, 1.0), (1, 0.3, 2.0)];
    }
    let original_choice = choice.clone();
    for (k, (n, p, power)) in counts.iter().enumerate() {
        let mut ins = incoming_instructions.clone();
        ins.update_percentage(*p);
        if k > 0 {
            state.apply_instructions(&ins.instruction_list);
            *choice = original_choice.clone();
        }
        let mut damage = damage;
        if *power != 1.0 {
            choice.base_power *= power;
            damage = calculate_damage(state, &attacking_side, choice, DamageRolls::Max);
        }
        // L30: each hit of a multi-hit move crits on its own (Showdown): k of n crits with the
        // binomial chance, the hits' average damage each (before: all or none)
        let crit = hit_crit_chance(state, &attacking_side, choice);
        let split = *n > 1 && fixed.is_none() && damage.is_some();
        if !split {
            finish_move(
                state,
                choice,
                defender_choice,
                attacking_side,
                ins,
                final_instructions,
                branch_on_damage,
                damage,
                fixed,
                *n,
                None,
            );
            continue;
        }
        let (max, max_crit) = damage.unwrap();
        let (normal, critical) = (max as f32 * 0.925, max_crit as f32 * 0.925);
        // L34: each hit's exact rolls (else 85-100% of its max)
        let linear = |m: i16| {
            let mut r = [0i16; 16];
            for (i, x) in r.iter_mut().enumerate() {
                *x = (m as f32 * (0.85 + 0.01 * i as f32)) as i16;
            }
            r
        };
        // (computed once per hit count, only when a total can reach the target's HP)
        let target_hp = state
            .get_side_immutable(&attacking_side.get_other_side())
            .get_active_immutable()
            .hp as i32;
        let (normal_rolls, crit_rolls) =
            if branch_on_damage && *n as i32 * max_crit as i32 >= target_hp {
                damage_rolls(state, &attacking_side, choice)
                    .filter(|(r, c)| r[15] == max && c[15] == max_crit)
                    .unwrap_or((linear(max), linear(max_crit)))
            } else {
                (linear(max), linear(max_crit))
            };
        let hits = *n as i32;
        let before = choice.clone();
        let hp = state
            .get_side_immutable(&attacking_side.get_other_side())
            .get_active_immutable()
            .hp as i32;
        // the state has `ins` applied until a finish_move reverses it
        let mut applied = true;
        for crits in 0..=hits {
            let ways = (0..crits).fold(1.0, |a, i| a * (hits - i) as f32 / (i + 1) as f32);
            let chance = ways * crit.powi(crits) * (1.0 - crit).powi(hits - crits);
            if chance <= 0.0 {
                continue;
            }
            // the hits' total against the HP: its rolls decide a knockout near it (each hit's own
            // roll: multi_hit_kill)
            let total_max = (hits - crits) * max as i32 + crits * max_crit as i32;
            let mut parts = vec![(
                1.0,
                ((hits - crits) as f32 * normal + crits as f32 * critical) / hits as f32,
            )];
            if branch_on_damage && total_max >= hp && (total_max as f32 * 0.85) < hp as f32 {
                let mut per_hit = vec![normal_rolls; (hits - crits) as usize];
                per_hit.extend(vec![crit_rolls; crits as usize]);
                let (kill, non_kill) = multi_hit_kill(&per_hit, hp);
                parts = vec![
                    (1.0 - kill, non_kill / hits as f32),
                    (kill, (hp as f32 / hits as f32).ceil()),
                ];
            }
            for (share, per_hit) in parts.iter() {
                if *share <= 0.0 {
                    continue;
                }
                let mut part = ins.clone();
                part.update_percentage(chance * share);
                if !applied {
                    state.apply_instructions(&part.instruction_list);
                    *choice = before.clone();
                }
                finish_move(
                    state,
                    choice,
                    defender_choice,
                    attacking_side,
                    part,
                    final_instructions,
                    branch_on_damage,
                    damage,
                    fixed,
                    *n,
                    Some(*per_hit as i16),
                );
                applied = false;
            }
        }
        if applied {
            state.reverse_instructions(&ins.instruction_list);
        }
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L109): a side's net end-of-turn HP loss this
// turn as far as the state tells it (its status, Salt Cure, Leech Seed, a partial trap, Curse, sand,
// Sticky Barb / Black Sludge, less Leftovers / Black Sludge / Poison Heal / Grassy Terrain); only
// where the surviving rolls split (an approximation there is a coarser split, not a wrong one)
fn expected_residual(state: &State, side_ref: &SideReference) -> i16 {
    let side = state.get_side_immutable(side_ref);
    let p = side.get_active_immutable();
    let m = p.maxhp;
    let has = |v: PokemonVolatileStatus| side.volatile_statuses.contains(&v);
    let poison_heal = p.ability == Abilities::POISONHEAL;
    let mut loss = 0;
    if p.ability != Abilities::MAGICGUARD {
        loss += match p.status {
            PokemonStatus::BURN => m / 16,
            PokemonStatus::POISON if !poison_heal => m / 8,
            PokemonStatus::TOXIC if !poison_heal => {
                m * (side.side_conditions.toxic_count as i16 + 1) / 16
            }
            _ => 0,
        };
        if has(PokemonVolatileStatus::LEECHSEED) || has(PokemonVolatileStatus::PARTIALLYTRAPPED) {
            loss += m / 8
                * (has(PokemonVolatileStatus::LEECHSEED) as i16
                    + has(PokemonVolatileStatus::PARTIALLYTRAPPED) as i16);
        }
        if has(PokemonVolatileStatus::SALTCURE) {
            let hurt = p.has_type(&PokemonType::WATER) || p.has_type(&PokemonType::STEEL);
            loss += if hurt { m / 4 } else { m / 8 };
        }
        if has(PokemonVolatileStatus::CURSE) {
            loss += m / 4;
        }
        if state.weather_is_active(&Weather::SAND)
            && !p.has_type(&PokemonType::ROCK)
            && !p.has_type(&PokemonType::GROUND)
            && !p.has_type(&PokemonType::STEEL)
            && !matches!(
                p.ability,
                Abilities::OVERCOAT
                    | Abilities::SANDVEIL
                    | Abilities::SANDRUSH
                    | Abilities::SANDFORCE
            )
            && p.item != Items::SAFETYGOGGLES
        {
            loss += m / 16;
        }
        if p.item == Items::STICKYBARB
            || (p.item == Items::BLACKSLUDGE && !p.has_type(&PokemonType::POISON))
        {
            loss += m / 8;
        }
    }
    let mut gain = 0;
    if !has(PokemonVolatileStatus::HEALBLOCK) {
        if p.item == Items::LEFTOVERS
            || (p.item == Items::BLACKSLUDGE && p.has_type(&PokemonType::POISON))
        {
            gain += m / 16;
        }
        if poison_heal && matches!(p.status, PokemonStatus::POISON | PokemonStatus::TOXIC) {
            gain += m / 8;
        }
        if state.terrain_is_active(&Terrain::GRASSYTERRAIN) && p.is_grounded() {
            gain += m / 16;
        }
    }
    loss - gain
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L30): the rest of generate_instructions_from_move
// after the hit count (the damage branches, run_move), once per hit count
#[allow(clippy::too_many_arguments)]
fn finish_move(
    state: &mut State,
    choice: &mut Choice,
    defender_choice: &Choice,
    attacking_side: SideReference,
    mut incoming_instructions: StateInstructions,
    mut final_instructions: &mut Vec<StateInstructions>,
    branch_on_damage: bool,
    damage: Option<(i16, i16)>,
    fixed: Option<i16>,
    hit_count: i8,
    per_hit: Option<i16>,
) {
    let crit_stage_chance = crit_stage_chance(state, &attacking_side, choice);
    let mut does_damage = false;
    let (mut branch_damage, mut regular_damage) = (0, 0);
    let mut branch_instructions: Option<StateInstructions> = None;
    let mut crit_kill_branch: Option<StateInstructions> = None;
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L92): what the hit can knock out: the
    // Substitute's HP when it hits the Substitute (its break splits by the rolls, as a
    // knockout), else the target's HP
    let target_hp = {
        let (att, def) = state.get_both_sides_immutable(&attacking_side);
        if def
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SUBSTITUTE)
            && !choice.flags.sound
            && att.get_active_immutable().ability != Abilities::INFILTRATOR
        {
            def.substitute_health
        } else {
            def.get_active_immutable().hp
        }
    };
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L109): the HP below which the target falls at
    // the end of this turn (its predictable end-of-turn loss: expected_residual); the surviving
    // rolls split there into two branches, like a knockout. Not on a Substitute
    let residual_thr = {
        let def = state.get_side_immutable(&attacking_side.get_other_side());
        let r = expected_residual(state, &attacking_side.get_other_side());
        if target_hp == def.get_active_immutable().hp && r > 0 && r < target_hp {
            Some(target_hp - r)
        } else {
            None
        }
    };
    // the surviving rolls of the regular branch, (weight, damage), when they are known exactly
    let mut regular_rolls: Option<Vec<(f32, i16)>> = None;
    if let Some((max_damage_dealt, max_crit_damage)) = damage {
        does_damage = true;
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L42): a guaranteed crit's damage is
        // its crit's, rolls and knockout included (before: the knockout branch looked at the
        // non-crit max, a crit's average otherwise)
        let sure_crit = choice.move_id.guaranteed_crit() && {
            let d = state
                .get_side_immutable(&attacking_side.get_other_side())
                .get_active_immutable();
            d.ability != Abilities::BATTLEARMOR && d.ability != Abilities::SHELLARMOR
        };
        let max_damage_dealt = if sure_crit && per_hit.is_none() && fixed.is_none() {
            max_crit_damage
        } else {
            max_damage_dealt
        };
        let avg_damage_dealt = (max_damage_dealt as f32 * 0.925) as i16;
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L34): near a knockout, the exact 16
        // rolls (Showdown's rounding) when the state still gives this max (else the rolls of
        // 85-100% of it); computed only there (a second damage calculation)
        let near_ko = branch_on_damage
            && per_hit.is_none()
            && fixed.is_none()
            && max_damage_dealt >= residual_thr.unwrap_or(target_hp);
        let exact = if near_ko {
            damage_rolls(state, &attacking_side, choice)
                .map(|(r, c)| if sure_crit { (c, c) } else { (r, c) })
                .filter(|(r, c)| r[15] == max_damage_dealt && c[15] == max_crit_damage)
        } else {
            None
        };
        let (_attacker_side, defender_side) = state.get_both_sides(&attacking_side);
        let defender_active = defender_side.get_active();
        let min_damage_dealt = match exact {
            Some((r, _)) => r[0],
            None => (max_damage_dealt as f32 * 0.85) as i16,
        };
        if let Some(d) = per_hit {
            // L30: a multi-hit branch with its number of crits decided (the dispatch)
            regular_damage = d;
        } else if fixed.is_some() {
            regular_damage = max_damage_dealt;
        } else if branch_on_damage && max_damage_dealt >= target_hp && min_damage_dealt < target_hp
        {
            let crit_rate = if defender_active.ability == Abilities::BATTLEARMOR
                || defender_active.ability == Abilities::SHELLARMOR
            {
                0.0
            } else if choice.move_id.guaranteed_crit() {
                1.0
            } else {
                crit_stage_chance
            };

            // the chance of a branch is the chance of the roll killing + the chance of a crit
            // (L34, exact rolls: a crit's own rolls, the non-kill damage averaged over both)
            let (branch_chance, average_non_kill_damage) = match exact {
                Some((rolls, crit_rolls)) => {
                    let hp = target_hp;
                    let part = |rs: &[i16; 16], w: f32| {
                        let alive: Vec<f32> =
                            rs.iter().filter(|d| **d < hp).map(|d| *d as f32).collect();
                        (
                            w * (16 - alive.len()) as f32 / 16.0,
                            w * alive.iter().sum::<f32>() / 16.0,
                        )
                    };
                    let (kill_n, sum_n) = part(&rolls, 1.0 - crit_rate);
                    let (kill_c, sum_c) = part(&crit_rolls, crit_rate);
                    regular_rolls = Some(
                        rolls
                            .iter()
                            .filter(|d| **d < hp)
                            .map(|d| ((1.0 - crit_rate) / 16.0, *d))
                            .chain(
                                crit_rolls
                                    .iter()
                                    .filter(|d| **d < hp)
                                    .map(|d| (crit_rate / 16.0, *d)),
                            )
                            .collect(),
                    );
                    let kill = kill_n + kill_c;
                    let avg = if kill < 1.0 {
                        ((sum_n + sum_c) / (1.0 - kill)) as i16
                    } else {
                        0
                    };
                    (kill, avg)
                }
                None => {
                    let (average_non_kill_damage, num_kill_rolls) =
                        compare_health_with_damage_multiples(max_damage_dealt, target_hp);
                    (
                        ((1.0 - crit_rate) * (num_kill_rolls as f32 / 16.0)) + crit_rate,
                        average_non_kill_damage,
                    )
                }
            };

            let mut branch_ins = incoming_instructions.clone();
            branch_ins.update_percentage(branch_chance);
            branch_instructions = Some(branch_ins);
            branch_damage = target_hp;

            incoming_instructions.update_percentage(1.0 - branch_chance);
            regular_damage = average_non_kill_damage;
        } else if branch_on_damage && max_damage_dealt < target_hp {
            let crit_rate = if defender_active.ability == Abilities::BATTLEARMOR
                || defender_active.ability == Abilities::SHELLARMOR
            {
                0.0
            } else if choice.move_id.guaranteed_crit() {
                1.0
            } else {
                crit_stage_chance
            };
            let mut branch_ins = incoming_instructions.clone();
            branch_ins.update_percentage(crit_rate);
            branch_damage = (max_crit_damage as f32 * 0.925) as i16;
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L51): a crit that can knock out
            // splits by its exact rolls into a knockout and the rest (before: its average,
            // a knockout whenever that reached the HP)
            let hp = target_hp;
            if crit_rate > 0.0 && max_crit_damage >= hp && per_hit.is_none() && fixed.is_none() {
                if let Some((_, c)) = damage_rolls(state, &attacking_side, choice)
                    .filter(|(r, c)| r[15] == max_damage_dealt && c[15] == max_crit_damage)
                {
                    let alive: Vec<f32> =
                        c.iter().filter(|d| **d < hp).map(|d| *d as f32).collect();
                    let kill = (16 - alive.len()) as f32 / 16.0;
                    if !alive.is_empty() {
                        let mut kill_ins = incoming_instructions.clone();
                        kill_ins.update_percentage(crit_rate * kill);
                        crit_kill_branch = Some(kill_ins);
                        branch_ins = incoming_instructions.clone();
                        branch_ins.update_percentage(crit_rate * (1.0 - kill));
                        branch_damage = (alive.iter().sum::<f32>() / alive.len() as f32) as i16;
                    }
                }
            }
            branch_instructions = Some(branch_ins);
            incoming_instructions.update_percentage(1.0 - crit_rate);
            regular_damage = (max_damage_dealt as f32 * 0.925) as i16;
            if let Some((r, _)) = exact {
                regular_rolls = Some(r.iter().map(|d| (1.0 / 16.0, *d)).collect());
            }
        } else if choice.move_id.guaranteed_crit()
            && defender_active.ability != Abilities::BATTLEARMOR
            && defender_active.ability != Abilities::SHELLARMOR
        {
            regular_damage = (max_crit_damage as f32 * 0.925) as i16;
        } else {
            regular_damage = avg_damage_dealt;
        }
    }

    // L109: the surviving rolls split at the end-of-turn knockout
    let mut residual_branch: Option<(StateInstructions, i16)> = None;
    if let (Some(thr), Some(rs)) = (residual_thr, regular_rolls.as_ref()) {
        let (survive, fall): (Vec<(f32, i16)>, Vec<(f32, i16)>) =
            rs.iter().partition(|(_, d)| *d < thr);
        let w = |v: &Vec<(f32, i16)>| v.iter().map(|(w, _)| *w).sum::<f32>();
        let avg = |v: &Vec<(f32, i16)>| {
            (v.iter().map(|(w, d)| *w * *d as f32).sum::<f32>() / w(v)) as i16
        };
        if !survive.is_empty() && !fall.is_empty() && incoming_instructions.percentage > 0.0 {
            let share = w(&fall) / (w(&survive) + w(&fall));
            let mut fall_ins = incoming_instructions.clone();
            fall_ins.update_percentage(share);
            incoming_instructions.update_percentage(1.0 - share);
            regular_damage = avg(&survive);
            residual_branch = Some((fall_ins, avg(&fall)));
        }
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Focus Band, a 1/10 chance to survive
    // a hit that would knock its holder out, at 1 HP (Showdown's onDamage; not through a
    // Substitute): a knockout path splits into 9/10 and 1/10 with the damage the HP less 1
    let band_hp = {
        let side = state.get_side_immutable(&attacking_side.get_other_side());
        let defender = side.get_active_immutable();
        let behind_sub = side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SUBSTITUTE)
            && !choice.flags.sound;
        if does_damage && defender.item == Items::FOCUSBAND && defender.hp > 0 && !behind_sub {
            Some(defender.hp)
        } else {
            None
        }
    };
    let band_split = |ins: &mut StateInstructions, damage: i16| -> Option<StateInstructions> {
        let hp = band_hp?;
        if damage as i32 * hit_count as i32 >= hp as i32 && ins.percentage > 0.0 {
            let mut survive = ins.clone();
            survive.update_percentage(0.1);
            ins.update_percentage(0.9);
            Some(survive)
        } else {
            None
        }
    };
    let regular_band = band_split(&mut incoming_instructions, regular_damage);
    let mut branch_instructions = branch_instructions;
    let branch_band = match branch_instructions.as_mut() {
        Some(b) => band_split(b, branch_damage),
        None => None,
    };
    // (L92: the Substitute's HP when the hit is on it)
    let kill_hp = target_hp;
    let crit_kill_band = match crit_kill_branch.as_mut() {
        Some(b) => band_split(b, kill_hp),
        None => None,
    };

    let starf_from = final_instructions.len();
    if incoming_instructions.percentage != 0.0 {
        run_move(
            state,
            attacking_side,
            incoming_instructions,
            hit_count,
            does_damage,
            regular_damage,
            choice,
            defender_choice,
            &mut final_instructions,
        );
    } else {
        state.reverse_instructions(&incoming_instructions.instruction_list);
    }

    // L109: the rolls that leave the target to fall at the end of the turn
    if let Some((fall_ins, fall_damage)) = residual_branch {
        if fall_ins.percentage != 0.0 {
            state.apply_instructions(&fall_ins.instruction_list);
            run_move(
                state,
                attacking_side,
                fall_ins,
                hit_count,
                does_damage,
                fall_damage,
                choice,
                defender_choice,
                &mut final_instructions,
            );
        }
    }

    // A branch representing either a roll that kills the opponent or a crit
    if let Some(branch_ins) = branch_instructions {
        if branch_ins.percentage != 0.0 {
            state.apply_instructions(&branch_ins.instruction_list);
            run_move(
                state,
                attacking_side,
                branch_ins,
                hit_count,
                does_damage,
                branch_damage,
                choice,
                defender_choice,
                &mut final_instructions,
            );
        }
    }

    // L51: a crit's knockout
    if let Some(kill_ins) = crit_kill_branch {
        if kill_ins.percentage != 0.0 {
            state.apply_instructions(&kill_ins.instruction_list);
            run_move(
                state,
                attacking_side,
                kill_ins,
                hit_count,
                does_damage,
                kill_hp,
                choice,
                defender_choice,
                &mut final_instructions,
            );
        }
    }

    // L24: the Focus Band paths (one hit for the HP less 1)
    for survive in vec![regular_band, branch_band, crit_kill_band]
        .into_iter()
        .flatten()
    {
        let hp = band_hp.unwrap();
        state.apply_instructions(&survive.instruction_list);
        run_move(
            state,
            attacking_side,
            survive,
            1,
            does_damage,
            hp - 1,
            choice,
            defender_choice,
            &mut final_instructions,
        );
    }

    // L24: Starf Berry after each hit
    starf_berry_branches(state, &mut final_instructions, starf_from);

    combine_duplicate_instructions(final_instructions);
}

fn combine_duplicate_instructions(list_of_instructions: &mut Vec<StateInstructions>) {
    for i in 0..list_of_instructions.len() {
        let mut j = i + 1;
        while j < list_of_instructions.len() {
            if list_of_instructions[i].instruction_list == list_of_instructions[j].instruction_list
            {
                list_of_instructions[i].percentage += list_of_instructions[j].percentage;
                list_of_instructions.remove(j);
            } else {
                j += 1;
            }
        }
    }
}

fn get_effective_speed(state: &State, side_reference: &SideReference) -> i16 {
    let side = state.get_side_immutable(side_reference);
    let active_pkmn = side.get_active_immutable();

    let mut boosted_speed = side.calculate_boosted_stat(PokemonBoostableStat::Speed) as f32;

    match state.weather.weather_type {
        Weather::SUN | Weather::HARSHSUN if active_pkmn.ability == Abilities::CHLOROPHYLL => {
            boosted_speed *= 2.0
        }
        Weather::RAIN | Weather::HEAVYRAIN if active_pkmn.ability == Abilities::SWIFTSWIM => {
            boosted_speed *= 2.0
        }
        Weather::SAND if active_pkmn.ability == Abilities::SANDRUSH => boosted_speed *= 2.0,
        Weather::HAIL if active_pkmn.ability == Abilities::SLUSHRUSH => boosted_speed *= 2.0,
        _ => {}
    }

    match active_pkmn.ability {
        Abilities::SURGESURFER if state.terrain.terrain_type == Terrain::ELECTRICTERRAIN => {
            boosted_speed *= 2.0
        }
        Abilities::UNBURDEN
            if side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::UNBURDEN) =>
        {
            boosted_speed *= 2.0
        }
        Abilities::QUICKFEET if active_pkmn.status != PokemonStatus::NONE => boosted_speed *= 1.5,
        _ => {}
    }
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): the Power items halve the Speed
    if matches!(
        active_pkmn.item,
        Items::POWERANKLET
            | Items::POWERBAND
            | Items::POWERBELT
            | Items::POWERBRACER
            | Items::POWERLENS
            | Items::POWERWEIGHT
    ) {
        boosted_speed *= 0.5;
    }

    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::SLOWSTART)
    {
        boosted_speed *= 0.5;
    }

    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PROTOSYNTHESISSPE)
        || side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::QUARKDRIVESPE)
    {
        boosted_speed *= 1.5;
    }

    if side.side_conditions.tailwind > 0 {
        boosted_speed *= 2.0
    }

    match active_pkmn.item {
        Items::IRONBALL => boosted_speed *= 0.5,
        Items::CHOICESCARF => boosted_speed *= 1.5,
        _ => {}
    }

    if active_pkmn.status == PokemonStatus::PARALYZE && active_pkmn.ability != Abilities::QUICKFEET
    {
        boosted_speed *= PARALYSIS_SPEED_MULTIPLIER;
    }

    boosted_speed as i16
}

fn modify_choice_priority(state: &State, side_reference: &SideReference, choice: &mut Choice) {
    let side = state.get_side_immutable(side_reference);
    let active_pkmn = side.get_active_immutable();

    if choice.move_id == Choices::GRASSYGLIDE && state.terrain_is_active(&Terrain::GRASSYTERRAIN) {
        choice.priority += 1;
    }

    match active_pkmn.ability {
        Abilities::PRANKSTER if choice.category == MoveCategory::Status => choice.priority += 1,
        Abilities::GALEWINGS
            if choice.move_type == PokemonType::FLYING && active_pkmn.hp == active_pkmn.maxhp =>
        {
            choice.priority += 1
        }
        Abilities::TRIAGE if choice.flags.heal => choice.priority += 3,
        _ => {}
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L24): the chance side one moves first, with
// Quick Claw (Showdown's onFractionalPriority: a 1/5 chance each, at priority 0 or less, of +0.1:
// one alone that procs goes first, both or neither leave it to the speeds)
fn quick_claw_first_chance(
    state: &State,
    side_one_choice: &Choice,
    side_two_choice: &Choice,
    order: &SideMovesFirst,
    custap: bool,
) -> f32 {
    let base = match order {
        SideMovesFirst::SideOne => 1.0,
        SideMovesFirst::SideTwo => 0.0,
        SideMovesFirst::SpeedTie => 0.5,
    };
    let either_switches = side_one_choice.category == MoveCategory::Switch
        || side_two_choice.category == MoveCategory::Switch;
    if custap || either_switches || side_one_choice.priority != side_two_choice.priority {
        return base;
    }
    let procs = |side: &Side, choice: &Choice| -> f32 {
        let active = side.get_active_immutable();
        if active.item == Items::QUICKCLAW
            && choice.priority <= 0
            && !(choice.category == MoveCategory::Status
                && active.ability == Abilities::MYCELIUMMIGHT)
        {
            0.2
        } else {
            0.0
        }
    };
    let (a1, a2) = (
        procs(&state.side_one, side_one_choice),
        procs(&state.side_two, side_two_choice),
    );
    a1 * (1.0 - a2) + (a1 * a2 + (1.0 - a1) * (1.0 - a2)) * base
}

fn moves_first(
    state: &State,
    side_one_choice: &Choice,
    side_two_choice: &Choice,
    incoming_instructions: &mut StateInstructions,
) -> SideMovesFirst {
    let side_one_effective_speed = get_effective_speed(&state, &SideReference::SideOne);
    let side_two_effective_speed = get_effective_speed(&state, &SideReference::SideTwo);

    if side_one_choice.category == MoveCategory::Switch
        && side_two_choice.category == MoveCategory::Switch
    {
        return if side_one_effective_speed > side_two_effective_speed {
            SideMovesFirst::SideOne
        } else if side_one_effective_speed == side_two_effective_speed {
            SideMovesFirst::SpeedTie
        } else {
            SideMovesFirst::SideTwo
        };
    } else if side_one_choice.category == MoveCategory::Switch {
        return if side_two_choice.move_id != Choices::PURSUIT {
            SideMovesFirst::SideOne
        } else {
            SideMovesFirst::SideTwo
        };
    } else if side_two_choice.category == MoveCategory::Switch {
        return if side_one_choice.move_id == Choices::PURSUIT {
            SideMovesFirst::SideOne
        } else {
            SideMovesFirst::SideTwo
        };
    }

    let side_one_active = state.side_one.get_active_immutable();
    let side_two_active = state.side_two.get_active_immutable();
    if side_one_choice.priority == side_two_choice.priority {
        if side_one_active.item == Items::CUSTAPBERRY
            && side_one_active.hp < side_one_active.maxhp / 4
            && !super::items::unnerved(state, &SideReference::SideOne)
        {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: SideReference::SideOne,
                    new_item: Items::NONE,
                    current_item: Items::CUSTAPBERRY,
                }));
            // (L57: used up; the state follows these instructions when applied)
            let last = side_one_active.last_item;
            if last != Items::CUSTAPBERRY {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ChangeLastItem(ChangeItemInstruction {
                        side_ref: SideReference::SideOne,
                        current_item: last,
                        new_item: Items::CUSTAPBERRY,
                    }));
            }
            return SideMovesFirst::SideOne;
        } else if side_two_active.item == Items::CUSTAPBERRY
            && !super::items::unnerved(state, &SideReference::SideTwo)
            && side_two_active.hp < side_two_active.maxhp / 4
        {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: SideReference::SideTwo,
                    new_item: Items::NONE,
                    current_item: Items::CUSTAPBERRY,
                }));
            // (L57: used up; the state follows these instructions when applied)
            let last = side_two_active.last_item;
            if last != Items::CUSTAPBERRY {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::ChangeLastItem(ChangeItemInstruction {
                        side_ref: SideReference::SideTwo,
                        current_item: last,
                        new_item: Items::CUSTAPBERRY,
                    }));
            }
            return SideMovesFirst::SideTwo;
        }

        if side_one_effective_speed == side_two_effective_speed {
            return SideMovesFirst::SpeedTie;
        }

        match state.trick_room.active {
            true => {
                if side_one_effective_speed < side_two_effective_speed {
                    SideMovesFirst::SideOne
                } else {
                    SideMovesFirst::SideTwo
                }
            }
            false => {
                if side_one_effective_speed > side_two_effective_speed {
                    SideMovesFirst::SideOne
                } else {
                    SideMovesFirst::SideTwo
                }
            }
        }
    } else {
        if side_one_choice.priority > side_two_choice.priority {
            SideMovesFirst::SideOne
        } else {
            SideMovesFirst::SideTwo
        }
    }
}

fn get_active_protosynthesis(side: &Side) -> Option<PokemonVolatileStatus> {
    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PROTOSYNTHESISATK)
    {
        Some(PokemonVolatileStatus::PROTOSYNTHESISATK)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PROTOSYNTHESISDEF)
    {
        Some(PokemonVolatileStatus::PROTOSYNTHESISDEF)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PROTOSYNTHESISSPA)
    {
        Some(PokemonVolatileStatus::PROTOSYNTHESISSPA)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PROTOSYNTHESISSPD)
    {
        Some(PokemonVolatileStatus::PROTOSYNTHESISSPD)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::PROTOSYNTHESISSPE)
    {
        Some(PokemonVolatileStatus::PROTOSYNTHESISSPE)
    } else {
        None
    }
}

fn get_active_quarkdrive(side: &Side) -> Option<PokemonVolatileStatus> {
    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::QUARKDRIVEATK)
    {
        Some(PokemonVolatileStatus::QUARKDRIVEATK)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::QUARKDRIVEDEF)
    {
        Some(PokemonVolatileStatus::QUARKDRIVEDEF)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::QUARKDRIVESPA)
    {
        Some(PokemonVolatileStatus::QUARKDRIVESPA)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::QUARKDRIVESPD)
    {
        Some(PokemonVolatileStatus::QUARKDRIVESPD)
    } else if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::QUARKDRIVESPE)
    {
        Some(PokemonVolatileStatus::QUARKDRIVESPE)
    } else {
        None
    }
}

fn on_weather_end(
    state: &mut State,
    sides: [&SideReference; 2],
    incoming_instructions: &mut StateInstructions,
) {
    match state.weather.weather_type {
        Weather::SUN => {
            for side_ref in sides {
                let side = state.get_side(side_ref);
                if side.get_active_immutable().ability == Abilities::PROTOSYNTHESIS {
                    if let Some(volatile_status) = get_active_protosynthesis(side) {
                        let active = side.get_active();
                        if active.item == Items::BOOSTERENERGY {
                            incoming_instructions
                                .instruction_list
                                .push(Instruction::ChangeItem(ChangeItemInstruction {
                                    side_ref: *side_ref,
                                    current_item: Items::BOOSTERENERGY,
                                    new_item: Items::NONE,
                                }));
                            active.item = Items::NONE;
                        } else {
                            incoming_instructions.instruction_list.push(
                                Instruction::RemoveVolatileStatus(
                                    RemoveVolatileStatusInstruction {
                                        side_ref: *side_ref,
                                        volatile_status,
                                    },
                                ),
                            );
                            side.volatile_statuses.remove(&volatile_status);
                        }
                    }
                }
            }
        }
        _ => {}
    }
}

fn on_terrain_end(
    state: &mut State,
    sides: [&SideReference; 2],
    incoming_instructions: &mut StateInstructions,
) {
    match state.terrain.terrain_type {
        Terrain::ELECTRICTERRAIN => {
            for side_ref in sides {
                let side = state.get_side(side_ref);
                if side.get_active_immutable().ability == Abilities::QUARKDRIVE {
                    if let Some(volatile_status) = get_active_quarkdrive(side) {
                        let active = side.get_active();
                        if active.item == Items::BOOSTERENERGY {
                            incoming_instructions
                                .instruction_list
                                .push(Instruction::ChangeItem(ChangeItemInstruction {
                                    side_ref: *side_ref,
                                    current_item: Items::BOOSTERENERGY,
                                    new_item: Items::NONE,
                                }));
                            active.item = Items::NONE;
                        } else {
                            incoming_instructions.instruction_list.push(
                                Instruction::RemoveVolatileStatus(
                                    RemoveVolatileStatusInstruction {
                                        side_ref: *side_ref,
                                        volatile_status,
                                    },
                                ),
                            );
                            side.volatile_statuses.remove(&volatile_status);
                        }
                    }
                }
            }
        }
        _ => {}
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L62): Unburden, on when the active lost its
// item since it came in (Showdown's onAfterUseItem / onTakeItem: at once; here at the end of the
// turn, from the turn's instructions: its Speed matters from the next turn's order)
fn unburden_check(state: &mut State, instructions: &mut StateInstructions) {
    for side_ref in [SideReference::SideOne, SideReference::SideTwo] {
        // (a scan only when the active has Unburden: this runs at every end of turn)
        if state
            .get_side_immutable(&side_ref)
            .get_active_immutable()
            .ability
            != Abilities::UNBURDEN
        {
            continue;
        }
        let mut lost = false;
        for ins in instructions.instruction_list.iter() {
            match ins {
                Instruction::Switch(s) if s.side_ref == side_ref => lost = false,
                Instruction::ChangeItem(c)
                    if c.side_ref == side_ref
                        && c.new_item == Items::NONE
                        && c.current_item != Items::NONE =>
                {
                    lost = true
                }
                _ => {}
            }
        }
        let side = state.get_side(&side_ref);
        let active = side.get_active_immutable();
        if lost
            && active.ability == Abilities::UNBURDEN
            && active.item == Items::NONE
            && active.hp > 0
            && !side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::UNBURDEN)
        {
            side.volatile_statuses
                .insert(PokemonVolatileStatus::UNBURDEN);
            instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref,
                        volatile_status: PokemonVolatileStatus::UNBURDEN,
                    },
                ));
        }
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L57): Harvest at the end of the turn, a
// used-up berry back (always in sun, else half the time: Showdown's onResidual); the berry is
// then eaten in the end of the turn as any (Sitrus at half HP)
fn harvest_chance(state: &State) -> Option<(SideReference, f32)> {
    for side_ref in [SideReference::SideOne, SideReference::SideTwo] {
        let a = state.get_side_immutable(&side_ref).get_active_immutable();
        if a.ability == Abilities::HARVEST
            && a.hp > 0
            && a.item == Items::NONE
            && is_berry(a.last_item)
        {
            let sun = state.weather_is_active(&Weather::SUN)
                || state.weather_is_active(&Weather::HARSHSUN);
            return Some((side_ref, if sun { 1.0 } else { 0.5 }));
        }
    }
    None
}

fn harvest_instructions(state: &mut State, side_ref: SideReference, ins: &mut StateInstructions) {
    let a = state.get_side(&side_ref).get_active();
    let berry = a.last_item;
    ins.instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref,
            current_item: Items::NONE,
            new_item: berry,
        }));
    a.item = berry;
    ins.instruction_list
        .push(Instruction::ChangeLastItem(ChangeItemInstruction {
            side_ref,
            current_item: berry,
            new_item: Items::NONE,
        }));
    a.last_item = Items::NONE;
}

/// the end of the turn with Harvest (the state has `si` applied, and has it again on return):
/// after the rest of the end of the turn (the engine eats a Sitrus there, Showdown at once), the
/// berry back and eaten again if it would be (Showdown's onUpdate); the branch where a chance of
/// it succeeds, if any
fn end_of_turn_with_harvest(
    state: &mut State,
    si: &mut StateInstructions,
    first_move_side: &SideReference,
) -> Option<StateInstructions> {
    add_end_of_turn_instructions(state, si, first_move_side);
    let (h, p) = harvest_chance(state)?;
    if p >= 1.0 {
        harvest_instructions(state, h, si);
        item_end_of_turn(state, &h, si, false);
        return None;
    }
    let base = si.instruction_list.len();
    let mut yes = si.clone();
    si.update_percentage(1.0 - p);
    yes.update_percentage(p);
    harvest_instructions(state, h, &mut yes);
    item_end_of_turn(state, &h, &mut yes, false);
    state.reverse_instructions(&yes.instruction_list[base..].to_vec());
    Some(yes)
}

fn add_end_of_turn_instructions(
    state: &mut State,
    mut incoming_instructions: &mut StateInstructions,
    first_move_side: &SideReference,
) {
    if state.side_one.force_switch || state.side_two.force_switch {
        return;
    }
    unburden_check(state, incoming_instructions);

    let sides = [first_move_side, &first_move_side.get_other_side()];

    // Weather decrement / dissipation
    if state.weather.turns_remaining > 0 && state.weather.weather_type != Weather::NONE {
        let weather_dissipate_instruction = Instruction::DecrementWeatherTurnsRemaining;
        incoming_instructions
            .instruction_list
            .push(weather_dissipate_instruction);
        state.weather.turns_remaining -= 1;
        if state.weather.turns_remaining == 0 {
            on_weather_end(state, sides, &mut incoming_instructions);
            let weather_end_instruction = Instruction::ChangeWeather(ChangeWeather {
                new_weather: Weather::NONE,
                new_weather_turns_remaining: 0,
                previous_weather: state.weather.weather_type,
                previous_weather_turns_remaining: 0,
            });
            incoming_instructions
                .instruction_list
                .push(weather_end_instruction);
            state.weather.weather_type = Weather::NONE;
        }
    }

    // Trick Room decrement / dissipation
    if state.trick_room.turns_remaining > 0 && state.trick_room.active {
        incoming_instructions
            .instruction_list
            .push(Instruction::DecrementTrickRoomTurnsRemaining);
        state.trick_room.turns_remaining -= 1;
        if state.trick_room.turns_remaining == 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ToggleTrickRoom(ToggleTrickRoomInstruction {
                    currently_active: true,
                    new_trickroom_turns_remaining: 0,
                    previous_trickroom_turns_remaining: 0,
                }));
            state.trick_room.active = false;
        }
    }

    // Side Condition decrement
    for side_ref in sides {
        let side = state.get_side(side_ref);
        if side.side_conditions.reflect > 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: *side_ref,
                        side_condition: PokemonSideCondition::Reflect,
                        amount: -1,
                    },
                ));
            side.side_conditions.reflect -= 1;
        }
        if side.side_conditions.light_screen > 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: *side_ref,
                        side_condition: PokemonSideCondition::LightScreen,
                        amount: -1,
                    },
                ));
            side.side_conditions.light_screen -= 1;
        }
        if side.side_conditions.aurora_veil > 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: *side_ref,
                        side_condition: PokemonSideCondition::AuroraVeil,
                        amount: -1,
                    },
                ));
            side.side_conditions.aurora_veil -= 1;
        }
        if side.side_conditions.tailwind > 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: *side_ref,
                        side_condition: PokemonSideCondition::Tailwind,
                        amount: -1,
                    },
                ));
            side.side_conditions.tailwind -= 1;
        }
    }

    // Weather Damage
    for side_ref in sides {
        if state.weather_is_active(&Weather::HAIL) {
            let active_pkmn = state.get_side(side_ref).get_active();
            if active_pkmn.hp == 0
                || active_pkmn.ability == Abilities::MAGICGUARD
                || active_pkmn.ability == Abilities::OVERCOAT
                || active_pkmn.item == Items::SAFETYGOGGLES // alpha-poke patch (2026-10-13)
                || active_pkmn.ability == Abilities::ICEBODY
                || active_pkmn.has_type(&PokemonType::ICE)
            {
                continue;
            }

            let damage_amount =
                cmp::min((active_pkmn.maxhp as f32 * 0.0625) as i16, active_pkmn.hp);
            let hail_damage_instruction = Instruction::Damage(DamageInstruction {
                side_ref: *side_ref,
                damage_amount: damage_amount,
            });

            active_pkmn.hp -= damage_amount;
            incoming_instructions
                .instruction_list
                .push(hail_damage_instruction);
        } else if state.weather_is_active(&Weather::SAND) {
            let active_pkmn = state.get_side(side_ref).get_active();
            if active_pkmn.hp == 0
                || active_pkmn.ability == Abilities::MAGICGUARD
                || active_pkmn.ability == Abilities::OVERCOAT
                || active_pkmn.item == Items::SAFETYGOGGLES // alpha-poke patch (2026-10-13)
                || active_pkmn.has_type(&PokemonType::GROUND)
                || active_pkmn.has_type(&PokemonType::STEEL)
                || active_pkmn.has_type(&PokemonType::ROCK)
            {
                continue;
            }
            let damage_amount =
                cmp::min((active_pkmn.maxhp as f32 * 0.0625) as i16, active_pkmn.hp);
            let sand_damage_instruction = Instruction::Damage(DamageInstruction {
                side_ref: *side_ref,
                damage_amount: damage_amount,
            });
            active_pkmn.hp -= damage_amount;
            incoming_instructions
                .instruction_list
                .push(sand_damage_instruction);
        }
    }

    // future sight
    for side_ref in sides {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L35): the hit is its user's move
        // while the user is active (its abilities' and items' modifiers: Life Orb, Choice Specs,
        // ...; Life Orb's recoil below), the target's always (Assault Vest, Multiscale, ...)
        let user_active = {
            let side = state.get_side_immutable(side_ref);
            side.future_sight.0 == 1 && side.active_index == side.future_sight.1
        };
        if state.get_side_immutable(side_ref).future_sight.0 == 0 {
            continue;
        }
        let mut fs_choice = Choice::default();
        if state.get_side_immutable(side_ref).future_sight.0 == 1 {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L56): Doom Desire's hit (Steel,
            // 140) when its user knows Doom Desire and not Future Sight (the engine keeps only
            // the user's index); before, always Future Sight's
            let side = state.get_side_immutable(side_ref);
            let user = &side.pokemon[side.future_sight.1];
            let knows = |c: Choices| user.moves.into_iter().any(|m| m.id == c);
            let id = if knows(Choices::DOOMDESIRE) && !knows(Choices::FUTURESIGHT) {
                Choices::DOOMDESIRE
            } else {
                Choices::FUTURESIGHT
            };
            fs_choice = MOVES.get(&id).unwrap().clone();
            let none = Choice::default();
            if user_active {
                ability_modify_attack_being_used(state, &mut fs_choice, &none, side_ref);
                item_modify_attack_being_used(state, &mut fs_choice, side_ref);
            }
            ability_modify_attack_against(state, &mut fs_choice, &none, side_ref);
            item_modify_attack_against(state, &mut fs_choice, side_ref);
        }
        let (attacking_side, defending_side) = state.get_both_sides(side_ref);
        if attacking_side.future_sight.0 > 0 {
            let decrement_future_sight_instruction =
                Instruction::DecrementFutureSight(DecrementFutureSightInstruction {
                    side_ref: *side_ref,
                });
            if attacking_side.future_sight.0 == 1 {
                let mut damage = calculate_futuresight_damage(
                    &attacking_side,
                    &defending_side,
                    &attacking_side.future_sight.1,
                    &fs_choice,
                );
                let defender = defending_side.get_active();
                damage = cmp::min(damage, defender.hp);
                let future_sight_damage_instruction = Instruction::Damage(DamageInstruction {
                    side_ref: side_ref.get_other_side(),
                    damage_amount: damage,
                });
                incoming_instructions
                    .instruction_list
                    .push(future_sight_damage_instruction);
                defender.hp -= damage;
                let user = attacking_side.get_active();
                if user_active
                    && damage > 0
                    && user.item == Items::LIFEORB
                    && user.ability != Abilities::MAGICGUARD
                    && user.hp > 0
                {
                    let recoil = cmp::min(user.maxhp / 10, user.hp);
                    incoming_instructions
                        .instruction_list
                        .push(Instruction::Damage(DamageInstruction {
                            side_ref: *side_ref,
                            damage_amount: recoil,
                        }));
                    user.hp -= recoil;
                }
            }
            attacking_side.future_sight.0 -= 1;
            incoming_instructions
                .instruction_list
                .push(decrement_future_sight_instruction);
        }
    }

    // wish
    for side_ref in sides {
        let side = state.get_side(side_ref);
        let side_wish = side.wish;
        // alpha-poke patch (2026-10-16, L19): no healing under Heal Block
        let heal_blocked = side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::HEALBLOCK);
        let active_pkmn = side.get_active();

        if side_wish.0 > 0 {
            let decrement_wish_instruction = Instruction::DecrementWish(DecrementWishInstruction {
                side_ref: *side_ref,
            });
            if side_wish.0 == 1
                && 0 < active_pkmn.hp
                && active_pkmn.hp < active_pkmn.maxhp
                && !heal_blocked
            {
                #[cfg(not(feature = "gen4"))]
                let heal_amount = cmp::min(active_pkmn.maxhp - active_pkmn.hp, side_wish.1);

                #[cfg(feature = "gen4")]
                let heal_amount =
                    cmp::min(active_pkmn.maxhp - active_pkmn.hp, active_pkmn.maxhp / 2);

                let wish_heal_instruction = Instruction::Heal(HealInstruction {
                    side_ref: *side_ref,
                    heal_amount,
                });
                incoming_instructions
                    .instruction_list
                    .push(wish_heal_instruction);
                active_pkmn.hp += heal_amount;
            }
            side.wish.0 -= 1;
            incoming_instructions
                .instruction_list
                .push(decrement_wish_instruction);
        }
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L84): the terrain after the weather's
    // damage, Future Sight and Wish (Showdown: Grassy Terrain's heal 5.2, the terrain's end
    // 27); it was before the weather's damage
    // Terrain decrement / dissipation
    if state.terrain.turns_remaining > 0 && state.terrain.terrain_type != Terrain::NONE {
        if state.terrain.terrain_type == Terrain::GRASSYTERRAIN {
            for side_ref in sides {
                let side = state.get_side(side_ref);
                // alpha-poke patch (2026-10-16, doc/engine-diff.md L19): no healing under Heal Block
                let heal_blocked = side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::HEALBLOCK);
                let active_pkmn = side.get_active();
                if active_pkmn.hp == 0 || !active_pkmn.is_grounded() || heal_blocked {
                    continue;
                }
                let heal_amount = cmp::min(
                    (active_pkmn.maxhp as f32 * 0.0625) as i16,
                    active_pkmn.maxhp - active_pkmn.hp,
                );
                if heal_amount > 0 {
                    let heal_instruction = Instruction::Heal(HealInstruction {
                        side_ref: *side_ref,
                        heal_amount,
                    });
                    active_pkmn.hp += heal_amount;
                    incoming_instructions
                        .instruction_list
                        .push(heal_instruction);
                }
            }
        }
        let terrain_dissipate_instruction = Instruction::DecrementTerrainTurnsRemaining;
        incoming_instructions
            .instruction_list
            .push(terrain_dissipate_instruction);
        state.terrain.turns_remaining -= 1;
        if state.terrain.turns_remaining == 0 {
            on_terrain_end(state, sides, &mut incoming_instructions);
            let terrain_end_instruction = Instruction::ChangeTerrain(ChangeTerrain {
                new_terrain: Terrain::NONE,
                new_terrain_turns_remaining: 0,
                previous_terrain: state.terrain.terrain_type,
                previous_terrain_turns_remaining: 0,
            });
            incoming_instructions
                .instruction_list
                .push(terrain_end_instruction);
            state.terrain.terrain_type = Terrain::NONE;
        }
    }

    // alpha-poke patch (2026-10-16): Showdown's residual order: the weather abilities (1),
    // Hydration / Shed Skin (5.3), Leftovers / Black Sludge (5.4) and Leech Seed (8) come before
    // the status damage (poison 9, burn 10); before, they all came after it
    for side_ref in sides {
        let side = state.get_side(side_ref);
        let active_pkmn = side.get_active();
        if active_pkmn.hp == 0 {
            continue;
        }

        ability_end_of_turn(state, side_ref, &mut incoming_instructions, true);
        item_end_of_turn(state, side_ref, &mut incoming_instructions, true);
    }

    // leechseed sap
    for side_ref in sides {
        let (leechseed_side, other_side) = state.get_both_sides(side_ref);
        // alpha-poke patch (2026-10-16, L19): the seeder heals nothing under Heal Block
        let seeder_heal_blocked = other_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::HEALBLOCK);
        if leechseed_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::LEECHSEED)
        {
            let active_pkmn = leechseed_side.get_active();
            let other_active_pkmn = other_side.get_active();
            if active_pkmn.hp == 0
                || other_active_pkmn.hp == 0
                || active_pkmn.ability == Abilities::MAGICGUARD
            {
                continue;
            }

            let health_sapped = cmp::min((active_pkmn.maxhp as f32 * 0.125) as i16, active_pkmn.hp);
            let damage_ins = Instruction::Damage(DamageInstruction {
                side_ref: *side_ref,
                damage_amount: health_sapped,
            });
            active_pkmn.hp -= health_sapped;
            incoming_instructions.instruction_list.push(damage_ins);

            // alpha-poke patch (2026-10-16, L24): the seeder's Big Root
            let sapped_heal = if other_active_pkmn.item == Items::BIGROOT {
                big_root(health_sapped)
            } else {
                health_sapped
            };
            let health_recovered =
                cmp::min(sapped_heal, other_active_pkmn.maxhp - other_active_pkmn.hp);
            if health_recovered > 0 && !seeder_heal_blocked {
                let heal_ins = Instruction::Heal(HealInstruction {
                    side_ref: side_ref.get_other_side(),
                    heal_amount: health_recovered,
                });
                other_active_pkmn.hp += health_recovered;
                incoming_instructions.instruction_list.push(heal_ins);
            }
        }
    }

    // status damage
    for side_ref in sides {
        let (side, other_side) = state.get_both_sides(side_ref);
        let toxic_count = side.side_conditions.toxic_count as f32;
        let heal_blocked = side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::HEALBLOCK);
        let active_pkmn = side.get_active();
        let other_side_active = other_side.get_active();
        if active_pkmn.hp == 0 || active_pkmn.ability == Abilities::MAGICGUARD {
            continue;
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L12b): Poison Heal heals 1/8 in place
        // of the poison damage (Showdown's onDamage, at the poison's residual order 9), so not in
        // the turn a Toxic Orb poisons (28); before, ability_end_of_turn healed after the orb
        if active_pkmn.ability == Abilities::POISONHEAL
            && other_side_active.ability != Abilities::NEUTRALIZINGGAS
            && matches!(
                active_pkmn.status,
                PokemonStatus::POISON | PokemonStatus::TOXIC
            )
            && active_pkmn.hp < active_pkmn.maxhp
            && !heal_blocked
        {
            let heal_amount = cmp::min(active_pkmn.maxhp / 8, active_pkmn.maxhp - active_pkmn.hp);
            incoming_instructions
                .instruction_list
                .push(Instruction::Heal(HealInstruction {
                    side_ref: *side_ref,
                    heal_amount,
                }));
            active_pkmn.hp += heal_amount;
        }

        match active_pkmn.status {
            PokemonStatus::BURN => {
                let mut damage_factor = BURN_RESIDUAL_DAMAGE_PCT;

                if active_pkmn.ability == Abilities::HEATPROOF {
                    damage_factor /= 2.0;
                }
                let damage_amount = cmp::max(
                    cmp::min(
                        (active_pkmn.maxhp as f32 * damage_factor) as i16,
                        active_pkmn.hp,
                    ),
                    1,
                );
                let burn_damage_instruction = Instruction::Damage(DamageInstruction {
                    side_ref: *side_ref,
                    damage_amount,
                });
                active_pkmn.hp -= damage_amount;
                incoming_instructions
                    .instruction_list
                    .push(burn_damage_instruction);
            }
            PokemonStatus::POISON if active_pkmn.ability != Abilities::POISONHEAL => {
                let damage_amount = cmp::max(
                    1,
                    cmp::min((active_pkmn.maxhp as f32 * 0.125) as i16, active_pkmn.hp),
                );

                let poison_damage_instruction = Instruction::Damage(DamageInstruction {
                    side_ref: *side_ref,
                    damage_amount,
                });
                active_pkmn.hp -= damage_amount;
                incoming_instructions
                    .instruction_list
                    .push(poison_damage_instruction);
            }
            PokemonStatus::TOXIC => {
                if active_pkmn.ability != Abilities::POISONHEAL
                    || other_side_active.ability == Abilities::NEUTRALIZINGGAS
                {
                    let toxic_multiplier = (1.0 / 16.0) * toxic_count + (1.0 / 16.0);
                    let damage_amount = cmp::max(
                        cmp::min(
                            (active_pkmn.maxhp as f32 * toxic_multiplier) as i16,
                            active_pkmn.hp,
                        ),
                        1,
                    );
                    let toxic_damage_instruction = Instruction::Damage(DamageInstruction {
                        side_ref: *side_ref,
                        damage_amount,
                    });

                    active_pkmn.hp -= damage_amount;
                    incoming_instructions
                        .instruction_list
                        .push(toxic_damage_instruction);
                }

                // toxic counter is always incremented, even if the pokemon has poison heal
                let toxic_counter_increment_instruction =
                    Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                        side_ref: *side_ref,
                        side_condition: PokemonSideCondition::ToxicCount,
                        amount: 1,
                    });
                side.side_conditions.toxic_count += 1;
                incoming_instructions
                    .instruction_list
                    .push(toxic_counter_increment_instruction);
            }
            _ => {}
        }
    }

    // ability/item end-of-turn effects
    for side_ref in sides {
        let side = state.get_side(side_ref);
        let active_pkmn = side.get_active();
        if active_pkmn.hp == 0 {
            continue;
        }

        item_end_of_turn(state, side_ref, &mut incoming_instructions, false);
        ability_end_of_turn(state, side_ref, &mut incoming_instructions, false);
    }

    // volatile statuses
    for side_ref in sides {
        let side = state.get_side(side_ref);
        if side.get_active().hp == 0 {
            continue;
        }

        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SLOWSTART)
        {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::SLOWSTART,
                        amount: -1,
                    },
                ));
            side.volatile_status_durations.slowstart -= 1;
            if side.volatile_status_durations.slowstart == 0 {
                incoming_instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::SLOWSTART,
                        },
                    ));
                side.volatile_statuses
                    .remove(&PokemonVolatileStatus::SLOWSTART);
            }
        }

        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::LOCKEDMOVE)
        {
            // the number says 2 but this is 3 turns of using a locking move
            // because turn 0 is the first turn the move is used
            // branching is not implemented here so the engine assumes it always lasts 3 turns
            if side.volatile_status_durations.lockedmove == 2 {
                side.volatile_status_durations.lockedmove = 0;
                side.volatile_statuses
                    .remove(&PokemonVolatileStatus::LOCKEDMOVE);
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::LOCKEDMOVE,
                            amount: -2,
                        },
                    ),
                );
                incoming_instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::LOCKEDMOVE,
                        },
                    ));
                if !side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::CONFUSION)
                {
                    incoming_instructions
                        .instruction_list
                        .push(Instruction::ApplyVolatileStatus(
                            ApplyVolatileStatusInstruction {
                                side_ref: *side_ref,
                                volatile_status: PokemonVolatileStatus::CONFUSION,
                            },
                        ));
                    side.volatile_statuses
                        .insert(PokemonVolatileStatus::CONFUSION);
                }
                // alpha-poke patch (2026-10-16, L23): the other moves can be used again (a choice
                // item keeps them locked)
                let active = side.get_active();
                if !matches!(
                    active.item,
                    Items::CHOICEBAND | Items::CHOICESPECS | Items::CHOICESCARF
                ) {
                    for move_index in [
                        PokemonMoveIndex::M0,
                        PokemonMoveIndex::M1,
                        PokemonMoveIndex::M2,
                        PokemonMoveIndex::M3,
                    ] {
                        if active.moves[&move_index].disabled {
                            active.moves[&move_index].disabled = false;
                            incoming_instructions
                                .instruction_list
                                .push(Instruction::EnableMove(EnableMoveInstruction {
                                    side_ref: *side_ref,
                                    move_index,
                                }));
                        }
                    }
                }
            } else {
                side.volatile_status_durations.lockedmove += 1;
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::LOCKEDMOVE,
                            amount: 1,
                        },
                    ),
                );
            }
        }

        // alpha-poke patch (2026-10-16, doc/engine-diff.md L89 / L90): Encore's and Taunt's ends of
        // turn; at 3 they end
        #[cfg(not(feature = "gen4"))]
        for v in [PokemonVolatileStatus::ENCORE, PokemonVolatileStatus::TAUNT] {
            if !side.volatile_statuses.contains(&v) {
                continue;
            }
            let count = if v == PokemonVolatileStatus::ENCORE {
                &mut side.volatile_status_durations.encore
            } else {
                &mut side.volatile_status_durations.taunt
            };
            let (amount, ends) = if *count + 1 >= 3 {
                (-*count, true)
            } else {
                (1, false)
            };
            *count += amount;
            if ends {
                side.volatile_statuses.remove(&v);
                incoming_instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: *side_ref,
                            volatile_status: v,
                        },
                    ));
            }
            if amount != 0 {
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: v,
                            amount,
                        },
                    ),
                );
            }
        }

        // alpha-poke patch (2026-10-16, doc/engine-diff.md L70): Disable's ends of turn; at 4 it
        // ends and its move can be used again
        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::DISABLE)
        {
            let value = side.volatile_status_durations.disable;
            if value % 8 + 1 >= 5 {
                side.volatile_statuses
                    .remove(&PokemonVolatileStatus::DISABLE);
                incoming_instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::DISABLE,
                        },
                    ));
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::DISABLE,
                            amount: -value,
                        },
                    ),
                );
                side.volatile_status_durations.disable = 0;
                let slot = match value / 8 {
                    0 => PokemonMoveIndex::M0,
                    1 => PokemonMoveIndex::M1,
                    2 => PokemonMoveIndex::M2,
                    _ => PokemonMoveIndex::M3,
                };
                let active = side.get_active();
                if active.moves[&slot].disabled {
                    active.moves[&slot].disabled = false;
                    incoming_instructions
                        .instruction_list
                        .push(Instruction::EnableMove(EnableMoveInstruction {
                            side_ref: *side_ref,
                            move_index: slot,
                        }));
                }
            } else {
                side.volatile_status_durations.disable += 1;
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::DISABLE,
                            amount: 1,
                        },
                    ),
                );
            }
        }

        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::YAWN)
        {
            match side.volatile_status_durations.yawn {
                0 => {
                    incoming_instructions.instruction_list.push(
                        Instruction::ChangeVolatileStatusDuration(
                            ChangeVolatileStatusDurationInstruction {
                                side_ref: *side_ref,
                                volatile_status: PokemonVolatileStatus::YAWN,
                                amount: 1,
                            },
                        ),
                    );
                    side.volatile_status_durations.yawn += 1;
                }
                1 => {
                    side.volatile_statuses.remove(&PokemonVolatileStatus::YAWN);
                    incoming_instructions
                        .instruction_list
                        .push(Instruction::RemoveVolatileStatus(
                            RemoveVolatileStatusInstruction {
                                side_ref: *side_ref,
                                volatile_status: PokemonVolatileStatus::YAWN,
                            },
                        ));
                    incoming_instructions.instruction_list.push(
                        Instruction::ChangeVolatileStatusDuration(
                            ChangeVolatileStatusDurationInstruction {
                                side_ref: *side_ref,
                                volatile_status: PokemonVolatileStatus::YAWN,
                                amount: -1,
                            },
                        ),
                    );
                    side.volatile_status_durations.yawn -= 1;

                    let active = side.get_active();
                    if active.status == PokemonStatus::NONE {
                        active.status = PokemonStatus::SLEEP;
                        incoming_instructions
                            .instruction_list
                            .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                                side_ref: *side_ref,
                                pokemon_index: side.active_index,
                                old_status: PokemonStatus::NONE,
                                new_status: PokemonStatus::SLEEP,
                            }));
                    }
                }
                _ => panic!(
                    "Yawn duration cannot be {} when yawn volatile is active",
                    side.volatile_status_durations.yawn
                ),
            }
        }

        // alpha-poke patch (2026-10-13): Heal Block (Psychic Noise: 2 turns), Magnet Rise (5) and
        // Throat Chop (2) end; before, they lasted until a switch. 2026-10-16: a partial trap
        // ends at its fifth end of turn, before its damage (Showdown: the fifth or the sixth,
        // doc/engine-diff.md L13); before, it lasted until a switch
        for (volatile, limit) in [
            (PokemonVolatileStatus::HEALBLOCK, 2),
            (PokemonVolatileStatus::MAGNETRISE, 5),
            (PokemonVolatileStatus::THROATCHOP, 2),
            (PokemonVolatileStatus::PARTIALLYTRAPPED, 5),
            (PokemonVolatileStatus::MICLEBERRY, 2),
        ] {
            if !side.volatile_statuses.contains(&volatile) {
                continue;
            }
            let duration = match volatile {
                PokemonVolatileStatus::HEALBLOCK => &mut side.volatile_status_durations.healblock,
                PokemonVolatileStatus::THROATCHOP => &mut side.volatile_status_durations.throatchop,
                PokemonVolatileStatus::PARTIALLYTRAPPED => {
                    &mut side.volatile_status_durations.partiallytrapped
                }
                PokemonVolatileStatus::MICLEBERRY => &mut side.volatile_status_durations.micleberry,
                _ => &mut side.volatile_status_durations.magnetrise,
            };
            if *duration + 1 >= limit {
                let amount = -*duration;
                *duration = 0;
                side.volatile_statuses.remove(&volatile);
                incoming_instructions
                    .instruction_list
                    .push(Instruction::RemoveVolatileStatus(
                        RemoveVolatileStatusInstruction {
                            side_ref: *side_ref,
                            volatile_status: volatile,
                        },
                    ));
                if amount != 0 {
                    incoming_instructions.instruction_list.push(
                        Instruction::ChangeVolatileStatusDuration(
                            ChangeVolatileStatusDurationInstruction {
                                side_ref: *side_ref,
                                volatile_status: volatile,
                                amount,
                            },
                        ),
                    );
                }
            } else {
                *duration += 1;
                incoming_instructions.instruction_list.push(
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: volatile,
                            amount: 1,
                        },
                    ),
                );
            }
        }

        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::PERISH1)
        {
            let active_pkmn = side.get_active();
            incoming_instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *side_ref,
                    damage_amount: active_pkmn.hp,
                }));
            active_pkmn.hp = 0;
        }

        if side
            .volatile_statuses
            .remove_with_check(&PokemonVolatileStatus::PERISH2)
        {
            side.volatile_statuses
                .insert(PokemonVolatileStatus::PERISH1);
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::PERISH2,
                    },
                ));
            incoming_instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::PERISH1,
                    },
                ));
        }
        if side
            .volatile_statuses
            .remove_with_check(&PokemonVolatileStatus::PERISH3)
        {
            side.volatile_statuses
                .insert(PokemonVolatileStatus::PERISH2);
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::PERISH3,
                    },
                ));
            incoming_instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::PERISH2,
                    },
                ));
        }
        if side
            .volatile_statuses
            .remove_with_check(&PokemonVolatileStatus::PERISH4)
        {
            side.volatile_statuses
                .insert(PokemonVolatileStatus::PERISH3);
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::PERISH4,
                    },
                ));
            incoming_instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::PERISH3,
                    },
                ));
        }

        if side
            .volatile_statuses
            .remove_with_check(&PokemonVolatileStatus::FLINCH)
        {
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::FLINCH,
                    },
                ));
        }
        if side
            .volatile_statuses
            .remove_with_check(&PokemonVolatileStatus::ROOST)
        {
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::ROOST,
                    },
                ));
        }

        // alpha-poke patch (2026-10-16, doc/engine-diff.md L82): Magic Guard stops the partial
        // trap's, Salt Cure's and Curse's damage
        let guarded = side.get_active_immutable().ability == Abilities::MAGICGUARD;
        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::PARTIALLYTRAPPED)
            && !guarded
        {
            let active_pkmn = side.get_active();
            let damage_amount = cmp::min(
                (active_pkmn.maxhp as f32 * PARTIALLY_TRAPPED_DAMAGE_PCT) as i16,
                active_pkmn.hp,
            );
            incoming_instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *side_ref,
                    damage_amount,
                }));
            active_pkmn.hp -= damage_amount;
        }
        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SALTCURE)
            && !guarded
        {
            let active_pkmn = side.get_active();
            let mut divisor = SALT_CURE_DAMAGE_DIVISOR;
            if active_pkmn.has_type(&PokemonType::WATER)
                || active_pkmn.has_type(&PokemonType::STEEL)
            {
                divisor /= 2.0;
            }
            let damage_amount =
                cmp::min((active_pkmn.maxhp as f32 / divisor) as i16, active_pkmn.hp);
            incoming_instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *side_ref,
                    damage_amount: damage_amount,
                }));
            active_pkmn.hp -= damage_amount;
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L2a): a cursed mon loses 1/4 of its
        // max HP at the end of every turn (Showdown's curse onResidual: baseMaxhp / 4, at least 1)
        if side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::CURSE)
            && !guarded
        {
            let active_pkmn = side.get_active();
            if active_pkmn.hp > 0 {
                let damage_amount = cmp::min(cmp::max(active_pkmn.maxhp / 4, 1), active_pkmn.hp);
                incoming_instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: *side_ref,
                        damage_amount,
                    }));
                active_pkmn.hp -= damage_amount;
            }
        }

        let possible_statuses = [
            PokemonVolatileStatus::PROTECT,
            PokemonVolatileStatus::BANEFULBUNKER,
            PokemonVolatileStatus::BURNINGBULWARK,
            PokemonVolatileStatus::SPIKYSHIELD,
            PokemonVolatileStatus::SILKTRAP,
            PokemonVolatileStatus::ENDURE,
        ];

        let mut protect_vs = None;
        for status in &possible_statuses {
            if side.volatile_statuses.contains(status) {
                protect_vs = Some(*status);
                break;
            }
        }

        if let Some(protect_vs) = protect_vs {
            incoming_instructions
                .instruction_list
                .push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: protect_vs,
                    },
                ));
            side.volatile_statuses.remove(&protect_vs);
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: *side_ref,
                        side_condition: PokemonSideCondition::Protect,
                        amount: 1,
                    },
                ));
            side.side_conditions.protect += 1;
        } else if side.side_conditions.protect > 0 {
            incoming_instructions
                .instruction_list
                .push(Instruction::ChangeSideCondition(
                    ChangeSideConditionInstruction {
                        side_ref: *side_ref,
                        side_condition: PokemonSideCondition::Protect,
                        amount: -1 * side.side_conditions.protect,
                    },
                ));
            side.side_conditions.protect -= side.side_conditions.protect;
        }
    } // end volatile statuses
      // (L62: an item used up at the end of the turn too)
    unburden_check(state, incoming_instructions);
}

// alpha-poke patch (2026-10-13): a side's stat stages (Eject Pack: lowered by a move)
fn boosts_of(side: &Side) -> [i8; 7] {
    [
        side.attack_boost,
        side.defense_boost,
        side.special_attack_boost,
        side.special_defense_boost,
        side.speed_boost,
        side.accuracy_boost,
        side.evasion_boost,
    ]
}

fn lowered(before: &[i8; 7], after: &[i8; 7]) -> bool {
    before.iter().zip(after.iter()).any(|(b, a)| a < b)
}

fn run_move(
    state: &mut State,
    attacking_side: SideReference,
    mut instructions: StateInstructions,
    hit_count: i8,
    does_damage: bool,
    damage_amount: i16,
    choice: &mut Choice,
    defender_choice: &Choice,
    final_instructions: &mut Vec<StateInstructions>,
) {
    let mut hit_sub = false;
    // alpha-poke patch (2026-10-13): before the move (Emergency Exit / Wimp Out, Eject Pack)
    let defender_hp_before = state
        .get_side_immutable(&attacking_side.get_other_side())
        .get_active_immutable()
        .hp;
    let attacker_boosts_before = boosts_of(state.get_side_immutable(&attacking_side));
    let defender_boosts_before =
        boosts_of(state.get_side_immutable(&attacking_side.get_other_side()));
    for _ in 0..hit_count {
        if does_damage {
            hit_sub = generate_instructions_from_damage(
                state,
                choice,
                damage_amount,
                &attacking_side,
                &mut instructions,
            );
        }
        if let Some(side_condition) = &choice.side_condition {
            generate_instructions_from_side_conditions(
                state,
                side_condition,
                &attacking_side,
                &mut instructions,
            );
        }
        choice_hazard_clear(state, &choice, &attacking_side, &mut instructions);
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L2d): a damaging move that hit the
        // target's substitute puts no volatile on the target (Showdown: the hit's effects on a
        // target behind a substitute are skipped; Salt Cure used to go through)
        let blocked_by_sub = |v: &VolatileStatus| {
            hit_sub && v.target == MoveTarget::Opponent && choice.category != MoveCategory::Status
        };
        if let Some(volatile_status) = choice
            .volatile_status
            .as_ref()
            .filter(|v| !blocked_by_sub(v))
        {
            get_instructions_from_volatile_statuses(
                state,
                &choice,
                volatile_status,
                &attacking_side,
                &mut instructions,
            );
        }
        if let Some(status) = &choice.status {
            get_instructions_from_status_effects(
                state,
                status,
                &attacking_side,
                &mut instructions,
                hit_sub,
            );
        }
        if let Some(heal) = &choice.heal {
            get_instructions_from_heal(state, heal, &attacking_side, &mut instructions);
        }
    } // end multi-hit

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L50): Rocky Helmet / Rough Skin / Iron
    // Barbs hurt the attacker once per contact hit (Showdown's onDamagingHit); the engine applies
    // them once per move (a secondary, ability_after_damage): the hits after the first here
    if does_damage && !hit_sub && hit_count > 1 && choice.flags.contact && damage_amount > 0 {
        let (attacker_side, defender_side) = state.get_both_sides(&attacking_side);
        let defender = defender_side.get_active_immutable();
        let attacker = attacker_side.get_active();
        let mut per_hit = 0;
        if defender.item == Items::ROCKYHELMET {
            per_hit += attacker.maxhp / 6;
        }
        if matches!(
            defender.ability,
            Abilities::ROUGHSKIN | Abilities::IRONBARBS
        ) {
            per_hit += attacker.maxhp / 8;
        }
        if attacker.ability == Abilities::MAGICGUARD || attacker.item == Items::PROTECTIVEPADS {
            per_hit = 0;
        }
        let extra = cmp::min(per_hit * (hit_count as i16 - 1), attacker.hp);
        if extra > 0 {
            attacker.hp -= extra;
            instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: attacking_side,
                    damage_amount: extra,
                }));
        }
    }
    // this is wrong, but I am deciding it is good enough for this engine (for now)
    // each multi-hit move should trigger a chance for a secondary effect,
    // but the way this engine was structured makes it difficult to implement
    // without some performance hits.

    if let Some(boost) = &choice.boost {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L63): a sound move or an Infiltrator's
        // goes through the target's Substitute (Showdown's bypasssub): it is off for the boosts
        // (state only, no instruction)
        let bypass = boost.target == MoveTarget::Opponent
            && (choice.flags.sound
                || state
                    .get_side_immutable(&attacking_side)
                    .get_active_immutable()
                    .ability
                    == Abilities::INFILTRATOR);
        let target = attacking_side.get_other_side();
        let lifted = bypass
            && state
                .get_side_immutable(&target)
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE);
        if lifted {
            state
                .get_side(&target)
                .volatile_statuses
                .remove(&PokemonVolatileStatus::SUBSTITUTE);
        }
        get_instructions_from_boosts(state, boost, &attacking_side, &mut instructions);
        if lifted {
            state
                .get_side(&target)
                .volatile_statuses
                .insert(PokemonVolatileStatus::SUBSTITUTE);
        }
    }

    // alpha-poke patch (2026-10-11): the defender's Eject Button / Red Card, after a damaging
    // move hits it (not its substitute) and it survives. Eject Button: the holder switches out
    // (its choice, as a pivot; the attacker's own pivot does not happen; a holder that had not
    // moved does not move: generate_instructions_from_move). Red Card: the attacker is dragged
    // out (a random benched mon).
    // alpha-poke patch (2026-10-13): Emergency Exit / Wimp Out (the defender dropped to half HP
    // or below by this damaging move, alive) and Eject Pack (the defender's stats lowered by this
    // move; secondary effects and Intimidate are not modeled) switch the defender out like an
    // Eject Button, without an item for the abilities
    let defender_ref = attacking_side.get_other_side();
    let mut ejected = false;
    let damaging = does_damage && !hit_sub && choice.category != MoveCategory::Status;
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Sticky Barb moves to an attacker
    // without an item that makes contact (Showdown's onHit)
    if damaging && choice.flags.contact {
        let attacker = state
            .get_side_immutable(&attacking_side)
            .get_active_immutable();
        let defender = state
            .get_side_immutable(&defender_ref)
            .get_active_immutable();
        if defender.item == Items::STICKYBARB && attacker.item == Items::NONE && attacker.hp > 0 {
            for ins in [
                Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: defender_ref,
                    current_item: Items::STICKYBARB,
                    new_item: Items::NONE,
                }),
                Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: attacking_side,
                    current_item: Items::NONE,
                    new_item: Items::STICKYBARB,
                }),
            ] {
                state.apply_one_instruction(&ins);
                instructions.instruction_list.push(ins);
            }
        }
    }
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L78): Pickpocket, its holder without an
    // item takes the item of an attacker that made contact (Showdown's onAfterMoveSecondary:
    // after Knock Off took the holder's own; not from a pivoting attacker)
    if damaging && choice.flags.contact && !choice.flags.pivot {
        let attacker = state
            .get_side_immutable(&attacking_side)
            .get_active_immutable();
        let defender = state
            .get_side_immutable(&defender_ref)
            .get_active_immutable();
        let item = attacker.item;
        if defender.ability == Abilities::PICKPOCKET
            && attacker.ability != Abilities::NEUTRALIZINGGAS
            && defender.item == Items::NONE
            && defender.hp > 0
            && item != Items::NONE
            && attacker.item_can_be_removed()
        {
            for ins in [
                Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: attacking_side,
                    current_item: item,
                    new_item: Items::NONE,
                }),
                Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: defender_ref,
                    current_item: Items::NONE,
                    new_item: item,
                }),
            ] {
                state.apply_one_instruction(&ins);
                instructions.instruction_list.push(ins);
            }
        }
    }
    let (emergency_exit, eject_pack) = {
        let defender_side = state.get_side_immutable(&defender_ref);
        let holder = defender_side.get_active_immutable();
        let can_switch = defender_side.visible_alive_pkmn() > 1 && !defender_side.force_switch;
        (
            damaging
                && can_switch
                && (holder.ability == Abilities::EMERGENCYEXIT
                    || holder.ability == Abilities::WIMPOUT)
                && defender_hp_before > holder.maxhp / 2
                && holder.hp > 0
                && holder.hp <= holder.maxhp / 2,
            can_switch
                && holder.item == Items::EJECTPACK
                && holder.hp > 0
                && lowered(&defender_boosts_before, &boosts_of(defender_side)),
        )
    };
    if damaging || emergency_exit || eject_pack {
        let defender_side = state.get_side_immutable(&defender_ref);
        let holder = defender_side.get_active_immutable();
        let (item, holder_hp) = (holder.item, holder.hp);
        let can_switch = defender_side.visible_alive_pkmn() > 1 && !defender_side.force_switch;
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L44): Red Card only when the
        // attacker's side has someone to switch in (Showdown's canSwitch)
        let attacker_alive = state
            .get_side_immutable(&attacking_side)
            .get_active_immutable()
            .hp
            > 0
            && state
                .get_side_immutable(&attacking_side)
                .visible_alive_pkmn()
                > 1;
        if emergency_exit
            || eject_pack
            || damaging
                && holder_hp > 0
                && (item == Items::EJECTBUTTON && can_switch
                    || item == Items::REDCARD && attacker_alive)
        {
            if !emergency_exit {
                instructions.instruction_list.push(Instruction::ChangeItem(
                    ChangeItemInstruction {
                        side_ref: defender_ref,
                        current_item: item,
                        new_item: Items::NONE,
                    },
                ));
                state.get_side(&defender_ref).get_active().item = Items::NONE;
            }
            if !emergency_exit && !eject_pack && item == Items::REDCARD {
                // alpha-poke patch (2026-10-16, doc/engine-diff.md L64): the hit's secondaries
                // first, then the drag on each of their outcomes (as L7's drag moves; Showdown:
                // onAfterMoveSecondary), but not Life Orb's recoil (its onAfterMoveSecondarySelf
                // checks the dragged attacker's forceSwitchFlag)
                let secondaries: Option<Vec<Secondary>> = choice.secondaries.as_ref().map(|v| {
                    v.iter()
                        .filter(|x| {
                            !(x.target == MoveTarget::User
                                && matches!(x.effect, Effect::Heal(h) if h == -0.1))
                        })
                        .cloned()
                        .collect()
                });
                if let Some(secondaries_vec) = secondaries.as_ref().filter(|v| !v.is_empty()) {
                    state.reverse_instructions(&instructions.instruction_list);
                    let branches = get_instructions_from_secondaries(
                        state,
                        &choice,
                        secondaries_vec,
                        &attacking_side,
                        instructions,
                        hit_sub,
                    );
                    for branch in branches {
                        state.apply_instructions(&branch.instruction_list);
                        get_instructions_from_drag(
                            state,
                            &defender_ref,
                            branch,
                            final_instructions,
                        );
                    }
                    return;
                }
                get_instructions_from_drag(state, &defender_ref, instructions, final_instructions);
                return;
            }
            ejected = true;
            let defender_side = state.get_side(&defender_ref);
            defender_side.force_switch = true;
            instructions.instruction_list.push(match defender_ref {
                SideReference::SideOne => Instruction::ToggleSideOneForceSwitch,
                SideReference::SideTwo => Instruction::ToggleSideTwoForceSwitch,
            });
            // the attacker has nothing left to do in this turn
            let attacker_side = state.get_side(&attacking_side);
            let previous_choice = attacker_side.switch_out_move_second_saved_move;
            attacker_side.switch_out_move_second_saved_move = Choices::NONE;
            let set = SetSecondMoveSwitchOutMoveInstruction {
                new_choice: Choices::NONE,
                previous_choice,
            };
            instructions.instruction_list.push(match attacking_side {
                SideReference::SideOne => Instruction::SetSideOneMoveSecondSwitchOutMove(set),
                SideReference::SideTwo => Instruction::SetSideTwoMoveSecondSwitchOutMove(set),
            });
        }
    }

    // L69: a drag Magic Bounce reflected drags its user's side (get_instructions_from_drag drags
    // the side opposite the one given)
    let drag_from = if choice.target == MoveTarget::User {
        attacking_side.get_other_side()
    } else {
        attacking_side
    };
    if choice.flags.drag
        && !ejected
        && state
            .get_side_immutable(&attacking_side.get_other_side())
            .get_active_immutable()
            .ability
            != Abilities::GUARDDOG
    {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L7): the secondaries first (the
        // target's contact effects -- Static, Rocky Helmet, ... -- are added to the move as
        // secondaries on its user), then the drag on each of their outcomes; the drag used to
        // return before them, so they never happened (Showdown: the hit's effects, then the
        // forced switch)
        if let Some(secondaries_vec) = &choice.secondaries {
            state.reverse_instructions(&instructions.instruction_list);
            let branches = get_instructions_from_secondaries(
                state,
                &choice,
                secondaries_vec,
                &attacking_side,
                instructions,
                hit_sub,
            );
            for branch in branches {
                state.apply_instructions(&branch.instruction_list);
                get_instructions_from_drag(state, &drag_from, branch, final_instructions);
            }
            return;
        }
        get_instructions_from_drag(state, &drag_from, instructions, final_instructions);
        return;
    }

    // alpha-poke patch (2026-10-13): the attacker's Eject Pack, its stats lowered by its own move
    // (Draco Meteor, Overheat, Close Combat, ...): it switches out as after a pivot move
    let self_eject = !ejected && {
        let side = state.get_side_immutable(&attacking_side);
        let holder = side.get_active_immutable();
        holder.item == Items::EJECTPACK
            && holder.hp > 0
            && side.visible_alive_pkmn() > 1
            && !side.force_switch
            && lowered(&attacker_boosts_before, &boosts_of(side))
    };
    if self_eject {
        instructions
            .instruction_list
            .push(Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: attacking_side,
                current_item: Items::EJECTPACK,
                new_item: Items::NONE,
            }));
        state.get_side(&attacking_side).get_active().item = Items::NONE;
    }

    // Only entered if the move causes a switch-out
    // U-turn, Volt Switch, Baton Pass, etc.
    // This deals with a bunch of flags that are required for the next turn to run properly
    if (choice.flags.pivot || self_eject) && !ejected {
        match attacking_side {
            SideReference::SideOne => {
                if state.side_one.visible_alive_pkmn() > 1 {
                    if choice.move_id == Choices::BATONPASS {
                        state.side_one.baton_passing = !state.side_one.baton_passing;
                        instructions
                            .instruction_list
                            .push(Instruction::ToggleBatonPassing(
                                ToggleBatonPassingInstruction {
                                    side_ref: SideReference::SideOne,
                                },
                            ));
                    } else if choice.move_id == Choices::SHEDTAIL {
                        state.side_one.shed_tailing = !state.side_one.shed_tailing;
                        instructions
                            .instruction_list
                            .push(Instruction::ToggleShedTailing(
                                ToggleShedTailingInstruction {
                                    side_ref: SideReference::SideOne,
                                },
                            ));
                    }
                    state.side_one.force_switch = !state.side_one.force_switch;
                    instructions
                        .instruction_list
                        .push(Instruction::ToggleSideOneForceSwitch);

                    if choice.first_move {
                        instructions.instruction_list.push(
                            Instruction::SetSideTwoMoveSecondSwitchOutMove(
                                SetSecondMoveSwitchOutMoveInstruction {
                                    new_choice: defender_choice.move_id,
                                    previous_choice: state
                                        .side_two
                                        .switch_out_move_second_saved_move,
                                },
                            ),
                        );
                        state.side_two.switch_out_move_second_saved_move = defender_choice.move_id;
                    } else {
                        instructions.instruction_list.push(
                            Instruction::SetSideTwoMoveSecondSwitchOutMove(
                                SetSecondMoveSwitchOutMoveInstruction {
                                    new_choice: Choices::NONE,
                                    previous_choice: state
                                        .side_two
                                        .switch_out_move_second_saved_move,
                                },
                            ),
                        );
                        state.side_two.switch_out_move_second_saved_move = defender_choice.move_id;
                    }
                }
            }
            SideReference::SideTwo => {
                if state.side_two.visible_alive_pkmn() > 1 {
                    if choice.move_id == Choices::BATONPASS {
                        state.side_two.baton_passing = !state.side_two.baton_passing;
                        instructions
                            .instruction_list
                            .push(Instruction::ToggleBatonPassing(
                                ToggleBatonPassingInstruction {
                                    side_ref: SideReference::SideTwo,
                                },
                            ));
                    } else if choice.move_id == Choices::SHEDTAIL {
                        state.side_two.shed_tailing = !state.side_two.shed_tailing;
                        instructions
                            .instruction_list
                            .push(Instruction::ToggleShedTailing(
                                ToggleShedTailingInstruction {
                                    side_ref: SideReference::SideTwo,
                                },
                            ));
                    }
                    state.side_two.force_switch = !state.side_two.force_switch;
                    instructions
                        .instruction_list
                        .push(Instruction::ToggleSideTwoForceSwitch);

                    if choice.first_move {
                        instructions.instruction_list.push(
                            Instruction::SetSideOneMoveSecondSwitchOutMove(
                                SetSecondMoveSwitchOutMoveInstruction {
                                    new_choice: defender_choice.move_id,
                                    previous_choice: state
                                        .side_one
                                        .switch_out_move_second_saved_move,
                                },
                            ),
                        );
                        state.side_one.switch_out_move_second_saved_move = defender_choice.move_id;
                    } else {
                        instructions.instruction_list.push(
                            Instruction::SetSideOneMoveSecondSwitchOutMove(
                                SetSecondMoveSwitchOutMoveInstruction {
                                    new_choice: Choices::NONE,
                                    previous_choice: state
                                        .side_one
                                        .switch_out_move_second_saved_move,
                                },
                            ),
                        );
                        state.side_one.switch_out_move_second_saved_move = defender_choice.move_id;
                    }
                }
            }
        }
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L65): Covert Cloak blocks the secondaries
    // on its holder only (Showdown's onModifySecondaries keeps the self ones); before, all
    let cloaked = state
        .get_side_immutable(&attacking_side.get_other_side())
        .get_active_immutable()
        .item
        == Items::COVERTCLOAK;
    let kept: Option<Vec<Secondary>> = choice.secondaries.as_ref().map(|v| {
        v.iter()
            .filter(|x| !cloaked || x.target == MoveTarget::User)
            .cloned()
            .collect()
    });
    if kept.as_ref().map_or(true, |v| v.is_empty()) {
        state.reverse_instructions(&instructions.instruction_list);
        final_instructions.push(instructions);
    } else if let Some(secondaries_vec) = &kept {
        state.reverse_instructions(&instructions.instruction_list);
        let instructions_vec_after_secondaries = get_instructions_from_secondaries(
            state,
            &choice,
            secondaries_vec,
            &attacking_side,
            instructions,
            hit_sub,
        );
        final_instructions.extend(instructions_vec_after_secondaries);
    } else {
        state.reverse_instructions(&instructions.instruction_list);
        final_instructions.push(instructions);
    }
}

fn after_move_finish(state: &mut State, final_instructions: &mut Vec<StateInstructions>) {
    for state_instructions in final_instructions.iter_mut() {
        state.apply_instructions(&state_instructions.instruction_list);

        // check if anybody has negative boosts and a whiteherb
        // if so, consume the item and set the boosts to 0
        for side_ref in [SideReference::SideOne, SideReference::SideTwo] {
            let side = state.get_side(&side_ref);
            let active_has_whiteherb = side.get_active_immutable().item == Items::WHITEHERB;
            if active_has_whiteherb {
                if side.reset_negative_boosts(side_ref, state_instructions) {
                    let active = side.get_active();
                    active.item = Items::NONE;
                    state_instructions
                        .instruction_list
                        .push(Instruction::ChangeItem(ChangeItemInstruction {
                            side_ref,
                            current_item: Items::WHITEHERB,
                            new_item: Items::NONE,
                        }));
                }
            }
        }
        state.reverse_instructions(&state_instructions.instruction_list);
    }
}

fn handle_both_moves(
    state: &mut State,
    first_move_side_choice: &mut Choice,
    second_move_side_choice: &mut Choice,
    first_move_side_ref: SideReference,
    incoming_instructions: StateInstructions,
    state_instructions_vec: &mut Vec<StateInstructions>,
    branch_on_damage: bool,
) {
    generate_instructions_from_move(
        state,
        first_move_side_choice,
        second_move_side_choice,
        first_move_side_ref,
        incoming_instructions,
        state_instructions_vec,
        branch_on_damage,
    );
    after_move_finish(state, state_instructions_vec);

    let mut i = 0;
    let vec_len = state_instructions_vec.len();
    second_move_side_choice.first_move = false;
    while i < vec_len {
        let state_instruction = state_instructions_vec.remove(0);
        generate_instructions_from_move(
            state,
            &mut second_move_side_choice.clone(), // this clone is needed because the choice may be modified in this loop
            first_move_side_choice,
            first_move_side_ref.get_other_side(),
            state_instruction,
            state_instructions_vec,
            branch_on_damage,
        );
        after_move_finish(state, state_instructions_vec);
        i += 1;
    }
}

fn run_mega_evolutions(
    state: &mut State,
    s1_mega: bool,
    s2_mega: bool,
    incoming_instructions: &mut StateInstructions,
) {
    match (s1_mega, s2_mega) {
        (true, true) => {
            let s1_speed = get_effective_speed(state, &SideReference::SideOne);
            let s2_speed = get_effective_speed(state, &SideReference::SideTwo);

            // technically missing a branch if s1_speed == s2_speed,
            // but practically this is rare enough for me to not care
            if s1_speed > s2_speed {
                mega_evolve(state, SideReference::SideOne, incoming_instructions);
                mega_evolve(state, SideReference::SideTwo, incoming_instructions);
            } else {
                mega_evolve(state, SideReference::SideTwo, incoming_instructions);
                mega_evolve(state, SideReference::SideOne, incoming_instructions);
            }
        }
        (true, false) => {
            mega_evolve(state, SideReference::SideOne, incoming_instructions);
        }
        (false, true) => {
            mega_evolve(state, SideReference::SideTwo, incoming_instructions);
        }
        (false, false) => {}
    }
}

fn mega_evolve(state: &mut State, side_ref: SideReference, instructions: &mut StateInstructions) {
    let side = state.get_side(&side_ref);
    let active_pkmn = side.get_active();

    // assumes that you can mega-evolve if this function is called
    let mega_evolve_data = active_pkmn
        .id
        .mega_evolve_target(active_pkmn.item)
        .unwrap_or_else(|| {
            panic!(
                "cannot mega evolve {:?} with {:?}",
                active_pkmn.id, active_pkmn.item
            )
        });

    // change id
    instructions
        .instruction_list
        .push(Instruction::FormeChange(FormeChangeInstruction {
            side_ref,
            name_change: mega_evolve_data.id as i16 - active_pkmn.id as i16,
        }));
    active_pkmn.id = mega_evolve_data.id;

    // change stats
    active_pkmn.recalculate_stats(&side_ref, instructions);

    // change ability / base_ability
    // base_ability is used to revert a pokemon's ability when it switches out
    // so it also needs to be changed if the mega evolution changes the pokemon's ability
    if mega_evolve_data.ability != active_pkmn.ability {
        instructions
            .instruction_list
            .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
                side_ref,
                ability_change: mega_evolve_data.ability as i16 - active_pkmn.ability as i16,
            }));
        active_pkmn.ability = mega_evolve_data.ability;
    }
    if mega_evolve_data.ability != active_pkmn.base_ability {
        instructions
            .instruction_list
            .push(Instruction::ChangeBaseAbility(ChangeAbilityInstruction {
                side_ref,
                ability_change: mega_evolve_data.ability as i16 - active_pkmn.base_ability as i16,
            }));
        active_pkmn.base_ability = mega_evolve_data.ability;
    }

    // change type
    if mega_evolve_data.types != active_pkmn.types {
        instructions
            .instruction_list
            .push(Instruction::ChangeType(ChangeType {
                side_ref,
                new_types: mega_evolve_data.types,
                old_types: active_pkmn.types,
            }));
        active_pkmn.types = mega_evolve_data.types;
    }

    instructions
        .instruction_list
        .push(Instruction::ToggleMegaEvolved(
            ToggleMegaEvolvedInstruction { side_ref },
        ));
    active_pkmn.mega_evolved = true;

    // ability on switch in
    let from = instructions.instruction_list.len();
    ability_on_switch_in(state, &side_ref, instructions);
    extend_field_durations(state, &side_ref, instructions, from);
}

pub fn generate_instructions_for_bss_team_preview(
    state: &mut State,
    side_one_move: (PokemonIndex, PokemonIndex, PokemonIndex),
    side_two_move: (PokemonIndex, PokemonIndex, PokemonIndex),
) -> Vec<StateInstructions> {
    let mut state_instructions: StateInstructions = StateInstructions::default();
    let should_last_used_move = state.use_last_used_move;

    // run the switches
    for (side_ref, move_choice) in [
        (SideReference::SideOne, side_one_move),
        (SideReference::SideTwo, side_two_move),
    ] {
        let side = state.get_side(&side_ref);
        state_instructions
            .instruction_list
            .push(Instruction::Switch(SwitchInstruction {
                side_ref,
                previous_index: side.active_index,
                next_index: move_choice.0,
            }));
        if should_last_used_move {
            state_instructions
                .instruction_list
                .push(Instruction::SetLastUsedMove(SetLastUsedMoveInstruction {
                    side_ref,
                    last_used_move: LastUsedMove::Switch(move_choice.0),
                    previous_last_used_move: side.last_used_move,
                }));
            side.last_used_move = LastUsedMove::Switch(move_choice.0);
        }
        side.active_index = move_choice.0;
    }

    let pkmn_speed_order = if get_effective_speed(state, &SideReference::SideOne)
        > get_effective_speed(state, &SideReference::SideTwo)
    {
        vec![SideReference::SideOne, SideReference::SideTwo]
    } else {
        vec![SideReference::SideTwo, SideReference::SideOne]
    };

    for side_ref in pkmn_speed_order.iter() {
        let from = state_instructions.instruction_list.len();
        ability_on_switch_in(state, side_ref, &mut state_instructions);
        extend_field_durations(state, side_ref, &mut state_instructions, from);
        item_on_switch_in(state, side_ref, &mut state_instructions);
    }
    state.reverse_instructions(&state_instructions.instruction_list);

    // after this point the instructions are reversed,
    // so the state does not need to be modified to reflect the additional instructions added

    // faint the pkmn that were not selected
    for (side_ref, move_choice) in [
        (SideReference::SideOne, side_one_move),
        (SideReference::SideTwo, side_two_move),
    ] {
        let pkmn_indices = [move_choice.0, move_choice.1, move_choice.2];
        let mut pkmn_iter = state.get_side_immutable(&side_ref).pokemon.into_iter();
        while let Some(_) = pkmn_iter.next() {
            if !pkmn_indices.contains(&pkmn_iter.pokemon_index) {
                state_instructions
                    .instruction_list
                    .push(Instruction::TeamPreviewFaintIndex(
                        side_ref,
                        pkmn_iter.pokemon_index,
                    ));
            }
        }
    }

    state_instructions
        .instruction_list
        .push(Instruction::ToggleTeamPreview);

    vec![state_instructions]
}

pub fn generate_instructions_from_move_pair(
    state: &mut State,
    side_one_move: &MoveChoice,
    side_two_move: &MoveChoice,
    branch_on_damage: bool,
) -> Vec<StateInstructions> {
    #[cfg(feature = "bss")]
    if state.team_preview {
        let (s1_lead, s1_reserve_1, s1_reserve_2) = match side_one_move {
            MoveChoice::TeamPreview(a, b, c) => (*a, *b, *c),
            _ => panic!("Side one move is not a team preview"),
        };
        let (s2_lead, s2_reserve_1, s2_reserve_2) = match side_two_move {
            MoveChoice::TeamPreview(a, b, c) => (*a, *b, *c),
            _ => panic!("Side two move is not a team preview"),
        };
        return generate_instructions_for_bss_team_preview(
            state,
            (s1_lead, s1_reserve_1, s1_reserve_2),
            (s2_lead, s2_reserve_1, s2_reserve_2),
        );
    }

    let mut side_one_choice;
    let mut s1_tera = false;
    let mut s1_mega = false;
    let mut s1_replacing_fainted_pkmn = false;
    match side_one_move {
        MoveChoice::Switch(switch_id) => {
            if state.side_one.get_active().hp == 0 {
                s1_replacing_fainted_pkmn = true;
            }
            side_one_choice = Choice::default();
            side_one_choice.switch_id = *switch_id;
            side_one_choice.category = MoveCategory::Switch;
        }
        MoveChoice::Move(move_index) => {
            side_one_choice = state.side_one.get_active().moves[move_index].choice.clone();
            side_one_choice.move_index = *move_index;
        }
        MoveChoice::MoveTera(move_index) => {
            side_one_choice = state.side_one.get_active().moves[move_index].choice.clone();
            side_one_choice.move_index = *move_index;
            s1_tera = true;
        }
        MoveChoice::MoveMega(move_index) => {
            side_one_choice = state.side_one.get_active().moves[move_index].choice.clone();
            side_one_choice.move_index = *move_index;
            s1_mega = true;
        }
        MoveChoice::TeamPreview(_, _, _) => {
            panic!("Team preview should not be handled in generate_instructions_from_move_pair");
        }
        MoveChoice::None => {
            side_one_choice = Choice::default();
        }
    }

    let mut side_two_choice;
    let mut s2_replacing_fainted_pkmn = false;
    let mut s2_tera = false;
    let mut s2_mega = false;
    match side_two_move {
        MoveChoice::Switch(switch_id) => {
            if state.side_two.get_active().hp == 0 {
                s2_replacing_fainted_pkmn = true;
            }
            side_two_choice = Choice::default();
            side_two_choice.switch_id = *switch_id;
            side_two_choice.category = MoveCategory::Switch;
        }
        MoveChoice::Move(move_index) => {
            side_two_choice = state.side_two.get_active().moves[move_index].choice.clone();
            side_two_choice.move_index = *move_index;
        }
        MoveChoice::MoveTera(move_index) => {
            side_two_choice = state.side_two.get_active().moves[move_index].choice.clone();
            side_two_choice.move_index = *move_index;
            s2_tera = true;
        }
        MoveChoice::MoveMega(move_index) => {
            side_two_choice = state.side_two.get_active().moves[move_index].choice.clone();
            side_two_choice.move_index = *move_index;
            s2_mega = true;
        }
        MoveChoice::TeamPreview(_, _, _) => {
            panic!("Team preview should not be handled in generate_instructions_from_move_pair");
        }
        MoveChoice::None => {
            side_two_choice = Choice::default();
        }
    }

    let mut state_instructions_vec: Vec<StateInstructions> = Vec::with_capacity(4);
    let mut incoming_instructions: StateInstructions = StateInstructions::default();

    // short-circuit if pursuit hitting a switching target
    // pursuit screws up some assumptions so it's just easier to separate the logic if we detect
    // that pursuit is being used against a switching target
    //
    // normally, the order of operations is:
    //     run switches -> run megas/teras -> run moves
    // however, if pursuit is used against a switching opponent, the order of operations becomes:
    //    run megas/teras -> run pursuit -> run switches
    if side_one_choice.move_id == Choices::PURSUIT
        && side_two_choice.category == MoveCategory::Switch
    {
        get_instructions_from_pursuit_hitting_switching_target(
            state,
            SideReference::SideOne,
            SideReference::SideTwo,
            &mut side_one_choice,
            &mut side_two_choice,
            incoming_instructions,
            &mut state_instructions_vec,
            s1_mega,
            s1_tera,
            branch_on_damage,
        );
        return state_instructions_vec;
    } else if side_two_choice.move_id == Choices::PURSUIT
        && side_one_choice.category == MoveCategory::Switch
    {
        get_instructions_from_pursuit_hitting_switching_target(
            state,
            SideReference::SideTwo,
            SideReference::SideOne,
            &mut side_two_choice,
            &mut side_one_choice,
            incoming_instructions,
            &mut state_instructions_vec,
            s2_mega,
            s2_tera,
            branch_on_damage,
        );
        return state_instructions_vec;
    }

    // run switches
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L39): both switching, the faster of the
    // two leaving first (Showdown's switch actions by the outgoing mon's speed, reversed in
    // Trick Room; a tie: side one first, an approximation); before, always side one first
    let mut switches = [
        (side_one_move, SideReference::SideOne),
        (side_two_move, SideReference::SideTwo),
    ];
    if matches!(side_one_move, MoveChoice::Switch(_))
        && matches!(side_two_move, MoveChoice::Switch(_))
    {
        let one = get_effective_speed(state, &SideReference::SideOne);
        let two = get_effective_speed(state, &SideReference::SideTwo);
        if (two > one) != state.trick_room.active && one != two {
            switches.swap(0, 1);
        }
    }
    for (choice, side_ref) in switches {
        if let MoveChoice::Switch(switch_id) = choice {
            generate_instructions_from_switch(
                state,
                *switch_id,
                side_ref,
                &mut incoming_instructions,
            );
        }
    }
    if s1_tera {
        state.side_one.get_active().terastallized = true;
        incoming_instructions
            .instruction_list
            .push(Instruction::ToggleTerastallized(
                ToggleTerastallizedInstruction {
                    side_ref: SideReference::SideOne,
                },
            ));
        embody_aspect_on_tera(state, SideReference::SideOne, &mut incoming_instructions);
    }
    if s2_tera {
        state.side_two.get_active().terastallized = true;
        incoming_instructions
            .instruction_list
            .push(Instruction::ToggleTerastallized(
                ToggleTerastallizedInstruction {
                    side_ref: SideReference::SideTwo,
                },
            ));
        embody_aspect_on_tera(state, SideReference::SideTwo, &mut incoming_instructions);
    }

    run_mega_evolutions(state, s1_mega, s2_mega, &mut incoming_instructions);

    modify_choice_priority(&state, &SideReference::SideOne, &mut side_one_choice);
    modify_choice_priority(&state, &SideReference::SideTwo, &mut side_two_choice);

    // reverse instructions because mega-evolving might've added some
    state.reverse_instructions(&incoming_instructions.instruction_list);

    let items_before = incoming_instructions.instruction_list.len();
    let order = moves_first(
        &state,
        &side_one_choice,
        &side_two_choice,
        &mut incoming_instructions,
    );
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): Quick Claw, a 1/5 chance to move
    // first in the priority bracket (not after a Custap Berry: moves_first used it, an instruction)
    let custap = incoming_instructions.instruction_list.len() > items_before;
    let side_one_first =
        quick_claw_first_chance(&state, &side_one_choice, &side_two_choice, &order, custap);
    let order = if side_one_first >= 1.0 {
        SideMovesFirst::SideOne
    } else if side_one_first <= 0.0 {
        SideMovesFirst::SideTwo
    } else {
        SideMovesFirst::SpeedTie
    };
    match order {
        SideMovesFirst::SideOne => {
            handle_both_moves(
                state,
                &mut side_one_choice,
                &mut side_two_choice,
                SideReference::SideOne,
                incoming_instructions,
                &mut state_instructions_vec,
                branch_on_damage,
            );

            let mut harvested = vec![];
            for state_instruction in state_instructions_vec.iter_mut() {
                state.apply_instructions(&state_instruction.instruction_list);
                if !(s1_replacing_fainted_pkmn
                    || s2_replacing_fainted_pkmn
                    || state.side_one.force_switch
                    || state.side_two.force_switch)
                {
                    harvested.extend(end_of_turn_with_harvest(
                        state,
                        state_instruction,
                        &SideReference::SideOne,
                    ));
                }
                state.reverse_instructions(&state_instruction.instruction_list);
            }
            state_instructions_vec.extend(harvested);
        }
        SideMovesFirst::SideTwo => {
            handle_both_moves(
                state,
                &mut side_two_choice,
                &mut side_one_choice,
                SideReference::SideTwo,
                incoming_instructions,
                &mut state_instructions_vec,
                branch_on_damage,
            );
            let mut harvested = vec![];
            for state_instruction in state_instructions_vec.iter_mut() {
                state.apply_instructions(&state_instruction.instruction_list);
                if !(s1_replacing_fainted_pkmn
                    || s2_replacing_fainted_pkmn
                    || state.side_one.force_switch
                    || state.side_two.force_switch)
                {
                    harvested.extend(end_of_turn_with_harvest(
                        state,
                        state_instruction,
                        &SideReference::SideTwo,
                    ));
                }
                state.reverse_instructions(&state_instruction.instruction_list);
            }
            state_instructions_vec.extend(harvested);
        }
        SideMovesFirst::SpeedTie => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L29): the second order gets the moves
            // as they were (handle_both_moves changes them: an item's added secondaries, Rocky
            // Helmet's, came twice); before, both orders used the same ones
            let (mut side_one_choice_2, mut side_two_choice_2) =
                (side_one_choice.clone(), side_two_choice.clone());
            let mut side_one_moves_first_instruction = incoming_instructions.clone();
            incoming_instructions.update_percentage(1.0 - side_one_first);
            side_one_moves_first_instruction.update_percentage(side_one_first);

            // side_one moves first
            handle_both_moves(
                state,
                &mut side_one_choice,
                &mut side_two_choice,
                SideReference::SideOne,
                side_one_moves_first_instruction,
                &mut state_instructions_vec,
                branch_on_damage,
            );
            let mut harvested = vec![];
            for state_instruction in state_instructions_vec.iter_mut() {
                state.apply_instructions(&state_instruction.instruction_list);
                if !(s1_replacing_fainted_pkmn
                    || s2_replacing_fainted_pkmn
                    || state.side_one.force_switch
                    || state.side_two.force_switch)
                {
                    harvested.extend(end_of_turn_with_harvest(
                        state,
                        state_instruction,
                        &SideReference::SideOne,
                    ));
                }
                state.reverse_instructions(&state_instruction.instruction_list);
            }
            state_instructions_vec.extend(harvested);

            // side_two moves first
            let mut side_two_moves_first_si = Vec::with_capacity(4);
            handle_both_moves(
                state,
                &mut side_two_choice_2,
                &mut side_one_choice_2,
                SideReference::SideTwo,
                incoming_instructions,
                &mut side_two_moves_first_si,
                branch_on_damage,
            );
            let mut harvested = vec![];
            for state_instruction in side_two_moves_first_si.iter_mut() {
                state.apply_instructions(&state_instruction.instruction_list);
                if !(s1_replacing_fainted_pkmn
                    || s2_replacing_fainted_pkmn
                    || state.side_one.force_switch
                    || state.side_two.force_switch)
                {
                    harvested.extend(end_of_turn_with_harvest(
                        state,
                        state_instruction,
                        &SideReference::SideTwo,
                    ));
                }
                state.reverse_instructions(&state_instruction.instruction_list);
            }
            side_two_moves_first_si.extend(harvested);

            // combine both vectors into the final vector
            state_instructions_vec.extend(side_two_moves_first_si);
        }
    }
    state_instructions_vec
}

fn get_instructions_from_pursuit_hitting_switching_target(
    state: &mut State,
    pursuiting_side_ref: SideReference,
    switching_side_ref: SideReference,
    pursuit_choice: &mut Choice,
    switching_choice: &mut Choice,
    mut incoming_instructions: StateInstructions,
    state_instructions_vec: &mut Vec<StateInstructions>,
    pursuiting_side_mega: bool,
    pursuiting_side_tera: bool,
    branch_on_damage: bool,
) {
    // pursuiting side mega / tera
    if pursuiting_side_mega {
        mega_evolve(state, pursuiting_side_ref, &mut incoming_instructions);
    }
    if pursuiting_side_tera {
        state
            .get_side(&pursuiting_side_ref)
            .get_active()
            .terastallized = true;
        incoming_instructions
            .instruction_list
            .push(Instruction::ToggleTerastallized(
                ToggleTerastallizedInstruction {
                    side_ref: SideReference::SideOne,
                },
            ));
    }

    // reverse instructions because mega/tera might've added some
    state.reverse_instructions(&incoming_instructions.instruction_list);

    // pursuiting move
    generate_instructions_from_move(
        state,
        pursuit_choice,
        switching_choice,
        pursuiting_side_ref,
        incoming_instructions,
        state_instructions_vec,
        branch_on_damage,
    );
    after_move_finish(state, state_instructions_vec);

    // loop through branches from pursuiting move, and apply the switching move on each of them
    let mut i = 0;
    let vec_len = state_instructions_vec.len();
    switching_choice.first_move = false;
    while i < vec_len {
        let mut state_instruction = state_instructions_vec.remove(0);
        state.apply_instructions(&state_instruction.instruction_list);
        if state.get_side(&switching_side_ref).get_active().hp > 0 {
            generate_instructions_from_switch(
                state,
                switching_choice.switch_id,
                switching_side_ref,
                &mut state_instruction,
            );
        }
        state.reverse_instructions(&state_instruction.instruction_list);
        after_move_finish(state, state_instructions_vec);
        state_instructions_vec.push(state_instruction);
        i += 1;
    }

    let mut harvested = vec![];
    for state_instruction in state_instructions_vec.iter_mut() {
        state.apply_instructions(&state_instruction.instruction_list);
        harvested.extend(end_of_turn_with_harvest(
            state,
            state_instruction,
            &SideReference::SideOne,
        ));
        state.reverse_instructions(&state_instruction.instruction_list);
    }
    state_instructions_vec.extend(harvested);
}

pub fn calculate_damage_rolls(
    mut state: State,
    attacking_side_ref: &SideReference,
    mut choice: Choice,
    mut defending_choice: &Choice,
) -> Option<Vec<i16>> {
    let mut incoming_instructions = StateInstructions::default();

    if choice.flags.charge {
        choice.flags.charge = false;
    }
    if choice.move_id == Choices::FAKEOUT || choice.move_id == Choices::FIRSTIMPRESSION {
        state.get_side(attacking_side_ref).last_used_move = LastUsedMove::Switch(PokemonIndex::P0);
    }

    let attacker_active = state
        .get_side_immutable(attacking_side_ref)
        .get_active_immutable();
    let defender_active = state
        .get_side_immutable(&attacking_side_ref.get_other_side())
        .get_active_immutable();
    match choice.move_id {
        Choices::SEISMICTOSS => {
            if type_effectiveness_modifier(&PokemonType::NORMAL, &defender_active) == 0.0 {
                return None;
            }
            return Some(vec![attacker_active.level as i16]);
        }
        Choices::NIGHTSHADE => {
            if type_effectiveness_modifier(&PokemonType::GHOST, &defender_active) == 0.0 {
                return None;
            }
            return Some(vec![attacker_active.level as i16]);
        }
        Choices::FINALGAMBIT => {
            if type_effectiveness_modifier(&PokemonType::GHOST, &defender_active) == 0.0 {
                return None;
            }
            return Some(vec![attacker_active.hp]);
        }
        Choices::ENDEAVOR => {
            if type_effectiveness_modifier(&PokemonType::GHOST, &defender_active) == 0.0
                || defender_active.hp <= attacker_active.hp
            {
                return None;
            }
            return Some(vec![defender_active.hp - attacker_active.hp]);
        }
        Choices::PAINSPLIT => {
            if type_effectiveness_modifier(&PokemonType::GHOST, &defender_active) == 0.0
                || defender_active.hp <= attacker_active.hp
            {
                return None;
            }
            return Some(vec![
                defender_active.hp - (attacker_active.hp + defender_active.hp) / 2,
            ]);
        }
        Choices::SUPERFANG
            if type_effectiveness_modifier(&PokemonType::NORMAL, &defender_active) == 0.0 =>
        {
            return None;
        }
        Choices::SUPERFANG | Choices::NATURESMADNESS | Choices::RUINATION => {
            return Some(vec![defender_active.hp / 2]);
        }
        Choices::SUCKERPUNCH | Choices::THUNDERCLAP => {
            defending_choice = MOVES.get(&Choices::TACKLE).unwrap();
        }

        _ => {}
    }

    before_move(
        &mut state,
        &mut choice,
        defending_choice,
        attacking_side_ref,
        &mut incoming_instructions,
    );

    if matches!(choice.move_id, Choices::FUTURESIGHT | Choices::DOOMDESIRE) {
        choice = MOVES.get(&choice.move_id)?.clone();
    }

    let mut return_vec = Vec::with_capacity(4);
    if let Some((damage, crit_damage)) =
        calculate_damage(&state, attacking_side_ref, &choice, DamageRolls::Max)
    {
        return_vec.push(damage);
        return_vec.push(crit_damage);
        Some(return_vec)
    } else {
        None
    }
}

/// alpha-poke patch (2026-10-16, doc/engine-diff.md L34): the exact 16 rolls of a move's damage
/// (without, with a crit) as calculate_damage_rolls computes its max: the dual-engine tests
/// check Showdown's damage is one of them; None for a fixed-damage or no-damage move
pub fn calculate_damage_roll_sets(
    mut state: State,
    attacking_side_ref: &SideReference,
    mut choice: Choice,
    mut defending_choice: &Choice,
) -> Option<([i16; 16], [i16; 16])> {
    let mut incoming_instructions = StateInstructions::default();
    if choice.flags.charge {
        choice.flags.charge = false;
    }
    if choice.move_id == Choices::FAKEOUT || choice.move_id == Choices::FIRSTIMPRESSION {
        state.get_side(attacking_side_ref).last_used_move = LastUsedMove::Switch(PokemonIndex::P0);
    }
    if matches!(choice.move_id, Choices::SUCKERPUNCH | Choices::THUNDERCLAP) {
        defending_choice = MOVES.get(&Choices::TACKLE).unwrap();
    }
    if fixed_damage(&state, &choice, attacking_side_ref).is_some() {
        return None;
    }
    before_move(
        &mut state,
        &mut choice,
        defending_choice,
        attacking_side_ref,
        &mut incoming_instructions,
    );
    damage_rolls(&state, attacking_side_ref, &choice)
}

pub fn calculate_both_damage_rolls(
    state: &State,
    mut s1_choice: Choice,
    mut s2_choice: Choice,
    side_one_moves_first: bool,
) -> (Option<Vec<i16>>, Option<Vec<i16>>) {
    if side_one_moves_first {
        s1_choice.first_move = true;
        s2_choice.first_move = false;
    } else {
        s1_choice.first_move = false;
        s2_choice.first_move = true;
    }

    let damages_dealt_s1 = calculate_damage_rolls(
        state.clone(),
        &SideReference::SideOne,
        s1_choice.clone(),
        &s2_choice,
    );
    let damages_dealt_s2 = calculate_damage_rolls(
        state.clone(),
        &SideReference::SideTwo,
        s2_choice,
        &s1_choice,
    );

    (damages_dealt_s1, damages_dealt_s2)
}

#[cfg(test)]
mod tests {
    use super::super::abilities::Abilities;
    use super::super::state::{PokemonVolatileStatus, Terrain, Weather};
    use super::*;
    use crate::choices::{Choices, MOVES};
    use crate::instruction::{
        ApplyVolatileStatusInstruction, BoostInstruction, ChangeItemInstruction,
        ChangeStatusInstruction, ChangeSubsituteHealthInstruction, ChangeTerrain,
        DamageInstruction, EnableMoveInstruction, SwitchInstruction,
    };
    use crate::state::{
        Move, PokemonBoostableStat, PokemonIndex, PokemonMoveIndex, PokemonSideCondition,
        PokemonStatus, SideReference, State,
    };

    #[test]
    fn test_drag_move_as_second_move_exits_early_if_opponent_used_drag_move() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::DRAGONTAIL).unwrap().to_owned();
        choice.first_move = false;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::DRAGONTAIL).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );
        assert_eq!(instructions, vec![StateInstructions::default()])
    }

    #[test]
    fn test_electric_move_does_nothing_versus_ground_type() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::THUNDERBOLT).unwrap().to_owned();
        state.side_two.get_active().types = (PokemonType::GROUND, PokemonType::TYPELESS);
        choice.first_move = false;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );
        assert_eq!(instructions, vec![StateInstructions::default()])
    }

    #[test]
    fn test_grass_type_cannot_have_powder_move_used_against_it() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::SPORE).unwrap().to_owned(); // Spore is a powder move
        state.side_two.get_active().types = (PokemonType::GRASS, PokemonType::TYPELESS);
        choice.first_move = false;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        #[cfg(any(
            feature = "gen6",
            feature = "gen7",
            feature = "gen8",
            feature = "gen9",
            feature = "champions"
        ))]
        let expected_instructions = vec![StateInstructions::default()];

        #[cfg(any(feature = "gen4", feature = "gen5"))]
        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ChangeStatus(ChangeStatusInstruction {
                side_ref: SideReference::SideTwo,
                pokemon_index: PokemonIndex::P0,
                old_status: PokemonStatus::NONE,
                new_status: PokemonStatus::SLEEP,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_spikes_sets_first_layer() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::SPIKES).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ChangeSideCondition(
                ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::Spikes,
                    amount: 1,
                },
            )],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_spikes_layers_cannot_exceed_3() {
        let mut state: State = State::default();
        state.side_two.side_conditions.spikes = 3;
        let mut choice = MOVES.get(&Choices::SPIKES).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_aurora_veil_works_in_hail() {
        let mut state: State = State::default();
        state.weather.weather_type = Weather::HAIL;
        let mut choice = MOVES.get(&Choices::AURORAVEIL).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ChangeSideCondition(
                ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::AuroraVeil,
                    amount: 5,
                },
            )],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_auroa_veil_fails_outside_hail() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::AURORAVEIL).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_auroa_veil_fails_outside_of_hail() {
        let mut state: State = State::default();
        state.weather.weather_type = Weather::NONE;
        let mut choice = MOVES.get(&Choices::AURORAVEIL).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_stealthrock_cannot_exceed_1_layer() {
        let mut state: State = State::default();
        state.side_two.side_conditions.stealth_rock = 1;
        let mut choice = MOVES.get(&Choices::STEALTHROCK).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_stoneaxe_damage_and_stealthrock_setting() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::STONEAXE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 10.000002,
                instruction_list: vec![],
            },
            StateInstructions {
                percentage: 90.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 51,
                    }),
                    Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                        side_ref: SideReference::SideTwo,
                        side_condition: PokemonSideCondition::Stealthrock,
                        amount: 1,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_ceaselessedge_damage_and_stealthrock_setting() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::CEASELESSEDGE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 10.000002,
                instruction_list: vec![],
            },
            StateInstructions {
                percentage: 90.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 51,
                    }),
                    Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                        side_ref: SideReference::SideTwo,
                        side_condition: PokemonSideCondition::Spikes,
                        amount: 1,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_100_percent_secondary_volatilestatus() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::CHATTER).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 51,
                }),
                Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
                    side_ref: SideReference::SideTwo,
                    volatile_status: PokemonVolatileStatus::CONFUSION,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_possible_secondary_volatilestatus() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::CONFUSION).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 90.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 40,
                })],
            },
            StateInstructions {
                percentage: 10.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 40,
                    }),
                    Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_possible_secondary_volatilestatus_with_possible_accuracy() {
        let mut state: State = State::default();
        state.side_two.get_active().hp = 400;
        state.side_two.get_active().maxhp = 400;
        let mut choice = MOVES.get(&Choices::AXEKICK).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 10.000002,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 50, // This move has recoil lol
                })],
            },
            StateInstructions {
                percentage: 63.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 188,
                })],
            },
            StateInstructions {
                percentage: 27.0000019,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 188,
                    }),
                    Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_volatile_status_applied_to_self() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::AQUARING).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ApplyVolatileStatus(
                ApplyVolatileStatusInstruction {
                    side_ref: SideReference::SideOne,
                    volatile_status: PokemonVolatileStatus::AQUARING,
                },
            )],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_volatile_status_applied_to_opponent() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::ATTRACT).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ApplyVolatileStatus(
                ApplyVolatileStatusInstruction {
                    side_ref: SideReference::SideTwo,
                    volatile_status: PokemonVolatileStatus::ATTRACT,
                },
            )],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_cannot_apply_volatile_status_twice() {
        let mut state: State = State::default();
        state
            .side_two
            .volatile_statuses
            .insert(PokemonVolatileStatus::ATTRACT);
        let mut choice = MOVES.get(&Choices::ATTRACT).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_substitute_failing_if_user_has_less_than_25_percent_hp() {
        let mut state: State = State::default();
        state.side_one.get_active().hp = 25;
        let mut choice = MOVES.get(&Choices::SUBSTITUTE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_shedtail_failing_if_user_has_less_than_50_percent_hp() {
        let mut state: State = State::default();
        state.side_one.get_active().hp = 50;
        let mut choice = MOVES.get(&Choices::SHEDTAIL).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_drag_move() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::WHIRLWIND).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 20.0,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                })],
            },
            StateInstructions {
                percentage: 20.0,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P2,
                })],
            },
            StateInstructions {
                percentage: 20.0,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P3,
                })],
            },
            StateInstructions {
                percentage: 20.0,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P4,
                })],
            },
            StateInstructions {
                percentage: 20.0,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P5,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_drag_move_with_fainted_reserve() {
        let mut state: State = State::default();
        state.side_two.pokemon[PokemonIndex::P1].hp = 0;
        state.side_two.pokemon[PokemonIndex::P3].hp = 0;
        let mut choice = MOVES.get(&Choices::WHIRLWIND).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 33.333336,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P2,
                })],
            },
            StateInstructions {
                percentage: 33.333336,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P4,
                })],
            },
            StateInstructions {
                percentage: 33.333336,
                instruction_list: vec![Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideTwo,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P5,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_damaging_drag_move_with_fainted_reserve() {
        let mut state: State = State::default();
        state.side_two.pokemon[PokemonIndex::P1].hp = 0;
        state.side_two.pokemon[PokemonIndex::P3].hp = 0;
        let mut choice = MOVES.get(&Choices::DRAGONTAIL).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 10.0000019,
                instruction_list: vec![], // The move missed
            },
            StateInstructions {
                percentage: 30.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 48,
                    }),
                    Instruction::Switch(SwitchInstruction {
                        side_ref: SideReference::SideTwo,
                        previous_index: PokemonIndex::P0,
                        next_index: PokemonIndex::P2,
                    }),
                ],
            },
            StateInstructions {
                percentage: 30.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 48,
                    }),
                    Instruction::Switch(SwitchInstruction {
                        side_ref: SideReference::SideTwo,
                        previous_index: PokemonIndex::P0,
                        next_index: PokemonIndex::P4,
                    }),
                ],
            },
            StateInstructions {
                percentage: 30.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 48,
                    }),
                    Instruction::Switch(SwitchInstruction {
                        side_ref: SideReference::SideTwo,
                        previous_index: PokemonIndex::P0,
                        next_index: PokemonIndex::P5,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_damaging_drag_that_knocks_out_defender() {
        let mut state: State = State::default();
        state.side_two.pokemon[PokemonIndex::P1].hp = 0;
        state.side_two.pokemon[PokemonIndex::P3].hp = 0;
        state.side_two.get_active().hp = 5;
        let mut choice = MOVES.get(&Choices::DRAGONTAIL).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 10.0000019,
                instruction_list: vec![], // The move missed
            },
            StateInstructions {
                percentage: 90.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 5,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_drag_versus_no_alive_reserved() {
        let mut state: State = State::default();
        state.side_two.pokemon[PokemonIndex::P1].hp = 0;
        state.side_two.pokemon[PokemonIndex::P2].hp = 0;
        state.side_two.pokemon[PokemonIndex::P3].hp = 0;
        state.side_two.pokemon[PokemonIndex::P4].hp = 0;
        state.side_two.pokemon[PokemonIndex::P5].hp = 0;
        let mut choice = MOVES.get(&Choices::WHIRLWIND).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_drag_move_with_fainted_reserve_and_prior_instruction() {
        let mut state: State = State::default();
        state.side_two.pokemon[PokemonIndex::P1].hp = 0;
        state.side_two.pokemon[PokemonIndex::P3].hp = 0;
        let mut choice = MOVES.get(&Choices::WHIRLWIND).unwrap().to_owned();

        let previous_instruction = StateInstructions {
            percentage: 50.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 5,
            })],
        };

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            previous_instruction,
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 16.666668,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideOne,
                        damage_amount: 5,
                    }),
                    Instruction::Switch(SwitchInstruction {
                        side_ref: SideReference::SideTwo,
                        previous_index: PokemonIndex::P0,
                        next_index: PokemonIndex::P2,
                    }),
                ],
            },
            StateInstructions {
                percentage: 16.666668,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideOne,
                        damage_amount: 5,
                    }),
                    Instruction::Switch(SwitchInstruction {
                        side_ref: SideReference::SideTwo,
                        previous_index: PokemonIndex::P0,
                        next_index: PokemonIndex::P4,
                    }),
                ],
            },
            StateInstructions {
                percentage: 16.666668,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideOne,
                        damage_amount: 5,
                    }),
                    Instruction::Switch(SwitchInstruction {
                        side_ref: SideReference::SideTwo,
                        previous_index: PokemonIndex::P0,
                        next_index: PokemonIndex::P5,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    #[cfg(any(feature = "gen9", feature = "champions"))]
    fn test_basic_status_move() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::GLARE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ChangeStatus(ChangeStatusInstruction {
                side_ref: SideReference::SideTwo,
                pokemon_index: PokemonIndex::P0,
                old_status: PokemonStatus::NONE,
                new_status: PokemonStatus::PARALYZE,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    #[cfg(any(feature = "gen9", feature = "champions"))]
    fn test_status_move_that_can_miss() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::THUNDERWAVE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 10.000002,
                instruction_list: vec![],
            },
            StateInstructions {
                percentage: 90.0,
                instruction_list: vec![Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideTwo,
                    pokemon_index: PokemonIndex::P0,
                    old_status: PokemonStatus::NONE,
                    new_status: PokemonStatus::PARALYZE,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_status_move_that_can_miss_but_is_blocked_by_ability() {
        let mut state: State = State::default();
        state.side_two.get_active().ability = Abilities::LIMBER;
        let mut choice = MOVES.get(&Choices::THUNDERWAVE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_flamebody_conditional_burn_on_contact() {
        let mut state: State = State::default();
        state.side_two.get_active().ability = Abilities::FLAMEBODY;
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 70.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 48,
                })],
            },
            StateInstructions {
                percentage: 30.0000019,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 48,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideOne,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_protectivepads_stops_flamebody() {
        let mut state: State = State::default();
        state.side_two.get_active().ability = Abilities::FLAMEBODY;
        state.side_one.get_active().item = Items::PROTECTIVEPADS;
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 48,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_flamebody_versus_noncontact_move() {
        let mut state: State = State::default();
        state.side_two.get_active().ability = Abilities::FLAMEBODY;
        let mut choice = MOVES.get(&Choices::WATERGUN).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 32,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_flamebody_versus_fire_type() {
        let mut state: State = State::default();
        state.side_one.get_active().types.0 = PokemonType::FIRE;
        state.side_two.get_active().ability = Abilities::FLAMEBODY;
        let mut choice = MOVES.get(&Choices::WATERGUN).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 32,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_move_with_multiple_secondaries() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::FIREFANG).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 5.00000095,
                instruction_list: vec![],
            },
            StateInstructions {
                percentage: 76.9499969,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 51,
                })],
            },
            StateInstructions {
                percentage: 8.55000019,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 51,
                    }),
                    Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        volatile_status: PokemonVolatileStatus::FLINCH,
                    }),
                ],
            },
            StateInstructions {
                percentage: 8.55000019,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 51,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                ],
            },
            StateInstructions {
                percentage: 0.949999988,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 51,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                    Instruction::ApplyVolatileStatus(ApplyVolatileStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        volatile_status: PokemonVolatileStatus::FLINCH,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_flamebody() {
        let mut state: State = State::default();
        state.side_two.get_active().ability = Abilities::FLAMEBODY;
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 70.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 48,
                })],
            },
            StateInstructions {
                percentage: 30.000002,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 48,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideOne,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                ],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_flamebody_creating_a_move_with_multiple_secondaries() {
        let mut state: State = State::default();
        state.side_two.get_active().ability = Abilities::FLAMEBODY;
        let mut choice = MOVES.get(&Choices::FIREPUNCH).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 63.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 60,
                })],
            },
            StateInstructions {
                percentage: 27.0000019,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 60,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideOne,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                ],
            },
            StateInstructions {
                percentage: 7.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 60,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                ],
            },
            StateInstructions {
                percentage: 3.0,
                instruction_list: vec![
                    Instruction::Damage(DamageInstruction {
                        side_ref: SideReference::SideTwo,
                        damage_amount: 60,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideTwo,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                    Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: SideReference::SideOne,
                        pokemon_index: PokemonIndex::P0,
                        old_status: PokemonStatus::NONE,
                        new_status: PokemonStatus::BURN,
                    }),
                ],
            },
        ];
        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_substitute_does_not_block_rest() {
        let mut state: State = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::SUBSTITUTE);
        state.side_one.get_active().hp = state.side_one.get_active().maxhp - 1;
        let mut choice = MOVES.get(&Choices::REST).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P0,
                    old_status: PokemonStatus::NONE,
                    new_status: PokemonStatus::SLEEP,
                }),
                Instruction::SetRestTurns(SetSleepTurnsInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P0,
                    new_turns: 3,
                    previous_turns: 0,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 1,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_heal_move() {
        let mut state: State = State::default();
        state.side_one.get_active().hp = 1;
        let mut choice = MOVES.get(&Choices::RECOVER).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 50,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_heal_move_generates_no_instruction_at_maxhp() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::RECOVER).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_negative_heal_move() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::EXPLOSION).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 100,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 100,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_negative_heal_move_does_not_overkill() {
        let mut state: State = State::default();
        state.side_one.get_active().hp = 1;
        let mut choice = MOVES.get(&Choices::EXPLOSION).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 1,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 100,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_heal_move_does_not_overheal() {
        let mut state: State = State::default();
        state.side_one.get_active().hp = 55;
        let mut choice = MOVES.get(&Choices::RECOVER).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 45,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_boosting_move() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::SWORDSDANCE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Boost(BoostInstruction {
                side_ref: SideReference::SideOne,
                stat: PokemonBoostableStat::Attack,
                amount: 2,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_does_not_overboost() {
        let mut state: State = State::default();
        state.side_one.attack_boost = 5;
        let mut choice = MOVES.get(&Choices::SWORDSDANCE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Boost(BoostInstruction {
                side_ref: SideReference::SideOne,
                stat: PokemonBoostableStat::Attack,
                amount: 1,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_no_instruction_when_boosting_at_max() {
        let mut state: State = State::default();
        state.side_one.attack_boost = 6;
        let mut choice = MOVES.get(&Choices::SWORDSDANCE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_boost_lowering_that_can_miss() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::KINESIS).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 19.999998,
                instruction_list: vec![],
            },
            StateInstructions {
                percentage: 80.0,
                instruction_list: vec![Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideTwo,
                    stat: PokemonBoostableStat::Accuracy,
                    amount: -1,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_basic_boost_lowering() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::CHARM).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Boost(BoostInstruction {
                side_ref: SideReference::SideTwo,
                stat: PokemonBoostableStat::Attack,
                amount: -2,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_cannot_boost_lower_than_negative_6() {
        let mut state: State = State::default();
        state.side_two.attack_boost = -5;
        let mut choice = MOVES.get(&Choices::CHARM).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Boost(BoostInstruction {
                side_ref: SideReference::SideTwo,
                stat: PokemonBoostableStat::Attack,
                amount: -1,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_no_boost_when_already_at_minimum() {
        let mut state: State = State::default();
        state.side_two.attack_boost = -6;
        let mut choice = MOVES.get(&Choices::CHARM).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_clearbody_blocks_stat_lowering() {
        let mut state: State = State::default();
        state.side_two.get_active().ability = Abilities::CLEARBODY;
        let mut choice = MOVES.get(&Choices::CHARM).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_clearbody_does_not_block_self_stat_lowering() {
        let mut state: State = State::default();
        state.side_one.get_active().ability = Abilities::CLEARBODY;
        let mut choice = MOVES.get(&Choices::SHELLSMASH).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Attack,
                    amount: 2,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Defense,
                    amount: -1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::SpecialAttack,
                    amount: 2,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::SpecialDefense,
                    amount: -1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Speed,
                    amount: 2,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_defog_does_not_change_terrain_if_terrain_is_none() {
        let mut state: State = State::default();

        let mut choice = MOVES.get(&Choices::DEFOG).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Boost(BoostInstruction {
                // alpha-poke patch (L1): Defog lowers the target's evasion first
                side_ref: SideReference::SideTwo,
                stat: PokemonBoostableStat::Evasion,
                amount: -1,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_defog_clears_terrain() {
        let mut state: State = State::default();
        state.terrain.terrain_type = Terrain::ELECTRICTERRAIN;
        state.terrain.turns_remaining = 1;

        let mut choice = MOVES.get(&Choices::DEFOG).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Boost(BoostInstruction {
                    // alpha-poke patch (L1): Defog lowers the target's evasion first
                    side_ref: SideReference::SideTwo,
                    stat: PokemonBoostableStat::Evasion,
                    amount: -1,
                }),
                Instruction::ChangeTerrain(ChangeTerrain {
                    new_terrain: Terrain::NONE,
                    new_terrain_turns_remaining: 0,
                    previous_terrain: Terrain::ELECTRICTERRAIN,
                    previous_terrain_turns_remaining: 1,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_defog_clears_terrain_and_side_conditions() {
        let mut state: State = State::default();
        state.terrain.terrain_type = Terrain::ELECTRICTERRAIN;
        state.terrain.turns_remaining = 1;
        state.side_one.side_conditions.reflect = 1;
        state.side_two.side_conditions.reflect = 1;

        let mut choice = MOVES.get(&Choices::DEFOG).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Boost(BoostInstruction {
                    // alpha-poke patch (L1): Defog lowers the target's evasion first
                    side_ref: SideReference::SideTwo,
                    stat: PokemonBoostableStat::Evasion,
                    amount: -1,
                }),
                Instruction::ChangeTerrain(ChangeTerrain {
                    new_terrain: Terrain::NONE,
                    new_terrain_turns_remaining: 0,
                    previous_terrain: Terrain::ELECTRICTERRAIN,
                    previous_terrain_turns_remaining: 1,
                }),
                // alpha-poke patch (L91): only the target's screens (Showdown's defog onHit);
                // the user's Reflect stays
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::Reflect,
                    amount: -1,
                }),
            ],
        }];
        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_tidyup_clears_side_conditions_and_substitutes() {
        let mut state: State = State::default();
        state.terrain.terrain_type = Terrain::ELECTRICTERRAIN;
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::SUBSTITUTE);
        state
            .side_two
            .volatile_statuses
            .insert(PokemonVolatileStatus::SUBSTITUTE);
        state.side_one.substitute_health = 10;
        state.side_two.substitute_health = 25;
        state.terrain.turns_remaining = 1;
        state.side_one.side_conditions.spikes = 2;
        state.side_two.side_conditions.stealth_rock = 1;

        let mut choice = MOVES.get(&Choices::TIDYUP).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Spikes,
                    amount: -2,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::Stealthrock,
                    amount: -1,
                }),
                Instruction::ChangeSubstituteHealth(ChangeSubsituteHealthInstruction {
                    side_ref: SideReference::SideOne,
                    health_change: -10,
                }),
                Instruction::RemoveVolatileStatus(RemoveVolatileStatusInstruction {
                    side_ref: SideReference::SideOne,
                    volatile_status: PokemonVolatileStatus::SUBSTITUTE,
                }),
                Instruction::ChangeSubstituteHealth(ChangeSubsituteHealthInstruction {
                    side_ref: SideReference::SideTwo,
                    health_change: -25,
                }),
                Instruction::RemoveVolatileStatus(RemoveVolatileStatusInstruction {
                    side_ref: SideReference::SideTwo,
                    volatile_status: PokemonVolatileStatus::SUBSTITUTE,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Attack,
                    amount: 1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Speed,
                    amount: 1,
                }),
            ],
        }];
        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    #[cfg(any(feature = "gen8", feature = "gen9", feature = "champions"))]
    fn test_rapidspin_clears_hazards() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;

        let mut choice = MOVES.get(&Choices::RAPIDSPIN).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 61,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Stealthrock,
                    amount: -1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    amount: 1,
                    stat: PokemonBoostableStat::Speed,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_missing_rapidspin_does_not_clear_hazards() {
        let mut state: State = State::default();
        state.side_two.get_active().types = (PokemonType::GHOST, PokemonType::NORMAL);
        state.side_one.side_conditions.stealth_rock = 1;

        let mut choice = MOVES.get(&Choices::RAPIDSPIN).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];
        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_acid_into_steel_type() {
        let mut state: State = State::default();
        state.side_two.get_active().types = (PokemonType::STEEL, PokemonType::NORMAL);

        let mut choice = MOVES.get(&Choices::ACID).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        }];
        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    #[cfg(any(feature = "gen8", feature = "gen9", feature = "champions"))]
    fn test_rapidspin_clears_multiple_hazards() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;
        state.side_one.side_conditions.toxic_spikes = 2;
        state.side_one.side_conditions.spikes = 3;
        state.side_one.side_conditions.sticky_web = 1;

        let mut choice = MOVES.get(&Choices::RAPIDSPIN).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 61,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Stealthrock,
                    amount: -1,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Spikes,
                    amount: -3,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::ToxicSpikes,
                    amount: -2,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::StickyWeb,
                    amount: -1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    amount: 1,
                    stat: PokemonBoostableStat::Speed,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    #[cfg(any(feature = "gen8", feature = "gen9", feature = "champions"))]
    fn test_rapidspin_does_not_clear_opponent_hazards() {
        let mut state: State = State::default();
        state.side_two.side_conditions.stealth_rock = 1;
        state.side_two.side_conditions.toxic_spikes = 2;
        state.side_two.side_conditions.spikes = 3;
        state.side_two.side_conditions.sticky_web = 1;

        let mut choice = MOVES.get(&Choices::RAPIDSPIN).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 61,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    amount: 1,
                    stat: PokemonBoostableStat::Speed,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_courtchange_basic_swap() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;

        let mut choice = MOVES.get(&Choices::COURTCHANGE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Stealthrock,
                    amount: -1,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::Stealthrock,
                    amount: 1,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_courtchange_complicated_swap() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;
        state.side_two.side_conditions.toxic_spikes = 2;
        state.side_two.side_conditions.spikes = 3;
        state.side_two.side_conditions.sticky_web = 1;

        let mut choice = MOVES.get(&Choices::COURTCHANGE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Stealthrock,
                    amount: -1,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::Stealthrock,
                    amount: 1,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::Spikes,
                    amount: -3,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Spikes,
                    amount: 3,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::ToxicSpikes,
                    amount: -2,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::ToxicSpikes,
                    amount: 2,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideTwo,
                    side_condition: PokemonSideCondition::StickyWeb,
                    amount: -1,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::StickyWeb,
                    amount: 1,
                }),
            ],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_stoneaxe_does_not_set_stealthrock_if_already_set() {
        let mut state: State = State::default();
        state.side_two.side_conditions.stealth_rock = 1;
        let mut choice = MOVES.get(&Choices::STONEAXE).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions = vec![
            StateInstructions {
                percentage: 10.000002,
                instruction_list: vec![],
            },
            StateInstructions {
                percentage: 90.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 51,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_flinched_pokemon_cannot_move() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::FLINCH);

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );
        assert_eq!(instructions, vec![StateInstructions::default()])
    }

    #[test]
    fn test_dead_pokemon_moving_second_does_nothing() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        choice.first_move = false;
        state.side_one.get_active().hp = 0;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );
        assert_eq!(instructions, vec![StateInstructions::default()])
    }

    #[test]
    fn test_cannot_ohko_versus_study() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::EARTHQUAKE).unwrap().to_owned();
        state.side_two.get_active().ability = Abilities::STURDY;
        state.side_two.get_active().hp = 50;
        state.side_two.get_active().maxhp = 50;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 49,
            })],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_cannot_ohko_versus_sash() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::EARTHQUAKE).unwrap().to_owned();
        state.side_two.get_active().item = Items::FOCUSSASH;
        state.side_two.get_active().hp = 50;
        state.side_two.get_active().maxhp = 50;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        // alpha-poke patch (2026-10-16, L17): the sash is used up
        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: SideReference::SideTwo,
                    current_item: Items::FOCUSSASH,
                    new_item: Items::NONE,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 49,
                }),
            ],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_sturdy_does_not_affect_non_ohko_move() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::EARTHQUAKE).unwrap().to_owned();
        state.side_two.get_active().ability = Abilities::STURDY;
        state.side_two.get_active().hp = 45;
        state.side_two.get_active().maxhp = 50;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 45,
            })],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_beastboost_boosts_on_kill() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().ability = Abilities::BEASTBOOST;
        state.side_one.get_active().attack = 500; // highest stat
        state.side_two.get_active().hp = 1;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Attack,
                    amount: 1,
                }),
            ],
        };
        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_beastboost_boosts_different_stat_on_kill() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().ability = Abilities::BEASTBOOST;
        state.side_one.get_active().defense = 500; // highest stat
        state.side_two.get_active().hp = 1;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Defense,
                    amount: 1,
                }),
            ],
        };
        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_beastboost_does_not_overboost() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().ability = Abilities::BEASTBOOST;
        state.side_one.get_active().attack = 500; // highest stat
        state.side_one.attack_boost = 6; // max boosts already
        state.side_two.get_active().hp = 1;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 1,
            })],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_beastboost_does_not_boost_without_kill() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().ability = Abilities::BEASTBOOST;
        state.side_one.get_active().attack = 150; // highest stat
        state.side_two.get_active().hp = 100;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 72,
            })],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_drain_move_heals() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::ABSORB).unwrap().to_owned();
        state.side_one.get_active().hp = 100;
        state.side_one.get_active().maxhp = 200;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 16,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 8,
                }),
            ],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_drain_move_does_not_overheal() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::ABSORB).unwrap().to_owned();
        state.side_one.get_active().hp = 100;
        state.side_one.get_active().maxhp = 105;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 16,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 5,
                }),
            ],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_recoil_damage() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::BRAVEBIRD).unwrap().to_owned();
        state.side_one.get_active().hp = 105;
        state.side_one.get_active().maxhp = 105;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 94,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 31,
                }),
            ],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_recoil_cannot_overkill() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::BRAVEBIRD).unwrap().to_owned();
        state.side_one.get_active().hp = 5;
        state.side_one.get_active().maxhp = 105;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 94,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 5,
                }),
            ],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_drain_and_recoil_together() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::ABSORB).unwrap().to_owned();
        choice.recoil = Some(0.33);
        state.side_one.get_active().hp = 1;
        state.side_one.get_active().maxhp = 105;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 16,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 8,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 5,
                }),
            ],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_crash_move_missing() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::JUMPKICK).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: Vec<StateInstructions> = vec![
            StateInstructions {
                percentage: 5.000001,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 50,
                })],
            },
            StateInstructions {
                percentage: 95.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 100,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_crash_move_missing_versus_ghost_type() {
        let mut state: State = State::default();
        state.side_two.get_active().types.0 = PokemonType::GHOST;
        let mut choice = MOVES.get(&Choices::JUMPKICK).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: Vec<StateInstructions> = vec![StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 50,
            })],
        }];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    fn test_crash_move_missing_cannot_overkill() {
        let mut state: State = State::default();
        state.get_side(&SideReference::SideOne).get_active().hp = 5;
        let mut choice = MOVES.get(&Choices::JUMPKICK).unwrap().to_owned();

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: Vec<StateInstructions> = vec![
            StateInstructions {
                percentage: 5.000001,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 5,
                })],
            },
            StateInstructions {
                percentage: 95.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 100,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions)
    }

    #[test]
    #[cfg(any(feature = "gen9", feature = "champions"))]
    fn test_knockoff_removing_item() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::KNOCKOFF).unwrap().to_owned();
        state.get_side(&SideReference::SideTwo).get_active().item = Items::HEAVYDUTYBOOTS;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 76,
                }),
                Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: SideReference::SideTwo,
                    current_item: Items::HEAVYDUTYBOOTS,
                    new_item: Items::NONE,
                }),
            ],
        };

        assert_eq!(instructions, vec![expected_instructions])
    }

    #[test]
    fn test_blunderpolicy_boost() {
        let mut state: State = State::default();
        let mut choice = MOVES.get(&Choices::CROSSCHOP).unwrap().to_owned();
        state.get_side(&SideReference::SideOne).get_active().item = Items::BLUNDERPOLICY;

        let mut instructions = vec![];
        generate_instructions_from_move(
            &mut state,
            &mut choice,
            &MOVES.get(&Choices::TACKLE).unwrap(),
            SideReference::SideOne,
            StateInstructions::default(),
            &mut instructions,
            false,
        );

        let expected_instructions: Vec<StateInstructions> = vec![
            StateInstructions {
                percentage: 19.999998,
                instruction_list: vec![
                    Instruction::Boost(BoostInstruction {
                        side_ref: SideReference::SideOne,
                        stat: PokemonBoostableStat::Speed,
                        amount: 2,
                    }),
                    Instruction::ChangeItem(ChangeItemInstruction {
                        side_ref: SideReference::SideOne,
                        current_item: Items::BLUNDERPOLICY,
                        new_item: Items::NONE,
                    }),
                ],
            },
            StateInstructions {
                percentage: 80.0,
                instruction_list: vec![Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 100,
                })],
            },
        ];

        assert_eq!(instructions, expected_instructions);
    }

    #[test]
    fn test_basic_switch_functionality_with_no_prior_instructions() {
        let mut state: State = State::default();
        let mut choice = Choice {
            ..Default::default()
        };

        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_basic_switch_with_volatile_statuses() {
        let mut state: State = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::LEECHSEED);
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::RemoveVolatileStatus(RemoveVolatileStatusInstruction {
                    side_ref: SideReference::SideOne,
                    volatile_status: PokemonVolatileStatus::LEECHSEED,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_basic_switch_with_toxic_count() {
        let mut state: State = State::default();
        state.side_one.side_conditions.toxic_count = 2;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::ToxicCount,
                    amount: -2,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_basic_switch_with_boost() {
        let mut state: State = State::default();
        state.side_one.attack_boost = 2;
        state.side_one.speed_boost = 5;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Attack,
                    amount: -2,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Speed,
                    amount: -5,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_basic_switch_with_disabled_move() {
        let mut state: State = State::default();
        state.side_one.get_active().moves.m0 = Move {
            id: Choices::NONE,
            disabled: true,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().moves.m1 = Move {
            id: Choices::NONE,
            disabled: false,
            pp: 32,
            ..Default::default()
        };

        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: SideReference::SideOne,
                    move_index: PokemonMoveIndex::M0,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_basic_switch_with_multiple_disabled_moves() {
        let mut state: State = State::default();
        state.side_one.get_active().moves.m0 = Move {
            id: Choices::NONE,
            disabled: true,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().moves.m1 = Move {
            id: Choices::NONE,
            disabled: true,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().moves.m2 = Move {
            id: Choices::NONE,
            disabled: false,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().moves.m3 = Move {
            id: Choices::NONE,
            disabled: true,
            pp: 32,
            ..Default::default()
        };
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: SideReference::SideOne,
                    move_index: PokemonMoveIndex::M0,
                }),
                Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: SideReference::SideOne,
                    move_index: PokemonMoveIndex::M1,
                }),
                Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: SideReference::SideOne,
                    move_index: PokemonMoveIndex::M3,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_basic_switch_functionality_with_a_prior_instruction() {
        let mut state: State = State::default();
        let mut incoming_instructions = StateInstructions::default();
        let mut choice = Choice {
            ..Default::default()
        };

        choice.switch_id = PokemonIndex::P1;
        incoming_instructions
            .instruction_list
            .push(Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 1,
            }));

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 1,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switch_with_regenerator() {
        let mut state: State = State::default();
        state.side_one.get_active().hp -= 10;
        state.side_one.get_active().ability = Abilities::REGENERATOR;
        state.side_one.get_active().base_ability = Abilities::REGENERATOR;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 10,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switch_with_regenerator_plus_move_enabling() {
        let mut state: State = State::default();
        state.side_one.get_active().moves.m0 = Move {
            id: Choices::NONE,
            disabled: true,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().moves.m1 = Move {
            id: Choices::NONE,
            disabled: true,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().moves.m2 = Move {
            id: Choices::NONE,
            disabled: false,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().moves.m3 = Move {
            id: Choices::NONE,
            disabled: true,
            pp: 32,
            ..Default::default()
        };
        state.side_one.get_active().hp -= 10;
        state.side_one.get_active().ability = Abilities::REGENERATOR;
        state.side_one.get_active().base_ability = Abilities::REGENERATOR;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: SideReference::SideOne,
                    move_index: PokemonMoveIndex::M0,
                }),
                Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: SideReference::SideOne,
                    move_index: PokemonMoveIndex::M1,
                }),
                Instruction::EnableMove(EnableMoveInstruction {
                    side_ref: SideReference::SideOne,
                    move_index: PokemonMoveIndex::M3,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 10,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switch_with_regenerator_but_no_damage_taken() {
        let mut state: State = State::default();
        state.side_one.get_active().ability = Abilities::REGENERATOR;
        state.side_one.get_active().base_ability = Abilities::REGENERATOR;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_fainted_pokemon_with_regenerator_does_not_heal() {
        let mut state: State = State::default();
        state.side_one.get_active().ability = Abilities::REGENERATOR;
        state.side_one.get_active().base_ability = Abilities::REGENERATOR;
        state.side_one.get_active().hp = 0;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_regenerator_only_heals_one_third() {
        let mut state: State = State::default();
        state.side_one.get_active().ability = Abilities::REGENERATOR;
        state.side_one.get_active().base_ability = Abilities::REGENERATOR;
        state.side_one.get_active().hp = 3;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 33,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_naturalcure() {
        let mut state: State = State::default();
        state.side_one.get_active().ability = Abilities::NATURALCURE;
        state.side_one.get_active().base_ability = Abilities::NATURALCURE;
        state.side_one.get_active().status = PokemonStatus::PARALYZE;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P0,
                    old_status: PokemonStatus::PARALYZE,
                    new_status: PokemonStatus::NONE,
                }),
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_naturalcure_with_no_status() {
        let mut state: State = State::default();
        state.side_one.get_active().ability = Abilities::NATURALCURE;
        state.side_one.get_active().base_ability = Abilities::NATURALCURE;
        state.side_one.get_active().status = PokemonStatus::NONE;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_stealthrock() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: state.side_one.get_active().hp / 8,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_resisted_stealthrock() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;
        state.side_one.pokemon[PokemonIndex::P1].types = (PokemonType::GROUND, PokemonType::NORMAL);
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: state.side_one.get_active().hp / 16,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_stealthrock_does_not_overkill() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;
        state.side_one.pokemon[PokemonIndex::P1].hp = 5;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 5,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_stickyweb() {
        let mut state: State = State::default();
        state.side_one.side_conditions.sticky_web = 1;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Speed,
                    amount: -1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_stickyweb_with_heavydutyboots() {
        let mut state: State = State::default();
        state.side_one.side_conditions.sticky_web = 1;
        state.side_one.pokemon[PokemonIndex::P1].item = Items::HEAVYDUTYBOOTS;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_stickyweb_with_contrary() {
        let mut state: State = State::default();
        state.side_one.side_conditions.sticky_web = 1;
        state.side_one.pokemon[PokemonIndex::P1].ability = Abilities::CONTRARY;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideOne,
                    stat: PokemonBoostableStat::Speed,
                    amount: 1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_single_layer_toxicspikes() {
        let mut state: State = State::default();
        state.side_one.side_conditions.toxic_spikes = 1;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P1,
                    old_status: PokemonStatus::NONE,
                    new_status: PokemonStatus::POISON,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_double_layer_toxicspikes() {
        let mut state: State = State::default();
        state.side_one.side_conditions.toxic_spikes = 2;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P1,
                    old_status: PokemonStatus::NONE,
                    new_status: PokemonStatus::TOXIC,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_double_layer_toxicspikes_as_flying_type() {
        let mut state: State = State::default();
        state.side_one.side_conditions.toxic_spikes = 2;
        state.side_one.pokemon[PokemonIndex::P1].types.0 = PokemonType::FLYING;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_double_layer_toxicspikes_as_poison_and_flying_type() {
        let mut state: State = State::default();
        state.side_one.side_conditions.toxic_spikes = 2;
        state.side_one.pokemon[PokemonIndex::P1].types.0 = PokemonType::FLYING;
        state.side_one.pokemon[PokemonIndex::P1].types.1 = PokemonType::POISON;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_in_with_intimidate() {
        let mut state: State = State::default();
        state.side_one.pokemon[PokemonIndex::P1].ability = Abilities::INTIMIDATE;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Boost(BoostInstruction {
                    side_ref: SideReference::SideTwo,
                    stat: PokemonBoostableStat::Attack,
                    amount: -1,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_in_with_intimidate_when_opponent_is_already_lowest_atk_boost() {
        let mut state: State = State::default();
        state.side_one.pokemon[PokemonIndex::P1].ability = Abilities::INTIMIDATE;
        state.side_two.attack_boost = -6;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_in_with_intimidate_versus_clearbody() {
        let mut state: State = State::default();
        state.side_one.pokemon[PokemonIndex::P1].ability = Abilities::INTIMIDATE;
        state.side_two.get_active().ability = Abilities::CLEARBODY;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Switch(SwitchInstruction {
                side_ref: SideReference::SideOne,
                previous_index: PokemonIndex::P0,
                next_index: PokemonIndex::P1,
            })],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_double_layer_toxicspikes_as_poison_type() {
        let mut state: State = State::default();
        state.side_one.pokemon[PokemonIndex::P1].types.0 = PokemonType::POISON;
        state.side_one.side_conditions.toxic_spikes = 2;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::ToxicSpikes,
                    amount: -2,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_stealthrock_and_spikes_does_not_overkill() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;
        state.side_one.side_conditions.spikes = 1;
        state.side_one.pokemon[PokemonIndex::P1].hp = 15;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 12,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 3,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_switching_into_stealthrock_and_multiple_layers_of_spikes_does_not_overkill() {
        let mut state: State = State::default();
        state.side_one.side_conditions.stealth_rock = 1;
        state.side_one.side_conditions.spikes = 3;
        state.side_one.pokemon[PokemonIndex::P1].hp = 25;
        let mut choice = Choice {
            ..Default::default()
        };
        choice.switch_id = PokemonIndex::P1;

        let expected_instructions: StateInstructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Switch(SwitchInstruction {
                    side_ref: SideReference::SideOne,
                    previous_index: PokemonIndex::P0,
                    next_index: PokemonIndex::P1,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 12,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 13,
                }),
            ],
            ..Default::default()
        };

        let mut incoming_instructions = StateInstructions::default();
        generate_instructions_from_switch(
            &mut state,
            choice.switch_id,
            SideReference::SideOne,
            &mut incoming_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_healthy_pokemon_with_no_prior_instructions() {
        let mut state = State::default();
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions::default();

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            &mut vec![],
        );

        assert_eq!(expected_instructions, incoming_instructions);
    }

    #[test]
    fn test_rest_turns_at_3_with_no_prior_instructions() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::SLEEP;
        state.side_one.get_active().rest_turns = 3;
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::DecrementRestTurns(
                DecrementRestTurnsInstruction {
                    side_ref: SideReference::SideOne,
                },
            )],
        };

        let expected_frozen_instructions: &mut Vec<StateInstructions> = &mut vec![];

        let frozen_instructions = &mut vec![];
        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_rest_turns_at_2_with_no_prior_instructions() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::SLEEP;
        state.side_one.get_active().rest_turns = 2;
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::DecrementRestTurns(
                DecrementRestTurnsInstruction {
                    side_ref: SideReference::SideOne,
                },
            )],
        };

        let expected_frozen_instructions: &mut Vec<StateInstructions> = &mut vec![];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_paralyzed_pokemon_with_no_prior_instructions() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::PARALYZE;
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: (1.0 - FULLY_PARALYZED_CHANCE) * 100.0,
            instruction_list: vec![],
        };

        let expected_frozen_instructions = &mut vec![StateInstructions {
            percentage: FULLY_PARALYZED_CHANCE * 100.0,
            instruction_list: vec![],
        }];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_confused_pokemon_with_no_prior_instructions() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::CONFUSION);
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: 100.0 * (1.0 - HIT_SELF_IN_CONFUSION_CHANCE),
            instruction_list: vec![Instruction::ChangeVolatileStatusDuration(
                ChangeVolatileStatusDurationInstruction {
                    side_ref: SideReference::SideOne,
                    volatile_status: PokemonVolatileStatus::CONFUSION,
                    amount: 1,
                },
            )],
        };

        let expected_frozen_instructions = &mut vec![StateInstructions {
            percentage: 100.0 * (HIT_SELF_IN_CONFUSION_CHANCE),
            instruction_list: vec![
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 31, // alpha-poke patch (L54): the 16 rolls' mean of 35, was 35
                }),
            ],
        }];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_confused_pokemon_with_prior_instruction() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::CONFUSION);
        let mut incoming_instructions = StateInstructions::default();
        incoming_instructions.instruction_list = vec![Instruction::Damage(DamageInstruction {
            side_ref: SideReference::SideOne,
            damage_amount: 1,
        })];

        let expected_instructions = StateInstructions {
            percentage: 100.0 * (1.0 - HIT_SELF_IN_CONFUSION_CHANCE),
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 1,
                }),
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ),
            ],
        };

        let expected_frozen_instructions = &mut vec![StateInstructions {
            percentage: 100.0 * HIT_SELF_IN_CONFUSION_CHANCE,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 1,
                }),
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 31, // alpha-poke patch (L54): the 16 rolls' mean of 35, was 35
                }),
            ],
        }];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_confused_pokemon_with_prior_instruction_does_not_overkill() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::CONFUSION);
        let mut incoming_instructions = StateInstructions::default();
        state.side_one.get_active().hp = 2;
        incoming_instructions.instruction_list = vec![Instruction::Damage(DamageInstruction {
            side_ref: SideReference::SideOne,
            damage_amount: 1,
        })];

        let expected_instructions = StateInstructions {
            percentage: 100.0 * (1.0 - HIT_SELF_IN_CONFUSION_CHANCE),
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 1,
                }),
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ),
            ],
        };

        let expected_frozen_instructions = &mut vec![StateInstructions {
            percentage: 100.0 * HIT_SELF_IN_CONFUSION_CHANCE,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 1,
                }),
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 2,
                }),
            ],
        }];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    // alpha-poke patch: confusion ends after 1-4 confused attempts
    fn test_confusion_after_two_confused_attempts_may_have_ended() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::CONFUSION);
        state.side_one.volatile_status_durations.confusion = 2;
        let mut incoming_instructions = StateInstructions::default();
        let self_hit = HIT_SELF_IN_CONFUSION_CHANCE * (1.0 - 1.0 / 3.0);
        let inc =
            Instruction::ChangeVolatileStatusDuration(ChangeVolatileStatusDurationInstruction {
                side_ref: SideReference::SideOne,
                volatile_status: PokemonVolatileStatus::CONFUSION,
                amount: 1,
            });
        let frozen_instructions = &mut vec![];
        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );
        assert_eq!(
            StateInstructions {
                percentage: 100.0 * (1.0 - self_hit),
                instruction_list: vec![inc.clone()],
            },
            incoming_instructions
        );
        assert_eq!(frozen_instructions.len(), 1);
        assert!((frozen_instructions[0].percentage - 100.0 * self_hit).abs() < 1e-3);
        assert_eq!(frozen_instructions[0].instruction_list[0], inc);
        assert_eq!(state.side_one.volatile_status_durations.confusion, 3);
    }

    #[test]
    fn test_confusion_ends_after_four_confused_attempts() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::CONFUSION);
        state.side_one.volatile_status_durations.confusion = 4;
        let mut incoming_instructions = StateInstructions::default();
        let frozen_instructions = &mut vec![];
        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );
        assert_eq!(
            StateInstructions {
                percentage: 100.0,
                instruction_list: vec![
                    Instruction::RemoveVolatileStatus(RemoveVolatileStatusInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                    }),
                    Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: SideReference::SideOne,
                            volatile_status: PokemonVolatileStatus::CONFUSION,
                            amount: -4,
                        }
                    ),
                ],
            },
            incoming_instructions
        );
        assert!(frozen_instructions.is_empty());
        assert!(!state
            .side_one
            .volatile_statuses
            .contains(&PokemonVolatileStatus::CONFUSION));
        assert_eq!(state.side_one.volatile_status_durations.confusion, 0);
    }

    #[test]
    fn test_frozen_pokemon_with_no_prior_instructions() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::FREEZE;
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: THAW_CHANCE * 100.0,
            instruction_list: vec![Instruction::ChangeStatus(ChangeStatusInstruction {
                side_ref: SideReference::SideOne,
                pokemon_index: state.side_one.active_index,
                old_status: PokemonStatus::FREEZE,
                new_status: PokemonStatus::NONE,
            })],
        };

        let expected_frozen_instructions = &mut vec![StateInstructions {
            percentage: (1.0 - THAW_CHANCE) * 100.0,
            instruction_list: vec![],
        }];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_asleep_pokemon_with_no_prior_instructions() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::SLEEP;
        state.side_one.get_active().sleep_turns = MAX_SLEEP_TURNS;
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: state.side_one.active_index,
                    old_status: PokemonStatus::SLEEP,
                    new_status: PokemonStatus::NONE,
                }),
                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P0,
                    new_turns: 0,
                    previous_turns: MAX_SLEEP_TURNS,
                }),
            ],
        };

        let expected_frozen_instructions: &mut Vec<StateInstructions> = &mut vec![];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_asleep_waking_up_and_confused() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::SLEEP;
        state.side_one.get_active().sleep_turns = MAX_SLEEP_TURNS;
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::CONFUSION);
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: 100.0 * (1.0 - HIT_SELF_IN_CONFUSION_CHANCE),
            instruction_list: vec![
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: state.side_one.active_index,
                    old_status: PokemonStatus::SLEEP,
                    new_status: PokemonStatus::NONE,
                }),
                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P0,
                    new_turns: 0,
                    previous_turns: MAX_SLEEP_TURNS,
                }),
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ),
            ],
        };

        let expected_frozen_instructions = &mut vec![StateInstructions {
            percentage: 100.0 * HIT_SELF_IN_CONFUSION_CHANCE,
            instruction_list: vec![
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: state.side_one.active_index,
                    old_status: PokemonStatus::SLEEP,
                    new_status: PokemonStatus::NONE,
                }),
                Instruction::SetSleepTurns(SetSleepTurnsInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: PokemonIndex::P0,
                    new_turns: 0,
                    previous_turns: MAX_SLEEP_TURNS,
                }),
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::CONFUSION,
                        amount: 1,
                    },
                ),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 31, // alpha-poke patch (L54): the 16 rolls' mean of 35, was 35
                }),
            ],
        }];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_asleep_pokemon_waking_up_with_1_rest_turn() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::SLEEP;
        state.side_one.get_active().rest_turns = 1;
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: state.side_one.active_index,
                    old_status: PokemonStatus::SLEEP,
                    new_status: PokemonStatus::NONE,
                }),
                Instruction::DecrementRestTurns(DecrementRestTurnsInstruction {
                    side_ref: SideReference::SideOne,
                }),
            ],
        };

        let expected_frozen_instructions: &mut Vec<StateInstructions> = &mut vec![];
        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_asleep_pokemon_staying_asleep_with_two_rest_turns() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::SLEEP;
        state.side_one.get_active().rest_turns = 1;
        let mut incoming_instructions = StateInstructions::default();

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: SideReference::SideOne,
                    pokemon_index: state.side_one.active_index,
                    old_status: PokemonStatus::SLEEP,
                    new_status: PokemonStatus::NONE,
                }),
                Instruction::DecrementRestTurns(DecrementRestTurnsInstruction {
                    side_ref: SideReference::SideOne,
                }),
            ],
        };

        let expected_frozen_instructions: &mut Vec<StateInstructions> = &mut vec![];
        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_paralyzed_pokemon_preserves_prior_instructions() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::PARALYZE;
        let mut incoming_instructions = StateInstructions::default();
        incoming_instructions.instruction_list = vec![Instruction::Damage(DamageInstruction {
            side_ref: SideReference::SideOne,
            damage_amount: 1,
        })];

        let expected_instructions = StateInstructions {
            percentage: (1.0 - FULLY_PARALYZED_CHANCE) * 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 1,
            })],
        };

        let expected_frozen_instructions = &mut vec![StateInstructions {
            percentage: FULLY_PARALYZED_CHANCE * 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 1,
            })],
        }];

        let frozen_instructions = &mut vec![];

        generate_instructions_from_existing_status_conditions(
            &mut state,
            &SideReference::SideOne,
            &Choice::default(),
            &mut incoming_instructions,
            frozen_instructions,
        );

        assert_eq!(expected_instructions, incoming_instructions);
        assert_eq!(expected_frozen_instructions, frozen_instructions);
    }

    #[test]
    fn test_basic_side_two_moves_first() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;

        assert_eq!(
            SideMovesFirst::SideTwo,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_custap_berry_when_less_than_25_percent_activates() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().item = Items::CUSTAPBERRY;
        state.side_one.get_active().hp = 24;
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_quarkdrivespe_boost_works() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::QUARKDRIVESPE);
        state.side_one.get_active().hp = 24;
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_protosynthesisspe_boost_works() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::PROTOSYNTHESISSPE);
        state.side_one.get_active().hp = 24;
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_custap_berry_when_greater_than_25_percent_does_not_activate() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().item = Items::CUSTAPBERRY;
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;

        assert_eq!(
            SideMovesFirst::SideTwo,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_custap_berry_does_not_matter_when_opponent_uses_increased_priority_move() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::QUICKATTACK).unwrap().to_owned();
        state.side_one.get_active().item = Items::CUSTAPBERRY;
        state.side_one.get_active().hp = 24;
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;

        assert_eq!(
            SideMovesFirst::SideTwo,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_slowstart_halves_effective_speed() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;
        state
            .side_two
            .volatile_statuses
            .insert(PokemonVolatileStatus::SLOWSTART);

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_basic_side_one_moves_first() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().speed = 101;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_paralysis_reduces_effective_speed() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();

        state.side_one.get_active().status = PokemonStatus::PARALYZE;
        state.side_one.get_active().speed = 101;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SideTwo,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    #[cfg(any(
        feature = "gen7",
        feature = "gen8",
        feature = "gen9",
        feature = "champions"
    ))]
    fn test_later_gen_speed_cutting_in_half() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::PARALYZE;
        state.side_one.get_active().speed = 100;

        assert_eq!(50, get_effective_speed(&state, &SideReference::SideOne))
    }

    #[test]
    #[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
    fn test_earlier_gen_speed_cutting_by_75_percent() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::PARALYZE;
        state.side_one.get_active().speed = 100;

        assert_eq!(25, get_effective_speed(&state, &SideReference::SideOne))
    }

    #[test]
    fn test_choicescarf_multiplying_speed() {
        let mut state = State::default();
        state.side_one.get_active().speed = 100;
        state.side_one.get_active().item = Items::CHOICESCARF;

        assert_eq!(150, get_effective_speed(&state, &SideReference::SideOne))
    }

    #[test]
    fn test_iron_ball_halving_speed() {
        let mut state = State::default();
        state.side_one.get_active().speed = 100;
        state.side_one.get_active().item = Items::IRONBALL;

        assert_eq!(50, get_effective_speed(&state, &SideReference::SideOne))
    }

    #[test]
    fn test_speed_tie_goes_to_side_two() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SpeedTie,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_higher_priority_ignores_speed_diff() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::QUICKATTACK).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        state.side_one.get_active().speed = 100;
        state.side_two.get_active().speed = 101;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_side_two_higher_priority_ignores_speed_diff() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::TACKLE).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::QUICKATTACK).unwrap().to_owned();
        state.side_one.get_active().speed = 101;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SideTwo,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_both_higher_priority_defaults_back_to_speed() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::QUICKATTACK).unwrap().to_owned();
        let side_two_choice = MOVES.get(&Choices::QUICKATTACK).unwrap().to_owned();
        state.side_one.get_active().speed = 101;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_switch_always_goes_first() {
        let mut state = State::default();
        let mut side_one_choice = MOVES.get(&Choices::SPLASH).unwrap().to_owned();
        side_one_choice.category = MoveCategory::Switch;
        let side_two_choice = MOVES.get(&Choices::QUICKATTACK).unwrap().to_owned();
        state.side_one.get_active().speed = 99;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_double_switch_checks_higher_speed() {
        let mut state = State::default();
        let mut side_one_choice = MOVES.get(&Choices::SPLASH).unwrap().to_owned();
        side_one_choice.category = MoveCategory::Switch;
        let mut side_two_choice = MOVES.get(&Choices::SPLASH).unwrap().to_owned();
        side_two_choice.category = MoveCategory::Switch;

        state.side_one.get_active().speed = 99;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SideTwo,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_pursuit_goes_before_switch() {
        let mut state = State::default();
        let side_one_choice = MOVES.get(&Choices::PURSUIT).unwrap().to_owned();
        let mut side_two_choice = MOVES.get(&Choices::SPLASH).unwrap().to_owned();
        side_two_choice.category = MoveCategory::Switch;

        state.side_one.get_active().speed = 50;
        state.side_two.get_active().speed = 100;

        assert_eq!(
            SideMovesFirst::SideOne,
            moves_first(
                &state,
                &side_one_choice,
                &side_two_choice,
                &mut StateInstructions::default()
            )
        )
    }

    #[test]
    fn test_end_of_turn_hail_damage() {
        let mut state = State::default();
        state.weather.weather_type = Weather::HAIL;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 6,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 6,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_end_of_turn_hail_damage_against_ice_type() {
        let mut state = State::default();
        state.weather.weather_type = Weather::HAIL;
        state.side_two.get_active().types.0 = PokemonType::ICE;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                // no damage to side_two
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 6,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_end_of_turn_sand_damage() {
        let mut state = State::default();
        state.weather.weather_type = Weather::SAND;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 6,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 6,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_end_of_turn_sand_damage_against_ground_type() {
        let mut state = State::default();
        state.weather.weather_type = Weather::SAND;
        state.side_two.get_active().types.0 = PokemonType::GROUND;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,

            // no damage to side_two
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 6,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_hail_does_not_overkill() {
        let mut state = State::default();
        state.weather.weather_type = Weather::HAIL;
        state.side_one.get_active().hp = 3;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 3,
                }),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount: 6,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_fainted_pkmn_does_not_take_hail_dmg() {
        let mut state = State::default();
        state.weather.weather_type = Weather::HAIL;
        state.side_one.get_active().hp = 0;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideTwo,
                damage_amount: 6,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    #[cfg(not(feature = "gen4"))]
    fn test_wished_pokemon_gets_healed() {
        let mut state = State::default();
        state.side_one.wish = (1, 5);
        state.side_one.get_active().hp = 50;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 5,
                }),
                Instruction::DecrementWish(DecrementWishInstruction {
                    side_ref: SideReference::SideOne,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_wish_does_not_overheal() {
        let mut state = State::default();
        state.side_one.wish = (1, 50);
        state.side_one.get_active().hp = 95;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 5,
                }),
                Instruction::DecrementWish(DecrementWishInstruction {
                    side_ref: SideReference::SideOne,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_wish_does_nothing_when_maxhp() {
        let mut state = State::default();
        state.side_one.wish = (1, 50);
        state.side_one.get_active().hp = 100;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::DecrementWish(DecrementWishInstruction {
                side_ref: SideReference::SideOne,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_wish_does_nothing_when_fainted() {
        let mut state = State::default();
        state.side_one.wish = (1, 50);
        state.side_one.get_active().hp = 0;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::DecrementWish(DecrementWishInstruction {
                side_ref: SideReference::SideOne,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_wish_at_2_does_not_heal() {
        let mut state = State::default();
        state.side_one.wish = (2, 50);
        state.side_one.get_active().hp = 95;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::DecrementWish(DecrementWishInstruction {
                side_ref: SideReference::SideOne,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leftovers_heals_at_end_of_turn() {
        let mut state = State::default();
        state.side_one.get_active().hp = 50;
        state.side_one.get_active().item = Items::LEFTOVERS;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 6,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leftovers_does_not_overheal() {
        let mut state = State::default();
        state.side_one.get_active().hp = 99;
        state.side_one.get_active().item = Items::LEFTOVERS;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 1,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leftovers_generates_no_instruction_at_maxhp() {
        let mut state = State::default();
        state.side_one.get_active().hp = 100;
        state.side_one.get_active().item = Items::LEFTOVERS;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leftovers_generates_no_instruction_when_fainted() {
        let mut state = State::default();
        state.side_one.get_active().hp = 0;
        state.side_one.get_active().item = Items::LEFTOVERS;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_blacksludge_heal_as_poison_type() {
        let mut state = State::default();
        state.side_one.get_active().hp = 50;
        state.side_one.get_active().item = Items::BLACKSLUDGE;
        state.side_one.get_active().types.0 = PokemonType::POISON;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 6,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_blacksludge_damage_as_non_poison_type() {
        let mut state = State::default();
        state.side_one.get_active().hp = 50;
        state.side_one.get_active().item = Items::BLACKSLUDGE;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 12, // alpha-poke patch (L9): 1/8 (was 1/16)
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_blacksludge_does_not_overheal() {
        let mut state = State::default();
        state.side_one.get_active().hp = 99;
        state.side_one.get_active().item = Items::BLACKSLUDGE;
        state.side_one.get_active().types.0 = PokemonType::POISON;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 1,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_flameorb_end_of_turn_burn() {
        let mut state = State::default();
        state.side_one.get_active().item = Items::FLAMEORB;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ChangeStatus(ChangeStatusInstruction {
                side_ref: SideReference::SideOne,
                pokemon_index: PokemonIndex::P0,
                old_status: PokemonStatus::NONE,
                new_status: PokemonStatus::BURN,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_fire_type_cannot_be_burned_by_flameorb() {
        let mut state = State::default();
        state.side_one.get_active().item = Items::FLAMEORB;
        state.side_one.get_active().types.0 = PokemonType::FIRE;
        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_toxicorb_applies_status() {
        let mut state = State::default();
        state.side_one.get_active().item = Items::TOXICORB;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ChangeStatus(ChangeStatusInstruction {
                side_ref: SideReference::SideOne,
                pokemon_index: PokemonIndex::P0,
                old_status: PokemonStatus::NONE,
                new_status: PokemonStatus::TOXIC,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_toxicorb_does_not_apply_to_poison_type() {
        let mut state = State::default();
        state.side_one.get_active().item = Items::TOXICORB;
        state.side_one.get_active().types.0 = PokemonType::POISON;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_poisonheal_heals_at_end_of_turn() {
        let mut state = State::default();
        state.side_one.get_active().ability = Abilities::POISONHEAL;
        state.side_one.get_active().status = PokemonStatus::POISON;
        state.side_one.get_active().hp = 50;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 12,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_poisonheal_while_toxiced_still_increases_toxic_count() {
        let mut state = State::default();
        state.side_one.get_active().ability = Abilities::POISONHEAL;
        state.side_one.get_active().status = PokemonStatus::TOXIC;
        state.side_one.get_active().hp = 50;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            // alpha-poke patch (2026-10-16, L12b): the heal comes with the status damage now
            instruction_list: vec![
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideOne,
                    heal_amount: 12,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::ToxicCount,
                    amount: 1,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_poisonheal_does_not_overheal() {
        let mut state = State::default();
        state.side_one.get_active().ability = Abilities::POISONHEAL;
        state.side_one.get_active().status = PokemonStatus::POISON;
        state.side_one.get_active().hp = 99;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Heal(HealInstruction {
                side_ref: SideReference::SideOne,
                heal_amount: 1,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_poisonheal_does_nothing_at_maxhp() {
        let mut state = State::default();
        state.side_one.get_active().ability = Abilities::POISONHEAL;
        state.side_one.get_active().status = PokemonStatus::POISON;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_speedboost() {
        let mut state = State::default();
        state.side_one.get_active().ability = Abilities::SPEEDBOOST;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Boost(BoostInstruction {
                side_ref: SideReference::SideOne,
                stat: PokemonBoostableStat::Speed,
                amount: 1,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_speedboost_does_not_boost_beyond_6() {
        let mut state = State::default();
        state.side_one.get_active().ability = Abilities::SPEEDBOOST;
        state.side_one.speed_boost = 6;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_end_of_turn_poison_damage() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::POISON;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 12,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_poison_damage_does_not_overkill() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::POISON;
        state.side_one.get_active().hp = 5;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 5,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    #[cfg(any(
        feature = "gen9",
        feature = "gen8",
        feature = "gen7",
        feature = "champions"
    ))]
    fn test_end_of_turn_burn_damage() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::BURN;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 6,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    #[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
    fn test_early_generation_burn_one_eigth() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::BURN;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 12,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_burn_damage_does_not_overkill() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::BURN;
        state.side_one.get_active().hp = 5;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 5,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_burn_damage_ignored_if_has_magicguard() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::BURN;
        state.side_one.get_active().ability = Abilities::MAGICGUARD;
        state.side_one.get_active().hp = 5;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_first_toxic_damage() {
        let mut state = State::default();
        state.side_one.get_active().status = PokemonStatus::TOXIC;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 6,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::ToxicCount,
                    amount: 1,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leechseed_sap() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::LEECHSEED);
        state.side_one.get_active().hp = 50;
        state.side_two.get_active().hp = 50;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 12,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideTwo,
                    heal_amount: 12,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leechseed_sap_does_not_heal_if_receiving_side_is_maxhp() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::LEECHSEED);
        state.side_one.get_active().hp = 50;
        state.side_two.get_active().hp = 100;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 12,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leechseed_sap_does_not_overkill() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::LEECHSEED);
        state.side_one.get_active().hp = 5;
        state.side_two.get_active().hp = 50;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 5,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideTwo,
                    heal_amount: 5,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_leechseed_sap_does_not_overheal() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::LEECHSEED);
        state.side_one.get_active().hp = 50;
        state.side_two.get_active().hp = 95;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 12,
                }),
                Instruction::Heal(HealInstruction {
                    side_ref: SideReference::SideTwo,
                    heal_amount: 5,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_protect_volatile_being_removed() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::PROTECT);

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::RemoveVolatileStatus(RemoveVolatileStatusInstruction {
                    side_ref: SideReference::SideOne,
                    volatile_status: PokemonVolatileStatus::PROTECT,
                }),
                Instruction::ChangeSideCondition(ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Protect,
                    amount: 1,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_protect_side_condition_being_removed() {
        let mut state = State::default();
        state.side_one.side_conditions.protect = 2;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::ChangeSideCondition(
                ChangeSideConditionInstruction {
                    side_ref: SideReference::SideOne,
                    side_condition: PokemonSideCondition::Protect,
                    amount: -2,
                },
            )],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_roost_vs_removal() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::ROOST);

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: SideReference::SideOne,
                    volatile_status: PokemonVolatileStatus::ROOST,
                },
            )],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_partiallytrapped_damage() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::PARTIALLYTRAPPED);

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        #[cfg(any(feature = "gen4", feature = "gen5"))]
        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: 6,
            })],
        };

        #[cfg(any(
            feature = "gen6",
            feature = "gen7",
            feature = "gen8",
            feature = "gen9",
            feature = "champions"
        ))]
        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                // alpha-poke patch (2026-10-16): the trap's end-of-turn count
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::PARTIALLYTRAPPED,
                        amount: 1,
                    },
                ),
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideOne,
                    damage_amount: 12,
                }),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    // alpha-poke patch (2026-10-16): the trap ends at its fifth end of turn, without damage
    #[test]
    fn test_partiallytrapped_ends_at_the_fifth_end_of_turn() {
        let mut state = State::default();
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::PARTIALLYTRAPPED);
        state.side_one.volatile_status_durations.partiallytrapped = 4;

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![
                Instruction::RemoveVolatileStatus(RemoveVolatileStatusInstruction {
                    side_ref: SideReference::SideOne,
                    volatile_status: PokemonVolatileStatus::PARTIALLYTRAPPED,
                }),
                Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: SideReference::SideOne,
                        volatile_status: PokemonVolatileStatus::PARTIALLYTRAPPED,
                        amount: -4,
                    },
                ),
            ],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_saltcure_on_water_type_damage() {
        let mut state = State::default();
        state.side_one.get_active().types.0 = PokemonType::WATER;
        state
            .side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::SALTCURE);

        let mut incoming_instructions = StateInstructions::default();
        add_end_of_turn_instructions(
            &mut state,
            &mut incoming_instructions,
            &SideReference::SideOne,
        );

        let expected_damage = (2.0 * (100.0 / SALT_CURE_DAMAGE_DIVISOR)) as i16;
        let expected_instructions = StateInstructions {
            percentage: 100.0,
            instruction_list: vec![Instruction::Damage(DamageInstruction {
                side_ref: SideReference::SideOne,
                damage_amount: expected_damage,
            })],
        };

        assert_eq!(expected_instructions, incoming_instructions)
    }

    #[test]
    fn test_chance_to_wake_up_with_no_turns_asleep_is_0() {
        assert_eq!(0.0, chance_to_wake_up(0));
    }

    #[test]
    #[cfg(any(feature = "gen4"))]
    fn test_gen4_25_percent_to_wake_after_1_sleep_turn() {
        assert_eq!(0.25, chance_to_wake_up(1));
    }

    #[test]
    #[cfg(any(feature = "gen4"))]
    fn test_gen4_100_percent_to_wake_after_4_sleep_turn() {
        assert_eq!(1.0, chance_to_wake_up(4));
    }
}
