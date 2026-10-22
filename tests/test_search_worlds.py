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
