"""Checks of the review app's metagame knowledge before it ships (scripts/knowledge.py validate;
2026-10-30): a candidate snapshot (scripts/build_meta_knowledge.py) against the rules of the game
today, its own sources, the snapshot it replaces and the engine.

  structure    every part present and of a plausible size
  freshness    the games, Smogon's month and the Showdown checkout recent enough
  legality     no species banned today (the local Showdown's rules, re-asked: a snapshot built
               before a ban fails) in what the app suggests or names as the metagame; the threats'
               builds pass the validator
  coverage     the threats cover the metagame's Pokemon
  model        the matchup model beats the coin and its teammate term helps (held-out log loss)
  archetypes   the style classifier's leave-one-out accuracy, the features' agreement with the
               forum's titles, the rules' own names all known to Showdown
  diff         what moved since the shipped snapshot (usage, threats, the classifier) -- a large
               move warns: a broken source looks like a new metagame
  damage       the damage model behind the threat check (agents.damage) against poke-engine's
               calculation (checked against Showdown's: doc/engine-diff.md) on the threats' own
               builds: the claims "checks" / "OHKOs" agree

Each check: {"name", "status" ("pass" / "warn" / "fail"), "detail", optional "data"}; a "fail"
stops the promotion."""

import datetime as dt
import random

PASS, WARN, FAIL = "pass", "warn", "fail"


def _c(name: str, ok: bool, detail: str, warn: bool = False, **data) -> dict:
    status = PASS if ok else (WARN if warn else FAIL)
    return {"name": name, "status": status, "detail": detail, **({"data": data} if data else {})}


def structure(snap: dict) -> list[dict]:
    need = {"model": 50, "threats": 50, "metagame": 1000, "smogon": 50, "cores": 100,
            "forum": 200, "ladder": 20}  # fmt: skip
    out = []
    for k, n in need.items():
        part = snap.get(k) or []
        size = len(part["species"] if k == "model" and part else part)
        out.append(_c(f"structure: {k}", size >= n, f"{size} entries (>= {n})"))
    if snap.get("model"):
        m = snap["model"]
        sq = all(len(r) == len(m["species"]) for r in m["M"]) and len(m["a"]) == len(m["species"])
        out.append(_c("structure: model shape", sq, f"{len(m['species'])} species, a and M agree"))
    arch = snap.get("archetypes") or {}
    out.append(_c("structure: archetypes", bool(arch.get("model") and arch.get("stats")),
                  f"{len(arch.get('stats') or {})} archetypes with statistics"))  # fmt: skip
    return out


def freshness(snap: dict, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    src = snap.get("sources") or {}
    games = dt.date.fromisoformat(src.get("games_to", "2000-01-01"))
    month = dt.date.fromisoformat((src.get("smogon_month") or "2000-01") + "-01")
    sd = (src.get("showdown") or " 2000-01-01").split()[-1]
    return [
        _c("freshness: games", (today - games).days <= 14,
           f"the newest game {games} ({(today - games).days} days old; fresh replays: <= 14)", warn=True),
        _c("freshness: Smogon's month", (today - month).days <= 75,
           f"{src.get('smogon_month')} (scripts/fetch_smogon_stats.py)", warn=True),
        _c("freshness: Showdown checkout", (today - dt.date.fromisoformat(sd)).days <= 45,
           f"{src.get('showdown')} (vendor/pokemon-showdown: its rules decide the legality)", warn=True),
    ]  # fmt: skip


def named_species(snap: dict) -> dict[str, set[str]]:
    """The species each part names (the parts the app suggests or calls the metagame)."""

    def keys(rows):
        return {s for k in rows for s in k.split("|")}

    return {
        "metagame": keys(k for k, _ in snap.get("metagame") or []),
        "threats": set(snap.get("threats") or {}),
        "cores": keys(snap.get("cores") or {}),
        "smogon": set(snap.get("smogon") or {}),
        "ladder": keys(r["key"] for r in snap.get("ladder") or []),
        "forum": keys(r["key"] for r in snap.get("forum") or []),
    }


def legality(snap: dict, fmt: str = "gen9ou") -> list[dict]:
    from alpha_poke.teams.validate import banned_species, check

    parts = named_species(snap)
    model = set((snap.get("model") or {}).get("species", [])[:-1])
    banned = banned_species(sorted(set().union(*parts.values()) | model), fmt)
    out = []
    for k, names in parts.items():
        bad = sorted(names & set(banned))
        out.append(_c(f"legality: {k}", not bad, f"banned today: {', '.join(bad) or 'none'}"))
    unlisted = sorted((model & set(banned)) - set(snap.get("banned") or {}))
    out.append(_c("legality: the model's banned list", not unlisted,
                  f"banned but not listed (coach.meta would suggest them): {', '.join(unlisted) or 'none'}"))  # fmt: skip
    texts = [(n, text) for n, t in (snap.get("threats") or {}).items() for _, text in t["builds"]]
    res = check([text for _, text in texts], fmt)
    bad = [
        f"{n}: {r['problems'][0][:90]}"
        for (n, _), r in zip(texts, res, strict=True)
        if r["problems"]
    ]
    out.append(_c("legality: the threats' builds (validator)", len(bad) <= 0.03 * max(len(texts), 1),
                  f"{len(bad)} of {len(texts)} builds not legal (<= 3%: a build is a belief's guess)",
                  warn=bool(bad) and len(bad) <= 0.1 * len(texts), examples=bad[:10]))  # fmt: skip
    return out


def coverage(snap: dict) -> list[dict]:
    share = sum(t["share"] for t in (snap.get("threats") or {}).values())
    return [_c("coverage: threats", share >= 0.95,
               f"{share:.1%} of the metagame's Pokemon (>= 95%)", warn=share >= 0.9)]  # fmt: skip


def model(snap: dict) -> list[dict]:
    v = (snap.get("sources") or {}).get("model_val") or {}
    ll, plain = v.get("val_logloss"), v.get("val_logloss_without_synergy")
    out = [_c("model: held-out log loss", ll is not None and ll < 0.6931,
              f"{ll} (a coin: 0.6931)")]  # fmt: skip
    if ll is not None and plain is not None:
        out.append(_c("model: the teammate term", ll <= plain + 0.001,
                      f"{ll:.4f} with it, {plain:.4f} without", warn=True))  # fmt: skip
    return out


def rule_names() -> list[dict]:
    """Every move, item, ability and species the archetype rules name is known to Showdown (a
    misspelt id would never match)."""
    from alpha_poke.dex import GEN
    from alpha_poke.teams import archetypes as A

    moves = A.ROCKS | A.LAYERS | A.RECOVERY | A.PASSIVE | A.SETUP | A.PIVOTS
    items = A.OFFENSIVE_ITEMS | A.DEFENSIVE_ITEMS
    unknown = sorted([m for m in moves if m not in GEN.moves]
                     + [s for s in A.WALLS if s not in GEN.pokedex]
                     + [i for i in items if i not in _items()])  # fmt: skip
    return [
        _c("archetypes: the rules' names", not unknown, f"unknown to Showdown: {unknown or 'none'}")
    ]


def _items() -> set[str]:
    from alpha_poke.coach.packet import en_names

    return set(en_names("items"))


def archetypes(snap: dict) -> list[dict]:
    arch = snap.get("archetypes") or {}
    m = arch.get("model") or {}
    loo = m.get("loo", 0.0)
    out = [_c("archetypes: style classifier", loo >= 0.6,
              f"leave-one-out {loo:.1%} on {m.get('n')} titled teams (>= 60%; 2026-10-30: 74.6%)",
              warn=loo >= 0.5)]  # fmt: skip
    feats = (arch.get("agreement") or {}).get("model") or {}
    weak = [f"{k} {v['recall']:.0%} of {v['n']}" for k, v in feats.items()
            if k not in ("stall", "balance", "bulky offense", "hyper offense") and v["n"] >= 10
            and v["recall"] < 0.8]  # fmt: skip
    out.append(_c("archetypes: features vs forum titles", not weak,
                  f"recall < 80% (titles naming it >= 10): {', '.join(weak) or 'none'}", warn=True))  # fmt: skip
    empty = [k for k in ("stall", "balance", "bulky offense", "hyper offense")
             if not (arch.get("stats") or {}).get(k, {}).get("share")]  # fmt: skip
    out.append(
        _c("archetypes: every style seen", not empty, f"no share: {empty or 'none'}", warn=True)
    )
    return out + rule_names()


def _usage(snap: dict) -> dict[str, float]:
    use: dict[str, float] = {}
    total = sum(w for _, w in snap.get("metagame") or []) or 1.0
    for k, w in snap.get("metagame") or []:
        for s in k.split("|"):
            use[s] = use.get(s, 0.0) + w / total / 6
    return use


def diff(snap: dict, prev: dict | None) -> list[dict]:
    if not prev:
        return [_c("diff: previous snapshot", True, "none (a first build)")]
    a, b = _usage(prev), _usage(snap)
    moved = sum(abs(a.get(s, 0.0) - b.get(s, 0.0)) for s in set(a) | set(b)) / 2
    top = lambda u: [s for s, _ in sorted(u.items(), key=lambda kv: -kv[1])[:30]]  # noqa: E731
    came, left = sorted(set(top(b)) - set(top(a))), sorted(set(top(a)) - set(top(b)))
    out = [_c("diff: usage moved", moved <= 0.25,
              f"{moved:.1%} of the metagame's Pokemon changed hands since {prev.get('built')} (<= 25%); "
              f"top 30 in: {', '.join(came) or '-'}; out: {', '.join(left) or '-'}",
              warn=True, came=came, left=left)]  # fmt: skip
    pa = ((prev.get("archetypes") or {}).get("model") or {}).get("loo")
    pb = ((snap.get("archetypes") or {}).get("model") or {}).get("loo")
    if pa is not None and pb is not None:
        out.append(_c("diff: style classifier", pb >= pa - 0.05,
                      f"leave-one-out {pa:.1%} -> {pb:.1%}", warn=True))  # fmt: skip
    return out


def engine_mon(view, moves):
    """A damage view (agents.damage.MonView: an export's exact stats) as poke-engine's Pokemon."""
    import poke_engine as pe

    from alpha_poke.agents.engine_state import _base_types, _types
    from alpha_poke.analysis.roles import to_id

    mon, st = view.mon, view.stats
    return pe.Pokemon(
        id=mon.species, level=100, types=_types(mon), base_types=_base_types(mon.species),
        hp=st["hp"], maxhp=st["hp"], ability=to_id(view.ability or "none"),
        base_ability=to_id(view.ability or "none"), item=mon.item or "none", attack=st["atk"],
        defense=st["def"], special_attack=st["spa"], special_defense=st["spd"], speed=st["spe"],
        weight_kg=float(mon.weight or 50), moves=[pe.Move(id=m.id, pp=16) for m in moves][:4],
    )  # fmt: skip


def engine_damage(att, dfn, move_id: str) -> float:
    """poke-engine's max roll (no crit) of ``move_id`` from ``att`` on ``dfn``, of its HP."""
    import poke_engine as pe

    fainted = [pe.Pokemon.create_fainted()] * 5
    s = pe.State(
        side_one=pe.Side(pokemon=[att] + fainted), side_two=pe.Side(pokemon=[dfn] + fainted)
    )
    rolls = pe.calculate_damage(s, move_id, "splash", True)[0]
    return (rolls[0] if rolls else 0) / dfn.maxhp


# damage the engine computes from the turn (order, the foe's move, its own rolls) or a probe can
# not see (check_damage_calc's exclusions): not compared
SKIP_MOVES = {"payback", "boltbeak", "fishiousrend", "avalanche", "revenge", "assurance", "lashout",
              "ragefist", "retaliate", "stompingtantrum", "temperflare", "focuspunch", "beatup",
              "lastrespects", "counter", "mirrorcoat", "metalburst", "comeuppance", "fling",
              "suckerpunch", "thunderclap", "upperhand", "futuresight", "fakeout",
              "firstimpression", "endeavor", "ficklebeam", "superfang", "ruination",
              "naturesmadness", "seismictoss", "nightshade", "finalgambit", "electroshot",
              "solarbeam", "solarblade", "meteorbeam", "skyattack", "phantomforce", "dig", "dive",
              "fly", "bounce", "shadowforce", "terablast", "terastarstorm",
              # (escalating hits: the engine one hit of its own power, not the model's expected hits)
              "tripleaxel", "triplekick", "populationbomb"}  # fmt: skip


def damage(snap: dict, n: int = 600, seed: int = 0) -> list[dict]:
    """The damage model (an expectation: average roll, expected hits, accuracy) against the
    engine's max roll x 0.925 x the same hits and accuracy on ``n`` random pairs of the threats'
    builds (each attacker's best move by the model; not into Disguise / Ice Face, which the engine
    blocks): the share within 5 points of the defender's HP or 10% of the damage, the agreement of
    the threat check's verdicts (< 50%: "comes in"; >= 100%: "OHKO"), and the worst pairs with
    the attacker's ability and item (what the model leaves out shows there)."""
    from alpha_poke.agents.damage import AVG_ROLL, damage_fraction, is_damaging
    from alpha_poke.teams.threats import own_views

    views = []
    for t in (snap.get("threats") or {}).values():
        for _, text in t["builds"]:
            try:
                views.append(own_views(text)[0])
            except Exception:  # noqa: BLE001 - a build poke-env cannot read: not sampled
                continue
    rng = random.Random(seed)
    close = verdict = done = 0
    worst = []
    for _ in range(n):
        (va, ma), (vd, md) = rng.choice(views), rng.choice(views)
        moves = [m for m in ma if is_damaging(m) and m.id not in SKIP_MOVES]
        if (
            not moves
            or va.mon.ability in ("protean", "libero", "analytic")
            or vd.mon.ability in ("disguise", "iceface")
        ):
            continue
        best = max(moves, key=lambda m: damage_fraction(va, vd, m))
        ours = damage_fraction(va, vd, best)
        try:
            eng = AVG_ROLL * engine_damage(engine_mon(va, ma), engine_mon(vd, md), best.id)
            eng *= (best.expected_hits or 1) * (
                best.accuracy if isinstance(best.accuracy, float) else 1.0
            )
        except BaseException:  # noqa: BLE001 - the binding panics on a name it lacks
            continue
        done += 1
        close += abs(ours - eng) <= max(0.05, 0.1 * eng)
        verdict += (ours < 0.5) == (eng < 0.5) and (ours >= 1.0) == (eng >= 1.0)
        worst.append((abs(ours - eng), f"{va.mon.species} ({va.mon.ability}, {va.mon.item}) {best.id} -> "
                      f"{vd.mon.species} ({vd.mon.ability}, {vd.mon.item}): model {ours:.0%}, engine {eng:.0%}"))  # fmt: skip
    if not done:
        return [_c("damage: model vs engine", False, "no pair computed")]
    worst = [w for _, w in sorted(worst, reverse=True)[:10]]
    return [
        _c("damage: model vs engine (amount)", close / done >= 0.85,
           f"{close / done:.1%} of {done} pairs within 5 points / 10% (>= 85%)", warn=close / done >= 0.75,
           worst=worst),
        _c("damage: model vs engine (verdicts)", verdict / done >= 0.9,
           f"{verdict / done:.1%} agree on 'comes in' (< 50%) and 'OHKO' (>= 100%) (>= 90%)",
           warn=verdict / done >= 0.8),
    ]  # fmt: skip


def run(
    snap: dict, prev: dict | None = None, damage_pairs: int = 600, today=None, log=print
) -> list[dict]:
    out = []
    for name, f in (("structure", lambda: structure(snap)), ("freshness", lambda: freshness(snap, today)),
                    ("legality", lambda: legality(snap)), ("coverage", lambda: coverage(snap)),
                    ("model", lambda: model(snap)), ("archetypes", lambda: archetypes(snap)),
                    ("diff", lambda: diff(snap, prev)),
                    ("damage", lambda: damage(snap, damage_pairs) if damage_pairs else [])):  # fmt: skip
        log(f"checking {name} ...")
        try:
            out += f()
        except Exception as e:  # noqa: BLE001 - a check that cannot run fails, the others go on
            out.append(_c(f"{name}: could not run", False, f"{type(e).__name__}: {e}"[:300]))
    return out


def report(checks: list[dict], snap: dict, prev: dict | None) -> str:
    """The checks and the knowledge's main numbers as markdown (for the commit and a reviewer)."""
    icon = {PASS: "ok", WARN: "WARN", FAIL: "FAIL"}
    lines = [f"# Metagame knowledge {snap.get('built')}", "",
             f"Sources: {snap.get('sources', {}).get('games_to')} games, Smogon "
             f"{snap.get('sources', {}).get('smogon_month')}, Showdown {snap.get('sources', {}).get('showdown')}; "
             f"previous: {prev.get('built') if prev else 'none'}", "", "## Checks", "",
             "| | check | detail |", "|---|---|---|"]  # fmt: skip
    for c in checks:
        lines.append(f"| {icon[c['status']]} | {c['name']} | {c['detail'].replace('|', '/')} |")
    for c in checks:
        for k, v in (c.get("data") or {}).items():
            if isinstance(v, list) and v:
                lines += ["", f"{c['name']} -- {k}:", *[f"- {x}" for x in v]]
    arch = snap.get("archetypes") or {}
    if arch.get("stats"):
        lines += ["", "## Archetypes (for review: do the answers make sense?)", "",
                  "| archetype | share | games | win | margin | usual members | answers (model logit, games' lift, games) |",
                  "|---|---|---|---|---|---|---|"]  # fmt: skip
        for k, v in arch["stats"].items():
            mem = ", ".join(s for s, *_ in v["members"][:6])
            ans = ", ".join(f"{s} ({lg:+.2f}, {lf:+.1%}, {n})" for s, lg, lf, n in v["answers"][:6])
            lines.append(
                f"| {k} | {v['share']:.1%} | {v['games']} | {v['win']:.1%} | {v['margin']:+.1%} | {mem} | {ans} |"
            )
        lines += ["", "Style vs style (row's margin over the Elo expectation, games):", ""]
        for k, row in (arch.get("vs") or {}).items():
            lines.append(
                f"- {k}: " + ", ".join(f"vs {o} {m:+.1%} ({n})" for o, (n, m) in row.items())
            )
    return "\n".join(lines) + "\n"
