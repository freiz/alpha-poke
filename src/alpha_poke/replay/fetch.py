"""Polite, cached client for the public Showdown replay endpoints (read-only HTTP).

Endpoints (see https://github.com/smogon/pokemon-showdown-client/blob/master/WEB-API.md):
  search.json?format=gen9ou[&before=<uploadtime>][&user=..]   max 51 results per request
  <id>.json                                                     full spectator log

No rate limit is documented, so the client stays at one request per ``min_interval`` seconds,
backs off on 429/5xx, and caches every replay on disk so nothing is downloaded twice.
"""

import json
import time
from collections.abc import Iterator
from pathlib import Path

import requests

BASE = "https://replay.pokemonshowdown.com"
DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "data" / "replays"
USER_AGENT = "alpha-poke research (personal project, low request rate)"


class ReplayClient:
    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE, min_interval: float = 1.0):
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self._last = 0.0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        for attempt in range(5):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self._session.get(url, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                retry = float(r.headers.get("Retry-After", 0)) or 2.0 * 2**attempt
                time.sleep(retry)
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()
        return r

    def search(
        self, format_id: str, before: int | None = None, user: str | None = None
    ) -> list[dict]:
        """One page (<= 51 entries, newest first) of replay metadata."""
        params: dict = {"format": format_id}
        if before is not None:
            params["before"] = before
        if user:
            params["user"] = user
        return self._get(f"{BASE}/search.json", params).json()

    def iter_search(
        self, format_id: str, max_pages: int = 3, before: int | None = None
    ) -> Iterator[dict]:
        """Walk back in time page by page, yielding replay metadata entries."""
        for _ in range(max_pages):
            page = self.search(format_id, before=before)
            yield from page
            if len(page) < 51:
                return
            before = page[-1]["uploadtime"]

    def path_for(self, format_id: str, replay_id: str) -> Path:
        return self.cache_dir / format_id / f"{replay_id}.json"

    def get(self, replay_id: str, format_id: str | None = None) -> dict:
        """Return the replay JSON (``log``, ``players``, ``rating``, ...), using the disk cache."""
        format_id = format_id or replay_id.rsplit("-", 1)[0]
        path = self.path_for(format_id, replay_id)
        if path.exists():
            return json.loads(path.read_text())
        data = self._get(f"{BASE}/{replay_id}.json").json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return data
