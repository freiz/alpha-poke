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
