"""Diagnostics of self-play's synthetic teams (selfplay.teams.Composer, 2026-10-26): N validated
synthetic sides against the real ones -- the validator's pass rate; the species' shares against
Smogon's usage; the teammate pairs' co-occurrence against the real compositions' (the joint
distribution kept?); the compositions' variety (distinct, seen on the ladder); the sets' items /
abilities / tera types against Smogon's.

  uv run python scripts/check_synthetic_teams.py --n 1000 [--tau 1.0 --gamma 1.0]
"""

import argparse
import collections
import itertools
import json
import logging

import numpy as np

from alpha_poke.analysis.roles import to_id


def _sets(text: str) -> list[dict]:
    """The sets of an export: species, item, ability, tera (ids)."""
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().splitlines()
        head = lines[0].split(" @ ")
        d = {
            "species": to_id(head[0].split(" (")[0]),
            "item": to_id(head[1]) if len(head) > 1 else "",
        }
        for ln in lines[1:]:
            if ln.startswith("Ability:"):
                d["ability"] = to_id(ln[8:])
            elif ln.startswith("Tera Type:"):
                d["tera"] = to_id(ln[10:])
            elif ln.startswith("- "):
                d.setdefault("moves", []).append(to_id(ln[2:]))
        out.append(d)
    return out


def _tv(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in keys)


def _norm(c: collections.Counter) -> dict:
    t = sum(c.values())
    return {k: v / t for k, v in c.items()} if t else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000, help="synthetic sides (half as many pairs)")
    ap.add_argument("--tau", type=float, default=1.0)
    ap.add_argument("--gamma", type=float, default=0.7)
    ap.add_argument("--eps", type=float, default=0.1, help="the composition's noise")
    ap.add_argument("--set-eps", type=float, default=0.1, help="the sets' noise")
    ap.add_argument("--beta", type=float, default=0.5, help="the sets' synergy weight")
    ap.add_argument("--steps", type=int, default=12, help="Metropolis-Hastings steps per team")
    ap.add_argument("--real-sets", type=int, default=3000, help="real games parsed for the combos")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay import teams

    logging.disable(logging.WARNING)
    ts = teams.TeamSampler(BeliefModel.load(), since=1746057600, catalog_frac=0.0, synth_frac=1.0,
                           synth_tau=a.tau, synth_gamma=a.gamma, synth_eps=a.eps, set_eps=a.set_eps,
                           synth_beta=a.beta, synth_steps=a.steps,
                           seed=a.seed)  # fmt: skip
    msgs = []
    pairs = ts.sample(a.n // 2, log=msgs.append)
    synth = [_sets(s.text) for p in pairs for s in (p.p1, p.p2)]
    syn_comps = [frozenset(m["species"] for m in t) for t in synth]

    # the real compositions of the sampler's window (the ladder's), as many
    rng = np.random.default_rng(a.seed)
    idx = rng.choice(len(ts.games), size=len(synth) // 2, p=ts.weights)
    real_comps = []
    for col in ("team1", "team2"):
        for t in ts.games[col].iloc[idx]:
            real_comps.append(frozenset(to_id(x.replace("-*", "")) for x in str(t).split("|")))
    all_real = {frozenset(to_id(x.replace("-*", "")) for x in str(t).split("|"))
                for col in ("team1", "team2") for t in ts.games[col]}  # fmt: skip

    usage = {to_id(n): ts.stats.species[n].usage for n in ts.composer.names}
    tot = sum(usage.values())
    usage = {k: v / tot for k, v in usage.items()}
    syn_species = _norm(collections.Counter(sp for c in syn_comps for sp in c))
    real_species = _norm(collections.Counter(sp for c in real_comps for sp in c))

    def pair_rates(comps):
        c = collections.Counter(
            p for comp in comps for p in itertools.combinations(sorted(comp), 2)
        )
        return {k: v / len(comps) for k, v in c.items()}

    syn_pairs, real_pairs = pair_rates(syn_comps), pair_rates(real_comps)
    top = sorted(real_pairs, key=lambda k: -real_pairs[k])[:200]
    x = np.array([real_pairs[k] for k in top])
    y = np.array([syn_pairs.get(k, 0.0) for k in top])
    # (the same pairs' rates if the species were drawn alone: products of the shares x 15/36)
    indep = np.array([syn_species.get(i, 0) * syn_species.get(j, 0) * 36 * 15 / 36 for i, j in top])

    items = collections.defaultdict(collections.Counter)
    abil = collections.defaultdict(collections.Counter)
    tera = collections.defaultdict(collections.Counter)
    for t in synth:
        for m in t:
            items[m["species"]][m["item"]] += 1
            abil[m["species"]][m.get("ability", "")] += 1
            tera[m["species"]][m.get("tera", "")] += 1
    set_tv = {}
    for name in ts.composer.names[:30]:
        sp = to_id(name)
        st = ts.stats.species[name]
        if items[sp].total() >= 20:
            set_tv[name] = {
                "n": items[sp].total(),
                "item_tv": round(
                    _tv(_norm(items[sp]), {to_id(k): v for k, v in st.items.items()}), 3
                ),
                "ability_tv": round(
                    _tv(_norm(abil[sp]), {to_id(k): v for k, v in st.abilities.items()}), 3
                ),
                "tera_tv": round(
                    _tv(_norm(tera[sp]), {to_id(k): v for k, v in st.tera_types.items()}), 3
                ),
            }

    # the sets' cross-mon combos (selfplay.synergy): a feature t on one mon, how often a teammate
    # has u -- against the real teams' revealed sets (a lower bound: what was not revealed is not)
    from alpha_poke.selfplay import synergy

    def feats(t):
        return [synergy.tokens(m.get("ability"), m.get("item"), m.get("moves", [])) for m in t]

    syn_feats = [feats(t) for t in synth]
    combos = [("a:drought", "a:chlorophyll"), ("a:drizzle", "a:swiftswim"), ("a:sandstream", "a:sandrush"),
              ("m:trickroom", "m:trickroom"), ("m:stickyweb", "i:focussash"), ("m:defog", "m:stealthrock"),
              ("a:drought", "a:protosynthesis"), ("a:electricsurge", "a:quarkdrive")]  # fmt: skip

    def combo_rates(teams):
        out = {}
        for t, u in combos:
            have = [any(u in f for j, f in enumerate(team) if j != i) for team in teams
                    for i, f in enumerate(team) if t in f]  # fmt: skip
            out[f"{t} -> {u}"] = (round(float(np.mean(have)), 3), len(have)) if have else None
        return out

    from alpha_poke.analysis.games_lite import logs
    from alpha_poke.replay.parser import parse_replay

    rows = ts.games.iloc[rng.choice(len(ts.games), size=a.real_sets, p=ts.weights)].to_dict("records")
    full = logs(rows)
    real_feats = []
    for r in rows:
        rep = parse_replay(full[r["id"]])
        for side in ("p1", "p2"):
            mons = [m for m in rep.teams[side] if not m.phantom]
            if not rep.warnings and len(mons) == 6:
                real_feats.append([synergy.tokens(m.ability, m.item, m.moves) for m in mons])

    out = {
        "sampler": msgs,
        "set_synergy": {"mean_team_score": round(float(np.mean([ts.synergy.team_score(f) for f in syn_feats])), 2)
                        if ts.synergy else None, "combos_synthetic": combo_rates(syn_feats),
                        "combos_real_revealed": combo_rates(real_feats)},
        "synthetic_sides": len(synth),
        "species": {"tv_synthetic_vs_usage": round(_tv(syn_species, usage), 3),
                    "tv_real_vs_usage": round(_tv(real_species, usage), 3),
                    "distinct_synthetic": len(syn_species), "distinct_real": len(real_species)},
        "teammate_pairs_top200": {"corr_synthetic_vs_real": round(float(np.corrcoef(x, y)[0, 1]), 3),
                                  "corr_independent_vs_real": round(float(np.corrcoef(x, indep)[0, 1]), 3),
                                  "mean_rate_real": round(float(x.mean()), 4),
                                  "mean_rate_synthetic": round(float(y.mean()), 4)},
        "compositions": {"distinct_synthetic": len(set(syn_comps)) / len(syn_comps),
                         "distinct_real": len(set(real_comps)) / len(real_comps),
                         "synthetic_seen_on_the_ladder": round(sum(c in all_real for c in syn_comps) / len(syn_comps), 3)},
        "sets_tv_top30": set_tv,
        "examples": [sorted(c) for c in syn_comps[:8]],
    }  # fmt: skip
    text = json.dumps(out, indent=1)
    print(text)
    if a.out:
        open(a.out, "w").write(text)


if __name__ == "__main__":
    main()
