"""Rerun the example battles of state-construction differential reports with the current code
(doc/state-diff.md: the triage loop). Each report (scripts/check_state_build.py --out) keeps up
to 20 examples per kind; this reruns every battle they name -- its team pair is
pairs[seed - seed_offset], as check_state_build takes it -- and prints the kinds left, by battle
count. --list KIND: also each battle of that kind with its first decision.

  uv run python scripts/rerun_state_build.py data/selfplay/diag/sb_p_ou.json data/selfplay/diag/sb_p_fix.json
  uv run python scripts/rerun_state_build.py --path replay data/selfplay/diag/rb_b_*.json --list own:pp
"""

import argparse
import collections
import glob
import json
import multiprocessing as mp
from pathlib import Path


def _one(job):
    f, seed, offset, path = job
    pairs = [json.loads(x) for x in Path(f).read_text().splitlines()]
    p = pairs[(seed - offset) % len(pairs)]
    try:
        if path == "replay":
            from alpha_poke.enginecheck.replaybuild import battle_diffs

            diffs, stats = battle_diffs(p["p1"], p["p2"], seed=seed, max_turns=40)
        else:
            from alpha_poke.enginecheck.statebuild import battle_diffs

            diffs, stats = battle_diffs(p["p1"], p["p2"], seed=seed, max_turns=40, oracle=True)
    except Exception as e:  # noqa: BLE001
        return job, [], [f"{type(e).__name__}: {e}"[:200]]
    return job, diffs, stats["errors"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", help="check_state_build reports (globs too)")
    ap.add_argument("--path", choices=("live", "replay"), default=None,
                    help="default: each report's own (its 'path', else live)")
    ap.add_argument("--list", default="", help="a kind: each of its battles with its first decision")
    ap.add_argument("--procs", type=int, default=8)
    a = ap.parse_args()
    jobs = set()
    for r in sorted({f for x in a.reports for f in (glob.glob(x) or [x])}):
        rep = json.loads(Path(r).read_text())
        files = {Path(f).stem: f for f in rep["teams"]}
        path = a.path or rep.get("path", "live")
        for kind, ex in rep["examples"].items():
            if kind != "error":
                jobs |= {(files[stem], seed, rep.get("seed_offset", 0), path) for (stem, seed), *_ in ex}
    now: collections.Counter = collections.Counter()
    battles: dict = collections.defaultdict(set)
    first: dict = {}
    with mp.get_context("spawn").Pool(a.procs) as pool:
        for job, diffs, errors in pool.imap_unordered(_one, sorted(jobs)):
            if errors:
                print("error", Path(job[0]).stem, job[1], errors[:2])
            for k, side, kind, detail in diffs:
                now[kind] += 1
                battles[kind].add(job)
                first.setdefault((kind, job), (k, side, detail))
    print(f"{len(jobs)} battles rerun")
    for kind, c in now.most_common():
        job = min(battles[kind])
        print(f"{c:6d}  {kind:36s} in {len(battles[kind])} battles, e.g. {Path(job[0]).stem} {job[1]} "
              f"{first[(kind, job)]}"[:220])  # fmt: skip
    for job in sorted(battles.get(a.list, ())):
        print("  ", job[0], job[1], "offset", job[2], *first[(a.list, job)])


if __name__ == "__main__":
    main()
