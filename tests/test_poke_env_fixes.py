"""poke-env's methods we replace (agents/poke_env_fixes.py) take what poke-env passes them: the
player calls ``battle.parse_request(request, strict_battle_tracking)`` -- S115's replacement took
the request alone, and from 2026-10-23 every live game stalled on its first request (the state
checks call it with the request alone; found 2026-10-25 by the search A/B)."""

import inspect

from poke_env.battle import Battle
from poke_env.battle.abstract_battle import AbstractBattle

import alpha_poke.agents.poke_env_fixes  # noqa: F401 - installs the replacements


def test_the_replaced_methods_take_poke_envs_arguments():
    for cls, name, args in (
        (Battle, "parse_request", ({}, False)),
        (AbstractBattle, "parse_message", ([],)),
    ):
        inspect.signature(getattr(cls, name)).bind(object(), *args)  # (raises TypeError if not)


def test_the_player_calls_parse_request_with_the_strict_flag():
    import poke_env.player.player as player

    assert "parse_request(request, self._strict_battle_tracking)" in inspect.getsource(player)
