"""The full-information engine differential (doc/engine-diff.md): random battles in Showdown's
simulator (real OU team pairs, random legal choices), poke-engine's outcomes of every turn
compared with Showdown's truth -- no player's view, no belief (unlike check_engine_diff.py on
self-play records, where the field came from one player's view).

A turn is compared when it runs from a turn start to the next with no decision in between (a
faint's replacement or a pivot's switch is a decision point the engine stops at: counted apart).
The engine's state is built from Showdown's own numbers (enginecheck.engine_state); the closest
outcome must agree on every discrete field and on HP within the rolls' spread (closest(hp=True)).

  uv run python scripts/check_engine_random.py --battles 300 --procs 8

Report: data/selfplay/diag/engine_random.json (counts per kind, per move pair, examples with
the turn's protocol lines and the engine's outcomes).
"""

import argparse
import collections
import json
import re
import multiprocessing as mp
from pathlib import Path

from alpha_poke import enginecheck as ec
from alpha_poke.selfplay import SELFPLAY_DIR, teams


def kind_of(key: str) -> str:
    """'s1.0.hp' -> 'hp', 's2.boost.def' -> 'boost.def', 's1.volatile.x' -> 'volatile.x'."""
    return re.sub(r"^s[12]\.(\d+\.)?", "", key)


def comparable(steps: list[dict], k: int) -> str | None:
    """Why turn step k cannot be compared with step k + 1 (None: it can)."""
    a, b = steps[k], steps[k + 1]
    if set(a["choices"]) != {"p1", "p2"} or any(
        s["request"] != "move" for s in a["state"]["sides"]
    ):
        return "not a turn start"
    if b["state"]["ended"]:
        return "battle ended"
    if b["state"]["turn"] != a["state"]["turn"] + 1 or any(
        s["request"] != "move" for s in b["state"]["sides"]
    ):
        return "a decision in the turn (faint, pivot)"
    return None


def battle(job: tuple) -> dict:
    i, p1, p2, max_turns = job
    out = {"turns": 0, "match": 0, "skipped": collections.Counter(), "kinds": collections.Counter(),
           "pairs": collections.defaultdict(collections.Counter), "examples": [], "errors": []}  # fmt: skip
    try:
        steps, err = ec.random_battle(p1, p2, f"gen5,{i},{i + 1},{i + 2},{i + 3}", i + 1,
                                      max_turns=max_turns)  # fmt: skip
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"runner: {str(e)[:200]}")
        return out
    if err:
        out["errors"].append(f"showdown: {err.splitlines()[0][:200]}")
    for k in range(len(steps) - 1):
        why = comparable(steps, k)
        if why:
            out["skipped"][why] += 1
            continue
        a, b = steps[k], steps[k + 1]
        c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
        if "struggle" in (c1, c2):  # the engine has no choice for it (no PP left)
            out["skipped"]["struggle"] += 1
            continue
        n = tuple(len(s["mons"]) for s in a["state"]["sides"])
        try:
            outs = ec.engine_outcomes(ec.engine_state(a["state"]), c1, c2)
            res = ec.closest(b["state"], outs, n, hp=True)
        except BaseException as e:  # noqa: BLE001 - the binding's panics are BaseExceptions
            out["errors"].append(f"engine: {c1} | {c2}: {type(e).__name__}: {str(e)[:120]}")
            continue
        out["turns"] += 1
        found = sorted({kind_of(x) for x in res["diff"]})
        if not found:
            out["match"] += 1
            continue
        for f in found:
            out["kinds"][f] += 1
            out["pairs"][f][f"{c1} | {c2}"] += 1
        if len(out["examples"]) < 6:
            log = [x for x in b["state"]["log"] if x.startswith(("|move", "|switch", "|drag",
                   "|-", "|cant", "|faint", "|upkeep", "|turn"))]  # fmt: skip
            out["examples"].append({"battle": i, "turn": a["state"]["turn"], "p1": c1, "p2": c2,
                                    "kinds": found, "diff": {k: list(v) for k, v in res["diff"].items()},
                                    "log": log})  # fmt: skip
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=300)
    ap.add_argument("--teams", default=str(SELFPLAY_DIR / "gen901" / "teams.jsonl"),
                    help="team pairs (selfplay.py teams)")  # fmt: skip
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--out", default="data/selfplay/diag/engine_random.json")
    a = ap.parse_args()
    pairs = teams.load(Path(a.teams))
    jobs = [(i, pairs[i % len(pairs)].p1.text, pairs[i % len(pairs)].p2.text, a.max_turns)
            for i in range(a.battles)]  # fmt: skip
    tot = {"turns": 0, "match": 0}
    skipped, kinds = collections.Counter(), collections.Counter()
    pairs_by_kind: dict = collections.defaultdict(collections.Counter)
    examples: dict = collections.defaultdict(list)
    errors: collections.Counter = collections.Counter()
    # spawn, not fork: a forked worker can inherit a held lock of the extension modules' threads
    with mp.get_context("spawn").Pool(a.procs) as pool:
        for r in pool.imap_unordered(battle, jobs):
            tot["turns"] += r["turns"]
            tot["match"] += r["match"]
            skipped.update(r["skipped"])
            kinds.update(r["kinds"])
            for k, c in r["pairs"].items():
                pairs_by_kind[k].update(c)
            for e in r["examples"]:
                for k in e["kinds"]:
                    if len(examples[k]) < 8:
                        examples[k].append(e)
            errors.update(re.sub(r"\d+", "N", x) for x in r["errors"])
    n = max(tot["turns"], 1)
    print(f"{a.battles} battles, {tot['turns']} compared turns: {tot['match']} match "
          f"({100 * tot['match'] / n:.1f}%); skipped {dict(skipped)}")  # fmt: skip
    for k, c in kinds.most_common(30):
        print(f"  {c:6d} ({100 * c / n:.2f}%)  {k:28s} {pairs_by_kind[k].most_common(3)}")
    for e, c in errors.most_common(10):
        print(f"  error x{c}: {e}")
    rep = {"battles": a.battles, **tot, "skipped": skipped, "kinds": kinds.most_common(),
           "pairs": {k: v.most_common(20) for k, v in pairs_by_kind.items()},
           "examples": examples, "errors": errors.most_common()}  # fmt: skip
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
