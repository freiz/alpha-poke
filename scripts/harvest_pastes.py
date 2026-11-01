"""PokéPaste teams beyond the ones linked from the forum (2026-10-31): pokepast.es has no listing,
but the Wayback Machine has archived ~100k of its pastes -- their ids from its index (CDX), their
pages from the archive (not from pokepast.es: a small site), parsed into the pastes' cache
(teams.pokepaste: {"title", "author", "notes", "paste"}) and added to the links as source
"wayback". Most of them are VGC team lists: only the ones labelled gen9ou are linked (unlabelled
ones with --unlabelled), and the catalog's build keeps those that pass the validator.

  uv run python scripts/harvest_pastes.py list          # the archived ids -> raw/pokepaste_index.jsonl
  uv run python scripts/harvest_pastes.py fetch [--max N] [--delay 2]   # resumable
  uv run python scripts/harvest_pastes.py links         # gen9ou-labelled pastes -> links.jsonl
  uv run python scripts/teams.py build                  # then the catalog as usual
"""

import argparse
import html
import json
import re
import time

import requests

from alpha_poke.teams import RAW_DIR, pokepaste
from alpha_poke.teams.catalog import LINKS
from alpha_poke.teams.forum import USER_AGENT

INDEX = RAW_DIR / "pokepaste_index.jsonl"
CDX = "https://web.archive.org/cdx/search/cdx"
ID_RE = re.compile(r"pokepast\.es(?::\d+)?/([0-9a-f]{16})$")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def cmd_list(a) -> None:
    s = session()
    pages = int(
        s.get(
            CDX, params={"url": "pokepast.es/*", "showNumPages": "true"}, timeout=120
        ).text.strip()
    )
    cache = RAW_DIR / "pokepaste_cdx"
    cache.mkdir(parents=True, exist_ok=True)
    latest: dict[str, str] = {}
    for p in range(pages):
        f = cache / f"page-{p}.txt"
        if not f.exists() or a.refresh:  # (--refresh: the archive's index again -- new pastes)
            time.sleep(a.delay)
            r = s.get(CDX, params={"url": "pokepast.es/*", "fl": "original,timestamp,statuscode",
                                   "collapse": "urlkey", "page": p}, timeout=300)  # fmt: skip
            r.raise_for_status()
            f.write_text(r.text, encoding="utf-8")
        for line in f.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 3 or parts[2] != "200":
                continue
            m = ID_RE.search(parts[0])
            if m and parts[1] > latest.get(m.group(1), ""):
                latest[m.group(1)] = parts[1]
        print(f"page {p + 1}/{pages}: {len(latest)} ids", flush=True)
    INDEX.write_text(
        "".join(json.dumps({"id": k, "ts": v}) + "\n" for k, v in sorted(latest.items()))
    )
    print(f"{len(latest)} archived pastes -> {INDEX}")


def parse(page: str) -> dict | None:
    """An archived paste page -> the pastes' cache format (None: not a paste page)."""
    sets = re.findall(r"<pre>(.*?)</pre>", page, re.S)
    if not sets:
        return None

    def text(x: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", x)).replace("\xa0", " ").strip()

    aside = re.search(r"<aside>(.*?)</aside>", page, re.S)
    a = aside.group(1) if aside else ""
    title = re.search(r"<h1>(.*?)</h1>", a, re.S)
    author = re.search(r"<h2>(.*?)</h2>", a, re.S)
    notes = re.search(r"<p>(.*?)</p>", a, re.S)
    return {"title": text(title.group(1)) if title else "",
            "author": re.sub(r"^by\s+", "", text(author.group(1))) if author else "",
            "notes": text(notes.group(1)) if notes else "",
            "paste": "\n\n".join(text(x) for x in sets), "via": "wayback"}  # fmt: skip


def cmd_fetch(a) -> None:
    s = session()
    rows = [json.loads(line) for line in INDEX.read_text().splitlines()]
    pokepaste.CACHE.mkdir(parents=True, exist_ok=True)
    todo = [r for r in rows if not (pokepaste.CACHE / f"{r['id']}.json").exists()][: a.max or None]
    print(f"{len(rows)} archived, {len(todo)} to fetch", flush=True)
    got = gone = 0
    for k, r in enumerate(todo):
        time.sleep(a.delay)
        url = f"https://web.archive.org/web/{r['ts']}id_/https://pokepast.es/{r['id']}"
        try:
            resp = s.get(url, timeout=120)
        except requests.RequestException:
            time.sleep(30)
            continue
        if resp.status_code == 429:  # (slowed down by the archive: wait, then on)
            time.sleep(120)
            continue
        p = parse(resp.text) if resp.status_code == 200 else None
        # (an unreadable one is cached empty: pokepaste.load reads it as missing, not refetched)
        (pokepaste.CACHE / f"{r['id']}.json").write_text(
            json.dumps(p) if p else "", encoding="utf-8"
        )
        got += p is not None
        gone += p is None
        if (k + 1) % 200 == 0:
            print(f"  {k + 1}/{len(todo)}: {got} pastes, {gone} unreadable", flush=True)
    print(f"done: {got} pastes, {gone} unreadable")


def cmd_links(a) -> None:
    """The archived pastes labelled gen9ou (their "Format:" note) not linked yet -> links.jsonl rows
    of source "wayback" (the date: the snapshot's). Unlabelled ones only with --unlabelled: a UU
    or RU team is legal in OU, so the validator alone does not make one an OU team."""
    rows = [json.loads(line) for line in INDEX.read_text().splitlines()]
    links = (
        [json.loads(line) for line in LINKS.read_text().splitlines() if line]
        if LINKS.exists()
        else []
    )
    have = {r.get("paste") for r in links}
    keep = [r for r in links if r.get("source") != "wayback"]
    new, formats = [], {}
    for r in rows:
        p = pokepaste.load(r["id"])
        if p is None:
            continue
        fmt = pokepaste.paste_format(p) or "?"
        formats[fmt] = formats.get(fmt, 0) + 1
        if not (fmt == "gen9ou" or (a.unlabelled and fmt == "?")) or r["id"] in have:
            continue
        ts = r["ts"]
        new.append({"source": "wayback", "thread": 0, "thread_title": "", "post": 0, "author": "",
                    "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:00+0000", "paste": r["id"]})  # fmt: skip
    LINKS.write_text("".join(json.dumps(r) + "\n" for r in keep + new))
    top = sorted(formats.items(), key=lambda kv: -kv[1])[:8]
    print(f"{len(new)} archived pastes added (gen9ou{' or unlabelled' if a.unlabelled else ''}); "
          f"formats seen: {top}")  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--delay", type=float, default=3.0)
    p.add_argument("--refresh", action="store_true", help="read the index again (new pastes)")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("fetch")
    p.add_argument("--max", type=int, default=0)
    p.add_argument("--delay", type=float, default=2.0)
    p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("links")
    p.add_argument(
        "--unlabelled", action="store_true", help="unlabelled pastes too (unchecked tier)"
    )
    p.set_defaults(fn=cmd_links)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
