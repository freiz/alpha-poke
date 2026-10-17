//! alpha-poke search on top of poke-engine (MIT), used as a library: state, option generation,
//! instruction generation, evaluation, apply / reverse. Python passes poke-engine state strings
//! (`poke_engine.State.to_string()`); see design D12.

pub mod bsearch;
pub mod counts;
pub mod extra;
pub mod features;
pub mod ismcts;
pub mod tnet;

use poke_engine::engine::generate_instructions::generate_instructions_from_move_pair;
use poke_engine::engine::state::MoveChoice;
use poke_engine::state::{Side, State};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use std::time::Duration;

/// Same strings as the poke-engine Python binding: "earthquake", "earthquake-tera",
/// "switch greattusk".
pub fn choice_str(side: &Side, mc: &MoveChoice) -> String {
    match mc {
        MoveChoice::Switch(_) => format!("switch {}", mc.to_string(side)),
        _ => mc.to_string(side),
    }
}

/// Parse a state string and serialize it again (interop check with the Python package).
#[pyfunction]
fn roundtrip(state: &str) -> String {
    State::deserialize(state).serialize()
}

/// SO-ISMCTS over belief-sampled worlds (state strings sharing our side). Returns
/// ([(our option, visits, mean value)], iterations, tree nodes, max depth). threads > 1: root
/// parallel (independent trees, merged root statistics). A model directory (the transformer)
/// needs `contexts`: per world (public-information bits [12], (own rating,
/// opponent rating), turn, history string), side one's view.
#[pyfunction(name = "ismcts")]
#[pyo3(signature = (states, duration_ms, iterations=0, seed=None, c=std::f32::consts::SQRT_2,
                    cache_root=true, branch_depth=2, threads=1, model_dir=None,
                    use_policy=false, policy_opponent=true, c_puct=1.0, contexts=None,
                    root_noise=(0.0, 10.0), ml=(0.0, 0.0, 0.0, false)))]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn py_ismcts(
    py: Python<'_>,
    states: Vec<String>,
    duration_ms: u64,
    mut iterations: u32,
    seed: Option<u64>,
    c: f32,
    cache_root: bool,
    branch_depth: u16,
    threads: usize,
    model_dir: Option<String>,
    use_policy: bool,
    policy_opponent: bool,
    c_puct: f32,
    contexts: Option<Vec<PyContext>>,
    root_noise: (f32, f32),
    ml: (f32, f32, f32, bool),
) -> PyResult<(Vec<(String, u32, f32)>, u32, usize, u16)> {
    if states.is_empty() {
        return Err(PyValueError::new_err("ismcts needs at least one world"));
    }
    let mut worlds: Vec<State> = states.iter().map(|s| State::deserialize(s)).collect();
    if worlds[0].root_get_all_options().0.len() <= 1 {
        iterations = 100; // one option: quick exit
    }
    let tnet = match &model_dir {
        Some(d) => Some(tnet::shared(d).map_err(PyValueError::new_err)?),
        None => None,
    };
    let ctxs: Vec<tnet::Context> = match (&tnet, contexts) {
        (Some(_), Some(cs)) if cs.len() == worlds.len() => cs
            .into_iter()
            .map(to_context)
            .collect::<PyResult<Vec<_>>>()?,
        (Some(_), _) => {
            return Err(PyValueError::new_err(
                "a transformer model needs one context per world",
            ))
        }
        _ => Vec::new(),
    };
    let cfg = ismcts::Config {
        c,
        cache_root,
        branch_depth,
        use_policy,
        policy_opponent,
        c_puct,
        tnet,
        root_noise_eps: root_noise.0,
        root_noise_conc: root_noise.1,
        ml: ml_params(ml),
    };
    let res = py.detach(|| {
        if threads > 1 {
            ismcts::search_parallel(
                &worlds,
                &ctxs,
                Duration::from_millis(duration_ms),
                iterations,
                &cfg,
                seed,
                threads,
            )
        } else {
            ismcts::search(
                &mut worlds,
                &ctxs,
                Duration::from_millis(duration_ms),
                iterations,
                &cfg,
                seed,
            )
        }
    });
    let w0 = &worlds[0];
    let mut ours = Vec::with_capacity(res.s1.len());
    for (l, visits, mean) in res.s1 {
        let name = match ismcts::our_choice(w0, l) {
            Some(mc) => choice_str(&w0.side_one, &mc),
            None => format!("{l:?}"),
        };
        ours.push((name, visits, mean));
    }
    Ok((ours, res.iterations, res.nodes, res.max_depth))
}

/// `f` on every item, the items split into contiguous chunks over the available cores; results in
/// input order (batch featurization of training data).
pub(crate) fn par_map<T: Sync, R: Send>(items: &[T], f: impl Fn(&T) -> R + Sync) -> Vec<R> {
    let n = std::thread::available_parallelism().map_or(1, |n| n.get());
    if n <= 1 || items.len() < 256 {
        return items.iter().map(f).collect();
    }
    let chunk = items.len().div_ceil(n);
    let f = &f;
    std::thread::scope(|sc| {
        let handles: Vec<_> = items
            .chunks(chunk)
            .map(|c| sc.spawn(move || c.iter().map(f).collect::<Vec<R>>()))
            .collect();
        handles
            .into_iter()
            .flat_map(|h| h.join().expect("featurize thread"))
            .collect()
    })
}

fn le_bytes<T: Copy, const N: usize>(v: &[T], f: impl Fn(T) -> [u8; N]) -> Vec<u8> {
    v.iter().flat_map(|&x| f(x)).collect()
}

/// Features of many state strings (side one's view, design D13) as raw little-endian buffers:
/// (sparse int32 [B, 12, 10], dense float32 [B, 12, 23], global float32 [B, G], mask uint8
/// [B, 14]); shapes in `feature_dims()`. `flip`: side two's view (its team first, its options
/// in the mask), as the search computes the opponent's prior.
#[pyfunction]
#[pyo3(signature = (states, flip=false))]
#[allow(clippy::type_complexity)]
fn featurize<'py>(
    py: Python<'py>,
    states: Vec<String>,
    flip: bool,
) -> (
    Bound<'py, PyBytes>,
    Bound<'py, PyBytes>,
    Bound<'py, PyBytes>,
    Bound<'py, PyBytes>,
) {
    let (sparse, dense, global, mask) = py.detach(|| {
        let (mut sparse, mut dense, mut global, mut mask) = (vec![], vec![], vec![], vec![]);
        for f in par_map(&states, |s| {
            features::featurize_view(&State::deserialize(s), flip)
        }) {
            sparse.extend(f.sparse);
            dense.extend(f.dense);
            global.extend(f.global);
            mask.extend(f.mask);
        }
        (
            le_bytes(&sparse, i32::to_le_bytes),
            le_bytes(&dense, f32::to_le_bytes),
            le_bytes(&global, f32::to_le_bytes),
            mask,
        )
    });
    (
        PyBytes::new(py, &sparse),
        PyBytes::new(py, &dense),
        PyBytes::new(py, &global),
        PyBytes::new(py, &mask),
    )
}

/// History features (design D13 v2) of many history strings ("ONE/TWO;..." oldest first, side
/// one = the player to act; see features::parse_history): (sparse int32 [B, HIST, HIST_SPARSE],
/// dense float32 [B, HIST, HIST_DENSE]).
#[pyfunction]
fn featurize_history<'py>(
    py: Python<'py>,
    histories: Vec<String>,
) -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>) {
    let (sparse, dense) = py.detach(|| {
        let (mut sparse, mut dense) = (vec![], vec![]);
        for h in &histories {
            features::history_features(&features::parse_history(h), false, &mut sparse, &mut dense);
        }
        (
            le_bytes(&sparse, i32::to_le_bytes),
            le_bytes(&dense, f32::to_le_bytes),
        )
    });
    (PyBytes::new(py, &sparse), PyBytes::new(py, &dense))
}

/// v6 counters (`counts::featurize_counts`) of many state strings: (entity counters
/// [B * 12 * ENT_COUNT], side counters [B * GLOBAL_COUNT]) as little-endian f32 bytes.
#[pyfunction]
#[pyo3(signature = (states, flip=false))]
fn featurize_counts<'py>(
    py: Python<'py>,
    states: Vec<String>,
    flip: bool,
) -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>) {
    let (ent, glob) = py.detach(|| {
        let (mut ent, mut glob) = (vec![], vec![]);
        for (e, g) in par_map(&states, |s| {
            counts::featurize_counts(&State::deserialize(s), flip)
        }) {
            ent.extend(e);
            glob.extend(g);
        }
        (
            le_bytes(&ent, f32::to_le_bytes),
            le_bytes(&glob, f32::to_le_bytes),
        )
    });
    (PyBytes::new(py, &ent), PyBytes::new(py, &glob))
}

/// v3 features of many state strings (design D13, `extra.rs`): (entity extras float32
/// [B, 12, ENT_EXTRA], global extras float32 [B, GLOBAL_EXTRA]); `flip` as in `featurize`.
/// `reference`: the slower path without the light state copy (parity checks).
#[pyfunction]
#[pyo3(signature = (states, flip=false, reference=false))]
fn featurize_extra<'py>(
    py: Python<'py>,
    states: Vec<String>,
    flip: bool,
    reference: bool,
) -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>) {
    let (ent, glob) = py.detach(|| {
        let (mut ent, mut glob) = (vec![], vec![]);
        for (e, g) in par_map(&states, |s| {
            let st = State::deserialize(s);
            if reference {
                extra::featurize_extra_reference(&st, flip)
            } else {
                extra::featurize_extra(&st, flip)
            }
        }) {
            ent.extend(e);
            glob.extend(g);
        }
        (
            le_bytes(&ent, f32::to_le_bytes),
            le_bytes(&glob, f32::to_le_bytes),
        )
    });
    (PyBytes::new(py, &ent), PyBytes::new(py, &glob))
}

/// The static move table (float32 [VOCAB move, MOVE_FEAT], row = move id; `extra::move_table`).
#[pyfunction]
fn move_table(py: Python<'_>) -> Bound<'_, PyBytes> {
    let t = extra::move_table(features::VOCAB[4]);
    PyBytes::new(py, &le_bytes(&t, f32::to_le_bytes))
}

/// poke-engine's data tables for the data tests against Showdown (tests/test_engine_data.py,
/// doc/engine-diff.md L8): (the moves: per move [id, type, accuracy, category, base power,
/// priority, target, boost, drain, recoil, heal, status, volatile status, side condition,
/// secondaries, flags] as Rust Debug text; the type chart: (attacking type, defending type,
/// multiplier) for single-typed defenders, from the engine's own type_effectiveness_modifier).
#[pyfunction]
fn engine_data() -> (Vec<Vec<String>>, Vec<(String, String, f32)>) {
    use poke_engine::choices::MOVES;
    use poke_engine::engine::damage_calc::type_effectiveness_modifier;
    use poke_engine::state::{Pokemon, PokemonType};
    let mut ids: Vec<_> = MOVES.keys().collect();
    ids.sort_by_key(|c| format!("{:?}", c));
    let moves = ids
        .into_iter()
        .map(|id| {
            let c = MOVES.get(id).unwrap();
            let f = &c.flags;
            let flags = [
                ("bite", f.bite),
                ("bullet", f.bullet),
                ("charge", f.charge),
                ("contact", f.contact),
                ("drag", f.drag),
                ("heal", f.heal),
                ("powder", f.powder),
                ("protect", f.protect),
                ("pulse", f.pulse),
                ("punch", f.punch),
                ("recharge", f.recharge),
                ("reflectable", f.reflectable),
                ("slicing", f.slicing),
                ("sound", f.sound),
                ("pivot", f.pivot),
                ("wind", f.wind),
            ];
            vec![
                format!("{:?}", id),
                format!("{:?}", c.move_type),
                c.accuracy.to_string(),
                format!("{:?}", c.category),
                c.base_power.to_string(),
                c.priority.to_string(),
                format!("{:?}", c.target),
                format!("{:?}", c.boost),
                format!("{:?}", c.drain),
                format!("{:?}", c.recoil),
                format!("{:?}", c.heal),
                format!("{:?}", c.status),
                format!("{:?}", c.volatile_status),
                format!("{:?}", c.side_condition),
                format!("{:?}", c.secondaries),
                flags
                    .iter()
                    .filter(|x| x.1)
                    .map(|x| x.0)
                    .collect::<Vec<_>>()
                    .join(","),
            ]
        })
        .collect();
    let types = [
        PokemonType::NORMAL,
        PokemonType::FIRE,
        PokemonType::WATER,
        PokemonType::ELECTRIC,
        PokemonType::GRASS,
        PokemonType::ICE,
        PokemonType::FIGHTING,
        PokemonType::POISON,
        PokemonType::GROUND,
        PokemonType::FLYING,
        PokemonType::PSYCHIC,
        PokemonType::BUG,
        PokemonType::ROCK,
        PokemonType::GHOST,
        PokemonType::DRAGON,
        PokemonType::DARK,
        PokemonType::STEEL,
        PokemonType::FAIRY,
    ];
    let mut chart = Vec::new();
    for a in types {
        for d in types {
            let mut p = Pokemon::default();
            p.types = (d, PokemonType::TYPELESS);
            p.terastallized = false;
            let m = type_effectiveness_modifier(&a, &p);
            chart.push((format!("{:?}", a), format!("{:?}", d), m));
        }
    }
    (moves, chart)
}

/// poke-engine's moves aimed at the target that cannot miss (`Choices::always_hits`), lowercase.
#[pyfunction]
fn always_hit_moves() -> Vec<String> {
    use poke_engine::choices::MOVES;
    let mut out: Vec<String> = MOVES
        .keys()
        .filter(|c| c.always_hits())
        .map(|c| format!("{:?}", c).to_lowercase())
        .collect();
    out.sort();
    out
}

/// poke-engine's max PP of the moves where it is below 10 (`Choices::max_pp_below_10`).
#[pyfunction]
fn low_max_pp_moves() -> Vec<(String, i8)> {
    use poke_engine::choices::MOVES;
    let mut out: Vec<(String, i8)> = MOVES
        .keys()
        .filter_map(|c| {
            c.max_pp_below_10()
                .map(|pp| (format!("{:?}", c).to_lowercase(), pp))
        })
        .collect();
    out.sort();
    out
}

/// poke-engine's base stats of species (the forme-change table, `PokemonName::base_stats`):
/// None for a species the engine has none of.
#[pyfunction]
fn engine_base_stats(names: Vec<String>) -> Vec<Option<(i16, i16, i16, i16, i16, i16)>> {
    use poke_engine::pokemon::PokemonName;
    use std::str::FromStr;
    let hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {})); // the engine panics on a species it has none of
    let out = names
        .iter()
        .map(|n| {
            PokemonName::from_str(n)
                .ok()
                .and_then(|p| std::panic::catch_unwind(|| p.base_stats()).ok())
        })
        .collect();
    std::panic::set_hook(hook);
    out
}

/// Engine ids of names (case-insensitive engine spelling, e.g. "CHOICESCARF"): `kind` is
/// "species", "item", "ability", "type" or "move"; unknown names give 0.
#[pyfunction]
fn encode_ids(kind: &str, names: Vec<String>) -> PyResult<Vec<i32>> {
    use poke_engine::choices::Choices;
    use poke_engine::engine::abilities::Abilities;
    use poke_engine::engine::items::Items;
    use poke_engine::pokemon::PokemonName;
    use poke_engine::state::PokemonType;
    use std::str::FromStr;
    let f: fn(&str) -> i32 = match kind {
        "species" => |x| PokemonName::from_str(x).map_or(0, |v| v as i32),
        "item" => |x| Items::from_str(x).map_or(0, features::item_id),
        "ability" => |x| Abilities::from_str(x).map_or(0, |v| v as i32),
        "type" => |x| PokemonType::from_str(x).map_or(0, |v| v as i32),
        "move" => |x| Choices::from_str(x).map_or(0, |v| v as i32),
        _ => return Err(PyValueError::new_err(format!("unknown kind {kind}"))),
    };
    Ok(names
        .iter()
        .map(|n| if n.is_empty() { 0 } else { f(n) })
        .collect())
}

/// poke-engine's handcrafted evaluation of many state strings (side one's view; the leaf value
/// the search uses is sigmoid(0.0125 * (eval - root eval))). Offline baseline for the value net.
#[pyfunction]
fn evaluate(py: Python<'_>, states: Vec<String>) -> Vec<f32> {
    py.detach(|| {
        par_map(&states, |s| {
            poke_engine::engine::evaluate::evaluate(&State::deserialize(s))
        })
    })
}

/// The transformer network (model directory: best.safetensors + config.json) on many
/// positions: `states`, per position the public-information bits (12 ints, side one's view),
/// ratings (own, opponent), turn and history string ("ONE/TWO;..."); `flip` = side two's view.
/// Returns (policy logits [B * 14], -inf on illegal slots; value logits [B]). For checking the
/// Rust forward pass against PyTorch.
#[pyfunction]
#[pyo3(signature = (model_dir, states, reveals, ratings, turns, histories, flip=false))]
#[allow(clippy::too_many_arguments)]
fn tnet_forward(
    py: Python<'_>,
    model_dir: &str,
    states: Vec<String>,
    reveals: Vec<Vec<u8>>,
    ratings: Vec<(i32, i32)>,
    turns: Vec<i32>,
    histories: Vec<String>,
    flip: bool,
) -> PyResult<(Vec<f32>, Vec<f32>)> {
    let net = tnet::shared(model_dir).map_err(PyValueError::new_err)?;
    let n = states.len();
    if [reveals.len(), ratings.len(), turns.len(), histories.len()] != [n; 4] {
        return Err(PyValueError::new_err("one context per state"));
    }
    Ok(py.detach(|| {
        let outs = par_map(&(0..n).collect::<Vec<_>>(), |&i| {
            let st = State::deserialize(&states[i]);
            let mut reveal = [0u8; features::N_ENTITIES];
            reveal.copy_from_slice(&reveals[i][..features::N_ENTITIES]);
            let ctx = tnet::Context {
                reveal,
                rating: [ratings[i].0, ratings[i].1],
                turn: turns[i],
                history: features::parse_history(&histories[i]),
            };
            let ev = poke_engine::engine::evaluate::evaluate(&st);
            net.forward(&tnet::Input::new(&st, &ctx, flip, ev))
        });
        let (mut logits, mut values) = (Vec::with_capacity(n * 14), Vec::with_capacity(n));
        for o in outs {
            logits.extend_from_slice(&o.logits);
            values.push(o.value);
        }
        (logits, values)
    }))
}

/// The moves-left term's (slope, cap, threshold, winner only) (`ismcts::MlParams`; slope 0 =
/// off).
fn ml_params((slope, cap, threshold, winner_only): (f32, f32, f32, bool)) -> ismcts::MlParams {
    ismcts::MlParams {
        slope,
        cap,
        threshold,
        winner_only,
    }
}

/// A search context from Python: (public-information bits [12], (own rating, opponent rating),
/// turn, history string), side one's view.
type PyContext = (Vec<u8>, (i32, i32), i32, String);

fn to_context((rv, (r1, r2), turn, h): PyContext) -> PyResult<tnet::Context> {
    if rv.len() != features::N_ENTITIES {
        return Err(PyValueError::new_err(
            "12 public-information bytes per context",
        ));
    }
    let mut reveal = [0u8; features::N_ENTITIES];
    reveal.copy_from_slice(&rv);
    Ok(tnet::Context {
        reveal,
        rating: [r1, r2],
        turn,
        history: features::parse_history(&h),
    })
}

/// Batched ISMCTS (design D13, `bsearch`): the network runs outside (PyTorch on the GPU).
/// `collect(n)` -> dict of input arrays (bytes; 2 rows per pending leaf: side one's view, side
/// two's) + "rows"; `apply(values, logits)` with the value logits [rows] and policy logits
/// [rows * 14]; `root()` -> [(our option, visits, mean value)]; `stats()` -> (iterations,
/// collisions, nodes).
#[pyclass(name = "BatchSearch")]
struct PyBatchSearch {
    inner: bsearch::BatchSearch,
}

/// A collected batch as the dict GpuNet takes (raw little-endian buffers).
fn batch_dict(py: Python<'_>, b: bsearch::Batch) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("rows", b.rows)?;
    d.set_item(
        "sparse",
        PyBytes::new(py, &le_bytes(&b.sparse, i32::to_le_bytes)),
    )?;
    d.set_item(
        "dense",
        PyBytes::new(py, &le_bytes(&b.dense, f32::to_le_bytes)),
    )?;
    d.set_item(
        "global",
        PyBytes::new(py, &le_bytes(&b.global, f32::to_le_bytes)),
    )?;
    d.set_item("mask", PyBytes::new(py, &b.mask))?;
    d.set_item(
        "hsparse",
        PyBytes::new(py, &le_bytes(&b.hsparse, i32::to_le_bytes)),
    )?;
    d.set_item(
        "hdense",
        PyBytes::new(py, &le_bytes(&b.hdense, f32::to_le_bytes)),
    )?;
    d.set_item(
        "ent2",
        PyBytes::new(py, &le_bytes(&b.ent2, f32::to_le_bytes)),
    )?;
    d.set_item(
        "glob2",
        PyBytes::new(py, &le_bytes(&b.glob2, f32::to_le_bytes)),
    )?;
    d.set_item(
        "ent3",
        PyBytes::new(py, &le_bytes(&b.ent3, f32::to_le_bytes)),
    )?;
    d.set_item(
        "glob3",
        PyBytes::new(py, &le_bytes(&b.glob3, f32::to_le_bytes)),
    )?;
    d.set_item("reveal", PyBytes::new(py, &b.reveal))?;
    d.set_item(
        "turn",
        PyBytes::new(py, &le_bytes(&b.turn, i32::to_le_bytes)),
    )?;
    d.set_item(
        "rating",
        PyBytes::new(py, &le_bytes(&b.rating, i32::to_le_bytes)),
    )?;
    d.set_item(
        "eval",
        PyBytes::new(py, &le_bytes(&b.eval, f32::to_le_bytes)),
    )?;
    Ok(d)
}

#[pymethods]
impl PyBatchSearch {
    #[new]
    #[pyo3(signature = (states, contexts, c_puct=1.0, policy_opponent=true, seed=None,
                        branch_depth=2, threads=1, vl=1, root_noise=(0.0, 10.0),
                        ml=(0.0, 0.0, 0.0, false)))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        states: Vec<String>,
        contexts: Vec<PyContext>,
        c_puct: f32,
        policy_opponent: bool,
        seed: Option<u64>,
        branch_depth: u16,
        threads: usize,
        vl: u32,
        root_noise: (f32, f32),
        ml: (f32, f32, f32, bool),
    ) -> PyResult<Self> {
        if states.is_empty() || states.len() != contexts.len() {
            return Err(PyValueError::new_err(
                "one context per world, at least one world",
            ));
        }
        let worlds: Vec<State> = states.iter().map(|s| State::deserialize(s)).collect();
        let ctxs = contexts
            .into_iter()
            .map(to_context)
            .collect::<PyResult<Vec<_>>>()?;
        let cfg = ismcts::Config {
            cache_root: false,
            branch_depth,
            use_policy: true,
            policy_opponent,
            c_puct,
            root_noise_eps: root_noise.0,
            root_noise_conc: root_noise.1,
            ml: ml_params(ml),
            ..ismcts::Config::default()
        };
        Ok(PyBatchSearch {
            inner: bsearch::BatchSearch::new(worlds, ctxs, cfg, seed, threads, vl),
        })
    }

    fn collect<'py>(&mut self, py: Python<'py>, n: usize) -> PyResult<Bound<'py, PyDict>> {
        let inner = &mut self.inner;
        let b = py.detach(|| inner.collect(n));
        batch_dict(py, b)
    }

    /// `turns`: the predicted remaining turns per row (a network with the remaining-turns head;
    /// the moves-left term)
    #[pyo3(signature = (values, logits, turns=None))]
    fn apply(
        &mut self,
        values: Vec<f32>,
        logits: Vec<f32>,
        turns: Option<Vec<f32>>,
    ) -> PyResult<()> {
        if values.len() != 2 * self.inner.n_pending()
            || logits.len() != values.len() * features::N_ACTIONS
            || turns.as_ref().is_some_and(|t| t.len() != values.len())
        {
            return Err(PyValueError::new_err(
                "outputs do not match the collected batch",
            ));
        }
        self.inner.apply(&values, &logits, turns.as_deref());
        Ok(())
    }

    /// The pending batch evaluated by the Rust CPU network (`model_dir`): (values, logits,
    /// remaining turns or None) as `apply` takes them. For checking the GPU outputs, and a CPU
    /// fallback.
    #[allow(clippy::type_complexity)]
    fn evaluate_cpu(
        &mut self,
        py: Python<'_>,
        model_dir: &str,
    ) -> PyResult<(Vec<f32>, Vec<f32>, Option<Vec<f32>>)> {
        let net = tnet::shared(model_dir).map_err(PyValueError::new_err)?;
        let inner = &mut self.inner;
        Ok(py.detach(|| inner.evaluate_cpu(&net)))
    }

    fn root(&mut self) -> Vec<(String, u32, f32)> {
        let w0 = self.inner.world0().clone();
        let w0 = &w0;
        self.inner
            .root()
            .into_iter()
            .map(|(l, v, m)| {
                let name = match ismcts::our_choice(w0, l) {
                    Some(mc) => choice_str(&w0.side_one, &mc),
                    None => format!("{l:?}"),
                };
                (name, v, m)
            })
            .collect()
    }

    /// The root's search result in the network's action slots (design D15-3): dict of
    /// "visits", "mean", "prior" (< 0 = none), "legal", "names" (our option per slot, as in
    /// `root()`), "opp_visits" (lists of 14), "q" (our visit-weighted root value),
    /// "opp_unmapped" (opponent visits on moves world 0 lacks).
    fn record<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let r = self.inner.record();
        // our option of each slot, as `root()` names it ("" = no option)
        let w0 = self.inner.world0().clone();
        let mut names = vec![String::new(); features::N_ACTIONS];
        for (l, _, _) in self.inner.root() {
            if let Some(mc) = ismcts::our_choice(&w0, l) {
                if let Some(i) = features::slot(&mc) {
                    names[i] = choice_str(&w0.side_one, &mc);
                }
            }
        }
        let d = PyDict::new(py);
        d.set_item("names", names)?;
        d.set_item("visits", r.visits.to_vec())?;
        d.set_item("mean", r.mean.to_vec())?;
        d.set_item("prior", r.prior.to_vec())?;
        d.set_item("legal", r.legal.to_vec())?;
        d.set_item("q", r.q)?;
        d.set_item("opp_visits", r.opp_visits.to_vec())?;
        d.set_item("opp_unmapped", r.opp_unmapped)?;
        Ok(d)
    }

    fn stats(&mut self) -> (u32, u32, usize) {
        self.inner.stats()
    }

    /// seconds spent in collect: (descents, input building)
    fn timing(&self) -> (f64, f64) {
        (self.inner.timing[0], self.inner.timing[1])
    }
}

/// The network's policy priors over our root options (as the search uses them, no noise):
/// [(our option, prior)]. `model_dir` / `contexts` as for `ismcts`.
#[pyfunction]
fn root_priors(
    py: Python<'_>,
    states: Vec<String>,
    model_dir: String,
    contexts: Vec<PyContext>,
) -> PyResult<Vec<(String, f32)>> {
    let mut worlds: Vec<State> = states.iter().map(|s| State::deserialize(s)).collect();
    if contexts.len() != worlds.len() {
        return Err(PyValueError::new_err("one context per world"));
    }
    let cfg = ismcts::Config {
        use_policy: true,
        tnet: Some(tnet::shared(&model_dir).map_err(PyValueError::new_err)?),
        ..ismcts::Config::default()
    };
    let ctxs = contexts
        .into_iter()
        .map(to_context)
        .collect::<PyResult<Vec<_>>>()?;
    let res = py.detach(|| ismcts::search(&mut worlds, &ctxs, Duration::ZERO, 1, &cfg, Some(0)));
    let w0 = &worlds[0];
    Ok(res
        .s1_priors
        .into_iter()
        .map(|(l, p)| {
            let name = match ismcts::our_choice(w0, l) {
                Some(mc) => choice_str(&w0.side_one, &mc),
                None => format!("{l:?}"),
            };
            (name, p)
        })
        .collect())
}

/// Cross-search batching (self-play, design D15-2): collect up to `n` new leaves from each
/// search in parallel (searches split over up to `threads` threads), as one batch; returns
/// (batch dict, network rows per search, failed per search). A search whose collect panics (an
/// engine panic on a rare state) is marked failed and contributes nothing; the others go on (the
/// caller drops the failed ones). `apply_many` hands each search its rows of the outputs.
#[pyfunction]
#[pyo3(signature = (searches, n, threads=8))]
fn collect_many<'py>(
    py: Python<'py>,
    mut searches: Vec<PyRefMut<'py, PyBatchSearch>>,
    n: usize,
    threads: usize,
) -> PyResult<(Bound<'py, PyDict>, Vec<usize>, Vec<bool>)> {
    use std::panic::{catch_unwind, AssertUnwindSafe};
    let mut inners: Vec<&mut bsearch::BatchSearch> =
        searches.iter_mut().map(|s| &mut s.inner).collect();
    let batches: Vec<Option<bsearch::Batch>> = py.detach(|| {
        let per = inners.len().div_ceil(threads.max(1)).max(1);
        std::thread::scope(|sc| {
            let handles: Vec<_> = inners
                .chunks_mut(per)
                .map(|chunk| {
                    sc.spawn(move || {
                        chunk
                            .iter_mut()
                            .map(|s| catch_unwind(AssertUnwindSafe(|| s.collect(n))).ok())
                            .collect::<Vec<_>>()
                    })
                })
                .collect();
            handles
                .into_iter()
                .flat_map(|h| h.join().unwrap())
                .collect()
        })
    });
    let failed: Vec<bool> = batches.iter().map(|b| b.is_none()).collect();
    let rows: Vec<usize> = batches
        .iter()
        .map(|b| b.as_ref().map_or(0, |b| b.rows))
        .collect();
    let mut all = bsearch::Batch::default();
    for b in batches.into_iter().flatten() {
        all.extend(b);
    }
    Ok((batch_dict(py, all)?, rows, failed))
}

/// `values` [rows] and `logits` [rows * 14] as raw little-endian float32 bytes (numpy
/// `tobytes()`: no Python lists for the large outputs). Returns failed per search (a panic
/// while backing up: the caller drops it).
#[pyfunction]
#[pyo3(signature = (searches, values, logits, rows, threads=8, turns=None))]
fn apply_many(
    py: Python<'_>,
    mut searches: Vec<PyRefMut<'_, PyBatchSearch>>,
    values: &[u8],
    logits: &[u8],
    rows: Vec<usize>,
    threads: usize,
    turns: Option<&[u8]>,
) -> PyResult<Vec<bool>> {
    use std::panic::{catch_unwind, AssertUnwindSafe};
    let f32s = |b: &[u8]| -> Vec<f32> {
        b.chunks_exact(4)
            .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect()
    };
    let (values, logits) = (f32s(values), f32s(logits));
    let turns = turns.map(f32s);
    let na = features::N_ACTIONS;
    if rows.len() != searches.len()
        || rows.iter().sum::<usize>() != values.len()
        || logits.len() != values.len() * na
        || turns.as_ref().is_some_and(|t| t.len() != values.len())
    {
        return Err(PyValueError::new_err("outputs do not match the batches"));
    }
    let mut jobs = Vec::new();
    let mut r = 0;
    for (i, (s, &k)) in searches.iter_mut().zip(&rows).enumerate() {
        if k > 0 {
            if k != 2 * s.inner.n_pending() {
                return Err(PyValueError::new_err(
                    "rows do not match a search's oldest batch",
                ));
            }
            jobs.push((&mut s.inner, r, k, i));
        }
        r += k;
    }
    let (values, logits, turns) = (&values, &logits, &turns);
    let bad: Vec<usize> = py.detach(|| {
        let per = jobs.len().div_ceil(threads.max(1)).max(1);
        std::thread::scope(|sc| {
            let handles: Vec<_> = jobs
                .chunks_mut(per)
                .map(|chunk| {
                    sc.spawn(move || {
                        let mut bad = Vec::new();
                        for (s, r, k, i) in chunk.iter_mut() {
                            let (v, l) = (&values[*r..*r + *k], &logits[*r * na..(*r + *k) * na]);
                            let t = turns.as_ref().map(|t| &t[*r..*r + *k]);
                            if catch_unwind(AssertUnwindSafe(|| s.apply(v, l, t))).is_err() {
                                bad.push(*i);
                            }
                        }
                        bad
                    })
                })
                .collect();
            handles
                .into_iter()
                .flat_map(|h| h.join().unwrap())
                .collect()
        })
    });
    let mut failed = vec![false; rows.len()];
    for i in bad {
        failed[i] = true;
    }
    Ok(failed)
}

/// Side one's option name of each of the 14 action slots of each state ("" = none), as the
/// search names options (`choice_str`): compares actions across differently built states.
#[pyfunction]
fn slot_names(states: Vec<String>) -> Vec<Vec<String>> {
    states
        .iter()
        .map(|s| {
            let st = State::deserialize(s);
            let mut names = vec![String::new(); features::N_ACTIONS];
            let (o1, _) = st.root_get_all_options();
            for mc in o1 {
                if let Some(i) = features::slot(&mc) {
                    names[i] = choice_str(&st.side_one, &mc);
                }
            }
            names
        })
        .collect()
}

/// Feature shapes and embedding table sizes.
#[pyfunction]
fn feature_dims(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("entities", features::N_ENTITIES)?;
    d.set_item("sparse", features::SPARSE)?;
    d.set_item("dense", features::DENSE)?;
    d.set_item("global", features::GLOBAL)?;
    d.set_item("actions", features::N_ACTIONS)?;
    d.set_item("vocab", features::VOCAB.to_vec())?;
    d.set_item("hist", features::HIST)?;
    d.set_item("hist_sparse", features::HIST_SPARSE)?;
    d.set_item("hist_dense", features::HIST_DENSE)?;
    d.set_item("ent_extra", extra::ENT_EXTRA)?;
    d.set_item("global_extra", extra::GLOBAL_EXTRA)?;
    d.set_item("move_feat", extra::MOVE_FEAT)?;
    d.set_item("ent_count", counts::ENT_COUNT)?;
    d.set_item("global_count", counts::GLOBAL_COUNT)?;
    d.set_item("count_version", counts::COUNT_VERSION)?;
    Ok(d)
}

/// poke-engine's exact 16 damage rolls, lowest first, of a side's move against the other side's
/// move (doc/engine-diff.md L34; the dual-engine tests check Showdown's damage is one of them):
/// (no crit, crit), None for a fixed-damage or no-damage move.
#[pyfunction]
fn damage_rolls(
    state: &str,
    side_one: bool,
    mv: &str,
    foe_move: &str,
) -> PyResult<Option<(Vec<i16>, Vec<i16>)>> {
    use poke_engine::choices::{Choices, MOVES};
    use poke_engine::engine::generate_instructions::calculate_damage_roll_sets;
    use poke_engine::state::SideReference;
    use std::str::FromStr;
    let get = |m: &str| {
        Choices::from_str(m)
            .ok()
            .and_then(|c| MOVES.get(&c))
            .cloned()
            .ok_or_else(|| PyValueError::new_err(format!("unknown move {m}")))
    };
    let (choice, foe) = (get(mv)?, get(foe_move)?);
    let side = if side_one {
        SideReference::SideOne
    } else {
        SideReference::SideTwo
    };
    Ok(
        calculate_damage_roll_sets(State::deserialize(state), &side, choice, &foe)
            .map(|(a, b)| (a.to_vec(), b.to_vec())),
    )
}

/// poke-engine's move targets ("opponent" / "user"), lowercase move ids (the data test compares
/// them with Showdown's: Good as Gold / Magic Bounce read them; doc/engine-diff.md L72).
#[pyfunction]
fn move_targets() -> Vec<(String, String)> {
    use poke_engine::choices::{MoveTarget, MOVES};
    let mut out: Vec<(String, String)> = MOVES
        .iter()
        .map(|(id, c)| {
            let t = match c.target {
                MoveTarget::User => "user",
                MoveTarget::Opponent => "opponent",
            };
            (format!("{:?}", id).to_lowercase(), t.to_string())
        })
        .collect();
    out.sort();
    out
}

/// poke-engine's Fling power with each item (`Items::fling_power`; None: Fling fails with it or
/// the engine does not know the item; doc/engine-diff.md L140).
#[pyfunction]
fn fling_powers(names: Vec<String>) -> Vec<Option<u8>> {
    use poke_engine::engine::items::Items;
    use std::str::FromStr;
    names
        .iter()
        .map(|x| Items::from_str(x).ok().and_then(|i| i.fling_power()))
        .collect()
}

/// The status moves aimed at the foe that go through a Substitute (`Choices::bypasses_substitute`,
/// lowercase; doc/engine-diff.md L133).
#[pyfunction]
fn bypass_substitute_moves() -> Vec<String> {
    use poke_engine::choices::MOVES;
    let mut out: Vec<String> = MOVES
        .keys()
        .filter(|c| c.bypasses_substitute())
        .map(|c| format!("{:?}", c).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The moves a foe's Pressure takes one more PP of (`Choices::pressure_applies` on their engine
/// target, lowercase; doc/engine-diff.md L177).
#[pyfunction]
fn pressure_moves() -> Vec<String> {
    use poke_engine::choices::MOVES;
    let mut out: Vec<String> = MOVES
        .iter()
        .filter(|(c, m)| c.pressure_applies(&m.target))
        .map(|(c, _)| format!("{:?}", c).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The weight (hg) of each forme the engine changes weight with (`PokemonName::forme_weight_hg`;
/// doc/engine-diff.md L183): [(species id, weight)].
#[pyfunction]
fn forme_weights() -> Vec<(String, i16)> {
    use poke_engine::pokemon::PokemonName;
    use std::str::FromStr;
    let names = [
        "minior", "miniorblue", "miniorgreen", "miniorindigo", "miniororange", "miniorviolet",
        "minioryellow", "miniormeteor", "wishiwashi", "wishiwashischool", "palafin",
        "palafinhero", "terapagos", "terapagosterastal", "terapagosstellar",
    ];
    names
        .iter()
        .filter_map(|n| {
            let p = PokemonName::from_str(n).ok()?;
            Some((n.to_string(), p.forme_weight_hg()?))
        })
        .collect()
}

/// The dance moves (`Choices::is_dance`, lowercase; doc/engine-diff.md L171).
#[pyfunction]
fn dance_moves() -> Vec<String> {
    use poke_engine::choices::MOVES;
    let mut out: Vec<String> = MOVES
        .keys()
        .filter(|c| c.is_dance())
        .map(|c| format!("{:?}", c).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The moves Copycat cannot copy (`Choices::fails_copycat`, lowercase; doc/engine-diff.md L167).
#[pyfunction]
fn fail_copycat_moves() -> Vec<String> {
    use poke_engine::choices::MOVES;
    let mut out: Vec<String> = MOVES
        .keys()
        .filter(|c| c.fails_copycat())
        .map(|c| format!("{:?}", c).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The moves poke-engine aims at the opponent that are not aimed at the foe's Pokemon
/// (`Choices::not_aimed_at_foe`, lowercase; doc/engine-diff.md L72).
#[pyfunction]
fn not_aimed_at_foe_moves() -> Vec<String> {
    use poke_engine::choices::MOVES;
    let mut out: Vec<String> = MOVES
        .keys()
        .filter(|c| c.not_aimed_at_foe())
        .map(|c| format!("{:?}", c).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The species poke-engine counts as Paradox (`PARADOX`, lowercase; doc/engine-diff.md L79).
#[pyfunction]
fn paradox_species() -> Vec<String> {
    let mut out: Vec<String> = poke_engine::engine::state::PARADOX
        .iter()
        .map(|p| format!("{:?}", p).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The abilities Skill Swap fails on (`FAIL_SKILL_SWAP`, lowercase; doc/engine-diff.md L106).
#[pyfunction]
fn fail_skill_swap_abilities() -> Vec<String> {
    let mut out: Vec<String> = poke_engine::engine::abilities::FAIL_SKILL_SWAP
        .iter()
        .map(|a| format!("{:?}", a).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The abilities no other ability replaces (`CANT_SUPPRESS`, lowercase; doc/engine-diff.md L184).
#[pyfunction]
fn cant_suppress_abilities() -> Vec<String> {
    let mut out: Vec<String> = poke_engine::engine::abilities::CANT_SUPPRESS
        .iter()
        .map(|a| format!("{:?}", a).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The abilities Trace does not copy (`NO_TRACE`, lowercase; doc/engine-diff.md L184).
#[pyfunction]
fn no_trace_abilities() -> Vec<String> {
    let mut out: Vec<String> = poke_engine::engine::abilities::NO_TRACE
        .iter()
        .map(|a| format!("{:?}", a).to_lowercase())
        .collect();
    out.sort();
    out
}

/// The full-information state of a self-play / evaluation position: side one from `a` (side
/// one's own view: its side exact), side two = side one of `b` (the other player's own view),
/// the field from `a`; the weather / terrain from `b` with `weather_from_b` / `terrain_from_b`
/// (the view of the side that set it: only the setter knows its extending item, e.g. Damp Rock;
/// the other view's turns are a belief sample -- doc/engine-diff.md, full information). For luck
/// estimates and the engine differential.
#[pyfunction]
#[pyo3(signature = (a, b, weather_from_b=false, terrain_from_b=false))]
fn merge_sides(a: &str, b: &str, weather_from_b: bool, terrain_from_b: bool) -> String {
    let mut st = State::deserialize(a);
    let sb = State::deserialize(b);
    if weather_from_b {
        st.weather = sb.weather.clone();
    }
    if terrain_from_b {
        st.terrain = sb.terrain.clone();
    }
    st.side_two = sb.side_one;
    st.serialize()
}

fn option_of(options: &[MoveChoice], slot: i32) -> Option<MoveChoice> {
    options.iter().copied().find(|mc| match features::slot(mc) {
        Some(i) => i as i32 == slot,
        None => slot < 0,
    })
}

/// The chance outcomes of the move pair (slots relative to each side; -1 = no choice) in
/// `state`: [(probability, resulting state, battle_is_over)] as the search's transition model
/// generates them (`branch`: also branch on damage rolls). With `damage`, each outcome also has
/// the damage each side took ([side one, side two], the sum of its Damage instructions: the
/// engine differential's roll tolerance, scripts/check_engine_diff.py).
#[pyfunction]
#[pyo3(signature = (state, slot1, slot2, branch=false, damage=false))]
fn chance_outcomes<'py>(
    py: Python<'py>,
    state: &str,
    slot1: i32,
    slot2: i32,
    branch: bool,
    damage: bool,
) -> PyResult<Vec<Bound<'py, pyo3::types::PyTuple>>> {
    let mut st = State::deserialize(state);
    let (o1, o2) = st.root_get_all_options();
    let (Some(m1), Some(m2)) = (option_of(&o1, slot1), option_of(&o2, slot2)) else {
        return Err(PyValueError::new_err("slot not among the options"));
    };
    let outcomes = generate_instructions_from_move_pair(&mut st, &m1, &m2, branch);
    let total: f32 = outcomes.iter().map(|o| o.percentage.max(0.0)).sum();
    let mut out = Vec::with_capacity(outcomes.len());
    for o in &outcomes {
        st.apply_instructions(&o.instruction_list);
        let (p, s, over) = (
            o.percentage.max(0.0) / total,
            st.serialize(),
            st.battle_is_over(),
        );
        st.reverse_instructions(&o.instruction_list);
        let t = if damage {
            let mut dmg = [0i32; 2];
            for ins in &o.instruction_list {
                if let poke_engine::instruction::Instruction::Damage(d) = ins {
                    let k = (d.side_ref != poke_engine::state::SideReference::SideOne) as usize;
                    dmg[k] += d.damage_amount as i32;
                }
            }
            pyo3::types::PyTuple::new(
                py,
                [
                    p.into_pyobject(py)?.into_any(),
                    s.into_pyobject(py)?.into_any(),
                    over.into_pyobject(py)?.into_any(),
                    dmg.to_vec().into_pyobject(py)?.into_any(),
                ],
            )?
        } else {
            pyo3::types::PyTuple::new(
                py,
                [
                    p.into_pyobject(py)?.into_any(),
                    s.into_pyobject(py)?.into_any(),
                    over.into_pyobject(py)?.into_any(),
                ],
            )?
        };
        out.push(t);
    }
    Ok(out)
}

/// Per side: (active index, [(species, hp, max hp, status)], boosts [atk, def, spa, spd, spe,
/// acc, eva]) — what a player sees of a state, to match outcomes with observations.
type SideInfo = (usize, Vec<(String, i16, i16, String)>, [i8; 7]);

#[pyfunction]
fn describe(states: Vec<String>) -> Vec<(SideInfo, SideInfo)> {
    let side = |s: &Side| -> SideInfo {
        let mons = s
            .pokemon
            .pkmn
            .iter()
            .map(|p| {
                (
                    format!("{:?}", p.id),
                    p.hp,
                    p.maxhp,
                    format!("{:?}", p.status),
                )
            })
            .collect();
        let b = [
            s.attack_boost,
            s.defense_boost,
            s.special_attack_boost,
            s.special_defense_boost,
            s.speed_boost,
            s.accuracy_boost,
            s.evasion_boost,
        ];
        (s.active_index as usize, mons, b)
    };
    states
        .iter()
        .map(|x| {
            let st = State::deserialize(x);
            (side(&st.side_one), side(&st.side_two))
        })
        .collect()
}

#[pymodule]
fn alpha_search(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(py_ismcts, m)?)?;
    m.add_function(wrap_pyfunction!(featurize, m)?)?;
    m.add_function(wrap_pyfunction!(featurize_history, m)?)?;
    m.add_function(wrap_pyfunction!(feature_dims, m)?)?;
    m.add_function(wrap_pyfunction!(featurize_extra, m)?)?;
    m.add_function(wrap_pyfunction!(featurize_counts, m)?)?;
    m.add_function(wrap_pyfunction!(move_table, m)?)?;
    m.add_function(wrap_pyfunction!(engine_data, m)?)?;
    m.add_function(wrap_pyfunction!(engine_base_stats, m)?)?;
    m.add_function(wrap_pyfunction!(always_hit_moves, m)?)?;
    m.add_function(wrap_pyfunction!(low_max_pp_moves, m)?)?;
    m.add_function(wrap_pyfunction!(encode_ids, m)?)?;
    m.add_function(wrap_pyfunction!(tnet_forward, m)?)?;
    m.add_class::<PyBatchSearch>()?;
    m.add_function(wrap_pyfunction!(collect_many, m)?)?;
    m.add_function(wrap_pyfunction!(apply_many, m)?)?;
    m.add_function(wrap_pyfunction!(slot_names, m)?)?;
    m.add_function(wrap_pyfunction!(root_priors, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(merge_sides, m)?)?;
    m.add_function(wrap_pyfunction!(damage_rolls, m)?)?;
    m.add_function(wrap_pyfunction!(move_targets, m)?)?;
    m.add_function(wrap_pyfunction!(not_aimed_at_foe_moves, m)?)?;
    m.add_function(wrap_pyfunction!(bypass_substitute_moves, m)?)?;
    m.add_function(wrap_pyfunction!(fail_copycat_moves, m)?)?;
    m.add_function(wrap_pyfunction!(dance_moves, m)?)?;
    m.add_function(wrap_pyfunction!(forme_weights, m)?)?;
    m.add_function(wrap_pyfunction!(pressure_moves, m)?)?;
    m.add_function(wrap_pyfunction!(fling_powers, m)?)?;
    m.add_function(wrap_pyfunction!(paradox_species, m)?)?;
    m.add_function(wrap_pyfunction!(fail_skill_swap_abilities, m)?)?;
    m.add_function(wrap_pyfunction!(cant_suppress_abilities, m)?)?;
    m.add_function(wrap_pyfunction!(no_trace_abilities, m)?)?;
    m.add_function(wrap_pyfunction!(chance_outcomes, m)?)?;
    m.add_function(wrap_pyfunction!(describe, m)?)?;
    Ok(())
}
