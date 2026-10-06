//! alpha-poke search on top of poke-engine (MIT), used as a library: state, option generation,
//! instruction generation, evaluation, apply / reverse. Python passes poke-engine state strings
//! (`poke_engine.State.to_string()`); see design D12.

use poke_engine::engine::state::MoveChoice;
use poke_engine::mcts::perform_mcts;
use poke_engine::state::{Side, State};
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

#[pymodule]
fn alpha_search(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(reference_mcts, m)?)?;
    Ok(())
}
