"""Diagnostic team pools beyond the ladder distribution (design D16): fixed pairs, for
measuring how the networks do on teams self-play rarely sees. Never used for promotion.

  offmeta  real games (completed like self-play's, no catalog teams) where BOTH teams are
           off-meta: at most ``max_count`` games in the window with the same six species, and
           at least ``min_off`` species outside the window's ``top_k`` most used ones
  random   teams of six species drawn by Smogon OU usage ** ``alpha`` (flattened; no teammate
           structure), sets completed like a replay side with nothing revealed (belief sampler)

Pool layout as eval.arena.pair_schedule reads it: ``pair<k>_a.txt`` / ``pair<k>_b.txt``, plus
meta.json."""

import collections
import json
import random
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from alpha_poke.analysis.games_lite import DEST as GAMES
from alpha_poke.analysis.roles import to_id
from alpha_poke.selfplay.teams import TeamPair, TeamSampler, poke_env_clash
from alpha_poke.teams.validate import check


def offmeta_games(since: int, top_k: int = 40, min_off: int = 4, max_count: int = 2) -> set:
    """Ids of the window's games whose two teams are both off-meta."""
    g = pd.read_parquet(GAMES, columns=["id", "time", "team1", "team2", "winner"])
    g = g[(g.winner > 0) & (g.time >= since)]
    comps = collections.Counter(list(g.team1) + list(g.team2))
    species: collections.Counter = collections.Counter()
    for t, n in comps.items():
        for s in t.split("|"):
            species[s] += n
    top = {s for s, _ in species.most_common(top_k)}

    def off(t: str) -> bool:
        return comps[t] <= max_count and sum(s not in top for s in t.split("|")) >= min_off

    ok = g.team1.map(off) & g.team2.map(off)
    return set(g.id[ok])


def offmeta_pairs(ts: TeamSampler, n: int, ids: set) -> list[TeamPair]:
    """``n`` pairs from the off-meta games (the sampler's recency weights, no catalog)."""
    keep = ts.games.id.isin(ids).to_numpy()
    ts.games = ts.games[keep].reset_index(drop=True)
    w = ts.weights[keep]
    ts.weights = w / w.sum()
    ts.catalog_frac = 0.0
    return ts.sample(n)


def _base(species: str) -> str:
    return to_id(species.split("-")[0])


def random_team(ts: TeamSampler, rng: random.Random, names: list, weights: list) -> str:
    """Six species by flattened usage (species clause, no poke-env clash), sets completed."""
    while True:
        team: list[str] = []
        while len(team) < 6:
            s = rng.choices(names, weights=weights)[0]
            if all(_base(s) != _base(t) for t in team):
                team.append(s)
        recs = [SimpleNamespace(species=s, forms=[], moves=[], item="", ability="",
                                tera_type="") for s in team]  # fmt: skip
        text = ts._try_complete(recs)
        if text and not poke_env_clash(text):
            return text


def random_pairs(ts: TeamSampler, n: int, alpha: float = 0.5, min_usage: float = 0.001,
                 seed: int = 0) -> list[str]:  # fmt: skip
    """``n`` validated pairs of random teams (texts a, b alternating)."""
    rng = random.Random(seed)
    usage = {name: e.usage for name, e in ts.stats.species.items() if e.usage >= min_usage}
    names = sorted(usage)
    weights = [usage[s] ** alpha for s in names]
    out: list[str] = []
    while len(out) < 2 * n:
        texts = [random_team(ts, rng, names, weights) for _ in range(2 * n - len(out))]
        for _text, res in zip(texts, check(texts), strict=True):
            if res["n"] == 6 and not res["problems"]:
                out.append(res["text"])
            else:
                ts._learn_bans(res["problems"])
    return out


def write_pool(d: Path, texts: list[str], meta: dict) -> str:
    d.mkdir(parents=True, exist_ok=True)
    for i in range(len(texts) // 2):
        (d / f"pair{i:03d}_a.txt").write_text(texts[2 * i])
        (d / f"pair{i:03d}_b.txt").write_text(texts[2 * i + 1])
    (d / "meta.json").write_text(json.dumps(meta | {"pairs": len(texts) // 2}, indent=1))
    return str(d)


def species_stats(texts: list[str], top: set) -> dict:
    """Mean species per team outside ``top``, distinct species."""
    from alpha_poke.selfplay.teams import species_names

    teams = [species_names(t) for t in texts]
    return {"off_top_mean": round(float(np.mean([sum(s not in top for s in t) for t in teams])),
                                  2),
            "distinct_species": len({s for t in teams for s in t})}  # fmt: skip
