"""The review pages' local server (2026-10-29): the replay player's files without the official
site at viewing time.

  /coach/<review>/viewer.html   the review pages (data/coach)
  /config/config.js             our minimal client config: every resource from this server
  anything else under CLIENT_PATHS   Showdown's built client (scripts, styles, data, sprites,
                                fx, audio), from the local cache data/coach/client/ -- fetched once
                                from play.pokemonshowdown.com on first use, then never again
                                (the cache is our pinned copy; refresh=True fetches anew; offline=True
                                never fetches)

Showdown's client is AGPL-3.0: it is fetched and served unmodified, for local viewing only, and
never committed (data/ is git-ignored); our page only loads it in the browser.
"""

import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

from alpha_poke import paths

UPSTREAM = "https://play.pokemonshowdown.com/"
CLIENT_PATHS = ("js/", "style/", "data/", "sprites/", "fx/", "audio/", "fonts/", "images/")
USER_AGENT = "alpha-poke-review-viewer (local cache of the replay player; one fetch per file)"
CONFIG = """var Config = Config || {};
Config.routes = {root: location.host, client: location.host, dex: 'dex.pokemonshowdown.com',
  replays: 'replay.pokemonshowdown.com', users: 'pokemonshowdown.com/users', teams: 'teams.pokemonshowdown.com'};
Config.server = {id: 'showdown', host: location.hostname, port: Number(location.port) || 80};
Config.customcolors = {};
Config.whitelist = [];
Config.testclient = false;
"""


class Cache:
    """Showdown's client files on disk, each fetched at most once (one fetch at a time)."""

    def __init__(self, root: Path, offline: bool = False, refresh: bool = False):
        self.root, self.offline, self.refresh = Path(root), offline, refresh
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.fetched: set[str] = set()

    def get(self, rel: str) -> Path | None:
        """The local copy of ``rel`` (a client path), fetched if missing; None if unavailable."""
        if not rel.startswith(CLIENT_PATHS) or ".." in Path(rel).parts:
            return None
        path = self.root / rel
        stale = self.refresh and rel not in self.fetched
        if path.exists() and not stale:
            return path
        if self.offline:
            return path if path.exists() else None
        with self.lock:
            if path.exists() and (not self.refresh or rel in self.fetched):
                return path
            r = self.session.get(UPSTREAM + rel, timeout=30)
            self.fetched.add(rel)
            if r.status_code != 200:
                return path if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(r.content)
            tmp.replace(path)
        return path


def handler(cache: Cache, pages: Path):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            rel = unquote(urlsplit(self.path).path).lstrip("/")
            if rel == "config/config.js":
                return self._send(CONFIG.encode(), "application/javascript")
            if rel.startswith("coach/"):
                path = pages / rel.removeprefix("coach/")
                if ".." in Path(rel).parts or not path.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
            else:
                path = cache.get(rel)
                if path is None:
                    return self.send_error(HTTPStatus.NOT_FOUND)
            return self._send(path.read_bytes(), self.guess_type(str(path)))

    return Handler


def serve(port: int = 8090, offline: bool = False, refresh: bool = False) -> ThreadingHTTPServer:
    """The server (loopback only); ``serve_forever()`` it."""
    cache = Cache(paths.DATA / "coach" / "client", offline, refresh)
    return ThreadingHTTPServer(("127.0.0.1", port), handler(cache, paths.DATA / "coach"))


def running(port: int) -> bool:
    """Whether our server already answers on ``port``."""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/config/config.js", timeout=2)
    except requests.RequestException:
        return False
    return r.status_code == 200 and "Config.routes" in r.text


def open_page(url: str) -> None:
    """``url`` in the desktop's browser (WSL: Windows' default browser, which reaches the server
    through WSL's localhost forwarding)."""
    import shutil
    import subprocess
    import webbrowser

    wsl = (
        "microsoft" in Path("/proc/version").read_text().lower()
        if Path("/proc/version").exists()
        else False
    )
    if wsl and shutil.which("explorer.exe"):
        subprocess.run(["explorer.exe", url], check=False)  # (its exit status is 1 on success)
    else:
        webbrowser.open(url)
