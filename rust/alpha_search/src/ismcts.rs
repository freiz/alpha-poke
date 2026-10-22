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
use poke_engine::engine::state::MoveChoice;
use poke_engine::instruction::{Instruction, StateInstructions};
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

/// (tests) the public phase of a state: both actives, whether each side must switch
#[cfg(test)]
pub(crate) fn phase(state: &State) -> (PokemonIndex, PokemonIndex, bool, bool) {
    let forced = |side: &Side| side.force_switch || side.get_active_immutable().hp <= 0;
    (state.side_one.active_index, state.side_two.active_index, forced(&state.side_one), forced(&state.side_two))
}

#[cfg(test)]
pub(crate) static PHASE_SAME: [std::sync::atomic::AtomicU64; 2] =
    [std::sync::atomic::AtomicU64::new(0), std::sync::atomic::AtomicU64::new(0)];

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
        }
    }
}

pub struct Tree {
    pub nodes: Vec<Node>,
    pub(crate) children: FxHashMap<(u32, u16, u16, u64), u32>,
    pub(crate) cache: FxHashMap<(u32, u16, u16, u16), Vec<StateInstructions>>,
}

pub struct SearchResult {
    /// our root actions: (label, visits, mean value)
    pub s1: Vec<(Label, u32, f32)>,
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
        let x = Input::new(state, &path.context(ctx), false, crate::bsearch::evaluate_checked(state));
        return 1.0 / (1.0 + (-tnet.value(&x)).exp());
    }
    sigmoid(crate::bsearch::evaluate_checked(state) - root_eval)
}

/// What the descent adds to a world's context: the decision steps taken, the bits they reveal,
/// the main steps (turns) completed.
pub(crate) struct PathCtx<'a> {
    base: Option<&'a Context>,
    steps: Vec<Step>,
    reveal: [u8; 12],
    mains: i32,
    // the last step's moves, until `settle` (side: the reveal byte and bits a used move adds)
    pending: [Option<(usize, u8, PokemonIndex)>; 2],
}

impl<'a> PathCtx<'a> {
    pub(crate) fn new(base: Option<&'a Context>) -> Self {
        PathCtx {
            base,
            steps: Vec::new(),
            reveal: base.map_or([0; 12], |c| c.reveal),
            mains: 0,
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
        // HP even without `force_switch`; 2026-10-14) is not a new turn
        let forced = |side: &Side| side.force_switch || side.get_active_immutable().hp <= 0;
        if !(forced(&state.side_one) || forced(&state.side_two)) {
            self.mains += 1;
        }
        self.steps.push(Step {
            one: Act::of_choice(&state.side_one, m1),
            two: Act::of_choice(&state.side_two, m2),
        });
        for (k, (off, side, mc)) in [(0, &state.side_one, m1), (6, &state.side_two, m2)]
            .into_iter()
            .enumerate()
        {
            self.pending[k] = None;
            match mc {
                MoveChoice::Move(i) | MoveChoice::MoveTera(i) => {
                    let a = off + side.active_index as usize;
                    // seen (and its tera) whether or not the move comes
                    self.reveal[a] |= 1;
                    if matches!(mc, MoveChoice::MoveTera(_)) {
                        self.reveal[a] |= 1 << 3;
                    }
                    self.pending[k] = Some((a, 1 << (4 + *i as usize), side.active_index));
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
        let Some(step) = self.steps.last_mut() else {
            return;
        };
        for (k, side_ref, side) in [
            (0, SideReference::SideOne, &state.side_one),
            (1, SideReference::SideTwo, &state.side_two),
        ] {
            let Some((a, bits, slot)) = self.pending[k].take() else {
                continue;
            };
            let acted = instructions
                .iter()
                .any(|i| matches!(i, Instruction::Acted(s) if *s == side_ref));
            if acted {
                self.reveal[a] |= bits;
                continue;
            }
            let fainted = side.pokemon[slot].hp <= 0;
            let act = Act {
                fainted_first: fainted,
                prevented: !fainted,
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
    let slots: Vec<Option<usize>> = avail
        .iter()
        .map(|(_, mc)| crate::features::slot(mc))
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
        .map(|j| if z > 0.0 { exps[j] / z } else { 1.0 / avail.len() as f32 })
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
        && avail
            .iter()
            .all(|(_, mc)| crate::features::slot(mc).is_none_or(|k| cached.0[k].is_finite()))
}

/// (tests: how often the cached logits did not fit / did)
#[cfg(test)]
pub(crate) static CACHE_FIT: [std::sync::atomic::AtomicU64; 2] =
    [std::sync::atomic::AtomicU64::new(0), std::sync::atomic::AtomicU64::new(0)];

/// Averages the root's priors over the worlds (2026-10-21, the search review: they came from
/// the first world alone -- the worlds' order changed the search's priors): `add(world's
/// avail, its priors)` per world, then `finish` sets each arm's prior to its mean over all the
/// worlds (0 in a world where it is no option: the arm's marginal prior over the belief).
#[derive(Default)]
pub(crate) struct PriorMean {
    sum: Vec<f32>,
    worlds: u32,
}

impl PriorMean {
    pub(crate) fn add(&mut self, avail: &[(usize, MoveChoice)], probs: &[f32]) {
        for (&(i, _), &p) in avail.iter().zip(probs) {
            if self.sum.len() <= i {
                self.sum.resize(i + 1, 0.0);
            }
            self.sum[i] += p;
        }
        self.worlds += 1;
    }

    pub(crate) fn finish(&self, arms: &mut [Arm]) {
        for (i, a) in arms.iter_mut().enumerate() {
            a.prior = self.sum.get(i).copied().unwrap_or(0.0) / self.worlds.max(1) as f32;
        }
    }
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
        if arms[i].prior >= 0.0 {
            known += arms[i].prior;
            nk += 1;
        }
    }
    let stand_in = if nk > 0 { known / nk as f32 } else { 1.0 };
    let raw = |a: &Arm| if a.prior >= 0.0 { a.prior } else { stand_in };
    let z: f32 = avail.iter().map(|&(i, _)| raw(&arms[i])).sum();
    let uniform = 1.0 / avail.len() as f32;
    let ml_term = moves_left_term(arms, avail, ml);
    let mut best = avail[0];
    let mut best_u = f32::MIN;
    for &(i, mc) in avail {
        let a = &arms[i];
        let q = if a.visits > 0 { a.mean() } else { fpu };
        let p = if z > 0.0 { raw(a) / z } else { uniform };
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
        let mut pc = PathCtx::new(ctx.filter(|_| cfg.tnet.is_some()));
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
                        PHASE_SAME[(p == ph) as usize].fetch_add(1, std::sync::atomic::Ordering::Relaxed);
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
                select_puct(&n.s2, &av2, cfg.c_puct, &cfg.ml)
            } else {
                select(&n.s2, &av2, cfg.c)
            };
            let depth = n.depth;
            if m1 == MoveChoice::None && m2 == MoveChoice::None {
                break (leaf_value(state, root_eval, cfg, &pc), None);
            }
            pc.push(state, &m1, &m2);
            let (i1, i2) = (i1 as u16, i2 as u16);
            let branch = depth < cfg.branch_depth;
            if node == 0 && cfg.cache_root {
                let outcomes = self.cache.entry((node, i1, i2, world)).or_insert_with(|| {
                    generate_instructions_from_move_pair(state, &m1, &m2, branch)
                });
                let k = sample(outcomes, rng);
                state.apply_instructions(&outcomes[k].instruction_list);
                pc.settle(&outcomes[k].instruction_list, state);
                root_step = Some((i1, i2, k));
            } else {
                let mut outcomes = generate_instructions_from_move_pair(state, &m1, &m2, branch);
                let k = sample(&outcomes, rng);
                let instructions = outcomes.swap_remove(k).instruction_list;
                state.apply_instructions(&instructions);
                pc.settle(&instructions, state);
                applied.push(instructions);
            }
            path.push((node, i1, i2));
            let sig = 0; // open-loop: one child per joint action
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
                        let x = Input::new(state, &pc.context(base), false, crate::bsearch::evaluate_checked(state));
                        let out = tnet.forward(&x);
                        self.nodes[child as usize].logits1 = Some(Box::new((out.logits, state.side_one.active_index)));
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

/// Search over the given worlds (they must share our side; the opponent's hidden details may
/// differ). Stops after `duration` or, when `max_iterations` > 0, after that many iterations.
/// Every world's state is restored before returning.
/// The root's priors from the network in every world, averaged (`PriorMean`), and its noise
/// (2026-10-21, the search review: they came from the first iteration's world alone); nothing
/// without the network's policy.
fn root_priors_over_worlds(root: &mut Node, worlds: &[State], ctxs: &[Context], cfg: &Config, rng: &mut StdRng) {
    let Some(tnet) = cfg.tnet.as_ref().filter(|_| cfg.use_policy) else {
        return;
    };
    if ctxs.len() != worlds.len() || worlds.is_empty() {
        return;
    }
    let (mut m1, mut m2) = (PriorMean::default(), PriorMean::default());
    let (mut last1, mut last2) = (vec![], vec![]);
    for (state, ctx) in worlds.iter().zip(ctxs) {
        let (o1, o2) = state.root_get_all_options();
        let av1: Vec<(usize, MoveChoice)> =
            o1.into_iter().map(|mc| (arm_index(&mut root.s1, label(&state.side_one, &mc)), mc)).collect();
        let av2: Vec<(usize, MoveChoice)> =
            o2.into_iter().map(|mc| (arm_index(&mut root.s2, label(&state.side_two, &mc)), mc)).collect();
        let lc = PathCtx::new(Some(ctx)).context(ctx);
        let own = Input::new(state, &lc, false, crate::bsearch::evaluate_checked(state));
        m1.add(&av1, &prior_probs(&av1, &tnet.forward(&own).logits));
        if cfg.policy_opponent {
            m2.add(&av2, &prior_probs(&av2, &tnet.forward(&own.flipped(state, &lc)).logits));
        }
        (last1, last2) = (av1, av2);
    }
    m1.finish(&mut root.s1);
    if cfg.policy_opponent {
        m2.finish(&mut root.s2);
    }
    if cfg.root_noise_eps > 0.0 {
        let (e, c) = (cfg.root_noise_eps, cfg.root_noise_conc);
        add_root_noise(&mut root.s1, &last1, e, c, rng);
        if cfg.policy_opponent {
            add_root_noise(&mut root.s2, &last2, e, c, rng);
        }
    }
    root.priors_set = true;
}

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
    let root_evals: Vec<f32> = worlds.iter().map(evaluate).collect();
    let mut tree = Tree::new();
    root_priors_over_worlds(&mut tree.nodes[0], worlds, ctxs, cfg, &mut rng);
    let start = Instant::now();
    let mut it: u32 = 0;
    loop {
        for _ in 0..256 {
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
        s1_priors: root.s1.iter().map(|a| (a.label, a.prior)).collect(),
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
    let mut merged: Vec<(Label, u32, f32)> = Vec::new();
    for r in &results {
        for &(l, visits, mean) in &r.s1 {
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
    SearchResult {
        s1: merged,
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
        for (side, id, speed) in [(&mut s.side_one, Choices::TACKLE, 1), (&mut s.side_two, Choices::UTURN, 999)] {
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
        assert_eq!(s.serialize(), before, "the generation left the state changed");
        assert_eq!(s.side_one.switch_out_move_second_saved_move, Choices::NONE, "saved move leaked");
        let pivots: Vec<_> = outcomes.iter().filter(|o| {
            o.instruction_list.iter().any(|i| matches!(i, Instruction::ToggleSideTwoForceSwitch))
        }).collect();
        assert!(!pivots.is_empty(), "U-turn switches side two out");
        for o in pivots {
            s.apply_instructions(&o.instruction_list);
            assert_eq!(s.side_one.switch_out_move_second_saved_move, Choices::TACKLE);
            let (o1, _) = s.get_all_options();
            assert!(!o1.is_empty());
            s.reverse_instructions(&o.instruction_list);
            assert_eq!(s.serialize(), before);
            assert_eq!(s.side_one.switch_out_move_second_saved_move, Choices::NONE);
        }
        // the follow-up (side two's replacement, our move after it): nothing saved after it
        s.apply_instructions(&outcomes.iter().find(|o| o.instruction_list.iter().any(|i| matches!(i, Instruction::ToggleSideTwoForceSwitch))).unwrap().instruction_list.clone());
        let (o1, o2) = s.get_all_options();
        let sw = o2.iter().find(|c| matches!(c, MoveChoice::Switch(_))).unwrap().clone();
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
        let j = (0..6).find(|&j| j != a2 && s.side_two.pokemon.pkmn[j].hp > 0).unwrap();
        let p = &mut s.side_two.pokemon.pkmn[j];
        p.item = Items::EJECTPACK;
        p.types.0 = PokemonType::NORMAL; // grounded
        p.types.1 = PokemonType::TYPELESS;
        p.ability = poke_engine::engine::abilities::Abilities::NONE;
        let a1 = s.side_one.active_index as usize;
        let k = (0..6).find(|&k| k != a1 && s.side_one.pokemon.pkmn[k].hp > 0).unwrap();
        let (m1, m2) = (MoveChoice::Switch(PokemonIndex::deserialize(&k.to_string())),
                        MoveChoice::Switch(PokemonIndex::deserialize(&j.to_string())));
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
        let (mut steps, mut leaks, mut empty, mut boosts, mut unreversed) = (0usize, 0usize, 0usize, 0usize, 0usize);
        let in_range = |s: &State| {
            [&s.side_one, &s.side_two].iter().all(|sd| {
                [sd.attack_boost, sd.defense_boost, sd.special_attack_boost, sd.special_defense_boost,
                 sd.speed_boost, sd.accuracy_boost, sd.evasion_boost]
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
                let (m1, m2) = (o1[rng.gen_range(0..o1.len())].clone(), o2[rng.gen_range(0..o2.len())].clone());
                let before = s.serialize();
                let outcomes = generate_instructions_from_move_pair(&mut s, &m1, &m2, false);
                steps += 1;
                if s.serialize() != before {
                    leaks += 1;
                    if leaks <= 3 {
                        eprintln!("LEAK {m1:?} {m2:?}\nBEFORE {before}\nAFTER  {}", s.serialize());
                    }
                    s = State::deserialize(&before);
                }
                for o in &outcomes {
                    s.apply_instructions(&o.instruction_list);
                    if !in_range(&s) {
                        boosts += 1;
                        if boosts <= 5 {
                            eprintln!("BOOST {m1:?} {m2:?}\nBEFORE {before}\nINSTRUCTIONS {:?}", o.instruction_list);
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
                let k = rng.gen_range(0..outcomes.len());
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
                                [sd.attack_boost, sd.defense_boost, sd.special_attack_boost, sd.special_defense_boost,
                                 sd.speed_boost, sd.accuracy_boost, sd.evasion_boost]
                                    .iter()
                                    .any(|b| !(-6..=6).contains(b))
                            });
                            if out {
                                bad += 1;
                                let key = format!("{m1:?} / {m2:?}");
                                if seen.insert(key.clone()) && seen.len() <= 12 {
                                    eprintln!("STAGE {v}: {key}\n  {:?}", o.instruction_list.iter().filter(|i| format!("{i:?}").contains("Boost")).collect::<Vec<_>>());
                                }
                            }
                            s.reverse_instructions(&o.instruction_list);
                        }
                    }
                }
            }
        }
        eprintln!("move pairs {pairs}, outcomes past the stages' limits {bad} ({} kinds)", seen.len());
        assert_eq!(bad, 0);
    }

    /// The stages near their limits with the abilities that change stage changes (Contrary,
    /// Simple, ...) and the moves that change them a lot: no outcome past -6..6 (the search's
    /// evaluation panicked on a +7, 2026-10-21; `fuzz_stage_limits` has no such sets)
    #[test]
    fn stage_changes_stay_within_the_limits() {
        use poke_engine::choices::Choices;
        use poke_engine::engine::abilities::Abilities;
        let base = State::deserialize(include_str!("../../../tests/fixtures/engine_state_6v6.txt").lines().next().unwrap());
        let mut bad = vec![];
        let abilities = [Abilities::CONTRARY, Abilities::SIMPLE, Abilities::NONE, Abilities::DEFIANT, Abilities::COMPETITIVE, Abilities::MOODY, Abilities::SPEEDBOOST, Abilities::ANGERPOINT, Abilities::BERSERK, Abilities::WEAKARMOR, Abilities::STAMINA, Abilities::MOXIE, Abilities::BEASTBOOST, Abilities::JUSTIFIED, Abilities::RATTLED, Abilities::STEAMENGINE, Abilities::WATERCOMPACTION, Abilities::MIRRORARMOR, Abilities::OPPORTUNIST, Abilities::GUARDDOG];
        let moves = [Choices::LEAFSTORM, Choices::DRACOMETEOR, Choices::OVERHEAT, Choices::CLOSECOMBAT, Choices::SHELLSMASH, Choices::BELLYDRUM, Choices::SWORDSDANCE, Choices::NASTYPLOT, Choices::QUIVERDANCE, Choices::CURSE, Choices::SUPERPOWER, Choices::MAKEITRAIN, Choices::SPINOUT, Choices::FILLETAWAY, Choices::CLANGOROUSSOUL, Choices::ACUPRESSURE, Choices::GROWTH, Choices::TAILGLOW, Choices::GEOMANCY, Choices::SNARL, Choices::PARTINGSHOT, Choices::MEMENTO, Choices::CHARM, Choices::SCREECH, Choices::METALSOUND, Choices::FAKETEARS, Choices::FEATHERDANCE, Choices::TICKLE, Choices::NOBLEROAR, Choices::BABYDOLLEYES, Choices::PSYCHUP, Choices::SPECTRALTHIEF, Choices::POWERTRIP, Choices::STOREDPOWER, Choices::TOPSYTURVY, Choices::HAZE, Choices::DEFOG, Choices::SCALESHOT, Choices::TRIPLEARROWS, Choices::ROCKSMASH, Choices::FLAMECHARGE, Choices::TRAILBLAZE, Choices::TORCHSONG, Choices::POWERUPPUNCH, Choices::DIAMONDSTORM, Choices::METEORMASH, Choices::ARMORCANNON, Choices::HEADLONGRUSH, Choices::VCREATE, Choices::HAMMERARM, Choices::ICEHAMMER, Choices::LUNGE, Choices::TROPKICK, Choices::SPIRITBREAK, Choices::MYSTICALFIRE, Choices::STRUGGLEBUG, Choices::ELECTROWEB, Choices::ICYWIND, Choices::BULLDOZE, Choices::ROCKTOMB, Choices::SKITTERSMACK, Choices::BITTERMALICE, Choices::CHILLINGWATER, Choices::POUNCE, Choices::FIRELASH, Choices::THUNDEROUSKICK, Choices::GRAVAPPLE, Choices::BREAKINGSWIPE, Choices::CRUNCH, Choices::SHADOWBALL, Choices::MOONBLAST, Choices::ENERGYBALL, Choices::FOCUSBLAST, Choices::EARTHPOWER, Choices::PSYCHIC, Choices::IRONTAIL, Choices::BUGBUZZ, Choices::LIQUIDATION];
        let names = |s: &State| [&s.side_one, &s.side_two].map(|sd| [sd.attack_boost, sd.defense_boost, sd.special_attack_boost, sd.special_defense_boost, sd.speed_boost, sd.accuracy_boost, sd.evasion_boost]);
        for &ab in &abilities {
            for &ab2 in &[Abilities::NONE, Abilities::CONTRARY, Abilities::SIMPLE, Abilities::DEFIANT, Abilities::COMPETITIVE, Abilities::MIRRORARMOR] {
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
                        let m1 = o1.iter().find(|m| matches!(m, MoveChoice::Move(PokemonMoveIndex::M0))).cloned();
                        let Some(m1) = m1 else { continue };
                        for m2 in o2.iter().take(3) {
                            let outs = generate_instructions_from_move_pair(&mut s, &m1, m2, false);
                            for o in &outs {
                                s.apply_instructions(&o.instruction_list);
                                if names(&s).iter().flatten().any(|b| !(-6..=6).contains(b)) && bad.len() < 20 {
                                    bad.push(format!("{ab:?} vs {ab2:?} at {v}: {mv:?} / {m2:?} -> {:?}", names(&s)));
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
        let mut pc = PathCtx::new(Some(&base));
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
            ctx.reveal[0 + state.side_one.active_index as usize] & (1 << 4),
            0
        );
        assert_eq!(ctx.turn, 11);
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
        let mut pc = PathCtx::new(Some(&base));
        let m = MoveChoice::Move(PokemonMoveIndex::M0);
        pc.push(&state, &m, &m);
        let outcomes = generate_instructions_from_move_pair(&mut state, &m, &m, false);
        for o in &outcomes {
            let mut st = state.clone();
            st.apply_instructions(&o.instruction_list);
            let mut p = PathCtx {
                pending: pc.pending,
                steps: pc.steps.clone(),
                ..PathCtx::new(Some(&base))
            };
            p.settle(&o.instruction_list, &st);
            let step = p.steps.last().unwrap();
            assert!(step.one.kind == 0 && step.one.prevented, "asleep: {step:?}");
            assert!(step.two.kind == 1, "their move came: {step:?}");
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

    /// 2026-10-21: a node's cached logits (from the state that created it) set its priors only
    /// for the same options -- not where they were computed with our active fainted (moves
    /// -inf) or with another active
    #[test]
    fn cached_logits_serve_only_the_same_options() {
        let s = fixture();
        let (o1, _) = s.get_all_options();
        let avail: Vec<(usize, MoveChoice)> = o1.into_iter().enumerate().collect();
        assert!(avail.iter().any(|(_, mc)| matches!(mc, MoveChoice::Move(_))));
        let active = s.side_one.active_index;
        let n = crate::features::N_ACTIONS;
        let all = [0.5f32; crate::features::N_ACTIONS];
        assert!(cached_logits_fit(&(all, active), &s, &avail));
        // created in a forced switch: only the switch slots are finite
        let mut forced = [f32::NEG_INFINITY; crate::features::N_ACTIONS];
        forced[8..n].fill(0.5);
        assert!(!cached_logits_fit(&(forced, active), &s, &avail));
        let switches: Vec<(usize, MoveChoice)> =
            avail.iter().copied().filter(|(_, mc)| matches!(mc, MoveChoice::Switch(_))).collect();
        assert!(cached_logits_fit(&(forced, active), &s, &switches));
        // created with another active
        let other = if active == PokemonIndex::P0 { PokemonIndex::P1 } else { PokemonIndex::P0 };
        assert!(!cached_logits_fit(&(all, other), &s, &avail));
    }

    /// How often a node's cached logits do not fit its first selection, in real positions
    /// (ALPHA_STATES: one state per line; ALPHA_MODEL: a run): 2026-10-21, the search review
    #[test]
    #[ignore]
    fn measure_cached_logits_fit() {
        use std::sync::atomic::Ordering;
        let (Ok(states), Ok(model)) = (std::env::var("ALPHA_STATES"), std::env::var("ALPHA_MODEL")) else {
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
            search(&mut worlds, &[Context::default()], Duration::ZERO, 800, &cfg, Some(1));
            n += 1;
        }
        let (bad, ok) = (CACHE_FIT[0].load(Ordering::Relaxed), CACHE_FIT[1].load(Ordering::Relaxed));
        let (diff, same) = (PHASE_SAME[0].load(Ordering::Relaxed), PHASE_SAME[1].load(Ordering::Relaxed));
        println!("node visits after the first in another public phase (actives, forced switches) than the first: {diff} of {} ({:.2}%)",
                 diff + same, 100.0 * diff as f64 / (diff + same).max(1) as f64);
        println!("{n} searches x 800: cached logits did not fit {bad} of {} first selections ({:.2}%)",
                 bad + ok, 100.0 * bad as f64 / (bad + ok).max(1) as f64);
    }
}
