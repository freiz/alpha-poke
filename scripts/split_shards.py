"""Split oversized replay shards into Metamon-sized ones (whole games, upload order), and their
training shards along with them (positions follow their game), streaming: neither file is
read whole. Featurization holds a shard in memory (train_pv.MAX_SHARD_ROWS); the HF dump's
shards hold up to 193k games where Metamon's hold <= 58k (2026-10-09: one of 3.7M positions took
41.5 GB and WSL down).

  uv run python scripts/split_shards.py data/replays_hf/gen9ou/hf-part12.parquet --train v5

Writes <stem>-<k>.parquet next to each, drops the old feature cache, and moves the originals
to <dir>/unsplit/ (outside the source globs).
"""

import argparse
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class Rotating:
    """Writers <dir>/<stem>-<k>.parquet, opened on first use."""

    def __init__(self, d: Path, stem: str, schema: pa.Schema):
        self.d, self.stem, self.schema, self.w = d, stem, schema, {}

    def write(self, k: int, table: pa.Table) -> None:
        if k not in self.w:
            self.w[k] = pq.ParquetWriter(self.d / f"{self.stem}-{k}.tmp", self.schema,
                                         compression="zstd")  # fmt: skip
        self.w[k].write_table(table)

    def close(self) -> list[Path]:
        out = []
        for k, w in sorted(self.w.items()):
            w.close()
            tmp = self.d / f"{self.stem}-{k}.tmp"
            dst = tmp.with_suffix(".parquet")
            tmp.rename(dst)
            out.append(dst)
        return out


def split(src: Path, games: int, train: Path | None) -> None:
    f = pq.ParquetFile(src)
    n = f.metadata.num_rows
    k_of: dict[str, int] = {}
    out = Rotating(src.parent, src.stem, f.schema_arrow)
    seen = 0
    for batch in f.iter_batches(batch_size=2000):
        ids = batch.column("id").to_pylist()
        ks = [(seen + i) // games for i in range(len(ids))]
        seen += len(ids)
        for k in sorted(set(ks)):
            mask = pa.array([x == k for x in ks])
            out.write(k, pa.Table.from_batches([batch]).filter(mask))
        k_of.update(zip(ids, ks, strict=True))
    files = out.close()
    print(f"{src}: {n} games -> {[(p.name, pq.read_metadata(p).num_rows) for p in files]}")
    if train is not None:
        t = train / src.name
        tf = pq.ParquetFile(t)
        tout = Rotating(train, t.stem, tf.schema_arrow)
        for batch in tf.iter_batches(batch_size=50_000):
            ks = [k_of[g] for g in batch.column("game").to_pylist()]
            for k in sorted(set(ks)):
                mask = pa.array([x == k for x in ks])
                tout.write(k, pa.Table.from_batches([batch]).filter(mask))
        tfiles = tout.close()
        rows = [pq.read_metadata(p).num_rows for p in tfiles]
        assert sum(rows) == tf.metadata.num_rows, (sum(rows), tf.metadata.num_rows)
        print(f"{t}: {tf.metadata.num_rows} positions -> {[p.name for p in tfiles]} {rows}")
        cache = train / "features" / (t.stem + ".npz")
        cache.unlink(missing_ok=True)
        (train / "unsplit").mkdir(exist_ok=True)
        shutil.move(t, train / "unsplit" / t.name)
    (src.parent / "unsplit").mkdir(exist_ok=True)
    shutil.move(src, src.parent / "unsplit" / src.name)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+")
    ap.add_argument("--games", type=int, default=45_000, help="games per new shard")
    ap.add_argument("--train", default="", help="also split data/train/<name>/<stem>.parquet")
    a = ap.parse_args()
    for s in a.src:
        split(Path(s), a.games, Path("data/train") / a.train if a.train else None)
