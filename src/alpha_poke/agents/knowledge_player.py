"""KnowledgePlayer: planning layer at team preview + heuristic action layer (D9 prototype).

Team preview (planning):
  * belief: likely set (stats / item / moves) of each opponent mon from the team-conditional prior;
  * 6x6 one-vs-one matchup matrix (our mon i vs their mon j) with the damage model;
  * threats (their mons that beat many of ours), our answers to each threat, our win conditions
    (mons that beat many of theirs), mons to preserve (win conditions + sole answers);
  * lead: best expected matchup against their likely leads (lead rates from replays);
  * the opponent's matching cores from the archetype library (names, for the log / later use).

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
import random
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
from poke_env.player import Player, SimpleHeuristicsPlayer

from alpha_poke.agents.belief_state import BeliefModel, own_view
from alpha_poke.agents.damage import (
    MonView,
    _recovers,  # noqa: F401 (recovery-aware chip value)
    best_damage,
    damage_fraction,
    is_damaging,
    moves_first,
    one_v_one,
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


def top(d: dict[str, float], k: int) -> list[list]:
    """Top-k (name, probability rounded to 2 decimals) of a distribution."""
    return [[n, round(p, 2)] for n, p in sorted(d.items(), key=lambda kv: -kv[1])[:k]]


def _display_species(species_id: str) -> str:
    from poke_env.data import GenData

    entry = GenData.from_gen(9).pokedex.get(species_id)
    return entry["name"] if entry else species_id


STALL_TURNS = 25  # turns without a faint after which the bot actively tries to break the stall
KO_BONUS = 1.0  # bonus for an attack expected to KO (was 0.5: too close to a 50% heal)


class BattleMemory:
    """Per-battle history used by the anti-loop rules."""

    def __init__(self):
        self.actions: deque = deque(maxlen=30)  # (turn, kind, key)
        self.switch_outs: dict[str, int] = {}  # species -> last turn it was switched out
        self.fainted = 0
        self.last_progress_turn = 0
        self.attacks: deque = deque(maxlen=6)  # (turn, move id or None, opp species, opp hp)

    def observe(self, battle) -> None:
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
    opp_cores: list[str] = field(default_factory=list)
    tera_target: str | None = None  # None = no restriction (computed plans)
    pace: str = "balanced"  # aggressive | balanced | defensive
    hazards_priority: str = "normal"  # high | normal | low
    source: str = "computed"  # computed | llm | computed(llm-failed)
    llm: dict = field(default_factory=dict)  # key, cached, cost, problems, game_plan, ...
    llm_raw: dict = field(default_factory=dict)  # the validated LLM plan (executable part)
    exec_state: object = None  # plan_exec.PlanState for this battle

    def summary(self) -> str:
        return (
            f"[{self.source}] lead={self.lead} wincons={self.win_conditions} "
            f"preserve={sorted(self.preserve)} threats={self.threats[:3]} "
            f"answers={ {t: self.answers.get(t, []) for t in self.threats[:3]} } "
            f"tera={self.tera_target} pace={self.pace} hazards={self.hazards_priority} "
            f"opp_cores={self.opp_cores[:1]}"
        )

    def to_log(self) -> dict:
        return {
            "source": self.source,
            "lead": self.lead,
            "win_conditions": self.win_conditions,
            "preserve": sorted(self.preserve),
            "threats": self.threats[:4],
            "answers": {t: self.answers.get(t, []) for t in self.threats[:4]},
            "tera_target": self.tera_target,
            "pace": self.pace,
            "hazards_priority": self.hazards_priority,
            "opp_cores": self.opp_cores[:1],
            "llm": self.llm,
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
        library: dict | None = None,
        use_plan: bool = True,
        plan_lead: bool = True,
        lead_prior: str = "human",
        random_lead: bool = False,
        anti_loop: bool = True,
        trace_dir: str | None = None,
        plan_mode: str = "computed",
        llm_model: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.belief = belief
        self.use_plan = use_plan  # ablation: no threats / answers / win conditions / preserve
        self.plan_lead = plan_lead and use_plan  # ablation: lead = first slot of the team file
        self.lead_prior = lead_prior  # "human": replay lead rates; "uniform": any of the six
        self.random_lead = random_lead  # ablation: uniformly random lead
        self.library = library
        self.plans: dict[str, Plan] = {}
        self.fallbacks = 0
        self.anti_loop = anti_loop
        self.trace_dir = Path(trace_dir) if trace_dir else None
        if self.trace_dir:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.memory: dict[str, BattleMemory] = {}
        self.plan_mode = plan_mode  # "computed" (rules) or "llm" (one cached LLM call per pair)
        self.llm_model = llm_model
        self._planner = None

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
        rates = (
            {t: 1.0 for t in their_keys}
            if self.lead_prior == "uniform"
            else {
                t: self.belief.lead_rate.get(n, 1 / 6)
                for t, n in zip(their_keys, plan.opp_species, strict=False)
            }
        )
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

        if self.random_lead:
            plan.lead = random.choice(our_keys)
        else:
            plan.lead = max(our_keys, key=lead_value) if self.plan_lead else our_keys[0]
        if not self.use_plan:  # keep the matchup cache (pure knowledge), drop the strategy
            plan.threats, plan.answers, plan.win_conditions, plan.preserve = [], {}, [], set()
        if self.library:
            names = set(plan.opp_species)
            hits = [c for c in self.library.get("cores", []) if set(c["members"]) <= names]
            hits.sort(key=lambda c: (-c["size"], -c["support"]))
            plan.opp_cores = [f"{c['name']} ({' + '.join(c['members'])})" for c in hits]
        return plan

    # ---- executable plans ------------------------------------------------------------------
    def _name_maps(self, battle) -> tuple[dict[str, str], dict[str, str]]:
        """(our key -> display name, their key -> display name) as used in plans/prompts."""
        our = {self._key(m): _display_species(m.species) for m in battle.team.values()}
        theirs_raw = battle.teampreview_opponent_team or list(battle.opponent_team.values())
        names = self._opp_team_names(battle)
        their = {self._key(t): n.replace("-*", "") for t, n in zip(theirs_raw, names, strict=False)}
        return our, their

    def _computed_exec(self, battle, plan: Plan, our: dict, their: dict) -> dict:
        """Rule-generated executable plan with the same structure as the LLM's (so that
        LLM vs rules compares plan *content*, not execution machinery)."""
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
        d = plan.llm_raw if plan.source == "llm" and plan.llm_raw.get("phases") else None
        if d is None:
            d = self._computed_exec(battle, plan, our, their)
        state = PlanState(ExecPlan.from_dict(d, names), matchup=plan.matchup)
        plan.exec_state = state
        return state

    # ---- LLM plan --------------------------------------------------------------------------
    def _llm_inputs(self, battle, plan: Plan):
        """Prompt inputs + name maps. Opponent: species and *belief* estimates only."""
        from alpha_poke.agents.llm_plan import display_ability, display_item, display_move

        ours_raw = list(battle.team.values())
        our_name = {self._key(m): _display_species(m.species) for m in ours_raw}
        ours = [
            {
                "species": our_name[self._key(m)],
                "item": display_item(m.item),
                "ability": display_ability(m.ability, m.species),
                "tera": m.tera_type.name.title() if m.tera_type else "",
                "moves": [display_move(x) for x in m.moves],
            }
            for m in ours_raw
        ]
        theirs_raw = battle.teampreview_opponent_team or list(battle.opponent_team.values())
        team_names = self._opp_team_names(battle)
        their_name = {}
        their_info = []
        for t, tname in zip(theirs_raw, team_names, strict=False):
            dist = self.belief.prior.predict(tname, team_names)
            name = tname.replace("-*", "")
            their_name[self._key(t)] = name
            their_info.append(
                {
                    "species": name,
                    "items": [[display_item(i), p] for i, p in top(dist.item, 3)],
                    "tera": [[x.title(), p] for x, p in top(dist.tera, 2)],
                    "moves": [[display_move(x), p] for x, p in top(dist.move, 8) if p >= 0.04],
                }
            )
        their_info.sort(key=lambda x: x["species"])
        matchups = []
        for o in sorted(our_name, key=our_name.get):
            row = [
                (their_name[t], round(plan.matchup.get((o, t), 0.0), 1))
                for t in sorted(their_name, key=their_name.get)
            ]
            matchups.append([our_name[o], row])
        return ours, their_info, plan.opp_cores[:2], matchups, our_name, their_name

    def _apply_llm(self, plan: Plan, llm, our_name: dict, their_name: dict) -> None:
        our_key = {v: k for k, v in our_name.items()}
        their_key = {v: k for k, v in their_name.items()}
        p = llm.raw
        if p.get("lead") in our_key:
            plan.lead = our_key[p["lead"]]
        plan.win_conditions = [our_key[x] for x in p.get("win_conditions", []) if x in our_key]
        plan.preserve = {our_key[x] for x in p.get("preserve", []) if x in our_key}
        plan.preserve |= set(plan.win_conditions)
        plan.threats = [their_key[x] for x in p.get("threats", []) if x in their_key]
        plan.answers = {
            their_key[t]: [our_key[a] for a in v if a in our_key]
            for t, v in (p.get("answers") or {}).items()
            if t in their_key
        }
        tt = p.get("tera_target")
        plan.tera_target = our_key.get(tt) if tt else None
        plan.pace = p.get("pace", "balanced")
        plan.hazards_priority = p.get("hazards_priority", "normal")
        plan.source = "llm"
        plan.llm_raw = p
        plan.llm = {
            "key": llm.key[:16],
            "cached": llm.cached,
            "cost_usd": round(llm.cost_usd, 5),
            "latency_s": round(llm.latency_s, 2),
            "problems": llm.problems,
            "game_plan": p.get("game_plan", ""),
            "their_win_route": p.get("their_win_route", ""),
        }

    async def teampreview(self, battle: AbstractBattle) -> str:
        try:
            sync_tera_types(battle)
            plan = self.make_plan(battle)
            if self.plan_mode == "llm":
                import asyncio

                from alpha_poke.agents.llm_plan import LLMPlanner

                try:
                    if self._planner is None:
                        self._planner = LLMPlanner(model=self.llm_model)
                    ours, info, cores, matchups, our_name, their_name = self._llm_inputs(
                        battle, plan
                    )
                    llm = await asyncio.to_thread(self._planner.plan, ours, info, cores, matchups)
                    self._apply_llm(plan, llm, our_name, their_name)
                except Exception as e:  # noqa: BLE001 - keep playing with the computed plan
                    log.exception("LLM plan failed; using the computed plan")
                    plan.source = "computed(llm-failed)"
                    plan.llm = {"error": f"{type(e).__name__}: {e}"[:200]}
            self.plans[battle.battle_tag] = plan
            if self.use_plan:
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
        sync_tera_types(battle)
        me, opp = battle.active_pokemon, battle.opponent_active_pokemon
        if me is None or opp is None:
            return self.choose_random_move(battle)
        plan = self.plans.get(battle.battle_tag)
        if plan is None:
            plan = self.plans[battle.battle_tag] = self.make_plan(battle)
        state = plan.exec_state
        if state is None and self.use_plan:
            state = self._init_exec(battle, plan)
        if state is not None:
            state.update(battle)
        mv = own_view(me)
        ov, ov_moves = self._opp(battle, opp)
        opp_move, incoming = best_damage(ov, mv, ov_moves, battle)
        opp_kos_me = incoming >= me.current_hp_fraction
        forced = not battle.available_moves

        tactical: list[tuple[float, object]] = []
        if battle.available_moves:
            tactical += self._score_moves(battle, plan, mv, ov, incoming, opp_kos_me, ov_moves)
        for s in battle.available_switches:
            tactical.append(
                (self._score_switch(battle, plan, s, ov, ov_moves, opp_move, forced), s)
            )
        if not tactical:
            return self.choose_random_move(battle)
        mem = self.memory.setdefault(battle.battle_tag, BattleMemory())
        mem.observe(battle)
        rows = []
        for v, c in tactical:
            terms: dict[str, float] = {}
            dmg = damage_fraction(mv, ov, c[0], battle) if isinstance(c, tuple) else None
            first = moves_first(mv, ov, c[0], battle) if isinstance(c, tuple) else None
            if state is not None:
                ctx = {
                    "forced": forced,
                    "opp_hp": opp.current_hp_fraction,
                    "safe": incoming < 0.35 and me.current_hp_fraction >= 0.6,
                    "lead": plan.lead,
                    "tactical": v,
                }
                if isinstance(c, tuple):
                    d = damage_fraction(mv, ov, c[0], battle)
                    ctx["damage"] = d
                    if c[1]:  # tera option: respect the plan's tera directive
                        tera_ctx = {
                            "secures_ko": d >= opp.current_hp_fraction,
                            "saves_from_ko": opp_kos_me,
                        }
                        if not state.tera_allowed(battle, me.species, tera_ctx):
                            continue
                terms = plan_terms(state, battle, c, ctx)
            loop = self._loop_adjust(battle, mem, c, v) if self.anti_loop else 0.0
            rows.append(
                {
                    "dmg": dmg,
                    "first": first,
                    "choice": c,
                    "tactical": v,
                    "plan": terms,
                    "loop": loop,
                    "total": v + sum(terms.values()) + loop,
                }
            )
        best = max(rows, key=lambda r: r["total"])
        choice = best["choice"]
        mem.record(battle, choice)
        if self.trace_dir:
            self._trace(battle, mem, rows, best, incoming, state)
        if isinstance(choice, Pokemon):
            return self.create_order(choice)
        move, tera = choice
        return self.create_order(move, terastallize=tera)

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
        best_tactical = max(rows, key=lambda r: r["tactical"] + r["loop"])
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

    def _score_moves(self, battle, plan, mv, ov, incoming, opp_kos_me, ov_moves=()):
        me, opp = mv.mon, ov.mon
        opp_hp = opp.current_hp_fraction
        n_opp_left = 6 - sum(m.fainted for m in battle.opponent_team.values())
        n_my_left = sum(not m.fainted for m in battle.team.values())
        is_wincon = me.species in plan.win_conditions
        out = []
        for move in battle.available_moves:
            first = moves_first(mv, ov, move, battle)
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
            else:
                v = self._status_value(
                    battle, move, mv, ov, incoming, n_opp_left, n_my_left, is_wincon
                )
            if opp_kos_me and first < 1.0:
                v *= 0.15  # we probably faint before acting
            out.append((v, (move, False)))
            tera_allowed = (
                plan.tera_target is None
                or plan.tera_target == me.species
                or (sum(not m.fainted for m in battle.team.values()) == 1)
            )
            if battle.can_tera and me.tera_type is not None and is_damaging(move) and tera_allowed:
                tv = self._tera_value(battle, plan, move, mv, ov, opp_kos_me, first)
                if tv is not None:
                    out.append((tv, (move, True)))
        return out

    def _status_value(self, battle, move, mv, ov, incoming, n_opp_left, n_my_left, is_wincon):
        me, opp = mv.mon, ov.mon
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
        if mid in REMOVAL:
            layers = len([c for c in battle.side_conditions if c in HAZARDS.values()])
            return hz * 0.3 * layers if n_my_left >= 2 else 0.0
        if move.heal:
            missing = 1 - me.current_hp_fraction
            v = max(0.0, min(move.heal, missing) - 0.5 * incoming) if missing > 0.35 else 0.0
            return v * (1.3 if defensive else 1.0)
        if move.boosts and move.target == "self":
            if any(me.boosts.get(s, 0) >= 4 for s in move.boosts):
                return 0.0
            safe = incoming < 0.35 and me.current_hp_fraction >= 0.6
            return (0.45 + (0.1 if is_wincon else 0.0)) if safe else 0.05
        if opp.status is None and move.status is not None:
            types = set(opp.types)
            if (
                mid == "willowisp"
                and PokemonType.FIRE not in types
                and ov.stats["atk"] > ov.stats["spa"]
            ):
                return 0.4
            if mid == "thunderwave" and not types & {PokemonType.ELECTRIC, PokemonType.GROUND}:
                return 0.35 if moves_first(mv, ov, None, battle) < 1 else 0.15
            if mid == "toxic" and not types & {PokemonType.POISON, PokemonType.STEEL}:
                return 0.3
            if mid in SLEEP and not any(
                m.status and m.status.name == "SLP" for m in battle.opponent_team.values()
            ):
                return 0.55
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
        defensive = False
        if opp_kos_me:
            mult_now = max((me.damage_multiplier(t) for t in opp.types if t), default=1)
            mult_tera = max(
                (t.damage_multiplier(tera, None, type_chart=_TYPE_CHART) for t in opp.types if t),
                default=1,
            )
            defensive = mult_tera < mult_now
        if not (secures_ko or defensive):
            return None
        is_wincon = me.species in plan.win_conditions
        last = sum(not m.fainted for m in battle.team.values()) == 1
        if not (is_wincon or last or secures_ko):
            return None
        v = min(d, opp.current_hp_fraction) + (KO_BONUS if d >= opp.current_hp_fraction else 0)
        if defensive:
            v += 0.3
        return v + (0.1 if is_wincon else 0.0)

    def _score_switch(self, battle, plan, s, ov, ov_moves, opp_move, forced: bool) -> float:
        sv = own_view(s)
        taken = 0.0
        if not forced and opp_move is not None:
            taken = damage_fraction(ov, sv, opp_move, battle)
        hp_after = max(0.0, s.current_hp_fraction - taken)
        if hp_after <= 0:
            return -1.0
        # live 1v1 (current boosts / HP of the opponent): the preview table goes stale
        mu = one_v_one(sv, ov, list(s.moves.values()), ov_moves, battle)
        # matchup was computed at full HP; scale by remaining HP
        mu = mu * (0.5 + 0.5 * hp_after)
        v = 0.6 * mu - taken
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
        return v


from poke_env.data import GenData  # noqa: E402

_TYPE_CHART = GenData.from_gen(9).type_chart
