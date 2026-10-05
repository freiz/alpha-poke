"""Analyze an arena run: per-game plans, plan execution and per-turn decision traces.

Usage: uv run python scripts/analyze_eval.py data/eval/<run>.jsonl [--side a] [--games 5]

Reads the arena log and, if present, data/eval/traces/<run>/ (written with --trace).
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--side", default="a", choices=["a", "b"])
    ap.add_argument("--games", type=int, default=4, help="games to print in detail")
    a = ap.parse_args()
    log = Path(a.log)
    rows = [json.loads(x) for x in log.read_text().splitlines() if x]
    trace_dir = log.parent / "traces" / log.stem
    bot = rows[0][f"bot_{a.side}"]
    print(f"run {log.stem}: {len(rows)} games, analysing side {a.side} = {bot}\n")

    # ---- plans -----------------------------------------------------------------------
    sources, problems, finals, events = Counter(), Counter(), Counter(), Counter()
    llm_cost = 0.0
    for r in rows:
        p = r.get(f"plan_{a.side}") or {}
        sources[p.get("source")] += 1
        llm = p.get("llm") or {}
        llm_cost += llm.get("cost_usd", 0) or 0
        for x in (llm.get("problems") or []) + ((p.get("exec") or {}).get("problems") or []):
            problems[x.split(":")[0]] += 1
        ex = p.get("exec") or {}
        finals[ex.get("final_phase")] += 1
        for e in ex.get("events") or []:
            events[
                "phase change" if "phase ->" in e else "repair" if "->" in e or "lost" in e else e
            ] += 1
    print("plan sources:", dict(sources), f"| LLM cost in these games ${llm_cost:.3f}")
    print("validation problems (by field):", dict(problems.most_common(10)) or "none")
    print("final phase reached:", dict(finals))
    print("execution events:", dict(events), "\n")

    # ---- traces ------------------------------------------------------------------------
    if not trace_dir.exists():
        print("(no traces; run the arena with --trace)")
        return
    side_prefix = "A" if a.side == "a" else "B"
    per_game = {}
    for f in trace_dir.glob("*.jsonl"):
        battle, user = f.stem.rsplit("_", 1)
        if not user.startswith(side_prefix):
            continue
        per_game[battle] = [json.loads(x) for x in f.read_text().splitlines() if x]
    won = {
        r["battle"]: r["a_won"]
        if a.side == "a"
        else (None if r["a_won"] is None else not r["a_won"])
        for r in rows
    }
    turns = [t for g in per_game.values() for t in g]
    terms, chosen_terms = Counter(), Counter()
    tera_used = 0
    for t in turns:
        for o in t["options"]:
            for k in o["plan"]:
                terms[k] += 1
        best = t["options"][0]
        for k, v in best["plan"].items():
            if v:
                chosen_terms[k] += 1
        tera_used += t["chosen"].endswith("+tera")
    n = max(len(turns), 1)
    print(f"{len(per_game)} traced games, {len(turns)} decisions")
    print(
        f"followed plan (chosen option had a positive plan term): "
        f"{sum(t['followed_plan'] for t in turns) / n:.0%}"
    )
    print(
        f"plan changed the decision vs tactical-only best: "
        f"{sum(t['plan_changed_decision'] for t in turns) / n:.0%}"
    )
    print(
        f"tera used in {tera_used} decisions; rules active in "
        f"{sum(bool(t['rules_active']) for t in turns)} decisions"
    )
    print("plan terms present among top options:", dict(terms.most_common()))
    print("plan terms on the chosen option:", dict(chosen_terms.most_common()), "\n")

    for res in (True, False):
        g = [b for b in per_game if won.get(b) is res]
        ts = [t for b in g for t in per_game[b]]
        if ts:
            print(
                f"{'won' if res else 'lost'} games ({len(g)}): followed plan "
                f"{sum(t['followed_plan'] for t in ts) / len(ts):.0%}, plan changed decision "
                f"{sum(t['plan_changed_decision'] for t in ts) / len(ts):.0%}, "
                f"avg turns {sum(len(per_game[b]) for b in g) / len(g):.0f}"
            )

    # ---- a few games in detail ------------------------------------------------------------
    for r in rows[: a.games]:
        p = r.get(f"plan_{a.side}") or {}
        b = r["battle"]
        print(f"\n=== {b}: {r['team_a']} vs {r['team_b']}, A won={r['a_won']}, {r['turns']} turns")
        print(
            f"plan [{p.get('source')}]: lead={p.get('lead')} wincons={p.get('win_conditions')} "
            f"tera={p.get('tera_target')} pace={p.get('pace')}"
        )
        if (p.get("llm") or {}).get("game_plan"):
            print("  game plan:", p["llm"]["game_plan"])
        ex = p.get("exec") or {}
        print(f"  phases {ex.get('phases')} -> {ex.get('final_phase')}; events {ex.get('events')}")
        for t in per_game.get(b, [])[:12]:
            opts = ", ".join(
                f"{o['a']} {o['total']:+.2f}" + (f"[{','.join(o['plan'])}]" if o["plan"] else "")
                for o in t["options"][:3]
            )
            mark = " *plan*" if t["plan_changed_decision"] else ""
            print(
                f"  T{t['turn']:>2} [{t['phase']}] {t['me']} {t['me_hp']:.0%} vs {t['opp']} "
                f"{t['opp_hp']:.0%}: {t['chosen']}{mark}  | {opts}"
            )


if __name__ == "__main__":
    main()
