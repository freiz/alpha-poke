"""Self-play records across a stopped run (2026-10-22 review): a pair stopped after its decisions
and before its games row is played again as another attempt; the converter takes only the
records of the attempt the games row names, drops a row whose recorded action the log does not
show, and rejects a game whose records and log are out of step."""

import json
from dataclasses import dataclass, field

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
    stats = convert._convert_shard((tmp_path / "x.parquet", [(3, {"attempt": "b"}, "")], dec, 1, 0, 10))
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
