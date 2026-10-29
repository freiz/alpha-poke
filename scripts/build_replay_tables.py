"""Parse downloaded replays into data/derived/parsed/<format>_{games,mons}.parquet (incremental).

Usage: uv run python scripts/build_replay_tables.py [--format gen9ou]
"""

import argparse

from alpha_poke.analysis.tables import build

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    build(ap.parse_args().format)
