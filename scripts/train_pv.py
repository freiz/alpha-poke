"""Train the policy / value network on replay positions (design D13).

Usage: uv run --group train python scripts/train_pv.py --data v1 --size medium --epochs 6

Input: data/train/<data>/*.parquet (scripts/build_training_data.py). The state strings are turned
into features by the Rust featurizer (alpha_search.featurize) once and cached next to them
(features/*.npz). Validation: the most recent ``--val-frac`` of the games (by upload time; whole
games, so no game is in both sets). Sample weights: 0.5 ** (age / --half-life days).

Monitoring (stdout and runs/<run>/metrics.jsonl): train policy CE / value BCE / policy accuracy /
grad norm / lr / samples per second; on validation: policy CE, top-1 / top-3, value BCE, value
accuracy, calibration error (ECE), value accuracy by game phase, against the baselines (uniform
over legal actions, value 0.5 -> BCE ln 2). Checkpoints: best (val loss) and last; weights are
exported as safetensors with a JSON config for the Rust inference later.
v2: ``--history`` feeds the decision-step history (data built with a ``history`` column), ``--arch
transformer`` the small Transformer; ``--value-per-game N`` scales each position's value loss so
that every game counts as at most N positions (many positions per game share one outcome).
``--mtp K`` (Transformer, data with a ``future`` column): auxiliary multi-step action prediction
over the first K decision steps from the position (design D13), weight ``--mtp-weight``.
v3 (design D13, data with a ``reveal`` column): ``--feats`` (reveal, num, movetab, matchup) and
``--aux`` (oppset, faint, turns; weight ``--aux-weight`` each) switch the new input groups
and auxiliary heads on (alpha_poke.train.model); the caches always hold all of them.
v4 (data with ``kind`` / ratings, design D13): ``--kinds`` picks the decision points to train on
(main = turn starts; forced / pivot switches; blind = a turn start whose action the log does not
show, trained with a partial label: some move slot, tera known); ``--elo-dropout`` hides each
player's rating with that probability in training. Evaluation: the usual metrics on the
turn-start positions only (comparable with v3), plus the forced / pivot switch accuracy.
``--stream K`` (data larger than memory, e.g. the full set: ~2.5 KB per position): only the small
columns of all shards stay in memory (splits and weights); the validation positions (at most
``--val-max``, random) are loaded once; training reads K whole shards at a time (Metamon's shards
are random in time), samples its batches there by time weight -- as many as the chunk's share of
the whole weight (the global half-life) -- and loads the next K shards in the background. Shard
order is reshuffled every pass.
"""

import argparse
import glob
import json
import math
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import alpha_search
import numpy as np
import pyarrow.parquet as pq
import torch
import torch.nn.functional as F

from alpha_poke.train.model import AUX_HEADS, FEATS, TransformerPV

T_SIZES = {
    "small": dict(d_model=96, n_layers=2, n_heads=4, d_ff=192),
    "medium": dict(d_model=128, n_layers=3, n_heads=4, d_ff=256),
    "large": dict(d_model=192, n_layers=4, n_heads=6, d_ff=384),
}
DIMS = alpha_search.feature_dims()
HDMG = [8, 15]  # history dense: own / opponent damage dealt (features.rs history_features)


# the most positions of one shard: featurization holds a whole shard in memory (~21 KB per
# position at its peak, 18.4 GB for 0.87M; 3.7M took 41.5 GB before the kill and, with the
# evaluation running, exhausted WSL's 48 GB: 2026-10-09), and the training reads a shard's columns
# whole from its cache. Metamon's shards hold <= 1.15M; bigger ones are split first
# (scripts/split_shards.py)
MAX_SHARD_ROWS = 1_200_000


def featurize_shard(path: Path, cache: Path) -> int:
    """Write the shard's feature cache (if missing); returns its number of positions."""
    names = pq.read_schema(path).names
    rows = pq.read_metadata(path).num_rows
    if rows > MAX_SHARD_ROWS:
        raise ValueError(f"{path}: {rows} positions > {MAX_SHARD_ROWS} (memory): split it with "
                         "scripts/split_shards.py")  # fmt: skip
    has_hist, has_fut, has_v3 = "history" in names, "future" in names, "reveal" in names
    if cache.exists():
        with np.load(cache) as z:
            # caches from before the handcrafted evaluation / the history are rebuilt
            fresh = cache.stat().st_mtime >= path.stat().st_mtime  # data rebuilt since?
            ok_hist = not has_hist or ("hsp" in z.files and z["hsp"].shape[1] == DIMS["hist"])
            ok_fut = not has_fut or "fsp" in z.files
            ok_v3 = not has_v3 or ("ent2" in z.files and z["ent2"].shape[2] == DIMS["ent_extra"])
            # v6: the counters (caches from before them are rebuilt)
            ok_v3 = ok_v3 and (not has_v3 or (
                "ent3" in z.files and "count_version" in z.files
                and (z["count_version"][:1] == DIMS["count_version"]).all()))  # fmt: skip
            # v7: the extras' version (benched matchups without the active's state), the v7
            # entity inputs, and the F2 posterior when the data has it
            ok_v3 = ok_v3 and (not has_v3 or (
                "ent4" in z.files and z["ent4"].shape[2] == DIMS["ent_new"]
                and "extra_version" in z.files
                and (z["extra_version"][:1] == DIMS["extra_version"]).all()
                and ("post" in names) == ("post" in z.files)))  # fmt: skip
            # v4: the damage columns (fractions) are kept apart as percents ("hdmg"); the first
            # v4 caches stored them in the uint8 "hde" and truncated them to 0
            hdmg_ok = DIMS["hist_dense"] == 7 or "hdmg" in z.files
            ok_hd = not has_hist or (z["hde"].shape[2] == DIMS["hist_dense"] and hdmg_ok)
            ok_v4 = ("kind" in names) == ("kind" in z.files) and ("weight" in names) == (
                "sw" in z.files
            )
            ok_sp = ("pi" in names) == ("pi" in z.files)  # self-play (design D15)
            if (fresh and "evalv" in z.files and ok_hist and ok_fut and ok_v3 and ok_hd and ok_v4
                    and ok_sp):  # fmt: skip
                return len(z["action"])
    cols = ["game", "turn", "state", "action", "won", "rating", "uploadtime"]
    extra = (["history"] if has_hist else []) + (["future"] if has_fut else [])
    if has_v3:
        extra += ["reveal", "opp_sets", "faint", "left_own", "left_opp", "turns"]
        extra += ["post"] if "post" in names else []
    if "kind" in names:
        extra += ["rating_own", "rating_opp", "kind"]
    if "weight" in names:
        extra += ["weight"]
    sp_cols = ["pi", "pi_w", "q", "value_ok"] if "pi" in names else []
    t = pq.read_table(path, columns=cols + extra + sp_cols)
    states = t.column("state").to_pylist()
    e, s, d, g, a = DIMS["entities"], DIMS["sparse"], DIMS["dense"], DIMS["global"], DIMS["actions"]
    parts = {"sparse": [], "dense": [], "glob": [], "mask": []}
    for i in range(0, len(states), 20_000):
        sp, de, gl, ma = alpha_search.featurize(states[i : i + 20_000])
        parts["sparse"].append(np.frombuffer(sp, np.int32).reshape(-1, e, s).astype(np.int16))
        parts["dense"].append(np.frombuffer(de, np.float32).reshape(-1, e, d).astype(np.float16))
        parts["glob"].append(np.frombuffer(gl, np.float32).reshape(-1, g).astype(np.float16))
        parts["mask"].append(np.frombuffer(ma, np.uint8).reshape(-1, a))
    out = {k: np.concatenate(v) for k, v in parts.items()}
    if has_hist:
        hist = t.column("history").to_pylist()
        hs, hd = DIMS["hist"], (DIMS["hist_sparse"], DIMS["hist_dense"])
        chunks = [alpha_search.featurize_history(hist[i : i + 50_000])
                  for i in range(0, len(hist), 50_000)]  # fmt: skip
        sp, de = [c[0] for c in chunks], [c[1] for c in chunks]
        out["hsp"] = np.concatenate(
            [np.frombuffer(x, np.int32).reshape(-1, hs, hd[0]).astype(np.int16) for x in sp]
        )
        out["hde"] = np.concatenate(
            [np.frombuffer(x, np.float32).reshape(-1, hs, hd[1]).astype(np.uint8) for x in de]
        )
        if hd[1] > 7:  # v4 outcomes: the damage dealt by each side, as percent
            out["hdmg"] = np.concatenate([
                (np.frombuffer(x, np.float32).reshape(-1, hs, hd[1])[..., HDMG] * 100).round()
                .astype(np.uint8) for x in de])  # fmt: skip
    if has_fut:  # same encoding; steps reversed so that slot k = future step k
        fut = [";".join(reversed(x.split(";"))) for x in t.column("future").to_pylist()]
        hs, hd = DIMS["hist"], (DIMS["hist_sparse"], DIMS["hist_dense"])
        chunks = [alpha_search.featurize_history(fut[i : i + 50_000])
                  for i in range(0, len(fut), 50_000)]  # fmt: skip
        out["fsp"] = np.concatenate([np.frombuffer(c[0], np.int32).reshape(-1, hs, hd[0])[:, :4]
                                     .astype(np.int16) for c in chunks])  # fmt: skip
        out["fde"] = np.concatenate([np.frombuffer(c[1], np.float32).reshape(-1, hs, hd[1])[:, :4]
                                     .astype(np.uint8) for c in chunks])  # fmt: skip
    if has_v3:
        out |= v3_arrays(t, states)
    out["evalv"] = np.concatenate(
        [np.asarray(alpha_search.evaluate(states[i : i + 50_000]), np.float32)
         for i in range(0, len(states), 50_000)]
    )  # fmt: skip
    if sp_cols:  # self-play: search visit distribution, its weight, root value, outcome known
        out["pi"] = np.asarray(t.column("pi").to_pylist(), np.float32)
        for k in ("pi_w", "q", "value_ok"):
            out[k] = np.asarray(t.column(k).to_pylist(), np.float32)
    out["action"] = np.asarray(t.column("action").to_pylist(), np.int64)
    out["won"] = np.asarray(t.column("won").to_pylist(), np.float32)
    out["turn"] = np.asarray(t.column("turn").to_pylist(), np.int32)
    out["uploadtime"] = np.asarray(t.column("uploadtime").to_pylist(), np.int64)
    out["game"] = np.asarray(
        [zlib.crc32(x.encode()) for x in t.column("game").to_pylist()], np.int64
    )
    act = out["action"].clip(0, a - 1)
    ok = (out["action"] < a) & (out["mask"][np.arange(len(act)), act] == 1)
    ok |= out["action"] < 0  # partial labels (v4 blind positions)
    out = {k: v[ok] for k, v in out.items()}
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(cache.stem + ".tmp.npz")  # atomic: a killed run leaves no broken cache
    np.savez(tmp, **out)
    tmp.rename(cache)
    return len(out["action"])


def v3_arrays(t, states: list[str]) -> dict:
    """v3 inputs (featurize_extra, reveal bits, turn), v6 counters (featurize_counts) and
    auxiliary targets of a shard."""
    e, g, e4 = DIMS["ent_extra"], DIMS["global_extra"], DIMS["ent_new"]
    ent, glob, new = [], [], []
    for i in range(0, len(states), 20_000):
        a, b, c = alpha_search.featurize_extra_full(states[i : i + 20_000])
        ent.append(np.frombuffer(a, np.float32).reshape(-1, 12, e).astype(np.float16))
        glob.append(np.frombuffer(b, np.float32).reshape(-1, g).astype(np.float16))
        new.append(np.frombuffer(c, np.float32).reshape(-1, 12, e4).astype(np.float16))
    out = {"ent2": np.concatenate(ent), "glob2": np.concatenate(glob),
           "ent4": np.concatenate(new),
           "extra_version": np.full(len(states), DIMS["extra_version"], np.uint8)}  # fmt: skip
    if "post" in t.column_names:  # F2: [12 * N_POST] per position (positions.py)
        # (stored x 255)
        out["post"] = (
            (np.asarray(t.column("post").to_pylist(), np.float32) / 255)
            .astype(np.float16)
            .reshape(-1, 12, DIMS["post"])
        )
    e3, g3 = DIMS["ent_count"], DIMS["global_count"]
    ent, glob = [], []
    for i in range(0, len(states), 50_000):
        a, b = alpha_search.featurize_counts(states[i : i + 50_000])
        ent.append(np.frombuffer(a, np.float32).reshape(-1, 12, e3).astype(np.float16))
        glob.append(np.frombuffer(b, np.float32).reshape(-1, g3).astype(np.float16))
    # per row (every loader takes rows of every array)
    out |= {"ent3": np.concatenate(ent), "glob3": np.concatenate(glob),
            "count_version": np.full(len(states), DIMS["count_version"], np.uint8)}  # fmt: skip
    out["reveal"] = np.asarray(t.column("reveal").to_pylist(), np.uint8).reshape(-1, 12)
    out["faint"] = np.asarray(t.column("faint").to_pylist(), np.uint8)
    own, opp = (np.asarray(t.column(c).to_pylist(), np.int8) for c in ("left_own", "left_opp"))
    out["margin"] = (own - opp).clip(-6, 6).astype(np.int8) + 6  # class 0..12
    out["turns"] = np.asarray(t.column("turns").to_pylist(), np.int16)
    # opponent sets as revealed by the end: per opponent entity item, ability, tera, 4 moves
    n = len(states)
    fields = {"item": [], "ability": [], "type": [], "move": []}
    for row in t.column("opp_sets").to_pylist():
        mons = (row.split(";") + [""] * 6)[:6]
        for m in mons:
            f = (m.split("|") + ["", "", "", ""])[:4]
            fields["item"].append(f[0])
            fields["ability"].append(f[1])
            fields["type"].append(f[2])
            fields["move"] += ((f[3].split(",") if f[3] else []) + [""] * 4)[:4]
    ids = {k: np.asarray(alpha_search.encode_ids(k, v), np.int16) for k, v in fields.items()}
    out["set_item"] = ids["item"].reshape(n, 6)
    out["set_ability"] = ids["ability"].reshape(n, 6)
    out["set_tera"] = ids["type"].reshape(n, 6)
    out["set_move"] = ids["move"].reshape(n, 6, 4)
    if "kind" in t.column_names:
        out["rating"] = np.stack([np.asarray(t.column(c).to_pylist(), np.int16)
                                  for c in ("rating_own", "rating_opp")], 1)  # fmt: skip
        out["kind"] = np.asarray(t.column("kind").to_pylist(), np.uint8)
    if "weight" in t.column_names:
        out["sw"] = np.asarray(t.column("weight").to_pylist(), np.float32)
    return out


# decision order within a turn (positions.KIND_*): the turn start, a pivot's switch, then the
# switches after faints (a blind turn start counts as a turn start)
def load(data: str) -> dict:
    """All shards in one set of arrays, filled shard by shard into preallocated arrays (peak
    memory = the result + one shard; concatenating would double it: 2026-10-06 OOM)."""
    root = Path("data/train") / data
    files = [f for f in sorted(glob.glob(str(root / "*.parquet"))) if pq.read_metadata(f).num_rows]
    caches = [root / "features" / (Path(f).stem + ".npz") for f in files]
    sizes = [featurize_shard(Path(f), c) for f, c in zip(files, caches, strict=True)]
    total = sum(sizes)
    out: dict = {}
    pos = 0
    for c, n in zip(caches, sizes, strict=True):
        if not n:
            continue
        with np.load(c) as z:
            for k in z.files:
                v = z[k]
                if k not in out:
                    out[k] = np.empty((total, *v.shape[1:]), v.dtype)
                out[k][pos : pos + n] = v
        pos += n
    return out


SMALL = ("game", "uploadtime", "kind", "sw", "turn")


def shard_caches(data: str) -> tuple[list[Path], list[int]]:
    """The shards' feature caches (built if missing) and their sizes."""
    root = Path("data/train") / data
    files = [f for f in sorted(glob.glob(str(root / "*.parquet"))) if pq.read_metadata(f).num_rows]
    caches = [root / "features" / (Path(f).stem + ".npz") for f in files]
    sizes = [featurize_shard(Path(f), c) for f, c in zip(files, caches, strict=True)]
    return [c for c, n in zip(caches, sizes, strict=True) if n], [n for n in sizes if n]


# self-play arrays of at least this many bytes per row go to a memory-mapped file (--sp-memmap)
MEMMAP_ROW_BYTES = 32


V3_KEYS = ("reveal", "ent2", "glob2", "ent3", "glob3", "ent4", "post", "turn", "faint", "turns",
           "set_item", "set_ability", "set_tera", "set_move", "rating", "kind")  # fmt: skip


def plan_selfplay(items: list[tuple[str, float]], per_game: int,
                  seed: int) -> tuple[list[tuple[Path, np.ndarray]], int]:  # fmt: skip
    """The self-play rows to train on (``load_selfplay``): [(shard cache, its kept rows)] and the
    positions before the per-game cap."""
    plan, n_before = [], 0
    for d_i, (name, keep) in enumerate(items):
        caches, sizes = shard_caches(name)
        for s_i, (c, n) in enumerate(zip(caches, sizes, strict=True)):
            with np.load(c) as z:
                game, pi_w = z["game"], z["pi_w"]
            idx = np.arange(n)
            if keep < 1:  # by game, hash digits independent of the validation split (% 1000)
                idx = idx[(game // 1000) % 1000 < keep * 1000]
            n_before += len(idx)
            if per_game > 0 and len(idx):
                key = np.random.default_rng([seed + 1, d_i, s_i]).random(len(idx))
                key += pi_w[idx] <= 0
                o = np.lexsort((key, game[idx]))
                g = game[idx][o]
                starts = np.r_[0, np.flatnonzero(g[1:] != g[:-1]) + 1]
                rank = np.arange(len(idx)) - np.repeat(starts, np.diff(np.r_[starts, len(idx)]))
                idx = np.sort(idx[o[rank < per_game]])
            plan.append((c, idx))
    return plan, n_before


def load_selfplay(items: list[tuple[str, float]], per_game: int, seed: int,
                  memmap_dir: Path | None = None) -> tuple[dict, int]:  # fmt: skip
    """Self-play datasets ``(name, share of games kept)`` in one set of arrays, at most
    ``per_game`` positions per game (those with a policy target first, in random order), the
    cap applied shard by shard (a game is in one shard) on the small columns, then the kept rows
    filled shard by shard into preallocated arrays: peak memory = the kept rows + one shard
    (2026-10-10: ~6.3M positions after gen 4 no longer fit in memory twice). ``memmap_dir``: the
    large arrays (the network inputs)
    in memory-mapped .npy files there instead of memory (2026-10-11: a generation of 100,000
    games would be ~19 GB of arrays; mapped, they live in the page cache, which the kernel can
    reclaim under the memory cap; same rows, same order: training is unchanged). Returns
    (arrays, positions before the cap)."""
    plan, n_before = plan_selfplay(items, per_game, seed)
    total = sum(len(i) for _, i in plan)
    out: dict = {}
    pos = 0
    for c, idx in plan:
        if not len(idx):
            continue
        with np.load(c) as z:
            for k in z.files:
                v = z[k]
                if k not in out:
                    shape = (total, *v.shape[1:])
                    if memmap_dir is not None and v[:1].nbytes >= MEMMAP_ROW_BYTES:
                        out[k] = np.lib.format.open_memmap(memmap_dir / f"{k}.npy", mode="w+",
                                                           dtype=v.dtype, shape=shape)  # fmt: skip
                    else:  # (zeros: a key an earlier shard lacks -- post -- reads 0 there)
                        out[k] = np.zeros(shape, v.dtype)
                out[k][pos : pos + len(idx)] = v[idx]
        pos += len(idx)
    for v in out.values():  # written back: clean pages the kernel can drop and re-read
        if isinstance(v, np.memmap):
            v.flush()
    return out, n_before


SP_SMALL = ("game", "pi_w", "value_ok")


def selfplay_small(plan) -> tuple[list[Path], dict]:
    """--sp-stream: the kept self-play rows' small columns (SP_SMALL) and each row's shard and row
    (``gather``), from ``plan_selfplay``'s plan."""
    plan = [(c, idx) for c, idx in plan if len(idx)]
    out: dict = {"shard": np.repeat(np.arange(len(plan)), [len(i) for _, i in plan]),
                 "row": np.concatenate([i for _, i in plan])}  # fmt: skip
    parts: dict = {k: [] for k in SP_SMALL}
    for c, idx in plan:
        with np.load(c) as z:
            for k in SP_SMALL:
                parts[k].append(z[k][idx])
    out |= {k: np.concatenate(v) for k, v in parts.items()}
    return [c for c, _ in plan], out


class SpStream:
    """--sp-stream R (self-play data larger than memory: 2026-10-15, all 8 generations = 15.9M
    positions, 42 GB memory-mapped, read randomly from disk at 1/30 of the speed): batches from
    chunks of about R train rows (whole shards, reshuffled every pass), every train row once per
    pass in a random order (a short last batch filled with other rows of the chunk); the next
    chunk loads in a background thread. ``value_rows`` (--sp-value-schedule spread): every one of
    these rows' outcomes goes to ``value_passes`` random passes, and in that pass's chunk it is
    spread evenly over the chunk's steps. ``next()``: (chunk data, policy rows local / global,
    value rows local / global)."""

    def __init__(self, caches, small, train_idx, rows: int, batch: int, passes: int, rng,
                 value_rows=None, value_passes: int = 1):  # fmt: skip
        self.caches, self.small, self.batch, self.rng = caches, small, batch, rng
        shard = small["shard"][train_idx]
        o = np.argsort(shard, kind="stable")
        bounds = np.flatnonzero(np.diff(shard[o])) + 1
        by_shard = np.split(train_idx[o], bounds)
        self.chunks: list = []  # (pass, global rows)
        for p in range(passes):
            cur, n = [], 0
            for s in rng.permutation(len(by_shard)):
                cur.append(by_shard[s])
                n += len(by_shard[s])
                if n >= rows:
                    self.chunks.append((p, np.concatenate(cur)))
                    cur, n = [], 0
            if cur:
                self.chunks.append((p, np.concatenate(cur)))
        self.vpass = None
        if value_rows is not None:  # each valued row's passes, as a bit mask
            self.vpass = np.zeros(len(small["shard"]), np.int64)
            for v in value_rows:
                pick = rng.choice(passes, min(value_passes, passes), replace=False)
                self.vpass[v] |= int(sum(1 << int(q) for q in pick))
        self.steps = sum(-(-len(r) // batch) for _, r in self.chunks)
        self.pool = ThreadPoolExecutor(1)
        self.i = 0
        self.next_chunk = self.pool.submit(self._load, 0)
        self.left = 0

    def _load(self, i: int):
        p, glob_rows = self.chunks[i]
        glob_rows = glob_rows[np.argsort(self.small["shard"][glob_rows], kind="stable")]
        return p, glob_rows, gather(self.caches, self.small, glob_rows)

    def _advance(self):
        p, self.glob_rows, self.data = self.next_chunk.result()
        self.i += 1
        if self.i < len(self.chunks):
            self.next_chunk = self.pool.submit(self._load, self.i)
        n = len(self.glob_rows)
        self.left = -(-n // self.batch)
        perm = self.rng.permutation(n)
        fill = self.rng.choice(n, self.left * self.batch - n)
        self.order = np.concatenate([perm, fill]).reshape(self.left, self.batch)
        self.k = 0
        if self.vpass is not None:
            v = np.flatnonzero((self.vpass[self.glob_rows] >> p) & 1)
            self.vsplit = np.array_split(self.rng.permutation(v), self.left)

    def next(self):
        if self.left == 0:
            self._advance()
        b = self.order[self.k]
        bv = self.vsplit[self.k] if self.vpass is not None else b[:0]
        self.k += 1
        self.left -= 1
        return self.data, b, self.glob_rows[b], bv, self.glob_rows[bv]


def load_small(caches: list[Path], sizes: list[int]) -> dict:
    """The small columns (SMALL) of all shards + each row's shard and row number."""
    out: dict = {"shard": np.repeat(np.arange(len(sizes)), sizes),
                 "row": np.concatenate([np.arange(n) for n in sizes])}  # fmt: skip
    for k in SMALL:
        parts = []
        for c in caches:
            with np.load(c) as z:
                if k not in z.files:
                    break
                parts.append(z[k])
        if len(parts) == len(caches):
            out[k] = np.concatenate(parts)
    return out


def gather(caches: list[Path], small: dict, idx: np.ndarray) -> dict:
    """All columns of the rows ``idx`` (global), read shard by shard."""
    out: dict = {}
    order = np.argsort(small["shard"][idx], kind="stable")
    idx = idx[order]
    pos = 0
    for s_id in np.unique(small["shard"][idx]):
        rows = small["row"][idx[small["shard"][idx] == s_id]]
        with np.load(caches[s_id]) as z:
            for k in z.files:
                v = z[k][rows]
                if k not in out:  # (zeros: a key another shard lacks)
                    out[k] = np.zeros((len(idx), *v.shape[1:]), v.dtype)
                out[k][pos : pos + len(rows)] = v
        pos += len(rows)
    return out


class ChunkStream:
    """Batches from K shards at a time (see --stream): yields (chunk data, local rows, global
    rows); the next chunk loads in a background thread."""

    def __init__(self, caches, small, train_idx, probs_w, k, batch, rng):
        self.caches, self.small, self.k, self.batch, self.rng = caches, small, k, batch, rng
        self.train = np.zeros(len(small["shard"]), bool)
        self.train[train_idx] = True
        self.w = np.zeros(len(small["shard"]))
        self.w[train_idx] = probs_w
        self.w_total, self.n_train = float(self.w.sum()), len(train_idx)
        self.pool = ThreadPoolExecutor(1)
        self.order: list = []
        self.next = self.pool.submit(self._load, self._next_shards())
        self._advance()

    def _next_shards(self) -> list[int]:
        if len(self.order) < self.k:
            self.order += list(self.rng.permutation(len(self.caches)))
        out, self.order = self.order[: self.k], self.order[self.k :]
        return out

    def _load(self, shards):
        glob_rows = np.flatnonzero(np.isin(self.small["shard"], shards) & self.train)
        return glob_rows, gather(self.caches, self.small, glob_rows)

    def _advance(self):
        self.glob_rows, self.chunk = self.next.result()
        # gather sorts by shard: map its row order back to the global ids
        order = np.argsort(self.small["shard"][self.glob_rows], kind="stable")
        self.glob_rows = self.glob_rows[order]
        self.next = self.pool.submit(self._load, self._next_shards())
        w = self.w[self.glob_rows]
        self.p = w / w.sum()
        # the chunk's steps by its share of the whole time weight (a pass: n_train / batch
        # steps; randomly rounded, 0 skips it): a row's chance is then its global weight. Before,
        # by its rows (2026-10-23 review): a chunk of old games trained as long as one of new ones
        # and the half-life held within a chunk only (the hf- shards ~23% of the batches, 43.5% by
        # weight)
        exp = w.sum() / self.w_total * self.n_train / self.batch
        self.left = int(exp) + int(self.rng.random() < exp - int(exp))
        self.block, self.used = None, 0

    def batch_rows(self):
        while self.left == 0:
            self._advance()
        if self.block is None or self.used == len(self.block):
            m = min(1000, self.left)
            self.block = self.rng.choice(len(self.glob_rows), (m, self.batch), p=self.p)
            self.used = 0
        b = self.block[self.used]
        self.used += 1
        self.left -= 1
        return self.chunk, b, self.glob_rows[b]


def to_torch(d: dict, idx: np.ndarray, device) -> tuple:
    """(sparse, dense, glob, mask, action, won, handcrafted eval / 100, history sparse, history
    dense); the history is None without a history in the data"""
    hist = (None, None)
    if "hsp" in d:
        hde = d["hde"][idx].astype(np.float32)
        if "hdmg" in d:
            hde[..., HDMG] = d["hdmg"][idx] / 100
        hist = (torch.from_numpy(d["hsp"][idx].astype(np.int64)).to(device, non_blocking=True),
                torch.from_numpy(hde).to(device, non_blocking=True))  # fmt: skip
    fut = (
        (torch.from_numpy(d["fsp"][idx].astype(np.int64)).to(device, non_blocking=True),
         torch.from_numpy(d["fde"][idx].astype(np.float32)).to(device, non_blocking=True))
        if "fsp" in d else (None, None)
    )  # fmt: skip
    x = None
    if "ent2" in d:
        x = {}
        for k in (k for k in V3_KEYS if k in d):
            v = d[k][idx]
            v = v.astype(np.float32) if v.dtype == np.float16 else v.astype(np.int64)
            x[k] = torch.from_numpy(v).to(device, non_blocking=True)
    return (
        torch.from_numpy(d["sparse"][idx].astype(np.int64)).to(device, non_blocking=True),
        torch.from_numpy(d["dense"][idx].astype(np.float32)).to(device, non_blocking=True),
        torch.from_numpy(d["glob"][idx].astype(np.float32)).to(device, non_blocking=True),
        torch.from_numpy(d["mask"][idx].astype(bool)).to(device, non_blocking=True),
        torch.from_numpy(d["action"][idx]).to(device, non_blocking=True),
        torch.from_numpy(d["won"][idx]).to(device, non_blocking=True),
        torch.from_numpy(d["evalv"][idx] / 100).to(device, non_blocking=True),
        *hist,
        *fut,
        x,
    )


def mtp_targets(sp, fs, fd, k: int):
    """Targets of the first k future steps, side 0 = own / 1 = opponent: kind (0 none, 1 move,
    2 switch), move id, switch-in entity index (+ whether it matched an entity), valid mask (step
    present; own step 0 excluded: it is the policy label)."""
    fs, fd = fs[:, :k], fd[:, :k]
    kind = torch.stack([fd[..., 1] + 2 * fd[..., 2], fd[..., 4] + 2 * fd[..., 5]], 2).long()
    move_id = torch.stack([fs[..., 1], fs[..., 4]], 2)
    species = torch.stack([fs[..., 2], fs[..., 5]], 2)
    ents = torch.stack([sp[:, :6, 0], sp[:, 6:12, 0]], 1)  # [B,2,6]
    match = species[..., None] == ents[:, None]  # [B,k,2,6]
    valid = (fd[..., 0] > 0)[..., None].expand(-1, -1, 2).clone()
    valid[:, 0, 0] = False
    return kind, move_id, match.float().argmax(-1), match.any(-1), valid


def opp_topk(aux, targets, k: int) -> float:
    """Hits of the opponent's step-0 action among the k most likely of the joint distribution
    over none / each move / each switch-in (log P(kind) + log P(target | kind))."""
    kl, ml, sl = (x[:, 0, 1].float() for x in aux)
    kind, move_id, sw_idx, sw_ok, valid = (x[:, 0, 1] for x in targets)
    lk = kl.log_softmax(-1)
    joint = torch.cat([lk[:, :1], lk[:, 1:2] + ml.log_softmax(-1), lk[:, 2:3] + sl.log_softmax(-1)],
                      dim=-1)  # fmt: skip
    nm = ml.shape[-1]
    target = torch.where(kind == 1, 1 + move_id, torch.where(kind == 2, 1 + nm + sw_idx, 0))
    ok = valid & ~((kind == 2) & ~sw_ok)
    hit = (joint.topk(k, dim=-1).indices == target[:, None]).any(-1)
    return hit[ok].float().sum().item()


def mtp_loss(aux, targets, decay: float = 1.0) -> tuple:
    """(loss, opponent step-0 action accuracy, its count); step k weighs decay ** k"""
    kl, ml, sl = (x.float() for x in aux)
    kind, move_id, sw_idx, sw_ok, valid = targets
    k = kl.shape[1]
    w = (decay ** torch.arange(k, device=kl.device, dtype=torch.float32))[None, :, None]
    w = w.expand_as(valid)
    # joint NLL of each (step, side) action: -log P(kind) - log P(move | move) - log P(switch-in
    # | switch), averaged over the same valid targets (a proper likelihood, not 1:1:1 averages)
    nll = (F.cross_entropy(kl[valid], kind[valid], reduction="none") * w[valid]).sum()
    mm = valid & (kind == 1) & (move_id > 0)
    if mm.any():
        nll = nll + (F.cross_entropy(ml[mm], move_id[mm], reduction="none") * w[mm]).sum()
    ss = valid & (kind == 2) & sw_ok
    if ss.any():
        nll = nll + (F.cross_entropy(sl[ss], sw_idx[ss], reduction="none") * w[ss]).sum()
    loss = nll / w[valid].sum().clamp(min=1e-6)
    o = valid[:, 0, 1]
    pk = kl[:, 0, 1].argmax(-1)
    k0, m0, s0 = kind[:, 0, 1], move_id[:, 0, 1], sw_idx[:, 0, 1]
    ok = (pk == k0) & ((k0 == 0) | ((k0 == 1) & (ml[:, 0, 1].argmax(-1) == m0))
                       | ((k0 == 2) & sw_ok[:, 0, 1] & (sl[:, 0, 1].argmax(-1) == s0)))  # fmt: skip
    return loss, ok[o].float().sum().item(), o.sum().item()


def aux_loss(out: dict, x: dict, sp, turn, bw, heads, stats: dict | None = None):
    """Mean of the auxiliary heads' losses (each head weighs 1; game-level targets -- margin,
    turns -- use the value loss weights ``bw``). With ``stats`` (evaluation) also accumulates
    metric sums, the opponent-set ones on the fields not yet revealed at the position, against
    the belief sample in the state."""
    losses = []

    def add(k: str, v: float) -> None:
        stats[k] = stats.get(k, 0) + v

    if "oppset" in heads:
        exists = sp[:, 6:12, 0] > 0
        bits = (x["reveal"][:, 6:12, None] >> torch.arange(8, device=sp.device)) & 1  # [B,6,8]
        terms = []
        for key, col, bit in (("item", 1, 1), ("ability", 2, 2), ("tera", 3, 3)):
            lab, lg = x[f"set_{key}"], out[f"set_{key}"].float()
            ok = exists & (lab > 0)
            if ok.any():
                terms.append(F.cross_entropy(lg[ok], lab[ok]))
            if stats is not None:
                hid = ok & (bits[..., bit] == 0)
                add(f"n_{key}", hid.sum().item())
                add(f"net_{key}", (lg.argmax(-1) == lab)[hid].sum().item())
                add(f"belief_{key}", (sp[:, 6:12, col] == lab)[hid].sum().item())
        lab, lg = x["set_move"], out["set_move"].float()  # [B,6,4], [B,6,V]
        ok = exists[..., None] & (lab > 0)
        if ok.any():
            lp = lg.log_softmax(-1).gather(-1, lab)  # [B,6,4]
            terms.append(-lp[ok].mean())
        if stats is not None:
            st_moves = sp[:, 6:12, 6:10]  # the world's moves; the revealed ones flagged
            rev = bits[..., 4:8].bool() & (st_moves > 0)
            n_rev = rev.sum(-1, keepdim=True)  # [B,6,1]
            masked = lg.scatter(-1, st_moves * rev, float("-inf"))  # revealed moves out
            masked[..., 0] = float("-inf")
            is_rev = ((lab[..., :, None] == st_moves[..., None, :]) & rev[..., None, :]).any(-1)
            hid = ok & ~is_rev  # label moves not revealed yet
            score = masked.gather(-1, lab)
            rank = (masked[..., None, :] > score[..., None]).sum(-1)  # [B,6,4]
            net_hit = rank < (4 - n_rev)
            sampled = st_moves[..., None, :] == lab[..., None]  # [B,6,4(label),4(slot)]
            belief_hit = (sampled & ~rev[..., None, :]).any(-1)
            add("n_move", hid.sum().item())
            add("net_move", net_hit[hid].sum().item())
            add("belief_move", belief_hit[hid].sum().item())
        if terms:
            losses.append(torch.stack(terms).mean())
    if "faint" in heads:
        y = torch.stack([(x["faint"] & 1), (x["faint"] >> 1) & 1], -1).float()
        lg = out["faint"].float()
        losses.append(F.binary_cross_entropy_with_logits(lg, y))
        if stats is not None:
            add("faint_bce", F.binary_cross_entropy_with_logits(lg, y, reduction="sum").item() / 2)
            add("faint_acc", ((lg > 0) == y.bool()).float().mean(-1).sum().item())
    if "turns" in heads:
        y = torch.log1p((x["turns"] - turn).clamp(min=0).float())
        pred = out["turns"].float()
        # (clamped: a batch of capped self-play games only has no remaining-turns label -- all
        # weights 0, 0 / 0 = NaN into the gradients, 2026-10-22 review; now 0)
        losses.append(
            (F.smooth_l1_loss(pred, y, reduction="none") * bw).sum() / bw.sum().clamp_min(1e-6)
        )
        if stats is not None:
            add("turns_mae", (torch.expm1(pred.clamp(max=6)) - torch.expm1(y)).abs().sum().item())
    return torch.stack(losses).mean() if losses else torch.zeros((), device=sp.device)


def policy_loss(logits, act, mask, reduction="mean"):
    """Cross-entropy; a negative action is a partial label (v4 blind positions: -1 some move slot
    without tera, -2 with tera): -log of the probability of that set of legal slots."""
    logits = logits.float()
    full = act >= 0
    ce = torch.zeros(len(act), device=logits.device)
    if full.any():
        ce[full] = F.cross_entropy(logits[full], act[full], reduction="none")
    part = ~full
    if part.any():
        slots = torch.arange(logits.shape[1], device=logits.device)
        tera = (act[part] == -2)[:, None]
        allowed = mask[part] & torch.where(tera, (slots >= 4) & (slots < 8), slots < 4)
        num = logits[part].masked_fill(~allowed, float("-inf")).logsumexp(-1)
        nll = logits[part].logsumexp(-1) - num
        ce[part] = torch.where(allowed.any(-1), nll, torch.zeros_like(nll))
    return ce.mean() if reduction == "mean" else ce


def soft_policy_loss(logits, pi, mask):
    """Cross-entropy with a target distribution (self-play: the search's visits): -sum pi log p
    over the legal slots (= KL(pi || p) + the target's entropy), per position."""
    logp = torch.log_softmax(logits.float().masked_fill(~mask, float("-inf")), -1)
    return -(pi * logp.masked_fill(~mask, 0.0)).sum(-1)


@torch.no_grad()
def evaluate_sp(model, d, idx, device, vpg: float, batch=8192, ref=None) -> dict:
    """Self-play validation: policy CE / KL against the search's visits (full searches),
    agreement of the net's top choice with the most visited, value BCE (games with an outcome),
    the root value q as a value baseline; the remaining-turns head's error (games that ended)."""
    model.eval()
    ce = kl = top = n_pi = bce = bce_q = n_v = kl_ref = t_err = n_t = 0.0
    turns_head = "turns" in getattr(model, "aux_heads", ())
    for i in range(0, len(idx), batch):
        b = idx[i : i + batch]
        sp, de, gl, ma, act, won, ev, hs, hd, fs, fd, x = to_torch(d, b, device)
        kw = {"x": x} if x is not None else {}
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            out = model(sp, de, gl, ma, hs, hd, aux=turns_head, **kw)
        logits, v = out[0], out[1]
        if turns_head:
            ended = torch.from_numpy(d["value_ok"][b]).to(device) * (won != 0.5)
            left = (x["turns"] - x["turn"]).clamp(min=0).float()
            pred = torch.expm1(out[3]["turns"].float().clamp(max=6))
            t_err += ((pred - left).abs() * ended).sum().item()
            n_t += ended.sum().item()
        pi = torch.from_numpy(d["pi"][b]).to(device)
        pw = torch.from_numpy(d["pi_w"][b]).to(device)
        c = soft_policy_loss(logits, pi, ma)
        if ref is not None:
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                rlp = _logp(ref(sp, de, gl, ma, hs, hd, **kw)[0], ma)
            kl_ref += _kl(rlp, _logp(logits, ma), ma).sum().item()
        ent = -(pi * torch.log(pi.clamp_min(1e-12))).sum(-1)
        ce += (c * pw).sum().item()
        kl += ((c - ent) * pw).sum().item()
        top += ((logits.float().argmax(-1) == pi.argmax(-1)).float() * pw).sum().item()
        n_pi += pw.sum().item()
        ok = torch.from_numpy(d["value_ok"][b]).to(device)
        vl = value_logit(model, v.float(), ev)
        bce += (F.binary_cross_entropy_with_logits(vl, won, reduction="none") * ok).sum().item()
        q = torch.from_numpy(d["q"][b]).to(device).clamp(1e-4, 1 - 1e-4)
        bce_q += (F.binary_cross_entropy(q, won, reduction="none") * ok).sum().item()
        n_v += ok.sum().item()
    model.train()
    return {"sp_ce": ce / max(n_pi, 1), "sp_kl": kl / max(n_pi, 1),
            "sp_top1": top / max(n_pi, 1), "sp_bce": bce / max(n_v, 1),
            "sp_bce_rootq": bce_q / max(n_v, 1), "sp_val_pi": n_pi, "sp_val_v": n_v,
            "sp_kl_ref": kl_ref / max(len(idx), 1),
            **({"sp_turns_mae": t_err / max(n_t, 1)} if turns_head else {})}  # fmt: skip


def value_logit(model, v, ev):
    """Residual value (--value-residual): a * handcrafted eval / 100 + b + the net's output."""
    if getattr(model, "residual", None) is None:
        return v
    return model.residual[0] * ev + model.residual[1] + v


def _logp(logits, mask):
    return torch.log_softmax(logits.float().masked_fill(~mask, float("-inf")), -1)


def _kl(ref_logp, logp, mask):
    """KL(ref || cur) per position over the legal slots."""
    p = ref_logp.exp()
    return (p * (ref_logp - logp)).masked_fill(~mask, 0.0).sum(-1)


@torch.no_grad()
def evaluate_drift(model, ref, d, idx, device, n_max=100_000, batch=8192) -> dict:
    """How the policy moved on human positions (design D15-6), on turn starts with a visible
    action (at most ``n_max``): cross-entropy of the human's move with the player's real rating
    as input (``hce_true``; the net should still imitate a rating-r human) and with the rating
    unknown (``hce_unk``, the input self-play uses), by rating band (true rating); with ``ref``
    (the run's starting point, frozen) KL(start || now) of the policies with each rating input."""
    if "kind" in d:
        idx = idx[d["kind"][idx] == 0]
    idx = idx[d["action"][idx] >= 0][:n_max]
    sums: dict = {}
    amp = dict(dtype=torch.bfloat16, enabled=device.type == "cuda")
    model.eval()

    def add(k, v):
        sums[k] = sums.get(k, 0.0) + float(v)

    for i in range(0, len(idx), batch):
        b = idx[i : i + batch]
        sp, de, gl, ma, act, won, ev, hs, hd, fs, fd, x = to_torch(d, b, device)
        own = x["rating"][:, 0]
        bands = {"lt1300": (own > 0) & (own < 1300), "1300_1600": (own >= 1300) & (own < 1600),
                 "ge1600": own >= 1600}  # fmt: skip
        for mode in ("true", "unk"):
            xx = dict(x)
            if mode == "unk":
                xx["rating"] = torch.zeros_like(x["rating"])
            with torch.autocast(device.type, **amp):
                lp = _logp(model(sp, de, gl, ma, hs, hd, x=xx)[0], ma)
            ce = -lp.gather(1, act[:, None])[:, 0]
            add(f"hce_{mode}", ce.sum())
            if mode == "true":
                for name, sel in bands.items():
                    add(f"hce_{name}", ce[sel].sum())
                    add(f"n_{name}", sel.sum())
            if ref is not None:
                with torch.autocast(device.type, **amp):
                    rlp = _logp(ref(sp, de, gl, ma, hs, hd, x=xx)[0], ma)
                add(f"kl_ref_{mode}", _kl(rlp, lp, ma).sum())
    model.train()
    n = max(len(idx), 1)
    out = {k: v / n for k, v in sums.items() if k in ("hce_true", "hce_unk")
           or k.startswith("kl_ref")}  # fmt: skip
    for name in ("lt1300", "1300_1600", "ge1600"):
        if sums.get(f"n_{name}"):
            out[f"hce_{name}"] = sums[f"hce_{name}"] / sums[f"n_{name}"]
    return out


@torch.no_grad()
def evaluate(model, d, idx, device, batch=16384) -> dict:
    """Metrics on the turn-start positions of ``idx`` with a visible action (comparable with v3);
    v4 data, over all its decision points: forced / pivot switch accuracy (``*_forced``), the
    policy loss over all turn starts (``ce_turn``: the unseen choices with their partial label;
    the visible ones alone are a biased sample, they miss the turns where the player was KOed
    first or could not move, which always chose a move), value BCE on all positions
    (``bce_all``) and on the unseen-choice ones (``bce_blind``); with sampling weights in the
    data also ``ce_turn_w`` / ``bce_all_w`` weighted by them (the selection metric)."""
    if "kind" not in d:
        return _evaluate(model, d, idx, device, batch)
    k = d["kind"][idx]
    out = _evaluate(model, d, idx[k == 0], device, batch)
    v3 = getattr(model, "feats", None) is not None
    amp = dict(dtype=torch.bfloat16, enabled=device.type == "cuda")
    pl, vl, hit = [], [], []
    model.eval()
    for i in range(0, len(idx), batch):
        b = idx[i : i + batch]
        sp, de, gl, ma, act, won, ev, hs, hd, fs, fd, x = to_torch(d, b, device)
        with torch.autocast(device.type, **amp):
            o = model(sp, de, gl, ma, hs, hd, **({"x": x} if v3 else {}))
        lg = o[0].float()
        pl.append(policy_loss(lg, act, ma, reduction="none").cpu().numpy())
        v = value_logit(model, o[1].float(), ev)
        vl.append(F.binary_cross_entropy_with_logits(v, won, reduction="none").cpu().numpy())
        hit.append((lg.argmax(-1) == act).cpu().numpy())
    model.train()
    pl, vl, hit = np.concatenate(pl), np.concatenate(vl), np.concatenate(hit)
    sw, turn, blind = (k == 1) | (k == 2), (k == 0) | (k == 3), k == 3
    if sw.any():
        out |= {"ce_forced": float(pl[sw].mean()), "top1_forced": float(hit[sw].mean())}
    out |= {"ce_turn": float(pl[turn].mean()), "bce_all": float(vl.mean())}
    if "sw" in d:  # weighted by the sampling weights: the game's real mix of decision points
        w = d["sw"][idx]
        out |= {"ce_turn_w": float(np.average(pl[turn], weights=w[turn])),
                "bce_all_w": float(np.average(vl, weights=w))}  # fmt: skip
    if blind.any():
        out |= {"ce_blind": float(pl[blind].mean()), "bce_blind": float(vl[blind].mean())}
    if "ent3" in d:  # v6: the positions where the counters say something (``count_active``)
        act = count_active(d, idx)
        if act.any():
            out |= {"count_frac": float(act.mean()), "bce_count": float(vl[act].mean())}
            if (act & turn).any():
                out["ce_count"] = float(pl[act & turn].mean())
    # v7: the positions each new group speaks to (v7_subsets), their policy / value losses
    acts = d["action"][idx]
    for name, sub in v7_subsets(d, idx, acts).items():
        if sub.any():
            out[f"{name}_frac"] = float(sub.mean())
            out[f"bce_{name}"] = float(vl[sub].mean())
            if (sub & turn).any():
                out[f"ce_{name}"] = float(pl[sub & turn].mean())
                out[f"top1_{name}"] = float(hit[sub & turn].mean())
    return out


def v7_subsets(d: dict, idx: np.ndarray, acts: np.ndarray) -> dict[str, np.ndarray]:
    """(v7 acceptance, design: feature candidates) the positions where a v7 group says something:
    ko2 -- our active has a two-hit KO but no one-hit KO, or a priority KO is on; tera -- our side
    can still terastallize; tera_used -- the player terastallized (its action); team -- the late
    game (six mons or fewer left in all); post -- the belief worlds disagree on our active's
    consequences (faster, KOed, KOs, safe switch-in, priority KO: between 0.1 and 0.9)."""
    out = {}
    own_active = d["dense"][idx][:, :6, 2] > 0.5
    if "ent4" in d:
        e4 = d["ent4"][idx].astype(np.float32)
        k2, kt = DIMS["ent_ko2"], DIMS["ent_tera"]
        own = (e4[:, :6] * own_active[..., None]).sum(1)  # our active's v7 columns
        ko2_any = own[:, 1:8:2].max(1) > 0.5  # some move 2HKOs possibly
        ent2 = d["ent2"][idx].astype(np.float32)
        ohko_any = ((ent2[:, :6, 6:20:4] * own_active[..., None]).sum(1) > 0.5).any(1)
        prio = (e4[:, :, 8:10] > 0.5).any((1, 2))
        out["ko2"] = (ko2_any & ~ohko_any) | prio
        out["tera"] = own[:, k2 + kt - 2] > 0.5  # our side can still terastallize
        out["tera_used"] = (acts >= 4) & (acts < 8)
        alive = d["dense"][idx][:, :, 1] > 0.5
        out["team"] = alive.sum(1) <= 6  # the late game
    if "post" in d:
        pst = d["post"][idx].astype(np.float32)
        key = (pst[:, :6, :5] * own_active[..., None]).sum(1)  # our active's consequences
        out["post"] = ((key > 0.1) & (key < 0.9)).any(1)
    return out


def count_active(d: dict, idx: np.ndarray) -> np.ndarray:
    """Positions whose v6 counters are not all at their default: a side counter (protects,
    substitute, Wish, Future Sight, volatile turns), a disabled move, sleep turns, or a move of
    the own active with 4 PP or fewer left."""
    e3, g3 = d["ent3"][idx], d["glob3"][idx]
    on = (g3 != 0).any(1) | (e3[:, :, 4:10] != 0).any((1, 2))
    own_active = d["dense"][idx][:, :6, 2] > 0.5
    pp = e3[:, :6, 0:4].astype(np.float32)
    low = ((pp > 0) & (pp <= 0.25) & own_active[..., None]).any((1, 2))
    return on | low


def _evaluate(model, d, idx, device, batch=16384) -> dict:
    model.eval()
    sums = dict(ce=0.0, top1=0.0, top2=0.0, top3=0.0, top5=0.0, bce=0.0, vacc=0.0,
                uniform_ce=0.0, n_sw=0.0, top1_sw=0.0, top3_sw=0.0, ce_sw=0.0)  # fmt: skip
    mtp = getattr(model, "mtp", 0) and "fsp" in d
    heads = getattr(model, "aux_heads", ())
    v3 = "ent2" in d and getattr(model, "feats", None) is not None
    a_stats: dict = {}
    m_sum = dict(loss=0.0, acc=0.0, acc3=0.0, n=0.0, b=0)
    probs, wons, turns = [], [], []
    for i in range(0, len(idx), batch):
        b = idx[i : i + batch]
        sp, de, gl, ma, act, won, ev, hs, hd, fs, fd, x = to_torch(d, b, device)
        kw = {"x": x} if v3 else {}
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            out = model(sp, de, gl, ma, hs, hd, aux=bool(mtp or heads), **kw)
        if heads:
            aux_loss(out[3], x, sp, x["turn"], (won != 0.5).float(), heads, a_stats)
        logits, v = out[0].float(), value_logit(model, out[1].float(), ev)
        if mtp:
            tg = mtp_targets(sp, fs, fd, model.mtp)
            ml, acc, cnt = mtp_loss(out[2], tg)
            m_sum["loss"] += ml.item()
            m_sum["acc"] += acc
            m_sum["acc3"] += opp_topk(out[2], tg, 3)
            m_sum["n"] += cnt
            m_sum["b"] += 1
        ce = F.cross_entropy(logits, act, reduction="none")
        sums["ce"] += ce.sum().item()
        top = logits.topk(5, dim=-1).indices  # fewer legal actions: the true one comes first
        hit = top == act[:, None]
        for k in (1, 2, 3, 5):
            sums[f"top{k}"] += hit[:, :k].any(-1).sum().item()
        sw = act >= 8  # switches: where reading the opponent matters most
        sums["n_sw"] += sw.sum().item()
        sums["top1_sw"] += hit[:, 0][sw].sum().item()
        sums["top3_sw"] += hit[:, :3].any(-1)[sw].sum().item()
        sums["ce_sw"] += ce[sw].sum().item()
        sums["bce"] += F.binary_cross_entropy_with_logits(v, won, reduction="sum").item()
        p = torch.sigmoid(v)
        sums["vacc"] += ((p > 0.5).float() == won).sum().item()
        sums["uniform_ce"] += torch.log(ma.sum(-1).float()).sum().item()
        probs.append(p.cpu().numpy())
        wons.append(won.cpu().numpy())
        turns.append(d["turn"][b])
    n = len(idx)
    n_sw = max(1.0, sums.pop("n_sw"))
    top1_sw, top3_sw = sums.pop("top1_sw") / n_sw, sums.pop("top3_sw") / n_sw
    ce_sw = sums.pop("ce_sw") / n_sw
    out = {k: v / n for k, v in sums.items()}
    out |= {"top1_switch": top1_sw, "top3_switch": top3_sw, "ce_switch": ce_sw,
            "switch_frac": n_sw / n}  # fmt: skip
    if mtp:
        out |= {"mtp_loss": m_sum["loss"] / m_sum["b"], "opp_act_acc": m_sum["acc"] / m_sum["n"],
                "opp_act_top3": m_sum["acc3"] / m_sum["n"]}  # fmt: skip
    for k in ("item", "ability", "tera", "move"):
        if a_stats.get(f"n_{k}"):
            nk = a_stats[f"n_{k}"]
            out[f"set_{k}_net"] = a_stats[f"net_{k}"] / nk
            out[f"set_{k}_belief"] = a_stats[f"belief_{k}"] / nk
    for k in ("faint_bce", "faint_acc", "turns_mae"):
        if k in a_stats:
            out[k] = a_stats[k] / n
    p, w, t = np.concatenate(probs), np.concatenate(wons), np.concatenate(turns)
    bins = np.minimum((p * 10).astype(int), 9)
    out["value_ece"] = float(
        sum(
            abs(p[bins == k].mean() - w[bins == k].mean()) * (bins == k).mean()
            for k in range(10)
            if (bins == k).any()
        )  # fmt: skip
    )
    late = t >= 12  # value BCE where it is learnable (the opening is close to a coin flip)
    pl = p[late].clip(1e-7, 1 - 1e-7)
    out["bce_t12"] = float(-(w[late] * np.log(pl) + (1 - w[late]) * np.log(1 - pl)).mean())
    for name, lo, hi in (("early", 0, 10), ("mid", 10, 25), ("late", 25, 10_000)):
        sel = (t >= lo) & (t < hi)
        if sel.any():
            out[f"vacc_{name}"] = float(((p[sel] > 0.5) == w[sel]).mean())
    model.train()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--size", choices=sorted(T_SIZES), default="medium")
    ap.add_argument("--arch", choices=["transformer"], default="transformer")
    ap.add_argument("--history", action="store_true", help="feed the decision-step history")
    ap.add_argument("--hist-len", type=int, default=8, help="most recent steps the model reads")
    ap.add_argument("--mtp", type=int, default=0, help="future steps to predict (auxiliary)")
    ap.add_argument("--mtp-weight", type=float, default=0.5)
    ap.add_argument("--mtp-decay", type=float, default=1.0, help="weight of future step k: d^k")
    ap.add_argument("--feats", default="", help=f"v3 input groups, comma-separated: {FEATS}")
    ap.add_argument("--aux", default="", help=f"v3 auxiliary heads, comma-separated: {AUX_HEADS}")
    ap.add_argument("--aux-weight", type=float, default=0.3)
    ap.add_argument("--kinds", default="main", help="v4 decision points: main,forced,pivot,blind")
    # architecture experiments (transformer): sizes override --size; block options (model.Block)
    ap.add_argument("--d-model", type=int, default=0)
    ap.add_argument("--layers", type=int, default=0)
    ap.add_argument("--heads", type=int, default=0)
    ap.add_argument("--d-ff", type=int, default=0)
    ap.add_argument("--ffn", choices=["relu", "swiglu"], default="relu")
    ap.add_argument("--norm", choices=["ln", "rms"], default="ln")
    ap.add_argument("--qk-norm", action="store_true")
    ap.add_argument("--value-hidden", type=int, default=0,
                    help="value hidden layer size (a warm start adds it, zero)")  # fmt: skip
    ap.add_argument("--elo-dropout", type=float, default=0.25)
    ap.add_argument("--stream", type=int, default=0, help="shards per chunk (0 = all in memory)")
    ap.add_argument("--val-max", type=int, default=500_000, help="--stream: validation positions")
    ap.add_argument("--mask-hidden", action="store_true",
                    help="unrevealed opponent fields -> unknown (no belief sample)")  # fmt: skip
    ap.add_argument("--value-per-game", type=float, default=0,
                    help="value loss weight min(1, N / game's positions); 0 = off")  # fmt: skip
    ap.add_argument("--epochs", type=float, default=6)
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--value-weight", type=float, default=1.0)
    ap.add_argument(
        "--value-residual",
        action="store_true",
        help="value = a * handcrafted eval + b + net (starts at the baseline)",
    )
    ap.add_argument("--half-life", type=float, default=180.0, help="days; 0 = no time weighting")
    ap.add_argument("--val-frac", type=float, default=0.03)
    ap.add_argument("--skip-shards", default="",
                    help="shard name prefixes left out of the data (comma-separated)")  # fmt: skip
    ap.add_argument("--train-only", default="",
                    help="shard name prefixes never in validation (comma-separated), e.g. hf-: "
                         "the replays after Metamon's; v5's validation stays")  # fmt: skip
    ap.add_argument("--val-cutoff", type=int, default=None,
                    help="validation = games uploaded at / after this unix time (fixed split "
                         "across datasets; v1's 3%% cutoff is 1776921722)")  # fmt: skip
    ap.add_argument("--eval-every", type=int, default=500, help="0: a fifth of the steps")
    # expert iteration (design D15-5): self-play data mixed into every batch, warm start
    ap.add_argument(
        "--selfplay", default="", help="self-play datasets (data/train/<x>), comma-sep."
    )
    ap.add_argument(
        "--sp-value-passes", type=int, default=0,
        help="self-play outcomes train the value only the first k draws of a position (0: all); "
             "with --sp-value-schedule spread: k passes of the outcomes over the run",
    )  # fmt: skip
    # design v6 "value training schedule": "first" lets a position's outcome train the value the first k
    # times its row is drawn (fewer fresh rows later, same denominator: the value's weight
    # shrinks over the run); "spread" draws the value rows on their own, every outcome k times
    # in a random order spread evenly over the steps, its loss the weighted mean of those rows
    ap.add_argument("--sp-value-schedule", choices=["first", "spread"], default="first")
    ap.add_argument(
        "--sp-memmap",
        default="data/tmp/sp_memmap",
        help="self-play inputs memory-mapped under this directory ('' = in memory)",
    )
    ap.add_argument("--sp-stream", type=int, default=0,
                    help="self-play read in chunks of about this many train rows (SpStream; "
                         "0: all in memory / memory-mapped)")  # fmt: skip
    ap.add_argument("--sp-per-game", type=int, default=0,
                    help="self-play: max positions per game, policy targets first")  # fmt: skip
    ap.add_argument("--sp-passes", type=float, default=0.0,
                    help="steps = passes over the kept self-play train positions")  # fmt: skip
    ap.add_argument("--sp-frac", type=float, default=0.5, help="share of each batch from self-play")
    ap.add_argument("--sp-val-frac", type=float, default=0.05, help="self-play games held out")
    ap.add_argument("--init", default="", help="warm start: a run directory (its last.pt)")
    ap.add_argument("--steps", type=int, default=0, help="training steps (default: from --epochs)")
    ap.add_argument("--warmup-frac", type=float, default=0.02,
                    help="learning-rate warmup share of the steps (warm starts: longer, the "
                         "optimizer's moments start empty)")  # fmt: skip
    ap.add_argument("--export", choices=["best", "last"], default="best",
                    help="checkpoint exported for inference (self-play: last)")  # fmt: skip
    ap.add_argument("--run", default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    run = a.run or f"{time.strftime('%Y%m%d-%H%M%S')}_{a.data}_{a.size}"
    out_dir = Path("data/train") / a.data / "runs" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    log = open(out_dir / "metrics.jsonl", "a")

    def emit(row: dict) -> None:
        log.write(json.dumps(row) + "\n")
        log.flush()
        parts = [f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in row.items()]
        print(" ".join(parts), flush=True)

    t0 = time.time()
    if a.stream:
        caches, sizes = shard_caches(a.data)
        if a.skip_shards:  # e.g. hf-: the data a run without the newer replays had (v5-glu)
            keep = [not c.stem.startswith(tuple(a.skip_shards.split(","))) for c in caches]
            caches = [c for c, k in zip(caches, keep, strict=True) if k]
            sizes = [n for n, k in zip(sizes, keep, strict=True) if k]
        d = load_small(caches, sizes)  # small columns only; the rest is read chunk by chunk
        n = len(d["game"])
    else:
        d = load(a.data)
        n = len(d["action"])
    # validation: the most recent games (whole games)
    # --train-only: shards whose games always train (newer data: the validation set stays as it
    # was). Their games are left out of the game times too: a game id (crc32) they share with an
    # older game would move that one into validation (11 shared ids moved 159 positions, which
    # changes the whole drawn validation subset: 2026-10-09)
    fixed = np.zeros(n, bool)
    if a.train_only:
        assert a.stream, "--train-only needs --stream"
        prefixes = tuple(a.train_only.split(","))
        fixed = np.array([c.stem.startswith(prefixes) for c in caches])[d["shard"]]
    game_time = {}
    for g, ut, f in zip(d["game"], d["uploadtime"], fixed, strict=True):
        if not f:
            game_time[g] = max(game_time.get(g, 0), ut)
    cutoff = a.val_cutoff or np.quantile(np.fromiter(game_time.values(), np.int64), 1 - a.val_frac)
    is_val = np.array([not f and game_time[g] >= cutoff for g, f in zip(d["game"], fixed,
                                                                         strict=True)])  # fmt: skip
    train_idx, val_idx = np.flatnonzero(~is_val), np.flatnonzero(is_val)
    if "kind" in d:  # v4: the decision points to train on
        names = ("main", "forced", "pivot", "blind")
        use = [names.index(k) for k in a.kinds.split(",")]
        train_idx = train_idx[np.isin(d["kind"][train_idx], use)]
    age_days = (d["uploadtime"].max() - d["uploadtime"]) / 86400
    w = 0.5 ** (age_days / a.half_life) if a.half_life > 0 else np.ones(n)
    w = (w / w[train_idx].mean()).astype(np.float32)
    vw = np.ones(n, np.float32)  # value loss weights
    pw = np.ones(n, np.float32)  # policy loss weights
    _, inv, cnt = np.unique(d["game"], return_inverse=True, return_counts=True)
    if a.value_per_game > 0:
        vw = np.minimum(1.0, a.value_per_game / cnt[inv]).astype(np.float32)
    if a.stream:  # the columns the data has (every shard has the same)
        with np.load(caches[0]) as z:
            keys = set(z.files)
        if len(val_idx) > a.val_max:
            # the same human validation subset whatever --seed (= what seed 0 drew: generations
            # compare on the same positions)
            val_idx = np.sort(np.random.default_rng(0).choice(val_idx, a.val_max, replace=False))
        dv, v_idx = gather(caches, d, val_idx), np.arange(len(val_idx))
    else:
        keys, dv, v_idx = set(d), d, val_idx
    assert not a.history or "hsp" in keys, "--history needs data built with a history column"
    emit(dict(event="data", positions=n, games=len(game_time), train=len(train_idx),
              val=len(val_idx), val_cutoff=int(cutoff), load_s=round(time.time() - t0, 1),
              eff_train=float(w[train_idx].sum() ** 2 / (w[train_idx] ** 2).sum())))  # fmt: skip

    size = dict(T_SIZES[a.size])
    for k, v in (("d_model", a.d_model), ("n_layers", a.layers), ("n_heads", a.heads),
                 ("d_ff", a.d_ff)):  # fmt: skip
        if v:
            size[k] = v
    arch_opts = {"ffn": a.ffn, "norm": a.norm, "qk_norm": a.qk_norm,
                 "value_hidden": a.value_hidden}  # fmt: skip
    assert a.hist_len <= DIMS["hist"], f"--hist-len > the {DIMS['hist']} featurized steps"
    dims = DIMS | {"hist": a.hist_len}
    assert not a.mtp or (a.arch == "transformer" and "fsp" in keys), "--mtp: transformer + future"
    feats = tuple(f for f in a.feats.split(",") if f)
    heads = tuple(f for f in a.aux.split(",") if f)
    v3_ok = a.arch == "transformer" and "ent2" in keys
    assert not (feats or heads) or v3_ok, "--feats / --aux: transformer + v3 data"
    model = TransformerPV(dims, **size, history=a.history, mtp=a.mtp, feats=feats,
                          aux_heads=heads, mask_hidden=a.mask_hidden, arch=arch_opts)  # fmt: skip
    model.residual = None
    if a.value_residual:  # start exactly at the fitted handcrafted baseline
        model.residual = torch.nn.Parameter(torch.tensor([0.714, 0.078]))
        torch.nn.init.zeros_(model.value.weight)
        torch.nn.init.zeros_(model.value.bias)
    init_step = None
    if a.init:  # warm start (same architecture as the run it comes from)
        init = torch.load(Path(a.init) / "last.pt", weights_only=False, map_location="cpu")
        state = init["model"]
        init_step = init.get("step")
        # the exported weights (best.safetensors): the network that played the games and is
        # evaluated (alpha_poke.train.load), not last.pt -- with --export best another step
        # (v0: exported 64,000, last 65,590; 2026-10-22 review); last.pt gives the names
        exported = Path(a.init) / "best.safetensors"
        if exported.exists():
            from safetensors.torch import load_file

            names = set(state)
            state = {("emb." + k if "emb." + k in names else k): v
                     for k, v in load_file(exported).items()}  # fmt: skip
            cfg_path = Path(a.init) / "config.json"
            init_step = (json.loads(cfg_path.read_text()).get("step")
                         if cfg_path.exists() else None)  # fmt: skip
        if "residual" in state:
            model.residual = torch.nn.Parameter(state["residual"].clone())
        # new heads (a value hidden layer --value-hidden, auxiliary heads --aux) are the only
        # parts allowed to be missing: they start from their initialization
        missing, unexpected = model.load_state_dict(state, strict=False)
        new = ("value_mlp.", "faint_head.", "turns_head.")
        assert not unexpected and all(k.startswith(new) for k in missing), (
            missing, unexpected)  # fmt: skip
    model = model.to(device)
    ref_model = None
    if a.init:  # the starting point, frozen: how far the policy moves (KL, design D15-6)
        import copy

        ref_model = copy.deepcopy(model).eval()
        for p_ in ref_model.parameters():
            p_.requires_grad_(False)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=a.wd)
    # self-play data (in memory): train / validation split by game
    dsp = sp_stream = None
    if a.selfplay:  # "name" or "name:keep" (share of its games kept)
        items = [(n, float(k) if k else 1.0)
                 for n, _, k in (x.partition(":") for x in a.selfplay.split(","))]  # fmt: skip
        mdir = None
        if a.sp_memmap and not a.sp_stream:
            import atexit
            import os
            import shutil

            mdir = Path(a.sp_memmap) / f"{a.run}-{os.getpid()}"
            mdir.mkdir(parents=True, exist_ok=True)
            atexit.register(shutil.rmtree, mdir, ignore_errors=True)
        if a.sp_stream:  # small columns only; the rest is read chunk by chunk (SpStream)
            sp_plan, sp_n0 = plan_selfplay(items, a.sp_per_game, a.seed)
            sp_caches, dsp = selfplay_small(sp_plan)
        else:
            dsp, sp_n0 = load_selfplay(items, a.sp_per_game, a.seed, mdir)
        if a.sp_per_game > 0:
            # at most N positions per game (fixed for the run): long games (switch loops of two
            # stall teams, up to 650 decisions) would otherwise weigh tens of times more than a
            # typical one (63); typical games keep all their policy targets
            emit(dict(event="sp_per_game", cap=a.sp_per_game, positions=sp_n0,
                      kept=len(dsp["game"]),
                      policy_targets_kept=int(dsp["pi_w"].sum())))  # fmt: skip
        val_g = (dsp["game"] % 1000) < a.sp_val_frac * 1000
        sp_train, sp_val = np.flatnonzero(~val_g), np.flatnonzero(val_g)
        _, sinv, scnt = np.unique(dsp["game"], return_inverse=True, return_counts=True)
        sp_vw = (np.minimum(1.0, a.value_per_game / scnt[sinv]) if a.value_per_game > 0
                 else np.ones(len(sinv))) * dsp["value_ok"]  # fmt: skip
        sp_vw = sp_vw.astype(np.float32)
        sp_seen = np.zeros(len(sp_vw), np.int32)  # draws per position (--sp-value-passes)
        bsp = int(round(a.batch * a.sp_frac))
        sp_eval = (dsp, sp_val)  # the self-play validation data and its rows
        if a.sp_stream:
            assert a.sp_passes == int(a.sp_passes) > 0 and not a.steps, "--sp-stream: --sp-passes"
            spread = a.sp_value_schedule == "spread"
            sp_stream = SpStream(sp_caches, dsp, sp_train, a.sp_stream, bsp, int(a.sp_passes), rng,
                                 sp_train[sp_vw[sp_train] > 0] if spread else None,
                                 max(1, a.sp_value_passes))  # fmt: skip
            a.steps = sp_stream.steps
            sp_eval = (gather(sp_caches, dsp, sp_val), np.arange(len(sp_val)))
        if not a.steps and a.sp_passes > 0:  # each kept self-play position ~sp_passes times
            a.steps = max(50, math.ceil(a.sp_passes * len(sp_train) / bsp))
        emit(dict(event="selfplay", positions=len(sinv), games=len(scnt), train=len(sp_train),
                  val=len(sp_val), policy_targets=int(dsp["pi_w"][sp_train].sum()),
                  batch_selfplay=bsp,
                  passes_per_target=round(a.steps * bsp / max(len(sp_train), 1), 2)
                  if a.steps else None))  # fmt: skip
    hb = a.batch - (bsp if dsp is not None else 0)  # human rows per batch
    steps = a.steps or int(a.epochs * len(train_idx) / a.batch)
    v_sched = None  # --sp-value-schedule spread: the value rows of each step
    if dsp is not None and a.sp_value_schedule == "spread" and sp_stream is None:
        valued = sp_train[sp_vw[sp_train] > 0]
        order = np.concatenate([rng.permutation(valued)
                                for _ in range(max(1, a.sp_value_passes))])  # fmt: skip
        v_sched = np.array_split(order, steps)
        emit(dict(event="value_schedule", outcomes=len(valued), passes=max(1, a.sp_value_passes),
                  rows_per_step=round(len(order) / steps, 1)))  # fmt: skip
    if a.eval_every <= 0:
        a.eval_every = max(50, steps // 5)
    warm = max(1, int(steps * a.warmup_frac))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(1, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(s, steps) / steps)),
    )
    emit(dict(event="start", arch=a.arch, history=a.history, size=a.size, params=n_params,
              steps=steps, device=str(device), init_step=init_step,
              args=json.dumps(vars(a))))  # fmt: skip
    best = float("inf")
    probs = w[train_idx] / w[train_idx].sum()
    stream = (ChunkStream(caches, d, train_idx, probs, a.stream, hb, rng)
              if a.stream and hb > 0 else None)  # fmt: skip
    agg = dict(ce=0.0, bce=0.0, acc=0.0, gn=0.0, k=0)
    if a.init:  # the starting point on the same validation sets (the run's own baseline)
        m = evaluate(model, dv, v_idx, device)
        m |= evaluate_drift(model, ref_model, dv, v_idx, device)
        if dsp is not None:
            m |= evaluate_sp(model, *sp_eval, device, a.value_per_game, ref=ref_model)
        emit(dict(event="val", step=0, **{k: float(v) for k, v in m.items()}))
    t_last = time.time()
    nonfinite = 0  # batches with a non-finite loss / gradient (skipped)
    for step in range(1, steps + 1):
        if hb > 0:  # the human sub-batch (none with --sp-frac 1: the self-play data alone)
            if stream is not None:  # chunk data, its rows, their global ids
                dd, b_loc, b = stream.batch_rows()
            else:
                if (step - 1) % 1000 == 0:  # time-weighted sampling, drawn 1000 steps at a time
                    block = train_idx[rng.choice(len(train_idx), (1000, hb), p=probs)]
                dd, b = d, block[(step - 1) % 1000]
                b_loc = b
            sp, de, gl, ma, act, won, ev, hs, hd, fs, fd, x = to_torch(dd, b_loc, device)
            kw = {"x": x} if a.arch == "transformer" and x is not None else {}
            if x is not None and "rating" in x and a.elo_dropout > 0:  # unknown ratings, as in play
                drop = torch.rand(x["rating"].shape, device=device) < a.elo_dropout
                x["rating"] = x["rating"].masked_fill(drop, 0)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                out = model(sp, de, gl, ma, hs, hd, aux=bool(a.mtp or heads), **kw)
            logits, v = out[0], out[1]
            pwb = torch.from_numpy(pw[b]).to(device)
            ce = (policy_loss(logits, act, ma, reduction="none") * pwb).sum() / pwb.sum().clamp_min(
                1e-6
            )
            bw = torch.from_numpy(vw[b]).to(device)
            vl = value_logit(model, v.float(), ev)
            bce = (
                F.binary_cross_entropy_with_logits(vl, won, reduction="none") * bw
            ).sum() / bw.sum().clamp_min(1e-6)
            loss = ce + a.value_weight * bce
            if a.mtp:
                tg = mtp_targets(sp, fs, fd, a.mtp)
                loss = loss + a.mtp_weight * mtp_loss(out[2], tg, a.mtp_decay)[0]
            if heads:
                # remaining turns: not from a draw (a self-play game capped: its end unknown)
                bw_t = bw * (won != 0.5)
                loss = loss + a.aux_weight * aux_loss(out[3], x, sp, x["turn"], bw_t, heads)
        else:
            ce = bce = loss = torch.zeros((), device=device)
            logits = act = None
        if dsp is not None:  # self-play sub-batch: soft policy targets, outcome, same aux heads
            # rows: local to the data (s_data), global ids (bs / bv: weights, value draws)
            if sp_stream is not None:
                s_data, b_loc, bs, bv_loc, bv = sp_stream.next()
                spread = sp_stream.vpass is not None
            else:
                s_data, bs = dsp, sp_train[rng.integers(0, len(sp_train), bsp)]
                b_loc = bs
                spread = v_sched is not None
                if spread:
                    bv = bv_loc = v_sched[step - 1]
            s_sp, s_de, s_gl, s_ma, s_act, s_won, s_ev, s_hs, s_hd, s_fs, s_fd, s_x = to_torch(
                s_data, b_loc, device
            )
            s_kw = {"x": s_x} if a.arch == "transformer" and s_x is not None else {}
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                s_out = model(s_sp, s_de, s_gl, s_ma, s_hs, s_hd, aux=bool(a.mtp or heads), **s_kw)
            pi = torch.from_numpy(s_data["pi"][b_loc]).to(device)
            pw_s = torch.from_numpy(s_data["pi_w"][b_loc]).to(device)
            s_ce = (soft_policy_loss(s_out[0], pi, s_ma) * pw_s).sum() / pw_s.sum().clamp_min(1)
            bw_s = torch.from_numpy(sp_vw[bs]).to(device)
            # --sp-value-passes: a position's outcome counts only the first k times it is drawn
            # (the outcome is one noisy bit per game: the value overfits when the policy targets
            # are trained several passes); same denominator, so fewer rows = a smaller step
            # (known: the value's effective weight shrinks over a run; design v6)
            if spread and not len(bv):  # (a chunk with fewer value rows than steps)
                s_bce = torch.zeros((), device=device)
            elif spread:  # the step's own value rows (weighted mean)
                v_sp, v_de, v_gl, v_ma, _, v_won, v_ev, v_hs, v_hd, _, _, v_x = to_torch(
                    s_data, bv_loc, device
                )
                v_kw = {"x": v_x} if a.arch == "transformer" and v_x is not None else {}
                with torch.autocast(device.type, dtype=torch.bfloat16,
                                    enabled=device.type == "cuda"):  # fmt: skip
                    v_v = model(v_sp, v_de, v_gl, v_ma, v_hs, v_hd, **v_kw)[1]
                v_w = torch.from_numpy(sp_vw[bv]).to(device)
                s_vl = value_logit(model, v_v.float(), v_ev)
                s_bce = (F.binary_cross_entropy_with_logits(s_vl, v_won, reduction="none")
                         * v_w).sum() / v_w.sum().clamp_min(1e-6)  # fmt: skip
            else:
                vv_s = bw_s
                bv_s = vv_s
                if a.sp_value_passes > 0:
                    fresh = sp_seen[bs] < a.sp_value_passes
                    np.add.at(sp_seen, bs, 1)
                    bv_s = vv_s * torch.from_numpy(fresh.astype(np.float32)).to(device)
                s_vl = value_logit(model, s_out[1].float(), s_ev)
                s_bce = (F.binary_cross_entropy_with_logits(s_vl, s_won, reduction="none")
                         * bv_s).sum() / vv_s.sum().clamp_min(1e-6)  # fmt: skip
            s_loss = s_ce + a.value_weight * s_bce
            if a.mtp:
                s_loss = (
                    s_loss
                    + a.mtp_weight
                    * mtp_loss(s_out[2], mtp_targets(s_sp, s_fs, s_fd, a.mtp), a.mtp_decay)[0]
                )
            if heads:
                s_loss = s_loss + a.aux_weight * aux_loss(s_out[3], s_x, s_sp, s_x["turn"],
                                                          bw_s * (s_won != 0.5), heads)  # fmt: skip
            loss = (1 - a.sp_frac) * loss + a.sp_frac * s_loss
            agg["sp_ce"] = agg.get("sp_ce", 0.0) + s_ce.item()
            agg["sp_bce"] = agg.get("sp_bce", 0.0) + s_bce.item()
        opt.zero_grad(set_to_none=True)
        loss.backward()
        gn = torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0).item()
        finite = math.isfinite(gn) and math.isfinite(loss.item())
        if finite:
            opt.step()
        else:
            # a non-finite loss or gradient: no update from this batch (counted; the schedule
            # goes on), never NaN weights (2026-10-22 review)
            opt.zero_grad(set_to_none=True)
            nonfinite += 1
            emit(dict(event="nonfinite", step=step, loss=float(loss.item()), grad_norm=gn,
                      total=nonfinite))  # fmt: skip
        sched.step()
        if finite:
            agg["ce"] += ce.item()
            agg["bce"] += bce.item()
            if logits is not None:
                agg["acc"] += (logits.argmax(-1) == act).float().mean().item()
            agg["gn"] += gn
            agg["k"] += 1
        if step % 100 == 0 and agg["k"] > 0:
            k = agg.pop("k")
            sp_part = ({"sp_policy_ce": agg["sp_ce"] / k, "sp_value_bce": agg["sp_bce"] / k}
                       if "sp_ce" in agg else {})  # fmt: skip
            emit(dict(event="train", step=step, epoch=round(step * hb / len(train_idx), 3),
                      policy_ce=agg["ce"] / k, value_bce=agg["bce"] / k, policy_acc=agg["acc"] / k,
                      **sp_part, grad_norm=agg["gn"] / k, lr=sched.get_last_lr()[0],
                      samples_per_s=round(100 * a.batch / (time.time() - t_last))))  # fmt: skip
            agg = dict(ce=0.0, bce=0.0, acc=0.0, gn=0.0, k=0)
            t_last = time.time()
        if step % a.eval_every == 0 or step == steps:
            m = evaluate(model, dv, v_idx, device)
            if ref_model is not None:
                m |= evaluate_drift(model, ref_model, dv, v_idx, device)
            if dsp is not None:
                m |= evaluate_sp(model, *sp_eval, device, a.value_per_game, ref=ref_model)
            emit(dict(event="val", step=step, **{k: float(v) for k, v in m.items()}))
            # selection: all turn starts + all positions when the data has them (the visible
            # turn starts alone are a biased sample), weighted when it has sampling weights
            sel = ("ce_turn_w", "bce_all_w") if "ce_turn_w" in m else (
                ("ce_turn", "bce_all") if "ce_turn" in m else ("ce", "bce"))  # fmt: skip
            val_loss = m[sel[0]] + a.value_weight * m[sel[1]]
            ckpt = {"model": model.state_dict(), "dims": dims, "size": size, "arch": a.arch,
                    "history": a.history, "mtp": a.mtp, "feats": feats, "aux_heads": heads,
                    "mask_hidden": a.mask_hidden, "arch_opts": getattr(model, "arch", {}),
                    "step": step, "val": m,
                    "value_residual": a.value_residual}  # fmt: skip
            torch.save(ckpt, out_dir / "last.pt")
            if val_loss < best:
                best = val_loss
                torch.save(ckpt, out_dir / "best.pt")
    from safetensors.torch import save_file

    best_ckpt = torch.load(out_dir / f"{a.export}.pt", weights_only=False)
    # the shared embedding tables keep their v1 names (emb.species -> species) for the Rust loader
    save_file({k.removeprefix("emb."): v.float().contiguous()
               for k, v in best_ckpt["model"].items()}, out_dir / "best.safetensors")  # fmt: skip
    (out_dir / "config.json").write_text(json.dumps(
        {"dims": dims, "size": size, "arch": a.arch, "history": a.history, "mtp": a.mtp,
         "feats": feats, "aux_heads": heads, "arch_opts": getattr(model, "arch", {}),
         "step": best_ckpt["step"], "val": best_ckpt["val"]}, indent=2))  # fmt: skip
    emit(dict(event="done", best_val_loss=best, minutes=round((time.time() - t0) / 60, 1)))


if __name__ == "__main__":
    main()
