"""The review as a coach's report: a plain-text summary (no model needed), and a write-up by an
OpenAI-compatible chat model (.env: COACH_LLM_BASE_URL, COACH_LLM_API_KEY, COACH_LLM_MODEL;
never printed) told to use only the review's numbers and facts. Every move the write-up names is
checked against the two teams' learnsets and the moves used in the game: an unknown one gets a
warning appended (a model's invention, not a fact)."""

import functools
import json
import re

import requests

from alpha_poke.analysis.roles import to_id
from alpha_poke.coach.review import key_moments, metrics, mistake_score, swings
from alpha_poke.dex import MOVE_IDS, learnset
from alpha_poke.servers import load_env

SYSTEM = """You are a Pokémon Showdown Gen 9 OU coach reviewing one game for a young player.
You get the game's review as JSON: for each of the player's decisions the options a strong search
AI considered, with its estimated winning chance after each option ("value", 0-1) and how often
it chose each ("share"), the option the player chose, the AI's choice and the loss
(AI choice's chance minus the chosen one's); the public state; the turn's log events (ME = the
player, OPP = the opponent); both teams as revealed; the most common sets of each species on the
ladder (Smogon usage statistics).
Rules:
- Use only these numbers and facts. Do not invent moves, items, abilities or events. Name
  Pokémon, moves, items and abilities in English exactly as Showdown does.
- The AI's numbers are estimates from a few seconds of search: say "the AI thought ... was
  better (about X% vs Y% to win)", never that a move was certainly wrong; the decisions in key_moments are the ones it disagreed with most (its share of visits on its own
  choice vs the player's counts more than small differences of value).
- Explain *why* using the facts: type matchups (resisted / immune / super effective), abilities
  and items that blocked a move, boosts the opponent set up, hazards, speed, tera timing.
- Suggest set changes only with moves the species can learn (the learnsets given) and items /
  abilities / tera types from the common sets given; say why each helps.
Write in {language}, friendly and concrete, for a child; Pokémon / move / item names in English.
Sections: 1. 总结 (2-3 sentences) 2. 指挥 (the 3-5 most important moments: turn, what happened,
what the AI preferred and why, the lesson) 3. 队伍与配置 (team weaknesses this game exposed;
concrete set suggestions) 4. 下次练习 (2-3 points)."""


@functools.cache
def _usage(path) -> dict:
    """Species id -> its usage statistics (one file read per process: 5 s each time)."""
    from alpha_poke.data.smogon_stats import UsageStats

    return {to_id(n): s for n, s in UsageStats.load(path).species.items()}


def common_sets(species: list[str], top: int = 6) -> dict:
    """The species' most common abilities, items, moves, tera types and spreads in the latest
    month of Smogon's gen9ou statistics (data/raw/smogon; {} without them)."""
    from alpha_poke.data.smogon_stats import DEFAULT_DIR

    months = (
        sorted(p.name for p in DEFAULT_DIR.iterdir() if p.is_dir()) if DEFAULT_DIR.exists() else []
    )
    path = DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1500.json" if months else None
    if path is None or not path.exists():
        return {}
    by_id = _usage(path)
    out = {}
    for sp in species:
        s = by_id.get(to_id(sp.replace("-*", "")))
        if s is None:
            continue
        pick = lambda d: [k for k in list(d)[:top]]  # noqa: E731
        out[sp] = {"usage": round(s.usage, 3), "abilities": pick(s.abilities), "items": pick(s.items),
                   "moves": pick(s.move_has), "tera": pick(s.tera_types), "spreads": pick(s.spreads)[:3]}  # fmt: skip
    return out


def summary(report: dict) -> str:
    """The review in plain text (markdown): the result, the winning-chance curve, the decisions
    that cost the most, the largest swings."""
    me = report["side"]
    won = report["winner"] == me
    ds = report["decisions"]
    lines = [f"# Review: {report['id']} ({'won' if won else 'lost'}, {report['turns']} turns)", ""]
    m = metrics(report)
    pc = lambda x: "-" if x is None else f"{100 * x:.0f}%"  # noqa: E731
    lines += [f"Matched the AI's first choice {pc(m['top1'])}, its top two {pc(m['top2'])} "
              f"({m['decisions']} decisions with a choice); mean winning chance lost "
              f"{'-' if m['mean_loss'] is None else f'{100 * m['mean_loss']:.1f} points'}; "
              f"AI disagreed {m['bad']}, didn't like it {m['mild']}.", ""]  # fmt: skip
    lines += ["## Winning chance by decision (the search's estimate)", "",
              "| turn | kind | chosen | AI's choice | win % | loss |", "|---|---|---|---|---|---|"]  # fmt: skip
    for d in ds:
        loss = ("untried" if d["chosen_value"] is None else "?" if d["loss"] is None  # (never with the best)
                else f"{max(0.0, 100 * d['loss']):.0f}")  # fmt: skip
        mark = " **" if mistake_score(d) >= 0.10 else ""
        lines.append(f"| {d['turn']} | {d['kind']} | {d['chosen']}{mark} | {d['best']} | "
                     f"{100 * d['value']:.0f} | {loss} |")  # fmt: skip
    lines += ["", "## The decisions that cost the most", ""]
    for d in key_moments(report):
        opts = ", ".join(
            f"{c} {'untried' if q is None else f'{100 * q:.0f}%'} ({100 * s:.0f}% of the search)"
            for c, s, q, *_ in d["options"][:4]
        )
        lines.append(f"- turn {d['turn']}: chose **{d['chosen']}**"
                     f" ({'never tried by the search' if d['chosen_value'] is None else f'{100 * d['chosen_value']:.0f}%'}),"
                     f" the AI: **{d['best']}** {100 * d['best_value']:.0f}%. Options: {opts}")  # fmt: skip
    lines += ["", "## The largest swings", ""]
    for s in swings(report):
        lines.append(
            f"- turns {s['from']} -> {s['to']}: {100 * s['before']:.0f}% -> {100 * s['after']:.0f}%"
        )
    return "\n".join(lines) + "\n"


def _prompt(report: dict, language: str) -> tuple[str, str]:
    me, opp = report["side"], "p2" if report["side"] == "p1" else "p1"
    teams = {"me": report["teams"][me], "opp": report["teams"][opp]}
    species = [m["species"] for m in teams["me"] + teams["opp"]]
    data = {
        "result": "won" if report["winner"] == me else "lost", "turns": report["turns"],
        "teams": teams, "common_sets": common_sets(species),
        "learnsets": {m["species"]: sorted(learnset(m["species"]) or []) for m in teams["me"]},
        "key_moments": key_moments(report, k=6), "swings": swings(report),
        "all_decisions": [{k: d[k] for k in ("turn", "kind", "chosen", "best", "value", "loss")}
                          for d in report["decisions"]],
    }  # fmt: skip
    return SYSTEM.replace("{language}", language), json.dumps(data, ensure_ascii=False)


def unknown_moves(text: str, report: dict) -> list[str]:
    """Moves the text names that neither team can learn nor anyone used in the game."""
    allowed: set[str] = set()
    for side in ("p1", "p2"):
        for m in report["teams"][side]:
            allowed |= learnset(m["species"]) or set()
            allowed |= {to_id(x) for x in m["moves"]}
    names = {to_id(v): v for v in MOVE_IDS.values() if len(v) > 4}
    found = {mid for mid, name in names.items() if re.search(rf"\b{re.escape(name)}\b", text)}
    return sorted(names[m] for m in found - allowed)


def write_up(report: dict, language: str = "Chinese (简体中文)", timeout: float = 300) -> str:
    """The coach's report by the configured chat model."""
    env = load_env()
    base, key, model = (
        env.get(k) for k in ("COACH_LLM_BASE_URL", "COACH_LLM_API_KEY", "COACH_LLM_MODEL")
    )
    if not (base and key and model):
        raise RuntimeError(
            "COACH_LLM_BASE_URL / COACH_LLM_API_KEY / COACH_LLM_MODEL missing in .env"
        )
    system, user = _prompt(report, language)
    r = requests.post(
        base.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "temperature": 0.3,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=timeout,
    )  # fmt: skip
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    bad = unknown_moves(text, report)
    if bad:
        text += ("\n\n> 校验提示：报告提到的这些招式不在双方宝可梦的可学招式里，也没有在对局中出现，"
                 f"可能是模型写错了：{', '.join(bad)}\n")  # fmt: skip
    return text
