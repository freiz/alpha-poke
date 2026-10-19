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
//!
//! A benched mon in a hypothetical matchup is made its side's active with none of the active's
//! own state (boosts, volatiles, substitute: side-level in the engine); before `EXTRA_VERSION` 2
//! it took the active's (design TODO P0, 2026-10-19).
//!
//! v7 entity inputs (`featurize_extra_full`, [12, ENT_NEW], side-relative; design TODO 特征候选,
//! 2026-10-19), from the same damage memo:
//! * `ko2` (F3a, actives): each of its moves against the opposing active: two-hit KO for sure /
//!   possibly, the target's end-of-turn HP change (`residual`: Leftovers, status, weather, Leech
//!   Seed, Salt Cure, ...) between the hits; then the opposing active's priority moves against
//!   it: KO for sure / possibly (none on a grounded target in Psychic Terrain);
//! * `tera` (F6, actives): if its side can still terastallize, its moves terastallized against
//!   the opposing active (max damage / HP, KO for sure, possibly) and the opposing active's best
//!   hit on it terastallized; if the other side can, its moves against the opposing active
//!   terastallized (damage / HP, KO possible) and that one's best hit on it then; the two flags.
//!   The opponent's tera type is the world's sample: across worlds, the posterior;
//! * `team` (F5, every living mon, against the other side's living mons, each made active):
//!   how many it KOs (max roll), how many KO it, against how many it takes under half its HP
//!   (a switch-in), against how many it is faster and KOs (a revenge kill); as a threat, how many
//!   of the other side's mons answer it (survive its best hit and 2HKO it, or revenge-kill it),
//!   whether only one does; as an answer, for how many threats it is the only one.

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
    LastUsedMove, Pokemon, PokemonBoostableStat, PokemonIndex, PokemonMoveIndex,
    PokemonStatus, PokemonType, Side, SideReference, State,
};

/// 2: benched mons made active without the active's boosts / volatiles / substitute
pub const EXTRA_VERSION: usize = 2;
pub const MOVE_FEAT: usize = 20 + 3 + 3 + 16 + 3 + 1 + 2 + 4 + 1;
pub const ENT_KO2: usize = 4 * 2 + 2;
pub const ENT_TERA: usize = 4 * 3 + 3 + 4 * 2 + 3 + 2;
pub const ENT_TEAM: usize = 7;
/// the v7 entity inputs: ko2 [0, ENT_KO2), tera, team
pub const ENT_NEW: usize = ENT_KO2 + ENT_TERA + ENT_TEAM;
/// F2 (`posterior`): per entity, the action-consequence probabilities over belief worlds
pub const N_POST: usize = 10;
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

/// A benched mon made its side's active for a hypothetical matchup: the active's own state is
/// saved and cleared (its boosts, volatiles and substitute are side-level in the engine), and
/// restored by `leave`. None when `j` is the active already.
struct Saved {
    idx: PokemonIndex,
    boosts: [i8; 7],
    vol: u128,
    sub: i16,
}

fn enter(side: &mut Side, j: usize) -> Option<Saved> {
    if side.active_index as usize == j {
        return None;
    }
    let saved = Saved {
        idx: side.active_index,
        boosts: [
            side.attack_boost,
            side.defense_boost,
            side.special_attack_boost,
            side.special_defense_boost,
            side.speed_boost,
            side.accuracy_boost,
            side.evasion_boost,
        ],
        vol: side.volatile_statuses.0,
        sub: side.substitute_health,
    };
    side.active_index = PokemonIndex::deserialize(&j.to_string());
    side.attack_boost = 0;
    side.defense_boost = 0;
    side.special_attack_boost = 0;
    side.special_defense_boost = 0;
    side.speed_boost = 0;
    side.accuracy_boost = 0;
    side.evasion_boost = 0;
    side.volatile_statuses.0 = 0;
    side.substitute_health = 0;
    Some(saved)
}

fn leave(side: &mut Side, saved: Option<Saved>) {
    if let Some(v) = saved {
        side.active_index = v.idx;
        [
            side.attack_boost,
            side.defense_boost,
            side.special_attack_boost,
            side.special_defense_boost,
            side.speed_boost,
            side.accuracy_boost,
            side.evasion_boost,
        ] = v.boosts;
        side.volatile_statuses.0 = v.vol;
        side.substitute_health = v.sub;
    }
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
    enter(s.get_side(&attacker.get_other_side()), def_idx);
    calculate_damage_rolls(s, attacker, choice.clone(), &Choice::default())
        .and_then(|v| v.first().copied())
        .map(|d| d.max(0) as f32)
}

/// `max_damage` on the unmodified state (`work`: a copy, restored after every in-place call),
/// memoized per (attacking side, attacking mon, move slot, defending mon): the same calls recur
/// (the predicted move, the threats, the actives' moves, the team matrix). A benched attacker or
/// defender is made active without the active's own state (`enter`).
struct DamageMemo {
    work: State,
    inplace: bool,
    refs: [SideReference; 2],
    memo: Vec<Option<Option<f32>>>,
}

impl DamageMemo {
    fn new(state: &State, inplace: bool, refs: [SideReference; 2]) -> DamageMemo {
        DamageMemo {
            work: state.clone(),
            inplace,
            refs,
            memo: vec![None; 2 * 6 * 4 * 6],
        }
    }

    fn damage(&mut self, att: usize, j: usize, choice: &Choice, def: usize) -> Option<f32> {
        if self.inplace {
            let saved = enter(self.work.get_side(&self.refs[att]), j);
            let r = max_damage_inplace(&mut self.work, &self.refs[att], choice, def);
            leave(self.work.get_side(&self.refs[att]), saved);
            r
        } else {
            let mut s = self.work.clone();
            enter(s.get_side(&self.refs[att]), j);
            max_damage(&s, &self.refs[att], choice, def)
        }
    }

    /// side `att`'s mon `j` with its move `slot` against the other side's mon `def`
    fn get(&mut self, att: usize, j: usize, slot: usize, choice: &Choice, def: usize) -> Option<f32> {
        let key = ((att * 6 + j) * 4 + slot) * 6 + def;
        if let Some(v) = self.memo[key] {
            return v;
        }
        let v = self.damage(att, j, choice, def);
        self.memo[key] = Some(v);
        v
    }

    /// The best max damage of side `att`'s mon `j` against the other side's mon `def` (both made
    /// active); `usable`: the moves not disabled only (the active's choice lock).
    fn best(&mut self, att: usize, j: usize, def: usize, usable: bool) -> f32 {
        let side = self.work.get_side_immutable(&self.refs[att]);
        let p = &side.pokemon.pkmn[j];
        let moves: Vec<(usize, Choice, bool)> = [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3]
            .iter()
            .enumerate()
            .map(|(k, m)| (k, m.choice.clone(), m.disabled))
            .collect();
        moves
            .into_iter()
            .filter(|(_, _, disabled)| !(usable && *disabled))
            .filter_map(|(k, c, _)| self.get(att, j, k, &c, def))
            .fold(0.0f32, f32::max)
    }
}

/// The net HP change of `p` (its side's active) at the end of a turn, heal positive: Leftovers /
/// Black Sludge, Grassy Terrain, burn / poison / toxic (Poison Heal), the weather's chip and the
/// weather abilities, Leech Seed, Salt Cure, Aqua Ring, Ingrain, Curse, a partial trap. The common
/// ones only: an estimate for the two-hit KO lines.
fn residual(state: &State, side: &Side, p: &Pokemon) -> f32 {
    let max = p.maxhp as f32;
    let guard = p.ability == Abilities::MAGICGUARD;
    let chip = |f: f32| if guard { 0.0 } else { -f * max };
    let poison_type = p.types.0 == PokemonType::POISON || p.types.1 == PokemonType::POISON;
    let mut net = 0.0;
    match p.item {
        Items::LEFTOVERS => net += max / 16.0,
        Items::BLACKSLUDGE if poison_type => net += max / 16.0,
        Items::BLACKSLUDGE => net += chip(1.0 / 8.0),
        _ => {}
    }
    if state.terrain.terrain_type == Terrain::GRASSYTERRAIN && side.active_grounded() {
        net += max / 16.0;
    }
    match p.status {
        PokemonStatus::BURN => net += chip(1.0 / 16.0),
        PokemonStatus::POISON | PokemonStatus::TOXIC if p.ability == Abilities::POISONHEAL => {
            net += max / 8.0
        }
        PokemonStatus::POISON => net += chip(1.0 / 8.0),
        PokemonStatus::TOXIC => {
            net += chip((side.side_conditions.toxic_count as f32 + 1.0).min(15.0) / 16.0)
        }
        _ => {}
    }
    let has = |t: PokemonType| p.types.0 == t || p.types.1 == t;
    match state.weather.weather_type {
        Weather::SAND
            if !(has(PokemonType::ROCK) || has(PokemonType::GROUND) || has(PokemonType::STEEL))
                && !matches!(
                    p.ability,
                    Abilities::OVERCOAT
                        | Abilities::SANDVEIL
                        | Abilities::SANDRUSH
                        | Abilities::SANDFORCE
                )
                && p.item != Items::SAFETYGOGGLES =>
        {
            net += chip(1.0 / 16.0)
        }
        Weather::RAIN | Weather::HEAVYRAIN => match p.ability {
            Abilities::RAINDISH => net += max / 16.0,
            Abilities::DRYSKIN => net += max / 8.0,
            _ => {}
        },
        Weather::SUN | Weather::HARSHSUN
            if matches!(p.ability, Abilities::DRYSKIN | Abilities::SOLARPOWER) =>
        {
            net += chip(1.0 / 8.0)
        }
        Weather::HAIL | Weather::SNOW if p.ability == Abilities::ICEBODY => net += max / 16.0,
        _ => {}
    }
    let v = &side.volatile_statuses;
    if v.contains(&PokemonVolatileStatus::LEECHSEED) {
        net += chip(1.0 / 8.0);
    }
    if v.contains(&PokemonVolatileStatus::SALTCURE) {
        net += chip(if has(PokemonType::WATER) || has(PokemonType::STEEL) { 0.25 } else { 0.125 });
    }
    if v.contains(&PokemonVolatileStatus::CURSE) {
        net += chip(0.25);
    }
    if v.contains(&PokemonVolatileStatus::PARTIALLYTRAPPED) {
        net += chip(1.0 / 8.0);
    }
    if v.contains(&PokemonVolatileStatus::AQUARING) {
        net += max / 16.0;
    }
    if v.contains(&PokemonVolatileStatus::INGRAIN) {
        net += max / 16.0;
    }
    net
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
    let (e, g, _) = featurize_extra_with(state, flip, true, false);
    (e, g)
}

/// `featurize_extra` and the v7 entity inputs ([12 * ENT_NEW]: ko2, tera, team) from one memo.
pub fn featurize_extra_full(state: &State, flip: bool) -> (Vec<f32>, Vec<f32>, Vec<f32>) {
    featurize_extra_with(state, flip, true, true)
}

/// The same with a copy of the state per damage call (poke-engine's `calculate_damage_rolls`):
/// the reference for checking `featurize_extra`.
pub fn featurize_extra_reference(state: &State, flip: bool) -> (Vec<f32>, Vec<f32>, Vec<f32>) {
    featurize_extra_with(state, flip, false, true)
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
    let saved = enter(state.get_side(&other), def_idx);
    let r = damage_inplace(state, attacker, choice.clone()).map(|d| d.max(0) as f32);
    leave(state.get_side(&other), saved);
    r
}

/// `inplace`: damage on a working copy restored after each call, else a copy per call.
fn featurize_extra_with(
    state: &State,
    flip: bool,
    inplace: bool,
    full: bool,
) -> (Vec<f32>, Vec<f32>, Vec<f32>) {
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
    let mut memo = DamageMemo::new(state, inplace, refs);
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
                .filter_map(|(k, m)| {
                    memo.get(1 - s, act[1 - s], k, &m.choice, act[s]).map(|d| (d, k))
                })
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
                    let d = memo
                        .get(1 - s, act[1 - s], k, &att_moves[k].choice, j)
                        .unwrap_or(0.0);
                    let hp = p.hp as f32;
                    e[22] = (d / hp).min(2.0);
                    e[23] = (d >= hp) as u8 as f32;
                }
                if attacker_alive {
                    // this bench mon's best move vs the opposing active (as if it were in)
                    let best = memo.best(s, j, act[1 - s], false);
                    e[24] = (best / target_hp).min(2.0);
                }
            }
            let hp = p.hp as f32;
            if attacker_alive {
                let best = att_moves
                    .iter()
                    .enumerate()
                    .filter(|(_, m)| !m.disabled)
                    .filter_map(|(k, m)| memo.get(1 - s, act[1 - s], k, &m.choice, j))
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
                if let Some(d) = memo.get(s, act[s], i, &m.choice, act[1 - s]) {
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
    let new = if full {
        v7_entities(state, &sides, act, refs, &mut memo)
    } else {
        Vec::new()
    };
    (ent, glob, new)
}

/// The v7 entity inputs (module docs): ko2, tera, team; `memo` shared with the v3 extras.
fn v7_entities(
    state: &State,
    sides: &[&Side; 2],
    act: [usize; 2],
    refs: [SideReference; 2],
    memo: &mut DamageMemo,
) -> Vec<f32> {
    let mut out = vec![0.0f32; 12 * ENT_NEW];
    let alive = |s: usize, j: usize| sides[s].pokemon.pkmn[j].hp > 0;
    let moves_of = |p: &Pokemon| -> [Choice; 4] {
        [
            p.moves.m0.choice.clone(),
            p.moves.m1.choice.clone(),
            p.moves.m2.choice.clone(),
            p.moves.m3.choice.clone(),
        ]
    };
    let both = alive(0, act[0]) && alive(1, act[1]);
    for s in 0..2 {
        let o = 1 - s;
        let me = &sides[s].pokemon.pkmn[act[s]];
        let foe = &sides[o].pokemon.pkmn[act[o]];
        let base = (s * 6 + act[s]) * ENT_NEW;
        if !both {
            continue;
        }
        // ko2 (F3a): two-hit KO lines with the target's end-of-turn HP change between the hits
        {
            // two hits KO when they cover its HP plus what it heals (less what it loses) at the
            // end of the turn between them
            let thresh = foe.hp as f32 + residual(state, sides[o], foe);
            let my_moves = moves_of(me);
            for (i, c) in my_moves.iter().enumerate() {
                if let Some(d) = memo.get(s, act[s], i, c, act[o]) {
                    let e = &mut out[base + 2 * i..base + 2 * i + 2];
                    e[0] = (2.0 * 0.85 * d >= thresh) as u8 as f32;
                    e[1] = (2.0 * d >= thresh) as u8 as f32;
                }
            }
            // the opposing active's priority moves against this one
            let psychic = state.terrain.terrain_type == Terrain::PSYCHICTERRAIN
                && sides[s].active_grounded();
            if !psychic {
                let foe_moves = [&foe.moves.m0, &foe.moves.m1, &foe.moves.m2, &foe.moves.m3];
                let mut best = 0.0f32;
                for (k, m) in foe_moves.iter().enumerate() {
                    if m.disabled || m.choice.priority <= 0 || m.choice.category == MoveCategory::Status
                    {
                        continue;
                    }
                    if let Some(d) = memo.get(o, act[o], k, &m.choice.clone(), act[s]) {
                        best = best.max(d);
                    }
                }
                let hp = me.hp as f32;
                out[base + 8] = (0.85 * best >= hp && best > 0.0) as u8 as f32;
                out[base + 9] = (best >= hp && best > 0.0) as u8 as f32;
            }
        }
        // tera (F6): this side's tera, then the other side's, on the working copy (restored)
        let t = base + ENT_KO2;
        let can = [sides[s].can_use_tera(), sides[o].can_use_tera()];
        let tera_ok = |p: &Pokemon| !p.terastallized && p.tera_type != PokemonType::TYPELESS;
        if can[0] && tera_ok(me) {
            out[t + 4 * 3 + 3 + 4 * 2 + 3] = 1.0;
            memo.work.get_side(&refs[s]).pokemon.pkmn[act[s]].terastallized = true;
            let my_moves = moves_of(me);
            for (i, c) in my_moves.iter().enumerate() {
                if let Some(d) = max_damage_inplace(&mut memo.work, &refs[s], c, act[o]) {
                    let hp = foe.hp as f32;
                    out[t + 3 * i] = (d / hp).min(2.0);
                    out[t + 3 * i + 1] = (0.85 * d >= hp) as u8 as f32;
                    out[t + 3 * i + 2] = (d >= hp) as u8 as f32;
                }
            }
            let mut best = 0.0f32;
            for (k, c) in moves_of(foe).iter().enumerate() {
                if foe_disabled(foe, k) {
                    continue;
                }
                if let Some(d) = max_damage_inplace(&mut memo.work, &refs[o], c, act[s]) {
                    best = best.max(d);
                }
            }
            let hp = me.hp as f32;
            out[t + 12] = (best / hp).min(2.0);
            out[t + 13] = (0.85 * best >= hp) as u8 as f32;
            out[t + 14] = (best >= hp) as u8 as f32;
            memo.work.get_side(&refs[s]).pokemon.pkmn[act[s]].terastallized = false;
        }
        if can[1] && tera_ok(foe) {
            out[t + 4 * 3 + 3 + 4 * 2 + 3 + 1] = 1.0;
            memo.work.get_side(&refs[o]).pokemon.pkmn[act[o]].terastallized = true;
            let u = t + 15;
            for (i, c) in moves_of(me).iter().enumerate() {
                if let Some(d) = max_damage_inplace(&mut memo.work, &refs[s], c, act[o]) {
                    let hp = foe.hp as f32;
                    out[u + 2 * i] = (d / hp).min(2.0);
                    out[u + 2 * i + 1] = (d >= hp) as u8 as f32;
                }
            }
            let mut best = 0.0f32;
            for (k, c) in moves_of(foe).iter().enumerate() {
                if foe_disabled(foe, k) {
                    continue;
                }
                if let Some(d) = max_damage_inplace(&mut memo.work, &refs[o], c, act[s]) {
                    best = best.max(d);
                }
            }
            let hp = me.hp as f32;
            out[u + 8] = (best / hp).min(2.0);
            out[u + 9] = (0.85 * best >= hp) as u8 as f32;
            out[u + 10] = (best >= hp) as u8 as f32;
            memo.work.get_side(&refs[o]).pokemon.pkmn[act[o]].terastallized = false;
        }
    }
    // team (F5): every living mon against the other side's living mons, both made active
    let mut dmg = [[[0.0f32; 6]; 6]; 2]; // [side][own mon][foe mon]: best damage / foe's HP
    for s in 0..2 {
        for j in 0..6 {
            if !alive(s, j) {
                continue;
            }
            for k in 0..6 {
                if !alive(1 - s, k) {
                    continue;
                }
                let d = memo.best(s, j, k, j == act[s]);
                dmg[s][j][k] = d / sides[1 - s].pokemon.pkmn[k].hp.max(1) as f32;
            }
        }
    }
    let faster = |s: usize, j: usize, k: usize| {
        let a = effective_speed(state, sides[s], j);
        let b = effective_speed(state, sides[1 - s], k);
        a != b && ((a > b) != state.trick_room.active)
    };
    // answers[s][j][k]: side s's mon j answers the other side's mon k
    let mut answers = [[[false; 6]; 6]; 2];
    for s in 0..2 {
        for j in 0..6 {
            for k in 0..6 {
                if !alive(s, j) || !alive(1 - s, k) {
                    continue;
                }
                let takes = dmg[1 - s][k][j];
                let deals = dmg[s][j][k];
                answers[s][j][k] = (takes < 1.0 && deals >= 0.5) || (deals >= 1.0 && faster(s, j, k));
            }
        }
    }
    for s in 0..2 {
        let o = 1 - s;
        for j in 0..6 {
            if !alive(s, j) {
                continue;
            }
            let e = &mut out[(s * 6 + j) * ENT_NEW + ENT_KO2 + ENT_TERA..(s * 6 + j + 1) * ENT_NEW];
            let foes: Vec<usize> = (0..6).filter(|&k| alive(o, k)).collect();
            let n = |f: &dyn Fn(usize) -> bool| foes.iter().filter(|&&k| f(k)).count() as f32 / 6.0;
            e[0] = n(&|k| dmg[s][j][k] >= 1.0);
            e[1] = n(&|k| dmg[o][k][j] >= 1.0);
            e[2] = n(&|k| dmg[o][k][j] < 0.5);
            e[3] = n(&|k| dmg[s][j][k] >= 1.0 && faster(s, j, k));
            // as a threat: the other side's answers to it
            let ans = (0..6).filter(|&k| answers[o][k][j]).count();
            e[4] = ans as f32 / 6.0;
            e[5] = (ans == 1) as u8 as f32;
            // as an answer: the threats it alone answers
            e[6] = foes
                .iter()
                .filter(|&&k| answers[s][j][k] && (0..6).filter(|&m| answers[s][m][k]).count() == 1)
                .count() as f32
                / 6.0;
        }
    }
    out
}

/// F2 (design TODO 特征候选): per entity, side-relative, against the other side's active, the
/// mean over the belief worlds `states` (the same player's view: its own sets fixed, the
/// opponent's sampled -- the joint posterior, not independent marginals): faster than it; its
/// best hit KOs this one (max roll); this one's best hit KOs it; this one takes under half its
/// HP from it (a switch-in); this one's priority moves KO it; and of this mon's set: a healing
/// move, a self-boosting move, a phazing / hazard- or boost-clearing move, a Choice item, a Focus
/// Sash or Sturdy (an OHKO it survives at full HP). [12 * N_POST], zeros for fainted mons.
/// Computed once at the search's root and passed down the tree in the context (a leaf is
/// evaluated in one world: no posterior there).
pub fn posterior(states: &[State], flip: bool) -> Vec<f32> {
    let mut acc = vec![0.0f32; 12 * N_POST];
    if states.is_empty() {
        return acc;
    }
    for st in states {
        for (a, x) in acc.iter_mut().zip(posterior_world(st, flip)) {
            *a += x;
        }
    }
    let n = states.len() as f32;
    acc.iter_mut().for_each(|a| *a /= n);
    acc
}

const CLEARING: [Choices; 9] = [
    Choices::HAZE,
    Choices::CLEARSMOG,
    Choices::DEFOG,
    Choices::RAPIDSPIN,
    Choices::MORTALSPIN,
    Choices::TIDYUP,
    Choices::COURTCHANGE,
    Choices::ROAR,
    Choices::WHIRLWIND,
];

fn posterior_world(state: &State, flip: bool) -> Vec<f32> {
    let mut out = vec![0.0f32; 12 * N_POST];
    let refs = [side_ref(true, flip), side_ref(false, flip)];
    let sides = [
        state.get_side_immutable(&refs[0]),
        state.get_side_immutable(&refs[1]),
    ];
    let act = [
        sides[0].active_index as usize,
        sides[1].active_index as usize,
    ];
    let mut memo = DamageMemo::new(state, true, refs);
    for s in 0..2 {
        let o = 1 - s;
        let a = act[o];
        let foe = &sides[o].pokemon.pkmn[a];
        let speed_a = effective_speed(state, sides[o], a);
        for j in 0..6 {
            let p = &sides[s].pokemon.pkmn[j];
            if p.hp <= 0 {
                continue;
            }
            let e = &mut out[(s * 6 + j) * N_POST..(s * 6 + j + 1) * N_POST];
            let moves = [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3];
            if foe.hp > 0 {
                let sp = effective_speed(state, sides[s], j);
                e[0] = (sp != speed_a && ((sp > speed_a) != state.trick_room.active)) as u8 as f32;
                let takes = memo.best(o, a, j, true) / p.hp.max(1) as f32;
                let deals = memo.best(s, j, a, j == act[s]) / foe.hp.max(1) as f32;
                e[1] = (takes >= 1.0) as u8 as f32;
                e[2] = (deals >= 1.0) as u8 as f32;
                e[3] = (takes < 0.5) as u8 as f32;
                let mut prio = 0.0f32;
                for (k, m) in moves.iter().enumerate() {
                    if m.choice.priority > 0 && m.choice.category != MoveCategory::Status {
                        if let Some(d) = memo.get(s, j, k, &m.choice.clone(), a) {
                            prio = prio.max(d);
                        }
                    }
                }
                e[4] = (prio >= foe.hp as f32 && prio > 0.0) as u8 as f32;
            }
            e[5] = moves.iter().any(|m| m.choice.flags.heal || m.choice.heal.is_some()) as u8 as f32;
            e[6] = moves.iter().any(|m| {
                m.choice.boost.as_ref().is_some_and(|b| {
                    b.target == MoveTarget::User
                        && b.boosts.attack + b.boosts.special_attack + b.boosts.speed
                            + b.boosts.defense
                            + b.boosts.special_defense
                            > 0
                })
            }) as u8 as f32;
            e[7] = moves
                .iter()
                .any(|m| CLEARING.contains(&m.id) || (m.choice.flags.drag && m.choice.category == MoveCategory::Status))
                as u8 as f32;
            e[8] = matches!(p.item, Items::CHOICEBAND | Items::CHOICESPECS | Items::CHOICESCARF)
                as u8 as f32;
            e[9] = (p.item == Items::FOCUSSASH || p.ability == Abilities::STURDY) as u8 as f32;
        }
    }
    out
}

fn foe_disabled(p: &Pokemon, k: usize) -> bool {
    [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3][k].disabled
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
            let (e1, g1, n1) = featurize_extra_full(&st, flip);
            let (e2, g2, n2) = featurize_extra_reference(&st, flip);
            assert!(e1.iter().zip(&e2).all(|(a, b)| a.to_bits() == b.to_bits()));
            assert!(g1.iter().zip(&g2).all(|(a, b)| a.to_bits() == b.to_bits()));
            assert!(n1.iter().zip(&n2).all(|(a, b)| a.to_bits() == b.to_bits()));
            // the full path's v3 part is the plain one's
            let (e3, g3) = featurize_extra(&st, flip);
            assert_eq!(e1, e3);
            assert_eq!(g1, g3);
            // the working copy is restored: featurizing twice gives the same
            assert_eq!(featurize_extra_full(&st, flip).2, n1);
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

    /// v7 entity inputs: shape, flip symmetry (every quantity is computed for both sides the
    /// same way), finite, and the team block filled for the living mons
    #[test]
    fn v7_shapes_and_flip() {
        let st = fixture();
        let (_, _, n) = featurize_extra_full(&st, false);
        let (_, _, n2) = featurize_extra_full(&st, true);
        assert_eq!(n.len(), 12 * ENT_NEW);
        assert_eq!(&n[..6 * ENT_NEW], &n2[6 * ENT_NEW..]);
        assert_eq!(&n[6 * ENT_NEW..], &n2[..6 * ENT_NEW]);
        assert!(n.iter().all(|x| x.is_finite()));
        let team = |e: usize| &n[e * ENT_NEW + ENT_KO2 + ENT_TERA..(e + 1) * ENT_NEW];
        assert!((0..12).any(|e| team(e).iter().any(|&x| x > 0.0)), "team block empty");
    }

    /// F2: averaging one world twice is the world; flip-symmetric; probabilities in [0, 1]
    #[test]
    fn posterior_shapes() {
        let st = fixture();
        let one = posterior(&[st.clone()], false);
        let two = posterior(&[st.clone(), st.clone()], false);
        assert_eq!(one.len(), 12 * N_POST);
        assert_eq!(one, two);
        let fl = posterior(&[st.clone()], true);
        assert_eq!(&one[..6 * N_POST], &fl[6 * N_POST..]);
        assert!(one.iter().all(|&x| (0.0..=1.0).contains(&x)));
        assert!(one.iter().any(|&x| x > 0.0));
    }

    /// a benched mon's matchup no longer takes the active's boosts (EXTRA_VERSION 2)
    #[test]
    fn bench_ignores_active_boosts() {
        let mut st = fixture();
        let (e0, _) = featurize_extra(&st, false);
        st.side_one.defense_boost = 6;
        st.side_one.special_defense_boost = 6;
        let (e1, _) = featurize_extra(&st, false);
        let a1 = st.side_one.active_index as usize;
        for j in (0..6).filter(|&j| j != a1) {
            // the threat from the opposing active on benched mon j: unchanged
            assert_eq!(e0[j * ENT_EXTRA + 1], e1[j * ENT_EXTRA + 1], "bench {j}");
            assert_eq!(e0[j * ENT_EXTRA + 22], e1[j * ENT_EXTRA + 22], "bench {j}");
        }
    }
}
