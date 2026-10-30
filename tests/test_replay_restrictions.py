"""A replay's own side has no request to name its usable moves (issue #28: a Choice Band
Kingambit's every move offered in a review). Dual checks on scripted Showdown battles: the
options of the state replay-built for p1 (enginecheck/replaybuild.py, the training positions' and
the reviews' path) against Showdown's own state's, at every decision -- and the restriction
really on (Showdown's options at the step after the script)."""

from pathlib import Path

import pytest

from alpha_poke.enginecheck.scenarios import FAST, FILLER, S, team

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "vendor/pokemon-showdown/dist/sim").exists(),
                                reason="needs the built Showdown simulator")  # fmt: skip


def _run(p1: str, p2: str, script: list[dict], max_turns: int = 6):
    """[(step, Showdown's p1 options, the replay-built state's option differences)] of p1."""
    from alpha_poke.agents import slots
    from alpha_poke.enginecheck.replaybuild import _option_diffs, decisions

    stats: dict = {}
    out = [(k, sorted(n for n in slots.names(t) if n), _option_diffs(built, t))
           for k, side, b, built, t in decisions(p1, p2, 1, max_turns, stats, script)
           if side == "p1"]  # fmt: skip
    assert not stats["errors"], stats["errors"]
    return out


def _moves(options: list[str]) -> set[str]:
    return {o.removesuffix("-tera") for o in options if not o.startswith("switch ")}


def _check(p1: str, p2: str, script: list[dict], want: set[str], max_turns: int = 6,
           play: list[dict] | None = None):  # fmt: skip
    """``want``: Showdown's moves for p1 after ``script`` (``play``: the whole script played)."""
    rows = _run(p1, p2, play or script, max_turns)
    assert all(not d for _, _, d in rows), [(k, d) for k, _, d in rows if d]
    after = rows[len(script)]  # (p1's decision after the script)
    assert _moves(after[1]) == want, after


SLOW = S("Snorlax", "Leftovers", "Thick Fat", ["Slack Off", "Body Slam", "Curse", "Rest"])


def test_a_choice_lock():
    gambit = S("Kingambit", "Choice Band", "Supreme Overlord",
               ["Iron Head", "Kowtow Cleave", "Low Kick", "Swords Dance"])  # fmt: skip
    _check(
        team(gambit, FILLER), team(SLOW, FILLER), [{"p1": "move 1", "p2": "move 1"}], {"ironhead"}
    )


def test_gorilla_tactics():
    darm = S("Darmanitan-Galar", "Heavy-Duty Boots", "Gorilla Tactics",
             ["Icicle Crash", "Flare Blitz", "U-turn", "Earthquake"])  # fmt: skip
    _check(
        team(darm, FILLER), team(SLOW, FILLER), [{"p1": "move 4", "p2": "move 1"}], {"earthquake"}
    )


def test_a_choice_lock_ends_with_the_item_knocked_off():
    pult = S("Dragapult", "Choice Band", "Clear Body",
             ["Dragon Darts", "U-turn", "Sucker Punch", "Tera Blast"], FAST, "Jolly")  # fmt: skip
    pex = S("Toxapex", "Black Sludge", "Regenerator", ["Knock Off", "Recover", "Haze", "Toxic"])
    _check(team(pult, FILLER), team(pex, FILLER), [{"p1": "move 1", "p2": "move 1"}],
           {"dragondarts", "uturn", "suckerpunch", "terablast"})  # fmt: skip


def test_a_choice_lock_out_of_pp_struggles():
    """Draco Meteor's 8 PP, two a use against Pressure: four uses and the lock has none left --
    Showdown's request offers Struggle alone."""
    pult = S("Dragapult", "Choice Specs", "Clear Body",
             ["Draco Meteor", "Shadow Ball", "U-turn", "Flamethrower"], FAST, "Timid")  # fmt: skip
    corv = S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"],
             "252 HP / 4 Def / 252 SpD", "Calm")  # fmt: skip
    script = [{"p1": "move 1", "p2": "move 1"}] * 4
    rows = _run(team(pult, FILLER), team(corv, FILLER), script)
    assert all(not d for _, _, d in rows), [(k, d) for k, _, d in rows if d]
    assert _moves(rows[len(script)][1]) == {"struggle"}, rows[len(script)]


def test_taunt_encore_and_disable():
    """The engine's own (Taunt: no status move; Encore: the last move; Disable: its slot)."""
    mon = S(
        "Clefable",
        "Leftovers",
        "Magic Guard",
        ["Moonblast", "Calm Mind", "Moonlight", "Flamethrower"],
    )
    taunter = S(
        "Grimmsnarl", "Light Clay", "Prankster", ["Taunt", "Encore", "Disable", "Spirit Break"]
    )
    _check(team(mon, FILLER), team(taunter, FILLER), [{"p1": "move 2", "p2": "move 1"}],
           {"moonblast", "flamethrower"})  # fmt: skip
    first = {"p1": "move 2", "p2": "move 4"}  # (a last move to encore / disable)
    _check(
        team(mon, FILLER),
        team(taunter, FILLER),
        [first, {"p1": "move 2", "p2": "move 2"}],
        {"calmmind"},
    )
    _check(team(mon, FILLER), team(taunter, FILLER), [first, {"p1": "move 2", "p2": "move 3"}],
           {"moonblast", "moonlight", "flamethrower"})  # fmt: skip


def test_imprison():
    """Showdown's Imprison is a hidden disable (its request still offers the move; choosing it is
    an error): the script plays every turn, no random choice after it."""
    mon = S(
        "Clefable",
        "Leftovers",
        "Magic Guard",
        ["Moonblast", "Calm Mind", "Moonlight", "Flamethrower"],
    )
    mew = S(
        "Mew",
        "Leftovers",
        "Synchronize",
        ["Imprison", "Moonblast", "Calm Mind", "Psychic"],
        FAST,
        "Timid",
    )
    script = [{"p1": "move 3", "p2": "move 1"}, {"p1": "move 3", "p2": "move 4"}]
    _check(team(mon, FILLER), team(mew, FILLER), script[:1], {"moonlight", "flamethrower"}, max_turns=2,
           play=script)  # fmt: skip
