use super::abilities::Abilities;
use super::items::Items;
use super::state::{PokemonVolatileStatus, Terrain, Weather};
use crate::choices::Choices;
use crate::choices::{Choice, MoveCategory};
use crate::state::{
    Pokemon, PokemonBoostableStat, PokemonIndex, PokemonStatus, PokemonType, Side, SideReference,
    State,
};

#[rustfmt::skip]
#[cfg(any(feature = "champions", feature = "gen9",feature = "gen8",feature = "gen7",feature = "gen6"))]
const TYPE_MATCHUP_DAMAGE_MULTIPICATION: [[f32; 19]; 19] = [
/*         0    1    2    3    4    5    6    7    8    9   10   11   12   13   14   15   16   17   18  */
/*  0 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.0, 1.0, 1.0, 0.5, 1.0, 1.0],
/*  1 */ [1.0, 0.5, 0.5, 1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 0.5, 1.0, 2.0, 1.0, 1.0],
/*  2 */ [1.0, 2.0, 0.5, 1.0, 0.5, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0],
/*  3 */ [1.0, 1.0, 2.0, 0.5, 0.5, 1.0, 1.0, 1.0, 0.0, 2.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0],
/*  4 */ [1.0, 0.5, 2.0, 1.0, 0.5, 1.0, 1.0, 0.5, 2.0, 0.5, 1.0, 0.5, 2.0, 1.0, 0.5, 1.0, 0.5, 1.0, 1.0],
/*  5 */ [1.0, 0.5, 0.5, 1.0, 2.0, 0.5, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 1.0],
/*  6 */ [2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 0.5, 0.5, 0.5, 2.0, 0.0, 1.0, 2.0, 2.0, 0.5, 1.0],
/*  7 */ [1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 0.0, 2.0, 1.0],
/*  8 */ [1.0, 2.0, 1.0, 2.0, 0.5, 1.0, 1.0, 2.0, 1.0, 0.0, 1.0, 0.5, 2.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0],
/*  9 */ [1.0, 1.0, 1.0, 0.5, 2.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0],
/* 10 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0, 0.0, 0.5, 1.0, 1.0],
/* 11 */ [1.0, 0.5, 1.0, 1.0, 2.0, 1.0, 0.5, 0.5, 1.0, 0.5, 2.0, 1.0, 1.0, 0.5, 1.0, 2.0, 0.5, 0.5, 1.0],
/* 12 */ [1.0, 2.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 0.5, 2.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0],
/* 13 */ [0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 1.0, 1.0],
/* 14 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 0.0, 1.0],
/* 15 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 0.5, 1.0],
/* 16 */ [1.0, 0.5, 0.5, 0.5, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 0.5, 2.0, 1.0],
/* 17 */ [1.0, 0.5, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 0.5, 1.0, 1.0],
/* 18 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
];

#[rustfmt::skip]
#[cfg(any(feature = "gen5",feature = "gen4"))]
const TYPE_MATCHUP_DAMAGE_MULTIPICATION: [[f32; 19]; 19] = [
/*         0    1    2    3    4    5    6    7    8    9   10   11   12   13   14   15   16   17   18  */
/*  0 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.0, 1.0, 1.0, 0.5, 1.0, 1.0],
/*  1 */ [1.0, 0.5, 0.5, 1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 0.5, 1.0, 2.0, 1.0, 1.0],
/*  2 */ [1.0, 2.0, 0.5, 1.0, 0.5, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0],
/*  3 */ [1.0, 1.0, 2.0, 0.5, 0.5, 1.0, 1.0, 1.0, 0.0, 2.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0],
/*  4 */ [1.0, 0.5, 2.0, 1.0, 0.5, 1.0, 1.0, 0.5, 2.0, 0.5, 1.0, 0.5, 2.0, 1.0, 0.5, 1.0, 0.5, 1.0, 1.0],
/*  5 */ [1.0, 0.5, 0.5, 1.0, 2.0, 0.5, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 1.0],
/*  6 */ [2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 0.5, 0.5, 0.5, 2.0, 0.0, 1.0, 2.0, 2.0, 0.5, 1.0],
/*  7 */ [1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 0.0, 2.0, 1.0],
/*  8 */ [1.0, 2.0, 1.0, 2.0, 0.5, 1.0, 1.0, 2.0, 1.0, 0.0, 1.0, 0.5, 2.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0],
/*  9 */ [1.0, 1.0, 1.0, 0.5, 2.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0],
/* 10 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0, 0.0, 0.5, 1.0, 1.0],
/* 11 */ [1.0, 0.5, 1.0, 1.0, 2.0, 1.0, 0.5, 0.5, 1.0, 0.5, 2.0, 1.0, 1.0, 0.5, 1.0, 2.0, 0.5, 0.5, 1.0],
/* 12 */ [1.0, 2.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 0.5, 2.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0],
/* 13 */ [0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 0.5, 0.5, 1.0, 1.0],
/* 14 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 0.0, 1.0],
/* 15 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 0.5, 0.5, 0.5, 1.0],
/* 16 */ [1.0, 0.5, 0.5, 0.5, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 0.5, 2.0, 1.0],
/* 17 */ [1.0, 0.5, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 0.5, 1.0, 1.0],
/* 18 */ [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
];

#[cfg(any(feature = "gen4", feature = "gen5"))]
pub const CRIT_MULTIPLIER: f32 = 2.0;

#[cfg(any(
    feature = "gen6",
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const CRIT_MULTIPLIER: f32 = 1.5;

#[allow(dead_code)]
pub enum DamageRolls {
    Average,
    Min,
    Max,
}

fn type_enum_to_type_matchup_int(type_enum: &PokemonType) -> usize {
    match type_enum {
        PokemonType::NORMAL => 0,
        PokemonType::FIRE => 1,
        PokemonType::WATER => 2,
        PokemonType::ELECTRIC => 3,
        PokemonType::GRASS => 4,
        PokemonType::ICE => 5,
        PokemonType::FIGHTING => 6,
        PokemonType::POISON => 7,
        PokemonType::GROUND => 8,
        PokemonType::FLYING => 9,
        PokemonType::PSYCHIC => 10,
        PokemonType::BUG => 11,
        PokemonType::ROCK => 12,
        PokemonType::GHOST => 13,
        PokemonType::DRAGON => 14,
        PokemonType::DARK => 15,
        PokemonType::STEEL => 16,
        PokemonType::FAIRY => 17,
        PokemonType::TYPELESS => 18,
        PokemonType::STELLAR => 18, // Stellar is typeless for type effectiveness
    }
}

pub fn type_effectiveness_modifier(attacking_type: &PokemonType, defender: &Pokemon) -> f32 {
    #[cfg(not(feature = "terastallization"))]
    let defending_types = defender.types;
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L175): a Stellar tera keeps its own types
    // on defense (Showdown's getTypes; as get_defending_types): Stealth Rock, Freeze-Dry, ...
    #[cfg(feature = "terastallization")]
    let defending_types = if defender.terastallized && defender.tera_type != PokemonType::STELLAR {
        (defender.tera_type, PokemonType::TYPELESS)
    } else {
        defender.types
    };
    _type_effectiveness_modifier(attacking_type, &defending_types)
}

/// alpha-poke patch (2026-10-16, doc/engine-diff.md L34): a move's effectiveness on the
/// defender, Freeze-Dry's on Water included (what Expert Belt, Tinted Lens, Filter, ... read:
/// Showdown's typeMod)
pub fn move_type_effectiveness(choice: &Choice, defender: &Pokemon) -> f32 {
    let e = type_effectiveness_modifier(&choice.move_type, defender);
    if choice.move_id == Choices::FREEZEDRY && defender.has_type(&PokemonType::WATER) {
        e * 4.0
    } else if choice.move_id == Choices::FLYINGPRESS {
        // (L118: Flying too)
        e * type_effectiveness_modifier(&PokemonType::FLYING, defender)
    } else {
        e
    }
}

fn _type_effectiveness_modifier(
    attacking_type: &PokemonType,
    defending_types: &(PokemonType, PokemonType),
) -> f32 {
    let mut modifier = 1.0;
    let attacking_type_index = type_enum_to_type_matchup_int(attacking_type);
    modifier = modifier
        * TYPE_MATCHUP_DAMAGE_MULTIPICATION[attacking_type_index]
            [type_enum_to_type_matchup_int(&defending_types.0)];
    modifier = modifier
        * TYPE_MATCHUP_DAMAGE_MULTIPICATION[attacking_type_index]
            [type_enum_to_type_matchup_int(&defending_types.1)];
    modifier
}

fn weather_modifier(attacking_move_type: &PokemonType, weather: &Weather) -> f32 {
    match weather {
        Weather::SUN => match attacking_move_type {
            PokemonType::FIRE => 1.5,
            PokemonType::WATER => 0.5,
            _ => 1.0,
        },
        Weather::RAIN => match attacking_move_type {
            PokemonType::WATER => 1.5,
            PokemonType::FIRE => 0.5,
            _ => 1.0,
        },
        Weather::HARSHSUN => match attacking_move_type {
            PokemonType::FIRE => 1.5,
            PokemonType::WATER => 0.0,
            _ => 1.0,
        },
        Weather::HEAVYRAIN => match attacking_move_type {
            PokemonType::WATER => 1.5,
            PokemonType::FIRE => 0.0,
            _ => 1.0,
        },
        _ => 1.0,
    }
}

// (L175: Showdown's condition: a tera of the move's type -- a Stellar one: a type not boosted yet
// --, the move's dex priority 0 or less, not multi-hit, not a power of its own: data 0, or 150
// with a callback -- Eruption, Water Spout, Dragon Energy)
#[cfg(feature = "terastallization")]
fn tera_floor_applies(attacker: &Pokemon, choice: &Choice) -> bool {
    use crate::choices::MOVES;
    let data = MOVES.get(&choice.move_id);
    let data_power = data.map_or(choice.base_power, |m| m.base_power);
    let own_power = data_power == 0.0
        || matches!(
            choice.move_id,
            Choices::ERUPTION | Choices::WATERSPOUT | Choices::DRAGONENERGY
        );
    let typed = if attacker.tera_type == PokemonType::STELLAR {
        stellar_boost_due(&choice.move_type, attacker)
    } else {
        attacker.tera_type == choice.move_type
    };
    attacker.terastallized
        && typed
        && data.map_or(choice.priority, |m| m.priority) <= 0
        && !own_power
        && choice.multi_hit() == crate::choices::MultiHitMove::None
        && choice.multi_accuracy() == crate::choices::MultiAccuracyMove::None
}

pub fn stellar_boost_due(move_type: &PokemonType, pkmn: &Pokemon) -> bool {
    pkmn.id == crate::pokemon::PokemonName::TERAPAGOSSTELLAR || pkmn.stellar_boosted & (1 << *move_type as u32) == 0
}

fn stab_modifier(attacking_move_type: &PokemonType, active_pkmn: &Pokemon) -> f32 {
    if attacking_move_type == &PokemonType::TYPELESS {
        return 1.0;
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L34): Adaptability's 2 / 2.25 here
    // (Showdown's onModifySTAB; before, its ratio on the base power)
    let s = stab_without_adaptability(attacking_move_type, active_pkmn);
    if active_pkmn.ability == Abilities::ADAPTABILITY && active_pkmn.has_type(attacking_move_type) {
        return if s == 2.0 { 2.25 } else { 2.0 };
    }
    s
}

fn stab_without_adaptability(attacking_move_type: &PokemonType, active_pkmn: &Pokemon) -> f32 {
    let active_types = active_pkmn.types;
    let move_has_basic_stab =
        attacking_move_type == &active_types.0 || attacking_move_type == &active_types.1;
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L175): a Stellar tera's first move of each
    // type: 2 with STAB, 4915 / 4096 without (Showdown's modifyDamage; Terapagos-Stellar always),
    // then the usual; was the usual 1.5 / 1 always
    if active_pkmn.terastallized && active_pkmn.tera_type == PokemonType::STELLAR {
        if stellar_boost_due(attacking_move_type, active_pkmn) {
            return if move_has_basic_stab { 2.0 } else { 4915.0 / 4096.0 };
        }
        return if move_has_basic_stab { 1.5 } else { 1.0 };
    }
    if active_pkmn.terastallized {
        if &active_pkmn.tera_type == attacking_move_type && move_has_basic_stab {
            return 2.0;
        } else if &active_pkmn.tera_type == attacking_move_type || move_has_basic_stab {
            return 1.5;
        }
    } else if move_has_basic_stab {
        return 1.5;
    }
    1.0
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L33): not with Guts, not for Facade
// (Showdown's modifyDamage, Gen 6+)
fn burn_modifier(choice: &Choice, attacker: &Pokemon, defender: &Pokemon) -> f32 {
    // (L35: Guts suppressed by the target's Neutralizing Gas, unless Ability Shield)
    let guts = attacker.ability == Abilities::GUTS
        && !(defender.ability == Abilities::NEUTRALIZINGGAS
            && attacker.item != Items::ABILITYSHIELD);
    if attacker.status == PokemonStatus::BURN
        && choice.category == MoveCategory::Physical
        && !guts
        && choice.move_id != Choices::FACADE
    {
        return 0.5;
    }

    1.0
}

// (L188: the actives' grounding with their volatiles, Side::active_grounded)
fn terrain_modifier(
    terrain: &Terrain,
    attacker_grounded: bool,
    defender_grounded: bool,
    choice: &Choice,
) -> f32 {
    #[cfg(any(feature = "champions", feature = "gen9", feature = "gen8"))]
    let terrain_boost = 5325.0 / 4096.0; // alpha-poke patch (L34): Showdown's 4096ths

    #[cfg(not(any(feature = "champions", feature = "gen9", feature = "gen8")))]
    let terrain_boost = 1.5;

    match terrain {
        Terrain::ELECTRICTERRAIN => {
            if choice.move_type == PokemonType::ELECTRIC && attacker_grounded {
                terrain_boost
            } else {
                1.0
            }
        }
        Terrain::GRASSYTERRAIN => {
            if choice.move_type == PokemonType::GRASS && attacker_grounded {
                terrain_boost
            } else if matches!(
                choice.move_id,
                Choices::EARTHQUAKE | Choices::BULLDOZE | Choices::MAGNITUDE
            ) && defender_grounded
            {
                // alpha-poke patch (L34): Bulldoze / Magnitude too, a grounded target only
                // (Showdown's grassyterrain onBasePower)
                0.5
            } else {
                1.0
            }
        }
        Terrain::MISTYTERRAIN => {
            if choice.move_type == PokemonType::DRAGON && defender_grounded {
                0.5
            } else {
                1.0
            }
        }
        Terrain::PSYCHICTERRAIN => {
            if choice.move_type == PokemonType::PSYCHIC && attacker_grounded {
                terrain_boost
            } else {
                1.0
            }
        }
        Terrain::NONE => 1.0,
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L34): the volatiles' modifiers at the stage
// Showdown applies them (before: one product on the damage)
struct VolatileMods {
    base_power: f32, // Charge (onBasePower)
    attack: f32,     // Flash Fire, Slow Start, Protosynthesis / Quark Drive (onModifyAtk / SpA)
    defense: f32,    // Protosynthesis / Quark Drive (onModifyDef / SpD)
    damage: f32,     // Glaive Rush (onSourceModifyDamage)
    type_stages: i8, // Tar Shot (onEffectiveness)
    immune: bool,    // Magnet Rise against Ground, a semi-invulnerable target
}

const BOOST_1_3: f32 = 5325.0 / 4096.0;

fn volatile_status_modifiers(
    choice: &Choice,
    attacking_side: &Side,
    defending_side: &Side,
) -> VolatileMods {
    let mut m = VolatileMods {
        base_power: 1.0,
        attack: 1.0,
        defense: 1.0,
        damage: 1.0,
        type_stages: 0,
        immune: false,
    };
    let physical = choice.category == MoveCategory::Physical;
    let special = choice.category == MoveCategory::Special;
    // L35: Neutralizing Gas out, the other's Protosynthesis / Quark Drive does nothing (their
    // handlers check ignoringAbility(); Ability Shield keeps it)
    let gassed = |side: &Side, other: &Side| {
        other.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
            && side.get_active_immutable().item != Items::ABILITYSHIELD
    };
    let (atk_gassed, def_gassed) = (
        gassed(attacking_side, defending_side),
        gassed(defending_side, attacking_side),
    );
    let atk = &attacking_side.volatile_statuses;
    if atk.contains(&PokemonVolatileStatus::FLASHFIRE) && choice.move_type == PokemonType::FIRE {
        m.attack *= 1.5;
    }
    if atk.contains(&PokemonVolatileStatus::SLOWSTART) && physical {
        m.attack *= 0.5;
    }
    if atk.contains(&PokemonVolatileStatus::CHARGE) && choice.move_type == PokemonType::ELECTRIC {
        m.base_power *= 2.0;
    }
    if (atk.contains(&PokemonVolatileStatus::PROTOSYNTHESISATK)
        || atk.contains(&PokemonVolatileStatus::QUARKDRIVEATK))
        && physical
        && !atk_gassed
    {
        m.attack *= BOOST_1_3;
    }
    if (atk.contains(&PokemonVolatileStatus::PROTOSYNTHESISSPA)
        || atk.contains(&PokemonVolatileStatus::QUARKDRIVESPA))
        && special
        && !atk_gassed
    {
        m.attack *= BOOST_1_3;
    }

    let def = &defending_side.volatile_statuses;
    if def.contains(&PokemonVolatileStatus::MAGNETRISE)
        && choice.move_type == PokemonType::GROUND
        && choice.move_id != Choices::THOUSANDARROWS
        && !grounded_by_effect(defending_side, defending_side.get_active_immutable())
    {
        m.immune = true;
    }
    if def.contains(&PokemonVolatileStatus::TARSHOT) && choice.move_type == PokemonType::FIRE {
        m.type_stages += 1;
    }
    if def.contains(&PokemonVolatileStatus::PHANTOMFORCE)
        || def.contains(&PokemonVolatileStatus::SHADOWFORCE)
        || def.contains(&PokemonVolatileStatus::BOUNCE)
        || def.contains(&PokemonVolatileStatus::DIG)
        || def.contains(&PokemonVolatileStatus::DIVE)
        || def.contains(&PokemonVolatileStatus::FLY)
    {
        m.immune = true;
    }
    if def.contains(&PokemonVolatileStatus::GLAIVERUSH) {
        m.damage *= 2.0;
    }
    if (def.contains(&PokemonVolatileStatus::PROTOSYNTHESISDEF)
        || def.contains(&PokemonVolatileStatus::QUARKDRIVEDEF))
        && physical
        && !def_gassed
    {
        m.defense *= BOOST_1_3;
    }
    if (def.contains(&PokemonVolatileStatus::PROTOSYNTHESISSPD)
        || def.contains(&PokemonVolatileStatus::QUARKDRIVESPD))
        && special
        && !def_gassed
    {
        m.defense *= BOOST_1_3;
    }
    m
}

/// alpha-poke patch (L32): grounded whatever its type, ability or Air Balloon (Showdown's
/// isGrounded: Iron Ball, Smack Down)
pub fn grounded_by_effect(side: &Side, pkmn: &Pokemon) -> bool {
    pkmn.item == Items::IRONBALL
        || side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SMACKDOWN)
}

fn get_defending_types(
    side: &Side,
    defending_pkmn: &Pokemon,
    attacking_pkmn: &Pokemon,
    attacking_choice: &Choice,
) -> (PokemonType, PokemonType) {
    let mut defender_types =
        if defending_pkmn.terastallized && !(defending_pkmn.tera_type == PokemonType::STELLAR) {
            (defending_pkmn.tera_type, PokemonType::TYPELESS)
        } else {
            defending_pkmn.types
        };
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L32): a Ground move against a grounded
    // Flying type: a Smack Down target's Flying type neutral (Showdown's isGrounded); an Iron
    // Ball holder's every type neutral (its onEffectiveness: 0 for each type, unless Smack Down)
    let flying = defender_types.0 == PokemonType::FLYING || defender_types.1 == PokemonType::FLYING;
    if attacking_choice.move_type == PokemonType::GROUND
        && flying
        && defending_pkmn.item == Items::IRONBALL
        && !side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SMACKDOWN)
        && !side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::ROOST)
    {
        return (PokemonType::TYPELESS, PokemonType::TYPELESS);
    }
    if attacking_choice.move_type == PokemonType::GROUND && grounded_by_effect(side, defending_pkmn)
    {
        if defender_types.0 == PokemonType::FLYING {
            defender_types.0 = PokemonType::TYPELESS;
        }
        if defender_types.1 == PokemonType::FLYING {
            defender_types.1 = PokemonType::TYPELESS;
        }
    }
    if defending_pkmn.terastallized && !(defending_pkmn.tera_type == PokemonType::STELLAR) {
        return defender_types;
    }
    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::ROOST)
    {
        if defender_types.0 == PokemonType::FLYING {
            defender_types = (PokemonType::TYPELESS, defender_types.1);
        }
        if defender_types.1 == PokemonType::FLYING {
            defender_types = (defender_types.0, PokemonType::TYPELESS);
        }
    }
    if (attacking_pkmn.ability == Abilities::SCRAPPY
        || attacking_pkmn.ability == Abilities::MINDSEYE)
        && (attacking_choice.move_type == PokemonType::NORMAL
            || attacking_choice.move_type == PokemonType::FIGHTING)
    {
        if defender_types.0 == PokemonType::GHOST {
            defender_types = (PokemonType::TYPELESS, defender_types.1);
        }
        if defender_types.1 == PokemonType::GHOST {
            defender_types = (defender_types.0, PokemonType::TYPELESS);
        }
    }
    defender_types
}

fn get_attacking_and_defending_stats(
    attacker: &Pokemon,
    defender: &Pokemon,
    attacking_side: &Side,
    defending_side: &Side,
    choice: &Choice,
    effective_weather: Weather,
) -> (i16, i16, i16, i16) {
    let mut should_calc_attacker_boost = true;
    let mut should_calc_defender_boost = true;
    let defending_stat;
    let (
        attacking_final_stat,
        mut defending_final_stat,
        crit_attacking_stat,
        mut crit_defending_stat,
    );

    // alpha-poke patch (2026-10-17, doc/engine-diff.md L216): the target's Unaware is ignored by
    // every Mold Breaker and an ability-ignoring move (Photon Geyser, ...), not through an Ability
    // Shield; and suppressed by the attacker's Neutralizing Gas. It was Mold Breaker only
    let unaware_broken = (matches!(
        attacker.ability,
        Abilities::MOLDBREAKER | Abilities::TERAVOLT | Abilities::TURBOBLAZE
    ) || matches!(
        choice.move_id,
        Choices::MOONGEISTBEAM | Choices::SUNSTEELSTRIKE | Choices::PHOTONGEYSER
    )) && defender.item != Items::ABILITYSHIELD
        || attacker.ability == Abilities::NEUTRALIZINGGAS && defender.item != Items::ABILITYSHIELD;
    match choice.category {
        MoveCategory::Physical => {
            // Unaware checks
            if defender.ability == Abilities::UNAWARE && !unaware_broken
            {
                should_calc_attacker_boost = false;
            }
            // alpha-poke patch (2026-10-17, doc/engine-diff.md L160): the attacker's own Unaware,
            // whatever the target's ability (Mold Breaker is the attacker's against the target's);
            // the target's Mold Breaker used to switch it off
            if attacker.ability == Abilities::UNAWARE {
                should_calc_defender_boost = false;
            }
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L67): Sacred Sword / Darkest Lariat /
            // Chip Away ignore the target's Defense boosts (Showdown's ignoreDefensive)
            if matches!(
                choice.move_id,
                Choices::SACREDSWORD | Choices::DARKESTLARIAT | Choices::CHIPAWAY
            ) {
                should_calc_defender_boost = false;
            }

            // Get the attacking stat

            // checks for moves that change which stat is used for the attacking_stat
            if choice.move_id == Choices::FOULPLAY {
                if should_calc_attacker_boost {
                    attacking_final_stat =
                        defending_side.calculate_boosted_stat(PokemonBoostableStat::Attack);
                } else {
                    attacking_final_stat = defender.attack;
                }
            } else if choice.move_id == Choices::BODYPRESS {
                if should_calc_attacker_boost {
                    attacking_final_stat =
                        attacking_side.calculate_boosted_stat(PokemonBoostableStat::Defense);
                } else {
                    attacking_final_stat = attacker.defense;
                }
            } else if should_calc_attacker_boost {
                attacking_final_stat =
                    attacking_side.calculate_boosted_stat(PokemonBoostableStat::Attack);
            } else {
                attacking_final_stat = attacker.attack;
            }

            // Get the defending stat
            defending_stat = PokemonBoostableStat::Defense;
            if should_calc_defender_boost {
                defending_final_stat =
                    defending_side.calculate_boosted_stat(PokemonBoostableStat::Defense);
            } else {
                defending_final_stat = defender.defense;
            }
        }
        MoveCategory::Special => {
            // Unaware checks
            if defender.ability == Abilities::UNAWARE && !unaware_broken
            {
                should_calc_attacker_boost = false;
            }
            // alpha-poke patch (2026-10-17, doc/engine-diff.md L160): the attacker's own Unaware,
            // whatever the target's ability (Mold Breaker is the attacker's against the target's);
            // the target's Mold Breaker used to switch it off
            if attacker.ability == Abilities::UNAWARE {
                should_calc_defender_boost = false;
            }

            // Get the attacking stat
            if should_calc_attacker_boost {
                attacking_final_stat =
                    attacking_side.calculate_boosted_stat(PokemonBoostableStat::SpecialAttack);
            } else {
                attacking_final_stat = attacker.special_attack;
            }

            // Get the defending stat
            // check for moves that change which stat is used for the defending_stat
            if choice.move_id == Choices::PSYSHOCK
                || choice.move_id == Choices::SECRETSWORD
                || choice.move_id == Choices::PSYSTRIKE
            {
                defending_stat = PokemonBoostableStat::Defense;
                if should_calc_defender_boost {
                    defending_final_stat =
                        defending_side.calculate_boosted_stat(PokemonBoostableStat::Defense);
                } else {
                    defending_final_stat = defender.defense;
                }
            } else {
                defending_stat = PokemonBoostableStat::SpecialDefense;
                if should_calc_defender_boost {
                    defending_final_stat =
                        defending_side.calculate_boosted_stat(PokemonBoostableStat::SpecialDefense);
                } else {
                    defending_final_stat = defender.special_defense;
                }
            }
        }
        _ => panic!("Can only calculate damage for physical or special moves"),
    }

    // alpha-poke patch (2026-10-16, doc/engine-diff.md L88): a crit drops only the stat's boosts
    // that hurt the attacker (Showdown's getDamage: atkBoosts < 0, defBoosts > 0 -> 0), of the stat
    // actually used (Body Press: the user's Defense, Foul Play: the target's Attack) and only
    // where they count at all (Unaware, Sacred Sword); it kept the boosts of the usual stat
    let boost_of = |side: &Side, stat: PokemonBoostableStat| match stat {
        PokemonBoostableStat::Attack => side.attack_boost,
        PokemonBoostableStat::Defense => side.defense_boost,
        PokemonBoostableStat::SpecialAttack => side.special_attack_boost,
        _ => side.special_defense_boost,
    };
    let (atk_side, atk_stat) = match (choice.category, choice.move_id) {
        (MoveCategory::Physical, Choices::FOULPLAY) => {
            (defending_side, PokemonBoostableStat::Attack)
        }
        (MoveCategory::Physical, Choices::BODYPRESS) => {
            (attacking_side, PokemonBoostableStat::Defense)
        }
        (MoveCategory::Physical, _) => (attacking_side, PokemonBoostableStat::Attack),
        _ => (attacking_side, PokemonBoostableStat::SpecialAttack),
    };
    let raw = |pkmn: &Pokemon, stat: PokemonBoostableStat| match stat {
        PokemonBoostableStat::Attack => pkmn.attack,
        PokemonBoostableStat::Defense => pkmn.defense,
        PokemonBoostableStat::SpecialAttack => pkmn.special_attack,
        _ => pkmn.special_defense,
    };
    crit_attacking_stat = if should_calc_attacker_boost && boost_of(atk_side, atk_stat) > 0 {
        atk_side.calculate_boosted_stat(atk_stat)
    } else {
        raw(atk_side.get_active_immutable(), atk_stat)
    };
    crit_defending_stat =
        if should_calc_defender_boost && boost_of(defending_side, defending_stat) < 0 {
            defending_side.calculate_boosted_stat(defending_stat)
        } else {
            raw(defender, defending_stat)
        };

    #[cfg(any(
        feature = "gen4",
        feature = "gen5",
        feature = "gen6",
        feature = "gen7",
        feature = "gen8",
        feature = "gen9",
        feature = "champions"
    ))]
    if effective_weather == Weather::SNOW
        && defender.has_type(&PokemonType::ICE)
        && defending_stat == PokemonBoostableStat::Defense
    {
        defending_final_stat = (defending_final_stat as f32 * 1.5) as i16;
        crit_defending_stat = (crit_defending_stat as f32 * 1.5) as i16;
    } else if effective_weather == Weather::SAND
        && defender.has_type(&PokemonType::ROCK)
        && defending_stat == PokemonBoostableStat::SpecialDefense
    {
        defending_final_stat = (defending_final_stat as f32 * 1.5) as i16;
        crit_defending_stat = (crit_defending_stat as f32 * 1.5) as i16;
    }

    (
        attacking_final_stat,
        defending_final_stat,
        crit_attacking_stat,
        crit_defending_stat,
    )
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L34): Showdown's damage step by step with its
// integer rounding (sim/battle-actions.ts getDamage / modifyDamage, battle.ts modify): the base
// power and the stats modified once by their chained modifiers, the base damage, weather, crit,
// the roll (85-100%), STAB, effectiveness (x 2 / halved per stage), burn, the final modifiers
// (ModifyDamage: screens, ...); before, one float product of every modifier on the damage and
// rolls of 85-100% of the final number
#[derive(Clone, Copy, Debug)]
pub struct DamageRecipe {
    base: i64,
    crit_base: i64,
    stab: i64,
    type_stages: i8,
    burn: bool,
    final_mod: f32,
    screen_mod: f32,
}

/// a modifier in 4096ths (Showdown's chain / modify)
fn q4096(m: f32) -> i64 {
    if m == 1.0 {
        4096
    } else {
        (m * 4096.0).round() as i64
    }
}

/// Showdown's modify(value, modifier): tr((tr(value * modifier) + 2047) / 4096)
fn modify(value: i64, m4096: i64) -> i64 {
    if m4096 == 4096 {
        value
    } else {
        (value * m4096 + 2047) / 4096
    }
}

impl DamageRecipe {
    /// the damage of the roll `r` (85-100)
    pub fn roll(&self, r: i64, crit: bool) -> i16 {
        let mut d = if crit { self.crit_base } else { self.base };
        d = d * r / 100;
        d = modify(d, self.stab);
        if self.type_stages > 0 {
            d <<= self.type_stages;
        } else {
            for _ in 0..(-self.type_stages) {
                d /= 2;
            }
        }
        if self.burn {
            d = modify(d, 2048);
        }
        let m = if crit {
            self.final_mod
        } else {
            self.final_mod * self.screen_mod
        };
        d = modify(d, q4096(m));
        d.clamp(1, i16::MAX as i64) as i16
    }

    /// the 16 rolls, lowest first
    pub fn rolls(&self, crit: bool) -> [i16; 16] {
        let mut out = [0; 16];
        for (i, x) in out.iter_mut().enumerate() {
            *x = self.roll(85 + i as i64, crit);
        }
        out
    }
}

fn type_stages(effectiveness: f32) -> i8 {
    if effectiveness == 1.0 {
        0
    } else if effectiveness == 2.0 {
        1
    } else if effectiveness == 0.5 {
        -1
    } else if effectiveness == 4.0 {
        2
    } else if effectiveness == 0.25 {
        -2
    } else {
        effectiveness.log2().round() as i8
    }
}

fn common_pkmn_damage_calc(
    attacking_side: &Side,
    attacker: &Pokemon,
    attacking_stat: i16,
    crit_attacking_stat: i16,
    defending_side: &Side,
    defender: &Pokemon,
    defending_stat: i16,
    crit_defending_stat: i16,
    weather: &Weather,
    terrain: &Terrain,
    choice: &Choice,
) -> Option<DamageRecipe> {
    let vol = volatile_status_modifiers(&choice, attacking_side, defending_side);
    let effectiveness = if defender.terastallized && choice.move_type == PokemonType::STELLAR {
        2.0
    } else {
        _type_effectiveness_modifier(
            &choice.move_type,
            &get_defending_types(&defending_side, defender, attacker, choice),
        )
    };
    let mut weather_mod = 1.0;
    // (L208: not by a fainted holder: State::weather_suppressed)
    let suppresses =
        |p: &Pokemon| matches!(p.ability, Abilities::AIRLOCK | Abilities::CLOUDNINE) && p.hp > 0;
    if !suppresses(attacker) && !suppresses(defender) {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): not against a Utility Umbrella
        // holder in sun / rain (Showdown's onWeatherModifyDamage)
        if !(defender.item == Items::UTILITYUMBRELLA
            && matches!(
                weather,
                Weather::SUN | Weather::RAIN | Weather::HARSHSUN | Weather::HEAVYRAIN
            ))
        {
            weather_mod = weather_modifier(&choice.move_type, weather);
        }
    }
    if vol.immune || effectiveness == 0.0 || weather_mod == 0.0 {
        return None;
    }

    let level = (2 * attacker.level as i64) / 5 + 2;
    let base_power =
        choice.base_power * vol.base_power * terrain_modifier(
            terrain,
            attacking_side.active_grounded(),
            defending_side.active_grounded(),
            &choice,
        );
    // modify's rounding of the chained base power (half down)
    let base_power = ((base_power as f64 + 2047.0 / 4096.0).floor() as i64).max(1);
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L175): the tera floor of 60 where Showdown's
    // getDamage has it, after the BasePower modifiers (a terrain's, Technician's, a gem's, a
    // basePowerCallback's: Grassy Glide in Grassy Terrain, Acrobatics without an item are above)
    #[cfg(feature = "terastallization")]
    let base_power = if base_power < 60 && tera_floor_applies(attacker, choice) {
        60
    } else {
        base_power
    };
    let stat = |s: i16, m: f32| modify(s as i64, q4096(m)).max(1);
    let base = |a: i16, d: i16| {
        let a = stat(a, vol.attack * choice.attack_modifier);
        let d = stat(d, vol.defense * choice.defense_modifier);
        let b = level * base_power * a / d / 50 + 2;
        modify(b, q4096(weather_mod))
    };
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L154): Sniper, a crit's 1.5 x more
    // (Showdown's onModifyDamage; here on the crit's base)
    let gassed = defender.ability == Abilities::NEUTRALIZINGGAS
        && defender.hp > 0
        && attacker.item != Items::ABILITYSHIELD;
    let sniper = if attacker.ability == Abilities::SNIPER && !gassed {
        1.5
    } else {
        1.0
    };
    let crit_base =
        base(crit_attacking_stat, crit_defending_stat) as f32 * CRIT_MULTIPLIER * sniper;

    let screen_mod = if attacker.ability != Abilities::INFILTRATOR
        && (defending_side.side_conditions.aurora_veil > 0
            || (defending_side.side_conditions.reflect > 0
                && choice.category == MoveCategory::Physical)
            || (defending_side.side_conditions.light_screen > 0
                && choice.category == MoveCategory::Special))
    {
        0.5
    } else {
        1.0
    };
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L195): Tera Shell, a full-HP
    // Terapagos-Terastal resists every damaging hit it is not immune to (Showdown's
    // onEffectiveness: -1; breakable)
    // (L214: a mon transformed into one too -- its species Terapagos-Terastal in Showdown, the
    // engine keeps its own id)
    let tera_shell = (defender.id == crate::pokemon::PokemonName::TERAPAGOSTERASTAL
        || defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::TRANSFORM))
        && defender.ability == Abilities::TERASHELL
        && defender.hp == defender.maxhp
        && effectiveness > 0.0
        && !matches!(
            attacker.ability,
            Abilities::MOLDBREAKER | Abilities::TERAVOLT | Abilities::TURBOBLAZE
        )
        // (L203: nor the moves that ignore abilities)
        && !matches!(
            choice.move_id,
            Choices::SUNSTEELSTRIKE | Choices::MOONGEISTBEAM | Choices::PHOTONGEYSER
        );
    Some(DamageRecipe {
        base: base(attacking_stat, defending_stat),
        crit_base: crit_base.floor() as i64,
        stab: q4096(stab_modifier(&choice.move_type, &attacker)),
        // Freeze-Dry: super effective on Water (its onEffectiveness: +1 instead of -1)
        type_stages: if tera_shell {
            -1
        } else {
            type_stages(effectiveness)
            + vol.type_stages
            + if choice.move_id == Choices::FREEZEDRY && defender.has_type(&PokemonType::WATER) {
                2
            } else {
                0
            }
            // alpha-poke patch (2026-10-17, doc/engine-diff.md L118): Flying Press is Flying too
            + if choice.move_id == Choices::FLYINGPRESS {
                type_stages(_type_effectiveness_modifier(
                    &PokemonType::FLYING,
                    &get_defending_types(&defending_side, defender, attacker, choice),
                ))
            } else {
                0
            }
        },
        burn: burn_modifier(&choice, &attacker, defender) != 1.0,
        // alpha-poke patch (2026-10-18, doc/engine-diff.md L219): Tinted Lens doubles a hit Tera
        // Shell made resisted (Showdown's typeMod; its ability hook saw the types only)
        final_mod: vol.damage
            * choice.damage_modifier
            * if tera_shell
                && attacker.ability == Abilities::TINTEDLENS
                && move_type_effectiveness(choice, defender) >= 1.0
            {
                2.0
            } else {
                1.0
            },
        screen_mod,
    })
}

/// alpha-poke patch (L34): the recipe of a move's damage (calculate_damage's), None for no
/// damage (a status move, an immunity)
pub fn damage_recipe(
    state: &State,
    attacking_side: &SideReference,
    choice: &Choice,
) -> Option<DamageRecipe> {
    if choice.category == MoveCategory::Status
        || choice.category == MoveCategory::Switch
        || choice.base_power <= 0.0
    {
        return None;
    }
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side);
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L211): Gravity grounds the target as Smack
    // Down does (grounded_by_effect: its Flying type, Levitate, Magnet Rise, an Air Balloon); a
    // copy of its side with the mark, only then
    let grounded;
    let defending_side = if state.gravity > 0
        && choice.move_type == PokemonType::GROUND
        && !defending_side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::SMACKDOWN)
    {
        let mut side = defending_side.clone();
        side.volatile_statuses
            .insert(PokemonVolatileStatus::SMACKDOWN);
        grounded = side;
        &grounded
    } else {
        defending_side
    };
    let attacker = attacking_side.get_active_immutable();
    let defender = defending_side.get_active_immutable();

    let effective_weather = if attacker.ability == Abilities::MEGASOL {
        Weather::SUN
    } else {
        state.get_weather()
    };

    let (attacking_stat, defending_stat, crit_attacking_stat, crit_defending_stat) =
        get_attacking_and_defending_stats(
            attacker,
            defender,
            attacking_side,
            defending_side,
            &choice,
            effective_weather,
        );

    common_pkmn_damage_calc(
        attacking_side,
        attacker,
        attacking_stat,
        crit_attacking_stat,
        defending_side,
        defender,
        defending_stat,
        crit_defending_stat,
        &effective_weather,
        &state.terrain.terrain_type,
        choice,
    )
}

/// alpha-poke patch (L34): the 16 rolls of a move's damage, without and with a crit
pub fn damage_rolls(
    state: &State,
    attacking_side: &SideReference,
    choice: &Choice,
) -> Option<([i16; 16], [i16; 16])> {
    damage_recipe(state, attacking_side, choice).map(|r| (r.rolls(false), r.rolls(true)))
}

// This is a basic damage calculation function that assumes special effects/modifiers
// are reflected in the `Choice` struct
//
// i.e. if an ability would multiply a move's base-power by 1.3x, that should already
// be reflected in the `Choice`
pub fn calculate_damage(
    state: &State,
    attacking_side: &SideReference,
    choice: &Choice,
    _damage_rolls: DamageRolls,
) -> Option<(i16, i16)> {
    if choice.category == MoveCategory::Status || choice.category == MoveCategory::Switch {
        return None;
    } else if choice.base_power == 0.0 {
        return Some((0, 0));
    }
    let recipe = match damage_recipe(state, attacking_side, choice) {
        Some(r) => r,
        None => return Some((0, 0)),
    };
    let (max, max_crit) = (recipe.roll(100, false), recipe.roll(100, true));
    match _damage_rolls {
        DamageRolls::Average => Some((
            (max as f32 * 0.925) as i16,
            (max_crit as f32 * 0.925) as i16,
        )),
        DamageRolls::Min => Some((recipe.roll(85, false), recipe.roll(85, true))),
        DamageRolls::Max => Some((max, max_crit)),
    }
}

pub fn calculate_futuresight_damage(
    attacking_side: &Side,
    defending_side: &Side,
    attacking_side_pokemon_index: &PokemonIndex,
    choice: &Choice,
    crit: bool,
    hint: i16,
) -> i16 {
    // L35: the user's Special Attack boosts while it is active (Showdown's getDamage on the
    // source at the hit; a switch resets them)
    let user_active = attacking_side.active_index == *attacking_side_pokemon_index;
    let attacking_stat = if user_active {
        attacking_side.calculate_boosted_stat(PokemonBoostableStat::SpecialAttack)
    } else {
        attacking_side.pokemon[attacking_side_pokemon_index].special_attack
    };
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L168): a crit (the end of turn's branch)
    // leaves out the user's lowered Sp. Atk and the target's raised Sp. Def (and the screens: the
    // recipe's crit)
    let crit_attacking_stat = if user_active && attacking_side.special_attack_boost > 0 {
        attacking_stat
    } else {
        attacking_side.pokemon[attacking_side_pokemon_index].special_attack
    };
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L15): a special move's damage at the hit,
    // as Showdown's: the target's Special Defense boosts, its Eviolite / Assault Vest, Aurora
    // Veil, and the STAB of the user (not of the side's active); before, the target's unboosted
    // stat and the active's types
    // (Eviolite / Assault Vest, L35: the choice's modifiers, item_modify_attack_against)
    let defending_stat =
        defending_side.calculate_boosted_stat(PokemonBoostableStat::SpecialDefense);
    let crit_defending_stat = if defending_side.special_defense_boost < 0 {
        defending_stat
    } else {
        defending_side.get_active_immutable().special_defense
    };
    let attacker = &attacking_side.pokemon[attacking_side_pokemon_index];
    match common_pkmn_damage_calc(
        attacking_side,
        attacker,
        attacking_stat,
        crit_attacking_stat,
        defending_side,
        defending_side.get_active_immutable(),
        defending_stat,
        crit_defending_stat,
        &Weather::NONE,
        &Terrain::NONE,
        choice,
    ) {
        // (Light Screen / Aurora Veil: the recipe's screens; L212: the harness's hint when it is
        // one of the rolls of this branch, a crit's or not)
        Some(r) => {
            let crit_hint = super::generate_instructions::CRIT_HINT;
            let (hint_crit, d) =
                if hint >= crit_hint { (true, hint - crit_hint) } else { (false, hint) };
            if hint >= 0 && hint_crit == crit && r.rolls(crit).contains(&d) {
                d
            } else {
                (r.roll(100, crit) as f32 * 0.925) as i16
            }
        }
        None => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::super::state::{PokemonVolatileStatus, Weather};
    use super::*;
    use crate::state::{PokemonStatus, PokemonType, SideReference, State, VolatileStatusBitset};

    #[test]
    fn test_basic_damaging_move() {
        let state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };
        choice.move_id = Choices::TACKLE;
        choice.move_type = PokemonType::TYPELESS;
        choice.base_power = 40.0;
        choice.category = MoveCategory::Physical;

        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        // level 100 tackle with 100 base stats across the board (attacker & defender)
        assert_eq!(32, dmg.unwrap().0);
    }

    #[test]
    fn test_basic_non_damaging_move() {
        let state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };
        choice.move_id = Choices::PROTECT;
        choice.category = MoveCategory::Status;

        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        assert_eq!(None, dmg);
    }

    #[test]
    fn test_move_with_zero_base_power() {
        let state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };
        choice.move_id = Choices::TACKLE;
        choice.move_type = PokemonType::TYPELESS;
        choice.base_power = 0.0;
        choice.category = MoveCategory::Physical;

        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        assert_eq!(0, dmg.unwrap().0);
    }

    #[test]
    fn test_boosted_damaging_move() {
        let mut state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };
        state.side_one.attack_boost = 1;
        choice.move_id = Choices::TACKLE;
        choice.move_type = PokemonType::TYPELESS;
        choice.base_power = 40.0;
        choice.category = MoveCategory::Physical;

        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        assert_eq!(48, dmg.unwrap().0);
    }

    #[test]
    fn test_unaware_does_not_get_damaged_by_boosted_stats() {
        let mut state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };
        state.side_one.attack_boost = 1;
        state.side_two.get_active().ability = Abilities::UNAWARE;
        choice.move_id = Choices::TACKLE;
        choice.move_type = PokemonType::TYPELESS;
        choice.base_power = 40.0;
        choice.category = MoveCategory::Physical;

        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        assert_eq!(32, dmg.unwrap().0);
    }

    #[test]
    fn test_unaware_does_get_damaged_by_boosted_stats_if_attacker_has_moldbreaker() {
        let mut state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };
        state.side_one.attack_boost = 1;
        state.side_two.get_active().ability = Abilities::UNAWARE;
        state.side_one.get_active().ability = Abilities::MOLDBREAKER;
        choice.move_id = Choices::TACKLE;
        choice.move_type = PokemonType::TYPELESS;
        choice.base_power = 40.0;
        choice.category = MoveCategory::Physical;

        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        assert_eq!(48, dmg.unwrap().0);
    }

    #[test]
    fn test_basic_super_effective_move() {
        let mut state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };

        state.side_two.get_active().types = (PokemonType::FIRE, PokemonType::TYPELESS);
        choice.move_id = Choices::WATERGUN;
        choice.move_type = PokemonType::WATER;
        choice.base_power = 40.0;
        choice.category = MoveCategory::Special;
        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        assert_eq!(64, dmg.unwrap().0);
    }

    #[test]
    fn test_basic_not_very_effective_move() {
        let mut state = State::default();
        let mut choice = Choice {
            ..Default::default()
        };

        state.side_two.get_active().types = (PokemonType::WATER, PokemonType::TYPELESS);
        choice.move_id = Choices::WATERGUN;
        choice.move_type = PokemonType::WATER;
        choice.base_power = 40.0;
        choice.category = MoveCategory::Special;
        let dmg = calculate_damage(
            &state,
            &SideReference::SideOne,
            &choice,
            DamageRolls::Average,
        );

        assert_eq!(15, dmg.unwrap().0);
    }

    macro_rules! weather_tests {
        ($($name:ident: $value:expr,)*) => {
            $(
                #[test]
                fn $name() {
                    let (weather_type, move_type, expected_damage_amount) = $value;
                    let mut state = State::default();
                    let mut choice = Choice {
                        ..Default::default()
                    };
                    state.weather.weather_type = weather_type;

                    choice.move_type = move_type;
                    choice.base_power = 40.0;
                    choice.category = MoveCategory::Special;
                    let dmg = calculate_damage(&state, &SideReference::SideOne, &choice, DamageRolls::Average);

                    assert_eq!(expected_damage_amount, dmg.unwrap().0);
                }
             )*
        }
    }
    weather_tests! {
        test_rain_boosting_water: (Weather::RAIN, PokemonType::WATER, 48),
        test_rain_not_boosting_normal: (Weather::RAIN, PokemonType::NORMAL, 48),
        test_sun_boosting_fire: (Weather::SUN, PokemonType::FIRE, 48),
        test_sun_reducing_water: (Weather::SUN, PokemonType::WATER, 15),
        test_sun_not_boosting_normal: (Weather::SUN, PokemonType::NORMAL, 48),
        test_heavy_rain_makes_fire_do_zero: (Weather::HEAVYRAIN, PokemonType::FIRE, 0),
        test_heavy_rain_boost_water: (Weather::HEAVYRAIN, PokemonType::WATER, 48),
        test_harsh_sun_makes_water_do_zero: (Weather::HARSHSUN, PokemonType::WATER, 0),
        test_harsh_sun_boosting_fire: (Weather::HARSHSUN, PokemonType::FIRE, 48),
    }

    macro_rules! stab_tests {
        ($($name:ident: $value:expr,)*) => {
            $(
                #[test]
                fn $name() {
                    let (attacker_types, attacking_move_type, expected_damage_amount) = $value;
                    let mut state = State::default();
                    let mut choice = Choice {
                        ..Default::default()
                    };
                    state.side_one.get_active().types = attacker_types;

                    choice.move_type = attacking_move_type;
                    choice.base_power = 40.0;
                    choice.category = MoveCategory::Special;
                    let dmg = calculate_damage(&state, &SideReference::SideOne, &choice, DamageRolls::Average);

                    assert_eq!(expected_damage_amount, dmg.unwrap().0);
                }
             )*
        }
    }
    stab_tests! {
        test_basic_stab: ((PokemonType::WATER, PokemonType::FIRE), PokemonType::WATER, 48),
        test_basic_without_stab: ((PokemonType::WATER, PokemonType::FIRE), PokemonType::NORMAL, 32),
    }

    macro_rules! burn_tests {
        ($($name:ident: $value:expr,)*) => {
            $(
                #[test]
                fn $name() {
                    let (attacking_move_category, expected_damage_amount) = $value;
                    let mut state = State::default();
                    let mut choice = Choice {
                        ..Default::default()
                    };
                    state.side_one.get_active().status = PokemonStatus::BURN;

                    choice.category = attacking_move_category;
                    choice.move_type = PokemonType::TYPELESS;
                    choice.base_power = 40.0;
                    let dmg = calculate_damage(&state, &SideReference::SideOne, &choice, DamageRolls::Average);

                    assert_eq!(expected_damage_amount, dmg.unwrap().0);
                }
             )*
        }
    }
    burn_tests! {
        test_physical_move_when_burned_reduces: (MoveCategory::Physical, 15),
        test_special_move_when_burned_does_not_reduce: (MoveCategory::Special, 32),
    }

    macro_rules! screens_tests {
        ($($name:ident: $value:expr,)*) => {
            $(
                #[test]
                fn $name() {
                    let (reflect_count, lightscreen_count, auroraveil_count, move_category, expected_damage_amount) = $value;
                    let mut state = State::default();
                    let mut choice = Choice {
                        ..Default::default()
                    };
                    state.side_two.side_conditions.reflect = reflect_count;
                    state.side_two.side_conditions.light_screen = lightscreen_count;
                    state.side_two.side_conditions.aurora_veil = auroraveil_count;

                    choice.category = move_category;
                    choice.base_power = 40.0;
                    choice.move_type = PokemonType::TYPELESS;
                    let dmg = calculate_damage(&state, &SideReference::SideOne, &choice, DamageRolls::Average);

                    assert_eq!(expected_damage_amount, dmg.unwrap().0);
                }
             )*
        }
    }
    screens_tests! {
        test_reflect_reduces_physical_damage_by_half: (1, 0, 0, MoveCategory::Physical, 15),
        test_lightscreen_reduces_special_damage_by_half: (0, 1, 0, MoveCategory::Special, 15),
        test_auroraveil_reduces_physical_damage_by_half: (0, 0, 1, MoveCategory::Physical, 15),
        test_auroraveil_reduces_special_damage_by_half: (0, 0, 1, MoveCategory::Special, 15),
        test_reflect_does_not_reduce_special_damage: (1, 0, 0, MoveCategory::Special, 32),
        test_light_screen_does_not_reduce_physical_damage: (0, 1, 0, MoveCategory::Physical, 32),
        test_auroraveil_does_not_stack_with_reflect: (1, 1, 1, MoveCategory::Physical, 15),
        test_auroraveil_does_not_stack_with_lightscreen: (1, 1, 1, MoveCategory::Special, 15),
    }

    macro_rules! volatile_status_tests{
        ($($name:ident: $value:expr,)*) => {
            $(
                #[test]
                fn $name() {
                    let (attacking_volatile_status, defending_volatile_status, move_type, move_name, expected_damage_amount) = $value;
                    let mut state = State::default();
                    let mut choice = Choice {
                        ..Default::default()
                    };
                    let mut s1_vs = VolatileStatusBitset::default();
                    for vs in attacking_volatile_status {
                        s1_vs.insert(vs);
                    }
                    let mut s2_vs = VolatileStatusBitset::default();
                    for vs in defending_volatile_status {
                        s2_vs.insert(vs);
                    }
                    state.side_one.volatile_statuses = s1_vs;
                    state.side_two.volatile_statuses = s2_vs;

                    choice.move_id = move_name;
                    choice.category = MoveCategory::Physical;
                    choice.move_type = move_type;
                    choice.base_power = 40.0;
                    let dmg = calculate_damage(&state, &SideReference::SideOne, &choice, DamageRolls::Average);

                    assert_eq!(expected_damage_amount, dmg.unwrap().0);
                }
             )*
        }
    }
    volatile_status_tests! {
        test_flashfire_boosts_fire_move: (
            vec![PokemonVolatileStatus::FLASHFIRE],
            vec![],
            PokemonType::FIRE,
            Choices::NONE,
            48
        ),
        test_flashfire_does_not_boost_normal_move: (
            vec![PokemonVolatileStatus::FLASHFIRE],
            vec![],
            PokemonType::TYPELESS,
            Choices::NONE,
            32
        ),
        test_magnetrise_makes_pkmn_immune_to_ground_move: (
            vec![],
            vec![PokemonVolatileStatus::MAGNETRISE],
            PokemonType::GROUND,
            Choices::NONE,
            0
        ),
        test_thousandarrows_can_hit_magnetrise_pokemon: (
            vec![],
            vec![PokemonVolatileStatus::MAGNETRISE],
            PokemonType::GROUND,
            Choices::THOUSANDARROWS,
            32
        ),
        test_tarshot_boosts_fire_move: (
            vec![],
            vec![PokemonVolatileStatus::TARSHOT],
            PokemonType::FIRE,
            Choices::NONE,
            64
        ),
        test_slowstart_halves_move: (
            vec![PokemonVolatileStatus::SLOWSTART],
            vec![],
            PokemonType::NORMAL,
            Choices::NONE,
            24
        ),
        test_tarshot_and_flashfire_together: (
            vec![PokemonVolatileStatus::FLASHFIRE],
            vec![PokemonVolatileStatus::TARSHOT],
            PokemonType::FIRE,
            Choices::NONE,
            96 // alpha-poke patch (L34): Showdown's rounding (STAB 35 -> 52, x 2), was 97
        ),
        test_glaiverush_doubles_damage_against: (
            vec![],
            vec![PokemonVolatileStatus::GLAIVERUSH],
            PokemonType::NORMAL,
            Choices::NONE,
            96 // alpha-poke patch (L34): Showdown's rounding (STAB 35 -> 52, x 2), was 97
        ),
        test_phantomforce_on_defender_causes_0_damage: (
            vec![],
            vec![PokemonVolatileStatus::PHANTOMFORCE],
            PokemonType::NORMAL,
            Choices::NONE,
            0
        ),
    }
}
