"""The matchup model (analysis.matchups) on made-up games."""

import numpy as np
import pandas as pd

from alpha_poke.analysis import matchups

SPECIES = [f"S{i}" for i in range(12)]


def games(n: int, seed: int = 0) -> pd.DataFrame:
    """Random teams of equally strong species; a side with S0 and S1 together wins 75%."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n):
        t1, t2 = (sorted(rng.choice(SPECIES, 6, replace=False)) for _ in range(2))
        z = 1.1 * ({"S0", "S1"} <= set(t1)) - 1.1 * ({"S0", "S1"} <= set(t2))
        won = rng.random() < 1 / (1 + np.exp(-z))
        rows.append({"time": k, "team1": "|".join(t1), "team2": "|".join(t2), "r1": 1500, "r2": 1500,
                     "winner": 1 if won else 2})  # fmt: skip
    return pd.DataFrame(rows)


def test_teammate_synergy_is_found():
    """synergy=True learns what a pair brings together: S0 + S1 stands out of every other pair;
    without it the model has no S (its old form, as the team builder uses it)."""
    g = games(20_000)
    model, val = matchups.fit(
        g, min_games=100, synergy=True, l2_s=1e-4, iters=100, log=lambda *x: None
    )
    i, j = model.species.index("S0"), model.species.index("S1")
    others = [
        model.S[a, b]
        for a in range(len(SPECIES))
        for b in range(a + 1, len(SPECIES))
        if {a, b} != {i, j}
    ]
    assert model.S[i, j] > 0.5 and model.S[i, j] > 3 * max(others), (model.S[i, j], max(others))
    assert np.allclose(model.S, model.S.T) and not model.S.diagonal().any()
    assert model.synergy(["S0", "S1", "S2", "S3", "S4", "S5"]) > model.synergy(
        ["S2", "S3", "S4", "S5", "S6", "S7"]
    )
    plain, _ = matchups.fit(g, min_games=100, iters=50, log=lambda *x: None)
    assert plain.S is None and plain.synergy(["S0", "S1"]) == 0.0
