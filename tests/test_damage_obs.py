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


# 2026-10-24, the belief check (doc/state-diff.md B3): hits F1 read wrong -- each one's test
def test_a_pain_splits_hp_is_the_next_hits_before():
    """-sethp (Pain Split) sets the HP too: the next hit's HP before was the old one (a Knock Off
    of 79 HP read as 26 -- the true set ruled out)."""
    lines = [
        "|switch|p1a: Cat|Meowscarada, F|294/294",
        "|switch|p2a: Rotom|Rotom-Wash|62/100",
        "|turn|1",
        "|move|p2a: Rotom|Pain Split|p1a: Cat",
        "|-sethp|p1a: Cat|210/294|[from] move: Pain Split|[silent]",
        "|-sethp|p2a: Rotom|79/100|[from] move: Pain Split",
        "|turn|2",
        "|move|p1a: Cat|Knock Off|p2a: Rotom",
        "|-damage|p2a: Rotom|54/100",
        "|turn|3",
    ]
    (h,) = hits(lines, "p1")
    assert (h.before, h.after) == (79, 54)


def test_a_transformed_mons_hits_and_another_formes_are_left_out():
    transform = [
        "|switch|p1a: Corv|Corviknight, M|399/399",
        "|switch|p2a: Ditto|Ditto|100/100",
        "|-transform|p2a: Ditto|p1a: Corv|[from] ability: Imposter",
        "|turn|1",
        "|move|p2a: Ditto|Body Press|p1a: Corv",
        "|-damage|p1a: Corv|300/399",
        "|turn|2",
    ]
    assert hits(transform, "p1") == []
    # (a Palafin-Zero's hit, Hero now: the candidates' stats are the Hero's)
    forme = [
        "|switch|p1a: Corv|Corviknight, M|399/399",
        "|switch|p2a: Fin|Palafin|100/100",
        "|turn|1",
        "|move|p2a: Fin|Flip Turn|p1a: Corv",
        "|-damage|p1a: Corv|370/399",
        "|turn|2",
        "|switch|p2a: Fin|Palafin-Hero|100/100",
        "|detailschange|p2a: Fin|Palafin-Hero",
        "|turn|3",
    ]
    assert hits(forme, "p1") == []
    assert len(hits(forme[:6], "p1")) == 1


def test_a_broken_illusions_hits_are_left_out():
    """Their Zoroark hit as a Latias until its Illusion broke: those hits are not the Latias's."""
    lines = [
        "|switch|p1a: Corv|Corviknight, M|399/399",
        "|switch|p2a: Latias|Latias, F|100/100",
        "|turn|1",
        "|move|p2a: Latias|Sludge Bomb|p1a: Corv",
        "|-damage|p1a: Corv|330/399",
        "|turn|2",
        "|move|p1a: Corv|Brave Bird|p2a: Latias",
        "|-damage|p2a: Latias|40/100",
        "|replace|p2a: Zoroark|Zoroark-Hisui, F",
        "|-end|p2a: Zoroark|Illusion",
        "|turn|3",
    ]
    assert hits(lines, "p1") == []


def test_which_switch_ins_may_be_an_illusion():
    """Showdown's Illusion: the last non-fainted mon after the holder, the two places swapped
    first (the one going out may be it). Preview order Corviknight, Zoroark, Snorlax: a
    Corviknight lead is itself (a Zoroark lead would show the Snorlax); a Snorlax in for it may be
    the Zoroark (its place swapped with Corviknight's: the Snorlax last) -- it was; after its
    faint nothing is."""
    from alpha_poke.agents.damage_obs import _Illusion

    il = _Illusion()
    for line in ("|poke|p2|Corviknight, M|", "|poke|p2|Zoroark-Hisui, M|", "|poke|p2|Snorlax, M|"):
        il.feed(line.split("|"))

    def switch(line):
        il.feed(line.split("|"))
        return il.ambiguous["p2a"]

    assert switch("|switch|p2a: Corviknight|Corviknight, M|100/100") is False
    assert switch("|switch|p2a: Snorlax|Snorlax, M|100/100") is True
    il.feed("|replace|p2a: Zoroark|Zoroark-Hisui, M".split("|"))
    assert il.ambiguous["p2a"] is False and il.order["p2"] == ["zoroarkhisui", "corviknight", "snorlax"]
    il.feed("|faint|p2a: Zoroark".split("|"))
    assert switch("|switch|p2a: Snorlax|Snorlax, M|100/100") is False


def test_a_takers_victim_lost_its_item():
    """2026-10-25 review: Showdown's Magician / Covet / Bestow print no -enditem of the one that
    lost the item (its takeItem prints nothing) -- the Latios's Choice Scarf turns read itemless.
    (Showdown's log of the scenario belief/magician-scarf.)"""
    lines = [
        "|switch|p1a: Hoopa|Hoopa|100/100",
        "|switch|p2a: Latios|Latios, M|100/100",
        "|turn|1",
        "|move|p2a: Latios|Psyshock|p1a: Hoopa",
        "|-resisted|p1a: Hoopa",
        "|-damage|p1a: Hoopa|69/100",
        "|move|p1a: Hoopa|Shadow Ball|p2a: Latios",
        "|-supereffective|p2a: Latios",
        "|-damage|p2a: Latios|48/100",
        "|-item|p1a: Hoopa|Choice Scarf|[from] ability: Magician|[of] p2a: Latios",
        "|turn|2",
    ]
    assert item_changes(lines) == {("p1", "hoopa"): "none", ("p2", "latios"): "choicescarf"}
    bestow = lines[:3] + ["|move|p2a: Latios|Bestow|p1a: Hoopa",
                          "|-item|p1a: Hoopa|Choice Scarf|[from] move: Bestow|[of] p2a: Latios", "|turn|2"]
    assert item_changes(bestow) == {("p1", "hoopa"): "none", ("p2", "latios"): "choicescarf"}


# (Showdown's log of the scenario belief/skillswap-after-hit: our Gardevoir Skill Swaps after
# their Huge Power Azumarill's first hit)
SKILL_SWAP = [
    "|switch|p1a: Gardevoir|Gardevoir, M|340/340",
    "|switch|p2a: Azumarill|Azumarill, M|100/100",
    "|turn|1",
    "|move|p2a: Azumarill|Liquidation|p1a: Gardevoir",
    "|-damage|p1a: Gardevoir|187/340",
    "|-unboost|p1a: Gardevoir|def|1",
    "|move|p1a: Gardevoir|Skill Swap|p2a: Azumarill",
    "|-activate|p1a: Gardevoir|Skill Swap|Huge Power|Synchronize|[of] p2a: Azumarill",
    "|turn|2",
    "|move|p2a: Azumarill|Liquidation|p1a: Gardevoir",
    "|-damage|p1a: Gardevoir|88/340",
    "|turn|3",
]


def test_each_hit_is_explained_with_its_ability_then():
    """2026-10-25 review: a Huge Power Azumarill's hit, then a Skill Swap gave it Synchronize --
    F1's candidates held the Synchronize alone (poke-env's ability now), the first hit's true set
    read at the floor. The candidates hold the ability it started with (the swap names it), each
    hit its own then."""
    from alpha_poke.agents.damage_obs import ability_changes

    assert ability_changes(SKILL_SWAP) == {("p2", "azumarill"): "hugepower", ("p1", "gardevoir"): "synchronize"}
    assert [h.ability_then for h in hits(SKILL_SWAP, "p1") if not h.by_us] == [None, "synchronize"]
    mon = Pokemon(species="azumarill", gen=9)
    mon.ability = "hugepower"
    mon.temporary_ability = "synchronize"  # (poke-env after the swap)
    cands, _ = _candidates(BeliefModel.load(), mon, ("Azumarill",),
                           ab=ability_changes(SKILL_SWAP).get(("p2", "azumarill"), False))  # fmt: skip
    assert {c[1] for c in cands} == {"hugepower"}
    # (the one it started with unknown -- a Gastro Acid's suppression names none: the species')
    gastro = SKILL_SWAP[:6] + ["|-endability|p2a: Azumarill", "|turn|2"] + SKILL_SWAP[9:]
    assert ability_changes(gastro) == {("p2", "azumarill"): None}
    assert [h.ability_then for h in hits(gastro, "p1") if not h.by_us] == [None, "none"]
    cands, _ = _candidates(BeliefModel.load(), Pokemon(species="azumarill", gen=9), ("Azumarill",), ab=None)
    assert {"hugepower", "thickfat"} <= {c[1] for c in cands}
    # (a change lasts while it is in: back after a switch, its own again)
    back = SKILL_SWAP[:9] + ["|switch|p2a: Snorlax|Snorlax, M|100/100", "|turn|2",
                             "|switch|p2a: Azumarill|Azumarill, M|100/100", "|turn|3"] + [
        x.replace("turn|2", "turn|3") for x in SKILL_SWAP[9:11]] + ["|turn|4"]
    assert [h.ability_then for h in hits(back, "p1") if not h.by_us] == [None, None]


def test_a_contact_with_lingering_aroma_or_mummy_changes_the_hitters_ability():
    """2026-10-25 review: Showdown prints the change as -activate holder "ability: X" hitter
    "[ability] OLD" (setAbility) -- no -ability line (the scenarios belief/*-contact)."""
    from alpha_poke.agents.damage_obs import ability_changes

    for holder, ability in (("Oinkologne", "Lingering Aroma"), ("Cofagrigus", "Mummy")):
        lines = [
            f"|switch|p1a: {holder}|{holder}, M|424/424",
            "|switch|p2a: Azumarill|Azumarill, M|100/100",
            "|turn|1",
            f"|move|p2a: Azumarill|Liquidation|p1a: {holder}",
            f"|-damage|p1a: {holder}|264/424",
            f"|-activate|p1a: {holder}|ability: {ability}|p2a: Azumarill|[ability] Huge Power",
            "|turn|2",
            f"|move|p2a: Azumarill|Liquidation|p1a: {holder}",
            f"|-damage|p1a: {holder}|215/424",
            "|turn|3",
        ]
        assert ability_changes(lines) == {("p2", "azumarill"): "hugepower"}
        assert [h.ability_then for h in hits(lines, "p1")] == [None, ability.lower().replace(" ", "")]


def test_an_illusions_changes_are_the_real_mons():
    """Showdown's log (a Zoroark-Hisui as the Garchomp it shows hits a Mummy Cofagrigus): Illusion's
    End prints the replace before the -activate -- the change is the Zoroark's. ability_changes /
    item_changes followed switches only: the Garchomp's candidates held Illusion alone (2026-10-25
    review)."""
    from alpha_poke.agents.damage_obs import ability_changes

    lines = [
        "|switch|p1a: Cofagrigus|Cofagrigus, M|320/320",
        "|switch|p2a: Garchomp|Garchomp, M|100/100",
        "|turn|1",
        "|move|p2a: Garchomp|Night Slash|p1a: Cofagrigus",
        "|-supereffective|p1a: Cofagrigus",
        "|-damage|p1a: Cofagrigus|204/320",
        "|replace|p2a: Zoroark|Zoroark-Hisui, M",
        "|-end|p2a: Zoroark|Illusion",
        "|-activate|p1a: Cofagrigus|ability: Mummy|p2a: Zoroark|[ability] Illusion",
        "|turn|2",
        "|move|p2a: Zoroark|Night Slash|p1a: Cofagrigus",
        "|-supereffective|p1a: Cofagrigus",
        "|-damage|p1a: Cofagrigus|138/320",
        "|-enditem|p2a: Zoroark|Leftovers|[from] move: Knock Off|[of] p1a: Cofagrigus",
        "|turn|3",
    ]
    assert ability_changes(lines) == {("p2", "zoroarkhisui"): "illusion"}
    assert set(item_changes(lines)) == {("p2", "zoroarkhisui")}
    assert [(h.attacker, h.ability_then) for h in hits(lines, "p1")] == [("zoroarkhisui", "mummy")]
