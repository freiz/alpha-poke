"""The full-information engine differential (doc/engine-diff.md): random battles in Showdown's
simulator (real OU team pairs, random legal choices), poke-engine's outcomes of every turn
compared with Showdown's truth -- no player's view, no belief (unlike check_engine_diff.py on
self-play records, where the field came from one player's view).

A turn is compared from a turn start to the next turn start, or to the decision point it stops at
(a faint's replacement, a pivot's switch: the engine stops there too; 2026-10-17, they used to be
left out -- 40% of the turns; a fainted active's boosts / volatiles are not compared there).
The engine's state is built from Showdown's own numbers (enginecheck.engine_state); the closest
outcome must agree on every discrete field and on HP within the rolls' spread (closest(hp=True)).

  uv run python scripts/check_engine_random.py --battles 300 --procs 8
  uv run python scripts/check_engine_random.py --update-baseline   # after a fix that passes

Report: data/selfplay/diag/engine_random.json (counts per kind, per move pair, every mismatch
with its diff and the turn's protocol lines).

No regression (doc/engine-diff.md): the battles are deterministic (fixed team pairs in
tests/fixtures/random_battle_teams.jsonl, fixed simulator and choice seeds; the choices do not
depend on the engine), so a position has a stable id "b<battle>-t<turn>". Each mismatch is
(id, kind); the set must be a subset of the baseline's (tests/fixtures/engine_random_baseline.json):
a new (id, kind) is a regression -- listed, exit status 1. --update-baseline writes the new set
only when it is a subset (--force for a deliberate change, e.g. a harness fix that exposes more).
"""

import argparse
import collections
import functools
import hashlib
import json
import multiprocessing as mp
import re
import sys
from pathlib import Path

from alpha_poke import enginecheck as ec


def kind_of(key: str) -> str:
    """'s1.0.hp' -> 'hp', 's2.boost.def' -> 'boost.def', 's1.volatile.x' -> 'volatile.x'."""
    return re.sub(r"^s[12]\.(\d+\.)?", "", key)


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


def battle(job: tuple) -> dict:
    i, p1, p2, max_turns = job[:4]
    off = job[4] if len(job) > 4 else 0  # the seeds' offset (a new set of battles)
    out = {"turns": 0, "match": 0, "decisions": 0, "skipped": collections.Counter(),
           "kinds": collections.Counter(), "pairs": collections.defaultdict(collections.Counter),
           "mismatches": {}, "errors": []}  # fmt: skip
    try:
        k = i + off
        steps, err = ec.random_battle(p1, p2, f"gen5,{k},{k + 1},{k + 2},{k + 3}", k + 1,
                                      max_turns=max_turns)  # fmt: skip
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"runner: {str(e)[:200]}")
        return out
    if err:
        out["errors"].append(f"showdown: {err.splitlines()[0][:200]}")
    for k in range(len(steps) - 1):
        why = comparable(steps, k)
        if why:
            out["skipped"][why] += 1
            continue
        a, b = steps[k], steps[k + 1]
        c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
        if "struggle" in (c1, c2):  # the engine has no choice for it (no PP left)
            out["skipped"]["struggle"] += 1
            continue
        n = tuple(len(s["mons"]) for s in a["state"]["sides"])
        try:
            outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
            # (an Endeavor's target ends at its user's HP: it follows the damage it dealt itself)
            dealt = (follows_dealt(a["state"], 0, c1) or c2.startswith("endeavor"),
                     follows_dealt(a["state"], 1, c2) or c1.startswith("endeavor"))  # fmt: skip
            res = ec.closest(b["state"], outs, n, hp=True, dealt=dealt)
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


def pairs_of(mismatches: dict) -> set[tuple[str, str]]:
    return {(i, k) for i, m in mismatches.items() for k in m["kinds"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=300)
    ap.add_argument("--teams", default="tests/fixtures/random_battle_teams.jsonl",
                    help='team pairs, one {"p1": text, "p2": text} per line')  # fmt: skip
    ap.add_argument("--baseline", default="tests/fixtures/engine_random_baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--force", action="store_true", help="update the baseline even with new ones")
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--seed-offset", type=int, default=0,
                    help="another set of battles: the simulator / choice seeds shifted (0: the "
                    "baseline's)")  # fmt: skip
    ap.add_argument("--out", default="data/selfplay/diag/engine_random.json")
    a = ap.parse_args()
    text = Path(a.teams).read_text()
    pairs = [json.loads(x) for x in text.splitlines()]
    jobs = [(i, pairs[i % len(pairs)]["p1"], pairs[i % len(pairs)]["p2"], a.max_turns,
             a.seed_offset) for i in range(a.battles)]  # fmt: skip
    setup = {"battles": a.battles, "max_turns": a.max_turns,
             "teams": hashlib.sha256(text.encode()).hexdigest()[:16]}  # fmt: skip
    if a.seed_offset:
        setup["seed_offset"] = a.seed_offset
    tot = {"turns": 0, "match": 0, "decisions": 0}
    skipped, kinds = collections.Counter(), collections.Counter()
    pairs_by_kind: dict = collections.defaultdict(collections.Counter)
    mismatches: dict = {}
    errors: collections.Counter = collections.Counter()
    # spawn, not fork: a forked worker can inherit a held lock of the extension modules' threads
    with mp.get_context("spawn").Pool(a.procs) as pool:
        for r in pool.imap_unordered(battle, jobs):
            tot["turns"] += r["turns"]
            tot["match"] += r["match"]
            tot["decisions"] += r["decisions"]
            skipped.update(r["skipped"])
            kinds.update(r["kinds"])
            for k, c in r["pairs"].items():
                pairs_by_kind[k].update(c)
            mismatches.update(r["mismatches"])
            errors.update(re.sub(r"\d+", "N", x) for x in r["errors"])
    n = max(tot["turns"], 1)
    print(f"{a.battles} battles, {tot['turns']} compared turns ({tot['decisions']} to a decision): "
          f"{tot['match']} match "
          f"({100 * tot['match'] / n:.1f}%); skipped {dict(skipped)}")  # fmt: skip
    for k, c in kinds.most_common(30):
        print(f"  {c:6d} ({100 * c / n:.2f}%)  {k:28s} {pairs_by_kind[k].most_common(3)}")
    for e, c in errors.most_common(10):
        print(f"  error x{c}: {e}")
    rep = {**setup, **tot, "skipped": skipped, "kinds": kinds.most_common(),
           "pairs": {k: v.most_common(20) for k, v in pairs_by_kind.items()},
           "mismatches": dict(sorted(mismatches.items())), "errors": errors.most_common()}  # fmt: skip
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1))
    sys.exit(check_baseline(a, setup, mismatches))


def check_baseline(a, setup: dict, mismatches: dict) -> int:
    """The no-regression check: every (position, kind) must be in the baseline."""
    now = pairs_of(mismatches)
    path = Path(a.baseline)
    if path.exists():
        base = json.loads(path.read_text())
        if base["setup"] != setup:
            print(f"baseline of another setup {base['setup']} (now {setup}): not compared")
            return 1
        before = {(i, k) for i, ks in base["mismatches"].items() for k in ks}
        new = sorted(now - before)
        plain = [x for x in new if not mismatches[x[0]].get("decision")]
        print(f"baseline: {len(before)} (position, kind) -> {len(now)}; fixed {len(before - now)}, "
              f"new {len(new)} ({len(plain)} not at a decision)")  # fmt: skip
        for i, k in new:
            m = mismatches[i]
            print(f"  NEW {i} {k}: {m['p1']} | {m['p2']} {m['diff']}")
            print("      " + " ".join(x for x in m["log"] if "-damage" not in x)[:400])
    else:
        new = []
        print(f"no baseline yet ({path})")
    if a.update_baseline:
        if new and not a.force:
            print("baseline not updated: new mismatches (--force to accept them)")
            return 1
        ids = {}
        for i, k in sorted(now):
            ids.setdefault(i, []).append(k)
        path.write_text(json.dumps({"setup": setup, "mismatches": ids}, indent=0) + "\n")
        print(f"baseline updated: {len(now)} (position, kind)")
    return 1 if new else 0


if __name__ == "__main__":
    main()
