"""Self-play: the stalling-loop detector (2026-10-14, design "防拖延循环")."""

from types import SimpleNamespace

from alpha_poke.selfplay.player import SelfPlayPlayer


def battle(turns: int, switch_every: int, faint_at: int = 1):
    data = [["", "switch", "p1a: A", "A", "100/100"], ["", "switch", "p2a: B", "B", "100/100"]]
    for t in range(1, turns + 1):
        data.append(["", "turn", str(t)])
        if t % switch_every == 0:
            data.append(["", "switch", "p1a: C", "C", "100/100"])
        else:
            data.append(["", "move", "p1a: A", "Tackle", "p2a: B"])
        if t == faint_at:
            data.append(["", "faint", "p2a: B"])
    return SimpleNamespace(_replay_data=data, player_role="p1")


def looping(b, loop=(20, 6, 8, 1.0, 0.25)):
    return SelfPlayPlayer.looping(SimpleNamespace(loop=loop), b)


def test_loop_needs_quiet_turns_and_switching():
    assert looping(battle(40, 1))  # switching every turn, no faint for 39 turns
    assert not looping(battle(40, 3))  # switching one turn in three: not a loop
    assert not looping(battle(40, 1, faint_at=30))  # a faint 10 turns ago: progress
    assert not looping(battle(40, 1), loop=None)


def test_incremental_equals_from_scratch():
    b = battle(40, 1)
    full = looping(b)
    c = battle(40, 1)
    data = c._replay_data
    c._replay_data = data[:30]
    looping(c)  # fed in two parts
    c._replay_data = data
    assert looping(c) == full
