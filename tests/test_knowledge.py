"""The metagame knowledge's archetypes and checks (teams.archetypes, teams.knowledge_checks,
teams.validate.banned_species; scripts/knowledge.py)."""

import shutil

import pytest

from alpha_poke.teams import archetypes as A
from alpha_poke.teams.validate import SIM

needs_showdown = pytest.mark.skipif(
    shutil.which("node") is None or not SIM.exists(), reason="needs node and the Showdown checkout"
)

RAIN = """Pelipper @ Damp Rock
Ability: Drizzle
EVs: 248 HP / 252 Def / 8 SpD
Bold Nature
- Hurricane
- U-turn
- Roost
- Knock Off

Barraskewda @ Choice Band
Ability: Swift Swim
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Liquidation
- Close Combat
- Aqua Jet
- Psychic Fangs"""


def test_title_labels():
    """The forum titles' words for archetypes (hazard control is not a stack)."""
    assert A.title_labels("Hastack Balance") == {"hazard stack", "balance"}
    assert A.title_labels("Rain HO") == {"rain", "hyper offense"}
    assert A.title_labels("Hazard Control BO") == {"bulky offense"}
    assert A.title_labels("my cool team") == set()


def test_features_by_rules():
    t = A.tags(A.from_export(RAIN))
    assert "rain" in t["features"] and "volt-turn" not in t["features"]  # (one pivot)
    webs = [A.mon("ribombee", ["stickyweb", "moonblast"]), A.mon("greattusk", ["headlongrush"])]
    assert "webs" in A.tags(webs)["features"]


def _team(style: str, i: int) -> list[dict]:
    """Made-up teams: stall-like walls with recovery, or attackers with offensive items."""
    if style == "stall":
        return [A.mon(s, ["recover", "toxic", "haze"][: 1 + i % 3], "leftovers")
                for s in ("blissey", "toxapex", "dondozo", "clodsire", "gliscor", "corviknight")]  # fmt: skip
    return [A.mon(s, ["swordsdance", "closecombat"][: 1 + i % 2], "lifeorb")
            for s in ("ironvaliant", "dragapult", "kingambit", "zamazenta", "glimmora", "ceruledge")]  # fmt: skip


def test_style_classifier_is_scikit_learns():
    """fit_style keeps scikit-learn's fit as plain numbers: style_probs is its predict_proba."""
    pytest.importorskip("sklearn")
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    teams = [_team(s, i) for s in ("stall", "hyper offense") for i in range(6)]
    labels = ["stall"] * 6 + ["hyper offense"] * 6
    model = A.fit_style(teams, labels)
    assert model["loo"] == 1.0 and model["n"] == 12
    ref = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000))
    ref.fit([A.features(t) for t in teams], labels)
    for t in teams[:2] + teams[-2:]:
        mine = A.style_probs(t, model)
        theirs = dict(zip(ref.classes_, ref.predict_proba([A.features(t)])[0], strict=True))
        assert all(abs(mine[k] - theirs[k]) < 1e-3 for k in mine)
    assert A.tags(teams[0], model)["style"] == "stall"
    assert A.tags(teams[-1], model)["style"] == "hyper offense"


def test_archetype_notes_in_both_languages():
    t = {"style": "stall", "features": ["rain"]}
    assert set(A.notes(t, "zh")) == {"受队", "雨天队"} and set(A.notes(t, "en")) == {
        "Stall",
        "Rain",
    }


@needs_showdown
def test_banned_species_by_showdowns_rules():
    from alpha_poke.teams.validate import banned_species

    b = banned_species(["Kyogre", "Great Tusk", "Zamazenta-*", "Urshifu-*", "Nope"])
    assert set(b) == {"Kyogre", "Urshifu-*", "Nope"} and b["Kyogre"].startswith("banned")


@needs_showdown
def test_legality_check_fails_a_banned_species():
    """A snapshot naming a banned species in its metagame (or not listing one its model keeps)
    fails; a clean one passes."""
    from alpha_poke.teams import knowledge_checks as K

    snap = {"model": {"species": ["Great Tusk", "Kyogre", "other"]}, "banned": {},
            "metagame": [["Great Tusk|Kyogre", 1.0]], "threats": {}}  # fmt: skip
    res = {c["name"]: c["status"] for c in K.legality(snap)}
    assert (
        res["legality: metagame"] == "fail" and res["legality: the model's banned list"] == "fail"
    )
    snap |= {"metagame": [["Great Tusk", 1.0]], "banned": {"Kyogre": "banned (Uber)"}}
    res = {c["name"]: c["status"] for c in K.legality(snap)}
    assert (
        res["legality: metagame"] == "pass" and res["legality: the model's banned list"] == "pass"
    )


def test_damage_check_model_against_engine():
    """The threat check's damage model and poke-engine agree on a plain hit (Great Tusk's
    Headlong Rush on Corviknight-free Gholdengo), within the check's tolerance."""
    from alpha_poke.agents.damage import AVG_ROLL, damage_fraction
    from alpha_poke.teams import knowledge_checks as K
    from alpha_poke.teams.threats import own_views

    tusk = "Great Tusk @ Leftovers\nAbility: Protosynthesis\nEVs: 252 Atk / 4 Def / 252 Spe\nJolly Nature\n- Headlong Rush"
    ghold = "Gholdengo @ Leftovers\nAbility: Good as Gold\nEVs: 252 HP / 4 Def / 252 SpD\nCalm Nature\n- Shadow Ball"
    (va, ma), (vd, md) = own_views(tusk)[0], own_views(ghold)[0]
    ours = damage_fraction(va, vd, ma[0])
    eng = AVG_ROLL * K.engine_damage(K.engine_mon(va, ma), K.engine_mon(vd, md), "headlongrush")
    assert ours > 0.3 and abs(ours - eng) <= max(0.05, 0.1 * eng)


def test_structure_and_diff_checks():
    from alpha_poke.teams import knowledge_checks as K

    a = {"built": "a", "metagame": [["X|Y", 1.0]]}
    b = {"built": "b", "metagame": [["Z|W", 1.0]]}
    assert K.diff(b, a)[0]["status"] == "warn"  # (everything moved: a broken source looks so)
    assert K.diff(a, a)[0]["status"] == "pass"
    assert {c["status"] for c in K.structure({})} == {"fail"}


def test_team_archetype_facts():
    """coach.meta.archetype: the team's style by the snapshot's classifier, its features, the
    metagame's numbers for them and the team's chance by the style it meets."""
    import numpy as np

    from alpha_poke.coach import meta

    n = len(A.FEATURE_NAMES)
    model = {"mean": [0.0] * n, "scale": [1.0] * n, "coef": [[0.0] * n] * 4,
             "intercept": [0.0, 2.0, 0.0, 0.0], "classes": list(A.STYLES)}  # fmt: skip
    stats = {"balance": {"share": 0.5, "games": 100, "margin": 0.01, "members": [["X", 1.0, 1.0]],
                         "answers": [["Y", 0.1, 0.02, 50]]}}  # fmt: skip
    snap = {"_w": np.array([0.75, 0.25]),
            "archetypes": {"model": model, "stats": stats, "metagame": [["balance"], ["stall", "rain"]],
                           "vs": {"balance": {"stall": [10, 0.02]}}}}  # fmt: skip
    a = meta.archetype(snap, [], (RAIN, True), p=np.array([0.6, 0.3]))
    assert a["style"] == "balance" and "rain" in a["features"] and a["from"] == "sets"
    assert a["metagame"]["balance"]["answers"][0]["species"] == "Y"
    assert a["your_score_by_opponent_style"] == {
        "balance": {"share": 0.75, "expected": 0.6},
        "stall": {"share": 0.25, "expected": 0.3},
    }
    assert a["style_vs_style"] == {"stall": {"games": 10, "margin_over_ratings": 0.02}}
    assert meta.archetype({}, [], None) is None
