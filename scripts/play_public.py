"""Friendly games on the OFFICIAL Showdown server against ONE whitelisted user (e.g. family).

  uv run python scripts/play_public.py --public --opponent <their username> --n 3 \\
      --difficulty normal

Safety: connects to the official server only with --public, logs in with the registered bot
account from .env (PS_BOT_USERNAME / PS_BOT_PASSWORD), accepts challenges ONLY from --opponent
(other challenges are ignored), never ladders, never joins rooms, never challenges anyone, and
exits after --n games. Without --public it runs against a local server (dry run).

The opponent challenges the bot in Gen 9 OU with their own team. The bot's team: --team (pool
team name or a Showdown-export file), default a random pool team each game.
Difficulty: easy = heuristic bot, normal = search 200 ms, hard = search 1 s x 4 threads; all
with the rule-based game plan (no LLM call) unless --llm.
Replays and decision traces go to data/public_games/<date>/.

With a team chosen against this opponent (scripts/counter_pipeline.py <user> writes
data/players/<user id>/counter/, team_00 = the best):
  # always the best team
  uv run python scripts/play_public.py --public --opponent <user> --n 3 \\
      --team data/players/<user id>/counter/team_00.txt
  # a random one of the chosen teams each game
  uv run python scripts/play_public.py --public --opponent <user> --n 3 \\
      --pool data/players/<user id>/counter
(<user id>: the username lowercased, letters and digits only.)
"""

import argparse
import asyncio
import logging
import os
import random
import time
from pathlib import Path

from poke_env.teambuilder import Teambuilder

from alpha_poke.eval.bots import make_bot
from alpha_poke.servers import account, local_server, public_account, public_server
from alpha_poke.teams import DEFAULT_POOL, load_team_files

# Rule-based (computed) plans, no LLM: the LLM plan showed no measurable gain over the computed
# plan for either the heuristic bot (51.3% +- 4.6%) or the search bot (lead 47.3% +- 6.6%,
# root plan prior 46.8% +- 7.3%); design D11. --llm turns it back on.
DIFFICULTY = {  # variant, LLM variant, search env
    "easy": ("knowledge", "k_llmplan", {}),
    "normal": ("s_computed", "s_llmplan", {"ALPHA_SEARCH_MS": "200", "ALPHA_SEARCH_SAMPLES": "2",
                                           "ALPHA_SEARCH_THREADS": "1"}),
    "hard": ("s_computed", "s_llmplan", {"ALPHA_SEARCH_MS": "1000", "ALPHA_SEARCH_SAMPLES": "4",
                                         "ALPHA_SEARCH_THREADS": "4"}),
}  # fmt: skip


def pick_team(arg: str | None, pool: dict[str, str], rng: random.Random) -> tuple[str, str]:
    if arg is None:
        name = rng.choice(sorted(pool))
        return name, pool[name]
    if arg in pool:
        return arg, pool[arg]
    text = Path(arg).read_text()
    return Path(arg).stem, Teambuilder.join_team(Teambuilder.parse_showdown_team(text + "\n\n"))


async def main(a) -> None:
    variant, llm_variant, env = DIFFICULTY[a.difficulty]
    if a.llm:
        variant = llm_variant
    os.environ.update(env)
    pool = load_team_files(a.pool)
    rng = random.Random()
    out = Path("data/public_games") / time.strftime("%Y%m%d")
    out.mkdir(parents=True, exist_ok=True)
    if a.public:
        server, acct = public_server(confirm=True), public_account()
    else:
        server, acct = local_server(a.local_port), account(a.local_name)
    name, team = pick_team(a.team, pool, rng)
    bot = make_bot(
        variant,
        acct.username,
        a.local_port,
        team,
        trace_dir=str(out / "traces"),
        replay_dir=str(out / "replays"),
        server_configuration=server,
        account_configuration=acct,
    )
    where = "OFFICIAL server" if a.public else f"local server :{a.local_port}"
    print(f"[{where}] bot {acct.username} ({a.difficulty}: {variant}); only {a.opponent!r}")
    for i in range(a.n):
        if i:
            name, team = pick_team(a.team, pool, rng)
            bot.update_team(team)
        print(f"game {i + 1}/{a.n}: waiting for a Gen 9 OU challenge from {a.opponent} "
              f"(bot team: {name})", flush=True)  # fmt: skip
        before = set(bot.battles)
        await bot.accept_challenges(a.opponent, n_challenges=1)
        for tag in set(bot.battles) - before:
            b = bot.battles[tag]
            res = "bot won" if b.won else "bot lost" if b.lost else "tie"
            print(f"  {tag}: {res} in {b.turn} turns", flush=True)
    if hasattr(bot, "close"):
        bot.close()
    won = sum(1 for b in bot.battles.values() if b.won)
    print(f"done: bot won {won}/{len(bot.battles)}; replays in {out / 'replays'}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--opponent", required=True, help="the ONLY user whose challenges we accept")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--difficulty", choices=sorted(DIFFICULTY), default="normal")
    ap.add_argument("--team", default=None, help="pool team name or Showdown-export file")
    ap.add_argument("--pool", default=str(DEFAULT_POOL))
    ap.add_argument("--llm", action="store_true", help="LLM game plan (off by default, D11)")
    ap.add_argument("--public", action="store_true", help="connect to the OFFICIAL server")
    ap.add_argument("--local-port", type=int, default=8000, help="dry run (without --public)")
    ap.add_argument("--local-name", default="alphapokebot", help="dry-run bot name")
    asyncio.run(main(ap.parse_args()))
