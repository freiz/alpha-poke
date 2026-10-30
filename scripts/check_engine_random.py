"""The full-information engine differential (doc/engine-diff.md): random battles in Showdown's
simulator (real OU team pairs, random legal choices), poke-engine's outcomes of every turn
compared with Showdown's truth -- no player's view, no belief (unlike the removed check_engine_diff.py on
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
import hashlib
import json
import multiprocessing as mp
import re
import sys
from pathlib import Path

from alpha_poke import enginecheck as ec
from alpha_poke.enginecheck.stepdiff import (  # noqa: F401 (kind_of: the report's)
    kind_of,
    step_diffs,
)


def battle(job: tuple) -> dict:
    i, p1, p2, max_turns = job[:4]
    off = job[4] if len(job) > 4 else 0  # the seeds' offset (a new set of battles)
    try:
        k = i + off
        steps, err = ec.random_battle(p1, p2, f"gen5,{k},{k + 1},{k + 2},{k + 3}", k + 1,
                                      max_turns=max_turns)  # fmt: skip
    except Exception as e:  # noqa: BLE001
        out = step_diffs([], None, i)
        out["errors"].append(f"runner: {str(e)[:200]}")
        return out
    return step_diffs(steps, err, i)


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
    ap.add_argument("--from-report", action="store_true",
                    help="check / update the baseline from the last run's report (--out), no new "
                    "battles: after a run with the same arguments")  # fmt: skip
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--seed-offset", type=int, default=0,
                    help="another set of battles: the simulator / choice seeds shifted (0: the "
                    "baseline's)")  # fmt: skip
    ap.add_argument("--out", default="data/selfplay/diag/engine_random.json")
    a = ap.parse_args()
    text = Path(a.teams).read_text(encoding="utf-8")
    pairs = [json.loads(x) for x in text.splitlines()]
    jobs = [(i, pairs[i % len(pairs)]["p1"], pairs[i % len(pairs)]["p2"], a.max_turns,
             a.seed_offset) for i in range(a.battles)]  # fmt: skip
    setup = {"battles": a.battles, "max_turns": a.max_turns,
             "teams": hashlib.sha256(text.encode()).hexdigest()[:16]}  # fmt: skip
    if a.seed_offset:
        setup["seed_offset"] = a.seed_offset
    if a.from_report:
        rep = json.loads(Path(a.out).read_text(encoding="utf-8"))
        if {k: rep.get(k) for k in setup} != setup:
            print(f"the report {a.out} is of another setup: not used")
            sys.exit(1)
        sys.exit(check_baseline(a, setup, rep["mismatches"]))
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
    Path(a.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    sys.exit(check_baseline(a, setup, mismatches))


def check_baseline(a, setup: dict, mismatches: dict) -> int:
    """The no-regression check: every (position, kind) must be in the baseline."""
    now = pairs_of(mismatches)
    path = Path(a.baseline)
    if path.exists():
        base = json.loads(path.read_text(encoding="utf-8"))
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
        path.write_text(
            json.dumps({"setup": setup, "mismatches": ids}, indent=0) + "\n", encoding="utf-8"
        )
        print(f"baseline updated: {len(now)} (position, kind)")
    return 1 if new else 0


if __name__ == "__main__":
    main()
