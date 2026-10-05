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
# name -> (full belief, use plan, plan lead)
VARIANTS = {
    "knowledge": (True, True, True),
    "k_nobelief": (False, True, True),
    "k_noplan": (True, False, False),
    "k_nolead": (True, True, False),
    "k_none": (False, False, False),
    "k_uniformlead": (True, True, True),
    "k_randlead": (True, True, True),
    "knowledge_twin": (True, True, True),  # identical to "knowledge" (sanity check)
}


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
    if kind in VARIANTS:
        from alpha_poke.agents.belief_state import BeliefModel
        from alpha_poke.agents.knowledge_player import KnowledgePlayer
        from alpha_poke.library import load_library

        belief_full, use_plan, plan_lead = VARIANTS[kind]
        belief = BeliefModel.load()
        if not belief_full:
            belief = belief.marginal_only()
        extra = {
            "k_uniformlead": {"lead_prior": "uniform"},
            "k_randlead": {"random_lead": True},
        }.get(kind, {})
        return KnowledgePlayer(
            belief, library=load_library(), use_plan=use_plan, plan_lead=plan_lead, **extra, **kw
        )
    return {
        "heuristic": SimpleHeuristicsPlayer,
        "max_bp": MaxBasePowerPlayer,
        "random": RandomPlayer,
    }[kind](**kw)


async def _run(job):
    """One worker: ``n`` battles between ``kind_a`` and ``kind_b``. If ``swap`` is set, ``kind_b``
    sends the challenges (roles swapped) -- results are always reported from ``kind_a``'s view."""
    kind_a, kind_b, port, n, conc, wid, swap = job
    tag = f"{os.getpid() % 10000}"
    a = _make(kind_a, f"{kind_a[:4]}{tag}a{wid}", port, conc)
    b = _make(kind_b, f"{kind_b[:4]}{tag}b{wid}", port, conc)
    if swap:
        await b.battle_against(a, n_battles=n)
    else:
        await a.battle_against(b, n_battles=n)
    return (
        a.n_won_battles,
        a.n_finished_battles,
        getattr(a, "fallbacks", 0),
        getattr(b, "fallbacks", 0),
    )


def _worker(job):
    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(_run(job))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="battles per opponent")
    ap.add_argument("--bot", nargs="+", default=["knowledge"])
    ap.add_argument("--opponents", nargs="+", default=["heuristic", "max_bp", "random"])
    ap.add_argument("--ports", type=int, nargs="+", default=[8000])
    ap.add_argument("--procs-per-opponent", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=8)
    a = ap.parse_args()
    pairs = [(b, o) for b in a.bot for o in a.opponents if b != o]
    for bot, opp in pairs:
        k = a.procs_per_opponent
        # half of the workers swap who sends the challenges, cancelling any role bias
        jobs = [
            (bot, opp, a.ports[i % len(a.ports)], a.n // k, a.concurrency, i, i % 2 == 1)
            for i in range(k)
        ]
        t0 = time.time()
        with mp.get_context("spawn").Pool(k) as pool:
            res = pool.map(_worker, jobs)
        won = sum(r[0] for r in res)
        n = sum(r[1] for r in res)
        fb = sum(r[2] for r in res)
        fb_opp = sum(r[3] for r in res)
        p = won / max(n, 1)
        ci = 1.96 * math.sqrt(p * (1 - p) / max(n, 1))
        print(
            f"{bot} vs {opp}: {won}/{n} = {p:.1%} ± {ci:.1%}  "
            f"(fallbacks {fb}/{fb_opp}, {time.time() - t0:.0f}s)",
            flush=True,
        )


if __name__ == "__main__":
    main()
