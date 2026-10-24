"""Set sampling (agents/engine_state.sample_set) draws only sets the battle allows: an Assault
Vest holder cannot choose a status move (2026-10-24, plan C's slot check: a replay's
Slowking-Galar with Toxic and Chilly Reception was drawn an Assault Vest -- its Toxic, the move
it used, no option of the training state)."""

import random

from poke_env.battle import Pokemon

from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.agents.engine_state import KnownSet, _status, sample_set

# (the replay's: gen9ou-2122314865, side one -- its game-wide known moves Toxic, Future Sight,
# Sludge Bomb; without the check, Assault Vest about one draw in a few hundred)
NAMES = ("Kyurem", "Slowking-Galar", "Great Tusk", "Kingambit", "Iron Valiant", "Dragapult")
KNOWN = KnownSet(moves=["toxic", "futuresight", "sludgebomb"])


def _mon(*moves: str, item: str | None = None) -> Pokemon:
    mon = Pokemon(species="slowkinggalar", gen=9)
    for m in moves:
        mon._add_move(m)
    if item is not None:
        mon.item = item
    return mon


def test_a_mon_with_a_status_move_draws_no_assault_vest():
    belief = BeliefModel.load()
    rng = random.Random(0)
    items = [sample_set(belief, _mon(), NAMES, rng, known=KNOWN).item for _ in range(3000)]
    assert "assaultvest" not in items
    # (the check means something: without a status move known it is drawn)
    rng = random.Random(0)
    items = [sample_set(belief, _mon("sludgebomb"), NAMES, rng).item for _ in range(300)]
    assert "assaultvest" in items


def test_an_assault_vest_holder_draws_no_status_move():
    belief = BeliefModel.load()
    rng = random.Random(0)
    for _ in range(200):
        s = sample_set(belief, _mon("sludgebomb", item="assaultvest"), NAMES, rng)
        assert s.item == "assaultvest"
        assert not any(_status(m) for m in s.moves), s.moves
