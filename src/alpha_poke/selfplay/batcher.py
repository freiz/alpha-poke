"""Cross-game batching of searches on the GPU (design D15-2).

One ``Batcher`` per process: a thread runs every submitted search (``alpha_search.BatchSearch``,
one descent thread each) in shared rounds: each round collects a few new leaves from every
search that still needs iterations (``collect_many``, the searches in parallel), one GPU
forward pass for all of them, and the outputs go back (``apply_many``). Pipelined: the next
round is collected while the GPU evaluates the previous one. A search that reached its
iterations and has no batch in flight is finished: its future gets (record, iterations).
Few leaves per search per round = little virtual loss: each search is close to a sequential
search, the batch is large because there are many searches."""

import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field

import alpha_search
import numpy as np

log = logging.getLogger(__name__)

MAX_LEAVES = 512  # GpuNet's largest CUDA graph: 1024 rows = 512 leaves (two views each)


# the moves-left term of our searches (self-play, the evaluations, play_public; "slope,cap,
# threshold[,loser]", ``parse_ml``; design v6). 2026-10-15 (from gen 8, v6): ml3, the winning
# side only (A/B 50.96% +- 2.42%, wins ~3 turns shorter; both sides stalled to the turn cap)
SEARCH_ML = "0.005,0.03,0.5,0"


def ml_for(run: str) -> str:
    """SEARCH_ML if the network ``run`` has the remaining-turns head, else "" (off)."""
    import json
    from pathlib import Path

    cfg = json.loads((Path(run) / "config.json").read_text())
    return SEARCH_ML if "turns" in cfg.get("aux_heads", ()) else ""


def parse_ml(s: str | None) -> tuple[float, float, float, bool]:
    """The moves-left term's "slope,cap,threshold[,loser]" (alpha_search MlParams; design v6)
    -> a tuple; loser 0 = the winning side only (default 1: both sides); None / "" = off."""
    if not s:
        return (0.0, 0.0, 0.0, False)
    v = s.split(",")
    slope, cap, threshold = (float(x) for x in v[:3])
    return (slope, cap, threshold, len(v) > 3 and v[3].strip() == "0")


@dataclass
class _Job:
    search: object
    target: int
    future: Future
    inflight: int = 0
    # (the search's input, written out when it fails: data/selfplay/diag/search_failures.jsonl)
    states: list | None = None
    contexts: list | None = None
    seed: int = 0
    t0: float = field(default_factory=time.time)


class Batcher:
    def __init__(self, model: str, leaves: int = 8, threads: int = 8, dtype: str | None = None,
                 ml: tuple[float, float, float, bool] = (0.0, 0.0, 0.0, False)):  # fmt: skip
        """``ml``: the moves-left term of every search (``parse_ml``; needs a network with the
        remaining-turns head)."""
        from alpha_poke.agents.gpu_net import GpuNet

        self.net = GpuNet(model, dtype=dtype)
        # (a network with the v7 entity groups: the searches compute their inputs)
        from alpha_poke.agents.net_context import needs_full, needs_post

        self.full = needs_full(model)
        # (a network reading F2: the contexts carry the root's posterior)
        self.post = needs_post(model)
        assert ml[0] <= 0 or self.net.has_turns, f"{model}: no remaining-turns head for ml {ml}"
        self.leaves, self.threads, self.ml = leaves, threads, ml
        self.queue: queue.SimpleQueue = queue.SimpleQueue()
        self.stats = {"rounds": 0, "rows": 0, "searches": 0, "gpu_s": 0.0, "collect_s": 0.0}
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, states: list[str], contexts: list, iterations: int, seed: int,
               root_noise: tuple[float, float]) -> Future:  # fmt: skip
        """A search of ``iterations`` leaves; the future's result: (record, iterations)."""
        f: Future = Future()
        self.queue.put((states, contexts, iterations, seed, root_noise, f))
        return f

    def _intake(self, active: list, block: bool) -> None:
        while True:
            try:
                item = self.queue.get(block=block and not active)
            except queue.Empty:
                return
            states, ctxs, iters, seed, noise, f = item
            try:
                bs = alpha_search.BatchSearch(states, ctxs, seed=seed, threads=1, vl=1,
                                              root_noise=noise, ml=self.ml,
                                              full=self.full)  # fmt: skip
                active.append(_Job(bs, iters, f, states=states, contexts=ctxs, seed=seed))
            except Exception as e:  # noqa: BLE001 - the game falls back, the batcher goes on
                f.set_exception(e)
            block = False

    def _fail(self, active: list, jobs: list, what: str) -> None:
        for j in jobs:
            if j in active:
                active.remove(j)
            if not j.future.done():
                j.future.set_exception(RuntimeError(f"search failed in {what}"))
        self.stats["failed"] = self.stats.get("failed", 0) + len(jobs)
        log.warning("batcher: %d search(es) failed in %s (engine panic?)", len(jobs), what)
        # (the failed searches' input, to reproduce them: 2026-10-21, a stat stage of +7 in the
        # engine's evaluation, 1 in 1,200 games)
        try:
            import json
            import time
            from pathlib import Path

            out = Path(__file__).resolve().parents[3] / "data" / "selfplay" / "diag" / "search_failures.jsonl"
            with open(out, "a") as fh:
                for j in jobs:
                    fh.write(json.dumps({"time": time.time(), "what": what, "seed": j.seed, "target": j.target,
                                         "states": j.states, "contexts": j.contexts}, default=repr) + "\n")
        except Exception:  # noqa: BLE001 - diagnostics only
            log.exception("batcher: could not write the failed searches")

    def _loop(self) -> None:
        active: list[_Job] = []
        inflight = None  # (jobs, rows, handle)
        while True:
            try:
                inflight = self._round(active, inflight)
            except BaseException:  # noqa: BLE001 - never die silently: the games would hang
                log.exception("batcher round failed; failing every pending search")
                for j in active:
                    if not j.future.done():
                        j.future.set_exception(RuntimeError("batcher round failed"))
                self.stats["failed"] = self.stats.get("failed", 0) + len(active)
                active.clear()
                inflight = None

    def _round(self, active: list, inflight):
        self._intake(active, block=inflight is None)
        want = [j for j in active if j.search.stats()[0] < j.target]
        # nothing pending when collected: iterations before the collect
        idle = {id(j): j.search.stats()[0] for j in want if j.inflight == 0}
        batch, rows = None, []
        if want:
            k = max(1, min(self.leaves, MAX_LEAVES // len(want)))
            t = time.time()
            batch, rows, failed = alpha_search.collect_many([j.search for j in want], k,
                                                            self.threads)  # fmt: skip
            self.stats["collect_s"] += time.time() - t
            if any(failed):
                # a failed search contributed no rows: drop it (its in-flight batch, if any,
                # is applied below and ignored)
                self._fail(active, [j for j, f in zip(want, failed, strict=True) if f], "collect")
        if inflight is not None:
            jobs, rows_i, h = inflight
            t = time.time()
            values, logits, turns = self.net.result(h)
            self.stats["gpu_s"] += time.time() - t
            bad = alpha_search.apply_many(
                [j.search for j in jobs], np.ascontiguousarray(values, np.float32).tobytes(),
                np.ascontiguousarray(logits, np.float32).tobytes(), rows_i, self.threads,
                np.ascontiguousarray(turns, np.float32).tobytes() if turns is not None else None,
            )  # fmt: skip
            for j, r in zip(jobs, rows_i, strict=True):
                j.inflight -= r > 0
            if any(bad):
                self._fail(active, [j for j, f in zip(jobs, bad, strict=True) if f], "apply")
            inflight = None
        if batch is not None and batch["rows"]:
            for j, r in zip(want, rows, strict=True):
                j.inflight += r > 0
            inflight = (want, rows, self.net.launch(batch))
            self.stats["rounds"] += 1
            self.stats["rows"] += batch["rows"]
        done = [j for j in active if j.inflight == 0 and j.search.stats()[0] >= j.target]
        for j in done:
            active.remove(j)
            self._finish(j)
        # a search that had nothing pending, gave no new leaf and made no progress (descents
        # ending in terminal states count as iterations without a leaf) cannot progress:
        # finish it as it is
        if batch is not None:
            for j, r in zip(want, rows, strict=True):
                stuck = id(j) in idle and j.search.stats()[0] == idle[id(j)]
                if r == 0 and stuck and j.inflight == 0 and j in active:
                    active.remove(j)
                    self._finish(j)
        return inflight

    def _finish(self, j: _Job) -> None:
        self.stats["searches"] += 1
        if not j.future.done():
            j.future.set_result((j.search.record(), j.search.stats()[0]))
