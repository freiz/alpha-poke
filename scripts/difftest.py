"""The differential tests (doc/difftest.md): checks over a corpus of recorded battles, compared
with the corpus' baseline (tests/fixtures/difftest/<corpus>.json).

  uv run python scripts/difftest.py --corpus fast                  # pytest's tier
  uv run python scripts/difftest.py --corpus full --procs 14        # before a commit
  uv run python scripts/difftest.py --corpus fast --update-baseline # fewer findings: tighten it
  uv run python scripts/difftest.py --corpus scenarios --checks engine_chain --show 3

Exit status 1 on a regression (a kind new to the baseline, or more often; a skip reason more
often; fewer comparisons). --update-baseline writes the run's counts only when nothing grew
(--force: a deliberate change, e.g. a check that sees more now) and only from the whole corpus
(not --only); refused, the status is 1 too."""

import argparse
import json
import sys
from pathlib import Path

from alpha_poke.enginecheck import difftest as dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="fast")
    ap.add_argument("--checks", default=",".join(dt.CHECKS))
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--only", default="", help="specs whose id contains this")
    ap.add_argument("--show", type=int, default=2, help="examples per kind printed")
    ap.add_argument("--out", default="data/selfplay/diag/difftest.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    specs = [s for s in dt.corpus(a.corpus) if a.only in s.id]
    checks = [c for c in a.checks.split(",") if c]
    res = dt.run(specs, checks, a.procs)
    for c, o in res.items():
        print(f"{c}: {o['specs']} battles, {o['n']} compared, {sum(o['kinds'].values())} findings")
        for k, n in o["kinds"].items():
            print(f"  {n:6d}  {k}")
            for sid, x in o["examples"].get(k, [])[: a.show]:
                print(f"            {sid}: {json.dumps(x)[:200]}")
        for k, n in o.get("skipped", {}).items():
            print(f"  {n:6d}  (skipped: {k})")
        for sid, e in o["errors"][: a.show]:
            print(f"    error {sid}: {e[:200]}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, default=str))
    bp = dt.baseline_path(a.corpus)
    base = json.loads(bp.read_text()) if bp.exists() else {}
    grown = dt.regressions(res, base)
    for g in grown:
        print("REGRESSION", g)
    if a.update_baseline:
        new, why = dt.updated_baseline(base, res, checks, a.only, a.force)
        if new is None:  # (2026-10-25 review: a refused update exited 0)
            print("baseline NOT written:", why)
            return 1
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_text(json.dumps(new, indent=1, sort_keys=True) + "\n")
        print("baseline written:", bp)
        return 0
    return 1 if grown else 0


if __name__ == "__main__":
    sys.exit(main())
