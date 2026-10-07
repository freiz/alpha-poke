//! Batched ISMCTS for network evaluation on another device (GPU, design D13): the same tree,
//! selection and chance handling as `ismcts::Tree::iterate`, but the leaves are collected in
//! batches with virtual loss and evaluated outside (Python / PyTorch), then backed up.
//!
//! * `collect(n)`: up to `n` descents (round robin over the worlds). Each one either ends in a
//!   terminal state (backed up at once), or creates a new node (a pending leaf: the leaf state
//!   is copied, the world restored), or reaches a pending node (a collision: undone). Virtual
//!   loss: the visits along the path are counted at selection time (with no value yet), so the
//!   next descents of the batch spread out; the values are added when the batch comes back.
//! * The pending leaves' network inputs (side one's view + side two's, `tnet::Input`) are built
//!   in parallel and handed out as arrays; `apply` takes the value logits and policy logits.
//!   A new node gets both sides' priors from its own evaluation (in the world that created it).
//! * The root is evaluated first (its priors), before any descent.

use crate::extra::{ENT_EXTRA, GLOBAL_EXTRA};
use crate::features::{HIST, HIST_DENSE, HIST_SPARSE, N_ACTIONS, N_ENTITIES, SPARSE};
use crate::ismcts::{
    arm_index, label, outcome_signature, sample, select_puct, set_priors, Config, Label, Node,
    PathCtx, Tree,
};
use crate::tnet::{Context, Input};
use poke_engine::engine::evaluate::evaluate;
use poke_engine::engine::generate_instructions::generate_instructions_from_move_pair;
use poke_engine::engine::state::MoveChoice;
use poke_engine::instruction::Instruction;
use poke_engine::state::State;
use rand::rngs::StdRng;
use rand::SeedableRng;

pub struct Pending {
    /// (node, our arm, their arm) from the root; empty for the root itself
    path: Vec<(u32, u16, u16)>,
    node: u32,
    state: State,
    ctx: Context,
}

pub struct BatchSearch {
    pub worlds: Vec<State>,
    ctxs: Vec<Context>,
    root_evals: Vec<f32>,
    pub tree: Tree,
    cfg: Config,
    rng: StdRng,
    next_world: usize,
    pub pending: Vec<Pending>,
    pub iterations: u32,
    pub collisions: u32,
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
    pub reveal: Vec<u8>,
    pub turn: Vec<i32>,
    pub rating: Vec<i32>,
    pub eval: Vec<f32>,
}

impl Batch {
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
    Terminal,
    Leaf,
    Collision,
}

impl BatchSearch {
    pub fn new(worlds: Vec<State>, ctxs: Vec<Context>, cfg: Config, seed: Option<u64>) -> Self {
        assert_eq!(worlds.len(), ctxs.len(), "one context per world");
        let root_evals = worlds.iter().map(evaluate).collect();
        let mut tree = Tree::new();
        tree.nodes[0].pending = true;
        let pending = vec![Pending {
            path: Vec::new(),
            node: 0,
            state: worlds[0].clone(),
            ctx: ctxs[0].clone(),
        }];
        BatchSearch {
            worlds,
            ctxs,
            root_evals,
            tree,
            cfg,
            rng: match seed {
                Some(s) => StdRng::seed_from_u64(s),
                None => StdRng::from_os_rng(),
            },
            next_world: 0,
            pending,
            iterations: 0,
            collisions: 0,
        }
    }

    /// Up to `n` descents (fewer when the root is still pending); the pending leaves' inputs.
    pub fn collect(&mut self, n: usize) -> Batch {
        if self.pending.is_empty() {
            let mut attempts = 0;
            while self.pending.len() < n && attempts < 2 * n {
                attempts += 1;
                let w = self.next_world % self.worlds.len();
                self.next_world += 1;
                match self.descend(w) {
                    Descent::Collision => self.collisions += 1,
                    Descent::Terminal => self.iterations += 1,
                    Descent::Leaf => {}
                }
            }
        }
        let rows = crate::par_map(&self.pending, |p| {
            let ev = evaluate(&p.state);
            let own = Input::new(&p.state, &p.ctx, false, ev);
            let opp = own.flipped(&p.state, &p.ctx);
            (own, opp)
        });
        let mut b = Batch::default();
        for (own, opp) in &rows {
            b.push(own);
            b.push(opp);
        }
        b
    }

    /// The batch's outputs: value logits [rows] (side one's view rows are used) and policy logits
    /// [rows * 14] (-inf on illegal slots), in `collect`'s row order.
    pub fn apply(&mut self, values: &[f32], logits: &[f32]) {
        let pending = std::mem::take(&mut self.pending);
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
            let n = &mut self.tree.nodes[p.node as usize];
            let av1: Vec<(usize, MoveChoice)> = o1
                .into_iter()
                .map(|mc| (arm_index(&mut n.s1, label(&p.state.side_one, &mc)), mc))
                .collect();
            let av2: Vec<(usize, MoveChoice)> = o2
                .into_iter()
                .map(|mc| (arm_index(&mut n.s2, label(&p.state.side_two, &mc)), mc))
                .collect();
            set_priors(&mut n.s1, &av1, l1);
            if self.cfg.policy_opponent {
                set_priors(&mut n.s2, &av2, l2);
            }
            n.priors_set = true;
            n.pending = false;
            if p.node != 0 {
                let v = 1.0 / (1.0 + (-values[2 * k]).exp());
                self.backup(&p.path, p.node, v);
                self.iterations += 1;
            }
        }
    }

    /// Values along a path whose visits were counted at selection time (virtual loss).
    fn backup(&mut self, path: &[(u32, u16, u16)], leaf: u32, score: f32) {
        self.tree.nodes[leaf as usize].visits += 1;
        for &(nd, i1, i2) in path.iter().rev() {
            let n = &mut self.tree.nodes[nd as usize];
            n.s1[i1 as usize].total += score;
            n.s2[i2 as usize].total += 1.0 - score;
        }
    }

    /// Undo the virtual visits of a path that ended in a collision.
    fn undo(&mut self, path: &[(u32, u16, u16)]) {
        for &(nd, i1, i2) in path {
            let n = &mut self.tree.nodes[nd as usize];
            n.visits -= 1;
            n.s1[i1 as usize].visits -= 1;
            n.s2[i2 as usize].visits -= 1;
        }
    }

    fn descend(&mut self, w: usize) -> Descent {
        let cfg = &self.cfg;
        let state = &mut self.worlds[w];
        let ctx = &self.ctxs[w];
        let mut pc = PathCtx::new(Some(ctx));
        let mut path: Vec<(u32, u16, u16)> = Vec::with_capacity(16);
        let mut applied: Vec<Vec<Instruction>> = Vec::with_capacity(16);
        let mut root_step: Option<(u16, u16, usize)> = None;
        let mut node: u32 = 0;
        let mut leaf: Option<(u32, State, Context)> = None;
        let outcome = loop {
            let over = state.battle_is_over();
            if over != 0.0 && node != 0 {
                let score = if over > 0.0 { 1.0 } else { 0.0 };
                break (Descent::Terminal, Some(score));
            }
            if self.tree.nodes[node as usize].pending {
                break (Descent::Collision, None);
            }
            let (o1, o2) = if node == 0 {
                state.root_get_all_options()
            } else {
                state.get_all_options()
            };
            let n: &mut Node = &mut self.tree.nodes[node as usize];
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
                let score = crate::ismcts::sigmoid(evaluate(state) - self.root_evals[w]);
                break (Descent::Terminal, Some(score));
            }
            // virtual loss: the visit is counted now, its value when the evaluation is back
            n.visits += 1;
            n.s1[i1].visits += 1;
            n.s2[i2].visits += 1;
            let (i1, i2) = (i1 as u16, i2 as u16);
            pc.push(state, &m1, &m2);
            let branch = depth < cfg.branch_depth;
            if node == 0 && cfg.cache_root {
                let outcomes = self
                    .tree
                    .cache
                    .entry((node, i1, i2, w as u16))
                    .or_insert_with(|| {
                        generate_instructions_from_move_pair(state, &m1, &m2, branch)
                    });
                let k = sample(outcomes, &mut self.rng);
                state.apply_instructions(&outcomes[k].instruction_list);
                root_step = Some((i1, i2, k));
            } else {
                let mut outcomes = generate_instructions_from_move_pair(state, &m1, &m2, branch);
                let k = sample(&outcomes, &mut self.rng);
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
            match self.tree.children.get(&(node, i1, i2, sig)) {
                Some(&child) => node = child,
                None => {
                    let child = self.tree.nodes.len() as u32;
                    self.tree.nodes.push(Node {
                        depth: depth + 1,
                        ..Node::default()
                    });
                    self.tree.children.insert((node, i1, i2, sig), child);
                    node = child;
                    let over = state.battle_is_over();
                    if over != 0.0 {
                        break (Descent::Terminal, Some(if over > 0.0 { 1.0 } else { 0.0 }));
                    }
                    self.tree.nodes[child as usize].pending = true;
                    leaf = Some((child, state.clone(), pc.context(ctx)));
                    break (Descent::Leaf, None);
                }
            }
        };
        // restore the world
        for ins in applied.iter().rev() {
            state.reverse_instructions(ins);
        }
        if let Some((i1, i2, k)) = root_step {
            let outcomes = &self.tree.cache[&(0, i1, i2, w as u16)];
            state.reverse_instructions(&outcomes[k].instruction_list);
        }
        match outcome {
            (Descent::Terminal, Some(score)) => {
                self.backup(&path, node, score);
                Descent::Terminal
            }
            (Descent::Collision, _) => {
                self.undo(&path);
                Descent::Collision
            }
            _ => {
                let (node, state, ctx) = leaf.expect("leaf");
                self.pending.push(Pending {
                    path,
                    node,
                    state,
                    ctx,
                });
                Descent::Leaf
            }
        }
    }

    /// The pending leaves evaluated by the CPU network: (value logits, policy logits) in
    /// `collect`'s row order.
    pub fn evaluate_cpu(&self, net: &crate::tnet::TNet) -> (Vec<f32>, Vec<f32>) {
        let outs = crate::par_map(&self.pending, |p| {
            let ev = evaluate(&p.state);
            let own = Input::new(&p.state, &p.ctx, false, ev);
            let opp = own.flipped(&p.state, &p.ctx);
            (net.forward(&own), net.forward(&opp))
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
    pub fn root(&self) -> Vec<(Label, u32, f32)> {
        self.tree.nodes[0]
            .s1
            .iter()
            .map(|a| (a.label, a.visits, a.mean()))
            .collect()
    }
}
