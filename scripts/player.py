"""Models of one specific opponent, offline (design D5-O, steps 1-2). Public data only.

  fetch  <user>   search and download their public replays (data/players/<user id>/)
  teams  <user>   step 1: species-level team model (own frequency vs ladder usage, recency),
                  team repeats, personalized sets vs the generic belief; rolling-origin
  play   <user>   step 2: fit the network's rating input r and temperature tau to their
                  decisions (first 2/3 of the games by time), test on the rest

Usage: uv run python scripts/player.py teams <user> [--fmt gen9ou]
"""

import argparse
import json
import math

import numpy as np

from alpha_poke.analysis.roles import to_id
from alpha_poke.players import PLAYERS_DIR, games, play_model, team_model

START = 10  # rolling-origin evaluation from the 11th game on
HALF_DAYS = (3, 5, 7, 14, 30, 60, math.inf)
HALF_GAMES = (2, 3, 5, 8, 12, 20, math.inf)
KS = (0.0, 0.5, 1, 2, 4, 8)


def cmd_fetch(a) -> None:
    out = games.fetch(a.user)
    gs = games.load(a.user, a.fmt)
    print(f"{len(out)} public replays, {len(gs)} usable {a.fmt} games")


def cmd_teams(a) -> None:
    gs = games.load(a.user, a.fmt)
    print(f"{len(gs)} games; predicting games {START + 1}..{len(gs)} from the earlier ones")
    for cutoff in ("0", "1500"):
        base = team_model.ladder_usage(cutoff=cutoff)
        bits, rec = team_model.rolling_teams(gs, base, math.inf, math.inf, START)
        print(f"ladder usage gen9ou-{cutoff:4s}: {bits:6.2f} bits/species, recall@10 {rec:.0%}")
    base = team_model.ladder_usage(cutoff="0")
    grids = {}
    for unit, lives in (("games", HALF_GAMES), ("days", HALF_DAYS)):
        grid = grids[unit] = {}
        for h in lives:
            for k in KS:
                grid[(h, k)] = team_model.rolling_teams(gs, base, h, k, START, unit)
        best = max(grid, key=lambda x: grid[x][0])
        own = grid[(math.inf, 0.0)]
        bb, br = grid[best]
        print(f"[recency in {unit}] own frequency only (k=0, no recency): {own[0]:6.2f} "
              f"bits/species, recall@10 {own[1]:.0%}; best (half-life {best[0]} {unit}, k "
              f"{best[1]}): {bb:6.2f} bits/species, recall@10 {br:.0%}")  # fmt: skip
        print(f"  bits/species (rows: half-life in {unit}; columns: k)")
        print("        " + "".join(f"{k:>8}" for k in KS))
        for h in lives:
            print(f"{h!s:>7} " + "".join(f"{grid[(h, k)][0]:8.2f}" for k in KS))
    reps = team_model.repeats(gs, START)
    print(f"whole team used before: {reps['repeat']:.0%} of games; best overlap with an earlier "
          f"team (species in common: games): {reps['overlap']}")  # fmt: skip

    from alpha_poke.agents.belief_state import BeliefModel

    ks = [0.0, 0.5, 1.0, 2.0, 4.0, 8.0, math.inf]
    sets = team_model.rolling_sets(gs, BeliefModel.load(), ks, START)
    print("sets: generic belief (k = inf) vs personalized (prior weight k), log-lik (nats) / "
          "top-1 (item, tera) or recall in the top 4 (moves)")  # fmt: skip
    for f, d in sets.items():
        n = d[ks[0]][2]
        print(f"  {f:5s} ({n:3d} revealed): " + "  ".join(
            f"k={k}: {ll:.2f}/{acc:.0%}" for k, (ll, acc, _) in d.items()))  # fmt: skip
    rep = {"games": len(gs),
           "teams_grid": {u: {f"{h}|{k}": v for (h, k), v in g.items()} for u, g in grids.items()},
           "repeats": reps,
           "sets": {f: {str(k): v for k, v in d.items()} for f, d in sets.items()}}  # fmt: skip
    _save(a.user, "teams.json", rep)


def cmd_play(a) -> None:
    from alpha_poke.agents.belief_state import BeliefModel

    gs = games.load(a.user, a.fmt)
    belief = BeliefModel.load()
    pos = play_model.decisions(gs, belief)
    opp = play_model.decisions(gs, belief, side="opponent")
    cut = int(len(gs) * 2 / 3)
    fit = np.array([gi < cut for gi, _ in pos])
    act = np.array([p.action for _, p in pos])
    act_o = np.array([p.action for _, p in opp])
    print(f"{len(gs)} games: {len(pos)} of the player's decisions ({fit.sum()} fit / "
          f"{(~fit).sum()} test: games {cut + 1}..{len(gs)}), "
          f"{len(opp)} of their opponents'")  # fmt: skip
    ratings = [None, 0] + list(range(900, 2201, 100))
    taus = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]
    lgs = {r: play_model.logits(a.run, pos, r) for r in ratings}
    # the chosen action must be legal in the rebuilt state (a few edge cases are not)
    ok = np.isfinite(lgs[None][np.arange(len(act)), act])
    print(f"left out {(~ok).sum()} decisions whose action is illegal in the rebuilt state")
    lgs = {r: v[ok] for r, v in lgs.items()}
    act, fit = act[ok], fit[ok]
    table = {}
    for r in ratings:
        for t in taus:
            ll, top = play_model.scores(lgs[r], act, t)
            table[(r, t)] = (ll[fit].mean(), ll[~fit].mean(), top[fit].mean(), top[~fit].mean())
    best = max((k for k in table if k[0] is not None), key=lambda k: table[k][0])

    def row(name, k):
        f, te, a1, a2 = table[k]
        return f"  {name:34s} fit {-f:.3f}  test {-te:.3f} nats/decision; top-1 {a1:.0%} / {a2:.0%}"

    print("cross-entropy of the player's actions (lower = better explained):")
    print(row("rating of the game, tau 1", (None, 1.0)))
    print(row("rating unknown, tau 1", (0, 1.0)))
    print(row(f"fit: rating {best[0]}, tau {best[1]}", best))
    print("by rating input (tau fit per rating; fit-set cross-entropy):")
    for r in ratings[1:]:
        t = max(taus, key=lambda t, r=r: table[(r, t)][0])
        print(f"  {r!s:>5}: tau {t:<5} {-table[(r, t)][0]:.3f}")
    lg_o = play_model.logits(a.run, opp, None)
    ok_o = np.isfinite(lg_o[np.arange(len(act_o)), act_o])
    ll_o, top_o = play_model.scores(lg_o[ok_o], act_o[ok_o], 1.0)
    print(f"reference, their opponents (rating of the game, tau 1): {-ll_o.mean():.3f} nats, "
          f"top-1 {top_o.mean():.0%}")  # fmt: skip
    _save(a.user, "play.json", {"fit_games": cut, "best": list(best),
                                "table": {f"{r}|{t}": v for (r, t), v in table.items()},
                                "opponents": [float(-ll_o.mean()), float(top_o.mean())]},
          )  # fmt: skip


def _save(user: str, name: str, obj) -> None:
    path = PLAYERS_DIR / to_id(user) / name
    path.write_text(json.dumps(obj, indent=1, default=float))
    print(f"-> {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("fetch", cmd_fetch), ("teams", cmd_teams), ("play", cmd_play)):
        p = sub.add_parser(name)
        p.add_argument("user")
        p.add_argument("--fmt", default="gen9ou")
        p.add_argument("--run", default="data/train/v5/runs/v5-final")
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
