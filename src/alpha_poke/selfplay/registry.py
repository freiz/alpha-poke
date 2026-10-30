"""The model registry (data/selfplay/registry/; git-ignored, exp/ until 2026-10-28): every network
version with what made it and how it played.

  matches.jsonl      one row per head-to-head evaluation: models, settings (search, iterations or
                     time, team pool), games, pairs, paired mean and its 95% CI, the SPRT
                     ratio / decision, the log, and ``elo``: whether it enters the Elo fit
                     (promotion-grade evaluations; diagnostics such as policy-only games or
                     A = B controls are kept but not fitted)
  models.json        one entry per model: run, weights hash, parent, generation, training
                     settings, offline metrics, promoted or not, the generations it played,
                     estimated Elo (95% CI) and its matches

Elo: weighted least squares over the fitted matches. Each match gives an Elo difference
400 log10(p / (1 - p)) with the variance of its paired mean (delta method). The anchor (the self-play
start) is fixed at ANCHOR_ELO; a model connected to it by no fitted match has no Elo. Rebuilt from
state.json, the run directories and matches.jsonl by ``write()`` (scripts/selfplay.py
registry, and after every evaluation)."""

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from alpha_poke import paths
from alpha_poke.selfplay.runner import MODEL

ROOT = paths.ROOT
EXP = paths.SELFPLAY / "registry"
MATCHES = EXP / "matches.jsonl"
MODELS = EXP / "models.json"
RUNS = paths.TRAIN  # <data>/runs/<run>


def run_dir(name: str) -> Path:
    """A run's directory by name (data/train/*/runs/<name>; the v5 one if none exists yet)."""
    found = sorted(RUNS.glob(f"*/runs/{name}"))
    if len(found) > 1:  # (the name alone would pick one of them)
        raise ValueError(f"run name {name} is ambiguous: {[str(f) for f in found]}")
    return found[0] if found else RUNS / "v5" / "runs" / name


# 2026-10-09: self-play restarted from v5-glu (the human-data network); the earlier run is in
# registry/archive-2026-10-08/. 2026-10-20: restarted from v0 (lineage r2, scripts/selfplay.py); the
# v5-glu lineage's registry is in registry/archive-2026-10-20/. 2026-10-23: the start v6arch-pp (v7.3)
# before r2's first generation (no matches yet), 2026-10-26 v6arch-pp-v75 (v7.5): the anchor is
# the start's name (runner.MODEL)
ANCHOR, ANCHOR_ELO = Path(MODEL).name, 1500.0


def name_of(run: str | None) -> str | None:
    return Path(run).name if run else None


def read_matches() -> list[dict]:
    if not MATCHES.exists():
        return []
    return [json.loads(line) for line in MATCHES.read_text().splitlines() if line.strip()]


def add_match(row: dict) -> None:
    """Append a match (replaces an earlier row with the same id)."""
    EXP.mkdir(parents=True, exist_ok=True)
    rows = [r for r in read_matches() if r["id"] != row["id"]]
    rows.append(row)
    MATCHES.write_text("".join(json.dumps(r) + "\n" for r in rows))


def match_row(mid: str, a: str, b: str, res: dict, *, kind: str, elo: bool, **extra) -> dict:
    """A matches.jsonl row from an evaluation result (eval.arena.summarize + settings)."""
    keys = (
        "games",
        "pairs",
        "paired_mean",
        "ci95_paired",
        "win_rate",
        "ties",
        "failed_games",
        "llr",
        "decision",
        "search",
        "search_iterations",
        "search_ms",
        "pool",
        "log",
    )
    row = {"id": mid, "a": name_of(a), "b": name_of(b), "kind": kind, "elo": elo,
           "date": time.strftime("%Y-%m-%d")}  # fmt: skip
    return row | {k: res.get(k) for k in keys if k in res} | extra


def fit_elo(matches: list[dict]) -> dict[str, tuple[float, float]]:
    """name -> (Elo, 95% half-width) from the matches with ``elo``; the anchor fixed."""
    rows = [m for m in matches if m.get("elo") and m.get("pairs") and m.get("ci95_paired")]
    names = sorted({m["a"] for m in rows} | {m["b"] for m in rows})
    if ANCHOR not in names:
        return {}
    # models connected to the anchor
    linked, frontier = {ANCHOR}, [ANCHOR]
    while frontier:
        x = frontier.pop()
        for m in rows:
            for u, v in ((m["a"], m["b"]), (m["b"], m["a"])):
                if u == x and v not in linked:
                    linked.add(v)
                    frontier.append(v)
    free = [n for n in names if n in linked and n != ANCHOR]
    if not free:
        return {ANCHOR: (ANCHOR_ELO, 0.0)}
    idx = {n: i for i, n in enumerate(free)}
    a_mat, b_vec = np.zeros((len(free), len(free))), np.zeros(len(free))
    for m in rows:
        if m["a"] not in linked or m["b"] not in linked:
            continue
        p = min(max(m["paired_mean"], 0.01), 0.99)
        se_p = m["ci95_paired"] / 1.96
        d = 400 * math.log10(p / (1 - p))
        se = max(400 / math.log(10) * se_p / (p * (1 - p)), 1.0)
        w = 1 / se**2
        # residual: R_a - R_b - d; the anchor's rating is a constant
        coef = {}
        for n, sgn in ((m["a"], 1.0), (m["b"], -1.0)):
            if n == ANCHOR:
                d -= sgn * ANCHOR_ELO
            else:
                coef[idx[n]] = coef.get(idx[n], 0.0) + sgn
        for i, ci in coef.items():
            b_vec[i] += w * ci * d
            for j, cj in coef.items():
                a_mat[i, j] += w * ci * cj
    cov = np.linalg.pinv(a_mat)
    sol = cov @ b_vec
    out = {ANCHOR: (ANCHOR_ELO, 0.0)}
    for n, i in idx.items():
        out[n] = (round(float(sol[i]), 1), round(1.96 * math.sqrt(max(cov[i, i], 0.0)), 1))
    return out


def _sha(run: Path) -> str | None:
    f = run / "best.safetensors"
    if not f.exists():
        return None
    return hashlib.sha256(f.read_bytes()).hexdigest()[:16]


def _run_info(run: Path) -> dict:
    """Training settings and last validation of a run (its metrics.jsonl)."""
    info: dict = {}
    mf = run / "metrics.jsonl"
    if not mf.exists():
        return info
    rows = [json.loads(line) for line in mf.read_text().splitlines()]
    start = next((r for r in rows if r.get("event") == "start"), {})
    args = json.loads(start.get("args", "{}")) if start.get("args") else {}
    keep = (
        "init",
        "selfplay",
        "sp_frac",
        "lr",
        "batch",
        "warmup_frac",
        "sp_per_game",
        "sp_value_passes",
        "sp_value_per_game",
        "sp_value_lambda",
        "seed",
        "epochs",
    )
    info["training"] = {k: args[k] for k in keep if k in args}
    info["training"] |= {"steps": start.get("steps"), "params": start.get("params")}
    info["parent"] = name_of(args.get("init")) or None
    val = [r for r in rows if "ce_turn_w" in r or "sp_kl" in r]
    if val:
        last = val[-1]
        vk = ("ce_turn_w", "bce_all_w", "top1", "value_ece", "hce_true", "opp_act_acc", "sp_kl",
              "sp_top1", "sp_bce", "sp_kl_ref")  # fmt: skip
        info["validation_last"] = {k: round(last[k], 4) for k in vk if last.get(k) is not None}
    info["created"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(mf.stat().st_mtime))
    return info


def _played_by(gen_dir: Path) -> str | None:
    """The network that played a generation's self-play games (their own records)."""
    for f in sorted(gen_dir.glob("games-w*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            line = fh.readline()
        if line:
            return json.loads(line).get("model")
    return None


def build(state: dict) -> dict:
    """models.json from state.json, the runs and the matches."""
    matches = read_matches()
    elo = fit_elo(matches)
    gens = state.get("generations", {})
    models: dict[str, dict] = {}

    def entry(name: str) -> dict:
        if name not in models:
            run = run_dir(name)
            models[name] = {"name": name, "run": str(run.relative_to(ROOT)), "sha256": _sha(run),
                            "generation": None, "role": "variant", "promoted": None,
                            "played_generations": [], **_run_info(run)}  # fmt: skip
        return models[name]

    entry(ANCHOR)["role"] = "human-data baseline (self-play start)"
    for g, v in sorted(gens.items(), key=lambda kv: int(kv[0])):
        tr = v.get("train") or {}
        if tr.get("run"):
            e = entry(name_of(tr["run"]))
            e["generation"], e["role"] = int(g), "generation"
            ev = v.get("eval") or {}
            e["promoted"] = ev.get("promoted")
            for k in ("human_share", "sp_positions", "sp_positions_kept", "recent_gens"):
                if k in tr:
                    e.setdefault("training", {})[k] = tr[k]
        played = _played_by(paths.SELFPLAY / f"gen{g}")
        if played:
            entry(name_of(played))["played_generations"].append(int(g))
    # the network each generation ended with: a variant that became the current network (gen 1's
    # retrain) counts as that generation's, promoted
    for g, run in sorted(state.get("lineage", {}).items(), key=lambda kv: int(kv[0])):
        e = entry(name_of(run))
        e["promoted"] = True
        if e["generation"] is None:
            e["generation"], e["role"] = int(g), "generation (retrained)"
    for m in matches:
        for n in (m["a"], m["b"]):
            entry(n)
    for n, e in models.items():
        e["matches"] = [m["id"] for m in matches if n in (m["a"], m["b"])]
        if n in elo:
            e["elo"], e["elo_ci95"] = elo[n]
        else:
            e["elo"], e["elo_ci95"] = None, None
    current = name_of(state.get("current"))
    if current in models:
        models[current]["current"] = True
    return {"anchor": {"model": ANCHOR, "elo": ANCHOR_ELO},
            "built": time.strftime("%Y-%m-%d %H:%M"),
            "current": current,
            "models": sorted(models.values(),
                             key=lambda e: (e["generation"] is None, e["generation"] or 0,
                                            e["name"]))}  # fmt: skip


def write(state: dict) -> dict:
    EXP.mkdir(parents=True, exist_ok=True)
    out = build(state)
    MODELS.write_text(json.dumps(out, indent=1))
    return out
