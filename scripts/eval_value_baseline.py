"""Offline bar for the value net: poke-engine's handcrafted evaluation as a win predictor.

Usage: uv run --group train python scripts/eval_value_baseline.py --data v1

Same validation split as scripts/train_pv.py (the most recent --val-frac of the games). The
evaluation is turned into a probability by a logistic fit p = sigmoid(a * eval + b) on a sample
of training positions (the search itself uses sigmoid(0.0125 * (eval - root eval)), a relative
scale). Reports value BCE, accuracy, ECE and accuracy by game phase, the same metrics as the
value head; the net must beat these to be worth replacing the handcrafted evaluation.
"""

import argparse
import glob
from pathlib import Path

import alpha_search
import numpy as np
import pyarrow.parquet as pq
import torch


def metrics(p: np.ndarray, w: np.ndarray, t: np.ndarray) -> dict:
    eps = 1e-6
    out = {
        "bce": float(-(w * np.log(p + eps) + (1 - w) * np.log(1 - p + eps)).mean()),
        "acc": float(((p > 0.5) == w).mean()),
    }
    bins = np.minimum((p * 10).astype(int), 9)
    out["ece"] = float(
        sum(
            abs(p[bins == k].mean() - w[bins == k].mean()) * (bins == k).mean()
            for k in range(10)
            if (bins == k).any()
        )  # fmt: skip
    )
    for name, lo, hi in (("early", 0, 10), ("mid", 10, 25), ("late", 25, 10_000)):
        sel = (t >= lo) & (t < hi)
        out[f"acc_{name}"] = float(((p[sel] > 0.5) == w[sel]).mean())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--val-frac", type=float, default=0.03)
    ap.add_argument("--fit-n", type=int, default=300_000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    files = sorted(glob.glob(str(Path("data/train") / a.data / "*.parquet")))
    files = [f for f in files if pq.read_metadata(f).num_rows]  # shards without games
    # pass 1, light columns only: the validation split (same rule as train_pv)
    game_time: dict = {}
    for f in files:
        t = pq.read_table(f, columns=["game", "uploadtime"])
        for g, u in zip(t.column("game").to_pylist(), t.column("uploadtime").to_pylist(),
                        strict=True):  # fmt: skip
            game_time[g] = max(game_time.get(g, 0), u)
    cutoff = np.quantile(np.fromiter(game_time.values(), np.int64), 1 - a.val_frac)
    n_train = sum(pq.read_metadata(f).num_rows for f in files) - sum(
        1 for f in files for g in pq.read_table(f, columns=["game"]).column("game").to_pylist()
        if game_time[g] >= cutoff
    )  # fmt: skip
    keep_p = min(1.0, a.fit_n / max(1, n_train))
    # pass 2, shard by shard: evaluate only the positions used (the fit sample and validation);
    # never all state strings at once (8M x ~3 KB: the 2026-10-06 OOM)
    rng = np.random.default_rng(a.seed)
    x_fit, y_fit, x_val, y_val, t_val = [], [], [], [], []
    for f in files:
        t = pq.read_table(f, columns=["game", "turn", "state", "won"])
        val = np.array([game_time[g] >= cutoff for g in t.column("game").to_pylist()])
        fit = ~val & (rng.random(len(val)) < keep_p)
        won = t.column("won").to_numpy().astype(np.float32)
        for sel, xs, ys in ((fit, x_fit, y_fit), (val, x_val, y_val)):
            idx = np.flatnonzero(sel)
            if len(idx):
                xs.append(np.asarray(alpha_search.evaluate(
                    t.column("state").take(idx).to_pylist()), np.float32))  # fmt: skip
                ys.append(won[idx])
        t_val.append(t.column("turn").to_numpy()[val])
        del t
    x_fit, y_fit = np.concatenate(x_fit), np.concatenate(y_fit)
    x_val, y_val, t_val = np.concatenate(x_val), np.concatenate(y_val), np.concatenate(t_val)
    # logistic fit p = sigmoid(a * eval + b)
    xa, ya = torch.tensor(x_fit / 100), torch.tensor(y_fit)
    ab = torch.zeros(2, requires_grad=True)
    opt = torch.optim.LBFGS([ab], max_iter=200)

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(ab[0] * xa + ab[1], ya)
        loss.backward()
        return loss

    opt.step(closure)
    sa, sb = ab.detach().numpy()
    p_val = 1 / (1 + np.exp(-(sa * x_val / 100 + sb)))
    p_search = 1 / (1 + np.exp(-0.0125 * x_val))  # the search's own scale (no root offset)
    print(f"positions: fit {len(x_fit)}, val {len(x_val)}; fitted p = sigmoid({sa:.3f} * "
          f"eval/100 + {sb:.3f}) (the search uses 1.25 * eval/100)")  # fmt: skip
    print("handcrafted eval, fitted scale:", {k: round(v, 4) for k, v in
          metrics(p_val, y_val, t_val).items()})  # fmt: skip
    print("handcrafted eval, search scale:", {k: round(v, 4) for k, v in
          metrics(p_search, y_val, t_val).items()})  # fmt: skip
    print("constant 0.5:", {k: round(v, 4) for k, v in
          metrics(np.full(len(x_val), 0.5), y_val, t_val).items()})  # fmt: skip


if __name__ == "__main__":
    main()
