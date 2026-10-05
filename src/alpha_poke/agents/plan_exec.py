"""Executable game plans: condition language, plan state machine, plan score terms.

A plan (from the LLM or from rules) is turned into *directives* the action layer can execute:

  roles         our mon -> lead | hazard_setter | hazard_removal | pivot | wallbreaker |
                win_condition | sacrifice_ok | check | utility
  assignments   their mon -> {primary, backup, avoid[]}: who switches in / must not
  kill_priority their mons to remove first
  phases        [{name, until: <condition>, goals: [<goal>]}] advanced by a state machine
  tera          {who, when: <condition>, never_before: <phase name>}
  rules         [{if: <condition>, then: <action>}]

Condition language (evaluated every turn; AND binds tighter than OR, no parentheses; any atom
may be prefixed with NOT):
  fainted:X  alive:X  active:X  our_active:X  their_hp_below:X:0.5  our_hp_below:X:0.5
  our_hazard_set:stealthrock  their_hazard_set:spikes  their_tera:X  their_tera_used
  our_tera_used  revealed_item:X:Item Name  revealed_move:X:Move Name  turn_after:N
  secures_ko  saves_from_ko   (tera context only; evaluated by the action layer)
Goals: set_hazard:<hazard> clear_hazards chip:X ko:X setup:Y sweep:Y status:X scout
Rule actions: switch_to:Y  use_move:Move Name  tera_now  setup

X / Y are species names as written in the plan (display names); ``Names`` maps them to the
poke-env species keys of our / their Pokemon.
"""

import re
from dataclasses import dataclass, field

from poke_env.battle import SideCondition

from alpha_poke.analysis.roles import to_id

HAZARD_IDS = {
    "stealthrock": SideCondition.STEALTH_ROCK,
    "spikes": SideCondition.SPIKES,
    "toxicspikes": SideCondition.TOXIC_SPIKES,
    "stickyweb": SideCondition.STICKY_WEB,
}
REMOVAL_IDS = {"rapidspin", "defog", "mortalspin", "tidyup", "courtchange"}
ROLES = {
    "lead",
    "hazard_setter",
    "hazard_removal",
    "pivot",
    "wallbreaker",
    "win_condition",
    "sacrifice_ok",
    "check",
    "utility",
}
ATOMS = {
    "fainted": 1,
    "alive": 1,
    "active": 1,
    "our_active": 1,
    "their_hp_below": 2,
    "our_hp_below": 2,
    "our_hazard_set": 1,
    "their_hazard_set": 1,
    "their_tera": 1,
    "their_tera_used": 0,
    "our_tera_used": 0,
    "revealed_item": 2,
    "revealed_move": 2,
    "turn_after": 1,
    "secures_ko": 0,
    "saves_from_ko": 0,
    "their_boosted": 2,  # their_boosted:X:N = X has >= N positive Atk/SpA/Spe stages
}
GOALS = {
    "set_hazard": 1,
    "clear_hazards": 0,
    "chip": 1,
    "ko": 1,
    "setup": 1,
    "sweep": 1,
    "status": 1,
    "scout": 0,
    "stop_setup": 1,  # stop THEIR X's boosting: phaze / Haze / Encore / Taunt / status / KO
    "heal": 1,  # keep YOUR Y healthy with its recovery
    "remove_item": 1,  # Knock Off / Trick THEIR X's item
}
OPEN_GOALS = ("sweep", "scout", "stop_setup", "heal")  # never "done": do not close a phase
HOW = {"phaze", "haze", "encore", "taunt", "status", "ko", "unaware", "revenge"}
ANTI_SETUP_IDS = {
    "roar",
    "whirlwind",
    "dragontail",
    "circlethrow",
    "haze",
    "clearsmog",
    "encore",
    "taunt",
    "willowisp",
    "thunderwave",
    "glare",
    "nuzzle",
    "perishsong",
    "spectralthief",
}
ACTIONS = {"switch_to": 1, "use_move": 1, "tera_now": 0, "setup": 0}

# score weights of the plan terms (in the same "HP-fraction swing" units as tactical scores)
W = {
    "goal_hazard": 0.25,
    "goal_clear": 0.25,
    "goal_chip": 0.15,
    "goal_ko": 0.25,
    "goal_setup": 0.3,
    "goal_sweep": 0.15,
    "goal_status": 0.15,
    "kill_priority": 0.12,
    "assign_primary": 0.3,
    "assign_backup": 0.15,
    "assign_avoid": -0.35,
    "sacrifice_stay": -0.1,
    "wincon_hidden": -0.1,
    "wincon_endgame": 0.15,
    "rule": 0.5,
    "rule_move": 0.4,
    "goal_stop_setup": 0.35,
    "goal_heal": 0.2,
    "goal_remove_item": 0.2,
    "setup_answer": 0.4,
}


class PlanError(ValueError):
    pass


@dataclass
class Atom:
    kind: str
    args: tuple[str, ...]
    negated: bool = False


@dataclass
class Condition:
    """OR of ANDs of atoms; an empty condition is never true (``None`` = absent)."""

    clauses: list[list[Atom]]
    text: str

    @classmethod
    def parse(cls, text: str) -> "Condition":
        clauses = []
        for part in re.split(r"\s+OR\s+", text.strip()):
            atoms = []
            for raw in re.split(r"\s+AND\s+", part.strip()):
                negated = raw.strip().upper().startswith("NOT ")
                if negated:
                    raw = raw.strip()[4:]
                kind, *args = [x.strip() for x in raw.split(":")]
                if kind not in ATOMS:
                    raise PlanError(f"unknown condition {kind!r} in {text!r}")
                if len(args) != ATOMS[kind]:
                    raise PlanError(f"{kind} needs {ATOMS[kind]} argument(s) in {text!r}")
                atoms.append(Atom(kind, tuple(args), negated))
            clauses.append(atoms)
        return cls(clauses, text)

    def names(self) -> set[str]:
        out = set()
        for clause in self.clauses:
            for a in clause:
                if a.kind in (
                    "fainted",
                    "alive",
                    "active",
                    "our_active",
                    "their_hp_below",
                    "our_hp_below",
                    "their_tera",
                    "revealed_item",
                    "revealed_move",
                    "their_boosted",
                ):
                    out.add(a.args[0])
        return out


def _parse_item(text: str, table: dict[str, int], what: str) -> tuple[str, tuple[str, ...]]:
    kind, *args = [x.strip() for x in text.split(":")]
    if kind not in table:
        raise PlanError(f"unknown {what} {kind!r}")
    if len(args) != table[kind]:
        raise PlanError(f"{what} {kind} needs {table[kind]} argument(s)")
    return kind, tuple(args)


@dataclass
class Names:
    ours: dict[str, str]  # display name -> poke-env species key
    theirs: dict[str, str]

    def our(self, name: str) -> str | None:
        return self.ours.get(name)

    def their(self, name: str) -> str | None:
        return self.theirs.get(name)

    def any(self, name: str) -> tuple[str, str] | None:
        if name in self.ours:
            return "ours", self.ours[name]
        if name in self.theirs:
            return "theirs", self.theirs[name]
        return None


@dataclass
class Phase:
    name: str
    until: Condition | None
    goals: list[tuple[str, tuple[str, ...]]]


@dataclass
class ExecPlan:
    names: Names
    roles: dict[str, str] = field(default_factory=dict)  # our key -> role
    assignments: dict[str, dict] = field(default_factory=dict)  # their key -> {primary,...}
    kill_priority: list[str] = field(default_factory=list)  # their keys
    phases: list[Phase] = field(default_factory=list)
    tera_who: str | None = None  # our key
    tera_when: Condition | None = None
    tera_never_before: str | None = None
    rules: list[tuple[Condition, tuple[str, tuple[str, ...]]]] = field(default_factory=list)
    # their setup threat key -> {"who": our key or None, "how": one of HOW}
    setup_answers: dict[str, dict] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, names: Names) -> "ExecPlan":
        """Validate a plan dict; anything that cannot be executed is dropped and recorded."""
        p = cls(names)

        def check_names(cond: Condition, where: str) -> bool:
            bad = [n for n in cond.names() if names.any(n) is None]
            if bad:
                p.problems.append(f"{where}: unknown Pokemon {bad}")
            return not bad

        for mon, role in (d.get("roles") or {}).items():
            key = names.our(mon)
            if key is None or role not in ROLES:
                p.problems.append(f"roles: dropped {mon}={role}")
            else:
                p.roles[key] = role
        for mon, a in (d.get("assignments") or {}).items():
            key = names.their(mon)
            if key is None or not isinstance(a, dict):
                p.problems.append(f"assignments: dropped {mon}")
                continue
            entry = {
                "primary": names.our(a.get("primary") or ""),
                "backup": names.our(a.get("backup") or ""),
                "avoid": [names.our(x) for x in (a.get("avoid") or []) if names.our(x)],
            }
            p.assignments[key] = entry
        p.kill_priority = [names.their(x) for x in (d.get("kill_priority") or []) if names.their(x)]
        for i, ph in enumerate(d.get("phases") or []):
            goals = []
            for g in ph.get("goals") or []:
                try:
                    kind, args = _parse_item(g, GOALS, "goal")
                except PlanError as e:
                    p.problems.append(f"phase {i}: {e}")
                    continue
                if args and kind not in ("set_hazard",) and names.any(args[0]) is None:
                    p.problems.append(f"phase {i}: unknown Pokemon in goal {g!r}")
                    continue
                goals.append((kind, args))
            until = None
            if ph.get("until"):
                try:
                    until = Condition.parse(ph["until"])
                    if not check_names(until, f"phase {i} until"):
                        until = None
                except PlanError as e:
                    p.problems.append(f"phase {i}: {e}")
            p.phases.append(Phase(str(ph.get("name") or f"phase{i}"), until, goals))
        for mon, a in (d.get("setup_answers") or {}).items():
            key = names.their(mon)
            if key is None or not isinstance(a, dict):
                p.problems.append(f"setup_answers: dropped {mon}")
                continue
            how = str(a.get("how") or "").lower()
            p.setup_answers[key] = {
                "who": names.our(a.get("who") or ""),
                "how": how if how in HOW else "ko",
            }
        tera = d.get("tera") or {}
        if tera.get("who"):
            p.tera_who = names.our(tera["who"])
            if p.tera_who is None:
                p.problems.append(f"tera: unknown {tera['who']!r}")
        if tera.get("when"):
            try:
                p.tera_when = Condition.parse(tera["when"])
            except PlanError as e:
                p.problems.append(f"tera.when: {e}")
        p.tera_never_before = tera.get("never_before")
        for i, r in enumerate(d.get("rules") or []):
            try:
                cond = Condition.parse(r["if"])
                action = _parse_item(r["then"], ACTIONS, "action")
                if action[0] == "switch_to" and names.our(action[1][0]) is None:
                    raise PlanError(f"unknown Pokemon in {r['then']!r}")
                if check_names(cond, f"rule {i}"):
                    p.rules.append((cond, action))
            except (PlanError, KeyError, TypeError) as e:
                p.problems.append(f"rule {i}: {e}")
        return p


# ---- evaluation --------------------------------------------------------------------------
def _mon(battle, side: str, key: str):
    team = battle.team if side == "ours" else battle.opponent_team
    for m in team.values():
        if m.species == key:
            return m
    if side == "theirs":
        for m in battle.teampreview_opponent_team or []:
            if m.species == key:
                return m
    return None


def eval_atom(a: Atom, battle, names: Names, tera_ctx: dict | None = None) -> bool:
    k, args = a.kind, a.args
    if k in ("secures_ko", "saves_from_ko"):
        return bool(tera_ctx and tera_ctx.get(k))
    if k == "turn_after":
        return battle.turn > int(args[0])
    if k == "their_tera_used":
        return any(m.is_terastallized for m in battle.opponent_team.values())
    if k == "our_tera_used":
        return any(m.is_terastallized for m in battle.team.values())
    if k in ("our_hazard_set", "their_hazard_set"):
        sc = HAZARD_IDS.get(to_id(args[0]))
        conds = battle.opponent_side_conditions if k == "our_hazard_set" else battle.side_conditions
        return sc is not None and sc in conds
    ref = names.any(args[0])
    if ref is None:
        return False
    side, key = ref
    mon = _mon(battle, side, key)
    if k == "fainted":
        return bool(mon and mon.fainted)
    if k == "alive":
        return bool(mon is None or not mon.fainted)
    if k == "active":
        opp = battle.opponent_active_pokemon
        return side == "theirs" and opp is not None and opp.species == key
    if k == "our_active":
        me = battle.active_pokemon
        return side == "ours" and me is not None and me.species == key
    if k in ("their_hp_below", "our_hp_below"):
        return bool(mon and mon.current_hp_fraction < float(args[1]))
    if k == "their_tera":
        return bool(mon and mon.is_terastallized)
    if k == "revealed_item":
        return bool(mon and mon.item and to_id(mon.item) == to_id(args[1]))
    if k == "revealed_move":
        return bool(mon and to_id(args[1]) in mon.moves)
    if k == "their_boosted":
        try:
            n = int(float(args[1]))
        except ValueError:
            return False
        return bool(mon and boosted_stages(mon) >= n)
    return False


def _stops_setup(move, ctx: dict, opp) -> bool:
    """An answer to a (possibly) boosting opponent: an anti-setup move, or an attack that KOs."""
    if move.id in ANTI_SETUP_IDS:
        return True
    from alpha_poke.agents.damage import is_damaging

    return is_damaging(move) and ctx.get("damage", 0) >= ctx.get("opp_hp", 1)


def boosted_stages(mon) -> int:
    return sum(max(0, mon.boosts.get(s, 0)) for s in ("atk", "spa", "spe"))


def eval_condition(c: Condition | None, battle, names: Names, tera_ctx=None) -> bool:
    if c is None:
        return False
    return any(
        all(eval_atom(a, battle, names, tera_ctx) != a.negated for a in clause)
        for clause in c.clauses
    )


@dataclass
class PlanState:
    """Runtime state of an ExecPlan within one battle."""

    plan: ExecPlan
    phase: int = 0
    log: list[str] = field(default_factory=list)  # phase changes / repairs (for traces)
    matchup: dict = field(default_factory=dict)  # (our key, their key) -> 1v1 score
    # outcome metrics (filled by observe(); reported in the arena log)
    goals_done: list = field(default_factory=list)  # "T12 ko:Toxapex"
    assign_won: int = 0  # their mon fainted while facing its assigned answer
    assign_lost: int = 0  # assigned answer fainted while facing that mon
    wincon_kos: int = 0  # their faints while one of our win conditions was active
    _prev: tuple = ()  # (our active, their active, our fainted set, their fainted set)

    @property
    def phase_name(self) -> str:
        return self.plan.phases[self.phase].name if self.plan.phases else ""

    def goals(self):
        return self.plan.phases[self.phase].goals if self.plan.phases else []

    def goal_done(self, goal, battle) -> bool:
        kind, args = goal
        names = self.plan.names
        if kind == "set_hazard":
            sc = HAZARD_IDS.get(to_id(args[0]))
            return sc is not None and sc in battle.opponent_side_conditions
        if kind == "clear_hazards":
            return not any(c in battle.side_conditions for c in HAZARD_IDS.values())
        if kind in ("ko", "chip", "status"):
            ref = names.any(args[0])
            mon = _mon(battle, *ref) if ref else None
            if mon is None:
                return False
            if kind == "ko":
                return mon.fainted
            if kind == "chip":
                return mon.fainted or mon.current_hp_fraction < 0.5
            return mon.status is not None or mon.fainted
        if kind == "setup":
            ref = names.any(args[0])
            mon = _mon(battle, *ref) if ref else None
            return bool(mon and (mon.fainted or max(mon.boosts.values(), default=0) >= 2))
        if kind == "remove_item":
            ref = names.any(args[0])
            mon = _mon(battle, *ref) if ref else None
            return bool(mon and (mon.fainted or mon.item == ""))
        return False  # sweep / scout / stop_setup / heal: open-ended

    def observe(self, battle) -> None:
        """Outcome bookkeeping: goal completion, assignment results, win-condition KOs."""
        for i, ph in enumerate(self.plan.phases):
            for g in ph.goals:
                tag = f"{g[0]}:{':'.join(g[1])}" if g[1] else g[0]
                if (
                    i <= self.phase
                    and not any(x.endswith(" " + tag) for x in self.goals_done)
                    and g[0] not in OPEN_GOALS
                    and self.goal_done(g, battle)
                ):
                    self.goals_done.append(f"T{battle.turn} {tag}")
        ours_f = {m.species for m in battle.team.values() if m.fainted}
        theirs_f = {m.species for m in battle.opponent_team.values() if m.fainted}
        if self._prev:
            me, opp, prev_ours_f, prev_theirs_f = self._prev
            assigned = self.plan.assignments.get(opp, {}).get("primary") if opp else None
            if opp in theirs_f - prev_theirs_f:
                if me is not None and me == assigned:
                    self.assign_won += 1
                if self.plan.roles.get(me) == "win_condition":
                    self.wincon_kos += 1
            if me in ours_f - prev_ours_f and me is not None and me == assigned:
                self.assign_lost += 1
        me = battle.active_pokemon.species if battle.active_pokemon else None
        opp = battle.opponent_active_pokemon.species if battle.opponent_active_pokemon else None
        self._prev = (me, opp, ours_f, theirs_f)

    def update(self, battle) -> None:
        """Advance phases (several at once if needed) and repair broken assignments."""
        self.observe(battle)
        while self.phase < len(self.plan.phases) - 1:
            ph = self.plan.phases[self.phase]
            closable = [g for g in ph.goals if g[0] not in OPEN_GOALS]
            done = closable and all(self.goal_done(g, battle) for g in closable)
            if eval_condition(ph.until, battle, self.plan.names) or done:
                self.phase += 1
                why = "until" if not done else "goals done"
                self.log.append(f"T{battle.turn}: phase -> {self.phase_name} ({why})")
            else:
                break
        self._repair(battle)

    def _repair(self, battle) -> None:
        alive = {m.species for m in battle.team.values() if not m.fainted}
        for their, a in self.plan.assignments.items():
            if a.get("primary") and a["primary"] not in alive:
                if a.get("backup") in alive:
                    self.log.append(
                        f"T{battle.turn}: {their} primary {a['primary']} fainted -> "
                        f"backup {a['backup']}"
                    )
                    a["primary"], a["backup"] = a["backup"], None
                else:
                    best = self._best_alive_answer(their, alive, a.get("avoid", []))
                    self.log.append(f"T{battle.turn}: {their} answers fainted -> reassigned {best}")
                    a["primary"] = best
        wincons = [k for k, r in self.plan.roles.items() if r == "win_condition"]
        if wincons and not any(w in alive for w in wincons) and "wincon_lost" not in self.log:
            self.log.append("wincon_lost")

    def _best_alive_answer(self, their: str, alive: set[str], avoid: list[str]) -> str | None:
        """Local repair: best remaining mon by the computed matchup table (score > 0)."""
        cands = [(self.matchup.get((o, their), 0.0), o) for o in alive if o not in avoid]
        cands = [c for c in cands if c[0] > 0]
        return max(cands)[1] if cands else None

    def in_endgame(self) -> bool:
        return any(g[0] in ("sweep", "setup") for g in self.goals())

    def tera_allowed(self, battle, me_key: str, tera_ctx: dict) -> bool:
        """Tera directive, applied softly: the designated mon may tera before ``never_before``
        when it secures a KO or saves it from one; once the designated mon has fainted, any mon
        may tera under the same 'secures / saves' test."""
        p = self.plan
        urgent = bool(tera_ctx.get("secures_ko") or tera_ctx.get("saves_from_ko"))
        if p.tera_who is not None and p.tera_who != me_key:
            if sum(not m.fainted for m in battle.team.values()) == 1:
                return True
            who = _mon(battle, "ours", p.tera_who)
            return bool(who is not None and who.fainted and urgent)
        if p.tera_never_before:
            names = [ph.name for ph in p.phases]
            if p.tera_never_before in names and self.phase < names.index(p.tera_never_before):
                return urgent
        if p.tera_when is not None:
            return eval_condition(p.tera_when, battle, p.names, tera_ctx)
        return True

    def active_rules(self, battle) -> list[tuple[str, tuple[str, ...]]]:
        return [
            act for cond, act in self.plan.rules if eval_condition(cond, battle, self.plan.names)
        ]


def plan_terms(state: PlanState, battle, option, ctx: dict) -> dict[str, float]:
    """Plan score terms for one option. ``option`` is (move, tera) or a Pokemon (switch).
    ``ctx``: dict with 'damage' (fraction vs the active opponent), 'opp_hp', 'safe' (setup is
    safe), 'forced' (switch after a faint)."""
    p = state.plan
    me = battle.active_pokemon
    opp = battle.opponent_active_pokemon
    terms: dict[str, float] = {}
    rules = state.active_rules(battle)
    if not isinstance(option, tuple):  # a switch target
        key = option.species
        a = p.assignments.get(opp.species, {}) if opp is not None else {}
        if (
            battle.turn <= 1
            and not ctx.get("forced")
            and me is not None
            and me.species == ctx.get("lead")
        ):
            a = {}  # the planned lead gets its first turn: no assignment-driven switch-out
        # the assignment was made at team preview; if the tactical layer now rates this switch
        # as bad (e.g. the opponent has boosted since), trust the assignment less
        tv = ctx.get("tactical", 0.0)
        trust = 1.0 if tv >= 0 else 0.5 if tv >= -0.4 else 0.0
        if key == a.get("primary") and trust:
            terms["assign_primary"] = W["assign_primary"] * trust
        elif key == a.get("backup") and trust:
            terms["assign_backup"] = W["assign_backup"] * trust
        if key in a.get("avoid", []):
            terms["assign_avoid"] = W["assign_avoid"]
        sa = p.setup_answers.get(opp.species) if opp is not None else None
        if sa and sa["who"] == key and boosted_stages(opp) >= 1 and trust:
            terms["setup_answer"] = W["setup_answer"] * trust  # bring the planned answer in
        if not ctx.get("forced") and me is not None and p.roles.get(me.species) == "sacrifice_ok":
            terms["sacrifice_stay"] = W["sacrifice_stay"]
        if p.roles.get(key) == "win_condition" and not ctx.get("forced"):
            if state.in_endgame():
                terms["wincon_endgame"] = W["wincon_endgame"]
            elif key != a.get("primary"):
                terms["wincon_hidden"] = W["wincon_hidden"]
        for kind, args in rules:
            if kind == "switch_to" and p.names.our(args[0]) == key and trust:
                terms["rule"] = W["rule"] * trust  # same staleness guard as assignments
        return terms
    move, tera = option
    from alpha_poke.agents.damage import is_damaging

    attacking = is_damaging(move)
    # never promote an action the tactical layer considers useless (status move into an
    # immune target, an attack that does no damage, ...): the plan decides *what* to want,
    # the tactical layer decides whether it can work
    if attacking and ctx.get("damage", 1.0) <= 0:
        return terms
    if not attacking and ctx.get("tactical", 1.0) <= 0.0:  # 0 / negative = known useless
        return terms
    names = p.names
    for kind, args in state.goals():
        if state.goal_done((kind, args), battle):
            continue
        target = names.any(args[0])[1] if args and names.any(args[0]) else None
        if kind == "set_hazard" and move.id == to_id(args[0]):
            terms["goal_hazard"] = W["goal_hazard"]
        elif kind == "clear_hazards" and move.id in REMOVAL_IDS:
            terms["goal_clear"] = W["goal_clear"]
        elif kind in ("chip", "ko") and attacking and opp is not None and opp.species == target:
            terms["goal_" + kind] = W["goal_" + kind] * (
                1.0 if kind == "chip" or ctx.get("damage", 0) >= ctx.get("opp_hp", 1) else 0.4
            )
        elif (
            kind == "status"
            and move.status is not None
            and opp is not None
            and opp.species == target
        ):
            terms["goal_status"] = W["goal_status"]
        elif (
            kind == "setup"
            and me is not None
            and me.species == target
            and move.boosts
            and move.target == "self"
            and ctx.get("safe")
        ):
            terms["goal_setup"] = W["goal_setup"]
        elif kind == "sweep" and me is not None and me.species == target and attacking:
            terms["goal_sweep"] = W["goal_sweep"]
        elif kind == "stop_setup" and opp is not None and opp.species == target:
            if _stops_setup(move, ctx, opp):
                terms["goal_stop_setup"] = W["goal_stop_setup"]
        elif (
            kind == "heal"
            and me is not None
            and me.species == target
            and ctx.get("heals")
            and me.current_hp_fraction < 0.6
        ):
            terms["goal_heal"] = W["goal_heal"]
        elif (
            kind == "remove_item"
            and opp is not None
            and opp.species == target
            and move.id in ("knockoff", "trick", "switcheroo", "thief", "covet")
            and opp.item != ""
        ):
            terms["goal_remove_item"] = W["goal_remove_item"]
    sa = p.setup_answers.get(opp.species) if opp is not None else None
    if sa and boosted_stages(opp) >= 1 and _stops_setup(move, ctx, opp):
        terms["setup_answer"] = W["setup_answer"]
    if attacking and opp is not None and opp.species in p.kill_priority:
        rank = p.kill_priority.index(opp.species)
        share = (len(p.kill_priority) - rank) / len(p.kill_priority)
        d, hp = ctx.get("damage", 0.0), ctx.get("opp_hp", 1.0)
        # only reward real progress on a priority target: a KO, or a hit of >= 35% max HP
        progress = 1.0 if d >= hp else 0.5 if d >= 0.35 else 0.0
        if progress:
            terms["kill_priority"] = W["kill_priority"] * share * progress
    for kind, args in rules:
        if kind == "use_move" and move.id == to_id(args[0]):
            terms["rule_move"] = W["rule_move"]
        elif kind == "setup" and move.boosts and move.target == "self":
            terms["rule_move"] = W["rule_move"]
        elif kind == "tera_now" and tera:
            terms["rule_move"] = W["rule_move"]
    return terms
