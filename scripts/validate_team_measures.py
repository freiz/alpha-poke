"""Which team measure predicts our bot's results (2026-10-28; doc/team_design.md)? Stage 2's games
(scripts/sim_team_pool.py's log) against stage 1's measures (build_robust_teams: the matchup
model's expected score, CVaR, robust) and threat_check's (threats with no answer / one answer,
usage-weighted; role slots lacking):

  per team: the bot's score (its share of the games won) and its own worst tail (the score
    against its worst --tail of the opponents, pair by pair) beside each measure; Spearman rank
    correlations of the measures with the score;
  per (team, opponent) pair: the matchup model's prediction against the pair's result (log loss,
    correlation) -- does the model see matchups at all?

  uv run python scripts/validate_team_measures.py --pool data/derived/teams/pools/teamsim_<...> \\
      --candidates data/derived/teams/pools/sim_candidates_v2 --threats <threat_check --out json>
"""

import argparse
import glob
import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_robust_teams import all_games, metagame, score  # noqa: E402

from alpha_poke import paths  # noqa: E402
from alpha_poke.eval.arena import read_log  # noqa: E402
from alpha_poke.teams.validate import check  # noqa: E402


def species(text: str) -> list[str]:
    """Preview species of an export (as the lite tables write them)."""
    from alpha_poke.teams.replay_pool import PREVIEW_FORMS

    preview = {v: k for k, v in PREVIEW_FORMS.items()}  # (Zamazenta -> Zamazenta-*, as the tables)
    res = check([text])[0]
    names = [
        b.split("\n")[0].split(" @ ")[0].split(" (")[0].strip()
        for b in res["text"].strip().split("\n\n")
    ]
    return [preview.get(x, x) for x in names]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True, help="sim_team_pool's pair pool (teamsim_...)")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--threats", default="", help="threat_check --out JSON")
    ap.add_argument("--log", default="", help="the arena log (default: the newest teamsim log)")
    ap.add_argument("--tail", type=float, default=0.2)
    ap.add_argument("--model", default="", help="matchup model pickle (default: the newest)")
    a = ap.parse_args()

    pool, cands = Path(a.pool), Path(a.candidates)
    log = a.log or sorted(glob.glob("data/eval/teamsim/*.jsonl"))[-1]
    names = sorted(json.loads((cands / "index.json").read_text()))
    index = json.loads((cands / "index.json").read_text())
    n_opp = len(list(pool.glob("pair*_a.txt"))) // len(names)
    # per (team, opponent): the finalist's score over the pair's games
    pair = defaultdict(list)
    for r in read_log(log):
        if r.get("a_won") is None:
            continue
        k = r["pair"]
        mine = r["team_a"].endswith("_a")
        pair[k].append(1.0 if r["a_won"] == mine else 0.0)
    rows = []
    for k, v in pair.items():
        i, j = divmod(k, n_opp)
        rows.append({"team": names[i], "opp": j, "score": float(np.mean(v)), "games": len(v)})
    df = pd.DataFrame(rows)

    # stage 1's measures for every candidate, on the cached model and the recent metagame
    ns = argparse.Namespace(
        meta_days=21, meta_half_life=14.0, meta_elo=1500, meta_teams=5000, tail=a.tail, threats=15
    )
    cache = a.model or sorted(glob.glob(str(paths.TEAM_DATA / "matchup_model_*.pkl")))[-1]
    model, _ = pickle.loads(Path(cache).read_bytes())
    meta = metagame(all_games(log=lambda *x: None), ns)
    st1 = score(model, [index[n] for n in names], meta, ns)

    # the model on each simulated pair
    opp_sp = {j: species((pool / f"pair{j:03d}_b.txt").read_text()) for j in range(n_opp)}
    df["pred"] = [
        model.win(index[t].split("|"), opp_sp[j]) for t, j in zip(df.team, df.opp, strict=True)
    ]
    full = df[df.games == 2]
    eps = 1e-6
    ll = -np.mean(
        full.score * np.log(full.pred + eps) + (1 - full.score) * np.log(1 - full.pred + eps)
    )
    print(f"pairs: {len(full)} complete; model vs result: corr {np.corrcoef(full.pred, full.score)[0, 1]:+.3f}, "
          f"log loss {ll:.4f} (0.5 everywhere: {np.log(2):.4f})")  # fmt: skip

    threats = json.loads(Path(a.threats).read_text()) if a.threats else {}
    out = []
    for n in names:
        d = df[df.team == n]
        s = d.score.to_numpy()
        tail = np.sort(s)[: max(1, int(len(s) * a.tail))].mean() if len(s) else float("nan")
        t1 = st1.loc[index[n]]
        th = next(
            (
                v
                for k, v in threats.items()
                if Path(k).stem == n and Path(k).parent.name == cands.name
            ),
            None,
        )
        out.append({"name": n, "team": index[n], "bot_score": round(s.mean(), 4) if len(s) else None,
                    "bot_tail": round(float(tail), 4), "games": int(d.games.sum()),
                    "mean": round(t1["mean"], 4), "cvar": round(t1.cvar, 4), "robust": round(t1.robust, 4),
                    "none": len(th["unanswered"]) if th else None, "one": len(th["single"]) if th else None,
                    "roles_lacking": len(th["lacking"]) if th else None})  # fmt: skip
    res = pd.DataFrame(out).sort_values("bot_score", ascending=False)
    print(res.drop(columns=["name"]).to_string(index=False))
    print("Spearman with the bot's score:")
    for m in ("mean", "cvar", "robust", "none", "one", "roles_lacking", "bot_tail"):
        if res[m].notna().all():
            print(f"  {m:14s} {res[m].rank().corr(res.bot_score.rank()):+.3f}")
    n_g = res.games.mean()
    print(
        f"(each team's score: about +-{1.96 * 0.5 / np.sqrt(max(n_g, 1)):.3f} at {n_g:.0f} games)"
    )


if __name__ == "__main__":
    main()
