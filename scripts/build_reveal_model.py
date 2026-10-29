"""Fit the move-reveal model (negative evidence for hidden moves, alpha_poke.belief.reveal).

Usage: uv run python scripts/build_reveal_model.py [--format gen9ou] [--cutoff 1500]
Writes data/derived/belief/reveal_model.pkl and prints a few examples.
"""

import argparse
from pathlib import Path

from alpha_poke.analysis.tables import REPLAYS
from alpha_poke.belief.reveal import RevealModel, replay_first_use_rows
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--cutoff", type=int, default=1500)
    a = ap.parse_args()
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / f"{a.format}-{a.cutoff}.json")
    rows = list(replay_first_use_rows(REPLAYS, a.format))
    model = RevealModel.fit(rows, stats)
    model.save()
    print(f"{len(rows)} rows; {sum(1 for k in model.F if k[0])} species-move and "
          f"{sum(1 for k in model.F if not k[0])} pooled first-use curves")  # fmt: skip
    examples = [
        ("Great Tusk", "rapidspin"), ("Gholdengo", "nastyplot"), ("Ting-Lu", "stealthrock"),
        ("Kingambit", "suckerpunch"), ("Enamorus", "healingwish"), ("", "trick"),
        ("Dragonite", "extremespeed"), ("", "protect"),
    ]  # fmt: skip
    for sp, mv in examples:
        print(f"  {sp or '(pooled)':12s} {mv:13s} r(t) for t=1,2,4,8:",
              [round(model.r(sp, mv, t), 2) for t in (1, 2, 4, 8)])  # fmt: skip
