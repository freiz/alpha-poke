"""Threat coverage of a team (2026-10-28; the ladder bot's team design): for each threat of the
current metagame, does one of our six answer it?

  check:   the threat's best likely move does < --check-in of its HP, and its own best move does
           >= --check-out of the threat's (it can come in and fight back);
  revenge: it moves first (faster, or a priority move) and its best move does >= 100%.
The threats' sets: the belief (agents.belief_state: the species' most likely moves, items, its
most common spread); ours: exact (the export's EVs / nature). The damage model is the knowledge
layer's (agents.damage: average roll, the main multipliers -- an estimate, not the engine).

  uv run python scripts/threat_check.py data/derived/teams/pools/ladder_top5 [--threats 15] [--also "Iron Valiant"]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alpha_poke import paths  # noqa: E402
from alpha_poke.agents.damage import MonView, priority  # noqa: E402
from alpha_poke.teams.threats import answers, own_views  # noqa: E402,F401  (here since 2026-10-30)


def threat_sets(belief, stats, name: str, k: int, min_w: float) -> list[tuple[float, str]]:
    """The threat's main builds: the belief's set archetypes with weight >= ``min_w`` (at most
    ``k``), each as an export -- its 4 likeliest moves, likeliest item, the species' most used
    ability and tera, the Smogon spread fitting the item and moves (scripts/top_ladder_teams)."""
    import numpy as np
    import pandas as pd
    import top_ladder_teams as tlt

    from alpha_poke.analysis.roles import to_id
    from alpha_poke.dex import MOVE_IDS
    from alpha_poke.teams.replay_pool import build_set

    ss = belief.sets.get(name)
    base = build_set(name, pd.DataFrame(columns=["item", "ability", "tera_type", "moves"]), stats)
    if ss is None or not ss.vocab.get("move"):
        return [(1.0, tlt.fit_spread(base, stats))]
    head = base.split("\n")
    ability = next((x for x in head if x.startswith("Ability:")), None)
    pi = np.asarray(ss.params["pi"], dtype=float)
    out = []
    for i in np.argsort(-pi)[:k]:
        if pi[i] < min_w and out:
            break
        mw = np.asarray(ss.params["move"][i], dtype=float)
        moves = [
            ss.vocab["move"][j] for j in np.argsort(-mw) if to_id(ss.vocab["move"][j]) in MOVE_IDS
        ][:4]
        iw = np.asarray(ss.params["item"][i], dtype=float) if ss.vocab.get("item") else None
        item = ss.vocab["item"][int(np.argmax(iw))] if iw is not None and len(iw) else None
        lines = [f"{name} @ {item}" if item else name] + ([ability] if ability else [])
        lines += ["EVs: 84 HP / 84 Atk / 84 Def / 84 SpA / 84 SpD / 84 Spe", "Serious Nature"]
        lines += [f"- {m}" for m in moves]
        out.append((float(pi[i]), tlt.fit_spread("\n".join(lines), stats)))
    return out


def threat_views(belief, stats, names: list[str], k: int, min_w: float) -> dict[str, list]:
    """name -> [(weight, (MonView, moves))] of its main builds (preview names -- "Zamazenta-*" --
    as the species they are)."""
    from alpha_poke.teams.replay_pool import PREVIEW_FORMS

    out = {}
    for n in names:
        sp = PREVIEW_FORMS.get(n, n)
        out[n] = [(w, own_views(text)[0]) for w, text in threat_sets(belief, stats, sp, k, min_w)]
    return out


HAZARDS = {"stealthrock", "spikes", "toxicspikes", "stickyweb", "stoneaxe", "ceaselessedge"}
REMOVAL = {"rapidspin", "defog", "mortalspin", "tidyup", "courtchange"}
PIVOT = {
    "uturn",
    "voltswitch",
    "flipturn",
    "partingshot",
    "teleport",
    "chillyreception",
    "shedtail",
}
SPEED = {"thunderwave", "icywind", "trickroom", "tailwind", "electroweb", "stickyweb", "nuzzle",
         "glare", "dragondance", "quiverdance", "shellsmash", "agility", "rockpolish", "bulkup"}  # fmt: skip


def roles(ours: list[tuple[MonView, list]]) -> dict[str, list[str]]:
    """The team's role slots: hazards, their removal, pivoting (moves or Regenerator), speed
    control (a Choice Scarf, priority, speed-changing / setup moves)."""
    out = {"hazards": [], "removal": [], "pivot": [], "speed": []}
    for v, moves in ours:
        ids = {m.id for m in moves}
        name = v.mon.species
        if ids & HAZARDS:
            out["hazards"].append(name)
        if ids & REMOVAL:
            out["removal"].append(name)
        if ids & PIVOT or v.mon.ability == "regenerator":
            out["pivot"].append(name)
        if (
            v.mon.item == "choicescarf"
            or ids & SPEED
            or any(priority(m) > 0 and m.base_power for m in moves)
        ):
            out["speed"].append(name)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pools", nargs="+", help="pool directories (team_XX.txt) or export files")
    ap.add_argument("--threats", type=int, default=15, help="the metagame's most used species")
    ap.add_argument("--also", nargs="*", default=[], help="more threats by name")
    ap.add_argument("--meta", default=str(paths.POOLS / "robust_candidates" / "report.json"),
                    help="build_robust_teams' report (its threats), else Smogon's top usage")  # fmt: skip
    ap.add_argument("--check-in", type=float, default=0.5)
    ap.add_argument("--check-out", type=float, default=0.35)
    ap.add_argument("--out", default="", help="the per-team answers as JSON")
    ap.add_argument(
        "--builds", type=int, default=3, help="a threat's main builds (belief archetypes)"
    )
    ap.add_argument("--min-build", type=float, default=0.15, help="an archetype's weight at least")
    a = ap.parse_args()

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats

    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    stats = UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1500.json")
    rep = Path(a.meta)
    meta_threats = (
        json.loads(rep.read_text(encoding="utf-8")).get("threats") if rep.exists() else None
    )
    if meta_threats:  # (the recent metagame's, build_robust_teams' report)
        names = [s for s, _ in meta_threats[: a.threats]] + list(a.also)
    else:
        names = [s.name for s in stats.ranked()[: a.threats]] + list(a.also)
    print("threats:", ", ".join(names), flush=True)
    belief = BeliefModel.load()
    threats = threat_views(belief, stats, names, a.builds, a.min_build)
    files = []
    for p in a.pools:
        p = Path(p)
        files += sorted(p.glob("team_*.txt")) if p.is_dir() else [p]
    result = {}
    for f in files:
        ours = own_views(f.read_text())
        team = "|".join(v.mon.species for v, _ in ours)
        cover = {n: answers(ours, t, a.check_in, a.check_out) for n, t in threats.items()}
        missing = [n for n, x in cover.items() if not x]
        single = [n for n, x in cover.items() if len(x) == 1]
        rl = roles(ours)
        lacking = [r for r, x in rl.items() if not x]
        result[str(f)] = {"team": team, "unanswered": missing, "single": single, "answers": cover,
                          "roles": rl, "lacking": lacking}  # fmt: skip
        print(f"{f.parent.name}/{f.stem}: none {len(missing)} [{', '.join(missing) or '-'}]; "
              f"one {len(single)} [{', '.join(single) or '-'}]; roles lacking [{', '.join(lacking) or '-'}]"
              f"   ({team})", flush=True)  # fmt: skip
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
