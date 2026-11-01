"""Self-play on a shared computer (2026-10-31): start it, pause it whenever the computer is wanted
(games with people, the GPU for something else), resume it later -- one generation grown by
`selfplay.py iterate` in batches of --chunk games (150,000: the games first, the training and the
promotion test only when a batch is complete).

  uv run python scripts/selfplay_ctl.py start [--gen 1] [--chunk 150000] [--max-games 300000]
  uv run python scripts/selfplay_ctl.py pause      # stops now: CPU and GPU free
  uv run python scripts/selfplay_ctl.py resume     # where it stopped
  uv run python scripts/selfplay_ctl.py status

Pausing loses only the step in progress: the games being played (every finished game is kept,
`run` plays only the missing ones), or a conversion / training / test, which start again on
resume (pause in the middle of a 2.5-hour conversion and it restarts). The control file
data/selfplay/ctl.json keeps the generation, the batch and the running process group.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from alpha_poke.selfplay import SELFPLAY_DIR

CTL = SELFPLAY_DIR / "ctl.json"
ROOT = Path(__file__).resolve().parents[1]
COST = {"teams": "the teams being drawn (minutes)", "run": "the games in progress (minutes of play)",
        "convert": "the conversion so far (it takes ~2.5 h)", "train": "the training so far (~30 min)",
        "eval": "the promotion test so far"}  # fmt: skip


def read() -> dict:
    return json.loads(CTL.read_text()) if CTL.exists() else {}


def write(d: dict) -> None:
    CTL.write_text(json.dumps(d, indent=1))


def alive(pgid: int | None) -> bool:
    if not pgid:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def step_now(gen: int) -> str | None:
    """The step iterate is in (its last "gen G: <step>" line)."""
    out = SELFPLAY_DIR / f"gen{gen}" / "iterate.out"
    if not out.exists():
        return None
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if f"gen {gen}: " in ln]
    return lines[-1].split(f"gen {gen}: ")[-1].strip() if lines else None


def games(gen: int) -> int:
    from alpha_poke.selfplay import runner

    return len(runner.done_pairs(SELFPLAY_DIR / f"gen{gen}"))


def start(d: dict) -> None:
    if alive(d.get("pgid")):
        print(f"already running (process group {d['pgid']})")
        return
    gen_dir = SELFPLAY_DIR / f"gen{d['gen']}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "scripts" / "selfplay.py"), "iterate", "--gen", str(d["gen"]),
           "--chunk", str(d["chunk"]), "--max-games", str(d["max_games"])]  # fmt: skip
    with open(gen_dir / "iterate.out", "a", encoding="utf-8") as f:
        f.write(f"--- start {time.strftime('%m-%d %H:%M:%S')}\n")
        f.flush()
        # (its own process group: pause stops iterate and every step it started at once)
        p = subprocess.Popen(
            cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, start_new_session=True
        )
    d |= {
        "pgid": p.pid,
        "state": "running",
        "since": time.strftime("%m-%d %H:%M"),
        "games_at_start": games(d["gen"]),
    }
    write(d)
    print(f"gen {d['gen']}: running (process group {p.pid}), {d['games_at_start']} games so far, "
          f"batches of {d['chunk']}")  # fmt: skip


def pause(d: dict) -> None:
    pg = d.get("pgid")
    if not alive(pg):
        print("not running")
        d["state"] = "paused"
        write(d)
        return
    step = step_now(d["gen"])
    os.killpg(pg, signal.SIGTERM)
    for _ in range(40):
        if not alive(pg):
            break
        time.sleep(0.5)
    if alive(pg):
        os.killpg(pg, signal.SIGKILL)
    d |= {
        "state": "paused",
        "pgid": None,
        "paused_at": time.strftime("%m-%d %H:%M"),
        "paused_in": step,
    }
    write(d)
    print(f"paused in '{step}': lost {COST.get(step or '', 'nothing')}; {games(d['gen'])} games kept. "
          "resume continues from here")  # fmt: skip


def status(d: dict) -> None:
    if not d:
        print("never started (selfplay_ctl.py start)")
        return
    run = alive(d.get("pgid"))
    n = games(d["gen"])
    target = (n // d["chunk"] + 1) * d["chunk"]
    line = f"gen {d['gen']}: {'running' if run else 'paused'}"
    line += (
        f", step '{step_now(d['gen'])}'"
        if run
        else f" (since {d.get('paused_at')}, in '{d.get('paused_in')}')"
    )
    line += f"; {n} games, the batch trains at {target}"
    if run and d.get("since"):
        try:
            t0 = time.mktime(
                time.strptime(f"{time.localtime().tm_year}-{d['since']}", "%Y-%m-%d %H:%M")
            )
            rate = (n - d.get("games_at_start", n)) / max((time.time() - t0) / 3600, 1e-6)
            line += f"; {rate:.0f} games/hour since started"
        except ValueError:
            pass
    print(line)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "pause", "resume", "status"])
    ap.add_argument("--gen", type=int, default=None)
    ap.add_argument("--chunk", type=int, default=150000)
    ap.add_argument("--max-games", type=int, default=300000)
    a = ap.parse_args()
    d = read()
    if a.cmd == "start":
        d = d | {
            "gen": a.gen if a.gen is not None else d.get("gen", 1),
            "chunk": a.chunk,
            "max_games": a.max_games,
        }
        start(d)
    elif a.cmd == "resume":
        if not d:
            sys.exit("never started (selfplay_ctl.py start)")
        start(d)
    elif a.cmd == "pause":
        pause(d)
    else:
        status(d)


if __name__ == "__main__":
    main()
