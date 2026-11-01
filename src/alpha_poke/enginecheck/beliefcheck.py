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

HARD = ("belief:speed", "belief:damage", "belief:candidates")
EXAMPLES = 5  # (examples kept per kind; an analysis may raise it)


def _item_support(belief, mon, team_names, known_moves) -> dict:
    """The item marginal the sampler draws from (engine_state.sample_set: the archetype's item
    weights under the posterior of its revealed moves; the team prior's marginal without
    archetypes); an Assault Vest out with a status move known."""
    from alpha_poke.agents.belief_state import _preview_name
    from alpha_poke.agents.engine_state import (
        _status,
        arch_mix,
        base_marginal,
        rake_factors,
        required_item,
    )

    species = _preview_name(mon, team_names)
    if required_item(mon):  # (a forme's item: the sampler's for sure)
        return {required_item(mon): 1.0}
    base = base_marginal(belief, species, team_names, "item")
    ss = belief.sets.get(species)
    out: dict = collections.defaultdict(float)
    if ss is not None and ss.params and ss.vocab.get("item"):
        names = {to_id(n): n for n in ss.vocab["move"]}
        post = ss.posterior(item=None, moves=[names.get(m, m) for m in known_moves])
        total = float(sum(post)) or 1.0
        for k, pk in enumerate(post):
            for n, x in arch_mix(ss, k, "item", base).items():
                out[n] += float(pk) / total * x
    else:
        for n, x in base.items():
            out[n] += float(x)
    if any(map(_status, known_moves)):
        out.pop("assaultvest", None)
    c = rake_factors(belief, species, "item")  # (the sampler's raked weights, if on)
    return {k: v * c.get(k, 1.0) for k, v in out.items()} if c else out


def _tera_support(belief, species: str, team_names) -> dict:
    """The tera types the sampler draws from: the base marginal, mixed into every archetype's."""
    from alpha_poke.agents.engine_state import base_marginal

    out = dict(base_marginal(belief, species, team_names, "tera"))
    ss = belief.sets.get(species)
    if ss is not None and ss.params and ss.vocab.get("tera"):
        for k in range(len(ss.params["tera"])):
            for n, w in zip(ss.vocab["tera"], ss.params["tera"][k], strict=False):
                out[to_id(n)] = out.get(to_id(n), 0.0) + float(w)
    return out


def _move_support(belief, mon, team_names) -> set:
    from alpha_poke.agents.belief_state import _preview_name
    from alpha_poke.agents.engine_state import _prior, move_weights

    species = _preview_name(mon, team_names)
    dist = _prior(belief, species, team_names)
    # (the sampler's own weights -- engine_state.move_weights, its floor too: every archetype's and
    # the prior's; 2026-10-25 review, this re-derived them and a broken floor went unseen)
    ss = belief.sets.get(species)
    ks = (
        range(len(ss.params["move"]))
        if ss is not None and ss.params and ss.vocab.get("move")
        else ()
    )
    out: set = set()
    for k in (None, *ks):
        out |= {
            to_id(m) for m, w in move_weights(ss, k, dist, to_id(mon.species), 0.0).items() if w > 0
        }
    return out


def belief_diffs(
    p1: str,
    p2: str,
    seed: int,
    max_turns: int = 40,
    script: list | None = None,
    fmt: str | None = None,
) -> dict:
    """{"decisions", "kinds": {kind: n}, "examples": {kind: [...]}, "errors"} over a recorded
    battle's decisions, both sides' views."""
    from alpha_poke.agents.belief_state import _preview_name, ability_probs
    from alpha_poke.agents.damage_obs import (
        EPS,
        _candidates,
        ability_changes,
        item_changes,
        likelihood,
        our_disguised,  # fmt: skip
        slot_of,
    )
    from alpha_poke.agents.net_context import battle_log
    from alpha_poke.agents.pokeview import own_moves
    from alpha_poke.agents.speed import abilities as species_abilities
    from alpha_poke.agents.speed import battle_observations, consistent, spe_stat
    from alpha_poke.belief.priors import legal_moves
    from alpha_poke.enginecheck import random_battle
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
        if len(ex) < EXAMPLES:
            ex.append(detail)

    seen_hits: set = set()  # (each hit checked once: the log's hits are all the battle's so far)
    # (the true sets' EVs / IVs / nature / level: a mon's speed in the forme it was in at each
    # turn -- the observations carry it, Obs.base_spe; Showdown's recording, cached)
    steps, _ = random_battle(p1, p2, f"gen5,{seed},{seed + 1},{seed + 2},{seed + 3}", seed + 1,
                             max_turns=max_turns, script=script, **({"fmt": fmt} if fmt else {}))  # fmt: skip
    true_sets = {}
    for s in steps[0]["state"]["sides"] if steps else ():
        for m in s["mons"]:
            true_sets[(s["id"], to_id(m["name"]))] = m

    def stat_of(side_id: str, sp: str):
        m = true_sets.get((side_id, sp)) or next(
            (
                v
                for (s, n), v in true_sets.items()
                if s == side_id and (sp.startswith(n) or n.startswith(sp))
            ),
            None,
        )
        if m is None:
            return None
        return lambda base: spe_stat(base, m["evs"][5], to_id(m["nature"]), m["level"], m["ivs"][5])

    for k, side, b, _built, t in decisions(
        p1, p2, seed, max_turns, ("p1", "p2"), stats, False, script, fmt
    ):
        out["decisions"] += 1
        names = tuple(
            belief.display(m.species)
            for m in (b.teampreview_opponent_team or list(b.opponent_team.values()))
        )
        truth = {str(p.id).lower(): p for p in t.side_two.pokemon}
        obs = battle_observations(b) or {}
        hits = getattr(b, "_alpha_hits", None)
        bases = getattr(b, "_alpha_bases", {}) or {}
        lines = [m if isinstance(m, str) else "|".join(m) for m in battle_log(b)]
        changes, ab_changes = item_changes(lines), ability_changes(lines)
        them = "p2" if side == "p1" else "p1"
        for mon in b.opponent_team.values():
            sp = to_id(mon.species)
            # (poke-env keeps the species it came in as: its forme now the truth's -- a prefix)
            tm = truth.get(sp) or next(
                (p for x, p in truth.items() if x.startswith(sp) or sp.startswith(x)), None
            )
            if tm is None or mon.transformed:
                continue
            item, ab = str(tm.item).lower(), str(tm.base_ability).lower()
            where = (seed, k, side, sp)
            # (the evidence: the hard checks)
            spe = tm.speed
            # (the observations carry their item phases: speed.ObsTracker.result -- the item
            # passed is the one of a mon whose item never changed)
            if obs.get(sp) and not consistent(obs[sp], spe, item, stat_of(them, sp)):
                found("belief:speed", (*where, spe, item))
            mine = [h for h in (hits[1] if hits else ()) if (h.defender if h.by_us else h.attacker) == sp
                    and h.turn in bases]  # fmt: skip
            if mine:
                # (the ability F1's candidates hold: the one it started with -- _candidates, the
                # code under test, not the truth's put in; 2026-10-25 review: a Skill Swap after the
                # hit left the candidates the Synchronize it got, the check passed with the truth's)
                cands, _ = _candidates(belief, mon, names, then=changes.get((them, sp), False),
                                       ab=ab_changes.get((them, sp), False))  # fmt: skip
                # (an illegal one is no set the belief need know: a scenario's -- a Shell Armor Rotom)
                if ab in species_abilities(mon.species) and not any(c[1] == ab for c in cands):
                    found("belief:candidates", (*where, ab, sorted({c[1] for c in cands})))
                for h in mine:
                    if (h.defender if h.by_us else h.attacker) != sp or h.turn not in bases:
                        continue
                    hk = (side, sp, h.turn, h.move, h.by_us, h.before, h.after)
                    if hk in seen_hits:
                        continue
                    seen_hits.add(hk)
                    # (the candidate holds the item it started with, as F1's candidates do --
                    # likelihood puts the hit's own in for a later phase: the code under test,
                    # not around it -- a mutation check missed it so, 2026-10-24)
                    if (
                        (them, sp) in changes
                        and changes[(them, sp)] is None
                        and h.item_then is None
                    ):
                        continue  # (its item changed, the one it started with unknown)
                    then = changes.get((them, sp)) or item
                    try:
                        import poke_engine as pe

                        st = pe.State.from_string(bases[h.turn])
                        ours = h.attacker if h.by_us else h.defender
                        os_, ts = slot_of(st, True, ours), slot_of(st, False, sp)
                        if os_ is None or ts is None or our_disguised(st, ours, b.team):
                            continue
                        on = h.defender_tera if h.by_us else h.tera
                        tera = on or str(tm.tera_type).lower()
                        vec = [
                            tm.maxhp,
                            tm.attack,
                            tm.defense,
                            tm.special_attack,
                            tm.special_defense,
                            tm.speed,
                        ]
                        p = likelihood(
                            h, bases[h.turn], os_, ts, [(then, ab, vec, tera, bool(on))]
                        )[0]
                    except BaseException as e:  # noqa: BLE001
                        out["errors"].append(f"likelihood: {type(e).__name__}: {str(e)[:100]}")
                        continue
                    if p <= EPS:
                        found(
                            "belief:damage",
                            (*where, h.turn, h.move, h.by_us, then, h.before, h.after),
                        )
            # (the prior's support: the soft checks)
            known = list(own_moves(mon))
            if mon.item == "unknown_item" and item not in ("", "none"):
                if _item_support(belief, mon, names, known).get(item, 0.0) <= 0:
                    found("belief:item", (*where, item))
            if not mon.ability and ab and ab != "none":
                if ability_probs(mon).get(ab, 0.0) <= 0 and not any(
                    to_id(x) == ab for x in ability_probs(mon)
                ):
                    found("belief:ability", (*where, ab))
            if not mon.is_terastallized:
                # (the name the sampler asks with: engine_state.sample_set's -- poke-env's id is no
                # table name, Maushold-Four's tera prior read empty; 2026-10-25)
                tera_support = _tera_support(belief, _preview_name(mon, names), names)
                tt = str(tm.tera_type).lower()
                if tt not in ("", "typeless") and tera_support.get(tt, 0.0) <= 0:
                    found("belief:tera", (*where, tt))
            support = None
            for mv in tm.moves:
                mid = str(mv.id).lower()
                if mid in ("none", "") or mid in known:
                    continue
                support = support if support is not None else _move_support(belief, mon, names)
                # (an illegal one is no set the belief need know: a scenario's hand-written --
                # Snorlax's Slack Off)
                if mid not in support and mid in legal_moves(to_id(mon.species)):
                    found("belief:move", (*where, mid))
    out["errors"] += stats.get("errors", [])
    out["kinds"] = dict(out["kinds"])
    return out
