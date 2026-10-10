"""Self-play games (design D15). Local servers only.

Processes x lanes: a lane is two ``SelfPlayPlayer``s playing their share of the generation's
team pairs one game at a time (``update_team`` before each game, the challenger alternates);
the lanes of a process run concurrently and share one GPU batcher (cross-game batching,
``selfplay.batcher``). After each game the lane writes
  games-w<k>.jsonl      one row per game: pair index, battle, teams (sources), winner, turns,
                        decisions, fallbacks, seconds
  decisions-w<k>.jsonl  one row per decision of either side (SelfPlayPlayer.records) plus
                        "game", "won" (that side's outcome; None if capped) and "model"
  logs-w<k>.jsonl       the game's protocol log (labels for training: selfplay.convert)
  progress-w<k>.log     every minute: games, decisions, leaves / s, fallbacks, batcher counters
  errors-w<k>.log       warnings and errors (failed searches, fallbacks)
in ``data/selfplay/gen<g>/``. Pairs already in a games file are skipped (resume).

"""

import asyncio
import json
import logging
import multiprocessing as mp
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from alpha_poke.servers import account, local_server

MODEL = "data/train/v5/runs/v5-glu"


def done_pairs(gen_dir: Path) -> set[int]:
    done = set()
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in f.read_text().splitlines():
            done.add(json.loads(line)["pair"])
    return done


def packed(text: str) -> str:
    """A team export as poke-env's packed team: the species line goes into the species field
    with no nickname (poke-env reads "Species @ Item" as a nickname; a species name longer than
    18 characters, e.g. Tauros-Paldea-Combat, is then an illegal nickname and the server rejects
    the challenge)."""
    from poke_env.teambuilder import Teambuilder

    clean = "\n".join(line.strip() for line in text.strip().splitlines()) + "\n\n"
    mons = Teambuilder.parse_showdown_team(clean)
    for m in mons:
        m.species = m.species or m.nickname
        m.nickname = ""
    return Teambuilder.join_team(mons)


# seconds: a game that never ends (e.g. a challenge the server refused). Not 30 minutes: a game
# to the 300-turn cap is ~600 decisions, each waiting for a batched search round (gen 1: such
# games ran over 30 minutes and were skipped)
GAME_TIMEOUT = 7200.0
# seconds without a new turn in a started game: stalled. A decision's search takes seconds; a
# lost choice leaves the game waiting for good (gens 3-4, ~1 in 7,000 games, all long games: the
# server answered "/choose - must be used in a chat room" and the turn never came), which cost
# a lane the whole GAME_TIMEOUT
STALL_TIMEOUT = 600.0


async def _lane(lane: str, jobs: list, port: int, gen_dir: Path, settings: dict, batcher,
                belief, wid: int, counters: dict) -> int:  # fmt: skip
    from alpha_poke.selfplay.player import SelfPlayPlayer

    def player(tag: str, seed: int):
        return SelfPlayPlayer(
            belief,
            account_configuration=account(f"s{settings['run_tag']}{lane}{tag}"),
            battle_format="gen9ou", server_configuration=local_server(port),
            max_concurrent_battles=1, team=jobs[0][1].p1.text, worlds=32,
            # poke-env logs the server's |error| messages ([Invalid choice], [Unavailable
            # choice]) at level 25: kept, for the stalled games' causes
            log_level=25,
            net_policy="both", model=settings["model"], batcher=batcher, seed=seed,
            full_frac=settings["full_frac"], full_iters=settings["full_iters"],
            fast_iters=settings["fast_iters"], fast_worlds=settings["fast_worlds"],
            noise=tuple(settings["noise"]), turn_cap=settings["turn_cap"],
            temp_turns=settings.get("temp_turns", 8), temp_late=settings.get("temp_late", 0.25),
        )  # fmt: skip

    # per run (run_tag) and lane: a lane named alike in every generation must not replay the same
    # random choices (full / fast searches, root noise, move sampling)
    seed = zlib.crc32(f"{settings['run_tag']}:{lane}".encode())
    a, b = player("a", 2 * seed), player("b", 2 * seed + 1)
    n = resets = 0
    prev_tag = None
    for idx, pair in jobs:
        a.update_team(packed(pair.p1.text))
        b.update_team(packed(pair.p2.text))
        t0 = time.time()
        before = set(a.battles)
        fb0 = (a.search_fallbacks, b.search_fallbacks)
        first, second = (a, b) if idx % 2 == 0 else (b, a)
        task = asyncio.ensure_future(first.battle_against(second, n_battles=1))
        last_turn, last_change, why = -1, time.time(), None
        while why is None:
            done, _ = await asyncio.wait({task}, timeout=60)
            if task in done:
                task.result()
                break
            cur = [a.battles[k] for k in a.battles if k not in before]
            turn = cur[0].turn if cur else -1
            if turn != last_turn:
                last_turn, last_change = turn, time.time()
            if cur and time.time() - last_change > STALL_TIMEOUT:
                why = f"no new turn for {STALL_TIMEOUT:.0f}s at turn {turn}"
            elif time.time() - t0 > GAME_TIMEOUT:
                why = f"no finished game after {GAME_TIMEOUT:.0f}s"
        if why is not None:
            task.cancel()
            log = logging.getLogger(__name__)
            log.warning("pair %d: %s, skipped", idx, why)
            if cur:  # the protocol's last messages, for the cause
                from alpha_poke.agents.net_context import battle_log

                tail = ["|".join(m) for m in battle_log(cur[0])][-40:]
                log.warning("pair %d (%s) last messages:\n%s", idx, cur[0].battle_tag,
                            "\n".join(tail))  # fmt: skip
            # the players still hold the unfinished battle (max_concurrent_battles=1): every
            # later challenge of theirs would wait for it too. New players (accounts) instead.
            resets += 1
            a = player(f"a{resets}", 2 * seed + 2 * resets)
            b = player(f"b{resets}", 2 * seed + 2 * resets + 1)
            continue
        new = [k for k in a.battles if k not in before]
        if not new:
            continue
        tag = new[0]
        battle = a.battles[tag]
        recs = {"a": a.records.pop(tag, []), "b": b.records.pop(tag, [])}
        capped = battle.turn >= settings["turn_cap"]
        won_a = None if capped else battle.won
        game = {
            "pair": idx, "battle": tag, "p1": pair.p1.ref, "p1_kind": pair.p1.kind,
            "p2": pair.p2.ref, "p2_kind": pair.p2.kind, "source_game": pair.game,
            "a_side": battle.player_role, "a_won": won_a, "turns": battle.turn,
            "capped": capped,
            "decisions": len(recs["a"]) + len(recs["b"]),
            "fallbacks": [a.search_fallbacks - fb0[0], b.search_fallbacks - fb0[1]],
            "seconds": round(time.time() - t0, 1), "model": settings["model"], "lane": lane,
        }  # fmt: skip
        with open(gen_dir / f"decisions-w{wid}.jsonl", "a") as f:
            for who, rs in recs.items():
                won = won_a if who == "a" or won_a is None else not won_a
                for r in rs:
                    f.write(json.dumps(r | {"game": idx, "won": won, "model": settings["model"]})
                            + "\n")  # fmt: skip
        with open(gen_dir / f"games-w{wid}.jsonl", "a") as f:
            f.write(json.dumps(game) + "\n")
        # the protocol log (player a's view): the labels only the whole game knows are built
        # from it with the replay pipeline (selfplay.convert)
        from alpha_poke.agents.net_context import battle_log

        log_text = "\n".join("|".join(m) for m in battle_log(battle))
        with open(gen_dir / f"logs-w{wid}.jsonl", "a") as f:
            f.write(json.dumps({"pair": idx, "battle": tag, "log": log_text}) + "\n")
        # the previous game's state, no longer needed: one game late, so that no message of it
        # (e.g. |deinit| after /leave) can still come (poke-env would wait for that battle
        # forever, and wake every such waiter at each new battle)
        if prev_tag is not None:
            for pl in (a, b):
                pl.forget(prev_tag)
        prev_tag = tag
        n += 1
        counters["games"] += 1
        counters["decisions"] += game["decisions"]
        counters["leaves"] += sum(r["iterations"] for rs in recs.values() for r in rs)
        counters["fallbacks"] += sum(game["fallbacks"])
        counters["capped"] += capped
    return n


async def _process(wid: int, jobs: list, port: int, gen_dir: Path, settings: dict) -> int:
    """One process: ``lanes`` concurrent lanes sharing one GPU batcher."""
    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay.batcher import Batcher

    belief = BeliefModel.load()
    batcher = Batcher(settings["model"], leaves=settings["leaves"], threads=settings["threads"],
                      dtype=settings.get("dtype", "fp32"))  # fmt: skip
    lanes = settings["lanes"]
    parts = [jobs[i::lanes] for i in range(lanes)]
    counters = {"games": 0, "decisions": 0, "leaves": 0, "fallbacks": 0, "capped": 0}
    t0 = time.time()

    async def progress():
        """Every minute: games, decisions, leaves per second, fallbacks, batcher counters."""
        while True:
            await asyncio.sleep(60)
            dt = time.time() - t0
            line = {"t": round(dt), "jobs": len(jobs), **counters,
                    "leaves_per_s": round(batcher.stats["rows"] / 2 / dt),
                    "games_per_h": round(counters["games"] / dt * 3600),
                    "batcher": {k: round(v, 1) if isinstance(v, float) else v
                                for k, v in batcher.stats.items()}}  # fmt: skip
            with open(gen_dir / f"progress-w{wid}.log", "a") as f:
                f.write(json.dumps(line) + "\n")

    reporter = asyncio.create_task(progress())
    counts = await asyncio.gather(*[
        _lane(f"{wid}x{i}", part, port, gen_dir, settings, batcher, belief, wid, counters)
        for i, part in enumerate(parts) if part
    ])  # fmt: skip
    reporter.cancel()
    (gen_dir / f"batcher-w{wid}.json").write_text(json.dumps(batcher.stats))
    return sum(counts)


def _worker(args) -> int:
    wid, jobs, port, gen_dir, settings = args
    import os

    # the batcher's network compiled (agents.gpu_net; GPU-bound since the CPU fixes)
    os.environ["ALPHA_GPU_COMPILE"] = "1" if settings.get("compile", True) else "0"
    # warnings and errors (search failures, engine panics, fallbacks) of this worker
    logging.basicConfig(level=logging.WARNING, filename=str(Path(gen_dir) / f"errors-w{wid}.log"),
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")  # fmt: skip
    return asyncio.run(_process(wid, jobs, port, Path(gen_dir), settings))


def run(gen_dir: Path, pairs: list, settings: dict, procs: int = 4,
        ports: tuple[int, ...] = (8000, 8001), limit: int = 0) -> int:  # fmt: skip
    """Play the pairs not yet done (at most ``limit`` if > 0); returns the games played."""
    from alpha_poke.selfplay.teams import poke_env_clash

    done = done_pairs(gen_dir)
    jobs = [(i, p) for i, p in enumerate(pairs) if i not in done]
    bad = [i for i, p in jobs if poke_env_clash(p.p1.text) or poke_env_clash(p.p2.text)]
    if bad:  # pairs drawn before teams.sample rejected them
        print(f"pairs {bad}: a team poke-env cannot track, skipped")
        jobs = [(i, p) for i, p in jobs if i not in bad]
    if limit:
        jobs = jobs[:limit]
    if not jobs:
        return 0
    procs = min(procs, len(jobs))
    # usernames unique per run: a run must never log in as the players of an earlier one (the
    # server would hand it that run's unfinished battles)
    settings = settings | {"run_tag": format(int(time.time() * 1000) % 36**4, "x")[-4:]}
    parts = [(w, jobs[w::procs], ports[w % len(ports)], str(gen_dir), settings)
             for w in range(procs)]  # fmt: skip
    with ProcessPoolExecutor(procs, mp_context=mp.get_context("spawn")) as ex:
        return sum(ex.map(_worker, parts))
