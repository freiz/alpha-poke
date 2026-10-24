"""Turn replays into training positions (design D13): data/train/<name>/<source shard>.parquet.

Usage: uv run python scripts/build_training_data.py --name v1 --per-game 4 --workers 8

Source: the Gen9 OU replays of analysis.games_lite.SOURCES (Metamon's, scripts/fetch_metamon.py,
and the newer HF dump's, data/replays_hf), all of them
by default. Every game gives ``--per-game`` positions drawn at random among its turn-start
decision points (+ ``--extra-per-game`` of its forced / pivot switches and unseen choices, v4)
(many games x few positions: positions of one game are strongly correlated and share one
outcome); each is the poke-engine state seen by the player to act (its own sets: game-wide reveals
+ belief samples; the opponent: reveals so far + belief samples), the action it took (14 slots)
and whether it won (alpha_poke.train.positions). Features are computed from the state strings at
training time (alpha_search.featurize); rating and uploadtime are kept for weighting there.

One output file per source shard, renamed into place when the shard is done: rerunning skips
finished shards. Each task's positions are written as they come back (a row group per task,
``--schema-from``: the column types of an earlier build, else the first task's): the main process
holds one task's positions, not a shard's ~1.1M (2026-10-19).
"""

import argparse
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from alpha_poke.analysis.games_lite import source_files
from alpha_poke.teams import DEFAULT_POOL

_belief = None


def _init(heldout: bool):
    global _belief
    import logging

    from alpha_poke.agents.belief_state import BeliefModel

    logging.disable(logging.WARNING)
    _belief = BeliefModel.load(heldout_pool=str(DEFAULT_POOL) if heldout else None)


def _work(args):
    rows, seed, move_beta, per_game, extra_per_game, game_seed, pool = args
    from alpha_poke.train.positions import positions_from_replay

    rng = random.Random(seed)
    out, failed = [], 0
    for r in rows:
        try:
            out += [
                asdict(p)
                for p in positions_from_replay(
                    r, _belief, rng, move_beta, per_game, extra_per_game, game_seed, pool
                )
            ]
        except Exception:  # noqa: BLE001 - a broken log must not stop the build
            failed += 1
    return out, failed


def load_games(path: str, min_rating: int, since: float, fraction: float, seed: int) -> list:
    t = pq.read_table(path, columns=["id", "log", "rating", "uploadtime"])
    rating = pc.cast(pc.if_else(pc.utf8_is_numeric(t["rating"]), t["rating"], "0"), pa.int64())
    keep = pc.and_(pc.greater_equal(rating, min_rating), pc.greater_equal(t["uploadtime"], since))
    # (not Radical Red's server: a ROM hack's Gen 9 OU, its own species, stats and moves -- ~1,000
    # games in the sources, a third of them with species the dex does not have; 2026-10-24)
    keep = pc.and_(keep, pc.invert(pc.starts_with(t["id"], "radicalred-")))
    rows = t.filter(keep).to_pylist()
    if fraction < 1:
        rows = random.Random(seed).sample(rows, int(len(rows) * fraction))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--per-game", type=int, default=4, help="positions per game (0 = all)")
    ap.add_argument("--extra-per-game", type=int, default=0,
                    help="v4: other decision points per game (forced / pivot switches, turns "
                         "whose action the log does not show)")  # fmt: skip
    ap.add_argument("--pool", choices=["split", "all"], default="split",
                    help="all: --per-game from all decision points (real shares)")  # fmt: skip
    ap.add_argument("--min-rating", type=int, default=0)
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--fraction", type=float, default=1.0, help="of the games of each shard")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--chunk", type=int, default=250, help="games per task")
    ap.add_argument("--move-beta", type=float, default=1.0)
    ap.add_argument("--heldout", action="store_true", help="belief without the eval team pool")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--row-group", type=int, default=50_000, help="positions per write")
    ap.add_argument("--schema-from", default="",
                    help="a parquet file of an earlier build: its column types (a column all "
                         "null in the first task would otherwise be typed null)")  # fmt: skip
    ap.add_argument("--max-games", type=int, default=60_000,
                    help="per source shard (Metamon's: <= 58k; split bigger ones)")  # fmt: skip
    a = ap.parse_args()
    out = Path("data/train") / a.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(json.dumps(vars(a), indent=2))
    since = time.mktime(time.strptime(a.since, "%Y-%m-%d"))
    t0 = time.time()
    n_games = n_pos = n_failed = 0
    schema = pq.read_schema(a.schema_from) if a.schema_from else None
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.heldout,)) as pool:
        for k, src in enumerate(source_files()):
            dst = out / Path(src).name
            if dst.exists():
                continue
            n_src = pq.read_metadata(src).num_rows
            if n_src > a.max_games:  # its positions would not fit featurization (train_pv)
                raise SystemExit(f"{src}: {n_src} games > --max-games {a.max_games}: split it "
                                 "with scripts/split_shards.py")  # fmt: skip
            rows = load_games(src, a.min_rating, since, a.fraction, a.seed + k)
            n_src_used = len(rows)
            tasks = [
                (
                    rows[i : i + a.chunk],
                    a.seed * 1_000_003 + k * 10_007 + i,
                    a.move_beta,
                    a.per_game,
                    a.extra_per_game,
                    a.seed,
                    a.pool,
                )  # fmt: skip
                for i in range(0, len(rows), a.chunk)
            ]
            n_shard, failed, writer, buf = 0, 0, None, []
            tmp = dst.with_suffix(".tmp")

            def flush():
                nonlocal writer, schema
                t = pa.Table.from_pylist(buf, schema=schema)
                if writer is None:
                    schema = schema or t.schema
                    writer = pq.ParquetWriter(tmp, schema, compression="zstd")
                writer.write_table(t)
                buf.clear()

            for p, f in pool.map(_work, tasks):  # (in order; written as they come back)
                failed += f
                buf += p
                n_shard += len(p)
                if len(buf) >= a.row_group:
                    flush()
            if buf:
                flush()
            if writer is not None:
                writer.close()
                tmp.rename(dst)
            del rows, tasks
            n_games, n_pos, n_failed = n_games + n_src_used, n_pos + n_shard, n_failed + failed
            rate = n_games / (time.time() - t0)
            print(
                f"{Path(src).name}: {n_src_used} games -> {n_shard} positions ({failed} failed); "
                f"total {n_games} games, {n_pos} positions, {rate:.0f} games/s",
                flush=True,
            )
    print(f"done in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
