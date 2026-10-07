"""ISMCTS with the network on the GPU (design D13): ``trees`` independent batched searches
(root parallel, different seeds) collect their leaves in parallel threads (the Rust side
releases the GIL), one GPU forward pass evaluates all of them, the outputs go back to each tree;
the root statistics are merged by option at the end (as alpha_search's root-parallel search).
Each tree's batch stays small (``batch``), which keeps the virtual-loss distortion small; the
GPU sees ``trees * batch`` leaves (2 rows each) per call.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import alpha_search
import numpy as np

KEYS = ("sparse", "dense", "global", "mask", "hsparse", "hdense", "ent2", "glob2", "reveal",
        "turn", "rating", "eval")  # fmt: skip


def merge(batches: list[dict]) -> dict:
    out = {k: b"".join(b[k] for b in batches) for k in KEYS}
    out["rows"] = sum(b["rows"] for b in batches)
    return out


class GpuSearch:
    def __init__(self, net, trees: int = 4, batch: int = 32):
        self.net, self.trees, self.batch = net, trees, batch
        self.pool = ThreadPoolExecutor(trees)

    def run(self, states: list[str], contexts: list, seconds: float, seed: int = 0,
            iterations: int = 0) -> tuple[list, int, dict]:  # fmt: skip
        """([(our option, visits, mean value)], iterations, stats) after ``seconds`` (or, if
        > 0, at least ``iterations`` leaves in total)."""
        searches = [alpha_search.BatchSearch(states, contexts, seed=seed * 1009 + k)
                    for k in range(self.trees)]  # fmt: skip
        t0 = time.time()
        calls = 0

        def done() -> bool:
            if iterations > 0:
                return sum(s.stats()[0] for s in searches) >= iterations
            return time.time() - t0 >= seconds

        while not done():
            batches = list(self.pool.map(lambda s: s.collect(self.batch), searches))
            b = merge(batches)
            if b["rows"] == 0:
                continue
            values, logits = self.net(b)
            calls += 1
            r = 0
            for s, bi in zip(searches, batches, strict=True):
                n = bi["rows"]
                if n:
                    s.apply(values[r : r + n].tolist(), logits[r * 14 : (r + n) * 14].tolist())
                r += n
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
        return ours, int(stats[0]), info

    def close(self) -> None:
        self.pool.shutdown(wait=False)
