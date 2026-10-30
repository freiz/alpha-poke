"""The causality check of the search's tree (doc/state-diff.md plan B, part 2): below the root
the search extends the history with the steps of its descent (rust ismcts PathCtx: push /
settle); the network was trained on the replays' history (train/positions: the log's steps). On
the state-construction differential's random battles: at each turn start where both sides
chose, the step the tree records for the actual joint action (from Showdown's true state, each
chance outcome of it) against the step the log gives for that turn. The structural fields --
the act's kind, tera, actor, target, prevented, fainted first -- must match one outcome's; the
outcome fields (damage, first, crit, miss, KO) are counted apart: the tree does not fill them.

  uv run python scripts/check_tree_history.py --battles 200 --teams tests/fixtures/random_battle_teams.jsonl
"""

import argparse
import collections
import glob
import json
import multiprocessing as mp
from pathlib import Path

from alpha_poke.enginecheck.treediff import tree_diffs


def battle(job) -> dict:
    (stem, seed), p1, p2 = job
    return tree_diffs(p1, p2, seed, label=stem)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=100)
    ap.add_argument("--teams", default="tests/fixtures/random_battle_teams.jsonl")
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--out", default="data/selfplay/diag/tree_history.json")
    a = ap.parse_args()
    files = sorted({f for t in a.teams.split(",") for f in (glob.glob(t) or [t])})
    jobs = []
    for f in files:
        pairs = [json.loads(x) for x in Path(f).read_text(encoding="utf-8").splitlines()]
        jobs += [((Path(f).stem, a.seed_offset + i), pairs[i % len(pairs)]["p1"], pairs[i % len(pairs)]["p2"])
                 for i in range(a.battles)]  # fmt: skip
    total = 0
    struct: collections.Counter = collections.Counter()
    outcome: collections.Counter = collections.Counter()
    skipped: collections.Counter = collections.Counter()
    examples, errors = [], []
    with mp.get_context("spawn").Pool(a.procs) as pool:
        for r in pool.imap_unordered(battle, jobs):
            total += r["steps"]
            struct.update(r["struct"])
            outcome.update(r["outcome"])
            skipped.update(r["skipped"])
            examples += r["examples"]
            errors += r["errors"]
    bad = sum(1 for e in examples)
    print(
        f"{len(jobs)} battles, {total} turn steps; structural mismatches by field: {dict(struct)}"
    )
    print(f"  outcome fields the tree leaves out (log != tree): {dict(outcome)}")
    print(f"  skipped {dict(skipped)}; errors {len(errors)} {errors[:3]}")
    for e in examples[:10]:
        print("  e.g.", e)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(
        json.dumps(
            {
                "battles": len(jobs),
                "steps": total,
                "struct": dict(struct),
                "outcome": dict(outcome),
                "skipped": dict(skipped),
                "examples": examples,
                "errors": errors[:50],
                "bad": bad,
            },
            indent=1,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
