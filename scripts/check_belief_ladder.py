"""The belief's item and tera draws against the ladder's own population (issue #33), not the
forum's teams (scripts/check_belief_sets.py): held-out ladder replays (after the replay tables
the belief was built from), each revealed value weighted by 1 / P(revealed | value, times the mon
came in) -- inverse probability weighting. A replay shows a Booster Energy nearly always, Heavy-
Duty Boots or a Choice Scarf rarely; weighted, the revealed ones stand for the unrevealed alike,
so the mean -log P is an estimate of the one over every mon that came in, shown or not.

The reveal rates come from self-play (the generation's games; both sides' teams known in full:
teams.jsonl), the same parser on both. They assume a value is revealed as often in a ladder game
as in self-play, given the value and the switch-ins; the check of that: the weighted item shares
per species against Smogon's usage (the ladder's teams, unrevealed items included), next to the
raw revealed shares.

  uv run python scripts/check_belief_ladder.py [--gen 0] [--selfplay 12000] [--replays 6000]
"""

import argparse
import collections
import gzip
import json
import math
import sqlite3

MIN_N = 30  # self-play observations a reveal rate needs (else the value's pooled over switch-ins)
MIN_RATE = 0.02  # rarer: the value is left out (its weights would be noise) and counted apart


def bucket(entries: int) -> int:
    return min(entries, 4)


def selfplay_rates(gen: int, n: int) -> tuple[dict, dict]:
    """attr -> {(value, bucket) | (value, None): (revealed, seen)} over self-play mons that came in,
    and diagnostics. Streams the generation's files (each worker's first games)."""
    from alpha_poke.analysis.roles import to_id
    from alpha_poke.coach.team import parse_team
    from alpha_poke.replay import parse_replay
    from alpha_poke.selfplay import SELFPLAY_DIR

    gd = SELFPLAY_DIR / f"gen{gen}"
    # (a worker's logs keep the games of an earlier draw of the teams, their pairs another
    # team's: a log is taken only with its games row's attempt -- that row is the pair's current)
    want: dict[int, list] = {}
    for w in sorted(gd.glob("games-w*.jsonl")):
        done, k = set(), 0
        with open(w, encoding="utf-8") as fh:
            for line in fh:
                if k >= n // 10:
                    break
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                done.add((r["pair"], r.get("attempt")))
                k += 1
        with open(gd / w.name.replace("games-", "logs-"), encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if (r["pair"], r.get("attempt")) in done:
                    want.setdefault(r["pair"], []).append(r["log"])
    counts = {
        "item": collections.defaultdict(lambda: [0, 0]),
        "tera": collections.defaultdict(lambda: [0, 0]),
    }
    diag = collections.Counter()
    with open(gd / "teams.jsonl", encoding="utf-8") as fh:
        for pair, line in enumerate(fh):
            if pair not in want:
                continue
            sides = json.loads(line)
            truth = {s: parse_team(sides[s]["text"]) for s in ("p1", "p2")}
            for log in want[pair]:
                try:
                    rep = parse_replay({"id": f"sp-{pair}", "log": log, "uploadtime": 0})
                except Exception:  # noqa: BLE001 - a log the parser refuses
                    diag["unparsed"] += 1
                    continue

                # (the challenger alternates: the log's p1 is either team -- the one whose
                # species it shows)
                def overlap(side, team, rep=rep):
                    ids = {to_id(m.species.replace("-*", "")) for m in rep.teams[side]}
                    return sum(any(k.startswith(i) or i.startswith(k) for k in team) for i in ids)

                swap = overlap("p1", truth["p2"]) > overlap("p1", truth["p1"])
                for side in ("p1", "p2"):
                    own = truth[{"p1": "p2", "p2": "p1"}[side] if swap else side]
                    for m in rep.teams[side]:
                        if m.phantom or not m.switch_ins:
                            continue
                        sid = to_id(m.species.replace("-*", ""))
                        t = next(
                            (v for k, v in own.items() if k.startswith(sid) or sid.startswith(k)),
                            None,
                        )
                        if t is None:
                            diag["no truth"] += 1
                            continue
                        b = bucket(len(m.switch_ins))
                        for attr, true, seen in (("item", to_id(t.item or "") or "none", to_id(m.item or "")),
                                                 ("tera", to_id(t.tera or ""), to_id(m.tera_type or ""))):  # fmt: skip
                            if not true:
                                continue
                            if seen and seen != true:
                                diag[f"{attr} shown != true (Trick, Illusion, ...)"] += 1
                                continue
                            for key in ((true, b), (true, None)):
                                counts[attr][key][0] += bool(seen)
                                counts[attr][key][1] += 1
                diag["games"] += 1
    return counts, diag


def rate(counts: dict, value: str, b: int) -> float | None:
    for key in ((value, b), (value, None)):
        r, n = counts.get(key, (0, 0))
        if n >= MIN_N:
            return r / n
    return None


def ladder_mons(n: int, after: float):
    """(team preview names, species, item shown, tera shown, first two moves shown, switch-ins)
    of held-out ladder replays (uploaded after ``after``), both sides."""
    from alpha_poke import paths
    from alpha_poke.replay import parse_replay

    db = sqlite3.connect(paths.REPLAYS / "index.sqlite")
    rows = db.execute(
        "SELECT id, format_id FROM replays WHERE status='done' AND format_id='gen9ou' AND uploadtime > ? "
        "ORDER BY uploadtime LIMIT ?",
        (after, n),
    ).fetchall()
    for rid, fid in rows:
        try:
            with gzip.open(paths.REPLAYS / fid / f"{rid}.json.gz", "rt", encoding="utf-8") as f:
                rep = parse_replay(json.load(f))
        except Exception:  # noqa: BLE001
            continue
        for side in ("p1", "p2"):
            team = [m for m in rep.teams[side] if not m.phantom]
            names = tuple(m.species for m in team)
            for m in team:
                if m.switch_ins:
                    yield names, m.species, m.item, m.tera_type, m.moves[:2], len(m.switch_ins)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, default=0)
    ap.add_argument("--selfplay", type=int, default=12000, help="self-play games for the rates")
    ap.add_argument("--replays", type=int, default=6000)
    a = ap.parse_args()

    import pandas as pd
    from check_belief_sets import tera_dist
    from poke_env.battle import Pokemon

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.analysis.roles import to_id
    from alpha_poke.analysis.tables import OUT
    from alpha_poke.enginecheck.beliefcheck import _item_support

    counts, diag = selfplay_rates(a.gen, a.selfplay)
    print(f"reveal rates from {diag['games']} self-play games; {dict(diag)}")
    for attr in ("item", "tera"):
        top = sorted(
            ((v, rn) for (v, b), rn in counts[attr].items() if b is None), key=lambda x: -x[1][1]
        )[:12]
        print(f"  {attr}: " + ", ".join(f"{v} {r / n:.2f} ({n})" for v, (r, n) in top))

    after = int(
        pd.read_parquet(OUT / "gen9ou_games.parquet", columns=["uploadtime"]).uploadtime.max()
    )
    belief = BeliefModel.load()
    mons = list(ladder_mons(a.replays, after))
    print(f"{len(mons)} mons that came in, held-out ladder replays (after the belief's tables)")

    # the check of the rates: weighted shares per species vs Smogon's usage, raw shares beside
    shares = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    for _, sp, item, _, _, ins in mons:
        it = to_id(item or "")
        if it:
            r = rate(counts["item"], it, bucket(ins))
            shares[sp][0][it] += 1
            if r and r >= MIN_RATE:
                shares[sp][1][it] += 1 / r
    from alpha_poke.belief.priors import SmogonPrior
    from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats

    month = sorted(p.name for p in DEFAULT_DIR.iterdir() if p.is_dir())[-1]
    top = sorted(shares, key=lambda s: -sum(shares[s][0].values()))[:20]
    for cut in (0, 1500, 1825):
        f = DEFAULT_DIR / month / "chaos" / f"gen9ou-{cut}.json"
        if not f.exists():
            continue
        prior = SmogonPrior(UsageStats.load(f))
        tv = {"raw": [], "weighted": []}
        for sp in top:
            name = belief.display(to_id(sp.replace("-*", "")))
            use = prior.predict(name, (name,)).item
            t = sum(use.values()) or 1
            use = {("none" if to_id(k) == "nothing" else to_id(k)): v / t for k, v in use.items()}
            for label, c in (("raw", shares[sp][0]), ("weighted", shares[sp][1])):
                n = sum(c.values()) or 1
                d = {k: v / n for k, v in c.items()}
                tv[label].append(
                    sum(abs(d.get(k, 0) - use.get(k, 0)) for k in set(d) | set(use)) / 2
                )
        print(f"item shares vs Smogon {month} gen9ou-{cut} (top 20 species, mean TV): raw revealed "
              f"{sum(tv['raw']) / len(tv['raw']):.3f}, weighted {sum(tv['weighted']) / len(tv['weighted']):.3f}")  # fmt: skip

    print(f"{'':22} {'shown':>5} {'n':>6} {'weight':>8}  {'NLL':>6} {'top-1':>6}  (weighted)")
    skipped = collections.Counter()
    for label, on in (("belief", False), ("belief raked", True)):
        belief.rake = on
        st = collections.defaultdict(lambda: collections.defaultdict(float))
        for names, sp, item, tera, moves, ins in mons:
            name = belief.display(to_id(sp.replace("-*", "")))
            mon = Pokemon(gen=9, species=to_id(sp.replace("-*", "")))
            team = tuple(belief.display(to_id(x.replace("-*", ""))) for x in names)
            for attr, val in (("item", to_id(item or "")), ("tera", to_id(tera or ""))):
                if not val:
                    continue
                r = rate(counts[attr], val, bucket(ins))
                if r is None or r < MIN_RATE:
                    skipped[(attr, "rare or unseen in self-play")] += on is False
                    continue
                w = 1 / r
                for shown in (0, 2):
                    mv = [to_id(x) for x in moves[:shown]]
                    d = (
                        _item_support(belief, mon, team, mv)
                        if attr == "item"
                        else tera_dist(belief, name, team, mv)
                    )
                    p = d.get(val, 0.0) / (sum(d.values()) or 1.0)
                    s = st[(attr, shown)]
                    s["n"] += 1
                    s["w"] += w
                    s["nll"] += w * -math.log(max(p, 1e-6))
                    s["top1"] += w * (bool(d) and max(d, key=d.get) == val)
        for attr in ("item", "tera"):
            for shown in (0, 2):
                s = st[(attr, shown)]
                if s["n"]:
                    print(f"{attr + ': ' + label:22} {shown:5} {int(s['n']):6} {s['w']:8.0f}  "
                          f"{s['nll'] / s['w']:6.3f} {s['top1'] / s['w']:6.1%}")  # fmt: skip
    belief.rake = False
    print(f"left out: {dict(skipped)}")


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
