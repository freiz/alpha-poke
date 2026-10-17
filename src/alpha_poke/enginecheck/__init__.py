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
import math
import re
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
                 fmt: str = "gen9customgame", damage_probe: bool = False) -> list[dict]:  # fmt: skip
    """Showdown's state after the setup and after every turn (``showdown_case.js``). ``p1`` /
    ``p2``: Showdown export text or a list of sets; ``turns``: [(p1 choice, p2 choice)];
    ``force_random``: every chance roll succeeds (True) / fails (False); ``damage_probe``: each
    state also has "damage", {"p1" / "p2": {move: its max damage (no crit) on the other active}}
    (``showdown_damage.js``)."""
    case = {"format": fmt, "seed": seed, "force_random": force_random, "p1": p1, "p2": p2,
            "turns": [list(t) for t in turns], "damage_probe": damage_probe}  # fmt: skip
    r = subprocess.run(["node", str(RUNNER), str(SIM)], input=json.dumps(case),
                       capture_output=True, text=True, check=True, timeout=120)  # fmt: skip
    out = json.loads(r.stdout)
    if out["error"]:
        raise RuntimeError(out["error"])
    return out["states"]


def random_battle(p1, p2, seed: str, choice_seed: int, max_turns: int = 100,
                  switch_p: float = 0.15, tera_p: float = 0.1, fmt: str = "gen9customgame",
                  damage_probe: bool = False) -> tuple[list[dict], str | None]:  # fmt: skip
    """A whole battle with random legal choices (``random_battle.js``): ([{"state", "choices"}]
    per decision point, the error if the battle broke off). The full-information differential
    (doc/engine-diff.md): the truth at every step, no player's view, no belief."""
    case = {"format": fmt, "seed": seed, "choice_seed": choice_seed, "p1": p1, "p2": p2,
            "max_turns": max_turns, "switch_p": switch_p, "tera_p": tera_p,
            "damage_probe": damage_probe}  # fmt: skip
    r = subprocess.run(["node", str(RUNNER.with_name("random_battle.js")), str(SIM)],
                       input=json.dumps(case), capture_output=True, text=True, check=True,
                       timeout=600)  # fmt: skip
    out = json.loads(r.stdout)
    return out["steps"], out["error"]


@functools.cache
def _engine_item(name: str) -> bool:
    """Whether poke-engine knows the item ``name`` (an unknown one reads back as UNKNOWNITEM)."""
    p = pe.Pokemon(item=name)
    s = pe.State(side_one=pe.Side(pokemon=[p] + [pe.Pokemon.create_fainted()] * 5))
    return str(pe.State.from_string(s.to_string()).side_one.pokemon[0].item).lower() == name


@functools.cache
def _engine_volatile(name: str) -> bool:
    """Whether poke-engine knows the volatile status ``name`` (unknown ones are left out): the
    binding takes any name and the engine reads an unknown one as NONE (2026-10-16: so a check of
    ``pe.Side`` alone let Showdown's "choicelock" into the comparison)."""
    try:
        side = pe.Side(pokemon=[pe.Pokemon.create_fainted()] * 6, volatile_statuses={name})
        back = pe.State.from_string(pe.State(side_one=side).to_string()).side_one
        return {str(v).lower() for v in back.volatile_statuses} == {name}
    except BaseException:  # noqa: BLE001 - the binding panics on an unknown name
        return False


def _types(types: list[str]) -> tuple[str, str]:
    t = [x.lower() for x in types] + ["typeless"]
    return t[0], t[1]


def _sleep(m: dict) -> dict:
    """The engine's sleep counters from Showdown's: Rest's remaining turns (rest_turns), or the
    attempts made asleep (sleep_turns: startTime - time; it wakes at the startTime-th, 2-4)."""
    if m["status"] != "slp":
        return {}
    ss = m["status_state"]
    if ss.get("source") == "rest":
        return {"rest_turns": max(ss["time"], 1)}
    return {"sleep_turns": min(max(ss["startTime"] - ss["time"], 0), 3)}


def _engine_mon(m: dict) -> pe.Pokemon:
    st = m["stats"]
    return pe.Pokemon(**_sleep(m),
        # the engine keeps the original types when terastallized (tera_type apart, L31)
        id=m["species"], level=m["level"], types=_types(m.get("pre_tera_types") or m["types"]),
        base_types=_types(m["base_types"]), hp=m["hp"], maxhp=m["maxhp"],
        ability=m["ability"] or "none",
        # a used once-per-battle switch-in ability: base ability none (L18)
        base_ability="none" if m.get("used_once") else (m["base_ability"] or m["ability"] or "none"),
        item=m["item"] or "none", attack=st["atk"], defense=st["def"],
        special_attack=st["spa"], special_defense=st["spd"], speed=st["spe"],
        status=STATUS[m["status"]], weight_kg=m["weight"], nature=m.get("nature", "serious").lower(),
        moves=[pe.Move(id=x["id"], pp=x["pp"], disabled=x["disabled"]) for x in m["moves"]],
        terastallized=bool(m["terastallized"]), tera_type=(m["tera_type"] or "typeless").lower(),
        last_item=m.get("last_item") if _engine_item(m.get("last_item") or "") else "none",
    )  # fmt: skip


def _changed_types(m: dict) -> bool:
    """A type change other than Terastallization (the engine's typechange volatile)."""
    return not m["terastallized"] and [t.lower() for t in m["types"]] != [
        t.lower() for t in m["base_types"]
    ]


# the patched engine's limits of the volatiles it ends (ends of turn)
LIMITS = {"partiallytrapped": 5, "healblock": 2, "throatchop": 2, "magnetrise": 5, "micleberry": 2}


def _engine_side(s: dict, future_sight=None, wish=None) -> pe.Side:
    mons = [_engine_mon(m) for m in s["mons"]]
    mons += [pe.Pokemon.create_fainted() for _ in range(6 - len(mons))]
    act = s["mons"][s["active"]] if s["active"] >= 0 else None
    c = s["conditions"]
    sc = {v: c[k]["layers"] for k, v in LAYERED.items() if k in c}
    sc |= {v: 1 for k, v in PRESENT.items() if k in c}
    sc |= {v: c[k]["duration"] for k, v in TIMED.items() if k in c}
    # Healing Wish / Lunar Dance waiting on the slot (Gen 9: until a mon that needs it comes in;
    # Showdown's slot condition, the engine's side condition; L48)
    # (Lunar Dance: the engine's Healing Wish, L52)
    for name, eng in (("healingwish", "healing_wish"), ("lunardance", "healing_wish")):
        if name in s.get("slot", {}):
            sc[eng] = 1
    kw: dict = {"future_sight": future_sight} if future_sight else {}
    if wish:
        kw["wish"] = wish
    if act is not None:
        kw |= {ENGINE_BOOST[b]: act["boosts"][b] for b in BOOSTS}
        names = [x + st["stat"] if x in ("protosynthesis", "quarkdrive") and st.get("stat") else x
                 for x, st in act["volatiles"].items()]  # fmt: skip
        vol = {v for v in names if _engine_volatile(v) and v != "stall"}
        # Metronome: Showdown keeps the volatile from the switch-in, the engine while it counts
        metronome = act["volatiles"].get("metronome", {}).get("num_consecutive", 0)
        if not metronome:
            vol.discard("metronome")
        if _changed_types(act):  # Showdown keeps no volatile for a type change (Libero, Soak, ...)
            vol.add("typechange")
        if act.get("transformed"):  # (L36: Showdown's flag, the engine's volatile)
            vol.add("transform")
        kw["volatile_statuses"] = vol
        if "substitute" in act["volatiles"]:  # its HP (L43: it was 0, any hit broke it)
            kw["substitute_health"] = act["volatiles"]["substitute"]["hp"]
        stall = act["volatiles"].get("stall")  # Protect's counter: 3 ** (consecutive protects)
        if stall and stall["counter"]:
            sc["protect"] = round(math.log(stall["counter"], 3))
        ids = [x["id"] for x in act["moves"]]
        if act.get("move_actions") and act.get("last_move") in ids:
            kw["last_used_move"] = f"move:{ids.index(act['last_move'])}"
        else:  # not moved since it came in
            kw["last_used_move"] = f"switch:{s['active']}"
        # the engine counts ends of turn up to its limit (L13; the 2026-10-13 patch), Showdown
        # counts the turns left down
        dur = {k: max(n - act["volatiles"][k]["duration"], 0) for k, n in LIMITS.items()
               if k in vol and act["volatiles"][k]["duration"]}  # fmt: skip
        # the engine counts what has passed: Taunt / Encore (ends at the third), Yawn (sleep at
        # the second end of turn), confusion (attempts; ends for sure after 4: Showdown's time
        # is the attempts left, the last one snapping out)
        for k, n, top in (("taunt", 3, 2), ("encore", 3, 2), ("yawn", 2, 1)):
            if k in vol and act["volatiles"][k]["duration"]:
                dur[k] = min(max(n - act["volatiles"][k]["duration"], 0), top)
        # a locking move (Outrage): the engine's count of its ends of turn ends it at 2 (3 turns),
        # Showdown's trueDuration counts the turns left down
        if "lockedmove" in vol and act["volatiles"]["lockedmove"]["true_duration"]:
            dur["lockedmove"] = min(max(3 - act["volatiles"]["lockedmove"]["true_duration"], 0), 2)
        if metronome:
            dur["metronome"] = metronome
        if "confusion" in vol and act["volatiles"]["confusion"]["time"]:
            dur["confusion"] = min(max(5 - act["volatiles"]["confusion"]["time"], 0), 4)
        if dur:
            kw["volatile_status_durations"] = pe.VolatileStatusDurations(**dur)
        if act["status"] == "tox":
            sc["toxic_count"] = act["status_state"]["stage"]
    return pe.Side(pokemon=mons, active_index=str(max(s["active"], 0)),
                   side_conditions=pe.SideConditions(**sc), **kw)  # fmt: skip


def engine_state(sd: dict) -> pe.State:
    """poke-engine's state built from a Showdown state (``run_showdown``)."""
    f = sd["field"]
    tr = "trickroom" in f["pseudo"]
    # a pending Future Sight is on its target's slot in Showdown (it hits at the end of turn
    # endingTurn + 1), on its user's side in the engine (turns: 1 before the turn it hits)
    future = [None, None]
    for k, s in enumerate(sd["sides"]):
        fm = s.get("slot", {}).get("futuremove")
        if fm and fm["source"] >= 0:
            turns = fm["ending_turn"] - sd["turn"] + 2
            future[1 - k] = (turns, pe.PokemonIndex(str(fm["source"])))
    # Wish: a condition of the user's slot (its HP, unrounded maxhp / 2; Showdown heals at the end
    # of turn startingTurn + 2, the engine at the end of the turn its count is 1)
    wish = [None, None]
    for k, s in enumerate(sd["sides"]):
        w = s.get("slot", {}).get("wish")
        if w and w.get("hp"):
            wish[k] = (w["starting_turn"] + 3 - sd["turn"], int(w["hp"]))
    sides = [_engine_side(s, f, w) for s, f, w in zip(sd["sides"], future, wish, strict=True)]
    return pe.State(
        side_one=sides[0], side_two=sides[1],
        weather=WEATHER[f["weather"]], weather_turns_remaining=f["weather_duration"],
        terrain=TERRAIN[f["terrain"]], terrain_turns_remaining=f["terrain_duration"],
        trick_room=tr, trick_room_turns_remaining=f["pseudo"].get("trickroom", 0),
    )  # fmt: skip


DAMAGE = re.compile(r"^Damage (SideOne|SideTwo): (-?\d+)$")


def engine_outcomes(state: pe.State, c1: str, c2: str) -> list[tuple[float, pe.State]]:
    """Every chance outcome of the move pair in poke-engine (choices as the engine names them:
    "defog", "earthquake-tera", "switch greattusk"): [(probability, resulting state)]; each
    state carries ``damage`` (``engine_damage``)."""
    out = []
    for si in pe.generate_instructions(state, c1, c2):
        # the binding returns a new state (it does not change ``state``)
        dmg = [0, 0]
        for ins in si.instruction_list:
            m = DAMAGE.match(str(ins))
            if m:  # (a negative one is a heal: Pain Split, not a roll)
                dmg[m.group(1) == "SideTwo"] += max(int(m.group(2)), 0)
        out.append((si.percentage / 100, state.apply_instructions(si), tuple(dmg)))
    return [Outcome(p, s, d) for p, s, d in out]


class Outcome(tuple):
    """(probability, state) with the damage each side took (the sum of the outcome's Damage
    instructions: the roll tolerance of the HP comparison)."""

    def __new__(cls, p: float, state: pe.State, damage: tuple[int, int]):
        o = super().__new__(cls, (p, state))
        o.damage = damage
        return o


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
            # an item the engine does not know is its unknownitem (tests/test_engine_data.py lists them)
            v[f"{k}.{j}.item"] = (m["item"] if _engine_item(m["item"]) else "unknownitem") if m["item"] else "none"
        act = s["mons"][s["active"]] if s["active"] >= 0 else None
        if act is not None:
            for b in BOOSTS:
                v[f"{k}.boost.{b}"] = act["boosts"][b]
            if _changed_types(act):
                v[f"{k}.volatile.typechange"] = True
            if act.get("transformed"):
                v[f"{k}.volatile.transform"] = True
            for x, st in act["volatiles"].items():
                # Protosynthesis / Quark Drive: one volatile in Showdown (the stat in its state),
                # one per stat in the engine ("protosynthesisatk")
                if x in ("protosynthesis", "quarkdrive") and st.get("stat"):
                    x += st["stat"]
                # (Protect's counter: Showdown's "stall" volatile, the engine's protect side
                # condition -- not compared as a volatile)
                if x == "metronome" and not st.get("num_consecutive"):
                    continue  # (the engine's is on while it counts)
                if _engine_volatile(x) and x != "stall":
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
        tera = side.pokemon[a].terastallized
        for x in side.volatile_statuses:
            # (a terastallized mon's typechange has no effect: its type is the tera type;
            # Showdown's side compares the types other than Terastallization, _changed_types)
            if str(x).lower() != "none" and not (tera and str(x).lower() == "typechange"):
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


def hp_diff(showdown_after: dict, out, n_mons=(6, 6), tol: int = 2,
            dealt=(False, False)) -> dict:  # fmt: skip
    """{"sK.j.hp": (engine, showdown)} where an HP differs by more than the damage rolls'
    spread: the engine deals the average roll (0.925 x max), so +-8.5% of the damage that side
    took in this outcome, + ``tol``; a side whose HP also follows the damage it dealt (``dealt``:
    a drain / recoil move, Shell Bell) +-8.5% of 3/4 of that too."""
    target = view(showdown_after)
    v = view_engine(out[1], n_mons)
    dmg = getattr(out, "damage", (0, 0))
    bad = {}
    for k, e in v.items():
        if k.endswith(".hp"):
            side = 0 if k.startswith("s1.") else 1
            spread = 0.085 * dmg[side] + (0.085 * 0.75 * dmg[1 - side] if dealt[side] else 0)
            if abs(e - target[k]) > spread + tol:
                bad[k] = (e, target[k])
    return bad


def closest(showdown_after: dict, outs: list, n_mons=(6, 6), hp: bool = False,
            dealt=(False, False)) -> dict:  # fmt: skip
    """The engine outcome nearest to Showdown's next state: its differences and probability.
    HP is left out unless ``hp`` (then compared within the damage rolls' spread, ``hp_diff``)."""
    target = view(showdown_after)
    best = None
    for o in outs:
        d = diff(view_engine(o[1], n_mons), target, skip_hp=True)
        if hp:
            d |= hp_diff(showdown_after, o, n_mons, dealt=dealt)
        if best is None or len(d) < len(best[1]):
            best = (o[0], d)
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


def field_setters(lines: list[str]) -> dict[int, tuple[str | None, str | None]]:
    """{turn t: (the side that set the weather, the side that set the terrain)} at the start of
    turn t ("p1" / "p2" / None), from a battle's protocol lines (public: "[of] pXa: ..." for an
    ability, else the side that just moved). The full-information state of a turn takes the
    weather / terrain from the setter's own view: only it knows its extending item (Damp Rock,
    Terrain Extender, ...); the other view's turns are a belief sample."""
    out: dict[int, tuple[str | None, str | None]] = {}
    weather = terrain = mover = None
    for line in lines:
        p = line.split("|")
        if len(p) < 2:
            continue
        of = next((x[5:7] for x in p[3:] if x.startswith("[of] p")), None)
        if p[1] == "move" and len(p) > 2:
            mover = p[2][:2]
        elif p[1] == "-weather" and len(p) > 2 and "[upkeep]" not in p:
            weather = None if p[2] == "none" else (of or mover)
        elif p[1] == "-fieldstart" and len(p) > 2 and p[2].endswith("Terrain"):
            terrain = of or mover
        elif p[1] == "-fieldend" and len(p) > 2 and p[2].endswith("Terrain"):
            terrain = None
        elif p[1] == "turn" and len(p) > 2:
            out[int(p[2])] = (weather, terrain)
    return out


def crit_stages(p1, p2, turns=(), seed: str = "gen5,1,2,3,4") -> dict[str, int]:
    """Showdown's critical-hit stage of p1's active's moves against p2's active after ``turns``
    (``crit_ratio.js``: its ModifyCritRatio event; Showdown's ratio starts at 1, a move's
    default: chance 1/24, 1/8, 1/2, 1 for 1, 2, 3, 4)."""
    case = {"p1": p1, "p2": p2, "turns": [list(t) for t in turns], "seed": seed}
    r = subprocess.run(["node", str(RUNNER.with_name("crit_ratio.js")), str(SIM)],
                       input=json.dumps(case), capture_output=True, text=True, check=True,
                       timeout=120)  # fmt: skip
    out = json.loads(r.stdout)
    if out["error"]:
        raise RuntimeError(out["error"])
    return out["stages"]


def accuracies(p1, p2, turns=(), seed: str = "gen5,1,2,3,4") -> dict:
    """Showdown's accuracy of p1's active's moves against p2's active after ``turns`` (its
    ModifyAccuracy event: Bright Powder, Zoom Lens as if p2 had moved; True: it cannot miss)."""
    case = {"p1": p1, "p2": p2, "turns": [list(t) for t in turns], "seed": seed}
    r = subprocess.run(["node", str(RUNNER.with_name("crit_ratio.js")), str(SIM)],
                       input=json.dumps(case), capture_output=True, text=True, check=True,
                       timeout=120)  # fmt: skip
    out = json.loads(r.stdout)
    if out["error"]:
        raise RuntimeError(out["error"])
    return out["accuracy"]


def showdown_rate(p1, p2, turns, line: str, n: int = 400) -> float:
    """The share of n simulator seeds where ``line`` (a substring) appears in the last turn's
    protocol (``chance_count.js``): Showdown's chance of an event one battle cannot show."""
    case = {"p1": p1, "p2": p2, "turns": [list(t) for t in turns], "line": line, "n": n}
    r = subprocess.run(["node", str(RUNNER.with_name("chance_count.js")), str(SIM)],
                       input=json.dumps(case), capture_output=True, text=True, check=True,
                       timeout=600)  # fmt: skip
    out = json.loads(r.stdout)
    if out["error"]:
        raise RuntimeError(out["error"])
    return out["hits"] / out["n"]


def showdown_log_counts(p1, p2, turns, n: int = 1000) -> list[list[str]]:
    """The last turn's protocol lines of n simulator seeds (``chance_count.js`` with ``lines``):
    for chances that depend on each other (the crits of a multi-hit move)."""
    case = {"p1": p1, "p2": p2, "turns": [list(t) for t in turns], "line": "", "n": n,
            "lines": True}  # fmt: skip
    r = subprocess.run(["node", str(RUNNER.with_name("chance_count.js")), str(SIM)],
                       input=json.dumps(case), capture_output=True, text=True, check=True,
                       timeout=600)  # fmt: skip
    out = json.loads(r.stdout)
    if out["error"]:
        raise RuntimeError(out["error"])
    return out["logs"]
