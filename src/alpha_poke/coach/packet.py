"""A review as the first-hand facts a language model reasons from (2026-10-30): the game, both
teams with every fact the game showed (types, base stats, abilities, moves with their type,
category, power), the type matchups, the ladder's common sets, the Chinese names Showdown uses,
the turn-by-turn log and every decision's numbers. The model is told to use only these: its own
Pokémon knowledge is the part most often wrong (abilities, learnsets, and above all the Chinese
names). ``build`` -> a dict; ``text`` -> the compact JSON sent."""

import functools
import json
import re

from alpha_poke import paths
from alpha_poke.analysis.roles import to_id
from alpha_poke.coach.review import metrics, turn_events, verdict
from alpha_poke.dex import GEN

TYPES = [t.capitalize() for t in GEN.type_chart]


@functools.cache
def zh_names() -> dict[str, dict[str, str]]:
    """Showdown's Chinese names (its client's data/text/zh-cn.js, fetched for the review page):
    {"pokemon" | "moves" | "items" | "abilities": {id: name}, "types": {Type: name}}; empty
    without the client."""
    f = paths.DATA / "coach" / "client" / "data" / "text" / "zh-cn.js"
    out: dict[str, dict[str, str]] = {
        k: {} for k in ("pokemon", "moves", "items", "abilities", "types")
    }
    if not f.exists():
        return out
    js = f.read_text(encoding="utf-8")
    sections = {"Pokedex": "pokemon", "Moves": "moves", "Items": "items", "Abilities": "abilities"}
    starts = sorted((m.start(), m.group(1)) for m in re.finditer(r"[{,]([A-Z][A-Za-z]*):\{", js))
    for (a, name), (b, _) in zip(starts, starts[1:] + [(len(js), "")], strict=True):
        if name in sections:
            out[sections[name]].update(re.findall(r"([a-z0-9]+):\{name:\"([^\"]*)\"", js[a:b]))
    m = re.search(r"TypeNames:\{([^}]*)\}", js)
    if m:
        out["types"] = dict(re.findall(r"\"?([A-Za-z?]+)\"?:\"([^\"]*)\"", m.group(1)))
    return out


@functools.cache
def en_names(kind: str) -> dict[str, str]:
    """Item / ability ids -> their names (the Showdown client's data/items.js, abilities.js:
    poke-env has no such tables); empty without the client."""
    f = paths.DATA / "coach" / "client" / "data" / f"{kind}.js"
    if not f.exists():
        return {}
    js = f.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"[{,]([a-z0-9]+):\{", js):
        n = re.search(r'name:"([^"]*)"', js[m.end() : m.end() + 400])
        if n and m.group(1) not in out:
            out[m.group(1)] = n.group(1)
    return out


def _name(kind: str, x: str) -> str:
    return en_names(kind).get(to_id(x), x)


def _matchups(types: list[str]) -> dict:
    """The attacking types' multipliers on a mon of ``types``: {"x4": [...], "x2": [...],
    "x0.5": [...], "x0.25": [...], "immune": [...]}."""
    out: dict[str, list] = {"x4": [], "x2": [], "x0.5": [], "x0.25": [], "immune": []}
    for att in TYPES:
        m = 1.0
        for t in types:
            m *= GEN.type_chart.get(t.upper(), {}).get(att.upper(), 1)
        key = {4: "x4", 2: "x2", 0.5: "x0.5", 0.25: "x0.25", 0: "immune"}.get(m)
        if key:
            out[key].append(att)
    return {k: v for k, v in out.items() if v}


def _move(mid: str) -> dict:
    m = GEN.moves.get(to_id(mid)) or {}
    out = {"name": m.get("name", mid), "type": m.get("type"), "cat": m.get("category")}
    if m.get("basePower"):
        out["power"] = m["basePower"]
    if m.get("accuracy") is not True and m.get("accuracy"):
        out["acc"] = m["accuracy"]
    if m.get("priority"):
        out["priority"] = m["priority"]
    return out


def _mon(rec: dict, exact: dict | None) -> dict:
    """One mon as the facts give it: ``rec`` the review's revealed set (report["teams"]),
    ``exact`` the player's pasted set (KnownSet as a dict) or None."""
    sp = rec["species"].replace("-*", "")
    dex = GEN.pokedex.get(to_id(sp)) or {}
    types = dex.get("types", [])
    out = {"species": dex.get("name", sp), "types": types, "base": dex.get("baseStats"),
           "abilities_possible": list((dex.get("abilities") or {}).values()),
           "takes": _matchups(types)}  # fmt: skip
    src = exact or {}
    ability = src.get("ability") or rec.get("ability")
    item = src.get("item") if exact else rec.get("item")
    moves = src.get("moves") if exact else rec.get("moves")
    if ability:
        out["ability"] = _name("abilities", ability)
    if exact or item:
        out["item"] = _name("items", item) if item else "(none)"
    if src.get("tera") or rec.get("tera_type"):
        out["tera"] = (src.get("tera") or rec.get("tera_type")).capitalize()
    out["moves" if exact else "moves_seen"] = [_move(m) for m in moves or []]
    if exact and src.get("evs"):
        out["nature"], out["evs"] = src.get("nature"), src.get("evs")
    return out


def _turns(row: dict, side: str) -> dict[int, list[str]]:
    """The log by turn, compact: the lines that tell what happened (moves, switches, damage,
    faints, statuses, boosts, tera, field), ME = the player, OPP = the opponent."""
    keep = ("move", "switch", "drag", "replace", "faint", "cant", "-terastallize", "-damage", "-heal",
            "-status", "-boost", "-unboost", "-crit", "-supereffective", "-resisted", "-immune",
            "-miss", "-fail", "-sidestart", "-sideend", "-weather", "-fieldstart", "-item",
            "-enditem", "-ability", "-start", "win", "tie")  # fmt: skip
    out = {}
    for t, lines in turn_events(row["log"], side).items():
        kept = [x for x in lines if x.split("|")[0] in keep]
        if kept:
            out[t] = kept
    return out


def _decision(d: dict) -> dict:
    out = {"turn": d["turn"], "kind": d["kind"], "chosen": d["chosen"], "ai_choice": d["best"],
           "win_chance": d["value"], "loss": d["loss"], "verdict": verdict(d),
           "options": [{"option": o[0], "share": o[1], "win_chance": o[2]} for o in d["options"][:4]]}  # fmt: skip
    if d.get("guessed"):
        out["guessed_moves"] = d["guessed"]
    if d.get("opp_options"):
        out["opponent_expected"] = [{"option": o[0], "share": o[1], "your_win_chance": o[2]}
                                    for o in d["opp_options"][:3]]  # fmt: skip
        out["opponent_did"] = d.get("opp_did")
    if d.get("lines"):
        out["ai_lines"] = [[f"{s['o']} / {s['t']}: you {s['me'][0]} {s['me'][1]:.0%}"
                            + (f" (fainted in {s['me'][2]:.0%})" if s["me"][2] else "")
                            + f", opp {s['opp'][0]} {s['opp'][1]:.0%}"
                            + (f" (fainted in {s['opp'][2]:.0%})" if s["opp"][2] else "")
                            for s in line] for line in d["lines"][:2]]  # fmt: skip
    return out


def build(report: dict, row: dict, team: dict | None = None) -> dict:
    """The facts of a review (``team``: the player's pasted sets, species id -> KnownSet as a
    dict, as team.json keeps them)."""
    from alpha_poke.coach.narrate import common_sets

    me, opp = report["side"], "p2" if report["side"] == "p1" else "p1"
    exact = {to_id(k): v for k, v in (team or {}).items()}

    def mine(rec):
        sid = to_id(rec["species"].replace("-*", ""))
        return next((v for k, v in exact.items() if k.startswith(sid) or sid.startswith(k)), None)

    teams = {"you": [_mon(r, mine(r)) for r in report["teams"][me]],
             "opponent": [_mon(r, None) for r in report["teams"][opp]]}  # fmt: skip
    result = ("tie" if report["winner"] not in ("p1", "p2") else
              "won" if report["winner"] == me else "lost")  # fmt: skip
    players = row.get("players") or ["", ""]
    data = {
        "game": {"you": report.get("player"), "opponent": players[int(opp[1]) - 1] if len(players) > 1 else "",
                 "result": result, "turns": report["turns"], "your_team_pasted": bool(team),
                 "review": {k: report["settings"].get(k) for k in ("ms", "worlds", "repeats")}},
        "teams": teams,
        "opponent_common_sets": common_sets([m["species"] for m in report["teams"][opp]], top=4),
        "metrics": metrics(report),
        "log": _turns(row, me),
        "decisions": [_decision(d) for d in report["decisions"]],
    }  # fmt: skip
    data["names_zh"] = _names(data)
    return data


def _names(data: dict) -> dict:
    """The Chinese names of every Pokémon, move, item, ability and type the facts name."""
    zh = zh_names()
    text = json.dumps(data, ensure_ascii=False)
    words = set(re.findall(r"[a-z0-9]+", text))
    out: dict[str, dict] = {}
    tables = {"pokemon": {k: v.get("name") for k, v in GEN.pokedex.items()},
              "moves": {k: v.get("name") for k, v in GEN.moves.items()},
              "items": en_names("items"), "abilities": en_names("abilities")}  # fmt: skip
    for kind, table in tables.items():
        names = {}
        for k, name in zh[kind].items():
            en = table.get(k)
            # (whole words: an id inside another -- "natu" in "nature" -- is not a mention; the
            # text's words looked up, a name's boundaries checked only where it occurs: 5 s of
            # regex searches over the whole text before)
            if en and (k in words or (en in text and re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(en)}(?![A-Za-z0-9])", text))):  # fmt: skip
                names[en] = name
        out[kind] = names
    out["types"] = {t: n for t, n in zh["types"].items() if t in TYPES}
    return out


def text(data: dict) -> str:
    """The facts as sent: compact JSON."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
