"""Explain examples of the engine differential (doc/engine-diff.md): for each example of a
mismatch kind or HP-gap tag in data/selfplay/diag/engine_diff_gen<G>.json, the mon concerned,
Showdown's log of that turn (logs-w<k>.jsonl, the decision's game = the log's pair) and the
instructions of poke-engine's outcomes of the same two choices.

  uv run python scripts/explain_engine_diff.py --gen 8 --hp "active -1/16" --n 3
  uv run python scripts/explain_engine_diff.py --gen 8 --kind status --n 3

The logs are read streaming, one line per game (a generation's are GBs).
"""

import argparse
import json
from pathlib import Path

import poke_engine as pe

from alpha_poke.selfplay import SELFPLAY_DIR


def turn_log(gen: int, worker: str, pair: int, turn: int) -> list[str]:
    """Showdown's protocol lines of ``turn`` (from |turn|t to |turn|t+1) of one game."""
    prefix = f'{{"pair": {pair},'
    with open(SELFPLAY_DIR / f"gen{gen}" / f"logs-w{worker}.jsonl") as f:
        for line in f:
            if line.startswith(prefix):
                log = json.loads(line)["log"].splitlines()
                break
        else:
            return []
    try:
        i = log.index(f"|turn|{turn}")
    except ValueError:
        return []
    j = log.index(f"|turn|{turn + 1}") if f"|turn|{turn + 1}" in log else len(log)
    keep = ("|move", "|switch", "|drag", "|-", "|cant", "|faint", "|upkeep", "|turn")
    return [x for x in log[i : j + 1] if x.startswith(keep)]


def mon_info(state: str, i: int) -> str:
    s = pe.State.from_string(state)
    side = (s.side_one, s.side_two)[i // 6]
    p = side.pokemon[i % 6]
    act = int(side.active_index) == i % 6
    sc = side.side_conditions
    hz = {k: getattr(sc, k) for k in ("spikes", "toxic_spikes", "stealth_rock", "toxic_count")
          if getattr(sc, k)}  # fmt: skip
    return (f"{p.id} hp {p.hp}/{p.maxhp} item {p.item} ability {p.ability} status {p.status} "
            f"types {p.types} {'active' if act else 'bench'} side {hz} "
            f"vol {sorted(str(v) for v in side.volatile_statuses) if act else '-'} "
            f"weather {s.weather} terrain {s.terrain}")  # fmt: skip


def engine_lines(state: str, slots: list[int]) -> list[str]:
    """The engine's outcomes of the two recorded choices (action slots): probability, the HP
    changes per mon (the binding's instruction strings cannot name a switch's slot, so the
    outcomes come from alpha_search.chance_outcomes and are diffed against the state)."""
    import alpha_search

    b = pe.State.from_string(state)
    out = []
    for p, s, _, dmg in alpha_search.chance_outcomes(state, slots[0], slots[1], True, True):
        a = pe.State.from_string(s)
        ch = []
        for k, sb, sa in (("s1", b.side_one, a.side_one), ("s2", b.side_two, a.side_two)):
            if int(sb.active_index) != int(sa.active_index):
                ch.append(f"{k} active {sb.active_index}->{sa.active_index}")
            for j, (x, y) in enumerate(zip(sb.pokemon, sa.pokemon, strict=True)):
                if x.hp != y.hp or x.status != y.status:
                    ch.append(f"{k}.{j} {y.id} hp {x.hp}->{y.hp} {y.status}")
            vb, va = ({str(v).lower() for v in x.volatile_statuses} for x in (sb, sa))
            ch += [f"{k} +{v}" for v in sorted(va - vb)] + [f"{k} -{v}" for v in sorted(vb - va)]
        out.append(f"  {100 * p:5.1f}%  damage taken {dmg}  {ch}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, default=8)
    ap.add_argument("--hp", default=None, help='an HP-gap tag, e.g. "active -1/16"')
    ap.add_argument("--kind", default=None, help="a mismatch kind, e.g. status")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--move", default=None, help="only examples with this move (either side)")
    a = ap.parse_args()
    rep = json.loads((Path("data/selfplay/diag") / f"engine_diff_gen{a.gen}.json").read_text())
    exs = rep["hp_gap_examples"].get(a.hp, []) if a.hp else rep["examples"].get(a.kind, [])
    if a.move:
        exs = [e for e in exs if a.move in (e["p1"], e["p2"])]
    for e in exs[: a.n]:
        (w, g), t = e["game"], e["turn"]
        print(f"=== worker {w} game {g} turn {t}: {e['p1']} | {e['p2']}")
        if a.hp:
            print(f"  mon {e['mon']}: engine {e['engine']} actual {e['actual']} max {e['max']}")
            print("  before:", mon_info(e["before"], e["mon"]))
        else:
            print("  discrete:", e["discrete"], "hp:", e["hp"])
            b = pe.State.from_string(e["before"])
            print("  before durations:", b.side_one.volatile_status_durations.confusion,
                  b.side_two.volatile_status_durations.confusion, "vol",
                  sorted(str(v) for v in b.side_one.volatile_statuses),
                  sorted(str(v) for v in b.side_two.volatile_statuses))
        print("  Showdown:")
        for x in turn_log(a.gen, w, int(g), t):
            print("   ", x)
        print("  poke-engine outcomes:")
        for x in engine_lines(e["before"], e["slots"]):
            print(x[:400])


if __name__ == "__main__":
    main()
