"""Local head-to-head evaluation of bots on the reconstructed team pool.

Both sides draw a random team from the pool every battle. Reports win rate with a 95% CI.
Connects only to local Showdown servers (alpha_poke.servers.local_server).

Usage:
  uv run python scripts/eval_bots.py --n 200 --opponents heuristic max_bp
  uv run python scripts/eval_bots.py --n 400 --ports 8000 8001 8002 8003
"""

import argparse
import asyncio
import logging
import math
import multiprocessing as mp
import os
import time

from alpha_poke.teams import TeamPool, load_team_files

POOL = "data/teams/pool"


def _make(kind: str, name: str, port: int, concurrency: int):
    from poke_env.player import MaxBasePowerPlayer, RandomPlayer, SimpleHeuristicsPlayer

    from alpha_poke.servers import account, local_server

    kw = dict(
        account_configuration=account(name),
        battle_format="gen9ou",
        server_configuration=local_server(port),
        max_concurrent_battles=concurrency,
        team=TeamPool(load_team_files(POOL)),
    )
    if kind == "knowledge":
        from alpha_poke.agents.belief_state import BeliefModel
        from alpha_poke.agents.knowledge_player import KnowledgePlayer
        from alpha_poke.library import load_library

        return KnowledgePlayer(BeliefModel.load(), library=load_library(), **kw)
    return {
        "heuristic": SimpleHeuristicsPlayer,
        "max_bp": MaxBasePowerPlayer,
        "random": RandomPlayer,
    }[kind](**kw)


async def _run(job):
    kind_a, kind_b, port, n, conc, wid = job
    tag = f"{os.getpid() % 10000}"
    a = _make(kind_a, f"{kind_a[:4]}{tag}a{wid}", port, conc)
    b = _make(kind_b, f"{kind_b[:4]}{tag}b{wid}", port, conc)
    await a.battle_against(b, n_battles=n)
    return a.n_won_battles, a.n_finished_battles, getattr(a, "fallbacks", 0)


def _worker(job):
    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(_run(job))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="battles per opponent")
    ap.add_argument("--bot", default="knowledge")
    ap.add_argument("--opponents", nargs="+", default=["heuristic", "max_bp", "random"])
    ap.add_argument("--ports", type=int, nargs="+", default=[8000])
    ap.add_argument("--procs-per-opponent", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=8)
    a = ap.parse_args()
    for opp in a.opponents:
        k = a.procs_per_opponent
        jobs = [
            (a.bot, opp, a.ports[i % len(a.ports)], a.n // k, a.concurrency, i) for i in range(k)
        ]
        t0 = time.time()
        with mp.get_context("spawn").Pool(k) as pool:
            res = pool.map(_worker, jobs)
        won = sum(r[0] for r in res)
        n = sum(r[1] for r in res)
        fb = sum(r[2] for r in res)
        p = won / max(n, 1)
        ci = 1.96 * math.sqrt(p * (1 - p) / max(n, 1))
        print(
            f"{a.bot} vs {opp}: {won}/{n} = {p:.1%} ± {ci:.1%}  "
            f"(fallbacks {fb}, {time.time() - t0:.0f}s)",
            flush=True,
        )


if __name__ == "__main__":
    main()
