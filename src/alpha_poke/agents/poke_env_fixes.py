"""Fixes to poke-env's battle tracking that our state construction reads (2026-10-23, the
state-construction differential, enginecheck/statebuild.py): applied once, on import (by
agents/engine_state.py), to every poke-env battle -- live, self-play and the replays' spectator
battles alike.

  Pressure    poke-env takes 2 PP for a move at a Pressure holder even under Neutralizing Gas or
              with the holder's ability suppressed (Gastro Acid): Showdown takes 1 (its DeductPP
              handler suppressed)
  Illusion    a broken Illusion (replace): poke-env clears the disguise's volatiles (its
              switch-out) and gives the Zoroark none -- Showdown's were the Zoroark's all along
              (a Salt Cure that broke it stayed on: S60); they go to the Zoroark (its boosts: the
              timers' illusion_boosts)
              -- and live, a request's active the Zoroark our switch-in's log named the disguise
              of: poke-env's fix switches the disguise out, its stage changes and volatiles this
              turn lost (a Sticky Web's Speed drop: S68)
  Disguise    live, the request made our Zoroark the active: the log still names its disguise
              ("p1a: Bronzong") -- poke-env gave the disguise's object the stage changes and
              volatiles, the Zoroark lost them: an active slot's ident is the active (Showdown's
              position), our Zoroark (S82); not a switch's
  Formes      a -formechange (Meloetta-Pirouette, Cramorant-Gulping, Morpeko-Hangry: Showdown's
              formeChange, not permanent) changes poke-env's types and stats and its switch-out
              keeps them -- Showdown's switch-out (clearVolatile) gives the species' back: the
              Meloetta back in as Aria had Pirouette's types (S66); a detailschange's stays
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


_inner_end_illusion = AbstractBattle._end_illusion_on


def _end_illusion_on(self, illusionist, illusioned, details: str):
    effects = dict(illusioned.effects) if illusioned is not None else {}
    # (our own disguise's stage changes too, live -- a battle with requests; the opponent's / a
    # replay's: the timers' illusion_boosts, engine_state adds them; S81: a Special Defense drop
    # the turn it broke)
    ours = illusioned is not None and bool(self._last_request) \
        and any(m is illusioned for m in self.team.values())
    boosts = dict(illusioned.boosts) if ours else {}
    mon = _inner_end_illusion(self, illusionist, illusioned, details)
    if mon is not illusioned:
        for effect, count in effects.items():
            mon.effects.setdefault(effect, count)
        for k, v in boosts.items():
            if v:
                mon.boosts[k] = v
    return mon




_inner_update_team = AbstractBattle._update_team_from_request


def _update_team_from_request(self, side, strict_battle_tracking: bool = False):
    actives = [p["ident"] for p in side.get("pokemon", []) if p.get("active")]
    falsely = [m for p in side.get("pokemon", []) if not p.get("active")
               and (m := self._team.get(p["ident"])) is not None and m.active]  # fmt: skip
    # (one disguise, its Zoroark: the request's active -- maybe not in the team yet, a lead's)
    carried = (dict(falsely[0].boosts), dict(falsely[0].effects)) \
        if len(falsely) == 1 and len(actives) == 1 else None  # fmt: skip
    _inner_update_team(self, side, strict_battle_tracking)
    target = self._team.get(actives[0]) if carried is not None else None
    if target is not None and target is not falsely[0]:
        boosts, effects = carried
        for k, v in boosts.items():
            if v:
                target.boosts[k] = v
        for effect, count in effects.items():
            target.effects.setdefault(effect, count)


if getattr(AbstractBattle, "_alpha_illusion_fixed", False) is False:
    AbstractBattle._end_illusion_on = _end_illusion_on
    AbstractBattle._update_team_from_request = _update_team_from_request
    AbstractBattle._alpha_illusion_fixed = True


_inner_parse_message = AbstractBattle.parse_message


def _parse_message(self, split_message):
    self.__dict__["_alpha_event"] = split_message[1] if len(split_message) > 1 else ""
    try:
        _inner_parse_message(self, split_message)
    finally:
        self.__dict__["_alpha_event"] = ""
    temp = self.__dict__.setdefault("_alpha_temp_formes", {})  # id -> a mon in a -formechange forme
    if len(split_message) > 3 and split_message[1] in ("-formechange", "detailschange"):
        try:
            mon = self.get_pokemon(split_message[2])
        except Exception:  # noqa: BLE001
            return
        if split_message[1] == "-formechange":
            temp[id(mon)] = mon
        else:
            temp.pop(id(mon), None)
    for k, mon in list(temp.items()):
        if not mon.active:  # (switched out: the species' types and stats back)
            del temp[k]
            try:
                mon._update_from_pokedex(mon.species, store_species=False)
            except KeyError:
                pass


if getattr(AbstractBattle, "_alpha_formes_fixed", False) is False:
    AbstractBattle.parse_message = _parse_message
    AbstractBattle._alpha_formes_fixed = True


_inner_get_pokemon = AbstractBattle.get_pokemon
_SWITCHES = ("switch", "drag", "replace", "detailschange", "poke", "teampreview")


def _get_pokemon(self, identifier, force_self_team=False, details="", request=None):
    mon = _inner_get_pokemon(self, identifier, force_self_team, details, request)
    if (len(identifier) > 2 and identifier[2] == "a" and identifier[:2] == self.player_role
            and self._last_request and self.__dict__.get("_alpha_event", "") not in _SWITCHES):
        act = self.active_pokemon
        if act is not None and act is not mon and act.species.startswith("zoroark"):
            return act
    return mon


if getattr(AbstractBattle, "_alpha_disguise_fixed", False) is False:
    AbstractBattle.get_pokemon = _get_pokemon
    AbstractBattle._alpha_disguise_fixed = True
