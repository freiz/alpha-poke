"""Resumable replay crawler with a SQLite metadata index.

Phases (all idempotent, all resumable; state lives in ``index.sqlite``):

  seed_top_users   ladder JSON (pokemonshowdown.com/ladder/<fmt>.json, top 500) -> ``users``
  crawl_users      latest 25 replays of each seeded user (the API gives no more) -> ``replays``
  walk_listing     global listing, 51 entries per request, newest first; ``back`` pages further
                   into the past from the stored cursor, ``new`` fetches what is newer than
                   anything seen so far (use it to keep the dataset fresh)
  download         fetch full logs for pending replays that pass the filters; gzip to disk

Listing requests carry 25-51 replays' metadata each, so the index can be built cheaply; the
expensive part is one request per replay log. Everything goes through ``PoliteClient``.
"""

import signal
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from alpha_poke.http import CrawlAbort
from alpha_poke.replay.fetch import BASE as REPLAY_BASE
from alpha_poke.replay.fetch import DEFAULT_CACHE, ReplayClient

LADDER_URL = "https://pokemonshowdown.com/ladder/{fmt}.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS replays(
  id TEXT PRIMARY KEY, format_id TEXT NOT NULL, format_name TEXT, uploadtime INTEGER NOT NULL,
  p1 TEXT, p2 TEXT, rating INTEGER, private INTEGER, source TEXT, discovered_at INTEGER,
  status TEXT NOT NULL DEFAULT 'pending', fetched_at INTEGER, bytes INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS idx_replays_queue ON replays(status, private, uploadtime);
CREATE TABLE IF NOT EXISTS users(
  userid TEXT PRIMARY KEY, username TEXT, source TEXT, rank INTEGER, elo REAL, gxe REAL,
  crawled_at INTEGER, n_listed INTEGER);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass
class Budget:
    """Stop conditions shared by every phase (the crawl can always be resumed later)."""

    max_requests: int | None = None
    max_seconds: float | None = None
    started: float = field(default_factory=time.monotonic)
    stop_requested: bool = False

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            print(
                f"\n[signal {signum}] finishing the current request, then stopping...", flush=True
            )
            self.stop_requested = True

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def exhausted(self, requests_made: int) -> bool:
        if self.stop_requested:
            return True
        if self.max_requests is not None and requests_made >= self.max_requests:
            return True
        return self.max_seconds is not None and time.monotonic() - self.started >= self.max_seconds


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


class ReplayCrawler:
    def __init__(
        self,
        root: Path | str = DEFAULT_CACHE,
        format_id: str = "gen9ou",
        min_interval: float = 2.0,
        budget: Budget | None = None,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.format_id = format_id
        self.client = ReplayClient(cache_dir=self.root, min_interval=min_interval)
        self.budget = budget or Budget()
        self.db = sqlite3.connect(self.root / "index.sqlite")
        self.db.executescript(SCHEMA)

    # ---- helpers --------------------------------------------------------------------
    def _meta(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def _set_meta(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, str(value)))
        self.db.commit()

    def _stop(self) -> bool:
        return self.budget.exhausted(self.client.http.requests_made)

    def upsert(self, entries: list[dict], source: str) -> int:
        """Insert listing entries; returns how many were new."""
        now = int(time.time())
        new = 0
        for e in entries:
            players = e.get("players") or [None, None]
            cur = self.db.execute(
                "INSERT OR IGNORE INTO replays(id, format_id, format_name, uploadtime, p1, p2,"
                " rating, private, source, discovered_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    e["id"],
                    e["id"].rsplit("-", 1)[0],
                    e.get("format"),
                    e["uploadtime"],
                    players[0],
                    players[1] if len(players) > 1 else None,
                    e.get("rating"),
                    int(bool(e.get("private"))),
                    source,
                    now,
                ),
            )
            new += cur.rowcount
        self.db.commit()
        return new

    # ---- phase 1: top users -----------------------------------------------------------
    def seed_top_users(self, top_n: int = 500) -> int:
        r = self.client.http.get(LADDER_URL.format(fmt=self.format_id))
        top = r.json()["toplist"][:top_n]
        for i, u in enumerate(top, 1):
            self.db.execute(
                "INSERT OR IGNORE INTO users(userid, username, source, rank, elo, gxe)"
                " VALUES (?,?,?,?,?,?)",
                (u["userid"], u["username"], "ladder_top", i, u.get("elo"), u.get("gxe")),
            )
        self.db.commit()
        log(f"seeded {len(top)} top users from the {self.format_id} ladder")
        return len(top)

    def crawl_users(self, max_users: int | None = None) -> None:
        rows = self.db.execute(
            "SELECT userid FROM users WHERE crawled_at IS NULL ORDER BY rank LIMIT ?",
            (max_users if max_users is not None else -1,),
        ).fetchall()
        for i, (uid,) in enumerate(rows, 1):
            if self._stop():
                break
            entries = self.client.search(self.format_id, user=uid)
            new = self.upsert(entries, source="user")
            self.db.execute(
                "UPDATE users SET crawled_at=?, n_listed=? WHERE userid=?",
                (int(time.time()), len(entries), uid),
            )
            self.db.commit()
            if i % 25 == 0 or i == len(rows):
                log(f"users {i}/{len(rows)}  last: {len(entries)} listed, {new} new")

    def expand_users_from_replays(self, min_rating: int, limit: int = 200) -> int:
        """Add opponents seen in high-rated replays as new users to crawl (snowballing)."""
        rows = self.db.execute(
            "SELECT p1, p2 FROM replays WHERE rating >= ? ORDER BY uploadtime DESC LIMIT 20000",
            (min_rating,),
        ).fetchall()
        added = 0
        for name in {n for pair in rows for n in pair if n}:
            uid = "".join(c for c in name.lower() if c.isalnum())
            if not uid:
                continue
            cur = self.db.execute(
                "INSERT OR IGNORE INTO users(userid, username, source, rank) VALUES (?,?,?,100000)",
                (uid, name, "expanded"),
            )
            added += cur.rowcount
            if added >= limit:
                break
        self.db.commit()
        log(f"added {added} new users from replays rated >= {min_rating}")
        return added

    # ---- phase 2: global listing --------------------------------------------------------
    def walk_listing(self, mode: str = "back", max_pages: int = 100, since_ts: int | None = None):
        """``back``: continue into the past from the stored cursor; ``new``: fetch newer entries."""
        assert mode in ("back", "new")
        newest_seen = int(self._meta("list_newest", "0"))
        before = None
        if mode == "back" and self._meta("list_cursor"):
            before = int(self._meta("list_cursor")) + 1  # +1: overlap one second, dedup by id
        pages = total_new = 0
        while pages < max_pages and not self._stop():
            page = self.client.search(self.format_id, before=before)
            pages += 1
            if not page:
                break
            total_new += self.upsert(page, source="listing")
            oldest, newest = page[-1]["uploadtime"], page[0]["uploadtime"]
            if mode == "back":
                self._set_meta("list_cursor", oldest)
            if newest > newest_seen:
                newest_seen = newest
                self._set_meta("list_newest", newest)
            if pages % 20 == 0:
                when = time.strftime("%F %T", time.gmtime(oldest))
                log(f"listing[{mode}] page {pages}: oldest={when} new so far {total_new}")
            if since_ts is not None and oldest <= since_ts:
                break
            if mode == "new" and oldest <= int(self._meta("list_prev_newest", "0")):
                break
            if len(page) < 51:
                break
            before = oldest + 1
        if mode == "new":
            self._set_meta("list_prev_newest", newest_seen)
        log(f"listing[{mode}] done: {pages} pages, {total_new} new entries")

    # ---- phase 3: download --------------------------------------------------------------
    def download(
        self,
        target: int,
        min_rating: int | None = None,
        since_ts: int | None = None,
        order: str = "recent",
    ) -> None:
        """Fetch full logs until ``target`` replays are on disk (counting earlier runs)."""
        order_sql = "uploadtime DESC" if order == "recent" else "rating DESC, uploadtime DESC"
        where = "status='pending' AND private=0"
        args: list = []
        if min_rating is not None:
            where += " AND rating >= ?"
            args.append(min_rating)
        if since_ts is not None:
            where += " AND uploadtime >= ?"
            args.append(since_ts)
        done = self.db.execute("SELECT COUNT(*) FROM replays WHERE status='done'").fetchone()[0]
        log(f"download: {done} already done, target {target}")
        while done < target and not self._stop():
            rows = self.db.execute(
                f"SELECT id, format_id FROM replays WHERE {where} ORDER BY {order_sql} LIMIT 200",
                args,
            ).fetchall()
            if not rows:
                log("download: nothing pending that matches the filters")
                return
            for rid, fid in rows:
                if done >= target or self._stop():
                    break
                self._download_one(rid, fid)
                done = self.db.execute(
                    "SELECT COUNT(*) FROM replays WHERE status='done'"
                ).fetchone()[0]
                if done % 100 == 0:
                    log(f"download: {done}/{target} done")
        log(f"download stopped at {done}/{target}")

    def _download_one(self, rid: str, fid: str) -> None:
        try:
            self.client.get(rid, format_id=fid)
        except CrawlAbort:
            raise
        except requests.HTTPError as e:
            status = (
                "missing" if e.response is not None and e.response.status_code == 404 else "error"
            )
            self.db.execute(
                "UPDATE replays SET status=?, error=? WHERE id=?", (status, str(e), rid)
            )
            self.db.commit()
            return
        except ValueError as e:  # bad JSON
            self.db.execute("UPDATE replays SET status='error', error=? WHERE id=?", (str(e), rid))
            self.db.commit()
            return
        size = self.client.path_for(fid, rid).stat().st_size
        self.db.execute(
            "UPDATE replays SET status='done', fetched_at=?, bytes=? WHERE id=?",
            (int(time.time()), size, rid),
        )
        self.db.commit()

    # ---- reporting ----------------------------------------------------------------------
    def status(self) -> str:
        q = self.db.execute
        lines = [f"index: {self.root / 'index.sqlite'}  base={REPLAY_BASE}"]
        for status, n, b in q(
            "SELECT status, COUNT(*), COALESCE(SUM(bytes),0) FROM replays GROUP BY status"
        ):
            lines.append(f"  {status:8s} {n:8d}  {b / 1e6:8.1f} MB")
        lo, hi = q("SELECT MIN(uploadtime), MAX(uploadtime) FROM replays").fetchone()
        if lo:
            fmt = lambda t: time.strftime("%F %T", time.gmtime(t))  # noqa: E731
            lines.append(f"  uploadtime range: {fmt(lo)} .. {fmt(hi)} (UTC)")
        lines.append(
            "  rating buckets (all indexed): "
            + ", ".join(
                f"{lo_}+: {n}"
                for lo_, n in [
                    (b, q("SELECT COUNT(*) FROM replays WHERE rating >= ?", (b,)).fetchone()[0])
                    for b in (1000, 1300, 1500, 1600, 1700, 1800)
                ]
            )
        )
        u = q("SELECT COUNT(*), SUM(crawled_at IS NOT NULL) FROM users").fetchone()
        lines.append(f"  users: {u[0]} known, {u[1] or 0} crawled")
        lines.append(
            f"  list cursor: {self._meta('list_cursor')}  newest seen: {self._meta('list_newest')}"
        )
        return "\n".join(lines)
