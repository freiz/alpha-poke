"""The opponent side of a split paired evaluation (alpha_poke.eval.split): bot B's lanes, run by
another checkout's interpreter -- its own code, its own engine build (an A/B of two versions:
2026-10-25, the state / engine changes a single process cannot hold both of).

Uses only what every checkout has (eval.bots.make_bot, teams.load_team_files); the schedule and
its lanes are built here the way split.py builds them, the names agreed: bot A is ``a<run>l<i>``,
bot B ``b<run>l<i>`` on lane i.

  <other>/.venv/bin/python scripts/eval_pairs_opponent.py g_mb --pool <dir> --pairs N \\
      --lanes-total L --lanes 0 1 2 --port 8000 --run r1
"""

import argparse
import asyncio
import logging
import re
from pathlib import Path

GAME_TIMEOUT = 1200  # (arena.GAME_TIMEOUT)
START_WAIT = 90  # (split.START_WAIT)


def schedule(pool: str, pairs: int) -> list[tuple[str, str, bool]]:
    """[(team A, team B, A challenges)] in play order -- eval_pairs.py's."""
    ks = sorted({int(m.group(1)) for f in Path(pool).glob("pair*_a.txt") if (m := re.match(r"pair(\d+)_a", f.stem))})
    if pairs:
        ks = ks[:pairs]
    out = []
    for k in ks:
        x, y = f"pair{k:03d}_a", f"pair{k:03d}_b"
        out += [(x, y, k % 2 == 0), (y, x, k % 2 == 1)]
    return out


async def lane(bot: str, matches, port: int, pool: str, run: str, i: int) -> int:
    from alpha_poke.eval.bots import make_bot
    from alpha_poke.teams import load_team_files

    teams = load_team_files(pool)
    me = make_bot(bot, f"b{run}l{i}", port, next(iter(teams.values())))
    opp = f"a{run}l{i}"
    failed = 0
    await asyncio.sleep(START_WAIT)  # (both sides online before the first challenge: split.py's)
    for _team_a, team_b, a_challenges in matches:
        me.update_team(teams[team_b])
        play = me.accept_challenges(opp, n_challenges=1) if a_challenges else me.send_challenges(opp, n_challenges=1)
        try:
            await asyncio.wait_for(play, GAME_TIMEOUT)
        except TimeoutError:
            failed += 1
            logging.getLogger(__name__).warning("lane %d: no finished game after %ds", i, GAME_TIMEOUT)
    if hasattr(me, "close"):
        me.close()
    return {"failed": failed, "fallbacks": getattr(me, "fallbacks", 0), "search_fallbacks": getattr(me, "search_fallbacks", 0)}


async def main(a) -> None:
    sched = schedule(a.pool, a.pairs)
    lanes = [sched[i :: a.lanes_total] for i in range(a.lanes_total)]
    fails = await asyncio.gather(*[lane(a.bot, lanes[i], a.port, a.pool, a.run, i) for i in a.lanes])
    print("OPPONENT DONE", dict(zip(a.lanes, fails, strict=True)), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bot")
    ap.add_argument("--pool", required=True)
    ap.add_argument("--pairs", type=int, default=0)
    ap.add_argument("--lanes-total", type=int, required=True)
    ap.add_argument("--lanes", type=int, nargs="+", required=True)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--run", required=True)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(ap.parse_args()))
