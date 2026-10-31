"""The metagame knowledge the review app's team analysis reads (coach.meta; 2026-10-30): one compact
file shipped with the app (src/alpha_poke/coach/meta_knowledge.json.gz) -- nothing is fetched on the
player's computer. Re-run with the team design's update (doc/team_design.md: fresh replays first),
then commit the file.

  uv run python scripts/build_meta_knowledge.py [--meta-days 21] [--top 200]

It holds:
  model     the matchup model (analysis.matchups, refit on the games since --since as
            build_robust_teams does, with its teammate term S -- synergy; cached by the games'
            newest time): the --top species by games (the rest "other"), their strength a, the
            matchup matrix M and the teammate matrix S (rounded); its held-out log loss beside the
            model without S
  threats   every species of the metagame with a share of its Pokemon >= --threat-share, with that
            share and its main builds (scripts/threat_check: the belief's set archetypes as exports
            with Smogon spreads; 3 for the --threats most used, 2 for the rest), for coach.meta's
            set-by-set threat check -- 123 species, 98% of the opponents' Pokemon, 2026-10-30: the
            15 most used were half of them, a rare counter of the team went unseen
  metagame  the compositions played by players >= --meta-elo in the last --meta-days, each game
            weighted 0.5 ** (age / --meta-half-life) (build_robust_teams.metagame): the --meta-teams
            heaviest, with their weights
  smogon    per species of the latest Smogon month (gen9ou-1500): usage, its most common teammates,
            its checks and counters (the share of encounters it was KOed or forced out, games)
  cores     pairs of species on one side in the last --core-days (players >= --meta-elo, both
            rated): games, win rate, and the margin over what the ratings predict (Elo) -- a core's
            players are part of its record
  forum     the catalog's complete teams (teams/catalog.jsonl: legal today when built): the key and
            the export, its date -- no poster, no link
  ladder    the ladder's best compositions (top_ladder_teams.ranked: time-weighted, players >=
            --min-elo, several players): games, win rate, Elo margin
"""

import argparse
import gzip
import itertools
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_robust_teams as brt  # noqa: E402
import threat_check  # noqa: E402
import top_ladder_teams as tlt  # noqa: E402

from alpha_poke import paths  # noqa: E402
from alpha_poke.analysis import matchups  # noqa: E402
from alpha_poke.coach.meta import SNAPSHOT  # noqa: E402
from alpha_poke.data.smogon_stats import DEFAULT_DIR  # noqa: E402
from alpha_poke.teams import catalog  # noqa: E402

DAY = 86400


def model_of(g: pd.DataFrame, since: int, synergy: bool):
    fit_g = (g[(g.time >= since) & (g.winner > 0) & (g.r1 > 0) & (g.r2 > 0)]
             .sort_values("time").reset_index(drop=True))  # fmt: skip
    cache = paths.TEAM_DATA / f"matchup_model_{'syn_' if synergy else ''}{int(g.time.max())}.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    import torch

    torch.set_num_threads(max(1, (os.cpu_count() or 4) // 4))
    print(f"fitting the matchup model (synergy {synergy}) on {len(fit_g)} games ...", flush=True)
    model, val = matchups.fit(
        fit_g, l2_a=1e-4, l2_m=1e-3, iters=150, synergy=synergy, log=lambda *x: None
    )
    cache.write_bytes(pickle.dumps((model, val)))
    return model, val


def compact_model(model, g: pd.DataFrame, top: int) -> dict:
    """The --top species by games (their rows of a and M); the rest fold into "other"."""
    games = pd.concat([g.team1, g.team2]).str.split("|").explode().value_counts()
    keep = [s for s in games.index if s in set(model.species[:-1])][:top]
    idx = [model.species.index(s) for s in keep] + [len(model.species) - 1]
    out = {"species": keep + ["other"], "beta": round(float(model.beta), 4),
           "a": [round(float(x), 4) for x in model.a[idx]],
           "M": [[round(float(x), 4) for x in row] for row in model.M[np.ix_(idx, idx)]]}  # fmt: skip
    if model.S is not None:
        out["S"] = [[round(float(x), 4) for x in row] for row in model.S[np.ix_(idx, idx)]]
    return out


def threat_builds(meta: pd.Series, k: int, min_share: float) -> dict:
    """The metagame's species with a share of its Pokemon >= ``min_share`` -> {"share", "builds":
    [[weight, export]]}: 3 builds for the k most used, 2 for the rest."""
    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.data.smogon_stats import UsageStats
    from alpha_poke.teams.replay_pool import PREVIEW_FORMS

    use: dict[str, float] = {}
    for team, w in meta.items():
        for s in team.split("|"):
            use[s] = use.get(s, 0.0) + w
    total = sum(use.values())
    names = [s for s in sorted(use, key=lambda s: -use[s]) if use[s] / total >= min_share]
    months = sorted(p.name for p in DEFAULT_DIR.iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1500.json")
    belief = BeliefModel.load()
    return {n: {"share": round(use[n] / total, 5),
                "builds": [[round(w, 3), text] for w, text in
                           threat_check.threat_sets(belief, stats, PREVIEW_FORMS.get(n, n), 3 if i < k else 2, 0.15)]}
            for i, n in enumerate(names)}  # fmt: skip


def smogon() -> tuple[str, dict]:
    months = sorted(p.name for p in DEFAULT_DIR.iterdir() if p.is_dir())
    path = DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1500.json"
    data = json.loads(path.read_text())["data"]
    out = {}
    for sp, d in sorted(data.items(), key=lambda kv: -kv[1]["usage"])[:150]:
        mates = sorted(d.get("Teammates", {}).items(), key=lambda kv: -kv[1])[:8]
        cc = [(k, v) for k, v in d.get("Checks and Counters", {}).items() if v.get("n", 0) >= 300]
        cc = sorted(cc, key=lambda kv: -kv[1]["p"])[:8]
        out[sp] = {"usage": round(d["usage"], 4), "teammates": [k for k, _ in mates],
                   "counters": [[k, round(v["p"], 3), int(v["n"])] for k, v in cc]}  # fmt: skip
    return months[-1], out


def cores(g: pd.DataFrame, days: int, elo: int, min_n: int, species: set) -> dict:
    """ "A|B" -> [games, win rate, margin over the Elo expectation]."""
    g = g[(g.time >= g.time.max() - days * DAY) & (g.winner > 0) & (g.r1 > 0) & (g.r2 > 0)]
    acc: dict[str, list] = {}
    for team, r, ro, won in itertools.chain(
        zip(g.team1, g.r1, g.r2, g.winner == 1, strict=True),
        zip(g.team2, g.r2, g.r1, g.winner == 2, strict=True),
    ):
        if r < elo:
            continue
        exp = 1 / (1 + 10 ** ((ro - r) / 400))
        mons = sorted(s for s in team.split("|") if s in species)
        for a, b in itertools.combinations(mons, 2):
            x = acc.setdefault(f"{a}|{b}", [0, 0.0, 0.0])
            x[0] += 1
            x[1] += won
            x[2] += won - exp
    return {k: [n, round(w / n, 4), round(m / n, 4)] for k, (n, w, m) in acc.items() if n >= min_n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--since", type=int, default=1746057600, help="the model's games from (2025-05-01)"
    )
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--meta-days", type=int, default=21)
    ap.add_argument("--meta-half-life", type=float, default=14.0)
    ap.add_argument("--meta-elo", type=int, default=1500)
    ap.add_argument("--meta-teams", type=int, default=5000)
    ap.add_argument("--core-days", type=int, default=90)
    ap.add_argument("--core-min", type=int, default=300)
    ap.add_argument("--min-elo", type=int, default=1600, help="(the ladder's: as top_ladder_teams)")
    ap.add_argument("--ladder", type=int, default=300)
    ap.add_argument("--threats", type=int, default=60, help="the most used: 3 builds each")
    ap.add_argument(
        "--threat-share",
        type=float,
        default=0.0005,
        help="a threat's share of the metagame's Pokemon",
    )
    ap.add_argument("--out", default=str(SNAPSHOT))
    a = ap.parse_args()

    g = brt.all_games()
    _, plain = model_of(g, a.since, synergy=False)
    model, val = model_of(g, a.since, synergy=True)
    val["val_logloss_without_synergy"] = plain["val_logloss"]
    print("model:", {k: round(v, 4) if isinstance(v, float) else v for k, v in val.items()})
    meta = brt.metagame(g, a).head(a.meta_teams)
    month, smog = smogon()
    m = compact_model(model, g, a.top)
    tlt_args = argparse.Namespace(
        days=60, half_life=14.0, min_elo=a.min_elo, min_n=8, min_players=5, prior=20
    )
    lad, _ = tlt.ranked(tlt_args)
    lad = lad.head(a.ladder)
    forum = [e for e in catalog.load() if e.complete]
    snap = {
        "built": time.strftime("%Y-%m-%d"),
        "sources": {"games_to": time.strftime("%Y-%m-%d", time.gmtime(int(g.time.max()))),
                    "meta_days": a.meta_days, "meta_elo": a.meta_elo, "smogon_month": month,
                    "core_days": a.core_days, "forum_teams": len(forum), "model_val": val},
        "model": m,
        "threats": threat_builds(meta, a.threats, a.threat_share),
        "metagame": [[k, round(float(w), 4)] for k, w in meta.items()],
        "smogon": smog,
        "cores": cores(g, a.core_days, a.meta_elo, a.core_min, set(m["species"])),
        "forum": [{"key": e.key, "text": e.text, "date": e.date} for e in forum],
        "ladder": [{"key": k, "games": int(r.n), "win": round(float(r.win), 4), "margin": round(float(r.margin), 4),
                    "players": int(r.players)} for k, r in lad.iterrows()],
    }  # fmt: skip
    out = Path(a.out)
    out.write_bytes(
        gzip.compress(json.dumps(snap, separators=(",", ":"), default=float).encode(), 9)
    )
    print(f"{out}: {out.stat().st_size // 1024} KB -- {len(m['species'])} species, {len(snap['metagame'])} "
          f"compositions, {len(snap['cores'])} cores, {len(forum)} forum teams, {len(snap['ladder'])} ladder teams")  # fmt: skip


if __name__ == "__main__":
    main()
