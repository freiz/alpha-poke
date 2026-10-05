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
