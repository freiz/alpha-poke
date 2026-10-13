"""The alpha-poke patches of poke-engine (rust/patches), end to end: states built with the
patched Python binding, transitions from alpha_search's engine (2026-10-11)."""

import alpha_search
import poke_engine as pe


def mon(sp, item="none", moves=("tackle",), spe=100):
    return pe.Pokemon(id=sp, hp=300, maxhp=300, item=item, speed=spe, attack=200, defense=200,
                      moves=[pe.Move(id=m, pp=10) for m in moves])  # fmt: skip


def after(item2, spe1=200, spe2=100, moves1=("tackle",)):
    s1 = pe.Side(pokemon=[mon("garchomp", moves=moves1, spe=spe1), mon("dondozo")],
                 active_index=pe.PokemonIndex("0"))  # fmt: skip
    s2 = pe.Side(pokemon=[mon("tinglu", item=item2, spe=spe2), mon("gholdengo")],
                 active_index=pe.PokemonIndex("0"))  # fmt: skip
    outs = alpha_search.chance_outcomes(pe.State(side_one=s1, side_two=s2).to_string(), 0, 0)
    assert len(outs) == 1
    return pe.State.from_string(outs[0][1])


def test_binding_knows_patched_items():
    assert pe.Pokemon(id="tinglu", item="ejectbutton").item == "ejectbutton"
    assert pe.Pokemon(id="tinglu", item="redcard").item == "redcard"


def test_eject_button_holder_hit_first_does_not_move():
    st = after("ejectbutton")
    assert st.side_two.force_switch and st.side_two.pokemon[0].item == "NONE"
    assert st.side_one.pokemon[0].hp == 300  # the holder never attacked


def test_eject_button_after_the_holder_moved():
    st = after("ejectbutton", spe1=50, spe2=100)
    assert st.side_two.force_switch and st.side_one.pokemon[0].hp < 300


def test_eject_button_stops_u_turn():
    st = after("ejectbutton", moves1=("uturn",))
    assert st.side_two.force_switch and not st.side_one.force_switch


def test_red_card_drags_the_attacker():
    st = after("redcard")
    assert str(st.side_one.active_index) == "1" and st.side_two.pokemon[0].item == "NONE"
    assert st.side_one.pokemon[1].hp < 300  # the holder hit the dragged-in mon


def test_network_item_ids_unchanged():
    # the patched items keep the id they had before (unknown item); the others keep theirs
    ids = alpha_search.encode_ids("item", ["ejectbutton", "redcard", "unknownitem", "leftovers"])
    assert ids[0] == ids[1] == ids[2] == 1 and ids[3] > 1


def end_of_turn(volatile: str, **dur):
    """The state after one turn (both use Splash) of a side-one active with ``volatile`` and
    the given durations."""
    s1 = pe.Side(pokemon=[mon("garchomp", moves=("splash",), spe=200), mon("dondozo")],
                 active_index=pe.PokemonIndex("0"), volatile_statuses={volatile},
                 volatile_status_durations=pe.VolatileStatusDurations(**dur))  # fmt: skip
    s2 = pe.Side(pokemon=[mon("tinglu", moves=("splash",)), mon("gholdengo")],
                 active_index=pe.PokemonIndex("0"))  # fmt: skip
    outs = alpha_search.chance_outcomes(pe.State(side_one=s1, side_two=s2).to_string(), 0, 0)
    assert len(outs) == 1
    return pe.State.from_string(outs[0][1]).side_one


def test_heal_block_ends_after_two_turns():
    s = end_of_turn("healblock")  # applied this turn: one turn left
    assert "HEALBLOCK" in s.volatile_statuses and s.volatile_status_durations.healblock == 1
    s = end_of_turn("healblock", healblock=1)
    assert "HEALBLOCK" not in s.volatile_statuses and s.volatile_status_durations.healblock == 0


def test_magnet_rise_ends_after_five_turns():
    s = end_of_turn("magnetrise", magnetrise=3)
    assert "MAGNETRISE" in s.volatile_statuses and s.volatile_status_durations.magnetrise == 4
    s = end_of_turn("magnetrise", magnetrise=4)
    assert "MAGNETRISE" not in s.volatile_statuses


def test_throat_chop_blocks_sound_moves_for_two_turns():
    s1 = pe.Side(pokemon=[mon("primarina", moves=("boomburst", "moonblast"), spe=200),
                          mon("dondozo")],
                 active_index=pe.PokemonIndex("0"), volatile_statuses={"throatchop"})  # fmt: skip
    s2 = pe.Side(pokemon=[mon("tinglu", moves=("splash",)), mon("gholdengo")],
                 active_index=pe.PokemonIndex("0"))  # fmt: skip
    ours, *_ = alpha_search.ismcts([pe.State(side_one=s1, side_two=s2).to_string()], 20,
                                   iterations=64)  # fmt: skip
    assert "boomburst" not in {c for c, _, _ in ours} and "moonblast" in {c for c, _, _ in ours}
    s = end_of_turn("throatchop", throatchop=1)
    assert "THROATCHOP" not in s.volatile_statuses


def test_charge_ends_with_the_electric_move():
    def hit(volatiles):
        s1 = pe.Side(pokemon=[mon("raichu", moves=("thunderbolt",), spe=200), mon("dondozo")],
                     active_index=pe.PokemonIndex("0"), volatile_statuses=volatiles)  # fmt: skip
        s2 = pe.Side(pokemon=[mon("tinglu", moves=("splash",)), mon("gholdengo")],
                     active_index=pe.PokemonIndex("0"))  # fmt: skip
        outs = alpha_search.chance_outcomes(pe.State(side_one=s1, side_two=s2).to_string(), 0, 0)
        st = pe.State.from_string(max(outs, key=lambda o: o[0])[1])
        return 300 - st.side_two.pokemon[0].hp, st.side_one.volatile_statuses

    plain, _ = hit(set())
    charged, vols = hit({"charge"})
    assert charged > 1.8 * plain and "CHARGE" not in vols


NEW_ITEMS = ["pechaberry", "cheriberry", "rawstberry", "aspearberry", "persimberry", "mentalherb",
             "safetygoggles", "ejectpack"]  # fmt: skip


def test_new_items_parse_and_stay_unknown_to_the_network():
    for i in NEW_ITEMS:  # through the engine's parser (not the unknown item)
        st = pe.State(side_one=pe.Side(pokemon=[mon("tinglu", item=i)],
                                       active_index=pe.PokemonIndex("0")))  # fmt: skip
        assert pe.State.from_string(st.to_string()).side_one.pokemon[0].item == i.upper()
    ids = alpha_search.encode_ids("item", [*NEW_ITEMS, "unknownitem"])
    assert set(ids) == {1}


def turn(item="none", status="none", volatiles=(), ability="none", moves2=("splash",), dur=None,
         move1="splash"):  # fmt: skip
    """The outcomes (probability, side one) of one turn: side one's active (``item``,
    ``status``, ``volatiles``) uses Splash, side two ``moves2[0]``."""
    p1 = pe.Pokemon(id="garchomp", hp=300, maxhp=300, item=item, status=status, ability=ability,
                    speed=200, moves=[pe.Move(id=move1, pp=10)])  # fmt: skip
    s1 = pe.Side(pokemon=[p1, mon("dondozo")], active_index=pe.PokemonIndex("0"),
                 volatile_statuses=set(volatiles),
                 volatile_status_durations=dur or pe.VolatileStatusDurations())  # fmt: skip
    s2 = pe.Side(pokemon=[mon("tinglu", moves=moves2), mon("gholdengo")],
                 active_index=pe.PokemonIndex("0"))  # fmt: skip
    outs = alpha_search.chance_outcomes(pe.State(side_one=s1, side_two=s2).to_string(), 0, 0)
    return [(o[0], pe.State.from_string(o[1]).side_one) for o in outs]


def test_status_berries_cure_their_status():
    for item, status in (("pechaberry", "poison"), ("cheriberry", "paralyze"),
                         ("rawstberry", "burn"), ("pechaberry", "toxic")):  # fmt: skip
        for _, s in turn(item, status):
            assert s.pokemon[0].status == "NONE" and s.pokemon[0].item == "NONE", (item, status)
    for _, s in turn("cheriberry", "burn"):  # the wrong berry stays
        assert s.pokemon[0].item == "CHERIBERRY"


def test_persim_berry_and_mental_herb():
    for _, s in turn("persimberry", volatiles=("confusion",)):
        assert "CONFUSION" not in s.volatile_statuses and s.pokemon[0].item == "NONE"
    dur = pe.VolatileStatusDurations(taunt=1)
    for _, s in turn("mentalherb", volatiles=("taunt",), dur=dur, move1="tackle"):
        assert "TAUNT" not in s.volatile_statuses and s.volatile_status_durations.taunt == 0
        assert s.pokemon[0].item == "NONE"


def test_safety_goggles_block_spore():
    assert all(s.pokemon[0].status == "SLEEP" for _, s in turn(moves2=("spore",)))
    assert all(s.pokemon[0].status == "NONE" for _, s in turn("safetygoggles", moves2=("spore",)))


def test_early_bird_wakes_sooner():
    def woke(ability, turns):
        p1 = pe.Pokemon(id="garchomp", hp=300, maxhp=300, status="sleep", ability=ability,
                        sleep_turns=turns, speed=200,
                        moves=[pe.Move(id="tackle", pp=10)])  # fmt: skip
        s1 = pe.Side(pokemon=[p1, mon("dondozo")], active_index=pe.PokemonIndex("0"))
        s2 = pe.Side(pokemon=[mon("tinglu", moves=("splash",)), mon("gholdengo")],
                     active_index=pe.PokemonIndex("0"))  # fmt: skip
        outs = alpha_search.chance_outcomes(pe.State(side_one=s1, side_two=s2).to_string(), 0, 0)
        return sum(o[0] for o in outs if pe.State.from_string(o[1]).side_one.pokemon[0].status
                   == "NONE")  # fmt: skip

    assert woke("none", 0) == 0 and abs(woke("earlybird", 0) - 1 / 3) < 0.01
    assert abs(woke("none", 1) - 1 / 3) < 0.01 and woke("earlybird", 1) > 0.99


def duel(move1, p2_item="none", p2_ability="none", p1_item="none", atk=200):
    """Outcomes (probability, state) of side one (faster) using ``move1`` on side two (Splash)."""
    p1 = pe.Pokemon(id="dragapult", hp=300, maxhp=300, item=p1_item, speed=300, attack=atk,
                    special_attack=atk, moves=[pe.Move(id=move1, pp=10)])  # fmt: skip
    p2 = pe.Pokemon(id="golisopod", hp=300, maxhp=300, item=p2_item, ability=p2_ability,
                    speed=100, defense=150, special_defense=150,
                    moves=[pe.Move(id="splash", pp=10)])  # fmt: skip
    s1 = pe.Side(pokemon=[p1, mon("dondozo")], active_index=pe.PokemonIndex("0"))
    s2 = pe.Side(pokemon=[p2, mon("gholdengo")], active_index=pe.PokemonIndex("0"))
    outs = alpha_search.chance_outcomes(pe.State(side_one=s1, side_two=s2).to_string(), 0, 0)
    return [(o[0], pe.State.from_string(o[1])) for o in outs]


def test_wimp_out_switches_out_below_half():
    outs = duel("bodyslam", p2_ability="wimpout", atk=520)
    hit = [st for _, st in outs if 0 < st.side_two.pokemon[0].hp <= 150]
    assert hit and all(st.side_two.force_switch for st in hit)
    above = [st for _, st in outs if st.side_two.pokemon[0].hp > 150]
    assert all(not st.side_two.force_switch for st in above)
    assert all(not st.side_two.force_switch for _, st in duel("bodyslam", atk=520))


def test_eject_pack_on_a_lowered_defender():
    outs = duel("charm", p2_item="ejectpack")
    assert all(st.side_two.force_switch and st.side_two.pokemon[0].item == "NONE"
               for _, st in outs)  # fmt: skip


def test_eject_pack_after_draco_meteor():
    outs = duel("dracometeor", p1_item="ejectpack")
    hit = [st for _, st in outs if st.side_one.special_attack_boost < 0]
    assert hit and all(st.side_one.force_switch and st.side_one.pokemon[0].item == "NONE"
                       for st in hit)  # fmt: skip
    assert all(
        not st.side_one.force_switch for _, st in outs if st.side_one.special_attack_boost == 0
    )
    assert all(not st.side_one.force_switch for _, st in duel("dracometeor"))
