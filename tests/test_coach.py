"""Game reviews (alpha_poke.coach, 2026-10-29) on a fixture replay with the tiny network: every
decision of the player searched, its option named as the state's options, the numbers in range;
the log's events with the sides as ME / OPP; the write-up's move check."""

import gzip
import json
import random
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
    means with standard errors, the loss with the two errors combined."""
    rep = review(game, "p1", BeliefModel.load(), str(FIXTURES / "tiny_net"), worlds=2, ms=20,
                 threads=1, log=lambda *_: None, repeats=3)  # fmt: skip
    ds = rep["decisions"]
    assert rep["settings"]["repeats"] == 3 and all(d["repeats"] == 3 for d in ds)
    assert all(
        abs(sum(o[1] for o in d["options"]) - 1) < 0.05 or len(d["options"]) >= 6 for d in ds
    )
    assert any(d["value_se"] is not None for d in ds)
    assert all(len(o) == 4 for d in ds for o in d["options"])


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
    assert verdict(shunned | {"loss": 0.02, "loss_se": 0.014}) == "mild"  # within the noise
    assert (
        verdict(shunned | {"loss": 0.02, "loss_se": 0.014}, z=1) == "bad"
    )  # (stricter on noise: 1 error)
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
            r["url"] == j["url"] for r in requests.get(base + "/api/reviews", timeout=5).json()
        )
        # review again (the page's button): the game, the player and the team kept with it
        name = j["url"].split("/")[2]
        redo = requests.get(f"{base}/api/redo-info?review={name}", timeout=5).json()
        assert redo["team"] is True and redo["settings"]["repeats"] == 2 and redo["decisions"] >= 1
        again = requests.post(base + "/api/redo", json={"review": name, "custom": {"repeats": 1, "seconds": 0.2,
                              "worlds": 4}, "parallel": 1}, timeout=30).json()["job"]  # fmt: skip
        assert wait(again)["url"] == j["url"]
        rep = json.loads((app.COACH / name / "review.json").read_text(encoding="utf-8"))
        assert rep["settings"]["team"] is True and rep["settings"]["repeats"] == 1
        # (a review saved before its replay was kept: the log in its page)
        (app.COACH / name / "replay.json").unlink()
        assert requests.get(f"{base}/api/redo-info?review={name}", timeout=5).status_code == 200
        assert app.stored(name)[1]["log"] == game["log"]
        assert '"side": "p2"' in requests.get(base + j["url"], timeout=5).text
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
