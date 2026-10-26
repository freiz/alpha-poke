"""The request against the engine state (agents/consistency.py, 2026-10-11)."""

from types import SimpleNamespace

import poke_engine as pe

from alpha_poke.agents.consistency import request_mismatch


def state(moves, bench=(("garchomp", 100),)):
    act = pe.Pokemon(id="pecharunt", hp=100, moves=[pe.Move(id=m, pp=pp) for m, pp in moves])
    mons = [act] + [pe.Pokemon(id=s, hp=hp) for s, hp in bench]
    return pe.State(side_one=pe.Side(pokemon=mons, active_index=pe.PokemonIndex("0")))


def battle(moves=(), switches=(), force_switch=False):
    return SimpleNamespace(available_moves=[SimpleNamespace(id=m) for m in moves],
                           available_switches=[SimpleNamespace(species=s) for s in switches],
                           force_switch=force_switch)  # fmt: skip


def test_consistent():
    s = state([("shadowball", 10), ("recover", 3)])
    assert request_mismatch(battle(["shadowball", "recover"], ["garchomp"]), s) == []


def test_move_without_pp_in_the_engine():
    s = state([("shadowball", 10), ("recover", 0)])
    issues = request_mismatch(battle(["shadowball", "recover"]), s)
    assert issues == ["move recover: pp 0, disabled False"]


def test_revival_blessing_like_switch():
    # the request offers a fainted mon (Revival Blessing): the engine's bench has none alive
    s = state([("shadowball", 10)], bench=(("garchomp", 0), ("dondozo", 100)))
    issues = request_mismatch(battle(switches=["garchomp"], force_switch=True), s)
    assert issues == ["switch garchomp: not a live benched mon in the engine"]


def test_struggle_is_fine():
    s = state([("shadowball", 0)])
    assert request_mismatch(battle(["struggle"]), s) == []


def test_greninja_bond_is_the_requests_greninja():
    """The engine's Greninja-Bond is the request's "greninja" (slots.order_of maps it by prefix):
    no mismatch -- 2026-10-25, the A/B's logs, 867 false warnings."""
    s = state([("shadowball", 10)], bench=(("greninjabond", 100),))
    assert request_mismatch(battle(switches=["greninja"]), s) == []
