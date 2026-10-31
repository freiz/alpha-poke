"""What the metagame says of a team (2026-10-30; the review's team analysis): from the snapshot
scripts/build_meta_knowledge.py builds and the app ships (meta_knowledge.json.gz beside this file:
nothing is fetched on the player's computer). All of it by species: the matchup model knows no
sets, the ladder's numbers are its players' too.

  expected score   the matchup model's (analysis.matchups: species strength and species-vs-species,
                   equal ratings) mean chance against the recent metagame's compositions, and the
                   mean over its worst 20% (CVaR: what the team loses to)
  threats          its chance against the compositions that bring each of the metagame's 15 most
                   used species: the worst and the best
  members          each member's strength in the model (rank), its checks and counters and its usual
                   teammates (Smogon)
  cores            the team's pairs on the ladder: games, win rate, margin over the ratings' expectation
  synergy          the team's pairs by the model's teammate term (S: what two bring together beyond
                   each alone, from the games), in points of winning chance
  threat coverage  set by set (teams.threats, the damage model): for each of the metagame's most
                   used species' main builds (the snapshot's), which of the team checks or revenge-
                   kills it and which of the team it KOs in one hit -- the team's sets exact when
                   pasted, else what the game showed, completed by the species' most common set
  swaps            one member replaced by one of the metagame's 40 most used species: the model's
                   best gains (a lead to look at, not a verdict: roles, sets and synergy are unseen)
  similar teams    the forum's complete teams and the ladder's best compositions sharing 4 or more
                   species (none: 3): what they run instead, their record or score"""

import functools
import gzip
import json
from pathlib import Path

import numpy as np

SNAPSHOT = Path(__file__).with_name("meta_knowledge.json.gz")
TAIL, THREATS, SWAP_POOL = 0.2, 15, 40


@functools.cache
def load(path: Path = SNAPSHOT) -> dict | None:
    """The shipped snapshot, prepared (None without it)."""
    return prepare(json.loads(gzip.decompress(path.read_bytes()))) if path.exists() else None


def prepare(snap: dict) -> dict:
    """A snapshot (build_meta_knowledge's dict) with its arrays and indexes ready."""
    m = snap["model"]
    snap["_idx"] = {s: i for i, s in enumerate(m["species"])}
    snap["_a"] = np.array(m["a"], dtype=float)
    snap["_M"] = np.array(m["M"], dtype=float)
    meta = snap["metagame"]
    snap["_w"] = np.array([w for _, w in meta], dtype=float)
    snap["_w"] /= snap["_w"].sum()
    snap["_teams"] = [k.split("|") for k, _ in meta]
    snap["_opp"] = np.array(
        [[snap["_idx"].get(s, len(m["species"]) - 1) for s in t] for t in snap["_teams"]]
    )
    S = np.array(m["S"], dtype=float) if m.get("S") else np.zeros_like(snap["_M"])
    snap["_S"] = S
    opp = snap["_opp"]  # (each composition's own teammate term, counted once per pair)
    snap["_syn_opp"] = S[opp[:, :, None], opp[:, None, :]].sum((1, 2)) / 2
    use: dict[str, float] = {}
    for t, w in zip(snap["_teams"], snap["_w"], strict=True):
        for s in t:
            use[s] = use.get(s, 0.0) + w
    snap["_use"] = sorted(use.items(), key=lambda kv: -kv[1])
    return snap


def _scores(snap: dict, team: list[str]) -> np.ndarray:
    """The model's chance of ``team`` against each metagame composition (equal ratings)."""
    other = len(snap["_a"]) - 1
    ic = [snap["_idx"].get(s, other) for s in team]
    opp = snap["_opp"]
    z = (snap["_a"][ic].sum() - snap["_a"][opp].sum(1)
         + snap["_M"][np.ix_(ic, opp.ravel())].reshape(len(ic), -1, opp.shape[1]).sum((0, 2))
         + snap["_S"][np.ix_(ic, ic)].sum() / 2 - snap["_syn_opp"])  # fmt: skip
    return 1 / (1 + np.exp(-z))


def _summary(snap: dict, p: np.ndarray) -> tuple[float, float]:
    w = snap["_w"]
    order = np.argsort(p)
    k = int(np.searchsorted(np.cumsum(w[order]), TAIL)) + 1
    return float((p * w).sum()), float((p[order][:k] * w[order][:k]).sum() / w[order][:k].sum())


def team_export(report: dict, team_sets: dict | None = None) -> tuple[str, bool]:
    """The reviewed player's team as a Showdown export, and whether it is exact: its pasted sets
    (KnownSet dicts by species id), else what the game showed completed by the species' most
    common set (Smogon: item, ability, tera, moves, spread)."""
    from alpha_poke.analysis.roles import to_id
    from alpha_poke.coach.narrate import usage_table

    usage = usage_table()

    def top(d):
        return next(iter(d), None) if d else None

    blocks = []
    for rec in report["teams"][report["side"]]:
        sp = rec["species"].replace("-*", "")
        sid = to_id(sp)
        k = next(
            (
                v
                for key, v in (team_sets or {}).items()
                if sid.startswith(key) or key.startswith(sid)
            ),
            None,
        )
        u = usage.get(sid)
        if k:
            item, ability, tera = k.get("item"), k.get("ability"), k.get("tera")
            moves = list(k.get("moves") or [])
            nature, evs = k.get("nature") or "serious", list(k.get("evs") or [0] * 6)
        else:
            item = rec.get("item") or (top(u.items) if u else None)
            ability = rec.get("ability") or (top(u.abilities) if u else None)
            tera = rec.get("tera") or (top(u.tera_types) if u else None)
            moves = [to_id(m) for m in rec.get("moves") or []]
            extra = [m for m in (u.move_has if u else {}) if m not in moves and m != "nothing"]
            moves += extra[: max(0, 4 - len(moves))]
            spread = top(u.spreads) if u else None
            nature, evs = (
                (spread.split(":")[0], spread.split(":")[1].split("/"))
                if spread
                else ("serious", [84] * 6)
            )
        names = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
        lines = [f"{sp} @ {item}" if item and item != "nothing" else sp]
        lines += [f"Ability: {ability}"] if ability else []
        lines += [f"Tera Type: {str(tera).capitalize()}"] if tera else []
        if any(int(e) for e in evs):
            lines.append(
                "EVs: "
                + " / ".join(f"{int(e)} {n}" for e, n in zip(evs, names, strict=True) if int(e))
            )
        lines += [f"{str(nature).capitalize()} Nature"] + [f"- {m}" for m in moves[:4]]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), bool(team_sets)


def threat_coverage(export: str, snap: dict) -> dict | None:
    """Set by set: per threat (the snapshot's builds) which of the team answers it, which it KOs."""
    from alpha_poke.teams.threats import answers, ko_by, own_views

    if not snap.get("threats"):
        return None
    try:
        ours = own_views(export)
    except Exception:  # noqa: BLE001 - an export poke-env cannot read: no coverage
        return None
    out = []
    for name, builds in snap["threats"].items():
        views = [(w, own_views(text)[0]) for w, text in builds]
        out.append(
            {
                "threat": name,
                "answered_by": answers(ours, views),
                "kos_in_one_hit": ko_by(ours, views),
            }
        )
    return {"threats": out, "unanswered": [x["threat"] for x in out if not x["answered_by"]],
            "one_answer": [x["threat"] for x in out if len(x["answered_by"]) == 1]}  # fmt: skip


def facts(
    team: list[str], snap: dict | None = None, export: tuple[str, bool] | None = None
) -> dict | None:
    """The metagame's facts of ``team`` (its species as the replays name them: preview names);
    None without the snapshot (``snap``: a prepared one, else the shipped one). ``export``:
    team_export's (the threat coverage, set by set)."""
    snap = snap or load()
    if snap is None:
        return None
    w = snap["_w"]
    p = _scores(snap, team)
    mean, cvar = _summary(snap, p)
    threats = {}
    for s, share in snap["_use"][:THREATS]:
        has = np.array([s in t for t in snap["_teams"]])
        threats[s] = (float((p[has] * w[has]).sum() / w[has].sum()), round(share, 3))
    ranked = sorted(threats.items(), key=lambda kv: kv[1][0])
    strength = {s: i + 1 for i, s in enumerate(sorted(snap["model"]["species"][:-1],
                                                      key=lambda s: -snap["_a"][snap["_idx"][s]]))}  # fmt: skip
    members = []
    for s in team:
        sm = snap["smogon"].get(s, {})
        members.append({"species": s, "model_strength_rank": strength.get(s),
                        "of": len(strength), "metagame_share": round(dict(snap["_use"]).get(s, 0.0), 3),
                        "checks_and_counters": [{"species": c, "ko_or_forced_out": pr, "games": n}
                                                for c, pr, n in sm.get("counters", [])[:5]],
                        "usual_teammates": sm.get("teammates", [])[:6]})  # fmt: skip
    cores = []
    for i, a in enumerate(team):
        for b in team[i + 1 :]:
            c = snap["cores"].get("|".join(sorted((a, b))))
            if c:
                cores.append(
                    {"pair": [a, b], "games": c[0], "win": c[1], "margin_over_ratings": c[2]}
                )
    swaps = []
    pool = [s for s, _ in snap["_use"][:SWAP_POOL] if s not in team]
    for i, out in enumerate(team):
        for new in pool:
            m2, c2 = _summary(snap, _scores(snap, team[:i] + [new] + team[i + 1 :]))
            swaps.append({"out": out, "in": new, "expected": round(m2, 3), "gain": round(m2 - mean, 3),
                          "worst_20pct": round(c2, 3)})  # fmt: skip
    swaps = sorted(swaps, key=lambda x: -x["gain"])[:5]
    similar = []
    mine = set(team)
    for src, rows in (("forum", snap["forum"]), ("ladder", snap["ladder"])):
        for r in rows:
            theirs = r["key"].split("|")
            shared = len(mine & set(theirs))
            if shared >= 3:
                x = {"source": src, "shared": shared, "they_have": sorted(set(theirs) - mine),
                     "you_have": sorted(mine - set(theirs)), "model_expected": round(_summary(snap, _scores(snap, theirs))[0], 3)}  # fmt: skip
                if src == "forum":
                    x["date"] = r["date"][:10]
                    x["their_sets"] = [b for b in r["text"].split("\n\n")
                                       if any(b.startswith(s) or f"({s})" in b.split("\n")[0] for s in x["they_have"])]  # fmt: skip
                else:
                    x |= {"games": r["games"], "win": r["win"], "margin_over_ratings": r["margin"]}
                similar.append(x)
    # (4 or more species shared; a team of one's own may have none: then 3)
    close = [x for x in similar if x["shared"] >= 4] or similar
    similar = sorted(close, key=lambda x: (-x["shared"], -x["model_expected"]))[:5]
    cover = threat_coverage(export[0], snap) if export else None
    return {
        "about": {"built": snap["built"], **{k: snap["sources"][k] for k in ("games_to", "smogon_month", "meta_days")},
                  "note": "species only: the model knows no sets; ladder records are their players' too"},
        "expected_vs_metagame": round(mean, 3), "worst_20pct_of_metagame": round(cvar, 3),
        "threats_worst": [{"species": s, "score_vs_teams_with_it": round(v, 3), "metagame_share": sh}
                          for s, (v, sh) in ranked[:5]],
        "threats_best": [{"species": s, "score_vs_teams_with_it": round(v, 3), "metagame_share": sh}
                         for s, (v, sh) in ranked[-3:]],
        "members": members, "cores": cores, "synergy": _synergy(snap, team), "swaps": swaps, "similar_teams": similar,
    } | ({"threat_coverage": cover | {"your_sets_exact": export[1]}} if cover else {})  # fmt: skip


def _synergy(snap: dict, team: list[str]) -> list[dict]:
    """The team's pairs by the teammate term, in points of winning chance (S / 4 at even odds):
    the best 3 and the worst 2 of at least half a point."""
    other = len(snap["_a"]) - 1
    pairs = []
    for i, a in enumerate(team):
        for b in team[i + 1 :]:
            ia, ib = snap["_idx"].get(a, other), snap["_idx"].get(b, other)
            if other not in (ia, ib):
                pairs.append(
                    {"pair": [a, b], "points": round(float(100 * snap["_S"][ia, ib] / 4), 1)}
                )
    pairs = [x for x in sorted(pairs, key=lambda x: -x["points"]) if abs(x["points"]) >= 0.5]
    return [x for x in pairs if x["points"] > 0][:3] + [x for x in pairs if x["points"] < 0][-2:]
