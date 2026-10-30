"""Team pairs for self-play (design D5 / D15).

Per game:
  1. a real game is drawn from the replays (the lite scan of all Metamon games), recent ones
     more often (weight 0.5 ** (age / half_life)); its two teams are the pair (teams meet as on
     the ladder: rating-matched, so the pair keeps their correlation);
  2. each side's set is completed: what the replay revealed (moves, item, ability, tera) is
     kept, the rest is drawn from the belief sampler (``engine_state.sample_set``) at
     temperature ``temp`` > 1, EVs / nature from the species' Smogon spread distribution at
     ``spread_temp`` (completion more varied than what the search's belief expects, D5; the
     search's belief assumes one fixed spread per species, so the natural spread distribution
     already differs; flattening it gives odd spreads from its long tail). Moves banned since
     the game (learned from the validator's messages, e.g. Tera Blast) are dropped and drawn
     again; species without belief data get their moves from the Smogon statistics within
     their learnset;
  3. with probability ``catalog_frac`` a side is replaced by a complete real team from the
     catalog (teams/catalog.jsonl; no completion at all);
  3'. with probability ``synth_frac`` (first: the rest split by ``catalog_frac``) a side is a
     synthetic team (2026-10-26, more varied teams than the ladder's own compositions): its six
     species drawn one after another by the Smogon usage and the teammates of those already in
     (``Composer``: the compositions' joint distribution, not each species on its own), its sets
     completed as a replay side's with nothing known (the belief's archetypes: moves, item,
     ability and tera drawn together), each set's move slots, item, ability and tera redrawn
     with probability ``set_eps`` (noise), then ``synth_steps`` Metropolis-Hastings steps over
     the sets (one mon's set drawn again the same way, kept with probability
     min(1, exp(synth_beta * the change of the team's cross-mon synergy)): selfplay.synergy --
     the combos the ladder builds, a Drought with a Chlorophyll, more often than their species
     alone explain);
  4. every team passes the local Showdown validator (canonical export); a side that fails is
     completed again (up to ``retries`` times), otherwise the game is skipped.
"""

import collections
import json
import logging
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from poke_env.battle import Pokemon

from alpha_poke.analysis.games_lite import DEST as GAMES
from alpha_poke.analysis.games_lite import logs
from alpha_poke.analysis.roles import to_id
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats
from alpha_poke.replay.parser import parse_replay
from alpha_poke.selfplay.synergy import PATH as SYNERGY
from alpha_poke.selfplay.synergy import Synergy
from alpha_poke.selfplay.synergy import tokens as synergy_tokens
from alpha_poke.teams import catalog
from alpha_poke.teams.replay_pool import STAT_NAMES, smogon_entry
from alpha_poke.teams.validate import check

DAY = 86400


class Composer:
    """Synthetic team compositions (2026-10-26): species one after another, the first by its
    usage, each next by its usage and how often it is the teammate of those already chosen --
    P(B) ** (1 / tau) x (the product of lift(A, B) over the chosen A) ** gamma, lift(A, B) =
    P(B | A) / P(B) from Smogon's Teammates (co-occurrence weights: a team's five others,
    P(B | A) = 5 w(A, B) / sum_B' w(A, B')). tau > 1 flattens the usage (rarer species more often),
    gamma 0 ignores the teammates; a pair never seen together keeps ``floor`` of a lift. One mon
    per base species (the species clause; Ogerpon's masks, Urshifu's styles alike). ``eps``: a
    pick's chance of the noise (the usage flattened by ``noise_tau``, no teammates)."""

    # (gamma 0.7: the top-300 teammate pairs' rates against the ladder's 0.91, 98.7% compositions
    # distinct -- 2026-10-26; the geometric mean's 0.82, a gamma 1 product's 0.91 but 94%)
    def __init__(self, stats: UsageStats, min_usage: float = 0.002, tau: float = 1.0, gamma: float = 0.7,
                 floor: float = 0.05, eps: float = 0.0, noise_tau: float = 3.0):  # fmt: skip
        from poke_env.data import GenData

        dex = GenData.from_gen(9).pokedex
        self.names = [
            x.name for x in stats.ranked() if x.usage >= min_usage and to_id(x.name) in dex
        ]
        self.base = {n: to_id(dex[to_id(n)].get("baseSpecies") or n) for n in self.names}
        idx = {n: i for i, n in enumerate(self.names)}
        usage = np.array([stats.species[n].usage for n in self.names], dtype=float)
        self.prior = usage ** (1 / tau)
        self.prior /= self.prior.sum()
        # (the noise, 2026-10-26: a pick with probability eps by the usage flattened -- noise_tau --
        # and no teammates; still among the species the ladder brings, the validator's after)
        self.eps, self.flat = eps, usage ** (1 / noise_tau) / (usage ** (1 / noise_tau)).sum()
        p_b = usage / usage.sum() * 6  # (a species' share of a team's six)
        n = len(self.names)
        self.log_lift = np.full((n, n), np.log(floor))
        for a in self.names:
            tm = stats.species[a].teammates
            total = sum(tm.values())
            if not total:
                continue
            for b, w in tm.items():
                if b in idx and w > 0:
                    self.log_lift[idx[a], idx[b]] = np.log(max(5 * w / total / p_b[idx[b]], floor))
        self.gamma = gamma
        self.same_base = [[k for k, m in enumerate(self.names) if self.base[m] == self.base[nm]]
                          for nm in self.names]  # fmt: skip

    def sample(self, rng: np.random.Generator) -> list[str]:
        chosen: list[int] = []
        for _ in range(6):
            if rng.random() < self.eps:
                w = self.flat.copy()
            else:
                w = np.log(self.prior)
                # (the lifts multiplied -- each chosen mon a factor; their mean too weak)
                if chosen:
                    w = w + self.gamma * self.log_lift[chosen].sum(axis=0)
                w = np.exp(w - w.max())
            for j in chosen:  # (the species clause: by base species)
                w[self.same_base[j]] = 0
            chosen.append(int(rng.choice(len(w), p=w / w.sum())))
        return [self.names[j] for j in chosen]


@dataclass
class Side:
    text: str  # canonical Showdown export
    # "replay" (completed from a real game) / "catalog" (a complete real team) / "synthetic"
    # (Composer's)
    kind: str
    ref: str  # "<game id>:<p1|p2>" / catalog entry id / "syn:<game id>:<p1|p2>"


@dataclass
class TeamPair:
    p1: Side
    p2: Side
    game: str  # the real game the pair was drawn from
    time: int
    ratings: tuple[int, int]

    def row(self) -> dict:
        return asdict(self)


def export_set(species: str, item: str, ability: str, tera: str, moves: list[str],
               spread: str) -> str:  # fmt: skip
    """A Showdown export of one set (ids are fine: the validator helper writes names)."""
    nature, evs = spread.split(":")
    ev_text = " / ".join(f"{v} {s}" for v, s in zip(evs.split("/"), STAT_NAMES, strict=True)
                         if v != "0")  # fmt: skip
    lines = [f"{species} @ {item}" if item and item != "none" else species]
    lines += [f"Ability: {ability}"] if ability and ability != "none" else []
    lines += [f"Tera Type: {tera}"] if tera else []
    lines += [f"EVs: {ev_text}"] if ev_text else []
    lines += [f"{nature} Nature"] + [f"- {m}" for m in moves]
    return "\n".join(lines)


def _species(rec) -> str:
    """The species for a team export: team preview hides some formes ("Urshifu-*"); the forme
    seen in battle if any, else the base species."""
    if not rec.species.endswith("-*"):
        return rec.species
    base = rec.species[:-2]
    seen = [f for f in rec.forms if f.startswith(base) and not f.endswith("-Tera")
            and "Crowned" not in f]  # fmt: skip
    return seen[0] if seen else base


# kinds of a set's parts whose reveal rates correct the marginal draws (a tera type shows only
# when used, whatever it is: no correction)
REVEAL_KINDS = ("item", "ability", "move")
MIN_EXPECTED = 20.0  # (a part expected fewer times in the sample: its kind's overall rate)
# the least weight a part keeps (x its usage) however often it shows: a rate of 1 is an estimate,
# and a set must still find four moves
UNSEEN_FLOOR = 0.02
# moves a Choice item holder still uses (the item given away)
CHOICE_STATUS_OK = frozenset({"trick", "switcheroo"})


def reveal_rates(records: list, stats: UsageStats) -> dict[str, dict[str, float]]:
    """How often a set's part shows in a game when a mon that was on the field has it (2026-10-30,
    the fair evaluation pool): per kind ("item", "ability", "move"), id -> the times replays
    revealed it over the times Smogon's usage (complete teams: no reveal bias) says brought mons
    had it, at most 1; "default" -> each kind's overall rate. Leftovers heal every turn (near 1),
    Heavy-Duty Boots almost never show (near 0). ``records``: replay.parse_replay mons."""
    exp = {k: collections.Counter() for k in REVEAL_KINDS}
    obs = {k: collections.Counter() for k in REVEAL_KINDS}
    for rec in records:
        if not rec.brought:
            continue
        smog = smogon_entry(stats, _species(rec))
        if smog is None:
            continue
        for kind, dist, seen in (("item", smog.items, [rec.item] if rec.item else []),
                                 ("ability", smog.abilities, [rec.ability] if rec.ability else []),
                                 ("move", smog.move_has, rec.moves)):  # fmt: skip
            for k, p in dist.items():
                if to_id(k):
                    exp[kind][to_id(k)] += p
            for x in seen:
                obs[kind][to_id(x)] += 1
    out: dict[str, dict[str, float]] = {"default": {}}
    for kind in REVEAL_KINDS:
        total = sum(exp[kind].values())
        out["default"][kind] = (
            min(1.0, sum(obs[kind][k] for k in exp[kind]) / total) if total else 0.0
        )
        out[kind] = {
            k: min(1.0, obs[kind][k] / e) for k, e in exp[kind].items() if e >= MIN_EXPECTED
        }
    return out


def marginal_set(smog, known, brought: bool, rates: dict, legal: set, rng: random.Random,
                 banned: frozenset = frozenset()) -> tuple[str, str, str, list[str]]:  # fmt: skip
    """(item, ability, tera, moves) of one side's mon from a real game (the fair evaluation
    pool): what the game revealed (``known``) kept; the rest each drawn from the species'
    Smogon usage, weighted for a mon that was on the field by 1 - its reveal rate
    (``reveal_rates``: a part that would have shown is unlikely when it did not; at least
    UNSEEN_FLOOR of its usage); a mon never
    on the field: the usage as is. Coherent: no Assault Vest / Choice item beside a status move
    (Trick / Switcheroo with a Choice item allowed), moves legal for the species."""
    from alpha_poke.agents.engine_state import _status

    def weights(dist: dict, kind: str | None, skip=()) -> dict[str, float]:
        out = {}
        for k, p in dist.items():
            kid = to_id(k)
            if not kid or kid in skip:
                continue
            rho = 0.0
            if kind is not None and brought:
                rho = rates.get(kind, {}).get(kid, rates.get("default", {}).get(kind, 0.0))
            if p > 0:
                out[kid] = p * max(1 - rho, UNSEEN_FLOOR)
        return out

    def draw(w: dict) -> str | None:
        return rng.choices(list(w), weights=list(w.values()))[0] if w else None

    moves = [m for m in known.moves if m not in banned][:4]
    status = any(_status(m) and m not in CHOICE_STATUS_OK for m in moves)
    blocked = {"assaultvest", "choiceband", "choicespecs", "choicescarf"} if status else set()
    item = known.item or draw(weights(smog.items, "item", blocked)) or "none"
    ability = known.ability or draw(weights(smog.abilities, "ability")) or ""
    tera = known.tera or draw(weights({k: v for k, v in smog.tera_types.items()
                                       if to_id(k) != "stellar"}, None)) or ""  # fmt: skip
    choice = item.startswith("choice")
    pool = weights({m: p for m, p in smog.move_has.items() if to_id(m) in legal}, "move",
                   set(moves) | banned)  # fmt: skip
    if item == "assaultvest" or choice:
        pool = {
            m: w for m, w in pool.items() if not _status(m) or (choice and m in CHOICE_STATUS_OK)
        }
    while len(moves) < 4 and pool:
        m = draw(pool)
        moves.append(m)
        pool.pop(m)
    return item, ability, tera, moves


class TeamSampler:
    def __init__(self, belief, since: int | None = None, half_life_days: float = 120.0,
                 catalog_frac: float = 0.3, temp: float = 1.3, spread_temp: float = 1.0,
                 move_beta: float = 1.0, seed: int = 0, retries: int = 3,
                 stats_cutoff: str = "1500", popularity_beta: float = 0.0, synth_frac: float = 0.0,
                 synth_tau: float = 1.0, synth_gamma: float = 0.7, synth_eps: float = 0.1,
                 set_eps: float = 0.1, synth_beta: float = 0.5, synth_steps: int = 12,
                 synergy=None, fill: str = "belief", min_rating: int = 0, exclude=None,
                 rates: dict | None = None):  # fmt: skip
        """``fill``: how a replay side's unrevealed parts are drawn -- "belief" (the search's
        belief, flattened by ``temp``: self-play's variety) or "marginal" (Smogon's usage,
        reveal-corrected: ``marginal_set`` with ``rates``; the fair evaluation pool).
        ``min_rating``: only games both players were rated at least this before; ``exclude``:
        game ids never drawn (self-play's and earlier tests' sources)."""
        g = pd.read_parquet(GAMES, columns=["id", "time", "p1", "p2", "r1", "r2", "winner", "shard",
                                            "row", "team1", "team2"])  # fmt: skip
        g = g[g.winner > 0]
        if since is not None:
            g = g[g.time >= since]
        if min_rating:
            g = g[(g.r1 >= min_rating) & (g.r2 >= min_rating)]
        if exclude:
            g = g[~g.id.isin(set(exclude))]
        age = (g.time.max() - g.time) / DAY
        self.games = g.reset_index(drop=True)
        self.weights = np.array(0.5 ** (age / half_life_days), dtype=float)
        if popularity_beta > 0:
            # flattened popularity (design D16): a game's weight / (n1 n2) ** (beta / 2), n = how
            # many games in the window had that side's six species; beta 0 = the ladder's own
            # distribution, 1 = every composition alike
            comps = pd.concat([self.games.team1, self.games.team2]).value_counts()
            n1 = self.games.team1.map(comps).to_numpy(float)
            n2 = self.games.team2.map(comps).to_numpy(float)
            self.weights = self.weights / (n1 * n2) ** (popularity_beta / 2)
        self.weights /= self.weights.sum()
        self.catalog = [e for e in catalog.load() if e.complete]
        months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
        self.stats = UsageStats.load(
            DEFAULT_DIR / months[-1] / "chaos" / f"gen9ou-{stats_cutoff}.json"
        )
        self.belief, self.catalog_frac, self.temp = belief, catalog_frac, temp
        self.synth_frac = synth_frac
        self.composer = (Composer(self.stats, tau=synth_tau, gamma=synth_gamma, eps=synth_eps)
                         if synth_frac > 0 else None)  # fmt: skip
        self.set_eps = set_eps  # (a synthetic set's noise: _noisy)
        if self.composer is not None and synergy is None:
            if SYNERGY.exists():
                synergy = Synergy.load(SYNERGY)
            else:  # (the sets then drawn each on its own: scripts/build_synergy.py builds it)
                logging.getLogger(__name__).warning("no %s: sets without synergy", SYNERGY)
        # (beta 0.5, 12 steps -- 2026-10-26, 1,000 teams: a second Trick Room setter beside one
        # 0.17 -> 0.46 (beta 1.0: 0.53, the ladder's revealed 0.53), the items' TV against
        # Smogon's 0.23 -> 0.17; the lower beta for the noise)
        self.synergy, self.synth_beta, self.synth_steps = synergy, synth_beta, synth_steps
        self.spread_temp, self.move_beta, self.retries = spread_temp, move_beta, retries
        self.rng = random.Random(seed)
        self.banned_moves: set[str] = set()  # move ids the validator reported as banned
        self.np_rng = np.random.default_rng(seed)
        self.fill, self.rates = fill, rates or {}
        # (marginal fills: how many parts of the sets were revealed / drawn)
        self.fill_counts: dict[str, int] = collections.Counter()

    def spread(self, species: str) -> str:
        smog = smogon_entry(self.stats, species)
        if smog is None or not smog.spreads:
            return "Serious:84/84/84/84/84/84"
        names, w = zip(*smog.spreads.items(), strict=True)
        w = np.asarray(w, dtype=float) ** (1 / self.spread_temp)
        return self.rng.choices(names, weights=w, k=1)[0]

    def complete(self, records: list) -> str:
        """One completed export of a replay side (preview order)."""
        from alpha_poke.train.positions import _known

        if self.fill == "marginal":
            return "\n\n".join(self._marginal(rec, _known(rec)) for rec in records)

        names = tuple(self.belief.display(to_id(r.species.replace("-*", ""))) for r in records)
        return self._complete([(_species(rec), _known(rec)) for rec in records], names)

    def _marginal(self, rec, known) -> str:
        """One mon's export: ``marginal_set`` (the game's revealed parts, the rest from usage)."""
        from alpha_poke.dex import MOVE_IDS, learnset

        species = _species(rec)
        smog = smogon_entry(self.stats, species)
        if smog is None:
            raise KeyError(species)  # (rejected: _try_complete)
        legal = {m for m in (learnset(species) or set()) if m in MOVE_IDS}
        item, ability, tera, moves = marginal_set(smog, known, rec.brought, self.rates, legal,
                                                  self.rng, frozenset(self.banned_moves))  # fmt: skip
        c = self.fill_counts
        c["moves_revealed"] += len(known.moves[:4])
        c["moves_drawn"] += len(moves) - len(known.moves[:4])
        for part, k in (("item", known.item), ("ability", known.ability), ("tera", known.tera)):
            c[f"{part}_{'revealed' if k else 'drawn'}"] += 1
        return export_set(species, item, ability, tera, moves, self.spread(species))

    def synthetic(self) -> str:
        """One completed export of a synthetic team (Composer's six; nothing known; the sets'
        synergy by Metropolis-Hastings: an independence proposal per mon, the target the
        completion's own distribution x exp(beta * team_score))."""
        from alpha_poke.agents.engine_state import KnownSet

        species = self.composer.sample(self.np_rng)
        names = tuple(self.belief.display(to_id(x)) for x in species)
        sets = [self._draw_set(x, KnownSet(moves=[]), names, self.set_eps) for x in species]
        if self.synergy is not None and self.synth_steps > 0:
            feats = [synergy_tokens(ability, item, moves) for _, item, ability, _, moves in sets]
            score = self.synergy.team_score(feats)
            for _ in range(self.synth_steps):
                i = self.rng.randrange(len(sets))
                new = self._draw_set(species[i], KnownSet(moves=[]), names, self.set_eps)
                trial = feats[:i] + [synergy_tokens(new[2], new[1], new[4])] + feats[i + 1 :]
                s = self.synergy.team_score(trial)
                if s >= score or self.rng.random() < np.exp(self.synth_beta * (s - score)):
                    sets[i], feats, score = new, trial, s
        return "\n\n".join(
            export_set(sp, item, ab, tera, moves, self.spread(sp))
            for sp, item, ab, tera, moves in sets
        )

    def _noisy(self, species: str, moves: list, item: str, ability: str, tera: str, eps: float):
        """A set with noise (2026-10-26): each move slot, the item, the ability and the tera type
        with probability ``eps`` drawn again from what the ladder uses on the species (Smogon's,
        weights square-rooted: its long tail more often), moves within its learnset; the
        validator after -- legal sets only."""
        from alpha_poke.dex import MOVE_IDS, learnset

        smog = smogon_entry(self.stats, species)
        if smog is None or eps <= 0:
            return moves, item, ability, tera

        def draw(d: dict, skip=()):
            pool = {k: v**0.5 for k, v in d.items() if k and k not in skip}
            return self.rng.choices(list(pool), weights=list(pool.values()))[0] if pool else None

        legal = learnset(species) or set()
        out = list(moves)
        for i in range(len(out)):
            if self.rng.random() < eps:
                pool = {m: w for m, w in smog.move_has.items() if m in legal and m in MOVE_IDS}
                m = draw(pool, skip=set(out) | self.banned_moves)
                if m:
                    out[i] = m
        if self.rng.random() < eps:
            item = to_id(draw(smog.items) or item)
        if self.rng.random() < eps:
            ability = to_id(draw(smog.abilities) or ability)
        if self.rng.random() < eps:
            tera = to_id(
                draw({k: v for k, v in smog.tera_types.items() if to_id(k) != "stellar"}) or tera
            )
        return out, item, ability, tera

    def _draw_set(self, species: str, known, names: tuple, noise: float = 0.0) -> tuple:
        """(species, item, ability, tera, moves): what is known of the set kept, the rest drawn."""
        from alpha_poke.agents.engine_state import sample_set

        mon = Pokemon(details=species, gen=9)
        known.moves = [m for m in known.moves if m not in self.banned_moves]
        s = sample_set(self.belief, mon, names, self.rng, self.move_beta, known=known,
                       temp=self.temp)  # fmt: skip
        moves = [m for m in s.moves if m not in self.banned_moves
                 and (m != "tackle" or "tackle" in known.moves)][:4]  # fmt: skip
        if len(moves) < 4:
            moves += self._top_up(species, moves, 4 - len(moves))
        tera = s.tera if s.tera and s.tera != "typeless" else ""
        item, ability = s.item, s.ability
        if noise > 0:
            moves, item, ability, tera = self._noisy(species, moves, item, ability, tera, noise)
        return species, item, ability, tera, moves

    def _complete(self, entries: list, names: tuple, noise: float = 0.0) -> str:
        """The export of a side's (species, what is known of its set) entries, the rest drawn."""
        sets = [self._draw_set(species, known, names, noise) for species, known in entries]
        return "\n\n".join(
            export_set(sp, item, ab, tera, moves, self.spread(sp))
            for sp, item, ab, tera, moves in sets
        )

    def _try_complete(self, records) -> str:
        """``complete`` (``synthetic`` for None), or "" (rejected by the validator) for a species
        the dex does not know (nonstandard formes in old logs)."""
        try:
            return self.synthetic() if records is None else self.complete(records)
        except KeyError:
            return ""

    def _top_up(self, species: str, have: list[str], n: int) -> list[str]:
        """Up to ``n`` more moves (ids) from the species' Smogon move usage, legal for it."""
        from alpha_poke.dex import MOVE_IDS, learnset

        smog = smogon_entry(self.stats, species)
        legal = learnset(species) or set()
        if smog is None:
            return []
        skip = set(have) | self.banned_moves
        pool = {m: w for m, w in smog.move_has.items()
                if m in legal and m in MOVE_IDS and m not in skip}  # fmt: skip
        out = []
        while pool and len(out) < n:
            m = self.rng.choices(list(pool), weights=list(pool.values()))[0]
            out.append(m)
            pool.pop(m)
        return out

    def _learn_bans(self, problems: list[str]) -> None:
        for p in problems:
            m = re.search(r"move (.+) is banned", p)
            if m:
                self.banned_moves.add(to_id(m.group(1)))

    def sample(self, n: int, log=print) -> list[TeamPair]:
        """``n`` validated pairs (completion and validation in batches: one validator process
        per round)."""
        out: list[TeamPair] = []
        stats = {
            "games": 0,
            "skipped": 0,
            "invalid_completions": 0,
            "catalog_sides": 0,
            "synthetic_sides": 0,
        }
        while len(out) < n:
            k = int((n - len(out)) * 1.2) + 4
            idx = self.np_rng.choice(len(self.games), size=k, p=self.weights)
            rows = self.games.iloc[idx].to_dict("records")
            full = logs(rows)
            todo = []  # (game row, side, records) to complete
            sides: dict[tuple[str, str], Side] = {}
            games = []
            for r in rows:
                stats["games"] += 1
                rep = parse_replay(full[r["id"]])
                teams = {s: [m for m in rep.teams[s] if not m.phantom] for s in ("p1", "p2")}
                if rep.warnings or any(len(t) != 6 for t in teams.values()):
                    stats["skipped"] += 1
                    continue
                games.append(r)
                for s, recs in teams.items():
                    # (a synthetic side first -- its share of all sides -- then the rest as before:
                    # a catalog team, else the replay's side completed)
                    if self.composer is not None and self.rng.random() < self.synth_frac:
                        todo.append((r["id"], s, None))
                        stats["synthetic_sides"] += 1
                    elif self.rng.random() < self.catalog_frac:
                        e = self.rng.choice(self.catalog)
                        sides[(r["id"], s)] = Side(e.text, "catalog", e.id)
                        stats["catalog_sides"] += 1
                    else:
                        todo.append((r["id"], s, recs))
            for _ in range(self.retries):
                if not todo:
                    break
                res = check([self._try_complete(recs) for _, _, recs in todo])
                left = []
                for (gid, s, recs), x in zip(todo, res, strict=True):
                    if x["n"] == 6 and not x["problems"]:
                        sides[(gid, s)] = (Side(x["text"], "synthetic", f"syn:{gid}:{s}") if recs is None
                                           else Side(x["text"], "replay", f"{gid}:{s}"))  # fmt: skip
                    else:
                        stats["invalid_completions"] += 1
                        self._learn_bans(x["problems"])
                        left.append((gid, s, recs))
                todo = left
            for r in games:
                p1, p2 = sides.get((r["id"], "p1")), sides.get((r["id"], "p2"))
                if p1 is None or p2 is None or poke_env_clash(p1.text) or poke_env_clash(p2.text):
                    stats["skipped"] += 1
                    continue
                if len(out) < n:
                    out.append(TeamPair(p1, p2, r["id"], int(r["time"]),
                                        (int(r["r1"]), int(r["r2"]))))  # fmt: skip
        log(f"{len(out)} pairs from {stats['games']} games: {stats}")
        return out


def species_names(text: str) -> list[str]:
    """The species of a Showdown export (nicknames and gender dropped)."""
    out = []
    for block in text.strip().split("\n\n"):
        head = block.strip().splitlines()[0].split(" @ ")[0].strip()
        head = re.sub(r" \([MF]\)$", "", head)
        m = re.search(r"\(([^()]+)\)$", head)
        out.append(m.group(1) if m else head)
    return out


def poke_env_clash(text: str) -> bool:
    """A team poke-env cannot track: it matches a request's Pokemon to a team member by base
    species or by any "-" part of the name (``Pokemon.identifies_as``), so Porygon and Porygon-Z
    become one member, the team-preview request raises KeyError and the game never starts (gen 1,
    2026-10-09: a lane stuck for good)."""
    names = species_names(text)
    mons = [Pokemon(gen=9, species=to_id(n)) for n in names]
    return any(p.identifies_as(q) for i, p in enumerate(mons)
               for j, q in enumerate(names) if i != j)  # fmt: skip


def save(pairs: list[TeamPair], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(p.row()) + "\n" for p in pairs), encoding="utf-8")


def load(path: Path) -> list[TeamPair]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        out.append(TeamPair(Side(**d["p1"]), Side(**d["p2"]), d["game"], d["time"],
                            tuple(d["ratings"])))  # fmt: skip
    return out
