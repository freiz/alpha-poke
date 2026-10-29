"""The causality check (doc/state-diff.md plan B): a training position's inputs besides the state
-- the history, the reveal bits, the ratings, the turn -- must be what the live path computes
from the log up to that decision. Each replay is turned into positions as the data build does
(train/positions.positions_from_replay: all decision points); at each position, the same battle,
as it stands then (its log so far), gives the live contexts (agents/net_context.contexts, what
the search feeds the network); the two are compared field by field. A difference is a future
line the training input read, or a live / training mismatch either way.

  uv run python scripts/check_causality.py --games 3000 --procs 12
"""

import argparse
import collections
import json
import multiprocessing as mp
import random
from pathlib import Path

_belief = None


def _init() -> None:
    global _belief
    import logging

    from alpha_poke.agents.belief_state import BeliefModel

    logging.disable(logging.WARNING)
    _belief = BeliefModel.load()


def game_diffs(row: dict, belief) -> tuple[list[tuple], int]:
    """[(turn, side, kind, field, training value, live value)] of a replay's positions; and how
    many positions."""
    import alpha_poke.train.positions as P
    from alpha_poke.agents import net_context as N

    live: list = []
    inner = P._position

    def position(battle, side, *a, **kw):
        out = inner(battle, side, *a, **kw)
        if out is not None:  # (the live contexts of this battle now: its log so far)
            if battle.opponent_username is None:
                # (live, the server's |title| line names the opponent -- a replay's log has none:
                # its |player| line; the shadow battle plays the opponent by its name)
                other = "p2" if battle.player_role == "p1" else "p1"
                battle._opponent_username = next(
                    (m[3] for m in battle._replay_data if len(m) > 3 and m[1] == "player" and m[2] == other and m[3]),
                    None)  # fmt: skip
            live.append(N.contexts(battle, [out[0]])[0])
        return out

    P._position = position
    try:
        positions = P.positions_from_replay(
            row, belief, random.Random(0), 1.0, 0, 10**6, 0, "split"
        )
    finally:
        P._position = inner
    out = []
    for p, (reveal, ratings, turn, hist) in zip(positions, live, strict=True):
        for field, mine, theirs in (("history", p.history, hist), ("reveal", list(p.reveal), list(reveal)),
                                    ("ratings", (p.rating_own, p.rating_opp), tuple(ratings)),
                                    ("turn", p.turn, turn)):  # fmt: skip
            if mine != theirs:
                out.append((p.turn, p.side, p.kind, field, str(mine)[:3000], str(theirs)[:3000]))
    return out, len(positions)


def _work(rows):
    out, n, failed = [], 0, []
    for r in rows:
        try:
            d, k = game_diffs(r, _belief)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{r['id']}: {type(e).__name__}: {e}"[:200])
            continue
        out += [(r["id"], *x) for x in d]
        n += k
    return out, n, failed


def _games(n: int, seed: int) -> list[dict]:
    """``n`` replays drawn from the data build's sources, read shard by shard (streamed)."""
    import pyarrow.parquet as pq

    from alpha_poke.analysis.games_lite import source_files

    files = sorted(source_files())
    rng = random.Random(seed)
    rng.shuffle(files)
    rows: list = []
    for f in files:
        pf = pq.ParquetFile(f)
        for batch in pf.iter_batches(
            batch_size=2000, columns=["id", "log", "rating", "uploadtime"]
        ):
            rows += [r for r in batch.to_pylist() if rng.random() < 0.05]
            if len(rows) >= n:
                return rows[:n]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="data/selfplay/diag/causality.json")
    a = ap.parse_args()
    rows = _games(a.games, a.seed)
    chunks = [rows[i : i + 10] for i in range(0, len(rows), 10)]
    kinds: collections.Counter = collections.Counter()
    games: dict = collections.defaultdict(set)
    examples: dict = collections.defaultdict(list)
    total, failed = 0, []
    with mp.get_context("spawn").Pool(a.procs, initializer=_init) as pool:
        for out, n, f in pool.imap_unordered(_work, chunks):
            total += n
            failed += f
            for gid, turn, side, kind, field, mine, theirs in out:
                key = f"{field} (kind {kind})"
                kinds[key] += 1
                games[key].add(gid)
                if len(examples[key]) < 20:
                    examples[key].append((gid, turn, side, mine, theirs))
    print(
        f"{len(rows)} replays, {total} positions: {sum(kinds.values())} differences; failed {len(failed)}"
    )
    for k, c in kinds.most_common():
        print(f"  {c:6d}  {k:24s} in {len(games[k])} games, e.g. {examples[k][0]}"[:300])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(
        json.dumps(
            {
                "games": len(rows),
                "positions": total,
                "kinds": dict(kinds),
                "failed": failed[:50],
                "examples": examples,
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
