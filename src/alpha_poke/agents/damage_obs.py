"""F1 (design TODO 特征候选): the opponent's sets from the damage its mons dealt and took.

Like the speed inference (agents/speed.py) this is evidence the belief samples against, at play
time (training positions sample the belief without it): a likelihood over candidate sets
(item, ability, spread), not a hard filter.

  hits(lines, our_side)         the clean hits of the protocol log: the first move of a turn,
                                one hit, no crit, no Substitute, nothing before it in the turn but
                                switches and their entry hazards (the turn-start state holds then);
                                theirs on ours (our exact HP) and ours on theirs (their percent)
  likelihood(hit, base, cands)  per candidate set of their mon, P(the observed HP | the set): the
                                engine's 16 non-crit rolls (alpha_search.set_damage_rolls) in the
                                turn-start state ``base``; their percent as Showdown shows it
                                (ceil, 99 below full)
  posterior(...)                the candidates' prior x likelihoods, floored at EPS x prior (a
                                set the engine or the parse gets wrong is not excluded), normalized

The evidence is limited: their HP is a percent; a KO shows only that the damage reached the HP
left; attack and bulk investments and items can trade off; a hit before a Terastallization says
nothing of the tera type.
"""

import math
import re
from dataclasses import dataclass

import alpha_search

from alpha_poke.analysis.roles import to_id

EPS = 1e-3  # the likelihood floor (x prior): no candidate is ever excluded outright
# a turn's lines before its first move that keep the turn-start state (others: the hit is skipped)
_QUIET = ("switch", "drag", "-damage", "-heal", "detailschange", "-terastallize", "j", "c", "l",
          "raw", "", "t:", "upkeep", "-hint", "-message", "-ability")  # fmt: skip
# moves whose damage line is not one roll of one hit (Dragon Darts' two hits show no -hitcount)
_SKIP_MOVES = {"dragondarts", "beatup", "populationbomb", "tripleaxel", "triplekick", "surgingstrikes"}
# after the move line, these void the hit as evidence
_VOID = ("-crit", "-hitcount", "-immune", "-miss", "-fail", "-activate", "-enditem", "cant")


@dataclass
class Hit:
    turn: int
    by_us: bool  # our active hit theirs (else theirs hit ours)
    move: str  # move id
    attacker: str  # species id of the attacker
    defender: str  # species id of the defender
    before: int  # the defender's HP before (ours exact; theirs percent)
    after: int  # after (0 = fainted)
    tera: str | None = None  # the attacker's tera type if it terastallized this turn or earlier
    defender_tera: str | None = None
    # their mon's item was gone at the hit (knocked off, eaten, popped: -enditem): it held none
    item_gone: bool = False


def _side(ident: str) -> str:
    return ident[:2]


def _hp(cond: str) -> int:
    """'123/300 brn' -> 123; '0 fnt' -> 0"""
    cond = cond.split()[0] if cond else "0"
    return int(cond.split("/")[0]) if "/" in cond else 0


def _species(details: str) -> str:
    return to_id(details.split(",")[0])


def hits(lines: list[str], our_side: str) -> list[Hit]:
    """The clean hits of a battle's log (the player's own view: its HP exact)."""
    out: list[Hit] = []
    active: dict[str, str] = {}  # "p1a" -> species id
    hp: dict[tuple[str, str], int] = {}  # (side, species) -> HP (ours exact, theirs percent)
    tera: dict[tuple[str, str], str] = {}
    gone: set[tuple[str, str]] = set()  # items used up / removed
    changed: set[tuple[str, str]] = set()  # items swapped in (Trick, ...): no evidence of them
    turn, quiet, seen_move = 0, True, False
    pending: dict | None = None
    recent = False  # the last hit can still be voided (a multi-hit's count, a Sash / Sturdy save)
    for line in lines:
        f = line.split("|")
        if len(f) < 2:
            continue
        tag = f[1]
        if recent:
            if tag in ("move", "turn"):
                recent = False
            elif tag == "-hitcount" or (tag in ("-enditem", "-activate") and len(f) > 3 and any(
                    k in f[3] for k in ("Focus Sash", "Sturdy", "Endure", "Focus Band"))):  # fmt: skip
                out.pop()
                recent = False
        if pending is not None and tag != "-damage":
            if tag in _VOID or tag == "move" or tag == "turn":
                pending = None
            elif tag in ("-supereffective", "-resisted"):
                pass
            else:  # anything else between the move and its damage line: skip (unknown effect)
                pending = None
        if tag == "turn":
            turn, quiet, seen_move = int(f[2]), True, False
            continue
        if tag in ("switch", "drag") and len(f) > 4:
            slot = f[2][:3]
            sp = _species(f[3])
            active[slot] = sp
            hp[(slot[:2], sp)] = _hp(f[4])
        elif tag in ("-damage", "-heal") and len(f) > 3:
            slot = f[2][:3]
            sp = active.get(slot)
            new = _hp(f[3])
            if pending is not None and tag == "-damage" and len(f) == 4 and slot == pending["def"]:
                if pending["key"] not in changed:
                    out.append(Hit(turn, pending["by_us"], pending["move"], pending["att"], sp,
                                   pending["before"], new, pending["tera"], pending["dtera"],
                                   pending["key"] in gone))  # fmt: skip
                    recent = True
                pending = None
            if sp is not None:
                hp[(slot[:2], sp)] = new
        elif tag in ("-enditem", "-item") and len(f) > 2:
            slot = f[2][:3]
            if active.get(slot):
                (gone if tag == "-enditem" else changed).add((slot[:2], active[slot]))
        elif tag == "-terastallize" and len(f) > 3:
            slot = f[2][:3]
            if active.get(slot):
                tera[(slot[:2], active[slot])] = to_id(f[3])
        elif tag == "move" and len(f) > 4:
            first = not seen_move
            seen_move = True
            att, dfn = f[2][:3], f[4][:3]
            if (not (first and quiet) or not dfn or _side(att) == _side(dfn) or "[" in line
                    or to_id(f[3]) in _SKIP_MOVES):  # fmt: skip
                continue  # (a called / reflected / still move: "[from]", "[still]", ...)
            a_sp, d_sp = active.get(att), active.get(dfn)
            if a_sp is None or d_sp is None or (dfn[:2], d_sp) not in hp:
                continue
            theirs = (dfn[:2], d_sp) if att[:2] == our_side else (att[:2], a_sp)
            pending = {"by_us": att[:2] == our_side, "move": to_id(f[3]), "att": a_sp,
                       "def": dfn, "before": hp[(dfn[:2], d_sp)],
                       "tera": tera.get((att[:2], a_sp)), "dtera": tera.get((dfn[:2], d_sp)),
                       "key": theirs}  # fmt: skip
            continue
        if not seen_move and tag not in _QUIET:
            quiet = False
    return out


def _shown(hp: int, maxhp: int) -> int:
    """Showdown's percent (HP Percentage Mod): ceil, 99 below full; 0 fainted."""
    if hp <= 0:
        return 0
    p = math.ceil(100 * hp / maxhp)
    return 99 if p == 100 and hp < maxhp else p


def _with_hp(base: str, side_one: bool, slot: int, hp: int | None = None,
             pct: int | None = None) -> str:
    """``base`` with one mon's HP set: ``hp`` exact, or ``pct`` percent of its max HP (the state
    string's mon fields: HP at index 6, max HP at 7)."""
    parts = base.split("/")
    k = 0 if side_one else 1
    segs = parts[k].split("=")
    f = segs[slot].split(",")
    maxhp = int(f[7])
    if hp is None:
        hp = maxhp if pct >= 100 else max(1, min(maxhp - 1, round(pct * maxhp / 100)))
    f[6] = str(max(1, min(maxhp, hp)))
    segs[slot] = ",".join(f)
    parts[k] = "=".join(segs)
    return "/".join(parts)


def likelihood(hit: Hit, base: str, our_slot: int, their_slot: int, cands: list[tuple]) -> list[float]:
    """P(the observed HP | candidate) per candidate (item, ability, stats [6], tera, on): the
    16 non-crit rolls in the turn-start state ``base`` (side one = us), the defender at its HP
    before the hit (a switch-in after its hazards: Multiscale / Shadow Shield need full HP)."""
    own_tera = bool(hit.tera if hit.by_us else hit.defender_tera)  # our mon terastallized
    if hit.item_gone:  # it held nothing at the hit, whatever it started with
        cands = [("none", *c[1:]) for c in cands]
    if hit.before > 0:
        base = (_with_hp(base, False, their_slot, pct=hit.before) if hit.by_us
                else _with_hp(base, True, our_slot, hp=hit.before))  # fmt: skip
    rolls = alpha_search.set_damage_rolls(base, hit.by_us, hit.move, our_slot, their_slot, cands,
                                          own_tera)  # fmt: skip
    out = []
    for c, r in zip(cands, rolls, strict=True):
        if not r:
            out.append(1.0)  # no / fixed damage: no evidence
            continue
        if not hit.by_us:  # theirs on ours: our HP exact
            if hit.after > 0:
                out.append(sum(x == hit.before - hit.after for x in r) / len(r))
            else:
                out.append(sum(x >= hit.before for x in r) / len(r))
            continue
        maxhp = c[2][0]
        # their HP before: every value Showdown shows as ``before`` percent
        befores = [maxhp] if hit.before >= 100 else [
            h for h in range(1, maxhp + 1) if _shown(h, maxhp) == hit.before]  # fmt: skip
        if not befores:
            out.append(0.0)
            continue
        p = 0.0
        for h in befores:
            p += sum(_shown(max(0, h - x), maxhp) == hit.after if hit.after > 0 else x >= h
                     for x in r) / len(r)  # fmt: skip
        out.append(p / len(befores))
    return out


_SLOT = re.compile(r"[^A-Z0-9]")


def slot_of(state, side_one: bool, species: str) -> int | None:
    """The team index of a species in a poke_engine.State side (engine ids, upper case)."""
    side = state.side_one if side_one else state.side_two
    want = _SLOT.sub("", species.upper())
    for i, p in enumerate(side.pokemon):
        if _SLOT.sub("", str(p.id).upper()) == want:
            return i
    return None


def posterior(prior: list[float], likes: list[list[float]]) -> list[float]:
    """prior x the likelihoods of every hit, each floored at EPS (no exclusion), normalized."""
    w = list(prior)
    for lk in likes:
        w = [x * max(p, EPS) for x, p in zip(w, lk, strict=True)]
    s = sum(w)
    return [x / s for x in w] if s > 0 else list(prior)


TOP_ITEMS = 8  # the belief's most likely items per mon (+ a revealed one)
TOP_SPREADS = 12


def _candidates(belief, mon, team_names: tuple[str, ...]) -> tuple[list, list[float]]:
    """(item, ability, Spread) candidates of an opposing mon and their prior: the belief's team-
    conditioned item marginal (a revealed item alone), the usage of its possible abilities (a
    revealed one alone), the usage spreads. The item is the one it held when it hit / was hit:
    a gone item counts as unknown here."""
    from alpha_poke.agents.belief_state import _preview_name, ability_probs
    from alpha_poke.agents.engine_state import _prior
    from alpha_poke.agents.speed import spread_dist

    dist = _prior(belief, _preview_name(mon, team_names), team_names)
    if mon.item and mon.item != "unknown_item":
        items = [(mon.item, 1.0)]
    else:
        items = sorted(dist.item.items(), key=lambda kv: -kv[1])[:TOP_ITEMS] or [("none", 1.0)]
    abilities = list(ability_probs(mon).items()) or [("none", 1.0)]
    spreads, ws = spread_dist(mon.species)
    if not spreads:
        spreads, ws = (belief.spread_for(mon.species),), (1.0,)
    spreads, ws = spreads[:TOP_SPREADS], ws[:TOP_SPREADS]
    cands, prior = [], []
    for it, pi in items:
        for ab, pa in abilities:
            for sp, w in zip(spreads, ws, strict=True):
                cands.append((to_id(it), to_id(ab), sp))
                prior.append(pi * pa * (w if sum(ws) > 0 else 1.0))
    return cands, prior


def damage_posteriors(battle, belief, theirs: list, team_names: tuple[str, ...]) -> dict:
    """Per opposing species id with clean hits: [(item, ability, Spread, posterior weight)] over
    its candidates (``_candidates``), from the turn-start states the search recorded
    (``record_base``). Cached per mon and evidence."""
    from alpha_poke.agents.damage import calc_stats
    from alpha_poke.agents.net_context import battle_log

    import poke_engine as pe

    bases = getattr(battle, "_alpha_bases", None)
    if not bases:
        return {}
    role = battle.player_role or "p1"
    # (poke-env's messages, split at "|")
    lines = [m if isinstance(m, str) else "|".join(m) for m in battle_log(battle)]
    parsed_log = getattr(battle, "_alpha_hits", None)  # (lines seen, hits): once per new message
    if parsed_log is None or parsed_log[0] != len(lines):
        parsed_log = (len(lines), hits(lines, role))
        battle._alpha_hits = parsed_log
    hs = [h for h in parsed_log[1] if h.turn in bases]
    if not hs:
        return {}
    cache = getattr(battle, "_alpha_dmg_post", None)
    if cache is None:
        cache = {}
        battle._alpha_dmg_post = cache
    parsed: dict[int, object] = {}
    out = {}
    for m in theirs:
        sp = to_id(m.species)
        mh = [h for h in hs if (h.defender if h.by_us else h.attacker) == sp]
        if not mh:
            continue
        key = (sp, len(mh), m.item, m.ability)
        if key not in cache:
            cands, prior = _candidates(belief, m, team_names)
            level = m.level or 100
            stats = [calc_stats(m.base_stats, c[2], level=level) for c in cands]
            vec = [[s["hp"], s["atk"], s["def"], s["spa"], s["spd"], s["spe"]] for s in stats]
            likes = []
            for h in mh:
                base = bases[h.turn]
                st = parsed.get(h.turn)
                if st is None:
                    st = parsed[h.turn] = pe.State.from_string(base)
                ours = h.attacker if h.by_us else h.defender
                os_, ts = slot_of(st, True, ours), slot_of(st, False, sp)
                if os_ is None or ts is None:
                    continue
                on = h.defender_tera if h.by_us else h.tera  # their mon terastallized at the hit
                tera = on or (m.tera_type.name.lower() if m.tera_type else "typeless")
                try:
                    likes.append(likelihood(h, base, os_, ts, [(c[0], c[1], v, tera, bool(on))
                                                               for c, v in zip(cands, vec)]))  # fmt: skip
                except BaseException:  # noqa: BLE001 - an engine panic: no evidence from it
                    continue
            post = posterior(prior, likes)
            cache[key] = [(c[0], c[1], c[2], p) for c, p in zip(cands, post, strict=True)]
        out[sp] = cache[key]
    return out


def record_base(battle, state_string: str) -> None:
    """Keep the turn's first built world (side one = us) as its turn-start state: the base of the
    damage likelihood for the hits of that turn."""
    bases = getattr(battle, "_alpha_bases", None)
    if bases is None:
        bases = {}
        battle._alpha_bases = bases
    bases.setdefault(battle.turn, state_string)
