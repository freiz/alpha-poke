"""Cross-validation of the ladder teams' set reconstruction (scripts/top_ladder_teams.py) against
the forum's complete teams (2026-10-27): for the catalog teams (teams/catalog.jsonl, complete
sets) whose six species the ladder played often, the sets reconstructed from those replays as if
the catalog had none, compared field by field with the posted ones -- item, ability, tera type,
moves (of 4), nature, EVs (exact; and the L1 distance / 1020); the production reconstruction (top_ladder_teams.reconstruct:
replays + the forum's spreads of the other teams), without the forum's spreads, and a baseline without the
replays (the species' most common Smogon item / ability / tera / moves / spread).

  uv run python scripts/check_team_reconstruction.py --min-games 30 --max-teams 60

A posted team is one version; the ladder's players change sets, so 100% is not the ceiling of a
right reconstruction -- the comparison is between the two methods on the same teams.
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from top_ladder_teams import forum_index, reconstruct  # noqa: E402

from alpha_poke.analysis.games_lite import DEST  # noqa: E402
from alpha_poke.analysis.roles import to_id  # noqa: E402
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats  # noqa: E402
from alpha_poke.teams import catalog  # noqa: E402
from alpha_poke.teams.replay_pool import STAT_NAMES, build_set  # noqa: E402

DAY = 86400


def parse(text: str) -> dict:
    """{species id: {item, ability, tera, nature, evs (6), moves (set)}} of an export."""
    out = {}
    for block in text.strip().split("\n\n"):
        lines = [x.strip() for x in block.strip().splitlines() if x.strip()]
        head = lines[0].split(" @ ")
        sp = to_id(head[0].split(" (")[0])
        d = {"item": to_id(head[1]) if len(head) > 1 else "", "ability": "", "tera": "", "nature": "",
             "evs": [0] * 6, "moves": set()}  # fmt: skip
        for x in lines[1:]:
            if x.startswith("Ability:"):
                d["ability"] = to_id(x[8:])
            elif x.startswith("Tera Type:"):
                d["tera"] = to_id(x[10:])
            elif x.endswith("Nature"):
                d["nature"] = to_id(x[:-6])
            elif x.startswith("EVs:"):
                for part in x[4:].split("/"):
                    v, st = part.split()
                    d["evs"][STAT_NAMES.index(st)] = int(v)
            elif x.startswith("- "):
                d["moves"].add(to_id(x[2:]))
        out[sp] = d
    return out


def base(sp: str) -> str:
    return {"ogerponwellspring": "ogerpon", "ogerponhearthflame": "ogerpon", "ogerponcornerstone": "ogerpon"}.get(
        sp, sp)  # fmt: skip


def compare(real: dict, guess: dict, acc: dict) -> None:
    for sp, r in real.items():
        gsp = (
            sp
            if sp in guess
            else next((k for k in guess if base(k) == base(sp) or k.startswith(sp)), None)
        )
        if gsp is None:
            continue
        g = guess[gsp]
        acc["mons"] += 1
        for f in ("item", "ability", "tera", "nature"):
            acc[f] += r[f] == g[f]
        acc["moves"] += len(r["moves"] & g["moves"]) / max(len(r["moves"]), 1)
        acc["evs"] += r["evs"] == g["evs"]
        acc["ev_l1"] += sum(abs(x - y) for x, y in zip(r["evs"], g["evs"], strict=True)) / 1020


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--min-games", type=int, default=30, help="ladder games of the composition at least"
    )
    ap.add_argument("--max-teams", type=int, default=60)
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--min-elo", type=int, default=1300, help="the replays' players rated at least")
    ap.add_argument("--replays", type=int, default=300)
    a = ap.parse_args()

    g = pd.read_parquet(
        DEST, columns=["id", "time", "r1", "r2", "team1", "team2", "winner", "shard", "row"]
    )
    g = g[(g.winner > 0) & (g.time >= g.time.max() - a.days * DAY)]
    sides = pd.concat([g.team1[g.r1 >= a.min_elo], g.team2[g.r2 >= a.min_elo]]).value_counts()
    newest = {}
    for e in sorted((e for e in catalog.load() if e.complete), key=lambda e: e.date):
        newest[e.key] = e
    cands = sorted(
        ((int(sides.get(k, 0)), k) for k in newest if sides.get(k, 0) >= a.min_games), reverse=True
    )
    cands = cands[: a.max_teams]
    print(
        f"{len(cands)} catalog teams with >= {a.min_games} ladder games (players >= {a.min_elo})",
        flush=True,
    )
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1825.json")
    empty = pd.DataFrame(columns=["species", "item", "ability", "tera_type", "moves"])
    forum = forum_index()
    accs = {"replays": defaultdict(float), "replays, no forum spreads": defaultdict(float),
            "smogon only": defaultdict(float)}  # fmt: skip
    for _, key in cands:
        real = parse(newest[key].text)
        rec = parse(
            reconstruct(key, g, a, stats, forum)
        )  # (the forum's spreads of other teams only)
        plain = parse(reconstruct(key, g, a, stats, {}))
        smog = parse(
            "\n\n".join(build_set(s, empty, stats, "top", random.Random(0)) for s in key.split("|"))
        )
        compare(real, rec, accs["replays"])
        compare(real, plain, accs["replays, no forum spreads"])
        compare(real, smog, accs["smogon only"])
    out = {}
    for name, acc in accs.items():
        m = acc["mons"]
        out[name] = {"mons": int(m), **{f: round(acc[f] / m, 3) for f in ("item", "ability", "tera", "moves",
                                                                         "nature", "evs", "ev_l1")}}  # fmt: skip
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
