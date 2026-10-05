"""Paired head-to-head evaluation (see alpha_poke.eval.arena). Local servers only.

Usage:
  uv run python scripts/arena.py knowledge heuristic --pairs 500
  uv run python scripts/arena.py knowledge k_nobelief --pairs 500 --heldout
  uv run python scripts/arena.py knowledge heuristic k_nobelief:heuristic --pairs 300  # several

Positional args are "A B" or "A:B" matchups. --heldout uses the belief model trained without the
pool's teams (the pool is then unknown to the belief model). Logs: data/eval/*.jsonl.
"""

import argparse
import json

from alpha_poke.eval.arena import run_arena
from alpha_poke.eval.bots import BOT_NAMES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("matchups", nargs="+", help="'A B' pair or 'A:B' items")
    ap.add_argument("--pairs", type=int, default=300, help="team pairs (2 games each)")
    ap.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--lanes", type=int, default=6, help="concurrent player pairs per process")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--heldout", action="store_true")
    ap.add_argument("--pool", default="data/teams/pool")
    ap.add_argument("--trace", action="store_true", help="per-turn decision logs (knowledge bots)")
    ap.add_argument("--replays", action="store_true", help="save Showdown HTML replays")
    a = ap.parse_args()
    items = a.matchups
    if all(":" not in x for x in items):
        assert len(items) == 2, "give 'A B' or 'A:B' items"
        items = [f"{items[0]}:{items[1]}"]
    for item in items:
        bot_a, bot_b = item.split(":")
        assert bot_a in BOT_NAMES and bot_b in BOT_NAMES, f"unknown bot in {item}: {BOT_NAMES}"
        res = run_arena(
            bot_a,
            bot_b,
            a.pairs,
            a.pool,
            tuple(a.ports),
            a.procs,
            a.lanes,
            a.seed,
            a.heldout,
            trace=a.trace,
            replays=a.replays,
        )
        tag = " [heldout belief]" if a.heldout else ""
        print(
            f"{bot_a} vs {bot_b}{tag}: {res['a_wins']}W {res['ties']}T / {res['games']} = "
            f"{res['win_rate']:.1%}  paired {res['paired_mean']:.1%} ± {res['ci95_paired']:.1%} "
            f"(naive ± {res['ci95_naive']:.1%}; {res['split_pairs']}/{res['pairs']} pairs split; "
            f"fallbacks {res['fallbacks_a']}/{res['fallbacks_b']}; failed {res['failed_games']}; "
            f"team mismatches {res['team_mismatches']}; "
            f"{res['seconds']}s)",
            flush=True,
        )
        print("  " + json.dumps({"log": res["log"]}))


if __name__ == "__main__":
    main()
