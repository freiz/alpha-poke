"""Robust teams for the ladder bot (2026-10-28): the forum's builds and the ladder's best
compositions, scored against the current metagame by the matchup model, not by their own win
rates alone (a team's ladder win rate is its players' too, and says nothing of what it loses to).

Stage 1 (this script, CPU):
  games: the lite scan (data/derived/parsed/gen9ou_games_lite.parquet) + the crawler's replays
    (data/raw/replays/gen9ou/*.json.gz, newer), deduplicated by id;
  the matchup model (analysis.matchups: species strength + species-vs-species, the players'
    ratings in) refit on the games since --since;
  the metagame: the compositions played by players >= --meta-elo in the last --meta-days, each
    game weighted 0.5 ** (age / --meta-half-life);
  candidates: the forum's complete teams legal today (teams/catalog.jsonl, validated) and
    the ladder's compositions with the best time-weighted win rates (top_ladder_teams.ranked);
  per candidate, against the metagame (equal ratings): the expected score (mean), the mean of its
    worst --tail of the metagame's weight (CVaR: what it loses to), and the worst threat (its mean
    against the teams that bring each of the --threats most used species); ranked by
    (mean + cvar) / 2, picked greedily with at most --overlap species shared between picks;
  sets: the forum's own for its teams, reconstructed for the ladder's (top_ladder_teams).
  -> --out (a pool, team_XX.txt) + report.json.

  uv run python scripts/build_robust_teams.py --finalists 12

Stage 2 (simulation with our bot) chooses among the finalists (scripts/sim_team_pool.py).
"""

import argparse
import glob
import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import top_ladder_teams as tlt  # noqa: E402

from alpha_poke import paths  # noqa: E402
from alpha_poke.analysis import games_lite, matchups  # noqa: E402
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats  # noqa: E402
from alpha_poke.teams import POOLS_DIR, catalog  # noqa: E402
from alpha_poke.teams.validate import check  # noqa: E402

DAY = 86400
CRAWL = str(paths.REPLAYS / "gen9ou" / "*.json.gz")


def crawled_games() -> pd.DataFrame:
    """The crawler's replays as lite rows (shard "crawl", row -1: no Metamon log)."""
    rows = []
    for f in glob.glob(CRAWL):
        try:
            d = json.loads(gzip.open(f).read())
        except (OSError, ValueError):
            continue
        r = games_lite.scan(d.get("log") or "")
        if r is not None and d.get("uploadtime"):
            rows.append(
                {"id": d["id"], "time": int(d["uploadtime"])} | r | {"shard": "crawl", "row": -1}
            )
    return pd.DataFrame(rows)


def all_games(log=print) -> pd.DataFrame:
    g = pd.read_parquet(games_lite.DEST)
    c = crawled_games()
    log(f"lite {len(g)} games (to {pd.Timestamp(g.time.max(), unit='s').date()}), crawled {len(c)}"
        + (f" (to {pd.Timestamp(c.time.max(), unit='s').date()})" if len(c) else ""))  # fmt: skip
    if len(c):
        g = pd.concat([g, c[~c.id.isin(set(g.id))]], ignore_index=True)
    return g


def metagame(g: pd.DataFrame, a) -> pd.Series:
    """composition -> weight (games by players >= --meta-elo in the last --meta-days)."""
    now = g.time.max()
    g = g[g.time >= now - a.meta_days * DAY]
    sides = pd.concat([pd.DataFrame({"team": g.team1, "r": g.r1, "t": g.time}),
                       pd.DataFrame({"team": g.team2, "r": g.r2, "t": g.time})])  # fmt: skip
    sides = sides[sides.r >= a.meta_elo]
    w = 0.5 ** ((now - sides.t) / DAY / a.meta_half_life)
    return w.groupby(sides.team).sum().sort_values(ascending=False)


def score(model: matchups.MatchupModel, cands: list[str], meta: pd.Series, a) -> pd.DataFrame:
    """Per candidate: mean, CVaR over the worst --tail of the metagame, the worst threat."""
    meta = meta.head(a.meta_teams)
    w = (meta / meta.sum()).to_numpy()
    opp = [model.index(t.split("|")) for t in meta.index]
    opp_idx = np.array(opp)  # [J, 6]
    # the threats: the most used species in the metagame (by weight)
    use = pd.Series({}, dtype=float)
    for t, x in zip(meta.index, w, strict=True):
        for s in t.split("|"):
            use[s] = use.get(s, 0.0) + x
    threats = use.sort_values(ascending=False).head(a.threats).index.tolist()
    has = {s: np.array([s in t.split("|") for t in meta.index]) for s in threats}
    out = []
    for c in cands:
        ic = model.index(c.split("|"))
        z = (
            model.a[ic].sum()
            - model.a[opp_idx].sum(1)
            + model.M[np.ix_(ic, opp_idx.ravel())].reshape(6, -1, 6).sum((0, 2))
        )
        p = 1 / (1 + np.exp(-z))
        order = np.argsort(p)
        cum = np.cumsum(w[order])
        k = int(np.searchsorted(cum, a.tail)) + 1
        cvar = float((p[order][:k] * w[order][:k]).sum() / w[order][:k].sum())
        mean = float((p * w).sum())
        per_threat = {s: float((p[has[s]] * w[has[s]]).sum() / w[has[s]].sum()) for s in threats}
        worst = min(per_threat, key=per_threat.get)
        out.append({"team": c, "mean": mean, "cvar": cvar, "robust": (mean + cvar) / 2,
                    "worst_threat": worst, "worst_threat_p": per_threat[worst]})  # fmt: skip
    return pd.DataFrame(out).set_index("team").sort_values("robust", ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--since", type=int, default=1746057600, help="the model's games from (2025-05-01)"
    )
    # (21 days / half-life 14, 2026-10-28: the metagame moved in October -- Zamazenta, Ogerpon-W,
    # Gholdengo, Dragonite, Iron Treads up ~10 points, Slowking-G / Cinderace / Rillaboom down)
    ap.add_argument("--meta-days", type=int, default=21)
    ap.add_argument("--meta-half-life", type=float, default=14.0)
    ap.add_argument("--meta-elo", type=int, default=1500)
    ap.add_argument(
        "--meta-teams", type=int, default=5000, help="the metagame's most weighted compositions"
    )
    ap.add_argument("--tail", type=float, default=0.2, help="CVaR: the worst share of the metagame")
    ap.add_argument("--threats", type=int, default=15)
    ap.add_argument("--overlap", type=int, default=3, help="species two picks may share at most")
    ap.add_argument("--finalists", type=int, default=12)
    ap.add_argument(
        "--ladder", type=int, default=200, help="the ladder's best compositions considered"
    )
    ap.add_argument("--min-elo", type=int, default=1600, help="(the ladder's: as top_ladder_teams)")
    ap.add_argument("--replays", type=int, default=300)
    ap.add_argument("--out", default=str(POOLS_DIR / "robust_candidates"))
    ap.add_argument(
        "--score-pool", nargs="*", default=[], help="also score these pools' teams (report only)"
    )
    a = ap.parse_args()

    g = all_games()
    fit_g = (
        g[(g.time >= a.since) & (g.winner > 0) & (g.r1 > 0) & (g.r2 > 0)]
        .sort_values("time")
        .reset_index(drop=True)
    )
    import pickle

    # (cached by the games' newest time: the same data, the same model)
    cache = paths.TEAM_DATA / f"matchup_model_{int(g.time.max())}.pkl"
    if cache.exists():
        model, val = pickle.loads(cache.read_bytes())
    else:
        print(f"fitting the matchup model on {len(fit_g)} games ...", flush=True)
        import torch

        torch.set_num_threads(max(1, (os.cpu_count() or 4) // 4))
        model, val = matchups.fit(fit_g, l2_a=1e-4, l2_m=1e-3, iters=150, log=lambda *x: None)
        cache.write_bytes(pickle.dumps((model, val)))
    print(
        "model:",
        {k: round(v, 4) if isinstance(v, float) else v for k, v in val.items()},
        flush=True,
    )
    meta = metagame(g, a)
    print(
        f"metagame: {len(meta)} compositions (players >= {a.meta_elo}, {a.meta_days} days)",
        flush=True,
    )

    for pool_dir in a.score_pool:  # (e.g. the earlier selection, for comparison)
        teams = list(json.loads((Path(pool_dir) / "index.json").read_text()).values())
        for team, r in score(model, teams, meta, a).iterrows():
            print(f"  [{Path(pool_dir).name}] {r.robust:.3f} (mean {r['mean']:.3f}, cvar {r.cvar:.3f}, "
                  f"worst vs {r.worst_threat} {r.worst_threat_p:.3f}) {team}", flush=True)  # fmt: skip

    # candidates: the forum's legal complete teams, the ladder's best compositions
    forum = {}
    for e in sorted((e for e in catalog.load() if e.complete), key=lambda e: e.date):
        forum[e.key] = e
    keys = sorted(forum)
    res = check([forum[k].text for k in keys])
    forum = {
        k: (forum[k], r["text"])
        for k, r in zip(keys, res, strict=True)
        if r["n"] == 6 and not r["problems"]
    }
    ns = argparse.Namespace(min_elo=a.min_elo, days=365, half_life=90.0, prior=20.0, min_n=30.0,
                            min_players=5, replays=a.replays)  # fmt: skip
    ladder, lite = tlt.ranked(ns)
    ladder_keys = [k for k in ladder.index[: a.ladder] if k not in forum]
    print(
        f"candidates: {len(forum)} forum teams (legal), {len(ladder_keys)} ladder compositions",
        flush=True,
    )
    sc = score(model, list(forum) + ladder_keys, meta, a)

    # greedy picks with limited overlap; sets: the forum's, else reconstructed (and validated)
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1825.json")
    index = tlt.forum_index()
    picked, report = [], []
    for team, r in sc.iterrows():
        if len(picked) >= a.finalists:
            break
        if any(len(set(team.split("|")) & set(t.split("|"))) > a.overlap for t, _ in picked):
            continue
        if team in forum:
            e, text = forum[team]
            src = f"forum {e.id} ({'/'.join(sorted(e.source_names))})"
        else:
            raw = tlt.reconstruct(team, lite, ns, stats, index)
            x = check([raw])[0]
            if x["n"] != 6 or x["problems"]:
                continue
            text, src = x["text"], "ladder (reconstructed)"
        picked.append((team, text))
        emp = ladder.loc[team] if team in ladder.index else None
        report.append({"team": team, "sets": src, **{k: round(float(r[k]), 4) for k in ("mean", "cvar", "robust")},
                       "worst_threat": r.worst_threat, "worst_threat_p": round(float(r.worst_threat_p), 4),
                       "ladder_win": None if emp is None else round(float(emp.win), 4),
                       "ladder_n": None if emp is None else int(emp.n)})  # fmt: skip
        print(f"  {r.robust:.3f} (mean {r['mean']:.3f}, cvar {r.cvar:.3f}, worst vs {r.worst_threat} "
              f"{r.worst_threat_p:.3f}) {team} [{src}]", flush=True)  # fmt: skip
    use = {}
    mw = meta / meta.sum()
    for t, x in mw.items():
        for s in t.split("|"):
            use[s] = use.get(s, 0.0) + float(x)
    threats = sorted(use, key=use.get, reverse=True)[: a.threats]
    meta_info = {"kind": "robust candidates", "args": vars(a), "model_val": val, "teams": report,
                 "threats": [(s, round(use[s], 4)) for s in threats]}  # fmt: skip
    catalog.write_pool(Path(a.out), picked, meta_info)
    (Path(a.out) / "report.json").write_text(json.dumps(meta_info, indent=1, default=str))
    print(f"{len(picked)} finalists -> {a.out}")


if __name__ == "__main__":
    main()
