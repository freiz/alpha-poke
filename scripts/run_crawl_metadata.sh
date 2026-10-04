#!/usr/bin/env bash
# Phase 1 of the replay crawl: metadata only (no replay logs are downloaded here).
#   1. top-500 ladder users + their latest 25 replays each      (~520 requests)
#   2. global listing, back in time for N days (51 entries/req)  (~8000 requests for 90 days)
# Resumable: just run it again. Polite: 2 s between requests (+ jitter), aborts on 403/failures.
# Usage: scripts/run_crawl_metadata.sh [days=90]
set -euo pipefail
cd "$(dirname "$0")/.."
DAYS="${1:-90}"
run() { uv run python scripts/crawl_replays.py "$@"; }
run seed-users
run crawl-users
run list --mode back --pages 20000 --since-days "$DAYS"
run status
