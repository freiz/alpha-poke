"""GPU inference in bfloat16 vs float32 (2026-10-10): speed and agreement on real positions.

* accuracy: root positions of a self-play generation's decisions (both views, as the search
  evaluates them); per row: |value difference| (win probability), the policy's KL(fp32 ||
  bf16) over the legal actions and whether the top action changes;
* speed: rows per second of the batched forward pass (CUDA graphs, torch.compile as in
  self-play) at each padded batch size.

uv run python scripts/bench_precision.py --run data/train/v5/runs/sp-gen2 --gen 3
"""

import argparse
import glob
import json
import random
import time

import alpha_search
import numpy as np


def batches(pattern: str, n: int, per_batch: int, seed: int) -> list[dict]:
    """GpuNet input batches of ``per_batch`` root positions (two views each) drawn from the
    decision records of ``pattern``."""
    files = sorted(glob.glob(pattern))
    rng = random.Random(seed)
    recs = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                if rng.random() < 0.02:
                    recs.append(json.loads(line))
                if len(recs) >= n:
                    break
        if len(recs) >= n:
            break
    out = []
    for k in range(0, len(recs) - per_batch + 1, per_batch):
        chunk = recs[k : k + per_batch]
        searches = [alpha_search.BatchSearch(
            [d["state"]], [(d["reveal"], tuple(d["ratings"]), d["ctx_turn"], d["history"])],
            seed=j, threads=1, vl=1) for j, d in enumerate(chunk)]  # fmt: skip
        b, _, _ = alpha_search.collect_many(searches, 1, 8)
        out.append(b)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--gen", type=int, required=True, help="decisions of this generation")
    ap.add_argument("--n", type=int, default=8192, help="positions for the accuracy test")
    ap.add_argument("--compile", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--reps", type=int, default=50, help="timed calls per batch size")
    a = ap.parse_args()
    import torch

    from alpha_poke.agents.gpu_net import SIZES, GpuNet

    data = batches(f"data/selfplay/gen{a.gen}/decisions-w*.jsonl", a.n, 512, 0)
    rows = sum(b["rows"] for b in data)
    nets = {d: GpuNet(a.run, compile=a.compile, dtype=d) for d in ("fp32", "bf16")}
    out = {}
    res = {d: [net(b) for b in data] for d, net in nets.items()}
    vd, kl, top = [], [], []
    for (v32, l32), (v16, l16), b in zip(res["fp32"], res["bf16"], data, strict=True):
        n = b["rows"]
        mask = np.frombuffer(b["mask"], np.uint8).reshape(n, -1).astype(bool)
        l32, l16 = l32.reshape(n, -1), l16.reshape(n, -1)
        p32 = 1 / (1 + np.exp(-v32))
        p16 = 1 / (1 + np.exp(-v16))
        vd.append(np.abs(p32 - p16))
        for i in range(n):
            m = mask[i]
            if m.sum() < 2:
                continue
            a32 = l32[i][m] - l32[i][m].max()
            a16 = l16[i][m] - l16[i][m].max()
            q32 = np.exp(a32) / np.exp(a32).sum()
            q16 = np.exp(a16) / np.exp(a16).sum()
            kl.append(float((q32 * (np.log(q32 + 1e-12) - np.log(q16 + 1e-12))).sum()))
            top.append(int(q32.argmax() == q16.argmax()))
    vd = np.concatenate(vd)
    out["accuracy"] = {"rows": int(rows), "value_abs_diff_mean": float(vd.mean()),
                       "value_abs_diff_p99": float(np.quantile(vd, 0.99)),
                       "value_abs_diff_max": float(vd.max()),
                       "policy_kl_mean": float(np.mean(kl)), "policy_kl_p99":
                       float(np.quantile(kl, 0.99)), "top1_same": float(np.mean(top))}  # fmt: skip
    print(json.dumps(out["accuracy"], indent=1), flush=True)
    # speed: a batch of real positions per padded size (rows = 2 x positions), the forward
    # pass replayed (CUDA graph), synchronized
    speed = {}
    for size in SIZES:
        if size < 64:
            continue
        sub = batches(f"data/selfplay/gen{a.gen}/decisions-w*.jsonl", size // 2, size // 2, 1)[0]
        for d, net in nets.items():
            for _ in range(5):
                net(sub)
            torch.cuda.synchronize()
            t = time.time()
            for _ in range(a.reps):
                net(sub)
            torch.cuda.synchronize()
            dt_ = (time.time() - t) / a.reps
            speed[f"{d}/{size}"] = {"ms": round(dt_ * 1000, 3), "rows_per_s": round(size / dt_)}
            print(d, size, speed[f"{d}/{size}"], flush=True)
    out["speed"] = speed
    print(json.dumps(out))


if __name__ == "__main__":
    main()
