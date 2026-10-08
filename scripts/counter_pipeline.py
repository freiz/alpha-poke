"""Choose teams against one specific opponent, end to end (design D5-O). Public data only;
the simulations run on local servers.

  uv run python scripts/counter_pipeline.py <user> [options]

Steps (each one is the corresponding script, run as a subprocess with the same options):
  1. scripts/player.py fetch <user>   their public replays (skipped with --skip-fetch)
  2. scripts/player.py play <user>    fit the opponent model (rating input, temperature)
  3. scripts/counter_team.py, stage 1 candidates from the catalog by the matchup model; both
                                      sides the policy model ("pol", fitted rating / tau),
                                      successive halving (cheap: no search)
  4. scripts/counter_team.py, stage 2 the --finalists best of stage 1, both sides the search bot
                                      (s_ismcts_glu, --search-ms per move), dropping candidates
                                      significantly worse than the leader each round
  5. export                           the --export best -> data/players/<user id>/counter/
                                      (scripts/play_public.py --pool / --team, see there)

A previous run's simulation directory is moved to sim-<time> first (the game log maps team
names to that run's candidates). Lightweight by default: --procs 2 x --lanes 2 games at once in
stage 1, --procs 2 x 1 in stage 2 (two searches per game), all at low priority (nice 10).
"""

import argparse
import json
import os
import subprocess
import sys
import time

from alpha_poke.analysis.roles import to_id
from alpha_poke.players import PLAYERS_DIR


def run(cmd: list[str], env: dict | None = None) -> None:
    print("$", " ".join(cmd), flush=True)
    full = ["nice", "-n", "10", sys.executable, *cmd]
    subprocess.run(full, check=True, env={**os.environ, **(env or {})})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("user")
    ap.add_argument("--fmt", default="gen9ou")
    ap.add_argument("--skip-fetch", action="store_true", help="use the replays already fetched")
    ap.add_argument("--k", type=int, default=12, help="candidates from the matchup model")
    ap.add_argument("--his", type=int, default=8, help="their teams to play against")
    ap.add_argument("--half-life", type=float, default=5.0, help="their team weights, in games")
    ap.add_argument("--stage1-games", type=int, default=40, help="per candidate, first round")
    ap.add_argument("--stage1-rounds", type=int, default=3)
    ap.add_argument("--finalists", type=int, default=3)
    ap.add_argument("--stage2-games", type=int, default=20, help="per finalist, first round")
    ap.add_argument("--stage2-rounds", type=int, default=4)
    ap.add_argument("--search-ms", type=int, default=200, help="stage 2 search time per move")
    ap.add_argument("--export", type=int, default=2, help="best teams in the output pool")
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--lanes", type=int, default=2, help="stage 1 games per process")
    ap.add_argument("--ports", type=int, nargs="+", default=[8000, 8001])
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    uid = to_id(a.user)
    t0 = time.time()

    if not a.skip_fetch:
        run(["scripts/player.py", "fetch", a.user, "--fmt", a.fmt])
    run(["scripts/player.py", "play", a.user, "--fmt", a.fmt])

    sim = PLAYERS_DIR / uid / "sim"
    if sim.exists():
        sim.rename(sim.with_name(f"sim-{time.strftime('%Y%m%d-%H%M%S')}"))
    common = ["scripts/counter_team.py", a.user, "--k", str(a.k), "--his", str(a.his),
              "--half-life", str(a.half_life), "--procs", str(a.procs), "--seed", str(a.seed),
              "--ports", *map(str, a.ports), "--export", str(a.export)]  # fmt: skip
    # stage 1: equal pilots, the policy model of the opponent on both sides
    run([*common, "--bot", "pol", "--opp-bot", "pol", "--keep", "half",
         "--first", str(a.stage1_games), "--rounds", str(a.stage1_rounds),
         "--lanes", str(a.lanes)])  # fmt: skip
    res = json.loads((sim / "result_pol.json").read_text())["win_rates"]
    # the finalists: the candidates that lasted longest (most games), then the best win rate
    finalists = sorted(res, key=lambda c: (-res[c][1], -res[c][0]))[: a.finalists]
    print("stage 1 finalists:", ", ".join(f"{c} {res[c][0]:.1%} ({res[c][1]})" for c in finalists))
    # stage 2: the search bot on both sides; ends with the export
    run([*common, "--bot", "s_ismcts_glu", "--opp-bot", "s_ismcts_glu", "--keep", "significant",
         "--only", ",".join(finalists), "--first", str(a.stage2_games),
         "--rounds", str(a.stage2_rounds), "--lanes", "1"],
        env={"ALPHA_SEARCH_MS": str(a.search_ms)})  # fmt: skip

    out = PLAYERS_DIR / uid / "counter"
    meta = json.loads((out / "meta.json").read_text())
    print(f"\ndone in {(time.time() - t0) / 60:.0f} min; pool: {out}")
    for i, t in enumerate(meta["teams"]):
        print(f"  team_{i:02d}: {t['win_rate']:.1%} ({t['games']} games) {t['key']}")
    print(f"play: uv run python scripts/play_public.py --public --opponent {a.user} "
          f"--team {out / 'team_00.txt'}   (or --pool {out})")  # fmt: skip


if __name__ == "__main__":
    main()
