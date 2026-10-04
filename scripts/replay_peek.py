"""Fetch (or load) one Gen9 OU replay and print what can be extracted from it.

Usage:
  uv run python scripts/replay_peek.py gen9ou-2692661258        # id (downloaded once, cached)
  uv run python scripts/replay_peek.py path/to/replay.json
  uv run python scripts/replay_peek.py gen9ou-2692661258 --timeline
"""

import argparse
import json
from pathlib import Path

from alpha_poke.replay import ReplayClient, parse_replay


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("replay", help="replay id or path to a saved .json")
    ap.add_argument("--timeline", action="store_true", help="print every turn's actions")
    a = ap.parse_args()

    p = Path(a.replay)
    data = json.loads(p.read_text()) if p.exists() else ReplayClient().get(a.replay)
    r = parse_replay(data)

    print(f"{r.id}  {r.format}  gen{r.gen}  {r.turns} turns  uploaded={r.uploadtime}")
    for s in ("p1", "p2"):
        flag = " (winner)" if r.winner == s else ""
        print(
            f"  {s}: {r.players.get(s)}  rating {r.ratings_before[s]} -> {r.ratings_after[s]}{flag}"
        )
    print("leads:", r.leads())
    for s in ("p1", "p2"):
        print(f"\n=== {s} team (revealed info only) ===")
        for m in r.teams[s]:
            tag = "" if m.brought else "  [never sent out]"
            fainted = f"  fainted T{m.fainted_turn}" if m.fainted_turn else ""
            print(
                f"{m.species:22s} item={m.item or '?':16s} ability={m.ability or '?':18s} "
                f"tera={m.tera_type or '?':9s} moves={m.moves}{fainted}{tag}"
            )
    print("\nfield events:")
    for e in r.field_events:
        print(f"  T{e['turn']:>2} {e['kind']:10s} {e['side'] or '-':2s} {e['detail']}")
    if a.timeline:
        print("\ntimeline:")
        by_turn: dict[int, list] = {}
        for x in r.actions:
            by_turn.setdefault(x.turn, []).append(x)
        for t, acts in sorted(by_turn.items()):
            desc = []
            for x in acts:
                if x.kind == "lead":
                    desc.append(f"{x.side} LEAD {x.to}")
                elif x.kind == "move":
                    desc.append(f"{x.side} {x.mon}:{x.move}{' [TERA]' if x.tera else ''}")
                else:
                    tag = " (forced)" if x.forced else " (pivot)" if x.pivot else ""
                    desc.append(f"{x.side} {x.mon}->{x.to}{tag}")
            hp = r.hp_by_turn.get(t, {})
            print(f"  T{t:>2}: " + " | ".join(desc) + (f"   HP@start {hp}" if hp else ""))
    if r.warnings:
        print("\nwarnings:", r.warnings)


if __name__ == "__main__":
    main()
