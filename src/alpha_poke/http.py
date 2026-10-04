"""A deliberately slow, polite HTTP client shared by all scrapers.

* one request at a time, at least ``min_interval`` seconds apart (+ random jitter);
* honours ``Retry-After`` and backs off exponentially on 429 / 5xx;
* aborts the whole crawl (``CrawlAbort``) after several consecutive failures or on 403,
  instead of hammering a site that is asking us to go away;
* identifies itself, without any personal contact information.
"""

import random
import time

import requests

USER_AGENT = "alpha-poke-research (personal, non-commercial; ~1 request per 2s)"


class CrawlAbort(RuntimeError):
    """Raised when the server tells us to stop (403) or keeps failing."""


class PoliteClient:
    def __init__(
        self,
        min_interval: float = 2.0,
        jitter: float = 0.25,
        max_consecutive_failures: int = 5,
        timeout: float = 30.0,
    ):
        self.min_interval = min_interval
        self.jitter = jitter
        self.max_consecutive_failures = max_consecutive_failures
        self.timeout = timeout
        self.requests_made = 0
        self._last = 0.0
        self._failures = 0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def _sleep_until_allowed(self) -> None:
        gap = self.min_interval * (1 + random.uniform(0, self.jitter))
        wait = gap - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        for attempt in range(6):
            self._sleep_until_allowed()
            self._last = time.monotonic()
            self.requests_made += 1
            try:
                r = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException:
                r = None
            if r is not None and r.status_code == 403:
                raise CrawlAbort(f"403 Forbidden from {url}; stopping")
            if r is not None and r.status_code == 404:
                r.raise_for_status()
            if r is not None and r.status_code < 400:
                self._failures = 0
                return r
            self._failures += 1
            if self._failures >= self.max_consecutive_failures:
                raise CrawlAbort(f"{self._failures} consecutive failures on {url}; stopping")
            retry = 0.0
            if r is not None:
                retry = float(r.headers.get("Retry-After", 0) or 0)
            time.sleep(min(max(retry, 5.0 * 2**attempt), 600.0))
        raise CrawlAbort(f"giving up on {url} after repeated errors")
