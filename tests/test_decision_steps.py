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
|poke|p1|Corviknight, M|
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
|switch|p1a: Corviknight|Corviknight, M|100/100
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
    # (turn 3: its chosen action unseen -- out before it moved -- a Blind; the Eject's a pivot --
    # to Corviknight: the log had the fainted Dondozo come back, no option, 2026-10-24)
    assert [p.kind for p in mine if p.turn == 3] == [KIND_BLIND, KIND_PIVOT]


LOG2 = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Dragapult, M|
|poke|p1|Garchomp, M|
|poke|p1|Blissey, F|
|poke|p2|Gholdengo|
|poke|p2|Kingambit, M|
|start
|switch|p1a: Dragapult|Dragapult, M|100/100
|switch|p2a: Gholdengo|Gholdengo|100/100
|turn|1
|move|p2a: Gholdengo|Sticky Web|p1a: Dragapult
|-sidestart|p1: Alice|move: Sticky Web
|move|p1a: Dragapult|Hex|p2a: Gholdengo
|-damage|p2a: Gholdengo|80/100
|upkeep
|turn|2
|move|p1a: Dragapult|U-turn|p2a: Gholdengo
|-damage|p2a: Gholdengo|70/100
|switch|p1a: Garchomp|Garchomp, M|100/100
|-activate|p1a: Garchomp|move: Sticky Web
|-unboost|p1a: Garchomp|spe|1
|-enditem|p1a: Garchomp|Eject Pack
|switch|p1a: Blissey|Blissey, F|100/100
|move|p2a: Gholdengo|Tackle|p1a: Blissey
|-damage|p1a: Blissey|82/100
|upkeep
|turn|3
|win|Bob
"""


def test_a_move_after_two_pivots_is_the_last_ones():
    """2026-10-23 review: a U-turn's switch-in, its Eject Pack's switch, then the foe's move: the
    move is in the second pivot's step (it was in the first's: the Eject Pack's choice of Blissey
    had the Tackle and its damage in its history; the log so far does not)."""
    rep = parse_replay({"id": "t2", "log": LOG2, "rating": None, "uploadtime": 0})
    steps = decision_steps(rep.actions)[2]
    assert [sorted(s) for s in steps] == [["p1"], ["p1"], ["p1", "p2"]], steps
    assert [steps[1]["p1"].to, steps[2]["p1"].to] == ["Garchomp", "Blissey"]
    assert steps[2]["p2"].move == "Tackle"


LOG3 = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Pikachu, M|
|poke|p1|Garchomp, M|
|poke|p1|Blissey, F|
|poke|p2|Gholdengo|
|poke|p2|Kingambit, M|
|start
|switch|p1a: Pikachu|Pikachu, M|100/100
|switch|p2a: Gholdengo|Gholdengo|100/100
|turn|1
|move|p2a: Gholdengo|Sticky Web|p1a: Pikachu
|-sidestart|p1: Alice|move: Sticky Web
|move|p1a: Pikachu|Thunderbolt|p2a: Gholdengo
|-damage|p2a: Gholdengo|80/100
|upkeep
|turn|2
|move|p2a: Gholdengo|Make It Rain|p1a: Pikachu
|-damage|p1a: Pikachu|0 fnt
|faint|p1a: Pikachu
|upkeep
|switch|p1a: Garchomp|Garchomp, M|100/100
|-activate|p1a: Garchomp|move: Sticky Web
|-unboost|p1a: Garchomp|spe|1
|-enditem|p1a: Garchomp|Eject Pack
|switch|p1a: Blissey|Blissey, F|100/100
|turn|3
|win|Bob
"""


def test_a_pivot_after_a_faints_replacement_comes_after_it():
    """2026-10-23 review: Pikachu faints, Garchomp is chosen, its entry sets off the Eject Pack,
    Blissey is chosen: the replacement's step first (its history without the Eject Pack's
    switch), then the pivot's (with the replacement). Before: every pivot, then the rounds."""
    rep = parse_replay({"id": "t3", "log": LOG3, "rating": None, "uploadtime": 0})
    steps = decision_steps(rep.actions)[2]
    p1 = [s["p1"] for s in steps if "p1" in s]
    assert [(a.to, a.forced, a.pivot) for a in p1] == [("Garchomp", True, False), ("Blissey", False, True)]


LOG_PAR = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Slowking-Galar, M|
|poke|p1|Zamazenta|
|poke|p2|Slowking-Galar, F|
|poke|p2|Heatran, M|
|start
|switch|p1a: Slowking|Slowking-Galar, M|100/100 par
|switch|p2a: Slowking|Slowking-Galar, F|100/100
|turn|1
|move|p2a: Slowking|Chilly Reception|p2a: Slowking
|-weather|Snow
|switch|p2a: Heatran|Heatran, M|100/100|[from] Chilly Reception
|cant|p1a: Slowking|par
|upkeep
|turn|2
|move|p2a: Heatran|Earth Power|p1a: Slowking
|-damage|p1a: Slowking|50/100 par
|move|p1a: Slowking|Sludge Bomb|p2a: Heatran
|-damage|p2a: Heatran|80/100
|upkeep
|turn|3
|win|Bob
"""


def test_a_prevented_action_after_a_pivot_is_in_the_pivots_step():
    """2026-10-23, the causality check (scripts/check_causality.py): the foe's full paralysis came
    after our Chilly Reception's switch -- at that switch-in's choice it has not happened -- but
    the Blind sat in the turn's first step: the training history had it, the live one not."""
    from alpha_poke.train.positions import blind_sides, history_string

    rep = parse_replay({"id": "t4", "log": LOG_PAR, "rating": None, "uploadtime": 0})
    steps = decision_steps(rep.actions, blind_sides(rep))
    first, pivot = steps[1][0], steps[1][1]
    assert "p1" not in first and isinstance(pivot.get("p1"), Blind)
    assert "par" not in history_string(steps, (1, 1), "p2")  # (the pivot's choice: before it)
    assert "par" in history_string(steps, 2, "p2")


LOG_EJECT = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Hatterene, F|
|poke|p1|Dragonite, M|
|poke|p2|Landorus-Therian, M|
|start
|switch|p1a: Hatterene|Hatterene, F|100/100
|switch|p2a: Landorus|Landorus-Therian, M|100/100
|turn|1
|move|p2a: Landorus|U-turn|p1a: Hatterene
|-damage|p1a: Hatterene|90/100
|-enditem|p1a: Hatterene|Eject Button
"""


def test_an_eject_before_its_switch_is_already_a_blind():
    """2026-10-23, the causality check: the log cut at an ejected side's switch-in choice (the
    live one) -- the Eject Button used, its switch not in the log yet -- had no Blind for it, the
    training history (its switch later in the log) and the search's tree a prevented action."""
    from alpha_poke.train.positions import blind_sides

    rep = parse_replay({"id": "t5", "log": LOG_EJECT, "rating": None, "uploadtime": 0})
    b = blind_sides(rep)
    assert b.get((1, "p1")) is not None and b[(1, "p1")].kind == "p"


LOG_REVIVE = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Reuniclus, M|
|poke|p1|Pawmot, F|
|poke|p2|Venusaur, M|
|start
|switch|p1a: Reuniclus|Reuniclus, M|100/100
|switch|p2a: Venusaur|Venusaur, M|100/100
|turn|1
|move|p2a: Venusaur|Weather Ball|p1a: Reuniclus
|-damage|p1a: Reuniclus|0 fnt
|faint|p1a: Reuniclus
|upkeep
|switch|p1a: Pawmot|Pawmot, F|100/100
|turn|2
|move|p1a: Pawmot|Revival Blessing|p1a: Pawmot
|-heal|p1: Reuniclus|50/100|[from] move: Revival Blessing
|move|p2a: Venusaur|Growth|p2a: Venusaur
|-boost|p2a: Venusaur|atk|1
|upkeep
|turn|3
|switch|p1a: Reuniclus|Reuniclus, M|50/100
|move|p2a: Venusaur|Weather Ball|p1a: Reuniclus
|-damage|p1a: Reuniclus|0 fnt
|faint|p1a: Reuniclus
|upkeep
|switch|p1a: Pawmot|Pawmot, F|100/100
|turn|4
|win|Bob
"""


def test_a_revived_mons_first_faint_is_a_blind():
    """2026-10-23, the causality check: a mon fainted before acting, brought back by Revival
    Blessing, fainted again later -- its record kept the last turn only: the first turn's
    "fainted before acting" was missing from the training history, the live one (the log so
    far) had it."""
    from alpha_poke.train.positions import blind_sides

    rep = parse_replay({"id": "t6", "log": LOG_REVIVE, "rating": None, "uploadtime": 0})
    b = blind_sides(rep)
    assert b.get((1, "p1")) is not None and b[(1, "p1")].kind == "d"


def test_a_faint_or_an_eject_after_a_pivot_is_in_the_pivots_step():
    """2026-10-23, the causality check: the foe's active fainted before acting -- or was ejected
    -- after our Chilly Reception's switch: at that switch-in's choice it had not happened, the
    Blind sat in the turn's first step all the same (the prevented ones' fix covered |cant| only)."""
    from alpha_poke.train.positions import blind_sides, history_string

    for tail, kind in (("|-damage|p1a: Mimikyu|0 fnt|[from] Stealth Rock\n|faint|p1a: Mimikyu", "d"),
                       ("|-damage|p1a: Mimikyu|80/100\n|-enditem|p1a: Mimikyu|Eject Button\n"
                        "|switch|p1a: Zamazenta|Zamazenta|100/100", "p")):  # fmt: skip
        log = LOG_PAR.replace("Slowking-Galar, M|100/100 par", "Mimikyu, F|100/100").replace(
            "|switch|p1a: Slowking|", "|switch|p1a: Mimikyu|").replace(
            "|cant|p1a: Slowking|par", tail).replace("|poke|p1|Slowking-Galar, M|", "|poke|p1|Mimikyu, F|")
        log = log.split("|upkeep\n|turn|2")[0] + "|upkeep\n|turn|2\n|win|Bob\n"
        rep = parse_replay({"id": "t7", "log": log, "rating": None, "uploadtime": 0})
        steps = decision_steps(rep.actions, blind_sides(rep))
        assert "p1" not in steps[1][0], (kind, steps[1])
        hist = history_string(steps, (1, 1), "p2")  # (the pivot's choice: before the faint / eject)
        assert f"{kind}:MIMIKYU" not in hist, hist
        assert f"{kind}:MIMIKYU" in history_string(steps, 2, "p2")


def test_a_tera_whose_mon_fainted_first_is_no_later_mons():
    """2026-10-23, the tree's history check (scripts/check_tree_history.py): Manaphy
    terastallized, a priority move knocked it out before it moved -- the side's next mon's next
    move read as a tera one in the history (the parser's pending tera was never cleared)."""
    log = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Raging Bolt|
|poke|p2|Manaphy|
|poke|p2|Dragonite, M|
|start
|switch|p1a: Raging Bolt|Raging Bolt|100/100
|switch|p2a: Manaphy|Manaphy|100/100
|turn|1
|-terastallize|p2a: Manaphy|Fairy
|move|p1a: Raging Bolt|Thunderclap|p2a: Manaphy
|-damage|p2a: Manaphy|0 fnt
|faint|p2a: Manaphy
|upkeep
|switch|p2a: Dragonite|Dragonite, M|100/100
|turn|2
|move|p2a: Dragonite|Dragon Dance|p2a: Dragonite
|-boost|p2a: Dragonite|atk|1
|move|p1a: Raging Bolt|Thunderbolt|p2a: Dragonite
|-damage|p2a: Dragonite|60/100
|upkeep
|turn|3
|win|Bob
"""
    rep = parse_replay({"id": "t8", "log": log, "rating": None, "uploadtime": 0})
    dd = next(a for a in rep.actions if a.move == "Dragon Dance")
    assert not dd.tera


def test_a_tera_whose_move_was_stopped_is_no_later_moves():
    """2026-10-24, the tree's history check: Pecharunt terastallized, Taunt stopped its Toxic
    (|cant|) -- its next turn's move read as a tera one (the pending tera kept past the turn)."""
    log = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Pecharunt|
|poke|p2|Landorus-Therian, M|
|start
|switch|p1a: Pecharunt|Pecharunt|100/100
|switch|p2a: Landorus|Landorus-Therian, M|100/100
|turn|1
|-terastallize|p1a: Pecharunt|Water
|move|p2a: Landorus|Taunt|p1a: Pecharunt
|-start|p1a: Pecharunt|move: Taunt
|cant|p1a: Pecharunt|move: Taunt|Toxic
|upkeep
|turn|2
|move|p1a: Pecharunt|Shadow Ball|p2a: Landorus
|-damage|p2a: Landorus|67/100
|upkeep
|turn|3
|win|Bob
"""
    rep = parse_replay({"id": "t9", "log": log, "rating": None, "uploadtime": 0})
    ball = next(a for a in rep.actions if a.move == "Shadow Ball")
    assert not ball.tera


def test_a_switch_a_bounced_parting_shot_made_is_no_chosen_switch():
    """2026-10-24, the tree's history check: Espeon's Magic Bounce sent Parting Shot back, its
    switch out ("[from] Parting Shot") read as its chosen action -- its own move lost: ejected,
    prevented (the bounced move's line is "[from] ability: Magic Bounce": not its action)."""
    from alpha_poke.train.positions import blind_sides

    log = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Grimmsnarl, M|
|poke|p2|Espeon, F|
|poke|p2|Furret, M|
|start
|switch|p1a: Grimmsnarl|Grimmsnarl, M|100/100
|switch|p2a: Espeon|Espeon, F|100/100
|turn|1
|move|p1a: Grimmsnarl|Parting Shot|p2a: Espeon
|move|p2a: Espeon|Parting Shot|p1a: Grimmsnarl|[from] ability: Magic Bounce
|-unboost|p1a: Grimmsnarl|atk|1
|-unboost|p1a: Grimmsnarl|spa|1
|
|switch|p2a: Furret|Furret, M|100/100|[from] Parting Shot
|upkeep
|turn|2
|win|Alice
"""
    rep = parse_replay({"id": "t10", "log": log, "rating": None, "uploadtime": 0})
    steps = decision_steps(rep.actions, blind_sides(rep))
    a = steps[1][0]["p2"]
    assert getattr(a, "kind", None) == "p" and a.reason == "ejected", steps[1]


def test_a_mon_left_at_one_hp_that_fainted_first_is_a_blind():
    """2026-10-24, the tree's history check: a Glimmora left at 1/307 by its Focus Sash read as
    0% -- as fainted -- at the next turn's start; knocked out before it moved, it had no "fainted
    before acting" (the search's tree has it)."""
    from alpha_poke.train.positions import blind_sides

    log = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Glimmora, M|
|poke|p1|Enamorus, F|
|poke|p2|Great Tusk|
|start
|switch|p1a: Glimmora|Glimmora, M|307/307
|switch|p2a: Great Tusk|Great Tusk|371/371
|turn|1
|move|p2a: Great Tusk|Headlong Rush|p1a: Glimmora
|-damage|p1a: Glimmora|1/307
|-enditem|p1a: Glimmora|Focus Sash
|move|p1a: Glimmora|Spiky Shield|p1a: Glimmora
|upkeep
|turn|2
|move|p2a: Great Tusk|Rapid Spin|p1a: Glimmora
|-damage|p1a: Glimmora|0 fnt
|faint|p1a: Glimmora
|upkeep
|switch|p1a: Enamorus|Enamorus, F|289/289
|turn|3
|win|Bob
"""
    rep = parse_replay({"id": "t11", "log": log, "rating": None, "uploadtime": 0})
    b = blind_sides(rep)
    assert b.get((2, "p1")) is not None and b[(2, "p1")].kind == "d", b


def test_a_locked_move_then_a_faint_is_no_blind():
    """2026-10-24, the tree's history check: Roaring Moon's locked Outrage ("[from]lockedmove":
    no decision, no action) came, then Lugia knocked it out -- it read as "fainted before acting"
    (no action of its own, a faint); the search's tree has no action, as for any locked turn."""
    from alpha_poke.train.positions import blind_sides

    log = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Lugia|
|poke|p2|Roaring Moon|
|poke|p2|Keldeo-Resolute|
|start
|switch|p1a: Lugia|Lugia|100/100
|switch|p2a: Roaring Moon|Roaring Moon|100/100
|turn|1
|move|p2a: Roaring Moon|Outrage|p1a: Lugia
|-damage|p1a: Lugia|80/100
|move|p1a: Lugia|Aeroblast|p2a: Roaring Moon
|-damage|p2a: Roaring Moon|40/100
|upkeep
|turn|2
|move|p2a: Roaring Moon|Outrage|p1a: Lugia|[from] lockedmove
|-damage|p1a: Lugia|40/100
|-start|p2a: Roaring Moon|confusion|[fatigue]
|move|p1a: Lugia|Aeroblast|p2a: Roaring Moon
|-damage|p2a: Roaring Moon|0 fnt
|faint|p2a: Roaring Moon
|upkeep
|switch|p2a: Keldeo|Keldeo-Resolute|100/100
|turn|3
|win|Alice
"""
    rep = parse_replay({"id": "t12", "log": log, "rating": None, "uploadtime": 0})
    assert (2, "p2") not in blind_sides(rep)


def test_a_bounced_parting_shot_before_its_switch_is_already_a_blind():
    """2026-10-24, the causality check: the log cut at the switch-in choice of the Magic Bounce
    holder a bounced Parting Shot sends out (the live one: its switch not in the log yet) had no
    Blind for it, the training history (its switch later in the log) "ejected" -- as C3's eject."""
    from alpha_poke.train.positions import blind_sides

    log = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Grimmsnarl, M|
|poke|p2|Hatterene, F|
|poke|p2|Furret, M|
|start
|switch|p1a: Grimmsnarl|Grimmsnarl, M|100/100
|switch|p2a: Hatterene|Hatterene, F|100/100
|turn|1
|move|p1a: Grimmsnarl|Parting Shot|p2a: Hatterene
|move|p2a: Hatterene|Parting Shot|p1a: Grimmsnarl|[from] ability: Magic Bounce
|-unboost|p1a: Grimmsnarl|atk|1
|-unboost|p1a: Grimmsnarl|spa|1
"""
    rep = parse_replay({"id": "t13", "log": log, "rating": None, "uploadtime": 0})
    b = blind_sides(rep)
    assert b.get((1, "p2")) is not None and b[(1, "p2")].kind == "p" and b[(1, "p2")].reason == "ejected", b
