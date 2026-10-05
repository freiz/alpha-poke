"""The archetype library ("what we learned from the guides"): mined set archetypes and cores,
named and explained by an LLM that is only allowed to summarize our own data.

    library = {
      "format": "gen9ou", "built": ..., "n_games": ...,
      "sets":  {species: [{index, weight, item, ability, tera, moves, name, role, description}]},
      "cores": [{members, size, support, lift, win_rate, name, tags, game_plan, roles,
                 win_conditions, weaknesses, how_to_play_against, violations}],
    }

Stored as ``data/library/<format>_library.json`` (derived data, regenerated as replays grow).
"""

import json
import time
from pathlib import Path

import pandas as pd

from alpha_poke.analysis.archetypes import team_table
from alpha_poke.analysis.cores import Core, mine_cores
from alpha_poke.analysis.roles import to_id
from alpha_poke.analysis.sets import SpeciesSets, mine_sets
from alpha_poke.llm import LLMClient
from alpha_poke.llm_bench import MOVE_IDS, extract_mentions, run_naming

ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = ROOT / "data" / "library"

SET_SYSTEM = (
    "You are an expert competitive Pokemon analyst for Smogon Gen 9 OU singles. You are given "
    "set archetypes mined from thousands of high-rated ladder replays (October 2026): for each "
    "archetype, its share among that species' appearances and the item / ability / tera type "
    "/ moves distributions. Name each archetype the way a strong player would (e.g. 'Hazard "
    "Lead', 'Booster Speed Sweeper', 'Choice Scarf Revenge Killer'). Mention ONLY moves, items, "
    "abilities and tera types that appear in the DATA for that archetype. English only. "
    "Answer with one JSON object."
)


def _archetype_dict(a) -> dict:
    return {
        "index": a.index,
        "weight": round(a.weight, 3),
        "item": [[k, round(v, 3)] for k, v in a.item],
        "ability": [[k, round(v, 3)] for k, v in a.ability],
        "tera": [[k, round(v, 3)] for k, v in a.tera],
        "moves": [[k, round(v, 3)] for k, v in a.moves],
    }


def name_sets(client: LLMClient, sets: dict[str, SpeciesSets], batch: int = 6) -> dict:
    out: dict[str, list[dict]] = {}
    species = list(sets)
    for i in range(0, len(species), batch):
        chunk = species[i : i + batch]
        lines = []
        for sp in chunk:
            for a in sets[sp].sets:
                lines.append(
                    f"{sp} #{a.index} [{a.weight:.0%}]: item "
                    + ", ".join(f"{k} {v:.0%}" for k, v in a.item[:2])
                    + "; ability "
                    + ", ".join(k for k, _ in a.ability[:1])
                    + "; tera "
                    + ", ".join(f"{k} {v:.0%}" for k, v in a.tera[:2])
                    + "; moves "
                    + ", ".join(f"{k} {v:.0%}" for k, v in a.moves[:6])
                )
        user = (
            "DATA:\n"
            + "\n".join(lines)
            + '\n\nReturn {"<species>": [{"index": <int>, "name": "<short archetype name>", '
            '"role": "<one of: lead, hazard_setter, hazard_removal, pivot, wallbreaker, '
            'setup_sweeper, revenge_killer, physical_wall, special_wall, cleric, utility>", '
            '"description": "<1-2 sentences on how it is played>"}], ...} '
            "covering every species and archetype above."
        )
        ans = client.chat_json(
            [{"role": "system", "content": SET_SYSTEM}, {"role": "user", "content": user}]
        )
        for sp in chunk:
            got = {int(x.get("index", -1)): x for x in ans.get(sp, []) if isinstance(x, dict)}
            rows = []
            for a in sets[sp].sets:
                d = _archetype_dict(a)
                x = got.get(a.index, {})
                d.update(
                    name=x.get("name", ""),
                    role=x.get("role", ""),
                    description=x.get("description", ""),
                )
                allowed = {to_id(k) for k, _ in a.item + a.ability + a.tera + a.moves}
                d["violations"] = sorted(
                    extract_mentions(d["description"], set(MOVE_IDS)) - allowed
                )
                rows.append(d)
            out[sp] = rows
    return out


def core_dict(c: Core, named: dict) -> dict:
    ans = named.get("answer", {})
    tags = ans.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    return {
        "members": list(c.members),
        "size": c.size,
        "support": c.support,
        "lift": round(c.lift, 1),
        "win_rate": round(c.win_rate, 3) if c.win_rate is not None else None,
        "subcores": [list(x) for x in c.subcores],
        "name": ans.get("name", ""),
        "tags": tags,
        "game_plan": ans.get("game_plan", ""),
        "roles": ans.get("roles", {}),
        "win_conditions": [w for w in ans.get("win_conditions", []) if w in c.members],
        "weaknesses": ans.get("weaknesses", ""),
        "how_to_play_against": ans.get("how_to_play_against", ""),
        "violations": named.get("violations", []),
    }


def build_library(format_id: str = "gen9ou", model: str | None = None) -> dict:
    from alpha_poke.analysis.tables import OUT

    m = pd.read_parquet(OUT / f"{format_id}_mons.parquet")
    teams = team_table(m)
    cores = mine_cores(
        [tuple(t) for t in teams.species],
        won=teams.won.tolist(),
        max_size=6,
        absorb=0.6,
        min_support=max(30, len(teams) // 300),
    )
    sets = mine_sets(m)
    client = LLMClient(model=model, max_tokens=8000, reasoning_effort="low")
    named_sets = name_sets(client, sets)
    named_cores = run_naming(client, cores, sets, m)
    lib = {
        "format": format_id,
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "model": client.model,
        "n_games": int(m.id.nunique()),
        "sets": named_sets,
        "cores": [core_dict(c, n) for c, n in zip(cores, named_cores, strict=True)],
        "llm_cost_usd": round(client.spent_usd, 4),
    }
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    (LIB_DIR / f"{format_id}_library.json").write_text(json.dumps(lib, indent=1))
    return lib


def load_library(format_id: str = "gen9ou") -> dict:
    return json.loads((LIB_DIR / f"{format_id}_library.json").read_text())


def library_markdown(lib: dict) -> str:
    L = [
        f"# {lib['format']} 套路库",
        "",
        f"构建时间 {lib['built']}；{lib['n_games']} 场高分 replay；命名模型 `{lib['model']}`"
        f"（只允许总结我们挖掘出的数据，英文输出）；LLM 花费 ${lib['llm_cost_usd']:.3f}。"
        "脚本 `scripts/build_library.py`，数据 `data/library/`。",
        "",
        "## 1. 核心与完整队伍",
        "",
        "| 成员 | 次数 | 胜率 | 名称 | 标签 | 胜利路线 |",
        "|---|---|---|---|---|---|",
    ]
    for c in lib["cores"]:
        wr = f"{c['win_rate']:.0%}" if c["win_rate"] is not None else ""
        L.append(
            f"| {' + '.join(c['members'])} | {c['support']} | {wr} | {c['name']} | "
            f"{', '.join(c['tags'])} | {', '.join(c['win_conditions'])} |"
        )
    L += ["", "### 说明（前 15 个）", ""]
    for c in lib["cores"][:15]:
        L += [
            f"**{c['name']}** — {' + '.join(c['members'])}",
            "",
            f"- Game plan: {c['game_plan']}",
            "- Roles: " + "; ".join(f"{k}: {v}" for k, v in c["roles"].items()),
            f"- Weaknesses: {c['weaknesses']}",
            f"- How to play against: {c['how_to_play_against']}",
            "",
        ]
    L += ["## 2. 配置原型", ""]
    for sp, rows in lib["sets"].items():
        L.append(f"**{sp}**")
        for r in rows:
            item = r["item"][0][0] if r["item"] else "?"
            mv = " / ".join(k for k, _ in r["moves"][:4])
            L.append(
                f"- #{r['index']} {r['name']}（{r['weight']:.0%}，{r['role']}）：@ {item}；"
                f"{mv}。{r['description']}"
            )
        L.append("")
    v_sets = sum(len(r["violations"]) for rows in lib["sets"].values() for r in rows)
    v_cores = sum(len(c["violations"]) for c in lib["cores"])
    L += [f"接地检查：配置说明中提到 DATA 以外招式 {v_sets} 次，核心说明中 {v_cores} 次。", ""]
    return "\n".join(L)
