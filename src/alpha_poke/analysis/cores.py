"""L2 of the layered archetype representation: maximal species cores (2-4 mons).

Plain frequent-itemset mining is dominated by redundant subsets of one big shell (e.g. every
3-subset of a stall core). A candidate itemset X is kept as a *core* when

* support(X) >= min_support,
* cohesion:   for every member x, P(x | X \\ x) >= min_conditional  (each mon is "expected"
  once the rest of the core is present) and lift(X) >= min_lift, and
* maximality: no kept superset Y has support(Y) >= absorb * support(X)  (X mostly occurs as
  part of Y, so it is absorbed into Y).

Each core records its sub-cores (``parents``) so the cores form a containment hierarchy.
"""

import itertools
import math
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Core:
    members: tuple[str, ...]
    support: int
    lift: float
    min_conditional: float  # min over members of P(member | rest)
    win_rate: float | None = None
    subcores: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.members)


def mine_cores(
    teams: list[tuple[str, ...]],
    won: list[bool | None] | None = None,
    max_size: int = 4,
    min_support: int = 100,
    min_conditional: float = 0.35,
    min_lift: float = 3.0,
    absorb: float = 0.7,
) -> list[Core]:
    n = len(teams)
    teams = [tuple(sorted(set(t))) for t in teams]
    single = Counter(s for t in teams for s in t)
    counts: dict[int, Counter] = {1: Counter({(s,): c for s, c in single.items()})}
    wins: dict[tuple, int] = {}
    for k in range(2, max_size + 1):
        frequent_prev = {x for x, c in counts[k - 1].items() if c >= min_support}
        frequent_items = {s for x in frequent_prev for s in x}
        ck = Counter()
        for i, t in enumerate(teams):
            t2 = [s for s in t if s in frequent_items]
            for combo in itertools.combinations(t2, k):
                # apriori: every (k-1)-subset must be frequent
                if k > 2 and any(
                    sub not in frequent_prev for sub in itertools.combinations(combo, k - 1)
                ):
                    continue
                ck[combo] += 1
                if won is not None and won[i]:
                    wins[combo] = wins.get(combo, 0) + 1
        counts[k] = ck

    def sup(x: tuple) -> int:
        return counts[len(x)].get(x, 0)

    candidates = []
    for k in range(2, max_size + 1):
        for x, c in counts[k].items():
            if c < min_support:
                continue
            expected = n * math.prod(single[s] / n for s in x)
            lift = c / expected
            cond = min(c / sup(tuple(s for s in x if s != m)) for m in x)
            if lift >= min_lift and cond >= min_conditional:
                candidates.append(
                    Core(x, c, lift, cond, wins.get(x, 0) / c if won is not None else None)
                )

    # maximality: process big cores first; absorb subsets that mostly occur inside them
    candidates.sort(key=lambda c: (-c.size, -c.support))
    kept: list[Core] = []
    for c in candidates:
        cs = set(c.members)
        if any(cs < set(k.members) and k.support >= absorb * c.support for k in kept):
            continue
        kept.append(c)
    for c in kept:
        cs = set(c.members)
        c.subcores = [k.members for k in kept if set(k.members) < cs]
    kept.sort(key=lambda c: -c.support * math.log(c.lift))
    return kept


def team_cores(team: tuple[str, ...] | list[str], cores: list[Core]) -> list[Core]:
    """Maximal cores fully contained in a team (a sub-core is dropped if its super-core matches)."""
    ts = set(team)
    hit = [c for c in cores if set(c.members) <= ts]
    return [c for c in hit if not any(set(c.members) < set(o.members) for o in hit)]
