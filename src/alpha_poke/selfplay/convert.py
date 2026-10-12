"""Self-play games -> training positions (design D15-3 / D15-5).

Per game: the replay pipeline (``positions_from_replay`` on the saved protocol log, every
decision point) gives each decision the labels only the whole game knows (future steps for the
MTP heads, faints, mons left, game length, ...) exactly as for the human data; each decision is
matched to the player's record by (side, turn, kind) (a turn start whose action the log does
not show, KIND_BLIND, is a turn start here: the record knows the action) and its INPUT is
replaced by the record's: world 0 and its context, what the root network saw during the search.
Added columns: ``pi`` (visit distribution over the 14 slots, full searches; zeros otherwise),
``pi_w`` (1 = full search: policy target), ``q`` (root value), ``value_ok`` (0 for capped
games: no outcome). ``action`` = the slot played (the record's).

Output: data/train/sp<gen>/shard-<k>.parquet, the human data's columns plus these."""

import json
import math
import os
import random
import shutil
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import alpha_search
import pyarrow as pa
import pyarrow.parquet as pq

from alpha_poke.train.positions import KIND_BLIND, KIND_MAIN, positions_from_replay

C_PUCT = 1.0  # the search's exploration constant (bsearch / ismcts c_puct)


def prune_visits(visits: list, mean: list, prior: list, c: float = C_PUCT) -> list:
    """Policy target pruning (KataGo): the visits a move got only from the exploration bonus are
    removed. For each move but the most visited one b, the most visits n' it would still be
    chosen with: Q_i + c P_i sqrt(N) / (1 + n') >= U_b = Q_b + c P_b sqrt(N) / (1 + n_b), i.e.
    n' = floor(c P_i sqrt(N) / (U_b - Q_i)) - 1, capped at its visits; a move left with one
    visit gets none. P = the root priors the search used (with the root noise), Q = the mean
    values (our side). Returns the pruned visits."""
    n = sum(visits)
    if n == 0:
        return list(visits)
    b = max(range(len(visits)), key=lambda i: visits[i])
    sq = math.sqrt(n)
    u_b = mean[b] + c * prior[b] * sq / (1 + visits[b])
    out = list(visits)
    for i, v in enumerate(visits):
        if i == b or v == 0 or mean[i] >= u_b:
            continue
        keep = math.floor(c * max(prior[i], 0.0) * sq / (u_b - mean[i])) - 1
        keep = max(0, min(v, keep))
        out[i] = 0 if keep <= 1 else keep
    return out


def load_gen(gen_dir: Path) -> tuple[dict, dict]:
    """(games by pair, logs by pair) of a generation directory (the decisions are streamed by
    ``split_decisions``: a 50,000-game generation's ~14 GB do not fit in memory)."""
    games, logs = {}, {}
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in f.read_text().splitlines():
            g = json.loads(line)
            games[g["pair"]] = g
    for f in gen_dir.glob("logs-w*.jsonl"):
        with open(f) as fh:
            for line in fh:
                x = json.loads(line)
                logs[x["pair"]] = x["log"]
    return games, logs


def split_decisions(gen_dir: Path, shard_of: dict, tmp: Path) -> None:
    """The decisions, line by line, into ``tmp/<shard>.jsonl`` by their game's shard (the
    game id is read from the record's tail, ``"game": N``, without parsing the line)."""
    tmp.mkdir(parents=True, exist_ok=True)
    out: dict = {}
    try:
        for f in sorted(gen_dir.glob("decisions-w*.jsonl")):
            with open(f) as fh:
                for line in fh:
                    i = line.rfind('"game": ')
                    game = int(line[i + 8 : line.index(",", i)])
                    k = shard_of.get(game)
                    if k is None:
                        continue
                    if k not in out:
                        out[k] = open(tmp / f"{k:04d}.jsonl", "w")
                    out[k].write(line)
    finally:
        for fh in out.values():
            fh.close()


def convert_game(pair: int, game: dict, log: str, decisions: list, belief, gen: int,
                 stamp: int, stats: dict, per_game: int = 0) -> list[dict]:  # fmt: skip
    rows = []
    # battle tags repeat across servers (each numbers its own battles): the pair makes it unique
    row = {"id": f"sp{gen}-{pair}-{game['battle']}", "log": log, "rating": None,
           "uploadtime": stamp}  # fmt: skip
    # per_game > 0: that many decision points drawn per game (value data from many games, as
    # AlphaGo's value net; only those states are built: 2026-10-11, policy-only games)
    positions = positions_from_replay(row, belief, random.Random(pair), per_game=per_game,
                                      pool="all")  # fmt: skip
    # a key can hold several decisions in order (two forced switches in one turn: the first
    # switch-in fainted to hazards); matched to the positions in order
    by_key: dict = defaultdict(list)
    for d in decisions:
        by_key[(d["side"], d["turn"], d["kind"])].append(d)
    capped = bool(game.get("capped"))
    for p in positions:
        kind = KIND_MAIN if p.kind == KIND_BLIND else p.kind
        ds = by_key.get((p.side, p.turn, kind))
        d = ds.pop(0) if ds else None
        if d is None:
            stats["unmatched_positions"] += 1
            continue
        stats["matched"] += 1
        if p.action >= 0:  # the log shows the move: it must be the recorded one (by name: the
            # two states order moves / mons differently)
            stats["action_checked"] += 1
            logged = alpha_search.slot_names([p.state])[0][p.action]
            stats["action_agree"] += logged == d["names"][d["slot"]]
        x = asdict(p)
        total = sum(d["visits"]) or 1
        x.update({
            "state": d["state"], "history": d["history"], "reveal": d["reveal"],
            "rating_own": d["ratings"][0], "rating_opp": d["ratings"][1], "turn": d["ctx_turn"],
            "kind": kind, "action": d["slot"],
            "won": 0.5 if capped or d["won"] is None else float(d["won"]),
            "value_ok": 0.0 if capped or d["won"] is None else 1.0,
            "pi": [v / total for v in d["visits"]] if d["full"] else [0.0] * 14,
            "pi_w": 1.0 if d["full"] else 0.0, "q": d["q"], "weight": 1.0,
        })  # fmt: skip
        rows.append(x)
    stats["unmatched_decisions"] += sum(len(ds) for ds in by_key.values())
    return rows


def _convert_shard(args) -> dict:
    """One shard (its own process): the games' rows written to ``path``; returns the counts."""
    from alpha_poke.agents.belief_state import BeliefModel

    path, items, dec_file, gen, stamp, per_game = args
    belief = BeliefModel.load()
    stats: dict = defaultdict(int)
    decs = defaultdict(list)
    if dec_file.exists():
        with open(dec_file) as fh:
            for line in fh:
                d = json.loads(line)
                decs[d["game"]].append(d)
    rows = []
    for pair, game, log_text in items:
        decisions = decs.pop(pair, [])
        try:
            rows += convert_game(pair, game, log_text, decisions, belief, gen, stamp, stats,
                                 per_game)  # fmt: skip
            stats["games"] += 1
        except Exception:  # noqa: BLE001 - a broken log must not stop the conversion
            stats["failed_games"] += 1
    if rows:
        pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
    stats["positions"] += len(rows)
    return dict(stats)


def convert(gen_dir: Path, out_dir: Path, gen: int, shard_games: int = 500, log=print,
            procs: int = 10, per_game: int = 0) -> dict:  # fmt: skip
    """The generation's games in shards of ``shard_games``, ``procs`` shards at a time (each
    game has its own random seed: the same rows in any order)."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    games, logs = load_gen(gen_dir)
    stamp = int(time.time())
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs = sorted(p for p in games if p in logs)
    shard_of = {p: i // shard_games for i, p in enumerate(pairs)}
    tmp = out_dir / "decisions_tmp"
    split_decisions(gen_dir, shard_of, tmp)
    jobs = [(out_dir / f"shard-{k // shard_games:04d}.parquet",
             [(p, games[p], logs[p]) for p in pairs[k : k + shard_games]],
             tmp / f"{k // shard_games:04d}.jsonl", gen, stamp, per_game)
            for k in range(0, len(pairs), shard_games)]  # fmt: skip
    del logs
    stats: dict = defaultdict(int)
    # reproducible rows: the replay pipeline's results depend on set order (string hashing);
    # the spawned workers read the seed at start-up
    os.environ["PYTHONHASHSEED"] = "0"
    with ProcessPoolExecutor(max(1, min(procs, len(jobs))),
                             mp_context=mp.get_context("spawn")) as ex:  # fmt: skip
        for part in ex.map(_convert_shard, jobs):
            for k, v in part.items():
                stats[k] += v
    shutil.rmtree(tmp)
    stats = dict(stats)
    if stats.get("action_checked"):
        stats["action_agree_frac"] = round(stats["action_agree"] / stats["action_checked"], 4)
    (out_dir / "convert.json").write_text(json.dumps(stats, indent=1))
    log(f"{gen_dir} -> {out_dir}: {stats}")
    return stats
