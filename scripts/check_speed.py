"""Who moves first, predicted three ways against the games (design D17 A, 2026-10-11): from one
side's view (its true speeds from the game's teams), the probability the opponent's active moves
first at each observed turn (agents/speed.py observations), the opponent's speed from

  fixed       the species' most common spread (what the search did), Choice Scarf by usage
  dist        the usage spreads (top 30), Choice Scarf by usage
  inferred    dist, weighted by consistency with the earlier turns of the game for that mon

Reported: accuracy (the likelier side), log loss, and the confidently wrong share (the true order
given < 10%: the "moved first, I fainted before acting" surprises).

  uv run python scripts/check_speed.py --gen 5 --games 3000
"""

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from alpha_poke.agents.speed import GEN, _by_id, consistent, observations, opp_eff, spread_dist
from alpha_poke.analysis.roles import to_id

STATS = ("hp", "atk", "def", "spa", "spd", "spe")


def speed_stat(species: str, nature: str, ev: int, iv: int = 31, level: int = 100) -> int:
    base = (GEN.pokedex.get(to_id(species)) or {}).get("baseStats", {}).get("spe", 80)
    mult = GEN.natures.get(to_id(nature), {}).get("spe", 1.0)
    return int(((2 * base + iv + ev // 4) * level // 100 + 5) * mult)


def parse_team(text: str) -> dict:
    """species id -> (speed stat, item id, ability id) from a Showdown export."""
    out = {}
    for block in text.strip().split("\n\n"):
        lines = [x.strip() for x in block.strip().split("\n") if x.strip()]
        if not lines:
            continue
        head = lines[0]
        item = to_id(head.split("@", 1)[1]) if "@" in head else ""
        name = head.split("@")[0].strip()
        m = re.search(r"\(([^()]{3,})\)", name)
        species = (
            m.group(1) if m and m.group(1) not in ("M", "F") else re.sub(r"\s*\([MF]\)", "", name)
        )
        nature, ev, iv, ability = "serious", 0, 31, ""
        for x in lines[1:]:
            if x.startswith("Ability:"):
                ability = to_id(x.split(":", 1)[1])
            elif x.endswith("Nature"):
                nature = x.split()[0]
            elif x.startswith("EVs:"):
                ev = next((int(p.split()[0]) for p in x[4:].split("/") if "Spe" in p), 0)
            elif x.startswith("IVs:"):
                iv = next((int(p.split()[0]) for p in x[4:].split("/") if "Spe" in p), 31)
        out[to_id(species)] = (speed_stat(species, nature, ev, iv), item, ability)
    return out


def p_scarf(species: str) -> float:
    s = _by_id().get(to_id(species))
    if s is None or not s.items:
        return 0.05
    tot = sum(s.items.values()) or 1
    return s.items.get("choicescarf", 0) / tot


def p_first(o, cands) -> float:
    """P(opponent first) over weighted (speed stat, item) candidates (ties: half)."""
    tot = sum(w for _, _, w in cands) or 1
    p = 0.0
    for stat, item, w in cands:
        e = opp_eff(o, stat, item)
        if e == o.ours:
            p += 0.5 * w
        elif (e > o.ours) != o.trick_room:
            p += w
    return p / tot


def candidates(species: str, fixed: bool) -> list:
    spreads, ws = spread_dist(species)
    if not spreads:
        return []
    if fixed:
        spreads, ws = spreads[:1], (1.0,)
    ps = p_scarf(species)
    out = []
    for sp, w in zip(spreads, ws, strict=True):
        stat = speed_stat(species, sp.nature, sp.evs[5])
        out += [(stat, "choicescarf", w * ps), (stat, "", w * (1 - ps))]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--games", type=int, default=3000)
    a = ap.parse_args()
    d = Path(f"data/selfplay/gen{a.gen}")
    teams = [json.loads(x) for x in (d / "teams.jsonl").read_text().splitlines()]
    games = {}
    for f in sorted(d.glob("games-w*.jsonl")):
        for line in f.open():
            g = json.loads(line)
            games[g["pair"]] = g
    res = defaultdict(lambda: {"n": 0, "acc": 0.0, "ll": 0.0, "wrong": 0})
    n_games = 0
    for f in sorted(d.glob("logs-w*.jsonl")):
        for line in f.open():
            if n_games >= a.games:
                break
            g = json.loads(line)
            meta = games.get(g["pair"])
            if meta is None or g["pair"] >= len(teams):
                continue
            n_games += 1
            pair = teams[g["pair"]]
            side_team = {meta["a_side"]: pair["p1"]["text"],
                         ("p2" if meta["a_side"] == "p1" else "p1"): pair["p2"]["text"]}  # fmt: skip
            lines = [x.split("|") for x in g["log"].split("\n")]
            for us in ("p1", "p2"):
                ours = parse_team(side_team[us])
                obs = observations(lines, us, lambda sp, t=ours: t.get(sp, (0, "", "")))
                seen = defaultdict(list)
                for o in obs:
                    for kind in ("fixed", "dist", "inferred"):
                        cands = candidates(o.species, kind == "fixed")
                        if not cands:
                            break
                        if kind == "inferred":
                            prior = seen[o.species]
                            kept = [c for c in cands if consistent(prior, c[0], c[1])]
                            cands = kept or cands
                        p = p_first(o, cands)
                        q = p if o.opp_first else 1 - p
                        r = res[kind]
                        r["n"] += 1
                        r["acc"] += 1.0 if q > 0.5 else 0.5 if q == 0.5 else 0.0
                        r["ll"] += -math.log(min(max(q, 1e-3), 1))
                        r["wrong"] += q < 0.1
                    seen[o.species].append(o)
    print(f"{n_games} games, both sides' views")
    for kind in ("fixed", "dist", "inferred"):
        r = res[kind]
        n = max(r["n"], 1)
        print(f"{kind:9s} n={r['n']:6d}  accuracy {r['acc'] / n:.3f}  log loss {r['ll'] / n:.3f}"
              f"  confidently wrong {r['wrong'] / n:.3%}")  # fmt: skip


if __name__ == "__main__":
    main()
