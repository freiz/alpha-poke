"""Turn counters from the protocol log (agents/timers.py), against hand-written turns."""

from alpha_poke.agents.timers import timers


def run(text: str):
    return timers([line.split("|") for line in text.strip().split("\n")])


START = """
|switch|p1a: Fishy|Dondozo, M|503/503
|switch|p2a: Bob|Gliscor, F|100/100
|turn|1
"""


def test_rest_counts_sleeping_attempts_not_sleep_talk():
    t = run(
        START
        + """
|move|p1a: Fishy|Rest|p1a: Fishy
|-status|p1a: Fishy|slp|[from] move: Rest
|upkeep
|turn|2
|cant|p1a: Fishy|slp
|move|p1a: Fishy|Sleep Talk|p1a: Fishy
|move|p1a: Fishy|Body Press|p2a: Bob|[from] move: Sleep Talk
|upkeep
|turn|3
"""
    )
    st = t["p1"]
    assert st.sleep["dondozo"] == [1, True]
    assert st.rest_sleep("dondozo") == (2, 0)  # one more sleeping turn, then it wakes


def test_rest_wakes_on_the_third():
    t = run(
        START
        + """
|-status|p1a: Fishy|slp|[from] move: Rest
|upkeep
|turn|2
|cant|p1a: Fishy|slp
|upkeep
|turn|3
|cant|p1a: Fishy|slp
|upkeep
|turn|4
"""
    )
    assert t["p1"].rest_sleep("dondozo") == (1, 0)


def test_sleep_counter_kept_across_switches():
    t = run(
        START
        + """
|-status|p2a: Bob|slp|[from] move: Spore
|upkeep
|turn|2
|cant|p2a: Bob|slp
|upkeep
|turn|3
|switch|p2a: Rex|Garchomp, M|100/100
|upkeep
|turn|4
|switch|p2a: Bob|Gliscor, F|100/100 slp
|upkeep
|turn|5
"""
    )
    assert t["p2"].rest_sleep("gliscor") == (0, 1)


def test_toxic_ticks_reset_on_switch():
    t = run(
        START
        + """
|-status|p2a: Bob|tox
|-damage|p2a: Bob|94/100 tox|[from] psn
|upkeep
|turn|2
|-damage|p2a: Bob|82/100 tox|[from] psn
|upkeep
|turn|3
"""
    )
    assert t["p2"].toxic == 2
    t = run(
        START
        + """
|-status|p2a: Bob|tox
|upkeep
|turn|2
|switch|p2a: Rex|Garchomp, M|100/100
|switch|p2a: Bob|Gliscor, F|88/100 tox
|upkeep
|turn|3
"""
    )
    assert t["p2"].toxic == 1  # back in: one tick since


def test_consecutive_protect():
    t = run(
        START
        + """
|move|p2a: Bob|Protect|p2a: Bob
|-singleturn|p2a: Bob|Protect
|upkeep
|turn|2
|move|p2a: Bob|Protect|p2a: Bob
|-singleturn|p2a: Bob|Protect
|upkeep
|turn|3
"""
    )
    assert t["p2"].protect == 2
    t = run(
        START
        + """
|move|p2a: Bob|Protect|p2a: Bob
|-singleturn|p2a: Bob|Protect
|upkeep
|turn|2
|move|p2a: Bob|Earthquake|p1a: Fishy
|upkeep
|turn|3
"""
    )
    assert t["p2"].protect == 0


def test_wish_pending_one_turn():
    t = run(
        START
        + """
|move|p1a: Fishy|Wish|p1a: Fishy
|upkeep
|turn|2
"""
    )
    assert t["p1"].wish == (1, "dondozo")
    t = run(
        START
        + """
|move|p1a: Fishy|Wish|p1a: Fishy
|upkeep
|turn|2
|-heal|p1a: Fishy|503/503|[from] move: Wish|[wisher] Fishy
|upkeep
|turn|3
"""
    )
    assert t["p1"].wish is None


def test_confusion_taunt_encore_yawn():
    t = run(
        START
        + """
|-start|p1a: Fishy|confusion
|-start|p2a: Bob|move: Taunt
|-start|p2a: Bob|Encore
|upkeep
|turn|2
|-activate|p1a: Fishy|confusion
|move|p1a: Fishy|Body Press|p2a: Bob
|move|p2a: Bob|Earthquake|p1a: Fishy
|-start|p1a: Fishy|move: Yawn|[of] p2a: Bob
|upkeep
|turn|3
"""
    )
    assert t["p1"].confusion == 1 and t["p1"].yawn == 1
    assert t["p2"].taunt == 2 and t["p2"].encore == 2  # (ends of turn: L89, L90)
    t = run(
        START
        + """
|move|p2a: Bob|Earthquake|p1a: Fishy
|move|p1a: Fishy|Encore|p2a: Bob
|-start|p2a: Bob|Encore
|upkeep
|turn|2
"""
    )
    assert t["p2"].encore == 0  # it had moved: one more turn (Showdown's duration 4)
    t = run(
        START
        + """
|-start|p1a: Fishy|confusion
|upkeep
|turn|2
|switch|p1a: Other|Toxapex, M|300/300
|upkeep
|turn|3
"""
    )
    assert t["p1"].confusion is None  # gone with the switch


def test_toxic_orb_poisons_after_the_damage():
    t = run(
        START
        + """
|-status|p2a: Bob|tox|[from] item: Toxic Orb
|upkeep
|turn|2
"""
    )
    assert t["p2"].toxic == 0  # the first tick comes at the end of turn 2


def test_future_sight_pending_until_it_lands():
    t = run(
        START
        + """
|move|p1a: Fishy|Future Sight|p2a: Bob
|-start|p1a: Fishy|move: Future Sight
|upkeep
|turn|2
"""
    )
    assert t["p1"].future == (2, "dondozo")
    t = run(
        START
        + """
|-start|p1a: Fishy|move: Future Sight
|upkeep
|turn|2
|upkeep
|turn|3
|-end|p2a: Bob|move: Future Sight
|upkeep
|turn|4
"""
    )
    assert t["p1"].future is None


def test_protosynthesis_from_booster_energy():
    """L141: a Protosynthesis / Quark Drive from Booster Energy (the engine's frombooster), not one
    from the sun; it ends with the volatile or a switch."""
    lead = """
|switch|p1a: Wake|Walking Wake|100/100
|switch|p2a: Bob|Gliscor, F|100/100
"""
    t = run(lead + """
|-enditem|p1a: Wake|Booster Energy
|-activate|p1a: Wake|ability: Protosynthesis|[fromitem]
|-start|p1a: Wake|protosynthesisspa
|turn|1
""")  # fmt: skip
    assert t["p1"].frombooster
    t = run(lead + """
|-weather|SunnyDay|[from] ability: Drought|[of] p2a: Bob
|-activate|p1a: Wake|ability: Protosynthesis
|-start|p1a: Wake|protosynthesisspa
|turn|1
""")  # fmt: skip
    assert not t["p1"].frombooster
    t = run(lead + """
|-activate|p1a: Wake|ability: Protosynthesis|[fromitem]
|-end|p1a: Wake|Protosynthesis
|turn|1
""")  # fmt: skip
    assert not t["p1"].frombooster


def test_times_attacked_counts_the_foes_hits():
    """L163: the hits of the foe's moves on a mon (Rage Fist), not the other damage."""
    t = run(START + """
|move|p1a: Fishy|Rock Blast|p2a: Bob
|-damage|p2a: Bob|80/100
|-damage|p2a: Bob|60/100
|-hitcount|p2a: Bob|2
|move|p2a: Bob|Toxic|p1a: Fishy
|-damage|p2a: Bob|50/100|[from] Stealth Rock
|upkeep
|turn|2
""")  # fmt: skip
    assert t["p2"].times_attacked == {"gliscor": 2}


def test_last_move_is_the_battles():
    """L167: the battle's last move (Copycat's), either side's, a called move after its caller; a
    move that could not start leaves it."""
    t = run(START + """
|move|p1a: Fishy|Copycat|p1a: Fishy
|move|p1a: Fishy|Stealth Rock|p2a: Bob|[from] move: Copycat
|cant|p2a: Bob|par
|upkeep
|turn|2
""")  # fmt: skip
    assert t["p1"].last_move == t["p2"].last_move == "stealthrock"


def test_trap_out_when_the_trapper_leaves():
    """L170: a partial trap whose source switched out does nothing more (Showdown ends it silently
    at the residual)."""
    t = run(START + """
|move|p1a: Fishy|Whirlpool|p2a: Bob
|-activate|p2a: Bob|move: Whirlpool|[of] p1a: Fishy
|upkeep
|turn|2
|switch|p1a: Other|Toxapex, M|304/304
|upkeep
|turn|3
""")  # fmt: skip
    assert t["p2"].partiallytrapped is not None and t["p2"].trap_out
    t2 = run(START + """
|move|p1a: Fishy|Whirlpool|p2a: Bob
|-activate|p2a: Bob|move: Whirlpool|[of] p1a: Fishy
|upkeep
|turn|2
""")  # fmt: skip
    assert not t2["p2"].trap_out
    t3 = run(START + """
|move|p1a: Fishy|Whirlpool|p2a: Bob
|-activate|p2a: Bob|move: Whirlpool|[of] p1a: Fishy
|move|p2a: Bob|Earthquake|p1a: Fishy
|faint|p1a: Fishy
""")  # fmt: skip
    assert t3["p2"].trap_out


def test_stellar_moves_after_the_tera():
    """L175: the moves a Stellar-terastallized mon used (its types boosted once), not before."""
    t = run(START + """
|move|p2a: Bob|Earthquake|p1a: Fishy
|upkeep
|turn|2
|-terastallize|p2a: Bob|Stellar
|move|p2a: Bob|Knock Off|p1a: Fishy
|-damage|p1a: Fishy|400/503
|upkeep
|turn|3
|move|p2a: Bob|Earthquake|p1a: Fishy|[miss]
|-miss|p2a: Bob|p1a: Fishy
|upkeep
|turn|4
|move|p2a: Bob|Fake Out||[still]
|-fail|p2a: Bob
|upkeep
|turn|5
""")  # fmt: skip
    # (S158: marked as it hits -- Showdown's, in the damage's STAB: not a miss, not a failure)
    assert t["p2"].stellar_moves == {"gliscor": {"knockoff"}}


def test_used_once_intrepid_sword():
    """L184: Intrepid Sword is once per battle too (Showdown's swordBoost), as Dauntless Shield."""
    t = run(START + """
|-ability|p2a: Bob|Intrepid Sword|boost
|-boost|p2a: Bob|atk|1
|upkeep
|turn|2
""")  # fmt: skip
    assert t["p2"].used_once == {"gliscor"}


# 2026-10-23: the state-construction differential's finds (enginecheck/statebuild.py), each
# against Showdown's behaviour


def test_a_fail_on_the_target_is_the_movers():
    """Toxic on a poisoned foe: the -fail names the target; the failed move is the mover's."""
    t = run(START + "|move|p2a: Bob|Toxic|p1a: Fishy\n|-fail|p1a: Fishy|tox\n|upkeep\n|turn|2")
    assert t["p2"].last_failed and not t["p1"].last_failed


def test_a_status_move_changing_no_stage_failed():
    """Swords Dance at +6: -boost 0, no -fail -- failed; Dragon Dance at +6 Attack, +1 Speed: not."""
    t = run(
        START + "|move|p2a: Bob|Swords Dance|p2a: Bob\n|-boost|p2a: Bob|atk|0\n|upkeep\n|turn|2"
    )
    assert t["p2"].last_failed
    t = run(START + "|move|p2a: Bob|Dragon Dance|p2a: Bob\n|-boost|p2a: Bob|atk|0\n"
            "|-boost|p2a: Bob|spe|1\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p2"].last_failed


def test_a_reflected_move_is_not_the_reflectors():
    """Magic Bounce: the reflected line is not the reflector's action; the user's move failed."""
    t = run(START + "|move|p2a: Bob|Toxic|p1a: Fishy\n"
            "|move|p1a: Fishy|Toxic|p2a: Bob|[from] ability: Magic Bounce\n|-fail|p2a: Bob|tox\n"
            "|move|p1a: Fishy|Body Press|p2a: Bob\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].last_failed and not t["p1"].last_failed


def test_a_broken_protect_resets_the_count():
    """Phantom Force / Feint break a protection: Gen 6+ deletes the stall counter."""
    t = run(START + "|move|p1a: Fishy|Protect|p1a: Fishy\n|-singleturn|p1a: Fishy|Protect\n"
            "|move|p2a: Bob|Phantom Force|p1a: Fishy|[from] lockedmove\n"
            "|-activate|p1a: Fishy|move: Phantom Force|[broken]\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].protect == 0


def test_rooms_and_screens_count_their_ends_of_turn():
    """Trick Room / screens: ends of turn counted (poke-env's start turn was one off at a forced
    switch after the turn's end)."""
    t = run(START + "|move|p1a: Fishy|Trick Room|p1a: Fishy\n|-fieldstart|move: Trick Room|[of] p1a: Fishy\n"
            "|-sidestart|p1: A|Reflect\n|upkeep\n|turn|2\n|upkeep")  # fmt: skip
    assert t["p1"].fields_elapsed["trickroom"] == 2 and t["p1"].side_elapsed["reflect"] == 2
    t = run(START + "|-sidestart|p1: A|Reflect\n|upkeep\n|-sideend|p1: A|Reflect\n|turn|2")
    assert "reflect" not in t["p1"].side_elapsed


def test_charging_and_locking_moves():
    """-prepare: charging until the move fires (not with -anim: fired at once); Outrage locks,
    a failed first use (immune) does not, the fatigue confusion ends it."""
    t = run(
        START
        + "|move|p1a: Fishy|Meteor Beam||[still]\n|-prepare|p1a: Fishy|Meteor Beam\n|upkeep\n|turn|2"
    )
    assert t["p1"].charging == "meteorbeam"
    t = run(START + "|move|p1a: Fishy|Solar Beam||[still]\n|-prepare|p1a: Fishy|Solar Beam\n"
            "|-anim|p1a: Fishy|Solar Beam|p2a: Bob\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].charging is None
    t = run(START + "|move|p1a: Fishy|Outrage|p2a: Bob\n|-damage|p2a: Bob|50/100\n|upkeep\n|turn|2")
    assert t["p1"].locked == ["outrage", 1]
    t = run(START + "|move|p1a: Fishy|Outrage|p2a: Bob\n|-immune|p2a: Bob\n|upkeep\n|turn|2")
    assert t["p1"].locked is None
    t = run(START + "|move|p1a: Fishy|Outrage|p2a: Bob\n|upkeep\n|turn|2\n"
            "|move|p1a: Fishy|Outrage|p2a: Bob|[from]lockedmove\n|-start|p1a: Fishy|confusion|[fatigue]\n"
            "|upkeep\n|turn|3")  # fmt: skip
    assert t["p1"].locked is None


def test_more_of_the_logs_facts():
    """2026-10-23 (state-construction differential), each Showdown's: Protean / Libero's change
    from the log; an absorbing ability fails the move (Flash Fire's -start, Wind Rider's -ability
    form); Synthesis at full HP is no failure (NOT_FAIL), Substitute's is; a failed Protect drops
    its count at once; an end-of-turn Future Sight's -immune is not the last move's; an ability's
    boost after a status move is not the move's; Destiny Bond till its next move; Roost this turn;
    the Metronome item's count; a reflected move is its reflector's result; a switch-in's first
    turn out; Skill Swap: no Regenerator at its switch-out."""
    t = run(
        START
        + "|move|p2a: Bob|Pyro Ball|p1a: Fishy\n|-start|p2a: Bob|typechange|Fire|[from] ability: Libero"
    )
    assert t["p2"].protean
    t = run(
        START
        + "|move|p2a: Bob|Pyro Ball|p1a: Fishy\n|-start|p1a: Fishy|ability: Flash Fire\n|upkeep\n|turn|2"
    )
    assert t["p2"].last_failed and t["p1"].flashfire
    t = run(START + "|move|p2a: Bob|Hurricane|p1a: Fishy\n|-ability|p1a: Fishy|Wind Rider|boost\n"
            "|-boost|p1a: Fishy|atk|1\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].last_failed
    t = run(
        START + "|move|p1a: Fishy|Synthesis|p1a: Fishy\n|-fail|p1a: Fishy|heal\n|upkeep\n|turn|2"
    )
    assert not t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Substitute|p1a: Fishy\n|-fail|p1a: Fishy|move: Substitute|[weak]\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Protect|p1a: Fishy\n|-singleturn|p1a: Fishy|Protect\n|upkeep\n|turn|2\n"
            "|move|p1a: Fishy|Protect||[still]\n|-fail|p1a: Fishy")  # fmt: skip
    assert t["p1"].protect == 0
    t = run(START + "|move|p1a: Fishy|Taunt|p2a: Bob\n|-start|p2a: Bob|move: Taunt\n"
            "|-end|p2a: Bob|move: Future Sight\n|-immune|p2a: Bob\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(START + "|move|p2a: Bob|Stealth Rock||[still]\n|-fail|p2a: Bob\n"
            "|-ability|p1a: Fishy|Speed Boost|boost\n|-boost|p1a: Fishy|spe|1\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].last_failed
    t = run(
        START
        + "|move|p2a: Bob|Destiny Bond|p2a: Bob\n|-singlemove|p2a: Bob|Destiny Bond\n|upkeep\n|turn|2"
    )
    assert t["p2"].destinybond
    t = run(START + "|move|p2a: Bob|Roost|p2a: Bob\n|-singleturn|p2a: Bob|move: Roost")
    assert t["p2"].roosted
    t = run(
        START
        + "|move|p1a: Fishy|Body Press|p2a: Bob\n|upkeep\n|turn|2\n|move|p1a: Fishy|Body Press|p2a: Bob"
    )
    assert t["p1"].consecutive == 1
    t = run(START + "|move|p1a: Fishy|Stealth Rock|p2a: Bob\n"
            "|move|p2a: Bob|Stealth Rock||[from] ability: Magic Bounce|[still]\n|-fail|p2a: Bob\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].last_failed and t["p2"].last_failed
    t = run(START)
    assert t["p1"].fresh == 2
    t = run(START + "|-activate|p1a: Fishy|Skill Swap|Regenerator|Unaware|[of] p2a: Bob\n"
            "|switch|p2a: Rob|Corviknight, M|100/100")  # fmt: skip
    assert "gliscor" in t["p2"].no_regen


def test_formes_from_the_log():
    """A detailschange's forme stays (the species the engine needs: Ogerpon's tera); a
    -formechange's until the switch-out."""
    t = run(START + "|-formechange|p2a: Bob|Gliscor-Fake|[msg]")
    assert t["p2"].temp_forme == ("Bob", "gliscorfake")
    t = run(START + "|detailschange|p2a: Bob|Ogerpon-Wellspring-Tera, F, tera:Water")
    assert t["p2"].formes["Bob"] == "ogerponwellspringtera"
    assert t["p2"].names["Bob"] == "gliscor"  # (the key stays: poke-env's species does)
    # (a record kept under the key is found after the forme change: Eiscue-Noice's eaten berry)
    t = run(START + "|-enditem|p2a: Bob|Sitrus Berry|[eat]\n|detailschange|p2a: Bob|Gliscor-Fake, F\n"
            "|-status|p2a: Bob|slp")  # fmt: skip
    assert t["p2"].last_item["gliscor"] == "sitrusberry" and t["p2"].status["gliscor"] == "slp"
    # (switched back in with the forme in its details: the key moves, the forme maps to it --
    # 2026-10-23: a Mimikyu-Busted's Red Card was lost)
    t = run(START + "|-enditem|p2a: Bob|Sitrus Berry|[eat]\n|detailschange|p2a: Bob|Gliscor-Fake, F\n"
            "|switch|p2a: Bob|Gliscor-Fake, F|100/100")  # fmt: skip
    assert t["p2"].last_item[t["p2"].k("gliscorfake")] == "sitrusberry"


def test_the_logs_facts_third_batch():
    """2026-10-23 (state-construction differential, 8,500 battles): a confused self-hit is a failed
    action (and ends a lock); a status move at a Substitute is no failure, a damaging one's -fail
    is; Psychic Terrain stopping a priority move fails it; Spite's PP; the last item -- used up,
    eaten, a gem's, not one knocked off, a popped Air Balloon; Harvest clears it; Lunar Dance
    restores the PP; Cud Chew's counter; a Simple Beam / Gastro Acid's ability; a type change
    before / after terastallizing."""
    t = run(
        START
        + "|-activate|p1a: Fishy|confusion\n|-damage|p1a: Fishy|400/503|[from] confusion\n|upkeep\n|turn|2"
    )
    assert t["p1"].last_failed and t["p1"].fresh == 0
    t = run(START + "|move|p2a: Bob|Substitute|p2a: Bob\n|-start|p2a: Bob|Substitute\n"
            "|move|p1a: Fishy|Will-O-Wisp||[still]\n|-fail|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(START + "|move|p2a: Bob|Substitute|p2a: Bob\n|-start|p2a: Bob|Substitute\n"
            "|move|p1a: Fishy|Sucker Punch||[still]\n|-fail|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].last_failed
    t = run(START + "|move|p2a: Bob|Quick Attack|p1a: Fishy\n|-activate|p1a: Fishy|move: Psychic Terrain\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].last_failed
    t = run(START + "|move|p1a: Fishy|Spite|p2a: Bob\n|-activate|p2a: Bob|move: Spite|Earthquake|4")
    assert t["p2"].pp_taken["gliscor"]["earthquake"] == 4
    t = run(START + "|-enditem|p1a: Fishy|Sitrus Berry|[eat]\n|-enditem|p2a: Bob|Leftovers|[from] move: Knock Off\n"
            "|-enditem|p1a: Fishy|Normal Gem|[from] gem")  # fmt: skip
    assert t["p1"].last_item["dondozo"] == "normalgem" and "gliscor" not in t["p2"].last_item
    t = run(START + "|-enditem|p1a: Fishy|Air Balloon")
    assert "dondozo" not in t["p1"].last_item
    t = run(
        START
        + "|-enditem|p1a: Fishy|Sitrus Berry|[eat]\n|-item|p1a: Fishy|Sitrus Berry|[from] ability: Harvest"
    )
    assert "dondozo" not in t["p1"].last_item
    t = run(START + "|move|p1a: Fishy|Spite|p2a: Bob\n|-activate|p2a: Bob|move: Spite|Earthquake|4\n"
            "|-heal|p2a: Bob|100/100|[from] move: Lunar Dance")  # fmt: skip
    assert "gliscor" not in t["p2"].pp_taken  # (Lunar Dance's PP restore: poke-env's, S84)
    t = run(
        START
        + "|move|p2a: Bob|Earthquake|p1a: Fishy\n|-enditem|p1a: Fishy|Sitrus Berry|[eat]\n|upkeep\n|turn|2"
    )
    assert t["p1"].cud == 1
    t = run(
        START
        + "|move|p2a: Bob|Simple Beam|p1a: Fishy\n|-ability|p1a: Fishy|Simple|[from] move: Simple Beam"
    )
    assert t["p1"].ability_now == "simple"
    t = run(START + "|move|p2a: Bob|Gastro Acid|p1a: Fishy\n|-endability|p1a: Fishy")
    assert t["p1"].ability_now == "none" and t["p1"].gastro
    t = run(
        START
        + "|-terastallize|p2a: Bob|Electric\n|-start|p2a: Bob|typechange|Ground|[from] move: Double Shock"
    )
    assert not t["p2"].typechanged
    t = run(
        START
        + "|-start|p2a: Bob|typechange|Fire|[from] ability: Protean\n|-terastallize|p2a: Bob|Ice"
    )
    assert t["p2"].typechanged


def test_pressure_under_neutralizing_gas_takes_one_pp():
    """poke-env took 2 PP at a Pressure holder under Neutralizing Gas (agents/poke_env_fixes.py)."""
    import logging

    from poke_env.battle import Battle

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Weezing|Weezing-Galar|100/100", "|switch|p2a: Kyurem|Kyurem|100/100",
                 "|-ability|p2a: Kyurem|Pressure", "|-ability|p1a: Weezing|Neutralizing Gas", "|turn|1",
                 "|move|p1a: Weezing|Pain Split|p2a: Kyurem"]:  # fmt: skip
        b.parse_message(line.split("|"))
    mv = next(iter(b.active_pokemon.moves.values()))
    assert mv.max_pp - mv.current_pp == 1


def test_a_broken_illusion_keeps_its_volatiles():
    """S60: a Salt Cure on a disguised Zoroark that broke its Illusion: poke-env cleared it with
    the disguise's switch-out, the Zoroark had none (agents/poke_env_fixes.py)."""
    import logging

    from poke_env.battle import Battle, Effect

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Garganacl|Garganacl|100/100", "|switch|p2a: Slowking|Slowking|100/100",
                 "|turn|1", "|move|p1a: Garganacl|Salt Cure|p2a: Slowking", "|-damage|p2a: Slowking|80/100",
                 "|-start|p2a: Slowking|Salt Cure", "|replace|p2a: Zoroark|Zoroark-Hisui, M",
                 "|-end|p2a: Zoroark|Illusion"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert b.opponent_active_pokemon.species == "zoroarkhisui"
    assert Effect.SALT_CURE in b.opponent_active_pokemon.effects
    # (a display typechange -- the disguise's apparent types, [silent] -- is not the Zoroark's:
    # S83)
    b = Battle("battle-gen9ou-4", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Garganacl|Garganacl|100/100", "|switch|p2a: Hatterene|Hatterene, F|100/100",
                 "|turn|1", "|-terastallize|p2a: Hatterene|Water", "|switch|p2a: Slowking|Slowking|100/100",
                 "|turn|2", "|switch|p2a: Hatterene|Hatterene, F|100/100",
                 "|-start|p2a: Hatterene|typechange|Water|[silent]", "|turn|3",
                 "|move|p1a: Garganacl|Salt Cure|p2a: Hatterene", "|-start|p2a: Hatterene|Salt Cure",
                 "|replace|p2a: Zoroark|Zoroark-Hisui, M", "|-end|p2a: Zoroark|Illusion"]:  # fmt: skip
        b.parse_message(line.split("|"))
    effects = b.opponent_active_pokemon.effects
    assert Effect.SALT_CURE in effects and Effect.TYPECHANGE not in effects

    # live: our Zoroark switched in as the disguise, a Sticky Web's drop on it, the request's
    # active the Zoroark -- the drop is the Zoroark's (S68)
    def mon(ident, details, active):
        ab = "illusion" if details.startswith("Zoroark") else "levitate"
        return {"ident": ident, "details": details, "condition": "100/100", "active": active,
                "moves": ["nightdaze"], "baseAbility": ab, "item": "", "ability": ab,
                "stats": {"atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 1}, "teraType": "Dark",
                "terastallized": ""}  # fmt: skip

    b = Battle("battle-gen9ou-2", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    side = lambda z: {  # noqa: E731
        "name": "us",
        "id": "p1",
        "pokemon": [
            mon("p1: Bronzong", "Bronzong", not z),
            mon("p1: Zoroark", "Zoroark-Hisui, M", z),
        ],
    }
    b.parse_request({"side": side(False), "rqid": 1})
    for line in ["|switch|p1a: Bronzong|Bronzong|100/100", "|switch|p2a: Slowking|Slowking|100/100",
                 "|turn|1", "|move|p2a: Slowking|Sticky Web|p1a: Bronzong", "|upkeep", "|turn|2",
                 "|switch|p1a: Bronzong|Bronzong|100/100", "|-activate|p1a: Bronzong|move: Sticky Web",
                 "|-unboost|p1a: Bronzong|spe|1", "|upkeep", "|turn|3"]:  # fmt: skip
        b.parse_message(line.split("|"))
    b.parse_request({"active": [{"moves": [{"move": "Night Daze", "id": "nightdaze", "pp": 16, "maxpp": 16,
                                            "disabled": False}]}], "side": side(True), "rqid": 2})  # fmt: skip
    assert b.active_pokemon.species == "zoroarkhisui" and b.active_pokemon.boosts["spe"] == -1
    # (a lead: the Zoroark not in poke-env's team before the first request after the log)
    b = Battle("battle-gen9ou-3", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Bronzong|Bronzong|100/100", "|switch|p2a: Landorus|Landorus-Therian, M|100/100",
                 "|-ability|p2a: Landorus|Intimidate|boost", "|-unboost|p1a: Bronzong|atk|1", "|turn|1"]:  # fmt: skip
        b.parse_message(line.split("|"))
    b.parse_request({"active": [{"moves": [{"move": "Night Daze", "id": "nightdaze", "pp": 16, "maxpp": 16,
                                            "disabled": False}]}], "side": side(True), "rqid": 1})  # fmt: skip
    assert b.active_pokemon.species == "zoroarkhisui" and b.active_pokemon.boosts["atk"] == -1

    # (later turns: the request made the Zoroark the active, the log names the disguise -- its
    # stage changes are the Zoroark's -- poke-env's own get_pokemon -- and stay through the
    # Illusion's end: S81)
    def req(r):
        return {"active": [{"moves": [{"move": "Night Daze", "id": "nightdaze", "pp": 16, "maxpp": 16,
                                       "disabled": False}]}], "side": side(True), "rqid": r}  # fmt: skip

    for line in ["|move|p2a: Landorus|Earth Power|p1a: Bronzong", "|-damage|p1a: Bronzong|50/100",
                 "|-unboost|p1a: Bronzong|spd|1", "|upkeep", "|turn|2"]:  # fmt: skip
        b.parse_message(line.split("|"))
    b.parse_request(req(2))
    for line in ["|move|p2a: Landorus|Earth Power|p1a: Bronzong", "|-damage|p1a: Bronzong|20/100",
                 "|replace|p1a: Zoroark|Zoroark-Hisui, M", "|-end|p1a: Zoroark|Illusion", "|upkeep", "|turn|3"]:  # fmt: skip
        b.parse_message(line.split("|"))
    b.parse_request(req(3))
    assert b.active_pokemon.species == "zoroarkhisui"
    assert (b.active_pokemon.boosts["atk"], b.active_pokemon.boosts["spd"]) == (-1, -1)

    # (live, our Zoroark switched in as a Pressure mon: its max HP the Zoroark's -- poke-env
    # switches the Zoroark in, a hit at it takes 1 PP: S86)
    def mon2(ident, details, hp, active, ability):
        return {
            **mon(ident, details, active),
            "condition": hp,
            "baseAbility": ability,
            "ability": ability,
        }

    b = Battle("battle-gen9ou-7", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    team = lambda z: {  # noqa: E731
        "name": "us",
        "id": "p1",
        "pokemon": [
            mon2("p1: Clodsire", "Clodsire, M", "464/464", not z, "unaware"),
            mon2("p1: Corviknight", "Corviknight, F", "399/399", False, "pressure"),
            mon2("p1: Zoroark", "Zoroark-Hisui, M", "251/251", z, "illusion"),
        ],
    }
    b.parse_request({"side": team(False), "rqid": 1})
    for line in ["|switch|p1a: Clodsire|Clodsire, M|464/464", "|switch|p2a: Azumarill|Azumarill, F|100/100",
                 "|turn|1", "|switch|p1a: Corviknight|Corviknight, F|251/251",
                 "|move|p2a: Azumarill|Liquidation|p1a: Corviknight", "|-damage|p1a: Corviknight|118/251"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert b.active_pokemon.species == "zoroarkhisui" and b.active_pokemon.current_hp == 118
    mv = b.opponent_active_pokemon.moves["liquidation"]
    assert mv.max_pp - mv.current_pp == 1
    assert b._replay_data[-3][2] == "p1a: Corviknight"  # (the log as shown: the timers' disguise)


def test_a_temporary_forme_ends_with_its_switch_out():
    """S66: Meloetta-Pirouette (-formechange) switched out and back in as Aria kept Pirouette's
    types in poke-env (agents/poke_env_fixes.py); a detailschange's forme stays."""
    import logging

    from poke_env.battle import Battle, PokemonType

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Garganacl|Garganacl|100/100", "|switch|p2a: Meloetta|Meloetta|100/100",
                 "|turn|1", "|move|p2a: Meloetta|Relic Song|p1a: Garganacl",
                 "|-formechange|p2a: Meloetta|Meloetta-Pirouette|[msg]", "|upkeep", "|turn|2"]:  # fmt: skip
        b.parse_message(line.split("|"))
    mel = b.opponent_active_pokemon
    assert PokemonType.FIGHTING in mel.types
    for line in ["|switch|p2a: Palafin|Palafin|100/100", "|detailschange|p2a: Palafin|Palafin-Hero",
                 "|upkeep", "|turn|3", "|switch|p2a: Meloetta|Meloetta|100/100"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert PokemonType.PSYCHIC in mel.types and PokemonType.FIGHTING not in mel.types
    palafin = next(m for m in b.opponent_team.values() if m.species.startswith("palafin"))
    assert palafin.base_stats["atk"] == 160  # (Hero's, kept)


def test_lunar_dance_and_skill_swap_pp():
    """S84: Lunar Dance restores the PP (poke-env's count -- Pressure's 2 included after; the
    timers' 1 per use read 1 PP too many). S85: Skill Swap's [of] mon's own ability is the one the
    user got -- a Pressure announced after it was taken as the [of] mon's own: 2 PP for every
    move at it after the swap back."""
    import logging

    from poke_env.battle import Battle

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-5", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Diancie|Diancie|100/100", "|switch|p2a: Kingambit|Kingambit, F|100/100",
                 "|-ability|p2a: Kingambit|Pressure", "|turn|1", "|move|p1a: Diancie|Earth Power|p2a: Kingambit",
                 "|-heal|p1a: Diancie|100/100|[from] move: Lunar Dance",
                 "|move|p1a: Diancie|Earth Power|p2a: Kingambit"]:  # fmt: skip
        b.parse_message(line.split("|"))
    mv = b.active_pokemon.moves["earthpower"]
    assert mv.max_pp - mv.current_pp == 2
    b = Battle("battle-gen9ou-6", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Deoxys|Deoxys-Speed|100/100", "|switch|p2a: Skarmory|Skarmory, F|100/100",
                 "|-ability|p1a: Deoxys|Pressure", "|turn|1",
                 "|-activate|p1a: Deoxys|Skill Swap|Sturdy|Pressure|[of] p2a: Skarmory",
                 "|-ability|p2a: Skarmory|Pressure",
                 "|-activate|p1a: Deoxys|Skill Swap|Pressure|Sturdy|[of] p2a: Skarmory",
                 "|-ability|p1a: Deoxys|Pressure", "|switch|p2a: Heatran|Heatran, M|100/100",
                 "|switch|p2a: Skarmory|Skarmory, F|100/100", "|move|p1a: Deoxys|Taunt|p2a: Skarmory"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert b.opponent_active_pokemon.ability == "sturdy"
    mv = b.active_pokemon.moves["taunt"]
    assert mv.max_pp - mv.current_pp == 1
    # (S99: a move at the opponent's Zoroark disguised as a Pressure mon took 2 PP; found out, 1)
    b = Battle("battle-gen9ou-8", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Dragapult|Dragapult, F|100/100", "|switch|p2a: Corviknight|Corviknight, F|100/100",
                 "|-ability|p2a: Corviknight|Pressure", "|turn|1", "|switch|p2a: Clodsire|Clodsire, M|100/100",
                 "|turn|2", "|switch|p2a: Corviknight|Corviknight, F|100/100",
                 "|move|p1a: Dragapult|Hex|p2a: Corviknight", "|-damage|p2a: Corviknight|60/100",
                 "|replace|p2a: Zoroark|Zoroark-Hisui, M", "|-end|p2a: Zoroark|Illusion"]:  # fmt: skip
        b.parse_message(line.split("|"))
    mv = b.active_pokemon.moves["hex"]
    assert mv.max_pp - mv.current_pp == 1
    # (S100: Gastro Acid's suppression is logged as -endability: no Pressure after it)
    b = Battle("battle-gen9ou-9", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Eelektross|Eelektross, M|100/100", "|switch|p2a: Corviknight|Corviknight, F|100/100",
                 "|-ability|p2a: Corviknight|Pressure", "|turn|1", "|move|p1a: Eelektross|Gastro Acid|p2a: Corviknight",
                 "|-endability|p2a: Corviknight", "|turn|2", "|move|p1a: Eelektross|Discharge|p2a: Corviknight"]:  # fmt: skip
        b.parse_message(line.split("|"))
    mv = b.active_pokemon.moves["discharge"]
    assert mv.max_pp - mv.current_pp == 1
    # (S115: a Yawned mon's own Rest -- its HP line asleep -- keeps the Yawn: Showdown's own -end)
    from poke_env.battle import Effect

    b = Battle("battle-gen9ou-10", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Dachsbun|Dachsbun, F|100/100", "|switch|p2a: Ursaring|Ursaring, M|60/100",
                 "|turn|1", "|move|p1a: Dachsbun|Yawn|p2a: Ursaring", "|-start|p2a: Ursaring|move: Yawn|[of] p1a: Dachsbun",
                 "|move|p2a: Ursaring|Rest|p2a: Ursaring", "|-status|p2a: Ursaring|slp|[from] move: Rest",
                 "|-heal|p2a: Ursaring|100/100 slp|[silent]", "|upkeep", "|turn|2"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert Effect.YAWN in b.opponent_active_pokemon.effects


def test_the_logs_facts_fourth_batch():
    """2026-10-23 (state-construction differential): Eerie Spell's PP; Court Change swaps the
    conditions' counts; a Regenerator going out under Neutralizing Gas heals nothing; a lock ends
    at its third use (its fatigue silent when confused); Fling's item is the last item; an
    ability's -fail (Synchronize) is not the move's; a broken Illusion's last move."""
    t = run(
        START
        + "|move|p1a: Fishy|Eerie Spell|p2a: Bob\n|-activate|p2a: Bob|move: Eerie Spell|Earthquake|3"
    )
    assert t["p2"].pp_taken["gliscor"]["earthquake"] == 3
    t = run(START + "|-sidestart|p1: A|Reflect\n|upkeep\n|turn|2\n|move|p2a: Bob|Court Change|p2a: Bob\n"
            "|-swapsideconditions\n|-activate|p2a: Bob|move: Court Change")  # fmt: skip
    assert t["p2"].side_elapsed == {"reflect": 1} and t["p1"].side_elapsed == {}
    t = run(
        START + "|-ability|p1a: Fishy|Neutralizing Gas\n|switch|p2a: Rob|Corviknight, M|100/100"
    )
    assert "gliscor" in t["p2"].no_regen
    t = run(START + "".join(f"|move|p1a: Fishy|Outrage|p2a: Bob{'|[from]lockedmove' if k else ''}\n|upkeep\n|turn|{k + 2}\n"
                            for k in range(3)))  # fmt: skip
    assert t["p1"].locked is None
    t = run(
        START + "|move|p2a: Bob|Fling|p1a: Fishy\n|-enditem|p2a: Bob|Toxic Orb|[from] move: Fling"
    )
    assert t["p2"].last_item["gliscor"] == "toxicorb"
    t = run(START + "|move|p1a: Fishy|Will-O-Wisp|p2a: Bob\n|-status|p2a: Bob|brn\n"
            "|-activate|p2a: Bob|ability: Synchronize\n|-fail|p2a: Bob\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(START + "|move|p2a: Bob|Hyper Voice|p1a: Fishy\n|replace|p2a: Zoroark|Zoroark-Hisui, M\n"
            "|-end|p2a: Zoroark|Illusion")  # fmt: skip
    assert t["p2"].illusion_last == "hypervoice"


def test_the_logs_facts_fifth_batch():
    """2026-10-23 (the million-decision differential): Doom Desire is a pending future attack;
    a protection this turn counts at once (mid-turn decisions: Showdown's stall counter); the move
    it chose stays its last (a Metronome-called charge's caller); a Choice item got by Trick after
    its move locks nothing; Imprison; a turn-1 stage change marks the turn even when undone; the
    Sleep Clause stopping a sleep move fails it; a status move at a passed Substitute is no
    failure; Double Shock without its type is no failure, Shed Tail too weak is one."""
    t = run(START + "|move|p1a: Fishy|Doom Desire|p2a: Bob\n|-start|p1a: Fishy|Doom Desire")
    assert t["p1"].future == (3, "dondozo") and t["p1"].future_doom
    t = run(START + "|move|p1a: Fishy|Protect|p1a: Fishy\n|-singleturn|p1a: Fishy|Protect")
    assert t["p1"].protected and t["p1"].protect == 0  # (_counts adds this turn's: 1)
    t = run(START + "|move|p1a: Fishy|Metronome|p1a: Fishy\n|move|p1a: Fishy|Meteor Beam||[from] move: Metronome|[still]\n"
            "|-prepare|p1a: Fishy|Meteor Beam\n|upkeep\n|turn|2\n|move|p1a: Fishy|Meteor Beam|p2a: Bob|[from] lockedmove")  # fmt: skip
    assert t["p1"].own_last == "metronome"
    t = run(START + "|move|p1a: Fishy|Trick|p2a: Bob\n|-activate|p1a: Fishy|move: Trick|[of] p2a: Bob\n"
            "|-item|p1a: Fishy|Choice Band|[from] move: Trick\n|-item|p2a: Bob|Leftovers|[from] move: Trick")  # fmt: skip
    assert t["p1"].item_new
    t = run(START + "|move|p1a: Fishy|Imprison|p1a: Fishy\n|-start|p1a: Fishy|move: Imprison")
    assert t["p1"].imprison
    t = timers([x.split("|") for x in ["|switch|p1a: Fishy|Dondozo, M|503/503", "|switch|p2a: Bob|Gliscor, F|100/100",
                                       "|-unboost|p1a: Fishy|atk|1", "|turn|1", "|-clearallboost"]])  # fmt: skip
    assert t["p1"].lowered_t1
    t = run(
        START
        + "|move|p1a: Fishy|Spore|p2a: Bob\n|-message|Sleep Clause Mod activated.\n|upkeep\n|turn|2"
    )
    assert t["p1"].last_failed
    t = run(START + "|move|p2a: Bob|Shed Tail|p2a: Bob\n|-start|p2a: Bob|Substitute|[from] move: Shed Tail\n"
            "|switch|p2a: Rob|Corviknight, M|100/100|[from] Shed Tail\n|move|p1a: Fishy|Leech Seed||[still]\n"
            "|-fail|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(
        START
        + "|move|p1a: Fishy|Double Shock||[still]\n|-fail|p1a: Fishy|move: Double Shock\n|upkeep\n|turn|2"
    )
    assert not t["p1"].last_failed
    t = run(
        START
        + "|move|p1a: Fishy|Shed Tail|p1a: Fishy\n|-fail|p1a: Fishy|move: Shed Tail|[weak]\n|upkeep\n|turn|2"
    )
    assert t["p1"].last_failed


def test_the_logs_facts_sixth_batch():
    """2026-10-23 (the third million-decision run): an ability stopping a priority move (Armor
    Tail: Showdown's cant names its holder, [of] the mover) fails the mover's move, not the
    holder's."""
    t = run(START + "|move|p2a: Bob|Protect|p2a: Bob\n|-singleturn|p2a: Bob|Protect\n"
            "|move|p1a: Fishy|Aqua Jet||[still]\n|cant|p2a: Bob|ability: Armor Tail|Aqua Jet|[of] p1a: Fishy\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].last_failed and not t["p2"].last_failed
    # (Baneful Bunker logs "move: Protect": its own volatile -- S61)
    t = run(START + "|move|p2a: Bob|Baneful Bunker|p2a: Bob\n|-singleturn|p2a: Bob|move: Protect")
    assert t["p2"].protected_move == "banefulbunker"
    t = run(START + "|move|p2a: Bob|Detect|p2a: Bob\n|-singleturn|p2a: Bob|Protect")
    assert t["p2"].protected_move == "protect"
    # (Dry Skin's heal in the rain at the turn's end is no absorbed move -- S63; one at the move,
    # [of] the mover, is)
    t = run(START + "|move|p2a: Bob|Earthquake|p1a: Fishy\n|-damage|p1a: Fishy|300/503\n"
            "|-weather|RainDance|[upkeep]\n|-heal|p1a: Fishy|363/503|[from] ability: Dry Skin\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p2"].last_failed
    t = run(START + "|move|p2a: Bob|Surf|p1a: Fishy\n|-heal|p1a: Fishy|363/503|[from] ability: Dry Skin|[of] p2a: Bob\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].last_failed
    # (a Perish Song with one target immune -- Good as Gold -- did not fail: S64)
    t = run(START + "|move|p1a: Fishy|Perish Song|p1a: Fishy\n|-start|p1a: Fishy|perish3|[silent]\n"
            "|-immune|p2a: Bob|[from] ability: Good as Gold\n|-fieldactivate|move: Perish Song\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    # (a stopped action -- paralysed -- ends Destiny Bond: its onMoveAborted, S65)
    t = run(START + "|move|p2a: Bob|Destiny Bond|p2a: Bob\n|-singlemove|p2a: Bob|Destiny Bond\n|upkeep\n|turn|2\n"
            "|cant|p2a: Bob|par")  # fmt: skip
    assert not t["p2"].destinybond
    # (a Morpeko terastallized as Hangry stays Hangry after its switch-out: S67)
    t = run(START + "|switch|p2a: Morpeko|Morpeko, F|100/100\n|-formechange|p2a: Morpeko|Morpeko-Hangry\n"
            "|upkeep\n|turn|2\n|-terastallize|p2a: Morpeko|Dark\n|drag|p2a: Bob|Gliscor, M|100/100")  # fmt: skip
    assert t["p2"].formes["Morpeko"] == "morpekohangry"
    # (brought back by Revival Blessing, then terastallized: no longer "revived" -- S69)
    t = run(START + "|faint|p2a: Bob\n|-heal|p2: Bob|50/100|[from] move: Revival Blessing\n"
            "|switch|p2a: Bob|Gliscor, M|50/100\n|-terastallize|p2a: Bob|Water")  # fmt: skip
    assert "gliscor" not in t["p2"].revived
    # (a Truant mon moving under a Neutralizing Gas does not loaf after: S71)
    t = run(START + "|switch|p1a: Weezing|Weezing-Galar, M|100/100\n|-ability|p1a: Weezing|Neutralizing Gas\n"
            "|move|p2a: Bob|Knock Off|p1a: Weezing\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p2"].truant_next
    t = run(START + "|move|p2a: Bob|Knock Off|p1a: Fishy\n|upkeep\n|turn|2")
    assert t["p2"].truant_next
    # (a Choice item got by Trick, then a Struggle: no lock of its set -- S72)
    t = run(START + "|move|p1a: Fishy|Trick|p2a: Bob\n|-activate|p1a: Fishy|move: Trick|[of] p2a: Bob\n"
            "|-item|p2a: Bob|Choice Scarf|[from] move: Trick\n|-item|p1a: Fishy|Choice Band|[from] move: Trick\n"
            "|-activate|p2a: Bob|move: Struggle\n|move|p2a: Bob|Struggle|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].item_new and t["p2"].struggled
    # (a Court Change's swapped screen: its setter of the other side -- S73)
    t = run(START + "|move|p1a: Fishy|Reflect|p1a: Fishy\n|-sidestart|p1: A|Reflect\n|upkeep\n|turn|2\n"
            "|move|p2a: Bob|Court Change|p2a: Bob\n|-swapsideconditions\n|-activate|p2a: Bob|move: Court Change")  # fmt: skip
    assert (
        t["p2"].setters["reflect"] == "dondozo"
        and "reflect" in t["p2"].swapped
        and not t["p1"].swapped
    )
    # (Slow Start's count stops under a Neutralizing Gas: S74)
    # (Bob comes in this turn and its Slow Start begins: not counted this end of turn -- a mon in
    # at the turn's start whose Slow Start began later is: S153)
    t = run(START + "|switch|p2a: Bob|Regigigas|100/100\n|-start|p2a: Bob|ability: Slow Start\n|upkeep\n|turn|2\n"
            "|switch|p1a: Weezing|Weezing-Galar, M|100/100\n"
            "|-ability|p1a: Weezing|Neutralizing Gas\n|upkeep\n|turn|3\n|upkeep\n|turn|4")  # fmt: skip
    assert t["p2"].slowstart == [5, True]  # (not counted: its first turn, then the Gas)
    # (a confused self-hit aborts the move: a charge's second turn ends; Truant ran before it, a
    # paralysis stop too -- a loaf next; asleep not -- S75)
    t = run(START + "|move|p2a: Bob|Phantom Force||[still]\n|-prepare|p2a: Bob|Phantom Force\n|upkeep\n|turn|2\n"
            "|-activate|p2a: Bob|confusion\n|-damage|p2a: Bob|80/100|[from] confusion")  # fmt: skip
    assert t["p2"].charging is None and t["p2"].truant_next
    assert run(START + "|cant|p2a: Bob|par")["p2"].truant_next
    assert not run(START + "|cant|p2a: Bob|slp")["p2"].truant_next
    # (a Neutralizing Gas ending after a Truant mon moved: its onStart, a loaf next -- S76)
    t = run(START + "|switch|p1a: Weezing|Weezing-Galar, M|100/100\n|-ability|p1a: Weezing|Neutralizing Gas\n"
            "|upkeep\n|turn|2\n|move|p2a: Bob|Body Slam|p1a: Weezing\n|-damage|p1a: Weezing|0 fnt\n|faint|p1a: Weezing\n"
            "|-end|p1a: Weezing|ability: Neutralizing Gas")  # fmt: skip
    assert t["p2"].truant_next
    # (an Intimidate a Substitute stopped -- its -immune -- is no failed move of the U-turn's
    # user: S77; a protection broken -- Hyperspace Fury -- ends its volatile too: S78)
    t = run(START + "|move|p2a: Bob|U-turn|p1a: Fishy\n|-damage|p1a: Fishy|400/503\n"
            "|switch|p2a: Rob|Landorus-Therian, M|100/100|[from] U-turn\n|-ability|p2a: Rob|Intimidate|boost\n"
            "|-immune|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p2"].last_failed
    t = run(START + "|move|p2a: Bob|Protect|p2a: Bob\n|-singleturn|p2a: Bob|Protect\n"
            "|move|p1a: Fishy|Hyperspace Fury|p2a: Bob\n|-activate|p2a: Bob|move: Hyperspace Fury|[broken]")  # fmt: skip
    assert t["p2"].protected_move == "" and not t["p2"].protected
    # (a switch-in's Wind Rider after the turn's end is no absorbed move of the foe's: S87)
    t = run(START + "|move|p1a: Fishy|Whirlwind|p2a: Bob\n|drag|p2a: Rob|Corviknight, M|100/100\n|upkeep\n"
            "|switch|p2a: Bram|Brambleghast, F|100/100\n|-ability|p2a: Bram|Wind Rider|boost\n|-boost|p2a: Bram|atk|1\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed


def test_the_logs_facts_seventh_batch():
    """2026-10-23 (the fifth million-decision run, new seeds): Misty / Electric Terrain or
    Safeguard stopping a status fails the move -- not a Yawn's sleep at the turn's end (S89); the
    Sleep Clause after a Yawn's end is no move's failure (S90); an ability's -block (Aroma Veil)
    fails the move (S91); a Substitute ends with its fainted holder (S92); a status move's -fail at
    a Substitute is kept apart -- an Infiltrator's went through (S93)."""
    t = run(
        START
        + "|move|p1a: Fishy|Will-O-Wisp|p2a: Bob\n|-activate|p2a: Bob|move: Misty Terrain\n|upkeep\n|turn|2"
    )
    assert t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Yawn|p2a: Bob\n|-start|p2a: Bob|move: Yawn|[of] p1a: Fishy\n|upkeep\n|turn|2\n"
            "|move|p1a: Fishy|Earthquake|p2a: Bob\n|-damage|p2a: Bob|80/100\n|-end|p2a: Bob|move: Yawn|[silent]\n"
            "|-activate|p2a: Bob|move: Electric Terrain\n|upkeep\n|turn|3")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Earthquake|p2a: Bob\n|-damage|p2a: Bob|80/100\n|-end|p2a: Bob|move: Yawn|[silent]\n"
            "|-message|Sleep Clause Mod activated.\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(
        START
        + "|move|p1a: Fishy|Taunt|p2a: Bob\n|-block|p2a: Bob|ability: Aroma Veil|[of] p2a: Bob\n|upkeep\n|turn|2"
    )
    assert t["p1"].last_failed
    t = run(
        START + "|move|p2a: Bob|Substitute|p2a: Bob\n|-start|p2a: Bob|Substitute\n|faint|p2a: Bob"
    )
    assert not t["p2"].sub_on
    t = run(START + "|move|p2a: Bob|Substitute|p2a: Bob\n|-start|p2a: Bob|Substitute\n"
            "|move|p1a: Fishy|Will-O-Wisp||[still]\n|-fail|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed and t["p1"].last_sub_failed
    # (a new Outrage after a lock that ended silently -- confused: a new lock, not its third use:
    # S96)
    t = run(START + "|move|p1a: Fishy|Outrage|p2a: Bob\n|-damage|p2a: Bob|80/100\n|upkeep\n|turn|2\n"
            "|move|p1a: Fishy|Outrage|p2a: Bob|[from]lockedmove\n|-damage|p2a: Bob|60/100\n|upkeep\n|turn|3\n"
            "|move|p1a: Fishy|Outrage|p2a: Bob\n|-damage|p2a: Bob|40/100\n|upkeep\n|turn|4")  # fmt: skip
    assert t["p1"].locked == ["outrage", 1]
    # (Trick takes the user's and the target's items -- no -enditem: both lost one; Unburden's
    # volatile stays with the new item -- S102)
    t = run(START + "|move|p2a: Bob|Trick|p1a: Fishy\n|-activate|p2a: Bob|move: Trick|[of] p1a: Fishy\n"
            "|-item|p1a: Fishy|Choice Scarf|[from] move: Trick\n|-item|p2a: Bob|Sitrus Berry|[from] move: Trick")  # fmt: skip
    assert t["p1"].item_lost and t["p2"].item_lost
    # (S104: Yawn at a statused foe behind a Substitute fails -- its status checked first)
    t = run(START + "|move|p2a: Bob|Substitute|p2a: Bob\n|-start|p2a: Bob|Substitute\n|-status|p2a: Bob|psn\n"
            "|move|p1a: Fishy|Yawn||[still]\n|-fail|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].last_failed
    # (S105: a Synchronized burn at a Fire type -- its -immune -- is no failed move)
    t = run(START + "|move|p1a: Fishy|Knock Off|p2a: Bob\n|-damage|p2a: Bob|80/100\n"
            "|-status|p1a: Fishy|brn|[from] ability: Flame Body|[of] p2a: Bob\n|-activate|p1a: Fishy|ability: Synchronize\n"
            "|-immune|p2a: Bob\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    # (S106: Take Heart at +6 curing its paralysis did something)
    t = run(START + "|move|p1a: Fishy|Take Heart|p1a: Fishy\n|-boost|p1a: Fishy|spa|0\n|-boost|p1a: Fishy|spd|0\n"
            "|-curestatus|p1a: Fishy|par|[msg]\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    # (S107: Rest stopped by its own Insomnia failed; S108: the Sleep Clause stopping an Effect
    # Spore at the attacker's contact is no failure of its move)
    t = run(START + "|move|p1a: Fishy|Rest|p1a: Fishy\n|-fail|p1a: Fishy|[from] ability: Insomnia|[of] p1a: Fishy\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Wave Crash|p2a: Bob\n|-damage|p2a: Bob|80/100\n|-message|Sleep Clause Mod activated.\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    # (S109: a broken Illusion's status counted under its disguise goes to the Zoroark: its toxic
    # count)
    t = run(START + "|switch|p1a: Hydreigon|Hydreigon, F|251/251\n|-status|p1a: Hydreigon|tox\n|upkeep\n|turn|2\n"
            "|replace|p1a: Zoroark|Zoroark-Hisui, F\n|-end|p1a: Zoroark|Illusion\n|upkeep\n|turn|3")  # fmt: skip
    assert t["p1"].status.get("zoroarkhisui") == "tox" and t["p1"].toxic == 2
    # (S112: Simple Beam on a Dry Skin mon -- the old ability named -- is an ability change)
    t = run(
        START
        + "|move|p1a: Fishy|Simple Beam|p2a: Bob\n|-ability|p2a: Bob|Simple|Dry Skin|[from] move: Simple Beam"
    )
    assert t["p2"].ability_now == "simple" and not t["p1"].failed_now
    # (S113: a broken Illusion's stage changes cleared -- White Herb's negative ones)
    t = run(START + "|switch|p2a: Rob|Corviknight, F|100/100\n|-unboost|p2a: Rob|spe|1\n|-boost|p2a: Rob|atk|1\n"
            "|replace|p2a: Zoroark|Zoroark-Hisui, F\n|-end|p2a: Zoroark|Illusion\n"
            "|-enditem|p2a: Zoroark|White Herb\n|-clearnegativeboost|p2a: Zoroark|[silent]")  # fmt: skip
    assert t["p2"].illusion_boosts == {"atk": 1}
    # (S114: a loaf due before the Gas came stays -- Truant's handler suppressed, its volatile kept)
    t = run(START + "|move|p2a: Bob|Knock Off|p1a: Fishy\n|upkeep\n|turn|2\n|switch|p1a: Weezing|Weezing-Galar, M|100/100\n"
            "|-ability|p1a: Weezing|Neutralizing Gas\n|upkeep\n|turn|3\n|move|p2a: Bob|Rock Slide|p1a: Weezing\n|upkeep\n|turn|4")  # fmt: skip
    assert t["p2"].truant_next
    # (S116: Skill Swap takes Protean -- its use mark gone; S117: a Copycat's Outrage locks)
    t = run(START + "|move|p1a: Fishy|Flower Trick|p2a: Bob\n|-start|p1a: Fishy|typechange|Grass|[from] ability: Protean\n"
            "|move|p2a: Bob|Skill Swap|p1a: Fishy\n|-activate|p2a: Bob|Skill Swap|Protean|Harvest|[of] p1a: Fishy")  # fmt: skip
    assert not t["p1"].protean
    t = run(START + "|move|p2a: Bob|Copycat|p2a: Bob\n|move|p2a: Bob|Outrage|p1a: Fishy|[from] move: Copycat\n"
            "|-damage|p1a: Fishy|300/503\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].locked == ["outrage", 1]
    # (S118: a mon out by fainting has no Regenerator -- brought back by Revival Blessing)
    t = run(
        START
        + "|faint|p2a: Bob\n|switch|p2a: Rob|Corviknight, M|100/100\n|-heal|p2: Bob|50/100|[from] move: Revival Blessing"
    )
    assert "gliscor" in t["p2"].no_regen
    # (S120: a move into Protect -- a null result -- ends the Metronome item's count)
    t = run(START + "|move|p1a: Fishy|Wave Crash|p2a: Bob\n|-damage|p2a: Bob|80/100\n|upkeep\n|turn|2\n"
            "|move|p2a: Bob|Protect|p2a: Bob\n|-singleturn|p2a: Bob|Protect\n|move|p1a: Fishy|Wave Crash|p2a: Bob\n"
            "|-activate|p2a: Bob|move: Protect\n|upkeep\n|turn|3\n|move|p1a: Fishy|Wave Crash|p2a: Bob\n|-damage|p2a: Bob|60/100")  # fmt: skip
    assert t["p1"].consecutive == 0
    # (S123: a Zoroark disguised as our asleep Suicune, found out -- the Suicune's own Rest stays
    # its; the Zoroark gets what this time in changed)
    t = run(START + "|switch|p2a: Sui|Suicune|100/100\n|move|p2a: Sui|Rest|p2a: Sui\n|-status|p2a: Sui|slp|[from] move: Rest\n"
            "|upkeep\n|turn|2\n|switch|p2a: Bob|Gliscor, M|100/100\n|upkeep\n|turn|3\n|switch|p2a: Sui|Suicune|50/100 par\n"
            "|replace|p2a: Zoroark|Zoroark, M\n|-end|p2a: Zoroark|Illusion")  # fmt: skip
    assert t["p2"].status.get("suicune") == "slp" and "suicune" in t["p2"].sleep
    assert t["p2"].status.get("zoroark") == "par"


def test_the_logs_facts_eighth_batch():
    """2026-10-23 (the sixth million-decision run, new seeds): Haze clears a broken Illusion's
    carried stage changes (S125); a field started in the end of turn's residuals is not counted
    by it (S126); Perish Song's silent perish3 is 4 till the turn's end (S128); a no-target move's
    -fail is a failure, Double Shock's too (S129); each time in keeps its shown max HP (S127)."""
    t = run(START + "|switch|p2a: Rob|Corviknight, F|100/100\n|-unboost|p2a: Rob|spe|1\n"
            "|replace|p2a: Zoroark|Zoroark-Hisui, F\n|-end|p2a: Zoroark|Illusion\n|-clearallboost")  # fmt: skip
    assert t["p2"].illusion_boosts == {}
    t = run(START + "|-end|p1a: Fishy|move: Future Sight\n|-damage|p1a: Fishy|400/503\n"
            "|-fieldstart|move: Grassy Terrain|[from] ability: Seed Sower|[of] p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].fields_elapsed["terrain"] == 0
    t = run(START + "|move|p1a: Fishy|Perish Song|p1a: Fishy\n|-start|p1a: Fishy|perish3|[silent]\n"
            "|-start|p2a: Bob|perish3|[silent]")  # fmt: skip
    assert t["p1"].perish_fresh and t["p2"].perish_fresh
    t = run(
        START
        + "|faint|p2a: Bob\n|move|p1a: Fishy|Double Shock|p2: Bob|[notarget]\n|-fail|p1a: Fishy\n|upkeep\n|turn|2"
    )
    assert t["p1"].last_failed
    t = run(START + "|switch|p1a: Rob|Corviknight, F|251/251")
    assert t["p1"].stint["max"] == "251" and t["p1"].past_stints[-1]["species"] == "dondozo"
    # (S132: the Metronome item knocked off -- its volatile till the next move; S133: Aroma Veil
    # blocking a hit's secondary is no failure of the hit)
    t = run(START + "|-enditem|p2a: Bob|Metronome|[from] move: Knock Off|[of] p1a: Fishy")
    assert t["p2"].metronome_gone
    t = run(START + "|move|p1a: Fishy|Psychic Noise|p2a: Bob\n|-damage|p2a: Bob|80/100\n"
            "|-block|p2a: Bob|ability: Aroma Veil|[of] p2a: Bob\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed

    # (S141: Clear Body blocking a Tickle's drop fails it; S142: Own Tempo blocking an Intimidate
    # is no failure of the blocked mon's own move)
    t = run(START + "|move|p1a: Fishy|Tickle|p2a: Bob\n|-fail|p2a: Bob|unboost|[from] ability: Clear Body|[of] p2a: Bob\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Defog|p2a: Bob\n|-fail|p2a: Bob|unboost|[from] ability: Clear Body|[of] p2a: Bob\n"
            "|-sideend|p1: A|Spikes|[from] move: Defog|[of] p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed  # (Defog did more than the drop)
    t = run(START + "|move|p1a: Fishy|Whirlwind|p2a: Bob\n|drag|p2a: Rob|Corviknight, M|100/100\n"
            "|-ability|p2a: Rob|Intimidate|boost\n|-fail|p1a: Fishy|unboost|atk|[from] ability: Own Tempo|[of] p1a: Fishy\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed


def test_imprison_pressure_glaive_rush_and_a_transforms_types():
    """S134: Imprison (self-targeting, mustpressure) at a Pressure foe takes 2 PP -- poke-env
    checked its user. S135: Glaive Rush's drawback ends before a stopped move (paralysis). S136:
    Transform copies its target's types now (a Libero's), not its species'."""
    import logging

    from poke_env.battle import Battle, Effect, PokemonType

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-11", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Mew|Mew|100/100", "|switch|p2a: Kyurem|Kyurem|100/100", "|-ability|p2a: Kyurem|Pressure",
                 "|turn|1", "|move|p1a: Mew|Imprison|p1a: Mew", "|-start|p1a: Mew|move: Imprison", "|upkeep", "|turn|2",
                 "|move|p2a: Kyurem|Glaive Rush|p1a: Mew", "|-damage|p1a: Mew|50/100", "|upkeep", "|turn|3",
                 "|cant|p2a: Kyurem|par"]:  # fmt: skip
        b.parse_message(line.split("|"))
    mv = b.active_pokemon.moves["imprison"]
    assert mv.max_pp - mv.current_pp == 2
    assert Effect.GLAIVE_RUSH not in b.opponent_active_pokemon.effects
    b = Battle("battle-gen9ou-12", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Cinderace|Cinderace|100/100", "|switch|p2a: Ditto|Ditto|100/100", "|turn|1",
                 "|move|p1a: Cinderace|Quick Attack|p2a: Ditto", "|-start|p1a: Cinderace|typechange|Normal|[from] ability: Libero",
                 "|-damage|p2a: Ditto|80/100", "|-transform|p2a: Ditto|p1a: Cinderace|[from] ability: Imposter"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert b.opponent_active_pokemon.base_types == [PokemonType.NORMAL]


def test_a_replays_illusion_and_transform_records():
    """S143: each use's PP this time in -- 2 at a Pressure foe (a broken Illusion's PP: the
    bookkeeping counted 1 a use). S145: a mon out transformed keeps its target (a copied
    Regenerator's heal)."""
    t = run(START + "|-ability|p1a: Fishy|Pressure\n|move|p2a: Bob|Earthquake|p1a: Fishy\n|-damage|p1a: Fishy|400/503\n"
            "|move|p2a: Bob|Swords Dance|p2a: Bob\n|-boost|p2a: Bob|atk|2")  # fmt: skip
    assert t["p2"].stint["costs"] == [2, 1]
    t = run(
        START
        + "|-transform|p2a: Bob|p1a: Fishy|[from] ability: Imposter\n|switch|p2a: Rob|Corviknight, M|100/100"
    )
    assert t["p2"].transformed_out == {"gliscor": "dondozo"}
    # (S147: Psych Up -- |-copyboost|user|target -- the user takes the target's stage changes)
    import logging

    from poke_env.battle import Battle

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-13", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Azumarill|Azumarill|100/100", "|switch|p2a: Corviknight|Corviknight|100/100",
                 "|turn|1", "|-unboost|p1a: Azumarill|evasion|1", "|-boost|p2a: Corviknight|def|2",
                 "|move|p1a: Azumarill|Psych Up|p2a: Corviknight",
                 "|-copyboost|p1a: Azumarill|p2a: Corviknight|[from] move: Psych Up"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert (b.active_pokemon.boosts["evasion"], b.active_pokemon.boosts["def"]) == (0, 2)
    assert b.opponent_active_pokemon.boosts["def"] == 2


def test_a_broken_illusions_tera_is_the_zoroarks():
    """S158 (state_chain): a Zoroark-Hisui terastallized disguised as a Flygon -- the log's
    -terastallize named the Flygon; poke-env kept it on the Flygon, never in, after the Illusion
    broke: our state's Flygon a terastallized Rock type. Its level alike: a Dodrio at the
    Zoroark's 80."""
    import logging

    from poke_env.battle import Battle, PokemonType

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-15", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    # (and its level: the disguise's switch-in details the Zoroark's, L80 -- the preview's L85)
    for line in ["|poke|p2|Flygon, L85, M|", "|poke|p2|Zoroark-Hisui, L80, M|",
                 "|switch|p1a: Garganacl|Garganacl|100/100", "|switch|p2a: Flygon|Flygon, L80, M|100/100", "|turn|1",
                 "|-terastallize|p2a: Flygon|Normal", "|move|p1a: Garganacl|Salt Cure|p2a: Flygon",
                 "|-damage|p2a: Flygon|60/100", "|replace|p2a: Zoroark|Zoroark-Hisui, L80, M",
                 "|-end|p2a: Zoroark|Illusion"]:  # fmt: skip
        b.parse_message(line.split("|"))
    zoroark = b.opponent_active_pokemon
    flygon = next(m for m in b.opponent_team.values() if m.species == "flygon")
    assert (
        zoroark.species == "zoroarkhisui"
        and zoroark.is_terastallized
        and zoroark.tera_type == PokemonType.NORMAL
    )
    assert not flygon.is_terastallized and flygon.tera_type is None
    assert flygon.level == 85 and zoroark.level == 80
    # (the disguise's own, before: a Serperior terastallized, a Zoroark as it later -- its own)
    b = Battle("battle-gen9ou-17", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Garganacl|Garganacl|100/100", "|switch|p2a: Serperior|Serperior, F|100/100", "|turn|1",
                 "|-terastallize|p2a: Serperior|Electric", "|switch|p2a: Weavile|Weavile, F|100/100", "|turn|2",
                 "|switch|p2a: Serperior|Serperior, F|100/100", "|turn|3", "|replace|p2a: Zoroark|Zoroark-Hisui, F",
                 "|-end|p2a: Zoroark|Illusion"]:  # fmt: skip
        b.parse_message(line.split("|"))
    serperior = next(m for m in b.opponent_team.values() if m.species == "serperior")
    assert serperior.is_terastallized and not b.opponent_active_pokemon.is_terastallized
    # (never found out: the Spectrier's level its own still)
    b = Battle("battle-gen9ou-16", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|poke|p2|Spectrier, L75|", "|poke|p2|Zoroark, L83, M|", "|switch|p1a: Garganacl|Garganacl|100/100",
                 "|switch|p2a: Spectrier|Spectrier, L83|100/100", "|turn|1"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert b.opponent_active_pokemon.level == 75


def test_the_replay_paths_second_run_facts():
    """2026-10-23 (the replay path's second million-decision run): a broken Illusion's shown
    status is the Zoroark's, its disguise's own (the same) kept (S146); a Sticky Web's drop a
    Clear Body blocks is no failure of the Whirlwind that dragged it in (S149); an asleep Truant
    mon's loaf mark is kept -- Truant's handler after sleep's (S150); Defog at the evasion floor
    clearing hazards did something (S151); a Soak on the disguise is the Zoroark's (S148)."""
    t = run(START + "|switch|p2a: Tink|Tinkaton, F|100/100 tox\n|upkeep\n|turn|2\n|switch|p2a: Bob|Gliscor, M|100/100\n"
            "|switch|p2a: Tink|Tinkaton, F|60/100 tox\n|replace|p2a: Zoroark|Zoroark, M\n|-end|p2a: Zoroark|Illusion")  # fmt: skip
    assert t["p2"].status.get("zoroark") == "tox" and t["p2"].status.get("tinkaton") == "tox"
    t = run(START + "|move|p1a: Fishy|Whirlwind|p2a: Bob\n|drag|p2a: Reg|Registeel|100/100\n"
            "|-activate|p2a: Reg|move: Sticky Web\n|-fail|p2a: Reg|unboost|[from] ability: Clear Body|[of] p2a: Reg\n"
            "|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(START + "|move|p2a: Bob|Knock Off|p1a: Fishy\n|upkeep\n|turn|2\n|cant|p2a: Bob|slp")
    assert t["p2"].truant_next
    t = run(START + "|move|p1a: Fishy|Defog|p2a: Bob\n|-unboost|p2a: Bob|evasion|0\n"
            "|-sideend|p2: B|Stealth Rock|[from] move: Defog|[of] p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    import logging

    from poke_env.battle import Battle, PokemonType

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-14", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Alomomola|Alomomola|100/100", "|switch|p2a: Iron Treads|Iron Treads|100/100", "|turn|1",
                 "|move|p1a: Alomomola|Soak|p2a: Iron Treads", "|-start|p2a: Iron Treads|typechange|Water",
                 "|replace|p2a: Zoroark|Zoroark-Hisui, F", "|-end|p2a: Zoroark|Illusion"]:  # fmt: skip
        b.parse_message(line.split("|"))
    assert b.opponent_active_pokemon.base_types == [PokemonType.WATER]
    # (a recharge removes Truant's volatile -- Showdown's mustrecharge: no loaf after)
    t = run(
        START
        + "|move|p2a: Bob|Giga Impact|p1a: Fishy\n|-mustrecharge|p2a: Bob\n|upkeep\n|turn|2\n|cant|p2a: Bob|recharge"
    )
    assert not t["p2"].truant_next


def test_a_healing_wish_waits_for_a_mon_that_needs_it():
    """S158 (state_chain): Gen 9's Healing Wish / Lunar Dance stay on the slot until a mon that
    needs them comes in (Showdown's slot condition, its -heal ends it) -- our states never had
    one: a hurt mon switching in later not healed in the search."""
    t = run(START + "|move|p1a: Fishy|Healing Wish|p1a: Fishy\n|faint|p1a: Fishy\n|upkeep\n"
            "|switch|p1a: Tank|Snorlax, M|430/430\n|turn|2")  # fmt: skip
    assert t["p1"].healing_wish == 1 and t["p2"].healing_wish == 0
    t = run(START + "|move|p1a: Fishy|Lunar Dance|p1a: Fishy\n|faint|p1a: Fishy\n|upkeep\n"
            "|switch|p1a: Tank|Snorlax, M|200/430\n|-heal|p1a: Tank|430/430|[from] move: Lunar Dance\n|turn|2")  # fmt: skip
    assert t["p1"].healing_wish == 0
    t = run(START + "|move|p1a: Fishy|Healing Wish|p1a: Fishy\n|faint|p1a: Fishy\n|upkeep\n"
            "|switch|p1a: Tank|Snorlax, M|430/430\n|turn|2\n|switch|p1a: Cat|Persian, M|100/300\n"
            "|-heal|p1a: Cat|300/300|[from] move: Healing Wish\n|upkeep\n|turn|3")  # fmt: skip
    assert t["p1"].healing_wish == 0
    # (no one to switch to: [still], -fail -- none waits)
    t = run(
        START
        + "|move|p1a: Fishy|Healing Wish|p1a: Fishy|[still]\n|-fail|p1a: Fishy\n|upkeep\n|turn|2"
    )
    assert t["p1"].healing_wish == 0


def test_a_rage_fists_count_after_transform_and_future_sight():
    """S158 (the state checks, once they compared every field): Showdown's transformInto copies the
    target's timesAttacked -- a Ditto's after an Imposter, kept; a Future Sight's hit is a move's
    hit too (moveHit) -- both counted for Rage Fist."""
    t = run(START + "|move|p1a: Fishy|Wave Crash|p2a: Bob\n|-damage|p2a: Bob|60/100\n|upkeep\n|turn|2\n"
            "|switch|p1a: Copy|Ditto|300/300\n|-transform|p1a: Copy|p2a: Bob|[from] ability: Imposter\n|upkeep\n|turn|3")  # fmt: skip
    assert t["p1"].times_attacked.get("ditto") == 1
    t = run(START + "|move|p1a: Fishy|Future Sight|p2a: Bob\n|-start|p1a: Fishy|move: Future Sight\n|upkeep\n|turn|2\n"
            "|upkeep\n|turn|3\n|-end|p2a: Bob|move: Future Sight\n|-supereffective|p2a: Bob\n|-damage|p2a: Bob|40/100\n"
            "|upkeep\n|turn|4")  # fmt: skip
    assert t["p2"].times_attacked.get("gliscor") == 1


def test_revival_blessings_faints_counted():
    """S158 (the state checks, every field): the faints Revival Blessing undid -- Showdown's
    totalFainted keeps them (Supreme Overlord, Last Respects; the engine's revived_faints, L220):
    never passed."""
    t = run(START + "|faint|p1a: Fishy\n|upkeep\n|switch|p1a: Paw|Pawmot, M|300/300\n|turn|2\n"
            "|move|p1a: Paw|Revival Blessing|p1a: Paw\n|-heal|p1a: Fishy|251/503|[from] move: Revival Blessing\n"
            "|upkeep\n|turn|3")  # fmt: skip
    assert t["p1"].revivals == 1 and t["p2"].revivals == 0


def test_a_multi_hits_count_follows_its_last_hit():
    """S158: Showdown's timesAttacked takes a multi-hit move's hits all at once when its last one
    landed on the mon (moveDamage, the last hit's) -- those on its Substitute too; none when the
    last was on the Substitute. A Bullet Seed: three on the Substitute, one breaking it, one on
    the Uxie -- five."""
    t = run(START + "|move|p2a: Bob|Bullet Seed|p1a: Fishy\n" + "|-activate|p1a: Fishy|move: Substitute|[damage]\n" * 3
            + "|-end|p1a: Fishy|Substitute\n|-damage|p1a: Fishy|400/503\n|-hitcount|p1a: Fishy|5\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].times_attacked.get("dondozo") == 5
    t = run(START + "|move|p2a: Bob|Bullet Seed|p1a: Fishy\n" + "|-activate|p1a: Fishy|move: Substitute|[damage]\n" * 2
            + "|-hitcount|p1a: Fishy|2\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].times_attacked.get("dondozo")
    t = run(START + "|move|p2a: Bob|Bullet Seed|p1a: Fishy\n" + "|-damage|p1a: Fishy|450/503\n" * 3
            + "|-hitcount|p1a: Fishy|3\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].times_attacked.get("dondozo") == 3


def test_our_disguise_as_a_spectator_sees_it():
    """2026-10-26 review: the tera and level fixes ran for the opponent alone -- the replay path's
    (a spectator's: no request) own Zoroark disguised as our Serperior moved Serperior's own
    earlier tera to it, and its disguise kept the Zoroark's level."""
    import logging

    from poke_env.battle import Battle

    import alpha_poke.agents.engine_state  # noqa: F401 (the fixes)

    b = Battle("battle-gen9ou-18", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|poke|p1|Serperior, L88, F|", "|poke|p1|Zoroark-Hisui, L80, F|",
                 "|switch|p1a: Serperior|Serperior, L88, F|100/100", "|switch|p2a: Garganacl|Garganacl|100/100",
                 "|turn|1", "|-terastallize|p1a: Serperior|Grass", "|switch|p1a: Weavile|Weavile, F|100/100", "|turn|2",
                 "|switch|p1a: Serperior|Serperior, L80, F|100/100", "|turn|3",
                 "|replace|p1a: Zoroark|Zoroark-Hisui, L80, F", "|-end|p1a: Zoroark|Illusion"]:  # fmt: skip
        b.parse_message(line.split("|"))
    serperior = next(m for m in b.team.values() if m.species == "serperior")
    assert serperior.is_terastallized and serperior.level == 88
    assert not b.active_pokemon.is_terastallized


def test_the_moves_a_choice_lock_counts_since_its_item_or_transform():
    """2026-10-26: the foe's Choice-lock guard counts its distinct moves since its item last
    changed (a Trick's Choice Scarf locks from the next move) or it transformed (the lock's move
    no longer its own: Showdown's choicelock ends) -- the full corpus' Quagsire and Ditto."""
    t = run(START + "|move|p2a: Bob|Earthquake|p1a: Fishy\n|upkeep\n|turn|2\n|move|p1a: Fishy|Trick|p2a: Bob\n"
            "|-item|p2a: Bob|Choice Scarf|[from] move: Trick\n|move|p2a: Bob|Toxic|p1a: Fishy\n|upkeep\n|turn|3")  # fmt: skip
    st = t["p2"].stint
    assert st["moves"][st["item_mark"] :] == ["toxic"]
    t = run(START + "|move|p2a: Bob|Transform|p1a: Fishy\n|-transform|p2a: Bob|p1a: Fishy\n|upkeep\n|turn|2\n"
            "|move|p2a: Bob|Substitute|p2a: Bob\n|upkeep\n|turn|3")  # fmt: skip
    st = t["p2"].stint
    assert st["moves"][st["item_mark"] :] == ["substitute"]


def test_a_lingering_aromas_ability_on_the_contact_mon():
    """B5 (the timers' copy): Mummy / Lingering Aroma give the contact mon -- the -activate's second
    -- their ability, its old one the [ability]; its Protean's mark goes. The poke-env copy
    (poke_env_fixes._ability_set, B8) sets the same: neither alone is seen in the differential --
    this test the timers' guard (2026-10-26, the mutation run)."""
    t = run(START + "|move|p1a: Fishy|Wave Crash|p2a: Bob\n"
            "|-activate|p2a: Bob|ability: Lingering Aroma|p1a: Fishy|[ability] Unaware\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p1"].ability_now == "lingeringaroma" and not t["p1"].protean
