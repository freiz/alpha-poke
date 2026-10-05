from types import SimpleNamespace as NS

import pytest
from poke_env.battle import SideCondition
from poke_env.battle.move import Move

from alpha_poke.agents.plan_exec import (
    Condition,
    ExecPlan,
    Names,
    PlanError,
    PlanState,
    eval_condition,
    plan_terms,
)


def mon(species, hp=1.0, fainted=False, item=None, moves=(), boosts=None, tera=False):
    return NS(
        species=species,
        current_hp_fraction=hp,
        fainted=fainted,
        item=item,
        moves={m: None for m in moves},
        boosts=boosts or {"atk": 0},
        is_terastallized=tera,
        status=None,
    )


def battle(ours, theirs, me, opp, turn=1, my_side=None, opp_side=None):
    return NS(
        team={m.species: m for m in ours},
        opponent_team={m.species: m for m in theirs},
        teampreview_opponent_team=list(theirs),
        active_pokemon=me,
        opponent_active_pokemon=opp,
        turn=turn,
        side_conditions=my_side or {},
        opponent_side_conditions=opp_side or {},
        available_moves=[1],
    )


NAMES = Names(
    {"Great Tusk": "greattusk", "Kingambit": "kingambit", "Corviknight": "corviknight"},
    {"Toxapex": "toxapex", "Dragapult": "dragapult"},
)


def test_condition_parsing_and_errors():
    c = Condition.parse("fainted:Toxapex AND our_hazard_set:stealthrock OR turn_after:30")
    assert len(c.clauses) == 2 and c.clauses[0][1].kind == "our_hazard_set"
    with pytest.raises(PlanError):
        Condition.parse("weather:rain")
    with pytest.raises(PlanError):
        Condition.parse("their_hp_below:Toxapex")  # missing threshold


def test_condition_evaluation():
    tusk, gambit = mon("greattusk"), mon("kingambit")
    pex, pult = mon("toxapex", hp=0.3), mon("dragapult", fainted=True)
    b = battle(
        [tusk, gambit], [pex, pult], tusk, pex, turn=12, opp_side={SideCondition.STEALTH_ROCK: 1}
    )
    assert eval_condition(Condition.parse("fainted:Dragapult"), b, NAMES)
    assert eval_condition(
        Condition.parse("their_hp_below:Toxapex:0.5 AND active:Toxapex"), b, NAMES
    )
    assert eval_condition(Condition.parse("our_hazard_set:stealthrock"), b, NAMES)
    assert not eval_condition(Condition.parse("turn_after:20"), b, NAMES)
    assert eval_condition(Condition.parse("turn_after:20 OR our_active:Great Tusk"), b, NAMES)


def test_from_dict_drops_unexecutable_parts():
    d = {
        "roles": {"Great Tusk": "hazard_setter", "Kingambit": "win_condition", "Pikachu": "lead"},
        "assignments": {
            "Dragapult": {"primary": "Kingambit", "backup": "Corviknight", "avoid": ["Great Tusk"]}
        },
        "kill_priority": ["Toxapex", "Mewtwo"],
        "phases": [
            {
                "name": "early",
                "until": "our_hazard_set:stealthrock",
                "goals": ["set_hazard:stealthrock", "fly:away"],
            },
            {"name": "endgame", "goals": ["setup:Kingambit", "sweep:Kingambit"]},
        ],
        "tera": {
            "who": "Kingambit",
            "when": "secures_ko OR saves_from_ko",
            "never_before": "endgame",
        },
        "rules": [
            {"if": "active:Dragapult", "then": "switch_to:Kingambit"},
            {"if": "weather:rain", "then": "tera_now"},
        ],
    }
    p = ExecPlan.from_dict(d, NAMES)
    assert p.roles == {"greattusk": "hazard_setter", "kingambit": "win_condition"}
    assert p.assignments["dragapult"]["primary"] == "kingambit"
    assert p.kill_priority == ["toxapex"]
    assert [g[0] for g in p.phases[0].goals] == ["set_hazard"]
    assert len(p.rules) == 1 and p.tera_who == "kingambit"
    assert len(p.problems) == 3  # Pikachu role, fly:away goal, weather condition


def test_state_machine_and_terms():
    tusk, gambit, corv = mon("greattusk"), mon("kingambit"), mon("corviknight")
    pex, pult = mon("toxapex"), mon("dragapult")
    d = {
        "roles": {"Kingambit": "win_condition"},
        "assignments": {"Dragapult": {"primary": "Corviknight", "backup": "Kingambit"}},
        "phases": [
            {"name": "early", "goals": ["set_hazard:stealthrock"]},
            {"name": "endgame", "goals": ["sweep:Kingambit"]},
        ],
        "rules": [{"if": "active:Dragapult", "then": "switch_to:Corviknight"}],
    }
    st = PlanState(ExecPlan.from_dict(d, NAMES))
    b = battle([tusk, gambit, corv], [pex, pult], tusk, pult)
    rocks = Move("stealthrock", gen=9)
    t = plan_terms(st, b, (rocks, False), {"damage": 0, "opp_hp": 1})
    assert t.get("goal_hazard", 0) > 0
    t = plan_terms(st, b, corv, {"forced": False})
    assert t["assign_primary"] > 0 and t["rule"] > 0
    t = plan_terms(st, b, gambit, {"forced": False})
    assert t.get("wincon_hidden", 0) < 0  # win condition kept back before the endgame
    # rocks go up -> early phase done -> endgame
    b.opponent_side_conditions = {SideCondition.STEALTH_ROCK: 1}
    st.update(b)
    assert st.phase_name == "endgame" and st.in_endgame()
    # Corviknight faints -> backup promoted
    corv.fainted = True
    st.update(b)
    assert st.plan.assignments["dragapult"]["primary"] == "kingambit"
