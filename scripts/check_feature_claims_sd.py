"""The network inputs' claims against Showdown itself (doc/results.md "特征断言检验"; the
engine-based check is scripts/check_feature_claims.py). Random battles of the differential's team
pairs (enginecheck.random_battle), every --every-th decision point serialized; at each, both
views, each claim played out in Showdown from that very battle under the claims' assumptions
(enginecheck/showdown_claims.js: every move hits, nothing by chance, each side's damage rolls /
multi-hit counts fixed): with the claim's rolls -- 'for sure' / 'reliably': the claimant's min,
the other's max; 'possibly': the other way round -- one deterministic battle per claim, so a
'possibly' over several hits is checked too (the engine averages a roll that does not KO).

  ko1 / ko2   the own active's move KOs the foe's active with one / within two uses (the
              target uses Splash: doing nothing), before the turn's end / by the second hit
  first       who moves first (a priority-0 damaging move each; a speed tie left out)
  team        each own benched mon switching in on the foe's active (both with their fixed moves,
              extra.rs duels), reliably / possibly; the actives head-to-head, reliably

Left out: a forced switch pending, an active asleep or frozen (the sleep turns are random).

  uv run python scripts/check_feature_claims_sd.py --battles 100 --every 4

Report: data/selfplay/diag/feature_claims_sd.json and a summary (as check_feature_claims.py)."""

import argparse
import collections
import json
import multiprocessing as mp
from pathlib import Path

import numpy as np

ROUNDS = 4  # (extra.rs ROUNDS)
# the pivots: their user goes out after one use (no second use / exchange to check)
PIVOTS = {"uturn", "voltswitch", "flipturn", "partingshot", "teleport", "chillyreception",
          "shedtail", "batonpass"}  # fmt: skip
NEEDS_FOE_MOVE = {"suckerpunch", "thunderclap", "upperhand", "focuspunch", "counter", "mirrorcoat",
                  "metalburst", "comeuppance", "bide"}  # fmt: skip
PLAIN: set[str] = set()


def _init():
    import alpha_search as A

    for row in A.engine_data()[0]:
        name, cat, power, prio, flags = row[0].lower(), row[3], float(row[4]), int(row[5]), row[-1]
        if cat != "Status" and power > 0 and prio == 0 and "heal" not in flags and name != "grassyglide":
            PLAIN.add(name)


def _orient(own: str, mine: str, theirs: str) -> list[str]:
    return [mine, theirs] if own == "p1" else [theirs, mine]


def check_battle(job) -> list[dict]:
    import alpha_search as A

    from alpha_poke import enginecheck as ec

    i, p1, p2, every, max_turns = job
    d = A.feature_dims()
    EE, EN = d["ent_extra"], d["ent_new"]
    try:
        steps, _ = ec.random_battle(p1, p2, f"gen5,{i},{i + 1},{i + 2},{i + 3}", i + 1,
                                    max_turns=max_turns, serialize_every=every)  # fmt: skip
    except Exception:  # noqa: BLE001
        return []
    out = []
    for step in steps:
        if "battle" not in step:
            continue
        st = step["state"]
        if any(s["active"] < 0 or s["mons"][s["active"]]["hp"] <= 0 for s in st["sides"]):
            continue
        if any(s["mons"][s["active"]].get("status") in ("slp", "frz") for s in st["sides"]):
            continue
        try:
            line = ec.engine_state(st).to_string()
        except BaseException:  # noqa: BLE001
            continue
        cases, claims = [], []
        for flip in (False, True):
            own, foe = ("p1", "p2") if not flip else ("p2", "p1")
            so, sf = st["sides"][0 if not flip else 1], st["sides"][1 if not flip else 0]
            a, b = so["active"], sf["active"]
            me, them = so["mons"][a], sf["mons"][b]
            e, g, n = A.featurize_extra_full([line], flip)
            ent = np.frombuffer(e, "<f4").reshape(12, EE)
            glob = np.frombuffer(g, "<f4")
            new = np.frombuffer(n, "<f4").reshape(12, EN)
            mech = [me.get("ability", ""), me.get("item", ""), them.get("ability", ""), them.get("item", "")]

            def add(kind, claim, case, judge, ctx, unknown=False):
                claims.append({"kind": kind, "claim": bool(claim), "unknown": unknown,
                               "case": len(cases), "judge": judge, "ctx": ctx})  # fmt: skip
                cases.append({"battle": step["battle"], **case})

            for k, m in enumerate(me["moves"][:4]):
                mv = m["id"]
                if ent[a, 4 + 4 * k] <= 0 or mv in NEEDS_FOE_MOVE or m.get("disabled"):
                    continue
                ctx = {"move": mv, "flip": flip, "mech": mech, "foe": them["species"]}
                for sure, rolls in ((True, {own: "min", foe: "max"}), (False, {own: "max", foe: "min"})):
                    turns = [_orient(own, f"move {mv}", "move splash")] * 2
                    case = {"rolls": rolls, "noop": foe, "turns": turns}
                    add("ko1_sure" if sure else "ko1_possible", ent[a, 4 + 4 * k + (1 if sure else 2)],
                        case, ("ko1", foe, str(b)), ctx)  # fmt: skip
                    if mv not in PIVOTS:
                        add("ko2_sure" if sure else "ko2_possible", new[a, 2 * k + (0 if sure else 1)],
                            case, ("ko2", foe, str(b)), ctx)  # fmt: skip
            # who moves first
            mine = next((m["id"] for m in me["moves"] if m["id"] in PLAIN and not m.get("disabled")), None)
            theirs = next((m["id"] for m in them["moves"] if m["id"] in PLAIN and not m.get("disabled")), None)
            if mine and theirs and glob[16] != 0:
                case = {"rolls": {"p1": "max", "p2": "max"}, "noop": None,
                        "turns": [_orient(own, f"move {mine}", f"move {theirs}")]}  # fmt: skip
                add("first", glob[16] > 0, case, ("first", own), {"moves": [mine, theirs], "flip": flip, "mech": mech})
            # team: own mons on the foe's active
            for s_, j, k, mj, mk, res in A.duels_debug(line, flip):
                if s_ != 0 or k != b or mj < 0:
                    continue
                res = list(res)
                pj = so["mons"][j]
                mjn = pj["moves"][mj]["id"]
                mkn = them["moves"][mk]["id"] if mk >= 0 else None
                if mkn is None or pj["hp"] <= 0:
                    continue
                ctx = {"mon": pj["species"], "moves": [mjn, mkn], "flip": flip,
                       "mech": [pj.get("ability", ""), pj.get("item", ""), mech[2], mech[3]]}  # fmt: skip
                rounds = [_orient(own, f"move {mjn}", f"move {mkn}")] * ROUNDS
                if j == a:
                    case = {"rolls": {own: "min", foe: "max"}, "noop": None, "turns": rounds}
                    add("team_head_to_head", res[2] == 0, case, ("fight", own, str(j), foe, str(b), True),
                        ctx, res[2] == 2)  # fmt: skip
                    continue
                if pj.get("status") in ("slp", "frz"):
                    continue
                entry = [_orient(own, f"switch {j}", f"move {mkn}")]
                for kind, code, sure in (("team_switch_in", res[0], True), ("team_switch_in_possible", res[1], False)):
                    rolls = {own: "min", foe: "max"} if sure else {own: "max", foe: "min"}
                    case = {"rolls": rolls, "noop": None, "turns": entry + rounds}
                    add(kind, code == 0, case, ("fight", own, str(j), foe, str(b), sure), ctx, code == 2)
        if not cases:
            continue
        try:
            runs = ec.showdown_claims(cases)
        except Exception:  # noqa: BLE001
            continue
        for c in claims:
            r = runs[c["case"]]
            if r["error"] or not r["turns"]:
                continue
            truth = _judge(c["judge"], r["turns"])
            if truth is None:
                continue
            out.append({"kind": c["kind"], "claim": c["claim"], "truth": truth, "unknown": c["unknown"],
                        "ctx": c["ctx"], "battle": i, "turn": st["turn"]})  # fmt: skip
    return out


def _judge(j, turns):
    """The claim's outcome in Showdown's turns: True / False (None: not decided -- a speed tie)."""
    kind = j[0]
    if kind == "ko1":
        _, foe, sp = j
        return turns[0]["hp_moves"][foe].get(sp, 1) <= 0
    if kind == "ko2":
        _, foe, sp = j
        if turns[0]["hp"][foe].get(sp, 1) <= 0:
            return True
        return len(turns) > 1 and turns[1]["hp_moves"][foe].get(sp, 1) <= 0
    if kind == "first":
        _, own = j
        return bool(turns[0]["moves"]) and turns[0]["moves"][0] == own
    # an exchange: won when the foe's mon is down first ('sure': both down at once is lost)
    _, own, mine, foe, theirs, sure = j
    for t in turns:
        a, b = t["hp"][own].get(mine, 0) <= 0, t["hp"][foe].get(theirs, 0) <= 0
        if a or b:
            return (b and not a) or (a and b and not sure)
    return False


def verdict(r: dict) -> str:
    if r["unknown"]:
        return "unknown"
    c, t, k = r["claim"], r["truth"], r["kind"]
    if c == t:
        return "ok"
    sure = k.endswith("_sure") or k in ("team_switch_in", "team_head_to_head", "first")
    if c:
        return "wrong"
    return "missed" if sure and k != "first" else "wrong"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=100)
    ap.add_argument("--teams", default="tests/fixtures/random_battle_teams.jsonl")
    ap.add_argument("--every", type=int, default=4)
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--out", default="data/selfplay/diag/feature_claims_sd.json")
    a = ap.parse_args()
    pairs = [json.loads(x) for x in Path(a.teams).read_text().splitlines()]
    jobs = [(i, pairs[i % len(pairs)]["p1"], pairs[i % len(pairs)]["p2"], a.every, a.max_turns)
            for i in range(a.battles)]  # fmt: skip
    stats = collections.defaultdict(collections.Counter)
    blame = collections.defaultdict(collections.Counter)
    seen = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    with mp.Pool(a.procs, initializer=_init) as pool:
        for rows in pool.imap_unordered(check_battle, jobs):
            for r in rows:
                v = verdict(r)
                stats[r["kind"]][v] += 1
                keys = [f"move:{m}" for m in r["ctx"].get("moves") or [r["ctx"].get("move")] if m]
                keys += [x for x in r["ctx"].get("mech", []) if x]
                for key in set(keys):
                    seen[r["kind"]][key] += 1
                    if v in ("wrong", "missed"):
                        blame[(r["kind"], v)][key] += 1
                if v in ("wrong", "missed") and len(examples[(r["kind"], v)]) < 25:
                    examples[(r["kind"], v)].append(r)
    breakdown = {
        f"{k}/{v}": [{"key": key, "count": x, "checked": seen[k][key]} for key, x in c.most_common(15)]
        for (k, v), c in blame.items()
    }
    report = {"battles": a.battles, "claims": {k: dict(c) for k, c in sorted(stats.items())},
              "breakdown": breakdown, "examples": {f"{k}/{v}": x for (k, v), x in examples.items()}}  # fmt: skip
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1))
    print(f"{a.battles} battles -> {a.out}")
    for k, c in sorted(stats.items()):
        n = sum(c.values())
        print(f"  {k:24s} {n:6d} checked  wrong {c['wrong'] / n:6.2%}  missed {c['missed'] / n:6.2%}"
              f"  unknown {c['unknown'] / n:6.2%}")  # fmt: skip
    for key, rows in sorted(breakdown.items()):
        print(f"    {key}: " + ", ".join(f"{r['key']} {r['count']}/{r['checked']}" for r in rows[:6]))


if __name__ == "__main__":
    main()
