"""F1 acceptance (design TODO 特征候选): the damage likelihood of agents/damage_obs.py on self-play
games, where both sides' true sets are known (the decision records' own sides).

Usage: uv run python scripts/check_damage_belief.py --gen 8 --workers 0,1 --games 300

The log's player (a game's log file is one player's view: its HP exact, ``viewer``) and its
turn-start decision states give the clean hits and their base states; the candidates are the
belief's (top items, the possible abilities, the usage spreads) plus the other player's true set. Reports how often the true set's likelihood is 0 (it would be
excluded without the floor: an engine / parse mismatch), the prior / posterior mass on the true
item, ability and the stats the hits speak to, and the share of mons whose most likely item is
the true one. States from before L31 (gen <= 8) keep the tera type in a terastallized mon's
types: its base types are copied back (``fix_tera_types``).
"""

import argparse
import collections
import json
import logging
import sys

import alpha_search
import numpy as np
import poke_engine as pe
from poke_env.data import GenData

from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.agents.damage import calc_stats
from alpha_poke.agents.damage_obs import hits, likelihood, posterior, slot_of
from alpha_poke.agents.engine_state import _prior
from alpha_poke.agents.speed import spread_dist
from alpha_poke.analysis.roles import to_id
from alpha_poke.selfplay import SELFPLAY_DIR
from alpha_poke.teams import DEFAULT_POOL

DEX = GenData.from_gen(9).pokedex


def fix_tera_types(state: str) -> str:
    """States from before L31: a terastallized mon's types are its tera type; its base types
    (fields 4-5) are right: copy them back (the engine's semantics, the current build_state)."""
    st = pe.State.from_string(state)
    tera = [[p.terastallized for p in side.pokemon] for side in (st.side_one, st.side_two)]
    parts = state.split("/")
    for k in (0, 1):
        segs = parts[k].split("=")
        for i in range(min(6, len(segs))):
            if tera[k][i]:
                f = segs[i].split(",")
                f[2], f[3] = f[4], f[5]
                segs[i] = ",".join(f)
        parts[k] = "=".join(segs)
    return "/".join(parts)


def viewer(lines: list[str]) -> str | None:
    """The side whose view the log is (its HP exact: a denominator other than 100)."""
    for line in lines:
        f = line.split("|")
        if len(f) > 4 and f[1] == "switch" and "/" in f[4]:
            if f[4].split()[0].split("/")[1] != "100":
                return f[2][:2]
    return None


def dex_key(species: str) -> str | None:
    k = to_id(species)
    return k if k in DEX else next((x for x in DEX if to_id(x) == k), None)


def load_games(gen: int, worker: str, n: int):
    """{game: p1's log lines}, {game: {(side, turn): turn-start state}} for the first n games."""
    logs: dict = {}
    with open(SELFPLAY_DIR / f"gen{gen}" / f"logs-w{worker}.jsonl") as f:
        for line in f:
            d = json.loads(line)
            logs[d["pair"]] = d["log"].split("\n")
            if len(logs) >= n:
                break
    recs: dict = collections.defaultdict(dict)
    with open(SELFPLAY_DIR / f"gen{gen}" / f"decisions-w{worker}.jsonl") as f:
        for line in f:
            i = line.index('"game": ') + 8
            if int(line[i : line.index(",", i)]) not in logs:
                continue
            r = json.loads(line)
            if r["kind"] == 0:
                state = fix_tera_types(r["state"]) if gen <= 8 else r["state"]
                recs[r["game"]].setdefault((r["side"], r["turn"]), state)
    return logs, recs


def candidates(belief, their: str, truth, names, t_item: str, t_ability: str):
    """(cands [(item, ability, stats [6])], prior, keys) for the true mon ``truth`` of species
    ``their``; the true item / ability always among them."""
    key = dex_key(their)
    dist = _prior(belief, belief.display(their), names)
    items = sorted(dist.item.items(), key=lambda x: -x[1])[:8]
    if t_item not in dict(items):
        items.append((t_item, 1e-3))
    abilities = [to_id(a) for a in DEX[key]["abilities"].values()]
    if t_ability not in abilities:
        abilities.append(t_ability)
    spreads, ws = spread_dist(DEX[key]["name"])
    if not spreads:
        spreads, ws = [belief.spread_for(DEX[key]["name"])], [1.0]
    stats = [calc_stats(DEX[key]["baseStats"], sp, level=int(truth.level)) for sp in spreads[:12]]
    cands, prior = [], []
    for it, pi in items:
        for ab in abilities:
            for st, w in zip(stats, ws[:12], strict=True):
                v = [st["hp"], st["atk"], st["def"], st["spa"], st["spd"], st["spe"]]
                cands.append((it, ab, v))
                prior.append(pi * w / len(abilities))
    return cands, prior


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, default=8)
    ap.add_argument("--workers", default="0")
    ap.add_argument("--games", type=int, default=300, help="per worker")
    ap.add_argument("--show", type=int, default=0, help="print this many excluded true sets")
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    belief = BeliefModel.load(heldout_pool=str(DEFAULT_POOL))
    stats = collections.Counter()
    prior_m: dict = collections.defaultdict(list)
    post_m: dict = collections.defaultdict(list)
    for worker in a.workers.split(","):
        logs, recs = load_games(a.gen, worker, a.games)
        for g, lines in logs.items():
            me = viewer(lines)
            other = "p2" if me == "p1" else "p1"
            theirs = [s for (side, _), s in recs[g].items() if side == other]
            if me is None or not theirs:
                continue
            truth = {to_id(str(p.id)): p for p in pe.State.from_string(theirs[0]).side_one.pokemon
                     if str(p.id) != "NONE"}  # fmt: skip
            names = tuple(belief.display(k) for k in truth)
            by_mon = collections.defaultdict(list)
            for h in hits(lines, me):
                base = recs[g].get((me, h.turn))
                their = h.defender if h.by_us else h.attacker
                ours = h.attacker if h.by_us else h.defender
                if base is None or to_id(their) not in truth:
                    stats["unmapped"] += 1
                    continue
                bs = pe.State.from_string(base)
                os_, ts = slot_of(bs, True, ours), slot_of(bs, False, their)
                if os_ is None or ts is None:
                    stats["unmapped"] += 1
                    continue
                by_mon[their].append((h, base, os_, ts))
            for their, obs in by_mon.items():
                t = truth[to_id(their)]
                if dex_key(their) is None:
                    continue
                t_item, t_ability = str(t.item).lower(), str(t.ability).lower()
                t_stats = [t.maxhp, t.attack, t.defense, t.special_attack, t.special_defense,
                           t.speed]  # fmt: skip
                cands, prior = candidates(belief, their, t, names, t_item, t_ability)
                likes = []
                for h, base, os_, ts in obs:
                    on = h.tera if not h.by_us else h.defender_tera  # theirs terastallized
                    tera = on or str(t.tera_type).lower()
                    cs = [(c[0], c[1], c[2], tera, bool(on)) for c in cands]
                    lk = likelihood(h, base, os_, ts, cs + [(t_item, t_ability, t_stats, tera,
                                                             bool(on))])  # fmt: skip
                    stats["hits"] += 1
                    stats["by_us" if h.by_us else "by_them"] += 1
                    if lk[-1] == 0.0:
                        stats["true set excluded"] += 1
                        if stats["true set excluded"] <= a.show:
                            r = alpha_search.set_damage_rolls(
                                base, h.by_us, h.move, os_, ts,
                                [(t_item, t_ability, t_stats, tera, bool(on))],
                                bool(h.tera if h.by_us else h.defender_tera))[0]  # fmt: skip
                            print(f"excluded: game {g} turn {h.turn} {h.move} {h.attacker} -> "
                                  f"{h.defender} {h.before} -> {h.after}; true {t_item} "
                                  f"{t_ability} {t_stats}; rolls {r and (min(r), max(r))}",
                                  file=sys.stderr)  # fmt: skip
                    likes.append(lk[:-1])
                post = posterior(prior, likes)
                total = sum(prior)
                rel = [0, 1, 3] if any(not h.by_us for h, *_ in obs) else [0, 2, 4]
                tests = {"item": lambda c: c[0] == t_item, "ability": lambda c: c[1] == t_ability,
                         "stats": lambda c: all(c[2][i] == t_stats[i] for i in rel)}  # fmt: skip
                for name, f in tests.items():
                    prior_m[name].append(sum(p for p, c in zip(prior, cands) if f(c)) / total)
                    post_m[name].append(sum(p for p, c in zip(post, cands) if f(c)))
                stats["mons"] += 1
                stats["top item right (prior)"] += max(zip(prior, cands))[1][0] == t_item
                stats["top item right (posterior)"] += max(zip(post, cands))[1][0] == t_item
    n = max(stats["hits"], 1)
    print(dict(stats))
    print(f"true set excluded: {stats['true set excluded'] / n:.2%} of {stats['hits']} hits")
    for k in prior_m:
        print(f"{k:8s} mass on the truth: prior {np.mean(prior_m[k]):.3f} -> posterior "
              f"{np.mean(post_m[k]):.3f}  ({len(prior_m[k])} mons)")  # fmt: skip


if __name__ == "__main__":
    main()
