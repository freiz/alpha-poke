"""Preview-time priors over each opponent mon's item, tera type and moves.

Every prior answers the same question: given the opponent's six species at team preview,
what is the distribution of (item, tera type, which moves will show up) for each of them?
All names are Showdown IDs. Moves are modelled as a categorical "share" distribution (which
move a revealed slot is), which is comparable between Smogon stats and replay reveals.

Priors (each falls back to the previous one, Dirichlet-smoothed with strength ``alpha``):
  SmogonPrior         monthly usage stats (marginal per species)
  SpeciesReplayPrior  revealed info in training replays, per species
  CorePrior           per species *within teams containing the same maximal core*
  TeamPrior           per species *within the exact same 6-mon team* (copied teams)
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

import pandas as pd

from alpha_poke.analysis.cores import Core, team_cores
from alpha_poke.analysis.roles import to_id
from alpha_poke.data.smogon_stats import UsageStats

ATTRS = ("item", "tera", "move")


@dataclass
class Dist:
    item: dict[str, float]
    tera: dict[str, float]
    move: dict[str, float]


def _norm(c: dict[str, float]) -> dict[str, float]:
    t = sum(c.values())
    return {k: v / t for k, v in c.items()} if t else {}


def _blend(counts: Counter, prior: dict[str, float], alpha: float) -> dict[str, float]:
    """Posterior mean of a Dirichlet(alpha * prior) after observing ``counts``."""
    n = sum(counts.values())
    keys = set(counts) | set(prior)
    return {k: (counts.get(k, 0) + alpha * prior.get(k, 0.0)) / (n + alpha) for k in keys}


class SmogonPrior:
    name = "smogon"

    def __init__(self, stats: UsageStats):
        self._d = {}
        for name, s in stats.species.items():
            self._d[to_id(name)] = Dist(
                item={to_id(k): v for k, v in s.items.items()},
                tera={to_id(k): v for k, v in s.tera_types.items()},
                move={to_id(k): v for k, v in s.moves.items()},
            )

    def predict(self, species: str, team: tuple[str, ...]) -> Dist:
        sid = to_id(species.replace("-*", ""))
        if sid in self._d:
            return self._d[sid]
        match = [v for k, v in self._d.items() if k.startswith(sid)]
        return match[0] if match else Dist({}, {}, {})


class _Counts:
    def __init__(self):
        self.item, self.tera, self.move = Counter(), Counter(), Counter()

    def add(self, row) -> None:
        if isinstance(row.item, str):
            self.item[to_id(row.item)] += 1
        if isinstance(row.tera_type, str):
            self.tera[to_id(row.tera_type)] += 1
        for mv in (row.moves or "").split("|"):
            if mv:
                self.move[to_id(mv)] += 1

    def dist(self, base: Dist, alpha: float) -> Dist:
        return Dist(
            _blend(self.item, base.item, alpha),
            _blend(self.tera, base.tera, alpha),
            _norm(_blend(self.move, base.move, alpha)),
        )


class SpeciesReplayPrior:
    name = "species_replay"

    def __init__(self, train: pd.DataFrame, base, alpha: float = 5.0):
        self.base, self.alpha = base, alpha
        self.c: dict[str, _Counts] = defaultdict(_Counts)
        for r in train.itertuples():
            self.c[r.species].add(r)

    def predict(self, species, team) -> Dist:
        b = self.base.predict(species, team)
        return self.c[species].dist(b, self.alpha) if species in self.c else b


class CorePrior:
    """Species distribution conditioned on the largest maximal core (containing it) in the team."""

    name = "core"

    def __init__(self, train: pd.DataFrame, cores: list[Core], base, alpha: float = 5.0):
        self.base, self.alpha, self.cores = base, alpha, cores
        self.c: dict[tuple, _Counts] = defaultdict(_Counts)
        for r in train.itertuples():
            core = self._core_for(r.species, tuple(r.team.split("|")))
            if core:
                self.c[(core, r.species)].add(r)

    def _core_for(self, species, team) -> tuple | None:
        hits = [c for c in team_cores(team, self.cores) if species in c.members]
        return max(hits, key=lambda c: (c.size, c.support)).members if hits else None

    def predict(self, species, team) -> Dist:
        b = self.base.predict(species, team)
        core = self._core_for(species, tuple(sorted(team)))
        key = (core, species)
        return self.c[key].dist(b, self.alpha) if core and key in self.c else b


class TeamPrior:
    """Species distribution within the exact same 6-mon team, if seen >= min_games times."""

    name = "team"

    def __init__(self, train: pd.DataFrame, base, alpha: float = 5.0, min_games: int = 5):
        self.base, self.alpha = base, alpha
        games = train.drop_duplicates(["id", "side"]).team.value_counts()
        self.known = set(games[games >= min_games].index)
        self.c: dict[tuple, _Counts] = defaultdict(_Counts)
        for r in train.itertuples():
            if r.team in self.known:
                self.c[(r.team, r.species)].add(r)

    def predict(self, species, team) -> Dist:
        b = self.base.predict(species, team)
        key = ("|".join(sorted(team)), species)
        return self.c[key].dist(b, self.alpha) if key in self.c else b
