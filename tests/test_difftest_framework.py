"""The differential framework's own guards (2026-10-25 review: seven ways a check reported no
difference without having compared) -- each test injects the failure and asserts it is seen."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_sim = pytest.mark.skipif(not (ROOT / "vendor/pokemon-showdown/dist/sim").exists(),
                               reason="needs the built Showdown simulator")  # fmt: skip


def test_a_reference_state_that_fails_to_build_is_a_difference():
    """extra_diff caught the conversion's error and returned no difference: the extended fields
    and the legal options went unchecked."""
    from alpha_poke import enginecheck as ec

    d = ec.extra_diff({}, (1.0, None))
    assert set(d) == {"reference_state"}, d


def _recorded_pair():
    """A recorded turn: (Showdown's state before, after, the engine's outcomes of its choices)."""
    from alpha_poke import enginecheck as ec
    from alpha_poke.enginecheck.scenarios import FILLER, S, team

    gengar = S("Gengar", "Leftovers", "Cursed Body", ["Confuse Ray", "Protect", "Shadow Ball", "Taunt"],
               "252 HP / 4 Atk / 252 Spe", "Timid")  # fmt: skip
    steps, err = ec.random_battle(team(gengar, FILLER), team(FILLER, FILLER), "gen5,1,2,3,4", 2, max_turns=4,
                                  script=[{"p1": "move 2", "p2": "move 4"}, {"p1": "move 1", "p2": "move 4"},
                                          {"p1": "move 2", "p2": "move 4"}])  # fmt: skip
    assert err is None
    return steps


def _without(outcome, volatile: str):
    """The engine outcome with ``volatile`` taken off both actives (an effect never applied)."""
    import poke_engine as pe

    from alpha_poke import enginecheck as ec

    st = outcome[1]
    sides = []
    for a in (st.side_one, st.side_two):
        kw = {x: getattr(a, x) for x in dir(pe.Side) if not x.startswith("_")}
        kw["volatile_statuses"] = {str(v).lower() for v in a.volatile_statuses} - {volatile}
        sides.append(pe.Side(**kw))
    new = pe.State(side_one=sides[0], side_two=sides[1]).to_string().split("/")[:2]
    rest = st.to_string().split("/")[2:]
    return ec.Outcome(outcome[0], pe.State.from_string("/".join(new + rest)), outcome.damage, outcome.sub_damage)


@needs_sim
def test_the_chain_sees_an_effect_never_applied(monkeypatch):
    """The chain filtered a hidden-length volatile new in the step (its presence too), then synced
    it from the truth: a Confuse Ray's confusion the engine never applied went unseen. Its count
    is Showdown's draw; its presence is not."""
    from alpha_poke import enginecheck as ec
    from alpha_poke.enginecheck import chaindiff

    steps = _recorded_pair()
    assert any("|-start|p2a: Snorlax|confusion" in x for x in steps[2]["state"]["log"])
    assert chaindiff.chain_diffs(steps)["kinds"].get("volatile.confusion", 0) == 0
    real = ec.engine_outcomes
    monkeypatch.setattr(ec, "engine_outcomes", lambda *a, **k: [_without(o, "confusion") for o in real(*a, **k)])
    assert chaindiff.chain_diffs(steps)["kinds"].get("volatile.confusion", 0) >= 1


@needs_sim
def test_a_probability_0_branch_is_no_match():
    """closest picked the nearest state whatever its probability: the right state at 0, a wrong
    one at 1, read as no difference. Only a positive branch matches; the branches must sum to 1."""
    from alpha_poke import enginecheck as ec

    steps = _recorded_pair()
    a, b = steps[1]["state"], steps[2]["state"]
    outs = ec.engine_outcomes(ec.engine_state(a), *(steps[1]["choices"][s]["engine"] for s in ("p1", "p2")))
    n = tuple(len(x["mons"]) for x in a["sides"])

    def at(p, o):
        return ec.Outcome(p, o[1], o.damage, o.sub_damage)

    right = min(outs, key=lambda o: len(ec.closest(b, [at(1.0, o)], n)["diff"]))
    wrong = ec.Outcome(1.0, ec.engine_state(a), (0, 0), (0, 0))  # (nothing happened: no confusion)
    assert not ec.closest(b, [at(1.0, right)], n)["diff"]
    assert ec.closest(b, [wrong], n)["diff"]
    res = ec.closest(b, [at(0.0, right), wrong], n)
    assert res["diff"], res
    res = ec.closest(b, [at(0.4, right)], n, complete=True)  # (all of the branches: they sum to 1)
    assert "probability" in res["diff"], res
    assert not ec.closest(b, [at(0.4, right)], n)["diff"]  # (a part of them: a test's chosen one)
    assert "probability" in ec.closest(b, [at(0.8, right), at(0.8, wrong)], n)["diff"]


def test_fewer_comparisons_or_more_skips_regress():
    from alpha_poke.enginecheck import difftest as dt

    run = {"engine_step": {"n": 10, "kinds": {"hp": 2}, "skipped": {"no choice": 1}}}
    base = dt.baseline_of(run)
    assert dt.regressions(run, base) == []
    assert dt.regressions({"engine_step": {**run["engine_step"], "n": 0}}, base) == \
        ["engine_step: #compared 10 -> 0"]  # fmt: skip
    assert dt.regressions({"engine_step": {**run["engine_step"], "skipped": {"no choice": 2}}}, base) == \
        ["engine_step: #skipped: no choice 1 -> 2"]  # fmt: skip
    # (a part of the corpus, --only: fewer comparisons are no regression; more findings still are --
    # 2026-10-25 review, every --only run exited 1)
    part = {"engine_step": {"n": 2, "kinds": {"hp": 1}, "skipped": {}}}
    assert dt.regressions(part, base, subset=True) == []
    assert dt.regressions({"engine_step": {**part["engine_step"], "kinds": {"hp": 3}}}, base, subset=True) == \
        ["engine_step: hp 2 -> 3"]  # fmt: skip


def test_a_refused_baseline_update_is_refused():
    """A subset (--only) emptied a check's baseline; an update a regression refused exited 0 (the
    script returns 1 when updated_baseline refuses)."""
    from alpha_poke.enginecheck import difftest as dt

    checks = list(dt.CHECKS)
    full = {c: {"n": 10, "kinds": {"hp": 2, "status": 1}, "skipped": {}} for c in checks}
    base = dt.baseline_of(full)
    sub = {c: {"n": 1, "kinds": {}, "skipped": {}} for c in checks}
    new, why = dt.updated_baseline(base, sub, checks, "scenario/x", force=True)
    assert new is None and "--only" in why
    more = {c: {"n": 10, "kinds": {"hp": 3, "status": 1}, "skipped": {}} for c in checks}
    new, why = dt.updated_baseline(base, more, checks, "", force=False)
    assert new is None and "regressions" in why
    new, _ = dt.updated_baseline(base, more, checks, "", force=True)
    assert new["engine_step"]["hp"] == 3


@needs_sim
def test_a_refused_update_exits_1(tmp_path, monkeypatch):
    """The script's own exit status (2026-10-25 review: REGRESSION printed, the baseline kept, 0)."""
    import importlib.util
    import sys

    from alpha_poke.enginecheck import difftest as dt

    spec = importlib.util.spec_from_file_location("difftest_script", ROOT / "scripts" / "difftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(dt, "run", lambda specs, checks, procs: {
        c: {"specs": 1, "n": 1, "kinds": {"hp": 3}, "examples": {}, "errors": [], "skipped": {}} for c in checks})
    monkeypatch.setattr(dt, "baseline_path", lambda name: tmp_path / f"{name}.json")
    (tmp_path / "fast.json").write_text(json.dumps({c: {"hp": 2, "#compared": 1} for c in dt.CHECKS}))
    for argv, code in ((["--update-baseline"], 1), (["--update-baseline", "--only", "scenario/"], 1), ([], 1),
                       (["--update-baseline", "--force"], 0)):  # fmt: skip
        monkeypatch.setattr(sys, "argv", ["difftest.py", "--corpus", "fast", "--out", str(tmp_path / "o.json"), *argv])
        assert mod.main() == code, argv
    assert json.loads((tmp_path / "fast.json").read_text())["engine_step"]["hp"] == 3
    # (an --only run that finds no more than the corpus' baseline: 0, though it compares less)
    (tmp_path / "fast.json").write_text(json.dumps({c: {"hp": 3, "#compared": 100} for c in dt.CHECKS}))
    monkeypatch.setattr(sys, "argv", ["difftest.py", "--corpus", "fast", "--out", str(tmp_path / "o.json"),
                                      "--only", "scenario/"])  # fmt: skip
    assert mod.main() == 0


def test_the_recording_depends_on_the_format_rules():
    """The cache fingerprint scanned dist/sim and dist/data: Showdown's format rules
    (dist/config/formats.js) and its lib changed nothing."""
    from alpha_poke import enginecheck as ec

    names = {str(f.relative_to(ec.SIM.parent)) for f in ec._recorder_files()}
    if (ec.SIM.parent / "config" / "formats.js").exists():
        assert "config/formats.js" in names
    assert any(n.startswith("lib/") for n in names) or not (ec.SIM.parent / "lib").exists()


def test_the_tree_check_keeps_a_recording_error(monkeypatch):
    """tree_diffs dropped the recorder's error: a failed recording read as no error."""
    # (the modules tree_diffs imports first: bound to the real recorder before the patch -- one
    # imported under it keeps the fake: the state checks' tests broke after this one)
    import alpha_poke.enginecheck.statebuild  # noqa: F401
    import alpha_poke.replay  # noqa: F401
    import alpha_poke.train.positions  # noqa: F401
    from alpha_poke import enginecheck as ec
    from alpha_poke.enginecheck import treediff

    def broken(*a, views=None, **k):
        views["spectator"] = ["|player|p1|a|", "|player|p2|b|", "|turn|1"]
        return [], "Error: the battle broke off\n  at ..."

    monkeypatch.setattr(ec, "random_battle", broken)
    r = treediff.tree_diffs("", "", 1)
    assert any("broke off" in e for e in r["errors"]), r


def test_every_side_condition_is_compared():
    """The state checks compared a hand-written list of side conditions: Healing Wish was never in
    it -- never compared, never built (S158, found by state_chain). Every engine field now."""
    import poke_engine as pe

    from alpha_poke.enginecheck import statebuild

    assert set(statebuild.CONDITIONS) == {x for x in dir(pe.SideConditions) if not x.startswith("_")}
    assert "healing_wish" in statebuild.CONDITIONS


@needs_sim
def test_the_foes_side_fields_are_compared():
    """foe_diffs compared no side field -- a pending Wish, Future Sight, a Substitute's HP: the
    live path's opponent and the replay path's both sides never had them checked (2026-10-25
    review)."""
    import poke_engine as pe

    from alpha_poke import enginecheck as ec
    from alpha_poke.enginecheck import statebuild

    side = ec.engine_state(_recorded_pair()[1]["state"]).side_two
    kw = {x: getattr(side, x) for x in dir(pe.Side) if not x.startswith("_")}
    for k, v in (("wish", (2, 150)), ("future_sight", (2, pe.PokemonIndex("0")))):
        other = pe.Side(**(kw | {k: v}))
        seen = {statebuild._sp(p) for p in side.pokemon}
        for oracle in (True, False):
            assert any(d[0] == f"foe:{k}" for d in statebuild.foe_diffs(other, side, seen, oracle)), (k, oracle)
        assert not statebuild.foe_diffs(side, side, seen, True)


def test_every_field_is_compared_or_says_why():
    """The state checks' compared fields were hand-listed: one left out was 0 for ever (Healing
    Wish, the Toxic Spikes' order, a Rage Fist's count, a forme's level -- 2026-10-25). Every
    field of the engine's state, side and mon is compared or skipped with its reason; a new
    engine field fails here until it is one of them."""
    import poke_engine as pe

    from alpha_poke.enginecheck import statebuild as sb

    def fields(cls):
        return {x for x in dir(cls) if not x.startswith("_")}

    assert fields(pe.Pokemon) == set(sb.MON_FIELDS) | set(sb.STATS) | set(sb.MON_OWN_WAY) | set(sb.MON_SKIPPED)
    assert fields(pe.Side) == set(sb.SIDE_FIELDS) | set(sb.SIDE_OWN_WAY) | set(sb.SIDE_SKIPPED)
    assert fields(pe.State) == set(sb.STATE_FIELDS) | set(sb.STATE_SKIPPED)
    assert all(sb.MON_SKIPPED.values()) and all(sb.SIDE_SKIPPED.values()) and all(sb.STATE_SKIPPED.values())



@needs_sim
def test_a_wrong_chance_is_seen(monkeypatch):
    """closest matched a step's one outcome to any branch with a positive probability: a
    Will-O-Wisp's 85% made 15% matched its hits all the same (2026-10-25 review). distdiff plays
    the turn again in Showdown under many seeds: the frequencies against the engine's."""
    from alpha_poke import enginecheck as ec
    from alpha_poke.enginecheck import distdiff
    from alpha_poke.enginecheck.scenarios import FILLER, S, team

    gengar = S("Gengar", "Leftovers", "Cursed Body", ["Will-O-Wisp", "Protect", "Shadow Ball", "Taunt"],
               "252 HP / 4 Atk / 252 Spe", "Timid")  # fmt: skip
    steps, err = ec.random_battle(team(gengar, FILLER), team(FILLER, FILLER), "gen5,1,2,3,4", 2, max_turns=2,
                                  script=[{"p1": "move 1", "p2": "move 4"}], serialize_every=1)  # fmt: skip
    assert err is None and "battle" in steps[0]
    one = steps[:2]
    r = distdiff.dist_diffs(one)
    assert r["compared"] == 1 and not r["kinds"], r
    real = ec.engine_outcomes

    def skewed(*a, **k):  # (the hit's chance and the miss's swapped: 15% / 85%)
        outs = real(*a, **k)
        ps = [o[0] for o in outs][::-1]
        return [ec.Outcome(p, o[1], o.damage, o.sub_damage) for p, o in zip(ps, outs, strict=True)]

    monkeypatch.setattr(ec, "engine_outcomes", skewed)
    r = distdiff.dist_diffs(one)
    assert r["kinds"].get("dist.freq") == 1, r


@needs_sim
def test_a_bench_mons_hp_has_no_roll_in_it():
    """hp_diff's tolerance was its side's damage this turn: a Sludge Bomb's 8.5% on the active
    let a bench mon's HP be off as much (2026-10-25 review). The damage by mon (the active it hit
    then)."""
    import copy

    from alpha_poke import enginecheck as ec
    from alpha_poke.enginecheck.scenarios import FILLER, S, team

    gengar = S("Gengar", "Leftovers", "Cursed Body", ["Sludge Bomb", "Protect", "Taunt", "Will-O-Wisp"],
               "252 HP / 4 Atk / 252 Spe", "Timid")  # fmt: skip
    p2 = team(S("Snorlax", "", "Thick Fat", ["Curse", "Rest", "Slack Off", "Body Slam"]), FILLER)
    steps, err = ec.random_battle(team(gengar, FILLER), p2, "gen5,1,2,3,4", 2, max_turns=2,
                                  script=[{"p1": "move 1", "p2": "move 1"}])  # fmt: skip
    assert err is None
    a, b = steps[0]["state"], steps[1]["state"]
    outs = ec.engine_outcomes(ec.engine_state(a), "sludgebomb", "curse")
    n = tuple(len(s["mons"]) for s in a["sides"])
    o = next(x for x in outs if x[0] > 0 and not ec.hp_diff(b, x, n))  # (the one that happened)
    assert o.damage[1] >= 60
    off = copy.deepcopy(b)
    bench = next(j for j, m in enumerate(off["sides"][1]["mons"]) if j != off["sides"][1]["active"])
    off["sides"][1]["mons"][bench]["hp"] -= 5
    assert f"s2.{bench}.hp" in ec.hp_diff(off, o, n)
    # (by side, as before: within)
    assert not ec.hp_diff(off, ec.Outcome(o[0], o[1], o.damage, o.sub_damage), n)


def test_a_fixed_finding_does_not_hide_a_new_one():
    """regressions compared the kinds' totals alone: a finding fixed in one battle hid a new one
    in another (2026-10-25 review). By spec too."""
    from alpha_poke.enginecheck import difftest as dt

    run = {"engine_step": {"n": 10, "kinds": {"hp": 1}, "skipped": {}, "by_spec": {"a": {"hp": 1}}}}
    base = dt.baseline_of(run)
    assert dt.regressions(run, base) == []
    moved = {"engine_step": {"n": 10, "kinds": {"hp": 1}, "skipped": {}, "by_spec": {"b": {"hp": 1}}}}
    assert dt.regressions(moved, base) == ["engine_step: b hp 0 -> 1"]
    # (a baseline from before the split: its totals only)
    old = {"engine_step": {k: v for k, v in base["engine_step"].items() if k != dt.BY_SPEC}}
    assert dt.regressions(moved, old) == []


@needs_sim
def test_the_last_transition_is_compared_by_its_faints():
    """A battle's last transition was skipped by every check (2026-10-25 review). Showdown stops
    the turn at the win, the engine plays it out: who fainted -- the winner -- is compared."""
    from alpha_poke import enginecheck as ec
    from alpha_poke.enginecheck.scenarios import FILLER, S, team

    gengar = S("Gengar", "Leftovers", "Cursed Body", ["Shadow Ball", "Protect", "Taunt", "Will-O-Wisp"],
               "252 HP / 4 Atk / 252 Spe", "Timid")  # fmt: skip
    shedinja = S("Shedinja", "", "Wonder Guard", ["Swords Dance", "Shadow Sneak", "X-Scissor", "Protect"])
    steps, err = ec.random_battle(team(gengar, FILLER), team(shedinja), "gen5,1,2,3,4", 2, max_turns=3,
                                  script=[{"p1": "move 1", "p2": "move 1"}])  # fmt: skip
    assert err is None and steps[1]["state"]["ended"]
    a, b = steps[0]["state"], steps[1]["state"]
    n = tuple(len(s["mons"]) for s in a["sides"])
    outs = ec.engine_outcomes(ec.engine_state(a), "shadowball", "swordsdance")
    assert ec.end_diff(b, outs, n)["diff"] == {}
    nothing = ec.Outcome(1.0, ec.engine_state(a), (0, 0), (0, 0))
    assert "end.fainted" in ec.end_diff(b, [nothing], n)["diff"]
    from alpha_poke.enginecheck.stepdiff import comparable

    assert comparable(steps, 0) is None


@needs_sim
def test_the_tree_check_takes_no_probability_0_branch(monkeypatch):
    """tree_diffs matched the log's step to the nearest of the tree's whatever its probability --
    the right one at 0, a wrong one at 1 read as no difference (2026-10-25 review)."""
    import alpha_search

    from alpha_poke.enginecheck import difftest as dt
    from alpha_poke.enginecheck import treediff

    spec = next(s for s in dt.corpus("fast") if s.id == "scenario/ends/healing-wish-waits")
    clean = treediff.tree_diffs(spec.p1, spec.p2, spec.seed, spec.max_turns, spec.steps_script, spec.id)
    assert clean["steps"] and not clean["struct"]
    real = alpha_search.tree_steps

    def zero_right(s, i1, i2, logged, *a):
        tree, (l1, l2) = real(s, i1, i2, logged, *a)
        wrong = (l1[0], l1[1], l1[2] + 1, *l1[3:])  # (another actor)
        return [(0.0, l1, l2, 0, False), (1.0, wrong, l2, 0, False)], (l1, l2)

    monkeypatch.setattr(alpha_search, "tree_steps", zero_right)
    r = treediff.tree_diffs(spec.p1, spec.p2, spec.seed, spec.max_turns, spec.steps_script, spec.id)
    assert r["struct"].get("one.actor", 0) == r["steps"], r["struct"]


def test_the_mutation_script_fails_loudly(monkeypatch, tmp_path):
    """The mutation script read the runner's output alone: a crash was "nothing found", a failed
    restore printed STALE and exited 0 (2026-10-25 review); a run with no mutation said "every
    mutation caught"."""
    import importlib.util
    import subprocess
    import sys
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("difftest_mutations", ROOT / "scripts" / "difftest_mutations.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(sys, "argv", ["difftest_mutations.py"])
    crash = SimpleNamespace(returncode=2, stdout="", stderr="Traceback ...\nImportError: x")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: crash)
    assert m.main() == 2  # (the code as it is: the runner broke)
    monkeypatch.setattr(m, "MUTATIONS", [])
    monkeypatch.setattr(m, "_fast", lambda: [])
    assert m.main() == 2  # (nothing to run)
    f = tmp_path / "x.py"
    f.write_text("a = 1\n")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "MUTATIONS", [("x", "x.py", "a = 1", "a = 2")])
    calls = iter([[], ["REGRESSION x"], ["REGRESSION still"]])  # (before, mutated, after the restore)
    monkeypatch.setattr(m, "_fast", lambda: next(calls))
    assert m.main() == 3 and f.read_text() == "a = 1\n"
