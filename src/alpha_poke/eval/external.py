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
from concurrent.futures import ProcessPoolExecutor
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


def _opponent_cmd(opp, port, opp_name, our_name, we_challenge, matches, pool_dir, run_dir, lane):
    """(command, cwd, env, label) of the opponent process for one lane.
    opp = {"kind": "foulplay", "search_ms", "parallelism"} or
          {"kind": "checkout", "path": <git worktree of an older commit>, "bot": <variant>}."""
    if opp["kind"] == "foulplay":
        fp_names = _install_teams(pool_dir)
        list_file = FP_TEAMS / "lists" / f"{run_dir.name}_lane{lane}.txt"
        list_file.parent.mkdir(parents=True, exist_ok=True)
        list_file.write_text("\n".join(fp_names[m.team_b] for m in matches) + "\n")
        cmd = [
            str(FP / ".venv" / "bin" / "python"), "run.py",
            "--websocket-uri", f"ws://localhost:{port}/showdown/websocket",
            "--ps-username", opp_name, "--pokemon-format", "gen9ou",
            "--team-list", str(list_file.relative_to(FP / "fp" / "teams" / "teams")),
            "--run-count", str(len(matches)),
            "--search-time-ms", str(opp["search_ms"]),
            "--search-parallelism", str(opp["parallelism"]),
            "--save-replay", "never", "--log-level", "INFO",
        ]  # fmt: skip
        cmd += (
            ["--bot-mode", "accept_challenge"]
            if we_challenge
            else ["--bot-mode", "challenge_user", "--user-to-challenge", our_name]
        )
        label = f"foulplay({opp['search_ms']}ms x{opp['parallelism']})"
        return cmd, FP, dict(os.environ, FP_OFFLINE="1"), label
    path = Path(opp["path"]).resolve()
    cmd = [
        str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "serve_bot.py"),
        "--bot", opp["bot"], "--port", str(port), "--username", opp_name,
        "--pool", str(Path(pool_dir).resolve()),
        "--teams", ",".join(m.team_b for m in matches),
        "--mode", "accept" if we_challenge else "challenge", "--opponent", our_name,
    ]  # fmt: skip
    # the old checkout's code wins over the editable install of the current one
    env = dict(os.environ, PYTHONPATH=str(path / "src"))
    return cmd, path, env, f"{opp['bot']}@{opp.get('rev', path.name)}"


async def _lane(bot, matches, port, pool_dir, lane, log_path, opp, extras, run_dir):
    from alpha_poke.eval.bots import make_bot

    teams = load_team_files(pool_dir)
    expected = {k: _species(v) for k, v in teams.items()}
    tag = f"{os.getpid() % 10000}l{lane}"
    our_name, opp_name = f"ab{tag}", ("fp" if opp["kind"] == "foulplay" else "old") + tag
    we_challenge = lane % 2 == 0
    cmd, cwd, env, label = _opponent_cmd(
        opp, port, opp_name, our_name, we_challenge, matches, pool_dir, run_dir, lane
    )
    fp_log = open(run_dir / f"opponent_lane{lane}.log", "w")
    first = next(iter(teams.values()))
    me = make_bot(bot, our_name, port, first, **extras)
    if not we_challenge:  # we must be logged in before the opponent starts challenging us
        await asyncio.sleep(3)
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=fp_log, stderr=subprocess.STDOUT, env=env)
    rows = []
    try:
        # opponent login + data loading (our older bots load the belief model: slower)
        await asyncio.sleep(6 if opp["kind"] == "foulplay" else 20)
        for m in matches:
            me.update_team(teams[m.team_a])
            if getattr(me, "use_oracle", False):
                me.set_oracle((Path(pool_dir) / f"{m.team_b}.txt").read_text())
            before = set(me.battles)
            fb0 = (getattr(me, "fallbacks", 0), getattr(me, "search_fallbacks", 0))
            if we_challenge:
                await me.send_challenges(opp_name, n_challenges=1)
            else:
                await me.accept_challenges(opp_name, n_challenges=1)
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
                "bot_b": label,
                "battle": battle.battle_tag if battle else None,
                "a_won": None if battle is None else battle.won,
                "turns": battle.turn if battle else None,
                "team_ok": team_ok,
                "lead_a": plan.lead if plan else None,
                "plan_a": plan.to_log() if plan else None,
                "plan_b": None,
                "fallbacks_a": getattr(me, "fallbacks", 0) - fb0[0],  # this game only
                "search_fallbacks_a": getattr(me, "search_fallbacks", 0) - fb0[1],
                "fallbacks_b": 0,
            }
            rows.append(row)
            with open(log_path, "a") as f:
                f.write(json.dumps(row) + "\n")
            if proc.poll() is not None and m is not matches[-1]:
                raise RuntimeError(f"opponent of lane {lane} exited early (see its log)")
    finally:
        if proc.poll() is None:
            proc.terminate()
        fp_log.close()
        if hasattr(me, "close"):
            me.close()
    return rows


def _worker(args):
    import logging

    logging.basicConfig(level=logging.WARNING)
    bot, lanes, port, pool_dir, log_path, opp, extras, run_dir, lane0 = args

    async def run():
        return await asyncio.gather(
            *[
                _lane(bot, ms, port, pool_dir, lane0 + i, log_path, opp, extras, run_dir)
                for i, ms in enumerate(lanes)
            ]
        )

    return [r for lane in asyncio.run(run()) for r in lane]


def run_external(
    bot: str,
    opp: dict,
    n_pairs: int,
    pool_dir: str = "data/teams/pool",
    ports: tuple[int, ...] = (8000,),
    lanes: int = 2,
    seed: int = 0,
    trace: bool = False,
    replays: bool = False,
    log_dir: str = "data/eval",
    heldout: bool = False,
) -> dict:
    """Paired run of our ``bot`` against an opponent process (see ``_opponent_cmd``).
    ``heldout``: our belief model without the pool's teams (as arena --heldout)."""
    names = sorted(load_team_files(pool_dir))
    schedule = make_schedule(names, n_pairs, seed)
    pairs = [schedule[i : i + 2] for i in range(0, len(schedule), 2)]
    lanes = min(lanes, len(pairs))  # an empty lane would still start an opponent process
    lane_matches = [[m for pr in pairs[i::lanes] for m in pr] for i in range(lanes)]
    if opp["kind"] == "foulplay":
        tag = f"foulplay{opp['search_ms']}x{opp['parallelism']}"
    else:
        tag = f"{opp['bot']}@{opp.get('rev', Path(opp['path']).name)}"
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}_{bot}_vs_{tag}" + ("_heldout" if heldout else "")
    run_dir = Path(log_dir) / "external" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(Path(log_dir) / f"{run_id}.jsonl")
    extras = {}
    if heldout:
        extras["heldout_pool"] = pool_dir
    if trace:
        extras["trace_dir"] = str(Path(log_dir) / "traces" / run_id)
    if replays:
        extras["replay_dir"] = str(Path(log_dir) / "replays" / run_id)
    # one process per lane (the opponent is CPU-bound; our bot is cheap)
    jobs = [
        (bot, [lane_matches[i]], ports[i % len(ports)], pool_dir, log_path, opp, extras, run_dir, i)
        for i in range(lanes)
    ]
    t0 = time.time()
    # non-daemonic workers: a search bot starts its own MCTS process pool
    with ProcessPoolExecutor(lanes, mp_context=mp.get_context("spawn")) as pool:
        rows = [r for part in pool.map(_worker, jobs) for r in part]
    return summarize(rows) | {
        "log": log_path,
        "seconds": round(time.time() - t0, 1),
        "opponent_logs": str(run_dir),
    }


def run_vs_foulplay(bot: str, n_pairs: int, pool_dir="data/teams/pool", ports=(8000,), lanes=2,
                    search_ms=1000, parallelism=4, seed=0, trace=False, replays=False,
                    log_dir="data/eval", heldout=False) -> dict:  # fmt: skip
    opp = {"kind": "foulplay", "search_ms": search_ms, "parallelism": parallelism}
    return run_external(bot, opp, n_pairs, pool_dir, ports, lanes, seed, trace, replays, log_dir,
                        heldout)  # fmt: skip
