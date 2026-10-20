"""The network inputs' claims (rust/alpha_search extra.rs, EXTRA_VERSION 3) against Showdown's
simulator on the same state: a feature that states an outcome (a damage, who moves first, a KO
within two hits, an answer in an exchange of hits) must agree with Showdown playing it out
(doc/engine-diff.md L230: the v7 review's cases, each wrong before). Showdown is the reference,
not the engine: the features' own computations (a multi-hit move's hits, the exchange of hits)
are not the engine's transitions. Battles with a crit or a miss are left out (the claims assume
neither) and replayed with the next seed."""

import hashlib
import shutil

import numpy as np
import pytest

from alpha_poke import enginecheck as ec

alpha_search = pytest.importorskip("alpha_search")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (ec.SIM / "index.js").exists(),
    reason="needs node and the built Showdown checkout (vendor/pokemon-showdown/dist/sim)",
)

DIMS = alpha_search.feature_dims()
EE, EN = DIMS["ent_extra"], DIMS["ent_new"]
TEAM = DIMS["ent_ko2"] + DIMS["ent_tera"]
# team's columns (extra.rs v7_entities), counts over the other side's mons x 6
TEAM_COLS = {"ko1": 0, "ko1_by": 1, "switch_in": 2, "switch_in_possible": 3, "head_to_head": 4,
             "revenge": 5, "switch_in_unknown": 6}  # fmt: skip


def mon(name, item, ability, moves, evs, nature, level=100, tera="Normal"):
    return (f"{name} @ {item}\nAbility: {ability}\nLevel: {level}\nTera Type: {tera}\nEVs: {evs}\n"
            f"{nature} Nature\n" + "\n".join(f"- {m}" for m in moves))  # fmt: skip


def features(sd: dict):
    """(entity extras [12, ENT_EXTRA], globals, v7 entities [12, ENT_NEW]) of Showdown's state,
    side one's view."""
    e, g, n = alpha_search.featurize_extra_full([ec.engine_state(sd).to_string()])
    return (np.frombuffer(e, "<f4").reshape(12, EE), np.frombuffer(g, "<f4"),
            np.frombuffer(n, "<f4").reshape(12, EN))  # fmt: skip


def hp(sd: dict, side: int, k: int | None = None) -> int:
    s = sd["sides"][side]
    return s["mons"][s["active"] if k is None else k]["hp"]


def clean_runs(p1, p2, turns, n=3):
    """Showdown's states for ``turns`` under seeds whose battle has no crit and no miss (n of
    them)."""
    out = []
    for i in range(200):
        seed = "sodium," + hashlib.sha256(str(i).encode()).hexdigest()[:32]
        st = ec.run_showdown(p1, p2, turns, seed=seed)
        if not any("|-crit|" in x or "|-miss|" in x for s in st for x in s["log"]):
            out.append(st)
            if len(out) == n:
                return out
    raise AssertionError("no clean seed")


SMEARGLE = mon("Smeargle", "Leftovers", "Own Tempo", ["Endeavor", "Final Gambit", "Pain Split", "Super Fang"],
               "252 HP / 252 Def / 4 SpD", "Bold", level=60)  # fmt: skip
BLISSEY = mon("Blissey", "Heavy-Duty Boots", "Natural Cure", ["Calm Mind", "Seismic Toss", "Soft-Boiled", "Protect"],
              "252 HP / 252 Def / 4 SpD", "Bold")  # fmt: skip
DUSKNOIR = mon("Dusknoir", "Leftovers", "Pressure", ["Calm Mind", "Shadow Sneak", "Will-O-Wisp", "Protect"],
               "252 HP / 252 Def / 4 SpD", "Bold")  # fmt: skip


@pytest.mark.parametrize("target", ["blissey", "dusknoir"])
@pytest.mark.parametrize("slot,move", [(0, "endeavor"), (1, "finalgambit")])
def test_fixed_damage_immunity(slot, move, target):
    """Endeavor (Normal) / Final Gambit (Fighting): damage on a Normal target, none on a Ghost
    one (before: the other way round, a Ghost move's immunity)."""
    t = BLISSEY if target == "blissey" else DUSKNOIR
    st = ec.run_showdown(SMEARGLE, t, [], damage_probe=True)
    ent, _, _ = features(st[0])
    want = st[0]["damage"]["p1"][move] or 0
    assert round(float(ent[0, 4 + 4 * slot]) * hp(st[0], 1)) == want


GARCHOMP_SCALE = mon("Garchomp", "Life Orb", "Rough Skin", ["Scale Shot", "Earthquake", "Swords Dance", "Protect"],
                     "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip


def test_multi_hit_damage_range():
    """Scale Shot (2-5 hits): the max damage is 5 hits' (before: 1), and a Showdown use falls in
    [2 hits at the min roll, 5 at the max]."""
    st = ec.run_showdown(GARCHOMP_SCALE, BLISSEY, [], damage_probe=True)
    per_hit = st[0]["damage"]["p1"]["scaleshot"]
    ent, _, _ = features(st[0])
    top = float(ent[0, 4]) * hp(st[0], 1)
    assert round(top) == 5 * per_hit
    for run in clean_runs(GARCHOMP_SCALE, BLISSEY, [("move scaleshot", "move calmmind")]):
        dealt = hp(run[0], 1) - hp(run[1], 1)
        assert 2 * int(0.85 * per_hit) - 2 <= dealt <= top


@pytest.mark.parametrize("attacker,move,slot", [
    (SMEARGLE, "superfang", 3),
    (mon("Ting-Lu", "Leftovers", "Vessel of Ruin", ["Calm Mind", "Ruination", "Spikes", "Rest"],
         "252 HP / 252 Def / 4 SpD", "Bold"), "ruination", 1),
])  # fmt: skip
def test_ko2_hp_based_moves(attacker, move, slot):
    """Two Super Fangs / Ruinations halve the HP twice (714 -> 357 -> 179): no two-hit KO (before:
    2 x half the HP now, 'possibly')."""
    _, _, new = features(ec.run_showdown(attacker, BLISSEY, [])[0])
    assert list(new[0, 2 * slot:2 * slot + 2]) == [0.0, 0.0]
    st = ec.run_showdown(attacker, BLISSEY, [(f"move {move}", "move calmmind")] * 2,
                         force_random=True)  # fmt: skip
    assert hp(st[2], 1) > 0


TOXAPEX_SLUDGE = mon("Toxapex", "Black Sludge", "Regenerator", ["Haze", "Recover", "Toxic", "Infestation"],
                     "252 HP / 252 Def / 4 SpD", "Bold")  # fmt: skip
BLISSEY_TOSS = mon("Blissey", "Leftovers", "Natural Cure", ["Seismic Toss", "Calm Mind", "Soft-Boiled", "Protect"],
                   "252 HP / 252 Def / 4 SpD", "Bold", level=85)  # fmt: skip


def test_ko2_end_of_turn_by_current_types():
    """A Tera Normal Toxapex (Poison originally) loses 1/8 to Black Sludge at the end of the
    turn: two Seismic Tosses KO it from 181 HP (before: the original types, a heal, no KO)."""
    turns = [("move seismictoss", "move haze terastallize")] + [("move seismictoss", "move haze")] * 2
    st = ec.run_showdown(BLISSEY_TOSS, TOXAPEX_SLUDGE, turns)
    assert any("Black Sludge" in x for x in st[1]["log"])
    _, _, new = features(st[1])
    assert list(new[0, 0:2]) == [1.0, 1.0]
    assert hp(st[3], 1) == 0


def test_speed_slush_rush_in_snow():
    """Slush Rush doubles the speed in Snow (Snowscape) too: Cetitan moves before a Jolly
    Garchomp (before: hail only, the features had it slower)."""
    cetitan = mon("Cetitan", "Leftovers", "Slush Rush", ["Snowscape", "Icicle Crash", "Protect", "Earthquake"],
                  "252 HP / 252 Atk / 4 SpD", "Adamant")  # fmt: skip
    garchomp = mon("Garchomp", "Leftovers", "Rough Skin", ["Swords Dance", "Earthquake", "Protect", "Scale Shot"],
                   "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip
    st = ec.run_showdown(cetitan, garchomp, [("move snowscape", "move swordsdance"),
                                             ("move iciclecrash", "move earthquake")])  # fmt: skip
    moves = [x for x in st[2]["log"] if x.startswith("|move|")]
    assert moves[0].startswith("|move|p1a: Cetitan")
    _, glob, _ = features(st[1])
    assert glob[16] == 1.0  # who moves first between the actives: own


def test_focus_sash_holds_one_hit():
    """A full-HP Focus Sash holder survives a single hit at 1 HP: no 'KO possible' (before: the
    damage alone)."""
    garchomp = mon("Garchomp", "Choice Band", "Rough Skin", ["Earthquake", "Stone Edge", "Fire Fang", "Outrage"],
                   "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip
    heatran = mon("Heatran", "Focus Sash", "Flash Fire", ["Magma Storm", "Earth Power", "Taunt", "Protect"],
                  "4 HP / 252 SpA / 252 Spe", "Timid")  # fmt: skip
    st = clean_runs(garchomp, heatran, [("move earthquake", "move taunt")], n=1)[0]
    ent, _, _ = features(st[0])
    assert ent[0, 4] >= 1.0 and ent[0, 4 + 2] == 0.0  # max damage over its HP, no KO
    assert hp(st[1], 1) == 1


GARCHOMP = mon("Garchomp", "Leftovers", "Rough Skin", ["Earthquake", "Swords Dance", "Protect", "Substitute"],
               "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip
FODDER = mon("Magikarp", "Leftovers", "Swift Swim", ["Splash", "Tackle"], "4 HP", "Hardy")
ANSWERS = {
    "corviknight-bravebird": (mon("Corviknight", "Leftovers", "Pressure", ["Brave Bird", "Roost", "Defog", "Iron Defense"],
                                  "252 HP / 252 Atk / 4 SpD", "Adamant"), "bravebird"),
    "rotomwash-surf": (mon("Rotom-Wash", "Leftovers", "Levitate", ["Surf", "Volt Switch", "Will-O-Wisp", "Pain Split"],
                           "252 HP / 252 SpA / 4 SpD", "Modest"), "surf"),
    "corviknight-bodypress": (mon("Corviknight", "Leftovers", "Pressure", ["Body Press", "Roost", "Defog", "Iron Defense"],
                                  "252 HP / 252 Def / 4 SpD", "Impish"), "bodypress"),
    "skeledirge": (mon("Skeledirge", "Leftovers", "Unaware", ["Torch Song", "Slack Off", "Will-O-Wisp", "Hex"],
                       "252 HP / 252 SpA / 4 SpD", "Modest"), "torchsong"),
    # the review's case: slower, takes 82% a hit, deals 51% (the old definition's answer)
    "kingambit": (mon("Kingambit", "Leftovers", "Supreme Overlord", ["Iron Head", "Swords Dance", "Protect", "Substitute"],
                      "252 HP / 252 Atk / 4 SpD", "Adamant"), "ironhead"),
    # takes 34%, deals 62%, but Wave Crash's recoil and Rough Skin (the old definition's answer)
    "dondozo": (mon("Dondozo", "Leftovers", "Unaware", ["Wave Crash", "Rest", "Curse", "Sleep Talk"],
                    "252 HP / 252 Atk / 4 SpD", "Adamant"), "wavecrash"),
    "kyurem": (mon("Kyurem", "Leftovers", "Pressure", ["Ice Beam", "Substitute", "Protect", "Roost"],
                   "252 SpA / 4 SpD / 252 Spe", "Timid"), "icebeam"),
    "weavile-iceshard": (mon("Weavile", "Choice Band", "Pressure", ["Ice Shard", "Swords Dance", "Protect", "Substitute"],
                             "252 Atk / 4 SpD / 252 Spe", "Jolly"), "iceshard"),
}  # fmt: skip


def outcome(st: list[dict]) -> str:
    """The answer's (side one's last mon) result: 'win' (Garchomp down), 'lose', 'unknown'."""
    last = st[-1]
    if last["sides"][0]["mons"][-1]["hp"] == 0:
        return "lose"
    return "win" if last["sides"][1]["mons"][0]["hp"] == 0 else "unknown"


ROUNDS = 4  # (extra.rs ROUNDS)


@pytest.mark.parametrize("answer,claim,result", [
    ("corviknight-bravebird", 1, "win"),
    ("rotomwash-surf", 1, "win"),
    ("skeledirge", 0, "lose"),
    ("kingambit", 0, "lose"),
    ("dondozo", 0, "lose"),
])  # fmt: skip
def test_team_switch_in(answer, claim, result):
    """A reliable switch-in answer (the hazards, Garchomp's Earthquake first, then the exchange,
    each with its fixed move) against Garchomp: Showdown playing it out agrees."""
    a, m = ANSWERS[answer]
    p1 = FODDER + "\n\n" + a
    _, _, new = features(ec.run_showdown(p1, GARCHOMP, [])[0])
    assert new[1, TEAM + TEAM_COLS["switch_in"]] * 6 == claim
    turns = [("switch 2", "move earthquake")] + [(f"move {m}", "move earthquake")] * ROUNDS
    assert {outcome(st) for st in clean_runs(p1, GARCHOMP, turns)} == {result}


def test_team_switch_in_unresolved():
    """Body Press needs 5 hits: unresolved within the rounds (not lost), as in Showdown."""
    a, m = ANSWERS["corviknight-bodypress"]
    p1 = FODDER + "\n\n" + a
    _, _, new = features(ec.run_showdown(p1, GARCHOMP, [])[0])
    assert new[1, TEAM + TEAM_COLS["switch_in_unknown"]] * 6 == 1
    assert new[1, TEAM + TEAM_COLS["switch_in"]] == 0
    turns = [("switch 2", "move earthquake")] + [(f"move {m}", "move earthquake")] * ROUNDS
    assert {outcome(st) for st in clean_runs(p1, GARCHOMP, turns)} == {"unknown"}


@pytest.mark.parametrize("answer,claim,result", [
    ("kyurem", 1, "win"),
    ("kingambit", 0, "lose"),
    ("skeledirge", 0, "lose"),
])  # fmt: skip
def test_team_head_to_head(answer, claim, result):
    a, m = ANSWERS[answer]
    _, _, new = features(ec.run_showdown(a, GARCHOMP, [])[0])
    assert new[0, TEAM + TEAM_COLS["head_to_head"]] * 6 == claim
    turns = [(f"move {m}", "move earthquake")] * ROUNDS
    assert {outcome(st) for st in clean_runs(a, GARCHOMP, turns)} == {result}


@pytest.mark.parametrize("answer,claim", [("weavile-iceshard", 1), ("kyurem", 0)])
def test_team_revenge(answer, claim):
    """A revenge kill: in free after a faint, its first hit KOs before Garchomp acts (Ice Shard's
    priority); Kyurem is slower: Garchomp moves first (it wins the exchange, not a revenge kill)."""
    a, m = ANSWERS[answer]
    p1 = FODDER.replace("Level: 100", "Level: 1") + "\n\n" + a
    _, _, new = features(ec.run_showdown(p1, GARCHOMP, [])[0])
    assert new[1, TEAM + TEAM_COLS["revenge"]] * 6 == claim
    turns = [("move splash", "move earthquake"), ("switch 2", ""), (f"move {m}", "move earthquake")]
    for st in clean_runs(p1, GARCHOMP, turns):
        first = next(x for x in st[-1]["log"] if x.startswith("|move|"))
        revenged = first.startswith("|move|p1a") and hp(st[-1], 1) == 0
        assert revenged == bool(claim)


def test_sure_crit_damage():
    """Surging Strikes always crits, three hits: its damage is three crits' (before: three
    no-crit hits; before that one)."""
    urshifu = mon("Urshifu-Rapid-Strike", "Choice Band", "Unseen Fist", ["Surging Strikes", "Close Combat", "U-turn", "Aqua Jet"],
                  "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip
    st = ec.run_showdown(urshifu, BLISSEY, [("move surgingstrikes", "move calmmind")])
    ent, _, _ = features(st[0])
    top = float(ent[0, 4]) * hp(st[0], 1)
    dealt = hp(st[0], 1) - hp(st[1], 1)
    assert sum("|-crit|" in x for x in st[1]["log"]) == 3
    assert 0.85 * top - 3 <= dealt <= top + 1


# combinations (the second review): each fixed mechanism with another one


def test_multi_hit_through_a_substitute():
    """Dragon Darts (2 hits) on a Substituted Dragonite: the first hit breaks the Substitute (its
    excess lost), the second alone reaches the mon -- no KO, as in Showdown (before: the two hits'
    total less the Substitute's HP, 'KO possible')."""
    darts = mon("Dragapult", "Life Orb", "Clear Body", ["Dragon Darts", "Protect", "Sucker Punch", "Phantom Force"],
                "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip
    dnite = mon("Dragonite", "Heavy-Duty Boots", "Inner Focus", ["Substitute", "Protect", "Earthquake", "Dragon Dance"],
                "252 HP / 4 Def / 252 SpD", "Careful")  # fmt: skip
    st = ec.run_showdown(darts, dnite, [("move protect", "move substitute")])
    ent, _, _ = features(st[1])
    assert ent[0, 4] * hp(st[1], 1) > 1.4 * hp(st[1], 1)  # (2 hits' max well over its HP)
    assert ent[0, 5] == 0.0 and ent[0, 6] == 0.0
    for run in clean_runs(darts, dnite, [("move protect", "move substitute"),
                                         ("move dragondarts", "move dragondance")]):  # fmt: skip
        assert any("|-end|p2a: Dragonite|Substitute" in x for x in run[2]["log"])
        assert hp(run[2], 1) > 0


def test_switch_in_on_sucker_punch():
    """Sucker Punch fails on the turn its target switches in (no move): Enamorus comes in free,
    then takes one a round; by the rolls it wins with a few HP left or loses -- 'possibly', not
    'reliably'. One hit more on the entry (as before) would have lost it every time."""
    kingambit = mon("Kingambit", "Leftovers", "Pressure", ["Sucker Punch", "Swords Dance", "Protect", "Substitute"],
                    "252 HP / 252 Atk / 4 SpD", "Adamant")  # fmt: skip
    enamorus = mon("Enamorus", "Heavy-Duty Boots", "Cute Charm", ["Moonblast", "Calm Mind", "Protect", "Taunt"],
                   "4 HP / 252 SpA / 252 Spe", "Timid")  # fmt: skip
    p1 = FODDER + "\n\n" + enamorus
    _, _, new = features(ec.run_showdown(p1, kingambit, [])[0])
    assert new[1, TEAM + TEAM_COLS["switch_in"]] == 0
    assert new[1, TEAM + TEAM_COLS["switch_in_possible"]] * 6 == 1
    turns = [("switch 2", "move suckerpunch")] + [("move moonblast", "move suckerpunch")] * ROUNDS
    runs = clean_runs(p1, kingambit, turns, n=4)
    for st in runs:
        assert not any(x.startswith("|-damage|p1a") for x in st[1]["log"])  # the entry: no hit
    wins = [hp(st[-1], 0, 1) for st in runs if outcome(st) == "win"]
    assert wins and min(wins) < 30  # (a win another hit would have lost)


def test_head_to_head_with_a_growing_toxic():
    """A badly poisoned Jolteon loses 1/16, 2/16, 3/16, ... at the ends of the turns (the
    engine's turns carried): the slower Clefable's Seismic Tosses win in two rounds; with the
    first turn's 1/16 repeated (before) Jolteon lasts a third round and moves first in it."""
    clefable = mon("Clefable", "Heavy-Duty Boots", "Unaware", ["Seismic Toss", "Toxic", "Protect", "Moonblast"],
                   "252 HP / 4 Def / 252 SpD", "Calm")  # fmt: skip
    jolteon = mon("Jolteon", "Heavy-Duty Boots", "Volt Absorb", ["Seismic Toss", "Protect", "Thunderbolt", "Calm Mind"],
                  "4 HP / 252 SpA / 252 Spe", "Timid")  # fmt: skip
    turns = [("move toxic", "move seismictoss")] + [("move seismictoss", "move seismictoss")] * ROUNDS
    for st in clean_runs(clefable, jolteon, turns):
        assert st[1]["sides"][1]["mons"][0]["status"] == "tox"
        assert 200 < hp(st[1], 0) <= 300  # (two Seismic Tosses survived, three not)
        _, _, new = features(st[1])
        assert new[0, TEAM + TEAM_COLS["head_to_head"]] * 6 == 1
        assert outcome(st) == "win" and len(st) == 4  # (Jolteon down at the second round's end)


def _with_hp(state, side: int, hp_now: int):
    """``state`` (poke_engine.State) with side ``side``'s active at ``hp_now`` HP (its string's
    HP field: Showdown cannot set one)."""
    import poke_engine as pe

    text = state.to_string()
    sides = text.split("/")
    s = state.side_one if side == 0 else state.side_two
    a = int(s.active_index)
    mons = sides[side].split("=")
    f = mons[a].split(",")
    f[6] = str(hp_now)
    mons[a] = ",".join(f)
    sides[side] = "=".join(mons)
    return pe.State.from_string("/".join(sides))


def _two_uses(state, move: str) -> float:
    """The probability that two uses of side one's ``move`` (side two doing nothing, no chance:
    poke_engine.set_no_chance) knock side two's active out, by the engine's transitions."""
    import poke_engine as pe

    pe.set_no_chance(True)
    try:
        b = int(state.side_two.active_index)
        ko = 0.0
        for o in pe.generate_instructions(state, move, "none"):
            s2 = state.apply_instructions(o)
            if s2.side_two.pokemon[b].hp <= 0:
                ko += o.percentage / 100
            elif s2.side_one.pokemon[int(s2.side_one.active_index)].hp > 0:
                for o2 in pe.generate_instructions(s2, move, "none"):
                    if s2.apply_instructions(o2).side_two.pokemon[b].hp <= 0:
                        ko += o.percentage / 100 * o2.percentage / 100
        return ko
    finally:
        pe.set_no_chance(False)


# the attacker's own HP over two uses and a heal larger than a quarter (the third review), with
# the engine's transitions as the reference (no HP a Showdown battle can be set to)


def test_ko2_attacker_down_after_its_first_hit():
    """A 1 HP Garchomp with a Life Orb: its first Earthquake's recoil knocks it out -- no second
    use, no two-hit KO (before: the second hit at its starting HP)."""
    gar = mon("Garchomp", "Life Orb", "Rough Skin", ["Earthquake", "Swords Dance", "Protect", "Substitute"],
              "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip
    tank = mon("Hippowdon", "Leftovers", "Sand Force", ["Slack Off", "Whirlwind", "Stealth Rock", "Yawn"],
               "252 HP / 252 Def / 4 SpD", "Impish")  # fmt: skip
    st = _with_hp(ec.engine_state(ec.run_showdown(gar, tank, [])[0]), 0, 1)
    _, _, n = alpha_search.featurize_extra_full([st.to_string()])
    new = np.frombuffer(n, "<f4").reshape(12, EN)
    assert list(new[0, 0:2]) == [0.0, 0.0]
    assert _two_uses(st, "earthquake") == 0.0
    # at full HP the same two Earthquakes do KO (possibly): the attacker's HP is what decides
    full = ec.engine_state(ec.run_showdown(gar, tank, [])[0])
    _, _, n = alpha_search.featurize_extra_full([full.to_string()])
    assert np.frombuffer(n, "<f4").reshape(12, EN)[0, 1] == float(_two_uses(full, "earthquake") > 0)


def test_ko2_a_wish_heals_whole():
    """A Wish of half the max HP lands between the two hits: whole (before: the end of the turn
    measured at 3/4 of the max HP, the heal cut to a quarter -- a two-hit KO claimed). The
    target's HP set where the cut heal would lose and the whole one survives."""
    att = mon("Garchomp", "Choice Band", "Rough Skin", ["Earthquake", "Outrage", "Stone Edge", "Fire Fang"],
              "252 Atk / 4 SpD / 252 Spe", "Jolly")  # fmt: skip
    wisher = mon("Vaporeon", "Heavy-Duty Boots", "Water Absorb", ["Wish", "Protect", "Scald", "Roar"],
                 "252 HP / 252 Def / 4 SpD", "Bold")  # fmt: skip
    st = clean_runs(att, wisher, [("move earthquake", "move wish")], n=1)[0]
    e = ec.engine_state(st[1])
    assert e.side_two.wish[0] == 1  # (its Wish lands at this turn's end)
    max_hp = e.side_two.pokemon[int(e.side_two.active_index)].maxhp
    ent, _, _ = features(st[1])
    d = float(ent[0, 4]) * hp(st[1], 1)  # Earthquake's max damage
    target = int(2 * d - 0.35 * max_hp)  # (KO with a quarter healed, not with a half)
    assert d < target
    s = _with_hp(e, 1, target)
    _, _, n = alpha_search.featurize_extra_full([s.to_string()])
    new = np.frombuffer(n, "<f4").reshape(12, EN)
    assert list(new[0, 0:2]) == [0.0, 0.0]
    assert _two_uses(s, "earthquake") == 0.0
