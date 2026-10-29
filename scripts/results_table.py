"""Regenerate the tables in doc/results.md from the logs (training runs and arena / external runs).

Usage: uv run python scripts/results_table.py [--write]

Training: data/train/<data>/runs/<run>/{config.json, metrics.jsonl} (best-checkpoint validation
metrics, final training metrics, data size). Evaluation: data/eval/*.jsonl, one row per run, with
the settings from the run's .meta.json when it has one (runs from 2026-10-06 on). Without --write
the tables are printed; with it they replace the generated part of doc/results.md (between the
markers) and the hand-written part is kept.
"""

import argparse
import glob
import json
import math
import os
import re
from pathlib import Path

from alpha_poke.eval.arena import summarize

DOC = Path("doc/results.md")
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"
SETTINGS = ("ALPHA_SEARCH_MS", "ALPHA_SEARCH_THREADS")


def n_params(path: Path) -> int | None:
    """Parameter count from the safetensors header (8-byte length + JSON with the shapes)."""
    if not path.exists():
        return None
    with open(path, "rb") as f:
        header = json.loads(f.read(int.from_bytes(f.read(8), "little")))
    return sum(math.prod(t["shape"]) for k, t in header.items() if k != "__metadata__")


def training_table() -> list[str]:
    out = [
        "| run | params | positions (train / val) | epochs | min | val policy CE | top-1 | top-3 "
        "| val value BCE | value acc | early / mid / late | ECE | train−val gap (policy / value) |",
        "|" + "---|" * 13,
    ]
    for cfg in sorted(glob.glob("data/train/*/runs/*/config.json")):
        d = Path(cfg).parent
        c = json.loads(Path(cfg).read_text())
        v = c["val"]
        ev = [json.loads(line) for line in open(d / "metrics.jsonl")]
        data = next((e for e in ev if e["event"] == "data"), {})
        done = next((e for e in ev if e["event"] == "done"), {})
        train = [e for e in ev if e["event"] == "train"]
        last = train[-1] if train else {}
        p = n_params(d / "best.safetensors")
        gap = (
            f"{v['ce'] - last['policy_ce']:.3f} / {v['bce'] - last['value_bce']:.3f}"
            if last
            else "—"
        )
        out.append(
            f"| {d.parent.parent.name}/{d.name} | {p / 1e3:.0f}k | "
            f"{data.get('train', 0) / 1e6:.2f}M / {data.get('val', 0) / 1e3:.0f}k | "
            f"{last.get('epoch', 0):.1f} | {done.get('minutes', '—')} | {v['ce']:.3f} | "
            f"{v['top1']:.1%} | {v['top3']:.1%} | {v['bce']:.4f} | {v['vacc']:.1%} | "
            f"{v['vacc_early']:.1%} / {v['vacc_mid']:.1%} / {v['vacc_late']:.1%} | "
            f"{v['value_ece']:.3f} | {gap} |"
        )
    return out


def eval_table(min_games: int) -> list[str]:
    out = [
        "| run (log) | A | B | games | A win | paired ± 95% | fallbacks | commit | settings |",
        "|" + "---|" * 9,
    ]
    for f in sorted(glob.glob("data/eval/*.jsonl")):
        rows = [json.loads(line) for line in open(f) if line.strip()]
        if len(rows) < min_games:
            continue
        s = summarize(rows)
        name = os.path.basename(f)[:-6]
        m = re.match(r"(\d{8}-\d{6})_(.+?)_vs_(.+?)(_heldout)?(@\w+)?$", name)
        run, a, b = (m.group(1), m.group(2), m.group(3)) if m else (name, "?", "?")
        meta_p = Path(f).with_suffix(".meta.json")
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        env = meta.get("env", {})
        settings = ", ".join(f"{k[6:].lower()}={env[k]}" for k in SETTINGS if k in env)
        if m and m.group(4):
            settings = ("heldout; " + settings).strip("; ")
        commit = meta.get("commit", "") + ("+" if meta.get("dirty") else "")
        fb = sum((r.get("search_fallbacks_a") or 0) for r in rows) if meta else "—"
        out.append(
            f"| {run} | {a} | {b} | {s['games']} | {s['win_rate']:.1%} | "
            f"{s['paired_mean']:.1%} ± {s['ci95_paired']:.1%} | {fb} | {commit or '—'} | "
            f"{settings or '—'} |"
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--min-games", type=int, default=20, help="skip smoke tests / aborted runs")
    a = ap.parse_args()
    gen = [
        BEGIN,
        "",
        "### Training runs (generated)",
        "",
        *training_table(),
        "",
        f"### Evaluation runs (generated; runs with ≥ {a.min_games} games)",
        "",
        *eval_table(a.min_games),
        "",
        END,
    ]
    text = "\n".join(gen)
    if not a.write:
        print(text)
        return
    doc = DOC.read_text()
    i, j = doc.index(BEGIN), doc.index(END) + len(END)
    DOC.write_text(doc[:i] + text + doc[j:])
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
