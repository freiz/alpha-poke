"""Compare preview-time belief priors on held-out (later) replays.

Usage: uv run python scripts/eval_belief_priors.py [--test-frac 0.2]
"""

import argparse
import time
from pathlib import Path

import pandas as pd

from alpha_poke.analysis.archetypes import team_table
from alpha_poke.analysis.cores import mine_cores
from alpha_poke.analysis.tables import OUT
from alpha_poke.belief.evaluate import evaluate
from alpha_poke.belief.priors import CorePrior, SmogonPrior, SpeciesReplayPrior, TeamPrior
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--cutoff", type=int, default=1825)
    a = ap.parse_args()

    g = pd.read_parquet(OUT / f"{a.format}_games.parquet").sort_values("uploadtime")
    m = pd.read_parquet(OUT / f"{a.format}_mons.parquet")
    split_t = g.uploadtime.iloc[int(len(g) * (1 - a.test_frac))]
    train_ids = set(g.id[g.uploadtime < split_t])
    train = m[m.id.isin(train_ids) & m.brought]
    test = m[~m.id.isin(train_ids) & m.brought]
    test_month = time.strftime("%Y-%m", time.gmtime(split_t))
    months = sorted(
        p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir() and p.name < test_month
    )
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / f"{a.format}-{a.cutoff}.json")
    print(
        f"train {len(train_ids)} games (< {time.strftime('%F', time.gmtime(split_t))}), "
        f"test {g.id.nunique() - len(train_ids)} games; Smogon stats {months[-1]}-{a.cutoff}"
    )

    teams = team_table(m[m.id.isin(train_ids)])
    cores = mine_cores(
        [tuple(t) for t in teams.species],
        max_size=6,
        absorb=0.6,
        min_support=max(30, len(teams) // 300),
    )
    smog = SmogonPrior(stats)
    sp = SpeciesReplayPrior(train, smog)
    core = CorePrior(train, cores, sp)
    team = TeamPrior(train, core)
    rows = {}
    for prior in (smog, sp, core, team):
        rows[prior.name] = evaluate(prior, test)
    df = pd.DataFrame(rows).T
    cols = ["item_nll", "item_top1", "tera_nll", "tera_top1", "move_nll", "move_recall@4"]
    print(df[cols].round(3).to_string())
    print(df[["n_item", "n_tera", "n_move"]].iloc[0].astype(int).to_dict())

    known = team.known
    is_known = test.team.isin(known)
    print(f"\ntest mons whose exact team was seen >=5 times in train: {is_known.mean():.1%}")
    sub = test[is_known]
    rows = {p.name: evaluate(p, sub) for p in (smog, sp, core, team)}
    print("on that subset:")
    print(pd.DataFrame(rows).T[cols].round(3).to_string())


if __name__ == "__main__":
    main()
