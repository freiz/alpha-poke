"""Parse a Showdown spectator-view replay log (singles) into structured records.

A replay is the *spectator* log: team preview shows species only, and moves / items /
abilities / tera types appear only when they are revealed during the battle. This parser
reconstructs, per side:

* the 6-mon team from team preview and what was revealed about each mon,
* the lead, every turn's actions (move / switch, with forced switches and tera flagged),
* HP% snapshots, field events (hazards, weather, terrain), faints, the winner and ratings.

Revealed information is heuristic where the protocol is: holders of ``[from] item:`` /
``[from] ability:`` tags are resolved with the ``[of]`` tag when present. Known limitations
(see ``Replay.warnings``): Illusion is merged on ``|replace|`` only; moves a transformed mon
uses are ignored; doubles are not supported.
"""

import re
from dataclasses import asdict, dataclass, field

SIDES = ("p1", "p2")
_ABILITY_CHANGERS = frozenset(
    {"Skill Swap", "Role Play", "Entrainment", "Worry Seed", "Simple Beam", "Doodle", "Gastro Acid"}
)
# commands whose handler interprets [from] item: / [from] ability: itself
_OWN_TAG_HANDLING = frozenset(
    {
        "move",
        "-item",
        "-enditem",
        "-ability",
        "-damage",
        "-heal",
        "-weather",
        "-fieldstart",
        "-activate",
        "switch",
        "drag",
        "replace",
        "detailschange",
        "-formechange",
    }
)
_POS = re.compile(r"^(p[12])([a-c])?: (.*)$")
_RATING = re.compile(r"^(.*)'s rating: (\d+) &rarr; <strong>(\d+)</strong>")


def _species(details: str) -> tuple[str, str | None]:
    """'Glimmora, F' -> ('Glimmora', 'F'); 'Garchomp, L50, M' -> ('Garchomp', 'M')."""
    parts = [p.strip() for p in details.split(",")]
    gender = next((p for p in parts[1:] if p in ("M", "F")), None)
    return parts[0], gender


def _base(species: str) -> str:
    return species.split("-")[0]


def _tags(args: list[str]) -> dict[str, str]:
    """Parse trailing '[from] x' / '[of] y' / '[still]' style tags into a dict."""
    out = {}
    for a in args:
        m = re.match(r"^\[(\w+)\]\s*(.*)$", a)
        if m:
            out[m.group(1)] = m.group(2)
    return out


@dataclass
class MonRecord:
    species: str  # as shown in team preview
    gender: str | None = None
    nicknames: list[str] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)  # other species names seen (formes, tera forms)
    moves: list[str] = field(default_factory=list)  # in order of first reveal
    item: str | None = None  # item held / used / consumed, first revealed
    item_consumed: bool = False
    item_lost: str | None = None  # how it was lost, e.g. 'Knock Off'
    ability: str | None = None
    tera_type: str | None = None
    tera_turn: int | None = None
    lead: bool = False
    brought: bool = False  # ever appeared on the field
    switch_ins: list[int] = field(default_factory=list)  # turns of switch-in
    fainted_turn: int | None = None
    hp: int | None = None  # last known HP percent
    phantom: bool = False  # not in team preview (Illusion / unmatched)

    def revealed_fraction(self) -> dict[str, float | bool]:
        return {
            "moves": len(self.moves) / 4,
            "item": self.item is not None,
            "ability": self.ability is not None,
            "tera": self.tera_type is not None,
        }


@dataclass
class Action:
    turn: int  # 0 = lead switch-in before turn 1
    side: str
    kind: str  # 'lead' | 'move' | 'switch'
    mon: str  # species of the acting / switched-out mon
    move: str | None = None  # for kind == 'move'
    to: str | None = None  # for kind in ('switch', 'lead'): the mon coming in
    tera: bool = False
    forced: bool = False  # switch after a faint
    pivot: bool = False  # switch right after the same side's move (U-turn, Baton Pass, ...)
    order: int = 0  # position within the turn (0 = first)


@dataclass
class Replay:
    id: str
    format: str
    gen: int
    players: dict[str, str]  # side -> name
    ratings_before: dict[str, int | None]
    ratings_after: dict[str, int | None]
    uploadtime: int | None
    winner: str | None  # 'p1' | 'p2' | None (tie / unknown)
    turns: int
    teams: dict[str, list[MonRecord]]
    actions: list[Action]
    hp_by_turn: dict[int, dict[str, tuple[str, int]]]  # turn -> side -> (species, hp%)
    field_events: list[dict]
    warnings: list[str]

    def leads(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {s: None for s in SIDES}
        for a in self.actions:
            if a.kind == "lead":
                out[a.side] = a.to
        return out

    def team_sheet(self, side: str) -> str:
        """Pokepaste-like text of what was revealed (unknown parts are omitted)."""
        blocks = []
        for m in self.teams[side]:
            head = m.species + (f" @ {m.item}" if m.item else "")
            lines = [head]
            if m.ability:
                lines.append(f"Ability: {m.ability}")
            if m.tera_type:
                lines.append(f"Tera Type: {m.tera_type}")
            lines += [f"- {mv}" for mv in m.moves]
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def to_dict(self) -> dict:
        return asdict(self)


class ReplayParser:
    """Stateful single-pass parser. Use ``parse_replay`` for the one-shot API."""

    def __init__(self, replay: dict):
        self.raw = replay
        self.players: dict[str, str] = {}
        self.ratings_before: dict[str, int | None] = {s: None for s in SIDES}
        self.ratings_after: dict[str, int | None] = {s: None for s in SIDES}
        self.teams: dict[str, list[MonRecord]] = {s: [] for s in SIDES}
        self.active: dict[str, MonRecord | None] = {s: None for s in SIDES}
        self.actions: list[Action] = []
        self.hp_by_turn: dict[int, dict[str, tuple[str, int]]] = {}
        self.field_events: list[dict] = []
        self.warnings: list[str] = []
        self.turn = 0
        self.winner: str | None = None
        self.gen = 0
        self.tier = replay.get("format", "")
        self.pending_forced: set[str] = set()
        self.tera_pending: dict[str, str] = {}
        self.order = 0
        self.transformed: set[str] = set()
        self.ability_changed: set[str] = set()  # sides whose active mon's ability was swapped
        self.gametype = "singles"

    # ---- helpers ---------------------------------------------------------------------
    def _side_of_name(self, name: str) -> str | None:
        for s, n in self.players.items():
            if n == name:
                return s
        return None

    def _mon(self, token: str) -> tuple[str | None, MonRecord | None]:
        """Resolve 'p1a: Nick' to (side, active mon)."""
        m = _POS.match(token.strip())
        if not m:
            return None, None
        side = m.group(1)
        return side, self.active[side]

    def _find_entry(self, side: str, species: str) -> MonRecord | None:
        team = self.teams[side]
        for m in team:
            if m.species == species or species in m.forms:
                return m
        b = _base(species)
        for m in team:
            if _base(m.species) == b:
                return m
        return None

    def _set_hp(self, side: str, mon: MonRecord, hp_field: str) -> None:
        if hp_field.endswith("fnt"):
            mon.hp = 0
            return
        m = re.match(r"^(\d+)/(\d+)", hp_field)
        if m:
            cur, mx = int(m.group(1)), int(m.group(2))
            mon.hp = round(100 * cur / mx) if mx else None

    def _holder(
        self, token_mon: tuple[str | None, MonRecord | None], tags: dict
    ) -> MonRecord | None:
        of = tags.get("of")
        if of:
            _, m = self._mon(of)
            if m:
                return m
        return token_mon[1]

    def _reveal_item(self, mon: MonRecord | None, item: str, consumed=False, lost=None) -> None:
        if mon is None or not item:
            return
        if mon.item is None:
            mon.item = item
        if consumed and mon.item == item:
            mon.item_consumed = True
        if lost and mon.item == item:
            mon.item_lost = lost

    def _reveal_from_tags(self, args: list[str], cmd: str = "") -> None:
        """Generic reveal for ``[from] ability: X`` / ``[from] item: Y`` on any message.

        Showdown's convention: a trailing ``[of]`` names the holder of the ability / item
        (``-status|ATTACKER|brn|[from] ability: Flame Body|[of] HOLDER``). Absorb-style
        abilities are the exception: ``-immune`` / ``-heal`` lines name the holder first and use
        ``[of]`` for the attacker; those are resolved to the first mon on the line.
        """
        tags = _tags(args)
        src = tags.get("from", "")
        if not (src.startswith("ability:") or src.startswith("item:")):
            return
        first = next((a for a in args if _POS.match(a.strip())), None)
        line_mon = self._mon(first) if first else (None, None)
        holder = line_mon[1] if cmd in ("-immune", "-heal") else self._holder(line_mon, tags)
        if src.startswith("ability:"):
            self._reveal_ability(holder, src[8:].strip())
        else:
            self._reveal_item(holder, src[5:].strip())

    def _reveal_ability(self, mon: MonRecord | None, ability: str) -> None:
        if mon is None or not ability:
            return
        if mon.ability is None:
            mon.ability = ability

    # ---- main loop -------------------------------------------------------------------
    def parse(self) -> Replay:
        for line in self.raw["log"].split("\n"):
            if not line.startswith("|"):
                continue
            parts = line.split("|")[1:]
            if not parts:
                continue
            cmd, args = parts[0], parts[1:]
            handler = getattr(self, f"_on_{cmd.strip('-').replace(':', '')}", None)
            if handler:
                handler(args)
            if cmd not in _OWN_TAG_HANDLING:
                self._reveal_from_tags(args, cmd)
        return Replay(
            id=self.raw.get("id", ""),
            format=self.raw.get("formatid") or self.tier,
            gen=self.gen,
            players=self.players,
            ratings_before=self.ratings_before,
            ratings_after=self.ratings_after,
            uploadtime=self.raw.get("uploadtime"),
            winner=self.winner,
            turns=self.turn,
            teams=self.teams,
            actions=self.actions,
            hp_by_turn=self.hp_by_turn,
            field_events=self.field_events,
            warnings=self.warnings,
        )

    # ---- header ----------------------------------------------------------------------
    def _on_gametype(self, a):
        self.gametype = a[0]
        if a[0] != "singles":
            self.warnings.append(f"unsupported gametype {a[0]}")

    def _on_gen(self, a):
        self.gen = int(a[0])

    def _on_tier(self, a):
        self.tier = a[0]

    def _on_player(self, a):
        side = a[0]
        if len(a) > 1 and a[1] and side not in self.players:
            self.players[side] = a[1]
            if len(a) > 3 and a[3].isdigit():
                self.ratings_before[side] = int(a[3])

    def _on_poke(self, a):
        side = a[0]
        species, gender = _species(a[1])
        self.teams[side].append(MonRecord(species=species, gender=gender))

    # ---- battle flow -----------------------------------------------------------------
    def _on_turn(self, a):
        self.turn = int(a[0])
        self.order = 0
        self.pending_forced.clear()
        snap = {}
        for s in SIDES:
            m = self.active[s]
            if m is not None and m.hp is not None:
                snap[s] = (m.species, m.hp)
        self.hp_by_turn[self.turn] = snap

    def _on_switch(self, a, drag=False):
        side, _ = self._mon(a[0])
        if side is None:
            return
        species, gender = _species(a[1])
        nick = _POS.match(a[0]).group(3)
        mon = self._find_entry(side, species)
        if mon is None:
            mon = MonRecord(species=species, gender=gender, phantom=True)
            self.teams[side].append(mon)
            self.warnings.append(f"{side} {species} not in team preview (Illusion?)")
        if species != mon.species and species not in mon.forms:
            mon.forms.append(species)
        if nick not in mon.nicknames:
            mon.nicknames.append(nick)
        prev = self.active[side]
        is_lead = not mon.brought and self.turn == 0 and prev is None
        mon.brought = True
        mon.lead = mon.lead or is_lead
        mon.switch_ins.append(self.turn)
        self._set_hp(side, mon, a[2] if len(a) > 2 else "")
        forced = side in self.pending_forced
        self.pending_forced.discard(side)
        last = next((x for x in reversed(self.actions) if x.side == side), None)
        pivot = (
            not forced
            and not is_lead
            and last is not None
            and last.turn == self.turn
            and last.kind == "move"
        )
        if is_lead:
            self.actions.append(Action(0, side, "lead", "", to=mon.species))
        elif not drag:
            self.actions.append(
                Action(
                    self.turn,
                    side,
                    "switch",
                    prev.species if prev else "",
                    to=mon.species,
                    forced=forced,
                    pivot=pivot,
                    order=self.order,
                )
            )
            self.order += 1
        self.active[side] = mon
        self.transformed.discard(side)
        self.ability_changed.discard(side)

    def _on_drag(self, a):
        self._on_switch(a, drag=True)

    def _on_replace(self, a):
        """Illusion ends: the phantom entry created on switch-in is merged into the real mon."""
        side, phantom = self._mon(a[0])
        if side is None or phantom is None:
            return
        species, _ = _species(a[1])
        real = self._find_entry(side, species)
        if real is None or real is phantom:
            return
        real.moves += [m for m in phantom.moves if m not in real.moves]
        real.item = real.item or phantom.item
        real.brought = True
        real.hp = phantom.hp
        real.switch_ins += phantom.switch_ins
        real.lead = real.lead or phantom.lead
        real.nicknames += [n for n in phantom.nicknames if n not in real.nicknames]
        if phantom.phantom and phantom in self.teams[side]:
            self.teams[side].remove(phantom)
        self.active[side] = real

    def _on_detailschange(self, a):
        side, mon = self._mon(a[0])
        if mon is None:
            return
        species, _ = _species(a[1])
        if species != mon.species and species not in mon.forms:
            mon.forms.append(species)

    _on_formechange = _on_detailschange

    def _on_move(self, a):
        side, mon = self._mon(a[0])
        if side is None or mon is None:
            return
        move = a[1]
        tags = _tags(a[3:] if len(a) > 3 else [])
        if "from" in tags:  # called / locked / ability-triggered: not a revealed move slot
            return
        if move not in ("Struggle", "Recharge") and side not in self.transformed:
            if move not in mon.moves:
                mon.moves.append(move)
        tera = self.tera_pending.pop(side, None) is not None
        self.actions.append(
            Action(self.turn, side, "move", mon.species, move=move, tera=tera, order=self.order)
        )
        self.order += 1

    def _on_cant(self, a):
        side, mon = self._mon(a[0])
        if mon is not None and len(a) > 2 and a[2] and side not in self.transformed:
            if a[2] not in mon.moves:
                mon.moves.append(a[2])

    def _on_faint(self, a):
        side, mon = self._mon(a[0])
        if mon is not None:
            mon.fainted_turn = self.turn
            mon.hp = 0
            self.pending_forced.add(side)

    # ---- reveals ---------------------------------------------------------------------
    def _on_terastallize(self, a):
        side, mon = self._mon(a[0])
        if mon is not None:
            mon.tera_type = a[1]
            mon.tera_turn = self.turn
            self.tera_pending[side] = a[1]

    def _on_damage(self, a, heal: bool = False):
        side, mon = self._mon(a[0])
        if mon is None:
            return
        self._set_hp(side, mon, a[1])
        tags = _tags(a[2:])
        src = tags.get("from", "")
        # -damage ... [from] item: Rocky Helmet / ability: Rough Skin | [of] HOLDER
        # -heal   ... [from] ability: Water Absorb | [of] ATTACKER  (holder = healed mon)
        holder = mon if heal else self._holder((side, mon), tags)
        if src.startswith("item:"):
            self._reveal_item(holder, src[5:].strip())
        elif src.startswith("ability:"):
            self._reveal_ability(holder, src[8:].strip())

    def _on_heal(self, a):
        self._on_damage(a, heal=True)

    def _on_sethp(self, a):
        pass

    def _on_item(self, a):
        side, mon = self._mon(a[0])
        tags = _tags(a[2:])
        src = tags.get("from", "")
        if src.startswith("move:"):
            return  # Trick / Switcheroo / Thief: not the original item
        if src.startswith("ability:"):
            ability = src[8:].strip()
            if ability == "Frisk":  # -item|TARGET|its item|[from] ability: Frisk|[of] FRISKER
                self._reveal_ability(self._holder((None, None), tags), ability)
                self._reveal_item(mon, a[1])
            else:  # Pickpocket / Magician / ...: the line mon took someone else's item
                self._reveal_ability(mon, ability)
            return
        self._reveal_item(mon, a[1])

    def _on_enditem(self, a):
        side, mon = self._mon(a[0])
        tags = _tags(a[2:])
        src = tags.get("from", "")
        lost = src[5:].strip() if src.startswith("move:") else None
        self._reveal_item(mon, a[1], consumed=True, lost=lost)

    def _on_ability(self, a):
        side, mon = self._mon(a[0])
        tags = _tags(a[2:])
        if "from" in tags and tags["from"].startswith("ability:"):
            return  # Trace / Skill Swap style transfers
        if side in self.ability_changed:
            return  # ability acquired via Skill Swap / Role Play / Entrainment / ...
        self._reveal_ability(mon, a[1])

    def _on_activate(self, a):
        side, mon = self._mon(a[0])
        if mon is None or len(a) < 2:
            return
        what = a[1]
        if what.replace("move: ", "") in _ABILITY_CHANGERS:
            self.ability_changed.add(side)
            of = _tags(a[2:]).get("of")
            if of and self._mon(of)[0]:
                self.ability_changed.add(self._mon(of)[0])
            return
        if what.startswith("ability:"):
            self._reveal_ability(mon, what[8:].strip())
        elif what.startswith("item:"):
            self._reveal_item(mon, what[5:].strip())

    def _on_transform(self, a):
        side, _ = self._mon(a[0])
        if side:
            self.transformed.add(side)

    # ---- field -----------------------------------------------------------------------
    def _field(self, kind: str, side: str | None, detail: str, **extra):
        self.field_events.append(
            {"turn": self.turn, "kind": kind, "side": side, "detail": detail, **extra}
        )

    def _on_sidestart(self, a):
        m = re.match(r"^(p[12]):", a[0])
        self._field("sidestart", m.group(1) if m else None, a[1].replace("move: ", ""))

    def _on_sideend(self, a):
        m = re.match(r"^(p[12]):", a[0])
        self._field("sideend", m.group(1) if m else None, a[1].replace("move: ", ""))

    def _on_weather(self, a):
        tags = _tags(a[1:])
        self._field("weather", None, a[0], source=tags.get("from"))
        src = tags.get("from", "")
        if src.startswith("ability:"):
            self._reveal_ability(self._holder((None, None), tags), src[8:].strip())

    def _on_fieldstart(self, a):
        tags = _tags(a[1:])
        self._field("fieldstart", None, a[0].replace("move: ", ""), source=tags.get("from"))
        src = tags.get("from", "")
        if src.startswith("ability:"):
            self._reveal_ability(self._holder((None, None), tags), src[8:].strip())

    def _on_fieldend(self, a):
        self._field("fieldend", None, a[0].replace("move: ", ""))

    # ---- result ----------------------------------------------------------------------
    def _on_win(self, a):
        self.winner = self._side_of_name(a[0])

    def _on_raw(self, a):
        m = _RATING.match(a[0])
        if m:
            side = self._side_of_name(m.group(1))
            if side:
                self.ratings_after[side] = int(m.group(3))


def parse_replay(replay: dict) -> Replay:
    """Parse the JSON returned by ``<id>.json`` (needs the ``log`` key)."""
    return ReplayParser(replay).parse()
