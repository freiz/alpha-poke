"""Smogon forum crawler: finds teams (pokepast.es links and inline Showdown exports) in the
threads of ``SOURCES``. Pages are cached under ``raw/smogon``; requests are sequential with a
delay (public site, be polite). Extraction works on the cache only, so it is repeatable."""

import html
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from alpha_poke.teams import RAW_DIR

BASE = "https://www.smogon.com/forums"
USER_AGENT = "alpha-poke-research/0.1 (offline team collection for a game-AI project)"
DELAY = 1.0  # seconds between requests

# name -> where to look. "threads": thread ids, every post of every page; "forum": a forum's
# threads, the first post only (Rate My Team: the opening post is the team, replies are
# suggestions) -- with "all_posts", every post of every thread (discussion forums: teams are
# posted in replies). The name is kept on every team found (catalog sources). Teams of other
# generations and tiers there are dropped when the catalog is built (the gen9ou validator).
SOURCES: dict[str, dict] = {
    "sample": {"threads": [3712513]},  # SV OU Sample Teams (council-picked)
    "teams_of_week": {"threads": [3712009]},  # SV OU Teams of the Week
    "tour_bazaar": {"threads": [3752863]},  # SV OU Tournament Team's Bazaar
    "rmt": {"forum": "sv-ou-teams.748"},  # Rate My Team > SV OU Teams
    # (2026-10-31: more teams, the ones people post in discussions and tournaments)
    "ou_forum": {"forum": "overused.726", "all_posts": True},  # Gen 9 OU (metagame discussion)
    "ou_archive": {"forum": "gen-9-ou-archive.841", "all_posts": True},
    "spl": {"forum": "smogon-premier-league.130", "all_posts": True},
    "scl": {"forum": "smogon-classic.334", "all_posts": True},
}

PASTE_RE = re.compile(r"pokepast\.es/([0-9a-f]{16})\b")
THREAD_RE = re.compile(
    r'<a href="/forums/threads/([^"/]*?\.)?(\d+)/"[^>]*data-tp-primary[^>]*>(.*?)</a>', re.S
)
ATTR_RE = re.compile(
    r"^(Ability|Level|Shiny|Tera Type|EVs|IVs|Happiness|Gigantamax|Dynamax Level|Hidden Power)"
    r"\s*:|^[A-Z][a-z]+ Nature\s*$"
)


@dataclass
class Found:
    """One team found in one post."""

    source: str
    thread: int
    thread_title: str
    post: int
    author: str
    date: str  # ISO, the post's
    paste: str | None = None  # pokepast.es id, or
    text: str | None = None  # an inline export

    def row(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class Fetcher:
    def __init__(self, refresh: bool = False, delay: float = DELAY):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.refresh, self.delay, self._last = refresh, delay, 0.0
        self.requests = 0
        self.blocked = 0  # pages not read: the site's browser check (see ``gated``)

    def get(self, url: str, cache: Path, refresh: bool = False) -> str | None:
        """The page (cached); None if it does not exist."""
        if cache.exists() and not (refresh and self.refresh):
            text = cache.read_text(encoding="utf-8")
            if not gated(text):
                return text or None
        if self.blocked:  # (checked once: no more requests to a site that turns bots away)
            self.blocked += 1
            return None
        time.sleep(max(0.0, self._last + self.delay - time.time()))
        r = self.session.get(url, timeout=60)
        self._last = time.time()
        self.requests += 1
        cache.parent.mkdir(parents=True, exist_ok=True)
        if r.status_code == 404:
            cache.write_text("", encoding="utf-8")
            return None
        r.raise_for_status()
        if gated(r.text):  # (not cached: it is not the page)
            self.blocked += 1
            return None
        cache.write_text(r.text, encoding="utf-8")
        return r.text


def gated(page: str) -> bool:
    """Smogon's browser check (since 2026-10-31, on thread pages): a JavaScript proof-of-work
    page instead of the thread. Not solved here -- the site turns crawlers away."""
    return "xf_smogon_gate" in page[:4000]


def _last_page(page: str, prefix: str) -> int:
    """The highest page number linked from ``page``; ``prefix``: regex of the URL before
    'page-N'."""
    pages = [int(p) for p in re.findall(prefix + r"page-(\d+)", page)]
    return max(pages, default=1)


def forum_threads(f: Fetcher, forum: str) -> list[tuple[int, str]]:
    """(thread id, title) of every thread listed in a forum (stickies included)."""
    cache = RAW_DIR / "smogon" / f"forum-{forum}"
    first = f.get(f"{BASE}/forums/{forum}/", cache / "page-1.html", refresh=True)
    out: dict[int, str] = {}
    for n in range(1, _last_page(first or "", re.escape(f"/forums/{forum}/")) + 1):
        url = f"{BASE}/forums/{forum}/page-{n}"
        page = first if n == 1 else f.get(url, cache / f"page-{n}.html", refresh=True)
        for _, tid, title in THREAD_RE.findall(page or ""):
            out.setdefault(int(tid), html.unescape(re.sub(r"<[^>]+>", "", title)).strip())
    return list(out.items())


def thread_pages(f: Fetcher, thread: int, first_only: bool = False) -> list[str]:
    cache = RAW_DIR / "smogon" / str(thread)
    first = f.get(f"{BASE}/threads/{thread}/", cache / "page-1.html")
    if first is None:
        return []
    n = 1 if first_only else _last_page(first, rf"/threads/(?:[^\"/]*\.)?{thread}/")
    pages = [first]
    for k in range(2, n + 1):
        # the last page may have grown since it was cached
        url = f"{BASE}/threads/{thread}/page-{k}"
        page = f.get(url, cache / f"page-{k}.html", refresh=k == n)
        if page:
            pages.append(page)
    return pages


def thread_title(page: str) -> str:
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    title = html.unescape(m.group(1)) if m else ""
    return re.sub(r"\s*\|\s*Smogon Forums\s*$", "", title).strip()


def posts(page: str) -> list[dict]:
    """The posts of a thread page: {post, author, date, body (html, signature removed)}."""
    out = []
    for chunk in re.split(r'(?=<article class="message message--post)', page)[1:]:
        pid = re.search(r'data-content="post-(\d+)"', chunk)
        if pid is None:
            continue
        author = re.search(r'data-author="([^"]*)"', chunk)
        date = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
        body = chunk.split('<aside class="message-signature')[0]
        m = re.search(r'<div class="bbWrapper">', body)
        out.append({
            "post": int(pid.group(1)),
            "author": html.unescape(author.group(1)) if author else "",
            "date": date.group(1) if date else "",
            "body": body[m.start():] if m else "",
        })  # fmt: skip
    return out


def body_text(body: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", body)
    text = re.sub(r"</(div|p|li|pre|code|blockquote)>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")


def inline_teams(text: str) -> list[str]:
    """The team written into a post as Showdown export (a set: a header line, attribute lines
    incl. Ability / EVs / Tera Type, 1-4 '- move' lines; blank lines ignored). Rate My Team
    posts interleave the sets with commentary and often end with the full importable:
      * the last run of exactly 6 sets with nothing in between (the importable), else
      * the first set of each species if the post has exactly 6 species, else nothing
        (set dumps, several teams, partial teams)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    sets: list[tuple[int, int]] = []  # (first line, last line) of each set
    i = 0
    while i < len(lines):
        j = i + 1
        attrs = moves = 0
        while j < len(lines) and ATTR_RE.search(lines[j]):
            attrs += 1
            j += 1
        while j < len(lines) and re.match(r"^[-~]\s+\S", lines[j]):
            moves += 1
            j += 1
        head = lines[i]
        if attrs and 1 <= moves <= 4 and len(head) < 80 and not ATTR_RE.search(head):
            sets.append((i, j - 1))
            i = j
        else:
            i += 1

    def text_of(run: list[tuple[int, int]]) -> str:
        return "\n\n".join("\n".join(lines[a : b + 1]) for a, b in run)

    runs: list[list[tuple[int, int]]] = []
    for s in sets:
        if runs and runs[-1][-1][1] + 1 == s[0]:
            runs[-1].append(s)
        else:
            runs.append([s])
    pure = [r for r in runs if len(r) == 6]
    if pure:
        return [text_of(pure[-1])]
    first: dict[str, tuple[int, int]] = {}
    for s in sets:
        first.setdefault(_species_of(lines[s[0]]), s)
    return [text_of(list(first.values()))] if len(first) == 6 else []


def _species_of(header: str) -> str:
    """'Nickname (Species) (M) @ Item' -> 'species'."""
    name = re.sub(r"\((M|F)\)", "", header.split(" @ ")[0]).strip()
    m = re.search(r"\(([^()]+)\)\s*$", name)
    return re.sub(r"[^a-z0-9]", "", (m.group(1) if m else name).lower())


def crawl(f: Fetcher, sources: dict[str, dict] = SOURCES, log=print) -> list[Found]:
    """Download (or read from the cache) every source; every team found, in source order."""
    found: list[Found] = []
    for name, spec in sources.items():
        threads = [(t, "") for t in spec.get("threads", [])]
        first_only = "forum" in spec and not spec.get("all_posts")
        if "forum" in spec:
            threads = forum_threads(f, spec["forum"])
        n0 = len(found)
        for k, (tid, title) in enumerate(threads):
            pages = thread_pages(f, tid, first_only)
            if not pages:
                continue
            title = title or thread_title(pages[0])
            ps = [p for page in pages for p in posts(page)]
            for p in ps[:1] if first_only else ps:
                meta = dict(source=name, thread=tid, thread_title=title, post=p["post"],
                            author=p["author"], date=p["date"])  # fmt: skip
                for pid in dict.fromkeys(PASTE_RE.findall(p["body"])):
                    found.append(Found(**meta, paste=pid))
                for text in inline_teams(body_text(p["body"])):
                    found.append(Found(**meta, text=text))
            if (k + 1) % 50 == 0:
                log(f"  {name}: {k + 1}/{len(threads)} threads, {len(found) - n0} teams, "
                    f"{f.requests} requests")  # fmt: skip
        log(f"{name}: {len(threads)} threads, {len(found) - n0} teams found")
    if f.blocked:
        log(f"warning: {f.blocked} pages not read -- the forum's browser check turned the "
            "crawler away; the cached pages were read")  # fmt: skip
    return found
