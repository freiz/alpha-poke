"""The causality check of the search's tree (doc/state-diff.md plan B, part 2): below the root
the search extends the history with the steps of its descent (rust ismcts PathCtx: push /
settle); the network was trained on the replays' history (train/positions: the log's steps). On
the state-construction differential's random battles: at each turn start where both sides
chose, the step the tree records for the actual joint action (from Showdown's true state, each
chance outcome of it) against the step the log gives for that turn. The structural fields --
the act's kind, tera, actor, target, prevented, fainted first -- must match one outcome's; the
outcome fields (damage, first, crit, miss, KO) are counted apart: the tree does not fill them.

  uv run python scripts/check_tree_history.py --battles 200 --teams tests/fixtures/random_battle_teams.jsonl
"""

import argparse
import collections
import glob
import json
import multiprocessing as mp
from pathlib import Path

STRUCT = ("kind", "tera", "actor", "target", "prevented", "fainted_first")
OUTCOME = ("dmg", "first", "crit", "miss", "ko")
FIELDS = STRUCT + OUTCOME


def _slots(names: list[str], choice: str) -> int | None:
    choice = "none" if choice == "struggle" else choice
    for i, n in enumerate(names):  # (a switch's engine name is the species: "switch <species>")
        if n in (choice, f"switch {choice}") or (choice == "none" and n == "struggle"):
            return i
    return -1 if choice == "none" else None


def battle(job) -> dict:
    import alpha_search

    from alpha_poke.enginecheck import engine_state, random_battle
    from alpha_poke.enginecheck.statebuild import _fainted_no_status, _flip
    from alpha_poke.replay import parse_replay
    from alpha_poke.train.positions import _step_str, blind_sides, decision_steps

    (stem, seed), p1, p2 = job
    out = {"steps": 0, "struct": collections.Counter(), "outcome": collections.Counter(),
           "examples": [], "errors": [], "skipped": collections.Counter()}  # fmt: skip
    views: dict = {}
    try:
        steps, err = random_battle(p1, p2, f"gen5,{seed},{seed + 1},{seed + 2},{seed + 3}", seed + 1,
                                   max_turns=40, views=views)  # fmt: skip
        rep = parse_replay({"id": f"t{seed}", "log": "\n".join(views["spectator"])})
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"{type(e).__name__}: {e}"[:200])
        return out
    if rep.warnings:
        out["skipped"]["parse warnings"] += 1
        return out
    log_steps = decision_steps(rep.actions, blind_sides(rep))
    # (the battle's last turn when it was won: the moves after the last knockout never come --
    # the engine plays them on; no input comes after it, in training or in the tree)
    won = any(x.startswith("|win|") for x in views["spectator"])
    last = max(log_steps, default=0) if won else None
    for k in range(len(steps) - 1):
        a = steps[k]
        if set(a.get("choices", {})) != {"p1", "p2"} or any(s["request"] != "move" for s in a["state"]["sides"]):
            continue
        turn = a["state"]["turn"]
        if turn == last:
            out["skipped"]["the last turn"] += 1
            continue
        if turn not in log_steps or not log_steps[turn]:
            out["skipped"]["no log step"] += 1
            continue
        try:
            st = engine_state(_fainted_no_status(a["state"]))
            s = st.to_string()
            n1 = alpha_search.slot_names([s])[0]
            n2 = alpha_search.slot_names([_flip(st).to_string()])[0]
            c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
            i1, i2 = _slots(n1, c1), _slots(n2, c2)
            if i1 is None or i2 is None:
                out["skipped"]["choice not a slot"] += 1
                continue
            logged = _step_str(log_steps[turn][0], "p1")
            tree, (l1, l2) = alpha_search.tree_steps(s, i1, i2, logged)
        except BaseException as e:  # noqa: BLE001 - the binding's panics are BaseExceptions
            out["errors"].append(f"{type(e).__name__}: {str(e)[:150]}")
            continue
        out["steps"] += 1
        log = dict(zip(FIELDS, l1, strict=True)), dict(zip(FIELDS, l2, strict=True))
        best = None
        for _, t1, t2, _, _ in tree:
            t = dict(zip(FIELDS, t1, strict=True)), dict(zip(FIELDS, t2, strict=True))
            miss = [f"{sd}.{f}" for sd, x, y in (("one", log[0], t[0]), ("two", log[1], t[1]))
                    for f in STRUCT if x[f] != y[f]]  # fmt: skip
            if best is None or len(miss) < len(best[0]):
                best = (miss, t)
        miss, t = best if best else (["no outcome"], ({}, {}))
        for m in miss:
            out["struct"][m] += 1
        if miss and len(out["examples"]) < 10:
            out["examples"].append((stem, seed, turn, c1, c2, logged, miss))
        for sd, x, y in (("one", log[0], t[0]), ("two", log[1], t[1])):
            for f in OUTCOME:
                if y and x[f] != y[f]:
                    out["outcome"][f"{sd}.{f}"] += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=100)
    ap.add_argument("--teams", default="tests/fixtures/random_battle_teams.jsonl")
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--out", default="data/selfplay/diag/tree_history.json")
    a = ap.parse_args()
    files = sorted({f for t in a.teams.split(",") for f in (glob.glob(t) or [t])})
    jobs = []
    for f in files:
        pairs = [json.loads(x) for x in Path(f).read_text().splitlines()]
        jobs += [((Path(f).stem, a.seed_offset + i), pairs[i % len(pairs)]["p1"], pairs[i % len(pairs)]["p2"])
                 for i in range(a.battles)]  # fmt: skip
    total = 0
    struct: collections.Counter = collections.Counter()
    outcome: collections.Counter = collections.Counter()
    skipped: collections.Counter = collections.Counter()
    examples, errors = [], []
    with mp.get_context("spawn").Pool(a.procs) as pool:
        for r in pool.imap_unordered(battle, jobs):
            total += r["steps"]
            struct.update(r["struct"])
            outcome.update(r["outcome"])
            skipped.update(r["skipped"])
            examples += r["examples"]
            errors += r["errors"]
    bad = sum(1 for e in examples)
    print(f"{len(jobs)} battles, {total} turn steps; structural mismatches by field: {dict(struct)}")
    print(f"  outcome fields the tree leaves out (log != tree): {dict(outcome)}")
    print(f"  skipped {dict(skipped)}; errors {len(errors)} {errors[:3]}")
    for e in examples[:10]:
        print("  e.g.", e)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"battles": len(jobs), "steps": total, "struct": dict(struct),
                                       "outcome": dict(outcome), "skipped": dict(skipped),
                                       "examples": examples, "errors": errors[:50], "bad": bad}, indent=1))


if __name__ == "__main__":
    main()
