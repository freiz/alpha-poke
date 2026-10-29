#!/bin/bash
# The large random differential (doc/engine-diff.md L227 / L228): thirty sets of 2900 Showdown
# random-battle pairs, about three million compared turns, each against its own no-regression
# baseline (BIG_SETS="10 11 ..." picks some). The teams
# come from scripts/randbats_teams.py with fixed seeds (the same pairs every run); they are made
# under data/derived/teams/big/ when missing, not committed (some 7 MB a set). Extra arguments go to each
# run (--update-baseline; --from-report: from the last run's reports, no new battles).
#   scripts/check_engine_random_big.sh [--update-baseline [--from-report]]
cd "$(dirname "$0")/.." || exit 1
status=0
mkdir -p data/derived/teams/big
for k in ${BIG_SETS:-$(seq 0 29)}; do
  teams=data/derived/teams/big/random_battle_teams_big$k.jsonl
  if [ ! -s "$teams" ]; then
    systemd-run --user --scope -q -p MemoryMax=4G uv run python scripts/randbats_teams.py \
      --pairs 2900 --seed $((3000000 + 100000 * k)) --out "$teams" > /dev/null || status=1
  fi
  log=data/selfplay/diag/engine_random_big$k.log
  systemd-run --user --scope -q -p MemoryMax=24G uv run python scripts/check_engine_random.py \
    --procs 16 --battles 2900 --seed-offset $((1000000 + 10000 * k)) --teams "$teams" \
    --out "data/selfplay/diag/engine_random_big$k.json" \
    --baseline "tests/fixtures/engine_random_baseline_big$k.json" "$@" > "$log" 2>&1 || status=1
  echo "== big$k"; grep -E "compared|baseline|NEW|error x" "$log" | cut -c1-300
done
exit $status
