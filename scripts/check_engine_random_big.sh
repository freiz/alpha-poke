#!/bin/bash
# The large random differential (doc/engine-diff.md L227): ten sets of 2900 Showdown random-battle
# pairs, about a million compared turns, each against its own no-regression baseline. The teams
# come from scripts/randbats_teams.py with fixed seeds (the same pairs every run); they are made
# under data/teams/big/ when missing, not committed (some 7 MB a set). Extra arguments go to each
# run (--update-baseline; --from-report: from the last run's reports, no new battles).
#   scripts/check_engine_random_big.sh [--update-baseline [--from-report]]
cd "$(dirname "$0")/.." || exit 1
status=0
mkdir -p data/teams/big
for k in 0 1 2 3 4 5 6 7 8 9; do
  teams=data/teams/big/random_battle_teams_big$k.jsonl
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
