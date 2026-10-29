"""Self-play's synthetic teams (selfplay.teams.Composer / TeamSampler.synthetic, selfplay.synergy;
2026-10-26): the compositions' teammates and species clause, the sets' cross-mon synergy and its
Metropolis-Hastings steps, the noise's legality."""

import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from alpha_poke.selfplay import synergy
from alpha_poke.selfplay.teams import Composer, TeamSampler

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _Sp:
    name: str
    usage: float
    teammates: dict = field(default_factory=dict)


class _Stats:
    def __init__(self, entries):
        self.species = {e.name: e for e in entries}

    def ranked(self):
        return sorted(self.species.values(), key=lambda e: -e.usage)


NAMES = ["Great Tusk", "Kingambit", "Gholdengo", "Dragapult", "Iron Valiant", "Zamazenta",
         "Landorus-Therian", "Ogerpon", "Ogerpon-Wellspring", "Slowking-Galar"]  # fmt: skip


def _stats(teammates=None):
    tm = teammates or {}
    return _Stats(
        [_Sp(n, 0.1, dict(tm.get(n, {n2: 1.0 for n2 in NAMES if n2 != n}))) for n in NAMES]
    )


def test_composer_keeps_the_species_clause_by_base_species():
    c = Composer(_stats(), min_usage=0.0)
    rng = np.random.default_rng(0)
    for _ in range(300):
        team = c.sample(rng)
        assert len(set(team)) == 6
        assert not {"Ogerpon", "Ogerpon-Wellspring"} <= set(team)


def test_composer_draws_the_teammates_of_those_chosen():
    # (Great Tusk's teammates: Kingambit almost always; the rest's: uniform)
    tm = {
        "Great Tusk": {n: (50.0 if n == "Kingambit" else 1.0) for n in NAMES if n != "Great Tusk"}
    }
    rates = {}
    for gamma in (0.0, 0.7):
        c = Composer(_stats(tm), min_usage=0.0, gamma=gamma)
        rng = np.random.default_rng(1)
        teams = [c.sample(rng) for _ in range(2000)]
        with_tusk = [t for t in teams if "Great Tusk" in t[:3]]
        rates[gamma] = np.mean(["Kingambit" in t[t.index("Great Tusk") :] for t in with_tusk])
    assert rates[0.7] > rates[0.0] + 0.15


def test_synergy_lift_beyond_what_the_species_explain():
    rng = random.Random(0)
    teams = []
    for _ in range(4000):
        # (species A and B always together, A always with "a:x", B always with "a:y": the species
        # explain it -- no lift; C's "m:p" and D's "m:q" together half the time, by design: a lift)
        combo = rng.random() < 0.5
        team = [("a", ["a:x"]), ("b", ["a:y"]),
                ("c", ["m:p"] if combo or rng.random() < 0.3 else ["m:r"]),
                ("d", ["m:q"] if combo or rng.random() < 0.3 else ["m:s"]),
                ("e", ["m:t"]), ("f", ["m:u"])]  # fmt: skip
        teams.append(team)
    syn, info = synergy.build(teams, min_count=10)
    L, i = syn.log_lift, syn.index
    assert abs(L[i["a:x"], i["a:y"]]) < 0.05
    # (P(p) = P(q) = 0.5 + 0.5 x 0.3, P(p, q) = 0.5 + 0.5 x 0.09, P(p, s) = 0.5 x 0.3 x 0.7)
    assert L[i["m:p"], i["m:q"]] == pytest.approx(np.log(0.545 / 0.65**2), abs=0.05)
    assert L[i["m:q"], i["m:p"]] == pytest.approx(np.log(0.545 / 0.65**2), abs=0.05)
    assert L[i["m:p"], i["m:s"]] == pytest.approx(np.log(0.105 / (0.65 * 0.35)), abs=0.08)
    assert info["teams"] == 4000


def test_team_score_sums_both_directions_over_teammates():
    syn = synergy.Synergy(["a:x", "a:y", "m:z"], np.array([[0, 1.0, 0], [0.5, 0, 0], [0, 0, 0]]))
    assert syn.team_score([["a:x"], ["a:y"]]) == pytest.approx(1.5)
    assert syn.team_score([["a:x", "a:y"]]) == 0.0  # (one mon: no teammate pair)
    assert syn.team_score([["a:x"], ["m:z"], ["a:y", "i:unknown"]]) == pytest.approx(1.5)


def test_synthetic_sets_metropolis_hastings_prefer_synergy():
    """With a strong lift between "a:drought" and "a:chlorophyll", the steps keep the teams having
    both more often than the completion alone (each mon's ability drawn 50/50)."""

    def sampler(beta, steps):
        ts = object.__new__(TeamSampler)
        ts.rng, ts.np_rng = random.Random(0), np.random.default_rng(0)
        ts.set_eps = 0.0
        ts.composer = type("C", (), {"sample": lambda self, rng: ["Torkoal", "Venusaur"]})()
        ts.belief = type("B", (), {"display": lambda self, x: x})()
        ts.synergy = synergy.Synergy(["a:drought", "a:chlorophyll"], np.array([[0, 2.0], [2.0, 0]]))
        ts.synth_beta, ts.synth_steps = beta, steps
        abil = {"Torkoal": ("drought", "whitesmoke"), "Venusaur": ("chlorophyll", "overgrow")}

        def draw(sp, known, names, noise):
            return sp, "", ts.rng.choice(abil[sp]), "", ["tackle"]

        ts._draw_set = draw
        ts.spread = lambda sp: "Serious:84/84/84/84/84/84"
        return ts

    def both(ts, n=600):
        return np.mean([("Ability: drought" in t and "Ability: chlorophyll" in t)
                        for t in (ts.synthetic() for _ in range(n))])  # fmt: skip

    base, mh = both(sampler(0.5, 0)), both(sampler(0.5, 12))
    assert 0.18 < base < 0.32
    assert mh > base + 0.3


def test_noisy_sets_stay_within_the_learnset():
    from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats
    from alpha_poke.dex import learnset

    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    ts = object.__new__(TeamSampler)
    ts.stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1500.json")
    ts.rng, ts.banned_moves = random.Random(0), {"terablast"}
    for species in ("greattusk", "kingambit", "gholdengo", "ogerponwellspring"):
        legal = learnset(species)
        for _ in range(50):
            moves, item, ability, tera = ts._noisy(
                species, ["a", "b", "c", "d"], "x", "y", "fire", 1.0
            )
            assert len(set(moves)) == 4 and set(moves) <= legal and "terablast" not in moves
            assert tera != "stellar" and item and ability
