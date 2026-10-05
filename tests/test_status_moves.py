from types import SimpleNamespace

from poke_env.battle import Pokemon
from poke_env.battle.move import Move

from alpha_poke.agents import status_moves as sm
from alpha_poke.agents.damage import MonView, Spread, calc_stats


def view(species, spread, moves=(), item=None, hp=1.0):
    mon = Pokemon(gen=9, species=species)
    for m in moves:
        mon._add_move(m)
    mon._current_hp, mon._max_hp = round(100 * hp), 100
    return MonView(
        mon, calc_stats(mon.base_stats, Spread.parse(spread)), {item: 1.0} if item else {}
    )


def battle(opp_team=()):
    return SimpleNamespace(
        side_conditions={},
        opponent_side_conditions={},
        weather={},
        fields={},
        team={},
        opponent_team={m.species: m for m in opp_team},
    )


def ctx(mv, ov, ov_moves, incoming, opp_last=None, team=()):
    return sm.Ctx(battle(team), mv, ov, ov_moves, incoming, 6, 6, False, opp_last)


def test_setup_is_worth_more_when_we_can_attack_afterwards():
    me = view("dragonite", "Adamant:0/252/0/0/4/252", ["dragondance", "extremespeed", "earthquake"])
    wall = view("clefable", "Bold:252/0/252/4/0/0")
    weak = [Move("moonblast", gen=9)]
    c = ctx(me, wall, weak, incoming=0.2)
    safe = sm.setup_value(c, Move("dragondance", gen=9))
    risky = sm.setup_value(ctx(me, wall, weak, incoming=0.9), Move("dragondance", gen=9))
    assert safe > risky + 0.1
    wall.ability = "unaware"
    assert sm.setup_value(c, Move("dragondance", gen=9)) <= 0.02


def test_weather_dependent_recovery_is_valued():
    me = view("clefable", "Bold:252/0/252/4/0/0", ["moonlight"], hp=0.4)
    opp = view("gholdengo", "Timid:0/0/0/252/4/252")
    c = ctx(me, opp, [Move("shadowball", gen=9)], incoming=0.2)
    assert sm.heal_value(c, Move("moonlight", gen=9)) >= 0.45


def test_phaze_and_haze_scale_with_the_opponents_boosts():
    me = view("skarmory", "Impish:252/0/252/0/4/0", ["whirlwind"])
    opp = view("dragonite", "Adamant:0/252/0/0/4/252")
    bench = Pokemon(gen=9, species="gholdengo")
    moves = [Move("extremespeed", gen=9), Move("earthquake", gen=9)]
    c = ctx(me, opp, moves, incoming=0.3, team=[opp.mon, bench])
    before = sm.phaze_value(c, Move("whirlwind", gen=9), sm.boost_threat(c))
    opp.mon.boosts["atk"] = 2
    opp.mon.boosts["spe"] = 2
    threat = sm.boost_threat(c)
    assert threat > 0.3
    assert sm.phaze_value(c, Move("whirlwind", gen=9), threat) > before + 0.3
    assert sm.haze_value(c, threat) > 0.3


def test_encore_after_a_setup_move():
    me = view("clefable", "Bold:252/0/252/4/0/0", ["encore"])
    opp = view("dragonite", "Adamant:0/252/0/0/4/252")
    c = ctx(me, opp, [Move("extremespeed", gen=9)], incoming=0.2, opp_last="dragondance")
    assert sm.encore_value(c, 0.0) >= 0.45
    c.opp_last_move = None
    assert sm.encore_value(c, 0.0) == 0.0


def test_knock_off_values_the_item():
    me = view("kingambit", "Adamant:252/252/0/0/4/0")
    opp = view("dondozo", "Impish:252/0/252/0/4/0", item="leftovers")
    c = ctx(me, opp, [], incoming=0.1)
    assert sm.knock_off_bonus(c) == 0.2
    opp.mon._item = ""  # already knocked off
    assert sm.knock_off_bonus(c) == 0.0
