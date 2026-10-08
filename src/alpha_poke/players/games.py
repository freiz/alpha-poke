"""A player's games: their public replays (Showdown replay search, cached by ReplayClient),
parsed into what they brought, revealed and how the game went."""

import json
from dataclasses import dataclass, field

from alpha_poke.analysis.roles import to_id
from alpha_poke.players import PLAYERS_DIR
from alpha_poke.replay.fetch import BASE, ReplayClient
from alpha_poke.replay.parser import parse_replay


@dataclass
class Game:
    id: str
    time: int  # upload time (unix seconds)
    side: str  # the player's side, 'p1' / 'p2'
    won: bool
    rating: int  # the player's ladder rating before the game (0 = unknown)
    opp_rating: int
    team: list[str]  # species as in team preview
    lead: str
    # species -> {"item", "ability", "tera"} (revealed values) and "moves" (revealed moves)
    sets: dict[str, dict] = field(default_factory=dict)
    replay: dict = field(default_factory=dict, repr=False)

    @property
    def key(self) -> str:
        return "|".join(sorted(self.team))


def fetch(user: str, client: ReplayClient | None = None, max_pages: int = 40) -> list[dict]:
    """Search every public replay of ``user`` (all formats, newest first) and download them
    (cached); the search result is saved to data/players/<user id>/search.json."""
    client = client or ReplayClient()
    uid = to_id(user)
    out, before = [], None
    for _ in range(max_pages):
        params = {"user": uid} | ({"before": before} if before else {})
        page = client.http.get(f"{BASE}/search.json", params).json()
        out += page
        if len(page) < 51:
            break
        before = page[-1]["uploadtime"]
    d = PLAYERS_DIR / uid
    d.mkdir(parents=True, exist_ok=True)
    (d / "search.json").write_text(json.dumps(out))
    for r in out:
        client.get(r["id"])
    return out


def _rating(log: str, side: str) -> int:
    for line in log.split("\n"):
        f = line.split("|")
        if len(f) > 5 and f[1] == "player" and f[2] == side and f[5].isdigit():
            return int(f[5])
    return 0


def load(user: str, fmt: str = "gen9ou", client: ReplayClient | None = None) -> list[Game]:
    """The player's games in ``fmt`` from the cache (``fetch`` first), oldest first."""
    client = client or ReplayClient()
    uid = to_id(user)
    search = json.loads((PLAYERS_DIR / uid / "search.json").read_text())
    games = []
    for meta in search:
        if meta["id"].rsplit("-", 1)[0] != fmt:
            continue
        d = client.load_cached(meta["id"])
        if d is None:
            continue
        side = next((f"p{i + 1}" for i, p in enumerate(d["players"]) if to_id(p) == uid), None)
        rep = parse_replay(d)
        if side is None or rep.winner not in ("p1", "p2"):
            continue
        opp = "p2" if side == "p1" else "p1"
        team = [m for m in rep.teams[side] if not m.phantom]
        sets = {
            m.species: {"item": m.item, "ability": m.ability, "tera": m.tera_type,
                        "moves": list(m.moves)}
            for m in team
        }  # fmt: skip
        lead = next((a.to for a in rep.actions if a.kind == "lead" and a.side == side), "")
        games.append(Game(
            id=meta["id"], time=meta["uploadtime"], side=side, won=rep.winner == side,
            rating=_rating(d["log"], side), opp_rating=_rating(d["log"], opp),
            team=[m.species for m in team], lead=lead, sets=sets, replay=d,
        ))  # fmt: skip
    return sorted(games, key=lambda g: g.time)
