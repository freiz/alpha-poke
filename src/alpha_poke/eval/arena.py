"""Paired, logged, reproducible head-to-head evaluation.

Schedule: ``n_pairs`` team pairs (X, Y), X != Y, drawn with a fixed seed. Each pair is played
twice with the teams exchanged -- (A: X, B: Y) and (A: Y, B: X) -- and the challenger alternates,
so team-matchup luck and challenger-role bias cancel within a pair.

Execution: each process runs several *lanes*; a lane is one (A, B) player pair that plays its
matches strictly one at a time after ``update_team`` -- so teams can never be mismatched by
concurrent team requests. Lanes run concurrently (asyncio) and processes in parallel.

Every game is appended to a JSONL log; the summary uses the per-pair mean score for the CI
(paired design), plus the naive binomial CI for reference.
"""

import asyncio
import json
import math
import multiprocessing as mp
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from poke_env.teambuilder import Teambuilder

from alpha_poke.analysis.roles import to_id
from alpha_poke.teams import load_team_files


def _base(species: str) -> str:
    """Base species id, so that in-battle forme changes (e.g. Ogerpon's Tera formes, Mimikyu
    busted) are not reported as team mismatches."""
    from poke_env.data import GenData

    sid = to_id(species)
    entry = GenData.from_gen(9).pokedex.get(sid, {})
    return to_id(entry.get("baseSpecies") or entry.get("name") or sid)


def _species(packed: str) -> list[str]:
    return sorted(_base(m.species or m.nickname) for m in Teambuilder.parse_packed_team(packed))


@dataclass
class Match:
    pair: int
    game: int  # 0 or 1 within the pair
    team_a: str
    team_b: str
    a_challenges: bool


def make_schedule(team_names: list[str], n_pairs: int, seed: int = 0) -> list[Match]:
    rng = random.Random(seed)
    out = []
    for p in range(n_pairs):
        x, y = rng.sample(team_names, 2)
        first = p % 2 == 0
        out.append(Match(p, 0, x, y, first))
        out.append(Match(p, 1, y, x, not first))
    return out


async def _lane(bot_a, bot_b, matches, port, pool_dir, heldout, lane_id, log_path, extras):
    from alpha_poke.eval.bots import make_bot

    teams = load_team_files(pool_dir)
    first = next(iter(teams.values()))
    tag = f"{os.getpid() % 10000}l{lane_id}"
    a = make_bot(bot_a, f"A{tag}", port, first, heldout_pool=heldout, **extras)
    b = make_bot(bot_b, f"B{tag}", port, first, heldout_pool=heldout, **extras)
    expected = {k: _species(v) for k, v in teams.items()}
    rows = []
    for m in matches:
        a.update_team(teams[m.team_a])
        b.update_team(teams[m.team_b])
        before, before_b = set(a.battles), set(b.battles)
        if m.a_challenges:
            await a.battle_against(b, n_battles=1)
        else:
            await b.battle_against(a, n_battles=1)
        new = [a.battles[k] for k in a.battles if k not in before]
        battle = new[0] if new else None
        new_b = [b.battles[k] for k in b.battles if k not in before_b]
        team_ok = bool(
            battle
            and new_b
            and sorted(_base(p.species) for p in battle.team.values()) == expected[m.team_a]
            and sorted(_base(p.species) for p in new_b[0].team.values()) == expected[m.team_b]
        )
        plan = getattr(a, "plans", {}).get(battle.battle_tag) if battle else None
        plan_b = getattr(b, "plans", {}).get(battle.battle_tag) if battle else None
        # the final KO happens without another decision: record the end state once more
        if plan is not None and plan.exec_state is not None:
            plan.exec_state.observe(battle)
        if plan_b is not None and plan_b.exec_state is not None and new_b:
            plan_b.exec_state.observe(new_b[0])
        row = asdict(m) | {
            "bot_a": bot_a,
            "bot_b": bot_b,
            "battle": battle.battle_tag if battle else None,
            "a_won": None if battle is None else battle.won,
            "turns": battle.turn if battle else None,
            "team_ok": team_ok,
            "lead_a": plan.lead if plan else None,
            "lead_b": plan_b.lead if plan_b else None,
            "plan_a": plan.to_log() if plan else None,
            "plan_b": plan_b.to_log() if plan_b else None,
            "fallbacks_a": getattr(a, "fallbacks", 0),
            "fallbacks_b": getattr(b, "fallbacks", 0),
        }
        rows.append(row)
        with open(log_path, "a") as f:
            f.write(json.dumps(row) + "\n")
    return rows


def _worker(args):
    bot_a, bot_b, lanes, port, pool_dir, heldout, log_path, wid, extras = args
    import logging

    logging.basicConfig(level=logging.WARNING)

    async def run():
        return await asyncio.gather(
            *[
                _lane(bot_a, bot_b, ms, port, pool_dir, heldout, f"{wid}x{i}", log_path, extras)
                for i, ms in enumerate(lanes)
            ]
        )

    return [r for lane in asyncio.run(run()) for r in lane]


def run_arena(
    bot_a: str,
    bot_b: str,
    n_pairs: int,
    pool_dir: str = "data/teams/pool",
    ports: tuple[int, ...] = (8000,),
    procs: int = 4,
    lanes_per_proc: int = 6,
    seed: int = 0,
    heldout: bool = False,
    log_dir: str = "data/eval",
    trace: bool = False,
    replays: bool = False,
) -> dict:
    names = sorted(load_team_files(pool_dir))
    schedule = make_schedule(names, n_pairs, seed)
    # keep both games of a pair in the same lane (not required, but keeps logs readable)
    pairs = [schedule[i : i + 2] for i in range(0, len(schedule), 2)]
    n_lanes = procs * lanes_per_proc
    lanes = [[m for pr in pairs[i::n_lanes] for m in pr] for i in range(n_lanes)]
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}_{bot_a}_vs_{bot_b}{'_heldout' if heldout else ''}"
    log_path = str(Path(log_dir) / f"{run_id}.jsonl")
    extras = {}
    if trace:
        extras["trace_dir"] = str(Path(log_dir) / "traces" / run_id)
    if replays:
        extras["replay_dir"] = str(Path(log_dir) / "replays" / run_id)
    jobs = [
        (
            bot_a,
            bot_b,
            lanes[w * lanes_per_proc : (w + 1) * lanes_per_proc],
            ports[w % len(ports)],
            pool_dir,
            pool_dir if heldout else None,
            log_path,
            w,
            extras,
        )
        for w in range(procs)
    ]
    t0 = time.time()
    # non-daemonic workers: a search bot starts its own MCTS process pool
    with ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn")) as pool:
        rows = [r for part in pool.map(_worker, jobs) for r in part]
    return summarize(rows) | {"log": log_path, "seconds": round(time.time() - t0, 1)}


def _score(r: dict) -> float | None:
    """1 / 0 for a win / loss of A, 0.5 for a tie (e.g. the 1000-turn limit), None if missing."""
    if r["a_won"] is not None:
        return float(r["a_won"])
    if r.get("battle") and r.get("turns") is not None:
        return 0.5
    return None


def summarize(rows: list[dict]) -> dict:
    scored = [(r, _score(r)) for r in rows]
    done = [(r, s) for r, s in scored if s is not None]
    n = len(done)
    total = sum(s for _, s in done)
    by_pair: dict[int, list[float]] = {}
    for r, s in done:
        by_pair.setdefault(r["pair"], []).append(s)
    scores = [sum(v) / len(v) for v in by_pair.values() if len(v) == 2]
    mean = sum(scores) / max(len(scores), 1)
    var = sum((x - mean) ** 2 for x in scores) / max(len(scores) - 1, 1)
    p = total / max(n, 1)
    return {
        "games": n,
        "a_wins": sum(1 for _, s in done if s == 1.0),
        "ties": sum(1 for _, s in done if s == 0.5),
        "win_rate": round(p, 4),  # ties count as half a win
        "ci95_naive": round(1.96 * math.sqrt(p * (1 - p) / max(n, 1)), 4),
        "pairs": len(scores),
        "paired_mean": round(mean, 4),
        "ci95_paired": round(1.96 * math.sqrt(var / max(len(scores), 1)), 4),
        "split_pairs": sum(1 for x in scores if x == 0.5),
        "fallbacks_a": max((r["fallbacks_a"] for r in rows), default=0),
        "fallbacks_b": max((r["fallbacks_b"] for r in rows), default=0),
        "failed_games": len(rows) - n,
        "team_mismatches": sum(1 for r in rows if not r.get("team_ok", True)),
    }
