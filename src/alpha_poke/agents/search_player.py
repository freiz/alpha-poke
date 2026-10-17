"""Search player: ISMCTS over belief-sampled worlds (design D12, rust/alpha_search).

Team preview (computed plan, lead) is the KnowledgePlayer's. Every decision: ``worlds``
determinizations from the belief model (engine_state.build_state) go to ONE information-set
tree; the time spent building them is taken out of the search budget. With a transformer model
(design D13) the per-world contexts (history, public-information bits, ratings, turn) come from
``net_context`` (their time is taken out of the budget too), the network gives the leaf values
and, with ``net_policy``, the PUCT priors; on the GPU (``device="cuda"``) one batched tree
(agents.gpu_search). The most visited option that maps to a legal order is played. Any failure
falls back to the KnowledgePlayer's heuristic decision (counted in ``search_fallbacks``).
"""

import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path

import alpha_search
from poke_env.player.battle_order import ForfeitBattleOrder

from alpha_poke.agents import net_context
from alpha_poke.agents.consistency import request_mismatch
from alpha_poke.agents.engine_state import build_state, engine_move_to_order
from alpha_poke.agents.knowledge_player import KnowledgePlayer, sync_tera_types

log = logging.getLogger("alpha_poke.search")
TURN_CAP = int(os.environ.get("ALPHA_TURN_CAP", 300))  # = eval.arena.TURN_CAP


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


def _is_transformer(model_dir: str) -> bool:
    try:
        cfg = json.loads((Path(model_dir) / "config.json").read_text())
        return cfg.get("arch") == "transformer"
    except (OSError, ValueError):
        return False


class SearchPlayer(KnowledgePlayer):
    def __init__(
        self,
        *args,
        search_ms=None,
        threads=None,
        move_beta=None,
        worlds=None,
        model=None,
        net_policy=None,
        device=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.search_ms = search_ms or _env_int("ALPHA_SEARCH_MS", 1000)
        self.threads = threads or _env_int("ALPHA_SEARCH_THREADS", 1)  # Rust threads
        self.search_fallbacks = 0
        self.revives = 0  # Revival Blessing choices (searched per candidate)
        self.mismatches = 0  # decisions whose request offered options the engine state lacked
        # sampled moves x team-conditioned move marginal ** move_beta (0 = archetype only; default
        # 1 since 2026-10-06: coverage of later revealed moves 61.7% -> 77.3%, design D11)
        self.move_beta = move_beta if move_beta is not None else _env_float("ALPHA_MOVE_BETA", 1.0)
        self.worlds = worlds or _env_int("ALPHA_ISMCTS_WORLDS", 32)
        # leaf values (and priors) from a trained network (run directory, design D13); None =
        # poke-engine's handcrafted evaluation
        self.model = model or os.environ.get("ALPHA_SEARCH_MODEL") or None
        if self.model and not _is_transformer(self.model):
            raise ValueError(f"{self.model}: not a transformer run (the only network)")
        self.model_transformer = bool(self.model)
        # the GPU: one batched tree, `gpu_threads` threads descending it, `gpu_batch` leaves per
        # network call (agents.gpu_search); "cpu" = Rust CPU inference
        self.device = device or os.environ.get("ALPHA_SEARCH_DEVICE", "cpu")
        self.gpu_threads = _env_int("ALPHA_GPU_THREADS", 8)
        self.gpu_batch = _env_int("ALPHA_GPU_BATCH", 32)
        # > 0: a fixed number of iterations (leaves) per decision instead of the time budget
        # (equal-work comparisons, e.g. GPU vs CPU search)
        self.search_iterations = _env_int("ALPHA_SEARCH_ITERATIONS", 0)
        self._gpu = None
        # PUCT with the network's policy priors: None = off, "both" = both sides, "ours" = ours
        # only (the opponent keeps UCB1)
        self.net_policy = net_policy or os.environ.get("ALPHA_NET_POLICY") or None
        # the moves-left term of the CPU search (ALPHA_ML "slope,cap,threshold"; design v6)
        from alpha_poke.selfplay.batcher import parse_ml

        self.ml = parse_ml(os.environ.get("ALPHA_ML"))
        assert self.net_policy in (None, "both", "ours"), self.net_policy

    def close(self) -> None:
        if self._gpu is not None:
            self._gpu.close()
            self._gpu = None

    def choose_move(self, battle):
        if battle.turn >= TURN_CAP:  # evaluation: a draw at the cap (eval.arena scores it 0.5)
            return ForfeitBattleOrder()
        try:
            order = self._search(battle)
            if order is not None:
                return order
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except BaseException as e:  # noqa: BLE001 - never lose (or hang) a game to a search bug;
            # BaseException: an engine panic (pyo3 PanicException) is not an Exception
            log.exception("search failed; heuristic decision")
            self._trace_fallback(battle, f"error: {e!r}"[:300])
        self.search_fallbacks += 1
        return super().choose_move(battle)

    def _run(self, states, ctxs, budget: int, rng) -> tuple[list, int]:
        """A search of ``states`` (``budget`` ms): ([(option, visits, mean value)], iterations)."""
        if self.model_transformer and self.device == "cuda":
            return self._gpu_search(states, ctxs, budget, rng)
        ours, n, _, _ = alpha_search.ismcts(
            [s.to_string() for s in states],
            budget,
            iterations=self.search_iterations,
            threads=self.threads,
            model_dir=self.model,
            use_policy=self.net_policy is not None,
            policy_opponent=self.net_policy == "both",
            contexts=ctxs,
            ml=self.ml,
        )
        return ours, n

    def _revive(self, battle):
        """Revival Blessing's choice (a fainted mon back at half HP; the engine's own pick, L166,
        needs the foe's pending move, unknown here): each candidate's state after it, searched (the time split between them), the best root
        value. (2026-10-11: the search ran as for a switch, its options -- live benched mons --
        had no order, and the heuristic chose.)"""
        cands = list(battle.available_switches)
        if len(cands) <= 1:
            return self.create_order(cands[0]) if cands else None
        names = self._opp_team_names(battle)
        rng = random.Random(f"{battle.battle_tag}:{battle.turn}:revive")
        budget = max(20, self.search_ms // len(cands))
        vals = {}
        for m in cands:
            states = [build_state(battle, self.belief, names, rng, move_beta=self.move_beta,
                                  force_switch=False, revived=m.species)
                      for _ in range(self.worlds)]  # fmt: skip
            ctxs = net_context.contexts(battle, states) if self.model_transformer else None
            ours, _ = self._run(states, ctxs, budget, rng)
            total = sum(v for _, v, _ in ours) or 1
            vals[m.species] = sum(v * q for _, v, q in ours) / total
        self.revives += 1
        best = max(cands, key=lambda m: vals[m.species])
        log.info("revive (%s turn %d): %s", battle.battle_tag, battle.turn, vals)
        return self.create_order(best)

    def _search(self, battle):
        sync_tera_types(battle)
        if battle.reviving:
            return self._revive(battle)
        if battle.active_pokemon is None or battle.opponent_active_pokemon is None:
            self._trace_fallback(battle, "no active pokemon")
            return None
        names = self._opp_team_names(battle)
        rng = random.Random(f"{battle.battle_tag}:{battle.turn}:{len(battle.available_moves)}")
        t0 = time.time()
        states = [build_state(battle, self.belief, names, rng, move_beta=self.move_beta)
                  for _ in range(self.worlds)]  # fmt: skip
        issues = request_mismatch(battle, states[0])
        if issues:
            self.mismatches += 1
            log.warning("request / engine state mismatch (%s turn %d): %s", battle.battle_tag,
                        battle.turn, issues)  # fmt: skip
        ctxs = net_context.contexts(battle, states) if self.model_transformer else None
        budget = max(20, self.search_ms - int((time.time() - t0) * 1000))
        ours, n = self._run(states, ctxs, budget, rng)
        total = sum(v for _, v, _ in ours) or 1
        ranked = sorted(((c, v / total) for c, v, _ in ours), key=lambda kv: -kv[1])
        orders = [(c, s, engine_move_to_order(self, battle, c)) for c, s in ranked]
        orders = [(c, s, o) for c, s, o in orders if o is not None]
        if not orders:
            self._trace_fallback(battle, f"no legal order among {[c for c, _ in ranked[:6]]}")
            return None
        chosen, _, order = orders[0]
        if self.trace_dir:
            self._trace_search(battle, ranked, chosen, n, time.time() - t0)
        return order

    def _gpu_search(self, states, ctxs, budget_ms: int, rng) -> tuple[list, int]:
        """The batched search with the network on the GPU (agents.gpu_search)."""
        if self._gpu is None:
            from alpha_poke.agents.gpu_net import GpuNet  # torch only when used
            from alpha_poke.agents.gpu_search import GpuSearch

            self._gpu = GpuSearch(GpuNet(self.model), self.gpu_batch, self.gpu_threads)
        ours, n, _ = self._gpu.run(
            [s.to_string() for s in states],
            ctxs,
            budget_ms / 1000,
            seed=rng.randrange(1 << 30),
            iterations=self.search_iterations,
        )
        return ours, n

    def _trace_fallback(self, battle, reason: str) -> None:
        """Why the search gave no order (the heuristic decides instead)."""
        if not self.trace_dir:
            return
        row = {
            "turn": battle.turn,
            "fallback": reason,
            "force_switch": battle.force_switch,
            "moves": [m.id for m in battle.available_moves],
            "switches": [m.species for m in battle.available_switches],
        }
        d = Path(self.trace_dir)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{battle.battle_tag}_{self.username}.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def _trace_search(self, battle, ranked, chosen, iters, seconds) -> None:
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
        d = Path(self.trace_dir)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{battle.battle_tag}_{self.username}.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
