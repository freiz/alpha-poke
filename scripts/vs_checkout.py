"""Regression test: our current bot vs the same (or another) bot from an older commit.

  uv run python scripts/vs_checkout.py k_llmplan --rev e623827 --pairs 20 --lanes 4

The old commit is checked out once into external/rev-<rev> (a git worktree, git-ignored) with its
data/ and .env symlinked to ours (belief model, cached LLM plans: no new LLM cost for already-cached
plans). It runs as a separate process (scripts/serve_bot.py with PYTHONPATH=<worktree>/src).
"""

import argparse
import json
import subprocess
from pathlib import Path

from alpha_poke.eval.bots import BOT_NAMES
from alpha_poke.eval.external import ROOT, run_external
from alpha_poke.teams import DEFAULT_POOL


def ensure_worktree(rev: str) -> Path:
    path = ROOT / "external" / f"rev-{rev}"
    if not path.exists():
        subprocess.run(["git", "worktree", "add", "--detach", str(path), rev], cwd=ROOT, check=True)
    data = path / "data"
    if not data.exists():
        data.symlink_to(ROOT / "data", target_is_directory=True)
    env = path / ".env"  # the old code reads its LLM key from <checkout>/.env (git-ignored)
    if not env.exists() and (ROOT / ".env").exists():
        env.symlink_to(ROOT / ".env")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bot", choices=BOT_NAMES)
    ap.add_argument("--rev", required=True, help="git revision of the opponent")
    ap.add_argument("--opp-bot", default=None, help="variant in the old checkout (default: same)")
    ap.add_argument("--pairs", type=int, default=20)
    ap.add_argument("--pool", default=str(DEFAULT_POOL))
    ap.add_argument("--ports", type=int, nargs="+", default=[8000, 8001, 8002, 8003])
    ap.add_argument("--lanes", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--replays", action="store_true")
    a = ap.parse_args()
    opp = {"kind": "checkout", "path": str(ensure_worktree(a.rev)), "bot": a.opp_bot or a.bot,
           "rev": a.rev}  # fmt: skip
    res = run_external(a.bot, opp, a.pairs, a.pool, tuple(a.ports), a.lanes, a.seed, a.trace,
                       a.replays)  # fmt: skip
    print(f"{a.bot} vs {opp['bot']}@{a.rev}: {res['a_wins']}W {res['ties']}T / {res['games']} = "
          f"{res['win_rate']:.1%}  paired {res['paired_mean']:.1%} ± {res['ci95_paired']:.1%}; "
          f"failed {res['failed_games']}; team mismatches {res['team_mismatches']}; "
          f"{res['seconds']}s")  # fmt: skip
    print(json.dumps({"log": res["log"], "opponent_logs": res["opponent_logs"]}))
