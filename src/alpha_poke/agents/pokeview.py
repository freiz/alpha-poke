"""A mon's values as poke-env tracks them, read in one place (doc/state-diff.md plan C). poke-env
mixes a mon's own values with its current ones: while it is transformed its ``moves``,
``base_stats`` and ``weight`` are its target's, its ``ability`` is a temporary one while it has
one (Trace, Skill Swap, a Transform). Reading the wrong one was a recurring construction error
(2026-10-23 review: a Ditto's set sampled with its copied moves, its backup's HP from its
target's base stats, its weight its target's). Each function here says which it reads:
``own_*`` -- the mon's own (its set's), ``current_*`` -- what it has now in the battle.
``agents/engine_state.py`` reads poke-env mons only through these (tests/test_pokeview.py)."""

from poke_env.data import GenData

from alpha_poke.analysis.roles import to_id

GEN = GenData.from_gen(9)


def own_moves(mon) -> dict:
    """A mon's own moves: poke-env's ``moves`` are the copied ones while it is transformed (its
    own set then is its base moves; 2026-10-23 review: a Ditto's set sampled with the copied
    moves -- Transform and Kowtow Cleave in one set)."""
    ms = mon._moves
    return ms._base_moves if ms._transform_moves is not None else mon.moves


def current_moves(mon) -> dict:
    """The moves a mon has now: a transformed one's copied ones (poke-env's ``moves``; their
    uses counted on the copies)."""
    return mon.moves


def last_used_move(mon) -> str:
    """The id of the move poke-env marks as the mon's last used, "" if none."""
    return next((mid for mid, mv in mon.moves.items() if mv.is_last_used), "")


def own_weight(mon) -> float:
    """A mon's own weight, its species' (poke-env's is its target's while it is transformed:
    the backup's weight, 2026-10-23 review -- and after: its switch-out does not restore it, a
    Ditto out of its Copperajah transform read 650 kg; 2026-10-24 review)."""
    entry = GEN.pokedex.get(to_id(mon.species))
    if entry and entry.get("weightkg"):
        return float(entry["weightkg"])
    return float(mon.weight or 0.0)


def own_base_stats(mon) -> dict:
    """A mon's own base stats (poke-env's ``base_stats`` are its target's while it is
    transformed: 2026-10-23 review -- a Ditto's HP 403, Showdown 300; its backup's Attack its
    target's)."""
    return getattr(mon, "_base_stats", None) or mon.base_stats


def own_stats(mon) -> dict:
    """Our mon's own stats, as the request gives them (a transformed one's too: the copied ones
    are not in it)."""
    return mon.stats or {}


def own_ability(mon) -> str | None:
    """A mon's own ability as poke-env knows it (its set's; a forme change's new one -- Zero to
    Hero, Tera Shift), None if unknown; not a temporary one."""
    return to_id(mon.base_ability) if mon.base_ability else None


def current_ability(mon) -> str:
    """The ability a mon has now as poke-env knows it (a temporary one -- Trace's, a Skill
    Swap's, a Transform's -- else its own), "" if unknown."""
    return to_id(mon.ability) if mon.ability else ""


def engine_ability(mon, own: str) -> str:
    """The engine's ability of a mon whose own (its set's) is ``own``: a temporary one -- Trace's,
    a Skill Swap's, a Transform's -- if it has one (poke-env's temporary_ability; gone when it
    switches out), else its own."""
    t = getattr(mon, "temporary_ability", None)
    # (As One announces itself and the ability it holds -- Unnerve, Chilling / Grim Neigh: the set's
    # As One, a Ditto's copied one too; S121)
    if t and own.startswith("asone") and to_id(t) in ("asone", "unnerve", "chillingneigh", "grimneigh"):
        return own
    return to_id(t) if t else own


def copied_ability(mon, target: str) -> str:
    """A transformed mon's copied ability: poke-env's temporary one -- unless poke-env never knew
    its target's and kept the Imposter it came by (a replay's own side: no request; S144), the
    target's in this world."""
    t = getattr(mon, "temporary_ability", None)
    return target if t and to_id(t) == "imposter" else engine_ability(mon, target)


def copied_pp(mon, mid: str) -> int:
    """The PP left of a move ``mon`` copied by transforming (poke-env counts its uses: 5 PP at
    most; 2026-10-23 review: always 5, a Scarf Ditto's fifth Protect left it at 5)."""
    mv = mon.moves.get(mid) if mon is not None and mon.transformed else None
    return max(0, mv.current_pp) if mv is not None else 5
