"""Task-specific LLM benchmark (English in / English out), auto-graded from our own data.

Tasks
  set_completion  team (6 species) + target mon + 1 revealed move -> item / tera / other moves;
                  graded against later replay reveals; compared with the statistical team prior;
                  also counts illegal moves (not in the species' learnset)
  type_chart      attack type vs defender typing -> multiplier (poke-env type chart)
  speed           which of two species has the higher base Speed (poke-env pokedex)
  naming          grounded archetype naming of mined cores; graded on JSON validity, clear tags
                  (weather / Sticky Web / stall) and *grounding violations*: moves / items
                  mentioned when describing the core that do not appear in the provided DATA
"""

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd
from poke_env.data import GenData

from alpha_poke.analysis.cores import Core
from alpha_poke.analysis.roles import to_id
from alpha_poke.analysis.sets import SpeciesSets
from alpha_poke.llm import LLMClient

GEN = GenData.from_gen(9)
MOVE_IDS = {k: v["name"] for k, v in GEN.moves.items()}
# multi-word non-move names (abilities) so that e.g. 'Water Absorb' is not read as 'Absorb'
OTHER_NAMES = {
    to_id(a) for e in GEN.pokedex.values() for a in (e.get("abilities") or {}).values()
} - set(MOVE_IDS)


def species_id(name: str) -> str:
    return to_id(name.replace("-*", ""))


def _learnset(species: str) -> set[str] | None:
    """Moves a species can know: its own learnset plus those of its pre-evolutions and base
    forme (poke-env's per-species learnsets omit moves inherited from earlier stages)."""
    start = species_id(species)
    if start not in GEN.pokedex:
        match = [k for k in GEN.pokedex if k.startswith(start)]
        if not match:
            return None
        start = match[0]
    seen, todo, moves = set(), [start], set()
    while todo:
        sid = todo.pop()
        if sid in seen or sid not in GEN.pokedex:
            continue
        seen.add(sid)
        moves |= set((GEN.learnset.get(sid) or {}).get("learnset", {}))
        entry = GEN.pokedex[sid]
        for k in ("prevo", "baseSpecies", "changesFrom"):
            if entry.get(k):
                todo.append(to_id(entry[k]))
    return moves or None


TYPE_WORDS = {
    "normal",
    "fire",
    "water",
    "grass",
    "electric",
    "ice",
    "fighting",
    "poison",
    "ground",
    "flying",
    "psychic",
    "bug",
    "rock",
    "ghost",
    "dragon",
    "dark",
    "steel",
    "fairy",
    "stellar",
}


def extract_mentions(text: str, vocab: set[str]) -> set[str]:
    """IDs from ``vocab`` mentioned as Capitalized 1-3 word phrases (e.g. 'Rapid Spin').

    Longest match wins and matched words are consumed, so 'Sludge Bomb' does not also count as
    'Sludge', nor 'Healing Wish' as 'Wish'. Single words that are type names are ignored."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    out, i = set(), 0
    while i < len(words):
        for n in (3, 2, 1):
            chunk = words[i : i + n]
            if len(chunk) < n or not all(w[0].isupper() for w in chunk):
                continue
            cid = to_id(" ".join(chunk))
            if n == 1 and cid in TYPE_WORDS:
                continue
            if len(cid) >= 4 and cid in vocab:
                out.add(cid)
                i += n
                break
            # an ability / other multi-word name (e.g. 'Water Absorb') should swallow its words
            if n > 1 and cid in OTHER_NAMES:
                i += n
                break
        else:
            i += 1
    return out


@dataclass
class TaskResult:
    task: str
    model: str
    metrics: dict
    details: list = field(default_factory=list)


# ---- set completion ---------------------------------------------------------------------
def build_set_completion(test: pd.DataFrame, n: int = 30, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    pool = test[
        test.item.notna() & (test.moves.str.count(r"\|") >= 2) & ~test.species.str.endswith("*")
    ]
    rows = pool.sample(n=min(n, len(pool)), random_state=seed)
    qs = []
    for r in rows.itertuples():
        moves = r.moves.split("|")
        shown = rng.choice(moves)
        qs.append(
            {
                "team": r.team.split("|"),
                "species": r.species,
                "shown_move": shown,
                "truth_item": r.item,
                "truth_tera": r.tera_type if isinstance(r.tera_type, str) else None,
                "truth_hidden_moves": [x for x in moves if x != shown],
            }
        )
    return qs


SET_SYSTEM = (
    "You are an expert competitive Pokemon player in Smogon Gen 9 OU singles (October 2026). "
    "For each question, predict the most likely competitive set of the target Pokemon given "
    "its full team (seen at team preview) and one move it has already used. Answer in JSON."
)


def run_set_completion(client: LLMClient, qs: list[dict], batch: int = 10) -> list[dict]:
    answers = []
    for i in range(0, len(qs), batch):
        chunk = qs[i : i + batch]
        lines = [
            f"Q{j}: team = {', '.join(q['team'])}; target = {q['species']}; "
            f"already used move = {q['shown_move']}"
            for j, q in enumerate(chunk)
        ]
        user = (
            "\n".join(lines)
            + '\n\nReturn {"answers": [{"q": <index>, "items": [top 3 items, best first], '
            '"tera": [top 3 tera types], "moves": [its 4 most likely OTHER moves, best first]}]}'
            " using official English names."
        )
        out = client.chat_json(
            [{"role": "system", "content": SET_SYSTEM}, {"role": "user", "content": user}]
        )
        by_q = {int(a.get("q", -1)): a for a in out.get("answers", []) if isinstance(a, dict)}
        answers += [by_q.get(j, {}) for j in range(len(chunk))]
    return answers


def grade_set_completion(qs: list[dict], answers: list[dict]) -> dict:
    s = Counter()
    n_tera = n_moves = n_pred_moves = 0
    for q, a in zip(qs, answers, strict=True):
        items = [to_id(x) for x in a.get("items", [])][:3]
        tera = [to_id(x) for x in a.get("tera", [])][:3]
        moves = [to_id(x) for x in a.get("moves", [])][:4]
        s["item_top1"] += bool(items) and items[0] == to_id(q["truth_item"])
        s["item_top3"] += to_id(q["truth_item"]) in items
        if q["truth_tera"]:
            n_tera += 1
            s["tera_top1"] += bool(tera) and tera[0] == to_id(q["truth_tera"])
        hidden = {to_id(x) for x in q["truth_hidden_moves"]}
        s["move_hits"] += len(hidden & set(moves))
        n_moves += len(hidden)
        legal = _learnset(q["species"])
        for mv in moves:
            n_pred_moves += 1
            if mv not in MOVE_IDS:
                s["nonexistent_moves"] += 1
            elif legal is not None and mv not in legal:
                s["illegal_moves"] += 1
        s["answered"] += bool(a)
    n = len(qs)
    return {
        "item_top1": s["item_top1"] / n,
        "item_top3": s["item_top3"] / n,
        "tera_top1": s["tera_top1"] / max(n_tera, 1),
        "move_recall@4": s["move_hits"] / max(n_moves, 1),
        "bad_moves_rate": (s["illegal_moves"] + s["nonexistent_moves"]) / max(n_pred_moves, 1),
        "answered": s["answered"] / n,
    }


def baseline_set_completion(prior, qs: list[dict]) -> list[dict]:
    """Same answer format from a statistical prior (``alpha_poke.belief.priors``)."""
    out = []
    for q in qs:
        d = prior.predict(q["species"], tuple(q["team"]))
        shown = to_id(q["shown_move"])
        moves = [m for m in sorted(d.move, key=d.move.get, reverse=True) if m != shown][:4]
        out.append(
            {
                "items": sorted(d.item, key=d.item.get, reverse=True)[:3],
                "tera": sorted(d.tera, key=d.tera.get, reverse=True)[:3],
                "moves": moves,
            }
        )
    return out


# ---- type chart & speed ---------------------------------------------------------------------
def _types(species: str) -> list[str]:
    return GEN.pokedex[species_id(species)]["types"]


def build_type_chart(species_pool: list[str], n: int = 40, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    atk_types = list(GEN.type_chart)
    qs = []
    pool = [s for s in species_pool if species_id(s) in GEN.pokedex]
    for _ in range(n):
        sp = rng.choice(pool)
        atk = rng.choice(atk_types)
        mult = 1.0
        for t in _types(sp):
            mult *= GEN.type_chart[t.upper()][atk]
        qs.append({"attack": atk.title(), "defender": sp, "types": _types(sp), "truth": mult})
    return qs


def run_type_chart(client: LLMClient, qs: list[dict]) -> list:
    lines = [
        f"Q{i}: a {q['attack']}-type move hits {q['defender']} ({'/'.join(q['types'])})"
        for i, q in enumerate(qs)
    ]
    user = (
        "Give the type effectiveness multiplier (0, 0.25, 0.5, 1, 2 or 4) for each, ignoring "
        "abilities and items.\n" + "\n".join(lines) + '\nReturn {"answers": [multiplier, ...]}'
    )
    out = client.chat_json(
        [
            {"role": "system", "content": "You are a Pokemon mechanics expert. JSON only."},
            {"role": "user", "content": user},
        ]
    )
    return out.get("answers", [])


def build_speed(species_pool: list[str], n: int = 20, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    pool = [s for s in species_pool if species_id(s) in GEN.pokedex]
    qs = []
    while len(qs) < n:
        a, b = rng.sample(pool, 2)
        sa = GEN.pokedex[species_id(a)]["baseStats"]["spe"]
        sb = GEN.pokedex[species_id(b)]["baseStats"]["spe"]
        if sa != sb:
            qs.append({"a": a, "b": b, "truth": a if sa > sb else b})
    return qs


def run_speed(client: LLMClient, qs: list[dict]) -> list:
    lines = [f"Q{i}: {q['a']} vs {q['b']}" for i, q in enumerate(qs)]
    user = (
        "For each pair, which Pokemon has the higher BASE Speed stat?\n"
        + "\n".join(lines)
        + '\nReturn {"answers": [name, ...]}'
    )
    out = client.chat_json(
        [
            {"role": "system", "content": "You are a Pokemon mechanics expert. JSON only."},
            {"role": "user", "content": user},
        ]
    )
    return out.get("answers", [])


def grade_simple(qs, answers, key="truth") -> dict:
    ok = 0
    for i, q in enumerate(qs):
        a = answers[i] if i < len(answers) else None
        try:
            ok += (
                abs(float(a) - q[key]) < 1e-9
                if isinstance(q[key], float)
                else to_id(str(a)) == to_id(q[key])
            )
        except (TypeError, ValueError):
            pass
    return {"accuracy": ok / len(qs), "answered": min(len(answers), len(qs)) / len(qs)}


# ---- grounded naming ----------------------------------------------------------------------
NAMING_SYSTEM = (
    "You are an expert competitive Pokemon analyst for Smogon Gen 9 OU singles (6v6, team "
    "preview, terastallization). You are given DATA mined from thousands of high-rated ladder "
    "replays (October 2026). Rules:\n"
    "1. When describing the core's members (roles, game_plan, evidence), mention ONLY moves, "
    "items, abilities and tera types that appear in DATA for that member. If something is not "
    "in DATA, do not mention it.\n"
    "2. Weaknesses and advice may mention other Pokemon and general strategies.\n"
    "3. Use official English names exactly as written in DATA. Answer with one JSON object."
)

NAMING_SCHEMA = {
    "name": "short archetype name, e.g. 'Sun Offense'",
    "tags": "subset of: sun, rain, sand, snow, terrain, hyper_offense, bulky_offense, balance, "
    "stall, hazard_stack, sticky_web, trick_room, volturn, setup, screens",
    "game_plan": "2-4 sentences on how this core wins",
    "roles": "object: member -> role in a few words",
    "win_conditions": "list of members",
    "evidence": "object: member -> list of moves/items from DATA your description relies on",
    "weaknesses": "2-3 sentences",
    "how_to_play_against": "2-3 sentences",
}


def core_data_block(
    core: Core, sets: dict[str, SpeciesSets], mons: pd.DataFrame
) -> tuple[str, set]:
    """DATA text for a core + the set of move/item/ability/tera IDs it contains."""
    allowed: set[str] = set()
    lines = [
        f"Core members ({core.size}): {', '.join(core.members)}",
        f"Seen together in {core.support} teams.",
    ]
    if core.size == 6:  # a copied full team: use sets reconstructed within this exact team
        key = "|".join(sorted(core.members))
        d = mons[(mons.team == key) & mons.brought]
        lines.append("Sets reconstructed from replays of this exact team:")
        for sp in core.members:
            g = d[d.species == sp]
            items = g.item.value_counts(normalize=True).head(2)
            tera = g.tera_type.value_counts(normalize=True).head(2)
            abil = g.ability.value_counts(normalize=True).head(1)
            mv = Counter(x for v in g.moves for x in v.split("|") if x).most_common(5)
            parts = [
                "item " + ", ".join(f"{k} {v:.0%}" for k, v in items.items()),
                "ability " + ", ".join(abil.index),
                "tera " + ", ".join(f"{k} {v:.0%}" for k, v in tera.items()),
                "moves " + ", ".join(f"{k} {c / max(len(g), 1):.0%}" for k, c in mv),
            ]
            allowed |= {to_id(x) for x in list(items.index) + list(tera.index) + list(abil.index)}
            allowed |= {to_id(k) for k, _ in mv}
            lines.append(f"- {sp}: " + "; ".join(parts))
    else:
        lines.append("Set archetypes per member (share of that species' appearances):")
        for sp in core.members:
            ss = sets.get(sp)
            if ss is None:
                lines.append(f"- {sp}: (no data)")
                continue
            for a in ss.sets[:3]:
                lines.append(
                    f"- {sp} [{a.weight:.0%}]: item {', '.join(k for k, _ in a.item[:2])}; "
                    f"ability {', '.join(k for k, _ in a.ability[:1])}; "
                    f"tera {', '.join(k for k, _ in a.tera[:2])}; "
                    f"moves {', '.join(k for k, _ in a.moves[:6])}"
                )
                allowed |= {to_id(k) for k, _ in a.item[:2] + a.ability[:1] + a.tera[:2]}
                allowed |= {to_id(k) for k, _ in a.moves[:6]}
    return "\n".join(lines), allowed


WEATHER = {
    "Pelipper": "rain",
    "Ninetales": "sun",
    "Torkoal": "sun",
    "Tyranitar": "sand",
    "Hippowdon": "sand",
    "Ninetales-Alola": "snow",
    "Abomasnow": "snow",
}
STALL = {
    "Toxapex",
    "Dondozo",
    "Clodsire",
    "Blissey",
    "Corviknight",
    "Gliscor",
    "Skarmory",
    "Clefable",
    "Garganacl",
    "Alomomola",
    "Chansey",
    "Quagsire",
}


def clear_tags(core: Core, sets: dict[str, SpeciesSets]) -> set[str]:
    tags = {WEATHER[m] for m in core.members if m in WEATHER}
    for m in core.members:
        ss = sets.get(m)
        if ss and any(mv == "Sticky Web" and p >= 0.5 for a in ss.sets for mv, p in a.moves[:6]):
            tags.add("sticky_web")
    if len(STALL & set(core.members)) >= 4:
        tags.add("stall")
    return tags


def run_naming(client, cores, sets, mons) -> list[dict]:
    out = []
    vocab = set(MOVE_IDS) | {to_id(x) for x in mons.item.dropna().unique()}
    for core in cores:
        data, allowed = core_data_block(core, sets, mons)
        user = (
            "DATA:\n"
            + data
            + "\n\nReturn a JSON object with exactly these keys:\n"
            + json.dumps(NAMING_SCHEMA, indent=1)
        )
        rec = {"members": core.members, "clear_tags": sorted(clear_tags(core, sets))}
        try:
            ans = client.chat_json(
                [{"role": "system", "content": NAMING_SYSTEM}, {"role": "user", "content": user}]
            )
            rec["json_ok"] = True
        except (json.JSONDecodeError, KeyError, IndexError, ValueError):
            ans, rec["json_ok"] = {}, False
        described = " ".join(
            [str(ans.get("game_plan", ""))]
            + [str(v) for v in (ans.get("roles") or {}).values()]
            + [
                " ".join(map(str, v))
                for v in (ans.get("evidence") or {}).values()
                if isinstance(v, list)
            ]
        )
        mentioned = extract_mentions(described, vocab)
        rec["violations"] = sorted(mentioned - allowed)
        rec["n_mentions"] = len(mentioned)
        rec["answer"] = ans
        out.append(rec)
    return out


def grade_naming(recs: list[dict]) -> dict:
    tp = fp = fn = 0
    clear_vocab = {"rain", "sun", "sand", "snow", "sticky_web", "stall"}
    for r in recs:
        tags = r["answer"].get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        pred = {t for t in tags if t in clear_vocab}
        truth = set(r["clear_tags"])
        tp += len(pred & truth)
        fp += len(pred - truth)
        fn += len(truth - pred)
    mentions = sum(r["n_mentions"] for r in recs)
    viol = sum(len(r["violations"]) for r in recs)
    return {
        "json_ok": sum(r["json_ok"] for r in recs) / len(recs),
        "tag_precision": tp / max(tp + fp, 1),
        "tag_recall": tp / max(tp + fn, 1),
        "grounding_violations_per_core": viol / len(recs),
        "violation_rate": viol / max(mentions, 1),
    }
