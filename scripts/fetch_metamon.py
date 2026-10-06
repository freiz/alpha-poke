"""Download Metamon's raw replay dataset (HF jakegrigsby/metamon-raw-replays) and keep one format.

Usage: uv run python scripts/fetch_metamon.py [--format gen9ou] [--keep-raw]

Every shard (46 x ~125 MB, 5.7 GB in total) is downloaded, checked against its sha256, filtered
to ``formatid == --format`` and written to data/metamon/<format>/<shard>.parquet; the raw shard
is then deleted (unless --keep-raw). Finished shards are skipped, so the script can be rerun.
Usernames are pseudonymized by Metamon; the dataset card states no license (public Showdown
replays): local research use only, not redistributed (design D13).
"""

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

REPO = "jakegrigsby/metamon-raw-replays"
API = f"https://huggingface.co/api/datasets/{REPO}/tree/main/data"
FILE = f"https://huggingface.co/datasets/{REPO}/resolve/main/"
ROOT = Path("data/metamon")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--keep-raw", action="store_true")
    a = ap.parse_args()
    raw_dir, out_dir = ROOT / "raw", ROOT / a.format
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(API, timeout=60) as r:
        shards = sorted(json.load(r), key=lambda x: x["path"])
    total_kept = 0
    for i, sh in enumerate(shards):
        name = Path(sh["path"]).name
        out = out_dir / name
        if out.exists():
            total_kept += pq.read_metadata(out).num_rows
            continue
        raw = raw_dir / name
        want = sh["lfs"]["oid"]
        if not raw.exists() or sha256(raw) != want:
            t0 = time.time()
            tmp = raw.with_suffix(".part")
            urllib.request.urlretrieve(FILE + sh["path"], tmp)
            if sha256(tmp) != want:
                tmp.unlink()
                raise RuntimeError(f"sha256 mismatch for {name}")
            tmp.rename(raw)
            dl = f"{sh['size'] / 1e6:.0f} MB in {time.time() - t0:.0f}s"
        else:
            dl = "cached"
        table = pq.read_table(raw)
        kept = table.filter(pc.equal(table["formatid"], a.format))
        pq.write_table(kept, out, compression="zstd")
        total_kept += kept.num_rows
        if not a.keep_raw:
            raw.unlink()
        print(
            f"[{i + 1}/{len(shards)}] {name}: {dl}; kept {kept.num_rows}/{table.num_rows} "
            f"(total {total_kept})",
            flush=True,
        )
    print(f"done: {total_kept} {a.format} replays in {out_dir}")


if __name__ == "__main__":
    main()
