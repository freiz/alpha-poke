"""One player's decisions in a replay, judged by the search from that player's view.

Every decision point of the player (turn starts, switches after a faint, pivot switches; not the
turns whose choice the log does not show) is rebuilt as the training data's positions are
(train.positions: the player's own team as the replay reveals it, the opponent's revealed parts,
belief samples for the rest) with ``worlds`` belief worlds, and searched for ``ms`` milliseconds
with the network, as the bot plays. Per decision: the options' visit shares and winning chances
(each option's mean value), the root's value (the search's winning chance for the player), the
option chosen, the search's own choice, and the loss: the search's choice's chance minus the
chosen one's. Plus what the log shows of the turn and the public state at the decision.
The numbers are the search's estimates (noisy: a few seconds of search, belief samples for the
hidden sets), good for finding the decisions that mattered, not exact probabilities.
"""

import random
import re
from dataclasses import asdict, dataclass, field

import alpha_search
import poke_engine as pe

from alpha_poke.agents import slots
from alpha_poke.replay import parse_replay
from alpha_poke.selfplay.batcher import ml_for, parse_ml
from alpha_poke.train.positions import KIND_BLIND, KIND_FORCED, KIND_PIVOT, positions_from_replay

KINDS = {KIND_FORCED: "switch after a faint", KIND_PIVOT: "pivot switch"}
BOOSTS = ("attack", "defense", "special_attack", "special_defense", "speed", "accuracy", "evasion")
HAZARDS = ("stealth_rock", "spikes", "toxic_spikes", "sticky_web")
SCREENS = ("reflect", "light_screen", "aurora_veil", "tailwind")
# log lines kept in a turn's events (the rest: chat, timers, animations)
# (the battle's record as the replay shows it; "" is the log's blank separator line: it ends the
# turn's actions before the end-of-turn effects; "upkeep" ends those, the switches after a faint
# follow)
EVENTS = {"", "upkeep", "move", "switch", "drag", "replace", "faint", "cant", "-terastallize",
          "-damage", "-heal", "-sethp", "-status", "-curestatus", "-cureteam", "-boost", "-unboost",
          "-setboost", "-swapboost", "-copyboost", "-clearboost", "-clearallboost",
          "-clearnegativeboost", "-crit", "-supereffective", "-resisted", "-immune", "-miss",
          "-fail", "-block", "-notarget", "-item", "-enditem", "-ability", "-endability",
          "-transform", "-formechange", "detailschange", "-sidestart", "-sideend",
          "-swapsideconditions", "-weather", "-fieldstart", "-fieldend", "-start", "-end",
          "-activate", "-singleturn", "-prepare", "-mustrecharge", "-hitcount", "-message",
          "win", "tie"}  # fmt: skip


@dataclass
class Decision:
    turn: int
    kind: str  # "turn" / "switch after a faint" / "pivot switch"
    chosen: str  # option names (agents.slots): "earthquake", "earthquake-tera", "switch greattusk"
    best: str  # the search's choice (the most visited)
    value: float  # the root's value: the player's winning chance as the search sees it
    chosen_value: float | None  # the chosen option's mean value (None: the search never tried it)
    best_value: float
    loss: float | None  # best_value - chosen_value
    chosen_share: float  # the chosen option's share of the search's visits
    options: list = field(default_factory=list)  # [name, visit share, mean value], by share
    state: dict = field(default_factory=dict)  # the public state at the decision
    events: list = field(default_factory=list)  # the turn's log lines, sides as ME / OPP


def _mon(p) -> dict:
    return {"species": str(p.id), "hp": round(p.hp / p.maxhp, 2) if p.maxhp else 0.0,
            "status": str(p.status).lower(), "tera": str(p.tera_type).lower() if p.terastallized else ""}  # fmt: skip


def _side(side, own: bool) -> dict:
    active = side.pokemon[int(side.active_index)]
    out = {"active": _mon(active),
           "boosts": {b: getattr(side, f"{b}_boost") for b in BOOSTS if getattr(side, f"{b}_boost")},
           "hazards": {h: getattr(side.side_conditions, h) for h in HAZARDS
                       if getattr(side.side_conditions, h)},
           "screens": {s: getattr(side.side_conditions, s) for s in SCREENS
                       if getattr(side.side_conditions, s)},
           "alive": sum(1 for p in side.pokemon if p.hp > 0 and str(p.id) not in ("", "none")),
           "tera_used": bool(side.tera_used)}  # fmt: skip
    if own:  # (the opponent's bench: belief samples beyond what was seen; not shown)
        out["bench"] = [_mon(p) for i, p in enumerate(side.pokemon)
                        if i != int(side.active_index) and str(p.id) not in ("", "none")]  # fmt: skip
    return out


def public_state(state: str) -> dict:
    """What both players can see at the decision (side one = the reviewed player): the actives'
    species / HP / status / tera, boosts, hazards and screens on each side, mons left, weather."""
    s = pe.State.from_string(state)
    return {"me": _side(s.side_one, True), "opp": _side(s.side_two, False),
            "weather": str(s.weather).lower(), "terrain": str(s.terrain).lower(),
            "trick_room": bool(s.trick_room)}  # fmt: skip


def turn_events(log: str, side: str) -> dict[int, list[str]]:
    """The log's relevant lines by turn (0: before turn 1), the reviewed side as ME, the other as
    OPP, nicknames replaced by species."""
    other = "p2" if side == "p1" else "p1"
    nick: dict[str, str] = {}
    out: dict[int, list[str]] = {0: []}
    turn = 0
    for line in log.split("\n"):
        f = line.split("|")
        if len(f) < 2:
            continue
        if f[1] == "turn":
            turn = int(f[2])
            out[turn] = []
            continue
        if f[1] in ("switch", "drag", "replace") and len(f) > 3:
            nick[f[2][:3] + f[2].split(":", 1)[1].strip()] = f[3].split(",")[0]
        if f[1] not in EVENTS or "[silent]" in f:
            continue
        text = "|".join(f[1:])
        for who in (side, other):
            tag = "ME" if who == side else "OPP"
            for key, species in nick.items():
                if key.startswith(who):
                    text = text.replace(f"{who}a: {key[3:]}", f"{tag} {species}")
            text = re.sub(rf"\b{who}: [^|]*", f"{tag} side", text)  # (a side: no player name)
            text = text.replace(f"[of] {who}a", f"[of] {tag}")
        out[turn].append(text)
    return out


def review(row: dict, side: str, belief, model: str, worlds: int = 16, ms: int = 2000,
           threads: int = 2, seed: int = 0, log=print, progress=None) -> dict:  # fmt: skip
    """The review of ``side``'s decisions in ``row`` (coach.replays): {"decisions": [...],
    "teams": ..., "result": ..., "settings": ...}. ``progress(done, total)``: called before the
    first search and after each (the app's progress bar)."""
    rep = parse_replay(row)
    rng = random.Random(seed)
    positions = [p for p in positions_from_replay(row, belief, rng, extra_per_game=10**6,
                                                  seed=seed, worlds=worlds)
                 if p.side == side and p.kind != KIND_BLIND]  # fmt: skip
    ml = parse_ml(ml_for(model))
    events = turn_events(row["log"], side)
    decisions = []
    if progress:
        progress(0, len(positions))
    for i, p in enumerate(positions):
        ctx = (list(p.reveal), (p.rating_own, p.rating_opp), p.turn, p.history)
        ours, n, _, _ = alpha_search.ismcts(p.worlds, ms, threads=threads, model_dir=model,
                                            use_policy=True, policy_opponent=True,
                                            contexts=[ctx] * len(p.worlds), ml=ml,
                                            seed=seed)  # fmt: skip
        total = sum(v for _, v, _ in ours) or 1
        # (an option the search never tried has no value: None, not its 0 mean)
        opts = sorted(([c, v / total, q if v else None] for c, v, q in ours), key=lambda o: -o[1])
        chosen = slots.names(p.state)[p.action]
        by = {o[0]: o for o in opts}
        best = opts[0]
        ch = by.get(chosen)
        ch = ch if ch and ch[2] is not None else None
        d = Decision(
            turn=p.turn, kind=KINDS.get(p.kind, "turn"), chosen=chosen, best=best[0],
            value=round(sum(o[1] * o[2] for o in opts if o[2] is not None), 3),
            chosen_value=round(ch[2], 3) if ch else None, best_value=round(best[2], 3),
            loss=round(best[2] - ch[2], 3) if ch else None,
            chosen_share=round(ch[1], 3) if ch else 0.0,
            options=[[c, round(s, 3), None if q is None else round(q, 3)] for c, s, q in opts[:6]],
            state=public_state(p.state), events=events.get(p.turn, []),
        )  # fmt: skip
        decisions.append(d)
        if progress:
            progress(i + 1, len(positions))
        log(f"  turn {p.turn:>3} {d.kind:<21} chose {chosen:<24} search {best[0]:<24} "
            f"win {d.value:.2f}  loss {d.loss if d.loss is not None else '-'}  ({i + 1}/{len(positions)}, {n} it)")  # fmt: skip
    return {
        "id": row["id"],
        "side": side,
        "player": row["players"][int(side[1]) - 1],
        "winner": rep.winner,
        "turns": rep.turns,
        "teams": {s: [_revealed(m) for m in rep.teams[s] if not m.phantom] for s in ("p1", "p2")},
        "decisions": [asdict(d) for d in decisions],
        "settings": {"model": model, "worlds": worlds, "ms": ms, "threads": threads, "seed": seed},
    }


def _revealed(m) -> dict:
    """A mon's set as the replay reveals it (unrevealed parts: None / missing moves)."""
    return {"species": m.species, "item": m.item, "item_lost": m.item_lost, "ability": m.ability,
            "tera": m.tera_type, "tera_turn": m.tera_turn, "moves": list(m.moves),
            "brought": m.brought, "fainted_turn": m.fainted_turn}  # fmt: skip


def mistake_score(d: dict) -> float:
    """How much the search disagreed with a decision: the winning chance lost (the search's
    choice's minus the chosen option's) + 0.15 x (its choice's share of the visits minus the
    chosen one's). The visits weigh in because an option the search hardly tried has a noisy mean
    (a few lines of play): 97% of the visits on Dragon Dance and 0.1% on Extreme Speed is a clear
    verdict even where their means differ by 3% (2026-10-29, calibrated on four games: >= 0.10
    picked the moments a person would)."""
    return max(0.0, d["loss"] or 0.0) + 0.15 * (d["options"][0][1] - d["chosen_share"])


def key_moments(report: dict, k: int = 5, min_score: float = 0.10) -> list[dict]:
    """The decisions the search disagreed with most (mistake_score >= ``min_score``), worst
    first, each with its score."""
    ds = sorted(report["decisions"], key=mistake_score, reverse=True)
    return [d | {"score": round(mistake_score(d), 3)} for d in ds if mistake_score(d) >= min_score][
        :k
    ]


def swings(report: dict, k: int = 3) -> list[dict]:
    """The largest drops of the player's winning chance from one decision to the next (what
    happened in between: the turn's events -- the opponent's play, luck, the player's choice)."""
    ds = report["decisions"]
    drops = [(a["value"] - b["value"], a, b) for a, b in zip(ds, ds[1:], strict=False)]
    return [{"from": a["turn"], "to": b["turn"], "drop": round(x, 3), "before": a["value"],
             "after": b["value"], "events": a["events"]}
            for x, a, b in sorted(drops, key=lambda t: -t[0])[:k] if x > 0.05]  # fmt: skip
