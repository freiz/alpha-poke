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
//! * Chance: the outcome of a joint action is sampled in the current world each time. Below
//!   ``chance_depth`` (shallow nodes) children are split by an observable outcome signature
//!   (both actives, HP in eighths, status, faints, main boosts; world-independent), so e.g.
//!   "they were KO'd" and "they survived" get separate subtrees; deeper it is open-loop. Instruction lists are cached per (joint action, world) at the root
//!   only: poke-engine instructions carry absolute old / new values, and below the root the
//!   same node is reached in different states (different sampled outcomes above it), so a
//!   cached list would apply and reverse the wrong values.
//! * Leaf value: sigmoid(evaluate(state) - that world's root evaluation), as poke-engine.
//! * Networks (design D13): the v1 MLP (`net`) or the transformer (`tnet`, with a `Context` per
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
use poke_engine::state::{PokemonIndex, Side, State};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use rustc_hash::{FxHashMap, FxHasher};
use std::hash::{Hash, Hasher};
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
    /// side one's policy logits from the forward pass that valued this node as a leaf
    pub logits1: Option<Box<[f32; crate::features::N_ACTIONS]>>,
    /// batched search: created as a leaf whose network evaluation has not come back yet
    pub pending: bool,
}

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
            });
            arms.len() - 1
        }
    }
}

#[derive(Clone)]
pub struct Config {
    pub c: f32,
    /// cache the root's instruction lists per (joint action, world)
    pub cache_root: bool,
    /// branch on damage rolls for nodes shallower than this (poke-engine: root and its children)
    pub branch_depth: u16,
    /// split children by the observable outcome for nodes shallower than this (0 = open-loop)
    pub chance_depth: u16,
    /// value network for the leaves (design D13); None = poke-engine's handcrafted evaluation
    pub net: Option<std::sync::Arc<crate::net::Net>>,
    /// PUCT with the network's policy priors (needs `net`); else decoupled UCB1
    pub use_policy: bool,
    /// also the opponent's priors (its view, one more forward pass per node); else UCB1 for it
    pub policy_opponent: bool,
    pub c_puct: f32,
    /// leaf values from the network; false = handcrafted evaluation even with `net` (priors only)
    pub net_value: bool,
    /// the transformer instead of `net` (needs one `Context` per world)
    pub tnet: Option<Arc<TNet>>,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            c: std::f32::consts::SQRT_2,
            cache_root: true,
            branch_depth: 2,
            chance_depth: 0,
            net: None,
            use_policy: false,
            policy_opponent: true,
            c_puct: 1.0,
            net_value: true,
            tnet: None,
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
    pub iterations: u32,
    pub nodes: usize,
    pub max_depth: u16,
}

/// What both players observe after a turn, independent of the opponent's hidden details:
/// active slots, HP in eighths of max HP (max HP differs between worlds), status, faints and
/// the main boosts.
pub fn outcome_signature(state: &State) -> u64 {
    let mut h = FxHasher::default();
    for side in [&state.side_one, &state.side_two] {
        let a = side.get_active_immutable();
        (side.active_index as u8).hash(&mut h);
        let eighths = if a.maxhp > 0 {
            (a.hp.max(0) as i32 * 8 + a.maxhp as i32 - 1) / a.maxhp as i32
        } else {
            0
        };
        eighths.hash(&mut h);
        (a.status as u8).hash(&mut h);
        side.pokemon
            .into_iter()
            .filter(|p| p.hp <= 0)
            .count()
            .hash(&mut h);
        (
            side.attack_boost,
            side.special_attack_boost,
            side.speed_boost,
        )
            .hash(&mut h);
    }
    h.finish()
}

/// Value of a non-terminal leaf for side one: the value network if there is one (its residual
/// uses the handcrafted evaluation), else poke-engine's leaf value relative to the root.
fn leaf_value(state: &State, root_eval: f32, cfg: &Config, path: &PathCtx) -> f32 {
    if cfg.net_value {
        if let (Some(tnet), Some(ctx)) = (&cfg.tnet, path.base) {
            let x = Input::new(state, &path.context(ctx), false, evaluate(state));
            return 1.0 / (1.0 + (-tnet.value(&x)).exp());
        }
        if let Some(net) = &cfg.net {
            let logit = net.value(&crate::features::featurize(state), evaluate(state));
            return 1.0 / (1.0 + (-logit).exp());
        }
    }
    sigmoid(evaluate(state) - root_eval)
}

/// What the descent adds to a world's context: the decision steps taken, the bits they reveal,
/// the main steps (turns) completed.
pub(crate) struct PathCtx<'a> {
    base: Option<&'a Context>,
    steps: Vec<Step>,
    reveal: [u8; 12],
    mains: i32,
}

impl<'a> PathCtx<'a> {
    pub(crate) fn new(base: Option<&'a Context>) -> Self {
        PathCtx {
            base,
            steps: Vec::new(),
            reveal: base.map_or([0; 12], |c| c.reveal),
            mains: 0,
        }
    }

    /// Record the joint action about to be applied in `state`.
    pub(crate) fn push(&mut self, state: &State, m1: &MoveChoice, m2: &MoveChoice) {
        if self.base.is_none() {
            return;
        }
        if !(state.side_one.force_switch || state.side_two.force_switch) {
            self.mains += 1;
        }
        self.steps.push(Step {
            one: Act::of_choice(&state.side_one, m1),
            two: Act::of_choice(&state.side_two, m2),
        });
        for (off, side, mc) in [(0, &state.side_one, m1), (6, &state.side_two, m2)] {
            match mc {
                MoveChoice::Move(i) | MoveChoice::MoveTera(i) => {
                    let a = off + side.active_index as usize;
                    self.reveal[a] |= 1 | (1 << (4 + *i as usize));
                    if matches!(mc, MoveChoice::MoveTera(_)) {
                        self.reveal[a] |= 1 << 3;
                    }
                }
                MoveChoice::Switch(p) => self.reveal[off + *p as usize] |= 1,
                _ => {}
            }
        }
    }

    /// The world's context at the current node.
    pub(crate) fn context(&self, base: &Context) -> Context {
        let mut history: Vec<Step> = base.history.clone();
        history.extend_from_slice(&self.steps);
        let cut = history.len().saturating_sub(HIST);
        Context {
            reveal: self.reveal,
            rating: base.rating,
            turn: base.turn + self.mains,
            history: history.split_off(cut),
        }
    }
}

pub(crate) fn sigmoid(x: f32) -> f32 {
    1.0 / (1.0 + (-0.0125 * x).exp())
}

/// Softmax of `logits` over the available options; their arms get the probabilities as priors.
pub(crate) fn set_priors(arms: &mut [Arm], avail: &[(usize, MoveChoice)], logits: &[f32]) {
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
    for (j, &(i, _)) in avail.iter().enumerate() {
        arms[i].prior = if z > 0.0 {
            exps[j] / z
        } else {
            1.0 / avail.len() as f32
        };
    }
}

/// PUCT over the available arms: Q + c * P * sqrt(N) / (1 + n); N = visits of the available
/// arms (availability, as the UCB variant); unvisited arms get the mean Q of the visited ones.
pub(crate) fn select_puct(
    arms: &[Arm],
    avail: &[(usize, MoveChoice)],
    c: f32,
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
    let uniform = 1.0 / avail.len() as f32;
    let mut best = avail[0];
    let mut best_u = f32::MIN;
    for &(i, mc) in avail {
        let a = &arms[i];
        let q = if a.visits > 0 { a.mean() } else { fpu };
        let p = if a.prior >= 0.0 { a.prior } else { uniform };
        let u = q + c * p * sq / (1.0 + a.visits as f32);
        if u > best_u {
            best_u = u;
            best = (i, mc);
        }
    }
    best
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
        let score = loop {
            let over = state.battle_is_over();
            if over != 0.0 && node != 0 {
                break if over > 0.0 { 1.0 } else { 0.0 };
            }
            let (o1, o2) = if node == 0 {
                state.root_get_all_options()
            } else {
                state.get_all_options()
            };
            let n = &mut self.nodes[node as usize];
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
                    let ev = evaluate(state);
                    let lc = pc.context(base);
                    let cached = n.logits1.take();
                    let need_own = cached.is_none();
                    let own = need_own.then(|| Input::new(state, &lc, false, ev));
                    let l1 = match cached {
                        Some(l) => *l,
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
                } else if let Some(net) = &cfg.net {
                    let ev = evaluate(state);
                    let l1 = match n.logits1.take() {
                        Some(l) => *l,
                        None => {
                            net.forward(&crate::features::featurize_view(state, false), ev)
                                .logits
                        }
                    };
                    set_priors(&mut n.s1, &av1, &l1);
                    if cfg.policy_opponent {
                        let f2 = crate::features::featurize_view(state, true);
                        set_priors(&mut n.s2, &av2, &net.forward(&f2, -ev).logits);
                    }
                }
                n.priors_set = true;
            }
            let (i1, m1) = if cfg.use_policy {
                select_puct(&n.s1, &av1, cfg.c_puct)
            } else {
                select(&n.s1, &av1, cfg.c)
            };
            let (i2, m2) = if cfg.use_policy && cfg.policy_opponent {
                select_puct(&n.s2, &av2, cfg.c_puct)
            } else {
                select(&n.s2, &av2, cfg.c)
            };
            let depth = n.depth;
            if m1 == MoveChoice::None && m2 == MoveChoice::None {
                break leaf_value(state, root_eval, cfg, &pc);
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
                root_step = Some((i1, i2, k));
            } else {
                let mut outcomes = generate_instructions_from_move_pair(state, &m1, &m2, branch);
                let k = sample(&outcomes, rng);
                let instructions = outcomes.swap_remove(k).instruction_list;
                state.apply_instructions(&instructions);
                applied.push(instructions);
            }
            path.push((node, i1, i2));
            let sig = if depth < cfg.chance_depth {
                outcome_signature(state)
            } else {
                0
            };
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
                    break if over > 0.0 {
                        1.0
                    } else if over < 0.0 {
                        0.0
                    } else if let (true, true, Some(tnet), Some(base)) =
                        (cfg.use_policy, cfg.net_value, &cfg.tnet, pc.base)
                    {
                        // one forward pass: the leaf value and the new node's own priors
                        let x = Input::new(state, &pc.context(base), false, evaluate(state));
                        let out = tnet.forward(&x);
                        self.nodes[child as usize].logits1 = Some(Box::new(out.logits));
                        1.0 / (1.0 + (-out.value).exp())
                    } else if let (true, true, Some(net)) =
                        (cfg.use_policy, cfg.net_value, &cfg.net)
                    {
                        // one forward pass: the leaf value and the new node's own priors
                        let out = net.forward(&crate::features::featurize(state), evaluate(state));
                        self.nodes[child as usize].logits1 = Some(Box::new(out.logits));
                        1.0 / (1.0 + (-out.value).exp())
                    } else {
                        leaf_value(state, root_eval, cfg, &pc)
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
            let a2 = &mut n.s2[i2 as usize];
            a2.visits += 1;
            a2.total += 1.0 - score;
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
    fn shallow_children_are_split_by_observable_outcome() {
        let run = |chance_depth: u16| {
            let mut worlds = [fixture()];
            let cfg = Config {
                chance_depth,
                ..Config::default()
            };
            let mut tree = Tree::new();
            let mut rng = StdRng::seed_from_u64(5);
            let eval = evaluate(&worlds[0]);
            for _ in 0..5000 {
                tree.iterate(&mut worlds[0], 0, eval, &cfg, None, &mut rng);
            }
            let root_children = tree.children.keys().filter(|k| k.0 == 0).count();
            let joint_actions: std::collections::HashSet<_> = tree
                .children
                .keys()
                .filter(|k| k.0 == 0)
                .map(|k| (k.1, k.2))
                .collect();
            (root_children, joint_actions.len())
        };
        let (open_children, open_joint) = run(0);
        assert_eq!(open_children, open_joint); // open-loop: one child per joint action
        let (closed_children, closed_joint) = run(2);
        assert!(
            closed_children > closed_joint,
            "{closed_children} children for {closed_joint} joint actions"
        );
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
    fn puct_with_network_priors() {
        let dir = std::path::Path::new("../../data/train/v1/runs/v1-medium-residual");
        let Ok(net) = crate::net::Net::load(dir) else {
            return; // no trained model in this checkout
        };
        let cfg = Config {
            net: Some(std::sync::Arc::new(net)),
            use_policy: true,
            ..Config::default()
        };
        let mut worlds = [fixture(), variant(Choices::SPLASH)];
        let before: Vec<String> = worlds.iter().map(|w| w.serialize()).collect();
        let mut tree = Tree::new();
        let mut rng = StdRng::seed_from_u64(11);
        let evals: Vec<f32> = worlds.iter().map(evaluate).collect();
        for it in 0..3000u32 {
            let w = (it % 2) as usize;
            tree.iterate(&mut worlds[w], w as u16, evals[w], &cfg, None, &mut rng);
        }
        let root = &tree.nodes[0];
        assert!(root.priors_set);
        let p1: f32 = root.s1.iter().map(|a| a.prior).sum();
        assert!((p1 - 1.0).abs() < 1e-3, "our root priors sum to {p1}");
        assert!(root.s2.iter().any(|a| a.prior > 0.0), "opponent priors set");
        let top = root
            .s1
            .iter()
            .max_by(|a, b| a.prior.total_cmp(&b.prior))
            .unwrap();
        assert!(top.visits > 0, "the highest-prior action is searched");
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
}
