"""Gen 9 dex helpers (poke-env's data): move ids and learnsets."""

from poke_env.data import GenData

from alpha_poke.analysis.roles import to_id

GEN = GenData.from_gen(9)
MOVE_IDS = {k: v["name"] for k, v in GEN.moves.items()}


def species_id(name: str) -> str:
    return to_id(name.replace("-*", ""))


def learnset(species: str) -> set[str] | None:
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
