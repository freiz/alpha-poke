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
  taunt       move attempts (move / cant) since the Taunt; ends at the third
  encore      encored moves used; ends after the third
  yawn        ends of turn since the Yawn (sleep at the second)
  disabled    the active's move Disable blocks (-start Disable <move>; until -end)
  recharge    the active must recharge this turn (-mustrecharge; cleared by its "cant recharge",
              a move or a switch: poke-env keeps its flag until the next move)
  healblock / throatchop / magnetrise
              ends of turn since the start (2026-10-13; the patched engine ends them: Psychic
              Noise's Heal Block 2, Throat Chop 2, Magnet Rise 5)
  partiallytrapped
              ends of turn of the active's partial trap (Infestation, Whirlpool, ...; from its
              -activate to its -end; 2026-10-16, doc/engine-diff.md L13: the patched engine ends
              it at the fifth, Showdown at the fifth or the sixth)
  slowstart   the active's Slow Start: [turns left, counting]; 5 from its -start, one less at each
              end of turn from the first turn start it is in for (Showdown's counter skips the
              turn it came in; doc/engine-diff.md L77), gone at its -end
  used_once   species ids whose Dauntless Shield has raised Defense (Gen 9: once per battle;
              2026-10-16, doc/engine-diff.md L18)
  sub_hit     the active's Substitute took a hit and stands (its HP below a quarter)
  setters     who set the weather / terrain / a side's screens: (side, species id), for an
              extending item (Light Clay, Heat Rock, ...: 8 turns)
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
    yawn: int | None = None
    disabled: str | None = None  # move id
    healblock: int | None = None
    throatchop: int | None = None
    magnetrise: int | None = None
    partiallytrapped: int | None = None
    slowstart: list | None = None  # [turns left, counting]
    sub_hit: bool = False
    recharge: bool = False
    just_moved: str = ""  # species id of this side's mon that made the last move
    # what this side set: "weather" / "terrain" -> (its id, the setter's species id); a screen
    # id (reflect, lightscreen, auroraveil) -> the setter's species id
    setters: dict = field(default_factory=dict)
    fields_elapsed: dict = field(default_factory=dict)  # "weather" / "terrain" -> ends of turn
    used_once: set = field(default_factory=set)  # species ids (Dauntless Shield used)
    status: dict = field(default_factory=dict)  # species id -> status ('tox', 'slp', ...)
    sleep: dict = field(default_factory=dict)  # species id -> [attempts, rest]
    names: dict = field(default_factory=dict)  # nickname -> species id

    def came_in(self, species: str) -> None:
        self.active = species
        self.toxic = self.protect = 0
        self.protected = False
        self.confusion = self.taunt = self.encore = self.yawn = None
        self.disabled = self.healblock = self.throatchop = self.magnetrise = None
        self.partiallytrapped = self.slowstart = None
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
    elif tag == "-mustrecharge":
        st.recharge = True
    elif tag == "cant" and len(p) > 3:
        if p[3] == "recharge":
            st.recharge = False
        if p[3] == "slp" and sp in st.sleep:
            st.sleep[sp][0] += 1
        if st.taunt is not None:
            st.taunt += 1
    elif tag == "move" and len(p) > 3:
        mv = to_id(p[3])
        st.just_moved = sp
        st.recharge = False
        sides["p2" if p[2][:2] == "p1" else "p1"].just_moved = ""
        called = any(x.startswith("[from]") for x in p[4:])
        if not called:
            if st.taunt is not None:
                st.taunt += 1
            if st.encore is not None:
                st.encore += 1
        if mv == "wish" and st.wish is None and "[still]" not in p:
            st.wish = (2, sp)
    elif tag == "-fail" and len(p) > 3 and to_id(p[3].replace("move: ", "")) == "wish":
        st.wish = None
    elif tag == "-singleturn" and len(p) > 3:
        if to_id(p[3].replace("move: ", "")) in PROTECTS:
            st.protected = True
    elif tag == "-start" and len(p) > 3:
        what = to_id(p[3].replace("move: ", ""))
        if what == "confusion":
            st.confusion = 0
        elif what == "taunt":
            st.taunt = 0
        elif what == "encore":
            st.encore = 0
        elif what == "yawn":
            st.yawn = 0
        elif what == "futuresight":  # by the user: its side's attack is pending
            st.future = (3, sp)
        elif what == "disable" and len(p) > 4:
            st.disabled = to_id(p[4].replace("move: ", ""))
        elif what in ("healblock", "throatchop", "magnetrise"):
            setattr(st, what, 0)
        elif what == "substitute":
            st.sub_hit = False
        elif what == "abilityslowstart":
            st.slowstart = [5, False]
    elif tag == "-ability" and len(p) > 3 and to_id(p[3]) == "dauntlessshield":
        st.used_once.add(sp)
    elif tag == "-activate" and len(p) > 3 and to_id(p[3].replace("move: ", "")) in TRAPS:
        if st.partiallytrapped is None:  # a second trap move does not restart it
            st.partiallytrapped = 0
    elif tag == "-activate" and len(p) > 3 and to_id(p[3]) == "confusion":
        if st.confusion is not None:
            st.confusion += 1
    elif tag == "-activate" and len(p) > 4 and to_id(p[3].replace("move: ", "")) == "substitute":
        if p[4] == "[damage]":
            st.sub_hit = True
    elif tag == "-sidestart" and len(p) > 3:
        st.setters[to_id(p[3].replace("move: ", ""))] = st.just_moved
    elif tag == "-end" and len(p) > 3:
        what = to_id(p[3].replace("move: ", ""))
        if "[partiallytrapped]" in p:
            st.partiallytrapped = None
        elif what in ("confusion", "taunt", "encore", "yawn", "healblock", "throatchop",
                    "magnetrise"):  # fmt: skip
            setattr(st, what, None)
        elif what == "disable":
            st.disabled = None
        elif what == "substitute":
            st.sub_hit = False
        elif what == "slowstart":
            st.slowstart = None
        elif what == "futuresight":  # on the target: the other side's attack landed
            sides["p2" if p[2][:2] == "p1" else "p1"].future = None


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
