#![allow(unused_variables)]
use super::abilities::Abilities;
use super::damage_calc::{move_type_effectiveness, type_effectiveness_modifier};
use super::generate_instructions::{apply_boost_instruction, immune_to_status};
use super::state::Terrain;
use crate::choices::{
    Choice, Choices, Effect, MoveCategory, MoveTarget, Secondary, StatBoosts, MOVES,
};
use crate::define_enum_with_from_str;
use crate::engine::generate_instructions::add_remove_status_instructions;
use crate::instruction::{
    ApplyVolatileStatusInstruction, ChangeItemInstruction, ChangeStatusInstruction,
    ChangeVolatileStatusDurationInstruction, DamageInstruction, DisableMoveInstruction,
    HealInstruction, Instruction, RemoveVolatileStatusInstruction, StateInstructions,
};
use crate::pokemon::PokemonName;
use crate::state::{
    Pokemon, PokemonBoostableStat, PokemonNature, PokemonStatus, PokemonType, Side, SideReference,
    State,
};
use std::cmp;

// alpha-poke patch (2026-10-13): every generation (Persim Berry, Mental Herb)
use super::state::PokemonVolatileStatus;

define_enum_with_from_str! {
    // alpha-poke patch (2026-10-16): u16, the items from Showdown do not fit in a u8
    #[repr(u16)]
    #[derive(Debug, PartialEq, Clone, Copy)]
    Items {
        NONE,
        UNKNOWNITEM,
        ABSORBBULB,
        ADRENALINEORB,
        ADAMANTORB,
        ADAMANTCRYSTAL,
        AIRBALLOON,
        ASSAULTVEST,
        BABIRIBERRY,
        BLACKBELT,
        BLACKSLUDGE,
        BLACKGLASSES,
        BLANKPLATE,
        BOOSTERENERGY,
        CELLBATTERY,
        CHARCOAL,
        CHARTIBERRY,
        CHILANBERRY,
        CHOICEBAND,
        CHOICESPECS,
        CHOICESCARF,
        CHOPLEBERRY,
        COBABERRY,
        COLBURBERRY,
        COVERTCLOAK,
        CUSTAPBERRY,
        DRAGONFANG,
        DRAGONSCALE,
        DREADPLATE,
        EARTHPLATE,
        ELECTRICSEED,
        EXPERTBELT,
        EVIOLITE,
        FAIRYFEATHER,
        FISTPLATE,
        FLAMEORB,
        GRASSYSEED,
        HABANBERRY,
        KASIBBERRY,
        KEBIABERRY,
        LEFTOVERS,
        LIFEORB,
        LUSTROUSORB,
        LUSTROUSGLOBE,
        METALCOAT,
        MISTYSEED,
        MUSCLEBAND,
        MYSTICWATER,
        NEVERMELTICE,
        PINKBOW,
        POLKADOTBOW,
        OCCABERRY,
        ODDINCENSE,
        PASSHOBERRY,
        PAYAPABERRY,
        POISONBARB,
        POWERHERB,
        PSYCHICSEED,
        PUNCHINGGLOVE,
        RINDOBERRY,
        ROSELIBERRY,
        ROCKYHELMET,
        SEAINCENSE,
        SHARPBEAK,
        SPELLTAG,
        MIRACLESEED,
        SHELLBELL,
        SHUCABERRY,
        SILKSCARF,
        SILVERPOWDER,
        SKYPLATE,
        SOFTSAND,
        SOULDEW,
        GRISEOUSORB,
        GRISEOUSCORE,
        TANGABERRY,
        THROATSPRAY,
        THICKCLUB,
        TOXICORB,
        TOXICPLATE,
        TWISTEDSPOON,
        HARDSTONE,
        METALPOWDER,
        WACANBERRY,
        WAVEINCENSE,
        MAGNET,
        WEAKNESSPOLICY,
        WISEGLASSES,
        BLUNDERPOLICY,
        HEAVYDUTYBOOTS,
        CLEARAMULET,
        PROTECTIVEPADS,
        SHEDSHELL,
        YACHEBERRY,
        STONEPLATE,
        INSECTPLATE,
        SPOOKYPLATE,
        IRONBALL,
        IRONPLATE,
        FLAMEPLATE,
        SPLASHPLATE,
        MEADOWPLATE,
        ZAPPLATE,
        MINDPLATE,
        ICICLEPLATE,
        DRACOPLATE,
        PIXIEPLATE,
        LIGHTBALL,
        FOCUSSASH,
        CHESTOBERRY,
        LUMBERRY,
        SITRUSBERRY,
        PETAYABERRY,
        SALACBERRY,
        LIECHIBERRY,
        NORMALGEM,
        BUGGEM,
        ELECTRICGEM,
        FIGHTINGGEM,
        GHOSTGEM,
        PSYCHICGEM,
        FLYINGGEM,
        STEELGEM,
        ICEGEM,
        POISONGEM,
        FIREGEM,
        DRAGONGEM,
        GROUNDGEM,
        WATERGEM,
        DARKGEM,
        ROCKGEM,
        GRASSGEM,
        FAIRYGEM,
        BUGMEMORY,
        FIGHTINGMEMORY,
        GHOSTMEMORY,
        PSYCHICMEMORY,
        FLYINGMEMORY,
        STEELMEMORY,
        ICEMEMORY,
        POISONMEMORY,
        FIREMEMORY,
        DRAGONMEMORY,
        GROUNDMEMORY,
        WATERMEMORY,
        DARKMEMORY,
        ROCKMEMORY,
        GRASSMEMORY,
        FAIRYMEMORY,
        ELECTRICMEMORY,
        WELLSPRINGMASK,
        HEARTHFLAMEMASK,
        CORNERSTONEMASK,
        WIDELENS,
        LOADEDDICE,
        RUSTEDSWORD,
        RUSTEDSHIELD,
        WHITEHERB,

        // mega stones
        VENUSAURITE,
        CHARIZARDITEX,
        CHARIZARDITEY,
        BLASTOISINITE,
        BEEDRILLITE,
        PIDGEOTITE,
        ALAKAZITE,
        SLOWBRONITE,
        GENGARITE,
        KANGASKHANITE,
        PINSIRITE,
        GYARADOSITE,
        AERODACTYLITE,
        MEWTWONITEX,
        MEWTWONITEY,
        AMPHAROSITE,
        STEELIXITE,
        SCIZORITE,
        HERACRONITE,
        HOUNDOOMINITE,
        TYRANITARITE,
        SCEPTILITE,
        BLAZIKENITE,
        SWAMPERTITE,
        GARDEVOIRITE,
        SABLENITE,
        MAWILITE,
        AGGRONITE,
        MEDICHAMITE,
        MANECTITE,
        SHARPEDONITE,
        CAMERUPTITE,
        ALTARIANITE,
        BANETTITE,
        ABSOLITE,
        GLALITITE,
        SALAMENCITE,
        METAGROSSITE,
        LATIASITE,
        LATIOSITE,
        LOPUNNITE,
        GARCHOMPITE,
        LUCARIONITE,
        ABOMASITE,
        GALLADITE,
        AUDINITE,
        DIANCITE,
        DRAGONINITE,
        CLEFABLITE,
        MEGANIUMITE,
        FERALIGITE,
        EMBOARITE,
        CHESNAUGHTITE,
        DELPHOXITE,
        GRENINJITE,
        CRABOMINITE,
        GOLURKITE,
        SCOVILLAINITE,
        GLIMMORANITE,
        FLOETTITE,
        VICTREEBELITE,
        STARMINITE,
        HAWLUCHANITE,
        SKARMORITE,
        MEOWSTICITE,
        FROSLASSITE,
        EXCADRITE,
        DRAMPANITE,
        CHIMECHITE,
        CHANDELURITE,
        STARAPTITE,
        SCOLIPITE,
        SCRAFTINITE,
        EELEKTROSSITE,
        PYROARITE,
        MALAMARITE,
        BARBARACITE,
        DRAGALGITE,
        FALINKSITE,
        RAICHUNITEX,
        RAICHUNITEY,
        // alpha-poke patch (2026-10-11), appended (alpha_search encodes items by their index for
        // the networks: earlier indices must not move): Eject Button, Red Card
        // (generate_instructions::run_move); before, both parsed as UNKNOWNITEM
        EJECTBUTTON,
        REDCARD,
        // alpha-poke patch (2026-10-13), appended likewise: status berries, Persim Berry, Mental
        // Herb (item_before_move / item_end_of_turn, like Lum Berry), Safety Goggles (powder
        // moves, weather damage)
        PECHABERRY,
        CHERIBERRY,
        RAWSTBERRY,
        ASPEARBERRY,
        PERSIMBERRY,
        MENTALHERB,
        SAFETYGOGGLES,
        // alpha-poke patch (2026-10-13): generate_instructions::run_move
        EJECTPACK,
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24), appended likewise: the items the
        // engine did not know, from Showdown's source (each with a dual-engine test). The duration
        // items: generate_instructions::extend_field_durations, the screens' duration
        DAMPROCK,
        HEATROCK,
        ICYROCK,
        SMOOTHROCK,
        TERRAINEXTENDER,
        LIGHTCLAY,
        // pinch berries (item_before_move / item_end_of_turn, as Sitrus Berry)
        FIGYBERRY,
        WIKIBERRY,
        MAGOBERRY,
        AGUAVBERRY,
        IAPAPABERRY,
        ORANBERRY,
        // used up by the hit that triggers them (item_modify_attack_against)
        KEEBERRY,
        MARANGABERRY,
        SNOWBALL,
        LUMINOUSMOSS,
        JABOCABERRY,
        ROWAPBERRY,
        ENIGMABERRY,
        // item_end_of_turn; its move to a contact attacker: generate_instructions::run_move
        STICKYBARB,
        // choice_effects (Trick Room), item_on_switch_in
        ROOMSERVICE,
        // the crit stage (generate_instructions_from_move)
        SCOPELENS,
        RAZORCLAW,
        // pinch berries: Defense / Sp. Def +1, Focus Energy (item_before_move / item_end_of_turn)
        GANLONBERRY,
        APICOTBERRY,
        LANSATBERRY,
        // accuracy (check_move_hit_or_miss)
        BRIGHTPOWDER,
        ZOOMLENS,
        // half the Speed (get_effective_speed)
        POWERANKLET,
        POWERBAND,
        POWERBELT,
        POWERBRACER,
        POWERLENS,
        POWERWEIGHT,
        // half the weight (choice_effects: Low Kick, Grass Knot, Heat Crash, Heavy Slam)
        FLOATSTONE,
        // drain / Leech Seed heals x 5324 / 4096
        BIGROOT,
        // a 10% flinch (item_modify_attack_being_used)
        KINGSROCK,
        RAZORFANG,
        // the holder's foes' sun / rain damage modifiers (damage_calc)
        UTILITYUMBRELLA,
        // generate_instructions::quick_claw_first_chance
        QUICKCLAW,
        // generate_instructions_from_move: a 1/10 survival branch
        FOCUSBAND,
        // generate_instructions::starf_berry_branches
        STARFBERRY,
        // generate_instructions_from_move (PP), item_end_of_turn + check_move_hit_or_miss, the
        // consecutive-use count (generate_instructions_from_move), get_instructions_from_boosts
        LEPPABERRY,
        MICLEBERRY,
        METRONOME,
        MIRRORHERB,
        // abilities.rs (Mold Breaker, Neutralizing Gas), get_instructions_from_volatile_statuses
        ABILITYSHIELD,
        DESTINYKNOT,
        // (L162: moves last in its bracket, generate_instructions' fractional priority)
        LAGGINGTAIL,
    },
    default = UNKNOWNITEM
}

pub fn get_choice_move_disable_instructions(
    pkmn: &Pokemon,
    side_ref: &SideReference,
    move_name: &Choices,
) -> Vec<Instruction> {
    let mut moves_to_disable = vec![];
    let mut iter = pkmn.moves.into_iter();
    while let Some(p) = iter.next() {
        if &p.id != move_name && p.disabled == false {
            moves_to_disable.push(Instruction::DisableMove(DisableMoveInstruction {
                side_ref: *side_ref,
                move_index: iter.pokemon_move_index,
            }));
        }
    }
    moves_to_disable
}

// alpha-poke patch (L45): the moves whose damage is fixed (Showdown's damageCallback: no
// modifyDamage, so no resist berry)
fn fixed_damage_move(m: &Choices) -> bool {
    matches!(
        m,
        Choices::SEISMICTOSS
            | Choices::NIGHTSHADE
            | Choices::SUPERFANG
            | Choices::RUINATION
            | Choices::NATURESMADNESS
            | Choices::ENDEAVOR
            | Choices::FINALGAMBIT
            | Choices::PSYWAVE
            | Choices::COUNTER
            | Choices::MIRRORCOAT
            | Choices::METALBURST
            | Choices::COMEUPPANCE
            | Choices::DRAGONRAGE
            | Choices::SONICBOOM
            | Choices::BIDE
    )
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L57): the item a mon used up (eaten / used,
// not lost), Showdown's lastItem: Harvest gives a berry back
pub fn set_last_item(
    pkmn: &mut Pokemon,
    side_ref: SideReference,
    item: Items,
    instructions: &mut StateInstructions,
) {
    if pkmn.last_item != item {
        instructions
            .instruction_list
            .push(Instruction::ChangeLastItem(ChangeItemInstruction {
                side_ref,
                current_item: pkmn.last_item,
                new_item: item,
            }));
        pkmn.last_item = item;
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L204): a berry eaten again (Cud Chew: Showdown's
// singleEvent Eat, the berry not held): its effect -- the berry given back for its handler, which
// uses it up again (the last item stays it); taken back if the handler did not
pub fn eat_again(
    state: &mut State,
    side_ref: &SideReference,
    berry: Items,
    instructions: &mut StateInstructions,
) {
    let side = state.get_side(side_ref);
    if side.get_active_immutable().hp == 0 || side.get_active_immutable().item != Items::NONE {
        return;
    }
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: Items::NONE,
            new_item: berry,
        }));
    side.get_active().item = berry;
    let stat = match berry {
        Items::LIECHIBERRY => Some(PokemonBoostableStat::Attack),
        Items::GANLONBERRY => Some(PokemonBoostableStat::Defense),
        Items::PETAYABERRY => Some(PokemonBoostableStat::SpecialAttack),
        Items::APICOTBERRY => Some(PokemonBoostableStat::SpecialDefense),
        Items::SALACBERRY => Some(PokemonBoostableStat::Speed),
        _ => None,
    };
    if let Some(stat) = stat {
        boost_berry(side_ref, state, stat, instructions);
    } else {
        let side = state.get_side(side_ref);
        match berry {
            Items::SITRUSBERRY => sitrus_berry(side_ref, side, instructions),
            Items::FIGYBERRY
            | Items::WIKIBERRY
            | Items::MAGOBERRY
            | Items::AGUAVBERRY
            | Items::IAPAPABERRY
            | Items::ORANBERRY => pinch_berry(side_ref, side, instructions),
            Items::LUMBERRY => lum_berry(side_ref, side, instructions),
            Items::PECHABERRY
            | Items::CHERIBERRY
            | Items::RAWSTBERRY
            | Items::ASPEARBERRY => status_berry(side_ref, side, berry, instructions),
            Items::CHESTOBERRY => chesto_berry(side_ref, side, instructions),
            Items::LANSATBERRY => lansat_berry(side_ref, side, instructions),
            _ => {}
        }
    }
    let active = state.get_side(side_ref).get_active();
    if active.item == berry {
        instructions
            .instruction_list
            .push(Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: *side_ref,
                current_item: berry,
                new_item: Items::NONE,
            }));
        active.item = Items::NONE;
    }
}

pub fn is_berry(item: Items) -> bool {
    format!("{:?}", item).ends_with("BERRY")
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L120): a damaging hit outside a move's usual
// damage (Future Sight, Counter / Mirror Coat / Metal Burst, Final Gambit) pops an Air Balloon too
// alpha-poke patch (2026-10-17, doc/engine-diff.md L140): Fling's base power with the item
// (Showdown's item.fling.basePower; None: it cannot be flung, Fling fails). tests/test_engine_data.py
// checks the table against Showdown's items
impl Items {
    pub fn fling_power(&self) -> Option<u8> {
        match self {
            Items::AGUAVBERRY
            | Items::AIRBALLOON
            | Items::APICOTBERRY
            | Items::ASPEARBERRY
            | Items::BABIRIBERRY
            | Items::BIGROOT
            | Items::BRIGHTPOWDER
            | Items::CHARTIBERRY
            | Items::CHERIBERRY
            | Items::CHESTOBERRY
            | Items::CHILANBERRY
            | Items::CHOICEBAND
            | Items::CHOICESCARF
            | Items::CHOICESPECS
            | Items::CHOPLEBERRY
            | Items::COBABERRY
            | Items::COLBURBERRY
            | Items::CUSTAPBERRY
            | Items::DESTINYKNOT
            | Items::ELECTRICSEED
            | Items::ENIGMABERRY
            | Items::EXPERTBELT
            | Items::FAIRYFEATHER
            | Items::FIGYBERRY
            | Items::FOCUSBAND
            | Items::FOCUSSASH
            | Items::GANLONBERRY
            | Items::GRASSYSEED
            | Items::HABANBERRY
            | Items::IAPAPABERRY
            | Items::JABOCABERRY
            | Items::KASIBBERRY
            | Items::KEBIABERRY
            | Items::KEEBERRY
            | Items::LANSATBERRY
            | Items::LEFTOVERS
            | Items::LEPPABERRY
            | Items::LIECHIBERRY
            | Items::LUMBERRY
            | Items::MAGOBERRY
            | Items::MARANGABERRY
            | Items::MENTALHERB
            | Items::MICLEBERRY
            | Items::MISTYSEED
            | Items::MUSCLEBAND
            | Items::OCCABERRY
            | Items::ORANBERRY
            | Items::PASSHOBERRY
            | Items::PAYAPABERRY
            | Items::PECHABERRY
            | Items::PERSIMBERRY
            | Items::PETAYABERRY
            | Items::POWERHERB
            | Items::PSYCHICSEED
            | Items::RAWSTBERRY
            | Items::REDCARD
            | Items::RINDOBERRY
            | Items::ROSELIBERRY
            | Items::ROWAPBERRY
            | Items::SALACBERRY
            | Items::SHEDSHELL
            | Items::SHUCABERRY
            | Items::SILKSCARF
            | Items::SILVERPOWDER
            | Items::SITRUSBERRY
            | Items::SMOOTHROCK
            | Items::SOFTSAND
            | Items::STARFBERRY
            | Items::TANGABERRY
            | Items::WACANBERRY
            | Items::WHITEHERB
            | Items::WIDELENS
            | Items::WIKIBERRY
            | Items::WISEGLASSES
            | Items::YACHEBERRY
            | Items::ZOOMLENS | Items::LAGGINGTAIL => Some(10),
            Items::ABILITYSHIELD
            | Items::ABSORBBULB
            | Items::ADRENALINEORB
            | Items::BLACKBELT
            | Items::BLACKGLASSES
            | Items::BLACKSLUDGE
            | Items::BOOSTERENERGY
            | Items::CELLBATTERY
            | Items::CHARCOAL
            | Items::CLEARAMULET
            | Items::COVERTCLOAK
            | Items::DRAGONSCALE
            | Items::EJECTBUTTON
            | Items::FLAMEORB
            | Items::FLOATSTONE
            | Items::KINGSROCK
            | Items::LIFEORB
            | Items::LIGHTBALL
            | Items::LIGHTCLAY
            | Items::LOADEDDICE
            | Items::LUMINOUSMOSS
            | Items::MAGNET
            | Items::METALCOAT
            | Items::METRONOME
            | Items::MIRACLESEED
            | Items::MIRRORHERB
            | Items::MYSTICWATER
            | Items::NEVERMELTICE
            | Items::PROTECTIVEPADS
            | Items::PUNCHINGGLOVE
            | Items::RAZORFANG
            | Items::SCOPELENS
            | Items::SHELLBELL
            | Items::SNOWBALL
            | Items::SOULDEW
            | Items::SPELLTAG
            | Items::THROATSPRAY
            | Items::TOXICORB
            | Items::TWISTEDSPOON => Some(30),
            Items::EVIOLITE | Items::ICYROCK => Some(40),
            Items::EJECTPACK | Items::SHARPBEAK => Some(50),
            Items::ADAMANTORB
            | Items::CORNERSTONEMASK
            | Items::DAMPROCK
            | Items::GRISEOUSORB
            | Items::HEARTHFLAMEMASK
            | Items::HEATROCK
            | Items::LUSTROUSORB
            | Items::ROCKYHELMET
            | Items::TERRAINEXTENDER
            | Items::UTILITYUMBRELLA
            | Items::WELLSPRINGMASK => Some(60),
            Items::DRAGONFANG
            | Items::POISONBARB
            | Items::POWERANKLET
            | Items::POWERBAND
            | Items::POWERBELT
            | Items::POWERBRACER
            | Items::POWERLENS
            | Items::POWERWEIGHT => Some(70),
            Items::ASSAULTVEST
            | Items::BLUNDERPOLICY
            | Items::HEAVYDUTYBOOTS
            | Items::QUICKCLAW
            | Items::RAZORCLAW
            | Items::SAFETYGOGGLES
            | Items::STICKYBARB
            | Items::WEAKNESSPOLICY => Some(80),
            Items::DRACOPLATE
            | Items::DREADPLATE
            | Items::EARTHPLATE
            | Items::FISTPLATE
            | Items::FLAMEPLATE
            | Items::ICICLEPLATE
            | Items::INSECTPLATE
            | Items::IRONPLATE
            | Items::MEADOWPLATE
            | Items::MINDPLATE
            | Items::PIXIEPLATE
            | Items::SKYPLATE
            | Items::SPLASHPLATE
            | Items::SPOOKYPLATE
            | Items::STONEPLATE
            | Items::TOXICPLATE
            | Items::ZAPPLATE => Some(90),
            Items::HARDSTONE | Items::ROOMSERVICE => Some(100),
            Items::IRONBALL => Some(130),
            _ => None,
        }
    }
}

pub fn pop_air_balloon(
    side_ref: &SideReference,
    side: &mut Side,
    instructions: &mut StateInstructions,
) {
    let holder = side.get_active();
    if holder.item == Items::AIRBALLOON {
        instructions
            .instruction_list
            .push(Instruction::ChangeItem(ChangeItemInstruction {
                side_ref: *side_ref,
                current_item: Items::AIRBALLOON,
                new_item: Items::NONE,
            }));
        holder.item = Items::NONE;
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L102): Unnerve / As One on the foe's active
// stop a berry being eaten (Showdown's onFoeTryEatItem; not under the holder's Neutralizing Gas)
pub fn unnerved(state: &State, side_ref: &SideReference) -> bool {
    let holder = state.get_side_immutable(side_ref).get_active_immutable();
    let foe = state
        .get_side_immutable(&side_ref.get_other_side())
        .get_active_immutable();
    is_berry(holder.item)
        && foe.hp > 0
        && holder.ability != Abilities::NEUTRALIZINGGAS
        && matches!(
            foe.ability,
            Abilities::UNNERVE | Abilities::ASONEGLASTRIER | Abilities::ASONESPECTRIER
        )
}

fn damage_reduction_berry(
    defending_pkmn: &mut Pokemon,
    attacking_side_ref: &SideReference,
    choice: &mut Choice,
    berry: Items,
    pkmn_type: &PokemonType,
    instructions: &mut StateInstructions,
) {
    // (L45: a damaging hit only, not a fixed damage: Showdown's onSourceModifyDamage)
    if &choice.move_type == pkmn_type
        && choice.category != MoveCategory::Status
        && !fixed_damage_move(&choice.move_id)
        && (berry == Items::CHILANBERRY
            || type_effectiveness_modifier(pkmn_type, &defending_pkmn) > 1.0)
    {
        eat_on_hit(choice, defending_pkmn, attacking_side_ref, berry, instructions);
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L152): a resist berry halves the damage and is
// eaten by the hit (Showdown's onSourceModifyDamage, at the damage): a secondary removing it, so
// a miss, a Protect, a Substitute or its foe's full paralysis leaves it; before, it was eaten as
// the move started (also Knock Off's 1.5 x: the berry is still held, choice_effects' check)
fn eat_on_hit(
    choice: &mut Choice,
    _defending_pkmn: &mut Pokemon,
    _attacking_side_ref: &SideReference,
    _berry: Items,
    _instructions: &mut StateInstructions,
) {
    choice.damage_modifier /= 2.0; // L34: a final modifier (onSourceModifyDamage)
    choice.add_or_create_secondaries(Secondary {
        chance: 100.0,
        effect: Effect::RemoveItem,
        target: MoveTarget::Opponent,
    });
}

pub fn is_resist_berry(item: Items) -> bool {
    matches!(
        item,
        Items::OCCABERRY
            | Items::PASSHOBERRY
            | Items::WACANBERRY
            | Items::RINDOBERRY
            | Items::YACHEBERRY
            | Items::CHOPLEBERRY
            | Items::KEBIABERRY
            | Items::SHUCABERRY
            | Items::COBABERRY
            | Items::PAYAPABERRY
            | Items::TANGABERRY
            | Items::CHARTIBERRY
            | Items::KASIBBERRY
            | Items::HABANBERRY
            | Items::COLBURBERRY
            | Items::BABIRIBERRY
            | Items::CHILANBERRY
            | Items::ROSELIBERRY
    )
}

/*
NormalGem, FlyingGem, etc.
*/
fn power_up_gem(
    attacking_side_ref: &SideReference,
    attacking_pkmn: &mut Pokemon,
    choice: &mut Choice,
    gem_type: PokemonType,
    instructions: &mut StateInstructions,
) {
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L104): damaging moves only
    if &choice.move_type == &gem_type && choice.category != MoveCategory::Status {
        #[cfg(feature = "gen5")]
        {
            choice.base_power *= 1.5;
        }
        #[cfg(not(feature = "gen5"))]
        {
            choice.base_power *= 5325.0 / 4096.0;
        }

        // alpha-poke patch (2026-10-17, doc/engine-diff.md L164): used up by the hit (Showdown's
        // onSourceTryPrimaryHit: after the accuracy, Protect): a secondary on its user, so a
        // miss, a Protect or a full paralysis keeps it; before, it went as the move started
        let _ = (attacking_side_ref, attacking_pkmn, instructions);
        choice.add_or_create_secondaries(Secondary {
            chance: 100.0,
            effect: Effect::RemoveItem,
            target: MoveTarget::User,
        });
    }
}

pub fn is_gem(item: Items) -> bool {
    format!("{:?}", item).ends_with("GEM")
}

/*
Regarding berries:
    most berries (lum, sitrus, etc) activate right away when applicable, but there isn't
    logic in this engine to implement that. Attempting to activate these berries before the user's
    move AND at the end-of-turn should be accurate enough for a simulation. The item is
    removed after this is triggered so only one will take effect
*/
// alpha-poke patch (2026-10-16, doc/engine-diff.md L81): the Lum / Chesto Berry the holder's own
// Rest sets off, at once (Showdown's onUpdate)
pub fn rest_berry(side_ref: &SideReference, side: &mut Side, instructions: &mut StateInstructions) {
    match side.get_active_immutable().item {
        Items::LUMBERRY => lum_berry(side_ref, side, instructions),
        Items::CHESTOBERRY => chesto_berry(side_ref, side, instructions),
        _ => {}
    }
}

fn lum_berry(
    side_ref: &SideReference,
    attacking_side: &mut Side,
    instructions: &mut StateInstructions,
) {
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L45): confusion too (Showdown's onUpdate:
    // a status or confusion)
    if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::CONFUSION)
    {
        attacking_side
            .volatile_statuses
            .remove(&PokemonVolatileStatus::CONFUSION);
        instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: PokemonVolatileStatus::CONFUSION,
                },
            ));
    }
    let active_index = attacking_side.active_index;
    let active_pkmn = attacking_side.get_active();
    if active_pkmn.status != PokemonStatus::NONE {
        instructions
            .instruction_list
            .push(Instruction::ChangeStatus(ChangeStatusInstruction {
                side_ref: *side_ref,
                pokemon_index: active_index,
                new_status: PokemonStatus::NONE,
                old_status: active_pkmn.status,
            }));
        active_pkmn.status = PokemonStatus::NONE;
    }
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: Items::LUMBERRY,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = Items::LUMBERRY;
        set_last_item(active_pkmn, *side_ref, used, instructions);
    }
    active_pkmn.item = Items::NONE;
}

fn sitrus_berry(
    side_ref: &SideReference,
    attacking_side: &mut Side,
    instructions: &mut StateInstructions,
) {
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L137): not eaten under Heal Block
    // (Showdown's onTryEatItem: no heal), as the pinch berries
    if attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::HEALBLOCK)
    {
        return;
    }
    let active_pkmn = attacking_side.get_active();
    let heal_amount = cmp::min(active_pkmn.maxhp / 4, active_pkmn.maxhp - active_pkmn.hp);
    instructions
        .instruction_list
        .push(Instruction::Heal(HealInstruction {
            side_ref: *side_ref,
            heal_amount: heal_amount,
        }));
    active_pkmn.hp += heal_amount;
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: Items::SITRUSBERRY,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = Items::SITRUSBERRY;
        set_last_item(active_pkmn, *side_ref, used, instructions);
    }
    active_pkmn.item = Items::NONE;
}

// alpha-poke patch (2026-10-13): a berry curing one status (Lum Berry's effect)
fn status_berry(
    side_ref: &SideReference,
    attacking_side: &mut Side,
    item: Items,
    instructions: &mut StateInstructions,
) {
    lum_berry(side_ref, attacking_side, instructions);
    if let Some(Instruction::ChangeItem(ins)) = instructions.instruction_list.last_mut() {
        ins.current_item = item;
    }
}

// alpha-poke patch (2026-10-13): volatiles cured by Persim Berry / Mental Herb, with their
// durations
const MENTAL_HERB_CURES: [PokemonVolatileStatus; 6] = [
    PokemonVolatileStatus::TAUNT,
    PokemonVolatileStatus::ENCORE,
    PokemonVolatileStatus::DISABLE,
    PokemonVolatileStatus::TORMENT,
    PokemonVolatileStatus::HEALBLOCK,
    PokemonVolatileStatus::ATTRACT,
];

fn has_any(side: &Side, volatiles: &[PokemonVolatileStatus]) -> bool {
    volatiles.iter().any(|v| side.volatile_statuses.contains(v))
}

fn cure_volatiles_item(
    side_ref: &SideReference,
    side: &mut Side,
    item: Items,
    volatiles: &[PokemonVolatileStatus],
    instructions: &mut StateInstructions,
) {
    for v in volatiles {
        if !side.volatile_statuses.contains(v) {
            continue;
        }
        side.volatile_statuses.remove(v);
        instructions
            .instruction_list
            .push(Instruction::RemoveVolatileStatus(
                RemoveVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: *v,
                },
            ));
        let duration = match v {
            PokemonVolatileStatus::TAUNT => &mut side.volatile_status_durations.taunt,
            PokemonVolatileStatus::ENCORE => &mut side.volatile_status_durations.encore,
            PokemonVolatileStatus::HEALBLOCK => &mut side.volatile_status_durations.healblock,
            PokemonVolatileStatus::CONFUSION => &mut side.volatile_status_durations.confusion,
            _ => continue,
        };
        if *duration != 0 {
            instructions
                .instruction_list
                .push(Instruction::ChangeVolatileStatusDuration(
                    ChangeVolatileStatusDurationInstruction {
                        side_ref: *side_ref,
                        volatile_status: *v,
                        amount: -*duration,
                    },
                ));
            *duration = 0;
        }
    }
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: item,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = item;
        set_last_item(side.get_active(), *side_ref, used, instructions);
    }
    side.get_active().item = Items::NONE;
}

fn chesto_berry(
    side_ref: &SideReference,
    attacking_side: &mut Side,
    instructions: &mut StateInstructions,
) {
    let active_index = attacking_side.active_index;
    let active_pkmn = attacking_side.get_active();
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: Items::CHESTOBERRY,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = Items::CHESTOBERRY;
        set_last_item(active_pkmn, *side_ref, used, instructions);
    }
    active_pkmn.item = Items::NONE;
    add_remove_status_instructions(instructions, active_index, *side_ref, attacking_side);
}

// alpha-poke patch (2026-10-16, L24): Lansat Berry, Focus Energy (+2 crit stages)
fn lansat_berry(side_ref: &SideReference, side: &mut Side, instructions: &mut StateInstructions) {
    if !side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::FOCUSENERGY)
    {
        instructions
            .instruction_list
            .push(Instruction::ApplyVolatileStatus(
                ApplyVolatileStatusInstruction {
                    side_ref: *side_ref,
                    volatile_status: PokemonVolatileStatus::FOCUSENERGY,
                },
            ));
        side.volatile_statuses
            .insert(PokemonVolatileStatus::FOCUSENERGY);
    }
    let active = side.get_active();
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: active.item,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = active.item;
        set_last_item(active, *side_ref, used, instructions);
    }
    active.item = Items::NONE;
}

fn boost_berry(
    side_ref: &SideReference,
    state: &mut State,
    stat: PokemonBoostableStat,
    instructions: &mut StateInstructions,
) {
    // (L149: Ripen doubles a berry's, Showdown's onChangeBoost)
    let amount = if state.get_side_immutable(side_ref).get_active_immutable().ability
        == Abilities::RIPEN
    {
        2
    } else {
        1
    };
    apply_boost_instruction(
        state.get_side(side_ref),
        &stat,
        &amount,
        side_ref,
        side_ref,
        instructions,
    );
    let attacker = state.get_side(side_ref).get_active();
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: attacker.item,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = attacker.item;
        set_last_item(attacker, *side_ref, used, instructions);
    }
    attacker.item = Items::NONE;
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L24): the pinch berries (Figy, Wiki, Mago, Aguav,
// Iapapa: 1/3 of max HP at 1/4 HP or less, confusing a holder whose nature lowers the berry's
// stat; Oran: 10 HP at half or less), as Sitrus Berry; not eaten under Heal Block (Showdown's
// onTryEatItem)
fn pinch_berry_heal(pkmn: &Pokemon) -> Option<(i16, Option<PokemonBoostableStat>)> {
    let low = pkmn.hp <= pkmn.maxhp / 4
        || (pkmn.ability == Abilities::GLUTTONY && pkmn.hp <= pkmn.maxhp / 2);
    let stat = match pkmn.item {
        Items::FIGYBERRY => PokemonBoostableStat::Attack,
        Items::WIKIBERRY => PokemonBoostableStat::SpecialAttack,
        Items::MAGOBERRY => PokemonBoostableStat::Speed,
        Items::AGUAVBERRY => PokemonBoostableStat::SpecialDefense,
        Items::IAPAPABERRY => PokemonBoostableStat::Defense,
        Items::ORANBERRY if pkmn.hp <= pkmn.maxhp / 2 && pkmn.hp > 0 => return Some((10, None)),
        _ => return None,
    };
    if !low || pkmn.hp == 0 {
        return None;
    }
    Some((pkmn.maxhp / 3, Some(stat)))
}

fn nature_lowers(nature: &PokemonNature, stat: &PokemonBoostableStat) -> bool {
    use PokemonNature::*;
    match stat {
        PokemonBoostableStat::Attack => matches!(nature, BOLD | MODEST | CALM | TIMID),
        PokemonBoostableStat::Defense => matches!(nature, LONELY | MILD | GENTLE | HASTY),
        PokemonBoostableStat::SpecialAttack => matches!(nature, ADAMANT | IMPISH | CAREFUL | JOLLY),
        PokemonBoostableStat::SpecialDefense => matches!(nature, NAUGHTY | LAX | RASH | NAIVE),
        PokemonBoostableStat::Speed => matches!(nature, BRAVE | RELAXED | QUIET | SASSY),
        _ => false,
    }
}

fn pinch_berry(side_ref: &SideReference, side: &mut Side, instructions: &mut StateInstructions) {
    if side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::HEALBLOCK)
    {
        return;
    }
    let confused = side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::CONFUSION);
    let active = side.get_active();
    let Some((amount, stat)) = pinch_berry_heal(active) else {
        return;
    };
    let heal_amount = cmp::min(amount, active.maxhp - active.hp);
    if heal_amount > 0 {
        instructions
            .instruction_list
            .push(Instruction::Heal(HealInstruction {
                side_ref: *side_ref,
                heal_amount,
            }));
        active.hp += heal_amount;
    }
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: active.item,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = active.item;
        set_last_item(active, *side_ref, used, instructions);
    }
    active.item = Items::NONE;
    if let Some(stat) = stat {
        if !confused && nature_lowers(&active.nature, &stat) {
            instructions
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
    }
}

// alpha-poke patch (2026-10-16, L24): Room Service, when Trick Room is up: the holder's Speed -1,
// used up (Showdown: on switching in under it, and when Trick Room starts)
pub fn room_service(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    if !state.trick_room.active {
        return;
    }
    let side = state.get_side(side_ref);
    if side.get_active_immutable().item != Items::ROOMSERVICE || side.get_active_immutable().hp == 0
    {
        return;
    }
    apply_boost_instruction(
        side,
        &PokemonBoostableStat::Speed,
        &-1,
        side_ref,
        side_ref,
        instructions,
    );
    instructions
        .instruction_list
        .push(Instruction::ChangeItem(ChangeItemInstruction {
            side_ref: *side_ref,
            current_item: Items::ROOMSERVICE,
            new_item: Items::NONE,
        }));
    // (L57: used up: its last item)
    {
        let used = Items::ROOMSERVICE;
        set_last_item(side.get_active(), *side_ref, used, instructions);
    }
    side.get_active().item = Items::NONE;
}

pub fn item_before_move(
    state: &mut State,
    choice: &mut Choice,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    // (L152: the attacker's Unnerve stops the target's resist berry, Showdown's onFoeTryEatItem)
    let berry_unnerved = unnerved(state, &side_ref.get_other_side());
    let (attacking_side, defending_side) = state.get_both_sides(side_ref);
    let active_pkmn = attacking_side.get_active();
    let defending_pkmn = defending_side.get_active();
    match defending_pkmn.item {
        x if is_resist_berry(x) && berry_unnerved => {}
        Items::CHOPLEBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::CHOPLEBERRY,
            &PokemonType::FIGHTING,
            instructions,
        ),
        Items::BABIRIBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::BABIRIBERRY,
            &PokemonType::STEEL,
            instructions,
        ),
        Items::CHARTIBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::CHARTIBERRY,
            &PokemonType::ROCK,
            instructions,
        ),
        Items::CHILANBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::CHILANBERRY,
            &PokemonType::NORMAL,
            instructions,
        ),
        Items::COBABERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::COBABERRY,
            &PokemonType::FLYING,
            instructions,
        ),
        Items::COLBURBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::COLBURBERRY,
            &PokemonType::DARK,
            instructions,
        ),
        Items::HABANBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::HABANBERRY,
            &PokemonType::DRAGON,
            instructions,
        ),
        Items::KASIBBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::KASIBBERRY,
            &PokemonType::GHOST,
            instructions,
        ),
        Items::KEBIABERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::KEBIABERRY,
            &PokemonType::POISON,
            instructions,
        ),
        Items::OCCABERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::OCCABERRY,
            &PokemonType::FIRE,
            instructions,
        ),
        Items::PASSHOBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::PASSHOBERRY,
            &PokemonType::WATER,
            instructions,
        ),
        Items::PAYAPABERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::PAYAPABERRY,
            &PokemonType::PSYCHIC,
            instructions,
        ),
        Items::RINDOBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::RINDOBERRY,
            &PokemonType::GRASS,
            instructions,
        ),
        Items::ROSELIBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::ROSELIBERRY,
            &PokemonType::FAIRY,
            instructions,
        ),
        Items::SHUCABERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::SHUCABERRY,
            &PokemonType::GROUND,
            instructions,
        ),
        Items::TANGABERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::TANGABERRY,
            &PokemonType::BUG,
            instructions,
        ),
        Items::WACANBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::WACANBERRY,
            &PokemonType::ELECTRIC,
            instructions,
        ),
        Items::YACHEBERRY => damage_reduction_berry(
            defending_pkmn,
            side_ref,
            choice,
            Items::YACHEBERRY,
            &PokemonType::ICE,
            instructions,
        ),
        _ => {}
    }
    match active_pkmn.item {
        Items::NORMALGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::NORMAL,
            instructions,
        ),
        Items::BUGGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::BUG,
            instructions,
        ),
        Items::ELECTRICGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::ELECTRIC,
            instructions,
        ),
        Items::FIGHTINGGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::FIGHTING,
            instructions,
        ),
        Items::GHOSTGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::GHOST,
            instructions,
        ),
        Items::PSYCHICGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::PSYCHIC,
            instructions,
        ),
        Items::FLYINGGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::FLYING,
            instructions,
        ),
        Items::STEELGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::STEEL,
            instructions,
        ),
        Items::ICEGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::ICE,
            instructions,
        ),
        Items::POISONGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::POISON,
            instructions,
        ),
        Items::FIREGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::FIRE,
            instructions,
        ),
        Items::DRAGONGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::DRAGON,
            instructions,
        ),
        Items::GROUNDGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::GROUND,
            instructions,
        ),
        Items::WATERGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::WATER,
            instructions,
        ),
        Items::DARKGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::DARK,
            instructions,
        ),
        Items::ROCKGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::ROCK,
            instructions,
        ),
        Items::GRASSGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::GRASS,
            instructions,
        ),
        Items::FAIRYGEM => power_up_gem(
            side_ref,
            active_pkmn,
            choice,
            PokemonType::FAIRY,
            instructions,
        ),
        // (L147: its own berries / Mental Herb: item_update, Showdown's Update)
        // (L179: a Choice item's lock: choice_lock, past the BeforeMove)
        Items::PROTECTIVEPADS => {
            choice.flags.contact = false;
        }
        _ => {}
    }
}

pub fn item_on_switch_in(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    // alpha-poke patch (2026-10-16, L24)
    if state
        .get_side_immutable(side_ref)
        .get_active_immutable()
        .item
        == Items::ROOMSERVICE
    {
        room_service(state, side_ref, instructions);
        return;
    }
    terrain_seed(state, side_ref, instructions);
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L148): a terrain seed goes off in its terrain
// (Showdown's onStart -- the switch-in -- and onTerrainChange: generate_instructions'
// field_change_events)
pub fn terrain_seed(state: &mut State, side_ref: &SideReference, instructions: &mut StateInstructions) {
    if state.get_side_immutable(side_ref).get_active_immutable().hp == 0 {
        return;
    }
    let active_terrain = state.get_terrain();
    let switching_in_side = state.get_side(side_ref);
    let switching_in_pkmn = switching_in_side.get_active_immutable();
    match switching_in_pkmn.item {
        Items::ELECTRICSEED => {
            if active_terrain == Terrain::ELECTRICTERRAIN {
                if apply_boost_instruction(
                    switching_in_side,
                    &PokemonBoostableStat::Defense,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                ) {
                    state.get_side(side_ref).get_active().item = Items::NONE;
                    instructions.instruction_list.push(Instruction::ChangeItem(
                        ChangeItemInstruction {
                            side_ref: side_ref.clone(),
                            current_item: Items::ELECTRICSEED,
                            new_item: Items::NONE,
                        },
                    ));
                    // (L178: used up, its last item: Showdown's useItem)
                    set_last_item(
                        state.get_side(side_ref).get_active(),
                        *side_ref,
                        Items::ELECTRICSEED,
                        instructions,
                    );
                }
            }
        }
        Items::GRASSYSEED => {
            if active_terrain == Terrain::GRASSYTERRAIN {
                if apply_boost_instruction(
                    switching_in_side,
                    &PokemonBoostableStat::Defense,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                ) {
                    state.get_side(side_ref).get_active().item = Items::NONE;
                    instructions.instruction_list.push(Instruction::ChangeItem(
                        ChangeItemInstruction {
                            side_ref: side_ref.clone(),
                            current_item: Items::GRASSYSEED,
                            new_item: Items::NONE,
                        },
                    ));
                    // (L178: used up, its last item: Showdown's useItem)
                    set_last_item(
                        state.get_side(side_ref).get_active(),
                        *side_ref,
                        Items::GRASSYSEED,
                        instructions,
                    );
                }
            }
        }
        Items::MISTYSEED => {
            if active_terrain == Terrain::MISTYTERRAIN {
                if apply_boost_instruction(
                    switching_in_side,
                    &PokemonBoostableStat::SpecialDefense,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                ) {
                    state.get_side(side_ref).get_active().item = Items::NONE;
                    instructions.instruction_list.push(Instruction::ChangeItem(
                        ChangeItemInstruction {
                            side_ref: side_ref.clone(),
                            current_item: Items::MISTYSEED,
                            new_item: Items::NONE,
                        },
                    ));
                    // (L178: used up, its last item: Showdown's useItem)
                    set_last_item(
                        state.get_side(side_ref).get_active(),
                        *side_ref,
                        Items::MISTYSEED,
                        instructions,
                    );
                }
            }
        }
        Items::PSYCHICSEED => {
            if active_terrain == Terrain::PSYCHICTERRAIN {
                if apply_boost_instruction(
                    switching_in_side,
                    &PokemonBoostableStat::SpecialDefense,
                    &1,
                    side_ref,
                    side_ref,
                    instructions,
                ) {
                    state.get_side(side_ref).get_active().item = Items::NONE;
                    instructions.instruction_list.push(Instruction::ChangeItem(
                        ChangeItemInstruction {
                            side_ref: side_ref.clone(),
                            current_item: Items::PSYCHICSEED,
                            new_item: Items::NONE,
                        },
                    ));
                    // (L178: used up, its last item: Showdown's useItem)
                    set_last_item(
                        state.get_side(side_ref).get_active(),
                        *side_ref,
                        Items::PSYCHICSEED,
                        instructions,
                    );
                }
            }
        }
        _ => {}
    }
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L75): the HP berries as soon as a hit takes
// their holder there (Showdown's onUpdate): Sitrus at 1/2, the pinch heal berries / Oran, the stat
// berries at 1/4 (1/2 with Gluttony); not under Heal Block for the heals
// alpha-poke patch (2026-10-17, doc/engine-diff.md L147): Showdown's Update for one active's item:
// its onUpdate handlers (the HP, stat and status berries, Mental Herb), the berries through
// eatItem (alive, not under Unnerve; the HP ones not under Heal Block: TryEatItem). The one place
// the engine runs them (generate_instructions::update, at Showdown's Update points: after a hit,
// after an action, after the weather's damage); before, three diverging copies did (at a hit's
// damage, before the holder's move, at the end of the turn). Starf Berry: its own branches;
// Leppa Berry: at the PP use; Booster Energy: abilities::paradox_update
pub fn item_update(state: &mut State, side_ref: &SideReference, instructions: &mut StateInstructions) {
    let a = state.get_side_immutable(side_ref).get_active_immutable();
    if a.hp <= 0 || a.item == Items::NONE || a.ability == Abilities::KLUTZ {
        return;
    }
    if unnerved(state, side_ref) {
        return;
    }
    let held = a.item;
    item_update_handlers(state, side_ref, instructions);
    let side = state.get_side(side_ref);
    if is_berry(held) && side.get_active_immutable().item == Items::NONE {
        cheek_pouch(side, side_ref, instructions);
    }
}

// alpha-poke patch (2026-10-17, doc/engine-diff.md L159): Cheek Pouch, a third of its max HP when
// its holder eats a berry (Showdown's onEatItem; not under Heal Block)
pub fn cheek_pouch(side: &mut Side, side_ref: &SideReference, instructions: &mut StateInstructions) {
    let heal_blocked = side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::HEALBLOCK);
    let a = side.get_active();
    if a.ability != Abilities::CHEEKPOUCH || a.hp == 0 || heal_blocked {
        return;
    }
    let amount = cmp::min(a.maxhp / 3, a.maxhp - a.hp);
    if amount > 0 {
        a.hp += amount;
        instructions
            .instruction_list
            .push(Instruction::Heal(HealInstruction {
                side_ref: *side_ref,
                heal_amount: amount,
            }));
    }
}

fn item_update_handlers(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
) {
    let side = state.get_side(side_ref);
    let confused = side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::CONFUSION);
    let mental_herb_cures = has_any(side, &MENTAL_HERB_CURES);
    let a = side.get_active_immutable();
    let low = a.hp <= a.maxhp / 4 || (a.ability == Abilities::GLUTTONY && a.hp <= a.maxhp / 2);
    let status = a.status;
    match a.item {
        Items::SITRUSBERRY if a.hp <= a.maxhp / 2 => sitrus_berry(side_ref, side, instructions),
        Items::FIGYBERRY
        | Items::WIKIBERRY
        | Items::MAGOBERRY
        | Items::AGUAVBERRY
        | Items::IAPAPABERRY
        | Items::ORANBERRY
            if pinch_berry_heal(a).is_some() =>
        {
            pinch_berry(side_ref, side, instructions)
        }
        Items::LIECHIBERRY if low => {
            boost_berry(side_ref, state, PokemonBoostableStat::Attack, instructions)
        }
        Items::GANLONBERRY if low => {
            boost_berry(side_ref, state, PokemonBoostableStat::Defense, instructions)
        }
        Items::PETAYABERRY if low => boost_berry(
            side_ref,
            state,
            PokemonBoostableStat::SpecialAttack,
            instructions,
        ),
        Items::APICOTBERRY if low => boost_berry(
            side_ref,
            state,
            PokemonBoostableStat::SpecialDefense,
            instructions,
        ),
        Items::SALACBERRY if low => {
            boost_berry(side_ref, state, PokemonBoostableStat::Speed, instructions)
        }
        Items::LANSATBERRY if low => lansat_berry(side_ref, side, instructions),
        Items::LUMBERRY if status != PokemonStatus::NONE || confused => {
            lum_berry(side_ref, side, instructions)
        }
        Items::PECHABERRY if matches!(status, PokemonStatus::POISON | PokemonStatus::TOXIC) => {
            status_berry(side_ref, side, Items::PECHABERRY, instructions)
        }
        Items::CHERIBERRY if status == PokemonStatus::PARALYZE => {
            status_berry(side_ref, side, Items::CHERIBERRY, instructions)
        }
        Items::RAWSTBERRY if status == PokemonStatus::BURN => {
            status_berry(side_ref, side, Items::RAWSTBERRY, instructions)
        }
        Items::ASPEARBERRY if status == PokemonStatus::FREEZE => {
            status_berry(side_ref, side, Items::ASPEARBERRY, instructions)
        }
        Items::CHESTOBERRY if status == PokemonStatus::SLEEP => {
            chesto_berry(side_ref, side, instructions)
        }
        Items::PERSIMBERRY if confused => cure_volatiles_item(
            side_ref,
            side,
            Items::PERSIMBERRY,
            &[PokemonVolatileStatus::CONFUSION],
            instructions,
        ),
        Items::MENTALHERB if mental_herb_cures => cure_volatiles_item(
            side_ref,
            side,
            Items::MENTALHERB,
            &MENTAL_HERB_CURES,
            instructions,
        ),
        _ => {}
    }
}

pub fn item_end_of_turn(
    state: &mut State,
    side_ref: &SideReference,
    instructions: &mut StateInstructions,
    before_status: bool,
) {
    if unnerved(state, side_ref) {
        return;
    }
    let attacking_side = state.get_side(side_ref);
    // alpha-poke patch (2026-10-16): Leftovers / Black Sludge come before the status damage
    // (Showdown's residual order 5; burn / poison 9-10), the orbs after it (28)
    let early = matches!(
        attacking_side.get_active_immutable().item,
        Items::LEFTOVERS | Items::BLACKSLUDGE
    );
    if early != before_status {
        return;
    }
    // alpha-poke patch (2026-10-13): read before the active is borrowed
    let confused = attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::CONFUSION);
    let mental_herb_cures = has_any(attacking_side, &MENTAL_HERB_CURES);
    // alpha-poke patch (2026-10-16, doc/engine-diff.md L19): no healing under Heal Block
    let heal_blocked = attacking_side
        .volatile_statuses
        .contains(&PokemonVolatileStatus::HEALBLOCK);
    let active_pkmn = attacking_side.get_active();
    match active_pkmn.item {
        // (L147: the berries / Mental Herb: item_update, Showdown's Update)
        // alpha-poke patch (2026-10-16, L24): Sticky Barb, 1/8 at the end of every turn (Showdown's
        // residual order 28, with the orbs)
        // (L83: not through Magic Guard)
        Items::STICKYBARB if active_pkmn.ability != Abilities::MAGICGUARD => {
            let damage_amount = cmp::min(cmp::max(active_pkmn.maxhp / 8, 1), active_pkmn.hp);
            instructions
                .instruction_list
                .push(Instruction::Damage(DamageInstruction {
                    side_ref: *side_ref,
                    damage_amount,
                }));
            active_pkmn.hp -= damage_amount;
        }
        // alpha-poke patch (2026-10-16, L24): Micle Berry, eaten at the end of the turn at 1/4 HP
        Items::MICLEBERRY
            if active_pkmn.hp > 0
                && (active_pkmn.hp <= active_pkmn.maxhp / 4
                    || (active_pkmn.ability == Abilities::GLUTTONY
                        && active_pkmn.hp <= active_pkmn.maxhp / 2)) =>
        {
            instructions
                .instruction_list
                .push(Instruction::ChangeItem(ChangeItemInstruction {
                    side_ref: *side_ref,
                    current_item: Items::MICLEBERRY,
                    new_item: Items::NONE,
                }));
            // (L57: used up: its last item)
            {
                let used = Items::MICLEBERRY;
                set_last_item(active_pkmn, *side_ref, used, instructions);
            }
            active_pkmn.item = Items::NONE;
            if !attacking_side
                .volatile_statuses
                .contains(&PokemonVolatileStatus::MICLEBERRY)
            {
                instructions
                    .instruction_list
                    .push(Instruction::ApplyVolatileStatus(
                        ApplyVolatileStatusInstruction {
                            side_ref: *side_ref,
                            volatile_status: PokemonVolatileStatus::MICLEBERRY,
                        },
                    ));
                attacking_side
                    .volatile_statuses
                    .insert(PokemonVolatileStatus::MICLEBERRY);
            }
        }
        Items::BLACKSLUDGE => {
            if active_pkmn.has_type(&PokemonType::POISON) {
                if active_pkmn.hp < active_pkmn.maxhp && !heal_blocked {
                    let heal_amount =
                        cmp::min(active_pkmn.maxhp / 16, active_pkmn.maxhp - active_pkmn.hp);
                    let ins = Instruction::Heal(HealInstruction {
                        side_ref: side_ref.clone(),
                        heal_amount: heal_amount,
                    });
                    active_pkmn.hp += heal_amount;
                    instructions.instruction_list.push(ins);
                }
            } else {
                // alpha-poke patch (2026-10-16, doc/engine-diff.md L9): a non-Poison holder loses
                // 1/8 of its max HP (Showdown: this.damage(baseMaxhp / 8), at least 1), also at
                // full HP; was min(maxhp / 16, maxhp - hp), the heal's formula (L83: not through
                // Magic Guard)
                let damage_amount = if active_pkmn.ability == Abilities::MAGICGUARD {
                    0
                } else {
                    cmp::min(cmp::max(active_pkmn.maxhp / 8, 1), active_pkmn.hp)
                };
                if damage_amount > 0 {
                    let ins = Instruction::Damage(DamageInstruction {
                        side_ref: side_ref.clone(),
                        damage_amount: damage_amount,
                    });
                    active_pkmn.hp -= damage_amount;
                    instructions.instruction_list.push(ins);
                }
            }
        }
        Items::FLAMEORB => {
            if !immune_to_status(state, &MoveTarget::User, side_ref, &PokemonStatus::BURN) {
                let side = state.get_side(side_ref);
                let ins = Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: side_ref.clone(),
                    pokemon_index: side.active_index,
                    new_status: PokemonStatus::BURN,
                    old_status: PokemonStatus::NONE,
                });
                side.get_active().status = PokemonStatus::BURN;
                instructions.instruction_list.push(ins);
            }
        }
        Items::LEFTOVERS => {
            let attacker = state.get_side(side_ref).get_active();
            if attacker.hp < attacker.maxhp && !heal_blocked {
                let heal_amount = cmp::min(attacker.maxhp / 16, attacker.maxhp - attacker.hp);
                let ins = Instruction::Heal(HealInstruction {
                    side_ref: side_ref.clone(),
                    heal_amount: heal_amount,
                });
                attacker.hp += heal_amount;
                instructions.instruction_list.push(ins);
            }
        }
        Items::TOXICORB => {
            if !immune_to_status(state, &MoveTarget::User, side_ref, &PokemonStatus::TOXIC) {
                let side = state.get_side(side_ref);
                let ins = Instruction::ChangeStatus(ChangeStatusInstruction {
                    side_ref: side_ref.clone(),
                    pokemon_index: side.active_index,
                    new_status: PokemonStatus::TOXIC,
                    old_status: PokemonStatus::NONE,
                });
                side.get_active().status = PokemonStatus::TOXIC;
                instructions.instruction_list.push(ins);
            }
        }
        _ => {}
    }
}

pub fn item_modify_attack_against(
    state: &State,
    attacking_choice: &mut Choice,
    attacking_side_ref: &SideReference,
) {
    if unnerved(state, &attacking_side_ref.get_other_side()) {
        return;
    }
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);
    match defending_side.get_active_immutable().item {
        Items::ABSORBBULB => {
            if attacking_choice.move_type == PokemonType::WATER {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::Boost(StatBoosts {
                        attack: 0,
                        defense: 0,
                        special_attack: 1,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    }),
                    target: MoveTarget::Opponent,
                });
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::Opponent,
                });
            }
        }
        Items::AIRBALLOON => {
            // alpha-poke patch (L32): not when grounded by Smack Down
            if attacking_choice.move_type == PokemonType::GROUND
                && attacking_choice.move_id != Choices::THOUSANDARROWS
                && !super::damage_calc::grounded_by_effect(
                    defending_side,
                    defending_side.get_active_immutable(),
                )
            {
                attacking_choice.base_power = 0.0;
            } else if attacking_choice.target == MoveTarget::Opponent
                && attacking_choice.category != MoveCategory::Status
            {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::Opponent,
                });
            }
        }
        Items::ASSAULTVEST => {
            if attacking_choice.targets_special_defense() {
                attacking_choice.defense_modifier *= 1.5;
            }
        }
        Items::METALPOWDER if attacking_side.get_active_immutable().id == PokemonName::DITTO => {
            attacking_choice.base_power /= 1.5;
        }
        Items::CELLBATTERY => {
            if attacking_choice.move_type == PokemonType::ELECTRIC {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::Boost(StatBoosts {
                        attack: 1,
                        defense: 0,
                        special_attack: 0,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    }),
                    target: MoveTarget::Opponent,
                });
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::Opponent,
                });
            }
        }
        Items::EVIOLITE => {
            attacking_choice.defense_modifier *= 1.5;
        }
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): used up by the hit that triggers
        // them (Showdown's onAfterMoveSecondary / onDamagingHit / onHit)
        Items::KEEBERRY | Items::MARANGABERRY | Items::SNOWBALL | Items::LUMINOUSMOSS => {
            let item = defending_side.get_active_immutable().item;
            // (Kee / Maranga trigger after the move's own effects: Knock Off, Thief / Covet and
            // Bug Bite / Pluck take the berry first)
            let takes_item = matches!(
                attacking_choice.move_id,
                Choices::KNOCKOFF
                    | Choices::THIEF
                    | Choices::COVET
                    | Choices::BUGBITE
                    | Choices::PLUCK
            );
            let triggers = match item {
                Items::KEEBERRY => {
                    attacking_choice.category == MoveCategory::Physical && !takes_item
                }
                Items::MARANGABERRY => {
                    attacking_choice.category == MoveCategory::Special && !takes_item
                }
                Items::SNOWBALL => {
                    attacking_choice.category != MoveCategory::Status
                        && attacking_choice.move_type == PokemonType::ICE
                }
                _ => {
                    attacking_choice.category != MoveCategory::Status
                        && attacking_choice.move_type == PokemonType::WATER
                }
            };
            if triggers {
                let mut boosts = StatBoosts {
                    attack: 0,
                    defense: 0,
                    special_attack: 0,
                    special_defense: 0,
                    speed: 0,
                    accuracy: 0,
                };
                // (L149: Ripen doubles a berry's, Showdown's onChangeBoost)
                let ripen = if defending_side.get_active_immutable().ability == Abilities::RIPEN
                    && matches!(item, Items::KEEBERRY | Items::MARANGABERRY)
                {
                    2
                } else {
                    1
                };
                match item {
                    Items::KEEBERRY => boosts.defense = ripen,
                    Items::SNOWBALL => boosts.attack = 1,
                    _ => boosts.special_defense = ripen,
                }
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::Boost(boosts),
                    target: MoveTarget::Opponent,
                });
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::Opponent,
                });
            }
        }
        Items::JABOCABERRY | Items::ROWAPBERRY => {
            let category = if defending_side.get_active_immutable().item == Items::JABOCABERRY {
                MoveCategory::Physical
            } else {
                MoveCategory::Special
            };
            if attacking_choice.category == category
                && attacking_side.get_active_immutable().ability != Abilities::MAGICGUARD
            {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::Heal(-0.125),
                    target: MoveTarget::User,
                });
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::Opponent,
                });
            }
        }
        Items::ENIGMABERRY => {
            let defender = defending_side.get_active_immutable();
            if attacking_choice.category != MoveCategory::Status
                && type_effectiveness_modifier(&attacking_choice.move_type, defender) > 1.0
                && !defending_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::HEALBLOCK)
            {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::Heal(0.25),
                    target: MoveTarget::Opponent,
                });
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::Opponent,
                });
            }
        }
        // (L151: Rocky Helmet: abilities::ability_damaging_hit, once per hit)
        Items::WEAKNESSPOLICY => {
            // (L53: not by a fixed damage)
            if attacking_choice.category != MoveCategory::Status
                && !fixed_damage_move(&attacking_choice.move_id)
                && move_type_effectiveness(
                    &attacking_choice,
                    &defending_side.get_active_immutable(),
                ) > 1.0
            {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::Boost(StatBoosts {
                        attack: 2,
                        defense: 0,
                        special_attack: 2,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    }),
                    target: MoveTarget::Opponent,
                });
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::Opponent,
                });
            }
        }
        Items::SOULDEW => {
            if defending_side.get_active_immutable().id == PokemonName::LATIOS
                || defending_side.get_active_immutable().id == PokemonName::LATIAS
            {
                #[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
                if attacking_choice.category == MoveCategory::Special {
                    attacking_choice.base_power /= 1.5;
                }
            }
        }
        _ => {}
    }
}

pub fn item_modify_attack_being_used(
    state: &State,
    attacking_choice: &mut Choice,
    attacking_side_ref: &SideReference,
) {
    let (attacking_side, defending_side) = state.get_both_sides_immutable(attacking_side_ref);
    match attacking_side.get_active_immutable().item {
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24): a 10% flinch for a damaging move
        // without one
        Items::KINGSROCK | Items::RAZORFANG => {
            let has_flinch = attacking_choice.secondaries.as_ref().is_some_and(|s| {
                s.iter()
                    .any(|x| x.effect == Effect::VolatileStatus(PokemonVolatileStatus::FLINCH))
            });
            if attacking_choice.category != MoveCategory::Status && !has_flinch {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 10.0,
                    effect: Effect::VolatileStatus(PokemonVolatileStatus::FLINCH),
                    target: MoveTarget::Opponent,
                });
            }
        }
        Items::WELLSPRINGMASK => match attacking_side.get_active_immutable().id {
            PokemonName::OGERPONWELLSPRING | PokemonName::OGERPONWELLSPRINGTERA => {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
            _ => {}
        },
        Items::HEARTHFLAMEMASK => match attacking_side.get_active_immutable().id {
            PokemonName::OGERPONHEARTHFLAME | PokemonName::OGERPONHEARTHFLAMETERA => {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
            _ => {}
        },
        Items::CORNERSTONEMASK => match attacking_side.get_active_immutable().id {
            PokemonName::OGERPONCORNERSTONE | PokemonName::OGERPONCORNERSTONETERA => {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
            _ => {}
        },
        Items::BLACKBELT => {
            if attacking_choice.move_type == PokemonType::FIGHTING {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::BLACKGLASSES => {
            if attacking_choice.move_type == PokemonType::DARK {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::CHARCOAL => {
            if attacking_choice.move_type == PokemonType::FIRE {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::CHOICEBAND => {
            if attacking_choice.category == MoveCategory::Physical {
                attacking_choice.attack_modifier *= 1.5;
            }
        }
        Items::CHOICESPECS => {
            if attacking_choice.category == MoveCategory::Special {
                attacking_choice.attack_modifier *= 1.5;
            }
        }
        Items::DRAGONFANG | Items::DRAGONSCALE => {
            if attacking_choice.move_type == PokemonType::DRAGON {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::EXPERTBELT => {
            if move_type_effectiveness(&attacking_choice, &defending_side.get_active_immutable())
                > 1.0
            {
                attacking_choice.damage_modifier *= 4915.0 / 4096.0;
            }
        }
        Items::FAIRYFEATHER => {
            if attacking_choice.move_type == PokemonType::FAIRY {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::LIFEORB => {
            // (L199: a hit Ice Face took too -- a status move by now: Showdown's recoil is the
            // move's onAfterMoveSecondarySelf, whatever damage it did)
            if attacking_choice.category != MoveCategory::Status || attacking_choice.face_break {
                attacking_choice.damage_modifier *= 5324.0 / 4096.0;

                #[cfg(feature = "gen4")]
                if !defending_side
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::SUBSTITUTE)
                    && attacking_side.get_active_immutable().ability != Abilities::MAGICGUARD
                {
                    attacking_choice.add_or_create_secondaries(Secondary {
                        chance: 100.0,
                        effect: Effect::Heal(-0.1),
                        target: MoveTarget::User,
                    });
                }

                // alpha-poke patch (2026-10-16, doc/engine-diff.md L55): no recoil on a move
                // Sheer Force boosts (Showdown skips AfterMoveSecondarySelf; the secondaries are
                // gone by now: the move's own data)
                let sheer_force = attacking_side.get_active_immutable().ability
                    == Abilities::SHEERFORCE
                    && MOVES
                        .get(&attacking_choice.move_id)
                        .is_some_and(super::abilities::sheer_force_applies);
                #[cfg(not(feature = "gen4"))]
                if attacking_side.get_active_immutable().ability != Abilities::MAGICGUARD
                    && !sheer_force
                {
                    attacking_choice.add_or_create_secondaries(Secondary {
                        chance: 100.0,
                        effect: Effect::Heal(-0.1),
                        target: MoveTarget::User,
                    });
                }
            }
        }
        Items::METALCOAT => {
            if attacking_choice.move_type == PokemonType::STEEL {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::MUSCLEBAND => {
            if attacking_choice.category == MoveCategory::Physical {
                attacking_choice.base_power *= 4505.0 / 4096.0;
            }
        }
        Items::MYSTICWATER => {
            if attacking_choice.move_type == PokemonType::WATER {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::NEVERMELTICE => {
            if attacking_choice.move_type == PokemonType::ICE {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::PINKBOW | Items::POLKADOTBOW => {
            if attacking_choice.move_type == PokemonType::NORMAL {
                attacking_choice.base_power *= 4505.0 / 4096.0;
            }
        }
        Items::ODDINCENSE => {
            if attacking_choice.move_type == PokemonType::PSYCHIC {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::POISONBARB => {
            if attacking_choice.move_type == PokemonType::POISON {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::PUNCHINGGLOVE => {
            if attacking_choice.flags.punch {
                attacking_choice.base_power *= 4505.0 / 4096.0;
                attacking_choice.flags.contact = false
            }
        }
        Items::SEAINCENSE => {
            if attacking_choice.move_type == PokemonType::WATER {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SHARPBEAK => {
            if attacking_choice.move_type == PokemonType::FLYING {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        // (L209: Shell Bell's heal is its own, after the drain: generate_instructions)
        Items::SILKSCARF => {
            if attacking_choice.move_type == PokemonType::NORMAL {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SILVERPOWDER => {
            if attacking_choice.move_type == PokemonType::BUG {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SOFTSAND => {
            if attacking_choice.move_type == PokemonType::GROUND {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SPELLTAG => {
            if attacking_choice.move_type == PokemonType::GHOST {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::MIRACLESEED => {
            if attacking_choice.move_type == PokemonType::GRASS {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SOULDEW => {
            if attacking_side.get_active_immutable().id == PokemonName::LATIOS
                || attacking_side.get_active_immutable().id == PokemonName::LATIAS
            {
                #[cfg(any(feature = "gen4", feature = "gen5", feature = "gen6"))]
                if attacking_choice.category == MoveCategory::Special {
                    attacking_choice.base_power *= 1.5;
                }

                #[cfg(not(any(feature = "gen4", feature = "gen5", feature = "gen6")))]
                if attacking_choice.move_type == PokemonType::DRAGON
                    || attacking_choice.move_type == PokemonType::PSYCHIC
                {
                    attacking_choice.base_power *= 4915.0 / 4096.0;
                }
            }
        }
        Items::GRISEOUSORB | Items::GRISEOUSCORE => {
            if [PokemonName::GIRATINAORIGIN, PokemonName::GIRATINA]
                .contains(&attacking_side.get_active_immutable().id)
            {
                if attacking_choice.move_type == PokemonType::DRAGON
                    || attacking_choice.move_type == PokemonType::GHOST
                {
                    attacking_choice.base_power *= 4915.0 / 4096.0;
                }
            }
        }
        Items::LUSTROUSORB | Items::LUSTROUSGLOBE => {
            if [PokemonName::PALKIAORIGIN, PokemonName::PALKIA]
                .contains(&attacking_side.get_active_immutable().id)
            {
                if attacking_choice.move_type == PokemonType::DRAGON
                    || attacking_choice.move_type == PokemonType::WATER
                {
                    attacking_choice.base_power *= 4915.0 / 4096.0;
                }
            }
        }
        Items::ADAMANTORB | Items::ADAMANTCRYSTAL => {
            if [PokemonName::DIALGAORIGIN, PokemonName::DIALGA]
                .contains(&attacking_side.get_active_immutable().id)
            {
                if attacking_choice.move_type == PokemonType::DRAGON
                    || attacking_choice.move_type == PokemonType::STEEL
                {
                    attacking_choice.base_power *= 4915.0 / 4096.0;
                }
            }
        }
        Items::THROATSPRAY => {
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L103): not after a Clangorous Soul
            // that fails (a third of the HP or less: Showdown's onTry)
            let attacker = attacking_side.get_active_immutable();
            let failed = attacking_choice.move_id == Choices::CLANGOROUSSOUL
                && attacker.hp <= attacker.maxhp / 3;
            if attacking_choice.flags.sound && !failed {
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::Boost(StatBoosts {
                        attack: 0,
                        defense: 0,
                        special_attack: 1,
                        special_defense: 0,
                        speed: 0,
                        accuracy: 0,
                    }),
                    target: MoveTarget::User,
                });
                attacking_choice.add_or_create_secondaries(Secondary {
                    chance: 100.0,
                    effect: Effect::RemoveItem,
                    target: MoveTarget::User,
                });
            }
        }
        Items::THICKCLUB => match attacking_side.get_active_immutable().id {
            PokemonName::CUBONE
            | PokemonName::MAROWAK
            | PokemonName::MAROWAKALOLA
            | PokemonName::MAROWAKALOLATOTEM => {
                attacking_choice.base_power *= 2.0;
            }
            _ => {}
        },
        Items::TWISTEDSPOON => {
            if attacking_choice.move_type == PokemonType::PSYCHIC {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::HARDSTONE => {
            if attacking_choice.move_type == PokemonType::ROCK {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::WAVEINCENSE => {
            if attacking_choice.move_type == PokemonType::WATER {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::MAGNET => {
            if attacking_choice.move_type == PokemonType::ELECTRIC {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::WISEGLASSES => {
            if attacking_choice.category == MoveCategory::Special {
                attacking_choice.base_power *= 4505.0 / 4096.0;
            }
        }
        Items::FISTPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::FIGHTING;
            }
            if attacking_choice.move_type == PokemonType::FIGHTING {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SKYPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::FLYING;
            }
            if attacking_choice.move_type == PokemonType::FLYING {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::TOXICPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::POISON;
            }
            if attacking_choice.move_type == PokemonType::POISON {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::EARTHPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::GROUND;
            }
            if attacking_choice.move_type == PokemonType::GROUND {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::STONEPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::ROCK;
            }
            if attacking_choice.move_type == PokemonType::ROCK {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::INSECTPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::BUG;
            }
            if attacking_choice.move_type == PokemonType::BUG {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SPOOKYPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::GHOST;
            }
            if attacking_choice.move_type == PokemonType::GHOST {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::IRONPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::STEEL;
            }
            if attacking_choice.move_type == PokemonType::STEEL {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::FLAMEPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::FIRE;
            }
            if attacking_choice.move_type == PokemonType::FIRE {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::SPLASHPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::WATER;
            }
            if attacking_choice.move_type == PokemonType::WATER {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::MEADOWPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::GRASS;
            }
            if attacking_choice.move_type == PokemonType::GRASS {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::ZAPPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::ELECTRIC;
            }
            if attacking_choice.move_type == PokemonType::ELECTRIC {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::MINDPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::PSYCHIC;
            }
            if attacking_choice.move_type == PokemonType::PSYCHIC {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::ICICLEPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::ICE;
            }
            if attacking_choice.move_type == PokemonType::ICE {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::DRACOPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::DRAGON;
            }
            if attacking_choice.move_type == PokemonType::DRAGON {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::DREADPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::DARK;
            }
            if attacking_choice.move_type == PokemonType::DARK {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::PIXIEPLATE => {
            if attacking_choice.move_id == Choices::JUDGMENT {
                attacking_choice.move_type = PokemonType::FAIRY;
            }
            if attacking_choice.move_type == PokemonType::FAIRY {
                attacking_choice.base_power *= 4915.0 / 4096.0;
            }
        }
        Items::LIGHTBALL => {
            if attacking_side
                .get_active_immutable()
                .id
                .is_pikachu_variant()
            {
                attacking_choice.base_power *= 2.0;
            }
        }
        _ => {}
    }
}
