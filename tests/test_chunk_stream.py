"""--stream's sampling (2026-10-23 review): a chunk's steps by its share of the whole time weight,
so a row's chance is its global weight. Before, by its rows: two shards of the same size, 2% and
98% of the weight, got the same number of steps."""

import sys

import numpy as np

sys.path.insert(0, "scripts")
from train_pv import ChunkStream  # noqa: E402


def _stream(tmp_path, weights, k):
    sizes = [500] * len(weights)
    caches = []
    for i, n in enumerate(sizes):
        c = tmp_path / f"s{i}.npz"
        np.savez(c, x=np.full(n, i, np.int32))
        caches.append(c)
    small = {"shard": np.repeat(np.arange(len(sizes)), sizes),
             "row": np.concatenate([np.arange(n) for n in sizes])}  # fmt: skip
    w = np.concatenate([np.full(n, wt / n) for n, wt in zip(sizes, weights, strict=True)])
    train_idx = np.arange(len(w))
    return ChunkStream(caches, small, train_idx, w / w.sum(), k, 10, np.random.default_rng(0))


def _shares(stream, steps, n_shards):
    got = np.zeros(n_shards)
    for _ in range(steps):
        chunk, b_loc, _ = stream.batch_rows()
        got += np.bincount(chunk["x"][b_loc], minlength=n_shards)
    return got / got.sum()


def test_a_chunk_trains_by_its_weight(tmp_path):
    s = _stream(tmp_path, [0.02, 0.98], k=1)
    got = _shares(s, 2000, 2)  # 20 passes of 100 steps
    assert abs(got[1] - 0.98) < 0.01, got
    s.pool.shutdown()


def test_pairs_of_shards_keep_the_global_weights(tmp_path):
    want = np.array([0.05, 0.15, 0.30, 0.50])
    s = _stream(tmp_path, list(want), k=2)
    got = _shares(s, 4000, 4)  # 20 passes of 200 steps
    assert np.abs(got - want).max() < 0.02, got
    s.pool.shutdown()


def test_a_chunks_steps_are_its_share_of_a_pass(tmp_path):
    s = _stream(tmp_path, [0.02, 0.98], k=1)  # a pass: 1,000 rows / 10 = 100 steps
    lefts = set()
    for _ in range(20):
        s._advance()
        lefts.add((int(s.chunk["x"][0]), s.left))
    assert lefts == {(0, 2), (1, 98)}  # before: 50 each
    s.pool.shutdown()
