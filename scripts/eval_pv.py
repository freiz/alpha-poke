"""Evaluate trained policy / value runs on one validation set (comparable across datasets).

Usage: uv run --group train python scripts/eval_pv.py --data v2s --since 1776921722 \
           data/train/v1/runs/v1-medium-residual data/train/v2s/runs/v2s-mlp ...

Positions of ``--data`` from games uploaded at / after ``--since`` (default: v1's validation
cutoff, so the games are in every run's validation split when the run used that cutoff or a
later one); same metrics as scripts/train_pv.py. v1 checkpoints (no arch / history keys, the
embedding tables at the top level) load as the MLP without history.
"""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import torch

from alpha_poke.train.load import load_run as _load_run

_spec = importlib.util.spec_from_file_location("train_pv", Path(__file__).with_name("train_pv.py"))
train_pv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(train_pv)

load_run = _load_run  # alpha_poke.train.load


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--data", required=True)
    ap.add_argument("--since", type=int, default=1776921722, help="unix time (v1 val cutoff)")
    a = ap.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # only the anchor games' rows are read (the full set does not fit in memory)
    caches, sizes = train_pv.shard_caches(a.data)
    small = train_pv.load_small(caches, sizes)
    idx = np.flatnonzero(small["uploadtime"] >= a.since)
    # whole games: a game counts by its latest upload time (as in train_pv)
    games = set(small["game"][idx].tolist())
    d = train_pv.gather(caches, small, np.flatnonzero(np.isin(small["game"], list(games))))
    idx = np.arange(len(d["game"]))
    print(f"{a.data}: {len(idx)} positions from {len(games)} games uploaded >= {a.since}")
    for r in a.runs:
        m = train_pv.evaluate(load_run(Path(r), device), d, idx, device)
        keys = (
            "ce",
            "top1",
            "top2",
            "top3",
            "top5",
            "top1_switch",
            "top3_switch",
            "ce_switch",
            "bce",
            "bce_t12",
            "vacc",
            "value_ece",
            "opp_act_acc",
            "opp_act_top3",
            "set_item_net",
            "set_item_belief",
            "set_ability_net",
            "set_ability_belief",
            "set_tera_net",
            "set_tera_belief",
            "set_move_net",
            "set_move_belief",
            "faint_bce",
            "faint_acc",
            "margin_ce",
            "margin_acc",
            "turns_mae",
            "ce_forced",
            "top1_forced",
            "ce_turn",
            "ce_blind",
            "bce_all",
            "bce_blind",
            "ce_turn_w",
            "bce_all_w",
        )
        print(json.dumps({"run": Path(r).name} | {k: round(m[k], 4) for k in keys if k in m}))


if __name__ == "__main__":
    main()
