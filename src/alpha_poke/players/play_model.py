"""Step 2 of design D5-O: how a specific player chooses, as the network's policy with a rating
input r (own rating; the opponent's stays as in the game) and a temperature tau:
  pi_o(a | s) = softmax(logits(s; rating = r) / tau).
(r, tau) are fit by maximum likelihood of the player's decisions in their games; only two
parameters, so a few dozen games are enough without overfitting the network itself.

Decision points come from the training pipeline (``positions_from_replay`` with every decision
point: turn starts, forced and pivot switches); positions without a full label (actions we
could not see) are left out. Inference: the Rust network (``alpha_search.tnet_forward``)."""

import random

import alpha_search
import numpy as np

from alpha_poke.players.games import Game
from alpha_poke.train.positions import positions_from_replay


def decisions(games: list[Game], belief, side: str = "player", seed: int = 0) -> list[tuple]:
    """[(game index, Position)] of the player's decisions (``side="opponent"``: of their
    opponents), fully labeled only."""
    out = []
    for gi, g in enumerate(games):
        want = g.side if side == "player" else ("p2" if g.side == "p1" else "p1")
        rng = random.Random(seed * 100003 + gi)
        for p in positions_from_replay(g.replay, belief, rng, per_game=0, pool="all"):
            if p.side == want and p.action >= 0:
                out.append((gi, p))
    return out


def logits(model_dir: str, pos: list, rating: int | None) -> np.ndarray:
    """[n, 14] policy logits (-inf = illegal) with the player's rating input set to ``rating``
    (None: the rating of the game; 0: unknown)."""
    ps = [p for _, p in pos]
    ratings = [((p.rating_own if rating is None else rating), p.rating_opp) for p in ps]
    lg, _ = alpha_search.tnet_forward(
        model_dir, [p.state for p in ps], [list(p.reveal) for p in ps], ratings,
        [p.turn for p in ps], [p.history for p in ps], False,
    )  # fmt: skip
    return np.asarray(lg, np.float32).reshape(-1, 14)


def scores(lg: np.ndarray, actions: np.ndarray, tau: float) -> tuple[np.ndarray, np.ndarray]:
    """(log-likelihood of each chosen action, whether it is the top choice)."""
    z = np.where(np.isfinite(lg), lg / tau, -np.inf)
    z = z - z.max(1, keepdims=True)
    logp = z - np.log(np.exp(z).sum(1, keepdims=True))
    ll = logp[np.arange(len(actions)), actions]
    return ll, lg.argmax(1) == actions
