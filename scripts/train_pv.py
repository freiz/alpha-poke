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
over the first K decision steps from the position (design D14-8), weight ``--mtp-weight``.
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

from alpha_poke.train.model import PolicyValueNet, TransformerPV

SIZES = {
    "small": dict(d_ent=64, d_trunk=128, d_global=32),
    "medium": dict(d_ent=128, d_trunk=256, d_global=64),
    "large": dict(d_ent=256, d_trunk=512, d_global=128),
}
T_SIZES = {
    "small": dict(d_model=96, n_layers=2, n_heads=4, d_ff=192),
    "medium": dict(d_model=128, n_layers=3, n_heads=4, d_ff=256),
    "large": dict(d_model=192, n_layers=4, n_heads=6, d_ff=384),
}
DIMS = alpha_search.feature_dims()


def featurize_shard(path: Path, cache: Path) -> int:
    """Write the shard's feature cache (if missing); returns its number of positions."""
    names = pq.read_schema(path).names
    has_hist, has_fut = "history" in names, "future" in names
    if cache.exists():
        with np.load(cache) as z:
            # caches from before the handcrafted evaluation / the history are rebuilt
            fresh = cache.stat().st_mtime >= path.stat().st_mtime  # data rebuilt since?
            ok_hist = not has_hist or ("hsp" in z.files and z["hsp"].shape[1] == DIMS["hist"])
            ok_fut = not has_fut or "fsp" in z.files
            if fresh and "evalv" in z.files and ok_hist and ok_fut:
                return len(z["action"])
    cols = ["game", "turn", "state", "action", "won", "rating", "uploadtime"]
    extra = (["history"] if has_hist else []) + (["future"] if has_fut else [])
    t = pq.read_table(path, columns=cols + extra)
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
    if has_fut:  # same encoding; steps reversed so that slot k = future step k
        fut = [";".join(reversed(x.split(";"))) for x in t.column("future").to_pylist()]
        hs, hd = DIMS["hist"], (DIMS["hist_sparse"], DIMS["hist_dense"])
        chunks = [alpha_search.featurize_history(fut[i : i + 50_000])
                  for i in range(0, len(fut), 50_000)]  # fmt: skip
        out["fsp"] = np.concatenate([np.frombuffer(c[0], np.int32).reshape(-1, hs, hd[0])[:, :4]
                                     .astype(np.int16) for c in chunks])  # fmt: skip
        out["fde"] = np.concatenate([np.frombuffer(c[1], np.float32).reshape(-1, hs, hd[1])[:, :4]
                                     .astype(np.uint8) for c in chunks])  # fmt: skip
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
    """(sparse, dense, glob, mask, action, won, handcrafted eval / 100, history sparse, history
    dense); the history is None without a history in the data"""
    hist = (
        (torch.from_numpy(d["hsp"][idx].astype(np.int64)).to(device, non_blocking=True),
         torch.from_numpy(d["hde"][idx].astype(np.float32)).to(device, non_blocking=True))
        if "hsp" in d else (None, None)
    )  # fmt: skip
    fut = (
        (torch.from_numpy(d["fsp"][idx].astype(np.int64)).to(device, non_blocking=True),
         torch.from_numpy(d["fde"][idx].astype(np.float32)).to(device, non_blocking=True))
        if "fsp" in d else (None, None)
    )  # fmt: skip
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


def value_logit(model, v, ev):
    """Residual value (--value-residual): a * handcrafted eval / 100 + b + the net's output."""
    if getattr(model, "residual", None) is None:
        return v
    return model.residual[0] * ev + model.residual[1] + v


@torch.no_grad()
def evaluate(model, d, idx, device, batch=16384) -> dict:
    model.eval()
    sums = dict(ce=0.0, top1=0.0, top2=0.0, top3=0.0, top5=0.0, bce=0.0, vacc=0.0,
                uniform_ce=0.0, n_sw=0.0, top1_sw=0.0, top3_sw=0.0, ce_sw=0.0)  # fmt: skip
    mtp = getattr(model, "mtp", 0) and "fsp" in d
    m_sum = dict(loss=0.0, acc=0.0, acc3=0.0, n=0.0, b=0)
    probs, wons, turns = [], [], []
    for i in range(0, len(idx), batch):
        b = idx[i : i + batch]
        sp, de, gl, ma, act, won, ev, hs, hd, fs, fd = to_torch(d, b, device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            out = model(sp, de, gl, ma, hs, hd, aux=True) if mtp else model(sp, de, gl, ma, hs, hd)
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
    ap.add_argument("--arch", choices=["mlp", "transformer"], default="mlp")
    ap.add_argument("--history", action="store_true", help="feed the decision-step history")
    ap.add_argument("--hist-len", type=int, default=8, help="most recent steps the model reads")
    ap.add_argument("--mtp", type=int, default=0, help="future steps to predict (auxiliary)")
    ap.add_argument("--mtp-weight", type=float, default=0.5)
    ap.add_argument("--mtp-decay", type=float, default=1.0, help="weight of future step k: d^k")
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
    ap.add_argument("--val-cutoff", type=int, default=None,
                    help="validation = games uploaded at / after this unix time (fixed split "
                         "across datasets; v1's 3%% cutoff is 1776921722)")  # fmt: skip
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
    cutoff = a.val_cutoff or np.quantile(np.fromiter(game_time.values(), np.int64), 1 - a.val_frac)
    is_val = np.array([game_time[g] >= cutoff for g in d["game"]])
    train_idx, val_idx = np.flatnonzero(~is_val), np.flatnonzero(is_val)
    age_days = (d["uploadtime"].max() - d["uploadtime"]) / 86400
    w = 0.5 ** (age_days / a.half_life) if a.half_life > 0 else np.ones(n)
    w = (w / w[train_idx].mean()).astype(np.float32)
    vw = np.ones(n, np.float32)  # value loss weights
    if a.value_per_game > 0:
        _, inv, cnt = np.unique(d["game"], return_inverse=True, return_counts=True)
        vw = np.minimum(1.0, a.value_per_game / cnt[inv]).astype(np.float32)
    assert not a.history or "hsp" in d, "--history needs data built with a history column"
    emit(dict(event="data", positions=n, games=len(game_time), train=len(train_idx),
              val=len(val_idx), val_cutoff=int(cutoff), load_s=round(time.time() - t0, 1),
              eff_train=float(w[train_idx].sum() ** 2 / (w[train_idx] ** 2).sum())))  # fmt: skip

    size = (T_SIZES if a.arch == "transformer" else SIZES)[a.size]
    assert a.hist_len <= DIMS["hist"], f"--hist-len > the {DIMS['hist']} featurized steps"
    dims = DIMS | {"hist": a.hist_len}
    assert not a.mtp or (a.arch == "transformer" and "fsp" in d), "--mtp: transformer + future data"
    if a.arch == "transformer":
        model = TransformerPV(dims, **size, history=a.history, mtp=a.mtp)
    else:
        model = PolicyValueNet(dims, **size, history=a.history)
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
    emit(dict(event="start", arch=a.arch, history=a.history, size=a.size, params=n_params,
              steps=steps, device=str(device), args=json.dumps(vars(a))))  # fmt: skip
    best = float("inf")
    probs = w[train_idx] / w[train_idx].sum()
    agg = dict(ce=0.0, bce=0.0, acc=0.0, gn=0.0, k=0)
    t_last = time.time()
    for step in range(1, steps + 1):
        if (step - 1) % 1000 == 0:  # time-weighted sampling, drawn 1000 steps at a time
            block = train_idx[rng.choice(len(train_idx), (1000, a.batch), p=probs)]
        b = block[(step - 1) % 1000]
        sp, de, gl, ma, act, won, ev, hs, hd, fs, fd = to_torch(d, b, device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            out = model(sp, de, gl, ma, hs, hd, aux=bool(a.mtp))
        logits, v = out[0], out[1]
        ce = F.cross_entropy(logits.float(), act)
        bw = torch.from_numpy(vw[b]).to(device)
        vl = value_logit(model, v.float(), ev)
        bce = (F.binary_cross_entropy_with_logits(vl, won, reduction="none") * bw).sum() / bw.sum()
        loss = ce + a.value_weight * bce
        if a.mtp:
            tg = mtp_targets(sp, fs, fd, a.mtp)
            loss = loss + a.mtp_weight * mtp_loss(out[2], tg, a.mtp_decay)[0]
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
            ckpt = {"model": model.state_dict(), "dims": dims, "size": size, "arch": a.arch,
                    "history": a.history, "mtp": a.mtp,
                    "step": step, "val": m, "value_residual": a.value_residual}  # fmt: skip
            torch.save(ckpt, out_dir / "last.pt")
            if val_loss < best:
                best = val_loss
                torch.save(ckpt, out_dir / "best.pt")
    from safetensors.torch import save_file

    best_ckpt = torch.load(out_dir / "best.pt", weights_only=False)
    # the shared embedding tables keep their v1 names (emb.species -> species) for the Rust loader
    save_file({k.removeprefix("emb."): v.float().contiguous()
               for k, v in best_ckpt["model"].items()}, out_dir / "best.safetensors")  # fmt: skip
    (out_dir / "config.json").write_text(json.dumps(
        {"dims": dims, "size": size, "arch": a.arch, "history": a.history,
         "step": best_ckpt["step"], "val": best_ckpt["val"]}, indent=2))  # fmt: skip
    emit(dict(event="done", best_val_loss=best, minutes=round((time.time() - t0) / 60, 1)))


if __name__ == "__main__":
    main()
