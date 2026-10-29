"""The search tree's history against the log's (scripts/check_tree_history.py; doc/state-diff.md
plan B, part 2): on the random battles where the check found each kind of difference
(2026-10-24), the step the tree records for the actual joint action matches the log's step in
the structural fields -- locked / charging turns no action, recharges and ejects prevented, a
move with no target left or an Encore's changed move the one used, a mon stopped then knocked
out prevented, a confusion self-hit's no action, a dragged mon's none, a Terastallized
Ogerpon's actor its entry forme, a tera kept past a stopped move none."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEAMS = ROOT / "tests/fixtures/random_battle_teams.jsonl"

pytestmark = pytest.mark.skipif(not (ROOT / "vendor/pokemon-showdown/dist/sim").exists(),
                                reason="needs the built Showdown simulator")  # fmt: skip

# (seed: the kinds it had) -- the seeds of tests/fixtures/random_battle_teams.jsonl, offset 0
SEEDS = {
    0: "Outrage's locked turns, Phantom Force's second",
    2: "a confusion self-hit's faint",
    4: "Meteor Beam's second turn",
    6: "a recharge, a recharge's faint first, a no-target move after Healing Wish",
    7: "an Encore's changed move",
    13: "a no-target move",
    15: "a Terastallized Ogerpon, an eject",
    16: "fully paralysed, then fainted at the end of the turn",
    17: "frozen, then knocked out",
    18: "frozen, then knocked out",
    20: "an eject",
    21: "a tera kept past a stopped move",
    28: "dragged out before its move",
    31: "knocked out by the foe's pivot",
}


def _check():
    spec = importlib.util.spec_from_file_location(
        "check_tree_history", ROOT / "scripts/check_tree_history.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_tree_step_is_the_logs():
    check = _check()
    pairs = [json.loads(x) for x in TEAMS.read_text().splitlines()]
    bad = []
    for seed, kinds in SEEDS.items():
        p = pairs[seed % len(pairs)]
        r = check.battle(((TEAMS.stem, seed), p["p1"], p["p2"]))
        assert not r["errors"], (seed, r["errors"])
        assert r["steps"] > 0, seed
        if r["struct"]:
            bad.append((seed, kinds, dict(r["struct"]), r["examples"][:3]))
    assert not bad, bad
