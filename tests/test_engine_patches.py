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
