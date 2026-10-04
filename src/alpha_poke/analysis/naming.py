"""LLM naming / explanation of mined archetypes, grounded in our own replay statistics.

The model is never asked to recall the metagame from memory: the prompt contains the core's
members, their mined set archetypes (item / tera / moves) and functional roles, and the model
only summarizes. Outputs are validated against the core (win conditions must be members).
"""

import json

from alpha_poke.analysis.cores import Core
from alpha_poke.analysis.sets import SpeciesSets
from alpha_poke.llm import LLMClient

SYSTEM = (
    "You are an expert competitive Pokemon analyst for Smogon Gen 9 OU singles (6v6, team "
    "preview, terastallization). You will be given statistics mined from thousands of "
    "high-rated ladder replays (October 2026 metagame). Base your analysis ONLY on the data "
    "provided and on general game mechanics; do not invent moves, items or Pokemon that are "
    "not in the data. Answer in JSON only."
)

SCHEMA = {
    "name_en": "short archetype name, e.g. 'Sun Offense' or 'Hazard Stack Stall'",
    "name_zh": "Chinese name",
    "tags": "list from: sun, rain, sand, snow, terrain, hyper_offense, bulky_offense, balance, "
    "stall, hazard_stack, sticky_web, trick_room, volturn, setup, screens, other",
    "game_plan": "2-4 sentences: how this core/team wins, in Chinese",
    "roles": "object: member -> its role in this core (Chinese, a few words)",
    "win_conditions": "list of members that are the main win conditions",
    "weaknesses": "2-3 sentences on what this core struggles against, in Chinese",
    "how_to_play_against": "2-3 sentences of advice for the opponent, in Chinese",
    "confidence": "0-1, how confident you are given the data",
}


def describe_core(core: Core, sets: dict[str, SpeciesSets], roles: dict[str, dict]) -> str:
    lines = [
        f"Core members ({core.size}): {', '.join(core.members)}",
        f"Seen together in {core.support} teams; lift {core.lift:.0f}; "
        f"each member appears with the rest at least {core.min_conditional:.0%} of the time.",
        "",
        "Mined set archetypes per member (share of that species' appearances):",
    ]
    for sp in core.members:
        ss = sets.get(sp)
        if ss is None:
            lines.append(f"- {sp}: (not enough data)")
            continue
        for a in ss.sets[:3]:
            it = ", ".join(f"{k} {v:.0%}" for k, v in a.item[:2])
            te = ", ".join(f"{k} {v:.0%}" for k, v in a.tera[:2])
            ab = ", ".join(k for k, _ in a.ability[:1])
            mv = ", ".join(f"{k} {v:.0%}" for k, v in a.moves[:6])
            lines.append(f"- {sp} [{a.weight:.0%}]: item {it}; ability {ab}; tera {te}; moves {mv}")
        r = roles.get(sp)
        if r:
            top = [k for k, v in sorted(r.items(), key=lambda kv: -kv[1]) if v >= 0.3][:5]
            lines.append(f"  functional roles (prior): {', '.join(top)}")
    return "\n".join(lines)


def name_core(
    client: LLMClient, core: Core, sets: dict[str, SpeciesSets], roles: dict[str, dict]
) -> dict:
    user = (
        describe_core(core, sets, roles)
        + "\n\nReturn a JSON object with exactly these keys:\n"
        + json.dumps(SCHEMA, ensure_ascii=False, indent=1)
    )
    out = client.chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    )
    members = set(core.members)
    wc = out.get("win_conditions") or []
    out["_invalid_win_conditions"] = [w for w in wc if w not in members]
    out["win_conditions"] = [w for w in wc if w in members]
    out["_members"] = list(core.members)
    out["_support"] = core.support
    return out
