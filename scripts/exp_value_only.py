"""Value heads on the policy-only value positions alone (2026-10-12): exp_value_scale.py's
runs mixed them with the human data (sp_frac 0.75), counted each outcome once (--sp-value-passes
1) and selected/exported by the human loss; the gains seen early (held-out BCE 0.4392 at step
656) were gone by the end. Here the self-play value positions are the only data (--sp-frac 1),
every draw counts, best.pt by the held-out self-play value BCE (--select sp_value), evaluated
often.

  A = 2-layer MLP on the frozen trunk; B = A + one value block; BU = B + the trunk's top block
  (--unfreeze-top 1, --policy-anchor keeping the policy); pv_bench scores, the best (value-only
  regret) vs sp-gen<gen> at 1,600 iterations.

  uv run python scripts/exp_value_only.py --gen 5 --data sp80,sp81,sp82,sp83
"""

import argparse
import sys

from exp_capacity import RUNS, args_of, match, run, say, train
from exp_value_source import bench_regret


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="sp-gen<gen>: trunk, opponent")
    ap.add_argument("--data", required=True, help="the policy-only value positions (train_pv)")
    ap.add_argument("--passes", type=float, default=3.0, help="over the value positions")
    ap.add_argument("--eval-every", type=int, default=50)
    ap.add_argument("--anchor", type=float, default=1.0, help="BU's --policy-anchor")
    ap.add_argument("--pairs", type=int, default=400)
    a = ap.parse_args()
    model = str(RUNS / f"sp-gen{a.gen}")
    base = args_of(f"sp-gen{a.gen}") | {
        "init": model, "freeze_trunk": True, "value_hidden": 256, "value_layers": 2,
        "selfplay": a.data, "sp_frac": 1.0, "sp_per_game": 0, "sp_passes": a.passes, "steps": 0,
        "sp_value_passes": 0, "eval_every": a.eval_every, "select": "sp_value", "export": "best",
        "warmup_frac": 0.05}  # fmt: skip
    names = []
    for tag, extra in (("A", {}), ("B", {"value_blocks": 1}),
                       ("BU", {"value_blocks": 1, "unfreeze_top": 1,
                               "policy_anchor": a.anchor})):  # fmt: skip
        name = f"exp-VO-{tag}-gen{a.gen}"
        train(base | extra | {"run": name}, f"data/selfplay/diag/{name}.log")
        names.append(name)
    run([sys.executable, "scripts/pv_bench.py", "score", "--nets", ",".join(names)],
        "data/eval/pv_bench.log")  # fmt: skip
    best = min(names, key=bench_regret)
    say(f"value only: the best by value-only regret: {best}")
    match(f"VO_vs_gen{a.gen}", best, f"sp-gen{a.gen}", a.pairs, 1600, 1600,
          "data/teams/pools/wide1000")  # fmt: skip
    say("value only done")


if __name__ == "__main__":
    main()
