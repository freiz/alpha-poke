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
_MOVES = GEN.moves


def _types(mon) -> tuple[str, str]:
    ts = [t.name.lower() for t in (mon.type_1, mon.type_2) if t is not None]
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


def sample_set(belief: BeliefModel, mon, team_names: tuple[str, ...], rng: random.Random):
    """One plausible full set for an opposing mon, consistent with what it revealed."""
    species = _preview_name(mon, team_names)
    dist = belief.prior.predict(species, team_names)
    revealed = [m for m in mon.moves if m in _MOVES]
    ss = belief.sets.get(species)
    item = mon.item if mon.item not in (None, "unknown_item") else None
    tera = _tera(mon) if mon.is_terastallized else None
    k = None
    if ss is not None and ss.params:
        names = {to_id(n): n for n in ss.vocab["move"]}
        item_name = next((n for n in ss.vocab["item"] if to_id(n) == item), None) if item else None
        post = ss.posterior(item=item_name, moves=[names.get(m, m) for m in revealed])
        k = int(np.searchsorted(np.cumsum(post), rng.random() * post.sum()))
        k = min(k, len(post) - 1)

    def draw(attr, fallback: dict[str, float]):
        if k is not None and ss.vocab.get(attr):
            w = ss.params[attr][k]
            if w.sum() > 0:
                i = int(np.searchsorted(np.cumsum(w), rng.random() * w.sum()))
                return to_id(ss.vocab[attr][min(i, len(w) - 1)])
        if fallback:
            keys, ws = zip(*fallback.items(), strict=True)
            if sum(ws) > 0:
                return to_id(rng.choices(keys, weights=ws)[0])
        return None

    if item is None:
        item = draw("item", dist.item) or "none"
    if tera is None:
        tera = draw("tera", dist.tera) or _tera(mon)
    ability = to_id(mon.ability) if mon.ability else None
    if ability is None:
        ap = ability_probs(mon)
        ability = (rng.choices(list(ap), weights=list(ap.values()))[0] if ap else None) or "none"
    # moves: revealed + draws (without replacement) from the archetype's move weights
    moves = list(revealed)[:4]
    if k is not None and ss.vocab.get("move"):
        weights = {
            to_id(n): float(w) for n, w in zip(ss.vocab["move"], ss.params["move"][k], strict=False)
        }
    else:
        weights = dict(dist.move)
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
    spread = belief.spread_for(mon.species)
    stats = calc_stats(mon.base_stats, spread, level=mon.level or 100)
    return SampledSet(moves or ["tackle"], item, ability, tera, stats)


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


def _side_conditions(sc: dict, turn: int) -> pe.SideConditions:
    return pe.SideConditions(
        spikes=sc.get(SideCondition.SPIKES, 0),
        toxic_spikes=sc.get(SideCondition.TOXIC_SPIKES, 0),
        stealth_rock=int(SideCondition.STEALTH_ROCK in sc),
        sticky_web=int(SideCondition.STICKY_WEB in sc),
        reflect=_remaining(sc.get(SideCondition.REFLECT), turn)
        if SideCondition.REFLECT in sc
        else 0,
        light_screen=(
            _remaining(sc.get(SideCondition.LIGHT_SCREEN), turn)
            if SideCondition.LIGHT_SCREEN in sc
            else 0
        ),
        aurora_veil=(
            _remaining(sc.get(SideCondition.AURORA_VEIL), turn)
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


def _our_mon(mon, available_moves: set[str] | None) -> pe.Pokemon:
    stats = mon.stats or {}
    moves = []
    for mid, mv in list(mon.moves.items())[:4]:
        disabled = available_moves is not None and mid not in available_moves
        moves.append(pe.Move(id=mid, pp=max(0, mv.current_pp), disabled=disabled))
    return pe.Pokemon(
        id=mon.species,
        level=mon.level or 100,
        types=_types(mon),
        base_types=_base_types(mon.species),
        hp=0 if mon.fainted else int(mon.current_hp or 0),
        maxhp=int(mon.max_hp or 1),
        ability=to_id(mon.ability) if mon.ability else "none",
        base_ability=to_id(mon.ability) if mon.ability else "none",
        item=mon.item or "none",
        attack=int(stats.get("atk") or 100),
        defense=int(stats.get("def") or 100),
        special_attack=int(stats.get("spa") or 100),
        special_defense=int(stats.get("spd") or 100),
        speed=int(stats.get("spe") or 100),
        status=STATUS.get(mon.status, "none"),
        weight_kg=float(mon.weight or 0.0),
        moves=moves,
        terastallized=mon.is_terastallized,
        tera_type=_tera(mon),
    )


def _their_mon(mon, s: SampledSet) -> pe.Pokemon:
    maxhp = s.stats["hp"]
    hp = 0 if mon.fainted else max(1, round(mon.current_hp_fraction * maxhp))
    return pe.Pokemon(
        id=mon.species,
        level=mon.level or 100,
        types=_types(mon),
        base_types=_base_types(mon.species),
        hp=hp,
        maxhp=maxhp,
        ability=s.ability,
        base_ability=s.ability,
        item=s.item,
        attack=s.stats["atk"],
        defense=s.stats["def"],
        special_attack=s.stats["spa"],
        special_defense=s.stats["spd"],
        speed=s.stats["spe"],
        status=STATUS.get(mon.status, "none"),
        weight_kg=float(mon.weight or 0.0),
        moves=[pe.Move(id=m, pp=16) for m in s.moves[:4]],
        terastallized=mon.is_terastallized,
        tera_type=s.tera,
    )


def _pad(mons: list) -> list:
    return (mons + [pe.Pokemon.create_fainted() for _ in range(6)])[:6]


def build_state(
    battle, belief: BeliefModel, team_names: tuple[str, ...], rng: random.Random
) -> pe.State:
    """One determinization of the current battle (side_one = us)."""
    turn = battle.turn
    ours = list(battle.team.values())
    active = battle.active_pokemon
    avail = {m.id for m in battle.available_moves} if battle.available_moves else None
    our_mons = [_our_mon(m, avail if m is active else None) for m in ours]
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
    their_mons = [_their_mon(m, sample_set(belief, m, team_names, rng)) for m in theirs]
    their_idx = next((i for i, m in enumerate(theirs) if m is opp_active), 0)

    side_one = pe.Side(
        pokemon=_pad(our_mons),
        active_index=pe.PokemonIndex(str(our_idx)),
        side_conditions=_side_conditions(battle.side_conditions, turn),
        volatile_statuses=_volatiles(active) if active is not None else set(),
        substitute_health=(
            int((active.max_hp or 4) // 4)
            if active is not None and Effect.SUBSTITUTE in active.effects
            else 0
        ),
        force_switch=bool(battle.force_switch),
        **(_boosts(active) if active is not None else {}),
    )
    side_two = pe.Side(
        pokemon=_pad(their_mons),
        active_index=pe.PokemonIndex(str(their_idx)),
        side_conditions=_side_conditions(battle.opponent_side_conditions, turn),
        volatile_statuses=_volatiles(opp_active) if opp_active is not None else set(),
        substitute_health=(
            their_mons[their_idx].maxhp // 4
            if opp_active is not None and Effect.SUBSTITUTE in opp_active.effects
            else 0
        ),
        **(_boosts(opp_active) if opp_active is not None else {}),
    )
    weather, wturns = "none", 0
    if battle.weather:
        w, start = next(iter(battle.weather.items()))
        weather, wturns = WEATHER.get(w, "none"), _remaining(start, turn)
    terrain, tturns = "none", 0
    trick_room, trturns = False, 0
    for f, start in battle.fields.items():
        if f in TERRAIN:
            terrain, tturns = TERRAIN[f], _remaining(start, turn)
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
