"""pokepast.es pastes ({"title", "author", "notes", "paste"}), cached under ``raw/pokepaste``."""

import json
import re

from alpha_poke.teams import RAW_DIR
from alpha_poke.teams.forum import Fetcher

CACHE = RAW_DIR / "pokepaste"


def fetch(f: Fetcher, paste_id: str) -> dict | None:
    """The paste, or None if it does not exist (any more)."""
    text = f.get(f"https://pokepast.es/{paste_id}/json", CACHE / f"{paste_id}.json")
    return json.loads(text) if text else None


def paste_format(paste: dict) -> str:
    """The format from the notes ("Format: gen9ou"), "" if not given."""
    m = re.search(r"Format:\s*(\S+)", paste.get("notes") or "")
    return m.group(1).lower() if m else ""


def load(paste_id: str) -> dict | None:
    """The cached paste (None if missing or not downloaded)."""
    path = CACHE / f"{paste_id}.json"
    text = path.read_text() if path.exists() else ""
    return json.loads(text) if text else None
