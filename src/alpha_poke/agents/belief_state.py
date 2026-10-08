"""Belief layer at runtime: what does each opponent mon probably carry?

Preview: the team-conditional prior (exact copied team -> core -> species -> Smogon) gives item /
tera / move distributions per opponent mon. In battle: revealed moves / item / ability / tera
override the prior, and the species' mined set archetypes (``analysis.sets``) re-weight the
remaining moves given what has been revealed (the in-battle update that measured +3.4 pp).
Stats use the species' most common Smogon spread.
"""

import json
import pickle
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
from poke_env.battle import Pokemon
from poke_env.battle.move import Move
from poke_env.data import GenData

from alpha_poke.agents.damage import MonView, Spread, calc_stats
from alpha_poke.analysis.archetypes import team_table
from alpha_poke.analysis.cores import mine_cores
from alpha_poke.analysis.roles import to_id
from alpha_poke.analysis.sets import SpeciesSets, mine_sets
from alpha_poke.analysis.tables import OUT
from alpha_poke.belief.priors import CorePrior, SmogonPrior, SpeciesReplayPrior, TeamPrior
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats

CACHE = Path(__file__).resolve().parents[3] / "data" / "belief_model.pkl"


@dataclass
class BeliefModel:
    prior: TeamPrior
    sets: dict[str, SpeciesSets]
    spreads: dict[str, Spread]  # species id -> most common spread
    lead_rate: dict[str, float]  # species -> P(lead | on team)
    names: dict[str, str]  # species id -> name as used in replay tables (e.g. 'Zamazenta-*')
    in_battle_update: bool = True  # re-weight unrevealed moves with set-archetype posteriors

    def marginal_only(self) -> "BeliefModel":
        """Ablation: Smogon marginal prior per species, no team/core conditioning, no in-battle
        archetype update (revealed information is still used)."""
        from dataclasses import replace

        smogon = self.prior
        while hasattr(smogon, "base"):
            smogon = smogon.base
        return replace(self, prior=smogon, in_battle_update=False)

    @classmethod
    def build(
        cls, format_id: str = "gen9ou", cutoff: int = 1825, exclude_teams: set[str] | None = None
    ) -> "BeliefModel":
        """``exclude_teams``: team keys ('A|B|...' sorted species) whose games are removed from the
        training data, so that those teams are *unknown* to the model (held-out evaluation)."""
        m = pd.read_parquet(OUT / f"{format_id}_mons.parquet")
        if exclude_teams:
            bad = set(m.loc[m.team.isin(exclude_teams), "id"])
            m = m[~m.id.isin(bad)]
        brought = m[m.brought]
        months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
        stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / f"{format_id}-{cutoff}.json")
        teams = team_table(m)
        cores = mine_cores(
            [tuple(t) for t in teams.species],
            max_size=6,
            absorb=0.6,
            min_support=max(30, len(teams) // 300),
        )
        prior = TeamPrior(
            brought, CorePrior(brought, cores, SpeciesReplayPrior(brought, SmogonPrior(stats)))
        )
        spreads = {}
        for name, s in stats.species.items():
            if s.spreads:
                spreads[to_id(name)] = Spread.parse(next(iter(s.spreads)))
        lead_rate = m.groupby("species").lead.mean().to_dict()
        names = {to_id(s.replace("-*", "")): s for s in m.species.unique()}
        return cls(prior, mine_sets(m), spreads, lead_rate, names)

    def display(self, species: str) -> str:
        """poke-env species id (e.g. 'zamazentacrowned', 'greattusk') -> table name."""
        sid = to_id(species)
        if sid in self.names:
            return self.names[sid]
        for k, v in self.names.items():
            if sid.startswith(k) and v.endswith("-*"):
                return v
        entry = GenData.from_gen(9).pokedex.get(sid)
        return entry["name"] if entry else species

    @classmethod
    def load(cls, rebuild: bool = False, heldout_pool: str | None = None) -> "BeliefModel":
        """Cached model. ``heldout_pool``: a team-pool directory (with ``index.json``) whose
        teams are excluded from training -> belief_model_heldout_<pool name>.pkl (one cache per
        pool: a model held out on one pool has seen the teams of every other)."""
        path = CACHE
        if heldout_pool is not None:
            path = CACHE.with_name(f"belief_model_heldout_{Path(heldout_pool).name}.pkl")
        if path.exists() and not rebuild:
            return pickle.loads(path.read_bytes())
        exclude = None
        if heldout_pool is not None:
            exclude = set(json.loads((Path(heldout_pool) / "index.json").read_text()).values())
        model = cls.build(exclude_teams=exclude)
        path.write_bytes(pickle.dumps(model))
        return model

    # ---------------------------------------------------------------------------------
    def spread_for(self, species: str) -> Spread:
        sid = to_id(species)
        if sid in self.spreads:
            return self.spreads[sid]
        match = [v for k, v in self.spreads.items() if k.startswith(sid) or sid.startswith(k)]
        return match[0] if match else Spread()

    def opponent_view(self, mon: Pokemon, team_species: tuple[str, ...]) -> tuple[MonView, list]:
        """(MonView with estimated stats / item probabilities, likely moves as poke-env Moves)."""
        species = _preview_name(mon, team_species)
        dist = self.prior.predict(species, team_species)
        stats = calc_stats(mon.base_stats, self.spread_for(mon.species))
        if mon.item and mon.item not in ("unknown_item", ""):
            items = {mon.item: 1.0}
        elif mon.item == "":
            items = {}
        else:
            items = dist.item
        move_p = dict(dist.move)
        ss = self.sets.get(species)
        revealed = [m.id for m in mon.moves.values()]
        if self.in_battle_update and ss is not None and (revealed or mon.item or mon.tera_type):
            post = ss.posterior(
                item=_display_item(mon.item, ss), moves=[_display_move(x, ss) for x in revealed]
            )
            arch_p: dict[str, float] = {}
            for k, w in enumerate(post):
                for name, p in zip(ss.vocab["move"], ss.params["move"][k], strict=False):
                    arch_p[to_id(name)] = arch_p.get(to_id(name), 0.0) + w * p
            # combine: prior x (archetype posterior / archetype marginal), as in the experiment
            marg: dict[str, float] = {}
            for k, w in enumerate(ss.params["pi"]):
                for name, p in zip(ss.vocab["move"], ss.params["move"][k], strict=False):
                    marg[to_id(name)] = marg.get(to_id(name), 0.0) + w * p
            move_p = {
                k: v * (arch_p.get(k, 1e-3) / max(marg.get(k, 1e-3), 1e-3))
                for k, v in move_p.items()
            }
        likely = list(revealed)
        for mid in sorted(move_p, key=move_p.get, reverse=True):
            if len(likely) >= 4:
                break
            if mid not in likely and mid in _MOVES:
                likely.append(mid)
        moves = [mon.moves[m] if m in mon.moves else Move(m, gen=9) for m in likely]
        return MonView(mon, stats, items, mon.ability, ability_probs(mon)), moves


@lru_cache(maxsize=1)
def _ability_usage(format_id: str = "gen9ou") -> dict[str, dict[str, float]]:
    """species id -> {ability id: share} from the latest Smogon month (all ratings)."""
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / f"{format_id}-0.json")
    return {
        to_id(n): {to_id(k): v for k, v in s.abilities.items()} for n, s in stats.species.items()
    }


def ability_probs(mon: Pokemon) -> dict[str, float]:
    """Distribution over an opponent's ability while it is unknown: Smogon usage restricted to
    the species' possible abilities, uniform over them when there is no usage data."""
    if mon.ability:
        return {to_id(mon.ability): 1.0}
    possible = [to_id(a) for a in (mon.possible_abilities or [])]
    try:
        usage = _ability_usage().get(to_id(mon.species), {})
    except (OSError, ValueError, KeyError):
        usage = {}
    d = {a: usage.get(a, 0.0) for a in possible} if possible else dict(usage)
    t = sum(d.values())
    if t <= 0:
        return {a: 1 / len(possible) for a in possible} if possible else {}
    return {a: v / t for a, v in d.items()}


def own_view(mon: Pokemon) -> MonView:
    stats = {k: (v or 0) for k, v in mon.stats.items()}
    if not stats.get("hp"):
        stats["hp"] = mon.max_hp or 1
    return MonView(mon, stats, {mon.item: 1.0} if mon.item else {}, mon.ability)


_MOVES = set(GenData.from_gen(9).moves)


def _preview_name(mon: Pokemon, team_species: tuple[str, ...]) -> str:
    """Map a battle Pokemon to the species name used in team preview / replay tables."""
    sid = to_id(mon.species)
    for s in team_species:
        if to_id(s.replace("-*", "")) == sid:
            return s
    for s in team_species:
        base = to_id(s.replace("-*", ""))
        if sid.startswith(base) or base.startswith(sid):
            return s
    return mon.species


def _display_move(mid: str, ss: SpeciesSets) -> str:
    for name in ss.vocab["move"]:
        if to_id(name) == mid:
            return name
    return mid


def _display_item(item: str | None, ss: SpeciesSets) -> str | None:
    if not item or item == "unknown_item":
        return None
    for name in ss.vocab["item"]:
        if to_id(name) == item:
            return name
    return None
