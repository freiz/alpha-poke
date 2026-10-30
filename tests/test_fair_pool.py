"""The fair evaluation pool's sets (2026-10-30, selfplay.teams.reveal_rates / marginal_set):
a game's revealed parts kept, the rest drawn from usage weighted by 1 - the reveal rate (a part
that would have shown is unlikely when it did not), coherent and legal -- on made-up usage."""

import random
from types import SimpleNamespace

from alpha_poke.agents.engine_state import KnownSet
from alpha_poke.selfplay.teams import marginal_set, reveal_rates

USAGE = SimpleNamespace(
    items={"Leftovers": 0.5, "Heavy-Duty Boots": 0.3, "Choice Specs": 0.2},
    abilities={"Drizzle": 1.0},
    move_has={
        "hurricane": 1.0,
        "uturn": 0.6,
        "roost": 0.5,
        "surf": 0.5,
        "knockoff": 0.4,
        "icebeam": 0.3,
        "weatherball": 0.3,
        "hydropump": 0.2,
        "protect": 0.2,
    },
    tera_types={"Water": 0.7, "Stellar": 0.1, "Ground": 0.2},
)
STATS = SimpleNamespace(species={"Pelipper": USAGE})
LEGAL = {
    "hurricane",
    "uturn",
    "roost",
    "surf",
    "knockoff",
    "icebeam",
    "weatherball",
    "hydropump",
    "protect",
}


def mon(brought=True, item=None, moves=()):
    return SimpleNamespace(species="Pelipper", forms=[], brought=brought, item=item, ability="Drizzle",
                           moves=list(moves))  # fmt: skip


def test_reveal_rates_compare_replays_with_usage():
    """Leftovers held by half the brought mons and always shown: rate 1; Heavy-Duty Boots never
    shown: 0; mons never on the field count for nothing."""
    recs = [mon(item="Leftovers" if i % 2 else None, moves=["hurricane"]) for i in range(100)]
    recs += [mon(brought=False, item="Leftovers") for _ in range(100)]
    r = reveal_rates(recs, STATS)
    assert r["item"]["leftovers"] == 1.0 and r["item"]["heavydutyboots"] == 0.0
    assert r["move"]["hurricane"] == 1.0 and r["move"]["uturn"] == 0.0
    assert 0.0 < r["default"]["item"] < 1.0 and r["ability"]["drizzle"] == 1.0


def test_unrevealed_parts_are_drawn_reveal_corrected():
    rates = {"item": {"leftovers": 1.0, "heavydutyboots": 0.0, "choicespecs": 0.5},
             "move": {"hurricane": 1.0}, "default": {"item": 0.5, "ability": 1.0, "move": 0.5}}  # fmt: skip
    rng = random.Random(0)
    unseen = KnownSet(moves=[])
    on_field = [marginal_set(USAGE, unseen, True, rates, LEGAL, rng) for _ in range(300)]
    benched = [marginal_set(USAGE, unseen, False, rates, LEGAL, rng) for _ in range(300)]
    # (a Leftovers holder on the field would have shown it -- rare, at the floor; one never in:
    # as often as usage says)
    assert sum(s[0] == "leftovers" for s in on_field) < 15
    assert sum(s[0] == "leftovers" for s in benched) > 100
    # (Hurricane always shows when used: seldom drawn for a mon on the field that showed none,
    # always for one never in)
    assert sum("hurricane" in s[3] for s in on_field) < 0.1 * len(on_field)
    assert sum("hurricane" in s[3] for s in benched) > 0.7 * len(benched)
    assert all(s[2] in ("water", "ground") for s in on_field + benched)  # (no Stellar)
    for item, _, _, moves in on_field + benched:
        assert len(moves) == 4 and len(set(moves)) == 4 and set(moves) <= LEGAL
        if item == "choicespecs":
            assert "roost" not in moves  # (no status move beside a Choice item)


def test_revealed_parts_are_kept():
    known = KnownSet(
        moves=["roost", "hurricane"], item="damprock", ability="drizzle", tera="ground"
    )
    rng = random.Random(1)
    for _ in range(50):
        item, ability, tera, moves = marginal_set(USAGE, known, True, {}, LEGAL, rng)
        assert (item, ability, tera) == ("damprock", "drizzle", "ground") and moves[:2] == [
            "roost",
            "hurricane",
        ]
    # a revealed status move: no Choice item drawn
    status = KnownSet(moves=["roost"])
    assert all(
        marginal_set(USAGE, status, False, {}, LEGAL, rng)[0] != "choicespecs" for _ in range(200)
    )
