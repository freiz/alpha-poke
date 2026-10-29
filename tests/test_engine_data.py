"""Data tests (doc/engine-diff.md L8): poke-engine's and poke-env's data tables against
Showdown's Gen 9 Dex (``alpha_poke.enginecheck.data``). Every difference must be listed below
with its reason; a new one, or a listed one that no longer differs, fails the test."""

import json
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
WEATHER_HEAL = (
    "Showdown's heal depends on the weather in code; the engine's 1/2 is adjusted in code"
)

# {move: ({fields that differ}, why)}
KNOWN_MOVES = {
    "aromaticmist": ({"boosts"}, ALLY_ONLY),
    "coaching": ({"boosts"}, ALLY_ONLY),
    "dragoncheer": ({"effects"}, ALLY_ONLY),
    "helpinghand": (
        {"effects"},
        "it only affects an ally: nothing in singles (the engine's "
        "volatile on the user is a marker without effect)",
    ),
    "ceaselessedge": ({"side_condition"}, SHOWDOWN_IN_CODE),
    "stoneaxe": ({"side_condition"}, SHOWDOWN_IN_CODE),
    "partingshot": ({"boosts"}, SHOWDOWN_IN_CODE),
    "takeheart": ({"boosts"}, SHOWDOWN_IN_CODE),
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
    "healingwish": (
        {"heal", "side_condition"},
        "the engine: heal -1 = the user faints, the "
        "next mon is healed by its side condition (Showdown: in code)",
    ),
    "lunardance": (
        {"heal", "side_condition"},
        "the engine: as Healing Wish (L52; Showdown: a slot condition in code)",
    ),
    "memento": ({"heal"}, "the engine: heal -1 = the user faints (Showdown: in code)"),
    "moonlight": ({"heal"}, WEATHER_HEAL),
    "morningsun": ({"heal"}, WEATHER_HEAL),
    "synthesis": ({"heal"}, WEATHER_HEAL),
    "shoreup": ({"heal"}, WEATHER_HEAL),
    "tripleaxel": (
        {"base_power"},
        "the engine's data: 40 a hit; its hit-count branches (L58) give "
        "k hits of the mean of 20, 40, ..., 20k (Showdown's 20 / 40 / 60)",
    ),
    "struggle": (
        {"type"},
        "Showdown: Normal in its data, '???' (typeless) from its onModifyMove; "
        "the engine: typeless in its data (L232)",
    ),
    "revivalblessing": (
        {"pivot"},
        "Showdown: selfSwitch in its data (a switch request for a "
        "fainted one); the engine: its pick in code (Side::reviving, L166)",
    ),
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


# the duration items: no event of their own in Showdown (the weather / terrain / screen
# conditions' durationCallback reads them), but they decide how long what their holder sets lasts
DURATION_ITEMS = ["damprock", "heatrock", "icyrock", "lightclay", "smoothrock", "terrainextender"]


def test_engine_knows_every_item_with_an_effect():
    """Every Gen 9 item with a battle effect (an event handler or a stat change in Showdown,
    or a duration item) is one the engine knows; each one's effect has a dual-engine test."""
    from alpha_poke.enginecheck import _engine_item, data

    unknown = data.items_unknown_to_engine() + [i for i in DURATION_ITEMS if not _engine_item(i)]
    assert unknown == []


@pytest.mark.parametrize("key, got", [("ignore_evasion", "ignore_evasion_moves"),
                                      ("thaws_target", "thaw_target_moves")])  # fmt: skip
def test_move_lists_match_showdown(key, got):
    """The moves that ignore the target's evasion (Showdown's ignoreEvasion) and the ones that thaw
    their frozen target (thawsTarget; L191), among the engine's moves."""
    import alpha_search

    from alpha_poke.enginecheck import data

    eng = dict(alpha_search.move_targets())
    want = sorted(m["id"] for m in data.showdown()["moves"] if m["id"] in eng and m.get(key))
    assert len(want) >= 2
    assert getattr(alpha_search, got)() == want


def test_always_hit_moves_match_showdown():
    """The moves aimed at the target that cannot miss (Showdown's accuracy: true; the engine
    keeps 100 for them and lists them in Choices::always_hits, so accuracy modifiers -- Bright
    Powder, Zoom Lens -- leave them alone)."""
    import alpha_search

    from alpha_poke.enginecheck import data

    foe = {"normal", "any", "adjacentFoe", "allAdjacentFoes", "randomNormal", "allAdjacent",
           "scripted"}  # fmt: skip
    want = sorted(m["id"] for m in data.showdown()["moves"]
                  if m["accuracy"] == "always" and m["target"] in foe)  # fmt: skip
    assert alpha_search.always_hit_moves() == want


def test_max_pps_match_showdown():
    """Every move's max PP (L189: Lunar Dance restores it): Showdown's pp x 8 / 5 (a set's PP Ups),
    noPPBoosts its pp; the engine's Hidden Power variants Hidden Power's, Return at 102 Return's."""
    import re
    import subprocess

    import alpha_search

    js = (
        "const {Dex} = require(process.argv[1]); console.log(JSON.stringify(Object.fromEntries("
        "Dex.moves.all().map(m => [m.id, m.noPPBoosts ? m.pp : Math.floor(m.pp * 8 / 5)]))))"
    )
    sd = json.loads(subprocess.run(["node", "-e", js, str(ec.SIM)], capture_output=True, text=True,
                                   check=True).stdout)  # fmt: skip
    got = dict(alpha_search.max_pps())
    assert len(got) > 800
    for move, pp in got.items():
        base = re.sub(r"^(hiddenpower)[a-z]+[67]0$", r"\1", move).replace("return102", "return")
        assert pp == sd.get(base, 0), move


def test_low_max_pp_moves_match_showdown():
    """The moves whose max PP is below 10 (5 PP: 8 with Showdown's PP Ups; a few 1 and none):
    the engine keeps no max PP and Leppa Berry restores 10 up to it."""
    import alpha_search

    from alpha_poke.enginecheck import data

    want = sorted((m["id"], m["pp"] if m["no_pp_boosts"] else m["pp"] * 8 // 5)
                  for m in data.showdown()["moves"]
                  if (m["pp"] if m["no_pp_boosts"] else m["pp"] * 8 // 5) < 10)  # fmt: skip
    assert [tuple(x) for x in alpha_search.low_max_pp_moves()] == want


def test_moves_not_aimed_at_the_foe_match_showdown():
    """The status moves the engine aims at the opponent but Showdown not at the foe's Pokemon
    (weather, terrains, rooms, hazards, Haze, ...: Good as Gold lets them through; L72)."""
    import alpha_search

    from alpha_poke.enginecheck import data

    eng = dict(alpha_search.move_targets())
    foe = {"normal", "any", "adjacentFoe", "allAdjacentFoes", "randomNormal", "allAdjacent",
           "scripted"}  # fmt: skip
    want = sorted(m["id"] for m in data.showdown()["moves"] if m["category"] == "Status"
                  and eng.get(m["id"]) == "opponent" and m["target"] not in foe)  # fmt: skip
    assert alpha_search.not_aimed_at_foe_moves() == want


def test_paradox_species_match_showdown():
    """The species whose Booster Energy cannot be taken (Showdown's "Paradox" tag; L79)."""
    import subprocess

    import alpha_search

    from alpha_poke import enginecheck as ec

    js = (
        "const {Dex} = require(process.argv[1]); console.log(JSON.stringify(Dex.species.all()"
        ".filter(s => s.tags.includes('Paradox') && !s.isNonstandard).map(s => s.id)))"
    )
    want = sorted(json.loads(subprocess.run(["node", "-e", js, str(ec.SIM)], capture_output=True,
                                            text=True, check=True).stdout))  # fmt: skip
    assert alpha_search.paradox_species() == want


def test_skill_swap_failures_match_showdown():
    """The abilities Skill Swap fails on (Showdown's failskillswap flag; L106)."""
    import subprocess

    import alpha_search

    from alpha_poke import enginecheck as ec

    js = (
        "const {Dex} = require(process.argv[1]); console.log(JSON.stringify(Dex.abilities.all()"
        ".filter(a => a.flags.failskillswap && !a.isNonstandard).map(a => a.id)))"
    )
    want = sorted(json.loads(subprocess.run(["node", "-e", js, str(ec.SIM)], capture_output=True,
                                            text=True, check=True).stdout))  # fmt: skip
    assert alpha_search.fail_skill_swap_abilities() == want


@pytest.mark.parametrize("flag, got", [("cantsuppress", "cant_suppress_abilities"),
                                       ("notrace", "no_trace_abilities"),
                                       ("failroleplay", "fail_role_play_abilities"),
                                       ("noentrain", "fail_role_play_abilities")])  # fmt: skip
def test_ability_flags_match_showdown(flag, got):
    """The abilities no other one replaces (Showdown's cantsuppress: Mummy, Lingering Aroma, ...)
    and the ones Trace does not copy (notrace; L184); Role Play / Doodle / Entrainment's (L190)."""
    import subprocess

    import alpha_search

    from alpha_poke import enginecheck as ec

    js = (
        "const {Dex} = require(process.argv[1]); console.log(JSON.stringify(Dex.abilities.all()"
        ".filter(a => a.flags[process.argv[2]] && !a.isNonstandard).map(a => a.id)))"
    )
    want = sorted(json.loads(subprocess.run(["node", "-e", js, str(ec.SIM), flag], capture_output=True,
                                            text=True, check=True).stdout))  # fmt: skip
    assert getattr(alpha_search, got)() == want


def test_mold_breaker_abilities_match_showdown():
    """The abilities a Mold Breaker (Sunsteel Strike, ...) ignores: Showdown's breakable flag (L200:
    not the auras nor the Ruin abilities; Grass Pelt)."""
    import subprocess

    import alpha_search

    from alpha_poke import enginecheck as ec

    js = (
        "const {Dex} = require(process.argv[1]); const all = Dex.abilities.all().filter(a => "
        "!a.isNonstandard); console.log(JSON.stringify([all.map(a => a.id), all.filter(a => "
        "a.flags.breakable).map(a => a.id)]))"
    )
    ids, breakable = json.loads(subprocess.run(["node", "-e", js, str(ec.SIM)], capture_output=True,
                                               text=True, check=True).stdout)  # fmt: skip
    assert alpha_search.mold_breaker_abilities(ids) == sorted(breakable)


def test_sheer_force_moves_match_showdown():
    """The moves Sheer Force applies to: Showdown's onModifyMove -- the move has secondaries (or
    hasSheerForceBoost: Electro Shot, Order Up). The engine counted any move with a volatile
    status: a Sheer Force Copperajah's Protect did nothing (L236)."""
    import alpha_search

    from alpha_poke.enginecheck import data

    eng = set(alpha_search.sheer_force_moves())
    known = {m["id"] for m in data.showdown()["moves"]}
    want = {m["id"] for m in data.showdown()["moves"] if m["sheer_force"]}
    assert sorted(eng & known - want) == [] and sorted(want - eng) == []


def test_bypass_substitute_moves_match_showdown():
    """The status moves aimed at the foe that go through a Substitute (Showdown's bypasssub
    flag; any other fails against one: L133), among the engine's moves aimed at the opponent."""
    import alpha_search

    from alpha_poke.enginecheck import data

    eng = dict(alpha_search.move_targets())
    foe = {"normal", "any", "adjacentFoe", "allAdjacentFoes", "randomNormal", "allAdjacent",
           "scripted"}  # fmt: skip
    want = sorted(m["id"] for m in data.showdown()["moves"] if m["category"] == "Status"
                  and eng.get(m["id"]) == "opponent" and m["target"] in foe
                  and "bypasssub" in m["flags"])  # fmt: skip
    assert alpha_search.bypass_substitute_moves() == want


def test_fling_powers_match_showdown():
    """Fling's power with each Gen 9 item the engine knows (Showdown's item.fling.basePower; none:
    Fling fails; L140)."""
    import subprocess

    import alpha_search

    from alpha_poke.enginecheck import _engine_item

    js = (
        "const {Dex} = require(process.argv[1]); console.log(JSON.stringify(Dex.items.all()"
        ".filter(i => !i.isNonstandard).map(i => [i.id, i.fling ? i.fling.basePower : null])))"
    )
    items = json.loads(subprocess.run(["node", "-e", js, str(ec.SIM)], capture_output=True,
                                      text=True, check=True).stdout)  # fmt: skip
    items = [(i, p) for i, p in items if _engine_item(i)]
    assert len(items) > 150
    got = alpha_search.fling_powers([i.upper() for i, _ in items])
    assert {i: g for (i, _), g in zip(items, got, strict=True)} == dict(items)


def test_fail_copycat_moves_match_showdown():
    """The moves Copycat fails on (Showdown's failcopycat flag; L167), among the engine's moves."""
    import alpha_search

    from alpha_poke.enginecheck import data

    eng = dict(alpha_search.move_targets())
    want = sorted(m["id"] for m in data.showdown()["moves"]
                  if m["id"] in eng and "failcopycat" in m["flags"])  # fmt: skip
    assert len(want) > 30
    assert alpha_search.fail_copycat_moves() == want


def test_dance_moves_match_showdown():
    """The dance moves (Showdown's dance flag: a Dancer uses them too; L171)."""
    import alpha_search

    from alpha_poke.enginecheck import data

    eng = dict(alpha_search.move_targets())
    want = sorted(m["id"] for m in data.showdown()["moves"]
                  if m["id"] in eng and "dance" in m["flags"])  # fmt: skip
    assert len(want) >= 12
    assert alpha_search.dance_moves() == want


def test_pressure_moves_match_showdown():
    """The moves a foe's Pressure takes one more PP of (Showdown's pressureTargets: aimed at the
    foe, the field's 'all' moves, mustpressure; L177), among the engine's moves."""
    import alpha_search

    from alpha_poke.enginecheck import data

    eng = dict(alpha_search.move_targets())
    foe = {"normal", "any", "adjacentFoe", "allAdjacentFoes", "allAdjacent", "randomNormal",
           "scripted", "all"}  # fmt: skip
    want = sorted(m["id"] for m in data.showdown()["moves"] if m["id"] in eng
                  and (m["target"] in foe or "mustpressure" in m["flags"]))  # fmt: skip
    ids = {m["id"] for m in data.showdown()["moves"]}
    got = [m for m in alpha_search.pressure_moves() if m in ids]
    assert sorted(set(want) - set(got)) == [] and sorted(set(got) - set(want)) == []


def test_forme_weights_match_showdown():
    """The formes whose weight the engine changes with them (L183) against Showdown's weighthg."""
    import subprocess

    import alpha_search

    got = dict(alpha_search.forme_weights())
    assert len(got) == 15
    js = (
        "const {Dex} = require(process.argv[1]); console.log(JSON.stringify(process.argv.slice(2)"
        ".map(n => Dex.species.get(n).weighthg)))"
    )
    want = json.loads(subprocess.run(["node", "-e", js, str(ec.SIM), *got], capture_output=True,
                                     text=True, check=True).stdout)  # fmt: skip
    assert list(got.values()) == want
