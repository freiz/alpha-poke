from alpha_poke.analysis.cores import mine_cores, team_cores
from alpha_poke.analysis.roles import revealed_roles, species_role_prior
from alpha_poke.data.smogon_stats import SpeciesStats


def test_full_shell_absorbs_its_subsets():
    shell = ("A", "B", "C", "D")
    teams = [shell + (f"x{i}", f"y{i}") for i in range(200)]  # the same 4-shell + random fill
    teams += [("A", "E", f"z{i}", f"w{i}", f"v{i}", f"u{i}") for i in range(200)]
    cores = mine_cores(teams, max_size=4, min_support=50, min_lift=1.5)
    members = [c.members for c in cores]
    assert shell in members
    assert not any(set(m) < set(shell) for m in members)  # 2/3-subsets were absorbed
    assert [c.members for c in team_cores(teams[0], cores)] == [shell]


def test_roles_from_reveals_and_prior():
    assert {"hazard_removal", "item_control"} <= revealed_roles(
        ["Rapid Spin", "Knock Off"], None, None
    )
    assert "booster_paradox" in revealed_roles([], None, "Booster Energy")
    s = SpeciesStats(
        name="X",
        usage=0.1,
        raw_count=1,
        abilities={"Intimidate": 1.0},
        items={"lightclay": 0.2, "leftovers": 0.8},
        moves={},
        move_has={"reflect": 0.2, "lightscreen": 0.2},
        tera_types={},
        spreads={},
        teammates={},
        counters={},
    )
    p = species_role_prior(s)
    assert abs(p["screens"] - 0.2) < 1e-9  # max over correlated indicators, not noisy-OR


def test_team_prior_beats_species_prior_on_copied_team():
    import pandas as pd

    from alpha_poke.belief.priors import SpeciesReplayPrior, TeamPrior

    class Empty:
        def predict(self, species, team):
            from alpha_poke.belief.priors import Dist

            return Dist({}, {}, {})

    team_a, team_b = "A|B|C|D|E|F", "A|G|H|I|J|K"
    rows = []
    for i in range(20):  # on team_a, A always holds Leftovers; elsewhere Choice Scarf
        rows.append(
            dict(
                id=f"a{i}",
                side="p1",
                species="A",
                team=team_a,
                item="Leftovers",
                tera_type=None,
                moves="Earthquake",
            )
        )
        rows.append(
            dict(
                id=f"b{i}",
                side="p1",
                species="A",
                team=team_b,
                item="Choice Scarf",
                tera_type=None,
                moves="U-turn",
            )
        )
    train = pd.DataFrame(rows)
    sp = SpeciesReplayPrior(train, Empty())
    tp = TeamPrior(train, sp)
    team = tuple(team_a.split("|"))
    assert abs(sp.predict("A", team).item["leftovers"] - 0.5) < 0.1
    assert tp.predict("A", team).item["leftovers"] > 0.8
