"""Reading paired evaluations (scripts/eval_pairs.py logs; 2026-10-31): each run's pair statistics
(score, Elo, normalized Elo, pentanomial, decisive pairs, the SPRT's log-likelihood ratio) and, for
runs on the same pairs against the same opponent, each run against a baseline pair by pair (the
teams' share of the noise taken out: a tighter interval than comparing the two intervals).

  uv run python scripts/eval_stats.py data/selfplay/diag/x_r2-gen0x1_400 data/selfplay/diag/scaling_400 \\
      [--baseline scaling_400] [--elo0 0 --elo1 20]

A path: a run's directory (its .jsonl log) or the log itself; a run is named by its directory.
--luck: runs saved with their replays (eval_pairs --replays) also with each game's luck taken out
(eval.luck: crits, misses, full paralyses -- the same expected score, less variance).
"""

import argparse
import json
from pathlib import Path

from alpha_poke.eval.arena import pair_score_map, pair_stats, paired_difference, read_log, sprt_llr


def log_of(p: str) -> Path:
    p = Path(p)
    return p if p.suffix == ".jsonl" else sorted(p.glob("*.jsonl"))[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument(
        "--baseline", default="", help="the run (its name) the others are compared with"
    )
    ap.add_argument("--elo0", type=float, default=0.0)
    ap.add_argument("--elo1", type=float, default=20.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--luck", action="store_true", help="also with the luck taken out (--replays runs)"
    )
    a = ap.parse_args()
    scores = {}
    for r in a.runs:
        f = log_of(r)
        name = f.parent.name if f.parent.name != "diag" else f.stem
        rows = read_log(str(f))
        scores[name] = pair_score_map(rows)
        rep = f.with_suffix(".replays")
        if a.luck and rep.is_dir():
            from alpha_poke.eval.luck import adjusted_pairs

            adj, fit = adjusted_pairs(rows, rep)
            scores[name + "+luck"] = adj
            if not a.json:
                print(
                    f"{name}: luck fit on {fit['games']} games, theta {fit['theta']}, R2 {fit.get('r2')}"
                )
    out = {}
    for name, m in scores.items():
        st = pair_stats(list(m.values()))
        st["llr"] = round(sprt_llr(list(m.values()), a.elo0, a.elo1), 2)
        out[name] = st
        if not a.json:
            print(f"{name:32} {st['pairs']:4} pairs  score {st['score']:.3f} ± {st['ci95']:.3f}  "
                  f"Elo {st['elo']:+.0f} [{st['elo_ci95'][0]:+.0f}, {st['elo_ci95'][1]:+.0f}]  nElo {st['nelo']:+.0f}  "
                  f"penta {st['pentanomial']}  decisive {st['decisive']:.0%}  LLR({a.elo0:g},{a.elo1:g}) {st['llr']:+.2f}")  # fmt: skip
    if a.baseline:
        base = scores[a.baseline]
        if not a.json:
            print(
                f"\nagainst {a.baseline}, pair by pair (x - baseline; the interval if they were independent):"
            )
        for name, m in scores.items():
            if name == a.baseline:
                continue
            d = paired_difference(m, base)
            out[name]["vs_baseline"] = d
            if not a.json:
                print(
                    f"{name:32} {d['pairs']:4} pairs  diff {d['diff']:+.3f} ± {d['ci95']:.3f}  "
                    f"(independent: ± {d['ci95_if_independent']:.3f})"
                )
    if a.json:
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
