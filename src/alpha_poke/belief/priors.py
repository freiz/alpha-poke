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

import contextvars
import functools
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

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


# Showdown's random-battle sets (the local checkout): a species no OU set uses -- its movepool and
# tera types, the fallback prior (2026-10-25, the belief check: 91% of its prior gaps were species
# the usage does not list at all, their prior empty: no move but the revealed ones, no item)
RANDBATS = (
    Path(__file__).resolve().parents[3]
    / "vendor/pokemon-showdown/data/random-battles/gen9/sets.json"
)
TYPES = (
    "bug",
    "dark",
    "dragon",
    "electric",
    "fairy",
    "fighting",
    "fire",
    "flying",
    "ghost",
    "grass",
    "ground",
    "ice",
    "normal",
    "poison",
    "psychic",
    "rock",
    "steel",
    "water",
    "stellar",
)


@functools.cache
def _randbats() -> dict:
    try:
        return {to_id(k): v for k, v in json.loads(RANDBATS.read_text()).items()}
    except OSError:
        return {}


ITEMS_TS = RANDBATS.parents[3] / "data/items.ts"


@functools.cache
def signature_items() -> dict[str, frozenset]:
    """Species id -> the items made for it (Showdown's itemUser: Palkia's Lustrous Orb, Latias's
    Soul Dew, ...), from the local checkout's data/items.ts."""
    import re

    try:
        text = ITEMS_TS.read_text()
    except OSError:
        return {}
    out: dict[str, set] = defaultdict(set)
    for m in re.finditer(r"\n\t(\w+): \{(.*?)\n\t\}", text, re.S):
        users = re.search(r"itemUser: \[([^\]]*)\]", m.group(2))
        if users and "isNonstandard" not in m.group(2):  # (no Mega Stone, Z-Crystal: not in Gen 9)
            for u in re.findall(r'"([^"]+)"', users.group(1)):
                out[to_id(u)].add(m.group(1))
    return {k: frozenset(v) for k, v in out.items()}


@functools.cache
def standard_items() -> frozenset:
    """The items of Gen 9 (data/items.ts without isNonstandard: no Z-Crystal, no Mega Stone)."""
    import re

    try:
        text = ITEMS_TS.read_text()
    except OSError:
        return frozenset()
    return frozenset(m.group(1) for m in re.finditer(r"\n\t(\w+): \{(.*?)\n\t\}", text, re.S)
                     if "isNonstandard" not in m.group(2))  # fmt: skip


# Showdown's item handlers that change a hit's damage or the speed order: the items F1's damage
# evidence and the speed observations can tell apart (data/items.ts)
EVIDENCE_HANDLERS = ("onBasePower", "onModifyAtk", "onModifySpA", "onModifyDef", "onModifySpD",
                     "onModifyDamage", "onSourceModifyDamage", "onSourceModifyAtk",
                     "onSourceModifySpA", "onSourceBasePower", "onModifySpe", "isGem")  # fmt: skip


@functools.cache
def evidence_items() -> frozenset:
    """Gen 9's items whose Showdown entry changes damage or speed (EVIDENCE_HANDLERS): Choice
    items, Life Orb, Expert Belt, plates and type boosters, gems, Assault Vest, Eviolite, resist
    berries, ... -- the rest hold no hit's damage or the order apart from no item."""
    import re

    try:
        text = ITEMS_TS.read_text()
    except OSError:
        return frozenset()
    return frozenset(m.group(1) for m in re.finditer(r"\n\t(\w+): \{(.*?)\n\t\}", text, re.S)
                     if "isNonstandard" not in m.group(2)
                     and any(h in m.group(2) for h in EVIDENCE_HANDLERS))  # fmt: skip


def items_for(sid: str, items: dict[str, float]) -> dict[str, float]:
    """OU's items across species (``global_item``) as one species can use them, normalized: not
    another species' own (its itemUser: an Ogerpon mask, a Latias's Soul Dew), no Booster Energy
    without Protosynthesis / Quark Drive (2026-10-25 review: 7% of a fallback's items a Booster
    Energy, 4% a Wellspring Mask)."""
    from poke_env.data import GenData

    sig = signature_items()
    owned = frozenset().union(*sig.values()) if sig else frozenset()
    mine = frozenset().union(*(v for k, v in sig.items() if sid.startswith(k)))
    abilities = {
        to_id(a)
        for a in ((GenData.from_gen(9).pokedex.get(sid) or {}).get("abilities") or {}).values()
    }
    out = {i: w for i, w in items.items()
           if (i not in owned or i in mine)
           and (i != "boosterenergy" or abilities & {"protosynthesis", "quarkdrive"})}  # fmt: skip
    t = sum(out.values())
    return {i: w / t for i, w in out.items()} if t > 0 else out


@functools.cache
def legal_moves(species: str) -> frozenset:
    """A species' Gen 9 learnset (move ids): its own, its base forme's, its pre-evolutions'."""
    from poke_env.data import GenData

    g = GenData.from_gen(9)
    out, seen, todo = set(), set(), [to_id(species)]
    while todo:
        sid = todo.pop()
        if sid in seen or sid not in g.pokedex:
            continue
        seen.add(sid)
        entry = g.pokedex[sid]
        for k in ("changesFrom", "baseSpecies", "prevo"):
            if entry.get(k):
                todo.append(to_id(entry[k]))
        ls = (g.learnset.get(sid) or {}).get("learnset") or {}
        out |= {m for m, src in ls.items() if any(str(s).startswith("9") for s in src)}
    if "sketch" in out:  # (Smeargle: any move)
        out |= {
            m
            for m, d in g.moves.items()
            if not d.get("isNonstandard") and not d.get("isZ") and not d.get("isMax")
        }
    return frozenset(out)


def _global_items(stats: UsageStats) -> dict[str, float]:
    glob: dict[str, float] = defaultdict(float)
    for s in stats.species.values():
        t = sum(s.items.values()) or 1.0
        for k, v in s.items.items():
            glob[to_id(k)] += s.usage * v / t
    return _norm(dict(glob))


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
        self._global_item = _global_items(stats)

    @property
    def global_item(self) -> dict[str, float]:
        """OU's items across its species, by usage (a species' unknown: the fallback, the floor);
        a model pickled before 2026-10-25 has none: from the usage file it was built from."""
        g = self.__dict__.get("_global_item")
        if g is None:
            from alpha_poke.data.smogon_stats import DEFAULT_DIR

            months = sorted(x.name for x in Path(DEFAULT_DIR).iterdir() if x.is_dir())
            g = self._global_item = _global_items(
                UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1825.json")
            )
        return g

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
        if same:
            return self._d[max(same, key=len)]
        return self.fallback(sid) if FALLBACK.get() else Dist({}, {}, {})

    def fallback(self, sid: str) -> Dist:
        """A species OU's usage does not list: Showdown's random-battle movepool and tera types
        (each set's share), else its learnset and every type, alike; OU's items across species."""
        tera, move = _fallback_tera_moves(sid)
        return Dist(items_for(sid, self.global_item), dict(tera), dict(move))


# (the fallback on: off for the belief before it -- engine_state's mix 0, the search A/B's old side;
# 2026-10-25 review, the switch left it on. A context variable: per thread, reset after the call)
FALLBACK: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "alpha_poke_prior_fallback", default=True
)


@functools.cache
def _fallback_tera_moves(sid: str) -> tuple[dict, dict]:
    """``SmogonPrior.fallback``'s tera types and moves (the species' alone: cached here, not on the
    prior -- a method's cache keeps its instance)."""
    sets = (_randbats().get(sid) or {}).get("sets") or []
    move: dict[str, float] = defaultdict(float)
    tera: dict[str, float] = defaultdict(float)
    for s in sets:
        for m in s.get("movepool", []):
            move[to_id(m)] += 1.0 / len(sets) / max(len(s["movepool"]), 1)
        for x in s.get("teraTypes", []):
            tera[to_id(x)] += 1.0 / len(sets) / max(len(s["teraTypes"]), 1)
    if not move:
        moves = legal_moves(sid)
        move = {m: 1.0 / len(moves) for m in moves}
    if not tera:
        tera = {x: 1.0 / len(TYPES) for x in TYPES}
    return dict(tera), dict(move)


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
