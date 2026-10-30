"""Helpers for talking to Showdown servers.

Everything (evaluation, training) goes through ``local_server``, which only accepts loopback
hosts. The single exception is ``public_server``: the official server, used only by
scripts/play_public.py (explicit --public, registered bot account, whitelisted opponent, no
ladder) for friendly games the user arranges.
"""

import asyncio
import random
from pathlib import Path

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.concurrency import handle_threaded_coroutines
from poke_env.data import to_id_str

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
        for line in path.read_text(encoding="utf-8").splitlines():
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


async def _accept_one(player, opponent: str, start_timeout: float) -> None:
    await player.ps_client.logged_in.wait()
    want = to_id_str(opponent)
    while True:
        if to_id_str(await player._challenge_queue.get()) != want:
            continue
        await player.ps_client.accept_challenge(want, player.next_team)
        try:
            await asyncio.wait_for(player._battle_semaphore.acquire(), start_timeout)
            break
        except TimeoutError:
            player.logger.warning("accepted %s's challenge but no battle started within %.0f s "
                                  "(withdrawn first?): waiting for a new one", want, start_timeout)  # fmt: skip
    await player._battle_count_queue.join()


async def accept_one(player, opponent: str, start_timeout: float = 30.0) -> None:
    """One challenge from ``opponent`` accepted and its battle played to the end: poke-env's
    accept_challenges(opponent, 1), except a failed accept. A challenge withdrawn before we accept
    it (the server: "... is not challenging you") never starts a battle, and poke-env waits for
    one forever (2026-10-29, a friendly game: the bot stopped answering). Now: no battle within
    ``start_timeout`` s of the accept -> back to waiting for the next challenge."""
    await handle_threaded_coroutines(
        _accept_one(player, opponent, start_timeout), player.ps_client.loop
    )


class TeamDeck:
    """A pool's teams in a shuffled order, each once before any comes again (a new shuffle per
    round); ``seed`` None: a different order every session (2026-10-29: independent random draws
    repeated a team before others were used)."""

    def __init__(self, names, seed: int | None = None):
        self.names = sorted(names)
        self.rng = random.Random(seed)
        self.order: list[str] = []

    def next(self) -> str:
        if not self.order:
            self.order = self.rng.sample(self.names, len(self.names))
        return self.order.pop(0)
