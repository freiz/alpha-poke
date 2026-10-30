"""The catalog of complete teams (``teams/catalog.jsonl``) and pool export.

Built from the crawl (``raw/links.jsonl`` + the paste cache): every found team is put into
Showdown's canonical export, deduplicated on the canonical text (the same team posted twice ->
one entry with both sources), and kept only if it is legal in gen9ou today (later bans make
old teams illegal; after a rule change, rebuild from the cache)."""

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

    @property
    def source_names(self) -> set[str]:
        return {s["source"] for s in self.sources}


def is_complete(text: str) -> bool:
    sets = text.strip().split("\n\n")
    return len(sets) == 6 and all(
        "\nEVs:" in s and "\nAbility:" in s and len(re.findall(r"^- ", s, re.M)) == 4 for s in sets
    )


def build(links: list[dict], fmt: str = "gen9ou", log=print) -> list[Entry]:
    texts, metas, skipped = [], [], Counter()
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
        e.sources.append(meta)
        e.date = min(e.date, meta["date"]) if e.date and meta["date"] else e.date or meta["date"]
    why = Counter(re.sub(r"^\S+ (\(.*?\) )?", "", p)[:60] for p in illegal.values())
    log(
        f"{len(texts)} found teams -> {len(entries)} distinct legal; dropped {len(illegal)} "
        f"distinct illegal (most common: {why.most_common(4)}); skipped {dict(skipped)}"
    )
    return sorted(entries.values(), key=lambda e: (e.date, e.id))


def save(entries: list[Entry], path: Path = CATALOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(e)) + "\n" for e in entries), encoding="utf-8")


def load(path: Path = CATALOG) -> list[Entry]:
    return [
        Entry(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line
    ]


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
