"""Download the released model (a GitHub release of this repository) into the places the code
reads it from: the network to selfplay.runner.MODEL, the belief / reveal models to
data/derived/belief/; then the month of Smogon usage statistics the belief was built from (one
file from smogon.com: the search reads it for speed spreads and item fallbacks). Enough to play
and evaluate the bot without the replay datasets.

  uv run python scripts/fetch_model.py                 # the release below
  uv run python scripts/fetch_model.py --base-url file:///path/to/assets/   # a local copy

Every file is checked against its SHA-256 below before it is moved into place (the belief
models are pickles: only these exact bytes are loaded). Existing files with the right hash are
skipped; a file with another hash is kept unless --force (a locally rebuilt model).
A private repository's assets need the GitHub CLI (``gh release download``); the script uses it
when the plain download is refused.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from alpha_poke import paths
from alpha_poke.selfplay.runner import MODEL

REPO = "freiz/alpha-poke"
TAG = "v0.1.0"
# v6arch-pp-v75: trained on human games only (no self-play), doc/model_card.md
ASSETS = {
    "best.safetensors": (paths.ROOT / MODEL,
                         "1c3440d1d7c76bb840b3fbf817046627c800b552f699cc5ddc664834f529c92d"),
    "config.json": (paths.ROOT / MODEL,
                    "8e8740402520b2a0b3329877d3549e2c03de67e09a32542b5cc45c46a5b39671"),
    "belief_model.pkl": (paths.BELIEF,
                         "473aab2a1e5df6f98a06821937b0cc4b6cc66cea77c9d9211d061f43db5aab63"),
    "reveal_model.pkl": (paths.BELIEF,
                         "9ae5984ab6ce8e41bc388d479388be8b144707987552ae2bd2d217f17f91f706"),
}  # fmt: skip
STATS = ("2026-09", "chaos", "gen9ou", 1825)  # data/raw/smogon/2026-09/chaos/gen9ou-1825.json


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(name: str, base_url: str, tmp: Path) -> Path:
    out = tmp / name
    try:
        with urllib.request.urlopen(base_url + name, timeout=60) as r, open(out, "wb") as f:
            shutil.copyfileobj(r, f)
    except OSError as e:
        if not base_url.startswith("https://github.com/") or shutil.which("gh") is None:
            raise
        print(f"  {e}; trying gh release download")
        subprocess.run(["gh", "release", "download", TAG, "--repo", REPO, "--pattern", name,
                        "--dir", str(tmp), "--clobber"], check=True)  # fmt: skip
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=f"https://github.com/{REPO}/releases/download/{TAG}/")
    ap.add_argument("--force", action="store_true", help="replace files with another hash")
    a = ap.parse_args()
    base = a.base_url if a.base_url.endswith("/") else a.base_url + "/"
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, (where, digest) in ASSETS.items():
            dest = where / name
            if dest.exists() and sha256(dest) == digest:
                print(f"ok (present): {dest.relative_to(paths.ROOT)}")
                continue
            if dest.exists() and not a.force:
                print(f"kept: {dest.relative_to(paths.ROOT)} differs from the release (--force)")
                continue
            got = download(name, base, Path(tmp))
            if sha256(got) != digest:
                print(f"FAILED: {name}: SHA-256 mismatch, not installed")
                failed += 1
                continue
            where.mkdir(parents=True, exist_ok=True)
            shutil.move(got, dest)
            print(f"installed: {dest.relative_to(paths.ROOT)}")
    if not any(paths.SMOGON.glob("*/chaos/gen9ou-1825.json")):
        from alpha_poke.data.smogon_stats import SmogonStatsClient

        got = SmogonStatsClient().fetch_file(*STATS)
        print(f"usage statistics: {got.relative_to(paths.ROOT) if got else 'FAILED'}")
        failed += got is None
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
