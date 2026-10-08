"""Team strength and species matchups from the outcomes of ~2M games (design D5-L).

  logit P(team A beats team B) = beta * (r_A - r_B) / 400            (the players' skill)
                                 + sum_{s in A} a_s - sum_{t in B} a_t   (species strength)
                                 + sum_{s in A, t in B} M[s, t]          (species matchups)
with M antisymmetric (M = U - U^T) and L2 on a and U. Fit by full-batch L-BFGS on the CPU.
Both ratings must be known; species seen in fewer than ``min_games`` games share one "other"
index. Held-out: the latest ``val_frac`` of the games by time."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

from alpha_poke.analysis.games_lite import DEST as GAMES


@dataclass
class MatchupModel:
    species: list[str]  # index -> name; the last one is "other"
    beta: float
    a: np.ndarray  # [V]
    M: np.ndarray  # [V, V], antisymmetric

    def index(self, team: list[str]) -> list[int]:
        idx = {s: i for i, s in enumerate(self.species)}
        return [idx.get(s, len(self.species) - 1) for s in team]

    def logit(self, team_a: list[str], team_b: list[str], rating_diff: float = 0.0) -> float:
        ia, ib = self.index(team_a), self.index(team_b)
        return float(self.beta * rating_diff / 400 + self.a[ia].sum() - self.a[ib].sum()
                     + self.M[np.ix_(ia, ib)].sum())  # fmt: skip

    def win(self, team_a: list[str], team_b: list[str], rating_diff: float = 0.0) -> float:
        return 1 / (1 + np.exp(-self.logit(team_a, team_b, rating_diff)))


def load_games(since: int = 0, rating: tuple[int, int] = (1, 10_000)) -> pd.DataFrame:
    g = pd.read_parquet(GAMES)
    lo, hi = rating
    keep = (g.time >= since) & (g.winner > 0) & g.r1.between(lo, hi) & g.r2.between(lo, hi)
    return g[keep].sort_values("time").reset_index(drop=True)


def fit(g: pd.DataFrame, l2_a: float = 1e-4, l2_m: float = 1e-3, min_games: int = 300,
        val_frac: float = 0.1, pairs: bool = True, iters: int = 200,
        log=print) -> tuple[MatchupModel, dict]:  # fmt: skip
    counts = pd.Series([s for t in pd.concat([g.team1, g.team2]) for s in t.split("|")])
    vc = counts.value_counts()
    species = sorted(vc[vc >= min_games].index) + ["other"]
    idx = {s: i for i, s in enumerate(species)}
    other = len(species) - 1

    def teams(col: pd.Series) -> torch.Tensor:
        return torch.tensor([[idx.get(s, other) for s in t.split("|")] for t in col])

    t1, t2 = teams(g.team1), teams(g.team2)
    rd = torch.tensor(((g.r1 - g.r2) / 400).to_numpy(), dtype=torch.float32)
    y = torch.tensor((g.winner == 1).to_numpy(), dtype=torch.float32)
    n_val = int(len(g) * val_frac)
    tr, va = slice(0, len(g) - n_val), slice(len(g) - n_val, len(g))
    V = len(species)
    beta = torch.zeros(1, requires_grad=True)
    a = torch.zeros(V, requires_grad=True)
    U = torch.zeros(V, V, requires_grad=True)

    def logits(sl):
        z = beta * rd[sl] + a[t1[sl]].sum(1) - a[t2[sl]].sum(1)
        if pairs:
            M = U - U.T
            z = z + M[t1[sl][:, :, None], t2[sl][:, None, :]].sum((1, 2))
        return z

    params = [beta, a] + ([U] if pairs else [])
    opt = torch.optim.LBFGS(params, max_iter=iters, line_search_fn="strong_wolfe")
    bce = torch.nn.functional.binary_cross_entropy_with_logits

    def closure():
        opt.zero_grad()
        loss = bce(logits(tr), y[tr]) + l2_a * (a**2).sum() + (l2_m * (U**2).sum() if pairs else 0)
        loss.backward()
        return loss

    opt.step(closure)
    with torch.no_grad():
        val = {
            "val_logloss": float(bce(logits(va), y[va])),
            "val_logloss_rating_only": float(bce(beta * rd[va], y[va])),
            "val_logloss_const": float(np.log(2)),
            "val_acc": float(((logits(va) > 0).float() == y[va]).float().mean()),
            "n_train": len(g) - n_val, "n_val": n_val, "species": V,
        }  # fmt: skip
    M = (U - U.T).detach().numpy() if pairs else np.zeros((V, V), np.float32)
    model = MatchupModel(species, float(beta.detach()), a.detach().numpy(), M)
    log(val)
    return model, val


def load_or_fit(path, since: int = 1746057600, log=print) -> MatchupModel:
    """The cached model at ``path``, else fit on the games since ``since`` (default 2025-05-01,
    the current metagame; the lite scan is built first if missing) and cache it."""
    import pickle
    from pathlib import Path

    from alpha_poke.analysis import games_lite

    path = Path(path)
    if path.exists():
        return pickle.loads(path.read_bytes())
    if not GAMES.exists():
        log("scanning the replay logs (games_lite) ...")
        games_lite.build()
    torch.set_num_threads(4)
    model, val = fit(load_games(since=since), l2_a=1e-4, l2_m=1e-3, iters=150, log=log)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(model))
    return model
