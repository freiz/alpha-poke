"""A fixed policy / value benchmark (2026-10-10): does a network's value judge the positions, does
its prior point at the right options, and do its searches (value only; prior and value) choose
them? The same positions for every network and generation.

  build      positions.jsonl: --sp self-play positions of generation --gen, from the games every
             training holds out (train_pv's self-play validation: crc32 of the game id % 1000 <
             50), and --human positions of the human validation games (uploaded at / after
             --cutoff, the v5 split; rated >= --min-rating; turn-start decisions); one position
             per game, at least two options; a fixed third of them (by id) is "dev" (to choose
             on), the rest "test" (to report on: choosing on the same positions biases them)
  reference  per network of --nets: a deep search of every position (--iterations, no noise,
             the network's prior and value) -> ref_<net>.jsonl (visits / mean per action slot)
  score      per network of --nets:
               * outcome: value BCE / ECE / calibration slope against the games' results (no
                 reference needed: unbiased, noisy);
               * decisions: a search guided by the value only (uniform priors, --iterations)
                 against the reference (the networks of reference.jsonl averaged, so that no
                 single network's own judgement is the yardstick): top-1 agreement with the
                 reference's most visited option, and the rank correlation of the options' mean
                 values (Spearman, options both searched);
               * the same with the network's prior (the search as played);
               * the prior alone (no search): its top option against the reference's, and its
                 rank correlation with the reference's visit shares
             -> score.json, one entry per network and position source

The positions are single worlds (the recorded world 0 / the training row's state): the searches
are determinized, the same for every network.

  uv run python scripts/pv_bench.py build --gen 4
  uv run python scripts/pv_bench.py reference --nets v5-glu,sp-gen0,sp-gen2
  uv run python scripts/pv_bench.py score --nets v5-glu,sp-gen0,sp-gen2,...
"""

import argparse
import glob
import json
import random
import zlib
from pathlib import Path

import numpy as np

OUT = Path("data/eval/pv_bench")
RUNS = Path("data/train/v5/runs")
SELFPLAY = Path("data/selfplay")


def run_dir(name: str) -> str:
    return name if "/" in name else str(RUNS / name)


def build(a) -> None:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    rng = random.Random(a.seed)
    gen_dir = SELFPLAY / f"gen{a.gen}"
    battle = {}
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in open(f):
            g = json.loads(line)
            battle[g["pair"]] = g["battle"]

    def held_out(pair: int) -> bool:  # train_pv: --sp-val-frac 0.05 of the games
        gid = f"sp{a.gen}-{pair}-{battle.get(pair)}"
        return pair in battle and zlib.crc32(gid.encode()) % 1000 < 50

    by_game: dict[int, list] = {}
    for f in sorted(gen_dir.glob("decisions-w*.jsonl")):
        for line in open(f):
            d = json.loads(line)
            if d["won"] is None or not held_out(d["game"]) or sum(d["legal"]) < 2:
                continue
            by_game.setdefault(d["game"], []).append(d)
    games = sorted(by_game)
    rng.shuffle(games)
    out = []
    for g in games[: a.sp]:
        d = rng.choice(by_game[g])
        out.append(
            {
                "source": "selfplay",
                "id": f"sp{a.gen}-{g}-{d['side']}-{d['turn']}",
                "state": d["state"],
                "reveal": d["reveal"],
                "ratings": d["ratings"],
                "turn": d["ctx_turn"],
                "history": d["history"],
                "won": float(d["won"]),
            }
        )
    n_sp = len(out)
    # human: the validation games (Metamon's shards; the newer hf- ones are training only)
    files = sorted(f for f in glob.glob("data/train/v5/train-*.parquet")
                   if pq.read_metadata(f).num_rows)  # fmt: skip
    rng.shuffle(files)
    cols = ["game", "turn", "state", "won", "rating_own", "rating_opp", "uploadtime", "history",
            "reveal", "kind"]  # fmt: skip
    seen: set = set()
    for f in files:
        if len(out) - n_sp >= a.human:
            break
        t = pq.read_table(f, columns=cols)
        keep = pc.and_(pc.greater_equal(t["uploadtime"], a.cutoff), pc.equal(t["kind"], 0))
        keep = pc.and_(keep, pc.greater_equal(t["rating_own"], a.min_rating))
        rows = t.filter(keep).to_pylist()
        rng.shuffle(rows)
        for r in rows:
            if r["game"] in seen or len(out) - n_sp >= a.human:
                continue
            seen.add(r["game"])
            out.append(
                {
                    "source": "human",
                    "id": f"{r['game']}-{r['turn']}",
                    "state": r["state"],
                    "reveal": r["reveal"],
                    "ratings": [r["rating_own"], r["rating_opp"]],
                    "turn": r["turn"],
                    "history": r["history"] or "",
                    "won": r["won"],
                }
            )
    for p in out:  # a fixed split: choose on "dev", report on "test" (selection bias)
        p["split"] = "dev" if zlib.crc32(p["id"].encode()) % 3 == 0 else "test"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "positions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in out))
    meta = {"gen": a.gen, "seed": a.seed, "selfplay": n_sp, "human": len(out) - n_sp,
            "cutoff": a.cutoff, "min_rating": a.min_rating}  # fmt: skip
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))
    print(meta)


def load_positions() -> list[dict]:
    return [json.loads(x) for x in (OUT / "positions.jsonl").read_text().splitlines()]


def search_all(net: str, pos: list[dict], iterations: int, prior: bool, seed: int,
               leaves: int = 8) -> list:  # fmt: skip
    """One search per position on the GPU (selfplay.Batcher), no root noise: records."""
    from alpha_poke.selfplay.batcher import Batcher

    b = Batcher(run_dir(net), leaves=leaves, threads=8, prior=prior)
    futs = [b.submit([p["state"]], [(p["reveal"], tuple(p["ratings"]), p["turn"], p["history"])],
                     iterations, seed + i, (0.0, 10.0)) for i, p in enumerate(pos)]  # fmt: skip
    out = []
    for f in futs:
        try:
            rec, _ = f.result()
            out.append({k: rec[k] for k in ("visits", "mean", "legal", "q", "prior")})
        except Exception as e:  # noqa: BLE001 - an engine failure: the position is skipped
            out.append({"error": str(e)})
    return out


def _search_chunk(args) -> list:
    net, pos, iterations, prior, seed = args
    return search_all(net, pos, iterations, prior, seed)


def search_par(net: str, pos: list[dict], iterations: int, prior: bool, seed: int,
               procs: int) -> list:  # fmt: skip
    """``search_all`` split over ``procs`` processes (a batcher each: the CPU side of the search
    is the bottleneck); seeds by position as in one process."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    if procs <= 1:
        return search_all(net, pos, iterations, prior, seed)
    k = -(-len(pos) // procs)
    jobs = [(net, pos[i : i + k], iterations, prior, seed + i) for i in range(0, len(pos), k)]
    with ProcessPoolExecutor(len(jobs), mp_context=mp.get_context("spawn")) as ex:
        return [r for part in ex.map(_search_chunk, jobs) for r in part]


def reference(a) -> None:
    pos = load_positions()
    for net in a.nets.split(","):
        recs = search_par(net, pos, a.iterations, True, a.seed, a.procs)
        name = Path(net).name
        (OUT / f"ref_{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        print(name, sum("error" in r for r in recs), "errors")
    f = OUT / "reference.json"
    refs = json.loads(f.read_text()) if f.exists() else {}
    refs |= {Path(n).name: a.iterations for n in a.nets.split(",")}
    (OUT / "reference.json").write_text(json.dumps(refs, indent=1))


def consensus() -> list:
    """Per position: the reference networks' visit shares and mean values averaged (slots any
    of them searched)."""
    names = json.loads((OUT / "reference.json").read_text())
    refs = [[json.loads(x) for x in (OUT / f"ref_{n}.jsonl").read_text().splitlines()]
            for n in names]  # fmt: skip
    out = []
    for rs in zip(*refs, strict=True):
        if any("error" in r for r in rs):
            out.append(None)
            continue
        share = np.mean([np.asarray(r["visits"], float) / max(sum(r["visits"]), 1) for r in rs], 0)
        mean = np.mean([np.asarray(r["mean"], float) for r in rs], 0)
        out.append({"share": share, "mean": mean})
    return out


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def outcome_metrics(net: str, pos: list[dict]) -> dict:
    import alpha_search

    _, vz = alpha_search.tnet_forward(
        run_dir(net),
        [p["state"] for p in pos],
        [p["reveal"] for p in pos],
        [tuple(p["ratings"]) for p in pos],
        [p["turn"] for p in pos],
        [p["history"] for p in pos],
    )
    z = np.asarray(vz, float)
    y = np.asarray([p["won"] for p in pos], float)
    pr = np.clip(1 / (1 + np.exp(-z)), 1e-6, 1 - 1e-6)
    bce = -(y * np.log(pr) + (1 - y) * np.log(1 - pr))
    bins = np.clip((pr * 10).astype(int), 0, 9)
    ece = sum(abs(pr[bins == k].mean() - y[bins == k].mean()) * (bins == k).mean()
              for k in range(10) if (bins == k).any())  # fmt: skip
    c, slope = 0.0, 1.0
    try:
        for _ in range(50):  # y ~ sigmoid(c + slope z), Newton
            q = 1 / (1 + np.exp(-(c + slope * z)))
            w = q * (1 - q)
            h = np.array([[w.sum(), (w * z).sum()], [(w * z).sum(), (w * z * z).sum()]])
            grad = [(q - y).sum(), ((q - y) * z).sum()]
            c, slope = np.array([c, slope]) - np.linalg.solve(h, grad)
    except np.linalg.LinAlgError:  # too few or separable positions
        slope = float("nan")
    return {
        "bce": round(float(bce.mean()), 4),
        "bce_se": round(float(bce.std() / len(bce) ** 0.5), 4),
        "ece": round(float(ece), 4),
        "slope": round(float(slope), 3),
    }


def decision_metrics(recs: list, cons: list, idx: list[int], prior: bool = False) -> dict:
    """Top-1 agreement with the reference and rank correlation: of a search's visits / option
    means with the reference's (options both searched), or (``prior``) of the network's prior
    with the reference's visit shares (options the reference searched)."""
    top, rho = [], []
    for i in idx:
        r, c = recs[i], cons[i]
        if c is None or "error" in r:
            continue
        legal = np.asarray(r["legal"], bool) & (c["share"] > 0)
        if legal.sum() < 2:
            continue
        v = np.asarray(r["prior" if prior else "visits"], float)
        top.append(
            int(np.argmax(np.where(legal, v, -1)) == np.argmax(np.where(legal, c["share"], -1)))
        )
        if prior:
            rho.append(spearman(v[legal], c["share"][legal]))
        else:
            both = legal & (v > 0)
            rho.append(spearman(np.asarray(r["mean"], float)[both], c["mean"][both]))
    rho = [x for x in rho if x == x]
    return {"positions": len(top), "top1": round(float(np.mean(top)), 4) if top else None,
            "top1_se": round(float(np.std(top) / len(top) ** 0.5), 4) if top else None,
            "spearman": round(float(np.mean(rho)), 4) if rho else None}  # fmt: skip


def score(a) -> None:
    pos = load_positions()
    cons = consensus()
    path = OUT / "score.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    for net in a.nets.split(","):
        name = Path(net).name
        value_only = search_par(net, pos, a.iterations, False, a.seed + 1_000_000, a.procs)
        with_prior = search_par(net, pos, a.iterations, True, a.seed + 2_000_000, a.procs)
        entry = {}
        for src, split in [(s, sp) for s in ("selfplay", "human") for sp in ("dev", "test")]:
            idx = [i for i, p in enumerate(pos) if p["source"] == src and p["split"] == split]
            entry[f"{src}/{split}"] = {"outcome": outcome_metrics(net, [pos[i] for i in idx]),
                          "prior_only": decision_metrics(with_prior, cons, idx, prior=True),
                          "value_only": decision_metrics(value_only, cons, idx),
                          "with_prior": decision_metrics(with_prior, cons, idx)}  # fmt: skip
        entry["iterations"] = a.iterations
        res[name] = entry
        print(name, json.dumps(entry), flush=True)
        path.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--gen", type=int, required=True, help="self-play positions from this gen")
    p.add_argument("--sp", type=int, default=1500)
    p.add_argument("--human", type=int, default=1500)
    p.add_argument("--cutoff", type=int, default=1776921722, help="the v5 validation split")
    p.add_argument("--min-rating", type=int, default=1500)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=build)
    p = sub.add_parser("reference")
    p.add_argument("--nets", required=True, help="comma-separated run names / directories")
    p.add_argument("--iterations", type=int, default=16000)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=reference)
    p = sub.add_parser("score")
    p.add_argument("--nets", required=True)
    p.add_argument("--iterations", type=int, default=800)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=score)
    for q in sub.choices.values():
        q.add_argument("--out", default=str(OUT), help="benchmark directory")
        q.add_argument("--procs", type=int, default=4, help="search processes")
    args = ap.parse_args()
    OUT = Path(args.out)
    args.fn(args)
