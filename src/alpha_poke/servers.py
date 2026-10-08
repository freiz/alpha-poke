"""Helpers for talking to Showdown servers.

Everything (evaluation, training) goes through ``local_server``, which only accepts loopback
hosts. The single exception is ``public_server``: the official server, used only by
scripts/play_public.py (explicit --public, registered bot account, whitelisted opponent, no
ladder) for friendly games the user arranges.
"""

from pathlib import Path

from poke_env import AccountConfiguration, ServerConfiguration

ROOT = Path(__file__).resolve().parents[2]

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def local_server(port: int = 8000, host: str = "localhost") -> ServerConfiguration:
    """A local no-security server (``scripts/start_showdown.sh <port>``)."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"refusing to connect to non-local host {host!r}")
    return ServerConfiguration(f"ws://{host}:{port}/showdown/websocket", None)


def account(name: str) -> AccountConfiguration:
    """Account for a local no-security server; no password required."""
    return AccountConfiguration(name[:18], None)


def public_server(confirm: bool = False):
    """The official Showdown server. Requires ``confirm=True`` (scripts/play_public.py --public)."""
    if not confirm:
        raise ValueError("the public server needs an explicit confirmation (--public)")
    from poke_env import ShowdownServerConfiguration

    return ShowdownServerConfiguration


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    """The KEY=value lines of .env (secrets: never printed or logged)."""
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def public_account() -> AccountConfiguration:
    """The registered bot account from .env (PS_BOT_USERNAME / PS_BOT_PASSWORD)."""
    env = load_env()
    user, password = env.get("PS_BOT_USERNAME"), env.get("PS_BOT_PASSWORD")
    if not user or not password:
        raise RuntimeError("PS_BOT_USERNAME / PS_BOT_PASSWORD missing in .env")
    return AccountConfiguration(user, password)
