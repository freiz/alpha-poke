"""The catalog of complete teams (``teams/catalog.jsonl``) and pool export.

Built from the crawl (``raw/links.jsonl`` + the paste cache): every found team is put into
Showdown's canonical export, deduplicated on the canonical text (the same team posted twice ->
one entry with both sources), and kept only if it is legal in gen9ou today (later bans make
old teams illegal; after a rule change, rebuild from the cache). Deduplication (2026-10-31, more
sources -- the forum read whole, archived pastes):
  * a paste linked from several posts or sources is read and validated once, its sources merged;
  * the same canonical text -> one entry;
  * near-duplicates -- the same six species, at most NEAR_DIFF differences in items, abilities,
    tera types and moves (spreads ignored: a team tweaked and posted again) -- share a
    ``family`` (its representative's id: the entry with the most sources, then the earliest);
    ``load(dedup=True)`` gives the representatives only."""

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from alpha_poke.teams import CATALOG, RAW_DIR, pokepaste
from alpha_poke.teams.validate import check, team_key

LINKS = RAW_DIR / "links.jsonl"


@dataclass
class Entry:
    id: str  # sha1 of the canonical text, 12 hex
    key: str  # team key (sorted preview species, as the replay tables)
    text: str  # canonical Showdown export
    complete: bool  # every set has EVs, an ability and 4 moves
    date: str  # earliest post date (ISO)
    sources: list[dict] = field(default_factory=list)  # links.jsonl rows (+ paste title)
    family: str = ""  # its near-duplicates' representative's id (itself when it is one)

    @property
    def source_names(self) -> set[str]:
        return {s["source"] for s in self.sources}


def is_complete(text: str) -> bool:
    sets = text.strip().split("\n\n")
    return len(sets) == 6 and all(
        "\nEVs:" in s and "\nAbility:" in s and len(re.findall(r"^- ", s, re.M)) == 4 for s in sets
    )


NEAR_DIFF = 2


def _parts(text: str) -> dict[str, tuple]:
    """A canonical export -> species -> (item, ability, tera, moves) (spreads left out)."""
    out = {}
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        head = lines[0].split(" @ ")
        species = head[0].strip()
        item = head[1].strip() if len(head) > 1 else ""
        ability = next((x[9:].strip() for x in lines if x.startswith("Ability:")), "")
        tera = next((x[10:].strip() for x in lines if x.startswith("Tera Type:")), "")
        moves = frozenset(x[2:].strip() for x in lines if x.startswith("- "))
        out[species] = (item, ability, tera, moves)
    return out


def _difference(a: dict, b: dict) -> int:
    """Differences between two teams of the same species: an item, ability or tera type each 1,
    a move swapped 1."""
    d = 0
    for sp, (i1, a1, t1, m1) in a.items():
        i2, a2, t2, m2 = b.get(sp, ("", "", "", frozenset()))
        d += (i1 != i2) + (a1 != a2) + (t1 != t2) + max(len(m1 - m2), len(m2 - m1))
    return d


def families(entries: list["Entry"], near: int = NEAR_DIFF) -> None:
    """Sets each entry's ``family``: near-duplicates (same key, at most ``near`` differences)
    joined, the representative the one with the most sources, then the earliest."""
    parent = {e.id: e.id for e in entries}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_key: dict[str, list] = {}
    for e in entries:
        by_key.setdefault(e.key, []).append((e, _parts(e.text)))
    for group in by_key.values():
        for i, (e1, p1) in enumerate(group):
            for e2, p2 in group[i + 1 :]:
                if _difference(p1, p2) <= near:
                    parent[find(e1.id)] = find(e2.id)
    members: dict[str, list] = {}
    for e in entries:
        members.setdefault(find(e.id), []).append(e)
    for group in members.values():
        rep = min(group, key=lambda e: (-len(e.sources), e.date or "9999", e.id))
        for e in group:
            e.family = rep.id


def build(links: list[dict], fmt: str = "gen9ou", log=print) -> list[Entry]:
    texts, metas, skipped = [], [], Counter()
    # (a paste linked several times -- posts, sources: read and validated once, its sources merged)
    by_paste: dict[str, list[dict]] = {}
    for row in links:
        if "paste" in row:
            by_paste.setdefault(row["paste"], []).append(row)
    first = {pid: rows[0] for pid, rows in by_paste.items()}
    links = [r for r in links if "paste" not in r or first[r["paste"]] is r]
    for row in links:
        meta = {k: v for k, v in row.items() if k != "author"}  # posters' names stay local
        if "paste" in row:
            p = pokepaste.load(row["paste"])
            if p is None:
                skipped["paste missing"] += 1
                continue
            pf = pokepaste.paste_format(p)
            if pf and pf != fmt:
                skipped[f"format {pf}"] += 1
                continue
            meta["paste_title"] = p.get("title") or ""
            text = p.get("paste") or ""
        else:
            text = meta.pop("text")
        texts.append(text.replace("\r\n", "\n"))
        metas.append(meta)
    entries: dict[str, Entry] = {}
    illegal: dict[str, str] = {}  # canonical text -> first problem
    for meta, r in zip(metas, check(texts, fmt), strict=True):
        if r["n"] != 6:
            skipped[f"{r['n']} sets"] += 1
            continue
        if r["problems"]:
            illegal[r["text"]] = r["problems"][0]
            continue
        eid = hashlib.sha1(r["text"].encode()).hexdigest()[:12]
        e = entries.get(eid)
        if e is None:
            e = entries[eid] = Entry(
                id=eid, key=team_key(r["species"]), text=r["text"],
                complete=is_complete(r["text"]), date=meta["date"],
            )  # fmt: skip
        if "paste" in meta:  # (every post / source that linked this paste)
            for other in by_paste[meta["paste"]]:
                m = {k: v for k, v in other.items() if k != "author"}
                m["paste_title"] = meta.get("paste_title", "")
                e.sources.append(m)
        else:
            e.sources.append(meta)
        dates = [x["date"] for x in e.sources if x.get("date")]
        e.date = min(dates) if dates else e.date
    families(list(entries.values()))
    n_fam = len({e.family for e in entries.values()})
    why = Counter(re.sub(r"^\S+ (\(.*?\) )?", "", p)[:60] for p in illegal.values())
    log(
        f"{len(texts)} found teams ({len(by_paste)} distinct pastes) -> {len(entries)} distinct legal "
        f"in {n_fam} families (near-duplicates joined); dropped {len(illegal)} "
        f"distinct illegal (most common: {why.most_common(4)}); skipped {dict(skipped)}"
    )
    return sorted(entries.values(), key=lambda e: (e.date, e.id))


def save(entries: list[Entry], path: Path = CATALOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(e)) + "\n" for e in entries), encoding="utf-8")


def load(path: Path = CATALOG, dedup: bool = False) -> list[Entry]:
    """The catalog; ``dedup``: one entry per family of near-duplicates (its representative)."""
    entries = [
        Entry(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line
    ]
    return [e for e in entries if not e.family or e.family == e.id] if dedup else entries


def write_pool(out: Path, teams: list[tuple[str, str]], meta: dict) -> None:
    """A pool directory: team_XX.txt (Showdown export), index.json (stem -> team key; the
    heldout belief model excludes these keys), meta.json (how it was made, per-team origin)."""
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("team_*.txt"):
        f.unlink()
    index = {}
    for i, (key, text) in enumerate(teams):
        stem = f"team_{i:02d}" if len(teams) <= 100 else f"team_{i:03d}"
        (out / f"{stem}.txt").write_text(text.strip() + "\n")
        index[stem] = key
    (out / "index.json").write_text(json.dumps(index, indent=1))
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
