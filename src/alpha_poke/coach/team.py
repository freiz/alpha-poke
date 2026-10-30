"""The reviewed player's own team, pasted as Showdown exports it (the teambuilder's "Export") or
as a PokéPaste link (pokepast.es: its raw text): the whole of each set -- moves, item, ability,
tera type, nature, EVs, IVs -- so that the review rebuilds the player's side exactly instead of
sampling what the replay did not show (the player knew it: the search should too)."""

import re

from poke_env.data import GenData
from poke_env.teambuilder import Teambuilder

from alpha_poke.agents.engine_state import KnownSet
from alpha_poke.analysis.roles import to_id

GEN = GenData.from_gen(9)


class TeamError(ValueError):
    """A pasted team that cannot be the player's: ``code`` (the app's message key) and its
    details (``names``)."""

    def __init__(self, code: str, names: str = ""):
        super().__init__(f"{code}: {names}" if names else code)
        self.code, self.names = code, names


PASTE = re.compile(r"\s*(?:https?://)?(?:www\.)?pokepast\.es/([0-9a-f]+)\S*\s*", re.I)
PASTE_RAW = "https://pokepast.es/{}/raw"


def team_text(source: str) -> str:
    """The export text of ``source``: itself, or a PokéPaste link's (fetched once, no retries:
    the page waits for it; TeamError "team_fetch" when it cannot be had)."""
    m = PASTE.fullmatch(source)
    if m is None:
        return source
    import requests

    from alpha_poke.http import USER_AGENT

    try:
        r = requests.get(PASTE_RAW.format(m.group(1).lower()), timeout=15,
                         headers={"User-Agent": USER_AGENT})  # fmt: skip
        r.raise_for_status()
    except requests.RequestException as e:
        raise TeamError("team_fetch", str(e)) from None
    return r.text[:100_000]


def load_team(source: str) -> dict[str, KnownSet]:
    """parse_team of an export or a PokéPaste link."""
    return parse_team(team_text(source))


def parse_team(text: str) -> dict[str, KnownSet]:
    """Species id -> its whole set, from a Showdown export (nicknames allowed)."""
    # (poke-env's parser: a CRLF line end breaks it -- "spe\r" no stat, or the stat read wrong --
    # and PokéPaste's lines end in two spaces; 2026-10-30)
    text = "\n".join(
        line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )
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
            # (no "EVs:" / "IVs:" line: none / all 31 -- the export leaves out the defaults)
            evs=tuple(int(x) for x in m.evs) if m.evs else (0,) * 6,
            ivs=tuple(int(x) for x in m.ivs) if m.ivs else (31,) * 6,
            exact=True,
        )
    if not out:
        raise TeamError("team_unreadable")
    return out


def _same(a: str, b: str) -> bool:
    """One species, one written as its base (a preview's "Urshifu-*": "urshifu")."""
    return a == b or a.startswith(b) or b.startswith(a)


def match_team(team: dict[str, KnownSet], records, log: str | None = None,
               side: str | None = None) -> dict[str, KnownSet]:  # fmt: skip
    """``team`` keyed for the replay's player (``records``: its mons as the replay shows them,
    replay.parse_replay's): every one of them in the team, with every move it used, and -- with
    the game's ``log`` and the player's ``side`` -- the tera type, item and ability the game
    showed as its own (else TeamError "team_mismatch" naming what does not fit). Keyed by the
    record's species and the team's own (a preview's "Urshifu-*" is "urshifurapidstrike" once
    in). Cautious, as a wrong refusal costs more than a missed one: an ability only when it is one
    of the species' own (not a forme's change -- Ogerpon's Embody Aspect -- nor a copied one), an
    item not on a side whose items changed hands (Trick, Thief, Magician, ...)."""
    swapped = side is not None and log is not None and any(
        f[1] == "-item" and f[2].startswith(side) and any(x.startswith(("[from] move:", "[from] ability:"))
                                                       and "Frisk" not in x for x in f[4:])
        for f in (line.split("|") for line in log.split("\n")) if len(f) > 3
    )  # fmt: skip
    out, missing = {}, []
    for rec in records:
        name = rec.species.replace("-*", "")
        sid = to_id(name)
        key = next((k for k in team if _same(k, sid)), None)
        if key is None:
            missing.append(name)
            continue
        k = team[key]
        moves = set(k.moves)
        odd = [m for m in rec.moves if to_id(m) not in moves and to_id(m) != "struggle"]
        if log is not None:
            if rec.tera_type and k.tera and to_id(rec.tera_type) != to_id(k.tera):
                odd.append(f"Tera {rec.tera_type}")
            if rec.item and not swapped and to_id(rec.item) != (k.item or ""):
                odd.append(rec.item)
            own = {to_id(x) for x in (GEN.pokedex.get(key) or {}).get("abilities", {}).values()}
            if (
                rec.ability
                and k.ability
                and to_id(rec.ability) in own
                and to_id(rec.ability) != k.ability
            ):
                odd.append(rec.ability)
        if odd:
            missing.append(f"{name}: {', '.join(odd)}")
        out[to_id(rec.species)] = out[key] = team[key]
    if missing:
        raise TeamError("team_mismatch", "; ".join(missing))
    return out
