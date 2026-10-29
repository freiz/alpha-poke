"""Paired evaluation on a pool of fixed team pairs (``pair<k>_a.txt`` / ``pair<k>_b.txt``, e.g.
data/derived/teams/pools/wide200: real-game pairs drawn like self-play's), each pair played twice with
the teams exchanged. Networks: ALPHA_MODEL_A / ALPHA_MODEL_B with the bots of eval.bots.

  ALPHA_MODEL_A=<run> ALPHA_MODEL_B=<run> uv run python scripts/eval_pairs.py g_ma g_mb \\
      --pool data/derived/teams/pools/wide200
"""

import argparse
import json
import re
import time
from pathlib import Path

from alpha_poke import paths  # noqa: E402
from alpha_poke.eval.arena import Match, run_schedule, summarize

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bot_a")
    ap.add_argument("bot_b")
    ap.add_argument("--pool", default=str(paths.pool("wide200")))
    ap.add_argument("--pairs", type=int, default=0, help="the first N pairs (0: all)")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--lanes", type=int, default=12)
    ap.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    ap.add_argument("--log-dir", default="data/selfplay/diag")
    # (bot B in another checkout, its own code and engine: alpha_poke.eval.split -- an A/B of two
    # versions; its .venv built there)
    ap.add_argument(
        "--other", default="", help="a checkout running bot B (scripts/eval_pairs_opponent.py)"
    )
    ap.add_argument("--run", default="r", help="a short tag in the split run's player names")
    a = ap.parse_args()
    ks = sorted({int(m.group(1)) for f in Path(a.pool).glob("pair*_a.txt")
                 if (m := re.match(r"pair(\d+)_a", f.stem))})  # fmt: skip
    if a.pairs:
        ks = ks[: a.pairs]
    schedule = []
    for k in ks:
        x, y = f"pair{k:03d}_a", f"pair{k:03d}_b"
        schedule += [Match(k, 0, x, y, k % 2 == 0), Match(k, 1, y, x, k % 2 == 1)]
    Path(a.log_dir).mkdir(parents=True, exist_ok=True)
    log = str(Path(a.log_dir) / f"{time.strftime('%Y%m%d-%H%M%S')}_{a.bot_a}_vs_{a.bot_b}_"
              f"{Path(a.pool).name}.jsonl")  # fmt: skip
    if a.other:
        from alpha_poke.eval.split import run_split

        rows = run_split(a.bot_a, a.bot_b, schedule, a.pool, a.pairs, log, a.other, ports=tuple(a.ports),
                         procs=a.procs, lanes_per_proc=a.lanes, run=a.run)  # fmt: skip
    else:
        rows = run_schedule(a.bot_a, a.bot_b, schedule, a.pool, log, ports=tuple(a.ports),
                            procs=a.procs, lanes_per_proc=a.lanes)  # fmt: skip
    print("SUMMARY", json.dumps(summarize(rows) | {"log": log}))
