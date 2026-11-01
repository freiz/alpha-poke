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

import alpha_search
import numpy as np
import poke_engine as pe
from poke_env.battle import Effect, Field, SideCondition, Status, Weather
from poke_env.battle.move import Move
from poke_env.data import GenData

from alpha_poke.agents import (
    poke_env_fixes,  # noqa: F401 (poke-env's tracking fixed on import)
    slots,
)
from alpha_poke.agents.belief_state import BeliefModel, _preview_name, ability_probs
from alpha_poke.agents.damage import Spread, calc_stats
from alpha_poke.agents.damage_obs import damage_posteriors, record_base
from alpha_poke.agents.pokeview import (
    copied_ability,
    copied_pp,
    current_ability,
    current_moves,
    engine_ability,
    last_used_move,
    own_ability,
    own_base_stats,
    own_moves,
    own_stats,
    own_weight,
)
from alpha_poke.agents.speed import battle_observations, consistent, spe_stat, spread_dist
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


def _status(mid: str) -> bool:
    """A status move (an Assault Vest holder cannot choose one)."""
    return (_MOVES.get(mid) or {}).get("category") == "Status"


def _types(mon) -> tuple[str, str]:
    # the non-tera types: the engine keeps them when terastallized, STAB on them (tera_type
    # apart: has_type reads only it), as Showdown's getTypes(false, true) (L31)
    # (Showdown's "???" -- Double Shock's, Burn Up's -- poke-env's THREE_QUESTION_MARKS: the
    # engine's typeless; 2026-10-24, the state check's types)
    ts = [
        "typeless" if t.name == "THREE_QUESTION_MARKS" else t.name.lower()
        for t in mon.base_types
        if t is not None
    ]
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
    # (S158: the spread's -- the engine recomputes stats from them on a forme change, a confusion
    # berry reads the nature; our states had neither)
    nature: str = "serious"
    evs: tuple | None = None
    # (S158: the forme a hidden one's set makes it -- Greninja-Bond by Battle Bond, Zacian-Crowned
    # by its Rusted Sword: resolve_forme; None, its own)
    forme: str | None = None


@dataclass
class KnownSet:
    """What a player knows of its own mon although the battle has not shown it yet (training
    positions from replays: everything the mon revealed during the whole game)."""

    moves: list[str]  # move ids
    item: str | None = None  # item id (the original item)
    ability: str | None = None
    tera: str | None = None  # tera type, lower case
    # (the whole set, from the player's own team -- a game review with the team pasted: nothing
    # of it sampled)
    nature: str | None = None
    evs: tuple[int, ...] | None = None
    ivs: tuple[int, ...] | None = None
    # (two moves in one stint on the field, its item the same: it holds no Choice item --
    # train.positions.choice_free; issue #28, a replay's own side now locked by the item it drew)
    no_choice: bool = False
    # (the whole set given -- a pasted team: no item is none, fewer than four moves are all;
    # nothing drawn. 2026-10-30 review: a pasted itemless three-move Dragonite drew Boots, Roost)
    exact: bool = False


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


def _prior(
    belief: BeliefModel, species: str, team_names: tuple[str, ...], mix: float | None = None
):
    """``belief.prior.predict``, cached: deterministic, and the same mon and team at every world
    of every decision (2026-10-11: 14% of a policy-only worker). Read-only for the callers. Mix 0
    (the belief before 2026-10-25): without the fallback prior of a species OU's usage lacks."""
    from alpha_poke.belief.priors import FALLBACK

    fallback = (mix if mix is not None else ARCH_MIX) > 0
    key = (id(belief), species, team_names, fallback)
    dist = _PRIORS.get(key)
    if dist is None:
        if len(_PRIORS) > 20_000:  # (a few KB each: bounded)
            _PRIORS.clear()
        token = FALLBACK.set(fallback)
        try:
            dist = _PRIORS[key] = belief.prior.predict(species, team_names)
        finally:
            FALLBACK.reset(token)
    return dist


# The item / tera an archetype is drawn with: its weights mixed with a base marginal (ARCH_MIX of
# it) -- the archetypes are mined from replays, which show an item only when it reveals itself
# (Leftovers, Rocky Helmet, a Focus Sash: yes; Heavy-Duty Boots, Soul Dew: hardly ever) and a tera
# type only when used: a Latias's Soul Dew, a Cramorant's Boots had no weight at all. The base is
# half the team prior's (its replay counts the same bias, its support the widest) and half
# Smogon's usage (the teams' own items). 2026-10-25, the catalog's 1,170 OU teams with two moves
# shown: item NLL 1.93 -> 1.65, top-1 0.48 -> 0.51, the true one at 0 5.6% -> 1.2%; tera NLL 2.49
# -> 2.14, at 0 12% -> 3.3%.
ARCH_MIX = 0.6
# A floor under the base: FLOOR of its mass on what no set of the species was seen with -- OU's
# items across species, every tera type, the species' learnset -- so a true off-meta set is never
# impossible to the belief (its evidence can find it), and hardly ever drawn (2026-10-25, the
# belief check's prior support: 3% of its gaps a value no OU set of the species uses)
FLOOR = 1e-3
_BASES: dict = {}


def _smogon(belief: BeliefModel):
    from alpha_poke.belief.priors import SmogonPrior

    p = belief.prior
    while not isinstance(p, SmogonPrior) and hasattr(p, "base"):
        p = p.base
    return p if isinstance(p, SmogonPrior) else None


def base_marginal(
    belief: BeliefModel,
    species: str,
    team_names: tuple[str, ...],
    attr: str,
    mix: float | None = None,
) -> dict:
    """``attr`` ("item" / "tera") of a species in a team: half the team prior's, half Smogon's
    (each normalized; one alone if the other has none), ids as keys -- the team prior's alone at
    ``mix`` 0 (the belief before 2026-10-25, for A/B). Cached, read-only."""
    old = (mix if mix is not None else ARCH_MIX) <= 0
    key = (id(belief), species, team_names, attr, old)
    out = _BASES.get(key)
    if out is None:
        if len(_BASES) > 20_000:
            _BASES.clear()
        parts = [getattr(_prior(belief, species, team_names, mix), attr)]
        sm = _smogon(belief)
        if sm is not None and not old:
            parts.append(getattr(sm.predict(species, team_names), attr))
        parts = [d for d in parts if sum(d.values()) > 0]
        out = {}
        for d in parts:
            t = sum(d.values())
            for k, v in d.items():
                out[to_id(k)] = out.get(to_id(k), 0.0) + v / t / len(parts)
        if not old and sm is not None:  # (the floor)
            from alpha_poke.belief.priors import TYPES, items_for

            floor = items_for(to_id(species), sm.global_item) if attr == "item" \
                else {x: 1.0 / len(TYPES) for x in TYPES}  # fmt: skip
            if attr == "item":  # (and the items made for it: Palkia's Lustrous Orb)
                from alpha_poke.belief.priors import signature_items

                own = [
                    i
                    for k, v in signature_items().items()
                    if to_id(species).startswith(k)
                    for i in v
                ]
                if own:
                    floor = {k: 0.5 * v for k, v in floor.items()}
                    for i in own:
                        floor[i] = floor.get(i, 0.0) + 0.5 / len(own)
            if out:
                out = {k: (1 - FLOOR) * v for k, v in out.items()}
                for k, v in floor.items():
                    out[k] = out.get(k, 0.0) + FLOOR * v
            else:
                out = dict(floor)
        _BASES[key] = out
    return out


def required_item(mon) -> str | None:
    """The item a forme is made by (Showdown's requiredItem: Zamazenta-Crowned's Rusted Shield,
    an Ogerpon mask; requiredItems, its Gen 9 one: an Arceus forme's Plate, not its Z-Crystal --
    2026-10-25 review): its item for sure."""
    from alpha_poke.belief.priors import standard_items

    entry = GEN.pokedex.get(to_id(mon.species)) or {}
    if entry.get("requiredItem"):
        return to_id(entry["requiredItem"])
    legal = [to_id(x) for x in entry.get("requiredItems") or [] if to_id(x) in standard_items()]
    return legal[0] if len(legal) == 1 else None


def _move_floor(weights: dict, species: str) -> dict:
    """``weights`` with FLOOR of their total spread over the species' other legal moves -- those
    without weight, a 0 one too (an archetype's vocabulary lists its species' moves at 0: they
    stayed impossible -- 2026-10-25, seen once the belief check read the sampler's own weights)."""
    from alpha_poke.belief.priors import legal_moves

    rest = [m for m in legal_moves(species) if weights.get(m, 0.0) <= 0]
    total = sum(weights.values())
    if not rest:
        return weights
    out = dict(weights)
    share = (FLOOR * total if total > 0 else 1.0) / len(rest)
    for m in rest:
        out[m] = share
    return out


def move_weights(
    ss, k: int | None, dist, species: str, move_beta: float, mix: float | None = None
) -> dict:
    """The moves ``sample_set`` draws from (unnormalized): archetype ``k``'s weights (times the
    prior's ** ``move_beta``), else the prior's; the floor under them (``_move_floor``) when the
    mix is on. The belief check's move support is these (2026-10-25 review: it re-derived them)."""
    if k is not None and ss is not None and ss.vocab.get("move"):
        weights = {
            to_id(n): float(w) for n, w in zip(ss.vocab["move"], ss.params["move"][k], strict=False)
        }
        if move_beta > 0:
            weights = {mid: w * dist.move.get(mid, 1e-4) ** move_beta for mid, w in weights.items()}
    else:
        weights = dict(dist.move)
    if (mix if mix is not None else ARCH_MIX) > 0:  # (the floor: its learnset's other moves)
        weights = _move_floor(weights, species)
    return weights


def arch_mix(ss, k: int, attr: str, base: dict, mix: float | None = None) -> dict:
    """Archetype ``k``'s ``attr`` weights (normalized) mixed with ``base`` (``mix`` of it, ARCH_MIX
    if None): ids as keys."""
    w = np.asarray(ss.params[attr][k], dtype=float)
    total = float(w.sum())
    lam = (mix if mix is not None else ARCH_MIX) if base else 0.0
    out = {key: lam * v for key, v in base.items()} if lam > 0 else {}
    if total > 0:
        for n, v in zip(ss.vocab[attr], w, strict=False):
            out[to_id(n)] = out.get(to_id(n), 0.0) + (1 - lam) * float(v) / total
    return out


# Raking (2026-10-31, issue #33): the archetypes are mined from replays and the team prior counts
# them, so the drawn items lean to the ones that reveal themselves (Life Orb, Leftovers, Booster
# Energy, Air Balloon) and away from the silent ones (Choice Specs / Scarf, Heavy-Duty Boots,
# Assault Vest): at preview, 0.23 of 14 top species' item mass misplaced against Smogon's usage
# (Dragapult's Specs 0.21 for 0.50). Smogon counts the teams' own sets, shown or not. One factor
# per value (``rake_factors``), multiplied into every archetype's item / tera weights, makes the
# drawn marginal with nothing revealed the usage's (iterative proportional fitting over the
# archetypes' prior mix): which items go with which moves stays the archetypes', the marginal
# is the ladder's. On a belief with ``rake`` set (off by default until its search A/B).
RAKE_ITERS = 30
_RAKES: dict = {}


def rake_factors(belief: BeliefModel, species: str, attr: str, mix: float | None = None) -> dict:
    """Value id -> the factor its drawn weight is multiplied by ({}: none -- the belief's
    ``rake`` off, the old belief at ``mix`` 0, or no usage for the species). Cached."""
    if not getattr(belief, "rake", False) or (mix if mix is not None else ARCH_MIX) <= 0:
        return {}
    key = (id(belief), species, attr)
    c = _RAKES.get(key)
    if c is None:
        if len(_RAKES) > 20_000:
            _RAKES.clear()
        c = _RAKES[key] = _fit_rake(belief, species, attr)
    return c


def raked(weights: dict, factors: dict) -> dict:
    return {k: v * factors.get(k, 1.0) for k, v in weights.items()} if factors else weights


def _fit_rake(belief: BeliefModel, species: str, attr: str) -> dict:
    sm = _smogon(belief)
    if sm is None:
        return {}
    usage: dict = {}
    for k, v in getattr(sm.predict(species, (species,)), attr).items():
        k = "none" if to_id(k) == "nothing" else to_id(k)  # (the sampler's no-item)
        usage[k] = usage.get(k, 0.0) + v
    total = sum(usage.values())
    if total <= 0:
        return {}
    # the draw with nothing revealed, the species alone: its archetypes' prior mix of their
    # weights mixed with the base, or the base alone (sample_set's draw)
    base = base_marginal(belief, species, (species,), attr)
    ss = belief.sets.get(species)
    if ss is not None and ss.params and ss.vocab.get(attr):
        post = np.asarray(ss.posterior(), dtype=float)
        post = post / post.sum()
        parts = [(float(p), arch_mix(ss, k, attr, base)) for k, p in enumerate(post) if p > 0]
    else:
        parts = [(1.0, base)]

    def marginal(c: dict) -> dict:
        out: dict = {}
        for p, w in parts:
            z = sum(v * c.get(i, 1.0) for i, v in w.items()) or 1.0
            for i, v in w.items():
                out[i] = out.get(i, 0.0) + p * v * c.get(i, 1.0) / z
        return out

    # the target: the usage, with the FLOOR of the draw's own under it (a value the usage lacks
    # stays possible); a value the draw never makes cannot be scaled up -- left out
    m0 = marginal({})
    target = {i: (1 - FLOOR) * usage.get(i, 0.0) / total + FLOOR * v for i, v in m0.items()}
    t = sum(target.values())
    target = {i: v / t for i, v in target.items()}
    c: dict = {}
    for _ in range(RAKE_ITERS):
        m = marginal(c)
        c = {i: c.get(i, 1.0) * target[i] / m[i] for i in m if m[i] > 0}
    return c


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
    mix: float | None = None,
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
    dist = _prior(belief, species, team_names, mix)
    # (``exclude``: moves its line showed that were a disguised Illusion's: _illusion_fix)
    revealed = [m for m in own_moves(mon) if m in _MOVES and m not in exclude]
    ss = belief.sets.get(species)
    # poke-env: "unknown_item" = not seen yet; None = gone (eaten, knocked off, used up: its
    # end_item) -- no item now (2026-10-11: a gone item was sampled again, so an eaten berry or
    # knocked-off Boots came back in every search)
    gone = mon.item is None
    item = mon.item if mon.item not in (None, "unknown_item") else None
    tera = _tera(mon) if mon.is_terastallized else None
    if known is not None:
        revealed += [m for m in known.moves if m in _MOVES and m not in revealed]
        if item is None and (known.item or known.exact) and not gone:
            item = known.item or "none"
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

    def draw(attr, fallback: dict[str, float], exclude: tuple = ()):
        if k is not None and ss.vocab.get(attr) and attr in ("item", "tera"):
            fallback = arch_mix(ss, k, attr, fallback, mix)  # (its weights with the base: ARCH_MIX)
        if attr in ("item", "tera"):  # (the usage's marginal: rake_factors)
            fallback = raked(fallback, rake_factors(belief, species, attr, mix))
        elif k is not None and ss.vocab.get(attr):
            w = flat(ss.params[attr][k])
            if exclude:
                w = np.where([to_id(n) in exclude for n in ss.vocab[attr]], 0.0, w)
            if w.sum() > 0:
                i = int(np.searchsorted(np.cumsum(w), rng.random() * w.sum()))
                return to_id(ss.vocab[attr][min(i, len(w) - 1)])
        if fallback:
            keys, ws = zip(*flat(fallback).items(), strict=True)
            ws = [0.0 if to_id(key) in exclude else x for key, x in zip(keys, ws, strict=True)]
            if sum(ws) > 0:
                return to_id(rng.choices(keys, weights=ws)[0])
        return None

    item_seen = gone or item is not None
    if gone:
        item = "none"
    elif item is None:
        # (an Assault Vest holder cannot choose a status move: not with one known -- the
        # archetype's item and moves are drawn apart; 2026-10-24, plan C's slot check: a replay's
        # Slowking-Galar with Toxic and Chilly Reception held an Assault Vest, its Toxic no option)
        no_vest = ("assaultvest",) if any(map(_status, revealed)) else ()
        no_choice = CHOICE_ITEMS if known is not None and known.no_choice else ()
        item = (
            (required_item(mon) if (mix if mix is not None else ARCH_MIX) > 0 else None)
            or draw(
                "item", base_marginal(belief, species, team_names, "item", mix), no_vest + no_choice
            )
            or "none"
        )
    if tera is None:
        tera = draw("tera", base_marginal(belief, species, team_names, "tera", mix)) or _tera(mon)
    # (its own: not a temporary one -- Trace's, a Transform's; 2026-10-23 review: the copied
    # Intimidate was its base ability, still on after its switch-out)
    ability = own_ability(mon)
    if ability is None and known is not None and known.ability:
        ability = known.ability
    if ability is None:
        ap = flat(ability_probs(mon))
        ability = (rng.choices(list(ap), weights=list(ap.values()))[0] if ap else None) or "none"
    # moves: revealed + draws (without replacement) from the archetype's move weights
    moves = list(revealed)[:4]
    weights = flat(move_weights(ss, k, dist, to_id(mon.species), move_beta, mix))
    for mid in list(weights):
        if mid in moves or mid not in _MOVES or (item == "assaultvest" and _status(mid)):
            weights.pop(mid)
    while len(moves) < 4 and weights and not (known is not None and known.exact):
        keys, ws = zip(*weights.items(), strict=True)
        if sum(ws) <= 0:
            break
        pick = rng.choices(keys, weights=ws)[0]
        moves.append(pick)
        weights.pop(pick)
    spread = None
    if known is not None and known.nature and known.evs:  # (the player's own team: exact)
        spread = Spread(known.nature, tuple(known.evs))
    if (
        spread is None and dmg_post
    ):  # F1: (item, ability, spread) from the damage posterior (agents/damage_obs.py)
        level = mon.level or 100
        w = [p for *_, p in dmg_post]
        if k is not None and not item_seen and ss.vocab.get("item"):
            # the item consistent with the moves: the candidates' prior is the base marginal
            # (damage_obs._candidates), swapped here for the archetype's item weights mixed with
            # it (the moves drawn below are the archetype's: a Choice Scarf with Nasty Plot
            # otherwise; ARCH_MIX)
            marg = base_marginal(belief, species, team_names, "item", mix)
            arch = flat(arch_mix(ss, k, "item", marg, mix))
            w = [p * arch.get(it, 0.0) / max(marg.get(it, 0.0), 1e-9)
                 for (it, *_), p in zip(dmg_post, w, strict=True)]  # fmt: skip
        if not item_seen and any(map(_status, moves)):  # (no Assault Vest with a status move)
            w = [0.0 if it == "assaultvest" else p for (it, *_), p in zip(dmg_post, w, strict=True)]
        if speed_obs:  # the move order too: an inconsistent spread / item nearly ruled out
            base = own_base_stats(mon)
            # (each turn's in the forme it was in then: a Minior's Meteor, an Eiscue's Noice)
            w = [p * (1.0 if consistent(speed_obs, calc_stats(base, s, level=level)["spe"],
                                        it if not item_seen else item, _forme_stat(s, level)) else 1e-3)
                 for (it, _, s, _), p in zip(dmg_post, w, strict=True)]  # fmt: skip
        if sum(w) > 0:
            it, ab, spread, _ = rng.choices(dmg_post, weights=w)[0]
            if not item_seen:
                item = it
            if own_ability(mon) is None and not (known is not None and known.ability):
                ability = ab
    if spread is None and speed_obs is not None:  # the spread sampled, consistent with the order
        spread, item = _sample_spread(mon, item, item_seen, speed_obs, dist, rng)
    if spread is None:
        spread = belief.spread_for(mon.species)
    sp = to_id(mon.species)
    # (only a mon never in: a switch-in shows its forme -- a "Zacian" seen is no Zacian-Crowned,
    # whatever this world drew; but Greninja-Bond shows as Greninja even then: 2026-10-26 review)
    hidden = sp in HIDDEN_FORMES and (sp == "greninja" or not mon.revealed)
    forme = resolve_forme(sp, item, ability, moves) if hidden else None
    forme = forme if forme != sp else None
    base = (GEN.pokedex.get(forme) or {}).get("baseStats") if forme else None
    ivs = known.ivs if known is not None and known.nature and known.evs else None
    stats = calc_stats(base or own_base_stats(mon), spread, level=mon.level or 100, ivs=ivs)
    return SampledSet(
        moves or ["tackle"], item, ability, tera, stats, spread.nature, tuple(spread.evs), forme
    )


# Showdown's team preview hides these formes ("-*": data/rulesets.ts' onTeamPreview -- Zacian /
# Zamazenta till the Crowned item changes them as the battle begins); a switch-in shows them, but
# Greninja-Bond as "Greninja" (its ability tells). Ours from our team
HIDDEN_FORMES = frozenset({"greninja", "gourgeist", "pumpkaboo", "xerneas", "silvally", "urshifu", "dudunsparce",
                           "zacian", "zamazenta"})  # fmt: skip


@functools.cache
def _forme_candidates(base: str) -> tuple[str, ...]:
    """A species' formes a set can make it: itself and its formes in Gen 9 -- not a Mega, a Gmax,
    nor one only a battle event makes (Greninja-Ash), but one its item makes (Zacian-Crowned)."""
    out = [base]
    for k, e in GEN.pokedex.items():
        if k == base or to_id(e.get("baseSpecies") or "") != base or e.get("isNonstandard"):
            continue
        forme = e.get("forme") or ""
        if (
            "Mega" in forme
            or "Gmax" in forme
            or (e.get("battleOnly") and not e.get("requiredItem"))
        ):
            continue
        out.append(k)
    return tuple(out)


def resolve_forme(base: str, item: str, ability: str, moves) -> str:
    """The forme a set makes a hidden species (HIDDEN_FORMES; S158 -- the engine's: Battle Bond
    works only as Greninja-Bond, a Zacian with its Rusted Sword is Zacian-Crowned): the candidates
    its ability is one of, its item the one a forme requires (else not that forme -- nor the base
    when the item is another's requirement), its moves all legal for; of those the one whose
    abilities are fewest (Battle Bond: Greninja-Bond's alone). None fitting: the base."""
    from alpha_poke.belief.priors import legal_moves

    def fits(c: str) -> bool:
        e = GEN.pokedex.get(c) or {}
        req = to_id(e.get("requiredItem") or "")
        abilities = {to_id(a) for a in (e.get("abilities") or {}).values()}
        if req and to_id(item or "") != req:
            return False
        if not req and any(to_id((GEN.pokedex.get(o) or {}).get("requiredItem") or "") == to_id(item or "")
                           for o in _forme_candidates(base) if o != c):  # fmt: skip
            return False
        if ability and ability != "none" and abilities and to_id(ability) not in abilities:
            return False
        legal = legal_moves(c)
        return not legal or all(to_id(m) in legal for m in moves or ())

    fit = [c for c in _forme_candidates(base) if fits(c)]
    if not fit:
        return base
    return min(
        fit, key=lambda c: (len((GEN.pokedex.get(c) or {}).get("abilities") or {}), c != base)
    )


_SPREAD_SPEEDS: dict = {}  # (species, level) -> the speed stat of each usage spread


def _forme_stat(spread, level: int):
    """A spread's speed stat in a forme of the given base speed (speed.consistent's stat_of)."""
    return lambda base: spe_stat(base, spread.evs[5], spread.nature, level)


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
            speeds = [calc_stats(own_base_stats(mon), s, level=level)["spe"] for s in spreads]
            _SPREAD_SPEEDS[key] = speeds
        for it in (item,) if item_seen else (item, "choicescarf"):
            if it == "choicescarf" and it != item and dist.item.get("choicescarf", 0) <= 0:
                continue
            ok = [
                i
                for i, sp in enumerate(speeds)
                if consistent(obs, sp, it, _forme_stat(spreads[i], level))
            ]
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
                     clay: frozenset = frozenset(), elapsed: dict | None = None,
                     healing_wish: int = 0) -> pe.SideConditions:  # fmt: skip
    """``clay``: the screens (reflect, lightscreen, auroraveil) set by a Light Clay holder: 8
    turns. ``elapsed``: the timed conditions' ends of turn so far (the timers' side_elapsed;
    poke-env's start turn when the log never showed one start). ``healing_wish``: the timers'
    (1 Healing Wish, 2 Lunar Dance waiting on the slot)."""
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
        light_screen=left(
            SideCondition.LIGHT_SCREEN, "lightscreen", 8 if "lightscreen" in clay else 5
        ),
        aurora_veil=left(SideCondition.AURORA_VEIL, "auroraveil", 8 if "auroraveil" in clay else 5),
        tailwind=left(SideCondition.TAILWIND, "tailwind", 4),
        # (the engine has them: 2026-10-23, the state-construction differential -- never passed)
        safeguard=left(SideCondition.SAFEGUARD, "safeguard", 5),
        mist=left(SideCondition.MIST, "mist", 5),
        # (S158: never passed -- a Healing Wish waiting for a mon that needs it, Gen 9's)
        healing_wish=healing_wish,
        # (L226: the damaging hazards laid before the Toxic Spikes, their order on switching in --
        # Showdown's conditions in the order they came, poke-env's dict too; never passed: S158c)
        toxic_spikes_order=_toxic_spikes_order(sc),
    )


def _toxic_spikes_order(sc: dict) -> int:
    """1 Stealth Rock, 2 Spikes: those laid before the Toxic Spikes (the engine's
    toxic_spikes_order)."""
    keys = list(sc)
    if SideCondition.TOXIC_SPIKES not in keys:
        return 0
    before = keys[: keys.index(SideCondition.TOXIC_SPIKES)]
    return (SideCondition.STEALTH_ROCK in before) | (SideCondition.SPIKES in before) << 1


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


def _once_used(mon, ability: str, tm: SideTimers | None) -> bool:
    """A once-per-battle ability it used as a copy (transformed: Showdown's swordBoost /
    shieldBoost on the mon -- a Ditto's second Dauntless Shield does nothing; the engine's
    once_used, L227; its own one's: _base_ability's none). S158: never passed."""
    return (tm is not None and ability not in ("dauntlessshield", "battlebond", "supersweetsyrup", "intrepidsword")
            and tm.k(to_id(mon.species)) in tm.used_once)  # fmt: skip


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
        # (one already built as Greninja-Bond -- a hidden forme's resolve_forme -- stays so: the
        # shown "Greninja" is the disguise of its forme; 2026-10-26 review, it went back to Greninja)
        if p.id.lower() in ("greninja", "greninjabond") and str(p.ability).lower() == "battlebond":
            f = "greninjabond"
        if f and f != p.id.lower() and not m.transformed and engine_species(f):
            # (its weight its forme's: Showdown's formeChange sets the species' -- Minior's
            # Meteor 40 kg, its core 0.3; 2026-10-24, the differential's weight check)
            w = (GEN.pokedex.get(f) or {}).get("weightkg")
            out[j] = _with(p, id=f, weight_kg=float(w) if w else p.weight_kg)
    return out


@functools.cache
def _move_kinds() -> dict:
    """Move id -> (category, flags) from the engine's data (alpha_search.engine_data)."""
    rows, _ = alpha_search.engine_data()
    return {r[0].lower(): (r[3], set(r[-1].split(","))) for r in rows}


# (L242) the locking moves a calling move can run -- the engine's genx::state::CALLED_LOCKS, its
# order (volatile_status_durations.calledlock - 1) -- and the calling moves whose slot runs one
# (Side::caller_slot; the differential's choice too)
CALLED_LOCKS = ("outrage", "thrash", "petaldance", "ragingfury", "uproar", "rollout", "iceball")
# (L224: the moves that call another -- a charge move one starts locks into the caller's slot)
CALLERS = ("metronome", "copycat", "assist", "mefirst", "naturepower", "mirrormove")


def derived_disable(move: str, *, taunt: bool, healblock: bool, throatchop: bool, item: str,
                    last_move: str, lock: str = "", disabled: str = "",
                    charging: str = "", recharge: bool = False, pp: int = 1,
                    encore: bool = False) -> bool:  # fmt: skip
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
    if (
        (taunt and cat == "Status")
        or (healblock and "heal" in flags)
        or (throatchop and "sound" in flags)
        or (item == "assaultvest" and cat == "Status")
        or (move in ("gigatonhammer", "bloodmoon") and last_move == move)
    ):
        return True  # (the differential's own: these before an Encore's flag)
    if encore:  # (Encore keeps the others out by their flags too)
        return False
    # (a charge's second turn, a recharge, out of PP: the engine's own too -- with no flag reason
    # above. Not an Uproar's lock: the engine keeps it by the flags, as lockedmove's -- L241)
    return bool((charging and move != charging) or recharge or pp <= 0)


def _sleep(mon, tm: SideTimers | None) -> dict:
    """rest_turns / sleep_turns of an asleep mon (timers), else nothing."""
    if tm is None or STATUS.get(mon.status) != "sleep":
        return {}
    rest, sleep = tm.rest_sleep(tm.k(to_id(mon.species)))
    return {"rest_turns": rest, "sleep_turns": sleep}


def _exact_side(spectator: SpectatorSide) -> bool:
    """Every set of a replay's side given whole (its team pasted: KnownSet.exact)."""
    return bool(spectator.known) and all(k.exact for k in spectator.known.values())


def _exact_speed(battle, spectator: SpectatorSide):
    """ObsTracker's our_speed for a replay's side with exact sets: (speed stat, item id, ability
    id) of a species -- its item as the log has it by then (Knock Off, Trick), else its own."""

    def speed(sp: str) -> tuple:
        known = spectator.known.get(sp)
        mon = next((m for m in battle.team.values() if to_id(m.species) == sp), None)
        if known is None or mon is None or not (known.nature and known.evs):
            return 0, "", ""
        spe = calc_stats(own_base_stats(mon), Spread(known.nature, tuple(known.evs)), level=mon.level or 100,
                         ivs=known.ivs)["spe"]  # fmt: skip
        item = (
            ""
            if mon.item is None
            else mon.item
            if mon.item != "unknown_item"
            else (known.item or "")
        )
        return spe, item, to_id(current_ability(mon) or known.ability or "")

    return speed


def _own_set(battle, mon) -> tuple | None:
    """(nature, EVs) of our mon from our team (``battle._alpha_own_sets``: species id -> them, the
    players' -- KnowledgePlayer -- and the differential's: no request names them; S158)."""
    sets = getattr(battle, "_alpha_own_sets", None) or {}
    # (its nickname first -- the team's key, a transformed mon's species its target's)
    nick = next((to_id(k.split(": ", 1)[-1]) for k, v in battle.team.items() if v is mon), "")
    sp = to_id(mon.species)
    return sets.get(nick) or sets.get(sp) or next(
        (v for k, v in sets.items() if sp.startswith(k) or k.startswith(sp)), None)  # fmt: skip


def _our_mon(
    mon,
    available_moves: set[str] | None,
    tm: SideTimers | None = None,
    req_pp: dict | None = None,
    revived: bool = False,
    pp_adj: dict | None = None,
    imprisoned: frozenset = frozenset(),
    own_set: tuple | None = None,
) -> pe.Pokemon:
    """``req_pp``: the request's PP of the active's moves (exact; poke-env counts uses itself and
    drifts low over long games: 2026-10-11, a move with PP left was 0 in the engine, no legal
    option); a move the request offers has PP. ``revived``: a fainted mon brought back at half
    HP (Revival Blessing's choice)."""
    stats = own_stats(mon)
    moves = []
    if mon.transformed:  # its own moves (the request's are the copied ones: _as_transformed)
        available_moves = req_pp = None
    last = last_used_move(mon)
    # (after a Struggle -- its locked move out of PP -- the lock's move is the one it chose: the
    # timers'; poke-env's last used one is not -- 2026-10-23, S70: a Taunt's flag on top)
    chosen = tm.own_last if tm is not None and tm.struggled and tm.own_last else last
    lock = chosen if ((mon.item in CHOICE_ITEMS and not (tm is not None and tm.item_new))
                    or current_ability(mon) == "gorillatactics") else ""  # fmt: skip
    if tm is not None and tm.locked and mon.active:
        # (a locking move's: its flags first -- L179; a Taunt on top derives none)
        lock = tm.locked[0]
    own = own_moves(mon)
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
        # (offered: 1 at least -- poke-env's count drifts; not a lock's move, which the request names
        # without its PP whatever it is: at 0 too -- L243, an Uproar Spite drained)
        if available_moves is not None and mid in available_moves and not (req_pp and mid in req_pp
                                                                           and req_pp[mid] is None):  # fmt: skip
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
                recharge=tm.recharge, pp=pp, encore=tm.encore is not None))  # fmt: skip
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
        ability=current_ability(mon) or "none",
        base_ability=_base_ability(mon, own_ability(mon) or "none", tm),
        once_used=_once_used(mon, own_ability(mon) or "none", tm),
        item=mon.item or "none",
        attack=int(stats.get("atk") or 100),
        defense=int(stats.get("def") or 100),
        special_attack=int(stats.get("spa") or 100),
        special_defense=int(stats.get("spd") or 100),
        speed=int(stats.get("spe") or 100),
        status="none" if revived else STATUS.get(mon.status, "none"),
        weight_kg=own_weight(mon),
        moves=moves,
        terastallized=bool((mon._last_request or {}).get("terastallized"))
        if "terastallized" in (getattr(mon, "_last_request", None) or {})
        else mon.is_terastallized,
        # (the request's tera type: a switch line's tera: details went to the mon a disguised
        # Illusion showed -- 2026-10-23, the state-construction differential)
        tera_type=to_id((getattr(mon, "_last_request", None) or {}).get("teraType") or "")
        or _tera(mon),
        **({"nature": own_set[0], "evs": tuple(own_set[1])} if own_set else {}),
        **_sleep(mon, tm),
        **_counted(mon, tm),
    )


def _counted(mon, tm: SideTimers | None) -> dict:
    """The engine's times attacked (Rage Fist) and gender (0 none, 1 male, 2 female; Attract,
    Cute Charm) of a mon (doc/engine-diff.md L163), a Stellar tera's boosted types (L175)."""
    gender = {"MALE": 1, "FEMALE": 2}.get(getattr(getattr(mon, "gender", None), "name", ""), 0)
    hits = tm.times_attacked.get(tm.k(to_id(mon.species)), 0) if tm is not None else 0
    # (L175: a Stellar tera's types already boosted: its damaging moves' since; Tera Blast's Stellar.
    # Not a Terapagos -- Stellar-terastallized it is Terapagos-Stellar, which Showdown never marks:
    # its boost each time; 2026-10-25, the chain from our own state)
    boosted = set()
    stellar_moves = () if to_id(mon.species).startswith("terapagos") else (
        tm.stellar_moves.get(tm.k(to_id(mon.species)), ()) if tm is not None else ())  # fmt: skip
    for m in stellar_moves:
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
        hp, _, back, _ = dis[id(m)]
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
        # (the PP the uses took -- a Pressure foe's 2: S143)
        cost = collections.Counter()
        for mv, c in zip(f["moves"], f.get("costs") or [1] * len(f["moves"]), strict=False):
            cost[mv] += c
        zuses.update(cost)
        if m is None or m is zoroark:
            continue
        own = tm.moves_by_nick.get(f["nick"], collections.Counter())
        hp, ex, back, n = dis.get(
            id(m), (f["hp"], set(), collections.Counter(), collections.Counter())
        )
        back.update(cost)
        n.update(uses)
        ex |= {mv for mv in uses if own[mv] - n[mv] <= 0}
        dis[id(m)] = (hp, ex, back, n)
    z = {id(zoroark): zuses} if zoroark is not None and zuses else {}
    return dis, z, (tm.illusion_boosts if not current else {})


def _pp(mon, mid: str) -> int:
    """The PP of an opponent's move: poke-env counts its uses (Pressure included; not the turns
    of a locked move) of a revealed move; an unrevealed one has its maximum (PP Ups)."""
    mv = own_moves(mon).get(mid)
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
            hp = max(
                1,
                round(int(cur) / max(int("".join(c for c in tot if c.isdigit()) or 1), 1) * maxhp),
            )
    elif not mon.max_hp:
        # never on the field (team preview only): poke-env reports an HP fraction of 0; the
        # mon is at full HP (before 2026-10-06 this gave it 1 HP in every search)
        hp = maxhp
    else:
        hp = max(1, round(mon.current_hp_fraction * maxhp))
        # a Regenerator that switched out (a benched mon seen before): a third back, silently --
        # poke-env adds it only when it knew the ability (2026-10-23, the state-construction
        # differential: this world's Regenerator healed nothing)
        regen = s.ability == "regenerator" and current_ability(mon) != "regenerator"
        if regen and not mon.active and not (
                tm is not None and tm.k(to_id(mon.species)) in tm.no_regen):  # fmt: skip
            hp = min(maxhp, hp + maxhp // 3)
    return pe.Pokemon(
        id=s.forme or mon.species,
        level=mon.level or 100,
        # (a hidden forme's: its own types -- Zacian-Crowned's Steel; S158 -- unless they changed:
        # a Protean Greninja's, poke-env's then; the full belief check, an Ice Beam with no STAB)
        types=(
            _base_types(s.forme)
            if s.forme and _types(mon) == _base_types(mon.species)
            else _types(mon)
        ),
        base_types=_base_types(s.forme or mon.species),
        hp=hp,
        maxhp=maxhp,
        ability=engine_ability(mon, s.ability),
        base_ability=_base_ability(mon, s.ability, tm),
        once_used=_once_used(mon, s.ability, tm),
        item=s.item,
        attack=s.stats["atk"],
        defense=s.stats["def"],
        special_attack=s.stats["spa"],
        special_defense=s.stats["spd"],
        speed=s.stats["spe"],
        status=STATUS.get(mon.status, "none"),
        weight_kg=float((GEN.pokedex.get(s.forme) or {}).get("weightkg") or own_weight(mon))
        if s.forme
        else own_weight(mon),
        moves=[
            pe.Move(
                id=m,
                pp=max(0, min(_max_pp(m), _pp(mon, m) + pp_adj.get(m, 0)) - _spited(tm, mon, m)),
                disabled=m == disabled,
            )
            for m in s.moves[:4]
        ],  # fmt: skip
        terastallized=mon.is_terastallized,
        tera_type=s.tera,
        nature=s.nature,
        **({"evs": tuple(s.evs)} if s.evs else {}),
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
            "transform_backup", "once_used", "mega_evolved")  # fmt: skip
    # (and its nature, EVs: S158 -- a copy lost them)
    kept = {"nature": str(p.nature).lower(), "evs": tuple(p.evs)}
    return pe.Pokemon(**({k: getattr(p, k) for k in keys} | kept | kw))


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


def _sp_id(p: pe.Pokemon) -> str:
    return to_id(str(p.id))


def _as_transformed(
    p: pe.Pokemon, target: pe.Pokemon, moves: list, ability: str, types: tuple | None = None
) -> pe.Pokemon:
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
        id=p.id, level=p.level, types=types or target.types, base_types=p.base_types, hp=p.hp,
        # (an ability that does nothing for a transformed holder: none, the engine's L214)
        maxhp=p.maxhp, ability="none" if ability in NO_TRANSFORM else ability,
        base_ability=p.base_ability, item=p.item,
        attack=target.attack, defense=target.defense, special_attack=target.special_attack,
        special_defense=target.special_defense, speed=target.speed, status=p.status,
        weight_kg=target.weight_kg, moves=moves, terastallized=p.terastallized,
        tera_type=p.tera_type, rest_turns=p.rest_turns, sleep_turns=p.sleep_turns,
        times_attacked=p.times_attacked, gender=p.gender, transform_backup=backup,
        stellar_boosted=p.stellar_boosted, last_item=p.last_item,  # (S138: its last item kept)
        # (its own nature, EVs: Showdown's transformInto copies the stats, not the set -- S158)
        nature=str(p.nature).lower(), evs=tuple(p.evs), once_used=p.once_used,
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
        (
            ids.index(mid)
            for mid, mv in current_moves(mon).items()
            if mv.is_last_used and mid in ids
        ),
        None,
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


def _pending_move(
    engine_mon: pe.Pokemon,
    last: dict,
    vol: set[str],
    weights: dict | None,
    rng: random.Random,
    legal: list[str],
) -> str:
    """The opponent's move still to come this turn, in this world: its locked move (a Choice
    item's, Outrage's: its last used one) if legal, else one of the ``legal`` ones (the engine's:
    alpha_search.pending_moves) drawn by ``weights`` (by move id: the turn's search's opponent
    visits, so conditioned on what is left; none or all zero: uniform); "none" without one."""
    moves = list(engine_mon.moves)
    lu = last.get("last_used_move", "")
    if lu.startswith("move:") and (engine_mon.item in ("choiceband", "choicespecs", "choicescarf")
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
    p = next(
        (b for m, b in zip(mons, built, strict=True) if tm.k(to_id(m.species)) == tm.sub_passed),
        None,
    )
    return p.maxhp // 4 if p is not None else 0


def _tera_used(mons: list, used: bool) -> list:
    """``mons`` with a fainted one terastallized when the side used its Terastallization and no
    mon shows it (doc/engine-diff.md L177)."""
    if not used or any(p.terastallized for p in mons):
        return mons
    j = next((j for j, p in enumerate(mons) if p.hp <= 0), None)
    if j is None:
        return mons
    return mons[:j] + [_with(mons[j], terastallized=True)] + mons[j + 1 :]


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
    arch_mix: float | None = None,
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
    zor = next((m for m in battle.team.values() if to_id(m.species).startswith("zoroark")), None)
    if spectator is None and zor is not None and zor.max_hp:
        # (the items our Zoroark used up in disguise -- this time in or an earlier one, its shown
        # max HP its own, not the disguise's: the timers keep them as the disguise's; the timers
        # move them only as an Illusion breaks -- 2026-10-23, S88, S127)
        z = tm_us.k(to_id(zor.species))
        for stint in [*tm_us.past_stints, tm_us.stint]:
            shown = battle.team.get(f"{role}: {stint.get('nick', '')}")
            if (
                not stint.get("items")
                or shown is None
                or shown is zor
                or str(zor.max_hp) != stint.get("max")
                or str(shown.max_hp) == stint.get("max")
            ):
                continue
            if tm_us is tms[role]:
                tm_us = copy.copy(tm_us)
                tm_us.last_item = dict(tm_us.last_item)
            for dsp, before in stint["items"]:
                used = tm_us.last_item.pop(dsp, None)
                if before is not None:
                    tm_us.last_item[dsp] = before
                if used:
                    tm_us.last_item[z] = used
    if spectator is None:
        # (our Zoroark's sleep counted under a disguise -- this time in or an earlier one: the
        # request's Zoroark asleep with no count, a mon not asleep with one -- S110, S119)
        zor = next(
            (m for m in battle.team.values() if to_id(m.species).startswith("zoroark")), None
        )
        if (
            zor is not None
            and STATUS.get(zor.status) == "sleep"
            and tm_us.k(to_id(zor.species)) not in tm_us.sleep
        ):
            stray = [
                k
                for k in tm_us.sleep
                if not any(
                    tm_us.k(to_id(m.species)) == k and STATUS.get(m.status) == "sleep"
                    for m in battle.team.values()
                )
            ]
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
        imprisoned = (frozenset(current_moves(foe)) if tm_them.imprison and foe is not None
                      else frozenset())  # fmt: skip
        our_mons = [
            _our_mon(m, avail if m is active else None, tm_us,
                     req_pp if m is active else None, revived == to_id(m.species),
                     imprisoned=imprisoned if m is active else frozenset(), own_set=_own_set(battle, m))
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
            our_mons.append(
                _their_mon(
                    m,
                    s,
                    tm_us,
                    tm_us.disabled if m is active else None,
                    *_illusion_adj(m, dis_us, z_us),
                )
            )
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

    # the opponent's speed: usage spreads consistent with the observed move order. F1: the damage
    # evidence, a posterior per mon with hits. Both need our real sets: play time, or a replay's
    # side whose team was pasted (a review -- 2026-10-30 review: it had neither, a foe that had
    # just outsped ours drawn slower); not the training data's replays (issue)
    evidence = spectator is None or _exact_side(spectator)
    obs = (battle_observations(battle, None if spectator is None else _exact_speed(battle, spectator))
           if evidence else None)  # fmt: skip
    dmg = (damage_posteriors(battle, belief, theirs, team_names, arch_mix, pct=spectator is not None)
           if evidence and damage_belief else {})  # fmt: skip
    their_keys = [next((k for k, v in battle.opponent_team.items() if v is m), None)
                  for m in theirs]  # fmt: skip
    our_keys = [next((k for k, v in battle.team.items() if v is m), None) for m in ours]
    # a transformed active: the index of its target (D17 J; replays too, 2026-10-23 review)
    our_t = _transform_target(battle, battle.team, active, their_keys)
    their_t = _transform_target(battle, battle.opponent_team, opp_active, our_keys)
    # (the moves our transformed active used are its target's: in that mon's sampled set)
    copied = None
    if our_t is not None:
        used = [m for m in current_moves(active) if m in _MOVES]
        if spectator is not None:  # (a replay: the game's, known from the transform on)
            used += [m for m in spectator.copied.get(to_id(theirs[our_t].species), [])
                     if m in _MOVES and m not in used]  # fmt: skip
        copied = KnownSet(moves=used)
    # this world's Illusion (D17 G): drawn before the sets -- a disguise's line then is its
    # Zoroark's (_illusion_fix)
    zi = _illusion(theirs, opp_active, battle.opponent_team, rng)
    dis_them, z_them, _ = _illusion_fix(battle.opponent_team, tm_them, zi is not None)
    their_sets = [sample_set(belief, m, team_names, rng, move_beta, mix=arch_mix,
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
    if spectator is None and tm_them.imprison and their_mons and our_active_idx is not None:
        # (the imprisoner's moves in this world -- its set's, not only those it revealed: S140)
        # (transformed: its copied ones)
        world = (
            frozenset(current_moves(opp_active))
            if their_t is not None
            else frozenset(their_sets[their_idx].moves) | frozenset(current_moves(opp_active))
        )
        our_mons[our_active_idx] = _our_mon(active, avail, tm_us, req_pp, revived == to_id(active.species),
                                            imprisoned=world, own_set=_own_set(battle, active))  # fmt: skip
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
            # (in the target's slot order: a locked Outrage, the request's only one, in its own slot
            # -- not the first, S158; a move of the request this world's target lacks, last)
            base = [m.id for m in their_mons[t].moves]
            extra = [x for x in req if x not in base]
            # (every move of the request kept: a target move it does not list goes first when
            # they are more than four -- 2026-10-26 review, a request move dropped)
            while len(base) + len(extra) > 4 and any(x not in req for x in base):
                base.remove(next(x for x in reversed(base) if x not in req))
            ids = list(req) if len(req) == 4 or not base else base + extra
            # (the move it chose: after a Struggle poke-env's last used one is the Struggle --
            # 2026-10-23, the state-construction differential: the lock's flags were lost)
            last = (tm_us.own_last if tm_us is not None else "") or last_used_move(active)
            lock = last if active.item in CHOICE_ITEMS and not tm_us.item_new else ""
            if tm_us.locked:
                lock = tm_us.locked[0]
            moves = []
            struggling = avail is not None and avail <= {"struggle"}
            for mid in ids:
                pp = (
                    int(req[mid])
                    if req.get(mid) is not None
                    else max(0, copied_pp(active, mid) - _spited(tm_us, active, mid))
                )
                cat, flags = _move_kinds().get(mid, ("", set()))
                # (S139: Heal Block's Horn Leech)
                blocked = (
                    (tm_us.taunt is not None and cat == "Status")
                    or tm_us.disabled == mid
                    or (tm_us.healblock is not None and "heal" in flags)
                    or (tm_us.throatchop is not None and "sound" in flags)
                    or (active.item == "assaultvest" and cat == "Status")
                )
                if struggling and mid == lock and not blocked:
                    pp = 0  # (Struggle only, locked into it: it is out of PP -- poke-env's count drifts)
                # (its flags as an untransformed mon's: not offered and no reason the engine
                # derives itself -- out of PP, a Taunt, ...: S95)
                disabled = avail is not None and mid not in avail and not derived_disable(
                    mid, taunt=tm_us.taunt is not None, healblock=tm_us.healblock is not None,
                    throatchop=tm_us.throatchop is not None, item=active.item or "", last_move=last,
                    lock=lock, disabled=tm_us.disabled or "", charging=tm_us.charging or "",
                    recharge=tm_us.recharge, pp=pp, encore=tm_us.encore is not None)  # fmt: skip
                moves.append(pe.Move(id=mid, pp=pp, disabled=disabled))
        else:  # the target's (this world's), the PP poke-env counted, Disable's flag
            moves = [pe.Move(id=m.id, pp=copied_pp(active, m.id), disabled=m.id == tm_us.disabled)
                     for m in their_mons[t].moves]  # fmt: skip
        our_mons[our_active_idx] = _as_transformed(
            our_mons[our_active_idx],
            their_mons[t],
            moves or their_mons[t].moves,
            copied_ability(active, their_sets[t].ability),
            _types(active),  # (its types as it copied them: S136)
        )
        our_tf = True
    t = their_t
    if t is not None and their_mons and t < len(our_mons):
        # (Disable's flag on a copied move: 2026-10-23 review -- left out, usable)
        # (S131: Spite's)
        moves = [
            pe.Move(
                id=m.id,
                pp=max(0, copied_pp(opp_active, m.id) - _spited(tm_them, opp_active, m.id)),
                disabled=m.id == tm_them.disabled,
            )
            for m in our_mons[t].moves
        ]
        own = own_ability(ours[t]) or our_mons[t].ability
        their_mons[their_idx] = _as_transformed(their_mons[their_idx], our_mons[t], moves,
                                                copied_ability(opp_active, own), _types(opp_active))  # fmt: skip
        their_tf = True
    our_last, our_vol = _last_move(
        active,
        our_mons[our_active_idx] if our_active_idx is not None else None,
        avail,
        our_active_idx,
        tm_us.switched_now,
        tm_us,
    )
    their_last, their_vol = _last_move(
        opp_active,
        their_mons[their_idx] if their_mons else None,
        None,
        their_idx if their_mons else None,
        tm_them.switched_now,
        tm_them,
    )
    # (a mon out transformed into a Regenerator holder healed as it went -- the copied ability;
    # poke-env does so only when it knew the target's ability: a replay's side, S145)
    for mons, src, tm, omons, osrc, otm, exact in ((our_mons, ours, tm_us, their_mons, theirs, tm_them, spectator is None),
                                                   (their_mons, theirs, tm_them, our_mons, ours, tm_us, False)):  # fmt: skip
        if exact or not tm.transformed_out:
            continue
        for j, (m, p) in enumerate(zip(src, mons, strict=True)):
            tgt = tm.transformed_out.get(tm.k(to_id(m.species)))
            if (
                not tgt
                or getattr(m, "active", False)
                or p.hp <= 0
                or tm.k(to_id(m.species)) in tm.no_regen
            ):
                continue
            q = next(
                (
                    (om, oq)
                    for om, oq in zip(osrc, omons, strict=True)
                    if otm.k(to_id(om.species)) == tgt
                ),
                None,
            )
            if (
                q is not None
                and str(q[1].ability).lower() == "regenerator"
                and current_ability(q[0]) != "regenerator"
            ):
                mons[j] = _with(p, hp=min(p.maxhp, p.hp + p.maxhp // 3))
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
        if mon is not None and "typechange" in vol and tm.protean:  # (the log's use: S130 -- a
            # Skill Swap back to Libero starts its state anew)
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
            if tm.temp_forme is not None or (
                mon is not None and str(p.id).lower() != to_id(mon.species)
            ):
                forme_tc.add(id(vol))  # (a forme's -- the timers': not a Double Shock's, S122)
    for vol, mons, i, tm in ((our_vol, our_mons, our_active_idx, tm_us),
                             (their_vol, their_mons, their_idx, tm_them)):  # fmt: skip
        p = mons[i] if i is not None and i < len(mons) else None
        if p is not None and p.terastallized and not tm.typechanged and id(vol) not in forme_tc and not (
                mons is our_mons and our_tf or mons is their_mons and their_tf):  # fmt: skip
            # (a type change after it terastallized did nothing -- Showdown's setType: a Double
            # Shock on a tera'd Pawmot; one before it stays)
            vol.discard("typechange")
            # (its types too: the -start typechange poke-env read names the tera type -- the
            # engine's STAB on the types it kept, Close Combat's lost; 2026-10-24, the belief
            # check, its damage evidence)
            mons[i] = _with(p, types=tuple(p.base_types))
    # (a type change to its own types -- a Ghost's Libero into Ghost: none, as Showdown's types
    # compare; not a transformed one's, nor Roost's turn -- S137)
    for vol, mons, i, tf, tm, mon in ((our_vol, our_mons, our_active_idx, our_tf, tm_us, active),
                                      (their_vol, their_mons, their_idx, their_tf, tm_them, opp_active)):  # fmt: skip
        p = mons[i] if i is not None and i < len(mons) else None
        if (
            p is not None
            and "typechange" in vol
            and not tf
            and not tm.roosted
            and not p.terastallized
            and tuple(p.types) == tuple(p.base_types)
            and Effect.TYPEADD not in getattr(mon, "effects", {})
        ):
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
        # (this turn's start: Showdown's 4 till the turn's end -- a mid-turn decision, S128)
        if counts:
            vol.add(f"perish{4 if tm.perish_fresh and min(counts) == 3 else min(counts)}")
        if tm.slowstart:  # (L77)
            vol.add("slowstart")
        if tm.trapped:  # (L107)
            vol.add("trapped")
        if tm.frombooster:  # (L141)
            vol.add("frombooster")
        # (L237: and this turn's, a decision mid-turn -- the engine makes it the next turn's at the
        # turn's end; past the end (a faint's switch-in) it is the next turn's already, as the
        # engine's: Showdown's moveLastTurnResult changes only at the next turn's start)
        now = tm.failed_now or (tm.sub_failed_now and ab[mon is active] == "infiltrator")
        # (L115; S93)
        last = tm.last_failed or (tm.last_sub_failed and ab[mon is active] == "infiltrator")
        if now if tm.upkept else last:
            vol.add("lastmovefailed")
        if now and not tm.upkept:
            vol.add("movefailed")
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
        if tm.rollout is not None:  # (L241: its hits so far)
            vol.add("rollout")
            vcounts.setdefault(mon is active, {})["rollout"] = tm.rollout[1]
        if tm.stockpile:
            vol.add("stockpile")
            vcounts.setdefault(mon is active, {})["stockpile"] = tm.stockpile
        if tm.roosted:  # (a mid-turn decision after its Roost)
            vol.add("roost")
        # (S132)
        if tm.consecutive and (items_now[mon is active] == "metronome" or tm.metronome_gone):
            vol.add("metronome")
            metronome[mon is active] = tm.consecutive
        # an Illusion in disguise (the engine's volatile: a Transform into it fails, L227): ours
        # when the log shows our active as another species; theirs in a world that drew the
        # Zoroark (2026-10-23, the state-construction differential: never passed)
        if (
            mon is active
            and mon is not None
            and tm.active
            and tm.active != tm.k(to_id(mon.species))
            and to_id(mon.species).startswith("zoroark")
        ):
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
    # (L241: an Uproar's own lock too -- Showdown's getLockedMove, onLockMove 'uproar'; L242: a move
    # it called -- Copycat's Outrage, not in its moveset -- its caller's slot runs it, the engine's
    # CALLEDLOCK keeps which: ours at the live root too, the request names the called move alone)
    for mons, i, tm, mine, vol in ((their_mons, their_idx, tm_them, False, their_vol),
                                   (our_mons, our_active_idx, tm_us, True, our_vol)):  # fmt: skip
        lock_move = tm.locked[0] if tm.locked else ("uproar" if tm.uproar is not None else
                                                      tm.rollout[0] if tm.rollout is not None else None)  # fmt: skip
        if not lock_move or i is None or i >= len(mons):
            continue
        em = mons[i]
        ids = [x.id for x in em.moves]
        keep = lock_move if lock_move in ids else next((x for x in ids if x in CALLERS), lock_move)
        called = keep != lock_move and lock_move in CALLED_LOCKS
        if called:
            vol.add("calledlock")
            vcounts.setdefault(mine, {})["calledlock"] = CALLED_LOCKS.index(lock_move) + 1
        if called or not (mine and spectator is None):
            mons[i] = _with(em, moves=[pe.Move(id=x.id, pp=x.pp, disabled=(x.disabled and not called) or x.id != keep)
                                       for x in em.moves])  # fmt: skip
    # (S158: the foe's Choice lock -- its world's Choice item or Gorilla Tactics and the move it
    # chose this time in: the engine keeps it by the other moves' flags, as ours by our request's;
    # its options were all of its moves. Not an item it got after that move -- L228. A replay's
    # own side the same way: no request -- 2026-10-30, issue #28, a Choice Band Kingambit's
    # every move offered)
    for mons, i, tm, mine in ((their_mons, their_idx, tm_them, False),
                              (our_mons, our_active_idx, tm_us, True)):  # fmt: skip
        if (mine and spectator is None) or i is None or i >= len(mons) or tm.locked:
            continue
        em = mons[i]
        last = tm.own_last
        # (not a world that contradicts the log -- two moves this time in: no Choice item, whatever
        # it drew; nor an item doing nothing: Klutz, Embargo, Magic Room -- Showdown's choicelock
        # ignoringItem; 2026-10-26 review)
        used = {
            m for m in tm.stint.get("moves", [])[tm.stint.get("item_mark", 0) :] if m != "struggle"
        }
        item_on = (
            str(em.ability).lower() != "klutz"
            and not tm.embargo
            and Field.MAGIC_ROOM not in battle.fields
        )
        if (
            last
            and not tm.item_new
            and any(x.id == last for x in em.moves)
            and len(used) <= 1
            and (
                (str(em.item).lower() in CHOICE_ITEMS and item_on)
                or str(em.ability).lower() == "gorillatactics"
            )
        ):
            mons[i] = _with(em, moves=[pe.Move(id=x.id, pp=x.pp, disabled=x.disabled or x.id != last)
                                       for x in em.moves])  # fmt: skip
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
        # whether its item worked as the effect began, one rule along every path (2026-10-24
        # review): a Klutz holder's does nothing -- its ability then: a move's change before,
        # else its own, this world's; not under Neutralizing Gas, which held the Klutz off --,
        # then the item it held then (the timers' snapshot: changed since, Magic Room / Embargo's
        # none) or now
        mine = (who == "us") != (key in tm.swapped)  # (the setter's side)
        setter = next((p for m, p in zip(ours if mine else theirs, our_mons if mine else their_mons,
                                         strict=True) if to_id(m.species) == sp), None)  # fmt: skip
        then = tm.set_ability.get(key) or (
            str(setter.base_ability).lower() if setter is not None else ""
        )
        if then == "klutz" and key not in tm.set_gas:
            return ""
        if key in tm.set_items:
            return tm.set_items[key]
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

    # (a transformed active's weight its target's forme's as it transformed -- Showdown's
    # transformInto takes it then: an Imposter Ditto into a Tera Shift Terapagos, 16 kg, read
    # its base forme's 6.5; and not the Stellar forme's 77 the target had later; 2026-10-24, the
    # differential test framework's full corpus)
    def copied_weight(tm: SideTimers, target: pe.Pokemon) -> float:
        w = (GEN.pokedex.get(tm.copied_forme) or {}).get("weightkg") if tm.copied_forme else None
        return float(w) if w else target.weight_kg

    # (and its stats: the target's in that forme -- an Ogerpon / Terapagos that changed forme after
    # the transform; the target's spread, now in its state: S158)
    def copied_stats(tm: SideTimers, target: pe.Pokemon) -> dict:
        entry = GEN.pokedex.get(tm.copied_forme) if tm.copied_forme else None
        if not entry or to_id(tm.copied_forme) == _sp_id(target):
            return {}
        st = calc_stats(
            entry["baseStats"],
            Spread(str(target.nature).lower(), tuple(target.evs)),
            level=target.level,
        )
        return {
            "attack": st["atk"],
            "defense": st["def"],
            "special_attack": st["spa"],
            "special_defense": st["spd"],
            "speed": st["spe"],
        }

    if our_tf and our_t is not None and our_t < len(their_mons):
        our_mons[our_active_idx] = _with(our_mons[our_active_idx], weight_kg=copied_weight(tm_us, their_mons[our_t]),
                                         **copied_stats(tm_us, their_mons[our_t]))  # fmt: skip
    if their_tf and their_t is not None and their_t < len(our_mons):
        their_mons[their_idx] = _with(their_mons[their_idx], weight_kg=copied_weight(tm_them, our_mons[their_t]),
                                      **copied_stats(tm_them, our_mons[their_t]))  # fmt: skip
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
        # (S158: never passed -- Supreme Overlord's, Last Respects' count)
        revived_faints=min(tm_us.revivals, 6),
        pokemon=_pad(our_mons),
        active_index=pe.PokemonIndex(str(our_idx)),
        side_conditions=_side_conditions(
            battle.side_conditions,
            turn,
            *_counts(tm_us, active),
            clay_us,
            tm_us.side_elapsed,
            tm_us.healing_wish,
        ),
        volatile_statuses=our_vol,
        **_timed(
            tm_us,
            active,
            ours,
            our_mons,
            our_vol,
            disable.get("us"),
            locked.get(True),
            metronome.get(True),
            vcounts.get(True),
        ),
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
        **(
            _boosts(
                active,
                (tm_us.stint["boosts"] if our_disguised else tm_us.illusion_boosts)
                if spectator is not None
                else None,
            )
            if active is not None
            else {}
        ),
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
        # (S158: never passed -- Supreme Overlord's, Last Respects' count)
        revived_faints=min(tm_them.revivals, 6),
        pokemon=_pad(their_mons),
        active_index=pe.PokemonIndex(str(their_idx)),
        side_conditions=_side_conditions(
            battle.opponent_side_conditions,
            turn,
            *_counts(tm_them, opp_active),
            clay_them,
            tm_them.side_elapsed,
            tm_them.healing_wish,
        ),
        volatile_statuses=their_vol,
        **_timed(
            tm_them,
            opp_active,
            theirs,
            their_mons,
            their_vol,
            disable.get("them"),
            locked.get(False),
            metronome.get(False),
            vcounts.get(False),
        ),
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
    gravity = (
        field_left("gravity", battle.fields[Field.GRAVITY]) if Field.GRAVITY in battle.fields else 0
    )
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
    if evidence and not (battle.force_switch if force_switch is None else force_switch):
        record_base(battle, st.to_string())
    return st


# (an option name -> the battle's order: agents/slots, the actions' one vocabulary -- plan C)
engine_move_to_order = slots.order_of


__all__ = ["build_state", "sample_set", "engine_move_to_order", "Move"]
