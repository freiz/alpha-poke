//! alpha-poke search on top of poke-engine (MIT), used as a library: state, option generation,
//! instruction generation, evaluation, apply / reverse. Python passes poke-engine state strings
//! (`poke_engine.State.to_string()`); see design D12.

pub mod ismcts;

use poke_engine::engine::state::MoveChoice;
use poke_engine::mcts::perform_mcts;
use poke_engine::state::{Side, State};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
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
/// ([(our option, visits, mean value)], iterations, tree nodes, max depth).
#[pyfunction(name = "ismcts")]
#[pyo3(signature = (states, duration_ms, iterations=0, seed=None, c=std::f32::consts::SQRT_2,
                    cache_root=true, branch_depth=2, chance_depth=0))]
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
    };
    let res = py.detach(|| {
        ismcts::search(
            &mut worlds,
            Duration::from_millis(duration_ms),
            iterations,
            &cfg,
            seed,
        )
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

#[pymodule]
fn alpha_search(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(reference_mcts, m)?)?;
    m.add_function(wrap_pyfunction!(py_ismcts, m)?)?;
    Ok(())
}
