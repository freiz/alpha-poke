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
    if len(runner.done_pairs(gen_dir)) >= len(pairs):  # finished (a resumed cycle)
        print(f"{gen_dir}: all {len(pairs)} games played already")
        return
    # the generation's games are played by the current network (gens 1-2 were played by the
    # old default, v5-glu, until this was fixed)
    model = a.model or state()["current"]
    played = {json.loads(line)["model"] for f in gen_dir.glob("games-w*.jsonl")
              for line in f.read_text().splitlines()}  # fmt: skip
    if played - {model}:
        raise SystemExit(f"{gen_dir} has games of {sorted(played)}, not {model}: move them "
                         "away or pass that --model")  # fmt: skip
    settings = {"model": model, "full_frac": a.full_frac, "full_iters": a.full_iters,
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


def cmd_stats(a) -> None:
    """Game statistics of the generation (design D15-7, selfplay.stats): lengths and moves
    played, by how defensive the two teams are, and the length change against the previous
    generation with the team mix held fixed."""
    import json

    from alpha_poke.selfplay.stats import game_stats

    prev = SELFPLAY_DIR / f"gen{a.gen - 1}"
    out = game_stats(SELFPLAY_DIR / f"gen{a.gen}", prev if prev.exists() else None)
    record(a.gen, "game_stats", out)
    print(json.dumps(out, indent=1))


def cmd_value(a) -> None:
    """Value check on this generation's fresh games (design D15-7): the generation's games are
    unseen by every network up to the current one (which played them), so its decisions are an
    out-of-sample test of the value on the bots' own play: BCE, ECE, calibration slope (> 1:
    underconfident, e.g. pulled to 0.5 by human outcomes), and each network's BCE minus the
    current one's (game-clustered 95% CI). Networks: the current one, the ones earlier
    generations ended with (--back), v5-glu (value from human games only)."""
    import json
    import random

    import alpha_search
    import numpy as np

    st = state()
    if "value_check" in st["generations"].get(str(a.gen), {}) and not (a.force or a.dry):
        print(f"gen {a.gen}: value check done already (--force redoes)")
        return
    rows = []
    for f in sorted((SELFPLAY_DIR / f"gen{a.gen}").glob("decisions-w*.jsonl")):
        for line in f.read_text().splitlines():
            d = json.loads(line)
            if d["won"] is not None:
                rows.append(d)
    random.Random(a.gen).shuffle(rows)
    rows = rows[: a.n]
    y = np.array([float(d["won"]) for d in rows])
    games = np.array([d["game"] for d in rows])
    cur = st["current"]
    nets = [cur] + [anchor_of(st, a.gen, k) for k in range(1, a.back + 1)] + [BASE_RUN]
    nets = list(dict.fromkeys(nets + [n for n in a.nets.split(",") if n]))
    ctx = ([d["state"] for d in rows], [d["reveal"] for d in rows],
           [tuple(d["ratings"]) for d in rows], [d["ctx_turn"] for d in rows],
           [d["history"] for d in rows])  # fmt: skip
    loss, out = {}, {"positions": len(rows), "games": int(len(set(games.tolist()))),
                     "generator": cur, "networks": {}}  # fmt: skip
    # policy: the search targets of the full searches (raw / pruned visits, design D15-7)
    from alpha_poke.selfplay.convert import prune_visits

    full = np.array([d["full"] and sum(d["visits"]) > 0 for d in rows])
    pi = np.array([d["visits"] for d in rows], np.float64)
    pi_pruned = np.array([prune_visits(d["visits"], d["mean"], d["prior"]) if f else d["visits"]
                          for d, f in zip(rows, full, strict=True)], np.float64)  # fmt: skip

    def entropy(p):
        p = p / np.maximum(p.sum(1, keepdims=True), 1e-12)
        return -(np.where(p > 0, p * np.log(np.maximum(p, 1e-12)), 0.0)).sum(1)

    pf = pi[full] / pi[full].sum(1, keepdims=True)
    prior = np.array([d["prior"] for d in rows], np.float64)[full]
    prior = np.maximum(prior, 0) / np.maximum(np.maximum(prior, 0).sum(1, keepdims=True), 1e-12)
    out["targets"] = {
        "full_searches": int(full.sum()),
        "entropy_raw": round(float(entropy(pi[full]).mean()), 4),
        "entropy_pruned": round(float(entropy(pi_pruned[full]).mean()), 4),
        "pruned_share": round(float(1 - pi_pruned[full].sum() / pi[full].sum()), 4),
        # how far the search moved from the priors it searched with (root noise included)
        "kl_search_prior": round(float((np.where(pf > 0, pf * np.log(pf / np.maximum(
            prior, 1e-9)), 0.0)).sum(1).mean()), 4),
    }  # fmt: skip
    for net in nets:
        lg, vz = alpha_search.tnet_forward(net, *ctx)
        z = np.array(vz, np.float64)
        lg = np.array(lg, np.float64).reshape(len(rows), -1)
        lg = np.where(np.isfinite(lg), lg, -1e9)
        p = np.exp(lg - lg.max(1, keepdims=True))
        p /= p.sum(1, keepdims=True)
        kl = (np.where(pf > 0, pf * np.log(pf / np.maximum(p[full], 1e-9)), 0.0)).sum(1)
        policy = {"entropy": round(float(entropy(p).mean()), 4),
                  "max_prob": round(float(p.max(1).mean()), 4),
                  "kl_target": round(float(kl.mean()), 4),
                  "top1_target": round(float((p[full].argmax(1) == pf.argmax(1)).mean()),
                                       4)}  # fmt: skip
        pr = np.clip(1 / (1 + np.exp(-z)), 1e-6, 1 - 1e-6)
        loss[net] = -(y * np.log(pr) + (1 - y) * np.log(1 - pr))
        b = np.clip((pr * 10).astype(int), 0, 9)
        ece = sum(abs(pr[b == k].mean() - y[b == k].mean()) * (b == k).mean()
                  for k in range(10) if (b == k).any())  # fmt: skip
        c, slope = 0.0, 1.0  # y ~ sigmoid(c + slope * z), Newton
        for _ in range(50):
            q = 1 / (1 + np.exp(-(c + slope * z)))
            w = q * (1 - q)
            h = np.array([[w.sum(), (w * z).sum()], [(w * z).sum(), (w * z * z).sum()]])
            grad = [(q - y).sum(), ((q - y) * z).sum()]
            c, slope = np.array([c, slope]) - np.linalg.solve(h, grad)
        out["networks"][net] = {"bce": round(float(loss[net].mean()), 4), "ece": round(ece, 4),
                                "slope": round(float(slope), 3), "policy": policy}  # fmt: skip
    ug, inv = np.unique(games, return_inverse=True)
    for net in nets:
        d = loss[net] - loss[cur]
        per = np.bincount(inv, weights=d, minlength=len(ug))
        ci = 1.96 * per.std() * np.sqrt(len(ug)) / len(d)
        out["networks"][net] |= {"minus_current": round(float(d.mean()), 4),
                                 "ci95": round(float(ci), 4)}  # fmt: skip
    if not a.dry:
        record(a.gen, "value_check", out)
    print(json.dumps(out, indent=1))


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
    # with --per-game the kept positions are counted by train_pv (--sp-passes)
    steps = a.steps or (0 if a.per_game > 0 else max(50, math.ceil(a.passes * n_sp / bsp)))
    size = (f"--steps {steps} --eval-every {max(50, steps // 5)}" if steps else
            f"--sp-passes {a.passes} --eval-every 0")  # fmt: skip
    run = f"sp-gen{a.gen}"
    cmd = (f"{sys.executable} scripts/train_pv.py {TRAIN_FLAGS} --selfplay {sp} "
           f"--sp-frac {sp_frac} --init {init} {size} --lr {lr} --batch {a.batch} "
           f"--warmup-frac {a.warmup_frac} --export last --sp-per-game {a.per_game} "
           f"--sp-value-passes {a.value_passes} --sp-value-per-game {a.value_per_game} "
           f"--sp-value-lambda {a.value_lambda} "
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
    steps = next((r["steps"] for r in rows if r.get("event") == "start" and "steps" in r), steps)
    kept = next((r for r in rows if r.get("event") == "sp_per_game"), None)
    keep = ("ce_turn_w", "bce_all_w", "top1", "top3", "top1_forced", "opp_act_acc", "value_ece",
            "hce_true", "hce_unk", "hce_lt1300", "hce_1300_1600", "hce_ge1600", "kl_ref_true",
            "kl_ref_unk", "sp_ce", "sp_kl", "sp_top1", "sp_bce", "sp_bce_rootq",
            "sp_kl_ref")  # fmt: skip
    summary = {"run": str(out), "init": init, "selfplay": sp, "sp_positions": n_sp,
               "recent_gens": recent, "older_gens": older, "older_keep": round(old_keep, 4),
               "human_share": round(1 - sp_frac, 4), "human_share_held": held,
               "steps": steps, "lr": lr, "after_rejections": rejected,
               "per_game": a.per_game, "sp_positions_kept": kept and kept["kept"],
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


def sequential_match(a, net_a: str, net_b: str, seed: int, log_dir: str) -> dict:
    """net_a vs net_b, equal time, paired, as a sequential test (design D15-6; fishtest-style
    SPRT on the pair scores): H0 = net_a is --elo0 weaker, H1 = --elo1; checked every
    --batch-pairs finished pairs, stops when the log-likelihood ratio leaves
    [log(beta / (1 - alpha)), log((1 - beta) / alpha)], at most --pairs pairs (then: the sign
    of the ratio). "decision": "H1" (not worse) or "H0" (worse)."""
    import math
    import os

    os.environ["ALPHA_MODEL_A"], os.environ["ALPHA_MODEL_B"] = net_a, net_b
    os.environ["ALPHA_SEARCH_MS"] = str(a.search_ms)
    # a fixed number of iterations per decision (both networks have the same cost per leaf):
    # no noise from the machine's load; time only bounds a decision when it is 0
    os.environ["ALPHA_SEARCH_ITERATIONS"] = str(a.iterations)
    from alpha_poke.eval.arena import pair_scores, run_arena, sprt_llr

    lo, hi = math.log(a.beta / (1 - a.alpha)), math.log((1 - a.beta) / a.alpha)
    trace = []

    def stop(rows) -> bool:
        scores = pair_scores(rows)
        n = len(scores) // a.batch_pairs * a.batch_pairs
        if n == 0 or (trace and trace[-1][0] >= n):
            return False
        llr = sprt_llr(scores, a.elo0, a.elo1)
        trace.append((len(scores), round(llr, 3)))
        print(f"{len(scores)} pairs: score {sum(scores) / len(scores):.3f}, LLR {llr:.2f} "
              f"[{lo:.2f}, {hi:.2f}]", flush=True)  # fmt: skip
        return not lo < llr < hi

    # --gpu: the same search with the networks batched on the GPU across games (eval.bots
    # g_ma / g_mb, as in self-play; top move agrees with the CPU search as often as two CPU
    # searches do: 88.8% vs 90.0%), compiled (ALPHA_GPU_COMPILE); else one CPU search per game
    if a.gpu:
        os.environ["ALPHA_GPU_COMPILE"] = "1"
        bots, procs, lanes = ("g_ma", "g_mb"), a.gpu_procs, a.gpu_lanes
    else:
        bots, procs, lanes = ("s_ismcts_ma", "s_ismcts_mb"), a.procs, a.lanes
    res = run_arena(*bots, a.pairs, ports=tuple(a.ports), procs=procs, lanes_per_proc=lanes,
                    seed=seed, log_dir=log_dir, stop=stop)  # fmt: skip
    from alpha_poke.eval.arena import read_log

    scores = pair_scores(read_log(res["log"]))
    if not res["stopped_early"] and len(scores) < a.pairs:
        # the workers ended before the test decided and before the maximum (killed, crashed):
        # no decision (2026-10-08: an evaluation killed with no game finished promoted)
        raise RuntimeError(f"evaluation incomplete: {len(scores)} of {a.pairs} pairs, no "
                           f"decision ({res['log']})")  # fmt: skip
    llr = sprt_llr(scores, a.elo0, a.elo1)
    res |= {"llr": round(llr, 3), "llr_bounds": [round(lo, 3), round(hi, 3)],
            "elo0": a.elo0, "elo1": a.elo1, "llr_trace": trace,
            "decision": "H1" if llr >= hi or (lo < llr and llr >= 0) else "H0",
            "search_ms": a.search_ms, "search_iterations": a.iterations,
            "search": "gpu" if a.gpu else "cpu"}  # fmt: skip
    return res


def cmd_eval(a) -> None:
    import json

    st = state()
    if "eval" in st["generations"].get(str(a.gen), {}) and not a.force:
        print(f"gen {a.gen} is evaluated already (--force evaluates again)")
        return
    cand = st["generations"][str(a.gen)]["train"]["run"]
    base = a.against or st["current"]
    res = sequential_match(a, cand, base, a.gen, str(SELFPLAY_DIR / f"gen{a.gen}"))
    p, ci = res["paired_mean"], res["ci95_paired"]
    # promotion (design D15-6): unless the sequential test says worse than the current network
    promote = res["decision"] == "H1"
    res |= {"candidate": cand, "against": base, "promoted": promote,
            "significantly_better": p - ci > 0.5}  # fmt: skip
    record(a.gen, "eval", res)
    st = state()
    if promote:
        st["current"] = cand
    # the network each generation ended with (the anchor of later checks)
    st.setdefault("lineage", {})[str(a.gen)] = st["current"]
    save_state(st)
    print(json.dumps(res, indent=1))


def anchor_of(st: dict, gen: int, back: int) -> str:
    """The network generation ``gen - back`` ended with (v5-glu before the lineage starts)."""
    lineage = st.get("lineage", {})
    for k in range(gen - back, -1, -1):
        if str(k) in lineage:
            return lineage[str(k)]
    return BASE_RUN


def cmd_baseline(a) -> int:
    """Progress check (design D15-6): the current network vs the one --back generations ago
    (--against: any network, e.g. v5-glu), equal time, sequential test. Worse (H0) -> the
    current network reverts to that one, returns 2. No significant progress -> one more
    "stagnant" check in a row (state.json); returns 3 at --max-stagnant in a row (the loop stops
    for a look: most likely the network needs to grow)."""
    import json

    st = state()
    cur = st["current"]
    against = a.against or anchor_of(st, a.gen, a.back)
    if cur == against:  # nothing promoted since: no progress by definition
        res = {"network": cur, "anchor": against, "skipped": "same network", "progress": False}
    else:
        res = sequential_match(a, cur, against, 1000 + a.gen, str(SELFPLAY_DIR / f"gen{a.gen}"))
        res |= {"network": cur, "anchor": against,
                "progress": res["paired_mean"] - res["ci95_paired"] > 0.5}  # fmt: skip
    st = state()
    code = 0
    if res.get("decision") == "H0":  # worse than the anchor: revert
        res["reverted_to"] = against
        st["current"] = against
        st.setdefault("lineage", {})[str(a.gen)] = against
        code = 2
    st["stagnant"] = 0 if res["progress"] else st.get("stagnant", 0) + 1
    res["stagnant_in_a_row"] = st["stagnant"]
    if code == 0 and st["stagnant"] >= a.max_stagnant:
        code = 3
    st["generations"].setdefault(str(a.gen), {})["baseline"] = res
    save_state(st)
    record(a.gen, "baseline", res)
    print(json.dumps(res, indent=1))
    return code


def cmd_foulplay(a) -> int:
    """External anchor (design D15-6): the current network vs Foul Play at a fixed setting
    (our CPU ISMCTS --search-ms vs Foul Play --fp-ms x --fp-parallelism, heldout belief), paired.
    Never decides promotion: returns 3 (the loop stops for a look) when the score is below the
    best earlier one at the same setting by more than --drop and significantly."""
    import json
    import math
    import os

    from alpha_poke.eval.external import run_vs_foulplay

    st = state()
    cur = st["current"]
    os.environ["ALPHA_MODEL_A"] = cur
    os.environ["ALPHA_SEARCH_MS"] = str(a.search_ms)
    setting = f"ours {a.search_ms}ms vs foulplay {a.fp_ms}ms x{a.fp_parallelism}"
    res = run_vs_foulplay("s_ismcts_ma", a.pairs, ports=tuple(a.ports), lanes=a.lanes,
                          search_ms=a.fp_ms, parallelism=a.fp_parallelism, seed=2000 + a.gen,
                          log_dir=str(SELFPLAY_DIR / f"gen{a.gen}"), heldout=True)  # fmt: skip
    res |= {"network": cur, "setting": setting, "gen": a.gen}
    st = state()
    earlier = [r for r in st.get("foulplay", []) if r["setting"] == setting
               and r["games"] >= a.pairs]  # fmt: skip
    code = 0
    if earlier and res["games"] >= a.pairs:
        best = max(earlier, key=lambda r: r["paired_mean"])
        diff = best["paired_mean"] - res["paired_mean"]
        se = math.hypot(best["ci95_paired"], res["ci95_paired"]) / 1.96
        res |= {"best_gen": best["gen"], "drop": round(diff, 4), "drop_z": round(diff / se, 2)}
        if diff > a.drop and diff / se > 1.96:
            code = 3
    elif res["games"] < a.pairs:
        res["incomplete"] = True
    st.setdefault("foulplay", []).append({k: res[k] for k in (
        "gen", "network", "setting", "games", "paired_mean", "ci95_paired", "win_rate",
        "failed_games", "log")})  # fmt: skip
    save_state(st)
    record(a.gen, "foulplay", res)
    print(json.dumps(res, indent=1))
    return code


def cmd_loop(a) -> None:
    """Generations one after another (design D15): each a full cycle; a failed step is retried
    once. Every --anchor-every generations: the current network vs the one --anchor-back
    generations ago (baseline); every --foulplay-every generations (and first when there is no
    Foul Play result yet): vs Foul Play. Stops when: --max-rejected consecutive generations were
    not promoted, the progress check reverted (worse) or found no progress --max-stagnant times
    in a row, the Foul Play score dropped significantly, or a step failed twice.
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
        gs = g.get("game_stats", {})
        vp = gs.get("vs_previous", {})
        say(f"gen {gen}: games: turns mean {gs.get('turns_mean')} / p99 {gs.get('turns_p99')}, "
            f">200 {gs.get('over_200')}, capped {gs.get('capped')}, status moves "
            f"{gs.get('status_share')}; vs previous at the same team mix "
            f"{vp.get('turns_mean_diff_same_teams')} turns {vp.get('ci95')}")  # fmt: skip
        vc = g.get("value_check", {}).get("networks", {})
        pol = {Path(k).name: v.get("policy", {}).get("entropy") for k, v in vc.items()}
        say(f"gen {gen}: policy entropy on its fresh games {pol}; targets "
            f"{g.get('value_check', {}).get('targets')}")  # fmt: skip
        say(f"gen {gen}: value on its fresh games (BCE minus the generator's): "
            + ", ".join(f"{Path(k).name} {v['bce']} ({v['minus_current']:+.4f} +- {v['ci95']})"
                        for k, v in vc.items()))  # fmt: skip
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
        if gen % a.anchor_every == 0:
            st = state()
            say(f"gen {gen}: progress check of {st['current']} vs "
                f"{anchor_of(st, gen, a.anchor_back)}")  # fmt: skip
            check = ["baseline", "--gen", str(gen), "--back", str(a.anchor_back), "--pairs",
                     str(a.baseline_pairs), "--max-stagnant", str(a.max_stagnant)]  # fmt: skip
            code = subprocess.run(me + check).returncode
            b = state()["generations"][str(gen)].get("baseline", {})
            say(f"gen {gen}: vs {b.get('anchor')} {b.get('paired_mean')} +- "
                f"{b.get('ci95_paired')}; progress {b.get('progress')} "
                f"(stagnant {b.get('stagnant_in_a_row')} in a row)"
                f"{'; REVERTED to ' + str(b.get('reverted_to')) if code == 2 else ''}")  # fmt: skip
            if code == 2:
                say("worse than 3 generations ago: reverted; loop stopped for a look")
                return
            if code == 3:
                say("no progress in consecutive checks: loop stopped for a look (network size?)")
                return
        if gen % a.foulplay_every == 0 or not state().get("foulplay"):
            say(f"gen {gen}: Foul Play check of {state()['current']}")
            code = subprocess.run(me + ["foulplay", "--gen", str(gen)]).returncode
            f = state()["generations"][str(gen)].get("foulplay", {})
            say(f"gen {gen}: vs Foul Play {f.get('paired_mean')} +- {f.get('ci95_paired')} "
                f"({f.get('games')} games; drop {f.get('drop')}, z {f.get('drop_z')})")  # fmt: skip
            if code == 3:
                say("significantly worse against Foul Play than before: loop stopped for a look")
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
        # a seed per generation: with the default (0) every generation drew the same ~5,000 real
        # games (gens 1-3: 99% of their source games shared, 2026-10-08)
        steps.append(("teams", ["teams", "--gen", str(a.gen), "--n", str(a.games), "--seed",
                                str(a.gen)]))  # fmt: skip
    steps += [("run", ["run", "--gen", str(a.gen), "--procs", str(a.procs),
                       "--lanes", str(a.lanes), "--threads", str(a.threads)]),
              ("stats", ["stats", "--gen", str(a.gen)]),
              ("value", ["value", "--gen", str(a.gen)]),
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


def sprt_args(p) -> None:
    """The sequential test of eval / baseline (sequential_match); --pairs is the maximum."""
    p.add_argument(
        "--gpu",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="GPU batched search (--no-gpu: one CPU search per game)",
    )
    p.add_argument("--gpu-procs", type=int, default=4)
    p.add_argument("--gpu-lanes", type=int, default=12, help="games per process (GPU search)")
    p.add_argument("--batch-pairs", type=int, default=12, help="test every this many pairs")
    p.add_argument("--elo0", type=float, default=-20.0, help="H0: the new network this weaker")
    p.add_argument("--elo1", type=float, default=0.0, help="H1: this (not worse)")
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--beta", type=float, default=0.05)
    # 2026-10-08: networks of the same architecture compare at a fixed number of iterations
    # (time varies with the load: 500 ms gave 1,500-1,800); 3,000 = the self-play full search
    # (a larger network: compare at equal time too)
    p.add_argument("--iterations", type=int, default=3000,
                   help="search iterations per decision (0: --search-ms of time)")  # fmt: skip


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
    p.add_argument("--model", default="", help="default: the current network (state.json)")
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
    p = sub.add_parser("stats", help="game statistics of the generation")
    p.add_argument("--gen", type=int, required=True)
    p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("value", help="value check on the generation's fresh games")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--n", type=int, default=30000, help="decisions sampled")
    p.add_argument("--back", type=int, default=2, help="also the networks of these gens ago")
    p.add_argument("--nets", default="", help="more networks (comma-separated run directories)")
    p.add_argument("--dry", action="store_true", help="print only, no record")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_value)
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
    # 2026-10-08: a game's positions up to 50 (policy targets first): typical games (63
    # decisions, 16 targets) keep their targets, the 2% of long games (stall-team switch loops,
    # up to 650 decisions, 9% of all positions) no longer dominate
    p.add_argument("--per-game", type=int, default=50, help="self-play positions per game")
    p.add_argument("--steps", type=int, default=0)
    # gen 0 (lr 3e-4, warmup 2 steps): the human validation drifted +0.011 / +0.013 in the
    # first 50 steps (fresh AdamW moments on a converged net), then stayed flat
    # gen 1 (1e-4, 2 passes) barely moved the net (KL 0.002 to its start); retrained with 4e-4,
    # 3 passes, outcomes once: 56.5% +- 6.6% against it (results.md)
    p.add_argument("--lr", type=float, default=4e-4)
    p.add_argument("--value-passes", type=int, default=1,
                   help="self-play outcomes: value loss on the first k draws only")  # fmt: skip
    p.add_argument("--value-lambda", type=float, default=0.0,
                   help="self-play value targets: lambda-returns over root q's")  # fmt: skip
    p.add_argument("--value-per-game", type=int, default=0,
                   help="self-play outcomes: value loss on k positions per game")  # fmt: skip
    p.add_argument("--warmup-frac", type=float, default=0.2)
    p.add_argument("--batch", type=int, default=4096)
    p.add_argument("--force", action="store_true", help="retrain even if the run is complete")
    p.set_defaults(fn=cmd_train)
    p = sub.add_parser("eval")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--against", default="", help="default: the current network")
    p.add_argument("--pairs", type=int, default=100)
    p.add_argument("--search-ms", type=int, default=500)
    sprt_args(p)
    # a search blocks its process's event loop (the lanes of a process take turns): many
    # processes with few lanes each (2026-10-08: 4 x 10 ran only 4 searches at a time)
    p.add_argument("--procs", type=int, default=18)
    p.add_argument("--lanes", type=int, default=2)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("baseline", help="progress: the current network vs --back gens ago")
    p.add_argument("--gen", type=int, required=True, help="where to log it")
    p.add_argument("--back", type=int, default=3)
    p.add_argument("--against", default="", help="instead: this network (e.g. v5-glu)")
    p.add_argument("--max-stagnant", type=int, default=2)
    p.add_argument("--pairs", type=int, default=200)
    p.add_argument("--search-ms", type=int, default=500)
    sprt_args(p)
    # a search blocks its process's event loop (the lanes of a process take turns): many
    # processes with few lanes each (2026-10-08: 4 x 10 ran only 4 searches at a time)
    p.add_argument("--procs", type=int, default=18)
    p.add_argument("--lanes", type=int, default=2)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.set_defaults(fn=lambda a: sys.exit(cmd_baseline(a)))
    p = sub.add_parser("foulplay", help="external anchor: the current network vs Foul Play")
    p.add_argument("--gen", type=int, required=True, help="where to log it")
    p.add_argument("--pairs", type=int, default=200)
    p.add_argument("--search-ms", type=int, default=200, help="ours (CPU ISMCTS, one thread)")
    p.add_argument("--fp-ms", type=int, default=200)
    p.add_argument("--fp-parallelism", type=int, default=1)
    p.add_argument("--lanes", type=int, default=8)
    p.add_argument("--drop", type=float, default=0.05, help="stop at a significant drop > this")
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.set_defaults(fn=lambda a: sys.exit(cmd_foulplay(a)))
    p = sub.add_parser("loop", help="generations one after another")
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--gens", type=int, default=100)
    p.add_argument("--games", type=int, default=5000)
    p.add_argument("--procs", type=int, default=6)  # self-play processes (20 logical CPUs)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--eval-pairs", type=int, default=100)
    p.add_argument("--anchor-every", type=int, default=3)
    p.add_argument("--anchor-back", type=int, default=3)
    p.add_argument("--baseline-pairs", type=int, default=200)
    p.add_argument("--max-stagnant", type=int, default=2)
    p.add_argument("--foulplay-every", type=int, default=9)
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
        default=100,
        help="most pairs of the per-generation sequential test (eval)",
    )
    p.set_defaults(fn=cmd_cycle)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
