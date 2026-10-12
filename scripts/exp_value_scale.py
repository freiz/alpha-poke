"""Value labels at scale (2026-10-12): 500,000 policy-only games of sp-gen<gen>, a few positions
each (AlphaGo's value-net data: many games x few positions), for the value head alone on
sp-gen<gen>'s frozen trunk. exp_value_source.py's A-P (50,000 games, all positions) found no
gain; here the same training (steps, batch, the value counted once) with 10x the games.

  1. games in --parts parts (gen <first>..: teams drawn per part, 100,000 each by default),
     sp-gen<gen>'s policy alone (selfplay.py run --policy-only); each part converted with
     --per-game 4 (only those states built) and --no-record
  2. value heads on the frozen trunk: A4 = 2-layer MLP, 4 positions per game; A1 = the same, 1
     position per game (--sp-per-game 1 at load); B4 = A + one value block, 4 per game
  3. pv_bench scores; the best (value-only regret) vs sp-gen<gen> at 1,600 iterations

Resumable (parts, conversions, runs, scores and the match are skipped when done).

  uv run python scripts/exp_value_scale.py --gen 5
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from exp_capacity import RUNS, args_of, match, run, say, train
from exp_value_source import bench_regret


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="sp-gen<gen>: games, trunk, opponent")
    ap.add_argument("--first", type=int, default=80, help="the parts' generation dirs from here")
    ap.add_argument("--parts", type=int, default=5)
    ap.add_argument("--games", type=int, default=100_000, help="per part")
    ap.add_argument("--per-game", type=int, default=4)
    ap.add_argument("--procs", type=int, default=12)
    ap.add_argument("--lanes", type=int, default=48)
    ap.add_argument("--pairs", type=int, default=400)
    a = ap.parse_args()
    py = sys.executable
    model = str(RUNS / f"sp-gen{a.gen}")
    parts = list(range(a.first, a.first + a.parts))
    for g in parts:  # the teams (drawn in parallel beforehand, or here)
        t = Path(f"data/selfplay/gen{g}/teams.jsonl")
        busy = ["pgrep", "-f", f"[s]elfplay.py teams --gen {g} "]
        while subprocess.run(busy, capture_output=True).returncode == 0:
            time.sleep(60)  # being drawn by another process
        if not t.exists():
            run([py, "scripts/selfplay.py", "teams", "--gen", str(g), "--n", str(a.games),
                 "--seed", str(100 + g - a.first)],
                f"data/selfplay/diag/teams_part{g}.log")  # fmt: skip
    for g in parts:
        say(f"value scale: part gen {g}, {a.games} policy-only games of {model}")
        run([py, "scripts/selfplay.py", "run", "--gen", str(g), "--policy-only", "--model", model,
             "--procs", str(a.procs), "--lanes", str(a.lanes)],
            f"data/selfplay/diag/value_scale_run{g}.log")  # fmt: skip
        if not Path(f"data/train/sp{g}/convert.json").exists():
            run([py, "scripts/selfplay.py", "convert", "--gen", str(g), "--per-game",
                 str(a.per_game), "--no-record"],
                f"data/selfplay/diag/value_scale_convert{g}.log")  # fmt: skip
    data = ",".join(f"sp{g}" for g in parts)
    base = args_of(f"sp-gen{a.gen}") | {"init": model, "freeze_trunk": True, "value_hidden": 256,
                                        "value_layers": 2, "selfplay": data}  # fmt: skip
    names = []
    for tag, extra in (("A4", {}), ("A1", {"sp_per_game": 1}), ("B4", {"value_blocks": 1})):
        name = f"exp-VX-{tag}-gen{a.gen}"
        train(base | extra | {"run": name}, f"data/selfplay/diag/{name}.log")
        names.append(name)
    run([py, "scripts/pv_bench.py", "score", "--nets", ",".join(names)], "data/eval/pv_bench.log")
    best = min(names, key=bench_regret)
    say(f"value scale: the best by value-only regret: {best}")
    match(f"VX_vs_gen{a.gen}", best, f"sp-gen{a.gen}", a.pairs, 1600, 1600,
          "data/teams/pools/wide1000")  # fmt: skip
    say("value scale done")


if __name__ == "__main__":
    main()
