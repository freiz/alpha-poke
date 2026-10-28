"""The ladder bot's teams (scripts/ladder.py --pool; 2026-10-27): the 6-species compositions with
the best time-weighted win rates on the human ladder, then complete sets for them.

  uv run python scripts/top_ladder_teams.py --min-elo 1600 --top 5

Ranking (the lite scan of all games, data/parsed/gen9ou_games_lite.parquet): the sides whose
player is rated >= --min-elo in the last --days days, each weighted 0.5 ** (age / --half-life)
(recent results first); per composition the weighted win rate shrunk toward 50% by --prior games
((W + prior / 2) / (N + prior)), compositions with >= --min-n weighted games by >= --min-players players only. Reported too:
the Elo-adjusted margin (weighted wins minus the wins the rating differences predict, per game)
-- strong players' teams win more because the players are strong.

Sets: a complete real team of the same composition from the catalog (data/teams/catalog.jsonl,
the newest) if there is one, else reconstructed from the composition's recent replays by players
>= --min-elo (teams.replay_pool.build_set: the most revealed item / ability / tera / moves, the
species' Smogon spreads at the 1825 cutoff fitting the item and moves; one variant per species:
the rows of its most common item). Validated (local Showdown) -> --out.
"""

import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_poke.analysis.games_lite import DEST, logs
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats
from alpha_poke.replay.parser import parse_replay
from alpha_poke.teams import POOLS_DIR, catalog
from alpha_poke.teams.replay_pool import build_set
from alpha_poke.teams.validate import check

DAY = 86400


def ranked(a) -> pd.DataFrame:
    g = pd.read_parquet(
        DEST,
        columns=["id", "time", "p1", "p2", "r1", "r2", "team1", "team2", "winner", "shard", "row"],
    )
    g = g[(g.winner > 0) & (g.time >= g.time.max() - a.days * DAY)]
    sides = pd.concat([
        pd.DataFrame({"id": g.id, "time": g.time, "team": g.team1, "player": g.p1, "r": g.r1, "ro": g.r2, "won": g.winner == 1}),
        pd.DataFrame({"id": g.id, "time": g.time, "team": g.team2, "player": g.p2, "r": g.r2, "ro": g.r1, "won": g.winner == 2}),
    ])  # fmt: skip
    sides = sides[(sides.r >= a.min_elo) & (sides.ro > 0)]
    w = 0.5 ** ((sides.time.max() - sides.time) / DAY / a.half_life)
    exp = 1 / (1 + 10 ** ((sides.ro - sides.r) / 400))
    sides = sides.assign(w=w, ww=w * sides.won, we=w * exp, w2=w * w)
    agg = sides.groupby("team").agg(n=("won", "size"), N=("w", "sum"), W=("ww", "sum"), E=("we", "sum"),
                                    w2=("w2", "sum"), last=("time", "max"), elo=("r", "mean"),
                                    players=("player", "nunique"))  # fmt: skip
    agg = agg[(agg.N >= a.min_n) & (agg.players >= a.min_players)]
    agg["win"] = agg.W / agg.N
    agg["score"] = (agg.W + a.prior / 2) / (agg.N + a.prior)
    agg["margin"] = (agg.W - agg.E) / agg.N
    agg["n_eff"] = agg.N**2 / agg.w2
    return agg.sort_values("score", ascending=False), g


NATURE_UP = {
    "atk": {"adamant", "brave", "lonely", "naughty"},
    "spa": {"modest", "quiet", "mild", "rash"},
}
NATURE_DOWN = {
    "atk": {"modest", "timid", "bold", "calm"},
    "spa": {"adamant", "jolly", "impish", "careful"},
}
STAT_INDEX = {"atk": 1, "spa": 3}


def fit_spread(text: str, stats: UsageStats) -> str:
    """A set's EVs / nature from the species' Smogon spreads that fit its item and moves (replays
    never show them; the species' most common spread can be another set's: a Choice Band
    Dragapult with Timid special EVs). Band / mostly physical attacks: Attack invested (EVs >= 100
    or a raising nature) and not lowered; Specs / mostly special: Special Attack alike; else the
    most common spread; two of each: both invested, neither lowered."""
    from poke_env.data import GenData

    from alpha_poke.analysis.roles import to_id
    from alpha_poke.teams.replay_pool import STAT_NAMES, smogon_entry

    moves_dex = GenData.from_gen(9).moves
    lines = text.split("\n")
    head = lines[0].split(" @ ")
    item = to_id(head[1]) if len(head) > 1 else ""
    cats = [moves_dex.get(to_id(x[2:]), {}).get("category") for x in lines if x.startswith("- ")]
    phys, spec = cats.count("Physical"), cats.count("Special")
    # (only clearly offensive sets: an attacking item, or three attacks of a kind -- a wall's two
    # physical moves, Ting-Lu's Earthquake / Stone Edge, keep its usual bulky spread)
    offensive = item in {
        "choiceband",
        "choicespecs",
        "choicescarf",
        "lifeorb",
        "loadeddice",
        "expertbelt",
    }
    need = ("atk" if item == "choiceband" else "spa" if item == "choicespecs" else
            None if not (offensive or max(phys, spec) >= 3) else
            "atk" if phys > spec else "spa" if spec > phys else "mixed")  # fmt: skip
    smog = smogon_entry(stats, head[0])
    if need is None or smog is None or not smog.spreads:
        return text
    for sp in smog.spreads:
        nature, evs = sp.split(":")
        ev = [int(x) for x in evs.split("/")]
        n = nature.lower()
        if need == "mixed":  # (both attacks invested, neither lowered)
            ok = ev[1] > 0 and ev[3] > 0 and n not in NATURE_DOWN["atk"] | NATURE_DOWN["spa"]
        else:
            ok = n not in NATURE_DOWN[need] and (
                ev[STAT_INDEX[need]] >= 100 or n in NATURE_UP[need]
            )
        if ok:
            ev_text = " / ".join(f"{v} {st}" for v, st in zip(ev, STAT_NAMES, strict=True) if v)
            out = [x for x in lines if not (x.startswith("EVs:") or x.endswith(" Nature"))]
            k = next(i for i, x in enumerate(out) if x.startswith("- "))
            return "\n".join(out[:k] + [f"EVs: {ev_text}", f"{nature} Nature"] + out[k:])
    return text


def trick_item(text: str, stats: UsageStats) -> str:
    """A Trick / Switcheroo set without a choice item: the species' most used choice item (the
    replay's item of a mon that used Trick is the one it received -- the opponent's)."""
    from alpha_poke.analysis.roles import to_id
    from alpha_poke.teams.replay_pool import smogon_entry

    lines = text.split("\n")
    head = lines[0].split(" @ ")
    moves = {to_id(x[2:]) for x in lines if x.startswith("- ")}
    if not moves & {"trick", "switcheroo"} or (
        len(head) > 1 and to_id(head[1]).startswith("choice")
    ):
        return text
    smog = smogon_entry(stats, head[0])
    choice = [i for i in (smog.items if smog else {}) if i.startswith("choice")]
    if not choice:
        return text
    names = {
        "choicescarf": "Choice Scarf",
        "choicespecs": "Choice Specs",
        "choiceband": "Choice Band",
    }
    return "\n".join([f"{head[0]} @ {names.get(choice[0], choice[0])}"] + lines[1:])


def forum_index() -> dict:
    """species id -> [(composition, item id, move ids, spread lines)] of the complete catalog sets."""
    from alpha_poke.analysis.roles import to_id

    index: dict = {}
    for e in catalog.load():
        if not e.complete:
            continue
        for block in e.text.strip().split("\n\n"):
            lines = [x.strip() for x in block.strip().splitlines()]
            head = lines[0].split(" @ ")
            spread = [x for x in lines if x.startswith(("EVs:", "IVs:")) or x.endswith(" Nature")]
            moves = {to_id(x[2:]) for x in lines if x.startswith("- ")}
            index.setdefault(to_id(head[0]), []).append(
                (e.key, to_id(head[1]) if len(head) > 1 else "", moves, spread)
            )
    return index


def forum_spread(text: str, index: dict, exclude: str) -> str | None:
    """The set's nature / EVs / IVs from the forum's set of its species with the same item and the
    most moves in common (>= 2), the catalog's other teams only (``exclude``: the composition);
    None without one. (Cross-validated against the forum's own teams, 2026-10-27: nature 66.7%
    -> 75.3%, the EVs' L1 distance 0.224 -> 0.150; scripts/check_team_reconstruction.py.)"""
    from alpha_poke.analysis.roles import to_id

    lines = text.split("\n")
    head = lines[0].split(" @ ")
    item = to_id(head[1]) if len(head) > 1 else ""
    moves = {to_id(x[2:]) for x in lines if x.startswith("- ")}
    best, score = None, 1
    for key, it, mv, spread in index.get(to_id(head[0]), []):
        sc = len(mv & moves)
        if key != exclude and it == item and sc > score:
            best, score = spread, sc
    if best is None:
        return None
    out = [x for x in lines if not (x.startswith(("EVs:", "IVs:")) or x.endswith(" Nature"))]
    k = next(i for i, x in enumerate(out) if x.startswith("- "))
    return "\n".join(out[:k] + best + out[k:])


_MONS: dict = {}  # (team, min_elo, replays) -> its replays' revealed sets


def replay_mons(team: str, g: pd.DataFrame, a) -> pd.DataFrame:
    """The composition's revealed sets in its recent replays (players >= --min-elo), cached."""
    key = (team, a.min_elo, a.replays)
    if key in _MONS:
        return _MONS[key]
    rows = g[((g.team1 == team) & (g.r1 >= a.min_elo)) | ((g.team2 == team) & (g.r2 >= a.min_elo))]
    rows = rows.sort_values("time", ascending=False).head(a.replays).to_dict("records")
    full = logs(rows)
    mons = []
    for r in rows:
        rep = parse_replay(full[r["id"]])
        for s, col in (("p1", "team1"), ("p2", "team2")):
            if r[col] != team:
                continue
            for m in rep.teams[s]:
                if m.phantom or not m.brought:
                    continue
                mons.append({"species": m.species, "item": m.item, "ability": m.ability,
                             "tera_type": m.tera_type, "moves": "|".join(m.moves)})  # fmt: skip
    d = pd.DataFrame(mons, columns=["species", "item", "ability", "tera_type", "moves"])
    _MONS[key] = d
    return d


def reconstruct(team: str, g: pd.DataFrame, a, stats: UsageStats, index: dict | None = None) -> str:
    """The composition's sets from its recent replays (players >= --min-elo)."""
    d = replay_mons(team, g, a)

    def one_variant(rows: pd.DataFrame) -> pd.DataFrame:
        # (players run different sets of a species on the same six: the moves counted over all
        # of them mix the variants -- a Loaded Dice Kyurem's Icicle Spear with a special one's
        # Earth Power; the rows of the most common revealed item only, when there are a few)
        item = rows.item.dropna().mode()
        if len(item) and (rows.item == item.iloc[0]).sum() >= 3:
            return rows[rows.item == item.iloc[0]]
        return rows

    sets = [
        trick_item(
            build_set(s, one_variant(d[d.species == s]), stats, "top", random.Random(0)), stats
        )
        for s in team.split("|")
    ]
    index = forum_index() if index is None else index
    return "\n\n".join(forum_spread(x, index, team) or fit_spread(x, stats) for x in sets)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-elo", type=int, default=1600, help="the team's player rated at least")
    ap.add_argument("--days", type=int, default=365, help="games of the last N days")
    ap.add_argument("--half-life", type=float, default=90.0, help="recency weight, days")
    ap.add_argument("--prior", type=float, default=20.0, help="shrinkage toward 50%, in games")
    ap.add_argument("--min-n", type=float, default=30.0, help="weighted games at least")
    # (5: a composition one player brought is that player's results, not the team's)
    ap.add_argument("--min-players", type=int, default=5, help="distinct players at least")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--replays", type=int, default=300, help="recent replays per reconstruction")
    ap.add_argument("--out", default=str(POOLS_DIR / "ladder_top5"))
    a = ap.parse_args()

    agg, g = ranked(a)
    print(
        f"{len(agg)} compositions with >= {a.min_n} weighted games, >= {a.min_players} players "
        f"(rated >= {a.min_elo})"
    )
    show = agg.head(15)
    for team, r in show.iterrows():
        print(f"  {r.score:.3f} (win {r.win:.3f}, margin {r.margin:+.3f}, n {r.n}, players {r.players}, "
              f"elo {r.elo:.0f}, last {pd.Timestamp(r['last'], unit='s').date()}) {team}")  # fmt: skip
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1825.json")
    index = forum_index()
    real = {}
    for e in sorted((e for e in catalog.load() if e.complete), key=lambda e: e.date):
        real[e.key] = e  # (the newest of a composition last)
    picked, origin = [], []
    for team in agg.index:
        if len(picked) >= a.top:
            break
        text, src = (real[team].text, f"catalog {real[team].id}") if team in real else (
            reconstruct(team, g, a, stats, index), "replays")  # fmt: skip
        res = check([text])[0]
        if res["n"] != 6 or res["problems"]:
            print(f"  [skip] {team}: {res['problems'][:1]}")
            continue
        picked.append((team, res["text"]))
        r = agg.loc[team]
        origin.append({"team": team, "sets": src, "score": round(r.score, 4), "win": round(r.win, 4),
                       "margin": round(r.margin, 4), "n": int(r.n), "players": int(r.players),
                       "n_eff": round(r.n_eff, 1)})  # fmt: skip
        print(f"picked {team} ({src})")
    meta = {"kind": "ladder top teams", "min_elo": a.min_elo, "days": a.days, "half_life": a.half_life,
            "prior": a.prior, "min_n": a.min_n, "teams": origin}  # fmt: skip
    catalog.write_pool(Path(a.out), picked, meta)
    print(json.dumps(origin, indent=1))
    print(f"{len(picked)} teams -> {a.out}")


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
