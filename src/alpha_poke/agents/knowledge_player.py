"""KnowledgePlayer: planning layer at team preview + heuristic action layer (the first bot;
the fallback of the search players).

Team preview (planning):
  * belief: likely set (stats / item / moves) of each opponent mon from the team-conditional prior;
  * 6x6 one-vs-one matchup matrix (our mon i vs their mon j) with the damage model;
  * threats (their mons that beat many of ours), our answers to each threat, our win conditions
    (mons that beat many of theirs), mons to preserve (win conditions + sole answers);
  * lead: best expected matchup against their likely leads (lead rates from replays).

Each turn (heuristic actions, scored in "HP-fraction swing" units):
  * attacks: expected damage, KO bonus, zero if we get KO'd before moving;
  * hazards / removal / setup / recovery / status / pivot with simple applicability rules;
  * switches: matchup of the switch-in vs the current opponent, minus the damage it takes coming
    in, plus plan bonuses (answers to the active threat) and penalties (preserved mons, cost);
  * terastallization when it secures a KO or flips a losing defensive matchup, preferring the
    plan's win conditions.
Any exception falls back to poke-env's SimpleHeuristicsPlayer decision.
"""

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from poke_env.battle import (
    AbstractBattle,
    Battle,
    Pokemon,
    PokemonType,
    SideCondition,
)
from poke_env.battle.move import Move
from poke_env.data.normalize import to_id_str
from poke_env.player import Player, SimpleHeuristicsPlayer

from alpha_poke.agents import status_moves as sm
from alpha_poke.agents.belief_state import BeliefModel, own_view
from alpha_poke.agents.damage import (
    MonView,
    _recovers,  # noqa: F401 (recovery-aware chip value)
    best_damage,
    damage_fraction,
    entry_hazard_cost,
    is_damaging,
    moves_first,
    one_v_one,
    priority,
)
from alpha_poke.agents.plan_exec import ExecPlan, Names, PlanState, plan_terms

HAZARDS = {
    "stealthrock": SideCondition.STEALTH_ROCK,
    "spikes": SideCondition.SPIKES,
    "toxicspikes": SideCondition.TOXIC_SPIKES,
    "stickyweb": SideCondition.STICKY_WEB,
}
REMOVAL = {"rapidspin", "defog", "mortalspin", "tidyup", "courtchange"}
PIVOT = {
    "uturn",
    "voltswitch",
    "flipturn",
    "partingshot",
    "teleport",
    "chillyreception",
    "shedtail",
}
SLEEP = {"spore", "sleeppowder", "hypnosis", "yawn", "darkvoid", "lovelykiss"}

log = logging.getLogger("alpha_poke.knowledge")


def sync_tera_types(battle) -> None:
    """poke-env ignores the request's ``teraType`` field, so our own mons' tera types are None
    unless set here (without this the bot never terastallized)."""
    for mon in battle.team.values():
        if mon.tera_type is None:
            req = getattr(mon, "_last_request", None) or {}
            if req.get("teraType"):
                mon._terastallized_type = PokemonType.from_name(req["teraType"])


def _display_species(species_id: str) -> str:
    from poke_env.data import GenData

    entry = GenData.from_gen(9).pokedex.get(species_id)
    return entry["name"] if entry else species_id


STALL_TURNS = 25  # turns without a faint after which the bot actively tries to break the stall
KO_BONUS = 1.0  # bonus for an attack expected to KO (was 0.5: too close to a 50% heal)
TERA_COST = 0.3  # opportunity cost of spending the one Terastallization of the game
SETUP_IDS = {
    "swordsdance",
    "dragondance",
    "calmmind",
    "nastyplot",
    "quiverdance",
    "bulkup",
    "shellsmash",
    "agility",
    "curse",
    "coil",
    "victorydance",
    "tidyup",
    "bellydrum",
    "irondefense",
    "amnesia",
    "geomancy",
    "shiftgear",
    "filletaway",
    "clangoroussoul",
}
ABSORB_HEAL = {"waterabsorb", "voltabsorb", "dryskin", "eartheater"}  # heal instead of damage
LOOKAHEAD_W = 0.6  # weight of the switch-in's next-turn value in the switch score
MATCHUP_W = 0.3  # weight of the longer-horizon 1v1 estimate (was 0.6 alone)
STATUS_BASELINE = 0.1  # rough value of a status / utility move in the lookahead
RESWITCH_FLOOR = -0.5  # a threatened switch-in can switch out again: its loss is bounded
SWITCH_MARGIN = 0.15  # a voluntary switch must beat the best move by this much
CHAIN_SWITCH_MARGIN = 0.25  # extra margin right after a switch (no chains of switches)
FREE_TURN_SETUP = 0.2  # a switch can hand a setup user a free boost
SURE_FIRST = 0.9  # "we surely move first" (moves_first is a probability with a possible Scarf)
NO_EFFECT_VALUE = -0.1  # an action seen to do nothing: below any useful move, so we change
PLAN_BONUS_CAP = 0.5  # max total positive plan bonus on one option (terms must not stack up)


FOE_TARGETS = {
    "NORMAL",
    "ANY",
    "ADJACENT_FOE",
    "ALL_ADJACENT_FOES",
    "ALL_ADJACENT",
    "RANDOM_NORMAL",
}
STATUS_IMMUNE = {  # move id -> abilities that ignore it (besides the general ones below)
    "willowisp": ("flashfire", "waterveil", "waterbubble", "thermalexchange"),
    "thunderwave": ("voltabsorb", "lightningrod", "motordrive", "limber"),
    "toxic": ("immunity", "poisonheal", "magicguard", "toxicboost"),
    "spore": ("insomnia", "vitalspirit", "sweetveil", "overcoat"),
    "sleeppowder": ("insomnia", "vitalspirit", "sweetveil", "overcoat"),
    "yawn": ("insomnia", "vitalspirit", "sweetveil"),
}


def status_block_p(move: Move, ov) -> float:
    """Probability that the opponent's ability makes a status move / hazard useless:
    Magic Bounce reflects it, Good as Gold blocks status moves aimed at it, and status
    immunities (Purifying Salt, Comatose, move-specific ones)."""
    p = 0.0
    if "reflectable" in (move.flags or set()):
        p += ov.ability_p("magicbounce")
    target = getattr(move.target, "name", "")
    if target in FOE_TARGETS:
        p += ov.ability_p("goodasgold")
        if move.status is not None or move.id in STATUS_IMMUNE:
            p += ov.ability_p("purifyingsalt", "comatose", *STATUS_IMMUNE.get(move.id, ()))
    return min(1.0, p)


def mon_loss(hp: float) -> float:
    """Cost of losing one of our Pokemon at ``hp``: its HP plus the same KO_BONUS we credit for
    removing an opposing mon, scaled down below 50% HP (a nearly dead mon is cheap to sack)."""
    return hp + KO_BONUS * min(1.0, 2 * hp)


class BattleMemory:
    """Per-battle history used by the anti-loop rules."""

    def __init__(self):
        self.actions: deque = deque(maxlen=30)  # (turn, kind, key)
        self.switch_outs: dict[str, int] = {}  # species -> last turn it was switched out
        self.fainted = 0
        self.last_progress_turn = 0
        self.attacks: deque = deque(maxlen=6)  # (turn, move id or None, opp species, opp hp)
        # fallback for whatever the damage model missed: (opp species, terastallized, key) of
        # our moves the battle showed had no effect (immune / absorbed); key = move type for
        # attacks, move id for status moves
        self.no_effect: set[tuple[str, bool, str]] = set()
        self.opp_last_move: dict[str, str] = {}  # their species -> last move since it came in
        self.opp_setups: dict[str, int] = {}  # their species -> setup moves used (whole game)
        self._scanned = 0

    @staticmethod
    def effect_key(move: Move) -> str:
        return f"type:{move.type.name}" if is_damaging(move) else move.id

    def blocked(self, opp: Pokemon, move: Move) -> bool:
        return (opp.species, opp.is_terastallized, self.effect_key(move)) in self.no_effect

    def scan_events(self, battle) -> None:
        """Read the new protocol lines: one of our moves followed by '-immune' on the opponent,
        or by an ability heal on it (Water Absorb, Volt Absorb, ...), had no effect."""
        data = getattr(battle, "_replay_data", None) or []
        role = battle.player_role or ""
        cur = None
        for ev in data[self._scanned :]:
            if len(ev) < 3:
                if len(ev) > 1 and ev[1] in ("turn", "upkeep"):
                    cur = None
                continue
            kind = ev[1]
            if kind in ("move", "switch", "drag") and role and not ev[2].startswith(role):
                try:
                    sp = battle.get_pokemon(ev[2]).species
                except Exception:  # noqa: BLE001
                    sp = None
                if sp and kind == "move":
                    mid = to_id_str(ev[3])
                    self.opp_last_move[sp] = mid
                    if mid in SETUP_IDS:
                        self.opp_setups[sp] = self.opp_setups.get(sp, 0) + 1
                elif sp:
                    self.opp_last_move.pop(sp, None)  # a fresh switch-in has no last move
            if kind == "move":
                cur = ev[3] if role and ev[2].startswith(role) else None
            elif kind in ("switch", "drag", "turn", "upkeep", "faint"):
                cur = None
            elif cur and not ev[2].startswith(role):
                absorbed = kind == "-heal" and any(
                    x.startswith("[from] ability:") and to_id_str(x[15:]) in ABSORB_HEAL
                    for x in ev[3:]
                )  # not residual heals like Poison Heal, which also say "[from] ability:"
                if kind == "-immune" or absorbed:
                    try:
                        mon = battle.get_pokemon(ev[2])
                        key = self.effect_key(Move(to_id_str(cur), gen=9))
                    except Exception:  # noqa: BLE001 - unknown move / mon: skip the line
                        continue
                    self.no_effect.add((mon.species, mon.is_terastallized, key))
        self._scanned = len(data)

    def observe(self, battle) -> None:
        self.scan_events(battle)
        fainted = sum(m.fainted for m in battle.team.values()) + sum(
            m.fainted for m in battle.opponent_team.values()
        )
        if fainted != self.fainted:
            self.fainted = fainted
            self.last_progress_turn = battle.turn

    def record(self, battle, choice) -> None:
        opp = battle.opponent_active_pokemon
        self.attacks.append(
            (
                battle.turn,
                None if isinstance(choice, Pokemon) else choice[0].id,
                opp.species if opp else None,
                opp.current_hp_fraction if opp else None,
            )
        )
        if isinstance(choice, Pokemon):
            if battle.active_pokemon is not None:
                self.switch_outs[battle.active_pokemon.species] = battle.turn
            self.actions.append((battle.turn, "switch", choice.species))
        else:
            self.actions.append((battle.turn, "move", choice[0].id))

    def futile_repeats(self, move_id: str, opp_species: str, opp_hp: float) -> int:
        """How many of the last decisions used ``move_id`` on the same opponent without its HP
        going down by decision time (e.g. it heals back every turn): 0 if progress was made."""
        n = 0
        for _, mid, sp, hp in reversed(self.attacks):
            if mid != move_id or sp != opp_species or hp is None or opp_hp < hp - 0.02:
                break
            n += 1
        return n

    def stalemate(self, opp_species: str, opp_hp: float, window: int = 4) -> int:
        """Decisions in a row facing ``opp_species`` (at most 6). Returns that count when the
        opponent's HP now is not lower than ``window`` decisions ago (no net progress, e.g. it
        heals back what we deal every other turn), otherwise 0."""
        same = []
        for _, _, sp, hp in reversed(self.attacks):
            if sp != opp_species or hp is None:
                break
            same.append(hp)
        if len(same) < window:
            return 0
        return len(same) if opp_hp >= same[window - 1] - 0.05 else 0

    def switched_out_recently(self, species: str, turn: int, within: int) -> bool:
        t = self.switch_outs.get(species)
        return t is not None and turn - t <= within

    def switched_since(self, turn: int) -> bool:
        """Did we switch (voluntarily or after a faint) at or after ``turn``?"""
        return any(k == "switch" and t >= turn for t, k, _ in self.actions)

    def recent_switches(self, turn: int, window: int) -> int:
        return sum(1 for t, k, _ in self.actions if k == "switch" and turn - t < window)

    def recent_uses(self, move_id: str, turn: int, window: int) -> int:
        return sum(
            1 for t, k, x in self.actions if k == "move" and x == move_id and turn - t < window
        )


@dataclass
class Plan:
    opp_species: tuple[str, ...]
    matchup: dict[tuple[str, str], float] = field(default_factory=dict)  # (ours, theirs) -> score
    threats: list[str] = field(default_factory=list)
    answers: dict[str, list[str]] = field(default_factory=dict)
    win_conditions: list[str] = field(default_factory=list)
    preserve: set[str] = field(default_factory=set)
    lead: str | None = None
    tera_target: str | None = None  # None = no restriction (computed plans)
    pace: str = "balanced"  # aggressive | balanced | defensive
    hazards_priority: str = "normal"  # high | normal | low
    exec_state: object = None  # plan_exec.PlanState for this battle

    def summary(self) -> str:
        return (
            f"lead={self.lead} wincons={self.win_conditions} "
            f"preserve={sorted(self.preserve)} threats={self.threats[:3]} "
            f"answers={ {t: self.answers.get(t, []) for t in self.threats[:3]} } "
            f"tera={self.tera_target} pace={self.pace} hazards={self.hazards_priority}"
        )

    def to_log(self) -> dict:
        return {
            "lead": self.lead,
            "win_conditions": self.win_conditions,
            "preserve": sorted(self.preserve),
            "threats": self.threats[:4],
            "answers": {t: self.answers.get(t, []) for t in self.threats[:4]},
            "tera_target": self.tera_target,
            "pace": self.pace,
            "hazards_priority": self.hazards_priority,
            "exec": None
            if self.exec_state is None
            else {
                "phases": [ph.name for ph in self.exec_state.plan.phases],
                "final_phase": self.exec_state.phase_name,
                "events": self.exec_state.log,
                "problems": self.exec_state.plan.problems,
                "roles": self.exec_state.plan.roles,
                "kill_priority": self.exec_state.plan.kill_priority,
                "goals_done": self.exec_state.goals_done,
                "assign_won": self.exec_state.assign_won,
                "assign_lost": self.exec_state.assign_lost,
                "wincon_kos": self.exec_state.wincon_kos,
                "wincon_alive_end": [
                    k
                    for k, r in self.exec_state.plan.roles.items()
                    if r == "win_condition"
                    and k not in (self.exec_state._prev[2] if self.exec_state._prev else set())
                ],
            },
        }


class KnowledgePlayer(Player):
    def __init__(
        self,
        belief: BeliefModel,
        trace_dir: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.belief = belief
        self.plans: dict[str, Plan] = {}
        self.fallbacks = 0
        self.trace_dir = Path(trace_dir) if trace_dir else None
        if self.trace_dir:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.memory: dict[str, BattleMemory] = {}

    # ---- helpers ------------------------------------------------------------------------
    def _opp_team_names(self, battle: AbstractBattle) -> tuple[str, ...]:
        mons = battle.teampreview_opponent_team or list(battle.opponent_team.values())
        return tuple(self.belief.display(m.species) for m in mons)

    def _opp(self, battle, mon: Pokemon) -> tuple[MonView, list[Move]]:
        return self.belief.opponent_view(mon, self._opp_team_names(battle))

    @staticmethod
    def _key(mon: Pokemon) -> str:
        return mon.species

    # ---- planning -------------------------------------------------------------------------
    def make_plan(self, battle: AbstractBattle) -> Plan:
        ours = list(battle.team.values())
        theirs = battle.teampreview_opponent_team or list(battle.opponent_team.values())
        plan = Plan(self._opp_team_names(battle))
        opp_views = {self._key(t): self._opp(battle, t) for t in theirs}
        for o in ours:
            ov = own_view(o)
            for t in theirs:
                tv, tmoves = opp_views[self._key(t)]
                plan.matchup[(self._key(o), self._key(t))] = one_v_one(
                    ov, tv, list(o.moves.values()), tmoves, battle
                )
        our_keys = [self._key(o) for o in ours]
        their_keys = [self._key(t) for t in theirs]
        threat = {t: -sum(plan.matchup[(o, t)] for o in our_keys) for t in their_keys}
        plan.threats = sorted(their_keys, key=threat.get, reverse=True)
        plan.answers = {t: [o for o in our_keys if plan.matchup[(o, t)] > 0.3] for t in their_keys}
        strength = {o: sum(plan.matchup[(o, t)] for t in their_keys) for o in our_keys}
        for o in ours:  # setup sweepers are natural win conditions
            if any(
                m.boosts and m.target == "self" and sum(m.boosts.values()) >= 1
                for m in o.moves.values()
            ):
                strength[self._key(o)] += 0.5
        plan.win_conditions = sorted(our_keys, key=strength.get, reverse=True)[:2]
        plan.preserve = set(plan.win_conditions)
        for t in plan.threats[:3]:
            if len(plan.answers[t]) == 1:
                plan.preserve.add(plan.answers[t][0])
        # lead: expected matchup vs their likely leads
        rates = {
            t: self.belief.lead_rate.get(n, 1 / 6)
            for t, n in zip(their_keys, plan.opp_species, strict=False)
        }
        total = sum(rates.values()) or 1.0

        def lead_value(o: str) -> float:
            v = sum(rates[t] / total * plan.matchup[(o, t)] for t in their_keys)
            mon = battle.team_by_species(o) if hasattr(battle, "team_by_species") else None
            mon = mon or next(m for m in ours if self._key(m) == o)
            if any(mv in HAZARDS for mv in mon.moves):
                v += 0.15
            if o in plan.win_conditions:
                v -= 0.15
            return v

        plan.lead = max(our_keys, key=lead_value)
        return plan

    # ---- executable plans ------------------------------------------------------------------
    def _name_maps(self, battle) -> tuple[dict[str, str], dict[str, str]]:
        """(our key -> display name, their key -> display name) as used in plans."""
        our = {self._key(m): _display_species(m.species) for m in battle.team.values()}
        theirs_raw = battle.teampreview_opponent_team or list(battle.opponent_team.values())
        names = self._opp_team_names(battle)
        their = {self._key(t): n.replace("-*", "") for t, n in zip(theirs_raw, names, strict=False)}
        return our, their

    def _computed_exec(self, battle, plan: Plan, our: dict, their: dict) -> dict:
        """Rule-generated executable plan (plan_exec's format: roles, assignments, phases)."""
        ours = list(battle.team.values())
        roles = {}
        for m in ours:
            mv, k = set(m.moves), self._key(m)
            if k in plan.win_conditions:
                roles[our[k]] = "win_condition"
            elif mv & set(HAZARDS):
                roles[our[k]] = "hazard_setter"
            elif mv & REMOVAL:
                roles[our[k]] = "hazard_removal"
            elif k not in plan.preserve:
                roles[our[k]] = "sacrifice_ok"
        assignments = {}
        for t in their:
            ranked = sorted(our, key=lambda o, t=t: -plan.matchup.get((o, t), 0.0))
            assignments[their[t]] = {
                "primary": our[ranked[0]],
                "backup": our[ranked[1]] if len(ranked) > 1 else None,
                "avoid": [our[o] for o in ranked if plan.matchup.get((o, t), 0) < -0.6],
            }
        threats = [their[t] for t in plan.threats[:2] if t in their]
        phases = []
        setter = next((m for m in ours if set(m.moves) & {"stealthrock", "spikes"}), None)
        if setter is not None:
            hz = "stealthrock" if "stealthrock" in setter.moves else "spikes"
            phases.append(
                {
                    "name": "early",
                    "until": f"our_hazard_set:{hz} OR turn_after:8",
                    "goals": [f"set_hazard:{hz}"],
                }
            )
        if threats:
            until = " AND ".join(f"fainted:{t}" for t in threats) + " OR turn_after:40"
            phases.append({"name": "mid", "until": until, "goals": [f"ko:{t}" for t in threats]})
        wc = [our[w] for w in plan.win_conditions if w in our]
        goals = [f"setup:{wc[0]}", f"sweep:{wc[0]}"] if wc else ["scout"]
        phases.append({"name": "endgame", "goals": goals})
        return {
            "roles": roles,
            "assignments": assignments,
            "kill_priority": threats,
            "phases": phases,
            "tera": {"who": wc[0] if wc else None, "when": "secures_ko OR saves_from_ko"},
            "rules": [],
        }

    def _init_exec(self, battle, plan: Plan) -> PlanState:
        our, their = self._name_maps(battle)
        names = Names({v: k for k, v in our.items()}, {v: k for k, v in their.items()})
        d = self._computed_exec(battle, plan, our, their)
        state = PlanState(ExecPlan.from_dict(d, names), matchup=plan.matchup)
        plan.exec_state = state
        return state

    async def teampreview(self, battle: AbstractBattle) -> str:
        try:
            sync_tera_types(battle)
            plan = self.make_plan(battle)
            self.plans[battle.battle_tag] = plan
            self._init_exec(battle, plan)
            ours = list(battle.team.values())
            order = sorted(range(len(ours)), key=lambda i: self._key(ours[i]) != plan.lead)
            for mon in ours:
                mon._selected_in_teampreview = True
            log.info("%s plan: %s", battle.battle_tag, plan.summary())
            return "/team " + "".join(str(i + 1) for i in order)
        except Exception:  # noqa: BLE001
            log.exception("teampreview failed; random order")
            self.fallbacks += 1
            return self.random_teampreview(battle)

    # ---- actions --------------------------------------------------------------------------
    def choose_move(self, battle: AbstractBattle):
        try:
            return self._choose(battle)
        except Exception:  # noqa: BLE001
            log.exception("choose_move failed; falling back to SimpleHeuristics")
            self.fallbacks += 1
            return SimpleHeuristicsPlayer.choose_singles_move(battle)[0]

    def _choose(self, battle: Battle):
        scored = self._score_options(battle)
        if scored is None:
            return self.choose_random_move(battle)
        rows, mem, incoming, state = scored
        best = max(rows, key=lambda r: r["total"])
        choice = best["choice"]
        mem.record(battle, choice)
        if self.trace_dir:
            self._trace(battle, mem, rows, best, incoming, state)
        if isinstance(choice, Pokemon):
            return self.create_order(choice)
        move, tera = choice
        return self.create_order(move, terastallize=tera)

    def _score_options(self, battle: Battle):
        """Score every legal option: (rows, memory, incoming estimate, plan state), or None
        when there is nothing to score. Each row: choice, tactical / stay / future / loop
        terms, plan terms and the total. Updates the battle memory and the plan state."""
        sync_tera_types(battle)
        me, opp = battle.active_pokemon, battle.opponent_active_pokemon
        if me is None or opp is None:
            return None
        plan = self.plans.get(battle.battle_tag)
        if plan is None:
            plan = self.plans[battle.battle_tag] = self.make_plan(battle)
        state = plan.exec_state
        if state is None:
            state = self._init_exec(battle, plan)
        if state is not None:
            state.update(battle)
        mv = own_view(me)
        ov, ov_moves = self._opp(battle, opp)
        opp_move, incoming = best_damage(ov, mv, ov_moves, battle)
        opp_kos_me = incoming >= me.current_hp_fraction
        forced = not battle.available_moves

        mem = self.memory.setdefault(battle.battle_tag, BattleMemory())
        mem.observe(battle)
        self._sctx = sm.Ctx(
            battle,
            mv,
            ov,
            ov_moves,
            incoming,
            n_opp_left=6 - sum(m.fainted for m in battle.opponent_team.values()),
            n_my_left=sum(not m.fainted for m in battle.team.values()),
            is_wincon=me.species in plan.win_conditions,
            opp_last_move=mem.opp_last_move.get(opp.species),
            used_protect_last_turn=any(
                k == "move" and x in sm.PROTECT and t >= battle.turn - 1 for t, k, x in mem.actions
            ),
        )
        self._threat = sm.boost_threat(self._sctx)
        tactical: list[tuple[float, object]] = []
        if battle.available_moves:
            tactical += self._score_moves(battle, plan, mv, ov, incoming, opp_kos_me, ov_moves, mem)
        for s in battle.available_switches:
            tactical.append(
                (self._score_switch(battle, plan, s, ov, ov_moves, opp_move, forced), s)
            )
        if not tactical:
            return None
        stay_future = 0.0
        if battle.available_moves and not forced:
            hp_next = me.current_hp_fraction - incoming
            if hp_next > 0:  # if we are KO'd, the stay cost already counts the whole mon
                stay_future = LOOKAHEAD_W * self._next_turn_value(battle, mv, ov, ov_moves, hp_next)
        switch_margin = SWITCH_MARGIN + (
            CHAIN_SWITCH_MARGIN if mem.switched_since(battle.turn - 1) else 0.0
        )
        rows = []
        for v, c in tactical:
            terms: dict[str, float] = {}
            dmg = None
            if isinstance(c, tuple):
                dmg = 0.0 if mem.blocked(opp, c[0]) else damage_fraction(mv, ov, c[0], battle)
            first = self._first(battle, mv, ov, c[0], ov_moves) if isinstance(c, tuple) else None
            if state is not None:
                ctx = {
                    "forced": forced,
                    "opp_hp": opp.current_hp_fraction,
                    "safe": incoming < 0.35 and me.current_hp_fraction >= 0.6,
                    "lead": plan.lead,
                    "tactical": v,
                }
                if isinstance(c, tuple):
                    d = dmg
                    ctx["damage"] = d
                    ctx["heals"] = sm.heal_fraction(c[0], battle) > 0 or c[0].id in (
                        "rest",
                        "wish",
                        "painsplit",
                    )
                    if c[1]:  # tera option: respect the plan's tera directive
                        tera_ctx = {
                            "secures_ko": d >= opp.current_hp_fraction,
                            "saves_from_ko": opp_kos_me,
                        }
                        if not state.tera_allowed(battle, me.species, tera_ctx):
                            continue
                terms = plan_terms(state, battle, c, ctx)
            loop = self._loop_adjust(battle, mem, c, v)
            # damage we take by staying in; switches already pay it on the switch-in. Kept out
            # of `tactical` so the plan layer's usefulness / trust checks see the action itself.
            stay = (
                self._stay_cost(battle, mv, ov, c, incoming, first) if isinstance(c, tuple) else 0.0
            )
            # switches are scored with the switch-in's next turn: give staying the same horizon,
            # and make a voluntary switch clear a margin (bigger right after another switch)
            if isinstance(c, tuple):
                future = stay_future
            else:
                future = 0.0 if forced else -switch_margin
            pos = sum(x for x in terms.values() if x > 0)
            plan_total = min(pos, PLAN_BONUS_CAP) + sum(x for x in terms.values() if x < 0)
            rows.append(
                {
                    "dmg": dmg,
                    "first": first,
                    "choice": c,
                    "tactical": v,
                    "stay": stay,
                    "future": future,
                    "plan": terms,
                    "loop": loop,
                    "plan_total": plan_total,
                    "total": v - stay + future + plan_total + loop,
                }
            )
        return (rows, mem, incoming, state) if rows else None

    # ---- anti-loop --------------------------------------------------------------------------
    def _loop_adjust(self, battle, mem: "BattleMemory", choice, value: float) -> float:
        """Score adjustment that breaks repetition loops (e.g. ping-pong switching, re-setting
        the same hazard forever). Grows with the number of turns since the last faint."""
        stall = battle.turn - mem.last_progress_turn
        adj = 0.0
        opp = battle.opponent_active_pokemon
        stuck = mem.stalemate(opp.species, opp.current_hp_fraction) if opp is not None else 0
        if isinstance(choice, Pokemon):
            forced = not battle.available_moves
            if not forced and stuck >= 3:
                # this matchup is a stalemate: bring something that can break it (the longer
                # it lasts, the stronger the push)
                adj += min(0.9, 0.2 + 0.1 * stuck)
            if not forced:
                if mem.switched_out_recently(choice.species, battle.turn, within=2):
                    adj -= 0.25  # switching back to what we just switched out
                adj -= 0.08 * mem.recent_switches(battle.turn, window=6)
                if stall >= STALL_TURNS:
                    adj -= 0.25
            return adj
        move, _ = choice
        attacking = is_damaging(move)
        ko_now = (
            attacking
            and opp is not None
            and damage_fraction(
                own_view(battle.active_pokemon), self._opp(battle, opp)[0], move, battle
            )
            >= opp.current_hp_fraction
        )
        if attacking and opp is not None and not ko_now:  # repeated KO attempts are not futile
            futile = mem.futile_repeats(move.id, opp.species, opp.current_hp_fraction)
            if futile >= 2:  # our damage is undone every turn (recovery loop): try something else
                adj -= 0.3 * (futile - 1)
        if stuck >= 3 and not attacking and (move.heal or move.id in ("rest",)):
            adj -= 0.2  # healing does not break a stalemate
        if stall >= 15 and not attacking:
            adj -= 0.04 * mem.recent_uses(move.id, battle.turn, window=10)
        if stall >= STALL_TURNS:
            if attacking:
                adj += 0.05
            else:
                adj -= 0.5 * max(value, 0.0)  # status / recovery values halved
        return adj

    def _trace(self, battle, mem, rows, best, incoming, state) -> None:
        def name(c):
            return c.species if isinstance(c, Pokemon) else c[0].id + ("+tera" if c[1] else "")

        top = sorted(rows, key=lambda r: -r["total"])[:5]
        best_tactical = max(rows, key=lambda r: r["tactical"] - r["stay"] + r["future"] + r["loop"])
        row = {
            "turn": battle.turn,
            "me": battle.active_pokemon.species,
            "me_hp": round(battle.active_pokemon.current_hp_fraction, 3),
            "opp": battle.opponent_active_pokemon.species,
            "opp_hp": round(battle.opponent_active_pokemon.current_hp_fraction, 3),
            "incoming_est": round(incoming, 3),
            "stall": battle.turn - mem.last_progress_turn,
            "our_fainted": sum(m.fainted for m in battle.team.values()),
            "their_fainted": sum(m.fainted for m in battle.opponent_team.values()),
            "phase": state.phase_name if state else None,
            "rules_active": [f"{k}:{':'.join(a)}" for k, a in state.active_rules(battle)]
            if state
            else [],
            "options": [
                {
                    "a": name(r["choice"]),
                    "total": round(r["total"], 3),
                    "tactical": round(r["tactical"], 3),
                    "stay": round(r["stay"], 3),
                    "future": round(r["future"], 3),
                    "loop": round(r["loop"], 3),
                    "plan": {k: round(v, 3) for k, v in r["plan"].items()},
                    "dmg": None if r["dmg"] is None else round(r["dmg"], 3),
                    "first": r["first"],
                }
                for r in top
            ],
            "opp_kos_me": incoming >= battle.active_pokemon.current_hp_fraction,
            "ko_available": [
                name(r["choice"])
                for r in rows
                if r["dmg"] is not None
                and r["dmg"] >= battle.opponent_active_pokemon.current_hp_fraction
                and (r["first"] == 1.0 or incoming < battle.active_pokemon.current_hp_fraction)
            ],
            "chosen": name(best["choice"]),
            "followed_plan": sum(best["plan"].values()) > 0,
            "plan_changed_decision": best is not best_tactical,
            "events": state.log[-3:] if state else [],
        }
        with open(self.trace_dir / f"{battle.battle_tag}_{self.username}.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def _first(self, battle, mv, ov, move, ov_moves, hp: float | None = None) -> float:
        """P(we act before the opponent) with ``move``: speed (with a possible Scarf), and 0 if
        one of the opponent's likely higher-priority attacks KOs us first (Sucker Punch /
        Thunderclap only work against an attack)."""
        f = moves_first(mv, ov, move, battle)
        if f <= 0:
            return f
        prio = priority(move) if move is not None else 0
        hp = mv.mon.current_hp_fraction if hp is None else hp
        for m in ov_moves:
            if priority(m) <= prio or not is_damaging(m):
                continue
            if m.id in ("suckerpunch", "thunderclap") and (move is None or not is_damaging(move)):
                continue
            if damage_fraction(ov, mv, m, battle) >= hp:
                return 0.0
        return f

    def _score_moves(self, battle, plan, mv, ov, incoming, opp_kos_me, ov_moves=(), mem=None):
        me, opp = mv.mon, ov.mon
        opp_hp = opp.current_hp_fraction
        n_opp_left = 6 - sum(m.fainted for m in battle.opponent_team.values())
        n_my_left = sum(not m.fainted for m in battle.team.values())
        is_wincon = me.species in plan.win_conditions
        # a KO we land before the opponent can act needs no Tera at all
        secure_ko = any(
            is_damaging(m)
            and damage_fraction(mv, ov, m, battle) >= opp_hp
            and self._first(battle, mv, ov, m, ov_moves) >= SURE_FIRST
            for m in battle.available_moves
        )
        out = []
        for move in battle.available_moves:
            if mem is not None and mem.blocked(opp, move):
                # the battle already showed this has no effect on this target: never again
                out.append((NO_EFFECT_VALUE, (move, False)))
                continue
            first = self._first(battle, mv, ov, move, ov_moves)
            v = 0.0
            if is_damaging(move):
                d = damage_fraction(mv, ov, move, battle)
                v = min(d, opp_hp)
                if d >= opp_hp:
                    v += KO_BONUS  # removing a Pokemon is worth far more than its last HP
                elif d < 0.5 and _recovers(ov_moves):
                    v *= 0.5  # chip that a reliable-recovery user heals back next turn
                if plan.pace == "aggressive":
                    v += 0.05
                if move.id in PIVOT:
                    v += 0.1 if plan.matchup.get((me.species, opp.species), 0) < 0 else 0.0
                if move.recoil:
                    v -= 0.3 * move.recoil * min(d, opp_hp)
                v += sm.attack_bonus(self._sctx, move, self._threat)
                if self._threat > 0:  # focus a boosted opponent: removing it is worth more
                    v += KO_BONUS * self._threat if d >= opp_hp else 0.5 * self._threat * min(d, 1)
            else:
                v = self._status_value(
                    battle, move, mv, ov, incoming, n_opp_left, n_my_left, is_wincon
                )
            if opp_kos_me:
                v *= first + (1 - first) * 0.15  # if we are slower we faint before acting
            out.append((v, (move, False)))
            tera_allowed = (
                plan.tera_target is None
                or plan.tera_target == me.species
                or (sum(not m.fainted for m in battle.team.values()) == 1)
            )
            if (
                battle.can_tera
                and me.tera_type is not None
                and is_damaging(move)
                and tera_allowed
                and not secure_ko
            ):
                tv = self._tera_value(battle, plan, move, mv, ov, opp_kos_me, first)
                if tv is not None:
                    out.append((tv, (move, True)))
        return out

    def _status_value(self, battle, move, mv, ov, incoming, n_opp_left, n_my_left, is_wincon):
        v = self._status_value_raw(battle, move, mv, ov, incoming, n_opp_left, n_my_left, is_wincon)
        return v * (1 - status_block_p(move, ov)) if v > 0 else v

    def _status_value_raw(self, battle, move, mv, ov, incoming, n_opp_left, n_my_left, is_wincon):
        opp = ov.mon
        mid = move.id
        plan = self.plans.get(battle.battle_tag)
        hz = {"high": 1.6, "normal": 1.0, "low": 0.5}.get(
            plan.hazards_priority if plan else "", 1.0
        )
        defensive = plan is not None and plan.pace == "defensive"
        if mid in HAZARDS:
            if HAZARDS[mid] in battle.opponent_side_conditions and mid != "spikes":
                return 0.0
            if (
                mid == "spikes"
                and battle.opponent_side_conditions.get(SideCondition.SPIKES, 0) >= 3
            ):
                return 0.0
            return hz * (0.4 if mid == "stealthrock" else 0.3) * min(1.0, n_opp_left / 4)
        if mid == "courtchange":
            return sm.court_change_value(self._sctx)
        if mid in REMOVAL:
            layers = len([c for c in battle.side_conditions if c in HAZARDS.values()])
            return hz * 0.3 * layers if n_my_left >= 2 else 0.0
        threat = self._threat
        if opp.status is None and move.status is not None:
            bonus = sm.status_threat_bonus(move, self._sctx, threat)
            types = set(opp.types)
            if (
                mid == "willowisp"
                and PokemonType.FIRE not in types
                and (ov.stats["atk"] > ov.stats["spa"] or opp.boosts.get("atk", 0) > 0)
            ):
                return 0.4 + bonus
            if mid == "thunderwave" and not types & {PokemonType.ELECTRIC, PokemonType.GROUND}:
                return (0.35 if moves_first(mv, ov, None, battle) < 0.5 else 0.15) + bonus
            if mid == "toxic" and not types & {PokemonType.POISON, PokemonType.STEEL}:
                return 0.3
            if mid in SLEEP and not any(
                m.status and m.status.name == "SLP" for m in battle.opponent_team.values()
            ):
                return 0.55
        v = sm.misc_status_value(self._sctx, move, threat)
        if v is not None:
            return v * (1.3 if defensive and sm.heal_fraction(move, battle) > 0 else 1.0)
        return 0.02

    def _tera_value(self, battle, plan, move, mv, ov, opp_kos_me, first):
        me, opp = mv.mon, ov.mon
        tera = me.tera_type
        orig = {t for t in (me.type_1, me.type_2) if t}
        if move.type == tera:
            stab_gain = (2.0 if tera in orig else 1.5) / (1.5 if tera in orig else 1.0)
        else:
            stab_gain = 1.0
        d = damage_fraction(mv, ov, move, battle) * stab_gain
        secures_ko = d >= opp.current_hp_fraction > damage_fraction(mv, ov, move, battle)
        # defensive flip: does tera turn a predicted KO into survival?
        defensive = opp_kos_me and _tera_def_ratio(me, opp) < 1.0
        if not (secures_ko or defensive):
            return None
        is_wincon = me.species in plan.win_conditions
        last = sum(not m.fainted for m in battle.team.values()) == 1
        if not (is_wincon or last or secures_ko):
            return None
        v = min(d, opp.current_hp_fraction) + (KO_BONUS if d >= opp.current_hp_fraction else 0)
        # tera is a once-per-game resource: only worth it for a clear gain
        return v + (0.1 if is_wincon else 0.0) - (0.0 if last else TERA_COST)

    def _stay_cost(self, battle, mv, ov, choice, incoming: float, first: float) -> float:
        """Expected loss from staying in with ``choice``: the HP the opponent's best attack
        takes, or the whole mon (mon_loss) when that attack KOs us. Zero if our attack KOs
        first (half on a speed tie)."""
        move, tera = choice
        me, opp = mv.mon, ov.mon
        if tera:
            incoming *= _tera_def_ratio(me, opp)
        if move.id in sm.PROTECT and not self._sctx.used_protect_last_turn:
            return 0.0  # the hit is blocked (the free turn it gives is in protect_value)
        factor = 1.0
        if is_damaging(move) and damage_fraction(mv, ov, move, battle) >= opp.current_hp_fraction:
            factor = 1.0 - first  # first: 1 = we move first, 0.5 = speed tie
        hp = me.current_hp_fraction
        heal = sm.heal_fraction(move, battle) if move.id not in ("rest", "wish") else 0.0
        if move.id == "rest" and me.status is None:
            heal = 1.0
        if heal:  # healing first (faster) means the hit lands on the healed HP
            healed = min(1.0, hp + heal)
            cost_after = mon_loss(healed) if incoming >= healed else incoming
            cost_before = mon_loss(hp) if incoming >= hp else incoming
            return first * cost_after + (1 - first) * cost_before
        return factor * (mon_loss(hp) if incoming >= hp else incoming)

    def _next_turn_value(self, battle, sv, ov, ov_moves, hp: float) -> float:
        """Value of the switch-in's best action on the turn after it comes in at ``hp``: the
        same 'action value minus stay cost' as for the active mon, floored at the cost of
        switching out again."""
        inc = max((damage_fraction(ov, sv, m, battle) for m in ov_moves), default=0.0)
        kos_us = inc >= hp
        hit_cost = mon_loss(hp) if kos_us else inc
        opp_hp = ov.mon.current_hp_fraction
        best = STATUS_BASELINE - hit_cost  # a status / utility move: we take the hit
        for m in sv.mon.moves.values():
            if not is_damaging(m):
                continue
            d = damage_fraction(sv, ov, m, battle)
            f = self._first(battle, sv, ov, m, ov_moves, hp=hp)
            val = min(d, opp_hp) + (KO_BONUS * (1 + self._threat) if d >= opp_hp else 0.0)
            if kos_us:
                val *= f + (1 - f) * 0.15
            cost = (1 - f if d >= opp_hp else 1.0) * hit_cost
            best = max(best, val - cost)
        return max(best, RESWITCH_FLOOR)

    def _score_switch(self, battle, plan, s, ov, ov_moves, opp_move, forced: bool) -> float:
        sv = own_view(s)
        taken = 0.0
        if not forced and opp_move is not None:
            taken = damage_fraction(ov, sv, opp_move, battle)
        hazard = entry_hazard_cost(s, battle.side_conditions)
        hp_after = max(0.0, s.current_hp_fraction - hazard - taken)
        if hp_after <= 0:
            return -mon_loss(s.current_hp_fraction)  # we would just lose this mon instead
        # live 1v1 (current boosts / HP of the opponent): the preview table goes stale
        mu = one_v_one(sv, ov, list(s.moves.values()), ov_moves, battle)
        # matchup was computed at full HP; scale by remaining HP
        mu = mu * (0.5 + 0.5 * hp_after)
        # one-turn lookahead: next turn the opponent aims its best move at the switch-in, so a
        # switch-in that is just as threatened as the current mon gains nothing (no chains of
        # switches that hand out free hits)
        nxt = self._next_turn_value(battle, sv, ov, ov_moves, hp_after)
        v = LOOKAHEAD_W * nxt + MATCHUP_W * mu - taken - hazard
        if s.species in plan.preserve and taken > 0.35:
            v -= 0.3  # plan: don't take big hits with mons we must keep
        if s.species in plan.win_conditions and forced and mu < 0.3:
            v -= 0.15  # don't throw the win condition in early
        if not forced:
            active = battle.active_pokemon
            # plan: save a preserved mon that is about to be KO'd
            if active is not None and active.species in plan.preserve:
                ov_best = max(
                    (damage_fraction(ov, own_view(active), m, battle) for m in ov_moves),
                    default=0.0,
                )
                if ov_best >= active.current_hp_fraction:
                    v += 0.2
            v -= {"aggressive": 0.2, "defensive": 0.06}.get(plan.pace, 0.12)  # switching tempo
            v -= self._free_turn_cost(battle, sv, ov, ov_moves)
        return v

    def _free_turn_cost(self, battle, sv, ov, ov_moves) -> float:
        """The opponent need not attack our switch: a setup user boosts, a recovery user heals.
        Costs more when the switch-in cannot threaten it (it can set up for free again)."""
        opp = ov.mon
        d_s = max(
            (damage_fraction(sv, ov, m, battle) for m in sv.mon.moves.values() if is_damaging(m)),
            default=0.0,
        )
        cost = 0.0
        if sm.positive_stages(opp) < 4 and any(m.id in SETUP_IDS for m in ov_moves):
            cost += FREE_TURN_SETUP if d_s < 0.35 else 0.4 * FREE_TURN_SETUP
        if 1 - opp.current_hp_fraction > 0.25 and any(
            sm.heal_fraction(m, battle) > 0 for m in ov_moves
        ):
            cost += 0.08
        return cost


from poke_env.data import GenData  # noqa: E402

_TYPE_CHART = GenData.from_gen(9).type_chart


def _tera_def_ratio(me: Pokemon, opp: Pokemon) -> float:
    """Damage multiplier of the opponent's STAB types against our tera type, relative to our
    current typing (< 1: tera makes us take less)."""
    if me.tera_type is None:
        return 1.0
    now = max((me.damage_multiplier(t) for t in opp.types if t), default=1)
    tera = max(
        (t.damage_multiplier(me.tera_type, None, type_chart=_TYPE_CHART) for t in opp.types if t),
        default=1,
    )
    return tera / now if now else 1.0
