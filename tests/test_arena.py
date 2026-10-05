from alpha_poke.eval.arena import make_schedule, summarize


def test_schedule_swaps_teams_and_challenger_within_each_pair():
    sched = make_schedule([f"t{i}" for i in range(10)], n_pairs=20, seed=1)
    assert len(sched) == 40
    for g0, g1 in zip(sched[::2], sched[1::2], strict=True):
        assert g0.pair == g1.pair and g0.team_a != g0.team_b
        assert (g0.team_a, g0.team_b) == (g1.team_b, g1.team_a)
        assert g0.a_challenges != g1.a_challenges
    assert make_schedule([f"t{i}" for i in range(10)], 20, seed=1) == sched


def test_summarize_paired_scores_and_ties():
    base = {"fallbacks_a": 0, "fallbacks_b": 0, "team_ok": True, "battle": "b", "turns": 30}
    rows = [
        base | {"pair": 0, "a_won": True},
        base | {"pair": 0, "a_won": False},
        base | {"pair": 1, "a_won": True},
        base | {"pair": 1, "a_won": None, "turns": 1000},  # tie
    ]
    s = summarize(rows)
    assert s["games"] == 4 and s["ties"] == 1 and s["a_wins"] == 2
    assert abs(s["win_rate"] - 2.5 / 4) < 1e-9
    assert abs(s["paired_mean"] - (0.5 + 0.75) / 2) < 1e-9
    assert s["split_pairs"] == 1
