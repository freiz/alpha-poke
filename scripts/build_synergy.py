"""The cross-mon set synergy of self-play's synthetic teams (selfplay.synergy, 2026-10-26): real
games' revealed sets (games since --since, --games of them at random) -> data/selfplay/synergy.npz.

  uv run python scripts/build_synergy.py --games 120000   (about 16 minutes, 3 GB)
"""

import argparse
import time

import pandas as pd

from alpha_poke.analysis.games_lite import DEST, logs
from alpha_poke.analysis.roles import to_id
from alpha_poke.replay.parser import parse_replay
from alpha_poke.selfplay import synergy


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=120000)
    ap.add_argument(
        "--since", type=int, default=1746057600, help="2025-05-01: the current metagame"
    )
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    g = pd.read_parquet(DEST, columns=["id", "time", "winner", "shard", "row"])
    g = g[(g.winner > 0) & (g.time >= a.since)]
    rows = g.sample(min(a.games, len(g)), random_state=a.seed).to_dict("records")
    t0, teams = time.time(), []
    for i in range(0, len(rows), 2000):  # (the logs in parts: memory)
        part = rows[i : i + 2000]
        full = logs(part)
        for r in part:
            try:
                rep = parse_replay(full[r["id"]])
            except Exception:
                continue
            if rep.warnings:
                continue
            for s in ("p1", "p2"):
                mons = [m for m in rep.teams[s] if not m.phantom]
                if len(mons) == 6:
                    teams.append([(to_id(m.species.replace("-*", "")), synergy.tokens(m.ability, m.item, m.moves))
                                  for m in mons])  # fmt: skip
    syn, info = synergy.build(teams)
    syn.save()
    print(f"{len(rows)} games, {info} in {time.time() - t0:.0f}s -> {synergy.PATH}")


if __name__ == "__main__":
    main()
