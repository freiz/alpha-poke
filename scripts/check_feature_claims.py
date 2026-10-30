"""The network inputs' claims against the engine's transitions on real states (doc/engine-diff.md
L230; rust/alpha_search extra.rs EXTRA_VERSION 3). The engine agrees with Showdown on every turn
of the differential sets; a feature that states an outcome must agree with the engine playing it
out under the feature's own assumptions -- no chance crit, no miss (poke_engine.set_no_chance),
the target doing nothing (ko2, the one-hit KO flags) or both using one fixed move (team). The
damage rolls, hit counts, Focus Sash, abilities, items and the end of the turn are the engine's.
(Not checked here: ko2's priority-KO columns -- the moves' priorities are not in the binding.)

Claims, per view (both sides of each state), each true / false claim checked against the share of
the transitions' probability where it holds:

  ko1      the own active's move KOs the foe's active with one use: for sure (all of it) /
           possibly (some of it)
  first    who moves first between the actives (priority-0 damaging moves): own / foe / a tie
  ko2      KO within two uses (the end of the turn between): for sure / possibly
  team     an own mon against the foe's active (its fixed move each, extra.rs duels): as a
           switch-in (reliably: every outcome won within the rounds; possibly: some), head-to-head
           (the actives, reliably), as a revenge kill (reliably: it moves first and KOs)

A false 'for sure' / 'reliably' that the transitions always meet is reported as conservative, not
as wrong (the features' rolls are 85-100% of the max per hit; the engine's KO branching is exact,
its other rolls averaged).

  uv run python scripts/check_feature_claims.py --states <engine state strings, one per line>

Report: data/selfplay/diag/feature_claims.json (per claim: checked, wrong, conservative,
examples) and a summary on stdout."""

import argparse
import collections
import json
import multiprocessing as mp
from pathlib import Path

import numpy as np

ROUNDS = 4  # (extra.rs ROUNDS)
# the pivots: their user goes out after one use (no second use / exchange to check)
PIVOTS = {"uturn", "voltswitch", "flipturn", "partingshot", "teleport", "chillyreception",
          "shedtail", "batonpass"}  # fmt: skip
NEEDS_FOE_MOVE = {"suckerpunch", "thunderclap", "upperhand", "focuspunch", "counter", "mirrorcoat",
                  "metalburst", "comeuppance", "bide"}  # fmt: skip
PLAIN: set[str] = set()  # damaging moves of priority 0 that no ability / terrain changes (_init)
MIN_P = 1e-4  # a branch below this probability is dropped (counted as unresolved)


def _init():
    import alpha_search as A
    import poke_engine as pe

    pe.set_no_chance(True)
    # the engine's move data: name, type, accuracy, category, power, priority, ..., flags
    PLAIN.clear()
    for row in A.engine_data()[0]:
        name, cat, power, prio, flags = row[0].lower(), row[3], float(row[4]), int(row[5]), row[-1]
        if (
            cat != "Status"
            and power > 0
            and prio == 0
            and "heal" not in flags
            and name != "grassyglide"
        ):
            PLAIN.add(name)


def _dims():
    import alpha_search as A

    d = A.feature_dims()
    return d["ent_extra"], d["ent_new"], d["ent_ko2"] + d["ent_tera"]


def _turn(pe, st, own_one: bool, mine: str, theirs: str):
    """The transitions of a turn: [(p, state)] (own / foe choices in the view's order)."""
    c1, c2 = (mine, theirs) if own_one else (theirs, mine)
    return [
        (o.percentage / 100, st.apply_instructions(o)) for o in pe.generate_instructions(st, c1, c2)
    ]


def _sides(st, own_one: bool):
    return (st.side_one, st.side_two) if own_one else (st.side_two, st.side_one)


def _active(side):
    return side.pokemon[int(side.active_index)]


def _legal(pe, st, own_one: bool):
    a, b = pe.options(st)
    return (set(a), set(b)) if own_one else (set(b), set(a))


def _move_name(p, slot: int) -> str:
    return str(p.moves[slot].id).lower()


def _status_on(o, side: str) -> bool:
    """A status the turn put on ``side``'s mon (a move's secondary effect: not in the claims)."""
    return any(str(i).startswith(f"ChangeStatus {side}") for i in o.instruction_list)


def _turn_clean(pe, st, own_one: bool, mine: str, theirs: str):
    """`_turn` without the branches that put a status on the foe (renormalized); [] if none is
    left."""
    foe = "SideTwo" if own_one else "SideOne"
    c1, c2 = (mine, theirs) if own_one else (theirs, mine)
    ins = [o for o in pe.generate_instructions(st, c1, c2) if not _status_on(o, foe)]
    tot = sum(o.percentage for o in ins)
    return [(o.percentage / tot, st.apply_instructions(o)) for o in ins] if tot > 0 else []


def _first_acted(o) -> str | None:
    for ins in o.instruction_list:
        t = str(ins)
        if t.startswith("Acted: "):
            return t.split(": ")[1].strip()
    return None


def check_state(line: str) -> list[dict]:
    import alpha_search as A
    import poke_engine as pe

    EE, EN, TEAM = _dims()
    out = []
    st = pe.State.from_string(line)
    if st.side_one.force_switch or st.side_two.force_switch:
        return out
    for flip in (False, True):
        own_one = not flip
        e, g, n = A.featurize_extra_full([line], flip)
        ent = np.frombuffer(e, "<f4").reshape(12, EE)
        glob = np.frombuffer(g, "<f4")
        new = np.frombuffer(n, "<f4").reshape(12, EN)
        me, foe = _sides(st, own_one)
        a, b = int(me.active_index), int(foe.active_index)
        pa, pb = me.pokemon[a], foe.pokemon[b]
        if pa.hp <= 0 or pb.hp <= 0:
            continue
        legal_me, legal_foe = _legal(pe, st, own_one)

        def rec(kind, claim, p, ctx, unknown=False):
            out.append({"kind": kind, "claim": bool(claim), "p": p, "ctx": ctx, "unknown": unknown})

        def mech(*mons):
            """the mons' abilities and items (the breakdown of the wrong / missed ones)"""
            return [f"{str(m.ability).lower()}" for m in mons] + [
                f"{str(m.item).lower()}" for m in mons
            ]

        def foe_hp(s2, own_one=own_one, b=b):
            return _sides(s2, own_one)[1].pokemon[b].hp

        # (the KO checks need the foe's HP to change by the hits only: none where the end of the
        # turn takes HP from it -- burn, poison, Leech Seed, the weather, ...; the claims include
        # the end of the turn between two hits, not after the last)
        eot_loss = any(foe_hp(s2) < pb.hp for _, s2 in _turn(pe, st, own_one, "none", "none"))
        for i in range(4 if not eot_loss else 0):
            mv = _move_name(pa, i)
            # (the moves that need the target to act: the claims assume they work, the check's
            # target does nothing)
            if mv not in legal_me or ent[a, 4 + 4 * i] <= 0 or mv in NEEDS_FOE_MOVE:
                continue
            outs = _turn_clean(pe, st, own_one, mv, "none")
            if not outs:
                continue
            p1 = sum(p for p, s2 in outs if foe_hp(s2) <= 0)
            ctx = {"move": mv, "flip": flip, "mech": mech(pa, pb)}
            rec("ko1_sure", ent[a, 4 + 4 * i + 1], p1, ctx)
            rec("ko1_possible", ent[a, 4 + 4 * i + 2], p1, ctx)
            # two uses, the target doing nothing (the end of the turn between)
            p2, lost = 0.0, 0.0
            for p, s2 in outs:
                if foe_hp(s2) <= 0:
                    p2 += p
                    continue
                m2, f2 = _sides(s2, own_one)
                if m2.force_switch or f2.force_switch or _active(m2).hp <= 0:
                    lost += p
                    continue
                if mv not in _legal(pe, s2, own_one)[0]:
                    lost += p
                    continue
                p2 += p * sum(
                    q for q, s3 in _turn_clean(pe, s2, own_one, mv, "none") if foe_hp(s3) <= 0
                )
            if lost < 1e-6 and mv not in PIVOTS:
                rec("ko2_sure", new[a, 2 * i], p2, ctx)
                rec("ko2_possible", new[a, 2 * i + 1], p2, ctx)

        # who moves first: a priority-0 damaging move each (none whose priority an ability or the
        # terrain changes)
        def plain(p, legal):
            for k in range(4):
                name = str(p.moves[k].id).lower()
                if name in legal and name in PLAIN:
                    yield name

        mine = next(iter(plain(pa, legal_me)), None)
        theirs = next(iter(plain(pb, legal_foe)), None)
        if mine and theirs:
            c1, c2 = (mine, theirs) if own_one else (theirs, mine)
            ins = pe.generate_instructions(st, c1, c2)
            own_name = "SideOne" if own_one else "SideTwo"
            p_own = sum(o.percentage / 100 for o in ins if _first_acted(o) == own_name)
            claim = glob[16]
            out.append({"kind": "first", "claim": float(claim), "p": p_own,
                        "ctx": {"moves": [mine, theirs], "flip": flip}})  # fmt: skip
        # team: the own mons against the foe's active, by the transitions
        names_me = {j: str(me.pokemon[j].id).lower() for j in range(6)}
        for s_, j, k, mj, mk, res in A.duels_debug(line, flip):
            if s_ != 0 or k != b or mj < 0:
                continue
            res = list(res)
            mjn = _move_name(me.pokemon[j], mj)
            mkn = _move_name(pb, mk) if mk >= 0 else "none"
            pj = me.pokemon[j]
            ctx = {"mon": names_me[j], "moves": [mjn, mkn], "flip": flip, "mech": mech(pj, pb)}
            if j == a:
                p_win, unres = _exchange(pe, st, own_one, a, b, None, mjn, mkn, "h2h")
                if unres < 1e-3:
                    rec("team_head_to_head", res[2] == 0, p_win, ctx, res[2] == 2)
                continue
            if f"switch {names_me[j]}" not in legal_me:
                continue
            sw = names_me[j]  # (a switch: the mon's name in generate_instructions)
            p_win, unres = _exchange(pe, st, own_one, j, b, sw, mjn, mkn, "switch")
            if unres < 1e-3:
                rec("team_switch_in", res[0] == 0, p_win, ctx, res[0] == 2)
                rec("team_switch_in_possible", res[1] == 0, p_win, ctx, res[1] == 2)
            p_win, unres = _exchange(pe, st, own_one, j, b, sw, mjn, mkn, "revenge")
            if unres < 1e-3:
                rec("team_revenge", res[3] == 0, p_win, ctx, res[3] == 2)
    return out


def _exchange(pe, st, own_one, j, b, switch, mj, mk, mode):
    """(P(the own mon j wins), the probability left unresolved) of the exchange playing out in
    the engine: 'switch' -- j switches in taking the foe's move, then ROUNDS rounds; 'h2h' --
    ROUNDS rounds; 'revenge' -- j comes in (the foe doing nothing), then wins if its first
    move KOs before the foe acts."""

    def hp(s, own):
        side = _sides(s, own_one)[0 if own else 1]
        return side.pokemon[j if own else b].hp

    def left(s):
        """A side switching out with its mon still up (U-turn, an Eject Button, ...): outside the
        claims' 'nobody switches'"""
        m, f = _sides(s, own_one)
        return (m.force_switch and hp(s, True) > 0) or (f.force_switch and hp(s, False) > 0)

    frontier = [(1.0, st)]
    win, unres = 0.0, 0.0
    if switch:
        first = _turn(pe, st, own_one, switch, "none" if mode == "revenge" else mk)
        frontier = []
        for p, s2 in first:
            if hp(s2, True) <= 0:
                continue
            if left(s2):
                unres += p
                continue
            if hp(s2, False) <= 0:
                win += p if mode != "revenge" else 0.0
                continue
            frontier.append((p, s2))
    if mode == "revenge":
        for p, s2 in frontier:
            c1, c2 = (mj, mk) if own_one else (mk, mj)
            try:
                ins = pe.generate_instructions(s2, c1, c2)
            except ValueError:
                unres += p
                continue
            own_name = "SideOne" if own_one else "SideTwo"
            for o in ins:
                s3 = s2.apply_instructions(o)
                if _first_acted(o) == own_name and hp(s3, False) <= 0:
                    win += p * o.percentage / 100
        return win, unres
    for _ in range(ROUNDS):
        nxt = []
        for p, s2 in frontier:
            try:
                outs = _turn(pe, s2, own_one, mj, mk)
            except ValueError:
                unres += p
                continue
            for q, s3 in outs:
                pq = p * q
                if hp(s3, True) <= 0:
                    continue
                if hp(s3, False) > 0 and left(s3):
                    unres += pq
                    continue
                if hp(s3, False) <= 0:
                    win += pq
                elif pq >= MIN_P:
                    nxt.append((pq, s3))
                else:
                    unres += pq
        frontier = nxt
    # (still going after the rounds: neither a win nor unresolved -- the claim's 'unknown')
    return win, unres


def verdict(r: dict) -> str:
    """'ok'; 'wrong' (a claim the transitions break); 'missed' (a false 'sure' the transitions
    always meet: a lower bound kept, but an answer the counts miss); 'unknown' (the features gave
    no outcome: a mechanic the exchange does not follow, or past its rounds); 'unverifiable': a
    'possibly' over several hits that no transition meets -- the engine branches a hit on whether
    it KOs (its rolls exactly), a hit that does not KO is its rolls' mean, so a KO by two high
    rolls has no branch."""
    k, c, p = r["kind"], r["claim"], r["p"]
    if r.get("unknown"):
        return "unknown"
    if k == "first":
        if c > 0:
            return "ok" if p > 0.999 else "wrong"
        if c < 0:
            return "ok" if p < 0.001 else "wrong"
        return "ok" if 0.001 < p < 0.999 else "wrong"
    sure = k.endswith("_sure") or k in ("team_switch_in", "team_head_to_head", "team_revenge")
    if sure:
        if c:
            return "ok" if p > 0.999 else "wrong"
        return "missed" if p > 0.999 else "ok"
    # 'possibly'
    if c:
        if p > 0.0:
            return "ok"
        return "unverifiable" if k in ("ko2_possible", "team_switch_in_possible") else "wrong"
    return "ok" if p < 1e-6 else "wrong"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--out", default="data/selfplay/diag/feature_claims.json")
    a = ap.parse_args()
    lines = [
        x.strip() for x in Path(a.states).read_text(encoding="utf-8").splitlines() if x.strip()
    ]
    if a.limit:
        lines = lines[: a.limit]
    stats = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    # the moves / abilities / items of the wrong and missed ones (with each one's checked count)
    blame = collections.defaultdict(collections.Counter)
    seen = collections.defaultdict(collections.Counter)
    errors = 0
    with mp.Pool(a.procs, initializer=_init) as pool:
        for res in pool.imap_unordered(_safe, lines, chunksize=4):
            if res is None:
                errors += 1
                continue
            line, rows = res
            for r in rows:
                v = verdict(r)
                stats[r["kind"]][v] += 1
                keys = [f"move:{m}" for m in r["ctx"].get("moves") or [r["ctx"].get("move")] if m]
                keys += r["ctx"].get("mech", [])
                for key in set(keys):
                    seen[r["kind"]][key] += 1
                    if v in ("wrong", "missed"):
                        blame[(r["kind"], v)][key] += 1
                if v != "ok" and len(examples[(r["kind"], v)]) < 20:
                    examples[(r["kind"], v)].append({**r, "state": line})
    # a mechanism's share of the wrong / missed ones over its share of the checked ones
    breakdown = {}
    for (k, v), c in blame.items():
        n = sum(stats[k].values())
        breakdown[f"{k}/{v}"] = [
            {"key": key, "count": x, "rate": round(x / seen[k][key], 4), "checked": seen[k][key]}
            for key, x in c.most_common(25)
            if seen[k][key] >= 5 and key not in ("none", "move:none")
        ][:15]
        del n
    report = {"states": len(lines), "errors": errors,
              "claims": {k: dict(c) for k, c in sorted(stats.items())},
              "breakdown": breakdown,
              "examples": {f"{k}/{v}": x for (k, v), x in examples.items()}}  # fmt: skip
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{len(lines)} states ({errors} errors) -> {a.out}")
    for k, c in sorted(stats.items()):
        n = sum(c.values())
        print(f"  {k:24s} {n:6d} checked  wrong {c['wrong'] / n:6.2%}  missed {c['missed'] / n:6.2%}"
              f"  unknown {c['unknown'] / n:6.2%}  unverifiable {c['unverifiable']:5d}")  # fmt: skip
    for key, rows in sorted(breakdown.items()):
        top = ", ".join(f"{r['key']} {r['count']}/{r['checked']}" for r in rows[:6])
        print(f"    {key}: {top}")


def _safe(line: str):
    try:
        return line, check_state(line)
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    main()
