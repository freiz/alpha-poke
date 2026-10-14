"""Capped self-play games in the conversion (2026-10-14, design "防拖延循环")."""

from alpha_poke.selfplay.convert import last_faint_turn


def test_last_faint_turn():
    log = "\n".join(["|turn|1", "|faint|p1a: A", "|turn|7", "|faint|p2a: B", "|turn|9"])
    assert last_faint_turn(log) == 7
    assert last_faint_turn("|turn|1\n|turn|2") == 0
