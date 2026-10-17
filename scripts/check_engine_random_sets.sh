#!/bin/bash
# The random differential on all its sets (doc/engine-diff.md, method 0), each against its own
# no-regression baseline: the main set and four validation sets (other seeds, other team pools:
# a fix must not only fit the main set). Extra arguments go to each run (--update-baseline).
#   scripts/check_engine_random_sets.sh [--update-baseline]
cd "$(dirname "$0")/.." || exit 1
status=0
run() {  # name, arguments
  name=$1; shift
  log=data/selfplay/diag/engine_random${name:+_$name}.log
  systemd-run --user --scope -q -p MemoryMax=12G uv run python scripts/check_engine_random.py \
    --procs 8 --out "data/selfplay/diag/engine_random${name:+_$name}.json" \
    --baseline "tests/fixtures/engine_random_baseline${name:+_$name}.json" "$@" > "$log" 2>&1 || status=1
  echo "== ${name:-main}"; grep -E "compared|baseline|NEW" "$log" | cut -c1-300
}
run "" --battles 300 "${@}"
run seed10k --battles 300 --seed-offset 10000 "${@}"
run offmeta --battles 200 --teams tests/fixtures/random_battle_teams_offmeta.jsonl "${@}"
run random --battles 200 --teams tests/fixtures/random_battle_teams_random.jsonl "${@}"
run wide --battles 300 --teams tests/fixtures/random_battle_teams_wide.jsonl "${@}"
exit $status
