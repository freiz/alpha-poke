from poke_env.battle import Pokemon
from poke_env.battle.move import Move

from alpha_poke.agents.damage import MonView, Spread, calc_stats, damage_fraction, one_v_one


def view(species: str, spread: str, item: str | None = None) -> MonView:
    mon = Pokemon(gen=9, species=species)
    return MonView(
        mon, calc_stats(mon.base_stats, Spread.parse(spread)), {item: 1.0} if item else {}
    )


def test_recovery_wall_is_not_an_easy_win():
    attacker = view("dragapult", "Timid:0/0/0/252/4/252")
    wall = view("toxapex", "Bold:252/0/252/0/4/0", "blacksludge")
    weak_hit = [Move("dragonpulse", gen=9)]
    wall_moves = [Move("recover", gen=9), Move("surf", gen=9)]
    no_recovery = [Move("surf", gen=9)]
    # without Recover the wall loses the 1v1, with Recover the attacker can no longer KO it
    assert one_v_one(attacker, wall, weak_hit, no_recovery) > 0
    assert one_v_one(attacker, wall, weak_hit, wall_moves) <= 0


def test_toxic_breaks_a_recovery_wall():
    attacker = view("clodsire", "Careful:252/4/0/0/252/0")
    wall = view("blissey", "Bold:252/0/252/0/4/0")
    wall_moves = [Move("softboiled", gen=9), Move("seismictoss", gen=9)]
    plain = [Move("earthquake", gen=9)]
    toxic = plain + [Move("toxic", gen=9)]
    assert one_v_one(attacker, wall, toxic, wall_moves) >= one_v_one(
        attacker, wall, plain, wall_moves
    )


def test_fixed_damage_moves_are_attacks():
    from alpha_poke.agents.damage import damage_fraction, is_damaging

    blissey = view("blissey", "Bold:252/0/252/0/4/0")
    target = view("greattusk", "Jolly:0/252/0/0/4/252")
    target.mon.set_hp_status("100/100")  # a fresh Pokemon has no HP information
    toss, ruin = Move("seismictoss", gen=9), Move("ruination", gen=9)
    assert is_damaging(toss) and is_damaging(ruin)
    assert abs(damage_fraction(blissey, target, toss) - 100 / target.stats["hp"]) < 1e-9
    # half the target's current HP, times Ruination's 90% accuracy
    assert abs(damage_fraction(blissey, target, ruin) - 0.5 * ruin.accuracy) < 1e-9


def test_futile_attack_detection():
    from types import SimpleNamespace as NS

    from alpha_poke.agents.knowledge_player import BattleMemory

    mem = BattleMemory()
    move = NS(id="ruination")
    for turn in (3, 4, 5):  # opponent back at 51% (healed) at every decision
        opp = NS(species="moltres", current_hp_fraction=0.51)
        mem.record(NS(turn=turn, opponent_active_pokemon=opp, active_pokemon=None), (move, False))
    assert mem.futile_repeats("ruination", "moltres", 0.51) == 3
    assert mem.futile_repeats("ruination", "moltres", 0.30) == 0  # progress was made


def test_stalemate_detects_alternating_heal_loops():
    from types import SimpleNamespace as NS

    from alpha_poke.agents.knowledge_player import BattleMemory

    mem = BattleMemory()
    move = NS(id="ruination")
    for turn, hp in zip(range(1, 6), (1.0, 0.51, 1.0, 0.51, 1.0), strict=True):
        opp = NS(species="moltres", current_hp_fraction=hp)
        mem.record(NS(turn=turn, opponent_active_pokemon=opp, active_pokemon=None), (move, False))
    assert mem.stalemate("moltres", 0.51) >= 4  # no net progress over 4 decisions
    mem2 = BattleMemory()
    for turn, hp in zip(range(1, 6), (1.0, 0.8, 0.6, 0.4, 0.2), strict=True):
        opp = NS(species="moltres", current_hp_fraction=hp)
        mem2.record(NS(turn=turn, opponent_active_pokemon=opp, active_pokemon=None), (move, False))
    assert mem2.stalemate("moltres", 0.1) == 0


def test_variable_power_moves():
    from alpha_poke.agents.damage import damage_fraction, is_damaging, variable_base_power

    gambit = view("kingambit", "Adamant:252/252/0/0/4/0")
    heavy = view("dondozo", "Impish:252/0/252/0/4/0")  # 220 kg
    light = view("ribombee", "Timid:0/0/0/252/4/252")  # 0.5 kg
    for v in (heavy, light):
        v.mon.set_hp_status("100/100")
    low_kick = Move("lowkick", gen=9)
    assert is_damaging(low_kick)
    assert variable_base_power(gambit, heavy, low_kick) == 120
    assert variable_base_power(gambit, light, low_kick) == 20
    assert damage_fraction(gambit, heavy, low_kick) > 0
    endeavor = Move("endeavor", gen=9)
    user = view("araquanid", "Sassy:252/0/0/4/252/0")
    user.mon.set_hp_status("1/100")
    assert damage_fraction(user, heavy, endeavor) > 0.9


def test_entry_hazard_cost():
    from poke_env.battle import SideCondition

    from alpha_poke.agents.damage import entry_hazard_cost

    rocks_spikes = {SideCondition.STEALTH_ROCK: 1, SideCondition.SPIKES: 2}
    moltres = Pokemon(gen=9, species="moltres")  # 4x weak to Rock, Flying: no Spikes
    assert abs(entry_hazard_cost(moltres, rocks_spikes) - 0.5) < 1e-9
    kyurem = Pokemon(gen=9, species="kyurem")  # 2x weak to Rock, grounded
    assert abs(entry_hazard_cost(kyurem, rocks_spikes) - (0.25 + 1 / 6)) < 1e-9
    kyurem._item = "heavydutyboots"
    assert entry_hazard_cost(kyurem, rocks_spikes) == 0.0
    assert entry_hazard_cost(Pokemon(gen=9, species="kyurem"), {}) == 0.0


def test_mon_loss_is_cheap_only_when_nearly_dead():
    from alpha_poke.agents.knowledge_player import KO_BONUS, mon_loss

    assert mon_loss(1.0) == 1.0 + KO_BONUS  # same as the credit for a KO on a full-HP mon
    assert mon_loss(0.05) < 0.2


def test_ability_immunities():
    from alpha_poke.agents.belief_state import ability_probs

    ting = view("tinglu", "Careful:252/4/0/0/252/0")
    eq = Move("earthquake", gen=9)
    rotom = Pokemon(gen=9, species="rotomwash")  # only possible ability: Levitate
    rv = MonView(rotom, calc_stats(rotom.base_stats, Spread.parse("Bold:252/0/212/0/44/0")), {})
    rv.ability = rotom.ability
    assert damage_fraction(ting, rv, eq) == 0.0
    # unknown ability: Clodsire is Water Absorb ~30% of the time -> Surf damage scaled down
    clod = Pokemon(gen=9, species="clodsire")
    stats = calc_stats(clod.base_stats, Spread.parse("Careful:252/4/0/0/252/0"))
    known = MonView(clod, stats, {}, "unaware")
    unknown = MonView(clod, stats, {}, None, ability_probs(clod))
    surf = Move("surf", gen=9)
    att = view("walkingwake", "Timid:0/0/0/252/4/252")
    assert 0 < damage_fraction(att, unknown, surf) < damage_fraction(att, known, surf)
    # Mold Breaker ignores Levitate
    exca = view("excadrill", "Jolly:0/252/0/0/4/252")
    exca.ability = "moldbreaker"
    assert damage_fraction(exca, rv, eq) > 0


def test_status_blocked_by_good_as_gold():
    from alpha_poke.agents.knowledge_player import status_block_p

    gh = view("gholdengo", "Timid:0/0/0/252/4/252")
    gh.ability = "goodasgold"
    assert status_block_p(Move("toxic", gen=9), gh) == 1.0
    assert status_block_p(Move("stealthrock", gen=9), gh) == 0.0  # side move: not blocked


def test_no_effect_memory_from_battle_log():
    from types import SimpleNamespace

    from alpha_poke.agents.knowledge_player import BattleMemory

    rotom = Pokemon(gen=9, species="rotomwash")
    battle = SimpleNamespace(
        player_role="p1",
        _replay_data=[
            ["", "move", "p1a: Ting-Lu", "Earthquake", "p2a: Rotom"],
            ["", "-immune", "p2a: Rotom", "[from] ability: Levitate"],
            ["", "upkeep"],
        ],
        get_pokemon=lambda ident: rotom,
    )
    mem = BattleMemory()
    mem.scan_events(battle)
    assert mem.blocked(rotom, Move("earthpower", gen=9))  # same type: blocked too
    assert not mem.blocked(rotom, Move("stoneedge", gen=9))


def test_residual_ability_heal_is_not_an_immunity():
    from types import SimpleNamespace

    from alpha_poke.agents.knowledge_player import BattleMemory

    gliscor = Pokemon(gen=9, species="gliscor")
    battle = SimpleNamespace(
        player_role="p1",
        _replay_data=[
            ["", "move", "p1a: Moltres", "Flamethrower", "p2a: Gliscor"],
            ["", "-damage", "p2a: Gliscor", "40/100 tox"],
            ["", "-heal", "p2a: Gliscor", "52/100 tox", "[from] ability: Poison Heal"],
        ],
        get_pokemon=lambda ident: gliscor,
    )
    mem = BattleMemory()
    mem.scan_events(battle)
    assert not mem.no_effect


def test_scarf_is_a_mixture_not_a_blended_speed():
    from alpha_poke.agents.damage import moves_first

    a = view("dragapult", "Timid:0/0/0/252/4/252")  # 421 speed
    b = view("ironvaliant", "Timid:0/0/0/252/4/252")  # 361: faster only with a Scarf
    assert moves_first(a, b, None) == 1.0
    b.item_probs = {"choicescarf": 0.4}
    assert abs(moves_first(a, b, None) - 0.6) < 1e-9


def test_opponent_priority_ko_means_we_do_not_move_first():
    from alpha_poke.agents.knowledge_player import KnowledgePlayer

    me = view("dragapult", "Timid:0/0/0/252/4/252")
    me.mon._current_hp, me.mon._max_hp = 5, 100  # 5% HP
    opp = view("kingambit", "Adamant:252/252/0/0/4/0")
    sucker = Move("suckerpunch", gen=9)
    first = KnowledgePlayer._first
    assert first(None, None, me, opp, Move("shadowball", gen=9), [sucker]) == 0.0
    # Sucker Punch fails against a status move
    assert first(None, None, me, opp, Move("willowisp", gen=9), [sucker]) == 1.0


def test_lookahead_penalises_a_switch_in_that_is_just_as_threatened():
    from types import SimpleNamespace

    from alpha_poke.agents.knowledge_player import KnowledgePlayer

    bot = SimpleNamespace(_first=lambda *a, **k: KnowledgePlayer._first(None, *a, **k), _threat=0.0)
    wake = view("walkingwake", "Timid:0/0/0/252/4/252", "choicespecs")
    draco = [Move("dracometeor", gen=9), Move("hydrosteam", gen=9)]
    kingambit = view("kingambit", "Adamant:252/252/0/0/4/0")
    kingambit.mon._add_move("ironhead")
    clefable = view("clefable", "Bold:252/0/252/4/0/0")  # Fairy: immune to Draco Meteor
    clefable.mon._add_move("moonblast")
    nv = KnowledgePlayer._next_turn_value
    # a 30% Kingambit just takes the Draco Meteor (floored: it would switch out again);
    # a Clefable is a real answer
    threatened = nv(bot, None, kingambit, wake, draco, 0.3)
    answer = nv(bot, None, clefable, wake, draco, 1.0)
    assert threatened < 0 < answer
