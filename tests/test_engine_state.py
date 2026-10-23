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
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|turn|2"], item="lightclay")  # fmt: skip
    assert state(b, belief).side_one.side_conditions.reflect == 8 - 1
    b = battle(["|move|p1a: Garchomp|Reflect|p1a: Garchomp", "|-sidestart|p1: us|Reflect",
                "|turn|2"])  # fmt: skip
    assert state(b, belief).side_one.side_conditions.reflect == 5 - 1


def test_heat_rock_drought(belief):
    # set during turn 1, one end of turn since (the timers count the ends of turn:
    # doc/engine-diff.md L3; a real log has an "|upkeep|" at every end of turn)
    b = battle(["|-weather|SunnyDay|[from] ability: Drought|[of] p1a: Torkoal", "|upkeep|",
                "|turn|2"], us="Torkoal", item="heatrock", ability="drought",
               moves=("lavaplume", "rapidspin", "yawn", "stealthrock"))  # fmt: skip
    assert state(b, belief).weather_turns_remaining == 8 - 1


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
    s = state(battle([line, "|turn|2"]), belief)
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
