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
     catalog (data/teams/catalog.jsonl; no completion at all);
  4. every team passes the local Showdown validator (canonical export); a side that fails is
     completed again (up to ``retries`` times), otherwise the game is skipped.
"""

import json
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
from alpha_poke.teams import catalog
from alpha_poke.teams.replay_pool import STAT_NAMES, smogon_entry
from alpha_poke.teams.validate import check

DAY = 86400


@dataclass
class Side:
    text: str  # canonical Showdown export
    kind: str  # "replay" (completed from a real game) / "catalog" (a complete real team)
    ref: str  # "<game id>:<p1|p2>" / catalog entry id


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


class TeamSampler:
    def __init__(self, belief, since: int | None = None, half_life_days: float = 120.0,
                 catalog_frac: float = 0.3, temp: float = 1.3, spread_temp: float = 1.0,
                 move_beta: float = 1.0, seed: int = 0, retries: int = 3,
                 stats_cutoff: str = "1500", popularity_beta: float = 0.0):  # fmt: skip
        g = pd.read_parquet(GAMES, columns=["id", "time", "r1", "r2", "winner", "shard", "row",
                                            "team1", "team2"])  # fmt: skip
        g = g[g.winner > 0]
        if since is not None:
            g = g[g.time >= since]
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
        self.spread_temp, self.move_beta, self.retries = spread_temp, move_beta, retries
        self.rng = random.Random(seed)
        self.banned_moves: set[str] = set()  # move ids the validator reported as banned
        self.np_rng = np.random.default_rng(seed)

    def spread(self, species: str) -> str:
        smog = smogon_entry(self.stats, species)
        if smog is None or not smog.spreads:
            return "Serious:84/84/84/84/84/84"
        names, w = zip(*smog.spreads.items(), strict=True)
        w = np.asarray(w, dtype=float) ** (1 / self.spread_temp)
        return self.rng.choices(names, weights=w, k=1)[0]

    def complete(self, records: list) -> str:
        """One completed export of a replay side (preview order)."""
        from alpha_poke.agents.engine_state import sample_set
        from alpha_poke.train.positions import _known

        names = tuple(self.belief.display(to_id(r.species.replace("-*", ""))) for r in records)
        sets = []
        for rec in records:
            species = _species(rec)
            mon = Pokemon(details=species, gen=9)
            known = _known(rec)
            known.moves = [m for m in known.moves if m not in self.banned_moves]
            s = sample_set(self.belief, mon, names, self.rng, self.move_beta, known=known,
                           temp=self.temp)  # fmt: skip
            moves = [m for m in s.moves if m not in self.banned_moves
                     and (m != "tackle" or "tackle" in known.moves)][:4]  # fmt: skip
            if len(moves) < 4:
                moves += self._top_up(species, moves, 4 - len(moves))
            tera = s.tera if s.tera and s.tera != "typeless" else ""
            sets.append(export_set(species, s.item, s.ability, tera, moves,
                                   self.spread(species)))  # fmt: skip
        return "\n\n".join(sets)

    def _try_complete(self, records: list) -> str:
        """``complete``, or "" (rejected by the validator) for a species the dex does not know
        (nonstandard formes in old logs)."""
        try:
            return self.complete(records)
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
        stats = {"games": 0, "skipped": 0, "invalid_completions": 0, "catalog_sides": 0}
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
                    if self.rng.random() < self.catalog_frac:
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
                        sides[(gid, s)] = Side(x["text"], "replay", f"{gid}:{s}")
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
    path.write_text("".join(json.dumps(p.row()) + "\n" for p in pairs))


def load(path: Path) -> list[TeamPair]:
    out = []
    for line in path.read_text().splitlines():
        d = json.loads(line)
        out.append(TeamPair(Side(**d["p1"]), Side(**d["p2"]), d["game"], d["time"],
                            tuple(d["ratings"])))  # fmt: skip
    return out
