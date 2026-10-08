"""Search-player helpers: engine states built from battles."""

from types import SimpleNamespace

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


def test_last_move_sets_encore_move_or_drops_encore():
    import alpha_search

    from alpha_poke.agents.engine_state import _last_move

    em = _engine_mon("dragonite", ["roost", "dragondance", "extremespeed"])
    kw, vol = _last_move(_poke_env_mon("dragondance", encored=True), em)
    assert kw == {"last_used_move": "move:1"} and "encore" in vol
    ours, n, _, _ = alpha_search.ismcts([_encore_state((vol, kw)).to_string()], 50)
    assert n > 0 and {c for c, v, _ in ours if v} <= {"dragondance", "dragondance-tera"}
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
