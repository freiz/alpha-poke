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
            if str(v).lower() != "none":  # a serialization artifact (doc/engine-diff.md L4)
                d[f"{k}.volatile.{str(v).lower()}"] = True
    return d, hp, mx


def kind_of(field: str) -> str:
    """Aggregation key of a field: side and mon index dropped."""
    parts = field.split(".")
    if parts[0] in ("s1", "s2"):
        parts = [p for p in parts[1:] if not p.isdigit()]
    return ".".join(parts)


def hp_fits(engine: int, actual: int, damage: int, tol: float) -> bool:
    """``actual`` within the damage rolls' spread around the engine's HP: ``damage`` is the
    engine's (average-roll) damage to that mon this turn, before any healing (a turn with Recover
    and a hit: the net change is small, the roll spread is the hit's)."""
    spread = 0.085 * max(damage, 0)  # (1 - 0.925) / 0.925 of an average roll
    return abs(actual - engine) <= spread + tol


def compare(before: str, after: str, slot1: int, slot2: int, hp_tol: float) -> dict:
    """The best-matching outcome's differences: {"discrete": {field: (engine, actual)},
    "hp": [(index, engine hp, actual hp, max hp)], "n_outcomes": n}. Chance (misses, crits,
    secondary effects, speed ties) is enumerated by the engine: matching any outcome is a match.
    Damage rolls are not: the engine deals the average roll (0.925 x max; it branches only on a
    KO and on crits), so an HP is a match within the rolls' spread around the damage the engine
    dealt that side this turn (0.85 / 0.925 .. 1 / 0.925 of it) + ``hp_tol`` x max HP. (The
    spread counted the net HP change until 2026-10-16: a turn with healing and a hit was
    flagged wrongly -- found by the dual-engine test of Roost, doc/engine-diff.md L5.)"""
    outs = alpha_search.chance_outcomes(before, slot1, slot2, True, True)
    b_snap = snapshot(before)
    actual, a_hp, a_max = snapshot(after)
    snaps = [(*snapshot(s), dmg) for _, s, _, dmg in outs]
    best = None
    for d, _, _, _ in snaps:
        keys = set(d) | set(actual)
        diff = {k: (d.get(k), actual.get(k)) for k in keys if d.get(k) != actual.get(k)}
        if best is None or len(diff) < len(best[0]):
            best = (diff, d)
    diff, d_best = best
    same = [(hp, d, dmg) for d, hp, _, dmg in snaps if d == d_best] or [
        (hp, d, dmg) for d, hp, _, dmg in snaps]  # fmt: skip
    bad_hp = []
    for i, (h, m) in enumerate(zip(a_hp, a_max, strict=True)):
        side, j = divmod(i, 6)
        k = ("s1", "s2")[side]

        def took(d: dict, dmg: list, side=side, j=j, k=k) -> int:
            # the side's damage went to its active (before the turn or after a switch)
            on = j in (b_snap[0][f"{k}.active"], d[f"{k}.active"])
            return dmg[side] if on else 0

        if not any(hp_fits(x[i], h, took(d, dmg), max(2, hp_tol * m)) for x, d, dmg in same):
            e = min((x[i] for x, _, _ in same), key=lambda v: abs(v - h))
            bad_hp.append((i, e, h, m))
    return {"discrete": diff, "hp": bad_hp, "n_outcomes": len(outs)}


PIVOT = {"uturn", "voltswitch", "flipturn", "teleport", "partingshot", "chillyreception",
         "shedtail", "batonpass"}  # fmt: skip
DRAG = {"roar", "whirlwind", "dragontail", "circlethrow"}


FRACTIONS = {"1/16": 1 / 16, "1/12": 1 / 12, "1/10": 0.1, "1/8": 1 / 8, "1/6": 1 / 6,
             "3/16": 3 / 16, "1/4": 1 / 4, "1/3": 1 / 3, "1/2": 0.5}  # fmt: skip


def hp_gap_tag(frac: float, i: int, before: str) -> str:
    """A label for an HP gap (actual - engine, share of max HP): the nearest common residual
    fraction (Leftovers 1/16, poison / Black Sludge 1/8, ...) within 1%, else "small" (< 5%) or
    "other"; prefixed by where the mon was before the turn (active / bench)."""
    side, j = divmod(i, 6)
    where = "active" if j == snapshot(before)[0][f"{('s1', 's2')[side]}.active"] else "bench"
    name, val = min(FRACTIONS.items(), key=lambda kv: abs(abs(frac) - kv[1]))
    if abs(abs(frac) - val) < 0.01:
        tag = ("+" if frac > 0 else "-") + name
    else:
        tag = "small" if abs(frac) < 0.05 else "other"
    return f"{where} {tag}"


def not_comparable(before: str, after: str, m1: str, m2: str) -> str | None:
    """Why a turn cannot be compared (None: it can): a mon fainted (the engine stops at the
    forced switch; the player's replacement, a decision not recorded when it was the only
    option, came before the next turn start), a pivot or drag move (a switch decided or drawn
    mid-turn). doc/engine-diff.md L6: 2026-10-16 these were 6% of all turns, counted as
    mismatches."""
    _, b_hp, _ = snapshot(before)
    _, a_hp, _ = snapshot(after)
    if any(b > 0 and x <= 0 for b, x in zip(b_hp, a_hp, strict=True)):
        return "faint"
    moves = {m.removesuffix("-tera") for m in (m1, m2)}
    if moves & PIVOT:
        return "pivot move"
    if moves & DRAG:
        return "drag move"
    return None


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
    skipped: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    per_move: collections.Counter = collections.Counter()
    kind_moves: dict = collections.defaultdict(collections.Counter)  # kind -> move pairs
    hp_gaps: collections.Counter = collections.Counter()
    hp_gap_moves: dict = collections.defaultdict(collections.Counter)
    hp_gap_examples: dict = collections.defaultdict(list)
    moves_seen: collections.Counter = collections.Counter()
    examples: dict = collections.defaultdict(list)
    n_games = 0
    for key, records in sampled_games(files, per_file, a.frac, a.seed):
        n_games += 1
        for t, a1, a2, b1, b2 in clean_turns(records):
            before = alpha_search.merge_sides(a1["state"], a2["state"])
            after = alpha_search.merge_sides(b1["state"], b2["state"])
            m1, m2 = a1["names"][a1["slot"]], a2["names"][a2["slot"]]
            why = not_comparable(before, after, m1, m2)
            if why:  # the engine stops at another decision point than the next turn start
                skipped[why] += 1
                continue
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
            for i, e, h, m in res["hp"]:  # HP gaps by size (a residual's fraction?)
                g = hp_gap_tag((h - e) / m, i, before)
                hp_gaps[g] += 1
                hp_gap_moves[g][f"{m1} | {m2}"] += 1
                if len(hp_gap_examples[g]) < a.examples:
                    hp_gap_examples[g].append({"game": list(key), "turn": t, "p1": m1, "p2": m2,
                                               "slots": [a1["slot"], a2["slot"]],
                                               "mon": i, "engine": e, "actual": h, "max": m,
                                               "before": before, "after": after})  # fmt: skip
            for k in found:
                kinds[k] += 1
                kind_moves[k][f"{m1} | {m2}"] += 1
                if len(examples[k]) < a.examples:
                    examples[k].append({
                        "game": list(key), "turn": t, "p1": m1, "p2": m2,
                        "slots": [a1["slot"], a2["slot"]],
                        "discrete": {f: v for f, v in res["discrete"].items()},
                        "hp": res["hp"], "before": before, "after": after})  # fmt: skip
            for m in (m1, m2):
                per_move[m] += 1
    rate = {m: round(per_move[m] / moves_seen[m], 4) for m in per_move if moves_seen[m] >= 30}
    out = {"gen": a.gen, "games": n_games, "clean_turns": n_turns, "match": n_match,
           "errors": n_err, "not_comparable": dict(skipped),
           "mismatch_kinds": kinds.most_common(),
           "mismatch_rate_by_move": sorted(rate.items(), key=lambda x: -x[1])[:60],
           "moves_by_kind": {k: c.most_common(15) for k, c in kind_moves.items()},
           "hp_gaps": hp_gaps.most_common(),
           "hp_gap_moves": {k: c.most_common(15) for k, c in hp_gap_moves.items()},
           "hp_gap_examples": hp_gap_examples,
           "examples": examples}  # fmt: skip
    path = Path("data/selfplay/diag") / f"engine_diff_gen{a.gen}.json"
    path.write_text(json.dumps(out, indent=1, default=str))
    print(
        f"{n_games} games, {n_turns} clean turns: {n_match} match "
        f"({n_match / max(n_turns, 1):.1%}), {n_err} errors -> {path}"
    )
    for k, c in kinds.most_common(30):
        print(f"  {c:6d} ({c / max(n_turns, 1):.2%})  {k}")
    print("HP gaps (where, actual - engine as a share of max HP):")
    for k, c in hp_gaps.most_common(16):
        print(f"  {c:6d}  {k:16s} {hp_gap_moves[k].most_common(4)}")


if __name__ == "__main__":
    main()
