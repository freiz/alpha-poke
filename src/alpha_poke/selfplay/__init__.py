"""Self-play (design D15): team sampling (``teams``), the game runner, recording of the
search results, conversion to training data. Data under ``data/selfplay/gen<g>/``."""

from pathlib import Path

SELFPLAY_DIR = Path(__file__).resolve().parents[3] / "data" / "selfplay"
