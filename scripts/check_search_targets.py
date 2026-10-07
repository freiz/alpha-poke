"""Self-play search settings (design D5 / D13): iterations and root Dirichlet noise, measured by
the quality of the search's root visit shares as training targets.

Usage: uv run --group train python scripts/check_search_targets.py \
           --run data/train/v5/runs/v5-final --data v5 --positions 60

On real positions (the state as all worlds, the context from the data):
  * reference: a deep noise-free search (single tree, ``--deep`` iterations) per position;
  * the network prior itself and noise-free single-tree searches of each ``--iterations``:
    how often the top option agrees with the reference, the total variation distance of the
    shares, the time per search (one thread);
  * at ``--noise-iterations``, root noise eps x total concentration (alpha = conc / options):
    target quality (agreement / TV with the noise-free reference) and exploration (of the
    options with prior < 5%, the share that gets >= 10% of the visits; of those, the share the
    reference also gives >= 10%).
Searches of different positions run in parallel threads (the Rust side releases the GIL).
"""

import argparse
import glob
import time
from concurrent.futures import ThreadPoolExecutor

import alpha_search
import numpy as np
import pyarrow.parquet as pq


def shares(root: list) -> dict:
    total = sum(v for _, v, _ in root) or 1
    return {c: v / total for c, v, _ in root}


def top(s: dict) -> str:
    return max(s, key=s.get)


def tv(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--positions", type=int, default=60)
    ap.add_argument("--worlds", type=int, default=32)
    ap.add_argument("--deep", type=int, default=16000)
    ap.add_argument("--iterations", default="500,1000,2000,3000,4000")
    ap.add_argument("--noise-iterations", type=int, default=3000)
    ap.add_argument("--eps", default="0,0.1,0.25,0.4")
    ap.add_argument("--conc", default="3,10,30")
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    files = sorted(glob.glob(f"data/train/{a.data}/*.parquet"))
    f = next(f for f in files[1:] if pq.read_metadata(f).num_rows)
    cols = ["state", "history", "reveal", "rating_own", "rating_opp", "turn", "kind"]
    rows = [r for r in pq.read_table(f, columns=cols).slice(0, 6000).to_pylist() if r["kind"] == 0]
    rows = rows[:: max(1, len(rows) // a.positions)][: a.positions]
    jobs = []
    for r in rows:
        ctx = (list(r["reveal"]), (r["rating_own"], r["rating_opp"]), r["turn"], r["history"])
        jobs.append(([r["state"]] * a.worlds, [ctx] * a.worlds))
    pool = ThreadPoolExecutor(a.threads)

    def search(k: int, it: int, seed: int, noise=(0.0, 10.0)) -> tuple[dict, float]:
        states, ctxs = jobs[k]
        t0 = time.time()
        ours, _, _, _ = alpha_search.ismcts(
            states, 0, iterations=it, seed=seed, model_dir=a.run, use_policy=True,
            contexts=ctxs, root_noise=noise,
        )  # fmt: skip
        return shares(ours), time.time() - t0

    n = len(jobs)
    ref = [s for s, _ in pool.map(lambda k: search(k, a.deep, 7 + k), range(n))]
    priors = [dict(alpha_search.root_priors(*jobs[k][:1], a.run, contexts=jobs[k][1]))
              for k in range(n)]  # fmt: skip
    print(f"{n} positions, {a.worlds} worlds; reference: {a.deep} iterations")
    ag = np.mean([top(p) == top(r) for p, r in zip(priors, ref, strict=True)])
    d = np.mean([tv(p, r) for p, r in zip(priors, ref, strict=True)])
    print(f"network prior: top agrees {ag:.0%}, TV {d:.3f}")
    print("iterations  top agrees  TV     s/search")
    for it in [int(x) for x in a.iterations.split(",")]:
        res = list(pool.map(lambda k, it=it: search(k, it, 1000 + k), range(n)))
        ag = np.mean([top(s) == top(r) for (s, _), r in zip(res, ref, strict=True)])
        d = np.mean([tv(s, r) for (s, _), r in zip(res, ref, strict=True)])
        print(f"{it:10d}  {ag:9.0%}  {d:.3f}  {np.mean([t for _, t in res]):.2f}", flush=True)
    print(f"root noise at {a.noise_iterations} iterations (quality vs the noise-free reference; "
          f"exploration = low-prior options reaching 10% of the visits)")  # fmt: skip
    print("eps   conc  top agrees  TV     explored  of which useful")
    for eps in [float(x) for x in a.eps.split(",")]:
        for conc in [float(x) for x in a.conc.split(",")] if eps > 0 else [10.0]:
            res = list(pool.map(lambda k, e=eps, c=conc: search(
                k, a.noise_iterations, 2000 + k, (e, c)), range(n)))  # fmt: skip
            ag = np.mean([top(s) == top(r) for (s, _), r in zip(res, ref, strict=True)])
            d = np.mean([tv(s, r) for (s, _), r in zip(res, ref, strict=True)])
            low = hit = useful = 0
            for (s, _), r, b in zip(res, ref, priors, strict=True):
                for opt in s:
                    if b.get(opt, 0) < 0.05:
                        low += 1
                        if s[opt] >= 0.10:
                            hit += 1
                            useful += r.get(opt, 0) >= 0.10
            print(f"{eps:4.2f}  {conc:4.0f}  {ag:9.0%}  {d:.3f}  {hit / max(1, low):7.1%}  "
                  f"{useful / max(1, hit):6.0%}", flush=True)  # fmt: skip


if __name__ == "__main__":
    main()
