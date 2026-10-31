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

    # its first turn out, its action stopped (cant: frozen) before a mid-turn decision: poke-env's
    # first_turn stays, the timers' count does not -- no switch-in last move (2026-10-23, S56)
    from alpha_poke.agents.timers import SideTimers

    mon = _poke_env_mon()
    mon.first_turn = True
    tm = SideTimers()
    tm.fresh = 0
    assert _last_move(mon, em, index=0, tm=tm)[0] == {}
    tm.fresh = 2
    assert _last_move(mon, em, index=0, tm=tm)[0] == {"last_used_move": "switch:0"}
    # a transformed Ditto's Transform: poke-env has its target's moves only, the engine's last
    # used move is Transform's slot in its backup (L187; 2026-10-23, S58)
    import poke_engine as pe

    t = ("normal", "typeless")
    ditto = pe.Pokemon(id="ditto", level=100, types=t, base_types=t, hp=300, maxhp=300,
                       ability="none", base_ability="none", item="none", attack=200, defense=200,
                       special_attack=200, special_defense=200, speed=200, status="none",
                       weight_kg=50.0, moves=[pe.Move(id=m, pp=5) for m in ("roost", "dragondance")],
                       terastallized=False, tera_type="normal",
                       transform_backup=([1] * 5, 40, [("transform", 15)] + [("none", 0)] * 3))  # fmt: skip
    tm = SideTimers()
    tm.own_last = "transform"
    assert _last_move(_poke_env_mon(), ditto, index=0, tm=tm)[0] == {"last_used_move": "move:0"}


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


def test_the_search_reports_the_opponents_root_options():
    """opponent=True (game reviews, 2026-10-30): the opponent's root options as the search saw
    them -- (name, visits, our value when it takes it), named in the first world that has each
    (its moves differ between worlds); without it the result stays four items."""
    import alpha_search
    import poke_engine as pe

    def world(their_moves):
        s = _encore_state((set(), {}))
        s2 = pe.Side(pokemon=([_engine_mon("ogerpon", their_moves)] + [pe.Pokemon.create_fainted()] * 6)[:6],
                     active_index=pe.PokemonIndex("0"), side_conditions=pe.SideConditions(),
                     volatile_statuses=set())  # fmt: skip
        return pe.State(side_one=s.side_one, side_two=s2, weather=pe.Weather("none"),
                        weather_turns_remaining=0, terrain=pe.Terrain("none"),
                        terrain_turns_remaining=0, trick_room=False,
                        trick_room_turns_remaining=0).to_string()  # fmt: skip

    worlds = [world(["knockoff", "splash"]), world(["splash", "closecombat"])]
    assert len(alpha_search.ismcts(worlds, 0, iterations=200, seed=1)) == 4
    ours, n, _, _, theirs = alpha_search.ismcts(worlds, 0, iterations=4000, seed=1, opponent=True)
    names = {c for c, v, _ in theirs if v}
    assert {"knockoff", "splash", "closecombat"} <= names, theirs
    assert all(0.0 <= q <= 1.0 for _, _, q in theirs)
    # (every iteration backs up one option of each side at the root: the opponent's arms, in our
    # value, average to what ours do)
    mean = lambda arms: sum(v * q for _, v, q in arms) / sum(v for _, v, _ in arms)  # noqa: E731
    assert abs(mean(theirs) - mean(ours)) < 1e-3, (mean(theirs), mean(ours))
    ours, n, _, _, theirs = alpha_search.ismcts(
        worlds, 0, iterations=4000, seed=1, threads=2, opponent=True
    )
    assert abs(mean(theirs) - mean(ours)) < 1e-3  # (and merged over the threads' trees)
