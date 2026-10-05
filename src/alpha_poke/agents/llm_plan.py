"""LLM game plan at team preview: one call per (our team, their team) pair, cached.

Input (English, grounded): our six full sets; their six species (all that team preview shows)
plus the belief model's likely sets for them (top items / moves / tera, rounded) and the
archetype-library cores they match; our computed 6x6 matchup table as reference data.
The opponent's *actual* sets are never included (that would leak hidden information).

Output: a structured plan (lead, win conditions, threats with answers, mons to preserve, tera
target, pace, their likely win route, per-opponent notes) that is mapped onto ``Plan``.

Cache: two layers.
  1. Plan cache ``data/llm_plans/<key>.json`` where ``key`` = sha256 of a canonical JSON of
     exactly the information that determines the plan: prompt version, model, reasoning effort,
     our canonical team (mons sorted; moves sorted), their sorted species, and the belief /
     library summary as it appears in the prompt (probabilities rounded to 2 decimals). No
     battle ids, timestamps or random state -> the same team pair never costs twice.
  2. ``LLMClient``'s exact-message cache as a safety net.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from alpha_poke.llm import LLMClient

ROOT = Path(__file__).resolve().parents[3]
PLAN_CACHE = ROOT / "data" / "llm_plans"
PROMPT_VERSION = "plan-v1"

SYSTEM = (
    "You are a top competitive Pokemon player (Smogon Gen 9 OU singles, 6v6, team preview, "
    "terastallization, October 2026 metagame). Before the battle you see your full team and only "
    "the six species of the opponent. You are also given the opponent's LIKELY sets estimated "
    "from thousands of high-rated replays, the archetype they most likely play, and a "
    "computed one-vs-one matchup table. Make a concrete game plan. Rules: refer to Pokemon, "
    "moves and items exactly as written in the input; only use moves your Pokemon actually "
    "have; be decisive. Answer with one JSON object only."
)

SCHEMA = {
    "lead": "one of YOUR Pokemon (species exactly as given)",
    "win_conditions": "1-2 of YOUR Pokemon that should win the endgame",
    "preserve": "YOUR Pokemon that must not be sacrificed early (include win conditions)",
    "threats": "list of THEIR Pokemon, most dangerous first (2-4)",
    "answers": "object: THEIR Pokemon -> list of YOUR Pokemon that handle it",
    "tera_target": "one of YOUR Pokemon that should use the Tera, or null",
    "pace": "one of: aggressive, balanced, defensive (how fast you should trade)",
    "hazards_priority": "one of: high, normal, low (setting / removing entry hazards)",
    "their_win_route": "1-2 sentences: how the opponent most likely tries to win",
    "game_plan": "2-4 sentences: how you win this matchup",
    "notes": "object: THEIR Pokemon -> one short tactical note",
}


@dataclass
class LLMPlan:
    key: str
    raw: dict
    cached: bool
    cost_usd: float = 0.0
    latency_s: float = 0.0
    problems: list[str] = field(default_factory=list)  # validation issues (fixed/dropped)


def canonical_team(mons: list[dict]) -> list[dict]:
    """Sorted, normalized team description used both in the prompt and the cache key."""
    out = []
    for m in sorted(mons, key=lambda x: x["species"]):
        out.append({
            "species": m["species"],
            "item": m.get("item") or "",
            "ability": m.get("ability") or "",
            "tera": m.get("tera") or "",
            "moves": sorted(m.get("moves") or []),
        })
    return out


def plan_key(model: str, effort: str | None, ours: list[dict], their_species: list[str],
             their_info: list[dict], matchups: list[list]) -> str:
    blob = json.dumps(
        {
            "v": PROMPT_VERSION,
            "model": model,
            "effort": effort,
            "ours": canonical_team(ours),
            "theirs": sorted(their_species),
            "their_info": their_info,
            "matchups": matchups,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def build_prompt(ours: list[dict], their_info: list[dict], cores: list[str],
                 matchups: list[list]) -> str:
    lines = ["YOUR TEAM (full sets):"]
    for m in canonical_team(ours):
        lines.append(f"- {m['species']} @ {m['item'] or 'no item'} | ability {m['ability']} | "
                     f"tera {m['tera']} | moves: {', '.join(m['moves'])}")
    lines += ["", "OPPONENT TEAM (species from team preview) with LIKELY sets from replay data:"]
    for t in their_info:
        lines.append(
            f"- {t['species']}: items {t['items']}; tera {t['tera']}; likely moves {t['moves']}"
        )
    if cores:
        lines += ["", "Opponent archetype (from our archetype library): " + "; ".join(cores[:2])]
    lines += ["", "ONE-VS-ONE MATCHUP TABLE (your Pokemon vs theirs, -1 = you lose, +1 = you "
              "win; from a simple damage model, use as a hint only):"]
    for row in matchups:
        lines.append(f"- {row[0]} vs " + ", ".join(f"{o} {s:+.1f}" for o, s in row[1]))
    lines += ["", "Return a JSON object with exactly these keys:",
              json.dumps(SCHEMA, indent=1)]
    return "\n".join(lines)


def validate(raw: dict, our_species: list[str], their_species: list[str]) -> tuple[dict, list]:
    """Keep only references to real Pokemon on the right side; record what was dropped."""
    ours, theirs = set(our_species), set(their_species)
    problems = []

    def keep(xs, allowed, field_name):
        xs = xs if isinstance(xs, list) else ([xs] if xs else [])
        bad = [x for x in xs if x not in allowed]
        if bad:
            problems.append(f"{field_name}: dropped {bad}")
        return [x for x in xs if x in allowed]

    out = dict(raw)
    lead = raw.get("lead")
    if lead not in ours:
        problems.append(f"lead: invalid {lead!r}")
        out["lead"] = None
    out["win_conditions"] = keep(raw.get("win_conditions"), ours, "win_conditions")
    out["preserve"] = keep(raw.get("preserve"), ours, "preserve")
    out["threats"] = keep(raw.get("threats"), theirs, "threats")
    answers = {}
    for t, a in (raw.get("answers") or {}).items():
        if t not in theirs:
            problems.append(f"answers: unknown threat {t!r}")
            continue
        answers[t] = keep(a, ours, f"answers[{t}]")
    out["answers"] = answers
    tt = raw.get("tera_target")
    if tt is not None and tt not in ours:
        problems.append(f"tera_target: invalid {tt!r}")
        out["tera_target"] = None
    for k, allowed in (("pace", {"aggressive", "balanced", "defensive"}),
                       ("hazards_priority", {"high", "normal", "low"})):
        if raw.get(k) not in allowed:
            problems.append(f"{k}: invalid {raw.get(k)!r}")
            out[k] = "balanced" if k == "pace" else "normal"
    return out, problems


class LLMPlanner:
    def __init__(self, model: str | None = None, reasoning_effort: str | None = "low"):
        self.client = LLMClient(model=model, max_tokens=8000, reasoning_effort=reasoning_effort)
        self.effort = reasoning_effort
        PLAN_CACHE.mkdir(parents=True, exist_ok=True)

    def plan(self, ours: list[dict], their_info: list[dict], cores: list[str],
             matchups: list[list]) -> LLMPlan:
        their_species = [t["species"] for t in their_info]
        key = plan_key(self.client.model, self.effort, ours, their_species, their_info, matchups)
        path = PLAN_CACHE / f"{key}.json"
        if path.exists():
            d = json.loads(path.read_text())
            return LLMPlan(key, d["plan"], True, 0.0, 0.0, d.get("problems", []))
        prompt = build_prompt(ours, their_info, cores, matchups)
        spent0 = self.client.spent_usd
        raw = self.client.chat_json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
        )
        plan, problems = validate(raw, [m["species"] for m in ours], their_species)
        cost = self.client.spent_usd - spent0
        path.write_text(json.dumps({
            "key": key, "model": self.client.model, "prompt_version": PROMPT_VERSION,
            "prompt": prompt, "raw": raw, "plan": plan, "problems": problems,
            "cost_usd": cost, "latency_s": self.client.last_latency,
        }, indent=1))
        return LLMPlan(key, plan, False, cost, self.client.last_latency, problems)
