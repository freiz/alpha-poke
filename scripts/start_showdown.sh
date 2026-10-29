#!/usr/bin/env bash
# Start a local Pokémon Showdown server (no auth) for training/testing.
#   scripts/start_showdown.sh [port]    # default 8000
#   scripts/start_showdown.sh --setup   # only clone and build (the tests need the built simulator)
# Clones into ./vendor/pokemon-showdown (git-ignored) on first run, at the commit the engine's
# differential tests were run against (SHOWDOWN_COMMIT; newer commits may change mechanics).
set -euo pipefail

cd "$(dirname "$0")/.."
DIR=vendor/pokemon-showdown
SHOWDOWN_COMMIT="${SHOWDOWN_COMMIT:-9fb3a5b99f1a0bea17f495c5cc1bfe04fdd19c3e}"  # 2026-10-03

if [ ! -d "$DIR" ]; then
  mkdir -p vendor
  git clone https://github.com/smogon/pokemon-showdown.git "$DIR"
  (cd "$DIR" && git checkout -q "$SHOWDOWN_COMMIT" && npm install)
  cp "$DIR/config/config-example.js" "$DIR/config/config.js"
fi

if [ "${1:-}" = "--setup" ]; then
  (cd "$DIR" && node build)
  exit 0
fi

cd "$DIR"
node pokemon-showdown start --no-security "${1:-8000}"
