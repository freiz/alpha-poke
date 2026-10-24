"""Engine state (design D17): must recharge, the opponent's PP, Perish Song, Disable, a hit
Substitute, items extending screens / weather, Illusion."""

import logging
import random

import pytest
from poke_env.battle import Battle

from alpha_poke.agents.engine_state import build_state


def mon(ident, species, moves, item="leftovers", ability="pressure", active=False):
    return {"ident": ident, "details": f"{species}, L100", "condition": "400/400",
            "active": active, "moves": moves, "baseAbility": ability, "item": item,
            "ability": ability, "stats": {"atk": 200, "def": 200, "spa": 200, "spd": 200,
                                          "spe": 200},
            "teraType": "Normal", "terastallized": ""}  # fmt: skip


def battle(
    lines,
    us="Garchomp",
    item="leftovers",
    ability="roughskin",
    moves=("earthquake", "reflect", "substitute", "hyperbeam"),
) -> Battle:
    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    side = [mon(f"p1: {us}", us, list(moves), item, ability, True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    req = [{"move": m, "id": m, "pp": 8, "maxpp": 8, "disabled": False} for m in moves]
    b.parse_request(
        {"active": [{"moves": req}], "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 1}
    )
    for line in [f"|switch|p1a: {us}|{us}|400/400", "|switch|p2a: Gholdengo|Gholdengo|100/100",
                 "|turn|1", *lines]:  # fmt: skip
        b.parse_message(line.split("|"))
    return b


@pytest.fixture(scope="module")
def belief():
    from alpha_poke.agents.belief_state import BeliefModel

    return BeliefModel.load()


def state(b, belief):
    return build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(0))


def test_must_recharge(belief):
    b = battle(["|move|p1a: Garchomp|Hyper Beam|p2a: Gholdengo", "|-mustrecharge|p1a: Garchomp",
                "|turn|2"])  # fmt: skip
    assert "mustrecharge" in state(b, belief).side_one.volatile_statuses


def test_opponent_pp_from_uses(belief):
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|2",
                "|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|3"])  # fmt: skip
    moves = {m.id: m.pp for m in state(b, belief).side_two.pokemon[0].moves}
    assert moves["makeitrain"] == 8 - 2  # 5 PP, 8 with PP Ups


def test_disable_and_perish(belief):
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|2",
                "|-start|p2a: Gholdengo|Disable|Make It Rain", "|-start|p2a: Gholdengo|perish3",
                "|turn|3"])  # fmt: skip
    s = state(b, belief)
    them = s.side_two.pokemon[0]
    assert [m.disabled for m in them.moves if m.id == "makeitrain"] == [True]
    assert "perish3" in s.side_two.volatile_statuses


DISABLED_REFLECT = ["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                    "|move|p2a: Gholdengo|Disable|p1a: Garchomp",
                    "|-start|p1a: Garchomp|Disable|Reflect", "|upkeep|", "|turn|3"]  # fmt: skip


def _disable_holds(s, want: int):
    """Side one's Reflect (slot 1) disabled by the volatile, its count ``want``; after one
    Earthquake it is still disabled (2026-10-23 review: the move's flag alone -- the engine's
    next move enabled it again)."""
    import poke_engine as pe

    one = s.side_one
    assert "disable" in one.volatile_statuses
    assert one.volatile_status_durations.disable == 1 * 8 + want
    assert [m.disabled for m in one.pokemon[0].moves][:2] == [False, True]
    for o in pe.generate_instructions(s, "earthquake", "none"):
        assert not any("EnableMove" in str(i) and "M1" in str(i) for i in o.instruction_list), o


def test_disable_holds_at_the_live_root(belief):
    """Our Reflect disabled (the request leaves it out): the Disable's volatile and count."""
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|2", *DISABLED_REFLECT])
    b.available_moves  # noqa: B018
    req = [{"move": m, "id": m, "pp": 8, "maxpp": 8, "disabled": m == "reflect"}
           for m in ("earthquake", "reflect", "substitute", "hyperbeam")]  # fmt: skip
    side = [mon("p1: Garchomp", "Garchomp", ["earthquake", "reflect", "substitute", "hyperbeam"],
                "leftovers", "roughskin", True), mon("p1: Dondozo", "Dondozo", ["wavecrash"])]
    b.parse_request({"active": [{"moves": req}], "side": {"name": "us", "id": "p1", "pokemon": side},
                     "rqid": 2})  # fmt: skip
    _disable_holds(state(b, belief), 1)  # Garchomp had moved: 5 turns, one end passed


def test_disable_holds_in_a_replay_position(belief):
    """Side one from a spectator log (training positions): Reflect disabled too (was usable)."""
    from alpha_poke.agents.engine_state import KnownSet, SpectatorSide

    b = battle(["|turn|2", *DISABLED_REFLECT])
    known = {"garchomp": KnownSet(moves=["earthquake", "reflect", "substitute", "hyperbeam"],
                                  item="leftovers", ability="roughskin", tera="normal")}
    spec = SpectatorSide(team=list(b.team.values()), known=known, names=("Garchomp", "Dondozo"))
    s = build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(0), spectator=spec)
    one = s.side_one
    slot = [m.id for m in one.pokemon[0].moves].index("reflect")
    assert "disable" in one.volatile_statuses
    assert one.volatile_status_durations.disable == slot * 8 + 1
    assert one.pokemon[0].moves[slot].disabled


def test_disable_before_its_target_moved_is_four_turns():
    from alpha_poke.agents.timers import timers

    lines = ["|switch|p1a: Garchomp|Garchomp|400/400", "|switch|p2a: Gholdengo|Gholdengo|100/100",
             "|turn|1", "|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|turn|2",
             "|move|p2a: Gholdengo|Disable|p1a: Garchomp", "|-start|p1a: Garchomp|Disable|Reflect",
             "|upkeep|"]  # fmt: skip
    assert timers([x.split("|") for x in lines])["p1"].disable_ends == 2
    lines[-3:] = ["|move|p1a: Garchomp|Earthquake|p2a: Gholdengo",
                  "|-start|p1a: Garchomp|Disable|Earthquake|[from] ability: Cursed Body|[of] p2a: Gholdengo",
                  "|upkeep|"]  # fmt: skip
    assert timers([x.split("|") for x in lines])["p1"].disable_ends == 2  # (Cursed Body: 4 too)


def test_hit_substitute(belief):
    b = battle(["|move|p1a: Garchomp|Substitute|p1a: Garchomp",
                "|-start|p1a: Garchomp|Substitute", "|turn|2",
                "|-activate|p1a: Garchomp|Substitute|[damage]", "|turn|3"])  # fmt: skip
    assert state(b, belief).side_one.substitute_health == 400 // 4 // 2


def test_light_clay_reflect(belief):
    # (a real log's end of turn: "|upkeep|" -- the timers count them, 2026-10-23)
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|upkeep|", "|turn|2"], item="lightclay")  # fmt: skip
    assert state(b, belief).side_one.side_conditions.reflect == 8 - 1
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|upkeep|", "|turn|2"])  # fmt: skip
    assert state(b, belief).side_one.side_conditions.reflect == 5 - 1


def test_heat_rock_drought(belief):
    # set during turn 1, one end of turn since (the timers count the ends of turn:
    # doc/engine-diff.md L3; a real log has an "|upkeep|" at every end of turn)
    b = battle(["|-weather|SunnyDay|[from] ability: Drought|[of] p1a: Torkoal", "|upkeep|",
                "|turn|2"], us="Torkoal", item="heatrock", ability="drought",
               moves=("lavaplume", "rapidspin", "yawn", "stealthrock"))  # fmt: skip
    assert state(b, belief).weather_turns_remaining == 8 - 1


def _spectator(b, item, ability, moves):
    from alpha_poke.agents.engine_state import KnownSet, SpectatorSide

    sp = next(iter(b.team.values())).species
    known = {sp: KnownSet(moves=list(moves), item=item, ability=ability, tera="normal")}
    return SpectatorSide(team=list(b.team.values()), known=known, names=("Garchomp", "Dondozo"))


def test_extending_items_in_a_replay_position(belief):
    """2026-10-23 review: a replay's own side (spectator) had no items for the durations: its
    Light Clay Reflect and Heat Rock sun read 5 turns (live: 8)."""
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|upkeep|", "|turn|2"], item="lightclay")  # fmt: skip
    spec = _spectator(b, "lightclay", "roughskin", ("earthquake", "reflect", "substitute", "hyperbeam"))
    s = build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(0), spectator=spec)
    assert s.side_one.side_conditions.reflect == 8 - 1 == state(b, belief).side_one.side_conditions.reflect
    moves = ("lavaplume", "rapidspin", "yawn", "stealthrock")
    b = battle(["|-weather|SunnyDay|[from] ability: Drought|[of] p1a: Torkoal", "|upkeep|",
                "|turn|2"], us="Torkoal", item="heatrock", ability="drought", moves=moves)  # fmt: skip
    spec = _spectator(b, "heatrock", "drought", moves)
    s = build_state(b, belief, ("Torkoal", "Dondozo"), random.Random(0), spectator=spec)
    assert s.weather_turns_remaining == 8 - 1


@pytest.mark.parametrize("take", [
    ["|move|p1a: Garchomp|Earthquake|p2a: Gholdengo", "|-damage|p2a: Gholdengo|50/100",
     "|-item|p1a: Garchomp|Light Clay|[from] ability: Magician|[of] p2a: Gholdengo"],
    ["|move|p1a: Garchomp|Thief|p2a: Gholdengo", "|-damage|p2a: Gholdengo|50/100",
     "|-enditem|p2a: Gholdengo|Light Clay|[silent]|[from] move: Thief|[of] p1a: Garchomp",
     "|-item|p1a: Garchomp|Light Clay|[from] move: Thief|[of] p2a: Gholdengo"],
])  # fmt: skip
def test_a_screen_set_without_an_item_is_not_extended_by_a_light_clay_taken_after(belief, take):
    """2026-10-23 review: an itemless Reflect setter takes a Light Clay the next turn (Magician,
    Thief): 5 turns (Showdown's 3 left after two ends of turn), not 8."""
    lines = ["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect", "|upkeep|",
             "|turn|2", *take, "|upkeep|", "|turn|3"]
    b = battle(lines, item="lightclay")  # (the request after: it holds the Light Clay)
    assert state(b, belief).side_one.side_conditions.reflect == 5 - 2


def test_a_screen_set_without_an_item_is_not_extended_by_a_light_clay_given_after(belief):
    """2026-10-23 review: Garchomp with no item sets Reflect, the next turn a Trick gives it a
    Light Clay: Showdown's 5 turns (3 left after two ends of turn), not 8 (6)."""
    lines = ["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect", "|upkeep|",
             "|turn|2", "|move|p2a: Gholdengo|Trick|p1a: Garchomp",
             "|-activate|p2a: Gholdengo|move: Trick|[of] p1a: Garchomp",
             "|-item|p1a: Garchomp|Light Clay|[from] move: Trick",
             "|-enditem|p2a: Gholdengo|Light Clay|[silent]|[from] move: Trick", "|upkeep|", "|turn|3"]
    b = battle(lines, item="lightclay")  # (the request after the Trick: it holds the Light Clay)
    assert state(b, belief).side_one.side_conditions.reflect == 5 - 2


@pytest.mark.parametrize("lines", [
    ["|move|p2a: Gholdengo|Knock Off|p1a: Garchomp",
     "|-enditem|p1a: Garchomp|Light Clay|[from] move: Knock Off|[of] p2a: Gholdengo"],
    ["|move|p2a: Gholdengo|Trick|p1a: Garchomp", "|-activate|p2a: Gholdengo|move: Trick|[of] p1a: Garchomp",
     "|-item|p1a: Garchomp|Choice Scarf|[from] move: Trick",
     "|-item|p2a: Gholdengo|Light Clay|[from] move: Trick"],
])  # fmt: skip
def test_an_extended_screen_keeps_its_length_after_the_item_goes(belief, lines):
    """2026-10-23 review: the length is the setter's item's as it starts (Showdown's
    durationCallback): Knocked Off / Tricked away the next turn, a Light Clay Reflect has 6 turns
    left, not 3."""
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|upkeep|", "|turn|2", *lines, "|upkeep|", "|turn|3"], item="lightclay")  # fmt: skip
    assert state(b, belief).side_one.side_conditions.reflect == 8 - 2


def test_sleep_talk_runs_out_of_pp(belief):
    """2026-10-23 review: every move of a Sleep Talk user had at least 1 PP, Sleep Talk itself too
    (poke-env counts its uses, none of the moves it calls)."""
    talk = ["|move|p2a: Gholdengo|Sleep Talk|p2a: Gholdengo",
            "|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp|[from]move: Sleep Talk"]  # fmt: skip
    lines = ["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|turn|2", "|-status|p2a: Gholdengo|slp"]
    for t in range(16):  # 10 PP, 16 with PP Ups
        lines += [*talk, f"|turn|{3 + t}"]
    pp = {m.id: m.pp for m in state(battle(lines), belief).side_two.pokemon[0].moves}
    assert pp["sleeptalk"] == 0
    assert pp["makeitrain"] == 8 - 1  # (the calls cost none)


def test_must_recharge_searches_to_the_recharge_order(belief):
    import alpha_search

    from alpha_poke.agents.engine_state import engine_move_to_order

    b = battle(["|move|p1a: Garchomp|Hyper Beam|p2a: Gholdengo", "|-mustrecharge|p1a: Garchomp",
                "|turn|2"])  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Recharge", "id": "recharge"}],
                                 "trapped": True}],
                     "side": {"name": "us", "id": "p1", "pokemon": [
                         mon("p1: Garchomp", "Garchomp", ["earthquake", "reflect", "substitute",
                                                          "hyperbeam"], "leftovers", "roughskin",
                             True), mon("p1: Dondozo", "Dondozo", ["wavecrash"])]},
                     "rqid": 2})  # fmt: skip
    ours, *_ = alpha_search.ismcts([state(b, belief).to_string()], 50, iterations=64)
    player = type("P", (), {"create_order": staticmethod(lambda m, **k: m.id)})()
    assert [engine_move_to_order(player, b, c) for c, _, _ in ours] == ["recharge"]


def test_illusion_worlds(belief):
    b = Battle("battle-gen9ou-2", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    side = [mon("p1: Garchomp", "Garchomp", ["earthquake"], active=True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Earthquake", "id": "earthquake", "pp": 8,
                                            "maxpp": 8, "disabled": False}]}],
                     "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 1})  # fmt: skip
    for line in ["|poke|p2|Gholdengo, L100|", "|poke|p2|Zoroark-Hisui, L100|",
                 "|poke|p2|Great Tusk, L100|", "|switch|p1a: Garchomp|Garchomp|400/400",
                 "|switch|p2a: Gholdengo|Gholdengo|60/100", "|turn|1"]:  # fmt: skip
        b.parse_message(line.split("|"))
    ids = [build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(k)) for k in range(300)]
    act = [s.side_two.pokemon[int(s.side_two.active_index)] for s in ids]
    z = [p for p in act if p.id.startswith("zoroark")]
    assert 0.2 < len(z) / len(act) < 0.47  # one in three alive
    assert all(abs(p.hp / p.maxhp - 0.6) < 0.02 for p in z)


def test_recharge_ends_after_the_recharge_turn(belief):
    # poke-env keeps must_recharge until the next move: the turn after recharging is free
    b = battle(["|move|p2a: Gholdengo|Hyper Beam|p1a: Garchomp", "|-mustrecharge|p2a: Gholdengo",
                "|turn|2", "|cant|p2a: Gholdengo|recharge", "|turn|3"])  # fmt: skip
    assert b.opponent_active_pokemon.must_recharge  # (poke-env's stale flag)
    assert "mustrecharge" not in state(b, belief).side_two.volatile_statuses
    b = battle(["|move|p2a: Gholdengo|Hyper Beam|p1a: Garchomp", "|-mustrecharge|p2a: Gholdengo",
                "|turn|2"])  # fmt: skip
    assert "mustrecharge" in state(b, belief).side_two.volatile_statuses


def test_perish_count_is_the_latest(belief):
    b = battle(["|-start|p2a: Gholdengo|perish3", "|turn|2", "|-start|p2a: Gholdengo|perish2",
                "|turn|3"])  # fmt: skip
    vol = state(b, belief).side_two.volatile_statuses
    assert "perish2" in vol and "perish3" not in vol


@pytest.mark.parametrize("who, line, want", [
    ("one", "|-terastallize|p1a: Garchomp|Steel", ("dragon", "ground")),
    ("two", "|-terastallize|p2a: Gholdengo|Fire", ("steel", "ghost")),
])  # fmt: skip
def test_terastallized_keeps_original_types(belief, who, line, want):
    """The engine's types stay the original ones after Terastallization (its STAB on them,
    Showdown's getTypes(false, true)); the tera type is apart (has_type reads only it)."""
    b = battle([line, "|turn|2"])
    if who == "one":  # (the request after the turn -- the server sends it last -- shows it)
        g = mon("p1: Garchomp", "Garchomp", ["earthquake", "reflect", "substitute", "hyperbeam"],
                "leftovers", "roughskin", True) | {"teraType": "Steel", "terastallized": "Steel"}
        req = [{"move": m, "id": m, "pp": 8, "maxpp": 8, "disabled": False} for m in GARCHOMP]
        b.parse_request({"active": [{"moves": req}], "side": {"name": "us", "id": "p1",
                         "pokemon": [g, mon("p1: Dondozo", "Dondozo", ["wavecrash"])]}, "rqid": 2})  # fmt: skip
    s = state(b, belief)
    side = getattr(s, f"side_{who}")
    act = side.pokemon[int(side.active_index)]
    assert act.terastallized
    assert tuple(act.types) == want
    assert act.tera_type == line.rsplit("|", 1)[1].lower()


# 2026-10-22 review: Gravity / Magic Room are in the engine (its remaining turns, as Trick Room's)
# but were never passed in from a battle
@pytest.mark.parametrize("field,attr", [("Gravity", "gravity"), ("Magic Room", "magic_room")])
def test_gravity_and_magic_room(belief, field, attr):
    b = battle([f"|move|p1a: Garchomp|{field}|p1a: Garchomp", f"|-fieldstart|move: {field}",
                "|upkeep|", "|turn|2"])  # fmt: skip
    assert getattr(state(b, belief), attr) == 5 - 1
    assert getattr(state(battle(["|turn|2"]), belief), attr) == 0


def _pivoted(lines):
    """Our Garchomp's U-turn went first this turn; our switch request (the opponent's
    Gholdengo, Make It Rain seen on turn 1, still to move unless ``lines`` say otherwise)."""
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|upkeep|", "|turn|2", *lines],
               moves=("uturn", "earthquake", "swordsdance", "stealthrock"))  # fmt: skip
    side = [mon("p1: Garchomp", "Garchomp", ["uturn", "earthquake", "swordsdance", "stealthrock"],
                active=True), mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"forceSwitch": [True], "side": {"name": "us", "id": "p1", "pokemon": side},
                     "rqid": 2})  # fmt: skip
    return b


UTURN = ["|move|p1a: Garchomp|U-turn|p2a: Gholdengo", "|-damage|p2a: Gholdengo|80/100"]


# 2026-10-22 review: after our pivot the opponent's move is still to come -- the engine's saved
# move, drawn per world (it was none: the opponent did nothing, the switch-in took no hit)
def test_pivot_keeps_the_opponents_pending_move(belief):
    import poke_engine as pe

    b = _pivoted(UTURN)
    assert b.force_switch
    s = build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(0),
                    foe_pending={"makeitrain": 1.0})  # fmt: skip
    assert s.side_two.switch_out_move_second_saved_move.lower() == "makeitrain"
    # (uniform without weights: one of its usable moves)
    moves = {m.id.lower() for m in s.side_two.pokemon[0].moves if m.id.lower() != "none"}
    for k in range(5):
        u = build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(k))
        assert u.side_two.switch_out_move_second_saved_move.lower() in moves
    # the switch-in takes it
    opts = pe.options(s)
    assert opts[1] == ["makeitrain"], opts
    hit = [si for si in pe.generate_instructions(s, "dondozo", "makeitrain", -1, -1)
           if any("Damage SideOne" in str(i) for i in si.instruction_list)]  # fmt: skip
    assert hit


@pytest.mark.parametrize("lines", [
    ["|move|p2a: Gholdengo|Nasty Plot|p2a: Gholdengo", *UTURN],  # it moved first
    ["|switch|p2a: Kingambit|Kingambit|100/100", *[x.replace("Gholdengo", "Kingambit") for x in UTURN]],
])  # fmt: skip
def test_no_pending_move_once_the_opponent_acted(belief, lines):
    s = build_state(_pivoted(lines), belief, ("Garchomp", "Dondozo"), random.Random(0),
                    foe_pending={"makeitrain": 1.0})  # fmt: skip
    assert s.side_two.switch_out_move_second_saved_move.lower() == "none"


# 2026-10-22 review: a double KO's replacements are chosen by both sides at once (the engine's
# phase from both actives' HP); the server's switch request as the engine's force_switch made it
# ours first, the foe none -- the search let the foe pick after seeing ours
def test_double_ko_replacements_are_simultaneous(belief):
    import poke_engine as pe

    b = battle(["|switch|p2a: Kingambit|Kingambit|100/100", "|turn|2",
                "|switch|p2a: Gholdengo|Gholdengo|100/100", "|turn|3",
                "|move|p1a: Garchomp|Earthquake|p2a: Gholdengo", "|-damage|p2a: Gholdengo|0 fnt",
                "|faint|p2a: Gholdengo", "|-damage|p1a: Garchomp|0 fnt|[from] item: Rocky Helmet",
                "|faint|p1a: Garchomp"])  # fmt: skip
    side = [mon("p1: Garchomp", "Garchomp", ["earthquake"], active=True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    side[0]["condition"] = "0 fnt"
    b.parse_request({"forceSwitch": [True], "side": {"name": "us", "id": "p1", "pokemon": side},
                     "rqid": 2})  # fmt: skip
    s = state(b, belief)
    assert not s.side_one.force_switch
    ours, theirs = pe.options(s)
    assert ours == ["switch dondozo"] and theirs == ["switch kingambit"], (ours, theirs)


# 2026-10-22 review: the opponent's move still to come after our pivot is a legal one (the
# engine's: not a status move under Taunt) and no faster than our move that went first (a
# Protect would have come before our U-turn)
@pytest.mark.parametrize("extra,banned", [
    (["|-start|p2a: Gholdengo|move: Taunt"], {"nastyplot", "recover", "protect"}),
    ([], {"protect"}),
])  # fmt: skip
def test_pending_move_is_legal_and_not_faster(belief, extra, banned):
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp",
                "|move|p2a: Gholdengo|Nasty Plot|p2a: Gholdengo", "|upkeep|", "|turn|2",
                "|move|p2a: Gholdengo|Protect|p2a: Gholdengo", "|upkeep|", "|turn|3",
                "|move|p2a: Gholdengo|Recover|p2a: Gholdengo", "|upkeep|", "|turn|4", *extra,
                *UTURN], moves=("uturn", "earthquake", "swordsdance", "stealthrock"))  # fmt: skip
    side = [mon("p1: Garchomp", "Garchomp", ["uturn", "earthquake", "swordsdance", "stealthrock"],
                active=True), mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"forceSwitch": [True], "side": {"name": "us", "id": "p1", "pokemon": side},
                     "rqid": 2})  # fmt: skip
    seen = set()
    for k in range(40):
        s = build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(k),
                        foe_pending={"protect": 5.0, "nastyplot": 5.0, "makeitrain": 1.0})  # fmt: skip
        seen.add(s.side_two.switch_out_move_second_saved_move.lower())
    assert seen and not seen & banned, seen
    assert "makeitrain" in seen


# the fifth review: a waiting Struggle (no move left to use) stays the opponent's action after our
# pivot; at our move's priority, only if this world lets our move go first
def test_pending_moves_struggle_and_speed():
    import alpha_search
    import poke_engine as pe

    s = pe.State.from_string(open("tests/fixtures/engine_state_6v6.txt").readline().strip())
    parts = s.to_string().split("/")
    # every move of the opponent's active out of PP: it struggles
    mons = parts[1].split("=")
    a = int(s.side_two.active_index)
    f = mons[a].split(",")
    f = [(x.split(";")[0] + ";" + x.split(";")[1] + ";0") if x.count(";") == 2 else x for x in f]
    mons[a] = ",".join(f)
    parts[1] = "=".join(mons)
    out = alpha_search.pending_moves("/".join(parts), "uturn")
    assert out == ["struggle"], out
    # speeds 200 (ours) / 300 (theirs), Tackle (priority 0) and Avalanche (-4): our U-turn went
    # first, so not their Tackle (it would have come first) -- Avalanche; Tackle alone: the world
    # contradicts the order, by priority alone
    def world(moves):
        parts = s.to_string().split("/")
        for k, sp in ((0, 200), (1, 300)):
            mons = parts[k].split("=")
            a = int((s.side_one if k == 0 else s.side_two).active_index)
            f = mons[a].split(",")
            f[17] = str(sp)
            slots = [i for i, x in enumerate(f) if x.count(";") == 2]
            if k == 1:
                for i, mv in zip(slots, moves + ["NONE"] * 4):
                    f[i] = f"{mv};false;{0 if mv == 'NONE' else 16}"
            mons[a] = ",".join(f)
            parts[k] = "=".join(mons)
        return "/".join(parts)

    assert alpha_search.pending_moves(world(["TACKLE", "AVALANCHE"]), "uturn") == ["avalanche"]
    assert alpha_search.pending_moves(world(["TACKLE"]), "uturn") == ["tackle"]


SIDE_CONDITIONS = ("aurora_veil", "light_screen", "reflect", "safeguard", "mist", "tailwind",
                   "spikes", "stealth_rock", "sticky_web", "toxic_spikes", "toxic_count",
                   "protect")  # fmt: skip
DURATIONS = ("confusion", "encore", "healblock", "magnetrise", "partiallytrapped", "slowstart",
             "taunt", "throatchop", "yawn")  # fmt: skip


def _our_view(s):
    """Side one as both paths must agree on it: options by name (the move order differs: a
    replay's own moves are shuffled), conditions, field turns, volatiles, their durations;
    Disable's count and its move by name."""
    import alpha_search

    one = s.side_one
    mon = one.pokemon[int(one.active_index)]
    d = one.volatile_status_durations
    dis = (d.disable % 8, mon.moves[d.disable // 8].id) if "disable" in one.volatile_statuses else None
    return {
        "options": sorted(n for n in alpha_search.slot_names([s.to_string()])[0] if n),
        "conditions": {k: getattr(one.side_conditions, k) for k in SIDE_CONDITIONS},
        "field": (s.weather, s.weather_turns_remaining, s.terrain, s.terrain_turns_remaining),
        "volatiles": sorted(one.volatile_statuses),
        "durations": {k: getattr(d, k) for k in DURATIONS},
        "disable": dis,
        "pp": sorted((m.id, m.pp) for m in mon.moves),
    }


GARCHOMP = ("earthquake", "reflect", "substitute", "hyperbeam")


@pytest.mark.parametrize("lines,item,disabled", [
    (["|turn|2", "|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect", "|upkeep|",
      "|turn|3", "|move|p2a: Gholdengo|Knock Off|p1a: Garchomp",
      "|-enditem|p1a: Garchomp|Light Clay|[from] move: Knock Off|[of] p2a: Gholdengo", "|upkeep|", "|turn|4"],
     "lightclay", ()),
    (["|turn|2", *DISABLED_REFLECT], "leftovers", ("reflect",)),
    (["|turn|2", "|move|p1a: Garchomp|Substitute|p1a: Garchomp", "|-start|p1a: Garchomp|Substitute",
      "|move|p2a: Gholdengo|Taunt|p1a: Garchomp", "|-start|p1a: Garchomp|move: Taunt", "|upkeep|",
      "|turn|3"], "leftovers", ("reflect", "substitute")),
])  # fmt: skip
def test_live_and_replay_build_the_same_side(belief, lines, item, disabled):
    """2026-10-23 review (regression of the battle -> engine conversion): our side from the live
    root (the request) and from a replay of the same log (spectator: its known set) agree on the
    options, the durations and the volatiles (a Light Clay knocked off, a Disable, a Taunt)."""
    b = battle(lines, item=item)
    req = [{"move": m, "id": m, "pp": 8, "maxpp": 8, "disabled": m in disabled} for m in GARCHOMP]
    side = [mon("p1: Garchomp", "Garchomp", list(GARCHOMP), item, "roughskin", True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"active": [{"moves": req}], "side": {"name": "us", "id": "p1", "pokemon": side},
                     "rqid": 2})  # fmt: skip
    live = state(b, belief)
    spec = _spectator(b, item, "roughskin", GARCHOMP)
    replay = build_state(b, belief, ("Garchomp", "Dondozo"), random.Random(0), spectator=spec)
    lv, rv = _our_view(live), _our_view(replay)
    lv.pop("pp"), rv.pop("pp")  # (live: the request's 8 each; a replay: from the uses)
    assert lv == rv


IMPOSTER = ["|move|p2a: Gholdengo|Make It Rain|p1a: Ditto", "|-damage|p1a: Ditto|90/100", "|upkeep|",
            "|turn|2", "|move|p1a: Ditto|Transform|p2a: Gholdengo",
            "|-transform|p1a: Ditto|p2a: Gholdengo"]  # fmt: skip


def _ditto_battle(lines, copied=None):
    """Our Scarf Ditto (Transform its one move) transformed into Gholdengo; the request
    (live) offers ``copied`` (the copied moves, 5 PP) when given."""
    b = battle(lines, us="Ditto", item="choicescarf", ability="imposter", moves=("transform",))
    if copied:
        req = [{"move": m, "id": m, "pp": 5, "maxpp": 5, "disabled": False} for m in copied]
        # (Showdown's side request lists a transformed mon's copied moves too)
        side = [mon("p1: Ditto", "Ditto", list(copied), "choicescarf", "imposter", True),
                mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
        b.parse_request({"active": [{"moves": req}],
                         "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 2})  # fmt: skip
    return b


def _check_transformed(s, want_moves=None):
    one, two = s.side_one, s.side_two
    me, foe = one.pokemon[int(one.active_index)], two.pokemon[int(two.active_index)]
    assert me.id.lower() == "ditto"  # (its own species: the engine's transform keeps it)
    assert "transform" in one.volatile_statuses
    assert (me.attack, me.special_attack, me.speed) == (foe.attack, foe.special_attack, foe.speed)
    assert me.types == foe.types and me.ability == foe.ability
    stats, weight, own = me.transform_backup
    assert own[0] == ("transform", 15) and stats[0] != foe.attack, me.transform_backup  # (used once)
    assert weight == 40  # (Ditto's 4 kg: not its target's)
    if want_moves is not None:
        assert sorted(m.id for m in me.moves if m.id != "none") == sorted(want_moves)
    return me


def test_a_replays_transformed_active_is_transformed(belief):
    """2026-10-23 review: a replay's own Ditto (spectator) transformed into Kingambit kept its own
    stats and Transform, no transform volatile; the moves it used then joined its own set. Now
    the live root's transform, the target's set (this world's) with the moves it used."""
    lines = [*IMPOSTER, "|move|p1a: Ditto|Make It Rain|p2a: Gholdengo",
             "|-damage|p2a: Gholdengo|60/100", "|upkeep|", "|turn|3"]  # fmt: skip
    b = _ditto_battle(lines)
    spec = _spectator(b, "choicescarf", "imposter", ("transform",))
    s = build_state(b, belief, ("Ditto", "Dondozo"), random.Random(0), spectator=spec)
    me = _check_transformed(s)
    foe = s.side_two.pokemon[int(s.side_two.active_index)]
    assert "makeitrain" in [m.id for m in foe.moves]  # (the target's set has it)
    assert [m.pp for m in me.moves if m.id == "makeitrain"] == [4]  # (5, one used)


def test_a_transformed_active_switched_out_in_the_search_is_itself_again(belief):
    """2026-10-23 review: no transform_backup at the live root -- switched out in the search, the
    Ditto stayed a Gholdengo (its stats, a 5 PP Transform); Showdown: its own again."""
    import poke_engine as pe

    copied = ("makeitrain", "shadowball", "nastyplot", "recover")
    b = _ditto_battle([*IMPOSTER, "|upkeep|", "|turn|3"], copied)
    s = state(b, belief)
    me = _check_transformed(s, copied)
    own_atk = me.transform_backup[0][0]
    import alpha_search

    j = next(i for i, p in enumerate(s.side_one.pokemon) if p.id.lower() == "dondozo")
    for _, after, _ in alpha_search.chance_outcomes(s.to_string(), 8 + j, 0):
        d = next(p for p in pe.State.from_string(after).side_one.pokemon if p.id.lower() == "ditto")
        assert d.attack == own_atk and (d.moves[0].id.lower(), d.moves[0].pp) == ("transform", 15)


def test_an_opponents_copied_moves_keep_their_pp(belief):
    """2026-10-23 review: the opponent's transformed active's moves had 5 PP at every rebuild (a
    Scarf Ditto's fifth Protect, the next request Struggle only, the search 5 PP)."""
    lines = ["|switch|p2a: Ditto|Ditto|100/100", "|-transform|p2a: Ditto|p1a: Garchomp|[from] ability: Imposter",
             "|turn|2"]  # fmt: skip
    for t in range(5):
        lines += ["|move|p2a: Ditto|Earthquake|p1a: Garchomp", "|-damage|p1a: Garchomp|90/100",
                  f"|turn|{3 + t}"]  # fmt: skip
    s = state(battle(lines), belief)
    two = s.side_two
    foe = two.pokemon[int(two.active_index)]
    assert foe.id.lower() == "ditto" and "transform" in two.volatile_statuses
    assert {m.id: m.pp for m in foe.moves}["earthquake"] == 0


def _their_ditto(extra=()):
    """The opponent's Ditto transformed into our Garchomp (Rough Skin), then ``extra``."""
    return battle(["|switch|p2a: Ditto|Ditto|100/100",
                   "|-transform|p2a: Ditto|p1a: Garchomp|[from] ability: Imposter", "|turn|2",
                   *extra])  # fmt: skip


def test_a_transformed_mons_own_hp_stats_and_ability(belief):
    """2026-10-23 review: a transformed mon's HP and backup came from its target's base stats
    (poke-env's base_stats while transformed: a Ditto at 403 HP, Showdown 300; its backup's
    Attack 308, Showdown 132), and the copied ability was its base one too (Intimidate after the
    switch-out)."""
    s = state(_their_ditto(), belief)
    two = s.side_two
    d = two.pokemon[int(two.active_index)]
    assert d.maxhp <= 2 * 48 + 31 + 63 + 110  # (Ditto's 48 base HP at most; Garchomp's 108: 420)
    atk = d.transform_backup[0][0]
    assert atk <= 2 * 48 + 31 + 63 + 5 + 30, d.transform_backup  # (Ditto's 48 base Attack)
    assert d.ability == "roughskin" and d.base_ability == "imposter"


def test_a_traced_ability_is_not_the_base_one(belief):
    """2026-10-23 review: Trace's copied ability was the base one too (still on after a
    switch-out in the search); base: Trace."""
    b = battle(["|switch|p2a: Gardevoir|Gardevoir, F|100/100",
                "|-ability|p2a: Gardevoir|Rough Skin|[from] ability: Trace|[of] p1a: Garchomp",
                "|turn|2"])  # fmt: skip
    s = state(b, belief)
    g = s.side_two.pokemon[int(s.side_two.active_index)]
    assert (g.ability, g.base_ability) == ("roughskin", "trace")


def test_a_disabled_copied_move_is_disabled(belief):
    """2026-10-23 review: Disable on a copied move was left out (the move rebuilt usable)."""
    lines = ["|move|p2a: Ditto|Earthquake|p1a: Garchomp", "|-damage|p1a: Garchomp|80/100",
             "|move|p1a: Garchomp|Disable|p2a: Ditto", "|-start|p2a: Ditto|Disable|Earthquake",
             "|upkeep|", "|turn|3"]  # fmt: skip
    s = state(_their_ditto(lines), belief)
    two = s.side_two
    d = two.pokemon[int(two.active_index)]
    assert [m.disabled for m in d.moves if m.id == "earthquake"] == [True]
    assert "disable" in two.volatile_statuses


def test_a_copied_ability_does_not_follow_its_target_after(belief):
    """2026-10-23 review: the copied ability was the target's at every rebuild -- our Ditto copied
    an Ogerpon-Wellspring (Water Absorb), the Ogerpon terastallized after (Embody Aspect): both
    Embody Aspect in the search. The ability it copied stays."""
    lines = ["|switch|p2a: Ogerpon|Ogerpon-Wellspring, F|100/100", "|turn|2",
             "|move|p1a: Ditto|Transform|p2a: Ogerpon", "|-transform|p1a: Ditto|p2a: Ogerpon",
             "|upkeep|", "|turn|3", "|-terastallize|p2a: Ogerpon|Water",
             "|detailschange|p2a: Ogerpon|Ogerpon-Wellspring-Tera, F, tera:Water",
             "|-activate|p2a: Ogerpon|ability: Embody Aspect (Wellspring)",
             "|-boost|p2a: Ogerpon|spd|1",
             "|upkeep|", "|turn|4"]  # fmt: skip
    b = _ditto_battle(lines)
    spec = _spectator(b, "choicescarf", "imposter", ("transform",))
    for s in (build_state(b, belief, ("Ditto", "Dondozo"), random.Random(0), spectator=spec),):
        one, two = s.side_one, s.side_two
        me, foe = one.pokemon[int(one.active_index)], two.pokemon[int(two.active_index)]
        assert "transform" in one.volatile_statuses
        assert (me.ability, me.base_ability) == ("waterabsorb", "imposter"), foe.ability


LOG4 = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Ditto|
|poke|p1|Garchomp, M|
|poke|p2|Kingambit, M|
|poke|p2|Gholdengo|
|start
|switch|p1a: Ditto|Ditto|100/100
|switch|p2a: Kingambit|Kingambit, M|100/100
|-transform|p1a: Ditto|p2a: Kingambit|[from] ability: Imposter
|turn|1
|move|p1a: Ditto|Taunt|p2a: Kingambit
|-start|p2a: Kingambit|move: Taunt
|move|p2a: Kingambit|Swords Dance|p2a: Kingambit
|-fail|p2a: Kingambit
|upkeep
|turn|2
|move|p1a: Ditto|Kowtow Cleave|p2a: Kingambit
|-damage|p2a: Kingambit|60/100
|move|p2a: Kingambit|Kowtow Cleave|p1a: Ditto
|-damage|p1a: Ditto|60/100
|upkeep
|turn|3
|win|Bob
"""


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_first_choice_of_a_copied_move_is_a_position(belief, seed):
    """2026-10-23 review: a replay's Ditto choosing a copied move for the first time (Taunt, turn
    1) -- the move not yet in the log, the target's sampled set without it: the position was
    dropped. The player knows the copied moves from its transform on (its request): the game's
    moves it used transformed into that target are in the target's set."""
    from alpha_poke.train.positions import positions_from_replay

    ps = positions_from_replay({"id": "t4", "log": LOG4, "rating": None, "uploadtime": 0}, belief,
                               random.Random(seed), pool="all", per_game=99)  # fmt: skip
    mine = [p for p in ps if p.side == "p1" and p.kind == 0]
    assert sorted(p.turn for p in mine) == [1, 2], [(p.turn, p.kind) for p in ps]


def test_a_disable_the_engine_derives_is_no_flag(belief):
    """2026-10-23 (state-construction differential): the request's Assault Vest / Taunt / recharge
    disables were the moves' flags -- the engine never clears a flag it did not set (the vest
    knocked off, the status move still out). derived_disable, shared with the differential."""
    from alpha_poke.agents.engine_state import derived_disable

    kw = dict(taunt=False, healblock=False, throatchop=False, item="", last_move="")
    assert derived_disable("reflect", **(kw | {"item": "assaultvest"}))
    assert derived_disable("reflect", **(kw | {"taunt": True}))
    assert not derived_disable("earthquake", **(kw | {"taunt": True}))
    assert derived_disable("earthquake", **kw, recharge=True)
    assert derived_disable("earthquake", **kw, charging="meteorbeam")
    assert not derived_disable("earthquake", **kw, charging="meteorbeam", lock="meteorbeam")
    req = [{"move": m, "id": m, "pp": 8, "maxpp": 8, "disabled": m == "reflect"} for m in GARCHOMP]
    b = battle(["|move|p2a: Gholdengo|Taunt|p1a: Garchomp", "|-start|p1a: Garchomp|move: Taunt",
                "|upkeep|", "|turn|2"])  # fmt: skip
    side = [mon("p1: Garchomp", "Garchomp", list(GARCHOMP), "leftovers", "roughskin", True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"active": [{"moves": req}], "side": {"name": "us", "id": "p1", "pokemon": side},
                     "rqid": 2})  # fmt: skip
    s = state(b, belief)
    assert not any(m.disabled for m in s.side_one.pokemon[0].moves)
    assert "taunt" in s.side_one.volatile_statuses


def test_a_charging_and_a_locked_active(belief):
    """A two-turn move's second turn: its volatile; an Outrage lock: lockedmove, the other moves
    disabled (the differential's states' convention)."""
    b = battle(["|move|p2a: Gholdengo|Meteor Beam||[still]", "|-prepare|p2a: Gholdengo|Meteor Beam",
                "|upkeep|", "|turn|2"])  # fmt: skip
    assert "meteorbeam" in state(b, belief).side_two.volatile_statuses
    b = battle(["|move|p2a: Gholdengo|Outrage|p1a: Garchomp", "|-damage|p1a: Garchomp|60/100",
                "|upkeep|", "|turn|2"])  # fmt: skip
    two = state(b, belief).side_two
    assert "lockedmove" in two.volatile_statuses
    assert all(m.disabled for m in two.pokemon[0].moves if m.id not in ("outrage", "none"))


def test_a_benched_regenerator_healed(belief):
    """A benched mon seen before whose world's ability is Regenerator: a third back (silent in
    the log; poke-env adds it only when it knew the ability)."""
    from alpha_poke.agents import engine_state as es

    b = battle(["|move|p1a: Garchomp|Earthquake|p2a: Gholdengo", "|-damage|p2a: Gholdengo|30/100",
                "|upkeep|", "|turn|2", "|switch|p2a: Slowking|Slowking-Galar, M|100/100", "|upkeep|",
                "|turn|3"])  # fmt: skip
    inner = es.sample_set

    def regen(*a, **kw):
        s = inner(*a, **kw)
        return es.SampledSet(s.moves, s.item, "regenerator", s.tera, s.stats)

    es.sample_set = regen
    try:
        s = state(b, belief)
    finally:
        es.sample_set = inner
    g = next(p for p in s.side_two.pokemon if p.id.lower() == "gholdengo")
    assert abs(g.hp / g.maxhp - (0.30 + 1 / 3)) < 0.02


def test_formes_and_more_volatiles_reach_the_engine(belief):
    """2026-10-23 (state-construction differential): a forme's species (poke-env keeps the one it
    came in as: Ogerpon's tera forme), a Battle Bond Greninja (the engine's Battle Bond works for
    Greninja-Bond only), Destiny Bond, a Struggle's mark, Protean from the log."""
    b = battle(["|switch|p2a: Ogerpon|Ogerpon-Wellspring, F|100/100", "|-terastallize|p2a: Ogerpon|Water",
                "|detailschange|p2a: Ogerpon|Ogerpon-Wellspring-Tera, F, tera:Water",
                "|move|p2a: Ogerpon|Destiny Bond|p2a: Ogerpon", "|-singlemove|p2a: Ogerpon|Destiny Bond",
                "|upkeep|", "|turn|2"])  # fmt: skip
    two = state(b, belief).side_two
    assert two.pokemon[int(two.active_index)].id.lower() == "ogerponwellspringtera"
    assert "destinybond" in two.volatile_statuses
    b = battle(["|move|p1a: Garchomp|Struggle|p2a: Gholdengo", "|-damage|p2a: Gholdengo|90/100",
                "|upkeep|", "|turn|2"], us="Greninja", ability="battlebond",
               moves=("watershuriken", "darkpulse", "icebeam", "uturn"))  # fmt: skip
    one = state(b, belief).side_one
    assert one.pokemon[0].id.lower() == "greninjabond"
    b = battle(["|move|p2a: Gholdengo|Shadow Ball|p1a: Garchomp",
                "|-start|p2a: Gholdengo|typechange|Ghost|[from] ability: Protean", "|upkeep|", "|turn|2"])  # fmt: skip
    assert "protean" in state(b, belief).side_two.volatile_statuses


def test_out_of_pp_and_encore_flags(belief):
    """Out of PP: the engine's own (no option), no flag; under Encore the others keep their flags
    (a charge's derived rule does not drop them)."""
    from alpha_poke.agents.engine_state import derived_disable

    kw = dict(taunt=False, healblock=False, throatchop=False, item="", last_move="")
    assert derived_disable("recover", **kw, pp=0)
    assert not derived_disable("bodypress", **kw, charging="meteorbeam", encore=True)


def test_a_saved_move_with_the_sides_optional_fields():
    """2026-10-23 (state-construction differential, a million decisions): the foe's waiting move
    was written as the sixth field from the end of its side's string -- with the optional trailing
    ones (tera_used, future_doom) present it went into a bool field and the engine panicked."""
    import poke_engine as pe

    from alpha_poke.agents.engine_state import _with_saved_move

    s2 = pe.Side(pokemon=[pe.Pokemon(id="gholdengo", hp=300, maxhp=300, moves=[pe.Move(id="shadowball", pp=8)])],
                 tera_used=True, future_sight=(2, pe.PokemonIndex("0")), future_doom=True)  # fmt: skip
    st = pe.State(side_one=pe.Side(pokemon=[pe.Pokemon(id="garchomp", hp=300, maxhp=300)]), side_two=s2)
    out = _with_saved_move(st, "shadowball")
    assert out.side_two.switch_out_move_second_saved_move.lower() == "shadowball"
    assert out.side_two.tera_used


def test_transformed_into_an_ogerpon_cannot_terastallize(belief):
    """S62 (2026-10-23, state-construction differential): a Ditto transformed into an Ogerpon /
    Terapagos has no Terastallization -- the engine's notera (L227) was left out."""
    b = battle(["|switch|p2a: Ditto|Ditto|100/100",
                "|-transform|p2a: Ditto|p1a: Ogerpon|[from] ability: Imposter", "|turn|2"],
               us="Ogerpon", ability="defiant", moves=("ivycudgel", "uturn", "hornleech", "spikes"))  # fmt: skip
    s = build_state(b, belief, ("Ogerpon", "Dondozo"), random.Random(0))
    assert {"transform", "notera"} <= {str(v).lower() for v in s.side_two.volatile_statuses}
    assert "notera" not in {str(v).lower() for v in state(_their_ditto_garchomp(), belief).side_two.volatile_statuses}


def _their_ditto_garchomp():
    return battle(["|switch|p2a: Ditto|Ditto|100/100",
                   "|-transform|p2a: Ditto|p1a: Garchomp|[from] ability: Imposter", "|turn|2"])  # fmt: skip


def test_a_struggling_choice_lock_keeps_its_flags_under_a_taunt(belief):
    """S70 (2026-10-23, state-construction differential): our Scarf Landorus locked into a move
    out of PP, Taunted, a Struggle: the lock's move from poke-env's last used one was lost -- the
    Taunt then derived Reflect's flag (no flag: usable once the Taunt ends). The lock's flags."""
    moves = ("earthquake", "reflect", "substitute", "hyperbeam")
    b = battle(["|move|p1a: Garchomp|Earthquake|p2a: Gholdengo", "|-damage|p2a: Gholdengo|80/100",
                "|move|p2a: Gholdengo|Taunt|p1a: Garchomp", "|-start|p1a: Garchomp|move: Taunt",
                "|upkeep", "|turn|2", "|-activate|p1a: Garchomp|move: Struggle",
                "|move|p1a: Garchomp|Struggle|p2a: Gholdengo", "|-damage|p2a: Gholdengo|70/100",
                "|upkeep", "|turn|3"], item="choicescarf", moves=moves)  # fmt: skip
    side = [mon("p1: Garchomp", "Garchomp", list(moves), "choicescarf", "roughskin", True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Struggle", "id": "struggle", "pp": 1, "maxpp": 1,
                                            "disabled": False}]}],
                     "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 3})  # fmt: skip
    flags = {m.id: m.disabled for m in state(b, belief).side_one.pokemon[0].moves}
    assert flags["reflect"] and flags["substitute"] and flags["hyperbeam"], flags  # (its locked move: PP)


def test_a_transformed_mons_copied_protean(belief):
    """S79 (2026-10-23, state-construction differential): a Ditto transformed into a Protean mon,
    its type changed by the copied Protean (the log's -start typechange): the engine's protean
    volatile (L218) -- left out for every transformed mon."""
    b = battle(["|switch|p2a: Ditto|Ditto|100/100",
                "|-transform|p2a: Ditto|p1a: Greninja|[from] ability: Imposter", "|turn|2",
                "|move|p2a: Ditto|Ice Beam|p1a: Greninja", "|-start|p2a: Ditto|typechange|Ice|[from] ability: Protean",
                "|-damage|p1a: Greninja|300/400", "|upkeep", "|turn|3"],
               us="Greninja", ability="protean", moves=("icebeam", "uturn", "gunkshot", "darkpulse"))  # fmt: skip
    s = build_state(b, belief, ("Greninja", "Dondozo"), random.Random(0))
    assert {"transform", "protean"} <= {str(v).lower() for v in s.side_two.volatile_statuses}
    assert "protean" not in {str(v).lower() for v in state(_their_ditto_garchomp(), belief).side_two.volatile_statuses}


def test_an_added_type_is_a_type_change(belief):
    """S80 (2026-10-23, state-construction differential): Forest's Curse's added Grass type --
    Showdown's types have it: the engine's typechange volatile (its switch-out ends it)."""
    b = battle(["|move|p1a: Garchomp|Forest's Curse|p2a: Gholdengo",
                "|-start|p2a: Gholdengo|typeadd|Grass|[from] move: Forest's Curse", "|upkeep", "|turn|2"])  # fmt: skip
    assert "typechange" in {str(v).lower() for v in state(b, belief).side_two.volatile_statuses}


def test_our_disguised_zoroarks_used_item_is_its_own(belief):
    """S88 (2026-10-23, state-construction differential): our lead Zoroark disguised as
    Ceruledge used up its Throat Spray -- the timers kept it as the disguise's last item."""
    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Ceruledge|Ceruledge, F|251/251", "|switch|p2a: Gholdengo|Gholdengo|100/100",
                 "|turn|1", "|move|p1a: Ceruledge|Hyper Voice|p2a: Gholdengo", "|-damage|p2a: Gholdengo|80/100",
                 "|-enditem|p1a: Ceruledge|Throat Spray", "|-boost|p1a: Ceruledge|spa|1|[from] item: Throat Spray",
                 "|upkeep", "|turn|2"]:  # fmt: skip
        b.parse_message(line.split("|"))
    side = [{**mon("p1: Zoroark", "Zoroark-Hisui", ["hypervoice"], "", "illusion", True), "condition": "251/251"},
            {**mon("p1: Ceruledge", "Ceruledge", ["bitterblade"], "leftovers", "flashfire"), "condition": "291/291"}]  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Hyper Voice", "id": "hypervoice", "pp": 15, "maxpp": 16,
                                            "disabled": False}]}],
                     "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 2})  # fmt: skip
    s = build_state(b, belief, ("Zoroark-Hisui", "Ceruledge"), random.Random(0))
    last = {str(m.id).lower(): str(m.last_item).lower() for m in s.side_one.pokemon if str(m.id).lower() != "none"}
    assert last.get("zoroarkhisui") == "throatspray" and last.get("ceruledge") in (None, "none"), last


def test_a_formes_type_change_after_terastallizing(belief):
    """S98 (2026-10-23, state-construction differential): Meloetta terastallized, then Relic Song's
    Pirouette forme -- Showdown's formeChange sets its pre-tera types: the engine's typechange
    (left out: a terastallized mon's type change counted as none)."""
    b = battle(["|switch|p2a: Meloetta|Meloetta|100/100", "|turn|2", "|-terastallize|p2a: Meloetta|Dark",
                "|move|p2a: Meloetta|Relic Song|p1a: Garchomp", "|-damage|p1a: Garchomp|300/400",
                "|-formechange|p2a: Meloetta|Meloetta-Pirouette|[msg]", "|upkeep", "|turn|3"])  # fmt: skip
    assert "typechange" in {str(v).lower() for v in state(b, belief).side_two.volatile_statuses}


def test_an_imprisoning_foes_shared_moves_are_disabled(belief):
    """S103 (2026-10-23, state-construction differential): the foe's Imprison, then its Transform
    into our active -- it knows all our moves: Showdown disables them (our request says only
    maybeDisabled); they were usable."""
    b = battle(["|move|p2a: Gholdengo|Imprison|p2a: Gholdengo", "|-start|p2a: Gholdengo|move: Imprison",
                "|upkeep", "|turn|2", "|move|p2a: Gholdengo|Transform|p1a: Garchomp",
                "|-transform|p2a: Gholdengo|p1a: Garchomp", "|upkeep", "|turn|3"])  # fmt: skip
    flags = {m.id: m.disabled for m in state(b, belief).side_one.pokemon[0].moves}
    assert all(flags.values()), flags


def test_a_disabled_locked_move_and_power_trick(belief):
    """S101: Cursed Body's Disable on our locked Outrage -- its request still lists it, Showdown's
    slot is disabled: the flag. S111: Power Trick -- the volatile, Attack and Defense swapped (the
    request's stats are the unswapped ones)."""
    moves = ("outrage", "earthquake", "swordsdance", "fireblast")
    b = battle(["|move|p1a: Garchomp|Outrage|p2a: Gholdengo", "|-damage|p2a: Gholdengo|60/100",
                "|-start|p1a: Garchomp|Disable|Outrage|[from] ability: Cursed Body|[of] p2a: Gholdengo",
                "|upkeep", "|turn|2"], moves=moves)  # fmt: skip
    side = [mon("p1: Garchomp", "Garchomp", list(moves), "leftovers", "roughskin", True),
            mon("p1: Dondozo", "Dondozo", ["wavecrash"])]  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Outrage", "id": "outrage"}]}],
                     "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 2})  # fmt: skip
    flags = {m.id: m.disabled for m in state(b, belief).side_one.pokemon[0].moves}
    assert flags["outrage"], flags
    b = battle(["|move|p1a: Garchomp|Power Trick|p1a: Garchomp", "|-start|p1a: Garchomp|Power Trick",
                "|upkeep", "|turn|2"])  # fmt: skip
    s = state(b, belief)
    assert "powertrick" in {str(v).lower() for v in s.side_one.volatile_statuses}
    their = battle(["|move|p2a: Gholdengo|Power Trick|p2a: Gholdengo", "|-start|p2a: Gholdengo|Power Trick",
                    "|upkeep", "|turn|2"])  # fmt: skip
    plain = battle(["|move|p2a: Gholdengo|Power Trick|p2a: Gholdengo", "|upkeep", "|turn|2"])  # (the same set)
    plain, tricked = state(plain, belief).side_two.pokemon[0], state(their, belief).side_two.pokemon[0]
    assert (tricked.attack, tricked.defense) == (plain.defense, plain.attack)


def test_our_disguised_zoroarks_sleep_is_its_own(belief):
    """S110: our Zoroark disguised as Ceruledge put to sleep -- the timers counted it as the
    disguise's sleep: the Zoroark's (the request: it is asleep, the Ceruledge not)."""
    b = Battle("battle-gen9ou-1", "us", logging.getLogger("t"), gen=9)
    b.player_role = "p1"
    for line in ["|switch|p1a: Ceruledge|Ceruledge, F|251/251", "|switch|p2a: Darkrai|Darkrai|100/100",
                 "|turn|1", "|move|p2a: Darkrai|Hypnosis|p1a: Ceruledge", "|-status|p1a: Ceruledge|slp|[from] move: Hypnosis",
                 "|upkeep", "|turn|2", "|cant|p1a: Ceruledge|slp", "|upkeep", "|turn|3"]:  # fmt: skip
        b.parse_message(line.split("|"))
    side = [{**mon("p1: Zoroark", "Zoroark-Hisui", ["hypervoice"], "", "illusion", True), "condition": "251/251 slp"},
            {**mon("p1: Ceruledge", "Ceruledge", ["bitterblade"], "leftovers", "flashfire"), "condition": "291/291"}]  # fmt: skip
    b.parse_request({"active": [{"moves": [{"move": "Hyper Voice", "id": "hypervoice", "pp": 16, "maxpp": 16,
                                            "disabled": False}]}],
                     "side": {"name": "us", "id": "p1", "pokemon": side}, "rqid": 3})  # fmt: skip
    s = build_state(b, belief, ("Zoroark-Hisui", "Ceruledge"), random.Random(0))
    z = next(m for m in s.side_one.pokemon if str(m.id).lower() == "zoroarkhisui")
    assert z.sleep_turns == 1, (z.sleep_turns, z.rest_turns)


def test_as_one_and_a_type_change_after_terastallizing(belief):
    """S121: As One announces itself and Unnerve -- poke-env's temporary ability the last one: the
    set's As One (a Ditto's copied one too). S122: a type change after terastallizing (Double
    Shock's message) did nothing -- not a forme's."""
    from types import SimpleNamespace

    from alpha_poke.agents.pokeview import engine_ability as _current_ability

    assert _current_ability(SimpleNamespace(temporary_ability="Unnerve"), "asoneglastrier") == "asoneglastrier"
    assert _current_ability(SimpleNamespace(temporary_ability="Simple"), "asoneglastrier") == "simple"
    b = battle(["|-terastallize|p2a: Gholdengo|Steel", "|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp",
                "|-damage|p1a: Garchomp|300/400", "|-start|p2a: Gholdengo|typechange|Steel|[from] move: Double Shock",
                "|upkeep", "|turn|2"])  # fmt: skip
    assert "typechange" not in {str(v).lower() for v in state(b, belief).side_two.volatile_statuses}


def test_the_sixth_runs_construction_facts(belief):
    """S124: a forme change sets its types -- a Soak before it gone (poke-env kept the typechange).
    S131: Spite's / Eerie Spell's PP of a transformed foe's copied move."""
    b = battle(["|switch|p2a: Palafin|Palafin, F|100/100", "|turn|2",
                "|move|p1a: Garchomp|Soak|p2a: Palafin", "|-start|p2a: Palafin|typechange|Water",
                "|detailschange|p2a: Palafin|Palafin-Hero, F", "|upkeep", "|turn|3"])  # fmt: skip
    assert "typechange" not in {str(v).lower() for v in state(b, belief).side_two.volatile_statuses}
    b = battle(["|switch|p2a: Ditto|Ditto|100/100", "|-transform|p2a: Ditto|p1a: Garchomp|[from] ability: Imposter",
                "|turn|2", "|move|p2a: Ditto|Earthquake|p1a: Garchomp", "|-damage|p1a: Garchomp|300/400",
                "|move|p1a: Garchomp|Spite|p2a: Ditto", "|-activate|p2a: Ditto|move: Spite|Earthquake|4",
                "|upkeep", "|turn|3"])  # fmt: skip
    two = state(b, belief).side_two
    assert {m.id: m.pp for m in two.pokemon[int(two.active_index)].moves}["earthquake"] == 0


def test_a_type_change_to_its_own_types_is_none(belief):
    """S137: a Libero into its own type (a Ghost's Poltergeist) -- Showdown's types unchanged: no
    typechange (poke-env's effect stayed)."""
    b = battle(["|move|p2a: Gholdengo|Make It Rain|p1a: Garchomp", "|-start|p2a: Gholdengo|typechange|Steel/Ghost|[from] ability: Libero",
                "|-damage|p1a: Garchomp|300/400", "|upkeep", "|turn|2"])  # fmt: skip
    assert "typechange" not in {str(v).lower() for v in state(b, belief).side_two.volatile_statuses}


def test_a_transformed_foes_last_item(belief):
    """S138: a transformed Ditto's Focus Sash used up -- its last item was dropped as the engine's
    transformed mon was rebuilt."""
    b = battle(["|switch|p2a: Ditto|Ditto|100/100", "|-transform|p2a: Ditto|p1a: Garchomp|[from] ability: Imposter",
                "|turn|2", "|move|p1a: Garchomp|Earthquake|p2a: Ditto", "|-enditem|p2a: Ditto|Focus Sash",
                "|-damage|p2a: Ditto|1/100", "|upkeep", "|turn|3"])  # fmt: skip
    two = state(b, belief).side_two
    assert str(two.pokemon[int(two.active_index)].last_item).lower() == "focussash"


def test_a_copied_ability_poke_env_never_knew():
    """S144: a replay's transformed mon -- poke-env never knew its target's ability, kept the
    Imposter it came by: the target's in this world."""
    from types import SimpleNamespace

    from alpha_poke.agents.pokeview import copied_ability as _copied_ability

    assert _copied_ability(SimpleNamespace(temporary_ability="Imposter"), "magicguard") == "magicguard"
    assert _copied_ability(SimpleNamespace(temporary_ability="Rough Skin"), "magicguard") == "roughskin"


def test_a_klutz_setters_weather_is_not_extended_after_its_ability_changed(belief):
    """2026-10-24 review: a Klutz Golurk with a Heat Rock sets the sun (5 turns: Klutz keeps the
    rock out), a Skill Swap makes it Regenerator the same turn -- the setter's ability now was
    read: 8 turns (7 left), Showdown's 4. The ability it had as it set it counts."""
    moves = ("sunnyday", "earthquake", "poltergeist", "rockpolish")
    lines = ["|move|p1a: Golurk|Sunny Day|p1a: Golurk", "|-weather|SunnyDay",
             "|move|p2a: Gholdengo|Skill Swap|p1a: Golurk",
             "|-activate|p2a: Gholdengo|move: Skill Swap|Klutz|Regenerator|[of] p1a: Golurk",
             "|upkeep|", "|turn|2"]
    b = battle(lines, us="Golurk", item="heatrock", ability="klutz", moves=moves)
    assert state(b, belief).weather_turns_remaining == 5 - 1
    # (and the other way: a Klutz it got before setting keeps the rock out too)
    lines = ["|move|p2a: Gholdengo|Skill Swap|p1a: Golurk",
             "|-activate|p2a: Gholdengo|move: Skill Swap|Regenerator|Klutz|[of] p1a: Golurk",
             "|move|p1a: Golurk|Sunny Day|p1a: Golurk", "|-weather|SunnyDay", "|upkeep|", "|turn|2"]
    b = battle(lines, us="Golurk", item="heatrock", ability="regenerator", moves=moves)
    assert state(b, belief).weather_turns_remaining == 5 - 1
