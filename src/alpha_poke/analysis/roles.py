"""L1 of the layered archetype representation: functional roles of a mon.

A role is derived from moves / abilities / items (all compared as Showdown IDs). For a mon in a
replay we combine two sources:

* revealed information (a revealed role move makes the role certain), and
* the species prior from Smogon usage stats. Smogon only publishes marginals, and the
  indicators of one role are usually parts of the *same* set (Reflect + Light Screen + Light
  Clay), so treating them as independent overestimates badly. We use the maximum over the
  role's indicators instead, i.e. a conservative lower bound on P(role).

The result is a probability per role, so a team's role profile is the sum over its six mons.
"""

import functools
from collections.abc import Iterable

from alpha_poke.data.smogon_stats import SpeciesStats, UsageStats


@functools.lru_cache(maxsize=1 << 16)
def _to_id(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def to_id(name: str | None) -> str:
    """Showdown's id (lowercase letters and digits). Cached: names repeat (species, moves,
    items), and self-play called it ~1,000 times per decision (2026-10-11: 22% of a worker)."""
    return _to_id(name) if isinstance(name, str) else ""


def _ids(*names: str) -> frozenset[str]:
    return frozenset(to_id(n) for n in names)


# role -> (moves, abilities, items)
ROLES: dict[str, tuple[frozenset, frozenset, frozenset]] = {
    "hazard_setter": (
        _ids("Stealth Rock", "Spikes", "Toxic Spikes", "Sticky Web", "Ceaseless Edge", "Stone Axe"),
        _ids("Toxic Debris"),
        frozenset(),
    ),
    "hazard_removal": (
        _ids("Rapid Spin", "Defog", "Mortal Spin", "Tidy Up", "Court Change"),
        frozenset(),
        frozenset(),
    ),
    "pivot": (
        _ids(
            "U-turn",
            "Volt Switch",
            "Flip Turn",
            "Parting Shot",
            "Teleport",
            "Chilly Reception",
            "Shed Tail",
        ),
        frozenset(),
        frozenset(),
    ),
    "setup_sweeper": (
        _ids(
            "Swords Dance",
            "Dragon Dance",
            "Nasty Plot",
            "Calm Mind",
            "Quiver Dance",
            "Bulk Up",
            "Shell Smash",
            "Agility",
            "Belly Drum",
            "Coil",
            "Victory Dance",
            "Shift Gear",
            "Tidy Up",
            "Geomancy",
            "Clangorous Soul",
            "Fillet Away",
            "Tail Glow",
            "Curse",
        ),
        frozenset(),
        frozenset(),
    ),
    "reliable_recovery": (
        _ids(
            "Recover",
            "Roost",
            "Slack Off",
            "Moonlight",
            "Morning Sun",
            "Synthesis",
            "Soft-Boiled",
            "Shore Up",
            "Strength Sap",
            "Wish",
            "Rest",
            "Milk Drink",
            "Lunar Blessing",
            "Life Dew",
            "Jungle Healing",
        ),
        _ids("Regenerator"),
        frozenset(),
    ),
    "priority": (
        _ids(
            "Sucker Punch",
            "Extreme Speed",
            "Aqua Jet",
            "Bullet Punch",
            "Ice Shard",
            "Mach Punch",
            "Shadow Sneak",
            "Vacuum Wave",
            "Quick Attack",
            "Accelerock",
            "Grassy Glide",
            "Jet Punch",
            "First Impression",
            "Thunderclap",
        ),
        frozenset(),
        frozenset(),
    ),
    "status_spreader": (
        _ids(
            "Will-O-Wisp",
            "Toxic",
            "Thunder Wave",
            "Spore",
            "Sleep Powder",
            "Yawn",
            "Glare",
            "Nuzzle",
            "Hypnosis",
            "Dark Void",
            "Malignant Chain",
        ),
        frozenset(),
        frozenset(),
    ),
    "anti_setup": (
        _ids(
            "Haze",
            "Clear Smog",
            "Roar",
            "Whirlwind",
            "Dragon Tail",
            "Circle Throw",
            "Encore",
            "Taunt",
        ),
        _ids("Unaware"),
        frozenset(),
    ),
    "screens": (_ids("Reflect", "Light Screen", "Aurora Veil"), frozenset(), _ids("Light Clay")),
    "item_control": (
        _ids("Knock Off", "Trick", "Switcheroo", "Thief", "Covet", "Poltergeist"),
        frozenset(),
        frozenset(),
    ),
    "weather_terrain_setter": (
        _ids(
            "Rain Dance",
            "Sunny Day",
            "Sandstorm",
            "Snowscape",
            "Chilly Reception",
            "Electric Terrain",
            "Grassy Terrain",
            "Psychic Terrain",
            "Misty Terrain",
        ),
        _ids(
            "Drizzle",
            "Drought",
            "Sand Stream",
            "Snow Warning",
            "Orichalcum Pulse",
            "Hadron Engine",
            "Electric Surge",
            "Grassy Surge",
            "Psychic Surge",
            "Misty Surge",
            "Seed Sower",
        ),
        frozenset(),
    ),
    "weather_abuser": (
        _ids("Weather Ball", "Solar Beam", "Hydro Steam", "Electro Shot"),
        _ids(
            "Swift Swim",
            "Chlorophyll",
            "Sand Rush",
            "Slush Rush",
            "Sand Force",
            "Solar Power",
            "Surge Surfer",
        ),
        frozenset(),
    ),
    "booster_paradox": (frozenset(), frozenset(), _ids("Booster Energy")),
    "choice_locked": (
        frozenset(),
        frozenset(),
        _ids("Choice Band", "Choice Specs", "Choice Scarf"),
    ),
    "physical_wall": (frozenset(), frozenset(), _ids("Rocky Helmet")),
    "special_wall": (frozenset(), frozenset(), _ids("Assault Vest")),
}
ROLE_NAMES = list(ROLES)


def species_role_prior(s: SpeciesStats) -> dict[str, float]:
    """Lower bound on P(role) for a species from Smogon stats (max over the role's indicators)."""
    out = {}
    abilities = {to_id(k): v for k, v in s.abilities.items()}
    items = {to_id(k): v for k, v in s.items.items()}
    for role, (moves, abils, its) in ROLES.items():
        p_move = max((s.move_has.get(m, 0.0) for m in moves), default=0.0)
        p_abil = sum(abilities.get(a, 0.0) for a in abils)  # alternatives: probabilities add
        p_item = sum(items.get(i, 0.0) for i in its)
        out[role] = min(1.0, max(p_move, p_abil, p_item))
    return out


def revealed_roles(moves: Iterable[str], ability: str | None, item: str | None) -> set[str]:
    mv = {to_id(m) for m in moves}
    ab, it = to_id(ability), to_id(item)
    return {r for r, (ms, abils, its) in ROLES.items() if mv & ms or ab in abils or it in its}


class RoleModel:
    """Role probabilities for a mon given its species and whatever was revealed."""

    def __init__(self, stats: UsageStats):
        self._prior = {to_id(n): species_role_prior(s) for n, s in stats.species.items()}

    def prior(self, species: str) -> dict[str, float]:
        sid = to_id(species.replace("-*", ""))
        if sid in self._prior:
            return self._prior[sid]
        # preview forms like "Urshifu-*" / "Zamazenta-*": fall back to any matching forme
        match = [v for k, v in self._prior.items() if k.startswith(sid)]
        return match[0] if match else dict.fromkeys(ROLE_NAMES, 0.0)

    def roles(
        self, species: str, moves: Iterable[str] = (), ability=None, item=None
    ) -> dict[str, float]:
        p = dict(self.prior(species))
        for r in revealed_roles(moves, ability, item):
            p[r] = 1.0
        return p
