"""The reviewed player's own team, pasted as Showdown exports it (the teambuilder's "Export"):
the whole of each set -- moves, item, ability, tera type, nature, EVs, IVs -- so that the review
rebuilds the player's side exactly instead of sampling what the replay did not show (the player
knew it: the search should too)."""

from poke_env.teambuilder import Teambuilder

from alpha_poke.agents.engine_state import KnownSet
from alpha_poke.analysis.roles import to_id


class TeamError(ValueError):
    """A pasted team that cannot be the player's: ``code`` (the app's message key) and its
    details (``names``)."""

    def __init__(self, code: str, names: str = ""):
        super().__init__(f"{code}: {names}" if names else code)
        self.code, self.names = code, names


def parse_team(text: str) -> dict[str, KnownSet]:
    """Species id -> its whole set, from a Showdown export (nicknames allowed)."""
    try:
        mons = Teambuilder.parse_showdown_team(text)
    except Exception as e:  # (poke-env raises on a malformed line)
        raise TeamError("team_unreadable", str(e)) from None
    out = {}
    for m in mons:
        species = m.species or m.nickname
        if not species:
            continue
        out[to_id(species)] = KnownSet(
            moves=[to_id(x) for x in m.moves if x],
            item=to_id(m.item) if m.item else None,
            ability=to_id(m.ability) if m.ability else None,
            tera=m.tera_type.lower() if m.tera_type else None,
            nature=(m.nature or "serious").lower(),
            evs=tuple(int(x) for x in m.evs),
            ivs=tuple(int(x) for x in m.ivs),
        )
    if not out:
        raise TeamError("team_unreadable")
    return out


def _same(a: str, b: str) -> bool:
    """One species, one written as its base (a preview's "Urshifu-*": "urshifu")."""
    return a == b or a.startswith(b) or b.startswith(a)


def match_team(team: dict[str, KnownSet], records) -> dict[str, KnownSet]:
    """``team`` keyed for the replay's player (``records``: its mons as the replay shows them,
    replay.parse_replay's): every one of them in the team, with every move it used (else
    TeamError "team_mismatch" naming what does not fit). Keyed by the record's species and the
    team's own (a preview's "Urshifu-*" is "urshifurapidstrike" once in)."""
    out, missing = {}, []
    for rec in records:
        sid = to_id(rec.species.replace("-*", ""))
        key = next((k for k in team if _same(k, sid)), None)
        if key is None:
            missing.append(rec.species.replace("-*", ""))
            continue
        moves = set(team[key].moves)
        odd = [m for m in rec.moves if to_id(m) not in moves and to_id(m) != "struggle"]
        if odd:
            missing.append(f"{rec.species.replace('-*', '')}: {', '.join(odd)}")
        out[to_id(rec.species)] = out[key] = team[key]
    if missing:
        raise TeamError("team_mismatch", "; ".join(missing))
    return out
