"""Process-pool worker for root-parallel MCTS (poke-engine's mcts holds the GIL, so threads do
not parallelize). Imports nothing but poke_engine so that workers start fast."""

import poke_engine as pe


def search(state, duration_ms: int) -> tuple[list[tuple[str, int]], int]:
    """One single-threaded MCTS: ([(move choice, visits)], iterations). A poke-engine panic
    (pyo3 PanicException derives from BaseException, so ``except Exception`` misses it and the
    bot would never answer the turn) is re-raised as a RuntimeError."""
    try:
        if isinstance(state, str):
            state = pe.State.from_string(state)
        res = pe.monte_carlo_tree_search(state, duration_ms, 0, 1)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:  # noqa: BLE001
        raise RuntimeError(f"poke-engine: {type(e).__name__}: {e}") from None
    return [(x.move_choice, x.visits) for x in res.side_one], res.total_visits


def run(state_str: str, duration_ms: int) -> tuple[list[tuple[str, int]], int]:
    """Worker entry point: MCTS on a serialized state."""
    return search(state_str, duration_ms)
