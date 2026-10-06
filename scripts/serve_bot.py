"""Run one of our bots as a separate process that plays a fixed list of teams (regression tests).

Used by alpha_poke.eval.external to pit the current code against an OLDER checkout: this file is
executed with PYTHONPATH pointing at the old checkout's src/, so it must only use APIs that
exist there (eval.bots.make_bot, teams.load_team_files). Local servers only.

  python scripts/serve_bot.py --bot k_llmplan --port 8000 --username old1 --pool data/teams/pool \\
      --teams team_03,team_17 --mode accept --opponent ab123
"""

import argparse
import asyncio
import logging

from alpha_poke.eval.bots import make_bot
from alpha_poke.teams import load_team_files


async def main(a) -> None:
    teams = load_team_files(a.pool)
    order = a.teams.split(",")
    bot = make_bot(a.bot, a.username, a.port, teams[order[0]])
    for name in order:
        bot.update_team(teams[name])
        if a.mode == "accept":
            await bot.accept_challenges(a.opponent, n_challenges=1)
        else:
            await bot.send_challenges(a.opponent, n_challenges=1)
    wins = sum(1 for b in bot.battles.values() if b.won)
    print(f"serve_bot {a.username}: {wins}/{len(bot.battles)} won", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--teams", required=True, help="comma-separated team names, in match order")
    ap.add_argument("--mode", choices=["accept", "challenge"], required=True)
    ap.add_argument("--opponent", required=True)
    asyncio.run(main(ap.parse_args()))
