"""Offline evaluation of preview-time priors against what was later revealed in replays."""

import math
from collections import defaultdict

import pandas as pd

from alpha_poke.analysis.roles import to_id

EPS = 1e-4


def evaluate(prior, test: pd.DataFrame) -> dict[str, float]:
    """NLL / accuracy of revealed item, tera type and moves; only ``brought`` mons with reveals."""
    acc = defaultdict(float)
    n = defaultdict(int)
    cache: dict[tuple, object] = {}
    for r in test.itertuples():
        team = tuple(r.team.split("|"))
        key = (r.species, r.team)
        if key not in cache:
            cache[key] = prior.predict(r.species, team)
        d = cache[key]
        for attr, val in (("item", r.item), ("tera", r.tera_type)):
            if isinstance(val, str):
                dist = getattr(d, attr)
                v = to_id(val)
                acc[f"{attr}_nll"] -= math.log(max(dist.get(v, 0.0), EPS))
                acc[f"{attr}_top1"] += float(bool(dist) and max(dist, key=dist.get) == v)
                n[attr] += 1
        moves = [to_id(m) for m in (r.moves or "").split("|") if m]
        if moves:
            top4 = set(sorted(d.move, key=d.move.get, reverse=True)[:4])
            for mv in moves:
                acc["move_nll"] -= math.log(max(d.move.get(mv, 0.0), EPS))
                acc["move_recall@4"] += float(mv in top4)
                n["move"] += 1
    out = {}
    for k, v in acc.items():
        out[k] = v / max(n[k.split("_")[0]], 1)
    out.update({f"n_{k}": v for k, v in n.items()})
    return out
