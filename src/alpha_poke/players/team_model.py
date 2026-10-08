"""Step 1 of design D5-O: which teams and sets a specific player uses.

Teams, at the species level (what we choose our team against, before team preview):
  p(s) = (sum_i w_i [s in T_i] + k * b(s)) / (sum_i w_i + k)
with w_i = 0.5 ** (age_i / half_life) over the player's earlier games and b the ladder usage at
their level (Smogon gen9ou-0: all players, unweighted; sums to 6). k = 0 is their own
frequency only, k = inf the ladder only. Repeats of whole teams are measured separately (the
"exact" part of the mixture).

Sets: per species, a Dirichlet posterior whose prior is the generic belief model's
team-conditioned prediction with weight ``k_set``, updated with what the player revealed in
earlier games.

Everything is evaluated rolling-origin: game i is predicted from games < i only."""

import math
from collections import Counter, defaultdict
from pathlib import Path

from alpha_poke.analysis.roles import to_id
from alpha_poke.data.smogon_stats import DEFAULT_DIR, UsageStats
from alpha_poke.players.games import Game
from alpha_poke.teams.validate import preview_name

DAY = 86400.0
FLOOR = 1e-4  # probability of a species / value never seen anywhere


def ladder_usage(months: list[str] | None = None, cutoff: str = "0") -> dict[str, float]:
    """Species (preview names) -> fraction of teams with it, averaged over ``months``."""
    months = months or sorted(p.name for p in Path(DEFAULT_DIR).iterdir() if p.is_dir())
    acc: Counter = Counter()
    for m in months:
        stats = UsageStats.load(DEFAULT_DIR / m / "chaos" / f"gen9ou-{cutoff}.json")
        for name, s in stats.species.items():
            acc[preview_name(name)] += s.usage / len(months)
    return dict(acc)


def inclusion(past: list[Game], now: int, base: dict[str, float], half_life: float,
              k: float, unit: str = "games") -> dict[str, float]:  # fmt: skip
    """p(species in the player's next team) from their games before ``now``; recency weight
    0.5 ** (age / half_life), age in games back (``unit="games"``) or days. Days make every
    weight small after a long break (the ladder prior takes over); games do not."""
    if unit == "games":
        w = [0.5 ** ((len(past) - j) / half_life) for j in range(len(past))]
    else:
        w = [0.5 ** ((now - g.time) / DAY / half_life) for g in past]
    total = sum(w)
    seen: Counter = Counter()
    for wi, g in zip(w, past, strict=True):
        for s in g.team:
            seen[s] += wi
    if math.isinf(k):
        return dict(base)
    return {s: (seen.get(s, 0.0) + k * base.get(s, 0.0)) / (total + k)
            for s in set(base) | set(seen)}  # fmt: skip


def team_score(p: dict[str, float], team: list[str]) -> tuple[float, float]:
    """(mean log2 of p(s)/6 over the team's species: bits per species, as 6 draws from the
    normalized inclusion; recall of the team in the model's 10 most likely species)."""
    bits = sum(math.log2(max(p.get(s, 0.0), FLOOR) / 6) for s in team) / len(team)
    top = {s for s, _ in sorted(p.items(), key=lambda x: -x[1])[:10]}
    return bits, sum(s in top for s in team) / len(team)


def rolling_teams(games: list[Game], base: dict[str, float], half_life: float, k: float,
                  start: int = 10, unit: str = "games") -> tuple[float, float]:  # fmt: skip
    """Mean (bits per species, recall@10) predicting each game from the earlier ones."""
    res = [team_score(inclusion(games[:i], games[i].time, base, half_life, k, unit),
                      games[i].team) for i in range(start, len(games))]  # fmt: skip
    return sum(r[0] for r in res) / len(res), sum(r[1] for r in res) / len(res)


def repeats(games: list[Game], start: int = 10) -> dict:
    """How often a game's team (species) was used before, and its best overlap with an
    earlier team (species in common)."""
    rep, overlap = [], []
    for i in range(start, len(games)):
        earlier = [set(g.team) for g in games[:i]]
        t = set(games[i].team)
        rep.append(any(e == t for e in earlier))
        overlap.append(max(len(e & t) for e in earlier))
    return {"repeat": sum(rep) / len(rep), "overlap": dict(sorted(Counter(overlap).items())),
            "n": len(rep)}  # fmt: skip


# ---- sets ------------------------------------------------------------------------------------
FIELDS = ("item", "tera", "move")


def _revealed(g: Game, species: str) -> dict[str, list[str]]:
    s = g.sets.get(species, {})
    return {"item": [to_id(s["item"])] if s.get("item") else [],
            "tera": [to_id(s["tera"])] if s.get("tera") else [],
            "move": [to_id(m) for m in s.get("moves", [])]}  # fmt: skip


def personal(prior: dict[str, float], counts: Counter, k_set: float) -> dict[str, float]:
    n = sum(counts.values())
    if math.isinf(k_set) or n + k_set == 0:
        return prior
    keys = set(prior) | set(counts)
    return {v: (counts.get(v, 0) + k_set * prior.get(v, 0.0)) / (n + k_set) for v in keys}


def rolling_sets(games: list[Game], belief, k_sets: list[float], start: int = 10) -> dict:
    """Per field and k_set: mean log-likelihood (nats) of each revealed value and top-1
    accuracy (item / tera) or recall in the top 4 (moves), predicting game i from games < i."""
    out = {f: {k: [0.0, 0.0, 0] for k in k_sets} for f in FIELDS}
    counts: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for i, g in enumerate(games):
        team = tuple(g.team)
        if i >= start:
            for sp in g.team:
                rev = _revealed(g, sp)
                if not any(rev.values()):
                    continue
                d = belief.prior.predict(sp, team)
                for f in FIELDS:
                    for k in k_sets:
                        p = personal(getattr(d, f), counts[sp][f], k)
                        top = sorted(p, key=p.get, reverse=True)[: 4 if f == "move" else 1]
                        for v in rev[f]:
                            o = out[f][k]
                            o[0] += math.log(max(p.get(v, 0.0), FLOOR))
                            o[1] += v in top
                            o[2] += 1
        for sp in g.team:
            for f, vals in _revealed(g, sp).items():
                counts[sp][f].update(vals)
    return {f: {k: (o[0] / max(1, o[2]), o[1] / max(1, o[2]), o[2]) for k, o in d.items()}
            for f, d in out.items()}  # fmt: skip
