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
import zlib
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
    rating_own: int = 0  # v4: the players' ratings before the game (0 = unknown)
    rating_opp: int = 0
    kind: int = 0  # v4: KIND_MAIN / KIND_FORCED / KIND_PIVOT / KIND_BLIND


REVEAL_BITS = ("seen", "item", "ability", "tera", "move0", "move1", "move2", "move3")
HIST = 8  # stored steps (rust/alpha_search/src/features.rs HIST); models may use fewer


def _eng(name: str) -> str:
    return to_id(name.replace("-*", "")).upper()


@dataclass
class Blind:
    """A side that chose an action we cannot see: ``kind`` 'p' = prevented (``|cant|``: full
    paralysis, sleep, flinch, recharge, ...), 'd' = its active fainted before acting."""

    kind: str
    mon: str
    reason: str = ""


def _act(a, first: bool = False) -> str:
    """One side's action in a decision step: "m:ACTOR:MOVE:DMG:FLAGS" (t: with tera; DMG = HP
    percent taken from the opposing active; FLAGS: c crit, x missed / failed / no effect, k it
    fainted, f acted first in the step), "s:ACTOR:TO::FLAGS", "p:ACTOR:REASON" (prevented),
    "d:ACTOR:" (fainted before acting), "" (no decision)."""
    if a is None:
        return ""
    if isinstance(a, Blind):
        return f"{a.kind}:{_eng(a.mon)}:{to_id(a.reason)}"
    flags = "f" if first else ""
    if a.kind == "move":
        flags += ("c" if a.crit else "") + ("x" if a.miss else "") + ("k" if a.ko else "")
        return f"{'t' if a.tera else 'm'}:{_eng(a.mon)}:{_eng(a.move or '')}:{a.dmg}:{flags}"
    return f"s:{_eng(a.mon)}:{_eng(a.to or '')}::{flags}"


def _step_str(s: dict, side: str) -> str:
    other = "p2" if side == "p1" else "p1"
    a, b = s.get(side), s.get(other)
    real = [x for x in (a, b) if x is not None and not isinstance(x, Blind)]
    first = min(real, key=lambda x: x.order) if len(real) == 2 else None
    return f"{_act(a, a is first)}/{_act(b, b is first)}"


def blind_sides(rep) -> dict[tuple[int, str], Blind]:
    """(turn, side) -> Blind for the turns where a side with an active mon chose an action that
    the log does not show: it could not move (``|cant|``) or its active fainted first."""
    main = {
        (a.turn, a.side)
        for a in rep.actions
        if a.turn >= 1 and a.kind in ("move", "switch") and not (a.forced or a.pivot)
    }
    cant = {(t, sd): r for t, sd, r in rep.cants}
    out = {}
    for t, snap in rep.hp_by_turn.items():
        if t < 1:
            continue
        for sd, (species, hp) in snap.items():
            if (t, sd) in main or not hp:
                continue
            if (t, sd) in cant:
                out[(t, sd)] = Blind("p", species, cant[(t, sd)])
                continue
            rec = next((m for m in rep.teams[sd] if m.species == species), None)
            if rec is not None and rec.fainted_turn == t:
                out[(t, sd)] = Blind("d", species)
    return out


def decision_steps(actions, blind: dict | None = None) -> dict[int, list[dict]]:
    """Turn -> its decision steps in order, each {side: action / Blind}: the chosen actions
    (the first move / voluntary switch of each side; a Blind when it chose but the log does not
    show what; absent when it had no decision), then each pivot switch, then the forced switches
    after faints (one step for both sides)."""
    by_turn: dict[int, list] = {}
    for a in actions:
        if a.turn >= 1 and a.kind in ("move", "switch"):
            by_turn.setdefault(a.turn, []).append(a)
    for t, _ in blind or {}:
        by_turn.setdefault(t, [])
    out = {}
    for t, acts in sorted(by_turn.items()):
        acts.sort(key=lambda a: a.order)
        main = {}
        for a in acts:
            if not a.forced and not a.pivot:
                main.setdefault(a.side, a)
        for sd in ("p1", "p2"):
            if sd not in main and (t, sd) in (blind or {}):
                main[sd] = blind[(t, sd)]
        steps = [main]
        steps += [{a.side: a} for a in acts if a.pivot]
        forced = {a.side: a for a in acts if a.forced}
        if forced:
            steps.append(forced)
        out[t] = steps
    return out


def _flat(steps: dict[int, list[dict]]) -> list[tuple[tuple[int, int], dict]]:
    return [((t, i), s) for t in sorted(steps) for i, s in enumerate(steps[t])]


def history_string(steps: dict[int, list[dict]], key, side: str) -> str:
    """The last HIST steps before ``key`` from ``side``'s point of view; ``key`` = a turn (its
    first step) or (turn, step index)."""
    key = (key, 0) if isinstance(key, int) else key
    seq = [s for k, s in _flat(steps) if k < key][-HIST:]
    return ";".join(_step_str(s, side) for s in seq)


FUTURE = 4  # stored future steps (step 0 = this decision: own label + the opponent's action)


def future_string(steps: dict[int, list[dict]], key, side: str) -> str:
    """The first FUTURE steps from ``key`` on (as in history_string), oldest first."""
    key = (key, 0) if isinstance(key, int) else key
    seq = [s for k, s in _flat(steps) if k >= key][:FUTURE]
    return ";".join(_step_str(s, side) for s in seq)


def step_key(steps: dict[int, list[dict]], a) -> tuple[int, int] | None:
    """(turn, step index) of the step holding action ``a``."""
    return next(((a.turn, i) for i, s in enumerate(steps.get(a.turn, [])) if s.get(a.side) is a),
                None)  # fmt: skip


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


KIND_MAIN, KIND_FORCED, KIND_PIVOT, KIND_BLIND = 0, 1, 2, 3
# partial labels of a Blind position (the log does not show the move): some move slot, without /
# with tera (a switch would have happened first; tera is shown at the start of the turn)
BLIND_MOVE, BLIND_MOVE_TERA = -1, -2


def positions_from_replay(
    row: dict,
    belief,
    rng: random.Random,
    move_beta: float = 1.0,
    per_game: int = 0,
    extra_per_game: int = 0,
    seed: int = 0,
):
    """``row``: a replay dict with ``id``, ``log`` (+ ``rating``, ``uploadtime``). ``per_game``
    > 0: only that many decision points, drawn at random (positions within a game are strongly
    correlated and share one outcome: many games x few positions, as AlphaGo's value net); states
    are built only for those, which is the expensive part.
    ``extra_per_game`` > 0 (v4): also that many of the other decision points (forced switches
    after a faint, pivot switches, Blind turn starts), drawn with their own generator (seeded
    from the game id) so that the turn-start positions stay exactly as without them."""
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
    blind = blind_sides(rep)
    steps = decision_steps(rep.actions, blind)
    # extra decision points: (kind, turn, side, action or Blind)
    extra: list = []
    rng2 = random.Random(zlib.crc32(f"{seed}:{row['id']}".encode()))
    if extra_per_game:
        for a in rep.actions:
            if a.turn >= 1 and a.kind == "switch" and (a.forced or a.pivot):
                extra.append((KIND_FORCED if a.forced else KIND_PIVOT, a.turn, a.side, a))
        extra += [(KIND_BLIND, t, sd, b) for (t, sd), b in sorted(blind.items())]
        if len(extra) > extra_per_game:
            extra = [extra[i] for i in sorted(rng2.sample(range(len(extra)), extra_per_game))]
    blind_at = {(t, sd): b for k, t, sd, b in extra if k == KIND_BLIND}
    switch_at = {id(a): k for k, _, _, a in extra if k in (KIND_FORCED, KIND_PIVOT)}
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
    ratings = {s: rep.ratings_before.get(s) or 0 for s in ("p1", "p2")}
    # the parser's switch actions (leads included, drags not) in log order, to find the action
    # of each |switch| line
    switch_queue = [a for a in rep.actions if a.kind in ("lead", "switch")]
    out = []

    def emit(kind, side, turn, a, key, gen):
        other = "p2" if side == "p1" else "p1"
        pos = _position(battles[side], side, a, records[side], known[side], belief, gen,
                        move_beta, kind)  # fmt: skip
        if pos is None:
            return
        st, action = pos
        reveal = reveal_flags(st, list(battles[side].opponent_team.values()),
                              list(battles[other].opponent_team.values()))  # fmt: skip
        labels = {to_id(r.species.replace("-*", "")): _set_label(r) for r in records[other]}
        opp_sets = ";".join(
            next((v for k, v in labels.items() if p.id and _same_species(k, p.id)), "")
            for p in st.side_two.pokemon
        )
        out.append(
            Position(
                row["id"], side, turn, st.to_string(), action, float(rep.winner == side),
                _rating(row), int(row.get("uploadtime") or 0),
                history_string(steps, key, side), future_string(steps, key, side),
                reveal, opp_sets,
                faints.get((turn, side), 0) | faints.get((turn, other), 0) << 1,
                len(records[side]) - total_faints[side],
                len(records[other]) - total_faints[other],
                cur, ratings[side], ratings[other], kind,
            )
        )  # fmt: skip

    forced_done: set = set()
    for line in lines:
        split = line.split("|")
        if len(split) < 2 or split[1] in _IGNORED:
            continue
        if split[1] == "switch" and switch_queue:
            a = switch_queue.pop(0)
            # a forced step: all sides' positions before the first forced switch line is seen
            if a.forced and (a.turn, "forced") not in forced_done:
                forced_done.add((a.turn, "forced"))
                for b in [x for x in steps.get(a.turn, [{}])[-1].values()
                          if getattr(x, "forced", False) and id(x) in switch_at]:  # fmt: skip
                    emit(KIND_FORCED, b.side, b.turn, b, step_key(steps, b), rng2)
            elif a.pivot and id(a) in switch_at:
                emit(KIND_PIVOT, a.side, a.turn, a, step_key(steps, a), rng2)
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
            if a is not None:
                emit(KIND_MAIN, side, turn, a, turn, rng)
            elif (turn, side) in blind_at:
                emit(KIND_BLIND, side, turn, blind_at[(turn, side)], turn, rng2)
    return out


def _position(battle, side, a, records, known, belief, rng, move_beta, kind=KIND_MAIN):
    me = battle.active_pokemon
    switch_only = kind in (KIND_FORCED, KIND_PIVOT)
    if me is None or (me.fainted and kind != KIND_FORCED) or battle.opponent_active_pokemon is None:
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
    state = build_state(battle, belief, opp_names, rng, move_beta=move_beta, spectator=spec,
                        force_switch=switch_only)  # fmt: skip
    if isinstance(a, Blind):
        rec = next((r for r in records if _same_species(r.species, me.species)), None)
        tera = rec is not None and rec.tera_turn == battle.turn  # tera shows before any move
        return state, BLIND_MOVE_TERA if tera else BLIND_MOVE
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
