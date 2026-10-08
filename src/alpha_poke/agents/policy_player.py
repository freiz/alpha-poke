"""A bot that plays the transformer network's policy without search, sampled with temperature
``tau`` and with the rating input of its choice: the model of a specific human player
(design D5-O step 2: rating ~ their ladder rating, tau fit to their decisions).

Per decision: ``worlds`` belief-sampled states, the network's root priors for each (Rust,
``alpha_search.root_priors``), averaged, ** (1 / tau), sampled."""

import os
import random
from collections import defaultdict

import alpha_search

from alpha_poke.agents import net_context
from alpha_poke.agents.engine_state import build_state, engine_move_to_order
from alpha_poke.agents.knowledge_player import sync_tera_types
from alpha_poke.agents.search_player import SearchPlayer


class PolicyPlayer(SearchPlayer):
    def __init__(self, *args, rating: int | None = None, tau: float | None = None,
                 policy_worlds: int = 4, seed: int | None = None, **kwargs):  # fmt: skip
        """``rating``: the rating input (0 = unknown; default ALPHA_POLICY_RATING or 0);
        ``tau``: the temperature (default ALPHA_POLICY_TAU or 1)."""
        super().__init__(*args, **kwargs)
        assert self.model_transformer, "PolicyPlayer needs a transformer model"
        self.rating = (
            rating if rating is not None else int(os.environ.get("ALPHA_POLICY_RATING", 0))
        )
        self.tau = tau if tau is not None else float(os.environ.get("ALPHA_POLICY_TAU", 1.0))
        self.policy_worlds = policy_worlds
        self._rng = random.Random(seed)

    def _search(self, battle):
        sync_tera_types(battle)
        if battle.active_pokemon is None or battle.opponent_active_pokemon is None:
            return None
        names = self._opp_team_names(battle)
        rng = random.Random(f"{battle.battle_tag}:{battle.turn}:{len(battle.available_moves)}")
        states = [build_state(battle, self.belief, names, rng, move_beta=self.move_beta)
                  for _ in range(self.policy_worlds)]  # fmt: skip
        ctxs = net_context.contexts(battle, states)
        # the modelled player's rating as our own rating input (the opponent's stays)
        ctxs = [(rv, (self.rating, rt[1]), turn, hist) for rv, rt, turn, hist in ctxs]
        prior: dict[str, float] = defaultdict(float)
        for st, ctx in zip(states, ctxs, strict=True):
            for choice, p in alpha_search.root_priors([st.to_string()], self.model, [ctx]):
                prior[choice] += p / len(states)
        options = [(c, p ** (1 / self.tau)) for c, p in prior.items() if p > 0]
        options = [(c, w, engine_move_to_order(self, battle, c)) for c, w in options]
        options = [(c, w, o) for c, w, o in options if o is not None]
        if not options:
            return None
        total = sum(w for _, w, _ in options)
        x = self._rng.random() * total
        for _, w, o in options:
            x -= w
            if x <= 0:
                return o
        return options[-1][2]
