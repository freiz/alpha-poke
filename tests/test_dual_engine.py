"""Dual-engine unit tests (doc/engine-diff.md): a scenario run in Showdown's simulator and in
poke-engine from the same state (alpha_poke.enginecheck). A confirmed engine issue is an
``xfail(strict=True)`` test until it is fixed; the controls show the harness agrees where the
engines do."""

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
    p1 = _corviknight("Micle Berry").replace("- Brave Bird", "- Stone Edge")
    turns = [("move defog", "move ruination")] * 2
    states = ec.run_showdown(p1, TINGLU_HITS, turns, seed="gen5,5,5,5,5")
    assert "micleberry" in states[2]["sides"][0]["mons"][0]["volatiles"]  # Showdown
    outs = ec.engine_outcomes(ec.engine_state(states[1]), "defog", "ruination")
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
