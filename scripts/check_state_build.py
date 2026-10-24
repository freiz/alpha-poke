"""The state-construction differential (enginecheck/statebuild.py): random battles of the engine
differential's team pairs, at every decision our engine state from the player's view (poke-env
from its protocol lines and request, build_state) against the one from Showdown's own state.
--belief: the opponent's hidden parts sampled by the belief (default: their true sets, so a
difference is the construction's). Report by kind with examples, like check_engine_random.

  uv run python scripts/check_state_build.py --battles 200 --teams tests/fixtures/random_battle_teams.jsonl
"""

import argparse
import collections
import json
import multiprocessing as mp
from pathlib import Path


# the fields whose difference is in a core part of the state (doc/state-diff.md: HP, status,
# stages, moves and PP, item, ability, the active, the field, the conditions, the flags)
CORE = ("hp", "maxhp", "status", "boost", "active", "team", "moves", "pp", "item", "ability",
        "base_ability", "attack", "defense", "special_attack", "special_defense", "speed",
        "terastallized", "tera_type", "condition", "field", "disabled", "volatile:substitute",
        "force_switch", "transform_backup", "tera_used")  # fmt: skip


def core(kind: str) -> bool:
    rest = kind.split(":", 1)[1]
    return any(rest == c or rest.startswith(c + ":") or rest.startswith(c) for c in CORE) and not rest.startswith("last_item")


def battle(job) -> dict:
    from alpha_poke.enginecheck.statebuild import battle_diffs

    i, p1, p2, max_turns, oracle = job
    try:
        diffs, stats = battle_diffs(p1, p2, seed=i[1], max_turns=max_turns, oracle=oracle)
    except Exception as e:  # noqa: BLE001
        return {"i": i, "diffs": [], "decisions": 0, "errors": [f"{type(e).__name__}: {e}"[:200]]}
    return {"i": i, "diffs": diffs, "decisions": stats["decisions"], "errors": stats["errors"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--battles", type=int, default=100)
    ap.add_argument("--teams", default="tests/fixtures/random_battle_teams.jsonl",
                    help="team pairs (one {p1, p2} per line); several, comma-separated or a glob")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--belief", action="store_true", help="the belief's samples, not the true sets")
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--out", default="data/selfplay/diag/state_build.json")
    a = ap.parse_args()
    import glob

    files = sorted({f for t in a.teams.split(",") for f in (glob.glob(t) or [t])})
    jobs = []
    for f in files:  # (a.battles from each file; the job id: the file and the seed)
        pairs = [json.loads(x) for x in Path(f).read_text().splitlines()]
        jobs += [((Path(f).stem, a.seed_offset + i), pairs[i % len(pairs)]["p1"],
                  pairs[i % len(pairs)]["p2"], a.max_turns, not a.belief) for i in range(a.battles)]  # fmt: skip
    kinds: collections.Counter = collections.Counter()
    battles_by_kind: dict = collections.defaultdict(set)
    examples: dict = {}
    errors: collections.Counter = collections.Counter()
    decisions = bad_dec = core_dec = 0
    with mp.get_context("spawn").Pool(a.procs) as pool:
        for r in pool.imap_unordered(battle, jobs):
            decisions += r["decisions"]
            per: dict = collections.defaultdict(set)
            for k, side, kind, _ in r["diffs"]:
                per[(k, side)].add(kind)
            bad_dec += len(per)
            core_dec += sum(any(core(x) for x in v) for v in per.values())
            errors.update(e[:80] for e in r["errors"])
            for e in r["errors"]:
                examples.setdefault("error", []).append((r["i"], -1, "", e[:300]))
            for k, side, kind, detail in r["diffs"]:
                kinds[kind] += 1
                battles_by_kind[kind].add(r["i"])
                examples.setdefault(kind, []).append((r["i"], k, side, detail))
    bad = sum(kinds.values())
    n = max(decisions, 1)
    print(f"{len(jobs)} battles ({len(files)} team files), {decisions} decisions: {bad} differences "
          f"({'oracle' if not a.belief else 'belief'}); decisions with one: {bad_dec} "
          f"({100 * bad_dec / n:.3f}%), in a core field: {core_dec} ({100 * core_dec / n:.3f}%)")  # fmt: skip
    for kind, c in kinds.most_common():
        print(f"  {c:6d}  {kind:36s} in {len(battles_by_kind[kind])} battles, e.g. {examples[kind][0]}")
    for e, c in errors.most_common(10):
        print(f"  error x{c}: {e}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"battles": len(jobs), "teams": files, "decisions": decisions,
                                       "decisions_with": bad_dec, "core_decisions_with": core_dec,
                                       "kinds": dict(kinds), "errors": dict(errors),
                                       "examples": {k: v[:20] for k, v in examples.items()}}, indent=1))


if __name__ == "__main__":
    main()
