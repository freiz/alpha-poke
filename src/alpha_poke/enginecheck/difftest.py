"""The differential test framework (doc/difftest.md): battle specs, corpora, the checks run on
each recorded battle, and the comparison with the baselines.

A spec is a battle: two teams, a seed, a turn limit, an optional script (the first decision
points' choices), a format. ``enginecheck.random_battle`` records it once per simulator build
(the cache), so every check reads the same battle without playing it again. A check takes a spec
and gives {"n": units compared, "kinds": {kind: count}, "examples": {kind: [...]}, "errors":
[...]}; ``run`` runs checks over a corpus in parallel and sums them up; ``regressions`` compares a
run with its baseline (no new kind, no kind more often)."""

import collections
import glob
import json
import multiprocessing as mp
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
BASELINES = FIXTURES / "difftest"
# the players' format: HP as a percent to the other side (gen9customgame is a debug format, every
# HP exact -- so F1's evidence, read as percents, cannot be checked there; the training data's
# and the live battles' logs are percents)
PCT = "gen9ou"


@dataclass(frozen=True)
class Spec:
    id: str
    p1: str
    p2: str
    seed: int
    max_turns: int = 40
    script: str = ""  # JSON: [{"p1": choice, "p2": choice}, ...]
    fmt: str = ""  # "" = enginecheck.FORMAT (exact HP)
    tags: tuple = field(default=())
    # (a scenario's proof it plays its mechanism: lines its spectator log must have -- a script can
    # run and test nothing: an Endure that never had to hold on, 2026-10-24)
    expect: tuple = field(default=())

    @property
    def steps_script(self) -> list | None:
        return json.loads(self.script) if self.script else None

    def battle(self, views: dict | None = None):
        from alpha_poke.enginecheck import random_battle

        kw = {"fmt": self.fmt} if self.fmt else {}
        s = self.seed
        return random_battle(self.p1, self.p2, f"gen5,{s},{s + 1},{s + 2},{s + 3}", s + 1,
                             max_turns=self.max_turns, views=views, script=self.steps_script, **kw)  # fmt: skip


def random_specs(files: str, n: int, offset: int = 0, fmt: str = "", tag: str = "random") -> list[Spec]:
    """``n`` battles of each team-pair file (globs, comma-separated): pairs[i], seed offset + i."""
    out = []
    for f in sorted({x for g in files.split(",") for x in (glob.glob(str(ROOT / g)) or [g])}):
        pairs = [json.loads(x) for x in Path(f).read_text().splitlines()]
        stem = Path(f).stem.replace("random_battle_teams", "rbt")
        for i in range(n):
            p = pairs[i % len(pairs)]
            out.append(Spec(f"{tag}/{stem}/{offset + i}", p["p1"], p["p2"], offset + i, fmt=fmt, tags=(tag,)))
    return out


def corpus(name: str) -> list[Spec]:
    """A named corpus: "fast" (the scenarios, 20 random battles, 10 in the players' format: pytest),
    "full" (each fixtures file 50 battles, seeds from 7000, and 10 each in the players' format),
    "scenarios"."""
    from alpha_poke.enginecheck.scenarios import scenarios

    fx = "tests/fixtures/random_battle_teams*.jsonl"
    if name == "scenarios":
        return scenarios()
    if name == "fast":
        return (scenarios() + random_specs("tests/fixtures/random_battle_teams.jsonl", 20)
                + random_specs("tests/fixtures/random_battle_teams.jsonl", 10, 100, PCT, "pct"))  # fmt: skip
    if name == "full":
        return (scenarios() + random_specs(fx, 50, 7000)
                + random_specs(fx, 10, 8000, PCT, "pct"))  # fmt: skip
    raise ValueError(f"unknown corpus {name}")


# ---- the checks -------------------------------------------------------------------------------


def _result(n: int = 0) -> dict:
    # ("skipped": reason -> what a check left out uncompared -- kept, the baseline bounds it)
    return {"n": n, "kinds": collections.Counter(), "examples": {}, "errors": [], "skipped": collections.Counter()}


def _add(out: dict, kind: str, detail, cap: int = 5) -> None:
    out["kinds"][kind] += 1
    ex = out["examples"].setdefault(kind, [])
    if len(ex) < cap:
        ex.append(detail)


def check_engine_step(spec: Spec) -> dict:
    from alpha_poke.enginecheck.stepdiff import step_diffs

    steps, err = spec.battle()
    r = step_diffs(steps, err)
    out = _result(r["turns"])
    for key, m in r["mismatches"].items():
        for k in m["kinds"]:
            _add(out, k, {"at": key, "choices": [m["p1"], m["p2"]], "diff": m["diff"]})
    out["errors"] = r["errors"]
    out["skipped"].update(r["skipped"])
    return out


def check_engine_chain(spec: Spec) -> dict:
    from alpha_poke.enginecheck.chaindiff import chain_diffs

    steps, err = spec.battle()
    r = chain_diffs(steps)
    out = _result(r["compared"])
    for k, c in r["kinds"].items():
        out["kinds"][k] += c
        out["examples"][k] = r["examples"].get(k, [])
    out["errors"] = r["errors"] + ([f"showdown: {err.splitlines()[0][:150]}"] if err else [])
    return out


def _state(spec: Spec, path: str) -> dict:
    if path == "replay":
        from alpha_poke.enginecheck.replaybuild import battle_diffs

        diffs, st = battle_diffs(spec.p1, spec.p2, spec.seed, spec.max_turns, spec.steps_script, spec.fmt or None)
    else:
        from alpha_poke.enginecheck.statebuild import battle_diffs

        diffs, st = battle_diffs(spec.p1, spec.p2, spec.seed, spec.max_turns, oracle=True,
                                 script=spec.steps_script, fmt=spec.fmt or None)  # fmt: skip
    out = _result(st["decisions"])
    for k, side, kind, detail in diffs:
        _add(out, kind, {"step": k, "side": side, "detail": detail})
    out["errors"] = st["errors"]
    out["skipped"].update(x.split(":")[0] for x in st.get("skipped", []))
    return out


def check_state_live(spec: Spec) -> dict:
    return _state(spec, "live")


def check_state_replay(spec: Spec) -> dict:
    return _state(spec, "replay")


def check_tree_history(spec: Spec) -> dict:
    from alpha_poke.enginecheck.treediff import tree_diffs

    r = tree_diffs(spec.p1, spec.p2, spec.seed, spec.max_turns, spec.steps_script, spec.id)
    out = _result(r["steps"])
    for k, c in r["struct"].items():
        out["kinds"][f"tree:{k}"] += c
    for e in r["examples"]:
        for m in e[-1]:
            ex = out["examples"].setdefault(f"tree:{m}", [])
            if len(ex) < 5:
                ex.append({"turn": e[2], "choices": [e[3], e[4]], "log": e[5]})
    out["errors"] = r["errors"]
    out["skipped"].update(r["skipped"])
    return out


def check_belief_truth(spec: Spec) -> dict:
    from alpha_poke.enginecheck.beliefcheck import belief_diffs

    r = belief_diffs(spec.p1, spec.p2, spec.seed, spec.max_turns, spec.steps_script, spec.fmt or None)
    out = _result(r["decisions"])
    for k, c in r["kinds"].items():
        out["kinds"][k] += c
        out["examples"][k] = r["examples"].get(k, [])
    out["errors"] = r["errors"]
    return out


# (name -> (the check, which specs it runs on)): the state checks on exact HP (their comparator
# reads the true HP: a percent view's rounding is no error -- not covered yet), the belief's in
# the players' format (F1 reads percents)
CHECKS = {
    "engine_step": (check_engine_step, lambda s: True),
    "engine_chain": (check_engine_chain, lambda s: True),
    "state_live": (check_state_live, lambda s: not s.fmt),
    "state_replay": (check_state_replay, lambda s: not s.fmt),
    "tree_history": (check_tree_history, lambda s: not s.fmt),
    "belief_truth": (check_belief_truth, lambda s: s.fmt == PCT),
}


def _job(job):
    check, spec = job
    try:
        r = CHECKS[check][0](spec)
    except BaseException as e:  # noqa: BLE001 - a broken check / scenario is a finding, not a crash
        r = _result()
        r["errors"].append(f"{type(e).__name__}: {str(e)[:200]}")
    r["kinds"] = dict(r["kinds"])
    r["skipped"] = dict(r.get("skipped", {}))
    return check, spec.id, r


def run(specs: list[Spec], checks: list[str], procs: int = 8) -> dict:
    """Every check on every spec it applies to: {check: {"specs", "n", "kinds": {kind: count},
    "examples": {kind: [(spec id, detail), ...]}, "errors": [(spec id, error), ...]}}; a spec's
    errors count as the kind "error"."""
    jobs = [(c, s) for c in checks for s in specs if CHECKS[c][1](s)]
    out = {c: {"specs": 0, "n": 0, "kinds": collections.Counter(), "examples": {}, "errors": [],
               "skipped": collections.Counter()} for c in checks}  # fmt: skip
    with mp.get_context("spawn").Pool(procs) as pool:
        for c, sid, r in pool.imap_unordered(_job, jobs):
            o = out[c]
            o["specs"] += 1
            o["n"] += r["n"]
            o["kinds"].update(r["kinds"])
            o["skipped"].update(r["skipped"])
            for k, ex in r["examples"].items():
                lst = o["examples"].setdefault(k, [])
                lst += [(sid, x) for x in ex[: max(0, 10 - len(lst))]]
            if r["errors"]:
                o["kinds"]["error"] += len(r["errors"])
                o["errors"] += [(sid, e) for e in r["errors"][:3]]
    for o in out.values():
        o["kinds"] = dict(sorted(o["kinds"].items()))
        o["skipped"] = dict(sorted(o["skipped"].items()))
    return out


def baseline_path(name: str) -> Path:
    return BASELINES / f"{name}.json"


COMPARED = "#compared"  # (a baseline's comparisons made: fewer is a regression)
SKIPPED = "#skipped: "  # (+ a reason: more left out is one)


def regressions(result: dict, baseline: dict) -> list[str]:
    """What a run has more of than its baseline: a new kind, or a kind more often; a skip reason
    more often; fewer comparisons (2026-10-25 review: every check at 0 compared passed -- the
    baseline counted findings only)."""
    out = []
    for c, o in result.items():
        base = baseline.get(c, {})
        counts = {**o["kinds"], **{SKIPPED + k: n for k, n in o.get("skipped", {}).items()}}
        for k, n in counts.items():
            if n > base.get(k, 0):
                out.append(f"{c}: {k} {base.get(k, 0)} -> {n}")
        if o["n"] < base.get(COMPARED, 0):
            out.append(f"{c}: {COMPARED} {base[COMPARED]} -> {o['n']}")
    return out


def updated_baseline(base: dict, result: dict, checks: list[str], only: str, force: bool) -> tuple[dict | None, str]:
    """The baseline a run writes (None: refused, and why): not from a subset of the corpus (its
    counts are the whole corpus' -- 2026-10-25 review, an --only run emptied a check's), not over
    a regression unless forced; a subset of the checks replaces those checks' alone."""
    if only:
        return None, "a subset of the corpus (--only) writes no baseline: its counts are the whole corpus'"
    grown = regressions(result, base)
    if grown and not force:
        return None, f"{len(grown)} regressions (--force: a deliberate change)"
    return (base | baseline_of(result) if set(checks) != set(CHECKS) else baseline_of(result)), ""


def baseline_of(result: dict) -> dict:
    return {c: {**o["kinds"], **{SKIPPED + k: n for k, n in o.get("skipped", {}).items()}, COMPARED: o["n"]}
            for c, o in result.items()}  # fmt: skip
