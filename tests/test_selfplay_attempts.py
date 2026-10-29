"""Self-play records across a stopped run (2026-10-22 review): a pair stopped after its decisions
and before its games row is played again as another attempt; the converter takes only the
records of the attempt the games row names, drops a row whose recorded action the log does not
show, and rejects a game whose records and log are out of step."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from alpha_poke.selfplay import convert


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_load_gen_takes_the_named_attempts_log(tmp_path):
    _write(tmp_path / "games-w0.jsonl", [{"pair": 3, "attempt": "b"}])
    _write(tmp_path / "logs-w0.jsonl", [{"pair": 3, "attempt": "a", "log": "OLD"},
                                         {"pair": 3, "attempt": "b", "log": "NEW"}])  # fmt: skip
    # (a games line cut by a stop is skipped)
    with open(tmp_path / "games-w0.jsonl", "a") as f:
        f.write('{"pair": 4, "att')
    games, logs = convert.load_gen(tmp_path)
    assert set(games) == {3} and logs == {3: "NEW"}


def test_shard_passes_the_named_attempts_decisions(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(convert, "convert_game",
                        lambda pair, game, log, decisions, *a, **k: seen.setdefault(pair, decisions) and [])  # fmt: skip
    import alpha_poke.agents.belief_state as bs

    monkeypatch.setattr(bs.BeliefModel, "load", staticmethod(lambda *a, **k: None))
    dec = tmp_path / "0000.jsonl"
    _write(dec, [{"game": 3, "turn": 1, "attempt": "a"}, {"game": 3, "turn": 1, "attempt": "b"},
                 {"game": 3, "turn": 2, "attempt": "b"}])  # fmt: skip
    with open(dec, "a") as f:
        f.write('{"game": 3, "tu')  # (cut)
    stats = convert._convert_shard(
        (tmp_path / "x.parquet", [(3, {"attempt": "b"}, "")], dec, 1, 0, 10)
    )
    assert [d["turn"] for d in seen[3]] == [1, 2] and all(d["attempt"] == "b" for d in seen[3])
    assert stats["broken_decision_lines"] == 1


@dataclass
class _Pos:
    side: str
    turn: int
    state: str
    action: int
    kind: int = 0
    extra: dict = field(default_factory=dict)


def _game(monkeypatch, logged: list[str], recorded: list[str]):
    """convert_game on positions whose logged action names are ``logged``, decisions whose
    recorded ones are ``recorded``."""
    pos = [_Pos("p1", t + 1, f"s{t}", 0) for t in range(len(logged))]
    monkeypatch.setattr(convert, "positions_from_replay", lambda *a, **k: pos)
    monkeypatch.setattr(convert.alpha_search, "slot_names",
                        lambda states: [[logged[int(states[0][1:])]] + [""] * 13])  # fmt: skip
    decs = [{"side": "p1", "turn": t + 1, "kind": 0, "names": [n] + [""] * 13, "slot": 0,
             "visits": [1] + [0] * 13, "full": True, "state": "x", "history": "", "reveal": [],
             "ratings": [0, 0], "ctx_turn": t + 1, "won": True, "q": 0.5}
            for t, n in enumerate(recorded)]  # fmt: skip
    stats = {k: 0 for k in ("matched", "unmatched_positions", "action_checked", "action_agree",
                            "action_rows_dropped", "rejected_games", "capped_rows",
                            "loop_policy_dropped", "unmatched_decisions")}  # fmt: skip
    rows = convert.convert_game(1, {"battle": "b", "capped": False}, "", decs, None, 1, 0, stats)
    return rows, stats


def test_a_disagreeing_action_drops_its_row(monkeypatch):
    names = ["earthquake", "stealthrock", "swordsdance", "scaleshot", "earthquake"]
    rows, stats = _game(monkeypatch, names, names[:1] + ["earthquake"] + names[2:])
    assert len(rows) == 4 and stats["action_rows_dropped"] == 1 and stats["rejected_games"] == 0


def test_records_out_of_step_reject_the_game(monkeypatch):
    rows, stats = _game(monkeypatch, ["earthquake", "stealthrock", "swordsdance"],
                        ["stealthrock", "swordsdance", "earthquake"])  # fmt: skip
    assert rows == [] and stats["rejected_games"] == 1


def test_same_action_by_species_and_unnamed():
    """A switch names a mon by its forme of the moment on either side (Mimikyu / Mimikyu-Busted,
    Ogerpon's tera forme): the same action; no name on the log's side: not checked."""
    assert convert.same_action("switch mimikyu", "switch mimikyubusted")
    assert convert.same_action("switch ogerponwellspringtera", "switch ogerponwellspring")
    assert not convert.same_action("switch zapdos", "switch gliscor")
    assert not convert.same_action("earthquake", "stealthrock")
    assert convert.same_action("", "nastyplot") is None


FIXTURE = Path(__file__).parent / "fixtures" / "selfplay_game.json.gz"


def _records(attempt):
    import gzip

    x = json.loads(gzip.open(FIXTURE, "rt").read())
    g, lg, ds = x["game"] | {"attempt": attempt}, x["log"] | {"attempt": attempt}, x["decisions"]
    return g, lg, [d | {"attempt": attempt} for d in ds]


def _attempt(gen, attempt, upto=None):
    """One attempt's records in the runner's order (decisions, log, games); ``upto``: stopped at
    that point -- (file, "cut": in the middle of its last line / "before": not written)."""
    from alpha_poke.selfplay.runner import append_lines

    g, lg, ds = _records(attempt)
    for name, lines in (("decisions", [json.dumps(d) for d in ds]), ("logs", [json.dumps(lg)]),
                        ("games", [json.dumps(g)])):  # fmt: skip
        path = gen / f"{name}-w0.jsonl"
        if upto == (name, "before"):
            return
        if upto == (name, "cut"):
            append_lines(path, lines[:-1])
            with open(path, "a") as f:
                f.write(lines[-1][: len(lines[-1]) // 2])  # (no newline: the stop)
            return
        append_lines(path, lines)


@pytest.mark.skipif(not FIXTURE.exists(), reason="needs the fixture")
@pytest.mark.parametrize("upto", [("decisions", "cut"), ("logs", "before"), ("logs", "cut"),
                                  ("games", "before"), ("games", "cut")])  # fmt: skip
def test_a_stop_at_any_write_then_resume(tmp_path, upto):
    """A run stopped at every write boundary (2026-10-22 review), the pair played again: the
    resume sees it not done, the second attempt is appended after the cut line, the conversion
    gives the rows of the clean run."""
    from alpha_poke.selfplay import runner

    clean, cut = tmp_path / "clean", tmp_path / "cut"
    clean.mkdir()
    cut.mkdir()
    _attempt(clean, "b")
    pair = json.loads(next((clean / "games-w0.jsonl").open()))["pair"]
    want = convert.convert(clean, clean / "out", 9, procs=1, log=lambda *a: None)
    _attempt(cut, "a", upto)
    assert pair not in runner.done_pairs(cut)
    assert runner.played_models(cut) <= runner.played_models(clean)
    _attempt(cut, "b")  # (the resume plays the pair again)
    assert pair in runner.done_pairs(cut)
    got = convert.convert(cut, cut / "out", 9, procs=1, log=lambda *a: None)
    for k in ("positions", "matched", "action_checked", "action_agree", "games"):
        assert got.get(k) == want.get(k), (k, got, want)
    a = pq.read_table(clean / "out" / "shard-0000.parquet").to_pylist()
    b = pq.read_table(cut / "out" / "shard-0000.parquet").to_pylist()
    assert [(r["turn"], r["action"], r["pi"], r["history"]) for r in a] == \
        [(r["turn"], r["action"], r["pi"], r["history"]) for r in b]  # fmt: skip


@pytest.mark.skipif(not FIXTURE.exists(), reason="needs the fixture")
def test_a_reconversion_replaces_the_earlier_shards(tmp_path):
    """The fifth review: a reconversion with no rows (or fewer shards) left the earlier shards
    behind, read by the training; the output directory is now replaced whole."""
    gen = tmp_path / "gen"
    gen.mkdir()
    _attempt(gen, "b")
    out = tmp_path / "out"
    convert.convert(gen, out, 9, procs=1, log=lambda *a: None)
    assert list(out.glob("shard-*.parquet"))
    (out / "shard-0007.parquet").write_bytes(b"stale")  # (a tail shard of a bigger run)
    for f in gen.glob("games-w*.jsonl"):
        f.write_text("")  # (no games now)
    stats = convert.convert(gen, out, 9, procs=1, log=lambda *a: None)
    assert stats.get("positions", 0) == 0
    assert not list(out.glob("shard-*.parquet")), list(out.iterdir())
    assert (out / "convert.json").exists()
