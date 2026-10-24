"""F1's damage evidence (agents/damage_obs): a hit is explained with the item its mon held then
(2026-10-24 review: Latios hit with Choice Specs, then a Trick gave it a Life Orb -- the old hit
was read with the Life Orb, the true Sp. Atk ruled out)."""

from poke_env.battle import Pokemon

from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.agents.damage_obs import _candidates, hits, item_changes

LINES = [
    "|switch|p1a: Corviknight|Corviknight, M|399/399",
    "|switch|p2a: Latios|Latios, M|100/100",
    "|turn|1",
    "|move|p2a: Latios|Surf|p1a: Corviknight",
    "|-damage|p1a: Corviknight|250/399",
    "|turn|2",
    "|move|p2a: Latios|Trick|p1a: Corviknight",
    "|-activate|p2a: Latios|move: Trick|[of] p1a: Corviknight",
    "|-item|p1a: Corviknight|Choice Specs|[from] move: Trick",
    "|-item|p2a: Latios|Life Orb|[from] move: Trick",
    "|turn|3",
]


def test_the_item_a_mon_held_before_a_trick():
    assert item_changes(LINES) == {("p2", "latios"): "choicespecs", ("p1", "corviknight"): "lifeorb"}
    # (Thief: it held none to steal one)
    thief = LINES[:6] + ["|move|p2a: Latios|Thief|p1a: Corviknight", "|-damage|p1a: Corviknight|200/399",
                         "|-enditem|p1a: Corviknight|Leftovers|[silent]|[from] move: Thief|[of] p2a: Latios",
                         "|-item|p2a: Latios|Leftovers|[from] move: Thief|[of] p1a: Corviknight", "|turn|3"]
    assert item_changes(thief) == {("p2", "latios"): "none", ("p1", "corviknight"): "leftovers"}


def test_a_tricked_mons_candidates_are_its_item_then():
    belief = BeliefModel.load()
    mon = Pokemon(species="latios", gen=9)
    mon.item = "lifeorb"  # (poke-env: the item it holds now)
    cands, _ = _candidates(belief, mon, ("Latios",), then=item_changes(LINES).get(("p2", "latios"), False))
    assert {c[0] for c in cands} == {"choicespecs"}
    # (not changed: the revealed item as before)
    cands, _ = _candidates(belief, mon, ("Latios",))
    assert {c[0] for c in cands} == {"lifeorb"}


def test_each_hit_is_explained_with_its_own_items_phase():
    """2026-10-24 review: Delphox hit with Choice Specs, was knocked off, took an Assault Vest by
    Magician -- one item for every hit read the Choice Specs hit as itemless (the true set's
    likelihood 0). Each hit its phase's: the one it started with (revealed by the Knock Off),
    none, the Assault Vest."""
    lines = [
        "|switch|p1a: Corviknight|Corviknight, M|399/399",
        "|switch|p2a: Delphox|Delphox, F|100/100",
        "|turn|1",
        "|move|p2a: Delphox|Psyshock|p1a: Corviknight",
        "|-damage|p1a: Corviknight|300/399",
        "|turn|2",
        "|move|p1a: Corviknight|Knock Off|p2a: Delphox",
        "|-damage|p2a: Delphox|60/100",
        "|-enditem|p2a: Delphox|Choice Specs|[from] move: Knock Off|[of] p1a: Corviknight",
        "|turn|3",
        "|move|p2a: Delphox|Psyshock|p1a: Corviknight",
        "|-damage|p1a: Corviknight|240/399",
        "|move|p1a: Corviknight|Brave Bird|p2a: Delphox",
        "|-damage|p2a: Delphox|10/100",
        "|-item|p2a: Delphox|Assault Vest|[from] ability: Magician|[of] p1a: Corviknight",
        "|turn|4",
        "|move|p2a: Delphox|Psyshock|p1a: Corviknight",
        "|-damage|p1a: Corviknight|190/399",
        "|turn|5",
    ]
    assert item_changes(lines)[("p2", "delphox")] == "choicespecs"
    theirs = [h.item_then for h in hits(lines, "p1") if not h.by_us]
    assert theirs == [None, "none", "assaultvest"], theirs
