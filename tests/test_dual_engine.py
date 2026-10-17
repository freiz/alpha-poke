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
