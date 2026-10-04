import pytest

from alpha_poke.servers import local_server


def test_local_server_ok():
    assert "localhost:8001" in local_server(8001).websocket_url


@pytest.mark.parametrize("host", ["sim.smogon.com", "play.pokemonshowdown.com", "10.0.0.5"])
def test_non_local_host_refused(host):
    with pytest.raises(ValueError):
        local_server(8000, host=host)
