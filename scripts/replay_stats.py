"""Aggregate statistics over a directory of cached replay JSON files.

Usage: uv run python scripts/replay_stats.py [dir=data/replays_sample] [--top 15]

Shows how much of each mon's set is revealed in a typical replay, plus species / lead /
tera / item frequencies. Works on any number of replays (it is the starting point for the
large-scale analysis).
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from alpha_poke.replay import parse_replay


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default="data/replays_sample")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()

    files = sorted(Path(a.dir).rglob("*.json"))
    species, brought, leads, items, teras, abilities, moves = (Counter() for _ in range(7))
    n_games = n_mons = 0
    reveal_brought = {"moves": 0.0, "item": 0, "ability": 0, "tera": 0}
    n_brought = 0
    turns, errors, warn = [], 0, 0
    for f in files:
        try:
            r = parse_replay(json.loads(f.read_text()))
        except Exception as e:  # noqa: BLE001 - report and continue
            errors += 1
            print(f"PARSE ERROR {f.name}: {type(e).__name__}: {e}")
            continue
        n_games += 1
        turns.append(r.turns)
        warn += len(r.warnings)
        for team in r.teams.values():
            for m in team:
                if m.phantom:
                    continue
                n_mons += 1
                species[m.species] += 1
                if m.lead:
                    leads[m.species] += 1
                if m.brought:
                    n_brought += 1
                    brought[m.species] += 1
                    fr = m.revealed_fraction()
                    for k in reveal_brought:
                        reveal_brought[k] += fr[k]
                if m.item:
                    items[m.item] += 1
                if m.tera_type:
                    teras[m.tera_type] += 1
                if m.ability:
                    abilities[m.ability] += 1
                for mv in m.moves:
                    moves[mv] += 1
    print(
        f"{n_games} replays parsed ({errors} errors, {warn} warnings), "
        f"avg {sum(turns) / max(len(turns), 1):.1f} turns"
    )
    print(
        f"{n_mons} team slots, {n_brought} actually sent out "
        f"({100 * n_brought / max(n_mons, 1):.0f}%)"
    )
    if n_brought:
        print("\nRevealed info per mon that was sent out (avg):")
        print(f"  moves   {4 * reveal_brought['moves'] / n_brought:.2f} / 4")
        print(f"  item    {100 * reveal_brought['item'] / n_brought:.0f}% known")
        print(f"  ability {100 * reveal_brought['ability'] / n_brought:.0f}% known")
        print(f"  tera    {100 * reveal_brought['tera'] / n_brought:.0f}% known")
    for title, c in [
        ("Species in teams", species),
        ("Leads", leads),
        ("Items revealed", items),
        ("Tera types revealed", teras),
        ("Abilities revealed", abilities),
        ("Moves revealed", moves),
    ]:
        print(f"\n{title}:")
        for k, v in c.most_common(a.top):
            print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
