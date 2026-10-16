"""Data tests (doc/engine-diff.md L8): poke-engine's and poke-env's data tables against
Showdown's Gen 9 Dex (``alpha_poke.enginecheck.data``). Every difference must be listed below
with its reason; a new one, or a listed one that no longer differs, fails the test."""

import shutil

import pytest

from alpha_poke import enginecheck as ec

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (ec.SIM / "index.js").exists(),
    reason="needs node and the built Showdown checkout (vendor/pokemon-showdown/dist/sim)",
)

SHOWDOWN_IN_CODE = "Showdown does it in code (onHit / onAfterHit), the engine in its data"
ENGINE_IN_CODE = "the engine does it in code (choice_effects), Showdown in its data"
ALLY_ONLY = "it only affects an ally: nothing in singles (the engine has no effect either)"
NO_EVASION = "the engine has no evasion stat (known limitation; Defog's drop is in code, L1)"
SELF_DAMAGE = "the engine's negative heal is the user's HP loss (Showdown: in code)"
WEATHER_HEAL = "Showdown's heal depends on the weather in code; the engine's 1/2 is adjusted in code"

# {move: ({fields that differ}, why)}
KNOWN_MOVES = {
    "aromaticmist": ({"boosts"}, ALLY_ONLY),
    "coaching": ({"boosts"}, ALLY_ONLY),
    "dragoncheer": ({"effects"}, ALLY_ONLY),
    "helpinghand": ({"effects"}, "it only affects an ally: nothing in singles (the engine's "
                    "volatile on the user is a marker without effect)"),
    "ceaselessedge": ({"side_condition"}, SHOWDOWN_IN_CODE),
    "stoneaxe": ({"side_condition"}, SHOWDOWN_IN_CODE),
    "partingshot": ({"boosts"}, SHOWDOWN_IN_CODE),
    "tidyup": ({"boosts"}, SHOWDOWN_IN_CODE),
    "junglehealing": ({"heal"}, SHOWDOWN_IN_CODE),
    "lunarblessing": ({"heal"}, SHOWDOWN_IN_CODE),
    "throatchop": ({"effects"}, SHOWDOWN_IN_CODE),
    "triattack": ({"effects"}, "Showdown: 20% for one of three in code; the engine 6.67% each"),
    "clangoroussoul": ({"boosts"}, ENGINE_IN_CODE),
    "filletaway": ({"boosts"}, ENGINE_IN_CODE),
    "shedtail": ({"pivot", "effects"}, ENGINE_IN_CODE),
    "curse": ({"boosts", "effects"}, "Ghost / non-Ghost in code in both (L2a / L2b)"),
    "defog": ({"boosts"}, NO_EVASION),
    "doubleteam": ({"boosts"}, NO_EVASION),
    "minimize": ({"boosts"}, NO_EVASION),
    "sweetscent": ({"boosts"}, NO_EVASION),
    "chloroblast": ({"heal"}, SELF_DAMAGE),
    "steelbeam": ({"heal"}, SELF_DAMAGE),
    "healingwish": ({"heal", "side_condition"}, "the engine: heal -1 = the user faints, the "
                    "next mon is healed by its side condition (Showdown: in code)"),
    "memento": ({"heal"}, "the engine: heal -1 = the user faints (Showdown: in code)"),
    "moonlight": ({"heal"}, WEATHER_HEAL),
    "morningsun": ({"heal"}, WEATHER_HEAL),
    "synthesis": ({"heal"}, WEATHER_HEAL),
    "shoreup": ({"heal"}, WEATHER_HEAL),
    "leechseed": ({"flags"}, "the engine makes Grass types immune through the powder flag"),
    "tripleaxel": ({"base_power"}, "the engine: 3 hits of 40 (Showdown 20, 40, 60; approximation)"),
    "ficklebeam": ({"base_power"}, "the engine: the expected power 80 x 1.3 (Showdown: 30% "
                   "double; L8b)"),
    "uproar": ({"effects"}, "not implemented in the engine (rare in OU)"),
    "revivalblessing": ({"pivot"}, "not implemented in the engine (rare in OU)"),
}


def test_moves_match_showdown():
    """poke-engine's moves, field by field (type, accuracy, category, power, priority, flags,
    stat changes, status / volatile effects, drain, recoil, heal, side condition, drag /
    pivot), against Showdown's Gen 9 moves."""
    from alpha_poke.enginecheck import data

    got = {m: set(d) for m, d in data.move_diffs().items()}
    want = {m: f for m, (f, _) in KNOWN_MOVES.items()}
    new = {m: data.move_diffs()[m] for m in got if got[m] != want.get(m)}
    gone = sorted(m for m in want if m not in got)
    assert not new, f"differences not listed: {new}"
    assert not gone, f"listed but no longer different (remove them): {gone}"


def test_type_chart_matches_showdown():
    from alpha_poke.enginecheck import data

    assert data.type_chart_diffs() == {}


def test_engine_base_stats_match_showdown():
    """The engine's own base stats (its forme-change table: Minior, Palafin, Eiscue, ...)."""
    from alpha_poke.enginecheck import data

    assert len(data.engine_base_stat_species()) >= 6
    assert data.base_stat_diffs() == {}


def test_pokeenv_species_match_showdown():
    """poke-env's pokedex (base stats, types, weight, abilities), what our state construction
    and the belief model read for the engine's state."""
    from alpha_poke.enginecheck import data

    assert data.pokeenv_species_diffs() == {}


def test_pokeenv_moves_match_showdown():
    from alpha_poke.enginecheck import data

    assert data.pokeenv_move_diffs() == {}
