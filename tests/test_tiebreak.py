"""The root tie-break (agents.tiebreak, 2026-10-14)."""

import poke_engine as pe

from alpha_poke.agents.tiebreak import TieBreak, choose, progress


def state():
    moves = [pe.Move(id="earthquake", pp=10), pe.Move(id="splash", pp=10)]
    us = pe.Pokemon(id="garchomp", hp=300, maxhp=300, attack=300, speed=300, moves=moves)
    them = pe.Pokemon(id="tinglu", hp=30, maxhp=400, speed=50,
                      moves=[pe.Move(id="splash", pp=10)])  # fmt: skip
    s1 = pe.Side(pokemon=[us, pe.Pokemon(id="dondozo", hp=400, maxhp=400)],
                 active_index=pe.PokemonIndex("0"))  # fmt: skip
    s2 = pe.Side(pokemon=[them, pe.Pokemon(id="gholdengo", hp=300, maxhp=300)],
                 active_index=pe.PokemonIndex("0"))  # fmt: skip
    return pe.State(side_one=s1, side_two=s2).to_string()


def test_progress_prefers_the_ko():
    s = state()
    assert progress(s, 0, 0) > 0.3 > abs(progress(s, 1, 0))  # Earthquake KOs, Splash nothing


def test_choose_only_in_a_won_tie():
    s, cands = state(), [0, 1]
    visits = [40] * 14
    visits[1] = 60  # Splash most visited
    means = [0.95] * 14
    assert choose(s, cands, visits, means, 0.95, 0, TieBreak()) == 0  # tied: the KO
    assert choose(s, cands, visits, means, 0.6, 0, TieBreak()) is None  # not ahead enough
    means[0] = 0.9  # Earthquake clearly worse by the search: no tie
    assert choose(s, cands, visits, means, 0.95, 0, TieBreak()) is None
