"""Scenarios: short scripted battles, one family per mechanism, its dimensions combined
(doc/difftest.md). Every check of the framework runs on each of them. A family names the
mechanism, its sets are neutral -- no ability, item or move beyond the mechanism's that turns a
mechanic on by itself (2026-10-24 review: a Spite test passed through Gengar's Cursed Body) --
and its script plays the dimensions (before / after the event; an item changing hands, an ability
changing, a suppression). Showdown's Battle validates no team: a set may have any moves.

A script is the first decision points' choices ({"p1": ..., "p2": ...}); random after it. Leads
are each team's first set; "switch 2" is its second."""

import itertools
import json

from alpha_poke.enginecheck.difftest import PCT, Spec


def S(species: str, item: str, ability: str, moves: list[str], evs: str = "252 HP / 4 Atk / 252 SpD",
      nature: str = "Careful", tera: str = "Normal") -> str:
    """A set in Showdown's export text."""
    head = f"{species} @ {item}" if item else species
    return "\n".join([head, f"Ability: {ability}", f"Tera Type: {tera}", f"EVs: {evs}", f"{nature} Nature",
                      *(f"- {m}" for m in moves)]) + "\n"  # fmt: skip


def team(*sets: str) -> str:
    return "\n".join(sets)


# a neutral bench mon: nothing that changes another mechanic
FILLER = S("Snorlax", "Leftovers", "Thick Fat", ["Body Slam", "Rest", "Slack Off", "Curse"])
FAST = "252 HP / 4 Atk / 252 Spe"


def _spec(name: str, p1: str, p2: str, script: list[dict], seed: int = 1, max_turns: int = 8,
          fmt: str = "", expect: tuple = ()) -> Spec:
    """``expect``: the log lines (substrings) that show the mechanism happened."""
    return Spec(f"scenario/{name}", p1, p2, seed, max_turns, json.dumps(script), fmt, ("scenario",), expect)


def extender_items() -> list[Spec]:
    """A Heat Rock sun's length is fixed as it begins: the item works unless its holder's ability
    then is Klutz -- not under Neutralizing Gas (R4, R4'). The setter (faster) sets it on turn 1;
    the foe then, the same turn: Knock Off (the item gone after), Trick (it changes hands), Skill
    Swap (the ability changes after), or nothing."""
    out = []
    events = {"knockoff": "move 1", "trick": "move 2", "skillswap": "move 3", "none": "move 4"}
    for ability, event, gas in itertools.product(("Klutz", "No Guard"), events, (False, True)):
        setter = S("Golurk", "Heat Rock", ability, ["Sunny Day", "Earthquake", "Poltergeist", "Rock Polish"],
                   FAST, "Jolly")  # fmt: skip
        foe = S("Weezing-Galar" if gas else "Slowking-Galar", "Leftovers",
                "Neutralizing Gas" if gas else "Regenerator", ["Knock Off", "Trick", "Skill Swap", "Slack Off"])  # fmt: skip
        script = [{"p1": "move 1", "p2": events[event]}] + [{"p1": "move 2", "p2": "move 4"}] * 4
        out.append(_spec(f"extender/{ability.lower().replace(' ', '')}-{event}-{'gas' if gas else 'nogas'}",
                         team(setter, FILLER), team(foe, FILLER), script))  # fmt: skip
    # (a screen: Light Clay, a Klutz setter, the clay knocked off after)
    for ability in ("Klutz", "Cursed Body"):
        setter = S("Golurk", "Light Clay", ability, ["Reflect", "Earthquake", "Poltergeist", "Light Screen"], FAST, "Jolly")
        foe = S("Slowking-Galar", "Leftovers", "Regenerator", ["Knock Off", "Trick", "Skill Swap", "Slack Off"])
        script = [{"p1": "move 1", "p2": "move 1"}] + [{"p1": "move 2", "p2": "move 4"}] * 3
        out.append(_spec(f"extender/screen-{ability.lower().replace(' ', '')}-knockoff", team(setter, FILLER),
                         team(foe, FILLER), script))  # fmt: skip
    return out


def pp_takers() -> list[Spec]:
    """Spite (4 PP) and Eerie Spell (3) off the target's last move: before / after its move this
    turn (R1, R5, R5'); no other mechanic that tracks the last move in the sets."""
    out = []
    target = S("Corviknight", "Leftovers", "Mirror Armor", ["Brave Bird", "Roost", "Defog", "U-turn"])
    for move, fast in itertools.product(("Spite", "Eerie Spell"), (True, False)):
        taker = S("Slowking-Galar" if move == "Eerie Spell" else "Spiritomb", "Leftovers",
                  "Regenerator" if move == "Eerie Spell" else "Infiltrator",
                  [move, "Slack Off", "Foul Play", "Thunder Wave"], FAST if fast else "252 HP / 252 SpD / 4 Spe",
                  "Timid" if fast else "Calm")  # fmt: skip
        script = [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}, {"p1": "move 1", "p2": "move 1"}]
        out.append(_spec(f"pp/{move.lower().replace(' ', '')}-{'faster' if fast else 'slower'}",
                         team(target, FILLER), team(taker, FILLER), script))  # fmt: skip
    return out


def transforms() -> list[Spec]:
    """A transform's copies and what comes back after it (R3): a Ditto (Imposter on its entry /
    the Transform move) copies Copperajah, goes out and comes back; the foe's Heavy Slam / Low
    Kick on it reads its weight. And a Slow Start copied mid-turn by a mon in since the turn's
    start (S153)."""
    out = []
    for how, move in itertools.product(("imposter", "transform"), ("Heavy Slam", "Low Kick")):
        ditto = S("Ditto", "Choice Scarf", "Imposter" if how == "imposter" else "Limber", ["Transform"])
        heavy = S("Copperajah", "Leftovers", "Sheer Force", [move, "Protect", "Stealth Rock", "Iron Defense"])
        lead = [{"p1": "switch 2", "p2": "move 2"}] if how == "imposter" else []
        script = ([{"p1": "move 1", "p2": "move 2"}] if how == "transform" else [{"p1": "move 1", "p2": "move 2"}]) + [
            {"p1": "switch 2", "p2": "move 3"}, {"p1": "switch 2", "p2": "move 1"}, {"p1": "move 1", "p2": "move 1"}]
        p1 = team(FILLER, ditto) if how == "imposter" else team(ditto, FILLER)
        out.append(_spec(f"transform/{how}-{move.lower().replace(' ', '')}", p1, team(heavy, FILLER),
                         lead + script if how == "imposter" else script))  # fmt: skip
    # (its target's forme now: a Terapagos's Tera Shift Terastal forme, 16 kg -- not 6.5, its base)
    terapagos = S("Terapagos", "Leftovers", "Tera Shift", ["Tera Starstorm", "Calm Mind", "Rapid Spin", "Dark Pulse"],
                  tera="Stellar")  # fmt: skip
    out.append(_spec("transform/imposter-into-a-forme", team(FILLER, S("Ditto", "Leftovers", "Imposter", ["Transform"])),
                     team(terapagos, FILLER), [{"p1": "switch 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2"},
                                              {"p1": "move 2", "p2": "move 2"}],
                     expect=("|-transform|p1a: Ditto|p2a: Terapagos",)))  # fmt: skip
    # (and the target's forme changes after: its Terastallization, the Stellar forme -- the copy
    # keeps the weight it took)
    out.append(_spec("transform/target-forme-after", team(FILLER, S("Ditto", "Leftovers", "Imposter", ["Transform"])),
                     team(terapagos, FILLER), [{"p1": "switch 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2 terastallize"},
                                              {"p1": "move 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2"}],
                     expect=("|-transform|p1a: Ditto|p2a: Terapagos", "Terapagos-Stellar")))  # fmt: skip
    # (a copied 1-PP move: Showdown's min(5, its PP) -- Revival Blessing's 1)
    pawmot = S("Pawmot", "Leftovers", "Volt Absorb", ["Revival Blessing", "Close Combat", "Nuzzle", "Double Shock"])
    out.append(_spec("transform/copied-one-pp", team(FILLER, S("Ditto", "Leftovers", "Imposter", ["Transform"])),
                     team(pawmot, FILLER), [{"p1": "switch 2", "p2": "move 3"}, {"p1": "move 3", "p2": "move 3"},
                                           {"p1": "move 2", "p2": "move 3"}],
                     expect=("|-transform|p1a: Ditto|p2a: Pawmot",)))  # fmt: skip
    gigas = S("Regigigas", "Leftovers", "Slow Start", ["Body Slam", "Protect", "Knock Off", "Substitute"])
    ditto = S("Ditto", "Leftovers", "Limber", ["Transform"])
    out.append(_spec("transform/slowstart-copied", team(ditto, FILLER), team(gigas, FILLER),
                     [{"p1": "move 1", "p2": "move 2"}, {"p1": "move 1", "p2": "move 1"},
                      {"p1": "move 2", "p2": "move 1"}]))  # fmt: skip
    return out


def locks() -> list[Spec]:
    """A locked Outrage's later turns into an Endure, a Protect, a Fairy (immune: the lock ends),
    a Substitute (S152)."""
    out = []
    user = S("Dragonite", "Leftovers", "Inner Focus", ["Outrage", "Roost", "Extreme Speed", "Earthquake"], FAST, "Jolly")
    # (an Endure that holds on: a frail target, Outrage's first hit would knock it out)
    frail = S("Pikachu", "", "Static", ["Endure", "Protect", "Thunderbolt", "Volt Switch"], "4 HP / 252 SpA / 252 Spe", "Timid")
    out.append(_spec("lock/outrage-into-endure", team(user, FILLER), team(frail, FILLER),
                     [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 1", "p2": "move 2"}, {"p1": "move 1", "p2": "move 3"}],
                     expect=("|-activate|p2a: Pikachu|move: Endure", "|[from] lockedmove")))  # fmt: skip
    for name, foe, move in (("endure", S("Araquanid", "Leftovers", "Water Bubble", ["Endure", "Liquidation", "Mirror Coat", "Leech Life"]), "move 1"),
                            ("protect", S("Toxapex", "Leftovers", "Regenerator", ["Protect", "Recover", "Toxic", "Haze"]), "move 1"),
                            ("fairy", S("Clefable", "Leftovers", "Unaware", ["Moonblast", "Soft-Boiled", "Calm Mind", "Protect"]), "move 3"),
                            ("substitute", S("Toxapex", "Leftovers", "Regenerator", ["Substitute", "Recover", "Toxic", "Haze"]), "move 1")):  # fmt: skip
        script = [{"p1": "move 1", "p2": "move 2"}, {"p1": "move 1", "p2": move}, {"p1": "move 1", "p2": "move 2"}]
        out.append(_spec(f"lock/outrage-{name}", team(user, FILLER), team(foe, FILLER), script))
    return out


def failed_moves() -> list[Spec]:
    """A move that failed doubles the next turn's Stomping Tantrum / Temper Flare (Showdown's
    moveLastTurnResult): a Fake Out past its first turn, a Ground move into a Flying type."""
    inc = S("Incineroar", "Leftovers", "Blaze", ["Fake Out", "Temper Flare", "Knock Off", "Parting Shot"])
    tusk = S("Great Tusk", "Leftovers", "Protosynthesis", ["Headlong Rush", "Stomping Tantrum", "Rapid Spin", "Bulk Up"])
    foe = S("Corviknight", "Leftovers", "Mirror Armor", ["Roost", "Body Press", "Iron Defense", "Brave Bird"])
    return [
        _spec("failed/fakeout-temperflare", team(inc, FILLER), team(foe, FILLER),
              [{"p1": "move 3", "p2": "move 1"}, {"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}]),
        _spec("failed/immune-stompingtantrum", team(tusk, FILLER), team(foe, FILLER),
              [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}, {"p1": "move 2", "p2": "move 3"}]),
    ]


def item_phases() -> list[Spec]:
    """F1's evidence across an item's phases (R2, R2'): hits before a Trick, after a Knock Off,
    after a Magician / Thief take -- in the players' format too (the belief check)."""
    out = []
    target = S("Corviknight", "Leftovers", "Mirror Armor", ["Brave Bird", "Roost", "Knock Off", "U-turn"])
    tricker = S("Corviknight", "Life Orb", "Mirror Armor", ["Brave Bird", "Roost", "Trick", "U-turn"])
    for name, att, script, tgt in (
        # (the Choice Specs holder is locked after its Surf: the target Tricks its Life Orb onto it)
        ("trick", S("Latios", "Choice Specs", "Levitate", ["Surf", "Draco Meteor", "Psyshock", "Calm Mind"], FAST, "Timid"),
         [{"p1": "move 2", "p2": "move 1"}, {"p1": "move 3", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}], tricker),
        ("knockoff-magician", S("Delphox", "Choice Specs", "Magician", ["Psyshock", "Mystical Fire", "Grass Knot", "Focus Blast"], FAST, "Timid"),
         [{"p1": "move 2", "p2": "move 1"}, {"p1": "move 3", "p2": "move 1"}, {"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}], target),
        ("thief", S("Weavile", "", "Pressure", ["Thief", "Knock Off", "Ice Shard", "Triple Axel"], FAST, "Jolly"),
         [{"p1": "move 2", "p2": "move 1"}, {"p1": "move 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2"}], target),
    ):  # fmt: skip
        for fmt in ("", PCT):
            out.append(_spec(f"items/{name}{'-pct' if fmt else ''}", team(tgt, FILLER), team(att, FILLER), script,
                             fmt=fmt))  # fmt: skip
    return out


def encore() -> list[Spec]:
    """An Encore in the turn changes the target's move (R1's tree check: the move used)."""
    tgt = S("Ceruledge", "Leftovers", "Flash Fire", ["Bitter Blade", "Poltergeist", "Swords Dance", "Shadow Sneak"])
    enc = S("Iron Valiant", "Leftovers", "Quark Drive", ["Encore", "Moonblast", "Close Combat", "Knock Off"], FAST, "Timid")
    return [_spec("encore/mid-turn", team(tgt, FILLER), team(enc, FILLER),
                  [{"p1": "move 3", "p2": "move 2"}, {"p1": "move 2", "p2": "move 1"}, {"p1": "move 3", "p2": "move 2"}])]


def formes() -> list[Spec]:
    """A forme change's weight is its new forme's (R3: Showdown's formeChange sets the species):
    Minior's Meteor shell broken below half its HP (40 kg -> 0.3), Palafin's Hero forme after its
    switch out and back (60.2 -> 97.4); the foe's weight move reads it."""
    minior = S("Minior", "Leftovers", "Shields Down", ["Shell Smash", "Acrobatics", "Earthquake", "Power Gem"])
    hitter = S("Kingambit", "Leftovers", "Supreme Overlord", ["Iron Head", "Low Kick", "Sucker Punch", "Swords Dance"],
               "252 Atk / 4 Def / 252 Spe", "Adamant")  # fmt: skip
    palafin = S("Palafin", "Leftovers", "Zero to Hero", ["Jet Punch", "Wave Crash", "Bulk Up", "Flip Turn"])
    heavy = S("Copperajah", "Leftovers", "Sheer Force", ["Heavy Slam", "Low Kick", "Protect", "Iron Defense"])
    return [
        _spec("forme/minior-shell", team(minior, FILLER), team(hitter, FILLER),
              [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 1", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2"},
               {"p1": "move 2", "p2": "move 2"}],
              expect=("|-formechange|p1a: Minior|Minior",)),
        _spec("forme/palafin-hero", team(palafin, FILLER), team(heavy, FILLER),
              [{"p1": "switch 2", "p2": "move 4"}, {"p1": "switch 2", "p2": "move 4"}, {"p1": "move 1", "p2": "move 1"},
               {"p1": "move 3", "p2": "move 2"}],
              expect=("Palafin-Hero",)),
    ]


def speed_phases() -> list[Spec]:
    """The move order read with the item held then (the speed observations' item phases): a
    Choice Scarf Glalie moves first, a Knock Off takes the scarf, it moves second after -- read
    with its item now (none), the first turn's order rules its true speed out (the players'
    format: the belief check)."""
    glalie = S("Glalie", "Choice Scarf", "Inner Focus", ["Spikes", "Freeze-Dry", "Disable", "Taunt"],
               "252 HP / 252 Def / 4 SpD", "Bold")  # fmt: skip
    fish = S("Basculegion", "Leftovers", "Adaptability", ["Knock Off", "Wave Crash", "Aqua Jet", "Phantom Force"],
             FAST, "Jolly")  # fmt: skip
    return [_spec("speed/scarf-knocked-off", team(fish, FILLER), team(glalie, FILLER),
                  [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2"}],
                  fmt=PCT, expect=("|-enditem|p2a: Glalie|Choice Scarf|[from] move: Knock Off",))]  # fmt: skip


FAMILIES = (extender_items, pp_takers, transforms, locks, failed_moves, item_phases, encore, formes, speed_phases)


def scenarios() -> list[Spec]:
    return [s for f in FAMILIES for s in f()]
