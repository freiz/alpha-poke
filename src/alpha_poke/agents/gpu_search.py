"""ISMCTS with the network on the GPU (design D13): one batched search tree
(alpha_search.BatchSearch) with ``threads`` threads descending it in parallel (tree parallel,
virtual loss); each round collects ``batch`` new leaves, one GPU forward pass evaluates them
(2 rows each: both sides' views), the outputs are backed up. ``trees`` > 1 adds independent
root-parallel trees (merged by option at the end); measured not to help (8 trees of ~2k
iterations choose like one tree of 2k), kept for comparisons.
Defaults (2026-10-07, 0.5 s per decision, agreement with a deep 16k-iteration search on 40
positions): batch 32 x 8 threads ~11k leaves per decision, 75% same top option (CPU search
3.6k leaves, 65%; two deep searches 82%); larger batches lose more to virtual loss than they
gain (64: 70%, 128: 57%).
"""

import time
from concurrent.futures import ThreadPoolExecutor

import alpha_search
import numpy as np

KEYS = ("sparse", "dense", "global", "mask", "hsparse", "hdense", "ent2", "glob2", "ent3",
        "glob3", "reveal", "turn", "rating", "eval")  # fmt: skip


def merge(batches: list[dict]) -> dict:
    out = {k: b"".join(b[k] for b in batches) for k in KEYS}
    out["rows"] = sum(b["rows"] for b in batches)
    return out


class GpuSearch:
    def __init__(self, net, batch: int = 32, threads: int = 8, trees: int = 1, vl: int = 1,
                 full: bool = False):  # fmt: skip
        """``full``: the network reads the v7 entity inputs (net_context.needs_full)."""
        self.net, self.trees, self.batch, self.threads, self.vl = net, trees, batch, threads, vl
        self.full = full
        self.pool = ThreadPoolExecutor(trees)

    def run(self, states: list[str], contexts: list, seconds: float, seed: int = 0,
            iterations: int = 0, root_noise: tuple[float, float] = (0.0, 10.0),
            ) -> tuple[list, int, dict]:  # fmt: skip
        """([(our option, visits, mean value)], iterations, stats) after ``seconds`` (or, if
        > 0, at least ``iterations`` leaves in total). ``root_noise``: Dirichlet (eps, total
        concentration) at the root, both sides. With one tree, stats["record"] is the root's
        result in the network's action slots (``BatchSearch.record``, design D15-3)."""
        searches = [alpha_search.BatchSearch(states, contexts, seed=seed * 1009 + k,
                                             threads=self.threads, vl=self.vl,
                                             root_noise=root_noise, full=self.full)
                    for k in range(self.trees)]  # fmt: skip
        t0 = time.time()
        calls = 0

        def done() -> bool:
            if iterations > 0:
                return sum(s.stats()[0] for s in searches) >= iterations
            return time.time() - t0 >= seconds

        def collect() -> tuple[list, dict]:
            if self.trees == 1:
                batches = [searches[0].collect(self.batch)]
            else:
                batches = list(self.pool.map(lambda s: s.collect(self.batch), searches))
            return batches, merge(batches)

        def finish(batches: list, handle) -> None:
            values, logits, turns = self.net.result(handle)
            r = 0
            for s, bi in zip(searches, batches, strict=True):
                n = bi["rows"]
                if n:
                    t = turns[r : r + n].tolist() if turns is not None else None
                    s.apply(values[r : r + n].tolist(), logits[r * 14 : (r + n) * 14].tolist(), t)
                r += n

        # pipeline: the next batch is collected while the GPU evaluates the previous one
        inflight = None
        while not done():
            batches, b = collect()
            if inflight is not None:
                finish(*inflight)
                inflight = None
            if b["rows"]:
                inflight = (batches, self.net.launch(b))
                calls += 1
        if inflight is not None:
            finish(*inflight)
        merged: dict = {}
        for s in searches:
            for name, visits, mean in s.root():
                v0, m0 = merged.get(name, (0, 0.0))
                total = v0 + visits
                merged[name] = (total, (m0 * v0 + mean * visits) / total if total else 0.0)
        stats = np.array([s.stats() for s in searches]).sum(0)
        ours = [(name, v, m) for name, (v, m) in merged.items()]
        info = {"iterations": int(stats[0]), "collisions": int(stats[1]), "nodes": int(stats[2]),
                "gpu_calls": calls}  # fmt: skip
        if self.trees == 1:
            info["record"] = searches[0].record()
        return ours, int(stats[0]), info

    def close(self) -> None:
        self.pool.shutdown(wait=False)
