"""Rust transformer inference (alpha_search.tnet_forward) against PyTorch on real positions.

Usage: uv run --group train python scripts/check_tnet.py --run data/train/v5/runs/v5-final \
           --data v5 --n 4000

Both sides get the same float32 inputs (the Rust featurizers, no float16 cache); side one's view
and side two's (flip). Reports the largest differences of the legal logits and of the value
logits, and how often the argmax agrees. Run after every change to the Rust forward pass.
"""

import argparse
import glob
import time
from pathlib import Path

import alpha_search
import numpy as np
import pyarrow.parquet as pq
import torch

from alpha_poke.train.load import load_run

D = alpha_search.feature_dims()


def flip_history(h: str) -> str:
    return ";".join("/".join(reversed(s.split("/", 1))) if "/" in s else s for s in h.split(";"))


def torch_forward(model, states, reveal, rating, turn, hist, flip, post=None):
    n, e = len(states), D["entities"]
    sp, de, gl, ma = alpha_search.featurize(states, flip=flip)
    hs, hd = alpha_search.featurize_history([flip_history(h) if flip else h for h in hist])
    ent2, glob2, ent4 = alpha_search.featurize_extra_full(states, flip=flip)
    ent3, glob3 = alpha_search.featurize_counts(states, flip=flip)
    ev = np.asarray(alpha_search.evaluate(states), np.float32) * (-1 if flip else 1)

    def t(buf, dt, shape, cast):
        return torch.from_numpy(np.frombuffer(buf, dt).reshape(shape).astype(cast))

    if flip:
        reveal = np.concatenate([reveal[:, 6:], reveal[:, :6]], 1)
        rating = rating[:, ::-1].copy()
    x = {
        "reveal": torch.from_numpy(reveal.astype(np.int64)),
        "ent2": t(ent2, np.float32, (n, e, D["ent_extra"]), np.float32),
        "glob2": t(glob2, np.float32, (n, D["global_extra"]), np.float32),
        "ent3": t(ent3, np.float32, (n, e, D["ent_count"]), np.float32),
        "glob3": t(glob3, np.float32, (n, D["global_count"]), np.float32),
        "ent4": t(ent4, np.float32, (n, e, D["ent_new"]), np.float32),
        # F2: side one's view, halves swapped for side two's (as the Rust Input::new)
        "post": torch.from_numpy(
            (
                np.zeros((n, e, D["post"]), np.float32)
                if post is None
                else (np.concatenate([post[:, 6:], post[:, :6]], 1) if flip else post)
            ).copy()
        ),
        "turn": torch.from_numpy(turn.astype(np.int64)),
        "rating": torch.from_numpy(rating.astype(np.int64)),
    }
    with torch.no_grad():
        logits, v = model(
            t(sp, np.int32, (n, e, D["sparse"]), np.int64),
            t(de, np.float32, (n, e, D["dense"]), np.float32),
            t(gl, np.float32, (n, D["global"]), np.float32),
            t(ma, np.uint8, (n, D["actions"]), bool),
            t(hs, np.int32, (n, D["hist"], D["hist_sparse"]), np.int64),
            t(hd, np.float32, (n, D["hist"], D["hist_dense"]), np.float32),
            x=x,
        )
        if model.residual is not None:
            v = model.residual[0] * torch.from_numpy(ev / 100) + model.residual[1] + v
    return logits.numpy(), v.numpy()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--tol", type=float, default=1e-3, help="fail above this difference")
    a = ap.parse_args()
    files = sorted(glob.glob(f"data/train/{a.data}/*.parquet"))
    f = next(f for f in files if pq.read_metadata(f).num_rows)
    cols = ["state", "history", "reveal", "rating_own", "rating_opp", "turn"]
    cols += ["post"] if "post" in pq.read_schema(f).names else []
    tb = pq.read_table(f, columns=cols).slice(0, a.n)
    post = (np.asarray(tb.column("post").to_pylist(), np.float32).reshape(-1, 12, D["post"]) / 255
            if "post" in cols else None)  # fmt: skip
    states, hist = tb.column("state").to_pylist(), tb.column("history").to_pylist()
    reveal = np.asarray(tb.column("reveal").to_pylist(), np.uint8)
    rating = np.stack([np.asarray(tb.column(c).to_pylist(), np.int32)
                       for c in ("rating_own", "rating_opp")], 1)  # fmt: skip
    turn = np.asarray(tb.column("turn").to_pylist(), np.int32)
    model = load_run(Path(a.run), torch.device("cpu")).float()
    worst = 0.0
    for flip in (False, True):
        lt, vt = torch_forward(model, states, reveal, rating, turn, hist, flip, post)
        t0 = time.time()
        lr, vr = alpha_search.tnet_forward(a.run, states, [list(r) for r in reveal],
                                           [tuple(r) for r in rating.tolist()], turn.tolist(),
                                           hist, flip,
                                           None if post is None else
                                           [list(map(float, r.ravel())) for r in post])  # fmt: skip
        dt = time.time() - t0
        lr, vr = np.asarray(lr, np.float32).reshape(-1, 14), np.asarray(vr, np.float32)
        legal = np.isfinite(lt)
        assert (legal == np.isfinite(lr)).all(), "legal slots differ"
        dl = np.abs(lt[legal] - lr[legal]).max()
        dv = np.abs(vt - vr).max()
        lt_m, lr_m = np.where(legal, lt, -1e9), np.where(legal, lr, -1e9)
        agree = (lt_m.argmax(1) == lr_m.argmax(1)).mean()
        print(f"flip={flip}: max |logit diff| {dl:.2e}, max |value diff| {dv:.2e}, "
              f"argmax agree {agree:.2%}  ({len(states)} positions, rust {dt:.2f}s)")  # fmt: skip
        worst = max(worst, dl, dv)
    print("OK" if worst <= a.tol else f"FAIL: {worst:.2e} > {a.tol}")
    raise SystemExit(0 if worst <= a.tol else 1)


if __name__ == "__main__":
    main()
