"""Helpers for talking to local Showdown servers.

The public Showdown server / ladder is deliberately unreachable from here for now: every
server configuration goes through ``local_server``, which only accepts loopback hosts.
"""

from poke_env import AccountConfiguration, ServerConfiguration

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def local_server(port: int = 8000, host: str = "localhost") -> ServerConfiguration:
    """A local no-security server (``scripts/start_showdown.sh <port>``)."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"refusing to connect to non-local host {host!r}")
    return ServerConfiguration(f"ws://{host}:{port}/showdown/websocket", None)


def account(name: str) -> AccountConfiguration:
    """Account for a local no-security server; no password required."""
    return AccountConfiguration(name[:18], None)
