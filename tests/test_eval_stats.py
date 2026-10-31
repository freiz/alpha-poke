"""Paired evaluation statistics (alpha_poke.eval.arena: pentanomial, pair_stats,
paired_difference) on made-up logs."""

from alpha_poke.eval.arena import pair_score_map, pair_stats, paired_difference, pentanomial


def _rows(results: list[tuple[int, bool | None]]) -> list[dict]:
    return [{"pair": k, "a_won": w, "battle": "b", "turns": 10} for k, w in results]


def test_pentanomial_and_pair_stats():
    # pair 0: A wins both; 1: split; 2: B wins both; 3: one tie (None with a battle) and a win
    m = pair_score_map(_rows([(0, True), (0, True), (1, True), (1, False), (2, False), (2, False),
                              (3, None), (3, True), (4, True)]))  # fmt: skip
    assert m == {0: 1.0, 1: 0.5, 2: 0.0, 3: 0.75}  # (pair 4: one game only)
    assert pentanomial(list(m.values())) == [1, 0, 1, 1, 1]
    st = pair_stats(list(m.values()))
    assert st["pairs"] == 4 and st["score"] == 0.5625 and st["decisive"] == 0.5
    assert st["elo"] > 0 and st["elo_ci95"][0] < st["elo"] < st["elo_ci95"][1]


def test_a_paired_difference_is_tighter_when_the_pairs_agree():
    """Two runs whose pair scores move together: the pair-by-pair interval is narrower than the
    two runs' own intervals combined; unrelated runs: about the same."""
    x = {k: (1.0 if k % 3 == 0 else 0.5 if k % 3 == 1 else 0.0) for k in range(60)}
    y = {k: v - 0.05 * (k % 2) for k, v in x.items()}
    d = paired_difference(x, y)
    assert d["pairs"] == 60 and d["diff"] > 0 and d["ci95"] < d["ci95_if_independent"] / 5


LOG = """|player|p1|Aone|
|player|p2|Btwo|
|turn|1
|move|p1a: Great Tusk|Headlong Rush|p2a: Gholdengo
|-supereffective|p2a: Gholdengo
|-crit|p2a: Gholdengo
|-damage|p2a: Gholdengo|10/100
|move|p2a: Gholdengo|Thunder Wave|p1a: Great Tusk
|-status|p1a: Great Tusk|par
|turn|2
|cant|p1a: Great Tusk|par
|move|p2a: Gholdengo|Focus Blast|p1a: Great Tusk|[miss]
|-miss|p2a: Gholdengo|p1a: Great Tusk
|turn|3
|move|p1a: Great Tusk|Stone Edge|p2a: Gholdengo
|-damage|p2a: Gholdengo|0 fnt
"""


def test_the_luck_in_a_log():
    """eval.luck: a crit (1 - 1/24), Thunder Wave's paralysis then one full paralysis (1 - 1/4)
    and one move through it (0 - 1/4), Focus Blast's miss (1 - 0.3), Stone Edge hitting (0 -
    0.2) with its own crit chance (1/8); Thunder Wave (accuracy 90) hitting: 0 - 0.1."""
    from alpha_poke.eval import luck

    r = luck.residuals(LOG)
    p1, p2 = r["p1"], r["p2"]
    assert p1["crit_n"] == 2 and abs(p1["crit"] - (1 - 1 / 24 - 1 / 8)) < 1e-9
    assert p1["para_n"] == 2 and abs(p1["para"] - (0.75 - 0.25)) < 1e-9
    assert p1["miss_n"] == 1 and abs(p1["miss"] - (-0.2)) < 1e-9
    assert p2["miss_n"] == 2 and abs(p2["miss"] - (0.7 - 0.1)) < 1e-9
    assert luck.side_of(LOG, "A") == "p1"
    f = luck.features(LOG, "p1")
    assert f[0] == p1["crit"] - p2["crit"] and f[1] == p2["miss"] - p1["miss"]
