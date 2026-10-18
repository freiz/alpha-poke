"""Dual-engine unit tests (doc/engine-diff.md): a scenario run in Showdown's simulator and in
poke-engine from the same state (alpha_poke.enginecheck). A confirmed engine issue is an
``xfail(strict=True)`` test until it is fixed; the controls show the harness agrees where the
engines do."""

import json
import shutil
from pathlib import Path

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


# L1 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l1_defog_lowers_evasion():
    states, outs = first_turn("move defog", "move spikes", "defog", "spikes")
    assert states[1]["sides"][1]["mons"][0]["boosts"]["evasion"] == -1  # Showdown
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


def test_control_volatile_of_engine_state_string():
    # a state without volatile statuses serializes and parses back unchanged
    s = pe.State(side_one=pe.Side(pokemon=[pe.Pokemon.create_fainted()] * 6))
    assert pe.State.from_string(s.to_string()).side_one.volatile_statuses == set()


# L4 (doc/engine-diff.md): fixed 2026-10-16; a regression test now
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


# L2a (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l2a_ghost_curse():
    states, outs = first_turn("move curse", "move spikes", "curse", "spikes", p1=SKELEDIRGE,
                              force_random=True)  # fmt: skip
    assert "curse" in states[1]["sides"][1]["mons"][0]["volatiles"]  # Showdown: the target
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L2b (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l2b_non_ghost_curse_no_volatile():
    states, outs = first_turn("move curse", "move spikes", "curse", "spikes", p1=URSALUNA)
    assert states[1]["sides"][0]["mons"][0]["volatiles"] == {}  # Showdown
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L2d (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
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


# L2c (doc/engine-diff.md): fixed 2026-10-16; a regression test now
def test_l2c_built_state_partial_trap(belief):
    truth, own, opp = built_volatiles(TOXAPEX, "infestation", belief)
    assert truth == {"partiallytrapped"}
    assert own == opp == truth


TYRANITAR = """Tyranitar @ Smooth Rock
Ability: Sand Stream
Tera Type: Ghost
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Protect
- Stealth Rock
- Rock Slide
- Earthquake"""
RILLABOOM = """Rillaboom @ Leftovers
Ability: Grassy Surge
Tera Type: Grass
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Protect
- Grassy Glide
- Wood Hammer
- U-turn"""
BLISSEY = """Blissey @ Heavy-Duty Boots
Ability: Natural Cure
Tera Type: Ghost
EVs: 252 HP / 252 Def / 4 SpD
Bold Nature
- Protect
- Soft-Boiled
- Seismic Toss
- Calm Mind"""


def field_turns(lead: str, kind: str, n: int, belief, view: str = "p2") -> tuple[list, list, list]:
    """(Showdown's remaining turns of the weather / terrain set by ``lead`` (p1) at each of n
    turns, poke-engine's next value from Showdown's state, ours built from ``view``'s side)."""
    states = ec.run_showdown(lead, BLISSEY, [("move protect", "move calmmind")] * n,
                             fmt="gen9ou")  # fmt: skip
    sd = [s["field"][f"{kind}_duration"] for s in states]
    attr = f"{kind}_turns_remaining"
    eng = []
    for k in range(n):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), "protect", "calmmind")
        eng.append(getattr(max(outs, key=lambda o: o[0])[1], attr))
    built = [getattr(ec.built_state(states, k, view, belief), attr) for k in range(n + 1)]
    return sd, eng, built


def test_control_engine_weather_and_terrain_turns(belief):
    for lead, kind in ((TYRANITAR, "weather"), (RILLABOOM, "terrain")):
        sd, eng, _ = field_turns(lead, kind, 6, belief)
        assert eng == [max(d - 1, 0) for d in sd[:-1]], (kind, sd, eng)


# L3a (doc/engine-diff.md): fixed 2026-10-16; a regression test now
def test_l3a_built_weather_turns(belief):
    # the setter's own side knows its Smooth Rock: exactly Showdown's turns
    sd, _, built = field_turns(TYRANITAR, "weather", 9, belief, view="p1")
    assert sd[:9] == [8, 7, 6, 5, 4, 3, 2, 1, 0]  # Showdown: Smooth Rock, 8 turns
    assert built == sd
    # the other side does not (the rock is never revealed): a belief sample, but the weather's
    # turns count down every turn and it ends when Showdown's does
    _, _, opp = field_turns(TYRANITAR, "weather", 9, belief, view="p2")
    seq = opp[:8]
    assert seq[0] in (5, 8), opp
    assert all(b == max(a - 1, 1) for a, b in zip(seq, seq[1:], strict=False)), opp
    assert opp[8:] == [0, 0], opp


# L3b (doc/engine-diff.md): fixed 2026-10-16; a regression test now
def test_l3b_built_terrain_turns(belief):
    sd, _, built = field_turns(RILLABOOM, "terrain", 6, belief)
    assert sd == [5, 4, 3, 2, 1, 0, 0]
    assert built == sd


DRAGAPULT_SLUDGE = """Dragapult @ Black Sludge
Ability: Infiltrator
Tera Type: Ghost
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Shadow Ball
- Draco Meteor
- U-turn
- Will-O-Wisp"""


def test_control_hp_salt_cure_infestation_roost_earthquake():
    """HP compared too (within the rolls' spread around the engine's damage): L5's leads (HP
    after Recover / Roost turns) were the differential's tolerance, not the engine."""
    roost_eq = [("move bravebird", "move ruination"), ("move roost", "move earthquake")]
    cases = [(GARGANACL, TINGLU, [("move saltcure", "move spikes")], ("saltcure", "spikes")),
             (TOXAPEX, TINGLU, [("move infestation", "move spikes")], ("infestation", "spikes")),
             (CORVIKNIGHT, TINGLU, roost_eq, ("roost", "earthquake"))]  # fmt: skip
    for p1, p2, turns, last in cases:
        states = ec.run_showdown(p1, p2, turns, seed="gen5,3,3,3,3")
        outs = ec.engine_outcomes(ec.engine_state(states[-2]), *last)
        assert ec.closest(states[-1], outs, (1, 1), hp=True)["diff"] == {}, last


# L9 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l9_black_sludge_non_poison():
    states = ec.run_showdown(DRAGAPULT_SLUDGE, BLISSEY, [("move willowisp", "move protect")])
    assert states[1]["sides"][0]["mons"][0]["hp"] == 317 - 317 // 8  # Showdown: 1/8 at full HP
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "willowisp", "protect")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


ZAPDOS_STATIC = """Zapdos @ Heavy-Duty Boots
Ability: Static
Tera Type: Fairy
EVs: 248 HP / 8 SpA / 252 Def
Bold Nature
- Roost
- Hurricane
- Discharge
- U-turn"""
DRAGONITE_TAIL = """Dragonite @ Leftovers
Ability: Inner Focus
Tera Type: Normal
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Dragon Tail
- Extreme Speed
- Earthquake
- Roost"""
CORVIKNIGHT_HELMET = (
    CORVIKNIGHT.replace("@ Leftovers", "@ Rocky Helmet")
    + "\n\n"
    + """Great Tusk @ Booster Energy
Ability: Protosynthesis
Tera Type: Ground
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Headlong Rush
- Ice Spinner
- Rapid Spin
- Stealth Rock"""
)


def contact_case(p1, move: str, **kw):
    states = ec.run_showdown(p1, DRAGONITE_TAIL, [("move roost", f"move {move}")], **kw)
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "roost", move)
    n = (len(states[0]["sides"][0]["mons"]), 1)
    return states, ec.closest(states[1], outs, n, hp=True)


def test_control_static_and_rocky_helmet_on_a_contact_move():
    states, res = contact_case(ZAPDOS_STATIC, "extremespeed", force_random=True)
    assert states[1]["sides"][1]["mons"][0]["status"] == "par"  # Showdown: Static
    assert res["diff"] == {}
    states, res = contact_case(CORVIKNIGHT_HELMET, "extremespeed", seed="gen5,9,9,9,9")
    assert res["diff"] == {}


# L7 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l7_static_on_dragon_tail():
    states, res = contact_case(ZAPDOS_STATIC, "dragontail", force_random=True)
    assert states[1]["sides"][1]["mons"][0]["status"] == "par"  # Showdown: Static
    assert res["diff"] == {}


# L7 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l7_rocky_helmet_on_dragon_tail():
    states, res = contact_case(CORVIKNIGHT_HELMET, "dragontail", seed="gen5,9,9,9,9")
    assert states[1]["sides"][1]["mons"][0]["hp"] < 386  # Showdown: the helmet hit
    assert res["diff"] == {}


def test_control_faint_stops_at_the_forced_switch():
    """L6: the engine stops a turn at a faint (the forced switch is the next decision), as
    Showdown asks for the replacement: those turns are compared at different points by the
    differential (not an engine issue)."""
    weak = TINGLU.replace("EVs: 252 HP / 4 Atk / 252 SpD", "EVs: 0 HP / 0 Atk / 0 SpD")
    weak += "\n\n" + BLISSEY
    presser = GARGANACL.replace("- Salt Cure", "- Body Press")
    turns = [("move bodypress", "move spikes")] * 6
    states = ec.run_showdown(presser, weak, turns, seed="gen5,4,4,4,4")
    k = next(i for i, s in enumerate(states) if s["sides"][1]["request"] == "switch")
    assert states[k]["sides"][1]["mons"][0]["hp"] == 0
    outs = ec.engine_outcomes(ec.engine_state(states[k - 1]), "bodypress", "spikes")
    fainted = [o for o in outs if o[1].side_two.pokemon[0].hp == 0]
    assert fainted and all(int(o[1].side_two.active_index) == 0 for o in fainted)


# L11 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l11_spikes_two_layers():
    p1 = CORVIKNIGHT + "\n\n" + BLISSEY.replace("Heavy-Duty Boots", "Leftovers")
    turns = [("move roost", "move spikes")] * 2 + [("switch 2", "move spikes")]
    states = ec.run_showdown(p1, TINGLU, turns)
    assert states[2]["sides"][0]["conditions"]["spikes"]["layers"] == 2
    assert "|-damage|p1a: Blissey|595/714|[from] Spikes" in states[3]["log"]  # Showdown: 1/6
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "blissey", "spikes")
    assert ec.closest(states[3], outs, (2, 1), hp=True)["diff"] == {}


FERROTHORN = """Ferrothorn @ Rocky Helmet
Ability: Iron Barbs
Tera Type: Water
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Leech Seed
- Protect
- Gyro Ball
- Spikes"""


# L12 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
@pytest.mark.parametrize("p1, move", [(CORVIKNIGHT, "roost"), (FERROTHORN, "leechseed")])
def test_l12_heal_before_status_damage(p1, move):
    """At full HP, Leftovers / Leech Seed's heal (Showdown's residual orders 5 / 8) come before
    the burn (10): nothing to heal, then the burn's 1/16."""
    states = ec.run_showdown(p1, DRAGAPULT_SLUDGE, [(f"move {move}", "move willowisp")],
                             force_random=True)  # fmt: skip
    m = states[1]["sides"][0]["mons"][0]
    assert m["status"] == "brn" and m["hp"] == m["maxhp"] - m["maxhp"] // 16  # Showdown
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "willowisp")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L13 (doc/engine-diff.md): fixed 2026-10-16 (engine, state construction); a regression test now
def test_l13_partial_trap_ends(belief):
    turns = [("move infestation", "move spikes")] + [("move recover", "move spikes")] * 6
    states = ec.run_showdown(TOXAPEX, TINGLU, turns, seed="gen5,3,3,3,3")
    trapped = ["partiallytrapped" in s["sides"][1]["mons"][0]["volatiles"] for s in states]
    assert trapped == [False] + [True] * 4 + [False] * 3  # Showdown: 4 ends of turn (5 or 6)
    for k in range(1, len(states) - 1):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), "recover", "spikes")
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k
    # our state construction counts the trap's ends of turn as the harness does (the engine from
    # those counts ends it when Showdown does: the loop above), from either side's view
    # (2026-10-16: a cap of 3 kept it one turn too long, found by the differential on new games)
    for k in range(1, 5):
        sd = ec.engine_state(states[k]).side_two.volatile_status_durations.partiallytrapped
        own = ec.built_state(states, k, "p2", belief).side_one.volatile_status_durations
        opp = ec.built_state(states, k, "p1", belief).side_two.volatile_status_durations
        assert own.partiallytrapped == opp.partiallytrapped == sd == k, k


CORVIKNIGHT_PROTECT = CORVIKNIGHT.replace("- Roost", "- Protect")


# L14 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
@pytest.mark.parametrize("p1, move, p2, answer, force", [
    (BLISSEY, "seismictoss", CORVIKNIGHT_PROTECT, "protect", None),
    (BLISSEY, "seismictoss", KYUREM, "substitute", None),
    (TINGLU, "ruination", CORVIKNIGHT_PROTECT, "protect", None),
    (TINGLU, "ruination", KYUREM, "substitute", None),
    (TINGLU, "ruination", BLISSEY, "calmmind", False),  # Showdown: every chance fails, a miss
])  # fmt: skip
def test_l14_fixed_damage_checks(p1, move, p2, answer, force):
    """Seismic Toss / Night Shade and the halving moves (Ruination, Super Fang, Nature's
    Madness) miss, are blocked by Protect and hit a Substitute like any damaging move."""
    states = ec.run_showdown(p1, p2, [(f"move {move}", f"move {answer}")], force_random=force)
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, answer)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


SLOWKING_FUTURE = """Slowking-Galar @ Heavy-Duty Boots
Ability: Regenerator
Tera Type: Water
EVs: 248 HP / 8 Def / 252 SpA
Modest Nature
- Future Sight
- Sludge Bomb
- Chilly Reception
- Slack Off"""
CHANSEY = """Chansey @ Eviolite
Ability: Natural Cure
Tera Type: Fairy
EVs: 248 HP / 252 Def / 8 SpD
Bold Nature
- Seismic Toss
- Soft-Boiled
- Calm Mind
- Protect"""


def test_control_future_sight():
    turns = [("move futuresight", "move defog")] + [("move slackoff", "move defog")] * 2
    states = ec.run_showdown(SLOWKING_FUTURE, CORVIKNIGHT, turns, seed="gen5,5,5,5,5")
    assert "|-end|p2a: Corviknight|move: Future Sight" in states[3]["log"]  # Showdown: it hit
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "slackoff", "defog")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


# L15 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
@pytest.mark.parametrize("target, answer", [(CHANSEY, "softboiled"), (BLISSEY, "calmmind")])
def test_l15_future_sight_defender(target, answer):
    """Future Sight's damage is a special move's at the hit: the target's Special Defense boosts
    (Calm Mind) and Eviolite count."""
    turns = [("move futuresight", f"move {answer}")] + [("move slackoff", f"move {answer}")] * 2
    states = ec.run_showdown(SLOWKING_FUTURE, target, turns, seed="gen5,5,5,5,5")
    assert any(x.endswith("move: Future Sight") for x in states[3]["log"])  # Showdown: it hit
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "slackoff", answer)
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


WEEZING = """Weezing-Galar @ Leftovers
Ability: Neutralizing Gas
Tera Type: Steel
EVs: 252 HP / 252 Def / 4 SpD
Bold Nature
- Will-O-Wisp
- Protect
- Strange Steam
- Pain Split"""
GHOLDENGO_TRICK = """Gholdengo @ Choice Scarf
Ability: Good as Gold
Tera Type: Steel
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Trick
- Shadow Ball
- Make It Rain
- Focus Blast"""


# L16a (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l16a_pain_split_max_hp():
    states = ec.run_showdown(WEEZING, TINGLU, [("move painsplit", "move spikes")])
    assert states[1]["sides"][0]["mons"][0]["hp"] == 334  # Showdown: at most the max HP
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "painsplit", "spikes")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L16b (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
@pytest.mark.parametrize("p1, move, pre", [
    (WEEZING, "painsplit", [("move protect", "move bravebird")]),  # Weezing below its max HP
    (GHOLDENGO_TRICK, "trick", []),
])  # fmt: skip
def test_l16b_special_moves_blocked_by_protect(p1, move, pre):
    states = ec.run_showdown(p1, CORVIKNIGHT_PROTECT, pre + [(f"move {move}", "move protect")],
                             seed="gen5,6,6,6,6")  # fmt: skip
    assert "|-activate|p2a: Corviknight|move: Protect" in states[-1]["log"]  # Showdown: blocked
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), move, "protect")
    assert ec.closest(states[-1], outs, (1, 1), hp=True)["diff"] == {}


GLIMMORA_SASH = """Glimmora @ Focus Sash
Ability: Toxic Debris
Tera Type: Ghost
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Mortal Spin
- Power Gem
- Earth Power
- Spikes"""


# L17 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l17_focus_sash_used_up():
    states = ec.run_showdown(GLIMMORA_SASH, TINGLU, [("move spikes", "move earthquake")])
    m = states[1]["sides"][0]["mons"][0]
    assert m["hp"] == 1 and m["item"] == ""  # Showdown: survived on the sash, which is gone
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "spikes", "earthquake")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


ZAMAZENTA = """Zamazenta @ Leftovers
Ability: Dauntless Shield
Tera Type: Fire
EVs: 252 HP / 4 Atk / 252 Spe
Jolly Nature
- Body Press
- Iron Defense
- Crunch
- Roar"""


def zamazenta_back():
    p1 = ZAMAZENTA + "\n\n" + CORVIKNIGHT
    turns = [("switch 2", "move spikes"), ("switch 2", "move spikes")]
    return ec.run_showdown(p1, TINGLU, turns, fmt="gen9ou")


# L18 (doc/engine-diff.md): fixed 2026-10-16 (engine, state construction); a regression test now
def test_l18_dauntless_shield_once(belief):
    states = zamazenta_back()
    assert states[0]["sides"][0]["mons"][0]["boosts"]["def"] == 1  # Showdown: the first time
    assert states[2]["sides"][0]["mons"][0]["boosts"]["def"] == 0  # ... and not again
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "zamazenta", "spikes")
    assert ec.closest(states[2], outs, (2, 1), hp=True)["diff"] == {}
    # our state construction marks it used, from either side's view
    own = ec.built_state(states, 1, "p1", belief).side_one.pokemon[0]
    opp = ec.built_state(states, 1, "p2", belief).side_two
    opp = next(p for p in opp.pokemon if str(p.id).lower() == "zamazenta")
    assert str(own.base_ability).lower() == str(opp.base_ability).lower() == "none"
    assert str(own.ability).lower() == str(opp.ability).lower() == "dauntlessshield"


HATTERENE = """Hatterene @ Life Orb
Ability: Magic Bounce
Tera Type: Fairy
EVs: 252 SpA / 4 SpD / 252 Spe
Modest Nature
- Psychic Noise
- Draining Kiss
- Calm Mind
- Mystical Fire"""


# L1b (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l1b_defog_magic_bounce():
    states, outs = first_turn("move calmmind", "move defog", "calmmind", "defog", p1=HATTERENE,
                              p2=CORVIKNIGHT)  # fmt: skip
    assert states[1]["sides"][1]["mons"][0]["boosts"]["evasion"] == -1  # Showdown: bounced
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L19 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
@pytest.mark.parametrize("p2, move", [
    (CORVIKNIGHT, "bravebird"),  # Leftovers
    (TOXAPEX, "haze"),  # Black Sludge (drain moves: Showdown's Heal Block disables them)
])  # fmt: skip
def test_l19_heal_block_stops_all_healing(p2, move):
    """Psychic Noise's Heal Block (2 turns): no healing at all for the target, Leftovers and
    Black Sludge included (Showdown's onTryHeal)."""
    first = "defog" if p2 is CORVIKNIGHT else "haze"
    turns = [("move psychicnoise", f"move {first}"), ("move calmmind", f"move {move}")]
    states = ec.run_showdown(HATTERENE, p2, turns, seed="gen5,2,2,2,2")
    assert "healblock" in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "calmmind", move)
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


GLISCOR = """Gliscor @ Toxic Orb
Ability: Poison Heal
Tera Type: Water
EVs: 244 HP / 12 Def / 252 SpD
Careful Nature
- Protect
- Earthquake
- Knock Off
- Spikes"""


# L12b (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l12b_poison_heal_after_the_orb():
    """Toxic Orb poisons at the very end of the turn (Showdown's residual order 28), after
    Poison Heal's turn (9): no heal in that turn."""
    states = ec.run_showdown(GLISCOR, TINGLU, [("move spikes", "move ruination")])
    m = states[1]["sides"][0]["mons"][0]
    assert m["status"] == "tox" and m["hp"] == m["maxhp"] - m["maxhp"] // 2  # Showdown
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "spikes", "ruination")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


ARMAROUGE = """Armarouge @ Heavy-Duty Boots
Ability: Weak Armor
Tera Type: Fairy
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Armor Cannon
- Psyshock
- Energy Ball
- Calm Mind"""
HYDRAPPLE = """Hydrapple @ Leftovers
Ability: Regenerator
Tera Type: Steel
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Fickle Beam
- Giga Drain
- Earth Power
- Nasty Plot"""


# L8a (doc/engine-diff.md): fixed in rust/patches (2026-10-16; move table diff); a regression test now
def test_l8a_armor_cannon_self_drops():
    states, outs = first_turn("move armorcannon", "move spikes", "armorcannon", "spikes",
                              p1=ARMAROUGE)  # fmt: skip
    b = states[1]["sides"][0]["mons"][0]["boosts"]
    assert (b["def"], b["spd"]) == (-1, -1)  # Showdown
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L8b (doc/engine-diff.md): fixed in rust/patches (2026-10-16; move table diff); a regression test now
def test_l8b_fickle_beam_no_boost():
    states, outs = first_turn("move ficklebeam", "move spikes", "ficklebeam", "spikes",
                              p1=HYDRAPPLE, force_random=True)  # fmt: skip
    assert "|-activate|p1a: Hydrapple|move: Fickle Beam" in states[1]["log"]  # Showdown: doubled
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spa"] == 0  # ... and no boost
    assert {o[1].side_one.special_attack_boost for o in outs} == {0}


BAXCALIBUR = """Baxcalibur @ Loaded Dice
Ability: Thermal Exchange
Tera Type: Dragon
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Glaive Rush
- Icicle Spear
- Earthquake
- Swords Dance"""


# L8c (doc/engine-diff.md): fixed in rust/patches (2026-10-16; move table diff); a regression test now
def test_l8c_glaive_rush_drawback():
    """Glaive Rush: the user takes double damage until it moves again."""
    turns = [("move glaiverush", "move bravebird"), ("move swordsdance", "move roost")]
    states = ec.run_showdown(BAXCALIBUR, CORVIKNIGHT, turns, seed="gen5,8,8,8,8")
    assert "glaiverush" in states[1]["sides"][0]["mons"][0]["volatiles"]  # Showdown
    assert states[2]["sides"][0]["mons"][0]["volatiles"] == {}  # gone when it moves again
    for k, (c1, c2) in enumerate((("glaiverush", "bravebird"), ("swordsdance", "roost"))):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, c2)
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k


# --- found by the full-information random-battle differential (scripts/check_engine_random.py)

GHOLDENGO = """Gholdengo @ Leftovers
Ability: Good as Gold
Tera Type: Steel
EVs: 252 HP / 252 SpA / 4 Spe
Modest Nature
- Make It Rain
- Shadow Ball
- Recover
- Nasty Plot"""
ARAQUANID = """Araquanid @ Leftovers
Ability: Water Bubble
Tera Type: Water
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Lunge
- Liquidation
- Sticky Web
- Mirror Coat"""
HAXORUS = """Haxorus @ Lum Berry
Ability: Mold Breaker
Tera Type: Dragon
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Outrage
- Earthquake
- Dragon Dance
- Close Combat"""
NINETALES = """Ninetales-Alola @ Light Clay
Ability: Snow Warning
Tera Type: Ghost
EVs: 252 HP / 4 SpA / 252 Spe
Timid Nature
- Aurora Veil
- Moonblast
- Freeze-Dry
- Encore"""


# L20 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l20_good_as_gold_blocks_trick():
    states, outs = first_turn("move trick", "move nastyplot", "trick", "nastyplot",
                              p1=GHOLDENGO_TRICK, p2=GHOLDENGO)  # fmt: skip
    assert "|-immune|p2a: Gholdengo|[from] ability: Good as Gold" in states[1]["log"]
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L21 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l21_mirror_armor_reflects():
    p1 = CORVIKNIGHT.replace("Ability: Pressure", "Ability: Mirror Armor")
    states, outs = first_turn("move roost", "move lunge", "roost", "lunge", p1=p1, p2=ARAQUANID,
                              seed="gen5,3,3,3,3")  # fmt: skip
    assert states[1]["sides"][1]["mons"][0]["boosts"]["atk"] == -1  # Showdown: reflected
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L22 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l22_outrage_lock_ends_on_immune_target():
    turns = [("move outrage", "move softboiled"), ("move outrage", "switch 2")]
    states = ec.run_showdown(HAXORUS, BLISSEY + "\n\n" + NINETALES, turns, seed="gen5,3,3,3,3")
    assert "|-immune|p2a: Ninetales" in states[2]["log"]
    assert "lockedmove" not in states[2]["sides"][0]["mons"][0]["volatiles"]  # Showdown
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "outrage", "ninetalesalola")
    assert ec.closest(states[2], outs, (1, 2), hp=True)["diff"] == {}


INCINEROAR = """Incineroar @ Heavy-Duty Boots
Ability: Intimidate
Tera Type: Fairy
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Knock Off
- Flare Blitz
- Parting Shot
- Will-O-Wisp"""


# L21 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l21_mirror_armor_reflects_intimidate():
    p1 = CORVIKNIGHT.replace("Ability: Pressure", "Ability: Mirror Armor")
    states = ec.run_showdown(p1, TINGLU + "\n\n" + INCINEROAR, [("move roost", "switch 2")])
    assert states[1]["sides"][1]["mons"][1]["boosts"]["atk"] == -1  # Showdown: reflected
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "roost", "incineroar")
    assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}


# L23 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l23_moves_usable_after_a_lock_ends():
    p1 = HAXORUS.replace("Lum Berry", "Leftovers")
    states = ec.run_showdown(p1, BLISSEY, [("move outrage", "move softboiled")] * 2,
                             seed="gen5,3,3,3,3")  # fmt: skip
    assert "confusion" in states[2]["sides"][0]["mons"][0]["volatiles"]  # Showdown: lock over
    usable = [not m.get("disabled") for m in states[2]["sides"][0]["request_json"]["active"][0]["moves"]]
    assert usable == [True] * 4  # Showdown: every move again
    for _, s in ec.engine_outcomes(ec.engine_state(states[1]), "outrage", "softboiled"):
        assert [not m.disabled for m in s.side_one.pokemon[0].moves] == usable


def test_control_trick_room_against_good_as_gold():
    """Good as Gold blocks status moves aimed at its holder, not field moves (the L20 fix first
    blocked Trick Room too: the engine's field moves target "Opponent"; found by the random
    differential's regression check)."""
    hatterene = HATTERENE.replace("- Calm Mind", "- Trick Room")
    states, outs = first_turn("move trickroom", "move nastyplot", "trickroom", "nastyplot",
                              p1=hatterene, p2=GHOLDENGO)  # fmt: skip
    assert states[1]["field"]["pseudo"].get("trickroom")  # Showdown: set
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L24 (doc/engine-diff.md): items the engine did not know, added from Showdown's source; fixed
# ones are regression tests

def _setter(species, ability, item, moves="- Protect\n- Roost\n- Knock Off\n- U-turn"):
    return f"""{species} @ {item}
Ability: {ability}
Tera Type: Normal
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
{moves}"""


DURATION_SETTERS = [  # (setter, the field's key, the engine's turns attribute)
    (_setter("Pelipper", "Drizzle", "Damp Rock"), "weather", "weather_turns_remaining"),
    (_setter("Torkoal", "Drought", "Heat Rock"), "weather", "weather_turns_remaining"),
    (_setter("Ninetales-Alola", "Snow Warning", "Icy Rock"), "weather", "weather_turns_remaining"),
    (_setter("Tyranitar", "Sand Stream", "Smooth Rock"), "weather", "weather_turns_remaining"),
    (_setter("Rillaboom", "Grassy Surge", "Terrain Extender"), "terrain", "terrain_turns_remaining"),
]


@pytest.mark.parametrize("setter, kind, attr", DURATION_SETTERS)
def test_l24_duration_items_set_on_switch_in(setter, kind, attr):
    """A weather / terrain set by an ability in the search (the setter switches in) lasts 8
    turns with its item (Showdown's durationCallback), not 5."""
    states = ec.run_showdown(BLISSEY + "\n\n" + setter, TINGLU, [("switch 2", "move spikes")])
    assert states[1]["field"][f"{kind}_duration"] == 7  # Showdown: 8, one end of turn
    species = setter.split(" @")[0].lower().replace("-", "")
    outs = ec.engine_outcomes(ec.engine_state(states[0]), species, "spikes")
    assert {getattr(o[1], attr) for o in outs} == {7}


@pytest.mark.parametrize("screen, cond", [("reflect", "reflect"), ("lightscreen", "light_screen")])
def test_l24_light_clay(screen, cond):
    # (not Prankster: against a Dark type the engine fails it, L26)
    p1 = _setter("Grimmsnarl", "Pressure", "Light Clay",
                 "- Reflect\n- Light Screen\n- Spirit Break\n- Parting Shot")  # fmt: skip
    states = ec.run_showdown(p1, TINGLU, [(f"move {screen}", "move spikes")])
    assert states[1]["sides"][0]["conditions"][screen]["duration"] == 7  # Showdown: 8 turns
    outs = ec.engine_outcomes(ec.engine_state(states[0]), screen, "spikes")
    assert {getattr(o[1].side_one.side_conditions, cond) for o in outs} == {7}


# L26 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
def test_l26_prankster_self_move_against_dark():
    """Prankster's status moves fail against a Dark-type target, not the user's own (Reflect):
    Ting-Lu is Dark."""
    p1 = _setter("Grimmsnarl", "Prankster", "Leftovers",
                 "- Reflect\n- Light Screen\n- Spirit Break\n- Parting Shot")  # fmt: skip
    states, outs = first_turn("move reflect", "move spikes", "reflect", "spikes", p1=p1)
    assert states[1]["sides"][0]["conditions"]["reflect"]["duration"] == 4  # Showdown: set
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_control_prankster_move_at_a_dark_type_fails():
    """(L26's other side) a Prankster status move aimed at the Dark-type target still fails."""
    p1 = _setter("Grimmsnarl", "Prankster", "Leftovers",
                 "- Reflect\n- Thunder Wave\n- Spirit Break\n- Parting Shot")  # fmt: skip
    states, outs = first_turn("move thunderwave", "move spikes", "thunderwave", "spikes", p1=p1)
    assert states[1]["sides"][1]["mons"][0]["status"] == ""  # Showdown: it failed
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L27 (doc/engine-diff.md): fixed in rust/patches (2026-10-16; exposed by the L26 fix: the random
# differential's baseline check showed a new mismatch, b117-t11 Brick Break | Light Screen)
@pytest.mark.parametrize("move", ["brickbreak", "psychicfangs", "ragingbull"])
def test_l27_screen_breakers(move):
    """Brick Break, Psychic Fangs and Raging Bull remove the target side's screens before they
    hit (Showdown's onTryHit: the damage is not halved)."""
    p1 = _setter("Tauros-Paldea-Combat", "Intimidate", "Leftovers",
                 "- Brick Break\n- Psychic Fangs\n- Raging Bull\n- Bulk Up")  # fmt: skip
    # (not a Dark type: Psychic Fangs could not hit it)
    p2 = _setter("Meowstic", "Prankster", "Leftovers",
                 "- Reflect\n- Light Screen\n- Psychic Noise\n- Thunder Wave")  # fmt: skip
    states = ec.run_showdown(p1, p2, [(f"move {move}", "move reflect")], seed="gen5,5,5,5,5")
    assert "reflect" not in states[1]["sides"][1]["conditions"]  # Showdown: broken
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "reflect")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


TINGLU_HITS = _setter("Ting-Lu", "Vessel of Ruin", "Leftovers",
                      "- Throat Chop\n- Ruination\n- Spikes\n- Whirlwind")  # fmt: skip


def _corviknight(item, nature="Careful"):
    # 400 HP: two Ruinations take it to exactly 1/4 (400 -> 200 -> 100)
    return CORVIKNIGHT.replace("@ Leftovers", f"@ {item}").replace("Careful Nature", f"{nature} Nature")


def _item_turn(p1, p2, turns, choices, n=(1, 1), seed="gen5,5,5,5,5"):
    """Showdown's last turn and the engine's outcomes of it from the turn before."""
    states = ec.run_showdown(p1, p2, turns, seed=seed)
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), *choices)
    return states, ec.closest(states[-1], outs, n, hp=True)


@pytest.mark.parametrize("berry, confused", [("Figy Berry", False), ("Wiki Berry", True),
                                             ("Aguav Berry", False), ("Mago Berry", False),
                                             ("Iapapa Berry", False)])  # fmt: skip
def test_l24_pinch_berries(berry, confused):
    """At 1/4 HP: heals 1/3; confused when the nature lowers the berry's stat (Careful: Sp. Atk,
    Wiki Berry's)."""
    turns = [("move defog", "move ruination")] * 2
    states, res = _item_turn(_corviknight(berry), TINGLU_HITS, turns, ("defog", "ruination"))
    m = states[2]["sides"][0]["mons"][0]
    assert m["item"] == "" and m["hp"] == 100 + 400 // 3  # Showdown: eaten at 100 / 400
    assert ("confusion" in m["volatiles"]) == confused
    assert res["diff"] == {}


def test_l24_oran_berry():
    states, res = _item_turn(_corviknight("Oran Berry"), TINGLU_HITS,
                             [("move defog", "move ruination")], ("defog", "ruination"))  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["hp"] == 210  # Showdown: 200 + 10
    assert res["diff"] == {}


KYUREM_ICE = KYUREM.replace("- Earth Power", "- Ice Beam")
ROTOM_WASH = _setter("Rotom-Wash", "Levitate", "Leftovers",
                     "- Thunderbolt\n- Hydro Pump\n- Volt Switch\n- Will-O-Wisp")  # fmt: skip
PELIPPER_SURF = _setter("Pelipper", "Keen Eye", "Leftovers", "- Surf\n- Roost\n- Hurricane\n- U-turn")


@pytest.mark.parametrize("item, p2, move, check", [
    ("Kee Berry", TINGLU_HITS, "throatchop", ("boosts", "def", 1)),
    ("Maranga Berry", TINGLU_HITS, "ruination", ("boosts", "spd", 1)),
    ("Snowball", KYUREM_ICE, "icebeam", ("boosts", "atk", 1)),
    ("Luminous Moss", PELIPPER_SURF, "surf", ("boosts", "spd", 1)),
    ("Jaboca Berry", TINGLU_HITS, "throatchop", ("foe_lost", 1 / 8)),
    ("Rowap Berry", TINGLU_HITS, "ruination", ("foe_lost", 1 / 8)),
    ("Enigma Berry", ROTOM_WASH, "thunderbolt", ("healed", 1 / 4)),
])  # fmt: skip
def test_l24_items_on_being_hit(item, p2, move, check):
    """Items used up by the hit that triggers them: a stat boost (Kee / Maranga Berry: physical /
    special, Snowball: Ice, Luminous Moss: Water), the attacker's 1/8 (Jaboca / Rowap Berry),
    a quarter healed after a super-effective hit (Enigma Berry: Electric on Corviknight)."""
    holder = _corviknight(item)
    states, res = _item_turn(holder, p2, [("move defog", f"move {move}")], ("defog", move),
                             seed="gen5,6,6,6,6")  # fmt: skip
    m = states[1]["sides"][0]["mons"][0]
    assert m["item"] == ""  # Showdown: used up
    if check[0] == "boosts":
        assert m["boosts"][check[1]] == check[2]
    assert res["diff"] == {}


STICKYBARB_FOE = _setter("Ferrothorn", "Iron Barbs", "Sticky Barb",
                         "- Leech Seed\n- Protect\n- Gyro Ball\n- Spikes")  # fmt: skip


def test_l24_sticky_barb():
    """Its holder loses 1/8 at the end of every turn; a contact move moves it to an attacker
    without an item."""
    states, res = _item_turn(STICKYBARB_FOE, TINGLU_HITS, [("move protect", "move spikes")],
                             ("protect", "spikes"))  # fmt: skip
    m = states[1]["sides"][0]["mons"][0]
    assert m["hp"] == m["maxhp"] - m["maxhp"] // 8  # Showdown
    assert res["diff"] == {}
    nothing = TINGLU_HITS.replace("@ Leftovers", "")
    states, res = _item_turn(STICKYBARB_FOE, nothing, [("move spikes", "move throatchop")],
                             ("spikes", "throatchop"))  # fmt: skip
    assert states[1]["sides"][1]["mons"][0]["item"] == "stickybarb"  # Showdown: moved
    assert res["diff"] == {}


def test_l24_room_service():
    """Trick Room starts: the holder's Speed -1, the item used up."""
    hatterene = HATTERENE.replace("@ Life Orb", "@ Room Service").replace("- Calm Mind", "- Trick Room")
    states, res = _item_turn(hatterene, TINGLU_HITS, [("move trickroom", "move spikes")],
                             ("trickroom", "spikes"))  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spe"] == -1  # Showdown
    assert res["diff"] == {}


def test_l24_kee_berry_knocked_off_first():
    """Knock Off takes a Kee / Maranga Berry before it triggers (Showdown: the move's onAfterHit
    before the berry's onAfterMoveSecondary); found by the random differential's baseline check
    (b191-t5) after the first version boosted anyway."""
    rilla = RILLABOOM.replace("- U-turn", "- Knock Off")
    states, res = _item_turn(_corviknight("Kee Berry"), rilla, [("move defog", "move knockoff")],
                             ("defog", "knockoff"))  # fmt: skip
    m = states[1]["sides"][0]["mons"][0]
    assert m["item"] == "" and m["boosts"]["def"] == 0  # Showdown: knocked off, no boost
    assert res["diff"] == {}


CRIT_CHANCE = {1: 1 / 24, 2: 1 / 8, 3: 1 / 2, 4: 1.0}


def _engine_crit_chance(outs) -> float:
    """The chance of the outcomes where side two took the most damage (the crit branch; the
    move always hits and cannot knock the target out)."""
    top = max(o.damage[1] for o in outs)
    if len({o.damage[1] for o in outs}) == 1:
        return 1.0 if top else 0.0
    return sum(o[0] for o in outs if o.damage[1] == top)


def _kingambit(ability, item):
    return _setter("Kingambit", ability, item, "- Kowtow Cleave\n- Night Slash\n- Focus Energy\n- Iron Head")


@pytest.mark.parametrize("ability, item, move, focus", [
    ("Supreme Overlord", "Leftovers", "kowtowcleave", False),  # control: 1/24
    ("Supreme Overlord", "Leftovers", "nightslash", False),  # control: a high-crit move, 1/8
    ("Supreme Overlord", "Scope Lens", "kowtowcleave", False),
    ("Supreme Overlord", "Razor Claw", "nightslash", False),
    ("Super Luck", "Leftovers", "kowtowcleave", False),
    ("Supreme Overlord", "Leftovers", "kowtowcleave", True),
])  # fmt: skip
def test_crit_chance(ability, item, move, focus):
    """The engine's crit chance is Showdown's crit stage's (move, Scope Lens / Razor Claw, Super
    Luck, Focus Energy -- L24 / L28)."""
    p1 = _kingambit(ability, item)
    pre = [("move focusenergy", "move spikes")] if focus else []
    stage = ec.crit_stages(p1, TINGLU, pre)[move]
    states = ec.run_showdown(p1, TINGLU, pre + [(f"move {move}", "move spikes")])
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), move, "spikes")
    assert _engine_crit_chance(outs) == pytest.approx(CRIT_CHANCE[stage], abs=1e-4), stage


@pytest.mark.parametrize("berry, check", [("Ganlon Berry", ("boosts", "def", 1)),
                                          ("Apicot Berry", ("boosts", "spd", 1)),
                                          ("Lansat Berry", ("volatile", "focusenergy")),
                                          ("Salac Berry", ("boosts", "spe", 1))])  # fmt: skip
def test_l24_pinch_boost_berries(berry, check):
    """At 1/4 HP: Defense / Sp. Def / Speed +1 (Ganlon / Apicot / Salac), Focus Energy (Lansat);
    eaten when the hit takes it there (Showdown's onUpdate), not at the holder's next move only
    (the engine's Salac Berry before: item_before_move)."""
    turns = [("move defog", "move ruination")] * 2
    states, res = _item_turn(_corviknight(berry), TINGLU_HITS, turns, ("defog", "ruination"))
    m = states[2]["sides"][0]["mons"][0]
    assert m["item"] == ""  # Showdown: eaten at 100 / 400
    if check[0] == "boosts":
        assert m["boosts"][check[1]] == check[2]
    else:
        assert check[1] in m["volatiles"]
    assert res["diff"] == {}


def _engine_hit_chance(outs) -> float:
    return sum(o[0] for o in outs if o.damage[1] > 0)


DRAGAPULT_FAST = _setter("Dragapult", "Infiltrator", "Leftovers",
                         "- Dragon Darts\n- Shadow Ball\n- U-turn\n- Will-O-Wisp")  # fmt: skip


@pytest.mark.parametrize("attacker_item, target_item, move", [
    ("Leftovers", "Bright Powder", "nightslash"),  # 100 x 0.9
    ("Zoom Lens", "Leftovers", "stoneedge"),  # 80 x 1.2 (it moves after the faster target)
])  # fmt: skip
def test_l24_accuracy_items(attacker_item, target_item, move):
    p1 = _setter("Kingambit", "Supreme Overlord", attacker_item,
                 "- Kowtow Cleave\n- Night Slash\n- Stone Edge\n- Iron Head")  # fmt: skip
    p2 = DRAGAPULT_FAST.replace("@ Leftovers", f"@ {target_item}")
    acc = ec.accuracies(p1, p2)[move]
    states = ec.run_showdown(p1, p2, [(f"move {move}", "move willowisp")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "willowisp")
    assert _engine_hit_chance(outs) == pytest.approx(min(acc / 100, 1.0), abs=2e-3), acc


def _first_mover_showdown(states) -> str:
    return next(x.split("|")[2][:2] for x in states[1]["log"] if x.startswith("|move|"))


def _first_mover_engine(state, c1, c2) -> str:
    si = max(pe.generate_instructions(state, c1, c2), key=lambda x: x.percentage)
    first = next(str(i) for i in si.instruction_list if str(i).startswith("Acted"))
    return "p1" if "SideOne" in first else "p2"


@pytest.mark.parametrize("item", ["Power Anklet", "Power Band", "Power Belt", "Power Bracer",
                                  "Power Lens", "Power Weight"])  # fmt: skip
def test_l24_power_items_halve_speed(item):
    """Kingambit outspeeds Ting-Lu, but not at half its Speed."""
    p1 = _setter("Kingambit", "Supreme Overlord", item,
                 "- Kowtow Cleave\n- Night Slash\n- Stone Edge\n- Iron Head")  # fmt: skip
    states = ec.run_showdown(p1, TINGLU, [("move kowtowcleave", "move spikes")])
    assert _first_mover_showdown(states) == "p2"  # Showdown: Ting-Lu first
    assert _first_mover_engine(ec.engine_state(states[0]), "kowtowcleave", "spikes") == "p2"


def test_l24_float_stone():
    """Low Kick against a Float Stone holder: half its weight (Corviknight 75 kg -> 37.5: 60
    power, not 80)."""
    p1 = _setter("Kingambit", "Supreme Overlord", "Leftovers",
                 "- Low Kick\n- Night Slash\n- Stone Edge\n- Iron Head")  # fmt: skip
    states, res = _item_turn(p1, _corviknight("Float Stone"), [("move lowkick", "move defog")],
                             ("lowkick", "defog"))  # fmt: skip
    assert res["diff"] == {}


def test_l24_big_root():
    """Leech Seed's heal x 1.3 for a Big Root holder (exact: no roll in it, within the HP
    tolerance of Ruination's damage otherwise)."""
    p1 = FERROTHORN.replace("@ Rocky Helmet", "@ Big Root")
    states, res = _item_turn(p1, TINGLU_HITS, [("move leechseed", "move ruination")],
                             ("leechseed", "ruination"))  # fmt: skip
    assert res["diff"] == {}
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "leechseed", "ruination")
    hp = states[1]["sides"][0]["mons"][0]["hp"]
    assert {o[1].side_one.pokemon[0].hp for o in outs if o[0] > 0.5} == {hp}


@pytest.mark.parametrize("item", ["King's Rock", "Razor Fang"])
def test_l24_flinch_items(item):
    """A damaging move without a flinch chance gets 10% (Showdown's rate counted over 1,000 seeds:
    a secondary's roll is not a randomChance, force_random cannot show it)."""
    p1 = _kingambit("Supreme Overlord", item)
    turns = [("move kowtowcleave", "move spikes")]
    rate = ec.showdown_rate(p1, TINGLU, turns, "|cant|p2a: Ting-Lu|flinch", 1000)
    states = ec.run_showdown(p1, TINGLU, turns)
    e = ec.engine_state(states[0])
    flinch = sum(si.percentage for si in pe.generate_instructions(e, "kowtowcleave", "spikes")
                 if any("FLINCH" in str(i) for i in si.instruction_list)) / 100  # fmt: skip
    assert flinch == pytest.approx(rate, abs=0.03), rate


def test_l24_utility_umbrella():
    """Rain does not boost a Water move against an Umbrella holder."""
    p1 = _setter("Pelipper", "Drizzle", "Damp Rock", "- Surf\n- Roost\n- Hurricane\n- U-turn")
    states, res = _item_turn(p1, _corviknight("Utility Umbrella"), [("move surf", "move defog")],
                             ("surf", "defog"))  # fmt: skip
    assert res["diff"] == {}


def _engine_first_chance(state, c1, c2) -> float:
    """The engine's chance that side one moves first (its first Acted marker)."""
    total = 0.0
    for si in pe.generate_instructions(state, c1, c2):
        first = next((str(i) for i in si.instruction_list if str(i).startswith("Acted")), "")
        if "SideOne" in first:
            total += si.percentage / 100
    return total


def test_l24_quick_claw():
    """A 1/5 chance to move first in its priority bracket (Showdown's rate counted over 1,000
    seeds): the slower Ferrothorn against Ting-Lu."""
    p1 = FERROTHORN.replace("@ Rocky Helmet", "@ Quick Claw")
    turns = [("move gyroball", "move spikes")]
    rate = ec.showdown_rate(p1, TINGLU, turns, "|-activate|p1a: Ferrothorn|item: Quick Claw", 1000)
    states = ec.run_showdown(p1, TINGLU, turns)
    assert _engine_first_chance(ec.engine_state(states[0]), "gyroball", "spikes") == pytest.approx(rate, abs=0.03)


PIKACHU_BAND = """Pikachu @ Focus Band
Ability: Static
Level: 1
- Thunder Shock
- Quick Attack
- Growl
- Tail Whip"""


def test_l24_focus_band():
    """A 1/10 chance to survive a knockout hit at 1 HP (Showdown's rate over 1,000 seeds):
    a level-1 Pikachu takes Blissey's Seismic Toss."""
    turns = [("move growl", "move seismictoss")]
    rate = ec.showdown_rate(PIKACHU_BAND, BLISSEY_TOSS_SET, turns, "item: Focus Band", 1000)
    states = ec.run_showdown(PIKACHU_BAND, BLISSEY_TOSS_SET, turns)
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "growl", "seismictoss")
    survived = sum(o[0] for o in outs if o[1].side_one.pokemon[0].hp == 1)
    assert survived == pytest.approx(rate, abs=0.03), rate


BLISSEY_TOSS_SET = BLISSEY


def test_l24_starf_berry():
    """At 1/4 HP: a random stat of the five +2 (Showdown's sample), one outcome per stat with a
    fifth of the chance each; Showdown's own pick is one of them."""
    turns = [("move defog", "move ruination")] * 2
    states = ec.run_showdown(_corviknight("Starf Berry"), TINGLU_HITS, turns, seed="gen5,5,5,5,5")
    m = states[2]["sides"][0]["mons"][0]
    assert m["item"] == "" and sorted(m["boosts"].values())[-1] == 2  # Showdown: eaten, +2
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "defog", "ruination")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}
    boosted = {}
    for p, s in outs:
        b = {k: getattr(s.side_one, a) for k, a in (("atk", "attack_boost"), ("def", "defense_boost"),
             ("spa", "special_attack_boost"), ("spd", "special_defense_boost"), ("spe", "speed_boost"))}  # fmt: skip
        for k, v in b.items():
            if v == 2:
                boosted[k] = boosted.get(k, 0) + p
    hit = sum(boosted.values())
    assert set(boosted) == {"atk", "def", "spa", "spd", "spe"}
    assert all(v == pytest.approx(hit / 5, abs=1e-4) for v in boosted.values())


# L29 (doc/engine-diff.md): fixed in rust/patches (2026-10-16; exposed by Quick Claw: the random
# differential's baseline check showed b48-t19, Rocky Helmet twice)
def test_l29_speed_tie_branches_do_not_share_choices():
    """Two Corviknight of equal Speed: whichever moves first, Brave Bird into Rocky Helmet hurts
    the user once (the engine computed the second order with the move the first one had
    already given the helmet's damage to)."""
    p2 = CORVIKNIGHT.replace("@ Leftovers", "@ Rocky Helmet")
    orders = set()
    for seed in ("gen5,40503,9973,31337,7919", "gen5,55973,29919,28475,23757"):  # p1, p2 first
        states = ec.run_showdown(CORVIKNIGHT, p2, [("move bravebird", "move roost")], seed=seed)
        orders.add(_first_mover_showdown(states))
        outs = ec.engine_outcomes(ec.engine_state(states[0]), "bravebird", "roost")
        assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}, seed
    assert orders == {"p1", "p2"}  # Showdown: both tie orders among the seeds


def test_l24_leppa_berry():
    """A move at 0 PP gets 10 back, at most its max (Recover: 5 PP, 8 with Showdown's PP Ups;
    used 8 times: back to 8)."""
    p1 = CORVIKNIGHT.replace("@ Leftovers", "@ Leppa Berry").replace("- Roost", "- Recover")
    states = ec.run_showdown(p1, BLISSEY, [("move recover", "move calmmind")] * 8)
    pp = {x["id"]: x["pp"] for x in states[8]["sides"][0]["mons"][0]["moves"]}
    assert pp["recover"] == 8 and states[8]["sides"][0]["mons"][0]["item"] == ""  # Showdown
    outs = ec.engine_outcomes(ec.engine_state(states[7]), "recover", "calmmind")
    assert {[m.pp for m in o[1].side_one.pokemon[0].moves if str(m.id).lower() == "recover"][0]
            for o in outs} == {8}  # fmt: skip
    assert ec.closest(states[8], outs, (1, 1), hp=True)["diff"] == {}


def test_l24_micle_berry():
    """Eaten at 1/4 HP at the end of the turn: the next move's accuracy x 4915 / 4096."""
    # (L191: Iron Defense, not Defog: Defog's evasion drop is an accuracy stage now)
    p1 = _corviknight("Micle Berry").replace("- Brave Bird", "- Stone Edge").replace("- Defog", "- Iron Defense")
    turns = [("move irondefense", "move ruination")] * 2
    states = ec.run_showdown(p1, TINGLU_HITS, turns, seed="gen5,5,5,5,5")
    assert "micleberry" in states[2]["sides"][0]["mons"][0]["volatiles"]  # Showdown
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "irondefense", "ruination")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}
    acc = ec.accuracies(p1, TINGLU_HITS, turns, seed="gen5,5,5,5,5")["stoneedge"]
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "stoneedge", "spikes")
    assert _engine_hit_chance(outs) == pytest.approx(min(acc / 100, 1.0), abs=2e-3), acc


def test_l24_metronome_item():
    """The same move again: x 4915 / 4096, 5734 / 4096, ... up to 2 (the third Iron Head)."""
    p1 = _kingambit("Supreme Overlord", "Metronome")
    turns = [("move ironhead", "move softboiled")] * 3
    states = ec.run_showdown(p1, BLISSEY, turns, seed="gen5,5,5,5,5")
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "ironhead", "softboiled")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


def test_l24_mirror_herb():
    """The foe's stat raises copied once (Swords Dance: Attack +2), the herb used up."""
    p2 = _kingambit("Supreme Overlord", "Leftovers").replace("- Focus Energy", "- Swords Dance")
    states, res = _item_turn(_corviknight("Mirror Herb"), p2, [("move defog", "move swordsdance")],
                             ("defog", "swordsdance"))  # fmt: skip
    m = states[1]["sides"][0]["mons"][0]
    assert m["boosts"]["atk"] == 2 and m["item"] == ""  # Showdown
    assert res["diff"] == {}


EXCADRILL_MB = _setter("Excadrill", "Mold Breaker", "Leftovers",
                       "- Earthquake\n- Iron Head\n- Rapid Spin\n- Swords Dance")  # fmt: skip


def test_l24_ability_shield_against_mold_breaker():
    """Mold Breaker does not ignore the holder's Levitate."""
    rotom = ROTOM_WASH.replace("@ Leftovers", "@ Ability Shield")
    states, res = _item_turn(EXCADRILL_MB, rotom, [("move earthquake", "move willowisp")],
                             ("earthquake", "willowisp"))  # fmt: skip
    assert "|-immune|p2a: Rotom|[from] ability: Levitate" in states[1]["log"]  # Showdown
    assert res["diff"] == {}


def test_l24_destiny_knot():
    """The holder infatuated: its foe too."""
    p1 = "Corviknight (M) @ Destiny Knot\n" + "\n".join(CORVIKNIGHT.split("\n")[1:])
    p2 = _setter("Gardevoir (F)", "Trace", "Leftovers", "- Attract\n- Moonblast\n- Psychic\n- Calm Mind")
    # (Roost at full HP: nothing either way, whether the infatuation stops it or not)
    states, res = _item_turn(p1, p2, [("move roost", "move attract")], ("roost", "attract"))
    assert "attract" in states[1]["sides"][1]["mons"][0]["volatiles"]  # Showdown: the foe too
    assert res["diff"] == {}


def test_control_wish():
    """Wish heals half the user's max HP at the end of the next turn (harness: Showdown's
    startingTurn to the engine's count)."""
    p1 = _corviknight("Leftovers").replace("- Defog", "- Wish")
    turns = [("move wish", "move ruination"), ("move roost", "move ruination")]
    states = ec.run_showdown(p1, TINGLU_HITS, turns, seed="gen5,5,5,5,5")
    assert any("move: Wish" in x for x in states[2]["log"])  # Showdown: healed
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "roost", "ruination")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


def _engine_hit_counts(state, c1, c2) -> dict[int, float]:
    """The chance of each number of hits on side two (its Damage instructions) in side one's
    move, over the engine's outcomes."""
    out: dict[int, float] = {}
    for si in pe.generate_instructions(state, c1, c2):
        n = sum(1 for i in si.instruction_list if str(i).startswith("Damage SideTwo"))
        out[n] = out.get(n, 0.0) + si.percentage / 100
    return out


# L30 (doc/engine-diff.md): fixed in rust/patches (2026-10-16); a regression test now
@pytest.mark.parametrize("item, counts", [("Leftovers", (2, 3, 4, 5)), ("Loaded Dice", (4, 5))])
def test_l30_multi_hit_counts(item, counts):
    """2-5 hits: 35 / 35 / 15 / 15% (Loaded Dice: 4 or 5), Showdown's rates over 1,000 seeds."""
    p1 = _setter("Breloom", "Technician", item, "- Bullet Seed\n- Mach Punch\n- Spore\n- Swords Dance")
    turns = [("move bulletseed", "move softboiled")]
    states = ec.run_showdown(p1, BLISSEY, turns)
    engine = _engine_hit_counts(ec.engine_state(states[0]), "bulletseed", "softboiled")
    for n in counts:
        rate = ec.showdown_rate(p1, BLISSEY, turns, f"|-hitcount|p2a: Blissey|{n}", 1000)
        assert engine.get(n, 0.0) == pytest.approx(rate, abs=0.04), (n, rate, engine)


# L8b, second step (doc/engine-diff.md): the expected power (80 x 1.3) was an approximation
def test_l8b_fickle_beam_double_power_branch():
    """30% of the time double power (Showdown's rate over 1,000 seeds): the engine's outcomes
    with at least 1.9 x the smallest damage (a crit is 1.5 x) have that chance."""
    turns = [("move ficklebeam", "move softboiled")]
    rate = ec.showdown_rate(HYDRAPPLE, BLISSEY, turns, "move: Fickle Beam", 1000)
    states = ec.run_showdown(HYDRAPPLE, BLISSEY, turns)
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "ficklebeam", "softboiled")
    low = min(o.damage[1] for o in outs if o.damage[1] > 0)
    doubled = sum(o[0] for o in outs if o.damage[1] >= 1.9 * low)
    assert doubled == pytest.approx(rate, abs=0.04), rate


def test_l30_multi_hit_crits_per_hit():
    """Each hit of a multi-hit move crits on its own: of the 2-hit Icicle Spears (Showdown, 2,000
    seeds), the share with exactly one crit; the engine's 2-hit outcomes with one crit (damage
    between none and both) in the same share."""
    p1 = KYUREM.replace("- Earth Power", "- Icicle Spear").replace("- Freeze-Dry", "- Scale Shot")
    turns = [("move iciclespear", "move softboiled")]
    logs = ec.showdown_log_counts(p1, BLISSEY, turns, 2000)
    two = [lg for lg in logs if "|-hitcount|p2a: Blissey|2" in lg]
    one_crit = sum(1 for lg in two if sum(x.startswith("|-crit|") for x in lg) == 1) / len(two)
    states = ec.run_showdown(p1, BLISSEY, turns)
    e = ec.engine_state(states[0])
    two_hit = [(si.percentage / 100, sum(int(str(i).split(": ")[1]) for i in si.instruction_list
                                         if str(i).startswith("Damage SideTwo")))
               for si in pe.generate_instructions(e, "iciclespear", "softboiled")
               if sum(str(i).startswith("Damage SideTwo") for i in si.instruction_list) == 2]  # fmt: skip
    total = sum(p for p, _ in two_hit)
    lo, hi = min(d for _, d in two_hit), max(d for _, d in two_hit)
    engine_one = sum(p for p, d in two_hit if lo < d < hi) / total
    assert engine_one == pytest.approx(one_crit, abs=0.025), (one_crit, engine_one)


def test_l30_multi_hit_knockout_rolls():
    """A multi-hit total near the target's HP: its rolls decide the knockout (Bullet Seed into a
    level-82 Shell Armor Lapras: no crits; 3+ hits always knock it out, 2 some of the time:
    Showdown's knockout rate over 1,000 seeds); before, the engine's average total decided."""
    p1 = _setter("Breloom", "Technician", "Leftovers", "- Bullet Seed\n- Mach Punch\n- Spore\n- Swords Dance")
    p2 = "Lapras @ Leftovers\nAbility: Shell Armor\nLevel: 82\n- Freeze-Dry\n- Surf\n- Haze\n- Protect"
    turns = [("move bulletseed", "move haze")]
    rate = ec.showdown_rate(p1, p2, turns, "|faint|p2a: Lapras", 1000)
    states = ec.run_showdown(p1, p2, turns)
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "bulletseed", "haze")
    knocked_out = sum(o[0] for o in outs if o[1].side_two.pokemon[0].hp == 0)
    assert knocked_out == pytest.approx(rate, abs=0.05), (rate, knocked_out)


MEOWSCARADA_TERA_FIRE = """Meowscarada @ Life Orb
Ability: Overgrow
Tera Type: Fire
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Knock Off
- Protect
- Flower Trick
- U-turn"""


# L31 (doc/engine-diff.md): the state gave the tera type as the types, losing the original STAB
@pytest.mark.parametrize("move", ["knockoff", "flowertrick"])
def test_l31_terastallized_keeps_original_stab(move):
    """A terastallized attacker keeps its original types' STAB (Showdown: getTypes(false, true)):
    the engine's damage after Tera Fire, Dark Knock Off / Grass Flower Trick, within the rolls."""
    turns = [("move protect terastallize", "move calmmind"), (f"move {move}", "move calmmind")]
    states = ec.run_showdown(MEOWSCARADA_TERA_FIRE, BLISSEY, turns)
    assert states[1]["sides"][0]["mons"][0]["terastallized"] == "Fire"
    outs = ec.engine_outcomes(ec.engine_state(states[1]), move, "calmmind")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


TYRANITAR_GROUNDER = """Tyranitar @ Leftovers
Ability: Unnerve
Tera Type: Ghost
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Earthquake
- Smack Down
- Stealth Rock
- Protect"""


# L32 (doc/engine-diff.md): a Flying type grounded by Iron Ball / Smack Down is hit by Ground
# moves (Showdown's isGrounded and Iron Ball's onEffectiveness: the Flying type neutral)
@pytest.mark.parametrize("item, pre", [
    ("Iron Ball", []),
    ("Leftovers", [("move smackdown", "move defog")]),
    ("Leftovers", []),  # control: immune
])  # fmt: skip
def test_l32_grounded_flying_hit_by_ground(item, pre):
    turns = pre + [("move earthquake", "move defog")]
    states = ec.run_showdown(TYRANITAR_GROUNDER, _corviknight(item), turns)
    a, b = (s["sides"][1]["mons"][0]["hp"] for s in states[-2:])
    assert (b < a) == (item == "Iron Ball" or bool(pre))
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "earthquake", "defog")
    assert ec.closest(states[-1], outs, (1, 1), hp=True)["diff"] == {}


URSALUNA_FACADE = _setter("Ursaluna", "Bulletproof", "Flame Orb", "- Facade\n- Protect\n- Earthquake\n- Swords Dance")
KINGAMBIT_KNOCK = _setter("Kingambit", "Supreme Overlord", "Leftovers", "- Knock Off\n- Protect\n- Iron Head\n- Swords Dance")
SLOWKING_COLBUR = _setter("Slowking-Galar", "Regenerator", "Colbur Berry", "- Chilly Reception\n- Slack Off\n- Sludge Bomb\n- Future Sight")
PINCURCHIN = _setter("Pincurchin", "Electric Surge", "Leftovers", "- Rising Voltage\n- Spikes\n- Protect\n- Recover")


# L33 (doc/engine-diff.md): found by the damage calculation differential
def test_l33_facade_ignores_burn():
    """Burned: Facade's 140 power, no burn halving (Showdown's modifyDamage, Gen 6+)."""
    turns = [("move protect", "move defog"), ("move facade", "move defog")]
    states = ec.run_showdown(URSALUNA_FACADE, CORVIKNIGHT, turns)
    assert states[1]["sides"][0]["mons"][0]["status"] == "brn"
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "facade", "defog")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


def test_l33_knock_off_boost_with_a_resist_berry():
    """Knock Off's 1.5 x on a resist berry's holder (Showdown's onBasePower sees the berry; it
    is eaten later, onSourceModifyDamage): the engine ate it first (item_before_move)."""
    turns = [("move knockoff", "move sludgebomb")]
    states = ec.run_showdown(KINGAMBIT_KNOCK, SLOWKING_COLBUR, turns)
    assert states[1]["sides"][1]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "knockoff", "sludgebomb")
    outs = [max(outs, key=lambda o: o[0])]  # no crit (a crit's 1.5 x would match the boost's)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


@pytest.mark.parametrize("target, foe", [(BLISSEY, "calmmind"), (CORVIKNIGHT, "roost")])
def test_l33_rising_voltage(target, foe):
    """In Electric Terrain: 2 x against a grounded target (Showdown's onBasePower), 1 x against
    a Flying type (the engine: 1.5 x against both)."""
    turns = [("move spikes", f"move {foe}"), ("move risingvoltage", f"move {foe}")]
    states = ec.run_showdown(PINCURCHIN, target, turns)
    assert states[1]["field"]["terrain"] == "electricterrain"
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "risingvoltage", foe)
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


SLOWKING_PLOT = SLOWKING_FUTURE.replace("- Chilly Reception", "- Nasty Plot")


# L35 (doc/engine-diff.md): found when L31 gave the user its STAB (the two errors had cancelled)
def test_l35_future_sight_user_boosts():
    """Future Sight's damage at the hit uses its user's Special Attack boosts while it is active
    (Showdown's getDamage on the source at the hit); the engine took the unboosted stat."""
    turns = [("move futuresight", "move defog"), ("move nastyplot", "move defog"),
             ("move nastyplot", "move defog")]  # fmt: skip
    states = ec.run_showdown(SLOWKING_PLOT, CORVIKNIGHT, turns, seed="gen5,5,5,5,5")
    assert "|-end|p2a: Corviknight|move: Future Sight" in states[3]["log"]
    assert states[3]["sides"][0]["mons"][0]["boosts"]["spa"] == 4
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "nastyplot", "defog")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


IRON_CROWN = """Iron Crown @ Booster Energy
Ability: Quark Drive
Tera Type: Fighting
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Psyshock
- Calm Mind
- Tachyon Cutter
- Focus Blast"""


def test_l35_neutralizing_gas_suppresses_quark_drive():
    """With Neutralizing Gas out, a Quark Drive / Protosynthesis boost does nothing (its
    handlers check ignoringAbility()): Iron Crown's Special Attack, its quarkdrive volatile
    still on."""
    turns = [("move calmmind", "switch 2"), ("move psyshock", "move willowisp")]
    states = ec.run_showdown(IRON_CROWN, BLISSEY + "\n\n" + WEEZING, turns)
    assert "quarkdrive" in states[1]["sides"][0]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "psyshock", "willowisp")
    assert ec.closest(states[2], outs, (1, 2), hp=True)["diff"] == {}


def test_l35_neutralizing_gas_attacker_suppresses_target_ability():
    """A Neutralizing Gas user's hit ignores the target's ability too (Vessel of Ruin's Special
    Attack drop): the engine only checked a Neutralizing Gas target."""
    turns = [("move strangesteam", "move spikes")]
    states = ec.run_showdown(WEEZING, TINGLU, turns)
    hit = next(x for x in states[1]["log"] if x.startswith("|-damage|p2a") and "[from]" not in x)
    assert "|-crit" not in "".join(states[1]["log"])
    dealt = 514 - int(hit.split("|")[3].split("/")[0])  # Showdown's roll of it
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "strangesteam", "spikes")
    low = min(o.damage[1] for o in outs if o.damage[1] > 0)  # no crit: the engine's average roll
    assert 0.85 / 0.925 * low - 2 <= dealt <= low / 0.925 + 2, (dealt, low)


def _hit(before: dict, after: dict, attacker: str, target: str) -> tuple[int, bool, bool]:
    """Showdown's damage of the attacker's move this turn on the target (from the log), whether
    it crit and whether it was capped by the target's HP (a knockout)."""
    side = before["sides"][1 if target.startswith("p2") else 0]
    hp = side["mons"][side["active"]]["hp"]
    log = after["log"]
    i = next(k for k, x in enumerate(log) if x.startswith(f"|move|{attacker}"))
    for x in log[:i]:  # HP changes before the move
        if x.startswith((f"|-damage|{target}", f"|-heal|{target}")):
            hp = int(x.split("|")[3].split("/")[0].split()[0])
    crit = False
    for x in log[i + 1:]:
        if x.startswith("|move|"):
            break
        crit |= x.startswith(f"|-crit|{target}")
        if x.startswith(f"|-damage|{target}") and "[from]" not in x:
            left = int(x.split("|")[3].split("/")[0].split()[0])
            return hp - left, crit, left == 0
    raise AssertionError("no hit")


def _attacker(species, ability, item, moves, nature="Adamant"):
    return f"""{species} @ {item}
Ability: {ability}
Tera Type: Normal
EVs: 252 Atk / 4 SpD / 252 SpA
{nature} Nature
{moves}"""


DONDOZO = _setter("Dondozo", "Unaware", "Leftovers", "- Rest\n- Wave Crash\n- Curse\n- Yawn")
DRAGONITE = _setter("Dragonite", "Multiscale", "Heavy-Duty Boots", "- Roost\n- Earthquake\n- Extreme Speed\n- Dragon Dance")
TINGLU_AV = _setter("Ting-Lu", "Vessel of Ruin", "Assault Vest", "- Earthquake\n- Ruination\n- Payback\n- Stone Edge")
TINGLU_HITS_EQ = _setter("Ting-Lu", "Vessel of Ruin", "Leftovers", "- Earthquake\n- Ruination\n- Payback\n- Spikes")
KYUREM_SPECIAL = _attacker("Kyurem", "Pressure", "Leftovers", "- Ice Beam\n- Earth Power\n- Freeze-Dry\n- Protect", "Modest")

# L34 (doc/engine-diff.md): Showdown's damage step by step with its rounding; each case's hit
# must be one of the engine's 16 rolls (alpha_search.damage_rolls), not only near them
ROLL_CASES = [  # (attacker, target, turns, attacker's move, target's move)
    (_attacker("Great Tusk", "Protosynthesis", "Life Orb", "- Headlong Rush\n- Ice Spinner\n- Rapid Spin\n- Knock Off"), TINGLU, [], "headlongrush", "spikes"),
    (_attacker("Kingambit", "Supreme Overlord", "Choice Band", "- Iron Head\n- Kowtow Cleave\n- Sucker Punch\n- Knock Off"), TINGLU, [], "ironhead", "spikes"),
    (_attacker("Gholdengo", "Good as Gold", "Choice Specs", "- Shadow Ball\n- Make It Rain\n- Trick\n- Focus Blast", "Modest"), TINGLU_AV, [], "shadowball", "earthquake"),
    (_attacker("Great Tusk", "Protosynthesis", "Leftovers", "- Close Combat\n- Ice Spinner\n- Rapid Spin\n- Knock Off"), CHANSEY, [], "closecombat", "calmmind"),
    (KYUREM_SPECIAL, DRAGONITE, [], "icebeam", "dragondance"),
    (_attacker("Venomoth", "Tinted Lens", "Life Orb", "- Bug Buzz\n- Sludge Bomb\n- Quiver Dance\n- Sleep Powder", "Modest"), CORVIKNIGHT, [], "bugbuzz", "defog"),
    (_attacker("Crawdaunt", "Adaptability", "Life Orb", "- Crabhammer\n- Knock Off\n- Aqua Jet\n- Swords Dance"), TINGLU, [], "crabhammer", "spikes"),
    (_attacker("Scizor", "Technician", "Choice Band", "- Bullet Punch\n- U-turn\n- Knock Off\n- Close Combat"), TINGLU, [], "bulletpunch", "spikes"),
    (KINGAMBIT_KNOCK, SLOWKING_COLBUR, [], "knockoff", "sludgebomb"),
    (_attacker("Rillaboom", "Grassy Surge", "Choice Band", "- Grassy Glide\n- Wood Hammer\n- U-turn\n- Knock Off"), TINGLU, [], "grassyglide", "spikes"),
    (KYUREM_SPECIAL, DONDOZO, [], "freezedry", "curse"),
    # Expert Belt's "super effective" includes Freeze-Dry on Water
    (_attacker("Kyurem", "Pressure", "Expert Belt", "- Ice Beam\n- Earth Power\n- Freeze-Dry\n- Protect", "Modest"), DONDOZO, [], "freezedry", "curse"),
    # Guts boosts the Attack only (the engine: any move's power)
    (_attacker("Conkeldurr", "Guts", "Flame Orb", "- Focus Blast\n- Drain Punch\n- Mach Punch\n- Protect", "Modest"), TINGLU, [("move protect", "move spikes")], "focusblast", "spikes"),
    # Grassy Terrain halves Bulldoze too (the engine: Earthquake only)
    (_attacker("Great Tusk", "Protosynthesis", "Leftovers", "- Bulldoze\n- Ice Spinner\n- Rapid Spin\n- Knock Off"), _setter("Rillaboom", "Grassy Surge", "Leftovers", "- Swords Dance\n- Wood Hammer\n- U-turn\n- Knock Off"), [], "bulldoze", "swordsdance"),
    # Eruption at 71 / 281 HP: 37.9 power, Showdown's 37 (a fraction is floored, its modifiers
    # skipped: runEvent modifies integers only); Choice Specs on a frail target, for a difference
    (_attacker("Torkoal", "Drought", "Choice Specs", "- Eruption\n- Lava Plume\n- Rapid Spin\n- Stealth Rock", "Modest"),
     TINGLU_HITS_EQ + "\n\n" + _attacker("Kingambit", "Pressure", "Leftovers", "- Iron Head\n- Kowtow Cleave\n- Swords Dance\n- Protect"),
     [("move eruption", "move earthquake"), ("move eruption", "switch 2")], "eruption", "swordsdance"),
    (_attacker("Ursaluna", "Guts", "Flame Orb", "- Headlong Rush\n- Facade\n- Protect\n- Trailblaze"), WEEZING, [("move protect", "move protect")], "headlongrush", "willowisp"),
]  # fmt: skip


@pytest.mark.parametrize("attacker, target, pre, move, foe", ROLL_CASES,
                         ids=[c[3] + "-" + c[0].split(" @")[0] for c in ROLL_CASES])  # fmt: skip
def test_l34_damage_is_a_showdown_roll(attacker, target, pre, move, foe):
    import alpha_search

    states = ec.run_showdown(attacker, target, pre + [(f"move {move}", f"move {foe}")])
    dealt, crit, capped = _hit(states[-2], states[-1], "p1a: ", "p2a: ")
    rolls = alpha_search.damage_rolls(ec.engine_state(states[-2]).to_string(), True, move, foe)
    r = rolls[1] if crit else rolls[0]
    assert dealt in r or (capped and dealt <= r[-1]), (dealt, crit, r)


@pytest.mark.parametrize("attacker, target, pre, move, foe", ROLL_CASES,
                         ids=[c[3] + "-" + c[0].split(" @")[0] for c in ROLL_CASES])  # fmt: skip
def test_l34_max_damage_matches_showdown(attacker, target, pre, move, foe):
    """The max roll (no crit) is Showdown's exactly (its getDamage on a copy of the battle at the
    turn's start: showdown_damage.js)."""
    import alpha_search

    states = ec.run_showdown(attacker, target, pre + [(f"move {move}", f"move {foe}")],
                             damage_probe=True)  # fmt: skip
    want = states[-2]["damage"]["p1"][move]
    rolls = alpha_search.damage_rolls(ec.engine_state(states[-2]).to_string(), True, move, foe)
    assert rolls[0][-1] == want


def test_l35_future_sight_user_life_orb():
    """Future Sight's hit is its user's move (while active): its Life Orb's 1.3 x on the damage
    and 1/10 recoil (Showdown's onModifyDamage / onAfterMoveSecondarySelf on the source)."""
    turns = [("move futuresight", "move defog"), ("move nastyplot", "move defog"),
             ("move nastyplot", "move defog")]  # fmt: skip
    p1 = SLOWKING_PLOT.replace("@ Heavy-Duty Boots", "@ Life Orb")
    states = ec.run_showdown(p1, CORVIKNIGHT, turns, seed="gen5,5,5,5,5")
    assert any("[from] item: Life Orb" in x for x in states[3]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "nastyplot", "defog")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


BLAZIKEN = _setter("Blaziken", "Speed Boost", "Leftovers", "- Protect\n- Flare Blitz\n- Close Combat\n- Swords Dance")


# L37 (doc/engine-diff.md): Speed Boost needs a turn on the field (Showdown's activeTurns: 0 at
# the end of the turn it came in; a replacement after a faint has 1 by the next end of turn)
@pytest.mark.parametrize("turns, choices, spe", [
    ([("switch 2", "move spikes")], ("blaziken", "spikes"), 0),
    ([("switch 2", "move spikes"), ("move protect", "move spikes")], ("protect", "spikes"), 1),
])  # fmt: skip
def test_l37_speed_boost_not_on_the_switch_in_turn(turns, choices, spe):
    states = ec.run_showdown(BLISSEY + "\n\n" + BLAZIKEN, TINGLU, turns)
    assert states[-1]["sides"][0]["mons"][1]["boosts"]["spe"] == spe
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), *choices)
    assert ec.closest(states[-1], outs, (2, 1))["diff"] == {}


# L38 (doc/engine-diff.md): Rest fails at full HP (Showdown's onTry), and where sleep cannot be
# set (setStatus: Misty / Electric Terrain on a grounded user, Purifying Salt, ...)
@pytest.mark.parametrize("pre, slept", [
    ([], False),  # full HP
    ([("move curse", "move earthquake")], True),  # control: damaged
])  # fmt: skip
def test_l38_rest_fails_at_full_hp(pre, slept):
    turns = pre + [("move rest", "move spikes")]
    states = ec.run_showdown(DONDOZO, TINGLU_HITS_EQ, turns)
    assert (states[-1]["sides"][0]["mons"][0]["status"] == "slp") == slept
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "rest", "spikes")
    assert ec.closest(states[-1], outs, (1, 1))["diff"] == {}


def test_l38_rest_fails_with_purifying_salt():
    garganacl = _setter("Garganacl", "Purifying Salt", "Leftovers", "- Rest\n- Salt Cure\n- Protect\n- Stealth Rock")
    turns = [("move protect", "move earthquake"), ("move rest", "move spikes")]
    states = ec.run_showdown(garganacl, TINGLU_HITS_EQ, turns)
    assert states[-1]["sides"][0]["mons"][0]["status"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "rest", "spikes")
    assert ec.closest(states[-1], outs, (1, 1))["diff"] == {}


INCINEROAR_INTIM = _setter("Incineroar", "Intimidate", "Leftovers", "- Knock Off\n- Parting Shot\n- Flare Blitz\n- Will-O-Wisp")
DRAGAPULT = _attacker("Dragapult", "Clear Body", "Choice Specs", "- Shadow Ball\n- Draco Meteor\n- U-turn\n- Flamethrower", "Timid")


# L39 (doc/engine-diff.md): both sides switching, the faster of the two leaving switches first
# (Showdown's switch actions by the outgoing mon's speed; Trick Room reverses it): the engine
# always switched side one first (an Intimidate hit the wrong mon)
@pytest.mark.parametrize("p1, p2", [
    (BLISSEY + "\n\n" + CORVIKNIGHT, DRAGAPULT + "\n\n" + INCINEROAR_INTIM),  # side two leaves faster
    (DRAGAPULT + "\n\n" + CORVIKNIGHT, BLISSEY + "\n\n" + INCINEROAR_INTIM),  # control: side one
])  # fmt: skip
def test_l39_double_switch_order(p1, p2):
    states = ec.run_showdown(p1, p2, [("switch 2", "switch 2")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "corviknight", "incineroar")
    assert ec.closest(states[1], outs, (2, 2))["diff"] == {}


PECHARUNT = _setter("Pecharunt", "Poison Puppeteer", "Heavy-Duty Boots", "- Malignant Chain\n- Toxic\n- Recover\n- Parting Shot")


# L40 (doc/engine-diff.md): Poison Puppeteer, a target Pecharunt's move poisons is confused too
# (Showdown's onAnyAfterSetStatus); not implemented in the engine
@pytest.mark.parametrize("move", ["malignantchain", "toxic"])
def test_l40_poison_puppeteer(move):
    states = ec.run_showdown(PECHARUNT, BLISSEY, [(f"move {move}", "move calmmind")],
                             force_random=True)  # fmt: skip
    assert "confusion" in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "calmmind")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


MEOWSCARADA_PROTEAN = _attacker("Meowscarada", "Protean", "Choice Band", "- Knock Off\n- Flower Trick\n- U-turn\n- Sucker Punch", "Jolly")


# L41 (doc/engine-diff.md): Gen 9 Protean / Libero, once per entry, when the move starts
# (onPrepareHit: not when it cannot move, not when its onTry fails), to the move's type unless
# the user is already exactly that type (a Grass / Dark user of Knock Off becomes pure Dark)
@pytest.mark.parametrize("move, foe, changed", [
    ("knockoff", "spikes", True),  # Grass / Dark -> Dark
    ("suckerpunch", "spikes", False),  # fails (the target uses a status move): no change
])  # fmt: skip
def test_l41_protean(move, foe, changed):
    states = ec.run_showdown(MEOWSCARADA_PROTEAN, TINGLU, [(f"move {move}", f"move {foe}")])
    m = states[1]["sides"][0]["mons"][0]
    assert (m["types"] != m["base_types"]) == changed
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, foe)
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


def test_l41_protean_not_when_frozen():
    """Frozen (the 80% it stays so), the move does not start: no type change (the engine's
    Protean was before the freeze check)."""
    states = ec.run_showdown(MEOWSCARADA_PROTEAN, TINGLU, [])
    st = states[0]
    st["sides"][0]["mons"][0]["status"] = "frz"
    outs = ec.engine_outcomes(ec.engine_state(st), "uturn", "spikes")
    stuck = [o for o in outs if "FREEZE" in str(o[1].side_one.pokemon[0].status).upper()]
    assert stuck
    assert all("GRASS" in str(o[1].side_one.pokemon[0].types[0]).upper() for o in stuck), [
        o[1].side_one.pokemon[0].types for o in stuck]


# L42 (doc/engine-diff.md): a guaranteed crit's knockout by its crit rolls (the engine took the
# crit's average whenever the non-crit max could not knock out)
def test_l42_guaranteed_crit_knockout_rolls():
    import alpha_search

    states = ec.run_showdown(MEOWSCARADA_PROTEAN, TINGLU, [])
    st = states[0]
    e = ec.engine_state(st)
    crit = alpha_search.damage_rolls(e.to_string(), True, "flowertrick", "spikes")[1]
    hp = crit[8]
    st["sides"][1]["mons"][0]["hp"] = hp
    outs = ec.engine_outcomes(ec.engine_state(st), "flowertrick", "spikes")
    kill = sum(o[0] for o in outs if o[1].side_two.pokemon[0].hp == 0)
    assert kill == pytest.approx(sum(d >= hp for d in crit) / 16, abs=1e-3), (crit, hp)


GARGANACL_SUB = _setter("Garganacl", "Purifying Salt", "Leftovers", "- Substitute\n- Salt Cure\n- Protect\n- Recover")


# harness (doc/engine-diff.md, L43): the Substitute's HP from Showdown's state (it was 0 in the
# engine: any hit broke it)
def test_l43_substitute_hp_mapped():
    turns = [("move substitute", "move calmmind"), ("move recover", "move seismictoss")]
    states = ec.run_showdown(GARGANACL_SUB, BLISSEY, turns)
    assert "substitute" in states[2]["sides"][0]["mons"][0]["volatiles"]  # 101 HP, 100 taken
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "recover", "seismictoss")
    assert ec.closest(states[2], outs, (1, 1))["diff"] == {}


# L44 (doc/engine-diff.md): Red Card does nothing when the attacker's side has no one to switch
# in (Showdown's canSwitch); Air Balloon pops when a hit only breaks / damages a Substitute
# (its onAfterSubDamage)
def test_l44_red_card_needs_a_replacement():
    red = _setter("Blissey", "Natural Cure", "Red Card", "- Soft-Boiled\n- Seismic Toss\n- Calm Mind\n- Protect")
    turns = [("move calmmind", "move earthquake")]
    # (no crit: force_random False; Ting-Lu alone: no replacement)
    states = ec.run_showdown(red, TINGLU_HITS_EQ, turns, force_random=False)
    assert states[1]["sides"][0]["mons"][0]["item"] == "redcard"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "calmmind", "earthquake")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


def test_l44_air_balloon_pops_on_a_substitute_hit():
    gliscor = _setter("Gliscor", "Poison Heal", "Air Balloon", "- Substitute\n- Protect\n- Earthquake\n- Toxic")
    turns = [("move substitute", "move calmmind"), ("move toxic", "move seismictoss")]
    states = ec.run_showdown(gliscor, BLISSEY, turns)
    assert states[2]["sides"][0]["mons"][0]["item"] == ""  # Showdown: popped through the Sub
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "toxic", "seismictoss")
    assert ec.closest(states[2], outs, (1, 1))["diff"] == {}


# L45 (doc/engine-diff.md): Lum Berry cures confusion too (Showdown's onUpdate: a status or
# confusion), at once; resist berries only on a damaging, non-fixed hit (onSourceModifyDamage:
# not Ground Spikes, Dark Nasty Plot, Ruination)
def test_l45_lum_berry_cures_confusion():
    lum = _setter("Blissey", "Natural Cure", "Lum Berry", "- Soft-Boiled\n- Seismic Toss\n- Calm Mind\n- Protect")
    sableye = _setter("Sableye", "Prankster", "Leftovers", "- Confuse Ray\n- Recover\n- Knock Off\n- Will-O-Wisp")
    states = ec.run_showdown(lum, sableye, [("move calmmind", "move confuseray")])
    b = states[1]["sides"][0]["mons"][0]
    assert b["item"] == "" and "confusion" not in b["volatiles"] and b["boosts"]["spa"] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "calmmind", "confuseray")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


@pytest.mark.parametrize("holder, move, foe", [
    (_setter("Gholdengo", "Good as Gold", "Shuca Berry", "- Shadow Ball\n- Nasty Plot\n- Recover\n- Make It Rain"), "nastyplot", "spikes"),
    (_setter("Slowking-Galar", "Regenerator", "Colbur Berry", "- Slack Off\n- Sludge Bomb\n- Future Sight\n- Nasty Plot"), "slackoff", "ruination"),
])  # fmt: skip
def test_l45_resist_berry_only_on_a_damaging_hit(holder, move, foe):
    target = TINGLU_HITS_EQ if foe == "ruination" else TINGLU
    states = ec.run_showdown(holder, target, [(f"move {move}", f"move {foe}")])
    assert states[1]["sides"][0]["mons"][0]["item"] != ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, foe)
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


UMBREON = _setter("Umbreon", "Synchronize", "Leftovers", "- Foul Play\n- Wish\n- Protect\n- Toxic")


# L46 (doc/engine-diff.md): Synchronize, a poison / burn / paralysis from the foe goes back to
# it (Showdown's onAfterSetStatus; not sleep / freeze); not implemented in the engine
SYNC_FOE = _setter("Blissey", "Natural Cure", "Heavy-Duty Boots", "- Thunder Wave\n- Toxic\n- Soft-Boiled\n- Will-O-Wisp")


@pytest.mark.parametrize("foe, foe_move, status", [
    (SYNC_FOE, "thunderwave", "par"),
    (SYNC_FOE, "toxic", "tox"),
    (SYNC_FOE, "willowisp", "brn"),
])  # fmt: skip
def test_l46_synchronize(foe, foe_move, status):
    states = ec.run_showdown(UMBREON, foe, [("move wish", f"move {foe_move}")])
    assert states[1]["sides"][1]["mons"][0]["status"] == status
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "wish", foe_move)
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# harness (doc/engine-diff.md, L47): Rest's sleep (Showdown: the statusState's source is the
# sleeper itself; its sourceEffect is not kept, so the dump's source was always empty and Rest's
# sleep went to the engine as an ordinary one)
@pytest.mark.parametrize("asleep_turns", [1, 2, 3])
def test_l47_rest_sleep_mapped(asleep_turns):
    turns = [("move curse", "move earthquake"), ("move rest", "move spikes")]
    turns += [("move rest", "move spikes")] * asleep_turns
    states = ec.run_showdown(DONDOZO, TINGLU_HITS_EQ, turns)
    asleep = states[-1]["sides"][0]["mons"][0]["status"] == "slp"  # Rest: 2 turns asleep
    assert asleep == (asleep_turns < 3)
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "rest", "spikes")
    p = sum(o[0] for o in outs if ("SLEEP" in str(o[1].side_one.pokemon[0].status).upper()) == asleep)
    assert p == pytest.approx(1.0, abs=1e-3)  # deterministic: no wake-up roll


HEALING_WISHER = _setter("Blissey", "Natural Cure", "Leftovers", "- Healing Wish\n- Soft-Boiled\n- Calm Mind\n- Protect")


# harness (doc/engine-diff.md, L48): Healing Wish waiting on its slot (Gen 9: until a mon that
# needs it comes in) was not mapped (a slot condition in Showdown, a side condition in the engine)
def test_l48_healing_wish_waits_mapped():
    team = DONDOZO + "\n\n" + HEALING_WISHER + "\n\n" + CORVIKNIGHT
    turns = [("move curse", "move earthquake"), ("switch 2", "move spikes"),
             ("move healingwish", "move spikes"), ("switch 3", ""),  # Corviknight: full HP, it waits
             ("switch 2", "move spikes")]  # fmt: skip
    states = ec.run_showdown(team, TINGLU_HITS_EQ, turns)
    assert "healingwish" in states[-2]["sides"][0]["slot"]
    assert any("[from] move: Healing Wish" in x for x in states[-1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "dondozo", "spikes")
    assert ec.closest(states[-1], outs, (3, 1), hp=True)["diff"] == {}


# L49 (doc/engine-diff.md): Belly Drum fails at +6 Attack (Showdown's onHit); the engine still
# took half the HP
def test_l49_belly_drum_fails_at_plus_six():
    azumarill = _setter("Azumarill", "Huge Power", "Sitrus Berry", "- Belly Drum\n- Aqua Jet\n- Play Rough\n- Protect")
    turns = [("move bellydrum", "move spikes"), ("move bellydrum", "move spikes")]
    states = ec.run_showdown(azumarill, TINGLU, turns)
    assert any("|-fail|p1a: Azumarill" in x for x in states[2]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "bellydrum", "spikes")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L50 (doc/engine-diff.md): a crash move (High Jump Kick, Supercell Slam, ...) into an immune
# target crashes too (Showdown's onMoveFail: a miss, an immunity, a Protect); and each hit of a
# multi-hit move into Rocky Helmet hurts (once per hit, Showdown's onDamagingHit)
def test_l50_crash_into_an_immune_target():
    hands = _attacker("Iron Hands", "Quark Drive", "Leftovers", "- Supercell Slam\n- Drain Punch\n- Ice Punch\n- Swords Dance")
    treads = _setter("Iron Treads", "Quark Drive", "Leftovers", "- Stealth Rock\n- Rapid Spin\n- Earthquake\n- Knock Off")
    states = ec.run_showdown(hands, treads, [("move supercellslam", "move stealthrock")])
    assert any("[from] supercellslam" in x for x in states[1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "supercellslam", "stealthrock")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l50_rocky_helmet_per_hit():
    cinccino = _attacker("Cinccino", "Skill Link", "Leftovers", "- Tail Slap\n- U-turn\n- Knock Off\n- Tidy Up", "Jolly")
    lando = _setter("Landorus-Therian", "Intimidate", "Rocky Helmet", "- Stealth Rock\n- Earthquake\n- U-turn\n- Taunt")
    states = ec.run_showdown(cinccino, lando, [("move tailslap", "move stealthrock")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "tailslap", "stealthrock")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L51 (doc/engine-diff.md): a crit that can knock out (the non-crit max cannot) by its exact
# rolls (the engine took the crit's average: a sure knockout whenever it reached the HP)
def test_l51_crit_knockout_rolls():
    import alpha_search

    states = ec.run_showdown(KINGAMBIT_KNOCK.replace("- Protect", "- Kowtow Cleave"), TINGLU, [])
    st = states[0]
    normal, crit = alpha_search.damage_rolls(ec.engine_state(st).to_string(), True,
                                             "kowtowcleave", "spikes")  # fmt: skip
    hp = crit[8]
    assert normal[-1] < hp
    st["sides"][1]["mons"][0]["hp"] = hp
    outs = ec.engine_outcomes(ec.engine_state(st), "kowtowcleave", "spikes")
    kill = sum(o[0] for o in outs if o[1].side_two.pokemon[0].hp == 0)
    assert kill == pytest.approx(CRIT_CHANCE[1] * sum(d >= hp for d in crit) / 16, abs=1e-4)


LUNAR_DANCER = _setter("Cresselia", "Levitate", "Leftovers", "- Lunar Dance\n- Moonlight\n- Calm Mind\n- Protect")


# L52 (doc/engine-diff.md): Lunar Dance had no effect in the engine (the user faints, the next
# mon that needs it is healed, as Healing Wish; its PP restoring is not modelled)
@pytest.mark.parametrize("waits", [False, True])
def test_l52_lunar_dance(waits):
    team = DONDOZO + "\n\n" + LUNAR_DANCER + "\n\n" + CORVIKNIGHT
    turns = [("move curse", "move earthquake"), ("switch 2", "move spikes"),
             ("move lunardance", "move spikes")]  # fmt: skip
    if not waits:  # the user faints this turn
        states = ec.run_showdown(team, TINGLU_HITS_EQ, turns)
        assert states[-1]["sides"][0]["mons"][1]["hp"] == 0
        outs = ec.engine_outcomes(ec.engine_state(states[-2]), "lunardance", "spikes")
        assert ec.closest(states[-1], outs, (3, 1))["diff"] == {}
        return
    turns += [("switch 3", ""), ("switch 2", "move spikes")]
    states = ec.run_showdown(team, TINGLU_HITS_EQ, turns)
    assert any("[from] move: Lunar Dance" in x for x in states[-1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "dondozo", "spikes")
    assert ec.closest(states[-1], outs, (3, 1), hp=True)["diff"] == {}


# L53 (doc/engine-diff.md): Weakness Policy is not set off by a fixed damage (Showdown:
# !move.damage && !move.damageCallback)
def test_l53_weakness_policy_not_by_fixed_damage():
    ceruledge = _setter("Ceruledge", "Weak Armor", "Weakness Policy", "- Bulk Up\n- Bitter Blade\n- Shadow Sneak\n- Protect")
    states = ec.run_showdown(ceruledge, TINGLU_HITS_EQ, [("move bulkup", "move ruination")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "weaknesspolicy"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "bulkup", "ruination")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


SABLEYE = _setter("Sableye", "Prankster", "Leftovers", "- Confuse Ray\n- Recover\n- Will-O-Wisp\n- Knock Off")


# L54 (doc/engine-diff.md): confusion's self-hit, Showdown's getConfusionDamage: 40 power of the
# mon's own boosted Attack on its Defense, a roll, no burn halving (the engine: the max roll,
# halved when burned)
def test_l54_confusion_self_hit_burned():
    turns = [("move calmmind", "move willowisp"), ("move calmmind", "move confuseray")]
    states = ec.run_showdown(BLISSEY, SABLEYE, turns, force_random=True)
    assert states[1]["sides"][0]["mons"][0]["status"] == "brn"
    hit = next(x for x in states[2]["log"] if x.endswith("[from] confusion"))
    sd = states[1]["sides"][0]["mons"][0]["hp"] - int(hit.split("|")[3].split("/")[0])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "calmmind", "confuseray")
    burn = 714 // 16
    self_hit = max(o.damage[0] for o in outs) - burn  # the self-hit branch, less the burn
    assert abs(self_hit - sd) <= 0.16 * sd + 1, (self_hit, sd)  # within the roll's spread


# L55 (doc/engine-diff.md): Sheer Force removes Life Orb's recoil on a move it boosts (Showdown
# skips AfterMoveSecondarySelf for it); control: a move without secondaries
@pytest.mark.parametrize("move, recoil", [("icebeam", False), ("earthquake", True)])
def test_l55_sheer_force_life_orb(move, recoil):
    gator = _attacker("Feraligatr", "Sheer Force", "Life Orb", "- Ice Beam\n- Earthquake\n- Crunch\n- Dragon Dance")
    states = ec.run_showdown(gator, TINGLU, [(f"move {move}", "move spikes")])
    assert any("[from] item: Life Orb" in x for x in states[1]["log"]) == recoil
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "spikes")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


JIRACHI = _setter("Jirachi", "Serene Grace", "Leftovers", "- Doom Desire\n- Wish\n- Protect\n- Iron Head")


# L56 (doc/engine-diff.md): Doom Desire's hit is a Steel move of 140 power (the engine hit with
# Future Sight's Psychic 120: nothing on a Dark type)
def test_l56_doom_desire():
    turns = [("move doomdesire", "move spikes"), ("move protect", "move spikes"),
             ("move wish", "move spikes")]  # fmt: skip
    states = ec.run_showdown(JIRACHI, TINGLU, turns, seed="gen5,5,5,5,5")
    assert any(x.endswith("move: Doom Desire") for x in states[3]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "wish", "spikes")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


# L58 (doc/engine-diff.md): Triple Axel's hits each check accuracy (90%), stopping at a miss,
# 20 / 40 / 60 power (the engine: one check, 3 hits of 40); Skill Link: all 3
@pytest.mark.parametrize("ability", ["Pressure", "Skill Link"])
def test_l58_triple_axel_hits(ability):
    p1 = _attacker("Weavile", ability, "Leftovers", "- Triple Axel\n- Knock Off\n- Ice Shard\n- Swords Dance", "Jolly")
    turns = [("move tripleaxel", "move softboiled")]
    states = ec.run_showdown(p1, BLISSEY, turns)
    engine = _engine_hit_counts(ec.engine_state(states[0]), "tripleaxel", "softboiled")
    for n in (1, 2, 3):
        rate = ec.showdown_rate(p1, BLISSEY, turns, f"|-hitcount|p2a: Blissey|{n}", 1000)
        assert engine.get(n, 0.0) == pytest.approx(rate, abs=0.03), (n, rate, engine)


# L58: Population Bomb, 10 hits each checking accuracy (90%), stopping at a miss (the engine: 6
# hits); Loaded Dice: one check, 4-10 hits; Skill Link: 10. The engine's counts in four bands
# (1-3, 4-6, 7-9, 10), each as its mean count (2, 5, 8, 10): Showdown's rates per band
BANDS = {2: range(1, 4), 5: range(4, 7), 8: range(7, 10), 10: range(10, 11)}


@pytest.mark.parametrize("ability, item", [("Technician", "Leftovers"), ("Technician", "Loaded Dice"),
                                           ("Skill Link", "Leftovers")])  # fmt: skip
def test_l58_population_bomb_hits(ability, item):
    p1 = _attacker("Maushold", ability, item, "- Population Bomb\n- Bite\n- Tidy Up\n- Encore", "Jolly")
    turns = [("move populationbomb", "move softboiled")]
    states = ec.run_showdown(p1, BLISSEY, turns)
    engine = _engine_hit_counts(ec.engine_state(states[0]), "populationbomb", "softboiled")
    logs = ec.showdown_log_counts(p1, BLISSEY, turns, 800)
    hits = [next((int(x.rsplit("|", 1)[1]) for x in log if x.startswith("|-hitcount|")), 0)
            for log in logs]  # fmt: skip
    for mean, band in BANDS.items():
        rate = sum(h in band for h in hits) / len(hits)
        assert engine.get(mean, 0.0) == pytest.approx(rate, abs=0.05), (mean, rate, engine)


# L59 (doc/engine-diff.md): a move Protect blocks does nothing (Rapid Spin / Mortal Spin clear no
# hazards, Defog lowers no evasion and clears nothing): the engine's hazard clearing and Defog
# were keyed on the move, not on its (removed) effects
@pytest.mark.parametrize("p1, move", [
    (_attacker("Great Tusk", "Protosynthesis", "Leftovers", "- Rapid Spin\n- Headlong Rush\n- Ice Spinner\n- Knock Off"), "rapidspin"),
    (CORVIKNIGHT, "defog"),
])  # fmt: skip
def test_l59_protected_move_does_nothing(p1, move):
    protector = _setter("Gliscor", "Poison Heal", "Toxic Orb", "- Protect\n- Stealth Rock\n- Earthquake\n- Spikes")
    turns = [("move " + ("headlongrush" if move == "rapidspin" else "roost"), "move stealthrock"),
             (f"move {move}", "move protect")]  # fmt: skip
    states = ec.run_showdown(p1, protector, turns)
    assert "stealthrock" in states[2]["sides"][0]["conditions"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), move, "protect")
    assert ec.closest(states[2], outs, (1, 1))["diff"] == {}


# L60 (doc/engine-diff.md): Ogerpon terastallizing takes its Embody Aspect (the Tera forme's
# ability) and its +1 (Wellspring Sp. Def, Hearthflame Atk, Cornerstone Def, Teal Spe); the
# engine kept the old ability (and gave the boost on a switch-in without checking tera)
@pytest.mark.parametrize("species, ability, item, tera, stat", [
    ("Ogerpon-Wellspring", "Water Absorb", "Wellspring Mask", "Water", "spd"),
    ("Ogerpon", "Defiant", "Leftovers", "Grass", "spe"),
])  # fmt: skip
def test_l60_embody_aspect_on_tera(species, ability, item, tera, stat):
    ogerpon = _attacker(species, ability, item, "- Ivy Cudgel\n- Horn Leech\n- Spikes\n- U-turn",
                        "Jolly").replace("Tera Type: Normal", f"Tera Type: {tera}")  # fmt: skip
    states = ec.run_showdown(ogerpon, BLISSEY, [("move ivycudgel terastallize", "move protect")])
    assert states[1]["sides"][0]["mons"][0]["boosts"][stat] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "ivycudgel-tera", "protect")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L61 (doc/engine-diff.md): a lock (Outrage) Protect stops on its last turn still confuses
# (Showdown's lockedmove onEnd: by trueDuration, however it ends); L22 ended it without
@pytest.mark.parametrize("last", [True, False])
def test_l61_lock_stopped_on_its_last_turn_confuses(last):
    chomp = _setter("Garchomp", "Rough Skin", "Leftovers", "- Outrage\n- Earthquake\n- Swords Dance\n- Stealth Rock")
    corv = _setter("Corviknight", "Pressure", "Leftovers", "- Protect\n- Roost\n- Defog\n- Body Press")
    turns = [("move outrage", "move roost")] * (2 if last else 1) + [("move outrage", "move protect")]
    states = ec.run_showdown(chomp, corv, turns)
    assert ("confusion" in states[-1]["sides"][0]["mons"][0]["volatiles"]) == last
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "outrage", "protect")
    assert ec.closest(states[-1], outs, (1, 1))["diff"] == {}


# L62 (doc/engine-diff.md): Unburden was never set off in the engine (its volatile only read for
# the Speed): an item used or lost while out puts it on (Showdown's onAfterUseItem / onTakeItem)
@pytest.mark.parametrize("item, foe_move", [("Sitrus Berry", "ruination"), ("Leftovers", "knockoff")])
def test_l62_unburden(item, foe_move):
    hawlucha = _setter("Hawlucha", "Unburden", item, "- Swords Dance\n- Acrobatics\n- Close Combat\n- Roost")
    tinglu = _setter("Ting-Lu", "Vessel of Ruin", "Leftovers", "- Ruination\n- Knock Off\n- Spikes\n- Whirlwind")
    states = ec.run_showdown(hawlucha, tinglu, [("move swordsdance", f"move {foe_move}")])
    assert "unburden" in states[1]["sides"][0]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "swordsdance", foe_move)
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L63 (doc/engine-diff.md): a sound move (Parting Shot) or an Infiltrator's move lowers the stats
# of a target behind a Substitute (Showdown's bypasssub); the engine's Substitute blocked them
def test_l63_parting_shot_through_a_substitute():
    grimm = _setter("Grimmsnarl", "Prankster", "Leftovers", "- Parting Shot\n- Spirit Break\n- Thunder Wave\n- Reflect")
    prim = _setter("Primarina", "Torrent", "Leftovers", "- Substitute\n- Moonblast\n- Surf\n- Calm Mind")
    turns = [("move reflect", "move substitute"), ("move partingshot", "move calmmind")]
    states = ec.run_showdown(grimm, prim, turns)
    assert states[2]["sides"][1]["mons"][0]["boosts"]["atk"] == -1
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "partingshot", "calmmind")
    assert ec.closest(states[2], outs, (1, 1))["diff"] == {}


def test_l56_doom_desire_hits_later():
    """Doom Desire is a future move: nothing the turn it is used (the engine hit at once)."""
    states = ec.run_showdown(JIRACHI, TINGLU, [("move doomdesire", "move spikes")])
    assert states[1]["sides"][1]["mons"][0]["hp"] == states[0]["sides"][1]["mons"][0]["hp"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "doomdesire", "spikes")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L64 (doc/engine-diff.md): Red Card's drag comes after the hit's secondaries (Showdown's
# onAfterMoveSecondary); the engine dragged first and the secondaries never happened
def test_l64_red_card_after_secondaries():
    red = _setter("Ting-Lu", "Vessel of Ruin", "Red Card", "- Spikes\n- Ruination\n- Earthquake\n- Whirlwind")
    clef = _attacker("Clefable", "Magic Guard", "Leftovers", "- Moonblast\n- Moonlight\n- Calm Mind\n- Protect", "Modest")
    states = ec.run_showdown(clef + "\n\n" + BLISSEY, red, [("move moonblast", "move spikes")],
                             seed="gen5,1,7,13,3")  # (a seed with the 30% drop)
    assert states[1]["sides"][1]["mons"][0]["boosts"]["spa"] == -1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "moonblast", "spikes")
    assert ec.closest(states[1], outs, (2, 1))["diff"] == {}


# L65 (doc/engine-diff.md): Covert Cloak blocks the secondaries on its holder only (Showdown keeps
# the self ones: Rapid Spin's Speed); the engine dropped every secondary (the target's contact
# abilities too: Static, ..., added to the move as secondaries on its user)
def test_l65_covert_cloak_keeps_self_secondaries():
    tusk = _attacker("Great Tusk", "Protosynthesis", "Leftovers", "- Rapid Spin\n- Headlong Rush\n- Ice Spinner\n- Knock Off")
    cloak = _setter("Blissey", "Natural Cure", "Covert Cloak", "- Soft-Boiled\n- Seismic Toss\n- Calm Mind\n- Protect")
    states = ec.run_showdown(tusk, cloak, [("move rapidspin", "move calmmind")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spe"] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "rapidspin", "calmmind")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L66 (doc/engine-diff.md): Take Heart had no effect in the engine (Showdown: Sp. Atk and Sp. Def
# +1 and its status cured, in code)
def test_l66_take_heart():
    manaphy = _setter("Manaphy", "Hydration", "Leftovers", "- Take Heart\n- Scald\n- Energy Ball\n- Rest")
    turns = [("move scald", "move willowisp"), ("move takeheart", "move recover")]
    states = ec.run_showdown(manaphy, SABLEYE, turns, force_random=True)
    assert states[1]["sides"][0]["mons"][0]["status"] == "brn"
    m = states[2]["sides"][0]["mons"][0]
    assert m["status"] == "" and m["boosts"]["spa"] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "takeheart", "recover")
    assert ec.closest(states[2], outs, (1, 1))["diff"] == {}


def test_l64_red_card_stops_life_orb_recoil():
    """The attacker Red Card drags out takes no Life Orb recoil (its onAfterMoveSecondarySelf
    checks forceSwitchFlag)."""
    red = _setter("Ting-Lu", "Vessel of Ruin", "Red Card", "- Spikes\n- Ruination\n- Earthquake\n- Whirlwind")
    orb = _attacker("Clefable", "Unaware", "Life Orb", "- Moonblast\n- Moonlight\n- Calm Mind\n- Protect", "Modest")
    states = ec.run_showdown(orb + "\n\n" + BLISSEY, red, [("move moonblast", "move spikes")])
    assert not any("Life Orb" in x for x in states[1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "moonblast", "spikes")
    assert ec.closest(states[1], outs, (2, 1), hp=True)["diff"] == {}


# L67 (doc/engine-diff.md): Sacred Sword / Darkest Lariat ignore the target's Defense boosts
# (Showdown's ignoreDefensive); the engine used them
def test_l67_sacred_sword_ignores_defense_boosts():
    gallade = _attacker("Gallade", "Sharpness", "Leftovers", "- Sacred Sword\n- Psycho Cut\n- Night Slash\n- Swords Dance")
    tusk = _setter("Great Tusk", "Protosynthesis", "Leftovers", "- Close Combat\n- Rapid Spin\n- Ice Spinner\n- Knock Off")
    turns = [("move swordsdance", "move closecombat"), ("move sacredsword", "move rapidspin")]
    states = ec.run_showdown(gallade, tusk, turns, damage_probe=True)
    assert states[1]["sides"][1]["mons"][0]["boosts"]["def"] == -1
    import alpha_search

    rolls = alpha_search.damage_rolls(ec.engine_state(states[1]).to_string(), True, "sacredsword", "rapidspin")
    assert rolls[0][-1] == states[1]["damage"]["p1"]["sacredsword"]


DITTO = """Ditto @ Choice Scarf
Ability: Imposter
Tera Type: Normal
EVs: 248 HP / 8 Def / 252 Spe
Relaxed Nature
- Transform"""
CLEFABLE = _setter("Clefable", "Magic Guard", "Leftovers", "- Moonblast\n- Calm Mind\n- Moonlight\n- Protect")


# L36 (doc/engine-diff.md): Imposter / Transform, the user takes the target's types (not its tera
# type), stats but HP, ability, boosts and moves (5 PP); it ends on a switch (Showdown's
# transformInto); the engine had neither
def test_l36_imposter_transforms_on_switch_in():
    states = ec.run_showdown(BLISSEY + "\n\n" + DITTO, CLEFABLE, [("switch 2", "move calmmind")])
    d = states[1]["sides"][0]["mons"][1]
    assert d["types"] == ["Fairy"] and [m["id"] for m in d["moves"]][:2] == ["moonblast", "calmmind"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "ditto", "calmmind")
    assert ec.closest(states[1], outs, (2, 1))["diff"] == {}
    e = outs[0][1].side_one.pokemon[1]
    assert [str(m.id).lower() for m in e.moves][:4] == ["moonblast", "calmmind", "moonlight", "protect"]
    sd = states[1]["sides"][0]["mons"][1]["stats"]
    assert (e.attack, e.defense, e.special_attack, e.special_defense, e.speed) == (
        sd["atk"], sd["def"], sd["spa"], sd["spd"], sd["spe"])
    assert str(e.ability).lower() == "magicguard"


def test_l36_transformed_moves_then_switch_back():
    turns = [("switch 2", "move calmmind"), ("move moonblast", "move calmmind")]
    states = ec.run_showdown(BLISSEY + "\n\n" + DITTO, CLEFABLE, turns)
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "moonblast", "calmmind")
    assert ec.closest(states[2], outs, (2, 1), hp=True)["diff"] == {}
    # switching out ends it: Ditto's own move and stats again
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "blissey", "calmmind")
    d = outs[0][1].side_one.pokemon[1]
    assert str(d.moves[0].id).lower() == "transform" and str(d.ability).lower() == "imposter"


EXEGGUTOR = _setter("Exeggutor", "Harvest", "Sitrus Berry", "- Leaf Storm\n- Psychic\n- Synthesis\n- Protect")


# L57 (doc/engine-diff.md): Harvest, a used-up berry back at the end of the turn, always in sun,
# else half the time (the engine kept no used-up item: Pokemon::last_item now)
@pytest.mark.parametrize("seed", ["gen5,1,2,3,4", "gen5,9,9,9,9"])
def test_l57_harvest(seed):
    states = ec.run_showdown(EXEGGUTOR, TINGLU_HITS_EQ, [("move synthesis", "move ruination")],
                             seed=seed)  # fmt: skip
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "synthesis", "ruination")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}
    hit = [o for o in outs if o.damage[0] > 0]  # (Ruination missed: the berry never eaten)
    back = sum(o[0] for o in hit if str(o[1].side_one.pokemon[0].item).lower() == "sitrusberry")
    eaten = any("[eat]" in x for x in states[1]["log"])
    if eaten:  # the berry eaten this turn: back with half the chance (no sun)
        assert back / sum(o[0] for o in hit) == pytest.approx(0.5, abs=1e-3)


HATTERENE_HW = _setter("Hatterene", "Magic Bounce", "Leftovers", "- Healing Wish\n- Psyshock\n- Calm Mind\n- Mystical Fire")


# L68 (doc/engine-diff.md): Healing Wish / Lunar Dance fail without a mon to switch in (Showdown's
# canSwitch: the user does not faint)
def test_l68_healing_wish_needs_a_replacement():
    states = ec.run_showdown(HATTERENE_HW, TINGLU, [("move healingwish", "move spikes")])
    assert states[1]["sides"][0]["mons"][0]["hp"] > 0
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "healingwish", "spikes")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L69: a Whirlwind / Roar Magic Bounce reflects drags its user's side; an Encore reflected onto an
# Encore user fails (Encore cannot encore Encore)
def test_l69_magic_bounce_whirlwind():
    lu = _setter("Ting-Lu", "Vessel of Ruin", "Leftovers", "- Whirlwind\n- Ruination\n- Spikes\n- Earthquake")
    states = ec.run_showdown(HATTERENE_HW, lu + "\n\n" + BLISSEY, [("move calmmind", "move whirlwind")])
    assert states[1]["sides"][1]["active"] == 1  # Ting-Lu dragged out
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "calmmind", "whirlwind")
    assert ec.closest(states[1], outs, (1, 2))["diff"] == {}


def test_l69_encore_bounced_onto_an_encore_user_fails():
    encorer = _setter("Clefable", "Magic Guard", "Leftovers", "- Encore\n- Moonblast\n- Moonlight\n- Calm Mind")
    turns = [("move calmmind", "move moonblast"), ("move psyshock", "move encore")]
    states = ec.run_showdown(HATTERENE_HW, encorer, turns)
    assert "encore" not in states[2]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "psyshock", "encore")
    assert ec.closest(states[2], outs, (1, 1))["diff"] == {}


def test_no_name_defined_twice():
    """A fixture or test defined twice silently replaces the first module-wide (it happened:
    HATTERENE, INCINEROAR, KYUREM)."""
    import ast
    import collections

    tree = ast.parse(Path(__file__).read_text())
    names = collections.Counter(
        t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
        if isinstance(t, ast.Name)
    ) + collections.Counter(n.name for n in tree.body if isinstance(n, ast.FunctionDef))
    assert [k for k, v in names.items() if v > 1] == []


GENGAR_CB = _setter("Gengar", "Cursed Body", "Leftovers", "- Shadow Ball\n- Sludge Bomb\n- Disable\n- Will-O-Wisp")


# L70 (doc/engine-diff.md): Disable stops the target's last move for 4 turns (Showdown's duration
# 5, counted down at the end of each turn; the engine only put a volatile on), and Cursed Body
# disables the move that hit its holder 30% of the time (not implemented)
@pytest.mark.parametrize("extra", [0, 1, 3, 4])
def test_l70_disable(extra):
    turns = [("move shadowball", "move earthquake"), ("move disable", "move earthquake")]
    turns += [("move shadowball", "move ruination")] * extra
    states = ec.run_showdown(GENGAR_CB.replace("Cursed Body", "Levitate"), TINGLU_HITS_EQ, turns)
    lu = states[-1]["sides"][1]["mons"][0]
    assert ("disable" in lu["volatiles"]) == (extra < 3)  # 4 turns with the one used (the target to move)
    move, foe = ("shadowball", "ruination") if extra else ("disable", "earthquake")
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), move, foe)
    assert ec.closest(states[-1], outs, (1, 1))["diff"] == {}


def test_l70_cursed_body():
    states = ec.run_showdown(GENGAR_CB, TINGLU_HITS_EQ, [("move willowisp", "move ruination")],
                             force_random=True)  # fmt: skip
    assert "disable" in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "willowisp", "ruination")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}
    hit = [o for o in outs if o.damage[0] > 0]  # (Ruination's 90%)
    disabled = sum(o[0] for o in hit if "DISABLE" in {str(v).upper() for v in o[1].side_two.volatile_statuses})
    assert disabled / sum(o[0] for o in hit) == pytest.approx(0.3, abs=1e-3)


# L71 (doc/engine-diff.md): Beat Up, a hit for the user and each ally neither fainted nor
# statused, each of 5 + its species' base Attack / 10 (Showdown's onModifyMove /
# basePowerCallback); the engine's had no power (the engine has every Gen 9 species' base
# stats now, generated from Showdown's Dex)
def test_l71_beat_up():
    sableye = _attacker("Sableye", "Prankster", "Leftovers", "- Beat Up\n- Recover\n- Will-O-Wisp\n- Knock Off")
    team = sableye + "\n\n" + KINGAMBIT_KNOCK + "\n\n" + CORVIKNIGHT
    states = ec.run_showdown(team, BLISSEY, [("move beatup", "move calmmind")])
    assert any("|-hitcount|p2a: Blissey|3" in x for x in states[1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "beatup", "calmmind")
    assert ec.closest(states[1], outs, (3, 1), hp=True)["diff"] == {}


# L72 (doc/engine-diff.md): Good as Gold blocks only status moves aimed at it: a non-Ghost Curse
# targets its user (Showdown's onModifyMove), the engine's Curse kept its foe target
def test_l72_curse_through_good_as_gold():
    g = _setter("Gholdengo", "Good as Gold", "Leftovers", "- Shadow Ball\n- Make It Rain\n- Recover\n- Nasty Plot")
    states = ec.run_showdown(DONDOZO, g, [("move curse", "move recover")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["atk"] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "curse", "recover")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


STOCKPILER = _setter("Toxapex", "Regenerator", "Black Sludge", "- Stockpile\n- Spit Up\n- Swallow\n- Toxic")


# L73 (doc/engine-diff.md): Stockpile, a layer (at most 3) of Defense / Sp. Def +1 each; Spit Up
# (100 power a layer) and Swallow (25 / 50 / 100% HP) use them up with their boosts; the engine had
# a volatile only (no boosts, no layers: Spit Up / Swallow did nothing)
@pytest.mark.parametrize("pre, move", [
    ([], "stockpile"),
    ([("move stockpile", "move spikes")] * 3, "stockpile"),  # fails at 3
    ([("move stockpile", "move spikes")] * 2, "spitup"),
    ([("move stockpile", "move earthquake")], "swallow"),
])  # fmt: skip
def test_l73_stockpile(pre, move):
    states = ec.run_showdown(STOCKPILER, TINGLU_HITS_EQ, pre + [(f"move {move}", "move spikes")])
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), move, "spikes")
    assert ec.closest(states[-1], outs, (1, 1), hp=True)["diff"] == {}


# L74 (doc/engine-diff.md): Electromorphosis, a damaging hit charges its holder (Showdown's
# onDamagingHit); not implemented in the engine
def test_l74_electromorphosis():
    belli = _setter("Bellibolt", "Electromorphosis", "Leftovers", "- Slack Off\n- Discharge\n- Muddy Water\n- Toxic")
    states = ec.run_showdown(belli, TINGLU_HITS_EQ, [("move slackoff", "move ruination")])
    assert "charge" in states[1]["sides"][0]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "slackoff", "ruination")
    assert ec.closest(states[1], outs, (1, 1))["diff"] == {}


# L75 (doc/engine-diff.md): Sitrus and the pinch berries are eaten as soon as a hit takes their
# holder there (Showdown's onUpdate); the engine waited for the holder's move (Sitrus at 1/4 then)
# or the end of the turn, so a heal in between kept the berry
def test_l75_sitrus_at_once():
    pex = _setter("Toxapex", "Regenerator", "Sitrus Berry", "- Recover\n- Toxic\n- Haze\n- Scald")
    states = ec.run_showdown(pex, TINGLU_HITS_EQ, [("move recover", "move ruination")])
    assert states[1]["sides"][0]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "recover", "ruination")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L76 (doc/engine-diff.md): Sticky Web's drop comes from the foe (Showdown's boost source: the
# foe's active): Clear Body stops it, Defiant answers it; the engine applied it as self-inflicted
@pytest.mark.parametrize("ability, spe, atk", [("Clear Body", 0, 0), ("Light Metal", -1, 0)])
def test_l76_sticky_web_from_the_foe(ability, spe, atk):
    webber = _setter("Ribombee", "Shield Dust", "Focus Sash", "- Sticky Web\n- Moonblast\n- U-turn\n- Stun Spore")
    gross = _setter("Metagross", ability, "Leftovers", "- Meteor Mash\n- Earthquake\n- Bullet Punch\n- Agility")
    turns = [("move stickyweb", "move softboiled"), ("move moonblast", "switch 2")]
    states = ec.run_showdown(webber, BLISSEY + "\n\n" + gross, turns)
    assert states[2]["sides"][1]["mons"][1]["boosts"]["spe"] == spe
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "moonblast", "metagross")
    assert ec.closest(states[2], outs, (1, 2))["diff"] == {}


def test_l75_knock_off_takes_the_berry_before_it_is_eaten():
    """Knock Off removes the Sitrus its hit would set off (its onAfterHit comes first)."""
    pex = _setter("Toxapex", "Regenerator", "Sitrus Berry", "- Recover\n- Toxic\n- Haze\n- Scald")
    knock = _attacker("Kingambit", "Supreme Overlord", "Life Orb", "- Knock Off\n- Iron Head\n- Sucker Punch\n- Swords Dance")
    states = ec.run_showdown(pex, knock, [("move haze", "move knockoff")])
    assert not any("[eat]" in x for x in states[1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "haze", "knockoff")
    # (not the crit: its damage + the Sitrus lands on Showdown's HP too)
    res = ec.closest(states[1], outs, (1, 1), hp=True)
    assert res["diff"] == {} and res["p"] > 0.9


# L77 (doc/engine-diff.md): Slow Start halves its holder's Attack / Speed for 5 turns after the one
# it came in on (Showdown: a counter in the ability's state, not a volatile); the harness did not
# carry it into the engine's state, so a Regigigas already in hit at full power
def test_l77_slow_start_counts_its_turns():
    gigas = _attacker("Regigigas", "Slow Start", "Leftovers", "- Earthquake\n- Protect\n- Substitute\n- Thunder Wave")
    states = ec.run_showdown(gigas, BLISSEY, [("move earthquake", "move softboiled")] * 6)
    assert any("|-end|p1a: Regigigas|Slow Start" in x for x in states[5]["log"])
    for k in range(6):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), "earthquake", "softboiled")
        res = ec.closest(states[k + 1], outs, (1, 1), hp=True)
        crit = any(x.startswith("|-crit") for x in states[k + 1]["log"])
        assert res["diff"] == {} and (crit or res["p"] > 0.9), (k, res)


def test_l77_slow_start_from_the_protocol():
    """Our state construction's count (agents/timers.py, from the log) against Showdown's counter,
    for a lead and for one that comes in mid-battle."""
    from alpha_poke.agents.timers import timers

    gigas = _attacker("Regigigas", "Slow Start", "Leftovers", "- Earthquake\n- Protect\n- Substitute\n- Thunder Wave")
    other = gigas.replace("Regigigas @", "Gigas (Regigigas) @")
    turns = [("move earthquake", "move softboiled"), ("move earthquake", "move protect"),
             ("switch 2", "move softboiled")]  # fmt: skip
    turns += [("move earthquake", f"move {m}") for m in ["protect", "softboiled"] * 3]
    states = ec.run_showdown(gigas + "\n\n" + other, BLISSEY, turns)
    lines: list = []
    for st in states:
        lines += [x.split("|") for x in st["log"]]
        p1 = st["sides"][0]
        sd = p1["mons"][p1["active"]]["volatiles"].get("slowstart", {}).get("duration", 0)
        ours = timers(lines)["p1"].slowstart
        assert (ours[0] if ours else 0) == sd, (st["turn"], ours, sd)


# L78 (doc/engine-diff.md): Pickpocket takes the attacker's item when a contact move hits its
# holder and the holder has none (Showdown's onAfterMoveSecondary: after Knock Off took its own);
# the engine had it as Magician's, its holder taking the target's item when it hit
WEAVILE_PICKPOCKET = """Weavile @ Heavy-Duty Boots
Ability: Pickpocket
Tera Type: Dark
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Swords Dance
- Ice Shard
- Triple Axel
- Low Kick"""


def test_l78_pickpocket_after_knock_off():
    knock = _attacker("Kingambit", "Supreme Overlord", "Leftovers", "- Knock Off\n- Iron Head\n- Sucker Punch\n- Swords Dance")
    states = ec.run_showdown(WEAVILE_PICKPOCKET, knock, [("move swordsdance", "move knockoff")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "leftovers"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "swordsdance", "knockoff")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l78_pickpocket_holder_takes_nothing_when_it_hits():
    weavile = WEAVILE_PICKPOCKET.replace(" @ Heavy-Duty Boots", "")
    states = ec.run_showdown(weavile, BLISSEY, [("move iceshard", "move softboiled")])
    assert states[1]["sides"][0]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "iceshard", "softboiled")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L79 (doc/engine-diff.md): a Paradox Pokemon's Booster Energy cannot be taken (Showdown's
# onTakeItem), so Knock Off neither removes it nor gets its 1.5x; the engine did both
def test_l79_booster_energy_stays_on_a_paradox():
    tusk = _setter("Great Tusk", "Protosynthesis", "Booster Energy", "- Rapid Spin\n- Headlong Rush\n- Ice Spinner\n- Bulk Up")
    # (a faster Drought first: the sun activates Protosynthesis, the Booster Energy stays)
    knock = """Ninetales @ Leftovers
Ability: Drought
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Knock Off
- Flare Blitz
- Protect
- Will-O-Wisp"""
    states = ec.run_showdown(tusk, knock, [("move bulkup", "move knockoff")])
    assert states[0]["sides"][0]["mons"][0]["item"] == "boosterenergy"
    assert states[1]["sides"][0]["mons"][0]["item"] == "boosterenergy"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "bulkup", "knockoff")
    res = ec.closest(states[1], outs, (1, 1), hp=True)
    crit = any(x.startswith("|-crit") for x in states[1]["log"])
    assert res["diff"] == {} and (crit or res["p"] > 0.9)


# L80 (doc/engine-diff.md): Neutralizing Gas suppresses the target's status-blocking ability
# (Purifying Salt, Water Veil, Limber, ...; not Comatose / Shields Down, which it cannot), and the
# target's Gas the user's Corrosion; the engine's status immunity read the abilities as they are
def test_l80_neutralizing_gas_lets_a_burn_through_purifying_salt():
    weezing = _setter("Weezing-Galar", "Neutralizing Gas", "Heavy-Duty Boots", "- Will-O-Wisp\n- Pain Split\n- Strange Steam\n- Defog")
    salt = _setter("Garganacl", "Purifying Salt", "Leftovers", "- Recover\n- Salt Cure\n- Stealth Rock\n- Protect")
    states = ec.run_showdown(weezing, salt, [("move willowisp", "move recover")])
    assert states[1]["sides"][1]["mons"][0]["status"] == "brn"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "willowisp", "recover")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l80_neutralizing_gas_stops_synchronize():
    weezing = _setter("Weezing-Galar", "Neutralizing Gas", "Heavy-Duty Boots", "- Will-O-Wisp\n- Pain Split\n- Strange Steam\n- Defog")
    garde = _setter("Gardevoir", "Synchronize", "Leftovers", "- Calm Mind\n- Moonblast\n- Psychic\n- Protect")
    states = ec.run_showdown(weezing, garde, [("move willowisp", "move calmmind")])
    assert states[1]["sides"][1]["mons"][0]["status"] == "brn"
    assert states[1]["sides"][0]["mons"][0]["status"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "willowisp", "calmmind")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L81 (doc/engine-diff.md): Rest's sleep sets off a Lum / Chesto Berry at once (Showdown's
# onUpdate), so a status later in the turn lands; the engine ate it before the holder's next move
# or at the end of the turn, the Rest user still asleep (immune) in between
@pytest.mark.parametrize("berry", ["Lum Berry", "Chesto Berry"])
def test_l81_rest_berry_at_once(berry):
    clef = _setter("Clefable", "Unaware", berry, "- Rest\n- Moonblast\n- Calm Mind\n- Protect")
    tork = _setter("Torkoal", "White Smoke", "Leftovers", "- Will-O-Wisp\n- Flamethrower\n- Rapid Spin\n- Yawn")
    states = ec.run_showdown(clef, tork, [("move moonblast", "move flamethrower"), ("move rest", "move willowisp")])
    assert states[2]["sides"][0]["mons"][0]["status"] == "brn"
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "rest", "willowisp")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L82 (doc/engine-diff.md): Magic Guard stops a partial trap's, Salt Cure's and a Ghost's Curse's
# end-of-turn damage (Showdown: their this.damage, Magic Guard's onDamage); the engine took it
@pytest.mark.parametrize("foe, move", [
    (_setter("Toxapex", "Regenerator", "Black Sludge", "- Infestation\n- Recover\n- Haze\n- Toxic"), "infestation"),
    (_setter("Garganacl", "Purifying Salt", "Leftovers", "- Salt Cure\n- Recover\n- Protect\n- Stealth Rock"), "saltcure"),
    (_setter("Gengar", "Cursed Body", "Black Sludge", "- Curse\n- Shadow Ball\n- Protect\n- Toxic"), "curse"),
], ids=["infestation", "saltcure", "curse"])  # fmt: skip
def test_l82_magic_guard_stops_residual_damage(foe, move):
    clef = _setter("Clefable", "Magic Guard", "Leftovers", "- Calm Mind\n- Moonblast\n- Protect\n- Soft-Boiled")
    states = ec.run_showdown(clef, foe, [("move calmmind", f"move {move}")] * 2)
    for k in (0, 1):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), "calmmind", move)
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k


# L83 (doc/engine-diff.md): Magic Guard stops Sticky Barb's and (on a non-Poison holder) Black
# Sludge's end-of-turn damage; the engine took it
@pytest.mark.parametrize("item", ["Sticky Barb", "Black Sludge"])
def test_l83_magic_guard_stops_item_damage(item):
    clef = _setter("Clefable", "Magic Guard", item, "- Calm Mind\n- Moonblast\n- Protect\n- Soft-Boiled")
    states = ec.run_showdown(clef, BLISSEY, [("move calmmind", "move softboiled")])
    assert states[1]["sides"][0]["mons"][0]["hp"] == states[0]["sides"][0]["mons"][0]["hp"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "calmmind", "softboiled")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L84 (doc/engine-diff.md): Grassy Terrain heals after the weather's damage (Showdown's residual
# order: weather 1, Future Sight 3, Wish 4, Grassy Terrain 5.2, the terrain's end 27); the engine
# healed first (nothing at full HP) and ended the terrain before
def test_l84_grassy_terrain_heals_after_sand():
    ttar = _setter("Tyranitar", "Sand Stream", "Leftovers", "- Stealth Rock\n- Knock Off\n- Protect\n- Thunder Wave")
    rilla = _setter("Rillaboom", "Grassy Surge", "Heavy-Duty Boots", "- Swords Dance\n- Wood Hammer\n- U-turn\n- Protect")
    states = ec.run_showdown(ttar, rilla, [("move stealthrock", "move swordsdance")])
    assert states[1]["sides"][1]["mons"][0]["hp"] == states[1]["sides"][1]["mons"][0]["maxhp"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "stealthrock", "swordsdance")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l84_grassy_terrain_heals_on_its_last_turn():
    rilla = _setter("Rillaboom", "Grassy Surge", "Heavy-Duty Boots", "- Swords Dance\n- Wood Hammer\n- U-turn\n- Protect")
    tusk = _setter("Great Tusk", "Protosynthesis", "Leftovers", "- Rapid Spin\n- Headlong Rush\n- Bulk Up\n- Ice Spinner")
    turns = [("move woodhammer", "move bulkup")] + [("move swordsdance", "move bulkup")] * 4
    states = ec.run_showdown(rilla, tusk, turns)
    assert any("|-fieldend|move: Grassy Terrain" in x for x in states[5]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[4]), "swordsdance", "bulkup")
    assert ec.closest(states[5], outs, (1, 1), hp=True)["diff"] == {}


# L85 (doc/engine-diff.md): Salt Cure's and Psychic Noise's volatiles are secondaries (100%) in
# Showdown, so Covert Cloak / Shield Dust stop them; the engine applied them as the move's own
@pytest.mark.parametrize("user, move, volatile", [
    (_setter("Garganacl", "Purifying Salt", "Leftovers", "- Salt Cure\n- Recover\n- Protect\n- Stealth Rock"), "saltcure", "saltcure"),
    (_attacker("Hatterene", "Magic Bounce", "Leftovers", "- Psychic Noise\n- Calm Mind\n- Draining Kiss\n- Protect", "Modest"), "psychicnoise", "healblock"),
], ids=["saltcure", "psychicnoise"])  # fmt: skip
def test_l85_covert_cloak_stops_the_volatile(user, move, volatile):
    mana = _setter("Manaphy", "Hydration", "Covert Cloak", "- Tail Glow\n- Surf\n- Rest\n- Energy Ball")
    states = ec.run_showdown(user, mana, [(f"move {move}", "move tailglow")])
    assert volatile not in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "tailglow")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L86 (doc/engine-diff.md): Smack Down's volatile only on an airborne target (Showdown's onStart:
# a Flying type, Levitate, Magnet Rise; not with an Iron Ball or Ingrain); the engine put it on
# every target
@pytest.mark.parametrize("target, grounded", [
    (_setter("Ting-Lu", "Vessel of Ruin", "Leftovers", "- Stealth Rock\n- Ruination\n- Whirlwind\n- Spikes"), True),
    (_setter("Corviknight", "Pressure", "Leftovers", "- Roost\n- Brave Bird\n- Defog\n- U-turn"), False),
], ids=["grounded", "flying"])  # fmt: skip
def test_l86_smack_down_only_grounds_the_airborne(target, grounded):
    lando = _attacker("Landorus-Therian", "Intimidate", "Leftovers", "- Smack Down\n- Earthquake\n- U-turn\n- Stealth Rock")
    second = target.splitlines()[5][2:].lower().replace(" ", "")
    states = ec.run_showdown(lando, target, [("move smackdown", f"move {second}")])
    assert ("smackdown" in states[1]["sides"][1]["mons"][0]["volatiles"]) != grounded
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "smackdown", second)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L87 (doc/engine-diff.md): the harness carries Perish Song's count (Showdown's perishsong volatile,
# its turns left) into the engine's perish<n>; without it the engine's state had none, and a
# second Perish Song worked again
def test_l87_perish_song_counts_down():
    alt = _setter("Altaria", "Natural Cure", "Leftovers", "- Perish Song\n- Roost\n- Protect\n- Defog")
    states = ec.run_showdown(alt, BLISSEY, [("move perishsong", "move softboiled"), ("move perishsong", "move protect"),
                                            ("move roost", "move softboiled")])  # fmt: skip
    for k, c1, c2 in ((0, "perishsong", "softboiled"), (1, "perishsong", "protect"), (2, "roost", "softboiled")):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, c2)
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k


# L88 (doc/engine-diff.md): a crit drops only the boosts that hurt the attacker, of the stat the
# move uses (Showdown's getDamage); the engine's crit took Body Press's user's Defense and Foul
# Play's target's Attack unboosted (a crit below the normal hit at +2)
def test_l88_body_press_crit_keeps_the_defense_boost():
    corv = _attacker("Corviknight", "Pressure", "Scope Lens", "- Iron Defense\n- Focus Energy\n- Body Press\n- Roost")
    pex = _setter("Toxapex", "Regenerator", "Leftovers", "- Recover\n- Toxic\n- Haze\n- Scald")
    turns = [("move irondefense", "move recover"), ("move focusenergy", "move recover"),
             ("move bodypress", "move toxic")]  # fmt: skip
    states = ec.run_showdown(corv, pex, turns)
    assert any(x.startswith("|-crit") for x in states[3]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "bodypress", "toxic")
    res = ec.closest(states[3], outs, (1, 1), hp=True)
    assert res["diff"] == {} and res["p"] > 0.9


def test_l88_foul_play_crit_keeps_the_targets_attack_boost():
    grim = _attacker("Grimmsnarl", "Prankster", "Scope Lens", "- Focus Energy\n- Foul Play\n- Reflect\n- Thunder Wave")
    sd = _attacker("Kingambit", "Supreme Overlord", "Leftovers", "- Swords Dance\n- Iron Head\n- Sucker Punch\n- Protect")
    turns = [("move focusenergy", "move swordsdance"), ("move foulplay", "move swordsdance")]
    states = ec.run_showdown(grim, sd, turns)
    assert any(x.startswith("|-crit") for x in states[2]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "foulplay", "swordsdance")
    res = ec.closest(states[2], outs, (1, 1), hp=True)
    assert res["diff"] == {} and res["p"] > 0.9


# L89 (doc/engine-diff.md): Encore lasts 3 turns (4 if the target had moved that turn), counted at
# the ends of turn (Showdown's duration); the engine counted the target's moves and ended it at
# the start of the third, so a second Encore in that turn worked where Showdown's failed
@pytest.mark.parametrize("encorer", [
    _setter("Whimsicott", "Prankster", "Leftovers", "- Encore\n- Moonblast\n- Protect\n- U-turn"),
    _setter("Clefable", "Unaware", "Leftovers", "- Encore\n- Moonblast\n- Protect\n- Soft-Boiled"),
], ids=["before-it-moved", "after-it-moved"])  # fmt: skip
def test_l89_encore_counts_turns(encorer):
    val = _attacker("Iron Valiant", "Quark Drive", "Leftovers", "- Calm Mind\n- Moonblast\n- Close Combat\n- Knock Off", "Timid")
    states = ec.run_showdown(val, encorer, [("move calmmind", "move encore")] * 6)
    assert any("|-end|p1a: Iron Valiant|Encore" in x for x in sum((s["log"] for s in states), []))
    for k in range(6):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), "calmmind", "encore")
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k
    # our state construction's count (agents/timers.py, from the log): 3 - Showdown's turns left
    from alpha_poke.agents.timers import timers

    lines: list = []
    for st in states:
        lines += [x.split("|") for x in st["log"]]
        sd = st["sides"][0]["mons"][0]["volatiles"].get("encore")
        ours = timers(lines)["p1"].encore
        assert ours == (3 - sd["duration"] if sd else None), (st["turn"], ours, sd)


# L90 (doc/engine-diff.md): Taunt, as Encore (L89): 3 turns (4 if the target had moved that
# turn), counted at the ends of turn; the engine counted the target's moves and ended it at the
# start of the third
@pytest.mark.parametrize("taunter", [
    _setter("Whimsicott", "Prankster", "Leftovers", "- Taunt\n- Moonblast\n- Protect\n- U-turn"),
    _setter("Slowbro", "Oblivious", "Leftovers", "- Taunt\n- Scald\n- Slack Off\n- Teleport"),
], ids=["before-it-moved", "after-it-moved"])  # fmt: skip
def test_l90_taunt_counts_turns(taunter):
    from alpha_poke.agents.timers import timers

    pex = _setter("Toxapex", "Regenerator", "Black Sludge", "- Scald\n- Recover\n- Haze\n- Toxic")
    states = ec.run_showdown(pex, taunter, [("move scald", "move taunt")] * 6)
    assert any("|-end|p1a: Toxapex|move: Taunt" in x for x in sum((s["log"] for s in states), []))
    lines: list = []
    for k in range(6):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), "scald", "taunt")
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k
    for st in states:  # our state construction's count: 3 - Showdown's turns left
        lines += [x.split("|") for x in st["log"]]
        sd = st["sides"][0]["mons"][0]["volatiles"].get("taunt")
        ours = timers(lines)["p1"].taunt
        assert ours == (3 - sd["duration"] if sd else None), (st["turn"], ours, sd)


def test_l90_taunted_attack_into_an_absorbing_ability():
    """A taunted attack into Water Absorb still goes (the engine's absorbed move is a status move:
    Taunt's check reads the move's own category)."""
    lan = _setter("Lanturn", "Water Absorb", "Life Orb", "- Thunderbolt\n- Scald\n- Volt Switch\n- Heal Bell")
    taunter = _setter("Grimmsnarl", "Prankster", "Leftovers", "- Taunt\n- Spirit Break\n- Reflect\n- Parting Shot")
    pex = _setter("Toxapex", "Regenerator", "Black Sludge", "- Scald\n- Recover\n- Haze\n- Toxic")
    turns = [("move thunderbolt", "move recover"), ("switch 2", "move recover"), ("move taunt", "move recover"),
             ("switch 2", "move scald")]  # fmt: skip
    states = ec.run_showdown(lan + "\n\n" + taunter, pex, turns)
    assert "taunt" in states[3]["sides"][1]["mons"][0]["volatiles"]
    assert any("Water Absorb" in x for x in states[4]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[3]), "lanturn", "scald")
    assert ec.closest(states[4], outs, (2, 1), hp=True)["diff"] == {}


# L91 (doc/engine-diff.md): Defog (Showdown's onHit) clears the screens, Safeguard and Mist of the
# target's side only (hazards of both); Good as Gold stops it unless a Mold Breaker / Neutralizing
# Gas user; Mirror Armor sends its evasion drop back. The engine cleared the user's screens too,
# let Good as Gold stop a Mold Breaker's Defog and Mirror Armor not see it
CORV_DEFOG = _setter("Corviknight", "Pressure", "Leftovers", "- Reflect\n- Defog\n- Roost\n- U-turn")


def test_l91_defog_keeps_the_users_screens():
    states = ec.run_showdown(CORV_DEFOG, BLISSEY, [("move reflect", "move softboiled"), ("move defog", "move softboiled")])
    assert "reflect" in states[2]["sides"][0]["conditions"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "defog", "softboiled")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


@pytest.mark.parametrize("user, target, drop", [
    (_setter("Hawlucha", "Mold Breaker", "Leftovers", "- Defog\n- Close Combat\n- Swords Dance\n- Roost"),
     _setter("Gholdengo", "Good as Gold", "Leftovers", "- Nasty Plot\n- Shadow Ball\n- Recover\n- Trick"), (0, -1)),
    (_setter("Hawlucha", "Limber", "Leftovers", "- Defog\n- Close Combat\n- Swords Dance\n- Roost"),
     _setter("Corviknight", "Mirror Armor", "Leftovers", "- Roost\n- Brave Bird\n- Defog\n- U-turn"), (-1, 0)),
], ids=["mold-breaker-through-good-as-gold", "mirror-armor"])  # fmt: skip
def test_l91_defog_evasion_drop(user, target, drop):
    second = target.splitlines()[5][2:].lower().replace(" ", "")
    states = ec.run_showdown(user, target, [("move defog", f"move {second}")])
    assert (states[1]["sides"][0]["mons"][0]["boosts"]["evasion"],
            states[1]["sides"][1]["mons"][0]["boosts"]["evasion"]) == drop  # fmt: skip
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "defog", second)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l91_neutralizing_gas_defog_through_mirror_armor():
    weezing = _setter("Weezing-Galar", "Neutralizing Gas", "Leftovers", "- Defog\n- Pain Split\n- Strange Steam\n- Will-O-Wisp")
    corv = _setter("Corviknight", "Mirror Armor", "Leftovers", "- Roost\n- Brave Bird\n- Defog\n- U-turn")
    states = ec.run_showdown(corv, weezing, [("move roost", "move defog")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["evasion"] == -1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "roost", "defog")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L92 (doc/engine-diff.md): a hit on a Substitute whose rolls straddle its HP splits by the exact
# rolls into a break and the rest, like a knockout (L34 / L51); the engine dealt the average roll
def test_l92_substitute_break_by_the_rolls():
    tran = _attacker("Heatran", "Flash Fire", "Choice Specs", "- Earth Power\n- Protect\n- Rest\n- Roar", "Modest")
    whim = _setter("Whimsicott", "Prankster", "Leftovers", "- Substitute\n- Moonblast\n- Protect\n- Encore")
    states = ec.run_showdown(tran, whim, [("move earthpower", "move substitute")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "earthpower", "substitute")
    broken = sum(p for p, o in outs if not ec.view_engine(o, (1, 1)).get("s2.volatile.substitute"))
    # the rolls 70-82 against its 81 HP: 2 of 16 break it, a crit (1/24) always
    assert broken == pytest.approx(23 / 24 * 2 / 16 + 1 / 24, abs=1e-3)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L93 (doc/engine-diff.md): Strength Sap fails against a Substitute (Showdown: no bypasssub); the
# engine healed by the target's Attack anyway
def test_l93_strength_sap_against_a_substitute():
    whim = _setter("Whimsicott", "Prankster", "Leftovers", "- Substitute\n- Air Slash\n- Protect\n- Encore")
    plume = _setter("Vileplume", "Effect Spore", "Black Sludge", "- Strength Sap\n- Giga Drain\n- Sleep Powder\n- Sludge Bomb")
    states = ec.run_showdown(plume, whim, [("move sleeppowder", "move airslash"), ("move strengthsap", "move substitute")])
    assert states[1]["sides"][0]["mons"][0]["hp"] < states[1]["sides"][0]["mons"][0]["maxhp"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "strengthsap", "substitute")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L94 (doc/engine-diff.md): Magic Guard stops Rough Skin's / Iron Barbs' and Rocky Helmet's damage;
# an absorbing ability (Earth Eater, Water / Volt Absorb, Dry Skin) does not take a move aimed at
# its side (Spikes: Showdown's onTryHit is for the moves that hit it). The engine took both
def test_l94_magic_guard_against_rough_skin_and_rocky_helmet():
    clef = _setter("Clefable", "Magic Guard", "Leftovers", "- Draining Kiss\n- Moonblast\n- Calm Mind\n- Soft-Boiled")
    chomp = _setter("Garchomp", "Rough Skin", "Rocky Helmet", "- Stealth Rock\n- Earthquake\n- Dragon Tail\n- Spikes")
    states = ec.run_showdown(clef, chomp, [("move drainingkiss", "move stealthrock")])
    assert states[1]["sides"][0]["mons"][0]["hp"] == states[1]["sides"][0]["mons"][0]["maxhp"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "drainingkiss", "stealthrock")
    assert ec.closest(states[1], outs, (1, 1), hp=True, dealt=(True, False))["diff"] == {}


def test_l94_spikes_into_earth_eater():
    glis = _setter("Gliscor", "Poison Heal", "Toxic Orb", "- Spikes\n- Earthquake\n- Protect\n- Toxic")
    worm = _setter("Orthworm", "Earth Eater", "Leftovers", "- Shed Tail\n- Iron Head\n- Body Press\n- Stealth Rock")
    states = ec.run_showdown(glis, worm, [("move spikes", "move stealthrock")])
    assert states[1]["sides"][1]["conditions"].get("spikes")
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "spikes", "stealthrock")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L95 (doc/engine-diff.md): Rapid Spin / Mortal Spin also free their user from Leech Seed and a
# partial trap, through a Substitute too (Showdown's onAfterHit / onAfterSubDamage); the engine
# cleared only the hazards
@pytest.mark.parametrize("foe_move, sub", [("leechseed", False), ("infestation", False), ("leechseed", True)],
                         ids=["leech-seed", "partial-trap", "through-a-substitute"])  # fmt: skip
def test_l95_rapid_spin_frees_its_user(foe_move, sub):
    tusk = _setter("Great Tusk", "Protosynthesis", "Leftovers", "- Rapid Spin\n- Headlong Rush\n- Bulk Up\n- Ice Spinner")
    foe = _setter("Ferrothorn", "Iron Barbs", "Leftovers", "- Leech Seed\n- Infestation\n- Substitute\n- Iron Defense")
    turns = [("move bulkup", f"move {foe_move}")] + ([("move bulkup", "move substitute")] if sub else [])
    turns.append(("move rapidspin", "move irondefense"))
    states = ec.run_showdown(tusk, foe, turns)
    k = len(turns) - 1
    assert {"leechseed", "partiallytrapped"} & set(states[k]["sides"][0]["mons"][0]["volatiles"])
    assert not {"leechseed", "partiallytrapped"} & set(states[k + 1]["sides"][0]["mons"][0]["volatiles"])
    outs = ec.engine_outcomes(ec.engine_state(states[k]), "rapidspin", "irondefense")
    assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}


# L96 (doc/engine-diff.md): a grounded Poison type absorbs Toxic Spikes when it comes in, Heavy-Duty
# Boots or not (Showdown's onSwitchIn checks the Poison type before the boots); the engine skipped
# a boots holder
def test_l96_poison_type_with_boots_absorbs_toxic_spikes():
    glim = _setter("Glimmora", "Toxic Debris", "Focus Sash", "- Toxic Spikes\n- Power Gem\n- Mortal Spin\n- Earth Power")
    pech = _setter("Pecharunt", "Poison Puppeteer", "Heavy-Duty Boots", "- Malignant Chain\n- Recover\n- Parting Shot\n- Nasty Plot")
    states = ec.run_showdown(glim, BLISSEY + "\n\n" + pech, [("move toxicspikes", "move softboiled"), ("move powergem", "switch 2")])
    assert states[1]["sides"][1]["conditions"].get("toxicspikes")
    assert not states[2]["sides"][1]["conditions"].get("toxicspikes")
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "powergem", "pecharunt")
    assert ec.closest(states[2], outs, (1, 2), hp=True)["diff"] == {}


# L97 (doc/engine-diff.md): Leech Seed is not a powder move (Overcoat / Safety Goggles do not stop
# it); the engine flagged it powder for the Grass immunity, which its volatile check has anyway
@pytest.mark.parametrize("ability, item", [("Overcoat", "Leftovers"), ("Pressure", "Safety Goggles")])
def test_l97_leech_seed_through_overcoat(ability, item):
    ferro = _setter("Ferrothorn", "Iron Barbs", "Leftovers", "- Leech Seed\n- Spikes\n- Protect\n- Power Whip")
    buzz = _setter("Mandibuzz", ability, item, "- Roost\n- Foul Play\n- Defog\n- U-turn")
    states = ec.run_showdown(ferro, buzz, [("move leechseed", "move defog")])
    assert "leechseed" in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "leechseed", "defog")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L98 (doc/engine-diff.md): Disguise breaks only on a hit that damages Mimikyu (Showdown's
# onDamage): not on a move it is immune to, nor on its Substitute; the engine broke it (and took
# the 1/8) on any attack
@pytest.mark.parametrize("move, sub", [("extremespeed", False), ("shadowsneak", True)], ids=["immune", "substitute"])
def test_l98_disguise_needs_a_damaging_hit(move, sub):
    mimi = _setter("Mimikyu", "Disguise", "Leftovers", "- Substitute\n- Swords Dance\n- Shadow Claw\n- Play Rough")
    nite = _attacker("Dragonite", "Inner Focus", "Leftovers", "- Extreme Speed\n- Shadow Sneak\n- Roost\n- Dragon Dance")
    turns = ([("move substitute", "move roost")] if sub else []) + [("move swordsdance", f"move {move}")]
    states = ec.run_showdown(mimi, nite, turns)
    assert states[-1]["sides"][0]["mons"][0]["species"].lower() == "mimikyu"
    outs = ec.engine_outcomes(ec.engine_state(states[-2]), "swordsdance", move)
    assert ec.closest(states[-1], outs, (1, 1), hp=True)["diff"] == {}


# L99 (doc/engine-diff.md): Soak makes its target pure Water (Showdown's setType; not a pure Water
# type, a Terastallized one or through a Substitute); it had no effect in the engine
def test_l99_soak():
    belli = _setter("Bellibolt", "Electromorphosis", "Leftovers", "- Soak\n- Slack Off\n- Discharge\n- Muddy Water")
    bolt = _attacker("Raging Bolt", "Protosynthesis", "Leftovers", "- Thunderbolt\n- Calm Mind\n- Draco Meteor\n- Protect", "Modest")
    states = ec.run_showdown(belli, bolt, [("move soak", "move calmmind"), ("move discharge", "move calmmind")])
    assert states[1]["sides"][1]["mons"][0]["types"] == ["Water"]
    for k, c1 in ((0, "soak"), (1, "discharge")):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, "calmmind")
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k


# L100 (doc/engine-diff.md): Dry Skin loses 1/8 in sun (Showdown's onWeather), heals 1/8 in rain
# and heavy rain; the engine only healed in rain
def test_l100_dry_skin_in_the_sun():
    tork = _setter("Torkoal", "Drought", "Leftovers", "- Stealth Rock\n- Lava Plume\n- Rapid Spin\n- Yawn")
    croak = _setter("Toxicroak", "Dry Skin", "Leftovers", "- Bulk Up\n- Drain Punch\n- Gunk Shot\n- Sucker Punch")
    states = ec.run_showdown(tork, croak, [("move stealthrock", "move bulkup")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "stealthrock", "bulkup")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l99_soak_into_water_absorb():
    belli = _setter("Bellibolt", "Electromorphosis", "Leftovers", "- Soak\n- Slack Off\n- Discharge\n- Muddy Water")
    lan = _setter("Lanturn", "Water Absorb", "Leftovers", "- Thunderbolt\n- Scald\n- Volt Switch\n- Heal Bell")
    states = ec.run_showdown(belli, lan, [("move soak", "move healbell")])
    assert "typechange" not in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "soak", "healbell")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L101 (doc/engine-diff.md): a Pokemon that cannot move (asleep, frozen, fully paralyzed, hitting
# itself in confusion) has not used its move (Showdown sets lastMove only when the move is used):
# an Encore after it in the turn fails when it had not moved since it came in; the engine had set
# its last used move to the chosen one before the check
def test_l101_asleep_has_not_used_its_move():
    lax = _setter("Snorlax", "Thick Fat", "Leftovers", "- Spore\n- Encore\n- Body Slam\n- Rest")
    chansey = BLISSEY.replace("Blissey @ Heavy-Duty Boots", "Chansey @ Eviolite")
    states = ec.run_showdown(lax, chansey + "\n\n" + BLISSEY, [("move spore", "switch 2"), ("move encore", "move softboiled")])
    assert any(x.startswith("|cant|p2a: Blissey|slp") for x in states[2]["log"])
    assert "encore" not in states[2]["sides"][1]["mons"][1]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "encore", "softboiled")
    assert ec.closest(states[2], outs, (1, 2), hp=True)["diff"] == {}


def test_l101_encore_fails_on_sleep_talk():
    """Encore fails on a move it cannot repeat (Showdown's failencore: Sleep Talk, Encore, Copycat,
    Metronome, Mimic, Sketch, Struggle, Transform) or one at 0 PP."""
    lax = _setter("Snorlax", "Thick Fat", "Leftovers", "- Spore\n- Encore\n- Body Slam\n- Rest")
    zo = _setter("Dondozo", "Unaware", "Leftovers", "- Sleep Talk\n- Curse\n- Rest\n- Waterfall")
    turns = [("move spore", "move curse"), ("move bodyslam", "move sleeptalk"), ("move encore", "move sleeptalk")]
    states = ec.run_showdown(lax, zo, turns)
    assert states[2]["sides"][1]["mons"][0]["last_move"] == "sleeptalk"
    assert "encore" not in states[3]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "encore", "sleeptalk")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


# L102 (doc/engine-diff.md): Unnerve / As One stop the foe eating berries (Showdown's
# onFoeTryEatItem); the engine had no Unnerve
@pytest.mark.parametrize("berry, move", [("Sitrus Berry", "ruination"), ("Lum Berry", "willowisp")])
def test_l102_unnerve_stops_berries(berry, move):
    pex = _setter("Toxapex", "Regenerator", berry, "- Recover\n- Toxic\n- Haze\n- Scald")
    lu = _setter("Ting-Lu", "Unnerve", "Leftovers", "- Ruination\n- Will-O-Wisp\n- Stealth Rock\n- Whirlwind")
    states = ec.run_showdown(pex, lu, [("move haze", f"move {move}")])
    assert states[1]["sides"][0]["mons"][0]["item"] == berry.lower().replace(" ", "")
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "haze", move)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L103 (doc/engine-diff.md): Throat Spray only after a sound move that went through (Showdown's
# onAfterMoveSecondarySelf): not a Clangorous Soul that fails at a third of the HP or below
def test_l103_throat_spray_not_on_a_failed_clangorous_soul():
    kommo = _setter("Kommo-o", "Soundproof", "Throat Spray", "- Clangorous Soul\n- Belly Drum\n- Substitute\n- Protect")
    lu = _setter("Ting-Lu", "Vessel of Ruin", "Leftovers", "- Ruination\n- Stealth Rock\n- Whirlwind\n- Spikes")
    turns = [("move bellydrum", "move stealthrock"), ("move substitute", "move spikes"),
             ("move clangoroussoul", "move spikes")]  # fmt: skip
    states = ec.run_showdown(kommo, lu, turns)
    k = 2
    assert states[k]["sides"][0]["mons"][0]["hp"] <= states[k]["sides"][0]["mons"][0]["maxhp"] // 3
    assert states[k + 1]["sides"][0]["mons"][0]["item"] == "throatspray"
    outs = ec.engine_outcomes(ec.engine_state(states[k]), "clangoroussoul", "spikes")
    assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}


# L104 (doc/engine-diff.md): a Gem powers only a damaging move (Showdown's onSourceTryPrimaryHit:
# not a status move); the engine used up a Normal Gem on Court Change
def test_l104_gem_not_on_a_status_move():
    cinder = _setter("Cinderace", "Blaze", "Normal Gem", "- Court Change\n- Pyro Ball\n- U-turn\n- Sucker Punch")
    states = ec.run_showdown(cinder, BLISSEY, [("move courtchange", "move softboiled")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "normalgem"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "courtchange", "softboiled")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L105 (doc/engine-diff.md): the terrain moves (Electric / Grassy / Misty / Psychic Terrain) set
# their terrain for 5 turns (8 with Terrain Extender); they had no effect in the engine (only the
# Surge abilities set one)
@pytest.mark.parametrize("move, item", [("electricterrain", "Leftovers"), ("grassyterrain", "Terrain Extender"),
                                        ("mistyterrain", "Leftovers"), ("psychicterrain", "Leftovers")])  # fmt: skip
def test_l105_terrain_moves(move, item):
    names = {"electricterrain": "Electric Terrain", "grassyterrain": "Grassy Terrain",
             "mistyterrain": "Misty Terrain", "psychicterrain": "Psychic Terrain"}  # fmt: skip
    setter = _setter("Indeedee", "Inner Focus", item, f"- {names[move]}\n- Psychic\n- Protect\n- Calm Mind")
    states = ec.run_showdown(setter, BLISSEY, [(f"move {move}", "move softboiled"), ("move calmmind", "move softboiled")])
    assert states[1]["field"]["terrain"] == move
    for k, c1 in ((0, move), (1, "calmmind")):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, "softboiled")
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k


# L106 (doc/engine-diff.md): Skill Swap swaps the two actives' abilities and starts the new ones
# (Showdown's skillSwap: fails on an ability with failskillswap, through an Ability Shield); it had
# no effect in the engine
@pytest.mark.parametrize("target, second", [
    (_setter("Zamazenta", "Dauntless Shield", "Leftovers", "- Iron Defense\n- Body Press\n- Crunch\n- Roar"), "irondefense"),
    (_setter("Landorus-Therian", "Intimidate", "Leftovers", "- Stealth Rock\n- Earthquake\n- U-turn\n- Taunt"), "stealthrock"),
    (_setter("Mimikyu", "Disguise", "Leftovers", "- Swords Dance\n- Shadow Claw\n- Play Rough\n- Substitute"), "swordsdance"),
], ids=["dauntless-shield", "intimidate", "disguise-fails"])  # fmt: skip
def test_l106_skill_swap(target, second):
    bee = _setter("Ribombee", "Shield Dust", "Leftovers", "- Skill Swap\n- Moonblast\n- Sticky Web\n- U-turn")
    states = ec.run_showdown(bee, target, [("move skillswap", f"move {second}")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "skillswap", second)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L107 (doc/engine-diff.md): Mean Look / Block / Spider Web trap the target until their user
# leaves the field (Showdown's trapped volatile, linked to the trapper; not a Ghost type, not
# through a Substitute); they had no effect in the engine
def _switch_options(state, side_two=True):
    res = pe.mcts(state, 0, 50, 1)
    side = res.s2 if side_two else res.s1
    return [o.move_choice for o in side if o.move_choice.startswith("switch")]


def test_l107_mean_look_traps():
    umb = _setter("Umbreon", "Synchronize", "Leftovers", "- Mean Look\n- Wish\n- Protect\n- Foul Play")
    chansey = BLISSEY.replace("Blissey @ Heavy-Duty Boots", "Chansey @ Eviolite")
    states = ec.run_showdown(umb, BLISSEY + "\n\n" + chansey, [("move meanlook", "move softboiled")])
    assert "trapped" in states[1]["sides"][1]["mons"][0]["volatiles"]
    assert states[1]["sides"][1]["request_json"]["active"][0].get("trapped")
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "meanlook", "softboiled")
    assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}
    assert _switch_options(ec.engine_state(states[1])) == []


def test_l107_trap_ends_when_the_trapper_leaves():
    umb = _setter("Umbreon", "Synchronize", "Leftovers", "- Mean Look\n- Wish\n- Protect\n- Foul Play")
    chansey = BLISSEY.replace("Blissey @ Heavy-Duty Boots", "Chansey @ Eviolite")
    states = ec.run_showdown(umb + "\n\n" + chansey, BLISSEY + "\n\n" + chansey,
                             [("move meanlook", "move softboiled"), ("switch 2", "move softboiled")])  # fmt: skip
    assert "trapped" not in states[2]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "chansey", "softboiled")
    assert ec.closest(states[2], outs, (2, 2), hp=True)["diff"] == {}
    assert _switch_options(ec.engine_state(states[2]))


# L108 (doc/engine-diff.md): Spirit Shackle / Anchor Shot trap their target (a 100% secondary:
# Covert Cloak / Shield Dust stop it), Jaw Lock traps both (its onHit, not through a Substitute);
# a Prankster's Mean Look fails on a Dark type (the code effects too, not only the data ones)
@pytest.mark.parametrize("user, move, both", [
    (_attacker("Decidueye", "Overgrow", "Leftovers", "- Spirit Shackle\n- Leaf Blade\n- Roost\n- Swords Dance"), "spiritshackle", False),
    (_attacker("Dhelmise", "Steelworker", "Leftovers", "- Anchor Shot\n- Power Whip\n- Rapid Spin\n- Swords Dance"), "anchorshot", False),
    (_attacker("Dracovish", "Strong Jaw", "Leftovers", "- Jaw Lock\n- Fishious Rend\n- Psychic Fangs\n- Swords Dance"), "jawlock", True),
], ids=["spirit-shackle", "anchor-shot", "jaw-lock"])  # fmt: skip
def test_l108_trapping_attacks(user, move, both):
    pex = _setter("Toxapex", "Regenerator", "Black Sludge", "- Recover\n- Toxic\n- Haze\n- Scald")
    states = ec.run_showdown(user, pex, [(f"move {move}", "move recover")])
    assert "trapped" in states[1]["sides"][1]["mons"][0]["volatiles"]
    assert ("trapped" in states[1]["sides"][0]["mons"][0]["volatiles"]) == both
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "recover")
    res = ec.closest(states[1], outs, (1, 1), hp=True)
    assert res["diff"] == {} and res["p"] > 0.9


def test_l108_prankster_mean_look_into_a_dark_type():
    sable = _setter("Sableye", "Prankster", "Leftovers", "- Mean Look\n- Recover\n- Will-O-Wisp\n- Knock Off")
    gambit = _attacker("Kingambit", "Supreme Overlord", "Leftovers", "- Swords Dance\n- Iron Head\n- Sucker Punch\n- Protect")
    states = ec.run_showdown(sable, gambit, [("move meanlook", "move swordsdance")])
    assert "trapped" not in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "meanlook", "swordsdance")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l107_trapped_from_the_protocol():
    """Our state construction's trap (agents/timers.py, from the log) against Showdown's."""
    from alpha_poke.agents.timers import timers

    umb = _setter("Umbreon", "Synchronize", "Leftovers", "- Mean Look\n- Wish\n- Protect\n- Foul Play")
    chansey = BLISSEY.replace("Blissey @ Heavy-Duty Boots", "Chansey @ Eviolite")
    states = ec.run_showdown(umb + "\n\n" + chansey, BLISSEY + "\n\n" + chansey,
                             [("move meanlook", "move softboiled"), ("move protect", "move softboiled"),
                              ("switch 2", "move softboiled")])  # fmt: skip
    lines: list = []
    for st in states:
        lines += [x.split("|") for x in st["log"]]
        p2 = st["sides"][1]
        assert timers(lines)["p2"].trapped == ("trapped" in p2["mons"][p2["active"]]["volatiles"]), st["turn"]


# L109 (doc/engine-diff.md): a hit whose rolls straddle "survives the end of the turn" (the
# target's predictable end-of-turn damage: Salt Cure, poison, Leech Seed, ...) splits by the exact
# rolls there too, like a knockout (L34); the engine dealt the average non-knockout roll, so the
# end-of-turn knockout was all or nothing
def test_l109_end_of_turn_knockout_by_the_rolls():
    import alpha_search

    gar = _setter("Garganacl", "Purifying Salt", "Leftovers", "- Salt Cure\n- Recover\n- Protect\n- Stealth Rock")
    gam = _attacker("Kingambit", "Supreme Overlord", "Choice Band", "- Kowtow Cleave\n- Protect\n- Swords Dance\n- Low Kick")
    blis = BLISSEY.replace("Blissey @ Heavy-Duty Boots", "Blissey @ Leftovers").replace("- Protect", "- Belly Drum")
    turns = [("move saltcure", "move bellydrum"), ("switch 2", "move softboiled"), ("move kowtowcleave", "move seismictoss")]
    states = ec.run_showdown(gar + "\n\n" + gam, blis, turns)
    b = states[2]["sides"][1]["mons"][0]
    assert "saltcure" in b["volatiles"]
    rolls, crits = alpha_search.damage_rolls(ec.engine_state(states[2]).to_string(), True, "kowtowcleave", "seismictoss")
    h, m = b["hp"], b["maxhp"]

    def dies(d):
        left = h - d
        return left <= 0 or min(m, left + m // 16) - m // 8 <= 0

    c = 1 / 24
    want = (1 - c) * sum(map(dies, rolls)) / 16 + c * sum(map(dies, crits)) / 16
    assert 0 < (1 - c) * sum(map(dies, rolls)) / 16 < 1 - c  # (the rolls straddle it)
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "kowtowcleave", "seismictoss")
    fainted = sum(p for p, o in outs if ec.view_engine(o, (2, 1))["s2.0.hp"] == 0)
    assert fainted == pytest.approx(want, abs=1e-3)
    # (Showdown's own roll: one of the engine's outcomes; a knockout is a decision point, where
    # the fainted active's boosts are compared differently, so only the HP)
    sd_hp = states[3]["sides"][1]["mons"][0]["hp"]
    assert any((ec.view_engine(o, (2, 1))["s2.0.hp"] == 0) == (sd_hp == 0) for _, o in outs)


# L110 (doc/engine-diff.md): at a decision point in the turn (a pivot's switch), a roosting mon's
# types are without Flying in Showdown (getTypes): no type change for the comparison (the engine's
# roost volatile says it); the trapper's faint ends its partial trap before the end of the turn
# (Showdown's onResidual: the source is not active), and a fainted seeder's Leech Seed saps nothing
def test_l110_roost_is_no_type_change():
    nite = _setter("Dragonite", "Multiscale", "Heavy-Duty Boots", "- Roost\n- Extreme Speed\n- Dragon Dance\n- Earthquake")
    bolt = _attacker("Raging Bolt", "Protosynthesis", "Leftovers", "- Volt Switch\n- Thunderbolt\n- Draco Meteor\n- Calm Mind", "Modest")
    states = ec.run_showdown(nite, bolt + "\n\n" + BLISSEY, [("move dragondance", "move dracometeor"),
                                                               ("move roost", "move voltswitch")])  # fmt: skip
    assert "roost" in states[2]["sides"][0]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "roost", "voltswitch")
    assert ec.closest(states[2], outs, (1, 2), hp=True)["diff"] == {}


def test_l110_partial_trap_ends_with_its_fainted_user():
    pex = _setter("Toxapex", "Regenerator", "Black Sludge", "- Infestation\n- Recover\n- Haze\n- Toxic")
    gambit = _attacker("Kingambit", "Supreme Overlord", "Leftovers", "- Sucker Punch\n- Iron Head\n- Swords Dance\n- Kowtow Cleave")
    pex2 = pex.replace("Toxapex @", "Pex (Toxapex) @")
    turns = [("move infestation", "move swordsdance")] + [("move toxic", "move ironhead")] * 3
    states = ec.run_showdown(pex + "\n\n" + pex2, gambit, turns)
    k = next(k for k in range(len(states) - 1) if states[k + 1]["sides"][0]["request"] == "switch")
    assert "partiallytrapped" in states[k]["sides"][1]["mons"][0]["volatiles"]
    assert "partiallytrapped" not in states[k + 1]["sides"][1]["mons"][0]["volatiles"]
    c1 = turns[k][0].split()[1]
    outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, turns[k][1].split()[1])
    assert ec.closest(states[k + 1], outs, (2, 1), hp=True)["diff"] == {}


# L111 (doc/engine-diff.md): Battle Bond raises Attack / Sp. Atk / Speed after a knockout only
# for Greninja-Bond, once per battle (Showdown's species check, bondTriggered); the engine gave it
# to any holder at every knockout
@pytest.mark.parametrize("species, boost", [("Greninja-Bond", 1), ("Greninja", 0)])
def test_l111_battle_bond(species, boost):
    gren = _attacker(species, "Battle Bond", "Life Orb", "- Dark Pulse\n- Surf\n- Ice Beam\n- U-turn", "Timid")
    shed = """Shedinja @ Heavy-Duty Boots
Ability: Wonder Guard
EVs: 252 Atk / 252 Spe
Adamant Nature
- Swords Dance
- Shadow Sneak
- Protect
- X-Scissor"""
    states = ec.run_showdown(gren, shed + "\n\n" + BLISSEY, [("move darkpulse", "move swordsdance")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spa"] == boost
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "darkpulse", "swordsdance")
    assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}


# L112 (doc/engine-diff.md): a pivot user that faints from its own move (Rocky Helmet, Rough Skin,
# recoil) does not switch out (Showdown: no switch request for it, the turn goes on: the foe's move
# fails without a target, then the end of the turn); the engine stopped for its pivot switch and
# saved the foe's move for the replacement
def test_l112_pivot_user_fainting():
    cinder = _attacker("Cinderace", "Blaze", "Life Orb", "- U-turn\n- Pyro Ball\n- Sucker Punch\n- Court Change", "Jolly")
    chomp = _setter("Garchomp", "Rough Skin", "Rocky Helmet", "- Earthquake\n- Stealth Rock\n- Swords Dance\n- Dragon Tail")
    pult = _attacker("Dragapult", "Infiltrator", "Choice Specs", "- Shadow Ball\n- Draco Meteor\n- U-turn\n- Flamethrower", "Timid")
    turns = [("move pyroball", "move earthquake"), ("move uturn", "move earthquake")]
    states = ec.run_showdown(cinder + "\n\n" + pult, chomp, turns)
    assert any(x.startswith("|faint|p1a: Cinderace") for x in states[2]["log"])
    assert any("[from] brn" in x for x in states[2]["log"])  # (the turn went on: Pyro Ball's burn)
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "uturn", "earthquake")
    assert ec.closest(states[2], outs, (2, 1), hp=True)["diff"] == {}


def test_l112_status_move_without_a_target():
    """After the pivot user faints, a status move aimed at it fails (Showdown's [notarget]): Pain
    Split does nothing; one aimed at the side (Stealth Rock) still goes."""
    cinder = _attacker("Cinderace", "Blaze", "Life Orb", "- U-turn\n- Pyro Ball\n- Sucker Punch\n- Court Change", "Jolly")
    pult = _attacker("Dragapult", "Infiltrator", "Choice Specs", "- Shadow Ball\n- Draco Meteor\n- U-turn\n- Flamethrower", "Timid")
    for move in ("painsplit", "stealthrock", "curse"):
        chomp = _setter("Garchomp", "Rough Skin", "Rocky Helmet", "- Earthquake\n- Stealth Rock\n- Pain Split\n- Curse")
        turns = [("move pyroball", "move earthquake"), ("move uturn", f"move {move}")]
        states = ec.run_showdown(cinder + "\n\n" + pult, chomp, turns)
        assert any(x.startswith("|faint|p1a: Cinderace") for x in states[2]["log"]), move
        outs = ec.engine_outcomes(ec.engine_state(states[1]), "uturn", move)
        assert ec.closest(states[2], outs, (2, 1), hp=True)["diff"] == {}, move


# L113 (doc/engine-diff.md): Knock Off takes nothing when its user faints from the hit's contact
# damage (Rocky Helmet, Rough Skin / Iron Barbs: Showdown's onAfterHit needs the user's HP); the
# engine took the item
def test_l113_knock_off_user_fainting_to_rocky_helmet():
    shed = """Shedinja @ Heavy-Duty Boots
Ability: Wonder Guard
EVs: 252 Atk / 252 Spe
Adamant Nature
- Knock Off
- Shadow Sneak
- Protect
- X-Scissor"""
    pult = _attacker("Dragapult", "Infiltrator", "Choice Specs", "- Shadow Ball\n- Draco Meteor\n- U-turn\n- Flamethrower", "Timid")
    chomp = _setter("Garchomp", "Rough Skin", "Rocky Helmet", "- Earthquake\n- Stealth Rock\n- Swords Dance\n- Spikes")
    states = ec.run_showdown(shed + "\n\n" + pult, chomp, [("move knockoff", "move spikes")])
    assert any(x.startswith("|faint|p1a: Shedinja") for x in states[1]["log"])
    assert states[1]["sides"][1]["mons"][0]["item"] == "rockyhelmet"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "knockoff", "spikes")
    assert ec.closest(states[1], outs, (2, 1), hp=True)["diff"] == {}


# L114 (doc/engine-diff.md): a Sticky Barb moves to an attacker without an item before Knock Off
# would take it (Showdown: its onHit during the hit, Knock Off's onAfterHit after); a Life Orb that
# Pickpocket takes gives its former holder no recoil (Showdown: the recoil after the move, from the
# item it holds then)
def test_l114_sticky_barb_before_knock_off():
    buzz = _setter("Mandibuzz", "Overcoat", "Heavy-Duty Boots", "- Knock Off\n- Roost\n- Defog\n- U-turn")
    buzz = buzz.replace(" @ Heavy-Duty Boots", "")
    clef = _setter("Clefable", "Magic Guard", "Sticky Barb", "- Calm Mind\n- Moonblast\n- Protect\n- Trick")
    states = ec.run_showdown(buzz, clef, [("move knockoff", "move calmmind")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "stickybarb"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "knockoff", "calmmind")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l114_pickpocket_takes_the_life_orb_before_its_recoil():
    weavile = WEAVILE_PICKPOCKET.replace("Heavy-Duty Boots", "Leftovers")
    scizor = _attacker("Scizor", "Technician", "Life Orb", "- Knock Off\n- Bullet Punch\n- Swords Dance\n- U-turn")
    states = ec.run_showdown(weavile, scizor, [("move swordsdance", "move knockoff")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "lifeorb"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "swordsdance", "knockoff")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l114_balloon_pop_leaves_the_stolen_item():
    """Air Balloon pops on the hit; Pickpocket then takes the attacker's item, which the pop must
    not remove too (the engine's pop is a secondary after the move: it removed the new item)."""
    treads = _attacker("Iron Treads", "Quark Drive", "Assault Vest", "- Knock Off\n- Earthquake\n- Rapid Spin\n- Iron Head")
    tink = _setter("Tinkaton", "Pickpocket", "Air Balloon", "- Gigaton Hammer\n- Stealth Rock\n- Encore\n- Thunder Wave")
    states = ec.run_showdown(treads, tink, [("move knockoff", "move stealthrock")])
    assert states[1]["sides"][1]["mons"][0]["item"] == "assaultvest"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "knockoff", "stealthrock")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L115 (doc/engine-diff.md): Temper Flare / Stomping Tantrum double their power when their user's
# move failed the turn before (Showdown's moveLastTurnResult false: a miss, an immunity, a failure,
# a full paralysis / sleep / flinch; not a Protect, which gives null); the engine had no doubling
def test_l115_power_doubles_after_a_failed_move():
    tusk = _attacker("Great Tusk", "Protosynthesis", "Leftovers", "- Temper Flare\n- Headlong Rush\n- Rapid Spin\n- Bulk Up")
    corv = _setter("Corviknight", "Pressure", "Leftovers", "- Roost\n- Brave Bird\n- Defog\n- U-turn")
    states = ec.run_showdown(tusk, corv, [("move headlongrush", "move defog"), ("move temperflare", "move defog")])
    assert any(x.startswith("|-immune|p2a:") for x in states[1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "temperflare", "defog")
    res = ec.closest(states[2], outs, (1, 1), hp=True)
    crit = any(x.startswith("|-crit") for x in states[2]["log"])
    ko = states[2]["sides"][1]["mons"][0]["hp"] == 0  # (a knockout by the rolls: its branch's share)
    assert res["diff"] == {} and (crit or ko or res["p"] > 0.9)


def test_l115_failed_move_from_the_protocol():
    """Our state construction's flag (agents/timers.py, from the log) against Showdown's
    moveLastTurnResult (the harness's lastmovefailed)."""
    from alpha_poke.agents.timers import timers

    tusk = _attacker("Great Tusk", "Protosynthesis", "Leftovers", "- Temper Flare\n- Headlong Rush\n- Rapid Spin\n- Bulk Up")
    corv = _setter("Corviknight", "Pressure", "Leftovers", "- Roost\n- Brave Bird\n- Defog\n- U-turn")
    turns = [("move headlongrush", "move defog"), ("move bulkup", "move roost"), ("move headlongrush", "move defog")]
    states = ec.run_showdown(tusk, corv, turns)
    lines: list = []
    seen = set()
    for st in states:
        lines += [x.split("|") for x in st["log"]]
        sd = "lastmovefailed" in st["sides"][0]["mons"][0]["volatiles"]
        seen.add(sd)
        assert timers(lines)["p1"].last_failed == sd, st["turn"]
    assert seen == {True, False}


# L116 (doc/engine-diff.md): Steel Beam costs its user half its HP when it misses or is blocked too
# (Showdown's onMoveFail); the engine's cost came with the hit only
@pytest.mark.parametrize("foe_move, force", [("calmmind", False), ("protect", None)], ids=["miss", "protect"])
def test_l116_steel_beam_fails_at_a_cost(foe_move, force):
    treads = _attacker("Iron Treads", "Quark Drive", "Leftovers", "- Steel Beam\n- Earthquake\n- Rapid Spin\n- Iron Head", "Modest")
    states = ec.run_showdown(treads, BLISSEY, [("move steelbeam", f"move {foe_move}")], force_random=force)
    assert any("[from] Steel Beam" in x or "[from] steelbeam" in x for x in states[1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "steelbeam", foe_move)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L117 (doc/engine-diff.md): a multi-hit move stops at the hit after which its user faints to the
# target's contact damage (Rocky Helmet, Rough Skin: Showdown's hit loop breaks); the engine dealt
# every hit
def test_l117_multi_hit_stops_when_the_user_faints():
    cinc = _attacker("Cinccino", "Skill Link", "Heavy-Duty Boots", "- Tail Slap\n- Belly Drum\n- Substitute\n- U-turn", "Jolly")
    blis = BLISSEY.replace("Heavy-Duty Boots", "Rocky Helmet")
    pult = _attacker("Dragapult", "Infiltrator", "Choice Specs", "- Shadow Ball\n- Draco Meteor\n- U-turn\n- Flamethrower", "Timid")
    turns = [("move substitute", "move seismictoss")] * 2 + [("move tailslap", "move calmmind")]
    states = ec.run_showdown(cinc + "\n\n" + pult, blis, turns)
    assert any(x.startswith("|faint|p1a: Cinccino") for x in states[3]["log"])
    assert any(x.startswith("|-hitcount|") and x.endswith("|4") for x in states[3]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "tailslap", "calmmind")
    assert ec.closest(states[3], outs, (2, 1), hp=True)["diff"] == {}


# L118 (doc/engine-diff.md): Flying Press is Fighting and Flying for its effectiveness (Showdown's
# onEffectiveness adds Flying's); the engine took Fighting only (2x on a Tera Steel target, not 1x)
def test_l118_flying_press_is_flying_too():
    lucha = _attacker("Hawlucha", "Unburden", "Leftovers", "- Flying Press\n- Swords Dance\n- Roost\n- Acrobatics", "Jolly")
    latios = _setter("Latios", "Levitate", "Leftovers", "- Calm Mind\n- Draco Meteor\n- Recover\n- Psyshock")
    latios = latios.replace("Tera Type: Normal", "Tera Type: Steel")
    states = ec.run_showdown(lucha, latios, [("move flyingpress", "move calmmind terastallize")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "flyingpress", "calmmind-tera")
    res = ec.closest(states[1], outs, (1, 1), hp=True)
    assert res["diff"] == {}


# L119 (doc/engine-diff.md): a mover whose target has fainted still goes through its status (sleep's
# count and waking, a thaw: Showdown's BeforeMove comes before the target check); the engine stopped
# it first, so a Rest sleeper due to wake stayed asleep
def test_l119_sleeper_wakes_without_a_target():
    lu = _setter("Ting-Lu", "Vessel of Ruin", "Leftovers", "- Rest\n- Stealth Rock\n- Whirlwind\n- Ruination")
    blis = BLISSEY.replace("- Calm Mind", "- Healing Wish")
    chansey = BLISSEY.replace("Blissey @ Heavy-Duty Boots", "Chansey @ Eviolite")
    turns = [("move stealthrock", "move seismictoss"), ("move rest", "move seismictoss"),
             ("move rest", "move seismictoss"), ("move rest", "move seismictoss"),
             ("move ruination", "move healingwish")]  # fmt: skip
    states = ec.run_showdown(lu, blis + "\n\n" + chansey, turns)
    assert states[4]["sides"][0]["mons"][0]["status"] == "slp"
    assert states[5]["sides"][0]["mons"][0]["status"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[4]), "ruination", "healingwish")
    assert ec.closest(states[5], outs, (1, 2), hp=True)["diff"] == {}


# L120 (doc/engine-diff.md): an Air Balloon pops on any damaging hit: Future Sight's, Counter /
# Mirror Coat / Metal Burst's, Final Gambit's too (Showdown's onDamagingHit); the engine popped it
# only on a move's ordinary hit (a secondary)
def test_l120_balloon_pops_on_mirror_coat():
    momo = _setter("Alomomola", "Regenerator", "Leftovers", "- Mirror Coat\n- Wish\n- Protect\n- Scald")
    tran = _setter("Heatran", "Flash Fire", "Air Balloon", "- Earth Power\n- Magma Storm\n- Protect\n- Stealth Rock")
    states = ec.run_showdown(momo, tran, [("move mirrorcoat", "move earthpower")])
    assert states[1]["sides"][1]["mons"][0]["hp"] > 0
    assert states[1]["sides"][1]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "mirrorcoat", "earthpower")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L121 (doc/engine-diff.md): Parting Shot fails, and its user stays, when it lowers no stat (Clear
# Body, Mirror Armor, at -6, a Substitute: Showdown's onHit returns false); the engine switched out
def test_l121_parting_shot_into_clear_body():
    room = _setter("Revavroom", "Filter", "Leftovers", "- Parting Shot\n- Gunk Shot\n- Shift Gear\n- Iron Head")
    steel = _setter("Registeel", "Clear Body", "Leftovers", "- Body Press\n- Iron Defense\n- Stealth Rock\n- Protect")
    states = ec.run_showdown(steel, room + "\n\n" + BLISSEY, [("move irondefense", "move partingshot")])
    assert states[1]["sides"][1]["active"] == 0 and states[1]["sides"][1]["request"] == "move"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "irondefense", "partingshot")
    assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}


# L122 (doc/engine-diff.md): Red Card / Eject Button go off on a hit Disguise takes too (Showdown's
# onAfterMoveSecondary: a non-status move that hit, no damage needed); the engine needed damage
def test_l122_red_card_through_disguise():
    mimi = _setter("Mimikyu", "Disguise", "Red Card", "- Swords Dance\n- Shadow Claw\n- Play Rough\n- Substitute")
    gambit = _attacker("Kingambit", "Supreme Overlord", "Leftovers", "- Iron Head\n- Sucker Punch\n- Swords Dance\n- Kowtow Cleave")
    states = ec.run_showdown(mimi, gambit + "\n\n" + BLISSEY, [("move swordsdance", "move ironhead")])
    assert any(x.startswith("|-enditem|p1a: Mimikyu|Red Card") for x in states[1]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "swordsdance", "ironhead")
    assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}


# L123 (doc/engine-diff.md): a Custap Berry is eaten whenever its holder uses a move at a quarter of
# its HP or less (half with Gluttony), whatever the priorities (Showdown's onFractionalPriority
# gets the fractional priority, 0); the engine ate it only at equal priorities, below a quarter
def test_l123_custap_with_endure():
    quanid = _setter("Araquanid", "Water Bubble", "Custap Berry", "- Endure\n- Belly Drum\n- Substitute\n- Liquidation")
    turns = [("move bellydrum", "move calmmind"), ("move substitute", "move calmmind"), ("move endure", "move calmmind")]
    states = ec.run_showdown(quanid, BLISSEY, turns)
    a = states[2]["sides"][0]["mons"][0]
    assert a["hp"] * 4 == a["maxhp"] and a["item"] == "custapberry"  # (exactly a quarter)
    assert states[3]["sides"][0]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "endure", "calmmind")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


# L124 (doc/engine-diff.md): when Neutralizing Gas leaves (its holder switches out or faints),
# a Protosynthesis / Quark Drive holder's Booster Energy goes off at once (Showdown: the abilities
# start again); the engine never used it
def test_l124_booster_energy_after_neutralizing_gas():
    weezing = _setter("Weezing-Galar", "Neutralizing Gas", "Leftovers", "- Will-O-Wisp\n- Pain Split\n- Strange Steam\n- Defog")
    tusk = _attacker("Great Tusk", "Protosynthesis", "Booster Energy", "- Headlong Rush\n- Ice Spinner\n- Rapid Spin\n- Bulk Up", "Jolly")
    states = ec.run_showdown(weezing + "\n\n" + BLISSEY, tusk, [("switch 2", "move bulkup")])
    assert states[0]["sides"][1]["mons"][0]["item"] == "boosterenergy"
    assert states[1]["sides"][1]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "blissey", "bulkup")
    assert ec.closest(states[1], outs, (2, 1), hp=True)["diff"] == {}


# L125 (doc/engine-diff.md): Lunar Blessing / Jungle Healing also cure their user's status
# (Showdown's onHit: cureStatus); the engine only healed
@pytest.mark.parametrize("user, move", [
    (_setter("Cresselia", "Levitate", "Flame Orb", "- Lunar Blessing\n- Moonblast\n- Calm Mind\n- Protect"), "lunarblessing"),
    (_setter("Zarude", "Leaf Guard", "Flame Orb", "- Jungle Healing\n- Power Whip\n- Knock Off\n- U-turn"), "junglehealing"),
], ids=["lunar-blessing", "jungle-healing"])  # fmt: skip
def test_l125_healing_moves_cure_status(user, move):
    states = ec.run_showdown(user, BLISSEY, [("move protect" if move == "lunarblessing" else "move uturn", "move seismictoss"),
                                             (f"move {move}", "move seismictoss")])  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["status"] == "brn"
    outs = ec.engine_outcomes(ec.engine_state(states[1]), move, "seismictoss")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L126 (doc/engine-diff.md): a sleeper's (or a frozen mon's) status goes before a flinch / Taunt
# stops it (Showdown's BeforeMove order: sleep 10, flinch 8, Taunt 5): it can wake that turn; the
# engine stopped it first
def test_l126_wakes_before_the_flinch():
    zo = _setter("Dondozo", "Unaware", "Leftovers", "- Rest\n- Curse\n- Waterfall\n- Sleep Talk")
    gambit = _attacker("Kingambit", "Supreme Overlord", "Leftovers", "- Iron Head\n- Sucker Punch\n- Swords Dance\n- Kowtow Cleave")
    turns = [("move curse", "move ironhead"), ("move rest", "move swordsdance"), ("move curse", "move swordsdance"),
             ("move curse", "move swordsdance"), ("move curse", "move ironhead")]  # fmt: skip
    states = ec.run_showdown(zo, gambit, turns, force_random=True)
    assert states[4]["sides"][0]["mons"][0]["status"] == "slp"
    assert any("|cant|p1a: Dondozo|flinch" in x for x in states[5]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[4]), "curse", "ironhead")
    assert ec.closest(states[5], outs, (1, 1), hp=True)["diff"] == {}


# L127 (doc/engine-diff.md): a Mold Breaker's status move goes through a breakable status-blocking
# ability (Purifying Salt, Limber, Insomnia, ...); the engine's immunity ignored Mold Breaker
def test_l127_mold_breaker_through_purifying_salt():
    tink = _setter("Tinkaton", "Mold Breaker", "Leftovers", "- Thunder Wave\n- Gigaton Hammer\n- Stealth Rock\n- Encore")
    salt = _setter("Garganacl", "Purifying Salt", "Leftovers", "- Recover\n- Salt Cure\n- Stealth Rock\n- Protect")
    states = ec.run_showdown(tink, salt, [("move thunderwave", "move recover")], force_random=True)
    assert states[1]["sides"][1]["mons"][0]["status"] == "par"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "thunderwave", "recover")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L128 (doc/engine-diff.md): Magic Bounce sends a stat-lowering move's drops back to its user
# (Parting Shot, Tickle, ...) and the user does not switch out (its Parting Shot was bounced); the
# engine bounced the side / status / volatile effects only, the boosts stayed on the bouncer
def test_l128_magic_bounce_parting_shot():
    pech = _setter("Pecharunt", "Poison Puppeteer", "Leftovers", "- Parting Shot\n- Recover\n- Malignant Chain\n- Nasty Plot")
    hatt = _setter("Hatterene", "Magic Bounce", "Leftovers", "- Calm Mind\n- Psyshock\n- Draining Kiss\n- Protect")
    states = ec.run_showdown(pech + "\n\n" + BLISSEY, hatt, [("move partingshot", "move calmmind")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["atk"] == -1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "partingshot", "calmmind")
    assert ec.closest(states[1], outs, (2, 1), hp=True)["diff"] == {}


# L128: a reflector with someone to switch in is the one that switches out (its own move -- Calm
# Mind, after the faster Pecharunt's -- is lost)
def test_l128_magic_bounce_parting_shot_switches_the_reflector():
    pech = _setter("Pecharunt", "Poison Puppeteer", "Leftovers", "- Parting Shot\n- Recover\n- Malignant Chain\n- Nasty Plot")
    hatt = _setter("Hatterene", "Magic Bounce", "Leftovers", "- Calm Mind\n- Psyshock\n- Draining Kiss\n- Protect")
    states = ec.run_showdown(pech + "\n\n" + BLISSEY, hatt + "\n\n" + BLISSEY, [("move partingshot", "move calmmind")])
    assert states[1]["sides"][1]["request"] == "switch"
    assert states[1]["sides"][1]["mons"][0]["boosts"]["spa"] == 0
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "partingshot", "calmmind")
    assert ec.closest(states[1], outs, (2, 2), hp=True)["diff"] == {}


def _random_position(teams: str, i: int, turn: int, offset: int = 0):
    """A turn of a random-differential battle (scripts/check_engine_random.py): its start and the
    step after it."""
    pairs = [json.loads(x) for x in (Path("tests/fixtures") / teams).read_text().splitlines()]
    p = pairs[i % len(pairs)]
    k = i + offset
    steps, _ = ec.random_battle(p["p1"], p["p2"], f"gen5,{k},{k + 1},{k + 2},{k + 3}", k + 1, max_turns=60)
    j = next(j for j, s in enumerate(steps) if s["state"]["turn"] == turn and set(s["choices"]) == {"p1", "p2"})
    return steps[j], steps[j + 1]


# L129 (doc/engine-diff.md): a mon that faints to the hazards as it comes in starts no ability
# (Intimidate: Showdown's hazards come first); the engine's Intimidate went off anyway
def test_l129_no_intimidate_after_fainting_to_hazards():
    a, b = _random_position("random_battle_teams.jsonl", 224, 15)
    assert any(x.startswith("|faint|p2a: Landorus") for x in b["state"]["log"])
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L130 (doc/engine-diff.md): Clear Body / Clear Amulet (and the like) only block the foe's stat
# drops (Showdown's onTryBoost: boost < 0); the engine's check blocked the foe's raises too (a
# Weakness Policy's, Swagger's)
@pytest.mark.parametrize("ability,item,foe_move", [
    ("Clear Body", "Weakness Policy", "earthquake"),
    ("Clear Body", "Leftovers", "swagger"),
    ("Light Metal", "Clear Amulet", "swagger"),
])  # fmt: skip
def test_l130_clear_body_lets_foe_raises_through(ability, item, foe_move):
    meta = _setter("Metagross", ability, item, "- Protect\n- Iron Defense\n- Bullet Punch\n- Agility")
    chomp = _setter("Garchomp", "Rough Skin", "Leftovers", "- Earthquake\n- Swagger\n- Protect\n- Roar")
    states = ec.run_showdown(meta, chomp, [("move irondefense", f"move {foe_move}")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["atk"] == 2
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "irondefense", foe_move)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L130's control: a Substitute still stops Swagger (raise and confusion)
def test_l130_swagger_into_substitute():
    meta = _setter("Metagross", "Light Metal", "Leftovers", "- Protect\n- Substitute\n- Bullet Punch\n- Agility")
    chomp = _setter("Garchomp", "Rough Skin", "Leftovers", "- Earthquake\n- Swagger\n- Protect\n- Roar")
    states = ec.run_showdown(meta, chomp, [("move substitute", "move protect"), ("move agility", "move swagger")])
    assert states[2]["sides"][0]["mons"][0]["boosts"]["atk"] == 0
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "agility", "swagger")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L131 (doc/engine-diff.md): Mirror Herb copies the foe's raises whoever caused them (its holder's
# own Swagger too: Showdown's onFoeAfterBoost); the engine's only the foe's own
def test_l131_mirror_herb_copies_swagger():
    meta = _setter("Metagross", "Light Metal", "Leftovers", "- Protect\n- Iron Defense\n- Bullet Punch\n- Agility")
    chomp = _setter("Garchomp", "Rough Skin", "Mirror Herb", "- Earthquake\n- Swagger\n- Protect\n- Roar")
    states = ec.run_showdown(meta, chomp, [("move irondefense", "move swagger")])
    assert states[1]["sides"][1]["mons"][0]["boosts"]["atk"] == 2
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "irondefense", "swagger")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


SLAKING = """Slaking @ Leftovers
Ability: Truant
Tera Type: Normal
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Earthquake
- Hyper Beam
- Slack Off
- Body Slam"""


# L132 (doc/engine-diff.md): Truant's loafing turn comes after any move it started (Showdown's
# onBeforeMove: into an immune target too), and a recharge turn ends it (mustrecharge's
# onBeforeMove); the engine set it only on a hit, and kept it through a recharge
@pytest.mark.parametrize("turns", [
    [("move earthquake", "earthquake"), ("move earthquake", "earthquake")],
    [("move hyperbeam", "hyperbeam"), ("move 1", "none"), ("move bodyslam", "bodyslam"),
     ("move bodyslam", "bodyslam")],
])  # fmt: skip
def test_l132_truant_after_any_move(turns):
    states = ec.run_showdown(SLAKING, CORVIKNIGHT, [(c, "move roost") for c, _ in turns])
    if turns[1][1] == "none":
        assert "mustrecharge" in states[1]["sides"][0]["mons"][0]["volatiles"]
    for k, (_, c) in enumerate(turns):
        outs = ec.engine_outcomes(ec.engine_state(states[k]), c, "roost")
        assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}, k


# L133 (doc/engine-diff.md): a status move aimed at the foe fails against a Substitute unless it
# bypasses it (Showdown's bypasssub): Memento's user stays (the engine's fainted), and a Contrary
# target gets no raise (L130's control)
def test_l133_memento_into_contrary_substitute():
    drif = _setter("Drifblim", "Aftermath", "Leftovers", "- Memento\n- Protect\n- Shadow Ball\n- Will-O-Wisp")
    enam = _setter("Enamorus", "Contrary", "Leftovers", "- Substitute\n- Protect\n- Moonblast\n- Earth Power")
    states = ec.run_showdown(drif + "\n\n" + BLISSEY, enam, [("move protect", "move substitute"), ("move memento", "move moonblast")])
    assert states[2]["sides"][1]["mons"][0]["boosts"]["atk"] == 0
    assert any("|-fail|p1a: Drifblim" in x for x in states[2]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "memento", "moonblast")
    assert ec.closest(states[2], outs, (2, 1), hp=True)["diff"] == {}


# L133's controls: Pain Split / Trick into a Substitute fail (no HP shared, no items swapped; the
# engine's own checks already did)
@pytest.mark.parametrize("move", ["painsplit", "trick"])
def test_l133_status_moves_into_substitute(move):
    drif = _setter("Drifblim", "Aftermath", "Light Clay", "- Pain Split\n- Trick\n- Shadow Ball\n- Protect")
    enam = _setter("Enamorus", "Contrary", "Leftovers", "- Substitute\n- Protect\n- Moonblast\n- Earth Power")
    states = ec.run_showdown(drif, enam, [("move protect", "move substitute"), (f"move {move}", "move earthpower")])
    assert any("|-fail|p1a: Drifblim" in x for x in states[2]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), move, "earthpower")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L134 (doc/engine-diff.md): Magician takes nothing after its Knock Off (Showdown: Knock Off's
# onAfterHit removes the item first, Magician's onAfterMoveSecondarySelf finds none); the engine's
# Magician took the item before Knock Off
def test_l134_magician_knock_off():
    hoopa = """Hoopa-Unbound
Ability: Magician
Tera Type: Dark
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Knock Off
- Psychic
- Protect
- Trick"""
    states = ec.run_showdown(hoopa, CORVIKNIGHT, [("move knockoff", "move roost")])
    assert states[1]["sides"][0]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "knockoff", "roost")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L135 (doc/engine-diff.md): Protect stops a move an absorbing ability would take (Flash Fire,
# Well-Baked Body, Water Absorb, ...: Showdown's Protect onTryHit comes first); the engine's
# absorbed move had lost its protect flag
@pytest.mark.parametrize("target,move", [
    (_setter("Heatran", "Flash Fire", "Leftovers", "- Protect\n- Magma Storm\n- Earth Power\n- Taunt"), "flamethrower"),
    (_setter("Dachsbun", "Well-Baked Body", "Leftovers", "- Protect\n- Body Press\n- Wish\n- Roar"), "willowisp"),
])  # fmt: skip
def test_l135_protect_before_absorbing_abilities(target, move):
    user = _setter("Ninetales", "Flash Fire", "Leftovers", "- Flamethrower\n- Will-O-Wisp\n- Thunder Wave\n- Protect")
    states = ec.run_showdown(user, target, [(f"move {move}", "move protect")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, "protect")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L136 (doc/engine-diff.md): a Substitute frees its user from a partial trap (Showdown's
# substitute onStart); the engine kept the trap
def test_l136_substitute_ends_partial_trap():
    user = _setter("Serperior", "Contrary", "Leftovers", "- Substitute\n- Leaf Storm\n- Glare\n- Protect")
    trapper = _setter("Alomomola", "Regenerator", "Leftovers", "- Whirlpool\n- Protect\n- Wish\n- Scald")
    states = ec.run_showdown(user, trapper, [("move leafstorm", "move whirlpool"), ("move substitute", "move protect")])
    assert "partiallytrapped" in states[1]["sides"][0]["mons"][0]["volatiles"]
    assert "partiallytrapped" not in states[2]["sides"][0]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "substitute", "protect")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L137 (doc/engine-diff.md): Heal Block keeps a Sitrus Berry uneaten (Showdown's onTryEatItem: no
# heal); the engine's Sitrus was eaten (pinch berries already checked)
def test_l137_heal_block_stops_sitrus():
    noise = _setter("Latios", "Levitate", "Leftovers", "- Psychic Noise\n- Recover\n- Protect\n- Draco Meteor")
    azu = _setter("Azumarill", "Huge Power", "Sitrus Berry", "- Belly Drum\n- Aqua Jet\n- Play Rough\n- Protect")
    states = ec.run_showdown(noise, azu, [("move psychicnoise", "move bellydrum")])
    after = states[1]["sides"][1]["mons"][0]
    assert after["item"] == "sitrusberry" and after["boosts"]["atk"] == 6
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "psychicnoise", "bellydrum")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L138 (doc/engine-diff.md): a Terastallized Roost user gets no roost volatile (Showdown's roost
# onStart fails; its types stay); the engine's did (seen at a pivot's decision, mid-turn)
def test_l138_roost_after_terastallizing():
    corv = CORVIKNIGHT.replace("Tera Type: Dragon", "Tera Type: Flying")
    forre = _setter("Forretress", "Sturdy", "Leftovers", "- U-turn\n- Stone Edge\n- Spikes\n- Rapid Spin")
    states = ec.run_showdown(corv, forre + "\n\n" + BLISSEY, [("move defog", "move stoneedge"),
                                                              ("move roost terastallize", "move uturn")])  # fmt: skip
    assert states[2]["sides"][1]["request"] == "switch"
    assert "roost" not in states[2]["sides"][0]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "roost-tera", "uturn")
    assert ec.closest(states[2], outs, (1, 2), hp=True)["diff"] == {}


# L135's control: a charge move's first turn into Protect still charges (Meteor Beam's raise)
def test_l135_charge_turn_into_protect():
    glim = _setter("Glimmora", "Toxic Debris", "Leftovers", "- Meteor Beam\n- Earth Power\n- Spikes\n- Protect")
    states = ec.run_showdown(glim, _setter("Heatran", "Flash Fire", "Leftovers", "- Protect\n- Magma Storm\n- Earth Power\n- Taunt"),
                             [("move meteorbeam", "move protect")])  # fmt: skip
    assert "meteorbeam" in states[1]["sides"][0]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "meteorbeam", "protect")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L137: the Sitrus Berry Heal Block kept is eaten as it ends (the random differential's wide2
# b274-t4: Showdown's Update after Heal Block's residual)
def test_l137_sitrus_after_heal_block_ends():
    a, b = _random_position("random_battle_teams_wide2.jsonl", 274, 4, 30000)
    assert any("|-enditem|p2a: Tropius|Sitrus Berry|[eat]" in x for x in b["state"]["log"])
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L139 (doc/engine-diff.md): Pickpocket takes the attacker's item after the hit popped its own Air
# Balloon (Showdown: the balloon goes on the damaging hit, Pickpocket after the move); the
# engine's Pickpocket saw the balloon still there
def test_l139_pickpocket_after_air_balloon():
    tink = _setter("Tinkaton", "Pickpocket", "Air Balloon", "- Stealth Rock\n- Gigaton Hammer\n- Encore\n- Protect")
    gambit = _setter("Kingambit", "Supreme Overlord", "Leftovers", "- Iron Head\n- Sucker Punch\n- Swords Dance\n- Protect")
    states = ec.run_showdown(tink, gambit, [("move stealthrock", "move ironhead")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "leftovers"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "stealthrock", "ironhead")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L140 (doc/engine-diff.md): Fling, its power and effect its user's item's, the item used up even
# into Protect, no Life Orb recoil after it (Showdown's onPrepareHit and fling volatile); the
# engine's Fling had no power and kept the item
@pytest.mark.parametrize("item,foe_move", [
    ("Toxic Orb", "roost"), ("Rocky Helmet", "roost"), ("Life Orb", "roost"), ("King's Rock", "roost"),
    ("Iron Ball", "roost"), ("Toxic Orb", "protect"),
])  # fmt: skip
def test_l140_fling(item, foe_move):
    user = _setter("Gliscor", "Hyper Cutter", item, "- Fling\n- Earthquake\n- Protect\n- Toxic")
    states = ec.run_showdown(user.replace("Careful Nature", "Jolly Nature"), CORVIKNIGHT.replace("- Defog", "- Protect"),
                             [("move fling", f"move {foe_move}")])  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "fling", foe_move)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


WALKING_WAKE = """Walking Wake @ Booster Energy
Ability: Protosynthesis
Tera Type: Water
EVs: 4 Atk / 252 SpA / 252 Spe
Timid Nature
- Draco Meteor
- Calm Mind
- Flamethrower
- Protect"""


# L141 (doc/engine-diff.md): Protosynthesis follows the sun whenever it changes: on with the sun a
# move or a switch-in sets, off when another weather replaces it, and a held Booster Energy then
# goes off with the best stat as it is (Showdown's onWeatherChange, Booster Energy's onUpdate);
# the engine only looked at a switch-in and the sun's end of turn
@pytest.mark.parametrize("case", ["sunny day", "chilly reception", "sun ends"])
def test_l141_protosynthesis_follows_the_weather(case):
    wake = WALKING_WAKE.replace("Booster Energy", "Leftovers") if case == "sunny day" else WALKING_WAKE
    if case == "sunny day":
        foe = _setter("Torkoal", "White Smoke", "Leftovers", "- Sunny Day\n- Rapid Spin\n- Lava Plume\n- Protect")
        turns, k = [("move protect", "move sunnyday")], 0
    elif case == "chilly reception":
        foe = _setter("Torkoal", "Drought", "Leftovers", "- Sunny Day\n- Chilly Reception\n- Lava Plume\n- Protect")
        turns, k = [("move protect", "move chillyreception")], 0
    else:
        foe = _setter("Torkoal", "White Smoke", "Leftovers", "- Sunny Day\n- Rapid Spin\n- Lava Plume\n- Protect")
        # (Blissey first: the Booster Energy stays held under the sun)
        wake = BLISSEY + "\n\n" + WALKING_WAKE
        turns = [("move protect", "move sunnyday"), ("switch 2", "move rapidspin"),
                 ("move dracometeor", "move rapidspin"), ("move calmmind", "move rapidspin"),
                 ("move protect", "move rapidspin")]  # fmt: skip
        k = 4
    states = ec.run_showdown(wake, foe, turns)
    if case == "sun ends":  # the sun's Protosynthesis (Sp. Atk) ends, the Booster Energy's is Speed
        assert any("protosynthesisspe" in x for x in states[k + 1]["log"])
    c1, c2 = turns[k][0].split()[1], turns[k][1].split()[1]
    outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, c2)
    assert ec.closest(states[k + 1], outs, (1 + (case == "sun ends"), 1), hp=True)["diff"] == {}


# L142 (doc/engine-diff.md): a drag move that drags nobody (an immune target, a miss) leaves the
# target's move for the turn (Showdown); the engine skipped the slower target's move whenever the
# faster one's move was a drag
def test_l142_failed_drag_leaves_the_targets_move():
    chomp = _setter("Garchomp", "Rough Skin", "Leftovers", "- Dragon Tail\n- Earthquake\n- Protect\n- Roar")
    clef = _setter("Clefable", "Magic Guard", "Leftovers", "- Trick Room\n- Moonblast\n- Protect\n- Moonlight")
    states = ec.run_showdown(chomp, clef + "\n\n" + BLISSEY, [("move dragontail", "move trickroom")])
    assert "trickroom" in states[1]["field"]["pseudo"]  # (Trick Room's -7 after Dragon Tail's -6)
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "dragontail", "trickroom")
    assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}


# L143 (doc/engine-diff.md): a Lum Berry cures the confusion an ended Outrage leaves at once
# (Showdown's onUpdate); the engine's confusion stayed with the berry until the next move
def test_l143_lum_berry_cures_the_fatigue():
    hax = """Haxorus @ Lum Berry
Ability: Mold Breaker
Tera Type: Dragon
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Outrage
- Earthquake
- Dragon Dance
- Close Combat"""
    states = ec.run_showdown(hax, BLISSEY, [("move outrage", "move softboiled")] * 3)
    k = next(k for k in range(1, 4) if any("confusion|[fatigue]" in x for x in states[k]["log"]))
    assert states[k]["sides"][0]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[k - 1]), "outrage", "softboiled")
    assert ec.closest(states[k], outs, (1, 1), hp=True)["diff"] == {}


# L144 (doc/engine-diff.md): an Eject Pack goes off after a stat its foe's move's secondary lowered
# (Acid Spray's Sp. Def -2; Showdown's onAfterBoost): its holder switches out, its own move lost;
# the engine checked only the move's own stat drops
def test_l144_eject_pack_after_a_secondary_drop():
    user = _setter("Glimmora", "Toxic Debris", "Leftovers", "- Acid Spray\n- Earth Power\n- Spikes\n- Protect")
    goon = _setter("Amoonguss", "Regenerator", "Eject Pack", "- Spore\n- Giga Drain\n- Clear Smog\n- Protect")
    states = ec.run_showdown(user.replace("Careful", "Timid"), goon.replace("Careful", "Relaxed") + "\n\n" + BLISSEY,
                             [("move acidspray", "move gigadrain")])  # fmt: skip
    assert states[1]["sides"][1]["request"] == "switch"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "acidspray", "gigadrain")
    assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}


# L145 (doc/engine-diff.md): Alluring Voice confuses / Burning Jealousy burns a target whose stats
# were raised this turn (Showdown's statsRaisedThisTurn: its Swords Dance before; Dauntless
# Shield as it came in; Protect: a control); the engine's had no such effect
@pytest.mark.parametrize("move,foe_move", [
    ("alluringvoice", "swordsdance"), ("burningjealousy", "swordsdance"), ("alluringvoice", "protect"),
])  # fmt: skip
def test_l145_stats_raised_this_turn(move, foe_move):
    user = _setter("Skeledirge", "Unaware", "Leftovers", "- Alluring Voice\n- Burning Jealousy\n- Slack Off\n- Protect")
    chomp = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Protect\n- Earthquake\n- Roar")
    states = ec.run_showdown(user, chomp.replace("Careful", "Jolly"), [(f"move {move}", f"move {foe_move}")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), move, foe_move)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


WEEZING_NG = """Weezing-Galar @ Leftovers
Ability: Neutralizing Gas
Tera Type: Steel
EVs: 4 HP / 252 SpA / 252 Spe
Timid Nature
- Strange Steam
- Protect
- Defog
- Will-O-Wisp"""


# L146 (doc/engine-diff.md): Neutralizing Gas ends as its holder faints or leaves, and the other
# active's ability starts again (Showdown's onEnd: Moxie after the KO, Drought's sun, Dauntless
# Shield; Intimidate hits nobody); the engine kept them suppressed by a fainted holder and never
# restarted them
@pytest.mark.parametrize("case", ["moxie", "drought", "dauntless shield"])
def test_l146_abilities_after_neutralizing_gas(case):
    weez = WEEZING_NG
    if case == "moxie":
        foe = """Gyarados @ Leftovers
Ability: Moxie
Tera Type: Ground
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Waterfall
- Earthquake
- Dragon Dance
- Protect"""
        states = ec.run_showdown(weez.replace("Focus Sash", "Leftovers").replace("4 HP / ", "") + "\n\n" + BLISSEY,
                                 foe, [("move protect", "move dragondance"), ("move defog", "move earthquake")])  # fmt: skip
        k, c = 1, ("defog", "earthquake")
        assert any("|faint|p1a: Weezing" in x for x in states[2]["log"])
    else:
        mon = (_setter("Torkoal", "Drought", "Leftovers", "- Rapid Spin\n- Lava Plume\n- Protect\n- Yawn")
               if case == "drought" else
               _setter("Zamazenta", "Dauntless Shield", "Leftovers", "- Body Press\n- Iron Defense\n- Protect\n- Roar"))  # fmt: skip
        states = ec.run_showdown(weez + "\n\n" + BLISSEY, mon, [("switch 2", "move protect")])
        k, c = 0, ("blissey", "protect")
    outs = ec.engine_outcomes(ec.engine_state(states[k]), *c)
    assert ec.closest(states[k + 1], outs, (2, 1), hp=True)["diff"] == {}


# L147 (doc/engine-diff.md): Showdown's Update -- the berries' onUpdate after each hit (after its
# secondaries), after each action and after the weather's residual -- one place in the engine: a
# hit's own Heal Block (Psychic Noise) comes before the Sitrus Berry it takes to half (the engine
# ate the berry at the damage, before the secondaries)
def test_l147_update_after_the_secondaries():
    user = _setter("Latios", "Levitate", "Leftovers", "- Psychic Noise\n- Recover\n- Protect\n- Draco Meteor")
    user = user.replace("Careful", "Modest").replace("4 Atk / 252 SpD", "252 SpA / 4 SpD")
    foe = """Azumarill @ Sitrus Berry
Ability: Huge Power
Tera Type: Water
EVs: 4 HP / 252 Atk / 252 Spe
Adamant Nature
- Belly Drum
- Aqua Jet
- Play Rough
- Protect"""
    states = ec.run_showdown(user, foe, [("move psychicnoise", "move bellydrum")])
    assert states[1]["sides"][1]["mons"][0]["item"] == "sitrusberry"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "psychicnoise", "bellydrum")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L147: the Update comes before a drag move's drag too (the random differential's wide2 b66-t11:
# Dragon Tail takes Salazzle under half, its Sitrus Berry is eaten before it is dragged out)
def test_l147_update_before_the_drag():
    a, b = _random_position("random_battle_teams_wide2.jsonl", 66, 11, 30000)
    assert any("|-enditem|p2a: Salazzle|Sitrus Berry|[eat]" in x for x in b["state"]["log"])
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L148 (doc/engine-diff.md): Showdown's WeatherChange / TerrainChange events (setWeather /
# setTerrain): a terrain move sets off the foe's seed at once, Snowscape brings Ice Face back;
# the engine only looked at them on a switch-in (the seed: also before its holder's move)
@pytest.mark.parametrize("case", ["electric seed", "ice face"])
def test_l148_field_change_events(case):
    if case == "electric seed":
        user = _setter("Jolteon", "Volt Absorb", "Leftovers", "- Electric Terrain\n- Thunderbolt\n- Protect\n- Wish")
        user = user.replace("Careful", "Timid")
        foe = _setter("Corviknight", "Pressure", "Electric Seed", "- Defog\n- Roost\n- Brave Bird\n- U-turn")
        turns, k, c = [("move electricterrain", "move defog")], 0, ("electricterrain", "defog")
        states = ec.run_showdown(user, foe, turns)
        assert states[1]["sides"][1]["mons"][0]["item"] == ""
    else:
        # (turn 1: the face takes the Earthquake; turn 2: Snowscape first, the face back takes
        # the slower Hippowdon's Earthquake again)
        eiscue = _setter("Eiscue", "Ice Face", "Leftovers", "- Snowscape\n- Belly Drum\n- Protect\n- Icicle Crash")
        foe = _setter("Hippowdon", "Sand Force", "Leftovers", "- Earthquake\n- Slack Off\n- Protect\n- Roar")
        turns = [("move iciclecrash", "move earthquake"), ("move snowscape", "move earthquake")]
        states = ec.run_showdown(eiscue, foe, turns)
        assert states[1]["sides"][0]["mons"][0]["species"] == "eiscuenoice"
        assert states[2]["sides"][0]["mons"][0]["hp"] == states[1]["sides"][0]["mons"][0]["hp"]
        k, c = 1, ("snowscape", "earthquake")
    outs = ec.engine_outcomes(ec.engine_state(states[k]), *c)
    assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}


# L149 (doc/engine-diff.md): Showdown's boost() -- ChangeBoost (Simple doubles; Ripen a berry's),
# TryBoost (the foe's drops: Big Pecks, Mist; Intimidate: Guard Dog's +1 instead), AfterBoost
# (Rattled after Intimidate), FoeAfterBoost (Opportunist copies the foe's raises after its move);
# the engine had none of them
@pytest.mark.parametrize("case", ["simple", "big pecks", "mist", "guard dog", "rattled", "opportunist",
                                  "ripen"])  # fmt: skip
def test_l149_boost_handlers(case):
    foe = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Earthquake\n- Protect\n- Roar")
    k = 0
    if case == "simple":
        user = _setter("Swoobat", "Simple", "Leftovers", "- Calm Mind\n- Protect\n- Roost\n- Air Slash")
        turns = [("move calmmind", "move protect")]
    elif case == "big pecks":
        user = _setter("Pidgeot", "Big Pecks", "Leftovers", "- Roost\n- Protect\n- Hurricane\n- U-turn")
        foe = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Leer\n- Protect\n- Roar")
        turns = [("move protect", "move swordsdance"), ("move roost", "move leer")]
        k = 1
    elif case == "mist":
        user = _setter("Lapras", "Water Absorb", "Leftovers", "- Mist\n- Protect\n- Freeze-Dry\n- Haze")
        foe = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Scary Face\n- Protect\n- Roar")
        turns = [("move mist", "move swordsdance"), ("move freezedry", "move scaryface")]
        k = 1
    elif case in ("guard dog", "rattled"):
        user = (_setter("Okidogi", "Guard Dog", "Leftovers", "- Bulk Up\n- Drain Punch\n- Protect\n- Knock Off")
                if case == "guard dog" else
                _setter("Sudowoodo", "Rattled", "Leftovers", "- Protect\n- Stealth Rock\n- Head Smash\n- Sucker Punch"))  # fmt: skip
        lando = _setter("Landorus-Therian", "Intimidate", "Leftovers", "- Earthquake\n- U-turn\n- Stealth Rock\n- Protect")
        states = ec.run_showdown(user, foe + "\n\n" + lando, [("move protect", "switch 2")])
        outs = ec.engine_outcomes(ec.engine_state(states[0]), "protect", "landorustherian")
        assert ec.closest(states[1], outs, (1, 2), hp=True)["diff"] == {}
        return
    elif case == "opportunist":
        user = _setter("Espathra", "Opportunist", "Leftovers", "- Calm Mind\n- Protect\n- Roost\n- Lumina Crash")
        turns = [("move roost", "move swordsdance")]
    else:  # ripen: a Kee Berry's +2
        user = _setter("Appletun", "Ripen", "Kee Berry", "- Recover\n- Apple Acid\n- Protect\n- Dragon Pulse")
        foe = foe.replace("- Swords Dance", "- Tackle")
        turns = [("move recover", "move tackle")]
    states = ec.run_showdown(user, foe, turns)
    c = (turns[k][0].split()[1], turns[k][1].split()[1])
    outs = ec.engine_outcomes(ec.engine_state(states[k]), *c)
    assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}


# L150 (doc/engine-diff.md): Showdown's BeforeMove order (sleep / freeze 10, ..., confusion 3,
# attraction 2, paralysis 1): a Rest sleeper's confusion does not count down (the random
# differential's wide b208-t12), a fully paralyzed one's does (wide2 b184-t19); the attraction
# ends with its source fainted (wide b14-t4)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_wide.jsonl", 208, 12, 0),
    ("random_battle_teams_wide2.jsonl", 184, 19, 30000),
    ("random_battle_teams_wide.jsonl", 14, 4, 0),
])  # fmt: skip
def test_l150_before_move_order(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L150: attraction stops its holder half the time (Showdown's attract onBeforeMove); the engine
# never did
def test_l150_attraction_immobilizes():
    user = """Gardevoir @ Leftovers
Ability: Synchronize
Tera Type: Fairy
EVs: 252 HP / 252 SpA / 4 Spe
Modest Nature
- Attract
- Calm Mind
- Protect
- Moonblast"""
    foe = """Garchomp @ Leftovers
Ability: Rough Skin
Tera Type: Dragon
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Swords Dance
- Earthquake
- Protect
- Roar"""
    states = ec.run_showdown(user.replace("Gardevoir @", "Gardevoir (F) @"), foe.replace("Garchomp @", "Garchomp (M) @"),
                             [("move attract", "move swordsdance"), ("move calmmind", "move earthquake")])  # fmt: skip
    assert "attract" in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "calmmind", "earthquake")
    p = {round(o[0], 2) for o in outs}
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}
    assert any(abs(o[0] - 0.5) < 0.01 for o in outs), p


# L151 (doc/engine-diff.md): Showdown's DamagingHit after each hit's own effects -- Rough Skin once
# per hit (the engine also added L50's per-hit extra: twice), Weak Armor / Gooey per hit (the
# engine's were one secondary per move), Stamina after Clear Smog's clear (onHit before it)
@pytest.mark.parametrize("case", ["rough skin", "weak armor", "gooey", "stamina"])
def test_l151_damaging_hit(case):
    cinccino = _attacker("Cinccino", "Skill Link", "Leftovers", "- Tail Slap\n- U-turn\n- Knock Off\n- Tidy Up", "Jolly")
    k, turns = 0, [("move tailslap", "move protect")]
    if case == "rough skin":
        foe = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Earthquake\n- Protect\n- Roar")
        turns = [("move tailslap", "move swordsdance")]
    elif case == "weak armor":
        foe = _setter("Skarmory", "Weak Armor", "Leftovers", "- Roost\n- Spikes\n- Protect\n- Whirlwind")
        turns = [("move tailslap", "move roost")]
    elif case == "gooey":
        foe = _setter("Goodra", "Gooey", "Leftovers", "- Draco Meteor\n- Fire Blast\n- Protect\n- Sludge Bomb")
        turns = [("move tailslap", "move sludgebomb")]
    else:
        cinccino = _setter("Gastrodon", "Storm Drain", "Leftovers", "- Clear Smog\n- Recover\n- Earth Power\n- Scald")
        foe = _setter("Mudsdale", "Stamina", "Leftovers", "- Earthquake\n- Iron Defense\n- Protect\n- Rest")
        turns = [("move recover", "move irondefense"), ("move clearsmog", "move irondefense")]
        k = 1
    states = ec.run_showdown(cinccino, foe, turns)
    c = (turns[k][0].split()[1], turns[k][1].split()[1])
    outs = ec.engine_outcomes(ec.engine_state(states[k]), *c)
    assert ec.closest(states[k + 1], outs, (1, 1), hp=True)["diff"] == {}


# L151's random-differential positions: Rocky Helmet before Magician takes it (forum b12-t2),
# Gooey on an attacker behind its Substitute (offmeta b19-t31), Rocky Helmet on a hit Ice Face
# took (wide b139-t1), Rapid Spin clearing the Toxic Spikes Toxic Debris just set (main b114-t30),
# Triple Axel's growing hits knocking out at the third (wide2 b261-t2)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_forum.jsonl", 12, 2, 50000),
    ("random_battle_teams_offmeta.jsonl", 19, 31, 0),
    ("random_battle_teams_wide.jsonl", 139, 1, 0),
    ("random_battle_teams.jsonl", 114, 30, 0),
    ("random_battle_teams_wide2.jsonl", 261, 2, 30000),
])  # fmt: skip
def test_l151_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L152 (doc/engine-diff.md): a resist berry is eaten by the hit it halves (Showdown's
# onSourceModifyDamage): not into Protect, not when its foe is fully paralyzed (the random
# differential's wide b103-t33); the engine ate it as the move started. A hit: a control
@pytest.mark.parametrize("case", ["protect", "hit"])
def test_l152_resist_berry_on_the_hit(case):
    chomp = _setter("Garchomp", "Rough Skin", "Leftovers", "- Dragon Claw\n- Earthquake\n- Protect\n- Roar")
    dnite = _setter("Dragonite", "Multiscale", "Haban Berry", "- Roost\n- Protect\n- Extreme Speed\n- Dragon Dance")
    foe_move = "protect" if case == "protect" else "roost"
    states = ec.run_showdown(chomp.replace("Careful", "Jolly"), dnite, [("move dragonclaw", f"move {foe_move}")])
    assert (states[1]["sides"][1]["mons"][0]["item"] == "habanberry") == (case == "protect")
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "dragonclaw", foe_move)
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l152_resist_berry_kept_through_full_paralysis():
    a, b = _random_position("random_battle_teams_wide.jsonl", 103, 33)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L153 (doc/engine-diff.md): a lock its user could not move in ends with the turn (Showdown's
# lockedmove: only a use renews it; wide b146-t45: fully paralyzed); Pickpocket takes a U-turn
# user's item (only an Eject Button's switch stops it; wide2 b40-t25); a Custap Berry goes as its
# holder moves while the foe switches (random b12-t17, seed10k b57-t25)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_wide.jsonl", 146, 45, 0),
    ("random_battle_teams_wide2.jsonl", 40, 25, 30000),
    ("random_battle_teams_random.jsonl", 12, 17, 0),
    ("random_battle_teams.jsonl", 57, 25, 10000),
])  # fmt: skip
def test_l153_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L154 (doc/engine-diff.md): Sniper's crit 1.5 x (random b59-t3), Slush Rush in snow (wide200
# b90-t4), no tera power floor for Counter (seed10k b39-t11), the order after Terastallization's
# Embody Aspect Speed (random b128-t11), Embody Aspect whatever Ogerpon's tera type (seed10k
# b114-t9)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_random.jsonl", 59, 3, 0),
    ("random_battle_teams_wide200.jsonl", 90, 4, 40000),
    ("random_battle_teams.jsonl", 39, 11, 10000),
    ("random_battle_teams_random.jsonl", 128, 11, 0),
    ("random_battle_teams.jsonl", 114, 9, 10000),
    # (Life Orb's recoil after Counter; Neutralizing Gas stops Sniper and Embody Aspect)
    ("random_battle_teams.jsonl", 39, 13, 10000),
    ("random_battle_teams_wide.jsonl", 221, 1, 0),
    ("random_battle_teams_forum.jsonl", 90, 17, 50000),
])  # fmt: skip
def test_l154_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L155 (doc/engine-diff.md): a hit Disguise took deals nothing even when the move's power is its
# own (Heavy Slam: offmeta b80-t1); a reflected Strength Sap heals the reflector (wide2
# b115-t15); Mirror Coat's damage on its target's Substitute (wide b7-t7)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_offmeta.jsonl", 80, 1, 0),
    ("random_battle_teams_wide2.jsonl", 115, 15, 30000),
    ("random_battle_teams_wide.jsonl", 7, 7, 0),
])  # fmt: skip
def test_l155_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L156 (doc/engine-diff.md): Disguise takes a multi-hit move's first hit only (main b176-t18:
# Rock Blast); no drain for a user Destiny Bond took down (wide2 b146-t8); Supercell Slam into
# Volt Absorb crashes (offmeta b95-t14)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 176, 18, 0),
    ("random_battle_teams_wide2.jsonl", 146, 8, 30000),
    ("random_battle_teams_offmeta.jsonl", 95, 14, 0),
])  # fmt: skip
def test_l156_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L156: Ice Face takes a multi-hit move's first hit only (Rock Blast's later hits damage)
def test_l156_ice_face_multi_hit():
    eiscue = _setter("Eiscue", "Ice Face", "Leftovers", "- Belly Drum\n- Icicle Crash\n- Protect\n- Substitute")
    cloyster = _attacker("Cloyster", "Skill Link", "Leftovers", "- Icicle Spear\n- Rock Blast\n- Shell Smash\n- Spikes", "Jolly")
    states = ec.run_showdown(cloyster, eiscue, [("move rockblast", "move bellydrum")])
    assert states[1]["sides"][1]["mons"][0]["hp"] < states[0]["sides"][1]["mons"][0]["hp"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "rockblast", "bellydrum")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L157 (doc/engine-diff.md): the benched Future Sight user's Sp. Atk under its active ally's Vessel
# of Ruin (the random differential's wide b252-t15: Ting-Lu; Showdown's onAnyModifySpA)
def test_l157_future_sight_under_an_allys_vessel_of_ruin():
    a, b = _random_position("random_battle_teams_wide.jsonl", 252, 15)
    assert any("|-end|p1a: Moltres|move: Future Sight" in x for x in b["state"]["log"])
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L157's control: the ally's Vessel of Ruin under the foe's Neutralizing Gas (wide b299-t13)
def test_l157_vessel_of_ruin_under_neutralizing_gas():
    a, b = _random_position("random_battle_teams_wide.jsonl", 299, 13)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L158 (doc/engine-diff.md): Relic Song turns Meloetta into Pirouette after a hit (stats and types;
# Showdown's onAfterMoveSecondarySelf): seed10k b111-t1, wide2 b190-t4 / b55-t3, wide200 b75-t27
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 111, 1, 10000),
    ("random_battle_teams_wide2.jsonl", 190, 4, 30000),
    ("random_battle_teams_wide2.jsonl", 55, 3, 30000),
    ("random_battle_teams_wide200.jsonl", 75, 27, 40000),
])  # fmt: skip
def test_l158_relic_song(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L159 (doc/engine-diff.md): Cheek Pouch heals a third with the berry it eats (seed10k b200-t22:
# Greedent's Sitrus); a fixed damage into Disguise deals nothing (random b93-t4: Ruination)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 200, 22, 10000),
    ("random_battle_teams_random.jsonl", 93, 4, 0),
])  # fmt: skip
def test_l159_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L160 (doc/engine-diff.md): the attacker's Unaware whatever the target's ability (random b49-t4:
# Dondozo's Body Press into a Mold Breaker Haxorus at -2 Def); no heal under Heal Block, an
# absorbing ability's too (wide b283-t17: Water Absorb)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_random.jsonl", 49, 4, 0),
    ("random_battle_teams_wide.jsonl", 283, 17, 0),
])  # fmt: skip
def test_l160_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L161 (doc/engine-diff.md): moves whose Showdown callbacks the engine lacked: Venoshock x2 on a
# poisoned target, Infernal Parade x2 on a status, the storms' sure hit in rain, Shell Side Arm
# physical (contact: Rocky Helmet) when that deals more
@pytest.mark.parametrize("move", ["venoshock", "infernalparade"])
def test_l161_doubled_on_a_status(move):
    user = _setter("Toxapex", "Regenerator", "Black Sludge", "- Toxic\n- Venoshock\n- Infernal Parade\n- Recover")
    user = user.replace("Careful", "Modest").replace("4 Atk / 252 SpD", "252 SpA / 4 SpD")
    foe = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Protect\n- Earthquake\n- Roar")
    states = ec.run_showdown(user, foe, [("move toxic", "move swordsdance"), (f"move {move}", "move swordsdance")])
    assert states[1]["sides"][1]["mons"][0]["status"] == "tox"
    outs = ec.engine_outcomes(ec.engine_state(states[1]), move, "swordsdance")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


def test_l161_bleakwind_storm_in_rain():
    torn = _setter("Tornadus-Therian", "Regenerator", "Leftovers", "- Bleakwind Storm\n- Rain Dance\n- U-turn\n- Taunt")
    # (the misses forced in Showdown: it still hits; the engine has no miss branch)
    states = ec.run_showdown(torn, CORVIKNIGHT, [("move raindance", "move roost"), ("move bleakwindstorm", "move defog")],
                             force_random=False)  # fmt: skip
    hp = states[1]["sides"][1]["mons"][0]["hp"]
    assert states[2]["sides"][1]["mons"][0]["hp"] < hp
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "bleakwindstorm", "defog")
    assert sum(o[0] for o in outs if o[1].side_two.pokemon[0].hp == hp) < 0.01


def test_l161_shell_side_arm_physical():
    user = _attacker("Slowbro-Galar", "Regenerator", "Leftovers", "- Shell Side Arm\n- Psychic\n- Flamethrower\n- Slack Off", "Adamant")
    blissey = BLISSEY.replace("Heavy-Duty Boots", "Rocky Helmet").replace("252 Def / 4 SpD", "4 Def / 252 SpD")
    states = ec.run_showdown(user, blissey.replace("Bold", "Calm"), [("move shellsidearm", "move calmmind")])
    assert any("Rocky Helmet" in x for x in states[1]["log"])  # (physical: contact)
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "shellsidearm", "calmmind")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L162 (doc/engine-diff.md): abilities / items the engine never implemented that the team pools
# use: Merciless (a sure crit on a poisoned target), Steadfast (Speed +1 when flinched), Lagging
# Tail (last in its bracket), Anger Shell (main b100-t13), Quick Draw (3/10 first in its bracket)
def test_l162_merciless():
    pex = _setter("Toxapex", "Merciless", "Black Sludge", "- Toxic\n- Liquidation\n- Recover\n- Haze")
    foe = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Protect\n- Earthquake\n- Roar")
    states = ec.run_showdown(pex, foe, [("move toxic", "move swordsdance"), ("move liquidation", "move swordsdance")])
    assert any("|-crit|" in x for x in states[2]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "liquidation", "swordsdance")
    res = ec.closest(states[2], outs, (1, 1), hp=True)
    assert res["diff"] == {} and res["p"] > 0.5


def test_l162_steadfast():
    mach = _attacker("Mienshao", "Steadfast", "Leftovers", "- U-turn\n- Close Combat\n- Fake Out\n- Knock Off", "Jolly")
    foe = _attacker("Weavile", "Pressure", "Leftovers", "- Fake Out\n- Ice Shard\n- Knock Off\n- Swords Dance", "Jolly")
    states = ec.run_showdown(mach.replace("Jolly", "Adamant"), foe, [("move knockoff", "move fakeout")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spe"] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "knockoff", "fakeout")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l162_lagging_tail():
    slow = _setter("Hippowdon", "Sand Stream", "Lagging Tail", "- Slack Off\n- Earthquake\n- Stealth Rock\n- Whirlwind")
    fast = _attacker("Weavile", "Pressure", "Leftovers", "- Fake Out\n- Ice Shard\n- Knock Off\n- Swords Dance", "Jolly")
    # (Hippowdon is slower anyway: Lagging Tail on the faster one)
    states = ec.run_showdown(fast.replace("Leftovers", "Lagging Tail"), slow.replace("Lagging Tail", "Leftovers"),
                             [("move knockoff", "move earthquake")])  # fmt: skip
    log = [x for x in states[1]["log"] if x.startswith("|move|")]
    assert log[0].startswith("|move|p2a")
    # (the final state is the same either way: the engine's order itself)
    e = ec.engine_state(states[0])
    for x in pe.generate_instructions(e, "knockoff", "earthquake"):
        assert [str(i) for i in x.instruction_list if str(i).startswith("Acted")][:1] == ["Acted: SideTwo"]


def test_l162_anger_shell():
    a, b = _random_position("random_battle_teams.jsonl", 100, 13)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


def test_l162_quick_draw_chance():
    """The engine's chance that the slower Quick Draw holder moves first with a damaging move: 3/10
    (Showdown's randomChance(3, 10)); with a status move: never."""
    slow = _setter("Slowbro-Galar", "Quick Draw", "Leftovers", "- Shell Side Arm\n- Psychic\n- Calm Mind\n- Slack Off")
    fast = _attacker("Weavile", "Pressure", "Leftovers", "- Fake Out\n- Ice Shard\n- Knock Off\n- Swords Dance", "Jolly")
    states = ec.run_showdown(slow, fast, [])
    e = ec.engine_state(states[0])
    for move, want in (("psychic", 0.3), ("calmmind", 0.0)):
        first = sum(x.percentage for x in pe.generate_instructions(e, move, "swordsdance")
                    if [str(i) for i in x.instruction_list if str(i).startswith("Acted")][:1] == ["Acted: SideOne"])
        assert first / 100 == pytest.approx(want, abs=1e-3), move


# L163 (doc/engine-diff.md): two new Pokemon fields -- the times a move hit it (Rage Fist's 50 more
# per time: wide200 b192-t36 / b192-t28, main b41-t21) and the gender (Cute Charm's attraction on
# a contact attacker of the other gender: wide b14-t3; Attract fails between the same genders)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_wide200.jsonl", 192, 36, 40000),
    ("random_battle_teams_wide200.jsonl", 192, 28, 40000),
    ("random_battle_teams.jsonl", 41, 21, 0),
    ("random_battle_teams_wide.jsonl", 14, 3, 0),
])  # fmt: skip
def test_l163_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


def test_l163_attract_same_gender_fails():
    user = _setter("Gardevoir", "Synchronize", "Leftovers", "- Attract\n- Calm Mind\n- Protect\n- Moonblast")
    foe = _setter("Garchomp", "Rough Skin", "Leftovers", "- Swords Dance\n- Earthquake\n- Protect\n- Roar")
    states = ec.run_showdown(user.replace("Gardevoir @", "Gardevoir (F) @"), foe.replace("Garchomp @", "Garchomp (F) @"),
                             [("move attract", "move swordsdance")])  # fmt: skip
    assert "attract" not in states[1]["sides"][1]["mons"][0]["volatiles"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "attract", "swordsdance")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L164 (doc/engine-diff.md): a gem is used up by the hit (Showdown's onSourceTryPrimaryHit: not on
# a miss -- offmeta b76-t17); Encore ends with its move out of PP (wide b152-t19, wide2 b199-t58)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_offmeta.jsonl", 76, 17, 0),
    ("random_battle_teams_wide.jsonl", 152, 19, 0),
    ("random_battle_teams_wide2.jsonl", 199, 58, 30000),
])  # fmt: skip
def test_l164_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L164's control: a gem that hits is used up
def test_l164_gem_on_a_hit():
    user = _attacker("Dragonite", "Inner Focus", "Normal Gem", "- Extreme Speed\n- Earthquake\n- Roost\n- Dragon Dance", "Adamant")
    states = ec.run_showdown(user, CORVIKNIGHT, [("move extremespeed", "move roost")])
    assert states[1]["sides"][0]["mons"][0]["item"] == ""
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "extremespeed", "roost")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L165 (doc/engine-diff.md): Meteor Beam's charging Sp. Atk +1 after the BeforeMove (none in a full
# paralysis: wide2 b278-t36; a Power Herb's at once, into a Protect too: main b168-t31); Metronome's count only after a use that worked (seed10k b70-t18 /
# t19: a failed Sucker Punch); Sparkling Aria's volatile goes as the move ends (wide2 b138-t41 /
# t53)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_wide2.jsonl", 278, 36, 30000),
    ("random_battle_teams.jsonl", 168, 31, 0),
    ("random_battle_teams.jsonl", 70, 18, 10000),
    ("random_battle_teams.jsonl", 70, 19, 10000),
    ("random_battle_teams_wide2.jsonl", 138, 41, 30000),
    ("random_battle_teams_wide2.jsonl", 138, 53, 30000),
])  # fmt: skip
def test_l165_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L166 (doc/engine-diff.md): Revival Blessing, a pivot's decision: the user picks a fainted
# Pokemon (Showdown's switch request), back at half its HP on the bench; the foe's move after it
MAGIKARP_PAWMOT = """Magikarp
Ability: Swift Swim
Level: 5
EVs: 4 HP
- Splash

Pawmot
Ability: Volt Absorb
EVs: 252 Spe
Jolly Nature
- Revival Blessing
- Double Shock
- Close Combat
- Nuzzle"""


def test_l166_revival_blessing():
    turns = [("move splash", "move seismictoss"), ("switch 2", ""),
             ("move revivalblessing", "move seismictoss"), ("switch 2", "")]  # fmt: skip
    states = ec.run_showdown(MAGIKARP_PAWMOT, BLISSEY, turns)
    assert states[3]["sides"][0]["request"] == "switch"  # the pick, mid-turn
    assert states[4]["sides"][0]["mons"][0]["hp"] == 9  # Magikarp's 18 / 2
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "revivalblessing", "seismictoss")
    assert ec.closest(states[3], outs, (2, 1), hp=True)["diff"] == {}
    (_, mid), = outs
    r = pe.mcts(mid, 10, 0, 1)  # the pick's options: the fainted one; the foe's move saved
    assert ([x.move_choice for x in r.s1], [x.move_choice for x in r.s2]) == (["switch magikarp"], ["seismictoss"])
    outs = ec.engine_outcomes(mid, "magikarp", "seismictoss")
    assert ec.closest(states[4], outs, (2, 1), hp=True)["diff"] == {}


# L166's control: no fainted Pokemon, it fails (Showdown's onTryHit) and the turn goes on
def test_l166_revival_blessing_fails_without_a_fainted_one():
    states = ec.run_showdown(MAGIKARP_PAWMOT, BLISSEY, [("switch 2", "move calmmind"),
                                                        ("move revivalblessing", "move seismictoss")])  # fmt: skip
    assert any(x.startswith("|-fail|") for x in states[2]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "revivalblessing", "seismictoss")
    assert ec.closest(states[2], outs, (2, 1), hp=True)["diff"] == {}


# L167 (doc/engine-diff.md): Copycat uses the battle's last move (Showdown's battle.lastMove: the
# move that ran last, either side's; kept in the engine's state, set as each move starts)
BLISSEY_COPYCAT = BLISSEY.replace("- Calm Mind", "- Copycat")
DRAGAPULT_COPYCAT = """Dragapult @ Leftovers
Ability: Infiltrator
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Copycat
- Dragon Dance
- Draco Meteor
- Calm Mind"""


def test_l167_copycat_copies_the_foes_move_this_turn():
    states = ec.run_showdown(BLISSEY_COPYCAT, DRAGAPULT_COPYCAT, [("move copycat", "move dragondance")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["atk"] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "copycat", "dragondance")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


def test_l167_copycat_copies_the_last_move_of_last_turn():
    turns = [("move dragondance", "move protect"), ("move dragondance", "move seismictoss"),
             ("move copycat", "move protect")]  # fmt: skip
    states = ec.run_showdown(DRAGAPULT_COPYCAT, BLISSEY, turns)
    assert states[2]["last_move"] == "seismictoss"  # the slower Blissey's, last
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "copycat", "protect")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


# L167's control: a move it cannot copy (Counter, last: Showdown's failcopycat), it fails
def test_l167_copycat_fails_on_counter():
    states = ec.run_showdown(DRAGAPULT_COPYCAT, BLISSEY.replace("- Calm Mind", "- Counter"),
                             [("move dragondance", "move counter"), ("move copycat", "move seismictoss")])  # fmt: skip
    assert states[1]["last_move"] == "counter"
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "copycat", "seismictoss")
    assert ec.closest(states[2], outs, (1, 1), hp=True)["diff"] == {}


# L167 in the random differential: the foe's move this turn (main b259-t6: a Substitute that failed
# still counts; offmeta b60-t1), the last move of last turn (main b259-t15: a Chilling Water of a mon
# no longer in; main b9-t12; offmeta b101-t16; wide2 b110-t3: its user's own Nasty Plot)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 259, 6, 0),
    ("random_battle_teams.jsonl", 259, 15, 0),
    ("random_battle_teams.jsonl", 9, 12, 0),
    ("random_battle_teams_offmeta.jsonl", 60, 1, 0),
    ("random_battle_teams_offmeta.jsonl", 101, 16, 0),
    ("random_battle_teams_wide2.jsonl", 110, 3, 30000),
])  # fmt: skip
def test_l167_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L168 (doc/engine-diff.md): Future Sight's hit at the end of the turn is a move's hit: it can
# crit (1 in 24: the target's raised Sp. Def left out; main b211-t11 / b236-t29, seed10k b37-t19,
# ...) and a Substitute takes it (wide200 b40-t13)
BLISSEY_CM_SUB = BLISSEY.replace("- Protect", "- Substitute")


def test_l168_future_sight_crit():
    turns = [("move futuresight", "move calmmind"), ("move slackoff", "move calmmind"),
             ("move slackoff", "move calmmind")]  # fmt: skip
    states = ec.run_showdown(SLOWKING_FUTURE, BLISSEY_CM_SUB, turns, force_random=True)
    assert any(x.startswith("|-crit|") for x in states[3]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "slackoff", "calmmind")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


def test_l168_future_sight_into_a_substitute():
    turns = [("move futuresight", "move calmmind"), ("move slackoff", "move calmmind"),
             ("move slackoff", "move substitute")]  # fmt: skip
    states = ec.run_showdown(SLOWKING_FUTURE, BLISSEY_CM_SUB, turns)
    assert any(x.startswith("|-activate|p2a: Blissey|move: Substitute|[damage]") for x in states[3]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "slackoff", "substitute")
    assert ec.closest(states[3], outs, (1, 1), hp=True)["diff"] == {}


# L169 (doc/engine-diff.md): the screens end after Future Sight's hit (Showdown's residual orders
# 26 and 3): the hit of a Light Screen's last turn is still halved (wide b176-t38); the target's
# expected end-of-turn loss counts the hit (a move's surviving rolls split there: forum b61-t17)
BLISSEY_SCREEN = BLISSEY.replace("- Seismic Toss", "- Light Screen")


def test_l169_future_sight_on_a_screens_last_turn():
    turns = [("move slackoff", "move lightscreen"), ("move slackoff", "move calmmind"),
             ("move futuresight", "move calmmind"), ("move slackoff", "move calmmind"),
             ("move slackoff", "move softboiled")]  # fmt: skip
    states = ec.run_showdown(SLOWKING_FUTURE, BLISSEY_SCREEN, turns)
    assert "lightscreen" in states[4]["sides"][1]["conditions"]
    assert "lightscreen" not in states[5]["sides"][1]["conditions"]
    assert any("move: Future Sight" in x for x in states[5]["log"])
    assert not any(x.startswith("|-miss|") for x in states[5]["log"])
    outs = ec.engine_outcomes(ec.engine_state(states[4]), "slackoff", "softboiled")
    assert ec.closest(states[5], outs, (1, 1), hp=True)["diff"] == {}


@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_wide.jsonl", 176, 38, 0),
    ("random_battle_teams_forum.jsonl", 61, 17, 50000),
])  # fmt: skip
def test_l169_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L170 (doc/engine-diff.md): Counter / Mirror Coat / Metal Burst's hit is a damaging hit (Rocky
# Helmet, Stamina: offmeta b18-t9, random b88-t8); Ceaseless Edge / Stone Axe's hazard after the
# DamagingHit, not when a Rocky Helmet knocked the user out (seed10k b150-t7); a fainted trapper's
# Mean Look / Block / Jaw Lock ends at once (offmeta b199-t25, wide200 b107-t8), its partial trap
# too (random b145-t23: Showdown's is without effect then); a partial trap whose source left does
# nothing (the harness: wide b156-t5)
MUDSDALE_STAMINA = """Mudsdale @ Leftovers
Ability: Stamina
EVs: 252 HP / 252 Atk / 4 Def
Adamant Nature
- Rapid Spin
- Rest
- Heavy Slam
- Body Press"""


def test_l170_counter_into_stamina():
    states = ec.run_showdown(MUDSDALE_STAMINA, BLISSEY.replace("- Calm Mind", "- Counter"),
                             [("move rapidspin", "move counter")])  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["boosts"]["def"] == 1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "rapidspin", "counter")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_offmeta.jsonl", 18, 9, 0),
    ("random_battle_teams_random.jsonl", 88, 8, 0),
    ("random_battle_teams.jsonl", 150, 7, 10000),
    ("random_battle_teams_offmeta.jsonl", 199, 25, 0),
    ("random_battle_teams_wide200.jsonl", 107, 8, 40000),
    ("random_battle_teams_wide.jsonl", 156, 5, 0),
    ("random_battle_teams_random.jsonl", 145, 23, 0),
])  # fmt: skip
def test_l170_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L171 (doc/engine-diff.md): Dancer, after a dance move that did something, the Dancer uses it too
# at once (Showdown's runMove with externalMove; offmeta b137-t2 / b160-t6 / b160-t8, wide b52-t27)
ORICORIO = """Oricorio-Pom-Pom @ Heavy-Duty Boots
Ability: Dancer
EVs: 252 HP / 4 SpA / 252 Spe
Timid Nature
- Revelation Dance
- Quiver Dance
- Roost
- Hurricane"""
GARCHOMP_SD = """Garchomp @ Leftovers
Ability: Rough Skin
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Swords Dance
- Earthquake
- Scale Shot
- Stealth Rock"""


def test_l171_dancer_copies_swords_dance():
    states = ec.run_showdown(ORICORIO, GARCHOMP_SD, [("move roost", "move swordsdance")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["atk"] == 2
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "roost", "swordsdance")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_offmeta.jsonl", 137, 2, 0),
    ("random_battle_teams_offmeta.jsonl", 160, 6, 0),
    ("random_battle_teams_offmeta.jsonl", 160, 8, 0),
    ("random_battle_teams_wide.jsonl", 52, 27, 0),
])  # fmt: skip
def test_l171_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L172 (doc/engine-diff.md): a transformed mon's copied ability starts (Showdown's setAbility with
# isTransform: Imposter into an Intimidate; random b53-t11 Sand Stream, wide2 b61-t6 Dauntless
# Shield), no typechange into its own types (wide b73-t9); Supersweet Syrup (random b160-t23,
# wide2 b30-t21)
LANDO = """Landorus-Therian @ Leftovers
Ability: Intimidate
EVs: 252 HP / 252 Def / 4 SpD
Impish Nature
- Stealth Rock
- Earthquake
- U-turn
- Taunt"""
DITTO_BACK = """Blissey @ Heavy-Duty Boots
Ability: Natural Cure
EVs: 252 HP / 252 Def / 4 SpD
Bold Nature
- Soft-Boiled
- Seismic Toss

Ditto @ Choice Scarf
Ability: Imposter
EVs: 252 HP / 4 Def / 252 Spe
Relaxed Nature
- Transform"""
HYDRAPPLE_BACK = DITTO_BACK.split("\n\n")[0] + """

Hydrapple @ Leftovers
Ability: Supersweet Syrup
EVs: 252 HP / 252 SpD / 4 SpA
Calm Nature
- Draco Meteor
- Giga Drain"""


def test_l172_imposter_copies_intimidate():
    states = ec.run_showdown(DITTO_BACK, LANDO, [("switch 2", "move stealthrock")])
    assert states[1]["sides"][1]["mons"][0]["boosts"]["atk"] == -1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "ditto", "stealthrock")
    assert ec.closest(states[1], outs, (2, 1), hp=True)["diff"] == {}


def test_l172_supersweet_syrup():
    states = ec.run_showdown(HYDRAPPLE_BACK, LANDO, [("switch 2", "move stealthrock")])
    assert states[1]["sides"][1]["mons"][0]["boosts"]["evasion"] == -1
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "hydrapple", "stealthrock")
    assert ec.closest(states[1], outs, (2, 1), hp=True)["diff"] == {}


@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_random.jsonl", 53, 11, 0),
    ("random_battle_teams_wide2.jsonl", 61, 6, 30000),
    ("random_battle_teams_wide.jsonl", 73, 9, 0),
    ("random_battle_teams_random.jsonl", 160, 23, 0),
    ("random_battle_teams_wide2.jsonl", 30, 21, 30000),
])  # fmt: skip
def test_l172_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L173 (doc/engine-diff.md): Red Card / Eject Button do not go off on a holder the hit drags out
# (Dragon Tail, Circle Throw: Showdown's forceSwitchFlag; main b237-t11)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 237, 11, 0),
])  # fmt: skip
def test_l173_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


def test_l173_dragon_tail_into_red_card():
    p1 = BLISSEY.replace("Heavy-Duty Boots", "Red Card") + "\n\n" + DITTO_BACK.split("\n\n")[1]
    p2 = GARCHOMP_SD.replace("- Scale Shot", "- Dragon Tail") + "\n\n" + LANDO
    states = ec.run_showdown(p1, p2, [("move softboiled", "move dragontail")])
    assert any(x.startswith("|drag|p1a") for x in states[1]["log"])
    assert states[1]["sides"][0]["mons"][0]["item"] == "redcard"
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "softboiled", "dragontail")
    assert ec.closest(states[1], outs, (2, 2), hp=True)["diff"] == {}


# L174 (doc/engine-diff.md): the tera floor of 60 reads a basePowerCallback's power (Acrobatics
# without an item: 110, no floor; was floored to 60 and then doubled) and the move's priority as
# modified (Grassy Glide in Grassy Terrain: none)
TORNADUS_ACRO = """Tornadus-Therian
Ability: Regenerator
Tera Type: Flying
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Acrobatics
- U-turn
- Taunt
- Knock Off"""


def test_l174_tera_acrobatics_without_an_item():
    # the max damage (Showdown's getDamage probe) once terastallized: within the HP comparison's
    # roll spread the 120 vs 110 power would not show
    states = ec.run_showdown(TORNADUS_ACRO, BLISSEY, [("move taunt terastallize", "move softboiled")],
                             damage_probe=True)  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["terastallized"]
    want = states[1]["damage"]["p1"]["acrobatics"]
    got = pe.calculate_damage(ec.engine_state(states[1]), "acrobatics", "softboiled", True)[0]
    assert got[0] == want  # (the no-crit max; got[1]: the crit)


# L175 (doc/engine-diff.md): a Stellar tera's first move of each type: 2 with STAB, 4915 / 4096
# without, then the usual (Showdown's stellarBoostedTypes; main b185-t19, wide b242-t5); the tera
# floor of 60 after the BasePower modifiers, for a Stellar tera on a type not boosted yet (random
# b123-t11: a 20-power Stored Power); a Stellar tera's own types on defense (Stealth Rock: forum
# b156-t55)
VALIANT_STELLAR = """Iron Valiant @ Booster Energy
Ability: Quark Drive
Tera Type: Stellar
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Moonblast
- Calm Mind
- Shadow Ball
- Thunderbolt"""


def test_l175_stellar_boost_once_per_type():
    turns = [("move calmmind terastallize", "move softboiled"), ("move moonblast", "move softboiled")]
    states = ec.run_showdown(VALIANT_STELLAR, BLISSEY, turns, damage_probe=True)
    for k in (1, 2):  # the first Moonblast boosted (2x), the next not (1.5x)
        want = states[k]["damage"]["p1"]["moonblast"]
        got = pe.calculate_damage(ec.engine_state(states[k]), "moonblast", "softboiled", True)[0]
        assert got[0] == want, k
    assert states[1]["damage"]["p1"]["moonblast"] > states[2]["damage"]["p1"]["moonblast"] * 1.2


def test_l175_tera_floor_after_the_terrain():
    """Grassy Glide's 55 in Grassy Terrain is 71 before the floor (none); out of it, 60."""
    rilla = """Rillaboom @ Life Orb
Ability: Grassy Surge
Tera Type: Grass
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Grassy Glide
- Wood Hammer
- U-turn
- Knock Off"""
    for ability in ("Grassy Surge", "Overgrow"):
        states = ec.run_showdown(rilla.replace("Grassy Surge", ability), BLISSEY,
                                 [("move knockoff terastallize", "move softboiled")], damage_probe=True)  # fmt: skip
        want = states[1]["damage"]["p1"]["grassyglide"]
        got = pe.calculate_damage(ec.engine_state(states[1]), "grassyglide", "softboiled", True)[0]
        assert got[0] == want, ability


@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 185, 19, 0),
    ("random_battle_teams_wide.jsonl", 242, 5, 0),
    ("random_battle_teams_random.jsonl", 123, 11, 0),
    ("random_battle_teams_forum.jsonl", 156, 55, 50000),
])  # fmt: skip
def test_l175_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L176 (doc/engine-diff.md): Magic Powder, the target pure Psychic (seed10k b166-t8 / t10)
HATTERENE_POWDER = """Hatterene @ Leftovers
Ability: Magic Bounce
EVs: 252 HP / 252 SpA / 4 SpD
Quiet Nature
- Magic Powder
- Psychic
- Draining Kiss
- Trick Room"""


def test_l176_magic_powder():
    states = ec.run_showdown(HATTERENE_POWDER, GARCHOMP_SD, [("move magicpowder", "move swordsdance")])
    assert states[1]["sides"][1]["mons"][0]["types"] == ["Psychic"]
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "magicpowder", "swordsdance")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


# L176's control: a Grass type is immune to the powder
def test_l176_magic_powder_on_a_grass_type():
    rilla = TORNADUS_ACRO.replace("Tornadus-Therian", "Rillaboom").replace("Regenerator", "Overgrow")
    states = ec.run_showdown(HATTERENE_POWDER, rilla, [("move magicpowder", "move taunt")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "magicpowder", "taunt")
    assert ec.closest(states[1], outs, (1, 1), hp=True)["diff"] == {}


@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 166, 8, 10000),
    ("random_battle_teams.jsonl", 166, 10, 10000),
])  # fmt: skip
def test_l176_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True)["diff"] == {}


# L177 (doc/engine-diff.md, the full comparison): the PP as Showdown's runMove / useMoveInner --
# every use (was only below 10), past the BeforeMove (not in a full paralysis), not while locked
# (Outrage's later turns), Sleep Talk's own; Pressure one more on a move aimed at its holder (the
# foe, the field, the hazards), not on a self move
def _full(states, k, c1, c2, n=(1, 1)):
    outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, c2)
    return ec.closest(states[k + 1], outs, n, hp=True, full=True, start=states[k])["diff"]


def test_l177_pp_every_use():
    states = ec.run_showdown(BLISSEY, GARCHOMP_SD, [("move calmmind", "move swordsdance")])
    assert states[1]["sides"][0]["mons"][0]["moves"][3]["pp"] == 31
    assert _full(states, 0, "calmmind", "swordsdance") == {}


def test_l177_pp_not_in_a_full_paralysis():
    blissey = BLISSEY.replace("- Protect", "- Thunder Wave")
    turns = [("move dragondance", "move thunderwave"), ("move dragondance", "move calmmind")]
    states = ec.run_showdown(DRAGAPULT_COPYCAT, blissey, turns, force_random=True)
    assert any(x.startswith("|cant|p1a: Dragapult|par") for x in states[2]["log"])
    assert _full(states, 1, "dragondance", "calmmind") == {}


def test_l177_pressure():
    states = ec.run_showdown(GARCHOMP_SD, KYUREM, [("move stealthrock", "move protect"),
                                                    ("move swordsdance", "move protect")])  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["moves"][3]["pp"] == 30  # 32, Pressure: 2
    assert states[2]["sides"][0]["mons"][0]["moves"][0]["pp"] == 31  # Swords Dance: 1
    assert _full(states, 0, "stealthrock", "protect") == {}


def test_l177_pp_outrage_locked():
    garchomp = GARCHOMP_SD.replace("- Scale Shot", "- Outrage")
    states = ec.run_showdown(garchomp, BLISSEY, [("move outrage", "move softboiled"),
                                                  ("move outrage", "move softboiled")])  # fmt: skip
    assert _full(states, 1, "outrage", "softboiled") == {}


def test_l177_options_under_heal_block():
    """Heal Block's moves cannot be chosen (Showdown's onDisableMove)."""
    slowking = SLOWKING_FUTURE.replace("- Sludge Bomb", "- Psychic Noise")
    states = ec.run_showdown(slowking, BLISSEY, [("move psychicnoise", "move calmmind")])
    assert "softboiled" not in ec.showdown_options(states[1]["sides"][1])
    assert _full(states, 0, "psychicnoise", "calmmind") == {}


def test_l177_options_after_imposter():
    """A transformed Ditto's every copied move can be chosen."""
    states = ec.run_showdown(DITTO_BACK, LANDO, [("switch 2", "move stealthrock")])
    assert not [k for k in _full(states, 0, "ditto", "stealthrock", (2, 1)) if "options" in k]


def test_l177_no_second_tera_after_the_tera_mon_fainted():
    p1 = MAGIKARP_PAWMOT.replace("Ability: Swift Swim", "Ability: Swift Swim\nTera Type: Water")
    turns = [("move splash terastallize", "move seismictoss"), ("switch 2", "")]
    states = ec.run_showdown(p1, BLISSEY, turns)
    assert states[2]["sides"][0]["tera_used"]
    assert not any(o.endswith("-tera") for o in ec.showdown_options(states[2]["sides"][0]))
    assert not any(o.endswith("-tera") for o in pe.options(ec.engine_state(states[2]))[0])


# L178 (doc/engine-diff.md): an item used up is its holder's last item (Showdown's useItem: Booster
# Energy, Focus Sash, White Herb, Eject Button, Weakness Policy, the seeds, ...); a popped Air
# Balloon is not (its item set to '')
def _last_items(states, k, c1, c2, n=(1, 1)):
    return {key: v for key, v in _full(states, k, c1, c2, n).items() if "last_item" in key}


def test_l178_booster_energy_used_up():
    tusk = """Great Tusk @ Booster Energy
Ability: Protosynthesis
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Headlong Rush
- Rapid Spin
- Ice Spinner
- Knock Off"""
    states = ec.run_showdown(BLISSEY, CORVIKNIGHT + "\n\n" + tusk, [("move calmmind", "switch 2")])
    assert states[1]["sides"][1]["mons"][1]["last_item"] == "boosterenergy"
    assert _last_items(states, 0, "calmmind", "greattusk", (1, 2)) == {}


def test_l178_focus_sash_and_white_herb_used_up():
    states = ec.run_showdown(MAGIKARP_PAWMOT.replace("Magikarp\n", "Magikarp @ Focus Sash\n"), BLISSEY,
                             [("move splash", "move seismictoss")])  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["last_item"] == "focussash"
    assert _last_items(states, 0, "splash", "seismictoss", (2, 1)) == {}
    gar = GARCHOMP_SD.replace("Garchomp @ Leftovers", "Garchomp @ White Herb").replace("- Scale Shot", "- Close Combat")
    states = ec.run_showdown(gar, BLISSEY, [("move closecombat", "move calmmind")])
    assert states[1]["sides"][0]["mons"][0]["last_item"] == "whiteherb"
    assert _last_items(states, 0, "closecombat", "calmmind") == {}


# L178's control: a popped Air Balloon is no last item
def test_l178_air_balloon_is_not_used():
    gar = GARCHOMP_SD.replace("Garchomp @ Leftovers", "Garchomp @ Air Balloon")
    states = ec.run_showdown(gar, BLISSEY, [("move swordsdance", "move seismictoss")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "" and states[1]["sides"][0]["mons"][0]["last_item"] == ""
    assert _last_items(states, 0, "swordsdance", "seismictoss") == {}


# L179 (doc/engine-diff.md): locks and counts as Showdown's: Outrage's lock with its effect (not
# into an immune target), no Terastallization while locked; a Choice item's lock past the
# BeforeMove (not in a full paralysis), gone with the item (Trick); Taunt's turns for a target that
# came in this turn; Cursed Body's Disable 4 turns; the last used move past the BeforeMove (not a
# flinched move); Imprison
def _keys(d: dict, *names) -> dict:
    return {k: v for k, v in d.items() if any(n in k for n in names)}


def test_l179_outrage_into_an_immune_target_does_not_lock():
    garchomp = GARCHOMP_SD.replace("- Scale Shot", "- Outrage")
    states = ec.run_showdown(garchomp, CLEFABLE, [("move outrage", "move calmmind")])
    assert _keys(_full(states, 0, "outrage", "calmmind"), "options", "volatile") == {}


def test_l179_no_tera_while_locked():
    garchomp = GARCHOMP_SD.replace("- Scale Shot", "- Outrage")
    states = ec.run_showdown(garchomp, BLISSEY, [("move outrage", "move softboiled")])
    assert _keys(_full(states, 0, "outrage", "softboiled"), "options") == {}


def test_l179_choice_lock_not_in_a_full_paralysis_and_gone_with_the_item():
    pult = DRAGAPULT_COPYCAT.replace("Dragapult @ Leftovers", "Dragapult @ Choice Specs")
    blissey = BLISSEY.replace("- Protect", "- Thunder Wave")
    states = ec.run_showdown(pult, blissey, [("move dracometeor", "move thunderwave"),
                                              ("move dracometeor", "move calmmind")], force_random=True)  # fmt: skip
    assert _keys(_full(states, 1, "dracometeor", "calmmind"), "options") == {}
    iv = """Iron Valiant @ Choice Scarf
Ability: Quark Drive
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Trick
- Moonblast
- Shadow Ball
- Thunderbolt"""
    states = ec.run_showdown(iv, BLISSEY, [("move trick", "move calmmind")])
    assert _keys(_full(states, 0, "trick", "calmmind"), "options") == {}


def test_l179_taunt_on_a_mon_that_came_in():
    gren = """Grimmsnarl @ Light Clay
Ability: Prankster
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Taunt
- Spirit Break
- Reflect
- Thunder Wave"""
    # (its side's last used move a move before: the switch-in must count as one that came in)
    states = ec.run_showdown(gren, CORVIKNIGHT + "\n\n" + BLISSEY, [("move reflect", "move roost"),
                                                                    ("move taunt", "switch 2")])  # fmt: skip
    assert _keys(_full(states, 1, "taunt", "blissey", (1, 2)), "count", "options") == {}


def test_l179_cursed_body_disable_turns():
    gengar = """Gengar @ Leftovers
Ability: Cursed Body
EVs: 252 HP / 4 SpA / 252 Spe
Timid Nature
- Shadow Ball
- Sludge Bomb
- Hex
- Protect"""
    # (a seed where it goes off: force_random gives Showdown's Disable a turn more)
    states = ec.run_showdown(GARCHOMP_SD.replace("- Earthquake", "- Crunch"), gengar,
                             [("move crunch", "move hex")], seed="gen5,23,23,23,23")  # fmt: skip
    assert any("Cursed Body" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "crunch", "hex"), "count", "options") == {}


def test_l179_flinched_move_is_not_the_last_used():
    tusk = """Iron Treads @ Leftovers
Ability: Quark Drive
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Iron Head
- Rapid Spin
- Knock Off
- Encore"""
    states = ec.run_showdown(tusk, BLISSEY, [("move ironhead", "move calmmind")], force_random=True)
    assert any(x.startswith("|cant|p2a: Blissey|flinch") for x in states[1]["log"])
    assert _keys(_full(states, 0, "ironhead", "calmmind"), "last_used_move") == {}


def test_l179_imprison():
    mew = """Mew @ Leftovers
Ability: Synchronize
EVs: 252 HP / 252 Def / 4 SpD
Bold Nature
- Imprison
- Soft-Boiled
- Calm Mind
- Seismic Toss"""
    states = ec.run_showdown(mew, BLISSEY, [("move imprison", "move calmmind"), ("move calmmind", "move protect")])
    assert any("move: Imprison" in x for x in states[1]["log"])
    assert ec.showdown_options(states[1]["sides"][1]) == {"protect", "protect-tera"}
    assert _keys(_full(states, 0, "imprison", "calmmind"), "options") == {}


# L180 (doc/engine-diff.md): Protect as Showdown's onPrepareHit: its failure past its PP (a
# consecutive one), it fails as the turn's last action (the foe switched), a protect-breaking
# move ends its count; Transform keeps its user's own set and gives it back on the switch-out
# (stats, weight, moves, PP), copies the weight; a non-Ghost's Curse takes no Pressure PP
def test_l180_protect_last_action_fails():
    states = ec.run_showdown(BLISSEY, CORVIKNIGHT + "\n\n" + LANDO, [("move protect", "switch 2")])
    assert any(x.startswith("|-fail|p1a: Blissey") for x in states[1]["log"])
    assert _full(states, 0, "protect", "landorustherian", (1, 2)) == {}


def test_l180_consecutive_protect_failure_uses_its_pp():
    states = ec.run_showdown(BLISSEY, GARCHOMP_SD, [("move protect", "move swordsdance")] * 2,
                             force_random=False)  # fmt: skip
    assert any(x.startswith("|-fail|p1a: Blissey") for x in states[2]["log"])
    assert _keys(_full(states, 1, "protect", "swordsdance"), "pp", "sc.protect") == {}


def test_l180_phantom_force_breaks_the_protect_count():
    pult = DRAGAPULT_COPYCAT.replace("- Copycat", "- Phantom Force")
    states = ec.run_showdown(KYUREM, pult, [("move earthpower", "move phantomforce"),
                                             ("move protect", "move phantomforce")])  # fmt: skip
    assert any("[broken]" in x for x in states[2]["log"])
    assert _keys(_full(states, 1, "protect", "phantomforce"), "sc.protect") == {}


def test_l180_transform_own_set_back_on_switch_out():
    states = ec.run_showdown(DITTO_BACK, LANDO, [("switch 2", "move stealthrock"), ("switch 2", "move stealthrock")])
    assert states[1]["sides"][0]["mons"][1]["weight"] == 68.0  # Landorus-T's
    assert _full(states, 0, "ditto", "stealthrock", (2, 1)) == {}
    assert _full(states, 1, "blissey", "stealthrock", (2, 1)) == {}


def test_l180_curse_no_pressure():
    curse = BLISSEY.replace("- Calm Mind", "- Curse")
    states = ec.run_showdown(curse, KYUREM, [("move curse", "move protect")])
    assert _keys(_full(states, 0, "curse", "protect"), "pp") == {}


# L181 (doc/engine-diff.md): toxic's count as Showdown's stage (up to 15; counted under Magic
# Guard; gone with a Rest), a used Dauntless Shield (base ability none), Ogerpon's -Tera forme for
# good (species, base ability)
def test_l181_toxic_counts_under_magic_guard():
    blissey = BLISSEY.replace("- Calm Mind", "- Toxic")
    states = ec.run_showdown(CLEFABLE, blissey, [("move calmmind", "move toxic"), ("move calmmind", "move softboiled")])
    assert _keys(_full(states, 0, "calmmind", "toxic"), "toxic_count") == {}
    assert _keys(_full(states, 1, "calmmind", "softboiled"), "toxic_count") == {}


def test_l181_rest_ends_the_toxic_count():
    blissey = BLISSEY.replace("- Calm Mind", "- Toxic")
    zozo = DONDOZO
    states = ec.run_showdown(zozo, blissey, [("move curse", "move toxic"), ("move curse", "move seismictoss"),
                                             ("move rest", "move seismictoss")])  # fmt: skip
    assert states[3]["sides"][0]["mons"][0]["status"] == "slp"
    assert _keys(_full(states, 2, "rest", "seismictoss"), "toxic_count") == {}


def test_l181_dauntless_shield_used():
    zama = """Zamazenta @ Leftovers
Ability: Dauntless Shield
EVs: 252 HP / 252 Def / 4 Spe
Impish Nature
- Body Press
- Iron Defense
- Crunch
- Roar"""
    states = ec.run_showdown(BLISSEY, CORVIKNIGHT + "\n\n" + zama, [("move calmmind", "switch 2")])
    assert _keys(_full(states, 0, "calmmind", "zamazenta", (1, 2)), "ability") == {}


def test_l181_ogerpon_tera_forme():
    oger = """Ogerpon-Wellspring @ Wellspring Mask
Ability: Water Absorb
Tera Type: Water
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Ivy Cudgel
- Horn Leech
- Knock Off
- U-turn"""
    states = ec.run_showdown(oger, BLISSEY, [("move hornleech terastallize", "move calmmind")])
    assert _keys(_full(states, 0, "hornleech-tera", "calmmind"), "id", "ability") == {}


# L182 (doc/engine-diff.md): the Protect count is the mon's (Showdown's stall volatile): up as it
# protects, gone with its switch-out
def test_l182_protect_count_ends_with_the_switch():
    states = ec.run_showdown(BLISSEY + "\n\n" + CORVIKNIGHT, GARCHOMP_SD,
                             [("move protect", "move swordsdance"), ("switch 2", "move swordsdance")])  # fmt: skip
    assert _keys(_full(states, 1, "corviknight", "swordsdance", (2, 1)), "sc.protect") == {}


def test_l182_protect_count_at_a_pivot():
    # (Chilly Reception, aimed at its user: a pivot's decision with the Protect up)
    states = ec.run_showdown(BLISSEY, SLOWKING_FUTURE + "\n\n" + CORVIKNIGHT,
                             [("move protect", "move chillyreception")])  # fmt: skip
    assert states[1]["sides"][1]["request"] == "switch"
    assert _keys(_full(states, 0, "protect", "chillyreception", (1, 2)), "sc.protect") == {}


# L183 (doc/engine-diff.md): a forme change's stats by each stat's change (the mon's own IVs and
# EVs kept), its weight (Minior-Meteor 40, Palafin-Hero 97.4, ...), a temporary forme back on the
# switch-out (Minior-Meteor to its core, Wishiwashi-School, Aegislash-Blade, ...)
MINIOR = """Minior-Violet @ White Herb
Ability: Shields Down
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Shell Smash
- Acrobatics
- Earthquake
- Power Gem"""


def test_l183_minior_meteor_and_back():
    p1 = BLISSEY + "\n\n" + CORVIKNIGHT
    states = ec.run_showdown(p1, CORVIKNIGHT + "\n\n" + MINIOR, [("move calmmind", "switch 2"),
                                                                   ("move calmmind", "switch 2")])  # fmt: skip
    assert states[1]["sides"][1]["mons"][1]["species"] == "miniormeteor"
    assert _full(states, 0, "calmmind", "miniorviolet", (2, 2)) == {}
    assert _full(states, 1, "calmmind", "corviknight", (2, 2)) == {}


# L184 (doc/engine-diff.md): Mummy / Lingering Aroma give their own ability, Wandering Spirit
# swaps (Showdown's skillSwap); Trace copies no notrace ability and keeps seeking (the next foe's
# on its entry); a mover that woke and then flinched uses no PP; a failed Protect roll ends the
# count at once; the once-per-battle abilities (Intrepid Sword, Supersweet Syrup) used for good
OINKOLOGNE = """Oinkologne @ Leftovers
Ability: Lingering Aroma
EVs: 252 HP / 252 Def / 4 SpD
Impish Nature
- Body Slam
- Yawn
- Protect
- Curse"""


def test_l184_lingering_aroma_gives_itself():
    states = ec.run_showdown(GARCHOMP_SD.replace("- Scale Shot", "- Dragon Claw"), OINKOLOGNE, [("move dragonclaw", "move curse")])
    assert states[1]["sides"][0]["mons"][0]["ability"] == "lingeringaroma"
    assert _keys(_full(states, 0, "dragonclaw", "curse"), "ability") == {}


def test_l184_wandering_spirit_swaps():
    runerigus = OINKOLOGNE.replace("Oinkologne", "Runerigus").replace("Lingering Aroma", "Wandering Spirit")
    runerigus = runerigus.replace("- Body Slam", "- Shadow Ball").replace("- Yawn", "- Will-O-Wisp")
    states = ec.run_showdown(GARCHOMP_SD.replace("- Scale Shot", "- Dragon Claw"), runerigus, [("move dragonclaw", "move curse")])
    assert states[1]["sides"][1]["mons"][0]["ability"] == "roughskin"
    assert _keys(_full(states, 0, "dragonclaw", "curse"), "ability") == {}


PORYGON2 = """Porygon2 @ Eviolite
Ability: Trace
EVs: 252 HP / 252 Def / 4 SpD
Bold Nature
- Recover
- Ice Beam
- Discharge
- Trick Room"""
GREAT_TUSK = """Great Tusk @ Leftovers
Ability: Protosynthesis
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Headlong Rush
- Rapid Spin
- Ice Spinner
- Knock Off"""


def test_l184_trace_seeks_past_a_notrace_ability():
    states = ec.run_showdown(BLISSEY + "\n\n" + PORYGON2, GREAT_TUSK + "\n\n" + GARCHOMP_SD,
                             [("switch 2", "move rapidspin"), ("move recover", "switch 2")])  # fmt: skip
    assert states[1]["sides"][0]["mons"][1]["ability"] == "trace"  # not Protosynthesis
    assert states[2]["sides"][0]["mons"][1]["ability"] == "roughskin"  # the next foe's
    assert _keys(_full(states, 0, "porygon2", "rapidspin", (2, 1)), "ability") == {}
    assert _keys(_full(states, 1, "recover", "garchomp", (2, 2)), "ability") == {}


BRELOOM = """Breloom @ Leftovers
Ability: Technician
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Spore
- Mach Punch
- Bullet Seed
- Rock Tomb"""
MEOWSCARADA = """Meowscarada @ Leftovers
Ability: Overgrow
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Fake Out
- Flower Trick
- Knock Off
- U-turn"""


def test_l184_no_pp_after_waking_into_a_flinch():
    turns = [("move calmmind", "move spore"), ("move calmmind", "switch 2"), ("move calmmind", "move fakeout")]
    states = ec.run_showdown(BLISSEY, BRELOOM + "\n\n" + MEOWSCARADA, turns, seed="gen5,35,42,105,175")
    log = states[3]["log"]
    assert any("|-curestatus|p1a: Blissey|slp" in x for x in log)
    assert any("|cant|p1a: Blissey|flinch" in x for x in log)
    assert _keys(_full(states, 2, "calmmind", "fakeout"), "pp", "last_used_move") == {}


def test_l184_failed_protect_ends_the_count():
    states = ec.run_showdown(BLISSEY, SLOWKING_FUTURE + "\n\n" + CORVIKNIGHT,
                             [("move protect", "move slackoff"), ("move protect", "move chillyreception")],
                             seed="gen5,35,42,105,175")  # fmt: skip
    assert "|-fail|p1a: Blissey" in states[2]["log"] and states[2]["sides"][1]["request"] == "switch"
    assert _keys(_full(states, 1, "protect", "chillyreception", (1, 2)), "sc.protect") == {}


def test_l184_intrepid_sword_once():
    zacian = """Zacian @ Rusted Sword
Ability: Intrepid Sword
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Behemoth Blade
- Play Rough
- Swords Dance
- Close Combat"""
    turns = [("switch 2", "move spikes"), ("switch 2", "move spikes")]
    states = ec.run_showdown(zacian + "\n\n" + CORVIKNIGHT, TINGLU, turns, fmt="gen9customgame")
    assert states[0]["sides"][0]["mons"][0]["boosts"]["atk"] == 1
    assert states[2]["sides"][0]["mons"][0]["boosts"]["atk"] == 0
    assert _full(states, 0, "corviknight", "spikes", (2, 1)) == {}
    assert _full(states, 1, "zaciancrowned", "spikes", (2, 1)) == {}


def test_l184_supersweet_syrup_kept_on_the_switch_out():
    states = ec.run_showdown(BLISSEY, CORVIKNIGHT + "\n\n" + HYDRAPPLE_BACK.split("\n\n")[1],
                             [("move calmmind", "switch 2"), ("move calmmind", "switch 2")])  # fmt: skip
    assert _keys(_full(states, 0, "calmmind", "hydrapple", (1, 2)), "ability") == {}
    assert _keys(_full(states, 1, "calmmind", "corviknight", (1, 2)), "ability") == {}


# L185 (doc/engine-diff.md): a terastallized mon that fainted and was revived (Revival Blessing) is
# no longer terastallized (Showdown deletes it on the faint); its side's Terastallization is used
# (the side's tera_used: no mon shows it)
def test_l185_revived_tera_mon():
    p1 = MAGIKARP_PAWMOT.replace("Ability: Swift Swim", "Ability: Swift Swim\nTera Type: Water")
    turns = [("move splash terastallize", "move seismictoss"), ("switch 2", ""),
             ("move revivalblessing", "move seismictoss"), ("switch 2", ""), ("move nuzzle", "move calmmind")]  # fmt: skip
    states = ec.run_showdown(p1, BLISSEY, turns)
    after = states[4]["sides"][0]
    assert after["tera_used"] and not after["mons"][0]["terastallized"] and after["mons"][0]["hp"] > 0
    assert not any(o.endswith("-tera") for o in ec.showdown_options(after))
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "revivalblessing", "seismictoss")
    (_, mid), = outs
    outs = ec.engine_outcomes(mid, "magikarp", "seismictoss")
    assert ec.closest(states[4], outs, (2, 1), hp=True, full=True, start=states[3])["diff"] == {}
    # the state built from Showdown's (no mon terastallized, none fainted) can no longer either
    assert not any(o.endswith("-tera") for o in pe.options(ec.engine_state(states[4]))[0])
    assert _full(states, 4, "nuzzle", "calmmind", (2, 1)) == {}



# L186 (doc/engine-diff.md): the PP as Showdown's: Pressure's after the move's own, down to 0 at
# most, and a called move's from its caller (Sleep Talk); a lost Focus Punch uses none (its
# beforeMoveCallback stops runMove before the PP, as a flinch); Eerie Spell, 3 PP off the target's
# last move (a 100% secondary)
def test_l186_pressure_stops_at_zero():
    blissey = BLISSEY + "\n\n" + CORVIKNIGHT
    turns = [("move dracometeor", "move calmmind"), ("move dracometeor", "switch 2")] + [("move dracometeor", "move roost")] * 3
    states = ec.run_showdown(DRAGAPULT_COPYCAT, blissey, turns)
    assert [s["sides"][0]["mons"][0]["moves"][2]["pp"] for s in states] == [8, 7, 5, 3, 1, 0]
    assert _keys(_full(states, 4, "dracometeor", "roost", (1, 2)), "pp") == {}


def test_l186_pressure_on_sleep_talk():
    zozo = _setter("Dondozo", "Unaware", "Leftovers", "- Sleep Talk\n- Wave Crash\n- Earthquake\n- Body Slam")
    turns = [("move bodyslam", "move spore"), ("move sleeptalk", "switch 2")]
    states = ec.run_showdown(zozo, BRELOOM + "\n\n" + CORVIKNIGHT, turns, seed="gen5,36,43,108,180")
    assert any("[from] move: Sleep Talk" in x for x in states[2]["log"])  # (an Earthquake: immune)
    assert states[2]["sides"][0]["mons"][0]["moves"][0]["pp"] == 14  # its own 1, Pressure's 1
    assert _keys(_full(states, 1, "sleeptalk", "corviknight", (1, 2)), "pp") == {}


def test_l186_no_pp_for_a_lost_focus_punch():
    breloom = BRELOOM.replace("- Rock Tomb", "- Focus Punch")
    states = ec.run_showdown(breloom, BLISSEY, [("move focuspunch", "move seismictoss")])
    assert any("|cant|p1a: Breloom|Focus Punch" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "focuspunch", "seismictoss"), "pp", "last_used_move") == {}


def test_l186_eerie_spell():
    slowking = SLOWKING_FUTURE.replace("- Sludge Bomb", "- Eerie Spell")
    states = ec.run_showdown(slowking, BLISSEY, [("move eeriespell", "move calmmind")])
    assert states[1]["sides"][1]["mons"][0]["moves"][3]["pp"] == 28  # 32, its use, Eerie Spell's 3
    assert _keys(_full(states, 0, "eeriespell", "calmmind"), "pp") == {}


# L187 (doc/engine-diff.md): Future Sight set as the move goes (not by a fully paralyzed user);
# Knock Off takes no item the hit uses up (a resist berry, Weakness Policy: their last item); the
# harness: a transformed mon's Transform is its last used move (in its own moves), a type change
# before its Terastallization keeps the typechange volatile (the types back on the switch-out)
def test_l187_no_future_sight_when_fully_paralyzed():
    blissey = BLISSEY.replace("- Calm Mind", "- Thunder Wave")
    states = ec.run_showdown(SLOWKING_FUTURE, blissey, [("move futuresight", "move thunderwave")], force_random=True)
    assert any(x.startswith("|cant|p1a: Slowking|par") for x in states[1]["log"])
    assert _keys(_full(states, 0, "futuresight", "thunderwave"), "future_sight") == {}


@pytest.mark.parametrize("item", ["Colbur Berry", "Weakness Policy"])
def test_l187_knock_off_takes_no_used_up_item(item):
    gar = GARCHOMP_SD.replace("- Scale Shot", "- Knock Off")
    slowking = SLOWKING_FUTURE.replace("@ Heavy-Duty Boots", f"@ {item}")
    states = ec.run_showdown(gar, slowking, [("move knockoff", "move slackoff")])
    assert states[1]["sides"][1]["mons"][0]["last_item"] == item.lower().replace(" ", "")
    assert _keys(_full(states, 0, "knockoff", "slackoff"), "item") == {}


def test_l187_transform_is_the_last_used_move():
    mew = """Mew @ Leftovers
Ability: Synchronize
EVs: 252 HP / 4 Def / 252 Spe
Timid Nature
- Calm Mind
- Transform
- Soft-Boiled
- Psychic"""
    # (Taunt: the comparison has the last used move with a move reading it)
    states = ec.run_showdown(mew, BLISSEY.replace("- Protect", "- Taunt"), [("move transform", "move calmmind")])
    assert _keys(_full(states, 0, "transform", "calmmind"), "last_used_move") == {}


def test_l187_protean_then_tera_types_back_on_the_switch_out():
    greninja = """Greninja @ Leftovers
Ability: Protean
Tera Type: Water
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Dark Pulse
- Hydro Pump
- Ice Beam
- U-turn"""
    turns = [("move darkpulse", "move calmmind"), ("move hydropump terastallize", "move calmmind"),
             ("switch 2", "move calmmind")]  # fmt: skip
    states = ec.run_showdown(greninja + "\n\n" + CORVIKNIGHT, BLISSEY, turns)
    assert states[2]["sides"][0]["mons"][0]["pre_tera_types"] == ["Dark"]
    assert _keys(_full(states, 2, "corviknight", "calmmind", (2, 1)), "types") == {}


# L188 (doc/engine-diff.md): the active's grounding with its volatiles (Showdown's isGrounded: Roost
# takes the Flying type off for the turn, Magnet Rise lifts, Smack Down / Ingrain ground) for the
# terrains and Arena Trap; Grassy Terrain heals no semi-invulnerable mon (a charging Phantom Force)
RILLABOOM_KNOCK = """Rillaboom @ Leftovers
Ability: Grassy Surge
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Grassy Glide
- Wood Hammer
- U-turn
- Knock Off"""


def test_l188_roost_grounds_for_grassy_terrain():
    turns = [("move knockoff", "move uturn"), ("move knockoff", "move uturn"), ("move knockoff", "move roost")]
    states = ec.run_showdown(RILLABOOM_KNOCK, CORVIKNIGHT, turns)
    assert any("[from] Grassy Terrain" in x and "Corviknight" in x for x in states[3]["log"])
    assert _keys(_full(states, 2, "knockoff", "roost"), "hp") == {}


def test_l188_no_grassy_heal_while_semi_invulnerable():
    dragapult = DRAGAPULT_COPYCAT.replace("- Copycat", "- Phantom Force")
    states = ec.run_showdown(RILLABOOM_KNOCK, dragapult, [("move grassyglide", "move phantomforce")])
    assert not any("[from] Grassy Terrain" in x and "Dragapult" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "grassyglide", "phantomforce"), "hp") == {}


# L188: a Choice item a Trick gives starts: its lock ends (Showdown's choice items' onStart), two
# same items swap too
DRAGAPULT_SPECS = DRAGAPULT_COPYCAT.replace("@ Leftovers", "@ Choice Specs").replace("- Copycat", "- Shadow Ball")


@pytest.mark.parametrize("item", ["Choice Scarf", "Choice Specs"])
def test_l188_trick_choice_item_ends_the_lock(item):
    states = ec.run_showdown(DRAGAPULT_SPECS, GHOLDENGO_TRICK.replace("Choice Scarf", item),
                             [("move dracometeor", "move trick")])  # fmt: skip
    assert any("|-activate|p2a: Gholdengo|move: Trick" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "dracometeor", "trick"), "options") == {}


# L189 (doc/engine-diff.md): Lunar Dance restores the PP too (Showdown's lunardance onSwap: a mon
# missing only PP takes it); the engine's Healing Wish side condition at 2, every move's max PP
def test_l189_lunar_dance_restores_the_pp():
    cresselia = """Cresselia @ Leftovers
Ability: Levitate
EVs: 252 HP / 252 Def / 4 SpD
Bold Nature
- Lunar Dance
- Moonlight
- Psychic
- Thunder Wave"""
    turns = [("move calmmind", "move swordsdance"), ("switch 2", "move swordsdance"),
             ("move lunardance", "move swordsdance"), ("switch 2", "")]  # fmt: skip
    states = ec.run_showdown(BLISSEY + "\n\n" + cresselia, GARCHOMP_SD, turns)
    assert states[1]["sides"][0]["mons"][0]["moves"][3]["pp"] == 31
    assert states[4]["sides"][0]["mons"][0]["moves"][3]["pp"] == 32
    outs = ec.engine_outcomes(ec.engine_state(states[2]), "lunardance", "swordsdance")
    (_, mid), = outs
    outs = ec.engine_outcomes(mid, "blissey", "none")  # (the end of the turn's pick)
    assert _keys(ec.closest(states[4], outs, (2, 1), hp=True, full=True, start=states[3])["diff"], "pp") == {}


# L190 (doc/engine-diff.md): the moves that set an ability, Showdown's setAbility (Worry Seed's
# Insomnia wakes its target; Simple Beam; Entrainment gives the user's; Role Play / Doodle take the
# target's); they were nothing
def test_l190_worry_seed_wakes():
    breloom = BRELOOM.replace("- Rock Tomb", "- Worry Seed")
    states = ec.run_showdown(breloom, GARCHOMP_SD, [("move spore", "move swordsdance"),
                                                     ("move worryseed", "move swordsdance")])  # fmt: skip
    assert states[2]["sides"][1]["mons"][0]["ability"] == "insomnia"
    assert _keys(_full(states, 1, "worryseed", "swordsdance"), "ability", "status", "sleep") == {}


@pytest.mark.parametrize("move, side, ability", [("simplebeam", 1, "simple"), ("entrainment", 1, "naturalcure"),
                                                 ("roleplay", 0, "roughskin"), ("doodle", 0, "roughskin")])  # fmt: skip
def test_l190_ability_moves(move, side, ability):
    blissey = BLISSEY.replace("- Calm Mind", "- " + {"simplebeam": "Simple Beam", "entrainment": "Entrainment",
                                                     "roleplay": "Role Play", "doodle": "Doodle"}[move])  # fmt: skip
    states = ec.run_showdown(blissey, GARCHOMP_SD, [(f"move {move}", "move swordsdance")])
    assert states[1]["sides"][side]["mons"][0]["ability"] == ability
    assert _keys(_full(states, 0, move, "swordsdance"), "ability") == {}


# L190 (the harness): a copied once-per-battle ability used (Imposter into Zamazenta) keeps the base
# ability (the engine marks an own one only)
def test_l190_copied_dauntless_shield_keeps_the_base_ability():
    states = ec.run_showdown(DITTO_BACK, ZAMAZENTA, [("switch 2", "move irondefense")], fmt="gen9customgame")
    assert any("Dauntless Shield" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "ditto", "irondefense", (2, 1)), "ability") == {}


# L191 (doc/engine-diff.md): the accuracy as Showdown's hitStepAccuracy (the user's accuracy less
# the target's evasion; Unaware, Keen Eye, ignoreEvasion; no stage for a sure hit); Shed Skin cures
# 1 in 3 (a branch of the end of the turn); a frozen target thaws to a Fire attack / a thawing move
SCRAFTY_SHED = """Scrafty @ Leftovers
Ability: Shed Skin
EVs: 252 HP / 252 Def / 4 SpD
Impish Nature
- Bulk Up
- Drain Punch
- Knock Off
- Rest"""


def test_l191_evasion():
    blissey = BLISSEY.replace("- Calm Mind", "- Double Team")
    states = ec.run_showdown(GARCHOMP_SD, blissey, [("move swordsdance", "move doubleteam"),
                                                    ("move earthquake", "move softboiled")], seed="gen5,38,45,114,190")  # fmt: skip
    assert any("|-miss|p1a: Garchomp" in x for x in states[2]["log"])
    assert _full(states, 1, "earthquake", "softboiled") == {}


def test_l191_unaware_ignores_the_accuracy():
    gar = GARCHOMP_SD.replace("- Scale Shot", "- Stone Edge").replace("- Stealth Rock", "- Hone Claws")
    states = ec.run_showdown(gar, DONDOZO, [("move honeclaws", "move curse"), ("move stoneedge", "move curse")],
                             seed="gen5,41,48,123,205")  # fmt: skip
    assert any("|-miss|p1a: Garchomp" in x for x in states[2]["log"])
    assert _full(states, 1, "stoneedge", "curse") == {}


def test_l191_shed_skin_one_in_three():
    blissey = BLISSEY.replace("- Calm Mind", "- Toxic")
    states = ec.run_showdown(SCRAFTY_SHED, blissey, [("move bulkup", "move toxic")], seed="gen5,1,8,3,5")
    assert states[1]["sides"][0]["mons"][0]["status"] == "tox"  # not cured this time
    assert _keys(_full(states, 0, "bulkup", "toxic"), "status", "toxic") == {}


def test_l191_fire_thaws_the_target():
    kyurem = KYUREM_SPECIAL.replace("- Earth Power", "- Flamethrower")
    turns = [("move icebeam", "move calmmind"), ("move flamethrower", "move calmmind")]
    states = ec.run_showdown(kyurem, BLISSEY, turns, seed="gen5,42,49,126,210")
    assert states[1]["sides"][1]["mons"][0]["status"] == "frz"
    assert _keys(_full(states, 1, "flamethrower", "calmmind"), "status") == {}
    # (no branch left frozen: the hit thaws it before its own move; was its 1 in 5 thaw only)
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "flamethrower", "calmmind")
    assert not any(str(o[1].side_two.pokemon[0].status).lower() == "freeze" for o in outs)


# L192 (doc/engine-diff.md): a Stellar tera keeps its own types (Showdown's getTypes: a Ghost one
# cannot be trapped); the harness: every move disabled (Imprison's hidden ones too) is Struggle
def test_l192_stellar_ghost_not_trapped():
    heatran = """Heatran @ Leftovers
Ability: Flash Fire
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Magma Storm
- Earth Power
- Stealth Rock
- Protect"""
    dragapult = DRAGAPULT_COPYCAT.replace("Ability: Infiltrator", "Ability: Infiltrator\nTera Type: Stellar")
    states = ec.run_showdown(heatran, dragapult + "\n\n" + CORVIKNIGHT,
                             [("move magmastorm", "move dragondance terastallize")], seed="gen5,1,2,3,4")  # fmt: skip
    assert any("move: Magma Storm" in x for x in states[1]["log"])
    assert "switch corviknight" in ec.showdown_options(states[1]["sides"][1])
    assert _keys(_full(states, 0, "magmastorm", "dragondance-tera", (1, 2)), "options") == {}


def test_l192_imprison_every_move_is_struggle():
    mew = """Mew @ Leftovers
Ability: Synchronize
EVs: 252 HP / 4 Def / 252 Spe
Timid Nature
- Imprison
- Transform
- Soft-Boiled
- Psychic"""
    states = ec.run_showdown(mew, GARCHOMP_SD, [("move imprison", "move swordsdance"),
                                                 ("move transform", "move swordsdance")])  # fmt: skip
    assert "none" in ec.showdown_options(states[2]["sides"][1])
    assert _keys(_full(states, 1, "transform", "swordsdance"), "options") == {}


# L193 (doc/engine-diff.md): a drop an ability causes goes back off Mirror Armor (Gooey); an encored
# move keeps the turn's order (an encored Protect as the last action fails)
def test_l193_mirror_armor_reflects_gooey():
    goodra = """Goodra @ Leftovers
Ability: Gooey
EVs: 252 HP / 4 Def / 252 SpD
Calm Nature
- Draco Meteor
- Fire Blast
- Thunderbolt
- Sludge Bomb"""
    corv = CORVIKNIGHT.replace("Ability: Pressure", "Ability: Mirror Armor")
    states = ec.run_showdown(corv, goodra, [("move bravebird", "move thunderbolt")])
    assert states[1]["sides"][1]["mons"][0]["boosts"]["spe"] == -1
    assert _keys(_full(states, 0, "bravebird", "thunderbolt"), "boost") == {}


def test_l193_encored_protect_last_fails():
    valiant = """Iron Valiant @ Leftovers
Ability: Quark Drive
EVs: 252 SpA / 4 SpD / 252 Spe
Timid Nature
- Calm Mind
- Moonblast
- Protect
- Encore"""
    # (its first Protect fails as the last action: no count, Protect its last move)
    states = ec.run_showdown(BLISSEY, valiant, [("move protect", "move protect"), ("move calmmind", "move encore")])
    assert any(x.startswith("|-fail|p1a: Blissey") for x in states[1]["log"])
    assert any(x.startswith("|-fail|p1a: Blissey") for x in states[2]["log"])
    assert _keys(_full(states, 1, "calmmind", "encore"), "protect", "volatile") == {}


# L194 (doc/engine-diff.md): Shed Tail fails without a mon to switch in or at half its HP (rounded
# up); Soul-Heart's Sp. Atk +1 for a faint; Beak Blast burns a contact attacker before it moves
def test_l194_shed_tail_fails_without_a_switch():
    cyclizar = """Cyclizar @ Leftovers
Ability: Regenerator
EVs: 252 HP / 4 Def / 252 Spe
Jolly Nature
- Shed Tail
- Rapid Spin
- Knock Off
- Draco Meteor"""
    states = ec.run_showdown(cyclizar, BLISSEY, [("move shedtail", "move calmmind")])
    assert any(x.startswith("|-fail|p1a: Cyclizar") for x in states[1]["log"])
    assert _full(states, 0, "shedtail", "calmmind") == {}


def test_l194_soul_heart():
    magearna = """Magearna @ Leftovers
Ability: Soul-Heart
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Flash Cannon
- Fleur Cannon
- Volt Switch
- Trick Room"""
    states = ec.run_showdown(magearna, MAGIKARP_PAWMOT.split("\n\n")[0] + "\n\n" + BLISSEY,
                             [("move flashcannon", "move splash")])  # fmt: skip
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spa"] == 1
    assert _keys(_full(states, 0, "flashcannon", "splash", (1, 2)), "boost") == {}


def test_l194_beak_blast_burns_a_contact_attacker():
    toucannon = """Toucannon @ Leftovers
Ability: Skill Link
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Beak Blast
- Bullet Seed
- Knock Off
- Roost"""
    gar = GARCHOMP_SD.replace("- Scale Shot", "- Dragon Claw")
    states = ec.run_showdown(toucannon, gar, [("move beakblast", "move dragonclaw")])
    assert states[1]["sides"][1]["mons"][0]["status"] == "brn"
    assert _keys(_full(states, 0, "beakblast", "dragonclaw"), "status") == {}


# L195 (doc/engine-diff.md): Terapagos's permanent formes (Showdown's formeChange isPermanent: the
# ability as base too, updateMaxHp): Tera Shift's Terapagos-Terastal on its entry, whose Tera Shell
# resists every hit at full HP; Terapagos-Stellar on the tera (Teraform Zero)
TERAPAGOS = """Terapagos @ Leftovers
Ability: Tera Shift
Tera Type: Stellar
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Tera Starstorm
- Earth Power
- Calm Mind
- Rapid Spin"""


def test_l195_tera_shift_and_tera_shell():
    states = ec.run_showdown(GARCHOMP_SD, BLISSEY + "\n\n" + TERAPAGOS, [("move earthquake", "switch 2")])
    assert states[1]["sides"][1]["mons"][1]["species"] == "terapagosterastal"
    assert any("ability: Tera Shell" in x for x in states[1]["log"])
    assert _full(states, 0, "earthquake", "terapagos", (1, 2)) == {}


def test_l195_terapagos_stellar():
    states = ec.run_showdown(GARCHOMP_SD, TERAPAGOS, [("move swordsdance", "move calmmind terastallize")])
    assert states[1]["sides"][1]["mons"][0]["species"] == "terapagosstellar"
    assert _full(states, 0, "swordsdance", "calmmind-tera") == {}


# L196 (doc/engine-diff.md): Disguise / Ice Face break as the move hits (Showdown's onDamage), not
# as it starts: a miss, a Protect, a charging turn leave them
EISCUE = """Eiscue @ Leftovers
Ability: Ice Face
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Belly Drum
- Liquidation
- Ice Spinner
- Iron Head"""
MIMIKYU = """Mimikyu @ Leftovers
Ability: Disguise
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Swords Dance
- Play Rough
- Shadow Sneak
- Drain Punch"""


def test_l196_ice_face_kept_on_a_miss():
    gar = GARCHOMP_SD.replace("- Scale Shot", "- Stone Edge")
    states = ec.run_showdown(EISCUE, gar, [("move bellydrum", "move stoneedge")], force_random=False)
    assert any("|-miss|p2a: Garchomp" in x for x in states[1]["log"])
    assert states[1]["sides"][0]["mons"][0]["species"] == "eiscue"
    assert _keys(_full(states, 0, "bellydrum", "stoneedge"), "id", "defense") == {}


def test_l196_disguise_kept_on_a_charging_turn():
    armarouge = """Armarouge @ Leftovers
Ability: Weak Armor
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Meteor Beam
- Armor Cannon
- Psyshock
- Will-O-Wisp"""
    states = ec.run_showdown(armarouge, MIMIKYU, [("move meteorbeam", "move swordsdance")])
    assert states[1]["sides"][1]["mons"][0]["species"] == "mimikyu"
    assert _keys(_full(states, 0, "meteorbeam", "swordsdance"), "id", "hp") == {}


# L197 (doc/engine-diff.md): Yawn's drowsiness is no sleep yet (the Sleep Clause Mod does not stop
# it); its sleep is Showdown's trySetStatus (the Sleep Clause, the immunities)
def test_l197_yawn_through_the_sleep_clause():
    breloom = BRELOOM.replace("- Rock Tomb", "- Yawn")
    # (Corviknight asleep on the bench: no Natural Cure to wake it)
    turns = [("move spore", "move roost"), ("move yawn", "switch 2"), ("move bulletseed", "move calmmind")]
    states = ec.run_showdown(breloom, CORVIKNIGHT + "\n\n" + BLISSEY, turns)
    assert states[1]["sides"][1]["mons"][0]["status"] == "slp"
    assert any("move: Yawn" in x for x in states[2]["log"])
    assert any("Sleep Clause Mod activated" in x for x in states[3]["log"])
    assert _keys(_full(states, 1, "yawn", "blissey", (1, 2)), "yawn") == {}
    assert _keys(_full(states, 2, "bulletseed", "calmmind", (1, 2)), "status", "yawn") == {}


# L198 (doc/engine-diff.md): an absorbing ability takes an Electric move before a Ground type's
# immunity (Lightning Rod's +1); Charge ends with a stopped Electric move (onMoveAborted); Power
# Herb is used as the move goes; Unburden as the item goes; a Surf a target absorbs gives Gulp
# Missile no forme; Berserk's halves unrounded
def test_l198_lightning_rod_on_a_ground_type():
    rhydon = _attacker("Rhydon", "Lightning Rod", "Eviolite", "- Megahorn\n- Earthquake\n- Rock Blast\n- Stealth Rock")
    regice = _attacker("Regice", "Clear Body", "Leftovers", "- Thunderbolt\n- Ice Beam\n- Thunder Wave\n- Rest", "Modest")
    states = ec.run_showdown(rhydon, regice, [("move stealthrock", "move thunderbolt")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spa"] == 1
    assert _keys(_full(states, 0, "stealthrock", "thunderbolt"), "boost") == {}


def test_l198_charge_ends_with_a_flinched_electric_move():
    excadrill = _attacker("Excadrill", "Sand Rush", "Leftovers", "- Iron Head\n- Earthquake\n- Rock Slide\n- Rapid Spin")
    bellibolt = _attacker("Bellibolt", "Electromorphosis", "Leftovers", "- Thunderbolt\n- Muddy Water\n- Slack Off\n- Toxic", "Modest")
    states = ec.run_showdown(excadrill, bellibolt, [("move ironhead", "move thunderbolt")], force_random=True)
    assert any("|cant|p2a: Bellibolt|flinch" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "ironhead", "thunderbolt"), "charge", "pp") == {}


def test_l198_power_herb_kept_while_asleep():
    armarouge = """Armarouge @ Power Herb
Ability: Weak Armor
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Meteor Beam
- Armor Cannon
- Psyshock
- Will-O-Wisp"""
    states = ec.run_showdown(armarouge, BRELOOM, [("move meteorbeam", "move spore")])
    assert states[1]["sides"][0]["mons"][0]["item"] == "powerherb"
    assert _keys(_full(states, 0, "meteorbeam", "spore"), "item") == {}


def test_l198_unburden_as_the_item_goes():
    hawlucha = _attacker("Hawlucha", "Unburden", "White Herb", "- Close Combat\n- Acrobatics\n- Swords Dance\n- Roost")
    states = ec.run_showdown(hawlucha, CORVIKNIGHT + "\n\n" + BLISSEY, [("move closecombat", "move uturn")])
    assert states[1]["sides"][1]["request"] == "switch"
    assert _keys(_full(states, 0, "closecombat", "uturn", (1, 2)), "unburden") == {}


def test_l198_gulp_missile_absorbed_surf():
    cramorant = _attacker("Cramorant", "Gulp Missile", "Leftovers", "- Surf\n- Brave Bird\n- Roost\n- Defog", "Modest")
    gastrodon = _attacker("Gastrodon", "Storm Drain", "Leftovers", "- Earth Power\n- Recover\n- Spikes\n- Ice Beam", "Calm")
    states = ec.run_showdown(cramorant, gastrodon, [("move surf", "move spikes")])
    assert states[1]["sides"][0]["mons"][0]["species"] == "cramorant"
    assert _keys(_full(states, 0, "surf", "spikes"), "id") == {}


# L199 (doc/engine-diff.md): the differential's damage hints (Showdown's rolls from its log): a hint
# that is one of the engine's rolls is the hit's damage (no rolls' branches), an off-roll one
# changes nothing
def test_l199_damage_hints():
    states = ec.run_showdown(GARCHOMP_SD, BLISSEY, [("move earthquake", "move calmmind")])
    hints = ec.damage_hints(states[0], states[1])
    dealt = states[0]["sides"][1]["mons"][0]["hp"] - states[1]["sides"][1]["mons"][0]["hp"]
    assert hints == (dealt, -1)
    e = ec.engine_state(states[0])
    outs = ec.engine_outcomes(e, "earthquake", "calmmind", hints)
    assert {o.damage[1] for o in outs} == {dealt}
    assert ec.closest(states[1], outs, (1, 1), hp=True, full=True, start=states[0])["diff"] == {}
    plain = ec.engine_outcomes(e, "earthquake", "calmmind")
    assert [round(o[0], 4) for o in ec.engine_outcomes(e, "earthquake", "calmmind", (1, -1))] == \
        [round(o[0], 4) for o in plain]


# L199: a hit Ice Face takes still gives its user Life Orb's recoil (Showdown's
# onAfterMoveSecondarySelf, whatever the damage; was none: a status move by then)
def test_l199_life_orb_recoil_on_ice_face():
    gar = GARCHOMP_SD.replace("Garchomp @ Leftovers", "Garchomp @ Life Orb")
    states = ec.run_showdown(gar, EISCUE, [("move earthquake", "move bellydrum")])
    assert any("Ice Face" in x for x in states[1]["log"])
    assert any("[from] item: Life Orb" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "earthquake", "bellydrum"), "hp", "id") == {}


# L200 (doc/engine-diff.md): Shields Down / Schooling's forme on the switch-in too; a Magic Guard
# under the foe's Neutralizing Gas takes the hazards / residuals; Recycle; a Mold Breaker ignores
# only breakable abilities (not Tablets / Vessel of Ruin, the auras)
def _full_hinted(states, k, c1, c2, n=(1, 1)):
    hints = ec.damage_hints(states[k], states[k + 1])
    outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, c2, hints)
    return ec.closest(states[k + 1], outs, n, hp=True, full=True, start=states[k])["diff"]


def test_l200_minior_meteor_on_the_switch_in():
    gar = GARCHOMP_SD.replace("- Scale Shot", "- Iron Head")
    states = ec.run_showdown(gar, CORVIKNIGHT + "\n\n" + MINIOR, [("move ironhead", "switch 2")])
    assert any("Minior-Meteor" in x for x in states[1]["log"])  # (hit as Minior-Meteor)
    assert _keys(_full_hinted(states, 0, "ironhead", "miniorviolet", (1, 2)), "hp", "id") == {}


def test_l200_magic_guard_under_neutralizing_gas():
    weezing = _attacker("Weezing-Galar", "Neutralizing Gas", "Black Sludge", "- Stealth Rock\n- Toxic Spikes\n- Strange Steam\n- Will-O-Wisp", "Bold")
    clefable = CLEFABLE if "Magic Guard" in CLEFABLE else CLEFABLE.replace("Ability: Unaware", "Ability: Magic Guard")
    states = ec.run_showdown(weezing, BLISSEY + "\n\n" + clefable, [("move stealthrock", "move calmmind"),
                                                                     ("move toxicspikes", "switch 2")])  # fmt: skip
    assert any("[from] Stealth Rock" in x for x in states[2]["log"])
    assert _keys(_full(states, 1, "toxicspikes", "clefable", (1, 2)), "hp") == {}


def test_l200_recycle():
    snorlax = """Snorlax @ Sitrus Berry
Ability: Thick Fat
Level: 40
EVs: 4 HP
- Recycle
- Body Slam
- Curse
- Rest"""
    states = ec.run_showdown(snorlax, BLISSEY, [("move curse", "move seismictoss"), ("move recycle", "move calmmind")])
    assert states[1]["sides"][0]["mons"][0]["last_item"] == "sitrusberry"
    assert states[2]["sides"][0]["mons"][0]["item"] == "sitrusberry"
    assert _keys(_full(states, 1, "recycle", "calmmind"), "item") == {}


def test_l200_sunsteel_strike_and_tablets_of_ruin():
    solgaleo = _attacker("Solgaleo", "Full Metal Body", "Leftovers", "- Sunsteel Strike\n- Morning Sun\n- Flare Blitz\n- Knock Off")
    wochien = _attacker("Wo-Chien", "Tablets of Ruin", "Leftovers", "- Giga Drain\n- Ruination\n- Leech Seed\n- Protect", "Calm")
    states = ec.run_showdown(solgaleo, wochien, [("move sunsteelstrike", "move leechseed")])
    assert _keys(_full_hinted(states, 0, "sunsteelstrike", "leechseed"), "hp") == {}


# L201 (doc/engine-diff.md): a Guts mover that woke has no Guts by its hit; Sheer Force's moves (a
# volatile secondary too: Throat Chop) take no Life Orb recoil; Lash Out's double power after a drop
# this turn; Battery boosts no holder's own move; Tera Starstorm by Terapagos-Stellar is Stellar
def test_l201_guts_after_waking():
    ursaring = _attacker("Ursaring", "Guts", "Leftovers", "- Facade\n- Earthquake\n- Close Combat\n- Sleep Talk")
    turns = [("move earthquake", "move spore"), ("move earthquake", "move spore")] + [("move earthquake", "move bulletseed")] * 3
    states = ec.run_showdown(ursaring, BRELOOM, turns, seed="gen5,3,4,5,6")
    k = next((k for k in range(1, len(states) - 1) if any("|-curestatus|p1a: Ursaring|slp" in x for x in states[k + 1]["log"])
              and any("|move|p1a: Ursaring|Earthquake" in x for x in states[k + 1]["log"])), None)  # fmt: skip
    assert k is not None
    assert _keys(_full_hinted(states, k, "earthquake", "bulletseed" if k >= 2 else "spore"), "hp") == {}


def test_l201_sheer_force_throat_chop_no_life_orb_recoil():
    tauros = _attacker("Tauros", "Sheer Force", "Life Orb", "- Throat Chop\n- Body Slam\n- Close Combat\n- Earthquake")
    states = ec.run_showdown(tauros, BLISSEY, [("move throatchop", "move calmmind")])
    assert not any("[from] item: Life Orb" in x for x in states[1]["log"])
    assert _keys(_full_hinted(states, 0, "throatchop", "calmmind"), "hp") == {}


def test_l201_lash_out_after_intimidate():
    honchkrow = _attacker("Honchkrow", "Moxie", "Leftovers", "- Lash Out\n- Brave Bird\n- Roost\n- Sucker Punch")
    scrafty = _attacker("Scrafty", "Intimidate", "Leftovers", "- Drain Punch\n- Knock Off\n- Bulk Up\n- Rest", "Impish")
    states = ec.run_showdown(honchkrow, BLISSEY + "\n\n" + scrafty, [("move lashout", "switch 2")])
    hints = ec.damage_hints(states[0], states[1])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "lashout", "scrafty", hints)
    assert hints[0] > 0 and {o.damage[1] for o in outs} == {hints[0]}  # (the hint is a roll of its)
    # (doubled: the engine's likeliest damage near Showdown's, not half of it)
    plain = max(ec.engine_outcomes(ec.engine_state(states[0]), "lashout", "scrafty"), key=lambda o: o[0])
    assert 0.8 * hints[0] <= plain.damage[1] <= 1.2 * hints[0]


def test_l201_battery_not_its_holder():
    charjabug = _attacker("Charjabug", "Battery", "Eviolite", "- Volt Switch\n- Bug Buzz\n- Sticky Web\n- Discharge", "Modest")
    states = ec.run_showdown(charjabug, BLISSEY, [("move discharge", "move calmmind")])
    assert _keys(_full_hinted(states, 0, "discharge", "calmmind"), "hp") == {}


def test_l201_tera_starstorm_stellar():
    states = ec.run_showdown(TERAPAGOS, BLISSEY, [("move terastarstorm terastallize", "move calmmind")])
    assert _keys(_full_hinted(states, 0, "terastarstorm-tera", "calmmind"), "hp") == {}


# L202 (doc/engine-diff.md): the differential's move hints -- Metronome's called move, a multi-hit
# move's hit count -- and Multiscale / Shadow Shield halving a multi-hit move's full-HP hits only
def _full_moves(states, k, c1, c2, n=(1, 1)):
    hints = ec.move_hints(states[k], states[k + 1])
    outs = ec.engine_outcomes(ec.engine_state(states[k]), c1, c2, hints)
    return ec.closest(states[k + 1], outs, n, hp=True, full=True, start=states[k])["diff"]


def test_l202_metronome_hint():
    clefable = CLEFABLE.replace("- Calm Mind", "- Metronome")
    states = ec.run_showdown(BLISSEY, clefable, [("move calmmind", "move metronome")])
    hints = ec.move_hints(states[0], states[1])
    assert hints[5] != ""
    assert _full_moves(states, 0, "calmmind", "metronome") == {}


def test_l202_population_bomb_into_multiscale():
    maushold = _attacker("Maushold", "Technician", "Wide Lens", "- Population Bomb\n- Bite\n- Encore\n- Tidy Up")
    lugia = _attacker("Lugia", "Multiscale", "Leftovers", "- Aeroblast\n- Roost\n- Calm Mind\n- Earthquake", "Bold")
    states = ec.run_showdown(maushold, lugia, [("move populationbomb", "move calmmind")])
    hints = ec.move_hints(states[0], states[1])
    assert hints[2] >= 2
    assert _keys(_full_moves(states, 0, "populationbomb", "calmmind"), "hp") == {}


# L202: a multi-hit move's later hits by the state they hit (a Weak Armor drop after the first),
# all of them through a Tera Shell that took the first
def test_l202_triple_axel_after_weak_armor():
    weavile = _attacker("Weavile", "Pressure", "Choice Band", "- Triple Axel\n- Knock Off\n- Ice Shard\n- Low Kick")
    skarmory = _attacker("Skarmory", "Weak Armor", "Leftovers", "- Roost\n- Spikes\n- Brave Bird\n- Whirlwind", "Impish")
    states = ec.run_showdown(weavile, skarmory, [("move tripleaxel", "move roost")], seed="gen5,2,3,4,5")
    if ec.move_hints(states[0], states[1])[2] < 2:
        pytest.skip("the seed's Triple Axel missed early")
    assert _keys(_full_moves(states, 0, "tripleaxel", "roost"), "hp") == {}


def test_l202_tera_shell_resists_every_hit():
    weavile = _attacker("Weavile", "Pressure", "Choice Band", "- Triple Axel\n- Knock Off\n- Ice Shard\n- Low Kick")
    states = ec.run_showdown(weavile, TERAPAGOS, [("move tripleaxel", "move calmmind")], seed="gen5,2,3,4,5")
    if ec.move_hints(states[0], states[1])[2] < 2:
        pytest.skip("the seed's Triple Axel missed early")
    assert _keys(_full_moves(states, 0, "tripleaxel", "calmmind"), "hp") == {}


# L203 (doc/engine-diff.md): Slow Start's counter 5 from the switch-in, kept on that turn (a pivot's
# decision mid-turn); a forme's stats from the IVs inferred from the old forme's (a 0 Atk IV
# Terapagos); the ability-ignoring moves through Tera Shell
def test_l203_slow_start_at_a_pivot():
    regigigas = _attacker("Regigigas", "Slow Start", "Leftovers", "- Body Slam\n- Knock Off\n- Protect\n- Substitute")
    states = ec.run_showdown(BLISSEY + "\n\n" + regigigas, CORVIKNIGHT + "\n\n" + GARCHOMP_SD,
                             [("switch 2", "move uturn")])  # fmt: skip
    assert states[1]["sides"][1]["request"] == "switch"
    assert _keys(_full(states, 0, "regigigas", "uturn", (2, 2)), "slowstart") == {}


# (level 77, as the random battles': the stat formula's rounding then depends on the IV)
TERAPAGOS_0ATK = TERAPAGOS.replace("EVs: 252 HP / 252 SpA / 4 SpD", "Level: 77\nEVs: 252 HP / 252 SpA / 4 SpD\nIVs: 0 Atk")


def test_l203_forme_stats_from_inferred_ivs():
    states = ec.run_showdown(GARCHOMP_SD, BLISSEY + "\n\n" + TERAPAGOS_0ATK, [("move swordsdance", "switch 2")])
    assert _keys(_full(states, 0, "swordsdance", "terapagos", (1, 2)), "attack", "defense", "special") == {}


def test_l203_sunsteel_strike_through_tera_shell():
    solgaleo = _attacker("Solgaleo", "Full Metal Body", "Leftovers", "- Sunsteel Strike\n- Morning Sun\n- Flare Blitz\n- Knock Off")
    states = ec.run_showdown(solgaleo, BLISSEY + "\n\n" + TERAPAGOS, [("move sunsteelstrike", "switch 2")])
    assert _keys(_full_moves(states, 0, "sunsteelstrike", "terapagos", (1, 2)), "hp") == {}


# L204 (doc/engine-diff.md): Cud Chew eats its berry again at the next turn's end (Showdown's
# counter 2 from a berry eaten in the turn)
def test_l204_cud_chew():
    tauros = _attacker("Tauros-Paldea-Aqua", "Cud Chew", "Sitrus Berry", "- Wave Crash\n- Close Combat\n- Bulk Up\n- Protect")
    turns = [("move bulkup", "move seismictoss")] * 4
    states = ec.run_showdown(tauros, BLISSEY, turns)
    k = next(k for k in range(len(states) - 1) if states[k + 1]["sides"][0]["mons"][0]["last_item"] == "sitrusberry")
    assert any("Cud Chew" in x for x in states[k + 2]["log"])
    for j in (k, k + 1):
        assert _keys(_full(states, j, "bulkup", "seismictoss"), "hp", "item", "cudchew") == {}


BLISSEY_TOXIC = BLISSEY.replace("- Calm Mind", "- Toxic")


def test_l204_cud_chew_residual_berry():
    # a berry eaten in the end-of-turn residuals (Sitrus after the poison) counts 1, eaten again at
    # the next turn's end (Showdown: the queue is empty there)
    tauros = _attacker("Tauros-Paldea-Aqua", "Cud Chew", "Sitrus Berry", "- Wave Crash\n- Close Combat\n- Bulk Up\n- Protect")
    turns = [("move bulkup", "move toxic"), ("move bulkup", "move seismictoss")] + [("move bulkup", "move protect")] * 2
    states = ec.run_showdown(tauros, BLISSEY_TOXIC, turns)
    k = next(k for k in range(len(states) - 1) if states[k + 1]["sides"][0]["mons"][0]["last_item"] == "sitrusberry")
    log = states[k + 1]["log"]
    assert any("[from] psn" in x for x in log[: next(i for i, x in enumerate(log) if "Sitrus Berry|[eat]" in x)])
    assert any("Cud Chew" in x for x in states[k + 2]["log"])
    c2 = ("seismictoss", "protect")[k > 1]
    assert _keys(_full(states, k, "bulkup", c2), "hp", "item", "cudchew") == {}
    assert _keys(_full(states, k + 1, "bulkup", "protect"), "hp", "item", "cudchew") == {}


# L205 (doc/engine-diff.md): a locking move (Outrage) as Showdown's lockedmove -- 2 or 3 uses
# (trueDuration random(2, 4)), the last use ending it after the move with the confusion
# (onAfterMove), an interrupted lock confusing on its drawn last turn only, an asleep user's lock
# going after Yawn's sleep (its residual is the last), the fatigue's confusion stopped by Own Tempo
SALAMENCE_OUTRAGE = _attacker("Salamence", "Intimidate", "Leftovers", "- Outrage\n- Roost\n- Protect\n- Earthquake")
SLOWKING_YAWN = _attacker("Slowking", "Oblivious", "Leftovers", "- Yawn\n- Slack Off\n- Protect\n- Fake Out", "Bold")
SEED_TWO_USES = "gen5,1234,5678,910,1112"  # (the default seed draws 3)


def test_l205_lock_ends_after_its_last_use():
    states = ec.run_showdown(SALAMENCE_OUTRAGE, CORVIKNIGHT + "\n\n" + BLISSEY,
                             [("move outrage", "move roost"), ("move outrage", "move uturn")], seed=SEED_TWO_USES)  # fmt: skip
    assert any("[fatigue]" in x for x in states[2]["log"]) and states[2]["sides"][1]["request"] == "switch"
    assert _keys(_full(states, 1, "outrage", "uturn", (1, 2)), "lockedmove", "confusion") == {}


def test_l205_lock_length_drawn():
    states = ec.run_showdown(SALAMENCE_OUTRAGE, CORVIKNIGHT, [("move outrage", "move roost")])
    outs = ec.engine_outcomes(ec.engine_state(states[0]), "outrage", "roost")
    counts = {}
    for o in outs:
        n = o[1].side_one.volatile_status_durations.lockedmove
        counts[n] = counts.get(n, 0) + o[0]
    assert set(counts) == {1, 2} and abs(counts[1] - counts[2]) < 1e-6


def test_l205_lock_asleep_after_yawn():
    corviknight = CORVIKNIGHT.replace("- Defog", "- Yawn")
    states = ec.run_showdown(SALAMENCE_OUTRAGE, corviknight, [("move outrage", "move yawn"), ("move outrage", "move roost")])
    assert states[2]["sides"][0]["mons"][0]["status"] == "slp"
    assert _keys(_full(states, 1, "outrage", "roost"), "lockedmove", "confusion", "status") == {}


@pytest.mark.parametrize("seed, confused", [(None, False), (SEED_TWO_USES, True)])
def test_l205_lock_interrupted(seed, confused):
    states = ec.run_showdown(SALAMENCE_OUTRAGE, BLISSEY + "\n\n" + SLOWKING_YAWN,
                             [("move outrage", "switch 2"), ("move outrage", "move fakeout")],
                             **({"seed": seed} if seed else {}))  # fmt: skip
    assert any("flinch" in x for x in states[2]["log"])
    assert ("confusion" in states[2]["sides"][0]["mons"][0]["volatiles"]) == confused
    assert _keys(_full(states, 1, "outrage", "fakeout"), "lockedmove", "confusion") == {}


def test_l205_fatigue_through_own_tempo():
    sala = SALAMENCE_OUTRAGE.replace("Ability: Intimidate", "Ability: Own Tempo")
    states = ec.run_showdown(sala, CORVIKNIGHT, [("move outrage", "move roost")] * 2, seed=SEED_TWO_USES)
    assert "lockedmove" not in states[2]["sides"][0]["mons"][0]["volatiles"]
    assert _keys(_full(states, 1, "outrage", "roost"), "lockedmove", "confusion") == {}


# L206 (doc/engine-diff.md): Yawn's sleep at the end of the turn through a Substitute and a
# Safeguard set after it (Showdown's trySetStatus from the residual: no move hits, Safeguard's
# onSetStatus skips Yawn); Mycelium Might's status moves last in their bracket (-0.1, Showdown's
# onFractionalPriority)
@pytest.mark.parametrize("move", ["substitute", "safeguard"])
def test_l206_yawn_sleep_through(move):
    corviknight = CORVIKNIGHT.replace("- Defog", "- Yawn")
    blissey = BLISSEY.replace("- Calm Mind", "- " + move.capitalize())
    states = ec.run_showdown(corviknight, blissey, [("move yawn", "move softboiled"), ("move roost", "move " + move)])
    assert states[2]["sides"][1]["mons"][0]["status"] == "slp"
    assert _keys(_full(states, 1, "roost", move), "status", "sleep") == {}


def test_l206_mycelium_might_status_move_last():
    toedscruel = _attacker("Toedscruel", "Mycelium Might", "Leftovers", "- Spore\n- Earth Power\n- Giga Drain\n- Rapid Spin", "Timid")
    states = ec.run_showdown(toedscruel, BLISSEY, [("move spore", "move seismictoss")])
    log = [x for x in states[1]["log"] if x.startswith("|move|")]
    assert "Blissey" in log[0]
    assert _keys(_full(states, 0, "spore", "seismictoss"), "hp", "status") == {}


def test_l206_throat_chop_stops_a_sound_move_this_turn():
    chienpao = _attacker("Chien-Pao", "Sword of Ruin", "Leftovers", "- Throat Chop\n- Icicle Crash\n- Sacred Sword\n- Swords Dance", "Jolly")
    blissey = BLISSEY.replace("- Calm Mind", "- Hyper Voice")
    states = ec.run_showdown(chienpao, blissey, [("move throatchop", "move hypervoice")])
    assert any("|cant|p2a: Blissey|move: Throat Chop" in x for x in states[1]["log"])
    assert _keys(_full_hinted(states, 0, "throatchop", "hypervoice"), "hp", "pp", "last_used_move") == {}


def test_l206_explosion_user_flinched_does_not_faint():
    golem = _attacker("Golem", "Sturdy", "Leftovers", "- Explosion\n- Earthquake\n- Stone Edge\n- Stealth Rock")
    excadrill = _attacker("Excadrill", "Sand Rush", "Leftovers", "- Iron Head\n- Earthquake\n- Rapid Spin\n- Swords Dance", "Jolly")
    states = ec.run_showdown(golem, excadrill, [("move explosion", "move ironhead")], force_random=True)
    assert any("|cant|p1a: Golem|flinch" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "explosion", "ironhead"), "status") == {}


@pytest.mark.parametrize("move, item", [("Aqua Ring", "Heavy-Duty Boots"), ("Ingrain", "Heavy-Duty Boots"), ("Aqua Ring", "Big Root")])
def test_l206_aqua_ring_ingrain_heal(move, item):
    blissey = BLISSEY.replace("- Calm Mind", "- " + move).replace("@ Heavy-Duty Boots", "@ " + item)
    mid = ec._id(move)
    states = ec.run_showdown(blissey, BLISSEY, [("move " + mid, "move seismictoss"), ("move protect", "move seismictoss")])
    for k, c1 in ((0, mid), (1, "protect")):
        assert _keys(_full(states, k, c1, "seismictoss"), "hp") == {}


def test_l206_failed_sucker_punch_keeps_disguise():
    mimikyu = _attacker("Mimikyu", "Disguise", "Leftovers", "- Shadow Sneak\n- Play Rough\n- Swords Dance\n- Shadow Claw", "Jolly")
    kingambit = _attacker("Kingambit", "Supreme Overlord", "Leftovers", "- Sucker Punch\n- Iron Head\n- Kowtow Cleave\n- Swords Dance")
    states = ec.run_showdown(mimikyu, kingambit, [("move shadowsneak", "move suckerpunch")])
    assert any("|-fail|p2a: Kingambit" in x for x in states[1]["log"])
    assert _keys(_full_hinted(states, 0, "shadowsneak", "suckerpunch"), "hp", "id") == {}


def test_l206_clear_body_under_neutralizing_gas():
    weezing = _attacker("Weezing-Galar", "Neutralizing Gas", "Leftovers", "- Defog\n- Strange Steam\n- Will-O-Wisp\n- Pain Split", "Bold")
    metagross = _attacker("Metagross", "Clear Body", "Leftovers", "- Bullet Punch\n- Meteor Mash\n- Earthquake\n- Agility")
    states = ec.run_showdown(weezing, metagross, [("move defog", "move agility")])
    assert _keys(_full(states, 0, "defog", "agility"), "boost") == {}


def test_l206_ruin_not_on_a_holder_of_the_same():
    chienpao = _attacker("Chien-Pao", "Sword of Ruin", "Leftovers", "- Throat Chop\n- Icicle Crash\n- Sacred Sword\n- Swords Dance", "Jolly")
    tinglu = _attacker("Ting-Lu", "Vessel of Ruin", "Leftovers", "- Earth Power\n- Ruination\n- Whirlwind\n- Stealth Rock", "Modest")
    for p1, p2, c1, c2 in ((chienpao, chienpao, "throatchop", "swordsdance"), (tinglu, tinglu, "earthpower", "stealthrock")):
        states = ec.run_showdown(p1, p2, [(f"move {c1}", f"move {c2}")])
        assert _keys(_full_hinted(states, 0, c1, c2), "hp") == {}



# L207 (doc/engine-diff.md): Infiltrator's status move through a Substitute; Topsy-Turvy bounced
# by Magic Bounce; a transformed mon's ability back as it leaves under the foe's Neutralizing Gas;
# Heavy Metal in Heat Crash's weights; Minimize / Double Team's evasion; Immunity's cure once the
# gas has gone (Showdown's onUpdate)
def test_l207_infiltrator_status_through_substitute():
    blissey = BLISSEY.replace("- Calm Mind", "- Substitute")
    dragapult = _attacker("Dragapult", "Infiltrator", "Leftovers", "- Will-O-Wisp\n- Shadow Ball\n- Protect\n- Hex", "Timid")
    states = ec.run_showdown(blissey, dragapult, [("move substitute", "move protect"), ("move softboiled", "move willowisp")],
                             force_random=True)  # fmt: skip
    assert states[2]["sides"][0]["mons"][0]["status"] == "brn"
    assert _keys(_full(states, 1, "softboiled", "willowisp"), "status", "hp") == {}


def test_l207_topsy_turvy_bounced():
    malamar = _attacker("Malamar", "Suction Cups", "Leftovers", "- Topsy-Turvy\n- Swords Dance\n- Superpower\n- Knock Off")
    hatterene = _attacker("Hatterene", "Magic Bounce", "Leftovers", "- Calm Mind\n- Psyshock\n- Draining Kiss\n- Protect", "Quiet")
    states = ec.run_showdown(malamar, hatterene, [("move swordsdance", "move calmmind"), ("move topsyturvy", "move calmmind")])
    assert states[2]["sides"][0]["mons"][0]["boosts"]["atk"] == -2
    assert _keys(_full(states, 1, "topsyturvy", "calmmind"), "boost") == {}


def test_l207_transformed_ability_back_under_gas():
    weezing = _attacker("Weezing-Galar", "Neutralizing Gas", "Leftovers", "- Defog\n- Strange Steam\n- Will-O-Wisp\n- Pain Split", "Bold")
    mew = _attacker("Mew", "Synchronize", "Leftovers", "- Transform\n- Soft-Boiled\n- Psychic\n- Protect", "Bold")
    states = ec.run_showdown(weezing, mew + "\n\n" + BLISSEY, [("move defog", "move transform"), ("move defog", "switch 2")])
    assert _keys(_full(states, 1, "defog", "blissey", (1, 2)), "ability") == {}


def test_l207_heat_crash_heavy_metal():
    copperajah = _attacker("Copperajah", "Heavy Metal", "Leftovers", "- Heat Crash\n- Iron Head\n- Stealth Rock\n- Knock Off")
    ironhands = _attacker("Iron Hands", "Quark Drive", "Leftovers", "- Swords Dance\n- Drain Punch\n- Wild Charge\n- Ice Punch")
    states = ec.run_showdown(copperajah, ironhands, [("move heatcrash", "move swordsdance")])
    assert _keys(_full_hinted(states, 0, "heatcrash", "swordsdance"), "hp") == {}


@pytest.mark.parametrize("move", ["minimize", "doubleteam"])
def test_l207_evasion_raised(move):
    blissey = BLISSEY.replace("- Calm Mind", "- " + {"minimize": "Minimize", "doubleteam": "Double Team"}[move])
    states = ec.run_showdown(blissey, CORVIKNIGHT, [("move " + move, "move roost")])
    assert _keys(_full(states, 0, move, "roost"), "boost") == {}


def test_l207_immunity_cures_once_the_gas_goes():
    snorlax = _attacker("Snorlax", "Immunity", "Leftovers", "- Body Slam\n- Rest\n- Curse\n- Protect", "Careful")
    weezing = _attacker("Weezing-Galar", "Neutralizing Gas", "Leftovers", "- Toxic\n- Strange Steam\n- Will-O-Wisp\n- Pain Split", "Bold")
    states = ec.run_showdown(snorlax, weezing + "\n\n" + BLISSEY, [("move curse", "move toxic"), ("move curse", "switch 2")])
    assert states[1]["sides"][0]["mons"][0]["status"] == "tox" and states[2]["sides"][0]["mons"][0]["status"] == ""
    assert _keys(_full(states, 1, "curse", "blissey", (1, 2)), "status") == {}


def test_l207_topsy_turvy_on_the_foe():
    malamar = _attacker("Malamar", "Suction Cups", "Leftovers", "- Topsy-Turvy\n- Swords Dance\n- Superpower\n- Knock Off")
    hatterene = _attacker("Hatterene", "Healer", "Leftovers", "- Calm Mind\n- Psyshock\n- Draining Kiss\n- Protect", "Quiet")
    states = ec.run_showdown(malamar, hatterene, [("move swordsdance", "move calmmind"), ("move topsyturvy", "move calmmind")])
    assert states[2]["sides"][1]["mons"][0]["boosts"]["spa"] == 0  # (+1, inverted, then +1)
    assert _keys(_full(states, 1, "topsyturvy", "calmmind"), "boost") == {}


# L208 (doc/engine-diff.md): a fainted Air Lock holder suppresses no weather; Soul-Heart for a
# faint at the end of the turn; a status move misses a semi-invulnerable target; Flame Body on
# Counter's contact
def test_l208_air_lock_fainted():
    blissey = BLISSEY.replace("Ability: Natural Cure", "Ability: Sand Stream")
    rayquaza = _attacker("Rayquaza", "Air Lock", "Leftovers", "- Memento\n- Dragon Dance\n- Outrage\n- Extreme Speed", "Jolly")
    states = ec.run_showdown(blissey, rayquaza + "\n\n" + BLISSEY, [("move calmmind", "move memento")])
    assert any("[from] Sandstorm" in x and "p1a" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "calmmind", "memento", (1, 2)), "hp") == {}


def test_l208_soul_heart_residual_faint():
    magearna = _attacker("Magearna", "Soul-Heart", "Leftovers", "- Sandstorm\n- Flash Cannon\n- Protect\n- Calm Mind", "Modest")
    shedinja = _attacker("Shedinja", "Wonder Guard", "Leftovers", "- Swords Dance\n- Shadow Sneak\n- X-Scissor\n- Protect")
    states = ec.run_showdown(magearna, shedinja + "\n\n" + BLISSEY, [("move sandstorm", "move swordsdance")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["spa"] == 1
    assert _keys(_full(states, 0, "sandstorm", "swordsdance", (1, 2)), "boost") == {}


def test_l208_trick_misses_a_semi_invulnerable_target():
    blissey = BLISSEY.replace("- Calm Mind", "- Trick")
    dragapult = _attacker("Dragapult", "Clear Body", "Leftovers", "- Phantom Force\n- Dragon Darts\n- U-turn\n- Protect", "Jolly")
    states = ec.run_showdown(blissey, dragapult, [("move trick", "move phantomforce")])
    assert any("|-miss|p1a: Blissey" in x for x in states[1]["log"])
    assert _keys(_full(states, 0, "trick", "phantomforce"), "item") == {}


def test_l208_curse_on_its_user_through_a_semi_invulnerable_foe():
    snorlax = _attacker("Snorlax", "Thick Fat", "Leftovers", "- Curse\n- Body Slam\n- Rest\n- Protect", "Careful")
    dragapult = _attacker("Dragapult", "Clear Body", "Leftovers", "- Phantom Force\n- Dragon Darts\n- U-turn\n- Protect", "Jolly")
    states = ec.run_showdown(snorlax, dragapult, [("move curse", "move phantomforce")])
    assert states[1]["sides"][0]["mons"][0]["boosts"]["atk"] == 1
    assert _keys(_full(states, 0, "curse", "phantomforce"), "boost") == {}


def test_l208_flame_body_on_counter():
    snorlax = _attacker("Snorlax", "Thick Fat", "Leftovers", "- Counter\n- Body Slam\n- Rest\n- Curse", "Careful")
    talonflame = _attacker("Talonflame", "Flame Body", "Heavy-Duty Boots", "- Brave Bird\n- Flare Blitz\n- U-turn\n- Roost", "Jolly")
    states = ec.run_showdown(snorlax, talonflame, [("move counter", "move bravebird")], force_random=True)
    assert states[1]["sides"][0]["mons"][0]["status"] == "brn"
    assert _keys(_full(states, 0, "counter", "bravebird"), "status") == {}



# L209 (doc/engine-diff.md): the move Sleep Talk calls branches on its damage as any (a knockout
# by some rolls: randbats3 b257-t7); Harvest's chance for each side (both Harvest holders:
# randbats b67-t11); a drain on a knockout (seed10k b69-t16); recoil rounded (wide2 b130-t8);
# Gastro Acid fails on a cantsuppress ability (wide200 b70-t6); Stuff Cheeks (wide2 b297-t23); a
# partial trap started again (the harness: seed10k b53-t21)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats3.jsonl", 257, 7, 80000),
    ("random_battle_teams_randbats.jsonl", 67, 11, 60000),
    ("random_battle_teams.jsonl", 69, 16, 10000),
    ("random_battle_teams_wide2.jsonl", 130, 8, 30000),
    ("random_battle_teams_wide200.jsonl", 70, 6, 40000),
    ("random_battle_teams_wide2.jsonl", 297, 23, 30000),
    ("random_battle_teams.jsonl", 53, 21, 10000),
])  # fmt: skip
def test_l209_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


def test_l209_gastro_acid_suppresses():
    blissey = BLISSEY.replace("- Calm Mind", "- Gastro Acid")
    excadrill = _attacker("Excadrill", "Sand Rush", "Leftovers", "- Earthquake\n- Iron Head\n- Rapid Spin\n- Swords Dance", "Jolly")
    rotom = _attacker("Rotom-Wash", "Levitate", "Leftovers", "- Hydro Pump\n- Volt Switch\n- Will-O-Wisp\n- Protect", "Bold")
    states = ec.run_showdown(blissey + "\n\n" + excadrill, rotom, [("move gastroacid", "move willowisp"), ("switch 2", "move willowisp"),
                                                               ("move earthquake", "move hydropump")])  # fmt: skip
    assert not any("ability: Levitate" in x for x in states[3]["log"])
    assert _keys(_full(states, 0, "gastroacid", "willowisp"), "ability") == {}
    assert _keys(_full_hinted(states, 2, "earthquake", "hydropump"), "hp", "ability") == {}


def test_l209_shell_bell_besides_drain():
    hariyama = _attacker("Hariyama", "Thick Fat", "Shell Bell", "- Drain Punch\n- Knock Off\n- Bullet Punch\n- Bulk Up")
    states = ec.run_showdown(hariyama, BLISSEY, [("move bulkup", "move seismictoss"), ("move drainpunch", "move seismictoss")])
    assert _keys(_full_hinted(states, 1, "drainpunch", "seismictoss"), "hp") == {}


# L210 (doc/engine-diff.md): Liquid Ooze's damage at most the drainer's HP (randbats2 b177-t49);
# No Retreat on a trapped user, no volatile (wide2 b54-t36); White Herb after the move, before a
# Red Card's drag (offmeta b132-t16), Unburden after it (randbats3 b47-t28); Wind Rider for its
# side's Tailwind (randbats3 b130-t9)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats2.jsonl", 177, 49, 70000),
    ("random_battle_teams_wide2.jsonl", 54, 36, 30000),
    ("random_battle_teams_offmeta.jsonl", 132, 16, 0),
    ("random_battle_teams_randbats3.jsonl", 47, 28, 80000),
    ("random_battle_teams_randbats3.jsonl", 130, 9, 80000),
])  # fmt: skip
def test_l210_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L211 (doc/engine-diff.md): Magic Room -- 5 turns, its user's again ends it (Showdown's
# pseudoWeather: the items have no effect, ignoringItem; moved items still move): no Leftovers, no
# Choice Scarf speed or lock, a Light Clay's screen 5 turns
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_forum.jsonl", 30, 2, 50000),
    ("random_battle_teams_forum.jsonl", 30, 4, 50000),
    ("random_battle_teams_forum.jsonl", 30, 5, 50000),
    ("random_battle_teams_offmeta.jsonl", 41, 14, 0),
    ("random_battle_teams_offmeta.jsonl", 41, 15, 0),
    ("random_battle_teams_offmeta.jsonl", 41, 16, 0),
    ("random_battle_teams_offmeta.jsonl", 41, 17, 0),
])  # fmt: skip
def test_l211_magic_room_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


KLEFKI_ROOM = _attacker("Klefki", "Prankster", "Leftovers", "- Magic Room\n- Spikes\n- Thunder Wave\n- Play Rough", "Bold")


def test_l211_magic_room_leftovers_and_scarf():
    gholdengo = _attacker("Gholdengo", "Good as Gold", "Choice Scarf", "- Shadow Ball\n- Make It Rain\n- Recover\n- Nasty Plot", "Timid")
    states = ec.run_showdown(KLEFKI_ROOM, gholdengo, [("move magicroom", "move nastyplot"), ("move spikes", "move recover"),
                                                      ("move magicroom", "move shadowball")])  # fmt: skip
    for k, c1, c2 in ((0, "magicroom", "nastyplot"), (1, "spikes", "recover"), (2, "magicroom", "shadowball")):
        assert _keys(_full_hinted(states, k, c1, c2), "hp", "options", "magic_room", "boost") == {}


KINGAMBIT_ROOM = _attacker("Kingambit", "Defiant", "Leftovers", "- Magic Room\n- Kowtow Cleave\n- Sucker Punch\n- Iron Head")


@pytest.mark.parametrize("item, c2", [("Focus Sash", "calmmind"), ("Rocky Helmet", "calmmind")])
def test_l211_magic_room_sash_helmet(item, c2):
    alakazam = _attacker("Alakazam", "Synchronize", item, "- Psychic\n- Recover\n- Calm Mind\n- Protect", "Timid")
    hit = "kowtowcleave" if item == "Focus Sash" else "ironhead"
    states = ec.run_showdown(KINGAMBIT_ROOM, alakazam + "\n\n" + BLISSEY, [("move magicroom", "move calmmind"), (f"move {hit}", f"move {c2}")])
    assert _keys(_full_hinted(states, 1, hit, c2, (1, 2)), "hp", "item", "status") == {}


def test_l211_magic_room_heavy_duty_boots():
    states = ec.run_showdown(KLEFKI_ROOM, CORVIKNIGHT + "\n\n" + BLISSEY,
                             [("move spikes", "move roost"), ("move magicroom", "move roost"), ("move thunderwave", "switch 2")])  # fmt: skip
    assert any("[from] Spikes" in x for x in states[3]["log"])
    assert _keys(_full(states, 2, "thunderwave", "blissey", (1, 2)), "hp") == {}


# L211: Gravity -- 5 turns (fails while there is one); everyone grounded (Ground moves hit Flying
# types and Levitate, the hazards and terrains reach them), accuracy x 5 / 3, the gravity moves
# (High Jump Kick, Fly, ...) unusable
def test_l211_gravity_position():
    a, b = _random_position("random_battle_teams.jsonl", 189, 18, 10000)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


@pytest.mark.parametrize("foe", ["corviknight", "rotom"])
def test_l211_gravity_grounds(foe):
    blissey = BLISSEY.replace("- Calm Mind", "- Gravity").replace("- Protect", "- Earthquake")
    rotom = _attacker("Rotom-Wash", "Levitate", "Leftovers", "- Hydro Pump\n- Volt Switch\n- Will-O-Wisp\n- Protect", "Bold")
    p2, c2 = (CORVIKNIGHT, "roost") if foe == "corviknight" else (rotom, "willowisp")
    states = ec.run_showdown(blissey, p2, [("move gravity", "move " + c2), ("move earthquake", "move " + c2)])
    assert not any("|-immune|" in x for x in states[2]["log"])
    assert _keys(_full_hinted(states, 0, "gravity", c2), "gravity") == {}
    assert _keys(_full_hinted(states, 1, "earthquake", c2), "hp", "gravity") == {}


# L212 (doc/engine-diff.md): the harness's roll hints (enginecheck.roll_hints; the search never
# sets them) -- a confusion self-hit (main b245-t6), a Future Sight hit (seed10k b1-t26), each hit
# of a multi-hit move, a crit's too (main b123-t5, wide b24-t6, wide2 b190-t5: one hit); Rivalry
# (random b113-t2 / t3)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams.jsonl", 245, 6, 0),
    ("random_battle_teams.jsonl", 1, 26, 10000),
    ("random_battle_teams.jsonl", 123, 5, 0),
    ("random_battle_teams_wide.jsonl", 24, 6, 0),
    ("random_battle_teams_wide2.jsonl", 190, 5, 30000),
    ("random_battle_teams_random.jsonl", 113, 2, 0),
    ("random_battle_teams_random.jsonl", 113, 3, 0),
])  # fmt: skip
def test_l212_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


@pytest.mark.parametrize("foe_gender", ["M", "F"])
def test_l212_rivalry(foe_gender):
    haxorus = _attacker("Haxorus (M)", "Rivalry", "Leftovers", "- Dragon Claw\n- Swords Dance\n- Earthquake\n- Iron Tail")
    garchomp = _attacker(f"Garchomp ({foe_gender})", "Rough Skin", "Leftovers", "- Earthquake\n- Swords Dance\n- Protect\n- Dragon Claw")
    states = ec.run_showdown(haxorus, garchomp, [("move earthquake", "move swordsdance")])
    assert _keys(_full_hinted(states, 0, "earthquake", "swordsdance"), "hp") == {}


# L213 (doc/engine-diff.md): Heal Block / Disable after an asleep mover's sleep (randbats b137-t31);
# Disguise once the move's type is final (Weather Ball in rain: seed10k b199-t3); a transformed
# mon's own moves for the last used move (wide2 b184-t17); Guard Swap (offmeta b180-t13); Beat Up's
# hits by their hitters (random b50-t6); a multi-hit move breaking the Substitute (offmeta
# b169-t3, the harness); Big Nugget's Fling (wide2 b54-t12)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats.jsonl", 137, 31, 60000),
    ("random_battle_teams.jsonl", 199, 3, 10000),
    ("random_battle_teams_wide2.jsonl", 184, 17, 30000),
    ("random_battle_teams_offmeta.jsonl", 180, 13, 0),
    ("random_battle_teams_random.jsonl", 50, 6, 0),
    ("random_battle_teams_offmeta.jsonl", 169, 3, 0),
    ("random_battle_teams_wide2.jsonl", 54, 12, 30000),
])  # fmt: skip
def test_l213_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


@pytest.mark.parametrize("move", ["Guard Swap", "Power Swap", "Heart Swap"])
def test_l213_stage_swaps(move):
    blissey = BLISSEY.replace("- Calm Mind", "- " + move).replace("- Protect", "- Calm Mind")
    sala = _attacker("Salamence", "Moxie", "Leftovers", "- Dragon Dance\n- Iron Defense\n- Roost\n- Outrage")
    mid = ec._id(move)
    states = ec.run_showdown(blissey, sala, [("move calmmind", "move dragondance"), ("move calmmind", "move irondefense"),
                                             (f"move {mid}", "move roost")])  # fmt: skip
    assert _keys(_full(states, 2, mid, "roost"), "boost") == {}


# L214 (doc/engine-diff.md), from the randbats4 / randbats5 sets: Lash Out not after Haze (a
# direct set, SetBoost); a field move hits no absorbing ability (Sunny Day, Well-Baked Body);
# Leech Seed into Liquid Ooze; a Sleep Talk its user woke up for (its PP, its last move); Tera
# Shell on a transformed mon; White Herb after a switch-in's Intimidate; Soul-Heart for a foe its
# own Life Orb knocked out; Toxic Spikes absorbed by a Poison type before the foe's Corrosion;
# Encore on Dynamax Cannon (failencore); Fake Out after a turn out stopped by a flinch (none, not
# its switch-in); a move Magic Bounce sends into Volt Absorb; Protosynthesis on a transformed mon
# (notransform)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats4.jsonl", 155, 45, 90000),
    ("random_battle_teams_randbats4.jsonl", 199, 7, 90000),
    ("random_battle_teams_randbats4.jsonl", 203, 53, 90000),
    ("random_battle_teams_randbats4.jsonl", 229, 14, 90000),
    ("random_battle_teams_randbats4.jsonl", 49, 35, 90000),
    ("random_battle_teams_randbats4.jsonl", 99, 22, 90000),
    ("random_battle_teams_randbats5.jsonl", 130, 5, 100000),
    ("random_battle_teams_randbats5.jsonl", 155, 23, 100000),
    ("random_battle_teams_randbats5.jsonl", 189, 19, 100000),
    ("random_battle_teams_randbats5.jsonl", 198, 18, 100000),
    ("random_battle_teams_randbats5.jsonl", 46, 25, 100000),
    ("random_battle_teams_randbats5.jsonl", 56, 10, 100000),
])  # fmt: skip
def test_l214_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L215 (doc/engine-diff.md), from randbats6: Flame Body at each hit of a multi-hit move (its
# chance compounded; the harness's hints by the burned rolls after it: randbats6 b107-t1, main
# b162-t2); Psychic Terrain against a Prankster Encore; Bug Bite eats the target's berry; a Choice
# item Pickpocket takes starts unlocked; a lock's end keeps a Disable's move disabled
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats6.jsonl", 107, 1, 110000),
    ("random_battle_teams.jsonl", 162, 2, 0),
    ("random_battle_teams_randbats6.jsonl", 130, 20, 110000),
    ("random_battle_teams_randbats6.jsonl", 163, 1, 110000),
    ("random_battle_teams_randbats6.jsonl", 266, 12, 110000),
    ("random_battle_teams_randbats6.jsonl", 28, 17, 110000),
])  # fmt: skip
def test_l215_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L216 (doc/engine-diff.md), from randbats8 / randbats9: a terastallized Morpeko-Hangry stays
# Hangry; Yawn on Comatose; a Lum Berry at Yawn's sleep before a lock's residual; Eviolite only on
# a mon that can evolve; Orichalcum Pulse under Air Lock; Shield Dust against Throat Chop;
# Moongeist Beam through Disguise; Photon Geyser through Unaware; Meteor Beam with no target;
# Soul-Heart after the move's own drop
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats8.jsonl", 190, 3, 130000),
    ("random_battle_teams_randbats8.jsonl", 2, 20, 130000),
    ("random_battle_teams_randbats8.jsonl", 244, 3, 130000),
    ("random_battle_teams_randbats9.jsonl", 147, 19, 140000),
    ("random_battle_teams_randbats9.jsonl", 247, 11, 140000),
    ("random_battle_teams_randbats9.jsonl", 261, 7, 140000),
    ("random_battle_teams_randbats9.jsonl", 296, 15, 140000),
    ("random_battle_teams_randbats9.jsonl", 88, 41, 140000),
    ("random_battle_teams_randbats9.jsonl", 184, 5, 140000),
    ("random_battle_teams_randbats9.jsonl", 226, 45, 140000),
])  # fmt: skip
def test_l216_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L217 (doc/engine-diff.md), from randbats10 / randbats11: Early Bird's sleep counter (the
# harness: Showdown's runs twice as fast); a failed Thunderclap into Volt Absorb heals nothing; a
# recharge put off by the foe's U-turn waits for its switch
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats10.jsonl", 21, 3, 150000),
    ("random_battle_teams_randbats10.jsonl", 60, 24, 150000),
    ("random_battle_teams_randbats11.jsonl", 146, 6, 160000),
])  # fmt: skip
def test_l217_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L218 (doc/engine-diff.md): both switching at the same speed, either may leave first (random b165-t19:
# a Ditto with its target's Speed); Libero on a transformed mon (its own mark, not the type change:
# seed10k b232-t27); Doom Desire's hit from a user that knows Future Sight too (the side's mark:
# wide200 b76-t17); the mark goes with the ability (Skill Swap: offmeta b1-t29)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_random.jsonl", 165, 19, 0),
    ("random_battle_teams_offmeta.jsonl", 1, 29, 0),
    ("random_battle_teams.jsonl", 232, 27, 10000),
    ("random_battle_teams_wide200.jsonl", 76, 17, 40000),
])  # fmt: skip
def test_l218_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


def test_l218_state_string_keeps_doom_desire():
    from pathlib import Path
    s = pe.State.from_string(Path("tests/fixtures/engine_state_6v6.txt").read_text().splitlines()[0])
    s1 = s.side_one
    side = pe.Side(pokemon=s1.pokemon, active_index=s1.active_index, side_conditions=s1.side_conditions,
                   future_sight=(2, pe.PokemonIndex("1")), future_doom=True)  # fmt: skip
    t = pe.State(side_one=side, side_two=s.side_two).to_string()
    assert pe.State.from_string(t).side_one.future_doom and pe.State.from_string(t).to_string() == t


# L219 (doc/engine-diff.md): a loafing Truant mon whose foe pivots first loafs after the switch
# (randbats12 b170-t16: its volatile stays till then); a terastallized mon's type stays through
# Double Shock (Showdown's setType fails: randbats12 b63-t6); a confusion self-hit's rolls that KO
# (randbats13 b121-t20); Tinted Lens through Tera Shell's resistance (randbats13 b127-t40 /
# b127-t43); Future Sight's hit attacks its target (times attacked: randbats13 b137-t7); a Mold
# Breaker's drop through Clear Body (randbats13 b32-t35)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats12.jsonl", 170, 16, 170000),
    ("random_battle_teams_randbats12.jsonl", 63, 6, 170000),
    ("random_battle_teams_randbats13.jsonl", 121, 20, 180000),
    ("random_battle_teams_randbats13.jsonl", 127, 40, 180000),
    ("random_battle_teams_randbats13.jsonl", 127, 43, 180000),
    ("random_battle_teams_randbats13.jsonl", 137, 7, 180000),
    ("random_battle_teams_randbats13.jsonl", 32, 35, 180000),
])  # fmt: skip
def test_l219_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L220 (doc/engine-diff.md): an Encore on a move its Struggle replaced (randbats14 b170-t17: it
# panicked); Supreme Overlord counting the faints Revival Blessing undid (Showdown's totalFainted:
# randbats14 b146-t35); a Thunder Wave into Volt Absorb behind a Substitute (b197-t17); Judgment
# Normal without a plate (a transformed Ditto's: b236-t48 / t49 / t50); Hyperspace Fury through a
# Substitute (b58-t18 / t19); Roost's turn on a transformed mon (the harness's types: b72-t14); a
# Disable's end keeps an Outrage's lock (randbats15 b44-t14); a transformation copies the times
# attacked (b130-t11)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats14.jsonl", 170, 17, 190000),
    ("random_battle_teams_randbats14.jsonl", 146, 35, 190000),
    ("random_battle_teams_randbats14.jsonl", 197, 17, 190000),
    ("random_battle_teams_randbats14.jsonl", 236, 48, 190000),
    ("random_battle_teams_randbats14.jsonl", 236, 49, 190000),
    ("random_battle_teams_randbats14.jsonl", 236, 50, 190000),
    ("random_battle_teams_randbats14.jsonl", 58, 18, 190000),
    ("random_battle_teams_randbats14.jsonl", 58, 19, 190000),
    ("random_battle_teams_randbats14.jsonl", 72, 14, 190000),
    ("random_battle_teams_randbats15.jsonl", 44, 14, 200000),
    ("random_battle_teams_randbats15.jsonl", 130, 11, 200000),
    # (an Arceus's plate gives Judgment its type before the target's ability sees it: Sap Sipper,
    # Disguise; randbats8 b188, randbats14 b18 / b200)
    ("random_battle_teams_randbats8.jsonl", 188, 11, 130000),
    ("random_battle_teams_randbats8.jsonl", 188, 52, 130000),
    ("random_battle_teams_randbats8.jsonl", 188, 53, 130000),
    ("random_battle_teams_randbats14.jsonl", 18, 12, 190000),
    ("random_battle_teams_randbats14.jsonl", 200, 12, 190000),
    ("random_battle_teams_randbats14.jsonl", 200, 14, 190000),
])  # fmt: skip
def test_l220_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


def test_l220_state_string_keeps_revived_faints():
    from pathlib import Path
    s = pe.State.from_string(Path("tests/fixtures/engine_state_6v6.txt").read_text().splitlines()[0])
    s1 = s.side_one
    side = pe.Side(pokemon=s1.pokemon, active_index=s1.active_index, side_conditions=s1.side_conditions,
                   revived_faints=2)  # fmt: skip
    t = pe.State(side_one=side, side_two=s.side_two).to_string()
    assert pe.State.from_string(t).side_one.revived_faints == 2 and pe.State.from_string(t).to_string() == t


# L221 (doc/engine-diff.md): Knock Off on a Lum Berry the hit's status secondary uses up first
# (Showdown's secondaries / DamagingHit before onAfterHit): Poison Touch (randbats16 b67-t30),
# Toxic Chain (randbats7 b219-t14, L215's known gap)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats16.jsonl", 67, 30, 210000),
    ("random_battle_teams_randbats7.jsonl", 219, 14, 120000),
])  # fmt: skip
def test_l221_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L222 (doc/engine-diff.md): Lash Out doubled on turn 1 by a lead's Intimidate (Showdown keeps
# statsLoweredThisTurn as turn 1 starts: randbats18 b132-t1 / b171-t1); Tinted Lens by the hit's
# stages (Roost's turn without Flying: b163-t22); Gulp Missile's forme at the hit, not for an
# asleep Cramorant (b169-t10 / b50-t46)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats18.jsonl", 132, 1, 230000),
    ("random_battle_teams_randbats18.jsonl", 171, 1, 230000),
    ("random_battle_teams_randbats18.jsonl", 163, 22, 230000),
    ("random_battle_teams_randbats18.jsonl", 169, 10, 230000),
    ("random_battle_teams_randbats18.jsonl", 50, 46, 230000),
])  # fmt: skip
def test_l222_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L223 (doc/engine-diff.md): an Infiltrator's Pain Split through a Substitute (randbats21 b120-t27 /
# t28); a transformed mon's copy of a 1-PP move at 1 PP (Revival Blessing: b294-t9)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats21.jsonl", 120, 27, 260000),
    ("random_battle_teams_randbats21.jsonl", 120, 28, 260000),
    ("random_battle_teams_randbats21.jsonl", 294, 9, 260000),
])  # fmt: skip
def test_l223_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L224 (doc/engine-diff.md): the remaining hard cases -- a used once-per-battle ability back on a
# switch-out after Worry Seed (Dauntless Shield: wide b208-t22); Uproar's three turns (its end:
# offmeta b25-t8)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_wide.jsonl", 208, 22, 0),
    ("random_battle_teams_offmeta.jsonl", 25, 8, 0),
    # (an Eject Pack a Sticky Web drop sets off at the switch-in: random b156-t7; a hit a
    # Substitute survives, its damage from the Substitute's HP -- the harness's hint: wide2 b278-t18)
    ("random_battle_teams_random.jsonl", 156, 7, 0),
    ("random_battle_teams_wide2.jsonl", 278, 18, 30000),
    # (a charge move Metronome started locks its user into it: the caller's slot -- Meteor Beam:
    # offmeta b49-t3 / t4)
    ("random_battle_teams_offmeta.jsonl", 49, 3, 0),
    ("random_battle_teams_offmeta.jsonl", 49, 4, 0),
    # (Power Split, called by Metronome: offmeta b49-t15)
    ("random_battle_teams_offmeta.jsonl", 49, 15, 0),
])  # fmt: skip
def test_l224_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


def test_l224_state_string_keeps_uproar_count():
    from pathlib import Path
    s = pe.State.from_string(Path("tests/fixtures/engine_state_6v6.txt").read_text().splitlines()[0])
    s1 = s.side_one
    side = pe.Side(pokemon=s1.pokemon, active_index=s1.active_index, side_conditions=s1.side_conditions,
                   volatile_statuses={"uproar"},
                   volatile_status_durations=pe.VolatileStatusDurations(uproar=1))  # fmt: skip
    t = pe.State(side_one=side, side_two=s.side_two).to_string()
    assert pe.State.from_string(t).side_one.volatile_status_durations.uproar == 1
    assert pe.State.from_string(t).to_string() == t


# L225 (doc/engine-diff.md): from randbats22 - 25 -- Glaive Rush's drawback stays till its user
# moves after a foe's pivot (randbats22 b119-t27); a move's heal of its user rounded (Recover's
# Math.round: b186-t26); a multi-hit move's knockout hit, the harness's KO hint (randbats24
# b161-t26); a Prankster Spikes in Psychic Terrain (b292-t4); a Spore Magic Bounce sends back
# into a Grass-type user (randbats25 b241-t36)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats22.jsonl", 119, 27, 270000),
    ("random_battle_teams_randbats22.jsonl", 186, 26, 270000),
    ("random_battle_teams_randbats24.jsonl", 161, 26, 290000),
    ("random_battle_teams_randbats24.jsonl", 292, 4, 290000),
    ("random_battle_teams_randbats25.jsonl", 241, 36, 300000),
])  # fmt: skip
def test_l225_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


# L226 (doc/engine-diff.md): from randbats26 - 33 -- multi-hit hits on a Substitute by the
# harness's share / break hints (randbats26 b136-t19, randbats30 b209-t22); Mirror Armor on a
# holder the hit knocked out (b161-t13); the harness's hint HP by the active slot, not an
# Illusion's shown name (b182-t18, randbats30 b205-t1); Unburden as a Trick takes its item
# (randbats27 b1-t10); Collision Course's 5461 / 4096 (randbats31 b170-t1); an asleep Truant mon's
# sleep before its loafing (randbats32 b159-t17 / t18); Sunsteel Strike through Sturdy (randbats33
# b111-t4); Shell Side Arm's tie drawn (b18-t6); Heal Block before Sap Sipper takes a Giga Drain
# (b296-t32); an Infiltrator's Leech Seed through a Substitute (b36-t24); a Poison type the
# hazards laid first knock out absorbs no Toxic Spikes (b64-t58)
@pytest.mark.parametrize("teams,i,turn,offset", [
    ("random_battle_teams_randbats26.jsonl", 136, 19, 310000),
    ("random_battle_teams_randbats30.jsonl", 209, 22, 350000),
    ("random_battle_teams_randbats26.jsonl", 161, 13, 310000),
    ("random_battle_teams_randbats26.jsonl", 182, 18, 310000),
    ("random_battle_teams_randbats30.jsonl", 205, 1, 350000),
    ("random_battle_teams_randbats27.jsonl", 1, 10, 320000),
    ("random_battle_teams_randbats31.jsonl", 170, 1, 360000),
    ("random_battle_teams_randbats32.jsonl", 159, 17, 370000),
    ("random_battle_teams_randbats32.jsonl", 159, 18, 370000),
    ("random_battle_teams_randbats33.jsonl", 111, 4, 380000),
    ("random_battle_teams_randbats33.jsonl", 18, 6, 380000),
    ("random_battle_teams_randbats33.jsonl", 296, 32, 380000),
    ("random_battle_teams_randbats33.jsonl", 36, 24, 380000),
    ("random_battle_teams_randbats33.jsonl", 64, 58, 380000),
])  # fmt: skip
def test_l226_positions(teams, i, turn, offset):
    a, b = _random_position(teams, i, turn, offset)
    c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
    outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2, ec.move_hints(a["state"], b["state"]))
    n = tuple(len(s["mons"]) for s in a["state"]["sides"])
    assert ec.closest(b["state"], outs, n, hp=True, full=True, start=a["state"])["diff"] == {}


def test_l226_state_string_keeps_toxic_spikes_order():
    from pathlib import Path
    s = pe.State.from_string(Path("tests/fixtures/engine_state_6v6.txt").read_text().splitlines()[0])
    s1 = s.side_one
    side = pe.Side(pokemon=s1.pokemon, active_index=s1.active_index,
                   side_conditions=pe.SideConditions(spikes=1, toxic_spikes=1, toxic_spikes_order=2))  # fmt: skip
    t = pe.State(side_one=side, side_two=s.side_two).to_string()
    assert pe.State.from_string(t).side_one.side_conditions.toxic_spikes_order == 2
    assert pe.State.from_string(t).to_string() == t

