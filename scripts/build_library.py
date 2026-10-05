"""Mine cores + set archetypes from the parsed replays and name them with the LLM.

Usage: uv run python scripts/build_library.py [--format gen9ou] [--model google/gemini-3.8-flash]
Writes data/library/<format>_library.json and doc/archetype_library.md. Cached LLM calls are
free on re-runs; the global budget (LLM_BUDGET_USD) applies.
"""

import argparse
from pathlib import Path

from alpha_poke.analysis.tables import build
from alpha_poke.library import build_library, library_markdown
from alpha_poke.llm import ledger_total

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    build(a.format)
    lib = build_library(a.format, a.model)
    Path("doc/archetype_library.md").write_text(library_markdown(lib))
    print(
        f"{len(lib['cores'])} cores, {len(lib['sets'])} species; "
        f"cost this run ${lib['llm_cost_usd']:.3f}; ledger total ${ledger_total():.3f}"
    )
