"""The opponent's speed from the move order (agents/speed.py, 2026-10-11)."""

import random
from types import SimpleNamespace

from alpha_poke.agents.damage import calc_stats
from alpha_poke.agents.engine_state import _sample_spread
from alpha_poke.agents.speed import Obs, consistent, observations


def lines(text: str):
    return [x.split("|") for x in text.strip().split("\n")]


LOG = """
|switch|p1a: Bolt|Raging Bolt|391/391
|switch|p2a: Tusk|Great Tusk|100/100
|turn|1
|move|p2a: Tusk|Headlong Rush|p1a: Bolt
|-damage|p1a: Bolt|200/391
|move|p1a: Bolt|Dragon Dance|p1a: Bolt
|-boost|p1a: Bolt|spe|1
|upkeep
|switch|p1a: Fish|Dondozo, M|503/503
|turn|2
"""


def test_state_at_the_first_move():
    # the boost of the second mover's own move and the end-of-turn switch do not count
    speeds = {"ragingbolt": (249, "", "protosynthesis"), "dondozo": (95, "", "unaware")}
    obs = observations(lines(LOG), "p1", lambda sp: speeds[sp])
    assert len(obs) == 1
    o = obs[0]
    assert o.species == "greattusk" and o.opp_first and o.ours == 249 and o.mult == 1.0


def test_consistent_and_ties():
    o = Obs(1, "greattusk", ours=300.0, mult=1.0, trick_room=False, opp_first=True)
    assert consistent([o], 350, "") and not consistent([o], 250, "")
    assert consistent([o], 250, "choicescarf")  # 375
    assert consistent([o], 299, "")  # within the rounding tolerance: a tie
    tr = Obs(1, "greattusk", ours=300.0, mult=1.0, trick_room=True, opp_first=True)
    assert consistent([tr], 250, "") and not consistent([tr], 350, "")


def test_sample_spread_respects_the_order():
    mon = SimpleNamespace(species="greattusk", level=100,
                          base_stats={"hp": 115, "atk": 131, "def": 131, "spa": 53, "spd": 53,
                                      "spe": 87})  # fmt: skip
    dist = SimpleNamespace(item={"choicescarf": 0.2, "boosterenergy": 0.3})
    rng = random.Random(0)
    fast = Obs(1, "greattusk", ours=330.0, mult=1.0, trick_room=False, opp_first=True)
    for _ in range(30):
        spread, item = _sample_spread(mon, "boosterenergy", False, [fast], dist, rng)
        spe = calc_stats(mon.base_stats, spread)["spe"] * (1.5 if item == "choicescarf" else 1)
        assert spe >= 330 * 0.995  # a fast spread or (no spread fits) a Choice Scarf
    slow = Obs(1, "greattusk", ours=250.0, mult=1.0, trick_room=False, opp_first=False)
    for _ in range(30):
        spread, item = _sample_spread(mon, "", True, [slow], dist, rng)
        assert calc_stats(mon.base_stats, spread)["spe"] <= 250 * 1.005  # a bulky spread


def test_sample_spread_zero_weight_fits(monkeypatch):
    # 2026-10-12, gen 6: the spreads fitting the order all had usage weight 0 -> ValueError
    import alpha_poke.agents.engine_state as es

    fast = {"evs": {"spe": 252}, "nature": "jolly"}
    slow = {"evs": {"hp": 252}, "nature": "relaxed"}
    monkeypatch.setattr(es, "spread_dist", lambda sp: ([slow, fast], [1.0, 0.0]))
    monkeypatch.setattr(es, "calc_stats", lambda base, sp, level=100: {
        "spe": 300 if sp is fast else 200})  # fmt: skip
    es._SPREAD_SPEEDS.clear()
    mon = SimpleNamespace(species="testmon", level=100, base_stats={})
    o = Obs(1, "testmon", ours=250.0, mult=1.0, trick_room=False, opp_first=True)
    spread, item = _sample_spread(mon, "", True, [o], SimpleNamespace(item={}), random.Random(0))
    assert spread is fast and item == ""


SWITCHEROO = """
|switch|p1a: Fish|Basculegion, M|300/300
|switch|p2a: Glalie|Glalie, M|100/100
|turn|1
|move|p1a: Fish|Pain Split|p2a: Glalie
|move|p2a: Glalie|Spikes|p1a: Fish
|upkeep
|turn|2
|move|p2a: Glalie|Switcheroo|p1a: Fish
|-activate|p2a: Glalie|move: Trick|[of] p1a: Fish
|-item|p1a: Fish|Life Orb|[from] move: Trick
|-item|p2a: Glalie|Choice Scarf|[from] move: Trick
|move|p1a: Fish|Wave Crash|p2a: Glalie
|upkeep
|turn|3
|move|p2a: Glalie|Switcheroo|p1a: Fish
|move|p1a: Fish|Wave Crash|p2a: Glalie
|upkeep
|turn|4
"""


def test_an_observation_is_read_with_the_item_held_then():
    """2026-10-24, the belief check: a Glalie that got its Choice Scarf by Switcheroo after a turn
    it moved second -- read with the scarf, its true speed ruled out. The turn before the swap
    has the item it started with (revealed by the swap: the one we received) -- the swap's own
    turn too (its order was before the swap) --, the turn after the one the log named."""
    speeds = {"basculegion": (255, "", "adaptability")}
    obs = observations(lines(SWITCHEROO), "p1", lambda sp: speeds[sp])
    assert [(o.turn, o.item_then) for o in obs] == [
        (1, "lifeorb"),
        (2, "lifeorb"),
        (3, "choicescarf"),
    ]
    assert consistent(obs[:1], 217, "choicescarf")  # (its scarf: not at turn 1)
    # (we received nothing: it held none before)
    empty = SWITCHEROO.replace("|-item|p1a: Fish|Life Orb|[from] move: Trick\n", "")
    obs = observations(lines(empty), "p1", lambda sp: speeds[sp])
    assert [(o.turn, o.item_then) for o in obs] == [(1, "none"), (2, "none"), (3, "choicescarf")]


# 2026-10-24, the belief check (doc/state-diff.md B2): the true speed ruled out at 990 decisions --
# each cause one test: what the order observation must leave out or read as it was then
def _obs(text, speeds, side="p1"):
    return observations(lines(text), side, lambda sp: speeds[sp])


def test_a_status_the_hp_field_cured_counts_no_more():
    """A Healing Wish's cure is only its -heal's HP field (no status): the paralysis it cured made
    the switch-in read at half speed (Suicune's true speed ruled out)."""
    log = """
|switch|p1a: Egg|Blissey, F|600/600
|switch|p2a: Wake|Suicune|100/100 par
|-heal|p2a: Wake|100/100|[from] move: Healing Wish
|turn|1
|move|p2a: Wake|Scald|p1a: Egg
|move|p1a: Egg|Soft-Boiled|p1a: Egg
|upkeep
|turn|2
"""
    (o,) = _obs(log, {"blissey": (142, "", "naturalcure")})
    assert o.mult == 1.0


def test_an_encored_second_mover_is_left_out():
    """Its chosen move was not the one it used (a -6 Dragon Tail Encored into Energy Ball): the
    order says nothing about the speeds."""
    log = """
|switch|p1a: Mega|Meganium, F|300/300
|switch|p2a: Chan|Hitmonchan, M|100/100
|turn|1
|move|p2a: Chan|Encore|p1a: Mega
|-start|p1a: Mega|Encore
|move|p1a: Mega|Energy Ball|p2a: Chan
|upkeep
|turn|2
"""
    assert _obs(log, {"meganium": (195, "", "overgrow")}) == []


def test_mycelium_might_and_stall_are_left_out():
    log = """
|switch|p1a: Toed|Toedscruel, M|300/300
|switch|p2a: Nite|Dragonite, M|100/100
|turn|1
|move|p2a: Nite|Roost|p2a: Nite
|move|p1a: Toed|Spore|p2a: Nite
|upkeep
|turn|2
"""
    assert _obs(log, {"toedscruel": (224, "", "myceliummight")}) == []
    # (an attack of its: in order)
    assert (
        len(
            _obs(
                log.replace("|Spore|", "|Earth Power|"), {"toedscruel": (224, "", "myceliummight")}
            )
        )
        == 1
    )


def test_our_speed_is_read_with_our_item_then():
    """Our Choice Scarf Tricked away at turn 2: the turns before read with it (2026-10-24: a
    Gothitelle's own scarf left out of its speed -- the opponent's true speed ruled out)."""
    log = """
|switch|p1a: Goth|Gothitelle, F|300/300
|switch|p2a: Bolt|Zekrom|100/100
|turn|1
|move|p1a: Goth|Psychic|p2a: Bolt
|move|p2a: Bolt|Bolt Strike|p1a: Goth
|upkeep
|turn|2
|move|p1a: Goth|Trick|p2a: Bolt
|-activate|p1a: Goth|move: Trick|[of] p2a: Bolt
|-item|p2a: Bolt|Choice Scarf|[from] move: Trick
|-item|p1a: Goth|Life Orb|[from] move: Trick
|move|p2a: Bolt|Bolt Strike|p1a: Goth
|upkeep
|turn|3
|move|p2a: Bolt|Bolt Strike|p1a: Goth
|move|p1a: Goth|Psychic|p2a: Bolt
|upkeep
|turn|4
"""
    obs = _obs(log, {"gothitelle": (168, "lifeorb", "frisk")})
    assert [(o.turn, o.ours) for o in obs] == [(1, 252.0), (2, 252.0), (3, 168.0)]


def test_a_transformed_active_is_left_out():
    log = """
|switch|p1a: Wham|Whimsicott, F|250/250
|switch|p2a: Ditto|Ditto|100/100
|-transform|p2a: Ditto|p1a: Wham|[from] ability: Imposter
|turn|1
|move|p1a: Wham|Moonblast|p2a: Ditto
|move|p2a: Ditto|Moonblast|p1a: Wham
|upkeep
|turn|2
"""
    assert _obs(log, {"whimsicott": (264, "", "prankster")}) == []


def test_each_turn_in_the_opponents_forme_then():
    """Minior's Meteor (base 60) shell broken into its Core (120): the turns before read with
    the Meteor speed (consistent's stat_of); our own forme changed: its turns left out (our stat
    is the one now)."""
    from alpha_poke.agents.speed import spe_stat

    log = """
|switch|p1a: Corv|Corviknight, M|399/399
|switch|p2a: Rock|Minior-Meteor|100/100
|turn|1
|move|p1a: Corv|Brave Bird|p2a: Rock
|-damage|p2a: Rock|40/100
|-formechange|p2a: Rock|Minior|[from] ability: Shields Down
|move|p2a: Rock|Shell Smash|p2a: Rock
|upkeep
|turn|2
|move|p2a: Rock|Acrobatics|p1a: Corv
|move|p1a: Corv|Brave Bird|p2a: Rock
|upkeep
|turn|3
"""
    obs = _obs(log, {"corviknight": (300, "", "pressure")})
    assert [o.base_spe for o in obs] == [60, 120]
    # (its Core's speed now 372: the Meteor turn it moved second at 240 -- consistent only with
    # stat_of)
    stat_of = lambda b: spe_stat(b, 252, "jolly", 100)  # noqa: E731
    assert (stat_of(60), stat_of(120)) == (240, 372)
    assert consistent(obs, 372, "", stat_of) and not consistent(obs[:1], 372, "")


def test_each_turn_read_with_the_abilities_then():
    """2026-10-25 review (F1's twin): our Regigigas Skill Swaps its Slow Start to their Garchomp
    (Showdown's log). Turn 1 is read with our Slow Start then (not the Rough Skin we have now: our
    118 read as 236, the Garchomp's first move ruled its 216 out); turns 2 and 3 with their Slow
    Start (not the species' abilities: its halved speed read whole) -- both left out."""
    log = """
|switch|p1a: Regigigas|Regigigas|424/424
|switch|p2a: Garchomp|Garchomp, M|100/100
|-start|p1a: Regigigas|ability: Slow Start
|turn|1
|move|p2a: Garchomp|Swords Dance|p2a: Garchomp
|-boost|p2a: Garchomp|atk|2
|move|p1a: Regigigas|Skill Swap|p2a: Garchomp
|-activate|p1a: Regigigas|Skill Swap|Rough Skin|Slow Start|[of] p2a: Garchomp
|-end|p1a: Regigigas|Slow Start|[silent]
|-start|p2a: Garchomp|ability: Slow Start
|upkeep
|turn|2
|move|p1a: Regigigas|Bulk Up|p1a: Regigigas
|-boost|p1a: Regigigas|atk|1
|-boost|p1a: Regigigas|def|1
|move|p2a: Garchomp|Swords Dance|p2a: Garchomp
|-boost|p2a: Garchomp|atk|2
|upkeep
|turn|3
|move|p1a: Regigigas|Bulk Up|p1a: Regigigas
|-boost|p1a: Regigigas|atk|1
|-boost|p1a: Regigigas|def|1
|move|p2a: Garchomp|Stealth Rock|p1a: Regigigas
|-sidestart|p1: p1|move: Stealth Rock
|upkeep
|turn|4
"""
    assert _obs(log, {"regigigas": (236, "leftovers", "roughskin")}) == []
    # (no change: the same turns kept)
    plain = log.replace(
        "|-activate|p1a: Regigigas|Skill Swap|Rough Skin|Slow Start|[of] p2a: Garchomp\n", ""
    )
    assert [o.turn for o in _obs(plain, {"regigigas": (236, "leftovers", "pressure")})] == [1, 2, 3]


def test_our_ability_then_is_the_snapshots_mon():
    """2026-10-25 review: our ability then was read at the turn's flush with the slot's mon then --
    a faint's replacement. Grimmsnarl's Prankster Reflect at turn 3 (it fainted, the swapped
    Gardevoir came back): read with Gardevoir's Synchronize, the priority move's turn kept."""
    log = """
|switch|p1a: Gardevoir|Gardevoir, F|300/300
|switch|p2a: Garchomp|Garchomp, M|100/100
|turn|1
|move|p2a: Garchomp|Swords Dance|p2a: Garchomp
|-boost|p2a: Garchomp|atk|2
|move|p1a: Gardevoir|Skill Swap|p2a: Garchomp
|-activate|p1a: Gardevoir|Skill Swap|Rough Skin|Synchronize|[of] p2a: Garchomp
|upkeep
|turn|2
|switch|p1a: Grimmsnarl|Grimmsnarl, M|300/300
|move|p2a: Garchomp|Swords Dance|p2a: Garchomp
|-boost|p2a: Garchomp|atk|2
|upkeep
|turn|3
|move|p1a: Grimmsnarl|Reflect|p1a: Grimmsnarl
|-sidestart|p1: x|Reflect
|move|p2a: Garchomp|Earthquake|p1a: Grimmsnarl
|-damage|p1a: Grimmsnarl|0 fnt
|faint|p1a: Grimmsnarl
|upkeep
|switch|p1a: Gardevoir|Gardevoir, F|300/300
|turn|4
"""
    speeds = {"gardevoir": (200, "", "roughskin"), "grimmsnarl": (150, "", "prankster")}
    assert [o.turn for o in _obs(log, speeds)] == [1]
