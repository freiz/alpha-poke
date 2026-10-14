"""The root tie-break (2026-10-14, design TODO "根节点的平手裁决规则"): when the search finds
its best options about equal and our side clearly ahead, the one that makes progress.

The stalling loops of self-play (design "防拖延循环"): a side far ahead (root value 0.9+) saw
every option near 1, its prior preferred switching, and it kept switching. Among the options
whose mean is within ``delta`` of the best (each with enough visits for its mean to count),
the one with the most progress in a one-step rollout (the engine's transition from the search's
own state, world 0, against the opponent's most visited reply), if it makes ``min_gain`` more
than the most visited one (no churn among equal switches). Progress: the change of our
"standing" minus the opponent's: HP (fractions of max HP), faints, the lasting gains one turn
does not show in HP (a status on a mon, hazards on its side, a lost item, the active's stat
boosts). By the search's own estimate the cost is at most ``delta``; it is not an override of
the search (hidden information: Focus Sash, Sturdy, Protect, Disguise, priority moves make a
"sure" KO fail)."""

from dataclasses import dataclass

import alpha_search
import poke_engine as pe


@dataclass(frozen=True)
class TieBreak:
    delta: float = 0.01  # options within this of the best mean are tied
    q_min: float = 0.85  # only when the root value is at least this
    min_share: float = 0.05  # an option's visits (share of the root's) for its mean to count
    min_gain: float = 0.1  # progress over the most visited option to play another


# the standing's weights of what a turn's HP change does not show
FAINT, STATUS, ITEM, BOOST = 0.5, 0.25, 0.1, 0.05
HAZARDS = {"stealth_rock": 0.15, "spikes": 0.07, "toxic_spikes": 0.07, "sticky_web": 0.1}


def standing(side) -> float:
    """A side's standing: its mons' HP fractions, minus faints, statuses, missing items and the
    hazards on its side, plus its active's positive stat stages."""
    v = 0.0
    for p in side.pokemon:
        if p.maxhp <= 0:
            continue
        if p.hp <= 0:
            v -= FAINT
            continue
        v += p.hp / p.maxhp
        v -= STATUS * (str(p.status).upper() != "NONE")
        v -= ITEM * (str(p.item).upper() == "NONE")
    sc = side.side_conditions
    v -= sum(w * getattr(sc, k) for k, w in HAZARDS.items())
    boosts = (side.attack_boost, side.defense_boost, side.special_attack_boost,
              side.special_defense_boost, side.speed_boost)  # fmt: skip
    return v + BOOST * sum(b for b in boosts if b > 0)


def progress(state: str, slot: int, opp_slot: int) -> float | None:
    """The expected progress of our ``slot`` against the opponent's ``opp_slot`` in ``state``
    (side one = us): the change of our standing minus the opponent's. None if the pair is not
    among the options."""
    try:
        outs = alpha_search.chance_outcomes(state, slot, opp_slot)
    except ValueError:
        return None
    st = pe.State.from_string(state)
    us0, th0 = standing(st.side_one), standing(st.side_two)
    total = sum(o[0] for o in outs) or 1.0
    exp = 0.0
    for o in outs:
        nxt = pe.State.from_string(o[1])
        exp += o[0] / total * ((standing(nxt.side_one) - us0) - (standing(nxt.side_two) - th0))
    return exp


def choose(state: str, candidates: list[int], visits: list, means: list, q: float,
           opp_slot: int, tb: TieBreak) -> int | None:  # fmt: skip
    """The slot the tie-break plays among ``candidates`` (slots with an order), or None (no tie,
    not ahead enough, or the most visited option makes the most progress anyway)."""
    if q < tb.q_min:
        return None
    total = sum(visits) or 1
    counted = [i for i in candidates if visits[i] >= tb.min_share * total]
    if len(counted) < 2:
        return None
    best = max(means[i] for i in counted)
    tied = [i for i in counted if means[i] >= best - tb.delta]
    if len(tied) < 2:
        return None
    scored = {i: p for i in tied if (p := progress(state, i, opp_slot)) is not None}
    first = max(tied, key=lambda i: visits[i])
    if first not in scored or len(scored) < 2:
        return None
    pick = max(scored, key=lambda i: (scored[i], visits[i]))
    return pick if scored[pick] - scored[first] >= tb.min_gain else None
