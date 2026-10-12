"""Value labels from policy-only games (2026-10-11; AlphaGo trained its value network on games of
its policy network, without search): are they good enough to be bought in quantity?

  1. 50,000 policy-only games (gen <src>: --policy-only, the generator of gen <gen>'s searched
     games, sp-gen<gen-1>; the same team distribution); converted (value labels, no policy
     targets)
  2. two trainings with sp-gen<gen>'s recipe and start (sp-gen<gen-1>), only the self-play data
     differing: S = gen <gen>'s searched games, P = the policy-only games
  3. the value head alone on sp-gen<gen>'s frozen trunk (train_pv --freeze-trunk; the policy
     untouched): A = a 2-layer MLP (value_hidden 256), B = A + one value block on the trunk's
     tokens; A on either data, B on the policy-only games
  4. pv_bench scores of all (outcome BCE / ECE on held-out positions none saw, value-only
     decision regret); the human validation BCE is in the training logs; the best head-only
     variant vs sp-gen<gen> at 1,600 iterations (--pairs)

Resumable (games, conversion, runs and scores are skipped when done). Waits for --wait.

  uv run python scripts/exp_value_source.py --gen 5 --src 90
"""

import argparse
import sys
import time
from pathlib import Path

from exp_capacity import RUNS, args_of, match, run, say, train


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="the searched games: gen <gen>")
    ap.add_argument("--src", type=int, default=90, help="the policy-only games' generation dir")
    ap.add_argument("--games", type=int, default=50_000)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--lanes", type=int, default=48)
    ap.add_argument("--wait", default="DONE iters", help="a line in policy_vs_search.log")
    ap.add_argument("--pairs", type=int, default=400)
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
    head = {"init": str(RUNS / f"sp-gen{a.gen}"), "freeze_trunk": True, "value_hidden": 256,
            "value_layers": 2}  # fmt: skip
    heads = []
    for tag, data, extra in (("A-S", f"sp{a.gen}", {}), ("A-P", f"sp{a.src}", {}),
                             ("B-P", f"sp{a.src}", {"value_blocks": 1})):  # fmt: skip
        name = f"exp-VH-{tag}-gen{a.gen}"
        train(base | head | extra | {"run": name, "selfplay": data},
              f"data/selfplay/diag/{name}.log")  # fmt: skip
        heads.append(name)
    run([py, "scripts/pv_bench.py", "score", "--nets", ",".join(names + heads)],
        "data/eval/pv_bench.log")  # fmt: skip
    best = min(heads, key=lambda n: bench_regret(n))
    say(f"value sources: the best head-only variant by value-only regret: {best}")
    match(f"VH_vs_gen{a.gen}", best, f"sp-gen{a.gen}", a.pairs, 1600, 1600,
          "data/teams/pools/wide1000")  # fmt: skip
    say("value sources done")


def bench_regret(net: str) -> float:
    """pv_bench's value-only decision regret of ``net`` (self-play and human test sets)."""
    import json

    s = json.loads(Path("data/eval/pv_bench/score.json").read_text())[net]
    return sum(s[k]["value_only"]["regret"] for k in ("selfplay/test", "human/test"))


if __name__ == "__main__":
    main()
