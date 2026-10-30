"""The fair evaluation pools (2026-10-30): fixed team pairs for comparing two networks' strength
on the ladder -- promotion's test (scripts/selfplay.py eval, default fair2000) and A/B runs
(scripts/eval_pairs.py). Pools under data/derived/teams/pools/fair<N> (git-ignored).

Each pair is the two teams of one real game: games after the training data's cutoff, both
players rated at least ``min_rating``, none of them a source of self-play's teams or of an
earlier test's pool. A side's set: what the game revealed, the rest drawn from Smogon's usage
weighted by 1 - the part's reveal rate (selfplay.teams.marginal_set / reveal_rates, estimated on
``rate_games`` games of the same window) -- not the search's belief, so the opponents are not what
the networks expect them to be. On 600 pairs r2-gen0a3 scored 52.8% +- 2.5% against v6arch-pp-v75
here, 55.9% +- 3.2% on the per-attempt pool drawn like self-play's teams.

Self-play never draws its teams from a fair pool's games (selfplay.py sample_pairs: ``games``)."""

import glob
import json
import random
from pathlib import Path

from alpha_poke import paths

# the released network's (v6arch-pp-v75) training cutoff: its --val-cutoff, the later games held out
TRAINING_CUTOFF = 1776921722


def games(pools: Path = paths.POOLS) -> set[str]:
    """The game ids of every fair pool (self-play must not draw teams from them)."""
    out: set[str] = set()
    for f in glob.glob(str(Path(pools) / "fair*" / "meta.json")):
        meta = json.loads(Path(f).read_text(encoding="utf-8"))
        if meta.get("kind") == "fair":
            out |= set(meta.get("games", []))
    return out


def used_games() -> set[str]:
    """Game ids self-play drew teams from, and earlier tests' per-attempt pools."""
    out = set()
    for f in glob.glob(str(paths.DATA / "selfplay" / "gen*" / "teams.jsonl")):
        with open(f, encoding="utf-8") as fh:
            out |= {json.loads(line).get("game") for line in fh}
    for f in glob.glob(str(paths.DATA / "selfplay" / "gen*" / "eval_pool_*" / "meta.json")):
        out |= set(json.loads(Path(f).read_text(encoding="utf-8")).get("games", []))
    out.discard(None)
    return out


def size(pool: Path) -> int:
    """How many pairs a pool holds."""
    return len(list(Path(pool).glob("pair*_a.txt")))


def build(name: str, pairs: int, since: int = TRAINING_CUTOFF, min_rating: int = 1500,
          rate_games: int = 10000, seed: int = 9300, extend: str = "", pools: Path = paths.POOLS,
          log=print) -> str:  # fmt: skip
    """Write the fair pool ``pools/<name>`` of ``pairs`` pairs and return its path. ``extend``:
    another fair pool whose pairs come first, unchanged (its results stay comparable); the rest
    new games, none of its."""
    import logging

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.analysis.games_lite import logs
    from alpha_poke.replay.parser import parse_replay
    from alpha_poke.selfplay.pools import write_pool
    from alpha_poke.selfplay.teams import TeamSampler, reveal_rates

    if (Path(pools) / name).exists():  # (a pool is fixed: never rewritten in place)
        raise FileExistsError(f"{Path(pools) / name} exists")
    base_texts, base_meta = [], {"games": [], "ratings": []}
    if extend:
        src = Path(pools) / extend
        base_meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
        for k in range(size(src)):
            base_texts += [(src / f"pair{k:03d}_{x}.txt").read_text(encoding="utf-8") for x in "ab"]
    need = pairs - len(base_texts) // 2
    logging.disable(logging.WARNING)
    exclude = used_games() | set(base_meta["games"])
    ts = TeamSampler(BeliefModel.load(), since=since, catalog_frac=0.0, seed=seed, fill="marginal",
                     min_rating=min_rating, exclude=exclude)  # fmt: skip
    log(f"{len(ts.games)} eligible games ({len(exclude)} excluded ids)")
    rows = ts.games.sample(min(rate_games, len(ts.games)), random_state=seed).to_dict("records")
    records = []
    for row in logs(rows).values():
        rep = parse_replay(row)
        if not rep.warnings:
            records += [m for s in ("p1", "p2") for m in rep.teams[s] if not m.phantom]
    ts.rates = reveal_rates(records, ts.stats)
    log(f"reveal rates from {len(records)} mons: {ts.rates['default']}")
    new = ts.sample(need) if need > 0 else []
    texts = base_texts + [t for p in new for t in (p.p1.text, p.p2.text)]
    show = lambda kind, keys: {k: round(ts.rates[kind].get(k, -1), 3) for k in keys}  # noqa: E731
    meta = {
        "kind": "fair", "seed": seed, "since": since, "min_rating": min_rating, "extends": extend or None,
        "fill": "revealed parts kept, the rest Smogon usage x (1 - reveal rate); never-brought mons: usage",
        "rate_mons": len(records), "rates_default": ts.rates["default"],
        "rates_sample": show("item", ["leftovers", "heavydutyboots", "lifeorb", "choicescarf", "rockyhelmet",
                                      "boosterenergy", "assaultvest"]),
        "fill_counts": dict(ts.fill_counts), "excluded_ids": len(exclude),
        "games": base_meta["games"] + [p.game for p in new],
        "ratings": base_meta["ratings"] + [list(p.ratings) for p in new],
    }  # fmt: skip
    path = write_pool(Path(pools) / name, texts, meta)
    log(f"{path}: {len(texts) // 2} pairs; {random.Random(seed).choice(texts)[:200]}")
    return path
