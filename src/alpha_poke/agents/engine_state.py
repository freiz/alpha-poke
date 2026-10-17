"""poke-env battle -> poke-engine State (MIT-licensed Rust engine used as our forward model).

Our side is exact (request data). The opponent's hidden information is *sampled* from our belief
model: for every opposing mon, revealed facts are kept and the rest (moves to 4, item, ability,
tera type) is drawn from the species' set-archetype posterior given what has been revealed (or
the marginal prior when no archetypes exist); stats come from the species' common spread. Calling
``build_state`` several times gives several determinizations for root-parallel search.

Written from the poke-engine API (poke_engine.pyi) and poke-env; no Foul Play code is used.
"""

import random
from dataclasses import dataclass

import numpy as np
import poke_engine as pe
from poke_env.battle import Effect, Field, SideCondition, Status, Weather
from poke_env.battle.move import Move
from poke_env.data import GenData

from alpha_poke.agents.belief_state import BeliefModel, _preview_name, ability_probs
from alpha_poke.agents.damage import calc_stats
from alpha_poke.agents.speed import battle_observations, consistent, spread_dist
from alpha_poke.agents.timers import SideTimers, battle_timers
from alpha_poke.analysis.roles import to_id

GEN = GenData.from_gen(9)
STATUS = {
    Status.BRN: "burn",
    Status.PAR: "paralyze",
    Status.PSN: "poison",
    Status.TOX: "toxic",
    Status.SLP: "sleep",
    Status.FRZ: "freeze",
}
WEATHER = {
    Weather.SUNNYDAY: "sun",
    Weather.RAINDANCE: "rain",
    Weather.SANDSTORM: "sand",
    Weather.SNOWSCAPE: "snow",
    Weather.HAIL: "hail",
    Weather.DESOLATELAND: "harshsun",
    Weather.PRIMORDIALSEA: "heavyrain",
}
TERRAIN = {
    Field.ELECTRIC_TERRAIN: "electricterrain",
    Field.GRASSY_TERRAIN: "grassyterrain",
    Field.MISTY_TERRAIN: "mistyterrain",
    Field.PSYCHIC_TERRAIN: "psychicterrain",
}
# volatile statuses we carry over (names as the engine spells them)
VOLATILE = {
    Effect.SUBSTITUTE: "substitute",
    Effect.LEECH_SEED: "leechseed",
    Effect.CONFUSION: "confusion",
    Effect.TAUNT: "taunt",
    Effect.ENCORE: "encore",
    Effect.YAWN: "yawn",
    Effect.SALT_CURE: "saltcure",
}
# Protosynthesis / Quark Drive boosts (Booster Energy, sun, Electric Terrain)
BOOSTS = {e: e.name.lower() for e in Effect
          if e.name.startswith(("PROTOSYNTHESIS", "QUARKDRIVE"))
          and e.name not in ("PROTOSYNTHESIS",)}  # fmt: skip
# more volatiles the engine models (most common: typechange (Protean / Libero), healblock
# (Psychic Noise)); the engine ends heal block, magnet rise and throat chop, the others last until
# a switch in the search
BOOSTS |= {getattr(Effect, n): n.replace("_", "").lower() for n in (
    "TYPECHANGE", "HEAL_BLOCK", "CHARGE", "FLASH_FIRE", "CURSE", "MAGNET_RISE", "THROAT_CHOP",
    "FOCUS_ENERGY", "SMACK_DOWN", "ATTRACT", "NO_RETREAT", "TAR_SHOT", "AQUA_RING", "INGRAIN",
    "GLAIVE_RUSH", "OCTOLOCK", "TORMENT", "GASTRO_ACID", "SYRUP_BOMB")}  # fmt: skip
# partial trapping (doc/engine-diff.md L2c, 2026-10-16: left out until then -- the search did not
# see the trapped mon unable to switch nor its 1/8 per turn): poke-env names it after the move
BOOSTS |= {getattr(Effect, n): "partiallytrapped" for n in (
    "BIND", "WRAP", "FIRE_SPIN", "WHIRLPOOL", "SAND_TOMB", "MAGMA_STORM", "INFESTATION",
    "SNAP_TRAP", "THUNDER_CAGE", "CLAMP", "PARTIALLY_TRAPPED") if hasattr(Effect, n)}  # fmt: skip
_MOVES = GEN.moves
PERISH = {getattr(Effect, f"PERISH{n}"): n for n in (1, 2, 3)}
SCREENS = {"reflect", "lightscreen", "auroraveil"}
# the weather (its -weather id) / terrain an item extends to 8 turns
EXTENDERS = {"sunnyday": "heatrock", "raindance": "damprock", "sandstorm": "smoothrock",
             "snow": "icyrock", "snowscape": "icyrock", "hail": "icyrock"}  # fmt: skip


def _types(mon) -> tuple[str, str]:
    # the non-tera types: the engine keeps them when terastallized, STAB on them (tera_type
    # apart: has_type reads only it), as Showdown's getTypes(false, true) (L31)
    ts = [t.name.lower() for t in mon.base_types if t is not None]
    return (ts + ["typeless", "typeless"])[0], (ts + ["typeless", "typeless"])[1]


def _base_types(species: str) -> tuple[str, str]:
    entry = GEN.pokedex.get(species) or {}
    ts = [t.lower() for t in entry.get("types", [])] or ["normal"]
    return ts[0], (ts + ["typeless"])[1]


def _tera(mon) -> str:
    t = mon.tera_type
    return t.name.lower() if t is not None else "typeless"


def _remaining(start_turn: int | None, turn: int, length: int = 5) -> int:
    if start_turn is None:
        return length
    return max(1, length - max(0, turn - start_turn))


@dataclass
class SampledSet:
    moves: list[str]
    item: str
    ability: str
    tera: str
    stats: dict[str, int]


@dataclass
class KnownSet:
    """What a player knows of its own mon although the battle has not shown it yet (training
    positions from replays: everything the mon revealed during the whole game)."""

    moves: list[str]  # move ids
    item: str | None = None  # item id (the original item)
    ability: str | None = None
    tera: str | None = None  # tera type, lower case


@dataclass
class SpectatorSide:
    """Side one rebuilt from a spectator log (design D13): the full team in preview order
    (poke-env mons, for those not yet on the field fresh preview mons) and per species id the
    game-wide known parts of its set; the rest is sampled from the belief."""

    team: list
    known: dict[str, KnownSet]
    names: tuple[str, ...]  # belief team names of this side


_PRIORS: dict = {}  # (belief, species, team) -> Dist


def _prior(belief: BeliefModel, species: str, team_names: tuple[str, ...]):
    """``belief.prior.predict``, cached: deterministic, and the same mon and team at every world
    of every decision (2026-10-11: 14% of a policy-only worker). Read-only for the callers."""
    key = (id(belief), species, team_names)
    dist = _PRIORS.get(key)
    if dist is None:
        if len(_PRIORS) > 20_000:  # (a few KB each: bounded)
            _PRIORS.clear()
        dist = _PRIORS[key] = belief.prior.predict(species, team_names)
    return dist


def sample_set(
    belief: BeliefModel,
    mon,
    team_names: tuple[str, ...],
    rng: random.Random,
    move_beta: float = 0.0,
    known: KnownSet | None = None,
    temp: float = 1.0,
    speed_obs: list | None = None,
):
    """One plausible full set for an opposing mon, consistent with what it revealed (and with
    ``known``: game-wide facts about the mon, used for side one of replay positions).
    ``temp`` > 1 flattens every draw (weights ** (1 / temp)): more varied sets than the belief
    itself, for completing self-play teams (design D5: completion must not be exactly what the
    search's belief expects). temp = 1 is the belief as is.
    Moves: from the sampled (species-level) archetype; with ``move_beta`` > 0 the archetype's
    move weights are multiplied by the team-conditioned move marginal ** move_beta (the archetype
    ignores the opponent's team; the team prior is much sharper: time-split coverage of later
    revealed moves 61.7% -> 77.3% / 81.1% / 82.6% at beta 1 / 2 / 3, design D11)."""
    species = _preview_name(mon, team_names)
    dist = _prior(belief, species, team_names)
    revealed = [m for m in mon.moves if m in _MOVES]
    ss = belief.sets.get(species)
    # poke-env: "unknown_item" = not seen yet; None = gone (eaten, knocked off, used up: its
    # end_item) -- no item now (2026-10-11: a gone item was sampled again, so an eaten berry or
    # knocked-off Boots came back in every search)
    gone = mon.item is None
    item = mon.item if mon.item not in (None, "unknown_item") else None
    tera = _tera(mon) if mon.is_terastallized else None
    if known is not None:
        revealed += [m for m in known.moves if m in _MOVES and m not in revealed]
        if item is None and known.item and not gone:
            item = known.item
        if tera is None and known.tera:
            tera = known.tera

    def flat(w):
        """weights ** (1 / temp) (identity at temp 1)"""
        if temp == 1.0:
            return w
        if isinstance(w, dict):
            return {key: v ** (1 / temp) for key, v in w.items()}
        return np.asarray(w, dtype=float) ** (1 / temp)

    k = None
    if ss is not None and ss.params:
        names = {to_id(n): n for n in ss.vocab["move"]}
        item_name = next((n for n in ss.vocab["item"] if to_id(n) == item), None) if item else None
        post = flat(ss.posterior(item=item_name, moves=[names.get(m, m) for m in revealed]))
        k = int(np.searchsorted(np.cumsum(post), rng.random() * post.sum()))
        k = min(k, len(post) - 1)

    def draw(attr, fallback: dict[str, float]):
        if k is not None and ss.vocab.get(attr):
            w = flat(ss.params[attr][k])
            if w.sum() > 0:
                i = int(np.searchsorted(np.cumsum(w), rng.random() * w.sum()))
                return to_id(ss.vocab[attr][min(i, len(w) - 1)])
        if fallback:
            keys, ws = zip(*flat(fallback).items(), strict=True)
            if sum(ws) > 0:
                return to_id(rng.choices(keys, weights=ws)[0])
        return None

    item_seen = gone or item is not None
    if gone:
        item = "none"
    elif item is None:
        item = draw("item", dist.item) or "none"
    if tera is None:
        tera = draw("tera", dist.tera) or _tera(mon)
    ability = to_id(mon.ability) if mon.ability else None
    if ability is None and known is not None and known.ability:
        ability = known.ability
    if ability is None:
        ap = flat(ability_probs(mon))
        ability = (rng.choices(list(ap), weights=list(ap.values()))[0] if ap else None) or "none"
    # moves: revealed + draws (without replacement) from the archetype's move weights
    moves = list(revealed)[:4]
    if k is not None and ss.vocab.get("move"):
        weights = {
            to_id(n): float(w) for n, w in zip(ss.vocab["move"], ss.params["move"][k], strict=False)
        }
        if move_beta > 0:
            weights = {mid: w * dist.move.get(mid, 1e-4) ** move_beta for mid, w in weights.items()}
    else:
        weights = dict(dist.move)
    weights = flat(weights)
    for mid in list(weights):
        if mid in moves or mid not in _MOVES:
            weights.pop(mid)
    while len(moves) < 4 and weights:
        keys, ws = zip(*weights.items(), strict=True)
        if sum(ws) <= 0:
            break
        pick = rng.choices(keys, weights=ws)[0]
        moves.append(pick)
        weights.pop(pick)
    spread = None
    if speed_obs is not None:  # the spread sampled, consistent with the order
        spread, item = _sample_spread(mon, item, item_seen, speed_obs, dist, rng)
    if spread is None:
        spread = belief.spread_for(mon.species)
    stats = calc_stats(mon.base_stats, spread, level=mon.level or 100)
    return SampledSet(moves or ["tackle"], item, ability, tera, stats)


_SPREAD_SPEEDS: dict = {}  # (species, level) -> the speed stat of each usage spread


def _sample_spread(mon, item: str, item_seen: bool, obs: list, dist, rng) -> tuple:
    """(spread, item): a usage spread (agents/speed.py) consistent with the turns this mon moved
    before or after ours; if none is with the sampled item and the item is not known, with a
    Choice Scarf (if the species may hold one). (None, item) without usage spreads; the
    unconstrained draw if nothing fits (an effect the observations miss)."""
    spreads, ws = spread_dist(mon.species)
    if not spreads:
        return None, item
    level = mon.level or 100
    if obs:
        key = (to_id(mon.species), level)
        speeds = _SPREAD_SPEEDS.get(key)
        if speeds is None:
            speeds = [calc_stats(mon.base_stats, s, level=level)["spe"] for s in spreads]
            _SPREAD_SPEEDS[key] = speeds
        for it in (item,) if item_seen else (item, "choicescarf"):
            if it == "choicescarf" and it != item and dist.item.get("choicescarf", 0) <= 0:
                continue
            ok = [i for i, sp in enumerate(speeds) if consistent(obs, sp, it)]
            if ok:  # by usage; uniform if the fitting spreads all have zero usage weight
                w = [ws[j] for j in ok]
                i = rng.choices(ok, weights=w if sum(w) > 0 else None)[0]
                return spreads[i], it
    return rng.choices(spreads, weights=ws)[0], item


def _boosts(mon) -> dict:
    b = mon.boosts
    return {
        "attack_boost": b.get("atk", 0),
        "defense_boost": b.get("def", 0),
        "special_attack_boost": b.get("spa", 0),
        "special_defense_boost": b.get("spd", 0),
        "speed_boost": b.get("spe", 0),
        "accuracy_boost": b.get("accuracy", 0),
        "evasion_boost": b.get("evasion", 0),
    }


def _side_conditions(sc: dict, turn: int, toxic: int = 0, protect: int = 0,
                     clay: frozenset = frozenset()) -> pe.SideConditions:  # fmt: skip
    """``clay``: the screens (reflect, lightscreen, auroraveil) set by a Light Clay holder: 8
    turns."""
    return pe.SideConditions(
        toxic_count=toxic,
        protect=protect,
        spikes=sc.get(SideCondition.SPIKES, 0),
        toxic_spikes=sc.get(SideCondition.TOXIC_SPIKES, 0),
        stealth_rock=int(SideCondition.STEALTH_ROCK in sc),
        sticky_web=int(SideCondition.STICKY_WEB in sc),
        reflect=_remaining(sc.get(SideCondition.REFLECT), turn, 8 if "reflect" in clay else 5)
        if SideCondition.REFLECT in sc
        else 0,
        light_screen=(
            _remaining(sc.get(SideCondition.LIGHT_SCREEN), turn, 8 if "lightscreen" in clay else 5)
            if SideCondition.LIGHT_SCREEN in sc
            else 0
        ),
        aurora_veil=(
            _remaining(sc.get(SideCondition.AURORA_VEIL), turn, 8 if "auroraveil" in clay else 5)
            if SideCondition.AURORA_VEIL in sc
            else 0
        ),
        tailwind=(
            _remaining(sc.get(SideCondition.TAILWIND), turn, 4)
            if SideCondition.TAILWIND in sc
            else 0
        ),
    )


def _volatiles(mon) -> set[str]:
    return {name for eff, name in VOLATILE.items() if eff in mon.effects}


def _base_ability(mon, ability: str, tm: SideTimers | None) -> str:
    """The engine's base ability: none for a once-per-battle switch-in ability already used
    (Dauntless Shield; the patched engine then raises Defense no more, doc/engine-diff.md L18)."""
    if tm is not None and ability == "dauntlessshield" and to_id(mon.species) in tm.used_once:
        return "none"
    return ability


def _sleep(mon, tm: SideTimers | None) -> dict:
    """rest_turns / sleep_turns of an asleep mon (timers), else nothing."""
    if tm is None or STATUS.get(mon.status) != "sleep":
        return {}
    rest, sleep = tm.rest_sleep(to_id(mon.species))
    return {"rest_turns": rest, "sleep_turns": sleep}


def _our_mon(
    mon,
    available_moves: set[str] | None,
    tm: SideTimers | None = None,
    req_pp: dict | None = None,
    revived: bool = False,
) -> pe.Pokemon:
    """``req_pp``: the request's PP of the active's moves (exact; poke-env counts uses itself and
    drifts low over long games: 2026-10-11, a move with PP left was 0 in the engine, no legal
    option); a move the request offers has PP. ``revived``: a fainted mon brought back at half
    HP (Revival Blessing's choice)."""
    stats = mon.stats or {}
    moves = []
    for mid, mv in list(mon.moves.items())[:4]:
        disabled = available_moves is not None and mid not in available_moves
        pp = max(0, mv.current_pp)
        if req_pp and req_pp.get(mid) is not None:
            pp = int(req_pp[mid])
        if available_moves is not None and mid in available_moves:
            pp = max(pp, 1)
        moves.append(pe.Move(id=mid, pp=pp, disabled=disabled))
    hp = 0 if mon.fainted else int(mon.current_hp or 0)
    if revived:
        hp = max(1, int(mon.max_hp or 2) // 2)
    return pe.Pokemon(
        id=mon.species,
        level=mon.level or 100,
        types=_types(mon),
        base_types=_base_types(mon.species),
        hp=hp,
        maxhp=int(mon.max_hp or 1),
        ability=to_id(mon.ability) if mon.ability else "none",
        base_ability=_base_ability(mon, to_id(mon.ability) if mon.ability else "none", tm),
        item=mon.item or "none",
        attack=int(stats.get("atk") or 100),
        defense=int(stats.get("def") or 100),
        special_attack=int(stats.get("spa") or 100),
        special_defense=int(stats.get("spd") or 100),
        speed=int(stats.get("spe") or 100),
        status="none" if revived else STATUS.get(mon.status, "none"),
        weight_kg=float(mon.weight or 0.0),
        moves=moves,
        terastallized=mon.is_terastallized,
        tera_type=_tera(mon),
        **_sleep(mon, tm),
    )


def _pp(mon, mid: str) -> int:
    """The PP of an opponent's move: poke-env counts its uses (Pressure included; not the turns
    of a locked move) of a revealed move; an unrevealed one has its maximum (PP Ups)."""
    mv = mon.moves.get(mid)
    if mv is not None:
        # poke-env also counts a move Sleep Talk calls (it costs no PP): a Sleep Talk user's
        # moves keep at least 1
        return max(1 if "sleeptalk" in mon.moves else 0, mv.current_pp)
    return Move(mid, gen=9).max_pp if mid in _MOVES else 16


def _their_mon(mon, s: SampledSet, tm: SideTimers | None = None,
               disabled: str | None = None) -> pe.Pokemon:  # fmt: skip
    """The moves' PP from their uses; ``disabled``: the move Disable blocks."""
    maxhp = s.stats["hp"]
    if mon.fainted:
        hp = 0
    elif not mon.max_hp:
        # never on the field (team preview only): poke-env reports an HP fraction of 0; the
        # mon is at full HP (before 2026-10-06 this gave it 1 HP in every search)
        hp = maxhp
    else:
        hp = max(1, round(mon.current_hp_fraction * maxhp))
    return pe.Pokemon(
        id=mon.species,
        level=mon.level or 100,
        types=_types(mon),
        base_types=_base_types(mon.species),
        hp=hp,
        maxhp=maxhp,
        ability=s.ability,
        base_ability=_base_ability(mon, s.ability, tm),
        item=s.item,
        attack=s.stats["atk"],
        defense=s.stats["def"],
        special_attack=s.stats["spa"],
        special_defense=s.stats["spd"],
        speed=s.stats["spe"],
        status=STATUS.get(mon.status, "none"),
        weight_kg=float(mon.weight or 0.0),
        moves=[pe.Move(id=m, pp=_pp(mon, m), disabled=m == disabled) for m in s.moves[:4]],
        terastallized=mon.is_terastallized,
        tera_type=s.tera,
        **_sleep(mon, tm),
    )


def _transform_target(battle, team: dict, mon, other: dict) -> int | None:
    """The index in ``other`` (the opposing team's mons, a list of keys) of the mon ``mon`` (a
    value of ``team``) last transformed into (|-transform|; Imposter or the move), if
    ``mon.transformed``."""
    if mon is None or not mon.transformed:
        return None
    key = next((k for k, m in team.items() if m is mon), None)
    for ev in reversed(battle._replay_data):
        if len(ev) > 3 and ev[1] == "-transform":
            src, into = (x[:2] + x[3:] if len(x) > 3 and x[3] != " " else x for x in ev[2:4])
            if src == key:
                return other.index(into) if into in other else None
    return None


def _with(p: pe.Pokemon, **kw) -> pe.Pokemon:
    """A copy of ``p`` with ``kw`` changed (pe.Pokemon is immutable)."""
    keys = ("id", "level", "types", "base_types", "hp", "maxhp", "ability", "base_ability",
            "item", "attack", "defense", "special_attack", "special_defense", "speed", "status",
            "weight_kg", "moves", "terastallized", "tera_type", "rest_turns",
            "sleep_turns")  # fmt: skip
    return pe.Pokemon(**({k: getattr(p, k) for k in keys} | kw))


def _illusion(theirs: list, opp_active, revealed: dict, rng: random.Random) -> int | None:
    """The index in ``theirs`` of an opponent's Zoroark that may be the active in disguise
    (Illusion; design D17 G, 2026-10-13): in the team (preview), never seen (not among the
    revealed mons), alive, the active not a Zoroark; this world draws it with probability one
    over the alive mons (each switch-in as likely). None otherwise (no random draw: the worlds
    of battles without one are as before)."""
    if opp_active is None or to_id(opp_active.species).startswith("zoroark"):
        return None
    shown = set(revealed.values())
    zi = next((i for i, m in enumerate(theirs) if to_id(m.species).startswith("zoroark")
               and m not in shown and not m.fainted), None)  # fmt: skip
    if zi is None:
        return None
    alive = sum(1 for m in theirs if not m.fainted)
    return zi if rng.random() < 1 / max(alive, 1) else None


def _as_transformed(p: pe.Pokemon, target: pe.Pokemon, moves: list) -> pe.Pokemon:
    """``p`` transformed into ``target`` (Showdown's transformInto): the target's species, types,
    ability, stats except HP, weight and ``moves``; its own HP, level, item, status, tera and
    base types / ability (what a switch restores in the engine)."""
    return pe.Pokemon(
        id=target.id, level=p.level, types=target.types, base_types=p.base_types, hp=p.hp,
        maxhp=p.maxhp, ability=target.ability, base_ability=p.base_ability, item=p.item,
        attack=target.attack, defense=target.defense, special_attack=target.special_attack,
        special_defense=target.special_defense, speed=target.speed, status=p.status,
        weight_kg=target.weight_kg, moves=moves, terastallized=p.terastallized,
        tera_type=p.tera_type, rest_turns=p.rest_turns, sleep_turns=p.sleep_turns,
    )  # fmt: skip


def _last_move(mon, engine_mon, avail: set[str] | None = None) -> tuple[dict, set[str]]:
    """(``last_used_move`` Side kwarg, volatiles) for an active mon. The engine panics on an
    Encore without a last used move, so Encore is dropped when we cannot tell the move."""
    vol = _volatiles(mon) if mon is not None else set()
    if mon is None or engine_mon is None:
        vol.discard("encore")
        return {}, vol
    ids = [m.id for m in engine_mon.moves]
    idx = next(
        (ids.index(mid) for mid, mv in mon.moves.items() if mv.is_last_used and mid in ids), None
    )
    if idx is None and "encore" in vol and avail is not None and len(avail) == 1:
        (only,) = avail  # we are encored: the request offers only the encored move
        idx = ids.index(only) if only in ids else None
    if idx is None:
        vol.discard("encore")
        return {}, vol
    return {"last_used_move": f"move:{idx}"}, vol


def _counts(tm: SideTimers, active) -> tuple[int, int]:
    """(toxic_count, protect) of a side's active (timers)."""
    # Showdown's toxic stage stops at 15: the engine's damage is (count + 1) / 16
    toxic = min(tm.toxic, 14) if active is not None and STATUS.get(active.status) == "toxic" else 0
    return toxic, tm.protect


def _timed(tm: SideTimers, active, mons: list, engine_mons: list, vol: set[str]) -> dict:
    """pe.Side kwargs: the pending Wish (turns, half the wisher's max HP), the pending Future
    Sight (turns, its user's slot) and the active's
    volatile durations (only of volatiles it has; clamped to what the engine accepts)."""
    out = {}
    if tm.wish is not None:
        idx = next((i for i, m in enumerate(mons) if to_id(m.species) == tm.wish[1]),
                   next((i for i, m in enumerate(mons) if m is active), None))  # fmt: skip
        if idx is not None and idx < len(engine_mons):
            out["wish"] = (tm.wish[0], engine_mons[idx].maxhp // 2)
    if tm.future is not None:
        idx = next((i for i, m in enumerate(mons) if to_id(m.species) == tm.future[1]), None)
        if idx is not None:
            out["future_sight"] = (tm.future[0], pe.PokemonIndex(str(idx)))
    dur = {}
    # (the patched engine ends heal block, magnet rise and throat chop too; a partial trap at its
    # fifth end of turn: at 4 it ends at the next, right for Showdown's 5 and, at 4 or 5, its 6)
    tops = [("confusion", 4), ("taunt", 2), ("encore", 2), ("yawn", 1), ("healblock", 1),
            ("magnetrise", 4), ("throatchop", 1), ("partiallytrapped", 4)]  # fmt: skip
    for name, top in tops:
        n = getattr(tm, name)
        if name in vol and n:
            dur[name] = min(n, top)
    if dur:
        out["volatile_status_durations"] = pe.VolatileStatusDurations(**dur)
    return out


def _pad(mons: list) -> list:
    return (mons + [pe.Pokemon.create_fainted() for _ in range(6)])[:6]


def build_state(
    battle,
    belief: BeliefModel,
    team_names: tuple[str, ...],
    rng: random.Random,
    move_beta: float = 0.0,
    spectator: SpectatorSide | None = None,
    force_switch: bool | None = None,
    revived: str | None = None,
) -> pe.State:
    """One determinization of the current battle (side_one = us): the opponent's sets sampled
    from the belief, consistent with what they revealed. With ``spectator`` side
    one comes from a spectator log (no request): built like the opponent, from the known parts
    of each set plus belief samples (training positions, design D13). ``force_switch`` overrides
    side one's switch request (training positions of forced / pivot switches; a spectator log
    has no request). What the engine models of the battle (design D17): the turn counters
    (agents/timers.py), gone items staying gone, boosts and volatiles, the request's PP, the
    opponent's PP from its uses, the opponent's spread consistent with the move order
    (agents/speed.py), Transform, Illusion, extending items, a hit Substitute.
    ``revived``: our mon of this species back at half HP (the states of a Revival Blessing
    choice)."""
    turn = battle.turn
    active = battle.active_pokemon
    role = battle.player_role or "p1"
    # turn counters from the log (timers.py); off: every counter 0, as before 2026-10-11 (A/B)
    tms = battle_timers(battle)
    tm_us, tm_them = tms[role], tms["p2" if role == "p1" else "p1"]
    if spectator is None:
        ours = list(battle.team.values())
        avail = {m.id for m in battle.available_moves} if battle.available_moves else None
        req = battle.last_request or {}
        act = (req.get("active") or [{}])[0]
        req_pp = {to_id(m["id"]): m.get("pp") for m in act.get("moves", []) if "id" in m}
        our_mons = [
            _our_mon(m, avail if m is active else None, tm_us,
                     req_pp if m is active else None, revived == to_id(m.species))
            for m in ours
        ]  # fmt: skip
    else:
        ours, avail = spectator.team, None
        our_mons = []
        for m in ours:
            s = sample_set(
                belief,
                m,
                spectator.names,
                rng,
                move_beta,
                spectator.known.get(to_id(m.species)),
            )
            # known moves come first in sample_set; in a real battle our moves are in moveset
            # order, unrelated to use: shuffle so the slot does not leak which move gets used
            rng.shuffle(s.moves)
            our_mons.append(_their_mon(m, s, tm_us))
    our_idx = next((i for i, m in enumerate(ours) if m is active), 0)
    if battle.force_switch or (active is not None and active.fainted):
        our_idx = next((i for i, m in enumerate(ours) if m.active), our_idx)

    theirs = list(battle.opponent_team.values())
    seen = {to_id(m.species) for m in theirs}
    for m in battle.teampreview_opponent_team or []:  # not yet revealed: preview mons
        if to_id(m.species) not in seen and len(theirs) < 6:
            base = to_id(m.species.split("-")[0])
            if not any(to_id(t.species).startswith(base) for t in theirs):
                theirs.append(m)
    opp_active = battle.opponent_active_pokemon

    # the opponent's speed: usage spreads consistent with the observed move order
    obs = battle_observations(battle) if spectator is None else None
    their_sets = [sample_set(belief, m, team_names, rng, move_beta,
                             speed_obs=None if obs is None else obs.get(to_id(m.species), []))
                  for m in theirs]  # fmt: skip
    their_mons = [_their_mon(m, st, tm_them, tm_them.disabled if m is opp_active else None)
                  for m, st in zip(theirs, their_sets, strict=True)]  # fmt: skip
    their_idx = next((i for i, m in enumerate(theirs) if m is opp_active), 0)
    our_active_idx = next((i for i, m in enumerate(ours) if m is active), None)
    zi = _illusion(theirs, opp_active, battle.opponent_team, rng)
    if zi is not None:  # the active is the Zoroark: what is shown (HP fraction, status) is its
        z = their_mons[zi]
        their_mons[zi] = _with(z, hp=max(1, round(opp_active.current_hp_fraction * z.maxhp)),
                               status=STATUS.get(opp_active.status, "none"))  # fmt: skip
        their_idx = zi
    transformed = any(m is not None and m.transformed for m in (active, opp_active))
    our_tf = their_tf = False
    if spectator is None and transformed:  # a transformed active (D17 J; 2026-10-13)
        their_keys = [next((k for k, v in battle.opponent_team.items() if v is m), None)
                      for m in theirs]  # fmt: skip
        our_keys = list(battle.team)
        t = _transform_target(battle, battle.team, active, their_keys)
        if t is not None and our_active_idx is not None and t < len(their_mons):
            # our moves are the request's (the target's real moves, 5 PP each)
            moves = [pe.Move(id=to_id(m["id"]), pp=int(m.get("pp") or 0),
                             disabled=avail is not None and to_id(m["id"]) not in avail)
                     for m in act.get("moves", [])[:4] if "id" in m]  # fmt: skip
            our_mons[our_active_idx] = _as_transformed(
                our_mons[our_active_idx], their_mons[t], moves or their_mons[t].moves
            )
            our_tf = True
        t = _transform_target(battle, battle.opponent_team, opp_active, our_keys)
        if t is not None and their_mons and t < len(our_mons):
            moves = [pe.Move(id=m.id, pp=5) for m in our_mons[t].moves]
            their_mons[their_idx] = _as_transformed(their_mons[their_idx], our_mons[t], moves)
            their_tf = True
    our_last, our_vol = _last_move(
        active, our_mons[our_active_idx] if our_active_idx is not None else None, avail
    )
    their_last, their_vol = _last_move(opp_active, their_mons[their_idx] if their_mons else None)
    # the engine's transform / typechange volatiles (doc/engine-diff.md L36): a switch ends the
    # transformation, and an Imposter does not transform again while it is on
    for tf, vol in ((our_tf, our_vol), (their_tf, their_vol)):
        if tf:
            vol |= {"transform", "typechange"}
    # the actives' Protosynthesis / Quark Drive boosts and other volatiles (BOOSTS)
    for mon, vol in ((active, our_vol), (opp_active, their_vol)):
        vol |= {BOOSTS[e] for e in (mon.effects if mon is not None else ()) if e in BOOSTS}
    # must recharge (the engine offers no move), Perish Song's count
    for mon, vol, tm in ((active, our_vol, tm_us), (opp_active, their_vol, tm_them)):
        if mon is None:
            continue
        if tm.recharge:  # (not poke-env's must_recharge: it outlives the recharge turn)
            vol.add("mustrecharge")
        # Showdown starts perish3, perish2, ... without ending the previous count: poke-env keeps
        # them all, the lowest is current
        counts = [n for e, n in PERISH.items() if e in mon.effects]
        if counts:
            vol.add(f"perish{min(counts)}")
    # the items of the mons that set a screen / the weather / the terrain (ours known, theirs
    # this world's sample): an extending item makes it 8 turns
    items = {("us", to_id(m.species)): (m.item or "") for m in ours} if spectator is None else {}
    items |= {("them", to_id(m.species)): st.item for m, st in zip(theirs, their_sets, strict=True)}
    clay_us, clay_them = (
        frozenset(k for k, sp in tm.setters.items()
                  if k in SCREENS and items.get((who, sp)) == "lightclay")
        for who, tm in (("us", tm_us), ("them", tm_them))
    )  # fmt: skip
    ext = {}
    for who, tm in (("us", tm_us), ("them", tm_them)):
        for kind in ("weather", "terrain"):
            if kind in tm.setters:
                what, sp = tm.setters[kind]
                item = items.get((who, sp), "")
                if EXTENDERS.get(what) == item or (kind == "terrain" and item == "terrainextender"):
                    ext[kind] = 8

    side_one = pe.Side(
        pokemon=_pad(our_mons),
        active_index=pe.PokemonIndex(str(our_idx)),
        side_conditions=_side_conditions(
            battle.side_conditions, turn, *_counts(tm_us, active), clay_us
        ),
        volatile_statuses=our_vol,
        **_timed(tm_us, active, ours, our_mons, our_vol),
        substitute_health=(
            (
                int((active.max_hp or 4) // 4)
                if spectator is None
                else our_mons[our_active_idx].maxhp // 4
            )
            // (2 if tm_us.sub_hit else 1)  # a hit Substitute: about half left
            if active is not None
            and Effect.SUBSTITUTE in active.effects
            and our_active_idx is not None
            else 0
        ),
        force_switch=bool(battle.force_switch) if force_switch is None else force_switch,
        **our_last,
        **(_boosts(active) if active is not None else {}),
    )
    side_two = pe.Side(
        pokemon=_pad(their_mons),
        active_index=pe.PokemonIndex(str(their_idx)),
        side_conditions=_side_conditions(
            battle.opponent_side_conditions, turn, *_counts(tm_them, opp_active), clay_them
        ),
        volatile_statuses=their_vol,
        **_timed(tm_them, opp_active, theirs, their_mons, their_vol),
        substitute_health=(
            their_mons[their_idx].maxhp // 4 // (2 if tm_them.sub_hit else 1)
            if opp_active is not None and Effect.SUBSTITUTE in opp_active.effects
            else 0
        ),
        **their_last,
        **(_boosts(opp_active) if opp_active is not None else {}),
    )

    def field_left(kind: str, start: int) -> int:
        # ends of turn counted by the timers (doc/engine-diff.md L3); poke-env's start turn only
        # if the log never showed it start
        length = ext.get(kind, 5)
        n = tm_us.fields_elapsed.get(kind)
        return _remaining(start, turn, length) if n is None else max(1, length - n)

    weather, wturns = "none", 0
    if battle.weather:
        w, start = next(iter(battle.weather.items()))
        weather, wturns = WEATHER.get(w, "none"), field_left("weather", start)
    terrain, tturns = "none", 0
    trick_room, trturns = False, 0
    for f, start in battle.fields.items():
        if f in TERRAIN:
            terrain, tturns = TERRAIN[f], field_left("terrain", start)
        if f == Field.TRICK_ROOM:
            trick_room, trturns = True, _remaining(start, turn)
    return pe.State(
        side_one=side_one,
        side_two=side_two,
        weather=pe.Weather(weather),
        weather_turns_remaining=wturns,
        terrain=pe.Terrain(terrain),
        terrain_turns_remaining=tturns,
        trick_room=trick_room,
        trick_room_turns_remaining=trturns,
    )


def engine_move_to_order(player, battle, choice: str):
    """'earthquake' / 'earthquake-tera' / 'switch greattusk' -> a poke-env order (or None)."""
    if choice.startswith("switch "):
        sp = choice.split(" ", 1)[1]
        for m in battle.available_switches:
            if m.species == sp:
                return player.create_order(m)
        return None
    tera = choice.endswith("-tera")
    mid = choice[: -len("-tera")] if tera else choice
    for mv in battle.available_moves:
        if mv.id == mid:
            return player.create_order(mv, terastallize=tera and battle.can_tera)
    if len(battle.available_moves) == 1:  # recharge / struggle / locked move
        return player.create_order(battle.available_moves[0])
    return None


__all__ = ["build_state", "sample_set", "engine_move_to_order", "Move"]
