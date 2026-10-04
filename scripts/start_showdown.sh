#!/usr/bin/env bash
# Start a local Pokémon Showdown server (no auth) for training/testing.
# Clones into ./vendor/pokemon-showdown (git-ignored) on first run.
set -euo pipefail

cd "$(dirname "$0")/.."
DIR=vendor/pokemon-showdown
PORT="${1:-8000}"

if [ ! -d "$DIR" ]; then
  mkdir -p vendor
  git clone --depth 1 https://github.com/smogon/pokemon-showdown.git "$DIR"
  (cd "$DIR" && npm install)
  cp "$DIR/config/config-example.js" "$DIR/config/config.js"
fi

cd "$DIR"
node pokemon-showdown start --no-security "$PORT"
