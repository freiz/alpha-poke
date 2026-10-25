"""The state-construction differential (2026-10-23, after ten review rounds of point fixes): our
engine state built from what a player sees -- poke-env's battle from its protocol view and its
request, agents/engine_state.build_state -- against the engine state built from Showdown's own
(``engine_state``, the reference of the engine differential), at every decision of random
battles (``random_battle(..., views=...)``).

Compared: what the player can know -- its own side whole (each mon's HP, stats, status, item,
abilities, moves with PP and Disable, tera, sleep counters, transform backup; the side's
volatiles and their counts, conditions and their turns, boosts, Substitute, Wish / Future
Sight), the opponent's public parts (the active, each revealed mon's HP fraction and status,
tera, boosts, volatiles and counts, conditions and turns) and the field (weather / terrain /
rooms and their turns). The opponent's hidden parts are the belief's samples: not compared.
The replay path (a spectator's view, its own known set: build_state's ``spectator``) is
compared the same way (``replay=True``).

  diffs = battle_diffs(p1_team, p2_team, seed=0)   # [(step, side, kind, detail)]
"""

import contextlib
import json
import logging
import random

import poke_engine as pe
from poke_env.battle import Battle

from alpha_poke.analysis.roles import to_id

from . import HIDDEN_LENGTH, engine_state, random_battle

LOG = logging.getLogger("statebuild")
LOG.setLevel(logging.CRITICAL)

# the side's volatile counts compared (the engine's VolatileStatusDurations)
DURATIONS = ("confusion", "disable", "encore", "healblock", "magnetrise", "partiallytrapped",
             "slowstart", "taunt", "throatchop", "yawn", "lockedmove")  # fmt: skip
# every side condition of the engine's (S158: a hand-written list left Healing Wish out -- never
# compared, never built); test_every_field_is_compared_or_says_why
CONDITIONS = tuple(sorted(x for x in dir(pe.SideConditions) if not x.startswith("_")))
BOOSTS = ("attack_boost", "defense_boost", "special_attack_boost", "special_defense_boost",
          "speed_boost", "accuracy_boost", "evasion_boost")  # fmt: skip
STATS = ("attack", "defense", "special_attack", "special_defense", "speed")
# the side's own fields compared as they are
SIDE_FIELDS = ("substitute_health", "wish", "future_sight",
               "switch_out_move_second_saved_move")  # fmt: skip
# both sides': the last used move (by name: a move slot's, a switch's slot, none)
_BELIEF = None



def _true_forme(sp: str, t: dict, moves: list) -> str | None:
    """A hidden forme's, the truth's: Showdown's species when it is one of the forme candidates
    (S158 -- not engine_state.resolve_forme from the true set: a Dudunsparce-Three-Segment's set
    is a Dudunsparce's too); a forme the set alone tells, resolve_forme's (unit-tested)."""
    from alpha_poke.agents import engine_state as es

    if sp not in es.HIDDEN_FORMES:
        return None
    f = to_id(t.get("species") or "")
    if f not in es._forme_candidates(sp):
        f = es.resolve_forme(sp, t["item"] or "", t["base_ability"] or t["ability"] or "", moves)
    return f if f != sp else None


def _belief():
    global _BELIEF
    if _BELIEF is None:
        from alpha_poke.agents.belief_state import BeliefModel

        _BELIEF = BeliefModel.load()
    return _BELIEF


# species ids taken as one: a Battle Bond set's Greninja (the engine's Greninja-Bond, its Battle
# Bond's species; Showdown shows "Greninja", and a fixture's plain Greninja with Battle Bond is
# "greninja" in Showdown, where its Battle Bond does nothing)
SAME_SPECIES = {"greninjabond": "greninja"}


def _sp(p) -> str:
    sp = to_id(p.id)
    return SAME_SPECIES.get(sp, sp)


def _mons(side: pe.Side) -> dict:
    return {_sp(p): p for p in side.pokemon if p.id.lower() != "none"}


def _active(side: pe.Side):
    return side.pokemon[int(side.active_index)]


def _vols(side: pe.Side) -> set[str]:
    return {str(v).lower() for v in side.volatile_statuses}


def _durs(side: pe.Side, vols: set[str]) -> dict:
    d = side.volatile_status_durations
    out = {}
    for k in DURATIONS:
        if k in vols:
            v = getattr(d, k)
            if k == "disable":  # (slot * 8 + count: the slot by the move's name)
                out[k] = (_active(side).moves[v // 8].id.lower(), v % 8)
            else:
                out[k] = v
    return out


def own_diffs(built: pe.Side, truth: pe.Side) -> list[tuple[str, str]]:
    """A player's own side: everything it knows."""
    out = []
    bm, tm = _mons(built), _mons(truth)
    if set(bm) != set(tm):
        out.append(("own:team", f"{sorted(bm)} vs {sorted(tm)}"))
    if _sp(_active(built)) != _sp(_active(truth)):
        out.append(("own:active", f"{_sp(_active(built))} vs {_sp(_active(truth))}"))
    for sp in set(bm) & set(tm):
        b, t = bm[sp], tm[sp]
        # (a fainted mon's tera: where the side's used Terastallization is marked -- either
        # fainted one, L177 -- compared as the side's, own:tera_used; a transformed mon's stats
        # are its target's real ones, which its player does not see: not compared)
        keys = ["hp"]  # (a fainted one: nothing else of it is read -- its forme back, its maxhp)
        if t.hp > 0:
            keys += ["maxhp", "status", "item", "ability", "base_ability", "rest_turns",
                     "sleep_turns", "terastallized", "tera_type", "last_item",
                     "weight_kg"]  # fmt: skip (2026-10-24 review: a Ditto's copied weight kept)
        if t.transform_backup is None and t.hp > 0:
            keys += list(STATS)
        for k in keys:
            if _norm(k, getattr(b, k)) != _norm(k, getattr(t, k)):
                out.append((f"own:{k}", f"{sp} {getattr(b, k)} vs {getattr(t, k)}"))
        out += _type_diffs("own", sp, b, t)
        bmv = {m.id.lower(): (m.pp, m.disabled) for m in b.moves if m.id.lower() != "none"}
        tmv = {m.id.lower(): (m.pp, m.disabled) for m in t.moves if m.id.lower() != "none"}
        if t.hp <= 0:
            continue  # (a fainted one's moves and PP: nothing reads them)
        if set(bmv) != set(tmv):
            out.append(("own:moves", f"{sp} {sorted(bmv)} vs {sorted(tmv)}"))
        for mid in set(bmv) & set(tmv):
            if bmv[mid][0] != tmv[mid][0]:
                out.append(("own:pp", f"{sp} {mid} {bmv[mid][0]} vs {tmv[mid][0]}"))
            if bmv[mid][1] != tmv[mid][1]:
                out.append(("own:disabled", f"{sp} {mid} {bmv[mid][1]} vs {tmv[mid][1]}"))
        if (b.transform_backup is None) != (t.transform_backup is None) or (
            b.transform_backup and sorted(b.transform_backup[2]) != sorted(t.transform_backup[2])
        ) or (b.transform_backup and b.transform_backup[0] != t.transform_backup[0]) or (
            b.transform_backup and b.transform_backup[1] != t.transform_backup[1]):
            out.append(("own:transform_backup", f"{sp} {b.transform_backup} vs {t.transform_backup}"))
    if _tera_used(built) != _tera_used(truth):
        out.append(("own:tera_used", f"{_tera_used(built)} vs {_tera_used(truth)}"))
    out += _side_common("own", built, truth)
    for k in SIDE_FIELDS:
        bv, tv = getattr(built, k), getattr(truth, k)
        if k == "future_sight":  # (its user by species: the sides' mon orders differ)
            bv, tv = (_future(built), _future(truth))
        if k == "substitute_health" and tv not in (0, _active(truth).maxhp // 4):
            continue  # (a hit Substitute's HP: the log does not show it -- the player's guess)
        if str(bv).lower() != str(tv).lower():
            out.append((f"own:{k}", f"{bv} vs {tv}"))
    return out


def _norm(k: str, v) -> str:
    """A field's value as the engine reads it (an item it does not know: UNKNOWNITEM, as the
    differential's states name it)."""
    from alpha_poke.agents.engine_state import engine_item

    if k == "weight_kg":
        return f"{float(v):.1f}"
    v = str(v).lower()
    if k in ("item", "last_item") and v not in ("none", "") and not engine_item(v):
        return "unknownitem"
    return v


def _future(side: pe.Side):
    turns, idx = side.future_sight
    return (turns, _sp(side.pokemon[int(str(idx))]) if turns else "")


def _tera_used(side: pe.Side) -> bool:
    return any(p.terastallized for p in side.pokemon) or bool(getattr(side, "tera_used", False))


def _last_used(side: pe.Side) -> str:
    """The side's last used move by name ("move:<id>", "switch", "none")."""
    lu = str(side.last_used_move).lower()
    if lu.startswith("move:") and lu[5:].isdigit():
        return "move:" + _active(side).moves[int(lu[5:])].id.lower()
    return lu.split(":")[0] if lu.startswith("switch") else lu


def _transform_slot(side: pe.Side) -> bool:
    """The side's last used move is a slot of its transformed active's backup holding Transform."""
    lu = str(side.last_used_move).lower()
    backup = getattr(_active(side), "transform_backup", None)
    return bool(backup) and lu.startswith("move:") and lu[5:].isdigit() \
        and str(backup[2][int(lu[5:])][0]).lower() == "transform"


def _side_common(who: str, built: pe.Side, truth: pe.Side) -> list[tuple[str, str]]:
    """What both players see of a side: volatiles and their counts, conditions, boosts. (An active
    that fainted: its volatiles and boosts go with the switch -- not compared; the lengths
    Showdown draws when they start -- HIDDEN_LENGTH -- are the truth's, not the player's: their
    presence only.)"""
    out = []
    for k in CONDITIONS:
        b, t = getattr(built.side_conditions, k), getattr(truth.side_conditions, k)
        if k in ("toxic_count", "protect") and _active(truth).hp <= 0:
            continue  # (the active's own counts: a fainted one's go with it)
        if b != t:
            out.append((f"{who}:condition:{k}", f"{b} vs {t}"))
    if _active(truth).hp <= 0:
        return out
    if _last_used(built) != _last_used(truth) and not (_transform_slot(built) and _transform_slot(truth)):
        # (transformed, its Transform the last: the slot in its backup -- its own moves' order, a
        # replay's sampled one, is notation)
        out.append((f"{who}:last_used_move", f"{_last_used(built)} vs {_last_used(truth)}"))
    bv, tv = _vols(built), _vols(truth)
    bv.discard("flinch")  # (a flinch is drawn silently -- shown only as it stops the move: hidden)
    tv.discard("flinch")
    if _silent_lock_end(built, truth):
        bv.discard("lockedmove")
        tv.discard("lockedmove")
    for v in sorted(bv ^ tv):
        out.append((f"{who}:volatile:{v}", "built" if v in bv else "truth"))
    bd, td = _durs(built, bv & tv), _durs(truth, bv & tv)
    for k in bd:
        if k not in HIDDEN_LENGTH and bd[k] != td.get(k):
            out.append((f"{who}:duration:{k}", f"{bd[k]} vs {td.get(k)}"))
    for k in BOOSTS:
        b, t = getattr(built, k), getattr(truth, k)
        if b != t:
            out.append((f"{who}:boost:{k}", f"{b} vs {t}"))
    return out


def _disguised(battle, truth: pe.Side) -> set[str]:
    """The opponent's species ids a Zoroark showed itself as without being found out (a switch
    line's max HP not the mon's -- the differential's battles show exact HP): the player cannot
    tell (percentages in real battles), the belief's HP / moves for them its fair guess. Its
    Zoroark too, while it was never revealed."""
    tm = {_sp(p): p.maxhp for p in truth.pokemon}
    role = "p2" if battle.player_role == "p1" else "p1"
    out = set()
    for m in battle._replay_data:
        if len(m) > 4 and m[1] in ("switch", "drag") and m[2].startswith(role) and "/" in m[4]:
            sp = to_id(m[3].split(",")[0])
            sp = SAME_SPECIES.get(sp, sp)
            mx = m[4].split(" ")[0].split("/")[1]
            if sp in tm and mx.isdigit() and int(mx) != tm[sp] and int(mx) != 100:
                out.add(sp)
    if out:
        out |= {s for s in tm if s.startswith("zoroark")}
    return out


def foe_diffs(built: pe.Side, truth: pe.Side, seen: set[str], oracle: bool = False,
              hidden: frozenset = frozenset()) -> list[tuple[str, str]]:  # fmt: skip
    """The opponent's side as the player sees it: the active, the revealed mons' HP fraction
    and status, tera; the side's volatiles, counts, conditions, boosts. ``oracle`` (its sets the
    true ones): also the revealed mons' item, abilities, stats and moves with their PP."""
    out = []
    if "illusion" in _vols(truth) or "illusion" in _vols(built):
        # (its active an Illusion in disguise -- or this world drew one: which mon it is the
        # belief's draw, each world its own, D17 G -- so the active, its moves and boosts are not
        # the construction's)
        return [(k, d) for k, d in _side_common("foe", built, truth)
                if k.split(":")[1] in ("condition",)]
    seen = seen - hidden
    if oracle:
        bm, tm = _mons(built), _mons(truth)
        for sp in seen & set(bm) & set(tm):
            b, t = bm[sp], tm[sp]
            keys = ["maxhp", "item", "ability", "base_ability", "last_item", "weight_kg"]
            if t.transform_backup is None:
                keys += list(STATS)
            for k in keys:
                if _norm(k, getattr(b, k)) != _norm(k, getattr(t, k)):
                    out.append((f"foe:{k}", f"{sp} {getattr(b, k)} vs {getattr(t, k)}"))
            bmv = {m.id.lower(): m.pp for m in b.moves if m.id.lower() != "none"}
            tmv = {m.id.lower(): m.pp for m in t.moves if m.id.lower() != "none"}
            if set(bmv) != set(tmv):
                out.append(("foe:moves", f"{sp} {sorted(bmv)} vs {sorted(tmv)}"))
            for mid in set(bmv) & set(tmv):
                if bmv[mid] != tmv[mid]:
                    out.append(("foe:pp", f"{sp} {mid} {bmv[mid]} vs {tmv[mid]}"))
    if _sp(_active(built)) != _sp(_active(truth)) and not (
            _sp(_active(truth)).startswith("zoroark") and _active(truth).hp <= 0 and _active(built).hp <= 0):
        # (a Zoroark fainting in disguise: the log's faint names the disguise -- hidden)
        out.append(("foe:active", f"{_sp(_active(built))} vs {_sp(_active(truth))}"))
    bm, tm = _mons(built), _mons(truth)
    if _tera_used(built) != _tera_used(truth):
        out.append(("foe:tera_used", f"{_tera_used(built)} vs {_tera_used(truth)}"))
    for sp in seen & set(bm) & set(tm):
        b, t = bm[sp], tm[sp]
        fb, ft = b.hp / max(b.maxhp, 1), t.hp / max(t.maxhp, 1)
        if abs(fb - ft) > 0.02 or (b.hp == 0) != (t.hp == 0):
            out.append(("foe:hp", f"{sp} {fb:.3f} vs {ft:.3f}"))
        for k in ("status", "terastallized") if t.hp > 0 else ():  # (a fainted one's: Showdown's last)
            if str(getattr(b, k)).lower() != str(getattr(t, k)).lower():
                out.append((f"foe:{k}", f"{sp} {getattr(b, k)} vs {getattr(t, k)}"))
        if t.hp > 0 and t.terastallized and str(b.tera_type).lower() != str(t.tera_type).lower():
            out.append(("foe:tera_type", f"{sp} {b.tera_type} vs {t.tera_type}"))
        out += _type_diffs("foe", sp, b, t)
    out += _side_common("foe", built, truth)
    return out


def _type_diffs(who: str, sp: str, b, t) -> list[tuple[str, str]]:
    """An alive mon's types and base types (the engine's STAB, immunities, the types a switch-out
    gives back), as sets -- their order and a typeless second do not matter to the engine; not a
    transformed one's (its target's). 2026-10-24, the belief check: a tera'd Pawmot's Fighting
    type lost after a Double Shock -- the types were never compared."""
    if t.hp <= 0 or t.transform_backup is not None:
        return []
    out = []
    for k in ("types", "base_types"):
        bv = {str(x).lower() for x in getattr(b, k)} - {"typeless"}
        tv = {str(x).lower() for x in getattr(t, k)} - {"typeless"}
        if bv != tv:
            out.append((f"{who}:{k}", f"{sp} {sorted(bv)} vs {sorted(tv)}"))
    return out


def field_diffs(built: pe.State, truth: pe.State) -> list[tuple[str, str]]:
    out = []
    for k in ("weather", "weather_turns_remaining", "terrain", "terrain_turns_remaining",
              "trick_room", "trick_room_turns_remaining", "gravity", "magic_room"):  # fmt: skip
        b, t = getattr(built, k, None), getattr(truth, k, None)
        if str(b).lower() != str(t).lower():
            out.append((f"field:{k}", f"{b} vs {t}"))
    return out


def _fainted_no_status(sd: dict) -> dict:
    """Showdown's state with a fainted mon's status "fnt" as none (the engine's; engine_state
    knows none: the engine differential skips those steps)."""
    import copy

    sd = copy.deepcopy(sd)
    for s in sd["sides"]:
        for m in s["mons"]:
            if m.get("status") == "fnt":
                m["status"] = ""
    return sd


def _flip(st: pe.State) -> pe.State:
    """``st`` from side two's point of view (its sides swapped)."""
    one, two, *rest = st.to_string().split("/")
    return pe.State.from_string("/".join([two, one, *rest]))


def _feed(battle: Battle, lines: list[str]) -> None:
    for line in lines:
        split = line.split("|")
        if len(split) < 2 or split[1] in ("", "t:", "gametype", "split", "inactive", "inactiveoff",
                                          "j", "l", "c", "raw", "html", "uhtml"):  # fmt: skip
            continue
        if split[1] in ("win", "tie"):
            continue
        battle.parse_message(split)


def _forme_match(truth: dict, sp: str):
    """The true set of species id ``sp`` -- or of its one forme in the truth (poke-env keeps the
    species a mon came in as: a Mimikyu now Mimikyu-Busted; a Minior-Meteor the truth's core,
    Minior-Yellow -- by the base species, not a prefix)."""
    if sp in truth:
        return truth[sp]
    from alpha_poke.agents.engine_state import GEN

    def base(k: str) -> str:
        return to_id((GEN.pokedex.get(k) or {}).get("baseSpecies") or k)

    formes = [v for k, v in truth.items() if k.startswith(sp) or sp.startswith(k) or base(k) == base(sp)]
    return formes[0] if len(formes) == 1 else None


@contextlib.contextmanager
def _oracle(foe: dict | None):
    """build_state's belief samples of the opponent's mons replaced by their true sets (Showdown's
    ``foe`` side: moves, item, ability, tera, stats): a difference left is our construction's,
    not the belief's (and the hidden parts -- items, abilities, stats, PP -- can be compared).
    None: the belief as is."""
    from alpha_poke.agents import engine_state as es

    if foe is None:
        yield
        return
    inner = es.sample_set
    truth = {SAME_SPECIES.get(m["species"], m["species"]): m for m in foe["mons"]}

    def sample(belief, mon, *a, **kw):
        out = inner(belief, mon, *a, **kw)
        sp = to_id(mon.species)
        t = _forme_match(truth, SAME_SPECIES.get(sp, sp))
        if t is None:
            return out
        own = t.get("transform_backup")
        moves = [x for x, _ in own[2]] if own else [x["id"] for x in t["moves"]]
        st = dict(zip(("atk", "def", "spa", "spd", "spe"), own[0], strict=True)) if own else dict(t["stats"])
        if "powertrick" in (t.get("volatiles") or {}) and not own:  # (its set's: unswapped -- S111)
            st["atk"], st["def"] = st["def"], st["atk"]
        return es.SampledSet(moves=moves, item=t["item"] or "none",
                             ability=t["base_ability"] or t["ability"] or "none",
                             tera=(t["tera_type"] or "typeless").lower(),
                             stats={"hp": t["maxhp"], **st},
                             nature=(t.get("nature") or "serious").lower(),  # (S158)
                             evs=tuple(t["evs"]) if t.get("evs") else None,
                             forme=_true_forme(sp, t, moves))  # fmt: skip

    es.sample_set = sample
    try:
        yield
    finally:
        es.sample_set = inner


def decisions(p1: str, p2: str, seed: int, max_turns: int = 40, sides=("p1", "p2"),
              stats: dict | None = None, oracle: bool = True, script: list | None = None,
              fmt: str | None = None):  # fmt: skip
    """Each decision of a random battle: (step, side, poke-env battle, built state, truth from
    that side's point of view). ``stats``: filled with "decisions" and "errors". ``oracle``: the
    opponent's hidden parts its true set (_oracle), else the belief's samples."""
    from alpha_poke.agents.engine_state import build_state
    from alpha_poke.agents.knowledge_player import remember_own_sets, sync_tera_types

    stats = {} if stats is None else stats
    stats.setdefault("decisions", 0)
    stats.setdefault("errors", [])
    views: dict = {}
    steps, err = random_battle(p1, p2, f"gen5,{seed},{seed + 1},{seed + 2},{seed + 3}", seed + 1,
                               max_turns=max_turns, views=views, script=script,
                               **({"fmt": fmt} if fmt else {}))  # fmt: skip
    if err is not None:
        stats["errors"].append(f"battle: {err[:200]}")
    belief = _belief()
    battles = {}
    pos = {s: 0 for s in sides}
    for k, step in enumerate(steps):
        if "requests" not in step:
            continue
        # (a decision after the turn's end -- a forced switch -- before the next |turn|: the
        # next turn's counters of Future Sight / Wish -- engine_state's, from the state's upkept)
        sd = _fainted_no_status(step["state"])
        try:
            truth = engine_state(sd)
        except BaseException as e:  # noqa: BLE001
            stats["errors"].append(f"truth: {type(e).__name__}: {str(e)[:120]}")
            truth = None
        for side in sides:
            b = battles.get(side)
            if b is None:
                b = battles[side] = Battle(f"battle-gen9customgame-{seed}", side, LOG, gen=9)
                b._player_role = side
                remember_own_sets(b, p1 if side == "p1" else p2)  # (our natures, EVs: the players')
            _feed(b, views[side][pos[side]:step["view_pos"][side]])
            pos[side] = step["view_pos"][side]
            req = step["requests"][side]
            if truth is None or not req or req.get("wait") or req.get("teamPreview"):
                continue
            b.parse_request(req)  # (the server sends the request after the turn's lines)
            sync_tera_types(b)  # (as the players do before every decision)
            stats["decisions"] += 1
            foe = step["state"]["sides"][1 if side == "p1" else 0]
            try:
                names = tuple(belief.display(m.species) for m in
                              (b.teampreview_opponent_team or list(b.opponent_team.values())))
                with _oracle(foe if oracle else None):
                    built = build_state(b, belief, names, random.Random(k))
            except BaseException as e:  # noqa: BLE001
                stats["errors"].append(f"build: {type(e).__name__}: {str(e)[:160]}")
                continue
            yield k, side, b, built, truth if side == "p1" else _flip(truth)


def battle_diffs(p1: str, p2: str, seed: int, max_turns: int = 40, sides=("p1", "p2"),
                 oracle: bool = True, script: list | None = None,
                 fmt: str | None = None) -> tuple[list[tuple], dict]:  # fmt: skip
    """[(step, side, kind, detail)] over a random battle's decisions; and counts ({"decisions",
    "errors": [...]})."""
    out: list = []
    stats: dict = {}
    for k, side, b, built, t in decisions(p1, p2, seed, max_turns, sides, stats, oracle, script, fmt):
        out += [(k, side, kind, detail) for kind, detail in decision_diffs(b, built, t, oracle)]
    return out, stats


def fact_diffs(p1: str, p2: str, seed: int, max_turns: int = 40, sides=("p1", "p2"),
               script: list | None = None, fmt: str | None = None) -> tuple[list[tuple], dict]:  # fmt: skip
    """The belief's own construction (no oracle) against the truth on what it holds as known of
    the foe -- poke-env's / our trackers' facts: an ability it knows (now, its own), an item it
    knows, the moves it saw. Each must be true (2026-10-25: the oracle-mode checks took the true set
    for the foe -- a Worry Seed's Insomnia held as its own ability went unseen). Not what it draws:
    a spread, an unrevealed item are guesses, not facts (the draws' agreement is no test of them --
    a deterministic spread, a 99% prior)."""
    from alpha_poke.agents.pokeview import current_ability, own_ability, own_moves

    out: list = []
    stats: dict = {}
    for k, side, b, built, t in decisions(p1, p2, seed, max_turns, sides, stats, False, script, fmt):
        if "illusion" in _vols(t.side_two) or "illusion" in _vols(built.side_two):
            continue  # (which mon it is the world's draw: foe_diffs')
        hidden = frozenset(_disguised(b, t.side_two))
        bm, tm = _mons(built.side_two), _mons(t.side_two)
        for mon in b.opponent_team.values():
            sp = to_id(mon.species)
            if sp in hidden or sp not in bm or sp not in tm or mon.transformed:
                continue
            bp, tp = bm[sp], tm[sp]
            facts = []
            if own_ability(mon):
                facts.append(("base_ability", own_ability(mon)))
            if current_ability(mon):
                facts.append(("ability", None))
            if mon.item and mon.item != "unknown_item":
                facts.append(("item", None))
            for k2, known in facts:
                tv = _norm(k2, getattr(tp, k2))
                bv = _norm(k2, getattr(bp, k2))
                if bv != tv:
                    out.append((k, side, f"fact:{k2}", f"{sp} {bv} vs {tv}" + (f" (known {known})" if known else "")))
            seen_moves = {m for m in own_moves(mon)}
            tmv = {str(m.id).lower() for m in tp.moves}
            wrong = sorted(m for m in seen_moves if m not in tmv and m not in ("struggle",))
            if wrong and tp.transform_backup is None:
                out.append((k, side, "fact:moves", f"{sp} {wrong} not in {sorted(tmv)}"))
    return out, stats


def _in_order_of(st: pe.State, truth: pe.State) -> pe.State:
    """``st`` with each side's mons in ``truth``'s order (by species; the active, the last switch-in
    and Future Sight's user follow); a side it cannot match, as it is."""
    sides = []
    for a, b in ((st.side_one, truth.side_one), (st.side_two, truth.side_two)):
        have = [SAME_SPECIES.get(_sp(p), _sp(p)) for p in a.pokemon]
        want = [SAME_SPECIES.get(_sp(p), _sp(p)) for p in b.pokemon]
        perm = []  # new index -> old
        for sp in want:
            i = next((j for j, x in enumerate(have) if x == sp and j not in perm), None)
            perm.append(i)
        rest = [j for j in range(len(have)) if j not in perm]
        perm = [i if i is not None else rest.pop(0) for i in perm] if len(rest) == perm.count(None) else None
        if perm is None or perm == list(range(len(have))):
            sides.append(a)
            continue
        new_of = {old: new for new, old in enumerate(perm)}
        kw = {x: getattr(a, x) for x in dir(pe.Side) if not x.startswith("_")}
        kw["pokemon"] = [a.pokemon[i] for i in perm]
        kw["active_index"] = pe.PokemonIndex(str(new_of[int(str(a.active_index))]))
        lu = str(a.last_used_move)
        if lu.startswith("switch:"):
            kw["last_used_move"] = f"switch:{new_of[int(lu[7:])]}"
        if a.future_sight[0] > 0:
            kw["future_sight"] = (a.future_sight[0], pe.PokemonIndex(str(new_of[int(str(a.future_sight[1]))])))
        sides.append(pe.Side(**kw))
    new = pe.State(side_one=sides[0], side_two=sides[1]).to_string().split("/")[:2]
    return pe.State.from_string("/".join(new + st.to_string().split("/")[2:]))


def built_chain(p1: str, p2: str, seed: int, max_turns: int = 40, script: list | None = None,
                fmt: str | None = None, depth: int = 2, every: int = 2) -> tuple[dict, dict]:  # fmt: skip
    """The engine played on from our own construction (p1's, the oracle's sets) along the battle's
    choices, compared with Showdown from its first step (chaindiff.chain_diffs' start): what the
    state holds now is right, what it implies wrong -- a base ability back after a switch-out, a
    lock's options, a move at 0 PP (2026-10-25: the checks compared the decision's state alone, the
    engine's chains began at the truth). ({chain_diffs' counts}, {"decisions", "errors"})."""
    from alpha_poke.enginecheck.chaindiff import chain_diffs

    stats: dict = {}
    from alpha_poke.enginecheck.chaindiff import _with_true_hidden

    # (in the truth's order: the comparison is by slot -- Showdown's team order; ours, poke-env's.
    # The lengths Showdown draws hidden -- confusion's, a lock's, a partial trap's -- the truth's:
    # no player knows them, the chain's own resync after each step takes them so too)
    # (the lock's silent end first: the hidden lengths' sync drops its volatile, not its flags)
    built = {k: _with_true_disguised(_with_true_unseen(_with_true_hidden(_with_true_lock(_in_order_of(st, t), t), t), t),
                                     t, _disguised(b, t.side_two))
             for k, _, b, st, t in decisions(p1, p2, seed, max_turns, ("p1",), stats, True, script, fmt)
             # (an Illusion in disguise -- the truth's, or our construction's guess of one: a shown
             # Cetitan as the Zoroark it may be; the decision checks compare that one)
             if not ({"illusion"} & (_vols(t.side_one) | _vols(t.side_two) | _vols(st.side_one) | _vols(st.side_two)))}  # fmt: skip
    views: dict = {}  # (the same recording: its cache key has views)
    steps, err = random_battle(p1, p2, f"gen5,{seed},{seed + 1},{seed + 2},{seed + 3}", seed + 1,
                               max_turns=max_turns, views=views, script=script,
                               **({"fmt": fmt} if fmt else {}))  # fmt: skip
    r = chain_diffs(steps, depth, every, start=built.get, first=0, rename=_rename_choice, same=_alias)
    return r, stats


def _alias(key: str, ours, theirs) -> bool:
    """Our names for one thing Showdown names otherwise (SAME_SPECIES: Greninja-Bond as Greninja --
    its id, its switch option)."""
    def norm(v):
        s = json.dumps(v, default=str).lower()
        for a, b in SAME_SPECIES.items():
            s = s.replace(a, b)
        return s
    return norm(ours) == norm(theirs)


def _rename_choice(st: pe.State, k: int, choice: str) -> str:
    """A choice as Showdown names it -- a switch's "greninja" -- as the state's mon is named (our
    construction's: Greninja-Bond; or the truth's Greninja-Bond our Greninja), the one whose
    species it is (SAME_SPECIES). (The engine's switch: the species id alone.)"""
    side = st.side_one if k == 0 else st.side_two
    ids = [to_id(p.id) for p in side.pokemon]
    sp = SAME_SPECIES.get(choice, choice)
    if choice in ids or not any(SAME_SPECIES.get(i, i) == sp for i in ids):
        return choice
    return next(i for i in ids if SAME_SPECIES.get(i, i) == sp)


def _with_true_lock(st: pe.State, truth: pe.State) -> pe.State:
    """``st`` with a lock's silent end the truth's: confused already (or Own Tempo), its end shows
    nothing -- whether it is on, Showdown's drawn length (_silent_lock_end; a Zekrom's Outrage
    over after two turns, our state's on for a third)."""
    from alpha_poke.agents.engine_state import _with

    kws = []
    for a, b in ((st.side_one, truth.side_one), (st.side_two, truth.side_two)):
        kw = {x: getattr(a, x) for x in dir(pe.Side) if not x.startswith("_")}
        if _silent_lock_end(a, b):
            kw["volatile_statuses"] = (_vols(a) - {"lockedmove"}) | (_vols(b) & {"lockedmove"})
            off = {m.id.lower(): m.disabled for m in _active(b).moves}
            mons = list(a.pokemon)
            i = int(a.active_index)
            mons[i] = _with(mons[i], moves=[pe.Move(id=m.id, pp=m.pp, disabled=off.get(m.id.lower(), m.disabled))
                                            for m in mons[i].moves])  # fmt: skip
            kw["pokemon"] = mons
        kws.append(pe.Side(**kw))
    new = pe.State(side_one=kws[0], side_two=kws[1]).to_string().split("/")[:2]
    return pe.State.from_string("/".join(new + st.to_string().split("/")[2:]))


def _with_true_disguised(st: pe.State, truth: pe.State, hidden: set[str]) -> pe.State:
    """``st`` with the HP and PP of the foe's mons a Zoroark showed itself as, never found out
    (_disguised) -- and of the Zoroark -- the truth's: the player cannot tell whose they were (a
    Zoroark's Dark Pulse as a Spectrier's: its PP full in our state)."""
    from alpha_poke.agents.engine_state import _with

    if not hidden:
        return st
    a, b = st.side_two, truth.side_two
    tm = _mons(b)
    mons = list(a.pokemon)
    for i, p in enumerate(mons):
        t = tm.get(_sp(p))
        if _sp(p) in hidden and t is not None:
            pp = {m.id.lower(): m.pp for m in t.moves}
            mons[i] = _with(p, hp=t.hp, moves=[pe.Move(id=m.id, pp=pp.get(m.id.lower(), m.pp), disabled=m.disabled)
                                               for m in p.moves])  # fmt: skip
    kw = {x: getattr(a, x) for x in dir(pe.Side) if not x.startswith("_")} | {"pokemon": mons}
    new = pe.State(side_one=st.side_one, side_two=pe.Side(**kw)).to_string().split("/")[:2]
    return pe.State.from_string("/".join(new + st.to_string().split("/")[2:]))


def _with_true_unseen(st: pe.State, truth: pe.State) -> pe.State:
    """``st`` with what no player sees from the truth: a Substitute's HP after a hit (the log does
    not show it -- the state checks skip it too)."""
    kws = []
    for a, b in ((st.side_one, truth.side_one), (st.side_two, truth.side_two)):
        kw = {x: getattr(a, x) for x in dir(pe.Side) if not x.startswith("_")}
        if "substitute" in _vols(a) and "substitute" in _vols(b):
            kw["substitute_health"] = b.substitute_health
        kws.append(pe.Side(**kw))
    new = pe.State(side_one=kws[0], side_two=kws[1]).to_string().split("/")[:2]
    return pe.State.from_string("/".join(new + st.to_string().split("/")[2:]))


def decision_diffs(b, built, t, sets: bool) -> list[tuple[str, str]]:
    """One decision's built state against the truth (both from the player's side): [(kind,
    detail)]; ``sets``: the foe's revealed mons' sets too (item, abilities, stats, moves, PP)."""
    out: list = []
    seen = {to_id(m.species) for m in b.opponent_team.values()}
    # (a pivot's switch: force_switch, as the search needs it -- the differential's states
    # leave it off; a fainted active: off, the engine switches it anyway)
    req = b.last_request or {}
    want = bool(req.get("forceSwitch")) and _active(built.side_one).hp > 0
    if built.side_one.force_switch != want:
        out.append(("own:force_switch", f"{built.side_one.force_switch} vs {want}"))
    diffs = own_diffs(built.side_one, t.side_one)
    recharge = any(m.get("id") == "recharge" for m in ((req.get("active") or [{}])[0].get("moves") or []))
    if want or req.get("forceSwitch") or recharge:
        # (a switch decision -- the active leaves -- or a recharge: its moves' flags are its
        # last move request's in Showdown, whatever the lock since; nothing reads them now)
        act = _sp(_active(built.side_one))
        diffs = [(k2, d) for k2, d in diffs if not (k2 == "own:disabled" and d.startswith(act + " "))]
    for kind, detail in (diffs
                         + foe_diffs(built.side_two, t.side_two, seen, sets,
                                     frozenset(_disguised(b, t.side_two)))
                         + field_diffs(built, t)
                         + ([] if want or req.get("forceSwitch") else option_diffs(b, built, t))):  # fmt: skip
        out.append((kind, detail))
    return out


def _silent_lock_end(built: pe.Side, truth: pe.Side) -> bool:
    """A lock's end when it was confused already, or with Own Tempo -- no confusion: silent,
    hidden (the lock's moves and its options, the built side's)."""
    bv, tv = _vols(built), _vols(truth)
    return ("confusion" in bv & tv or str(_active(truth).ability).lower() == "owntempo") \
        and "lockedmove" in bv ^ tv


def option_diffs(b, built, t) -> list[tuple[str, str]]:
    """Plan C's round trip (agents/slots): the built state's options by name are the true
    state's, and each one is an order of the battle (poke-env's request). Not at a switch
    decision (the true states leave force_switch off)."""
    from poke_env.player import Player

    from alpha_poke.agents import slots

    if _silent_lock_end(built.side_one, t.side_one):
        return []
    ours, truth = slots.names(built), slots.names(t)
    out = []
    # (Greninja-Bond as Greninja: the true states' name, Showdown's details -- as the comparator)
    a = {n.replace("switch greninjabond", "switch greninja") for n in ours if n}
    z = {n.replace("switch greninjabond", "switch greninja") for n in truth if n}
    if a != z:
        out.append(("options", f"{sorted(a - z)} vs {sorted(z - a)}"))
    none = [n for n in ours if n and slots.order_of(Player, b, n) is None]
    if none:
        out.append(("options:order", f"{none}"))
    return out
