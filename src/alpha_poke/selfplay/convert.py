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
import random
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


def load_gen(gen_dir: Path) -> tuple[dict, dict, dict]:
    """(games by pair, logs by pair, decisions by pair) of a generation directory."""
    games, logs, decs = {}, {}, defaultdict(list)
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in f.read_text().splitlines():
            g = json.loads(line)
            games[g["pair"]] = g
    for f in gen_dir.glob("logs-w*.jsonl"):
        for line in f.read_text().splitlines():
            x = json.loads(line)
            logs[x["pair"]] = x["log"]
    for f in gen_dir.glob("decisions-w*.jsonl"):
        for line in f.read_text().splitlines():
            d = json.loads(line)
            decs[d["game"]].append(d)
    return games, logs, decs


def convert_game(pair: int, game: dict, log: str, decisions: list, belief, gen: int,
                 stamp: int, stats: dict) -> list[dict]:  # fmt: skip
    rows = []
    # battle tags repeat across servers (each numbers its own battles): the pair makes it unique
    row = {"id": f"sp{gen}-{pair}-{game['battle']}", "log": log, "rating": None,
           "uploadtime": stamp}  # fmt: skip
    positions = positions_from_replay(row, belief, random.Random(pair), per_game=0, pool="all")
    by_key = {}
    for d in decisions:
        by_key.setdefault((d["side"], d["turn"], d["kind"]), d)
    capped = bool(game.get("capped"))
    for p in positions:
        kind = KIND_MAIN if p.kind == KIND_BLIND else p.kind
        d = by_key.pop((p.side, p.turn, kind), None)
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
    stats["unmatched_decisions"] += len(by_key)
    return rows


def convert(gen_dir: Path, out_dir: Path, gen: int, shard_games: int = 500, log=print) -> dict:
    from alpha_poke.agents.belief_state import BeliefModel

    games, logs, decs = load_gen(gen_dir)
    belief = BeliefModel.load()
    stamp = int(time.time())
    stats: dict = defaultdict(int)
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs = sorted(p for p in games if p in logs)
    for k in range(0, len(pairs), shard_games):
        rows = []
        for pair in pairs[k : k + shard_games]:
            try:
                rows += convert_game(pair, games[pair], logs[pair], decs.get(pair, []), belief,
                                     gen, stamp, stats)  # fmt: skip
                stats["games"] += 1
            except Exception:  # noqa: BLE001 - a broken log must not stop the conversion
                stats["failed_games"] += 1
        if rows:
            path = out_dir / f"shard-{k // shard_games:04d}.parquet"
            pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
        stats["positions"] += len(rows)
    stats = dict(stats)
    if stats.get("action_checked"):
        stats["action_agree_frac"] = round(stats["action_agree"] / stats["action_checked"], 4)
    (out_dir / "convert.json").write_text(json.dumps(stats, indent=1))
    log(f"{gen_dir} -> {out_dir}: {stats}")
    return stats
