"""F1 (design: feature candidates): the opponent's sets from the damage its mons dealt and took.

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
_SKIP_MOVES = {
    "dragondarts",
    "beatup",
    "populationbomb",
    "tripleaxel",
    "triplekick",
    "surgingstrikes",
}
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
    # their mon's item at the hit when the log names it (after its first change: an -enditem's
    # "none", a Trick's / Thief's / Magician's / Harvest's item); None: the one it started with
    # (the candidates' item -- 2026-10-24 review: one item for every hit read a Choice Specs hit
    # before a Knock Off and a Magician Assault Vest as itemless)
    item_then: str | None = None
    # (their mon's forme at the hit: a hit in another forme than its last is left out -- the
    # candidates' stats are the forme's now; 2026-10-24, the belief check: a Palafin-Zero's hit)
    forme: str = ""
    # their mon's ability at the hit when the log changed it (``_Abilities``: a Skill Swap's, a
    # Mummy's, a Gastro Acid's "none"); None: the one it started with (the candidates')
    ability_then: str | None = None
    # our HP shown in percent too: a replay's (a spectator's log -- a review with the team pasted;
    # 2026-10-30 review: its 100/100 -> 76/100 was read as 24 HP lost, every candidate's
    # likelihood 0, and the full HP set to 100 of 371)
    pct: bool = False


def _side(ident: str) -> str:
    return ident[:2]


def _hp(cond: str) -> int:
    """'123/300 brn' -> 123; '0 fnt' -> 0"""
    cond = cond.split()[0] if cond else "0"
    return int(cond.split("/")[0]) if "/" in cond else 0


def _species(details: str) -> str:
    return to_id(details.split(",")[0])


def hits(lines: list[str], our_side: str, pct: bool = False) -> list[Hit]:
    """The clean hits of a battle's log (the player's own view: its HP exact; ``pct``: a
    spectator's log, ours in percent as theirs)."""
    out: list[Hit] = []
    active: dict[str, str] = {}  # "p1a" -> species id
    hp: dict[tuple[str, str], int] = {}  # (side, species) -> HP (ours exact, theirs percent)
    tera: dict[tuple[str, str], str] = {}
    items = _Items()  # their mons' items as the log shows them: each hit's item then
    abil = _Abilities()  # and their abilities: each hit's ability then
    forme: dict[
        tuple[str, str], str
    ] = {}  # (side, species) -> its forme now (a -formechange's, ...)
    transformed: set = set()  # slots whose active is transformed (its stats its target's)
    since: dict[str, int] = {}  # slot -> the hits' count as its active came in (an Illusion's undo)
    # (side, nickname) -> the species it first came in as -- poke-env's key: a Palafin back in as
    # Palafin-Hero is the same mon in another forme
    came_as: dict[tuple[str, str], str] = {}
    illusion = _Illusion()  # (switch-ins that may be an Illusion holder: their hits left out)
    turn, quiet, seen_move = 0, True, False
    pending: dict | None = None
    recent = False  # the last hit can still be voided (a multi-hit's count, a Sash / Sturdy save)
    for line in lines:
        f = line.split("|")
        if len(f) < 2:
            continue
        tag = f[1]
        items.feed(f, active)
        abil.feed(f, active)
        illusion.feed(f)
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
            shown = _species(f[3])
            sp = came_as.setdefault((slot[:2], f[2].split(": ", 1)[-1]), shown)
            active[slot] = sp
            abil.entered((slot[:2], sp))
            hp[(slot[:2], sp)] = _hp(f[4])
            forme[(slot[:2], sp)] = shown
            transformed.discard(slot)
            since[slot] = len(out)
        elif tag == "replace" and len(f) > 3:
            # (an Illusion broken: the hits since it came in were the disguise's name, not its own --
            # either side's, ours under its name after too; 2026-10-24, the belief check -- a
            # Zoroark's Choice Specs hits read as a Latias's)
            slot, fake = f[2][:3], active.get(f[2][:3])
            mine = slot[:2] == our_side
            out[since.get(slot, 0) :] = [
                h
                for h in out[since.get(slot, 0) :]
                if (
                    (h.attacker if h.by_us else h.defender)
                    if mine
                    else (h.defender if h.by_us else h.attacker)
                )
                != fake
            ]
            real = came_as.setdefault((slot[:2], f[2].split(": ", 1)[-1]), _species(f[3]))
            if fake is not None and (slot[:2], fake) in hp:
                hp[(slot[:2], real)] = hp[(slot[:2], fake)]
            active[slot] = real
            forme.setdefault((slot[:2], real), real)
            pending = None
        elif tag in ("-formechange", "detailschange") and len(f) > 3 and active.get(f[2][:3]):
            forme[(f[2][:2], active[f[2][:3]])] = _species(f[3])
        elif tag == "-transform":
            transformed.add(f[2][:3])
        elif tag in ("-damage", "-heal", "-sethp") and len(f) > 3:
            # (-sethp too: a Pain Split's HP -- the next hit's HP before was the old one;
            # 2026-10-24, the belief check)
            slot = f[2][:3]
            sp = active.get(slot)
            new = _hp(f[3])
            if pending is not None and tag == "-damage" and len(f) == 4 and slot == pending["def"]:
                out.append(Hit(turn, pending["by_us"], pending["move"], pending["att"], sp,
                               pending["before"], new, pending["tera"], pending["dtera"],
                               items.now.get(pending["key"]), pending["forme"],
                               abil.now.get(pending["key"]), pct))  # fmt: skip
                recent = True
                pending = None
            if sp is not None:
                hp[(slot[:2], sp)] = new
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
            # (not a transformed mon's: its stats are its target's; 2026-10-24, the belief check:
            # an Imposter Ditto's Body Press read with its own Defense)
            if att in transformed or dfn in transformed:
                continue
            # (nor one that may be an Illusion holder in disguise)
            if illusion.ambiguous.get(att) or illusion.ambiguous.get(dfn):
                continue
            theirs = (dfn[:2], d_sp) if att[:2] == our_side else (att[:2], a_sp)
            pending = {"by_us": att[:2] == our_side, "move": to_id(f[3]), "att": a_sp,
                       "def": dfn, "before": hp[(dfn[:2], d_sp)],
                       "tera": tera.get((att[:2], a_sp)), "dtera": tera.get((dfn[:2], d_sp)),
                       "key": theirs, "forme": forme.get(theirs, "")}  # fmt: skip
            continue
        if not seen_move and tag not in _QUIET:
            quiet = False
    # (their mons' formes now: the candidates' -- a hit in another is left out)
    their = "p2" if our_side == "p1" else "p1"
    return [
        h
        for h in out
        if not h.forme
        or h.forme == forme.get((their, h.defender if h.by_us else h.attacker), h.forme)
    ]


def _shown(hp: int, maxhp: int) -> int:
    """Showdown's percent (HP Percentage Mod): ceil, 99 below full; 0 fainted."""
    if hp <= 0:
        return 0
    p = math.ceil(100 * hp / maxhp)
    return 99 if p == 100 and hp < maxhp else p


def _with_hp(
    base: str, side_one: bool, slot: int, hp: int | None = None, pct: int | None = None
) -> str:
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


def likelihood(
    hit: Hit, base: str, our_slot: int, their_slot: int, cands: list[tuple]
) -> list[float]:
    """P(the observed HP | candidate) per candidate (item, ability, stats [6], tera, on): the
    16 non-crit rolls in the turn-start state ``base`` (side one = us), the defender at its HP
    before the hit (a switch-in after its hazards: Multiscale / Shadow Shield need full HP)."""
    own_tera = bool(hit.tera if hit.by_us else hit.defender_tera)  # our mon terastallized
    # the item it held at the hit, the log's (not the one it started with)
    if hit.item_then is not None:
        cands = [(hit.item_then, *c[1:]) for c in cands]
    if hit.ability_then is not None:  # and the ability it had then, the log's
        cands = [(c[0], hit.ability_then, *c[2:]) for c in cands]
    if hit.before > 0:
        base = (_with_hp(base, False, their_slot, pct=hit.before) if hit.by_us
                else _with_hp(base, True, our_slot, pct=hit.before) if hit.pct
                else _with_hp(base, True, our_slot, hp=hit.before))  # fmt: skip
    rolls = alpha_search.set_damage_rolls(base, hit.by_us, hit.move, our_slot, their_slot, cands,
                                          own_tera)  # fmt: skip
    our_max = int(base.split("/")[0].split("=")[our_slot].split(",")[7])
    out = []
    for c, r in zip(cands, rolls, strict=True):
        if not r:
            out.append(1.0)  # no / fixed damage: no evidence
            continue
        if not hit.by_us and not hit.pct:  # theirs on ours: our HP exact
            if hit.after > 0:
                out.append(sum(x == hit.before - hit.after for x in r) / len(r))
            else:
                out.append(sum(x >= hit.before for x in r) / len(r))
            continue
        # (the defender's HP in percent: theirs, or ours in a replay -- our max HP the state's)
        maxhp = c[2][0] if hit.by_us else our_max
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


def our_disguised(state, ours: str, our_team) -> bool:
    """Our mon at a hit may be our Illusion user under another's name: the hit's species is not
    our turn-start active while an Illusion holder of ours is alive (the log shows the disguise;
    2026-10-24, the belief check -- our Zoroark hit as a Latias). ``our_team``: poke-env's."""
    active = state.side_one.pokemon[int(state.side_one.active_index)]
    if _SLOT.sub("", str(active.id).upper()) == _SLOT.sub("", ours.upper()):
        return False
    return any(to_id(m.ability or "") == "illusion" and not m.fainted for m in our_team.values())


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


# (the item changes hands: the mover's Trick / Switcheroo swap; a thief takes one only with none)
_SWAPS = ("[from] move: Trick", "[from] move: Switcheroo")
_TAKERS = ("[from] move: Thief", "[from] move: Covet", "[from] ability: Magician",
           "[from] ability: Pickpocket", "[from] move: Bestow")  # fmt: skip


ILLUSION = {"zoroark", "zoroarkhisui", "zorua", "zoruahisui"}


class _Illusion:
    """Which switch-ins may be an Illusion holder in disguise (2026-10-24, the belief check: a
    Zoroark's hits / move order read as its disguise's -- the true set ruled out). Showdown's
    Illusion: the last non-fainted mon after the holder in party order; a switch swaps the two
    mons' places (battle-actions switchIn); the order the team preview's (|poke|), its lead
    first. ``feed`` each line; ``ambiguous[slot]``: the active there may be the holder."""

    def __init__(self):
        self.order: dict[str, list[str]] = {"p1": [], "p2": []}
        self.fainted: set = set()
        self.active: dict[str, str] = {}  # slot -> the species shown
        self.ambiguous: dict[str, bool] = {}
        self._led: set = set()
        self._before: dict[
            str, tuple
        ] = {}  # slot -> (the order before its last switch-in, a lead's)

    def _target(self, side: str, order: list[str], holder: str) -> str | None:
        """The disguise of ``holder`` switching in to the place of order[0]: Showdown swaps the
        two places first (switchIn), then picks it (Illusion's onBeforeSwitchIn) -- the one
        going out may be it."""
        hyp = list(order)
        j = hyp.index(holder)
        hyp[0], hyp[j] = hyp[j], hyp[0]
        for sp in reversed(hyp[1:]):
            if (side, sp) not in self.fainted:
                return sp
        return None

    def feed(self, f: list[str]) -> None:
        tag = f[1] if len(f) > 1 else ""
        if tag == "poke" and len(f) > 3:
            sp = _species(f[3])
            if sp not in self.order[f[2]]:
                self.order[f[2]].append(sp)
        elif tag in ("switch", "drag") and len(f) > 3:
            slot, side, shown = f[2][:3], f[2][:2], _species(f[3])
            order = self.order[side]
            if shown not in order:
                order.append(shown)
            lead = side not in self._led
            holders = [
                h
                for h in order
                if h in ILLUSION and (side, h) not in self.fainted and h != self.active.get(slot)
            ]
            # (if it is the holder: its disguise -- a lead's from the preview's order)
            self.ambiguous[slot] = any(
                h != shown and self._target(side, [h] + [x for x in order if x != h] if lead else order, h) == shown
                for h in holders)  # fmt: skip
            self._before[slot] = (list(order), lead)
            if lead:  # (the lead first, the rest in the preview's order)
                self._led.add(side)
                order.remove(shown)
                order.insert(0, shown)
            i, j = 0, order.index(shown)
            order[i], order[j] = order[j], order[i]
            self.active[slot] = shown
        elif tag == "replace" and len(f) > 3:
            slot, side, real = f[2][:3], f[2][:2], _species(f[3])
            before, lead = self._before.get(slot, (None, False))
            if before is not None and real in before:
                # (the holder came in, not the one shown: its switch redone from the order before --
                # a lead first, else its place swapped with the first's)
                if lead:
                    order = [real] + [h for h in before if h != real]
                else:
                    order, j = list(before), before.index(real)
                    order[0], order[j] = order[j], order[0]
                self.order[side] = order
            self.active[slot], self.ambiguous[slot] = real, False
        elif tag == "faint" and len(f) > 2:
            sp = self.active.get(f[2][:3])
            if sp is not None:
                self.fainted.add((f[2][:2], sp))


class _Items:
    """A battle's items as its log shows them, per (side, species id): the item a mon holds now --
    None while it is the one it started with (unknown unless revealed), else the one the log
    names: an -item change's (Trick, Thief, Magician, Harvest, Bestow, ...), "none" after an
    -enditem -- and the one it started with once revealed: an -enditem of it, a Frisk, a swap
    partner's received one, a taker's none (Thief, Covet, Magician, Pickpocket, Bestow's receiver
    take one only with none), the one a taker's [of] lost. A Frisk / an announcement (Air Balloon)
    is no change."""

    def __init__(self):
        self.now: dict = {}
        self.original: dict = {}
        self.changed: set = set()
        self._swap: list | None = None  # [(key, its item before)...] of the swap going on
        self._got: dict = {}

    def _end_swap(self) -> None:
        if self._swap:
            keys = [k for k, _ in self._swap]
            for k, before in self._swap:
                other = next((x for x in keys if x != k), None)
                if before is None and other is not None:
                    self.original.setdefault(k, self._got.get(other, "none"))
        self._swap, self._got = None, {}

    def feed(self, f: list[str], active: dict) -> None:
        tag = f[1] if len(f) > 1 else ""
        line = "|".join(f)
        if self._swap is not None and not (
            tag in ("-item", "-enditem") and any(x in line for x in _SWAPS)
        ):
            self._end_swap()
        if tag == "-activate" and len(f) > 3 and f[3] in ("move: Trick", "move: Switcheroo"):
            of = next((x[5:] for x in f[4:] if x.startswith("[of] ")), "")
            a, b = active.get(f[2][:3]), active.get(of[:3])
            if a and b:
                ka, kb = (f[2][:2], a), (of[:2], b)
                self._swap = [(ka, self.now.get(ka)), (kb, self.now.get(kb))]
            return
        if tag not in ("-item", "-enditem") or len(f) < 4 or not active.get(f[2][:3]):
            return
        key, item = (f[2][:2], active[f[2][:3]]), to_id(f[3])
        if tag == "-enditem":
            if self.now.get(key) is None:
                self.original.setdefault(key, item)
            self.now[key] = "none"
            self.changed.add(key)
        elif "[from]" not in line or "[from] ability: Frisk" in line:  # (a reveal)
            if self.now.get(key) is None:
                self.original.setdefault(key, item)
        else:
            if any(x in line for x in _SWAPS):
                self._got[key] = item
            elif any(x in line for x in _TAKERS):
                if self.now.get(key) is None:
                    self.original.setdefault(key, "none")
                # (the [of] one lost it: Magician's, Covet's, Bestow's giver's log no -enditem of
                # it -- Showdown's takeItem prints nothing; 2026-10-25 review: a Choice Scarf
                # Latios's turns before a Magician took it read itemless)
                of = next((x[5:] for x in f[4:] if x.startswith("[of] ")), "")
                lost = active.get(of[:3])
                if lost and of[:2] != f[2][:2]:
                    lk = (of[:2], lost)
                    if self.now.get(lk) is None:
                        self.original.setdefault(lk, item)
                    self.now[lk] = "none"
                    self.changed.add(lk)
            self.now[key] = item
            self.changed.add(key)


def item_changes(lines: list[str]) -> dict[tuple[str, str], str | None]:
    """(side, species id) -> the item it started with, for the mons whose item changed (``_Items``):
    None if not revealed -- its hits before the change are of that item, the candidates' (not the
    one it holds now: 2026-10-24 review, a Choice Specs Latios's Surf read with the Life Orb a
    Trick gave it)."""
    items, active = _Items(), {}
    for line in lines + [""]:
        f = line.split("|")
        # (an Illusion broken -- replace: the slot's mon is the real one from then; Showdown prints
        # it before the line its End came from, a Mummy's -activate: 2026-10-25 review)
        if len(f) > 3 and f[1] in ("switch", "drag", "replace"):
            active[f[2][:3]] = _species(f[3])
        items.feed(f, active)
    return {k: items.original.get(k) for k in items.changed}


class _Abilities:
    """A battle's abilities as its log shows them changing, per (side, species id) -- Showdown's
    Pokemon.setAbility / Battle.skillSwap, each till the mon switches out (clearVolatile: its
    baseAbility back): the ability it has now (None: the one it started with) and the one it
    started with once the log names it. The lines: -ability NEW OLD [from] (Trace, Role Play,
    Entrainment, Worry Seed, Simple Beam, Doodle; OLD absent in an older protocol); -activate
    "ability: Mummy" / "ability: Lingering Aroma" with the contact mon and its [ability] OLD;
    -activate Skill Swap A B [of] (Wandering Spirit's too: the user gets A, the [of] one B);
    -endability (Gastro Acid, Core Enforcer: suppressed, "none"). An announcement (-ability
    without [from]) is its ability now: the one it started with if unchanged."""

    def __init__(self):
        self.now: dict = {}
        self.original: dict = {}
        self.changed: set = set()

    def entered(self, key) -> None:
        self.now.pop(key, None)  # (its changes ended as it left)

    def _set(self, key, new: str, old: str = "") -> None:
        if self.now.get(key) is None and old:
            self.original.setdefault(key, to_id(old))
        self.now[key] = to_id(new) or "none"
        self.changed.add(key)

    def feed(self, f: list[str], active: dict) -> None:
        tag = f[1] if len(f) > 1 else ""
        if len(f) < 3 or not active.get(f[2][:3]):  # (-endability has no fourth field)
            return
        key = (f[2][:2], active[f[2][:3]])
        if tag == "-endability":
            self._set(key, "none")
        elif len(f) < 4:
            return
        elif tag == "-ability":
            if any(x.startswith("[from]") for x in f[4:]):
                self._set(key, f[3], f[4] if len(f) > 5 and not f[4].startswith("[") else "")
            elif self.now.get(key) is None:
                self.original.setdefault(key, to_id(f[3]))
        elif (
            tag == "-activate"
            and f[3] in ("ability: Mummy", "ability: Lingering Aroma")
            and len(f) > 4
        ):
            if self.now.get(key) is None:
                self.original.setdefault(key, to_id(f[3][9:]))  # (the holder's)
            mon = active.get(f[4][:3])
            if mon:
                old = next((x[10:] for x in f[5:] if x.startswith("[ability] ")), "")
                self._set((f[4][:2], mon), f[3][9:], old)
        elif tag == "-activate" and f[3].replace("move: ", "") == "Skill Swap" and len(f) > 6:
            of = next((x[5:] for x in f[4:] if x.startswith("[of] ")), "")
            other = active.get(of[:3])
            a, b = f[4].replace("[ability] ", ""), f[5].replace("[ability] ", "")
            if other and a and b and not b.startswith("[of]"):
                self._set(key, a, b)
                self._set((of[:2], other), b, a)


def ability_changes(lines: list[str]) -> dict[tuple[str, str], str | None]:
    """(side, species id) -> the ability it started with, for the mons whose ability changed
    (``_Abilities``): None if the log never named it -- its hits before the change are of that
    ability, the candidates' (not the one it has now: 2026-10-25 review, a Huge Power Azumarill's
    hit read with the Synchronize a Skill Swap gave it after)."""
    abil, active = _Abilities(), {}
    for line in lines + [""]:
        f = line.split("|")
        if len(f) > 3 and f[1] in ("switch", "drag", "replace"):  # (replace: item_changes')
            active[f[2][:3]] = _species(f[3])
            if f[1] != "replace":
                abil.entered((f[2][:2], active[f[2][:3]]))
        abil.feed(f, active)
    return {k: abil.original.get(k) for k in abil.changed}


def _candidates(
    belief, mon, team_names: tuple[str, ...], then=False, mix=None, ab=False
) -> tuple[list, list[float]]:
    """(item, ability, Spread) candidates of an opposing mon and their prior: the belief's team-
    conditioned item marginal (a revealed item alone), the usage of its possible abilities (a
    revealed one alone), the usage spreads. The item is the one it held when it hit / was hit:
    a gone item counts as unknown here; ``then``, for a mon whose item changed hands since
    (``item_changes``), the one it held before (None: not known -- not the one it holds now).
    The ability likewise the one it started with: ``ab``, for a mon whose ability changed since
    (``ability_changes``), the log's (None: not known -- the species', not poke-env's now)."""
    from alpha_poke.agents.belief_state import _preview_name, ability_probs, species_ability_probs
    from alpha_poke.agents.engine_state import base_marginal, required_item
    from alpha_poke.agents.speed import spread_dist

    # (the sampler's base item marginal: engine_state.base_marginal -- the team prior's sees the
    # revealed items only; 2026-10-25)
    marg = base_marginal(belief, _preview_name(mon, team_names), team_names, "item", mix)
    if then is not False and then is not None:
        items = [(then, 1.0)]
    elif then is None:
        items = sorted(marg.items(), key=lambda kv: -kv[1])[:TOP_ITEMS] or [("none", 1.0)]
    elif mon.item and mon.item != "unknown_item":
        items = [(mon.item, 1.0)]
    # (a forme's item: engine_state.required_item)
    elif required_item(mon) and (mix is None or mix > 0):
        items = [(required_item(mon), 1.0)]
    else:
        items = sorted(marg.items(), key=lambda kv: -kv[1])[:TOP_ITEMS] or [("none", 1.0)]
    if ab is not False and ab is not None:
        abilities = [(ab, 1.0)]
    else:
        abilities = list((ability_probs(mon) if ab is False else species_ability_probs(mon)).items()) \
            or [("none", 1.0)]  # fmt: skip
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


def damage_posteriors(battle, belief, theirs: list, team_names: tuple[str, ...], mix=None,
                      pct: bool = False) -> dict:  # fmt: skip
    """Per opposing species id with clean hits: [(item, ability, Spread, posterior weight)] over
    its candidates (``_candidates``), from the turn-start states the search recorded
    (``record_base``). Cached per mon and evidence. ``pct``: our HP in percent too (a replay's
    side, its team pasted)."""
    import poke_engine as pe

    from alpha_poke.agents.damage import calc_stats
    from alpha_poke.agents.net_context import battle_log
    from alpha_poke.agents.pokeview import own_base_stats

    bases = getattr(battle, "_alpha_bases", None)
    if not bases:
        return {}
    role = battle.player_role or "p1"
    # (poke-env's messages, split at "|")
    lines = [m if isinstance(m, str) else "|".join(m) for m in battle_log(battle)]
    parsed_log = getattr(battle, "_alpha_hits", None)  # (lines seen, hits): once per new message
    if parsed_log is None or parsed_log[0] != len(lines):
        parsed_log = (
            len(lines),
            hits(lines, role, pct),
            item_changes(lines),
            ability_changes(lines),
        )
        battle._alpha_hits = parsed_log
    them = "p2" if role == "p1" else "p1"
    changes = parsed_log[2]
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
        then = changes.get((them, sp), False)  # (its item changed hands: the one it held then)
        ab = parsed_log[3].get((them, sp), False)  # (its ability changed: the one it started with)
        key = (sp, len(mh), m.item, m.ability, then, ab, mix)
        if key not in cache:
            cands, prior = _candidates(belief, m, team_names, then=then, mix=mix, ab=ab)
            level = m.level or 100
            # (its own base stats: a transformed one's poke-env has its target's)
            stats = [calc_stats(own_base_stats(m), c[2], level=level) for c in cands]
            vec = [[s["hp"], s["atk"], s["def"], s["spa"], s["spd"], s["spe"]] for s in stats]
            likes = []
            for h in mh:
                base = bases[h.turn]
                st = parsed.get(h.turn)
                if st is None:
                    st = parsed[h.turn] = pe.State.from_string(base)
                ours = h.attacker if h.by_us else h.defender
                os_, ts = slot_of(st, True, ours), slot_of(st, False, sp)
                if os_ is None or ts is None or our_disguised(st, ours, battle.team):
                    continue
                on = h.defender_tera if h.by_us else h.tera  # their mon terastallized at the hit
                tera = on or (m.tera_type.name.lower() if m.tera_type else "typeless")
                try:
                    likes.append(likelihood(h, base, os_, ts, [(c[0], c[1], v, tera, bool(on))
                                                               for c, v in zip(cands, vec, strict=True)]))  # fmt: skip
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
