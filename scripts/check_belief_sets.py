"""A quick check of the belief's item and tera draws (seconds, no engine, no network): on the
catalog's complete teams (built by people: every item and tera type known, the ones that never
show in a game too), one team per near-duplicate family, the probability the sampler gives each
mon's true item and tera type at preview with 0 or 2 of its moves shown (engine_state.sample_set's
marginals: enginecheck.beliefcheck's item support; the archetype mix of the tera weights).

  uv run python scripts/check_belief_sets.py [--since 2025-06] [--rake both]

NLL: the mean -log P(the true value), floored at 1e-6; top-1: the most likely value is the true
one; at 0: P < 1e-4 (the draw hardly ever makes it). The teams are the forum's, which lean to
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


def score(dist: dict, truth: str, s: dict) -> None:
    t = sum(dist.values()) or 1.0
    p = dist.get(truth, 0.0) / t
    s["n"] += 1
    s["nll"] += -math.log(max(p, 1e-6))
    s["top1"] += bool(dist) and max(dist, key=dist.get) == truth
    s["zero"] += p < 1e-4


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-06", help="teams first posted from this month on")
    ap.add_argument("--rake", choices=["off", "on", "both"], default="both")
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
    for label, on in (("belief", False), ("belief raked", True)):
        if a.rake != "both" and (a.rake == "on") != on:
            continue
        belief.rake = on
        stats = collections.defaultdict(lambda: collections.defaultdict(float))
        for names, mon, species, shown, item, tera in cases:
            score(_item_support(belief, mon, names, shown), item, stats[("item", len(shown))])
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

    print(f"{'':26} {'shown':>5} {'n':>6}  {'NLL':>6} {'top-1':>6} {'at 0':>6}")
    for attr in ("item", "tera"):
        for label, stats in rows.items():
            for shown in (0, 2):
                s = stats.get((attr, shown))
                if s and s["n"]:
                    print(f"{attr + ': ' + label:26} {shown:5} {int(s['n']):6}  {s['nll'] / s['n']:6.3f} "
                          f"{s['top1'] / s['n']:6.1%} {s['zero'] / s['n']:6.1%}")  # fmt: skip


if __name__ == "__main__":
    main()
