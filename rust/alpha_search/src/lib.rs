//! alpha-poke search on top of poke-engine (MIT), used as a library: state, option generation,
//! instruction generation, evaluation, apply / reverse. Python passes poke-engine state strings
//! (`poke_engine.State.to_string()`); see design D12.

pub mod extra;
pub mod features;
pub mod ismcts;
pub mod net;

use poke_engine::engine::state::MoveChoice;
use poke_engine::mcts::perform_mcts;
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

/// poke-engine's own single-threaded MCTS, called from this crate: reference for speed and
/// strength. Returns ([(our option, visits)], iterations).
#[pyfunction]
#[pyo3(signature = (state, duration_ms, iterations=0))]
fn reference_mcts(
    py: Python<'_>,
    state: &str,
    duration_ms: u64,
    mut iterations: u32,
) -> (Vec<(String, u32)>, u32) {
    let mut st = State::deserialize(state);
    let (s1, s2) = st.root_get_all_options();
    if s1.len() <= 1 {
        iterations = 100; // as the Python binding: one option, quick exit
    }
    let res = py.detach(|| {
        perform_mcts(
            &mut st,
            s1,
            s2,
            Duration::from_millis(duration_ms),
            iterations,
        )
    });
    let ours = res
        .s1
        .iter()
        .map(|r| (choice_str(&st.side_one, &r.move_choice), r.visits))
        .collect();
    (ours, res.iteration_count)
}

/// SO-ISMCTS over belief-sampled worlds (state strings sharing our side). Returns
/// ([(our option, visits, mean value)], iterations, tree nodes, max depth). threads > 1: root
/// parallel (independent trees, merged root statistics).
#[pyfunction(name = "ismcts")]
#[pyo3(signature = (states, duration_ms, iterations=0, seed=None, c=std::f32::consts::SQRT_2,
                    cache_root=true, branch_depth=2, chance_depth=0, threads=1,
                    model_dir=None, use_policy=false, policy_opponent=true, c_puct=1.0,
                    net_value=true))]
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
    chance_depth: u16,
    threads: usize,
    model_dir: Option<String>,
    use_policy: bool,
    policy_opponent: bool,
    c_puct: f32,
    net_value: bool,
) -> PyResult<(Vec<(String, u32, f32)>, u32, usize, u16)> {
    if states.is_empty() {
        return Err(PyValueError::new_err("ismcts needs at least one world"));
    }
    let mut worlds: Vec<State> = states.iter().map(|s| State::deserialize(s)).collect();
    if worlds[0].root_get_all_options().0.len() <= 1 {
        iterations = 100; // one option: quick exit
    }
    let cfg = ismcts::Config {
        c,
        cache_root,
        branch_depth,
        chance_depth,
        net: match &model_dir {
            Some(d) => Some(net::shared(d).map_err(PyValueError::new_err)?),
            None => None,
        },
        use_policy,
        policy_opponent,
        c_puct,
        net_value,
    };
    let res = py.detach(|| {
        if threads > 1 {
            ismcts::search_parallel(
                &worlds,
                Duration::from_millis(duration_ms),
                iterations,
                &cfg,
                seed,
                threads,
            )
        } else {
            ismcts::search(
                &mut worlds,
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
fn par_map<T: Sync, R: Send>(items: &[T], f: impl Fn(&T) -> R + Sync) -> Vec<R> {
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

/// v3 features of many state strings (design D13, `extra.rs`): (entity extras float32
/// [B, 12, ENT_EXTRA], global extras float32 [B, GLOBAL_EXTRA]); `flip` as in `featurize`.
#[pyfunction]
#[pyo3(signature = (states, flip=false))]
fn featurize_extra<'py>(
    py: Python<'py>,
    states: Vec<String>,
    flip: bool,
) -> (Bound<'py, PyBytes>, Bound<'py, PyBytes>) {
    let (ent, glob) = py.detach(|| {
        let (mut ent, mut glob) = (vec![], vec![]);
        for (e, g) in par_map(&states, |s| {
            extra::featurize_extra(&State::deserialize(s), flip)
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
        "item" => |x| Items::from_str(x).map_or(0, |v| v as i32),
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

/// The trained network (model directory with best.safetensors) on many state strings:
/// (policy logits [B * 14] with -inf on illegal slots, value logits [B]). For checking the Rust
/// forward pass against PyTorch and for offline use.
#[pyfunction]
fn net_forward(
    py: Python<'_>,
    model_dir: &str,
    states: Vec<String>,
) -> PyResult<(Vec<f32>, Vec<f32>)> {
    let net = net::shared(model_dir).map_err(PyValueError::new_err)?;
    Ok(py.detach(|| {
        let (mut logits, mut values) = (Vec::new(), Vec::new());
        for s in &states {
            let st = State::deserialize(s);
            let out = net.forward(
                &features::featurize(&st),
                poke_engine::engine::evaluate::evaluate(&st),
            );
            logits.extend_from_slice(&out.logits);
            values.push(out.value);
        }
        (logits, values)
    }))
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
    Ok(d)
}

#[pymodule]
fn alpha_search(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(reference_mcts, m)?)?;
    m.add_function(wrap_pyfunction!(py_ismcts, m)?)?;
    m.add_function(wrap_pyfunction!(featurize, m)?)?;
    m.add_function(wrap_pyfunction!(featurize_history, m)?)?;
    m.add_function(wrap_pyfunction!(feature_dims, m)?)?;
    m.add_function(wrap_pyfunction!(featurize_extra, m)?)?;
    m.add_function(wrap_pyfunction!(move_table, m)?)?;
    m.add_function(wrap_pyfunction!(encode_ids, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(net_forward, m)?)?;
    Ok(())
}
