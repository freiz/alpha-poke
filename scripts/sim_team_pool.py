"""Stage 2 of the ladder bot's teams (after scripts/build_robust_teams.py; 2026-10-28): every
finalist played by our bot against the same --opponents teams of the current ladder (real games'
sides completed by the belief, as self-play's: selfplay.teams.TeamSampler, no catalog / synthetic
sides), the current network on both sides (GPU batched search, --iterations per decision); each
(finalist, opponent) pair twice with the bots exchanged, so the network cancels and what is left
is the team -- in our bot's hands. The --keep best (by the finalist's score) -> --out.

  uv run python scripts/sim_team_pool.py --opponents 100 --keep 5

Local servers only; needs the GPU (not with self-play running).
"""

import argparse
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path

from alpha_poke.teams import POOLS_DIR, load_team_files


def recent_opponents(ts, a) -> list[str]:
    """--opponents teams of the recent ladder (2026-10-28: the metagame moved in October): sides of
    the crawler's replays of the last --opp-days by players >= --opp-elo, completed by the belief
    as self-play's replay sides (TeamSampler.complete), validated."""
    import glob
    import gzip
    import random

    from alpha_poke.replay.parser import parse_replay
    from alpha_poke.teams.validate import check

    games = []
    for f in glob.glob("data/replays/gen9ou/*.json.gz"):
        try:
            d = json.loads(gzip.open(f).read())
        except (OSError, ValueError):
            continue
        if d.get("uploadtime"):
            games.append(d)
    newest = max(d["uploadtime"] for d in games)
    games = [d for d in games if d["uploadtime"] >= newest - a.opp_days * 86400]
    rng = random.Random(a.seed)
    rng.shuffle(games)
    texts = []
    for d in games:
        if len(texts) >= 2 * a.opponents:  # (some fail the validator)
            break
        try:
            rep = parse_replay(d)
        except Exception:
            continue
        if rep.warnings:
            continue
        for s in ("p1", "p2"):
            recs = [m for m in rep.teams[s] if not m.phantom]
            if len(recs) != 6 or (rep.ratings_before.get(s) or 0) < a.opp_elo:
                continue
            text = ts._try_complete(recs)
            if text:
                texts.append(text)
    out = [r["text"] for r in check(texts) if r["n"] == 6 and not r["problems"]][: a.opponents]
    print(
        f"{len(out)} recent ladder opponents ({len(games)} games of the last {a.opp_days} days)",
        flush=True,
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=str(POOLS_DIR / "robust_candidates"))
    ap.add_argument("--opponents", type=int, default=100, help="ladder teams each finalist meets")
    ap.add_argument(
        "--since", type=int, default=1754006400, help="opponents' games from (2025-08-01)"
    )
    ap.add_argument("--iterations", type=int, default=1600)
    ap.add_argument("--opp-days", type=int, default=21, help="opponents: the crawler's last N days")
    ap.add_argument("--opp-elo", type=int, default=1500)
    ap.add_argument("--keep", type=int, default=5)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--lanes", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--model", default=None, help="network (default: the current one)")
    ap.add_argument("--out", default=str(POOLS_DIR / "ladder_robust"))
    a = ap.parse_args()

    model = a.model or json.loads(Path("data/selfplay/state.json").read_text())["current"]
    from alpha_poke.selfplay.batcher import ml_for

    os.environ.update({"ALPHA_MODEL_A": model, "ALPHA_MODEL_B": model, "ALPHA_ML_A": ml_for(model),
                       "ALPHA_ML_B": ml_for(model), "ALPHA_SEARCH_ITERATIONS": str(a.iterations),
                       "ALPHA_GPU_COMPILE": "1"})  # fmt: skip
    cands_dir = Path(a.candidates)
    names = sorted(load_team_files(cands_dir))
    texts = {n: (cands_dir / f"{n}.txt").read_text() for n in names}
    meta = json.loads((cands_dir / "meta.json").read_text())

    # the opponents: the current ladder's teams (both sides of sampled real games)
    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay.teams import TeamSampler

    ts = TeamSampler(
        BeliefModel.load(), since=a.since, catalog_frac=0.0, synth_frac=0.0, seed=a.seed
    )
    opps = recent_opponents(ts, a)

    pool = Path("data/teams/pools") / f"teamsim_{time.strftime('%Y%m%d_%H%M')}"
    pool.mkdir(parents=True)
    index = {}
    for i, n in enumerate(names):
        for j, o in enumerate(opps):
            k = i * len(opps) + j
            (pool / f"pair{k:03d}_a.txt").write_text(texts[n])
            (pool / f"pair{k:03d}_b.txt").write_text(o)
            index[k] = n
    print(f"{len(names)} finalists x {len(opps)} opponents = {len(index)} pairs, {2 * len(index)} games "
          f"({model}, {a.iterations} iterations) -> {pool}", flush=True)  # fmt: skip

    from alpha_poke.eval.arena import read_log, run_arena

    res = run_arena("g_ma", "g_mb", 0, pool_dir=str(pool), ports=(8000, 8001, 8002, 8003), procs=a.procs,
                    lanes_per_proc=a.lanes, seed=a.seed, log_dir="data/eval/teamsim", pairs=True)  # fmt: skip
    won, games = defaultdict(float), defaultdict(int)
    for r in read_log(res["log"]):
        if r.get("a_won") is None:
            continue
        n = index[r["pair"]]
        mine = r["team_a"].endswith("_a")  # (bot A held the finalist in this game)
        won[n] += (1.0 if r["a_won"] == mine else 0.0) if r["a_won"] in (True, False) else 0.5
        games[n] += 1
    by_team = {m["team"]: m for m in meta.get("teams", [])}
    stage1 = (
        json.loads((cands_dir / "index.json").read_text())
        if (cands_dir / "index.json").exists()
        else {}
    )
    table = []
    for n in names:
        p = won[n] / max(games[n], 1)
        ci = 1.96 * math.sqrt(p * (1 - p) / max(games[n], 1))
        comp = stage1.get(n, "")
        table.append({"name": n, "team": comp, "score": round(p, 4), "ci95": round(ci, 4), "games": games[n],
                      "stage1": by_team.get(comp, {})})  # fmt: skip
    table.sort(key=lambda x: -x["score"])
    for t in table:
        s1 = t["stage1"]
        print(f"  {t['score']:.3f} +- {t['ci95']:.3f} ({t['games']} games; stage 1 robust {s1.get('robust')}) "
              f"{t['team']}", flush=True)  # fmt: skip
    from alpha_poke.teams import catalog

    keep = table[: a.keep]
    catalog.write_pool(Path(a.out), [(t["team"], texts[t["name"]]) for t in keep],
                       {"kind": "ladder robust (simulated)", "candidates": str(cands_dir), "model": model,
                        "iterations": a.iterations, "opponents": len(opps), "log": res["log"], "table": table})  # fmt: skip
    print(f"{len(keep)} teams -> {a.out}")


if __name__ == "__main__":
    main()
