"""Value labels from policy-only games (2026-10-11; AlphaGo trained its value network on games of
its policy network, without search): are they good enough to be bought in quantity?

  1. 50,000 policy-only games (gen <src>: --policy-only, the generator of gen <gen>'s searched
     games, sp-gen<gen-1>; the same team distribution); converted (value labels, no policy
     targets)
  2. two trainings with sp-gen<gen>'s recipe and start (sp-gen<gen-1>), only the self-play data
     differing: S = gen <gen>'s searched games, P = the policy-only games
  3. pv_bench scores of both (outcome BCE / ECE on held-out positions neither saw, value-only
     decision regret); the human validation BCE is in the training logs

Resumable (games, conversion, runs and scores are skipped when done). Waits for --wait.

  uv run python scripts/exp_value_source.py --gen 5 --src 90
"""

import argparse
import sys
import time
from pathlib import Path

from exp_capacity import args_of, run, say, train


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="the searched games: gen <gen>")
    ap.add_argument("--src", type=int, default=90, help="the policy-only games' generation dir")
    ap.add_argument("--games", type=int, default=50_000)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--lanes", type=int, default=48)
    ap.add_argument("--wait", default="DONE iters", help="a line in policy_vs_search.log")
    a = ap.parse_args()
    py = sys.executable
    log = Path("data/selfplay/diag/policy_vs_search.log")
    while a.wait and not (log.exists() and a.wait in log.read_text()):
        time.sleep(60)
    gen_dir = Path(f"data/selfplay/gen{a.src}")
    generator = f"data/train/v5/runs/sp-gen{a.gen - 1}"
    say(f"value sources: {a.games} policy-only games of {generator} -> gen {a.src}")
    if not (gen_dir / "teams.jsonl").exists():
        run([py, "scripts/selfplay.py", "teams", "--gen", str(a.src), "--n", str(a.games)],
            "data/selfplay/diag/value_source_teams.log")  # fmt: skip
    run([py, "scripts/selfplay.py", "run", "--gen", str(a.src), "--policy-only", "--model",
         generator, "--procs", str(a.procs), "--lanes", str(a.lanes)],
        "data/selfplay/diag/value_source_run.log")  # fmt: skip
    if not Path(f"data/train/sp{a.src}/convert.json").exists():
        run([py, "scripts/selfplay.py", "convert", "--gen", str(a.src)],
            "data/selfplay/diag/value_source_convert.log")  # fmt: skip
    base = args_of(f"sp-gen{a.gen}")
    names = []
    for tag, data in (("S", f"sp{a.gen}"), ("P", f"sp{a.src}")):
        name = f"exp-VS-{tag}-gen{a.gen}"
        train(base | {"run": name, "selfplay": data}, f"data/selfplay/diag/{name}.log")
        names.append(name)
    run([py, "scripts/pv_bench.py", "score", "--nets", ",".join(names)], "data/eval/pv_bench.log")
    say("value sources done")


if __name__ == "__main__":
    main()
