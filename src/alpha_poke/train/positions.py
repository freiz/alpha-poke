"""Training positions from replay logs (design D13): one per player and turn.

For every ``|turn|N`` of a replay and every player who then chose a move or a voluntary switch,
the position is the poke-engine state at the start of that turn seen by that player (side one):
  * its own team: game-wide revealed parts of each set (the player knows its own sets) + belief
    samples for the rest (``engine_state.SpectatorSide``);
  * the opponent: only what was revealed so far + belief samples (as in the search);
  * label: the action it took, in the fixed 14-slot action space; value: whether it won.
Forced switches after a faint and pivot switches (U-turn, ...) are mid-turn decisions in a
different state and are skipped for now; so are ties and replays the parser warns about.
History (v2): the decision steps before the position, in poke-engine's terms (one per turn for
the chosen actions, one for a pivot switch, one for the forced switches after faints), as the
string alpha_search.featurize_history reads ("OWN/OPP;..." oldest first, the last HIST steps).
"""

import logging
import random
from dataclasses import dataclass

from poke_env.battle import Battle, Pokemon

from alpha_poke.agents.engine_state import KnownSet, SpectatorSide, build_state
from alpha_poke.analysis.roles import to_id
from alpha_poke.replay import parse_replay

N_ACTIONS = 14  # 0-3 move slot, 4-7 move slot + tera, 8-13 switch to team slot
TERA_OFFSET, SWITCH_OFFSET = 4, 8
_IGNORED = {"", "t:", "j", "J", "l", "L", "c", "raw", "inactive", "inactiveoff", "html", "uhtml",
            "chat", "n", "N", "win", "tie", "seed", "bigerror", "error", "debug"}  # fmt: skip
_log = logging.getLogger("alpha_poke.positions")
_log.setLevel(logging.ERROR)


@dataclass
class Position:
    game: str
    side: str  # 'p1' / 'p2': the player to act (side one of ``state``)
    turn: int
    state: str  # poke-engine state string
    action: int
    won: float  # 1.0 if that player won the game, else 0.0
    rating: int | None
    uploadtime: int
    history: str = ""
    future: str = ""  # the decision steps from this one on (MTP targets), same format


HIST = 8  # stored steps (rust/alpha_search/src/features.rs HIST); models may use fewer


def _eng(name: str) -> str:
    return to_id(name.replace("-*", "")).upper()


def _act(a) -> str:
    if a is None:
        return ""
    if a.kind == "move":
        return f"{'t' if a.tera else 'm'}:{_eng(a.mon)}:{_eng(a.move or '')}"
    return f"s:{_eng(a.mon)}:{_eng(a.to or '')}"


def decision_steps(actions) -> dict[int, list[dict]]:
    """Turn -> its decision steps in order, each {side: action or None}: the chosen actions
    (the first move / voluntary switch of each side; none if it could not act), then each pivot
    switch, then the forced switches after faints (one step for both sides)."""
    by_turn: dict[int, list] = {}
    for a in actions:
        if a.turn >= 1 and a.kind in ("move", "switch"):
            by_turn.setdefault(a.turn, []).append(a)
    out = {}
    for t, acts in by_turn.items():
        acts.sort(key=lambda a: a.order)
        main = {}
        for a in acts:
            if not a.forced and not a.pivot:
                main.setdefault(a.side, a)
        steps = [main]
        steps += [{a.side: a} for a in acts if a.pivot]
        forced = {a.side: a for a in acts if a.forced}
        if forced:
            steps.append(forced)
        out[t] = steps
    return out


def history_string(steps: dict[int, list[dict]], turn: int, side: str) -> str:
    """The last HIST steps before ``turn`` from ``side``'s point of view."""
    other = "p2" if side == "p1" else "p1"
    seq = [s for t in sorted(steps) if t < turn for s in steps[t]][-HIST:]
    return ";".join(f"{_act(s.get(side))}/{_act(s.get(other))}" for s in seq)


FUTURE = 4  # stored future steps (step 0 = this decision: own label + the opponent's action)


def future_string(steps: dict[int, list[dict]], turn: int, side: str) -> str:
    """The first FUTURE steps from ``turn`` on, from ``side``'s point of view (oldest first)."""
    other = "p2" if side == "p1" else "p1"
    seq = [s for t in sorted(steps) if t >= turn for s in steps[t]][:FUTURE]
    return ";".join(f"{_act(s.get(side))}/{_act(s.get(other))}" for s in seq)


def _known(rec) -> KnownSet:
    return KnownSet(
        moves=[to_id(m) for m in rec.moves],
        item=to_id(rec.item) if rec.item else None,
        ability=to_id(rec.ability) if rec.ability else None,
        tera=rec.tera_type.lower() if rec.tera_type else None,
    )


def _same_species(a: str, b: str) -> bool:
    a, b = to_id(a.replace("-*", "")), to_id(b.replace("-*", ""))
    return a == b or a.startswith(b) or b.startswith(a)


def _rating(row: dict) -> int | None:
    try:
        return int(row.get("rating"))
    except (TypeError, ValueError):
        return None


def positions_from_replay(
    row: dict, belief, rng: random.Random, move_beta: float = 1.0, per_game: int = 0
):
    """``row``: a replay dict with ``id``, ``log`` (+ ``rating``, ``uploadtime``). ``per_game``
    > 0: only that many decision points, drawn at random (positions within a game are strongly
    correlated and share one outcome: many games x few positions, as AlphaGo's value net); states
    are built only for those, which is the expensive part."""
    rep = parse_replay(row)
    if rep.warnings or rep.winner not in ("p1", "p2"):
        return []
    actions = {}
    for a in rep.actions:
        if a.turn >= 1 and not a.forced and not a.pivot and a.kind in ("move", "switch"):
            actions.setdefault((a.turn, a.side), a)
    if per_game and len(actions) > per_game:
        keep = set(rng.sample(sorted(actions), per_game))
        actions = {k: v for k, v in actions.items() if k in keep}
    lines = row["log"].split("\n")
    names: dict[str, str] = {}
    for x in lines:  # first non-empty name: logs often end with "|player|p1|" (player left)
        f = x.split("|")
        if len(f) > 3 and f[1] == "player" and f[2] in ("p1", "p2") and f[3]:
            names.setdefault(f[2], f[3])
    if set(names) != {"p1", "p2"}:
        return []
    steps = decision_steps(rep.actions)
    battles = {s: Battle(f"battle-{row['id']}-{s}", names[s], _log, gen=9) for s in ("p1", "p2")}
    records = {s: [m for m in rep.teams[s] if not m.phantom] for s in ("p1", "p2")}
    known = {s: {to_id(m.species): _known(m) for m in records[s]} for s in ("p1", "p2")}
    out = []
    for line in lines:
        split = line.split("|")
        if len(split) < 2 or split[1] in _IGNORED:
            continue
        for b in battles.values():
            try:
                b.parse_message(split)
            except (NotImplementedError, KeyError, ValueError, AttributeError):
                pass
        if split[1] != "turn":
            continue
        turn = int(split[2])
        for side in ("p1", "p2"):
            a = actions.get((turn, side))
            if a is None:
                continue
            pos = _position(battles[side], side, a, records[side], known[side], belief, rng,
                            move_beta)  # fmt: skip
            if pos is not None:
                state, action = pos
                out.append(
                    Position(
                        row["id"],
                        side,
                        turn,
                        state,
                        action,
                        float(rep.winner == side),
                        _rating(row),
                        int(row.get("uploadtime") or 0),
                        history_string(steps, turn, side),
                        future_string(steps, turn, side),
                    )  # fmt: skip
                )
    return out


def _position(battle, side, a, records, known, belief, rng, move_beta):
    me = battle.active_pokemon
    if me is None or me.fainted or battle.opponent_active_pokemon is None:
        return None
    team = []
    for rec in records:  # preview order; mons already seen are poke-env's own objects
        mon = next((m for m in battle.team.values() if _same_species(m.species, rec.species)), None)
        team.append(mon if mon is not None else Pokemon(details=rec.species, gen=9))
    if len(team) > 6 or not any(m is me for m in team):
        return None
    names = tuple(belief.display(to_id(r.species.replace("-*", ""))) for r in records)
    opp_names = tuple(belief.display(m.species) for m in battle.teampreview_opponent_team)
    spec = SpectatorSide(team=team, known=known, names=names)
    state = build_state(battle, belief, opp_names, rng, move_beta=move_beta, spectator=spec)
    if a.kind == "move":
        idx = next((i for i, m in enumerate(team) if m is me), None)
        moves = [to_id(m.id) for m in state.side_one.pokemon[idx].moves]
        mid = to_id(a.move)
        if mid not in moves:
            return None  # Struggle, a called move, ...
        action = moves.index(mid) + (TERA_OFFSET if a.tera else 0)
    else:
        j = next((i for i, m in enumerate(team) if _same_species(m.species, a.to or "")), None)
        if j is None or j >= 6 or team[j] is me:
            return None
        action = SWITCH_OFFSET + j
    return state.to_string(), action
