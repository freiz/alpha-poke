"""One vocabulary for actions (doc/state-diff.md plan C). An action's name -- the engine's option
name, as ``alpha_search.slot_names`` gives a state's: "earthquake", "earthquake-tera",
"switch greattusk", "struggle" -- is what passes between the network's action slots, the
search's labels and the battle's orders. The slots themselves are computed in one place only,
the Rust crate (``features::slot`` / ``slot_in``): this module looks them up by name, it never
recomputes them (training's positions did: a move's index + 4 for its tera, 8 + a team index for
a switch -- the same layout written twice)."""

import alpha_search

from alpha_poke.analysis.roles import to_id


def names(state) -> list[str]:
    """``state``'s (a ``poke_engine.State`` or its string) action slots, side one's: each slot's
    option name, "" for a slot that is not an option."""
    return alpha_search.slot_names([state if isinstance(state, str) else state.to_string()])[0]


def move_name(move: str, tera: bool = False) -> str:
    """A move's option name ("Earthquake" -> "earthquake"; "earthquake-tera" with its tera)."""
    mid = to_id(move)
    return f"{mid}-tera" if tera else mid


def switch_name(species: str) -> str:
    """A switch's option name by the target's engine species id ("switch greattusk")."""
    return f"switch {to_id(species)}"


def slot_of(slot_names: list[str], name: str) -> int | None:
    """The slot of the option ``name`` among a state's ``names``; None when it is not one."""
    return slot_names.index(name) if name and name in slot_names else None


def order_of(player, battle, name: str):
    """An option name -> the battle's order (poke-env's ``create_order``), or None when the
    battle offers no such action."""
    if name.startswith("switch "):
        sp = name.split(" ", 1)[1]
        for m in battle.available_switches:
            if m.species == sp:
                return player.create_order(m)
        # (the engine names a mon by its forme of the moment, poke-env by the log's details --
        # Greninja-Bond is "Greninja" there: one forme's name the other's prefix, unique in a
        # team by the species clause; 2026-10-24, plan C's round trip: no order, the search's
        # switch to it lost)
        near = [m for m in battle.available_switches
                if sp.startswith(to_id(m.species)) or to_id(m.species).startswith(sp)]  # fmt: skip
        return player.create_order(near[0]) if len(near) == 1 else None
    tera = name.endswith("-tera")
    mid = name[: -len("-tera")] if tera else name
    for mv in battle.available_moves:
        if mv.id == mid:
            return player.create_order(mv, terastallize=tera and battle.can_tera)
    if len(battle.available_moves) == 1:  # recharge / struggle / locked move
        return player.create_order(battle.available_moves[0])
    return None
