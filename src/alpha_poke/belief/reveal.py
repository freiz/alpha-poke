"""Negative evidence for hidden moves: how likely a move a mon carries is still unrevealed after
it has made t move actions (design D11, direction B).

From replays, per mon and game: the number of move actions it made (``total``) and, for every
move it used, how many of its own move actions came before the first use (``first``). Then

    r(m, t) = P(m revealed within the first t move actions | the mon carries m)
            = rho(m) * F(m, t)

  F(m, t): first-use time distribution among mons that used m and made >= ``LONG`` move actions
           (long stays, so the first use is rarely censored);
  rho(m):  P(eventually used | carried, long stay) = (reveal rate among long stays) / (Smogon's
           P(set contains m)), clipped to [RHO_MIN, 1]: situational moves (Healing Wish, Destiny
           Bond, Trick, ...) are often carried but never clicked.

Estimated per (species, move) when there is enough data, else pooled per move (ratio of sums).
In battle: a carried-but-unrevealed move has likelihood 1 - r(m, t) of being still unrevealed;
``engine_state.sample_set`` multiplies it into the archetype posterior and the move weights.
"""

import gzip
import json
import pickle
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from alpha_poke import paths
from alpha_poke.analysis.roles import to_id

MAX_T = 16  # F(m, t) is tabulated for t = 0..MAX_T (t >= MAX_T uses the last value)
LONG = 10  # "long stay": >= LONG move actions in the game
MIN_SPECIES_OBS = 40  # per-(species, move) estimates need this many long-stay first uses
RHO_MIN = 0.05
CACHE = paths.BELIEF / "reveal_model.pkl"


def first_use_rows(replay) -> list[tuple[str, str, int, int | None]]:
    """(species, move id, total move actions, first-use index or None) per mon and used move,
    plus one (species, "", total, None) row per mon (the denominator of reveal rates)."""
    seq: dict[tuple[str, str], list[str]] = defaultdict(list)
    for a in replay.actions:
        if a.kind == "move" and a.move:
            seq[(a.side, a.mon)].append(to_id(a.move))
    rows = []
    for (_, species), moves in seq.items():
        total = len(moves)
        first: dict[str, int] = {}
        for i, mv in enumerate(moves):
            first.setdefault(mv, i)
        rows.append((species, "", total, None))
        rows += [(species, mv, total, i) for mv, i in first.items()]
    return rows


@dataclass
class RevealModel:
    # key: (species id, move id) or ("", move id) for the pooled estimate
    F: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)
    rho: dict[tuple[str, str], float] = field(default_factory=dict)

    def r(self, species: str, move: str, t: int) -> float:
        """P(revealed within the first t move actions | carried)."""
        if t <= 0:
            return 0.0
        sid, mid = to_id(species), to_id(move)
        f = self.F.get((sid, mid))
        if f is None:
            f = self.F.get(("", mid))
        if f is None:
            return 0.0  # unknown move: no evidence either way
        rho = self.rho.get((sid, mid), self.rho.get(("", mid), 1.0))
        return float(rho * f[min(t, MAX_T)])


    @classmethod
    def fit(cls, rows, smogon) -> "RevealModel":
        """rows: iterable of ``first_use_rows`` tuples; smogon: UsageStats (P(set contains m))."""
        long_mons: dict[str, int] = defaultdict(int)  # species -> long stays
        first: dict[tuple[str, str], list[int]] = defaultdict(list)  # long-stay first uses
        for species, mv, total, i in rows:
            sid = to_id(species)
            if total < LONG:
                continue
            if mv == "":
                long_mons[sid] += 1
            else:
                first[(sid, mv)].append(i)
        has = {}  # (species id, move id) -> Smogon P(set contains m)
        for name, s in smogon.species.items():
            for mv, p in s.move_has.items():
                has[(to_id(name), to_id(mv))] = p
        model = cls()
        pooled_first: dict[str, list[int]] = defaultdict(list)
        pooled_num: dict[str, float] = defaultdict(float)
        pooled_den: dict[str, float] = defaultdict(float)
        for (sid, mid), idx in first.items():
            pooled_first[mid] += idx
            n = long_mons[sid]
            p = has.get((sid, mid))
            if p:
                pooled_num[mid] += len(idx)
                pooled_den[mid] += n * p
            if len(idx) >= MIN_SPECIES_OBS:
                model.F[(sid, mid)] = _cdf(idx)
                if p and n:
                    model.rho[(sid, mid)] = _clip(len(idx) / (n * p))
        for mid, idx in pooled_first.items():
            if len(idx) >= MIN_SPECIES_OBS // 2:
                model.F[("", mid)] = _cdf(idx)
                if pooled_den[mid] > 0:
                    model.rho[("", mid)] = _clip(pooled_num[mid] / pooled_den[mid])
        return model

    @classmethod
    def load(cls, path: Path = CACHE) -> "RevealModel | None":
        return pickle.loads(path.read_bytes()) if path.exists() else None

    def save(self, path: Path = CACHE) -> None:
        path.write_bytes(pickle.dumps(self))


def _cdf(idx: list[int]) -> np.ndarray:
    """F[t] = P(first use index < t), t = 0..MAX_T."""
    a = np.asarray(idx)
    return np.array([(a < t).mean() for t in range(MAX_T + 1)])


def _clip(x: float) -> float:
    return float(min(1.0, max(RHO_MIN, x)))


def replay_first_use_rows(replays_dir: Path, format_id: str = "gen9ou", ids=None):
    """Parse the downloaded replays (optionally only ``ids``) into ``first_use_rows``."""
    from alpha_poke.replay.parser import parse_replay

    db = sqlite3.connect(replays_dir / "index.sqlite")
    q = "SELECT id, format_id FROM replays WHERE status='done' AND format_id=?"
    for rid, fid in db.execute(q, (format_id,)).fetchall():
        if ids is not None and rid not in ids:
            continue
        with gzip.open(replays_dir / fid / f"{rid}.json.gz", "rt", encoding="utf-8") as f:
            yield from first_use_rows(parse_replay(json.load(f)))
