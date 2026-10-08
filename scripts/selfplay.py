"""Self-play pipeline (design D15). Local servers only.

  teams  --gen G --n N   team pairs for generation G -> data/selfplay/gen<G>/teams.jsonl
                         (real games completed by the belief at a temperature + complete
                         catalog teams, validated; selfplay.teams)

  run    --gen G         play generation G's pairs (resumes; --limit N for a test run)
                         -> data/selfplay/gen<G>/games-w*.jsonl, decisions-w*.jsonl, logs
  convert --gen G        -> data/train/sp<G> (training positions: recorded inputs + targets)
  train  --gen G         warm start from the current network, human data + the last --window
                         generations' self-play (--sp-frac of each batch, each position seen
                         --passes times) -> data/train/v5/runs/sp-gen<G> (train.log, metrics)
  eval   --gen G         the new network vs the current one, equal time, paired; promoted
                         unless significantly worse (design D15-6)
Every step writes its summary to data/selfplay/gen<G>/summary.json and data/selfplay/state.json
(the current network and every generation's numbers).

Usage: uv run python scripts/selfplay.py teams --gen 0 --n 2000
       uv run python scripts/selfplay.py run --gen 0 [--procs 4] [--limit 10]
"""

import argparse
import collections
import logging
import sys
import time
from pathlib import Path

from alpha_poke.selfplay import SELFPLAY_DIR

SINCE_DEFAULT = 1746057600  # 2025-05-01: the current metagame (the matchup model's window too)


def cmd_teams(a) -> None:
    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay import teams

    logging.disable(logging.WARNING)
    ts = teams.TeamSampler(BeliefModel.load(), since=a.since, half_life_days=a.half_life,
                           catalog_frac=a.catalog_frac, temp=a.temp, seed=a.seed)  # fmt: skip
    pairs = ts.sample(a.n)
    path = SELFPLAY_DIR / f"gen{a.gen}" / "teams.jsonl"
    teams.save(pairs, path)
    kinds = collections.Counter(s.kind for p in pairs for s in (p.p1, p.p2))
    print(f"{len(pairs)} pairs -> {path}; sides {dict(kinds)}; bans learned {ts.banned_moves}")


def cmd_run(a) -> None:
    import json
    import time

    from alpha_poke.selfplay import runner, teams

    gen_dir = SELFPLAY_DIR / f"gen{a.gen}"
    pairs = teams.load(gen_dir / "teams.jsonl")
    settings = {"model": a.model, "full_frac": a.full_frac, "full_iters": a.full_iters,
                "fast_iters": a.fast_iters, "fast_worlds": a.fast_worlds,
                "noise": [a.noise_eps, a.noise_conc], "lanes": a.lanes, "leaves": a.leaves,
                "threads": a.threads, "turn_cap": a.turn_cap}  # fmt: skip
    (gen_dir / "settings.json").write_text(json.dumps(settings, indent=1))
    t0 = time.time()
    n = runner.run(gen_dir, pairs, settings, a.procs, tuple(a.ports), a.limit)
    dt = time.time() - t0
    print(f"{n} games in {dt:.0f}s ({n / max(dt, 1e-9) * 3600:.0f} games/hour) -> {gen_dir}")


STATE = SELFPLAY_DIR / "state.json"  # the current network and every generation's summary
BASE_RUN = "data/train/v5/runs/v5-glu"
# the training setup of the current network (v5-glu): same flags, plus self-play
TRAIN_FLAGS = ("--data v5 --stream 4 --val-cutoff 1776921722 --eval-every 500 --arch transformer "
               "--history --mtp 3 --mtp-weight 0.5 --mtp-decay 0.5 --value-residual "
               "--value-per-game 4 --kinds main,forced,pivot,blind --aux oppset "
               "--feats reveal,num,movetab,matchup,elo,counter "
               "--d-ff 171 --ffn swiglu --norm rms --qk-norm")  # fmt: skip


def state() -> dict:
    import json

    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"current": BASE_RUN, "generations": {}}


def save_state(st: dict) -> None:
    import json

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def record(gen: int, key: str, value) -> None:
    """Add a step's summary to the generation's entry (state.json, gen<G>/summary.json)."""
    import json

    st = state()
    st["generations"].setdefault(str(gen), {})[key] = value
    save_state(st)
    (SELFPLAY_DIR / f"gen{gen}" / "summary.json").write_text(
        json.dumps(st["generations"][str(gen)], indent=1)
    )


def cmd_convert(a) -> None:
    from alpha_poke.selfplay.convert import convert

    logging.disable(logging.WARNING)
    stats = convert(SELFPLAY_DIR / f"gen{a.gen}", Path(f"data/train/sp{a.gen}"), a.gen)
    record(a.gen, "convert", stats)


def cmd_train(a) -> None:
    import math
    import shlex
    import subprocess

    import pyarrow.parquet as pq

    st = state()
    init = a.init or st["current"]
    gens = [g for g in range(a.gen - a.window + 1, a.gen + 1) if g >= 0
            and Path(f"data/train/sp{g}").exists()]  # fmt: skip
    sp = ",".join(f"sp{g}" for g in gens)
    n_sp = sum(pq.read_metadata(f).num_rows for g in gens
               for f in Path(f"data/train/sp{g}").glob("*.parquet"))  # fmt: skip
    bsp = round(a.batch * a.sp_frac)
    steps = a.steps or max(50, math.ceil(a.passes * n_sp / bsp))
    run = f"sp-gen{a.gen}"
    cmd = (f"{sys.executable} scripts/train_pv.py {TRAIN_FLAGS} --selfplay {sp} "
           f"--sp-frac {a.sp_frac} --init {init} --steps {steps} --lr {a.lr} --batch {a.batch} "
           f"--eval-every {max(50, steps // 5)} --export last --run {run}")  # fmt: skip
    print("$", cmd, flush=True)
    log_path = SELFPLAY_DIR / f"gen{a.gen}" / "train.log"
    with open(log_path, "w") as f:
        subprocess.run(shlex.split(cmd), check=True, stdout=f, stderr=subprocess.STDOUT)
    out = Path("data/train/v5/runs") / run
    import json

    rows = [json.loads(line) for line in (out / "metrics.jsonl").read_text().splitlines()]
    val = [r for r in rows if r.get("event") == "val"]
    keep = ("ce_turn_w", "bce_all_w", "top1", "top3", "top1_forced", "sp_ce", "sp_kl", "sp_top1",
            "sp_bce", "sp_bce_rootq")  # fmt: skip
    summary = {"run": str(out), "init": init, "selfplay": sp, "sp_positions": n_sp,
               "steps": steps, "lr": a.lr,
               "first_val": {k: val[0].get(k) for k in keep} if val else None,
               "last_val": {k: val[-1].get(k) for k in keep} if val else None,
               "log": str(log_path)}  # fmt: skip
    # guard (design D15-6): the human validation must not drift much (the opponents are human)
    if val and val[0].get("ce_turn_w") is not None:
        keys = [k for k in ("ce_turn_w", "bce_all_w") if val[-1].get(k) is not None]
        summary["human_drift"] = {k: round(val[-1][k] - val[0][k], 4) for k in keys}
        summary["human_drift_flag"] = any(v > 0.01 for v in summary["human_drift"].values())
    record(a.gen, "train", summary)
    print(json.dumps(summary, indent=1))


def cmd_eval(a) -> None:
    import json
    import os

    st = state()
    cand = st["generations"][str(a.gen)]["train"]["run"]
    base = a.against or st["current"]
    os.environ["ALPHA_MODEL_A"], os.environ["ALPHA_MODEL_B"] = cand, base
    os.environ["ALPHA_SEARCH_MS"] = str(a.search_ms)
    from alpha_poke.eval.arena import run_arena

    log_dir = str(SELFPLAY_DIR / f"gen{a.gen}")
    res = run_arena("s_ismcts_ma", "s_ismcts_mb", a.pairs, ports=tuple(a.ports), procs=a.procs,
                    lanes_per_proc=a.lanes, seed=a.gen, log_dir=log_dir)  # fmt: skip
    p, ci = res["paired_mean"], res["ci95_paired"]
    # promotion (design D15-6): unless significantly worse than the current network
    promote = p + ci >= 0.5
    better = p - ci > 0.5
    res |= {"candidate": cand, "against": base, "search_ms": a.search_ms, "promoted": promote,
            "significantly_better": better}  # fmt: skip
    record(a.gen, "eval", res)
    if promote:
        st = state()
        st["current"] = cand
        save_state(st)
    print(json.dumps(res, indent=1))


def cmd_cycle(a) -> None:
    """One generation end to end: team pairs (if missing) -> games -> convert -> train -> eval.
    Each step's output goes to data/selfplay/gen<G>/<step>.log; stops at the first failure."""
    import subprocess

    gen_dir = SELFPLAY_DIR / f"gen{a.gen}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    me = [sys.executable, __file__]
    steps = []
    if not (gen_dir / "teams.jsonl").exists():
        steps.append(("teams", ["teams", "--gen", str(a.gen), "--n", str(a.games)]))
    steps += [("run", ["run", "--gen", str(a.gen), "--procs", str(a.procs),
                       "--lanes", str(a.lanes), "--threads", str(a.threads)]),
              ("convert", ["convert", "--gen", str(a.gen)]),
              ("train", ["train", "--gen", str(a.gen)]),
              ("eval", ["eval", "--gen", str(a.gen), "--pairs", str(a.eval_pairs)])]  # fmt: skip
    for name, args in steps:
        t0 = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] gen {a.gen}: {name}", flush=True)
        with open(gen_dir / f"{name}.log", "a") as f:
            subprocess.run(me + args, check=True, stdout=f, stderr=subprocess.STDOUT)
        record(a.gen, f"{name}_minutes", round((time.time() - t0) / 60, 1))
    print(f"[{time.strftime('%H:%M:%S')}] gen {a.gen} done: {state()['generations'][str(a.gen)]}")


def _stop_workers(*_) -> None:
    """On SIGTERM also stop the game worker processes (they would keep playing)."""
    import multiprocessing as mp

    for p in mp.active_children():
        p.terminate()
    raise SystemExit(1)


def main() -> None:
    import signal

    signal.signal(signal.SIGTERM, _stop_workers)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("teams")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--since", type=int, default=SINCE_DEFAULT, help="real games from (unix time)")
    p.add_argument("--half-life", type=float, default=120.0, help="recency weight, days")
    p.add_argument("--catalog-frac", type=float, default=0.3)
    p.add_argument("--temp", type=float, default=1.3, help="completion temperature")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_teams)
    p = sub.add_parser("run")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--model", default="data/train/v5/runs/v5-glu")
    p.add_argument("--procs", type=int, default=2)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.add_argument("--limit", type=int, default=0, help="at most this many games (test runs)")
    p.add_argument("--full-frac", type=float, default=0.25)
    p.add_argument("--full-iters", type=int, default=3000)
    p.add_argument("--fast-iters", type=int, default=600)
    p.add_argument("--noise-eps", type=float, default=0.1)
    p.add_argument("--noise-conc", type=float, default=10.0)
    p.add_argument("--fast-worlds", type=int, default=16, help="belief worlds, fast searches")
    p.add_argument("--lanes", type=int, default=24, help="concurrent games per process")
    p.add_argument("--leaves", type=int, default=8, help="leaves per search per GPU round")
    p.add_argument("--threads", type=int, default=8, help="collect threads per process")
    p.add_argument("--turn-cap", type=int, default=300, help="forfeit at this turn (capped)")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("convert")
    p.add_argument("--gen", type=int, required=True)
    p.set_defaults(fn=cmd_convert)
    p = sub.add_parser("train")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--init", default="", help="warm start run (default: the current network)")
    p.add_argument("--window", type=int, default=5, help="self-play generations in the mix")
    p.add_argument("--sp-frac", type=float, default=0.5)
    p.add_argument(
        "--passes", type=float, default=2.0, help="times each self-play position is seen"
    )
    p.add_argument("--steps", type=int, default=0)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--batch", type=int, default=4096)
    p.set_defaults(fn=cmd_train)
    p = sub.add_parser("eval")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--against", default="", help="default: the current network")
    p.add_argument("--pairs", type=int, default=100)
    p.add_argument("--search-ms", type=int, default=500)
    p.add_argument("--procs", type=int, default=4)
    p.add_argument("--lanes", type=int, default=6)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("cycle", help="one generation end to end")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--games", type=int, default=2000, help="team pairs if not sampled yet")
    p.add_argument("--procs", type=int, default=2)
    p.add_argument("--lanes", type=int, default=24)
    p.add_argument("--threads", type=int, default=8, help="collect threads per process")
    p.add_argument("--eval-pairs", type=int, default=100)
    p.set_defaults(fn=cmd_cycle)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
