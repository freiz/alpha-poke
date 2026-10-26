"""A paired evaluation split over two checkouts (2026-10-25): bot A runs here, bot B in another
checkout's interpreter (scripts/eval_pairs_opponent.py) -- an A/B of two code versions, the state
construction and the engine both (one process cannot hold two of either; the engine-only A/B
loaded an ``alpha_search_old`` build instead). The schedule and its lanes as eval_pairs.py's;
bot A ``a<run>l<i>``, bot B ``b<run>l<i>`` on lane i; per-game rows as the arena's (A's view)."""

import asyncio
import json
import logging
import multiprocessing as mp
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from alpha_poke.eval.arena import GAME_TIMEOUT, TURN_CAP, Match, _base, _species
from alpha_poke.teams import load_team_files

ROOT = Path(__file__).resolve().parents[3]
START_WAIT = 90  # seconds before a lane's first match (scripts/eval_pairs_opponent.py's too)


async def _lane(bot_a: str, matches: list[Match], port: int, pool: str, run: str, i: int, log_path: str) -> list:
    from alpha_poke.eval.bots import make_bot

    teams = load_team_files(pool)
    expected = {k: _species(v) for k, v in teams.items()}
    me = make_bot(bot_a, f"a{run}l{i}", port, next(iter(teams.values())))
    opp = f"b{run}l{i}"
    # (both sides online before the first challenge: the opponent's interpreter -- its imports, its
    # model, its login; a challenge to a user not yet on is lost -- "not found", the lane stuck)
    await asyncio.sleep(START_WAIT)
    rows = []
    broken = False  # (a game that never finished: the other side may be a game ahead or behind)
    for m in matches:
        if broken:  # (the lane stops: its teams and challenges would no longer agree -- 2026-10-26 review)
            rows.append(asdict(m) | {"bot_a": bot_a, "bot_b": "opponent", "battle": None, "a_won": None,
                                     "turns": None, "capped": False, "team_ok": False, "fallbacks_a": 0,
                                     "search_fallbacks_a": 0, "fallbacks_b": None, "seconds": 0.0})  # fmt: skip
            continue
        me.update_team(teams[m.team_a])
        before = set(me.battles)
        fb0 = (getattr(me, "fallbacks", 0), getattr(me, "search_fallbacks", 0))
        play = me.send_challenges(opp, n_challenges=1) if m.a_challenges else me.accept_challenges(opp, n_challenges=1)
        t0 = time.time()
        try:
            await asyncio.wait_for(play, GAME_TIMEOUT)
        except TimeoutError:
            logging.getLogger(__name__).warning("lane %d pair %d game %d: no finished game -- the lane stops", i,
                                                m.pair, m.game)  # fmt: skip
            broken = True
        new = [me.battles[t] for t in me.battles if t not in before]
        battle = new[0] if new else None
        row = asdict(m) | {
            "bot_a": bot_a,
            "bot_b": "opponent",
            "battle": battle.battle_tag if battle else None,
            "a_won": None if battle is None else battle.won,
            "turns": battle.turn if battle else None,
            "capped": bool(battle and battle.turn >= TURN_CAP),
            "team_ok": bool(battle and sorted(_base(p.species) for p in battle.team.values()) == expected[m.team_a]),
            "fallbacks_a": getattr(me, "fallbacks", 0) - fb0[0],
            "search_fallbacks_a": getattr(me, "search_fallbacks", 0) - fb0[1],
            "fallbacks_b": None,  # (the opponent's own: its log's OPPONENT DONE line)
            "seconds": round(time.time() - t0, 1),
        }
        rows.append(row)
        with open(log_path, "a") as f:
            f.write(json.dumps(row) + "\n")
    if hasattr(me, "close"):
        me.close()
    return rows


def _worker(args):
    bot_a, bot_b, lanes, ids, n_lanes, port, pool, pairs, run, log_path, other = args
    logging.basicConfig(level=logging.WARNING)
    cmd = [str(Path(other) / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "eval_pairs_opponent.py"), bot_b,
           "--pool", str(Path(pool).resolve()), "--pairs", str(pairs), "--lanes-total", str(n_lanes),
           "--lanes", *map(str, ids), "--port", str(port), "--run", run]  # fmt: skip
    out = open(Path(log_path).with_suffix(f".opp{ids[0]}.log"), "w")
    proc = subprocess.Popen(cmd, cwd=other, stdout=out, stderr=subprocess.STDOUT, env=dict(os.environ))

    async def go():
        return await asyncio.gather(*[_lane(bot_a, ms, port, pool, run, i, log_path) for i, ms in zip(ids, lanes, strict=True)])

    try:
        return [r for lane in asyncio.run(go()) for r in lane]
    finally:
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.terminate()


def run_split(bot_a: str, bot_b: str, schedule: list[Match], pool: str, pairs: int, log_path: str, other: str,
              ports=(8000,), procs: int = 4, lanes_per_proc: int = 12, run: str = "r") -> list[dict]:  # fmt: skip
    """``schedule`` (eval_pairs.py's: the opponent script builds the same) over procs x lanes; each
    worker starts its opponent process in ``other`` (a checkout with its own .venv)."""
    n = procs * lanes_per_proc
    lanes = [schedule[i::n] for i in range(n)]
    jobs = [(bot_a, bot_b, lanes[w * lanes_per_proc:(w + 1) * lanes_per_proc],
             list(range(w * lanes_per_proc, (w + 1) * lanes_per_proc)), n, ports[w % len(ports)], pool, pairs, run,
             log_path, other) for w in range(procs)]  # fmt: skip
    with ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn")) as ex:
        return [r for part in ex.map(_worker, jobs) for r in part]


if __name__ == "__main__":  # (see scripts/eval_pairs.py --other)
    sys.exit("use scripts/eval_pairs.py --other <checkout>")
