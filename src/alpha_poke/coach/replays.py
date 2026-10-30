"""Replays for review: a dict like the replay datasets' rows (``id``, ``log``, ``players``,
``rating``, ``uploadtime``) from

  * our saved battles (data/public_games/<date>/replays/*.html: the log in the page),
  * a Showdown replay's JSON (a file, or downloaded by id / URL from replay.pokemonshowdown.com),
  * a plain log file (the |...| protocol lines).
"""

import html
import json
import re
from pathlib import Path

from alpha_poke.analysis.roles import to_id

REPLAY_URL = "https://replay.pokemonshowdown.com/{}.json"
_ID = re.compile(r"(?:replay\.pokemonshowdown\.com/)?([a-z0-9]+-\d+(?:-[a-z0-9]+)?)", re.I)


def _row(rid: str, log: str, rating=None, uploadtime=0) -> dict:
    players = ["", ""]
    for line in log.split("\n"):
        f = line.split("|")
        if len(f) > 3 and f[1] == "player" and f[2] in ("p1", "p2") and f[3]:
            players[int(f[2][1]) - 1] = players[int(f[2][1]) - 1] or f[3]
    return {"id": rid, "log": log, "players": players, "rating": rating, "uploadtime": uploadtime,
            "format": "", "formatid": rid.split("-")[0]}  # fmt: skip


def from_html(path: Path) -> dict:
    text = Path(path).read_text()
    m = re.search(r'class="battle-log-data">(.*?)</script>', text, re.S)
    if m is None:
        raise ValueError(f"{path}: no battle log in the page")
    rid = re.search(r"battle-(gen\d+[a-z0-9]+-\d+)", Path(path).name)
    return _row(rid.group(1) if rid else Path(path).stem, html.unescape(m.group(1)))


def from_json(data: dict) -> dict:
    return _row(data["id"], data["log"], data.get("rating"), data.get("uploadtime") or 0)


def load(source: str) -> dict:
    """A replay from a file path (.html / .json / a log) or a Showdown replay id / URL."""
    path = Path(source)
    if path.is_dir():
        raise ValueError(f"{source}: a directory, not a replay")
    if path.exists():
        if path.suffix == ".html":
            return from_html(path)
        text = path.read_text()
        if text.lstrip().startswith("{"):
            return from_json(json.loads(text))
        return _row(path.stem, text)
    m = _ID.search(source)
    if m is None:
        raise ValueError(f"{source}: not a file, replay id or replay URL")
    from alpha_poke.http import PoliteClient

    return from_json(PoliteClient().get(REPLAY_URL.format(m.group(1))).json())


def side_of(row: dict, player: str) -> str:
    """The side ('p1' / 'p2') a player had in the replay."""
    for side, name in zip(("p1", "p2"), row["players"], strict=True):
        if name and to_id(name) == to_id(player):
            return side
    raise ValueError(f"{player!r} is not a player of {row['id']} ({row['players']})")
