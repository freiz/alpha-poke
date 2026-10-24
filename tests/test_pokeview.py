"""Plan C (doc/state-diff.md): the state construction reads poke-env's mons through one layer
(agents/pokeview: ``own_*`` / ``current_*``) and names actions in one vocabulary (agents/slots,
the slots alpha_search's).

The guard: in agents/engine_state.py, the attributes poke-env mixes up for a transformed mon or
one with a temporary ability (``moves``, ``ability``, ``base_ability``, ``base_stats``,
``stats``, ``weight``, ...) are read only on the engine's / the sets' objects -- the receivers
below, each one checked to be no poke-env mon. A new read on another receiver fails here: read
it through pokeview, or add the receiver if it is no poke-env mon."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARDED = {"moves", "ability", "base_ability", "base_stats", "_base_stats", "stats", "weight",
           "temporary_ability", "_moves", "_temporary_ability", "_ability"}  # fmt: skip
# receivers of those attributes in engine_state that are not poke-env mons
NOT_POKE_ENV = {
    "engine_mon",  # an engine pe.Pokemon (_last_move, _pending_move)
    "em",  # the engine mon of a lock (the lock's other moves disabled)
    "setter",  # the engine mon that set a screen / the weather (its world's ability)
    "p",  # an engine pe.Pokemon (_formes, _as_transformed)
    "s",  # a SampledSet
    "known",  # a KnownSet
    "GEN",  # poke-env's GenData (its moves table)
    "q[1]",  # an engine mon beside its poke-env one (q[0]): the Regenerator check
    "mons[i]",  # the built engine mons (our_mons / their_mons)
}
NOT_POKE_ENV_PREFIXES = ("our_mons[", "their_mons[", "their_sets[")  # engine mons / SampledSets


def test_engine_state_reads_poke_env_mons_through_pokeview():
    tree = ast.parse((ROOT / "src/alpha_poke/agents/engine_state.py").read_text())
    bad = sorted({(n.lineno, f"{ast.unparse(n.value)}.{n.attr}") for n in ast.walk(tree)
                  if isinstance(n, ast.Attribute) and n.attr in GUARDED
                  and ast.unparse(n.value) not in NOT_POKE_ENV
                  and not ast.unparse(n.value).startswith(NOT_POKE_ENV_PREFIXES)})  # fmt: skip
    assert not bad, bad


def test_pokeview_reads_own_and_current_values():
    """A transformed mon: its own moves / base stats are its set's, its current moves the copied
    ones; a temporary ability is its current one, not its own."""
    from poke_env.battle import Pokemon

    from alpha_poke.agents import pokeview as pv

    ditto = Pokemon(species="ditto", gen=9)
    ditto._add_move("transform")
    own_base = dict(pv.own_base_stats(ditto))
    target = Pokemon(species="greattusk", gen=9)
    target._add_move("headlongrush")
    ditto.transform(target)
    assert list(pv.own_moves(ditto)) == ["transform"]
    assert "headlongrush" in pv.current_moves(ditto)
    assert pv.own_base_stats(ditto) == own_base and own_base["hp"] == 48
    assert pv.own_weight(ditto) == 4.0
    mon = Pokemon(species="gardevoir", gen=9)
    mon.ability = "trace"
    mon.ability = "intimidate"  # (poke-env: a second one is temporary -- Trace's)
    assert pv.own_ability(mon) == "trace" and pv.current_ability(mon) == "intimidate"


# (the option names' round trip -- each state's options by name are the true state's, each one an
# order of the battle -- runs at every decision of the state-construction differential:
# enginecheck/statebuild.option_diffs, its kinds pinned by tests/test_state_build.py's baselines)


def test_a_switch_order_by_the_engines_forme_name():
    """The engine names a Battle Bond Greninja "greninjabond", poke-env by the log's details
    "greninja" (2026-10-24, plan C's round trip: the search's switch to it had no order)."""
    from types import SimpleNamespace

    from alpha_poke.agents import slots

    player = SimpleNamespace(create_order=lambda m, **kw: m)
    gren, tusk = SimpleNamespace(species="greninja"), SimpleNamespace(species="greattusk")
    battle = SimpleNamespace(available_switches=[gren, tusk], available_moves=[], can_tera=False)
    assert slots.order_of(player, battle, "switch greninjabond") is gren
    assert slots.order_of(player, battle, "switch greattusk") is tusk
    assert slots.order_of(player, battle, "switch kingambit") is None


def test_a_mons_own_weight_after_its_transform_ended():
    """poke-env's transform overwrites the weight with its target's and its switch-out keeps it:
    a Ditto out of its Copperajah transform read 650 kg, Showdown's 4 (2026-10-24 review: Heavy
    Slam, Low Kick, Grass Knot from it or at it)."""
    from poke_env.battle import Pokemon

    from alpha_poke.agents import pokeview as pv

    ditto = Pokemon(species="ditto", gen=9)
    ditto.transform(Pokemon(species="copperajah", gen=9))
    assert pv.own_weight(ditto) == 4.0
    ditto.switch_out({})
    assert not ditto.transformed and pv.own_weight(ditto) == 4.0


def test_a_copied_moves_pp_before_its_first_use():
    """Showdown's transformInto: min(5, the move's PP) -- a Revival Blessing's 1 (a replay's Ditto
    read 5, 2026-10-24); poke-env's own count once it is used."""
    from poke_env.battle import Pokemon

    from alpha_poke.agents import pokeview as pv

    ditto = Pokemon(species="ditto", gen=9)
    ditto.transform(Pokemon(species="pawmot", gen=9))
    assert pv.copied_pp(ditto, "revivalblessing") == 1
    assert pv.copied_pp(ditto, "closecombat") == 5
