"""The turn counters (agents/timers.py) against what the games did next (2026-10-11): at each
turn start the counters are computed from the log so far, then the turn's events are checked:

  rest     a Rest sleeper with rest_turns 1 wakes when it tries to move, with 2-3 it does not
  sleep    other sleep: the wake rate per attempts so far (engine: 0, 1/3, 1/2, 1)
  toxic    the toxic damage at the end of the turn is stage count + 1 (x 1/16 of max HP,
           within the HP display's rounding)
  protect  a protect move after n consecutive ones succeeds at (1/3) ** n
  wish     a pending Wish with 1 turn heals at the end of the turn (if the active is hurt)
  future   a pending Future Sight with 1 turn lands at the end of the turn
  confusion  the snap-out rate per confused attempts so far (engine patch: 0, 1/4, 1/3, 1/2, 1)

  uv run python scripts/check_timers.py --gen 5 --games 3000
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from alpha_poke.agents.timers import PROTECTS, timers
from alpha_poke.analysis.roles import to_id


def hp_frac(field: str) -> float | None:
    """'52/100 tox' -> 0.52 ('0 fnt' -> 0)."""
    v = field.split(" ")[0]
    if "/" not in v:
        return 0.0 if v == "0" else None
    a, b = v.split("/")
    return int(a) / int(b)


def check_game(log: str, out: Counter, rates: dict) -> None:
    lines = [ln.split("|") for ln in log.split("\n")]
    turn_starts = [i for i, p in enumerate(lines) if len(p) > 2 and p[1] == "turn"]
    for k, i in enumerate(turn_starts):
        end = turn_starts[k + 1] if k + 1 < len(turn_starts) else len(lines)
        tms = timers([p for p in lines[: i + 1] if len(p) > 1])
        block = lines[i + 1 : end]
        for side, st in tms.items():
            act = st.active

            def mine(p, tag, side=side):
                return len(p) > 2 and p[1] == tag and p[2].startswith(side + "a")

            # sleep / Rest: did it try to move, and was it still asleep?
            if act in st.sleep:
                attempts, rest = st.sleep[act]
                tried = [p for p in block if mine(p, "cant") or mine(p, "move")]
                if tried:
                    woke = any(mine(p, "-curestatus") and len(p) > 3 and p[3] == "slp"
                               for p in block)  # fmt: skip
                    if rest:
                        want = attempts >= 2
                        out[f"rest: {'wake' if want else 'asleep'} predicted, "
                            f"{'woke' if woke else 'asleep'}"] += 1
                    else:
                        rates["sleep"][min(attempts, 3)].append(woke)
            # toxic: the end-of-turn damage
            if st.status.get(act) == "tox":
                dmg = [p for p in block if mine(p, "-damage") and "[from] psn" in p]
                prev = None
                for p in block:  # the HP just before the poison damage
                    if dmg and p is dmg[0]:
                        break
                    if len(p) > 3 and p[1] in ("-damage", "-heal", "switch", "drag") \
                            and p[2].startswith(side + "a"):  # fmt: skip
                        prev = hp_frac(p[3] if p[1] in ("-damage", "-heal") else p[4])
                if dmg and prev is None:  # no HP change this turn: from the previous blocks
                    for p in reversed(lines[:i]):
                        if len(p) > 3 and p[1] in ("-damage", "-heal", "switch", "drag") \
                                and p[2].startswith(side + "a"):  # fmt: skip
                            prev = hp_frac(p[3] if p[1] in ("-damage", "-heal") else p[4])
                            break
                if dmg and prev is not None:
                    after = hp_frac(dmg[0][3])
                    if after is not None and after > 0:  # (not capped by the HP left)
                        # the damage's stage (Showdown: floor(max HP / 16) x stage; HP percents
                        # of the opponent's side round): the counter's stage + 1
                        ok = abs((prev - after) * 16 - (st.toxic + 1)) < 0.5
                        out[f"toxic damage {'ok' if ok else 'OFF'}"] += 1
                        if not ok and len(rates["toxic_off"]) < 5:
                            rates["toxic_off"].append((st.toxic, prev, after))
            # protect after n consecutive
            used = [p for p in block if mine(p, "move") and to_id(p[3]) in PROTECTS]
            if used and st.protect > 0:
                ok = any(mine(p, "-singleturn") for p in block)
                rates["protect"][min(st.protect, 2)].append(ok)
            # wish due this turn
            if st.wish is not None and st.wish[0] == 1:
                healed = any(len(p) > 2 and p[1] == "-heal" and p[2].startswith(side + "a")
                             and any("Wish" in x for x in p[4:]) for p in block)  # fmt: skip
                full = False
                for p in reversed(lines[:end]):  # at full HP at the end: no heal (no message)
                    if len(p) > 3 and p[1] in ("-damage", "-heal", "switch", "drag") \
                            and p[2].startswith(side + "a"):  # fmt: skip
                        full = hp_frac(p[3] if p[1] in ("-damage", "-heal") else p[4]) == 1
                        break
                fainted = any(mine(p, "faint") for p in block)
                if not full and not fainted:
                    out[f"wish due: {'healed' if healed else 'NOT healed'}"] += 1
            # Future Sight due at the end of this turn: it lands on the other side
            if st.future is not None and st.future[0] == 1:
                other = "p2" if side == "p1" else "p1"
                landed = any(len(p) > 3 and p[1] == "-end" and p[2].startswith(other)
                             and "Future Sight" in p[3] for p in block)  # fmt: skip
                ended = any(len(p) > 1 and p[1] in ("win", "tie") for p in block)
                if not ended:
                    out[f"future sight due: {'landed' if landed else 'NOT landed'}"] += 1
            # confusion: snapped out at this attempt?
            if st.confusion is not None:
                tried = [p for p in block if mine(p, "move") or mine(p, "cant")
                         or (mine(p, "-activate") and to_id(p[3]) == "confusion")]  # fmt: skip
                if tried:
                    ended = any(mine(p, "-end") and to_id(p[3]) == "confusion" for p in block)
                    rates["confusion"][min(st.confusion, 4)].append(ended)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--games", type=int, default=3000)
    ap.add_argument("--workers", default="0,1,2")
    a = ap.parse_args()
    out: Counter = Counter()
    rates: dict = {"sleep": defaultdict(list), "protect": defaultdict(list),
                   "confusion": defaultdict(list), "toxic_off": []}  # fmt: skip
    per = a.games // len(a.workers.split(","))
    for w in a.workers.split(","):
        with open(Path(f"data/selfplay/gen{a.gen}") / f"logs-w{w}.jsonl") as f:
            for n, line in enumerate(f):
                if n >= per:
                    break
                check_game(json.loads(line)["log"], out, rates)
    for k, v in sorted(out.items()):
        print(f"{v:7d}  {k}")
    want = {"sleep": {0: 0, 1: 1 / 3, 2: 1 / 2, 3: 1},
            "protect": {1: 1 / 3, 2: 1 / 9},
            "confusion": {0: 0, 1: 1 / 4, 2: 1 / 3, 3: 1 / 2, 4: 1}}  # fmt: skip
    for kind in ("sleep", "protect", "confusion"):
        for n, xs in sorted(rates[kind].items()):
            print(f"{kind} after {n}: {sum(xs)}/{len(xs)} = {sum(xs) / len(xs):.3f}"
                  f" (engine {want[kind].get(n, float('nan')):.3f})")  # fmt: skip
    if rates["toxic_off"]:
        print("toxic off examples (count, hp before, hp after):", rates["toxic_off"])


if __name__ == "__main__":
    main()
