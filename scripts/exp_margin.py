"""Margin auxiliary head on self-play (design TODO "胜负幅度辅助头", 2026-10-11): A's training
(sp-gen<gen>'s own arguments) with the margin head added (--aux ...,margin: mons left at the end,
own - opponent, 13 classes, on the human and the self-play positions; a denser per-game signal
than the outcome, as KataGo's score). Tried before only on the human data, in the v3 batch with
the other auxiliary heads (no value change, results.md). pv_bench scores of both, then the
variant vs A at equal iterations. Waits for the self-play loop to stop. Resumable.

  uv run python scripts/exp_margin.py --gen 5
"""

import argparse
import subprocess
import sys
import time

from exp_capacity import args_of, match, run, say, train


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="A = sp-gen<gen>")
    ap.add_argument("--pairs", type=int, default=400)
    ap.add_argument("--iterations", type=int, default=3000)
    ap.add_argument("--pool", default="data/teams/pools/wide1000")
    a = ap.parse_args()
    py = sys.executable
    loop = ["pgrep", "-f", "[s]elfplay.py loop"]
    while subprocess.run(loop, capture_output=True).returncode == 0:  # the loop's eval first
        time.sleep(60)
    base = f"sp-gen{a.gen}"
    name = "exp-M-margin"
    args = args_of(base)
    heads = [h for h in args["aux"].split(",") if h]
    args |= {"run": name, "aux": ",".join(heads + ["margin"])}
    say(f"margin head: {name} = {base}'s training with --aux {args['aux']}")
    train(args, f"data/selfplay/diag/{name}.log")
    run([py, "scripts/pv_bench.py", "score", "--nets", f"{base},{name}"], "data/eval/pv_bench.log")
    match("M_vs_A", name, base, a.pairs, a.iterations, a.iterations, a.pool)
    say("margin head done")


if __name__ == "__main__":
    main()
