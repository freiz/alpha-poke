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

import math
import random
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field

import alpha_search
import poke_engine as pe

from alpha_poke.agents import slots
from alpha_poke.coach.team import load_team, match_team
from alpha_poke.replay import parse_replay
from alpha_poke.selfplay.batcher import ml_for, parse_ml
from alpha_poke.train.positions import (
    KIND_BLIND,
    KIND_FORCED,
    KIND_PIVOT,
    blind_sides,
    extra_points,
    positions_from_replay,
)

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
    # [name, visit share, mean value, its standard error], by share; with repeats > 1 the share and
    # the value are the means over the independent searches (the error: their spread / sqrt(n))
    options: list = field(default_factory=list)
    state: dict = field(default_factory=dict)  # the public state at the decision
    events: list = field(default_factory=list)  # the turn's log lines, sides as ME / OPP
    value_se: float | None = None
    loss_se: float | None = None  # the loss's standard error (the two values' combined)
    repeats: int = 1
    visits: int = 0  # the searches' visits at the root, all repeats (more: surer numbers)


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


def _mean_se(xs: list) -> tuple[float | None, float | None]:
    if not xs:
        return None, None
    return statistics.fmean(xs), (
        statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else None
    )


def review(row: dict, side: str, belief, model: str, worlds: int = 16, ms: int = 2000,
           threads: int = 2, seed: int = 0, log=print, progress=None, repeats: int = 1,
           team=None, parallel: int = 1) -> dict:  # fmt: skip
    """The review of ``side``'s decisions in ``row`` (coach.replays): {"decisions": [...],
    "teams": ..., "result": ..., "settings": ...}. ``progress(done, total)``: called before the
    first search and after each decision (the app's progress bar). ``repeats`` > 1: each decision
    searched that many times, each over its own draw of everything hidden -- the opponent's
    worlds and the player's own unrevealed set parts (2026-10-30: one search's option values moved
    by +-2-5 points from one draw of the hidden sets to the next, as much as the options differ;
    drawing only the opponent's again showed +-1, the player's own guesses were most of it; the
    visit shares hardly moved): means and standard errors. ``team``: the player's own team (a
    Showdown export or a PokéPaste link, or coach.team.parse_team's) -- its sets exact, nothing of them sampled
    (TeamError when it is not the replay's team). ``parallel``: searches run at once (each with
    ``threads`` threads; the search releases the GIL)."""
    rep = parse_replay(row)
    known = None
    if team:
        sets = load_team(team) if isinstance(team, str) else team
        known = {side: match_team(sets, [m for m in rep.teams[side] if not m.phantom])}
    # one draw per repeat: its own positions (the player's guessed parts too), matched by point
    draws = []
    for k in range(repeats):
        ps = [p for p in positions_from_replay(row, belief, random.Random(seed + k),
                                               extra_per_game=10**6, seed=seed + k, worlds=worlds,
                                               known_sets=known, side=side)
              if p.kind != KIND_BLIND]  # fmt: skip
        draws.append(_by_point(ps))
    points = list(draws[0])
    ml = parse_ml(ml_for(model))
    events = turn_events(row["log"], side)
    if progress:
        progress(0, len(points))

    def search(i: int, k: int):
        p = draws[k].get(points[i])
        if p is None:
            return None
        ctx = (list(p.reveal), (p.rating_own, p.rating_opp), p.turn, p.history)
        ours, it, _, _ = alpha_search.ismcts(p.worlds, ms, threads=threads, model_dir=model,
                                             use_policy=True, policy_opponent=True,
                                             contexts=[ctx] * len(p.worlds), ml=ml, seed=seed + k)  # fmt: skip
        return ours, it

    results = [[None] * repeats for _ in points]
    left = [repeats] * len(points)
    decisions: list = [None] * len(points)
    done = 0
    with ThreadPoolExecutor(max(1, parallel)) as pool:
        futures = {
            pool.submit(search, i, k): (i, k) for i in range(len(points)) for k in range(repeats)
        }
        for f in as_completed(futures):
            i, k = futures[f]
            try:
                results[i][k] = f.result()
            except BaseException:
                pool.shutdown(cancel_futures=True)  # (not the remaining searches' minutes)
                raise
            left[i] -= 1
            if left[i]:
                continue
            p = draws[0][points[i]]
            decisions[i] = d = _decision(p, [r for r in results[i] if r is not None], events)
            done += 1
            if progress:
                progress(done, len(points))
            log(f"  turn {p.turn:>3} {d.kind:<21} chose {d.chosen:<24} search {d.best:<24} "
                f"win {d.value:.2f}  loss {d.loss if d.loss is not None else '-'}  ({done}/{len(points)}, "
                f"{d.visits} visits)")  # fmt: skip

    return {
        "id": row["id"],
        "side": side,
        "player": row["players"][int(side[1]) - 1],
        "winner": rep.winner,
        "turns": rep.turns,
        "teams": {s: [_revealed(m) for m in rep.teams[s] if not m.phantom] for s in ("p1", "p2")},
        "decisions": [asdict(d) for d in decisions],
        "settings": {
            "model": model,
            "worlds": worlds,
            "ms": ms,
            "threads": threads,
            "seed": seed,
            "repeats": repeats,
            "team": bool(team),
            "parallel": parallel,
        },
    }


def decision_count(row: dict, side: str) -> int:
    """How many decisions of ``side`` a review searches (its turn starts the log shows, its
    switches after a faint and pivot switches): positions_from_replay's points, without building
    them (the home page's time estimate; a point whose state is not built is counted)."""
    rep = parse_replay(row)
    main = {(a.turn, a.side) for a in rep.actions
            if a.turn >= 1 and not a.forced and not a.pivot and a.kind in ("move", "switch")}  # fmt: skip
    return sum(sd == side for _, sd in main) + sum(
        sd == side for k, _, sd, _ in extra_points(rep, blind_sides(rep)) if k != KIND_BLIND
    )


def _by_point(positions) -> dict:
    """Positions by decision point: (turn, kind, n-th of that turn and kind) -- the same in every
    draw of one replay."""
    out, n = {}, {}
    for p in positions:
        key = (p.turn, p.kind)
        n[key] = n.get(key, 0) + 1
        out[(*key, n[key])] = p
    return out


def _decision(p, searches, events) -> "Decision":
    """One decision from its searches ([(options, iterations)]: alpha_search.ismcts')."""
    runs, roots, visits = [], [], 0
    for ours, _ in searches:
        total = sum(v for _, v, _ in ours) or 1
        visits += sum(v for _, v, _ in ours)
        # (an option the search never tried has no value: None, not its 0 mean)
        run = {c: (v / total, q if v else None) for c, v, q in ours}
        runs.append(run)
        roots.append(sum(sh * q for sh, q in run.values() if q is not None))
    opts = []
    for c in {c for run in runs for c in run}:
        share = statistics.fmean(run.get(c, (0.0, None))[0] for run in runs)
        q, se = _mean_se([run[c][1] for run in runs if c in run and run[c][1] is not None])
        opts.append([c, share, q, se])
    opts.sort(key=lambda o: (-o[1], o[0]))
    chosen = slots.names(p.state)[p.action]
    by = {o[0]: o for o in opts}
    best = opts[0]
    ch = by.get(chosen)
    ch = ch if ch and ch[2] is not None else None
    value, value_se = _mean_se(roots)
    loss_se = (math.hypot(best[3], ch[3]) if ch and best[3] is not None and ch[3] is not None
               else None)  # fmt: skip
    r3 = lambda x: None if x is None else round(x, 3)  # noqa: E731
    shown = opts[:6] + ([by[chosen]] if chosen in by and by[chosen] not in opts[:6] else [])
    return Decision(
        turn=p.turn, kind=KINDS.get(p.kind, "turn"), chosen=chosen, best=best[0],
        value=round(value, 3), chosen_value=r3(ch[2]) if ch else None, best_value=round(best[2], 3),
        loss=round(best[2] - ch[2], 3) if ch else None,
        chosen_share=round(by[chosen][1], 3) if chosen in by else 0.0,
        options=[[c, round(s, 3), r3(q), r3(e)] for c, s, q, e in shown],
        state=public_state(p.state), events=events.get(p.turn, []),
        value_se=r3(value_se), loss_se=r3(loss_se), repeats=len(searches), visits=visits,
    )  # fmt: skip


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


def verdict(d: dict, z: float = 2.0, low_share: float = 0.10) -> str:
    """How the search sees a decision (the review page computes the same, its two thresholds
    adjustable): "same" (the search's own choice); "bad" -- the search hardly tried the choice
    (its visit share under ``low_share`` while its own choice took at least half) and the
    winning chance it loses is real (more than ``z`` standard errors; without errors: 5 points),
    or the loss alone is real and at least 5 points; "mild" -- hardly tried but the loss is
    within the noise (or unknown: never tried); "ok" otherwise."""
    if d["chosen"] == d["best"]:
        return "same"
    loss, se = d.get("loss"), d.get("loss_se")
    real = loss is not None and (loss > z * se if se else loss >= 0.05)
    shunned = d["chosen_share"] < low_share and d["options"][0][1] >= 0.5
    if shunned:
        return "bad" if real else "mild"
    return "bad" if real and loss >= 0.05 else "ok"


def metrics(report: dict, z: float = 2.0, low_share: float = 0.10) -> dict:
    """The game's scorecard (as Go and chess reviews give, 2026-10-30): over the decisions with a
    choice (two options or more the search tried) how often the player chose the search's first
    choice ("top1") and one of its first two by visits ("top2"), the mean winning chance lost
    (each decision's loss, at least 0; unknown for a choice never tried: left out), and over all
    decisions how many verdicts were "bad" / "mild" (``z`` / ``low_share``: verdict's)."""
    ds = [d for d in report["decisions"] if len(d["options"]) >= 2]
    n = len(ds)
    losses = [max(0.0, d["loss"]) for d in ds if d["loss"] is not None]
    vs = [verdict(d, z, low_share) for d in report["decisions"]]
    return {
        "decisions": n,
        "top1": sum(d["chosen"] == d["options"][0][0] for d in ds) / n if n else None,
        "top2": sum(d["chosen"] in (d["options"][0][0], d["options"][1][0]) for d in ds) / n
        if n
        else None,
        "mean_loss": statistics.fmean(losses) if losses else None,
        "bad": vs.count("bad"),
        "mild": vs.count("mild"),
    }


def key_moments(report: dict, k: int = 5, min_score: float = 0.10) -> list[dict]:
    """The decisions the search disagreed with most (mistake_score >= ``min_score``), worst
    first, each with its score."""
    ds = sorted(report["decisions"], key=mistake_score, reverse=True)
    return [d | {"score": round(mistake_score(d), 3)} for d in ds
            if mistake_score(d) >= min_score and verdict(d) == "bad"][:k]  # fmt: skip


def swings(report: dict, k: int = 3) -> list[dict]:
    """The largest drops of the player's winning chance from one decision to the next (what
    happened in between: the turn's events -- the opponent's play, luck, the player's choice)."""
    ds = report["decisions"]
    drops = [(a["value"] - b["value"], a, b) for a, b in zip(ds, ds[1:], strict=False)]
    return [{"from": a["turn"], "to": b["turn"], "drop": round(x, 3), "before": a["value"],
             "after": b["value"], "events": a["events"]}
            for x, a, b in sorted(drops, key=lambda t: -t[0])[:k] if x > 0.05]  # fmt: skip
