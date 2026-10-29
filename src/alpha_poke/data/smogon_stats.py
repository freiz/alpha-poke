"""Smogon monthly usage statistics (https://www.smogon.com/stats/).

``smogon.com/robots.txt`` only has an ``Amazonbot: Allow`` stanza (no restrictions for other
agents). The files are static, so a full month of one format is ~20 small requests.

Per month directory ``YYYY-MM/`` and format ``gen9ou`` with rating cutoff ``C``:
  gen9ou-C.txt                  usage table (rank, usage %, raw count)
  chaos/gen9ou-C.json           full machine-readable stats (what ``UsageStats`` parses)
  moveset/gen9ou-C.txt          human-readable per-mon sets
  leads/gen9ou-C.txt            lead usage
  metagame/gen9ou-C.txt         playstyle / archetype breakdown
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from alpha_poke import paths
from alpha_poke.http import PoliteClient

BASE = "https://www.smogon.com/stats"
DEFAULT_DIR = paths.SMOGON
KINDS = ("", "chaos", "moveset", "leads", "metagame")


def _norm(d: dict[str, float]) -> dict[str, float]:
    total = sum(d.values())
    return {k: v / total for k, v in sorted(d.items(), key=lambda kv: -kv[1])} if total else {}


@dataclass
class SpeciesStats:
    name: str
    usage: float  # fraction of teams (weighted) that bring this species
    raw_count: int
    abilities: dict[str, float]
    items: dict[str, float]
    moves: dict[str, float]  # share of move slots (sums to 1)
    move_has: dict[str, float]  # P(set contains the move) = count / species weight
    tera_types: dict[str, float]
    spreads: dict[str, float]  # "Nature:HP/Atk/Def/SpA/SpD/Spe" -> probability
    teammates: dict[str, float]  # co-occurrence weight (not a probability)
    counters: dict[str, tuple[float, float, float]]  # mon -> (n, p, d)


class UsageStats:
    def __init__(self, raw: dict):
        info = raw["info"]
        self.metagame: str = info["metagame"]
        self.cutoff: int = info["cutoff"]
        self.battles: int = info["number of battles"]
        self.species: dict[str, SpeciesStats] = {}
        for name, d in raw["data"].items():
            weight = sum(d.get("Abilities", {}).values()) or 1.0
            self.species[name] = SpeciesStats(
                name=name,
                usage=d.get("usage", 0.0),
                raw_count=d.get("Raw count", 0),
                abilities=_norm(d.get("Abilities", {})),
                items=_norm(d.get("Items", {})),
                moves=_norm({k: v for k, v in d.get("Moves", {}).items() if k}),
                move_has=dict(
                    sorted(
                        ((k, min(v / weight, 1.0)) for k, v in d.get("Moves", {}).items() if k),
                        key=lambda kv: -kv[1],
                    )
                ),
                tera_types=_norm(d.get("Tera Types", {})),
                spreads=_norm(d.get("Spreads", {})),
                teammates=dict(sorted(d.get("Teammates", {}).items(), key=lambda kv: -kv[1])),
                counters={k: tuple(v) for k, v in d.get("Checks and Counters", {}).items()},
            )

    @classmethod
    def load(cls, path: Path | str) -> "UsageStats":
        return cls(json.loads(Path(path).read_text()))

    def ranked(self) -> list[SpeciesStats]:
        return sorted(self.species.values(), key=lambda s: -s.usage)

    def profile(self, name: str, top: int = 6) -> str:
        s = self.species[name]

        def fmt(d):
            return ", ".join(f"{k} {100 * v:.0f}%" for k, v in list(d.items())[:top])

        return (
            f"{s.name}  usage {100 * s.usage:.1f}%  (raw {s.raw_count})\n"
            f"  abilities: {fmt(s.abilities)}\n  items:     {fmt(s.items)}\n"
            f"  tera:      {fmt(s.tera_types)}\n  moves:     {fmt(s.move_has)}\n"
            f"  spreads:   {fmt(s.spreads)}\n"
            f"  teammates: {', '.join(list(s.teammates)[:top])}"
        )


class SmogonStatsClient:
    def __init__(self, cache_dir: Path | str = DEFAULT_DIR, min_interval: float = 2.0):
        self.cache_dir = Path(cache_dir)
        self.http = PoliteClient(min_interval=min_interval)

    def months(self) -> list[str]:
        """Available month directories, oldest first (e.g. ['2026-08', '2026-09'])."""
        html = self.http.get(f"{BASE}/").text
        return sorted(set(re.findall(r'href="(\d{4}-\d{2})/"', html)))

    def cutoffs(self, month: str, format_id: str) -> list[int]:
        html = self.http.get(f"{BASE}/{month}/").text
        return sorted(
            {int(c) for c in re.findall(rf'href="{re.escape(format_id)}-(\d+)\.txt"', html)}
        )

    def fetch_file(self, month: str, kind: str, format_id: str, cutoff: int) -> Path | None:
        ext = "json" if kind == "chaos" else "txt"
        rel = f"{kind + '/' if kind else ''}{format_id}-{cutoff}.{ext}"
        path = self.cache_dir / month / rel
        if path.exists():
            return path
        try:
            r = self.http.get(f"{BASE}/{month}/{rel}")
        except Exception as e:  # noqa: BLE001 - 404 for a missing combination is normal
            print(f"  skip {month}/{rel}: {type(e).__name__}")
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return path

    def fetch_month(
        self, month: str, format_id: str, cutoffs: list[int] | None = None, kinds=KINDS
    ) -> list[Path]:
        cutoffs = cutoffs if cutoffs is not None else self.cutoffs(month, format_id)
        out = []
        for c in cutoffs:
            for k in kinds:
                p = self.fetch_file(month, k, format_id, c)
                if p:
                    out.append(p)
        return out
