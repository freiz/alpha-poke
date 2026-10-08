"""Pools reconstructed from replays: widely copied ladder teams, filled in where unseen.

For each 6-mon team used >= ``min_uses`` times in the parsed replays:
  item / ability / tera = most common revealed value within that exact team (else Smogon);
  moves = most revealed moves within the team, topped up from the species' Smogon moves;
  EVs / nature = never visible in replays: sampled from the species' Smogon spread
  distribution (``spread_mode="sample"``) or its most common spread (``"top"``).
Teams failing the local Showdown validator are reported and skipped. These are NOT real
complete teams (the catalog is); they approximate the most played ones.
"""

import random
from collections import Counter
from pathlib import Path

import pandas as pd

from alpha_poke.analysis.roles import to_id
from alpha_poke.analysis.tables import OUT
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats
from alpha_poke.llm_bench import GEN, MOVE_IDS, _learnset
from alpha_poke.teams.catalog import write_pool
from alpha_poke.teams.validate import check

PREVIEW_FORMS = {
    "Zamazenta-*": "Zamazenta",
    "Greninja-*": "Greninja",
    "Dudunsparce-*": "Dudunsparce",
}
# Ogerpon: (mask, fixed tera type, base ability). Replays show "Embody Aspect", which is only
# the ability it gets *after* terastallizing; teams must list the base ability.
OGERPON = {
    "Ogerpon-Wellspring": ("Wellspring Mask", "Water", "Water Absorb"),
    "Ogerpon-Hearthflame": ("Hearthflame Mask", "Fire", "Mold Breaker"),
    "Ogerpon-Cornerstone": ("Cornerstone Mask", "Rock", "Sturdy"),
    "Ogerpon": (None, "Grass", "Defiant"),
}
STAT_NAMES = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")


def smogon_entry(stats: UsageStats, species: str):
    """Smogon stats for a species; falls back to the base species (Smogon merges some formes,
    e.g. 'Zarude-Dada' is listed as 'Zarude')."""
    for name in (species, species.split("-")[0]):
        sid = to_id(name)
        for k, v in stats.species.items():
            if to_id(k) == sid:
                return v
    return None


def pick_spread(smog, mode: str, rng: random.Random) -> str:
    """'top': the species' most common Smogon spread; 'sample': draw from the spread
    distribution (so that a belief model assuming the top spread is not exactly right)."""
    if smog is None or not smog.spreads:
        return "Serious:84/84/84/84/84/84"
    if mode == "top":
        return next(iter(smog.spreads))
    names, weights = zip(*smog.spreads.items(), strict=True)
    return rng.choices(names, weights=weights, k=1)[0]


def build_set(
    species: str,
    rows: pd.DataFrame,
    stats: UsageStats,
    spread_mode: str = "top",
    rng: random.Random | None = None,
) -> str:
    name = PREVIEW_FORMS.get(species, species)
    smog = smogon_entry(stats, name)
    item = rows.item.dropna().mode()
    item = item.iloc[0] if len(item) else None
    ability = rows.ability.dropna().mode()
    ability = ability.iloc[0] if len(ability) else None
    tera = rows.tera_type.dropna().mode()
    tera = tera.iloc[0] if len(tera) else None
    if name in OGERPON:
        mask, tera, ability = OGERPON[name]
        item = mask or item
    if smog is not None:
        if item is None and smog.items:
            item = _display_item(next(iter(smog.items)))
        if ability is None and smog.abilities:
            ability = _display_ability(name, next(iter(smog.abilities)))
        if tera is None and smog.tera_types:
            tera = next(iter(smog.tera_types)).title()
    if ability is None:  # last resort: the species' first listed ability
        abilities = (GEN.pokedex.get(to_id(name), {}).get("abilities") or {}).values()
        ability = next(iter(abilities), None)
    legal = _learnset(name) or set()
    counts = Counter(m for v in rows.moves for m in v.split("|") if m)
    moves = [m for m, _ in counts.most_common() if to_id(m) in legal][:4]
    if smog is not None:
        for mid in smog.move_has:
            if len(moves) >= 4:
                break
            if mid in legal and mid in MOVE_IDS and MOVE_IDS[mid] not in moves:
                moves.append(MOVE_IDS[mid])
    nature, evs = pick_spread(smog, spread_mode, rng or random.Random(0)).split(":")
    ev_text = " / ".join(
        f"{v} {s}" for v, s in zip(evs.split("/"), STAT_NAMES, strict=True) if v != "0"
    )
    lines = [f"{name} @ {item}" if item else name]
    if ability:
        lines.append(f"Ability: {ability}")
    if tera:
        lines.append(f"Tera Type: {tera}")
    lines += [f"EVs: {ev_text}", f"{nature} Nature"] + [f"- {m}" for m in moves]
    return "\n".join(lines)


def _display_item(item_id: str) -> str:
    # Smogon uses ids; Showdown's importer accepts ids for items too, but keep it readable
    return item_id


def _display_ability(species: str, ability_id: str) -> str:
    entry = GEN.pokedex.get(to_id(species), {})
    for a in (entry.get("abilities") or {}).values():
        if to_id(a) == ability_id:
            return a
    return ability_id


def reconstruct(
    out: Path,
    min_uses: int = 50,
    max_teams: int = 40,
    offset: int = 0,
    spread_mode: str = "sample",
    seed: int = 0,
    log=print,
) -> None:
    """The ``max_teams`` most used teams (after skipping ``offset``) -> pool directory."""
    m = pd.read_parquet(OUT / "gen9ou_mons.parquet")
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats_file = DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1825.json"
    stats = UsageStats.load(stats_file)
    per_team = m.drop_duplicates(["id", "side"]).team.value_counts()
    popular = per_team[per_team >= min_uses].index[offset : offset + max_teams]
    rng = random.Random(seed)
    texts = []
    for team in popular:
        d = m[(m.team == team) & m.brought]
        sets = [build_set(s, d[d.species == s], stats, spread_mode, rng) for s in team.split("|")]
        texts.append("\n\n".join(sets))
    teams = []
    for i, (team, text, r) in enumerate(zip(popular, texts, check(texts), strict=True)):
        if r["problems"]:
            log(f"[skip] team {i} ({team}): {r['problems'][0][:120]}")
            continue
        teams.append((i, team, text))
    meta = {
        "kind": "replay reconstruction", "min_uses": min_uses, "offset": offset,
        "spread_mode": spread_mode, "seed": seed, "smogon_stats": str(stats_file),
        "uses": [int(per_team[t]) for _, t, _ in teams],
    }  # fmt: skip
    write_pool(out, [(t, x) for _, t, x in teams], meta)
    log(f"{len(teams)}/{len(popular)} teams valid -> {out}")
