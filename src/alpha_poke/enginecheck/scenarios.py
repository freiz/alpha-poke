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
    # (a terrain: Terrain Extender, into a Ground foe -- an Electric status move ignores its
    # immunity, Eerie Impulse lowers it; L234, L235)
    for ability in ("Klutz", "No Guard"):
        setter = S("Golurk", "Terrain Extender", ability, ["Electric Terrain", "Eerie Impulse", "Earthquake", "Rock Polish"],
                   FAST, "Jolly")  # fmt: skip
        foe = S("Ting-Lu", "Leftovers", "Vessel of Ruin", ["Spikes", "Ruination", "Earthquake", "Whirlwind"])
        script = [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 2"}] + [{"p1": "move 4", "p2": "move 2"}] * 2
        out.append(_spec(f"extender/terrain-{ability.lower().replace(' ', '')}-ground", team(setter, FILLER),
                         team(foe, FILLER), script, expect=("|-fieldstart|move: Electric Terrain", "|-unboost|p2a: Ting-Lu|spa|2")))  # fmt: skip
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


def second_sleep() -> list[Spec]:
    """A second foe put to sleep (L238: the players' format, Showdown's [Gen 9] OU, has no Sleep
    Clause Mod -- a Dire Claw's / Effect Spore's second sleep goes through; the engine's default)."""
    breloom = S("Breloom", "Leftovers", "Technician", ["Spore", "Mach Punch", "Bullet Seed", "Rock Tomb"], FAST, "Jolly")
    corv = S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"])
    blissey = S("Blissey", "Heavy-Duty Boots", "Serene Grace", ["Soft-Boiled", "Seismic Toss", "Calm Mind", "Protect"])
    script = [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 3", "p2": "switch 2"}, {"p1": "move 1", "p2": "move 3"},
              {"p1": "move 3", "p2": "move 3"}]
    return [_spec("sleep/second-sleep", team(breloom, FILLER), team(corv, blissey), script,
                  expect=("|-status|p2a: Corviknight|slp", "|-status|p2a: Blissey|slp"))]  # fmt: skip


def type_changes() -> list[Spec]:
    """Double Shock's type change: "???" in Showdown (poke-env's THREE_QUESTION_MARKS: the engine's
    typeless); after a Terastallization it does nothing, though Showdown prints a typechange of the
    tera type -- the original types kept, Close Combat's STAB on them (2026-10-24, the belief
    check's damage evidence; the state check's types)."""
    out = []
    for tera in (False, True):
        pawmot = S("Pawmot", "Leftovers", "Iron Fist", ["Double Shock", "Close Combat", "Protect", "Revival Blessing"],
                   FAST, "Jolly", tera="Electric")  # fmt: skip
        first = {"p1": "move 1 terastallize" if tera else "move 1", "p2": "move 1"}
        script = [first, {"p1": "move 2", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}]
        out.append(_spec(f"types/doubleshock-{'tera' if tera else 'plain'}", team(pawmot, FILLER),
                         team(S("Blissey", "Leftovers", "Natural Cure", ["Soft-Boiled", "Seismic Toss", "Calm Mind", "Protect"]),
                              FILLER), script, expect=("typechange",)))  # fmt: skip
    return out


def belief_evidence() -> list[Spec]:
    """The belief's evidence read as it was at its turn (2026-10-24, the belief check: the true
    speed / set ruled out -- B2, B3): a Pain Split's -sethp before a Knock Off; a Stakeout on a
    switch-in; a Zoroark's Illusion broken; an Imposter Ditto's hits; a Minior's Meteor shell
    broken (the speed in each forme); a Healing Wish's cure of a paralysis; our Choice Scarf
    Tricked away (our speed with it before). The players' format."""
    out = []
    cat = S("Meowscarada", "Choice Scarf", "Overgrow", ["Knock Off", "Trick", "U-turn", "Flower Trick"], FAST, "Jolly")
    # (Shell Armor: no crit voids the hit after the Pain Split)
    rotom = S("Rotom-Wash", "Leftovers", "Shell Armor", ["Pain Split", "Hydro Pump", "Volt Switch", "Will-O-Wisp"])
    out.append(_spec("belief/painsplit-knockoff", team(cat, FILLER), team(rotom, FILLER),
                     [{"p1": "move 1", "p2": "move 2"}, {"p1": "move 1", "p2": "move 1"}, {"p1": "move 1", "p2": "move 2"}],
                     fmt=PCT, expect=("|-sethp|p2a: Rotom",)))  # fmt: skip
    spid = S("Spidops", "Leftovers", "Stakeout", ["Knock Off", "Circle Throw", "Sticky Web", "U-turn"])
    corv = S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"])
    out.append(_spec("belief/stakeout-switch-in", team(spid, FILLER), team(FILLER, corv),
                     [{"p1": "move 1", "p2": "switch 2"}, {"p1": "move 1", "p2": "move 1"}],
                     fmt=PCT, expect=("|switch|p2a: Corviknight",)))  # fmt: skip
    zor = S("Zoroark-Hisui", "Choice Specs", "Illusion", ["Shadow Ball", "Hyper Voice", "Flamethrower", "U-turn"], FAST, "Timid")
    out.append(_spec("belief/illusion-broken", team(spid, FILLER), team(zor, FILLER),
                     [{"p1": "move 1", "p2": "move 3"}, {"p1": "move 1", "p2": "move 3"}, {"p1": "move 1", "p2": "move 3"}],
                     fmt=PCT, expect=("|replace|p2a: Zoroark",)))  # fmt: skip
    ditto = S("Ditto", "Choice Scarf", "Imposter", ["Transform"])
    # (our Corviknight 256: the Ditto's own speed with its scarf 198, its copy's 384 -- it moves first)
    fast_corv = S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"], FAST, "Jolly")
    out.append(_spec("belief/imposter-hits", team(fast_corv, FILLER), team(ditto, FILLER),
                     [{"p1": "move 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2"}],
                     fmt=PCT, expect=("|-transform|p2a: Ditto",)))  # fmt: skip
    # (the Meteor 156 moves after our Garchomp's 240; its Core 276 before -- each turn in its forme)
    minior = S("Minior", "Leftovers", "Shields Down", ["Power Gem", "Acrobatics", "Stealth Rock", "Earthquake"])
    chomp = S("Garchomp", "Leftovers", "Rough Skin", ["Iron Head", "Earthquake", "Stealth Rock", "Swords Dance"])
    out.append(_spec("belief/minior-shell", team(chomp, FILLER), team(minior, FILLER),
                     [{"p1": "move 1", "p2": "move 1"}] * 5, fmt=PCT, expect=("|-formechange|p2a: Minior",)))  # fmt: skip
    zap = S("Raichu", "Leftovers", "Lightning Rod", ["Thunder Wave", "Thunderbolt", "Nasty Plot", "Volt Switch"], FAST, "Timid")
    suicune = S("Suicune", "Leftovers", "Pressure", ["Scald", "Calm Mind", "Rest", "Protect"])
    gard = S("Gardevoir", "Leftovers", "Synchronize", ["Healing Wish", "Moonblast", "Calm Mind", "Protect"])
    # (cured, the Suicune's 206 moves before our Corviknight's 170 -- read paralyzed, 103, it could not)
    out.append(_spec("belief/healingwish-cure", team(zap, corv), team(suicune, gard),
                     [{"p1": "move 1", "p2": "move 2"}, {"p1": "move 3", "p2": "switch 2"}, {"p1": "move 3", "p2": "move 1"},
                      {"p1": "move 3", "p2": "switch 2"}, {"p1": "switch 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 2"},
                      {"p1": "move 2", "p2": "move 2"}],
                     fmt=PCT, max_turns=10, expect=("[from] move: Healing Wish",)))  # fmt: skip
    goth = S("Gothitelle", "Choice Scarf", "Frisk", ["Psychic", "Trick", "Thunderbolt", "Calm Mind"])
    bolt = S("Zekrom", "Life Orb", "Teravolt", ["Bolt Strike", "Outrage", "Dragon Claw", "Roost"])
    out.append(_spec("belief/our-scarf-tricked", team(goth, FILLER), team(bolt, FILLER),
                     [{"p1": "move 2", "p2": "move 4"}, {"p1": "move 1", "p2": "move 4"}, {"p1": "move 1", "p2": "move 4"}],
                     fmt=PCT, expect=("|-item|p2a: Zekrom|Choice Scarf|[from] move: Trick",)))  # fmt: skip
    # (an Encore on the faster's -6 Dragon Tail: its Energy Ball after the slower's Encore)
    mega = S("Meganium", "Leftovers", "Overgrow", ["Energy Ball", "Dragon Tail", "Synthesis", "Leech Seed"], FAST, "Jolly")
    chan = S("Hitmonchan", "Leftovers", "Iron Fist", ["Encore", "Drain Punch", "Ice Punch", "Rapid Spin"])
    out.append(_spec("belief/encore-a-dragon-tail", team(mega, FILLER), team(chan, FILLER),
                     [{"p1": "move 1", "p2": "move 2"}, {"p1": "move 2", "p2": "move 1"}, {"p1": "move 1", "p2": "move 2"}],
                     fmt=PCT, expect=("|-start|p1a: Meganium|Encore",)))  # fmt: skip
    # (Mycelium Might: the faster Toedscruel's Spore after the Dragonite's Earthquake)
    toed = S("Toedscruel", "Leftovers", "Mycelium Might", ["Spore", "Earth Power", "Knock Off", "Rapid Spin"], FAST, "Jolly")
    nite = S("Dragonite", "Leftovers", "Inner Focus", ["Earthquake", "Roost", "Fire Punch", "Ice Spinner"])
    out.append(_spec("belief/mycelium-might", team(toed, FILLER), team(nite, FILLER),
                     [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}],
                     fmt=PCT, expect=("|move|p1a: Toedscruel|Spore",)))  # fmt: skip
    # (a Palafin-Zero's Flip Turn, back in as the Hero: the hit in another forme)
    fin = S("Palafin", "Leftovers", "Zero to Hero", ["Flip Turn", "Jet Punch", "Wave Crash", "Bulk Up"], FAST, "Jolly")
    out.append(_spec("belief/palafin-hero", team(FILLER, FILLER), team(fin, FILLER),
                     [{"p1": "move 3", "p2": "move 1"}, {"p2": "switch 2"}, {"p1": "move 3", "p2": "switch 2"},
                      {"p1": "move 3", "p2": "move 3"}],
                     fmt=PCT, expect=("Palafin-Hero",)))  # fmt: skip
    # (2026-10-25 review: the phases of a value the log changes on the other mon -- a Magician
    # takes the Choice Scarf of a Latios that moved first with it, 256 x 1.5 before the Hoopa's
    # 262: no -enditem of it; a Huge Power Azumarill's hit, then a Skill Swap gives it Synchronize
    # and it hits again; a contact with Lingering Aroma / Mummy changes the hitter's ability)
    latios = S("Latios", "Choice Scarf", "Levitate", ["Psyshock", "Draco Meteor", "Recover", "Calm Mind"])
    hoopa = S("Hoopa", "", "Magician", ["Shadow Ball", "Psychic", "Nasty Plot", "Protect"], FAST, "Timid")
    out.append(_spec("belief/magician-scarf", team(hoopa, FILLER), team(latios, FILLER),
                     [{"p1": "move 1", "p2": "move 1"}] * 3,
                     fmt=PCT, expect=("|-item|p1a: Hoopa|Choice Scarf|[from] ability: Magician",)))  # fmt: skip
    # (the Azumarill's 218 before the Gardevoir's 196: its hits the turns' first moves)
    azu = S("Azumarill", "Leftovers", "Huge Power", ["Liquidation", "Aqua Jet", "Belly Drum", "Knock Off"], FAST, "Jolly")
    gard = S("Gardevoir", "Leftovers", "Synchronize", ["Skill Swap", "Calm Mind", "Moonblast", "Protect"])
    out.append(_spec("belief/skillswap-after-hit", team(gard, FILLER), team(azu, FILLER),
                     [{"p1": "move 1", "p2": "move 1"}] + [{"p1": "move 2", "p2": "move 1"}] * 2,
                     fmt=PCT, expect=("Skill Swap|Huge Power|Synchronize",)))  # fmt: skip
    for holder, ability in (("Oinkologne", "Lingering Aroma"), ("Cofagrigus", "Mummy")):
        mon = S(holder, "Leftovers", ability, ["Calm Mind", "Body Slam", "Yawn", "Protect"])
        out.append(_spec(f"belief/{ability.lower().replace(' ', '')}-contact", team(mon, FILLER), team(azu, FILLER),
                         [{"p1": "move 1", "p2": "move 1"}] * 3,
                         fmt=PCT, expect=(f"|ability: {ability}|p2a: Azumarill|[ability] Huge Power",)))  # fmt: skip
    # (the speed's abilities then: a Regigigas Skill Swaps its Slow Start away -- its 118 before,
    # 236 after; a Garchomp's 216 first on turn 1 (read with our ability now, not halved: ruled
    # out), its Jolly 333 halved second after (read with its species' abilities: ruled out))
    gigas = S("Regigigas", "Leftovers", "Slow Start", ["Skill Swap", "Bulk Up", "Body Slam", "Protect"])
    for name, evs, nature in (("slow", "252 HP / 4 Atk / 252 SpD", "Brave"), ("fast", FAST, "Jolly")):
        chomp = S("Garchomp", "Leftovers", "Rough Skin", ["Swords Dance", "Stealth Rock", "Earthquake", "Dragon Claw"],
                  evs, nature)  # fmt: skip
        out.append(_spec(f"belief/slowstart-swapped-{name}", team(gigas, FILLER), team(chomp, FILLER),
                         [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 2", "p2": "move 1"}, {"p1": "move 2", "p2": "move 2"}],
                         fmt=PCT, expect=("Skill Swap|Rough Skin|Slow Start",)))  # fmt: skip
    return out


def ability_changes() -> list[Spec]:
    """A contact with a Mummy / Lingering Aroma holder: the hitter's ability its, till it switches
    (Showdown prints -activate holder "ability: X" hitter "[ability] OLD"; 2026-10-25 review: the
    state kept the Huge Power); a Role Play's [of] keeps its own -- a Regenerator still heals as
    it switches out."""
    out = []
    azu = S("Azumarill", "Leftovers", "Huge Power", ["Liquidation", "Aqua Jet", "Belly Drum", "Knock Off"], FAST, "Jolly")
    for holder, ability in (("Oinkologne", "Lingering Aroma"), ("Cofagrigus", "Mummy")):
        mon = S(holder, "Leftovers", ability, ["Calm Mind", "Body Slam", "Yawn", "Protect"])
        out.append(_spec(f"abilities/{ability.lower().replace(' ', '')}-contact", team(mon, FILLER), team(azu, FILLER),
                         [{"p1": "move 1", "p2": "move 1"}] * 3,
                         expect=(f"|ability: {ability}|p2a: Azumarill|[ability] Huge Power",)))  # fmt: skip
    # (B8: Worry Seed over an ability the foe has not shown -- the log names the old one, its own
    # back after a switch-out; the state_facts check's: the oracle gives the true set)
    whim = S("Whimsicott", "Leftovers", "Prankster", ["Worry Seed", "Moonblast", "Protect", "Encore"])
    out.append(_spec("abilities/worryseed-unknown", team(whim, FILLER), team(azu, FILLER),
                     [{"p1": "move 1", "p2": "move 3"}, {"p1": "move 2", "p2": "switch 2"},
                      {"p1": "move 2", "p2": "switch 2"}, {"p1": "move 2", "p2": "move 3"}],
                     expect=("|-ability|p2a: Azumarill|Insomnia|Huge Power|[from] move: Worry Seed",)))  # fmt: skip
    rai = S("Raichu", "Leftovers", "Lightning Rod", ["Role Play", "Thunderbolt", "Nasty Plot", "Surf"], FAST, "Timid")
    slow = S("Slowking-Galar", "Leftovers", "Regenerator", ["Sludge Bomb", "Psyshock", "Calm Mind", "Thunder Wave"])
    out.append(_spec("abilities/roleplay-regenerator", team(rai, FILLER), team(slow, FILLER),
                     [{"p1": "move 1", "p2": "move 3"}, {"p1": "move 2", "p2": "move 3"},
                      {"p1": "move 2", "p2": "switch 2"}, {"p1": "move 2", "p2": "move 1"}],
                     expect=("[from] move: Role Play",)))  # fmt: skip
    return out


def engine_ends() -> list[Spec]:
    """L239 - L241 (doc/engine-diff.md), the engine's: an ability's End as it changes (Worry Seed,
    Skill Swap -- Slow Start's, Flash Fire's, Unburden's volatile off); a move with no target the
    battle's last move (a Copycat on the bench: the engine keeps it only then); an Uproar's locked
    turns spend no PP."""
    gigas = S("Regigigas", "Leftovers", "Slow Start", ["Skill Swap", "Bulk Up", "Body Slam", "Protect"])
    gard = S("Gardevoir", "Leftovers", "Synchronize", ["Skill Swap", "Worry Seed", "Flamethrower", "Knock Off"])
    heatran = S("Heatran", "Leftovers", "Flash Fire", ["Calm Mind", "Earth Power", "Magma Storm", "Protect"])
    hawlucha = S("Hawlucha", "Leftovers", "Unburden", ["Bulk Up", "Close Combat", "Acrobatics", "Roost"])
    blissey = S("Blissey", "Heavy-Duty Boots", "Natural Cure", ["U-turn", "Soft-Boiled", "Seismic Toss", "Copycat"])
    chomp = S("Garchomp", "Leftovers", "Rough Skin", ["Memento", "Uproar", "Swords Dance", "Earthquake"], FAST, "Jolly")
    return [
        _spec("ends/worryseed-slowstart", team(gigas, FILLER), team(gard, FILLER),
              [{"p1": "move 2", "p2": "move 2"}, {"p1": "move 2", "p2": "move 3"}],
              expect=("|-end|p1a: Regigigas|Slow Start|[silent]",)),
        _spec("ends/skillswap-flashfire", team(heatran, FILLER), team(gard, FILLER),
              [{"p1": "move 1", "p2": "move 3"}, {"p1": "move 1", "p2": "move 1"}, {"p1": "move 1", "p2": "move 3"}],
              expect=("|-start|p1a: Heatran|ability: Flash Fire", "Skill Swap|Flash Fire|Synchronize")),
        _spec("ends/skillswap-unburden", team(hawlucha, FILLER), team(gard, FILLER),
              [{"p1": "move 1", "p2": "move 4"}, {"p1": "move 1", "p2": "move 1"}],
              expect=("|-enditem|p1a: Hawlucha|Leftovers|[from] move: Knock Off", "Skill Swap|Unburden|Synchronize")),
        _spec("ends/notarget-lastmove", team(chomp, blissey), team(blissey, FILLER),
              [{"p1": "move 1", "p2": "move 1"}], expect=("[notarget]",)),
        # (its foe without Copycat: a called lock -- Copycat's Uproar -- is L242's, pending)
        _spec("ends/uproar-pp", team(chomp, FILLER), team(blissey.replace("- Copycat", "- Calm Mind"), FILLER),
              # (locked: the request's one move, "move 1")
              [{"p1": "move 2", "p2": "move 2"}] + [{"p1": "move 1", "p2": "move 2"}] * 2,
              expect=("[from] lockedmove",)),
    ] + rollouts() + called_locks() + lock_edges() + [
        # (S158: the foe's Choice lock -- our state gave it all its moves; state_chain's)
        _spec("ends/foe-choice-lock", team(S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"]), FILLER),
              team(S("Garchomp", "Choice Scarf", "Rough Skin", ["Earthquake", "Dragon Claw", "Stone Edge", "Fire Fang"], FAST, "Jolly"), FILLER),
              [{"p1": "move 3", "p2": "move 2"}] * 3, expect=("|move|p2a: Garchomp|Dragon Claw",)),
        # (S158: a hidden forme -- the team preview's Zacian-* / Urshifu-*, built as the base: its
        # stats, types and moves a Zacian's / a Single Strike's when it came in)
        _spec("ends/hidden-formes", team(S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"]), FILLER),
              team(FILLER, S("Zacian", "Rusted Sword", "Intrepid Sword", ["Behemoth Blade", "Play Rough", "Swords Dance", "Close Combat"], FAST, "Jolly"),
                   S("Urshifu-Rapid-Strike", "Choice Band", "Unseen Fist", ["Surging Strikes", "Close Combat", "Aqua Jet", "U-turn"], FAST, "Jolly")),
              [{"p1": "move 3", "p2": "switch 2"}, {"p1": "move 3", "p2": "move 1"}, {"p1": "move 3", "p2": "switch 3"},
               {"p1": "move 3", "p2": "move 1"}], expect=("|switch|p2a: Zacian|Zacian-Crowned", "|switch|p2a: Urshifu|Urshifu-Rapid-Strike")),
        # (S158: our transformed mon locked -- the request names the lock's move alone: its slot the
        # target's third, not the first)
        _spec("ends/transformed-lock-order", team(S("Ditto", "Choice Scarf", "Imposter", ["Transform"]), FILLER),
              team(S("Dragonite", "Leftovers", "Inner Focus", ["Dragon Dance", "Earthquake", "Outrage", "Roost"]), FILLER),
              [{"p1": "move 3", "p2": "move 1"}, {"p1": "move 1", "p2": "move 1"}],
              expect=("|move|p1a: Ditto|Outrage|p2a: Dragonite|[from] lockedmove",)),
        # (S158: a Healing Wish waiting -- Gen 9's: its replacement at full HP, a full Corviknight
        # after, the hurt Snorlax back healed; our state never had it)
        _spec("ends/healing-wish-waits",
              team(S("Gardevoir", "Leftovers", "Synchronize", ["Healing Wish", "Moonblast", "Calm Mind", "Protect"]), FILLER,
                   S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"])),
              team(S("Garchomp", "Leftovers", "Rough Skin", ["Earthquake", "Dragon Claw", "Stone Edge", "Swords Dance"]), FILLER),
              [{"p1": "move 1", "p2": "move 4"}, {"p1": "switch 2"}, {"p1": "move 4", "p2": "move 1"},
               {"p1": "switch 3", "p2": "move 4"}, {"p1": "switch 3", "p2": "move 4"}],
              expect=("|-heal|p1a: Snorlax|", "[from] move: Healing Wish")),
        # (S158c / L226: the Stealth Rock laid before the Toxic Spikes -- their order on a switch-in;
        # our state never had it)
        _spec("ends/toxic-spikes-order", team(S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"]), FILLER),
              team(S("Glimmora", "Focus Sash", "Toxic Debris", ["Stealth Rock", "Toxic Spikes", "Power Gem", "Mortal Spin"]), FILLER),
              [{"p1": "move 3", "p2": "move 1"}, {"p1": "move 3", "p2": "move 2"}, {"p1": "switch 2", "p2": "move 3"},
               {"p1": "move 4", "p2": "move 3"}], expect=("|-sidestart|p1: ", "move: Toxic Spikes")),
        # (S158d: a Stellar tera's type marked as its damage is computed -- an Earthquake at a
        # Corviknight (immune) not, a Dragon Claw's hit yes, a failed Fake Out not)
        _spec("ends/stellar-on-hit",
              team(S("Garchomp", "Leftovers", "Rough Skin", ["Earthquake", "Fake Out", "Dragon Claw", "Swords Dance"], FAST, "Jolly",
                     tera="Stellar"), FILLER),
              team(S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"]), FILLER),
              [{"p1": "move 1 terastallize", "p2": "move 3"}, {"p1": "move 3", "p2": "move 3"},
               {"p1": "move 2", "p2": "move 3"}], expect=("|-terastallize|p1a: Garchomp|Stellar", "|-fail|p1a: Garchomp")),
        # (S158d: a faint Revival Blessing undid -- Showdown's totalFainted keeps it)
        _spec("ends/revival-blessing",
              team(S("Shedinja", "", "Wonder Guard", ["Swords Dance", "Shadow Sneak", "X-Scissor", "Protect"]),
                   S("Pawmot", "Leftovers", "Volt Absorb", ["Revival Blessing", "Close Combat", "Nuzzle", "Protect"]), FILLER),
              team(S("Heatran", "Leftovers", "Flash Fire", ["Flamethrower", "Earth Power", "Stealth Rock", "Protect"]), FILLER),
              [{"p1": "move 1", "p2": "move 1"}, {"p1": "switch 2"}, {"p1": "move 1", "p2": "move 4"}, {"p1": "switch 2"},
               {"p1": "move 4", "p2": "move 3"}], expect=("[from] move: Revival Blessing",)),
    ]  # fmt: skip


def lock_edges() -> list[Spec]:
    """2026-10-25 review: a Sleep Talk's Rollout (asleep: Showdown's onModifyMove adds no volatile --
    no lock); an Uproar drained to 0 PP by Spite and Pressure while it locks (it goes on: L243)."""
    # (not a Snorlax -- the bench's is one; Sleep Talk calls neither Uproar nor Focus Punch: the
    # Rollout it must; no Belch, its berry rule open in the engine)
    snorlax = S("Lickilicky", "Leftovers", "Oblivious", ["Sleep Talk", "Rollout", "Uproar", "Focus Punch"])
    breloom = S("Breloom", "Leftovers", "Technician", ["Spore", "Mach Punch", "Bullet Seed", "Swords Dance"], FAST, "Jolly")
    uproar = S("Lickilicky", "Leftovers", "Oblivious", ["Uproar", "Body Slam", "Rest", "Curse"])
    corv = S("Corviknight", "Leftovers", "Pressure", ["Spite", "Roost", "Iron Defense", "Defog"], FAST, "Jolly")
    return [
        _spec("ends/sleeptalk-rollout", team(snorlax, FILLER), team(breloom, FILLER),
              [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 1", "p2": "move 4"}],
              expect=("|move|p1a: Lickilicky|Rollout|p2a: Breloom|[from] move: Sleep Talk",)),
        # (locked: the request's one move, "move 1" -- also the Uproar again after its three turns)
        _spec("ends/uproar-zero-pp", team(uproar, FILLER), team(corv, FILLER), [{"p1": "move 1", "p2": "move 1"}] * 6,
              expect=("|move|p1a: Lickilicky|Uproar|p2a: Corviknight|[from] lockedmove",)),
    ]  # fmt: skip


def called_locks() -> list[Spec]:
    """L242: a locking move a Copycat ran -- Outrage, Uproar, Rollout: its user locked into that
    move, its caller's slot runs it (Showdown's request the move alone), no PP."""
    # (physically bulky, Shell Armor -- no crit: the Outrage it copies leaves it in)
    blissey = S("Blissey", "Heavy-Duty Boots", "Shell Armor", ["Soft-Boiled", "Seismic Toss", "Protect", "Copycat"],
                "252 HP / 252 Def / 4 SpD", "Bold")  # fmt: skip
    corv = S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"])
    out = []
    for name in ("Outrage", "Uproar", "Rollout"):
        # (weak, no Rough Skin: the Blissey lives to use the lock -- still the faster)
        weak = S("Garchomp", "Leftovers", "Sand Veil", [name, "Swords Dance", "Earthquake", "Protect"],
                 "252 HP / 4 SpD / 252 Spe", "Timid")  # fmt: skip
        out.append(_spec(f"ends/copycat-{name.lower()}", team(blissey, corv), team(weak, FILLER),
                         [{"p1": "move 4", "p2": "move 1"}, {"p1": "move 1", "p2": "move 1"}],
                         expect=(f"|move|p1a: Blissey|{name}|p2a: Garchomp|[from] lockedmove",)))  # fmt: skip
    return out


def rollouts() -> list[Spec]:
    """L241's Rollout / Ice Ball: locked, 30 x 2 ** its hits -- five (the fifth a knockout, a weak
    user), or ended by a Protect (the lock over, the other moves back)."""
    weak = S("Garchomp", "Leftovers", "Rough Skin", ["Rollout", "Ice Ball", "Swords Dance", "Earthquake"],
             "252 HP / 4 SpD / 252 Spe", "Timid")  # fmt: skip
    blissey = S("Blissey", "Heavy-Duty Boots", "Natural Cure", ["Soft-Boiled", "Protect", "Seismic Toss", "Calm Mind"])
    corv = S("Corviknight", "Leftovers", "Pressure", ["Roost", "Body Press", "Iron Defense", "Defog"])
    out = []
    for k, move in ((1, "rollout"), (2, "iceball")):
        out.append(_spec(f"ends/{move}-five", team(weak, FILLER), team(blissey, corv),
                         # (locked: the request's one move, "move 1")
                         [{"p1": f"move {k}", "p2": "move 1"}] + [{"p1": "move 1", "p2": "move 1"}] * 4,
                         expect=("[from] lockedmove", "|faint|p2a: Blissey")))  # fmt: skip
    out.append(_spec("ends/rollout-protect", team(weak, FILLER), team(blissey, corv),
                     [{"p1": "move 1", "p2": "move 1"}, {"p1": "move 1", "p2": "move 2"}, {"p1": "move 4", "p2": "move 1"}],
                     expect=("|-activate|p2a: Blissey|move: Protect",)))  # fmt: skip
    return out


FAMILIES = (extender_items, pp_takers, transforms, locks, failed_moves, item_phases, encore, formes, speed_phases,
            second_sleep, type_changes, belief_evidence, ability_changes, engine_ends)


def scenarios() -> list[Spec]:
    return [s for f in FAMILIES for s in f()]
