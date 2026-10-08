"""Per-generation game statistics (design D15-7): how long the games are, what the bots play,
and both by how defensive the two teams are (a long game is normal for two stall teams; a
generation whose games get longer at the same team mix plays more passively, or loops).

Defensiveness of a team: its recovery / protection / setup moves (+ Regenerator / Poison Heal);
of a pair: the sum. Moves played: recovery / protection, setup (status moves that raise the
user's stats), all status moves, switches. From the generation's games, team pairs and
protocol logs only (no network)."""

import json
import re
from pathlib import Path

import numpy as np

RECOVERY = frozenset({
    "recover", "roost", "softboiled", "wish", "rest", "slackoff", "moonlight", "synthesis",
    "morningsun", "milkdrink", "shoreup", "strengthsap", "painsplit", "leechseed", "healorder",
    "lunarblessing", "junglehealing", "protect", "detect", "spikyshield", "banefulbunker",
    "kingsshield", "silktrap", "burningbulwark", "obstruct", "substitute",
})  # fmt: skip
BINS = (0, 4, 8, 12, 16)  # pair defensiveness: [0, 4), [4, 8), ..., [16, inf)


def _id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _move_sets() -> tuple[frozenset, frozenset]:
    """(setup moves, status moves) from the dex."""
    from alpha_poke.dex import GEN

    status = {k for k, v in GEN.moves.items() if v.get("category") == "Status"}
    setup = {k for k in status
             if (GEN.moves[k].get("boosts") and GEN.moves[k].get("target") == "self")
             or (GEN.moves[k].get("self") or {}).get("boosts")}  # fmt: skip
    setup |= {"bellydrum", "curse", "stockpile", "shellsmash", "filletaway", "clangoroussoul",
              "noretreat"}  # fmt: skip
    return frozenset(setup), frozenset(status)


def defensiveness(text: str, setup: frozenset) -> int:
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- ") and _id(line[2:]) in RECOVERY | setup:
            n += 1
        elif line.startswith("Ability:") and _id(line[8:]) in ("regenerator", "poisonheal"):
            n += 1
    return n


def _rows(gen_dir: Path) -> np.ndarray:
    """Per game: (pair defensiveness, turns, capped, moves, recovery, setup, status, switches)."""
    setup, status = _move_sets()
    pairs = [json.loads(line) for line in (gen_dir / "teams.jsonl").read_text().splitlines()]
    games, logs = {}, {}
    for f in gen_dir.glob("games-w*.jsonl"):
        for line in f.read_text().splitlines():
            g = json.loads(line)
            games[g["pair"]] = g
    for f in gen_dir.glob("logs-w*.jsonl"):
        for line in f.read_text().splitlines():
            x = json.loads(line)
            logs[x["pair"]] = x["log"]
    rows = []
    for i, g in games.items():
        if i not in logs or i >= len(pairs):
            continue
        p = pairs[i]
        d = defensiveness(p["p1"]["text"], setup) + defensiveness(p["p2"]["text"], setup)
        moves, switches = [], 0
        for line in logs[i].split("\n"):
            parts = line.split("|")
            if len(parts) > 3 and parts[1] == "move" and "[from]" not in line:
                moves.append(_id(parts[3]))
            elif len(parts) > 2 and parts[1] == "switch":
                switches += 1
        rows.append((d, g["turns"], bool(g.get("capped")), len(moves),
                     sum(m in RECOVERY for m in moves), sum(m in setup for m in moves),
                     sum(m in status for m in moves), switches))  # fmt: skip
    return np.array(rows, float).reshape(-1, 8)


def _summary(a: np.ndarray) -> dict:
    t, mv = a[:, 1], max(a[:, 3].sum(), 1)
    return {
        "games": len(a), "turns_mean": round(float(t.mean()), 2),
        "turns_median": float(np.median(t)),
        "turns_p90": round(float(np.percentile(t, 90)), 1),
        "turns_p99": round(float(np.percentile(t, 99)), 1),
        "over_100": round(float(np.mean(t > 100)), 4),
        "over_200": round(float(np.mean(t > 200)), 4), "capped": int(a[:, 2].sum()),
        "recovery_share": round(a[:, 4].sum() / mv, 4), "setup_share": round(a[:, 5].sum() / mv, 4),
        "status_share": round(a[:, 6].sum() / mv, 4),
        "switch_share": round(a[:, 7].sum() / max(a[:, 3].sum() + a[:, 7].sum(), 1), 4),
    }  # fmt: skip


def game_stats(gen_dir: Path, prev_dir: Path | None = None) -> dict:
    """The generation's statistics, overall and by pair defensiveness; with ``prev_dir`` also
    the change of the mean game length against that generation with the team mix held fixed
    (the previous generation's bin shares) and its bootstrap 95% CI."""
    a = _rows(gen_dir)
    if not len(a):
        return {}
    out = _summary(a) | {"team_defensiveness": round(float(a[:, 0].mean()) / 2, 2)}
    edges = list(BINS[1:])
    b = np.digitize(a[:, 0], edges)
    out["by_defensiveness"] = {
        f"{lo}-{hi - 1 if hi else ''}": _summary(a[b == k])
        for k, (lo, hi) in enumerate(zip(BINS, [*edges, 0], strict=True)) if (b == k).any()
    }  # fmt: skip
    if prev_dir is not None and (prev_dir / "teams.jsonl").exists():
        p = _rows(prev_dir)
        bp = np.digitize(p[:, 0], edges)

        def adjusted(x, bx, y, by) -> float:
            ks = [k for k in range(len(BINS)) if (bx == k).any() and (by == k).any()]
            return sum((by == k).mean() * (x[bx == k, 1].mean() - y[by == k, 1].mean())
                       for k in ks)  # fmt: skip

        rng = np.random.default_rng(0)
        boot = []
        for _ in range(500):
            i, j = rng.integers(0, len(a), len(a)), rng.integers(0, len(p), len(p))
            boot.append(adjusted(a[i], b[i], p[j], bp[j]))
        out["vs_previous"] = {
            "turns_mean_diff": round(float(a[:, 1].mean() - p[:, 1].mean()), 2),
            "turns_mean_diff_same_teams": round(adjusted(a, b, p, bp), 2),
            "ci95": [round(float(np.percentile(boot, 2.5)), 2),
                     round(float(np.percentile(boot, 97.5)), 2)],
            "status_share_diff": round(out["status_share"] - _summary(p)["status_share"], 4),
        }  # fmt: skip
    return out
