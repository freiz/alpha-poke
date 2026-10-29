"""Cached client for the public Showdown replay endpoints (read-only HTTP).

Endpoints (see https://github.com/smogon/pokemon-showdown-client/blob/master/WEB-API.md):
  search.json?format=gen9ou[&before=<uploadtime>]   max 51 entries per request, newest first,
                                                      can be paged back with ``before``
  search.json?format=gen9ou&user=<name>             only the latest 25 entries, no paging
  <id>.json                                         full spectator log

replay.pokemonshowdown.com has no robots.txt and documents no rate limit, so requests go
through ``PoliteClient`` (slow, jittered, backs off, aborts on 403 / repeated failures).
Replays are cached on disk as ``<cache>/<format>/<id>.json.gz``.
"""

import gzip
import json
from pathlib import Path

from alpha_poke import paths
from alpha_poke.http import PoliteClient

BASE = "https://replay.pokemonshowdown.com"
DEFAULT_CACHE = paths.REPLAYS


class ReplayClient:
    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE, min_interval: float = 2.0):
        self.cache_dir = Path(cache_dir)
        self.http = PoliteClient(min_interval=min_interval)

    # ---- listings -------------------------------------------------------------------
    def search(
        self, format_id: str, before: int | None = None, user: str | None = None
    ) -> list[dict]:
        """One page of replay metadata, newest first (51 entries; 25 when ``user`` is given)."""
        params: dict = {"format": format_id}
        if before is not None:
            params["before"] = before
        if user:
            params["user"] = user
        return self.http.get(f"{BASE}/search.json", params).json()


    # ---- full replays ---------------------------------------------------------------
    def path_for(self, format_id: str, replay_id: str) -> Path:
        return self.cache_dir / format_id / f"{replay_id}.json.gz"

    def load_cached(self, replay_id: str, format_id: str | None = None) -> dict | None:
        format_id = format_id or replay_id.rsplit("-", 1)[0]
        gz = self.path_for(format_id, replay_id)
        if gz.exists():
            with gzip.open(gz, "rt", encoding="utf-8") as f:
                return json.load(f)
        plain = gz.with_suffix("")  # legacy uncompressed cache
        if plain.exists():
            return json.loads(plain.read_text())
        return None

    def get(self, replay_id: str, format_id: str | None = None) -> dict:
        """Return the replay JSON (``log``, ``players``, ``rating``, ...), using the disk cache."""
        cached = self.load_cached(replay_id, format_id)
        if cached is not None:
            return cached
        format_id = format_id or replay_id.rsplit("-", 1)[0]
        data = self.http.get(f"{BASE}/{replay_id}.json").json()
        path = self.path_for(format_id, replay_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.rename(path)
        return data
