"""Fixes to poke-env's battle tracking that our state construction reads (2026-10-23, the
state-construction differential, enginecheck/statebuild.py): applied once, on import (by
agents/engine_state.py), to every poke-env battle -- live, self-play and the replays' spectator
battles alike.

  Pressure    poke-env takes 2 PP for a move at a Pressure holder even under Neutralizing Gas or
              with the holder's ability suppressed (Gastro Acid): Showdown takes 1 (its DeductPP
              handler suppressed)
"""

from poke_env.battle import Effect, Field
from poke_env.battle.abstract_battle import AbstractBattle

_inner_pressure = AbstractBattle._pressure_on


def _pressure_on(self, pokemon: str, move: str, target_str):
    if Field.NEUTRALIZING_GAS in self.fields:
        return False
    if not _inner_pressure(self, pokemon, move, target_str):
        return False
    try:
        from poke_env.data import GenData

        move_data = GenData.from_gen(self.gen).moves[_move_id(move)]
        target = self._get_target_mon(pokemon, move_data["target"], target_str)
    except Exception:  # noqa: BLE001
        return True
    return not (target is not None and Effect.GASTRO_ACID in target.effects)


def _move_id(move: str) -> str:
    from poke_env.battle.move import Move

    return Move.retrieve_id(move)


if getattr(AbstractBattle, "_alpha_pressure_fixed", False) is False:
    AbstractBattle._pressure_on = _pressure_on
    AbstractBattle._alpha_pressure_fixed = True
