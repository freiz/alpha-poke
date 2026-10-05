"""Paired evaluation against Foul Play running as a separate process (local server only).

Each *lane* = one Foul Play process + one of our bots, playing a fixed sequence of matches:
  * our side switches team with ``update_team`` before every match;
  * Foul Play gets a ``--team-list`` file with its teams in the same order (it loads the next
    team before every battle), so the paired schedule (teams exchanged within a pair) holds;
  * challenger role alternates by lane: even lanes -> we challenge (Foul Play accept_challenge),
    odd lanes -> Foul Play challenges us (challenge_user) and we accept.
Foul Play runs with FP_OFFLINE=1 (it can never download anything) against ws://localhost.
Per-game rows go to the usual arena JSONL; Foul Play's own logs are kept per lane.
"""

import asyncio
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from alpha_poke.eval.arena import _base, _species, make_schedule, summarize
from alpha_poke.teams import load_team_files

ROOT = Path(__file__).resolve().parents[3]
FP = ROOT / "external" / "foul-play"
FP_TEAMS = FP / "fp" / "teams" / "teams" / "alphapoke"


def _install_teams(pool_dir: str) -> dict[str, str]:
    """Copy the pool's Showdown-export files where Foul Play can load them."""
    dst = FP_TEAMS / Path(pool_dir).name
    dst.mkdir(parents=True, exist_ok=True)
    names = {}
    for f in sorted(Path(pool_dir).glob("*.txt")):
        shutil.copy(f, dst / f.stem)
        names[f.stem] = f"alphapoke/{Path(pool_dir).name}/{f.stem}"
    return names


async def _lane(bot, matches, port, pool_dir, lane, log_path, fp_args, extras, run_dir):
    from alpha_poke.eval.bots import make_bot

    teams = load_team_files(pool_dir)
    expected = {k: _species(v) for k, v in teams.items()}
    fp_names = _install_teams(pool_dir)
    tag = f"{os.getpid() % 10000}l{lane}"
    our_name, fp_name = f"ab{tag}", f"fp{tag}"
    we_challenge = lane % 2 == 0
    list_file = FP_TEAMS / "lists" / f"{run_dir.name}_lane{lane}.txt"
    list_file.parent.mkdir(parents=True, exist_ok=True)
    list_file.write_text("\n".join(fp_names[m.team_b] for m in matches) + "\n")

    cmd = [
        str(FP / ".venv" / "bin" / "python"),
        "run.py",
        "--websocket-uri",
        f"ws://localhost:{port}/showdown/websocket",
        "--ps-username",
        fp_name,
        "--pokemon-format",
        "gen9ou",
        "--team-list",
        str(list_file.relative_to(FP / "fp" / "teams" / "teams")),
        "--run-count",
        str(len(matches)),
        "--search-time-ms",
        str(fp_args["search_ms"]),
        "--search-parallelism",
        str(fp_args["parallelism"]),
        "--save-replay",
        "never",
        "--log-level",
        "INFO",
    ]
    cmd += (
        ["--bot-mode", "accept_challenge"]
        if we_challenge
        else ["--bot-mode", "challenge_user", "--user-to-challenge", our_name]
    )
    fp_log = open(run_dir / f"foulplay_lane{lane}.log", "w")
    env = dict(os.environ, FP_OFFLINE="1")
    first = next(iter(teams.values()))
    me = make_bot(bot, our_name, port, first, **extras)
    if not we_challenge:  # we must be logged in before Foul Play starts challenging us
        await asyncio.sleep(3)
    proc = subprocess.Popen(cmd, cwd=FP, stdout=fp_log, stderr=subprocess.STDOUT, env=env)
    rows = []
    try:
        await asyncio.sleep(6)  # Foul Play login + data loading
        for m in matches:
            me.update_team(teams[m.team_a])
            before = set(me.battles)
            if we_challenge:
                await me.send_challenges(fp_name, n_challenges=1)
            else:
                await me.accept_challenges(fp_name, n_challenges=1)
            new = [me.battles[k] for k in me.battles if k not in before]
            battle = new[0] if new else None
            plan = getattr(me, "plans", {}).get(battle.battle_tag) if battle else None
            if plan is not None and plan.exec_state is not None:
                plan.exec_state.observe(battle)
            team_ok = bool(
                battle
                and sorted(_base(p.species) for p in battle.team.values()) == expected[m.team_a]
                and sorted(_base(p.species) for p in battle.teampreview_opponent_team)
                == expected[m.team_b]
            )
            row = asdict(m) | {
                "a_challenges": we_challenge,
                "bot_a": bot,
                "bot_b": f"foulplay({fp_args['search_ms']}ms x{fp_args['parallelism']})",
                "battle": battle.battle_tag if battle else None,
                "a_won": None if battle is None else battle.won,
                "turns": battle.turn if battle else None,
                "team_ok": team_ok,
                "lead_a": plan.lead if plan else None,
                "plan_a": plan.to_log() if plan else None,
                "plan_b": None,
                "fallbacks_a": getattr(me, "fallbacks", 0),
                "fallbacks_b": 0,
            }
            rows.append(row)
            with open(log_path, "a") as f:
                f.write(json.dumps(row) + "\n")
            if proc.poll() is not None and m is not matches[-1]:
                raise RuntimeError(f"Foul Play lane {lane} exited early (see its log)")
    finally:
        if proc.poll() is None:
            proc.terminate()
        fp_log.close()
    return rows


def _worker(args):
    import logging

    logging.basicConfig(level=logging.WARNING)
    bot, lanes, port, pool_dir, log_path, fp_args, extras, run_dir, lane0 = args

    async def run():
        return await asyncio.gather(
            *[
                _lane(bot, ms, port, pool_dir, lane0 + i, log_path, fp_args, extras, run_dir)
                for i, ms in enumerate(lanes)
            ]
        )

    return [r for lane in asyncio.run(run()) for r in lane]


def run_vs_foulplay(
    bot: str,
    n_pairs: int,
    pool_dir: str = "data/teams/pool",
    ports: tuple[int, ...] = (8000,),
    lanes: int = 2,
    search_ms: int = 1000,
    parallelism: int = 4,
    seed: int = 0,
    trace: bool = False,
    replays: bool = False,
    log_dir: str = "data/eval",
) -> dict:
    names = sorted(load_team_files(pool_dir))
    schedule = make_schedule(names, n_pairs, seed)
    pairs = [schedule[i : i + 2] for i in range(0, len(schedule), 2)]
    lanes = min(lanes, len(pairs))  # an empty lane would still start a Foul Play process
    lane_matches = [[m for pr in pairs[i::lanes] for m in pr] for i in range(lanes)]
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}_{bot}_vs_foulplay{search_ms}x{parallelism}"
    run_dir = Path(log_dir) / "foulplay" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(Path(log_dir) / f"{run_id}.jsonl")
    extras = {}
    if trace:
        extras["trace_dir"] = str(Path(log_dir) / "traces" / run_id)
    if replays:
        extras["replay_dir"] = str(Path(log_dir) / "replays" / run_id)
    fp_args = {"search_ms": search_ms, "parallelism": parallelism}
    # one process per lane (Foul Play is CPU-bound; our bot is cheap)
    jobs = [
        (
            bot,
            [lane_matches[i]],
            ports[i % len(ports)],
            pool_dir,
            log_path,
            fp_args,
            extras,
            run_dir,
            i,
        )
        for i in range(lanes)
    ]
    t0 = time.time()
    with mp.get_context("spawn").Pool(lanes) as pool:
        rows = [r for part in pool.map(_worker, jobs) for r in part]
    return summarize(rows) | {
        "log": log_path,
        "seconds": round(time.time() - t0, 1),
        "foulplay_logs": str(run_dir),
    }
