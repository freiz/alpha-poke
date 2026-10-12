//! Network input features of a poke-engine state, from side one's point of view (design D13).
//!
//! The same function serves training (Python, via `alpha_search.featurize`) and inference inside
//! the search, so the two can never disagree.
//!
//! * 12 entities: side one's team slots 0-5, then side two's slots 0-5 (team-slot order, so the
//!   switch action 8 + j refers to entity j).
//!   - sparse ids (`SPARSE`): species, item, ability, tera type, type 1, type 2, move 0-3 —
//!     poke-engine's enum discriminants, looked up in embedding tables of `VOCAB` sizes;
//!   - dense (`DENSE`): HP fraction, alive, active, terastallized, status one-hot (7),
//!     attack / defense / sp. attack / sp. defense / speed / max HP (/ 500), the four moves'
//!     usability (not disabled, PP left), own side, level / 100.
//! * global (`GLOBAL`): weather one-hot (8), terrain one-hot (5), trick room + turns; per side:
//!   screens / tailwind / safeguard / mist turns, spikes, toxic spikes, stealth rock, sticky web,
//!   healing wish, lunar dance, wish, future sight, substitute, the seven boosts, force switch,
//!   force trapped, and the 104 volatile-status bits of its active mon.
//! * legal action mask (`N_ACTIONS`): 0-3 move slot, 4-7 move slot + tera, 8-13 switch to slot.
//! * history (v2, `history_features`): the last `HIST` decision steps (most recent first), each
//!   the two sides' actions in poke-engine's terms — a turn's chosen actions, a forced switch
//!   after a faint, a pivot switch. Sparse per step (`HIST_SPARSE`): own actor species, own move,
//!   own switch-in species, the same for the opponent (0 = none); dense (`HIST_DENSE`): step
//!   present, own move / switch / tera, opponent move / switch / tera, then (v4) each side's
//!   outcome: acted first, damage dealt (HP percent of the opposing active / 100), critical hit,
//!   missed / failed, KO, prevented (`|cant|`), fainted before acting. Independent of the state:
//!   training gets the steps from the replay, the search from the real game + its tree path (no
//!   outcomes on the tree path yet).

use poke_engine::choices::Choices;
use poke_engine::engine::state::MoveChoice;
use poke_engine::engine::items::Items;
use poke_engine::pokemon::PokemonName;
use poke_engine::state::{Pokemon, Side, State};
use std::str::FromStr;

pub const N_ENTITIES: usize = 12;
pub const SPARSE: usize = 10;
pub const DENSE: usize = 23;
pub const SIDE_GLOBAL: usize = 18 + 7 + 2 + 104;
pub const GLOBAL: usize = 8 + 5 + 2 + 2 * SIDE_GLOBAL;
pub const N_ACTIONS: usize = 14;
/// embedding table sizes: species, item, ability, type (tera / type 1 / type 2), move
pub const VOCAB: [usize; 5] = [1536, 256, 384, 32, 1024];
pub const HIST: usize = 8; // stored / featurized steps; a model may use fewer (config `hist`)
pub const HIST_SPARSE: usize = 6;
pub const HIST_DENSE: usize = 7 + 2 * 7;

/// One side's action in a decision step. `kind`: 0 none, 1 move, 2 switch; `target`: the move
/// (`Choices`) or the switch-in species (`PokemonName`) id; `actor`: the acting mon's species.
#[derive(Clone, Copy, Default, Debug, PartialEq)]
pub struct Act {
    pub kind: u8,
    pub tera: bool,
    pub actor: i32,
    pub target: i32,
    // outcome (v4; replay history only)
    pub first: bool,
    pub dmg: u8,
    pub crit: bool,
    pub miss: bool,
    pub ko: bool,
    pub prevented: bool,
    pub fainted_first: bool,
}

/// Both sides' actions in one decision step (side one / side two of the state).
#[derive(Clone, Copy, Default, Debug, PartialEq)]
pub struct Step {
    pub one: Act,
    pub two: Act,
}

impl Act {
    /// "" (none), "m:ACTOR:MOVE", "t:ACTOR:MOVE" (with tera), "s:ACTOR:SWITCHIN" (engine ids),
    /// optionally followed by ":DMG:FLAGS" (v4 outcome: HP percent dealt; c crit, x missed, k KO,
    /// f acted first); "p:ACTOR:REASON" (prevented) and "d:ACTOR:" (fainted before acting) are
    /// no action with that outcome.
    pub fn parse(s: &str) -> Act {
        let f: Vec<&str> = s.split(':').collect();
        if f.len() < 3 {
            return Act::default();
        }
        let species = |x: &str| PokemonName::from_str(x).map_or(0, |p| p as i32);
        let actor = species(f[1]);
        let flags = f.get(4).copied().unwrap_or("");
        let outcome = Act {
            first: flags.contains('f'),
            dmg: f
                .get(3)
                .and_then(|x| x.parse::<u16>().ok())
                .unwrap_or(0)
                .min(100) as u8,
            crit: flags.contains('c'),
            miss: flags.contains('x'),
            ko: flags.contains('k'),
            ..Act::default()
        };
        match f[0] {
            "m" | "t" => Act {
                kind: 1,
                tera: f[0] == "t",
                actor,
                target: Choices::from_str(f[2]).map_or(0, |c| c as i32),
                ..outcome
            },
            "s" => Act {
                kind: 2,
                actor,
                target: species(f[2]),
                ..outcome
            },
            "p" => Act {
                prevented: true,
                ..Act::default()
            },
            "d" => Act {
                fainted_first: true,
                ..Act::default()
            },
            _ => Act::default(),
        }
    }

    /// The action `mc` of `side` in the state it is chosen in (the search's tree path).
    pub fn of_choice(side: &Side, mc: &MoveChoice) -> Act {
        let me = side.get_active_immutable();
        let actor = me.id as i32;
        match mc {
            MoveChoice::Move(i) | MoveChoice::MoveTera(i) => Act {
                kind: 1,
                tera: matches!(mc, MoveChoice::MoveTera(_)),
                actor,
                target: me.moves[i].id as i32,
                ..Act::default()
            },
            MoveChoice::Switch(p) => Act {
                kind: 2,
                actor,
                target: side.pokemon[*p].id as i32,
                ..Act::default()
            },
            _ => Act::default(),
        }
    }
}

/// "ONE/TWO;ONE/TWO;..." (oldest first; ONE = side one's action) -> steps.
pub fn parse_history(s: &str) -> Vec<Step> {
    s.split(';')
        .filter(|x| !x.is_empty())
        .map(|x| {
            let (a, b) = x.split_once('/').unwrap_or((x, ""));
            Step {
                one: Act::parse(a),
                two: Act::parse(b),
            }
        })
        .collect()
}

/// History features of the last `HIST` steps (most recent first); `flip`: side two's view.
pub fn history_features(hist: &[Step], flip: bool, sparse: &mut Vec<i32>, dense: &mut Vec<f32>) {
    for k in 0..HIST {
        let Some(st) = hist.len().checked_sub(k + 1).map(|i| hist[i]) else {
            sparse.extend_from_slice(&[0; HIST_SPARSE]);
            dense.extend_from_slice(&[0.0; HIST_DENSE]);
            continue;
        };
        let (me, them) = if flip {
            (st.two, st.one)
        } else {
            (st.one, st.two)
        };
        dense.push(1.0);
        for a in [me, them] {
            let (mv, sw) = match a.kind {
                1 => (a.target, 0),
                2 => (0, a.target),
                _ => (0, 0),
            };
            sparse.extend_from_slice(&[if a.kind == 0 { 0 } else { a.actor }, mv, sw]);
        }
        for a in [me, them] {
            dense.extend_from_slice(&[
                (a.kind == 1) as u8 as f32,
                (a.kind == 2) as u8 as f32,
                a.tera as u8 as f32,
            ]);
        }
        for a in [me, them] {
            dense.extend_from_slice(&[
                a.first as u8 as f32,
                a.dmg as f32 / 100.0,
                a.crit as u8 as f32,
                a.miss as u8 as f32,
                a.ko as u8 as f32,
                a.prevented as u8 as f32,
                a.fainted_first as u8 as f32,
            ]);
        }
    }
}

pub struct Features {
    pub sparse: Vec<i32>, // [N_ENTITIES * SPARSE]
    pub dense: Vec<f32>,  // [N_ENTITIES * DENSE]
    pub global: Vec<f32>, // [GLOBAL]
    pub mask: Vec<u8>,    // [N_ACTIONS]
}

/// An item's id for the networks: items the engine learned after the networks' vocabularies
/// (the alpha-poke patch's Eject Button / Red Card, 2026-10-11) keep the id they had before,
/// unknown item
pub fn item_id(item: Items) -> i32 {
    match item {
        Items::EJECTBUTTON | Items::REDCARD => Items::UNKNOWNITEM as i32,
        x => x as i32,
    }
}

fn entity(p: &Pokemon, active: bool, own: bool, sparse: &mut Vec<i32>, dense: &mut Vec<f32>) {
    let m = [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3];
    sparse.extend_from_slice(&[
        p.id as i32,
        item_id(p.item),
        p.ability as i32,
        p.tera_type as i32,
        p.types.0 as i32,
        p.types.1 as i32,
        m[0].id as i32,
        m[1].id as i32,
        m[2].id as i32,
        m[3].id as i32,
    ]);
    let maxhp = p.maxhp.max(1) as f32;
    let alive = p.hp > 0;
    dense.push(if alive { p.hp as f32 / maxhp } else { 0.0 });
    dense.push(alive as u8 as f32);
    dense.push((active && alive) as u8 as f32);
    dense.push(p.terastallized as u8 as f32);
    let mut status = [0.0f32; 7];
    status[(p.status as usize).min(6)] = 1.0;
    dense.extend_from_slice(&status);
    for s in [
        p.attack,
        p.defense,
        p.special_attack,
        p.special_defense,
        p.speed,
        p.maxhp,
    ] {
        dense.push(s as f32 / 500.0);
    }
    for mv in m {
        dense.push((!mv.disabled && mv.pp > 0) as u8 as f32);
    }
    dense.push(own as u8 as f32);
    dense.push(p.level as f32 / 100.0);
}

fn side_global(s: &Side, g: &mut Vec<f32>) {
    let c = &s.side_conditions;
    for turns in [
        c.reflect,
        c.light_screen,
        c.aurora_veil,
        c.tailwind,
        c.safeguard,
        c.mist,
    ] {
        g.push(turns as f32 / 8.0);
    }
    g.push(c.spikes as f32 / 3.0);
    g.push(c.toxic_spikes as f32 / 2.0);
    g.push((c.stealth_rock > 0) as u8 as f32);
    g.push((c.sticky_web > 0) as u8 as f32);
    g.push((c.healing_wish > 0) as u8 as f32);
    g.push((c.lunar_dance > 0) as u8 as f32);
    g.push((s.wish.0 > 0) as u8 as f32);
    g.push((s.future_sight.0 > 0) as u8 as f32);
    g.push((s.substitute_health > 0) as u8 as f32);
    g.push(c.toxic_count as f32 / 8.0);
    g.push(s.baton_passing as u8 as f32);
    g.push(s.shed_tailing as u8 as f32);
    for b in [
        s.attack_boost,
        s.defense_boost,
        s.special_attack_boost,
        s.special_defense_boost,
        s.speed_boost,
        s.accuracy_boost,
        s.evasion_boost,
    ] {
        g.push(b as f32 / 6.0);
    }
    g.push(s.force_switch as u8 as f32);
    g.push(s.force_trapped as u8 as f32);
    for bit in 0..104 {
        g.push(((s.volatile_statuses.0 >> bit) & 1) as f32);
    }
}

/// Action slot of a move choice (relative to the side that makes it).
pub fn slot(mc: &MoveChoice) -> Option<usize> {
    let i = match mc {
        MoveChoice::Move(i) => *i as usize,
        MoveChoice::MoveTera(i) => 4 + *i as usize,
        MoveChoice::Switch(p) => 8 + *p as usize,
        _ => return None,
    };
    (i < N_ACTIONS).then_some(i)
}

fn mask_of(options: &[MoveChoice]) -> Vec<u8> {
    let mut mask = vec![0u8; N_ACTIONS];
    for i in options.iter().filter_map(slot) {
        mask[i] = 1;
    }
    mask
}

pub fn legal_mask(state: &State) -> Vec<u8> {
    mask_of(&state.root_get_all_options().0)
}

/// Side one's view (training and the value at the leaves).
pub fn featurize(state: &State) -> Features {
    featurize_view(state, false)
}

/// ``flip``: side two's view (its team first, its options in the mask) — the opponent's
/// policy prior in the search (design D13).
pub fn featurize_view(state: &State, flip: bool) -> Features {
    let (me, them) = if flip {
        (&state.side_two, &state.side_one)
    } else {
        (&state.side_one, &state.side_two)
    };
    let mut sparse = Vec::with_capacity(N_ENTITIES * SPARSE);
    let mut dense = Vec::with_capacity(N_ENTITIES * DENSE);
    for (own, side) in [(true, me), (false, them)] {
        let active = side.active_index as usize;
        for (j, p) in side.pokemon.pkmn.iter().enumerate() {
            entity(p, j == active, own, &mut sparse, &mut dense);
        }
    }
    let mut global = Vec::with_capacity(GLOBAL);
    let mut w = [0.0f32; 8];
    w[(state.weather.weather_type as usize).min(7)] = 1.0;
    global.extend_from_slice(&w);
    let mut t = [0.0f32; 5];
    t[(state.terrain.terrain_type as usize).min(4)] = 1.0;
    global.extend_from_slice(&t);
    global.push(state.trick_room.active as u8 as f32);
    global.push(state.trick_room.turns_remaining as f32 / 5.0);
    side_global(me, &mut global);
    side_global(them, &mut global);
    debug_assert_eq!(sparse.len(), N_ENTITIES * SPARSE);
    debug_assert_eq!(dense.len(), N_ENTITIES * DENSE);
    debug_assert_eq!(global.len(), GLOBAL);
    Features {
        sparse,
        dense,
        global,
        mask: {
            let (o1, o2) = state.root_get_all_options();
            mask_of(if flip { &o2 } else { &o1 })
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use poke_engine::state::PokemonMoveIndex;

    const FIXTURE: &str = include_str!("../../../tests/fixtures/engine_state_6v6.txt");

    #[test]
    fn shapes_vocab_and_mask() {
        for line in FIXTURE.lines() {
            let state = State::deserialize(line);
            let f = featurize(&state);
            assert_eq!(f.sparse.len(), N_ENTITIES * SPARSE);
            assert_eq!(f.dense.len(), N_ENTITIES * DENSE);
            assert_eq!(f.global.len(), GLOBAL);
            for e in 0..N_ENTITIES {
                let ids = &f.sparse[e * SPARSE..(e + 1) * SPARSE];
                let tables = [0, 1, 2, 3, 3, 3, 4, 4, 4, 4];
                for (k, &id) in ids.iter().enumerate() {
                    assert!(
                        id >= 0 && (id as usize) < VOCAB[tables[k]],
                        "entity {e} field {k}"
                    );
                }
            }
            // exactly one active entity per side
            let active: Vec<f32> = (0..N_ENTITIES).map(|e| f.dense[e * DENSE + 2]).collect();
            assert_eq!(active[..6].iter().sum::<f32>(), 1.0);
            assert_eq!(active[6..].iter().sum::<f32>(), 1.0);
            // the mask matches poke-engine's own options
            let (o1, _) = state.root_get_all_options();
            let n = f.mask.iter().filter(|&&m| m == 1).count();
            assert_eq!(n, o1.iter().filter(|m| **m != MoveChoice::None).count());
        }
    }

    #[test]
    fn history_parse_and_layout() {
        let h = parse_history("m:GLIMMORA:POWERGEM/s:IRONVALIANT:GREATTUSK;t:GLIMMORA:EARTHPOWER/");
        assert_eq!(h.len(), 2);
        assert_eq!(h[0].one.kind, 1);
        assert_eq!(h[0].one.target, Choices::POWERGEM as i32);
        assert_eq!(h[0].two.kind, 2);
        assert_eq!(h[0].two.target, PokemonName::GREATTUSK as i32);
        assert!(h[1].one.tera && h[1].two.kind == 0);
        let (mut sp, mut de) = (vec![], vec![]);
        history_features(&h, false, &mut sp, &mut de);
        assert_eq!(
            (sp.len(), de.len()),
            (HIST * HIST_SPARSE, HIST * HIST_DENSE)
        );
        // most recent first: tera Earth Power, opponent did nothing
        assert_eq!(sp[1], Choices::EARTHPOWER as i32);
        assert_eq!(&sp[3..6], &[0, 0, 0]);
        assert_eq!(&de[..7], &[1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0]);
        // flipped: the opponent's switch is "own"
        let (mut sp2, mut de2) = (vec![], vec![]);
        history_features(&h, true, &mut sp2, &mut de2);
        assert_eq!(sp2[HIST_SPARSE + 2], PokemonName::GREATTUSK as i32);
        assert!(de[2 * HIST_DENSE..].iter().all(|&x| x == 0.0)); // padding
                                                                 // the tree path gives the same ids
        let state = State::deserialize(FIXTURE.lines().next().unwrap());
        let a = Act::of_choice(&state.side_one, &MoveChoice::Move(PokemonMoveIndex::M0));
        let me = state.side_one.get_active_immutable();
        let want = Act {
            kind: 1,
            tera: false,
            actor: me.id as i32,
            target: me.moves.m0.id as i32,
            ..Act::default()
        };
        assert_eq!(a, want);
        let text = format!("m:{}:{}/", me.id, me.moves.m0.id);
        assert_eq!(parse_history(&text)[0].one, want); // engine names round-trip
        for &id in &sp {
            assert!(id >= 0 && (id as usize) < VOCAB[0].max(VOCAB[4]));
        }
        // v4 outcomes
        let h = parse_history("m:GREATTUSK:HEADLONGRUSH:57:fck/d:KINGAMBIT:;p:A:par/s:X:Y::f");
        assert_eq!(h[0].one.dmg, 57);
        assert!(h[0].one.first && h[0].one.crit && h[0].one.ko && !h[0].one.miss);
        assert!(h[0].two.fainted_first && h[0].two.kind == 0);
        assert!(h[1].one.prevented && h[1].two.kind == 2 && h[1].two.first);
        let (mut sp, mut de) = (vec![], vec![]);
        history_features(&h, false, &mut sp, &mut de);
        // most recent step first: prevented / switch
        assert_eq!(de[7 + 5], 1.0); // own prevented
        assert_eq!(de[14], 1.0); // opponent acted first
        let o = HIST_DENSE; // the older step
        assert_eq!(&de[o + 7..o + 14], &[1.0, 0.57, 1.0, 0.0, 1.0, 0.0, 0.0]);
        assert_eq!(de[o + 14 + 6], 1.0); // opponent fainted before acting
    }
}
