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
"""

import argparse
import glob
import json
import math
import time
import zlib
from pathlib import Path

import alpha_search
import numpy as np
import pyarrow.parquet as pq
import torch
import torch.nn.functional as F

from alpha_poke.train.model import PolicyValueNet

SIZES = {
    "small": dict(d_ent=64, d_trunk=128, d_global=32),
    "medium": dict(d_ent=128, d_trunk=256, d_global=64),
    "large": dict(d_ent=256, d_trunk=512, d_global=128),
}
DIMS = alpha_search.feature_dims()


def featurize_shard(path: Path, cache: Path) -> int:
    """Write the shard's feature cache (if missing); returns its number of positions."""
    if cache.exists():
        with np.load(cache) as z:
            if "evalv" in z.files:  # caches from before the handcrafted evaluation are rebuilt
                return len(z["action"])
    t = pq.read_table(
        path, columns=["game", "turn", "state", "action", "won", "rating", "uploadtime"]
    )
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
    out["evalv"] = np.concatenate(
        [np.asarray(alpha_search.evaluate(states[i : i + 50_000]), np.float32)
         for i in range(0, len(states), 50_000)]
    )  # fmt: skip
    out["action"] = np.asarray(t.column("action").to_pylist(), np.int64)
    out["won"] = np.asarray(t.column("won").to_pylist(), np.float32)
    out["turn"] = np.asarray(t.column("turn").to_pylist(), np.int32)
    out["uploadtime"] = np.asarray(t.column("uploadtime").to_pylist(), np.int64)
    out["game"] = np.asarray(
        [zlib.crc32(x.encode()) for x in t.column("game").to_pylist()], np.int64
    )
    act = out["action"].clip(0, a - 1)
    ok = (out["action"] < a) & (out["mask"][np.arange(len(act)), act] == 1)
    out = {k: v[ok] for k, v in out.items()}
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(cache.stem + ".tmp.npz")  # atomic: a killed run leaves no broken cache
    np.savez(tmp, **out)
    tmp.rename(cache)
    return len(out["action"])


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


def to_torch(d: dict, idx: np.ndarray, device) -> tuple:
    """(sparse, dense, glob, mask, action, won, handcrafted eval / 100)"""
    return (
        torch.from_numpy(d["sparse"][idx].astype(np.int64)).to(device, non_blocking=True),
        torch.from_numpy(d["dense"][idx].astype(np.float32)).to(device, non_blocking=True),
        torch.from_numpy(d["glob"][idx].astype(np.float32)).to(device, non_blocking=True),
        torch.from_numpy(d["mask"][idx].astype(bool)).to(device, non_blocking=True),
        torch.from_numpy(d["action"][idx]).to(device, non_blocking=True),
        torch.from_numpy(d["won"][idx]).to(device, non_blocking=True),
        torch.from_numpy(d["evalv"][idx] / 100).to(device, non_blocking=True),
    )


def value_logit(model, v, ev):
    """Residual value (--value-residual): a * handcrafted eval / 100 + b + the net's output."""
    if getattr(model, "residual", None) is None:
        return v
    return model.residual[0] * ev + model.residual[1] + v


@torch.no_grad()
def evaluate(model, d, idx, device, batch=16384) -> dict:
    model.eval()
    sums = dict(ce=0.0, top1=0.0, top3=0.0, bce=0.0, vacc=0.0, uniform_ce=0.0)
    probs, wons, turns = [], [], []
    for i in range(0, len(idx), batch):
        b = idx[i : i + batch]
        sp, de, gl, ma, act, won, ev = to_torch(d, b, device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits, v = model(sp, de, gl, ma)
        logits, v = logits.float(), value_logit(model, v.float(), ev)
        sums["ce"] += F.cross_entropy(logits, act, reduction="sum").item()
        top = logits.topk(3, dim=-1).indices
        sums["top1"] += (top[:, 0] == act).sum().item()
        sums["top3"] += (top == act[:, None]).any(-1).sum().item()
        sums["bce"] += F.binary_cross_entropy_with_logits(v, won, reduction="sum").item()
        p = torch.sigmoid(v)
        sums["vacc"] += ((p > 0.5).float() == won).sum().item()
        sums["uniform_ce"] += torch.log(ma.sum(-1).float()).sum().item()
        probs.append(p.cpu().numpy())
        wons.append(won.cpu().numpy())
        turns.append(d["turn"][b])
    n = len(idx)
    out = {k: v / n for k, v in sums.items()}
    p, w, t = np.concatenate(probs), np.concatenate(wons), np.concatenate(turns)
    bins = np.minimum((p * 10).astype(int), 9)
    out["value_ece"] = float(
        sum(
            abs(p[bins == k].mean() - w[bins == k].mean()) * (bins == k).mean()
            for k in range(10)
            if (bins == k).any()
        )  # fmt: skip
    )
    for name, lo, hi in (("early", 0, 10), ("mid", 10, 25), ("late", 25, 10_000)):
        sel = (t >= lo) & (t < hi)
        if sel.any():
            out[f"vacc_{name}"] = float(((p[sel] > 0.5) == w[sel]).mean())
    model.train()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--size", choices=sorted(SIZES), default="medium")
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
    ap.add_argument("--eval-every", type=int, default=500)
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
    d = load(a.data)
    n = len(d["action"])
    # validation: the most recent games (whole games)
    game_time = {}
    for g, ut in zip(d["game"], d["uploadtime"], strict=True):
        game_time[g] = max(game_time.get(g, 0), ut)
    cutoff = np.quantile(np.fromiter(game_time.values(), np.int64), 1 - a.val_frac)
    is_val = np.array([game_time[g] >= cutoff for g in d["game"]])
    train_idx, val_idx = np.flatnonzero(~is_val), np.flatnonzero(is_val)
    age_days = (d["uploadtime"].max() - d["uploadtime"]) / 86400
    w = 0.5 ** (age_days / a.half_life) if a.half_life > 0 else np.ones(n)
    w = (w / w[train_idx].mean()).astype(np.float32)
    emit(dict(event="data", positions=n, games=len(game_time), train=len(train_idx),
              val=len(val_idx), load_s=round(time.time() - t0, 1),
              eff_train=float(w[train_idx].sum() ** 2 / (w[train_idx] ** 2).sum())))  # fmt: skip

    model = PolicyValueNet(DIMS, **SIZES[a.size])
    model.residual = None
    if a.value_residual:  # start exactly at the fitted handcrafted baseline
        model.residual = torch.nn.Parameter(torch.tensor([0.714, 0.078]))
        torch.nn.init.zeros_(model.value.weight)
        torch.nn.init.zeros_(model.value.bias)
    model = model.to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=a.wd)
    steps = int(a.epochs * len(train_idx) / a.batch)
    warm = max(1, steps // 50)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(1, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(s, steps) / steps)),
    )
    emit(dict(event="start", size=a.size, params=n_params, steps=steps, device=str(device),
              args=json.dumps(vars(a))))  # fmt: skip
    best = float("inf")
    probs = w[train_idx] / w[train_idx].sum()
    agg = dict(ce=0.0, bce=0.0, acc=0.0, gn=0.0, k=0)
    t_last = time.time()
    for step in range(1, steps + 1):
        if (step - 1) % 1000 == 0:  # time-weighted sampling, drawn 1000 steps at a time
            block = train_idx[rng.choice(len(train_idx), (1000, a.batch), p=probs)]
        b = block[(step - 1) % 1000]
        sp, de, gl, ma, act, won, ev = to_torch(d, b, device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits, v = model(sp, de, gl, ma)
        ce = F.cross_entropy(logits.float(), act)
        bce = F.binary_cross_entropy_with_logits(value_logit(model, v.float(), ev), won)
        loss = ce + a.value_weight * bce
        opt.zero_grad(set_to_none=True)
        loss.backward()
        gn = torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0).item()
        opt.step()
        sched.step()
        agg["ce"] += ce.item()
        agg["bce"] += bce.item()
        agg["acc"] += (logits.argmax(-1) == act).float().mean().item()
        agg["gn"] += gn
        agg["k"] += 1
        if step % 100 == 0:
            k = agg.pop("k")
            emit(dict(event="train", step=step, epoch=round(step * a.batch / len(train_idx), 3),
                      policy_ce=agg["ce"] / k, value_bce=agg["bce"] / k, policy_acc=agg["acc"] / k,
                      grad_norm=agg["gn"] / k, lr=sched.get_last_lr()[0],
                      samples_per_s=round(100 * a.batch / (time.time() - t_last))))  # fmt: skip
            agg = dict(ce=0.0, bce=0.0, acc=0.0, gn=0.0, k=0)
            t_last = time.time()
        if step % a.eval_every == 0 or step == steps:
            m = evaluate(model, d, val_idx, device)
            emit(dict(event="val", step=step, **{k: float(v) for k, v in m.items()}))
            val_loss = m["ce"] + a.value_weight * m["bce"]
            ckpt = {"model": model.state_dict(), "dims": DIMS, "size": SIZES[a.size],
                    "step": step, "val": m, "value_residual": a.value_residual}  # fmt: skip
            torch.save(ckpt, out_dir / "last.pt")
            if val_loss < best:
                best = val_loss
                torch.save(ckpt, out_dir / "best.pt")
    from safetensors.torch import save_file

    best_ckpt = torch.load(out_dir / "best.pt", weights_only=False)
    save_file({k: v.float().contiguous() for k, v in best_ckpt["model"].items()},
              out_dir / "best.safetensors")  # fmt: skip
    (out_dir / "config.json").write_text(json.dumps(
        {"dims": DIMS, "size": SIZES[a.size], "step": best_ckpt["step"], "val": best_ckpt["val"]},
        indent=2))  # fmt: skip
    emit(dict(event="done", best_val_loss=best, minutes=round((time.time() - t0) / 60, 1)))


if __name__ == "__main__":
    main()
