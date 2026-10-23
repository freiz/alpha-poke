"""Decision steps and what a decision point may know (2026-10-22 review): the training history
of a pivot switch held the foe's move that came after it (our U-turn first, the foe's attack
after our switch-in), which the live history -- the log so far -- does not have."""

from pathlib import Path

import pytest

from alpha_poke.replay.parser import parse_replay
from alpha_poke.train.positions import Blind, decision_steps

pq = pytest.importorskip("pyarrow.parquet")
GAMES = sorted(Path("data/replays_hf/gen9ou").glob("*.parquet"))


def _rows(n):
    t = pq.ParquetFile(GAMES[-1]).read_row_group(0, columns=["id", "log", "rating", "uploadtime"])
    return t.to_pylist()[:n]


@pytest.mark.skipif(not GAMES, reason="needs the replays")
def test_no_step_before_a_pivot_holds_a_later_action():
    pivots = moved = 0
    for row in _rows(400):
        rep = parse_replay(row)
        if rep.warnings:
            continue
        steps = decision_steps(rep.actions)
        for t, ss in steps.items():
            for i, s in enumerate(ss):
                for a in s.values():
                    if isinstance(a, Blind) or not a.pivot:
                        continue
                    pivots += 1
                    # every action of this turn in a step before the pivot's came before it
                    for prev in ss[:i]:
                        for b in prev.values():
                            if not isinstance(b, Blind) and b.turn == t:
                                assert b.order < a.order, (row["id"], t, a, b)
                    moved += any(b is not a for b in s.values())
    assert pivots > 50
    assert moved > 0  # (the foe's later move: in the pivot's own step)


LOG = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Garchomp, M|
|poke|p1|Dondozo, M|
|poke|p1|Blissey, F|
|poke|p2|Gholdengo|
|poke|p2|Kingambit, M|
|start
|switch|p1a: Garchomp|Garchomp, M|100/100
|switch|p2a: Gholdengo|Gholdengo|100/100
|turn|1
|move|p2a: Gholdengo|Stealth Rock|p1a: Garchomp
|-sidestart|p1: Alice|move: Stealth Rock
|move|p1a: Garchomp|Earthquake|p2a: Gholdengo
|-damage|p2a: Gholdengo|10/100
|upkeep
|turn|2
|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp
|-damage|p1a: Garchomp|0 fnt
|faint|p1a: Garchomp
|upkeep
|switch|p1a: Dondozo|Dondozo, M|100/100
|-damage|p1a: Dondozo|0 fnt|[from] Stealth Rock
|faint|p1a: Dondozo
|switch|p1a: Blissey|Blissey, F|100/100
|-damage|p1a: Blissey|88/100|[from] Stealth Rock
|turn|3
|move|p2a: Gholdengo|Make It Rain|p1a: Blissey
|-damage|p1a: Blissey|50/100
|-enditem|p1a: Blissey|Eject Button
|switch|p1a: Dondozo|Dondozo, M|100/100
|turn|4
|win|Bob
"""


def test_an_eject_buttons_switch_is_a_pivot_and_hazard_faints_are_rounds():
    """2026-10-22 review: the switch an Eject Button made before its side moved was the turn's
    chosen one (KIND_MAIN); a replacement that fainted to the hazards as it came in and the
    next one were one forced step, the last one's."""
    rep = parse_replay({"id": "t1", "log": LOG, "rating": None, "uploadtime": 0})
    ej = [a for a in rep.actions if a.turn == 3 and a.side == "p1"]
    assert len(ej) == 1 and ej[0].pivot and not ej[0].forced
    steps = decision_steps(rep.actions)
    assert [sorted(s) for s in steps[2]] == [["p2"], ["p1"], ["p1"]]
    assert [s["p1"].to for s in steps[2][1:]] == ["Dondozo", "Blissey"]
    assert [sorted(s) for s in steps[3]] == [["p2"], ["p1"]]


def test_positions_of_hazard_faint_rounds_and_an_eject():
    import random

    import poke_engine as pe

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.train.positions import KIND_BLIND, KIND_FORCED, KIND_PIVOT, positions_from_replay

    ps = positions_from_replay({"id": "t1", "log": LOG, "rating": None, "uploadtime": 0},
                               BeliefModel.load(), random.Random(0), pool="all", per_game=99)  # fmt: skip
    mine = [p for p in ps if p.side == "p1"]
    forced = [p for p in mine if p.kind == KIND_FORCED and p.turn == 2]
    assert len(forced) == 2, [(p.turn, p.kind) for p in mine]
    # the second round: Dondozo down already (it came in and fainted), Blissey the choice
    for p, gone in zip(forced, ("garchomp", "dondozo")):
        st = pe.State.from_string(p.state)
        act = st.side_one.pokemon[int(st.side_one.active_index)]
        assert act.id.lower() == gone and act.hp == 0, (act.id, act.hp)
    # (turn 3: its chosen action unseen -- out before it moved -- a Blind; the Eject's a pivot)
    assert [p.kind for p in mine if p.turn == 3] == [KIND_BLIND, KIND_PIVOT]
