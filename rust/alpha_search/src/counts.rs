//! v6 network inputs (design TODO v6 "new features"): the counters of a poke-engine state that the v1 /
//! v3 features leave out (the move usability bit merges "no PP" with "disabled"; the volatile
//! bits say a status is on, not for how long), side-relative like `featurize_view`:
//!
//! * per entity (`ENT_COUNT`): each move's PP left, min(pp, 16) / 16 (exact for our side; the
//!   opponent's as `build_state` estimates it from its uses), each move disabled (our active:
//!   not offered by the request, e.g. a Choice lock; the opponent's: Disable), and while asleep
//!   the Rest turns / other sleep turns (/ 3); all 0 for an empty move slot and a fainted mon
//!   (`COUNT_VERSION` 2: version 1 had the empty slots' placeholder PP / disabled flags);
//! * per side (`SIDE_COUNT`, own then opponent): consecutive protects (/ 4), the substitute's HP
//!   / the active's max HP, Wish turns (/ 2) and heal / the active's max HP, Future Sight turns
//!   (/ 3), and the turn counters of confusion, Encore, a locked move, Slow Start, Taunt, Yawn,
//!   Heal Block, Magnet Rise and Throat Chop (/ 5; 0 when the volatile is off).
//!
//! Cheap (no damage calculation): always computed, read by networks with the "count" group.

use poke_engine::choices::Choices;
use poke_engine::engine::state::PokemonVolatileStatus;
use poke_engine::state::{PokemonStatus, Side, State};

/// bumped whenever the features' meaning changes (training caches of another version are rebuilt)
pub const COUNT_VERSION: usize = 2;
pub const ENT_COUNT: usize = 4 + 4 + 2;
pub const SIDE_COUNT: usize = 5 + 9;
pub const GLOBAL_COUNT: usize = 2 * SIDE_COUNT;

fn side_counts(s: &Side, g: &mut Vec<f32>) {
    let active = s.get_active_immutable();
    let maxhp = active.maxhp.max(1) as f32;
    g.push(s.side_conditions.protect.clamp(0, 4) as f32 / 4.0);
    g.push((s.substitute_health.max(0) as f32 / maxhp).min(1.0));
    let wish = s.wish.0 > 0;
    g.push(if wish { s.wish.0 as f32 / 2.0 } else { 0.0 });
    g.push(if wish {
        (s.wish.1.max(0) as f32 / maxhp).min(1.0)
    } else {
        0.0
    });
    g.push(s.future_sight.0.max(0) as f32 / 3.0);
    let d = &s.volatile_status_durations;
    let v = &s.volatile_statuses;
    for (turns, vs) in [
        (d.confusion, PokemonVolatileStatus::CONFUSION),
        (d.encore, PokemonVolatileStatus::ENCORE),
        (d.lockedmove, PokemonVolatileStatus::LOCKEDMOVE),
        (d.slowstart, PokemonVolatileStatus::SLOWSTART),
        (d.taunt, PokemonVolatileStatus::TAUNT),
        (d.yawn, PokemonVolatileStatus::YAWN),
        (d.healblock, PokemonVolatileStatus::HEALBLOCK),
        (d.magnetrise, PokemonVolatileStatus::MAGNETRISE),
        (d.throatchop, PokemonVolatileStatus::THROATCHOP),
    ] {
        g.push(if v.contains(&vs) {
            turns.max(0) as f32 / 5.0
        } else {
            0.0
        });
    }
}

/// (ENT_COUNT per entity in view order: own 0-5, opponent 0-5; GLOBAL_COUNT).
pub fn featurize_counts(state: &State, flip: bool) -> (Vec<f32>, Vec<f32>) {
    let (me, them) = if flip {
        (&state.side_two, &state.side_one)
    } else {
        (&state.side_one, &state.side_two)
    };
    let mut ent = Vec::with_capacity(12 * ENT_COUNT);
    for side in [me, them] {
        for p in side.pokemon.pkmn.iter() {
            let m = [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3];
            let real = |mv: &&poke_engine::state::Move| p.hp > 0 && mv.id != Choices::NONE;
            for mv in m {
                ent.push(if real(&mv) {
                    mv.pp.clamp(0, 16) as f32 / 16.0
                } else {
                    0.0
                });
            }
            for mv in m {
                ent.push((real(&mv) && mv.disabled) as u8 as f32);
            }
            let asleep = p.hp > 0 && p.status == PokemonStatus::SLEEP;
            ent.push(if asleep {
                p.rest_turns.max(0) as f32 / 3.0
            } else {
                0.0
            });
            ent.push(if asleep {
                p.sleep_turns.max(0) as f32 / 3.0
            } else {
                0.0
            });
        }
    }
    let mut glob = Vec::with_capacity(GLOBAL_COUNT);
    side_counts(me, &mut glob);
    side_counts(them, &mut glob);
    debug_assert_eq!(ent.len(), 12 * ENT_COUNT);
    debug_assert_eq!(glob.len(), GLOBAL_COUNT);
    (ent, glob)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> State {
        let s = include_str!("../../../tests/fixtures/engine_state_6v6.txt");
        State::deserialize(s.lines().next().unwrap())
    }

    #[test]
    fn shapes_flip_and_values() {
        let mut st = fixture();
        let (e, g) = featurize_counts(&st, false);
        assert_eq!((e.len(), g.len()), (12 * ENT_COUNT, GLOBAL_COUNT));
        assert!(e
            .iter()
            .chain(&g)
            .all(|x| x.is_finite() && (0.0..=1.0).contains(x)));
        let (e2, g2) = featurize_counts(&st, true);
        assert_eq!(&e[..6 * ENT_COUNT], &e2[6 * ENT_COUNT..]);
        assert_eq!(&g[..SIDE_COUNT], &g2[SIDE_COUNT..]);
        // counters show up where they belong
        st.side_one.side_conditions.protect = 2;
        st.side_two.substitute_health = 1;
        st.side_one.volatile_status_durations.taunt = 2;
        let (_, g3) = featurize_counts(&st, false);
        assert_eq!(g3[0], 0.5);
        assert!(g3[SIDE_COUNT + 1] > 0.0);
        assert_eq!(g3[5 + 4], 0.0, "taunt turns without the volatile");
        st.side_one
            .volatile_statuses
            .insert(PokemonVolatileStatus::TAUNT);
        let (_, g4) = featurize_counts(&st, false);
        assert_eq!(g4[5 + 4], 0.4);
        let a = st.side_one.active_index as usize;
        st.side_one.pokemon.pkmn[a].moves.m1.pp = 4;
        st.side_one.pokemon.pkmn[a].moves.m2.disabled = true;
        let (e5, _) = featurize_counts(&st, false);
        assert_eq!(e5[a * ENT_COUNT + 1], 0.25);
        assert_eq!(e5[a * ENT_COUNT + 4 + 2], 1.0);
    }
}
