"""Knowledge layer: lightweight stat / damage / speed estimates.

poke-env's exact damage calculator needs both sides' stats, which are hidden for the opponent
in OU. Here the opponent's stats come from the belief (species base stats + most common Smogon
spread), our own stats are known. The formula is the standard one with the main multipliers
(STAB / tera STAB, type effectiveness, burn, boosts, weather, a few items, average roll);
ignoring the long tail of special cases is intentional: this feeds heuristics, not search.
"""

import math
from dataclasses import dataclass, field

from poke_env.battle import MoveCategory, Pokemon, PokemonType, Status, Weather
from poke_env.battle.move import Move
from poke_env.data import GenData

GEN = GenData.from_gen(9)
STATS = ("hp", "atk", "def", "spa", "spd", "spe")
BOOST = {i: (2 + i) / 2 if i >= 0 else 2 / (2 - i) for i in range(-6, 7)}
AVG_ROLL = 0.925


@dataclass
class Spread:
    nature: str = "serious"
    evs: tuple[int, ...] = (84, 84, 84, 84, 84, 84)

    @classmethod
    def parse(cls, text: str) -> "Spread":
        """'Jolly:0/252/4/0/0/252' -> Spread."""
        nature, evs = text.split(":")
        return cls(nature.lower(), tuple(int(x) for x in evs.split("/")))


def calc_stats(base: dict[str, int], spread: Spread, level: int = 100) -> dict[str, int]:
    nat = GEN.natures.get(spread.nature, {})
    out = {}
    for i, s in enumerate(STATS):
        ev = spread.evs[i]
        core = (2 * base[s] + 31 + ev // 4) * level // 100
        out[s] = core + level + 10 if s == "hp" else int((core + 5) * nat.get(s, 1.0))
    return out


@dataclass
class MonView:
    """What the damage model needs to know about one Pokemon (ours: exact; theirs: estimated)."""

    mon: Pokemon
    stats: dict[str, int]
    item_probs: dict[str, float]  # item id -> probability (exact item -> {id: 1.0})
    ability: str | None = None  # known ability (ours, revealed, or the species' only one)
    ability_probs: dict[str, float] = field(default_factory=dict)  # when unknown: usage dist

    @property
    def hp_fraction(self) -> float:
        return self.mon.current_hp_fraction

    def item_p(self, *ids: str) -> float:
        return sum(self.item_probs.get(i, 0.0) for i in ids)

    def ability_p(self, *ids: str) -> float:
        known = _norm_id(self.ability)
        if known and known not in ("unknown", "unknownability"):
            return 1.0 if known in ids else 0.0
        return min(1.0, sum(self.ability_probs.get(i, 0.0) for i in ids))


def _norm_id(x: str | None) -> str:
    return "".join(c for c in (x or "").lower() if c.isalnum())


# abilities that make the holder immune to (or absorb) a move type
IMMUNE_ABILITIES = {
    PokemonType.GROUND: ("levitate", "eartheater"),
    PokemonType.WATER: ("waterabsorb", "stormdrain", "dryskin"),
    PokemonType.ELECTRIC: ("voltabsorb", "lightningrod", "motordrive"),
    PokemonType.FIRE: ("flashfire", "wellbakedbody"),
    PokemonType.GRASS: ("sapsipper",),
}
IGNORE_ABILITY = ("moldbreaker", "teravolt", "turboblaze")
PRIORITY_BLOCKERS = ("dazzling", "queenlymajesty", "armortail")


def ability_multiplier(att: "MonView", dfn: "MonView", move: Move, eff: float) -> float:
    """Expected damage multiplier from the defender's (possibly unknown) ability and an Air
    Balloon: immunities / absorption weighted by their probability, plus the common damage
    reducers. 1.0 when the attacker ignores abilities."""
    if att.ability_p(*IGNORE_ABILITY) >= 0.5:
        return 1.0
    t = move.type
    flags = move.flags or set()
    p_immune = dfn.ability_p(*IMMUNE_ABILITIES.get(t, ()))
    if t == PokemonType.GROUND and move.id != "thousandarrows":
        p_immune += dfn.item_p("airballoon")
    if "bullet" in flags:
        p_immune += dfn.ability_p("bulletproof")
    if "sound" in flags:
        p_immune += dfn.ability_p("soundproof")
    if "wind" in flags:
        p_immune += dfn.ability_p("windrider")
    if move.priority > 0:
        p_immune += dfn.ability_p(*PRIORITY_BLOCKERS)
    if eff <= 1:
        p_immune += dfn.ability_p("wonderguard")
    m = 1.0
    if t in (PokemonType.FIRE, PokemonType.ICE):
        m *= 1 - 0.5 * dfn.ability_p("thickfat")
    if t == PokemonType.FIRE:
        m *= 1 - 0.5 * dfn.ability_p("heatproof", "waterbubble")
        if "contact" in flags:
            m *= 1 + dfn.ability_p("fluffy")  # Fluffy: fire x2 (contact halving cancels)
    elif "contact" in flags:
        m *= 1 - 0.5 * dfn.ability_p("fluffy")
    if t == PokemonType.GHOST:
        m *= 1 - 0.5 * dfn.ability_p("purifyingsalt")
    if dfn.hp_fraction >= 1.0:
        m *= 1 - 0.5 * dfn.ability_p("multiscale", "shadowshield")
    if eff > 1:
        m *= 1 - 0.25 * dfn.ability_p("filter", "solidrock", "prismarmor")
    if move.category == MoveCategory.SPECIAL:
        m *= 1 - 0.5 * dfn.ability_p("icescales")
    return max(0.0, 1 - min(1.0, p_immune)) * m


def _attack_types(mon: Pokemon) -> set[PokemonType]:
    types = {t for t in (mon.type_1, mon.type_2) if t is not None}
    return types


def stab(attacker: Pokemon, move_type: PokemonType) -> float:
    original = _attack_types(attacker)
    if attacker.is_terastallized and attacker.tera_type is not None:
        if move_type == attacker.tera_type:
            return 2.0 if move_type in original else 1.5
        return 1.5 if move_type in original else 1.0
    return 1.5 if move_type in original else 1.0


def effective_speed(v: MonView, battle=None) -> float:
    spe = v.stats["spe"] * BOOST[v.mon.boosts.get("spe", 0)]
    if v.mon.status == Status.PAR:
        spe *= 0.5
    return spe  # Choice Scarf is handled as a mixture in moves_first


def moves_first(a: MonView, b: MonView, move: Move | None, battle=None) -> float:
    """Probability that ``a`` acts before ``b`` with ``move`` (our priority moves always first;
    the opponent's priority moves are checked by the caller). A possible Choice Scarf is a
    mixture of the with / without cases, not a blended speed: a 30% Scarf mon is either 1.5x
    faster or not at all."""
    if move is not None and move.priority > 0:
        return 1.0
    sa, sb = effective_speed(a, battle), effective_speed(b, battle)
    trick_room = battle is not None and any("trickroom" in str(f).lower() for f in battle.fields)
    pa, pb = min(1.0, a.item_p("choicescarf")), min(1.0, b.item_p("choicescarf"))
    p = 0.0
    for wa, fa in ((1 - pa, 1.0), (pa, 1.5)):
        for wb, fb in ((1 - pb, 1.0), (pb, 1.5)):
            if wa * wb == 0:
                continue
            x, y = sa * fa, sb * fb
            if trick_room:
                x, y = y, x
            p += wa * wb * (1.0 if x > y else 0.0 if x < y else 0.5)
    return p


FIXED_LEVEL_DAMAGE = {"seismictoss", "nightshade"}  # damage = user's level (100)
HALF_HP_MOVES = {"ruination", "superfang", "naturesmadness"}  # half the target's current HP


VARIABLE_BP = {
    "lowkick",
    "grassknot",
    "heavyslam",
    "heatcrash",
    "electroball",
    "gyroball",
    "reversal",
    "flail",
    "hardpress",
    "crushgrip",
    "wringout",
}
HP_DIFF_MOVES = {"endeavor", "finalgambit"}  # fixed damage from the HP of the two mons


def _weight(mon) -> float:
    entry = GEN.pokedex.get(mon.species, {})
    return (
        float(entry.get("weightkg") or mon.weight or 50.0)
        if hasattr(mon, "weight")
        else float(entry.get("weightkg") or 50.0)
    )


def variable_base_power(att: "MonView", dfn: "MonView", move: Move) -> int:
    """Base power of moves whose power depends on weight, speed or HP (basePower 0 in data)."""
    mid = move.id
    if mid in ("lowkick", "grassknot"):
        w = _weight(dfn.mon)
        return (
            20
            if w < 10
            else 40
            if w < 25
            else 60
            if w < 50
            else 80
            if w < 100
            else 100
            if w < 200
            else 120
        )
    if mid in ("heavyslam", "heatcrash"):
        r = _weight(att.mon) / max(_weight(dfn.mon), 0.1)
        return 120 if r >= 5 else 100 if r >= 4 else 80 if r >= 3 else 60 if r >= 2 else 40
    if mid == "electroball":
        r = effective_speed(att) / max(effective_speed(dfn), 1)
        return 150 if r >= 4 else 120 if r >= 3 else 80 if r >= 2 else 60 if r >= 1 else 40
    if mid == "gyroball":
        return int(min(150, 25 * effective_speed(dfn) / max(effective_speed(att), 1)) + 1)
    if mid in ("reversal", "flail"):
        p = att.hp_fraction
        return (
            200
            if p < 0.0417
            else 150
            if p < 0.1042
            else 100
            if p < 0.2083
            else 80
            if p < 0.3542
            else 40
            if p < 0.6875
            else 20
        )
    if mid == "hardpress":
        return max(1, int(100 * dfn.hp_fraction))
    if mid in ("crushgrip", "wringout"):
        return max(1, int(120 * dfn.hp_fraction))
    return move.base_power


def is_damaging(move: Move) -> bool:
    """Attacking move (including fixed-damage, HP-based and weight/speed-based moves)."""
    if (
        move.id in FIXED_LEVEL_DAMAGE
        or move.id in HALF_HP_MOVES
        or move.id in VARIABLE_BP
        or move.id in HP_DIFF_MOVES
    ):
        return True
    return move.category != MoveCategory.STATUS and bool(move.base_power)


def damage_fraction(att: MonView, dfn: MonView, move: Move, battle=None) -> float:
    """Expected fraction of the defender's max HP removed by ``move`` (0 for status moves)."""
    if move.id in HP_DIFF_MOVES:
        if dfn.mon.damage_multiplier(move) == 0:
            return 0.0
        own = att.hp_fraction * att.stats["hp"]
        if move.id == "finalgambit":
            return own / max(dfn.stats["hp"], 1)
        target = dfn.hp_fraction * dfn.stats["hp"]
        return max(0.0, target - own) / max(dfn.stats["hp"], 1)
    if move.id in FIXED_LEVEL_DAMAGE or move.id in HALF_HP_MOVES:
        if dfn.mon.damage_multiplier(move) == 0:  # e.g. Seismic Toss vs Ghost
            return 0.0
        acc = move.accuracy if isinstance(move.accuracy, float) else 1.0
        if move.id in FIXED_LEVEL_DAMAGE:
            return acc * 100 / max(dfn.stats["hp"], 1)
        return acc * 0.5 * dfn.hp_fraction
    if move.category == MoveCategory.STATUS:
        return 0.0
    if not move.base_power and move.id not in VARIABLE_BP:
        return 0.0
    eff = dfn.mon.damage_multiplier(move)
    if eff == 0:
        return 0.0
    ab = ability_multiplier(att, dfn, move, eff)
    if ab == 0:
        return 0.0
    physical = move.category == MoveCategory.PHYSICAL
    a_stat, d_stat = ("atk", "def") if physical else ("spa", "spd")
    if move.id == "bodypress":
        a_stat = "def"
    a = att.stats[a_stat] * BOOST[att.mon.boosts.get(a_stat, 0)]
    if move.id == "foulplay":
        a = dfn.stats["atk"] * BOOST[dfn.mon.boosts.get("atk", 0)]
    d = dfn.stats[d_stat] * BOOST[dfn.mon.boosts.get(d_stat, 0)]
    if move.id in ("psyshock", "psystrike", "secretsword"):
        d = dfn.stats["def"] * BOOST[dfn.mon.boosts.get("def", 0)]
    bp = variable_base_power(att, dfn, move) if move.id in VARIABLE_BP else move.base_power
    if move.id == "knockoff" and dfn.mon.item not in (None, ""):
        bp *= 1.5
    if move.id == "facade" and att.mon.status is not None:
        bp *= 2
    base = math.floor(math.floor(math.floor(2 * 100 / 5 + 2) * bp * a / max(d, 1)) / 50) + 2
    mult = stab(att.mon, move.type) * eff * ab * AVG_ROLL
    if physical and att.mon.status == Status.BRN and move.id != "facade":
        mult *= 0.5
    if battle is not None and battle.weather:
        w = next(iter(battle.weather))
        if w in (Weather.RAINDANCE, Weather.PRIMORDIALSEA):
            mult *= (
                1.5
                if move.type == PokemonType.WATER
                else 0.5
                if move.type == PokemonType.FIRE
                else 1
            )
        elif w in (Weather.SUNNYDAY, Weather.DESOLATELAND):
            if move.id == "hydrosteam":
                mult *= 1.5
            else:
                mult *= (
                    1.5
                    if move.type == PokemonType.FIRE
                    else 0.5
                    if move.type == PokemonType.WATER
                    else 1
                )
    mult *= 1 + 0.5 * att.item_p("choiceband" if physical else "choicespecs")
    mult *= 1 + 0.3 * att.item_p("lifeorb")
    mult *= 1 - 0.33 * dfn.item_p("assaultvest") if not physical else 1.0
    hits = move.expected_hits or 1
    acc = move.accuracy if isinstance(move.accuracy, float) else 1.0
    dmg = base * mult * hits * acc
    return dmg / max(dfn.stats["hp"], 1)


def best_damage(att: MonView, dfn: MonView, moves, battle=None) -> tuple[Move | None, float]:
    best, frac = None, 0.0
    for mv in moves:
        f = damage_fraction(att, dfn, mv, battle)
        if f > frac:
            best, frac = mv, f
    return best, frac


SPIKES_DAMAGE = {0: 0.0, 1: 1 / 8, 2: 1 / 6, 3: 1 / 4}
TOXIC_SPIKES_COST = {0: 0.0, 1: 0.08, 2: 0.15}  # HP-equivalent of regular / bad poison
STICKY_WEB_COST = 0.05


def _grounded(mon: Pokemon) -> bool:
    return (
        PokemonType.FLYING not in mon.types
        and mon.ability != "levitate"
        and mon.item != "airballoon"
    )


def entry_hazard_cost(mon: Pokemon, side_conditions) -> float:
    """HP fraction (plus an HP-equivalent for poison / Sticky Web) that ``mon`` loses when it
    switches in on a side with ``side_conditions`` ({SideCondition: layers})."""
    from poke_env.battle import SideCondition

    if mon.item == "heavydutyboots" or mon.ability == "magicguard":
        return 0.0
    cost = 0.0
    if SideCondition.STEALTH_ROCK in side_conditions:
        cost += mon.damage_multiplier(PokemonType.ROCK) / 8
    if _grounded(mon):
        cost += SPIKES_DAMAGE[min(3, side_conditions.get(SideCondition.SPIKES, 0))]
        tspikes = min(2, side_conditions.get(SideCondition.TOXIC_SPIKES, 0))
        if (
            tspikes
            and mon.status is None
            and not {PokemonType.POISON, PokemonType.STEEL} & set(mon.types)
            and mon.ability not in NO_POISON_ABILITIES
        ):
            cost += TOXIC_SPIKES_COST[tspikes]
        if SideCondition.STICKY_WEB in side_conditions:
            cost += STICKY_WEB_COST
    return cost


RECOVERY_MOVES = {
    "recover",
    "roost",
    "slackoff",
    "moonlight",
    "morningsun",
    "synthesis",
    "softboiled",
    "shoreup",
    "strengthsap",
    "milkdrink",
    "rest",
    "wish",
    "lunarblessing",
    "junglehealing",
}
NO_POISON_ABILITIES = {"poisonheal", "magicguard", "immunity", "purifyingsalt", "comatose"}


def _recovers(moves) -> bool:
    return any(m.id in RECOVERY_MOVES for m in moves)


def _passive_heal(v: MonView) -> float:
    return 0.0625 * v.item_p("leftovers", "blacksludge")


def _can_toxic(att_moves, dfn: MonView) -> bool:
    if not any(m.id == "toxic" for m in att_moves) or dfn.mon.status is not None:
        return False
    if {PokemonType.POISON, PokemonType.STEEL} & set(dfn.mon.types):
        return False
    return (dfn.ability or "") not in NO_POISON_ABILITIES


def _hits_to_ko(att: MonView, dfn: MonView, att_moves, dfn_moves, dmg: float) -> int:
    """Turns ``att`` needs to KO ``dfn``, accounting for the defender's sustain: a defender with
    reliable recovery that takes less than 50% per hit can heal forever; Leftovers / Black
    Sludge offset 1/16 per turn; Toxic eventually wears down a non-immune defender."""
    hp = max(dfn.hp_fraction, 0.01)
    net = dmg - _passive_heal(dfn)
    walled = net <= 0 or (_recovers(dfn_moves) and dmg < 0.5)
    if walled:
        return 12 if _can_toxic(att_moves, dfn) else 99
    return math.ceil(hp / net)


def one_v_one(a: MonView, b: MonView, a_moves, b_moves, battle=None) -> float:
    """Crude 1v1 score in [-1, 1]: >0 means ``a`` is expected to win the exchange.
    99 hits on both sides = mutual stall (score 0)."""
    ma, da = best_damage(a, b, a_moves, battle)
    mb, db = best_damage(b, a, b_moves, battle)
    hits_a = _hits_to_ko(a, b, a_moves, b_moves, da)
    hits_b = _hits_to_ko(b, a, b_moves, a_moves, db)
    if hits_a >= 99 and hits_b >= 99:
        return 0.0
    first = moves_first(a, b, ma, battle)
    if hits_a < hits_b or (hits_a == hits_b and first > 0.5):
        margin = (hits_b - hits_a) + (0.5 if first > 0.5 else 0)
        return min(1.0, 0.4 + 0.2 * margin)
    if hits_a == hits_b and first == 0.5:
        return 0.0
    margin = (hits_a - hits_b) + (0.5 if first < 0.5 else 0)
    return -min(1.0, 0.4 + 0.2 * margin)
