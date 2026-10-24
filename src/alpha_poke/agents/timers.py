"""Turn counters the engine needs but poke-env does not keep (2026-10-11): read from the
battle's protocol log (``battle._replay_data``, every parsed message, live or replayed), both
sides, in poke-engine's own units (rust/patches/poke-engine-0.0.48, generate_instructions.rs):

  toxic       side_conditions.toxic_count: end-of-turn toxic ticks of the active since it came
              in (damage (count + 1) / 16; reset on switch)
  protect     side_conditions.protect: consecutive turns the active protected (the next one
              succeeds with (1/3) ** protect)
  wish        Side.wish turns: 1 at the start of the turn after Wish (heals at its end)
  future      Side.future_sight turns: 2 at the start of the turn after Future Sight, 1 before
              the turn it hits (at the end)
  sleep       per mon: move attempts while asleep (``cant slp``: logged before a Sleep Talk
              too); Rest sleep
              is rest_turns = 3 - attempts (wakes on the third), other sleep sleep_turns =
              attempts (wake chance 0, 1/3, 1/2, 1); kept across switches (Gen 9)
  confusion   volatile_status_durations: confused attempts (-activate confusion), patched
              engine: ends after 1-4 (uniform)
  taunt       as encore (doc/engine-diff.md L90: it was the move attempts since the Taunt)
  encore      ends of turn since the Encore, from -1 when its target had moved that turn (Showdown's
              duration 4); ends at the third (doc/engine-diff.md L89: it was the encored moves)
  yawn        ends of turn since the Yawn (sleep at the second)
  disabled    the active's move Disable blocks (-start Disable <move>; until -end)
  disable_ends
              ends of turn since the Disable, from 1 when its target had yet to move that turn or
              by Cursed Body (Showdown's duration 4, else 5): the engine's disable duration's
              count (2026-10-23 review: the move alone, without the volatile, was enabled again
              by the engine's next move)
  names       nickname -> species id as its switch line names it (poke-env's species: the key of
              every per-mon record); formes: its forme since a detailschange (Ogerpon's tera,
              Mimikyu-Busted); temp_forme: the active's -formechange forme (until it switches out)
  charging    the two-turn move the active is charging (-prepare; not one fired at once: -anim)
  locked      [its locking move (Outrage, Thrash, Petal Dance, Raging Fury), its uses] until the
              lock's fatigue confusion, a move of another kind, cant or a switch
  recharge    the active must recharge this turn (-mustrecharge; cleared by its "cant recharge",
              a move or a switch: poke-env keeps its flag until the next move)
  healblock / throatchop / magnetrise
              ends of turn since the start (2026-10-13; the patched engine ends them: Psychic
              Noise's Heal Block 2, Throat Chop 2, Magnet Rise 5)
  trap_out    the partial trap's source left or fainted (Showdown keeps the volatile, without effect, to its
              silent -end at the residual: left out of the engine's state; doc/engine-diff.md L170)
  partiallytrapped
              ends of turn of the active's partial trap (Infestation, Whirlpool, ...; from its
              -activate to its -end; 2026-10-16, doc/engine-diff.md L13: the patched engine ends
              it at the fifth, Showdown at the fifth or the sixth)
  frombooster the active's Protosynthesis / Quark Drive came from Booster Energy (-activate ...
              [fromitem]) until it ends or the mon leaves (doc/engine-diff.md L141)
  slowstart   the active's Slow Start: [turns left, counting]; 5 from its -start, one less at each
              end of turn from the first turn start it is in for (Showdown's counter skips the
              turn it came in; doc/engine-diff.md L77), gone at its -end
  trapped     the active is trapped by Mean Look / Block / Jaw Lock / Spirit Shackle / Anchor Shot
              (-activate trapped) until it or the other side's active leaves (doc/engine-diff.md L107)
  last_failed the active's move failed last turn (a -fail / -miss of its own, an -immune of the
              target, a cant other than recharge: Showdown's moveLastTurnResult; Temper Flare /
              Stomping Tantrum double; doc/engine-diff.md L115)
  last_move   the battle's last move, either side's (each |move| line: past its BeforeMove, a
              called move after its caller; the same on both sides): Copycat's (doc/engine-diff.md
              L167)
  stellar_moves
              species id -> the moves it used once Stellar-terastallized: the damaging ones' types
              are boosted no more (Showdown's stellarBoostedTypes; doc/engine-diff.md L175)
  used_once   species ids whose Dauntless Shield has raised Defense / Battle Bond has activated
              (Gen 9: once per battle;
              2026-10-16, doc/engine-diff.md L18)
  sub_hit     the active's Substitute took a hit and stands (its HP below a quarter)
  setters     who set the weather / terrain / a side's screens: (side, species id), for an
              extending item (Light Clay, Heat Rock, ...: 8 turns)
  set_items   what a setter's item was as it set (the setters' keys): its item changed since
              (-enditem: Knock Off, a used item; -item by Trick / Switcheroo) -- Showdown's
              duration is the setter's item's when the effect starts (durationCallback), not its
              item now (2026-10-23 review: a Light Clay Reflect knocked off read 5 turns)
  fields_elapsed
              "weather" / "terrain" / a room (Trick Room, Gravity, Magic Room, Wonder Room) -> ends
              of turn since it started
  side_elapsed
              a side's timed conditions (screens, Tailwind, Safeguard, Mist) -> ends of turn since
              they started (2026-10-23: they were reckoned from poke-env's start turn, one off at
              a forced switch after the turn's end) (both sides keep the same
              count; 2026-10-16, doc/engine-diff.md L3: the remaining turns were reckoned from
              poke-env's start turn, which every "[upkeep]" message reset -- weather always 4
              left -- and a lead's terrain was one turn short)

Without them every search started from "just happened": a Rest sleeper about to wake stayed
asleep, toxic did 1/16 at any stage, a second Protect always worked, a pending Wish never
healed, confusion never ended (design.md, engine state gaps)."""

import collections
import copy
from dataclasses import dataclass, field

from alpha_poke.analysis.roles import to_id

TRAPS = {"bind", "wrap", "firespin", "whirlpool", "sandtomb", "magmastorm", "infestation",
         "snaptrap", "thundercage", "clamp"}  # fmt: skip
LOCKING = ("outrage", "thrash", "petaldance", "ragingfury")
# the moves whose own -fail Showdown returns NOT_FAIL for (moveLastTurnResult not false: no
# failure for Stomping Tantrum; data/moves.ts)
NOT_FAIL = {"allyswitch", "batonpass", "floralhealing", "healpulse", "moonlight", "morningsun",
            "purify", "shoreup", "swallow", "synthesis", "teatime", "doubleshock", "burnup"}  # fmt: skip
# (not Shed Tail too weak: a failure; Double Shock / Burn Up without their type: null, none)
# (not Healing Wish / Lunar Dance with no one to switch to: a failure in the differential's states)
# (not Substitute: its -fail -- one up already, too weak -- is a failed move in the differential's
# Showdown states, whatever its NOT_FAIL)
# the abilities that take a move in, as their logs name them
ABSORB = {"ability: " + a for a in ("Flash Fire", "Water Absorb", "Volt Absorb", "Dry Skin",
                                    "Storm Drain", "Lightning Rod", "Motor Drive", "Sap Sipper",
                                    "Earth Eater", "Well-Baked Body", "Wind Rider")}  # fmt: skip
BLOCKERS = ("move: Psychic Terrain", "ability: Queenly Majesty", "ability: Dazzling",
            "ability: Armor Tail", "move: Misty Terrain", "move: Electric Terrain",
            "move: Safeguard")  # fmt: skip
REFLECTED = ("[from] ability: Magic Bounce", "[from] Magic Coat", "[from] move: Magic Coat")
ROOMS = {"trickroom", "gravity", "magicroom", "wonderroom"}
# the side conditions that last some turns (their ends of turn counted: side_elapsed)
TIMED_SIDE = {"reflect", "lightscreen", "auroraveil", "tailwind", "safeguard", "mist"}
PROTECTS = {"protect", "detect", "spikyshield", "banefulbunker", "silktrap", "burningbulwark",
            "endure", "kingsshield", "obstruct"}  # fmt: skip


@dataclass
class SideTimers:
    active: str = ""  # species id of the active mon
    toxic: int = 0
    protect: int = 0
    protected: bool = False  # this turn
    protected_move: str = ""  # its protection this turn (protect, banefulbunker, endure, ...)
    wish: tuple[int, str] | None = None  # (turns left, the wisher's species id)
    future: tuple[int, str] | None = None  # Future Sight pending (turns, the user's species id)
    confusion: int | None = None
    taunt: int | None = None
    encore: int | None = None
    acted: bool = False  # the active moved (or could not) this turn
    switched_now: bool = False  # the active came in this turn (a switch is its action)
    yawn: int | None = None
    disabled: str | None = None  # move id
    disable_ends: int = 0
    healblock: int | None = None
    throatchop: int | None = None
    magnetrise: int | None = None
    partiallytrapped: int | None = None
    trap_out: bool = False  # the partial trap's source left (L170: it does nothing more)
    slowstart: list | None = None  # [turns left, counting]
    frombooster: bool = False
    trapped: bool = False
    failed_now: bool = False  # this turn (last_failed at the next turn)
    changed_now: bool = False  # its last move changed a stage (not all 0: it did not fail)
    last_failed: bool = False
    sub_hit: bool = False
    recharge: bool = False
    prev: str = ""  # the last message's tag (both sides the same)
    prev_line: list = field(default_factory=list)  # the last message
    protean: bool = False  # its Protean / Libero changed its type this time in
    item_lost: bool = False  # the active lost its item this time in (Unburden)
    struggled: bool = False  # the active's last move a Struggle (the engine's STRUGGLED)
    flashfire: bool = False  # its Flash Fire took a Fire move this time in
    destinybond: bool = False  # its Destiny Bond on (until its next move)
    roosted: bool = False  # it used Roost this turn
    truant_next: bool = False  # it moved last: a Truant mon loafs next (Showdown's truant volatile)
    minimized: bool = False  # it used Minimize this time in
    uproar: int | None = None  # its Uproar's ends of turn so far
    stockpile: int = 0  # its Stockpile layers
    embargo: bool = False  # the active under Embargo (its item does nothing)
    ability_now: str = ""  # the active's ability as a move / ability changed it ("none": suppressed)
    gas_on: bool = False  # the active's Neutralizing Gas is on
    imprison: bool = False  # the active used Imprison
    turn1: bool = True  # before turn 2 starts (the leads' entries: L222)
    raised_t1: bool = False  # a stage went up on turn 1 (Showdown's statsRaisedThisTurn)
    lowered_t1: bool = False
    gastro: bool = False  # the active's ability suppressed by Gastro Acid
    cud: int = 0  # Cud Chew's counter of the berry the active ate (0: none to eat again)
    last_item: dict = field(default_factory=dict)  # species id -> its last item used up / eaten
    pp_taken: dict = field(default_factory=dict)  # species id -> Counter of PP Spite took per move
    cud_now: bool = False  # it ate one this turn
    cud_eats: bool = False  # Cud Chew is eating its berry again (the next -enditem)
    typechanged: bool = False  # its type changed this time in, while not terastallized
    tera_now: bool = False  # the active is terastallized (this time in's -terastallize / switch line)
    sub_passed: str = ""  # the species that passed its Substitute to the active (Shed Tail, Baton Pass)
    sub_on: bool = False  # the active has a Substitute (a -start, until its -end)
    # Illusion: nickname -> the HP line last shown of it (switch / damage / heal); this time in
    # ({"nick", "species", "hp" before it, "moves", "boosts"}); a disguise's nickname -> the time
    # in that was a Zoroark's (its HP before, the Zoroark's moves and boosts then); the boosts a
    # broken Illusion had (poke-env lost them with its disguise)
    hp_shown: dict = field(default_factory=dict)
    stint: dict = field(default_factory=lambda: {"nick": "", "species": "", "hp": None, "moves": [],
                                                 "boosts": {}})  # fmt: skip
    illusions: dict = field(default_factory=dict)
    illusion_boosts: dict = field(default_factory=dict)
    illusion_last: str = ""  # a broken Illusion's last move while disguised (its last used one)
    moves_by_nick: dict = field(default_factory=dict)  # nickname -> Counter of the moves its line used
    consecutive: int = 0  # the same move used again in a row (the Metronome item's count)
    ability_off: bool = False  # the active's ability swapped / suppressed this time in
    # the active came in this turn (1) or last turn (2: its first turn out), no move since (0:
    # else) -- the engine's last used move "switch" (Fake Out); poke-env's first_turn misses a
    # disguised Illusion and a mid-turn switch-in
    fresh: int = 0
    no_regen: set = field(default_factory=set)  # benched species ids that went out so (no heal)
    revived: set = field(default_factory=set)  # species ids Revival Blessing brought back
    own_last: str = ""  # the active's last move this time in, not a Struggle (a lock's move)
    future_doom: bool = False  # its pending future attack is Doom Desire
    item_new: bool = False  # the active got its item after its last move (no Choice lock by it)
    locked_exec: str = ""  # its last move line a locked continuation's (a charge's second turn)
    temp_forme: tuple | None = None  # (the active's nickname, its -formechange forme id)
    charging: str | None = None  # the two-turn move it is charging (-prepare, not fired at once)
    locked: list | None = None  # [the locking move (Outrage, ...), its uses so far]
    just_moved: str = ""  # species id of this side's mon that made the last move
    last_move: str = ""  # the battle's last move id (both sides; L167)
    # what this side set: "weather" / "terrain" -> (its id, the setter's species id); a screen
    # id (reflect, lightscreen, auroraveil) -> the setter's species id
    setters: dict = field(default_factory=dict)
    set_items: dict = field(default_factory=dict)  # a setters key -> its setter's item then
    nothing_now: bool = False  # its move did nothing this turn (protected: Showdown's null result)
    last_nothing: bool = False
    sub_failed_now: bool = False  # its status move's -fail at a Substitute this turn (S93)
    last_sub_failed: bool = False  # last turn's
    fainted_out: str = ""  # the active that fainted (its way out: no Regenerator)
    perish_fresh: bool = False  # Perish Song's silent perish3 this turn: its count 4 till the turn's end
    notarget: bool = False  # its move this turn had no target ([notarget])
    metronome_gone: bool = False  # its Metronome item lost since its last move (the volatile stays)
    in_residual: bool = False  # this end of turn's residuals under way (a future attack's hit seen)
    past_stints: list = field(default_factory=list)  # the times in before this one (stint dicts)
    pressure: set = field(default_factory=set)  # species keys with Pressure announced
    copied_from: str = ""  # the active's Transform target (the other side's species key)
    transformed_out: dict = field(default_factory=dict)  # species key -> the target it went out transformed into
    upkept: bool = False  # this turn's end passed (|upkeep|, before the next |turn|)
    swapped: set = field(default_factory=set)  # setters keys whose setter is the other side's (Court Change)
    fields_elapsed: dict = field(default_factory=dict)  # "weather" / "terrain" / ROOMS -> ends of turn
    side_elapsed: dict = field(default_factory=dict)  # TIMED_SIDE (this side's) -> ends of turn
    used_once: set = field(default_factory=set)  # species ids (Dauntless Shield used)
    # species id -> the hits a foe's move landed on it (Rage Fist; doc/engine-diff.md L163)
    times_attacked: dict = field(default_factory=dict)
    # species id -> the moves it used once Stellar-terastallized (its types boosted once: L175)
    stellar_moves: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)  # species id -> status ('tox', 'slp', ...)
    sleep: dict = field(default_factory=dict)  # species id -> [attempts, rest]
    names: dict = field(default_factory=dict)  # nickname -> species id (poke-env's: the key)
    formes: dict = field(default_factory=dict)  # nickname -> its forme since a detailschange
    alias: dict = field(default_factory=dict)  # a forme's species id -> its records' key (k())

    def came_in(self, species: str, gas: bool = False) -> None:
        # (the one going out: its ability swapped / suppressed this time in -- or a Neutralizing
        # Gas on as it goes -- no Regenerator)
        if (self.ability_off or gas) and self.active:
            self.no_regen.add(self.active)
        elif self.active and self.active != self.fainted_out:  # (out by fainting: none -- S118)
            self.no_regen.discard(self.active)
        # (out transformed: the ability it copied went out with it -- a copied Regenerator: S145)
        if self.active and self.copied_from and not (self.ability_off or gas) \
                and self.active != self.fainted_out:
            self.transformed_out[self.active] = self.copied_from
        elif self.active:
            self.transformed_out.pop(self.active, None)
        self.copied_from = ""
        self.no_regen.discard(species)
        self.fainted_out = ""
        self.ability_off = False
        self.fresh = 1
        self.active = species
        self.acted = False
        self.switched_now = True
        self.toxic = self.protect = 0
        self.protected = False
        self.protected_move = ""
        self.confusion = self.taunt = self.encore = self.yawn = None
        self.disabled = self.healblock = self.throatchop = self.magnetrise = None
        self.partiallytrapped = self.slowstart = None
        self.trap_out = False
        self.trapped = self.frombooster = False
        self.failed_now = self.last_failed = False
        self.sub_failed_now = self.last_sub_failed = False
        self.nothing_now = self.last_nothing = False
        self.sub_hit = self.recharge = False
        self.charging = self.locked = self.temp_forme = None
        self.protean = self.item_lost = self.struggled = self.flashfire = self.metronome_gone = False
        self.destinybond = self.roosted = self.truant_next = self.minimized = False
        self.uproar, self.stockpile = None, 0
        self.embargo = self.sub_on = self.gastro = self.imprison = False
        self.raised_t1 = self.lowered_t1 = False
        self.illusion_last = ""
        self.cud, self.cud_now = 0, False
        self.typechanged = False
        self.tera_now = False
        self.ability_now = ""
        self.illusion_boosts = {}
        self.sub_passed = ""
        self.consecutive, self.own_last = 0, ""
        self.item_new = False
        self.locked_exec = ""

    def k(self, species: str) -> str:
        """The key of a mon's records for a species id poke-env gives (a forme of ours: the
        request's details follow it)."""
        return self.alias.get(species, species)

    def rekey(self, old: str, new: str) -> None:
        """A mon's species key changed (a switch line's new details): its records follow."""
        for d in (self.status, self.sleep, self.times_attacked, self.stellar_moves, self.last_item,
                  self.pp_taken):  # fmt: skip
            if old in d:
                d[new] = d.pop(old)
        for st in (self.revived, self.no_regen, self.used_once):
            if old in st:
                st.discard(old)
                st.add(new)
        # (a forme mapped to the old key maps to the new; the new one is its own key now --
        # 2026-10-23: a Mimikyu-Busted switched back in still mapped to "mimikyu")
        self.alias = {a: new if v == old else v for a, v in self.alias.items() if a != new}

    def rest_sleep(self, species: str) -> tuple[int, int]:
        """(rest_turns, sleep_turns) of an asleep mon."""
        attempts, rest = self.sleep.get(species, (0, False))
        return (max(1, 3 - attempts), 0) if rest else (0, min(attempts, 3))


def _who(p: list[str], sides: dict) -> tuple[SideTimers | None, str]:
    """The side and species id of an ident ("p1a: Nick")."""
    if len(p) < 3 or len(p[2]) < 3 or p[2][:2] not in sides:
        return None, ""
    st = sides[p[2][:2]]
    nick = p[2].split(": ", 1)[-1]
    return st, st.names.get(nick, to_id(nick))


def _feed(sides: dict, p: list[str]) -> None:
    """One protocol message into the counters (``timers`` / ``TimerTracker``)."""
    if len(p) < 2:
        return
    try:
        _feed_one(sides, p)
    finally:
        if p[1] not in ("debug", ""):
            for st in sides.values():
                st.prev = p[1]
                st.prev_line = p


def _feed_one(sides: dict, p: list[str]) -> None:
    tag = p[1]
    if tag == "upkeep":  # end of turn
        for st in sides.values():
            st.upkept = True
            st.perish_fresh = st.in_residual = False  # (the residuals over: S126)
            st.just_moved = ""  # (no move's effects after the turn's end: a switch-in's Wind Rider -- S87)
            if st.status.get(st.active) == "tox":
                st.toxic += 1
            st.protect = st.protect + 1 if st.protected else 0
            st.protected = False
            st.protected_move = ""
            if st.wish is not None:
                st.wish = (st.wish[0] - 1, st.wish[1]) if st.wish[0] > 1 else None
            if st.future is not None:
                st.future = (st.future[0] - 1, st.future[1]) if st.future[0] > 1 else None
            if st.yawn is not None:
                st.yawn += 1
            if st.encore is not None:
                st.encore += 1
            if st.taunt is not None:
                st.taunt += 1
            if st.disabled is not None:
                st.disable_ends += 1
            for k in ("healblock", "throatchop", "magnetrise", "partiallytrapped"):
                if getattr(st, k) is not None:
                    setattr(st, k, getattr(st, k) + 1)
            for k in st.fields_elapsed:
                st.fields_elapsed[k] += 1
            for k in st.side_elapsed:
                st.side_elapsed[k] += 1
            st.roosted = False
            if st.cud:  # (eaten this turn: 1 at its start -- in the residuals, no count down then)
                st.cud = 1 if st.cud_now else st.cud - 1
            st.cud_now = False
            if st.locked and st.status.get(st.active) == "slp":
                st.locked = None  # (lockedmove's residual: asleep then -- a Lum Berry before, not)
            # (its ability's own counter: none counted under a Neutralizing Gas / Gastro Acid --
            # its residual suppressed; S74)
            if st.slowstart and st.slowstart[1] and not (st.gastro or any(s.gas_on for s in sides.values())):
                st.slowstart[0] -= 1
                if st.slowstart[0] <= 0:
                    st.slowstart = None
        return
    if tag == "turn":
        for st in sides.values():
            st.turn1 = p[2:3] == ["1"]
            st.fresh = 2 if st.fresh == 1 else 0  # (in last turn: its first turn out now)
            st.acted = st.upkept = st.in_residual = False
            st.switched_now = False
            st.last_failed, st.failed_now = st.failed_now, False
            st.last_sub_failed, st.sub_failed_now = st.sub_failed_now, False
            st.last_nothing, st.nothing_now = st.nothing_now, False
            st.just_moved = ""  # (a new turn: a -fail from now is not its last move's)
            if st.slowstart:
                st.slowstart[1] = True
        return
    if tag in ("-weather", "-fieldstart") and len(p) > 2 and "[upkeep]" not in p:
        what = to_id(p[2].replace("move: ", ""))
        if tag == "-weather" or what.endswith("terrain"):
            kind = "weather" if tag == "-weather" else "terrain"
            _set_by(sides, p, kind, what)
            for st in sides.values():
                if what == "none":
                    st.fields_elapsed.pop(kind, None)
                else:
                    # (started in this end of turn's residuals -- a Future Sight's hit, Seed
                    # Sower: Showdown's residual handlers were gathered before, this end of turn
                    # does not count it; S126)
                    st.fields_elapsed[kind] = -1 if st.in_residual else 0
        elif what in ROOMS:  # (its ends of turn: 2026-10-23, the state-construction
            # differential -- poke-env's start turn was one off after an end of turn the turn
            # number had not passed yet: a forced switch at the end of the turn)
            for st in sides.values():
                st.fields_elapsed[what] = 0
        return
    if tag == "-fieldend" and len(p) > 2:
        what = to_id(p[2].replace("move: ", ""))
        for st in sides.values():
            st.fields_elapsed.pop("terrain" if what.endswith("terrain") else what, None)
        return
    if tag == "-message" and len(p) > 2 and p[2].startswith("Sleep Clause Mod activated"):
        mover = next((s for s in sides.values() if s.just_moved), None)
        pl = next(iter(sides.values())).prev_line
        if mover is not None and not (pl[1:2] == ["-end"] and "Yawn" in "".join(pl[3:4])) \
                and _is_status(mover.last_move):  # (not an Effect Spore's at its contact: S108)
            # (not a Yawn's sleep at the turn's end: S90)
            _missed(mover)  # (its sleep move stopped by the clause: a failed move)
        return
    if tag == "-swapsideconditions":  # (Court Change: the conditions and their counts swap)
        a, b = sides["p1"], sides["p2"]
        a.side_elapsed, b.side_elapsed = b.side_elapsed, a.side_elapsed
        for k in TIMED_SIDE | {"spikes", "toxicspikes", "stealthrock", "stickyweb"}:
            sa, sb = a.setters.pop(k, None), b.setters.pop(k, None)
            ia, ib = a.set_items.pop(k, None), b.set_items.pop(k, None)
            if sb is not None:
                a.setters[k] = sb
            if sa is not None:
                b.setters[k] = sa
            if ib is not None:
                a.set_items[k] = ib
            if ia is not None:
                b.set_items[k] = ia
            # (its setter is of the other side now -- or back to its own: a species of both
            # teams, a Dragapult each, read the wrong one's Light Clay; S73)
            wa, wb = k in a.swapped, k in b.swapped
            a.swapped.discard(k)
            b.swapped.discard(k)
            if sb is not None and not wb:
                a.swapped.add(k)
            if sa is not None and not wa:
                b.swapped.add(k)
        return
    if tag == "-clearallboost":  # (Haze: no mon named -- a broken Illusion's carried changes too: S125)
        for s2 in sides.values():
            s2.stint["boosts"] = {}
            s2.illusion_boosts = {}
    st, sp = _who(p, sides)
    if st is None:
        return
    nick = p[2].split(": ", 1)[-1] if len(p) > 2 else ""
    if tag in ("-damage", "-heal", "-sethp") and len(p) > 3 and p[2][2:3] in ("a", ":"):
        st.hp_shown[nick] = p[3]  # (its HP as last shown: a disguise's before its Zoroark came)
    # (this time in's stage changes: a broken Illusion's go to the Zoroark)
    if tag in ("-boost", "-unboost") and len(p) > 4 and p[4].lstrip("-").isdigit() and sp == st.active:
        b = st.stint["boosts"]
        b[p[3]] = b.get(p[3], 0) + (int(p[4]) if tag == "-boost" else -int(p[4]))
        if st.turn1 and int(p[4]) > 0:  # (L222's turn-1 marks: a change happened, whatever since)
            if tag == "-boost":
                st.raised_t1 = True
            else:
                st.lowered_t1 = True
    if tag in ("-clearboost", "-clearallboost", "-clearnegativeboost"):
        for s2 in (sides.values() if tag == "-clearallboost" else [st]):
            s2.stint["boosts"] = {}
            # (a broken Illusion's stage changes too -- White Herb's negative ones: S113)
            s2.illusion_boosts = {} if tag != "-clearnegativeboost" else \
                {k: v for k, v in s2.illusion_boosts.items() if v > 0}
    if tag in ("switch", "drag", "replace", "detailschange") and len(p) > 3:
        new = to_id(p[3].split(",")[0])
        if tag == "detailschange":
            # (a forme change: the species key stays -- an opponent's poke-env species stays too,
            # ours follows the request's details: k() maps a forme to the key -- the forme apart;
            # 2026-10-23, the state-construction differential: the key moved, the last item /
            # sleep / status kept under it were not found again)
            st.formes[nick] = new
            if nick in st.names and new != st.names[nick]:
                st.alias[new] = st.names[nick]
            if len(p) > 4 and p[4]:
                st.hp_shown[nick] = p[4]
            return
        old_key = st.names.get(nick)
        if tag in ("switch", "drag") and old_key and old_key != new:
            st.rekey(old_key, new)  # (its details changed -- Palafin-Hero: poke-env's species too)
        st.names[nick] = new
        st.formes.pop(nick, None)
        replaced = st.stint.get("records", {})  # (the disguise's records before this time in)
        if tag == "replace":  # an Illusion broken: this time in was the Zoroark's (Illusion)
            st.illusions[st.stint["nick"]] = dict(st.stint)
            for dsp, before in st.stint.get("items", []):  # (the items it used: the Zoroark's)
                used = st.last_item.get(dsp)
                if before is None:
                    st.last_item.pop(dsp, None)
                else:
                    st.last_item[dsp] = before
                if used:
                    st.last_item[new] = used
            st.illusion_boosts = dict(st.stint["boosts"])
            st.illusion_last = st.stint["moves"][-1] if st.stint["moves"] else ""
            st.stint = {"nick": nick, "species": new, "hp": None, "moves": [], "boosts": {}}
        if tag == "replace":  # the Illusion broken: the Zoroark's now
            # (its disguise's records this time in: the disguise's key -- the replace line names
            # the Zoroark; S109: a badly poisoned disguise's count lost)
            # (only what this time in changed: the disguise's own records from before stay --
            # a real Suicune's Rest under the same key; S123)
            before = replaced
            for name, d in (("status", st.status), ("sleep", st.sleep)):
                if st.active in d and st.active != new:
                    was = before.get(name)
                    now = d.pop(st.active)
                    if was is not None:
                        d[st.active] = was
                    if now != was:
                        d[new] = now
            st.active = new
            if len(p) > 4 and p[4]:
                st.hp_shown[nick] = p[4]
            return
        passer = st.active
        # (a Neutralizing Gas on as it goes out: the other active's, or its own -- gone with it)
        foe_side = sides["p2" if p[2][:2] == "p1" else "p1"]
        st.came_in(new, foe_side.gas_on)
        st.gas_on = False
        st.tera_now = "tera:" in p[3]
        if nick in st.illusions:  # (it is out again itself -- or so: its HP shown again)
            st.illusions[nick] = dict(st.illusions[nick], hp="")
        # this time in (an Illusion's disguise shows the mon it copies: its HP before is kept)
        st.past_stints.append(st.stint)  # (S127: a disguise's time in found out later)
        st.stint = {"nick": nick, "species": new, "hp": st.hp_shown.get(nick), "moves": [],
                    "boosts": {}, "records": {"status": st.status.get(new),  # (its records before: S123)
                                              "sleep": copy.deepcopy(st.sleep.get(new))},
                    "max": p[4].split(" ")[0].split("/")[-1] if len(p) > 4 else ""}  # fmt: skip
        if len(p) > 4:
            st.hp_shown[nick] = p[4]
        if any(x in ("[from] Shed Tail", "[from] Baton Pass") for x in p[4:]):
            st.sub_passed = passer  # (the Substitute it passed: the incoming mon's -- if any)
        foe = sides["p2" if p[2][:2] == "p1" else "p1"]
        foe.trapped = False  # (its trapper left)
        # (L170: a partial trap stays until its silent -end at the residual, without effect)
        foe.trap_out = foe.partiallytrapped is not None
        hp = p[4] if len(p) > 4 else ""
        if " " in hp:
            st.status[new] = hp.split(" ", 1)[1]
        elif hp:
            st.status.pop(new, None)
    elif tag == "-formechange" and len(p) > 3:
        # a forme until it switches out (Cramorant's Gorging, Aegislash's Blade, Minior's Meteor):
        # the engine's species (2026-10-23, the state-construction differential: poke-env keeps
        # the species it came in as)
        st.temp_forme = (p[2].split(": ", 1)[-1], to_id(p[3].split(",")[0]))
        if st.names.get(st.temp_forme[0]) and st.temp_forme[1] != st.names[st.temp_forme[0]]:
            st.alias[st.temp_forme[1]] = st.names[st.temp_forme[0]]
    elif tag == "-damage" and "[from] confusion" in p:
        st.acted = True  # (it hit itself: its action this turn -- Encore / Taunt's count)
        st.failed_now = True  # (and a failed one: Showdown's moveThisTurnResult false)
        st.fresh = 0
        st.locked = None  # (a lock's turn lost: it ends)
        # (its move aborted: a charge's second turn and Destiny Bond end -- onMoveAborted; Truant
        # ran before: a loaf next; S75)
        st.charging = None
        st.destinybond = False
        if not (st.gastro or any(s.gas_on for s in sides.values())):  # (suppressed: kept -- S114)
            st.truant_next = True
    elif tag == "-damage" and not any("[from]" in x for x in p[4:]) and (
        sides["p2" if p[2][:2] == "p1" else "p1"].just_moved
    ):
        st.times_attacked[sp] = st.times_attacked.get(sp, 0) + 1  # (L163: a hit of the foe's move)
    elif tag == "-status" and len(p) > 3:
        st.status[sp] = p[3]
        pass
        if p[3] == "slp":
            st.sleep[sp] = [0, any("move: Rest" in x for x in p[4:])]
        if p[3] == "tox" and sp == st.active:
            # Toxic Orb poisons at the end of the turn, after the poison damage: that turn's
            # upkeep is not a tick
            st.toxic = -1 if any("Toxic Orb" in x for x in p[4:]) else 0
    elif tag == "-curestatus" and len(p) > 3:
        st.status.pop(sp, None)
        st.sleep.pop(sp, None)
        if st.just_moved == sp and st.prev in ("-boost", "-unboost") and st.failed_now:
            st.failed_now = False  # (Take Heart at +6 curing its status did something: S106)
    elif tag == "-cureteam":  # (older Heal Bell / Aromatherapy message: the whole side)
        st.status.clear()
        st.sleep.clear()
    elif tag == "faint":
        st.no_regen.add(sp)  # (out by fainting: no Regenerator -- a Revival Blessing's mon: S118)
        if sp == st.active:
            st.fainted_out = sp
            st.sub_on, st.sub_passed = False, ""  # (its Substitute gone with it: S92)
        st.status.pop(sp, None)
        st.sleep.pop(sp, None)
        foe = sides["p2" if p[2][:2] == "p1" else "p1"]
        if sp == st.active:
            foe.trapped = False  # (its trapper fainted: L107's trap ends)
        foe.trap_out = foe.partiallytrapped is not None  # (L170: its trapper fainted)
    elif tag == "-mustrecharge":
        st.recharge = True
    elif tag == "-prepare" and len(p) > 3:
        st.charging = to_id(p[3])
    elif tag == "-anim" and len(p) > 3 and st.charging == to_id(p[3]):
        st.charging = None  # (fired at once: Solar Beam in the sun, Power Herb)
    elif tag == "cant" and len(p) > 3 and any(x.startswith("[of] ") for x in p[4:]):
        # an ability stopping a foe's move (Armor Tail, Dazzling, Queenly Majesty, Damp): Showdown's
        # cant names the holder, [of] the mover -- the mover's move failed, the holder did nothing
        # (2026-10-23, the state-construction differential: read as the holder's stopped action)
        ost, _ = _who(["", "", next(x[5:] for x in p[4:] if x.startswith("[of] "))], sides)
        if ost is not None:
            _missed(ost)
    elif tag == "cant" and len(p) > 3:
        st.acted = True
        st.fresh = 0  # (an action, stopped: Showdown's activeMoveActions -- its last move none now)
        # (Truant's onBeforeMove -- priority 9 -- ran before a flinch, Disable, paralysis, ...:
        # its volatile on, a loaf next; not after a recharge, sleep, freeze -- before it -- nor its
        # own loaf; S75)
        if not (st.gastro or any(s.gas_on for s in sides.values())):  # (suppressed: kept -- S114)
            st.truant_next = to_id(p[3].replace("ability: ", "")) not in ("slp", "frz", "recharge", "truant")
        st.charging = st.locked = None  # (prevented: the charge and the lock end)
        st.destinybond = False  # (its onMoveAborted: S65)
        st.failed_now = p[3] != "recharge"  # (L115)
        if p[3] == "recharge":
            st.recharge = False
        if p[3] == "slp" and sp in st.sleep:
            st.sleep[sp][0] += 1
    elif tag == "-terastallize" and len(p) > 3:
        if sp == st.active:
            st.tera_now = True
        st.revived.discard(sp)  # (terastallized after it was brought back: S69)
        nick = p[2].split(": ", 1)[-1]
        if st.temp_forme and st.temp_forme[0] == nick and st.temp_forme[1] == "morpekohangry":
            # (a Morpeko terastallized in its Hangry forme keeps it -- Showdown's terastallize sets
            # its baseSpecies, silently: S67)
            st.formes[nick] = st.temp_forme[1]
        if to_id(p[3]) == "stellar":
            st.stellar_moves.setdefault(sp, set())
    elif tag == "move" and len(p) > 3 and any(x in REFLECTED for x in p[4:]):
        # a status move reflected (Magic Bounce, Magic Coat): not its reflector's action; the
        # move its user chose failed (Showdown's moveLastTurnResult -- 2026-10-23, the
        # state-construction differential: it read as the reflector's own move)
        foe = sides["p2" if p[2][:2] == "p1" else "p1"]
        foe.failed_now = True
        foe.just_moved = ""
        # (the reflected move's result is its reflector's this turn -- Showdown's useMove --
        # until a move of its own: a -fail after it is the reflector's)
        st.just_moved, st.failed_now = sp, False
    elif tag == "move" and len(p) > 3:
        mv = to_id(p[3])
        st.locked_exec = mv if any("lockedmove" in x for x in p[4:]) else ""
        st.notarget = "[notarget]" in p
        st.metronome_gone = False
        if not any(x.startswith("[from]") and "lockedmove" not in x for x in p[4:]):
            st.stint["moves"].append(mv)  # (this time in's moves: a disguised Illusion's are its own)
            # (and the PP each took -- a Pressure foe's 2: a broken Illusion's PP, S143)
            st.stint.setdefault("costs", []).append(_pp_cost(sides, p, mv))
            st.moves_by_nick.setdefault(nick, collections.Counter())[mv] += 1
        st.changed_now = False
        st.destinybond = False
        st.fresh = 0
        if mv != "struggle":  # (a Struggle locks no move of its set: S72)
            st.item_new = False
        # (a Truant mon loafs the turn after a move -- not one its ability was suppressed for, a
        # Neutralizing Gas, Gastro Acid: its onBeforeMove adds the volatile; S71)
        if not (st.gastro or any(s.gas_on for s in sides.values())):  # (suppressed: kept -- S114)
            st.truant_next = True
        if mv == "minimize":
            st.minimized = True
        if not any(x.startswith("[from]") and "lockedmove" not in x for x in p[4:]):
            # (the Metronome item's count: the same move again after one that did not fail)
            st.consecutive = st.consecutive + 1 if mv == st.own_last and not st.last_failed \
                and not st.last_nothing else 0
            if mv != "struggle" and not any("lockedmove" in x for x in p[4:]):
                st.own_last = mv  # (the move it chose: a called move's caller -- Metronome's -- stays)
        # (a charge fires the turn after its -prepare; a locking move locks it, its next uses
        # "[from]lockedmove" -- 2026-10-23, the state-construction differential: neither was in
        # the engine's state, the search let it choose any move)
        st.struggled = mv == "struggle"  # (L232's volatile: the last action a Struggle)
        if st.charging is not None and "[still]" not in p:
            st.charging = None
        # (a called one -- Copycat's, Metronome's -- locks too: S117)
        if mv in LOCKING and not any(x.startswith("[from]") and "lockedmove" not in x
                                     and not x.startswith("[from] move:") for x in p[4:]):
            # (a continuation says [from] lockedmove; one without is a new lock -- the last one
            # may have ended silently, confused: S96)
            going = st.locked and st.locked[0] == mv and any("lockedmove" in x for x in p[4:])
            st.locked = [mv, (st.locked[1] if going else 0) + 1]
            if st.locked[1] >= 3:
                st.locked = None  # (its last turn: 3 at most -- its fatigue silent when confused)
        elif not any("lockedmove" in x for x in p[4:]):
            st.locked = None
        if sp in st.stellar_moves:
            st.stellar_moves[sp].add(mv)
        st.just_moved = sp
        st.acted = True
        st.failed_now = False
        st.recharge = False
        sides["p2" if p[2][:2] == "p1" else "p1"].just_moved = ""
        for s in sides.values():
            s.last_move = mv
        if mv == "wish" and st.wish is None and "[still]" not in p:
            st.wish = (2, sp)
    elif tag == "-fail" and len(p) > 3 and to_id(p[3].replace("move: ", "")) == "wish":
        st.wish = None
        st.failed_now = True
    elif tag in ("-boost", "-unboost") and len(p) > 4 and not any(x.startswith("[from]") for x in p[5:]) \
            and next(iter(sides.values())).prev in ("move", "-boost", "-unboost"):
        # (the move's own stage changes: right after its line -- not an ability's after it,
        # Speed Boost's at the end of the turn)
        # a status move's stage changes all 0 (Swords Dance at +6): it failed (Showdown's
        # moveLastTurnResult; no -fail logged -- 2026-10-23, the state-construction differential);
        # one that changed a stage did not (Dragon Dance at +6 Attack, +1 Speed)
        mover = next((s for s in sides.values() if s.just_moved), None)
        if mover is not None and _is_status(mover.last_move):
            if p[4] == "0" and not mover.changed_now:
                mover.failed_now = True
            elif p[4] != "0":
                mover.failed_now, mover.changed_now = False, True
    elif tag == "-fail" and any(s.just_moved and s.last_move in NOT_FAIL and not s.notarget
                                for s in sides.values()):  # (no target: a failure all the same, S129)
        pass  # (Showdown's NOT_FAIL: its -fail is not a failed move -- Synthesis at full HP)
    elif tag == "-fail" and len(p) == 3 and any(
            s.just_moved and _blocked_by_sub(s.last_move)
            and (sides["p2" if k == "p1" else "p1"].sub_on or sides["p2" if k == "p1" else "p1"].sub_passed)
            # (Yawn checks its target's status first -- its onTryHit, before the Substitute: a
            # statused one's -fail is a failure; S104)
            and not (s.last_move == "yawn" and (o := sides["p2" if k == "p1" else "p1"]).status.get(o.active))
            for k, s in sides.items()):  # fmt: skip
        # (a status move at a Substitute: its onTryPrimaryHit's null, not a failure -- unless an
        # Infiltrator's went through it and failed on its target: the log is the same, the
        # world's ability decides -- S93)
        for s in sides.values():
            if s.just_moved:
                s.sub_failed_now = True
    elif tag == "-fail" and st.prev == "-activate" and any(x.startswith("ability:") for x in st.prev_line[3:4]):
        pass  # (an ability's own failure -- Synchronize passing a burn to a Fire type -- not a move's)
    elif tag in ("-immune", "-miss") and any(s.just_moved and s.own_last == "perishsong"
                                             for s in sides.values()):  # fmt: skip
        pass  # (Perish Song: a target immune or missed is no failure -- its onHitField's result
        # true; 2026-10-23, S64: Good as Gold's -immune read as a failed Perish Song)
    elif tag == "-fail" and len(p) > 3 and p[3] == "unboost" and any(x.startswith("[from] ability:") for x in p[4:]) \
            and st.prev_line[1:2] != ["-ability"] \
            and (mover := sides["p2" if p[2][:2] == "p1" else "p1"]).just_moved and _is_status(mover.last_move) \
            and mover.last_move not in ("defog", "partingshot", "memento", "toxicthread", "spicyextract",
                                        "venomdrench", "strengthsap", "topsyturvy"):  # (more than a drop)
        _missed(mover)  # (a status move's only effect, a drop, all blocked -- Clear Body at a Tickle: S141)
    elif tag == "-fail" and st.just_moved == sp and _is_status(st.last_move) and "unboost" not in p \
            and any(x.startswith("[from] ability:") for x in p[3:]):  # (not an Intimidate's: S142)
        _missed(st)  # (its own ability stopping its own move -- Rest under Insomnia: S107)
    elif tag in ("-fail", "-miss") and not any(x.startswith("[from]") for x in p[3:]):
        # (L115: the last move failed -- its user's: the side that just moved; a -fail names its
        # target as often, a Toxic on a poisoned foe: 2026-10-23, the state-construction
        # differential -- it was the target's side, which had not just moved; a [from] one is an
        # ability stopping an effect, not the move)
        mover = next((s for s in sides.values() if s.just_moved), None)
        if mover is not None:
            _missed(mover)
            if mover.own_last in PROTECTS:
                mover.protect = 0  # (a failed protection: Showdown removes the stall count at once)
    elif tag == "-block" and len(p) > 3 and p[3].startswith("ability:") \
            and sides["p2" if p[2][:2] == "p1" else "p1"].just_moved \
            and _is_status(sides["p2" if p[2][:2] == "p1" else "p1"].last_move):  # (not a hit's
        # secondary -- Psychic Noise's Heal Block: S133)
        # (an ability blocking the foe's move -- Aroma Veil's Taunt / Encore: it failed; S91)
        _missed(sides["p2" if p[2][:2] == "p1" else "p1"])
    elif tag == "-immune" and sides["p2" if p[2][:2] == "p1" else "p1"].just_moved \
            and st.prev_line[1:2] != ["-ability"] \
            and not (st.prev_line[1:2] == ["-activate"] and "".join(st.prev_line[3:4]).startswith("ability:")):
        # (not an ability's effect -- an Intimidate a Substitute stopped: S77; a Synchronize's
        # status at a Fire type: S105)
        _missed(sides["p2" if p[2][:2] == "p1" else "p1"])
    elif tag in ("-start", "-heal", "-boost", "-ability") and sides["p2" if p[2][:2] == "p1" else "p1"].just_moved \
            and any(x.replace("[from] ", "") in ABSORB or "ability: " + x in ABSORB for x in p[3:5]) \
            and (tag != "-heal" or any(x.startswith("[of] ") for x in p[4:])) \
            and not any(x.startswith("[from] move:") for x in p[4:]):  # (an ability changed by a
        # move -- Simple Beam's |Simple|Dry Skin|: its old one named, not absorbing; S112)
        # (-ability|X|Wind Rider|boost: the boosting ones' own form; an absorbing heal names the
        # mover -- [of] --, Dry Skin's in the rain at the turn's end does not: 2026-10-23, S63)
        # the foe's move absorbed by an ability (Flash Fire, Water Absorb, Storm Drain, ...):
        # it failed as against an immunity (2026-10-23, the state-construction differential)
        _missed(sides["p2" if p[2][:2] == "p1" else "p1"])
        if "ability: Flash Fire" in p[3:]:
            st.flashfire = True
    elif tag == "-activate" and len(p) > 5 and to_id(p[3].replace("move: ", "")) in ("spite", "eeriespell") \
            and p[5].isdigit():
        # (Spite took that much PP of its last move -- poke-env does not track it; 2026-10-23)
        st.pp_taken.setdefault(sp, collections.Counter())[to_id(p[4])] += int(p[5])
    elif tag == "-activate" and len(p) > 3 and to_id(p[3]) == "abilitycudchew":
        st.cud_eats = True
    elif tag == "-activate" and len(p) > 3 and p[3] in BLOCKERS \
            and sides["p2" if p[2][:2] == "p1" else "p1"].just_moved and st.prev_line[1:2] != ["-end"]:
        # (a priority move stopped -- Psychic Terrain, Queenly Majesty, Dazzling, Armor Tail: the
        # foe's move failed; 2026-10-23, the state-construction differential; a status stopped by
        # Misty / Electric Terrain, Safeguard too -- not a Yawn's sleep at the turn's end: S89)
        _missed(sides["p2" if p[2][:2] == "p1" else "p1"])
    elif tag == "-activate" and len(p) > 3 and ("[broken]" in p or to_id(p[3]) == "movefeint"):
        # its protection broken (Feint, Phantom Force, ...): Gen 6+ deletes the stall counter
        # (Showdown's battle-actions; 2026-10-23, the state-construction differential)
        st.protected = False
        st.protect = 0
        st.protected_move = ""  # (its volatile gone too: S78)
    elif tag == "-activate" and len(p) > 3 and to_id(p[3].replace("move: ", "")) in PROTECTS:
        # (its target protected: the move did nothing -- a lock does not start; its result null,
        # not false: the Metronome item's count ends -- S120)
        mover = sides["p2" if p[2][:2] == "p1" else "p1"]
        if mover.just_moved:
            mover.nothing_now = True
        if mover.just_moved and mover.locked:
            mover.locked = None
    elif tag == "-singleturn" and len(p) > 3:
        if to_id(p[3].replace("move: ", "")) in PROTECTS:
            st.protected = True
            st.protected_move = to_id(p[3].replace("move: ", ""))
            # (Baneful Bunker, King's Shield, Spiky Shield, ... log "Protect": the move used --
            # its own volatile; 2026-10-23, the state-construction differential)
            pl = st.prev_line
            if st.protected_move == "protect" and len(pl) > 3 and pl[1] == "move" and pl[2] == p[2] \
                    and to_id(pl[3]) in PROTECTS - {"detect"}:  # (Detect: protect)
                st.protected_move = to_id(pl[3])
        if to_id(p[3].replace("move: ", "")) == "roost":
            st.roosted = True  # (its Flying type off for the rest of the turn)
    elif (tag == "-activate" and len(p) > 3 and to_id(p[3].replace("move: ", "")) == "skillswap") \
            or tag == "-endability" or (tag == "-ability" and any(
                x.startswith(("[from] ability: Mummy", "[from] ability: Wandering Spirit",
                              "[from] ability: Lingering Aroma", "[from] move:")) for x in p[4:])):
        # (its ability changed / suppressed: a Regenerator gone till it switches -- Skill Swap
        # names both: the [of] one's too)
        st.ability_off = True
        st.protean = False  # (its ability's state anew: Protean's use gone -- S116)
        of = next((x[5:] for x in p[4:] if x.startswith("[of] ")), None)
        ost = _who(["", "", of], sides)[0] if of is not None else None
        if ost is not None:
            ost.ability_off = True
            ost.protean = False
        # its ability now, till it switches out (2026-10-23, the state-construction differential:
        # poke-env keeps no temporary ability for a Simple Beam / Worry Seed / Skill Swap / Mummy
        # change, a Gastro Acid suppression none -- the engine's ability)
        if tag == "-endability":
            st.ability_now, st.gastro = "none", True
        elif tag == "-ability":
            st.ability_now = to_id(p[3])
        elif len(p) > 5 and not p[4].startswith("["):  # Skill Swap: its source gets the first
            st.ability_now = to_id(p[4])
            if ost is not None and not p[5].startswith("["):
                ost.ability_now = to_id(p[5])
    elif tag == "-transform" and len(p) > 3:
        st.copied_from = _who(["", "", p[3]], sides)[1]  # (S145)
    elif tag == "-ability" and len(p) == 4 and to_id(p[3]) == "pressure":
        st.pressure.add(sp)  # (announced on its entry: S143)
    elif tag == "-ability" and len(p) > 3 and to_id(p[3]) == "neutralizinggas" and len(p) == 4:
        st.gas_on = True
    elif tag == "-heal" and "[from] move: Revival Blessing" in p:
        st.revived.add(sp)  # (back from a faint: no longer terastallized -- Showdown's)
    elif tag == "-heal" and "[from] move: Lunar Dance" in p:
        # (Gen 9's Lunar Dance restores the PP too -- poke-env's count restored, agents/
        # poke_env_fixes.py; Spite's taken PP back as well: S84)
        st.pp_taken.pop(sp, None)
    elif tag == "-start" and len(p) > 3 and p[3] == "perish3" and "[silent]" in p and sp == st.active:
        st.perish_fresh = True  # (Showdown's duration 4 till this end of turn: S128)
    elif tag == "-singlemove" and len(p) > 3 and to_id(p[3]) == "destinybond":
        st.destinybond = True  # (until its next move: Gen 7+ keeps it past the turn's end)
    elif tag == "-start" and len(p) > 3:
        what = to_id(p[3].replace("move: ", ""))
        if what == "embargo":
            st.embargo = True
        if what == "imprison":
            st.imprison = True  # (its moves are the foe's no more: the engine's volatile)
        if what == "uproar":  # (its ends of turn: the [upkeep] -start each turn it goes on)
            st.uproar = st.uproar + 1 if "[upkeep]" in p and st.uproar is not None else 0
        if what.startswith("stockpile") and what[9:].isdigit():
            st.stockpile = int(what[9:])
        if what == "typechange" and not st.tera_now:
            st.typechanged = True  # (a type change before it terastallized; none after -- setType)
        if what == "typechange" and any(x in ("[from] ability: Protean", "[from] ability: Libero")
                                        for x in p[4:]):  # fmt: skip
            st.protean = True  # (L218: used this time in; the log says so, poke-env may not)
        if what == "confusion" and "[fatigue]" in p:
            st.locked = None  # (the lock's last turn)
        if what == "confusion":
            st.confusion = 0
        elif what == "taunt":
            st.taunt = -1 if st.acted else 0
        elif what == "encore":
            st.encore = -1 if st.acted else 0
        elif what == "yawn":
            st.yawn = 0
        elif what in ("futuresight", "doomdesire"):  # by the user: its side's attack is pending
            st.future = (3, sp)
            st.future_doom = what == "doomdesire"  # (Doom Desire's own: L218; was never tracked)
        elif what == "disable" and len(p) > 4:
            st.disabled = to_id(p[4].replace("move: ", ""))
            cursed = any(x.startswith("[from] ability:") for x in p[5:])  # (Cursed Body)
            st.disable_ends = 1 if not st.acted or cursed else 0
        elif what in ("healblock", "throatchop", "magnetrise"):
            setattr(st, what, 0)
        elif what == "substitute":
            st.sub_hit = False
            st.sub_on = True
        elif what == "abilityslowstart":
            st.slowstart = [5, False]
    elif tag == "-ability" and len(p) > 3 and to_id(p[3]) in ("dauntlessshield", "supersweetsyrup",
                                                                 "intrepidsword"):  # fmt: skip
        st.used_once.add(sp)  # (L172: Supersweet Syrup's once per battle too; L184: Intrepid Sword)
    elif tag == "-activate" and len(p) > 3 and to_id(p[3]) in ("abilityprotosynthesis",
                                                              "abilityquarkdrive"):  # fmt: skip
        st.frombooster = "[fromitem]" in p
    elif tag == "-activate" and len(p) > 3 and to_id(p[3]) == "abilitybattlebond":
        st.used_once.add(sp)  # (L111: once per battle too)
    elif tag == "-activate" and len(p) > 3 and to_id(p[3].replace("move: ", "")) in TRAPS:
        if st.partiallytrapped is None:  # a second trap move does not restart it
            st.partiallytrapped = 0
        st.trap_out = False
    elif tag == "-activate" and len(p) > 3 and to_id(p[3]) == "trapped":
        st.trapped = True
    elif tag == "-activate" and len(p) > 3 and to_id(p[3]) == "confusion":
        if st.confusion is not None:
            st.confusion += 1
    elif tag == "-activate" and len(p) > 4 and to_id(p[3].replace("move: ", "")) == "substitute":
        if p[4] == "[damage]":
            st.sub_hit = True
    elif tag == "-sideend" and len(p) > 3:
        st.side_elapsed.pop(to_id(p[3].replace("move: ", "")), None)
    elif tag == "-sidestart" and len(p) > 3 and to_id(p[3].replace("move: ", "")) in TIMED_SIDE:
        st.side_elapsed[to_id(p[3].replace("move: ", ""))] = 0  # (its ends of turn, as ROOMS)
        st.setters[to_id(p[3].replace("move: ", ""))] = st.just_moved
        st.swapped.discard(to_id(p[3].replace("move: ", "")))
        st.set_items.pop(to_id(p[3].replace("move: ", "")), None)
        if "magicroom" in st.fields_elapsed or st.embargo:
            # (its item suppressed as it set it -- Magic Room, Embargo: no Light Clay; Showdown's
            # hasItem; 2026-10-23, the state-construction differential)
            st.set_items[to_id(p[3].replace("move: ", ""))] = ""
    elif tag == "-sidestart" and len(p) > 3:
        st.setters[to_id(p[3].replace("move: ", ""))] = st.just_moved
        st.swapped.discard(to_id(p[3].replace("move: ", "")))
        st.set_items.pop(to_id(p[3].replace("move: ", "")), None)
    elif tag == "-enditem" and len(p) > 3:  # its item gone: the one its effects were set with
        _item_was(st, sp, to_id(p[3]))
        if "[eat]" in p and sp == st.active:  # (Cud Chew's counter, if it has it: Showdown's 2)
            if st.prev == "-activate" and st.cud_eats:  # (Cud Chew's own second eating: no more)
                st.cud, st.cud_now = 0, False
            else:
                st.cud, st.cud_now = 2, True
        st.cud_eats = False
        # its last item (Showdown's lastItem: an item used up -- useItem -- or eaten -- eatItem;
        # not one taken -- Knock Off, Trick, Thief, Bug Bite: [from] / [silent] -- nor a popped Air
        # Balloon, its item just cleared): Harvest, Recycle, Cud Chew read it (L57, L178, L204)
        # (a gem's -enditem says [from] gem: used up too)
        if ("[eat]" in p or "[from] gem" in p or "[from] move: Fling" in p
                or not any(x.startswith(("[from]", "[silent]")) for x in p[4:])) \
                and to_id(p[3]) != "airballoon":
            st.stint.setdefault("items", []).append((sp, st.last_item.get(sp)))
            st.last_item[sp] = to_id(p[3])
        if sp == st.active:  # (Unburden's: an item lost this time in -- silent in the log)
            st.item_lost = True
            # (the Metronome item's volatile stays till its next move tries -- its onTryMove: S132)
            st.metronome_gone = to_id(p[3]) == "metronome"
        if any(x in ("[from] move: Trick", "[from] move: Switcheroo") for x in p[4:]):
            # (a swap where it gets none: the other mon had none -- Showdown's trick logs an
            # -enditem for a side left empty-handed; 2026-10-23 review: an itemless setter given
            # a Light Clay read it as its own)
            foe = sides["p2" if p[2][:2] == "p1" else "p1"]
            _item_was(foe, foe.active, "")
    elif tag == "-item" and len(p) > 3 and any(x in ("[from] move: Trick", "[from] move: Switcheroo")
                                               for x in p[4:]):  # fmt: skip
        # a swap: the other side's active had the item this one gets
        foe = sides["p2" if p[2][:2] == "p1" else "p1"]
        _item_was(foe, foe.active, to_id(p[3]))
        foe.item_lost = True  # (its item taken -- no -enditem for a swap: Unburden's, S102)
        if sp == st.active:
            # (an item again: Unburden's volatile stays -- its speed only while itemless, the
            # engine's L226; S102)
            st.item_new = True  # (a Choice item got after its move locks nothing: L228)
    elif tag == "-item" and len(p) > 4 and p[4].removeprefix("[from] ") in GAINS:
        # an item taken / given / found: only by an empty-handed mon -- it had none; the mon it
        # came from ([of]: Magician, Covet, Thief, Pickpocket, Bestow) had it (2026-10-23 review:
        # an itemless Reflect setter stealing a Light Clay after read 8 turns)
        _item_was(st, sp, "")
        if sp == st.active:  # (Unburden's volatile stays: S102)
            st.item_new = True
        if p[4] in ("[from] ability: Harvest", "[from] move: Recycle"):
            st.last_item.pop(sp, None)  # (its last item back: Showdown clears lastItem)
        of = next((x[5:] for x in p[5:] if x.startswith("[of] ")), None)
        if of is not None:
            ost, osp = _who(["", "", of], sides)
            if ost is not None:
                _item_was(ost, osp, to_id(p[3]))
    elif tag == "-end" and len(p) > 3 and to_id(p[3].replace("move: ", "")) in ("futuresight", "doomdesire"):
        # (its hit at the end of the turn: not the last move's -- an -immune after it is not a
        # failed move; 2026-10-23, the state-construction differential)
        for s in sides.values():
            s.just_moved = ""
            s.in_residual = True  # (the end of turn's residuals: S126)
        sides["p2" if p[2][:2] == "p1" else "p1"].future = None
    elif tag == "-end" and len(p) > 3:
        what = to_id(p[3].replace("move: ", ""))
        if "[partiallytrapped]" in p:
            st.partiallytrapped = None
            st.trap_out = False
        elif what in ("confusion", "taunt", "encore", "yawn", "healblock", "throatchop",
                    "magnetrise"):  # fmt: skip
            setattr(st, what, None)
        elif what == "disable":
            st.disabled = None
        elif what == "uproar":
            st.uproar = None
        elif what == "embargo":
            st.embargo = False
        elif what == "abilityneutralizinggas":
            st.gas_on = False
            # (the others' abilities start again: Truant's onStart puts its volatile on one that
            # moved this turn or will not move -- the turn's end; S76)
            for o in sides.values():
                if o is not st and o.active and (o.acted or o.upkept) and not o.gastro:
                    o.truant_next = True
        elif what == "stockpile":
            st.stockpile = 0
        elif what == "substitute":
            st.sub_hit = False
            st.sub_on = False
            st.sub_passed = ""
        elif what == "slowstart":
            st.slowstart = None
        elif what in ("protosynthesis", "quarkdrive"):
            st.frombooster = False
        elif what == "futuresight":  # on the target: the other side's attack landed
            sides["p2" if p[2][:2] == "p1" else "p1"].future = None


# -item sources that give an item to a mon holding none (Frisk's -item is a reveal, Trick /
# Switcheroo a swap: their own branches)
GAINS = {"ability: Magician", "ability: Pickpocket", "move: Covet", "move: Thief", "move: Bestow",
         "ability: Harvest", "ability: Pickup", "move: Recycle", "move: G-Max Replenish"}  # fmt: skip


def _missed(st: SideTimers) -> None:
    """Its move failed (missed, the target immune): no lock starts by it (Showdown's lockedmove
    is the move's self effect, on a hit; 2026-10-23, the state-construction differential: an
    Outrage on a Fairy read as locked)."""
    st.failed_now = True
    if st.locked:
        st.locked = None  # (any use that did nothing: the lock's self effect not applied)


def _blocked_by_sub(move: str) -> bool:
    """A move a Substitute stops (at the foe, not bypassing it): a status one's -fail at it is
    not a failed move."""
    from poke_env.data import GenData

    d = GenData.from_gen(9).moves.get(move) or {}
    return d.get("category") == "Status" and d.get("target") in (
        "normal", "any", "adjacentFoe", "randomNormal") and not (d.get("flags") or {}).get("bypasssub")  # fmt: skip


# (poke-env's _pressure_on: the move targets Pressure reaches)
_PRESSURED = ("all", "allAdjacent", "allAdjacentFoes", "any", "normal", "randomNormal", "scripted")


def _pp_cost(sides: dict, p: list[str], mv: str) -> int:
    """The PP a move use takes: 2 at an active foe with Pressure (announced, not suppressed --
    poke-env's rule, Gastro Acid and Neutralizing Gas apart), else 1."""
    from poke_env.data import GenData

    d = GenData.from_gen(9).moves.get(mv) or {}
    if not (d.get("target") in _PRESSURED or "mustpressure" in d.get("flags", {})):
        return 1
    foe = sides["p2" if p[2][:2] == "p1" else "p1"]
    if any(s.gas_on for s in sides.values()) or foe.gastro or foe.active not in foe.pressure:
        return 1
    return 2


def _is_status(move: str) -> bool:
    from poke_env.data import GenData

    return (GenData.from_gen(9).moves.get(move) or {}).get("category") == "Status"


def _item_was(st: SideTimers, sp: str, item: str) -> None:
    """``sp`` (of side ``st``) held ``item`` until now: the item of what it set and has not
    changed its item since."""
    for k, v in st.setters.items():
        who = v[1] if isinstance(v, tuple) else v
        if who == sp and k not in st.set_items:
            st.set_items[k] = item


def _set_by(sides: dict, p: list[str], kind: str, what: str) -> None:
    """The setter of a weather / terrain (``kind``): the mon of ``[of] <ident>`` (an ability),
    else the mon that just moved; kept in its side's ``setters`` (the other side's dropped)."""
    of = next((x[5:] for x in p[3:] if x.startswith("[of] ")), None)
    for st in sides.values():
        st.setters.pop(kind, None)
    if of is not None:
        st, sp = _who(["", "", of], sides)
    else:
        st, sp = next(((st, st.just_moved) for st in sides.values() if st.just_moved),
                      (None, ""))  # fmt: skip
    if st is not None and what != "none":
        st.setters[kind] = (what, sp)
        st.set_items.pop(kind, None)
        if "magicroom" in st.fields_elapsed or (st.embargo and sp == st.active):
            st.set_items[kind] = ""  # (its item suppressed as it set it)


def timers(lines: list[list[str]]) -> dict[str, SideTimers]:
    """The counters at the end of ``lines`` (split protocol messages), per side ('p1', 'p2')."""
    sides = {"p1": SideTimers(), "p2": SideTimers()}
    for p in lines:
        _feed(sides, p)
    return sides


def battle_timers(battle) -> dict[str, SideTimers]:
    """``timers`` of a poke-env battle's log so far, kept on the battle and fed the messages
    added since the last call."""
    data = battle._replay_data
    n, sides = getattr(battle, "_alpha_timers", (0, None))
    if sides is None or n > len(data):
        n, sides = 0, {"p1": SideTimers(), "p2": SideTimers()}
    for m in data[n:]:  # incremental: only the new messages (2026-10-11: re-reading the whole
        # log at every decision was 9% of a policy-only worker)
        if len(m) > 1:
            _feed(sides, m)
    battle._alpha_timers = (len(data), sides)
    return sides
