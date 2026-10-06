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
}

fn arm_index(arms: &mut Vec<Arm>, l: Label) -> usize {
    match arms.iter().position(|a| a.label == l) {
        Some(i) => i,
        None => {
            arms.push(Arm {
                label: l,
                visits: 0,
                avail: 0,
                total: 0.0,
            });
            arms.len() - 1
        }
    }
}

#[derive(Debug, Clone)]
pub struct Config {
    pub c: f32,
    /// cache the root's instruction lists per (joint action, world)
    pub cache_root: bool,
    /// branch on damage rolls for nodes shallower than this (poke-engine: root and its children)
    pub branch_depth: u16,
    /// split children by the observable outcome for nodes shallower than this (0 = open-loop)
    pub chance_depth: u16,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            c: std::f32::consts::SQRT_2,
            cache_root: true,
            branch_depth: 2,
            chance_depth: 0,
        }
    }
}

pub struct Tree {
    pub nodes: Vec<Node>,
    children: FxHashMap<(u32, u16, u16, u64), u32>,
    cache: FxHashMap<(u32, u16, u16, u16), Vec<StateInstructions>>,
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

fn sigmoid(x: f32) -> f32 {
    1.0 / (1.0 + (-0.0125 * x).exp())
}

fn select(arms: &[Arm], avail: &[(usize, MoveChoice)], c: f32) -> (usize, MoveChoice) {
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

fn sample(outcomes: &[StateInstructions], rng: &mut impl Rng) -> usize {
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
        rng: &mut impl Rng,
    ) {
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
            let (i1, m1) = select(&n.s1, &av1, cfg.c);
            let (i2, m2) = select(&n.s2, &av2, cfg.c);
            let depth = n.depth;
            if m1 == MoveChoice::None && m2 == MoveChoice::None {
                break sigmoid(evaluate(state) - root_eval);
            }
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
                    } else {
                        sigmoid(evaluate(state) - root_eval)
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
    duration: Duration,
    max_iterations: u32,
    cfg: &Config,
    seed: Option<u64>,
) -> SearchResult {
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
            tree.iterate(&mut worlds[w], w as u16, root_evals[w], cfg, &mut rng);
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
        let res = search(&mut worlds, Duration::ZERO, 30_000, &cfg, Some(1));
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
            tree.iterate(&mut worlds[w], w as u16, evals[w], &cfg, &mut rng);
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
                tree.iterate(&mut worlds[0], 0, eval, &cfg, &mut rng);
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
    fn single_world_agrees_with_poke_engine_mcts() {
        let mut worlds = vec![fixture()];
        let res = search(
            &mut worlds,
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
