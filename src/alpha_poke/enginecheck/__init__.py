"""Dual-engine checks (doc/engine-diff.md): one battle scenario run in Showdown's simulator
(``showdown_case.js``, the reference) and in poke-engine (the search's transition model), from the
same state.

  states = run_showdown(p1_team, p2_team, [("move defog", "move spikes")], seed="gen5,1,2,3,4")
  before = engine_state(states[0])         # poke-engine's state built from Showdown's
  outs = engine_outcomes(before, "defog", "spikes")   # [(probability, pe.State)]
  view(states[1]) vs [view_engine(s) for _, s in outs]

The engine state is built from Showdown's own numbers (stats, HP, PP, boosts, conditions,
volatiles it knows), so a difference is the engine's, not our state construction's
(agents/engine_state.py, checked separately).
"""

import functools
import json
import subprocess
from pathlib import Path

import poke_engine as pe

ROOT = Path(__file__).resolve().parents[3]
SIM = ROOT / "vendor" / "pokemon-showdown" / "dist" / "sim"
RUNNER = Path(__file__).with_name("showdown_case.js")

STATUS = {"": "none", "brn": "burn", "par": "paralyze", "slp": "sleep", "frz": "freeze",
          "psn": "poison", "tox": "toxic"}  # fmt: skip
WEATHER = {"": "none", "sunnyday": "sun", "raindance": "rain", "sandstorm": "sand",
           "snowscape": "snow", "snow": "snow", "hail": "hail", "desolateland": "harshsun",
           "primordialsea": "heavyrain"}  # fmt: skip
TERRAIN = {"": "none", "electricterrain": "electricterrain", "grassyterrain": "grassyterrain",
           "mistyterrain": "mistyterrain", "psychicterrain": "psychicterrain"}  # fmt: skip
BOOSTS = ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")
ENGINE_BOOST = {"atk": "attack_boost", "def": "defense_boost", "spa": "special_attack_boost",
                "spd": "special_defense_boost", "spe": "speed_boost",
                "accuracy": "accuracy_boost", "evasion": "evasion_boost"}  # fmt: skip
TIMED = {"reflect": "reflect", "lightscreen": "light_screen", "auroraveil": "aurora_veil",
         "tailwind": "tailwind", "safeguard": "safeguard", "mist": "mist"}  # fmt: skip
LAYERED = {"spikes": "spikes", "toxicspikes": "toxic_spikes"}
PRESENT = {"stealthrock": "stealth_rock", "stickyweb": "sticky_web"}


def run_showdown(p1, p2, turns, seed: str | None = "gen5,1,2,3,4", force_random=None,
                 fmt: str = "gen9customgame") -> list[dict]:  # fmt: skip
    """Showdown's state after the setup and after every turn (``showdown_case.js``). ``p1`` /
    ``p2``: Showdown export text or a list of sets; ``turns``: [(p1 choice, p2 choice)];
    ``force_random``: every chance roll succeeds (True) / fails (False)."""
    case = {"format": fmt, "seed": seed, "force_random": force_random, "p1": p1, "p2": p2,
            "turns": [list(t) for t in turns]}  # fmt: skip
    r = subprocess.run(["node", str(RUNNER), str(SIM)], input=json.dumps(case),
                       capture_output=True, text=True, check=True, timeout=120)  # fmt: skip
    out = json.loads(r.stdout)
    if out["error"]:
        raise RuntimeError(out["error"])
    return out["states"]


@functools.cache
def _engine_volatile(name: str) -> bool:
    """Whether poke-engine knows the volatile status ``name`` (unknown ones are left out)."""
    try:
        pe.Side(volatile_statuses={name})
        return True
    except BaseException:  # noqa: BLE001 - the binding panics on an unknown name
        return False


def _types(types: list[str]) -> tuple[str, str]:
    t = [x.lower() for x in types] + ["typeless"]
    return t[0], t[1]


def _engine_mon(m: dict) -> pe.Pokemon:
    st = m["stats"]
    return pe.Pokemon(
        id=m["species"], level=m["level"], types=_types(m["types"]),
        base_types=_types(m["base_types"]), hp=m["hp"], maxhp=m["maxhp"],
        ability=m["ability"] or "none", base_ability=m["base_ability"] or m["ability"] or "none",
        item=m["item"] or "none", attack=st["atk"], defense=st["def"],
        special_attack=st["spa"], special_defense=st["spd"], speed=st["spe"],
        status=STATUS[m["status"]], weight_kg=m["weight"],
        moves=[pe.Move(id=x["id"], pp=x["pp"], disabled=x["disabled"]) for x in m["moves"]],
        terastallized=bool(m["terastallized"]), tera_type=(m["tera_type"] or "typeless").lower(),
    )  # fmt: skip


def _engine_side(s: dict) -> pe.Side:
    mons = [_engine_mon(m) for m in s["mons"]]
    mons += [pe.Pokemon.create_fainted() for _ in range(6 - len(mons))]
    act = s["mons"][s["active"]] if s["active"] >= 0 else None
    c = s["conditions"]
    sc = {v: c[k]["layers"] for k, v in LAYERED.items() if k in c}
    sc |= {v: 1 for k, v in PRESENT.items() if k in c}
    sc |= {v: c[k]["duration"] for k, v in TIMED.items() if k in c}
    kw: dict = {}
    if act is not None:
        kw = {ENGINE_BOOST[b]: act["boosts"][b] for b in BOOSTS}
        vol = {v for v in act["volatiles"] if _engine_volatile(v)}
        kw["volatile_statuses"] = vol
        if act["status"] == "tox":
            sc["toxic_count"] = act["status_state"]["stage"]
    return pe.Side(pokemon=mons, active_index=str(max(s["active"], 0)),
                   side_conditions=pe.SideConditions(**sc), **kw)  # fmt: skip


def engine_state(sd: dict) -> pe.State:
    """poke-engine's state built from a Showdown state (``run_showdown``)."""
    f = sd["field"]
    tr = "trickroom" in f["pseudo"]
    return pe.State(
        side_one=_engine_side(sd["sides"][0]), side_two=_engine_side(sd["sides"][1]),
        weather=WEATHER[f["weather"]], weather_turns_remaining=f["weather_duration"],
        terrain=TERRAIN[f["terrain"]], terrain_turns_remaining=f["terrain_duration"],
        trick_room=tr, trick_room_turns_remaining=f["pseudo"].get("trickroom", 0),
    )  # fmt: skip


def engine_outcomes(state: pe.State, c1: str, c2: str) -> list[tuple[float, pe.State]]:
    """Every chance outcome of the move pair in poke-engine (choices as the engine names them:
    "defog", "earthquake-tera", "switch greattusk"): [(probability, resulting state)]."""
    out = []
    for si in pe.generate_instructions(state, c1, c2):
        # the binding returns a new state (it does not change ``state``)
        out.append((si.percentage / 100, state.apply_instructions(si)))
    return out


def view(sd: dict) -> dict:
    """A Showdown state in the comparison format (``view_engine``)."""
    v: dict = {"weather": WEATHER[sd["field"]["weather"]],
               "terrain": TERRAIN[sd["field"]["terrain"]],
               "trick_room": "trickroom" in sd["field"]["pseudo"]}  # fmt: skip
    for k, s in zip(("s1", "s2"), sd["sides"], strict=True):
        v[f"{k}.active"] = s["active"]
        for j, m in enumerate(s["mons"]):
            v[f"{k}.{j}.hp"] = m["hp"]
            v[f"{k}.{j}.status"] = STATUS[m["status"]] if m["hp"] > 0 else "fainted"
            v[f"{k}.{j}.item"] = m["item"] or "none"
        act = s["mons"][s["active"]] if s["active"] >= 0 else None
        if act is not None:
            for b in BOOSTS:
                v[f"{k}.boost.{b}"] = act["boosts"][b]
            for x in act["volatiles"]:
                if _engine_volatile(x):
                    v[f"{k}.volatile.{x}"] = True
        c = s["conditions"]
        for name, eng in {**LAYERED}.items():
            v[f"{k}.{eng}"] = c[name]["layers"] if name in c else 0
        for name, eng in PRESENT.items():
            v[f"{k}.{eng}"] = int(name in c)
        for name, eng in TIMED.items():
            v[f"{k}.{eng}"] = name in c
    return v


def view_engine(s: pe.State, n_mons: tuple[int, int] = (6, 6)) -> dict:
    """A poke-engine state in the comparison format; ``n_mons``: the teams' real sizes (the
    padding is left out)."""
    v: dict = {"weather": str(s.weather).lower(), "terrain": str(s.terrain).lower(),
               "trick_room": bool(s.trick_room)}  # fmt: skip
    for (k, side), n in zip((("s1", s.side_one), ("s2", s.side_two)), n_mons, strict=True):
        a = int(side.active_index)
        v[f"{k}.active"] = a
        for j, m in enumerate(side.pokemon[:n]):
            v[f"{k}.{j}.hp"] = m.hp
            v[f"{k}.{j}.status"] = str(m.status).lower() if m.hp > 0 else "fainted"
            v[f"{k}.{j}.item"] = str(m.item).lower()
        for b in BOOSTS:
            v[f"{k}.boost.{b}"] = getattr(side, ENGINE_BOOST[b])
        for x in side.volatile_statuses:
            if str(x).lower() != "none":
                v[f"{k}.volatile.{str(x).lower()}"] = True
        sc = side.side_conditions
        for eng in LAYERED.values():
            v[f"{k}.{eng}"] = getattr(sc, eng)
        for eng in PRESENT.values():
            v[f"{k}.{eng}"] = int(getattr(sc, eng) > 0)
        for eng in TIMED.values():
            v[f"{k}.{eng}"] = getattr(sc, eng) > 0
    return v


def diff(a: dict, b: dict, skip_hp: bool = False) -> dict:
    """{key: (a's, b's)} where two views differ (``skip_hp``: HP left out)."""
    keys = set(a) | set(b)
    return {k: (a.get(k), b.get(k)) for k in sorted(keys)
            if a.get(k) != b.get(k) and not (skip_hp and k.endswith(".hp"))}  # fmt: skip


def closest(showdown_after: dict, outs: list[tuple[float, pe.State]], n_mons=(6, 6)) -> dict:
    """The engine outcome nearest to Showdown's next state: its differences (HP left out:
    the engine deals average damage rolls) and probability."""
    target = view(showdown_after)
    best = None
    for p, s in outs:
        d = diff(view_engine(s, n_mons), target, skip_hp=True)
        if best is None or len(d) < len(best[1]):
            best = (p, d)
    return {"p": best[0], "diff": best[1]} if best else {"p": 0.0, "diff": {"no outcome": 1}}


def player_log(lines: list[str], side: str) -> list[str]:
    """The log as player ``side`` ("p1" / "p2") sees it: after "|split|pX" comes the line for pX
    (exact HP) and then the one for everyone else."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("|split|"):
            who = lines[i].split("|")[2]
            out.append(lines[i + 1] if who == side else lines[i + 2])
            i += 3
        else:
            out.append(lines[i])
            i += 1
    return out


def built_state(states: list[dict], k: int, side: str, belief, seed: int = 0) -> pe.State:
    """Our own state construction (agents.engine_state.build_state, as in play) at Showdown state
    ``k`` for player ``side``: a poke-env battle fed that player's view of the log up to there
    and its request (side one = ``side``; the opponent's hidden sets sampled from ``belief``)."""
    import logging
    import random

    from poke_env.battle import Battle

    from alpha_poke.agents.engine_state import build_state

    battle = Battle(f"battle-check-{side}", side, logging.getLogger("enginecheck"), gen=9)
    for st in states[: k + 1]:
        for line in player_log(st["log"], side):
            split = line.split("|")
            if len(split) < 2 or split[1] in ("", "request"):
                continue
            try:
                battle.parse_message(split)
            except (NotImplementedError, KeyError, ValueError, AttributeError):
                pass
    req = states[k]["sides"][0 if side == "p1" else 1]["request_json"]
    if req:
        battle.parse_request(req)
    names = tuple(belief.display(m.species) for m in battle.teampreview_opponent_team)
    return build_state(battle, belief, names, random.Random(seed))
