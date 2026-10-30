"""The frozen app's smoke test (.github/workflows/desktop-app.yml, Windows and macOS): it answers on 8090, takes a
fixture replay (anonymized, tests/fixtures), reviews it at the fast strength and serves the page."""

import gzip
import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8090"
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "replays_gen9ou.jsonl.gz"


def main() -> int:
    for _ in range(120):  # (the first start unpacks and copies the assets)
        try:
            if requests.get(BASE + "/", timeout=2).ok:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        print("the app did not start")
        return 1
    rows = [json.loads(x) for x in gzip.decompress(FIXTURE.read_bytes()).decode().splitlines()]
    row = next(r for r in rows if 8 <= r["log"].count("|turn|") <= 15)
    upload = {"upload": {"name": "game.json", "text": json.dumps(row)}}
    players = requests.post(BASE + "/api/players", json=upload, timeout=60).json()
    print("players:", players)
    job = requests.post(BASE + "/api/review", json=upload | {"player": "Player A", "strength": "fast"},
                        timeout=60).json()["job"]  # fmt: skip
    for _ in range(600):
        j = requests.get(f"{BASE}/api/job/{job}", timeout=5).json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(1)
    print("job:", j)
    if j["status"] != "done":
        return 1
    page = requests.get(BASE + j["url"], timeout=10)
    print("page:", page.status_code, len(page.text))
    return 0 if page.ok and '"decisions"' in page.text else 1


if __name__ == "__main__":
    sys.exit(main())
