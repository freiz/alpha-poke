"""Dual-engine unit tests (doc/engine-diff.md): a scenario run in Showdown's simulator and in
poke-engine from the same state (alpha_poke.enginecheck). A confirmed engine issue is an
``xfail(strict=True)`` test until it is fixed; the controls show the harness agrees where the
engines do."""

import shutil

import poke_engine as pe
import pytest

from alpha_poke import enginecheck as ec

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (ec.SIM / "index.js").exists(),
    reason="needs node and the built Showdown checkout (vendor/pokemon-showdown/dist/sim)",
)

CORVIKNIGHT = """Corviknight @ Leftovers
Ability: Pressure
Tera Type: Dragon
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Defog
- Roost
- Brave Bird
- U-turn"""

TINGLU = """Ting-Lu @ Leftovers
Ability: Vessel of Ruin
Tera Type: Poison
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Spikes
- Ruination
- Earthquake
- Whirlwind"""


def first_turn(c1: str, c2: str, e1: str, e2: str, p1=CORVIKNIGHT, p2=TINGLU, **kw):
    """(Showdown's states before / after one turn, poke-engine's outcomes from the same state)."""
    states = ec.run_showdown(p1, p2, [(c1, c2)], **kw)
    before = ec.engine_state(states[0])
    return states, ec.engine_outcomes(before, e1, e2)


def test_start_state_is_the_same():
    states, _ = first_turn("move roost", "move spikes", "roost", "spikes")
    n = (len(states[0]["sides"][0]["mons"]), len(states[0]["sides"][1]["mons"]))
    assert ec.diff(ec.view_engine(ec.engine_state(states[0]), n), ec.view(states[0])) == {}


def test_control_spikes_and_roost_agree():
    states, outs = first_turn("move roost", "move spikes", "roost", "spikes")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


@pytest.mark.xfail(strict=True, reason="L1 (doc/engine-diff.md): poke-engine's Defog does not "
                                       "lower the target's evasion")  # fmt: skip
def test_l1_defog_lowers_evasion():
    states, outs = first_turn("move defog", "move spikes", "defog", "spikes")
    assert states[1]["sides"][1]["mons"][0]["boosts"]["evasion"] == -1  # Showdown
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


def test_control_volatile_of_engine_state_string():
    # a state without volatile statuses serializes and parses back unchanged
    s = pe.State(side_one=pe.Side(pokemon=[pe.Pokemon.create_fainted()] * 6))
    assert pe.State.from_string(s.to_string()).side_one.volatile_statuses == set()


L4 = "L4 (doc/engine-diff.md): a volatile serializes as 'SALTCURE:', parses back with a NONE"


@pytest.mark.xfail(strict=True, reason=L4)
def test_l4_volatile_roundtrip():
    s = pe.State(side_one=pe.Side(pokemon=[pe.Pokemon.create_fainted()] * 6,
                                  volatile_statuses={"saltcure"}))  # fmt: skip
    assert pe.State.from_string(s.to_string()).side_one.volatile_statuses == {"SALTCURE"}


TINGLU_SPIKES = ("move spikes", "spikes")
SKELEDIRGE = """Skeledirge @ Leftovers
Ability: Unaware
Tera Type: Fairy
EVs: 248 HP / 8 SpA / 252 Def
Bold Nature
- Curse
- Slack Off
- Torch Song
- Shadow Ball"""
URSALUNA = """Ursaluna @ Leftovers
Ability: Bulletproof
Tera Type: Normal
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Curse
- Facade
- Headlong Rush
- Protect"""
GARGANACL = """Garganacl @ Leftovers
Ability: Purifying Salt
Tera Type: Water
EVs: 252 HP / 4 Atk / 252 Def
Impish Nature
- Salt Cure
- Recover
- Protect
- Iron Defense"""
TOXAPEX = """Toxapex @ Black Sludge
Ability: Regenerator
Tera Type: Fairy
EVs: 252 HP / 4 Def / 252 SpD
Calm Nature
- Infestation
- Recover
- Haze
- Toxic"""
KYUREM = """Kyurem @ Leftovers
Ability: Pressure
Tera Type: Ground
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Substitute
- Freeze-Dry
- Earth Power
- Protect"""


def test_control_salt_cure_and_infestation_agree():
    for team, move in ((GARGANACL, "saltcure"), (TOXAPEX, "infestation")):
        states, outs = first_turn(f"move {move}", "move spikes", move, "spikes", p1=team,
                                  force_random=True)  # fmt: skip
        assert ec.closest(states[1], outs, (1, 1))["diff"] == {}, move


@pytest.mark.xfail(strict=True, reason="L2a (doc/engine-diff.md): poke-engine has only the "
                                       "non-Ghost Curse (boosts, no HP cost, no curse on the "
                                       "target)")  # fmt: skip
def test_l2a_ghost_curse():
    states, outs = first_turn("move curse", "move spikes", "curse", "spikes", p1=SKELEDIRGE,
                              force_random=True)  # fmt: skip
    assert "curse" in states[1]["sides"][1]["mons"][0]["volatiles"]  # Showdown: the target
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


@pytest.mark.xfail(strict=True, reason="L2b (doc/engine-diff.md): poke-engine's non-Ghost Curse "
                                       "also puts a (harmless) curse on the user")  # fmt: skip
def test_l2b_non_ghost_curse_no_volatile():
    states, outs = first_turn("move curse", "move spikes", "curse", "spikes", p1=URSALUNA)
    assert states[1]["sides"][0]["mons"][0]["volatiles"] == {}  # Showdown
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


@pytest.mark.xfail(strict=True, reason="L2d (doc/engine-diff.md): poke-engine applies Salt "
                                       "Cure's volatile through a Substitute")  # fmt: skip
def test_l2d_salt_cure_blocked_by_substitute():
    states, outs = first_turn("move saltcure", "move substitute", "saltcure", "substitute",
                              p1=GARGANACL, p2=KYUREM, force_random=True)  # fmt: skip
    assert states[1]["sides"][1]["mons"][0]["volatiles"] == {}  # Showdown: the Sub took it
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


@pytest.fixture(scope="module")
def belief():
    from alpha_poke.agents.belief_state import BeliefModel

    return BeliefModel.load()


def built_volatiles(p1, move, belief) -> tuple[set, set, set]:
    """(Showdown's volatiles of Ting-Lu after ``move`` hits it, ours from its own view, ours
    from the attacker's view) -- our state construction (build_state) in gen9ou."""
    states = ec.run_showdown(p1, TINGLU, [(f"move {move}", "move spikes")], fmt="gen9ou",
                             force_random=True)  # fmt: skip
    truth = set(states[1]["sides"][1]["mons"][0]["volatiles"])
    own = {
        str(v).lower() for v in ec.built_state(states, 1, "p2", belief).side_one.volatile_statuses
    }
    opp = {
        str(v).lower() for v in ec.built_state(states, 1, "p1", belief).side_two.volatile_statuses
    }
    return truth, own - {"none"}, opp - {"none"}


def test_control_built_state_salt_cure_and_curse(belief):
    for team, move in ((GARGANACL, "saltcure"), (SKELEDIRGE, "curse")):
        truth, own, opp = built_volatiles(team, move, belief)
        assert truth == own == opp, (move, truth, own, opp)


@pytest.mark.xfail(strict=True, reason="L2c (doc/engine-diff.md): build_state leaves out partial "
                                       "trapping (Infestation, Whirlpool, ...)")  # fmt: skip
def test_l2c_built_state_partial_trap(belief):
    truth, own, opp = built_volatiles(TOXAPEX, "infestation", belief)
    assert truth == {"partiallytrapped"}
    assert own == opp == truth
