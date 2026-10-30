"""Gen 9 OU ladder games on the OFFICIAL Showdown server, one at a time (2026-10-27): the bot's
strength against humans. The bot account must be registered as a bot (the PS bot policy, 2026-10:
/ht -> "Something else" -> "I want to register my bot"; an unregistered bot is bannable).

  uv run python scripts/ladder.py --public --n 20            # official server, 20 ladder games
  uv run python scripts/ladder.py --n 2                      # dry run: local server, a local
                                                             # heuristic bot ladders against it

Safety: connects to the official server only with --public, logs in with the bot account from
.env (PS_BOT_USERNAME / PS_BOT_PASSWORD; never printed), only searches for ladder games one at a
time, never challenges anyone, never accepts challenges, never joins rooms, never sends chat;
exits after --n games, or after the current game once data/ladder/STOP exists. Light on the
machine: CPU search (--threads, default 2, at nice 10), no GPU.

The bot: ISMCTS + the network (--model, default the self-play's current network), --search-ms
per decision (default 5,000), the moves-left term. Its team: a random team of --pool each game
(default ladder_robust: the team-design pipeline's stage 2 -- our bot's best teams against
the recent ladder, doc/team_design.md), the ones the local
validator passes. Every game's result, turns, ratings (as shown at the game's start: before it)
and team: data/ladder/<date>/games.jsonl (dry runs: data/ladder/dryrun/<date>/); replays and
decision traces next to it.
"""

import argparse
import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path

from alpha_poke import paths
from alpha_poke.selfplay.runner import MODEL
from alpha_poke.servers import account, local_server, public_account, public_server
from alpha_poke.teams import load_team_files

OUT = Path("data/ladder")
STOP = OUT / "STOP"


def current_network() -> str:
    """The self-play loop's current network (data/selfplay/state.json); without a self-play
    run, the released one (selfplay.runner.MODEL, scripts/fetch_model.py)."""
    state = Path("data/selfplay/state.json")
    return json.loads(state.read_text(encoding="utf-8"))["current"] if state.exists() else MODEL


def valid_teams(pool_dir: str) -> dict[str, str]:
    """The pool's teams (packed) whose exports the local validator passes (the current bans)."""
    from alpha_poke.teams.validate import check

    pool = load_team_files(pool_dir)
    names = sorted(pool)
    res = check([(Path(pool_dir) / f"{n}.txt").read_text() for n in names])
    return {
        n: pool[n] for n, r in zip(names, res, strict=True) if r["n"] == 6 and not r["problems"]
    }


def row(b, team: str, seconds: float) -> dict:
    return {"battle": b.battle_tag, "time": int(time.time()), "won": b.won, "lost": b.lost,
            "turns": b.turn, "rating": b.rating, "opponent": b.opponent_username,
            "opponent_rating": b.opponent_rating, "team": team,
            "seconds": round(seconds, 1)}  # fmt: skip


async def main(a) -> None:
    from alpha_poke.eval.bots import make_bot
    from alpha_poke.selfplay.batcher import ml_for

    model = a.model or current_network()
    os.environ.update({"ALPHA_SEARCH_MS": str(a.search_ms), "ALPHA_SEARCH_THREADS": str(a.threads),
                       "ALPHA_ML": ml_for(model)})  # fmt: skip
    pool = valid_teams(a.pool)
    if not pool:
        raise SystemExit(f"no team of {a.pool} passes the validator")
    rng = random.Random()
    out = (OUT if a.public else OUT / "dryrun") / time.strftime("%Y%m%d")
    out.mkdir(parents=True, exist_ok=True)
    if a.public:
        server, acct = public_server(confirm=True), public_account()
    else:
        server, acct = local_server(a.local_port), account(a.local_name)
    name = rng.choice(sorted(pool))
    bot = make_bot("s_ismcts_ma", acct.username, a.local_port, pool[name],
                   trace_dir=str(out / "traces"), replay_dir=str(out / "replays"),
                   server_configuration=server, account_configuration=acct,
                   overrides={"model": model})  # fmt: skip
    sparring = None
    if not a.public:  # (dry run: a local heuristic bot ladders too, so the two get matched)
        sparring = make_bot("heuristic", "ladderspar", a.local_port, pool[name])
    where = "OFFICIAL server" if a.public else f"local server :{a.local_port} (dry run)"
    print(f"[{where}] {model}, {a.search_ms} ms x {a.threads} threads; {len(pool)} valid teams; "
          f"{a.n} games (stop early: touch {STOP})", flush=True)  # fmt: skip
    log = open(out / "games.jsonl", "a", encoding="utf-8")
    for i in range(a.n):
        if STOP.exists():
            print(f"{STOP} found: stopped before game {i + 1}")
            break
        if i:
            name = rng.choice(sorted(pool))
            bot.update_team(pool[name])
        before, t0 = set(bot.battles), time.time()
        print(f"game {i + 1}/{a.n}: searching for a ladder game (team {name})", flush=True)
        play = [bot.ladder(1)] + ([sparring.ladder(1)] if sparring else [])
        await asyncio.gather(*play)
        for tag in set(bot.battles) - before:
            r = row(bot.battles[tag], name, time.time() - t0)
            log.write(json.dumps(r) + "\n")
            log.flush()
            res = "won" if r["won"] else "lost" if r["lost"] else "tie"
            print(f"  {tag}: {res} in {r['turns']} turns vs {r['opponent']} "
                  f"({r['opponent_rating']}); our rating {r['rating']}", flush=True)  # fmt: skip
    if hasattr(bot, "close"):
        bot.close()
    won = sum(1 for b in bot.battles.values() if b.won)
    print(f"done: {won}/{len(bot.battles)} won; {out / 'games.jsonl'}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="ladder games, one at a time")
    ap.add_argument("--pool", default=str(paths.pool("ladder_robust")))
    ap.add_argument("--model", default=None, help="network run (default: the current one)")
    ap.add_argument("--search-ms", type=int, default=5000, help="search time per decision")
    ap.add_argument("--threads", type=int, default=2, help="search threads")
    ap.add_argument("--public", action="store_true", help="connect to the OFFICIAL server")
    ap.add_argument("--local-port", type=int, default=8000, help="dry run (without --public)")
    ap.add_argument("--local-name", default="alphapokeladder", help="dry-run bot name")
    a = ap.parse_args()
    os.nice(10)  # (the machine stays usable for other work)
    asyncio.run(main(a))
