"""The luck in a game, from its log (2026-10-31; paired evaluations' variance, scripts/eval_stats.py
--luck): for each chance event the log shows -- a critical hit, a miss, a full paralysis -- the
outcome minus its probability, summed per side and kind. Whatever the players choose, each
residual has mean zero given the choice (the probability is the move's or the status's own), so
subtracting a fitted multiple of them from the results (a control variate, as poker's AIVAT does
with chance) leaves the expected score unchanged and takes out part of the luck's variance.

Approximations: the probabilities are the base ones -- a move's accuracy without accuracy /
evasion stages, weather (Thunder in rain), No Guard or Compound Eyes; a crit's chance from the
move's crit ratio without Focus Energy, Super Luck, Scope Lens or crit-immune abilities; a move
into Protect, an immunity or a failure is not an accuracy trial. A wrong probability gives its
residual a small mean -- a bias of the order of how often that case occurs."""

import re

from alpha_poke.analysis.roles import to_id
from alpha_poke.dex import GEN

KINDS = ("crit", "miss", "para")
CRIT = {1: 1 / 24, 2: 1 / 8, 3: 1 / 2}  # (crit ratio -> chance; 4 and up: always)
_MON = re.compile(r"^(p[12])[ab]?: ")


def _side(ident: str) -> str | None:
    m = _MON.match(ident)
    return m.group(1) if m else None


def _move(name: str) -> dict:
    return GEN.moves.get(to_id(name)) or {}


def residuals(log: str) -> dict[str, dict[str, float]]:
    """Per side ("p1", "p2") and kind: {kind: sum of (outcome - probability), kind + "_n":
    trials}. crit: each hit of a damaging move that dealt damage; miss: each use of a move with
    accuracy < 100 at the foe (outcome 1 = missed); para: each turn a paralyzed active Pokemon
    tried to act (outcome 1 = fully paralyzed)."""
    out = {s: {k: 0.0 for k in KINDS} | {f"{k}_n": 0 for k in KINDS} for s in ("p1", "p2")}
    lines = [ln.split("|")[1:] for ln in log.splitlines() if ln.startswith("|")]
    status: dict[str, str] = {}  # "p1: Name" -> its status
    i = 0
    while i < len(lines):
        p = lines[i]
        tag = p[0] if p else ""
        _track(status, p)
        if tag == "cant" and len(p) > 2 and p[2] == "par":
            s = _side(p[1])
            if s:
                out[s]["para"] += 1 - 0.25
                out[s]["para_n"] += 1
        elif tag == "move" and len(p) > 2:
            s = _side(p[1])
            mv = _move(p[2])
            extra = p[4:] if len(p) > 4 else []
            # (the events of this move: up to the next move, switch or turn)
            j = i + 1
            while j < len(lines) and lines[j] and lines[j][0] not in ("move", "switch", "drag", "turn",
                                                                     "cant", "upkeep", "win", "tie"):  # fmt: skip
                j += 1
            ev = lines[i + 1 : j]
            # (the status before this move counts for its paralysis trial; its effects after it)
            par = status.get(_key(p[1])) == "par"
            for e in ev:
                _track(status, e)
            if (
                s
                and mv
                and not any(x.startswith("[still]") or x.startswith("[from]") for x in extra)
            ):
                if par:
                    out[s]["para_n"] += 1
                    out[s]["para"] += 0 - 0.25
                _attack(out[s], mv, ev, s, extra)
            i = j
            continue
        i += 1
    return out


def _track(status: dict, p: list[str]) -> None:
    """A Pokemon's status from a protocol line (set, cured, fainted)."""
    tag = p[0] if p else ""
    if tag == "-status" and len(p) > 2:
        status[_key(p[1])] = p[2]
    elif tag in ("-curestatus", "faint") and len(p) > 1:
        status.pop(_key(p[1]), None)


def _key(ident: str) -> str:
    """ "p1a: Name" -> "p1: Name" (the Pokemon, wherever it is)."""
    side, _, name = ident.partition(": ")
    return f"{side[:2]}: {name}"


def _attack(acc: dict, mv: dict, ev: list[list[str]], side: str, extra: list[str]) -> None:
    foe = "p2" if side == "p1" else "p1"
    on_foe = [e for e in ev if len(e) > 1 and _side(e[1]) == foe]
    blocked = any(e[0] in ("-immune", "-fail") or (e[0] == "-activate" and len(e) > 2 and "Protect" in e[2])
                  for e in ev)  # fmt: skip
    missed = any(e[0] == "-miss" for e in ev) or "[miss]" in extra
    a = mv.get("accuracy")
    if mv.get("target") not in ("self", "allySide", "foeSide", "all", "allyTeam") and isinstance(a, int | float) \
            and not isinstance(a, bool) and a < 100 and not blocked:  # fmt: skip
        acc["miss_n"] += 1
        acc["miss"] += (1.0 if missed else 0.0) - (1 - a / 100)
    if mv.get("category") == "Status" or missed:
        return
    hits = sum(
        1 for e in on_foe if e[0] == "-damage" and not any(x.startswith("[from]") for x in e[3:])
    )
    if not hits:
        return
    hc = next(
        (int(e[2]) for e in ev if e[0] == "-hitcount" and len(e) > 2 and e[2].isdigit()), None
    )
    hits = hc or hits
    ratio = int(mv.get("critRatio") or 1)
    pc = CRIT.get(ratio, 1.0)
    crits = sum(1 for e in on_foe if e[0] == "-crit")
    acc["crit_n"] += hits
    acc["crit"] += crits - hits * pc


def features(log: str, a_side: str) -> list[float]:
    """The luck for side ``a_side`` ("p1" / "p2") of a game: [its crits' residual minus the foe's,
    the foe's misses' residual minus its own, the foe's full paralyses' minus its own] -- each
    positive when chance favoured it, each of mean zero."""
    r = residuals(log)
    me, foe = r[a_side], r["p2" if a_side == "p1" else "p1"]
    return [me["crit"] - foe["crit"], foe["miss"] - me["miss"], foe["para"] - me["para"]]


def log_of_replay(html: str) -> str:
    """A saved replay's (poke-env's save_replays) battle log."""
    m = re.search(r'<script type="text/plain" class="battle-log-data">(.*?)</script>', html, re.S)
    return (m.group(1) if m else html).replace("<\\/", "</")


def side_of(log: str, name_prefix: str) -> str | None:
    """The side ("p1" / "p2") whose player's name starts with ``name_prefix``."""
    for ln in log.splitlines():
        p = ln.split("|")
        if len(p) > 3 and p[1] == "player" and p[3].startswith(name_prefix):
            return p[2]
    return None


def adjusted_pairs(rows: list[dict], replay_dir, theta=None) -> tuple[dict[int, float], dict]:
    """Paired evaluation rows (eval_pairs' log) with their replays (eval_pairs --replays): pair ->
    A's mean score with each game's luck taken out (score - theta . features; theta: the least
    squares fit of the scores on the features over these games, unless given), and the fit
    ({"theta", "r2", "games"}). Games without a replay keep their raw score."""
    from pathlib import Path

    import numpy as np

    from alpha_poke.eval.arena import _score

    replay_dir = Path(replay_dir)
    games = []
    for r in rows:
        s = _score(r)
        if s is None or not r.get("battle"):
            continue
        f = next(iter(replay_dir.glob(f"A* - {r['battle']}.html")), None)
        x = None
        if f is not None:
            log = log_of_replay(f.read_text(encoding="utf-8"))
            side = side_of(log, "A")
            x = features(log, side) if side else None
        games.append((r["pair"], s, x))
    have = [(s, x) for _, s, x in games if x is not None]
    fit = {"games": len(have)}
    if theta is None and len(have) > 10:
        X = np.array([x for _, x in have])
        y = np.array([s for s, _ in have])
        A = np.c_[np.ones(len(X)), X]
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        theta = coef[1:]
        fit["r2"] = round(float(1 - ((y - A @ coef) ** 2).sum() / ((y - y.mean()) ** 2).sum()), 4)
    theta = np.zeros(len(KINDS)) if theta is None else np.asarray(theta, float)
    fit["theta"] = [round(float(t), 4) for t in theta]
    by: dict[int, list[float]] = {}
    for k, s, x in games:
        by.setdefault(k, []).append(s - (float(np.dot(theta, x)) if x is not None else 0.0))
    return {k: sum(v) / len(v) for k, v in by.items() if len(v) == 2}, fit
