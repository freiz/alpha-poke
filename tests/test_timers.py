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
|upkeep
|turn|3
""")  # fmt: skip
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
    t = run(START + "|move|p2a: Bob|Swords Dance|p2a: Bob\n|-boost|p2a: Bob|atk|0\n|upkeep\n|turn|2")
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
    t = run(START + "|move|p1a: Fishy|Meteor Beam||[still]\n|-prepare|p1a: Fishy|Meteor Beam\n|upkeep\n|turn|2")
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
    t = run(START + "|move|p2a: Bob|Pyro Ball|p1a: Fishy\n|-start|p2a: Bob|typechange|Fire|[from] ability: Libero")
    assert t["p2"].protean
    t = run(START + "|move|p2a: Bob|Pyro Ball|p1a: Fishy\n|-start|p1a: Fishy|ability: Flash Fire\n|upkeep\n|turn|2")
    assert t["p2"].last_failed and t["p1"].flashfire
    t = run(START + "|move|p2a: Bob|Hurricane|p1a: Fishy\n|-ability|p1a: Fishy|Wind Rider|boost\n"
            "|-boost|p1a: Fishy|atk|1\n|upkeep\n|turn|2")  # fmt: skip
    assert t["p2"].last_failed
    t = run(START + "|move|p1a: Fishy|Synthesis|p1a: Fishy\n|-fail|p1a: Fishy|heal\n|upkeep\n|turn|2")
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
    t = run(START + "|move|p2a: Bob|Destiny Bond|p2a: Bob\n|-singlemove|p2a: Bob|Destiny Bond\n|upkeep\n|turn|2")
    assert t["p2"].destinybond
    t = run(START + "|move|p2a: Bob|Roost|p2a: Bob\n|-singleturn|p2a: Bob|move: Roost")
    assert t["p2"].roosted
    t = run(START + "|move|p1a: Fishy|Body Press|p2a: Bob\n|upkeep\n|turn|2\n|move|p1a: Fishy|Body Press|p2a: Bob")
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


def test_the_logs_facts_third_batch():
    """2026-10-23 (state-construction differential, 8,500 battles): a confused self-hit is a failed
    action (and ends a lock); a status move at a Substitute is no failure, a damaging one's -fail
    is; Psychic Terrain stopping a priority move fails it; Spite's PP; the last item -- used up,
    eaten, a gem's, not one knocked off, a popped Air Balloon; Harvest clears it; Lunar Dance
    restores the PP; Cud Chew's counter; a Simple Beam / Gastro Acid's ability; a type change
    before / after terastallizing."""
    t = run(START + "|-activate|p1a: Fishy|confusion\n|-damage|p1a: Fishy|400/503|[from] confusion\n|upkeep\n|turn|2")
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
    t = run(START + "|-enditem|p1a: Fishy|Sitrus Berry|[eat]\n|-item|p1a: Fishy|Sitrus Berry|[from] ability: Harvest")
    assert "dondozo" not in t["p1"].last_item
    t = run(START + "|-heal|p1a: Fishy|503/503|[from] move: Lunar Dance\n|move|p1a: Fishy|Body Press|p2a: Bob")
    assert t["p1"].pp_reset["dondozo"]["bodypress"] == 1
    t = run(START + "|move|p2a: Bob|Earthquake|p1a: Fishy\n|-enditem|p1a: Fishy|Sitrus Berry|[eat]\n|upkeep\n|turn|2")
    assert t["p1"].cud == 1
    t = run(START + "|move|p2a: Bob|Simple Beam|p1a: Fishy\n|-ability|p1a: Fishy|Simple|[from] move: Simple Beam")
    assert t["p1"].ability_now == "simple"
    t = run(START + "|move|p2a: Bob|Gastro Acid|p1a: Fishy\n|-endability|p1a: Fishy")
    assert t["p1"].ability_now == "none" and t["p1"].gastro
    t = run(START + "|-terastallize|p2a: Bob|Electric\n|-start|p2a: Bob|typechange|Ground|[from] move: Double Shock")
    assert not t["p2"].typechanged
    t = run(START + "|-start|p2a: Bob|typechange|Fire|[from] ability: Protean\n|-terastallize|p2a: Bob|Ice")
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


def test_the_logs_facts_fourth_batch():
    """2026-10-23 (state-construction differential): Eerie Spell's PP; Court Change swaps the
    conditions' counts; a Regenerator going out under Neutralizing Gas heals nothing; a lock ends
    at its third use (its fatigue silent when confused); Fling's item is the last item; an
    ability's -fail (Synchronize) is not the move's; a broken Illusion's last move."""
    t = run(START + "|move|p1a: Fishy|Eerie Spell|p2a: Bob\n|-activate|p2a: Bob|move: Eerie Spell|Earthquake|3")
    assert t["p2"].pp_taken["gliscor"]["earthquake"] == 3
    t = run(START + "|-sidestart|p1: A|Reflect\n|upkeep\n|turn|2\n|move|p2a: Bob|Court Change|p2a: Bob\n"
            "|-swapsideconditions\n|-activate|p2a: Bob|move: Court Change")  # fmt: skip
    assert t["p2"].side_elapsed == {"reflect": 1} and t["p1"].side_elapsed == {}
    t = run(START + "|-ability|p1a: Fishy|Neutralizing Gas\n|switch|p2a: Rob|Corviknight, M|100/100")
    assert "gliscor" in t["p2"].no_regen
    t = run(START + "".join(f"|move|p1a: Fishy|Outrage|p2a: Bob{'|[from]lockedmove' if k else ''}\n|upkeep\n|turn|{k + 2}\n"
                            for k in range(3)))  # fmt: skip
    assert t["p1"].locked is None
    t = run(START + "|move|p2a: Bob|Fling|p1a: Fishy\n|-enditem|p2a: Bob|Toxic Orb|[from] move: Fling")
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
    t = run(START + "|move|p1a: Fishy|Spore|p2a: Bob\n|-message|Sleep Clause Mod activated.\n|upkeep\n|turn|2")
    assert t["p1"].last_failed
    t = run(START + "|move|p2a: Bob|Shed Tail|p2a: Bob\n|-start|p2a: Bob|Substitute|[from] move: Shed Tail\n"
            "|switch|p2a: Rob|Corviknight, M|100/100|[from] Shed Tail\n|move|p1a: Fishy|Leech Seed||[still]\n"
            "|-fail|p1a: Fishy\n|upkeep\n|turn|2")  # fmt: skip
    assert not t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Double Shock||[still]\n|-fail|p1a: Fishy|move: Double Shock\n|upkeep\n|turn|2")
    assert not t["p1"].last_failed
    t = run(START + "|move|p1a: Fishy|Shed Tail|p1a: Fishy\n|-fail|p1a: Fishy|move: Shed Tail|[weak]\n|upkeep\n|turn|2")
    assert t["p1"].last_failed
