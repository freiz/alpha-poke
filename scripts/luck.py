"""Offline check of luck-corrected game outcomes (AIVAT-style control variate) on self-play
games: how much of the outcome's variance is chance (damage rolls aside: crits, accuracy,
secondary effects, speed ties, ... as the search's transition model branches).

Per turn where both players chose at the turn start (each one's record gives its own side
exactly; together: the full-information state s), the engine's chance outcomes of the played
move pair give E = sum p_i V(s_i); the outcome that happened is the branch closest to what the
next record(s) show. luck = V(that branch) - E has mean zero whatever V is (given the moves), so
outcome - sum(luck) estimates the same expected score with less variance the better V is.
V = the value network (side one's view, side one's context), 1 / 0 at a decided battle.

  uv run python scripts/luck.py --gen 1 --games 500
"""

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import alpha_search
import numpy as np

KIND_MAIN = 0


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def mon_key(m) -> str:
    return m[0]


def distance(branch, obs, own_is_one: bool) -> float:
    """How far the branch (full information) is from what one player's record shows."""
    own_b, opp_b = (branch[0], branch[1]) if own_is_one else (branch[1], branch[0])
    own_o, opp_o = obs[0], obs[1]
    d = 0.0
    # own side: exact, same order
    for mb, mo in zip(own_b[1], own_o[1], strict=False):
        d += abs(mb[1] / max(mb[2], 1) - mo[1] / max(mo[2], 1)) + (mb[3] != mo[3])
    boosts = sum(abs(x - y) for x, y in zip(own_b[2], own_o[2], strict=True))
    d += 2 * (own_b[0] != own_o[0]) + 0.2 * boosts
    # the opponent's side as seen: by species (unrevealed mons are sampled: skipped)
    seen = {mon_key(m): m for m in opp_o[1]}
    for mb in opp_b[1]:
        mo = seen.get(mon_key(mb))
        if mo is not None:
            d += abs(mb[1] / max(mb[2], 1) - mo[1] / max(mo[2], 1)) + (mb[3] != mo[3])
    act_b, act_o = opp_b[1][opp_b[0]][0], opp_o[1][opp_o[0]][0]
    boosts = sum(abs(x - y) for x, y in zip(opp_b[2], opp_o[2], strict=True))
    d += 2 * (act_b != act_o) + 0.2 * boosts
    return d


def next_obs(recs: dict, side: str, i: int):
    lst = recs[side]
    return lst[i + 1] if i + 1 < len(lst) else None


def game_luck(game: dict, decs: list, model: str, stats: dict, branch: bool,
              sym: bool = False) -> dict | None:  # fmt: skip
    recs = defaultdict(list)
    for d in decs:
        recs[d["side"]].append(d)
    for lst in recs.values():
        lst.sort(key=lambda d: (d["turn"], d["kind"] != KIND_MAIN, d["kind"]))
    if set(recs) != {"p1", "p2"}:
        return None
    a_is_p1 = game["a_side"] == "p1"
    won_p1 = game["a_won"] if a_is_p1 else not game["a_won"]
    idx = {s: {(d["turn"], d["kind"]): i for i, d in enumerate(recs[s])} for s in recs}
    steps = []
    for (turn, kind), i1 in idx["p1"].items():
        if kind != KIND_MAIN or (turn, KIND_MAIN) not in idx["p2"]:
            continue
        i2 = idx["p2"][(turn, KIND_MAIN)]
        r1, r2 = recs["p1"][i1], recs["p2"][i2]
        n1, n2 = next_obs(recs, "p1", i1), next_obs(recs, "p2", i2)
        # the observation right after the turn's chance step: the earliest next record(s)
        cands = [(s, n) for s, n in (("p1", n1), ("p2", n2)) if n is not None]
        if not cands:
            stats["no_next"] += 1  # the battle ended this turn: the outcome is known exactly
            obs = []
        else:
            order = {s: (n["turn"], n["kind"] == KIND_MAIN) for s, n in cands}
            first = min(order.values())
            obs = [(s, n) for s, n in cands if order[s] == first]
            if len(obs) == 2 and obs[0][1]["kind"] != obs[1][1]["kind"]:
                stats["ambiguous"] += 1
                continue
        s = alpha_search.merge_sides(r1["state"], r2["state"])
        try:
            outs = alpha_search.chance_outcomes(s, r1["slot"], r2["slot"], branch)
        except ValueError:
            stats["no_option"] += 1
            continue
        steps.append((r1, s, outs, obs))
    if not steps:
        return None
    # values of every branch (one batched call)
    flat, ctx = [], []
    for r1, s, outs, _ in steps:
        flat.append(s)
        ctx.append(r1)
        for _, st, _ in outs:
            flat.append(st)
            ctx.append(r1)
    args = (model, flat, [c["reveal"] for c in ctx], [tuple(c["ratings"]) for c in ctx],
            [c["ctx_turn"] for c in ctx], [c["history"] for c in ctx])  # fmt: skip
    _, logits = alpha_search.tnet_forward(*args)
    if sym:  # both views: side one's value and one minus side two's (same context)
        _, lf = alpha_search.tnet_forward(*args, flip=True)
        logits = [-math.log(1 / (0.5 * (sigmoid(x) + 1 - sigmoid(y))) - 1)
                  for x, y in zip(logits, lf, strict=True)]  # fmt: skip
    k = 0
    luck, v0 = 0.0, None
    for _r1, _s, outs, obs in steps:
        v_root = sigmoid(logits[k])
        k += 1
        vals = []
        for _p, _st, over in outs:
            vals.append(1.0 if over > 0 else 0.0 if over < 0 else sigmoid(logits[k]))
            k += 1
        v0 = v_root if v0 is None else v0
        stats["v_root"].append((v_root, float(won_p1)))
        if len(outs) == 1:
            stats["single"] += 1
            continue
        probs = np.array([p for p, _, _ in outs])
        e = float(probs @ np.array(vals))
        if obs:
            infos = alpha_search.describe([st for _, st, _ in outs])
            obs_infos = alpha_search.describe([n["state"] for _, n in obs])
            pairs = list(zip(obs, obs_infos, strict=True))
            dist = [sum(distance(b, oi, s == "p1") for (s, _), oi in pairs) for b in infos]
            j = int(np.argmin(dist))
            stats["dist"].append(dist[j])
            ranked = sorted(dist)
            stats["margin"].append(ranked[1] - ranked[0])
        else:  # the battle ended: the decided branch on the winner's side
            ends = [i for i, (_, _, o) in enumerate(outs) if o != 0 and (o > 0) == won_p1]
            if not ends:
                stats["end_unmatched"] += 1
                continue
            j = max(ends, key=lambda i: outs[i][0])
        stats["steps"] += 1
        stats["luck_steps"].append(vals[j] - e)
        luck += vals[j] - e
    # the players' own sampling (tau = 1 over the visits): Q(played) - E_pi[Q], in p1's terms
    act = 0.0
    for side, sign in (("p1", 1.0), ("p2", -1.0)):
        for d in recs[side]:
            opts = [i for i, v in enumerate(d["visits"]) if v > 0 and d["names"][i]]
            if len(opts) < 2:
                continue
            w = np.array([d["visits"][i] for i in opts], float)
            q = np.array([d["mean"][i] for i in opts])
            act += sign * (d["mean"][d["slot"]] - float(w @ q) / w.sum())
    return {"won": float(won_p1), "luck": luck, "act": act, "v0": v0, "turns": game["turns"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, default=1)
    ap.add_argument("--games", type=int, default=500)
    ap.add_argument("--model", default="data/train/v5/runs/v5-glu")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--sym", action="store_true", help="value: mean of both views")
    ap.add_argument("--branch", action="store_true", help="also branch on damage rolls")
    a = ap.parse_args()
    gen_dir = Path(f"data/selfplay/gen{a.gen}")
    games = {}
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in f.read_text().splitlines():
            g = json.loads(line)
            if not g["capped"] and g["a_won"] is not None:
                games[g["pair"]] = g
    pick = set(random.Random(a.seed).sample(sorted(games), min(a.games, len(games))))
    decs = defaultdict(list)
    for f in gen_dir.glob("decisions-w*.jsonl"):
        for line in f.read_text().splitlines():
            if '"game": ' in line:
                d = json.loads(line)
                if d["game"] in pick:
                    decs[d["game"]].append(d)
    stats: dict = defaultdict(int) | {"dist": [], "margin": [], "luck_steps": [], "v_root": []}
    stats = defaultdict(int, stats)
    res = []
    for n, p in enumerate(sorted(pick)):
        r = game_luck(games[p], decs[p], a.model, stats, a.branch, a.sym)
        if r is not None:
            res.append(r)
        if (n + 1) % 100 == 0:
            print(f"{n + 1} games", flush=True)
    won = np.array([r["won"] for r in res])
    luck = np.array([r["luck"] for r in res])
    v0 = np.array([r["v0"] for r in res])
    act = np.array([r["act"] for r in res])
    corr = won - luck
    both = won - luck - act
    # the best weights (in-sample regression: how much a better-scaled correction could give)
    x = np.stack([luck, act], 1)
    beta = np.linalg.lstsq(x - x.mean(0), won - won.mean(), rcond=None)[0]
    ls = np.array(stats["luck_steps"])
    out = {
        "games": len(res), "steps": stats["steps"], "single_outcome_steps": stats["single"],
        "skipped": {k: stats[k] for k in ("ambiguous", "no_option", "end_unmatched")},
        "mean_won": won.mean(), "mean_corrected": corr.mean(),
        "luck_per_step_mean": ls.mean(), "luck_per_step_se": ls.std() / math.sqrt(len(ls)),
        "luck_per_game_mean": luck.mean(), "luck_per_game_se": luck.std() / math.sqrt(len(luck)),
        "var_won": won.var(), "var_corrected": corr.var(),
        "var_ratio": corr.var() / won.var(),
        "act_per_game_mean": act.mean(), "act_per_game_se": act.std() / math.sqrt(len(act)),
        "var_action_corrected": (won - act).var(), "var_both": both.var(),
        "var_ratio_both": both.var() / won.var(),
        "beta": [round(float(b), 3) for b in beta],
        "var_ratio_fitted": (won - x @ beta).var() / won.var(),
        # the team matchup / start removed (what pairing removes): V at the first turn
        "var_won_minus_v0": (won - v0).var(), "var_corrected_minus_v0": (corr - v0).var(),
        "corr_luck_won": float(np.corrcoef(luck, won)[0, 1]),
        # how well V predicts the outcome along the game (turn-start states)
        "v_bce": float(np.mean([-math.log(max(v if w else 1 - v, 1e-6))
                                for v, w in stats["v_root"]])),
        "v_corr": float(np.corrcoef(np.array(stats["v_root"]).T)[0, 1]),
        "match_dist_median": float(np.median(stats["dist"])),
        "match_dist_p90": float(np.percentile(stats["dist"], 90)),
        "match_margin_median": float(np.median(stats["margin"])),
        "match_margin_lt_0.05": float(np.mean(np.array(stats["margin"]) < 0.05)),
    }  # fmt: skip
    out = {k: round(v, 4) if isinstance(v, float) else v for k, v in out.items()}
    print(json.dumps(out, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
