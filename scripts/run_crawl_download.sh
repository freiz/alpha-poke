#!/usr/bin/env bash
# Phase 2 of the replay crawl: download full logs. Waits for the metadata phase to finish
# (only one crawler at a time, to keep the request rate low), then downloads by plan A:
#   rating >= 1300, last 90 days, highest rating first, until TARGET replays are on disk.
# Usage: scripts/run_crawl_download.sh [target=50000] [min_rating=1300] [days=90]
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:-50000}"; MINR="${2:-1300}"; DAYS="${3:-90}"
while pgrep -f "run_crawl_metadata[.]sh" > /dev/null; do sleep 60; done
uv run python scripts/crawl_replays.py status
uv run python scripts/crawl_replays.py download --target "$TARGET" \
  --min-rating "$MINR" --since-days "$DAYS" --order rating
uv run python scripts/crawl_replays.py status
