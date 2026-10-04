"""Round-robin of the built-in poke-env baselines in Gen9 OU on a local Showdown server.

Usage: uv run python scripts/baseline_match.py [--n 50] [--port 8000] [--concurrency 10]
"""

import argparse
import asyncio

from poke_env.player import MaxBasePowerPlayer, RandomPlayer, SimpleHeuristicsPlayer
from tabulate import tabulate

from alpha_poke.servers import account, local_server
from alpha_poke.teams import TeamPool

PLAYERS = {
    "random": RandomPlayer,
    "max_bp": MaxBasePowerPlayer,
    "heuristic": SimpleHeuristicsPlayer,
}


async def main(n: int, port: int, concurrency: int, fmt: str) -> None:
    players = {
        name: cls(
            account_configuration=account(name),
            battle_format=fmt,
            server_configuration=local_server(port),
            max_concurrent_battles=concurrency,
            team=TeamPool(),
        )
        for name, cls in PLAYERS.items()
    }
    names = list(players)
    wins = {a: {b: None for b in names} for a in names}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            players[a].reset_battles()
            players[b].reset_battles()
            await players[a].battle_against(players[b], n_battles=n)
            w = players[a].n_won_battles
            wins[a][b] = w / n
            wins[b][a] = 1 - w / n
            print(f"{a} vs {b}: {w}/{n}", flush=True)
    rows = [[a] + [("-" if a == b else f"{wins[a][b]:.2f}") for b in names] for a in names]
    print()
    print("Row player's win rate against column player")
    print(tabulate(rows, headers=[""] + names))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=50, help="battles per pairing")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--format", default="gen9ou")
    args = p.parse_args()
    asyncio.run(main(args.n, args.port, args.concurrency, args.format))
