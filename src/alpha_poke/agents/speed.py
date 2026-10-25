"""The opponent's speed (design D17 A, 2026-10-11): its nature / EVs were fixed to the species'
most common spread in every world (belief.spread_for), only the item (Choice Scarf) sampled, so a
fast spread was never considered and "it moved first" was never learned from.

  spread_dist(species)   the usage statistics' spreads (top ones, weights)
  observations(lines, our_side, our_speed)
                         from the protocol log: each turn both actives used a move of the same
                         priority, who moved first, our effective speed and the opponent's speed
                         multiplier then (boosts, paralysis, Tailwind, Protosynthesis / Quark
                         Drive, Trick Room); turns where an unseen effect could decide the order
                         (speed abilities in weather / terrain, Quick Claw, Prankster-like
                         priority, ...) are left out
  consistent(obs, speed_stat, item)
                         a candidate (speed stat, item) of the opponent's mon against them
"""

import functools
import dataclasses
from dataclasses import dataclass
from pathlib import Path

from poke_env.data import GenData

from alpha_poke.analysis.roles import to_id

GEN = GenData.from_gen(9)
TOP_SPREADS = 30
# abilities that change speed or priority without a message before the move
WEATHER_SPEED = {"raindance": "swiftswim", "sunnyday": "chlorophyll", "sandstorm": "sandrush",
                 "snowscape": "slushrush", "snow": "slushrush"}  # fmt: skip
PRIORITY_ABILITIES = {"prankster", "triage", "galewings"}
ORDER_ITEMS = ("Quick Claw", "Custap Berry", "Quick Draw")
TIE = 0.005  # relative speed difference treated as a tie (rounding)


@functools.cache
def _stats():
    from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats

    months = sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    return UsageStats.load(DEFAULT_DIR / months[-1] / "chaos" / "gen9ou-1825.json")


@functools.cache
def _by_id() -> dict:
    return {to_id(name): s for name, s in _stats().species.items()}


@functools.cache
def spread_dist(species: str) -> tuple[tuple, tuple]:
    """(spreads as Spread, weights) of the species' most used spreads (empty if unknown)."""
    from alpha_poke.agents.damage import Spread

    sid = to_id(species)
    s = _by_id().get(sid)
    if s is None:  # forms: the longest table name it starts with
        keys = [k for k in _by_id() if sid.startswith(k) or k.startswith(sid)]
        s = _by_id()[max(keys, key=len)] if keys else None
    if s is None or not s.spreads:
        return (), ()
    top = sorted(s.spreads.items(), key=lambda kv: -kv[1])[:TOP_SPREADS]
    return tuple(Spread.parse(t) for t, _ in top), tuple(w for _, w in top)


def boost_mult(stage: int) -> float:
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


def abilities(species: str) -> set[str]:
    entry = GEN.pokedex.get(to_id(species)) or {}
    return {to_id(a) for a in (entry.get("abilities") or {}).values()}


@dataclass
class Obs:
    turn: int
    species: str  # the opponent's active (species id)
    ours: float  # our active's effective speed
    mult: float  # the opponent's multiplier besides its stat and item
    trick_room: bool
    opp_first: bool
    # the opponent's item then when the log names it (after its first change hands: a Trick's,
    # a Switcheroo's, a Knock Off's none -- agents/damage_obs._Items); None: the one it started
    # with, the candidate's (2026-10-24, the belief check: a Glalie that got its Choice Scarf by
    # Switcheroo read with it at the turns before -- the true speed ruled out)
    item_then: str | None = None
    # the opponent's forme's base speed then (a Minior's Meteor / Core, an Eiscue's Noice, ...:
    # consistent's stat_of; 2026-10-24, the belief check -- the forme now read for every turn)
    base_spe: int | None = None
    # (our speed besides our item, our species, and our item then -- None: the one it started with,
    # resolved in result(): a Trick's Choice Scarf read at the turns before it, 2026-10-24)
    ours_raw: float = 0.0
    our_species: str = ""
    our_item_then: str | None = None
    our_forme: str = ""  # (our active's forme then: our speed stat is the one now -- another left out)


@dataclass
class _Side:
    active: str = ""
    names: dict = None
    spe: int = 0  # speed boost stage of the active
    status: dict = None
    tailwind: bool = False
    proto: bool = False  # Protosynthesis / Quark Drive on speed
    forme: dict = None  # species -> its forme now (a -formechange's, a detailschange's)
    transformed: bool = False  # the active is transformed (its speed its target's)

    def __post_init__(self):
        self.names, self.status, self.forme = {}, {}, {}


def _status_move(move: str) -> bool:
    return (GEN.moves.get(to_id(move)) or {}).get("category") == "Status"


def _move_priority(move: str) -> int:
    return int((GEN.moves.get(to_id(move)) or {}).get("priority", 0))


def _risky_priority(move: str, abils: set[str], grassy: bool) -> bool:
    """Could an unseen ability / terrain change the move's priority?"""
    m = GEN.moves.get(to_id(move)) or {}
    if "prankster" in abils and m.get("category") == "Status":
        return True
    if "triage" in abils and (m.get("flags") or {}).get("heal"):
        return True
    if "galewings" in abils and m.get("type") == "Flying":
        return True
    return to_id(move) == "grassyglide" and grassy


class ObsTracker:
    """``observations`` fed one protocol message at a time (a live battle feeds the messages
    added since the last decision: 2026-10-11, re-reading the whole log at every decision was 14%
    of a policy-only worker). ``our_speed(species) -> (speed stat, item id, ability id)``."""

    def __init__(self, our_side: str, our_speed):
        self.our_side, self.our_speed = our_side, our_speed
        self.opp_side = "p2" if our_side == "p1" else "p1"
        self.sides = {"p1": _Side(), "p2": _Side()}
        self.weather, self.terrain, self.trick_room = "", "", False
        self.out: list[Obs] = []
        self.block: list[list[str]] = []
        self.turn = 0
        # the state at the turn's first move (end-of-turn switches, boosts from the moves
        # themselves must not count: 2026-10-11, 11% of the observations broke the opponent's
        # true speed until this)
        self.snap: dict | None = None
        from alpha_poke.agents.damage_obs import _Abilities, _Illusion, _Items

        self.items = _Items()  # each side's item as the log shows it (its phases)
        self.abilities = _Abilities()  # and its ability (a Skill Swap's, a Mummy's, ...)
        self.illusion = _Illusion()  # (switch-ins that may be an Illusion holder: left out)
        self._iact: dict = {}  # "p1a" -> the species it switched in as (the item tracker's key)

    def _capture(self) -> dict:
        def one(st: _Side) -> tuple:
            m = boost_mult(st.spe) * (2.0 if st.tailwind else 1.0) * (1.5 if st.proto else 1.0)
            return st.active, m * (0.5 if st.status.get(st.active) == "par" else 1.0)

        opp = (self.opp_side, self._iact.get(self.opp_side + "a"))
        ours = (self.our_side, self._iact.get(self.our_side + "a"))
        o = self.sides[self.opp_side]
        entry = GEN.pokedex.get(o.forme.get(o.active, o.active)) or {}
        return {"sides": {k: one(v) for k, v in self.sides.items()},
                "trick_room": self.trick_room, "weather": self.weather,
                "terrain": self.terrain, "opp_item": self.items.now.get(opp),
                "our_item": self.items.now.get(ours) if ours in self.items.changed else None,
                "opp_ab": self.abilities.now.get(opp), "our_ab": self.abilities.now.get(ours),
                "our_key": ours, "opp_base": (entry.get("baseStats") or {}).get("spe"),
                "our_forme": self.sides[self.our_side].forme.get(self.sides[self.our_side].active, ""),
                "transformed": any(s.transformed for s in self.sides.values()),
                "disguised": any(self.illusion.ambiguous.get(k + "a") for k in self.sides)}  # fmt: skip

    def _flush(self, out: list) -> None:
        """The current turn's observation, if any, into ``out``."""
        block, snap, our_side, opp_side = self.block, self.snap, self.our_side, self.opp_side
        if self.turn == 0 or snap is None:
            return
        mains = {}  # side -> (index, move) of its own (not called) first move in the turn
        for i, p in enumerate(block):
            if len(p) > 3 and p[1] == "move" and p[2][:2] in self.sides \
                    and p[2][:2] not in mains \
                    and not any(x.startswith("[from]") for x in p[4:]):  # fmt: skip
                mains[p[2][:2]] = (i, p[3])
        if our_side not in mains or opp_side not in mains:
            return
        last = max(mains[our_side][0], mains[opp_side][0])
        for p in block[:last]:  # a switch as a turn's action (not a pivot's) comes first
            if len(p) > 2 and p[1] in ("switch", "drag") and not any(
                    x.startswith("[from]") for x in p[4:]):  # fmt: skip
                return
        if any(any(it in x for it in ORDER_ITEMS) for p in block[:last] for x in p):
            return
        # (a transformed active's speed is its target's; the second mover Encored before it moved
        # used another move than it chose -- its priority unknown: a Dragon Tail's -6 into Energy
        # Ball; 2026-10-24, the belief check)
        if snap["transformed"] or snap["disguised"]:
            return
        second = our_side if mains[our_side][0] > mains[opp_side][0] else opp_side
        first_i = min(mains[our_side][0], mains[opp_side][0])
        if any(len(p) > 3 and p[1] == "-start" and p[2][:2] == second and "Encore" in p[3]
               for p in block[first_i:last]):  # fmt: skip
            return
        our_move, opp_move = mains[our_side][1], mains[opp_side][1]
        (us, us_mult), (them, them_mult) = snap["sides"][our_side], snap["sides"][opp_side]
        stat, item, ability = self.our_speed(us)
        if not stat:
            return
        # (the abilities then: the log's after a change, else the one it started with -- ours
        # left out if the log never named it; 2026-10-25 review, F1's twin: a Skill Swap after)
        # (the key the snapshot took: at the flush, the next |turn|, a faint's replacement or a
        # late pivot may be in the slot -- 2026-10-25 review)
        ours_key = snap["our_key"]
        if snap["our_ab"] is not None:
            ability = snap["our_ab"]
        elif ours_key in self.abilities.changed:
            ability = self.abilities.original.get(ours_key)
            if ability is None:
                return
        opp_abils = {snap["opp_ab"]} if snap["opp_ab"] is not None else abilities(them)
        grassy = snap["terrain"] == "grassyterrain"
        if _move_priority(our_move) != _move_priority(opp_move) \
                or _risky_priority(our_move, {ability}, grassy) \
                or _risky_priority(opp_move, opp_abils, grassy):  # fmt: skip
            return
        speedy = {WEATHER_SPEED.get(snap["weather"], "-"), "quickfeet", "unburden", "slowstart"}
        if snap["terrain"] == "electricterrain":
            speedy.add("surgesurfer")
        if (opp_abils | {ability}) & speedy:
            return
        # (Stall moves its holder last, Mycelium Might its status moves)
        for abils, move in (({ability}, our_move), (opp_abils, opp_move)):
            if "stall" in abils or "myceliummight" in abils and _status_move(move):
                return
        ours = stat * us_mult * (1.5 if item == "choicescarf" else 1.0)
        opp_first = mains[opp_side][0] < mains[our_side][0]
        out.append(Obs(self.turn, them, ours, them_mult, snap["trick_room"], opp_first, snap.get("opp_item"),
                       snap["opp_base"], stat * us_mult, us, snap["our_item"], snap["our_forme"]))  # fmt: skip

    def result(self) -> list[Obs]:
        """The observations so far, the current turn's included (if it has both moves). Those of
        an opponent's first item phase once its item changed hands: with the item it started
        with if the log revealed it, else left out -- so a caller's item is only ever that of a
        mon whose item never changed (2026-10-24, the belief check: a Switcheroo's Choice Scarf
        read at the turns before it)."""
        out = list(self.out)
        self._flush(out)
        keep = []
        for o in out:
            key = (self.opp_side, o.species)
            if o.item_then is None and key in self.items.changed:
                start = self.items.original.get(key)
                if start is None:
                    continue
                o = dataclasses.replace(o, item_then=start)
            mine = self.sides[self.our_side]
            if o.our_forme and mine.forme.get(o.our_species, o.our_species) != o.our_forme:
                continue
            # (our item then: the one the log named, the one it started with if it changed since --
            # left out if the log never said which -- else the one we hold now)
            ours_key = (self.our_side, o.our_species)
            item = o.our_item_then
            if item is None and ours_key in self.items.changed:
                item = self.items.original.get(ours_key)
                if item is None:
                    continue
            if item is None:
                item = to_id(self.our_speed(o.our_species)[1] or "")
            o = dataclasses.replace(o, ours=o.ours_raw * (1.5 if item == "choicescarf" else 1.0))
            keep.append(o)
        return keep

    def feed(self, p: list[str]) -> None:
        if len(p) < 2:
            return
        tag = p[1]
        if tag in ("switch", "drag", "replace") and len(p) > 3:
            # (replace: an Illusion broken -- the real mon's items / abilities from then)
            self._iact[p[2][:3]] = to_id(p[3].split(",")[0])
            if tag != "replace":
                self.abilities.entered((p[2][:2], self._iact[p[2][:3]]))
        self.items.feed(p, self._iact)
        self.abilities.feed(p, self._iact)
        self.illusion.feed(p)
        if tag == "turn":
            self._flush(self.out)
            self.turn, self.block, self.snap = int(p[2]), [], None
            return
        if self.snap is None and tag == "move" and not any(x.startswith("[from]") for x in p[4:]):
            self.snap = self._capture()
        self.block.append(p)
        sides = self.sides
        if tag == "-clearallboost":  # Haze
            for st in sides.values():
                st.spe = 0
        if tag == "-weather" and len(p) > 2:
            self.weather = "" if p[2] == "none" else to_id(p[2])
        elif tag == "-fieldstart" and len(p) > 2:
            f = to_id(p[2].replace("move: ", ""))
            if f == "trickroom":
                self.trick_room = True
            elif f.endswith("terrain"):
                self.terrain = f
        elif tag == "-fieldend" and len(p) > 2:
            f = to_id(p[2].replace("move: ", ""))
            if f == "trickroom":
                self.trick_room = False
            elif f == self.terrain:
                self.terrain = ""
        elif tag in ("-sidestart", "-sideend") and len(p) > 3 and "Tailwind" in p[3]:
            sides[p[2][:2]].tailwind = tag == "-sidestart"
        if len(p) < 3 or p[2][:2] not in sides:
            return
        st = sides[p[2][:2]]
        nick = p[2].split(": ", 1)[-1]
        sp = st.names.get(nick, to_id(nick))
        if tag in ("switch", "drag", "replace", "detailschange") and len(p) > 3:
            new = to_id(p[3].split(",")[0])
            st.names[nick] = new
            st.forme[new] = new
            if tag in ("switch", "drag"):
                st.active, st.spe, st.proto, st.transformed = new, 0, False, False
                hp = p[4] if len(p) > 4 else ""
                if " " in hp:
                    st.status[new] = hp.split(" ", 1)[1]
                else:
                    st.status.pop(new, None)
            else:
                st.active = new
        elif tag in ("-boost", "-unboost") and len(p) > 4 and p[3] == "spe":
            st.spe = max(-6, min(6, st.spe + int(p[4]) * (1 if tag == "-boost" else -1)))
        elif tag == "-setboost" and len(p) > 4 and p[3] == "spe":
            st.spe = int(p[4])
        elif tag == "-clearboost" or (tag == "-clearnegativeboost" and st.spe < 0):
            st.spe = 0
        elif tag == "-status" and len(p) > 3:
            st.status[sp] = p[3]
        elif tag == "-curestatus":
            st.status.pop(sp, None)
        elif tag in ("-damage", "-heal", "-sethp") and len(p) > 3 and "fnt" not in p[3]:
            # (the HP field names the status now: a Healing Wish's cure is only its -heal's;
            # 2026-10-24, the belief check -- a paralysis it cured kept)
            hp = p[3].split(" ", 1)
            if len(hp) > 1:
                st.status[sp] = hp[1]
            else:
                st.status.pop(sp, None)
        elif tag == "-formechange" and len(p) > 3:
            st.forme[sp] = to_id(p[3])
        elif tag == "-transform":
            st.transformed = True
        elif tag == "-start" and len(p) > 3 and to_id(p[3]) in ("protosynthesisspe",
                                                                 "quarkdrivespe"):  # fmt: skip
            st.proto = True
        elif tag == "-end" and len(p) > 3 and to_id(p[3]) in ("protosynthesis", "quarkdrive"):
            st.proto = False


def observations(lines: list[list[str]], our_side: str, our_speed) -> list[Obs]:
    """``our_speed(species) -> (speed stat, item id, ability id)`` of our mons."""
    tr = ObsTracker(our_side, our_speed)
    for p in lines:
        tr.feed(p)
    return tr.result()


def opp_eff(o: Obs, speed_stat: int, item: str) -> float:
    """The opponent's effective speed at ``o``: ``item`` its candidate (the one it started with),
    the observation's own once the log named another (``Obs.item_then``)."""
    it = o.item_then if o.item_then is not None else item
    return speed_stat * o.mult * (1.5 if it == "choicescarf" else 1.0)


def spe_stat(base: int, ev: int, nature: str, level: int = 100, iv: int = 31) -> int:
    """A speed stat (the damage module's calc_stats for one stat)."""
    nat = GEN.natures.get(nature, {}).get("spe", 1.0)
    return int(((2 * base + iv + ev // 4) * level // 100 + 5) * nat)


def consistent(obs: list[Obs], speed_stat: int, item: str, stat_of=None) -> bool:
    """Can an opponent mon with ``speed_stat`` and ``item`` have moved as observed? (ties: either
    order) ``stat_of(base speed)``: its speed stat in another forme (``Obs.base_spe``: the forme
    it was in then), else ``speed_stat`` at every turn."""
    for o in obs:
        stat = stat_of(o.base_spe) if stat_of is not None and o.base_spe is not None else speed_stat
        e = opp_eff(o, stat, item)
        if abs(e - o.ours) <= TIE * o.ours:  # Showdown rounds each step: near-ties are ties
            continue
        faster = e > o.ours if not o.trick_room else e < o.ours
        slower = e < o.ours if not o.trick_room else e > o.ours
        if (o.opp_first and slower) or (not o.opp_first and faster):
            return False
    return True


def battle_observations(battle) -> dict[str, list[Obs]]:
    """``observations`` of a live poke-env battle (our view: our mons' real speeds, items and
    abilities at each turn's end), by the opponent's species; the tracker kept on the battle and
    fed the messages added since the last call."""
    data = battle._replay_data
    n, tr, by = getattr(battle, "_alpha_speed_obs", (0, None, None))
    if tr is not None and n == len(data):
        return by
    if tr is None or n > len(data):

        def our_speed(sp: str) -> tuple:
            for m in battle.team.values():
                if to_id(m.species) == sp:
                    return (m.stats or {}).get("spe") or 0, m.item or "", to_id(m.ability or "")
            return 0, "", ""

        n, tr = 0, ObsTracker(battle.player_role or "p1", our_speed)
    for m in data[n:]:
        tr.feed(m)
    by = {}
    for o in tr.result():
        by.setdefault(o.species, []).append(o)
    battle._alpha_speed_obs = (len(data), tr, by)
    return by
