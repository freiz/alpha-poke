"""The belief's truth check (doc/difftest.md: the ``belief_truth`` check): with the belief on (no
oracle), at every decision, the opponent's true set must never be ruled out.

Hard -- the evidence: its true speed must fit the observed move order (agents/speed's
``consistent``), each hit its F1 damage evidence recorded must have a likelihood above the floor
for its true item then, ability and stats (agents/damage_obs). A zero here is an inference error
(2026-10-24 review: a hit before a Trick read with the item the Trick gave).

Soft -- the prior's support: its true item, ability, tera type and unrevealed moves must have a
probability above zero in what the sampler draws from (an off-meta set -- random battles' -- can
fall outside the usage prior: counted apart, pinned by the baseline)."""

import collections

from alpha_poke.analysis.roles import to_id

HARD = ("belief:speed", "belief:damage")


def _item_support(belief, mon, team_names, known_moves) -> dict:
    """The item marginal the sampler draws from (engine_state.sample_set: the archetype's item
    weights under the posterior of its revealed moves; the team prior's marginal without
    archetypes); an Assault Vest out with a status move known."""
    from alpha_poke.agents.belief_state import _preview_name
    from alpha_poke.agents.engine_state import _prior, _status

    species = _preview_name(mon, team_names)
    dist = _prior(belief, species, team_names)
    ss = belief.sets.get(species)
    out: dict = collections.defaultdict(float)
    if ss is not None and ss.params and ss.vocab.get("item"):
        names = {to_id(n): n for n in ss.vocab["move"]}
        post = ss.posterior(item=None, moves=[names.get(m, m) for m in known_moves])
        total = float(sum(post)) or 1.0
        for k, pk in enumerate(post):
            w = ss.params["item"][k]
            s = float(sum(w)) or 1.0
            for n, x in zip(ss.vocab["item"], w, strict=False):
                out[to_id(n)] += float(pk) / total * float(x) / s
    else:
        for n, x in dist.item.items():
            out[to_id(n)] += float(x)
    if any(map(_status, known_moves)):
        out.pop("assaultvest", None)
    return out


def _move_support(belief, mon, team_names) -> set:
    from alpha_poke.agents.belief_state import _preview_name
    from alpha_poke.agents.engine_state import _prior

    species = _preview_name(mon, team_names)
    dist = _prior(belief, species, team_names)
    out = {to_id(m) for m, w in dist.move.items() if w > 0}
    ss = belief.sets.get(species)
    if ss is not None and ss.params and ss.vocab.get("move"):
        for k in range(len(ss.params["move"])):
            out |= {to_id(n) for n, w in zip(ss.vocab["move"], ss.params["move"][k], strict=False) if w > 0}
    return out


def belief_diffs(p1: str, p2: str, seed: int, max_turns: int = 40, script: list | None = None,
                 fmt: str | None = None) -> dict:
    """{"decisions", "kinds": {kind: n}, "examples": {kind: [...]}, "errors"} over a recorded
    battle's decisions, both sides' views."""
    from alpha_poke.agents.belief_state import ability_probs
    from alpha_poke.agents.damage_obs import EPS, item_changes, likelihood, slot_of
    from alpha_poke.agents.engine_state import _prior
    from alpha_poke.agents.net_context import battle_log
    from alpha_poke.agents.pokeview import own_moves
    from alpha_poke.agents.speed import battle_observations, consistent
    from alpha_poke.enginecheck.statebuild import _belief, decisions

    out: dict = {"decisions": 0, "kinds": collections.Counter(), "examples": {}, "errors": []}
    belief = _belief()
    stats: dict = {}

    reported: set = set()

    def found(kind: str, detail) -> None:
        # (a prior's gap once per battle, mon and value: it is the same at every decision)
        key = (kind, detail[2], detail[3], *detail[4:]) if kind not in HARD else None
        if key is not None:
            if key in reported:
                return
            reported.add(key)
        out["kinds"][kind] += 1
        ex = out["examples"].setdefault(kind, [])
        if len(ex) < 5:
            ex.append(detail)

    seen_hits: set = set()  # (each hit checked once: the log's hits are all the battle's so far)
    for k, side, b, _built, t in decisions(p1, p2, seed, max_turns, ("p1", "p2"), stats, False, script, fmt):
        out["decisions"] += 1
        names = tuple(belief.display(m.species) for m in (b.teampreview_opponent_team or list(b.opponent_team.values())))
        truth = {str(p.id).lower(): p for p in t.side_two.pokemon}
        obs = battle_observations(b) or {}
        hits = getattr(b, "_alpha_hits", None)
        bases = getattr(b, "_alpha_bases", {}) or {}
        changes = item_changes([m if isinstance(m, str) else "|".join(m) for m in battle_log(b)])
        them = "p2" if side == "p1" else "p1"
        for mon in b.opponent_team.values():
            sp = to_id(mon.species)
            # (poke-env keeps the species it came in as: its forme now the truth's -- a prefix)
            tm = truth.get(sp) or next((p for x, p in truth.items() if x.startswith(sp) or sp.startswith(x)), None)
            if tm is None or mon.transformed:
                continue
            item, ab = str(tm.item).lower(), str(tm.base_ability).lower()
            where = (seed, k, side, sp)
            # (the evidence: the hard checks)
            spe = tm.speed
            # (the observations carry their item phases: speed.ObsTracker.result -- the item
            # passed is the one of a mon whose item never changed)
            if obs.get(sp) and not consistent(obs[sp], spe, item):
                found("belief:speed", (*where, spe, item))
            if hits and hits[1]:
                for h in hits[1]:
                    if (h.defender if h.by_us else h.attacker) != sp or h.turn not in bases:
                        continue
                    hk = (side, sp, h.turn, h.move, h.by_us, h.before, h.after)
                    if hk in seen_hits:
                        continue
                    seen_hits.add(hk)
                    # (the candidate holds the item it started with, as F1's candidates do --
                    # likelihood puts the hit's own in for a later phase: the code under test,
                    # not around it -- a mutation check missed it so, 2026-10-24)
                    if (them, sp) in changes and changes[(them, sp)] is None and h.item_then is None:
                        continue  # (its item changed, the one it started with unknown)
                    then = changes.get((them, sp)) or item
                    try:
                        import poke_engine as pe

                        st = pe.State.from_string(bases[h.turn])
                        ours = h.attacker if h.by_us else h.defender
                        os_, ts = slot_of(st, True, ours), slot_of(st, False, sp)
                        if os_ is None or ts is None:
                            continue
                        on = h.defender_tera if h.by_us else h.tera
                        tera = on or str(tm.tera_type).lower()
                        vec = [tm.maxhp, tm.attack, tm.defense, tm.special_attack, tm.special_defense, tm.speed]
                        p = likelihood(h, bases[h.turn], os_, ts, [(then, ab, vec, tera, bool(on))])[0]
                    except BaseException as e:  # noqa: BLE001
                        out["errors"].append(f"likelihood: {type(e).__name__}: {str(e)[:100]}")
                        continue
                    if p <= EPS:
                        found("belief:damage", (*where, h.turn, h.move, h.by_us, then, h.before, h.after))
            # (the prior's support: the soft checks)
            known = list(own_moves(mon))
            if mon.item == "unknown_item" and item not in ("", "none"):
                if _item_support(belief, mon, names, known).get(item, 0.0) <= 0:
                    found("belief:item", (*where, item))
            if not mon.ability and ab and ab != "none":
                if ability_probs(mon).get(ab, 0.0) <= 0 and not any(to_id(x) == ab for x in ability_probs(mon)):
                    found("belief:ability", (*where, ab))
            if not mon.is_terastallized:
                dist = _prior(belief, mon.species, names)
                tt = str(tm.tera_type).lower()
                if tt not in ("", "typeless") and not any(to_id(x) == tt and w > 0 for x, w in dist.tera.items()):
                    found("belief:tera", (*where, tt))
            support = None
            for mv in tm.moves:
                mid = str(mv.id).lower()
                if mid in ("none", "") or mid in known:
                    continue
                support = support if support is not None else _move_support(belief, mon, names)
                if mid not in support:
                    found("belief:move", (*where, mid))
    out["errors"] += stats.get("errors", [])
    out["kinds"] = dict(out["kinds"])
    return out
