"""The review app (alpha_poke.coach.app): http://127.0.0.1:<port>/ -- paste a replay link or pick
a saved replay, choose your player, get the review page (Showdown's replay player from a local
cache, coach.server); the reviews so far at /coach/<review>/viewer.html. (The Windows package
starts the same app: coach.launcher.)

  uv run python scripts/review_server.py              # fetches missing client files once
  uv run python scripts/review_server.py --offline    # never fetches (the cache only)
  uv run python scripts/review_server.py --refresh    # fetches every file anew (a client update)

Loopback only. The first page view fills data/coach/client/ (Showdown's scripts, styles, data,
the sprites it shows); later views need no internet.
"""

import argparse
import sys

from alpha_poke import paths
from alpha_poke.coach import app


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--offline", action="store_true", help="serve the cache only")
    ap.add_argument("--refresh", action="store_true", help="fetch every client file anew")
    a = ap.parse_args()
    httpd = app.make(a.port, a.offline, a.refresh)
    print(f"the app: http://127.0.0.1:{a.port}/")
    for page in sorted((paths.DATA / "coach").glob("*/viewer.html")):
        print(f"http://127.0.0.1:{a.port}/coach/{page.parent.name}/viewer.html")
    print(
        f"serving on 127.0.0.1:{a.port} ({'offline' if a.offline else 'cache, fetch once'}); Ctrl-C stops"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
