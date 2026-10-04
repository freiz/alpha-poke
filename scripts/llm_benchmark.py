"""Run the task-specific LLM benchmark across models (budget-capped, cached).

Usage:
  uv run python scripts/llm_benchmark.py --models google/gemini-3.8-flash \
      deepseek/deepseek-v4.1-flash
  uv run python scripts/llm_benchmark.py --models ... --budget 3 --n-set 30 --n-naming 12

Writes doc/llm_benchmark.md and data/llm_bench/<model>.json (raw answers for review).
"""

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from alpha_poke.analysis.archetypes import team_table
from alpha_poke.analysis.cores import mine_cores
from alpha_poke.analysis.sets import mine_sets
from alpha_poke.analysis.tables import OUT
from alpha_poke.belief.priors import CorePrior, SmogonPrior, SpeciesReplayPrior, TeamPrior
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats
from alpha_poke.llm import BudgetExceeded, LLMClient, TruncatedResponse, ledger_total
from alpha_poke.llm_bench import (
    baseline_set_completion,
    build_set_completion,
    build_speed,
    build_type_chart,
    grade_naming,
    grade_set_completion,
    grade_simple,
    run_naming,
    run_set_completion,
    run_speed,
    run_type_chart,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--budget", type=float, default=3.0, help="total USD across all LLM calls")
    ap.add_argument("--n-set", type=int, default=30)
    ap.add_argument("--n-naming", type=int, default=12)
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--reasoning", default="low", help="reasoning effort for every model")
    ap.add_argument(
        "--skip",
        nargs="*",
        default=[],
        metavar="MODEL:TASK",
        help="skip a task for a model, e.g. deepseek/deepseek-v4.1-flash:set",
    )
    a = ap.parse_args()

    g = pd.read_parquet(OUT / f"{a.format}_games.parquet").sort_values("uploadtime")
    m = pd.read_parquet(OUT / f"{a.format}_mons.parquet")
    split = g.uploadtime.iloc[int(len(g) * 0.8)]
    tr = set(g.id[g.uploadtime < split])
    train, test = m[m.id.isin(tr) & m.brought], m[~m.id.isin(tr) & m.brought]
    teams = team_table(m[m.id.isin(tr)])
    cores = mine_cores(
        [tuple(t) for t in teams.species],
        won=teams.won.tolist(),
        max_size=6,
        absorb=0.6,
        min_support=max(30, len(teams) // 300),
    )
    month = time.strftime("%Y-%m", time.gmtime(split))
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir() and p.name < month)
    smog = SmogonPrior(
        UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / f"{a.format}-1825.json")
    )
    team_prior = TeamPrior(train, CorePrior(train, cores, SpeciesReplayPrior(train, smog)))
    sets = mine_sets(m[m.id.isin(tr)])

    set_qs = build_set_completion(test, a.n_set)
    pool = m.species.value_counts().head(80).index.tolist()
    tc_qs, sp_qs = build_type_chart(pool), build_speed(pool)
    naming_cores = cores[: a.n_naming]

    results = {
        "baseline(team prior)": {
            "set": grade_set_completion(set_qs, baseline_set_completion(team_prior, set_qs))
        }
    }
    raw_dir = Path("data/llm_bench")
    raw_dir.mkdir(parents=True, exist_ok=True)
    for model in a.models:
        c = LLMClient(
            model=model, budget_usd=a.budget, max_tokens=8000, reasoning_effort=a.reasoning
        )
        res, raw = {}, {}
        t0 = time.monotonic()

        def run_task(name: str, c: LLMClient):
            if name == "set":
                x = run_set_completion(c, set_qs)
                return grade_set_completion(set_qs, x), x
            if name == "type_chart":
                x = run_type_chart(c, tc_qs)
                return grade_simple(tc_qs, x), x
            if name == "speed":
                x = run_speed(c, sp_qs)
                return grade_simple(sp_qs, x), x
            x = run_naming(c, naming_cores, sets, m)
            return grade_naming(x), x

        errors = {}
        for name in ("set", "type_chart", "speed", "naming"):
            if f"{model}:{name}" in a.skip:
                errors[name] = "skipped"
                continue
            try:
                res[name], raw[name] = run_task(name, c)
            except BudgetExceeded as e:
                errors[name] = str(e)
                break
            except (TruncatedResponse, ValueError) as e:
                errors[name] = str(e)[:200]
        if errors:
            res["error"] = errors
        res["cost_usd"] = c.spent_usd
        res["calls"] = c.calls
        res["reasoning_tokens"] = c.reasoning_tokens
        res["wall_s"] = time.monotonic() - t0
        results[model] = res
        (raw_dir / f"{model.replace('/', '__')}.json").write_text(
            json.dumps(raw, indent=1, ensure_ascii=False, default=str)
        )
        print(model, json.dumps(res, indent=1, default=str), flush=True)

    rows = []
    for name, r in results.items():
        s, n = r.get("set", {}), r.get("naming", {})
        rows.append(
            {
                "model": name,
                "item@1": s.get("item_top1"),
                "item@3": s.get("item_top3"),
                "tera@1": s.get("tera_top1"),
                "moves@4": s.get("move_recall@4"),
                "bad_moves": s.get("bad_moves_rate"),
                "type_chart": r.get("type_chart", {}).get("accuracy"),
                "speed": r.get("speed", {}).get("accuracy"),
                "tag_P": n.get("tag_precision"),
                "tag_R": n.get("tag_recall"),
                "viol/core": n.get("grounding_violations_per_core"),
                "viol_rate": n.get("violation_rate"),
                "json_ok": n.get("json_ok"),
                "cost$": r.get("cost_usd"),
                "wall_s": r.get("wall_s"),
            }
        )
    df = pd.DataFrame(rows)
    md = [
        "# LLM benchmark（任务专用，英文输入输出）",
        "",
        f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}；脚本 `scripts/llm_benchmark.py`；"
        f"累计 LLM 花费（账本）${ledger_total():.2f}。",
        "",
        f"- set：{len(set_qs)} 道配置补全（队伍 + 目标 + 1 个已用招式 → 道具/太晶/其余招式），"
        "与之后 replay 中暴露的真实信息比对；bad_moves = 预测了不存在或学不会的招式的比例。",
        f"- type_chart：{len(tc_qs)} 道属性克制；speed：{len(sp_qs)} 道种族速度比较。",
        f"- naming：{len(naming_cores)} 个挖掘出的核心；tag_P/R 只统计明确标签"
        "（天气、黏黏网、受队）；viol = 描述核心时提到但 DATA 中没有的招式/道具。",
        "",
        df.to_markdown(index=False, floatfmt=".3f"),
        "",
    ]
    Path("doc/llm_benchmark.md").write_text("\n".join(md))
    print(df.to_string())


if __name__ == "__main__":
    main()
