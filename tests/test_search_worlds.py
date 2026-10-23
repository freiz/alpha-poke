"""The search over several belief worlds (2026-10-21, the search review): the root's priors are
the network's priors averaged over the worlds -- the same for any order of the worlds (before:
the first world's alone, [A, B] = A's, [B, A] = B's)."""

from pathlib import Path

import numpy as np
import pytest

alpha_search = pytest.importorskip("alpha_search")
pe = pytest.importorskip("poke_engine")
pq = pytest.importorskip("pyarrow.parquet")

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "data/train/v72/runs/v6arch"
DATA = ROOT / "data/train/v72/hf-part11.parquet"

pytestmark = pytest.mark.skipif(not (MODEL / "best.safetensors").exists() or not DATA.exists(),
                                reason="needs the v6arch run and the v7.2 data")  # fmt: skip


def _row():
    t = pq.ParquetFile(DATA).read_row_group(0, columns=["state", "reveal", "rating_own",
                                                       "rating_opp", "turn", "history"])  # fmt: skip
    for r in t.to_pylist()[:200]:
        if r["turn"] > 3 and pe.State.from_string(r["state"]).side_two.pokemon[0].hp > 0:
            return r
    raise AssertionError("no row")


def _faster_foe(state: str) -> str:
    """The opponent's active twice as fast (its speed stat: the 18th field of a mon)."""
    s = pe.State.from_string(state)
    a = int(s.side_two.active_index)
    sides = state.split("/")
    mons = sides[1].split("=")
    f = mons[a].split(",")
    f[17] = str(int(f[17]) * 2)
    mons[a] = ",".join(f)
    sides[1] = "=".join(mons)
    return "/".join(sides)


def _root_prior(worlds: list[str], ctx) -> np.ndarray:
    bs = alpha_search.BatchSearch(worlds, [ctx] * len(worlds), seed=0, threads=1)
    bs.collect(8)
    values, logits, turns = bs.evaluate_cpu(str(MODEL))
    bs.apply(values, logits, turns)
    return np.array(bs.record()["prior"], dtype=np.float32)


def test_root_priors_do_not_depend_on_the_worlds_order():
    r = _row()
    ctx = (list(r["reveal"]), (r["rating_own"], r["rating_opp"]), r["turn"], r["history"])
    a, b = r["state"], _faster_foe(r["state"])
    pa, pb = _root_prior([a], ctx), _root_prior([b], ctx)
    assert np.abs(pa - pb).sum() > 1e-4, "the two worlds should give different priors"
    ab, ba = _root_prior([a, b], ctx), _root_prior([b, a], ctx)
    assert np.allclose(ab, ba, atol=1e-6)
    legal = pa >= 0
    assert np.allclose(ab[legal], (pa[legal] + pb[legal]) / 2, atol=1e-6)


def test_cpu_root_priors_do_not_depend_on_the_worlds_order():
    """The CPU search's root (alpha_search.root_priors: its priors as the search sets them)."""
    r = _row()
    ctx = (list(r["reveal"]), (r["rating_own"], r["rating_opp"]), r["turn"], r["history"])
    a, b = r["state"], _faster_foe(r["state"])
    pri = lambda ws: dict(alpha_search.root_priors(ws, str(MODEL), [ctx] * len(ws)))  # noqa: E731
    pa, pb, ab, ba = pri([a]), pri([b]), pri([a, b]), pri([b, a])
    assert sum(abs(pa[k] - pb[k]) for k in pa) > 1e-4
    for k in pa:
        assert abs(ab[k] - ba[k]) < 1e-6
        assert abs(ab[k] - (pa[k] + pb[k]) / 2) < 1e-6


def _other_moves(state: str) -> str:
    """The opponent's active with another first move (the worlds' opponents differ in options)."""
    s = pe.State.from_string(state)
    a = int(s.side_two.active_index)
    sides = state.split("/")
    mons = sides[1].split("=")
    f = mons[a].split(",")
    k = next(i for i, x in enumerate(f) if ";" in x and x.split(";")[1] in ("true", "false"))
    f[k] = "SPLASH;false;" + f[k].split(";")[2]
    mons[a] = ",".join(f)
    sides[1] = "=".join(mons)
    return "/".join(sides)


def test_root_evaluations_come_in_batches():
    """2026-10-22, the second search review: the root's evaluations (one per world) are handed out
    ``n`` at a time like the leaves (all 32 at once broke the batcher's row limit: 17 searches
    gave 1,088 rows); the root is ready only when every world's is back."""
    r = _row()
    ctx = (list(r["reveal"]), (r["rating_own"], r["rating_opp"]), r["turn"], r["history"])
    a, b = r["state"], _faster_foe(r["state"])
    worlds = [a, b] * 16
    bs = alpha_search.BatchSearch(worlds, [ctx] * 32, seed=0, threads=1)
    rows = []
    while bs.stats()[0] == 0 and len(rows) < 10:
        rows.append(bs.collect(8)["rows"])
        values, logits, turns = bs.evaluate_cpu(str(MODEL))
        bs.apply(values, logits, turns)
    assert rows[:4] == [16, 16, 16, 16], rows  # 8 worlds x (our view, theirs) a call
    pa, pb = _root_prior([a], ctx), _root_prior([b], ctx)
    legal = pa >= 0
    assert np.allclose(np.array(bs.record()["prior"], dtype=np.float32)[legal],
                       (pa[legal] + pb[legal]) / 2, atol=1e-5)  # fmt: skip


def test_root_noise_does_not_depend_on_the_worlds_order():
    """Root noise (self-play) is one draw over all the root's options in label order, the same for
    any order of the worlds whose opponents differ (before: the last world's options only)."""
    r = _row()
    ctx = (list(r["reveal"]), (r["rating_own"], r["rating_opp"]), r["turn"], r["history"])
    a, b = r["state"], _other_moves(r["state"])
    assert a != b

    def prior(ws):
        bs = alpha_search.BatchSearch(ws, [ctx] * len(ws), seed=3, threads=1, root_noise=(0.25, 10.0))
        bs.collect(8)
        bs.apply(*bs.evaluate_cpu(str(MODEL)))
        return np.array(bs.record()["prior"], dtype=np.float32)

    ab, ba = prior([a, b]), prior([b, a])
    assert np.allclose(ab, ba, atol=1e-6)
    assert not np.allclose(ab, _root_prior([a, b], ctx), atol=1e-4)  # (the noise is in)


def _struggling(state: str) -> str:
    """Side one's active with no PP left (Struggle), the foe's active at 1 HP: Struggle wins."""
    import re

    s = pe.State.from_string(state)
    sides = state.split("/")
    mons = sides[0].split("=")
    a = int(s.side_one.active_index)
    mons[a] = re.sub(r"([A-Z0-9]+);(true|false);\d+", r"\1;\2;0", mons[a])
    sides[0] = "=".join(mons)
    foe = sides[1].split("=")
    b = int(s.side_two.active_index)
    f = foe[b].split(",")
    f[6] = "1"  # (hp)
    foe[b] = ",".join(f)
    sides[1] = "=".join(foe)
    return "/".join(sides)


def test_struggle_has_a_slot_a_prior_and_its_visits():
    """2026-10-23 review: Struggle (the none option beside switches) had no action slot: a prior
    of 0, its visits left out of the record, self-play played a switch. Now move slot 0."""
    r = _row()
    ctx = (list(r["reveal"]), (r["rating_own"], r["rating_opp"]), r["turn"], r["history"])
    st = _struggling(r["state"])
    names = alpha_search.slot_names([st])[0]
    assert names[0] == "struggle" and any(n.startswith("switch ") for n in names), names
    bs = alpha_search.BatchSearch([st], [ctx], seed=0, threads=1, root_noise=(0.25, 10.0))
    for _ in range(100):
        bs.collect(16)
        values, logits, turns = bs.evaluate_cpu(str(MODEL))
        bs.apply(values, logits, turns)
    rec = bs.record()
    assert rec["legal"][0] and rec["names"][0] == "struggle"
    assert rec["prior"][0] > 0
    assert rec["visits"][0] == max(rec["visits"]), rec["visits"]  # (it wins at once)
