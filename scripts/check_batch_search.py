"""Batched ISMCTS with the GPU network (alpha_search.BatchSearch + agents.gpu_net) against the
CPU references, on real positions (design D13).

Usage: uv run --group train python scripts/check_batch_search.py --run data/train/v5/runs/v5-final \
           --data v5 --positions 40 --iterations 2000 --batch 32

For every position (its state as all ``--worlds`` worlds, its context from the data):
  1. outputs: every batch of leaves is also evaluated by the Rust CPU network
     (BatchSearch.evaluate_cpu) on the first ``--check`` positions; the largest differences;
  2. search: the batched search and the unbatched CPU search (alpha_search.ismcts) at the same
     number of iterations: how often the most visited root option agrees, and the total
     variation distance of the root visit shares (two unbatched runs with different seeds give
     the noise level);
  3. speed: leaves per second of both;
  4. with ``--trees`` > 1 also the multi-tree GPU search (agents.gpu_search: root parallel,
     ``--trees`` x ``--tree-batch``) at the same number of iterations against the CPU search.
"""

import argparse
import glob
import time

import alpha_search
import numpy as np
import pyarrow.parquet as pq

from alpha_poke.agents.gpu_net import GpuNet
from alpha_poke.agents.gpu_search import GpuSearch


def shares(root: list) -> dict:
    total = sum(v for _, v, _ in root) or 1
    return {name: v / total for name, v, _ in root}


def tv(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b))


def top(s: dict) -> str:
    return max(s, key=s.get)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--positions", type=int, default=40)
    ap.add_argument("--worlds", type=int, default=8)
    ap.add_argument("--iterations", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--check", type=int, default=10, help="positions with the CPU output check")
    ap.add_argument("--threads", type=int, default=1, help="threads descending the batched tree")
    ap.add_argument("--trees", type=int, default=0)
    ap.add_argument("--tree-batch", type=int, default=16)
    a = ap.parse_args()
    files = sorted(glob.glob(f"data/train/{a.data}/*.parquet"))
    f = next(f for f in files if pq.read_metadata(f).num_rows)
    cols = ["state", "history", "reveal", "rating_own", "rating_opp", "turn", "kind"]
    rows = [r for r in pq.read_table(f, columns=cols).slice(0, 5000).to_pylist() if r["kind"] == 0]
    rows = rows[:: max(1, len(rows) // a.positions)][: a.positions]
    net = GpuNet(a.run)
    dv = dl = 0.0
    agree_b = agree_n = 0
    tv_b, tv_n, tv_g = [], [], []
    agree_g = 0
    gs = GpuSearch(net, a.tree_batch, threads=8, trees=a.trees) if a.trees > 0 else None
    t_b = t_c = 0.0
    n_b = n_c = 0
    for i, r in enumerate(rows):
        states = [r["state"]] * a.worlds
        ctx = (list(r["reveal"]), (r["rating_own"], r["rating_opp"]), r["turn"], r["history"])
        ctxs = [ctx] * a.worlds
        bs = alpha_search.BatchSearch(states, ctxs, seed=i, threads=a.threads)
        t0 = time.time()
        while bs.stats()[0] < a.iterations:
            b = bs.collect(a.batch)
            if b["rows"] == 0:
                continue
            v, lg = net(b)
            if i < a.check:
                v2, l2 = bs.evaluate_cpu(a.run)
                v2, l2 = np.asarray(v2, np.float32), np.asarray(l2, np.float32)
                fin = np.isfinite(lg)
                assert (fin == np.isfinite(l2)).all(), "legal slots differ"
                dv = max(dv, float(np.abs(v - v2).max()))
                dl = max(dl, float(np.abs(lg[fin] - l2[fin]).max()))
            bs.apply(v.tolist(), lg.tolist())
        t_b += time.time() - t0
        n_b += bs.stats()[0]
        sb = shares(bs.root())
        runs = []
        for seed in (1000 + i, 2000 + i):
            t0 = time.time()
            ours, n, _, _ = alpha_search.ismcts(
                states, 0, iterations=a.iterations, seed=seed, model_dir=a.run,
                use_policy=True, contexts=ctxs,
            )  # fmt: skip
            t_c += time.time() - t0
            n_c += n
            runs.append(shares([(c, v, m) for c, v, m in ours]))
        if gs is not None:
            ours, _, _ = gs.run(states, ctxs, 0, seed=i, iterations=a.iterations)
            sg = shares(ours)
            agree_g += top(sg) == top(runs[0])
            tv_g.append(tv(sg, runs[0]))
        agree_b += top(sb) == top(runs[0])
        agree_n += top(runs[1]) == top(runs[0])
        tv_b.append(tv(sb, runs[0]))
        tv_n.append(tv(runs[1], runs[0]))
    n = len(rows)
    print(f"outputs (GPU vs Rust CPU, {min(n, a.check)} positions): max |value diff| {dv:.2e}, "
          f"max |logit diff| {dl:.2e}")  # fmt: skip
    print(f"search ({n} positions, {a.iterations} iterations, batch {a.batch}): top option "
          f"agrees with the unbatched CPU search {agree_b / n:.0%} (two CPU seeds: "
          f"{agree_n / n:.0%}); visit-share TV distance {np.mean(tv_b):.3f} "
          f"(two CPU seeds: {np.mean(tv_n):.3f})")  # fmt: skip
    if gs is not None:
        print(f"multi-tree GPU search ({a.trees} x {a.tree_batch}): top option agrees "
              f"{agree_g / n:.0%}, TV distance {np.mean(tv_g):.3f}")  # fmt: skip
    print(f"speed: batched GPU {n_b / t_b:.0f} leaves/s (incl. CPU checks on {a.check}), "
          f"CPU {n_c / t_c:.0f} leaves/s (1 thread)")  # fmt: skip


if __name__ == "__main__":
    main()
