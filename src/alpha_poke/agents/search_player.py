"""Search-based player: belief-sampled determinizations + poke-engine MCTS (root parallel).

Team preview (LLM plan, lead) is the KnowledgePlayer's. Every decision:
  1. draw ``samples`` full opponent sets from the belief model (engine_state.build_state),
  2. run poke-engine's MCTS on each determinization for search_ms / samples,
  3. average the root visit shares of our options across the samples (+ an optional small plan
     prior), play the best one that maps to a legal order.
Any failure falls back to the KnowledgePlayer's heuristic decision (counted in ``fallbacks``).
"""

import json
import logging
import os
import random
import time
from collections import defaultdict
from pathlib import Path

import poke_engine as pe

from alpha_poke.agents.engine_state import build_state, engine_move_to_order
from alpha_poke.agents.knowledge_player import KnowledgePlayer, sync_tera_types

log = logging.getLogger("alpha_poke.search")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class SearchPlayer(KnowledgePlayer):
    def __init__(self, *args, search_ms=None, samples=None, threads=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_ms = search_ms or _env_int("ALPHA_SEARCH_MS", 1000)
        self.samples = samples or _env_int("ALPHA_SEARCH_SAMPLES", 4)
        self.threads = threads or _env_int("ALPHA_SEARCH_THREADS", 1)
        self.search_fallbacks = 0

    def choose_move(self, battle):
        try:
            order = self._search(battle)
            if order is not None:
                return order
        except Exception:  # noqa: BLE001 - never lose a game to a search bug
            log.exception("search failed; heuristic decision")
        self.search_fallbacks += 1
        return super().choose_move(battle)

    def _search(self, battle):
        sync_tera_types(battle)
        if battle.active_pokemon is None or battle.opponent_active_pokemon is None:
            return None
        names = self._opp_team_names(battle)
        rng = random.Random(f"{battle.battle_tag}:{battle.turn}:{len(battle.available_moves)}")
        per = max(20, self.search_ms // self.samples)
        share: dict[str, float] = defaultdict(float)
        t0 = time.time()
        iters = 0
        for _ in range(self.samples):
            state = build_state(battle, self.belief, names, rng)
            res = pe.monte_carlo_tree_search(state, per, 0, self.threads)
            iters += res.total_visits
            total = sum(x.visits for x in res.side_one) or 1
            for x in res.side_one:
                share[x.move_choice] += x.visits / total / self.samples
        ranked = sorted(share.items(), key=lambda kv: -kv[1])
        order = None
        chosen = None
        for choice, _ in ranked:
            order = engine_move_to_order(self, battle, choice)
            if order is not None:
                chosen = choice
                break
        if self.trace_dir:
            self._trace_search(battle, ranked, chosen, iters, time.time() - t0)
        return order

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
