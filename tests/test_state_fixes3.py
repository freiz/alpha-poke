"""Engine-state fix level 3 (design D17, 2026-10-13): must recharge, the opponent's PP, Perish
Song, Disable, a hit Substitute, items extending screens / weather."""

import logging
import random

import pytest
from poke_env.battle import Battle

from alpha_poke.agents.engine_state import build_state


def mon(ident, species, moves, item="leftovers", ability="pressure", active=False):
    return {"ident": ident, "details": f"{species}, L100", "condition": "400/400",
            "active": active, "moves": moves, "baseAbility": ability, "item": item,
            "ability": ability, "stats": {"atk": 200, "def": 200, "spa": 200, "spd": 200,
                                          "spe": 200},
            "teraType": "Normal", "terastallized": ""}  # fmt: skip


def battle(
    lines,
    us="Garchomp",
    item="leftovers",
    ability="roughskin",
    moves=("earthquake", "reflect", "substitute", "hyperbeam"),
) -> Battle:
    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    side = [mon(f"p1: {us}", us, list(moves), item, ability, True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    req = [{"move": m, "id": m, "pp": 8, "maxpp": 8, "disabled": False} for m in moves]
    b.parse_request(
        {"active": [{"moves": req}], "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 1}
    )
    for line in [f"|switch|p1a: {us}|{us}|400/400", "|switch|p2a: Gholdengo|Gholdengo|100/100",
                 "|turn|1", *lines]:  # fmt: skip
        b.parse_message(line.split("|"))
    return b


@pytest.fixture(scope="module")
def belief():
    from alpha_poke.agents.belief_state import BeliefModel

    return BeliefModel.load()


def state(b, belief, fixes=3):
    return build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(0), fixes=fixes)


def test_must_recharge(belief):
    b = battle(["|move|p1a: Garchomp|Hyper Beam|p2a: Gholdengo", "|-mustrecharge|p1a: Garchomp",
                "|turn|2"])  # fmt: skip
    assert "mustrecharge" in state(b, belief).side_one.volatile_statuses
    assert "mustrecharge" not in state(b, belief, 2).side_one.volatile_statuses


def test_opponent_pp_from_uses(belief):
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|2",
                "|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|3"])  # fmt: skip
    moves = {m.id: m.pp for m in state(b, belief).side_two.pokemon[0].moves}
    assert moves["makeitrain"] == 8 - 2  # 5 PP, 8 with PP Ups
    assert all(pp == 16 for pp in (m.pp for m in state(b, belief, 2).side_two.pokemon[0].moves))


def test_disable_and_perish(belief):
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|2",
                "|-start|p2a: Gholdengo|Disable|Make It Rain", "|-start|p2a: Gholdengo|perish3",
                "|turn|3"])  # fmt: skip
    s = state(b, belief)
    them = s.side_two.pokemon[0]
    assert [m.disabled for m in them.moves if m.id == "makeitrain"] == [True]
    assert "perish3" in s.side_two.volatile_statuses


def test_hit_substitute(belief):
    b = battle(["|move|p1a: Garchomp|Substitute|p1a: Garchomp",
                "|-start|p1a: Garchomp|Substitute", "|turn|2",
                "|-activate|p1a: Garchomp|Substitute|[damage]", "|turn|3"])  # fmt: skip
    assert state(b, belief).side_one.substitute_health == 400 // 4 // 2
    assert state(b, belief, 2).side_one.substitute_health == 400 // 4


def test_light_clay_reflect(belief):
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|turn|2"], item="lightclay")  # fmt: skip
    assert state(b, belief).side_one.side_conditions.reflect == 8 - 1
    assert state(b, belief, 2).side_one.side_conditions.reflect == 5 - 1
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|turn|2"])  # fmt: skip
    assert state(b, belief).side_one.side_conditions.reflect == 5 - 1


def test_heat_rock_drought(belief):
    b = battle(["|-weather|SunnyDay|[from] ability: Drought|[of] p1a: Torkoal", "|turn|2"],
               us="Torkoal", item="heatrock", ability="drought",
               moves=("lavaplume", "rapidspin", "yawn", "stealthrock"))  # fmt: skip
    b._weather = {next(iter(b.weather)): 1}  # set on turn 1
    assert state(b, belief).weather_turns_remaining == 8 - 1
    assert state(b, belief, 2).weather_turns_remaining == 5 - 1


def test_must_recharge_searches_to_the_recharge_order(belief):
    import alpha_search

    from alpha_poke.agents.engine_state import engine_move_to_order

    b = battle(["|move|p1a: Garchomp|Hyper Beam|p2a: Gholdengo", "|-mustrecharge|p1a: Garchomp",
                "|turn|2"])  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Recharge", "id": "recharge"}],
                                 "trapped": True}],
                     "side": {"name": "us", "id": "p1", "pokemon": [
                         mon("p1: Garchomp", "Garchomp", ["earthquake", "reflect", "substitute",
                                                          "hyperbeam"], "leftovers", "roughskin",
                             True), mon("p1: Dondozo", "Dondozo", ["wavecrash"])]},
                     "rqid": 2})  # fmt: skip
    ours, *_ = alpha_search.ismcts([state(b, belief).to_string()], 50, iterations=64)
    player = type("P", (), {"create_order": staticmethod(lambda m, **k: m.id)})()
    assert [engine_move_to_order(player, b, c) for c, _, _ in ours] == ["recharge"]


def test_illusion_worlds(belief):
    b = Battle("battle-gen9ou-2", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    side = [mon("p1: Garchomp", "Garchomp", ["earthquake"], active=True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Earthquake", "id": "earthquake", "pp": 8,
                                            "maxpp": 8, "disabled": False}]}],
                     "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 1})  # fmt: skip
    for line in ["|poke|p2|Gholdengo, L100|", "|poke|p2|Zoroark-Hisui, L100|",
                 "|poke|p2|Great Tusk, L100|", "|switch|p1a: Garchomp|Garchomp|400/400",
                 "|switch|p2a: Gholdengo|Gholdengo|60/100", "|turn|1"]:  # fmt: skip
        b.parse_message(line.split("|"))
    ids = [build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(k), fixes=3)
           for k in range(300)]  # fmt: skip
    act = [s.side_two.pokemon[int(s.side_two.active_index)] for s in ids]
    z = [p for p in act if p.id.startswith("zoroark")]
    assert 0.2 < len(z) / len(act) < 0.47  # one in three alive
    assert all(abs(p.hp / p.maxhp - 0.6) < 0.02 for p in z)
    s2 = build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(0), fixes=2)
    assert s2.side_two.pokemon[int(s2.side_two.active_index)].id == "gholdengo"


def test_recharge_ends_after_the_recharge_turn(belief):
    # poke-env keeps must_recharge until the next move: the turn after recharging is free
    b = battle(["|move|p2a: Gholdengo|Hyper Beam|p1a: Garchomp", "|-mustrecharge|p2a: Gholdengo",
                "|turn|2", "|cant|p2a: Gholdengo|recharge", "|turn|3"])  # fmt: skip
    assert b.opponent_active_pokemon.must_recharge  # (poke-env's stale flag)
    assert "mustrecharge" not in state(b, belief).side_two.volatile_statuses
    b = battle(["|move|p2a: Gholdengo|Hyper Beam|p1a: Garchomp", "|-mustrecharge|p2a: Gholdengo",
                "|turn|2"])  # fmt: skip
    assert "mustrecharge" in state(b, belief).side_two.volatile_statuses


def test_perish_count_is_the_latest(belief):
    b = battle(["|-start|p2a: Gholdengo|perish3", "|turn|2", "|-start|p2a: Gholdengo|perish2",
                "|turn|3"])  # fmt: skip
    vol = state(b, belief).side_two.volatile_statuses
    assert "perish2" in vol and "perish3" not in vol
