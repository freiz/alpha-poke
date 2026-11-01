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


def test_a_summary_counts_pairs_won_drawn_and_lost():
    """eval.arena.summarize: the pair as the unit -- won, drawn (split 1-1) or lost -- beside the
    win rate it equals, with the pentanomial and Elo."""
    from alpha_poke.eval.arena import summarize

    rows = _rows(
        [(0, True), (0, True), (1, True), (1, False), (2, False), (2, False), (3, True), (3, True)]
    )
    rows = [r | {"fallbacks_a": 0, "fallbacks_b": 0} for r in rows]
    s = summarize(rows)
    assert s["pair_wdl"] == [2, 1, 1] and s["pentanomial"] == [1, 0, 1, 0, 2]
    assert s["paired_mean"] == s["win_rate"] == 0.625 and s["elo"] > 0


def test_a_guess_is_played_mixed():
    """selfplay.player.greedy_choice: the most visited option, unless others are within the
    value margin -- then drawn by visits among them (a guess played mixed); never one far behind."""
    import random

    from alpha_poke.selfplay.player import greedy_choice

    options, mean = [(0, 600), (1, 300), (2, 100)], [0.42, 0.41, 0.20]
    assert greedy_choice(options, mean, 0.0, random.Random(0)) == 0
    picks = [greedy_choice(options, mean, 0.02, random.Random(s)) for s in range(400)]
    assert 2 not in picks and 0.55 < picks.count(0) / 400 < 0.8
