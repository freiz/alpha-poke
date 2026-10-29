"""Choose a team against one specific opponent (design D5-O steps 3-4). Local servers only.

  1. candidates: the catalog's complete teams ranked by the matchup model (2M games, species
     strength + species-vs-species) against the opponent's recent teams; the top ``--k``
     distinct species sets, plus the median-ranked one as a control;
  2. the opponent's teams: their ``--his`` most weighted recent teams (recency half-life
     ``--half-life`` games), completed from everything they revealed across their games
     (personalized), the rest from Smogon (gen9ou-0), validated;
  3. simulation: our CPU search bot with each candidate vs a model of the opponent
     (``pol_r1100``: the network's policy at their rating and fitted temperature) with their
     teams drawn by weight; the same draws for every candidate (common random numbers);
     each round doubles the games; ``--keep half``: keep the better half (successive halving),
     ``--keep significant``: drop only candidates significantly worse than the leader (one-
     sided two-proportion test, p < 0.05) and stop once one is left.

Usage: ALPHA_SEARCH_MS=300 uv run python scripts/counter_team.py <user> [--k 12] [--bot pol]
(needs scripts/player.py fetch / play <user> first)
"""

import argparse
import json
import math
import multiprocessing as mp
import os
import random
import signal
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_poke.analysis.matchups import load_or_fit
from alpha_poke.analysis.roles import to_id
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats
from alpha_poke.eval.arena import Match, run_schedule
from alpha_poke.players import PLAYERS_DIR, games
from alpha_poke.teams import catalog
from alpha_poke.teams.catalog import write_pool
from alpha_poke.teams.replay_pool import build_set
from alpha_poke.teams.validate import check


def his_teams(gs, n: int, half_life: float) -> list[tuple[list[str], float]]:
    w: dict[tuple, float] = defaultdict(float)
    for j, g in enumerate(gs):
        w[tuple(sorted(g.team))] += 0.5 ** ((len(gs) - 1 - j) / half_life)
    top = sorted(w.items(), key=lambda x: -x[1])[:n]
    total = sum(x for _, x in top)
    return [(list(t), x / total) for t, x in top]


def complete(team: list[str], gs, stats: UsageStats) -> str:
    """Their sets: per species, the values they revealed in any game (most common), topped up
    from Smogon (``replay_pool.build_set``)."""
    sets = []
    for sp in team:
        rows = [g.sets[sp] for g in gs if sp in g.sets]
        df = pd.DataFrame({
            "item": [r["item"] for r in rows], "ability": [r["ability"] for r in rows],
            "tera_type": [r["tera"] for r in rows],
            "moves": ["|".join(r["moves"]) for r in rows],
        })  # fmt: skip
        sets.append(build_set(sp, df, stats, "top"))
    return "\n\n".join(sets)


def worse(x: list[float], best: list[float], z_crit: float = 1.645) -> bool:
    """Is the win rate of ``x`` significantly below ``best`` (one-sided two-proportion z test,
    p < 0.05)?"""
    n1, n2 = len(best), len(x)
    p1, p2 = sum(best) / n1, sum(x) / n2
    pp = (p1 * n1 + p2 * n2) / (n1 + n2)
    if pp in (0.0, 1.0):
        return False
    return (p1 - p2) / math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2)) > z_crit


def conclude(out: Path, meta: dict, bot: str, opp_bot: str, n: int) -> None:
    """Rank the candidates by their win rate in every game played so far by ``bot`` (with the
    candidate) vs ``opp_bot`` (with the opponent's teams), from the game log; candidates
    eliminated earlier have fewer games but are ranked the same way. The best ``n`` ->
    ``<player>/counter`` (a team pool: scripts/play_public.py --pool <that dir>)."""
    res: dict[str, list[float]] = defaultdict(list)
    for line in (out / "games.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["bot_a"] == bot and r["bot_b"] == opp_bot and r["a_won"] is not None:
            res[r["team_a"]].append(float(r["a_won"]))
    cands = {c["stem"]: c for c in meta["candidates"]}
    ranked = sorted((c for c in res if c in cands), key=lambda c: -np.mean(res[c]))
    print(f"ranking from {sum(map(len, res.values()))} games of {bot} vs {opp_bot}:")
    for c in ranked:
        print(f"  {c}: {np.mean(res[c]):.1%} ({len(res[c])} games) {cands[c]['key']}")
    pool = out / "pool"
    best = ranked[:n]
    write_pool(out.parent / "counter",
               [(cands[c]["key"], (pool / f"{c}.txt").read_text()) for c in best],
               {"chosen_by": f"scripts/counter_team.py ({bot} vs {opp_bot})",
                "teams": [{"from": c, "key": cands[c]["key"], "entry": cands[c]["entry"],
                           "win_rate": round(float(np.mean(res[c])), 4), "games": len(res[c])}
                          for c in best]})  # fmt: skip
    print(f"best {len(best)} -> {out.parent / 'counter'} (team_00 = best)")


def _stop_workers(*_) -> None:
    """On SIGTERM / Ctrl-C also stop the game worker processes (they would keep playing)."""
    for p in mp.active_children():
        p.terminate()
    raise SystemExit(1)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop_workers)
    ap = argparse.ArgumentParser()
    ap.add_argument("user")
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--his", type=int, default=8)
    ap.add_argument("--half-life", type=float, default=5.0)
    ap.add_argument("--first", type=int, default=40, help="games per candidate in round 1")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--lanes", type=int, default=2)
    ap.add_argument("--ports", type=int, nargs="+", default=[8000, 8001])
    ap.add_argument("--bot", default="s_ismcts_ma")
    ap.add_argument("--opp-bot", default="pol")
    ap.add_argument("--rating", type=int, help="the policy bots' rating input (default: fit)")
    ap.add_argument("--tau", type=float, help="their temperature (default: fit)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--keep", choices=["half", "significant"], default="half")
    ap.add_argument(
        "--conclude",
        action="store_true",
        help="play nothing: rank the candidates "
        "from the games already played by --bot vs --opp-bot and export",
    )
    ap.add_argument(
        "--export", type=int, default=2, help="best teams -> data/players/<user>/counter"
    )
    ap.add_argument(
        "--only",
        default="",
        help="play only these candidate stems (e.g. the "
        "finalists of an earlier run, with --bot s_ismcts_ma)",
    )
    a = ap.parse_args()
    uid = to_id(a.user)
    out = PLAYERS_DIR / uid / "sim"
    out.mkdir(parents=True, exist_ok=True)
    gs = games.load(a.user)
    his = his_teams(gs, a.his, a.half_life)
    # the opponent model: the rating input and temperature fit by scripts/player.py play
    fit = json.loads((PLAYERS_DIR / uid / "play.json").read_text())["best"]
    rating = a.rating if a.rating is not None else int(fit[0])
    tau = a.tau if a.tau is not None else float(fit[1])
    os.environ["ALPHA_POLICY_RATING"], os.environ["ALPHA_POLICY_TAU"] = str(rating), str(tau)
    print(f"opponent model: {a.opp_bot}, rating input {rating}, tau {tau}")
    model = load_or_fit(PLAYERS_DIR / "matchup_model.pkl")

    # 1. candidates
    by_key: dict[str, catalog.Entry] = {}
    for e in catalog.load():
        if e.complete:
            by_key.setdefault(e.key, e)
    scored = sorted(((sum(w * model.win(k.split("|"), t) for t, w in his), k) for k in by_key),
                    reverse=True)  # fmt: skip
    pick = scored[: a.k] + [scored[len(scored) // 2]]
    # 2. their teams
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-0.json")
    his_text = [complete(t, gs, stats) for t, _ in his]
    for (t, _), r in zip(his, check(his_text), strict=True):
        assert not r["problems"], (t, r["problems"])
    teams = [(k, by_key[k].text) for _, k in pick] + [("|".join(t), x) for (t, _), x in
                                                      zip(his, his_text, strict=True)]  # fmt: skip
    meta = {"candidates": [{"stem": f"team_{i:02d}", "key": k, "model_score": round(s, 4),
                            "entry": by_key[k].id, "control": i == a.k}
                           for i, (s, k) in enumerate(pick)],
            "his": [{"stem": f"team_{len(pick) + j:02d}", "key": "|".join(t), "weight": round(w, 4)}
                    for j, (t, w) in enumerate(his)]}  # fmt: skip
    pool = out / "pool"
    write_pool(pool, teams, meta)
    print(f"{len(pick)} candidates (last = control), {len(his)} of their teams -> {pool}")
    for c in meta["candidates"]:
        print(f"  {c['stem']} model {c['model_score']:.3f} {c['key']}")
    for h in meta["his"]:
        print(f"  {h['stem']} weight {h['weight']:.2f} {h['key']}")

    if a.conclude:
        conclude(out, meta, a.bot, a.opp_bot, a.export)
        return

    # 3. rounds of simulation
    log_path = str(out / "games.jsonl")
    alive = [c["stem"] for c in meta["candidates"]]
    if a.only:
        alive = [c for c in alive if c in a.only.split(",")]
    his_stems = [h["stem"] for h in meta["his"]]
    his_w = [h["weight"] for h in meta["his"]]
    results: dict[str, list[float]] = defaultdict(list)
    n = a.first
    for rnd in range(a.rounds):
        rng = random.Random(a.seed * 1000 + rnd)
        draws = rng.choices(his_stems, weights=his_w, k=n)  # the same for every candidate
        schedule = [Match(pair=i, game=0, team_a=c, team_b=h, a_challenges=i % 2 == 0)
                    for c in alive for i, h in enumerate(draws)]  # fmt: skip
        rows = run_schedule(a.bot, a.opp_bot, schedule, str(pool), log_path, tuple(a.ports),
                            a.procs, a.lanes)  # fmt: skip
        for r in rows:
            if r["a_won"] is not None:
                results[r["team_a"]].append(float(r["a_won"]))
        rank = sorted(alive, key=lambda c: -np.mean(results[c]))
        print(f"round {rnd + 1}: {n} games each")
        for c in rank:
            x = results[c]
            p = np.mean(x)
            print(f"  {c}: {p:.1%} ± {1.96 * math.sqrt(p * (1 - p) / len(x)):.1%} ({len(x)} games)")
        if a.keep == "half":
            alive = rank[: max(1, len(rank) // 2)]
        else:
            alive = [c for c in rank if not worse(results[c], results[rank[0]])]
            print(f"  kept (not significantly worse than {rank[0]}): {alive}")
        if len(alive) == 1:
            break
        n *= 2
    (out / f"result_{a.bot}.json").write_text(json.dumps(
        {"final": alive, "win_rates": {c: [float(np.mean(x)), len(x)] for c, x in results.items()},
         "meta": meta}, indent=1))  # fmt: skip
    print("final:", alive)
    conclude(out, meta, a.bot, a.opp_bot, a.export)


if __name__ == "__main__":
    main()
