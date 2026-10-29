"""Build the diagnostic team pools (design D16; selfplay.pools): off-meta real games and random
teams, fixed pairs under data/derived/teams/pools/ (git-ignored).

  uv run python scripts/team_pools.py --pairs 200
"""

import argparse
import collections
import logging
from pathlib import Path

from alpha_poke import paths  # noqa: E402
from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.selfplay import pools
from alpha_poke.selfplay.teams import TeamSampler

SINCE = 1746057600  # 2025-05-01, as scripts/selfplay.py SINCE_DEFAULT

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=200)
    ap.add_argument("--out", default=str(paths.POOLS))
    ap.add_argument("--top-k", type=int, default=40)
    ap.add_argument("--min-off", type=int, default=4)
    ap.add_argument("--max-count", type=int, default=2)
    ap.add_argument("--alpha", type=float, default=0.5, help="random teams: usage ** alpha")
    ap.add_argument("--min-usage", type=float, default=0.001)
    ap.add_argument("--seed", type=int, default=9100)
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    belief = BeliefModel.load()
    ids = pools.offmeta_games(SINCE, a.top_k, a.min_off, a.max_count)
    ts = TeamSampler(belief, since=SINCE, seed=a.seed + 1)
    top = {s.name for s in ts.stats.ranked()[: a.top_k]}
    pairs = pools.offmeta_pairs(ts, a.pairs, ids)
    texts = [t for p in pairs for t in (p.p1.text, p.p2.text)]
    meta = {
        "kind": "offmeta",
        "seed": a.seed + 1,
        "eligible_games": len(ids),
        "top_k": a.top_k,
        "min_off": a.min_off,
        "max_count": a.max_count,
        "games": [p.game for p in pairs],
    }
    meta |= pools.species_stats(texts, top)
    print(pools.write_pool(Path(a.out) / f"offmeta{a.pairs}", texts, meta), meta | {"games": 0})
    ts = TeamSampler(belief, since=SINCE, seed=a.seed + 2)
    texts = pools.random_pairs(ts, a.pairs, a.alpha, a.min_usage, seed=a.seed + 2)
    meta = {"kind": "random", "seed": a.seed + 2, "alpha": a.alpha, "min_usage": a.min_usage}
    meta |= pools.species_stats(texts, top)
    print(pools.write_pool(Path(a.out) / f"random{a.pairs}", texts, meta), meta)
    # the ladder pool for reference
    from alpha_poke.selfplay.teams import species_names

    lad = [p.read_text() for p in sorted(Path(a.out, "wide200").glob("pair*.txt"))]
    print(
        "wide200",
        pools.species_stats(lad, top),
        collections.Counter(s for t in lad for s in species_names(t)).most_common(5),
    )
