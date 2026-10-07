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
v3 (design D13, network v3 first batch):
  * ``reveal``: public information per entity of the state (own 0-5, opponent 0-5), bit flags
    (REVEAL_BITS): been on the field, item / ability / tera type revealed, move slot 0-3 revealed.
    The opponent's: what the player has seen; its own: what the opponent has seen of it (the
    other player's view of the same log);
  * auxiliary targets: ``opp_sets`` (the opponent's sets as revealed by the end of the game, per
    opponent entity of the state: "ITEM|ABILITY|TERA|MOVE,MOVE;..." in engine names, empty =
    never revealed), ``faint`` (bit 0: the player's mon fainted during this turn, bit 1: the
    opponent's), ``left_own`` / ``left_opp`` (mons left at the end) and ``turns`` (game length).
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
    reveal: list[int] | None = None  # v3: REVEAL_BITS per entity, state order
    opp_sets: str = ""
    faint: int = 0
    left_own: int = 0
    left_opp: int = 0
    turns: int = 0


REVEAL_BITS = ("seen", "item", "ability", "tera", "move0", "move1", "move2", "move3")
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


def _public(mon) -> tuple[bool, bool, bool, set[str]]:
    """What a player's view (poke-env, as the opponent's mon) shows of ``mon``: item, ability,
    tera type known; the revealed moves (engine names)."""
    item = mon.item not in (None, "unknown_item")
    return item, mon.ability is not None, mon.is_terastallized, {_eng(m) for m in mon.moves}


def reveal_flags(state, view_of_opp, view_of_own) -> list[int]:
    """REVEAL_BITS per entity of the poke-engine ``state`` (side one = the player): side two
    from the player's view (``view_of_opp``: its battle's opponent_team), side one from the
    opponent's view of the player (``view_of_own``: the other battle's opponent_team)."""
    out = []
    for side, seen in ((state.side_one, view_of_own), (state.side_two, view_of_opp)):
        for p in side.pokemon:
            mon = next((m for m in seen if _same_species(m.species, p.id)), None) if p.id else None
            if mon is None:
                out.append(0)
                continue
            item, ability, tera, moves = _public(mon)
            bits = 1 | item << 1 | ability << 2 | tera << 3
            for k, m in enumerate(p.moves[:4]):
                bits |= (_eng(m.id) in moves) << (4 + k)
            out.append(bits)
    return out


def _set_label(rec) -> str:
    k = _known(rec)
    return "|".join([_eng(k.item or ""), _eng(k.ability or ""), (k.tera or "").upper(),
                     ",".join(_eng(m) for m in k.moves)])  # fmt: skip


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
    # per turn and side: fainted during the turn; whole game: faints, length
    faints: dict[tuple[int, str], int] = {}
    total_faints = {"p1": 0, "p2": 0}
    cur = 0
    for x in lines:
        f = x.split("|")
        if len(f) > 2 and f[1] == "turn":
            cur = int(f[2])
        elif len(f) > 2 and f[1] == "faint" and f[2][:2] in total_faints:
            faints[(cur, f[2][:2])] = 1
            total_faints[f[2][:2]] += 1
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
            other = "p2" if side == "p1" else "p1"
            pos = _position(battles[side], side, a, records[side], known[side], belief, rng,
                            move_beta)  # fmt: skip
            if pos is not None:
                st, action = pos
                state = st.to_string()
                reveal = reveal_flags(st, list(battles[side].opponent_team.values()),
                                      list(battles[other].opponent_team.values()))  # fmt: skip
                labels = {to_id(r.species.replace("-*", "")): _set_label(r) for r in records[other]}
                opp_sets = ";".join(
                    next((v for k, v in labels.items() if p.id and _same_species(k, p.id)), "")
                    for p in st.side_two.pokemon
                )
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
                        reveal,
                        opp_sets,
                        faints.get((turn, side), 0) | faints.get((turn, other), 0) << 1,
                        len(records[side]) - total_faints[side],
                        len(records[other]) - total_faints[other],
                        cur,
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
    return state, action
