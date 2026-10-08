"""Self-play pipeline (design D15). Local servers only.

  teams  --gen G --n N   team pairs for generation G -> data/selfplay/gen<G>/teams.jsonl
                         (real games completed by the belief at a temperature + complete
                         catalog teams, validated; selfplay.teams)

Usage: uv run python scripts/selfplay.py teams --gen 0 --n 2000
"""

import argparse
import collections
import logging

from alpha_poke.selfplay import SELFPLAY_DIR

SINCE_DEFAULT = 1746057600  # 2025-05-01: the current metagame (the matchup model's window too)


def cmd_teams(a) -> None:
    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay import teams

    logging.disable(logging.WARNING)
    ts = teams.TeamSampler(BeliefModel.load(), since=a.since, half_life_days=a.half_life,
                           catalog_frac=a.catalog_frac, temp=a.temp, seed=a.seed)  # fmt: skip
    pairs = ts.sample(a.n)
    path = SELFPLAY_DIR / f"gen{a.gen}" / "teams.jsonl"
    teams.save(pairs, path)
    kinds = collections.Counter(s.kind for p in pairs for s in (p.p1, p.p2))
    print(f"{len(pairs)} pairs -> {path}; sides {dict(kinds)}; bans learned {ts.banned_moves}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("teams")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--since", type=int, default=SINCE_DEFAULT, help="real games from (unix time)")
    p.add_argument("--half-life", type=float, default=120.0, help="recency weight, days")
    p.add_argument("--catalog-frac", type=float, default=0.3)
    p.add_argument("--temp", type=float, default=1.3, help="completion temperature")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_teams)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
