"""How the Gen 9 OU metagame moved (2026-10-28): species usage of teams by players >= --elo in the
last --recent days against the --before days before them, from the lite scan + the crawler's
newer replays; and the crawler's sampling checked against the lite scan where both cover the
same days (the crawler lists every public replay, but its seed users are the top 500).

  uv run python scripts/meta_shift.py [--recent 21 --before 30 --elo 1500]

Run after `scripts/crawl_replays.py list --mode new` + `download` (doc/team_design.md).
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_robust_teams import all_games, crawled_games  # noqa: E402

from alpha_poke.analysis.games_lite import DEST  # noqa: E402

DAY = 86400


def usage(df: pd.DataFrame, elo: int) -> tuple[pd.Series, int]:
    sides = pd.concat([df.team1[df.r1 >= elo], df.team2[df.r2 >= elo]])
    n = len(sides)
    return pd.Series([s for t in sides for s in t.split("|")]).value_counts() / max(n, 1), n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, default=21)
    ap.add_argument("--before", type=int, default=30)
    ap.add_argument("--elo", type=int, default=1500)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    g = all_games(log=print)
    now = g.time.max()
    recent = g[g.time >= now - a.recent * DAY]
    before = g[(g.time < now - a.recent * DAY) & (g.time >= now - (a.recent + a.before) * DAY)]
    ur, nr = usage(recent, a.elo)
    ub, nb = usage(before, a.elo)
    d = pd.DataFrame({"recent": ur, "before": ub}).fillna(0.0)
    d["diff"] = d.recent - d.before
    print(
        f"teams by players >= {a.elo}: last {a.recent} days {nr}, the {a.before} days before {nb}"
    )
    print((d.sort_values("recent", ascending=False).head(a.top) * 100).round(1).to_string())
    print("rising:")
    print(
        (d[d.recent > 0.03].sort_values("diff", ascending=False).head(8) * 100).round(1).to_string()
    )
    print("falling:")
    print((d[d.before > 0.03].sort_values("diff").head(8) * 100).round(1).to_string())

    # the crawler's sample against the lite scan on days both cover
    lite = pd.read_parquet(DEST, columns=["time", "r1", "r2", "team1", "team2"])
    c = crawled_games()
    lo, hi = max(lite.time.min(), c.time.min()), min(lite.time.max(), c.time.max())
    lo = max(lo, hi - 30 * DAY)
    uc, nc = usage(c[(c.time >= lo) & (c.time <= hi)], a.elo)
    ul, nl = usage(lite[(lite.time >= lo) & (lite.time <= hi)], a.elo)
    both = pd.DataFrame({"crawled": uc, "lite": ul}).fillna(0.0)
    top = both.sort_values("lite", ascending=False).head(15)
    print(f"sampling check, {pd.Timestamp(lo, unit='s').date()}..{pd.Timestamp(hi, unit='s').date()}: "
          f"crawled {nc} teams, lite {nl}; largest gap among the top 15: "
          f"{(top.crawled - top.lite).abs().max() * 100:.1f} points")  # fmt: skip


if __name__ == "__main__":
    main()
