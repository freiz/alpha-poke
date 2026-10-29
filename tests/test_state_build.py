"""The state-construction differential (enginecheck/statebuild.py; 2026-10-23, after ten review
rounds): our engine state from the player's view against the one from Showdown's own state, at
every decision of fixed random battles. The baseline (tests/fixtures/state_build_baseline.json)
lists the kinds of difference still open and their counts: no new kind, no kind more often --
a fixed kind leaves the baseline, so it cannot come back unnoticed."""

import collections
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/state_build_baseline.json"
TEAMS = ROOT / "tests/fixtures/random_battle_teams.jsonl"

pytestmark = pytest.mark.skipif(not (ROOT / "vendor/pokemon-showdown/dist/sim").exists(),
                                reason="needs the built Showdown simulator")  # fmt: skip


# the first 60 catalog team pairs of the local data/derived/teams/statebuild_catalog_pairs.jsonl
OU_TEAMS = ROOT / "tests/fixtures/state_build_ou_pairs.jsonl"
OU_BASELINE = ROOT / "tests/fixtures/state_build_baseline_ou.json"


def test_the_state_construction_differential_stays_within_its_baseline():
    _check(BASELINE, TEAMS)


def test_ou_teams_stay_within_their_baseline():
    """The same on real OU teams (the catalog's: the human data's metagame)."""
    _check(OU_BASELINE, OU_TEAMS)


REPLAY_BASELINE = ROOT / "tests/fixtures/state_build_baseline_replay.json"


def test_the_replay_path_stays_within_its_baseline():
    """The same for the replay path's construction (enginecheck/replaybuild.py: the training
    positions' -- the spectator's log, both sides' sets the oracle's)."""
    _check(REPLAY_BASELINE, TEAMS, replay=True)


def _check(baseline: Path, teams: Path, replay: bool = False) -> None:
    from alpha_poke.enginecheck.statebuild import battle_diffs

    if replay:
        from alpha_poke.enginecheck.replaybuild import battle_diffs as replay_diffs

    base = json.loads(baseline.read_text())
    pairs = [json.loads(x) for x in teams.read_text().splitlines()]
    kinds: collections.Counter = collections.Counter()
    decisions = 0
    examples: dict = {}
    for i in range(base["battles"]):
        p = pairs[i % len(pairs)]
        diffs, stats = replay_diffs(p["p1"], p["p2"], seed=i) if replay else battle_diffs(p["p1"], p["p2"], seed=i)
        assert not stats["errors"], stats["errors"]
        decisions += stats["decisions"]
        for k, side, kind, detail in diffs:
            kinds[kind] += 1
            examples.setdefault(kind, (i, k, side, detail))
    assert decisions == base["decisions"], "the battles changed: re-record the baseline"
    new = {k: (c, examples[k]) for k, c in kinds.items() if k not in base["open"]}
    assert not new, f"new kinds of difference: {new}"
    more = {k: (c, base["open"][k], examples[k]) for k, c in kinds.items() if c > base["open"][k]}
    assert not more, f"more differences than the baseline: {more}"
