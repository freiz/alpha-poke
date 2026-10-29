"""Cross-mon set synergy for self-play's synthetic teams (2026-10-26): how much more often a set
feature of one mon (its ability, item or a move: "a:drought", "i:choicescarf", "m:trickroom") comes
with a feature of a teammate than their species alone explain -- a Drought with a Chlorophyll, a
Trick Room with a slow attacker's, hazards with a remover's. From real games' revealed sets:

  observed O[t, u]: ordered teammate pairs (i != j) of a team with t on i, u on j;
  expected E[t, u] = sum over the same pairs of P(t | species_i) P(u | species_j) = P^T C P (C: the
    species pairs' counts, P: each species' feature rates) -- the compositions' own correlation
    taken out (the Composer draws it);
  log_lift = log((O + k) / (E + k)), clipped.

``team_score`` sums a team's lifts over its mons' ordered pairs (both directions): the factor
the synthetic teams' Metropolis-Hastings steps weigh a resampled set by (selfplay.teams)."""

from __future__ import annotations

import collections
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from alpha_poke import paths
from alpha_poke.analysis.roles import to_id

PATH = paths.SELFPLAY / "synergy.npz"


def tokens(ability: str | None, item: str | None, moves) -> list[str]:
    out = [f"m:{to_id(m)}" for m in moves if m]
    if ability:
        out.append(f"a:{to_id(ability)}")
    if item:
        out.append(f"i:{to_id(item)}")
    return out


@dataclass
class Synergy:
    vocab: list[str]
    log_lift: np.ndarray  # [V, V]

    def __post_init__(self):
        self.index = {t: i for i, t in enumerate(self.vocab)}

    def team_score(self, sets: list[list[str]]) -> float:
        """The sum of log lifts over a team's ordered teammate pairs' features."""
        ids = [[self.index[t] for t in s if t in self.index] for s in sets]
        total = 0.0
        for i, a in enumerate(ids):
            for j, b in enumerate(ids):
                if i != j and a and b:
                    total += float(self.log_lift[np.ix_(a, b)].sum())
        return total

    def save(self, path: Path = PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, vocab=np.array(self.vocab), log_lift=self.log_lift.astype(np.float32)
        )

    @classmethod
    def load(cls, path: Path = PATH) -> Synergy:
        z = np.load(path)
        return cls([str(x) for x in z["vocab"]], z["log_lift"])


def build(teams: list[list[tuple[str, list[str]]]], min_count: int = 300, k: float = 20.0,
          clip: float = 2.0) -> tuple[Synergy, dict]:  # fmt: skip
    """``teams``: [[(species id, its revealed features), ...], ...] -> the synergy and counts."""
    tok_count: collections.Counter = collections.Counter()
    for team in teams:
        for _, f in team:
            tok_count.update(set(f))
    vocab = sorted(t for t, n in tok_count.items() if n >= min_count)
    ti = {t: i for i, t in enumerate(vocab)}
    species = sorted({sp for team in teams for sp, _ in team})
    si = {s: i for i, s in enumerate(species)}
    S, V = len(species), len(vocab)
    rate = np.zeros((S, V))
    n_sp = np.zeros(S)
    C = np.zeros((S, S))
    obs = np.zeros((V, V))
    for team in teams:
        idx = [(si[sp], [ti[t] for t in set(f) if t in ti]) for sp, f in team]
        for s, f in idx:
            n_sp[s] += 1
            rate[s, f] += 1
        for a, (sa, fa) in enumerate(idx):
            for b, (sb, fb) in enumerate(idx):
                if a != b:
                    C[sa, sb] += 1
                    if fa and fb:
                        obs[np.ix_(fa, fb)] += 1
    P = rate / np.maximum(n_sp, 1)[:, None]
    E = P.T @ C @ P
    log_lift = np.clip(np.log((obs + k) / (E + k)), -clip, clip)
    return Synergy(vocab, log_lift), {"teams": len(teams), "vocab": V, "species": S}
