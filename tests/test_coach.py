"""Game reviews (alpha_poke.coach, 2026-10-29) on a fixture replay with the tiny network: every
decision of the player searched, its option named as the state's options, the numbers in range;
the log's events with the sides as ME / OPP; the write-up's move check."""

import gzip
import json
from pathlib import Path

import pytest

from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.coach import narrate, replays
from alpha_poke.coach.review import key_moments, review, turn_events

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def game():
    rows = [
        json.loads(x)
        for x in gzip.decompress((FIXTURES / "replays_gen9ou.jsonl.gz").read_bytes())
        .decode()
        .splitlines()
    ]
    row = next(r for r in rows if 8 <= r["log"].count("|turn|") <= 15)
    return replays.from_json(row)


@pytest.fixture(scope="module")
def report(game):
    return review(game, "p1", BeliefModel.load(), str(FIXTURES / "tiny_net"), worlds=2, ms=20,
                  threads=1, log=lambda *_: None)  # fmt: skip


def test_every_decision_is_searched(report):
    ds = report["decisions"]
    assert len(ds) >= 8 and report["side"] == "p1" and report["player"] == "Player A"
    for d in ds:
        names = [o[0] for o in d["options"]]
        assert d["best"] == names[0]
        assert 0.0 <= d["value"] <= 1.0
        assert d["chosen_value"] is None or 0.0 <= d["chosen_value"] <= 1.0
        assert d["state"]["me"]["active"]["species"] and d["state"]["opp"]["alive"] >= 1
    assert all(len(d["options"]) <= 6 for d in ds)
    assert key_moments(report, min_score=0.0)  # (some decision ranks first)


def test_events_name_the_sides(game):
    ev = turn_events(game["log"], "p1")
    lines = [x for t in ev.values() for x in t]
    assert any(x.startswith("move|ME ") for x in lines) and any(
        x.startswith("move|OPP ") for x in lines
    )
    assert not any("p1a:" in x or "p2a:" in x for x in lines if x.startswith("move|"))


def test_side_of_and_the_summary(game, report):
    assert replays.side_of(game, "player b") == "p2"
    with pytest.raises(ValueError):
        replays.side_of(game, "someone else")
    text = narrate.summary(report)
    assert text.startswith("# Review:") and "| turn |" in text


def test_the_move_check_flags_unlearnable_moves(report):
    from alpha_poke.analysis.roles import to_id
    from alpha_poke.dex import learnset

    teams = [m for side in ("p1", "p2") for m in report["teams"][side]]
    learnable = set().union(*(learnset(m["species"]) or set() for m in teams))
    used = next(x for m in teams for x in m["moves"])
    foreign = next(x for x in ("Spore", "Shell Smash", "Quiver Dance", "Tail Glow")
                   if to_id(x) not in learnable)  # fmt: skip
    assert narrate.unknown_moves(f"Keep using {used}; teach it {foreign}.", report) == [foreign]


def test_the_page_carries_the_review_and_the_log(game, report):
    from alpha_poke.coach import viewer

    local, online = viewer.render(report, game, "local"), viewer.render(report, game, "official")
    assert "/js/battle.js" in local and "replay-embed.js" not in local
    assert "play.pokemonshowdown.com/js/replay-embed.js" in online
    log = local.split('class="battle-log-data">', 1)[1].split("</script>", 1)[0]
    assert "|turn|1" in log and "</" not in log  # (no early end of the script element)
    assert '"decisions"' in local and "__" not in local.split("<style>", 1)[0]


def test_the_client_cache_fetches_once_and_stays_inside(tmp_path, monkeypatch):
    from alpha_poke.coach import server

    calls = []

    class Response:
        status_code, content = 200, b"sprite"

    cache = server.Cache(tmp_path)
    monkeypatch.setattr(cache.session, "get", lambda url, timeout: calls.append(url) or Response())
    assert cache.get("sprites/gen5/pikachu.png").read_bytes() == b"sprite"
    assert cache.get("sprites/gen5/pikachu.png") is not None and len(calls) == 1  # (cached)
    assert cache.get("../etc/passwd") is None and cache.get("sprites/../../x") is None
    assert cache.get("config/secret.js") is None  # (not a client path)
    offline = server.Cache(tmp_path, offline=True)
    assert offline.get("sprites/gen5/pikachu.png") is not None and offline.get("js/new.js") is None
    assert len(calls) == 1


def test_the_page_server_answers_once_started():
    import socket
    import threading

    from alpha_poke.coach import server

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert not server.running(port)
    httpd = server.serve(port, offline=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert server.running(port)
    finally:
        httpd.shutdown()
