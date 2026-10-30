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


def test_the_fair_pools_games_and_size(tmp_path):
    """selfplay.fair: the games of every fair pool (self-play leaves them out), not another kind's;
    a pool's pair count; a pool is never rewritten in place."""
    import json

    import pytest

    from alpha_poke.selfplay import fair

    for name, kind, games in (("fair10", "fair", ["g1", "g2"]), ("fair20", "fair", ["g3"]),
                              ("fairish", "offmeta", ["g9"])):  # fmt: skip
        d = tmp_path / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"kind": kind, "games": games}), encoding="utf-8")
        for k in range(len(games)):
            for x in "ab":
                (d / f"pair{k:03d}_{x}.txt").write_text("team", encoding="utf-8")
    assert fair.games(tmp_path) == {"g1", "g2", "g3"}
    assert fair.size(tmp_path / "fair10") == 2
    with pytest.raises(FileExistsError):
        fair.build("fair10", 2, pools=tmp_path)


def test_a_bank_pairs_teams_as_the_ladder_would(tmp_path):
    """selfplay.fair.bank_pairs / bank_pool: every team once, a pair's two teams from the same
    month with ratings within 200, a test's draw its own for its seed (another seed: other
    pairs), a resumed test the same pairs; the bank's games kept from self-play."""
    import json

    from alpha_poke.selfplay import fair

    rng = random.Random(0)
    day = fair.DAY
    teams = [{"game": f"g{i}", "side": "p1", "time": 1_780_000_000 + rng.randrange(90) * day,
              "rating": rng.randrange(1500, 2000), "text": f"team {i}"} for i in range(400)]  # fmt: skip
    pairs = fair.bank_pairs(teams, 150, seed=1)
    assert len(pairs) == 150
    seen = [t["game"] for p in pairs for t in p]
    assert len(seen) == len(set(seen))
    for a, b in pairs:
        assert (
            a["time"] // (31 * day) == b["time"] // (31 * day)
            and abs(a["rating"] - b["rating"]) <= 200
        )
    assert (
        fair.bank_pairs(teams, 150, seed=1) == pairs
        and fair.bank_pairs(teams, 150, seed=2) != pairs
    )
    bank = tmp_path / "teambank"
    bank.mkdir()
    (bank / "teams.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in teams), encoding="utf-8"
    )
    (bank / "meta.json").write_text(
        json.dumps({"kind": "fairbank", "games": ["g1", "g2"]}), encoding="utf-8"
    )
    out = fair.bank_pool(bank, tmp_path / "draw", 20, seed=5)
    assert fair.size(out) == 20
    first = (tmp_path / "draw" / "pair000_a.txt").read_text(encoding="utf-8")
    fair.bank_pool(bank, tmp_path / "draw", 20, seed=6)  # (present: kept)
    assert (tmp_path / "draw" / "pair000_a.txt").read_text(encoding="utf-8") == first
    assert {"g1", "g2"} <= fair.games(tmp_path)
    assert fair.test_half("gen9ou-1") in (True, False) and fair.test_half("x") == fair.test_half(
        "x"
    )
