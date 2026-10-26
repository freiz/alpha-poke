"""The engine's branch probabilities against Showdown's own distribution (2026-10-25 review: the
differential matched each step's one outcome to the nearest branch with a positive probability --
a Will-O-Wisp's 85% made 1% still matched its hits; nothing checked how likely each branch is).

A recorded turn (random_battle.js "serialize_every") is played again in Showdown under ``N``
seeds (showdown_resample.js); each outcome falls into a class -- its state without exact HP
(``ec.view``: statuses, volatiles, boosts, actives, ...) and who fainted -- and so does each
engine branch (poke-engine's own rolls: no hints). A class's
Showdown frequency against the engine's probability: off by more than chance allows (4 sigma,
at least ``FLOOR``) is a "dist.freq" finding; outcomes no branch has, "dist.unmatched"."""

from __future__ import annotations

import collections
import json
import math
import subprocess

from alpha_poke import enginecheck as ec
from alpha_poke.enginecheck.stepdiff import comparable

N = 100  # Showdown's outcomes per turn
EVERY = 4  # every EVERY-th turn with both sides choosing is serialized (random_battle.js)
FLOOR = 0.06  # the least difference reported (the engine's own approximations: a roll's kill chance)
EXAMPLES = 5  # (kept per kind; an analysis may raise it)


def resample(cases: list[dict]) -> list[dict]:
    """[{"battle", "choices": {side: Showdown's choice}, "n", "salt"}] -> [{"states", "error"}]."""
    if not cases:
        return []
    r = subprocess.run(["node", str(ec.RUNNER.with_name("showdown_resample.js")), str(ec.SIM)],
                       input=json.dumps(cases), capture_output=True, text=True, check=True)  # fmt: skip
    return json.loads(r.stdout)


def _fainted(v: dict) -> tuple:
    return tuple(sorted(k for k, x in v.items() if k.endswith(".hp") and x == 0))


def _engine_pattern(o, v: dict) -> tuple:
    """Who fainted. (Not who took damage: the engine's Damage instructions include the residuals,
    Showdown's -damage lines do not match them one to one; nor the HP's direction: a hit healed
    back by Leftovers, one roll more or less -- a pure damage move's miss is left to the HP checks.)"""
    return _fainted(v)


def _showdown_pattern(s: dict, v: dict) -> tuple:
    return _fainted(v)


def _rest(v: dict) -> str:
    return json.dumps({k: x for k, x in sorted(v.items()) if not k.endswith(".hp")}, default=str)


def _describe(v: dict, v0: dict, pattern: tuple) -> dict:
    """A class as its changes from the turn's start (examples)."""
    d = {k: list(x) for k, x in ec.diff(v0, v, skip_hp=True).items()}
    d["fainted"] = pattern
    return d


def turn_dist(a: dict, outcomes: list[dict]) -> dict:
    """One turn: ``a`` the recorded step (state, choices), ``outcomes`` Showdown's states after it.
    {"classes": {key: (p, frequency, description)}, "unmatched": [description, ...]}."""
    c1, c2 = ("none" if a["choices"][s]["engine"] == "struggle" else a["choices"][s]["engine"] for s in ("p1", "p2"))
    nm = tuple(len(s["mons"]) for s in a["state"]["sides"])
    start = ec.engine_state(a["state"])
    v0e, v0s = ec.view_engine(start, nm), ec.view(a["state"])
    branches = []  # (its view, key)
    probs: dict = collections.defaultdict(float)
    desc: dict = {}
    for o in ec.engine_outcomes(start, c1, c2):
        if o[0] <= 0:
            continue
        v = ec.view_engine(o[1], nm)
        key = (_rest(v), _engine_pattern(o, v))
        probs[key] += o[0]
        desc.setdefault(key, _describe(v, v0e, key[1]))
        branches.append((v, key))
    counts: collections.Counter = collections.Counter()
    unmatched = []
    for s in outcomes:
        vs = ec.view(s)
        pat = _showdown_pattern(s, vs)
        # (an outcome that ended the battle: who fainted alone -- Showdown stops the turn at the
        # win, the engine plays it out: ec.end_diff)
        key = next((k for v, k in branches if k[1] == pat and (s.get("ended") or not ec.diff(v, vs, skip_hp=True))), None)
        counts[key] += 1
        if key is None:
            unmatched.append(_describe(vs, v0s, pat))
    n = max(len(outcomes), 1)
    classes = {k: (round(probs.get(k, 0.0), 4), counts.get(k, 0) / n, desc.get(k)) for k in set(probs) | set(counts)
               if k is not None}  # fmt: skip
    return {"classes": classes, "unmatched": unmatched, "n": n, "choices": [c1, c2]}


def off(p: float, f: float, n: int) -> bool:
    """A frequency ``f`` of ``n`` outcomes further from ``p`` than chance allows."""
    return abs(f - p) > max(4 * math.sqrt(max(p * (1 - p), 1 / n) / n), FLOOR)


def _drawn(state: dict) -> str | None:
    """What Showdown drew already that a replay keeps (its serialization holds it) while the
    engine models it as chance: a hidden length running on an active (confusion's, a lock's, a
    partial trap's), an active's sleep -- such a turn's distribution is not the engine's to match."""
    for s in state["sides"]:
        if s["active"] < 0:
            continue
        m = s["mons"][s["active"]]
        if set(m["volatiles"]) & set(ec.HIDDEN_LENGTH):
            return "a hidden length drawn"
        if m["status"] == "slp":
            return "a sleep's length drawn"
    return None


def dist_diffs(steps: list[dict], n: int = N) -> dict:
    """Every serialized comparable turn of a recorded battle: {"compared", "kinds", "examples",
    "errors", "skipped"}."""
    out: dict = {"compared": 0, "kinds": collections.Counter(), "examples": {}, "errors": [],
                 "skipped": collections.Counter()}  # fmt: skip
    cases, at = [], []
    for k in range(len(steps) - 1):
        why = comparable(steps, k)
        if why or "battle" not in steps[k]:
            continue
        why = _drawn(steps[k]["state"])
        # (a Metronome's call: the engine's needs its hint, the move Showdown drew -- no model of
        # its own to compare)
        if any(steps[k]["choices"][s]["engine"].startswith("metronome") for s in ("p1", "p2")):
            why = "a Metronome's call"
        if why:
            out["skipped"][why] += 1
            continue
        cases.append({"battle": steps[k]["battle"], "n": n, "salt": k,
                      "choices": {s: steps[k]["choices"][s]["choice"] for s in ("p1", "p2")}})  # fmt: skip
        at.append(k)
    try:
        results = resample(cases)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        out["errors"].append(f"resample: {type(e).__name__}: {str(e)[:150]}")
        return out
    for k, r in zip(at, results, strict=True):
        if r["error"]:
            out["errors"].append(f"resample t{steps[k]['state']['turn']}: {r['error'].splitlines()[0][:150]}")
            continue
        try:
            t = turn_dist(steps[k], r["states"])
        except BaseException as e:  # noqa: BLE001 - the binding's panics are BaseExceptions
            out["errors"].append(f"engine t{steps[k]['state']['turn']}: {type(e).__name__}: {str(e)[:120]}")
            continue
        out["compared"] += 1
        found = []
        if len(t["unmatched"]) / t["n"] > FLOOR:
            found.append(("dist.unmatched", {"share": len(t["unmatched"]) / t["n"], "outcome": t["unmatched"][0]}))
        for p, f, d in t["classes"].values():
            if off(p, f, t["n"]):
                found.append(("dist.freq", {"engine": p, "showdown": f, "outcome": d}))
        for kind in sorted({x[0] for x in found}):
            out["kinds"][kind] += 1
            ex = out["examples"].setdefault(kind, [])
            if len(ex) < EXAMPLES:
                ex.append({"turn": steps[k]["state"]["turn"], "choices": t["choices"],
                           "found": [x[1] for x in found if x[0] == kind][:3]})  # fmt: skip
    return out
