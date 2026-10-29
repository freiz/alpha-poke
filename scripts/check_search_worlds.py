"""The search over real, different belief worlds (2026-10-21, the search review; check_batch_search
copies one state into every world and cannot see this): positions from replays, each with
--worlds belief worlds as the training data draws them (train.positions: the opponent's hidden
sets re-sampled, ours kept), searched by the GPU batched search (selfplay.batcher) at --iterations:

  seed      the same worlds, another seed: the search's own noise
  order     the worlds shuffled (same seed): should be no more than the seed's (the root's
            priors are the worlds' mean since 2026-10-21; before, the first world's)

Per pair of searches: the root's visit-share TV distance and whether the most visited option is
the same; and how far the first world's priors alone are from the worlds' mean (the old way's
error, L1 over our options).

  uv run python scripts/check_search_worlds.py --run data/train/v72/runs/v6arch --positions 100
"""

import argparse
import os
import random
import sys
from pathlib import Path

import numpy as np

from alpha_poke import paths  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--positions", type=int, default=100)
    ap.add_argument("--worlds", type=int, default=16)
    ap.add_argument("--iterations", type=int, default=1600)
    ap.add_argument("--games", default=str(paths.REPLAYS_HF / "gen9ou"))
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    os.environ["ALPHA_POST_WORLDS"] = str(a.worlds)  # (read when train.positions is imported)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import logging

    import alpha_search
    import pyarrow.parquet as pq

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay.batcher import Batcher
    from alpha_poke.teams import DEFAULT_POOL
    from alpha_poke.train import positions as P

    logging.disable(logging.WARNING)
    belief = BeliefModel.load(heldout_pool=str(DEFAULT_POOL))
    # every position's worlds: the main one and the re-sampled ones (wrapping _position)
    captured: dict = {}
    inner = P._position

    def grab(*args, **kw):
        pos = inner(*args, **kw)
        if pos is not None:
            st, _, more = pos
            captured[st.to_string()] = [st.to_string(), *more]
        return pos

    P._position = grab
    files = sorted(Path(a.games).glob("*.parquet"))[-1:]
    rows = pq.read_table(files[0], columns=["id", "log", "rating", "uploadtime"]).to_pylist()
    rng = random.Random(a.seed)
    rng.shuffle(rows)
    cases = []
    for r in rows:
        if len(cases) >= a.positions:
            break
        captured.clear()
        try:
            ps = P.positions_from_replay(r, belief, random.Random(len(cases)), per_game=1)
        except Exception:  # noqa: BLE001
            continue
        for p in ps:
            worlds = captured.get(p.state)
            if worlds is None or len(worlds) < 2:
                continue
            ctx = (list(p.reveal), (p.rating_own, p.rating_opp), p.turn, p.history)
            cases.append((worlds, ctx))
    print(f"{len(cases)} positions, {a.worlds} worlds each")
    # (the GPU search the games use: selfplay.batcher's BatchSearch, no root noise; 2026-10-28,
    # was agents.gpu_search)
    batcher = Batcher(a.run)

    def search(worlds, ctx, seed):
        rec, _ = batcher.submit(worlds, [ctx] * len(worlds), a.iterations, seed, (0.0, 10.0)).result()
        tot = sum(rec["visits"]) or 1
        return {c: v / tot for c, v in zip(rec["names"], rec["visits"], strict=True) if c and v}

    def tv(x, y):
        return 0.5 * sum(abs(x.get(k, 0) - y.get(k, 0)) for k in set(x) | set(y))

    def top(x):
        return max(x, key=x.get)

    res = {"seed": [], "order": []}
    prior_gap = []
    for i, (worlds, ctx) in enumerate(cases):
        base = search(worlds, ctx, 1)
        other = search(worlds, ctx, 2)
        shuffled = worlds[:]
        random.Random(i).shuffle(shuffled)
        perm = search(shuffled, ctx, 1)
        res["seed"].append((tv(base, other), top(base) == top(other)))
        res["order"].append((tv(base, perm), top(base) == top(perm)))
        # the old way's error: the first world's priors against the worlds' mean
        one = dict(alpha_search.root_priors(worlds[:1], a.run, [ctx]))
        mean = dict(alpha_search.root_priors(worlds, a.run, [ctx] * len(worlds)))
        prior_gap.append(sum(abs(one.get(k, 0) - mean.get(k, 0)) for k in set(one) | set(mean)))
    for k, v in res.items():
        d = np.array([x for x, _ in v])
        print(f"  {k:6s} visit-share TV {d.mean():.3f} (median {np.median(d):.3f}), "
              f"same top option {np.mean([s for _, s in v]):.0%}")  # fmt: skip
    g = np.array(prior_gap)
    print(f"  the first world's priors vs the worlds' mean: L1 {g.mean():.3f} (median {np.median(g):.3f}, "
          f"max {g.max():.3f})")  # fmt: skip


if __name__ == "__main__":
    main()
