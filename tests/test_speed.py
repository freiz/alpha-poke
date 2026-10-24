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
    assert [(o.turn, o.item_then) for o in obs] == [(1, "lifeorb"), (2, "lifeorb"), (3, "choicescarf")]
    assert consistent(obs[:1], 217, "choicescarf")  # (its scarf: not at turn 1)
    # (we received nothing: it held none before)
    empty = SWITCHEROO.replace("|-item|p1a: Fish|Life Orb|[from] move: Trick\n", "")
    obs = observations(lines(empty), "p1", lambda sp: speeds[sp])
    assert [(o.turn, o.item_then) for o in obs] == [(1, "none"), (2, "none"), (3, "choicescarf")]
