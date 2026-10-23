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
              "weather" / "terrain" -> ends of turn since it started (both sides keep the same
              count; 2026-10-16, doc/engine-diff.md L3: the remaining turns were reckoned from
              poke-env's start turn, which every "[upkeep]" message reset -- weather always 4
              left -- and a lead's terrain was one turn short)

Without them every search started from "just happened": a Rest sleeper about to wake stayed
asleep, toxic did 1/16 at any stage, a second Protect always worked, a pending Wish never
healed, confusion never ended (design.md, engine state gaps)."""

from dataclasses import dataclass, field

from alpha_poke.analysis.roles import to_id

TRAPS = {"bind", "wrap", "firespin", "whirlpool", "sandtomb", "magmastorm", "infestation",
         "snaptrap", "thundercage", "clamp"}  # fmt: skip
PROTECTS = {"protect", "detect", "spikyshield", "banefulbunker", "silktrap", "burningbulwark",
            "endure", "kingsshield", "obstruct"}  # fmt: skip


@dataclass
class SideTimers:
    active: str = ""  # species id of the active mon
    toxic: int = 0
    protect: int = 0
    protected: bool = False  # this turn
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
    last_failed: bool = False
    sub_hit: bool = False
    recharge: bool = False
    just_moved: str = ""  # species id of this side's mon that made the last move
    last_move: str = ""  # the battle's last move id (both sides; L167)
    # what this side set: "weather" / "terrain" -> (its id, the setter's species id); a screen
    # id (reflect, lightscreen, auroraveil) -> the setter's species id
    setters: dict = field(default_factory=dict)
    set_items: dict = field(default_factory=dict)  # a setters key -> its setter's item then
    fields_elapsed: dict = field(default_factory=dict)  # "weather" / "terrain" -> ends of turn
    used_once: set = field(default_factory=set)  # species ids (Dauntless Shield used)
    # species id -> the hits a foe's move landed on it (Rage Fist; doc/engine-diff.md L163)
    times_attacked: dict = field(default_factory=dict)
    # species id -> the moves it used once Stellar-terastallized (its types boosted once: L175)
    stellar_moves: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)  # species id -> status ('tox', 'slp', ...)
    sleep: dict = field(default_factory=dict)  # species id -> [attempts, rest]
    names: dict = field(default_factory=dict)  # nickname -> species id

    def came_in(self, species: str) -> None:
        self.active = species
        self.acted = False
        self.switched_now = True
        self.toxic = self.protect = 0
        self.protected = False
        self.confusion = self.taunt = self.encore = self.yawn = None
        self.disabled = self.healblock = self.throatchop = self.magnetrise = None
        self.partiallytrapped = self.slowstart = None
        self.trap_out = False
        self.trapped = self.frombooster = False
        self.failed_now = self.last_failed = False
        self.sub_hit = self.recharge = False

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
    tag = p[1]
    if tag == "upkeep":  # end of turn
        for st in sides.values():
            if st.status.get(st.active) == "tox":
                st.toxic += 1
            st.protect = st.protect + 1 if st.protected else 0
            st.protected = False
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
            if st.slowstart and st.slowstart[1]:
                st.slowstart[0] -= 1
                if st.slowstart[0] <= 0:
                    st.slowstart = None
        return
    if tag == "turn":
        for st in sides.values():
            st.acted = False
            st.switched_now = False
            st.last_failed, st.failed_now = st.failed_now, False
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
                    st.fields_elapsed[kind] = 0
        return
    if tag == "-fieldend" and len(p) > 2 and to_id(p[2].replace("move: ", "")).endswith("terrain"):
        for st in sides.values():
            st.fields_elapsed.pop("terrain", None)
        return
    st, sp = _who(p, sides)
    if st is None:
        return
    if tag in ("switch", "drag", "replace", "detailschange") and len(p) > 3:
        new = to_id(p[3].split(",")[0])
        st.names[p[2].split(": ", 1)[-1]] = new
        if tag in ("detailschange", "replace"):  # same mon, new form / Illusion broken
            for d in (st.status, st.sleep):
                if sp in d:
                    d[new] = d.pop(sp)
            st.active = new
            return
        st.came_in(new)
        foe = sides["p2" if p[2][:2] == "p1" else "p1"]
        foe.trapped = False  # (its trapper left)
        # (L170: a partial trap stays until its silent -end at the residual, without effect)
        foe.trap_out = foe.partiallytrapped is not None
        hp = p[4] if len(p) > 4 else ""
        if " " in hp:
            st.status[new] = hp.split(" ", 1)[1]
        elif hp:
            st.status.pop(new, None)
    elif tag == "-status" and len(p) > 3:
        st.status[sp] = p[3]
        if p[3] == "slp":
            st.sleep[sp] = [0, any("move: Rest" in x for x in p[4:])]
        if p[3] == "tox" and sp == st.active:
            # Toxic Orb poisons at the end of the turn, after the poison damage: that turn's
            # upkeep is not a tick
            st.toxic = -1 if any("Toxic Orb" in x for x in p[4:]) else 0
    elif tag == "-curestatus" and len(p) > 3:
        st.status.pop(sp, None)
        st.sleep.pop(sp, None)
    elif tag == "-cureteam":  # (older Heal Bell / Aromatherapy message: the whole side)
        st.status.clear()
        st.sleep.clear()
    elif tag == "faint":
        st.status.pop(sp, None)
        st.sleep.pop(sp, None)
        foe = sides["p2" if p[2][:2] == "p1" else "p1"]
        foe.trap_out = foe.partiallytrapped is not None  # (L170: its trapper fainted)
    elif tag == "-mustrecharge":
        st.recharge = True
    elif tag == "cant" and len(p) > 3:
        st.acted = True
        st.failed_now = p[3] != "recharge"  # (L115)
        if p[3] == "recharge":
            st.recharge = False
        if p[3] == "slp" and sp in st.sleep:
            st.sleep[sp][0] += 1
    elif tag == "-terastallize" and len(p) > 3 and to_id(p[3]) == "stellar":
        st.stellar_moves.setdefault(sp, set())
    elif tag == "move" and len(p) > 3:
        mv = to_id(p[3])
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
    elif tag == "-damage" and not any("[from]" in x for x in p[4:]) and (
        sides["p2" if p[2][:2] == "p1" else "p1"].just_moved
    ):
        st.times_attacked[sp] = st.times_attacked.get(sp, 0) + 1  # (L163: a hit of the foe's move)
    elif tag in ("-fail", "-miss") and st.just_moved:
        st.failed_now = True  # (L115: its move failed)
    elif tag == "-immune" and sides["p2" if p[2][:2] == "p1" else "p1"].just_moved:
        sides["p2" if p[2][:2] == "p1" else "p1"].failed_now = True
    elif tag == "-singleturn" and len(p) > 3:
        if to_id(p[3].replace("move: ", "")) in PROTECTS:
            st.protected = True
    elif tag == "-start" and len(p) > 3:
        what = to_id(p[3].replace("move: ", ""))
        if what == "confusion":
            st.confusion = 0
        elif what == "taunt":
            st.taunt = -1 if st.acted else 0
        elif what == "encore":
            st.encore = -1 if st.acted else 0
        elif what == "yawn":
            st.yawn = 0
        elif what == "futuresight":  # by the user: its side's attack is pending
            st.future = (3, sp)
        elif what == "disable" and len(p) > 4:
            st.disabled = to_id(p[4].replace("move: ", ""))
            cursed = any(x.startswith("[from] ability:") for x in p[5:])  # (Cursed Body)
            st.disable_ends = 1 if not st.acted or cursed else 0
        elif what in ("healblock", "throatchop", "magnetrise"):
            setattr(st, what, 0)
        elif what == "substitute":
            st.sub_hit = False
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
    elif tag == "-sidestart" and len(p) > 3:
        st.setters[to_id(p[3].replace("move: ", ""))] = st.just_moved
        st.set_items.pop(to_id(p[3].replace("move: ", "")), None)
    elif tag == "-enditem" and len(p) > 3:  # its item gone: the one its effects were set with
        _item_was(st, sp, to_id(p[3]))
    elif tag == "-item" and len(p) > 3 and any(x in ("[from] move: Trick", "[from] move: Switcheroo")
                                               for x in p[4:]):  # fmt: skip
        # a swap: the other side's active had the item this one gets
        foe = sides["p2" if p[2][:2] == "p1" else "p1"]
        _item_was(foe, foe.active, to_id(p[3]))
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
        elif what == "substitute":
            st.sub_hit = False
        elif what == "slowstart":
            st.slowstart = None
        elif what in ("protosynthesis", "quarkdrive"):
            st.frombooster = False
        elif what == "futuresight":  # on the target: the other side's attack landed
            sides["p2" if p[2][:2] == "p1" else "p1"].future = None


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
