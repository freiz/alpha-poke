"""Polite, resumable Showdown replay crawler (see alpha_poke.replay.crawl).

Typical session (everything is resumable; Ctrl-C / SIGTERM stops cleanly):

  uv run python scripts/crawl_replays.py seed-users                 # top-500 ladder users
  uv run python scripts/crawl_replays.py crawl-users                # their latest 25 replays each
  uv run python scripts/crawl_replays.py list --pages 2000          # global listing, back in time
  uv run python scripts/crawl_replays.py download --target 50000 --min-rating 1500
  uv run python scripts/crawl_replays.py status

Later, to keep the dataset fresh:
  uv run python scripts/crawl_replays.py list --mode new --pages 200
  uv run python scripts/crawl_replays.py download --target 60000 --min-rating 1500

Global flags: --interval (seconds between requests, default 2.0), --max-requests, --max-hours.
"""

import argparse
import time

from alpha_poke.http import CrawlAbort
from alpha_poke.replay.crawl import Budget, ReplayCrawler, log


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--max-requests", type=int, default=None)
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--root", default=None, help="data directory (default: data/replays)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed-users")
    s.add_argument("--top", type=int, default=500)

    s = sub.add_parser("crawl-users")
    s.add_argument("--max-users", type=int, default=None)

    s = sub.add_parser("expand-users", help="add opponents from high-rated replays as users")
    s.add_argument("--min-rating", type=int, default=1700)
    s.add_argument("--limit", type=int, default=200)

    s = sub.add_parser("list")
    s.add_argument("--mode", choices=["back", "new"], default="back")
    s.add_argument("--pages", type=int, default=100)
    s.add_argument("--since-days", type=float, default=None, help="stop when older than this")

    s = sub.add_parser("download")
    s.add_argument("--target", type=int, required=True, help="total replays on disk to reach")
    s.add_argument("--min-rating", type=int, default=None)
    s.add_argument("--since-days", type=float, default=None)
    s.add_argument("--order", choices=["recent", "rating"], default="recent")

    sub.add_parser("status")
    a = ap.parse_args()

    budget = Budget(
        max_requests=a.max_requests,
        max_seconds=a.max_hours * 3600 if a.max_hours else None,
    )
    budget.install_signal_handlers()
    kw = {"root": a.root} if a.root else {}
    c = ReplayCrawler(format_id=a.format, min_interval=a.interval, budget=budget, **kw)

    def since(days):
        return int(time.time() - days * 86400) if days else None

    try:
        if a.cmd == "seed-users":
            c.seed_top_users(a.top)
        elif a.cmd == "crawl-users":
            c.crawl_users(a.max_users)
        elif a.cmd == "expand-users":
            c.expand_users_from_replays(a.min_rating, a.limit)
        elif a.cmd == "list":
            c.walk_listing(a.mode, a.pages, since(a.since_days))
        elif a.cmd == "download":
            c.download(a.target, a.min_rating, since(a.since_days), a.order)
        print(c.status())
    except CrawlAbort as e:
        log(f"ABORTED: {e}")
        print(c.status())
        raise SystemExit(2) from e
    finally:
        log(f"{c.client.http.requests_made} HTTP requests this run")


if __name__ == "__main__":
    main()
