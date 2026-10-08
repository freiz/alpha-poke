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
# a candidate that moved this much (KL to its starting point, self-play positions) and was
# rejected counts as an over-update (gen 1: 0.0023, lr 1e-4, 2 passes)
KL_BIG = 0.01
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

    if Path(f"data/train/sp{a.gen}/convert.json").exists() and not a.force:
        print(f"sp{a.gen} is converted already (--force converts again)")
        return
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

    def rows(g: int) -> int:
        return sum(
            pq.read_metadata(f).num_rows for f in Path(f"data/train/sp{g}").glob("*.parquet")
        )

    have = [g for g in range(a.gen + 1) if Path(f"data/train/sp{g}").exists()]
    recent = [g for g in have if g > a.gen - a.window]
    older = [g for g in have if g <= a.gen - a.window]
    n_recent = sum(rows(g) for g in recent)
    n_older = sum(rows(g) for g in older)
    # older generations: a random share of their games, together ~old_share of the recent
    # window (against forgetting / cycling), the same share from every older generation
    old_keep = min(1.0, a.old_share * n_recent / n_older) if n_older else 0.0
    sp = ",".join([f"sp{g}" for g in recent] + [f"sp{g}:{old_keep:.4f}" for g in older])
    n_sp = n_recent + round(old_keep * n_older)
    # human share of each batch: lowered over the generations (the human data anchors the play
    # against humans; self-play's search targets are what goes beyond them), never below 20%;
    # held when the previous generation's training drifted on the human validation
    human = max(0.2, 0.5 - 0.05 * a.gen)
    prev = st["generations"].get(str(a.gen - 1), {}).get("train", {})
    held = bool(prev.get("human_drift_flag")) and prev.get("human_share") is not None
    if held:
        human = max(human, prev["human_share"])
    # after rejected generations whose candidate MOVED a lot (KL to its starting point on
    # self-play positions >= KL_BIG: an over-update), the learning rate is halved per such
    # consecutive rejection and the human share is not lowered; a rejection of a candidate that
    # barely moved is evaluation noise: the settings stay
    rejected = 0
    for g in range(a.gen - 1, -1, -1):
        gg = st["generations"].get(str(g), {})
        ev = gg.get("eval")
        if ev is None or ev.get("promoted"):
            break
        moved = ((gg.get("train") or {}).get("last_val") or {}).get("sp_kl_ref")
        if moved is not None and moved < KL_BIG:
            break
        rejected += 1
    lr = a.lr * 0.5 ** min(rejected, 3)
    if rejected and prev.get("human_share") is not None:
        human = max(human, prev["human_share"])
        held = True
    sp_frac = a.sp_frac if a.sp_frac is not None else round(1 - human, 4)
    bsp = round(a.batch * sp_frac)
    steps = a.steps or max(50, math.ceil(a.passes * n_sp / bsp))
    run = f"sp-gen{a.gen}"
    cmd = (f"{sys.executable} scripts/train_pv.py {TRAIN_FLAGS} --selfplay {sp} "
           f"--sp-frac {sp_frac} --init {init} --steps {steps} --lr {lr} --batch {a.batch} "
           f"--warmup-frac {a.warmup_frac} --eval-every {max(50, steps // 5)} --export last "
           f"--run {run}")  # fmt: skip
    log_path = SELFPLAY_DIR / f"gen{a.gen}" / "train.log"
    out = Path("data/train/v5/runs") / run
    done = (out / "metrics.jsonl").exists() and '"event": "done"' in (
        out / "metrics.jsonl"
    ).read_text()
    if done and not a.force:  # trained already (e.g. the summary failed): summarize only
        print(f"{run} is trained already; summary only (--force retrains)", flush=True)
    else:
        print("$", cmd, flush=True)
        with open(log_path, "w") as f:
            subprocess.run(shlex.split(cmd), check=True, stdout=f, stderr=subprocess.STDOUT)
    import json

    rows = [json.loads(line) for line in (out / "metrics.jsonl").read_text().splitlines()]
    val = [r for r in rows if r.get("event") == "val"]
    keep = ("ce_turn_w", "bce_all_w", "top1", "top3", "top1_forced", "opp_act_acc", "value_ece",
            "hce_true", "hce_unk", "hce_lt1300", "hce_1300_1600", "hce_ge1600", "kl_ref_true",
            "kl_ref_unk", "sp_ce", "sp_kl", "sp_top1", "sp_bce", "sp_bce_rootq",
            "sp_kl_ref")  # fmt: skip
    summary = {"run": str(out), "init": init, "selfplay": sp, "sp_positions": n_sp,
               "recent_gens": recent, "older_gens": older, "older_keep": round(old_keep, 4),
               "human_share": round(1 - sp_frac, 4), "human_share_held": held,
               "steps": steps, "lr": lr, "after_rejections": rejected,
               "warmup_frac": a.warmup_frac,
               "first_val": {k: val[0].get(k) for k in keep} if val else None,
               "last_val": {k: val[-1].get(k) for k in keep} if val else None,
               "log": str(log_path)}  # fmt: skip
    # guard (design D15-6): the net must keep modelling human opponents. Worse cross-entropy on
    # the humans' moves is expected as it outgrows them (raw ce_turn_w / bce_all_w: reference);
    # the flag: the moves of a human *with their rating as input* predicted worse (hce_true),
    # or the opponent's next move predicted worse (opp_act_acc, what the search's opponent
    # prior needs)
    if val and val[0].get("ce_turn_w") is not None:
        keys = [k for k in keep if val[-1].get(k) is not None and val[0].get(k) is not None]
        drift = {k: round(val[-1][k] - val[0][k], 4) for k in keys}
        summary["human_drift"] = drift
        summary["human_drift_flag"] = (drift.get("hce_true", 0) > 0.01
                                       or drift.get("opp_act_acc", 0) < -0.01)  # fmt: skip
    record(a.gen, "train", summary)
    print(json.dumps(summary, indent=1))


def cmd_eval(a) -> None:
    import json
    import os

    st = state()
    if "eval" in st["generations"].get(str(a.gen), {}) and not a.force:
        print(f"gen {a.gen} is evaluated already (--force evaluates again)")
        return
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


def cmd_baseline(a) -> int:
    """The current network vs the fixed baseline (v5-glu), equal time, paired (each generation
    is only compared with the previous one: slow decline would go unseen). Keeps the best
    network by this comparison; if the current one is significantly worse than the baseline,
    the current network reverts to the best one (or the baseline) and this returns 2."""
    import json
    import os

    st = state()
    cur = st["current"]
    if cur == BASE_RUN:
        print("the current network is the baseline itself")
        return 0
    os.environ["ALPHA_MODEL_A"], os.environ["ALPHA_MODEL_B"] = cur, BASE_RUN
    os.environ["ALPHA_SEARCH_MS"] = str(a.search_ms)
    from alpha_poke.eval.arena import run_arena

    log_dir = str(SELFPLAY_DIR / f"gen{a.gen}")
    res = run_arena("s_ismcts_ma", "s_ismcts_mb", a.pairs, ports=tuple(a.ports), procs=a.procs,
                    lanes_per_proc=a.lanes, seed=1000 + a.gen, log_dir=log_dir)  # fmt: skip
    p, ci = res["paired_mean"], res["ci95_paired"]
    res |= {"network": cur, "baseline": BASE_RUN, "search_ms": a.search_ms}
    st = state()
    best = st.get("best")
    if best is None or p > best["paired_mean"]:
        st["best"] = {"run": cur, "paired_mean": p, "ci95": ci, "gen": a.gen}
    code = 0
    if p + ci < 0.5:  # significantly worse than the baseline: revert
        back = st["best"]["run"] if st["best"]["run"] != cur else BASE_RUN
        res["reverted_to"] = back
        st["current"] = back
        code = 2
    st["generations"].setdefault(str(a.gen), {})["baseline"] = res
    save_state(st)
    record(a.gen, "baseline", res)
    print(json.dumps(res, indent=1))
    return code


def cmd_loop(a) -> None:
    """Generations one after another (design D15): each a full cycle; a failed step is retried
    once. Every --baseline-every generations the current network plays the fixed baseline. Stops
    when: --max-rejected consecutive generations were not promoted, the baseline comparison
    reverted the current network (significantly worse than the baseline), or a step failed twice.
    Log: data/selfplay/loop.log."""
    import subprocess

    log = SELFPLAY_DIR / "loop.log"

    def say(msg: str) -> None:
        line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(log, "a") as f:
            f.write(line + "\n")

    me = [sys.executable, __file__]
    say(f"loop: generations {a.start}..{a.start + a.gens - 1}")
    for gen in range(a.start, a.start + a.gens):
        args = ["cycle", "--gen", str(gen), "--games", str(a.games), "--procs", str(a.procs),
                "--threads", str(a.threads), "--eval-pairs", str(a.eval_pairs)]  # fmt: skip
        for attempt in (1, 2):
            say(f"gen {gen}: cycle (attempt {attempt})")
            if subprocess.run(me + args).returncode == 0:
                break
        else:
            say(f"gen {gen}: the cycle failed twice; loop stopped (see gen{gen}/cycle.log)")
            return
        g = state()["generations"][str(gen)]
        ev, tr = g.get("eval", {}), g.get("train", {})
        say(f"gen {gen}: {'promoted' if ev.get('promoted') else 'NOT promoted'} "
            f"({ev.get('paired_mean')} +- {ev.get('ci95_paired')} vs {ev.get('against')}); "
            f"human drift flag {tr.get('human_drift_flag')}; "
            f"current {state()['current']}")  # fmt: skip
        st = state()
        rejected = 0
        for k in range(gen, -1, -1):
            if st["generations"].get(str(k), {}).get("eval", {}).get("promoted", True):
                break
            rejected += 1
        if rejected >= a.max_rejected:
            say(f"{rejected} consecutive generations not promoted: loop stopped")
            return
        if (gen - a.start + 1) % a.baseline_every == 0:
            say(f"gen {gen}: baseline comparison of {st['current']}")
            code = subprocess.run(me + ["baseline", "--gen", str(gen), "--pairs",
                                        str(a.baseline_pairs)]).returncode  # fmt: skip
            b = state()["generations"][str(gen)].get("baseline", {})
            say(f"gen {gen}: vs baseline {b.get('paired_mean')} +- {b.get('ci95_paired')}"
                f"{'; REVERTED to ' + str(b.get('reverted_to')) if code == 2 else ''}")  # fmt: skip
            if code == 2:
                say("significantly worse than the baseline: loop stopped for a look")
                return
    say("loop: done")


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
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_convert)
    p = sub.add_parser("train")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--init", default="", help="warm start run (default: the current network)")
    p.add_argument("--window", type=int, default=5, help="recent generations, all of their games")
    p.add_argument("--old-share", type=float, default=0.2,
                   help="older generations: sampled games, this share of the window")  # fmt: skip
    p.add_argument("--sp-frac", type=float, default=None,
                   help="self-play share of a batch (default: the schedule, D15-5)")  # fmt: skip
    p.add_argument(
        "--passes", type=float, default=3.0, help="times each self-play position is seen"
    )
    p.add_argument("--steps", type=int, default=0)
    # gen 0 (lr 3e-4, warmup 2 steps): the human validation drifted +0.011 / +0.013 in the
    # first 50 steps (fresh AdamW moments on a converged net), then stayed flat
    # gen 1 (1e-4, 2 passes) barely moved the net (KL 0.002 to its start): larger from gen 2
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--warmup-frac", type=float, default=0.2)
    p.add_argument("--batch", type=int, default=4096)
    p.add_argument("--force", action="store_true", help="retrain even if the run is complete")
    p.set_defaults(fn=cmd_train)
    p = sub.add_parser("eval")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--against", default="", help="default: the current network")
    p.add_argument("--pairs", type=int, default=100)
    p.add_argument("--search-ms", type=int, default=500)
    p.add_argument("--procs", type=int, default=4)
    p.add_argument("--lanes", type=int, default=6)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("baseline", help="the current network vs v5-glu")
    p.add_argument("--gen", type=int, required=True, help="where to log it")
    p.add_argument("--pairs", type=int, default=100)
    p.add_argument("--search-ms", type=int, default=500)
    p.add_argument("--procs", type=int, default=4)
    p.add_argument("--lanes", type=int, default=6)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.set_defaults(fn=lambda a: sys.exit(cmd_baseline(a)))
    p = sub.add_parser("loop", help="generations one after another")
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--gens", type=int, default=100)
    p.add_argument("--games", type=int, default=5000)
    p.add_argument("--procs", type=int, default=4)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--eval-pairs", type=int, default=50)
    p.add_argument("--baseline-every", type=int, default=3)
    p.add_argument("--baseline-pairs", type=int, default=100)
    p.add_argument("--max-rejected", type=int, default=3)
    p.set_defaults(fn=cmd_loop)
    p = sub.add_parser("cycle", help="one generation end to end")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--games", type=int, default=5000, help="team pairs if not sampled yet")
    p.add_argument("--procs", type=int, default=2)
    p.add_argument("--lanes", type=int, default=24)
    p.add_argument("--threads", type=int, default=8, help="collect threads per process")
    p.add_argument(
        "--eval-pairs",
        type=int,
        default=50,
        help="safety check per generation "
        "(100 games); a fixed-baseline comparison every few generations",
    )
    p.set_defaults(fn=cmd_cycle)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
