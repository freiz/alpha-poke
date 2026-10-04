"""Team pool: loads Showdown-format team files and yields one at random per battle."""

import random
from pathlib import Path

from poke_env.teambuilder import Teambuilder

DEFAULT_TEAM_DIR = Path(__file__).resolve().parents[2] / "configs" / "teams"


def load_team_files(team_dir: Path | str = DEFAULT_TEAM_DIR) -> dict[str, str]:
    """Return {team name: packed team} for every ``*.txt`` file in ``team_dir``."""
    teams = {}
    for path in sorted(Path(team_dir).glob("*.txt")):
        mons = Teambuilder.parse_showdown_team(path.read_text().strip() + "\n\n")
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
