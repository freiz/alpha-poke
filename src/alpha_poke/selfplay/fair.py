"""The fair evaluation teams (2026-10-30): for comparing two networks' strength on the ladder --
promotion's test (scripts/selfplay.py eval) and A/B runs (scripts/eval_pairs.py). Under
data/derived/teams/pools (git-ignored).

  teambank10k  the team bank promotion draws from (``bank_build`` / ``bank_pool``): 10,000 sides
               of real games, each test pairing its own 2,000 of them anew -- the same month,
               ratings within 200, every team once (Showdown's ladder pairs by rating only, not
               by team: a real game's two teams are such a draw); no fixed small set
  fair<N>      fixed pairs, each the two teams of one real game (``build``): the reference for
               comparing generations on identical teams (fair1000)

The games: after the training data's cutoff, both players rated at least ``min_rating``, none a
source of self-play's teams or of an earlier test's pool; the bank's from the test half of the
games (``test_half``: by id). A side's set: what its game revealed, the rest drawn from Smogon's
usage weighted by 1 - the part's reveal rate (selfplay.teams.marginal_set / reveal_rates) -- not
the search's belief, so the opponents are not what the networks expect them to be. The bank's
sides weighted by min(1, cap / the games its player played with that composition): a team many
players use stays common (the metagame), one player's grind with one team does not dominate.
On 600 fair1000 pairs r2-gen0a3 scored 52.8% +- 2.5% against v6arch-pp-v75, 55.9% +- 3.2% on the
per-attempt pool drawn like self-play's teams.

Self-play never draws its teams from these games (selfplay.py sample_pairs: ``games``)."""

import collections
import glob
import json
import random
import zlib
from pathlib import Path

from alpha_poke import paths

# the released network's (v6arch-pp-v75) training cutoff: its --val-cutoff, the later games held out
TRAINING_CUTOFF = 1776921722


BANK = "teambank10k"
DAY = 86400


def games(pools: Path = paths.POOLS) -> set[str]:
    """The game ids of every fair pool and team bank (self-play must not draw teams from them)."""
    out: set[str] = set()
    for f in glob.glob(str(Path(pools) / "*" / "meta.json")):
        meta = json.loads(Path(f).read_text(encoding="utf-8"))
        if meta.get("kind") in ("fair", "fairbank"):
            out |= set(meta.get("games", []))
    return out


def test_half(game_id: str) -> bool:
    """The half of the games a team bank draws from (fixed by the id: new games split alike)."""
    return zlib.crc32(game_id.encode()) % 2 == 0


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


def sampler(since: int, min_rating: int, exclude: set, rate_games: int, seed: int, log=print):
    """(a TeamSampler of the eligible games filling sets from reveal-corrected usage, the mons the
    reveal rates were estimated on)."""
    import logging

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.analysis.games_lite import logs
    from alpha_poke.replay.parser import parse_replay
    from alpha_poke.selfplay.teams import TeamSampler, reveal_rates

    logging.disable(logging.WARNING)
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
    return ts, records


def build(name: str, pairs: int, since: int = TRAINING_CUTOFF, min_rating: int = 1500,
          rate_games: int = 10000, seed: int = 9300, extend: str = "", pools: Path = paths.POOLS,
          log=print) -> str:  # fmt: skip
    """Write the fair pool ``pools/<name>`` of ``pairs`` pairs and return its path. ``extend``:
    another fair pool whose pairs come first, unchanged (its results stay comparable); the rest
    new games, none of its."""
    from alpha_poke.selfplay.pools import write_pool

    if (Path(pools) / name).exists():  # (a pool is fixed: never rewritten in place)
        raise FileExistsError(f"{Path(pools) / name} exists")
    base_texts, base_meta = [], {"games": [], "ratings": []}
    if extend:
        src = Path(pools) / extend
        base_meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
        for k in range(size(src)):
            base_texts += [(src / f"pair{k:03d}_{x}.txt").read_text(encoding="utf-8") for x in "ab"]
    need = pairs - len(base_texts) // 2
    exclude = used_games() | set(base_meta["games"])
    ts, records = sampler(since, min_rating, exclude, rate_games, seed, log)
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


def bank_build(name: str = BANK, n: int = 10000, cap: float = 10.0, since: int = TRAINING_CUTOFF,
               min_rating: int = 1500, rate_games: int = 10000, seed: int = 9400,
               pools: Path = paths.POOLS, log=print) -> str:  # fmt: skip
    """Write the team bank ``pools/<name>`` (teams.jsonl: game, side, player, team, time, rating,
    text; meta.json) of ``n`` validated sides of the test half's games, drawn without replacement
    by min(1, ``cap`` / the games their player played with that composition)."""
    import numpy as np
    import pandas as pd

    from alpha_poke.analysis.games_lite import logs
    from alpha_poke.replay.parser import parse_replay
    from alpha_poke.selfplay.teams import poke_env_clash
    from alpha_poke.teams.validate import check

    out = Path(pools) / name
    if out.exists():  # (a bank is fixed: never rewritten in place)
        raise FileExistsError(f"{out} exists")
    exclude = used_games() | games(pools)
    ts, records = sampler(since, min_rating, exclude, rate_games, seed, log)
    g = ts.games[ts.games.id.map(test_half)]
    sides = pd.concat([
        pd.DataFrame({"game": g.id, "side": s, "player": g[s], "team": g[f"team{s[1]}"],
                      "time": g.time, "rating": g[f"r{s[1]}"], "shard": g.shard, "row": g.row})
        for s in ("p1", "p2")
    ], ignore_index=True)  # fmt: skip
    n_pc = sides.groupby(["player", "team"])["game"].transform("size").to_numpy(float)
    w = np.minimum(1.0, cap / n_pc)
    rng = np.random.default_rng(seed)
    order = rng.choice(
        len(sides), size=min(len(sides), int(n * 1.2) + 50), replace=False, p=w / w.sum()
    )
    chosen = sides.iloc[order].to_dict("records")
    log(f"{len(sides)} sides in the test half, {len(chosen)} drawn")
    kept, stats = [], collections.Counter()
    for i in range(0, len(chosen), 500):
        if len(kept) >= n:
            break
        batch = chosen[i : i + 500]
        full = logs([{"id": c["game"], "shard": c["shard"], "row": c["row"]} for c in batch])
        texts, keys = [], []
        for c in batch:
            rep = parse_replay(full[c["game"]])
            recs = [m for m in rep.teams[c["side"]] if not m.phantom]
            if rep.warnings or len(recs) != 6:
                stats["skipped"] += 1
                continue
            text = ts._try_complete(recs)
            if text:
                texts.append(text)
                keys.append(c)
        for c, x in zip(keys, check(texts), strict=True):
            if x["n"] == 6 and not x["problems"] and not poke_env_clash(x["text"]):
                kept.append({k: c[k] for k in ("game", "side", "player", "team", "time", "rating")}
                            | {"time": int(c["time"]), "rating": int(c["rating"]), "text": x["text"]})  # fmt: skip
            else:
                stats["invalid"] += 1
                ts._learn_bans(x["problems"])
        log(f"{len(kept)} teams kept ({dict(stats)})")
    kept = kept[:n]
    out.mkdir(parents=True)
    with open(out / "teams.jsonl", "w", encoding="utf-8") as f:
        for t in kept:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    meta = {"kind": "fairbank", "teams": len(kept), "cap": cap, "seed": seed, "since": since,
            "min_rating": min_rating, "half": "zlib.crc32(id) % 2 == 0", "rate_mons": len(records),
            "rates_default": ts.rates["default"], "fill_counts": dict(ts.fill_counts),
            "stats": dict(stats), "games": sorted({t["game"] for t in kept})}  # fmt: skip
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(f"{out}: {len(kept)} teams")
    return str(out)


def bank_pairs(teams: list[dict], n: int, seed: int, window_days: int = 31,
               max_gap: int = 200) -> list[tuple[dict, dict]]:  # fmt: skip
    """``n`` pairs of a bank's teams (at most): every team once, the two of a pair from the same
    ``window_days`` window with ratings at most ``max_gap`` apart (as the ladder pairs players),
    in a random order of its own for ``seed``."""
    rng = random.Random(seed)
    order = list(range(len(teams)))
    rng.shuffle(order)
    window = [t["time"] // (window_days * DAY) for t in teams]
    by_window: dict[int, list[int]] = collections.defaultdict(list)
    for i in order:
        by_window[window[i]].append(i)
    used: set[int] = set()
    out = []
    for i in order:
        if len(out) >= n:
            break
        if i in used:
            continue
        cands = [j for j in by_window[window[i]]
                 if j != i and j not in used and abs(teams[i]["rating"] - teams[j]["rating"]) <= max_gap]  # fmt: skip
        if not cands:
            continue
        j = rng.choice(cands)
        used |= {i, j}
        out.append((teams[i], teams[j]))
    return out


def bank_pool(bank: Path, out: Path, n: int, seed: int) -> str:
    """A test's pairs drawn from the team bank ``bank`` (``bank_pairs``), written as a pool at
    ``out`` (kept if present: a resumed test plays the same pairs)."""
    from alpha_poke.selfplay.pools import write_pool

    if Path(out).exists() and size(out) > 0:
        return str(out)
    with open(Path(bank) / "teams.jsonl", encoding="utf-8") as f:
        teams = [json.loads(line) for line in f]
    pairs = bank_pairs(teams, n, seed)
    texts = [t for a, b in pairs for t in (a["text"], b["text"])]
    meta = {"kind": "bankdraw", "bank": str(bank), "seed": seed,
            "games": [[a["game"], b["game"]] for a, b in pairs],
            "ratings": [[a["rating"], b["rating"]] for a, b in pairs]}  # fmt: skip
    return write_pool(Path(out), texts, meta)
