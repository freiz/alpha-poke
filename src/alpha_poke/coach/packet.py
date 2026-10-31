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
    # (the chances named apart: the position's, the chosen option's, the AI's choice's -- one
    # "win_chance" for the position read as the chosen move's, 2026-10-30; the chosen option always
    # among the options shown)
    opts = d["options"][:4] + [o for o in d["options"][4:] if o[0] == d["chosen"]][:1]
    out = {"turn": d["turn"], "kind": d["kind"], "chosen": d["chosen"], "ai_choice": d["best"],
           "position_win_chance": d["value"], "chosen_win_chance": d.get("chosen_value"),
           "ai_choice_win_chance": d.get("best_value"), "loss": d["loss"], "verdict": verdict(d),
           "options": [{"option": o[0], "share": o[1], "win_chance": o[2]} for o in opts]}  # fmt: skip
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
    from alpha_poke.coach.meta import revealed_archetype
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
        "opponent_archetype": revealed_archetype(report["teams"][opp]),
        "metrics": metrics(report),
        "log": _turns(row, me),
        "decisions": [_decision(d) for d in report["decisions"]],
    }  # fmt: skip
    data["names_zh"] = _names(data)
    return data


def team(report: dict, row: dict, team_sets: dict | None = None, review_dir=None) -> dict:
    """The facts for a team's analysis: build's (the game's numbers show what the team met) with
    team_facts, the names again over all of it."""
    from alpha_poke.coach import meta

    data = build(report, row, team_sets)
    data["team_facts"] = team_facts(data)
    # (the metagame's view of the team: the shipped snapshot, by species -- coach.meta)
    mine = [m["species"] for m in report["teams"][report["side"]]]
    export = meta.team_export(report, team_sets)
    if len(mine) != 6:
        facts = None
    elif review_dir is not None:
        facts = meta.facts_kept(review_dir, mine, export)
    else:
        facts = meta.facts(mine, export=export)
    if facts:
        data["team_facts"]["metagame"] = facts
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


HAZARDS = {"stealthrock", "spikes", "toxicspikes", "stickyweb", "stoneaxe", "ceaselessedge"}
REMOVAL = {"rapidspin", "defog", "courtchange", "tidyup", "mortalspin"}
PROTECT = {"protect", "detect", "kingsshield", "spikyshield", "banefulbunker", "silktrap",
           "burningbulwark", "obstruct"}  # fmt: skip
RECOVERY = {"wish", "rest", "strengthsap", "painsplit", "lifedew", "junglehealing"}


def roles(mid: str) -> list[str]:
    """What a move does for a team: hazards, hazard removal, priority, pivot, recovery, setup,
    protect, status."""
    mid = to_id(mid)
    m = GEN.moves.get(mid) or {}
    out = []
    if mid in HAZARDS or m.get("sideCondition") in HAZARDS:
        out.append("hazards")
    if mid in REMOVAL:
        out.append("hazard removal")
    if (m.get("priority") or 0) > 0 and m.get("category") != "Status":
        out.append("priority")
    if m.get("selfSwitch") and mid != "batonpass":
        out.append("pivot")
    if mid in RECOVERY or (m.get("heal") and m.get("target") == "self"):
        out.append("recovery")
    if m.get("boosts") and m.get("target") == "self":
        out.append("setup")
    if mid in PROTECT:
        out.append("protect")
    if m.get("category") == "Status" and m.get("status"):
        out.append("status")
    return out


def team_facts(data: dict, top: int = 15) -> dict:
    """The player's team as a whole (data: build's): how many of it each attacking type hits
    super effectively / is resisted by / cannot touch; what its known attacks hit super
    effectively and what nothing does; its speeds against the opponent's; the roles its known
    moves fill and the ones none does; its species' common sets on the ladder; the ladder's most
    used species (types, base Speed, their most common moves) -- the threats a team meets."""
    from alpha_poke.coach.narrate import common_sets, usage_table

    you = data["teams"]["you"]
    defense = {}
    for t in TYPES:
        row = {
            k: [m["species"] for m in you if t in m["takes"].get(k, [])]
            for k in ("x4", "x2", "x0.5", "x0.25", "immune")
        }
        weak = row["x4"] + row["x2"]
        if weak or row["immune"]:
            defense[t] = {
                "weak": weak,
                "resist": row["x0.5"] + row["x0.25"],
                "immune": row["immune"],
            }
    moves = [mv for m in you for mv in m.get("moves") or m.get("moves_seen") or []]
    hit = set()
    for mv in moves:
        if mv.get("cat") in ("Physical", "Special") and mv.get("type"):
            hit |= {
                d.capitalize()
                for d, row in GEN.type_chart.items()
                if row.get(mv["type"].upper(), 1) > 1
            }
    filled: dict[str, list] = {}
    for m in you:
        for mv in m.get("moves") or m.get("moves_seen") or []:
            for r in roles(mv["name"]):
                filled.setdefault(r, []).append(f"{m['species']}: {mv['name']}")
    usage = usage_table()
    ladder = sorted(usage.items(), key=lambda kv: -kv[1].usage)[:top]
    return {
        "defense_by_attacking_type": defense,
        "known_attacks_super_effective_on": sorted(hit),
        "known_attacks_nothing_super_effective_on": [t for t in TYPES if t not in hit],
        "speed": {"you": [[m["species"], m["base"]["spe"]] for m in you if m.get("base")],
                  "opponent": [[m["species"], m["base"]["spe"]] for m in data["teams"]["opponent"] if m.get("base")]},
        "roles": filled,
        "roles_missing": [r for r in ("hazards", "hazard removal", "priority", "pivot", "recovery") if r not in filled],
        "your_common_sets": common_sets([m["species"] for m in you], top=8),
        "ladder_top": [{"species": (GEN.pokedex.get(k) or {}).get("name", k), "usage": round(s.usage, 3),
                        "types": (GEN.pokedex.get(k) or {}).get("types"),
                        "base_spe": ((GEN.pokedex.get(k) or {}).get("baseStats") or {}).get("spe"),
                        "moves": [(GEN.moves.get(to_id(x)) or {}).get("name", x) for x in list(s.move_has)[:4]]}
                       for k, s in ladder],
    }  # fmt: skip


def turn(report: dict, row: dict, team: dict | None, i: int) -> dict:
    """The facts of one decision (the i-th of the review): both teams, the decision with every
    option, the opponent's expected replies, the AI's lines, the public state, the log of its turn
    and the two before."""
    data = build(report, row, team)
    d = report["decisions"][i]
    full = _decision(d) | {
        "options": [{"option": o[0], "share": o[1], "win_chance": o[2], "error": o[3]} for o in d["options"]],
        "state": d.get("state"),
    }  # fmt: skip
    if d.get("lines"):
        full["ai_lines"] = _decision(d | {"lines": d["lines"]})["ai_lines"] if len(d["lines"]) <= 2 else [
            _decision(d | {"lines": [x]})["ai_lines"][0] for x in d["lines"]]  # fmt: skip
    out = {k: data[k] for k in ("game", "teams", "opponent_common_sets")}
    out["log"] = {t: v for t, v in data["log"].items() if d["turn"] - 2 <= int(t) <= d["turn"]}
    out["decision"] = full
    out["names_zh"] = _names(out)
    return out


def text(data: dict) -> str:
    """The facts as sent: compact JSON."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
