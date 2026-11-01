"""The metagame knowledge the review app's team analysis reads (coach.meta; 2026-10-30): one compact
file shipped with the app (src/alpha_poke/coach/meta_knowledge.json.gz) -- nothing is fetched on the
player's computer. A step of scripts/knowledge.py (fetch, build, validate, promote): this builds the
candidate (data/derived/teams/knowledge/candidate.json.gz), which replaces the shipped file only
once validated.

  uv run python scripts/build_meta_knowledge.py [--meta-days 21] [--top 200]

Cleaned to Gen 9 OU today (teams.validate: the local Showdown checkout's rules -- a species banned
since leaves the metagame's compositions, the threats, cores, Smogon's table and the ladder's teams;
the forum's teams pass the validator); the matchup model keeps its history, with "banned" listing
what coach.meta must never suggest.

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
  archetypes  the style classifier and per style / feature its share, record, members, answers
            (archetype_stats)
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


def smogon() -> tuple[str, dict, dict]:
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
    return months[-1], out, data


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


def typical_sets(chaos: dict) -> dict[str, dict]:
    """Species (games' names) -> its most common set in Smogon's month (4 moves, item, ability):
    a composition's archetype from its species alone (the games keep no sets)."""
    from alpha_poke.teams import archetypes

    top = lambda d, k: [x for x, _ in sorted(d.items(), key=lambda kv: -kv[1])[:k]]  # noqa: E731
    return {sp: archetypes.mon(sp, top(d["Moves"], 4), (top(d["Items"], 1) or [""])[0],
                               (top(d["Abilities"], 1) or [""])[0])
            for sp, d in chaos.items()}  # fmt: skip


def archetype_stats(g: pd.DataFrame, meta: pd.Series, chaos: dict, a, forum: list, mm) -> dict:
    """The archetypes: the style classifier (archetypes.fit_style on the forum's titled teams, its
    leave-one-out accuracy and the rules' and its agreement with the titles); per style and feature
    in the metagame (each composition by its species' typical sets): its share, its record over
    the last --core-days (players >= --meta-elo, rated: games, win rate, margin over the Elo
    expectation less the average side's), its usual members (share of its teams, lift over the
    metagame), its answers -- the metagame's species (>= 1% of teams) best against its usual
    members by the matchup model ``mm`` (the logit one adds against a typical such team), each
    with the games' own evidence (margin against it less the species' average margin, shrunk
    by --arch-prior games, and the games) -- and style vs style margins."""
    from alpha_poke.teams import archetypes as A

    rows = A.labelled(forum)
    sty = [
        (t, next(iter(labs & set(A.STYLES)))) for t, labs in rows if len(labs & set(A.STYLES)) == 1
    ]
    model = A.fit_style([t for t, _ in sty], [s for _, s in sty])
    print(
        f"style classifier: {model['n']} titled teams, leave-one-out {model['loo']:.1%}", flush=True
    )
    sets = typical_sets(chaos)
    memo: dict[str, list[str]] = {}

    def arch(key: str) -> list[str]:
        if key not in memo:
            team = [sets.get(s) or A.mon(s) for s in key.split("|")]
            t = A.tags(team, model)
            memo[key] = [t["style"], *t["features"]]
        return memo[key]

    share: dict[str, float] = {}
    mons: dict[str, dict[str, float]] = {}
    total = float(meta.sum())
    for key, w in meta.items():
        for k in arch(key):
            share[k] = share.get(k, 0.0) + w / total
            for s in key.split("|"):
                mons.setdefault(k, {})[s] = mons.setdefault(k, {}).get(s, 0.0) + w / total
    base: dict[str, float] = {}
    for key, w in meta.items():
        for s in key.split("|"):
            base[s] = base.get(s, 0.0) + w / total
    g = g[(g.time >= g.time.max() - a.core_days * DAY) & (g.winner > 0) & (g.r1 > 0) & (g.r2 > 0)]
    rec: dict[str, list] = {}
    own: dict[str, list] = {}
    vs: dict[str, dict[str, list]] = {}
    beats: dict[str, dict[str, list]] = {}
    for t1, t2, r1, r2, w in zip(g.team1, g.team2, g.r1, g.r2, g.winner, strict=True):
        for team, opp, r, ro, won in ((t1, t2, r1, r2, w == 1), (t2, t1, r2, r1, w == 2)):
            if r < a.meta_elo:
                continue
            m = won - 1 / (1 + 10 ** ((ro - r) / 400))
            mine, theirs = arch(team), arch(opp)
            for k in mine:
                x = rec.setdefault(k, [0, 0, 0.0])
                x[0], x[1], x[2] = x[0] + 1, x[1] + won, x[2] + m
            y = vs.setdefault(mine[0], {}).setdefault(theirs[0], [0, 0.0])
            y[0], y[1] = y[0] + 1, y[1] + m
            for s in team.split("|"):
                o = own.setdefault(s, [0, 0.0])
                o[0], o[1] = o[0] + 1, o[1] + m
            for k in theirs:  # (the species against archetype k: this side's margin)
                for s in team.split("|"):
                    z = beats.setdefault(k, {}).setdefault(s, [0, 0.0])
                    z[0], z[1] = z[0] + 1, z[1] + m
    avg = sum(o[1] for o in own.values()) / max(sum(o[0] for o in own.values()), 1)
    idx = {s: i for i, s in enumerate(mm.species)}
    cands = [s for s, v in base.items() if v >= 0.01 and s in idx]
    out = {}
    for k in (*A.STYLES, *A.FEATURES):
        if k not in rec:
            continue
        n, won, m = rec[k]
        exp = {s: v / max(share[k], 1e-9) for s, v in mons.get(k, {}).items() if s in idx}
        members = sorted(exp.items(), key=lambda kv: -kv[1])[:12]
        logit = {c: sum(e * float(mm.M[idx[c], idx[t]]) for t, e in exp.items()) for c in cands}
        ans = []
        for c in sorted(cands, key=lambda c: -logit[c])[:10]:
            z, o = beats.get(k, {}).get(c, [0, 0.0]), own.get(c, [1, 0.0])
            lift = (z[1] - z[0] * o[1] / o[0]) / (z[0] + a.arch_prior)
            ans.append([c, round(logit[c], 3), round(lift, 4), z[0]])
        out[k] = {"share": round(share.get(k, 0.0), 4), "games": n, "win": round(won / n, 4),
                  "margin": round(m / n - avg, 4),
                  "members": [[s, round(e, 3), round(e / base[s], 2)] for s, e in members], "answers": ans}  # fmt: skip
    return {"model": model, "agreement": {"rules": A.agreement(rows), "model": A.agreement(rows, model)},
            "stats": out, "metagame": [arch(k) for k in meta.index], "vs": {k: {o: [n, round(m / n - avg, 4)] for o, (n, m) in v.items()} for k, v in vs.items()}}  # fmt: skip


CANDIDATE = paths.TEAM_DATA / "knowledge" / "candidate.json.gz"


def args(argv: list[str] | None = None) -> argparse.Namespace:
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
    ap.add_argument(
        "--arch-prior", type=int, default=500, help="an answer's games' evidence: shrunk by these"
    )
    ap.add_argument("--out", default=str(CANDIDATE))
    return ap.parse_args(argv)


def showdown_commit() -> str:
    import subprocess

    from alpha_poke.teams.validate import SIM

    r = subprocess.run(["git", "-C", str(SIM.parents[1]), "log", "-1", "--format=%h %cs"],
                       capture_output=True, text=True)  # fmt: skip
    return r.stdout.strip()


def build(a: argparse.Namespace, log=print) -> dict:
    from alpha_poke.teams.validate import banned_species, check

    g = brt.all_games()
    _, plain = model_of(g, a.since, synergy=False)
    model, val = model_of(g, a.since, synergy=True)
    val["val_logloss_without_synergy"] = plain["val_logloss"]
    log("model:", {k: round(v, 4) if isinstance(v, float) else v for k, v in val.items()})
    meta = brt.metagame(g, a)
    month, smog, chaos = smogon()
    m = compact_model(model, g, a.top)
    names = {s for k in meta.index for s in k.split("|")} | set(m["species"][:-1]) | set(smog)
    banned = banned_species(sorted(names))
    log(
        f"not in OU today: {len(banned)} species of {len(names)} --",
        ", ".join(sorted(banned))[:300],
    )
    legal = lambda key: not any(s in banned for s in key.split("|"))  # noqa: E731
    before = float(meta.sum())
    meta = meta[[legal(k) for k in meta.index]]
    log(
        f"metagame: {1 - float(meta.sum()) / before:.2%} of its weight had a banned species (dropped)"
    )
    meta = meta.head(a.meta_teams)
    smog = {k: v for k, v in smog.items() if k not in banned}
    tlt_args = argparse.Namespace(
        days=60, half_life=14.0, min_elo=a.min_elo, min_n=8, min_players=5, prior=20
    )
    lad, _ = tlt.ranked(tlt_args)
    lad = lad[[legal(k) for k in lad.index]].head(a.ladder)
    forum = [
        e for e in catalog.load(dedup=True) if e.complete
    ]  # (one per family of near-duplicates)
    problems = check([e.text for e in forum])
    dropped = [e for e, r in zip(forum, problems, strict=True) if r["problems"]]
    forum = [e for e, r in zip(forum, problems, strict=True) if not r["problems"]]
    log(f"forum: {len(dropped)} complete teams no longer legal (dropped), {len(forum)} kept")
    snap = {
        "built": time.strftime("%Y-%m-%d"),
        "sources": {"games_to": time.strftime("%Y-%m-%d", time.gmtime(int(g.time.max()))),
                    "meta_days": a.meta_days, "meta_elo": a.meta_elo, "smogon_month": month,
                    "core_days": a.core_days, "forum_teams": len(forum), "model_val": val,
                    "showdown": showdown_commit()},
        "banned": banned,
        "model": m,
        "threats": threat_builds(meta, a.threats, a.threat_share),
        "metagame": [[k, round(float(w), 4)] for k, w in meta.items()],
        "smogon": smog,
        "archetypes": archetype_stats(g, meta, chaos, a, forum, model),
        "cores": {k: v for k, v in cores(g, a.core_days, a.meta_elo, a.core_min, set(m["species"])).items()
                  if legal(k)},
        "forum": [{"key": e.key, "text": e.text, "date": e.date} for e in forum],
        "ladder": [{"key": k, "games": int(r.n), "win": round(float(r.win), 4), "margin": round(float(r.margin), 4),
                    "players": int(r.players)} for k, r in lad.iterrows()],
    }  # fmt: skip
    log(f"{len(m['species'])} species, {len(snap['metagame'])} compositions, {len(snap['threats'])} threats, "
        f"{len(snap['cores'])} cores, {len(forum)} forum teams, {len(snap['ladder'])} ladder teams")  # fmt: skip
    return snap


def write(snap: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(
        gzip.compress(json.dumps(snap, separators=(",", ":"), default=float).encode(), 9)
    )


def main() -> None:
    a = args()
    write(build(a), Path(a.out))
    print(
        f"{a.out}: {Path(a.out).stat().st_size // 1024} KB (scripts/knowledge.py validate, then promote)"
    )


if __name__ == "__main__":
    main()
