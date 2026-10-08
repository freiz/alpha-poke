//! v3 network inputs computed from a poke-engine state (design D13, network v3 first batch), next
//! to the v1 / v2 features (`features.rs`, unchanged so the v1 network keeps working):
//!
//! * static move table (`move_table`): per move id (`Choices`), its type, category, base power,
//!   accuracy, priority, flags and effects from poke-engine's move data — a fixed lookup the model
//!   projects onto the move embedding (rare moves get their properties without many samples);
//! * per entity (`ENT_EXTRA`, side-relative like `featurize_view`):
//!   - speed against the opposing active: log2(effective speed / the opposing active's) / 2,
//!     clipped to +-1.5 (boosts, Choice Scarf, paralysis, tailwind, weather abilities, ...;
//!     boosts and volatiles only for the active);
//!   - the threat from the opposing active: its best move's max damage / this mon's HP (clipped
//!     at 2), and whether that KOs for sure (min roll = 0.85 x max) / possibly (max roll);
//!   - actives only: each of its 4 moves against the opposing active: max damage / HP, KO for sure,
//!     KO possible, type effectiveness log2 / 2 (immune: -1.5);
//!   - benched only: entry hazard damage on switching in (Stealth Rock by type, Spikes when
//!     grounded; Heavy-Duty Boots / Magic Guard: none) as a fraction of max HP, and whether it
//!     faints on entry;
//!   - benched only (v4, switch-in counters): the damage it takes from the opposing active's
//!     predicted move (its strongest against this side's active) / HP and whether that KOs, and
//!     its own best move's damage against the opposing active / that one's HP;
//! * global (`GLOBAL_EXTRA`): per side (own, opponent) the living mons / 6, their summed HP
//!   fraction / 6, tera used, the last used move (none-or-switch / slot 0-3, a Choice lock); then
//!   who moves first between the actives (+1 own, -1 opponent, 0 tie; trick room counted) and the
//!   log2 speed ratio of the actives / 2; weather and terrain turns left / 8.
//!
//! Damage uses poke-engine's `calculate_damage_rolls` (the full Gen 9 damage calculation in the
//! world's sampled sets; abilities and items included, the defender's move ignored).

use poke_engine::choices::{Choice, Choices, MoveCategory, MoveTarget, MOVES};
use poke_engine::engine::abilities::Abilities;
use poke_engine::engine::damage_calc::{
    calculate_damage, type_effectiveness_modifier, DamageRolls,
};
use poke_engine::engine::generate_instructions::{before_move, calculate_damage_rolls};
use poke_engine::engine::items::Items;
use poke_engine::engine::state::{PokemonVolatileStatus, Terrain, Weather};
use poke_engine::instruction::StateInstructions;
use poke_engine::state::{
    LastUsedMove, Move, Pokemon, PokemonBoostableStat, PokemonIndex, PokemonMoveIndex,
    PokemonStatus, PokemonType, Side, SideReference, State,
};

pub const MOVE_FEAT: usize = 20 + 3 + 3 + 16 + 3 + 1 + 2 + 4 + 1;
pub const ENT_EXTRA: usize = 4 + 4 * 4 + 2 + 3;
pub const SIDE_EXTRA: usize = 3 + 5;
pub const GLOBAL_EXTRA: usize = 2 * SIDE_EXTRA + 2 + 2;

/// Static properties of every move: [VOCAB move, MOVE_FEAT] row-major (row = `Choices` id).
pub fn move_table(vocab: usize) -> Vec<f32> {
    let mut t = vec![0.0f32; vocab * MOVE_FEAT];
    for (id, c) in MOVES.iter() {
        let i = *id as usize;
        if i == 0 || i >= vocab {
            continue;
        }
        t[i * MOVE_FEAT..(i + 1) * MOVE_FEAT].copy_from_slice(&move_row(c));
    }
    t
}

fn move_row(c: &Choice) -> [f32; MOVE_FEAT] {
    let mut r = [0.0f32; MOVE_FEAT];
    let mut k = 0;
    let mut push = |x: f32| {
        r[k] = x;
        k += 1;
    };
    let ty = c.move_type as usize;
    for j in 0..20 {
        push((j == ty) as u8 as f32);
    }
    for cat in [
        MoveCategory::Physical,
        MoveCategory::Special,
        MoveCategory::Status,
    ] {
        push((c.category == cat) as u8 as f32);
    }
    push((c.base_power / 150.0).min(2.0));
    push(c.accuracy / 100.0);
    push(c.priority as f32 / 5.0);
    let f = &c.flags;
    for b in [
        f.bite,
        f.bullet,
        f.charge,
        f.contact,
        f.drag,
        f.heal,
        f.powder,
        f.protect,
        f.pulse,
        f.punch,
        f.recharge,
        f.reflectable,
        f.slicing,
        f.sound,
        f.pivot,
        f.wind,
    ] {
        push(b as u8 as f32);
    }
    push(c.drain.unwrap_or(0.0));
    push(c.recoil.unwrap_or(0.0));
    push(c.crash.is_some() as u8 as f32);
    push(c.heal.as_ref().map_or(0.0, |h| h.amount));
    let (mut up, mut down) = (0.0f32, 0.0f32);
    if let Some(b) = &c.boost {
        let s = &b.boosts;
        let sum = [
            s.attack,
            s.defense,
            s.special_attack,
            s.special_defense,
            s.speed,
            s.accuracy,
        ]
        .iter()
        .map(|&x| x as f32)
        .sum::<f32>();
        if b.target == MoveTarget::User {
            up = sum;
        } else {
            down = sum;
        }
    }
    push(up / 2.0);
    push(down / 2.0);
    push(c.status.is_some() as u8 as f32);
    push(c.volatile_status.is_some() as u8 as f32);
    let sc = c.side_condition.as_ref();
    push(sc.is_some_and(|s| s.target == MoveTarget::User) as u8 as f32);
    push(sc.is_some_and(|s| s.target == MoveTarget::Opponent) as u8 as f32);
    let chance = c
        .secondaries
        .as_ref()
        .map_or(0.0, |v| v.iter().map(|s| s.chance).fold(0.0, f32::max));
    push(chance / 100.0);
    debug_assert_eq!(k, MOVE_FEAT);
    r
}

fn side_ref(own: bool, flip: bool) -> SideReference {
    if own != flip {
        SideReference::SideOne
    } else {
        SideReference::SideTwo
    }
}

/// poke-engine's effective speed (generate_instructions::get_effective_speed, private there) for
/// the active; for a benched mon its raw speed with item / status / tailwind.
fn effective_speed(state: &State, side: &Side, idx: usize) -> f32 {
    let p = &side.pokemon.pkmn[idx];
    let active = idx == side.active_index as usize;
    let mut s = if active {
        side.calculate_boosted_stat(PokemonBoostableStat::Speed) as f32
    } else {
        p.speed as f32
    };
    match state.weather.weather_type {
        Weather::SUN | Weather::HARSHSUN if p.ability == Abilities::CHLOROPHYLL => s *= 2.0,
        Weather::RAIN | Weather::HEAVYRAIN if p.ability == Abilities::SWIFTSWIM => s *= 2.0,
        Weather::SAND if p.ability == Abilities::SANDRUSH => s *= 2.0,
        Weather::HAIL if p.ability == Abilities::SLUSHRUSH => s *= 2.0,
        _ => {}
    }
    if p.ability == Abilities::SURGESURFER && state.terrain.terrain_type == Terrain::ELECTRICTERRAIN
    {
        s *= 2.0;
    }
    if p.ability == Abilities::QUICKFEET && p.status != PokemonStatus::NONE {
        s *= 1.5;
    }
    if active {
        let v = &side.volatile_statuses;
        if p.ability == Abilities::UNBURDEN && v.contains(&PokemonVolatileStatus::UNBURDEN) {
            s *= 2.0;
        }
        if v.contains(&PokemonVolatileStatus::SLOWSTART) {
            s *= 0.5;
        }
        if v.contains(&PokemonVolatileStatus::PROTOSYNTHESISSPE)
            || v.contains(&PokemonVolatileStatus::QUARKDRIVESPE)
        {
            s *= 1.5;
        }
    }
    if side.side_conditions.tailwind > 0 {
        s *= 2.0;
    }
    match p.item {
        Items::IRONBALL => s *= 0.5,
        Items::CHOICESCARF => s *= 1.5,
        _ => {}
    }
    if p.status == PokemonStatus::PARALYZE && p.ability != Abilities::QUICKFEET {
        s *= 0.5;
    }
    s.max(1.0)
}

/// Entry hazard damage (fraction of max HP) for `p` switching in on `side`.
fn hazard_damage(side: &Side, p: &Pokemon) -> f32 {
    if p.item == Items::HEAVYDUTYBOOTS || p.ability == Abilities::MAGICGUARD {
        return 0.0;
    }
    let c = &side.side_conditions;
    let mut d = 0.0;
    if c.stealth_rock > 0 {
        d += 0.125 * type_effectiveness_modifier(&PokemonType::ROCK, p);
    }
    let flying = p.types.0 == PokemonType::FLYING || p.types.1 == PokemonType::FLYING;
    let grounded = !flying && p.ability != Abilities::LEVITATE && p.item != Items::AIRBALLOON;
    if grounded {
        d += match c.spikes {
            1 => 1.0 / 8.0,
            2 => 1.0 / 6.0,
            s if s >= 3 => 0.25,
            _ => 0.0,
        };
    }
    d
}

fn log_ratio(a: f32, b: f32) -> f32 {
    ((a / b).log2() / 2.0).clamp(-1.5, 1.5)
}

/// Max damage of `choice` by the attacker side's active on the defender side's mon `def_idx`
/// (made active in a copy of the state when it is benched); None for a status move / no damage.
fn max_damage(
    state: &State,
    attacker: &SideReference,
    choice: &Choice,
    def_idx: usize,
) -> Option<f32> {
    if choice.move_id == Choices::NONE || choice.category == MoveCategory::Status {
        return None;
    }
    let mut s = state.clone();
    let def = s.get_side(&attacker.get_other_side());
    if def.active_index as usize != def_idx {
        def.active_index = PokemonIndex::deserialize(&def_idx.to_string());
    }
    calculate_damage_rolls(s, attacker, choice.clone(), &Choice::default())
        .and_then(|v| v.first().copied())
        .map(|d| d.max(0) as f32)
}

/// `max_damage` on the unmodified state (`work`: a copy, restored after every in-place call),
/// memoized per (attacking side, move slot, defending slot): the same calls recur (the
/// predicted move, the threats, the actives' moves).
struct DamageMemo {
    work: State,
    inplace: bool,
    refs: [SideReference; 2],
    memo: [[[Option<Option<f32>>; 6]; 4]; 2],
}

impl DamageMemo {
    fn damage(&mut self, att: usize, choice: &Choice, def: usize) -> Option<f32> {
        if self.inplace {
            max_damage_inplace(&mut self.work, &self.refs[att], choice, def)
        } else {
            max_damage(&self.work, &self.refs[att], choice, def)
        }
    }

    /// `att`: index into `refs` of the attacking side (its active attacks with move `slot`)
    fn get(&mut self, att: usize, slot: usize, choice: &Choice, def: usize) -> Option<f32> {
        if let Some(v) = self.memo[att][slot][def] {
            return v;
        }
        let v = self.damage(att, choice, def);
        self.memo[att][slot][def] = Some(v);
        v
    }

    /// The best max damage of side `att`'s mon `j` (made active) against the other side's mon
    /// `def` (its active).
    fn bench_best(&mut self, att: usize, j: usize, moves: &[&Move; 4], def: usize) -> f32 {
        let side = self.refs[att];
        let active = self.work.get_side_immutable(&side).active_index;
        self.work.get_side(&side).active_index = PokemonIndex::deserialize(&j.to_string());
        let best = moves
            .iter()
            .filter_map(|m| self.damage(att, &m.choice, def))
            .fold(0.0f32, f32::max);
        self.work.get_side(&side).active_index = active;
        best
    }
}

/// (ENT_EXTRA per entity in view order: own 0-5, opponent 0-5; GLOBAL_EXTRA).
///
/// Speed: poke-engine's `calculate_damage_rolls` takes the state by value (its `before_move`
/// changes it), and that copy was ~90% of each of the ~100 damage calls here. This computes the
/// damage on one working copy instead and undoes `before_move`'s instructions after each call
/// (`damage_inplace`; `before_move` is made public by rust/patches/poke-engine-0.0.48). Bitwise
/// the same features as copying (`featurize_extra_reference`; scripts/check_extra.py on real
/// states, test `inplace_matches_reference`).
pub fn featurize_extra(state: &State, flip: bool) -> (Vec<f32>, Vec<f32>) {
    featurize_extra_with(state, flip, true)
}

/// The same with a copy of the state per damage call (poke-engine's `calculate_damage_rolls`):
/// the reference for checking `featurize_extra`.
pub fn featurize_extra_reference(state: &State, flip: bool) -> (Vec<f32>, Vec<f32>) {
    featurize_extra_with(state, flip, false)
}

/// `calculate_damage_rolls(state.clone(), side, choice, &Choice::default())`'s first roll (the
/// max non-crit damage), computed on `state` itself and restored afterwards: the same steps
/// (special-damage moves, Fake Out's last-move check, `before_move` -> reversed, Future Sight,
/// `calculate_damage`).
fn damage_inplace(state: &mut State, side: &SideReference, mut choice: Choice) -> Option<i16> {
    let default = Choice::default();
    let mut defending_choice = &default;
    if choice.flags.charge {
        choice.flags.charge = false;
    }
    let last = state.get_side_immutable(side).last_used_move;
    if choice.move_id == Choices::FAKEOUT || choice.move_id == Choices::FIRSTIMPRESSION {
        state.get_side(side).last_used_move = LastUsedMove::Switch(PokemonIndex::P0);
    }
    let restore = |state: &mut State| state.get_side(side).last_used_move = last;
    let attacker = state.get_side_immutable(side).get_active_immutable();
    let defender = state
        .get_side_immutable(&side.get_other_side())
        .get_active_immutable();
    let immune = |t: &PokemonType| type_effectiveness_modifier(t, defender) == 0.0;
    let special = match choice.move_id {
        Choices::SEISMICTOSS => {
            Some((!immune(&PokemonType::NORMAL)).then_some(attacker.level as i16))
        }
        Choices::NIGHTSHADE => {
            Some((!immune(&PokemonType::GHOST)).then_some(attacker.level as i16))
        }
        Choices::FINALGAMBIT => Some((!immune(&PokemonType::GHOST)).then_some(attacker.hp)),
        Choices::ENDEAVOR => Some(
            (!immune(&PokemonType::GHOST) && defender.hp > attacker.hp)
                .then_some(defender.hp - attacker.hp),
        ),
        Choices::PAINSPLIT => Some(
            (!immune(&PokemonType::GHOST) && defender.hp > attacker.hp)
                .then_some(defender.hp - (attacker.hp + defender.hp) / 2),
        ),
        Choices::SUPERFANG if immune(&PokemonType::NORMAL) => Some(None),
        Choices::SUPERFANG | Choices::NATURESMADNESS | Choices::RUINATION => {
            Some(Some(defender.hp / 2))
        }
        Choices::SUCKERPUNCH | Choices::THUNDERCLAP => {
            defending_choice = MOVES.get(&Choices::TACKLE).unwrap();
            None
        }
        _ => None,
    };
    if let Some(r) = special {
        restore(state);
        return r;
    }
    let mut incoming = StateInstructions::default();
    before_move(state, &mut choice, defending_choice, side, &mut incoming);
    if choice.move_id == Choices::FUTURESIGHT {
        choice = MOVES.get(&Choices::FUTURESIGHT).unwrap().clone();
    }
    let r = calculate_damage(state, side, &choice, DamageRolls::Max).map(|(d, _)| d);
    state.reverse_instructions(&incoming.instruction_list);
    restore(state);
    r
}

/// `max_damage` on `state` itself (restored afterwards).
fn max_damage_inplace(
    state: &mut State,
    attacker: &SideReference,
    choice: &Choice,
    def_idx: usize,
) -> Option<f32> {
    if choice.move_id == Choices::NONE || choice.category == MoveCategory::Status {
        return None;
    }
    let other = attacker.get_other_side();
    let active = state.get_side_immutable(&other).active_index;
    if active as usize != def_idx {
        state.get_side(&other).active_index = PokemonIndex::deserialize(&def_idx.to_string());
    }
    let r = damage_inplace(state, attacker, choice.clone()).map(|d| d.max(0) as f32);
    state.get_side(&other).active_index = active;
    r
}

/// `inplace`: damage on a working copy restored after each call, else a copy per call.
fn featurize_extra_with(state: &State, flip: bool, inplace: bool) -> (Vec<f32>, Vec<f32>) {
    let mut ent = vec![0.0f32; 12 * ENT_EXTRA];
    let mut glob = Vec::with_capacity(GLOBAL_EXTRA);
    let refs = [side_ref(true, flip), side_ref(false, flip)];
    let sides = [
        state.get_side_immutable(&refs[0]),
        state.get_side_immutable(&refs[1]),
    ];
    let act = [
        sides[0].active_index as usize,
        sides[1].active_index as usize,
    ];
    let mut memo = DamageMemo {
        work: state.clone(),
        inplace,
        refs,
        memo: [[[None; 6]; 4]; 2],
    };
    let speed_act = [
        effective_speed(state, sides[0], act[0]),
        effective_speed(state, sides[1], act[1]),
    ];
    for s in 0..2 {
        let (me, other) = (sides[s], sides[1 - s]);
        let attacker_alive = other.pokemon.pkmn[act[1 - s]].hp > 0;
        let att = &other.pokemon.pkmn[act[1 - s]];
        let att_moves = [&att.moves.m0, &att.moves.m1, &att.moves.m2, &att.moves.m3];
        // the opposing active's predicted move: its strongest against this side's active
        let predicted = if attacker_alive && me.pokemon.pkmn[act[s]].hp > 0 {
            att_moves
                .iter()
                .enumerate()
                .filter(|(_, m)| !m.disabled)
                .filter_map(|(k, m)| memo.get(1 - s, k, &m.choice, act[s]).map(|d| (d, k)))
                .max_by(|a, b| a.0.total_cmp(&b.0))
                .map(|(_, k)| k)
        } else {
            None
        };
        let target_hp = att.hp.max(1) as f32;
        for j in 0..6 {
            let p = &me.pokemon.pkmn[j];
            if p.hp <= 0 {
                continue;
            }
            let e = &mut ent[(s * 6 + j) * ENT_EXTRA..(s * 6 + j + 1) * ENT_EXTRA];
            e[0] = log_ratio(effective_speed(state, me, j), speed_act[1 - s]);
            if j != act[s] {
                let h = hazard_damage(me, p);
                e[20] = h;
                e[21] = (h * p.maxhp as f32 >= p.hp as f32) as u8 as f32;
                if let Some(k) = predicted {
                    let d = memo.get(1 - s, k, &att_moves[k].choice, j).unwrap_or(0.0);
                    let hp = p.hp as f32;
                    e[22] = (d / hp).min(2.0);
                    e[23] = (d >= hp) as u8 as f32;
                }
                if attacker_alive {
                    // this bench mon's best move vs the opposing active (as if it were in)
                    let moves = [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3];
                    let best = memo.bench_best(s, j, &moves, act[1 - s]);
                    e[24] = (best / target_hp).min(2.0);
                }
            }
            let hp = p.hp as f32;
            if attacker_alive {
                let best = att_moves
                    .iter()
                    .enumerate()
                    .filter(|(_, m)| !m.disabled)
                    .filter_map(|(k, m)| memo.get(1 - s, k, &m.choice, j))
                    .fold(0.0f32, f32::max);
                e[1] = (best / hp).min(2.0);
                e[2] = (0.85 * best >= hp) as u8 as f32;
                e[3] = (best >= hp) as u8 as f32;
            }
        }
        // the active's own moves against the opposing active
        let p = &me.pokemon.pkmn[act[s]];
        let target = &other.pokemon.pkmn[act[1 - s]];
        if p.hp > 0 && target.hp > 0 {
            let e = &mut ent[(s * 6 + act[s]) * ENT_EXTRA..(s * 6 + act[s] + 1) * ENT_EXTRA];
            for (i, m) in [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3]
                .iter()
                .enumerate()
            {
                let o = 4 + 4 * i;
                if let Some(d) = memo.get(s, i, &m.choice, act[1 - s]) {
                    let hp = target.hp as f32;
                    e[o] = (d / hp).min(2.0);
                    e[o + 1] = (0.85 * d >= hp) as u8 as f32;
                    e[o + 2] = (d >= hp) as u8 as f32;
                }
                if m.id != Choices::NONE && m.choice.category != MoveCategory::Status {
                    let te = type_effectiveness_modifier(&m.choice.move_type, target);
                    e[o + 3] = if te <= 0.0 { -1.5 } else { te.log2() / 2.0 };
                }
            }
        }
    }
    for side in sides {
        let alive = side.pokemon.pkmn.iter().filter(|p| p.hp > 0).count();
        let hp: f32 = side
            .pokemon
            .pkmn
            .iter()
            .filter(|p| p.hp > 0)
            .map(|p| p.hp as f32 / p.maxhp.max(1) as f32)
            .sum();
        glob.push(alive as f32 / 6.0);
        glob.push(hp / 6.0);
        glob.push(side.pokemon.pkmn.iter().any(|p| p.terastallized) as u8 as f32);
        let mut last = [0.0f32; 5];
        last[match side.last_used_move {
            LastUsedMove::Move(PokemonMoveIndex::M0) => 1,
            LastUsedMove::Move(PokemonMoveIndex::M1) => 2,
            LastUsedMove::Move(PokemonMoveIndex::M2) => 3,
            LastUsedMove::Move(PokemonMoveIndex::M3) => 4,
            _ => 0,
        }] = 1.0;
        glob.extend_from_slice(&last);
    }
    let (a, b) = (speed_act[0], speed_act[1]);
    let first = if a == b {
        0.0
    } else if (a > b) != state.trick_room.active {
        1.0
    } else {
        -1.0
    };
    glob.push(first);
    glob.push(log_ratio(a, b));
    glob.push(state.weather.turns_remaining.max(0) as f32 / 8.0);
    glob.push(state.terrain.turns_remaining.max(0) as f32 / 8.0);
    debug_assert_eq!(glob.len(), GLOBAL_EXTRA);
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
    fn move_table_rows() {
        let t = move_table(1024);
        let row = |c: Choices| &t[c as usize * MOVE_FEAT..(c as usize + 1) * MOVE_FEAT];
        let eq = row(Choices::EARTHQUAKE);
        assert_eq!(eq[8], 1.0, "ground type"); // NORMAL=0 ... GROUND=8
        assert_eq!(eq[20], 1.0, "physical");
        assert!((eq[23] - 100.0 / 150.0).abs() < 1e-6);
        let sr = row(Choices::STEALTHROCK);
        assert_eq!(sr[22], 1.0, "status");
        assert_eq!(sr[MOVE_FEAT - 2], 1.0, "side condition on the opponent");
        assert!(row(Choices::EXTREMESPEED)[25] > 0.0, "priority");
    }

    /// the in-place damage path gives bitwise the features of the copying one
    #[test]
    fn inplace_matches_reference() {
        let st = fixture();
        for flip in [false, true] {
            let (e1, g1) = featurize_extra(&st, flip);
            let (e2, g2) = featurize_extra_reference(&st, flip);
            assert!(e1.iter().zip(&e2).all(|(a, b)| a.to_bits() == b.to_bits()));
            assert!(g1.iter().zip(&g2).all(|(a, b)| a.to_bits() == b.to_bits()));
        }
    }

    #[test]
    fn extra_features_shapes_and_flip() {
        let st = fixture();
        let (e, g) = featurize_extra(&st, false);
        assert_eq!(e.len(), 12 * ENT_EXTRA);
        assert_eq!(g.len(), GLOBAL_EXTRA);
        let (e2, g2) = featurize_extra(&st, true);
        // flipping swaps the two sides' blocks
        assert_eq!(&e[..6 * ENT_EXTRA], &e2[6 * ENT_EXTRA..]);
        assert_eq!(&g[..SIDE_EXTRA], &g2[SIDE_EXTRA..2 * SIDE_EXTRA]);
        assert_eq!(g[2 * SIDE_EXTRA], -g2[2 * SIDE_EXTRA]);
        // the actives have damage numbers for some move
        let a1 = st.side_one.active_index as usize;
        let ea = &e[a1 * ENT_EXTRA..(a1 + 1) * ENT_EXTRA];
        assert!((0..4).any(|i| ea[4 + 4 * i] > 0.0), "{ea:?}");
        assert!(e.iter().all(|x| x.is_finite()));
    }
}
