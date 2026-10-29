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


def test_foe_move_weights_by_move_id():
    """The opponent's root visits by move id (2026-10-22 review: its move still to come after our
    pivot is drawn from them): slots 0-3 its moves, 4-7 the same with tera, switches left out."""
    from types import SimpleNamespace as N

    from alpha_poke.selfplay.player import foe_move_weights

    mon = N(moves=[N(id="makeitrain"), N(id="nastyplot"), N(id="shadowball"), N(id="none")])
    state = N(side_two=N(active_index="0", pokemon=[mon]))
    visits = [10, 0, 5, 0, 3, 0, 0, 0, 7, 0, 0, 0, 0, 0]
    assert foe_move_weights(state, {"opp_visits": visits}) == {
        "makeitrain": 13.0,
        "shadowball": 5.0,
    }
