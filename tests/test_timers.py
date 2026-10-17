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
