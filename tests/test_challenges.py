"""Accepting a friendly game's challenge (servers.accept_one) and the team order (TeamDeck),
2026-10-29: a challenge withdrawn before the accept left poke-env waiting forever."""

import asyncio
import logging
from types import SimpleNamespace

from alpha_poke.servers import TeamDeck, accept_one


class _Client:
    """poke-env's PSClient as accept_one uses it: the second accept of ``kid`` starts a battle."""

    def __init__(self, player, loop):
        self.player, self.loop, self.accepted = player, loop, []
        self.logged_in = asyncio.Event()
        self.logged_in.set()

    async def accept_challenge(self, user, team):
        self.accepted.append(user)
        if len(self.accepted) == 2:  # the battle starts (poke-env releases the semaphore)
            self.player._battle_semaphore.release()


def _player():
    loop = asyncio.get_running_loop()
    p = SimpleNamespace(_challenge_queue=asyncio.Queue(), _battle_semaphore=asyncio.Semaphore(0),
                        _battle_count_queue=asyncio.Queue(), next_team="team",
                        logger=logging.getLogger("t"))  # fmt: skip
    p.ps_client = _Client(p, loop)
    return p


def test_a_withdrawn_challenge_goes_back_to_waiting():
    async def run():
        p = _player()
        for user in ("someone", "Kid", "kid"):  # another user's, then the withdrawn one, again
            p._challenge_queue.put_nowait(user)
        await asyncio.wait_for(accept_one(p, "kid", start_timeout=0.05), 5)
        return p.ps_client.accepted

    assert asyncio.run(run()) == ["kid", "kid"]


def test_the_deck_uses_every_team_once_a_round():
    deck = TeamDeck(["a", "b", "c", "d"], seed=1)
    first, second = [deck.next() for _ in range(4)], [deck.next() for _ in range(4)]
    assert sorted(first) == sorted(second) == ["a", "b", "c", "d"]
    assert [TeamDeck(["a", "b", "c", "d"], seed=1).next() for _ in range(1)] == first[:1]
