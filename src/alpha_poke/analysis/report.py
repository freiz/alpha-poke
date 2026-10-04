"""Markdown report over the parsed replay tables (+ Smogon usage stats for comparison)."""

import math
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from alpha_poke.analysis.archetypes import soft_archetypes, team_table
from alpha_poke.analysis.cores import mine_cores
from alpha_poke.analysis.roles import ROLE_NAMES, RoleModel
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

    # ---- L1 roles ---------------------------------------------------------------------
    teams = team_table(m)
    if smog:
        rm = RoleModel(smog)
        L += [
            "## 3. L1 角色（Smogon 先验的保守下界 + replay 已暴露信息）",
            "",
            "每支队伍的角色数 = 6 只宝可梦该角色概率之和；下表是所有队伍的平均值。",
            "",
            "| 角色 | 每队平均 | 至少 1 只的队伍比例（≥0.5） |",
            "|---|---|---|",
        ]
        prof = []
        for _key, d in m.groupby(["id", "side"]):
            tot = dict.fromkeys(ROLE_NAMES, 0.0)
            for r in d.itertuples():
                for k, v in rm.roles(
                    r.species, r.moves.split("|") if r.moves else [], r.ability, r.item
                ).items():
                    tot[k] += v
            prof.append(tot)
        prof = pd.DataFrame(prof)
        for role in prof.mean().sort_values(ascending=False).index:
            L.append(f"| {role} | {prof[role].mean():.2f} | {_pct((prof[role] >= 0.5).mean())} |")
        L.append("")

    # ---- L2 cores -----------------------------------------------------------------------
    cores = mine_cores(
        [tuple(t) for t in teams.species], won=teams.won.tolist(), max_size=6, absorb=0.6
    )
    L += [
        "## 4. L2 核心与完整队伍（最大核心，2–6 只）",
        "",
        '只保留"最大核心"：每个成员在其余成员出现时的条件概率 ≥0.35、lift ≥3，'
        "且没有被一个出现次数 ≥60% 的超集吸收。6 只的核心就是被大量照搬的完整队伍。",
        "",
    ]
    by_size = Counter(c.size for c in cores)
    L.append(
        "核心数量（按大小）：" + "，".join(f"{k} 只 {v} 个" for k, v in sorted(by_size.items()))
    )
    L.append("")
    L += ["| 大小 | 成员 | 次数 | 条件概率下限 | 胜率 | 子核心数 |", "|---|---|---|---|---|---|"]
    for c in cores[:30]:
        L.append(
            f"| {c.size} | {' + '.join(c.members)} | {c.support} | "
            f"{c.min_conditional:.2f} | {_pct(c.win_rate)} | {len(c.subcores)} |"
        )
    L.append("")

    # popular identical teams and their reconstructed sets
    key = m.groupby(["id", "side"]).species.transform(lambda x: "/".join(sorted(x)))
    m2 = m.assign(team_key=key)
    per_team = m2.drop_duplicates(["id", "side"]).team_key.value_counts()
    popular = per_team[per_team >= 50]
    L += [
        "### 4.1 被照搬的完整队伍",
        "",
        f"使用 ≥50 次的相同 6 只队伍有 **{len(popular)}** 支，覆盖 "
        f"**{_pct(popular.sum() / len(teams))}** 的队伍。同一队伍的使用者配置几乎一致，"
        "把多场 replay 中零散暴露的信息汇总即可重建完整配置（下面是前 5 支）。",
        "",
    ]
    for tk, n in popular.head(5).items():
        L.append(f"**{tk}**（{n} 次）")
        d = m2[(m2.team_key == tk) & m2.brought]
        for sp, gg in d.groupby("species"):
            items = gg.item.value_counts(normalize=True).head(2)
            tera = gg.tera_type.value_counts(normalize=True).head(2)
            mv = Counter(x for v in gg.moves for x in v.split("|") if x)
            mv_s = ", ".join(f"{k} {v / len(gg):.0%}" for k, v in mv.most_common(5))
            L.append(
                f"- {sp}："
                + " / ".join(f"{k} {v:.0%}" for k, v in items.items())
                + "；太晶 "
                + " / ".join(f"{k} {v:.0%}" for k, v in tera.items())
                + f"；招式 {mv_s}"
            )
        L.append("")

    # ---- L3 soft archetypes -------------------------------------------------------------
    mix, soft = soft_archetypes(teams)
    second = float((pd.DataFrame(mix).apply(lambda r: sorted(r)[-2], axis=1) >= 0.3).mean())
    L += [
        "## 5. L3 队伍类型（NMF 软聚类，k=20）",
        "",
        '每支队伍得到各类型的混合比例；"质量"= 所有队伍在该类型上的比例之和。'
        f"第二大类型占比 ≥30% 的队伍：{_pct(second)}。名字需人工或 LLM 解读。",
        "",
        "| 类型 | 质量 | 主导队伍数 | 加权胜率 | 主要成员（载荷） |",
        "|---|---|---|---|---|",
    ]
    for sa in soft:
        tops = ", ".join(f"{sp} {w:.2f}" for sp, w in sa.top[:6])
        L.append(
            f"| {sa.component} | {sa.weight:.0f} | {sa.dominant} | {_pct(sa.win_rate)} | {tops} |"
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
        "## 7. 太晶与信息暴露",
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
