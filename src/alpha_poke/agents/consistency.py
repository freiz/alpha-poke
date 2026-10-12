"""The engine state against the server's request (2026-10-11): every option the request offers
must be one the engine state (side one) can play, or the search can choose only options that
have no order ("no order for the searched options": 232 in gen 5, from Revival Blessing's
choice -- the engine has no such step -- and poke-env's PP count drifting to 0). Checked before
each search; a mismatch is logged with what differs (the search still runs: options that do
map are fine)."""

from alpha_poke.analysis.roles import to_id

NOT_IN_ENGINE = {"struggle", "recharge"}  # request-only options the engine plays by itself


def request_mismatch(battle, state) -> list[str]:
    """What the request offers that ``state`` (a poke_engine.State, side one = us) cannot play."""
    s1 = state.side_one
    act_i = int(str(s1.active_index))
    act = s1.pokemon[act_i]
    out = []
    if battle.available_moves and not battle.force_switch:
        usable = {m.id for m in act.moves if m.pp > 0 and not m.disabled}
        for m in battle.available_moves:
            if m.id not in usable and m.id not in NOT_IN_ENGINE:
                out.append(f"move {m.id}: " + next(
                    (f"pp {x.pp}, disabled {x.disabled}" for x in act.moves if x.id == m.id),
                    "not in the engine's moveset"))  # fmt: skip
    if battle.available_switches:
        bench = {to_id(p.id) for i, p in enumerate(s1.pokemon) if i != act_i and p.hp > 0}
        for m in battle.available_switches:
            if to_id(m.species) not in bench:
                out.append(f"switch {m.species}: not a live benched mon in the engine")
    return out
