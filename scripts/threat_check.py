"""Threat coverage of a team (2026-10-28; the ladder bot's team design): for each threat of the
current metagame, does one of our six answer it?

  check:   the threat's best likely move does < --check-in of its HP, and its own best move does
           >= --check-out of the threat's (it can come in and fight back);
  revenge: it moves first (faster, or a priority move) and its best move does >= 100%.
The threats' sets: the belief (agents.belief_state: the species' most likely moves, items, its
most common spread); ours: exact (the export's EVs / nature). The damage model is the knowledge
layer's (agents.damage: average roll, the main multipliers -- an estimate, not the engine).

  uv run python scripts/threat_check.py data/teams/pools/ladder_top5 [--threats 15] [--also "Iron Valiant"]
"""

import argparse
import json
import sys
from pathlib import Path

from poke_env.battle import Pokemon
from poke_env.teambuilder import Teambuilder

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alpha_poke.agents.damage import (
    MonView,
    Spread,
    best_damage,
    calc_stats,
    damage_fraction,
    effective_speed,
    priority,
)


def own_views(text: str) -> list[tuple[MonView, list]]:
    out = []
    for tb in Teambuilder.parse_showdown_team(text.strip() + "\n\n"):
        mon = Pokemon(gen=9, teambuilder=tb)
        evs = tuple(int(x) for x in (tb.evs or [0] * 6))
        stats = calc_stats(mon.base_stats, Spread((tb.nature or "serious").lower(), evs))
        mon._terastallized_type = None  # (not terastallized: its own types)
        view = MonView(mon, stats, {mon.item: 1.0} if mon.item else {}, mon.ability)
        out.append((view, list(mon.moves.values())))
    return out


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
    """name -> [(weight, (MonView, moves))] of its main builds."""
    out = {}
    for n in names:
        out[n] = [(w, own_views(text)[0]) for w, text in threat_sets(belief, stats, n, k, min_w)]
    return out


def answers(ours: list[tuple[MonView, list]], builds: list, a) -> list[str]:
    """Our mons answering the threat in every one of its main builds: 'check' / 'revenge'."""
    out = []
    for v, moves in ours:
        tags = None
        for _, (tv, tmoves) in builds:
            dmg_in = max((damage_fraction(tv, v, m) for m in tmoves), default=0.0)
            best, dmg_out = best_damage(v, tv, moves)
            first = effective_speed(v) > effective_speed(tv) or (
                best is not None and priority(best) > 0
            )
            t = set()
            if dmg_in < a.check_in and dmg_out >= a.check_out:
                t.add("check")
            if first and dmg_out >= 1.0:
                t.add("revenge")
            tags = t if tags is None else tags & t
        if tags:
            out.append(f"{v.mon.species}({'/'.join(sorted(tags))})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pools", nargs="+", help="pool directories (team_XX.txt) or export files")
    ap.add_argument("--threats", type=int, default=15, help="the metagame's most used species")
    ap.add_argument("--also", nargs="*", default=[], help="more threats by name")
    ap.add_argument("--meta", default="data/teams/pools/robust_candidates/report.json",
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
    names = [s.name for s in stats.ranked()[: a.threats]] + [x for x in a.also]
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
        cover = {n: answers(ours, t, a) for n, t in threats.items()}
        missing = [n for n, x in cover.items() if not x]
        single = [n for n, x in cover.items() if len(x) == 1]
        result[str(f)] = {"team": team, "unanswered": missing, "single": single, "answers": cover}
        print(f"{f.parent.name}/{f.stem}: none {len(missing)} [{', '.join(missing) or '-'}]; "
              f"one {len(single)} [{', '.join(single) or '-'}]   ({team})", flush=True)  # fmt: skip
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
