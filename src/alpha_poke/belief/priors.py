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

import numpy as np
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
        if match:
            return match[0]
        # (a forme the stats list under its base species -- Maushold-Four as Maushold: only one the
        # same in battle, its types and base stats; not Tauros-Paldea-Combat as Tauros. 2026-10-25,
        # the belief check: its whole prior was empty)
        same = [k for k in self._d if sid.startswith(k) and _same_in_battle(sid, k)]
        return self._d[max(same, key=len)] if same else Dist({}, {}, {})


def _same_in_battle(a: str, b: str) -> bool:
    """Two species ids with the same types and base stats (a cosmetic forme and its base)."""
    from poke_env.data import GenData

    dex = GenData.from_gen(9).pokedex
    x, y = dex.get(a), dex.get(b)
    return bool(x and y) and x["types"] == y["types"] and x["baseStats"] == y["baseStats"]


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


class SetMixturePrior:
    """Mixture over mined set archetypes (``analysis.sets``), with the archetype weights
    conditioned on the most specific context seen in training: exact team, else largest core,
    else the species-level weights. Prediction = sum_k P(k | context) * phi_k."""

    name = "set_mixture"

    def __init__(self, train, sets, cores, base, min_games: int = 5, alpha: float = 3.0):
        from alpha_poke.analysis.cores import team_cores  # noqa: F401 (used via CorePrior)

        self.sets, self.base, self.alpha = sets, base, alpha
        self.core_helper = CorePrior(train.iloc[:0], cores, base)
        games = train.drop_duplicates(["id", "side"]).team.value_counts()
        self.known = set(games[games >= min_games].index)
        self.w: dict[tuple, np.ndarray] = {}
        for r in train.itertuples():
            ss = sets.get(r.species)
            if ss is None:
                continue
            post = ss.posterior(
                r.item, r.ability, r.tera_type, [m for m in (r.moves or "").split("|") if m]
            )
            team = tuple(r.team.split("|"))
            for key in self._contexts(r.species, team):
                self.w[key] = self.w.get(key, 0) + post
        self._phi = {
            sp: {
                a: [
                    {to_id(v): float(p) for v, p in zip(ss.vocab[a], ss.params[a][k], strict=False)}
                    for k in range(ss.k)
                ]
                for a in ("item", "tera", "move")
            }
            for sp, ss in sets.items()
        }

    def _contexts(self, species, team):
        tk = "|".join(sorted(team))
        out = []
        if tk in self.known:
            out.append(("team", tk, species))
        core = self.core_helper._core_for(species, tuple(sorted(team)))
        if core:
            out.append(("core", core, species))
        return out

    def predict(self, species, team) -> Dist:
        ss = self.sets.get(species)
        if ss is None:
            return self.base.predict(species, team)
        weights = ss.params["pi"]
        for key in self._contexts(species, team):  # most specific first
            if key in self.w:
                c = self.w[key]
                weights = (c + self.alpha * ss.params["pi"]) / (c.sum() + self.alpha)
                break
        b = self.base.predict(species, team)
        out = {}
        for a in ("item", "tera", "move"):
            mix: dict[str, float] = {}
            for k, wk in enumerate(weights):
                for v, p in self._phi[species][a][k].items():
                    mix[v] = mix.get(v, 0.0) + wk * p
            # small back-off to the base prior for values outside the mined vocabulary
            keys = set(mix) | set(getattr(b, a))
            out[a] = {v: 0.95 * mix.get(v, 0.0) + 0.05 * getattr(b, a).get(v, 0.0) for v in keys}
        return Dist(out["item"], out["tera"], out["move"])
