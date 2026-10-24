"""poke-env battle -> poke-engine State (MIT-licensed Rust engine used as our forward model).

Our side is exact (request data). The opponent's hidden information is *sampled* from our belief
model: for every opposing mon, revealed facts are kept and the rest (moves to 4, item, ability,
tera type) is drawn from the species' set-archetype posterior given what has been revealed (or
the marginal prior when no archetypes exist); stats come from the species' common spread. Calling
``build_state`` several times gives several determinizations for root-parallel search.

Written from the poke-engine API (poke_engine.pyi) and poke-env; no Foul Play code is used.
"""

import collections
import copy
import functools
import random
from dataclasses import dataclass, field

import numpy as np
import alpha_search
import poke_engine as pe
from poke_env.battle import Effect, Field, SideCondition, Status, Weather
from poke_env.battle.move import Move
from poke_env.data import GenData

from alpha_poke.agents import poke_env_fixes  # noqa: F401 (poke-env's tracking fixed on import)
from alpha_poke.agents.belief_state import BeliefModel, _preview_name, ability_probs
from alpha_poke.agents.damage import calc_stats
from alpha_poke.agents.damage_obs import damage_posteriors, record_base
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
# (an added type -- Forest's Curse, Trick-or-Treat: Showdown's getTypes has it, the engine's
# typechange volatile; S80)
BOOSTS[Effect.TYPEADD] = "typechange"
BOOSTS[Effect.POWER_TRICK] = "powertrick"  # (S111: never passed)
# partial trapping (doc/engine-diff.md L2c, 2026-10-16: left out until then -- the search did not
# see the trapped mon unable to switch nor its 1/8 per turn): poke-env names it after the move
BOOSTS |= {getattr(Effect, n): "partiallytrapped" for n in (
    "BIND", "WRAP", "FIRE_SPIN", "WHIRLPOOL", "SAND_TOMB", "MAGMA_STORM", "INFESTATION",
    "SNAP_TRAP", "THUNDER_CAGE", "CLAMP", "PARTIALLY_TRAPPED") if hasattr(Effect, n)}  # fmt: skip
_MOVES = GEN.moves
PERISH = {getattr(Effect, f"PERISH{n}"): n for n in (1, 2, 3)}
SCREENS = {"reflect", "lightscreen", "auroraveil"}
# the abilities that do nothing for a transformed holder (abilities.rs NO_TRANSFORM, L214)
NO_TRANSFORM = ("disguise", "embodyaspectcornerstone", "embodyaspecthearthflame", "embodyaspectteal",
                "embodyaspectwellspring", "gulpmissile", "hungerswitch", "iceface", "neutralizinggas",
                "protosynthesis", "quarkdrive", "terashift", "zerotohero")  # fmt: skip
CHOICE_ITEMS = ("choiceband", "choicespecs", "choicescarf")
# the weather (its -weather id) / terrain an item extends to 8 turns
EXTENDERS = {"sunnyday": "heatrock", "raindance": "damprock", "sandstorm": "smoothrock",
             "snow": "icyrock", "snowscape": "icyrock", "hail": "icyrock"}  # fmt: skip


def _own_moves(mon) -> dict:
    """A mon's own moves: poke-env's ``moves`` are the copied ones while it is transformed (its
    own set then is its base moves; 2026-10-23 review: a Ditto's set sampled with the copied
    moves -- Transform and Kowtow Cleave in one set)."""
    ms = mon._moves
    return ms._base_moves if ms._transform_moves is not None else mon.moves


def _weight(mon) -> float:
    """A mon's own weight (poke-env's is its target's while it is transformed: the backup's
    weight, 2026-10-23 review)."""
    if mon.transformed:
        entry = GEN.pokedex.get(to_id(mon.species))
        if entry and entry.get("weightkg"):
            return float(entry["weightkg"])
    return float(mon.weight or 0.0)


def _own_base_stats(mon) -> dict:
    """A mon's own base stats (poke-env's ``base_stats`` are its target's while it is
    transformed: 2026-10-23 review -- a Ditto's HP 403, Showdown 300; its backup's Attack its
    target's)."""
    return getattr(mon, "_base_stats", None) or mon.base_stats


def _current_ability(mon, own: str) -> str:
    """The engine's ability of a mon whose own (its set's) is ``own``: a temporary one -- Trace's,
    a Skill Swap's, a Transform's -- if it has one (poke-env's temporary_ability; gone when it
    switches out), else its own."""
    t = getattr(mon, "temporary_ability", None)
    # (As One announces itself and the ability it holds -- Unnerve, Chilling / Grim Neigh: the set's
    # As One, a Ditto's copied one too; S121)
    if t and own.startswith("asone") and to_id(t) in ("asone", "unnerve", "chillingneigh", "grimneigh"):
        return own
    return to_id(t) if t else own


def _copied_pp(mon, mid: str) -> int:
    """The PP left of a move ``mon`` copied by transforming (poke-env counts its uses: 5 PP at
    most; 2026-10-23 review: always 5, a Scarf Ditto's fifth Protect left it at 5)."""
    mv = mon.moves.get(mid) if mon is not None and mon.transformed else None
    return max(0, mv.current_pp) if mv is not None else 5


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
    # target species id -> the moves this side's active used transformed into it (the game's:
    # known from the transform on, as its request lists them)
    copied: dict = field(default_factory=dict)


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
    dmg_post: list | None = None,
    exclude: frozenset = frozenset(),
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
    # (``exclude``: moves its line showed that were a disguised Illusion's: _illusion_fix)
    revealed = [m for m in _own_moves(mon) if m in _MOVES and m not in exclude]
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
    # (its own: not a temporary one -- Trace's, a Transform's; 2026-10-23 review: the copied
    # Intimidate was its base ability, still on after its switch-out)
    ability = to_id(mon.base_ability) if mon.base_ability else None
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
    if dmg_post:  # F1: (item, ability, spread) from the damage posterior (agents/damage_obs.py)
        level = mon.level or 100
        w = [p for *_, p in dmg_post]
        if k is not None and not item_seen and ss.vocab.get("item"):
            # the item consistent with the moves: the candidates' prior is the item marginal
            # (dist.item), swapped here for the archetype's item weights (the moves drawn below
            # are the archetype's: a Choice Scarf with Nasty Plot otherwise)
            arch: dict[str, float] = {}
            for n, v in zip(ss.vocab["item"], flat(ss.params["item"][k]), strict=False):
                arch[to_id(n)] = arch.get(to_id(n), 0.0) + float(v)
            marg = {to_id(n): v for n, v in dist.item.items()}
            w = [p * arch.get(it, 0.0) / max(marg.get(it, 0.0), 1e-9)
                 for (it, *_), p in zip(dmg_post, w, strict=True)]  # fmt: skip
        if speed_obs:  # the move order too: an inconsistent spread / item nearly ruled out
            base = _own_base_stats(mon)
            w = [p * (1.0 if consistent(speed_obs, calc_stats(base, s, level=level)["spe"],
                                        it if not item_seen else item) else 1e-3)
                 for (it, _, s, _), p in zip(dmg_post, w, strict=True)]  # fmt: skip
        if sum(w) > 0:
            it, ab, spread, _ = rng.choices(dmg_post, weights=w)[0]
            if not item_seen:
                item = it
            if not mon.base_ability and not (known is not None and known.ability):
                ability = ab
    if spread is None and speed_obs is not None:  # the spread sampled, consistent with the order
        spread, item = _sample_spread(mon, item, item_seen, speed_obs, dist, rng)
    if spread is None:
        spread = belief.spread_for(mon.species)
    stats = calc_stats(_own_base_stats(mon), spread, level=mon.level or 100)
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
            speeds = [calc_stats(_own_base_stats(mon), s, level=level)["spe"] for s in spreads]
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


def _boosts(mon, more: dict | None = None) -> dict:
    """``more``: stage changes poke-env lost (a broken Illusion's: its disguise's then)."""
    b = dict(mon.boosts)
    for k, v in (more or {}).items():
        b[k] = max(-6, min(6, b.get(k, 0) + v))
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
                     clay: frozenset = frozenset(), elapsed: dict | None = None) -> pe.SideConditions:  # fmt: skip
    """``clay``: the screens (reflect, lightscreen, auroraveil) set by a Light Clay holder: 8
    turns. ``elapsed``: the timed conditions' ends of turn so far (the timers' side_elapsed;
    poke-env's start turn when the log never showed one start)."""
    elapsed = elapsed or {}

    def left(cond, key: str, length: int) -> int:
        if cond not in sc:
            return 0
        n = elapsed.get(key)
        return _remaining(sc.get(cond), turn, length) if n is None else max(1, length - n)

    return pe.SideConditions(
        toxic_count=toxic,
        protect=protect,
        spikes=sc.get(SideCondition.SPIKES, 0),
        toxic_spikes=sc.get(SideCondition.TOXIC_SPIKES, 0),
        stealth_rock=int(SideCondition.STEALTH_ROCK in sc),
        sticky_web=int(SideCondition.STICKY_WEB in sc),
        reflect=left(SideCondition.REFLECT, "reflect", 8 if "reflect" in clay else 5),
        light_screen=left(SideCondition.LIGHT_SCREEN, "lightscreen", 8 if "lightscreen" in clay else 5),
        aurora_veil=left(SideCondition.AURORA_VEIL, "auroraveil", 8 if "auroraveil" in clay else 5),
        tailwind=left(SideCondition.TAILWIND, "tailwind", 4),
        # (the engine has them: 2026-10-23, the state-construction differential -- never passed)
        safeguard=left(SideCondition.SAFEGUARD, "safeguard", 5),
        mist=left(SideCondition.MIST, "mist", 5),
    )


def _volatiles(mon) -> set[str]:
    return {name for eff, name in VOLATILE.items() if eff in mon.effects}


def _base_ability(mon, ability: str, tm: SideTimers | None) -> str:
    """The engine's base ability: none for a once-per-battle switch-in ability already used
    (Dauntless Shield; the patched engine then raises Defense no more, doc/engine-diff.md L18)."""
    if (tm is not None and ability in ("dauntlessshield", "battlebond", "supersweetsyrup",
                                                  "intrepidsword")
            and tm.k(to_id(mon.species)) in tm.used_once):  # fmt: skip
        return "none"
    return ability


@functools.cache
def engine_volatile(name: str) -> bool:
    """Whether poke-engine knows the volatile status ``name`` (the binding takes any name and the
    engine reads an unknown one as NONE: a round trip tells)."""
    try:
        side = pe.Side(pokemon=[pe.Pokemon.create_fainted()] * 6, volatile_statuses={name})
        back = pe.State.from_string(pe.State(side_one=side).to_string()).side_one
        return {str(v).lower() for v in back.volatile_statuses} == {name}
    except BaseException:  # noqa: BLE001 - the binding panics on an unknown name
        return False


@functools.cache
def engine_item(name: str) -> bool:
    """Whether poke-engine knows the item ``name`` (an unknown one reads back as UNKNOWNITEM)."""
    p = pe.Pokemon(item=name)
    s = pe.State(side_one=pe.Side(pokemon=[p] + [pe.Pokemon.create_fainted()] * 5))
    return str(pe.State.from_string(s.to_string()).side_one.pokemon[0].item).lower() == name


@functools.cache
def engine_species(name: str) -> bool:
    """Whether poke-engine knows the species ``name`` (a state round trip keeps it)."""
    try:
        side = pe.Side(pokemon=[pe.Pokemon(id=name)] + [pe.Pokemon.create_fainted()] * 5)
        back = pe.State.from_string(pe.State(side_one=side).to_string()).side_one
        return back.pokemon[0].id.lower() == name
    except BaseException:  # noqa: BLE001
        return False


def _formes(team: dict, mons: list, built: list, tm: SideTimers) -> list:
    """``built`` (the engine mons of ``mons``, a side's poke-env mons; ``team``: the side's
    battle dict) with each one's species its forme now: poke-env keeps the one it came in as (a
    detailschange -- Ogerpon's tera, Palafin-Hero, Mimikyu-Busted -- or a -formechange --
    Cramorant's Gorging -- change its stats and types only); a Battle Bond Greninja the engine's
    Greninja-Bond (its Battle Bond only works for that species; Showdown shows "Greninja"). Not a
    transformed one (it keeps its own species). 2026-10-23, the state-construction
    differential."""
    nick = {id(m): k.split(": ", 1)[-1] for k, m in team.items()}
    out = list(built)
    for j, (m, p) in enumerate(zip(mons, built, strict=True)):
        n = nick.get(id(m))
        f = (tm.formes.get(n) or tm.names.get(n)) if n is not None else None
        if tm.temp_forme and n == tm.temp_forme[0] and m.active and not m.fainted:
            f = tm.temp_forme[1]
        if p.id.lower() == "greninja" and str(p.ability).lower() == "battlebond":
            f = "greninjabond"
        if f and f != p.id.lower() and not m.transformed and engine_species(f):
            out[j] = _with(p, id=f)
    return out


@functools.cache
def _move_kinds() -> dict:
    """Move id -> (category, flags) from the engine's data (alpha_search.engine_data)."""
    rows, _ = alpha_search.engine_data()
    return {r[0].lower(): (r[3], set(r[-1].split(","))) for r in rows}


def derived_disable(move: str, *, taunt: bool, healblock: bool, throatchop: bool, item: str,
                    last_move: str, lock: str = "", disabled: str = "",
                    charging: str = "", recharge: bool = False, pp: int = 1,
                    encore: bool = False, uproar: bool = False) -> bool:  # fmt: skip
    """Showdown disables ``move`` only for a reason the engine derives itself -- so not the
    move's disabled flag, which the engine never clears (it never set it): a Taunt's status move,
    a Heal Block's healing one, a Throat Chop's sound one, an Assault Vest's status one, a
    Gigaton Hammer / Blood Moon used last (L232: Iron Defense still disabled after the Taunt
    ended). Not when a lock keeps it out as well (``lock``: a Choice item's / Gorilla Tactics'
    move; ``disabled``: Disable's): the engine's flags. ``charging``: a two-turn move's second
    turn -- the engine's charge volatile keeps the others out; ``recharge``: a recharge turn
    (the engine's mustrecharge); ``pp`` 0: out of PP (the engine's own: no option). One rule for the differential's
    states and ours (2026-10-23, the state-construction differential: our request's Assault
    Vest disable stayed after the vest was knocked off)."""
    if lock and lock != move:
        return False  # (a lock's flags stay through a recharge: the engine's after it)
    if disabled == move:
        return False
    cat, flags = _move_kinds().get(move, ("", set()))
    if (taunt and cat == "Status") or (healblock and "heal" in flags) \
            or (throatchop and "sound" in flags) or (item == "assaultvest" and cat == "Status") \
            or (move in ("gigatonhammer", "bloodmoon") and last_move == move):
        return True  # (the differential's own: these before an Encore's flag)
    if encore:  # (Encore keeps the others out by their flags too)
        return False
    # (a charge's second turn, a recharge, out of PP, an Uproar: the engine's own too -- with no
    # flag reason above)
    return bool((charging and move != charging) or recharge or pp <= 0 or (uproar and move != "uproar"))


def _sleep(mon, tm: SideTimers | None) -> dict:
    """rest_turns / sleep_turns of an asleep mon (timers), else nothing."""
    if tm is None or STATUS.get(mon.status) != "sleep":
        return {}
    rest, sleep = tm.rest_sleep(tm.k(to_id(mon.species)))
    return {"rest_turns": rest, "sleep_turns": sleep}


def _our_mon(
    mon,
    available_moves: set[str] | None,
    tm: SideTimers | None = None,
    req_pp: dict | None = None,
    revived: bool = False,
    pp_adj: dict | None = None,
    imprisoned: frozenset = frozenset(),
) -> pe.Pokemon:
    """``req_pp``: the request's PP of the active's moves (exact; poke-env counts uses itself and
    drifts low over long games: 2026-10-11, a move with PP left was 0 in the engine, no legal
    option); a move the request offers has PP. ``revived``: a fainted mon brought back at half
    HP (Revival Blessing's choice)."""
    stats = mon.stats or {}
    moves = []
    if mon.transformed:  # its own moves (the request's are the copied ones: _as_transformed)
        available_moves = req_pp = None
    last = next((mid for mid, mv in mon.moves.items() if mv.is_last_used), "")
    # (after a Struggle -- its locked move out of PP -- the lock's move is the one it chose: the
    # timers'; poke-env's last used one is not -- 2026-10-23, S70: a Taunt's flag on top)
    chosen = tm.own_last if tm is not None and tm.struggled and tm.own_last else last
    lock = chosen if ((mon.item in CHOICE_ITEMS and not (tm is not None and tm.item_new))
                    or mon.ability == "gorillatactics") else ""  # fmt: skip
    if tm is not None and tm.locked and mon.active:
        lock = tm.locked[0]  # (a locking move's: its flags first -- L179; a Taunt on top derives none)
    own = _own_moves(mon)
    # (its moves as its request lists them: poke-env adds a move our disguised Zoroark used to its
    # disguise's -- 2026-10-23, the state-construction differential)
    listed = [to_id(x) for x in ((getattr(mon, "_last_request", None) or {}).get("moves") or [])]
    if listed and not mon.transformed and all(x in own for x in listed):
        own = {x: own[x] for x in listed}
    for mid, mv in list(own.items())[:4]:
        pp = max(0, mv.current_pp + (pp_adj or {}).get(mid, 0))
        pp = max(0, pp - _spited(tm, mon, mid))
        if req_pp and req_pp.get(mid) is not None:
            pp = int(req_pp[mid])
        if available_moves is not None and mid in available_moves:
            pp = max(pp, 1)
        # (a Disable'd move offered anyway -- its lock's request, Outrage's: Showdown's slot is
        # disabled; S101)
        # (the foe's Imprison on a move it knows too: Showdown disables it -- its request says only
        # maybeDisabled; S103: a Mew's Imprison, then its Transform into us)
        disabled = available_moves is not None and (mid not in available_moves or mid in imprisoned or (
            tm is not None and tm.disabled == mid)) and not (
            tm is not None and derived_disable(
                mid, taunt=tm.taunt is not None, healblock=tm.healblock is not None,
                throatchop=tm.throatchop is not None, item=mon.item or "", last_move=last,
                lock=lock, disabled=tm.disabled or "", charging=tm.charging or "",
                recharge=tm.recharge, pp=pp, encore=tm.encore is not None,
                uproar=tm.uproar is not None))  # fmt: skip
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
        base_ability=_base_ability(mon, to_id(mon.base_ability or "") or "none", tm),
        item=mon.item or "none",
        attack=int(stats.get("atk") or 100),
        defense=int(stats.get("def") or 100),
        special_attack=int(stats.get("spa") or 100),
        special_defense=int(stats.get("spd") or 100),
        speed=int(stats.get("spe") or 100),
        status="none" if revived else STATUS.get(mon.status, "none"),
        weight_kg=_weight(mon),
        moves=moves,
        terastallized=bool((mon._last_request or {}).get("terastallized"))
        if "terastallized" in (getattr(mon, "_last_request", None) or {}) else mon.is_terastallized,
        # (the request's tera type: a switch line's tera: details went to the mon a disguised
        # Illusion showed -- 2026-10-23, the state-construction differential)
        tera_type=to_id((getattr(mon, "_last_request", None) or {}).get("teraType") or "") or _tera(mon),
        **_sleep(mon, tm),
        **_counted(mon, tm),
    )


def _counted(mon, tm: SideTimers | None) -> dict:
    """The engine's times attacked (Rage Fist) and gender (0 none, 1 male, 2 female; Attract,
    Cute Charm) of a mon (doc/engine-diff.md L163), a Stellar tera's boosted types (L175)."""
    gender = {"MALE": 1, "FEMALE": 2}.get(getattr(getattr(mon, "gender", None), "name", ""), 0)
    hits = tm.times_attacked.get(tm.k(to_id(mon.species)), 0) if tm is not None else 0
    # (L175: a Stellar tera's types already boosted: its damaging moves' since; Tera Blast's Stellar)
    boosted = set()
    for m in (tm.stellar_moves.get(tm.k(to_id(mon.species)), ()) if tm is not None else ()):
        d = _MOVES.get(m)
        if d and d.get("category") != "Status":
            boosted.add("stellar" if m == "terablast" else d["type"].lower())
    out = {"times_attacked": min(hits, 255), "gender": gender, "stellar_boosted": sorted(boosted)}
    # its last item used up / eaten (Harvest, Recycle, Cud Chew: L57 / L178 / L204; 2026-10-23,
    # the state-construction differential: never passed -- poke-env keeps no lastItem)
    last = tm.last_item.get(tm.k(to_id(mon.species))) if tm is not None else None
    if last and engine_item(last):
        out["last_item"] = last
    return out


def _spited(tm: SideTimers | None, mon, mid: str) -> int:
    """The PP Spite took of ``mon``'s move (the timers': poke-env does not track it)."""
    return (tm.pp_taken.get(tm.k(to_id(mon.species))) or {}).get(mid, 0) if tm is not None else 0


def _max_pp(mid: str) -> int:
    return Move(mid, gen=9).max_pp if mid in _MOVES else 64


def _illusion_adj(m, dis: dict, z: dict) -> tuple:
    """_their_mon's (pp_adj, hp_line) for ``m`` by the Illusion bookkeeping (_illusion_fix; an
    hp_line "": its own HP shown since -- out again itself)."""
    if id(m) in dis:
        hp, _, back = dis[id(m)]
        return dict(back), hp
    if id(m) in z:
        return {mv: -c for mv, c in z[id(m)].items()}, ""
    return None, ""


def _illusion_fix(team: dict, tm: SideTimers, current: bool) -> tuple[dict, dict, dict]:
    """A side's Illusion bookkeeping (2026-10-23, the state-construction differential: poke-env
    gives a disguised Zoroark's HP, moves and PP to its disguise, keeps none for the Zoroark and
    drops its boosts as the Illusion breaks): (id(disguise mon) -> (its HP line before the
    disguise came, None: never shown; the Zoroark's moves then to leave out of its set; the uses
    to give back), id(zoroark) -> the uses it made disguised, the boosts it had then). ``current``:
    this time in is a disguise too (our disguised active; a world that drew the Zoroark)."""
    fixes = list(tm.illusions.values()) + ([tm.stint] if current else [])
    by_nick = {k.split(": ", 1)[-1]: m for k, m in team.items()}
    zoroark = next((m for m in team.values() if to_id(m.species).startswith("zoroark")), None)
    dis: dict = {}
    zuses: collections.Counter = collections.Counter()
    for f in fixes:
        m = by_nick.get(f["nick"])
        uses = collections.Counter(f["moves"])
        zuses.update(uses)
        if m is None or m is zoroark:
            continue
        own = tm.moves_by_nick.get(f["nick"], collections.Counter())
        hp, ex, back = dis.get(id(m), (f["hp"], set(), collections.Counter()))
        back.update(uses)
        ex |= {mv for mv in uses if own[mv] - back[mv] <= 0}
        dis[id(m)] = (hp, ex, back)
    z = {id(zoroark): zuses} if zoroark is not None and zuses else {}
    return dis, z, (tm.illusion_boosts if not current else {})


def _pp(mon, mid: str) -> int:
    """The PP of an opponent's move: poke-env counts its uses (Pressure included; not the turns
    of a locked move) of a revealed move; an unrevealed one has its maximum (PP Ups)."""
    mv = _own_moves(mon).get(mid)
    if mv is not None:
        # (a move Sleep Talk calls costs no PP: poke-env counts none -- [from] move: Sleep Talk --,
        # Sleep Talk its own; 2026-10-23 review: a floor of 1 for a Sleep Talk user's moves kept
        # Sleep Talk itself at 1 PP forever; the engine's Sleep Talk calls a move without PP too)
        return max(0, mv.current_pp)
    return Move(mid, gen=9).max_pp if mid in _MOVES else 16


def _their_mon(mon, s: SampledSet, tm: SideTimers | None = None, disabled: str | None = None,
               pp_adj: dict | None = None, hp_line: str | None = "") -> pe.Pokemon:  # fmt: skip
    """The moves' PP from their uses; ``disabled``: the move Disable blocks. ``pp_adj``: uses
    to add back (+) / take (-) per move, ``hp_line``: its HP as shown before (None: never shown,
    full) -- a disguised Illusion's that poke-env gave its disguise (_illusion_fix)."""
    maxhp = s.stats["hp"]
    pp_adj = pp_adj or {}
    if mon.fainted:
        hp = 0
    elif hp_line is None or (hp_line and "/" in hp_line):
        hp = maxhp
        if hp_line:
            cur, tot = hp_line.split(" ")[0].split("/")
            hp = max(1, round(int(cur) / max(int("".join(c for c in tot if c.isdigit()) or 1), 1) * maxhp))
    elif not mon.max_hp:
        # never on the field (team preview only): poke-env reports an HP fraction of 0; the
        # mon is at full HP (before 2026-10-06 this gave it 1 HP in every search)
        hp = maxhp
    else:
        hp = max(1, round(mon.current_hp_fraction * maxhp))
        # a Regenerator that switched out (a benched mon seen before): a third back, silently --
        # poke-env adds it only when it knew the ability (2026-10-23, the state-construction
        # differential: this world's Regenerator healed nothing)
        if s.ability == "regenerator" and not mon.active and mon.ability != "regenerator" and not (
                tm is not None and tm.k(to_id(mon.species)) in tm.no_regen):  # fmt: skip
            hp = min(maxhp, hp + maxhp // 3)
    return pe.Pokemon(
        id=mon.species,
        level=mon.level or 100,
        types=_types(mon),
        base_types=_base_types(mon.species),
        hp=hp,
        maxhp=maxhp,
        ability=_current_ability(mon, s.ability),
        base_ability=_base_ability(mon, s.ability, tm),
        item=s.item,
        attack=s.stats["atk"],
        defense=s.stats["def"],
        special_attack=s.stats["spa"],
        special_defense=s.stats["spd"],
        speed=s.stats["spe"],
        status=STATUS.get(mon.status, "none"),
        weight_kg=_weight(mon),
        moves=[pe.Move(id=m, pp=max(0, min(_max_pp(m), _pp(mon, m) + pp_adj.get(m, 0))
                                    - _spited(tm, mon, m)),
                       disabled=m == disabled) for m in s.moves[:4]],  # fmt: skip
        terastallized=mon.is_terastallized,
        tera_type=s.tera,
        **_sleep(mon, tm),
        **_counted(mon, tm),
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
            "sleep_turns", "times_attacked", "gender", "stellar_boosted", "last_item",
            "transform_backup")  # fmt: skip
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


def _as_transformed(p: pe.Pokemon, target: pe.Pokemon, moves: list, ability: str) -> pe.Pokemon:
    """``p`` transformed into ``target`` (Showdown's transformInto): the target's types,
    ability, stats except HP, weight and ``moves``; its own species (as the engine's transform
    keeps it), HP, level, item, status, tera and base types / ability, and its own stats,
    weight, moves and PP as the engine's backup (transform_backup, L180: what its switch-out
    restores; 2026-10-23 review: none -- out in the search, a Ditto stayed a Kingambit with
    Kingambit's stats and a 5 PP Transform). ``ability``: the one it copied as it transformed
    (not its target's now: an Ogerpon terastallized after had both Embody Aspect)."""
    own = [(m.id, m.pp) for m in p.moves][:4]
    backup = ([p.attack, p.defense, p.special_attack, p.special_defense, p.speed],
              round(p.weight_kg * 10), own + [("none", 0)] * (4 - len(own)))  # fmt: skip
    return pe.Pokemon(
        id=p.id, level=p.level, types=target.types, base_types=p.base_types, hp=p.hp,
        # (an ability that does nothing for a transformed holder: none, the engine's L214)
        maxhp=p.maxhp, ability="none" if ability in NO_TRANSFORM else ability,
        base_ability=p.base_ability, item=p.item,
        attack=target.attack, defense=target.defense, special_attack=target.special_attack,
        special_defense=target.special_defense, speed=target.speed, status=p.status,
        weight_kg=target.weight_kg, moves=moves, terastallized=p.terastallized,
        tera_type=p.tera_type, rest_turns=p.rest_turns, sleep_turns=p.sleep_turns,
        times_attacked=p.times_attacked, gender=p.gender, transform_backup=backup,
    )  # fmt: skip


def _last_move(mon, engine_mon, avail: set[str] | None = None, index: int | None = None,
               switched_now: bool = False, tm: SideTimers | None = None) -> tuple[dict, set[str]]:  # fmt: skip
    """(``last_used_move`` Side kwarg, volatiles) for an active mon. The engine panics on an
    Encore without a last used move, so Encore is dropped when we cannot tell the move. Without
    one: its switch-in (``index``, its slot) on its first turn out -- Fake Out / First
    Impression work --, else none (doc/engine-diff.md L214: a turn out without a move)."""
    vol = _volatiles(mon) if mon is not None else set()
    if mon is None or engine_mon is None:
        vol.discard("encore")
        return {}, vol
    ids = [m.id for m in engine_mon.moves]
    # (L232: after a Struggle, a lock's move -- a Choice item's / Gorilla Tactics' / Encore's --
    # is the last used one; else none: 2026-10-23, the state-construction differential)
    if tm is not None and tm.struggled:
        # (a Choice item got since its locked move -- Trick: the lock gone, the Struggle's own
        # locks none; 2026-10-23, S72)
        locked = ((str(engine_mon.item).lower() in CHOICE_ITEMS and not tm.item_new)
                  or str(engine_mon.ability).lower() == "gorillatactics" or "encore" in vol)  # fmt: skip
        if locked and tm.own_last in ids:
            return {"last_used_move": f"move:{ids.index(tm.own_last)}"}, vol
        vol.discard("encore")
        return {}, vol
    idx = next(
        (ids.index(mid) for mid, mv in mon.moves.items() if mv.is_last_used and mid in ids), None
    )
    if tm is not None and tm.locked_exec and tm.locked_exec not in ids:
        # (a called charge's second turn -- Metronome's Meteor Beam, run locked: Showdown's
        # moveUsed sets lastMove to it, no move of its own: none; 2026-10-23)
        vol.discard("encore")
        return {}, vol
    backup = getattr(engine_mon, "transform_backup", None)
    if idx is None and tm is not None and backup and tm.own_last in [m for m, _ in backup[2]]:
        # (a transformed mon's own move -- its Transform: poke-env has its target's moves only;
        # the engine's last used one is its slot in the backup, L187; 2026-10-23)
        return {"last_used_move": f"move:{[m for m, _ in backup[2]].index(tm.own_last)}"}, vol
    if idx is None and tm is not None and tm.illusion_last in ids:
        # (a broken Illusion: its last move disguised -- poke-env gave it to the disguise)
        return {"last_used_move": f"move:{ids.index(tm.illusion_last)}"}, vol
    if idx is None and "encore" in vol and avail is not None and len(avail) == 1:
        (only,) = avail  # we are encored: the request offers only the encored move
        idx = ids.index(only) if only in ids else None
    if idx is None:
        vol.discard("encore")
        # (or it came in this very turn -- a mid-turn decision: poke-env's first_turn waits for
        # the next turn; 2026-10-23, the state-construction differential; with the timers, theirs
        # only: poke-env's first_turn stays through a stopped action -- cant -- this turn)
        fresh = tm.fresh if tm is not None else getattr(mon, "first_turn", False)
        if index is not None and (fresh or switched_now):
            return {"last_used_move": f"switch:{index}"}, vol
        return {}, vol
    return {"last_used_move": f"move:{idx}"}, vol


def _pending_move(mon: pe.Pokemon, last: dict, vol: set[str], weights: dict | None,
                  rng: random.Random, legal: list[str]) -> str:
    """The opponent's move still to come this turn, in this world: its locked move (a Choice
    item's, Outrage's: its last used one) if legal, else one of the ``legal`` ones (the engine's:
    alpha_search.pending_moves) drawn by ``weights`` (by move id: the turn's search's opponent
    visits, so conditioned on what is left; none or all zero: uniform); "none" without one."""
    moves = list(mon.moves)
    lu = last.get("last_used_move", "")
    if lu.startswith("move:") and (mon.item in ("choiceband", "choicespecs", "choicescarf")
                                   or "lockedmove" in vol):  # fmt: skip
        m = moves[int(lu[5:])]
        if m.id in legal:
            return m.id
    usable = list(legal)
    if not usable:
        return "none"
    w = [max(0.0, (weights or {}).get(mid, 0.0)) for mid in usable]
    return rng.choices(usable, weights=w if sum(w) > 0 else None)[0]


def _with_saved_move(st: pe.State, move: str) -> pe.State:
    """``st`` with side two's saved move (switch_out_move_second_saved_move: the 24th field of a
    side's string -- poke-engine's Side::deserialize, split[23]) set to ``move``. (It was the
    sixth from the end: the optional trailing fields -- tera_used, future_doom -- shifted it, the
    move went into a bool field and the engine panicked; 2026-10-23, the state-construction
    differential at a million decisions)"""
    parts = st.to_string().split("/")
    fields = parts[1].split("=")
    fields[23] = move.upper()
    parts[1] = "=".join(fields)
    out = pe.State.from_string("/".join(parts))
    assert out.side_two.switch_out_move_second_saved_move.lower() == move, (move, fields[-6:])
    return out


def _counts(tm: SideTimers, active) -> tuple[int, int]:
    """(toxic_count, protect) of a side's active (timers)."""
    # Showdown's toxic stage stops at 15 (the patched engine's count too, L181: its damage min(count +
    # 1, 15) / 16)
    toxic = min(tm.toxic, 15) if active is not None and STATUS.get(active.status) == "toxic" else 0
    # (a protection this turn counts at once -- Showdown's stall counter: a mid-turn decision)
    return toxic, tm.protect + (1 if tm.protected else 0)


def _timed(tm: SideTimers, active, mons: list, engine_mons: list, vol: set[str],
           disable: int | None = None, locked: int | None = None,
           metronome: int | None = None, counts: dict | None = None) -> dict:  # fmt: skip
    """pe.Side kwargs: the pending Wish (turns, half the wisher's max HP), the pending Future
    Sight (turns, its user's slot) and the active's
    volatile durations (only of volatiles it has; clamped to what the engine accepts;
    ``disable``: Disable's, its move's slot * 8 + its count)."""
    out = {}
    if tm.wish is not None:
        idx = next((i for i, m in enumerate(mons) if tm.k(to_id(m.species)) == tm.wish[1]),
                   next((i for i, m in enumerate(mons) if m is active), None))  # fmt: skip
        if idx is not None and idx < len(engine_mons):
            out["wish"] = (tm.wish[0], engine_mons[idx].maxhp // 2)
    if tm.future is not None:
        idx = next((i for i, m in enumerate(mons) if tm.k(to_id(m.species)) == tm.future[1]), None)
        if idx is not None:
            out["future_sight"] = (tm.future[0], pe.PokemonIndex(str(idx)))
            if tm.future_doom:
                out["future_doom"] = True
    dur = {}
    # (the patched engine ends heal block, magnet rise and throat chop too; a partial trap at its
    # fifth end of turn: at 4 it ends at the next, right for Showdown's 5 and, at 4 or 5, its 6)
    tops = [("confusion", 4), ("taunt", 2), ("encore", 2), ("yawn", 1), ("healblock", 1),
            ("magnetrise", 4), ("throatchop", 1), ("partiallytrapped", 4)]  # fmt: skip
    for name, top in tops:
        n = getattr(tm, name)
        if name in vol and n:
            dur[name] = min(n, top)
    if "slowstart" in vol and tm.slowstart:  # the turns left (the engine counts them down)
        dur["slowstart"] = tm.slowstart[0]
    if "disable" in vol and disable:
        dur["disable"] = disable
    if "lockedmove" in vol and locked:
        dur["lockedmove"] = locked
    if "metronome" in vol and metronome:
        dur["metronome"] = metronome
    for k, n in (counts or {}).items():
        if k in vol:
            dur[k] = n
    if dur:
        out["volatile_status_durations"] = pe.VolatileStatusDurations(**dur)
    return out


def _passed_sub(tm: SideTimers, mons: list, built: list) -> int:
    """The HP of a Substitute passed to the active (Shed Tail: a quarter of its user's max HP --
    Showdown's; Baton Pass: its passer's, about that), 0 without one."""
    if not tm.sub_passed:
        return 0
    p = next((b for m, b in zip(mons, built, strict=True) if tm.k(to_id(m.species)) == tm.sub_passed), None)
    return p.maxhp // 4 if p is not None else 0


def _tera_used(mons: list, used: bool) -> list:
    """``mons`` with a fainted one terastallized when the side used its Terastallization and no
    mon shows it (doc/engine-diff.md L177)."""
    if not used or any(p.terastallized for p in mons):
        return mons
    j = next((j for j, p in enumerate(mons) if p.hp <= 0), None)
    if j is None:
        return mons
    return mons[:j] + [_with(mons[j], terastallized=True)] + mons[j + 1:]


def _side_tera_used(mons: list, used: bool) -> dict:
    """The side's own marker when its Terastallization was used and no mon shows it, not even a
    fainted one (Revival Blessing brought it back; doc/engine-diff.md L185)."""
    return {"tera_used": True} if used and not any(p.terastallized for p in mons) else {}


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
    damage_belief: bool = True,
    foe_pending: dict[str, float] | None = None,
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
    choice). ``damage_belief``: the opponent's sets also from the damage evidence (F1,
    agents/damage_obs.py; off: as before 2026-10-19, for A/B). ``foe_pending``: our switch in the
    middle of a turn (a pivot, an Eject Button) with the opponent's move still to come -- the
    weights of its moves (the turn's search's opponent visits; none: uniform), one drawn per
    world as the engine's saved move (`_pending_move`)."""
    turn = battle.turn
    active = battle.active_pokemon
    role = battle.player_role or "p1"
    # turn counters from the log (timers.py); off: every counter 0, as before 2026-10-11 (A/B)
    tms = battle_timers(battle)
    tm_us, tm_them = tms[role], tms["p2" if role == "p1" else "p1"]
    # our active a disguised Zoroark (the log shows another species): this time in's boosts and
    # moves are its, poke-env gives them to the disguise
    our_disguised = bool(active is not None and tm_us.active and tm_us.active != to_id(active.species)
                         and to_id(active.species).startswith("zoroark"))  # fmt: skip
    if our_disguised:
        # (the items it used up this time in are the Zoroark's -- the timers move them as the
        # Illusion breaks; 2026-10-23, S88: a disguised lead's Throat Spray read as its disguise's)
        tm_us = copy.copy(tm_us)
        tm_us.last_item = dict(tm_us.last_item)
        for dsp, before in tm_us.stint.get("items", []):
            used = tm_us.last_item.pop(dsp, None)
            if before is not None:
                tm_us.last_item[dsp] = before
            if used:
                tm_us.last_item[to_id(active.species)] = used
    if spectator is None:
        # (our Zoroark's sleep counted under a disguise -- this time in or an earlier one: the
        # request's Zoroark asleep with no count, a mon not asleep with one -- S110, S119)
        zor = next((m for m in battle.team.values() if to_id(m.species).startswith("zoroark")), None)
        if zor is not None and STATUS.get(zor.status) == "sleep" and tm_us.k(to_id(zor.species)) not in tm_us.sleep:
            stray = [k for k in tm_us.sleep if not any(
                tm_us.k(to_id(m.species)) == k and STATUS.get(m.status) == "sleep" for m in battle.team.values())]
            if len(stray) == 1:
                tm_us = copy.copy(tm_us)
                tm_us.sleep = dict(tm_us.sleep)
                tm_us.sleep[tm_us.k(to_id(zor.species))] = tm_us.sleep.pop(stray[0])
        ours = list(battle.team.values())
        avail = {m.id for m in battle.available_moves} if battle.available_moves else None
        req = battle.last_request or {}
        act = (req.get("active") or [{}])[0]
        req_pp = {to_id(m["id"]): m.get("pp") for m in act.get("moves", []) if "id" in m}
        foe = battle.opponent_active_pokemon
        imprisoned = frozenset(foe.moves) if tm_them.imprison and foe is not None else frozenset()
        our_mons = [
            _our_mon(m, avail if m is active else None, tm_us,
                     req_pp if m is active else None, revived == to_id(m.species),
                     imprisoned=imprisoned if m is active else frozenset())
            for m in ours
        ]  # fmt: skip
    else:
        ours, avail = spectator.team, None
        our_mons = []
        dis_us, z_us, _ = _illusion_fix(battle.team, tm_us, our_disguised)
        for m in ours:
            s = sample_set(
                belief,
                m,
                spectator.names,
                rng,
                move_beta,
                spectator.known.get(to_id(m.species)),
                exclude=frozenset(dis_us[id(m)][1]) if id(m) in dis_us else frozenset(),
            )
            # known moves come first in sample_set; in a real battle our moves are in moveset
            # order, unrelated to use: shuffle so the slot does not leak which move gets used
            rng.shuffle(s.moves)
            our_mons.append(_their_mon(m, s, tm_us, tm_us.disabled if m is active else None,
                                       *_illusion_adj(m, dis_us, z_us)))
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
    # F1: the damage evidence (play time only, as the speed's): a posterior per mon with hits
    dmg = (damage_posteriors(battle, belief, theirs, team_names)
           if spectator is None and damage_belief else {})  # fmt: skip
    their_keys = [next((k for k, v in battle.opponent_team.items() if v is m), None)
                  for m in theirs]  # fmt: skip
    our_keys = [next((k for k, v in battle.team.items() if v is m), None) for m in ours]
    # a transformed active: the index of its target (D17 J; replays too, 2026-10-23 review)
    our_t = _transform_target(battle, battle.team, active, their_keys)
    their_t = _transform_target(battle, battle.opponent_team, opp_active, our_keys)
    # (the moves our transformed active used are its target's: in that mon's sampled set)
    copied = None
    if our_t is not None:
        used = [m for m in active.moves if m in _MOVES]
        if spectator is not None:  # (a replay: the game's, known from the transform on)
            used += [m for m in spectator.copied.get(to_id(theirs[our_t].species), [])
                     if m in _MOVES and m not in used]  # fmt: skip
        copied = KnownSet(moves=used)
    # this world's Illusion (D17 G): drawn before the sets -- a disguise's line then is its
    # Zoroark's (_illusion_fix)
    zi = _illusion(theirs, opp_active, battle.opponent_team, rng)
    dis_them, z_them, _ = _illusion_fix(battle.opponent_team, tm_them, zi is not None)
    their_sets = [sample_set(belief, m, team_names, rng, move_beta,
                             known=copied if i == our_t else (
                                 KnownSet(moves=[x for x in z_them[id(m)] if x in _MOVES])
                                 if id(m) in z_them else None),
                             speed_obs=None if obs is None else obs.get(to_id(m.species), []),
                             dmg_post=dmg.get(to_id(m.species)),
                             exclude=frozenset(dis_them[id(m)][1]) if id(m) in dis_them else frozenset())
                  for i, m in enumerate(theirs)]  # fmt: skip
    their_mons = [_their_mon(m, st, tm_them, tm_them.disabled if m is opp_active else None,
                             *_illusion_adj(m, dis_them, z_them))
                  for m, st in zip(theirs, their_sets, strict=True)]  # fmt: skip
    their_idx = next((i for i, m in enumerate(theirs) if m is opp_active), 0)
    our_active_idx = next((i for i, m in enumerate(ours) if m is active), None)
    if zi is not None:  # the active is the Zoroark: what is shown (HP fraction, status) is its
        z = their_mons[zi]
        their_mons[zi] = _with(z, hp=max(1, round(opp_active.current_hp_fraction * z.maxhp)),
                               status=STATUS.get(opp_active.status, "none"))  # fmt: skip
        their_idx = zi
    our_tf = their_tf = False
    # a transformed active (D17 J; 2026-10-13); a replay's too (2026-10-23 review: left out --
    # a Ditto's training state had its own stats and moves, no transform)
    t = our_t
    if t is not None and our_active_idx is not None and t < len(their_mons):
        if spectator is None:  # the request's moves (the target's, their PP exact)
            req = {to_id(m["id"]): m.get("pp") for m in act.get("moves", [])[:4]
                   if "id" in m and to_id(m["id"]) not in ("struggle", "recharge")}  # fmt: skip
            # (a lock's request lists the locked move only, without PP; Struggle only, a recharge
            # none: the target's moves, the PP poke-env counted -- 2026-10-23, S94: a locked
            # Outrage the Ditto's only move, 0 PP)
            ids = list(req) if len(req) == 4 or not their_mons[t].moves else \
                list(dict.fromkeys(list(req) + [m.id for m in their_mons[t].moves]))[:4]
            # (the move it chose: after a Struggle poke-env's last used one is the Struggle --
            # 2026-10-23, the state-construction differential: the lock's flags were lost)
            last = (tm_us.own_last if tm_us is not None else "") or next(
                (mid for mid, mv in active.moves.items() if mv.is_last_used), "")
            lock = last if active.item in CHOICE_ITEMS and not tm_us.item_new else ""
            if tm_us.locked:
                lock = tm_us.locked[0]
            moves = []
            struggling = avail is not None and avail <= {"struggle"}
            for mid in ids:
                pp = int(req[mid]) if req.get(mid) is not None else _copied_pp(active, mid)
                if struggling and mid == lock and tm_us.taunt is None and tm_us.disabled != mid:
                    pp = 0  # (Struggle only, locked into it: it is out of PP -- poke-env's count drifts)
                # (its flags as an untransformed mon's: not offered and no reason the engine
                # derives itself -- out of PP, a Taunt, ...: S95)
                disabled = avail is not None and mid not in avail and not derived_disable(
                    mid, taunt=tm_us.taunt is not None, healblock=tm_us.healblock is not None,
                    throatchop=tm_us.throatchop is not None, item=active.item or "", last_move=last,
                    lock=lock, disabled=tm_us.disabled or "", charging=tm_us.charging or "",
                    recharge=tm_us.recharge, pp=pp, encore=tm_us.encore is not None,
                    uproar=tm_us.uproar is not None)  # fmt: skip
                moves.append(pe.Move(id=mid, pp=pp, disabled=disabled))
        else:  # the target's (this world's), the PP poke-env counted, Disable's flag
            moves = [pe.Move(id=m.id, pp=_copied_pp(active, m.id), disabled=m.id == tm_us.disabled)
                     for m in their_mons[t].moves]  # fmt: skip
        our_mons[our_active_idx] = _as_transformed(
            our_mons[our_active_idx], their_mons[t], moves or their_mons[t].moves,
            _current_ability(active, their_sets[t].ability),
        )
        our_tf = True
    t = their_t
    if t is not None and their_mons and t < len(our_mons):
        # (Disable's flag on a copied move: 2026-10-23 review -- left out, usable)
        moves = [pe.Move(id=m.id, pp=_copied_pp(opp_active, m.id),
                         disabled=m.id == tm_them.disabled) for m in our_mons[t].moves]
        own = to_id(ours[t].base_ability) if ours[t].base_ability else our_mons[t].ability
        their_mons[their_idx] = _as_transformed(their_mons[their_idx], our_mons[t], moves,
                                                _current_ability(opp_active, own))  # fmt: skip
        their_tf = True
    our_last, our_vol = _last_move(
        active, our_mons[our_active_idx] if our_active_idx is not None else None, avail,
        our_active_idx, tm_us.switched_now, tm_us,
    )
    their_last, their_vol = _last_move(
        opp_active, their_mons[their_idx] if their_mons else None, None,
        their_idx if their_mons else None, tm_them.switched_now, tm_them,
    )
    # the engine's transform / typechange volatiles (doc/engine-diff.md L36): a switch ends the
    # transformation, and an Imposter does not transform again while it is on
    for tf, vol, mons, i, target in ((our_tf, our_vol, our_mons, our_active_idx, (their_mons, our_t)),
                                     (their_tf, their_vol, their_mons, their_idx, (our_mons, their_t))):  # fmt: skip
        if tf:
            vol.add("transform")
            # (transformed into an Ogerpon / Terapagos: no Terastallization, the engine's notera --
            # L227; 2026-10-23, the state-construction differential: left out)
            if str(target[0][target[1]].id).lower().startswith(("ogerpon", "terapagos")):
                vol.add("notera")
            # (a type change only if its types changed: Ditto into Blissey keeps Normal -- the
            # differential's states, Showdown's; 2026-10-23)
            p = mons[i] if i is not None and i < len(mons) else None
            if p is None or tuple(p.types) != tuple(p.base_types):
                vol.add("typechange")
    # the actives' Protosynthesis / Quark Drive boosts and other volatiles (BOOSTS)
    for mon, vol, tm in ((active, our_vol, tm_us), (opp_active, their_vol, tm_them)):
        vol |= {BOOSTS[e] for e in (mon.effects if mon is not None else ()) if e in BOOSTS}
        if tm.trap_out:  # (L170: its source left, it does nothing more)
            vol.discard("partiallytrapped")
        # (L218: a Protean / Libero type change marks the ability as used, its own volatile now)
        # (the log's -start typechange [from] ability: Protean / Libero -- the timers' -- not
        # poke-env's ability, which it may not know: 2026-10-23, the state-construction
        # differential)
        # (a transformed mon's typechange is its transform's -- unless the log shows its copied
        # Protean's: S79)
        tf = mon is active and our_tf or mon is opp_active and their_tf
        if mon is not None and "typechange" in vol and (
                tm.protean or (mon.ability in ("protean", "libero") and not tf)):
            vol.add("protean")
        # (L222: turn 1's stage changes are its leads' entries -- Intimidate, Intrepid Sword, ...:
        # Showdown's statsLoweredThisTurn / statsRaisedThisTurn, not reset as turn 1 starts)
        if mon is not None and turn <= 1:  # (the log's turn-1 changes, not the boosts now)
            if tm.lowered_t1 or any(v < 0 for v in mon.boosts.values()):
                vol.add("statslowered")
            if tm.raised_t1 or any(v > 0 for v in mon.boosts.values()):
                vol.add("statsraised")
        if tm.imprison:
            vol.add("imprison")
    # (Power Trick: Showdown swaps its stored Attack and Defense -- the engine keeps them swapped
    # with the volatile; the request's and the sets' are the unswapped ones: S111)
    for vol, mons, i in ((our_vol, our_mons, our_active_idx), (their_vol, their_mons, their_idx)):
        if "powertrick" in vol and i is not None and i < len(mons):
            mons[i] = _with(mons[i], attack=mons[i].defense, defense=mons[i].attack)
    # (a type change Showdown keeps no volatile for -- a forme's, Meloetta-Pirouette's: its types
    # not its species' and not terastallized -- the engine's typechange, as the differential's
    # states have it: its switch-out gives the species' back)
    # (a forme's even after its Terastallization -- Meloetta-Pirouette's: Showdown's formeChange
    # sets the pre-tera types; 2026-10-23, S98)
    forme_tc = set()
    for vol, mons, i, mon, tm in ((our_vol, our_mons, our_active_idx, active, tm_us),
                                  (their_vol, their_mons, their_idx, opp_active, tm_them)):  # fmt: skip
        p = mons[i] if i is not None and i < len(mons) else None
        if p is not None and p.hp > 0 and tuple(p.types) != tuple(p.base_types):
            vol.add("typechange")
            if tm.temp_forme is not None or (mon is not None and str(p.id).lower() != to_id(mon.species)):
                forme_tc.add(id(vol))  # (a forme's -- the timers': not a Double Shock's, S122)
    for vol, mons, i, tm in ((our_vol, our_mons, our_active_idx, tm_us),
                             (their_vol, their_mons, their_idx, tm_them)):  # fmt: skip
        p = mons[i] if i is not None and i < len(mons) else None
        if p is not None and p.terastallized and not tm.typechanged and id(vol) not in forme_tc and not (
                mons is our_mons and our_tf or mons is their_mons and their_tf):  # fmt: skip
            # (a type change after it terastallized did nothing -- Showdown's setType: a Double
            # Shock on a tera'd Pawmot; one before it stays)
            vol.discard("typechange")
    # must recharge (the engine offers no move), Perish Song's count
    locked: dict = {}  # (is ours) -> the lock's count
    metronome: dict = {}  # (is ours) -> the Metronome item's count
    vcounts: dict = {}  # (is ours) -> {volatile: its count} (Uproar, Stockpile)
    # (is ours) -> the active's ability in this world
    ab = {True: str(our_mons[our_active_idx].ability).lower() if our_active_idx is not None
          and our_active_idx < len(our_mons) else "",
          False: str(their_mons[their_idx].ability).lower() if their_mons else ""}  # fmt: skip
    items_now = {True: str(our_mons[our_active_idx].item).lower() if our_active_idx is not None
                 and our_active_idx < len(our_mons) else "",
                 False: str(their_mons[their_idx].item).lower() if their_mons else ""}  # fmt: skip
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
        if tm.slowstart:  # (L77)
            vol.add("slowstart")
        if tm.trapped:  # (L107)
            vol.add("trapped")
        if tm.frombooster:  # (L141)
            vol.add("frombooster")
        if tm.last_failed or (tm.last_sub_failed and ab[mon is active] == "infiltrator"):  # (L115; S93)
            vol.add("lastmovefailed")
        # a two-turn move charging (its second turn comes: the engine's volatile of the move)
        # and a locking move (Outrage: lockedmove) -- 2026-10-23, the state-construction
        # differential: neither was passed, the search let it choose another move
        if tm.charging and engine_volatile(tm.charging):
            vol.add(tm.charging)
        # (Unburden: its item lost this time in, this world's ability -- silent in the log;
        # 2026-10-23, the state-construction differential)
        if tm.struggled:  # (L232: the last action a Struggle -- never passed, 2026-10-23)
            vol.add("struggled")
        if tm.gastro:  # (Gastro Acid: the volatile, its ability none -- L209)
            vol.add("gastroacid")
        if tm.cud and ab[mon is active] == "cudchew":  # (L204: its berry again, the counter)
            vol.add("cudchew")
            vcounts.setdefault(mon is active, {})["cudchew"] = tm.cud
        if tm.flashfire:  # (its Flash Fire's boost: the log's -start, not poke-env's effect)
            vol.add("flashfire")
        if tm.destinybond:
            vol.add("destinybond")
        if tm.sub_passed:  # (a Substitute passed in: Shed Tail, Baton Pass)
            vol.add("substitute")
        # its protection this turn (a mid-turn decision: Protect's, Baneful Bunker's, Endure's ...)
        if tm.protected_move and engine_volatile(tm.protected_move):
            vol.add(tm.protected_move)
        if tm.minimized:
            vol.add("minimize")
        if tm.truant_next and ab[mon is active] == "truant":
            vol.add("truant")
        if tm.uproar is not None:
            vol.add("uproar")
            vcounts.setdefault(mon is active, {})["uproar"] = min(tm.uproar, 2)
        if tm.stockpile:
            vol.add("stockpile")
            vcounts.setdefault(mon is active, {})["stockpile"] = tm.stockpile
        if tm.roosted:  # (a mid-turn decision after its Roost)
            vol.add("roost")
        if tm.consecutive and items_now[mon is active] == "metronome":
            vol.add("metronome")
            metronome[mon is active] = tm.consecutive
        # an Illusion in disguise (the engine's volatile: a Transform into it fails, L227): ours
        # when the log shows our active as another species; theirs in a world that drew the
        # Zoroark (2026-10-23, the state-construction differential: never passed)
        if mon is active and mon is not None and tm.active and tm.active != tm.k(to_id(mon.species)) \
                and to_id(mon.species).startswith("zoroark"):
            vol.add("illusion")
        if mon is opp_active and zi is not None:
            vol.add("illusion")
        if tm.item_lost and ab[mon is active] == "unburden":
            vol.add("unburden")
        if tm.locked:
            vol.add("lockedmove")
            # (the engine's count: its ends of turn, the length drawn at the first one --
            # Showdown's 2 or 3 uses, hidden: this world's draw; a second use: 3 for sure)
            locked[mon is active] = 2 if tm.locked[1] >= 2 or rng.random() < 0.5 else 1
    # a lock's other moves disabled (the engine's flags, as the differential's states have them,
    # L179; ours at the live root: the request's)
    for mons, i, tm, mine in ((their_mons, their_idx, tm_them, False),
                              (our_mons, our_active_idx, tm_us, True)):  # fmt: skip
        if tm.locked and i is not None and i < len(mons) and not (mine and spectator is None):
            m = mons[i]
            mons[i] = _with(m, moves=[pe.Move(id=x.id, pp=x.pp, disabled=x.disabled or x.id != tm.locked[0])
                                      for x in m.moves])  # fmt: skip
    # Disable (L70): its volatile and its move's slot and count, not the move's flag alone (the
    # engine's next move enabled it again; 2026-10-23 review)
    disable = {}
    for who, mon, vol, tm, mons, i in (
        ("us", active, our_vol, tm_us, our_mons, our_active_idx),
        ("them", opp_active, their_vol, tm_them, their_mons, their_idx),
    ):
        ok = mon is not None and i is not None and i < len(mons)
        ids = [m.id for m in mons[i].moves] if ok else []
        if tm.disabled is not None and tm.disabled in ids:
            vol.add("disable")
            disable[who] = ids.index(tm.disabled) * 8 + min(tm.disable_ends, 4)
    # the items of the mons that set a screen / the weather / the terrain (ours known -- a replay's
    # own side: its set, 2026-10-23 review: none, 5 turns --, theirs this world's sample): an
    # extending item makes it 8 turns. The item it set it with: changed since, the timers' (the
    # duration is fixed as it starts; 2026-10-23 review: a Light Clay knocked off cut it to 5)
    items = {("us", to_id(m.species)): (p.item or "") for m, p in zip(ours, our_mons, strict=True)}
    items |= {("them", to_id(m.species)): st.item for m, st in zip(theirs, their_sets, strict=True)}

    def set_with(who: str, tm: SideTimers, key: str, sp: str) -> str:
        if key in tm.set_items:
            return tm.set_items[key]
        mine = (who == "us") != (key in tm.swapped)  # (the setter's side)
        mon = next((p for m, p in zip(ours if mine else theirs, our_mons if mine else their_mons,
                                      strict=True) if to_id(m.species) == sp), None)  # fmt: skip
        if mon is not None and str(mon.ability).lower() == "klutz":
            return ""  # (a Klutz holder's item does nothing: this world's ability)
        # (a Court Change put the other side's screen here: its setter is of that side)
        other = "them" if who == "us" else "us"
        if key in tm.swapped:
            return items.get((other, sp), "")
        return items.get((who, sp)) or items.get((other, sp), "")

    clay_us, clay_them = (
        frozenset(k for k, sp in tm.setters.items()
                  if k in SCREENS and set_with(who, tm, k, sp) == "lightclay")
        for who, tm in (("us", tm_us), ("them", tm_them))
    )  # fmt: skip
    ext = {}
    for who, tm in (("us", tm_us), ("them", tm_them)):
        for kind in ("weather", "terrain"):
            if kind in tm.setters:
                what, sp = tm.setters[kind]
                item = set_with(who, tm, kind, sp)
                if EXTENDERS.get(what) == item or (kind == "terrain" and item == "terrainextender"):
                    ext[kind] = 8

    our_mons = _formes(battle.team, ours, our_mons, tm_us)
    their_mons = _formes(battle.opponent_team, theirs, their_mons, tm_them)
    # (the actives' abilities as a move / ability changed them this time in, a Gastro Acid's none
    # -- poke-env keeps no temporary ability for them; the timers')
    for ms, i, tm in ((our_mons, our_active_idx, tm_us), (their_mons, their_idx, tm_them)):
        if tm.ability_now and i is not None and i < len(ms) and ms[i].hp > 0:
            ms[i] = _with(ms[i], ability=tm.ability_now)
    # (a mon Revival Blessing brought back is no longer terastallized -- Showdown clears it;
    # the side's used Terastallization its own marker, L185; 2026-10-23, the differential)
    for ms, src, tm in ((our_mons, ours, tm_us), (their_mons, theirs, tm_them)):
        for j, (m, p) in enumerate(zip(src, ms, strict=True)):
            if p.terastallized and tm.k(to_id(m.species)) in tm.revived:
                ms[j] = _with(p, terastallized=False)
    # (L177: a side's Terastallization used by a mon that fainted since: the engine reads it off
    # its mons, can_use_tera)
    our_mons = _tera_used(our_mons, bool(getattr(battle, "used_tera", False)))
    their_mons = _tera_used(their_mons, bool(getattr(battle, "opponent_used_tera", False)))
    side_one = pe.Side(
        pokemon=_pad(our_mons),
        active_index=pe.PokemonIndex(str(our_idx)),
        side_conditions=_side_conditions(
            battle.side_conditions, turn, *_counts(tm_us, active), clay_us, tm_us.side_elapsed
        ),
        volatile_statuses=our_vol,
        **_timed(tm_us, active, ours, our_mons, our_vol, disable.get("us"), locked.get(True),
                 metronome.get(True), vcounts.get(True)),
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
            else _passed_sub(tm_us, ours, our_mons)
        ),
        # the engine's force_switch is a switch in the middle of the turn (a pivot, an Eject
        # Button: the foe waits, its saved move); a fainted active's replacement is its own phase
        # from the HP (both sides at once when both fainted) -- 2026-10-22 review: a double KO's
        # replacements were built as ours first, the foe choosing after seeing it
        force_switch=(bool(battle.force_switch) if force_switch is None else force_switch)
        and not (active is not None and active.fainted),
        **_side_tera_used(our_mons, bool(getattr(battle, "used_tera", False))),
        **our_last,
        # (a replay's disguised / broken Illusion's boosts: poke-env gave them to the disguise;
        # live, the request's active is the Zoroark and poke-env keeps them there)
        **(_boosts(active, (tm_us.stint["boosts"] if our_disguised else tm_us.illusion_boosts)
                   if spectator is not None else None)
           if active is not None else {}),
    )
    # 2026-10-22 review: our switch in the middle of the turn (a pivot of ours went first, an
    # Eject Button) and the opponent not acted yet: its move comes after our switch-in (the
    # engine's saved move, as its own tree does after a U-turn); it was none -- the opponent did
    # nothing that turn and the switch-in took no hit (Garchomp's U-turn, Dondozo in: 0 against
    # 127-191 from a waiting Make It Rain)
    our_switch = bool(battle.force_switch) if force_switch is None else force_switch
    waiting = bool(our_switch and active is not None and not active.fainted and their_mons
                   and opp_active is not None and not opp_active.fainted and not tm_them.acted
                   and not tm_them.switched_now and not tm_them.recharge)  # fmt: skip
    side_two = pe.Side(
        pokemon=_pad(their_mons),
        active_index=pe.PokemonIndex(str(their_idx)),
        side_conditions=_side_conditions(
            battle.opponent_side_conditions, turn, *_counts(tm_them, opp_active), clay_them,
            tm_them.side_elapsed,
        ),
        volatile_statuses=their_vol,
        **_timed(tm_them, opp_active, theirs, their_mons, their_vol, disable.get("them"),
                 locked.get(False), metronome.get(False), vcounts.get(False)),
        substitute_health=(
            their_mons[their_idx].maxhp // 4 // (2 if tm_them.sub_hit else 1)
            if opp_active is not None and Effect.SUBSTITUTE in opp_active.effects
            else _passed_sub(tm_them, theirs, their_mons)
        ),
        **_side_tera_used(their_mons, bool(getattr(battle, "opponent_used_tera", False))),
        **their_last,
        **(_boosts(opp_active, tm_them.illusion_boosts) if opp_active is not None else {}),
    )

    def field_left(kind: str, start: int) -> int:
        # ends of turn counted by the timers (doc/engine-diff.md L3; the rooms too, 2026-10-23);
        # poke-env's start turn only if the log never showed it start
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
            trick_room, trturns = True, field_left("trickroom", start)
    # Gravity / Magic Room: the engine has them (L211 and others, its remaining turns as Trick
    # Room's); they were never passed in (2026-10-22 review: grounding, accuracy, items)
    gravity = field_left("gravity", battle.fields[Field.GRAVITY]) if Field.GRAVITY in battle.fields else 0
    magic_room = (field_left("magicroom", battle.fields[Field.MAGIC_ROOM])
                  if Field.MAGIC_ROOM in battle.fields else 0)  # fmt: skip
    st = pe.State(
        side_one=side_one,
        side_two=side_two,
        weather=pe.Weather(weather),
        weather_turns_remaining=wturns,
        terrain=pe.Terrain(terrain),
        terrain_turns_remaining=tturns,
        trick_room=trick_room,
        trick_room_turns_remaining=trturns,
        last_move=tm_us.last_move or "none",  # (L167: Copycat's; an unknown one reads as none)
        gravity=gravity,
        magic_room=magic_room,
    )
    if waiting:
        # (its legal moves no faster than our move that went first: the engine's,
        # alpha_search.pending_moves -- not the turn start's options: a Taunt's status moves, a
        # Protect that would have come before our U-turn)
        ours = tm_us.last_move if tm_us.just_moved else ""
        legal = alpha_search.pending_moves(st.to_string(), ours)
        pending = _pending_move(their_mons[their_idx], their_last, their_vol, foe_pending, rng,
                                legal)  # fmt: skip
        if pending != "none":
            st = _with_saved_move(st, pending)
    # F1: a turn start's world is the base of that turn's hits (not a mid-turn switch's)
    if spectator is None and not (battle.force_switch if force_switch is None else force_switch):
        record_base(battle, st.to_string())
    return st


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
