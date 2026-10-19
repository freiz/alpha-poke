"""Search contexts for the transformer network (design D13 v3 / v4): what it reads besides the
state, built from the live battle exactly as the training positions are built from a replay
(alpha_poke.train.positions):

  * history: the decision steps so far (``decision_steps`` + ``history_string`` on the battle's
    log, with the outcomes and the unseen choices);
  * public-information bits per entity of each world's state (``reveal_flags``): the opponent's
    from our battle, ours from a shadow poke-env battle that replays the same log as the
    opponent (what it has seen of us);
  * both players' ratings before the game (``|player|`` lines; 0 = unknown, e.g. local servers);
  * the turn.
"""

import functools
import json
import logging
from pathlib import Path

import alpha_search

from poke_env.battle import Battle

from alpha_poke.replay.parser import ReplayParser
from alpha_poke.train.positions import (
    _IGNORED,
    blind_sides,
    decision_steps,
    history_string,
    reveal_flags,
)

_log = logging.getLogger("alpha_poke.net_context")
_log.setLevel(logging.ERROR)
END = (10**9, 0)  # history key after every step so far


def battle_log(battle) -> list[list[str]]:
    """The battle's protocol messages so far (poke-env keeps every parsed one)."""
    return [m for m in battle._replay_data if len(m) > 1]


def opponent_view(battle, lines: list[list[str]]) -> Battle:
    """A poke-env battle that replays the log as the opponent: its ``opponent_team`` is what
    the opponent has seen of our mons. Kept on ``battle`` and fed the new messages each call
    (``lines`` = battle_log(battle): it only grows)."""
    n, shadow = getattr(battle, "_alpha_shadow", (0, None))
    if shadow is None or n > len(lines):
        n, shadow = 0, Battle(f"{battle.battle_tag}-shadow", battle.opponent_username, _log, gen=9)
    for split in lines[n:]:  # incremental: the messages since the last call (2026-10-11: the
        # whole log replayed at every decision was 18% of a policy-only worker)
        if split[1] in _IGNORED:
            continue
        try:
            shadow.parse_message(split)
        except (NotImplementedError, KeyError, ValueError, AttributeError):
            pass
    battle._alpha_shadow = (len(lines), shadow)
    return shadow


def _parsed(battle, lines: list[list[str]]):
    """parse_replay of the battle's log so far, the parser kept on the battle and fed the lines
    added since the last call (``lines`` = battle_log(battle): it only grows)."""
    n, parser = getattr(battle, "_alpha_parser", (0, None))
    if parser is None or n > len(lines):
        n, parser = 0, ReplayParser({"id": battle.battle_tag, "log": ""})
    parser.feed("|".join(m) for m in lines[n:])
    battle._alpha_parser = (len(lines), parser)
    return parser.replay()


@functools.cache
def model_feats(model_dir: str) -> frozenset:
    """The input groups of a network (its config.json ``feats``)."""
    cfg = json.loads((Path(model_dir) / "config.json").read_text())
    return frozenset(cfg.get("feats", ()))


def needs_full(model_dir: str | None) -> bool:
    """The network reads the v7 entity inputs (ko2 / tera / team): the searches compute them
    (alpha_search.BatchSearch(full=True); the CPU search and root_priors know it themselves)."""
    return bool(model_dir) and bool(model_feats(model_dir) & {"ko2", "tera", "team"})


def needs_post(model_dir: str | None) -> bool:
    """The network reads F2 (``post``): the contexts carry the root worlds' posterior."""
    return bool(model_dir) and "post" in model_feats(model_dir)


def contexts(battle, states, post: bool = False) -> list[tuple]:
    """One (reveal bits [12], (own rating, opponent rating), turn, history) per world state
    (poke_engine.State, side one = us), as alpha_search.ismcts(contexts=...) takes them. ``post``
    (a network with F2): + the action-consequence probabilities over all these worlds
    (alpha_search.posterior: computed once at the root, the same in every world's context)."""
    lines = battle_log(battle)
    side = battle.player_role or "p1"
    other = "p2" if side == "p1" else "p1"
    rep = _parsed(battle, lines)
    steps = decision_steps(rep.actions, blind_sides(rep))
    hist = history_string(steps, END, side)
    ratings = (rep.ratings_before.get(side) or 0, rep.ratings_before.get(other) or 0)
    shadow = opponent_view(battle, lines)
    theirs = list(battle.opponent_team.values())
    ours = list(shadow.opponent_team.values())
    if post:
        p = alpha_search.posterior([st.to_string() for st in states])
        return [(reveal_flags(st, theirs, ours), ratings, int(battle.turn), hist, p)
                for st in states]  # fmt: skip
    return [(reveal_flags(st, theirs, ours), ratings, int(battle.turn), hist) for st in states]
