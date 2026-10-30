"""The fair evaluation pool (2026-10-30): fixed team pairs for comparing two networks' strength
on the ladder, under data/derived/teams/pools/<name> (git-ignored), for scripts/eval_pairs.py.

Each pair is the two teams of one real game: games after the training data's cutoff, both
players rated at least --min-rating, none of them a source of self-play's teams or of an earlier
test's pool. A side's set: what the game revealed, the rest drawn from Smogon's usage weighted by
1 - the part's reveal rate (selfplay.teams.marginal_set / reveal_rates, estimated on --rate-games
games of the same window) -- not the search's belief, so the opponents are not what the networks
expect them to be.

  uv run python scripts/fair_pool.py --pairs 1000
"""

import argparse
import glob
import json
import logging
import random
from pathlib import Path

from alpha_poke import paths  # noqa: E402
from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.analysis.games_lite import logs
from alpha_poke.replay.parser import parse_replay
from alpha_poke.selfplay import pools
from alpha_poke.selfplay.teams import TeamSampler, reveal_rates

# the released network's (v6arch-pp-v75) training cutoff: --val-cutoff, its later games held out
TRAINING_CUTOFF = 1776921722


def used_games() -> set[str]:
    """Game ids self-play drew teams from, and earlier tests' pools."""
    out = set()
    for f in glob.glob(str(paths.DATA / "selfplay" / "gen*" / "teams.jsonl")):
        with open(f, encoding="utf-8") as fh:
            out |= {json.loads(line).get("game") for line in fh}
    for f in glob.glob(str(paths.DATA / "selfplay" / "gen*" / "eval_pool_*" / "meta.json")):
        out |= set(json.loads(Path(f).read_text(encoding="utf-8")).get("games", []))
    out.discard(None)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=1000)
    ap.add_argument("--name", default="")
    ap.add_argument("--since", type=int, default=TRAINING_CUTOFF)
    ap.add_argument("--min-rating", type=int, default=1500)
    ap.add_argument("--rate-games", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=9300)
    ap.add_argument("--out", default=str(paths.POOLS))
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    exclude = used_games()
    ts = TeamSampler(BeliefModel.load(), since=a.since, catalog_frac=0.0, seed=a.seed, fill="marginal",
                     min_rating=a.min_rating, exclude=exclude)  # fmt: skip
    print(f"{len(ts.games)} eligible games ({len(exclude)} excluded ids)", flush=True)
    rows = ts.games.sample(min(a.rate_games, len(ts.games)), random_state=a.seed).to_dict("records")
    records = []
    for row in logs(rows).values():
        rep = parse_replay(row)
        if not rep.warnings:
            records += [m for s in ("p1", "p2") for m in rep.teams[s] if not m.phantom]
    ts.rates = reveal_rates(records, ts.stats)
    print(f"reveal rates from {len(records)} mons: {ts.rates['default']}", flush=True)
    pairs = ts.sample(a.pairs)
    texts = [t for p in pairs for t in (p.p1.text, p.p2.text)]
    rng = random.Random(a.seed)
    show = lambda kind, keys: {k: round(ts.rates[kind].get(k, -1), 3) for k in keys}  # noqa: E731
    meta = {
        "kind": "fair", "seed": a.seed, "since": a.since, "min_rating": a.min_rating,
        "fill": "revealed parts kept, the rest Smogon usage x (1 - reveal rate); never-brought mons: usage",
        "rate_mons": len(records), "rates_default": ts.rates["default"],
        "rates_sample": show("item", ["leftovers", "heavydutyboots", "lifeorb", "choicescarf", "rockyhelmet",
                                      "boosterenergy", "assaultvest"]),
        "fill_counts": dict(ts.fill_counts), "excluded_ids": len(exclude),
        "games": [p.game for p in pairs], "ratings": [list(p.ratings) for p in pairs],
    }  # fmt: skip
    name = a.name or f"fair{a.pairs}"
    print(pools.write_pool(Path(a.out) / name, texts, meta),
          {k: v for k, v in meta.items() if k not in ("games", "ratings")})  # fmt: skip
    print(rng.choice(texts))
