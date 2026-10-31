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
TAIL, THREATS, SWAP_POOL = 0.2, 30, 40
RARE = 0.005  # (a threat's share of the opponents' Pokemon under which it is a rare one)


@functools.cache
def load(path: Path = SNAPSHOT) -> dict | None:
    """The shipped snapshot, prepared (None without it); "_sha" its file's (facts_kept's key)."""
    import hashlib

    if not path.exists():
        return None
    raw = path.read_bytes()
    return prepare(json.loads(gzip.decompress(raw))) | {"_sha": hashlib.sha1(raw).hexdigest()[:12]}


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
    """Set by set (teams.threats' damage checks) against every threat of the snapshot (its species
    with a share of the opponents' Pokemon >= 0.05%: 98% of them): the share of the opponents'
    Pokemon the team answers (checks or revenge-kills in every main build), the unanswered and the
    singly answered by share, the 15 most used in full, and the rare ones (share < RARE) nobody
    answers that KO two or more of the team in one hit -- a counter its rarity would hide."""
    from alpha_poke.teams.threats import answers, ko_by, own_views

    if not snap.get("threats"):
        return None
    try:
        ours = own_views(export)
    except Exception:  # noqa: BLE001 - an export poke-env cannot read: no coverage
        return None
    out = []
    for name, t in snap["threats"].items():
        share, builds = (t["share"], t["builds"]) if isinstance(t, dict) else (None, t)
        views = [(w, own_views(text)[0]) for w, text in builds]
        out.append({"threat": name, "share": share, "answered_by": answers(ours, views),
                    "kos_in_one_hit": ko_by(ours, views)})  # fmt: skip
    total = sum(x["share"] or 0 for x in out)
    by_share = sorted(out, key=lambda x: -(x["share"] or 0))

    def brief(x):
        return {"threat": x["threat"], "share": x["share"], "kos_in_one_hit": x["kos_in_one_hit"]}

    return {
        "checked": len(out), "checked_share": round(total, 3),
        "answered_share": round(sum(x["share"] or 0 for x in out if x["answered_by"]) / total, 3) if total else None,
        "unanswered": [brief(x) for x in by_share if not x["answered_by"]][:10],
        "one_answer": [brief(x) | {"answered_by": x["answered_by"]} for x in by_share if len(x["answered_by"]) == 1][:10],
        "rare_counters": sorted((brief(x) for x in out if not x["answered_by"] and (x["share"] or 0) < RARE
                                 and len(x["kos_in_one_hit"]) >= 2), key=lambda x: -len(x["kos_in_one_hit"]))[:5],
        "most_used": by_share[:15],
    }  # fmt: skip


def counters_by_model(snap: dict, team: list[str], k: int = 5) -> list[dict]:
    """The species the matchup model sees countering this team in particular, however rare: the
    sum of their matchup terms against its six (M; not their strength in general), in points of
    winning chance at even odds, with their share of the opponents' Pokemon (never one banned
    since: the snapshot's "banned")."""
    other = len(snap["_a"]) - 1
    banned = snap.get("banned") or {}
    ic = [snap["_idx"].get(s, other) for s in team]
    share = {s: u / 6 for s, u in snap["_use"]}
    out = []
    for t, j in snap["_idx"].items():
        if j == other or t in team or t in banned:
            continue
        hurt = float(-snap["_M"][ic, j].sum())
        out.append(
            {
                "species": t,
                "points_against_you": round(100 * hurt / 4, 1),
                "share": round(float(share.get(t, 0.0)), 4),
            }
        )
    return sorted(out, key=lambda x: -x["points_against_you"])[:k]


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
    legal = [s for s in snap["model"]["species"][:-1] if s not in (snap.get("banned") or {})]
    strength = {
        s: i + 1 for i, s in enumerate(sorted(legal, key=lambda s: -snap["_a"][snap["_idx"][s]]))
    }
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
    arch = archetype(snap, team, export, p)
    by_model = counters_by_model(snap, team)
    return {
        "about": {"built": snap["built"], **{k: snap["sources"][k] for k in ("games_to", "smogon_month", "meta_days")},
                  "note": "species only: the model knows no sets; ladder records are their players' too"},
        "expected_vs_metagame": round(mean, 3), "worst_20pct_of_metagame": round(cvar, 3),
        "threats_worst": [{"species": s, "score_vs_teams_with_it": round(v, 3), "metagame_share": sh}
                          for s, (v, sh) in ranked[:5]],
        "threats_best": [{"species": s, "score_vs_teams_with_it": round(v, 3), "metagame_share": sh}
                         for s, (v, sh) in ranked[-3:]],
        "members": members, "cores": cores, "synergy": _synergy(snap, team), "swaps": swaps, "similar_teams": similar,
        "counters_by_model": by_model,
    } | ({"archetype": arch} if arch else {}) | ({"threat_coverage": cover | {"your_sets_exact": export[1]}} if cover else {})  # fmt: skip


def facts_kept(review_dir: Path, team: list[str], export: tuple[str, bool]) -> dict | None:
    """facts, kept with the review (team_facts.json): computed again only when the snapshot or the
    team's export changed (the threat check takes a few seconds)."""
    import hashlib

    snap = load()
    if snap is None:
        return None
    key = hashlib.sha1(
        json.dumps(
            [snap.get("_sha"), snap["built"], snap["sources"].get("games_to"), team, export]
        ).encode()
    ).hexdigest()
    f = review_dir / "team_facts.json"
    try:
        kept = json.loads(f.read_text(encoding="utf-8"))
        if kept.get("key") == key:
            return kept["facts"]
    except (OSError, ValueError):
        pass
    out = facts(team, snap, export)
    try:
        f.write_text(json.dumps({"key": key, "facts": out}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


def archetype(snap: dict, team: list[str], export: tuple[str, bool] | None, p=None) -> dict | None:
    """The team's archetype (teams.archetypes: its style by the snapshot's classifier, its
    features by the rules; from its export -- the pasted sets, else what the game showed plus the
    usual sets -- else its species alone) and the metagame's numbers for it: per style and feature
    of the team, the share of the metagame, its record (margin over the Elo expectation), its
    usual members and its answers (the matchup model's logit against a typical such team, the
    games' lift, their games); the team's own expected score by the style it meets (the matchup
    model, ``p`` per composition) and its style's margins against the others."""
    from alpha_poke.teams import archetypes as A

    arch = snap.get("archetypes")
    if not arch:
        return None
    mons = A.from_export(export[0]) if export else [A.mon(s.replace("-*", "")) for s in team]
    t = A.tags(mons, arch["model"])
    out = {"style": t["style"], "style_probs": t["style_probs"], "features": t["features"],
           "from": "sets" if export else "species only"}  # fmt: skip
    stats = arch.get("stats") or {}
    out["metagame"] = {k: {"share": v["share"], "games": v["games"], "margin_over_ratings": v["margin"],
                           "usual_members": [s for s, *_ in v["members"][:6]],
                           "answers": [{"species": s, "model_logit": lg, "games_lift": lf, "games": n}
                                       for s, lg, lf, n in v["answers"][:5]]}
                       for k, v in stats.items() if k in (t["style"], *t["features"])}  # fmt: skip
    if p is not None and arch.get("metagame") and len(arch["metagame"]) == len(p):
        w = snap["_w"]
        by = {}
        for style in A.STYLES:
            has = np.array([tags[0] == style for tags in arch["metagame"]])
            if has.any():
                by[style] = {"share": round(float(w[has].sum()), 3),
                             "expected": round(float((p[has] * w[has]).sum() / w[has].sum()), 3)}  # fmt: skip
        out["your_score_by_opponent_style"] = by
    if (arch.get("vs") or {}).get(t["style"]):
        out["style_vs_style"] = {o: {"games": n, "margin_over_ratings": m}
                                 for o, (n, m) in arch["vs"][t["style"]].items()}  # fmt: skip
    return out


def revealed_archetype(recs: list[dict], snap: dict | None = None) -> dict | None:
    """The archetype of a team as a game showed it (the review's records: species, the moves,
    item and ability seen) -- the opponent's: a guess from what it revealed."""
    from alpha_poke.teams import archetypes as A

    snap = snap or load()
    model = ((snap or {}).get("archetypes") or {}).get("model")
    if not model:
        return None
    mons = [A.mon(r["species"].replace("-*", ""), r.get("moves") or (), r.get("item") or "",
                  r.get("ability") or "") for r in recs]  # fmt: skip
    t = A.tags(mons, model)
    return {"style": t["style"], "style_probs": t["style_probs"], "features": t["features"],
            "from": "what the game revealed"}  # fmt: skip


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
