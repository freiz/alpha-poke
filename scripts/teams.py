"""Team data (design D5-T; layout in ``alpha_poke.teams``).

  collect      crawl the Smogon forum sources + download the pokepast.es pastes they link
               (cached under data/teams/raw; --refresh re-reads forum listings / last pages)
               -> data/teams/raw/links.jsonl
  build        links + caches -> data/teams/catalog.jsonl (canonical, deduplicated, only the
               teams legal in gen9ou today; rerun after a rule change)
  stats        catalog summary
  export       catalog entries -> a pool directory (data/teams/pools/<name>)
  reconstruct  a pool of widely copied ladder teams reconstructed from replays

Usage:
  uv run python scripts/teams.py collect [--sources sample,rmt]
  uv run python scripts/teams.py build
  uv run python scripts/teams.py export --name sample --sources sample --complete
  uv run python scripts/teams.py reconstruct --name replay40 [--offset 40] [--spread-mode top]
"""

import argparse
import json
from collections import Counter

from alpha_poke.teams import POOLS_DIR, catalog, forum, pokepaste
from alpha_poke.teams.catalog import LINKS


def collect(a) -> None:
    names = a.sources.split(",") if a.sources else list(forum.SOURCES)
    f = forum.Fetcher(refresh=a.refresh)
    found = forum.crawl(f, {k: forum.SOURCES[k] for k in names})
    pastes = list(dict.fromkeys(x.paste for x in found if x.paste))
    missing = 0
    for i, pid in enumerate(pastes):
        missing += pokepaste.fetch(f, pid) is None
        if (i + 1) % 200 == 0:
            print(f"  pastes {i + 1}/{len(pastes)}", flush=True)
    # links.jsonl keeps the rows of sources not crawled this time
    keep = []
    if LINKS.exists():
        rows = map(json.loads, LINKS.read_text().splitlines())
        keep = [r for r in rows if r["source"] not in names]
    LINKS.parent.mkdir(parents=True, exist_ok=True)
    LINKS.write_text("".join(json.dumps(r) + "\n" for r in keep + [x.row() for x in found]))
    inline = sum(x.text is not None for x in found)
    print(f"{len(found)} teams found ({len(pastes)} pastes, {missing} gone, {inline} inline); "
          f"{f.requests} requests -> {LINKS}")  # fmt: skip


def build(a) -> None:
    links = [json.loads(line) for line in LINKS.read_text().splitlines() if line]
    entries = catalog.build(links)
    catalog.save(entries)
    stats(a, entries)


def stats(a, entries=None) -> None:
    entries = entries if entries is not None else catalog.load()
    print(f"{len(entries)} legal teams, {sum(e.complete for e in entries)} complete")
    by = Counter(s for e in entries for s in e.source_names)
    ok = Counter(s for e in entries if e.complete for s in e.source_names)
    for s, n in by.most_common():
        print(f"  {s:14s} {n:5d} teams, {ok[s]:5d} complete")
    years = Counter(e.date[:4] for e in entries if e.complete)
    print("  complete by year (first posted):", dict(sorted(years.items())))


def export(a) -> None:
    entries = catalog.load()
    names = set(a.sources.split(",")) if a.sources else None
    pick = [e for e in entries
            if (names is None or e.source_names & names)
            and (e.complete or not a.complete)
            and e.date[:10] >= a.since]  # fmt: skip
    if a.limit:
        pick = pick[-a.limit :]  # the most recent
    meta = {
        "kind": "catalog export", "sources": sorted(names) if names else "all",
        "complete": a.complete, "since": a.since,
        "entries": [e.id for e in pick],
    }  # fmt: skip
    catalog.write_pool(POOLS_DIR / a.name, [(e.key, e.text) for e in pick], meta)
    print(f"{len(pick)} teams -> {POOLS_DIR / a.name}")


def reconstruct(a) -> None:
    from alpha_poke.teams.replay_pool import reconstruct as run

    run(POOLS_DIR / a.name, a.min_uses, a.max_teams, a.offset, a.spread_mode, a.seed)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("collect")
    p.add_argument("--sources", default="", help=f"of {','.join(forum.SOURCES)} (default all)")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(fn=collect)
    sub.add_parser("build").set_defaults(fn=build)
    sub.add_parser("stats").set_defaults(fn=stats)
    p = sub.add_parser("export")
    p.add_argument("--name", required=True)
    p.add_argument("--sources", default="")
    p.add_argument("--complete", action="store_true")
    p.add_argument("--since", default="", help="first posted on or after (YYYY-MM-DD)")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(fn=export)
    p = sub.add_parser("reconstruct")
    p.add_argument("--name", required=True)
    p.add_argument("--min-uses", type=int, default=50)
    p.add_argument("--max-teams", type=int, default=40)
    p.add_argument("--offset", type=int, default=0, help="skip the N most used teams")
    p.add_argument("--spread-mode", choices=["top", "sample"], default="sample")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=reconstruct)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
