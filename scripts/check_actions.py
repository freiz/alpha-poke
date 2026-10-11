"""Self-play integrity check: every recorded decision (the searched option the player chose,
``names[slot]``) against what the server applied, from the game's protocol log (2026-10-11).

Per decision (side, turn, kind) of a game, the side's events in that turn's block of the log:
  main (turn start): the side's first action line -- a move (``|move|``, not called by another
    move), a switch without ``[from]``, or ``|cant|`` (it could not act: sleep, flinch, ...), or
    nothing (fainted first);
  forced / pivot (switch requests mid-turn): a switch of the side in the block (any).
Tera: a chosen ``-tera`` option needs the side's ``|-terastallize|`` in the block, a plain one
must not have it. Reported by category, with examples.

  uv run python scripts/check_actions.py --gen 5 --games 1000
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

KIND_MAIN, KIND_FORCED, KIND_PIVOT = 0, 1, 2


def to_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def blocks(log: str) -> dict[int, list[str]]:
    """Protocol lines by turn: block T = from ``|turn|T`` to the next ``|turn|`` (block 0: the
    lead switches)."""
    out: dict[int, list[str]] = defaultdict(list)
    t = 0
    for line in log.split("\n"):
        if line.startswith("|turn|"):
            t = int(line.split("|")[2])
            continue
        out[t].append(line)
    return out


def side_events(lines: list[str], side: str) -> dict:
    """The side's main action, its switches (species ids, in order), whether it terastallized,
    and whether its first switch-in shows Illusion / Transform afterwards."""
    main, switches, tera = None, [], False
    flags = set()  # why an action may differ or be missing: fainted, encore, eject, ended
    over = False  # the side's turn-start action can no longer come (it fainted, or upkeep)
    for line in lines:
        p = line.split("|")
        if line == "|upkeep":
            over = True
        if line.startswith(("|win|", "|tie")):
            flags.add("ended")
        if len(p) < 3 or not p[2].startswith(side):
            continue
        tag = p[1]
        if tag == "faint":
            over = True
            flags.add("fainted")
        if tag == "-start" and len(p) > 3 and p[3] == "Encore" and main is None:
            flags.add("encore")
        if tag == "-enditem" and len(p) > 3 and p[3] in ("Eject Button", "Eject Pack", "Red Card"):
            flags.add("eject")
        if tag == "-activate" and len(p) > 3 and p[3] == "confusion" and main is None:
            flags.add("confusion")  # may hit itself: no move line
        if tag == "drag" or (tag == "-activate" and "Emergency Exit" in line):
            flags.add("eject")
        if tag == "-terastallize":
            tera = True
        elif tag == "move" and main is None and not over and "[from]" not in line:
            main = ("move", to_id(p[3]))
        elif tag == "cant" and main is None and not over:
            main = ("cant", to_id(p[3]) if len(p) > 3 else "")
        elif tag in ("switch", "drag"):
            sp = to_id(p[3].split(",")[0])
            if main is None and not over and tag == "switch" and "[from]" not in line:
                main = ("switch", sp)
            else:
                switches.append(sp)
    return {"main": main, "switches": switches, "tera": tera, "flags": sorted(flags)}


def check_game(log: str, decisions: list[dict], out: Counter, examples: dict) -> None:
    bl = blocks(log)
    by_turn = {t: {s: side_events(lines, s) for s in ("p1a", "p2a")} for t, lines in bl.items()}
    illusion = "Illusion" in log or "-transform" in log
    for d in decisions:
        name = d["names"][d["slot"]]
        ev = by_turn.get(d["turn"], {}).get(d["side"] + "a")
        if ev is None:
            out["no log block"] += 1
            continue
        if d["kind"] == KIND_MAIN:
            got = ev["main"]
            if name.startswith("switch "):
                want = ("switch", name.split(" ", 1)[1])
            else:
                want = ("move", name.removesuffix("-tera"))
            fl = ev["flags"]
            if got is None:
                key = ("main: no action: fainted first" if "fainted" in fl else
                       "main: no action: forced out first (Eject / Red Card / phazing)"
                       if "eject" in fl or ev["switches"] else
                       "main: no action: the game ended first" if "ended" in fl else
                       "main: no action: hurt itself in confusion" if "confusion" in fl else
                       "main: no action: UNEXPLAINED")  # fmt: skip
            elif got[0] == "cant":
                key = "main: could not act (cant)"
            elif got == want:
                key = "main: ok"
            elif got[0] == want[0] == "switch" and illusion:
                key = "main: switch differs (Illusion / Transform game)"
            elif got[0] == "move" == want[0] and "encore" in fl:
                key = "main: other move (Encore applied first)"
            elif got[0] == "switch" and want[0] == "move" and "eject" in fl:
                key = "main: forced out first (Eject / Red Card)"
            else:
                key = f"main: MISMATCH {want[0]} -> {got[0]}"
            if want[0] == "move" and got and got[0] != "cant":
                if name.endswith("-tera") and not ev["tera"]:
                    key = "main: MISMATCH tera chosen, not applied"
                elif not name.endswith("-tera") and ev["tera"]:
                    key = "main: MISMATCH tera applied, not chosen"
        else:
            sp = name.split(" ", 1)[1] if name.startswith("switch ") else name
            later = ev["switches"] + ([ev["main"][1]] if ev["main"] and ev["main"][0] == "switch"
                                      else [])  # fmt: skip
            key = ("forced/pivot: ok" if sp in later else
                   "forced/pivot: switch differs (Illusion / Transform game)" if illusion else
                   "forced/pivot: MISMATCH")  # fmt: skip
        out[key] += 1
        if ("MISMATCH" in key or "UNEXPLAINED" in key) and len(examples[key]) < 8:
            examples[key].append({"battle": d["battle"], "side": d["side"], "turn": d["turn"],
                                  "kind": d["kind"], "chosen": name,
                                  "log": ev})  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--games", type=int, default=1000, help="games per worker file")
    ap.add_argument("--workers", default="0", help="worker files (comma-separated)")
    a = ap.parse_args()
    d = Path(f"data/selfplay/gen{a.gen}")
    out: Counter = Counter()
    examples: dict = defaultdict(list)
    for w in a.workers.split(","):
        logs = {}
        with open(d / f"logs-w{w}.jsonl") as f:
            for line in f:
                g = json.loads(line)
                logs[g["pair"]] = (g["battle"], g["log"])
                if len(logs) >= a.games:
                    break
        decs: dict = defaultdict(list)
        with open(d / f"decisions-w{w}.jsonl") as f:
            for line in f:
                r = json.loads(line)
                if r["game"] in logs:
                    decs[r["game"]].append({k: r[k] for k in ("side", "turn", "kind", "slot",
                                                              "names")})  # fmt: skip
                elif len(decs) >= len(logs):
                    break
        for game, (battle, log) in logs.items():
            ds = decs.get(game, [])
            for x in ds:
                x["battle"] = battle
            check_game(log, ds, out, examples)
    total = sum(out.values())
    for k, v in sorted(out.items()):
        print(f"{v:8d}  {v / total:7.3%}  {k}")
    for k, ex in examples.items():
        print("\n==", k)
        for e in ex:
            print(json.dumps(e))


if __name__ == "__main__":
    main()
