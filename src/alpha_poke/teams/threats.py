"""A team against the metagame's threats, set by set (2026-10-28 the ladder bot's team design,
scripts/threat_check.py; 2026-10-30 also the review app's team analysis, coach.meta): for each
threat, which of our six answer it in every one of its main builds --
  check:   the threat's best move does < ``check_in`` of its HP, and its own best move does
           >= ``check_out`` of the threat's (it can come in and fight back);
  revenge: it moves first (faster, or a priority move) and its best move does >= 100%;
and which of ours the threat KOs in one hit in some build. The damage model is the knowledge
layer's (agents.damage: average roll, the main multipliers -- an estimate, not the engine)."""

from poke_env.battle import Pokemon
from poke_env.teambuilder import Teambuilder

from alpha_poke.agents.damage import (
    MonView,
    Spread,
    best_damage,
    calc_stats,
    damage_fraction,
    effective_speed,
    priority,
)

CHECK_IN, CHECK_OUT = 0.5, 0.35


def own_views(text: str) -> list[tuple[MonView, list]]:
    """A Showdown export's mons as damage views with their moves (exact stats from its spreads)."""
    out = []
    for tb in Teambuilder.parse_showdown_team(text.strip() + "\n\n"):
        mon = Pokemon(gen=9, teambuilder=tb)
        evs = tuple(int(x) for x in (tb.evs or [0] * 6))
        stats = calc_stats(mon.base_stats, Spread((tb.nature or "serious").lower(), evs))
        mon._terastallized_type = None  # (not terastallized: its own types)
        view = MonView(mon, stats, {mon.item: 1.0} if mon.item else {}, mon.ability)
        out.append((view, list(mon.moves.values())))
    return out


def answers(ours: list[tuple[MonView, list]], builds: list, check_in: float = CHECK_IN,
            check_out: float = CHECK_OUT) -> list[str]:  # fmt: skip
    """Our mons answering the threat in every one of its main ``builds`` ([(weight, (view,
    moves))]): "Species(check)", "Species(revenge)", "Species(check/revenge)"."""
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
            if dmg_in < check_in and dmg_out >= check_out:
                t.add("check")
            if first and dmg_out >= 1.0:
                t.add("revenge")
            tags = t if tags is None else tags & t
        if tags:
            out.append(f"{v.mon.species}({'/'.join(sorted(tags))})")
    return out


def ko_by(ours: list[tuple[MonView, list]], builds: list) -> list[str]:
    """Our mons the threat KOs in one hit (its best move, from full HP) in some main build."""
    return [v.mon.species for v, _ in ours
            if any(max((damage_fraction(tv, v, m) for m in tmoves), default=0.0) >= 1.0
                   for _, (tv, tmoves) in builds)]  # fmt: skip
