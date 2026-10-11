"""Child-node value targets (design TODO "方案乙", 2026-10-10; TreeStrap-like): root positions of a
self-play generation's decisions searched again, the root's children with enough visits
exported with their search values and their network inputs (BatchSearch.children: world 0,
one chance outcome, the context extended as the search does).

Roots: decisions with at least two legal options of the games every training holds out NOT
(the held-out ones are pv_bench's), drawn uniformly (line numbers first: a 50,000-game
generation's decisions do not fit in memory). The recorded world 0 only (the other belief worlds
are not recorded): the searches are determinized, as the network's inputs are.

Output: data/train/children/gen<G>/chunk-<w>-<k>.npz, one row per child: the network input
arrays in compact types (as the feature caches) and root (global root index), our / their
(action slots), visits, value (the child's search value, side one = the player to act at the
root), q (the root's value).

  uv run python scripts/child_targets.py --gen 4 --roots 100000
"""

import argparse
import json
import random
import time
import zlib
from pathlib import Path

import numpy as np

OUT = Path("data/train/children")
CHUNK = 2000  # roots per output file


def pick_roots(gen_dir: Path, n: int, seed: int) -> list[dict]:
    battle = {}
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in open(f):
            g = json.loads(line)
            battle[g["pair"]] = g["battle"]
    files = sorted(gen_dir.glob("decisions-w*.jsonl"))
    counts = []
    for f in files:
        with open(f, "rb") as fh:
            counts.append(sum(c.count(b"\n") for c in iter(lambda: fh.read(1 << 24), b"")))
    pick = set(random.Random(seed).sample(range(sum(counts)), min(sum(counts), int(n * 1.5))))
    out, base = [], 0
    for f, c in zip(files, counts, strict=True):
        with open(f) as fh:
            for i, line in enumerate(fh):
                if base + i not in pick:
                    continue
                d = json.loads(line)
                gid = f"sp{gen_dir.name[3:]}-{d['game']}-{battle.get(d['game'])}"
                if d["game"] not in battle or zlib.crc32(gid.encode()) % 1000 < 50:
                    continue  # held out of every training (pv_bench's positions)
                if sum(d["legal"]) < 2:
                    continue
                out.append({k: d[k] for k in ("state", "reveal", "ratings", "ctx_turn",
                                              "history", "q")})  # fmt: skip
        base += c
    random.Random(seed).shuffle(out)
    return out[:n]


# the network input arrays of a batch: (key, raw dtype, stored dtype, shape after rows)
def specs(D: dict) -> list:
    e = D["entities"]
    return [("sparse", np.int32, np.int16, (e, D["sparse"])),
            ("dense", np.float32, np.float16, (e, D["dense"])),
            ("global", np.float32, np.float16, (D["global"],)),
            ("mask", np.uint8, np.uint8, (D["actions"],)),
            ("hsparse", np.int32, np.int16, (D["hist"], D["hist_sparse"])),
            ("hdense", np.float32, np.float16, (D["hist"], D["hist_dense"])),
            ("reveal", np.uint8, np.uint8, (e,)),
            ("ent2", np.float32, np.float16, (e, D["ent_extra"])),
            ("glob2", np.float32, np.float16, (D["global_extra"],)),
            ("turn", np.int32, np.int16, ()),
            ("rating", np.int32, np.int16, (2,)),
            ("eval", np.float32, np.float32, ())]  # fmt: skip


def work(args) -> int:
    wid, roots, first, a = args
    import alpha_search

    from alpha_poke.selfplay.batcher import Batcher

    D = alpha_search.feature_dims()
    out_dir = Path(a.out) / f"gen{a.gen}"
    b = Batcher(a.model, leaves=8, threads=8)
    n_rows = 0
    for k in range(0, len(roots), CHUNK):
        path = out_dir / f"chunk-{wid:02d}-{k // CHUNK:04d}.npz"
        if path.exists():
            continue
        part = roots[k : k + CHUNK]
        futs = [b.submit([r["state"]], [(r["reveal"], tuple(r["ratings"]), r["ctx_turn"],
                                         r["history"])],
                         a.iterations, a.seed + first + k + i, (0.0, 10.0), children=a.min_visits)
                for i, r in enumerate(part)]  # fmt: skip
        cols: dict = {key: [] for key, *_ in specs(D)}
        meta: dict = {"root": [], "our": [], "their": [], "visits": [], "value": [], "q": []}
        for i, (f, r) in enumerate(zip(futs, part, strict=True)):
            try:
                _, _, (batch, kids) = f.result()
            except Exception:  # noqa: BLE001 - an engine failure: the root is skipped
                continue
            n = batch["rows"]
            if n == 0:
                continue
            for key, raw, _, shape in specs(D):
                cols[key].append(np.frombuffer(batch[key], raw).reshape((n, *shape)))
            for our, their, visits, value in kids:
                meta["root"].append(first + k + i)
                meta["our"].append(our)
                meta["their"].append(their)
                meta["visits"].append(visits)
                meta["value"].append(value)
                meta["q"].append(r["q"])
        if not meta["root"]:
            continue
        arrays = {key: np.concatenate(cols[key]).astype(store) for key, _, store, _ in specs(D)}
        arrays |= {"root": np.asarray(meta["root"], np.int64),
                   "our": np.asarray(meta["our"], np.int8),
                   "their": np.asarray(meta["their"], np.int8),
                   "visits": np.asarray(meta["visits"], np.int32),
                   "value": np.asarray(meta["value"], np.float32),
                   "q": np.asarray(meta["q"], np.float32)}  # fmt: skip
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, **arrays)
        tmp.rename(path)
        n_rows += len(meta["root"])
        print(f"w{wid} {path.name}: {len(meta['root'])} children of {len(part)} roots", flush=True)
    return n_rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--roots", type=int, default=100_000)
    ap.add_argument("--model", default="", help="the searching network (default sp-gen<gen>)")
    ap.add_argument("--iterations", type=int, default=1600)
    ap.add_argument("--min-visits", type=int, default=50)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    a.model = a.model or f"data/train/v5/runs/sp-gen{a.gen}"
    t0 = time.time()
    roots = pick_roots(Path(f"data/selfplay/gen{a.gen}"), a.roots, a.seed)
    print(f"{len(roots)} roots ({time.time() - t0:.0f}s)", flush=True)
    (Path(a.out) / f"gen{a.gen}").mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f"gen{a.gen}" / "meta.json").write_text(json.dumps(
        {"gen": a.gen, "roots": len(roots), "model": a.model, "iterations": a.iterations,
         "min_visits": a.min_visits, "seed": a.seed}, indent=1))  # fmt: skip
    k = -(-len(roots) // a.procs)
    jobs = [(w, roots[w * k : (w + 1) * k], w * k, a) for w in range(a.procs)]
    with ProcessPoolExecutor(a.procs, mp_context=mp.get_context("spawn")) as ex:
        total = sum(ex.map(work, jobs))
    print(f"{total} children of {len(roots)} roots in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
