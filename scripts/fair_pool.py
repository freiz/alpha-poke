"""Build a fair evaluation pool (alpha_poke.selfplay.fair): real games' team pairs, the revealed
parts kept, the rest from usage corrected for what would have shown.

  uv run python scripts/fair_pool.py --pairs 1000                    # fair1000
  uv run python scripts/fair_pool.py --pairs 2000 --extend fair1000   # fair2000: fair1000 first
  uv run python scripts/fair_pool.py --bank 10000                     # teambank10k (promotion's)
"""

import argparse

from alpha_poke.selfplay import fair

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=1000)
    ap.add_argument("--name", default="", help="default fair<pairs>")
    ap.add_argument("--extend", default="", help="a fair pool whose pairs come first")
    ap.add_argument("--since", type=int, default=fair.TRAINING_CUTOFF)
    ap.add_argument("--min-rating", type=int, default=1500)
    ap.add_argument("--rate-games", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=9300)
    ap.add_argument("--bank", type=int, default=0, help="a team bank of this many teams instead")
    ap.add_argument(
        "--cap", type=float, default=10.0, help="the bank: a player's composition's games"
    )
    a = ap.parse_args()
    if a.bank:
        fair.bank_build(a.name or fair.BANK, a.bank, a.cap, a.since, a.min_rating, a.rate_games,
                        a.seed + 100)  # fmt: skip
        raise SystemExit(0)
    fair.build(a.name or f"fair{a.pairs}", a.pairs, a.since, a.min_rating, a.rate_games, a.seed,
               a.extend)  # fmt: skip
