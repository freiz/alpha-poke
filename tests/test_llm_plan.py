from alpha_poke.agents.llm_plan import canonical_team, plan_key, validate

OURS = [
    {
        "species": "Great Tusk",
        "item": "Rocky Helmet",
        "ability": "Protosynthesis",
        "tera": "Water",
        "moves": ["Rapid Spin", "Stealth Rock", "Headlong Rush", "Ice Spinner"],
    },
    {
        "species": "Gholdengo",
        "item": "Air Balloon",
        "ability": "Good as Gold",
        "tera": "Fairy",
        "moves": ["Shadow Ball", "Make It Rain", "Nasty Plot", "Recover"],
    },
]
INFO = [
    {
        "species": "Toxapex",
        "items": [["Heavy-Duty Boots", 0.9]],
        "tera": [["Steel", 0.6]],
        "moves": ["Toxic", "Recover"],
    }
]


def test_plan_key_ignores_order_and_is_sensitive_to_content():
    k1 = plan_key("m", "low", OURS, ["Toxapex", "Dondozo"], INFO, [])
    shuffled = [dict(OURS[1], moves=list(reversed(OURS[1]["moves"]))), OURS[0]]
    k2 = plan_key("m", "low", shuffled, ["Dondozo", "Toxapex"], INFO, [])
    assert k1 == k2  # same information -> same key (no wasted calls)
    assert k1 != plan_key("other-model", "low", OURS, ["Toxapex", "Dondozo"], INFO, [])
    changed = [dict(OURS[0], item="Leftovers"), OURS[1]]
    assert k1 != plan_key("m", "low", changed, ["Toxapex", "Dondozo"], INFO, [])
    assert canonical_team(OURS)[0]["species"] == "Gholdengo"


def test_validate_drops_wrong_side_references():
    raw = {
        "lead": "Toxapex",
        "win_conditions": ["Gholdengo", "Kingambit"],
        "preserve": ["Gholdengo"],
        "threats": ["Toxapex", "Great Tusk"],
        "answers": {"Toxapex": ["Gholdengo", "Toxapex"], "Pelipper": ["Great Tusk"]},
        "tera_target": "Gholdengo",
        "pace": "fast",
        "hazards_priority": "high",
    }
    out, problems = validate(raw, ["Great Tusk", "Gholdengo"], ["Toxapex", "Dondozo"])
    assert out["lead"] is None and out["win_conditions"] == ["Gholdengo"]
    assert out["threats"] == ["Toxapex"] and out["answers"] == {"Toxapex": ["Gholdengo"]}
    assert out["pace"] == "balanced" and out["hazards_priority"] == "high"
    assert len(problems) >= 5
