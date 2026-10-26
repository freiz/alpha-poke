"""The engine's chained differential (doc/difftest.md: the ``engine_chain`` check): from
Showdown's true state at a turn start, poke-engine plays on along the battle's actual choices --
each turn from its own previous outcome (the closest to Showdown's next state), not from the
truth -- and from its second turn on is compared with Showdown. The one-transition differential
(stepdiff) starts every turn from the truth, so what goes wrong only past the first step -- a
state field the engine stops updating (2026-10-24: its last move, tracked only when a listed
mechanic was in the state), a value leaking into the next step (L229's saved move) -- it cannot
see; the search's tree is that chain.

After each step the HP is set to Showdown's (the engine's damage is the rolls' mean or a
branch: a drift that is no state error), and so are the volatiles whose length Showdown draws as
they start (ec.HIDDEN_LENGTH: confusion, a partial trap, a lock -- their presence and count: the
truth encodes the draw); one that started in the step has its count not compared at it (the
engine's count is its own then), its presence is (2026-10-25 review: a Confuse Ray's confusion
the engine never applied was filtered, then synced from the truth -- unseen). The rest is the
engine's own."""

import poke_engine as pe

from alpha_poke import enginecheck as ec
from alpha_poke.enginecheck.stepdiff import at_decision, comparable, follows_dealt, kind_of

_SIDE = [a for a in dir(pe.Side) if not a.startswith("_")]
_DURS = [a for a in dir(pe.VolatileStatusDurations) if not a.startswith("_")]


def _with_true_hidden(st: pe.State, truth: pe.State) -> pe.State:
    """``st`` with its actives' hidden-length volatiles (presence, count) from ``truth`` (the
    same active: else as it is)."""
    sides = []
    for a, b in ((st.side_one, truth.side_one), (st.side_two, truth.side_two)):
        kw = {x: getattr(a, x) for x in _SIDE}
        durs = {x: getattr(a.volatile_status_durations, x) for x in _DURS}
        if str(a.active_index) == str(b.active_index):
            vols = {str(v).lower() for v in a.volatile_statuses}
            want = {str(v).lower() for v in b.volatile_statuses}
            for x in ec.HIDDEN_LENGTH:
                vols.discard(x)
                if x in want:
                    vols.add(x)
                durs[x] = getattr(b.volatile_status_durations, x)
            kw["volatile_statuses"] = vols
        kw["volatile_status_durations"] = pe.VolatileStatusDurations(**durs)
        sides.append(pe.Side(**kw))
    new = pe.State(side_one=sides[0], side_two=sides[1]).to_string().split("/")[:2]
    rest = st.to_string().split("/")[2:]
    return pe.State.from_string("/".join(new + rest))


def _with_true_hp(st: pe.State, truth: pe.State) -> pe.State:
    """``st`` with every mon's HP (the state string's field 6) from ``truth`` (the same mons in
    the same order: both from Showdown's sides)."""
    a, b = st.to_string().split("/"), truth.to_string().split("/")
    for k in (0, 1):
        sa, sb = a[k].split("="), b[k].split("=")
        for i in range(6):
            fa, fb = sa[i].split(","), sb[i].split(",")
            fa[6] = fb[6]
            sa[i] = ",".join(fa)
        a[k] = "=".join(sa)
    return pe.State.from_string("/".join(a))


def _hidden_keys(start: dict, now: dict) -> set[str]:
    """The diff keys of the hidden-length volatiles' counts not there at the step's start on the
    same active (Showdown's draws; their presence is compared)."""
    out = set()
    for k, (s0, s1) in enumerate(zip(start["sides"], now["sides"], strict=True)):
        same = s0["active"] == s1["active"] and s0["active"] >= 0
        had = set(s0["mons"][s0["active"]]["volatiles"]) if same else set()
        for x in ec.HIDDEN_LENGTH:
            if x not in had:
                out.add(f"s{k + 1}.count.{x}")
    return out


def chain_diffs(steps: list[dict], depth: int = 3, every: int = 3, start=None, first: int = 1,
                rename=None, same=None) -> dict:  # fmt: skip
    """From every ``every``-th comparable turn start: up to ``depth`` turns played on by the
    engine (clean turns only: turn start to turn start, both sides choosing); the second turn's
    on compared. {"chains", "compared", "kinds": {kind: n}, "examples": {kind: [...]},
    "errors"}. ``start``: step index -> the chain's first state (None: no chain there) -- our own
    construction's (builtchain), else the truth's; ``first``: the depth compared from (0 with a
    start of our own: its first step is no other check's); ``rename``: (state, side 0 / 1, choice)
    -> the choice as that state names it, ``same``: (key, engine value, Showdown's) -> alike though
    unequal (a start of our own: its names, poke-env's)."""
    out: dict = {"chains": 0, "compared": 0, "kinds": {}, "examples": {}, "errors": []}
    starts = [k for k in range(len(steps) - 1)
              if comparable(steps, k) is None and not at_decision(steps, k)][::every]  # fmt: skip
    for k0 in starts:
        try:
            st = ec.engine_state(steps[k0]["state"]) if start is None else start(k0)
        except BaseException as e:  # noqa: BLE001
            out["errors"].append(f"start: {type(e).__name__}: {str(e)[:120]}")
            continue
        if st is None:
            continue
        out["chains"] += 1
        # (a start of our own: its legal options too, the request's -- the steps compare those after
        # each step, when the engine's own rules have set them: a Choice lock our state left out
        # was on again after the locked move; S158)
        pre = {} if start is None else ec.options_diff(st, steps[k0]["state"]["sides"], "start_options")
        k = k0
        for d in range(depth):
            if k >= len(steps) - 1 or comparable(steps, k) is not None or at_decision(steps, k):
                break
            a, b = steps[k], steps[k + 1]
            c1, c2 = ("none" if a["choices"][s]["engine"] == "struggle" else a["choices"][s]["engine"]
                      for s in ("p1", "p2"))  # fmt: skip
            if rename is not None:
                c1, c2 = rename(st, 0, c1), rename(st, 1, c2)
            n = tuple(len(s["mons"]) for s in a["state"]["sides"])
            try:
                hints = ec.move_hints(a["state"], b["state"])
                outs = ec.engine_outcomes(st, c1, c2, hints)
                dealt = (follows_dealt(a["state"], 0, c1) or c2.startswith("endeavor"),
                         follows_dealt(a["state"], 1, c2) or c1.startswith("endeavor"))  # fmt: skip
                res = (ec.end_diff(b["state"], outs, n) if b["state"]["ended"] else
                       ec.closest(b["state"], outs, n, hp=True, dealt=dealt, full=True, start=a["state"],
                                  complete=True))  # fmt: skip
            except BaseException as e:  # noqa: BLE001 - the binding's panics are BaseExceptions
                out["errors"].append(f"engine d{d}: {c1} | {c2}: {type(e).__name__}: {str(e)[:120]}")
                break
            if d >= first:
                out["compared"] += 1
                hidden = _hidden_keys(a["state"], b["state"])
                diff = {x: v for x, v in {**(pre if d == 0 else {}), **res["diff"]}.items()
                        if x not in hidden and not (same is not None and same(x, *v))}  # fmt: skip
                for kind in sorted({kind_of(x) for x in diff}):
                    out["kinds"][kind] = out["kinds"].get(kind, 0) + 1
                    ex = out["examples"].setdefault(kind, [])
                    if len(ex) < 5:
                        ex.append({"from_turn": steps[k0]["state"]["turn"], "turn": a["state"]["turn"],
                                   "depth": d, "choices": [c1, c2],
                                   "diff": {x: list(v) for x, v in diff.items() if kind_of(x) == kind}})
            if res["state"] is None:
                break
            try:
                truth = ec.engine_state(b["state"])
                st = _with_true_hidden(_with_true_hp(res["state"], truth), truth)
            except BaseException as e:  # noqa: BLE001
                out["errors"].append(f"resync: {type(e).__name__}: {str(e)[:120]}")
                break
            k += 1
    return out
