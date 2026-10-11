"""The value-capacity experiment (design TODO "价值头实验", 2026-10-10), end to end, each step
skipped when its output exists (resumable):

  0. wait for the self-play loop to stop (data/selfplay/STOP after generation --gen)
  1. pv_bench: build (--gen's held-out games + human validation), reference (v5-glu and
     sp-gen2, the human-data and the self-play ends; deep searches)
  2. F = A's training (sp-gen<gen>: its own arguments, from its metrics.jsonl) with a value
     hidden layer (--value-hidden), another run name
  3. pv_bench scores of A and F; F vs A at --iterations (fixed pool pairs)
  4. G pretraining: v5-glu's arguments with the large trunk and the value hidden layer, on the
     data v5-glu had (--skip-shards hf-)
  5. G fine-tuning: A's training from G's pretraining, the large architecture
  6. pv_bench score of G; G vs A at equal iterations and at equal cost

Every training and match runs under a memory cap (systemd-run scope).

  uv run python scripts/exp_capacity.py --gen 4
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RUNS = Path("data/train/v5/runs")
LOG = Path("data/selfplay/diag/exp_capacity.log")
CAP = ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=40G", "-p",
       "MemorySwapMax=0"]  # fmt: skip


def say(msg: str) -> None:
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run(cmd: list[str], log: str, env: dict | None = None) -> None:
    import os

    say("$ " + " ".join(cmd))
    with open(log, "a") as f:
        subprocess.run(CAP + cmd, check=True, stdout=f, stderr=subprocess.STDOUT,
                       env=os.environ | (env or {}))  # fmt: skip


def args_of(run_name: str) -> dict:
    rows = [json.loads(x) for x in (RUNS / run_name / "metrics.jsonl").read_text().splitlines()]
    return json.loads(next(r for r in rows if r.get("event") == "start")["args"])


def to_flags(args: dict) -> list[str]:
    out = []
    for k, v in args.items():
        flag = "--" + k.replace("_", "-")
        if v is None or v is False or v == "":
            continue
        if v is True:
            out.append(flag)
        else:
            out += [flag, str(v)]
    return out


def trained(run_name: str) -> bool:
    m = RUNS / run_name / "metrics.jsonl"
    return m.exists() and '"event": "done"' in m.read_text()


def train(args: dict, log: str) -> None:
    if trained(args["run"]):
        say(f"{args['run']}: trained already")
        return
    run([sys.executable, "scripts/train_pv.py", *to_flags(args)], log)


def match(name: str, a: str, b: str, pairs: int, iters_a: int, iters_b: int, pool: str) -> None:
    out = Path("data/selfplay/diag") / f"exp_capacity_{name}.out"
    if out.exists() and "SUMMARY" in out.read_text():
        say(f"match {name}: done already")
        return
    env = {"ALPHA_MODEL_A": str(RUNS / a), "ALPHA_MODEL_B": str(RUNS / b),
           "ALPHA_SEARCH_ITERATIONS_A": str(iters_a), "ALPHA_SEARCH_ITERATIONS_B": str(iters_b),
           "ALPHA_GPU_COMPILE": "1"}  # fmt: skip
    run([sys.executable, "scripts/eval_pairs.py", "g_ma", "g_mb", "--pool", pool, "--pairs",
         str(pairs), "--log-dir", "data/selfplay/diag"], str(out), env)  # fmt: skip
    summary = next(x for x in out.read_text().splitlines() if x.startswith("SUMMARY"))
    say(f"match {name} ({a} {iters_a} it vs {b} {iters_b} it): {summary[8:]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True, help="A = sp-gen<gen>, its data and games")
    ap.add_argument("--value-hidden", type=int, default=256)
    ap.add_argument("--pairs", type=int, default=400)
    ap.add_argument("--iterations", type=int, default=3000)
    ap.add_argument("--cost-ratio", type=float, default=2.3, help="G's cost per leaf vs A's")
    ap.add_argument("--pool", default="data/teams/pools/wide1000")
    ap.add_argument("--skip-wait", action="store_true")
    a = ap.parse_args()
    py = sys.executable
    base = f"sp-gen{a.gen}"
    f_run, g_pre, g_run = f"exp-F-vh{a.value_hidden}", "exp-G-large-pre", "exp-G-large"
    # 0. the loop stops before generation gen + 1
    while not a.skip_wait:
        alive = subprocess.run(["pgrep", "-f", "[s]elfplay.py loop"], capture_output=True)
        if alive.returncode != 0:
            break
        time.sleep(60)
    assert trained(base), f"{base} is not trained"
    say(f"start (A = {base})")
    # 1. pv_bench
    bench = Path("data/eval/pv_bench")
    if not (bench / "positions.jsonl").exists():
        run([py, "scripts/pv_bench.py", "build", "--gen", str(a.gen)], str(bench) + ".log")
    if not (bench / "reference.json").exists():
        run([py, "scripts/pv_bench.py", "reference", "--nets", "v5-glu,sp-gen2"],
            str(bench) + ".log")  # fmt: skip
    # 2. F
    fa = args_of(base) | {"run": f_run, "value_hidden": a.value_hidden}
    train(fa, f"data/selfplay/diag/{f_run}.log")
    # 3. scores and F vs A
    run([py, "scripts/pv_bench.py", "score", "--nets", f"v5-glu,sp-gen2,{base},{f_run}"],
        str(bench) + ".log")  # fmt: skip
    match("F_vs_A", f_run, base, a.pairs, a.iterations, a.iterations, a.pool)
    # 4. G pretraining: v5-glu's recipe, larger
    ga = args_of("v5-glu") | {"run": g_pre, "size": "large", "d_ff": 256,
                              "value_hidden": a.value_hidden, "skip_shards": "hf-"}  # fmt: skip
    train(ga, f"data/selfplay/diag/{g_pre}.log")
    # 5. G fine-tuning: A's training from G's pretraining
    gf = args_of(base) | {"run": g_run, "init": str(RUNS / g_pre), "size": "large", "d_ff": 256,
                          "value_hidden": a.value_hidden}  # fmt: skip
    train(gf, f"data/selfplay/diag/{g_run}.log")
    # 6. G: score, equal iterations, equal cost
    run([py, "scripts/pv_bench.py", "score", "--nets", g_run], str(bench) + ".log")
    match("G_vs_A_iters", g_run, base, a.pairs, a.iterations, a.iterations, a.pool)
    match("G_vs_A_cost", g_run, base, a.pairs, round(a.iterations / a.cost_ratio), a.iterations,
          a.pool)  # fmt: skip
    say("done")


if __name__ == "__main__":
    main()
