"""Team archetypes by clustering species composition (spherical k-means, numpy only).

Each team (one side of one game) is a multi-hot vector over species, divided by sqrt of the
species' overall frequency so that ubiquitous mons (Great Tusk, Kingambit) do not dominate.
A cluster is described by its *signature*: species that are both frequent in the cluster and
over-represented relative to the whole metagame.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Archetype:
    cluster: int
    size: int
    win_rate: float
    signature: list[str]  # frequent AND over-represented
    common: list[str]  # most frequent in the cluster
    freq: dict[str, float]  # species -> share of teams in the cluster


def team_table(mons: pd.DataFrame) -> pd.DataFrame:
    return (
        mons.groupby(["id", "side"])
        .agg(species=("species", list), won=("won", "first"))
        .reset_index()
    )


def cluster_teams(
    teams: pd.DataFrame, k: int = 24, min_count: int = 30, restarts: int = 5, seed: int = 0
) -> tuple[np.ndarray, list[Archetype]]:
    counts = pd.Series([s for sp in teams.species for s in sp]).value_counts()
    vocab = counts[counts >= min_count].index.tolist()
    idx = {s: i for i, s in enumerate(vocab)}
    x = np.zeros((len(teams), len(vocab)), np.float32)
    for r, sp in enumerate(teams.species):
        for s in sp:
            if s in idx:
                x[r, idx[s]] = 1
    p = x.mean(0)
    w = x / np.sqrt(p + 1e-3)
    w /= np.linalg.norm(w, axis=1, keepdims=True) + 1e-9
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        c = w[rng.choice(len(w), k, replace=False)]
        for _ in range(60):
            lab = (w @ c.T).argmax(1)
            c = np.stack([w[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
            c /= np.linalg.norm(c, axis=1, keepdims=True) + 1e-9
        score = float((w * c[lab]).sum())
        if best is None or score > best[0]:
            best = (score, lab)
    lab = best[1]
    won = teams.won.astype(float).to_numpy()
    out = []
    for j in np.argsort(-np.bincount(lab, minlength=k)):
        sub = x[lab == j]
        if not len(sub):
            continue
        f = sub.mean(0)
        lift = f / (p + 1e-9)
        out.append(
            Archetype(
                cluster=int(j),
                size=len(sub),
                win_rate=float(np.nanmean(won[lab == j])),
                signature=[vocab[i] for i in np.argsort(-(f * np.log(lift + 1e-9)))[:4]],
                common=[vocab[i] for i in np.argsort(-f)[:8]],
                freq={vocab[i]: float(f[i]) for i in np.argsort(-f)[:15]},
            )
        )
    return lab, out
