#![allow(unused_variables)]
use super::damage_calc::move_type_effectiveness;
use super::generate_instructions::{add_remove_status_instructions, apply_boost_instruction};
use super::items::Items;
use super::state::{PokemonVolatileStatus, Terrain, Weather};
use crate::choices::{
    Boost, Choice, Choices, Effect, Heal, MoveCategory, MoveTarget, Secondary, StatBoosts,
    VolatileStatus,
};
use crate::define_enum_with_from_str;
use crate::instruction::{
    ApplyVolatileStatusInstruction, BoostInstruction, ChangeAbilityInstruction,
    ChangeItemInstruction, ChangeSideConditionInstruction, ChangeStatusInstruction, ChangeTerrain,
    ChangeType, ChangeVolatileStatusDurationInstruction, ChangeWeather, DamageInstruction,
    FormeChangeInstruction, HealInstruction, Instruction, RemoveVolatileStatusInstruction,
    StateInstructions,
};
use crate::pokemon::PokemonName;
use crate::state::{
    PokemonBoostableStat, PokemonSideCondition, PokemonStatus, PokemonType, Side, SideReference,
    State,
};
use std::cmp;

#[cfg(any(feature = "gen4", feature = "gen5"))]
pub const WEATHER_ABILITY_TURNS: i8 = -1;

#[cfg(any(
    feature = "gen6",
    feature = "gen7",
    feature = "gen8",
    feature = "gen9",
    feature = "champions"
))]
pub const WEATHER_ABILITY_TURNS: i8 = 5;

define_enum_with_from_str! {
    #[repr(i16)]
    #[derive(PartialEq, Debug, Clone, Copy)]
    Abilities {
        NONE,
        ARMORTAIL,
        RIPEN,
        TANGLEDFEET,
        DRAGONSMAW,
        CLEARBODY,
        GALVANIZE,
        VITALSPIRIT,
        AERILATE,
        DEFIANT,
        CUTECHARM,
        NEUROFORCE,
        SOUNDPROOF,
        RKSSYSTEM,
        POISONPOINT,
        STAKEOUT,
        UNNERVE,
        ROCKHEAD,
        AURABREAK,
        MIMICRY,
        BULLETPROOF,
        POWEROFALCHEMY,
        TECHNICIAN,
        MULTISCALE,
        ARENATRAP,
        BATTLEBOND,
        DISGUISE,
        EARLYBIRD,
        LIGHTNINGROD,
        MAGICIAN,
        REFRIGERATE,
        FRIENDGUARD,
        NOABILITY,
        GULPMISSILE,
        POWERCONSTRUCT,
        FORECAST,
        PRANKSTER,
        PROTEAN,
        ASONEGLASTRIER,
        SHADOWTAG,
        SHARPNESS,
        WINDRIDER,
        SKILLLINK,
        INTREPIDSWORD,
        SOULHEART,
        SWIFTSWIM,
        EARTHEATER,
        SUPERLUCK,
        SUPREMEOVERLORD,
        INSOMNIA,
        DANCER,
        STEAMENGINE,
        ANGERPOINT,
        CONTRARY,
        MAGMAARMOR,
        HUNGERSWITCH,
        RECEIVER,
        ZENMODE,
        EMERGENCYEXIT,
        ILLUSION,
        WEAKARMOR,
        DROUGHT,
        INNARDSOUT,
        SHIELDSDOWN,
        ADAPTABILITY,
        CORROSION,
        LONGREACH,
        PUREPOWER,
        TINTEDLENS,
        QUEENLYMAJESTY,
        DESOLATELAND,
        MOXIE,
        SAPSIPPER,
        SLUSHRUSH,
        BIGPECKS,
        STALL,
        WHITESMOKE,
        FLAREBOOST,
        SHADOWSHIELD,
        LIQUIDVOICE,
        MISTYSURGE,
        MULTITYPE,
        NOGUARD,
        TORRENT,
        DELTASTREAM,
        KLUTZ,
        LIBERO,
        SERENEGRACE,
        CURSEDBODY,
        UNAWARE,
        LIGHTMETAL,
        MARVELSCALE,
        TELEPATHY,
        QUICKDRAW,
        HYPERCUTTER,
        SYMBIOSIS,
        PLUS,
        MIRRORARMOR,
        PASTELVEIL,
        TOUGHCLAWS,
        EFFECTSPORE,
        MUMMY,
        BADDREAMS,
        MAGICGUARD,
        SANDSTREAM,
        POWERSPOT,
        FLAMEBODY,
        RECKLESS,
        PRESSURE,
        GOOEY,
        IMMUNITY,
        LEAFGUARD,
        HUGEPOWER,
        SOLARPOWER,
        SCHOOLING,
        MOTORDRIVE,
        ANTICIPATION,
        MERCILESS,
        TRACE,
        NATURALCURE,
        HARVEST,
        SUCTIONCUPS,
        ICEFACE,
        ROUGHSKIN,
        WONDERGUARD,
        WATERVEIL,
        FAIRYAURA,
        SANDSPIT,
        SEEDSOWER,
        TOXICDEBRIS,
        INTIMIDATE,
        DAUNTLESSSHIELD,
        AROMAVEIL,
        AIRLOCK,
        NORMALIZE,
        DARKAURA,
        VICTORYSTAR,
        GRASSYSURGE,
        STURDY,
        PICKPOCKET,
        ELECTRICSURGE,
        HADRONENGINE,
        ORICHALCUMPULSE,
        RUNAWAY,
        OBLIVIOUS,
        SURGESURFER,
        LEVITATE,
        ASONESPECTRIER,
        PICKUP,
        ICEBODY,
        CURIOUSMEDICINE,
        FLOWERVEIL,
        STATIC,
        WONDERSKIN,
        OVERGROW,
        PROPELLERTAIL,
        THICKFAT,
        GLUTTONY,
        KEENEYE,
        MOUNTAINEER,
        FLASHFIRE,
        COMPOUNDEYES,
        STEELWORKER,
        COMATOSE,
        BALLFETCH,
        DAZZLING,
        DOWNLOAD,
        TRANSISTOR,
        MOLDBREAKER,
        MYCELIUMMIGHT,
        LIQUIDOOZE,
        POISONHEAL,
        PRISMARMOR,
        SNIPER,
        STENCH,
        COMPETITIVE,
        SWARM,
        STALWART,
        ILLUMINATE,
        TURBOBLAZE,
        GORILLATACTICS,
        SPEEDBOOST,
        GUARDDOG,
        HEATPROOF,
        SNOWCLOAK,
        TERAVOLT,
        CHILLINGNEIGH,
        SHIELDDUST,
        RIVALRY,
        PRIMORDIALSEA,
        SCREENCLEANER,
        MAGNETPULL,
        HONEYGATHER,
        COTTONDOWN,
        GRASSPELT,
        BATTLEARMOR,
        BEASTBOOST,
        BERSERK,
        MINUS,
        RAINDISH,
        SYNCHRONIZE,
        FILTER,
        TRUANT,
        FURCOAT,
        FULLMETALBODY,
        REGENERATOR,
        FOREWARN,
        IRONBARBS,
        STAMINA,
        SANDRUSH,
        COLORCHANGE,
        BLAZE,
        ANALYTIC,
        TANGLINGHAIR,
        CLOUDNINE,
        STEELYSPIRIT,
        QUICKFEET,
        MAGICBOUNCE,
        MEGALAUNCHER,
        HEAVYMETAL,
        STORMDRAIN,
        PIXILATE,
        WATERCOMPACTION,
        JUSTIFIED,
        SLOWSTART,
        SNOWWARNING,
        FLOWERGIFT,
        SHEDSKIN,
        WIMPOUT,
        ICESCALES,
        INFILTRATOR,
        LIMBER,
        PSYCHICSURGE,
        DEFEATIST,
        WATERABSORB,
        IMPOSTER,
        DRYSKIN,
        FLUFFY,
        UNBURDEN,
        CHEEKPOUCH,
        STANCECHANGE,
        MOODY,
        ROCKYPAYLOAD,
        PUNKROCK,
        SANDVEIL,
        PARENTALBOND,
        STRONGJAW,
        BATTERY,
        HEALER,
        STEADFAST,
        DAMP,
        PERISHBODY,
        TRIAGE,
        SHEERFORCE,
        OWNTEMPO,
        FRISK,
        VOLTABSORB,
        GALEWINGS,
        AFTERMATH,
        STICKYHOLD,
        GRIMNEIGH,
        IRONFIST,
        REBOUND,
        UNSEENFIST,
        SOLIDROCK,
        HUSTLE,
        HYDRATION,
        SCRAPPY,
        MINDSEYE,
        OVERCOAT,
        NEUTRALIZINGGAS,
        SWEETVEIL,
        DRIZZLE,
        INNERFOCUS,
        POISONTOUCH,
        WANDERINGSPIRIT,
        GUTS,
        SHELLARMOR,
        RATTLED,
        WATERBUBBLE,
        SANDFORCE,
        TOXICBOOST,
        PERSISTENT,
        CHLOROPHYLL,
        SIMPLE,
        PURIFYINGSALT,
        EMBODYASPECTWELLSPRING,
        EMBODYASPECTCORNERSTONE,
        EMBODYASPECTHEARTHFLAME,
        EMBODYASPECTTEAL,
        ANGERSHELL,
        BEADSOFRUIN,
        COMMANDER,
        COSTAR,
        CUDCHEW,
        ELECTROMORPHOSIS,
        EMBODYASPECT,
        GOODASGOLD,
        HOSPITALITY,
        LINGERINGAROMA,
        OPPORTUNIST,
        POISONPUPPETEER,
        PROTOSYNTHESIS,
        QUARKDRIVE,
        SUPERSWEETSYRUP,
        SWORDOFRUIN,
        TABLETSOFRUIN,
        TERASHELL,
        TERASHIFT,
        TERAFORMZERO,
        THERMALEXCHANGE,
        TOXICCHAIN,
        VESSELOFRUIN,
        WELLBAKEDBODY,
        WINDPOWER,
        ZEROTOHERO,
        MEGASOL,
        DRAGONIZE,
        SPICYSPRAY,
        PIERCINGDRILL,
        EELEVATE,
        FIREMANE,
    },
    default = NONE
}

// https://bulbapedia.bulbagarden.net/wiki/Ignoring_Abilities#Ignorable_Abilities
pub fn mold_breaker_ignores(ability: &Abilities) -> bool {
    match ability {
        Abilities::BATTLEARMOR
        | Abilities::CLEARBODY
        | Abilities::ARMORTAIL
        | Abilities::EARTHEATER
        | Abilities::GUARDDOG
        | Abilities::GOODASGOLD
        | Abilities::ILLUMINATE
        | Abilities::MINDSEYE
        | Abilities::PURIFYINGSALT
        | Abilities::TERASHELL
        | Abilities::TABLETSOFRUIN
        | Abilities::THERMALEXCHANGE
        | Abilities::WELLBAKEDBODY
        | Abilities::VESSELOFRUIN
        | Abilities::DAMP
        | Abilities::DRYSKIN
        | Abilities::FILTER
        | Abilities::FLASHFIRE
        | Abilities::FLOWERGIFT
        | Abilities::HEATPROOF
        | Abilities::HYPERCUTTER
        | Abilities::IMMUNITY
        | Abilities::INNERFOCUS
        | Abilities::INSOMNIA
        | Abilities::KEENEYE
        | Abilities::LEAFGUARD
        | Abilities::LEVITATE
        | Abilities::EELEVATE
        | Abilities::LIGHTNINGROD
        | Abilities::LIMBER
        | Abilities::MAGMAARMOR
        | Abilities::MARVELSCALE
        | Abilities::MOTORDRIVE
        | Abilities::WINDRIDER
        | Abilities::OBLIVIOUS
        | Abilities::OWNTEMPO
        | Abilities::SANDVEIL
        | Abilities::SHELLARMOR
        | Abilities::SHIELDDUST
        | Abilities::SIMPLE
        | Abilities::SNOWCLOAK
        | Abilities::SOLIDROCK
        | Abilities::SOUNDPROOF
        | Abilities::STICKYHOLD
        | Abilities::STORMDRAIN
        | Abilities::STURDY
        | Abilities::SUCTIONCUPS
        | Abilities::TANGLEDFEET
        | Abilities::THICKFAT
        | Abilities::UNAWARE
        | Abilities::VITALSPIRIT
        | Abilities::VOLTABSORB
        | Abilities::WATERABSORB
        | Abilities::WATERVEIL
        | Abilities::WHITESMOKE
        | Abilities::WONDERGUARD
        | Abilities::BIGPECKS
        | Abilities::CONTRARY
        | Abilities::FRIENDGUARD
        | Abilities::HEAVYMETAL
        | Abilities::LIGHTMETAL
        | Abilities::MAGICBOUNCE
        | Abilities::MULTISCALE
        | Abilities::SAPSIPPER
        | Abilities::TELEPATHY
        | Abilities::WONDERSKIN
        | Abilities::AURABREAK
        | Abilities::AROMAVEIL
        | Abilities::BULLETPROOF
        | Abilities::FLOWERVEIL
        | Abilities::FURCOAT
        | Abilities::OVERCOAT
        | Abilities::SWEETVEIL
        | Abilities::DAZZLING
        | Abilities::DISGUISE
        | Abilities::FLUFFY
        | Abilities::QUEENLYMAJESTY
        | Abilities::WATERBUBBLE
        | Abilities::ICESCALES
        | Abilities::ICEFACE
        | Abilities::MIRRORARMOR
        | Abilities::PASTELVEIL
        | Abilities::PUNKROCK
        | Abilities::FAIRYAURA
        | Abilities::DARKAURA => true,
        _ => false,
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L106): the abilities Skill Swap fails on
// (Showdown's failskillswap; the data test checks the list)
// alpha-poke patch (2026-10-17, doc/engine-diff.md L184): the abilities no other ability can
// replace (Showdown's cantsuppress: setAbility fails) and the ones Trace does not copy (notrace);
// the data tests check the lists
pub const CANT_SUPPRESS: [Abilities; 16] = [
    Abilities::ASONEGLASTRIER,
    Abilities::ASONESPECTRIER,
    Abilities::BATTLEBOND,
    Abilities::COMATOSE,
    Abilities::DISGUISE,
    Abilities::GULPMISSILE,
    Abilities::ICEFACE,
    Abilities::MULTITYPE,
    Abilities::POWERCONSTRUCT,
    Abilities::RKSSYSTEM,
    Abilities::SCHOOLING,
    Abilities::SHIELDSDOWN,
    Abilities::STANCECHANGE,
    Abilities::TERASHIFT,
    Abilities::ZENMODE,
    Abilities::ZEROTOHERO,
];

pub const NO_TRACE: [Abilities; 34] = [
    Abilities::ASONEGLASTRIER,
    Abilities::ASONESPECTRIER,
    Abilities::BATTLEBOND,
    Abilities::COMATOSE,
    Abilities::COMMANDER,
    Abilities::DISGUISE,
    Abilities::EMBODYASPECTCORNERSTONE,
    Abilities::EMBODYASPECTHEARTHFLAME,
    Abilities::EMBODYASPECTTEAL,
    Abilities::EMBODYASPECTWELLSPRING,
    Abilities::FLOWERGIFT,
    Abilities::FORECAST,
    Abilities::HUNGERSWITCH,
    Abilities::ICEFACE,
    Abilities::ILLUSION,
    Abilities::IMPOSTER,
    Abilities::MULTITYPE,
    Abilities::NEUTRALIZINGGAS,
    Abilities::POISONPUPPETEER,
    Abilities::POWERCONSTRUCT,
    Abilities::POWEROFALCHEMY,
    Abilities::PROTOSYNTHESIS,
    Abilities::QUARKDRIVE,
    Abilities::RECEIVER,
    Abilities::RKSSYSTEM,
    Abilities::SCHOOLING,
    Abilities::SHIELDSDOWN,
    Abilities::STANCECHANGE,
    Abilities::TERAFORMZERO,
    Abilities::TERASHELL,
    Abilities::TERASHIFT,
    Abilities::TRACE,
    Abilities::ZENMODE,
    Abilities::ZEROTOHERO,
];

// alpha-poke patch (2026-10-17, doc/engine-diff.md L190): the abilities Role Play / Doodle do not
// copy and Entrainment does not give (Showdown's failroleplay / noentrain: the same list; the data
// test checks it)
pub const FAIL_ROLE_PLAY: [Abilities; 35] = [
    Abilities::ASONEGLASTRIER,
    Abilities::ASONESPECTRIER,
    Abilities::BATTLEBOND,
    Abilities::COMATOSE,
    Abilities::COMMANDER,
    Abilities::DISGUISE,
    Abilities::EMBODYASPECTCORNERSTONE,
    Abilities::EMBODYASPECTHEARTHFLAME,
    Abilities::EMBODYASPECTTEAL,
    Abilities::EMBODYASPECTWELLSPRING,
    Abilities::FLOWERGIFT,
    Abilities::FORECAST,
    Abilities::HUNGERSWITCH,
    Abilities::ICEFACE,
    Abilities::ILLUSION,
    Abilities::IMPOSTER,
    Abilities::MULTITYPE,
    Abilities::NEUTRALIZINGGAS,
    Abilities::POISONPUPPETEER,
    Abilities::POWERCONSTRUCT,
    Abilities::POWEROFALCHEMY,
    Abilities::PROTOSYNTHESIS,
    Abilities::QUARKDRIVE,
    Abilities::RECEIVER,
    Abilities::RKSSYSTEM,
    Abilities::SCHOOLING,
    Abilities::SHIELDSDOWN,
    Abilities::STANCECHANGE,
    Abilities::TERAFORMZERO,
    Abilities::TERASHELL,
    Abilities::TERASHIFT,
    Abilities::TRACE,
    Abilities::WONDERGUARD,
    Abilities::ZENMODE,
    Abilities::ZEROTOHERO,
];

// alpha-poke patch (2026-10-17, doc/engine-diff.md L190): Showdown's setAbility for a move (Worry
// Seed, Simple Beam, Entrainment, Role Play, Doodle): not on a fainted mon, not to or from a
// cantsuppress ability, not through an Ability Shield (its SetAbility); the old one ends (a
// Neutralizing Gas: the other's ability starts again; Protosynthesis / Quark Drive: their boost),
// the new one starts (not Imposter's transformation: a switch-in's). Whether it was set
pub fn set_ability(
    state: &mut State,
    side_ref: &SideReference,
    ability: Abilities,
    instructions: &mut StateInstructions,
) -> bool {
    let p = state.get_side(side_ref).get_active();
    let old = p.ability;
    if p.hp == 0
        || CANT_SUPPRESS.contains(&ability)
        || CANT_SUPPRESS.contains(&old)
        || p.item == Items::ABILITYSHIELD
    {
        return false;
    }
    instructions
        .instruction_list
        .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
            side_ref: *side_ref,
            ability_change: ability as i16 - old as i16,
        }));
    p.ability = ability;
    if old == Abilities::NEUTRALIZINGGAS {
        super::generate_instructions::restart_ability_after_gas(
            state,
            &side_ref.get_other_side(),
            instructions,
        );
    }
    if ability != Abilities::IMPOSTER {
        ability_on_switch_in(state, side_ref, instructions);
    }
    paradox_update(state, side_ref, instructions);
    true
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L184): Showdown's skillSwap, shared by Skill
// Swap and Wandering Spirit (were Skill Swap's own, L106; Wandering Spirit gave Mummy): the
// actives swap abilities and the new ones start (the source's old ability on the target first);
// not with a failskillswap ability, through an Ability Shield. `side_ref` is the source's side
pub fn skill_swap(state: &mut State, side_ref: &SideReference, instructions: &mut StateInstructions) {
    let target_ref = side_ref.get_other_side();
    let (a, d) = (
        state.get_side_immutable(side_ref).get_active_immutable(),
        state.get_side_immutable(&target_ref).get_active_immutable(),
    );
    if a.hp == 0
        || d.hp == 0
        || FAIL_SKILL_SWAP.contains(&a.ability)
        || FAIL_SKILL_SWAP.contains(&d.ability)
        || a.item == Items::ABILITYSHIELD
        || d.item == Items::ABILITYSHIELD
    {
        return;
    }
    let (mine, theirs) = (a.ability, d.ability);
    for (side_ref, old, new) in [(*side_ref, mine, theirs), (target_ref, theirs, mine)] {
        instructions
            .instruction_list
            .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
                side_ref,
                ability_change: new as i16 - old as i16,
            }));
        state.get_side(&side_ref).get_active().ability = new;
    }
    for side_ref in [target_ref, *side_ref] {
        if state.get_side_immutable(&side_ref).get_active_immutable().ability != Abilities::IMPOSTER {
            ability_on_switch_in(state, &side_ref, instructions);
        }
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L184): the once-per-battle abilities (Showdown's
// shieldBoost / swordBoost / syrupTriggered / bondTriggered, Gen 9), as Dauntless Shield's L181:
// a used one has its base ability none (the harness's and engine_state's encoding) and keeps the
// ability through a switch-out. Was Dauntless Shield only; Intrepid Sword raised at every entry
pub const ONCE_PER_BATTLE: [Abilities; 4] = [
    Abilities::DAUNTLESSSHIELD,
    Abilities::INTREPIDSWORD,
    Abilities::SUPERSWEETSYRUP,
    Abilities::BATTLEBOND,
];

fn used_once(pkmn: &crate::state::Pokemon) -> bool {
    ONCE_PER_BATTLE.contains(&pkmn.ability) && pkmn.base_ability == Abilities::NONE
}

fn use_once(pkmn: &mut crate::state::Pokemon, side_ref: &SideReference, instructions: &mut StateInstructions) {
    if pkmn.base_ability == pkmn.ability {
        instructions
            .instruction_list
            .push(Instruction::ChangeBaseAbility(ChangeAbilityInstruction {
                side_ref: *side_ref,
                ability_change: Abilities::NONE as i16 - pkmn.ability as i16,
            }));
        pkmn.base_ability = Abilities::NONE;
    }
}

pub const FAIL_SKILL_SWAP: [Abilities; 29] = [
    Abilities::ASONEGLASTRIER,
    Abilities::ASONESPECTRIER,
    Abilities::BATTLEBOND,
    Abilities::COMATOSE,
    Abilities::COMMANDER,
    Abilities::DISGUISE,
    Abilities::EMBODYASPECTCORNERSTONE,
    Abilities::EMBODYASPECTHEARTHFLAME,
    Abilities::EMBODYASPECTTEAL,
    Abilities::EMBODYASPECTWELLSPRING,
    Abilities::HUNGERSWITCH,
    Abilities::ICEFACE,
    Abilities::ILLUSION,
    Abilities::MULTITYPE,
    Abilities::NEUTRALIZINGGAS,
    Abilities::POISONPUPPETEER,
    Abilities::POWERCONSTRUCT,
    Abilities::PROTOSYNTHESIS,
    Abilities::QUARKDRIVE,
    Abilities::RKSSYSTEM,
    Abilities::SCHOOLING,
    Abilities::SHIELDSDOWN,
    Abilities::STANCECHANGE,
    Abilities::TERAFORMZERO,
    Abilities::TERASHELL,
    Abilities::TERASHIFT,
    Abilities::WONDERGUARD,
    Abilities::ZENMODE,
    Abilities::ZEROTOHERO,
];

// alpha-poke patch (2026-10-17, doc/engine-diff.md L141): Protosynthesis / Quark Drive follow the
// sun / Electric Terrain whenever they change (Showdown's onWeatherChange / onTerrainChange, and
// Booster Energy's onUpdate): on when it is there, off when it is gone unless it came from Booster
// Energy (FROMBOOSTER), and then a held Booster Energy goes off (the best stat as it is now). Not
// under the foe's Neutralizing Gas. Called after a switch-in, a move and the end of the turn's
// weather / terrain; before, only a switch-in and the sun's / terrain's end of turn did, and a
// held Booster Energy kept the volatile it had
pub fn paradox_update(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let (proto, field_on) = match state.get_side_immutable(side_ref).get_active_immutable().ability
    {
        Abilities::PROTOSYNTHESIS => (true, state.weather_is_active(&Weather::SUN)),
        Abilities::QUARKDRIVE => (false, state.terrain_is_active(&Terrain::ELECTRICTERRAIN)),
        _ => return,
    };
    let (side, foe) = state.get_both_sides(side_ref);
    let active = side.get_active_immutable();
    let gas = foe.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
        && foe.get_active_immutable().hp > 0;
    if active.hp == 0 || (gas && active.item != Items::ABILITYSHIELD) {
        return;
    }
    let all = if proto {
        [
            PokemonVolatileStatus::PROTOSYNTHESISATK,
            PokemonVolatileStatus::PROTOSYNTHESISDEF,
            PokemonVolatileStatus::PROTOSYNTHESISSPA,
            PokemonVolatileStatus::PROTOSYNTHESISSPD,
            PokemonVolatileStatus::PROTOSYNTHESISSPE,
        ]
    } else {
        [
            PokemonVolatileStatus::QUARKDRIVEATK,
            PokemonVolatileStatus::QUARKDRIVEDEF,
            PokemonVolatileStatus::QUARKDRIVESPA,
            PokemonVolatileStatus::QUARKDRIVESPD,
            PokemonVolatileStatus::QUARKDRIVESPE,
        ]
    };
    if let Some(on) = all.iter().find(|v| side.volatile_statuses.contains(v)) {
        if field_on
            || side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::FROMBOOSTER)
        {
            return;
        }
        side.volatile_statuses.remove(on);
        instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: *on,
                },
            ));
    }
    let booster = !field_on && side.get_active_immutable().item == Items::BOOSTERENERGY;
    if !field_on && !booster {
        return;
    }
    let volatile = if proto {
        protosynthesis_volatile_from_side(side)
    } else {
        quarkdrive_volatile_from_side(side)
    };
    if booster {
        instructions
            .instruction_list
            .push(Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: *side_ref,
                current_item: Items::BOOSTERENERGY,
                new_item: Items::NONE,
            }));
        side.get_active().item = Items::NONE;
        // (L178: used up, its last item: Showdown's useItem)
        super::items::set_last_item(
            side.get_active(),
            *side_ref,
            Items::BOOSTERENERGY,
            instructions,
        );
    }
    for v in [volatile, PokemonVolatileStatus::FROMBOOSTER] {
        if v == PokemonVolatileStatus::FROMBOOSTER && !booster {
            continue;
        }
        side.volatile_statuses.insert(v);
        instructions
            .instruction_list
            .push(Instruction::ApplyVolatileStatus(
                ApplyVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: v,
                },
            ));
    }
}

fn protosynthesis_volatile_from_side(side: &Side) -> PokemonVolatileStatus {
    match side.calculate_highest_stat() {
        PokemonBoostableStat::Attack => PokemonVolatileStatus::PROTOSYNTHESISATK,
        PokemonBoostableStat::Defense => PokemonVolatileStatus::PROTOSYNTHESISDEF,
        PokemonBoostableStat::SpecialAttack => PokemonVolatileStatus::PROTOSYNTHESISSPA,
        PokemonBoostableStat::SpecialDefense => PokemonVolatileStatus::PROTOSYNTHESISSPD,
        PokemonBoostableStat::Speed => PokemonVolatileStatus::PROTOSYNTHESISSPE,
        _ => panic!("Invalid stat for protosynthesis"),
    }
}

fn quarkdrive_volatile_from_side(side: &Side) -> PokemonVolatileStatus {
    match side.calculate_highest_stat() {
        PokemonBoostableStat::Attack => PokemonVolatileStatus::QUARKDRIVEATK,
        PokemonBoostableStat::Defense => PokemonVolatileStatus::QUARKDRIVEDEF,
        PokemonBoostableStat::SpecialAttack => PokemonVolatileStatus::QUARKDRIVESPA,
        PokemonBoostableStat::SpecialDefense => PokemonVolatileStatus::QUARKDRIVESPD,
        PokemonBoostableStat::Speed => PokemonVolatileStatus::QUARKDRIVESPE,
        _ => panic!("Invalid stat for quarkdrive"),
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L196): the hit Disguise / Ice Face takes
// (Showdown's onDamage, at the hit): Mimikyu-Busted and 1/8 of its HP, Eiscue-Noice and its stats
pub fn break_face(state: &mut State, side_ref: &SideReference, instructions: &mut StateInstructions) {
    let p = state.get_side(side_ref).get_active();
    let to = match p.id {
        PokemonName::MIMIKYU | PokemonName::MIMIKYUTOTEM => PokemonName::MIMIKYUBUSTED,
        PokemonName::EISCUE => PokemonName::EISCUENOICE,
        _ => return,
    };
    let from = p.id;
    instructions
        .instruction_list
        .push(Instruction::FormeChange(FormeChangeInstruction {
            side_ref: *side_ref,
            name_change: to as i16 - from as i16,
        }));
    p.id = to;
    if to == PokemonName::EISCUENOICE {
        p.recalculate_stats(from, side_ref, instructions);
    } else {
        let dmg = cmp::min(p.hp, p.maxhp / 8);
        instructions
            .instruction_list
            .push(Instruction::Damage(DamageInstruction {
                side_ref: *side_ref,
                damage_amount: dmg,
            }));
        p.hp -= dmg;
    }
}

pub fn ability_before_move(
    state: &mut State,
    choice: &mut Choice,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    let active_pkmn = attacking_side.get_active();
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L98): a hit on the target's Substitute
    let behind_sub = defending_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::SUBSTITUTE)
        && !choice.flags.sound
        && active_pkmn.ability != Abilities::INFILTRATOR;
    let defending_pkmn = defending_side.get_active();

    match defending_pkmn.ability {
        Abilities::NEUTRALIZINGGAS => {
            return;
        }
        // Incomplete: IceFace should not stop secondaries, but setting base_power to 0 makes
        // secondaries not apply in this engine
        Abilities::ICEFACE => {
            // (L196: not its Substitute's hit; the forme changes as the move hits: face_break)
            if defending_pkmn.id == PokemonName::EISCUE
                && choice.category == MoveCategory::Physical
                && !behind_sub
            {
                // hacky - changing the move to a status move makes it do no
                // damage but preserve secondary effects
                // due to some bad choices I made I cannot just set base_power to 0
                // (L156: a multi-hit move's first hit only)
                if choice.multi_hit() != crate::choices::MultiHitMove::None {
                    choice.first_hit_blocked = true;
                } else {
                    choice.category = MoveCategory::Status;
                }
                choice.face_break = true;
            }
        }
        // Technically incorrect
        // A move missing should not trigger this formechange
        #[cfg(not(any(feature = "gen8", feature = "gen9", feature = "champions")))]
        Abilities::DISGUISE
            if (choice.category == MoveCategory::Physical
                || choice.category == MoveCategory::Special)
                && (defending_pkmn.id == PokemonName::MIMIKYU
                    || defending_pkmn.id == PokemonName::MIMIKYUTOTEM) =>
        {
            choice.base_power = 0.0;
            instructions
                .instruction_list
                .push(Instruction::FormeChange(FormeChangeInstruction {
                    side_ref: side_ref.get_other_side(),
                    name_change: PokemonName::MIMIKYUBUSTED as i16 - defending_pkmn.id as i16,
                }));
            defending_pkmn.id = PokemonName::MIMIKYUBUSTED;
        }
        // (L98: only a hit that damages it -- not one it is immune to, nor its Substitute)
        #[cfg(any(feature = "gen8", feature = "gen9", feature = "champions"))]
        Abilities::DISGUISE
            if (choice.category == MoveCategory::Physical
                || choice.category == MoveCategory::Special)
                && (defending_pkmn.id == PokemonName::MIMIKYU
                    || defending_pkmn.id == PokemonName::MIMIKYUTOTEM)
                && !behind_sub
                && (move_type_effectiveness(choice, defending_pkmn) > 0.0
                    || matches!(
                        active_pkmn.ability,
                        Abilities::SCRAPPY | Abilities::MINDSEYE
                    )) =>
        {
            // (L156: a multi-hit move's first hit only)
            if choice.multi_hit() != crate::choices::MultiHitMove::None {
                choice.first_hit_blocked = true;
            } else {
                choice.base_power = 0.0;
            }
            // (L196: its forme and 1/8 as the move hits: break_face)
            choice.face_break = true;
        }
        _ => {}
    }
    match active_pkmn.ability {
        Abilities::GULPMISSILE => {
            if active_pkmn.id == PokemonName::CRAMORANT
                && (choice.move_id == Choices::SURF || choice.move_id == Choices::DIVE)
            {
                let new_forme = if active_pkmn.hp > active_pkmn.maxhp / 2 {
                    PokemonName::CRAMORANTGULPING
                } else {
                    PokemonName::CRAMORANTGORGING
                };
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: new_forme as i16 - active_pkmn.id as i16,
                    },
                ));
                active_pkmn.id = new_forme;
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L41): Gen 9 Protean / Libero in
        // generate_instructions (protean_type_change), when the move starts
        #[cfg(any(feature = "gen6", feature = "gen7", feature = "gen8"))]
        Abilities::PROTEAN | Abilities::LIBERO => {
            if !active_pkmn.has_type(&choice.move_type) && !active_pkmn.terastallized {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeType(ChangeType {
                        side_ref: *side_ref,
                        new_types: (choice.move_type, PokemonType::TYPELESS),
                        old_types: active_pkmn.types,
                    }));
                active_pkmn.types = (choice.move_type, PokemonType::TYPELESS);
                if !attacking_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::TYPECHANGE)
                {
                    instructions
                        .instruction_list
                        .push(Instruction::ApplyVolatileStatus(
                            ApplyVolatileStatusInstruction {
                                side_ref: *side_ref,
                                volatile_status: PokemonVolatileStatus::TYPECHANGE,
                            },
                        ));
                    attacking_side
                        .volatile_statuses
                        .insert(PokemonVolatileStatus::TYPECHANGE);
                }
            }
        }
        // (L179: Gorilla Tactics' lock: choice_lock, past the BeforeMove)
        _ => {}
    }
}

// alpha-poke patch (2026-10-16, L24): Neutralizing Gas does not suppress an Ability Shield
// holder's ability (the checks below)
// alpha-poke patch (2026-10-17, doc/engine-diff.md L151): Showdown's DamagingHit, once per hit
// after the hit's own effects (Clear Smog's clear, ...) and before its onAfterHit (Knock Off,
// Thief: choice_effects::choice_after_hit): the target's abilities (Rough Skin, Stamina, Weak
// Armor, Gooey, Justified, ...) and Rocky Helmet; not on a hit its Substitute took. Were part of
// ability_after_damage_hit (at the damage, before the hit's effects) or secondaries the move got
// before it (once per move)
// alpha-poke patch (2026-10-17, doc/engine-diff.md L151): Magician takes the target's item after
// the whole move (Showdown's onAfterMoveSecondarySelf: after the hits' Rocky Helmet, ...; was at
// the damage); not after its Knock Off (L134), not when its user fainted
pub fn magician_after_move(
    state: &mut State,
    choice: &Choice,
    side_ref: &SideReference,
    damage_dealt: i16,
    instructions: &mut StateInstructions,
) {
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    let active_pkmn = attacking_side.get_active();
    if active_pkmn.ability != Abilities::MAGICIAN
        || active_pkmn.hp == 0
        || (defending_side.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
            && defending_side.get_active_immutable().hp > 0
            && active_pkmn.item != Items::ABILITYSHIELD)
    {
        return;
    }
    let defending_pkmn = defending_side.get_active();
    if damage_dealt > 0
        && choice.move_id != Choices::KNOCKOFF
        && defending_pkmn.item != Items::NONE
        && defending_pkmn.item_can_be_removed()
        && active_pkmn.item == Items::NONE
    {
        instructions
            .instruction_list
            .push(Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: *side_ref,
                current_item: active_pkmn.item,
                new_item: defending_pkmn.item,
            }));
        active_pkmn.item = defending_pkmn.item;
        instructions
            .instruction_list
            .push(Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: side_ref.get_other_side(),
                current_item: defending_pkmn.item,
                new_item: Items::NONE,
            }));
        defending_pkmn.item = Items::NONE;
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L158): Relic Song changes Meloetta's forme after
// a hit (Aria <-> Pirouette: stats and types; Showdown's onAfterMoveSecondarySelf, not under Sheer
// Force, not while transformed); the switch-out brings Aria back (generate_instructions_from_switch)
// alpha-poke patch (2026-10-17, doc/engine-diff.md L162): Anger Shell, the move took its holder
// from above half to half or less: Atk / Sp. Atk / Speed +1, Def / Sp. Def -1 (Showdown's
// onAfterMoveSecondary); not under its foe's Neutralizing Gas
pub fn anger_shell(
    state: &mut State,
    side_ref: &SideReference,
    damage_dealt: i16,
    instructions: &mut StateInstructions,
) {
    let holder_ref = side_ref.get_other_side();
    let (attacking_side, side) = state.get_both_sides(side_ref);
    let gas = attacking_side.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
        && attacking_side.get_active_immutable().hp > 0;
    let holder = side.get_active_immutable();
    if holder.ability != Abilities::ANGERSHELL
        || gas
        || holder.hp == 0
        || damage_dealt <= 0
        || holder.hp > holder.maxhp / 2
        || holder.hp + damage_dealt <= holder.maxhp / 2
    {
        return;
    }
    for (stat, amount) in [
        (PokemonBoostableStat::Attack, 1),
        (PokemonBoostableStat::SpecialAttack, 1),
        (PokemonBoostableStat::Speed, 1),
        (PokemonBoostableStat::Defense, -1),
        (PokemonBoostableStat::SpecialDefense, -1),
    ] {
        apply_boost_instruction(side, &stat, &amount, &holder_ref, &holder_ref, instructions);
    }
}

pub fn relic_song_forme(
    state: &mut State,
    choice: &Choice,
    side_ref: &SideReference,
    damage_dealt: i16,
    instructions: &mut StateInstructions,
) {
    let side = state.get_side(side_ref);
    let user = side.get_active_immutable();
    if choice.move_id != Choices::RELICSONG
        || damage_dealt <= 0
        || user.hp == 0
        || user.ability == Abilities::SHEERFORCE
        || side
            .volatile_statuses
            .contains(&PokemonVolatileStatus::TRANSFORM)
    {
        return;
    }
    let to = match user.id {
        PokemonName::MELOETTA => PokemonName::MELOETTAPIROUETTE,
        PokemonName::MELOETTAPIROUETTE => PokemonName::MELOETTA,
        _ => return,
    };
    meloetta_forme(side, side_ref, to, instructions);
}

pub fn meloetta_forme(
    side: &mut Side,
    side_ref: &SideReference,
    to: PokemonName,
    instructions: &mut StateInstructions,
) {
    let types = if to == PokemonName::MELOETTAPIROUETTE {
        (PokemonType::NORMAL, PokemonType::FIGHTING)
    } else {
        (PokemonType::NORMAL, PokemonType::PSYCHIC)
    };
    let user = side.get_active();
    instructions
        .instruction_list
        .push(Instruction::FormeChange(FormeChangeInstruction {
            side_ref: *side_ref,
            name_change: to as i16 - user.id as i16,
        }));
    let from = user.id;
    user.id = to;
    user.recalculate_stats(from, side_ref, instructions);
    if user.types != types {
        instructions
            .instruction_list
            .push(Instruction::ChangeType(ChangeType {
                side_ref: *side_ref,
                new_types: types,
                old_types: user.types,
            }));
        user.types = types;
    }
    let changed = types != user.base_types;
    let has = side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::TYPECHANGE);
    if changed && !has {
        side.volatile_statuses
            .insert(PokemonVolatileStatus::TYPECHANGE);
        instructions
            .instruction_list
            .push(Instruction::ApplyVolatileStatus(
                ApplyVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: PokemonVolatileStatus::TYPECHANGE,
                },
            ));
    } else if !changed && has {
        side.volatile_statuses
            .remove(&PokemonVolatileStatus::TYPECHANGE);
        instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: PokemonVolatileStatus::TYPECHANGE,
                },
            ));
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L193): a drop the other mon's ability causes
// (Gooey, Tangling Hair, Cotton Down) with Showdown's Mirror Armor onTryBoost: the target's Mirror
// Armor sends it back to the source (if that one is still in; a stat at -6 stays); otherwise
// apply_boost_instruction
fn foe_drop(
    target: &mut Side,
    target_ref: &SideReference,
    source: &mut Side,
    source_ref: &SideReference,
    stat: &PokemonBoostableStat,
    amount: i8,
    instructions: &mut StateInstructions,
) -> bool {
    if amount < 0
        && target.get_active_immutable().ability == Abilities::MIRRORARMOR
        && target.get_boost_from_boost_enum(stat) > -6
    {
        if source.get_active_immutable().hp > 0 {
            apply_boost_instruction(source, stat, &amount, target_ref, source_ref, instructions);
        }
        return false;
    }
    apply_boost_instruction(target, stat, &amount, source_ref, target_ref, instructions)
}

pub fn ability_damaging_hit(
    state: &mut State,
    choice: &mut Choice,
    side_ref: &SideReference,
    damage_dealt: i16,
    instructions: &mut StateInstructions,
) {
    let holder = side_ref.get_other_side();
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L191): a frozen target thaws when an attack
    // of Fire type hits it (Showdown's frz onDamagingHit) or one that thaws it (thawsTarget: Scald,
    // Steam Eruption, Hydro Steam, Scorching Sands, Matcha Gotcha -- onAfterMoveSecondary); was
    // never
    {
        let target_side = state.get_side(&holder);
        let thaws = choice.category != MoveCategory::Status
            && (choice.move_type == PokemonType::FIRE || choice.move_id.thaws_target());
        if thaws
            && target_side.get_active_immutable().status == PokemonStatus::FREEZE
            && target_side.get_active_immutable().hp > 0
        {
            let index = target_side.active_index;
            super::generate_instructions::add_remove_status_instructions(
                instructions,
                index,
                holder,
                target_side,
            );
        }
    }
    {
        let (attacking_side, defending_side) = state.get_both_sides(side_ref);
        let attacker = attacking_side.get_active();
        let defender = defending_side.get_active_immutable();
        // (Rocky Helmet: contact, not through Magic Guard / Protective Pads; L94: at least 1)
        if defender.item == Items::ROCKYHELMET
            && choice.flags.contact
            && attacker.hp > 0
            && attacker.ability != Abilities::MAGICGUARD
            && attacker.item != Items::PROTECTIVEPADS
        {
            let amount = cmp::min(cmp::max(attacker.maxhp / 6, 1), attacker.hp);
            attacker.hp -= amount;
            instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *side_ref,
                    damage_amount: amount,
                }));
        }
    }
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    if attacking_side.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
        && attacking_side.get_active_immutable().hp > 0
        && defending_side.get_active_immutable().item != Items::ABILITYSHIELD
    {
        return;
    }
    let charged = defending_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::CHARGE);
    let attacking_pkmn = attacking_side.get_active();
    let defending_pkmn = defending_side.get_active();
    match defending_pkmn.ability {
        // (L151: were secondaries the move got before it: once per move, through a Substitute
        // for Gooey's)
        Abilities::WEAKARMOR if choice.category == MoveCategory::Physical => {
            for (stat, amount) in [
                (PokemonBoostableStat::Defense, -1),
                (PokemonBoostableStat::Speed, 2),
            ] {
                apply_boost_instruction(defending_side, &stat, &amount, &holder, &holder, instructions);
            }
        }
        // (L163: Cute Charm, 3/10 an attraction on a contact attacker -- the volatile's gender
        // check, generate_instructions)
        Abilities::CUTECHARM if choice.flags.contact && attacking_pkmn.hp > 0 => {
            choice.add_or_create_secondaries(Secondary {
                chance: 30.0,
                target: MoveTarget::User,
                effect: Effect::VolatileStatus(PokemonVolatileStatus::ATTRACT),
            });
        }
        // (L193: a Mirror Armor attacker sends it back: foe_drop)
        Abilities::GOOEY | Abilities::TANGLINGHAIR if choice.flags.contact => {
            foe_drop(
                attacking_side,
                side_ref,
                defending_side,
                &holder,
                &PokemonBoostableStat::Speed,
                -1,
                instructions,
            );
        }
        Abilities::STEAMENGINE
            if matches!(choice.move_type, PokemonType::WATER | PokemonType::FIRE) =>
        {
            apply_boost_instruction(
                defending_side,
                &PokemonBoostableStat::Speed,
                &6,
                &holder,
                &holder,
                instructions,
            );
        }
        Abilities::THERMALEXCHANGE if choice.move_type == PokemonType::FIRE => {
            apply_boost_instruction(
                defending_side,
                &PokemonBoostableStat::Attack,
                &1,
                &holder,
                &holder,
                instructions,
            );
        }
        Abilities::WATERCOMPACTION if choice.move_type == PokemonType::WATER => {
            apply_boost_instruction(
                defending_side,
                &PokemonBoostableStat::Defense,
                &2,
                &holder,
                &holder,
                instructions,
            );
        }
        Abilities::JUSTIFIED if choice.move_type == PokemonType::DARK => {
            apply_boost_instruction(
                defending_side,
                &PokemonBoostableStat::Attack,
                &1,
                &holder,
                &holder,
                instructions,
            );
        }
        Abilities::RATTLED
            if matches!(
                choice.move_type,
                PokemonType::BUG | PokemonType::DARK | PokemonType::GHOST
            ) =>
        {
            apply_boost_instruction(
                defending_side,
                &PokemonBoostableStat::Speed,
                &1,
                &holder,
                &holder,
                instructions,
            );
        }
        Abilities::ELECTROMORPHOSIS | Abilities::WINDPOWER
            if defending_pkmn.hp > 0
                && !charged
                && (defending_pkmn.ability == Abilities::ELECTROMORPHOSIS || choice.flags.wind) =>
        {
            defending_side
                .volatile_statuses
                .insert(PokemonVolatileStatus::CHARGE);
            instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref: holder,
                        volatile_status: PokemonVolatileStatus::CHARGE,
                    },
                ));
        }
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L184): Mummy / Lingering Aroma give
        // the attacker their own ability (was Mummy for both), not a cantsuppress one nor through
        // an Ability Shield (Showdown's setAbility); Wandering Spirit swaps (skill_swap)
        Abilities::MUMMY | Abilities::LINGERINGAROMA => {
            let own = defending_pkmn.ability;
            if choice.flags.contact
                && attacking_pkmn.hp > 0
                && attacking_pkmn.ability != own
                && !CANT_SUPPRESS.contains(&attacking_pkmn.ability)
                && attacking_pkmn.item != Items::ABILITYSHIELD
            {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
                        side_ref: *side_ref,
                        ability_change: own as i16 - attacking_pkmn.ability as i16,
                    }));
                attacking_pkmn.ability = own;
            }
        }
        Abilities::WANDERINGSPIRIT => {
            if choice.flags.contact {
                skill_swap(state, side_ref, instructions);
            }
        }
        Abilities::GULPMISSILE => {
            if damage_dealt > 0
                && [PokemonName::CRAMORANTGORGING, PokemonName::CRAMORANTGULPING]
                    .contains(&defending_pkmn.id)
            {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: side_ref.get_other_side(),
                        name_change: PokemonName::CRAMORANT as i16 - defending_pkmn.id as i16,
                    },
                ));

                let damage_dealt = cmp::min(attacking_pkmn.maxhp / 4, attacking_pkmn.hp);
                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: *side_ref,
                        damage_amount: damage_dealt,
                    }));
                attacking_pkmn.hp -= damage_dealt;

                if defending_pkmn.id == PokemonName::CRAMORANTGULPING {
                    defending_pkmn.id = PokemonName::CRAMORANT;
                    apply_boost_instruction(
                        attacking_side,
                        &PokemonBoostableStat::Defense,
                        &-1,
                        &side_ref.get_other_side(),
                        side_ref,
                        instructions,
                    );
                } else if defending_pkmn.id == PokemonName::CRAMORANTGORGING {
                    defending_pkmn.id = PokemonName::CRAMORANT;
                    choice.add_or_create_secondaries(Secondary {
                        chance: 100.0,
                        target: MoveTarget::User,
                        effect: Effect::Status(PokemonStatus::PARALYZE),
                    })
                }
            }
        }
        Abilities::COLORCHANGE => {
            if damage_dealt > 0
                && defending_pkmn.hp != 0
                && !defending_pkmn.has_type(&choice.move_type)
            {
                let change_type_instruction = Instruction::ChangeType(ChangeType {
                    side_ref: side_ref.get_other_side(),
                    new_types: (choice.move_type, PokemonType::TYPELESS),
                    old_types: defending_pkmn.types,
                });
                defending_pkmn.types = (choice.move_type, PokemonType::TYPELESS);
                instructions.instruction_list.push(change_type_instruction);
            }
        }
        Abilities::STAMINA => {
            if damage_dealt > 0 && defending_pkmn.hp != 0 {
                apply_boost_instruction(
                    defending_side,
                    &PokemonBoostableStat::Defense,
                    &1,
                    side_ref,
                    &side_ref.get_other_side(),
                    instructions,
                );
            }
        }
        Abilities::COTTONDOWN => {
            if damage_dealt > 0 {
                foe_drop(
                    attacking_side,
                    side_ref,
                    defending_side,
                    &side_ref.get_other_side(),
                    &PokemonBoostableStat::Speed,
                    -1,
                    instructions,
                );
            }
        }
        Abilities::SANDSPIT => {
            if damage_dealt > 0 && state.weather.weather_type != Weather::SAND {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::SAND,
                        new_weather_turns_remaining: WEATHER_ABILITY_TURNS,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::SAND;
                state.weather.turns_remaining = WEATHER_ABILITY_TURNS;
            }
        }
        Abilities::SEEDSOWER => {
            if damage_dealt > 0 && state.terrain.terrain_type != Terrain::GRASSYTERRAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeTerrain(ChangeTerrain {
                        new_terrain: Terrain::GRASSYTERRAIN,
                        new_terrain_turns_remaining: 5,
                        previous_terrain: state.terrain.terrain_type,
                        previous_terrain_turns_remaining: state.terrain.turns_remaining,
                    }));
                state.terrain.terrain_type = Terrain::GRASSYTERRAIN;
                state.terrain.turns_remaining = 5;
            }
        }
        Abilities::TOXICDEBRIS => {
            // Not complete: Toxic Spikes are not applied if a substitute is hit
            if damage_dealt > 0
                && choice.category == MoveCategory::Physical
                && attacking_side.side_conditions.toxic_spikes < 2
            {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: *side_ref,
                            side_condition: PokemonSideCondition::ToxicSpikes,
                            amount: 1,
                        },
                    ));
                attacking_side.side_conditions.toxic_spikes += 1;
            }
        }
        Abilities::BERSERK => {
            if damage_dealt > 0
                && defending_pkmn.hp < defending_pkmn.maxhp / 2
                && defending_pkmn.hp + damage_dealt >= defending_pkmn.maxhp / 2
            {
                apply_boost_instruction(
                    defending_side,
                    &PokemonBoostableStat::SpecialAttack,
                    &1,
                    &side_ref.get_other_side(),
                    &side_ref.get_other_side(),
                    instructions,
                );
            }
        }
        Abilities::ROUGHSKIN | Abilities::IRONBARBS => {
            // (L94: not through Magic Guard)
            if damage_dealt > 0
                && choice.flags.contact
                && attacking_pkmn.ability != Abilities::MAGICGUARD
            {
                // (L113: at least 1)
                let damage_dealt =
                    cmp::min(cmp::max(attacking_pkmn.maxhp / 8, 1), attacking_pkmn.hp);

                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: *side_ref,
                        damage_amount: damage_dealt,
                    }));
                attacking_pkmn.hp -= damage_dealt;
            }
        }
        Abilities::AFTERMATH => {
            if damage_dealt > 0
                && defending_side.get_active_immutable().hp == 0
                && choice.flags.contact
            {
                let damage_dealt = cmp::min(attacking_pkmn.maxhp / 4, attacking_pkmn.hp);
                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: *side_ref,
                        damage_amount: damage_dealt,
                    }));
                attacking_pkmn.hp -= damage_dealt;
            }
        }
        Abilities::INNARDSOUT => {
            if damage_dealt > 0 && defending_side.get_active_immutable().hp == 0 {
                let damage_dealt = cmp::min(damage_dealt, attacking_pkmn.hp);
                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: *side_ref,
                        damage_amount: damage_dealt,
                    }));
                attacking_pkmn.hp -= damage_dealt;
            }
        }
        Abilities::PERISHBODY => {
            if damage_dealt > 0 && choice.flags.contact {
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
        }
        _ => {}
    }
}

pub fn ability_after_damage_hit(
    state: &mut State,
    choice: &mut Choice,
    side_ref: &SideReference,
    damage_dealt: i16,
    instructions: &mut StateInstructions,
) {
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    let active_pkmn = attacking_side.get_active();
    // (L146: a holder this hit made faint no longer suppresses: Moxie after the KO)
    if (defending_side.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
        && defending_side.get_active_immutable().hp > 0
        && active_pkmn.item != Items::ABILITYSHIELD)
        || active_pkmn.ability == Abilities::NEUTRALIZINGGAS
    {
        return;
    }
    match active_pkmn.ability {
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L111): Greninja-Bond only, once per
        // battle (a used one has base ability none: the harness / our state construction)
        Abilities::BATTLEBOND => {
            if damage_dealt > 0
                && defending_side.get_active_immutable().hp == 0
                && active_pkmn.id == PokemonName::GRENINJABOND
                && active_pkmn.hp > 0
                && active_pkmn.base_ability != Abilities::NONE
            {
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::Attack,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::SpecialAttack,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::Speed,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
                // (L184: used now)
                use_once(attacking_side.get_active(), side_ref, instructions);
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L78): Pickpocket is the target's
        // (generate_instructions::run_move), not its user's
        // (L151: Magician: magician_after_move, Showdown's onAfterMoveSecondarySelf)
        Abilities::MOXIE | Abilities::CHILLINGNEIGH | Abilities::ASONEGLASTRIER => {
            if damage_dealt > 0 && defending_side.get_active_immutable().hp == 0 {
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::Attack,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
            }
        }
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L194): Soul-Heart, Sp. Atk +1 for a
        // faint (Showdown's onAnyFaint: here the foe its hit knocked out; a hazard's, the switch-in
        // -- generate_instructions_from_switch); was nothing
        Abilities::GRIMNEIGH | Abilities::ASONESPECTRIER | Abilities::SOULHEART => {
            if damage_dealt > 0 && defending_side.get_active_immutable().hp == 0 {
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::SpecialAttack,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
            }
        }
        Abilities::BEASTBOOST | Abilities::EELEVATE => {
            if damage_dealt > 0 && defending_side.get_active_immutable().hp == 0 {
                let highest_stat = &attacking_side.calculate_highest_stat();
                apply_boost_instruction(
                    attacking_side,
                    highest_stat,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
            }
        }
        _ => {}
    }
}

pub fn ability_on_switch_out(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    let active_pkmn = attacking_side.get_active();
    if defending_side.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
        && active_pkmn.item != Items::ABILITYSHIELD
    {
        return;
    }
    match active_pkmn.ability {
        Abilities::GULPMISSILE if active_pkmn.base_ability == Abilities::GULPMISSILE => {
            if active_pkmn.id != PokemonName::CRAMORANT {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::CRAMORANT as i16 - active_pkmn.id as i16,
                    },
                ));
                active_pkmn.id = PokemonName::CRAMORANT;
            }
        }
        Abilities::ZEROTOHERO => {
            if active_pkmn.id == PokemonName::PALAFIN {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::PALAFINHERO as i16 - active_pkmn.id as i16,
                    },
                ));
                let from = active_pkmn.id;
                active_pkmn.id = PokemonName::PALAFINHERO;
                active_pkmn.recalculate_stats(from, side_ref, instructions);
            }
        }
        Abilities::HUNGERSWITCH => {
            if active_pkmn.id == PokemonName::MORPEKOHANGRY && !active_pkmn.terastallized {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::MORPEKO as i16 - active_pkmn.id as i16,
                    },
                ));
                active_pkmn.id = PokemonName::MORPEKO;
            }
        }
        Abilities::NATURALCURE => {
            if active_pkmn.status != PokemonStatus::NONE {
                let status = active_pkmn.status.clone();
                active_pkmn.status = PokemonStatus::NONE;
                instructions
                    .instruction_list
                    .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                        side_ref: *side_ref,
                        pokemon_index: attacking_side.active_index,
                        old_status: status,
                        new_status: PokemonStatus::NONE,
                    }));
            }
        }
        Abilities::REGENERATOR => {
            let hp_recovered = cmp::min(active_pkmn.maxhp / 3, active_pkmn.maxhp - active_pkmn.hp);

            if hp_recovered > 0 && active_pkmn.hp > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::Heal(HealInstruction {
                        side_ref: *side_ref,
                        heal_amount: hp_recovered,
                    }));
                active_pkmn.hp += hp_recovered;
            }
        }
        Abilities::PRIMORDIALSEA => {
            if state.weather.weather_type == Weather::HEAVYRAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::NONE,
                        new_weather_turns_remaining: -1,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::NONE;
                state.weather.turns_remaining = -1;
            }
        }
        Abilities::DESOLATELAND => {
            if state.weather.weather_type == Weather::HARSHSUN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::NONE,
                        new_weather_turns_remaining: -1,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::NONE;
                state.weather.turns_remaining = -1;
            }
        }
        _ => {}
    }

    // revert ability on switch-out to base_ability if they are not the same
    let active_pkmn = state.get_side(side_ref).get_active();
    // alpha-poke patch (2026-10-16, L18): a used Dauntless Shield (base ability none) stays (L184:
    // any once-per-battle one)
    if active_pkmn.ability != active_pkmn.base_ability && !used_once(active_pkmn) {
        instructions
            .instruction_list
            .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
                side_ref: *side_ref,
                ability_change: active_pkmn.base_ability as i16 - active_pkmn.ability as i16,
            }));
        active_pkmn.ability = active_pkmn.base_ability;
    }
}

pub fn ability_end_of_turn(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
    before_status: bool,
    // (L191: this branch's Shed Skin cures: generate_instructions::EotRolls)
    shed_skin: bool,
) {
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L19): no healing under Heal Block
    let heal_blocked = attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::HEALBLOCK);
    let active_pkmn = attacking_side.get_active();
    // alpha-poke patch (2026-10-16): the weather abilities (Showdown's weather residual, order 1)
    // and Hydration / Shed Skin (5) come before the status damage (9-10), the rest after it
    let early = matches!(
        active_pkmn.ability,
        Abilities::SOLARPOWER
            | Abilities::ICEBODY
            | Abilities::RAINDISH
            | Abilities::DRYSKIN
            | Abilities::HYDRATION
            | Abilities::SHEDSKIN
    );
    if early != before_status {
        return;
    }
    if defending_side.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
        && active_pkmn.item != Items::ABILITYSHIELD
    {
        return;
    }
    match active_pkmn.ability {
        Abilities::HUNGERSWITCH => {
            if active_pkmn.id == PokemonName::MORPEKO && !active_pkmn.terastallized {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::MORPEKOHANGRY as i16 - active_pkmn.id as i16,
                    },
                ));
                active_pkmn.id = PokemonName::MORPEKOHANGRY;
            } else if active_pkmn.id == PokemonName::MORPEKOHANGRY && !active_pkmn.terastallized {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::MORPEKO as i16 - active_pkmn.id as i16,
                    },
                ));
                active_pkmn.id = PokemonName::MORPEKO;
            }
        }
        Abilities::SHIELDSDOWN => {
            if active_pkmn.hp <= active_pkmn.maxhp / 2
                && active_pkmn.id == PokemonName::MINIORMETEOR
            {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::MINIOR as i16 - active_pkmn.id as i16,
                    },
                ));
                let from = active_pkmn.id;
                active_pkmn.id = PokemonName::MINIOR;
                active_pkmn.recalculate_stats(from, side_ref, instructions);
            }
            if active_pkmn.hp > active_pkmn.maxhp / 2 && active_pkmn.id != PokemonName::MINIORMETEOR
            {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::MINIORMETEOR as i16 - active_pkmn.id as i16,
                    },
                ));
                let from = active_pkmn.id;
                active_pkmn.id = PokemonName::MINIORMETEOR;
                active_pkmn.recalculate_stats(from, side_ref, instructions);
            }
        }
        Abilities::SCHOOLING => {
            if active_pkmn.hp <= active_pkmn.maxhp / 4
                && active_pkmn.id == PokemonName::WISHIWASHISCHOOL
            {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::WISHIWASHI as i16 - active_pkmn.id as i16,
                    },
                ));
                let from = active_pkmn.id;
                active_pkmn.id = PokemonName::WISHIWASHI;
                active_pkmn.recalculate_stats(from, side_ref, instructions);
            }
            if active_pkmn.hp > active_pkmn.maxhp / 4 && active_pkmn.id == PokemonName::WISHIWASHI {
                instructions.instruction_list.push(Instruction::FormeChange(
                    FormeChangeInstruction {
                        side_ref: *side_ref,
                        name_change: PokemonName::WISHIWASHISCHOOL as i16 - active_pkmn.id as i16,
                    },
                ));
                let from = active_pkmn.id;
                active_pkmn.id = PokemonName::WISHIWASHISCHOOL;
                active_pkmn.recalculate_stats(from, side_ref, instructions);
            }
        }
        Abilities::BADDREAMS => {
            let defender = defending_side.get_active();
            if defender.status == PokemonStatus::SLEEP {
                let damage_dealt = cmp::min(defender.maxhp / 8, defender.hp);
                instructions
                    .instruction_list
                    .push(Instruction::Damage(DamageInstruction {
                        side_ref: side_ref.get_other_side(),
                        damage_amount: damage_dealt,
                    }));
                defender.hp -= damage_dealt;
            }
        }
        Abilities::SOLARPOWER => {
            if state.weather_is_active(&Weather::HARSHSUN) || state.weather_is_active(&Weather::SUN)
            {
                let active_pkmn = state.get_side(side_ref).get_active();
                let damage_dealt =
                    cmp::min(active_pkmn.maxhp / 8, active_pkmn.maxhp - active_pkmn.hp);
                if damage_dealt > 0 {
                    instructions
                        .instruction_list
                        .push(Instruction::Damage(DamageInstruction {
                            side_ref: *side_ref,
                            damage_amount: damage_dealt,
                        }));
                    active_pkmn.hp -= damage_dealt;
                }
            }
        }
        Abilities::ICEBODY => {
            // (L154: in snow too)
            if state.weather_is_active(&Weather::HAIL) || state.weather_is_active(&Weather::SNOW) {
                let active_pkmn = state.get_side(side_ref).get_active();
                let health_recovered =
                    cmp::min(active_pkmn.maxhp / 16, active_pkmn.maxhp - active_pkmn.hp);
                if health_recovered > 0 && !heal_blocked {
                    instructions
                        .instruction_list
                        .push(Instruction::Heal(HealInstruction {
                            side_ref: *side_ref,
                            heal_amount: health_recovered,
                        }));
                    active_pkmn.hp += health_recovered;
                }
            }
        }
        // alpha-poke patch (2026-10-16, L12b): healed with the status damage now
        Abilities::POISONHEAL => {}
        Abilities::SPEEDBOOST => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L37): not at the end of the turn it
            // came in (Showdown's activeTurns: a switch of this side among the turn's
            // instructions; a replacement after a faint is its own decision, a turn before)
            let came_in = instructions
                .instruction_list
                .iter()
                .any(|i| matches!(i, Instruction::Switch(s) if s.side_ref == *side_ref));
            if attacking_side.speed_boost < 6 && !came_in {
                let ins = Instruction::Boost(BoostInstruction {
                    side_ref: side_ref.clone(),
                    stat: PokemonBoostableStat::Speed,
                    amount: 1,
                });
                attacking_side.speed_boost += 1;
                instructions.instruction_list.push(ins);
            }
        }
        Abilities::RAINDISH => {
            if state.weather_is_active(&Weather::RAIN)
                || state.weather_is_active(&Weather::HEAVYRAIN)
            {
                let active_pkmn = state.get_side(side_ref).get_active();
                let health_recovered =
                    cmp::min(active_pkmn.maxhp / 16, active_pkmn.maxhp - active_pkmn.hp);
                if health_recovered > 0 && !heal_blocked {
                    instructions
                        .instruction_list
                        .push(Instruction::Heal(HealInstruction {
                            side_ref: *side_ref,
                            heal_amount: health_recovered,
                        }));
                    active_pkmn.hp += health_recovered;
                }
            }
        }
        Abilities::DRYSKIN => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L100): heavy rain heals too, sun /
            // harsh sun take 1/8 (Showdown's onWeather)
            if state.weather_is_active(&Weather::RAIN)
                || state.weather_is_active(&Weather::HEAVYRAIN)
            {
                let active_pkmn = state.get_side(side_ref).get_active();
                if active_pkmn.hp < active_pkmn.maxhp && !heal_blocked {
                    let heal_amount =
                        cmp::min(active_pkmn.maxhp / 8, active_pkmn.maxhp - active_pkmn.hp);
                    let ins = Instruction::Heal(HealInstruction {
                        side_ref: side_ref.clone(),
                        heal_amount: heal_amount,
                    });
                    active_pkmn.hp += heal_amount;
                    instructions.instruction_list.push(ins);
                }
            } else if state.weather_is_active(&Weather::SUN)
                || state.weather_is_active(&Weather::HARSHSUN)
            {
                let active_pkmn = state.get_side(side_ref).get_active();
                let damage_amount = cmp::min(active_pkmn.maxhp / 8, active_pkmn.hp);
                if damage_amount > 0 {
                    active_pkmn.hp -= damage_amount;
                    instructions
                        .instruction_list
                        .push(Instruction::Damage(DamageInstruction {
                            side_ref: *side_ref,
                            damage_amount,
                        }));
                }
            }
        }
        Abilities::HYDRATION => {
            if active_pkmn.status != PokemonStatus::NONE
                && (state.weather_is_active(&Weather::RAIN)
                    || state.weather_is_active(&Weather::HEAVYRAIN))
            {
                let attacking_side = state.get_side(side_ref);
                let active_index = attacking_side.active_index;
                let active_pkmn = attacking_side.get_active();

                add_remove_status_instructions(
                    instructions,
                    active_index,
                    *side_ref,
                    attacking_side,
                );
            }
        }
        // Shed skin only has a 1/3 chance of activating at the end of the turn
        // but I'm not going to branch on that here
        Abilities::SHEDSKIN => {
            if active_pkmn.status != PokemonStatus::NONE && shed_skin {
                let attacking_side = state.get_side(side_ref);
                let active_index = attacking_side.active_index;
                let active_pkmn = attacking_side.get_active();

                add_remove_status_instructions(
                    instructions,
                    active_index,
                    *side_ref,
                    attacking_side,
                );
            }
        }
        _ => {}
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L148): Ice Face comes back in hail / snow
// (Showdown's onStart -- the switch-in -- and onWeatherChange: generate_instructions'
// field_change_events; not while the weather goes on); before, a switch-in in snow changed any
// Eiscue's forme (the condition's precedence)
pub fn ice_face_in_snow(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let snow = state.weather_is_active(&Weather::HAIL) || state.weather_is_active(&Weather::SNOW);
    let active_pkmn = state.get_side(side_ref).get_active();
    if active_pkmn.ability == Abilities::ICEFACE
        && active_pkmn.id == PokemonName::EISCUENOICE
        && active_pkmn.hp > 0
        && snow
    {
        instructions
            .instruction_list
            .push(Instruction::FormeChange(FormeChangeInstruction {
                side_ref: *side_ref,
                name_change: PokemonName::EISCUE as i16 - active_pkmn.id as i16,
            }));
        let from = active_pkmn.id;
        active_pkmn.id = PokemonName::EISCUE;
        active_pkmn.recalculate_stats(from, side_ref, instructions);
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L184): Trace as Showdown's: it copies the
// foe's ability unless that one is notrace (Protosynthesis, Trace, ...) or the foe has fainted,
// and then keeps seeking (its onUpdate: trace_update, in the Update pass) -- the next foe's on its
// entry; nothing with an Ability Shield. Was the foe's ability whatever it was, fainted or notrace
fn trace_copy(state: &mut State, side_ref: &SideReference, instructions: &mut StateInstructions) -> bool {
    let (side, foe) = state.get_both_sides(side_ref);
    let me = side.get_active();
    let target = foe.get_active_immutable();
    if me.ability != Abilities::TRACE
        || me.hp == 0
        || me.item == Items::ABILITYSHIELD
        || target.hp == 0
        || NO_TRACE.contains(&target.ability)
        || target.ability == Abilities::NONE
    {
        return false;
    }
    instructions
        .instruction_list
        .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
            side_ref: *side_ref,
            ability_change: target.ability as i16 - me.ability as i16,
        }));
    me.ability = target.ability;
    true
}

// (the copied ability starts: Showdown's setAbility)
pub fn trace_update(state: &mut State, side_ref: &SideReference, instructions: &mut StateInstructions) {
    if trace_copy(state, side_ref, instructions) {
        ability_on_switch_in(state, side_ref, instructions);
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L195): a permanent forme change (Showdown's
// formeChange(..., isPermanent): the species, its ability as the base ability too, the stats by
// their change, updateMaxHp) -- Tera Shift's Terapagos-Terastal, the tera's Terapagos-Stellar
pub fn permanent_forme_change(
    state: &mut State,
    side_ref: &SideReference,
    to: PokemonName,
    ability: Abilities,
    instructions: &mut StateInstructions,
) {
    let active = state.get_side(side_ref).get_active();
    let from = active.id;
    instructions
        .instruction_list
        .push(Instruction::FormeChange(FormeChangeInstruction {
            side_ref: *side_ref,
            name_change: to as i16 - from as i16,
        }));
    active.id = to;
    if active.ability != ability {
        instructions
            .instruction_list
            .push(Instruction::ChangeAbility(ChangeAbilityInstruction {
                side_ref: *side_ref,
                ability_change: ability as i16 - active.ability as i16,
            }));
        active.ability = ability;
    }
    if active.base_ability != ability {
        instructions
            .instruction_list
            .push(Instruction::ChangeBaseAbility(ChangeAbilityInstruction {
                side_ref: *side_ref,
                ability_change: ability as i16 - active.base_ability as i16,
            }));
        active.base_ability = ability;
    }
    active.recalculate_stats(from, side_ref, instructions);
    active.update_max_hp(from, side_ref, instructions);
}

pub fn ability_on_switch_in(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L36): Imposter transforms into the foe (L172:
    // the copied ability starts, transform_into)
    {
        let (side, foe) = state.get_both_sides_immutable(side_ref);
        let me = side.get_active_immutable();
        if me.ability == Abilities::IMPOSTER
            && !(foe.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
                && me.item != Items::ABILITYSHIELD)
        {
            super::generate_instructions::transform_into(state, side_ref, instructions);
            return;
        }
    }
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    let active_pkmn = attacking_side.get_active();
    let defending_pkmn = defending_side.get_active_immutable();
    if defending_pkmn.ability == Abilities::NEUTRALIZINGGAS
        && active_pkmn.item != Items::ABILITYSHIELD
    {
        return;
    }

    // (L195: Tera Shift first, its onSwitchInPriority 2: Terapagos-Terastal and its Tera Shell)
    {
        let me = state.get_side_immutable(side_ref).get_active_immutable();
        if me.ability == Abilities::TERASHIFT && me.id == PokemonName::TERAPAGOS {
            permanent_forme_change(
                state,
                side_ref,
                PokemonName::TERAPAGOSTERASTAL,
                Abilities::TERASHELL,
                instructions,
            );
            return;
        }
    }
    // trace copying an ability needs to happen before the ability check to activate on switch-in
    // e.g. tracing intimidate will activate intimidate
    trace_copy(state, side_ref, instructions);
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    let active_pkmn = attacking_side.get_active();
    let defending_pkmn = defending_side.get_active_immutable();

    match active_pkmn.ability {
        Abilities::ICEFACE => ice_face_in_snow(state, side_ref, instructions),
        // (L141)
        Abilities::PROTOSYNTHESIS | Abilities::QUARKDRIVE => {
            paradox_update(state, side_ref, instructions);
        }
        Abilities::EMBODYASPECTTEAL => {
            apply_boost_instruction(
                attacking_side,
                &PokemonBoostableStat::Speed,
                &1,
                side_ref,
                side_ref,
                instructions,
            );
        }
        Abilities::EMBODYASPECTWELLSPRING => {
            apply_boost_instruction(
                attacking_side,
                &PokemonBoostableStat::SpecialDefense,
                &1,
                side_ref,
                side_ref,
                instructions,
            );
        }
        Abilities::EMBODYASPECTCORNERSTONE => {
            apply_boost_instruction(
                attacking_side,
                &PokemonBoostableStat::Defense,
                &1,
                side_ref,
                side_ref,
                instructions,
            );
        }
        Abilities::EMBODYASPECTHEARTHFLAME => {
            apply_boost_instruction(
                attacking_side,
                &PokemonBoostableStat::Attack,
                &1,
                side_ref,
                side_ref,
                instructions,
            );
        }
        // (L184: once per battle, as Dauntless Shield)
        Abilities::INTREPIDSWORD if active_pkmn.base_ability != Abilities::NONE => {
            // no need to check for boost at +6 because we are switching in
            attacking_side.attack_boost += 1;
            instructions
                .instruction_list
                .push(Instruction::Boost(BoostInstruction {
                    side_ref: *side_ref,
                    stat: PokemonBoostableStat::Attack,
                    amount: 1,
                }));
            use_once(attacking_side.get_active(), side_ref, instructions);
        }
        Abilities::SLOWSTART => {
            instructions
                .instruction_list
                .push(Instruction::ApplyVolatileStatus(
                    ApplyVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::SLOWSTART,
                    },
                ));
            instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: *side_ref,
                        volatile_status: PokemonVolatileStatus::SLOWSTART,
                        amount: 6 - attacking_side.volatile_status_durations.slowstart,
                    },
                ));
            attacking_side
                .volatile_statuses
                .insert(PokemonVolatileStatus::SLOWSTART);
            attacking_side.volatile_status_durations.slowstart = 6;
        }
        Abilities::DROUGHT | Abilities::ORICHALCUMPULSE => {
            if state.weather.weather_type != Weather::SUN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::SUN,
                        new_weather_turns_remaining: WEATHER_ABILITY_TURNS,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::SUN;
                state.weather.turns_remaining = WEATHER_ABILITY_TURNS;
            }
        }
        Abilities::DESOLATELAND => {
            if state.weather.weather_type != Weather::HARSHSUN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::HARSHSUN,
                        new_weather_turns_remaining: -1,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::HARSHSUN;
                state.weather.turns_remaining = -1;
            }
        }
        Abilities::MISTYSURGE => {
            if state.terrain.terrain_type != Terrain::MISTYTERRAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeTerrain(ChangeTerrain {
                        new_terrain: Terrain::MISTYTERRAIN,
                        new_terrain_turns_remaining: 5,
                        previous_terrain: state.terrain.terrain_type,
                        previous_terrain_turns_remaining: state.terrain.turns_remaining,
                    }));
                state.terrain.terrain_type = Terrain::MISTYTERRAIN;
                state.terrain.turns_remaining = 5;
            }
        }
        Abilities::SANDSTREAM => {
            if state.weather.weather_type != Weather::SAND {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::SAND,
                        new_weather_turns_remaining: WEATHER_ABILITY_TURNS,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::SAND;
                state.weather.turns_remaining = WEATHER_ABILITY_TURNS;
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L21): Mirror Armor reflects Intimidate
        Abilities::INTIMIDATE
            if defending_side.get_active_immutable().ability == Abilities::MIRRORARMOR
                && !defending_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::SUBSTITUTE) =>
        {
            apply_boost_instruction(
                attacking_side,
                &PokemonBoostableStat::Attack,
                &-1,
                &side_ref.get_other_side(),
                side_ref,
                instructions,
            );
        }
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L149): Showdown's Intimidate onStart and
        // the foe's boost() handlers for it: a Substitute, Own Tempo / Oblivious / Inner Focus /
        // Scrappy stop it, Guard Dog raises its Attack instead, Mirror Armor reflects it; after a
        // drop (Contrary's raise too), Adrenaline Orb and Rattled raise the Speed
        Abilities::INTIMIDATE => {
            let foe_ref = side_ref.get_other_side();
            let defender = defending_side.get_active_immutable();
            let ability = defender.ability;
            if defending_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::SUBSTITUTE)
                || matches!(
                    ability,
                    Abilities::OWNTEMPO
                        | Abilities::OBLIVIOUS
                        | Abilities::INNERFOCUS
                        | Abilities::SCRAPPY
                )
            {
            } else if ability == Abilities::GUARDDOG {
                apply_boost_instruction(
                    defending_side,
                    &PokemonBoostableStat::Attack,
                    &1,
                    &foe_ref,
                    &foe_ref,
                    instructions,
                );
            } else if ability == Abilities::MIRRORARMOR {
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::Attack,
                    &-1,
                    &foe_ref,
                    side_ref,
                    instructions,
                );
            } else if apply_boost_instruction(
                defending_side,
                &PokemonBoostableStat::Attack,
                &-1,
                side_ref,
                &foe_ref,
                instructions,
            ) {
                let defender = defending_side.get_active_immutable();
                if defender.item == Items::ADRENALINEORB
                    && apply_boost_instruction(
                        defending_side,
                        &PokemonBoostableStat::Speed,
                        &1,
                        &foe_ref,
                        &foe_ref,
                        instructions,
                    )
                {
                    let adrenaline_orb_item_instruction =
                        Instruction::ChangeItem(ChangeItemInstruction {
                            side_ref: foe_ref,
                            current_item: Items::ADRENALINEORB,
                            new_item: Items::NONE,
                        });
                    state.apply_one_instruction(&adrenaline_orb_item_instruction);
                    instructions
                        .instruction_list
                        .push(adrenaline_orb_item_instruction);
                    // (L178: used up, its last item)
                    super::items::set_last_item(
                        state.get_side(&foe_ref).get_active(),
                        foe_ref,
                        Items::ADRENALINEORB,
                        instructions,
                    );
                } else if ability == Abilities::RATTLED {
                    apply_boost_instruction(
                        state.get_side(&foe_ref),
                        &PokemonBoostableStat::Speed,
                        &1,
                        &foe_ref,
                        &foe_ref,
                        instructions,
                    );
                }
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L18): once per battle (Gen 9); a used
        // one has base ability none (agents/engine_state.py); before, at every switch-in
        // (L106: also one Skill Swap gave it, its base ability another)
        Abilities::DAUNTLESSSHIELD if active_pkmn.base_ability != Abilities::NONE => {
            // no need to check for boost at +6 because we are switching in
            attacking_side.defense_boost += 1;
            instructions
                .instruction_list
                .push(Instruction::Boost(BoostInstruction {
                    side_ref: *side_ref,
                    stat: PokemonBoostableStat::Defense,
                    amount: 1,
                }));
            // alpha-poke patch (2026-10-17, doc/engine-diff.md L181): used now (Showdown's
            // shieldBoost, once per battle): its base ability none, the harness's encoding too
            use_once(attacking_side.get_active(), side_ref, instructions);
        }
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L172): Supersweet Syrup, once per battle
        // (a used one: base ability none, as Dauntless Shield's): the foe's evasion -1, not through
        // a Substitute (Showdown's onStart; a foe's drop: Clear Body, Defiant, ...)
        Abilities::SUPERSWEETSYRUP if active_pkmn.base_ability != Abilities::NONE => {
            if defending_side.get_active_immutable().hp > 0
                && !defending_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::SUBSTITUTE)
            {
                super::generate_instructions::apply_boost_instruction(
                    defending_side,
                    &PokemonBoostableStat::Evasion,
                    &-1,
                    side_ref,
                    &side_ref.get_other_side(),
                    instructions,
                );
            }
            // (L184: used now, whatever the foe)
            use_once(attacking_side.get_active(), side_ref, instructions);
        }
        Abilities::GRASSYSURGE => {
            if state.terrain.terrain_type != Terrain::GRASSYTERRAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeTerrain(ChangeTerrain {
                        new_terrain: Terrain::GRASSYTERRAIN,
                        new_terrain_turns_remaining: 5,
                        previous_terrain: state.terrain.terrain_type,
                        previous_terrain_turns_remaining: state.terrain.turns_remaining,
                    }));
                state.terrain.terrain_type = Terrain::GRASSYTERRAIN;
                state.terrain.turns_remaining = 5;
            }
        }
        Abilities::ELECTRICSURGE | Abilities::HADRONENGINE => {
            if state.terrain.terrain_type != Terrain::ELECTRICTERRAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeTerrain(ChangeTerrain {
                        new_terrain: Terrain::ELECTRICTERRAIN,
                        new_terrain_turns_remaining: 5,
                        previous_terrain: state.terrain.terrain_type,
                        previous_terrain_turns_remaining: state.terrain.turns_remaining,
                    }));
                state.terrain.terrain_type = Terrain::ELECTRICTERRAIN;
                state.terrain.turns_remaining = 5;
            }
        }
        Abilities::DOWNLOAD => {
            if defending_side.calculate_boosted_stat(PokemonBoostableStat::Defense)
                < defending_side.calculate_boosted_stat(PokemonBoostableStat::SpecialDefense)
            {
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::Attack,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
            } else {
                apply_boost_instruction(
                    attacking_side,
                    &PokemonBoostableStat::SpecialAttack,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                );
            }
        }
        Abilities::PRIMORDIALSEA => {
            if state.weather.weather_type != Weather::HEAVYRAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::HEAVYRAIN,
                        new_weather_turns_remaining: -1,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::HEAVYRAIN;
                state.weather.turns_remaining = -1;
            }
        }
        Abilities::SCREENCLEANER => {
            if state.side_one.side_conditions.reflect > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: SideReference::SideOne,
                            side_condition: PokemonSideCondition::Reflect,
                            amount: -1 * state.side_one.side_conditions.reflect,
                        },
                    ));
                state.side_one.side_conditions.reflect = 0;
            }
            if state.side_two.side_conditions.reflect > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: SideReference::SideTwo,
                            side_condition: PokemonSideCondition::Reflect,
                            amount: -1 * state.side_two.side_conditions.reflect,
                        },
                    ));
                state.side_two.side_conditions.reflect = 0;
            }
            if state.side_one.side_conditions.light_screen > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: SideReference::SideOne,
                            side_condition: PokemonSideCondition::LightScreen,
                            amount: -1 * state.side_one.side_conditions.light_screen,
                        },
                    ));
                state.side_one.side_conditions.light_screen = 0;
            }
            if state.side_two.side_conditions.light_screen > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: SideReference::SideTwo,
                            side_condition: PokemonSideCondition::LightScreen,
                            amount: -1 * state.side_two.side_conditions.light_screen,
                        },
                    ));
                state.side_two.side_conditions.light_screen = 0;
            }
            if state.side_one.side_conditions.aurora_veil > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: SideReference::SideOne,
                            side_condition: PokemonSideCondition::AuroraVeil,
                            amount: -1 * state.side_one.side_conditions.aurora_veil,
                        },
                    ));
                state.side_one.side_conditions.aurora_veil = 0;
            }
            if state.side_two.side_conditions.aurora_veil > 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeSideCondition(
                        ChangeSideConditionInstruction {
                            side_ref: SideReference::SideTwo,
                            side_condition: PokemonSideCondition::AuroraVeil,
                            amount: -1 * state.side_two.side_conditions.aurora_veil,
                        },
                    ));
                state.side_two.side_conditions.aurora_veil = 0;
            }
        }
        Abilities::SNOWWARNING => {
            #[cfg(any(feature = "gen9", feature = "champions"))]
            let weather_type = Weather::SNOW;
            #[cfg(not(any(feature = "gen9", feature = "champions")))]
            let weather_type = Weather::HAIL;

            if state.weather.weather_type != weather_type {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: weather_type,
                        new_weather_turns_remaining: WEATHER_ABILITY_TURNS,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = weather_type;
                state.weather.turns_remaining = WEATHER_ABILITY_TURNS;
            }
        }
        Abilities::PSYCHICSURGE => {
            if state.terrain.terrain_type != Terrain::PSYCHICTERRAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeTerrain(ChangeTerrain {
                        new_terrain: Terrain::PSYCHICTERRAIN,
                        new_terrain_turns_remaining: 5,
                        previous_terrain: state.terrain.terrain_type,
                        previous_terrain_turns_remaining: state.terrain.turns_remaining,
                    }));
                state.terrain.terrain_type = Terrain::PSYCHICTERRAIN;
                state.terrain.turns_remaining = 5;
            }
        }
        Abilities::DRIZZLE => {
            if state.weather.weather_type != Weather::RAIN {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeather(ChangeWeather {
                        new_weather: Weather::RAIN,
                        new_weather_turns_remaining: WEATHER_ABILITY_TURNS,
                        previous_weather: state.weather.weather_type,
                        previous_weather_turns_remaining: state.weather.turns_remaining,
                    }));
                state.weather.weather_type = Weather::RAIN;
                state.weather.turns_remaining = WEATHER_ABILITY_TURNS;
            }
        }
        _ => {}
    }
}

pub fn ability_modify_attack_being_used(
    state: &State,
    attacker_choice: &mut Choice,
    defender_choice: &Choice,
    attacking_side_ref: &SideReference,
) {
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);
    let attacking_pkmn = attacking_side.get_active_immutable();
    if defending_side.get_active_immutable().ability == Abilities::NEUTRALIZINGGAS
        && attacking_pkmn.item != Items::ABILITYSHIELD
    {
        return;
    }
    match attacking_pkmn.ability {
        #[cfg(any(
            feature = "champions",
            feature = "gen9",
            feature = "gen8",
            feature = "gen7"
        ))]
        Abilities::PRANKSTER => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L26): only a move aimed at the
            // Dark-type target fails, not one on the user (Reflect) or a side / the field
            // (hazards, weather, terrain, Trick Room, ...: their data target is "Opponent" too);
            // before, any status move failed
            if attacker_choice.category == MoveCategory::Status
                && attacker_choice.target == MoveTarget::Opponent
                && ![
                    Choices::STEALTHROCK,
                    Choices::SPIKES,
                    Choices::TOXICSPIKES,
                    Choices::STICKYWEB,
                    Choices::TRICKROOM,
                    Choices::RAINDANCE,
                    Choices::SUNNYDAY,
                    Choices::SANDSTORM,
                    Choices::SNOWSCAPE,
                    Choices::HAIL,
                    Choices::GRASSYTERRAIN,
                    Choices::ELECTRICTERRAIN,
                    Choices::PSYCHICTERRAIN,
                    Choices::MISTYTERRAIN,
                    Choices::HAZE,
                    Choices::PERISHSONG,
                    Choices::GRAVITY,
                    Choices::MAGICROOM,
                    Choices::WONDERROOM,
                    Choices::COURTCHANGE,
                ]
                .contains(&attacker_choice.move_id)
                && defending_side
                    .get_active_immutable()
                    .has_type(&PokemonType::DARK)
            {
                attacker_choice.remove_all_effects();
            }
        }
        Abilities::BEADSOFRUIN => {
            if attacker_choice.category == MoveCategory::Special {
                attacker_choice.defense_modifier *= 0.75;
            }
        }
        Abilities::SWORDOFRUIN => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.defense_modifier *= 0.75;
            }
        }
        Abilities::SHARPNESS => {
            if attacker_choice.flags.slicing {
                attacker_choice.base_power *= 1.5;
            }
        }
        Abilities::WATERBUBBLE => {
            if attacker_choice.move_type == PokemonType::WATER {
                attacker_choice.attack_modifier *= 2.0;
            }
        }
        Abilities::DRAGONSMAW => {
            if attacker_choice.move_type == PokemonType::DRAGON {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::HADRONENGINE => {
            if attacker_choice.category == MoveCategory::Special
                && state.terrain.terrain_type == Terrain::ELECTRICTERRAIN
            {
                attacker_choice.attack_modifier *= 5461.0 / 4096.0;
            }
        }
        Abilities::ORICHALCUMPULSE => {
            if attacker_choice.category == MoveCategory::Physical
                && state.weather.weather_type == Weather::SUN
            {
                attacker_choice.attack_modifier *= 5461.0 / 4096.0;
            }
        }
        Abilities::GALVANIZE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::ELECTRIC;
                attacker_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        #[cfg(any(
            feature = "champions",
            feature = "gen9",
            feature = "gen8",
            feature = "gen7"
        ))]
        Abilities::AERILATE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::FLYING;
                attacker_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        #[cfg(any(feature = "gen6", feature = "gen5", feature = "gen4"))]
        Abilities::AERILATE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::FLYING;
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Abilities::NEUROFORCE => {
            if move_type_effectiveness(&attacker_choice, &defending_side.get_active_immutable())
                > 1.0
            {
                attacker_choice.damage_modifier *= 5120.0 / 4096.0;
            }
        }
        Abilities::STAKEOUT => {
            if defender_choice.category == MoveCategory::Switch {
                attacker_choice.attack_modifier *= 2.0;
            }
        }
        Abilities::TECHNICIAN => {
            if attacker_choice.base_power <= 60.0 {
                attacker_choice.base_power *= 1.5;
            }
        }
        #[cfg(any(
            feature = "champions",
            feature = "gen9",
            feature = "gen8",
            feature = "gen7"
        ))]
        Abilities::REFRIGERATE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::ICE;
                attacker_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        #[cfg(any(feature = "gen6", feature = "gen5", feature = "gen4"))]
        Abilities::REFRIGERATE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::ICE;
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L34): Showdown's 4096ths per fainted
        // ally, up to 5 (was 1 + 0.1 each, no cap)
        Abilities::SUPREMEOVERLORD => {
            const POW: [f32; 6] = [4096.0, 4506.0, 4915.0, 5325.0, 5734.0, 6144.0];
            let n = (attacking_side.num_fainted_pkmn() as usize).min(5);
            attacker_choice.base_power *= POW[n] / 4096.0;
        }
        // alpha-poke patch (L34): Adaptability in damage_calc's stab_modifier (was its ratio here)
        Abilities::LONGREACH => {
            attacker_choice.flags.contact = false;
        }
        Abilities::PUREPOWER => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.attack_modifier *= 2.0;
            }
        }
        Abilities::TINTEDLENS => {
            if move_type_effectiveness(&attacker_choice, &defending_side.get_active_immutable())
                < 1.0
            {
                attacker_choice.damage_modifier *= 2.0;
            }
        }
        Abilities::FLAREBOOST => {
            if attacking_pkmn.status == PokemonStatus::BURN {
                attacker_choice.base_power *= 1.5;
            }
        }
        Abilities::LIQUIDVOICE => {
            if attacker_choice.flags.sound {
                attacker_choice.move_type = PokemonType::WATER;
            }
        }
        Abilities::NOGUARD => {
            attacker_choice.accuracy = 100.0;
            attacker_choice.sure_hit = true;
        }
        Abilities::TORRENT => {
            if attacker_choice.move_type == PokemonType::WATER
                && attacking_pkmn.hp <= attacking_pkmn.maxhp / 3
            {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::SERENEGRACE => {
            if let Some(secondaries) = &mut attacker_choice.secondaries {
                for secondary in secondaries.iter_mut() {
                    secondary.chance *= 2.0;
                }
            }
        }
        Abilities::TOUGHCLAWS => {
            if attacker_choice.flags.contact {
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Abilities::RECKLESS => {
            if attacker_choice.crash.is_some() || attacker_choice.recoil.is_some() {
                attacker_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Abilities::ROCKHEAD => {
            attacker_choice.recoil = None;
        }
        Abilities::HUGEPOWER => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.attack_modifier *= 2.0;
            }
        }
        Abilities::SOLARPOWER => {
            if state.weather_is_active(&Weather::SUN) {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::FAIRYAURA => {
            if attacker_choice.move_type == PokemonType::FAIRY
                && defending_side.get_active_immutable().ability != Abilities::AURABREAK
            {
                attacker_choice.base_power *= 5448.0 / 4096.0;
            }
        }
        Abilities::NORMALIZE => {
            attacker_choice.move_type = PokemonType::NORMAL;
        }
        Abilities::DARKAURA => {
            if attacker_choice.move_type == PokemonType::DARK
                && defending_side.get_active_immutable().ability != Abilities::AURABREAK
            {
                attacker_choice.base_power *= 5448.0 / 4096.0;
            }
        }
        Abilities::VICTORYSTAR => {
            attacker_choice.accuracy *= 1.1;
        }
        Abilities::COMPOUNDEYES => {
            attacker_choice.accuracy *= 1.3;
        }
        Abilities::STEELWORKER | Abilities::STEELYSPIRIT => {
            if attacker_choice.move_type == PokemonType::STEEL {
                attacker_choice.base_power *= 1.5;
            }
        }
        #[cfg(any(feature = "gen9", feature = "champions"))]
        Abilities::TRANSISTOR => {
            if attacker_choice.move_type == PokemonType::ELECTRIC {
                attacker_choice.attack_modifier *= 5325.0 / 4096.0;
            }
        }
        #[cfg(any(
            feature = "gen8",
            feature = "gen7",
            feature = "gen6",
            feature = "gen5",
            feature = "gen4"
        ))]
        Abilities::TRANSISTOR => {
            if attacker_choice.move_type == PokemonType::ELECTRIC {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::FIREMANE => {
            if attacker_choice.move_type == PokemonType::FIRE {
                attacker_choice.base_power *= 1.5;
            }
        }
        Abilities::STENCH => {
            let mut already_flinches = false;
            if let Some(secondaries) = &mut attacker_choice.secondaries {
                for secondary in secondaries.iter() {
                    if secondary.effect == Effect::VolatileStatus(PokemonVolatileStatus::FLINCH) {
                        already_flinches = true;
                    }
                }
            }
            if !already_flinches {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 10.0,
                    target: MoveTarget::Opponent,
                    effect: Effect::VolatileStatus(PokemonVolatileStatus::FLINCH),
                })
            }
        }
        Abilities::SWARM => {
            if attacker_choice.move_type == PokemonType::BUG
                && attacking_pkmn.hp <= attacking_pkmn.maxhp / 3
            {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::GORILLATACTICS => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::BLAZE => {
            if attacker_choice.move_type == PokemonType::FIRE
                && attacking_pkmn.hp <= attacking_pkmn.maxhp / 3
            {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::OVERGROW => {
            if attacker_choice.move_type == PokemonType::GRASS
                && attacking_pkmn.hp <= attacking_pkmn.maxhp / 3
            {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::ANALYTIC => {
            if !attacker_choice.first_move {
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Abilities::MEGALAUNCHER => {
            if attacker_choice.flags.pulse {
                attacker_choice.base_power *= 1.5;
            };
        }
        #[cfg(any(
            feature = "champions",
            feature = "gen9",
            feature = "gen8",
            feature = "gen7"
        ))]
        Abilities::PIXILATE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::FAIRY;
                attacker_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        #[cfg(any(feature = "gen6", feature = "gen5", feature = "gen4"))]
        Abilities::PIXILATE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::FAIRY;
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Abilities::DRAGONIZE => {
            if attacker_choice.move_type == PokemonType::NORMAL {
                attacker_choice.move_type = PokemonType::DRAGON;
                attacker_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Abilities::DEFEATIST => {
            if attacking_pkmn.hp <= attacking_pkmn.maxhp / 2 {
                attacker_choice.attack_modifier *= 0.5;
            }
        }
        Abilities::ROCKYPAYLOAD => {
            if attacker_choice.move_type == PokemonType::ROCK {
                attacker_choice.attack_modifier *= 1.5;
            }
        }
        Abilities::PUNKROCK => {
            if attacker_choice.flags.sound {
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Abilities::STRONGJAW => {
            if attacker_choice.flags.bite {
                attacker_choice.base_power *= 1.5;
            }
        }
        Abilities::BATTERY => {
            if attacker_choice.category == MoveCategory::Special {
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Abilities::SHEERFORCE => {
            let mut sheer_force_volatile_boosted = false;
            if let Some(attacker_volatile_status) = &attacker_choice.volatile_status {
                if attacker_volatile_status.volatile_status
                    != PokemonVolatileStatus::PARTIALLYTRAPPED
                    && attacker_volatile_status.volatile_status != PokemonVolatileStatus::LOCKEDMOVE
                    && attacker_volatile_status.volatile_status != PokemonVolatileStatus::SMACKDOWN
                {
                    sheer_force_volatile_boosted = true;
                }
            }
            // (L186: Eerie Spell's PP drop is a secondary too)
            if attacker_choice.secondaries.is_some()
                || sheer_force_volatile_boosted
                || attacker_choice.move_id == Choices::EERIESPELL
            {
                attacker_choice.base_power *= 5325.0 / 4096.0;
                attacker_choice.secondaries = None;
                attacker_choice.volatile_status = None
            }
        }
        Abilities::IRONFIST => {
            if attacker_choice.flags.punch {
                attacker_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        #[cfg(feature = "champions")]
        Abilities::UNSEENFIST | Abilities::PIERCINGDRILL => {
            if attacker_choice.flags.contact {
                attacker_choice.flags.protect = false;
                attacker_choice.base_power *= 0.25;
            }
        }
        #[cfg(not(feature = "champions"))]
        Abilities::UNSEENFIST => {
            if attacker_choice.flags.contact {
                attacker_choice.flags.protect = false
            }
        }
        Abilities::HUSTLE => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.attack_modifier *= 1.5;
                attacker_choice.accuracy *= 0.80
            }
        }
        Abilities::POISONTOUCH => {
            if attacker_choice.flags.contact {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 30.0,
                    target: MoveTarget::Opponent,
                    effect: Effect::Status(PokemonStatus::POISON),
                })
            }
        }
        Abilities::TOXICCHAIN => {
            if attacker_choice.target == MoveTarget::Opponent {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 30.0,
                    target: MoveTarget::Opponent,
                    effect: Effect::Status(PokemonStatus::TOXIC),
                })
            }
        }
        Abilities::GUTS => {
            // (L34: the Attack only, Showdown's onModifyAtk; was any move's power)
            if attacking_pkmn.status != PokemonStatus::NONE
                && attacker_choice.category == MoveCategory::Physical
            {
                attacker_choice.attack_modifier *= 1.5;
                // alpha-poke patch (2026-10-16, doc/engine-diff.md L33): no burn halving with
                // Guts in damage_calc's burn_modifier (was a 2 x here)
            }
        }
        Abilities::SANDFORCE => {
            if state.weather_is_active(&Weather::SAND)
                && (attacker_choice.move_type == PokemonType::ROCK
                    || attacker_choice.move_type == PokemonType::GROUND
                    || attacker_choice.move_type == PokemonType::STEEL)
            {
                attacker_choice.base_power *= 5325.0 / 4096.0;
            }
        }
        Abilities::TOXICBOOST => {
            if attacking_pkmn.status == PokemonStatus::POISON
                || attacking_pkmn.status == PokemonStatus::TOXIC
            {
                attacker_choice.base_power *= 1.5;
            }
        }
        _ => {}
    }
}

pub fn ability_modify_attack_against(
    state: &State,
    attacker_choice: &mut Choice,
    defender_choice: &Choice,
    attacking_side_ref: &SideReference,
) {
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);
    let attacking_pkmn = attacking_side.get_active_immutable();
    let target_pkmn = defending_side.get_active_immutable();
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L35): a Neutralizing Gas user's hit
    // ignores the target's ability too (unless it holds Ability Shield)
    if target_pkmn.ability == Abilities::NEUTRALIZINGGAS
        || (attacking_pkmn.ability == Abilities::NEUTRALIZINGGAS
            && target_pkmn.item != Items::ABILITYSHIELD)
        || attacker_choice.target == MoveTarget::User
    {
        return;
    }
    if (attacking_pkmn.ability == Abilities::MOLDBREAKER
        || attacker_choice.move_id == Choices::MOONGEISTBEAM
        || attacker_choice.move_id == Choices::PHOTONGEYSER
        || attacker_choice.move_id == Choices::SUNSTEELSTRIKE
        || (attacking_pkmn.ability == Abilities::MYCELIUMMIGHT
            && attacker_choice.category == MoveCategory::Status)
        || attacking_pkmn.ability == Abilities::TERAVOLT
        || attacking_pkmn.ability == Abilities::TURBOBLAZE)
        && mold_breaker_ignores(&target_pkmn.ability)
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): not through an Ability Shield
        && target_pkmn.item != Items::ABILITYSHIELD
    {
        return;
    }

    match target_pkmn.ability {
        Abilities::TABLETSOFRUIN => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.attack_modifier *= 0.75;
            }
        }
        Abilities::VESSELOFRUIN => {
            if attacker_choice.category == MoveCategory::Special {
                attacker_choice.attack_modifier *= 0.75;
            }
        }
        Abilities::ARMORTAIL => {
            if attacker_choice.priority > 0 && attacker_choice.category != MoveCategory::Status {
                attacker_choice.remove_all_effects();
            }
        }
        Abilities::SOUNDPROOF => {
            if attacker_choice.flags.sound {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 0.0;
            }
        }
        Abilities::POISONPOINT => {
            if attacker_choice.flags.contact {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 33.0,
                    target: MoveTarget::User,
                    effect: Effect::Status(PokemonStatus::POISON),
                })
            }
        }
        Abilities::BULLETPROOF => {
            if attacker_choice.flags.bullet {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 0.0;
            }
        }
        Abilities::MULTISCALE => {
            if target_pkmn.hp == target_pkmn.maxhp {
                attacker_choice.damage_modifier /= 2.0;
            }
        }
        Abilities::LIGHTNINGROD => {
            if attacker_choice.move_type == PokemonType::ELECTRIC {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 100.0;
                attacker_choice.target = MoveTarget::Opponent;
                attacker_choice.boost = Some(Boost {
                    boosts: StatBoosts {
                        attack: 0,
                        defense: 0,
                        special_attack: 1,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    },
                    target: MoveTarget::Opponent,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        Abilities::EARTHEATER => {
            // (L94: not a move aimed at its side: Spikes, ...)
            if attacker_choice.move_type == PokemonType::GROUND
                && !attacker_choice.move_id.not_aimed_at_foe()
            {
                attacker_choice.remove_all_effects();
                attacker_choice.base_power = 0.0;
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::Opponent,
                    amount: 0.25,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        #[cfg(any(feature = "gen6", feature = "gen5", feature = "gen4"))]
        Abilities::WEAKARMOR => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    target: MoveTarget::Opponent,
                    effect: Effect::Boost(StatBoosts {
                        attack: 0,
                        defense: -1,
                        special_attack: 0,
                        special_defense: 0,
                        speed: 1,
                        accuracy: 0,
                    }),
                });
            }
        }
        Abilities::QUEENLYMAJESTY => {
            if attacker_choice.priority > 0 {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 0.0;
            }
        }
        Abilities::SAPSIPPER => {
            if attacker_choice.move_type == PokemonType::GRASS {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 100.0;
                attacker_choice.target = MoveTarget::Opponent;
                attacker_choice.boost = Some(Boost {
                    boosts: StatBoosts {
                        attack: 1,
                        defense: 0,
                        special_attack: 0,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    },
                    target: MoveTarget::Opponent,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        Abilities::SHADOWSHIELD => {
            if target_pkmn.hp == target_pkmn.maxhp {
                attacker_choice.damage_modifier /= 2.0;
            }
        }
        Abilities::NOGUARD => {
            attacker_choice.accuracy = 100.0;
            attacker_choice.sure_hit = true;
        }
        Abilities::MARVELSCALE => {
            if target_pkmn.status != PokemonStatus::NONE
                && attacker_choice.category == MoveCategory::Physical
            {
                attacker_choice.defense_modifier *= 1.5;
            }
        }
        Abilities::EFFECTSPORE => {
            if attacker_choice.flags.contact {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 9.0,
                    target: MoveTarget::User,
                    effect: Effect::Status(PokemonStatus::POISON),
                });
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 10.0,
                    target: MoveTarget::User,
                    effect: Effect::Status(PokemonStatus::PARALYZE),
                });
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 11.0,
                    target: MoveTarget::User,
                    effect: Effect::Status(PokemonStatus::SLEEP),
                });
            }
        }
        Abilities::FLAMEBODY => {
            if attacker_choice.flags.contact {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 30.0,
                    target: MoveTarget::User,
                    effect: Effect::Status(PokemonStatus::BURN),
                });
            }
        }
        Abilities::SPICYSPRAY => {
            attacker_choice.add_or_create_secondaries(Secondary {
                chance: 100.0,
                target: MoveTarget::User,
                effect: Effect::Status(PokemonStatus::BURN),
            });
        }
        Abilities::MOTORDRIVE => {
            if attacker_choice.move_type == PokemonType::ELECTRIC {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 100.0;
                attacker_choice.target = MoveTarget::Opponent;
                attacker_choice.boost = Some(Boost {
                    boosts: StatBoosts {
                        attack: 0,
                        defense: 0,
                        special_attack: 0,
                        special_defense: 0,
                        speed: 1,
                        accuracy: 0,
                    },
                    target: MoveTarget::Opponent,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        Abilities::WINDRIDER => {
            if attacker_choice.flags.wind {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 100.0;
                attacker_choice.target = MoveTarget::Opponent;
                attacker_choice.boost = Some(Boost {
                    boosts: StatBoosts {
                        attack: 1,
                        defense: 0,
                        special_attack: 0,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    },
                    target: MoveTarget::Opponent,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        Abilities::SUCTIONCUPS => {
            attacker_choice.flags.drag = false;
        }
        Abilities::WONDERGUARD => {
            if attacker_choice.category != MoveCategory::Status
                && move_type_effectiveness(&attacker_choice, &target_pkmn) <= 1.0
            {
                attacker_choice.remove_all_effects();
                attacker_choice.base_power = 0.0;
            }
        }
        Abilities::FAIRYAURA => {
            if attacker_choice.move_type == PokemonType::FAIRY {
                attacker_choice.base_power *= 5448.0 / 4096.0;
            }
        }
        Abilities::LEVITATE | Abilities::EELEVATE => {
            // alpha-poke patch (L32): not when grounded by Iron Ball / Smack Down
            if attacker_choice.move_type == PokemonType::GROUND
                && attacker_choice.target == MoveTarget::Opponent
                && attacker_choice.move_id != Choices::THOUSANDARROWS
                && !super::damage_calc::grounded_by_effect(defending_side, target_pkmn)
            {
                attacker_choice.base_power = 0.0;
            }
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L74): Electromorphosis, a damaging hit
        // charges its holder (a secondary on it: not through a Substitute)
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L70): Cursed Body, 30% of the time the
        // move that hit its holder is disabled (as a secondary on the user; Disable needs its last
        // move: the one being used)
        Abilities::CURSEDBODY => {
            if attacker_choice.category != MoveCategory::Status
                && attacker_choice.move_id != Choices::STRUGGLE
            {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 30.0,
                    target: MoveTarget::User,
                    effect: Effect::VolatileStatus(PokemonVolatileStatus::DISABLE),
                })
            }
        }
        Abilities::STATIC => {
            if attacker_choice.flags.contact {
                attacker_choice.add_or_create_secondaries(Secondary {
                    chance: 30.0,
                    target: MoveTarget::User,
                    effect: Effect::Status(PokemonStatus::PARALYZE),
                })
            }
        }
        Abilities::WONDERSKIN => {
            if attacker_choice.category == MoveCategory::Status && attacker_choice.accuracy > 50.0 {
                attacker_choice.accuracy = 50.0;
            }
        }
        Abilities::THICKFAT => {
            if attacker_choice.move_type == PokemonType::FIRE
                || attacker_choice.move_type == PokemonType::ICE
            {
                attacker_choice.attack_modifier /= 2.0;
            }
        }
        Abilities::FLASHFIRE => {
            if attacker_choice.move_type == PokemonType::FIRE {
                attacker_choice.remove_all_effects();
                attacker_choice.volatile_status = Some(VolatileStatus {
                    target: MoveTarget::Opponent,
                    volatile_status: PokemonVolatileStatus::FLASHFIRE,
                });
            }
        }
        Abilities::WELLBAKEDBODY => {
            if attacker_choice.move_type == PokemonType::FIRE {
                attacker_choice.remove_all_effects();
                attacker_choice.boost = Some(Boost {
                    boosts: StatBoosts {
                        attack: 0,
                        defense: 2,
                        special_attack: 0,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    },
                    target: MoveTarget::Opponent,
                });
            }
        }
        Abilities::DAZZLING => {
            if attacker_choice.priority > 0 {
                attacker_choice.accuracy = 0.0;
            }
        }
        Abilities::LIQUIDOOZE => {
            if let Some(drain) = attacker_choice.drain {
                attacker_choice.drain = Some(-1.0 * drain);
            }
        }
        Abilities::PRISMARMOR => {
            if move_type_effectiveness(&attacker_choice, &target_pkmn) > 1.0 {
                attacker_choice.damage_modifier *= 0.75;
            }
        }
        Abilities::HEATPROOF => {
            if attacker_choice.move_type == PokemonType::FIRE {
                attacker_choice.attack_modifier *= 0.5;
            }
        }
        Abilities::SHIELDDUST => {
            if let Some(secondaries) = &mut attacker_choice.secondaries {
                for secondary in secondaries.iter_mut() {
                    if secondary.target == MoveTarget::Opponent {
                        secondary.chance = 0.0;
                    }
                }
            }
        }
        Abilities::GRASSPELT => {
            if state.terrain_is_active(&Terrain::GRASSYTERRAIN)
                && attacker_choice.category == MoveCategory::Physical
            {
                attacker_choice.defense_modifier *= 1.5;
            }
        }
        Abilities::FILTER => {
            if move_type_effectiveness(&attacker_choice, &target_pkmn) > 1.0 {
                attacker_choice.damage_modifier *= 0.75;
            }
        }
        Abilities::FURCOAT => {
            if attacker_choice.category == MoveCategory::Physical {
                attacker_choice.defense_modifier *= 2.0;
            }
        }
        Abilities::MAGICBOUNCE => {
            if attacker_choice.flags.reflectable {
                attacker_choice.target = MoveTarget::User;
                if let Some(side_condition) = &mut attacker_choice.side_condition {
                    if side_condition.target == MoveTarget::Opponent {
                        side_condition.target = MoveTarget::User;
                    }
                }
                if let Some(status) = &mut attacker_choice.status {
                    if status.target == MoveTarget::Opponent {
                        status.target = MoveTarget::User;
                    }
                }
                if let Some(volatile_status) = &mut attacker_choice.volatile_status {
                    if volatile_status.target == MoveTarget::Opponent {
                        volatile_status.target = MoveTarget::User;
                    }
                }
                // alpha-poke patch (2026-10-17, doc/engine-diff.md L128): the stat drops come back
                // too (Parting Shot, Tickle, ...), and its user does not switch out (a reflected
                // Parting Shot switches the reflector out: finish_move)
                if let Some(boost) = &mut attacker_choice.boost {
                    if boost.target == MoveTarget::Opponent {
                        boost.target = MoveTarget::User;
                    }
                }
                attacker_choice.flags.pivot = false;
                // alpha-poke patch (2026-10-17, doc/engine-diff.md L155): a reflected Strength Sap
                // heals the reflector by its user's Attack (Liquid Ooze: its user's), the drop on
                // the user above; it healed its user by the reflector's
                if attacker_choice.move_id == Choices::STRENGTHSAP {
                    attacker_choice.heal = if attacking_side.attack_boost != -6 {
                        let attack = attacking_side.calculate_boosted_stat(PokemonBoostableStat::Attack);
                        let sign = if attacking_pkmn.ability == Abilities::LIQUIDOOZE {
                            -1.0
                        } else {
                            1.0
                        };
                        Some(Heal {
                            target: MoveTarget::Opponent,
                            amount: sign * attack as f32 / target_pkmn.maxhp as f32,
                        })
                    } else {
                        None
                    };
                }
            }
        }
        Abilities::STORMDRAIN => {
            if attacker_choice.move_type == PokemonType::WATER {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 100.0;
                attacker_choice.target = MoveTarget::Opponent;
                attacker_choice.boost = Some(Boost {
                    boosts: StatBoosts {
                        attack: 0,
                        defense: 0,
                        special_attack: 1,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    },
                    target: MoveTarget::Opponent,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        Abilities::ICESCALES => {
            if attacker_choice.category == MoveCategory::Special {
                attacker_choice.damage_modifier *= 0.5;
            }
        }
        Abilities::WATERABSORB => {
            // (L94: not a move aimed at its side: Spikes, ...)
            if attacker_choice.move_type == PokemonType::WATER
                && !attacker_choice.move_id.not_aimed_at_foe()
            {
                attacker_choice.remove_all_effects();
                attacker_choice.base_power = 0.0;
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::Opponent,
                    amount: 0.25,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        Abilities::DRYSKIN => {
            // (L94: not a move aimed at its side: Spikes, ...)
            if attacker_choice.move_type == PokemonType::WATER
                && !attacker_choice.move_id.not_aimed_at_foe()
            {
                attacker_choice.remove_all_effects();
                attacker_choice.base_power = 0.0;
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::Opponent,
                    amount: 0.25,
                });
                attacker_choice.category = MoveCategory::Status;
            } else if attacker_choice.move_type == PokemonType::FIRE {
                attacker_choice.base_power *= 1.25;
            }
        }
        Abilities::FLUFFY => {
            if attacker_choice.flags.contact {
                attacker_choice.damage_modifier *= 0.5;
            }
            if attacker_choice.move_type == PokemonType::FIRE {
                attacker_choice.damage_modifier *= 2.0;
            }
        }
        Abilities::PUNKROCK => {
            if attacker_choice.flags.sound {
                attacker_choice.damage_modifier /= 2.0;
            }
        }
        Abilities::DAMP => {
            if [
                Choices::SELFDESTRUCT,
                Choices::EXPLOSION,
                Choices::MINDBLOWN,
                Choices::MISTYEXPLOSION,
            ]
            .contains(&attacker_choice.move_id)
            {
                attacker_choice.accuracy = 0.0;
                attacker_choice.heal = None;
            }
        }
        Abilities::VOLTABSORB => {
            // (L94: not a move aimed at its side: Spikes, ...)
            if attacker_choice.move_type == PokemonType::ELECTRIC
                && !attacker_choice.move_id.not_aimed_at_foe()
            {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 100.0;
                attacker_choice.base_power = 0.0;
                attacker_choice.heal = Some(Heal {
                    target: MoveTarget::Opponent,
                    amount: 0.25,
                });
                attacker_choice.category = MoveCategory::Status;
            }
        }
        Abilities::SOLIDROCK => {
            if move_type_effectiveness(&attacker_choice, &target_pkmn) > 1.0 {
                attacker_choice.damage_modifier *= 0.75;
            }
        }
        Abilities::OVERCOAT => {
            if attacker_choice.flags.powder {
                attacker_choice.remove_all_effects();
                attacker_choice.accuracy = 0.0
            }
        }
        Abilities::GOODASGOLD => {
            // This engine doesn't distinguish "targetting other pkmn" versus "targetting the side"
            // Thankfully it is a short list of moves that target the opponent side
            // (L72: the moves not aimed at the foe's Pokemon -- hazards, weather, terrains, rooms,
            // Haze, ... -- and a non-Ghost Curse, aimed at its user, pass)
            let self_curse = attacker_choice.move_id == Choices::CURSE
                && !attacking_pkmn.has_type(&PokemonType::GHOST);
            if attacker_choice.category == MoveCategory::Status
                && attacker_choice.target == MoveTarget::Opponent
                && !attacker_choice.move_id.not_aimed_at_foe()
                && !self_curse
            {
                attacker_choice.remove_all_effects();
            }
        }
        Abilities::WATERBUBBLE => {
            if attacker_choice.move_type == PokemonType::FIRE {
                attacker_choice.attack_modifier /= 2.0;
            }
        }
        Abilities::PURIFYINGSALT => {
            if attacker_choice.move_type == PokemonType::GHOST {
                attacker_choice.attack_modifier /= 2.0;
            }
        }
        _ => {}
    }
}
