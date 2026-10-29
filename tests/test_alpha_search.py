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
