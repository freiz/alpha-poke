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
import logging
import math
import multiprocessing as mp
import os
import random
import re
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from poke_env.teambuilder import Teambuilder

from alpha_poke.analysis.roles import to_id
from alpha_poke.teams import DEFAULT_POOL, load_team_files


def _base(species: str) -> str:
    """Base species id, so that in-battle forme changes (e.g. Ogerpon's Tera formes, Mimikyu
    busted) are not reported as team mismatches."""
    from poke_env.data import GenData

    sid = to_id(species)
    entry = GenData.from_gen(9).pokedex.get(sid, {})
    return to_id(entry.get("baseSpecies") or entry.get("name") or sid)


def _species(packed: str) -> list[str]:
    return sorted(_base(m.species or m.nickname) for m in Teambuilder.parse_packed_team(packed))


# evaluation games end at this turn as a draw (stalling loops of two searches or two policies
# otherwise run to Showdown's 1000-turn tie): the bot to move forfeits to end the game
# (agents.search_player / selfplay.player), the result is scored 0.5 whoever forfeited
TURN_CAP = int(os.environ.get("ALPHA_TURN_CAP", 300))

# seconds per game: a game that never starts or never ends (2026-10-09: the last games of an
# evaluation hung for 20+ minutes with no search running); a 300-turn game takes ~10 minutes
GAME_TIMEOUT = 1200.0


@dataclass
class Match:
    pair: int
    game: int  # 0 or 1 within the pair
    team_a: str
    team_b: str
    a_challenges: bool


def pair_schedule(pool_dir: str, n_pairs: int = 0) -> list[Match]:
    """A pool of fixed team pairs (``pair<k>_a.txt`` / ``pair<k>_b.txt``: real-game pairs, e.g.
    sampled like self-play's): each pair played twice with the teams exchanged and the
    challenger alternating; the first ``n_pairs`` (0: all)."""
    ks = sorted({int(m.group(1)) for f in Path(pool_dir).glob("pair*_a.txt")
                 if (m := re.match(r"pair(\d+)_a", f.stem))})  # fmt: skip
    out = []
    for k in ks[:n_pairs] if n_pairs else ks:
        x, y = f"pair{k:03d}_a", f"pair{k:03d}_b"
        out += [Match(k, 0, x, y, k % 2 == 0), Match(k, 1, y, x, k % 2 == 1)]
    return out


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
        # the counters live on the lane's players: log this game's increase only
        fb0 = [(getattr(me, "fallbacks", 0), getattr(me, "search_fallbacks", 0)) for me in (a, b)]
        challenger, opponent = (a, b) if m.a_challenges else (b, a)
        try:
            await asyncio.wait_for(challenger.battle_against(opponent, n_battles=1), GAME_TIMEOUT)
        except TimeoutError:
            # a game that never starts or never ends (2026-10-08: three lanes waited forever on
            # their first challenge) must not hold the lane: skipped, logged without a result
            logging.getLogger(__name__).warning("pair %d game %d: no finished game after %ds",
                                                m.pair, m.game, GAME_TIMEOUT)  # fmt: skip
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
            "capped": bool(battle and battle.turn >= TURN_CAP),
            "team_ok": team_ok,
            "lead_a": plan.lead if plan else None,
            "lead_b": plan_b.lead if plan_b else None,
            "plan_a": plan.to_log() if plan else None,
            "plan_b": plan_b.to_log() if plan_b else None,
            "fallbacks_a": getattr(a, "fallbacks", 0) - fb0[0][0],
            "fallbacks_b": getattr(b, "fallbacks", 0) - fb0[1][0],
            "search_fallbacks_a": getattr(a, "search_fallbacks", 0) - fb0[0][1],
            "search_fallbacks_b": getattr(b, "search_fallbacks", 0) - fb0[1][1],
        }
        rows.append(row)
        with open(log_path, "a") as f:
            f.write(json.dumps(row) + "\n")
    for me in (a, b):  # search bots with worker processes must stop them
        if hasattr(me, "close"):
            me.close()
    return rows


def _worker(args):
    bot_a, bot_b, lanes, port, pool_dir, heldout, log_path, wid, extras = args
    import logging
    import signal

    logging.basicConfig(level=logging.WARNING)

    def stop(*_):  # an early stop (sequential test): this worker's own processes go too
        for c in mp.active_children():
            c.terminate()
        os._exit(1)

    signal.signal(signal.SIGTERM, stop)

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
    pool_dir: str = str(DEFAULT_POOL),
    ports: tuple[int, ...] = (8000,),
    procs: int = 4,
    lanes_per_proc: int = 6,
    seed: int = 0,
    heldout: bool = False,
    log_dir: str = "data/eval",
    trace: bool = False,
    replays: bool = False,
    stop=None,
    poll: float = 20.0,
    pairs: bool = False,
) -> dict:
    """``stop``: called with the logged rows every ``poll`` seconds; True ends the run early
    (the workers are terminated; the summary covers the games logged so far)."""
    if pairs:  # a pool of fixed real-game pairs (pair_schedule)
        schedule = pair_schedule(pool_dir, n_pairs)
    else:
        schedule = make_schedule(sorted(load_team_files(pool_dir)), n_pairs, seed)
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
    meta = run_meta(bot_a, bot_b, n_pairs=n_pairs, procs=procs, lanes=lanes_per_proc, seed=seed,
                    heldout=heldout, pool=pool_dir)  # fmt: skip
    meta_path = Path(log_path).with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=1))
    stopped = False
    if stop is None:
        # non-daemonic workers: a search bot starts its own MCTS process pool
        with ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn")) as pool:
            rows = [r for part in pool.map(_worker, jobs) for r in part]
    else:
        ctx = mp.get_context("spawn")
        workers = [ctx.Process(target=_worker, args=(j,)) for j in jobs]
        for w in workers:
            w.start()
        try:
            while any(w.is_alive() for w in workers):
                time.sleep(poll)
                if stop(read_log(log_path)):
                    stopped = True
                    break
        finally:
            for w in workers:
                if w.is_alive():
                    w.terminate()
            for w in workers:
                w.join()
        rows = read_log(log_path)
    res = summarize(rows) | {"log": log_path, "seconds": round(time.time() - t0, 1),
                             "stopped_early": stopped}  # fmt: skip
    meta_path.write_text(json.dumps(meta | {"result": res}, indent=1))
    return res


def run_schedule(bot_a: str, bot_b: str, schedule: list[Match], pool_dir: str, log_path: str,
                 ports: tuple[int, ...] = (8000,), procs: int = 4, lanes_per_proc: int = 2,
                 heldout: bool = False) -> list[dict]:  # fmt: skip
    """Play any list of matches (teams from ``pool_dir``), spread over procs x lanes; one JSONL
    row per game appended to ``log_path``. ``run_arena`` is this with the paired schedule."""
    n_lanes = procs * lanes_per_proc
    lanes = [schedule[i::n_lanes] for i in range(n_lanes)]
    jobs = [
        (bot_a, bot_b, lanes[w * lanes_per_proc : (w + 1) * lanes_per_proc], ports[w % len(ports)],
         pool_dir, pool_dir if heldout else None, log_path, w, {})
        for w in range(procs)
    ]  # fmt: skip
    with ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn")) as pool:
        return [r for part in pool.map(_worker, jobs) for r in part]


def run_meta(bot_a: str, bot_b: str, **args) -> dict:
    """Everything needed to compare runs later: code version, settings, bot definitions."""
    from alpha_poke.eval.bots import VARIANTS

    def git(*cmd):
        try:
            return subprocess.run(["git", *cmd], capture_output=True, text=True).stdout.strip()
        except OSError:
            return None

    return {
        "commit": git("rev-parse", "--short", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "env": {k: v for k, v in sorted(os.environ.items()) if k.startswith("ALPHA_")},  # fmt: skip
        "args": args,
        "bots": {b: repr(VARIANTS.get(b, "baseline")) for b in (bot_a, bot_b)},
    }


def _score(r: dict) -> float | None:
    """1 / 0 for a win / loss of A, 0.5 for a tie (or a game ended at the turn cap), None if
    missing."""
    if r.get("capped"):
        return 0.5
    if r["a_won"] is not None:
        return float(r["a_won"])
    if r.get("battle") and r.get("turns") is not None:
        return 0.5
    return None


def read_log(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def pair_scores(rows: list[dict]) -> list[float]:
    """A's mean score of every pair with both games finished."""
    by_pair: dict[int, list[float]] = {}
    for r in rows:
        s = _score(r)
        if s is not None:
            by_pair.setdefault(r["pair"], []).append(s)
    return [sum(v) / len(v) for v in by_pair.values() if len(v) == 2]


def elo_score(elo: float) -> float:
    return 1 / (1 + 10 ** (-elo / 400))


def sprt_llr(scores: list[float], elo0: float, elo1: float) -> float:
    """Log-likelihood ratio of H1 (A is elo1 stronger) against H0 (elo0) from paired scores:
    the normal approximation of the generalized SPRT on the pair means (pentanomial: each
    pair's score is 0, 1/4, ..., 1), as fishtest's GSPRT."""
    n = len(scores)
    if n < 2:
        return 0.0
    s0, s1 = elo_score(elo0), elo_score(elo1)
    mean = sum(scores) / n
    var = max(sum((x - mean) ** 2 for x in scores) / n, 1e-3)
    return (s1 - s0) * (2 * mean - s0 - s1) * n / (2 * var)


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
        "fallbacks_a": sum(r["fallbacks_a"] or 0 for r in rows),  # per-game counts
        "fallbacks_b": sum(r["fallbacks_b"] or 0 for r in rows),
        # the search's failures (a heuristic decision instead; 2026-10-14: per game only, the
        # summary showed 0 while gen 4 / 5's evaluations had 5 / 3)
        "search_fallbacks_a": sum(r.get("search_fallbacks_a") or 0 for r in rows),
        "search_fallbacks_b": sum(r.get("search_fallbacks_b") or 0 for r in rows),
        "failed_games": len(rows) - n,
        "team_mismatches": sum(1 for r in rows if not r.get("team_ok", True)),
    }
