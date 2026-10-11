"""Child-node value targets on disk (design TODO "方案乙"): the root's well-visited children of a
search (``BatchSearch.children``: their network inputs, side one's view, and their search
values), one row per child, in compact types as the feature caches. Written by
scripts/child_targets.py (roots searched again) and by self-play (exported right after each full
search: no extra search, the full belief worlds); read by train_pv ``--child-data``.

Arrays: the network inputs (``specs``) and root (an id per root search: siblings share it),
our / their (action slots), visits, value (side one = the player to act at the root), q (the
root's value)."""

from pathlib import Path

import numpy as np

DIR = Path("data/train/children")


def specs(D: dict) -> list:
    """(key, dtype in the batch, stored dtype, shape after the rows) of the network inputs."""
    e = D["entities"]
    return [("sparse", np.int32, np.int16, (e, D["sparse"])),
            ("dense", np.float32, np.float16, (e, D["dense"])),
            ("global", np.float32, np.float16, (D["global"],)),
            ("mask", np.uint8, np.uint8, (D["actions"],)),
            ("hsparse", np.int32, np.int16, (D["hist"], D["hist_sparse"])),
            ("hdense", np.float32, np.float16, (D["hist"], D["hist_dense"])),
            ("reveal", np.uint8, np.uint8, (e,)),
            ("ent2", np.float32, np.float16, (e, D["ent_extra"])),
            ("glob2", np.float32, np.float16, (D["global_extra"],)),
            ("turn", np.int32, np.int16, ()),
            ("rating", np.int32, np.int16, (2,)),
            ("eval", np.float32, np.float32, ())]  # fmt: skip


class Buffer:
    """Children of many searches, written as one file at a time."""

    def __init__(self):
        import alpha_search

        self.specs = specs(alpha_search.feature_dims())
        self.clear()

    def clear(self) -> None:
        self.cols: dict = {key: [] for key, *_ in self.specs}
        self.meta: dict = {k: [] for k in ("root", "our", "their", "visits", "value", "q")}

    def __len__(self) -> int:
        return len(self.meta["root"])

    def add(self, root: int, batch: dict, kids: list, q: float) -> None:
        """One search's export: ``batch`` its children's inputs (BatchSearch.children), ``kids``
        their (our, their, visits, value)."""
        n = batch["rows"]
        if n == 0:
            return
        assert n == len(kids), (n, len(kids))
        for key, raw, _, shape in self.specs:
            self.cols[key].append(np.frombuffer(batch[key], raw).reshape((n, *shape)))
        for our, their, visits, value in kids:
            self.meta["root"].append(root)
            self.meta["our"].append(our)
            self.meta["their"].append(their)
            self.meta["visits"].append(visits)
            self.meta["value"].append(value)
            self.meta["q"].append(q)

    def save(self, path: Path) -> int:
        """Write the buffered children (atomically) and clear; returns the rows written."""
        n = len(self)
        if n == 0:
            return 0
        arrays = {key: np.concatenate(self.cols[key]).astype(store)
                  for key, _, store, _ in self.specs}  # fmt: skip
        arrays |= {"root": np.asarray(self.meta["root"], np.int64),
                   "our": np.asarray(self.meta["our"], np.int8),
                   "their": np.asarray(self.meta["their"], np.int8),
                   "visits": np.asarray(self.meta["visits"], np.int32),
                   "value": np.asarray(self.meta["value"], np.float32),
                   "q": np.asarray(self.meta["q"], np.float32)}  # fmt: skip
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, **arrays)
        tmp.rename(path)
        self.clear()
        return n
