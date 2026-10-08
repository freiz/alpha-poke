"""The damage-based input features (rust extra.rs): the fast in-place path against the reference
(a state copy per damage call) on real states, bitwise. Run after any change to extra.rs.

Usage: uv run python scripts/check_extra.py [--n 40000]

States: training positions of the full data set (both views) and self-play root states (if any);
fails unless every float is bitwise equal."""

import argparse
import glob
import json

import alpha_search
import numpy as np
import pyarrow.parquet as pq


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40000)
    a = ap.parse_args()
    states = []
    for f in sorted(glob.glob("data/train/v5/*.parquet"))[1::7]:
        if pq.read_metadata(f).num_rows:
            states += pq.read_table(f, columns=["state"]).column("state").to_pylist()[:10000]
        if len(states) >= a.n:
            break
    sp = sorted(glob.glob("data/selfplay/gen*/decisions-w*.jsonl"))
    for f in sp[:4]:
        with open(f) as fh:
            for i, line in enumerate(fh):
                if i >= a.n // 8:
                    break
                states.append(json.loads(line)["state"])
    bad = 0
    for flip in (False, True):
        fe, fg = alpha_search.featurize_extra(states, flip)
        re_, rg = alpha_search.featurize_extra(states, flip, reference=True)
        e1, e2 = np.frombuffer(fe, np.uint32), np.frombuffer(re_, np.uint32)
        g1, g2 = np.frombuffer(fg, np.uint32), np.frombuffer(rg, np.uint32)
        n_ent = int((e1 != e2).sum())
        n_glob = int((g1 != g2).sum())
        print(f"flip={flip}: {len(states)} states, differing floats: entity {n_ent}, "
              f"global {n_glob}")  # fmt: skip
        bad += n_ent + n_glob
    print("OK (bitwise identical)" if bad == 0 else f"FAIL: {bad} differing floats")
    raise SystemExit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
