"""The differential tests' fast tier (doc/difftest.md): every check on the scenarios and a few
random battles, against tests/fixtures/difftest/fast.json -- no kind new, none more often (a
broken scenario counts as the kind "error"). A fix that removes findings: tighten the baseline
(scripts/difftest.py --corpus fast --update-baseline)."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not (ROOT / "vendor/pokemon-showdown/dist/sim").exists(),
                                reason="needs the built Showdown simulator")  # fmt: skip


def test_the_fast_tier_stays_within_its_baseline():
    from alpha_poke.enginecheck import difftest as dt

    res = dt.run(dt.corpus("fast"), list(dt.CHECKS), procs=8)
    base = json.loads(dt.baseline_path("fast").read_text())
    grown = dt.regressions(res, base)
    detail = {g: res[g.split(":")[0]]["examples"].get(g.split(": ")[1].rsplit(" ", 3)[0], [])[:2] for g in grown}
    assert not grown, (grown, detail)
    # (every check ran on something: a corpus or applies rule that silently skips is no test)
    assert all(o["specs"] > 0 for o in res.values()), {c: o["specs"] for c, o in res.items()}


def test_every_scenario_plays_its_script():
    """A scenario whose script breaks (a choice Showdown refuses) tests nothing: none may."""
    from alpha_poke.enginecheck.scenarios import scenarios

    bad = []
    for s in scenarios():
        views: dict = {}
        steps, err = s.battle(views)
        if err:
            bad.append((s.id, err.splitlines()[0][:120]))
        log = "\n".join(views.get("spectator", []))
        bad += [(s.id, "missing", e) for e in s.expect if e not in log]
    assert not bad, bad
