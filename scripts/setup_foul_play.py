"""Install Foul Play (GPL-3.0) as an external, separate-process opponent for local evaluation.

  uv run python scripts/setup_foul_play.py install   # clone (pinned), own venv, build engine
  uv run python scripts/setup_foul_play.py patch     # local-login + offline patches
  uv run python scripts/setup_foul_play.py cache     # ONE-TIME data download / cache warm-up

Everything lives in external/foul-play (git-ignored). Foul Play code is never imported by
alpha_poke; it runs as its own process and connects to our LOCAL Showdown server only.

Patches (minimal, idempotent):
  * login: on a ws://localhost / 127.0.0.1 server send "/trn <name>,0," instead of fetching an
    assertion from play.pokemonshowdown.com (same as poke-env does for local servers);
  * offline guard: with FP_OFFLINE=1 a missing data cache raises instead of downloading, so a
    battle can never trigger network access.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FP = ROOT / "external" / "foul-play"
COMMIT = "8f541f8"
VENV_PY = FP / ".venv" / "bin" / "python"
FORMAT = "gen9ou"


def sh(*cmd, cwd=None):
    print("+", " ".join(map(str, cmd)))
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def install():
    if not FP.exists():
        sh("git", "clone", "https://github.com/pmariglia/foul-play", FP)
    sh("git", "checkout", "-q", COMMIT, cwd=FP)
    if not VENV_PY.exists():
        sh("uv", "venv", "--python", "3.13", FP / ".venv")
    sh(
        "uv",
        "pip",
        "install",
        "-p",
        FP / ".venv",
        "poke-engine==0.0.48",
        "-C",
        "build-args=--features poke-engine/terastallization --no-default-features",
    )
    sh(
        "uv",
        "pip",
        "install",
        "-p",
        FP / ".venv",
        "requests==2.33.0",
        "websockets==14.1",
        "python-dateutil==2.8.0",
    )


def _patch(path: Path, anchor: str, insert: str, marker: str):
    text = path.read_text()
    if marker in text:
        print(f"already patched: {path.relative_to(FP)}")
        return
    assert anchor in text, f"anchor not found in {path}: {anchor!r}"
    path.write_text(text.replace(anchor, anchor + insert, 1))
    print(f"patched: {path.relative_to(FP)}")


def patch():
    _patch(
        FP / "fp" / "websocket_client.py",
        "        client_id, challstr = await self.get_id_and_challstr()\n",
        "        # alpha-poke patch: local no-security server, no assertion from the public site\n"
        "        if self.address.startswith(('ws://localhost', 'ws://127.0.0.1')):\n"
        "            await self.send_message('', ['/trn ' + self.username + ',0,'])\n"
        "            await asyncio.sleep(1)\n"
        "            logger.info('Logged in to the local server (alpha-poke patch)')\n"
        "            return self.username\n",
        "alpha-poke patch: local no-security server",
    )
    guard = (
        "    if os.environ.get('FP_OFFLINE') == '1':  # alpha-poke patch: never download\n"
        "        raise RuntimeError(f'FP_OFFLINE: missing cache {cache_path}')\n"
    )
    _patch(
        FP / "fp" / "data" / "sets" / "base.py",
        "def get_sets_file(cache_path: str, remote_url: str) -> dict:\n"
        "    if os.path.exists(cache_path):\n"
        '        with open(cache_path, "r") as f:\n'
        "            sets = json.load(f)\n"
        '        logger.info(f"Loaded from cache: {cache_path}")\n'
        "        return sets\n",
        "\n" + guard,
        "alpha-poke patch: never download",
    )
    smog = FP / "fp" / "data" / "sets" / "smogon.py"
    text = smog.read_text()
    if "alpha-poke patch: never download" in text:
        print("already patched: fp/data/sets/smogon.py")
    else:  # the guard sits inside an else-branch here, so it needs deeper indentation
        anchor = "        else:\n            r = requests.get(smogon_stats_url)\n"
        repl = (
            "        else:\n"
            "            if os.environ.get('FP_OFFLINE') == '1':"
            "  # alpha-poke patch: never download\n"
            "                raise RuntimeError(f'FP_OFFLINE: missing cache {cache_file}')\n"
            "            r = requests.get(smogon_stats_url)\n"
        )
        assert anchor in text
        smog.write_text(text.replace(anchor, repl, 1))
        print("patched: fp/data/sets/smogon.py")


def cache():
    """One-time warm-up. Smogon stats come from our own download (data/smogon/); the other
    two files are fetched once from their public static URLs."""
    import requests

    sets_dir = FP / "fp" / "data" / "pkmn_sets_cache" / FORMAT
    sets_dir.mkdir(parents=True, exist_ok=True)
    for name in ("pokemon_full_sets.json", "replay_moves.json"):
        path = sets_dir / name
        if not path.exists():
            r = requests.get(f"https://data.foulplay.cc/{FORMAT}/{name}", timeout=60)
            r.raise_for_status()
            path.write_text(r.text)
        print(f"cached {path.relative_to(FP)} ({path.stat().st_size // 1024} KB)")
    ps = sets_dir / "showdown_sets.json"
    if not ps.exists():
        r = requests.get(f"https://play.pokemonshowdown.com/data/sets/{FORMAT}.json", timeout=60)
        r.raise_for_status()
        ps.write_text(r.text)
    print(f"cached {ps.relative_to(FP)} ({ps.stat().st_size // 1024} KB)")
    # Foul Play uses the previous month's chaos stats (-0 cutoff), cached by file basename
    month = datetime.now().replace(day=1)
    prev = (
        month.replace(month=month.month - 1)
        if month.month > 1
        else month.replace(year=month.year - 1, month=12)
    ).strftime("%Y-%m")
    src = ROOT / "data" / "smogon" / prev / "chaos" / f"{FORMAT}-0.json"
    dst_dir = FP / "fp" / "data" / "smogon_stats_cache"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{FORMAT}-0.json"
    if not src.exists():
        sys.exit(f"missing {src}: run scripts/fetch_smogon_stats.py first")
    dst.write_text(json.dumps(json.loads(src.read_text())["data"]))
    print(f"cached {dst.relative_to(FP)} from {src.relative_to(ROOT)}")


if __name__ == "__main__":
    {"install": install, "patch": patch, "cache": cache}[sys.argv[1]]()
