from alpha_poke.teams import TeamPool, load_team_files


def test_team_pool_yields_packed_six_mon_teams():
    teams = load_team_files()
    assert teams
    pool = TeamPool(seed=0)
    for _ in range(5):
        assert len(pool.parse_packed_team(pool.yield_team())) == 6
