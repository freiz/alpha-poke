#!/bin/bash
# The state-construction differential at a million decisions (doc/state-diff.md): 8,000 OU
# battles of the catalog's 10,000 pairs, 100 of each of the 40 fixture sets, 80 of each of the 30
# big sets (~1.09M decisions, ~1 hour on 14 processes, memory capped). New seeds for each run.
#
#   scripts/state_build_sweep.sh live 70000 4000 p     -> data/selfplay/diag/sb_p_{ou,fix,big}.{json,txt}
#   scripts/state_build_sweep.sh replay 80000 5000 b   -> data/selfplay/diag/rb_b_{ou,fix,big}.{json,txt}
#
# (data/derived/teams/ is local: statebuild_catalog_pairs10k.jsonl and big/ are not committed)
set -e
path=${1:?live or replay} ou_offset=${2:?OU seed offset} small_offset=${3:?fixture / big seed offset} tag=${4:?tag}
cd "$(dirname "$0")/.."
prefix=$([ "$path" = replay ] && echo rb || echo sb)
D=data/selfplay/diag
R="systemd-run --user --scope -q -p MemoryMax=30G .venv/bin/python scripts/check_state_build.py --path $path --procs 14"
$R --battles 8000 --seed-offset "$ou_offset" --teams data/derived/teams/statebuild_catalog_pairs10k.jsonl \
    --out $D/${prefix}_${tag}_ou.json > $D/${prefix}_${tag}_ou.txt 2>&1
$R --battles 100 --seed-offset "$small_offset" --teams "tests/fixtures/random_battle_teams*.jsonl" \
    --out $D/${prefix}_${tag}_fix.json > $D/${prefix}_${tag}_fix.txt 2>&1
$R --battles 80 --seed-offset "$small_offset" --teams "data/derived/teams/big/*.jsonl" \
    --out $D/${prefix}_${tag}_big.json > $D/${prefix}_${tag}_big.txt 2>&1
head -1 $D/${prefix}_${tag}_ou.txt $D/${prefix}_${tag}_fix.txt $D/${prefix}_${tag}_big.txt
