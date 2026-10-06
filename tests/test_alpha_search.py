"""Rust search crate (rust/alpha_search, design D12): interop with the poke-engine package."""

from pathlib import Path

import alpha_search
import poke_engine as pe

STATES = (Path(__file__).parent / "fixtures" / "engine_state_6v6.txt").read_text().splitlines()


def test_state_string_roundtrip():
    # the crate parses exactly what the Python package writes (same version, same features)
    for s in STATES:
        assert alpha_search.roundtrip(s) == s
        assert pe.State.from_string(alpha_search.roundtrip(s)).to_string() == s


def test_reference_mcts_matches_python_package():
    s = STATES[0]
    ours, n = alpha_search.reference_mcts(s, 0, 20_000)
    assert n >= 20_000
    theirs = pe.monte_carlo_tree_search(pe.State.from_string(s), 0, 20_000, 1)
    assert {c for c, _ in ours} == {x.move_choice for x in theirs.side_one}
    best = max(ours, key=lambda x: x[1])[0]
    top3 = sorted(theirs.side_one, key=lambda x: -x.visits)[:3]
    assert best in {x.move_choice for x in top3}
