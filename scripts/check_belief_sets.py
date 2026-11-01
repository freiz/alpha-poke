"""A quick check of the belief's item and tera draws (seconds, no engine, no network): on the
catalog's complete teams (built by people: every item and tera type known, the ones that never
show in a game too), one team per near-duplicate family, the probability the sampler gives each
mon's true item and tera type at preview with 0 or 2 of its moves shown (engine_state.sample_set's
marginals: enginecheck.beliefcheck's item support; the archetype mix of the tera weights).

  uv run python scripts/check_belief_sets.py [--since 2025-06]

Precision -- NLL: the mean -log P(the true value), floored at 1e-6; top-1: the most likely value
is the true one. Recall -- at 0: P < 1e-4 (the draw hardly ever makes it); in 16 / in 32: the
chance the true value is among a decision's 16 / 32 worlds at all (1 - (1 - P) ** W); in F1:
the true item among the items the damage evidence weighs (once a clean hit is seen, the only
ones drawn). The teams are the forum's, which lean to
polished, showcased sets (issue #33): Smogon's ladder usage is a reference row, not the truth.
"""

import argparse
import collections
import math
import random

import numpy as np


def tera_dist(belief, species: str, team_names, known_moves) -> dict:
    """The tera marginal sample_set draws from: the archetypes' posterior on the shown moves, each
    one's tera weights mixed with the base, raked if the belief's ``rake`` is on."""
    from alpha_poke.agents.engine_state import arch_mix, base_marginal, rake_factors, raked
    from alpha_poke.analysis.roles import to_id

    base = base_marginal(belief, species, team_names, "tera")
    ss = belief.sets.get(species)
    c = rake_factors(belief, species, "tera")
    if not (ss is not None and ss.params and ss.vocab.get("tera")):
        w = raked(base, c)
        t = sum(w.values()) or 1.0
        return {k: v / t for k, v in w.items()}
    names = {to_id(n): n for n in ss.vocab["move"]}
    post = np.asarray(ss.posterior(moves=[names.get(m, m) for m in known_moves]), dtype=float)
    post = post / post.sum()
    out: dict = collections.defaultdict(float)
    for k, p in enumerate(post):
        w = raked(arch_mix(ss, k, "tera", base), c)
        t = sum(w.values()) or 1.0
        for i, v in w.items():
            out[i] += p * v / t
    return out


WORLDS = (16, 32)  # the worlds a decision draws: self-play's fast searches, the full ones
# the belief's switches compared (BeliefModel's booleans; all off by default)
CONFIGS = (
    ("belief", ()),
    ("raked", ("rake",)),
    ("raked+F1all", ("rake", "f1_all")),
    ("raked+F1all+strat", ("rake", "f1_all", "stratify")),
)
SWITCHES = ("rake", "f1_all", "stratify")


def configure(belief, opts) -> None:
    for o in SWITCHES:
        setattr(belief, o, o in opts)


def f1_items(belief, mon, team_names) -> set:
    """The items F1's damage evidence weighs (damage_obs._candidates: the base marginal's
    TOP_ITEMS): once a clean hit is seen, an unrevealed item is drawn from these alone."""
    from alpha_poke.agents.damage_obs import _candidates

    return {c[0] for c in _candidates(belief, mon, team_names)[0]}


def score(dist: dict, truth: str, s: dict, w: float = 1.0, f1: set | None = None,
          strat: bool = False) -> None:  # fmt: skip
    """Precision: NLL, top-1. Recall: at 0 (P < 1e-4: as good as never drawn); in W worlds (the
    chance the true value is in at least one of a decision's W draws: 1 - (1 - P) ** W, or
    min(1, W P) for stratified draws -- not in any, the search never considers it there); in
    F1's candidates (``f1``, items: named, or covered by its OTHER)."""
    from alpha_poke.agents.damage_obs import OTHER

    t = sum(dist.values()) or 1.0
    p = dist.get(truth, 0.0) / t
    s["n"] += 1
    s["w"] += w
    s["nll"] += w * -math.log(max(p, 1e-6))
    s["top1"] += w * (bool(dist) and max(dist, key=dist.get) == truth)
    s["zero"] += w * (p < 1e-4)
    for n in WORLDS:
        s[f"in{n}"] += w * (min(1.0, n * p) if strat else 1 - (1 - p) ** n)
    if f1 is not None:
        s["f1"] += w * (truth in f1 or OTHER in f1)
        s["f1n"] += w


HEAD = (
    f"{'NLL':>6} {'top-1':>6} {'at 0':>6} "
    + " ".join(f"{'in ' + str(n):>6}" for n in WORLDS)
    + f" {'in F1':>6}"
)


def line(s: dict) -> str:
    """The row of ``score``'s sums."""
    w = s["w"] or 1.0
    out = f"{s['nll'] / w:6.3f} {s['top1'] / w:6.1%} {s['zero'] / w:6.1%} "
    out += " ".join(f"{s[f'in{n}'] / w:6.1%}" for n in WORLDS)
    return out + (f" {s['f1'] / s['f1n']:6.1%}" if s.get("f1n") else f" {'':>6}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-06", help="teams first posted from this month on")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    from poke_env.battle import Pokemon

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.agents.engine_state import _smogon
    from alpha_poke.analysis.roles import to_id
    from alpha_poke.coach.team import parse_team
    from alpha_poke.enginecheck.beliefcheck import _item_support
    from alpha_poke.teams import catalog

    belief = BeliefModel.load()
    sm = _smogon(belief)
    teams = [e for e in catalog.load(dedup=True) if e.complete and e.date[:7] >= a.since]
    rng = random.Random(a.seed)
    cases = []  # (team names, poke-env mon, species, shown moves, true item, true tera)
    for e in teams:
        sets = parse_team(e.text)
        mons = {sid: Pokemon(gen=9, species=sid) for sid in sets}
        names = tuple(belief.display(sid) for sid in sets)
        for sid, k in sets.items():
            moves = [to_id(m) for m in k.moves]
            for shown in (0, 2):
                cases.append((names, mons[sid], belief.display(sid), rng.sample(moves, min(shown, len(moves))),
                              to_id(k.item or "none") or "none", to_id(k.tera or "")))  # fmt: skip
    print(
        f"{len(teams)} teams (one per family, first posted since {a.since}), {len(cases) // 2} mons"
    )

    rows = {}
    for label, opts in CONFIGS:
        configure(belief, opts)
        stats = collections.defaultdict(lambda: collections.defaultdict(float))
        for names, mon, species, shown, item, tera in cases:
            score(_item_support(belief, mon, names, shown), item, stats[("item", len(shown))],
                  f1=f1_items(belief, mon, names), strat=belief.stratify)  # fmt: skip
            if tera:
                score(tera_dist(belief, species, names, shown), tera, stats[("tera", len(shown))])
        rows[label] = stats
    usage = collections.defaultdict(lambda: collections.defaultdict(float))
    for _, _, species, shown, item, tera in cases:
        if shown:
            continue
        d = sm.predict(species, (species,))
        score(
            {("none" if to_id(k) == "nothing" else to_id(k)): v for k, v in d.item.items()},
            item,
            usage[("item", 0)],
        )
        if tera:
            score({to_id(k): v for k, v in d.tera.items()}, tera, usage[("tera", 0)])  # fmt: skip
    rows["Smogon usage (reference)"] = usage

    print(f"{'':26} {'shown':>5} {'n':>6}  {HEAD}")
    for attr in ("item", "tera"):
        for label, stats in rows.items():
            for shown in (0, 2):
                s = stats.get((attr, shown))
                if s and s["n"]:
                    print(f"{attr + ': ' + label:26} {shown:5} {int(s['n']):6}  {line(s)}")


if __name__ == "__main__":
    main()
