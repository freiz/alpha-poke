"""poke-engine against Showdown on self-play games (differential test of the search's transition
model; design D17).

Self-play games are played on the local Showdown server by two of our bots, and each decision
record holds that player's own side exactly (its request) and the field. For a "clean" turn t
(both players chose at turn start t and t + 1, nobody made another decision in between: no
faint, no pivot switch), the full state before is merge_sides(p1's record, p2's record) at t and
the actual state after is the same at t + 1. The engine's chance outcomes of the two chosen
actions (alpha_search.chance_outcomes, damage rolls branched) are compared with the actual one:
discrete fields (actives, status, boosts, hazards, screens, volatiles, items, field) must agree
with some outcome, and every HP must lie within the outcomes' range (+- --hp-tol of max HP).

  uv run python scripts/check_engine_diff.py --gen 8 --games 3000

Report: data/selfplay/diag/engine_diff_gen<G>.json (counts per mismatch kind, per move pair,
examples) and a summary on stdout. A mismatch is ours to explain: the engine (rust/patches) or
the state construction (agents/engine_state.py, timers.py) -- the examples tell which.
"""

import argparse
import collections
import json
import re
import zlib
from pathlib import Path

import alpha_search
import poke_engine as pe

from alpha_poke.selfplay import SELFPLAY_DIR

KIND_MAIN = 0
BOOSTS = ("attack", "defense", "special_attack", "special_defense", "speed", "accuracy",
          "evasion")  # fmt: skip
HAZARDS = ("spikes", "toxic_spikes", "stealth_rock", "sticky_web")
TIMED = ("reflect", "light_screen", "aurora_veil", "tailwind", "safeguard", "mist")


def snapshot(state_str: str) -> tuple[dict, list[int], list[int]]:
    """(discrete fields, HP per mon (side one then two), max HP)"""
    s = pe.State.from_string(state_str)
    d: dict = {"weather": str(s.weather), "terrain": str(s.terrain), "trick_room": s.trick_room}
    hp, mx = [], []
    for k, side in (("s1", s.side_one), ("s2", s.side_two)):
        d[f"{k}.active"] = int(side.active_index)
        for j, p in enumerate(side.pokemon):
            d[f"{k}.{j}.status"] = str(p.status) if p.hp > 0 else "FAINTED"
            d[f"{k}.{j}.item"] = str(p.item)
            d[f"{k}.{j}.tera"] = bool(p.terastallized)
            hp.append(int(p.hp))
            mx.append(int(p.maxhp))
        for b in BOOSTS:
            d[f"{k}.boost.{b}"] = int(getattr(side, f"{b}_boost"))
        sc = side.side_conditions
        for h in HAZARDS:
            d[f"{k}.hazard.{h}"] = int(getattr(sc, h))
        for t in TIMED:
            d[f"{k}.screen.{t}"] = getattr(sc, t) > 0
        d[f"{k}.substitute"] = side.substitute_health > 0
        d[f"{k}.wish"] = side.wish[0] > 0
        d[f"{k}.future_sight"] = side.future_sight[0] > 0
        for v in side.volatile_statuses:
            d[f"{k}.volatile.{str(v).lower()}"] = True
    return d, hp, mx


def kind_of(field: str) -> str:
    """Aggregation key of a field: side and mon index dropped."""
    parts = field.split(".")
    if parts[0] in ("s1", "s2"):
        parts = [p for p in parts[1:] if not p.isdigit()]
    return ".".join(parts)


def hp_fits(before: int, engine: int, actual: int, tol: float) -> bool:
    """``actual`` within the damage rolls' spread around the engine's (average-roll) damage."""
    spread = 0.085 * max(before - engine, 0)  # (1 - 0.925) / 0.925 of an average roll
    return abs(actual - engine) <= spread + tol


def compare(before: str, after: str, slot1: int, slot2: int, hp_tol: float) -> dict:
    """The best-matching outcome's differences: {"discrete": {field: (engine, actual)},
    "hp": [(index, engine hp, actual hp, max hp)], "n_outcomes": n}. Chance (misses, crits,
    secondary effects, speed ties) is enumerated by the engine: matching any outcome is a match.
    Damage rolls are not: the engine deals the average roll (0.925 x max; it branches only on a
    KO and on crits), so an HP is a match within the rolls' spread around each outcome's damage
    (0.85 / 0.925 .. 1 / 0.925 of it) + ``hp_tol`` x max HP."""
    outs = alpha_search.chance_outcomes(before, slot1, slot2, True)
    _, b_hp, _ = snapshot(before)
    actual, a_hp, a_max = snapshot(after)
    snaps = [snapshot(s) for _, s, _ in outs]
    best = None
    for d, _, _ in snaps:
        keys = set(d) | set(actual)
        diff = {k: (d.get(k), actual.get(k)) for k in keys if d.get(k) != actual.get(k)}
        if best is None or len(diff) < len(best[0]):
            best = (diff, d)
    diff, d_best = best
    same = [hp for d, hp, _ in snaps if d == d_best] or [hp for _, hp, _ in snaps]
    bad_hp = []
    for i, (h, m) in enumerate(zip(a_hp, a_max, strict=True)):
        if not any(hp_fits(b_hp[i], x[i], h, max(2, hp_tol * m)) for x in same):
            e = min((x[i] for x in same), key=lambda v: abs(v - h))
            bad_hp.append((i, e, h, m))
    return {"discrete": diff, "hp": bad_hp, "n_outcomes": len(outs)}


def clean_turns(records: list[dict]):
    """(t, p1 record at t, p2 at t, p1 at t + 1, p2 at t + 1) for the clean turns of one game."""
    by = collections.defaultdict(list)
    for r in records:
        by[(r["side"], r["turn"])].append(r)
    turns = sorted({r["turn"] for r in records})
    for t in turns:
        now = [by.get((s, t), []) for s in ("p1", "p2")]
        nxt = [by.get((s, t + 1), []) for s in ("p1", "p2")]
        if any(len(x) != 1 or x[0]["kind"] != KIND_MAIN for x in now + nxt):
            continue  # an extra decision in the turn (faint, pivot) or a side with none
        yield t, now[0][0], now[1][0], nxt[0][0], nxt[1][0]


GAME = re.compile(r'"game": (\d+)')


def sampled_games(files: list[Path], per_file: int, frac: float, seed: int):
    """(key, records) of up to ``per_file`` games of each decision file, streamed: a game's
    records are contiguous (written when it ends), lines are parsed only for the chosen games
    (a hash of worker + game below ``frac``; a generation's files are ~33 GB: never load them
    whole -- 2026-10-16 that filled the memory and restarted WSL)."""
    for f in files:
        w = f.stem.split("-w")[1]
        taken, cur, lines = 0, None, []
        with open(f) as fh:
            for line in fh:
                m = GAME.search(line)
                g = m.group(1) if m else None
                if g != cur:
                    if lines:
                        yield (w, cur), [json.loads(x) for x in lines]
                        taken += 1
                        if taken >= per_file:
                            break
                    cur, lines = g, []
                if (
                    g is not None
                    and zlib.crc32(f"{seed}:{w}:{g}".encode()) % 10_000 < frac * 10_000
                ):
                    lines.append(line)
            else:
                if lines and taken < per_file:
                    yield (w, cur), [json.loads(x) for x in lines]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, default=8)
    ap.add_argument("--games", type=int, default=2000, help="games sampled (all workers)")
    ap.add_argument("--frac", type=float, default=0.05,
                    help="share of each file's games eligible (by a hash of the game)")  # fmt: skip
    ap.add_argument("--hp-tol", type=float, default=0.01, help="HP tolerance, share of max HP")
    ap.add_argument("--examples", type=int, default=8, help="examples kept per mismatch kind")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    gen_dir = SELFPLAY_DIR / f"gen{a.gen}"
    files = sorted(gen_dir.glob("decisions-w*.jsonl"))
    per_file = -(-a.games // len(files))
    n_turns = n_match = n_err = 0
    kinds: collections.Counter = collections.Counter()
    per_move: collections.Counter = collections.Counter()
    kind_moves: dict = collections.defaultdict(collections.Counter)  # kind -> move pairs
    moves_seen: collections.Counter = collections.Counter()
    examples: dict = collections.defaultdict(list)
    n_games = 0
    for key, records in sampled_games(files, per_file, a.frac, a.seed):
        n_games += 1
        for t, a1, a2, b1, b2 in clean_turns(records):
            before = alpha_search.merge_sides(a1["state"], a2["state"])
            after = alpha_search.merge_sides(b1["state"], b2["state"])
            m1, m2 = a1["names"][a1["slot"]], a2["names"][a2["slot"]]
            n_turns += 1
            moves_seen[m1] += 1
            moves_seen[m2] += 1
            try:
                res = compare(before, after, a1["slot"], a2["slot"], a.hp_tol)
            except Exception as e:  # noqa: BLE001 - a slot the engine does not offer, ...
                n_err += 1
                kinds[f"error: {type(e).__name__}: {str(e)[:60]}"] += 1
                continue
            found = {kind_of(k) for k in res["discrete"]}
            if res["hp"]:
                found.add("hp")
            if not found:
                n_match += 1
                continue
            for k in found:
                kinds[k] += 1
                kind_moves[k][f"{m1} | {m2}"] += 1
                if len(examples[k]) < a.examples:
                    examples[k].append({
                        "game": list(key), "turn": t, "p1": m1, "p2": m2,
                        "discrete": {f: v for f, v in res["discrete"].items()},
                        "hp": res["hp"], "before": before, "after": after})  # fmt: skip
            for m in (m1, m2):
                per_move[m] += 1
    rate = {m: round(per_move[m] / moves_seen[m], 4) for m in per_move if moves_seen[m] >= 30}
    out = {"gen": a.gen, "games": n_games, "clean_turns": n_turns, "match": n_match,
           "errors": n_err, "mismatch_kinds": kinds.most_common(),
           "mismatch_rate_by_move": sorted(rate.items(), key=lambda x: -x[1])[:60],
           "moves_by_kind": {k: c.most_common(15) for k, c in kind_moves.items()},
           "examples": examples}  # fmt: skip
    path = Path("data/selfplay/diag") / f"engine_diff_gen{a.gen}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    print(
        f"{n_games} games, {n_turns} clean turns: {n_match} match "
        f"({n_match / max(n_turns, 1):.1%}), {n_err} errors -> {path}"
    )
    for k, c in kinds.most_common(30):
        print(f"  {c:6d} ({c / max(n_turns, 1):.2%})  {k}")


if __name__ == "__main__":
    main()
