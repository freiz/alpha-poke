"""Game reviews (alpha_poke.coach, 2026-10-29) on a fixture replay with the tiny network: every
decision of the player searched, its option named as the state's options, the numbers in range;
the log's events with the sides as ME / OPP; the write-up's move check."""

import gzip
import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import poke_engine as pe
import pytest
from poke_env.data import GenData

from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.coach import narrate, replays
from alpha_poke.coach.review import (
    decision_count,
    key_moments,
    metrics,
    review,
    turn_events,
    verdict,
)
from alpha_poke.coach.team import TeamError, load_team, match_team, parse_team
from alpha_poke.replay import parse_replay
from alpha_poke.train.positions import positions_from_replay

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GEN = GenData.from_gen(9)


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
    # (the first six by visits, and the chosen one when it is not among them)
    assert all(len(d["options"]) <= 6 or (len(d["options"]) == 7 and d["options"][6][0] == d["chosen"])
               for d in ds)  # fmt: skip
    # (the moments: the "bad" verdicts, worst first -- none at all is possible, the search timed)
    moments = key_moments(report, min_score=0.0)
    assert all(verdict(d) == "bad" for d in moments)
    assert [d["score"] for d in moments] == sorted((d["score"] for d in moments), reverse=True)


def test_repeated_searches_give_errors(game):
    """repeats > 1: each decision searched over that many draws of belief worlds; the values are
    means with standard errors, the loss's from each search's own gap (paired)."""
    rep = review(game, "p1", BeliefModel.load(), str(FIXTURES / "tiny_net"), worlds=2, ms=20,
                 threads=1, log=lambda *_: None, repeats=3)  # fmt: skip
    ds = rep["decisions"]
    assert rep["settings"]["repeats"] == 3 and all(d["repeats"] == 3 for d in ds)
    assert all(
        abs(sum(o[1] for o in d["options"]) - 1) < 0.05 or len(d["options"]) >= 6 for d in ds
    )
    assert any(d["value_se"] is not None for d in ds)
    assert all(len(o) == 6 for d in ds for o in d["options"])


def test_parallel_searches_count_and_visits(game, report):
    """Searches run at once give every decision (the count the home page shows beforehand), each
    with the root's visits of all its searches."""
    rep = review(game, "p1", BeliefModel.load(), str(FIXTURES / "tiny_net"), worlds=2, ms=20,
                 threads=1, log=lambda *_: None, repeats=2, parallel=3)  # fmt: skip
    turns = [(d["turn"], d["kind"]) for d in report["decisions"]]
    assert [(d["turn"], d["kind"]) for d in rep["decisions"]] == turns
    assert decision_count(game, "p1") == len(turns)
    assert all(d["visits"] > 0 and d["repeats"] == 2 for d in rep["decisions"])
    assert rep["settings"]["parallel"] == 3 and rep["settings"]["team"] is False


def _export(game, side: str, drop_move: bool = False) -> str:
    """A Showdown export of ``side``'s team in ``game``: its revealed parts, the rest made up
    (Modest, 252 HP / 4 Def / 252 Spe, 0 Atk IVs)."""
    out = []
    for m in [m for m in parse_replay(game).teams[side] if not m.phantom]:
        moves = [] if drop_move else list(m.moves)
        moves = (moves + [x for x in ("Protect", "Substitute", "Rest", "Toxic") if x not in moves])[
            :4
        ]
        out += [f"{m.species.replace('-*', '')} @ {m.item or 'Leftovers'}",
                f"Ability: {m.ability or 'Pressure'}", f"Tera Type: {m.tera_type or 'Fairy'}",
                "EVs: 252 HP / 4 Def / 252 Spe", "Modest Nature", "IVs: 0 Atk",
                *[f"- {x}" for x in moves], ""]  # fmt: skip
    return "\n".join(out)


def _own_sides(game, belief, seed: int, known=None) -> list:
    """The player's sets in each position of one draw (the move slots' order is shuffled)."""
    ps = positions_from_replay(game, belief, random.Random(seed), extra_per_game=10**6, seed=seed,
                               worlds=2, known_sets=known, side="p1")  # fmt: skip
    return [[(str(m.id), str(m.item), str(m.ability), str(m.nature), tuple(m.evs), m.attack,
              m.speed, sorted(str(x.id) for x in m.moves))
             for m in pe.State.from_string(p.state).side_one.pokemon]
            for p in ps]  # fmt: skip


def test_a_pasted_team_is_the_players_sets_exactly(game):
    """The player's own team pasted: every state has its sets (moves, item, ability, nature,
    EVs, IVs: the stats) in every draw; without it, the parts the game did not show are drawn
    anew for each repeat (their spread is in the error ranges)."""
    belief = BeliefModel.load()
    records = [m for m in parse_replay(game).teams["p1"] if not m.phantom]
    sets = match_team(parse_team(_export(game, "p1")), records)
    known = {"p1": sets}
    a, b = _own_sides(game, belief, 0, known), _own_sides(game, belief, 1, known)
    assert a == b
    assert _own_sides(game, belief, 0) != _own_sides(game, belief, 1)
    st = pe.State.from_string(
        positions_from_replay(
            game,
            belief,
            random.Random(0),
            extra_per_game=10**6,
            worlds=2,
            known_sets=known,
            side="p1",
        )[0].state  # fmt: skip
    )
    for p in st.side_one.pokemon:
        k = next(v for key, v in sets.items() if key.startswith(str(p.id).lower()[:5]))
        assert str(p.nature).lower() == "modest" and tuple(p.evs) == (252, 0, 4, 0, 0, 252)
        assert sorted(str(m.id).lower() for m in p.moves) == sorted(k.moves)
        base = GEN.pokedex[str(p.id).lower()]["baseStats"]["atk"]
        assert p.attack == int(((2 * base + 0) * 100 // 100 + 5) * 0.9)  # (0 Atk IVs, Modest)
    rep = review(game, "p1", belief, str(FIXTURES / "tiny_net"), worlds=2, ms=20, threads=1,
                 log=lambda *_: None, team=_export(game, "p1"))  # fmt: skip
    assert rep["settings"]["team"] is True and rep["decisions"]


def test_a_team_that_is_not_the_games_is_refused(game):
    records = [m for m in parse_replay(game).teams["p1"] if not m.phantom]
    with pytest.raises(TeamError) as e:  # (another side's team)
        match_team(parse_team(_export(game, "p2")), records)
    assert e.value.code == "team_mismatch"
    if any(m.moves for m in records):  # (a move the game showed, missing from the set)
        with pytest.raises(TeamError):
            match_team(parse_team(_export(game, "p1", drop_move=True)), records)
    with pytest.raises(TeamError) as e:
        parse_team("")
    assert e.value.code == "team_unreadable"


PASTE = """G.O.A.T. (Orthworm) (F) @ Rocky Helmet  \r
Ability: Earth Eater  \r
Shiny: Yes  \r
Tera Type: Ghost  \r
EVs: 248 HP / 252 Def / 8 Spe  \r
Impish Nature  \r
- Iron Defense  \r
- Body Press  \r
- Heavy Slam  \r
- Spikes  \r
\r
Slowking-Galar @ Heavy-Duty Boots  \r
Ability: Regenerator  \r
Tera Type: Fairy  \r
EVs: 248 HP / 16 Def / 4 SpA / 240 SpD  \r
Sassy Nature  \r
IVs: 0 Atk / 0 Spe  \r
- Chilly Reception  \r
- Future Sight  \r
- Sludge Bomb  \r
- Thunder Wave  \r
"""


def test_a_pokepaste_link_is_fetched(monkeypatch):
    """A PokéPaste link: its raw text fetched (a nickname, a gender, Shiny, CRLF; no IVs line:
    all 31); an export pasted as is; a link that cannot be fetched: TeamError "team_fetch"."""
    import requests

    asked = []

    class Reply:
        text = PASTE

        def raise_for_status(self):
            pass

    def get(url, **kw):
        asked.append(url)
        if "0000" in url:
            raise requests.ConnectionError("offline")
        return Reply()

    monkeypatch.setattr(requests, "get", get)
    team = load_team("  https://pokepast.es/6E7F76243D853231 \n")
    assert asked == ["https://pokepast.es/6e7f76243d853231/raw"]
    assert team["orthworm"].evs == (248, 0, 252, 0, 0, 8) and team["orthworm"].ivs == (31,) * 6
    assert team["orthworm"].nature == "impish" and team["orthworm"].tera == "ghost"
    assert team["slowkinggalar"].ivs == (31, 0, 31, 31, 31, 0)
    assert load_team(PASTE) == team and len(asked) == 1  # (an export: no fetch)
    with pytest.raises(TeamError) as e:
        load_team("pokepast.es/0000")
    assert e.value.code == "team_fetch"


def test_the_verdict():
    from alpha_poke.coach.review import verdict

    base = {
        "chosen": "a",
        "best": "b",
        "options": [["b", 0.8, 0.40, 0.01], ["a", 0.02, 0.30, 0.01]],
    }
    shunned = base | {"chosen_share": 0.02}
    assert verdict(base | {"chosen": "b", "chosen_share": 0.8, "loss": 0}) == "same"
    assert verdict(shunned | {"loss": 0.10, "loss_se": 0.014}) == "bad"  # beyond 2 errors
    assert verdict(shunned | {"loss": 0.04, "loss_se": 0.025}) == "mild"  # within the noise
    assert (
        verdict(shunned | {"loss": 0.04, "loss_se": 0.025}, z=1) == "bad"
    )  # (stricter on noise: 1 error)
    # (under 3 points is no mistake, however sure: 2026-10-30, a Tera Fire Punch 1.2 +- 0.3
    # points below the plain one, read as "AI disagrees")
    assert verdict(shunned | {"loss": 0.012, "loss_se": 0.003, "repeats": 5, "paired": 5}) == "ok"
    assert verdict(shunned | {"loss": None, "loss_se": None}) == "mild"  # never tried: no value
    assert verdict(base | {"chosen_share": 0.3, "loss": 0.03, "loss_se": None}) == "ok"
    assert verdict(base | {"chosen_share": 0.3, "loss": 0.08, "loss_se": 0.01}) == "bad"


def test_the_scorecard():
    """metrics: first / top-two matches and the mean loss over the decisions with a choice (one
    option: left out), the verdicts' counts over all."""
    opt = lambda *names: [[c, 0.5, 0.5, None] for c in names]  # noqa: E731
    ds = [
        {"chosen": "a", "best": "a", "options": opt("a", "b"), "loss": 0.0, "chosen_share": 0.6},
        {"chosen": "b", "best": "a", "options": opt("a", "b", "c"), "loss": 0.02, "chosen_share": 0.3},
        {"chosen": "c", "best": "a", "options": [["a", 0.9, 0.6, None], ["b", 0.08, 0.5, None],
                                                 ["c", 0.02, 0.4, None]],
         "loss": 0.2, "chosen_share": 0.02},
        {"chosen": "a", "best": "a", "options": opt("a"), "loss": 0.0, "chosen_share": 1.0},
    ]  # fmt: skip
    m = metrics({"decisions": ds})
    assert m["decisions"] == 3 and m["top1"] == 1 / 3 and m["top2"] == 2 / 3
    assert abs(m["mean_loss"] - 0.22 / 3) < 1e-9 and m["bad"] == 1 and m["mild"] == 0


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


def test_the_reviews_index(game, report, tmp_path, monkeypatch):
    """coach.index: the saved reviews' rows (the reviewed player first, the scorecard, both
    teams), searched, sorted and paged; a review's name and note kept when it is indexed again;
    a review gone, its row gone."""
    import copy
    import os
    import shutil

    from alpha_poke.coach import app, index

    monkeypatch.setattr(app, "COACH", tmp_path)
    other = copy.deepcopy(report) | {"side": "p2", "player": "Player B"}
    app.save(report, game)
    app.save(other, game)
    os.utime(tmp_path / f"{game['id']}-p1" / "review.json", (1, 1))  # (p1 reviewed long ago)
    index.sync(tmp_path, app.stored)
    rows = index.query(tmp_path)["rows"]
    assert [(r["player"], r["opponent"]) for r in rows] == [
        ("Player B", "Player A"),
        ("Player A", "Player B"),
    ]
    assert rows[1]["teams"][0] == rows[0]["teams"][1] and rows[1]["decisions"] >= 1
    assert rows[1]["played"] == index.played_at(game) and rows[1]["url"].endswith("-p1/viewer.html")
    assert [r["side"] for r in index.query(tmp_path, q="player b")["rows"]] == ["p2", "p1"]
    mon = rows[0]["teams"][1][0].lower()[:5]
    assert index.query(tmp_path, q=mon)["total"] == 2
    page = index.query(tmp_path, sort="reviewed", desc=False, size=1, page=2)
    assert page["pages"] == 2 and page["rows"][0]["side"] == "p2"
    assert index.set_meta(tmp_path, f"{game['id']}-p1", "  Zeta game ", "watch turn 5")
    assert not index.set_meta(tmp_path, "nothing-here", "x", "")
    assert [r["side"] for r in index.query(tmp_path, sort="title", desc=False)["rows"]] == [
        "p2",
        "p1",
    ]
    assert index.query(tmp_path, q="turn 5")["rows"][0]["title"] == "Zeta game"
    app.save(report, game)  # (reviewed again: indexed again, its name and note kept)
    index.sync(tmp_path, app.stored)
    r = next(r for r in index.query(tmp_path)["rows"] if r["side"] == "p1")
    assert r["title"] == "Zeta game" and r["note"] == "watch turn 5" and r["reviewed"] > 1
    page = (tmp_path / f"{game['id']}-p1" / "viewer.html").read_text(encoding="utf-8")
    assert '"title": "Zeta game"' in page
    shutil.rmtree(tmp_path / f"{game['id']}-p2")
    index.sync(tmp_path, app.stored)
    assert [r["side"] for r in index.query(tmp_path)["rows"]] == ["p1"]


def test_the_app_reviews_an_uploaded_replay(game):
    """The home page's flow: upload -> players -> a review job (the tiny network, a token search)
    -> the review page; a request from another site's page refused."""
    import socket
    import threading
    import time

    import requests

    from alpha_poke.coach import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = app.make(port, offline=True, threads=1, model=str(FIXTURES / "tiny_net"),
                     strengths={"standard": (2, 20, 2)})  # fmt: skip
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        home = requests.get(base + "/", timeout=5)
        assert "对局复盘" in home.text and home.headers["Cache-Control"] == "no-cache"
        upload = {"upload": {"name": "game.json", "text": json.dumps(game)}}
        info = requests.post(base + "/api/players", json=upload, timeout=30).json()
        assert info["players"] == ["Player A", "Player B"] and info["max_parallel"] >= 1
        assert info["decisions"] == [decision_count(game, s) for s in ("p1", "p2")]
        wrong = requests.post(base + "/api/review", json=upload | {"player": "Player B", "lang": "zh",
                              "team": _export(game, "p1")}, timeout=30)  # fmt: skip
        assert wrong.status_code == 400 and "队伍和这局对不上" in wrong.json()["error"]
        for lang, text in (("en", "Paste a replay"), ("zh", "请粘贴")):  # (the page's language)
            r = requests.post(base + "/api/players", json={"source": "", "lang": lang}, timeout=5)
            assert r.status_code == 400 and text in r.json()["error"]
        bad = requests.post(base + "/api/review", json=upload | {"player": "Player A"},
                            headers={"Origin": "https://elsewhere.example"}, timeout=5)  # fmt: skip
        assert bad.status_code == 403
        job = requests.post(
            base + "/api/review",
            json=upload | {"player": "Player B", "team": _export(game, "p2"), "parallel": 2},
            timeout=30,
        ).json()["job"]

        def wait(job):
            for _ in range(240):
                j = requests.get(f"{base}/api/job/{job}", timeout=5).json()
                if j["status"] in ("done", "error"):
                    break
                time.sleep(0.5)
            assert j["status"] == "done", j
            return j

        j = wait(job)
        page = requests.get(base + j["url"], timeout=5).text
        assert '"side": "p2"' in page and "/js/battle.js" in page and "reviewForm(" in page
        assert any(
            r["url"] == j["url"]
            for r in requests.get(base + "/api/reviews", timeout=5).json()["rows"]
        )
        # review again (the page's button): the game, the player and the team kept with it
        name = j["url"].split("/")[2]
        redo = requests.get(f"{base}/api/redo-info?review={name}", timeout=5).json()
        assert (
            redo["team"] is True
            and redo["settings"]["repeats"] == 2
            and redo["decisions"] == [decision_count(game, s) for s in ("p1", "p2")]
        )
        again = requests.post(base + "/api/redo", json={"review": name, "custom": {"repeats": 1, "seconds": 0.2,
                              "worlds": 4}, "parallel": 1}, timeout=30).json()["job"]  # fmt: skip
        assert wait(again)["url"] == j["url"]
        rep = json.loads((app.COACH / name / "review.json").read_text(encoding="utf-8"))
        assert rep["settings"]["team"] is True and rep["settings"]["repeats"] == 1
        # the other player's view: its own review (this one stays), the team kept not its own
        assert redo["players"] == ["Player A", "Player B"] and redo["other"] is None
        other = requests.post(base + "/api/redo", json={"review": name, "player": "Player A", "custom": {
                              "repeats": 1, "seconds": 0.2, "worlds": 4}}, timeout=30).json()["job"]  # fmt: skip
        url = wait(other)["url"]
        assert url != j["url"] and (app.COACH / name / "review.json").is_file()
        rep = json.loads(
            (app.COACH / url.split("/")[2] / "review.json").read_text(encoding="utf-8")
        )
        assert rep["side"] == "p1" and rep["settings"]["team"] is False
        link = requests.get(f"{base}/api/redo-info?review={name}", timeout=5).json()["other"]
        assert link == url
        # (a review saved before its replay was kept: the log in its page)
        (app.COACH / name / "replay.json").unlink()
        assert requests.get(f"{base}/api/redo-info?review={name}", timeout=5).status_code == 200
        assert app.stored(name)[1]["log"] == game["log"]
        assert '"side": "p2"' in requests.get(base + j["url"], timeout=5).text
        # the home page's list and a rename (the review page shows the name)
        listed = requests.get(base + "/api/reviews?sort=title&order=asc&size=1", timeout=5).json()
        assert listed["total"] == 2 and listed["pages"] == 2 and len(listed["rows"]) == 1
        ok = requests.post(base + "/api/meta", json={"review": name, "title": "Practice 1", "note": "n"},
                           timeout=5)  # fmt: skip
        assert ok.json() == {"ok": True}
        assert '"title": "Practice 1"' in requests.get(base + j["url"], timeout=5).text
        assert (
            requests.get(base + "/api/reviews?q=practice", timeout=5).json()["rows"][0]["dir"]
            == name
        )
        gone = requests.post(
            base + "/api/redo", json={"review": "nothing-here", "lang": "zh"}, timeout=5
        )
        assert gone.status_code == 400 and "找不到这份复盘" in gone.json()["error"]
    finally:
        httpd.shutdown()


def test_the_launcher_survives_a_console_without_chinese():
    """2026-10-30, the Windows build's smoke test: printing the start message to a cp1252 stdout
    raised UnicodeEncodeError and the frozen app died."""
    import subprocess
    import sys

    code = (
        "from alpha_poke.coach import launcher, app, server\n"
        "server.open_page = lambda url: None\n"
        "server.running = lambda port: False\n"
        "app.free_port = lambda start=8090: 1\n"
        "app.make = lambda port: type('S', (), {'serve_forever': lambda self: None})()\n"
        "launcher.main()\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60,
                       env={**__import__("os").environ, "PYTHONIOENCODING": "cp1252"})  # fmt: skip
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-500:]


def test_the_frozen_app_keeps_its_data_where_the_platform_wants(monkeypatch, tmp_path):
    """The packaged app's data directory: Windows %LOCALAPPDATA%, macOS Application Support,
    elsewhere XDG's data home."""
    from alpha_poke.coach import launcher

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(launcher.Path, "home", lambda: tmp_path / "home")
    for platform, want in (("win32", tmp_path / "local" / "alpha-poke"),
                           ("darwin", tmp_path / "home" / "Library" / "Application Support" / "alpha-poke"),
                           ("linux", tmp_path / "xdg" / "alpha-poke")):  # fmt: skip
        monkeypatch.setattr(launcher.sys, "platform", platform)
        assert launcher.user_data() == want


def test_the_smoke_test_finds_its_replay():
    """packaging/smoke_test.py (run by the desktop app's workflow only) reads a fixture replay by a
    path relative to itself: there (2026-10-30: moved up a directory, its path was not)."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "packaging" / "smoke_test.py"
    spec = importlib.util.spec_from_file_location("smoke_test", path)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    assert smoke.FIXTURE.is_file()


def test_a_struggle_is_named_struggle(monkeypatch):
    """Issue #28's follow-up: the search names the engine's none option "No Move"; a review shows
    Struggle when the side struggles (its slots' name), so the player's choice matches it."""
    from types import SimpleNamespace

    from alpha_poke.coach import review as rv

    names = ["struggle", "switch greattusk"] + [""] * 12
    monkeypatch.setattr(rv.slots, "names", lambda state: names)
    monkeypatch.setattr(rv, "public_state", lambda state: {})
    p = SimpleNamespace(state="", action=0, turn=24, kind=0)
    d = rv._decision(p, [([("No Move", 60, 0.01), ("switch greattusk", 40, 0.02)], 100)], {})
    assert {o[0] for o in d.options} == {"struggle", "switch greattusk"}
    assert d.chosen == "struggle" and d.chosen_value == 0.01


LOG_FAST = """|player|p1|Alice|1|
|player|p2|Bob|2|
|gen|9
|tier|[Gen 9] OU
|poke|p1|Great Tusk|
|poke|p1|Dragonite, M|
|poke|p2|Gliscor, M|
|poke|p2|Kingambit, M|
|start
|switch|p1a: Great Tusk|Great Tusk|100/100
|switch|p2a: Gliscor|Gliscor, M|100/100
|turn|1
|move|p2a: Gliscor|Earthquake|p1a: Great Tusk
|-damage|p1a: Great Tusk|76/100
|move|p1a: Great Tusk|Headlong Rush|p2a: Gliscor
|-immune|p2a: Gliscor
|-heal|p2a: Gliscor|100/100|[from] item: Leftovers
|upkeep
|turn|2
|move|p2a: Gliscor|Spikes|p1a: Great Tusk
|-sidestart|p1: Alice|Spikes
|move|p1a: Great Tusk|Rapid Spin|p2a: Gliscor
|-damage|p2a: Gliscor|90/100
|-sideend|p1: Alice|Spikes|[from] move: Rapid Spin|[of] p1a: Great Tusk
|upkeep
|turn|3
|win|Alice
"""
TEAM_FAST = """Great Tusk
Ability: Protosynthesis
Tera Type: Steel
EVs: 252 Atk / 4 Def / 252 Spe
Jolly Nature
- Headlong Rush
- Rapid Spin
- Close Combat

Dragonite @ Heavy-Duty Boots
Ability: Multiscale
Tera Type: Normal
EVs: 252 Atk / 4 Def / 252 Spe
Adamant Nature
- Extreme Speed
- Earthquake
- Dragon Dance
- Roost
"""


TEAM_FAST_P2 = """Gliscor @ Leftovers
Ability: Poison Heal
Tera Type: Water
EVs: 244 HP / 12 Def / 252 Spe
Jolly Nature
- Earthquake
- Knock Off
- Protect
- Spikes

Kingambit @ Leftovers
Ability: Supreme Overlord
Tera Type: Dark
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Kowtow Cleave
- Sucker Punch
- Iron Head
- Swords Dance
"""
# (a local replay: its saver's side, p1, in exact HP -- the Great Tusk's 371 -- the other in percent)
LOG_FAST_EXACT = LOG_FAST.replace("|Great Tusk|100/100", "|Great Tusk|371/371").replace(
    "|p1a: Great Tusk|76/100", "|p1a: Great Tusk|281/371"
)


def _turn2(known=None, k=0, log=None, side="p1"):
    ps = positions_from_replay({"id": "fast", "log": log or LOG_FAST, "rating": None, "uploadtime": 0},
                               BeliefModel.load(), random.Random(k), extra_per_game=10**6,
                               worlds=8, known_sets=known, side=side)  # fmt: skip
    p = next(p for p in ps if p.turn == 2 and p.kind == 0)
    return [pe.State.from_string(w) for w in [p.state, *(p.worlds or [])]]


def test_a_pasted_team_is_not_completed():
    """2026-10-30 review: a pasted Dragonite with no item and three moves drew Boots / Leftovers
    and a fourth move (Roost, Ice Spinner): the AI weighed moves and items the player has not.
    An exact set is the set (here the itemless three-move Great Tusk)."""
    known = {"p1": parse_team(TEAM_FAST)}
    for k in range(4):
        for st in _turn2(known, k):
            tusk = next(p for p in st.side_one.pokemon if str(p.id).lower() == "greattusk")
            assert str(tusk.item).lower() == "none", tusk.item
            assert sorted(str(m.id).lower() for m in tusk.moves if str(m.id).lower() != "none") == [
                "closecombat", "headlongrush", "rapidspin"]  # fmt: skip


def test_a_pasted_team_uses_the_speed_evidence():
    """2026-10-30 review: a review ignored the move order -- a foe that had just moved first drawn
    slower than ours. Here a Gliscor (Leftovers: no Choice Scarf) moved before a 300-Speed Great
    Tusk, which most of its spreads cannot. With the team pasted our speed is exact: every world's
    Gliscor is at least as fast (play's rule, the evidence before the decision only)."""
    known = {"p1": parse_team(TEAM_FAST)}
    for k in range(3):
        for st in _turn2(known, k):
            tusk = next(p for p in st.side_one.pokemon if str(p.id).lower() == "greattusk")
            gliscor = st.side_two.pokemon[int(st.side_two.active_index)]
            assert tusk.speed == 300 and gliscor.speed >= 300, (tusk.speed, gliscor.speed)


def test_a_pasted_team_uses_the_damage_evidence(monkeypatch):
    """The same for F1's damage evidence: turn 1's Knock Off on our exact Great Tusk weighs the
    Gliscor's sets at turn 2 (the turn-start worlds kept as the hits' bases); without the team,
    none (our stats are a guess)."""
    import alpha_poke.agents.engine_state as es

    seen = []
    inner = es.damage_posteriors

    def spy(battle, *a, **k):
        out = inner(battle, *a, **k)
        seen.append((battle.turn, sorted(out)))
        return out

    monkeypatch.setattr(es, "damage_posteriors", spy)
    _turn2({"p1": parse_team(TEAM_FAST)})
    assert (2, ["gliscor"]) in seen, seen
    seen.clear()
    _turn2()
    assert seen == []


def test_the_gaps_error_is_paired(monkeypatch):
    """2026-10-30 reviews: the gap's error combined the two options' errors as if independent; in
    one search they share the hidden sets' draw and move together -- three searches whose values
    swing by 15 points but whose gap is 10 points each time: no error in the gap, a sure "bad".
    And the gap must come from the same searches as its error: the best untried in one search
    (90/89, 80/79, -/10) is a 1-point gap over two searches, not 26 points with no error."""
    from types import SimpleNamespace

    from alpha_poke.coach import review as rv

    monkeypatch.setattr(rv.slots, "names", lambda state: ["a", "b"] + [""] * 12)
    monkeypatch.setattr(rv, "public_state", lambda state: {})
    p = SimpleNamespace(state="", action=1, turn=3, kind=0)
    runs = [([("a", 95, q + 0.1), ("b", 5, q)], 100) for q in (0.3, 0.45, 0.6)]
    d = rv._decision(p, runs, {})
    assert d.loss == 0.1 and d.loss_se == 0.0 and d.paired == 3
    assert rv.verdict(vars(d)) == "bad"
    runs = [([("a", 95, 0.9), ("b", 5, 0.89)], 100), ([("a", 95, 0.8), ("b", 5, 0.79)], 100),
            ([("a", 0, 0.0), ("b", 100, 0.1)], 100)]  # fmt: skip
    d = rv._decision(p, runs, {})
    assert d.loss == 0.01 and d.paired == 2 and rv.verdict(vars(d)) != "bad"
    b = next(o for o in d.options if o[0] == "b")
    assert b[4] == 0.01 and b[5] == 0.0
    # (one search with both: unsure -- not a "bad", however large the gap)
    d = rv._decision(p, runs[:1] + [([("a", 100, 0.8), ("b", 0, 0.0)], 100)] * 2, {})
    assert d.paired == 1 and rv.verdict(vars(d)) != "bad"


def test_a_tie_is_reviewed(game):
    """2026-10-30 review: a tie (no winner) gave a finished review with no decisions, shown as a
    loss -- the training data's filter (no value label). A review needs no label: every decision,
    shown as a tie; a replay with nothing to rebuild is an error, not an empty review."""
    from alpha_poke.coach.review import decision_count
    from alpha_poke.coach.viewer import render

    log = re.sub(r"^\|win\|.*$", "|tie", game["log"], flags=re.M)
    tie = game | {"log": log}
    rep = review(tie, "p1", BeliefModel.load(), str(FIXTURES / "tiny_net"), worlds=2, ms=20,
                 threads=1, log=lambda *_: None)  # fmt: skip
    assert rep["winner"] is None and len(rep["decisions"]) == decision_count(tie, "p1") > 0
    assert '"won": null' in render(rep, tie, "local")
    cut = game | {"log": game["log"].split("|turn|1\n")[0]}
    with pytest.raises(ValueError, match="no decision"):
        review(cut, "p1", BeliefModel.load(), str(FIXTURES / "tiny_net"), worlds=2, ms=20,
               threads=1, log=lambda *_: None)  # fmt: skip


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_an_eject_buttons_switch_is_its_decisions_step():
    """2026-10-30 review: the page took a pivot's switch only from a switch line with "[from]"
    (U-turn's); an Eject Button's has none, and its decision was put at the turn's end as one the
    log does not show. The page's own steps(), run in node on that turn."""
    from alpha_poke.coach import viewer

    js = viewer.PAGE
    fns = (
        js[js.index("const fromOf") : js.index("function event(")]
        + js[
            js.index("function steps(t) {") : js.index("\n}\n", js.index("function steps(t) {")) + 3
        ]
    )
    # (the turn as turn_events gives it -- gen9ou-demo-fp-281849-p1's turn 2)
    events = {2: ["", "switch|ME Toxapex|Toxapex, F|100/100", "-terastallize|OPP Pecharunt|Ghost",
                  "move|OPP Pecharunt|Shadow Ball|ME Toxapex", "-damage|ME Toxapex|48/100",
                  "-enditem|ME Toxapex|Eject Button", "", "switch|ME Weavile|Weavile, M|100/100",
                  "-ability|ME Weavile|Pressure", "", "upkeep"]}  # fmt: skip
    decisions = [{"turn": 2, "kind": "turn"}, {"turn": 2, "kind": "pivot switch"}]
    code = (f"const R = {json.dumps({'events': events, 'decisions': decisions})};\n{fns}\n"
            "console.log(JSON.stringify(steps(2).map(s => [s.kind, s.dec ?? null])));")  # fmt: skip
    out = json.loads(
        subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
    )
    assert out == [["switch", 0], ["move", None], ["switch", 1]], out


def test_guessed_moves_are_marked(game, report):
    """Without the team, the player's moves the game never showed are the belief's guesses: a
    review marks them (the AI may be suggesting a move the player has not); with the team, none."""
    from alpha_poke.analysis.roles import to_id

    records = {to_id(m.species): {to_id(x) for x in m.moves}
               for m in parse_replay(game).teams["p1"] if not m.phantom}  # fmt: skip
    marked = [
        (to_id(d["state"]["me"]["active"]["species"]), g)
        for d in report["decisions"]
        for g in d["guessed"]
    ]
    assert marked
    for sp, g in marked:
        known = next(v for k, v in records.items() if sp.startswith(k) or k.startswith(sp))
        assert g.removesuffix("-tera") not in known
    team = review(game, "p1", BeliefModel.load(), str(FIXTURES / "tiny_net"), worlds=2, ms=20,
                  threads=1, log=lambda *_: None, team=_export(game, "p1"))  # fmt: skip
    assert all(not d["guessed"] for d in team["decisions"])


def test_the_team_must_fit_the_tera_item_and_ability_shown():
    """A pasted team that contradicts what the game showed of the player's own sets is refused
    (the tera type, the item, the ability), but not for a forme's ability (Ogerpon's Embody
    Aspect on terastallizing) nor an item that changed hands (a Trick's Choice Scarf knocked off)."""
    head = ("|player|p1|Alice|1|\n|player|p2|Bob|2|\n|gen|9\n|tier|[Gen 9] OU\n"
            "|poke|p1|Ogerpon-Wellspring, F|\n|poke|p1|Garchomp, M|\n|poke|p2|Kingambit, M|\n"
            "|poke|p2|Gholdengo|\n")  # fmt: skip
    log = head + "\n".join([
        "|start", "|switch|p1a: Ogerpon|Ogerpon-Wellspring, F|100/100",
        "|switch|p2a: Kingambit|Kingambit, M|100/100", "|turn|1",
        "|-terastallize|p1a: Ogerpon|Water",
        "|-ability|p1a: Ogerpon|Embody Aspect (Wellspring)|boost", "|-boost|p1a: Ogerpon|spd|1",
        "|move|p1a: Ogerpon|Ivy Cudgel|p2a: Kingambit", "|-damage|p2a: Kingambit|60/100",
        "|-heal|p1a: Ogerpon|100/100|[from] item: Wellspring Mask", "|upkeep", "|turn|2",
        "|switch|p1a: Garchomp|Garchomp, M|100/100", "|-ability|p1a: Garchomp|Rough Skin",
        "|-enditem|p1a: Garchomp|Leftovers|[from] move: Knock Off", "|upkeep", "|turn|3", "|win|Alice", ""])  # fmt: skip
    team = """Ogerpon-Wellspring @ Wellspring Mask
Ability: Water Absorb
Tera Type: Water
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Ivy Cudgel
- Horn Leech
- Knock Off
- U-turn

Garchomp @ Leftovers
Ability: Rough Skin
Tera Type: Steel
EVs: 252 HP / 4 Def / 252 Spe
Jolly Nature
- Earthquake
- Stealth Rock
- Spikes
- Dragon Tail
"""
    records = [m for m in parse_replay({"id": "t", "log": log}).teams["p1"] if not m.phantom]
    assert match_team(parse_team(team), records, log, "p1")  # (Embody Aspect: the forme's)
    for wrong, what in (("Tera Type: Water", "Tera Type: Fire"), ("Garchomp @ Leftovers", "Garchomp @ Rocky Helmet"),
                        ("Ability: Rough Skin", "Ability: Sand Veil")):  # fmt: skip
        with pytest.raises(TeamError, match="team_mismatch"):
            match_team(parse_team(team.replace(wrong, what)), records, log, "p1")
    # (a Trick gave it a Choice Scarf, then lost: the side's items changed hands -- no item check)
    tricked = log.replace("|-enditem|p1a: Garchomp|Leftovers|", "|-item|p1a: Garchomp|Choice Scarf|[from] move: Trick\n"
                          "|-enditem|p1a: Garchomp|Choice Scarf|")  # fmt: skip
    records = [m for m in parse_replay({"id": "t", "log": tricked}).teams["p1"] if not m.phantom]
    assert match_team(parse_team(team), records, tricked, "p1")


@pytest.mark.parametrize("log", ["percent", "p1 exact"])
@pytest.mark.parametrize("side", ["p1", "p2"])
def test_a_replays_hits_are_read_in_percent(monkeypatch, log, side):
    """2026-10-30 reviews: a review's damage evidence read our HP as exact, as in play, but a
    public replay shows both sides in percent -- Gliscor's Earthquake taking our 371-HP Great Tusk
    from 100/100 to 76/100 was 24 HP lost (every candidate's likelihood 0) and its full HP set to
    100 -- while a local replay has its saver's side exact (371/371 -> 281/371) and the other in
    percent. A replay's every HP is read in percent, whatever its units, from either player's
    view: the hit on us (p1's view) and by us (p2's)."""
    from alpha_poke.agents import damage_obs

    seen = []
    inner = damage_obs.likelihood

    def spy(hit, base, *a, **k):
        out = inner(hit, base, *a, **k)
        seen.append((hit, out))
        return out

    monkeypatch.setattr(damage_obs, "likelihood", spy)
    team = TEAM_FAST if side == "p1" else TEAM_FAST_P2
    _turn2(
        {side: parse_team(team)}, log=LOG_FAST if log == "percent" else LOG_FAST_EXACT, side=side
    )
    hits = [(h, out) for h, out in seen if h.move == "earthquake"]
    assert hits and all(h.by_us == (side == "p2") for h, _ in hits)
    assert all(h.pct and h.before == 100 and h.after == 76 for h, _ in hits), hits
    assert all(any(x > 0 for x in out) for _, out in hits), hits
