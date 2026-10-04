"""Throughput benchmark of the poke-env path (Python client <-> local Showdown server).

Runs random-vs-random Gen9 OU battles and reports battles/s and turns/s.
Scaling knobs: concurrent battles per player pair, number of client processes, and the
list of server ports (processes are spread round-robin over the servers).

Usage:
  uv run python scripts/bench_poke_env.py --battles 100 --concurrency 20
  uv run python scripts/bench_poke_env.py --battles 100 --concurrency 20 --procs 4 --ports 8000
  uv run python scripts/bench_poke_env.py --battles 100 --concurrency 20 --procs 8 --ports 8000 8001
"""

import argparse
import asyncio
import multiprocessing as mp
import os
import time

from alpha_poke.servers import account, local_server
from alpha_poke.teams import TeamPool


async def _run(worker: int, port: int, battles: int, concurrency: int, fmt: str):
    from poke_env.player import RandomPlayer

    kw = dict(
        battle_format=fmt,
        server_configuration=local_server(port),
        max_concurrent_battles=concurrency,
    )
    p1 = RandomPlayer(
        account_configuration=account(f"bn{os.getpid() % 100000}a"), team=TeamPool(), **kw
    )
    p2 = RandomPlayer(
        account_configuration=account(f"bn{os.getpid() % 100000}b"), team=TeamPool(), **kw
    )
    t0 = time.perf_counter()
    await p1.battle_against(p2, n_battles=battles)
    dt = time.perf_counter() - t0
    turns = sum(b.turn for b in p1.battles.values())
    return p1.n_finished_battles, turns, dt


def _worker(args):
    worker, port, battles, concurrency, fmt = args
    return asyncio.run(_run(worker, port, battles, concurrency, fmt))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=100, help="battles per process")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--ports", type=int, nargs="+", default=[8000])
    ap.add_argument("--format", default="gen9ou")
    a = ap.parse_args()

    jobs = [
        (i, a.ports[i % len(a.ports)], a.battles, a.concurrency, a.format) for i in range(a.procs)
    ]
    t0 = time.perf_counter()
    if a.procs == 1:
        results = [_worker(jobs[0])]
    else:
        with mp.get_context("spawn").Pool(a.procs) as pool:
            results = pool.map(_worker, jobs)
    wall = time.perf_counter() - t0

    battles = sum(r[0] for r in results)
    turns = sum(r[1] for r in results)
    print(
        f"procs={a.procs} servers={len(a.ports)} conc={a.concurrency}: "
        f"{battles} battles, {turns} turns in {wall:.1f}s -> "
        f"{battles / wall:.1f} battles/s, {turns / wall:.0f} turns/s "
        f"({turns / max(battles, 1):.1f} turns/battle)"
    )
