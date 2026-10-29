"""Friendly games on the OFFICIAL Showdown server against ONE whitelisted user (e.g. family).

  uv run python scripts/play_public.py --public --opponent <their username> --n 3 \\
      --difficulty normal

Safety: connects to the official server only with --public, logs in with the registered bot
account from .env (PS_BOT_USERNAME / PS_BOT_PASSWORD), accepts challenges ONLY from --opponent
(other challenges are ignored), never ladders, never joins rooms, never challenges anyone, and
exits after --n games. Without --public it runs against a local server (dry run).

The opponent challenges the bot in Gen 9 OU with their own team. The bot's team: --team (pool
team name or a Showdown-export file), default a random team of --pool each game (default
ladder_robust, 2026-10-28: the team-design pipeline's stage 2, doc/team_design.md). The network: the current one (the last promoted, state.json), or
--model <run> (e.g. a self-play attempt still under evaluation).
Difficulty: easy = heuristic bot, normal = ISMCTS + the current network 200 ms, hard = ISMCTS +
the current network 1 s x 4 threads (CPU; --model, default the self-play's current network in
data/selfplay/state.json; with its moves-left term, selfplay.batcher.SEARCH_ML); the lead from
the rule-based game plan. The strength by the search time: --search-ms (and --threads) replace
the difficulty's (e.g. --difficulty hard --search-ms 50 for a weaker bot, 3000 for a stronger).
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
from alpha_poke.teams import POOLS_DIR, load_team_files

DIFFICULTY = {  # variant, search env (the search variants get --model)
    "easy": ("knowledge", {}),
    "normal": ("s_ismcts_ma", {"ALPHA_SEARCH_MS": "200", "ALPHA_SEARCH_THREADS": "1"}),
    "hard": ("s_ismcts_ma", {"ALPHA_SEARCH_MS": "1000", "ALPHA_SEARCH_THREADS": "4"}),
}


def current_network() -> str:
    """The self-play loop's current network (data/selfplay/state.json)."""
    import json

    return json.loads(Path("data/selfplay/state.json").read_text())["current"]


def pick_team(arg: str | None, pool: dict[str, str], rng: random.Random) -> tuple[str, str]:
    if arg is None:
        name = rng.choice(sorted(pool))
        return name, pool[name]
    if arg in pool:
        return arg, pool[arg]
    text = Path(arg).read_text()
    return Path(arg).stem, Teambuilder.join_team(Teambuilder.parse_showdown_team(text + "\n\n"))


async def main(a) -> None:
    variant, env = DIFFICULTY[a.difficulty]
    os.environ.update(env)
    if a.search_ms is not None:
        os.environ["ALPHA_SEARCH_MS"] = str(a.search_ms)
    if a.threads is not None:
        os.environ["ALPHA_SEARCH_THREADS"] = str(a.threads)
    model = a.model or current_network()
    search = variant != "knowledge"
    if search:
        from alpha_poke.selfplay.batcher import ml_for

        os.environ["ALPHA_ML"] = ml_for(model)
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
        overrides={"model": model} if search else None,
    )
    where = "OFFICIAL server" if a.public else f"local server :{a.local_port}"
    e = os.environ
    net = (f", {model}, {e['ALPHA_SEARCH_MS']} ms x {e['ALPHA_SEARCH_THREADS']} threads, "
           f"moves-left {e.get('ALPHA_ML') or 'off'}") if search else ""  # fmt: skip
    print(f"[{where}] bot {acct.username} ({a.difficulty}: {variant}{net}); only {a.opponent!r}")
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
    ap.add_argument("--pool", default=str(POOLS_DIR / "ladder_robust"))
    ap.add_argument("--model", default=None, help="network run (default: the current one)")
    ap.add_argument("--search-ms", type=int, default=None, help="search time per decision")
    ap.add_argument("--threads", type=int, default=None, help="search threads")
    ap.add_argument("--public", action="store_true", help="connect to the OFFICIAL server")
    ap.add_argument("--local-port", type=int, default=8000, help="dry run (without --public)")
    ap.add_argument("--local-name", default="alphapokebot", help="dry-run bot name")
    asyncio.run(main(ap.parse_args()))
