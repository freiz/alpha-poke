"""Data tables of poke-engine and poke-env against Showdown's Gen 9 Dex (doc/engine-diff.md L8;
tests/test_engine_data.py): each function returns the differences, {key: {field: (ours, Showdown's)}}.

- moves: poke-engine's ``MOVES`` (``alpha_search.engine_data``) field by field: type, accuracy,
  category, base power, priority, flags, stat changes (self / target, as data or as a
  secondary), secondaries (status / volatile), drain, recoil, heal, status, volatile status,
  side condition, drag / pivot;
- type chart: the engine's ``type_effectiveness_modifier`` for every pair;
- base stats: the engine's forme-change table (``PokemonName::base_stats``);
- poke-env's pokedex (base stats, types, weight, abilities) and its moves (what our state
  construction and belief read)."""

import functools
import json
import re
import subprocess
from pathlib import Path

from alpha_poke.enginecheck import SIM

STAT = {"attack": "atk", "defense": "def", "special_attack": "spa", "special_defense": "spd",
        "speed": "spe", "accuracy": "accuracy"}  # fmt: skip
STATUS = {"BURN": "brn", "PARALYZE": "par", "SLEEP": "slp", "TOXIC": "tox", "POISON": "psn",
          "FREEZE": "frz"}  # fmt: skip
# the flags both sides have (the engine's drag / pivot are Showdown's forceSwitch / selfSwitch)
FLAGS = {"bite", "bullet", "charge", "contact", "heal", "powder", "protect", "pulse", "punch",
         "recharge", "reflectable", "slicing", "sound", "wind"}  # fmt: skip
SELF_TARGETS = ("self", "adjacentAllyOrSelf", "allies", "allySide")


@functools.cache
def showdown() -> dict:
    """{"moves", "species", "types"} of Showdown's Gen 9 Dex (``showdown_data.js``)."""
    js = Path(__file__).with_name("showdown_data.js")
    out = subprocess.run(["node", str(js), str(SIM)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _boosts(text: str) -> dict:
    return {STAT[k]: int(v) for k, v in re.findall(r"(\w+): (-?\d+)", text)
            if k in STAT and int(v)}  # fmt: skip


def _engine_move(row: list[str]) -> dict:
    (_, typ, acc, cat, bp, pri, _, boost, drain, recoil, heal, status, vol, side, sec,
     flags) = row  # fmt: skip
    flag_set = set(filter(None, flags.split(",")))
    e = {"type": typ.lower(), "accuracy": float(acc), "category": cat.lower(),
         "base_power": float(bp), "priority": int(pri), "flags": flag_set & FLAGS,
         "drag": "drag" in flag_set, "pivot": "pivot" in flag_set}  # fmt: skip
    boosts = set()
    if boost != "None":
        who = "self" if "target: User" in boost else "target"
        boosts.add((100.0, who, tuple(sorted(_boosts(boost).items()))))
    e["drain"] = round(float(drain[5:-1]), 2) if drain.startswith("Some") else None
    e["recoil"] = round(float(recoil[5:-1]), 2) if recoil.startswith("Some") else None
    m = re.search(r"amount: (-?[\d.]+)", heal)
    e["heal"] = round(float(m.group(1)), 2) if m and "User" in heal else None
    # status / volatile effects, of the move itself (100%) or a secondary: (chance, who, kind, name)
    effects = set()
    m = re.search(r"status: (\w+)", status)
    if m:
        who = "self" if "target: User" in status else "target"
        effects.add((100.0, who, "status", STATUS.get(m.group(1), m.group(1).lower())))
    m = re.search(r"volatile_status: (\w+)", vol)
    if m:
        who = "self" if "target: User" in vol else "target"
        effects.add((100.0, who, "volatile", m.group(1).lower()))
    m = re.search(r"condition: (\w+)", side)
    e["side_condition"] = m.group(1).lower().replace("_", "") if m else None
    for chunk in sec.split("Secondary {")[1:]:
        ch = float(re.search(r"chance: ([\d.]+)", chunk).group(1))
        who = "self" if "target: User" in chunk else "target"
        eff = chunk.split("effect: ", 1)[1]
        if eff.startswith("Boost"):
            boosts.add((ch, who, tuple(sorted(_boosts(eff).items()))))
        elif eff.startswith("Status"):
            s = re.search(r"Status\((\w+)", eff).group(1)
            effects.add((ch, who, "status", STATUS.get(s, s.lower())))
        elif eff.startswith("VolatileStatus"):
            effects.add((ch, who, "volatile", re.search(r"\((\w+)", eff).group(1).lower()))
        else:
            effects.add((ch, who, "other", eff.split("}")[0].strip()))
    e["boosts"], e["effects"] = sorted(boosts), sorted(effects)
    return e


def _showdown_move(m: dict) -> dict:
    s = {"type": m["type"].lower(),
         "accuracy": 100.0 if m["accuracy"] == "always" else float(m["accuracy"]),
         "category": m["category"].lower(), "base_power": float(m["basePower"]),
         "priority": m["priority"], "flags": set(m["flags"]) & FLAGS,
         "drag": m["forceSwitch"], "pivot": m["selfSwitch"]}  # fmt: skip
    boosts = set()
    target_boosts = {k: v for k, v in (m["boosts"] or {}).items() if v}
    if target_boosts:
        who = "self" if m["target"] in SELF_TARGETS else "target"
        boosts.add((100.0, who, tuple(sorted(target_boosts.items()))))
    self_boosts = {k: v for k, v in ((m["self"] or {}).get("boosts") or m["selfBoost"] or {}).items()
                   if v}  # fmt: skip
    if self_boosts:
        ch = float((m["self"] or {}).get("chance") or 100)
        boosts.add((ch, "self", tuple(sorted(self_boosts.items()))))
    move_who = "self" if m["target"] in SELF_TARGETS else "target"
    effects = set()
    if m["status"]:
        effects.add((100.0, move_who, "status", m["status"]))
    if m["volatileStatus"]:
        effects.add((100.0, move_who, "volatile", m["volatileStatus"]))
    sv = (m["self"] or {}).get("volatileStatus")
    if sv and sv != "mustrecharge":  # the engine's recharge flag
        effects.add((100.0, "self", "volatile", sv))
    for x in m["secondaries"]:
        ch = float(x["chance"])
        if x["status"]:
            effects.add((ch, "target", "status", x["status"]))
        if x["volatileStatus"]:
            effects.add((ch, "target", "volatile", x["volatileStatus"]))
        if x["boosts"]:
            boosts.add((ch, "target", tuple(sorted(x["boosts"].items()))))
        if x["self"] and x["self"]["boosts"]:
            boosts.add((ch, "self", tuple(sorted(x["self"]["boosts"].items()))))
    s["boosts"], s["effects"] = sorted(boosts), sorted(effects)
    s["drain"] = round(m["drain"][0] / m["drain"][1], 2) if m["drain"] else None
    s["recoil"] = round(m["recoil"][0] / m["recoil"][1], 2) if m["recoil"] else None
    s["heal"] = round(m["heal"][0] / m["heal"][1], 2) if m["heal"] else None
    s["side_condition"] = m["sideCondition"].lower() if m["sideCondition"] else None
    return s


def move_diffs() -> dict:
    """{move id: {field: (engine's, Showdown's)}} over Showdown's Gen 9 moves; a move the engine
    does not have: {"missing": (None, id)}."""
    import alpha_search

    rows, _ = alpha_search.engine_data()
    eng = {r[0].lower(): _engine_move(r) for r in rows}
    out = {}
    for m in showdown()["moves"]:
        e = eng.get(m["id"])
        if e is None:
            out[m["id"]] = {"missing": (None, m["id"])}
            continue
        s = _showdown_move(m)
        d = {k: (e[k], s[k]) for k in s if e[k] != s[k]}
        if "flags" in d:
            d["flags"] = (sorted(e["flags"] - s["flags"]), sorted(s["flags"] - e["flags"]))
        if d:
            out[m["id"]] = d
    return out


def type_chart_diffs() -> dict:
    """{(attacking, defending): (engine's multiplier, Showdown's)}."""
    import alpha_search

    _, chart = alpha_search.engine_data()
    eng = {(a.lower(), d.lower()): m for a, d, m in chart}
    out = {}
    for a, d, m in showdown()["types"]:
        e = eng.get((a.lower(), d.lower()))
        if e != m:
            out[(a.lower(), d.lower())] = (e, m)
    return out


def base_stat_diffs() -> dict:
    """{species: (engine's base stats, Showdown's)} for the species the engine has base stats of
    (its forme-change table) among Showdown's Gen 9 species."""
    import alpha_search

    sd = showdown()["species"]
    eng = alpha_search.engine_base_stats([s["id"] for s in sd])
    out = {}
    for s, e in zip(sd, eng, strict=True):
        b = s["baseStats"]
        want = (b["hp"], b["atk"], b["def"], b["spa"], b["spd"], b["spe"])
        if e is not None and tuple(e) != want:
            out[s["id"]] = (tuple(e), want)
    return out


def engine_base_stat_species() -> list[str]:
    import alpha_search

    sd = showdown()["species"]
    eng = alpha_search.engine_base_stats([s["id"] for s in sd])
    return [s["id"] for s, e in zip(sd, eng, strict=True) if e is not None]


def pokeenv_species_diffs() -> dict:
    """{species: {field: (poke-env's, Showdown's)}}: base stats, types, weight, abilities of
    poke-env's Gen 9 pokedex (what build_state and the belief read)."""
    from poke_env.data import GenData

    dex = GenData.from_gen(9).pokedex
    out = {}
    for s in showdown()["species"]:
        p = dex.get(s["id"])
        if p is None:
            out[s["id"]] = {"missing": (None, s["id"])}
            continue
        d = {}
        if p["baseStats"] != s["baseStats"]:
            d["base_stats"] = (p["baseStats"], s["baseStats"])
        if [t.lower() for t in p["types"]] != [t.lower() for t in s["types"]]:
            d["types"] = (p["types"], s["types"])
        if p.get("weightkg") != s["weightkg"]:
            d["weight"] = (p.get("weightkg"), s["weightkg"])
        ab = sorted(re.sub(r"[^a-z0-9]", "", a.lower()) for a in p["abilities"].values())
        if ab != s["abilities"]:
            d["abilities"] = (ab, s["abilities"])
        if d:
            out[s["id"]] = d
    return out


def pokeenv_move_diffs() -> dict:
    """{move: {field: (poke-env's, Showdown's)}}: type, accuracy, category, base power, priority
    of poke-env's Gen 9 moves."""
    from poke_env.data import GenData

    dex = GenData.from_gen(9).moves
    out = {}
    for m in showdown()["moves"]:
        p = dex.get(m["id"])
        if p is None:
            out[m["id"]] = {"missing": (None, m["id"])}
            continue
        acc = "always" if p["accuracy"] is True else p["accuracy"]
        d = {k: (p.get(pk), m[k]) for k, pk in (("type", "type"), ("category", "category"),
             ("basePower", "basePower"), ("priority", "priority")) if p.get(pk) != m[k]}  # fmt: skip
        if acc != m["accuracy"]:
            d["accuracy"] = (acc, m["accuracy"])
        if d:
            out[m["id"]] = d
    return out


def items_unknown_to_engine() -> list[str]:
    """Showdown's Gen 9 items with a battle effect that poke-engine does not know (it reads them
    as UNKNOWNITEM: no effect in the search)."""
    from alpha_poke.enginecheck import _engine_item

    return sorted(i["id"] for i in showdown()["items"] if i["effect"] and not _engine_item(i["id"]))
