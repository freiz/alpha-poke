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

import logging
import random
from dataclasses import dataclass, field

from poke_env.battle import (
    AbstractBattle,
    Battle,
    MoveCategory,
    Pokemon,
    PokemonType,
    SideCondition,
)
from poke_env.battle.move import Move
from poke_env.player import Player, SimpleHeuristicsPlayer

from alpha_poke.agents.belief_state import BeliefModel, own_view
from alpha_poke.agents.damage import MonView, best_damage, damage_fraction, moves_first, one_v_one

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

    def summary(self) -> str:
        return (
            f"lead={self.lead} wincons={self.win_conditions} threats={self.threats[:3]} "
            f"answers={ {t: self.answers.get(t, []) for t in self.threats[:3]} } "
            f"opp_cores={self.opp_cores[:2]}"
        )


class KnowledgePlayer(Player):
    def __init__(
        self,
        belief: BeliefModel,
        library: dict | None = None,
        use_plan: bool = True,
        plan_lead: bool = True,
        lead_prior: str = "human",
        random_lead: bool = False,
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

    def teampreview(self, battle: AbstractBattle) -> str:
        try:
            plan = self.make_plan(battle)
            self.plans[battle.battle_tag] = plan
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
        me, opp = battle.active_pokemon, battle.opponent_active_pokemon
        if me is None or opp is None:
            return self.choose_random_move(battle)
        plan = self.plans.get(battle.battle_tag)
        if plan is None:
            plan = self.plans[battle.battle_tag] = self.make_plan(battle)
        mv, ov_moves = own_view(me), None
        ov, ov_moves = self._opp(battle, opp)
        opp_move, incoming = best_damage(ov, mv, ov_moves, battle)
        opp_kos_me = incoming >= me.current_hp_fraction

        options: list[tuple[float, object]] = []
        if battle.available_moves:
            options += self._score_moves(battle, plan, mv, ov, incoming, opp_kos_me)
        for s in battle.available_switches:
            options.append(
                (
                    self._score_switch(
                        battle, plan, s, ov, ov_moves, opp_move, forced=not battle.available_moves
                    ),
                    s,
                )
            )
        if not options:
            return self.choose_random_move(battle)
        score, choice = max(options, key=lambda x: x[0])
        if isinstance(choice, Pokemon):
            return self.create_order(choice)
        move, tera = choice
        return self.create_order(move, terastallize=tera)

    def _score_moves(self, battle, plan, mv, ov, incoming, opp_kos_me):
        me, opp = mv.mon, ov.mon
        opp_hp = opp.current_hp_fraction
        n_opp_left = 6 - sum(m.fainted for m in battle.opponent_team.values())
        n_my_left = sum(not m.fainted for m in battle.team.values())
        is_wincon = me.species in plan.win_conditions
        out = []
        for move in battle.available_moves:
            first = moves_first(mv, ov, move, battle)
            v = 0.0
            if move.category != MoveCategory.STATUS and move.base_power:
                d = damage_fraction(mv, ov, move, battle)
                v = min(d, opp_hp)
                if d >= opp_hp:
                    v += 0.5
                if opp.species in plan.threats[:2]:
                    v *= 1.15
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
            if battle.can_tera and me.tera_type is not None and move.base_power:
                tv = self._tera_value(battle, plan, move, mv, ov, opp_kos_me, first)
                if tv is not None:
                    out.append((tv, (move, True)))
        return out

    def _status_value(self, battle, move, mv, ov, incoming, n_opp_left, n_my_left, is_wincon):
        me, opp = mv.mon, ov.mon
        mid = move.id
        if mid in HAZARDS:
            if HAZARDS[mid] in battle.opponent_side_conditions and mid != "spikes":
                return 0.0
            if (
                mid == "spikes"
                and battle.opponent_side_conditions.get(SideCondition.SPIKES, 0) >= 3
            ):
                return 0.0
            return (0.4 if mid == "stealthrock" else 0.3) * min(1.0, n_opp_left / 4)
        if mid in REMOVAL:
            layers = len([c for c in battle.side_conditions if c in HAZARDS.values()])
            return 0.3 * layers if n_my_left >= 2 else 0.0
        if move.heal:
            missing = 1 - me.current_hp_fraction
            return max(0.0, min(move.heal, missing) - 0.5 * incoming) if missing > 0.35 else 0.0
        if move.boosts and move.target == "self":
            if any(me.boosts.get(s, 0) >= 4 for s in move.boosts):
                return 0.0
            safe = incoming < 0.35 and me.current_hp_fraction >= 0.6
            return (0.45 + (0.15 if is_wincon else 0.0)) if safe else 0.05
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
        v = min(d, opp.current_hp_fraction) + (0.5 if d >= opp.current_hp_fraction else 0)
        if defensive:
            v += 0.3
        return v + (0.1 if is_wincon else 0.0)

    def _score_switch(self, battle, plan, s, ov, ov_moves, opp_move, forced: bool) -> float:
        sv = own_view(s)
        opp = ov.mon
        taken = 0.0
        if not forced and opp_move is not None:
            taken = damage_fraction(ov, sv, opp_move, battle)
        hp_after = max(0.0, s.current_hp_fraction - taken)
        if hp_after <= 0:
            return -1.0
        mu = plan.matchup.get((s.species, opp.species))
        if mu is None:
            mu = one_v_one(sv, ov, list(s.moves.values()), ov_moves, battle)
        # matchup was computed at full HP; scale by remaining HP
        mu = mu * (0.5 + 0.5 * hp_after)
        v = 0.6 * mu - taken
        if s.species in plan.answers.get(opp.species, []):
            v += 0.15
        if s.species in plan.preserve and taken > 0.35:
            v -= 0.2
        if s.species in plan.win_conditions and forced and mu < 0.3:
            v -= 0.15  # don't throw the win condition in early
        if not forced:
            v -= 0.12  # tempo cost of switching
        return v


from poke_env.data import GenData  # noqa: E402

_TYPE_CHART = GenData.from_gen(9).type_chart
