use super::abilities::Abilities;
use super::items::Items;
use crate::choices::{Choices, MoveCategory, MOVES};
use crate::define_enum_with_from_str;
use crate::instruction::BoostInstruction;
use crate::instruction::{
    ChangeSideConditionInstruction, ChangeStatInstruction, ChangeType,
    ChangeVolatileStatusDurationInstruction, Instruction, RemoveVolatileStatusInstruction,
    StateInstructions,
};
use crate::pokemon::PokemonName;
use crate::state::VolatileStatusBitset;
use crate::state::{
    LastUsedMove, Pokemon, PokemonBoostableStat, PokemonIndex, PokemonMoveIndex, PokemonNature,
    PokemonSideCondition, PokemonStatus, PokemonType, Side, SideReference, State,
};
use core::panic;

// (L203: the IVs an inferred one is tried in: 31 and 0 first, the sets' usual ones -- two IVs can
// give one stat, e.g. 0 and 1, the new forme's stat not)
const IV_ORDER: [u16; 32] = [
    31, 0, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8,
    7, 6, 5, 4, 3, 2, 1,
];

// (L203: with an IV -- 31 for a state's own stats; recalculate_stats / update_max_hp infer it
// from the stat it has)
fn common_pkmn_stat_calc_iv(stat: u16, ev: u16, level: u16, iv: u16) -> u16 {
    ((2 * stat + iv + (ev / 4)) * level) / 100
}

// alpha-poke patch (2026-10-16, doc/engine-diff.md L79): Showdown's "Paradox" species (their
// Booster Energy cannot be taken; the data test checks the list against Showdown's tags)
pub const PARADOX: [PokemonName; 16] = [
    PokemonName::GREATTUSK,
    PokemonName::SCREAMTAIL,
    PokemonName::BRUTEBONNET,
    PokemonName::FLUTTERMANE,
    PokemonName::SLITHERWING,
    PokemonName::SANDYSHOCKS,
    PokemonName::IRONTREADS,
    PokemonName::IRONBUNDLE,
    PokemonName::IRONHANDS,
    PokemonName::IRONJUGULIS,
    PokemonName::IRONMOTH,
    PokemonName::IRONTHORNS,
    PokemonName::ROARINGMOON,
    PokemonName::IRONVALIANT,
    PokemonName::WALKINGWAKE,
    PokemonName::IRONLEAVES,
];

#[cfg(feature = "champions")]
fn stat_points_to_effective_ev(stat_points: u16) -> u16 {
    if stat_points == 0 {
        0
    } else {
        8 * stat_points - 4
    }
}

fn multiply_boost(boost_num: i8, stat_value: i16) -> i16 {
    match boost_num {
        -6 => stat_value * 2 / 8,
        -5 => stat_value * 2 / 7,
        -4 => stat_value * 2 / 6,
        -3 => stat_value * 2 / 5,
        -2 => stat_value * 2 / 4,
        -1 => stat_value * 2 / 3,
        0 => stat_value,
        1 => stat_value * 3 / 2,
        2 => stat_value * 4 / 2,
        3 => stat_value * 5 / 2,
        4 => stat_value * 6 / 2,
        5 => stat_value * 7 / 2,
        6 => stat_value * 8 / 2,
        _ => panic!("Invalid boost number: {}", boost_num),
    }
}

#[derive(Debug, PartialEq, Eq, Copy, Clone, Hash)]
pub enum MoveChoice {
    MoveTera(PokemonMoveIndex),
    MoveMega(PokemonMoveIndex),
    Move(PokemonMoveIndex),
    Switch(PokemonIndex),
    TeamPreview(PokemonIndex, PokemonIndex, PokemonIndex), // lead, second, third
    None,
}

impl MoveChoice {
    pub fn to_string(&self, side: &Side) -> String {
        match self {
            MoveChoice::MoveTera(index) => {
                format!("{}-tera", side.get_active_immutable().moves[&index].id).to_lowercase()
            }
            MoveChoice::MoveMega(index) => {
                format!("{}-mega", side.get_active_immutable().moves[&index].id).to_lowercase()
            }
            MoveChoice::Move(index) => {
                format!("{}", side.get_active_immutable().moves[&index].id).to_lowercase()
            }
            MoveChoice::Switch(index) => format!("{}", side.pokemon[*index].id).to_lowercase(),
            MoveChoice::TeamPreview(lead, second, third) => format!(
                "{},{},{}",
                side.pokemon[*lead].id, side.pokemon[*second].id, side.pokemon[*third].id
            )
            .to_lowercase(),
            MoveChoice::None => "No Move".to_string(),
        }
    }
    pub fn from_string(s: &str, side: &Side) -> Option<MoveChoice> {
        let s = s.to_lowercase();
        if s == "none" {
            return Some(MoveChoice::None);
        }

        let mut pkmn_iter = side.pokemon.into_iter();
        while let Some(pkmn) = pkmn_iter.next() {
            if pkmn.id.to_string().to_lowercase() == s
                && pkmn_iter.pokemon_index != side.active_index
            {
                return Some(MoveChoice::Switch(pkmn_iter.pokemon_index));
            }
        }
        let pkmn_id_strings = side
            .pokemon
            .pkmn
            .iter()
            .map(|pkmn| pkmn.id.to_string().to_lowercase())
            .collect::<Vec<String>>();
        let parts = s.split(',').collect::<Vec<&str>>();
        if parts.len() == 3
            && pkmn_id_strings.contains(&parts[0].to_string())
            && pkmn_id_strings.contains(&parts[1].to_string())
            && pkmn_id_strings.contains(&parts[2].to_string())
        {
            let lead_index = pkmn_id_strings
                .iter()
                .position(|id| id == parts[0])
                .unwrap();
            let second_index = pkmn_id_strings
                .iter()
                .position(|id| id == parts[1])
                .unwrap();
            let third_index = pkmn_id_strings
                .iter()
                .position(|id| id == parts[2])
                .unwrap();
            return Some(MoveChoice::TeamPreview(
                PokemonIndex::deserialize(&lead_index.to_string()),
                PokemonIndex::deserialize(&second_index.to_string()),
                PokemonIndex::deserialize(&third_index.to_string()),
            ));
        }

        // check if s endswith `-tera`
        // if it does, find the move with the name and return MoveChoice::MoveTera
        // if it doesn't, find the move with the name and return MoveChoice::Move
        let mut move_iter = side.get_active_immutable().moves.into_iter();
        let mut move_name = s;
        if move_name.ends_with("-tera") {
            move_name = move_name[..move_name.len() - 5].to_string();
            while let Some(mv) = move_iter.next() {
                if format!("{:?}", mv.id).to_lowercase() == move_name {
                    return Some(MoveChoice::MoveTera(move_iter.pokemon_move_index));
                }
            }
        } else if move_name.ends_with("-mega") {
            move_name = move_name[..move_name.len() - 5].to_string();
            while let Some(mv) = move_iter.next() {
                if format!("{:?}", mv.id).to_lowercase() == move_name {
                    return Some(MoveChoice::MoveMega(move_iter.pokemon_move_index));
                }
            }
        } else {
            while let Some(mv) = move_iter.next() {
                if format!("{:?}", mv.id).to_lowercase() == move_name {
                    return Some(MoveChoice::Move(move_iter.pokemon_move_index));
                }
            }
        }

        None
    }
}

define_enum_with_from_str! {
    #[repr(u8)]
    #[derive(PartialEq, Eq, Hash, Debug, Copy, Clone)]
    PokemonVolatileStatus {
        NONE,
        AQUARING,
        ATTRACT,
        AUTOTOMIZE,
        BANEFULBUNKER,
        BIDE,
        BOUNCE,
        BURNINGBULWARK,
        CHARGE,
        CONFUSION,
        CURSE,
        DEFENSECURL,
        DESTINYBOND,
        DIG,
        DISABLE,
        DIVE,
        ELECTRIFY,
        ELECTROSHOT,
        EMBARGO,
        ENCORE,
        ENDURE,
        FLASHFIRE,
        FLINCH,
        FLY,
        FOCUSENERGY,
        FOLLOWME,
        FORESIGHT,
        FREEZESHOCK,
        GASTROACID,
        GEOMANCY,
        GLAIVERUSH,
        GRUDGE,
        HEALBLOCK,
        HELPINGHAND,
        ICEBURN,
        IMPRISON,
        INGRAIN,
        KINGSSHIELD,
        LASERFOCUS,
        LEECHSEED,
        LIGHTSCREEN,
        LOCKEDMOVE,
        MAGICCOAT,
        MAGNETRISE,
        MAXGUARD,
        METEORBEAM,
        MINIMIZE,
        MIRACLEEYE,
        MUSTRECHARGE,
        NIGHTMARE,
        NORETREAT,
        OCTOLOCK,
        PARTIALLYTRAPPED,
        PERISH4,
        PERISH3,
        PERISH2,
        PERISH1,
        PHANTOMFORCE,
        POWDER,
        POWERSHIFT,
        POWERTRICK,
        PROTECT,
        PROTOSYNTHESISATK,
        PROTOSYNTHESISDEF,
        PROTOSYNTHESISSPA,
        PROTOSYNTHESISSPD,
        PROTOSYNTHESISSPE,
        QUARKDRIVEATK,
        QUARKDRIVEDEF,
        QUARKDRIVESPA,
        QUARKDRIVESPD,
        QUARKDRIVESPE,
        RAGE,
        RAGEPOWDER,
        RAZORWIND,
        REFLECT,
        ROOST,
        SALTCURE,
        SHADOWFORCE,
        SKULLBASH,
        SKYATTACK,
        SKYDROP,
        SILKTRAP,
        SLOWSTART,
        SMACKDOWN,
        SNATCH,
        SOLARBEAM,
        SOLARBLADE,
        SPARKLINGARIA,
        SPIKYSHIELD,
        SPOTLIGHT,
        STOCKPILE,
        SUBSTITUTE,
        SYRUPBOMB,
        TARSHOT,
        TAUNT,
        TELEKINESIS,
        THROATCHOP,
        TRUANT,
        TORMENT,
        TYPECHANGE,
        UNBURDEN,
        UPROAR,
        YAWN,
        // alpha-poke patch (2026-10-16, doc/engine-diff.md L24), appended (the networks read bits
        // 1-103): Micle Berry's next accuracy, Metronome's consecutive uses (its count in
        // volatile_status_durations.metronome; on while it is above 0)
        MICLEBERRY,
        METRONOME,
        // (L36: transformed by Transform / Imposter; ends on a switch)
        TRANSFORM,
        // (L107: Mean Look / Block / Spider Web; ends when the trapper leaves)
        TRAPPED,
        // (L115: the side's move failed last turn -- Temper Flare / Stomping Tantrum double; from
        // the state given, cleared at the end of the turn)
        LASTMOVEFAILED,
        // (L141: the Protosynthesis / Quark Drive volatile came from Booster Energy -- Showdown's
        // fromBooster: the weather / terrain leaving does not end it; ends on a switch)
        FROMBOOSTER,
        // (L204: Cud Chew's berry to eat again: its counter in volatile_status_durations.cudchew,
        // the berry its last item; ends on a switch)
        CUDCHEW,
        // (L218: Protean / Libero has changed the type since the switch-in -- Showdown's
        // effectState.protean / libero; a Transform's new ability starts without it)
        PROTEAN,
    },
    default = NONE
}

define_enum_with_from_str! {
    #[repr(u8)]
    #[derive(Debug, PartialEq, Copy, Clone)]
    Weather {
        NONE,
        SUN,
        RAIN,
        SAND,
        HAIL,
        SNOW,
        HARSHSUN,
        HEAVYRAIN,
    }
}

define_enum_with_from_str! {
    #[repr(u8)]
    #[derive(Debug, PartialEq, Copy, Clone)]
    Terrain {
        NONE,
        ELECTRICTERRAIN,
        PSYCHICTERRAIN,
        MISTYTERRAIN,
        GRASSYTERRAIN,
    }
}

impl Pokemon {
    pub fn can_mega_evolve(&self) -> bool {
        // this assumes that if you have the correct mega stone, you can always mega evolve
        // even if another pkmn on the team already mega evolved
        // it is incorrect but practically most teams aren't going to have multiple mega stones
        if let Some(_mega_evolve_data) = self.id.mega_evolve_target(self.item) {
            true
        } else {
            false
        }
    }

    // alpha-poke patch (2026-10-17, doc/engine-diff.md L195): Showdown's updateMaxHp after a
    // permanent forme change (from `from`): the max HP by the HP stat's change, the HP lost kept
    // (at least 1)
    pub fn update_max_hp(
        &mut self,
        from: PokemonName,
        side_ref: &SideReference,
        instructions: &mut StateInstructions,
    ) {
        // (L203: the HP IV inferred from its max HP in the old forme, as recalculate_stats')
        let to = self.id;
        let iv = IV_ORDER
            .iter()
            .copied()
            .find(|iv| {
                let mut ivs = [31u16; 6];
                ivs[0] = *iv;
                self.stats_for(from, ivs).0 == self.maxhp
            })
            .unwrap_or(31);
        let mut ivs = [31u16; 6];
        ivs[0] = iv;
        let amount = self.stats_for(to, ivs).0 - self.stats_for(from, ivs).0;
        if amount == 0 {
            return;
        }
        instructions
            .instruction_list
            .push(Instruction::ChangeMaxHp(ChangeStatInstruction {
                side_ref: *side_ref,
                amount,
            }));
        self.maxhp += amount;
        if self.hp > 0 {
            let hp = std::cmp::max(1, self.hp + amount);
            if hp > self.hp {
                instructions
                    .instruction_list
                    .push(Instruction::Heal(crate::instruction::HealInstruction {
                        side_ref: *side_ref,
                        heal_amount: hp - self.hp,
                    }));
            } else if hp < self.hp {
                instructions
                    .instruction_list
                    .push(Instruction::Damage(crate::instruction::DamageInstruction {
                        side_ref: *side_ref,
                        damage_amount: self.hp - hp,
                    }));
            }
            self.hp = hp;
        }
    }

    pub fn recalculate_stats(
        &mut self,
        from: PokemonName,
        side_ref: &SideReference,
        instructions: &mut StateInstructions,
    ) {
        // recalculate stats from base-stats and push any changes made to the StateInstructions
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L183): by the forme's change of each
        // stat (the new forme's minus the old's, at its EVs / nature): its own IVs and EVs kept
        // (the state's EVs are not always its real ones: was the new forme's stats from them);
        // and the forme's weight (Showdown's weighthg: Minior-Meteor 40, Palafin-Hero 97.4, ...)
        // (L203: each stat's IV inferred from the stat it has in the old forme -- the first of
        // IV_ORDER that fits -- and the new forme's from it exactly; the change when no IV fits:
        // a stat Transform / Power Trick / Guard Split set)
        let to = self.id;
        let new_stats = self.calculate_stats_from_base_stats();
        let old_stats = self.stats_for(from, [31; 6]);
        let has = [0, self.attack, self.defense, self.special_attack, self.special_defense, self.speed];
        let pick = |k: usize, s: (i16, i16, i16, i16, i16, i16)| [s.0, s.1, s.2, s.3, s.4, s.5][k];
        let stat = |k: usize| -> i16 {
            for iv in IV_ORDER {
                let mut ivs = [31u16; 6];
                ivs[k] = iv;
                if pick(k, self.stats_for(from, ivs)) == has[k] {
                    return pick(k, self.stats_for(to, ivs));
                }
            }
            has[k] + pick(k, new_stats) - pick(k, old_stats)
        };
        let stats = (new_stats.0, stat(1), stat(2), stat(3), stat(4), stat(5));
        if let Some(w) = to.forme_weight_hg() {
            let amount = w - (self.weight_kg * 10.0).round() as i16;
            if amount != 0 {
                instructions
                    .instruction_list
                    .push(Instruction::ChangeWeight(ChangeStatInstruction {
                        side_ref: *side_ref,
                        amount,
                    }));
                self.weight_kg = w as f32 / 10.0;
            }
        }
        if stats.1 != self.attack {
            let ins = Instruction::ChangeAttack(ChangeStatInstruction {
                side_ref: *side_ref,
                amount: stats.1 - self.attack,
            });
            self.attack = stats.1;
            instructions.instruction_list.push(ins);
        }
        if stats.2 != self.defense {
            let ins = Instruction::ChangeDefense(ChangeStatInstruction {
                side_ref: *side_ref,
                amount: stats.2 - self.defense,
            });
            self.defense = stats.2;
            instructions.instruction_list.push(ins);
        }
        if stats.3 != self.special_attack {
            let ins = Instruction::ChangeSpecialAttack(ChangeStatInstruction {
                side_ref: *side_ref,
                amount: stats.3 - self.special_attack,
            });
            self.special_attack = stats.3;
            instructions.instruction_list.push(ins);
        }
        if stats.4 != self.special_defense {
            let ins = Instruction::ChangeSpecialDefense(ChangeStatInstruction {
                side_ref: *side_ref,
                amount: stats.4 - self.special_defense,
            });
            self.special_defense = stats.4;
            instructions.instruction_list.push(ins);
        }
        if stats.5 != self.speed {
            let ins = Instruction::ChangeSpeed(ChangeStatInstruction {
                side_ref: *side_ref,
                amount: stats.5 - self.speed,
            });
            self.speed = stats.5;
            instructions.instruction_list.push(ins);
        }
    }
    pub fn calculate_stats_from_base_stats(&self) -> (i16, i16, i16, i16, i16, i16) {
        self.stats_for(self.id, [31; 6])
    }

    // alpha-poke patch (2026-10-17, doc/engine-diff.md L203): the stats of forme `id` with these
    // IVs (the state's level, EVs, nature)
    pub fn stats_for(&self, id: PokemonName, ivs: [u16; 6]) -> (i16, i16, i16, i16, i16, i16) {
        let base_stats = id.base_stats();

        #[cfg(feature = "champions")]
        let evs = (
            stat_points_to_effective_ev(self.evs.0 as u16),
            stat_points_to_effective_ev(self.evs.1 as u16),
            stat_points_to_effective_ev(self.evs.2 as u16),
            stat_points_to_effective_ev(self.evs.3 as u16),
            stat_points_to_effective_ev(self.evs.4 as u16),
            stat_points_to_effective_ev(self.evs.5 as u16),
        );

        #[cfg(not(feature = "champions"))]
        let evs = (
            self.evs.0 as u16,
            self.evs.1 as u16,
            self.evs.2 as u16,
            self.evs.3 as u16,
            self.evs.4 as u16,
            self.evs.5 as u16,
        );

        let mut result = (
            (common_pkmn_stat_calc_iv(base_stats.0 as u16, evs.0, self.level as u16, ivs[0])
                + self.level as u16
                + 10) as i16,
            (common_pkmn_stat_calc_iv(base_stats.1 as u16, evs.1, self.level as u16, ivs[1]) + 5) as i16,
            (common_pkmn_stat_calc_iv(base_stats.2 as u16, evs.2, self.level as u16, ivs[2]) + 5) as i16,
            (common_pkmn_stat_calc_iv(base_stats.3 as u16, evs.3, self.level as u16, ivs[3]) + 5) as i16,
            (common_pkmn_stat_calc_iv(base_stats.4 as u16, evs.4, self.level as u16, ivs[4]) + 5) as i16,
            (common_pkmn_stat_calc_iv(base_stats.5 as u16, evs.5, self.level as u16, ivs[5]) + 5) as i16,
        );

        match self.nature {
            PokemonNature::LONELY => {
                result.1 = result.1 * 11 / 10; // +Atk
                result.2 = result.2 * 9 / 10; // -Def
            }
            PokemonNature::ADAMANT => {
                result.1 = result.1 * 11 / 10; // +Atk
                result.3 = result.3 * 9 / 10; // -SpA
            }
            PokemonNature::NAUGHTY => {
                result.1 = result.1 * 11 / 10; // +Atk
                result.4 = result.4 * 9 / 10; // -SpD
            }
            PokemonNature::BRAVE => {
                result.1 = result.1 * 11 / 10; // +Atk
                result.5 = result.5 * 9 / 10; // -Spe
            }
            PokemonNature::BOLD => {
                result.2 = result.2 * 11 / 10; // +Def
                result.1 = result.1 * 9 / 10; // -Atk
            }
            PokemonNature::IMPISH => {
                result.2 = result.2 * 11 / 10; // +Def
                result.3 = result.3 * 9 / 10; // -SpA
            }
            PokemonNature::LAX => {
                result.2 = result.2 * 11 / 10; // +Def
                result.4 = result.4 * 9 / 10; // -SpD
            }
            PokemonNature::RELAXED => {
                result.2 = result.2 * 11 / 10; // +Def
                result.5 = result.5 * 9 / 10; // -Spe
            }
            PokemonNature::MODEST => {
                result.3 = result.3 * 11 / 10; // +SpA
                result.1 = result.1 * 9 / 10; // -Atk
            }
            PokemonNature::MILD => {
                result.3 = result.3 * 11 / 10; // +SpA
                result.2 = result.2 * 9 / 10; // -Def
            }
            PokemonNature::RASH => {
                result.3 = result.3 * 11 / 10; // +SpA
                result.4 = result.4 * 9 / 10; // -SpD
            }
            PokemonNature::QUIET => {
                result.3 = result.3 * 11 / 10; // +SpA
                result.5 = result.5 * 9 / 10; // -Spe
            }
            PokemonNature::CALM => {
                result.4 = result.4 * 11 / 10; // +SpD
                result.1 = result.1 * 9 / 10; // -Atk
            }
            PokemonNature::GENTLE => {
                result.4 = result.4 * 11 / 10; // +SpD
                result.2 = result.2 * 9 / 10; // -Def
            }
            PokemonNature::CAREFUL => {
                result.4 = result.4 * 11 / 10; // +SpD
                result.3 = result.3 * 9 / 10; // -SpA
            }
            PokemonNature::SASSY => {
                result.4 = result.4 * 11 / 10; // +SpD
                result.5 = result.5 * 9 / 10; // -Spe
            }
            PokemonNature::TIMID => {
                result.5 = result.5 * 11 / 10; // +Spe
                result.1 = result.1 * 9 / 10; // -Atk
            }
            PokemonNature::HASTY => {
                result.5 = result.5 * 11 / 10; // +Spe
                result.2 = result.2 * 9 / 10; // -Def
            }
            PokemonNature::JOLLY => {
                result.5 = result.5 * 11 / 10; // +Spe
                result.3 = result.3 * 9 / 10; // -SpA
            }
            PokemonNature::NAIVE => {
                result.5 = result.5 * 11 / 10; // +Spe
                result.4 = result.4 * 9 / 10; // -SpD
            }
            // Neutral natures: no change
            PokemonNature::HARDY
            | PokemonNature::DOCILE
            | PokemonNature::SERIOUS
            | PokemonNature::BASHFUL
            | PokemonNature::QUIRKY => {}
        }
        result
    }

    pub fn add_available_moves(
        &self,
        vec: &mut Vec<MoveChoice>,
        last_used_move: &LastUsedMove,
        encored: bool,
        taunted: bool,
        throat_chopped: bool,
        can_tera: bool,
        side_can_mega: bool,
        heal_blocked: bool,
    ) {
        let mut iter = self.moves.into_iter();
        while let Some(p) = iter.next() {
            if !p.disabled && p.pp > 0 {
                match last_used_move {
                    LastUsedMove::Move(last_used_move) => {
                        if encored && last_used_move != &iter.pokemon_move_index {
                            continue;
                        } else if (self.moves[last_used_move].id == Choices::BLOODMOON
                            || self.moves[last_used_move].id == Choices::GIGATONHAMMER)
                            && &iter.pokemon_move_index == last_used_move
                        {
                            continue;
                        }
                    }
                    _ => {
                        // there are some situations where you switched out and got encored into
                        // a move from a different pokemon because you also have that move.
                        // just assume nothing is locked in this case
                    }
                }
                if (self.item == Items::ASSAULTVEST || taunted)
                    && self.moves[&iter.pokemon_move_index].choice.category == MoveCategory::Status
                {
                    continue;
                }
                // alpha-poke patch (2026-10-17, doc/engine-diff.md L209): Stuff Cheeks needs a held
                // berry (Showdown's onDisableMove)
                if p.id == Choices::STUFFCHEEKS && !super::items::is_berry(self.item) {
                    continue;
                }
                // alpha-poke patch (2026-10-13): Throat Chop blocks sound moves
                if throat_chopped && self.moves[&iter.pokemon_move_index].choice.flags.sound {
                    continue;
                }
                // alpha-poke patch (2026-10-17, doc/engine-diff.md L177): Heal Block, the healing
                // moves too (Showdown's onDisableMove: not chosen; was a failure as it moved)
                if heal_blocked && self.moves[&iter.pokemon_move_index].choice.flags.heal {
                    continue;
                }
                vec.push(MoveChoice::Move(iter.pokemon_move_index));
                if can_tera {
                    vec.push(MoveChoice::MoveTera(iter.pokemon_move_index));
                }
                if side_can_mega && self.can_mega_evolve() {
                    vec.push(MoveChoice::MoveMega(iter.pokemon_move_index));
                }
            }
        }
    }

    pub fn add_move_from_choice(&self, vec: &mut Vec<MoveChoice>, choice: Choices) {
        let mut iter = self.moves.into_iter();
        while let Some(p) = iter.next() {
            if p.id == choice {
                vec.push(MoveChoice::Move(iter.pokemon_move_index));
            }
        }
    }

    #[cfg(feature = "terastallization")]
    pub fn has_type(&self, pkmn_type: &PokemonType) -> bool {
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L192): a Stellar tera keeps its own
        // types (Showdown's getTypes: only a non-Stellar tera type replaces them); was Stellar only
        if self.terastallized && self.tera_type != PokemonType::STELLAR {
            pkmn_type == &self.tera_type
        } else {
            pkmn_type == &self.types.0 || pkmn_type == &self.types.1
        }
    }

    #[cfg(not(feature = "terastallization"))]
    pub fn has_type(&self, pkmn_type: &PokemonType) -> bool {
        pkmn_type == &self.types.0 || pkmn_type == &self.types.1
    }

    pub fn item_is_permanent(&self) -> bool {
        match self.item {
            Items::BOOSTERENERGY => PARADOX.contains(&self.id),
            Items::LUSTROUSGLOBE => self.id == PokemonName::PALKIAORIGIN,
            Items::GRISEOUSCORE => self.id == PokemonName::GIRATINAORIGIN,
            Items::ADAMANTCRYSTAL => self.id == PokemonName::DIALGAORIGIN,
            Items::RUSTEDSWORD => {
                self.id == PokemonName::ZACIANCROWNED || self.id == PokemonName::ZACIAN
            }
            Items::RUSTEDSHIELD => {
                self.id == PokemonName::ZAMAZENTACROWNED || self.id == PokemonName::ZAMAZENTA
            }
            Items::SPLASHPLATE => self.id == PokemonName::ARCEUSWATER,
            Items::TOXICPLATE => self.id == PokemonName::ARCEUSPOISON,
            Items::EARTHPLATE => self.id == PokemonName::ARCEUSGROUND,
            Items::STONEPLATE => self.id == PokemonName::ARCEUSROCK,
            Items::INSECTPLATE => self.id == PokemonName::ARCEUSBUG,
            Items::SPOOKYPLATE => self.id == PokemonName::ARCEUSGHOST,
            Items::IRONPLATE => self.id == PokemonName::ARCEUSSTEEL,
            Items::FLAMEPLATE => self.id == PokemonName::ARCEUSFIRE,
            Items::MEADOWPLATE => self.id == PokemonName::ARCEUSGRASS,
            Items::ZAPPLATE => self.id == PokemonName::ARCEUSELECTRIC,
            Items::MINDPLATE => self.id == PokemonName::ARCEUSPSYCHIC,
            Items::ICICLEPLATE => self.id == PokemonName::ARCEUSICE,
            Items::DRACOPLATE => self.id == PokemonName::ARCEUSDRAGON,
            Items::DREADPLATE => self.id == PokemonName::ARCEUSDARK,
            Items::FISTPLATE => self.id == PokemonName::ARCEUSFIGHTING,
            Items::BLANKPLATE => self.id == PokemonName::ARCEUS,
            Items::SKYPLATE => self.id == PokemonName::ARCEUSFLYING,
            Items::PIXIEPLATE => self.id == PokemonName::ARCEUSFAIRY,
            Items::BUGMEMORY => self.id == PokemonName::SILVALLYBUG,
            Items::FIGHTINGMEMORY => self.id == PokemonName::SILVALLYFIGHTING,
            Items::GHOSTMEMORY => self.id == PokemonName::SILVALLYGHOST,
            Items::PSYCHICMEMORY => self.id == PokemonName::SILVALLYPSYCHIC,
            Items::FLYINGMEMORY => self.id == PokemonName::SILVALLYFLYING,
            Items::STEELMEMORY => self.id == PokemonName::SILVALLYSTEEL,
            Items::ICEMEMORY => self.id == PokemonName::SILVALLYICE,
            Items::POISONMEMORY => self.id == PokemonName::SILVALLYPOISON,
            Items::FIREMEMORY => self.id == PokemonName::SILVALLYFIRE,
            Items::DRAGONMEMORY => self.id == PokemonName::SILVALLYDRAGON,
            Items::GROUNDMEMORY => self.id == PokemonName::SILVALLYGROUND,
            Items::WATERMEMORY => self.id == PokemonName::SILVALLYWATER,
            Items::DARKMEMORY => self.id == PokemonName::SILVALLYDARK,
            Items::ROCKMEMORY => self.id == PokemonName::SILVALLYROCK,
            Items::GRASSMEMORY => self.id == PokemonName::SILVALLYGRASS,
            Items::FAIRYMEMORY => self.id == PokemonName::SILVALLYFAIRY,
            Items::ELECTRICMEMORY => self.id == PokemonName::SILVALLYELECTRIC,
            Items::CORNERSTONEMASK => {
                self.id == PokemonName::OGERPONCORNERSTONE
                    || self.id == PokemonName::OGERPONCORNERSTONETERA
            }
            Items::HEARTHFLAMEMASK => {
                self.id == PokemonName::OGERPONHEARTHFLAME
                    || self.id == PokemonName::OGERPONHEARTHFLAMETERA
            }
            Items::WELLSPRINGMASK => {
                self.id == PokemonName::OGERPONWELLSPRING
                    || self.id == PokemonName::OGERPONWELLSPRINGTERA
            }
            Items::VENUSAURITE
            | Items::CHARIZARDITEX
            | Items::CHARIZARDITEY
            | Items::BLASTOISINITE
            | Items::BEEDRILLITE
            | Items::PIDGEOTITE
            | Items::ALAKAZITE
            | Items::SLOWBRONITE
            | Items::GENGARITE
            | Items::KANGASKHANITE
            | Items::PINSIRITE
            | Items::GYARADOSITE
            | Items::AERODACTYLITE
            | Items::MEWTWONITEX
            | Items::MEWTWONITEY
            | Items::AMPHAROSITE
            | Items::STEELIXITE
            | Items::SCIZORITE
            | Items::HERACRONITE
            | Items::HOUNDOOMINITE
            | Items::TYRANITARITE
            | Items::SCEPTILITE
            | Items::BLAZIKENITE
            | Items::SWAMPERTITE
            | Items::GARDEVOIRITE
            | Items::SABLENITE
            | Items::MAWILITE
            | Items::AGGRONITE
            | Items::MEDICHAMITE
            | Items::MANECTITE
            | Items::SHARPEDONITE
            | Items::CAMERUPTITE
            | Items::ALTARIANITE
            | Items::BANETTITE
            | Items::ABSOLITE
            | Items::GLALITITE
            | Items::SALAMENCITE
            | Items::METAGROSSITE
            | Items::LATIASITE
            | Items::LATIOSITE
            | Items::LOPUNNITE
            | Items::GARCHOMPITE
            | Items::LUCARIONITE
            | Items::ABOMASITE
            | Items::GALLADITE
            | Items::AUDINITE
            | Items::DIANCITE
            | Items::DRAGONINITE
            | Items::CLEFABLITE
            | Items::MEGANIUMITE
            | Items::FERALIGITE
            | Items::EMBOARITE
            | Items::CHESNAUGHTITE
            | Items::DELPHOXITE
            | Items::GRENINJITE
            | Items::CRABOMINITE
            | Items::GOLURKITE
            | Items::SCOVILLAINITE
            | Items::GLIMMORANITE
            | Items::FLOETTITE
            | Items::VICTREEBELITE
            | Items::STARMINITE
            | Items::HAWLUCHANITE
            | Items::SKARMORITE
            | Items::MEOWSTICITE
            | Items::FROSLASSITE
            | Items::EXCADRITE
            | Items::DRAMPANITE
            | Items::CHIMECHITE
            | Items::CHANDELURITE => true,
            _ => false,
        }
    }

    pub fn item_can_be_removed(&self) -> bool {
        if self.ability == Abilities::STICKYHOLD {
            return false;
        }
        !self.item_is_permanent()
    }

    pub fn is_grounded(&self) -> bool {
        if self.item == Items::IRONBALL {
            return true;
        }
        if self.has_type(&PokemonType::FLYING)
            || self.ability == Abilities::LEVITATE
            || self.ability == Abilities::EELEVATE
            || self.item == Items::AIRBALLOON
        {
            return false;
        }
        true
    }

    pub fn volatile_status_can_be_applied(
        &self,
        volatile_status: &PokemonVolatileStatus,
        active_volatiles: &VolatileStatusBitset,
        first_move: bool,
    ) -> bool {
        if active_volatiles.contains(volatile_status) || self.hp == 0 {
            return false;
        }
        match volatile_status {
            // alpha-poke patch (2026-10-17, doc/engine-diff.md L209): Gastro Acid fails on an
            // ability that cannot be suppressed and through an Ability Shield (Showdown's onTryHit)
            PokemonVolatileStatus::GASTROACID => {
                !super::abilities::CANT_SUPPRESS.contains(&self.ability)
                    && self.item != Items::ABILITYSHIELD
            }
            PokemonVolatileStatus::LEECHSEED => {
                if self.has_type(&PokemonType::GRASS)
                    || active_volatiles.contains(&PokemonVolatileStatus::SUBSTITUTE)
                {
                    return false;
                }
                true
            }
            PokemonVolatileStatus::CONFUSION => {
                if active_volatiles.contains(&PokemonVolatileStatus::SUBSTITUTE) {
                    return false;
                }
                true
            }
            PokemonVolatileStatus::SUBSTITUTE => self.hp > self.maxhp / 4,
            PokemonVolatileStatus::FLINCH => {
                if !first_move || [Abilities::INNERFOCUS].contains(&self.ability) {
                    return false;
                }
                true
            }
            PokemonVolatileStatus::PROTECT => first_move,
            // alpha-poke patch (2026-10-16, doc/engine-diff.md L86): only an airborne target
            // (Showdown's smackdown onStart)
            PokemonVolatileStatus::SMACKDOWN => {
                (self.has_type(&PokemonType::FLYING)
                    || self.ability == Abilities::LEVITATE
                    || active_volatiles.contains(&PokemonVolatileStatus::MAGNETRISE))
                    && self.item != Items::IRONBALL
                    && !active_volatiles.contains(&PokemonVolatileStatus::INGRAIN)
            }
            PokemonVolatileStatus::TAUNT
            | PokemonVolatileStatus::TORMENT
            | PokemonVolatileStatus::ENCORE
            | PokemonVolatileStatus::DISABLE
            | PokemonVolatileStatus::HEALBLOCK
            | PokemonVolatileStatus::ATTRACT => self.ability != Abilities::AROMAVEIL,
            _ => true,
        }
    }

    pub fn immune_to_stats_lowered_by_opponent(
        &self,
        stat: &PokemonBoostableStat,
        _volatiles: &VolatileStatusBitset,
    ) -> bool {
        if [
            Abilities::CLEARBODY,
            Abilities::WHITESMOKE,
            Abilities::FULLMETALBODY,
        ]
        .contains(&self.ability)
            || ([Items::CLEARAMULET].contains(&self.item))
        {
            return true;
        }

        // alpha-poke patch (2026-10-17, doc/engine-diff.md L151): no Substitute here (Showdown's
        // boost() has none: the Substitute stops the moves, L133; a Parting Shot goes through)

        if stat == &PokemonBoostableStat::Attack && self.ability == Abilities::HYPERCUTTER {
            return true;
        } else if stat == &PokemonBoostableStat::Accuracy && self.ability == Abilities::KEENEYE {
            return true;
        }

        false
    }
}

const ALL_POKEMON_INDICES: [PokemonIndex; 6] = [
    PokemonIndex::P0,
    PokemonIndex::P1,
    PokemonIndex::P2,
    PokemonIndex::P3,
    PokemonIndex::P4,
    PokemonIndex::P5,
];

impl Side {
    // alpha-poke patch (2026-10-17, doc/engine-diff.md L188): the active's isGrounded as Showdown's,
    // with its volatiles (Pokemon::is_grounded has none): Ingrain / Smack Down / an Iron Ball
    // ground it; Roost takes its Flying type off for the turn (not a terastallized one's: its
    // tera type); Magnet Rise lifts it; then Levitate, an Air Balloon (Pokemon::is_grounded).
    // For the terrains (their boosts, Grassy Terrain's healing, the status they stop, Psychic
    // Terrain's priority block) and Arena Trap
    pub fn active_grounded(&self) -> bool {
        let p = self.get_active_immutable();
        let v = &self.volatile_statuses;
        if v.contains(&PokemonVolatileStatus::INGRAIN)
            || v.contains(&PokemonVolatileStatus::SMACKDOWN)
            || p.item == Items::IRONBALL
        {
            return true;
        }
        let tera_types = p.terastallized && p.tera_type != PokemonType::STELLAR;
        let flying = p.has_type(&PokemonType::FLYING)
            && !(v.contains(&PokemonVolatileStatus::ROOST) && !tera_types);
        if flying || v.contains(&PokemonVolatileStatus::MAGNETRISE) {
            return false;
        }
        !matches!(p.ability, Abilities::LEVITATE | Abilities::EELEVATE) && p.item != Items::AIRBALLOON
    }

    // (L188: Showdown's isSemiInvulnerable: a charging Fly / Bounce / Dive / Dig / Phantom Force /
    // Shadow Force; Grassy Terrain heals no such one)
    pub fn semi_invulnerable(&self) -> bool {
        [
            PokemonVolatileStatus::FLY,
            PokemonVolatileStatus::BOUNCE,
            PokemonVolatileStatus::DIVE,
            PokemonVolatileStatus::DIG,
            PokemonVolatileStatus::PHANTOMFORCE,
            PokemonVolatileStatus::SHADOWFORCE,
        ]
        .iter()
        .any(|v| self.volatile_statuses.contains(v))
    }

    // generates BSS team preview options
    // BSS is a 6v6 game at team preview, but only 3v3 in battle.
    // This should generate all 60 options for both sides using MoveChoice::TeamPreview.
    // 60 options because: 6 choose 3 = 20, and each side must select a lead, so 20 * 3 = 60.
    // MoveChoice::TeamPreview(lead, reserve1, reserve2) where lead is the index of the lead pokemon,
    // and reserve1 and reserve2 are the indices of the other two pokemon.
    // Note that the order of reserve1 and reserve2 does not matter, so we can just generate all combinations of 3 pokemon from 6,
    // and then for each combination, generate 3 permutations of the 3 pokemon to determine the lead.
    pub fn bss_team_preview_get_all_options(&self) -> Vec<MoveChoice> {
        let mut options = Vec::with_capacity(60);

        let num_pkmn_indices = ALL_POKEMON_INDICES.len();
        for i in 0..num_pkmn_indices {
            for j in (i + 1)..num_pkmn_indices {
                for k in (j + 1)..num_pkmn_indices {
                    let lead = ALL_POKEMON_INDICES[i];
                    let reserve1 = ALL_POKEMON_INDICES[j];
                    let reserve2 = ALL_POKEMON_INDICES[k];
                    options.push(MoveChoice::TeamPreview(lead, reserve1, reserve2));
                    options.push(MoveChoice::TeamPreview(reserve1, lead, reserve2));
                    options.push(MoveChoice::TeamPreview(reserve2, lead, reserve1));
                }
            }
        }
        options
    }

    pub fn reset_negative_boosts(
        &mut self,
        side_ref: SideReference,
        instructions: &mut StateInstructions,
    ) -> bool {
        let mut changed = false;
        if self.attack_boost < 0 {
            instructions
                .instruction_list
                .push(Instruction::SetBoost(BoostInstruction {
                    side_ref,
                    stat: PokemonBoostableStat::Attack,
                    amount: -self.attack_boost,
                }));
            self.attack_boost = 0;
            changed = true;
        }
        if self.defense_boost < 0 {
            instructions
                .instruction_list
                .push(Instruction::SetBoost(BoostInstruction {
                    side_ref,
                    stat: PokemonBoostableStat::Defense,
                    amount: -self.defense_boost,
                }));
            self.defense_boost = 0;
            changed = true;
        }
        if self.special_attack_boost < 0 {
            instructions
                .instruction_list
                .push(Instruction::SetBoost(BoostInstruction {
                    side_ref,
                    stat: PokemonBoostableStat::SpecialAttack,
                    amount: -self.special_attack_boost,
                }));
            self.special_attack_boost = 0;
            changed = true;
        }
        if self.special_defense_boost < 0 {
            instructions
                .instruction_list
                .push(Instruction::SetBoost(BoostInstruction {
                    side_ref,
                    stat: PokemonBoostableStat::SpecialDefense,
                    amount: -self.special_defense_boost,
                }));
            self.special_defense_boost = 0;
            changed = true;
        }
        if self.speed_boost < 0 {
            instructions
                .instruction_list
                .push(Instruction::SetBoost(BoostInstruction {
                    side_ref,
                    stat: PokemonBoostableStat::Speed,
                    amount: -self.speed_boost,
                }));
            self.speed_boost = 0;
            changed = true;
        }
        if self.accuracy_boost < 0 {
            instructions
                .instruction_list
                .push(Instruction::SetBoost(BoostInstruction {
                    side_ref,
                    stat: PokemonBoostableStat::Accuracy,
                    amount: -self.accuracy_boost,
                }));
            self.accuracy_boost = 0;
            changed = true;
        }
        if self.evasion_boost < 0 {
            instructions
                .instruction_list
                .push(Instruction::SetBoost(BoostInstruction {
                    side_ref,
                    stat: PokemonBoostableStat::Evasion,
                    amount: -self.evasion_boost,
                }));
            self.evasion_boost = 0;
            changed = true;
        }
        changed
    }
    pub fn active_is_charging_move(&self) -> Option<PokemonMoveIndex> {
        const CHARGE_VOLATILES: &[(PokemonVolatileStatus, Choices)] = &[
            (PokemonVolatileStatus::BOUNCE, Choices::BOUNCE),
            (PokemonVolatileStatus::DIG, Choices::DIG),
            (PokemonVolatileStatus::DIVE, Choices::DIVE),
            (PokemonVolatileStatus::FLY, Choices::FLY),
            (PokemonVolatileStatus::FREEZESHOCK, Choices::FREEZESHOCK),
            (PokemonVolatileStatus::GEOMANCY, Choices::GEOMANCY),
            (PokemonVolatileStatus::ICEBURN, Choices::ICEBURN),
            (PokemonVolatileStatus::METEORBEAM, Choices::METEORBEAM),
            (PokemonVolatileStatus::ELECTROSHOT, Choices::ELECTROSHOT),
            (PokemonVolatileStatus::PHANTOMFORCE, Choices::PHANTOMFORCE),
            (PokemonVolatileStatus::RAZORWIND, Choices::RAZORWIND),
            (PokemonVolatileStatus::SHADOWFORCE, Choices::SHADOWFORCE),
            (PokemonVolatileStatus::SKULLBASH, Choices::SKULLBASH),
            (PokemonVolatileStatus::SKYATTACK, Choices::SKYATTACK),
            (PokemonVolatileStatus::SKYDROP, Choices::SKYDROP),
            (PokemonVolatileStatus::SOLARBEAM, Choices::SOLARBEAM),
            (PokemonVolatileStatus::SOLARBLADE, Choices::SOLARBLADE),
        ];

        let vs = &self.volatile_statuses;

        for (volatile, choice_id) in CHARGE_VOLATILES {
            if vs.contains(volatile) {
                let mut iter = self.get_active_immutable().moves.into_iter();
                while let Some(mv) = iter.next() {
                    if mv.id == *choice_id {
                        return Some(iter.pokemon_move_index);
                    }
                }
            }
        }
        None
    }

    pub fn calculate_highest_stat(&self) -> PokemonBoostableStat {
        let mut highest_stat = PokemonBoostableStat::Attack;
        let mut highest_stat_value = self.calculate_boosted_stat(PokemonBoostableStat::Attack);
        for stat in [
            PokemonBoostableStat::Defense,
            PokemonBoostableStat::SpecialAttack,
            PokemonBoostableStat::SpecialDefense,
            PokemonBoostableStat::Speed,
        ] {
            let stat_value = self.calculate_boosted_stat(stat);
            if stat_value > highest_stat_value {
                highest_stat = stat;
                highest_stat_value = stat_value;
            }
        }
        highest_stat
    }
    pub fn get_boost_from_boost_enum(&self, boost_enum: &PokemonBoostableStat) -> i8 {
        match boost_enum {
            PokemonBoostableStat::Attack => self.attack_boost,
            PokemonBoostableStat::Defense => self.defense_boost,
            PokemonBoostableStat::SpecialAttack => self.special_attack_boost,
            PokemonBoostableStat::SpecialDefense => self.special_defense_boost,
            PokemonBoostableStat::Speed => self.speed_boost,
            PokemonBoostableStat::Evasion => self.evasion_boost,
            PokemonBoostableStat::Accuracy => self.accuracy_boost,
        }
    }

    pub fn calculate_boosted_stat(&self, stat: PokemonBoostableStat) -> i16 {
        /*
        In Gen4, simple doubles the effective boost, without it visually being doubled
        It will not boost beyond an effective value of 6 though.
        */
        let active = self.get_active_immutable();
        match stat {
            PokemonBoostableStat::Attack => {
                #[cfg(feature = "gen4")]
                let boost = if active.ability == Abilities::SIMPLE {
                    (self.attack_boost * 2).min(6).max(-6)
                } else {
                    self.attack_boost
                };

                #[cfg(not(feature = "gen4"))]
                let boost = self.attack_boost;

                multiply_boost(boost, active.attack)
            }
            PokemonBoostableStat::Defense => {
                #[cfg(feature = "gen4")]
                let boost = if active.ability == Abilities::SIMPLE {
                    (self.defense_boost * 2).min(6).max(-6)
                } else {
                    self.defense_boost
                };
                #[cfg(not(feature = "gen4"))]
                let boost = self.defense_boost;

                multiply_boost(boost, active.defense)
            }
            PokemonBoostableStat::SpecialAttack => {
                #[cfg(feature = "gen4")]
                let boost = if active.ability == Abilities::SIMPLE {
                    (self.special_attack_boost * 2).min(6).max(-6)
                } else {
                    self.special_attack_boost
                };
                #[cfg(not(feature = "gen4"))]
                let boost = self.special_attack_boost;

                multiply_boost(boost, active.special_attack)
            }
            PokemonBoostableStat::SpecialDefense => {
                #[cfg(feature = "gen4")]
                let boost = if active.ability == Abilities::SIMPLE {
                    (self.special_defense_boost * 2).min(6).max(-6)
                } else {
                    self.special_defense_boost
                };
                #[cfg(not(feature = "gen4"))]
                let boost = self.special_defense_boost;

                multiply_boost(boost, active.special_defense)
            }
            PokemonBoostableStat::Speed => {
                #[cfg(feature = "gen4")]
                let boost = if active.ability == Abilities::SIMPLE {
                    (self.speed_boost * 2).min(6).max(-6)
                } else {
                    self.speed_boost
                };
                #[cfg(not(feature = "gen4"))]
                let boost = self.speed_boost;

                multiply_boost(boost, active.speed)
            }
            _ => {
                panic!("Not implemented")
            }
        }
    }

    pub fn has_alive_non_rested_sleeping_pkmn(&self) -> bool {
        for p in self.pokemon.into_iter() {
            if p.status == PokemonStatus::SLEEP && p.hp > 0 && p.rest_turns == 0 {
                return true;
            }
        }
        false
    }

    #[cfg(not(feature = "terastallization"))]
    pub fn can_use_tera(&self) -> bool {
        false
    }

    #[cfg(feature = "terastallization")]
    pub fn can_use_tera(&self) -> bool {
        if self.tera_used {
            return false;
        }
        for p in self.pokemon.into_iter() {
            if p.terastallized {
                return false;
            }
        }
        true
    }

    pub fn can_use_mega(&self) -> bool {
        for p in self.pokemon.into_iter() {
            if p.mega_evolved {
                return false;
            }
        }
        true
    }

    pub fn add_switches(&self, vec: &mut Vec<MoveChoice>) {
        // alpha-poke patch (2026-10-17, doc/engine-diff.md L166): Revival Blessing's pick: the
        // fainted Pokemon (not an empty slot), as Showdown's switch request then
        if self.reviving {
            let mut iter = self.pokemon.into_iter();
            while let Some(p) = iter.next() {
                if p.hp == 0 && p.id != PokemonName::NONE {
                    vec.push(MoveChoice::Switch(iter.pokemon_index));
                }
            }
            if vec.len() == 0 {
                vec.push(MoveChoice::None);
            }
            return;
        }
        let mut iter = self.pokemon.into_iter();
        while let Some(p) = iter.next() {
            if p.hp > 0 && iter.pokemon_index != self.active_index {
                vec.push(MoveChoice::Switch(iter.pokemon_index));
            }
        }
        if vec.len() == 0 {
            vec.push(MoveChoice::None);
        }
    }

    pub fn trapped(&self, opponent_active: &Pokemon) -> bool {
        let active_pkmn = self.get_active_immutable();
        if self
            .volatile_statuses
            .contains(&PokemonVolatileStatus::LOCKEDMOVE)
            || self
                .volatile_statuses
                .contains(&PokemonVolatileStatus::NORETREAT)
        {
            return true;
        }
        if active_pkmn.item == Items::SHEDSHELL || active_pkmn.has_type(&PokemonType::GHOST) {
            return false;
        } else if self
            .volatile_statuses
            .contains(&PokemonVolatileStatus::PARTIALLYTRAPPED)
            || self
                .volatile_statuses
                .contains(&PokemonVolatileStatus::TRAPPED)
        {
            return true;
        } else if opponent_active.ability == Abilities::SHADOWTAG {
            return true;
        } else if opponent_active.ability == Abilities::ARENATRAP && self.active_grounded() {
            return true;
        } else if opponent_active.ability == Abilities::MAGNETPULL
            && active_pkmn.has_type(&PokemonType::STEEL)
        {
            return true;
        }
        false
    }

    // alpha-poke patch (2026-10-18, doc/engine-diff.md L220): Showdown's totalFainted, the
    // fainted ones and the faints Revival Blessing undid
    pub fn total_fainted(&self) -> i8 {
        self.num_fainted_pkmn() + self.revived_faints as i8
    }

    pub fn num_fainted_pkmn(&self) -> i8 {
        let mut count = 0;
        for p in self.pokemon.into_iter() {
            if p.hp == 0 && p.id != PokemonName::NONE {
                count += 1;
            }
        }
        count
    }
}

impl State {
    pub fn root_get_all_options(&self) -> (Vec<MoveChoice>, Vec<MoveChoice>) {
        #[cfg(feature = "bss")]
        if self.team_preview {
            return (
                self.side_one.bss_team_preview_get_all_options(),
                self.side_two.bss_team_preview_get_all_options(),
            );
        }

        if self.team_preview {
            let mut s1_options = Vec::with_capacity(6);
            let mut s2_options = Vec::with_capacity(6);

            let mut pkmn_iter = self.side_one.pokemon.into_iter();
            while let Some(_) = pkmn_iter.next() {
                if self.side_one.pokemon[pkmn_iter.pokemon_index].hp > 0 {
                    s1_options.push(MoveChoice::Switch(pkmn_iter.pokemon_index));
                }
            }
            let mut pkmn_iter = self.side_two.pokemon.into_iter();
            while let Some(_) = pkmn_iter.next() {
                if self.side_two.pokemon[pkmn_iter.pokemon_index].hp > 0 {
                    s2_options.push(MoveChoice::Switch(pkmn_iter.pokemon_index));
                }
            }
            return (s1_options, s2_options);
        }

        let (mut s1_options, mut s2_options) = self.get_all_options();

        if self.side_one.force_trapped {
            s1_options.retain(|x| match x {
                MoveChoice::Move(_) | MoveChoice::MoveTera(_) | MoveChoice::MoveMega(_) => true,
                MoveChoice::Switch(_) => false,
                MoveChoice::TeamPreview(_, _, _) => false,
                MoveChoice::None => true,
            });
        }
        if self.side_one.slow_uturn_move {
            s1_options.clear();
            let encored = self
                .side_one
                .volatile_statuses
                .contains(&PokemonVolatileStatus::ENCORE);
            let taunted = self
                .side_one
                .volatile_statuses
                .contains(&PokemonVolatileStatus::TAUNT);
            self.side_one.get_active_immutable().add_available_moves(
                &mut s1_options,
                &self.side_one.last_used_move,
                encored,
                taunted,
                self.side_one
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::THROATCHOP),
                // (L179: not while locked into a move -- Showdown's request offers no Terastallization then)
                self.side_one.can_use_tera()
                    && !self
                        .side_one
                        .volatile_statuses
                        .contains(&PokemonVolatileStatus::LOCKEDMOVE),
                self.side_one.can_use_mega(),
                self.side_one
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::HEALBLOCK),
            );
        }

        if self.side_two.force_trapped {
            s2_options.retain(|x| match x {
                MoveChoice::Move(_) | MoveChoice::MoveTera(_) | MoveChoice::MoveMega(_) => true,
                MoveChoice::Switch(_) => false,
                MoveChoice::TeamPreview(_, _, _) => false,
                MoveChoice::None => true,
            });
        }
        if self.side_two.slow_uturn_move {
            s2_options.clear();
            let encored = self
                .side_two
                .volatile_statuses
                .contains(&PokemonVolatileStatus::ENCORE);
            let taunted = self
                .side_two
                .volatile_statuses
                .contains(&PokemonVolatileStatus::TAUNT);
            self.side_two.get_active_immutable().add_available_moves(
                &mut s2_options,
                &self.side_two.last_used_move,
                encored,
                taunted,
                self.side_two
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::THROATCHOP),
                // (L179: not while locked into a move -- Showdown's request offers no Terastallization then)
                self.side_two.can_use_tera()
                    && !self
                        .side_two
                        .volatile_statuses
                        .contains(&PokemonVolatileStatus::LOCKEDMOVE),
                self.side_two.can_use_mega(),
                self.side_two
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::HEALBLOCK),
            );
        }

        if s1_options.len() == 0 {
            s1_options.push(MoveChoice::None);
        }
        if s2_options.len() == 0 {
            s2_options.push(MoveChoice::None);
        }

        // (L211: no gravity move under Gravity)
        let mut out = (s1_options, s2_options);
        self.gravity_filter(&mut out);
        out
    }

    // alpha-poke patch (2026-10-17, doc/engine-diff.md L211): Gravity disables the gravity moves
    // (Showdown's onDisableMove: High Jump Kick, Fly, Bounce, Splash, ...); with none left, Struggle
    fn gravity_filter(&self, out: &mut (Vec<MoveChoice>, Vec<MoveChoice>)) {
        if self.gravity == 0 {
            return;
        }
        for (options, side) in [(&mut out.0, &self.side_one), (&mut out.1, &self.side_two)] {
            let had_moves = options.iter().any(|o| !matches!(o, MoveChoice::Switch(_) | MoveChoice::None));
            options.retain(|o| match o {
                MoveChoice::Move(i) | MoveChoice::MoveTera(i) | MoveChoice::MoveMega(i) => {
                    !side.get_active_immutable().moves[i].id.disabled_by_gravity()
                }
                _ => true,
            });
            if had_moves
                && !options.iter().any(|o| !matches!(o, MoveChoice::Switch(_) | MoveChoice::None))
                && !options.contains(&MoveChoice::None)
            {
                options.push(MoveChoice::None);
            }
        }
    }

    pub fn get_all_options(&self) -> (Vec<MoveChoice>, Vec<MoveChoice>) {
        let mut side_one_options: Vec<MoveChoice> = Vec::with_capacity(9);
        let mut side_two_options: Vec<MoveChoice> = Vec::with_capacity(9);

        let side_one_active = self.side_one.get_active_immutable();
        let side_two_active = self.side_two.get_active_immutable();

        if self.side_one.force_switch {
            self.side_one.add_switches(&mut side_one_options);
            if self.side_two.switch_out_move_second_saved_move == Choices::NONE {
                side_two_options.push(MoveChoice::None);
            } else {
                self.side_two.get_active_immutable().add_move_from_choice(
                    &mut side_two_options,
                    self.side_two.switch_out_move_second_saved_move,
                );
            }
            return (side_one_options, side_two_options);
        }

        if self.side_two.force_switch {
            self.side_two.add_switches(&mut side_two_options);
            if self.side_one.switch_out_move_second_saved_move == Choices::NONE {
                side_one_options.push(MoveChoice::None);
            } else {
                self.side_one.get_active_immutable().add_move_from_choice(
                    &mut side_one_options,
                    self.side_one.switch_out_move_second_saved_move,
                );
            }
            return (side_one_options, side_two_options);
        }

        let side_one_force_switch = self.side_one.get_active_immutable().hp <= 0;
        let side_two_force_switch = self.side_two.get_active_immutable().hp <= 0;

        if side_one_force_switch && side_two_force_switch {
            self.side_one.add_switches(&mut side_one_options);
            self.side_two.add_switches(&mut side_two_options);
            return (side_one_options, side_two_options);
        }
        if side_one_force_switch {
            self.side_one.add_switches(&mut side_one_options);
            side_two_options.push(MoveChoice::None);
            return (side_one_options, side_two_options);
        }
        if side_two_force_switch {
            side_one_options.push(MoveChoice::None);
            self.side_two.add_switches(&mut side_two_options);
            return (side_one_options, side_two_options);
        }

        if self
            .side_one
            .volatile_statuses
            .contains(&PokemonVolatileStatus::MUSTRECHARGE)
        {
            side_one_options.push(MoveChoice::None);
        } else if let Some(mv_index) = self.side_one.active_is_charging_move() {
            side_one_options.push(MoveChoice::Move(mv_index));
        } else {
            let encored = self
                .side_one
                .volatile_statuses
                .contains(&PokemonVolatileStatus::ENCORE);
            let taunted = self
                .side_one
                .volatile_statuses
                .contains(&PokemonVolatileStatus::TAUNT);
            self.side_one.get_active_immutable().add_available_moves(
                &mut side_one_options,
                &self.side_one.last_used_move,
                encored,
                taunted,
                self.side_one
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::THROATCHOP),
                // (L179: not while locked into a move -- Showdown's request offers no Terastallization then)
                self.side_one.can_use_tera()
                    && !self
                        .side_one
                        .volatile_statuses
                        .contains(&PokemonVolatileStatus::LOCKEDMOVE),
                self.side_one.can_use_mega(),
                self.side_one
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::HEALBLOCK),
            );
            // (L179: not a move the foe's Imprison holder knows -- Showdown's onFoeDisableMove)
            let foe = &self.side_two;
            let active = self.side_one.get_active_immutable();
            side_one_options.retain(|o| match o {
                MoveChoice::Move(i) | MoveChoice::MoveTera(i) | MoveChoice::MoveMega(i) => {
                    !super::generate_instructions::imprisoned(foe, active.moves[i].id)
                }
                _ => true,
            });
            if side_one_options.is_empty() {
                side_one_options.push(MoveChoice::None);
            }
            if !self.side_one.trapped(side_two_active) {
                self.side_one.add_switches(&mut side_one_options);
            }
        }

        if self
            .side_two
            .volatile_statuses
            .contains(&PokemonVolatileStatus::MUSTRECHARGE)
        {
            side_two_options.push(MoveChoice::None);
        } else if let Some(mv_index) = self.side_two.active_is_charging_move() {
            side_two_options.push(MoveChoice::Move(mv_index));
        } else {
            let encored = self
                .side_two
                .volatile_statuses
                .contains(&PokemonVolatileStatus::ENCORE);
            let taunted = self
                .side_two
                .volatile_statuses
                .contains(&PokemonVolatileStatus::TAUNT);
            self.side_two.get_active_immutable().add_available_moves(
                &mut side_two_options,
                &self.side_two.last_used_move,
                encored,
                taunted,
                self.side_two
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::THROATCHOP),
                // (L179: not while locked into a move -- Showdown's request offers no Terastallization then)
                self.side_two.can_use_tera()
                    && !self
                        .side_two
                        .volatile_statuses
                        .contains(&PokemonVolatileStatus::LOCKEDMOVE),
                self.side_two.can_use_mega(),
                self.side_two
                    .volatile_statuses
                    .contains(&PokemonVolatileStatus::HEALBLOCK),
            );
            // (L179: not a move the foe's Imprison holder knows -- Showdown's onFoeDisableMove)
            let foe = &self.side_one;
            let active = self.side_two.get_active_immutable();
            side_two_options.retain(|o| match o {
                MoveChoice::Move(i) | MoveChoice::MoveTera(i) | MoveChoice::MoveMega(i) => {
                    !super::generate_instructions::imprisoned(foe, active.moves[i].id)
                }
                _ => true,
            });
            if side_two_options.is_empty() {
                side_two_options.push(MoveChoice::None);
            }
            if !self.side_two.trapped(side_one_active) {
                self.side_two.add_switches(&mut side_two_options);
            }
        }

        if side_one_options.len() == 0 {
            side_one_options.push(MoveChoice::None);
        }
        if side_two_options.len() == 0 {
            side_two_options.push(MoveChoice::None);
        }

        // (L211: no gravity move under Gravity)
        let mut out = (side_one_options, side_two_options);
        self.gravity_filter(&mut out);
        out
    }

    pub fn reset_toxic_count(
        &mut self,
        side_ref: &SideReference,
        vec_to_add_to: &mut Vec<Instruction>,
    ) {
        let side = self.get_side(side_ref);
        if side.side_conditions.toxic_count > 0 {
            vec_to_add_to.push(Instruction::ChangeSideCondition(
                ChangeSideConditionInstruction {
                    side_ref: *side_ref,
                    side_condition: PokemonSideCondition::ToxicCount,
                    amount: -1 * side.side_conditions.toxic_count,
                },
            ));
            side.side_conditions.toxic_count = 0;
        }
    }

    pub fn remove_volatile_statuses_on_switch(
        &mut self,
        side_ref: &SideReference,
        instructions: &mut Vec<Instruction>,
        baton_passing: bool,
        shed_tailing: bool,
    ) {
        let side = self.get_side(side_ref);

        // Take ownership of the current set to avoid borrow conflicts
        // since we may need to modify the side in the loop
        let mut volatile_statuses = std::mem::take(&mut side.volatile_statuses);

        volatile_statuses.retain(&mut |pkmn_volatile_status| {
            let should_retain = match pkmn_volatile_status {
                PokemonVolatileStatus::SUBSTITUTE => baton_passing || shed_tailing,
                PokemonVolatileStatus::LEECHSEED => baton_passing,
                // alpha-poke patch (2026-10-16, doc/engine-diff.md L36): Transform ends: the mon's
                // own move again (the engine keeps no moves of its own while transformed:
                // Transform, the move of an Imposter Ditto); its types and ability go back with
                // TYPECHANGE and the switch-out. Its stats stay the copied ones (the engine has no
                // base stats of most species to recompute them; an Imposter copies them again
                // when it comes back in, and on the bench they are not used)
                PokemonVolatileStatus::TRANSFORM => {
                    let side_ref = *side_ref;
                    let active = side.get_active();
                    // alpha-poke patch (2026-10-17, doc/engine-diff.md L180): its own stats,
                    // weight, moves and PP back (Pokemon::own, kept as it transformed)
                    if active.own.is_set() {
                        let own = active.own;
                        let current = [
                            active.attack,
                            active.defense,
                            active.special_attack,
                            active.special_defense,
                            active.speed,
                        ];
                        for k in 0..5 {
                            let amount = own.stats[k] - current[k];
                            if amount == 0 {
                                continue;
                            }
                            let c = crate::instruction::ChangeStatInstruction { side_ref, amount };
                            instructions.push(match k {
                                0 => Instruction::ChangeAttack(c),
                                1 => Instruction::ChangeDefense(c),
                                2 => Instruction::ChangeSpecialAttack(c),
                                3 => Instruction::ChangeSpecialDefense(c),
                                _ => Instruction::ChangeSpeed(c),
                            });
                        }
                        active.attack = own.stats[0];
                        active.defense = own.stats[1];
                        active.special_attack = own.stats[2];
                        active.special_defense = own.stats[3];
                        active.speed = own.stats[4];
                        let weight = own.weight_hg - (active.weight_kg * 10.0).round() as i16;
                        if weight != 0 {
                            instructions.push(Instruction::ChangeWeight(
                                crate::instruction::ChangeStatInstruction {
                                    side_ref,
                                    amount: weight,
                                },
                            ));
                            active.weight_kg = own.weight_hg as f32 / 10.0;
                        }
                        for (k, index) in [
                            PokemonMoveIndex::M0,
                            PokemonMoveIndex::M1,
                            PokemonMoveIndex::M2,
                            PokemonMoveIndex::M3,
                        ]
                        .iter()
                        .enumerate()
                        {
                            let m = &mut active.moves[index];
                            if m.id != own.moves[k] {
                                instructions.push(Instruction::ChangeMove(
                                    crate::instruction::ChangeMoveInstruction {
                                        side_ref,
                                        move_index: *index,
                                        move_change: own.moves[k] as i16 - m.id as i16,
                                    },
                                ));
                                m.id = own.moves[k];
                                m.choice = MOVES.get(&own.moves[k]).unwrap().to_owned();
                            }
                            if m.pp != own.pp[k] {
                                instructions.push(Instruction::DecrementPP(
                                    crate::instruction::DecrementPPInstruction {
                                        side_ref,
                                        move_index: *index,
                                        amount: m.pp - own.pp[k],
                                    },
                                ));
                                m.pp = own.pp[k];
                            }
                        }
                        // (and the set cleared)
                        let mut clear: Vec<(u8, i16)> =
                            (0..5).map(|k| (k as u8, -own.stats[k])).collect();
                        clear.push((5, -own.weight_hg));
                        for k in 0..4 {
                            clear.push((6 + k as u8, Choices::NONE as i16 - own.moves[k] as i16));
                            clear.push((10 + k as u8, -(own.pp[k] as i16)));
                        }
                        for (field, amount) in clear {
                            if amount != 0 {
                                instructions.push(Instruction::ChangeOwn(
                                    crate::instruction::ChangeOwnInstruction {
                                        side_ref,
                                        field,
                                        amount,
                                    },
                                ));
                                active.own.change(field, amount);
                            }
                        }
                    } else {
                        for (k, index) in [
                            PokemonMoveIndex::M0,
                            PokemonMoveIndex::M1,
                            PokemonMoveIndex::M2,
                            PokemonMoveIndex::M3,
                        ]
                        .iter()
                        .enumerate()
                        {
                            let own = if k == 0 {
                                Choices::TRANSFORM
                            } else {
                                Choices::NONE
                            };
                            let m = &mut active.moves[index];
                            if m.id != own {
                                instructions.push(Instruction::ChangeMove(
                                    crate::instruction::ChangeMoveInstruction {
                                        side_ref,
                                        move_index: *index,
                                        move_change: own as i16 - m.id as i16,
                                    },
                                ));
                                m.id = own;
                                m.choice = MOVES.get(&own).unwrap().to_owned();
                            }
                        }
                    }
                    false
                }
                PokemonVolatileStatus::TYPECHANGE => {
                    let active = side.get_active();
                    if active.base_types != active.types {
                        instructions.push(Instruction::ChangeType(ChangeType {
                            side_ref: *side_ref,
                            new_types: active.base_types,
                            old_types: active.types,
                        }));
                        active.types = active.base_types;
                    }
                    false
                }
                // While you can't switch out of a locked move you can be forced out in other ways
                PokemonVolatileStatus::LOCKEDMOVE => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.lockedmove,
                        },
                    ));
                    side.volatile_status_durations.lockedmove = 0;
                    false
                }
                PokemonVolatileStatus::YAWN => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.yawn,
                        },
                    ));
                    side.volatile_status_durations.yawn = 0;
                    false
                }
                // alpha-poke patch: confusion's attempt count (generate_instructions::before_move)
                PokemonVolatileStatus::CONFUSION => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.confusion,
                        },
                    ));
                    side.volatile_status_durations.confusion = 0;
                    false
                }
                PokemonVolatileStatus::TAUNT => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.taunt,
                        },
                    ));
                    side.volatile_status_durations.taunt = 0;
                    false
                }
                // (L204: Cud Chew's count ends with it: Showdown's ability state goes)
                PokemonVolatileStatus::CUDCHEW => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.cudchew,
                        },
                    ));
                    side.volatile_status_durations.cudchew = 0;
                    false
                }
                // (L73: Stockpile's layers end with it; its boosts with the switch)
                PokemonVolatileStatus::STOCKPILE => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.stockpile,
                        },
                    ));
                    side.volatile_status_durations.stockpile = 0;
                    false
                }
                // (L70: Disable's count ends with it; the moves are enabled again on a switch)
                PokemonVolatileStatus::DISABLE => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.disable,
                        },
                    ));
                    side.volatile_status_durations.disable = 0;
                    false
                }
                // alpha-poke patch (2026-10-13): their turn counts end with them
                PokemonVolatileStatus::HEALBLOCK => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.healblock,
                        },
                    ));
                    side.volatile_status_durations.healblock = 0;
                    false
                }
                PokemonVolatileStatus::MAGNETRISE => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.magnetrise,
                        },
                    ));
                    side.volatile_status_durations.magnetrise = 0;
                    false
                }
                PokemonVolatileStatus::THROATCHOP => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.throatchop,
                        },
                    ));
                    side.volatile_status_durations.throatchop = 0;
                    false
                }
                PokemonVolatileStatus::PARTIALLYTRAPPED => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.partiallytrapped,
                        },
                    ));
                    side.volatile_status_durations.partiallytrapped = 0;
                    false
                }
                // alpha-poke patch (2026-10-16, L24)
                PokemonVolatileStatus::MICLEBERRY => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.micleberry,
                        },
                    ));
                    side.volatile_status_durations.micleberry = 0;
                    false
                }
                PokemonVolatileStatus::METRONOME => {
                    instructions.push(Instruction::ChangeVolatileStatusDuration(
                        ChangeVolatileStatusDurationInstruction {
                            side_ref: *side_ref,
                            volatile_status: *pkmn_volatile_status,
                            amount: -1 * side.volatile_status_durations.metronome,
                        },
                    ));
                    side.volatile_status_durations.metronome = 0;
                    false
                }
                _ => false,
            };

            if !should_retain {
                instructions.push(Instruction::RemoveVolatileStatus(
                    RemoveVolatileStatusInstruction {
                        side_ref: *side_ref,
                        volatile_status: *pkmn_volatile_status,
                    },
                ));
            }
            should_retain
        });

        // Clean up by re-setting the volatile statuses
        side.volatile_statuses = volatile_statuses;
    }

    pub fn terrain_is_active(&self, terrain: &Terrain) -> bool {
        &self.terrain.terrain_type == terrain && self.terrain.turns_remaining > 0
    }

    pub fn get_terrain(&self) -> Terrain {
        if self.terrain.turns_remaining > 0 {
            self.terrain.terrain_type
        } else {
            Terrain::NONE
        }
    }

    pub fn get_weather(&self) -> Weather {
        if self.weather.turns_remaining == 0 {
            return Weather::NONE;
        }
        if self.weather_suppressed() {
            Weather::NONE
        } else {
            self.weather.weather_type
        }
    }

    pub fn weather_is_active(&self, weather: &Weather) -> bool {
        &self.weather.weather_type == weather && !self.weather_suppressed()
    }

    // alpha-poke patch (2026-10-17, doc/engine-diff.md L208): an active Air Lock / Cloud Nine
    // that has not fainted (Showdown's suppressingWeather: !pokemon.fainted); a fainted holder
    // suppressed it until its replacement came in
    pub fn weather_suppressed(&self) -> bool {
        [&self.side_one, &self.side_two].iter().any(|s| {
            let p = s.get_active_immutable();
            matches!(p.ability, Abilities::AIRLOCK | Abilities::CLOUDNINE) && p.hp > 0
        })
    }

    fn _state_contains_any_move(&self, moves: &[Choices]) -> bool {
        for s in [&self.side_one, &self.side_two] {
            for pkmn in s.pokemon.into_iter() {
                for mv in pkmn.moves.into_iter() {
                    if moves.contains(&mv.id) {
                        return true;
                    }
                }
                // alpha-poke patch (2026-10-17, doc/engine-diff.md L213): a transformed mon's own
                // moves too (back as it leaves)
                if pkmn.own.moves.iter().any(|m| moves.contains(m)) {
                    return true;
                }
            }
        }

        false
    }

    pub fn set_damage_dealt_flag(&mut self) {
        if self._state_contains_any_move(&[
            Choices::COUNTER,
            Choices::MIRRORCOAT,
            Choices::METALBURST,
            Choices::COMEUPPANCE,
            Choices::FOCUSPUNCH,
            Choices::AVALANCHE,
        ]) {
            self.use_damage_dealt = true
        }
    }

    pub fn set_last_used_move_flag(&mut self) {
        // alpha-poke patch (2026-10-16, L24): Metronome counts on it
        // (L70: Disable / Cursed Body stop the last move too)
        let metronome = [&self.side_one, &self.side_two].iter().any(|s| {
            s.pokemon
                .pkmn
                .iter()
                .any(|p| p.item == Items::METRONOME || p.ability == Abilities::CURSEDBODY)
        });
        if metronome {
            self.use_last_used_move = true;
        }
        if self._state_contains_any_move(&[
            Choices::ENCORE,
            Choices::FAKEOUT,
            Choices::FIRSTIMPRESSION,
            Choices::BLOODMOON,
            Choices::GIGATONHAMMER,
            Choices::DISABLE,
            // (L179: Taunt reads it -- the target came in this turn, Showdown's activeTurns)
            Choices::TAUNT,
            // (L186: Eerie Spell takes the PP of the target's last move)
            Choices::EERIESPELL,
        ]) {
            self.use_last_used_move = true
        }
    }

    pub fn set_conditional_mechanics(&mut self) {
        /*
        These mechanics are not always relevant but when they are it
        is important that they are enabled. Enabling them all the time would
        suffer about a 20% performance hit.
        */
        self.set_damage_dealt_flag();
        self.set_last_used_move_flag();
        // (L163)
        if self._state_contains_any_move(&[Choices::RAGEFIST]) {
            self.use_times_attacked = true;
        }
        // (L167)
        if self._state_contains_any_move(&[Choices::COPYCAT]) {
            self.use_last_move = true;
        }
        // (L177)
        self.use_exact_pp = true;
    }
}

