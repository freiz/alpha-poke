"""Self-play records: a refused choice drops its record, a record only for the order sent,
several decisions of one (side, turn, kind) all converted (2026-10-11)."""

from types import SimpleNamespace

from alpha_poke.selfplay.player import SelfPlayPlayer, order_is


def order(o, tera=False):
    return SimpleNamespace(order=o, terastallize=tera)


def test_order_is():
    eq = SimpleNamespace(id="earthquake")
    assert order_is(order(eq), "earthquake")
    assert not order_is(order(eq), "earthquake-tera")
    assert order_is(order(eq, True), "earthquake-tera")
    assert not order_is(order(SimpleNamespace(id="struggle")), "bodypress")
    assert order_is(order(SimpleNamespace(species="greattusk")), "switch greattusk")
    assert not order_is(order(SimpleNamespace(species="kingambit")), "switch greattusk")


def player():
    p = SelfPlayPlayer.__new__(SelfPlayPlayer)  # no server: only the record bookkeeping
    p.records, p._record_request, p._n_requests, p.dropped_records = {}, {}, {}, 0
    return p


def test_refused_choice_drops_its_record():
    p = player()
    p._n_requests["b"] = 3
    p.records["b"] = [{"turn": 1}, {"turn": 2}]
    p._record_request["b"] = 3  # the last record answered request 3
    p._on_choice_rejected("b")
    assert p.records["b"] == [{"turn": 1}] and p.dropped_records == 1


def test_refused_unrecorded_choice_keeps_records():
    p = player()
    p._n_requests["b"] = 4  # request 4 was answered without a record (a single option)
    p.records["b"] = [{"turn": 1}]
    p._record_request["b"] = 3
    p._on_choice_rejected("b")
    assert p.records["b"] == [{"turn": 1}] and p.dropped_records == 0
