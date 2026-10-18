#!/bin/bash
# The random differential on all its sets (doc/engine-diff.md, method 0), each against its own
# no-regression baseline: the main set and eighteen validation sets (other seeds, other team pools:
# a fix must not only fit the main set). Extra arguments go to each run (--update-baseline;
# --from-report: from the last run's reports, no new battles).
#   scripts/check_engine_random_sets.sh [--update-baseline [--from-report]]
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
run wide2 --battles 300 --seed-offset 30000 --teams tests/fixtures/random_battle_teams_wide2.jsonl "${@}"
run wide200 --battles 200 --seed-offset 40000 --teams tests/fixtures/random_battle_teams_wide200.jsonl "${@}"
run forum --battles 200 --seed-offset 50000 --teams tests/fixtures/random_battle_teams_forum.jsonl "${@}"
# (Showdown's random-battle teams, scripts/randbats_teams.py: species / moves / items the pools lack)
run randbats --battles 300 --seed-offset 60000 --teams tests/fixtures/random_battle_teams_randbats.jsonl "${@}"
run randbats2 --battles 300 --seed-offset 70000 --teams tests/fixtures/random_battle_teams_randbats2.jsonl "${@}"
run randbats3 --battles 300 --seed-offset 80000 --teams tests/fixtures/random_battle_teams_randbats3.jsonl "${@}"
run randbats4 --battles 300 --seed-offset 90000 --teams tests/fixtures/random_battle_teams_randbats4.jsonl "${@}"
run randbats5 --battles 300 --seed-offset 100000 --teams tests/fixtures/random_battle_teams_randbats5.jsonl "${@}"
run randbats6 --battles 300 --seed-offset 110000 --teams tests/fixtures/random_battle_teams_randbats6.jsonl "${@}"
run randbats7 --battles 300 --seed-offset 120000 --teams tests/fixtures/random_battle_teams_randbats7.jsonl "${@}"
run randbats8 --battles 300 --seed-offset 130000 --teams tests/fixtures/random_battle_teams_randbats8.jsonl "${@}"
run randbats9 --battles 300 --seed-offset 140000 --teams tests/fixtures/random_battle_teams_randbats9.jsonl "${@}"
run randbats10 --battles 300 --seed-offset 150000 --teams tests/fixtures/random_battle_teams_randbats10.jsonl "${@}"
run randbats11 --battles 300 --seed-offset 160000 --teams tests/fixtures/random_battle_teams_randbats11.jsonl "${@}"
run randbats12 --battles 300 --seed-offset 170000 --teams tests/fixtures/random_battle_teams_randbats12.jsonl "${@}"
run randbats13 --battles 300 --seed-offset 180000 --teams tests/fixtures/random_battle_teams_randbats13.jsonl "${@}"
run randbats14 --battles 300 --seed-offset 190000 --teams tests/fixtures/random_battle_teams_randbats14.jsonl "${@}"
run randbats15 --battles 300 --seed-offset 200000 --teams tests/fixtures/random_battle_teams_randbats15.jsonl "${@}"
run randbats16 --battles 300 --seed-offset 210000 --teams tests/fixtures/random_battle_teams_randbats16.jsonl "${@}"
run randbats17 --battles 300 --seed-offset 220000 --teams tests/fixtures/random_battle_teams_randbats17.jsonl "${@}"
run randbats18 --battles 300 --seed-offset 230000 --teams tests/fixtures/random_battle_teams_randbats18.jsonl "${@}"
run randbats19 --battles 300 --seed-offset 240000 --teams tests/fixtures/random_battle_teams_randbats19.jsonl "${@}"
run randbats20 --battles 300 --seed-offset 250000 --teams tests/fixtures/random_battle_teams_randbats20.jsonl "${@}"
run randbats21 --battles 300 --seed-offset 260000 --teams tests/fixtures/random_battle_teams_randbats21.jsonl "${@}"
run randbats22 --battles 300 --seed-offset 270000 --teams tests/fixtures/random_battle_teams_randbats22.jsonl "${@}"
run randbats23 --battles 300 --seed-offset 280000 --teams tests/fixtures/random_battle_teams_randbats23.jsonl "${@}"
run randbats24 --battles 300 --seed-offset 290000 --teams tests/fixtures/random_battle_teams_randbats24.jsonl "${@}"
run randbats25 --battles 300 --seed-offset 300000 --teams tests/fixtures/random_battle_teams_randbats25.jsonl "${@}"
run randbats26 --battles 300 --seed-offset 310000 --teams tests/fixtures/random_battle_teams_randbats26.jsonl "${@}"
run randbats27 --battles 300 --seed-offset 320000 --teams tests/fixtures/random_battle_teams_randbats27.jsonl "${@}"
run randbats28 --battles 300 --seed-offset 330000 --teams tests/fixtures/random_battle_teams_randbats28.jsonl "${@}"
run randbats29 --battles 300 --seed-offset 340000 --teams tests/fixtures/random_battle_teams_randbats29.jsonl "${@}"
run randbats30 --battles 300 --seed-offset 350000 --teams tests/fixtures/random_battle_teams_randbats30.jsonl "${@}"
run randbats31 --battles 300 --seed-offset 360000 --teams tests/fixtures/random_battle_teams_randbats31.jsonl "${@}"
run randbats32 --battles 300 --seed-offset 370000 --teams tests/fixtures/random_battle_teams_randbats32.jsonl "${@}"
run randbats33 --battles 300 --seed-offset 380000 --teams tests/fixtures/random_battle_teams_randbats33.jsonl "${@}"
exit $status
