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
  Pressure    ... and a disguised Zoroark's (Illusion, no Pressure) found out: the moves at it this
              time in get their extra PP back (S99)
  Psych Up    |-copyboost|user|target: the user takes the target's stage changes -- poke-env had
              it backwards (S147)
  Lunar Dance Gen 9's restores the PP too: poke-env's count restored (its count, Pressure's 2
              included, from there -- the timers' uses since counted 1 each: S84)
  Skill Swap  the [of] mon's own ability (the one the user got) never set: a Pressure announced
              after the swap became its own -- every move at it 2 PP after (S85)
  Switch-in   live, our Zoroark switched in as a disguise: the shown max HP is the Zoroark's --
              poke-env switches the Zoroark in (S86)
  Yawn        poke-env ends it at any sleep an HP line shows (a Rest's): Showdown's own -end (S115)
  Formes      a -formechange (Meloetta-Pirouette, Cramorant-Gulping, Morpeko-Hangry: Showdown's
              formeChange, not permanent) changes poke-env's types and stats and its switch-out
              keeps them -- Showdown's switch-out (clearVolatile) gives the species' back: the
              Meloetta back in as Aria had Pirouette's types (S66); a detailschange's stays
  Tera        ... and a disguised Zoroark's Terastallization: the -terastallize line named the
              disguise -- its own after the Illusion broke; and a disguise's level: its switch-in's
              details the Zoroark's -- the team preview's kept (S158)
"""

from poke_env.battle import Battle, Effect, Field
from poke_env.battle.abstract_battle import AbstractBattle
from poke_env.data.normalize import to_id_str

_inner_pressure = AbstractBattle._pressure_on


def _pressure_on(self, pokemon: str, move: str, target_str):
    if Field.NEUTRALIZING_GAS in self.fields:
        return False
    try:
        from poke_env.data import GenData

        data = GenData.from_gen(self.gen).moves[_move_id(move)]
    except Exception:  # noqa: BLE001
        data = {}
    if data.get("target") == "self" and "mustpressure" in data.get("flags", {}):
        # (a self-targeting move Pressure reaches all the same -- Imprison, Snatch: the foe's
        # active's Pressure, poke-env checked its user's; S134)
        user = self.get_pokemon(pokemon)
        foe = self.opponent_active_pokemon if user in self.team.values() else self.active_pokemon
        return foe is not None and foe.ability == "pressure" and not foe.fainted \
            and Effect.GASTRO_ACID not in foe.effects
    if not _inner_pressure(self, pokemon, move, target_str):
        return False
    try:
        from poke_env.data import GenData

        move_data = GenData.from_gen(self.gen).moves[_move_id(move)]
        target = self._get_target_mon(pokemon, move_data["target"], target_str)
    except Exception:  # noqa: BLE001
        return True
    if target is not None and Effect.GASTRO_ACID in target.effects:
        return False
    if target is not None:  # (its extra PP, kept per target this time in: an Illusion's refunded)
        self.__dict__.setdefault("_alpha_pressured", {}).setdefault(id(target), []).append(
            (self.get_pokemon(pokemon), _move_id(move)))
    return True


def _move_id(move: str) -> str:
    from poke_env.battle.move import Move

    return Move.retrieve_id(move)


if getattr(AbstractBattle, "_alpha_pressure_fixed", False) is False:
    AbstractBattle._pressure_on = _pressure_on
    AbstractBattle._alpha_pressure_fixed = True


_inner_end_illusion = AbstractBattle._end_illusion_on


def _end_illusion_on(self, illusionist, illusioned, details: str):
    effects = dict(illusioned.effects) if illusioned is not None else {}
    # (the moves at the disguise a Pressure took 2 PP from: the Zoroark's Illusion, 1 -- S99)
    for user, mid in self.__dict__.get("_alpha_pressured", {}).pop(id(illusioned), []):
        mv = user.moves.get(mid)
        if mv is not None:
            mv._current_pp = min(mv.max_pp, mv._current_pp + 1)
    # (our own disguise's stage changes too, live -- a battle with requests; the opponent's / a
    # replay's: the timers' illusion_boosts, engine_state adds them; S81: a Special Defense drop
    # the turn it broke)
    ours = illusioned is not None and bool(self._last_request) \
        and any(m is illusioned for m in self.team.values())
    boosts = dict(illusioned.boosts) if ours else {}
    types = list(illusioned._temporary_types) if illusioned is not None else []  # (a Soak on it: S148)
    # (its Terastallization in disguise -- the -terastallize line named the disguise: the Zoroark's;
    # the disguise, a Flygon never in, had it after: S158)
    tera = (illusioned._terastallized, illusioned._terastallized_type) if illusioned is not None else (False, None)
    if illusioned is not None and self.__dict__.get("_alpha_tera_in", {}).get(id(illusioned)):
        tera = (False, None)  # (its own, before the disguise came in: a Serperior's earlier one)
    mon = _inner_end_illusion(self, illusionist, illusioned, details)
    if mon is not illusioned:
        if types:
            mon._temporary_types = types
        if tera[0] and illusioned is not None:
            mon._terastallized, mon._terastallized_type = tera
            illusioned._terastallized = False
            if not ours:  # (ours: the request's; the foe's disguise its own, unknown)
                illusioned._terastallized_type = None
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
    carried = (dict(falsely[0].boosts), dict(falsely[0].effects), list(falsely[0]._temporary_types)) \
        if len(falsely) == 1 and len(actives) == 1 else None  # fmt: skip
    _inner_update_team(self, side, strict_battle_tracking)
    target = self._team.get(actives[0]) if carried is not None else None
    if target is not None and target is not falsely[0]:
        boosts, effects, types = carried
        if types:
            target._temporary_types = types
        for k, v in boosts.items():
            if v:
                target.boosts[k] = v
        for effect, count in effects.items():
            target.effects.setdefault(effect, count)


_inner_switch = Battle.switch
_inner_register_preview = AbstractBattle._register_teampreview_pokemon


def _register_preview(self, player: str, details: str):
    """poke-env keeps the opponent's team preview only: our own's levels too (a spectator's --
    the replay path's -- our disguise's level below; 2026-10-26 review)."""
    _inner_register_preview(self, player, details)
    if player == self._player_role:
        from poke_env.battle import Pokemon

        mon = Pokemon(details=details, gen=self.gen)
        self.__dict__.setdefault("_alpha_own_preview", {})[mon.species] = mon.level


def _switch(self, pokemon_str: str, details: str, hp_status: str):
    _inner_switch(self, pokemon_str, details, hp_status)
    ours = pokemon_str.split(":")[0][:2] == self._player_role
    mon = self.active_pokemon if ours else self.opponent_active_pokemon
    if mon is None:
        return
    # (whether it came in terastallized: a Zoroark's tera in its disguise is the one after -- either
    # side's: the replay path's own Zoroark too, 2026-10-26 review)
    self.__dict__.setdefault("_alpha_tera_in", {})[id(mon)] = mon._terastallized
    # (a disguised Zoroark's switch-in details name the disguise at the Zoroark's level -- a
    # Spectrier at 83 for its 75, never found out; a level never changes: the team preview's.
    # Ours: a request's level is exact -- only a spectator's, the replay path's)
    if ours:
        lv = None if self._last_request else self.__dict__.get("_alpha_own_preview", {}).get(mon.species)
    else:
        lv = next((m.level for m in self._teampreview_opponent_team if m.species == mon.species), None)
    if lv is not None:
        mon._level = lv


if getattr(AbstractBattle, "_alpha_illusion_fixed", False) is False:
    AbstractBattle._end_illusion_on = _end_illusion_on
    AbstractBattle._update_team_from_request = _update_team_from_request
    Battle.switch = _switch
    AbstractBattle._register_teampreview_pokemon = _register_preview
    AbstractBattle._alpha_illusion_fixed = True


_inner_parse_message = AbstractBattle.parse_message


def _max_hp(condition: str) -> int | None:
    hp = condition.split()[0] if condition else ""
    return int(hp.split("/")[1]) if "/" in hp and hp.split("/")[1].isdigit() else None


def _our_disguised_switch(self, split_message):
    """Live, our switch-in shown as one mon whose max HP is not its own but our Zoroark's: the
    Zoroark in disguise (we chose it) -- the message as poke-env should read it (the Zoroark's
    ident and details), else None. poke-env took the disguise as the one in until the turn's
    request (S86: a hit on it at a Pressure disguise took 2 PP of the foe's move)."""
    if len(split_message) < 5 or split_message[1] not in ("switch", "drag") or not self._last_request \
            or split_message[2][:2] != self.player_role:
        return None
    side = (self._last_request.get("side") or {}).get("pokemon") or []
    shown = _max_hp(split_message[4])
    nick = split_message[2].split(": ", 1)[-1]
    named = next((p for p in side if p["ident"].split(": ", 1)[-1] == nick), None)
    if named is None or shown is None or _max_hp(named.get("condition", "")) in (None, shown):
        return None
    z = next((p for p in side if p.get("details", "").startswith("Zoroark")
              and _max_hp(p.get("condition", "")) == shown), None)  # fmt: skip
    if z is None:
        return None
    out = list(split_message)
    out[2] = f"{split_message[2][:3]}: {z['ident'].split(': ', 1)[-1]}"
    out[3] = z["details"]
    return out


def _display_typechange(split_message) -> bool:
    """Showdown's -start typechange [silent] with no cause: a switch-in's apparent types (Gen 7+),
    an Illusion's its disguise's."""
    return len(split_message) > 4 and split_message[1] == "-start" and split_message[3] == "typechange" \
        and "[silent]" in split_message and not any(x.startswith("[from]") for x in split_message[4:])


def _ability_set(self, split_message):
    """(the mon, its ability before, the one it had, the new one) of a line that sets an ability
    over another, else None."""
    tag = split_message[1] if len(split_message) > 1 else ""
    if tag == "-ability" and len(split_message) > 5 and not split_message[4].startswith("[") \
            and any(x.startswith("[from]") for x in split_message[5:]):
        mon, old, new = split_message[2], split_message[4], split_message[3]
    elif tag == "-activate" and len(split_message) > 5 \
            and split_message[3] in ("ability: Mummy", "ability: Lingering Aroma"):
        old = next((x[10:] for x in split_message[5:] if x.startswith("[ability] ")), "")
        mon, new = split_message[4], split_message[3][9:]
    else:
        return None
    try:
        p = self.get_pokemon(mon)
    except Exception:  # noqa: BLE001 - not a mon of this battle's
        return None
    return (p, p._ability, to_id_str(old), to_id_str(new)) if old else None


def _parse_message(self, split_message):
    yawned = [m for m in (*self._team.values(), *self._opponent_team.values()) if Effect.YAWN in m.effects]
    yawn_end = split_message[1:2] == ["-end"] and "Yawn" in "".join(split_message[3:4])
    if len(split_message) > 6 and split_message[1] == "-activate" \
            and split_message[3].replace("move: ", "") == "Skill Swap" and split_message[-1].startswith("[of] "):
        # (the [of] mon's own ability: the one the user got -- the first named; S85)
        of = self.get_pokemon(split_message[-1][5:])
        if of._ability is None and split_message[4]:
            of._ability = to_id_str(split_message[4].replace("[ability] ", ""))
    # (an ability set over another -- Worry Seed, Entrainment, Simple Beam, Role Play, Doodle, Trace:
    # Showdown's -ability NEW OLD [from]; Mummy / Lingering Aroma's -activate's [ability] OLD -- names
    # the one it had: its own when unknown, the new one temporary. poke-env took the first ability it
    # saw for its own: a Worry Seed's Insomnia, kept after a switch-out; 2026-10-25 review)
    changed = _ability_set(self, split_message)
    kept = None
    if split_message[1:2] == ["-terastallize"] and len(split_message) > 2:
        # (Terastallization keeps the pre-tera types -- a transformed Ditto's copied ones:
        # poke-env drops its temporary types; S136)
        kept = self.get_pokemon(split_message[2])
        kept = (kept, list(kept._temporary_types))
    disguised = _our_disguised_switch(self, split_message)
    if disguised is not None:  # (poke-env switches the Zoroark in; the log stays as shown)
        _inner_parse_message(self, disguised)
        self._replay_data[-1] = split_message[:]
    elif split_message[1:2] == ["-copyboost"] and len(split_message) > 3:
        # (Psych Up: |-copyboost|user|target -- the user takes its target's stage changes;
        # poke-env copied them the other way: S147)
        self._replay_data.append(split_message[:])
        self.get_pokemon(split_message[2]).copy_boosts(self.get_pokemon(split_message[3]))
    elif _display_typechange(split_message):
        # (Showdown's display of a switch-in's apparent types -- Gen 7+'s bottom screen: no type
        # change; a disguise's are its disguise's -- S83, S97: a Ditto transformed into a Normal
        # type read as type-changed)
        self._replay_data.append(split_message[:])
    else:
        _inner_parse_message(self, split_message)
    if kept is not None and kept[1]:
        kept[0]._temporary_types = kept[1]
    if changed is not None:
        mon, before, old, new = changed
        if before is None:
            mon._ability = old  # (the one it had: its own)
        if new != to_id_str(mon._ability or ""):
            mon.temporary_ability = new
    for m in yawned:  # (poke-env ends Yawn at any sleep its HP line shows -- a Rest's too:
        # Showdown keeps it till its own -end; S115)
        if Effect.YAWN not in m.effects and m.active and not yawn_end:
            m.effects[Effect.YAWN] = 0
    if split_message[1:2] == ["cant"] and len(split_message) > 3 \
            and not any(x.startswith("[of]") for x in split_message[4:]):
        # (Glaive Rush's drawback ends before any stopped move -- its BeforeMove priority 100: S135)
        self.get_pokemon(split_message[2]).effects.pop(Effect.GLAIVE_RUSH, None)
    if len(split_message) == 3 and split_message[1] == "-endability":
        # (Gastro Acid: Showdown logs its suppression so -- poke-env keeps no effect of it, its
        # Pressure still took 2 PP: S100)
        self.get_pokemon(split_message[2]).effects.setdefault(Effect.GASTRO_ACID, 1)
    if len(split_message) > 3 and split_message[1] in ("switch", "drag"):  # (a new time in)
        self.__dict__.get("_alpha_pressured", {}).pop(id(self.get_pokemon(split_message[2])), None)
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
        # (a forme change sets the forme's types -- Showdown's setSpecies: a Soak before it gone;
        # S124: an Ogerpon soaked, then its tera forme)
        mon.effects.pop(Effect.TYPECHANGE, None)
        mon._temporary_types = []
    if len(split_message) > 3 and split_message[1] == "-transform":
        # (its target's types now -- a Libero's / Soak's included: Showdown's transformInto copies
        # getTypes; poke-env its species' -- S136)
        mon, target = self.get_pokemon(split_message[2]), self.get_pokemon(split_message[3])
        mon._temporary_types = list(target.base_types)
    if len(split_message) > 3 and split_message[1] == "-heal" and "[from] move: Lunar Dance" in split_message:
        for mv in self.get_pokemon(split_message[2]).moves.values():
            mv._current_pp = mv.max_pp
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




_inner_parse_request = Battle.parse_request


def _parse_request(self, request, *args, **kwargs):
    # (a request's conditions: its sleep ends no Yawn either -- S115)
    # (poke-env's player passes strict_battle_tracking too: 2026-10-25, every live game stalled
    # on a TypeError at its first request -- the state checks call it with the request alone)
    yawned = [m for m in self._team.values() if Effect.YAWN in m.effects]
    _inner_parse_request(self, request, *args, **kwargs)
    for m in yawned:
        if Effect.YAWN not in m.effects and m.active:
            m.effects[Effect.YAWN] = 0


if getattr(Battle, "_alpha_yawn_fixed", False) is False:
    Battle.parse_request = _parse_request
    Battle._alpha_yawn_fixed = True
