"""Download Smogon usage statistics for one format (default gen9ou) into data/smogon/.

Usage: uv run python scripts/fetch_smogon_stats.py [--format gen9ou] [--months 3] [--interval 2]
"""

import argparse

from alpha_poke.data.smogon_stats import SmogonStatsClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--months", type=int, default=3, help="how many most recent months")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between requests")
    a = ap.parse_args()

    c = SmogonStatsClient(min_interval=a.interval)
    months = c.months()
    print("latest months on server:", months[-6:])
    for m in months[-a.months :]:
        paths = c.fetch_month(m, a.format)
        print(f"{m}: {len(paths)} files in data/smogon/{m}/")
    print(f"{c.http.requests_made} requests made")


if __name__ == "__main__":
    main()
