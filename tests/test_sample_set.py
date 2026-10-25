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


def test_an_item_replays_never_show_is_drawn():
    """2026-10-25 (the belief check's prior support): the archetypes are mined from replays, which
    show an item only when it reveals itself -- a Latias's Soul Dew never: its archetypes had no
    weight on it, the sampler never drew it (Smogon's usage: 36%). Mixed with the base marginal
    (ARCH_MIX) it is drawn; at mix 0, the old belief, not."""
    belief = BeliefModel.load()
    names = ("Corviknight", "Great Tusk", "Latias", "Gholdengo", "Kingambit", "Dragapult")
    mon = Pokemon(species="latias", gen=9)

    def items(mix):
        rng = random.Random(0)
        return {sample_set(belief, mon, names, rng, 1.0, mix=mix).item for _ in range(400)}

    assert "souldew" in items(None) and "souldew" not in items(0.0)


def test_a_cosmetic_formes_prior_is_its_base_species():
    """Smogon's usage lists Maushold-Four under Maushold: its prior was empty (2026-10-25). Only
    a forme the same in battle falls back -- not Tauros-Paldea-Combat to Tauros."""
    from alpha_poke.belief.priors import SmogonPrior

    belief = BeliefModel.load()
    p = belief.prior
    while not isinstance(p, SmogonPrior):
        p = p.base
    assert p.predict("Maushold-Four", ()).move == p.predict("Maushold", ()).move != {}
    assert p.predict("Tauros-Paldea-Combat", ()).move != p.predict("Tauros", ()).move


def test_a_species_ou_never_uses_has_a_prior():
    """2026-10-25 (the belief check: 91% of its prior gaps): a species not in OU's usage had an
    empty prior -- no move but the revealed ones, no item. Its fallback: Showdown's random-battle
    movepool and tera types, OU's items across species; a species not there either, its learnset."""
    from alpha_poke.belief.priors import SmogonPrior, legal_moves

    belief = BeliefModel.load()
    p = belief.prior
    while not isinstance(p, SmogonPrior):
        p = p.base
    glalie = p.predict("Glalie", ())
    assert set(glalie.move) == {"earthquake", "freezedry", "spikes", "taunt"}
    assert set(glalie.tera) == {"ghost", "ground", "water"} and glalie.item.get("heavydutyboots", 0) > 0.1
    assert "spore" in legal_moves("smeargle") and "spikes" in legal_moves("glalie")


def test_a_legal_set_no_ou_player_uses_is_never_impossible():
    """The floor (engine_state.FLOOR): a move of its learnset no archetype has, an item OU uses
    elsewhere, any tera type, a forme's item for sure -- reachable, not drawn in practice."""
    from alpha_poke.agents.engine_state import FLOOR, _move_floor, base_marginal, required_item

    belief = BeliefModel.load()
    names = ("Corviknight", "Great Tusk", "Latias", "Gholdengo", "Kingambit", "Dragapult")
    w = _move_floor({"bravebird": 1.0, "roost": 1.0}, "corviknight")
    assert w["bodypress"] > 0 and abs(sum(w.values()) - 2.0 * (1 + FLOOR)) < 1e-9
    items = base_marginal(belief, "Corviknight", names, "item")
    assert items.get("choicespecs", 0) > 0 and abs(sum(items.values()) - 1) < 1e-9
    assert base_marginal(belief, "Corviknight", names, "tera").get("stellar", 0) > 0
    assert "lustrousorb" in base_marginal(belief, "Palkia", (), "item")
    assert required_item(Pokemon(species="zamazentacrowned", gen=9)) == "rustedshield"
    # (mix 0, the old belief: the team prior's alone, no floor)
    from alpha_poke.agents.engine_state import _prior
    from alpha_poke.analysis.roles import to_id

    old = base_marginal(belief, "Corviknight", names, "item", mix=0.0)
    assert set(old) == {to_id(k) for k in _prior(belief, "Corviknight", names).item}
