"""The damage calculation differential (doc/engine-diff.md): at every turn start of the random
battles (scripts/check_engine_random.py's, with the damage probe), each active's every damaging
move's max damage (the 100% roll, no crit) in Showdown (its own getDamage, on a copy of the
battle) and in poke-engine (poke_engine.calculate_damage, from Showdown's state).

  uv run python scripts/check_damage_calc.py --battles 300 --procs 8

Report: data/selfplay/diag/damage_calc.json (the share exact / off by 1 / within 2% / beyond,
the cases beyond 2% grouped by move, attacker ability / item, defender ability / item, weather,
terrain, and examples).
"""

import argparse
import collections
import json
import multiprocessing as mp
from pathlib import Path

import poke_engine as pe

from alpha_poke import enginecheck as ec

# the damage depends on the order (Payback, Bolt Beak, ...) or on the turn's events (Assurance,
# Revenge, ...): left out
ORDER = {"payback", "boltbeak", "fishiousrend", "avalanche", "revenge", "assurance", "lashout",
         "ragefist", "retaliate", "stompingtantrum", "temperflare", "focuspunch", "beatup",
         "lastrespects", "counter", "mirrorcoat", "metalburst", "comeuppance", "bide",
         "fling", "naturalgift", "present", "magnitude", "psywave", "spitup",
         # their onTry reads the turn's queue (empty at the probe) or sets a later hit
         "suckerpunch", "thunderclap", "upperhand", "futuresight", "doomdesire", "fakeout",
         "firstimpression",
         # the engine's own damage (calculate_damage_rolls' cases) / the probe's random power
         "endeavor", "ficklebeam"}  # fmt: skip
# the probe's empty queue (Analytic: moving last) and a target out of reach (semi-invulnerable:
# the hit step, not getDamage): left out
QUEUE_ABILITIES = {"analytic"}
SEMI_INVULNERABLE = {"phantomforce", "shadowforce", "dig", "dive", "fly", "bounce"}
# the engine's 0 that Showdown's getDamage does not see (onDamage: Disguise / Ice Face's block,
# a Substitute's): left out
BLOCKERS = {"disguise", "iceface"}


def mon(state: dict, side: int) -> dict:
    s = state["sides"][side]
    return s["mons"][s["active"]]


def battle(job: tuple) -> list[dict]:
    i, p1, p2, max_turns = job
    out = []
    try:
        steps, _ = ec.random_battle(p1, p2, f"gen5,{i},{i + 1},{i + 2},{i + 3}", i + 1,
                                    max_turns=max_turns, damage_probe=True)  # fmt: skip
    except Exception:  # noqa: BLE001
        return out
    for step in steps:
        if "damage" not in step:
            continue
        st = step["state"]
        try:
            e = ec.engine_state(st)
        except BaseException:  # noqa: BLE001
            continue
        for side, sid in ((0, "p1"), (1, "p2")):
            other = mon(st, 1 - side)
            foe_move = other["moves"][0]["id"]
            for move, sd in (step["damage"].get(sid) or {}).items():
                if not isinstance(sd, int) or move in ORDER:
                    continue
                if other["ability"] in BLOCKERS or "substitute" in other["volatiles"]:
                    continue
                if mon(st, side)["ability"] in QUEUE_ABILITIES or SEMI_INVULNERABLE & set(
                    other["volatiles"]
                ):
                    continue
                try:
                    if side == 0:
                        rolls = pe.calculate_damage(e, move, foe_move, True)[0]
                    else:
                        rolls = pe.calculate_damage(e, foe_move, move, False)[1]
                except BaseException as ex:  # noqa: BLE001
                    out.append({"error": f"{move}: {type(ex).__name__} {str(ex)[:80]}"})
                    continue
                eng = rolls[0] if rolls else 0
                a, d = mon(st, side), other
                out.append({"battle": i, "turn": st["turn"], "side": sid, "move": move, "sd": sd,
                            "engine": eng, "attacker": a["species"], "a_ability": a["ability"],
                            "a_item": a["item"], "a_tera": a["terastallized"],
                            "a_status": a["status"], "defender": d["species"],
                            "d_ability": d["ability"], "d_item": d["item"],
                            "d_tera": d["terastallized"], "weather": st["field"]["weather"],
                            "terrain": st["field"]["terrain"],
                            "a_boosts": {k: v for k, v in a["boosts"].items() if v},
                            "d_boosts": {k: v for k, v in d["boosts"].items() if v},
                            "screens": sorted(st["sides"][1 - side]["conditions"])})  # fmt: skip
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=300)
    ap.add_argument("--teams", default="tests/fixtures/random_battle_teams.jsonl")
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--out", default="data/selfplay/diag/damage_calc.json")
    a = ap.parse_args()
    pairs = [json.loads(x) for x in Path(a.teams).read_text().splitlines()]
    jobs = [(i, pairs[i % len(pairs)]["p1"], pairs[i % len(pairs)]["p2"], a.max_turns)
            for i in range(a.battles)]  # fmt: skip
    rows, errors = [], collections.Counter()
    with mp.get_context("spawn").Pool(a.procs) as pool:
        for r in pool.imap_unordered(battle, jobs):
            for x in r:
                if "error" in x:
                    errors[x["error"]] += 1
                else:
                    rows.append(x)
    bands = collections.Counter()
    beyond = []
    for x in rows:
        diff = x["engine"] - x["sd"]
        rel = abs(diff) / max(x["sd"], 1)
        band = ("exact" if diff == 0 else "off by 1" if abs(diff) == 1 else
                "within 2%" if rel <= 0.02 else "beyond 2%")  # fmt: skip
        bands[band] += 1
        if band == "beyond 2%":
            beyond.append(x | {"ratio": round(x["engine"] / max(x["sd"], 1), 3)})
    n = max(len(rows), 1)
    print(f"{len(rows)} (position, move) damages: " + ", ".join(
        f"{b} {c} ({100 * c / n:.1f}%)" for b, c in bands.most_common()))  # fmt: skip
    groups = {}
    for key in ("move", "a_ability", "a_item", "d_ability", "d_item", "weather", "terrain",
                "a_tera", "a_status"):  # fmt: skip
        c = collections.Counter(str(x[key]) for x in beyond)
        groups[key] = c.most_common(15)
        print(f"  {key:10s} {c.most_common(10)}")
    for e, c in errors.most_common(5):
        print(f"  error x{c}: {e}")
    with Path(a.out).with_suffix(".rows.jsonl").open("w") as f:  # every case, for analysis
        for x in rows:
            f.write(json.dumps(x) + "\n")
    Path(a.out).write_text(json.dumps({"bands": bands, "groups": groups, "beyond": beyond,
                                       "errors": errors.most_common()}, indent=1))  # fmt: skip


if __name__ == "__main__":
    main()
