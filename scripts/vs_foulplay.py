"""Paired evaluation of one of our bots against Foul Play (see alpha_poke.eval.external).

Usage:
  uv run python scripts/vs_foulplay.py s_ismcts_glu --pairs 10 --lanes 2 --search-ms 1000 \\
      --parallelism 4 --trace --replays

Requires: scripts/setup_foul_play.py install / patch / cache. Local servers only.
CPU budget: lanes x parallelism should not exceed the number of cores (Foul Play's search is
time-based, so CPU contention weakens it).
"""

import argparse
import json

from alpha_poke.eval.bots import BOT_NAMES
from alpha_poke.eval.external import run_vs_foulplay
from alpha_poke.teams import DEFAULT_POOL

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bot", choices=BOT_NAMES)
    ap.add_argument("--pairs", type=int, default=10)
    ap.add_argument("--pool", default=str(DEFAULT_POOL))
    ap.add_argument("--ports", type=int, nargs="+", default=[8000, 8001])
    ap.add_argument("--lanes", type=int, default=2)
    ap.add_argument("--search-ms", type=int, default=1000)
    ap.add_argument("--parallelism", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--replays", action="store_true")
    ap.add_argument("--heldout", action="store_true", help="belief model without the pool's teams")
    a = ap.parse_args()
    res = run_vs_foulplay(
        a.bot,
        a.pairs,
        a.pool,
        tuple(a.ports),
        a.lanes,
        a.search_ms,
        a.parallelism,
        a.seed,
        a.trace,
        a.replays,
        heldout=a.heldout,
    )
    print(
        f"{a.bot} vs foulplay({a.search_ms}ms x{a.parallelism}): {res['a_wins']}W "
        f"{res['ties']}T / {res['games']} = {res['win_rate']:.1%}  paired "
        f"{res['paired_mean']:.1%} ± {res['ci95_paired']:.1%}; failed {res['failed_games']}; "
        f"team mismatches {res['team_mismatches']}; {res['seconds']}s"
    )
    print(json.dumps({"log": res["log"], "opponent_logs": res["opponent_logs"]}))
