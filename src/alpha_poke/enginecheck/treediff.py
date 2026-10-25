"""The search tree's history against the log's on a recorded battle (doc/state-diff.md plan B,
part 2; doc/difftest.md: the ``tree_history`` check). Shared by scripts/check_tree_history.py
and enginecheck/difftest.py."""

import collections

STRUCT = ("kind", "tera", "actor", "target", "prevented", "fainted_first")
OUTCOME = ("dmg", "first", "crit", "miss", "ko")
FIELDS = STRUCT + OUTCOME


def _slots(names: list[str], choice: str) -> int | None:
    choice = "none" if choice == "struggle" else choice
    for i, n in enumerate(names):  # (a switch's engine name is the species: "switch <species>")
        if n in (choice, f"switch {choice}") or (choice == "none" and n == "struggle"):
            return i
    return -1 if choice == "none" else None


def tree_diffs(p1: str, p2: str, seed: int, max_turns: int = 40, script: list | None = None,
               label: str = "") -> dict:
    """The tree's step against the log's at each turn start of a recorded battle where both
    sides chose: structural mismatches by field (examples: (label, seed, turn, choices, the
    log's step, the fields)), the outcome fields counted apart."""
    import alpha_search

    from alpha_poke.enginecheck import engine_state, random_battle
    from alpha_poke.enginecheck.statebuild import _fainted_no_status, _flip
    from alpha_poke.replay import parse_replay
    from alpha_poke.train.positions import _step_str, blind_sides, decision_steps

    stem = label
    out = {"steps": 0, "struct": collections.Counter(), "outcome": collections.Counter(),
           "examples": [], "errors": [], "skipped": collections.Counter()}  # fmt: skip
    views: dict = {}
    try:
        steps, err = random_battle(p1, p2, f"gen5,{seed},{seed + 1},{seed + 2},{seed + 3}", seed + 1,
                                   max_turns=max_turns, views=views, script=script)  # fmt: skip
        rep = parse_replay({"id": f"t{seed}", "log": "\n".join(views["spectator"])})
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"{type(e).__name__}: {e}"[:200])
        return out
    # (the recording's error and a skipped battle are kept: 2026-10-25 review, a recording that
    # failed read as no error)
    if err:
        out["errors"].append(f"showdown: {err.splitlines()[0][:200]}")
    if rep.warnings:
        out["skipped"]["parse warnings"] += 1
        return out
    log_steps = decision_steps(rep.actions, blind_sides(rep))
    # (the battle's last turn when it was won: the moves after the last knockout never come --
    # the engine plays them on; no input comes after it, in training or in the tree)
    won = any(x.startswith("|win|") for x in views["spectator"])
    last = max(log_steps, default=0) if won else None
    for k in range(len(steps) - 1):
        a = steps[k]
        if set(a.get("choices", {})) != {"p1", "p2"} or any(s["request"] != "move" for s in a["state"]["sides"]):
            continue
        turn = a["state"]["turn"]
        if turn == last:
            out["skipped"]["the last turn"] += 1
            continue
        if turn not in log_steps or not log_steps[turn]:
            out["skipped"]["no log step"] += 1
            continue
        try:
            st = engine_state(_fainted_no_status(a["state"]))
            s = st.to_string()
            n1 = alpha_search.slot_names([s])[0]
            n2 = alpha_search.slot_names([_flip(st).to_string()])[0]
            c1, c2 = a["choices"]["p1"]["engine"], a["choices"]["p2"]["engine"]
            i1, i2 = _slots(n1, c1), _slots(n2, c2)
            if i1 is None or i2 is None:
                out["skipped"]["choice not a slot"] += 1
                continue
            logged = _step_str(log_steps[turn][0], "p1")
            tree, (l1, l2) = alpha_search.tree_steps(s, i1, i2, logged)
        except BaseException as e:  # noqa: BLE001 - the binding's panics are BaseExceptions
            out["errors"].append(f"{type(e).__name__}: {str(e)[:150]}")
            continue
        out["steps"] += 1
        log = dict(zip(FIELDS, l1, strict=True)), dict(zip(FIELDS, l2, strict=True))
        best = None
        for _, t1, t2, _, _ in tree:
            t = dict(zip(FIELDS, t1, strict=True)), dict(zip(FIELDS, t2, strict=True))
            miss = [f"{sd}.{f}" for sd, x, y in (("one", log[0], t[0]), ("two", log[1], t[1]))
                    for f in STRUCT if x[f] != y[f]]  # fmt: skip
            if best is None or len(miss) < len(best[0]):
                best = (miss, t)
        miss, t = best if best else (["no outcome"], ({}, {}))
        for m in miss:
            out["struct"][m] += 1
        if miss and len(out["examples"]) < 10:
            out["examples"].append((stem, seed, turn, c1, c2, logged, miss))
        for sd, x, y in (("one", log[0], t[0]), ("two", log[1], t[1])):
            for f in OUTCOME:
                if y and x[f] != y[f]:
                    out["outcome"][f"{sd}.{f}"] += 1
    return out


