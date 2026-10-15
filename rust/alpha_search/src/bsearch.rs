//! Batched ISMCTS for network evaluation on another device (GPU, design D13): the same tree,
//! selection and chance handling as `ismcts::Tree::iterate` (open loop), but the leaves are
//! collected in batches with virtual loss and evaluated outside (Python / PyTorch), then backed
//! up.
//!
//! * Tree parallel: `threads` threads descend the one shared tree at the same time, each in its
//!   own copies of the worlds. The tree is behind a lock taken for each step's selection,
//!   virtual loss and child lookup / creation; generating and applying the instructions, and
//!   copying a leaf, happen outside it. (Root-parallel independent trees were measured not to
//!   help: 8 trees of ~2k iterations each choose like one tree of 2k.)
//! * `collect(n)`: descents until `n` new leaves (round robin over the worlds). A descent ends
//!   in a terminal state (backed up at once), or creates a new node (a pending leaf: the leaf
//!   state is copied, the world restored), or reaches a pending node (a collision). Virtual
//!   loss: `vl` visits (with no value) along the path are counted at selection time, the real
//!   visit and value are put in when the batch comes back, so the descents of a batch spread
//!   out. A collision's virtual visits stay until the batch is applied (so the next descents
//!   avoid that path too), then they are taken back.
//! * The pending leaves' network inputs (side one's view + side two's, `tnet::Input`) are built
//!   in parallel and handed out as arrays; `apply` takes the value logits and policy logits. A
//!   new node gets both sides' priors from its own evaluation (in the world that created it).
//! * The root is evaluated first (its priors), before any descent.
//! * Pipelining: `collect` hands out only the leaves it adds (a batch can be collected while the
//!   previous one is being evaluated; its leaves count as pending), `apply` takes the oldest
//!   batch handed out.
//! * The root's instruction lists are cached per (joint action, world), shared by the threads
//!   (the root state of a world is the same in every thread's copy).

use crate::extra::{ENT_EXTRA, GLOBAL_EXTRA};
use crate::features::{slot, HIST, HIST_DENSE, HIST_SPARSE, N_ACTIONS, N_ENTITIES, SPARSE};
use crate::ismcts::{
    add_root_noise, arm_index, label, sample, select_puct, set_priors, Config, Label, Node,
    PathCtx, Tree,
};
use crate::tnet::{Context, Input};
use poke_engine::engine::evaluate::evaluate;
use poke_engine::engine::generate_instructions::generate_instructions_from_move_pair;
use poke_engine::engine::state::MoveChoice;
use poke_engine::instruction::{Instruction, StateInstructions};
use poke_engine::state::State;
use rand::rngs::StdRng;
use rand::SeedableRng;
use std::sync::Arc;
use std::sync::Mutex;

/// `BatchSearch::record`: the root's search result per action slot.
#[derive(Debug, Default, Clone)]
pub struct Record {
    pub visits: [u32; N_ACTIONS],
    pub mean: [f32; N_ACTIONS],
    pub prior: [f32; N_ACTIONS],
    pub legal: [bool; N_ACTIONS],
    pub q: f32,
    pub opp_visits: [u32; N_ACTIONS],
    pub opp_unmapped: u32,
}

pub struct Pending {
    /// (node, our arm, their arm) from the root; empty for the root itself
    path: Vec<(u32, u16, u16)>,
    node: u32,
    state: State,
    /// the network inputs: side one's view, side two's (built by the thread that found it)
    inputs: Box<(Input, Input)>,
}

fn inputs(state: &State, ctx: &Context) -> Box<(Input, Input)> {
    let ev = evaluate(state);
    let own = Input::new(state, ctx, false, ev);
    let opp = own.flipped(state, ctx);
    Box::new((own, opp))
}

/// What the descending threads share (behind one lock).
pub struct Shared {
    pub tree: Tree,
    pub pending: Vec<Pending>,
    /// paths of this batch's collisions (their virtual visits are taken back in `apply`)
    collided: Vec<Vec<(u32, u16, u16)>>,
    /// the root's instruction lists per (our arm, their arm, world)
    root_cache: rustc_hash::FxHashMap<(u16, u16, u16), Arc<Vec<StateInstructions>>>,
    pub iterations: u32,
    pub collisions: u32,
    next_world: usize,
}

pub struct BatchSearch {
    /// one copy of the worlds per thread
    worlds: Vec<Vec<State>>,
    ctxs: Vec<Context>,
    root_evals: Vec<f32>,
    pub shared: Mutex<Shared>,
    cfg: Config,
    seed: u64,
    round: u64,
    /// virtual visits per descent
    vl: u32,
    /// seconds spent in collect: descents (with the leaves' inputs), packing
    pub timing: [f64; 2],
    /// pending leaves already handed out by `collect` (the oldest ones)
    returned: usize,
    /// sizes of the batches handed out and not applied yet, oldest first
    in_flight: std::collections::VecDeque<usize>,
}

/// The network inputs of a batch, row-major arrays (`rows` = 2 per pending leaf: side one's
/// view, then side two's).
#[derive(Default)]
pub struct Batch {
    pub rows: usize,
    pub sparse: Vec<i32>,
    pub dense: Vec<f32>,
    pub global: Vec<f32>,
    pub mask: Vec<u8>,
    pub hsparse: Vec<i32>,
    pub hdense: Vec<f32>,
    pub ent2: Vec<f32>,
    pub glob2: Vec<f32>,
    pub ent3: Vec<f32>,
    pub glob3: Vec<f32>,
    pub reveal: Vec<u8>,
    pub turn: Vec<i32>,
    pub rating: Vec<i32>,
    pub eval: Vec<f32>,
}

impl Batch {
    /// Append another batch's rows (cross-search batching, `collect_many`).
    pub fn extend(&mut self, o: Batch) {
        self.rows += o.rows;
        self.sparse.extend(o.sparse);
        self.dense.extend(o.dense);
        self.global.extend(o.global);
        self.mask.extend(o.mask);
        self.hsparse.extend(o.hsparse);
        self.hdense.extend(o.hdense);
        self.ent2.extend(o.ent2);
        self.glob2.extend(o.glob2);
        self.ent3.extend(o.ent3);
        self.glob3.extend(o.glob3);
        self.reveal.extend(o.reveal);
        self.turn.extend(o.turn);
        self.rating.extend(o.rating);
        self.eval.extend(o.eval);
    }

    fn push(&mut self, x: &Input) {
        self.rows += 1;
        self.sparse.extend_from_slice(&x.f.sparse);
        self.dense.extend_from_slice(&x.f.dense);
        self.global.extend_from_slice(&x.f.global);
        self.mask.extend_from_slice(&x.f.mask);
        self.hsparse.extend_from_slice(&x.hsparse);
        self.hdense.extend_from_slice(&x.hdense);
        self.ent2.extend_from_slice(&x.ent2);
        self.glob2.extend_from_slice(&x.glob2);
        self.ent3.extend_from_slice(&x.ent3);
        self.glob3.extend_from_slice(&x.glob3);
        self.reveal.extend_from_slice(&x.reveal);
        self.turn.push(x.turn);
        self.rating.extend_from_slice(&x.rating);
        self.eval.push(x.eval);
        debug_assert_eq!(self.sparse.len(), self.rows * N_ENTITIES * SPARSE);
        debug_assert_eq!(self.hsparse.len(), self.rows * HIST * HIST_SPARSE);
        debug_assert_eq!(self.hdense.len(), self.rows * HIST * HIST_DENSE);
        debug_assert_eq!(self.ent2.len(), self.rows * N_ENTITIES * ENT_EXTRA);
        debug_assert_eq!(self.glob2.len(), self.rows * GLOBAL_EXTRA);
    }
}

enum Descent {
    Terminal(f32),
    Leaf(Box<State>, Box<(Input, Input)>),
    Collision,
}

impl Shared {
    /// The real visit and value along a path that carries `vl` virtual visits.
    fn backup(&mut self, path: &[(u32, u16, u16)], leaf: u32, score: f32, vl: u32) {
        self.tree.nodes[leaf as usize].visits += 1;
        self.undo(path, vl - 1);
        for &(nd, i1, i2) in path.iter().rev() {
            let n = &mut self.tree.nodes[nd as usize];
            n.s1[i1 as usize].total += score;
            n.s2[i2 as usize].total += 1.0 - score;
        }
    }

    /// Take back `k` virtual visits along a path.
    fn undo(&mut self, path: &[(u32, u16, u16)], k: u32) {
        for &(nd, i1, i2) in path {
            let n = &mut self.tree.nodes[nd as usize];
            n.visits -= k;
            n.s1[i1 as usize].visits -= k;
            n.s2[i2 as usize].visits -= k;
        }
    }
}

/// One descent in `state` (world `w`, this thread's copy) through the shared tree.
#[allow(clippy::too_many_arguments)]
fn descend(
    shared: &Mutex<Shared>,
    state: &mut State,
    w: u16,
    ctx: &Context,
    root_eval: f32,
    cfg: &Config,
    vl: u32,
    rng: &mut StdRng,
) {
    let mut pc = PathCtx::new(Some(ctx));
    let mut path: Vec<(u32, u16, u16)> = Vec::with_capacity(16);
    let mut applied: Vec<Vec<Instruction>> = Vec::with_capacity(16);
    let mut root_step: Option<(Arc<Vec<StateInstructions>>, usize)> = None;
    let mut node: u32 = 0;
    let result = loop {
        let over = state.battle_is_over();
        if over != 0.0 && node != 0 {
            break Descent::Terminal(if over > 0.0 { 1.0 } else { 0.0 });
        }
        let (o1, o2) = if node == 0 {
            state.root_get_all_options()
        } else {
            state.get_all_options()
        };
        let mut g = shared.lock().unwrap();
        let n: &mut Node = &mut g.tree.nodes[node as usize];
        if n.pending {
            break Descent::Collision;
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
        let (i1, m1) = select_puct(&n.s1, &av1, cfg.c_puct);
        let (i2, m2) = if cfg.policy_opponent {
            select_puct(&n.s2, &av2, cfg.c_puct)
        } else {
            crate::ismcts::select(&n.s2, &av2, cfg.c)
        };
        let depth = n.depth;
        if m1 == MoveChoice::None && m2 == MoveChoice::None {
            // no decision for either side (should not happen): handcrafted leaf value
            break Descent::Terminal(crate::ismcts::sigmoid(evaluate(state) - root_eval));
        }
        // virtual loss: `vl` visits are counted now, the value when the evaluation is back
        n.visits += vl;
        n.s1[i1].visits += vl;
        n.s2[i2].visits += vl;
        let (i1, i2) = (i1 as u16, i2 as u16);
        path.push((node, i1, i2));
        let key = (node, i1, i2, 0u64);
        let (next, created) = match g.tree.children.get(&key) {
            Some(&c) if g.tree.nodes[c as usize].pending => break Descent::Collision,
            Some(&c) => (c, false),
            None => {
                let c = g.tree.nodes.len() as u32;
                g.tree.nodes.push(Node {
                    depth: depth + 1,
                    pending: true,
                    ..Node::default()
                });
                g.tree.children.insert(key, c);
                (c, true)
            }
        };
        let cached = (node == 0)
            .then(|| g.root_cache.get(&(i1, i2, w)).cloned())
            .flatten();
        drop(g);
        pc.push(state, &m1, &m2);
        let branch = depth < cfg.branch_depth;
        if node == 0 {
            let outcomes = match cached {
                Some(o) => o,
                None => {
                    let o = Arc::new(generate_instructions_from_move_pair(
                        state, &m1, &m2, branch,
                    ));
                    let mut g = shared.lock().unwrap();
                    g.root_cache.entry((i1, i2, w)).or_insert(o).clone()
                }
            };
            let k = sample(&outcomes, rng);
            state.apply_instructions(&outcomes[k].instruction_list);
            pc.settle(&outcomes[k].instruction_list, state);
            root_step = Some((outcomes, k));
        } else {
            let mut outcomes = generate_instructions_from_move_pair(state, &m1, &m2, branch);
            let k = sample(&outcomes, rng);
            let instructions = outcomes.swap_remove(k).instruction_list;
            state.apply_instructions(&instructions);
            pc.settle(&instructions, state);
            applied.push(instructions);
        }
        node = next;
        if created {
            let over = state.battle_is_over();
            if over != 0.0 {
                shared.lock().unwrap().tree.nodes[node as usize].pending = false;
                break Descent::Terminal(if over > 0.0 { 1.0 } else { 0.0 });
            }
            // the leaf's inputs now, in this thread, outside the lock
            let x = inputs(state, &pc.context(ctx));
            break Descent::Leaf(Box::new(state.clone()), x);
        }
    };
    for ins in applied.iter().rev() {
        state.reverse_instructions(ins);
    }
    if let Some((outcomes, k)) = root_step {
        state.reverse_instructions(&outcomes[k].instruction_list);
    }
    let mut g = shared.lock().unwrap();
    match result {
        Descent::Terminal(score) => {
            g.backup(&path, node, score, vl);
            g.iterations += 1;
        }
        Descent::Collision => {
            g.collided.push(path);
            g.collisions += 1;
        }
        Descent::Leaf(state, inputs) => g.pending.push(Pending {
            path,
            node,
            state: *state,
            inputs,
        }),
    }
}

impl BatchSearch {
    pub fn new(
        worlds: Vec<State>,
        ctxs: Vec<Context>,
        cfg: Config,
        seed: Option<u64>,
        threads: usize,
        vl: u32,
    ) -> Self {
        assert_eq!(worlds.len(), ctxs.len(), "one context per world");
        let root_evals = worlds.iter().map(evaluate).collect();
        let mut tree = Tree::new();
        tree.nodes[0].pending = true;
        let pending = vec![Pending {
            path: Vec::new(),
            node: 0,
            state: worlds[0].clone(),
            inputs: inputs(&worlds[0], &ctxs[0]),
        }];
        BatchSearch {
            worlds: vec![worlds; threads.max(1)],
            ctxs,
            root_evals,
            shared: Mutex::new(Shared {
                tree,
                pending,
                collided: Vec::new(),
                root_cache: Default::default(),
                iterations: 0,
                collisions: 0,
                next_world: 0,
            }),
            cfg,
            seed: seed.unwrap_or_else(rand::random),
            round: 0,
            vl: vl.max(1),
            timing: [0.0; 2],
            returned: 0,
            in_flight: Default::default(),
        }
    }

    /// Descents until `n` pending leaves (none while the root is pending); their inputs.
    pub fn collect(&mut self, n: usize) -> Batch {
        let t0 = std::time::Instant::now();
        let root_pending = self.shared.get_mut().unwrap().tree.nodes[0].pending;
        let target = self.returned + n;
        if !root_pending {
            self.round += 1;
            let threads = self.worlds.len();
            let (shared, ctxs, evals, cfg) =
                (&self.shared, &self.ctxs, &self.root_evals, &self.cfg);
            let (seed, round, vl) = (self.seed, self.round, self.vl);
            std::thread::scope(|scope| {
                for (t, worlds) in self.worlds.iter_mut().enumerate() {
                    scope.spawn(move || {
                        let mut rng = StdRng::seed_from_u64(
                            seed ^ round.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ (t as u64 * 7919),
                        );
                        for _ in 0..(4 * n).div_ceil(threads) {
                            let w = {
                                let mut g = shared.lock().unwrap();
                                if g.pending.len() >= target {
                                    break;
                                }
                                g.next_world += 1;
                                (g.next_world - 1) % worlds.len()
                            };
                            descend(
                                shared,
                                &mut worlds[w],
                                w as u16,
                                &ctxs[w],
                                evals[w],
                                cfg,
                                vl,
                                &mut rng,
                            );
                        }
                    });
                }
            });
        }
        let t1 = std::time::Instant::now();
        self.timing[0] += (t1 - t0).as_secs_f64();
        let vl = self.vl;
        let g = self.shared.get_mut().unwrap();
        if g.pending.is_empty() {
            // no leaf this round (nothing to apply): take the collisions' virtual visits back
            for path in std::mem::take(&mut g.collided) {
                g.undo(&path, vl);
            }
        }
        let mut b = Batch::default();
        for p in &g.pending[self.returned..] {
            b.push(&p.inputs.0);
            b.push(&p.inputs.1);
        }
        let new = g.pending.len() - self.returned;
        if new > 0 {
            self.in_flight.push_back(new);
        }
        self.returned = g.pending.len();
        self.timing[1] += t1.elapsed().as_secs_f64();
        b
    }

    /// leaves in the oldest batch handed out and not applied yet
    pub fn n_pending(&mut self) -> usize {
        self.in_flight.front().copied().unwrap_or(0)
    }

    /// The batch's outputs: value logits [rows] (side one's view rows are used) and policy logits
    /// [rows * 14] (-inf on illegal slots), in `collect`'s row order.
    pub fn apply(&mut self, values: &[f32], logits: &[f32]) {
        let (policy_opponent, vl) = (self.cfg.policy_opponent, self.vl);
        let (noise_eps, noise_conc, seed) =
            (self.cfg.root_noise_eps, self.cfg.root_noise_conc, self.seed);
        let k = self.in_flight.pop_front().expect("no batch to apply");
        self.returned -= k;
        let g = self.shared.get_mut().unwrap();
        for path in std::mem::take(&mut g.collided) {
            g.undo(&path, vl);
        }
        let pending: Vec<Pending> = g.pending.drain(..k).collect();
        assert_eq!(values.len(), 2 * pending.len());
        assert_eq!(logits.len(), 2 * pending.len() * N_ACTIONS);
        for (k, p) in pending.into_iter().enumerate() {
            let l1 = &logits[2 * k * N_ACTIONS..(2 * k + 1) * N_ACTIONS];
            let l2 = &logits[(2 * k + 1) * N_ACTIONS..(2 * k + 2) * N_ACTIONS];
            // the node's options in the world that created it, its priors
            let (o1, o2) = if p.node == 0 {
                p.state.root_get_all_options()
            } else {
                p.state.get_all_options()
            };
            let n = &mut g.tree.nodes[p.node as usize];
            let av1: Vec<(usize, MoveChoice)> = o1
                .into_iter()
                .map(|mc| (arm_index(&mut n.s1, label(&p.state.side_one, &mc)), mc))
                .collect();
            let av2: Vec<(usize, MoveChoice)> = o2
                .into_iter()
                .map(|mc| (arm_index(&mut n.s2, label(&p.state.side_two, &mc)), mc))
                .collect();
            set_priors(&mut n.s1, &av1, l1);
            if policy_opponent {
                set_priors(&mut n.s2, &av2, l2);
            }
            if p.node == 0 && noise_eps > 0.0 {
                let mut rng = StdRng::seed_from_u64(seed ^ 0xD1B5_4A32_D192_ED03);
                let (e, c) = (noise_eps, noise_conc);
                add_root_noise(&mut n.s1, &av1, e, c, &mut rng);
                if policy_opponent {
                    add_root_noise(&mut n.s2, &av2, e, c, &mut rng);
                }
            }
            n.priors_set = true;
            n.pending = false;
            if p.node != 0 {
                let v = 1.0 / (1.0 + (-values[2 * k]).exp());
                g.backup(&p.path, p.node, v, vl);
                g.iterations += 1;
            }
        }
    }

    /// The pending leaves evaluated by the CPU network: (value logits, policy logits) in
    /// `collect`'s row order.
    pub fn evaluate_cpu(&mut self, net: &crate::tnet::TNet) -> (Vec<f32>, Vec<f32>) {
        let k = self.n_pending();
        let g = self.shared.get_mut().unwrap();
        let outs = crate::par_map(&g.pending[..k], |p| {
            (net.forward(&p.inputs.0), net.forward(&p.inputs.1))
        });
        let (mut values, mut logits) = (Vec::new(), Vec::new());
        for (a, b) in outs {
            values.extend([a.value, b.value]);
            logits.extend_from_slice(&a.logits);
            logits.extend_from_slice(&b.logits);
        }
        (values, logits)
    }

    /// Our root actions: (label, visits, mean value).
    pub fn root(&mut self) -> Vec<(Label, u32, f32)> {
        self.shared.get_mut().unwrap().tree.nodes[0]
            .s1
            .iter()
            .map(|a| (a.label, a.visits, a.mean()))
            .collect()
    }

    /// The search result at the root as training targets (design D15-3), in the network's
    /// action slots (`features::slot`; side one = us, side two = the opponent, each relative
    /// to itself): visits, mean value (our win probability), network prior (< 0 = none), legal
    /// options; our root value q (visit-weighted mean). The opponent's labels are mapped
    /// through world 0 (its moves differ between worlds): visits of moves world 0's opponent
    /// does not have are counted in `opp_unmapped`.
    pub fn record(&mut self) -> Record {
        let w0 = self.worlds[0][0].clone();
        let root = &self.shared.get_mut().unwrap().tree.nodes[0];
        let mut r = Record::default();
        let (mut tv, mut tt) = (0u64, 0.0f64);
        for a in &root.s1 {
            if let Some(i) = crate::ismcts::our_choice(&w0, a.label).and_then(|mc| slot(&mc)) {
                r.visits[i] = a.visits;
                r.mean[i] = a.mean();
                r.prior[i] = a.prior;
                r.legal[i] = true;
            }
            tv += a.visits as u64;
            tt += a.total as f64;
        }
        r.q = if tv > 0 { (tt / tv as f64) as f32 } else { 0.5 };
        for a in &root.s2 {
            match crate::ismcts::their_choice(&w0, a.label).and_then(|mc| slot(&mc)) {
                Some(i) => r.opp_visits[i] += a.visits,
                None => r.opp_unmapped += a.visits,
            }
        }
        r
    }

    /// (iterations, collisions, nodes)
    pub fn stats(&mut self) -> (u32, u32, usize) {
        let g = self.shared.get_mut().unwrap();
        (g.iterations, g.collisions, g.tree.nodes.len())
    }

    pub fn world0(&self) -> &State {
        &self.worlds[0][0]
    }
}
