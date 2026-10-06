"""Search-player helpers: oracle sets (D11 B upper bound) and plan-prior option keys (D11 A1)."""

from types import SimpleNamespace

from poke_env.player.battle_order import SingleBattleOrder

from alpha_poke.agents.engine_state import _oracle_set, oracle_sets
from alpha_poke.agents.search_player import _option_key, _order_key

TEAM = """Cinderace @ Heavy-Duty Boots
Ability: Libero
Tera Type: Fire
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Pyro Ball
- U-turn

Landorus-Therian @ Rocky Helmet
Ability: Intimidate
- Earthquake
"""


def _mon(species, item="unknown_item", ability=None, tera=False):
    return SimpleNamespace(
        species=species,
        item=item,
        ability=ability,
        is_terastallized=tera,
        tera_type=None,
        level=100,
        base_stats={"hp": 80, "atk": 116, "def": 75, "spa": 65, "spd": 75, "spe": 119},
    )


def test_oracle_sets_parse():
    o = oracle_sets(TEAM)
    assert sorted(o) == ["cinderace", "landorustherian"]
    c = o["cinderace"]
    assert c.moves == ["pyroball", "uturn"] and c.item == "heavydutyboots"
    assert c.tera == "fire" and c.spread.nature == "jolly"
    assert c.spread.evs == (0, 252, 0, 0, 4, 252)
    assert o["landorustherian"].spread.evs == (0,) * 6  # no EVs line


def test_oracle_set_keeps_battle_knowledge():
    o = oracle_sets(TEAM)
    s = _oracle_set(_mon("cinderace"), o)
    assert s.item == "heavydutyboots" and s.ability == "libero"
    assert s.stats["spe"] == 370  # 119 base, 252 EVs, Jolly
    s = _oracle_set(_mon("cinderace", item=""), o)  # knocked off
    assert s.item == "none"
    assert _oracle_set(_mon("greattusk"), o) is None  # not in the team: caller samples


def test_option_and_order_keys_match():
    move = SimpleNamespace(id="earthquake")
    mon = SimpleNamespace(species="greattusk")
    assert _option_key((move, True)) == ("move", "earthquake", True)
    assert _option_key(mon) == ("switch", "greattusk")
    order = SingleBattleOrder(move, terastallize=True)
    assert _order_key(order) == _option_key((move, True))


# ---- Encore: the engine panics on Encore without a last used move (hung games, 2026-10-05)


def _engine_mon(species, moves):
    import poke_engine as pe

    t = ("normal", "typeless")
    return pe.Pokemon(id=species, level=100, types=t, base_types=t, hp=300, maxhp=300,
                      ability="none", base_ability="none", item="none", attack=200, defense=200,
                      special_attack=200, special_defense=200, speed=200, status="none",
                      weight_kg=50.0, moves=[pe.Move(id=m, pp=16) for m in moves],
                      terastallized=False, tera_type="normal")  # fmt: skip


def _encore_state(last_kw):
    import poke_engine as pe

    def side(mons, vol, kw):
        return pe.Side(pokemon=(mons + [pe.Pokemon.create_fainted()] * 6)[:6],
                       active_index=pe.PokemonIndex("0"), side_conditions=pe.SideConditions(),
                       volatile_statuses=vol, **kw)  # fmt: skip

    s1 = side([_engine_mon("dragonite", ["roost", "dragondance", "extremespeed"])], *last_kw)
    s2 = side([_engine_mon("ogerpon", ["knockoff", "encore"])], set(), {})
    return pe.State(side_one=s1, side_two=s2, weather=pe.Weather("none"),
                    weather_turns_remaining=0, terrain=pe.Terrain("none"),
                    terrain_turns_remaining=0, trick_room=False,
                    trick_room_turns_remaining=0)  # fmt: skip


def _poke_env_mon(last=None, encored=False):
    from poke_env.battle import Effect

    moves = {
        m: SimpleNamespace(is_last_used=m == last) for m in ("roost", "dragondance", "extremespeed")
    }
    return SimpleNamespace(moves=moves, effects={Effect.ENCORE: 1} if encored else {})


def test_engine_panic_becomes_runtime_error():
    import pytest

    from alpha_poke.agents import mcts_worker

    with pytest.raises(RuntimeError, match="poke-engine"):
        mcts_worker.search(_encore_state(({"encore"}, {})), 50)


def test_last_move_sets_encore_move_or_drops_encore():
    from alpha_poke.agents import mcts_worker
    from alpha_poke.agents.engine_state import _last_move

    em = _engine_mon("dragonite", ["roost", "dragondance", "extremespeed"])
    kw, vol = _last_move(_poke_env_mon("dragondance", encored=True), em)
    assert kw == {"last_used_move": "move:1"} and "encore" in vol
    visits, n = mcts_worker.search(_encore_state((vol, kw)), 50)
    assert n > 0 and {c for c, _ in visits} <= {"dragondance", "dragondance-tera"}
    # encored, poke-env lost the last move, but the request offers only the encored move
    kw, vol = _last_move(_poke_env_mon(encored=True), em, avail={"extremespeed"})
    assert kw == {"last_used_move": "move:2"}
    # unknown: drop Encore rather than build a state the engine panics on
    kw, vol = _last_move(_poke_env_mon(encored=True), em)
    assert kw == {} and "encore" not in vol


def test_unrevealed_opponent_mon_is_at_full_hp():

    from poke_env.battle import Pokemon

    from alpha_poke.agents.engine_state import SampledSet, _their_mon

    stats = {"hp": 391, "atk": 200, "def": 200, "spa": 300, "spd": 200, "spe": 250}
    s = SampledSet(["icebeam"], "leftovers", "pressure", "ground", stats)
    preview = Pokemon(details="Kyurem", gen=9)  # team preview only: HP fraction reads 0
    assert _their_mon(preview, s).hp == 391
    seen = Pokemon(details="Kyurem", gen=9)
    seen.set_hp_status("50/100")
    assert _their_mon(seen, s).hp == round(0.5 * 391)
