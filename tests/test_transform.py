"""A transformed active in the engine state (design D17 J, 2026-10-13): Imposter / Transform."""

import logging
import random

import pytest
from poke_env.battle import Battle

from alpha_poke.agents.consistency import request_mismatch
from alpha_poke.agents.engine_state import build_state

AMBIT = ["kowtowcleave", "suckerpunch", "ironhead", "swordsdance"]


def mon(ident, species, moves, active=False, stats=None):
    return {"ident": ident, "details": f"{species}, L100", "condition": "300/300",
            "active": active, "moves": moves, "baseAbility": "imposter" if species == "Ditto"
            else "pressure", "item": "choicescarf", "ability": "imposter",
            "stats": stats or {"atk": 200, "def": 200, "spa": 200, "spd": 200, "spe": 200},
            "teraType": "Normal", "terastallized": ""}  # fmt: skip


def battle(our_ditto: bool) -> Battle:
    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    if our_ditto:
        # a transformed mon's side entry lists its copied moves (Showdown's moveSlots)
        active = mon("p1: Ditto", "Ditto", AMBIT, True)
        moves = [{"move": m, "id": m, "pp": 5, "maxpp": 5, "disabled": False} for m in AMBIT]
        side = [active, mon("p1: Garchomp", "Garchomp", ["earthquake"])]
    else:
        active = mon("p1: Kingambit", "Kingambit", AMBIT, True,
                     {"atk": 369, "def": 276, "spa": 156, "spd": 206, "spe": 198})  # fmt: skip
        moves = [{"move": m, "id": m, "pp": 16, "maxpp": 16, "disabled": False} for m in AMBIT]
        side = [active, mon("p1: Garchomp", "Garchomp", ["earthquake"])]
    # the request comes first (poke-env applies it, then the turn's messages)
    b.parse_request(
        {
            "active": [{"moves": moves}],
            "side": {"name": "us", "id": "p1", "pokemon": side},
            "rqid": 1,
        }
    )
    us, them = ("Ditto", "Kingambit") if our_ditto else ("Kingambit", "Ditto")
    for line in (f"|switch|p1a: {us}|{us}|300/300", f"|switch|p2a: {them}|{them}|100/100",
                 f"|-transform|p{1 if our_ditto else 2}a: Ditto|p{2 if our_ditto else 1}a: "
                 "Kingambit|[from] ability: Imposter", "|turn|1"):  # fmt: skip
        b.parse_message(line.split("|"))
    return b


@pytest.fixture(scope="module")
def belief():
    from alpha_poke.agents.belief_state import BeliefModel

    return BeliefModel.load()


def test_our_ditto_takes_the_targets_moves_and_stats(belief):
    b = battle(our_ditto=True)
    s = build_state(b, belief, ("Ditto", "Garchomp"), random.Random(0))
    ours, theirs = s.side_one.pokemon[0], s.side_two.pokemon[0]
    assert sorted(m.id for m in ours.moves) == sorted(AMBIT)
    # (its own species, as the engine's transform and the differential's states keep it; its
    # own set the switch-out's backup -- 2026-10-23 review: the target's species, no backup)
    assert ours.id == "ditto" and ours.attack == theirs.attack and ours.speed == theirs.speed
    assert ours.transform_backup is not None
    assert ours.hp == 300 and ours.base_ability == "imposter"
    # (L36: the engine's transform / typechange volatiles: a switch ends them)
    assert {"transform", "typechange"} <= {str(v).lower() for v in s.side_one.volatile_statuses}
    assert request_mismatch(b, s) == []


def test_their_ditto_takes_our_moves_and_stats(belief):
    b = battle(our_ditto=False)
    s = build_state(b, belief, ("Kingambit", "Garchomp"), random.Random(0))
    ours, theirs = s.side_one.pokemon[0], s.side_two.pokemon[0]
    assert sorted(m.id for m in theirs.moves) == sorted(AMBIT)
    assert all(m.pp == 5 for m in theirs.moves)
    assert theirs.id == "ditto" and theirs.attack == 369 and theirs.speed == 198
    assert theirs.transform_backup is not None
    assert {"transform", "typechange"} <= {str(v).lower() for v in s.side_two.volatile_statuses}
    assert theirs.maxhp != ours.maxhp or theirs.hp > 0  # its own HP


def test_our_struggling_choice_locked_ditto_keeps_the_locks_flags(belief):
    """2026-10-23 (state-construction differential, S59): our Scarf Ditto's locked copied move out
    of PP, a Struggle, the request Struggle only -- the lock's flags were lost (poke-env's last
    used move is the Struggle): the others disabled, the locked one not."""
    b = battle(our_ditto=True)
    for line in ("|move|p1a: Ditto|Kowtow Cleave|p2a: Kingambit", "|-damage|p2a: Kingambit|80/100",
                 "|upkeep", "|turn|2", "|-activate|p1a: Ditto|move: Struggle",
                 "|move|p1a: Ditto|Struggle|p2a: Kingambit", "|-damage|p2a: Kingambit|70/100",
                 "|upkeep", "|turn|3"):  # fmt: skip
        b.parse_message(line.split("|"))
    side = [mon("p1: Ditto", "Ditto", AMBIT, True), mon("p1: Garchomp", "Garchomp", ["earthquake"])]
    b.parse_request({"active": [{"moves": [{"move": "Struggle", "id": "struggle", "pp": 1, "maxpp": 1,
                                            "disabled": False}]}],
                     "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 3})  # fmt: skip
    s = build_state(b, belief, ("Ditto", "Garchomp"), random.Random(0))
    flags = {m.id: m.disabled for m in s.side_one.pokemon[0].moves if m.id != "none"}
    assert flags.get("kowtowcleave") is False, flags
    assert all(v for k, v in flags.items() if k != "kowtowcleave"), flags
