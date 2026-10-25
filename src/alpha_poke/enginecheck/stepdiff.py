"""The engine's one-transition differential on a recorded battle (doc/engine-diff.md,
doc/difftest.md: the ``engine_step`` check): each turn from Showdown's true state at its start,
poke-engine's closest outcome against Showdown's next state. Shared by
scripts/check_engine_random.py and enginecheck/difftest.py."""

import collections
import functools
import re

from alpha_poke import enginecheck as ec


def kind_of(key: str) -> str:
    """'s1.0.hp' -> 'hp', 's2.boost.def' -> 'boost.def', 's1.volatile.x' -> 'volatile.x',
    's1.2.pp[1]' -> 'pp'."""
    return re.sub(r"\[\d+\]$", "", re.sub(r"^s[12]\.(\d+\.)?", "", key))


@functools.cache
def drain_or_recoil() -> frozenset[str]:
    """The engine's moves whose user's HP follows the damage dealt (drain, recoil)."""
    import alpha_search

    rows, _ = alpha_search.engine_data()
    return frozenset(r[0].lower() for r in rows if r[8].startswith("Some") or r[9].startswith("Some"))


def follows_dealt(state: dict, side: int, move: str) -> bool:
    """Whether a side's HP this turn follows the damage it deals (a drain / recoil move, Shell
    Bell): its HP tolerance includes that damage's rolls."""
    s = state["sides"][side]
    item = s["mons"][s["active"]]["item"] if s["active"] >= 0 else ""
    return move.removesuffix("-tera") in drain_or_recoil() or item == "shellbell"


def comparable(steps: list[dict], k: int) -> str | None:
    """Why turn step k cannot be compared with step k + 1 (None: it can)."""
    a, b = steps[k], steps[k + 1]
    if set(a["choices"]) != {"p1", "p2"} or any(
        s["request"] != "move" for s in a["state"]["sides"]
    ):
        return "not a turn start"
    if b["state"]["ended"]:
        return "battle ended"
    return None


def at_decision(steps: list[dict], k: int) -> bool:
    """Whether turn step k stops at a decision (a faint's replacement, a pivot's switch)."""
    a, b = steps[k], steps[k + 1]
    return b["state"]["turn"] != a["state"]["turn"] + 1 or any(
        s["request"] != "move" for s in b["state"]["sides"]
    )


def step_diffs(steps: list[dict], err: str | None, i=0) -> dict:
    """The comparison of every comparable turn of a recorded battle (``ec.random_battle``'s
    steps): counts, kinds, move pairs and each mismatch ("b<i>-t<turn>": choices, kinds, diff,
    the turn's protocol lines)."""
    out = {"turns": 0, "match": 0, "decisions": 0, "skipped": collections.Counter(),
           "kinds": collections.Counter(), "pairs": collections.defaultdict(collections.Counter),
           "mismatches": {}, "errors": []}  # fmt: skip
    if err:
        out["errors"].append(f"showdown: {err.splitlines()[0][:200]}")
    for k in range(len(steps) - 1):
        why = comparable(steps, k)
        if why:
            out["skipped"][why] += 1
            continue
        a, b = steps[k], steps[k + 1]
        c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
        # (L232: Struggle is the engine's none option since 2026-10-22; compared, no longer
        # skipped)
        c1, c2 = ("none" if c == "struggle" else c for c in (c1, c2))
        n = tuple(len(s["mons"]) for s in a["state"]["sides"])
        try:
            # (L199: Showdown's damage rolls as hints: no knockout-or-not roll noise)
            hints = ec.move_hints(a["state"], b["state"])  # (L202: hit counts, Metronome's call)
            outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, hints)
            # (an Endeavor's target ends at its user's HP: it follows the damage it dealt itself)
            dealt = (follows_dealt(a["state"], 0, c1) or c2.startswith("endeavor"),
                     follows_dealt(a["state"], 1, c2) or c1.startswith("endeavor"))  # fmt: skip
            res = ec.closest(b["state"], outs, n, hp=True, dealt=dealt, full=True,
                             start=a["state"], complete=True)  # fmt: skip
        except BaseException as e:  # noqa: BLE001 - the binding's panics are BaseExceptions
            out["errors"].append(f"engine: {c1} | {c2}: {type(e).__name__}: {str(e)[:120]}")
            out["mismatches"][f"b{i}-t{a['state']['turn']}"] = {
                "p1": c1, "p2": c2, "kinds": ["error"], "diff": {"error": [str(e)[:200], None]},
                "log": []}  # fmt: skip
            continue
        out["turns"] += 1
        decision = at_decision(steps, k)
        out["decisions"] += decision
        found = sorted({kind_of(x) for x in res["diff"]})
        if not found:
            out["match"] += 1
            continue
        for f in found:
            out["kinds"][f] += 1
            out["pairs"][f][f"{c1} | {c2}"] += 1
        log = [x for x in b["state"]["log"] if x.startswith(("|move", "|switch", "|drag", "|-",
               "|cant", "|faint", "|upkeep", "|turn"))]  # fmt: skip
        out["mismatches"][f"b{i}-t{a['state']['turn']}"] = {
            "p1": c1, "p2": c2, "kinds": found, "decision": decision,
            "diff": {k: list(v) for k, v in res["diff"].items()}, "log": log}  # fmt: skip
    return out
