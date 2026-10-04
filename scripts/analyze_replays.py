"""Rebuild the parsed tables and write the replay analysis report.

Usage: uv run python scripts/analyze_replays.py [--out doc/analysis_gen9ou.md]
"""

import argparse
from pathlib import Path

from alpha_poke.analysis.report import write_report
from alpha_poke.analysis.tables import build

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--out", default="doc/analysis_gen9ou.md")
    a = ap.parse_args()
    build(a.format)
    write_report(Path(a.out), a.format)
