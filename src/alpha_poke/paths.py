"""Where the data lives (2026-10-28; README "Data"). One place for the paths the code reads and
writes; the scripts' defaults come from here.

  teams/                  tracked: the curated team data
    catalog.jsonl           the forum's complete teams (scripts/teams.py build)
    pools/<name>/           the fixed pools (ab600b, forum_curated, replay40, replay40b; wide200:
                            the A/B and Foul Play pairs; ladder_robust: the human-game teams)
  data/                   local (git-ignored)
    raw/                    downloaded, slow to redo
      metamon/ replays_hf/  replay datasets (scripts/fetch_metamon.py)
      replays/              the crawler's replays and index (scripts/crawl_replays.py)
      replays_sample/       a few replays for the parser's tests
      smogon/               usage statistics (scripts/fetch_smogon_stats.py)
      forum/                the forum crawl's cache (scripts/teams.py collect)
    derived/                rebuilt from raw by scripts
      parsed/               replay tables (analysis.tables, analysis.games_lite)
      belief/               the belief / reveal models
      teams/                generated pools (pools/<name>), team-design runs, random-battle teams
    train/ selfplay/        training data and runs; self-play generations (paths recorded in
                            state.json and the model registry: not moved)
    eval/ difftest/ public_games/ ladder/ players/ logs/ tmp/   run outputs
    archive/                ended experiments' leftovers
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEAMS = ROOT / "teams"
CATALOG = TEAMS / "catalog.jsonl"
TRACKED_POOLS = TEAMS / "pools"

DATA = ROOT / "data"
RAW = DATA / "raw"
METAMON = RAW / "metamon"
REPLAYS_HF = RAW / "replays_hf"
REPLAYS = RAW / "replays"
REPLAYS_SAMPLE = RAW / "replays_sample"
SMOGON = RAW / "smogon"
FORUM = RAW / "forum"

DERIVED = DATA / "derived"
PARSED = DERIVED / "parsed"
BELIEF = DERIVED / "belief"
TEAM_DATA = DERIVED / "teams"
POOLS = TEAM_DATA / "pools"

TRAIN = DATA / "train"
SELFPLAY = DATA / "selfplay"
EVAL = DATA / "eval"
DIFFTEST = DATA / "difftest"
PLAYERS = DATA / "players"


def pool(name: str) -> Path:
    """A pool by name: the tracked one (teams/pools) if there is one, else the generated
    (data/derived/teams/pools)."""
    tracked = TRACKED_POOLS / name
    return tracked if tracked.exists() else POOLS / name
