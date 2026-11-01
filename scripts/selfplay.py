"""Self-play pipeline (design D15). Local servers only.

  teams  --gen G --n N   team pairs for generation G -> data/selfplay/gen<G>/teams.jsonl
                         (real games completed by the belief at a temperature + complete
                         catalog teams, validated; selfplay.teams)

  run    --gen G         play generation G's pairs (resumes; --limit N for a test run)
                         -> data/selfplay/gen<G>/games-w*.jsonl, decisions-w*.jsonl, logs
  convert --gen G        -> data/train/r2-sp<G> (training positions: recorded inputs + targets)
  train  --gen G         warm start from the current network, human data + the last --window
                         generations' self-play (--sp-frac of each batch, each position seen
                         --passes times) -> data/train/<TRAIN_DATA>/runs/r2-gen<G> (train.log,
                         metrics)
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

from alpha_poke import paths  # noqa: E402
from alpha_poke.selfplay import SELFPLAY_DIR
from alpha_poke.selfplay.batcher import ml_for  # SEARCH_ML with a remaining-turns head
from alpha_poke.selfplay.runner import MODEL

SINCE_DEFAULT = 1746057600  # 2025-05-01: the current metagame (the matchup model's window too)


def sample_pairs(n: int, seed: int, since: int = 0, half_life: float = 120.0,
                 catalog_frac: float = 0.3, temp: float = 1.3,
                 popularity_beta: float = 0.0, synth_frac: float = 0.0, synth_tau: float = 1.0,
                 synth_gamma: float = 0.7, synth_eps: float = 0.1, set_eps: float = 0.1,
                 synth_beta: float = 0.5, synth_steps: int = 12) -> tuple[list, object]:  # fmt: skip
    """``n`` validated real-game team pairs, drawn like self-play's (selfplay.teams); ``synth_frac``
    of the sides synthetic (Composer: the usage and teammates' joint draw; evaluation pools: 0)."""
    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay import fair, teams

    logging.disable(logging.WARNING)
    # (never a fair pool's games: promotion's test would meet teams self-play trained on)
    ts = teams.TeamSampler(BeliefModel.load(), since=since or SINCE_DEFAULT, exclude=fair.games(),
                           half_life_days=half_life, catalog_frac=catalog_frac, temp=temp,
                           popularity_beta=popularity_beta, synth_frac=synth_frac, synth_tau=synth_tau,
                           synth_gamma=synth_gamma, synth_eps=synth_eps, set_eps=set_eps, synth_beta=synth_beta,
                           synth_steps=synth_steps, seed=seed)  # fmt: skip
    pairs = ts.sample(n)
    logging.disable(logging.NOTSET)
    return pairs, ts


def eval_pool(gen_dir: Path, name: str, n: int, seed: int) -> str:
    """An evaluation pool of ``n`` fresh real-game pairs (``gen_dir/<name>``, pair files for
    eval.arena.pair_schedule), drawn like self-play's with a seed of its own; kept if present."""
    import json

    d = gen_dir / name
    if len(list(d.glob("pair*_a.txt"))) >= n:
        return str(d)
    pairs, _ = sample_pairs(n, seed)
    d.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(pairs):
        (d / f"pair{i:03d}_a.txt").write_text(p.p1.text)
        (d / f"pair{i:03d}_b.txt").write_text(p.p2.text)
    meta = {"seed": seed, "pairs": len(pairs), "games": [p.game for p in pairs]}
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    return str(d)


def cmd_teams(a) -> None:
    from alpha_poke.selfplay import teams

    pairs, ts = sample_pairs(a.n, a.seed, a.since, a.half_life, a.catalog_frac, a.temp,
                             a.popularity_beta, a.synth_frac, a.synth_tau, a.synth_gamma, a.synth_eps,
                             a.set_eps, a.synth_beta, a.synth_steps)  # fmt: skip
    path = SELFPLAY_DIR / f"gen{a.gen}" / "teams.jsonl"
    if a.append and path.exists():  # more pairs for a grown generation; the drawn ones stay
        pairs = teams.load(path) + pairs
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
    played = runner.played_models(gen_dir)
    if played - {model}:
        raise SystemExit(f"{gen_dir} has games of {sorted(played)}, not {model}: move them "
                         "away or pass that --model")  # fmt: skip
    settings = {"model": model, "full_frac": a.full_frac, "full_iters": a.full_iters,
                "fast_iters": a.fast_iters, "fast_worlds": a.fast_worlds,
                "noise": [a.noise_eps, a.noise_conc], "lanes": a.lanes, "leaves": a.leaves,
                "threads": a.threads, "turn_cap": a.turn_cap, "temp_turns": a.temp_turns,
                "temp_late": a.temp_late, "dtype": a.dtype,
                "ml": a.ml if a.ml is not None else ml_for(model),
                "loop": [a.loop_quiet, a.loop_switches, a.loop_window, a.loop_tau, a.loop_noise]
                if a.loop_quiet > 0 else None}  # fmt: skip
    (gen_dir / "settings.json").write_text(json.dumps(settings, indent=1))
    t0 = time.time()
    n = runner.run(gen_dir, pairs, settings, a.procs, tuple(a.ports), a.limit)
    dt = time.time() - t0
    print(f"{n} games in {dt:.0f}s ({n / max(dt, 1e-9) * 3600:.0f} games/hour) -> {gen_dir}")


STATE = SELFPLAY_DIR / "state.json"  # the current network and every generation's summary
# 2026-10-20: self-play restarted from v0 (the v7.1 human data: inputs as the current state
# construction, no search targets from the old engine); the lineage before it (v5-glu, gens
# 0-8) is in data/selfplay/archive-v6/ and data/selfplay/registry/archive-2026-10-20/, its game data deleted.
# LINEAGE prefixes this lineage's products (self-play data data/train/<LINEAGE>-sp<G>, runs
# <LINEAGE>-gen<G>): the registry finds runs by name, the old sp-gen<G> runs stay
BASE_RUN = MODEL  # (2026-10-26: v6arch-pp-v75; 2026-10-23: v6arch-pp on v7.3; was v72/v0)
LINEAGE = "r2"


def sp_data(gen: int) -> str:
    """Generation ``gen``'s self-play training positions (data/train/<this>)."""
    return f"{LINEAGE}-sp{gen}"


# a candidate that moved this much (KL to its starting point, self-play positions) and was
# rejected counts as an over-update (gen 1: 0.0023, lr 1e-4, 2 passes)
KL_BIG = 0.01
# the training setup of the starting network (v5-glu, then v6-h, now v0): same flags, plus self-play
# --stream 2 (2026-10-10, was 4): two human shards per chunk; a chunk in use and the next one
# loading are in memory together (4 + 4 shards with the 50,000-game generations' self-play data:
# over the 40 GB cap). A generation's training reads ~0.02 epoch of the human data either way
# 2026-10-15 (from gen 8): v6 (design v6) -- the reconverted human data, the counters ("count"),
# the remaining-turns head ("turns"), the self-play outcomes spread over the run (A/B 52.38% +-
# 2.60%), the self-play data streamed in chunks (all generations no longer fit in memory)
# 2026-10-20 (lineage r2): v0's setup -- the v7.2 human data (EXTRA_VERSION 3), the v7 inputs ko2 /
# tera / team (not post: design D13 appendix). 2026-10-23: v6arch-pp's -- the v7.3 data (the decision
# stages, EXTRA_VERSION 4), v6's 7 input groups (its GPU search 38% faster than v0's). train_pv
# builds the model from these flags, so they must match the starting network's (cmd_train checks
# its config)
TRAIN_DATA = "v75"  # the human data (data/train/<x>); the generations' runs go to its runs/
FEATS = "reveal,num,movetab,matchup,elo,counter,count"
# 2026-10-27: --stream 1 (was 2) -- a 52,959-game generation's training took 31 GB with 2 human shards
# per chunk (2 in use + 2 loading, ~4.2 GB each of v7.5 features): over the 30 GB cap
TRAIN_FLAGS = (f"--data {TRAIN_DATA} --stream 1 --val-cutoff 1776921722 --train-only hf- "
               "--eval-every 500 "
               "--arch transformer "
               "--history --mtp 3 --mtp-weight 0.5 --mtp-decay 0.5 --value-residual "
               "--value-per-game 4 --kinds main,forced,pivot,blind --aux oppset,turns "
               f"--feats {FEATS} "
               "--d-ff 171 --ffn swiglu --norm rms --qk-norm "
               "--sp-value-schedule spread --sp-stream 750000")  # fmt: skip


def capped(cmd: list[str], gb: float) -> list[str]:
    """``cmd`` under a cgroup memory cap (a systemd user scope): a step that outgrows it is
    killed alone, by the OOM killer of its own cgroup, with all its child processes; without a
    cap a step can exhaust the machine's memory and take WSL down with it (2026-10-09: a 41.5 GB
    featurization of an oversized shard did). No cap without systemd-run or with gb <= 0."""
    import shutil

    if gb <= 0 or not shutil.which("systemd-run"):
        return cmd
    return ["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryMax={gb:g}G",
            "-p", "MemorySwapMax=0", *cmd]  # fmt: skip


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

    out = Path("data/train") / sp_data(a.gen)
    if (out / "convert.json").exists() and not a.force:
        print(f"{out.name} is converted already (--force converts again)")
        return
    logging.disable(logging.WARNING)
    stats = convert(SELFPLAY_DIR / f"gen{a.gen}", out, a.gen,
                    loop_margin=a.loop_margin)  # fmt: skip
    record(a.gen, "convert", stats)


def registry_match(mid: str, a_run: str, b_run: str, res: dict, kind: str, elo: bool,
                   **extra) -> None:  # fmt: skip
    """Add the match to the model registry (data/selfplay/registry) and rebuild its models.json."""
    from alpha_poke.selfplay import registry

    registry.add_match(registry.match_row(mid, a_run, b_run, res, kind=kind, elo=elo, **extra))
    registry.write(state())


def cmd_registry(a) -> None:
    """Rebuild the registry's models.json (Elo fit, model entries) from state.json, the runs and
    matches.jsonl."""
    from alpha_poke.selfplay import registry

    out = registry.write(state())
    for m in out["models"]:
        print(
            f"{m['name']:28s} gen {m['generation']!s:4s} promoted {m['promoted']!s:5s} "
            f"Elo {m['elo']} +- {m['elo_ci95']}"
        )


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
    generations ended with (--back), the base network (BASE_RUN: value from human games only)."""
    import json
    import random

    import alpha_search
    import numpy as np

    st = state()
    if "value_check" in st["generations"].get(str(a.gen), {}) and not (a.force or a.dry):
        print(f"gen {a.gen}: value check done already (--force redoes)")
        return
    # a random sample of the decisions, streamed: a 50,000-game generation's decisions (~14 GB
    # of JSON) do not fit in memory. Line numbers first, then only those lines are parsed (with
    # room for the ones without an outcome)
    files = sorted((SELFPLAY_DIR / f"gen{a.gen}").glob("decisions-w*.jsonl"))
    counts = []
    for f in files:
        with open(f, "rb") as fh:
            counts.append(sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 24), b"")))
    total = sum(counts)
    pick = set(random.Random(a.gen).sample(range(total), min(total, int(a.n * 1.2) + 100)))
    rows, base = [], 0
    for f, c in zip(files, counts, strict=True):
        with open(f, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if base + i in pick:
                    d = json.loads(line)
                    if d["won"] is not None:
                        rows.append(d)
        base += c
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
    kl_net, top1_net = {}, {}
    for net in nets:
        # (F2: the records' root posteriors; a network without post ignores them)
        posts = ([[v / 255 for v in d["post"]] for d in rows]
                 if all(d.get("post") for d in rows) else None)  # fmt: skip
        lg, vz = alpha_search.tnet_forward(net, *ctx, False, posts)
        z = np.array(vz, np.float64)
        lg = np.array(lg, np.float64).reshape(len(rows), -1)
        lg = np.where(np.isfinite(lg), lg, -1e9)
        p = np.exp(lg - lg.max(1, keepdims=True))
        p /= p.sum(1, keepdims=True)
        kl = (np.where(pf > 0, pf * np.log(pf / np.maximum(p[full], 1e-9)), 0.0)).sum(1)
        kl_net[net], top1_net[net] = kl, p[full].argmax(1) == pf.argmax(1)
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
    out["by_team"] = team_groups(a, rows, y, nets, loss, kl_net, top1_net, full)
    if not a.dry:
        record(a.gen, "value_check", out)
    print(json.dumps(out, indent=1))


def team_groups(a, rows: list, y, nets: list, loss: dict, kl_net: dict, top1_net: dict,
                full) -> dict:  # fmt: skip
    """The value check per group of the deciding player's own team (overfitting to the teams
    self-play sees most, design TODO 2026-10-09): ``catalog`` (complete catalog teams, fixed
    sets, reused across games), ``popular`` (a completed replay team whose six species came
    up >= --popular times in the teams of generations 0..gen, both sides), ``rare`` (<= --rare
    times), ``mid`` (the rest). Per network: BCE, policy KL / top-1 against the full searches;
    ``gain_vs_base``: the base network's (BASE_RUN) BCE minus this one's, so a gain that grows on
    popular / catalog teams but not on rare ones over the generations is the overfitting sign."""
    import json
    from collections import Counter

    import numpy as np

    from alpha_poke.selfplay import teams

    def comp(text: str) -> frozenset:
        return frozenset(teams.species_names(text))

    counts: Counter = Counter()
    for g in range(a.gen + 1):
        f = SELFPLAY_DIR / f"gen{g}" / "teams.jsonl"
        if f.exists():
            for pr in teams.load(f):
                counts.update([comp(pr.p1.text), comp(pr.p2.text)])
    gen_dir = SELFPLAY_DIR / f"gen{a.gen}"
    pairs = teams.load(gen_dir / "teams.jsonl")
    a_side = {}  # pair -> the side player a (team p1 of the pair) played
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in f.read_text().splitlines():
            gm = json.loads(line)
            a_side[gm["pair"]] = gm["a_side"]

    def group(d: dict) -> str:
        pr = pairs[d["game"]]
        side = pr.p1 if d["side"] == a_side.get(d["game"]) else pr.p2
        if side.kind in ("catalog", "synthetic"):  # (synthetic: Composer's, 2026-10-26)
            return side.kind
        n = counts[comp(side.text)]
        return "popular" if n >= a.popular else "rare" if n <= a.rare else "mid"

    labels = np.array([group(d) for d in rows])
    out = {}
    for lab in ("catalog", "synthetic", "popular", "mid", "rare"):
        m = labels == lab
        if not m.any():
            continue
        mf = m[full]
        res = {"positions": int(m.sum()), "nets": {}}
        for net in nets:
            res["nets"][Path(net).name] = {
                "bce": round(float(loss[net][m].mean()), 4),
                "gain_vs_base": round(float(loss[BASE_RUN][m].mean() - loss[net][m].mean()), 4),
                "kl_target": round(float(kl_net[net][mf].mean()), 4) if mf.any() else None,
                "top1_target": round(float(top1_net[net][mf].mean()), 4) if mf.any() else None,
            }
        out[lab] = res
    return out


def cmd_train(a) -> None:
    import json
    import math
    import shlex
    import subprocess

    import pyarrow.parquet as pq

    st = state()
    init = a.init or st["current"]
    # the model is built from TRAIN_FLAGS: a starting network with other inputs does not load
    feats = json.loads((Path(init) / "config.json").read_text()).get("feats")
    if feats != FEATS.split(","):
        raise SystemExit(f"{init} reads {feats}, the training flags {FEATS}")

    def rows(g: int) -> int:
        return sum(
            pq.read_metadata(f).num_rows
            for f in (Path("data/train") / sp_data(g)).glob("*.parquet")
        )

    have = [g for g in range(a.gen + 1) if (Path("data/train") / sp_data(g)).exists()]
    recent = [g for g in have if g > a.gen - a.window]
    older = [g for g in have if g <= a.gen - a.window]
    n_recent = sum(rows(g) for g in recent)
    n_older = sum(rows(g) for g in older)
    # older generations: a random share of their games, together ~old_share of the recent
    # window (against forgetting / cycling), the same share from every older generation
    old_keep = min(1.0, a.old_share * n_recent / n_older) if n_older else 0.0
    sp = ",".join([sp_data(g) for g in recent] + [f"{sp_data(g)}:{old_keep:.4f}" for g in older])
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
    # (iterate: attempt k of a generation -- its games so far -- is a run of its own)
    run = f"{LINEAGE}-gen{a.gen}" + (f"a{a.attempt}" if a.attempt else "")
    cmd = (f"{sys.executable} scripts/train_pv.py {TRAIN_FLAGS} --selfplay {sp} "
           f"--sp-frac {sp_frac} --init {init} {size} --lr {lr} --batch {a.batch} "
           f"--warmup-frac {a.warmup_frac} --export last --sp-per-game {a.per_game} "
           f"--sp-value-passes {a.value_passes} --seed {a.gen} --run {run}")  # fmt: skip
    log_path = (
        SELFPLAY_DIR / f"gen{a.gen}" / (f"train-a{a.attempt}.log" if a.attempt else "train.log")
    )
    out = Path("data/train") / TRAIN_DATA / "runs" / run
    done = (out / "metrics.jsonl").exists() and '"event": "done"' in (
        out / "metrics.jsonl"
    ).read_text()
    if done and not a.force:  # trained already (e.g. the summary failed): summarize only
        print(f"{run} is trained already; summary only (--force retrains)", flush=True)
    else:
        print("$", cmd, flush=True)
        with open(log_path, "w", encoding="utf-8") as f:
            subprocess.run(shlex.split(cmd), check=True, stdout=f, stderr=subprocess.STDOUT)

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


# a played schedule decides only with at least this share of its pairs complete (both games
# finished)
MIN_PAIRS_FRAC = 0.8


def sequential_match(a, net_a: str, net_b: str, seed: int, log_dir: str) -> dict:
    """net_a vs net_b at a fixed number of search iterations, paired, as a sequential test
    (design D15-6; fishtest-style SPRT on the pair scores): H0 = net_a is --elo0 weaker,
    H1 = --elo1; checked every --batch-pairs finished pairs, stops when the log-likelihood
    ratio leaves [log(beta / (1 - alpha)), log((1 - beta) / alpha)], at most --pairs pairs
    (then: the sign of the ratio). "decision": "H1" (not worse) or "H0" (worse).

    The teams (selfplay.fair: real games after the training cutoff, both players >= 1500, the
    revealed parts kept and the rest from reveal-corrected usage): --pool a team bank (default
    teambank10k) -- this test's own --pairs pairs drawn from it (seed ``seed`` + 200,000: the
    same month, ratings within 200, every team once) -- or a fixed fair pool (fair1000; built if
    missing), its first --pairs at most. 2026-10-30: was a fresh pool per attempt drawn like
    self-play's teams (belief-completed, 13% of its games self-play sources): r2-gen0a3 scored
    55.9% +- 3.2% there, 52.8% +- 2.5% on fair1000. Before: not the 40 copied teams of replay40
    (2026-10-08: on those gen 2 scored 46.5% against gen 1, on 200 real-game pairs 53.6%)."""
    import json
    import math
    import os

    os.environ["ALPHA_MODEL_A"], os.environ["ALPHA_MODEL_B"] = net_a, net_b
    os.environ["ALPHA_ML_A"], os.environ["ALPHA_ML_B"] = ml_for(net_a), ml_for(net_b)
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
    from alpha_poke.selfplay import fair

    pool = paths.POOLS / a.pool
    kind = (json.loads((pool / "meta.json").read_text(encoding="utf-8")).get("kind")
            if (pool / "meta.json").exists() else None)  # fmt: skip
    if kind == "fairbank":
        pool = Path(
            fair.bank_pool(pool, Path(log_dir) / f"eval_bank_{seed}", a.pairs, 200_000 + seed)
        )
    elif a.pool == fair.BANK:
        raise SystemExit(f"no team bank {pool}: build it (scripts/fair_pool.py --bank)")
    elif not pool.exists():
        fair.build(a.pool, a.pairs)
    n_pairs = min(a.pairs, fair.size(pool))
    pool = str(pool)
    res = run_arena(*bots, n_pairs, pool_dir=pool, ports=tuple(a.ports), procs=procs,
                    lanes_per_proc=lanes, seed=seed, log_dir=log_dir, stop=stop,
                    pairs=True)  # fmt: skip
    from alpha_poke.eval.arena import read_log

    rows = read_log(res["log"])
    scores = pair_scores(rows)
    if not res["stopped_early"] and len(rows) < 2 * n_pairs:
        # the workers ended before the schedule was played (killed, crashed): no decision
        # (2026-10-08: an evaluation killed with no game finished promoted). A played schedule
        # with failed or timed-out games decides on its complete pairs
        raise RuntimeError(f"evaluation incomplete: {len(rows)} of {2 * n_pairs} games, no "
                           f"decision ({res['log']})")  # fmt: skip
    if len(scores) < MIN_PAIRS_FRAC * n_pairs and not res["stopped_early"]:
        # (2026-10-14: every game failed -> no pair -> llr 0 -> H1 would promote)
        raise RuntimeError(f"evaluation: {len(scores)} complete pairs of {n_pairs}, no "
                           f"decision ({res['log']})")  # fmt: skip
    if not scores:
        raise RuntimeError(f"evaluation: no complete pair, no decision ({res['log']})")
    llr = sprt_llr(scores, a.elo0, a.elo1)
    res |= {"llr": round(llr, 3), "llr_bounds": [round(lo, 3), round(hi, 3)],
            "elo0": a.elo0, "elo1": a.elo1, "llr_trace": trace,
            "decision": "H1" if llr >= hi or (lo < llr and llr >= 0) else "H0",
            "search_ms": a.search_ms, "search_iterations": a.iterations, "pool": pool,
            "search": "gpu" if a.gpu else "cpu"}  # fmt: skip
    return res


def cmd_eval(a) -> None:
    import json

    st = state()
    key = f"eval_a{a.attempt}" if a.attempt else "eval"
    if key in st["generations"].get(str(a.gen), {}) and not a.force:
        print(f"gen {a.gen} ({key}) is evaluated already (--force evaluates again)")
        return
    cand = st["generations"][str(a.gen)]["train"]["run"]
    base = a.against or st["current"]
    # (an attempt's own team pool: seed 1,000 x gen + attempt -- a pool used again would let
    # the attempts' repeated tests fit it)
    seed = 1000 * a.gen + a.attempt if a.attempt else a.gen
    res = sequential_match(a, cand, base, seed, str(SELFPLAY_DIR / f"gen{a.gen}"))
    p, ci = res["paired_mean"], res["ci95_paired"]
    # promotion (design D15-6): unless the sequential test says worse than the current network;
    # iterate (2026-10-27): only when it says better (H1 = elo1 above, against H0 = elo0 above)
    promote = res["decision"] == "H1"
    if a.attempt and promote and res["llr"] < res["llr_bounds"][1]:
        # (the test ran to --pairs undecided: H1 by the sign alone -- an attempt is promoted then
        # only if the 95% interval's lower end is above H0's score)
        from alpha_poke.eval.arena import elo_score

        promote = p - ci >= elo_score(a.elo0)
    res |= {"candidate": cand, "against": base, "promoted": promote,
            "significantly_better": p - ci > 0.5}  # fmt: skip
    record(a.gen, key, res)
    registry_match(f"gen{a.gen}-{key.replace('_', '-')}", cand, base, res, "promotion", True)
    st = state()
    if promote:
        st["current"] = cand
    if promote or not a.attempt:  # (an attempt that failed: the generation goes on)
        if a.attempt:
            st["generations"][str(a.gen)]["eval"] = res
        # the network each generation ended with (the anchor of later checks)
        st.setdefault("lineage", {})[str(a.gen)] = st["current"]
    save_state(st)
    print(json.dumps(res, indent=1))


def anchor_of(st: dict, gen: int, back: int) -> str:
    """The network generation ``gen - back`` ended with (BASE_RUN before the lineage starts)."""
    lineage = st.get("lineage", {})
    for k in range(gen - back, -1, -1):
        if str(k) in lineage:
            return lineage[str(k)]
    return BASE_RUN


def cmd_baseline(a) -> int:
    """Progress check (design D15-6): the current network vs the one --back generations ago
    (--against: any network, e.g. v6-s-spread), equal time, sequential test. Worse (H0) -> the
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
    # revert only on a significant result: the ratio past its lower bound (2026-10-09: a check
    # that ended undecided at the cap, 48.1% +- 2.9%, reverted to gen 0 by the ratio's sign);
    # an undecided result counts as no progress (below)
    lo = (res.get("llr_bounds") or [float("-inf")])[0]
    if res.get("llr") is not None and res["llr"] <= lo:  # worse than the anchor: revert
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
    if "skipped" not in res:
        registry_match(f"gen{a.gen}-baseline", cur, against, res, "progress check", True)
    print(json.dumps(res, indent=1))
    return code


def cmd_diag(a) -> None:
    """Diagnostic team pools (design D16): the current network vs --against (BASE_RUN) on fixed
    pools beyond the ladder distribution (data/derived/teams/pools: wide200 = the ladder's, offmeta200,
    random200; scripts/team_pools.py), --pairs each, GPU search at --iterations, no early stop.
    Never decides anything: whether self-play's gain on the ladder pool and on the others drift
    apart over the generations (overfitting to the common teams). Recorded in state.json
    (generation's ``diag_pools``) and the registry (not in the Elo fit)."""
    import json
    import os

    from alpha_poke.eval.arena import run_arena

    st = state()
    cur, against = st["current"], a.against
    os.environ["ALPHA_MODEL_A"], os.environ["ALPHA_MODEL_B"] = cur, against
    os.environ["ALPHA_ML_A"], os.environ["ALPHA_ML_B"] = ml_for(cur), ml_for(against)
    os.environ["ALPHA_SEARCH_ITERATIONS"] = str(a.iterations)
    os.environ["ALPHA_GPU_COMPILE"] = "1"
    out = {}
    for pool in a.pools.split(","):
        pdir = str(paths.pool(pool))
        res = run_arena("g_ma", "g_mb", a.pairs, pool_dir=pdir, ports=tuple(a.ports),
                        procs=a.gpu_procs, lanes_per_proc=a.gpu_lanes, seed=0,
                        log_dir=str(SELFPLAY_DIR / f"gen{a.gen}"), pairs=True)  # fmt: skip
        res |= {"network": cur, "against": against, "pool": pdir, "search": "gpu",
                "search_iterations": a.iterations}  # fmt: skip
        out[pool] = {k: res.get(k) for k in ("games", "pairs", "paired_mean", "ci95_paired",
                                             "failed_games", "log")}  # fmt: skip
        print(pool, json.dumps(out[pool]), flush=True)
        registry_match(f"gen{a.gen}-diag-{pool}", cur, against, res, "diagnostic pool", False)
    record(a.gen, "diag_pools", out)


def cmd_foulplay(a) -> int:
    """External anchor (design D15-6): the current network vs Foul Play at a fixed setting
    (our CPU ISMCTS --search-ms vs Foul Play --fp-ms x --fp-parallelism) on the SAME 200 real-game
    team pairs every time (data/derived/teams/pools/wide200, sampled like self-play's with seed 9001;
    re-sampled if missing), each played twice with the teams exchanged.
    Never decides promotion: returns 3 (the loop stops for a look) when the score is below the
    best earlier one at the same setting by more than --drop and significantly."""
    import json
    import math
    import os

    from alpha_poke.eval.external import run_vs_foulplay

    st = state()
    cur = st["current"]
    os.environ["ALPHA_MODEL_A"] = cur
    os.environ["ALPHA_ML"] = ml_for(cur)  # the CPU search (s_ismcts_ma)
    os.environ["ALPHA_SEARCH_MS"] = str(a.search_ms)
    pool = eval_pool(paths.POOLS, "wide200", 200, 9001)
    setting = (f"ours {a.search_ms}ms vs foulplay {a.fp_ms}ms x{a.fp_parallelism}, "
               f"{Path(pool).name} pairs")  # fmt: skip
    res = run_vs_foulplay("s_ismcts_ma", a.pairs, pool_dir=pool, ports=tuple(a.ports),
                          lanes=a.lanes, search_ms=a.fp_ms, parallelism=a.fp_parallelism,
                          log_dir=str(SELFPLAY_DIR / f"gen{a.gen}"), pairs=True)  # fmt: skip
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
    registry_match(f"gen{a.gen}-foulplay", cur, f"foulplay-{a.fp_ms}ms", res, "external", False,
                   search_ms=a.search_ms)  # fmt: skip
    print(json.dumps(res, indent=1))
    return code


def cmd_iterate(a) -> None:
    """One generation grown until it gives a clearly better network (2026-10-27): its games so
    far converted, the current network fine-tuned on them (attempt k: run <LINEAGE>-gen<G>a<k>),
    then the sequential test against the current network with H0 = --elo0 better (default
    +7.0 Elo: a 51% score), H1 = --elo1 (+27.8: 54%) -- promoted only on H1, i.e. confidently
    above 51% (2026-10-28; was 52% / 55%). Otherwise --chunk more games of the same network and the next attempt on all of
    them; stops promoted or at --max-games. Every attempt's games and result: the generation's
    "attempts" (state.json): how many self-play games a clearly better network takes."""
    import json
    import subprocess

    from alpha_poke.selfplay import runner
    from alpha_poke.selfplay import teams as teams_mod

    gen_dir = SELFPLAY_DIR / f"gen{a.gen}"
    me = [sys.executable, __file__]

    def step(name: str, args: list[str]) -> None:
        t0 = time.time()
        print(f"[{time.strftime('%m-%d %H:%M:%S')}] gen {a.gen}: {name}", flush=True)
        with open(gen_dir / f"{name}.log", "a", encoding="utf-8") as f:
            subprocess.run(capped(me + args, a.mem_cap_gb), check=True, stdout=f,
                           stderr=subprocess.STDOUT)  # fmt: skip
        record(a.gen, f"{name}_minutes", round((time.time() - t0) / 60, 1))

    attempts = state()["generations"].get(str(a.gen), {}).get("attempts", [])
    while True:
        k = len(attempts) + 1
        games = len(runner.done_pairs(gen_dir))
        # (more games before another attempt: --chunk more than the last attempt had -- the first
        # attempt --chunk games, 2026-10-31: a new generation went to its training with none; a
        # resumed run plays only what the chunk still lacks)
        target = (attempts[-1]["games"] if attempts else 0) + a.chunk
        if games < target:
            if games >= a.max_games:
                print(f"gen {a.gen}: {games} games, no clearly better network -- stopped")
                return
            need = target - games
            have = (
                len(teams_mod.load(gen_dir / "teams.jsonl"))
                if (gen_dir / "teams.jsonl").exists()
                else 0
            )
            if have < target:
                step("teams", ["teams", "--gen", str(a.gen), "--n", str(target - have),
                               "--seed", str(1000 * a.gen + have)] + (["--append"] if have else []))  # fmt: skip
            step("run", ["run", "--gen", str(a.gen), "--procs", str(a.procs), "--lanes",
                         str(a.lanes), "--threads", str(a.threads), "--limit", str(need)])  # fmt: skip
            games = len(runner.done_pairs(gen_dir))
        conv = Path("data/train") / sp_data(a.gen) / "convert.json"
        if not (conv.exists() and json.loads(conv.read_text()).get("games") == games):
            # (else: converted already)
            step("convert", ["convert", "--gen", str(a.gen), "--force"])
        step("train", ["train", "--gen", str(a.gen), "--attempt", str(k), "--force"])
        step("eval", ["eval", "--gen", str(a.gen), "--attempt", str(k), "--force",
                      "--pairs", str(a.eval_pairs), "--iterations", str(a.eval_iterations),
                      "--elo0", str(a.elo0), "--elo1", str(a.elo1), "--alpha", str(a.alpha),
                      "--beta", str(a.beta), "--pool", a.eval_pool])  # fmt: skip
        g = state()["generations"][str(a.gen)]
        ev, tr = g[f"eval_a{k}"], g["train"]
        attempts.append({"attempt": k, "games": games, "run": tr["run"], "steps": tr["steps"],
                         "pairs": ev["pairs"],
                         "paired_mean": ev["paired_mean"], "ci95": ev["ci95_paired"],
                         "llr": ev["llr"], "decision": ev["decision"], "promoted": ev["promoted"]})  # fmt: skip
        record(a.gen, "attempts", attempts)
        print(json.dumps(attempts[-1]), flush=True)
        if ev["promoted"]:
            print(f"gen {a.gen}: promoted {tr['run']} after {games} games")
            return
        if a.once:  # (this attempt only: no more games without being asked)
            print(f"gen {a.gen}: not promoted after {games} games -- stopped (--once)")
            return


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
    p.add_argument("--pool", default="teambank10k",
                   help="a team bank or fixed team pairs (data/derived/teams/pools; selfplay.fair)")  # fmt: skip
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
    # self-play's team mix (design D16, from gen 3; evaluation pools keep the ladder's: 0.3 / 0)
    p.add_argument("--catalog-frac", type=float, default=0.15)
    p.add_argument("--popularity-beta", type=float, default=0.3,
                   help="flatten the compositions' popularity (0 = as on the ladder)")  # fmt: skip
    p.add_argument("--temp", type=float, default=1.3, help="completion temperature")
    # (2026-10-26: half the sides synthetic -- compositions beyond the ladder's own, drawn by the
    # usage and the teammates jointly; the other half as before: catalog / completed replay sides)
    p.add_argument("--synth-frac", type=float, default=0.5, help="share of synthetic sides")
    p.add_argument("--synth-tau", type=float, default=1.0, help="usage flattening (> 1: rarer)")
    p.add_argument("--synth-gamma", type=float, default=0.7, help="teammates' weight (0: none)")
    p.add_argument("--synth-eps", type=float, default=0.1, help="a pick's noise (flat usage)")
    p.add_argument("--set-eps", type=float, default=0.1, help="a set's noise per slot")
    p.add_argument("--synth-beta", type=float, default=0.5, help="the sets' synergy weight")
    p.add_argument("--synth-steps", type=int, default=12, help="Metropolis-Hastings steps per team")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--append", action="store_true", help="add to the generation's pairs")
    p.set_defaults(fn=cmd_teams)
    p = sub.add_parser("run")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--model", default="", help="default: the current network (state.json)")
    p.add_argument("--procs", type=int, default=2)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.add_argument("--limit", type=int, default=0, help="at most this many games (test runs)")
    p.add_argument("--full-frac", type=float, default=0.25)
    # 2026-10-10 (from gen 4): 1,600 / 400 (was 3,000 / 600): ~700 iterations per decision
    # instead of ~1,200, ~1.7x the games (value, the bottleneck, needs independent games); a
    # 1,600-iteration target keeps ~80% of a 3,000 one's gain over the prior (results.md)
    p.add_argument("--full-iters", type=int, default=1600)
    p.add_argument("--fast-iters", type=int, default=400)
    p.add_argument("--noise-eps", type=float, default=0.1)
    p.add_argument("--noise-conc", type=float, default=10.0)
    p.add_argument("--fast-worlds", type=int, default=16, help="belief worlds, fast searches")
    p.add_argument("--lanes", type=int, default=24, help="concurrent games per process")
    p.add_argument("--leaves", type=int, default=8, help="leaves per search per GPU round")
    p.add_argument("--threads", type=int, default=8, help="collect threads per process")
    p.add_argument("--turn-cap", type=int, default=300, help="forfeit at this turn (capped)")
    p.add_argument("--temp-turns", type=int, default=8, help="moves sampled at tau 1 until")
    p.add_argument("--temp-late", type=float, default=0.25, help="tau after --temp-turns")
    # stalling loops (2026-10-14, design "stall loops"): exploration once a side loops
    p.add_argument(
        "--loop-quiet",
        type=int,
        default=20,
        help="a loop: no faint for this many turns (0: off) ...",
    )
    p.add_argument(
        "--loop-switches", type=int, default=6, help="... and the side switched in this many ..."
    )
    p.add_argument("--loop-window", type=int, default=8, help="... of its last turns")
    p.add_argument("--loop-tau", type=float, default=1.0, help="tau in a loop")
    p.add_argument("--loop-noise", type=float, default=0.25, help="root noise eps in a loop")
    p.add_argument("--dtype", choices=["fp32", "bf16"], default="bf16", help="GPU inference")
    p.add_argument("--ml", default=None,
                   help="moves-left term 'slope,cap,threshold' (default: SEARCH_ML)")  # fmt: skip
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("convert")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--force", action="store_true")
    # capped games (stalling loops; valued as a draw): no policy target from this many turns
    # after the last faint
    p.add_argument("--loop-margin", type=int, default=10)
    p.set_defaults(fn=cmd_convert)
    p = sub.add_parser(
        "registry", help="rebuild the model registry (data/selfplay/registry/models.json)"
    )
    p.set_defaults(fn=cmd_registry)
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
    p.add_argument("--popular", type=int, default=10, help="team groups: seen this often")
    p.add_argument("--rare", type=int, default=1, help="team groups: seen at most this often")
    p.set_defaults(fn=cmd_value)
    p = sub.add_parser("train")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--init", default="", help="warm start run (default: the current network)")
    # 2026-10-11 (from gen 5; was 5 / 0.2): the newest generation in full (the current
    # network's games: on-policy outcomes, the strongest search targets) and the older ones
    # sampled to half its size (against forgetting). A window of 5 generations kept everything
    # once the generations grew from 10,000 to 50,000 games (gens 0-3: 35,000 games together)
    p.add_argument("--window", type=int, default=1, help="recent generations, all of their games")
    p.add_argument("--old-share", type=float, default=0.5,
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
    p.add_argument("--warmup-frac", type=float, default=0.2)
    p.add_argument("--batch", type=int, default=4096)
    p.add_argument("--force", action="store_true", help="retrain even if the run is complete")
    p.add_argument("--attempt", type=int, default=0, help="iterate: attempt k (run ...a<k>)")
    p.set_defaults(fn=cmd_train)
    p = sub.add_parser("eval")
    p.add_argument("--gen", type=int, required=True)
    p.add_argument("--against", default="", help="default: the current network")
    p.add_argument("--pairs", type=int, default=400)
    p.add_argument("--search-ms", type=int, default=500)
    sprt_args(p)
    # a search blocks its process's event loop (the lanes of a process take turns): many
    # processes with few lanes each (2026-10-08: 4 x 10 ran only 4 searches at a time)
    p.add_argument("--procs", type=int, default=18)
    p.add_argument("--lanes", type=int, default=2)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.add_argument("--force", action="store_true")
    p.add_argument("--attempt", type=int, default=0, help="iterate: attempt k (eval_a<k>)")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser(
        "diag", help="diagnostic team pools: current vs the base network (D16; by hand)"
    )
    p.add_argument("--gen", type=int, required=True, help="where to log it")
    p.add_argument("--against", default=BASE_RUN)
    p.add_argument("--pools", default="wide200,offmeta200,random200")
    p.add_argument("--pairs", type=int, default=200)
    p.add_argument("--iterations", type=int, default=3000)
    p.add_argument("--gpu-procs", type=int, default=4)
    p.add_argument("--gpu-lanes", type=int, default=12)
    p.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    p.set_defaults(fn=cmd_diag)
    p = sub.add_parser("baseline", help="progress: the current network vs --back gens ago")
    p.add_argument("--gen", type=int, required=True, help="where to log it")
    p.add_argument("--back", type=int, default=3)
    p.add_argument("--against", default="", help="instead: this network (e.g. v6-s-spread)")
    p.add_argument("--max-stagnant", type=int, default=2)
    p.add_argument("--pairs", type=int, default=400)
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
    p = sub.add_parser("iterate", help="one generation grown until a clearly better network")
    p.add_argument("--gen", type=int, required=True)
    # (50,000, 2026-10-28: was 25,000 -- attempt 2 on 77,959 games 52.5% +- 2.1%, short of the bar)
    p.add_argument("--chunk", type=int, default=50000, help="more games before the next attempt")
    p.add_argument("--max-games", type=int, default=300000)
    p.add_argument("--procs", type=int, default=10)
    p.add_argument("--lanes", type=int, default=24)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--eval-pairs", type=int, default=2000, help="the test's most pairs")
    p.add_argument("--eval-iterations", type=int, default=1600)
    p.add_argument("--eval-pool", default="teambank10k", help="the test's team bank or fixed pairs")
    # (H0: 51% -- 400 log10(0.51 / 0.49) Elo; H1: 54%. 2026-10-28, was 52% / 55%: promoted with
    # P ~ 18% / 57% / 86% at a true 52 / 53 / 54%, ~1% at 50%)
    p.add_argument("--elo0", type=float, default=7.0, help="H0: the candidate this much better")
    p.add_argument("--elo1", type=float, default=27.8, help="H1: this much (promoted)")
    p.add_argument("--alpha", type=float, default=0.05, help="P(promoted | at most elo0)")
    p.add_argument("--beta", type=float, default=0.1)
    # (30, 2026-10-27: a 40 GB training left the 48 GB WSL too little -- the session's background
    # tasks were stopped for low memory)
    p.add_argument("--mem-cap-gb", type=float, default=30, help="memory cap of every step")
    p.add_argument(
        "--once",
        action="store_true",
        help="stop after this attempt's test (not promoted: no more games)",
    )
    p.set_defaults(fn=cmd_iterate)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
