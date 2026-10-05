"""Multi-turn values of status moves (and status side effects of attacks) for the knowledge bot.

Units are the bot's usual "HP-fraction swing" (1.0 = a full HP bar; a KO adds KO_BONUS). The
damage we take *this* turn is not counted here: the caller subtracts the stay cost for every
move option alike. What a status move buys is the future: more damage from boosts, HP that
lets us stay in longer, an opposing sweeper stopped, an item removed, ...

Anti-setup: ``boost_threat`` measures how dangerous the opponent's stat boosts are; phazing,
Haze, Encore, Taunt, burn / paralysis and attacks into the boosted mon are all scaled by it.
"""

import math
from dataclasses import dataclass

from poke_env.battle import Effect, PokemonType, SideCondition, Weather
from poke_env.battle.move import Move

from alpha_poke.agents.damage import (
    MonView,
    best_damage,
    boosts_as,
    damage_fraction,
    entry_hazard_cost,
    is_damaging,
    moves_first,
)

OFFENSIVE = ("atk", "spa", "spe")
SETUP_DISCOUNT = 0.6  # boosts can be phazed / the opponent can switch: future gains are uncertain
ANTI_SETUP_MOVES = {
    "haze",
    "clearsmog",
    "roar",
    "whirlwind",
    "dragontail",
    "circlethrow",
    "encore",
    "perishsong",
    "spectralthief",
}
PHAZE = {"roar", "whirlwind", "dragontail", "circlethrow"}
PROTECT = {
    "protect",
    "detect",
    "kingsshield",
    "spikyshield",
    "banefulbunker",
    "silktrap",
    "burningbulwark",
    "obstruct",
}
# heal fraction when poke-env reports 0 (weather-dependent moves: value without weather)
HEAL_AMOUNT = {
    "moonlight": 0.5,
    "morningsun": 0.5,
    "synthesis": 0.5,
    "shoreup": 0.5,
    "strengthsap": 0.35,
    "lunarblessing": 0.25,
    "junglehealing": 0.25,
}
WEATHER_HEAL = {"moonlight", "morningsun", "synthesis"}
ITEM_VALUE = {  # what removing it (Knock Off) is worth
    "heavydutyboots": 0.25,
    "leftovers": 0.2,
    "blacksludge": 0.2,
    "eviolite": 0.3,
    "assaultvest": 0.15,
    "choiceband": 0.15,
    "choicespecs": 0.15,
    "choicescarf": 0.15,
    "rockyhelmet": 0.1,
    "lifeorb": 0.1,
    "airballoon": 0.1,
    "lightclay": 0.1,
    "sitrusberry": 0.05,
}
CHOICE = ("choicescarf", "choicespecs", "choiceband")


@dataclass
class Ctx:
    """What the valuations need about the current turn."""

    battle: object
    mv: MonView  # our active
    ov: MonView  # their active
    ov_moves: list
    incoming: float  # the opponent's best damage on us this turn
    n_opp_left: int
    n_my_left: int
    is_wincon: bool
    opp_last_move: str | None = None  # their active's last move since it came in
    used_protect_last_turn: bool = False

    @property
    def me(self):
        return self.mv.mon

    @property
    def opp(self):
        return self.ov.mon


# ---- threat of a boosted opponent -------------------------------------------------------------
def positive_stages(mon, stats=OFFENSIVE) -> int:
    return sum(max(0, mon.boosts.get(s, 0)) for s in stats)


def boost_threat(ctx: Ctx) -> float:
    """How much the opponent's current boosts are worth to it: the extra damage per hit they
    give it on our active, over ~2 turns, plus a bonus if they flip the speed order; 0 when it
    has no positive offensive stages."""
    opp = ctx.opp
    if positive_stages(opp) == 0:
        return 0.0
    _, boosted = best_damage(ctx.ov, ctx.mv, ctx.ov_moves, ctx.battle)
    base_first = None
    with boosts_as(opp, **{s: min(0, opp.boosts.get(s, 0)) for s in OFFENSIVE}):
        _, plain = best_damage(ctx.ov, ctx.mv, ctx.ov_moves, ctx.battle)
        base_first = moves_first(ctx.mv, ctx.ov, None, ctx.battle)
    now_first = moves_first(ctx.mv, ctx.ov, None, ctx.battle)
    t = 2 * max(0.0, boosted - plain)
    if base_first > now_first:  # its speed boost made it outspeed us
        t += 0.3 * (base_first - now_first)
    return min(1.5, t + 0.1 * positive_stages(opp))


# ---- self boosts -------------------------------------------------------------------------------
def _setup_stages(move: Move, me) -> dict[str, int] | None:
    if move.id == "bellydrum":
        return {"atk": 6} if me.current_hp_fraction > 0.5 else None
    if move.id == "curse" and PokemonType.GHOST not in me.types:
        return {"atk": 1, "def": 1, "spe": -1}
    if move.boosts and move.target is not None and move.target.name == "SELF":
        return dict(move.boosts)
    return None


def setup_value(ctx: Ctx, move: Move) -> float | None:
    """Self-boost: extra damage of our best attack over the attacks we expect to make after
    this turn (+ a KO it unlocks), plus the damage the defensive stages save; None if not a
    setup move."""
    me = ctx.me
    stages = _setup_stages(move, me)
    if stages is None:
        return None
    if all(me.boosts.get(s, 0) >= 6 for s, v in stages.items() if v > 0):
        return 0.0
    if ctx.ov.ability_p("unaware") >= 0.5:
        return 0.02  # its Unaware ignores our boosts
    our_moves = [m for m in me.moves.values() if is_damaging(m)]
    _, d_now = best_damage(ctx.mv, ctx.ov, our_moves, ctx.battle)
    _, inc_model = best_damage(ctx.ov, ctx.mv, ctx.ov_moves, ctx.battle)
    new = {s: me.boosts.get(s, 0) + v for s, v in stages.items()}
    if move.id == "bellydrum":
        new = {"atk": 6}
    with boosts_as(me, **new):
        _, d_boost = best_damage(ctx.mv, ctx.ov, our_moves, ctx.battle)
        _, inc_after = best_damage(ctx.ov, ctx.mv, ctx.ov_moves, ctx.battle)
        first_after = moves_first(ctx.mv, ctx.ov, None, ctx.battle)
    # same scale as this turn's estimate: our defensive stages scale what we take
    inc_after = ctx.incoming * (inc_after / inc_model) if inc_model > 0 else ctx.incoming
    hp_left = me.current_hp_fraction - ctx.incoming - (0.5 if move.id == "bellydrum" else 0.0)
    if hp_left <= 0:
        return 0.0
    if inc_after <= 0.01:
        attacks = 3
    elif first_after >= 0.5:
        attacks = min(3, math.ceil(hp_left / inc_after))
    else:
        attacks = min(3, math.floor(hp_left / inc_after))
    from alpha_poke.agents.knowledge_player import KO_BONUS

    gain = attacks * max(0.0, min(d_boost, 1.0) - min(d_now, 1.0))
    opp_hp = ctx.opp.current_hp_fraction
    if attacks and d_boost >= opp_hp > d_now:
        gain += 0.5 * KO_BONUS  # the boost turns our hit into a KO
    gain += min(3, attacks + 1) * max(0.0, ctx.incoming - inc_after)  # defensive stages
    anti = any(m.id in ANTI_SETUP_MOVES for m in ctx.ov_moves)
    v = SETUP_DISCOUNT * gain * (0.5 if anti else 1.0)
    return v + (0.05 if ctx.is_wincon else 0.0)


# ---- recovery ----------------------------------------------------------------------------------
def heal_fraction(move: Move, battle) -> float:
    """HP fraction a healing move restores (weather-dependent moves adjusted)."""
    if move.heal:
        return move.heal
    h = HEAL_AMOUNT.get(move.id, 0.0)
    if move.id in WEATHER_HEAL and battle is not None and battle.weather:
        w = next(iter(battle.weather))
        h = 2 / 3 if w in (Weather.SUNNYDAY, Weather.DESOLATELAND) else 0.25
    return h


def heal_value(ctx: Ctx, move: Move) -> float | None:
    """HP gained, worth less when we cannot out-heal the opponent's damage (a recovery loop);
    the survival effect is in the stay cost (we heal before the hit when faster)."""
    me = ctx.me
    missing = 1 - me.current_hp_fraction
    if move.id == "rest":
        return max(0.0, missing - 0.3) if missing > 0.5 and me.status is None else 0.0
    if move.id == "wish":
        return 0.5 * min(0.5, missing) + 0.05
    if move.id == "painsplit":
        mine = me.current_hp_fraction * ctx.mv.stats["hp"]
        theirs = ctx.opp.current_hp_fraction * ctx.ov.stats["hp"]
        avg = (mine + theirs) / 2
        return max(0.0, (avg - mine) / ctx.mv.stats["hp"]) + max(
            0.0, (theirs - avg) / max(ctx.ov.stats["hp"], 1)
        )
    h = heal_fraction(move, ctx.battle)
    if h <= 0:
        return None
    gain = min(h, missing)
    if gain < 0.1:
        return 0.0
    if ctx.incoming >= h:
        gain *= 0.4  # we cannot out-heal it: this only delays
    return gain


# ---- anti-setup / disruption -------------------------------------------------------------------
def _drag_chip(ctx: Ctx) -> float:
    """Average entry-hazard damage of the mon a phaze drags in."""
    side = ctx.battle.opponent_side_conditions
    bench = [
        m
        for m in ctx.battle.opponent_team.values()
        if not m.fainted and not m.active and m is not ctx.opp
    ]
    if not bench or not side:
        return 0.0
    return sum(entry_hazard_cost(m, side) for m in bench) / len(bench)


def phaze_value(ctx: Ctx, move: Move, threat: float) -> float:
    if ctx.n_opp_left < 2 or ctx.ov.ability_p("suctioncups", "guarddog") >= 0.5:
        return 0.0
    if Effect.SUBSTITUTE in ctx.opp.effects and not is_damaging(move):
        return 0.0
    return threat + _drag_chip(ctx) + 0.03


def haze_value(ctx: Ctx, threat: float) -> float:
    ours = 0.15 * positive_stages(ctx.me)
    return max(0.0, threat - ours)


def encore_value(ctx: Ctx, threat: float) -> float:
    last = ctx.opp_last_move
    if not last or Effect.ENCORE in ctx.opp.effects:
        return 0.0
    try:
        lm = Move(last, gen=9)
    except Exception:  # noqa: BLE001
        return 0.0
    if not is_damaging(lm):
        return 0.45 + threat  # locked into setup / recovery / hazards: free turns for us
    if damage_fraction(ctx.ov, ctx.mv, lm, ctx.battle) < 0.15:
        return 0.25  # locked into an attack that barely hurts us
    return 0.0


def taunt_value(ctx: Ctx, threat: float) -> float:
    if Effect.TAUNT in ctx.opp.effects or ctx.ov.ability_p("oblivious", "aromaveil") >= 0.5:
        return 0.0
    status = [m for m in ctx.ov_moves if not is_damaging(m)]
    if not status:
        return 0.0
    v = 0.35 * len(status) / max(1, len(ctx.ov_moves))
    if any(_setup_stages(m, ctx.opp) for m in status):
        v += 0.15 if threat == 0 else 0.1
    if ctx.opp_last_move and ctx.opp_last_move in {m.id for m in status}:
        v += 0.1
    return v


def protect_value(ctx: Ctx) -> float:
    if ctx.used_protect_last_turn:
        return 0.0
    opp = ctx.opp
    v = 0.03
    if opp.status is not None and opp.status.name in ("PSN", "TOX", "BRN"):
        v += 0.1
    if Effect.LEECH_SEED in opp.effects:
        v += 0.12
    if ctx.mv.item_p("leftovers", "blacksludge"):
        v += 0.06
    if any(_setup_stages(m, opp) for m in ctx.ov_moves):
        v -= 0.15  # a free turn for a setup user
    return max(0.0, v)


def screen_value(ctx: Ctx, move: Move) -> float:
    side = ctx.battle.side_conditions
    if move.id == "auroraveil":
        snow = any("snow" in str(w).lower() or "hail" in str(w).lower() for w in ctx.battle.weather)
        if not snow or SideCondition.AURORA_VEIL in side:
            return 0.0
        return 0.45 * min(1.0, (ctx.n_my_left + 1) / 4)
    cond = SideCondition.REFLECT if move.id == "reflect" else SideCondition.LIGHT_SCREEN
    if cond in side:
        return 0.0
    from poke_env.battle import MoveCategory

    want = MoveCategory.PHYSICAL if move.id == "reflect" else MoveCategory.SPECIAL
    mv, _ = best_damage(ctx.ov, ctx.mv, ctx.ov_moves, ctx.battle)
    match = mv is not None and mv.category == want
    return (0.3 if match else 0.08) * min(1.0, (ctx.n_my_left + 1) / 4)


def court_change_value(ctx: Ctx) -> float:
    def layers(side):
        return (
            1.5 * (SideCondition.STEALTH_ROCK in side)
            + side.get(SideCondition.SPIKES, 0)
            + side.get(SideCondition.TOXIC_SPIKES, 0)
            + (SideCondition.STICKY_WEB in side)
        )

    return max(
        0.0,
        0.2 * (layers(ctx.battle.side_conditions) - layers(ctx.battle.opponent_side_conditions)),
    )


def trick_value(ctx: Ctx) -> float:
    ours = ctx.me.item
    if ours not in CHOICE or ctx.ov.item_p(*CHOICE) >= 0.5:
        return 0.02
    status = sum(1 for m in ctx.ov_moves if not is_damaging(m))
    return 0.2 + 0.1 * status


def substitute_value(ctx: Ctx) -> float:
    if Effect.SUBSTITUTE in ctx.me.effects or ctx.me.current_hp_fraction <= 0.5:
        return 0.0
    if ctx.incoming >= 0.25:
        return 0.0
    status = sum(1 for m in ctx.ov_moves if not is_damaging(m))
    return 0.15 + 0.05 * status


def leech_seed_value(ctx: Ctx) -> float:
    opp = ctx.opp
    if PokemonType.GRASS in opp.types or Effect.LEECH_SEED in opp.effects:
        return 0.0
    if ctx.ov.ability_p("magicguard") >= 0.5:
        return 0.0
    return 0.25


def knock_off_bonus(ctx: Ctx) -> float:
    """Expected value of removing the target's item (on top of Knock Off's damage)."""
    item = ctx.opp.item
    if item == "":
        return 0.0
    if item and item not in ("unknown_item",):
        return ITEM_VALUE.get(item, 0.1)
    return sum(p * ITEM_VALUE.get(i, 0.1) for i, p in ctx.ov.item_probs.items())


def status_threat_bonus(move: Move, ctx: Ctx, threat: float) -> float:
    """Burn a boosted physical attacker / paralyse a speed-boosted one."""
    if threat <= 0:
        return 0.0
    opp = ctx.opp
    if move.id == "willowisp" and opp.boosts.get("atk", 0) > 0:
        return 0.4 * threat
    if move.id in ("thunderwave", "glare", "stunspore", "nuzzle") and opp.boosts.get("spe", 0) > 0:
        return 0.4 * threat
    return 0.0


def misc_status_value(ctx: Ctx, move: Move, threat: float) -> float | None:
    """Dispatch for the status moves that are not hazards / removal / inflicting a status
    (handled by the caller); None when the move is not covered here."""
    mid = move.id
    v = setup_value(ctx, move)
    if v is not None:
        return v
    v = heal_value(ctx, move)
    if v is not None:
        return v
    if mid in PHAZE:
        return phaze_value(ctx, move, threat)
    if mid == "haze":
        return haze_value(ctx, threat)
    if mid == "encore":
        return encore_value(ctx, threat)
    if mid == "taunt":
        return taunt_value(ctx, threat)
    if mid in PROTECT:
        return protect_value(ctx)
    if mid in ("reflect", "lightscreen", "auroraveil"):
        return screen_value(ctx, move)
    if mid == "courtchange":
        return court_change_value(ctx)
    if mid in ("trick", "switcheroo"):
        return trick_value(ctx)
    if mid == "substitute":
        return substitute_value(ctx)
    if mid == "leechseed":
        return leech_seed_value(ctx)
    return None


def attack_bonus(ctx: Ctx, move: Move, threat: float) -> float:
    """Extra value of an attack's side effects: Knock Off's item removal, phazing / clearing
    boosts (Dragon Tail, Circle Throw, Clear Smog)."""
    b = 0.0
    if move.id == "knockoff":
        b += knock_off_bonus(ctx)
    if move.id in ("dragontail", "circlethrow"):
        b += phaze_value(ctx, move, threat) - 0.03
    if move.id == "clearsmog":
        b += haze_value(ctx, threat)
    return b
