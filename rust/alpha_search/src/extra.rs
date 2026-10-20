//! v3 network inputs computed from a poke-engine state (design D13, network v3 first batch), next
//! to the v1 / v2 features (`features.rs`, unchanged so the v1 network keeps working):
//!
//! * static move table (`move_table`): per move id (`Choices`), its type, category, base power,
//!   accuracy, priority, flags and effects from poke-engine's move data — a fixed lookup the model
//!   projects onto the move embedding (rare moves get their properties without many samples);
//! * per entity (`ENT_EXTRA`, side-relative like `featurize_view`):
//!   - speed against the opposing active: log2(effective speed / the opposing active's) / 2,
//!     clipped to +-1.5 (the engine's `get_effective_speed`; boosts and volatiles only for the
//!     active);
//!   - the threat from the opposing active: its best move's max damage / this mon's HP (clipped
//!     at 2), and whether that KOs for sure (min roll = 0.85 x max, min hits) / possibly (max
//!     roll, max hits; a Focus Sash / Sturdy at full HP holds a single hit);
//!   - actives only: each of its 4 moves against the opposing active: max damage / HP, KO for sure,
//!     KO possible, type effectiveness log2 / 2 (immune: -1.5);
//!   - benched only: the HP it loses switching in (the engine's switch-in: Stealth Rock by its
//!     current types, Spikes when grounded, Heavy-Duty Boots, ...) as a fraction of max HP, and
//!     whether it faints on entry;
//!   - benched only (v4, switch-in counters): the damage it takes from the opposing active's
//!     predicted move (its strongest against this side's active) / HP and whether that KOs, and
//!     its own best move's damage against the opposing active / that one's HP;
//! * global (`GLOBAL_EXTRA`): per side (own, opponent) the living mons / 6, their summed HP
//!   fraction / 6, tera used, the last used move (none-or-switch / slot 0-3, a Choice lock); then
//!   who moves first between the actives (+1 own, -1 opponent, 0 tie; trick room counted) and the
//!   log2 speed ratio of the actives / 2; weather and terrain turns left / 8.
//!
//! Damage uses poke-engine's `calculate_damage_rolls` (the full Gen 9 damage calculation in the
//! world's sampled sets; abilities and items included, the defender's move ignored) per hit, a
//! multi-hit move's total by the engine's hit counts (`hits`). Game rules come from the engine
//! (speed, priority, a switch-in, the end of the turn), not copies of them (`EXTRA_VERSION` 3).
//!
//! A benched mon in a hypothetical matchup is made its side's active with none of the active's
//! own state (boosts, volatiles, substitute: side-level in the engine); before `EXTRA_VERSION` 2
//! it took the active's (design TODO P0, 2026-10-19).
//!
//! v7 entity inputs (`featurize_extra_full`, [12, ENT_NEW], side-relative; design TODO 特征候选,
//! 2026-10-19), from the same damage memo:
//! * `ko2` (F3a, actives): each of its moves against the opposing active: KO within two hits for
//!   sure / possibly, hit by hit (the second at the HP the first left: Super Fang; the target's
//!   end-of-turn HP change between them, the engine's; a Focus Sash / Sturdy; one use of Final
//!   Gambit / Fake Out / First Impression; the target does not act); then the opposing active's priority moves against it: KO for sure / possibly (none on
//!   a grounded target in Psychic Terrain);
//! * `tera` (F6, actives): if its side can still terastallize, its moves terastallized against
//!   the opposing active (max damage / HP, KO for sure, possibly) and the opposing active's best
//!   hit on it terastallized; if the other side can, its moves against the opposing active
//!   terastallized (damage / HP, KO possible) and that one's best hit on it then; the two flags.
//!   The opponent's tera type is the world's sample: across worlds, the posterior;
//! * `team` (F5, every living mon, against the other side's living mons, each made active; counts
//!   / 6): how many it KOs with one hit (max roll), how many KO it; then by an exchange of hits
//!   (`fight`: each with its one strongest move, nobody switches / recovers / boosts /
//!   terastallizes, hit by hit, the end of each turn, at most ROUNDS rounds after the entry), the
//!   foes it answers as a switch-in (the hazards, one hit taken first) reliably (its min rolls,
//!   the foe's max, a speed tie to the foe) and possibly, head-to-head reliably, as a revenge kill
//!   (in free after a faint, the hazards; its first hit KOs before the foe acts) reliably, and
//!   against how many the reliable switch-in exchange is unresolved within the rounds; as a
//!   threat, how many of the other side's mons answer it reliably as a switch-in, against how many
//!   that is Unknown, how many revenge-kill it reliably; as an answer, the threats it is the only
//!   confirmed answer to as a switch-in / as a revenge kill.

use poke_engine::choices::{Choice, Choices, Effect, MoveCategory, MoveTarget, MultiHitMove, MOVES};
use poke_engine::engine::choice_effects::{charge_choice_to_volatile, modify_choice};
use poke_engine::engine::abilities::Abilities;
use poke_engine::engine::damage_calc::{
    calculate_damage, type_effectiveness_modifier, DamageRolls,
};
use poke_engine::engine::generate_instructions::{
    add_end_of_turn_instructions, before_move, calculate_damage_rolls,
    generate_instructions_from_switch, get_effective_speed, hit_crit_chance, hits_substitute,
    modify_choice_priority,
};
use poke_engine::engine::items::{item_ignored, Items};
use poke_engine::engine::state::Terrain;
use poke_engine::engine::state::PokemonVolatileStatus;
use poke_engine::instruction::{Instruction, StateInstructions};
use poke_engine::state::{
    LastUsedMove, Pokemon, PokemonIndex, PokemonMoveIndex,
    PokemonType, Side, SideReference, State,
};

/// 2: benched mons made active without the active's boosts / volatiles / substitute; 3
/// (2026-10-20, the review of the v7 inputs, doc/engine-diff.md L230): the engine's own speed,
/// priority, switch-in (hazards) and end of turn instead of copies of them; a multi-hit move's
/// hits; Endeavor / Final Gambit's immunities; Focus Sash / Sturdy in the KO flags; ko2 hit by
/// hit; team's answers by an exchange of hits (12 columns, were 7); a sure crit's damage
pub const EXTRA_VERSION: usize = 3;
pub const MOVE_FEAT: usize = 20 + 3 + 3 + 16 + 3 + 1 + 2 + 4 + 1;
pub const ENT_KO2: usize = 4 * 2 + 2;
pub const ENT_TERA: usize = 4 * 3 + 3 + 4 * 2 + 3 + 2;
pub const ENT_TEAM: usize = 12;
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

/// The effective speed of side `r`'s mon `idx`: the engine's own (`get_effective_speed`: weather
/// and its suppression, abilities, items, Magic Room, paralysis, tailwind, ...), a benched mon
/// made the active as a switch-in (`enter`: no boosts / volatiles) on `work` (restored). Before
/// `EXTRA_VERSION` 3 a copy of the engine's function, behind its later fixes (Slush Rush in
/// snow, Power items, Unburden, Cloud Nine; doc/engine-diff.md L230).
fn speed(work: &mut State, r: &SideReference, idx: usize) -> f32 {
    let saved = enter(work.get_side(r), idx);
    let v = get_effective_speed(work, r) as f32;
    leave(work.get_side(r), saved);
    v.max(1.0)
}

/// Runs `f` (engine instructions applied to `work`, returned) and undoes them (the engine's
/// `reverse_instructions`: no copy of the state, ~25 a state before, the features' main cost);
/// None when the engine panics, `work` reset to `orig` then.
fn undone<T>(work: &mut State, orig: &State, f: impl FnOnce(&mut State, &mut StateInstructions) -> T) -> Option<T> {
    let mut ins = StateInstructions::default();
    let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f(work, &mut ins)));
    match r {
        Ok(v) => {
            work.reverse_instructions(&ins.instruction_list);
            Some(v)
        }
        Err(_) => {
            *work = orig.clone();
            None
        }
    }
}

/// Side `r`'s benched mon `idx` switching in, by the engine itself on `work` (undone; `orig`:
/// `work` as it is, for a panic): its HP after the switch-in (entry hazards by its current types,
/// Heavy-Duty Boots, an Air Balloon, ...); its HP now if the engine panics on the state.
fn entry_hp(work: &mut State, orig: &State, r: &SideReference, idx: usize) -> i16 {
    let r = *r;
    let now = work.get_side_immutable(&r).pokemon.pkmn[idx].hp;
    undone(work, orig, |st, ins| {
        generate_instructions_from_switch(st, PokemonIndex::deserialize(&idx.to_string()), r, ins);
        st.get_side_immutable(&r).pokemon.pkmn[idx].hp
    })
    .unwrap_or(now)
}

/// One end of the turn's effect on a side's active: (its heal, its damage), each measured where
/// no HP cuts it off -- the exchange adds them at its own HP (heal first, then the damage)
type Hd = (f32, f32);

/// The HP-threshold berries (Sitrus, the 1/3 ones, the pinch stat ones, Custap): taken off while
/// the ends of the turns are measured (at a low HP they would go off there; the exchange follows
/// the healing ones itself, `berry_heal`)
fn hp_berry(i: Items) -> bool {
    matches!(
        i,
        Items::SITRUSBERRY
            | Items::FIGYBERRY
            | Items::WIKIBERRY
            | Items::MAGOBERRY
            | Items::AGUAVBERRY
            | Items::IAPAPABERRY
            | Items::LIECHIBERRY
            | Items::GANLONBERRY
            | Items::SALACBERRY
            | Items::PETAYABERRY
            | Items::APICOTBERRY
            | Items::STARFBERRY
            | Items::LANSATBERRY
            | Items::MICLEBERRY
            | Items::CUSTAPBERRY
    )
}

/// The ends of `n` turns in a row (at most `EOTS`: an exchange's entry, then its rounds), by the
/// engine (`add_end_of_turn_instructions`) on `work`, the turns' state carried from one to the
/// next -- the toxic counter, the weather's / terrain's turns, Wish, Future Sight, a binding's
/// turns -- and all undone after (`orig`: `work` as it is, for a panic: zeros then). Per turn
/// and side's active ([turn][refs[0], refs[1]]): its heal and damage measured at 1/4 of its max
/// HP (if one goes down there: the heal at 1/2, the damage at full HP) -- no HP cuts either off (before: the net
/// change at 3/4, a Wish's half cut to a quarter; one turn's change repeated). Zeros when an
/// active is down.
fn eot_hd(work: &mut State, orig: &State, refs: &[SideReference; 2], n: usize) -> [[Hd; 2]; EOTS] {
    let mut out = [[(0.0f32, 0.0f32); 2]; EOTS];
    if refs.iter().any(|r| work.get_side_immutable(r).get_active_immutable().hp <= 0) {
        return out;
    }
    let refs = *refs;
    let hp0 = refs.map(|r| work.get_side_immutable(&r).get_active_immutable().hp);
    let item0 = refs.map(|r| work.get_side_immutable(&r).get_active_immutable().item);
    let max = refs.map(|r| work.get_side_immutable(&r).get_active_immutable().maxhp.max(1));
    for i in 0..2 {
        if hp_berry(item0[i]) {
            work.get_side(&refs[i]).get_active().item = Items::NONE;
        }
    }
    let sum = |ins: &StateInstructions, r: &SideReference| {
        let (mut h, mut d) = (0.0f32, 0.0f32);
        for x in &ins.instruction_list {
            match x {
                Instruction::Heal(v) if v.side_ref == *r => {
                    if v.heal_amount >= 0 {
                        h += v.heal_amount as f32
                    } else {
                        d -= v.heal_amount as f32
                    }
                }
                Instruction::Damage(v) if v.side_ref == *r => d += v.damage_amount as f32,
                _ => {}
            }
        }
        (h, d)
    };
    let set_hp = |work: &mut State, f: &dyn Fn(i16) -> i16| {
        for i in 0..2 {
            work.get_side(&refs[i]).get_active().hp = f(max[i]).max(1);
        }
    };
    let mut kept: Vec<StateInstructions> = Vec::with_capacity(n);
    // an end of the turn that changed nothing but HP: the next starts from the same state (its
    // HP set again), the same then -- the rest copied, not run
    let hp_only = |ins: &StateInstructions| {
        ins.instruction_list.iter().all(|x| matches!(x, Instruction::Heal(_) | Instruction::Damage(_)))
    };
    let ok = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        for t in 0..n.min(EOTS) {
            if t > 0 && kept.last().is_some_and(hp_only) {
                out[t] = out[t - 1];
                continue;
            }
            let row = &mut out[t];
            // at 1/4 of the max HP: nothing cut off unless one goes down there (a heal over 3/4
            // aside) -- then the heal at 1/2, the damage at full HP
            set_hp(work, &|m| m / 4);
            let mut a = StateInstructions::default();
            add_end_of_turn_instructions(work, &mut a, &SideReference::SideOne);
            if refs.iter().all(|r| work.get_side_immutable(r).get_active_immutable().hp > 0) {
                *row = [0, 1].map(|i| sum(&a, &refs[i]));
                kept.push(a);
                continue;
            }
            work.reverse_instructions(&a.instruction_list);
            set_hp(work, &|m| m / 2);
            let mut a = StateInstructions::default();
            add_end_of_turn_instructions(work, &mut a, &SideReference::SideOne);
            let heal = [0, 1].map(|i| sum(&a, &refs[i]).0);
            work.reverse_instructions(&a.instruction_list);
            set_hp(work, &|m| m);
            let mut b = StateInstructions::default();
            add_end_of_turn_instructions(work, &mut b, &SideReference::SideOne);
            *row = [0, 1].map(|i| (heal[i], sum(&b, &refs[i]).1));
            kept.push(b);
        }
    }))
    .is_ok();
    if !ok {
        *work = orig.clone();
        return [[(0.0, 0.0); 2]; EOTS];
    }
    for b in kept.iter().rev() {
        work.reverse_instructions(&b.instruction_list);
    }
    for i in 0..2 {
        let p = work.get_side(&refs[i]).get_active();
        p.hp = hp0[i];
        p.item = item0[i];
    }
    out
}

/// One end of the turn (`eot_hd`)
fn eot_on(work: &mut State, orig: &State, refs: &[SideReference; 2]) -> [Hd; 2] {
    eot_hd(work, orig, refs, 1)[0]
}

/// `hp` after an end of the turn's (heal, damage) (`eot_hd`): the heal first, cut at `max`
fn after_eot(hp: f32, max: f32, hd: Hd) -> f32 {
    (hp + hd.0).min(max) - hd.1
}

/// `eot_on` on a copy of `state`
fn eot_delta(state: &State, refs: &[SideReference; 2]) -> [Hd; 2] {
    let mut st = state.clone();
    eot_on(&mut st, state, refs)
}

/// What of a foe can change a mon's end of the turn (with the foe as the other side's active):
/// a weather suppressor (Cloud Nine, Air Lock), Neutralizing Gas, Bad Dreams; being the other
/// side's actual active with a Leech Seed on it (it heals this side's active; `seeded`). The ends of
/// the turns are cached by it (before: by the slot, the j-th of each side in together -- the
/// order of the teams changed an answer)
fn foe_context(p: &Pokemon, seeded: bool) -> (Option<Abilities>, bool) {
    let a = matches!(
        p.ability,
        Abilities::CLOUDNINE | Abilities::AIRLOCK | Abilities::NEUTRALIZINGGAS | Abilities::BADDREAMS
    )
    .then_some(p.ability);
    (a, seeded)
}

fn log_ratio(a: f32, b: f32) -> f32 {
    ((a / b).log2() / 2.0).clamp(-1.5, 1.5)
}

/// A benched mon made its side's active for a hypothetical matchup: the active's own state is
/// saved and cleared (its boosts, volatiles and substitute are side-level in the engine), and
/// restored by `leave`. None when `j` is the active already.
#[derive(Clone)]
struct Saved {
    idx: PokemonIndex,
    boosts: [i8; 7],
    vol: u128,
    sub: i16,
    toxic: i8,
}

/// `j` made the side's active as a switch-in (none of the previous active's own state): the
/// helper of `enter`, for callers outside this module (lib.rs set_damage_rolls)
pub fn switch_in(side: &mut Side, j: usize) {
    enter(side, j);
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
        toxic: side.side_conditions.toxic_count,
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
    // (a switch-in's toxic counter starts again)
    side.side_conditions.toxic_count = 0;
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
        side.side_conditions.toxic_count = v.toxic;
    }
}

/// A move's hits (min, max), no miss assumed: the engine's multi-hit kinds (`Choice::multi_hit`;
/// 2-5 hits: 2 / 5, Skill Link 5, Loaded Dice 4-5; Population Bomb 10, Loaded Dice 4-10, as the
/// engine's L58). Before `EXTRA_VERSION` 3 one hit (Scale Shot's 2-5 counted as 1).
fn hits(c: &Choice, att: &Pokemon) -> (f32, f32) {
    match c.multi_hit() {
        MultiHitMove::None => (1.0, 1.0),
        MultiHitMove::DoubleHit => (2.0, 2.0),
        MultiHitMove::TripleHit => (3.0, 3.0),
        // Triple Axel / Triple Kick: three hits at 1x, 2x, 3x the first's power (20 / 40 / 60;
        // 10 / 20 / 30), in hits of the data's power (the engine's: 40, their mean -- 3 hits)
        MultiHitMove::TripleAxel => {
            let first = if c.move_id == Choices::TRIPLEAXEL { 20.0 } else { 10.0 };
            let data = MOVES.get(&c.move_id).map_or(first, |m| m.base_power).max(1.0);
            let n = 6.0 * first / data;
            (n, n)
        }
        MultiHitMove::TwoToFiveHits if att.ability == Abilities::SKILLLINK => (5.0, 5.0),
        MultiHitMove::TwoToFiveHits if att.item == Items::LOADEDDICE => (4.0, 5.0),
        MultiHitMove::TwoToFiveHits => (2.0, 5.0),
        MultiHitMove::PopulationBomb if att.ability == Abilities::SKILLLINK => (10.0, 10.0),
        MultiHitMove::PopulationBomb if att.item == Items::LOADEDDICE => (4.0, 10.0),
        MultiHitMove::PopulationBomb => (10.0, 10.0),
    }
}

/// Damage without the 85-100% roll: the fixed and the HP-based moves
fn unrolled(c: &Choice) -> bool {
    matches!(
        c.move_id,
        Choices::SEISMICTOSS
            | Choices::NIGHTSHADE
            | Choices::SUPERFANG
            | Choices::NATURESMADNESS
            | Choices::RUINATION
            | Choices::ENDEAVOR
            | Choices::FINALGAMBIT
    )
}

/// The damage range of a move (min roll x min hits, max roll x max hits; the min roll 0.85 x the
/// max) from one hit's max damage `d`
fn range(c: &Choice, att: &Pokemon, d: f32) -> (f32, f32) {
    let (lo, hi) = hits(c, att);
    ((if unrolled(c) { d } else { 0.85 * d }) * lo, d * hi)
}

/// Whether a hit of `c` that would knock `def` out at full HP leaves it 1 HP instead (a Focus
/// Sash, not under Magic Room; Sturdy, not through a Mold Breaker or an ability-ignoring move;
/// a single-hit move: a multi-hit one's later hits go through), as the engine's damage step
/// (L17 / L211 / L226)
fn holds_at_full(state: &State, att: &Pokemon, c: &Choice, def: &Pokemon) -> bool {
    if hits(c, att).1 > 1.0 {
        return false;
    }
    let ignored = (matches!(att.ability, Abilities::MOLDBREAKER | Abilities::TERAVOLT | Abilities::TURBOBLAZE)
        || matches!(c.move_id, Choices::SUNSTEELSTRIKE | Choices::MOONGEISTBEAM | Choices::PHOTONGEYSER))
        && def.item != Items::ABILITYSHIELD;
    (def.ability == Abilities::STURDY && !ignored) || (def.item == Items::FOCUSSASH && !item_ignored(state))
}

/// `hp` after a hit of `d` (`hold`: `holds_at_full`)
fn take(hp: f32, max: f32, d: f32, hold: bool) -> f32 {
    if hold && hp >= max && d >= hp {
        1.0
    } else {
        hp - d
    }
}

/// Whether a use of `c` by side `r`'s active deals its damage this turn (the damage columns show
/// it either way): not Future Sight / Doom Desire (two turns later), not a charging turn (the
/// engine's `modify_choice`: Solar Beam / Blade in the sun, Electro Shot in the rain hit at once;
/// a Power Herb, when `herb`; charged already), Fake Out / First Impression on its first turn
/// in only (its side's last move a switch)
fn lands_now(state: &State, r: &SideReference, c: &Choice, herb: bool) -> bool {
    let side = state.get_side_immutable(r);
    match c.move_id {
        Choices::FUTURESIGHT | Choices::DOOMDESIRE => return false,
        Choices::FAKEOUT | Choices::FIRSTIMPRESSION => {
            return matches!(side.last_used_move, LastUsedMove::Switch(_))
        }
        _ => {}
    }
    if !c.flags.charge || side.volatile_statuses.contains(&charge_choice_to_volatile(&c.move_id)) {
        return true;
    }
    let mut m = c.clone();
    modify_choice(state, &mut m, &Choice::default(), r);
    !m.flags.charge
        || (herb && side.get_active_immutable().item == Items::POWERHERB && c.move_id != Choices::SKYDROP)
}

/// Whether a Knock Off on `def` takes its item (its 1.5x power then, none after): an item it can
/// lose (the engine's `item_is_permanent`)
fn knocks_item(c: &Choice, def: &Pokemon) -> bool {
    c.move_id == Choices::KNOCKOFF && def.item != Items::NONE && !def.item_is_permanent()
}

/// The resist berries (eaten by the first super-effective hit: halved, the later ones not)
fn resist_berry(i: Items) -> bool {
    matches!(
        i,
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

/// Whether a hit of `c` (reaching the mon) costs `def` its item: a Knock Off's, a popped Air
/// Balloon, a resist berry (eaten on a super-effective hit; a hit not super effective leaves it,
/// but then none of the same move's is either: the same damage)
fn loses_item(state: &State, c: &Choice, def: &Pokemon) -> bool {
    knocks_item(c, def)
        || (!item_ignored(state) && (def.item == Items::AIRBALLOON || resist_berry(def.item)))
}

/// A HP-restoring berry's heal on `p` at `hp` (Sitrus: 1/4 at half or less; Figy / Wiki / Mago /
/// Aguav / Iapapa: 1/3 at a quarter or less), once; none under Unnerve / As One (`nervous`) or
/// Magic Room
fn berry_heal(state: &State, p: &Pokemon, hp: f32, nervous: bool) -> f32 {
    if hp <= 0.0 || nervous || item_ignored(state) {
        return 0.0;
    }
    let max = p.maxhp as f32;
    match p.item {
        Items::SITRUSBERRY if hp <= max / 2.0 => (max / 4.0).floor(),
        Items::FIGYBERRY | Items::WIKIBERRY | Items::MAGOBERRY | Items::AGUAVBERRY | Items::IAPAPABERRY
            if hp <= max / 4.0 =>
        {
            (max / 3.0).floor()
        }
        _ => 0.0,
    }
}

/// Whether `p`'s foe stops berries (Unnerve, As One)
fn unnerves(p: &Pokemon) -> bool {
    matches!(p.ability, Abilities::UNNERVE | Abilities::ASONEGLASTRIER | Abilities::ASONESPECTRIER)
}

/// The Substitute HP in the way of `c` used by side `r`'s active on the other side's active (0:
/// none, or the move goes through it: the engine's `hits_substitute`)
fn sub_in_way(state: &State, r: &SideReference, c: &Choice) -> f32 {
    if hits_substitute(state, r, c) {
        state.get_side_immutable(&r.get_other_side()).substitute_health.max(0) as f32
    } else {
        0.0
    }
}

/// A use of `d` in `n` equal hits on a Substitute of `sub` HP: (the damage to the mon behind it,
/// the Substitute left). Hit by hit: the one that breaks it loses its excess (the engine's), the
/// later ones hit the mon; before, a multi-hit move's whole excess went through
fn through_sub(d: f32, sub: f32, n: f32) -> (f32, f32) {
    if sub <= 0.0 {
        return (d, 0.0);
    }
    if d < sub {
        return (0.0, sub - d);
    }
    let n = n.round().max(1.0);
    let per = d / n;
    // the hits it takes to break it
    let k = (sub / per).ceil().max(1.0);
    if k >= n {
        (0.0, 0.0)
    } else {
        ((n - k) * per, 0.0)
    }
}

/// Whether a use of `c` dealing `d` in `n` hits knocks `def` out (at its HP now; `sub`: a
/// Substitute in the way)
#[allow(clippy::too_many_arguments)]
fn kos(state: &State, att: &Pokemon, c: &Choice, def: &Pokemon, d: f32, sub: f32, n: f32) -> bool {
    let (d, _) = through_sub(d, sub, n);
    d > 0.0 && take(def.hp as f32, def.maxhp as f32, d, holds_at_full(state, att, c, def)) <= 0.0
}

/// The damage range of `choice` by the attacker side's active on the defender side's mon
/// `def_idx` (made active in a copy of the state when it is benched); None for a status move /
/// no damage.
fn max_damage(
    state: &State,
    attacker: &SideReference,
    choice: &Choice,
    def_idx: usize,
) -> Option<(f32, f32)> {
    if choice.move_id == Choices::NONE || choice.category == MoveCategory::Status {
        return None;
    }
    let mut s = state.clone();
    enter(s.get_side(&attacker.get_other_side()), def_idx);
    let att = s.get_side_immutable(attacker).get_active_immutable().clone();
    // (a sure crit's damage, as damage_inplace)
    let k = (hit_crit_chance(&s, attacker, choice) >= 1.0) as usize;
    calculate_damage_rolls(s, attacker, choice.clone(), &Choice::default())
        .and_then(|v| v.get(k.min(v.len() - 1)).copied())
        .map(|d| range(choice, &att, d.max(0) as f32))
}

/// `max_damage` on the unmodified state (`work`: a copy, restored after every in-place call),
/// memoized per (attacking side, attacking mon, move slot, defending mon): the same calls recur
/// (the predicted move, the threats, the actives' moves, the team matrix). A benched attacker or
/// defender is made active without the active's own state (`enter`).
struct DamageMemo {
    work: State,
    inplace: bool,
    refs: [SideReference; 2],
    memo: Vec<Option<Option<(f32, f32)>>>,
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

    fn damage(&mut self, att: usize, j: usize, choice: &Choice, def: usize) -> Option<(f32, f32)> {
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
    fn get(&mut self, att: usize, j: usize, slot: usize, choice: &Choice, def: usize) -> Option<(f32, f32)> {
        let key = ((att * 6 + j) * 4 + slot) * 6 + def;
        if let Some(v) = self.memo[key] {
            return v;
        }
        let v = self.damage(att, j, choice, def);
        self.memo[key] = Some(v);
        v
    }

    /// The move of side `att`'s mon `j` with the highest max damage against the other side's mon
    /// `def` (both made active): (slot, its range); `usable`: the moves not disabled only (the
    /// active's choice lock); `repeat`: none usable on the first turn only (Fake Out, First
    /// Impression: an exchange of hits)
    fn best_move(&mut self, att: usize, j: usize, def: usize, usable: bool, repeat: bool) -> Option<(usize, (f32, f32))> {
        let mut best: Option<(usize, (f32, f32))> = None;
        for k in 0..4 {
            // (the move's data cloned only for a damage not in the memo yet)
            let key = ((att * 6 + j) * 4 + k) * 6 + def;
            let (disabled, skip) = {
                let m = &self.work.get_side_immutable(&self.refs[att]).pokemon.pkmn[j].moves[&SLOTS[k]];
                let c = &m.choice;
                // in a repeated exchange: none landing on its first turn only or a later turn
                // (with this mon made active; a Power Herb used up)
                let skip = repeat
                    && (matches!(
                        c.move_id,
                        // (and the moves returning the damage taken: their damage is the turn's)
                        Choices::FAKEOUT
                            | Choices::FIRSTIMPRESSION
                            | Choices::COUNTER
                            | Choices::MIRRORCOAT
                            | Choices::METALBURST
                            | Choices::COMEUPPANCE
                            | Choices::BIDE
                    )
                        || ((c.flags.charge || matches!(c.move_id, Choices::FUTURESIGHT | Choices::DOOMDESIRE)) && {
                            let mut st = self.work.clone();
                            enter(st.get_side(&self.refs[att]), j);
                            !lands_now(&st, &self.refs[att], c, false)
                        }));
                (m.disabled, skip)
            };
            if (usable && disabled) || skip {
                continue;
            }
            let r = match self.memo[key] {
                Some(v) => v,
                None => {
                    let c = self.work.get_side_immutable(&self.refs[att]).pokemon.pkmn[j].moves[&SLOTS[k]]
                        .choice
                        .clone();
                    self.get(att, j, k, &c, def)
                }
            };
            if let Some(r) = r {
                if best.is_none_or(|b| r.1 > b.1 .1) {
                    best = Some((k, r));
                }
            }
        }
        best
    }

    /// The best max damage of side `att`'s mon `j` against the other side's mon `def` (both made
    /// active): its range, (0, 0) if none; `usable` as `best_move`.
    fn best(&mut self, att: usize, j: usize, def: usize, usable: bool) -> (f32, f32) {
        self.best_move(att, j, def, usable, false).map_or((0.0, 0.0), |(_, r)| r)
    }
}

/// Moves whose damage depends on the HPs (the user's or the target's), abilities that change the
/// damage with them: an exchange of hits computes these per hit at the HPs then (`hit`)
fn hp_based(c: &Choice, att: &Pokemon, def: &Pokemon) -> bool {
    matches!(
        c.move_id,
        Choices::SUPERFANG
            | Choices::NATURESMADNESS
            | Choices::RUINATION
            | Choices::ENDEAVOR
            | Choices::FINALGAMBIT
            | Choices::ERUPTION
            | Choices::WATERSPOUT
            | Choices::DRAGONENERGY
            | Choices::REVERSAL
            | Choices::FLAIL
            | Choices::CRUSHGRIP
            | Choices::WRINGOUT
            | Choices::HARDPRESS
    ) || matches!(def.ability, Abilities::MULTISCALE | Abilities::SHADOWSHIELD | Abilities::TERASHELL)
        || matches!(
            att.ability,
            Abilities::BLAZE | Abilities::TORRENT | Abilities::OVERGROW | Abilities::SWARM | Abilities::DEFEATIST
        )
}

/// Stat stage changes in an exchange of hits ([Atk, Def, SpA, SpD]: a move's own drops / raises)
type Stages = [i8; 4];

/// Side `att`'s mon `j` hitting the other side's mon `k` with its move `slot` (`c`) at the HPs
/// `hp_j` / `hp_k`, each with the stat stage changes `sj` / `sk` on top of its own: the damage
/// range. HP-based damage (`hp_based`) or changed stages by the engine then (both made active on
/// `work`, restored), the rest from the memo.
#[allow(clippy::too_many_arguments)]
fn hit(
    memo: &mut DamageMemo,
    att: usize,
    j: usize,
    slot: usize,
    c: &Choice,
    k: usize,
    hp_j: f32,
    hp_k: f32,
    sj: Stages,
    sk: Stages,
    off: (bool, bool),
) -> Option<(f32, f32)> {
    let (ra, rd) = (memo.refs[att], memo.refs[1 - att]);
    let (a_hp, d_hp, a_item, d_item, based) = {
        let a = &memo.work.get_side_immutable(&ra).pokemon.pkmn[j];
        let d = &memo.work.get_side_immutable(&rd).pokemon.pkmn[k];
        (a.hp, d.hp, a.item, d.item, hp_based(c, a, d))
    };
    if !based && sj == [0; 4] && sk == [0; 4] && !off.0 && !off.1 {
        return memo.get(att, j, slot, c, k);
    }
    let saved_a = enter(memo.work.get_side(&ra), j);
    let saved_d = enter(memo.work.get_side(&rd), k);
    let shift = |side: &mut Side, st: Stages, sign: i8| {
        for (b, x) in [
            &mut side.attack_boost,
            &mut side.defense_boost,
            &mut side.special_attack_boost,
            &mut side.special_defense_boost,
        ]
        .into_iter()
        .zip(st)
        {
            *b = (*b + sign * x).clamp(-6, 6);
        }
    };
    // (the shifted stages clamped: undone exactly only from inside -6..6; `before` restores them)
    let before = |side: &Side| {
        [side.attack_boost, side.defense_boost, side.special_attack_boost, side.special_defense_boost]
    };
    let (ba, bd) = (before(memo.work.get_side_immutable(&ra)), before(memo.work.get_side_immutable(&rd)));
    shift(memo.work.get_side(&ra), sj, 1);
    shift(memo.work.get_side(&rd), sk, 1);
    memo.work.get_side(&ra).pokemon.pkmn[j].hp = (hp_j.round() as i16).max(1);
    memo.work.get_side(&rd).pokemon.pkmn[k].hp = (hp_k.round() as i16).max(1);
    // (an item lost in the exchange: a Knock Off's -- its 1.5x then gone too --, a popped Air
    // Balloon, a resist berry eaten)
    if off.0 {
        memo.work.get_side(&ra).pokemon.pkmn[j].item = Items::NONE;
    }
    if off.1 {
        memo.work.get_side(&rd).pokemon.pkmn[k].item = Items::NONE;
    }
    let r = max_damage_inplace(&mut memo.work, &ra, c, k);
    memo.work.get_side(&ra).pokemon.pkmn[j].hp = a_hp;
    memo.work.get_side(&rd).pokemon.pkmn[k].hp = d_hp;
    memo.work.get_side(&ra).pokemon.pkmn[j].item = a_item;
    memo.work.get_side(&rd).pokemon.pkmn[k].item = d_item;
    let restore = |side: &mut Side, b: [i8; 4]| {
        [side.attack_boost, side.defense_boost, side.special_attack_boost, side.special_defense_boost] = b;
    };
    restore(memo.work.get_side(&ra), ba);
    restore(memo.work.get_side(&rd), bd);
    leave(memo.work.get_side(&rd), saved_d);
    leave(memo.work.get_side(&ra), saved_a);
    r
}

/// The move slots by number
const SLOTS: [PokemonMoveIndex; 4] =
    [PokemonMoveIndex::M0, PokemonMoveIndex::M1, PokemonMoveIndex::M2, PokemonMoveIndex::M3];

/// What a hit does besides its damage (`after_hit`)
#[derive(Clone, Copy, Debug, PartialEq, Default)]
struct HitEffect {
    /// the user's HP change
    hp: f32,
    /// the user's stat stage changes
    user: Stages,
    /// the target's
    target: Stages,
    /// a volatile on the target that takes HP at the end of the turn (Salt Cure, a binding move)
    afflict: Option<PokemonVolatileStatus>,
}

/// A stage change as `p` takes it: Contrary reverses it, Simple doubles it
fn staged(p: &Pokemon, st: Stages) -> Stages {
    match p.ability {
        Abilities::CONTRARY => st.map(|x| -x),
        Abilities::SIMPLE => st.map(|x| (2 * x).clamp(-6, 6)),
        _ => st,
    }
}

/// What a hit of `c` dealing `dealt` to `def` does besides the damage, from the engine's move data
/// (no chance assumed: a 100% secondary happens, a lesser one not): to its user `att` -- recoil
/// (not Rock Head / Magic Guard), drain, Life Orb (not Magic Guard / Sheer Force on a move with
/// secondaries / Magic Room), Rough Skin / Iron Barbs and a Rocky Helmet on contact (not
/// Protective Pads / Magic Guard), its own stage changes (Close Combat, Draco Meteor, Torch
/// Song, ...; Contrary / Simple); to the target: a 100% secondary's stage changes (Snarl,
/// Spirit Break, ...; not through Covert Cloak / Shield Dust, no drop through Clear Body / White
/// Smoke / Full Metal Body; none with Sheer Force) and an end-of-turn volatile (Salt Cure, Magma
/// Storm, ...)
fn after_hit(state: &State, att: &Pokemon, c: &Choice, def: &Pokemon, dealt: f32) -> HitEffect {
    let mut e = HitEffect::default();
    if dealt <= 0.0 {
        return e;
    }
    let max = att.maxhp as f32;
    let guard = att.ability == Abilities::MAGICGUARD;
    let items = !item_ignored(state);
    let sheer = att.ability == Abilities::SHEERFORCE && c.secondaries.is_some();
    if let Some(f) = c.recoil {
        if !guard && att.ability != Abilities::ROCKHEAD {
            e.hp -= f * dealt;
        }
    }
    if let Some(f) = c.drain {
        e.hp += f * dealt;
    }
    if items && att.item == Items::LIFEORB && !guard && !sheer {
        e.hp -= max / 10.0;
    }
    if c.flags.contact && !guard && !(items && att.item == Items::PROTECTIVEPADS) {
        let n = hits(c, att).0;
        if matches!(def.ability, Abilities::ROUGHSKIN | Abilities::IRONBARBS) {
            e.hp -= n * max / 8.0;
        }
        if items && def.item == Items::ROCKYHELMET {
            e.hp -= n * max / 6.0;
        }
    }
    let four = |b: &poke_engine::choices::StatBoosts| [b.attack, b.defense, b.special_attack, b.special_defense];
    if let Some(b) = &c.boost {
        if b.target == MoveTarget::User {
            e.user = four(&b.boosts);
        }
    }
    let eot = |v: &PokemonVolatileStatus| matches!(v, PokemonVolatileStatus::SALTCURE | PokemonVolatileStatus::PARTIALLYTRAPPED);
    if let Some(v) = &c.volatile_status {
        if v.target == MoveTarget::Opponent && eot(&v.volatile_status) {
            e.afflict = Some(v.volatile_status);
        }
    }
    let shielded = (items && def.item == Items::COVERTCLOAK) || def.ability == Abilities::SHIELDDUST;
    let clear = matches!(def.ability, Abilities::CLEARBODY | Abilities::WHITESMOKE | Abilities::FULLMETALBODY);
    for sec in c.secondaries.iter().flatten() {
        if sheer || sec.chance < 100.0 {
            continue;
        }
        match (&sec.effect, &sec.target) {
            (Effect::Boost(b), &MoveTarget::User) => e.user = add_stages(e.user, four(b)),
            (Effect::Boost(b), &MoveTarget::Opponent) if !shielded => {
                let st = four(b).map(|x| if clear && x < 0 { 0 } else { x });
                e.target = add_stages(e.target, st);
            }
            (Effect::VolatileStatus(v), &MoveTarget::Opponent) if !shielded && eot(v) => e.afflict = Some(*v),
            _ => {}
        }
    }
    e.user = staged(att, e.user);
    e.target = staged(def, e.target);
    e
}

/// The ends of the turns of side `s`'s mon `j` (`eot_hd`: [turn] its (heal, damage)) as its
/// side's active against the other side's mon `k` made active, with its item lost (`off`) / the
/// volatile `v` on it (Salt Cure, a binding), on `work` restored (`orig`: `work` as it is)
#[allow(clippy::too_many_arguments)]
fn eot_variant(
    work: &mut State,
    orig: &State,
    refs: &[SideReference; 2],
    s: usize,
    j: usize,
    k: usize,
    off: bool,
    v: Option<PokemonVolatileStatus>,
    n: usize,
) -> [Hd; EOTS] {
    let saved = enter(work.get_side(&refs[s]), j);
    let saved_k = enter(work.get_side(&refs[1 - s]), k);
    let item = work.get_side_immutable(&refs[s]).pokemon.pkmn[j].item;
    if off {
        work.get_side(&refs[s]).pokemon.pkmn[j].item = Items::NONE;
    }
    let had = v.is_some_and(|v| work.get_side_immutable(&refs[s]).volatile_statuses.contains(&v));
    if let Some(v) = v {
        work.get_side(&refs[s]).volatile_statuses.insert(v);
    }
    let out = eot_hd(work, orig, refs, n).map(|r| r[s]);
    if let (Some(v), false) = (v, had) {
        work.get_side(&refs[s]).volatile_statuses.remove(&v);
    }
    work.get_side(&refs[s]).pokemon.pkmn[j].item = item;
    leave(work.get_side(&refs[1 - s]), saved_k);
    leave(work.get_side(&refs[s]), saved);
    out
}

fn add_stages(a: Stages, b: Stages) -> Stages {
    [0, 1, 2, 3].map(|i| (a[i] + b[i]).clamp(-6, 6))
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
        // (each move's immunity by its own type, as the engine's since L230: Final Gambit and
        // Endeavor checked a Ghost move's; Pain Split, a status move, none)
        Choices::SEISMICTOSS => {
            Some((!immune(&PokemonType::FIGHTING)).then_some(attacker.level as i16))
        }
        Choices::NIGHTSHADE => {
            Some((!immune(&PokemonType::GHOST)).then_some(attacker.level as i16))
        }
        Choices::FINALGAMBIT => Some((!immune(&PokemonType::FIGHTING)).then_some(attacker.hp)),
        Choices::ENDEAVOR => Some(
            (!immune(&PokemonType::NORMAL) && defender.hp > attacker.hp)
                .then_some(defender.hp - attacker.hp),
        ),
        Choices::PAINSPLIT => Some(
            (defender.hp > attacker.hp).then_some(defender.hp - (attacker.hp + defender.hp) / 2),
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
    // (a sure crit's damage: Surging Strikes, Wicked Blow, Flower Trick, Merciless on a poisoned
    // target; not on a Battle Armor / Shell Armor -- the engine's chance; before EXTRA_VERSION 3
    // the no-crit damage)
    let sure_crit = hit_crit_chance(state, side, &choice) >= 1.0;
    let mut incoming = StateInstructions::default();
    before_move(state, &mut choice, defending_choice, side, &mut incoming);
    if choice.move_id == Choices::FUTURESIGHT {
        choice = MOVES.get(&Choices::FUTURESIGHT).unwrap().clone();
    }
    let r = calculate_damage(state, side, &choice, DamageRolls::Max).map(|(d, c)| if sure_crit { c } else { d });
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
) -> Option<(f32, f32)> {
    if choice.move_id == Choices::NONE || choice.category == MoveCategory::Status {
        return None;
    }
    let other = attacker.get_other_side();
    let saved = enter(state.get_side(&other), def_idx);
    let att = state.get_side_immutable(attacker).get_active_immutable().clone();
    let r = damage_inplace(state, attacker, choice.clone()).map(|d| range(choice, &att, d.max(0) as f32));
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
        speed(&mut memo.work, &refs[0], act[0]),
        speed(&mut memo.work, &refs[1], act[1]),
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
                    memo.get(1 - s, act[1 - s], k, &m.choice, act[s]).map(|d| (d.1, k))
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
            e[0] = log_ratio(speed(&mut memo.work, &refs[s], j), speed_act[1 - s]);
            if j != act[s] {
                // the switch-in's entry (hazards) by the engine
                let h = (p.hp - entry_hp(&mut memo.work, state, &refs[s], j)).max(0) as f32;
                e[20] = h / p.maxhp.max(1) as f32;
                e[21] = (h >= p.hp as f32) as u8 as f32;
                if let Some(k) = predicted {
                    let d = memo
                        .get(1 - s, act[1 - s], k, &att_moves[k].choice, j)
                        .map_or(0.0, |r| r.1);
                    let hp = p.hp as f32;
                    e[22] = (d / hp).min(2.0);
                    e[23] = kos(state, att, &att_moves[k].choice, p, d, 0.0, hits(&att_moves[k].choice, att).1) as u8 as f32;
                }
                if attacker_alive {
                    // this bench mon's best move vs the opposing active (as if it were in)
                    let best = memo.best(s, j, act[1 - s], false);
                    e[24] = (best.1 / target_hp).min(2.0);
                }
            }
            let hp = p.hp as f32;
            if attacker_alive {
                // its strongest hit (max roll) and whether that one KOs for sure / possibly
                let best = att_moves
                    .iter()
                    .enumerate()
                    .filter(|(_, m)| !m.disabled)
                    .filter_map(|(k, m)| memo.get(1 - s, act[1 - s], k, &m.choice, j).map(|r| (r, k)))
                    .fold(None, |a: Option<((f32, f32), usize)>, b| match a {
                        Some(x) if x.0 .1 >= b.0 .1 => Some(x),
                        _ => Some(b),
                    });
                if let Some(((lo, d), k)) = best {
                    let c = &att_moves[k].choice;
                    let sub = if j == act[s] { sub_in_way(state, &refs[1 - s], c) } else { 0.0 };
                    let now = lands_now(state, &refs[1 - s], c, true);
                    e[1] = (d / hp).min(2.0);
                    e[2] = (now && kos(state, att, c, p, lo, sub, hits(c, att).0)) as u8 as f32;
                    e[3] = (now && kos(state, att, c, p, d, sub, hits(c, att).1)) as u8 as f32;
                }
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
                if let Some((lo, d)) = memo.get(s, act[s], i, &m.choice, act[1 - s]) {
                    let hp = target.hp as f32;
                    e[o] = (d / hp).min(2.0);
                    let sub = sub_in_way(state, &refs[s], &m.choice);
                    let now = lands_now(state, &refs[s], &m.choice, true);
                    e[o + 1] = (now && kos(state, p, &m.choice, target, lo, sub, hits(&m.choice, p).0)) as u8 as f32;
                    e[o + 2] = (now && kos(state, p, &m.choice, target, d, sub, hits(&m.choice, p).1)) as u8 as f32;
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
    // (zeros if the engine panics in one of its calculations: a state it cannot handle)
    let new = if full {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            v7_entities(state, &sides, act, refs, &mut memo)
        }))
        .unwrap_or_else(|_| vec![0.0; 12 * ENT_NEW])
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
    // the actives' ends of the turn (the engine's: each one's heal, damage)
    let eot = if both { eot_on(&mut memo.work, state, &refs) } else { [(0.0, 0.0); 2] };
    for s in 0..2 {
        let o = 1 - s;
        let me = &sides[s].pokemon.pkmn[act[s]];
        let foe = &sides[o].pokemon.pkmn[act[o]];
        let base = (s * 6 + act[s]) * ENT_NEW;
        if !both {
            continue;
        }
        // ko2 (F3a): two uses of a move KO, hit by hit: the second at the HPs the first left
        // (Super Fang's half of it) -- the target's and the attacker's (recoil, Life Orb, drain:
        // a second use only if the attacker is still up), each one's end of the turn between
        // them, a Focus Sash / Sturdy at full HP, an item the first took, Final Gambit's one hit;
        // for sure (min rolls / hits), possibly (max). The target does not act (no switch, no
        // recovery move)
        {
            for (i, c) in moves_of(me).iter().enumerate() {
                if memo.get(s, act[s], i, c, act[o]).is_none() {
                    continue;
                }
                let hold = holds_at_full(state, me, c, foe);
                let nh = hits(c, me);
                // a use that lands on a later turn (a charge, Future Sight) lands once in the two
                // turns; Fake Out / First Impression only now, once
                let now = lands_now(state, &refs[s], c, true);
                let once = !now
                    || matches!(c.move_id, Choices::FINALGAMBIT | Choices::FAKEOUT | Choices::FIRSTIMPRESSION);
                if !now && matches!(c.move_id, Choices::FAKEOUT | Choices::FIRSTIMPRESSION) {
                    continue;
                }
                let (max, my_max) = (foe.maxhp as f32, me.maxhp as f32);
                for (col, sure) in [(0, true), (1, false)] {
                    let pick = |r: (f32, f32)| if sure { r.0 } else { r.1 };
                    let (mut hp, mut mine) = (foe.hp as f32, me.hp as f32);
                    let n = if sure { nh.0 } else { nh.1 };
                    // (landing later: the end of the first turn, then the one hit)
                    if !now {
                        hp = after_eot(hp, max, eot[o]);
                        mine = after_eot(mine, my_max, eot[s]);
                        if hp <= 0.0 || mine <= 0.0 {
                            out[base + 2 * i + col] = (hp <= 0.0) as u8 as f32;
                            continue;
                        }
                    }
                    let d1 = hit(memo, s, act[s], i, c, act[o], mine, hp, [0; 4], [0; 4], (false, false))
                        .map_or(0.0, pick);
                    let (d1, sub) = through_sub(d1, sub_in_way(state, &refs[s], c), n);
                    let fx = after_hit(state, me, c, foe, d1.min(hp));
                    let lost = now && d1 > 0.0 && loses_item(state, c, foe);
                    // (the target's end of the turn with its item lost / the move's volatile on it)
                    let eot_o = if lost || fx.afflict.is_some() {
                        eot_variant(&mut memo.work, state, &refs, o, act[o], act[s], lost, fx.afflict, 1)[0]
                    } else {
                        eot[o]
                    };
                    hp = take(hp, max, d1, hold);
                    mine = (mine + fx.hp).min(my_max);
                    if c.move_id == Choices::FINALGAMBIT && d1 > 0.0 {
                        mine = 0.0;
                    }
                    if !lost && hp > 0.0 {
                        hp += berry_heal(state, foe, hp, unnerves(me));
                    }
                    let ko = hp <= 0.0 || {
                        hp = after_eot(hp, max, eot_o);
                        mine = after_eot(mine, my_max, eot[s]);
                        hp <= 0.0
                            || (!once && mine > 0.0 && {
                                // (its item lost to the first: the engine's damage without it -- a
                                // Knock Off's 1.5x gone, an Air Balloon, a resist berry; no Focus Sash)
                                let d2 = hit(memo, s, act[s], i, c, act[o], mine, hp, fx.user, fx.target, (false, lost))
                                    .map_or(0.0, pick);
                                let (d2, _) = through_sub(d2, sub, n);
                                take(hp, max, d2, hold && !lost) <= 0.0
                            })
                    };
                    out[base + 2 * i + col] = ko as u8 as f32;
                }
            }
            // the opposing active's priority moves against this one (its priority by the engine:
            // Grassy Glide, Gale Wings, ...)
            let psychic = state.terrain.terrain_type == Terrain::PSYCHICTERRAIN
                && sides[s].active_grounded();
            if !psychic {
                let foe_moves = [&foe.moves.m0, &foe.moves.m1, &foe.moves.m2, &foe.moves.m3];
                let (mut sure, mut maybe) = (false, false);
                for (k, m) in foe_moves.iter().enumerate() {
                    let mut c = m.choice.clone();
                    modify_choice_priority(state, &refs[o], &mut c);
                    if m.disabled || c.priority <= 0 || c.category == MoveCategory::Status {
                        continue;
                    }
                    if !lands_now(state, &refs[o], &m.choice, true) {
                        continue;
                    }
                    if let Some((lo, d)) = memo.get(o, act[o], k, &m.choice.clone(), act[s]) {
                        let sub = sub_in_way(state, &refs[o], &m.choice);
                        sure |= kos(state, foe, &m.choice, me, lo, sub, hits(&m.choice, foe).0);
                        maybe |= kos(state, foe, &m.choice, me, d, sub, hits(&m.choice, foe).1);
                    }
                }
                out[base + 8] = sure as u8 as f32;
                out[base + 9] = maybe as u8 as f32;
            }
        }
        // tera (F6): this side's tera, then the other side's, on the working copy (restored)
        let t = base + ENT_KO2;
        let can = [sides[s].can_use_tera(), sides[o].can_use_tera()];
        let tera_ok = |p: &Pokemon| !p.terastallized && p.tera_type != PokemonType::TYPELESS;
        // the best hit of `att`'s active on `def`'s (range, move) on the working copy
        let best_on = |memo: &mut DamageMemo, att: usize, def: usize| {
            let p = memo.work.get_side_immutable(&refs[att]).get_active_immutable().clone();
            let mut best: Option<((f32, f32), Choice)> = None;
            for (k, c) in moves_of(&p).iter().enumerate() {
                if foe_disabled(&p, k) {
                    continue;
                }
                if let Some(r) = max_damage_inplace(&mut memo.work, &refs[att], c, act[def]) {
                    if best.as_ref().is_none_or(|b| r.1 > b.0 .1) {
                        best = Some((r, c.clone()));
                    }
                }
            }
            best
        };
        if can[0] && tera_ok(me) {
            out[t + 4 * 3 + 3 + 4 * 2 + 3] = 1.0;
            memo.work.get_side(&refs[s]).pokemon.pkmn[act[s]].terastallized = true;
            let tme = memo.work.get_side_immutable(&refs[s]).get_active_immutable().clone();
            for (i, c) in moves_of(me).iter().enumerate() {
                if let Some((lo, d)) = max_damage_inplace(&mut memo.work, &refs[s], c, act[o]) {
                    let hp = foe.hp as f32;
                    out[t + 3 * i] = (d / hp).min(2.0);
                    let sub = sub_in_way(state, &refs[s], c);
                    let now = lands_now(state, &refs[s], c, true);
                    out[t + 3 * i + 1] = (now && kos(state, &tme, c, foe, lo, sub, hits(c, &tme).0)) as u8 as f32;
                    out[t + 3 * i + 2] = (now && kos(state, &tme, c, foe, d, sub, hits(c, &tme).1)) as u8 as f32;
                }
            }
            if let Some(((lo, d), c)) = best_on(memo, o, s) {
                let hp = me.hp as f32;
                out[t + 12] = (d / hp).min(2.0);
                let sub = sub_in_way(state, &refs[o], &c);
                let now = lands_now(state, &refs[o], &c, true);
                out[t + 13] = (now && kos(state, foe, &c, &tme, lo, sub, hits(&c, foe).0)) as u8 as f32;
                out[t + 14] = (now && kos(state, foe, &c, &tme, d, sub, hits(&c, foe).1)) as u8 as f32;
            }
            memo.work.get_side(&refs[s]).pokemon.pkmn[act[s]].terastallized = false;
        }
        if can[1] && tera_ok(foe) {
            out[t + 4 * 3 + 3 + 4 * 2 + 3 + 1] = 1.0;
            memo.work.get_side(&refs[o]).pokemon.pkmn[act[o]].terastallized = true;
            let tfoe = memo.work.get_side_immutable(&refs[o]).get_active_immutable().clone();
            let u = t + 15;
            for (i, c) in moves_of(me).iter().enumerate() {
                if let Some((_, d)) = max_damage_inplace(&mut memo.work, &refs[s], c, act[o]) {
                    let hp = foe.hp as f32;
                    out[u + 2 * i] = (d / hp).min(2.0);
                    let now = lands_now(state, &refs[s], c, true);
                    out[u + 2 * i + 1] = (now && kos(state, me, c, &tfoe, d, sub_in_way(state, &refs[s], c), hits(c, me).1)) as u8 as f32;
                }
            }
            if let Some(((lo, d), c)) = best_on(memo, o, s) {
                let hp = me.hp as f32;
                out[u + 8] = (d / hp).min(2.0);
                let sub = sub_in_way(state, &refs[o], &c);
                let now = lands_now(state, &refs[o], &c, true);
                out[u + 9] = (now && kos(state, &tfoe, &c, me, lo, sub, hits(&c, &tfoe).0)) as u8 as f32;
                out[u + 10] = (now && kos(state, &tfoe, &c, me, d, sub, hits(&c, &tfoe).1)) as u8 as f32;
            }
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
                let d = memo.best(s, j, k, j == act[s]).1;
                dmg[s][j][k] = d / sides[1 - s].pokemon.pkmn[k].hp.max(1) as f32;
            }
        }
    }
    let duels = duels(state, sides, act, refs, memo);
    for s in 0..2 {
        let o = 1 - s;
        for j in 0..6 {
            if !alive(s, j) {
                continue;
            }
            let e = &mut out[(s * 6 + j) * ENT_NEW + ENT_KO2 + ENT_TERA..(s * 6 + j + 1) * ENT_NEW];
            let foes: Vec<usize> = (0..6).filter(|&k| alive(o, k)).collect();
            let n = |f: &dyn Fn(usize) -> bool| foes.iter().filter(|&&k| f(k)).count() as f32 / 6.0;
            let d = &duels[s][j];
            e[0] = n(&|k| dmg[s][j][k] >= 1.0);
            e[1] = n(&|k| dmg[o][k][j] >= 1.0);
            e[2] = n(&|k| d[k].switch_in == Fight::Win);
            e[3] = n(&|k| d[k].switch_in_possible == Fight::Win);
            e[4] = n(&|k| d[k].head_to_head == Fight::Win);
            e[5] = n(&|k| d[k].revenge == Fight::Win);
            e[6] = n(&|k| d[k].switch_in == Fight::Unknown);
            // as a threat: the other side's confirmed switch-in answers, the ones Unknown against it
            // (not "cannot": a mechanic the exchange does not follow, or past its rounds), its
            // confirmed revenge killers
            let count = |f: Fight| (0..6).filter(|&m| alive(o, m) && duels[o][m][j].switch_in == f).count() as f32 / 6.0;
            e[7] = count(Fight::Win);
            e[8] = count(Fight::Unknown);
            e[9] = (0..6).filter(|&m| alive(o, m) && duels[o][m][j].revenge == Fight::Win).count() as f32 / 6.0;
            // as an answer: the threats it is the only confirmed answer to (by switching in / by
            // revenge; another one Unknown may answer too: e[8] of the threat)
            let only = |f: &dyn Fn(&Duel) -> bool| {
                foes.iter()
                    .filter(|&&k| f(&d[k]) && (0..6).filter(|&m| alive(s, m) && f(&duels[s][m][k])).count() == 1)
                    .count() as f32
                    / 6.0
            };
            e[10] = only(&|x| x.switch_in == Fight::Win);
            e[11] = only(&|x| x.revenge == Fight::Win);
        }
    }
    out
}

/// The outcome of an exchange of hits (`fight`) for the mon it is computed for
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
enum Fight {
    Win,
    Lose,
    #[default]
    Unknown,
}

/// How the mon comes in against the foe (design TODO F5 2026-10-20): a switch-in takes the
/// entry hazards and one hit of the foe first; head-to-head, both already in, neither; a revenge
/// kill comes in free after a faint (the hazards only) and must KO with its first hit before
/// the foe acts
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Entry {
    SwitchIn,
    HeadToHead,
    Revenge,
}

/// The exchange rounds after the entry that `fight` plays out (a longer one: Unknown, not lost)
const ROUNDS: usize = 4;
/// The ends of the turns an exchange has at most (the entry's, then each round's)
const EOTS: usize = ROUNDS + 1;
/// The ends of the turns computed first (the rest when an exchange gets that far)
const SHORT: usize = 2;

/// A move that works only if its target attacks (Sucker Punch, Thunderclap) or uses a priority
/// move (Upper Hand), and only before it acts: none on the turn the target switches in
fn needs_target_move(c: &Choice) -> bool {
    matches!(c.move_id, Choices::SUCKERPUNCH | Choices::THUNDERCLAP | Choices::UPPERHAND)
}

/// Mechanics an exchange of hits does not follow (design TODO F5): a reaction to a hit or a turn
/// that changes the exchange -- a stat change (Speed Boost, Weak Armor, Stamina, Berserk, Anger
/// Shell, Justified, Defiant, Competitive, Moody, a Weakness Policy, a Room Service, ...), a type
/// change (Libero, Protean, Color Change), a blocked first hit (Disguise, Ice Face), a switch
/// (Emergency Exit, Wimp Out, an Eject Button / Pack, a Red Card), a berry other than the status,
/// resist, Sitrus and 1/3 ones (a pinch stat berry, Custap, Kee, ...), a White Herb, a Booster
/// Energy on a mon not in yet (it goes off as it comes in). A pair with one: the switch-in / head-to-head
/// outcomes Unknown (not a sure answer built on them); its frequency in `results.md`
fn unsupported(state: &State, p: &Pokemon, active: bool) -> bool {
    let reacts = matches!(
        p.ability,
        Abilities::SPEEDBOOST
            | Abilities::WEAKARMOR
            | Abilities::STAMINA
            | Abilities::BERSERK
            | Abilities::ANGERSHELL
            | Abilities::JUSTIFIED
            | Abilities::RATTLED
            | Abilities::DEFIANT
            | Abilities::COMPETITIVE
            | Abilities::MOODY
            | Abilities::STEAMENGINE
            | Abilities::WATERCOMPACTION
            | Abilities::THERMALEXCHANGE
            | Abilities::LIBERO
            | Abilities::PROTEAN
            | Abilities::COLORCHANGE
            | Abilities::DISGUISE
            | Abilities::ICEFACE
            | Abilities::EMERGENCYEXIT
            | Abilities::WIMPOUT
            | Abilities::ELECTROMORPHOSIS
            | Abilities::WINDPOWER
            | Abilities::SEEDSOWER
            | Abilities::SANDSPIT
            | Abilities::COTTONDOWN
    );
    if reacts {
        return true;
    }
    if item_ignored(state) {
        return false;
    }
    // (followed: a status berry -- no status in an exchange --, a resist berry, Sitrus and the
    // 1/3 ones: `loses_item`, `berry_heal`)
    let followed_berry = matches!(
        p.item,
        Items::LUMBERRY
            | Items::CHESTOBERRY
            | Items::PERSIMBERRY
            | Items::CHERIBERRY
            | Items::PECHABERRY
            | Items::RAWSTBERRY
            | Items::ASPEARBERRY
            | Items::SITRUSBERRY
            | Items::FIGYBERRY
            | Items::WIKIBERRY
            | Items::MAGOBERRY
            | Items::AGUAVBERRY
            | Items::IAPAPABERRY
    ) || resist_berry(p.item);
    (format!("{:?}", p.item).ends_with("BERRY") && !followed_berry)
        // (a Booster Energy goes off as its holder comes in: not in the damage of one made active)
        || (p.item == Items::BOOSTERENERGY && !active)
        || matches!(
            p.item,
            Items::WEAKNESSPOLICY
                | Items::EJECTBUTTON
                | Items::EJECTPACK
                | Items::REDCARD
                | Items::WHITEHERB
                | Items::ROOMSERVICE
                | Items::ABSORBBULB
                | Items::CELLBATTERY
                | Items::LUMINOUSMOSS
                | Items::SNOWBALL
                | Items::ADRENALINEORB
        )
}

/// Side s's mon j against side o's mon k, both made active: each with one fixed move (its
/// highest max damage on the other; none usable on the first turn only; the active's choice
/// lock), who acts first (the engine's priority -- Grassy Glide, Gale Wings, ... -- then the
/// engine's speeds and Trick Room; None: a speed tie), the HPs, the end-of-turn HP changes
/// (the engine's), the HP after j's entry (the engine's switch-in), whether each one's Focus
/// Sash / Sturdy holds the other's hit at full HP
#[derive(Clone, Debug)]
struct DuelSetup<'a> {
    pj: &'a Pokemon,
    pk: &'a Pokemon,
    mj: Option<(usize, Choice)>,
    mk: Option<(usize, Choice)>,
    j_first: Option<bool>,
    hp_j: f32,
    max_j: f32,
    entry_j: f32,
    hp_k: f32,
    max_k: f32,
    /// the end-of-turn HP changes, turn by turn (`eot_turns`), as it is / its item knocked off /
    /// the other's volatile on it (Salt Cure, a binding) / both: [knocked * 2 + afflicted]
    eot_j: [[Hd; EOTS]; 4],
    eot_k: [[Hd; EOTS]; 4],
    /// the ends of the turns known (`SHORT` first: most exchanges end by then; all of them
    /// when one needs more -- `fight` None)
    known: usize,
    /// the fixed move works only if the other attacks first-hand (`needs_target_move`); Upper
    /// Hand: the other's priority
    cond_j: bool,
    cond_k: bool,
    prio_j: i8,
    prio_k: i8,
    /// a mechanic the exchange does not follow (`unsupported`): switch-in / head-to-head Unknown
    unsupported: bool,
    /// the first hit blocked (Disguise / Ice Face): the revenge kill Unknown
    blocked_k: bool,
    hold_j: bool,
    hold_k: bool,
    /// the Substitute HP in the way of k's move on j (head-to-head: a switch-in has none) / of
    /// j's on k
    sub_j: f32,
    sub_k: f32,
}

/// The outcomes of side s's mon j against side o's mon k: as a switch-in (reliable: j's min
/// rolls / hits, k's max, a speed tie to k; possible: the other way round), head-to-head and
/// as a revenge kill (both reliable)
#[derive(Clone, Copy, Debug, Default)]
struct Duel {
    switch_in: Fight,
    switch_in_possible: Fight,
    head_to_head: Fight,
    revenge: Fight,
}

/// An exchange of hits (design TODO F5, 2026-10-20): j and k use their fixed moves, nobody
/// switches, recovers, boosts or terastallizes; hit by hit, each at the HPs and stat stages
/// then (Super Fang, Endeavor, Multiscale, Draco Meteor's drop, ...: `hit`), with what the hit
/// does to its user (recoil, Life Orb, Rough Skin, ...: `after_hit`), a KO ending it at once,
/// then the end of the turn (each one's HP change, the engine's at the state's start). The
/// outcome for j; `sure`: j's min rolls / hits, k's max, a speed tie to k (else the other way
/// round). The ends of the turns turn by turn (the engine's, its turns' state carried: a toxic's
/// growing damage, Wish, the weather ending; with a knocked-off item / an end-of-turn volatile).
/// A move needing the target's attack (Sucker Punch) fails on the switch-in's turn and when it
/// moves second. Not followed (`unsupported`: Unknown): a reaction to a hit / a turn.
#[allow(clippy::too_many_arguments)]
fn fight(
    memo: &mut DamageMemo,
    state: &State,
    s: usize,
    j: usize,
    k: usize,
    d: &DuelSetup<'_>,
    entry: Entry,
    sure: bool,
) -> Option<Fight> {
    if (d.unsupported && entry != Entry::Revenge) || (d.blocked_k && entry == Entry::Revenge) {
        return Some(Fight::Unknown);
    }
    // (an end of the turn not known yet: None, run again with all of them)
    let short = std::cell::Cell::new(false);
    let pick = |r: (f32, f32), mine: bool| if sure == mine { r.0 } else { r.1 };
    let mut hj = if entry == Entry::HeadToHead { d.hp_j } else { d.entry_j };
    let mut hk = d.hp_k;
    if hj <= 0.0 {
        return Some(Fight::Lose);
    }
    let j_first = d.j_first.unwrap_or(!sure);
    let (mut sj, mut sk): (Stages, Stages) = ([0; 4], [0; 4]);
    let subs = std::cell::Cell::new([if entry == Entry::HeadToHead { d.sub_j } else { 0.0 }, d.sub_k]);
    // the items lost (index 0: j's, 1: k's: a Knock Off's, a popped Air Balloon, a berry eaten):
    // the engine's damage without them after, no Focus Sash, the ends of the turns without them
    let knocked = std::cell::Cell::new([false, false]);
    // an end-of-turn volatile on it (Salt Cure, a binding move: its end-of-turn change then)
    let afflicted = std::cell::Cell::new([false, false]);
    let afflict = |i: usize, fx: &HitEffect| {
        if fx.afflict.is_some() {
            let mut v = afflicted.get();
            v[i] = true;
            afflicted.set(v);
        }
    };
    let lose = |i: usize, dm: f32, c: &Choice, def: &Pokemon| {
        let mut v = knocked.get();
        if dm > 0.0 && !v[i] && loses_item(state, c, def) {
            v[i] = true;
            knocked.set(v);
        }
    };
    // a berry's heal after a hit (once: then lost)
    let heal = |i: usize, hp: &mut f32, p: &Pokemon, other: &Pokemon| {
        let mut v = knocked.get();
        if !v[i] {
            let h = berry_heal(state, p, *hp, unnerves(other));
            if h > 0.0 {
                *hp += h;
                v[i] = true;
                knocked.set(v);
            }
        }
    };
    // the damage to the mon behind its side's Substitute (index 0: j's, 1: k's)
    // (`mine`: j's hit -- its hit count as its rolls: the min ones when sure)
    let behind = |i: usize, dd: f32, c: &Choice, att: &Pokemon, mine: bool| {
        let mine = sure == mine;
        let mut v = subs.get();
        let (dm, left) = through_sub(dd, v[i], if mine { hits(c, att).0 } else { hits(c, att).1 });
        v[i] = left;
        subs.set(v);
        dm
    };
    // j hits k (k's HP, then what the hit does to j; Final Gambit: j down too)
    // (`first`: whether it acts before the other this turn -- a move needing the other's attack
    // works only then, and only if the other attacks)
    let works = |cond: bool, first: bool, other: &Option<(usize, Choice)>, other_prio: i8, c: &Choice| {
        !cond || (first && other.is_some() && (c.move_id != Choices::UPPERHAND || other_prio > 0))
    };
    let j_hits = |memo: &mut DamageMemo, hj: &mut f32, hk: &mut f32, sj: &mut Stages, sk: &mut Stages, first: bool| {
        if let Some((slot, c)) = d.mj.as_ref().filter(|(_, c)| works(d.cond_j, first, &d.mk, d.prio_k, c)) {
            let lost = knocked.get();
            let dd = hit(memo, s, j, *slot, c, k, *hj, *hk, *sj, *sk, (lost[0], lost[1])).map_or(0.0, |r| pick(r, true));
            let held = d.hold_k && !lost[1];
            let fx = after_hit(state, d.pj, c, d.pk, dd.min(*hk));
            let dd = behind(1, dd, c, d.pj, true);
            *hk = take(*hk, d.max_k, dd, held);
            lose(1, dd, c, d.pk);
            heal(1, hk, d.pk, d.pj);
            *hj = (*hj + fx.hp).min(d.max_j);
            *sj = add_stages(*sj, fx.user);
            *sk = add_stages(*sk, fx.target);
            afflict(1, &fx);
            if c.move_id == Choices::FINALGAMBIT && dd > 0.0 {
                *hj = 0.0;
            }
        }
    };
    let k_hits = |memo: &mut DamageMemo, hj: &mut f32, hk: &mut f32, sj: &mut Stages, sk: &mut Stages, first: bool| {
        if let Some((slot, c)) = d.mk.as_ref().filter(|(_, c)| works(d.cond_k, first, &d.mj, d.prio_j, c)) {
            let lost = knocked.get();
            let dd = hit(memo, 1 - s, k, *slot, c, j, *hk, *hj, *sk, *sj, (lost[1], lost[0])).map_or(0.0, |r| pick(r, false));
            let held = d.hold_j && !lost[0];
            let fx = after_hit(state, d.pk, c, d.pj, dd.min(*hj));
            let dd = behind(0, dd, c, d.pk, false);
            *hj = take(*hj, d.max_j, dd, held);
            lose(0, dd, c, d.pj);
            heal(0, hj, d.pj, d.pk);
            *hk = (*hk + fx.hp).min(d.max_k);
            *sk = add_stages(*sk, fx.user);
            *sj = add_stages(*sj, fx.target);
            afflict(0, &fx);
            if c.move_id == Choices::FINALGAMBIT && dd > 0.0 {
                *hk = 0.0;
            }
        }
    };
    // both down at once (Final Gambit): lost when sure, won otherwise
    let ended = |hj: f32, hk: f32| -> Option<Fight> {
        match (hj <= 0.0, hk <= 0.0) {
            (true, true) => Some(if sure { Fight::Lose } else { Fight::Win }),
            (true, false) => Some(Fight::Lose),
            (false, true) => Some(Fight::Win),
            _ => None,
        }
    };
    // the ends of the turns in order (the engine's, the turns' state carried: `eot_turns`)
    let turn = std::cell::Cell::new(0usize);
    // (each one's heal at its HP then, cut at its max, then the damage; then a berry's heal)
    let end_of_turn = |hj: &mut f32, hk: &mut f32| {
        let (a, kn, t) = (afflicted.get(), knocked.get(), turn.get().min(EOTS - 1));
        if t >= d.known {
            short.set(true);
        }
        *hj = after_eot(*hj, d.max_j, d.eot_j[kn[0] as usize * 2 + a[0] as usize][t]);
        *hk = after_eot(*hk, d.max_k, d.eot_k[kn[1] as usize * 2 + a[1] as usize][t]);
        turn.set(t + 1);
        heal(0, hj, d.pj, d.pk);
        heal(1, hk, d.pk, d.pj);
    };
    match entry {
        Entry::SwitchIn => {
            // (j only switches in: a move needing its attack fails -- Sucker Punch)
            k_hits(memo, &mut hj, &mut hk, &mut sj, &mut sk, false);
            if let Some(f) = ended(hj, hk) {
                return if short.get() { None } else { Some(f) };
            }
            end_of_turn(&mut hj, &mut hk);
            if let Some(f) = ended(hj, hk) {
                return if short.get() { None } else { Some(f) };
            }
        }
        Entry::Revenge => {
            if !j_first || d.mj.is_none() {
                return Some(Fight::Lose);
            }
            j_hits(memo, &mut hj, &mut hk, &mut sj, &mut sk, true);
            return Some(ended(hj, hk).unwrap_or(Fight::Lose));
        }
        Entry::HeadToHead => {}
    }
    for _ in 0..ROUNDS {
        if j_first {
            j_hits(memo, &mut hj, &mut hk, &mut sj, &mut sk, true);
            if let Some(f) = ended(hj, hk) {
                return if short.get() { None } else { Some(f) };
            }
            k_hits(memo, &mut hj, &mut hk, &mut sj, &mut sk, false);
        } else {
            k_hits(memo, &mut hj, &mut hk, &mut sj, &mut sk, true);
            if let Some(f) = ended(hj, hk) {
                return if short.get() { None } else { Some(f) };
            }
            j_hits(memo, &mut hj, &mut hk, &mut sj, &mut sk, false);
        }
        if let Some(f) = ended(hj, hk) {
            return if short.get() { None } else { Some(f) };
        }
        end_of_turn(&mut hj, &mut hk);
        if let Some(f) = ended(hj, hk) {
            return if short.get() { None } else { Some(f) };
        }
    }
    if short.get() { None } else { Some(Fight::Unknown) }
}

/// Every living mon of each side against each living mon of the other ([side][mon][foe mon]).
fn duels(state: &State, sides: &[&Side; 2], act: [usize; 2], refs: [SideReference; 2], memo: &mut DamageMemo) -> [[[Duel; 6]; 6]; 2] {
    let alive = |s: usize, j: usize| sides[s].pokemon.pkmn[j].hp > 0;
    // each mon's HP after switching in
    let mut entry = [[0.0f32; 6]; 2];
    for s in 0..2 {
        for j in 0..6 {
            if alive(s, j) {
                entry[s][j] = if j == act[s] {
                    sides[s].pokemon.pkmn[j].hp as f32
                } else {
                    entry_hp(&mut memo.work, state, &refs[s], j) as f32
                };
            }
        }
    }
    // each mon's ends of the turns (turn by turn: `eot_variant`) as its side's active against a
    // foe of the context `foe_context` (the foe made active: weather suppression, Neutralizing
    // Gas, Bad Dreams, the actual active's volatiles), with its item lost / an end-of-turn
    // volatile on it: cached by all of these, computed as pairs need them
    type Key = (usize, usize, (Option<Abilities>, bool), bool, Option<PokemonVolatileStatus>, usize);
    let mut cache: Vec<(Key, [Hd; EOTS])> = vec![];
    let mut variant = |memo: &mut DamageMemo, s: usize, j: usize, k: usize, off: bool, v: Option<PokemonVolatileStatus>, n: usize| {
        let seeded = k == act[1 - s] && sides[1 - s].volatile_statuses.contains(&PokemonVolatileStatus::LEECHSEED);
        let key = (s, j, foe_context(&sides[1 - s].pokemon.pkmn[k], seeded), off, v, n);
        if let Some((_, x)) = cache.iter().find(|(c, _)| *c == key) {
            return *x;
        }
        let x = eot_variant(&mut memo.work, state, &refs, s, j, k, off, v, n);
        cache.push((key, x));
        x
    };
    // (each mon's unsupported mechanics, once)
    let uns: [[bool; 6]; 2] = [0, 1].map(|s| core::array::from_fn(|j| alive(s, j) && unsupported(state, &sides[s].pokemon.pkmn[j], j == act[s])));
    let mut out = [[[Duel::default(); 6]; 6]; 2];
    for s in 0..2 {
        let o = 1 - s;
        for j in 0..6 {
            for k in 0..6 {
                if !alive(s, j) || !alive(o, k) {
                    continue;
                }
                let (pj, pk) = (&sides[s].pokemon.pkmn[j], &sides[o].pokemon.pkmn[k]);
                let mj = memo.best_move(s, j, k, j == act[s], true);
                let mk = memo.best_move(o, k, j, k == act[o], true);
                let choice = |p: &Pokemon, m: Option<(usize, (f32, f32))>| {
                    m.map(|(slot, _)| (slot, [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3][slot].choice.clone()))
                };
                let (mut mj, mut mk) = (choice(pj, mj), choice(pk, mk));
                // who acts first: both made active on the working copy
                let sj = enter(memo.work.get_side(&refs[s]), j);
                let sk = enter(memo.work.get_side(&refs[o]), k);
                let prio = |work: &State, r: &SideReference, m: &Option<(usize, Choice)>| {
                    m.as_ref().map_or(0, |(_, c)| {
                        let mut c = c.clone();
                        modify_choice_priority(work, r, &mut c);
                        c.priority
                    })
                };
                let (qj, qk) = (prio(&memo.work, &refs[s], &mj), prio(&memo.work, &refs[o], &mk));
                // a priority move fails on a grounded target in Psychic Terrain
                let psychic = memo.work.terrain.terrain_type == Terrain::PSYCHICTERRAIN;
                if psychic && qj > 0 && memo.work.get_side_immutable(&refs[o]).active_grounded() {
                    mj = None;
                }
                if psychic && qk > 0 && memo.work.get_side_immutable(&refs[s]).active_grounded() {
                    mk = None;
                }
                let (vj, vk) = (
                    get_effective_speed(&memo.work, &refs[s]) as f32,
                    get_effective_speed(&memo.work, &refs[o]) as f32,
                );
                // (a Substitute only on an active: `enter` clears a benched mon's)
                let sub_on = |r: &SideReference, m: &Option<(usize, Choice)>| {
                    m.as_ref().map_or(0.0, |(_, c)| sub_in_way(&memo.work, r, c))
                };
                let (sub_j, sub_k) = (sub_on(&refs[o], &mk), sub_on(&refs[s], &mj));
                leave(memo.work.get_side(&refs[o]), sk);
                leave(memo.work.get_side(&refs[s]), sj);
                let j_first = if qj != qk {
                    Some(qj > qk)
                } else if vj == vk {
                    None
                } else {
                    Some((vj > vk) != state.trick_room.active)
                };
                let hold = |att: &Pokemon, m: &Option<(usize, Choice)>, def: &Pokemon| {
                    m.as_ref().is_some_and(|(_, c)| holds_at_full(state, att, c, def))
                };
                // the ends of the turns once the other's move knocked its item off / put its
                // volatile on it
                let afflicting = |att: &Pokemon, m: &Option<(usize, Choice)>, def: &Pokemon| {
                    m.as_ref().and_then(|(_, c)| after_hit(state, att, c, def, 1.0).afflict)
                };
                // (an item the other's hits can take, or a berry it eats)
                let knocking = |m: &Option<(usize, Choice)>, def: &Pokemon| {
                    m.as_ref().is_some_and(|(_, c)| loses_item(state, c, def)) || berry_heal(state, def, 1.0, false) > 0.0
                };
                let mut seqs = |memo: &mut DamageMemo, s: usize, j: usize, k: usize, att: &Pokemon, m: &Option<(usize, Choice)>, def: &Pokemon, n: usize| {
                    let (v, off) = (afflicting(att, m, def), knocking(m, def));
                    [(false, None), (false, v), (off, None), (off, v)].map(|(o2, v2)| variant(memo, s, j, k, o2, v2, n))
                };
                let eot_j = seqs(memo, s, j, k, pk, &mk, pj, SHORT);
                let eot_k = seqs(memo, o, k, j, pj, &mj, pk, SHORT);
                let cond = |m: &Option<(usize, Choice)>| m.as_ref().is_some_and(|(_, c)| needs_target_move(c));
                let blocks_first = |p: &Pokemon| matches!(p.ability, Abilities::DISGUISE | Abilities::ICEFACE);
                let mut setup = DuelSetup {
                    known: SHORT,
                    eot_j,
                    eot_k,
                    cond_j: cond(&mj),
                    cond_k: cond(&mk),
                    prio_j: qj,
                    prio_k: qk,
                    unsupported: uns[s][j] || uns[o][k],
                    blocked_k: blocks_first(pk),
                    sub_j,
                    sub_k,
                    pj,
                    pk,
                    hold_j: hold(pk, &mk, pj),
                    hold_k: hold(pj, &mj, pk),
                    mj,
                    mk,
                    j_first,
                    hp_j: pj.hp as f32,
                    max_j: pj.maxhp as f32,
                    entry_j: entry[s][j],
                    hp_k: pk.hp as f32,
                    max_k: pk.maxhp as f32,
                };
                let modes = [(Entry::SwitchIn, true), (Entry::SwitchIn, false), (Entry::HeadToHead, true), (Entry::Revenge, true)];
                // (a possible switch-in lost: the reliable one too; won reliably: possibly too)
                let mut res = [None; 4];
                res[1] = fight(memo, state, s, j, k, &setup, Entry::SwitchIn, false);
                res[0] = if res[1] == Some(Fight::Lose) { res[1] } else { fight(memo, state, s, j, k, &setup, Entry::SwitchIn, true) };
                res[2] = fight(memo, state, s, j, k, &setup, Entry::HeadToHead, true);
                res[3] = fight(memo, state, s, j, k, &setup, Entry::Revenge, true);
                if res.iter().any(|r| r.is_none()) {
                    // (one got past the ends of the turns known: all of them, and again)
                    setup.eot_j = seqs(memo, s, j, k, pk, &setup.mk, pj, EOTS);
                    setup.eot_k = seqs(memo, o, k, j, pj, &setup.mj, pk, EOTS);
                    setup.known = EOTS;
                    for (r, (e, sure)) in res.iter_mut().zip(modes) {
                        if r.is_none() {
                            *r = fight(memo, state, s, j, k, &setup, e, sure);
                        }
                    }
                }
                let [switch_in, switch_in_possible, head_to_head, revenge] = res.map(|r| r.unwrap_or(Fight::Unknown));
                out[s][j][k] = Duel { switch_in, switch_in_possible, head_to_head, revenge };
            }
        }
    }
    out
}

/// The exchanges of hits behind `team` (for checking them against the transitions,
/// scripts/check_feature_claims.py): per (side, mon, foe mon) both living, side-relative (0 =
/// the view's own side), the two fixed move slots (-1: none) and the outcomes for the mon
/// (switch-in reliable / possible, head-to-head, revenge: 0 win, 1 lose, 2 unknown).
pub fn duels_debug(state: &State, flip: bool) -> Vec<(usize, usize, usize, i8, i8, [u8; 4])> {
    let refs = [side_ref(true, flip), side_ref(false, flip)];
    let sides = [state.get_side_immutable(&refs[0]), state.get_side_immutable(&refs[1])];
    let act = [sides[0].active_index as usize, sides[1].active_index as usize];
    let mut memo = DamageMemo::new(state, true, refs);
    let d = duels(state, &sides, act, refs, &mut memo);
    let setup_moves = |s: usize, j: usize, k: usize, memo: &mut DamageMemo| {
        let mj = memo.best_move(s, j, k, j == act[s], true).map_or(-1, |m| m.0 as i8);
        let mk = memo.best_move(1 - s, k, j, k == act[1 - s], true).map_or(-1, |m| m.0 as i8);
        (mj, mk)
    };
    let code = |f: Fight| match f {
        Fight::Win => 0u8,
        Fight::Lose => 1,
        Fight::Unknown => 2,
    };
    let mut out = vec![];
    for s in 0..2 {
        for j in 0..6 {
            for k in 0..6 {
                if sides[s].pokemon.pkmn[j].hp <= 0 || sides[1 - s].pokemon.pkmn[k].hp <= 0 {
                    continue;
                }
                let (mj, mk) = setup_moves(s, j, k, &mut memo);
                let x = d[s][j][k];
                out.push((s, j, k, mj, mk, [x.switch_in, x.switch_in_possible, x.head_to_head, x.revenge].map(code)));
            }
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
    // (a world the engine panics on -- a state it cannot handle -- is left out: the mean of the
    // others; all zeros if none is left)
    let mut n = 0;
    for st in states {
        let w = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| posterior_world(st, flip)));
        if let Ok(w) = w {
            for (a, x) in acc.iter_mut().zip(w) {
                *a += x;
            }
            n += 1;
        }
    }
    if n > 0 {
        acc.iter_mut().for_each(|a| *a /= n as f32);
    }
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
        let speed_a = speed(&mut memo.work, &refs[o], a);
        for j in 0..6 {
            let p = &sides[s].pokemon.pkmn[j];
            if p.hp <= 0 {
                continue;
            }
            let e = &mut out[(s * 6 + j) * N_POST..(s * 6 + j + 1) * N_POST];
            let moves = [&p.moves.m0, &p.moves.m1, &p.moves.m2, &p.moves.m3];
            if foe.hp > 0 {
                let sp = speed(&mut memo.work, &refs[s], j);
                e[0] = (sp != speed_a && ((sp > speed_a) != state.trick_room.active)) as u8 as f32;
                let takes = memo.best(o, a, j, true).1 / p.hp.max(1) as f32;
                let deals = memo.best(s, j, a, j == act[s]).1 / foe.hp.max(1) as f32;
                e[1] = (takes >= 1.0) as u8 as f32;
                e[2] = (deals >= 1.0) as u8 as f32;
                e[3] = (takes < 0.5) as u8 as f32;
                // (none on a grounded target in Psychic Terrain, as ko2's priority columns)
                let psychic = state.terrain.terrain_type == Terrain::PSYCHICTERRAIN
                    && sides[o].active_grounded();
                let mut prio = 0.0f32;
                for (k, m) in moves.iter().enumerate() {
                    if !psychic
                        && !m.disabled
                        && m.choice.priority > 0
                        && m.choice.category != MoveCategory::Status
                    {
                        if let Some(d) = memo.get(s, j, k, &m.choice.clone(), a) {
                            prio = prio.max(d.1);
                        }
                    }
                }
                e[4] = (prio >= foe.hp as f32 && prio > 0.0) as u8 as f32;
            }
            // a recovery move: the heal flag without draining (Giga Drain, Drain Punch, Horn
            // Leech have it too) or a heal effect
            e[5] = moves
                .iter()
                .any(|m| (m.choice.flags.heal && m.choice.drain.is_none()) || m.choice.heal.is_some())
                as u8 as f32;
            // a self-boosting move: boost data on the user (Curse only for a non-Ghost), or one the
            // engine boosts by hand (Belly Drum, Fillet Away, Clangorous Soul)
            let ghost = p.has_type(&PokemonType::GHOST);
            e[6] = moves.iter().any(|m| {
                matches!(m.id, Choices::BELLYDRUM | Choices::FILLETAWAY | Choices::CLANGOROUSSOUL)
                    || (!(m.id == Choices::CURSE && ghost)
                        && m.choice.boost.as_ref().is_some_and(|b| {
                            b.target == MoveTarget::User
                                && b.boosts.attack + b.boosts.special_attack + b.boosts.speed
                                    + b.boosts.defense
                                    + b.boosts.special_defense
                                    > 0
                        }))
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

    fn mv(c: Choices) -> Choice {
        MOVES.get(&c).unwrap().clone()
    }

    #[test]
    fn hits_follow_the_engines_kinds() {
        let mut p = fixture().side_one.pokemon.pkmn[0].clone();
        p.ability = Abilities::NONE;
        p.item = Items::NONE;
        assert_eq!(hits(&mv(Choices::EARTHQUAKE), &p), (1.0, 1.0));
        assert_eq!(hits(&mv(Choices::SCALESHOT), &p), (2.0, 5.0));
        assert_eq!(hits(&mv(Choices::SURGINGSTRIKES), &p), (3.0, 3.0));
        assert_eq!(hits(&mv(Choices::DRAGONDARTS), &p), (2.0, 2.0));
        assert_eq!(hits(&mv(Choices::POPULATIONBOMB), &p), (10.0, 10.0));
        assert_eq!(hits(&mv(Choices::TRIPLEAXEL), &p), (3.0, 3.0), "20 / 40 / 60 in hits of 40");
        p.item = Items::LOADEDDICE;
        assert_eq!(hits(&mv(Choices::SCALESHOT), &p), (4.0, 5.0));
        assert_eq!(hits(&mv(Choices::POPULATIONBOMB), &p), (4.0, 10.0));
        p.ability = Abilities::SKILLLINK;
        assert_eq!(hits(&mv(Choices::SCALESHOT), &p), (5.0, 5.0));
    }

    #[test]
    fn ranges_roll_except_the_fixed_damage() {
        let mut p = fixture().side_one.pokemon.pkmn[0].clone();
        p.ability = Abilities::NONE;
        p.item = Items::NONE;
        assert_eq!(range(&mv(Choices::SEISMICTOSS), &p, 100.0), (100.0, 100.0));
        assert_eq!(range(&mv(Choices::SUPERFANG), &p, 100.0), (100.0, 100.0));
        assert_eq!(range(&mv(Choices::EARTHQUAKE), &p, 100.0), (85.0, 100.0));
        assert_eq!(range(&mv(Choices::SCALESHOT), &p, 100.0), (170.0, 500.0));
    }

    #[test]
    fn sash_and_sturdy_hold_a_single_hit_at_full_hp() {
        let st = fixture();
        let att = st.side_one.pokemon.pkmn[0].clone();
        let mut def = st.side_two.pokemon.pkmn[0].clone();
        def.ability = Abilities::NONE;
        def.item = Items::FOCUSSASH;
        def.hp = def.maxhp;
        let eq = mv(Choices::EARTHQUAKE);
        assert!(holds_at_full(&st, &att, &eq, &def));
        assert!(!holds_at_full(&st, &att, &mv(Choices::SCALESHOT), &def), "a multi-hit move breaks it");
        assert!(!kos(&st, &att, &eq, &def, def.maxhp as f32 - 0.5, 0.0, 1.0));
        let max = def.maxhp as f32;
        assert_eq!(take(max, max, 2.0 * max, true), 1.0);
        assert_eq!(take(max - 1.0, max, 2.0 * max, true), -max - 1.0, "not at full HP");
        assert!(!kos(&st, &att, &eq, &def, 2.0 * max, 0.0, 1.0));
        def.hp -= 1;
        assert!(kos(&st, &att, &eq, &def, 2.0 * max, 0.0, 1.0));
        // a Substitute in the way takes a single hit whole (its excess lost), a multi-hit move's
        // later hits go through
        assert!(!kos(&st, &att, &eq, &def, 2.0 * max, 10.0, 1.0));
        assert!(kos(&st, &att, &mv(Choices::SCALESHOT), &def, 2.0 * max, 10.0, 5.0));
        def.hp = def.maxhp;
        def.item = Items::NONE;
        def.ability = Abilities::STURDY;
        assert!(holds_at_full(&st, &att, &eq, &def));
        let mut breaker = att.clone();
        breaker.ability = Abilities::MOLDBREAKER;
        assert!(!holds_at_full(&st, &breaker, &eq, &def), "Mold Breaker ignores Sturdy");
    }

    #[test]
    fn a_substitute_takes_the_hit() {
        assert_eq!(through_sub(50.0, 0.0, 1.0), (50.0, 0.0));
        assert_eq!(through_sub(30.0, 80.0, 1.0), (0.0, 50.0));
        assert_eq!(through_sub(100.0, 80.0, 1.0), (0.0, 0.0), "no carry-over");
        // multi-hit: the breaking hit's excess is lost, the later hits go through (the review's
        // Dragon Darts: 2 x 66 on a 1 HP Substitute: 66 on the mon, not 131)
        assert_eq!(through_sub(132.0, 1.0, 2.0), (66.0, 0.0));
        assert_eq!(through_sub(100.0, 30.0, 5.0), (60.0, 0.0), "2 of 5 hits of 20 break it, 3 hit the mon");
        assert_eq!(through_sub(100.0, 80.0, 2.0), (0.0, 0.0));
        // in the way of a move as the engine has it: not a sound move's, not an Infiltrator's
        let mut st = fixture();
        st.side_two.volatile_statuses.insert(PokemonVolatileStatus::SUBSTITUTE);
        st.side_two.substitute_health = 77;
        st.side_one.get_active().ability = Abilities::NONE;
        let r = SideReference::SideOne;
        assert_eq!(sub_in_way(&st, &r, &mv(Choices::EARTHQUAKE)), 77.0);
        assert_eq!(sub_in_way(&st, &r, &mv(Choices::BOOMBURST)), 0.0);
        st.side_one.get_active().ability = Abilities::INFILTRATOR;
        assert_eq!(sub_in_way(&st, &r, &mv(Choices::EARTHQUAKE)), 0.0);
    }

    #[test]
    fn some_moves_land_later_or_only_first() {
        use poke_engine::engine::state::Weather;
        let mut st = fixture();
        let r = SideReference::SideOne;
        st.weather.weather_type = Weather::NONE;
        st.side_one.get_active().item = Items::NONE;
        assert!(!lands_now(&st, &r, &mv(Choices::FUTURESIGHT), true));
        assert!(lands_now(&st, &r, &mv(Choices::EARTHQUAKE), true));
        assert!(!lands_now(&st, &r, &mv(Choices::SOLARBEAM), true), "a charging turn");
        st.weather.weather_type = Weather::SUN;
        st.weather.turns_remaining = 5;
        assert!(lands_now(&st, &r, &mv(Choices::SOLARBEAM), true), "in the sun at once");
        st.weather.weather_type = Weather::NONE;
        st.side_one.get_active().item = Items::POWERHERB;
        assert!(lands_now(&st, &r, &mv(Choices::SOLARBEAM), true));
        assert!(!lands_now(&st, &r, &mv(Choices::SOLARBEAM), false), "the herb not counted");
        st.side_one.last_used_move = LastUsedMove::Switch(PokemonIndex::P1);
        assert!(lands_now(&st, &r, &mv(Choices::FAKEOUT), true));
        st.side_one.last_used_move = LastUsedMove::Move(PokemonMoveIndex::M0);
        assert!(!lands_now(&st, &r, &mv(Choices::FAKEOUT), true), "not on its first turn");
    }

    #[test]
    fn items_lost_and_berries() {
        let st = fixture();
        let mut def = st.side_two.pokemon.pkmn[0].clone();
        let mut att = st.side_one.pokemon.pkmn[0].clone();
        att.ability = Abilities::NONE;
        def.item = Items::AIRBALLOON;
        assert!(loses_item(&st, &mv(Choices::FLAMETHROWER), &def), "a hit pops it");
        def.item = Items::SHUCABERRY;
        assert!(loses_item(&st, &mv(Choices::EARTHQUAKE), &def));
        def.item = Items::LEFTOVERS;
        assert!(!loses_item(&st, &mv(Choices::EARTHQUAKE), &def));
        assert!(loses_item(&st, &mv(Choices::KNOCKOFF), &def), "knocked off");
        // Sitrus: 1/4 at half or less, not above; none under Unnerve
        def.item = Items::SITRUSBERRY;
        let max = def.maxhp as f32;
        assert_eq!(berry_heal(&st, &def, max / 2.0 + 1.0, false), 0.0);
        assert_eq!(berry_heal(&st, &def, max / 2.0, false), (max / 4.0).floor());
        assert_eq!(berry_heal(&st, &def, max / 2.0, true), 0.0);
        assert_eq!(berry_heal(&st, &def, 0.0, false), 0.0, "down");
        def.item = Items::FIGYBERRY;
        assert_eq!(berry_heal(&st, &def, max / 3.0, false), 0.0);
        assert_eq!(berry_heal(&st, &def, max / 4.0, false), (max / 3.0).floor());
        // the unsupported mechanics: a Weakness Policy, a Booster Energy not in yet
        def.item = Items::WEAKNESSPOLICY;
        assert!(unsupported(&st, &def, true));
        def.item = Items::BOOSTERENERGY;
        assert!(unsupported(&st, &def, false) && !unsupported(&st, &def, true));
        def.item = Items::SITRUSBERRY;
        def.ability = Abilities::NONE;
        assert!(!unsupported(&st, &def, false));
    }

    #[test]
    fn a_hit_costs_its_user() {
        let st = fixture();
        let mut att = st.side_one.pokemon.pkmn[0].clone();
        let mut def = st.side_two.pokemon.pkmn[0].clone();
        att.ability = Abilities::NONE;
        att.item = Items::NONE;
        def.ability = Abilities::NONE;
        def.item = Items::NONE;
        let max = att.maxhp as f32;
        // recoil: a third of the damage dealt (Brave Bird); none with Rock Head
        let fx = |att: &Pokemon, c: Choices, def: &Pokemon, d: f32| after_hit(&st, att, &mv(c), def, d);
        assert!((fx(&att, Choices::BRAVEBIRD, &def, 90.0).hp + 0.33 * 90.0).abs() < 1e-3);
        att.ability = Abilities::ROCKHEAD;
        assert_eq!(fx(&att, Choices::BRAVEBIRD, &def, 90.0).hp, 0.0);
        att.ability = Abilities::NONE;
        // drain: half (Drain Punch)
        assert!((fx(&att, Choices::DRAINPUNCH, &def, 80.0).hp - 40.0).abs() < 1e-3);
        // Life Orb: a tenth of its max HP; none with Magic Guard
        att.item = Items::LIFEORB;
        assert!((fx(&att, Choices::EARTHQUAKE, &def, 80.0).hp + max / 10.0).abs() < 1e-3);
        att.ability = Abilities::MAGICGUARD;
        assert_eq!(fx(&att, Choices::EARTHQUAKE, &def, 80.0).hp, 0.0);
        att.ability = Abilities::NONE;
        att.item = Items::NONE;
        // Rough Skin / a Rocky Helmet on contact, per hit; Earthquake makes none
        def.ability = Abilities::ROUGHSKIN;
        assert!((fx(&att, Choices::CLOSECOMBAT, &def, 80.0).hp + max / 8.0).abs() < 1e-3);
        assert_eq!(fx(&att, Choices::EARTHQUAKE, &def, 80.0).hp, 0.0);
        def.ability = Abilities::NONE;
        def.item = Items::ROCKYHELMET;
        assert!((fx(&att, Choices::DOUBLEKICK, &def, 80.0).hp + 2.0 * max / 6.0).abs() < 1e-3);
        def.item = Items::NONE;
        // the move's own stage changes on the user: Close Combat Def / SpD -1, Draco Meteor SpA
        // -2, Torch Song SpA +1 (a 100% secondary); Contrary reverses them
        assert_eq!(fx(&att, Choices::CLOSECOMBAT, &def, 80.0).user, [0, -1, 0, -1]);
        assert_eq!(fx(&att, Choices::DRACOMETEOR, &def, 80.0).user, [0, 0, -2, 0]);
        assert_eq!(fx(&att, Choices::TORCHSONG, &def, 80.0).user, [0, 0, 1, 0]);
        att.ability = Abilities::CONTRARY;
        assert_eq!(fx(&att, Choices::LEAFSTORM, &def, 80.0).user, [0, 0, 2, 0]);
        att.ability = Abilities::NONE;
        assert_eq!(fx(&att, Choices::DRACOMETEOR, &def, 0.0), HitEffect::default(), "no hit");
        // on the target: Snarl's SpA -1 (not through Clear Body / Covert Cloak), Salt Cure's
        // volatile
        assert_eq!(fx(&att, Choices::SNARL, &def, 80.0).target, [0, 0, -1, 0]);
        def.ability = Abilities::CLEARBODY;
        assert_eq!(fx(&att, Choices::SNARL, &def, 80.0).target, [0; 4]);
        def.ability = Abilities::NONE;
        def.item = Items::COVERTCLOAK;
        assert_eq!(fx(&att, Choices::SNARL, &def, 80.0).target, [0; 4]);
        assert_eq!(fx(&att, Choices::SALTCURE, &def, 80.0).afflict, None);
        def.item = Items::NONE;
        assert_eq!(fx(&att, Choices::SALTCURE, &def, 80.0).afflict, Some(PokemonVolatileStatus::SALTCURE));
        assert_eq!(fx(&att, Choices::MAGMASTORM, &def, 80.0).afflict, Some(PokemonVolatileStatus::PARTIALLYTRAPPED));
    }

    #[test]
    fn end_of_turn_is_the_engines() {
        use poke_engine::engine::state::Weather;
        let mut st = fixture();
        st.weather.weather_type = Weather::NONE;
        st.terrain.terrain_type = Terrain::NONE;
        let refs = [SideReference::SideOne, SideReference::SideTwo];
        for r in refs {
            let side = st.get_side(&r);
            side.volatile_statuses.0 = 0;
            let p = side.get_active();
            p.item = Items::LEFTOVERS;
            p.status = poke_engine::state::PokemonStatus::NONE;
            p.ability = Abilities::NONE;
        }
        let max = st.side_one.get_active_immutable().maxhp;
        // (heal, damage) of side one's active
        assert_eq!(eot_delta(&st, &refs)[0], ((max / 16) as f32, 0.0), "Leftovers");
        // Black Sludge on a Poison type terastallized into a Normal: damage (its current type)
        let p = st.side_one.get_active();
        p.item = Items::BLACKSLUDGE;
        p.types = (PokemonType::POISON, PokemonType::WATER);
        p.tera_type = PokemonType::NORMAL;
        p.terastallized = true;
        assert_eq!(eot_delta(&st, &refs)[0], (0.0, (max / 8) as f32));
        st.side_one.get_active().terastallized = false;
        assert_eq!(eot_delta(&st, &refs)[0], ((max / 16) as f32, 0.0), "a Poison type heals");
        // the HP now does not matter (no HP cuts either off), a fainted active: none
        st.side_one.get_active().hp = 1;
        assert_eq!(eot_delta(&st, &refs)[0], ((max / 16) as f32, 0.0));
        // a Wish of half the max HP, whole (the review: measured at 3/4 it was cut to 1/4)
        st.side_one.get_active().hp = max - 1;
        st.side_one.get_active().item = Items::NONE;
        st.side_one.wish = (1, max / 2);
        assert_eq!(eot_delta(&st, &refs)[0], ((max / 2) as f32, 0.0));
        assert_eq!(after_eot(190.0, 400.0, (200.0, 0.0)), 390.0);
        assert_eq!(after_eot(300.0, 400.0, (200.0, 50.0)), 350.0, "the heal cut at the max, then the damage");
        // the turns' state carried: a toxic grows 1/16, 2/16, 3/16 (the review: 1/16 repeated)
        st.side_one.wish = (0, 0);
        st.side_one.get_active().status = poke_engine::state::PokemonStatus::TOXIC;
        st.side_one.side_conditions.toxic_count = 0;
        let mut work = st.clone();
        let turns = eot_hd(&mut work, &st, &refs, 3);
        assert_eq!([turns[0][0].1, turns[1][0].1, turns[2][0].1], [1, 2, 3].map(|k| (max * k / 16) as f32));
        assert_eq!(work.serialize(), st.serialize());
        st.side_one.get_active().hp = 0;
        assert_eq!(eot_delta(&st, &refs), [(0.0, 0.0); 2]);
    }

    #[test]
    fn in_place_engine_calls_are_undone() {
        // the switch-ins and the ends of the turn run on the working copy and are reversed: the
        // copy is the state again after each (and after all the features)
        let st = fixture();
        let refs = [SideReference::SideOne, SideReference::SideTwo];
        let mut work = st.clone();
        for r in refs {
            for j in 0..6 {
                if work.get_side_immutable(&r).active_index as usize != j && work.get_side_immutable(&r).pokemon.pkmn[j].hp > 0 {
                    entry_hp(&mut work, &st, &r, j);
                    assert_eq!(work.serialize(), st.serialize(), "switch-in {j}");
                }
            }
        }
        eot_on(&mut work, &st, &refs);
        assert_eq!(work.serialize(), st.serialize(), "end of turn");
        eot_variant(&mut work, &st, &refs, 0, 1, 2, true, Some(PokemonVolatileStatus::SALTCURE), EOTS);
        assert_eq!(work.serialize(), st.serialize(), "the ends of the turns, an item off, a volatile");
        eot_hd(&mut work, &st, &refs, EOTS);
        assert_eq!(work.serialize(), st.serialize(), "the ends of the turns");
        let mut memo = DamageMemo::new(&st, true, refs);
        let sides = [st.get_side_immutable(&refs[0]), st.get_side_immutable(&refs[1])];
        let act = [sides[0].active_index as usize, sides[1].active_index as usize];
        v7_entities(&st, &sides, act, refs, &mut memo);
        assert_eq!(memo.work.serialize(), st.serialize(), "after the v7 inputs");
    }

    /// (timing of the parts on real states: ALPHA_FUZZ_STATES=<file> cargo test --release --lib
    /// bench_extra_parts -- --ignored --nocapture)
    #[test]
    #[ignore]
    fn bench_extra_parts() {
        let path = std::env::var("ALPHA_FUZZ_STATES").expect("ALPHA_FUZZ_STATES");
        let states: Vec<State> = std::fs::read_to_string(path).unwrap().lines().take(1000).map(State::deserialize).collect();
        let refs = [SideReference::SideOne, SideReference::SideTwo];
        let t = std::time::Instant::now();
        for st in &states {
            featurize_extra_with(st, false, true, false);
        }
        let v3 = t.elapsed();
        let (mut matrix, mut duel, mut all) = (std::time::Duration::ZERO, std::time::Duration::ZERO, std::time::Duration::ZERO);
        for st in &states {
            let sides = [st.get_side_immutable(&refs[0]), st.get_side_immutable(&refs[1])];
            let act = [sides[0].active_index as usize, sides[1].active_index as usize];
            let mut memo = DamageMemo::new(st, true, refs);
            let t = std::time::Instant::now();
            for s in 0..2 {
                for j in 0..6 {
                    for k in 0..6 {
                        memo.best(s, j, k, false);
                    }
                }
            }
            matrix += t.elapsed();
            let t = std::time::Instant::now();
            let _ = duels(st, &sides, act, refs, &mut memo);
            duel += t.elapsed();
            let t = std::time::Instant::now();
            let mut memo = DamageMemo::new(st, true, refs);
            let _ = v7_entities(st, &sides, act, refs, &mut memo);
            all += t.elapsed();
        }
        let n = states.len() as f64;
        let us = |d: std::time::Duration| d.as_secs_f64() * 1e6 / n;
        println!("per state: v3 {:.0} us; v7 {:.0} us (damage matrix {:.0}, duels after it {:.0})", us(v3), us(all), us(matrix), us(duel));
    }

    /// `state` with side `r`'s mons `a` and `b` swapped (the indices pointing at them too: the
    /// active, a switch as the last move, a Future Sight's user)
    fn swapped(state: &State, r: &SideReference, a: usize, b: usize) -> State {
        let mut st = state.clone();
        let side = st.get_side(r);
        side.pokemon.pkmn.swap(a, b);
        let map = |i: usize| if i == a { b } else if i == b { a } else { i };
        let idx = |i: PokemonIndex| PokemonIndex::deserialize(&map(i as usize).to_string());
        side.active_index = idx(side.active_index);
        if let LastUsedMove::Switch(i) = side.last_used_move {
            side.last_used_move = LastUsedMove::Switch(idx(i));
        }
        side.future_sight.1 = idx(side.future_sight.1);
        st
    }

    /// The structural check (the third review): the order of the teams changes nothing -- two
    /// mons of a side swapped, every input of each mon the same (its row moves), the global ones
    /// the same, in both views. `states`: real states; each side's first two benched mons swapped
    fn order_free(states: &[State]) -> usize {
        // (equal up to the summing order's last bits: the HP fractions' sum)
        let close = |x: &[f32], y: &[f32], what: &str| {
            assert!(x.len() == y.len() && x.iter().zip(y).all(|(a, b)| (a - b).abs() < 1e-5), "{what}: {x:?} vs {y:?}");
        };
        let mut checked = 0;
        for st in states {
            for (si, r) in [SideReference::SideOne, SideReference::SideTwo].iter().enumerate() {
                let side = st.get_side_immutable(r);
                let bench: Vec<usize> = (0..6).filter(|&j| j != side.active_index as usize).collect();
                let (a, b) = (bench[0], bench[1]);
                let sw = swapped(st, r, a, b);
                for flip in [false, true] {
                    let (e1, g1, n1) = featurize_extra_full(st, flip);
                    let (e2, g2, n2) = featurize_extra_full(&sw, flip);
                    close(&g1, &g2, &format!("global inputs (side {si} {a}<->{b}, flip {flip})"));
                    // the swapped side's rows in the view: own (0-5) when it is the view's side
                    let off = if (si == 0) != flip { 0 } else { 6 };
                    let row = |e: usize| if e == off + a { off + b } else if e == off + b { off + a } else { e };
                    for e in 0..12 {
                        close(&e1[e * ENT_EXTRA..(e + 1) * ENT_EXTRA], &e2[row(e) * ENT_EXTRA..(row(e) + 1) * ENT_EXTRA],
                              &format!("v3 inputs of entity {e} (side {si} {a}<->{b}, flip {flip})"));
                        close(&n1[e * ENT_NEW..(e + 1) * ENT_NEW], &n2[row(e) * ENT_NEW..(row(e) + 1) * ENT_NEW],
                              &format!("v7 inputs of entity {e} (side {si} {a}<->{b}, flip {flip})"));
                    }
                    checked += 1;
                }
            }
        }
        checked
    }

    #[test]
    fn the_team_order_changes_nothing() {
        assert_eq!(order_free(&[fixture()]), 4);
    }

    /// (on real states: ALPHA_FUZZ_STATES=<file> cargo test --release --lib
    /// the_team_order_changes_nothing_real -- --ignored)
    #[test]
    #[ignore]
    fn the_team_order_changes_nothing_real() {
        let path = std::env::var("ALPHA_FUZZ_STATES").expect("ALPHA_FUZZ_STATES");
        let states: Vec<State> = std::fs::read_to_string(path).unwrap().lines().take(3000).map(State::deserialize).collect();
        println!("checked {}", order_free(&states));
    }

    #[test]
    fn speed_is_the_engines() {
        let st = fixture();
        let mut work = st.clone();
        let r = SideReference::SideOne;
        let a = st.side_one.active_index as usize;
        assert_eq!(speed(&mut work, &r, a), get_effective_speed(&st, &r).max(1) as f32);
        // a benched mon: as the active without the active's boosts / volatiles
        let j = (a + 1) % 6;
        let mut s2 = st.clone();
        enter(&mut s2.side_one, j);
        assert_eq!(speed(&mut work, &r, j), get_effective_speed(&s2, &r).max(1) as f32);
        assert_eq!(work.serialize(), st.serialize(), "the working copy restored");
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

    /// F2's set columns: a drain move is not recovery; Belly Drum is setup, Curse not on a Ghost
    #[test]
    fn posterior_set_columns() {
        let mut st = fixture();
        let a = st.side_one.active_index as usize;
        let col = |st: &State, k: usize| posterior(&[st.clone()], false)[a * N_POST + k];
        let set = |st: &mut State, ids: [Choices; 4]| {
            let p = &mut st.side_one.pokemon.pkmn[a];
            for (m, id) in [&mut p.moves.m0, &mut p.moves.m1, &mut p.moves.m2, &mut p.moves.m3]
                .into_iter()
                .zip(ids)
            {
                m.id = id;
                m.choice = MOVES.get(&id).unwrap().clone();
            }
        };
        let t = Choices::TACKLE;
        set(&mut st, [Choices::GIGADRAIN, Choices::DRAINPUNCH, t, t]);
        assert_eq!(col(&st, 5), 0.0, "drain moves are not recovery");
        set(&mut st, [Choices::RECOVER, t, t, t]);
        assert_eq!(col(&st, 5), 1.0);
        set(&mut st, [Choices::BELLYDRUM, t, t, t]);
        assert_eq!(col(&st, 6), 1.0, "Belly Drum is setup");
        set(&mut st, [Choices::CURSE, t, t, t]);
        let ghost = st.side_one.pokemon.pkmn[a].has_type(&PokemonType::GHOST);
        assert_eq!(col(&st, 6), if ghost { 0.0 } else { 1.0 }, "Curse");
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
