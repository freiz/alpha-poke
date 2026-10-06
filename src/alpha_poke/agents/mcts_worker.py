"""Process-pool worker for root-parallel MCTS (poke-engine's mcts holds the GIL, so threads do
not parallelize). Imports nothing but poke_engine so that workers start fast."""

import poke_engine as pe


def run(state_str: str, duration_ms: int) -> tuple[list[tuple[str, int]], int]:
    """One single-threaded MCTS on a serialized state: ([(move choice, visits)], iterations)."""
    res = pe.monte_carlo_tree_search(pe.State.from_string(state_str), duration_ms, 0, 1)
    return [(x.move_choice, x.visits) for x in res.side_one], res.total_visits
