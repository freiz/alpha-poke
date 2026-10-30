"""The reviews' index, data/coach/reviews.sqlite (2026-10-30): one row per saved review -- the
players (the reviewed one first: the left / bottom-left of its page), when the game was played
and reviewed, both teams, the result, the scorecard, the settings -- for the home page's list
(searched, sorted and paged in SQL), plus the person's own name and note for it.

The reviews' files stay the record (review.json, replay.json, ...): their rows are made from
them and made again when a review changes (``sync``: a review.json newer than its row, a review
not indexed yet; a row whose review is gone, dropped). The name and the note live only here, kept
through every re-index."""

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB = "reviews.sqlite"
SCHEMA = """CREATE TABLE IF NOT EXISTS reviews (
  dir TEXT PRIMARY KEY, id TEXT NOT NULL, side TEXT NOT NULL, player TEXT, opponent TEXT,
  won INTEGER, turns INTEGER, played INTEGER, reviewed INTEGER NOT NULL,
  team_me TEXT, team_opp TEXT, repeats INTEGER, ms INTEGER, worlds INTEGER, team INTEGER,
  decisions INTEGER, top1 REAL, top2 REAL, mean_loss REAL, bad INTEGER, mild INTEGER,
  title TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '')"""
# the list's sort keys -> their SQL (a name not given: the players)
SORTS = {
    "reviewed": "reviewed", "played": "played", "won": "won", "turns": "turns", "top1": "top1",
    "top2": "top2", "mean_loss": "mean_loss", "bad": "bad",
    "title": "lower(coalesce(nullif(title, ''), player || ' vs ' || opponent))",
}  # fmt: skip
FIELDS = ("id", "side", "player", "opponent", "won", "turns", "played", "reviewed", "team_me",
          "team_opp", "repeats", "ms", "worlds", "team", "decisions", "top1", "top2", "mean_loss",
          "bad", "mild")  # fmt: skip


def connect(root: Path) -> sqlite3.Connection:
    """A connection to ``root``'s index (one per request: the app's threads each their own)."""
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


@contextmanager
def db(root: Path):
    """``connect`` for one use: committed (rolled back on an error) and closed."""
    con = connect(root)
    try:
        with con:
            yield con
    finally:
        con.close()


def played_at(row: dict) -> int | None:
    """When the game was played (unix time): the log's first timestamp, else the replay's upload
    time; None when the replay has neither (our own saved battles)."""
    m = re.search(r"^\|t:\|(\d+)", row["log"], re.M)
    return int(m.group(1)) if m else (int(row.get("uploadtime") or 0) or None)


def record(rep: dict, row: dict, has_team: bool, reviewed: int) -> dict:
    """A review's row (without the person's name and note)."""
    from alpha_poke.coach.review import metrics

    side = rep["side"]
    other = "p2" if side == "p1" else "p1"
    m, s = metrics(rep), rep["settings"]
    team = lambda x: json.dumps([t["species"].replace("-*", "") for t in rep["teams"][x]])  # noqa: E731
    return {"id": rep["id"], "side": side, "player": row["players"][int(side[1]) - 1],
            "opponent": row["players"][int(other[1]) - 1], "won": int(rep["winner"] == side),
            "turns": rep["turns"], "played": played_at(row), "reviewed": reviewed,
            "team_me": team(side), "team_opp": team(other), "repeats": s.get("repeats", 1),
            "ms": s["ms"], "worlds": s["worlds"], "team": int(has_team), "decisions": m["decisions"],
            "top1": m["top1"], "top2": m["top2"], "mean_loss": m["mean_loss"], "bad": m["bad"],
            "mild": m["mild"]}  # fmt: skip


def put(con: sqlite3.Connection, name: str, rec: dict) -> None:
    """Index review ``name`` (its name and note, if it had them, kept)."""
    cols = ", ".join(FIELDS)
    con.execute(
        f"INSERT INTO reviews (dir, {cols}) VALUES (?, {', '.join('?' * len(FIELDS))}) "
        f"ON CONFLICT(dir) DO UPDATE SET {', '.join(f'{f} = excluded.{f}' for f in FIELDS)}",
        [name, *(rec[f] for f in FIELDS)],
    )


def sync(root: Path, load) -> None:
    """Bring the index up to the reviews in ``root``: each review.json not indexed or newer than
    its row indexed again (``load(name)`` -> (report, replay, team): coach.app.stored); rows of
    reviews no longer there dropped. One that cannot be read is left out."""
    with db(root) as con:
        have = {r["dir"]: r["reviewed"] for r in con.execute("SELECT dir, reviewed FROM reviews")}
        seen = set()
        for f in root.glob("*/review.json"):
            name, mtime = f.parent.name, int(f.stat().st_mtime)
            seen.add(name)
            if have.get(name) == mtime:
                continue
            try:
                rep, row, team = load(name)
                put(con, name, record(rep, row, team is not None, mtime))
            except Exception:  # noqa: BLE001 - a broken review is not listed
                seen.discard(name)
        gone = [n for n in have if n not in seen]
        con.executemany("DELETE FROM reviews WHERE dir = ?", [(n,) for n in gone])


def query(root: Path, q: str = "", sort: str = "reviewed", desc: bool = True, page: int = 1,
          size: int = 20) -> dict:  # fmt: skip
    """One page of the list: {total, page, size, rows}; ``q`` matches the name, the note, the
    players, the id and the teams' Pokemon (case-insensitive); unknown values (a game's time)
    last whichever the order."""
    key = SORTS.get(sort, "reviewed")
    size = max(1, min(int(size), 200))
    where, args = "", []
    if q.strip():
        like = f"%{q.strip().lower()}%"
        fields = ("title", "note", "player", "opponent", "id", "team_me", "team_opp")
        where = "WHERE " + " OR ".join(f"lower({f}) LIKE ?" for f in fields)
        args = [like] * len(fields)
    with db(root) as con:
        total = con.execute(f"SELECT count(*) FROM reviews {where}", args).fetchone()[0]
        pages = max(1, -(-total // size))
        page = max(1, min(int(page), pages))
        rows = con.execute(
            f"SELECT * FROM reviews {where} ORDER BY {key} IS NULL, {key} {'DESC' if desc else 'ASC'}, "
            f"reviewed DESC LIMIT ? OFFSET ?",
            [*args, size, (page - 1) * size],
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["teams"] = [json.loads(d.pop("team_me") or "[]"), json.loads(d.pop("team_opp") or "[]")]
        d["won"], d["team"] = bool(d["won"]), bool(d["team"])
        d["url"] = f"/coach/{d['dir']}/viewer.html"
        out.append(d)
    return {"total": total, "page": page, "size": size, "pages": pages, "rows": out}


def set_meta(root: Path, name: str, title: str, note: str) -> bool:
    """Rename review ``name`` / note on it (its id and link stay); False: not indexed."""
    with db(root) as con:
        n = con.execute("UPDATE reviews SET title = ?, note = ? WHERE dir = ?",
                        (title.strip()[:120], note.strip()[:2000], name)).rowcount  # fmt: skip
    return n > 0


def title_of(root: Path, name: str) -> str:
    """The name the person gave review ``name`` ("" if none)."""
    with db(root) as con:
        r = con.execute("SELECT title FROM reviews WHERE dir = ?", (name,)).fetchone()
    return r["title"] if r else ""
