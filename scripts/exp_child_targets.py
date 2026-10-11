"""Child-node value targets, the experiment (design TODO "方案乙", 2026-10-10): generate the
targets (scripts/child_targets.py), train A's recipe (sp-gen<gen>'s own arguments) with the
child loss added (regression / sibling ranking / both; the outcome loss kept), score them on
pv_bench. Resumable (the targets' chunks, trained runs and scored networks are skipped).

  uv run python scripts/exp_child_targets.py --gen 4
"""

import argparse
import subprocess
import sys
import time

from exp_capacity import args_of, run, say, train


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="A = sp-gen<gen>, its games")
    ap.add_argument("--roots", type=int, default=100_000)
    ap.add_argument("--modes", default="both,rank,reg")
    ap.add_argument("--weight", type=float, default=1.0)
    ap.add_argument("--wait", default="exp_value_targets.py", help="a script to wait for")
    a = ap.parse_args()
    py = sys.executable
    while a.wait and subprocess.run(["pgrep", "-f", f"[{a.wait[0]}]{a.wait[1:]}"],
                                    capture_output=True).returncode == 0:  # fmt: skip
        time.sleep(60)
    base = f"sp-gen{a.gen}"
    out = f"data/train/children/gen{a.gen}"
    say(f"child targets: {a.roots} roots of gen {a.gen}")
    run([py, "scripts/child_targets.py", "--gen", str(a.gen), "--roots", str(a.roots)],
        "data/selfplay/diag/child_targets.log")  # fmt: skip
    for mode in a.modes.split(","):
        name = f"exp-child-{mode}"
        args = args_of(base) | {"run": name, "child_data": out, "child_loss": mode,
                                "child_weight": a.weight}  # fmt: skip
        train(args, f"data/selfplay/diag/{name}.log")
        run([py, "scripts/pv_bench.py", "score", "--nets", name], "data/eval/pv_bench.log")
        say(f"child targets, {mode}: trained and scored")
    say("child-target experiment done")


if __name__ == "__main__":
    main()
