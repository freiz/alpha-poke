"""Move-reveal model (negative evidence for hidden moves)."""

from types import SimpleNamespace

from alpha_poke.belief.reveal import LONG, RevealModel, first_use_rows


def _replay(seq):
    acts = [SimpleNamespace(kind="move", move=m, side="p1", mon="Gholdengo") for m in seq]
    acts.insert(1, SimpleNamespace(kind="switch", move=None, side="p1", mon="Gholdengo"))
    return SimpleNamespace(actions=acts)


def test_first_use_rows():
    rows = first_use_rows(_replay(["Nasty Plot", "Shadow Ball", "Shadow Ball", "Recover"]))
    assert ("Gholdengo", "", 4, None) in rows
    assert ("Gholdengo", "nastyplot", 4, 0) in rows
    assert ("Gholdengo", "shadowball", 4, 1) in rows
    assert ("Gholdengo", "recover", 4, 3) in rows


def test_fit_and_r():
    # 50 long stays; all carry and use Nasty Plot first; half of them carry Trick and use it at 5
    rows = []
    for i in range(50):
        seq = ["Nasty Plot"] + ["Shadow Ball"] * 4 + (["Trick"] if i % 2 else []) + ["Recover"] * 5
        rows += first_use_rows(_replay(seq))
    smogon = SimpleNamespace(
        species={"Gholdengo": SimpleNamespace(move_has={"Nasty Plot": 1.0, "Trick": 1.0})}
    )
    assert all(r[2] >= LONG for r in rows)
    model = RevealModel.fit(rows, smogon)
    assert model.r("gholdengo", "nastyplot", 1) == 1.0  # always used first
    assert model.r("gholdengo", "trick", 5) == 0.0  # never before the 6th action
    assert abs(model.r("gholdengo", "trick", 6) - 0.5) < 1e-9  # rho: only half ever click it
    assert model.r("gholdengo", "unknownmove", 8) == 0.0  # no data: no evidence
    assert model.r("gholdengo", "nastyplot", 0) == 0.0
