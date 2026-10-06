"""Search-based player: belief-sampled determinizations + poke-engine MCTS (root parallel).

Team preview (LLM plan, lead) is the KnowledgePlayer's. Every decision:
  1. draw ``samples`` full opponent sets from the belief model (engine_state.build_state),
  2. run poke-engine's MCTS on each determinization: with ``workers`` > 1 the samples run in
     parallel single-threaded processes for the full search_ms each (poke-engine's mcts holds
     the GIL; one multi-threaded shared-tree search gets ~40% of the iterations), otherwise
     sequentially for search_ms / samples each,
  3. average the root visit shares of our options across the samples, play the best one that
     maps to a legal order.
ISMCTS backend (``backend="ismcts"``, design D12): ``worlds`` determinizations go to ONE
information-set tree (rust/alpha_search); the time spent building them is taken out of the
search budget so that the decision time matches the determinized backend.
Plan prior (design D11, A1; ``plan_prior`` > 0, env ALPHA_PLAN_PRIOR): the KnowledgePlayer's
plan terms of each option (goals, assignments, rules, ...; the same trust checks as the
heuristic) are added to the visit shares as ``plan_prior * plan_total``, and tera options the
plan's tera directive forbids are dropped. It only moves the choice between close options.
Without it the plan only picks the lead.
Any failure falls back to the KnowledgePlayer's heuristic decision (counted in ``fallbacks``).
"""

import asyncio
import json
import logging
import os
import random
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import alpha_search
from poke_env.battle import Pokemon

from alpha_poke.agents import mcts_worker
from alpha_poke.agents.engine_state import build_state, engine_move_to_order, oracle_sets
from alpha_poke.agents.knowledge_player import KnowledgePlayer, sync_tera_types

log = logging.getLogger("alpha_poke.search")
ORACLE_FIELDS = frozenset({"item", "moves", "tera", "ability", "spread"})


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _option_key(choice) -> tuple:
    """Same key for a KnowledgePlayer row choice ((move, tera) or a Pokemon) and an order."""
    if isinstance(choice, tuple):
        return ("move", choice[0].id, bool(choice[1]))
    return ("switch", choice.species)


def _order_key(order) -> tuple:
    o = order.order
    if isinstance(o, Pokemon):
        return ("switch", o.species)
    return ("move", o.id, bool(order.terastallize))


class SearchPlayer(KnowledgePlayer):
    def __init__(
        self,
        *args,
        search_ms=None,
        samples=None,
        threads=None,
        plan_prior=None,
        oracle=False,
        move_beta=None,
        backend=None,
        worlds=None,
        chance_depth=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # oracle (local evaluation only, design D11 B): the evaluator hands us the opponent's
        # true team with set_oracle() before every game; the search then samples nothing.
        # oracle="item,moves" (subset of item / moves / tera / ability / spread): only those
        # fields are true, the rest is sampled from the belief as usual.
        self.use_oracle = bool(oracle)
        self.oracle_fields = None if oracle is True or not oracle else frozenset(oracle.split(","))
        assert self.oracle_fields is None or self.oracle_fields <= ORACLE_FIELDS, oracle
        self.oracle = None
        self.plan_prior = (
            plan_prior if plan_prior is not None else _env_float("ALPHA_PLAN_PRIOR", 0.0)
        )
        self.search_ms = search_ms or _env_int("ALPHA_SEARCH_MS", 1000)
        self.samples = samples or _env_int("ALPHA_SEARCH_SAMPLES", 4)
        self.threads = threads or _env_int("ALPHA_SEARCH_THREADS", 1)  # = worker processes
        self.search_fallbacks = 0
        # sampled moves x team-conditioned move marginal ** move_beta (0 = archetype only; default
        # 1 since 2026-10-06: coverage of later revealed moves 61.7% -> 77.3%, design D11)
        self.move_beta = move_beta if move_beta is not None else _env_float("ALPHA_MOVE_BETA", 1.0)
        self._row_choice: dict = {}
        self._pool = None
        # "determinized" (K independent poke-engine trees) or "ismcts" (one tree, design D12)
        self.backend = backend or os.environ.get("ALPHA_SEARCH_BACKEND", "determinized")
        self.worlds = worlds or _env_int("ALPHA_ISMCTS_WORLDS", 32)
        # ISMCTS: split shallow children by the observable outcome below this depth (0 = open-loop)
        self.chance_depth = (
            chance_depth if chance_depth is not None else _env_int("ALPHA_ISMCTS_CHANCE_DEPTH", 0)
        )
        assert self.backend in ("determinized", "ismcts"), self.backend

    def _workers(self):
        if self.threads > 1 and self._pool is None:
            self._pool = ProcessPoolExecutor(self.threads, mp_context=get_context("spawn"))
        return self._pool

    def set_oracle(self, team_text: str) -> None:
        self.oracle = oracle_sets(team_text)

    def close(self) -> None:
        """Stop the worker processes (a live pool keeps its parent from exiting)."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def choose_move(self, battle):
        try:
            order = self._search(battle)
            if order is not None:
                return order
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except BaseException:  # noqa: BLE001 - never lose (or hang) a game to a search bug;
            # BaseException: an engine panic (pyo3 PanicException) is not an Exception
            log.exception("search failed; heuristic decision")
        self.search_fallbacks += 1
        return super().choose_move(battle)

    def _search(self, battle):
        sync_tera_types(battle)
        if battle.active_pokemon is None or battle.opponent_active_pokemon is None:
            return None
        names = self._opp_team_names(battle)
        rng = random.Random(f"{battle.battle_tag}:{battle.turn}:{len(battle.available_moves)}")
        share: dict[str, float] = defaultdict(float)
        t0 = time.time()
        iters = 0
        oracle = self.oracle if self.use_oracle else None
        n_states = self.worlds if self.backend == "ismcts" else self.samples
        states = [
            build_state(battle, self.belief, names, rng, oracle, self.oracle_fields, self.move_beta)
            for _ in range(n_states)
        ]
        pool = None if self.backend == "ismcts" else self._workers()
        if self.backend == "ismcts":
            budget = max(20, self.search_ms - int((time.time() - t0) * 1000))
            ours, n, _, _ = alpha_search.ismcts(
                [s.to_string() for s in states], budget, chance_depth=self.chance_depth
            )
            results = [([(c, v) for c, v, _ in ours], n)]
        elif pool is not None:  # parallel: each sample gets the full budget on its own core
            futs = [pool.submit(mcts_worker.run, s.to_string(), self.search_ms) for s in states]
            results = [f.result() for f in futs]
        else:
            per = max(20, self.search_ms // self.samples)
            results = [mcts_worker.search(s, per) for s in states]
        for visits, n in results:
            iters += n
            total = sum(v for _, v in visits) or 1
            for choice, v in visits:
                share[choice] += v / total / len(results)
        ranked = sorted(share.items(), key=lambda kv: -kv[1])
        orders = [(c, s, engine_move_to_order(self, battle, c)) for c, s in ranked]
        orders = [(c, s, o) for c, s, o in orders if o is not None]
        if not orders:
            return None
        prior = self._plan_prior(battle) if self.plan_prior > 0 else None
        scored = []
        for c, s, o in orders:
            p = 0.0
            if prior is not None:
                p = prior.get(_order_key(o))
                if p is None:  # an option the plan rules out (tera against its directive)
                    continue
            scored.append((s + self.plan_prior * p, c, s, p, o))
        if not scored:  # the plan forbids everything the search found: trust the search
            scored = [(s, c, s, 0.0, o) for c, s, o in orders]
        best = max(scored, key=lambda x: x[0])
        if prior is not None and (rc := self._row_choice.get(_order_key(best[4]))) is not None:
            self.memory[battle.battle_tag].record(battle, rc)
        if self.trace_dir:
            self._trace_search(
                battle, ranked, best[1], iters, time.time() - t0,
                prior={c: round(p, 3) for _, c, _, p, _ in scored if p} if prior else None,
                changed=prior is not None and best[1] != orders[0][0],
            )  # fmt: skip
        return best[4]

    def _plan_prior(self, battle) -> dict | None:
        """Plan total of every option the heuristic scores (forbidden tera options are absent).
        Also keeps the battle memory and the plan state up to date."""
        scored = self._score_options(battle)
        if scored is None:
            return None
        rows = scored[0]
        self._row_choice = {_option_key(r["choice"]): r["choice"] for r in rows}
        return {_option_key(r["choice"]): r["plan_total"] for r in rows}

    def _trace_search(
        self, battle, ranked, chosen, iters, seconds, prior=None, changed=False
    ) -> None:
        me, opp = battle.active_pokemon, battle.opponent_active_pokemon
        row = {
            "turn": battle.turn,
            "me": me.species,
            "me_hp": round(me.current_hp_fraction, 3),
            "opp": opp.species,
            "opp_hp": round(opp.current_hp_fraction, 3),
            "our_fainted": sum(m.fainted for m in battle.team.values()),
            "their_fainted": sum(m.fainted for m in battle.opponent_team.values()),
            "search": [[c, round(s, 3)] for c, s in ranked[:6]],
            "chosen": chosen,
            "iterations": iters,
            "seconds": round(seconds, 2),
        }
        if self.use_oracle:
            row["oracle"] = self.oracle is not None
        if prior is not None:
            row["plan_prior"] = prior
            row["plan_changed"] = changed
        d = Path(self.trace_dir)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{battle.battle_tag}_{self.username}.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
