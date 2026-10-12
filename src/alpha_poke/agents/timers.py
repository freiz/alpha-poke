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

Without them every search started from "just happened": a Rest sleeper about to wake stayed
asleep, toxic did 1/16 at any stage, a second Protect always worked, a pending Wish never
healed, confusion never ended (design.md, engine state gaps)."""

from dataclasses import dataclass, field

from alpha_poke.analysis.roles import to_id

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
    status: dict = field(default_factory=dict)  # species id -> status ('tox', 'slp', ...)
    sleep: dict = field(default_factory=dict)  # species id -> [attempts, rest]
    names: dict = field(default_factory=dict)  # nickname -> species id

    def came_in(self, species: str) -> None:
        self.active = species
        self.toxic = self.protect = 0
        self.protected = False
        self.confusion = self.taunt = self.encore = self.yawn = None

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


def timers(lines: list[list[str]]) -> dict[str, SideTimers]:
    """The counters at the end of ``lines`` (split protocol messages), per side ('p1', 'p2')."""
    sides = {"p1": SideTimers(), "p2": SideTimers()}
    for p in lines:
        if len(p) < 2:
            continue
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
            continue
        st, sp = _who(p, sides)
        if st is None:
            continue
        if tag in ("switch", "drag", "replace", "detailschange") and len(p) > 3:
            new = to_id(p[3].split(",")[0])
            st.names[p[2].split(": ", 1)[-1]] = new
            if tag in ("detailschange", "replace"):  # same mon, new form / Illusion broken
                for d in (st.status, st.sleep):
                    if sp in d:
                        d[new] = d.pop(sp)
                st.active = new
                continue
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
        elif tag == "cant" and len(p) > 3:
            if p[3] == "slp" and sp in st.sleep:
                st.sleep[sp][0] += 1
            if st.taunt is not None:
                st.taunt += 1
        elif tag == "move" and len(p) > 3:
            mv = to_id(p[3])
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
        elif tag == "-activate" and len(p) > 3 and to_id(p[3]) == "confusion":
            if st.confusion is not None:
                st.confusion += 1
        elif tag == "-end" and len(p) > 3:
            what = to_id(p[3].replace("move: ", ""))
            if what in ("confusion", "taunt", "encore", "yawn"):
                setattr(st, what, None)
            elif what == "futuresight":  # on the target: the other side's attack landed
                sides["p2" if p[2][:2] == "p1" else "p1"].future = None
    return sides


def battle_timers(battle) -> dict[str, SideTimers]:
    """``timers`` of a poke-env battle's log so far, cached on the battle (build_state runs once
    per world of a decision)."""
    data = battle._replay_data
    cached = getattr(battle, "_alpha_timers", None)
    if cached is None or cached[0] != len(data):
        cached = (len(data), timers([m for m in data if len(m) > 1]))
        battle._alpha_timers = cached
    return cached[1]
