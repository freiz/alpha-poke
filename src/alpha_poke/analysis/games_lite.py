"""A light scan of every replay log (no full parse): players, ratings before the game, the two
teams as team preview shows them, winner. ~2M Metamon games in minutes; used for team strength
and matchup statistics and for per-player histories (design D5-L / D5-O).

Output: data/parsed/gen9ou_games_lite.parquet, one row per game:
  id, time, p1, p2 (user ids), r1, r2 (ratings, 0 = unknown), team1, team2 (sorted preview
  species joined by '|'), winner (1 / 2, 0 = tie or unknown), turns."""

import glob
import re
from concurrent.futures import ProcessPoolExecutor

import pyarrow as pa
import pyarrow.parquet as pq

from alpha_poke.analysis.roles import to_id
from alpha_poke.analysis.tables import OUT

SRC = "data/metamon/gen9ou/*.parquet"
DEST = OUT / "gen9ou_games_lite.parquet"
_POKE = re.compile(r"^\|poke\|(p[12])\|([^,|]+)", re.M)
_PLAYER = re.compile(r"^\|player\|(p[12])\|([^|\n]*)\|[^|\n]*\|?(\d*)", re.M)
_WIN = re.compile(r"^\|win\|(.*)$", re.M)
_TURN = re.compile(r"^\|turn\|(\d+)", re.M)


def scan(log: str) -> dict | None:
    teams: dict[str, list[str]] = {"p1": [], "p2": []}
    for side, sp in _POKE.findall(log):
        teams[side].append(sp.strip())
    if len(teams["p1"]) != 6 or len(teams["p2"]) != 6:
        return None
    names, ratings = {}, {}
    for side, name, rating in _PLAYER.findall(log):
        if name and side not in names:
            names[side] = name
            ratings[side] = int(rating) if rating else 0
    if set(names) != {"p1", "p2"}:
        return None
    w = _WIN.findall(log)
    winner = 0
    if w:
        wid = to_id(w[-1])
        winner = 1 if wid == to_id(names["p1"]) else 2 if wid == to_id(names["p2"]) else 0
    turns = _TURN.findall(log)
    return {
        "p1": to_id(names["p1"]), "p2": to_id(names["p2"]),
        "r1": ratings["p1"], "r2": ratings["p2"],
        "team1": "|".join(sorted(teams["p1"])), "team2": "|".join(sorted(teams["p2"])),
        "winner": winner, "turns": int(turns[-1]) if turns else 0,
    }  # fmt: skip


def _shard(path: str) -> list[dict]:
    t = pq.read_table(path, columns=["id", "log", "uploadtime"])
    out = []
    for gid, log, ts in zip(*(t.column(c).to_pylist() for c in ("id", "log", "uploadtime")),
                            strict=True):  # fmt: skip
        r = scan(log)
        if r is not None:
            out.append({"id": gid, "time": int(ts)} | r)
    return out


def build(workers: int = 8) -> pa.Table:
    files = sorted(glob.glob(SRC))
    with ProcessPoolExecutor(workers) as ex:
        rows = [r for part in ex.map(_shard, files) for r in part]
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, DEST)
    return table


if __name__ == "__main__":
    import time

    t0 = time.time()
    tb = build()
    print(f"{tb.num_rows} games -> {DEST} ({time.time() - t0:.0f}s)")
