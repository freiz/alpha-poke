"""Teams: every complete team we have, where it came from, and the pools built from them
(design D5-T). The CLI is ``scripts/teams.py``.

Data layout (``data/teams``):
  raw/smogon/<thread id>/page-<n>.html  forum pages as downloaded (cache, untrusted)
  raw/pokepaste/<paste id>.json         pokepast.es pastes as downloaded (cache, untrusted)
  raw/links.jsonl                       where each team was found: one row per (post, team)
  catalog.jsonl                         all complete teams, canonical, deduplicated, validated
                                        (``catalog.Entry``); built from raw/ by ``teams.py build``
  pools/<name>/team_XX.txt + index.json fixed pools for evaluation (``index.json``: file stem
                                        -> preview team key, used for the heldout belief model)

Modules: ``validate`` (Showdown canonical export + validator), ``forum`` (Smogon forum
crawler), ``pokepaste``, ``catalog`` (the catalog and pool export), ``replay_pool`` (pools
reconstructed from replays).
"""

import random
from pathlib import Path

from poke_env.teambuilder import Teambuilder

ROOT = Path(__file__).resolve().parents[3]
TEAMS_DIR = ROOT / "data" / "teams"
RAW_DIR = TEAMS_DIR / "raw"
CATALOG = TEAMS_DIR / "catalog.jsonl"
POOLS_DIR = TEAMS_DIR / "pools"
# the evaluation pool: 40 teams reconstructed from replays (2026-10)
DEFAULT_POOL = POOLS_DIR / "replay40"
DEFAULT_TEAM_DIR = ROOT / "configs" / "teams"


def load_team_files(team_dir: Path | str = DEFAULT_TEAM_DIR) -> dict[str, str]:
    """Return {team name: packed team} for every ``*.txt`` file in ``team_dir``."""
    teams = {}
    for path in sorted(Path(team_dir).glob("*.txt")):
        # lines stripped: an export's lines end in two spaces, and on a set line without an item
        # poke-env keeps them in the nickname; a long species name ("Vivillon-Pokeball  ") then
        # exceeds 18 characters, the server rejects the team and the game never starts
        # (2026-10-09: two pairs of the offmeta200 pool hung every time)
        text = "\n".join(line.rstrip() for line in path.read_text().strip().splitlines())
        mons = Teambuilder.parse_showdown_team(text + "\n\n")
        teams[path.stem] = Teambuilder.join_team(mons)
    if not teams:
        raise FileNotFoundError(f"no team files found in {team_dir}")
    return teams


class TeamPool(Teambuilder):
    """Teambuilder that samples uniformly from a fixed pool of human-built teams."""

    def __init__(self, teams: dict[str, str] | None = None, seed: int | None = None):
        self.teams = teams if teams is not None else load_team_files()
        self._names = list(self.teams)
        self._rng = random.Random(seed)

    def yield_team(self) -> str:
        return self.teams[self._rng.choice(self._names)]
