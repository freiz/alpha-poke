"""Markdown report over the parsed replay tables (+ Smogon usage stats for comparison)."""

import itertools
import math
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from alpha_poke.analysis.archetypes import cluster_teams, team_table
from alpha_poke.analysis.tables import OUT, to_id
from alpha_poke.data.smogon_stats import DEFAULT_DIR as SMOGON_DIR
from alpha_poke.data.smogon_stats import UsageStats


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _ci(n: int) -> str:
    return f"±{196 * math.sqrt(0.25 / n):.1f}" if n else ""


def _latest_smogon(format_id: str, cutoff: int) -> UsageStats | None:
    months = sorted(p.name for p in SMOGON_DIR.glob("*") if p.is_dir())
    for m in reversed(months):
        f = SMOGON_DIR / m / "chaos" / f"{format_id}-{cutoff}.json"
        if f.exists():
            stats = UsageStats.load(f)
            stats.month = m
            return stats
    return None


def build_report(format_id: str = "gen9ou", top: int = 25) -> str:
    g = pd.read_parquet(OUT / f"{format_id}_games.parquet")
    m = pd.read_parquet(OUT / f"{format_id}_mons.parquet")
    sides = 2 * len(g)
    L = [f"# {format_id} replay 分析报告", ""]
    L.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}；脚本 `scripts/analyze_replays.py`。")
    L.append("")

    # ---- dataset ------------------------------------------------------------------------
    lo, hi = g.uploadtime.min(), g.uploadtime.max()
    q = g.rating.quantile([0, 0.5, 1]).tolist()
    diff = g.p1_rating - g.p2_rating
    far = diff.abs() >= 50
    higher_wins = ((diff[far] > 0) == (g.winner[far] == "p1")).mean()
    L += [
        "## 1. 数据概况",
        "",
        f"- 对局数：**{len(g)}**（{time.strftime('%F', time.gmtime(lo))} ～ "
        f"{time.strftime('%F', time.gmtime(hi))}），队伍数 {sides}",
        f"- replay `rating` 字段：最小 {q[0]:.0f}，中位 {q[1]:.0f}，最大 {q[2]:.0f}",
        f"- 回合数：中位 {g.turns.median():.0f}，平均 {g.turns.mean():.1f}，"
        f"90% 分位 {g.turns.quantile(0.9):.0f}",
        f"- p1 胜率 {_pct((g.winner == 'p1').mean())}；无胜者 {int(g.winner.isna().sum())} 场",
        f"- 赛前评分差 ≥50 时，评分高的一方胜率 **{_pct(higher_wins)}**（n={int(far.sum())}）",
        "",
        "> **选择偏差**：下载按 `rating` 字段从高到低进行，而该字段接近双方赛后评分中较低者，",
        '> 因此优先选中了"低分方获胜、评分上涨"的对局（上面那个低于 50% 的数字就是症状）。',
        "> 胜率类结论都受此影响，只能作参考；使用率、搭配、配招类统计受影响较小。",
        "",
    ]

    # ---- usage --------------------------------------------------------------------------
    smog = _latest_smogon(format_id, 1825)
    use = m.groupby("species").agg(
        n=("id", "size"), win=("won", "mean"), lead=("lead", "mean"), brought=("brought", "mean")
    )
    use = use.sort_values("n", ascending=False)
    L += ["## 2. 使用率、首发率与胜率", ""]
    if smog:
        L.append(f"对照：Smogon {smog.month} 使用率统计（门槛 1825）。")
        L.append("")
    L.append("| # | 宝可梦 | 出现率 | Smogon | 首发率 | 上场率 | 胜率（95% CI） |")
    L.append("|---|---|---|---|---|---|---|")
    for i, (sp, r) in enumerate(use.head(top).iterrows(), 1):
        s = ""
        if smog:
            key = next((k for k in smog.species if to_id(k) == to_id(sp.replace("-*", ""))), None)
            s = _pct(smog.species[key].usage) if key else "—"
        L.append(
            f"| {i} | {sp} | {_pct(r.n / sides)} | {s} | {_pct(r.lead)} | {_pct(r.brought)} | "
            f"{_pct(r.win)} {_ci(int(r.n))} |"
        )
    L.append("")

    leads = m[m.lead].species.value_counts()
    L += [
        "**最常见首发**："
        + "、".join(f"{s} {_pct(n / sides)}" for s, n in leads.head(12).items())
        + "",
        "",
    ]

    # ---- cores --------------------------------------------------------------------------
    teams = team_table(m)
    cnt, pair = Counter(), Counter()
    for t in teams.species:
        t = sorted(t)
        cnt.update(t)
        pair.update(itertools.combinations(t, 2))
    rows = [(n, n * len(teams) / (cnt[a] * cnt[b]), a, b) for (a, b), n in pair.items() if n >= 150]
    L += [
        "## 3. 核心搭配（lift 最高的组合，出现 ≥150 次）",
        "",
        "lift = 实际共同出现次数 ÷ 独立时的期望次数，越高说明越是刻意的搭配。",
        "",
        "| 组合 | 次数 | lift |",
        "|---|---|---|",
    ]
    for n, lift, a, b in sorted(rows, key=lambda r: -r[1])[:20]:
        L.append(f"| {a} + {b} | {n} | {lift:.1f} |")
    L.append("")

    # ---- archetypes ---------------------------------------------------------------------
    _, arch = cluster_teams(teams)
    L += [
        "## 4. 队伍类型（按物种组成聚类，k=24）",
        "",
        '"特征"= 在该类中常见且明显多于整体平均的宝可梦。名字需要人工或 LLM 解读。',
        "",
        "| 类 | 队伍数 | 胜率 | 特征 | 常见成员 |",
        "|---|---|---|---|---|",
    ]
    for a in arch:
        L.append(
            f"| {a.cluster} | {a.size} | {_pct(a.win_rate)} {_ci(a.size)} | "
            f"{', '.join(a.signature)} | {', '.join(a.common[:6])} |"
        )
    L.append("")

    # ---- per species sets ---------------------------------------------------------------
    L += [
        "## 5. 常见配置（仅统计 replay 中暴露出来的信息）",
        "",
        "百分比的分母是该宝可梦上场的次数；未暴露的部分不计入，所以招式比例偏低。",
        "",
    ]
    brought = m[m.brought]
    for sp in use.head(15).index:
        d = brought[brought.species == sp]
        n = len(d)
        items = d.item.value_counts().head(4)
        tera = d.tera_type.value_counts().head(4)
        moves = Counter(mv for s in d.moves for mv in s.split("|") if mv)
        abil = d.ability.value_counts().head(2)
        L.append(f"**{sp}**（上场 {n} 次）")
        L.append(
            f"- 道具（暴露 {_pct(d.item.notna().mean())}）："
            + "、".join(f"{k} {_pct(v / n)}" for k, v in items.items())
        )
        L.append(
            f"- 特性（暴露 {_pct(d.ability.notna().mean())}）："
            + "、".join(f"{k} {_pct(v / n)}" for k, v in abil.items())
        )
        L.append(
            f"- 太晶（使用 {_pct(d.tera_type.notna().mean())}）："
            + "、".join(f"{k} {_pct(v / n)}" for k, v in tera.items())
        )
        L.append("- 招式：" + "、".join(f"{k} {_pct(v / n)}" for k, v in moves.most_common(8)))
        L.append("")

    # ---- tera & information -------------------------------------------------------------
    t = m[m.tera_turn.notna()]
    tera_side = t.groupby(["id", "side"]).size()
    rev = brought
    L += [
        "## 6. 太晶与信息暴露",
        "",
        f"- 使用太晶的队伍：{_pct(len(tera_side) / sides)}；太晶回合中位数 "
        f"{t.tera_turn.median():.0f}",
        "- 太晶属性："
        + "、".join(f"{k} {v}" for k, v in t.tera_type.value_counts().head(10).items()),
        f"- 上场的宝可梦平均暴露招式 {rev.n_moves.mean():.2f}/4，"
        f"道具 {_pct(rev.item.notna().mean())}，特性 {_pct(rev.ability.notna().mean())}，"
        f"太晶 {_pct(rev.tera_type.notna().mean())}",
        f"- 一局中未上场的宝可梦比例：{_pct(1 - m.brought.mean())}",
        "",
    ]
    return "\n".join(L)


def write_report(path: Path, format_id: str = "gen9ou") -> None:
    path.write_text(build_report(format_id))
    print(f"wrote {path}")
