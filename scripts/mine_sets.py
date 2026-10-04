"""Mine per-species set archetypes and set-level cores; write doc/sets_<format>.md.

Usage: uv run python scripts/mine_sets.py [--format gen9ou] [--top 40]
"""

import argparse
import time
from pathlib import Path

import pandas as pd

from alpha_poke.analysis.archetypes import team_table
from alpha_poke.analysis.cores import mine_cores
from alpha_poke.analysis.roles import to_id
from alpha_poke.analysis.sets import assign_sets, mine_sets
from alpha_poke.analysis.tables import OUT
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats

# Items that announce themselves whenever they act; they are over-represented among *revealed*
# items compared with silent ones (Choice Specs, Mystic Water, ...), which Smogon's server-side
# stats see in full.
SELF_REVEALING = {
    to_id(x)
    for x in (
        "Life Orb",
        "Leftovers",
        "Black Sludge",
        "Booster Energy",
        "Rocky Helmet",
        "Focus Sash",
        "Air Balloon",
        "Weakness Policy",
        "Sitrus Berry",
        "Lum Berry",
        "Heavy-Duty Boots",
        "Toxic Orb",
        "Flame Orb",
        "Custap Berry",
        "Covert Cloak",
        "Clear Amulet",
        "White Herb",
        "Mental Herb",
        "Throat Spray",
        "Red Card",
        "Eject Button",
        "Eject Pack",
    )
}


def novelty(arch, smog) -> list[str]:
    """Key atoms of an archetype that are rare (<5%) in Smogon's marginal stats."""
    key = next((k for k in smog.species if to_id(k) == to_id(arch.species.replace("-*", ""))), None)
    if key is None:
        return ["species not in Smogon stats"]
    s = smog.species[key]
    items = {to_id(k): v for k, v in s.items.items()}
    tera = {to_id(k): v for k, v in s.tera_types.items()}
    flags = []
    if arch.item and arch.item[0][1] >= 0.5 and items.get(to_id(arch.item[0][0]), 0) < 0.05:
        bias = "，可能是暴露偏差" if to_id(arch.item[0][0]) in SELF_REVEALING else ""
        flags.append(
            f"道具 {arch.item[0][0]}（Smogon {items.get(to_id(arch.item[0][0]), 0):.0%}{bias}）"
        )
    if arch.tera and arch.tera[0][1] >= 0.5 and tera.get(to_id(arch.tera[0][0]), 0) < 0.05:
        flags.append(f"太晶 {arch.tera[0][0]}（Smogon {tera.get(to_id(arch.tera[0][0]), 0):.0%}）")
    for mv, p in arch.moves[:4]:
        if p >= 0.6 and s.move_has.get(to_id(mv), 0) < 0.05:
            flags.append(f"招式 {mv}（Smogon {s.move_has.get(to_id(mv), 0):.0%}）")
    return flags


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="gen9ou")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    m = pd.read_parquet(OUT / f"{a.format}_mons.parquet")
    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    smog = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / f"{a.format}-1825.json")

    sets = mine_sets(m)
    m = m.assign(set_idx=assign_sets(m, sets))
    L = [
        f"# {a.format} 配置原型与配置层面的组合",
        "",
        f"生成时间：{time.strftime('%Y-%m-%d %H:%M')}；脚本 `scripts/mine_sets.py`；"
        f"数据 {m.id.nunique()} 场 replay；对照 Smogon {months[-1]}（门槛 1825）。",
        "",
        "方法：每只宝可梦一个潜在类别混合模型（EM，K 由 BIC 选），每场只用实际暴露的道具/特性/"
        '太晶/招式，未暴露不计入。招式后的数字是"带这个招式"的粗略估计（4×份额，封顶 1）。',
        "",
    ]

    # ---- archetypes ----------------------------------------------------------------
    order = m[m.brought].species.value_counts().index
    L += ["## 1. 配置原型", ""]
    novel = []
    for sp in [s for s in order if s in sets][: a.top]:
        ss = sets[sp]
        L.append(f"**{sp}**（{ss.n} 次有暴露信息，K={ss.k}）")
        for arch in ss.sets:
            it = " / ".join(f"{k} {v:.0%}" for k, v in arch.item[:2])
            te = " / ".join(f"{k} {v:.0%}" for k, v in arch.tera[:2])
            mv = ", ".join(f"{k} {v:.0%}" for k, v in arch.moves[:6])
            L.append(f"- 原型 {arch.index}（{arch.weight:.0%}）：{it}；太晶 {te}；{mv}")
            f = novelty(arch, smog)
            if f and arch.weight >= 0.1:
                novel.append((sp, arch, f))
        L.append("")

    L += [
        "## 2. 与 Smogon 统计不一致的配置（可能的新技巧）",
        "",
        "条件：原型占该宝可梦 ≥10%，且其主要道具/太晶（≥50%）或核心招式（≥60%）在 Smogon "
        "边缘统计中 <5%。",
        "",
    ]
    for sp, arch, f in novel:
        L.append(
            f"- **{sp} 原型 {arch.index}**（{arch.weight:.0%}）：{arch.summary()} — " + "；".join(f)
        )
    if not novel:
        L.append("（无）")
    L.append("")

    # ---- set-level cores ------------------------------------------------------------
    def token(r):
        return f"{r.species}#{int(r.set_idx)}" if pd.notna(r.set_idx) else r.species

    m = m.assign(token=[token(r) for r in m.itertuples()])
    teams = team_table(m.assign(species=m.token))
    cores = mine_cores(
        [tuple(t) for t in teams.species],
        won=teams.won.tolist(),
        max_size=4,
        min_support=60,
        absorb=0.6,
    )
    set_cores = [c for c in cores if any("#" in t for t in c.members)]
    L += [
        "## 3. 配置层面的组合",
        "",
        '单位是"宝可梦#原型编号"（后验 ≥0.7 时才认定原型，否则只记物种）。'
        "只列出至少包含一个配置原型的核心。",
        "",
        "| 组合 | 次数 | lift | 条件概率下限 | 胜率 |",
        "|---|---|---|---|---|",
    ]
    for c in set_cores[:40]:
        L.append(
            f"| {' + '.join(c.members)} | {c.support} | {c.lift:.1f} | "
            f"{c.min_conditional:.2f} | {c.win_rate:.1%} |"
        )
    L.append("")
    lookup = {f"{sp}#{x.index}": x.summary() for sp, ss in sets.items() for x in ss.sets}
    used = sorted({t for c in set_cores[:40] for t in c.members if "#" in t})
    L += ["原型编号对照：", ""] + [f"- `{t}`：{lookup.get(t, '')}" for t in used] + [""]

    out = Path(a.out or f"doc/sets_{a.format}.md")
    out.write_text("\n".join(L))
    print(
        f"wrote {out}: {len(sets)} species, {len(novel)} novelty flags, {len(set_cores)} set cores"
    )


if __name__ == "__main__":
    main()
