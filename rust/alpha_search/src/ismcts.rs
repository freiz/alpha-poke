//! SO-ISMCTS over belief-sampled worlds (design D12).
//!
//! One tree for all worlds. Every iteration takes the next world (round robin), descends from
//! the tree root applying instructions to that world's state, and reverses them afterwards.
//! * Children are keyed by (our action label, their action label). Labels are world-independent:
//!   our side is identical in every world; the opponent's moves are labelled by move id (their
//!   move *indices* differ between worlds), switches by team slot.
//! * Selection is decoupled UCB1 per side (as poke-engine's MCTS) with availability counts
//!   (Cowling et al. 2012): an action's exploration term uses ln(times it was available)
//!   instead of the parent's visits, because a move may exist in only some worlds.
//! * Chance: the outcome of a joint action is sampled in the current world each time;
//!   open-loop (one child per joint action). Instruction lists are cached per (joint action, world) at the root
//!   only: poke-engine instructions carry absolute old / new values, and below the root the
//!   same node is reached in different states (different sampled outcomes above it), so a
//!   cached list would apply and reverse the wrong values.
//! * Leaf value: sigmoid(crate::bsearch::evaluate_checked(state) - that world's root evaluation), as poke-engine.
//! * Network (design D13): the transformer (`tnet`, with a `Context` per
//!   world: public-information bits, ratings, turn, real history). Along the descent the path's
//!   decision steps extend the history, the moves / tera / switch-ins used reveal their bits and
//!   the main steps advance the turn, so every node is evaluated with its own inputs.

use crate::features::{Act, Step, HIST};
use crate::tnet::{Context, Input, TNet};
use poke_engine::choices::Choices;
use poke_engine::engine::evaluate::evaluate;
use poke_engine::engine::generate_instructions::generate_instructions_from_move_pair;
use poke_engine::engine::state::{MoveChoice, PokemonVolatileStatus};
use poke_engine::instruction::{Instruction, StateInstructions};
use poke_engine::state::PokemonMoveIndex::{M0, M1, M2, M3};
use poke_engine::state::{PokemonIndex, Side, SideReference, State};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use rustc_hash::FxHashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Label {
    None,
    Move(Choices),
    MoveTera(Choices),
    Switch(PokemonIndex),
    Other(MoveChoice), // mega / team preview: not used in Gen 9 OU singles
}

pub fn label(side: &Side, mc: &MoveChoice) -> Label {
    match mc {
        MoveChoice::Move(i) => Label::Move(side.get_active_immutable().moves[i].id),
        MoveChoice::MoveTera(i) => Label::MoveTera(side.get_active_immutable().moves[i].id),
        MoveChoice::Switch(p) => Label::Switch(*p),
        MoveChoice::None => Label::None,
        other => Label::Other(*other),
    }
}

#[derive(Debug, Clone)]
pub struct Arm {
    pub label: Label,
    pub visits: u32,
    pub avail: u32,
    pub total: f32,
    /// policy prior (PUCT); < 0 = none (an action first seen in a later world: uniform)
    pub prior: f32,
    /// moves left (v6 head): the sum and number of the backed-up estimates of the turns from
    /// the root to the game's end (turns on the path + the leaf's predicted remaining turns)
    pub ml_total: f32,
    pub ml_n: u32,
}

impl Arm {
    fn ucb(&self, c: f32) -> f32 {
        if self.visits == 0 {
            return f32::INFINITY;
        }
        self.total / self.visits as f32 + c * ((self.avail as f32).ln() / self.visits as f32).sqrt()
    }

    pub fn mean(&self) -> f32 {
        if self.visits == 0 {
            0.0
        } else {
            self.total / self.visits as f32
        }
    }
}

#[derive(Debug, Default)]
pub struct Node {
    pub visits: u32,
    pub depth: u16,
    pub s1: Vec<Arm>,
    pub s2: Vec<Arm>,
    /// priors set (first selection at this node, in whatever world it happens)
    pub priors_set: bool,
    /// side one's policy logits from the forward pass that valued this node as a leaf, and our
    /// active mon in that state (`cached_logits_fit`)
    pub logits1: Option<Box<([f32; crate::features::N_ACTIONS], PokemonIndex)>>,
    /// batched search: created as a leaf whose network evaluation has not come back yet
    pub pending: bool,
    /// (tests: the public phase of the state that first reached it, `phase`)
    #[cfg(test)]
    pub phase: Option<(PokemonIndex, PokemonIndex, bool, bool)>,
}

/// The public phase of a state: both actives, whether each side must switch
pub(crate) fn phase(state: &State) -> (PokemonIndex, PokemonIndex, bool, bool) {
    let forced = |side: &Side| side.force_switch || side.get_active_immutable().hp <= 0;
    (
        state.side_one.active_index,
        state.side_two.active_index,
        forced(&state.side_one),
        forced(&state.side_two),
    )
}

/// A child's key part after its joint action's outcome: the public phase (`Config::phase_key`),
/// else 0 (open loop)
pub(crate) fn phase_sig(state: &State, cfg: &Config) -> u64 {
    if !cfg.phase_key {
        return 0;
    }
    let (a, b, f1, f2) = phase(state);
    1 << 8 | (a as u64) | (b as u64) << 3 | (f1 as u64) << 6 | (f2 as u64) << 7
}

#[cfg(test)]
pub(crate) static PHASE_SAME: [std::sync::atomic::AtomicU64; 2] = [
    std::sync::atomic::AtomicU64::new(0),
    std::sync::atomic::AtomicU64::new(0),
];

pub(crate) fn arm_index(arms: &mut Vec<Arm>, l: Label) -> usize {
    match arms.iter().position(|a| a.label == l) {
        Some(i) => i,
        None => {
            arms.push(Arm {
                label: l,
                visits: 0,
                avail: 0,
                total: 0.0,
                prior: -1.0,
                ml_total: 0.0,
                ml_n: 0,
            });
            arms.len() - 1
        }
    }
}

/// The moves-left term of the selection (design v6, Leela's moves-left utility): when a side's
/// value at a node is clearly decided (|2q - 1| > `threshold`), its arms get
/// -sign(2q - 1) * clamp(`slope` * (arm's moves left - the node's), +-`cap`) * the excess
/// (|2q - 1| - threshold) / (1 - threshold): the winner prefers shorter games, the loser longer
/// ones; the win probability itself stays unchanged. `slope` 0 = off. `winner_only`: the losing
/// side gets no term (a capped game is a draw, 2026-10-15: preferring long games when losing
/// meant stalling to the turn cap: 8 capped games in 1,200 vs 2-5 without the term).
#[derive(Clone, Copy, Debug, Default)]
pub struct MlParams {
    pub slope: f32,
    pub cap: f32,
    pub threshold: f32,
    pub winner_only: bool,
}

#[derive(Clone)]
pub struct Config {
    pub c: f32,
    /// cache the root's instruction lists per (joint action, world)
    pub cache_root: bool,
    /// branch on damage rolls for nodes shallower than this (poke-engine: root and its children)
    pub branch_depth: u16,
    /// PUCT with the network's policy priors (needs `tnet`); else decoupled UCB1
    pub use_policy: bool,
    /// also the opponent's priors (its view, one more forward pass per node); else UCB1 for it
    pub policy_opponent: bool,
    pub c_puct: f32,
    /// the network for the leaves and priors (design D13; needs one `Context` per world); None
    /// = poke-engine's handcrafted evaluation
    pub tnet: Option<Arc<TNet>>,
    /// self-play exploration: the root priors of both sides become (1 - eps) p + eps eta,
    /// eta ~ Dirichlet(conc / n options) (AlphaZero); eps 0 = off
    pub root_noise_eps: f32,
    pub root_noise_conc: f32,
    /// moves-left term (needs a network with the remaining-turns head)
    pub ml: MlParams,
    /// children keyed also by the public phase after the outcome (`phase_sig`: both actives,
    /// forced switches; 2026-10-21, the search review): else open loop, one child per joint
    /// action (a KO and no KO by the damage roll share a node)
    pub phase_key: bool,
    /// the principal variations to return (`variations`): our top options, the opponent's top
    /// replies to each, plies; (0, 0, 0) = none (a review's, 2026-10-30)
    pub pv: (usize, usize, usize),
}

impl Default for Config {
    fn default() -> Self {
        Config {
            c: std::f32::consts::SQRT_2,
            cache_root: true,
            branch_depth: 2,
            use_policy: false,
            policy_opponent: true,
            c_puct: 1.0,
            tnet: None,
            root_noise_eps: 0.0,
            root_noise_conc: 10.0,
            ml: MlParams::default(),
            phase_key: false,
            pv: (0, 0, 0),
        }
    }
}

pub struct Tree {
    pub nodes: Vec<Node>,
    pub(crate) children: FxHashMap<(u32, u16, u16, u64), u32>,
    pub(crate) cache: FxHashMap<(u32, u16, u16, u16), Vec<StateInstructions>>,
    /// the opponent's root priors per world (`RootPriors`): its selection at the root uses the
    /// current world's own; empty = the arms' priors
    pub(crate) root_opp: Vec<Vec<f32>>,
}

pub struct SearchResult {
    /// our root actions: (label, visits, mean value)
    pub s1: Vec<(Label, u32, f32)>,
    /// the opponent's root actions: (label, visits, mean value -- side one's: what that choice of
    /// theirs leaves us); a review shows what the search expected of the opponent (2026-10-30)
    pub s2: Vec<(Label, u32, f32)>,
    /// the principal variations (`Config::pv`, `variations`)
    pub variations: Vec<Vec<PvStep>>,
    /// our root actions' priors (PUCT; < 0 = none, e.g. without a network)
    pub s1_priors: Vec<(Label, f32)>,
    pub iterations: u32,
    pub nodes: usize,
    pub max_depth: u16,
}

/// Value of a non-terminal leaf for side one: the value network if there is one (its residual
/// uses the handcrafted evaluation), else poke-engine's leaf value relative to the root.
fn leaf_value(state: &State, root_eval: f32, cfg: &Config, path: &PathCtx) -> f32 {
    if let (Some(tnet), Some(ctx)) = (&cfg.tnet, path.base) {
        let x = Input::new(
            state,
            &path.context(ctx),
            false,
            crate::bsearch::evaluate_checked(state),
        );
        return 1.0 / (1.0 + (-tnet.value(&x)).exp());
    }
    sigmoid(crate::bsearch::evaluate_checked(state) - root_eval)
}

/// A side switches before the turn goes on: a pivot's switch (`force_switch`) or a faint's (the
/// engine switches a side whose active has no HP even without `force_switch`)
fn forced(side: &Side) -> bool {
    side.force_switch || side.get_active_immutable().hp <= 0
}

/// What the descent adds to a world's context: the decision steps taken, the bits they reveal,
/// the main steps (turns) completed.
pub(crate) struct PathCtx<'a> {
    base: Option<&'a Context>,
    steps: Vec<Step>,
    reveal: [u8; 12],
    mains: i32,
    // a main step pushed, its turn not over yet (a pivot's / a faint's switch to come)
    open: bool,
    // the last step's moves, until `settle`
    pending: [Option<Pending>; 2],
}

/// A side's move in the last step, until `settle` sees whether it came.
#[derive(Clone, Copy)]
struct Pending {
    /// its reveal byte
    at: usize,
    slot: PokemonIndex,
    /// the move slot chosen (none: a Struggle, a recharge)
    chosen: Option<usize>,
    /// its moves' ids then (the slot it used may be another: an Encore's)
    moves: [i32; 4],
    /// locked into its move (Outrage's later turns, a charge move's second, a recharge): no
    /// decision -- the log's move line is "[from]lockedmove", no action
    locked: bool,
}

impl<'a> PathCtx<'a> {
    /// `root`: the search's root state -- a switch to come there (a faint's replacement, a
    /// pivot's switch-in) is the root turn's, not over yet: counted once it is done (2026-10-23
    /// review: a forced root opened no turn, every node below read one turn behind)
    pub(crate) fn new(base: Option<&'a Context>, root: &State) -> Self {
        PathCtx {
            base,
            steps: Vec::new(),
            reveal: base.map_or([0; 12], |c| c.reveal),
            mains: 0,
            open: base.is_some() && (forced(&root.side_one) || forced(&root.side_two)),
            pending: [None; 2],
        }
    }

    /// Record the joint action about to be applied in `state` (its moves as used until
    /// `settle` sees the outcome).
    pub(crate) fn push(&mut self, state: &State, m1: &MoveChoice, m2: &MoveChoice) {
        if self.base.is_none() {
            return;
        }
        // a forced switch (a pivot, or a faint: the engine switches a side whose active has no
        // HP even without `force_switch`; 2026-10-14) is not a new turn; a main step opens one,
        // counted when it is over (`settle`: no switch left to come -- 2026-10-22 review: a
        // pivot's switch-in node read the next turn already, the log and replays the same one)
        if !(forced(&state.side_one) || forced(&state.side_two)) {
            self.open = true;
        }
        let mut step = Step {
            one: Act::of_choice(&state.side_one, m1),
            two: Act::of_choice(&state.side_two, m2),
        };
        // a Struggle (the none option of a side that struggles) is its move, as the log and the
        // replays' history have it ("m:<mon>:STRUGGLE"; 2026-10-23 review: no action); checked
        // by `settle` as a move is (it may not come: asleep, fainted first, saved behind the
        // foe's pivot -- 2026-10-23 review)
        let mut struggle = [false; 2];
        for (k, (act, mc, side_ref)) in [
            (&mut step.one, m1, SideReference::SideOne),
            (&mut step.two, m2, SideReference::SideTwo),
        ]
        .into_iter()
        .enumerate()
        {
            if *mc == MoveChoice::None && crate::features::struggles(state, side_ref) {
                act.kind = 1;
                act.actor = crate::features::entry_forme(
                    state
                        .get_side_immutable(&side_ref)
                        .get_active_immutable()
                        .id,
                ) as i32;
                act.target = Choices::STRUGGLE as i32;
                struggle[k] = true;
            }
        }
        self.steps.push(step);
        for (k, (off, side, mc)) in [(0, &state.side_one, m1), (6, &state.side_two, m2)]
            .into_iter()
            .enumerate()
        {
            self.pending[k] = None;
            let me = side.get_active_immutable();
            let mut pending = Pending {
                at: off + side.active_index as usize,
                slot: side.active_index,
                chosen: None,
                moves: [M0, M1, M2, M3].map(|j| me.moves[&j].id as i32),
                locked: false,
            };
            if struggle[k] {
                // (nothing to reveal: no move of its set -- slot 0 is not its first move)
                self.pending[k] = Some(pending);
                continue;
            }
            match mc {
                MoveChoice::Move(i) | MoveChoice::MoveTera(i) => {
                    let a = pending.at;
                    // seen (and its tera) whether or not the move comes
                    self.reveal[a] |= 1;
                    if matches!(mc, MoveChoice::MoveTera(_)) {
                        self.reveal[a] |= 1 << 3;
                    }
                    pending.chosen = Some(*i as usize);
                    // (L241: an Uproar's own lock too -- the engine's Side::locked)
                    pending.locked = side.locked() || side.active_is_charging_move().is_some();
                    self.pending[k] = Some(pending);
                }
                // a recharge (the engine's only option then): "cant ... recharge" in the log --
                // prevented, or fainted first (2026-10-24, the tree's history check: no action)
                MoveChoice::None
                    if side
                        .volatile_statuses
                        .contains(&PokemonVolatileStatus::MUSTRECHARGE) =>
                {
                    pending.locked = true;
                    self.pending[k] = Some(pending);
                }
                MoveChoice::Switch(p) => self.reveal[off + *p as usize] |= 1,
                _ => {}
            }
        }
    }

    /// The last step's outcome (`instructions` applied, `state` after them): a move the engine
    /// never started (`Instruction::Acted` absent: fainted first, asleep, frozen, paralysed,
    /// flinched, ...) is no action -- "fainted before acting" or "prevented", as the replays
    /// record it -- and reveals no move (2026-10-14: the chosen move was recorded as used).
    pub(crate) fn settle(&mut self, instructions: &[Instruction], state: &State) {
        if self.base.is_none() {
            return;
        }
        // (the turn over: no pivot's / faint's switch to come)
        if self.open && !(forced(&state.side_one) || forced(&state.side_two)) {
            self.mains += 1;
            self.open = false;
        }
        let Some(step) = self.steps.last_mut() else {
            return;
        };
        for (k, side_ref, side) in [
            (0, SideReference::SideOne, &state.side_one),
            (1, SideReference::SideTwo, &state.side_two),
        ] {
            let Some(p) = self.pending[k].take() else {
                continue;
            };
            let acted = instructions
                .iter()
                .position(|i| matches!(i, Instruction::Acted(s) if *s == side_ref));
            // the slot its PP went from, before the move started: the move it used (an Encore
            // in the turn put it on another than the chosen one; Showdown's log, the replays'
            // history: the move used -- 2026-10-24, the tree's history check). A move with no
            // target left (its foe gone: the engine returns before `Acted`) is used too: the
            // log's move line, failed ("[notarget]"; a locked one's "[from]lockedmove": none)
            // (its own move's span only: from its Turn on, to its start -- or to the foe's turn
            // after; a foe's Eerie Spell / Spite takes its PP too: 2026-10-24 review, the Roost of
            // a Corviknight Eerie Spell hit read as its Brave Bird)
            let from = instructions
                .iter()
                .position(|i| matches!(i, Instruction::Turn(s) if *s == side_ref))
                .unwrap_or(instructions.len());
            let to = acted.unwrap_or_else(|| {
                instructions[from..]
                    .iter()
                    .position(|i| matches!(i, Instruction::Turn(s) if *s != side_ref))
                    .map_or(instructions.len(), |k| from + k)
            });
            let used = instructions[from..to.max(from)]
                .iter()
                .find_map(|i| match i {
                    Instruction::DecrementPP(d) if d.side_ref == side_ref && d.amount > 0 => {
                        Some(d.move_index as usize)
                    }
                    _ => None,
                });
            let no_target = instructions
                .iter()
                .any(|i| matches!(i, Instruction::NoTarget(s) if *s == side_ref));
            if acted.is_some() || used.is_some() || no_target {
                if p.locked {
                    // (no decision: no action, nothing revealed by it)
                    if k == 0 {
                        step.one = Act::default();
                    } else {
                        step.two = Act::default();
                    }
                    continue;
                }
                let slot = used.or(p.chosen);
                if let Some(j) = slot {
                    self.reveal[p.at] |= 1 << (4 + j);
                    if slot != p.chosen {
                        let act = if k == 0 { &mut step.one } else { &mut step.two };
                        act.target = p.moves[j];
                    }
                }
                continue;
            }
            // a move that did not come, as the replays record it (train/positions blind_sides):
            // stopped at its turn -- asleep, frozen, fully paralysed, flinched, recharging, ...:
            // "cant" in the log -- prevented, knocked out after it or not; it hit itself in
            // confusion (no "cant"): fainted first if that knocked it out, else no action; no turn
            // (fainted before it, dragged out, its move saved behind the foe's pivot -- the next
            // step's): fainted first if it fainted, else no action -- but one ejected before it (an
            // Eject Button's, an Emergency Exit's switch to come: "ejected", prevented) (2026-10-24,
            // the tree's history check: a frozen mon knocked out after read as fainted first, a
            // dragged one or a confusion self-hit as prevented)
            let turn = instructions
                .iter()
                .any(|i| matches!(i, Instruction::Turn(s) if *s == side_ref))
                || (side.force_switch && side.pokemon[p.slot].hp > 0);
            let hit = instructions
                .iter()
                .any(|i| matches!(i, Instruction::HitItself(s) if *s == side_ref));
            let fainted = side.pokemon[p.slot].hp <= 0;
            let act = Act {
                prevented: turn && !hit,
                fainted_first: (!turn || hit) && fainted,
                ..Act::default()
            };
            if k == 0 {
                step.one = act;
            } else {
                step.two = act;
            }
        }
    }

    /// The world's context at the current node.
    /// main steps (turns) completed along the path
    pub(crate) fn turns(&self) -> i32 {
        self.mains
    }

    pub(crate) fn context(&self, base: &Context) -> Context {
        let mut history: Vec<Step> = base.history.clone();
        history.extend_from_slice(&self.steps);
        let cut = history.len().saturating_sub(HIST);
        Context {
            reveal: self.reveal,
            rating: base.rating,
            turn: base.turn + self.mains,
            history: history.split_off(cut),
            full: base.full,
            post: base.post.clone(),
        }
    }
}

/// Either side's none option is Struggle (the engine's `struggles`): both none is then a turn
/// to play out, not a leaf (2026-10-22 review: both out of PP, the search stayed at the root)
pub(crate) fn someone_struggles(state: &State) -> bool {
    use poke_engine::engine::generate_instructions::struggles;
    struggles(state, &SideReference::SideOne) || struggles(state, &SideReference::SideTwo)
}

pub(crate) fn sigmoid(x: f32) -> f32 {
    1.0 / (1.0 + (-0.0125 * x).exp())
}

/// Softmax of `logits` over the available options; their arms get the probabilities as priors.
pub(crate) fn set_priors(arms: &mut [Arm], avail: &[(usize, MoveChoice)], logits: &[f32]) {
    for (&(i, _), p) in avail.iter().zip(prior_probs(avail, logits)) {
        arms[i].prior = p;
    }
}

/// The network's priors over `avail` (a softmax over their action slots' logits; uniform when
/// none is finite)
pub(crate) fn prior_probs(avail: &[(usize, MoveChoice)], logits: &[f32]) -> Vec<f32> {
    // (a Struggle: move slot 0 -- it had none, a prior of 0; 2026-10-23 review)
    let struggle = crate::features::struggle_in(avail);
    let slots: Vec<Option<usize>> = avail
        .iter()
        .map(|(_, mc)| crate::features::slot_in(mc, struggle))
        .collect();
    let m = slots
        .iter()
        .flatten()
        .map(|&k| logits[k])
        .filter(|x| x.is_finite())
        .fold(f32::MIN, f32::max);
    let exps: Vec<f32> = slots
        .iter()
        .map(|s| match s {
            Some(k) if logits[*k].is_finite() => (logits[*k] - m).exp(),
            _ => 0.0,
        })
        .collect();
    let z: f32 = exps.iter().sum();
    (0..avail.len())
        .map(|j| {
            if z > 0.0 {
                exps[j] / z
            } else {
                1.0 / avail.len() as f32
            }
        })
        .collect()
}

/// The logits cached when a node was created serve its priors only if they were computed for
/// the same options (2026-10-21, the search review): open loop, the node's first selection is in
/// another world / sampled outcome than its creation -- created where our active fainted (the
/// network's moves -inf: only switches legal), selected where it lives, every move's prior was 0
/// for good; or our active another mon (a phazing move, Eject Button), its moves' logits were
/// the other mon's. Same active and every option's slot finite, else a forward pass here.
pub(crate) fn cached_logits_fit(
    cached: &([f32; crate::features::N_ACTIONS], PokemonIndex),
    state: &State,
    avail: &[(usize, MoveChoice)],
) -> bool {
    cached.1 == state.side_one.active_index
        && avail.iter().all(|(_, mc)| {
            crate::features::slot_in(mc, crate::features::struggle_in(avail))
                .is_none_or(|k| cached.0[k].is_finite())
        })
}

/// (tests) a step's outcome leaves the stat stages within -6..6, else the step is printed
#[cfg(test)]
fn check_stages(
    before: &str,
    m1: &MoveChoice,
    m2: &MoveChoice,
    ins: &[Instruction],
    state: &State,
) {
    let out = [&state.side_one, &state.side_two].iter().any(|sd| {
        [
            sd.attack_boost,
            sd.defense_boost,
            sd.special_attack_boost,
            sd.special_defense_boost,
            sd.speed_boost,
            sd.accuracy_boost,
            sd.evasion_boost,
        ]
        .iter()
        .any(|b| !(-6..=6).contains(b))
    });
    assert!(
        !out,
        "stages out of range\nBEFORE {before}\nMOVES {m1:?} {m2:?}\nINSTRUCTIONS {ins:?}"
    );
}

/// (tests: how often the cached logits did not fit / did)
#[cfg(test)]
pub(crate) static CACHE_FIT: [std::sync::atomic::AtomicU64; 2] = [
    std::sync::atomic::AtomicU64::new(0),
    std::sync::atomic::AtomicU64::new(0),
];

/// The root's priors from every world's network evaluation (2026-10-21/22, the search reviews:
/// they came from the first world alone -- the worlds' order changed the search):
/// * ours: the mean over the worlds (our side, and so our options, is the same in every world);
/// * the opponent's: each world's own (it knows its set: its policy is conditioned on the world,
///   not the belief's marginal -- an arm of a rare set at its mean over all worlds was pushed
///   down again where the set is); its arms' priors (the record, a fallback) are the mean over
///   the worlds that have the arm;
/// * root noise (self-play): one Dirichlet draw over all the root's arms of a side (every world's
///   options), in label order -- the same for any order of the worlds (before: the last world's
///   options only, the others' kept their prior).
///
/// `add` per world in world order, then `finish`.
#[derive(Default)]
pub(crate) struct RootPriors {
    ours: Vec<f32>,
    worlds: u32,
    opp: Vec<Vec<(usize, f32)>>,
}

impl RootPriors {
    pub(crate) fn add(
        &mut self,
        av1: &[(usize, MoveChoice)],
        p1: &[f32],
        av2: &[(usize, MoveChoice)],
        p2: Option<&[f32]>,
    ) {
        for (&(i, _), &p) in av1.iter().zip(p1) {
            if self.ours.len() <= i {
                self.ours.resize(i + 1, 0.0);
            }
            self.ours[i] += p;
        }
        self.worlds += 1;
        if let Some(p2) = p2 {
            self.opp
                .push(av2.iter().zip(p2).map(|(&(i, _), &p)| (i, p)).collect());
        }
    }

    pub(crate) fn finish(
        &self,
        root: &mut Node,
        root_opp: &mut Vec<Vec<f32>>,
        cfg: &Config,
        rng: &mut impl Rng,
    ) {
        for (i, a) in root.s1.iter_mut().enumerate() {
            a.prior = self.ours.get(i).copied().unwrap_or(0.0) / self.worlds.max(1) as f32;
        }
        root_opp.clear();
        if !self.opp.is_empty() {
            let n = root.s2.len();
            let (mut sum, mut cnt) = (vec![0.0f32; n], vec![0u32; n]);
            for w in &self.opp {
                let mut v = vec![-1.0f32; n];
                for &(i, p) in w {
                    v[i] = p;
                    sum[i] += p;
                    cnt[i] += 1;
                }
                root_opp.push(v);
            }
            for (i, a) in root.s2.iter_mut().enumerate() {
                a.prior = if cnt[i] > 0 {
                    sum[i] / cnt[i] as f32
                } else {
                    -1.0
                };
            }
        }
        if cfg.root_noise_eps > 0.0 {
            let (eps, conc) = (cfg.root_noise_eps, cfg.root_noise_conc);
            let eta = dirichlet_by_label(&root.s1, conc, rng);
            for (a, e) in root.s1.iter_mut().zip(&eta) {
                a.prior = (1.0 - eps) * a.prior.max(0.0) + eps * e;
            }
            if !self.opp.is_empty() {
                let eta = dirichlet_by_label(&root.s2, conc, rng);
                for v in root_opp.iter_mut() {
                    for (p, e) in v.iter_mut().zip(&eta) {
                        if *p >= 0.0 {
                            *p = (1.0 - eps) * *p + eps * e;
                        }
                    }
                }
                for (a, e) in root.s2.iter_mut().zip(&eta) {
                    a.prior = (1.0 - eps) * a.prior.max(0.0) + eps * e;
                }
            }
        }
        root.priors_set = true;
    }
}

/// One Dirichlet(conc / n) draw per arm, drawn in the arms' label order (the arms' own order
/// follows the worlds' order)
fn dirichlet_by_label(arms: &[Arm], conc: f32, rng: &mut impl Rng) -> Vec<f32> {
    if arms.len() < 2 {
        return vec![1.0; arms.len()];
    }
    let mut order: Vec<usize> = (0..arms.len()).collect();
    order.sort_by_cached_key(|&i| format!("{:?}", arms[i].label));
    let gamma = rand_distr::Gamma::new((conc / arms.len() as f32).max(1e-3), 1.0).expect("gamma");
    let mut eta = vec![0.0f32; arms.len()];
    for i in order {
        eta[i] = rng.sample(gamma);
    }
    let total: f32 = eta.iter().sum::<f32>().max(1e-12);
    eta.iter_mut().for_each(|e| *e /= total);
    eta
}

/// Mix Dirichlet noise into the priors of the available arms (root exploration, self-play).
pub(crate) fn add_root_noise(
    arms: &mut [Arm],
    avail: &[(usize, MoveChoice)],
    eps: f32,
    conc: f32,
    rng: &mut impl Rng,
) {
    if eps <= 0.0 || avail.len() < 2 {
        return;
    }
    let alpha = (conc / avail.len() as f32).max(1e-3);
    let gamma = rand_distr::Gamma::new(alpha, 1.0).expect("gamma");
    let draws: Vec<f32> = avail.iter().map(|_| rng.sample(gamma)).collect();
    let total: f32 = draws.iter().sum::<f32>().max(1e-12);
    let uniform = 1.0 / avail.len() as f32;
    for (&(i, _), d) in avail.iter().zip(&draws) {
        let p = if arms[i].prior >= 0.0 {
            arms[i].prior
        } else {
            uniform
        };
        arms[i].prior = (1.0 - eps) * p + eps * d / total;
    }
}

/// PUCT over the available arms: Q + c * P * sqrt(N) / (1 + n); N = visits of the available
/// arms (availability, as the UCB variant); unvisited arms get the mean Q of the visited ones.
pub(crate) fn select_puct(
    arms: &[Arm],
    avail: &[(usize, MoveChoice)],
    c: f32,
    ml: &MlParams,
) -> (usize, MoveChoice) {
    select_puct_with(arms, avail, c, ml, None)
}

/// `select_puct` with the priors from `priors` (by arm; the opponent's at the root: the current
/// world's own, `RootPriors`) instead of the arms'
pub(crate) fn select_puct_with(
    arms: &[Arm],
    avail: &[(usize, MoveChoice)],
    c: f32,
    ml: &MlParams,
    priors: Option<&[f32]>,
) -> (usize, MoveChoice) {
    let prior = |i: usize| match priors {
        Some(v) => v.get(i).copied().unwrap_or(-1.0),
        None => arms[i].prior,
    };
    let n: u32 = avail.iter().map(|&(i, _)| arms[i].visits).sum();
    let sq = (n.max(1) as f32).sqrt();
    let (mut qs, mut k) = (0.0f32, 0u32);
    for &(i, _) in avail {
        if arms[i].visits > 0 {
            qs += arms[i].mean();
            k += 1;
        }
    }
    let fpu = if k > 0 { qs / k as f32 } else { 0.5 };
    // the priors over the options here, renormalized (2026-10-21, the search review): an arm
    // with none (an option first seen in a later world) gets the known ones' mean, then all of
    // them sum to 1 over `avail` (before: a uniform 1 / n mixed with another world's softmax;
    // the root's marginal priors over the belief summed to less than 1 in a world)
    let (mut known, mut nk) = (0.0f32, 0u32);
    for &(i, _) in avail {
        if prior(i) >= 0.0 {
            known += prior(i);
            nk += 1;
        }
    }
    let stand_in = if nk > 0 { known / nk as f32 } else { 1.0 };
    let raw = |i: usize| if prior(i) >= 0.0 { prior(i) } else { stand_in };
    let z: f32 = avail.iter().map(|&(i, _)| raw(i)).sum();
    let uniform = 1.0 / avail.len() as f32;
    let ml_term = moves_left_term(arms, avail, ml);
    let mut best = avail[0];
    let mut best_u = f32::MIN;
    for &(i, mc) in avail {
        let a = &arms[i];
        let q = if a.visits > 0 { a.mean() } else { fpu };
        let p = if z > 0.0 { raw(i) / z } else { uniform };
        let mut u = q + c * p * sq / (1.0 + a.visits as f32);
        if let Some((sign, m_node)) = ml_term {
            if a.ml_n > 0 {
                let d = ml.slope * (a.ml_total / a.ml_n as f32 - m_node);
                u += sign * d.clamp(-ml.cap, ml.cap);
            }
        }
        if u > best_u {
            best_u = u;
            best = (i, mc);
        }
    }
    best
}

/// The moves-left term's common parts at a node for one side (`MlParams`): (-sign(2q - 1) x the
/// excess over the threshold, the node's mean moves left); None when off or not decided.
fn moves_left_term(
    arms: &[Arm],
    avail: &[(usize, MoveChoice)],
    ml: &MlParams,
) -> Option<(f32, f32)> {
    if ml.slope <= 0.0 {
        return None;
    }
    let (mut tot, mut vis, mut m_tot, mut m_n) = (0.0f32, 0u32, 0.0f32, 0u32);
    for &(i, _) in avail {
        let a = &arms[i];
        tot += a.total;
        vis += a.visits;
        m_tot += a.ml_total;
        m_n += a.ml_n;
    }
    if vis == 0 || m_n == 0 {
        return None;
    }
    let q = 2.0 * tot / vis as f32 - 1.0;
    if ml.winner_only && q < 0.0 {
        return None;
    }
    let excess = (q.abs() - ml.threshold) / (1.0 - ml.threshold).max(1e-6);
    (excess > 0.0).then(|| (-q.signum() * excess.min(1.0), m_tot / m_n as f32))
}

pub(crate) fn select(arms: &[Arm], avail: &[(usize, MoveChoice)], c: f32) -> (usize, MoveChoice) {
    let mut best = avail[0];
    let mut best_ucb = f32::MIN;
    for &(i, mc) in avail {
        let u = arms[i].ucb(c);
        if u > best_ucb {
            best_ucb = u;
            best = (i, mc);
        }
    }
    best
}

pub(crate) fn sample(outcomes: &[StateInstructions], rng: &mut impl Rng) -> usize {
    let total: f32 = outcomes.iter().map(|o| o.percentage.max(0.0)).sum();
    if total <= 0.0 {
        return 0;
    }
    let mut t = rng.random_range(0.0..total);
    for (i, o) in outcomes.iter().enumerate() {
        t -= o.percentage.max(0.0);
        if t <= 0.0 {
            return i;
        }
    }
    outcomes.len() - 1
}

impl Tree {
    pub fn new() -> Tree {
        Tree {
            nodes: vec![Node::default()],
            children: FxHashMap::default(),
            cache: FxHashMap::default(),
            root_opp: Vec::new(),
        }
    }

    fn iterate(
        &mut self,
        state: &mut State,
        world: u16,
        root_eval: f32,
        cfg: &Config,
        ctx: Option<&Context>,
        rng: &mut impl Rng,
    ) {
        let mut pc = PathCtx::new(ctx.filter(|_| cfg.tnet.is_some()), state);
        let mut path: Vec<(u32, u16, u16)> = Vec::with_capacity(16);
        let mut applied: Vec<Vec<Instruction>> = Vec::with_capacity(16); // below the root
        let mut root_step: Option<(u16, u16, usize)> = None; // cached root outcome applied
        let mut node: u32 = 0;
        // (side one's value, the moves-left estimate from the root if known)
        let (score, ml_leaf) = loop {
            let over = state.battle_is_over();
            if over != 0.0 && node != 0 {
                break (if over > 0.0 { 1.0 } else { 0.0 }, Some(pc.mains as f32));
            }
            let (o1, o2) = if node == 0 {
                state.root_get_all_options()
            } else {
                state.get_all_options()
            };
            let n = &mut self.nodes[node as usize];
            #[cfg(test)]
            if node != 0 {
                let ph = phase(state);
                match n.phase {
                    None => n.phase = Some(ph),
                    Some(p) => {
                        PHASE_SAME[(p == ph) as usize]
                            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    }
                }
            }
            let mut av1 = Vec::with_capacity(o1.len());
            for mc in o1 {
                let i = arm_index(&mut n.s1, label(&state.side_one, &mc));
                n.s1[i].avail += 1;
                av1.push((i, mc));
            }
            let mut av2 = Vec::with_capacity(o2.len());
            for mc in o2 {
                let i = arm_index(&mut n.s2, label(&state.side_two, &mc));
                n.s2[i].avail += 1;
                av2.push((i, mc));
            }
            if cfg.use_policy && !n.priors_set {
                if let (Some(tnet), Some(base)) = (&cfg.tnet, pc.base) {
                    let ev = crate::bsearch::evaluate_checked(state);
                    let lc = pc.context(base);
                    let cached = n.logits1.take().filter(|c| {
                        let fit = cached_logits_fit(c, state, &av1);
                        #[cfg(test)]
                        CACHE_FIT[fit as usize].fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        fit
                    });
                    let cached = cached.map(|c| c.0);
                    let need_own = cached.is_none();
                    let own = need_own.then(|| Input::new(state, &lc, false, ev));
                    let l1 = match cached {
                        Some(l) => l,
                        None => tnet.forward(own.as_ref().unwrap()).logits,
                    };
                    set_priors(&mut n.s1, &av1, &l1);
                    if cfg.policy_opponent {
                        let x2 = match &own {
                            Some(o) => o.flipped(state, &lc),
                            None => Input::new(state, &lc, true, ev),
                        };
                        set_priors(&mut n.s2, &av2, &tnet.forward(&x2).logits);
                    }
                }
                if node == 0 && cfg.root_noise_eps > 0.0 {
                    add_root_noise(
                        &mut n.s1,
                        &av1,
                        cfg.root_noise_eps,
                        cfg.root_noise_conc,
                        rng,
                    );
                    if cfg.policy_opponent {
                        let (e, c) = (cfg.root_noise_eps, cfg.root_noise_conc);
                        add_root_noise(&mut n.s2, &av2, e, c, rng);
                    }
                }
                n.priors_set = true;
            }
            let (i1, m1) = if cfg.use_policy {
                select_puct(&n.s1, &av1, cfg.c_puct, &cfg.ml)
            } else {
                select(&n.s1, &av1, cfg.c)
            };
            let (i2, m2) = if cfg.use_policy && cfg.policy_opponent {
                // (the root: this world's own priors for the opponent, `RootPriors`)
                let own = if node == 0 {
                    self.root_opp.get(world as usize).map(|v| v.as_slice())
                } else {
                    None
                };
                select_puct_with(&n.s2, &av2, cfg.c_puct, &cfg.ml, own)
            } else {
                select(&n.s2, &av2, cfg.c)
            };
            let depth = n.depth;
            if m1 == MoveChoice::None
                && m2 == MoveChoice::None
                && !crate::ismcts::someone_struggles(state)
            {
                break (leaf_value(state, root_eval, cfg, &pc), None);
            }
            pc.push(state, &m1, &m2);
            let (i1, i2) = (i1 as u16, i2 as u16);
            let branch = depth < cfg.branch_depth;
            #[cfg(test)]
            let before = state.serialize();
            if node == 0 && cfg.cache_root {
                let outcomes = self.cache.entry((node, i1, i2, world)).or_insert_with(|| {
                    generate_instructions_from_move_pair(state, &m1, &m2, branch)
                });
                let k = sample(outcomes, rng);
                state.apply_instructions(&outcomes[k].instruction_list);
                #[cfg(test)]
                check_stages(&before, &m1, &m2, &outcomes[k].instruction_list, state);
                pc.settle(&outcomes[k].instruction_list, state);
                root_step = Some((i1, i2, k));
            } else {
                let mut outcomes = generate_instructions_from_move_pair(state, &m1, &m2, branch);
                let k = sample(&outcomes, rng);
                let instructions = outcomes.swap_remove(k).instruction_list;
                state.apply_instructions(&instructions);
                #[cfg(test)]
                check_stages(&before, &m1, &m2, &instructions, state);
                pc.settle(&instructions, state);
                applied.push(instructions);
            }
            path.push((node, i1, i2));
            let sig = phase_sig(state, cfg);
            match self.children.get(&(node, i1, i2, sig)) {
                Some(&child) => node = child,
                None => {
                    let child = self.nodes.len() as u32;
                    self.nodes.push(Node {
                        depth: depth + 1,
                        ..Node::default()
                    });
                    self.children.insert((node, i1, i2, sig), child);
                    node = child;
                    let over = state.battle_is_over();
                    let mains = Some(pc.mains as f32);
                    break if over > 0.0 {
                        (1.0, mains)
                    } else if over < 0.0 {
                        (0.0, mains)
                    } else if let (true, Some(tnet), Some(base)) =
                        (cfg.use_policy, &cfg.tnet, pc.base)
                    {
                        // one forward pass: the leaf value and the new node's own priors
                        let x = Input::new(
                            state,
                            &pc.context(base),
                            false,
                            crate::bsearch::evaluate_checked(state),
                        );
                        let out = tnet.forward(&x);
                        self.nodes[child as usize].logits1 =
                            Some(Box::new((out.logits, state.side_one.active_index)));
                        let ml = out.turns.map(|t| pc.mains as f32 + t);
                        (1.0 / (1.0 + (-out.value).exp()), ml)
                    } else {
                        (leaf_value(state, root_eval, cfg, &pc), None)
                    };
                }
            }
        };
        self.nodes[node as usize].visits += 1;
        for &(nd, i1, i2) in path.iter().rev() {
            let n = &mut self.nodes[nd as usize];
            n.visits += 1;
            let a1 = &mut n.s1[i1 as usize];
            a1.visits += 1;
            a1.total += score;
            if let Some(m) = ml_leaf {
                a1.ml_total += m;
                a1.ml_n += 1;
            }
            let a2 = &mut n.s2[i2 as usize];
            a2.visits += 1;
            a2.total += 1.0 - score;
            if let Some(m) = ml_leaf {
                a2.ml_total += m;
                a2.ml_n += 1;
            }
        }
        for ins in applied.iter().rev() {
            state.reverse_instructions(ins);
        }
        if let Some((i1, i2, k)) = root_step {
            let outcomes = &self.cache[&(0, i1, i2, world)];
            state.reverse_instructions(&outcomes[k].instruction_list);
        }
    }
}

impl Default for Tree {
    fn default() -> Self {
        Tree::new()
    }
}

/// The root's priors from the network in every world (`RootPriors`: ours their mean, the
/// opponent's each world's own) and its noise; nothing without the network's policy.
fn root_priors_over_worlds(
    tree: &mut Tree,
    worlds: &[State],
    ctxs: &[Context],
    cfg: &Config,
    rng: &mut StdRng,
) {
    let Some(tnet) = cfg.tnet.as_ref().filter(|_| cfg.use_policy) else {
        return;
    };
    if ctxs.len() != worlds.len() || worlds.is_empty() {
        return;
    }
    let root = &mut tree.nodes[0];
    let mut rp = RootPriors::default();
    for (state, ctx) in worlds.iter().zip(ctxs) {
        let (o1, o2) = state.root_get_all_options();
        let av1: Vec<(usize, MoveChoice)> = o1
            .into_iter()
            .map(|mc| (arm_index(&mut root.s1, label(&state.side_one, &mc)), mc))
            .collect();
        let av2: Vec<(usize, MoveChoice)> = o2
            .into_iter()
            .map(|mc| (arm_index(&mut root.s2, label(&state.side_two, &mc)), mc))
            .collect();
        let lc = PathCtx::new(Some(ctx), state).context(ctx);
        let own = Input::new(state, &lc, false, crate::bsearch::evaluate_checked(state));
        let p1 = prior_probs(&av1, &tnet.forward(&own).logits);
        let p2 = cfg
            .policy_opponent
            .then(|| prior_probs(&av2, &tnet.forward(&own.flipped(state, &lc)).logits));
        rp.add(&av1, &p1, &av2, p2.as_deref());
    }
    rp.finish(root, &mut tree.root_opp, cfg, rng);
}

/// Search over the given worlds (they must share our side; the opponent's hidden details may
/// differ). Stops after `duration` or, when `max_iterations` > 0, after that many iterations;
/// the root's evaluation in every world counts in the time (2026-10-22, the search review).
/// Every world's state is restored before returning.
pub fn search(
    worlds: &mut [State],
    ctxs: &[Context],
    duration: Duration,
    max_iterations: u32,
    cfg: &Config,
    seed: Option<u64>,
) -> SearchResult {
    assert!(
        cfg.tnet.is_none() || ctxs.len() == worlds.len(),
        "one context per world"
    );
    let mut rng = match seed {
        Some(s) => StdRng::seed_from_u64(s),
        None => StdRng::from_os_rng(),
    };
    let start = Instant::now();
    let root_evals: Vec<f32> = worlds.iter().map(evaluate).collect();
    let mut tree = Tree::new();
    root_priors_over_worlds(&mut tree, worlds, ctxs, cfg, &mut rng);
    let mut it: u32 = 0;
    loop {
        // (the time checked every 16 iterations: every 256 overran a 200 ms budget by 60-70 ms
        // with the network, 2026-10-22)
        for _ in 0..16 {
            let w = (it as usize) % worlds.len();
            tree.iterate(
                &mut worlds[w],
                w as u16,
                root_evals[w],
                cfg,
                ctxs.get(w),
                &mut rng,
            );
            it += 1;
            if max_iterations > 0 && it >= max_iterations {
                break;
            }
        }
        if max_iterations > 0 {
            if it >= max_iterations {
                break;
            }
        } else if start.elapsed() >= duration {
            break;
        }
    }
    let root = &tree.nodes[0];
    SearchResult {
        s1: root
            .s1
            .iter()
            .map(|a| (a.label, a.visits, a.mean()))
            .collect(),
        // (its arms back up the opponent's value: 1 - ours)
        s2: root
            .s2
            .iter()
            .map(|a| {
                (
                    a.label,
                    a.visits,
                    if a.visits > 0 { 1.0 - a.mean() } else { 0.0 },
                )
            })
            .collect(),
        s1_priors: root.s1.iter().map(|a| (a.label, a.prior)).collect(),
        variations: if cfg.pv.0 > 0 {
            variations(&tree, cfg.pv)
        } else {
            Vec::new()
        },
        iterations: it,
        nodes: tree.nodes.len(),
        max_depth: tree.nodes.iter().map(|n| n.depth).max().unwrap_or(0),
    }
}

/// Root-parallel search: `threads` independent trees over (copies of) all worlds with
/// different seeds; our root statistics are merged by label (visits summed, means weighted).
pub fn search_parallel(
    worlds: &[State],
    ctxs: &[Context],
    duration: Duration,
    max_iterations: u32,
    cfg: &Config,
    seed: Option<u64>,
    threads: usize,
) -> SearchResult {
    let threads = threads.max(1);
    let per_thread = if max_iterations > 0 {
        max_iterations.div_ceil(threads as u32)
    } else {
        0
    };
    let results: Vec<SearchResult> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let mut own: Vec<State> = worlds.to_vec();
                let seed = seed.map(|s| s.wrapping_add(t as u64 * 0x9E37_79B9));
                scope.spawn(move || search(&mut own, ctxs, duration, per_thread, cfg, seed))
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });
    SearchResult {
        s1: merge_root(results.iter().map(|r| &r.s1)),
        s2: merge_root(results.iter().map(|r| &r.s2)),
        // (one tree's: the one that ran most)
        variations: results
            .iter()
            .max_by_key(|r| r.iterations)
            .map(|r| r.variations.clone())
            .unwrap_or_default(),
        s1_priors: results
            .first()
            .map(|r| r.s1_priors.clone())
            .unwrap_or_default(),
        iterations: results.iter().map(|r| r.iterations).sum(),
        nodes: results.iter().map(|r| r.nodes).sum(),
        max_depth: results.iter().map(|r| r.max_depth).max().unwrap_or(0),
    }
}

/// Our root option in `state` for a label (our side is the same in every world).
/// One step of a principal variation: the joint action (our label, theirs: None when that side
/// does not choose -- the other's switch after a faint), the visits of the node it leads to, and
/// our winning chance there (the node's backed-up mean; None when it was never expanded).
#[derive(Clone, Debug)]
pub struct PvStep {
    pub ours: Label,
    pub theirs: Label,
    pub visits: u32,
    pub value: Option<f32>,
}

/// The principal variations of a tree, as KataGo shows its variations (2026-10-30, game reviews):
/// for each of our `pv.0` most visited root options and each of the opponent's `pv.1` most
/// visited replies to it (the joint children's visits), the most visited joint action at every
/// node below, `pv.2` steps in all. Open loop: a node stands for every chance outcome of its
/// joint action (a KO and no KO share it unless `phase_key`), so a line is the search's main
/// expectation, not one game.
pub fn variations(tree: &Tree, pv: (usize, usize, usize)) -> Vec<Vec<PvStep>> {
    let mut kids: FxHashMap<u32, Vec<(u16, u16, u32)>> = FxHashMap::default();
    for (&(parent, i1, i2, _), &child) in &tree.children {
        kids.entry(parent).or_default().push((i1, i2, child));
    }
    let value = |c: u32| {
        let n = &tree.nodes[c as usize];
        let v: u32 = n.s1.iter().map(|a| a.visits).sum();
        (v > 0).then(|| n.s1.iter().map(|a| a.total).sum::<f32>() / v as f32)
    };
    let step = |node: u32, i1: u16, i2: u16, child: u32| {
        let n = &tree.nodes[node as usize];
        PvStep {
            ours: n.s1[i1 as usize].label,
            theirs: n.s2[i2 as usize].label,
            visits: tree.nodes[child as usize].visits,
            value: value(child),
        }
    };
    let by_visits = |v: &mut Vec<(u16, u16, u32)>| {
        v.sort_by_key(|&(_, _, c)| std::cmp::Reverse(tree.nodes[c as usize].visits))
    };
    let mut ours: Vec<usize> = (0..tree.nodes[0].s1.len()).collect();
    ours.sort_by_key(|&i| std::cmp::Reverse(tree.nodes[0].s1[i].visits));
    let mut out = Vec::new();
    for &i1 in ours.iter().take(pv.0) {
        let mut first: Vec<(u16, u16, u32)> = kids
            .get(&0)
            .map(|v| v.iter().filter(|k| k.0 as usize == i1).copied().collect())
            .unwrap_or_default();
        by_visits(&mut first);
        for &(a, b, c) in first.iter().take(pv.1) {
            let mut line = vec![step(0, a, b, c)];
            let mut node = c;
            while line.len() < pv.2 {
                let Some(mut next) = kids.get(&node).cloned() else {
                    break;
                };
                by_visits(&mut next);
                let (a, b, c) = next[0];
                line.push(step(node, a, b, c));
                node = c;
            }
            out.push(line);
        }
    }
    out
}

/// Root statistics of independent trees merged by label: visits summed, means weighted by them.
fn merge_root<'a>(
    runs: impl Iterator<Item = &'a Vec<(Label, u32, f32)>>,
) -> Vec<(Label, u32, f32)> {
    let mut merged: Vec<(Label, u32, f32)> = Vec::new();
    for run in runs {
        for &(l, visits, mean) in run {
            match merged.iter_mut().find(|m| m.0 == l) {
                Some(m) => {
                    let total = m.1 + visits;
                    if total > 0 {
                        m.2 = (m.2 * m.1 as f32 + mean * visits as f32) / total as f32;
                    }
                    m.1 = total;
                }
                None => merged.push((l, visits, mean)),
            }
        }
    }
    merged
}

pub fn our_choice(state: &State, l: Label) -> Option<MoveChoice> {
    let (o1, _) = state.root_get_all_options();
    o1.into_iter().find(|mc| label(&state.side_one, mc) == l)
}

/// The opponent's move choice for a label in this world (its moves differ between worlds:
/// None if this world's opponent does not have the move).
pub fn their_choice(state: &State, l: Label) -> Option<MoveChoice> {
    let (_, o2) = state.root_get_all_options();
    o2.into_iter().find(|mc| label(&state.side_two, mc) == l)
}

/// The causality check of the search's tree (doc/state-diff.md plan B): the decision step a
/// descent records for the joint action (`m1`, `m2`) in `state`, for each of its chance outcomes
/// -- (probability, the step, main steps completed, a turn still open). The step is what the
/// network reads below the root; scripts/check_tree_history.py compares it with the step the
/// log gives (the replays' history).
pub(crate) fn tree_step_outcomes(
    state: &State,
    m1: &MoveChoice,
    m2: &MoveChoice,
    branch: bool,
) -> Vec<(f32, Step, i32, bool)> {
    let base = Context {
        reveal: [0; 12],
        rating: [0, 0],
        turn: 1,
        history: Vec::new(),
        full: false,
        post: Vec::new(),
    };
    let mut st = state.clone();
    let outcomes = generate_instructions_from_move_pair(&mut st, m1, m2, branch);
    let total: f32 = outcomes.iter().map(|o| o.percentage.max(0.0)).sum();
    let mut out = Vec::with_capacity(outcomes.len());
    for o in &outcomes {
        let mut path = PathCtx::new(Some(&base), &st);
        path.push(&st, m1, m2);
        st.apply_instructions(&o.instruction_list);
        path.settle(&o.instruction_list, &st);
        let step = path.steps.last().copied().unwrap_or_default();
        out.push((
            o.percentage.max(0.0) / total.max(1e-9),
            step,
            path.mains,
            path.open,
        ));
        st.reverse_instructions(&o.instruction_list);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use poke_engine::state::PokemonMoveIndex;

    const FIXTURE: &str = include_str!("../../../tests/fixtures/engine_state_6v6.txt");

    fn fixture() -> State {
        State::deserialize(FIXTURE.lines().next().unwrap())
    }

    /// a second world: the opponent's active mon has a different first move
    fn variant(mv: Choices) -> State {
        let mut s = fixture();
        s.side_two.get_active().moves[&PokemonMoveIndex::M0].id = mv;
        s
    }

    /// side one (fast, Tackle) KOs side two's active (1 HP, its Ice Beam never comes)
    fn ko_first() -> State {
        use poke_engine::engine::abilities::Abilities;
        use poke_engine::engine::items::Items;
        use poke_engine::state::PokemonType;
        let mut s = fixture();
        let a = s.side_one.get_active();
        a.speed = 999;
        a.moves[&PokemonMoveIndex::M0].id = Choices::TACKLE;
        let b = s.side_two.get_active();
        (b.hp, b.speed, b.ability, b.item) = (1, 1, Abilities::NONE, Items::NONE);
        b.types = (PokemonType::NORMAL, PokemonType::TYPELESS);
        b.moves[&PokemonMoveIndex::M0].id = Choices::ICEBEAM;
        s.side_one.force_switch = false;
        s.side_two.force_switch = false;
        s
    }

    /// 2026-10-20: a move that waits for the foe's pivot switch is saved by an instruction: the
    /// generation leaves the state as it was (it was set on the state directly, outside the
    /// instructions -- a search's world kept it after every branch, a stale saved move that a
    /// later forced switch (Eject Pack on a switch-in) offered as the only option, or none: an
    /// empty option list, `select_puct` panicked; 51 searches in a 1,200-game A/B)
    #[test]
    fn a_waiting_move_is_saved_by_an_instruction() {
        use poke_engine::choices::MOVES;
        let mut s = fixture();
        for (side, id, speed) in [
            (&mut s.side_one, Choices::TACKLE, 1),
            (&mut s.side_two, Choices::UTURN, 999),
        ] {
            let a = side.get_active();
            a.speed = speed;
            a.moves[&PokemonMoveIndex::M0].id = id;
            a.moves[&PokemonMoveIndex::M0].choice = MOVES.get(&id).unwrap().clone();
            side.force_switch = false;
            side.switch_out_move_second_saved_move = Choices::NONE;
        }
        let before = s.serialize();
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        let outcomes = generate_instructions_from_move_pair(&mut s, &m, &m, false);
        assert_eq!(
            s.serialize(),
            before,
            "the generation left the state changed"
        );
        assert_eq!(
            s.side_one.switch_out_move_second_saved_move,
            Choices::NONE,
            "saved move leaked"
        );
        let pivots: Vec<_> = outcomes
            .iter()
            .filter(|o| {
                o.instruction_list
                    .iter()
                    .any(|i| matches!(i, Instruction::ToggleSideTwoForceSwitch))
            })
            .collect();
        assert!(!pivots.is_empty(), "U-turn switches side two out");
        for o in pivots {
            s.apply_instructions(&o.instruction_list);
            assert_eq!(
                s.side_one.switch_out_move_second_saved_move,
                Choices::TACKLE
            );
            let (o1, _) = s.get_all_options();
            assert!(!o1.is_empty());
            s.reverse_instructions(&o.instruction_list);
            assert_eq!(s.serialize(), before);
            assert_eq!(s.side_one.switch_out_move_second_saved_move, Choices::NONE);
        }
        // the follow-up (side two's replacement, our move after it): nothing saved after it
        s.apply_instructions(
            &outcomes
                .iter()
                .find(|o| {
                    o.instruction_list
                        .iter()
                        .any(|i| matches!(i, Instruction::ToggleSideTwoForceSwitch))
                })
                .unwrap()
                .instruction_list
                .clone(),
        );
        let (o1, o2) = s.get_all_options();
        let sw = o2
            .iter()
            .find(|c| matches!(c, MoveChoice::Switch(_)))
            .copied()
            .unwrap();
        let follow = generate_instructions_from_move_pair(&mut s, &o1[0], &sw, false);
        for o in &follow {
            s.apply_instructions(&o.instruction_list);
            let (n1, n2) = s.get_all_options();
            assert!(!n1.is_empty() && !n2.is_empty());
            s.reverse_instructions(&o.instruction_list);
        }
    }

    /// the A/B's case: a stale saved move (a mon that has left) and a turn-start switch-in into
    /// Sticky Web with an Eject Pack: the foe's forced switch, side one with nothing waiting --
    /// no action (it was offered the stale move: none, an empty option list)
    #[test]
    fn a_stale_saved_move_is_cleared() {
        use poke_engine::engine::items::Items;
        use poke_engine::state::PokemonType;
        let mut s = fixture();
        s.side_one.force_switch = false;
        s.side_two.force_switch = false;
        s.side_one.switch_out_move_second_saved_move = Choices::STONEAXE; // no mon of its has it
        s.side_two.side_conditions.sticky_web = 1;
        let a2 = s.side_two.active_index as usize;
        let j = (0..6)
            .find(|&j| j != a2 && s.side_two.pokemon.pkmn[j].hp > 0)
            .unwrap();
        let p = &mut s.side_two.pokemon.pkmn[j];
        p.item = Items::EJECTPACK;
        p.types.0 = PokemonType::NORMAL; // grounded
        p.types.1 = PokemonType::TYPELESS;
        p.ability = poke_engine::engine::abilities::Abilities::NONE;
        let a1 = s.side_one.active_index as usize;
        let k = (0..6)
            .find(|&k| k != a1 && s.side_one.pokemon.pkmn[k].hp > 0)
            .unwrap();
        let (m1, m2) = (
            MoveChoice::Switch(PokemonIndex::deserialize(&k.to_string())),
            MoveChoice::Switch(PokemonIndex::deserialize(&j.to_string())),
        );
        let before = s.serialize();
        let outcomes = generate_instructions_from_move_pair(&mut s, &m1, &m2, false);
        assert_eq!(s.serialize(), before);
        let mut ejected = 0;
        for o in &outcomes {
            s.apply_instructions(&o.instruction_list);
            if s.side_two.force_switch {
                ejected += 1;
                let (o1, o2) = s.get_all_options();
                assert_eq!(o1, vec![MoveChoice::None], "side one: no action");
                assert!(!o2.is_empty());
            }
            s.reverse_instructions(&o.instruction_list);
        }
        assert!(ejected > 0, "the Eject Pack went off");
    }

    /// Random playouts from the states of a file (one per line, ALPHA_FUZZ_STATES): every move
    /// pair's generation leaves the state unchanged, no side is left without an option, and
    /// every outcome keeps the stat stages within -6..6 (the engine's evaluation panics past
    /// them: a search fell back, 2026-10-21).
    /// `cargo test --release fuzz_generation -- --ignored --nocapture`
    #[test]
    #[ignore]
    fn fuzz_generation() {
        use rand::{rngs::StdRng, Rng, SeedableRng};
        let path = std::env::var("ALPHA_FUZZ_STATES").expect("ALPHA_FUZZ_STATES");
        let text = std::fs::read_to_string(path).unwrap();
        let mut rng = StdRng::seed_from_u64(0);
        let (mut steps, mut leaks, mut empty, mut boosts, mut unreversed) =
            (0usize, 0usize, 0usize, 0usize, 0usize);
        let in_range = |s: &State| {
            [&s.side_one, &s.side_two].iter().all(|sd| {
                [
                    sd.attack_boost,
                    sd.defense_boost,
                    sd.special_attack_boost,
                    sd.special_defense_boost,
                    sd.speed_boost,
                    sd.accuracy_boost,
                    sd.evasion_boost,
                ]
                .iter()
                .all(|b| (-6..=6).contains(b))
            })
        };
        for line in text.lines().filter(|l| !l.is_empty()) {
            let mut s = State::deserialize(line);
            for _ in 0..12 {
                if s.battle_is_over() != 0.0 {
                    break;
                }
                let (o1, o2) = s.get_all_options();
                if o1.is_empty() || o2.is_empty() {
                    empty += 1;
                    if empty <= 3 {
                        eprintln!("EMPTY {}", s.serialize());
                    }
                    break;
                }
                let (m1, m2) = (
                    o1[rng.random_range(0..o1.len())],
                    o2[rng.random_range(0..o2.len())],
                );
                let before = s.serialize();
                let outcomes = generate_instructions_from_move_pair(&mut s, &m1, &m2, false);
                steps += 1;
                if s.serialize() != before {
                    leaks += 1;
                    if leaks <= 3 {
                        eprintln!(
                            "LEAK {m1:?} {m2:?}\nBEFORE {before}\nAFTER  {}",
                            s.serialize()
                        );
                    }
                    s = State::deserialize(&before);
                }
                for o in &outcomes {
                    s.apply_instructions(&o.instruction_list);
                    if !in_range(&s) {
                        boosts += 1;
                        if boosts <= 5 {
                            eprintln!(
                                "BOOST {m1:?} {m2:?}\nBEFORE {before}\nINSTRUCTIONS {:?}",
                                o.instruction_list
                            );
                        }
                    }
                    s.reverse_instructions(&o.instruction_list);
                    // (an outcome applied then reversed: the state again -- the search does it
                    // every iteration)
                    if s.serialize() != before {
                        unreversed += 1;
                        if unreversed <= 5 {
                            eprintln!("UNREVERSED {m1:?} {m2:?}\nBEFORE {before}\nAFTER  {}\nINSTRUCTIONS {:?}", s.serialize(), o.instruction_list);
                        }
                        s = State::deserialize(&before);
                    }
                }
                let k = rng.random_range(0..outcomes.len());
                s.apply_instructions(&outcomes[k].instruction_list);
            }
        }
        eprintln!("steps {steps} leaks {leaks} empty {empty} boosts out of range {boosts} not reversed {unreversed}");
        assert_eq!((leaks, empty, boosts, unreversed), (0, 0, 0, 0));
    }

    /// The stat stages at their limits (+6 / -6 on both actives) and every move pair: no outcome
    /// leaves one past them (`fuzz_generation`'s check where random playouts rarely get).
    /// `ALPHA_FUZZ_STATES=<file> cargo test --release fuzz_stage_limits -- --ignored --nocapture`
    #[test]
    #[ignore]
    fn fuzz_stage_limits() {
        let path = std::env::var("ALPHA_FUZZ_STATES").expect("ALPHA_FUZZ_STATES");
        let text = std::fs::read_to_string(path).unwrap();
        let (mut pairs, mut bad) = (0usize, 0usize);
        let mut seen = std::collections::BTreeSet::new();
        for line in text.lines().filter(|l| !l.is_empty()).take(3000) {
            for v in [6i8, -6] {
                let mut s = State::deserialize(line);
                if s.battle_is_over() != 0.0 {
                    continue;
                }
                for sd in [&mut s.side_one, &mut s.side_two] {
                    sd.attack_boost = v;
                    sd.defense_boost = v;
                    sd.special_attack_boost = v;
                    sd.special_defense_boost = v;
                    sd.speed_boost = v;
                    sd.accuracy_boost = v;
                    sd.evasion_boost = v;
                }
                let (o1, o2) = s.get_all_options();
                for m1 in &o1 {
                    for m2 in &o2 {
                        let outcomes = generate_instructions_from_move_pair(&mut s, m1, m2, false);
                        pairs += 1;
                        for o in &outcomes {
                            s.apply_instructions(&o.instruction_list);
                            let out = [&s.side_one, &s.side_two].iter().any(|sd| {
                                [
                                    sd.attack_boost,
                                    sd.defense_boost,
                                    sd.special_attack_boost,
                                    sd.special_defense_boost,
                                    sd.speed_boost,
                                    sd.accuracy_boost,
                                    sd.evasion_boost,
                                ]
                                .iter()
                                .any(|b| !(-6..=6).contains(b))
                            });
                            if out {
                                bad += 1;
                                let key = format!("{m1:?} / {m2:?}");
                                if seen.insert(key.clone()) && seen.len() <= 12 {
                                    eprintln!(
                                        "STAGE {v}: {key}\n  {:?}",
                                        o.instruction_list
                                            .iter()
                                            .filter(|i| format!("{i:?}").contains("Boost"))
                                            .collect::<Vec<_>>()
                                    );
                                }
                            }
                            s.reverse_instructions(&o.instruction_list);
                        }
                    }
                }
            }
        }
        eprintln!(
            "move pairs {pairs}, outcomes past the stages' limits {bad} ({} kinds)",
            seen.len()
        );
        assert_eq!(bad, 0);
    }

    /// The stages near their limits with the abilities that change stage changes (Contrary,
    /// Simple, ...) and the moves that change them a lot: no outcome past -6..6 (the search's
    /// evaluation panicked on a +7, 2026-10-21; `fuzz_stage_limits` has no such sets)
    #[test]
    fn stage_changes_stay_within_the_limits() {
        use poke_engine::choices::Choices;
        use poke_engine::engine::abilities::Abilities;
        let base = State::deserialize(
            include_str!("../../../tests/fixtures/engine_state_6v6.txt")
                .lines()
                .next()
                .unwrap(),
        );
        let mut bad = vec![];
        let abilities = [
            Abilities::CONTRARY,
            Abilities::SIMPLE,
            Abilities::NONE,
            Abilities::DEFIANT,
            Abilities::COMPETITIVE,
            Abilities::MOODY,
            Abilities::SPEEDBOOST,
            Abilities::ANGERPOINT,
            Abilities::BERSERK,
            Abilities::WEAKARMOR,
            Abilities::STAMINA,
            Abilities::MOXIE,
            Abilities::BEASTBOOST,
            Abilities::JUSTIFIED,
            Abilities::RATTLED,
            Abilities::STEAMENGINE,
            Abilities::WATERCOMPACTION,
            Abilities::MIRRORARMOR,
            Abilities::OPPORTUNIST,
            Abilities::GUARDDOG,
        ];
        let moves = [
            Choices::LEAFSTORM,
            Choices::DRACOMETEOR,
            Choices::OVERHEAT,
            Choices::CLOSECOMBAT,
            Choices::SHELLSMASH,
            Choices::BELLYDRUM,
            Choices::SWORDSDANCE,
            Choices::NASTYPLOT,
            Choices::QUIVERDANCE,
            Choices::CURSE,
            Choices::SUPERPOWER,
            Choices::MAKEITRAIN,
            Choices::SPINOUT,
            Choices::FILLETAWAY,
            Choices::CLANGOROUSSOUL,
            Choices::ACUPRESSURE,
            Choices::GROWTH,
            Choices::TAILGLOW,
            Choices::GEOMANCY,
            Choices::SNARL,
            Choices::PARTINGSHOT,
            Choices::MEMENTO,
            Choices::CHARM,
            Choices::SCREECH,
            Choices::METALSOUND,
            Choices::FAKETEARS,
            Choices::FEATHERDANCE,
            Choices::TICKLE,
            Choices::NOBLEROAR,
            Choices::BABYDOLLEYES,
            Choices::PSYCHUP,
            Choices::SPECTRALTHIEF,
            Choices::POWERTRIP,
            Choices::STOREDPOWER,
            Choices::TOPSYTURVY,
            Choices::HAZE,
            Choices::DEFOG,
            Choices::SCALESHOT,
            Choices::TRIPLEARROWS,
            Choices::ROCKSMASH,
            Choices::FLAMECHARGE,
            Choices::TRAILBLAZE,
            Choices::TORCHSONG,
            Choices::POWERUPPUNCH,
            Choices::DIAMONDSTORM,
            Choices::METEORMASH,
            Choices::ARMORCANNON,
            Choices::HEADLONGRUSH,
            Choices::VCREATE,
            Choices::HAMMERARM,
            Choices::ICEHAMMER,
            Choices::LUNGE,
            Choices::TROPKICK,
            Choices::SPIRITBREAK,
            Choices::MYSTICALFIRE,
            Choices::STRUGGLEBUG,
            Choices::ELECTROWEB,
            Choices::ICYWIND,
            Choices::BULLDOZE,
            Choices::ROCKTOMB,
            Choices::SKITTERSMACK,
            Choices::BITTERMALICE,
            Choices::CHILLINGWATER,
            Choices::POUNCE,
            Choices::FIRELASH,
            Choices::THUNDEROUSKICK,
            Choices::GRAVAPPLE,
            Choices::BREAKINGSWIPE,
            Choices::CRUNCH,
            Choices::SHADOWBALL,
            Choices::MOONBLAST,
            Choices::ENERGYBALL,
            Choices::FOCUSBLAST,
            Choices::EARTHPOWER,
            Choices::PSYCHIC,
            Choices::IRONTAIL,
            Choices::BUGBUZZ,
            Choices::LIQUIDATION,
        ];
        let names = |s: &State| {
            [&s.side_one, &s.side_two].map(|sd| {
                [
                    sd.attack_boost,
                    sd.defense_boost,
                    sd.special_attack_boost,
                    sd.special_defense_boost,
                    sd.speed_boost,
                    sd.accuracy_boost,
                    sd.evasion_boost,
                ]
            })
        };
        for &ab in &abilities {
            for &ab2 in &[
                Abilities::NONE,
                Abilities::CONTRARY,
                Abilities::SIMPLE,
                Abilities::DEFIANT,
                Abilities::COMPETITIVE,
                Abilities::MIRRORARMOR,
            ] {
                for v in [-6i8, -5, 5, 6] {
                    for &mv in &moves {
                        let mut s = base.clone();
                        for sd in [&mut s.side_one, &mut s.side_two] {
                            sd.attack_boost = v;
                            sd.defense_boost = v;
                            sd.special_attack_boost = v;
                            sd.special_defense_boost = v;
                            sd.speed_boost = v;
                            sd.accuracy_boost = v;
                            sd.evasion_boost = v;
                        }
                        s.side_one.get_active().ability = ab;
                        s.side_one.get_active().hp = s.side_one.get_active().maxhp;
                        s.side_two.get_active().ability = ab2;
                        let slot = &mut s.side_one.get_active().moves.m0;
                        slot.id = mv;
                        slot.choice = poke_engine::choices::MOVES.get(&mv).unwrap().clone();
                        slot.disabled = false;
                        slot.pp = 8;
                        let (o1, o2) = s.get_all_options();
                        let m1 = o1
                            .iter()
                            .find(|m| matches!(m, MoveChoice::Move(PokemonMoveIndex::M0)))
                            .cloned();
                        let Some(m1) = m1 else { continue };
                        for m2 in o2.iter().take(3) {
                            let outs = generate_instructions_from_move_pair(&mut s, &m1, m2, false);
                            for o in &outs {
                                s.apply_instructions(&o.instruction_list);
                                if names(&s).iter().flatten().any(|b| !(-6..=6).contains(b))
                                    && bad.len() < 20
                                {
                                    bad.push(format!(
                                        "{ab:?} vs {ab2:?} at {v}: {mv:?} / {m2:?} -> {:?}",
                                        names(&s)
                                    ));
                                }
                                s.reverse_instructions(&o.instruction_list);
                            }
                        }
                    }
                }
            }
        }
        assert!(bad.is_empty(), "{}", bad.join("\n"));
    }

    #[test]
    fn a_move_never_used_is_not_history_or_revealed() {
        // 2026-10-14 (external review): the chosen move was recorded as used before the turn
        let base = Context {
            reveal: [0; 12],
            rating: [0, 0],
            turn: 10,
            history: vec![],
            ..Default::default()
        };
        let mut state = ko_first();
        let mut pc = PathCtx::new(Some(&base), &state);
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        pc.push(&state, &m, &m);
        let outcomes = generate_instructions_from_move_pair(&mut state, &m, &m, false);
        assert_eq!(outcomes.len(), 1);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        let ctx = pc.context(&base);
        let step = ctx.history.last().unwrap();
        assert_eq!(step.one.kind, 1, "our Tackle was used");
        assert!(
            step.two.kind == 0 && step.two.fainted_first,
            "theirs never came: {step:?}"
        );
        let theirs = 6 + state.side_two.active_index as usize;
        assert_eq!(ctx.reveal[theirs] & (1 << 4), 0, "Ice Beam revealed");
        assert_ne!(
            ctx.reveal[state.side_one.active_index as usize] & (1 << 4),
            0
        );
        // (2026-10-22 review: the replacement is chosen in the same turn -- the next only after it)
        assert_eq!(ctx.turn, 10);
        // the faint's forced switch: the same turn (the engine switches a side whose active has
        // no HP although `force_switch` is false)
        assert!(!state.side_two.force_switch && state.side_two.get_active_immutable().hp <= 0);
        let (o1, o2) = state.get_all_options();
        pc.push(&state, &o1[0], &o2[0]);
        let outcomes = generate_instructions_from_move_pair(&mut state, &o1[0], &o2[0], false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        assert_eq!(pc.context(&base).turn, 11);
    }

    /// 2026-10-23 review: the search started at a forced switch (a faint's replacement in turn
    /// 10, a U-turn's switch-in): once the switch is done, the context is turn 11 (was 10, and
    /// every node below one turn behind)
    #[test]
    fn a_forced_root_ends_its_turn() {
        let base = Context {
            reveal: [0; 12],
            rating: [0, 0],
            turn: 10,
            history: vec![],
            ..Default::default()
        };
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        // the faint's replacement
        let mut state = ko_first();
        let outcomes = generate_instructions_from_move_pair(&mut state, &m, &m, false);
        state.apply_instructions(&outcomes[0].instruction_list);
        assert!(state.side_two.get_active_immutable().hp <= 0);
        let mut pc = PathCtx::new(Some(&base), &state);
        assert_eq!(pc.context(&base).turn, 10, "the root: still its turn");
        let (o1, o2) = state.get_all_options();
        pc.push(&state, &o1[0], &o2[0]);
        let outcomes = generate_instructions_from_move_pair(&mut state, &o1[0], &o2[0], false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        assert_eq!(pc.context(&base).turn, 11);
        // the next main step: turn 12 once over
        let (o1, o2) = state.get_all_options();
        pc.push(&state, &o1[0], &o2[0]);
        let outcomes = generate_instructions_from_move_pair(&mut state, &o1[0], &o2[0], false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        if !(forced(&state.side_one) || forced(&state.side_two)) {
            assert_eq!(pc.context(&base).turn, 12);
        }
        // a U-turn's switch-in, the foe's move saved
        let mut state = ko_first();
        state.side_one.get_active().moves[&PokemonMoveIndex::M0].id = Choices::UTURN;
        state.side_one.get_active().moves[&PokemonMoveIndex::M0].choice =
            poke_engine::choices::MOVES
                .get(&Choices::UTURN)
                .unwrap()
                .clone();
        let foe = state.side_two.get_active();
        (foe.hp, foe.maxhp) = (400, 400);
        let outcomes = generate_instructions_from_move_pair(&mut state, &m, &m, false);
        state.apply_instructions(&outcomes[0].instruction_list);
        assert!(state.side_one.force_switch);
        let mut pc = PathCtx::new(Some(&base), &state);
        let (o1, o2) = state.get_all_options();
        pc.push(&state, &o1[0], &o2[0]);
        let outcomes = generate_instructions_from_move_pair(&mut state, &o1[0], &o2[0], false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        assert_eq!(pc.context(&base).turn, 11);
    }

    /// 2026-10-22 review: our U-turn first, the foe's move saved for after our switch-in: in
    /// the history that step has no action of the foe yet (the log so far; it read as prevented)
    /// and its move is unrevealed; the switch's step has the move
    #[test]
    fn a_move_after_our_pivot_is_the_switch_steps() {
        let base = Context {
            reveal: [0; 12],
            rating: [0, 0],
            turn: 10,
            history: vec![],
            ..Default::default()
        };
        let mut state = ko_first();
        state.side_one.get_active().moves[&PokemonMoveIndex::M0].id = Choices::UTURN;
        state.side_one.get_active().moves[&PokemonMoveIndex::M0].choice =
            poke_engine::choices::MOVES
                .get(&Choices::UTURN)
                .unwrap()
                .clone();
        let foe = state.side_two.get_active();
        (foe.hp, foe.maxhp) = (400, 400);
        foe.moves[&PokemonMoveIndex::M0].choice = poke_engine::choices::MOVES
            .get(&Choices::ICEBEAM)
            .unwrap()
            .clone();
        let mut pc = PathCtx::new(Some(&base), &state);
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        pc.push(&state, &m, &m);
        let outcomes = generate_instructions_from_move_pair(&mut state, &m, &m, false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        assert!(state.side_one.force_switch);
        assert_ne!(
            state.side_two.switch_out_move_second_saved_move,
            Choices::NONE,
            "its move saved"
        );
        let ctx = pc.context(&base);
        let step = *ctx.history.last().unwrap();
        assert_eq!(step.one.kind, 1, "our U-turn");
        assert_eq!(step.two, Act::default(), "the foe's move not yet: {step:?}");
        let theirs = 6 + state.side_two.active_index as usize;
        assert_eq!(
            ctx.reveal[theirs] & (1 << 4),
            0,
            "its move revealed before it came"
        );
        assert_eq!(
            ctx.turn, 10,
            "the pivot's switch-in: still the turn it started"
        );
        // the switch's step: our switch-in, then the foe's saved move
        let (o1, o2) = state.get_all_options();
        assert!(matches!(o2[..], [MoveChoice::Move(_)]), "{o2:?}");
        pc.push(&state, &o1[0], &o2[0]);
        let outcomes = generate_instructions_from_move_pair(&mut state, &o1[0], &o2[0], false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        let ctx = pc.context(&base);
        let step = ctx.history.last().unwrap();
        assert_eq!(step.two.kind, 1, "the foe's move with the switch: {step:?}");
        assert_ne!(ctx.reveal[theirs] & (1 << 4), 0);
        assert_eq!(ctx.turn, 11);
    }

    /// 2026-10-22 review: both sides out of PP, one mon each -- both struggle: the turn is played
    /// out (the search stayed at the root: both none was a leaf)
    #[test]
    fn both_struggling_is_played_out() {
        let mut s = fixture();
        for side in [&mut s.side_one, &mut s.side_two] {
            let a = side.active_index;
            for p in [
                PokemonIndex::P0,
                PokemonIndex::P1,
                PokemonIndex::P2,
                PokemonIndex::P3,
                PokemonIndex::P4,
                PokemonIndex::P5,
            ] {
                if p != a {
                    side.pokemon[p].hp = 0;
                }
            }
            for k in [
                PokemonMoveIndex::M0,
                PokemonMoveIndex::M1,
                PokemonMoveIndex::M2,
                PokemonMoveIndex::M3,
            ] {
                side.get_active().moves[&k].pp = 0;
            }
        }
        let (o1, o2) = s.get_all_options();
        assert_eq!(
            (o1.clone(), o2.clone()),
            (vec![MoveChoice::None], vec![MoveChoice::None])
        );
        assert!(someone_struggles(&s));
        let res = search(
            &mut [s],
            &[],
            Duration::ZERO,
            32,
            &Config::default(),
            Some(1),
        );
        assert!(res.nodes > 1, "the search stayed at the root");
        assert!(res.s1.iter().map(|x| x.1).sum::<u32>() > 0);
    }

    /// 2026-10-23 review: Struggle beside a switch -- move slot 0 in the priors (it had none: a
    /// prior of 0) and the masks, a move in the history as the replays write it
    #[test]
    fn struggle_has_move_slot_0_and_is_a_move_in_the_history() {
        let mut s = fixture();
        for k in [
            PokemonMoveIndex::M0,
            PokemonMoveIndex::M1,
            PokemonMoveIndex::M2,
            PokemonMoveIndex::M3,
        ] {
            s.side_one.get_active().moves[&k].pp = 0;
        }
        let (o1, _) = s.get_all_options();
        assert!(
            o1.contains(&MoveChoice::None) && o1.iter().any(|m| matches!(m, MoveChoice::Switch(_))),
            "{o1:?}"
        );
        assert!(crate::features::struggles(&s, SideReference::SideOne));
        let mask = crate::features::legal_mask(&s);
        assert_eq!(mask[0], 1);
        assert!(mask[1..8].iter().all(|&m| m == 0));
        let avail: Vec<(usize, MoveChoice)> = o1.iter().copied().enumerate().collect();
        let p = prior_probs(&avail, &[0.0; crate::features::N_ACTIONS]);
        let none = o1.iter().position(|m| *m == MoveChoice::None).unwrap();
        assert!((p[none] - 1.0 / o1.len() as f32).abs() < 1e-6, "{p:?}");
        let base = Context {
            reveal: [0; 12],
            rating: [0, 0],
            turn: 10,
            history: vec![],
            ..Default::default()
        };
        let mut pc = PathCtx::new(Some(&base), &s);
        pc.push(
            &s,
            &MoveChoice::None,
            &MoveChoice::Move(PokemonMoveIndex::M0),
        );
        let me = s.side_one.get_active_immutable().id;
        let want = Act::parse(&format!("m:{me:?}:STRUGGLE"));
        let got = pc.steps[0].one;
        assert_eq!(
            (got.kind, got.actor, got.target),
            (want.kind, want.actor, want.target)
        );
        assert_eq!(want.target, Choices::STRUGGLE as i32);
    }

    /// 2026-10-23 review: a Struggle in the history is checked as a move: our U-turn first, the
    /// foe's Struggle saved for after our switch-in -- no action yet (it showed the Struggle);
    /// once it comes, the Struggle
    #[test]
    fn a_struggle_not_come_yet_is_no_action() {
        let base = Context {
            reveal: [0; 12],
            rating: [0, 0],
            turn: 10,
            history: vec![],
            ..Default::default()
        };
        let mut state = ko_first();
        state.side_one.get_active().moves[&PokemonMoveIndex::M0].id = Choices::UTURN;
        state.side_one.get_active().moves[&PokemonMoveIndex::M0].choice =
            poke_engine::choices::MOVES
                .get(&Choices::UTURN)
                .unwrap()
                .clone();
        let foe = state.side_two.get_active();
        (foe.hp, foe.maxhp) = (400, 400);
        for k in [
            PokemonMoveIndex::M0,
            PokemonMoveIndex::M1,
            PokemonMoveIndex::M2,
            PokemonMoveIndex::M3,
        ] {
            state.side_two.get_active().moves[&k].pp = 0;
        }
        assert!(crate::features::struggles(&state, SideReference::SideTwo));
        let mut pc = PathCtx::new(Some(&base), &state);
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        pc.push(&state, &m, &MoveChoice::None);
        let outcomes =
            generate_instructions_from_move_pair(&mut state, &m, &MoveChoice::None, false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        assert!(state.side_one.force_switch);
        assert_eq!(
            state.side_two.switch_out_move_second_saved_move,
            Choices::STRUGGLE
        );
        let ctx = pc.context(&base);
        assert_eq!(
            ctx.history.last().unwrap().two,
            Act::default(),
            "the Struggle has not come yet"
        );
        assert_eq!(
            ctx.reveal[6 + state.side_two.active_index as usize] & 0xf0,
            0,
            "a move revealed"
        );
        // our switch-in, then its Struggle
        let (o1, o2) = state.get_all_options();
        pc.push(&state, &o1[0], &o2[0]);
        let outcomes = generate_instructions_from_move_pair(&mut state, &o1[0], &o2[0], false);
        state.apply_instructions(&outcomes[0].instruction_list);
        pc.settle(&outcomes[0].instruction_list, &state);
        let two = pc.context(&base).history.last().unwrap().two;
        assert_eq!(
            (two.kind, two.target),
            (1, Choices::STRUGGLE as i32),
            "{two:?}"
        );
    }

    #[test]
    fn a_sleeping_mon_is_prevented() {
        use poke_engine::state::PokemonStatus;
        let base = Context {
            reveal: [0; 12],
            rating: [0, 0],
            turn: 3,
            history: vec![],
            ..Default::default()
        };
        let mut state = ko_first();
        let a = state.side_one.get_active();
        (a.status, a.sleep_turns, a.rest_turns) = (PokemonStatus::SLEEP, 0, 0); // cannot wake yet
        state.side_two.get_active().hp = 300;
        let mut pc = PathCtx::new(Some(&base), &state);
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        pc.push(&state, &m, &m);
        let outcomes = generate_instructions_from_move_pair(&mut state, &m, &m, false);
        for o in &outcomes {
            let mut st = state.clone();
            st.apply_instructions(&o.instruction_list);
            let mut p = PathCtx {
                pending: pc.pending,
                steps: pc.steps.clone(),
                ..PathCtx::new(Some(&base), &st)
            };
            p.settle(&o.instruction_list, &st);
            let step = p.steps.last().unwrap();
            assert!(step.one.kind == 0 && step.one.prevented, "asleep: {step:?}");
            assert!(step.two.kind == 1, "their move came: {step:?}");
        }
    }

    /// 2026-10-24, the tree's history check: the step the tree records as the log has it -- a
    /// locked turn (Outrage's later ones, a charge move's second: "[from]lockedmove") no action;
    /// a recharge prevented; a move with no target left (the foe's Healing Wish fainted it) the
    /// move (an Encore's move in the turn: tests/test_tree_history.py, from a battle)
    #[test]
    fn the_tree_step_is_the_logs() {
        use poke_engine::engine::state::PokemonVolatileStatus as V;
        use poke_engine::state::LastUsedMove;
        let outrage = {
            let mut s = ko_first();
            s.side_two.get_active().hp = 300;
            s.side_one.get_active().moves[&PokemonMoveIndex::M0].id = Choices::OUTRAGE;
            s.side_one.volatile_statuses.insert(V::LOCKEDMOVE);
            s.side_one.volatile_status_durations.lockedmove = 1;
            s.side_one.last_used_move = LastUsedMove::Move(PokemonMoveIndex::M0);
            s
        };
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        for (_, step, _, _) in tree_step_outcomes(&outrage, &m, &m, true) {
            assert!(step.one == Act::default(), "locked: {step:?}");
        }
        let mut recharge = ko_first();
        recharge.side_two.get_active().hp = 300;
        recharge.side_one.volatile_statuses.insert(V::MUSTRECHARGE);
        for (_, step, _, _) in tree_step_outcomes(&recharge, &MoveChoice::None, &m, true) {
            assert!(
                step.one.kind == 0 && step.one.prevented,
                "recharge: {step:?}"
            );
        }
        let mut wish = ko_first();
        wish.side_one.get_active().moves[&PokemonMoveIndex::M0].id = Choices::HEALINGWISH;
        wish.side_two.get_active().hp = 300;
        wish.side_two.get_active().moves[&PokemonMoveIndex::M0].id = Choices::TACKLE;
        for (_, step, _, _) in tree_step_outcomes(&wish, &m, &m, true) {
            assert!(step.one.kind == 1, "{step:?}");
            assert!(
                step.two.kind == 1
                    && step.two.target == Choices::TACKLE as i32
                    && !step.two.prevented,
                "no target: {step:?}"
            );
        }
    }

    /// 2026-10-24 review: a foe's Eerie Spell takes the PP of its target's last move before the
    /// target moves -- that slot read as the move it used (Brave Bird for its Roost)
    #[test]
    fn a_foes_eerie_spell_is_not_the_targets_move() {
        use poke_engine::choices::MOVES;
        use poke_engine::engine::abilities::Abilities;
        use poke_engine::engine::items::Items;
        use poke_engine::state::{LastUsedMove, Pokemon, PokemonType};
        // (a move's choice data with its id: the engine reads the choice)
        fn set(p: &mut Pokemon, i: PokemonMoveIndex, id: Choices) {
            p.moves[&i].id = id;
            p.moves[&i].choice = MOVES.get(&id).unwrap().clone();
        }
        let mut s = ko_first();
        let a = s.side_one.get_active();
        (a.speed, a.ability, a.item) = (1, Abilities::NONE, Items::NONE);
        a.types = (PokemonType::NORMAL, PokemonType::TYPELESS);
        set(a, PokemonMoveIndex::M0, Choices::ROOST);
        set(a, PokemonMoveIndex::M1, Choices::BRAVEBIRD);
        s.side_one.last_used_move = LastUsedMove::Move(PokemonMoveIndex::M1);
        let b = s.side_two.get_active();
        (b.hp, b.speed) = (300, 999);
        set(b, PokemonMoveIndex::M0, Choices::EERIESPELL);
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        let outcomes = generate_instructions_from_move_pair(&mut s.clone(), &m, &m, true);
        let took = outcomes.iter().any(|o| {
            o.instruction_list.iter().any(|i| {
                matches!(i, Instruction::DecrementPP(d) if d.side_ref == SideReference::SideOne
                    && d.move_index == PokemonMoveIndex::M1)
            })
        });
        assert!(
            took,
            "the Eerie Spell takes Brave Bird's PP: {:?}",
            outcomes[0].instruction_list
        );
        for (_, step, _, _) in tree_step_outcomes(&s, &m, &m, true) {
            if step.one.kind == 1 {
                assert!(step.one.target == Choices::ROOST as i32, "{step:?}");
            }
        }
    }

    #[test]
    fn worlds_are_restored_after_search() {
        let mut worlds = vec![
            fixture(),
            variant(Choices::SPLASH),
            variant(Choices::EARTHQUAKE),
        ];
        let before: Vec<String> = worlds.iter().map(|w| w.serialize()).collect();
        let cfg = Config::default();
        let res = search(&mut worlds, &[], Duration::ZERO, 30_000, &cfg, Some(1));
        assert!(res.iterations >= 30_000);
        assert!(res.max_depth >= 3, "tree too shallow: {}", res.max_depth);
        let after: Vec<String> = worlds.iter().map(|w| w.serialize()).collect();
        assert_eq!(before, after);
    }

    #[test]
    fn opponent_arms_are_labelled_by_move_and_counted_by_availability() {
        let mut worlds = [variant(Choices::SPLASH), variant(Choices::EARTHQUAKE)];
        let cfg = Config::default();
        let mut tree = Tree::new();
        let mut rng = StdRng::seed_from_u64(7);
        let evals: Vec<f32> = worlds.iter().map(evaluate).collect();
        for it in 0..2000u32 {
            let w = (it % 2) as usize;
            tree.iterate(&mut worlds[w], w as u16, evals[w], &cfg, None, &mut rng);
        }
        let root = &tree.nodes[0];
        let arm = |l: Label| root.s2.iter().find(|a| a.label == l).unwrap();
        // each world-specific move was available in exactly half of the iterations
        assert_eq!(arm(Label::Move(Choices::SPLASH)).avail, 1000);
        assert_eq!(arm(Label::Move(Choices::EARTHQUAKE)).avail, 1000);
        // our options are the same in every world: always available
        assert!(root.s1.iter().all(|a| a.avail == 2000));
        // useless Splash is valued below a real attack (all options are close in this position,
        // so visits alone are not a sharp test at 2000 iterations)
        let splash = arm(Label::Move(Choices::SPLASH)).mean();
        let attack = arm(Label::Move(Choices::HYDROSTEAM)).mean();
        assert!(splash < attack, "splash {splash} vs hydro steam {attack}");
    }

    #[test]
    fn parallel_search_merges_threads_and_leaves_worlds_untouched() {
        let worlds = vec![fixture(), variant(Choices::SPLASH)];
        let before: Vec<String> = worlds.iter().map(|w| w.serialize()).collect();
        let res = search_parallel(
            &worlds,
            &[],
            Duration::ZERO,
            20_000,
            &Config::default(),
            Some(9),
            4,
        );
        assert!(res.iterations >= 20_000);
        // every thread's root visits are merged: our options' visits add up to the iterations
        let visits: u32 = res.s1.iter().map(|x| x.1).sum();
        assert_eq!(visits, res.iterations);
        let after: Vec<String> = worlds.iter().map(|w| w.serialize()).collect();
        assert_eq!(before, after);
    }

    #[test]
    fn single_world_agrees_with_poke_engine_mcts() {
        let mut worlds = vec![fixture()];
        let res = search(
            &mut worlds,
            &[],
            Duration::ZERO,
            50_000,
            &Config::default(),
            Some(3),
        );
        let best = res.s1.iter().max_by_key(|x| x.1).unwrap().0;
        let mut st = fixture();
        let (o1, o2) = st.root_get_all_options();
        let reference = poke_engine::mcts::perform_mcts(&mut st, o1, o2, Duration::ZERO, 50_000);
        let mut top: Vec<_> = reference.s1.iter().collect();
        top.sort_by_key(|r| std::cmp::Reverse(r.visits));
        let top3: Vec<Label> = top[..3]
            .iter()
            .map(|r| label(&st.side_one, &r.move_choice))
            .collect();
        assert!(
            top3.contains(&best),
            "ismcts best {best:?} not in reference top 3 {top3:?}"
        );
    }

    /// the moves-left term: off by default; when one side is clearly winning its shorter
    /// option is preferred, when it is losing the longer one; nothing near an even value
    #[test]
    fn moves_left_term_prefers_short_wins_and_long_losses() {
        let arm = |total: f32, ml: f32| Arm {
            label: Label::Other(MoveChoice::None),
            visits: 10,
            avail: 10,
            total,
            prior: 0.5,
            ml_total: 10.0 * ml,
            ml_n: 10,
        };
        let avail: Vec<(usize, MoveChoice)> = (0..2).map(|i| (i, MoveChoice::None)).collect();
        let ml = MlParams {
            slope: 0.01,
            cap: 0.05,
            threshold: 0.5,
            winner_only: false,
        };
        // equal values, arm 1 shorter: winning -> 1, losing -> 0, even / off -> the first
        let win = [arm(9.0, 20.0), arm(9.0, 10.0)];
        assert_eq!(select_puct(&win, &avail, 1.0, &ml).0, 1);
        assert_eq!(select_puct(&win, &avail, 1.0, &MlParams::default()).0, 0);
        let lose = [arm(1.0, 10.0), arm(1.0, 20.0)];
        assert_eq!(select_puct(&lose, &avail, 1.0, &ml).0, 1);
        let winner_only = MlParams {
            winner_only: true,
            ..ml
        };
        assert_eq!(select_puct(&lose, &avail, 1.0, &winner_only).0, 0);
        assert_eq!(select_puct(&win, &avail, 1.0, &winner_only).0, 1);
        let even = [arm(5.0, 20.0), arm(5.0, 10.0)];
        assert_eq!(select_puct(&even, &avail, 1.0, &ml).0, 0);
        // bounded: a large value difference is not overturned
        let big = [arm(9.5, 40.0), arm(8.5, 5.0)];
        assert_eq!(select_puct(&big, &avail, 1.0, &ml).0, 0);
    }

    #[test]
    fn root_noise_mixes_priors() {
        let mut arms: Vec<Arm> = (0..4)
            .map(|k| Arm {
                label: Label::Other(MoveChoice::None),
                visits: 0,
                avail: 0,
                total: 0.0,
                prior: [0.7, 0.2, 0.1, 0.0][k],
                ml_total: 0.0,
                ml_n: 0,
            })
            .collect();
        let avail: Vec<(usize, MoveChoice)> = (0..4).map(|i| (i, MoveChoice::None)).collect();
        let before: Vec<f32> = arms.iter().map(|a| a.prior).collect();
        let mut rng = StdRng::seed_from_u64(3);
        add_root_noise(&mut arms, &avail, 0.0, 10.0, &mut rng);
        assert_eq!(before, arms.iter().map(|a| a.prior).collect::<Vec<_>>());
        add_root_noise(&mut arms, &avail, 0.25, 10.0, &mut rng);
        let after: Vec<f32> = arms.iter().map(|a| a.prior).collect();
        assert!((after.iter().sum::<f32>() - 1.0).abs() < 1e-5, "{after:?}");
        assert!(after[3] > 0.0, "the zero prior gets some mass: {after:?}");
        assert!(
            after[0] < 0.7 + 0.25 && after[0] >= 0.75 * 0.7 - 1e-6,
            "{after:?}"
        );
    }

    /// The root's priors over worlds whose opponents differ (2026-10-22, the second search
    /// review): world A's opponent has X, Y, world B's Y, Z (each 50 / 50); ours are the same.
    /// Returns the root's arms and the opponent's per-world priors, keyed by label.
    #[allow(clippy::type_complexity)]
    fn root_priors_of(
        worlds: &[(&[Choices], &[f32])],
        eps: f32,
    ) -> (
        Vec<(Label, f32)>,
        Vec<(Label, f32)>,
        Vec<Vec<(Label, f32)>>,
        Tree,
    ) {
        let mut tree = Tree::new();
        let mut rp = RootPriors::default();
        let ours = [Choices::TACKLE, Choices::PROTECT, Choices::SWORDSDANCE];
        for (opp, probs) in worlds {
            let root = &mut tree.nodes[0];
            let av1: Vec<(usize, MoveChoice)> = ours
                .iter()
                .map(|&m| (arm_index(&mut root.s1, Label::Move(m)), MoveChoice::None))
                .collect();
            let av2: Vec<(usize, MoveChoice)> = opp
                .iter()
                .map(|&m| (arm_index(&mut root.s2, Label::Move(m)), MoveChoice::None))
                .collect();
            rp.add(&av1, &[0.6, 0.3, 0.1], &av2, Some(probs));
        }
        let cfg = Config {
            root_noise_eps: eps,
            ..Config::default()
        };
        let mut rng = StdRng::seed_from_u64(11);
        let Tree {
            nodes, root_opp, ..
        } = &mut tree;
        rp.finish(&mut nodes[0], root_opp, &cfg, &mut rng);
        let by_label = |arms: &[Arm]| arms.iter().map(|a| (a.label, a.prior)).collect::<Vec<_>>();
        let per_world = tree
            .root_opp
            .iter()
            .map(|v| {
                v.iter()
                    .enumerate()
                    .filter(|(_, p)| **p >= 0.0)
                    .map(|(i, p)| (tree.nodes[0].s2[i].label, *p))
                    .collect()
            })
            .collect();
        (
            by_label(&tree.nodes[0].s1),
            by_label(&tree.nodes[0].s2),
            per_world,
            tree,
        )
    }

    fn sorted(mut v: Vec<(Label, f32)>) -> Vec<(String, f32)> {
        let mut out: Vec<(String, f32)> = v.drain(..).map(|(l, p)| (format!("{l:?}"), p)).collect();
        out.sort_by(|a, b| a.0.cmp(&b.0));
        out
    }

    /// The opponent knows its set: at the root it selects with its world's own priors (X 50%,
    /// Y 50% in A -- the belief's marginal, X 25% Y 50% Z 25%, renormalized gave A X 33% Y 67%)
    #[test]
    fn root_priors_condition_the_opponent_on_its_world() {
        let (x, y, z) = (Choices::ICEBEAM, Choices::EARTHQUAKE, Choices::THUNDERBOLT);
        let half = [0.5f32, 0.5];
        let (ours, opp, per_world, tree) =
            root_priors_of(&[(&[x, y], &half), (&[y, z], &half)], 0.0);
        assert_eq!(
            sorted(ours).iter().map(|x| x.1).collect::<Vec<_>>().len(),
            3
        );
        // the arms' priors (record, fallback): the mean over the worlds that have the arm
        for (_, p) in &opp {
            assert!((p - 0.5).abs() < 1e-6, "{opp:?}");
        }
        assert_eq!(
            sorted(per_world[0].clone()),
            sorted(vec![(Label::Move(x), 0.5), (Label::Move(y), 0.5)])
        );
        assert_eq!(
            sorted(per_world[1].clone()),
            sorted(vec![(Label::Move(y), 0.5), (Label::Move(z), 0.5)])
        );
        // the root's selection in world A: X and Y even (the first selection: prior only)
        let root = &tree.nodes[0];
        let ix = root
            .s2
            .iter()
            .position(|a| a.label == Label::Move(x))
            .unwrap();
        let iy = root
            .s2
            .iter()
            .position(|a| a.label == Label::Move(y))
            .unwrap();
        let av: Vec<(usize, MoveChoice)> = vec![(ix, MoveChoice::None), (iy, MoveChoice::None)];
        let mut arms = root.s2.clone();
        let (mut nx, mut ny) = (0i32, 0i32);
        for _ in 0..1000 {
            let (i, _) = select_puct_with(
                &arms,
                &av,
                1.0,
                &MlParams::default(),
                Some(&tree.root_opp[0]),
            );
            arms[i].visits += 1;
            arms[i].total += 0.5;
            if i == ix {
                nx += 1
            } else {
                ny += 1
            }
        }
        assert!((nx - ny).abs() <= 1, "{nx} {ny}");
    }

    /// Root noise: one draw over all the root's arms in label order -- every option gets noise,
    /// the same for any order of the worlds (before: the last world's options only)
    #[test]
    fn root_noise_is_the_same_for_any_order_of_the_worlds() {
        let (x, y, z) = (Choices::ICEBEAM, Choices::EARTHQUAKE, Choices::THUNDERBOLT);
        let (a, b) = (
            (&[x, y][..], &[0.7f32, 0.3][..]),
            (&[y, z][..], &[0.4f32, 0.6][..]),
        );
        let (o1, p1, w1, _) = root_priors_of(&[a, b], 0.1);
        let (o2, p2, w2, _) = root_priors_of(&[b, a], 0.1);
        let close = |u: Vec<(String, f32)>, v: Vec<(String, f32)>| {
            u.len() == v.len()
                && u.iter()
                    .zip(&v)
                    .all(|(s, t)| s.0 == t.0 && (s.1 - t.1).abs() < 1e-6)
        };
        assert!(close(sorted(o1.clone()), sorted(o2)), "ours");
        assert!(close(sorted(p1), sorted(p2)), "the opponent's arms");
        assert!(
            close(sorted(w1[0].clone()), sorted(w2[1].clone())),
            "world A"
        );
        assert!(
            close(sorted(w1[1].clone()), sorted(w2[0].clone())),
            "world B"
        );
        // every option got noise (with it, not the plain priors)
        let (o0, _, w0, _) = root_priors_of(&[a, b], 0.0);
        assert!(sorted(o1)
            .iter()
            .zip(sorted(o0))
            .all(|(s, t)| (s.1 - t.1).abs() > 1e-6));
        for (s, t) in sorted(w1[1].clone()).iter().zip(sorted(w0[1].clone())) {
            assert!((s.1 - t.1).abs() > 1e-6, "world B's {} kept its prior", s.0);
        }
    }

    /// 2026-10-21: a node's cached logits (from the state that created it) set its priors only
    /// for the same options -- not where they were computed with our active fainted (moves
    /// -inf) or with another active
    #[test]
    fn cached_logits_serve_only_the_same_options() {
        let s = fixture();
        let (o1, _) = s.get_all_options();
        let avail: Vec<(usize, MoveChoice)> = o1.into_iter().enumerate().collect();
        assert!(avail
            .iter()
            .any(|(_, mc)| matches!(mc, MoveChoice::Move(_))));
        let active = s.side_one.active_index;
        let n = crate::features::N_ACTIONS;
        let all = [0.5f32; crate::features::N_ACTIONS];
        assert!(cached_logits_fit(&(all, active), &s, &avail));
        // created in a forced switch: only the switch slots are finite
        let mut forced = [f32::NEG_INFINITY; crate::features::N_ACTIONS];
        forced[8..n].fill(0.5);
        assert!(!cached_logits_fit(&(forced, active), &s, &avail));
        let switches: Vec<(usize, MoveChoice)> = avail
            .iter()
            .copied()
            .filter(|(_, mc)| matches!(mc, MoveChoice::Switch(_)))
            .collect();
        assert!(cached_logits_fit(&(forced, active), &s, &switches));
        // created with another active
        let other = if active == PokemonIndex::P0 {
            PokemonIndex::P1
        } else {
            PokemonIndex::P0
        };
        assert!(!cached_logits_fit(&(all, other), &s, &avail));
    }

    /// 2026-10-21: with `phase_key`, a joint action whose damage roll KOs or not gets a child
    /// for each (the KO: a forced switch next); open loop, one child
    #[test]
    fn the_phase_key_splits_a_ko_from_no_ko() {
        use poke_engine::instruction::DamageInstruction;
        let mut s = ko_first();
        let b = s.side_two.get_active();
        (b.hp, b.maxhp) = (1000, 1000);
        let m1 = our_choice(&s, Label::Move(Choices::TACKLE)).unwrap();
        let m2 = their_choice(&s, Label::Move(Choices::ICEBEAM)).unwrap();
        // the foe's HP inside Tackle's damage range: some rolls KO
        let mut dmg: Vec<i16> = generate_instructions_from_move_pair(&mut s, &m1, &m2, true)
            .iter()
            .flat_map(|o| o.instruction_list.iter())
            .filter_map(|i| match i {
                Instruction::Damage(DamageInstruction {
                    side_ref: SideReference::SideTwo,
                    damage_amount,
                }) => Some(*damage_amount),
                _ => None,
            })
            .collect();
        dmg.sort();
        assert!(dmg[0] < dmg[dmg.len() - 1], "{dmg:?}");
        s.side_two.get_active().hp = dmg[dmg.len() / 2];
        for phase_key in [false, true] {
            let cfg = Config {
                phase_key,
                ..Config::default()
            };
            let mut tree = Tree::new();
            let mut rng = StdRng::seed_from_u64(5);
            let ev = evaluate(&s);
            for _ in 0..3000 {
                tree.iterate(&mut s, 0, ev, &cfg, None, &mut rng);
            }
            let n = &tree.nodes[0];
            let i1 =
                n.s1.iter()
                    .position(|a| a.label == Label::Move(Choices::TACKLE))
                    .unwrap() as u16;
            let i2 =
                n.s2.iter()
                    .position(|a| a.label == Label::Move(Choices::ICEBEAM))
                    .unwrap() as u16;
            let kids = tree
                .children
                .keys()
                .filter(|k| (k.0, k.1, k.2) == (0, i1, i2))
                .count();
            assert_eq!(kids, if phase_key { 2 } else { 1 }, "phase_key {phase_key}");
        }
    }

    /// Simultaneous moves (2026-10-21, the search review): the decoupled PUCT of both sides on
    /// matrix games with known equilibria, as at a node whose children are terminal (value
    /// M[i][j] for side one, Bernoulli). Prints our visit shares against the equilibrium and
    /// the exploitability (equilibrium value - our worst case against a best response) of the
    /// visit distribution and of the most visited option alone (what the search plays).
    #[test]
    #[ignore]
    fn matrix_games() {
        let games: [(&str, Vec<Vec<f32>>, Vec<f32>, f32); 4] = [
            (
                "matching pennies",
                vec![vec![1.0, 0.0], vec![0.0, 1.0]],
                vec![0.5, 0.5],
                0.5,
            ),
            (
                "rock paper scissors",
                vec![
                    vec![0.5, 0.0, 1.0],
                    vec![1.0, 0.5, 0.0],
                    vec![0.0, 1.0, 0.5],
                ],
                vec![1.0 / 3.0; 3],
                0.5,
            ),
            // a win with rock counts double: equilibrium (1/4, 1/2, 1/4) for both
            (
                "biased rps",
                vec![
                    vec![0.5, 0.25, 1.0],
                    vec![0.75, 0.5, 0.25],
                    vec![0.0, 0.75, 0.5],
                ],
                vec![0.25, 0.5, 0.25],
                0.5,
            ),
            // attack / protect against attack / set up: equilibrium (2/3, 1/3), value 2/3
            (
                "protect guess",
                vec![vec![0.5, 1.0], vec![1.0, 0.0]],
                vec![2.0 / 3.0, 1.0 / 3.0],
                2.0 / 3.0,
            ),
        ];
        let arm = |prior: f32| Arm {
            label: Label::None,
            visits: 0,
            avail: 0,
            total: 0.0,
            prior,
            ml_total: 0.0,
            ml_n: 0,
        };
        for (name, m, nash, value) in games {
            for iters in [200u32, 1600, 12800] {
                let (n1, n2) = (m.len(), m[0].len());
                let mut a1: Vec<Arm> = (0..n1).map(|_| arm(1.0 / n1 as f32)).collect();
                let mut a2: Vec<Arm> = (0..n2).map(|_| arm(1.0 / n2 as f32)).collect();
                let av1: Vec<(usize, MoveChoice)> =
                    (0..n1).map(|i| (i, MoveChoice::None)).collect();
                let av2: Vec<(usize, MoveChoice)> =
                    (0..n2).map(|i| (i, MoveChoice::None)).collect();
                let mut rng = StdRng::seed_from_u64(7);
                for _ in 0..iters {
                    let (i, _) = select_puct(&a1, &av1, 1.0, &MlParams::default());
                    let (j, _) = select_puct(&a2, &av2, 1.0, &MlParams::default());
                    let r = if rng.random::<f32>() < m[i][j] {
                        1.0
                    } else {
                        0.0
                    };
                    a1[i].visits += 1;
                    a1[i].total += r;
                    a2[j].visits += 1;
                    a2[j].total += 1.0 - r;
                }
                let x: Vec<f32> = a1.iter().map(|a| a.visits as f32 / iters as f32).collect();
                let worst = |x: &[f32]| {
                    (0..n2)
                        .map(|j| (0..n1).map(|i| x[i] * m[i][j]).sum::<f32>())
                        .fold(f32::MAX, f32::min)
                };
                let top = (0..n1).max_by_key(|&i| a1[i].visits).unwrap();
                let pure: Vec<f32> = (0..n1).map(|i| (i == top) as u32 as f32).collect();
                let tv = 0.5 * x.iter().zip(&nash).map(|(a, b)| (a - b).abs()).sum::<f32>();
                println!(
                    "{name:20} {iters:6}: visits {:?} (equilibrium {:?}, TV {tv:.3}); \
                     exploitability: visit mix {:.3}, most visited alone {:.3}",
                    x.iter()
                        .map(|v| (v * 1000.0).round() / 1000.0)
                        .collect::<Vec<_>>(),
                    nash.iter()
                        .map(|v| (v * 1000.0).round() / 1000.0)
                        .collect::<Vec<_>>(),
                    value - worst(&x),
                    value - worst(&pure)
                );
            }
        }
    }

    /// The search that fell back on a +7 (2026-10-22, the `phase_key` A/B: world 0 of a dumped
    /// failure, the handcrafted search, seed 1): ALPHA_STAGE_STATE = its state
    #[test]
    #[ignore]
    fn the_search_keeps_the_stages_in_range() {
        let Ok(line) = std::env::var("ALPHA_STAGE_STATE") else {
            return;
        };
        let mut worlds = vec![State::deserialize(line.trim())];
        search(
            &mut worlds,
            &[],
            Duration::ZERO,
            20_000,
            &Config::default(),
            Some(1),
        );
    }

    /// How often a node's cached logits do not fit its first selection, in real positions
    /// (ALPHA_STATES: one state per line; ALPHA_MODEL: a run): 2026-10-21, the search review
    #[test]
    #[ignore]
    fn measure_cached_logits_fit() {
        use std::sync::atomic::Ordering;
        let (Ok(states), Ok(model)) = (std::env::var("ALPHA_STATES"), std::env::var("ALPHA_MODEL"))
        else {
            return;
        };
        let cfg = Config {
            use_policy: true,
            tnet: Some(crate::tnet::shared(&model).unwrap()),
            ..Config::default()
        };
        let lines = std::fs::read_to_string(states).unwrap();
        let mut n = 0;
        for line in lines.lines().filter(|l| !l.is_empty()) {
            let mut worlds = vec![State::deserialize(line)];
            if worlds[0].battle_is_over() != 0.0 {
                continue;
            }
            search(
                &mut worlds,
                &[Context::default()],
                Duration::ZERO,
                800,
                &cfg,
                Some(1),
            );
            n += 1;
        }
        let (bad, ok) = (
            CACHE_FIT[0].load(Ordering::Relaxed),
            CACHE_FIT[1].load(Ordering::Relaxed),
        );
        let (diff, same) = (
            PHASE_SAME[0].load(Ordering::Relaxed),
            PHASE_SAME[1].load(Ordering::Relaxed),
        );
        println!("node visits after the first in another public phase (actives, forced switches) than the first: {diff} of {} ({:.2}%)",
                 diff + same, 100.0 * diff as f64 / (diff + same).max(1) as f64);
        println!(
            "{n} searches x 800: cached logits did not fit {bad} of {} first selections ({:.2}%)",
            bad + ok,
            100.0 * bad as f64 / (bad + ok).max(1) as f64
        );
    }
}
