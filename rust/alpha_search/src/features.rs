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

use poke_engine::engine::state::MoveChoice;
use poke_engine::state::{Pokemon, Side, State};

pub const N_ENTITIES: usize = 12;
pub const SPARSE: usize = 10;
pub const DENSE: usize = 23;
pub const SIDE_GLOBAL: usize = 18 + 7 + 2 + 104;
pub const GLOBAL: usize = 8 + 5 + 2 + 2 * SIDE_GLOBAL;
pub const N_ACTIONS: usize = 14;
/// embedding table sizes: species, item, ability, type (tera / type 1 / type 2), move
pub const VOCAB: [usize; 5] = [1536, 256, 384, 32, 1024];

pub struct Features {
    pub sparse: Vec<i32>, // [N_ENTITIES * SPARSE]
    pub dense: Vec<f32>,  // [N_ENTITIES * DENSE]
    pub global: Vec<f32>, // [GLOBAL]
    pub mask: Vec<u8>,    // [N_ACTIONS]
}

fn entity(p: &Pokemon, active: bool, own: bool, sparse: &mut Vec<i32>, dense: &mut Vec<f32>) {
    let m = [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3];
    sparse.extend_from_slice(&[
        p.id as i32,
        p.item as i32,
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

pub fn legal_mask(state: &State) -> Vec<u8> {
    let mut mask = vec![0u8; N_ACTIONS];
    let (o1, _) = state.root_get_all_options();
    for mc in o1 {
        let i = match mc {
            MoveChoice::Move(i) => i as usize,
            MoveChoice::MoveTera(i) => 4 + i as usize,
            MoveChoice::Switch(p) => 8 + p as usize,
            _ => continue,
        };
        if i < N_ACTIONS {
            mask[i] = 1;
        }
    }
    mask
}

pub fn featurize(state: &State) -> Features {
    let mut sparse = Vec::with_capacity(N_ENTITIES * SPARSE);
    let mut dense = Vec::with_capacity(N_ENTITIES * DENSE);
    for (own, side) in [(true, &state.side_one), (false, &state.side_two)] {
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
    side_global(&state.side_one, &mut global);
    side_global(&state.side_two, &mut global);
    debug_assert_eq!(sparse.len(), N_ENTITIES * SPARSE);
    debug_assert_eq!(dense.len(), N_ENTITIES * DENSE);
    debug_assert_eq!(global.len(), GLOBAL);
    Features {
        sparse,
        dense,
        global,
        mask: legal_mask(state),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
