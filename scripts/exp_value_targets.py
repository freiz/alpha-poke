"""Value-target variants, screened on pv_bench (2026-10-10; design TODO "价值头实验"): A's training
(sp-gen<gen>, its own arguments) with only the self-play value target changed, then pv_bench
scores (decision metrics: does the value tell the options apart?). Resumable: trained runs and
scored networks are skipped.

  C  lambda-return targets, lambda 0.9 (outcome mixed with the next steps' root search values)
  D  lambda 0.7
  B  8 positions per game count for the value
  E  a position's outcome counts every time it is drawn (3 passes)

  uv run python scripts/exp_value_targets.py --gen 4
"""

import argparse
import sys

from exp_capacity import args_of, run, say, train

VARIANTS = {
    "C": {"sp_value_lambda": 0.9},
    "D": {"sp_value_lambda": 0.7},
    "B": {"sp_value_per_game": 8},
    "E": {"sp_value_passes": 3},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="A = sp-gen<gen>")
    ap.add_argument("--variants", default="C,D,B,E")
    a = ap.parse_args()
    base = f"sp-gen{a.gen}"
    for v in a.variants.split(","):
        name = f"exp-{v}-" + "-".join(f"{k.removeprefix('sp_value_')}{x}"
                                       for k, x in VARIANTS[v].items())  # fmt: skip
        args = args_of(base) | VARIANTS[v] | {"run": name}
        train(args, f"data/selfplay/diag/{name}.log")
        run([sys.executable, "scripts/pv_bench.py", "score", "--nets", name],
            "data/eval/pv_bench.log")  # fmt: skip
        say(f"variant {v} ({name}): trained and scored")
    say("value-target variants done")


if __name__ == "__main__":
    main()
