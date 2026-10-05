from poke_env.battle import Pokemon
from poke_env.battle.move import Move

from alpha_poke.agents.damage import MonView, Spread, calc_stats, one_v_one


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
