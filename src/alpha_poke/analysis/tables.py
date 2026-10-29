"""Flatten parsed replays into analysis tables (one row per game / per game-side-mon).

Built incrementally from the crawler index: only replays not yet in the tables are parsed.
Names are normalized to Showdown IDs (lowercase alphanumerics) in ``*_id`` columns so they can
be joined with Smogon usage statistics.
"""

import gzip
import json
import sqlite3

import pandas as pd

from alpha_poke import paths  # noqa: E402
from alpha_poke.replay import parse_replay

REPLAYS = paths.REPLAYS
OUT = paths.PARSED


def to_id(name: str | None) -> str | None:
    return "".join(c for c in name.lower() if c.isalnum()) if name else None


def replay_rows(data: dict, meta: dict) -> tuple[dict, list[dict]]:
    r = parse_replay(data)
    leads = r.leads()
    game = {
        "id": r.id,
        "uploadtime": r.uploadtime,
        "rating": meta.get("rating"),
        "turns": r.turns,
        "winner": r.winner,
        "p1_rating": r.ratings_before["p1"],
        "p2_rating": r.ratings_before["p2"],
        "p1_lead": leads["p1"],
        "p2_lead": leads["p2"],
        "n_warnings": len(r.warnings),
    }
    mons = []
    for side in ("p1", "p2"):
        team = [m for m in r.teams[side] if not m.phantom]
        species = sorted(m.species for m in team)
        hazards = {
            e["detail"] for e in r.field_events if e["kind"] == "sidestart" and e["side"] != side
        }  # hazards this side set on the opponent
        for m in team:
            mons.append(
                {
                    "id": r.id,
                    "side": side,
                    "player": r.players.get(side),
                    "rating": r.ratings_before[side],
                    "won": None if r.winner is None else r.winner == side,
                    "species": m.species,
                    "species_id": to_id(m.species),
                    "team": "|".join(species),
                    "item": m.item,
                    "item_id": to_id(m.item),
                    "ability": m.ability,
                    "ability_id": to_id(m.ability),
                    "tera_type": m.tera_type,
                    "tera_turn": m.tera_turn,
                    "moves": "|".join(m.moves),
                    "n_moves": len(m.moves),
                    "lead": m.lead,
                    "brought": m.brought,
                    "fainted_turn": m.fainted_turn,
                    "n_switch_ins": len(m.switch_ins),
                    "side_hazards_set": "|".join(sorted(hazards)),
                }
            )
    return game, mons


def build(format_id: str = "gen9ou") -> tuple[pd.DataFrame, pd.DataFrame]:
    OUT.mkdir(parents=True, exist_ok=True)
    gpath, mpath = OUT / f"{format_id}_games.parquet", OUT / f"{format_id}_mons.parquet"
    games = pd.read_parquet(gpath) if gpath.exists() else pd.DataFrame()
    mons = pd.read_parquet(mpath) if mpath.exists() else pd.DataFrame()
    have = set(games["id"]) if len(games) else set()
    db = sqlite3.connect(REPLAYS / "index.sqlite")
    rows = db.execute(
        "SELECT id, format_id, rating FROM replays WHERE status='done' AND format_id=?",
        (format_id,),
    ).fetchall()
    new_g, new_m = [], []
    for rid, fid, rating in rows:
        if rid in have:
            continue
        with gzip.open(REPLAYS / fid / f"{rid}.json.gz", "rt", encoding="utf-8") as f:
            g, ms = replay_rows(json.load(f), {"rating": rating})
        new_g.append(g)
        new_m.extend(ms)
    if new_g:
        games = pd.concat([games, pd.DataFrame(new_g)], ignore_index=True)
        mons = pd.concat([mons, pd.DataFrame(new_m)], ignore_index=True)
        games.to_parquet(gpath, index=False)
        mons.to_parquet(mpath, index=False)
    print(f"{len(new_g)} new games parsed; tables now {len(games)} games / {len(mons)} mon rows")
    return games, mons
