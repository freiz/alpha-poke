"""The replay-path state-construction differential (doc/state-diff.md "follow-up": the training data's
path). As statebuild.py for the live path, but the state built as train/positions.py builds a
replay's: a spectator's log (Showdown's public lines -- HP in percent, no request), the side's
team from the whole game's parse (parse_replay: preview order, the game-wide known parts of each
set) as a SpectatorSide, build_state(spectator=...). The oracle replaces the belief's samples of
*both* sides by their true sets (a replay knows neither side's hidden parts): a difference left
is the construction's. Both sides are compared as the opponent is on the live path (HP
fractions; with the oracle the sets' items, abilities, stats, moves and PP)."""

import contextlib
import random

from poke_env.battle import Battle, Pokemon

from alpha_poke.analysis.roles import to_id
from alpha_poke.enginecheck import engine_state, random_battle
from alpha_poke.enginecheck.statebuild import (LOG, SAME_SPECIES, _belief, _disguised, _fainted_no_status, _forme_match, _true_forme,
                                               _feed, _flip, field_diffs, foe_diffs)  # fmt: skip


@contextlib.contextmanager
def _oracle(team: list, ours: dict, theirs: dict):
    """build_state's samples replaced by the true sets: a mon of ``team`` (side one's, the
    SpectatorSide's) by ``ours`` (its side's Showdown state), any other by ``theirs`` (the team
    names cannot tell the sides apart: a mirror match)."""
    from alpha_poke.agents import engine_state as es

    inner = es.sample_set
    mine = {id(m) for m in team}
    by_side = {side: {SAME_SPECIES.get(m["species"], m["species"]): m for m in st["mons"]}
               for side, st in (("ours", ours), ("theirs", theirs))}  # fmt: skip

    def sample(belief, mon, team_names, *a, **kw):
        out = inner(belief, mon, team_names, *a, **kw)
        sp = to_id(mon.species)
        t = _forme_match(by_side["ours" if id(mon) in mine else "theirs"], SAME_SPECIES.get(sp, sp))
        if t is None:
            return out
        own = t.get("transform_backup")
        moves = [x for x, _ in own[2]] if own else [x["id"] for x in t["moves"]]
        st = dict(zip(("atk", "def", "spa", "spd", "spe"), own[0], strict=True)) if own else dict(t["stats"])
        if "powertrick" in (t.get("volatiles") or {}) and not own:
            st["atk"], st["def"] = st["def"], st["atk"]
        return es.SampledSet(moves=moves, item=t["item"] or "none",
                             ability=t["base_ability"] or t["ability"] or "none",
                             tera=(t["tera_type"] or "typeless").lower(),
                             stats={"hp": t["maxhp"], **st},
                             nature=(t.get("nature") or "serious").lower(),  # (S158)
                             evs=tuple(t["evs"]) if t.get("evs") else None,
                             forme=_true_forme(sp, t, moves))  # fmt: skip

    es.sample_set = sample
    try:
        yield
    finally:
        es.sample_set = inner



def decisions(p1: str, p2: str, seed: int, max_turns: int = 40, stats: dict | None = None,
              script: list | None = None, fmt: str | None = None):
    """Each decision of a random battle, built from the spectator's log as a replay's position
    is: (step, side, poke-env battle, built state, truth from that side's point of view)."""
    from alpha_poke.agents.engine_state import KnownSet, SpectatorSide, build_state
    from alpha_poke.replay import parse_replay
    from alpha_poke.train.positions import _known, _same_species

    stats = {} if stats is None else stats
    stats.setdefault("decisions", 0)
    stats.setdefault("errors", [])
    views: dict = {}
    steps, err = random_battle(p1, p2, f"gen5,{seed},{seed + 1},{seed + 2},{seed + 3}", seed + 1,
                               max_turns=max_turns, views=views, script=script,
                               **({"fmt": fmt} if fmt else {}))  # fmt: skip
    if err is not None:
        stats["errors"].append(f"battle: {err[:200]}")
    log = views.get("spectator") or []
    try:
        rep = parse_replay({"id": f"diff-{seed}", "log": "\n".join(log)})
    except BaseException as e:  # noqa: BLE001
        stats["errors"].append(f"parse: {type(e).__name__}: {str(e)[:120]}")
        return
    if rep.warnings:
        stats.setdefault("skipped", []).append(f"parse warnings: {rep.warnings[:2]}")
        return
    belief = _belief()
    records = {s: [m for m in rep.teams[s] if not m.phantom] for s in ("p1", "p2")}
    known: dict[str, dict[str, KnownSet]] = {s: {to_id(m.species): _known(m) for m in records[s]}
                                             for s in ("p1", "p2")}  # fmt: skip
    copied = {s: {to_id(t): [to_id(x) for x in ms] for (sd, t), ms in rep.copied.items() if sd == s}
              for s in ("p1", "p2")}  # fmt: skip
    battles = {s: Battle(f"battle-diff-{seed}-{s}", s, LOG, gen=9) for s in ("p1", "p2")}
    for s, b in battles.items():
        b._player_role = s
    pos = 0
    for k, step in enumerate(steps):
        if "requests" not in step:
            continue
        upto = step["view_pos"]["spectator"]
        for b in battles.values():
            _feed(b, log[pos:upto])
        pos = upto
        sd = _fainted_no_status(step["state"])  # (after the turn's end: engine_state's upkept)
        try:
            truth = engine_state(sd)
        except BaseException as e:  # noqa: BLE001
            stats["errors"].append(f"truth: {type(e).__name__}: {str(e)[:120]}")
            continue
        for side in ("p1", "p2"):
            req = step["requests"][side]
            if not req or req.get("wait") or req.get("teamPreview"):
                continue
            b = battles[side]
            me = b.active_pokemon
            if me is None or b.opponent_active_pokemon is None:
                continue
            team = []
            for rec in records[side]:  # (train/positions._position: preview order)
                mon = next((m for m in b.team.values() if _same_species(m.species, rec.species)), None)
                team.append(mon if mon is not None else Pokemon(details=rec.species, gen=9))
            if len(team) > 6 or not any(m is me for m in team):
                stats.setdefault("skipped", []).append("team")
                continue
            names = tuple(belief.display(to_id(r.species.replace("-*", ""))) for r in records[side])
            opp_names = tuple(belief.display(m.species) for m in b.teampreview_opponent_team)
            spec = SpectatorSide(team=team, known=known[side], names=names, copied=copied[side])
            ours = step["state"]["sides"][0 if side == "p1" else 1]
            theirs = step["state"]["sides"][1 if side == "p1" else 0]
            stats["decisions"] += 1
            try:
                with _oracle(team, ours, theirs):
                    built = build_state(b, belief, opp_names, random.Random(k), spectator=spec,
                                        force_switch=bool(req.get("forceSwitch")))  # fmt: skip
            except BaseException as e:  # noqa: BLE001
                stats["errors"].append(f"build: {type(e).__name__}: {str(e)[:160]}")
                continue
            yield k, side, b, built, truth if side == "p1" else _flip(truth)


class _Mirror:
    """A battle seen from the other side (statebuild._disguised reads the opponent's lines)."""

    def __init__(self, b):
        self.player_role = "p2" if b.player_role == "p1" else "p1"
        self._replay_data = b._replay_data


def battle_diffs(p1: str, p2: str, seed: int, max_turns: int = 40,
                 script: list | None = None, fmt: str | None = None) -> tuple[list[tuple], dict]:
    """[(step, side, kind, detail)] over a random battle's decisions, replay-built; and counts."""
    out: list = []
    stats: dict = {}
    for k, side, b, built, t in decisions(p1, p2, seed, max_turns, stats, script, fmt):
        own_seen = {to_id(m.species) for m in b.team.values()}
        foe_seen = {to_id(m.species) for m in b.opponent_team.values()}
        # (a disguise not found out: a spectator cannot tell -- its percent HP -- on either side)
        own_hidden = frozenset(_disguised(_Mirror(b), t.side_one))
        diffs = [(kind.replace("foe:", "own:", 1), d)
                 for kind, d in foe_diffs(built.side_one, t.side_one, own_seen, True, own_hidden)]  # fmt: skip
        foe_hidden = frozenset(_disguised(b, t.side_two))
        diffs += foe_diffs(built.side_two, t.side_two, foe_seen, True, foe_hidden)
        # (the PP its foe's moves took at an undetected disguise -- a Pressure one's 2: hidden too)
        diffs = [(kind, d) for kind, d in diffs
                 if not (kind == "own:pp" and foe_hidden) and not (kind == "foe:pp" and own_hidden)]
        diffs += field_diffs(built, t)
        out += [(k, side, kind, detail) for kind, detail in diffs]
    return out, stats
