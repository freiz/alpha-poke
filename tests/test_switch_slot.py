from alpha_poke.agents.knowledge_player import switch_by_slot


def request(*mons):
    return {"side": {"pokemon": [{"ident": f"p2: {n}", "active": a} for n, a in mons]}}


def test_transformed_ditto_does_not_take_the_benched_name():
    # Ditto (active, transformed into Alomomola) first: Showdown would resolve "alomomola" to it
    req = request(("Ditto", True), ("Alomomola", False), ("Keldeo", False))
    assert switch_by_slot("/choose switch alomomola", req) == "/choose switch 2"
    assert switch_by_slot("/choose switch Keldeo", req) == "/choose switch 3"


def test_other_messages_unchanged():
    req = request(("Ditto", True), ("Alomomola", False))
    for m in ("/choose move earthquake", "/choose switch 2", "/choose default", "/team 123456"):
        assert switch_by_slot(m, req) == m
    assert switch_by_slot("/choose switch alomomola", None) == "/choose switch alomomola"
    assert switch_by_slot("/choose switch missing", req) == "/choose switch missing"


def test_nickname_from_ident():
    req = request(("Gholdengo", True), ("Big Fish", False))
    assert switch_by_slot("/choose switch big fish", req) == "/choose switch 2"
