"""Team pairs from Showdown's random-battle generator (gen9randombattle) for the random engine
differential (doc/engine-diff.md, method 0): a validation set of random teams -- species, moves,
items and abilities the curated pools leave out. Fixed seeds: the same pairs every run.

  uv run python scripts/randbats_teams.py --pairs 300 --out tests/fixtures/random_battle_teams_randbats.jsonl
"""

import argparse
import json
import subprocess
from pathlib import Path

from alpha_poke import enginecheck as ec

JS = """
const {Teams} = require(process.argv[1]);
const [n, seed] = [+process.argv[2], +process.argv[3]];
const team = s => Teams.export(Teams.generate('gen9randombattle', {seed: [s, s + 1, s + 2, s + 3]}));
const out = [];
for (let i = 0; i < n; i++) {
  const s = seed + 8 * i;
  out.push(JSON.stringify({p1: team(s), p2: team(s + 4)}));
}
console.log(out.join('\\n'));
"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=70000)
    ap.add_argument("--out", default="tests/fixtures/random_battle_teams_randbats.jsonl")
    a = ap.parse_args()
    r = subprocess.run(["node", "-e", JS, str(ec.SIM), str(a.pairs), str(a.seed)],
                       capture_output=True, text=True, check=True)  # fmt: skip
    lines = r.stdout.strip().splitlines()
    assert len(lines) == a.pairs and all(json.loads(x)["p1"] for x in lines)
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} pairs -> {a.out}")
