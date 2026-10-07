"""Which opponent prior predicts the opponent better (design D14-1 / D14-8)?

Usage: uv run --group train python scripts/eval_opp_prior.py --data v2m \
           --flip-run data/train/v2m/runs/v2m-transformer-h8-mtp0 \
           --mtp-run data/train/v2m/runs/v2m-transformer-h8-mtp3

On the anchor games (uploaded >= --since), for each position the opponent's actual action at
this decision (the ``future`` column, step 0) is scored under two priors over the opponent's
options in the position's world (side two of the state: revealed + belief-sampled set):
  * flip: the main policy head on side two's view (what the search uses now; the opponent's
    network sees our whole set, hidden parts included);
  * mtp: the MTP opponent head from our own view (one forward pass with the value and our
    prior; trained on what real opponents did without seeing our hidden information),
    projected onto the world's options: log P(kind) + log P(move id | move) per move slot (the
    tera variant gets the same score), log P(kind) + log P(switch-in | switch) per switch slot.
Tera is ignored (MTP does not predict it): 10 classes, 4 moves + 6 switches. Reports top-1 /
top-3 / NLL on the positions whose actual action is one of the world's options
(the rest -- a move missing from the sampled set -- no prior over the world's options can
cover), and that coverage.
"""

import argparse
import glob
import importlib.util
from pathlib import Path

import alpha_search
import numpy as np
import poke_engine as pe
import pyarrow.parquet as pq
import torch

_spec = importlib.util.spec_from_file_location("eval_pv", Path(__file__).with_name("eval_pv.py"))
eval_pv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_pv)

DIMS = alpha_search.feature_dims()


def flip_history(h: str) -> str:
    return ";".join("/".join(reversed(s.split("/", 1))) if "/" in s else s for s in h.split(";"))


def true_slot(state: str, act: str) -> int | None:
    """The opponent's (side two) action ``act`` ("m:ACTOR:MOVE", "t:..", "s:ACTOR:TO") as an
    action slot of side two in this world, or None if it is not one of its options."""
    kind, _, target = act.split(":")
    side = pe.State.from_string(state).side_two
    if kind in ("m", "t"):
        moves = [m.id for m in side.pokemon[int(side.active_index)].moves]
        return moves.index(target) + (4 if kind == "t" else 0) if target in moves else None
    ids = [p.id for p in side.pokemon]
    return 8 + ids.index(target) if target in ids else None


def tensors(states, hists, flip, device):
    e, s, d, g, a = DIMS["entities"], DIMS["sparse"], DIMS["dense"], DIMS["global"], DIMS["actions"]
    sp, de, gl, ma = alpha_search.featurize(states, flip=flip)
    hs, hd = alpha_search.featurize_history([flip_history(h) if flip else h for h in hists])
    k, (s1, s2) = DIMS["hist"], (DIMS["hist_sparse"], DIMS["hist_dense"])

    def t(buf, dt, shape, cast):
        return torch.from_numpy(np.frombuffer(buf, dt).reshape(shape).astype(cast)).to(device)

    n = len(states)
    return (
        t(sp, np.int32, (n, e, s), np.int64),
        t(de, np.float32, (n, e, d), np.float32),
        t(gl, np.float32, (n, g), np.float32),
        t(ma, np.uint8, (n, a), bool),
        t(hs, np.int32, (n, k, s1), np.int64),
        t(hd, np.float32, (n, k, s2), np.float32),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--flip-run", required=True)
    ap.add_argument("--mtp-run", required=True)
    ap.add_argument("--since", type=int, default=1776921722)
    a = ap.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    rows = []
    for f in sorted(glob.glob(f"data/train/{a.data}/*.parquet")):
        if not pq.read_metadata(f).num_rows:
            continue
        t = pq.read_table(f, columns=["state", "history", "future", "uploadtime"])
        keep = np.flatnonzero(t.column("uploadtime").to_numpy() >= a.since)
        rows += t.take(keep).to_pylist()
    data = []
    for r in rows:
        step0 = r["future"].split(";")[0] if r["future"] else ""
        opp = step0.split("/", 1)[1] if "/" in step0 else ""
        if opp:
            data.append((r["state"], r["history"], opp))
    flip_m = eval_pv.load_run(Path(a.flip_run), device)
    mtp_m = eval_pv.load_run(Path(a.mtp_run), device)
    assert getattr(mtp_m, "mtp", 0), "--mtp-run has no MTP heads"
    stats = {k: [] for k in ("flip", "mtp")}
    covered = 0
    for i in range(0, len(data), 8192):
        chunk = data[i : i + 8192]
        states, hists, acts = zip(*chunk, strict=True)
        slots = [true_slot(s, x) for s, x in zip(states, acts, strict=True)]
        with torch.no_grad():
            ft = tensors(list(states), list(hists), True, device)  # side two's view
            lf = flip_m(*ft)[0].float()
            sp, de, gl, ma, hs, hd = tensors(list(states), list(hists), False, device)
            kl, ml, sl = (x[:, 0, 1].float() for x in mtp_m(sp, de, gl, ma, hs, hd, aux=True)[2])
        omask = ft[3]  # side two's options
        lk, lm, ls = kl.log_softmax(-1), ml.log_softmax(-1), sl.log_softmax(-1)
        # the world's opponent moves (engine ids) for the move slots: its active entity's moves
        own_active = ft[1][:, :6, 2].long()
        mids = (ft[0][:, :6, 6:10] * own_active[..., None]).sum(1)  # [B,4]
        move_s = lk[:, 1:2] + lm.gather(1, mids)  # [B,4]
        # compare without tera (MTP does not predict it): 10 classes = 4 moves (with or without
        # tera, probabilities summed) + 6 switches
        m10 = torch.cat([omask[:, :4] | omask[:, 4:8], omask[:, 8:]], dim=1)
        lmtp = torch.cat([move_s, lk[:, 2:3] + ls], dim=1).masked_fill(~m10, float("-inf"))
        pf = lf.softmax(-1)
        lflip = torch.cat([pf[:, :4] + pf[:, 4:8], pf[:, 8:]], dim=1).log()
        for name, lg in (("flip", lflip), ("mtp", lmtp)):
            logp = lg.log_softmax(-1)
            top = lg.topk(3, dim=-1).indices
            for j, sl_ in enumerate(slots):
                if sl_ is None or not omask[j, sl_]:
                    continue
                c = sl_ % 4 if sl_ < 8 else sl_ - 4
                stats[name].append(
                    (float(top[j, 0] == c), float((top[j] == c).any()), -float(logp[j, c]))
                )
        covered += sum(1 for j, sl_ in enumerate(slots) if sl_ is not None and omask[j, sl_])
    print(f"{len(data)} positions with an opponent action; covered by the world's options: "
          f"{covered / len(data):.1%}")  # fmt: skip
    for name, v in stats.items():
        x = np.array(v)
        print(f"{name:5s} top-1 {x[:, 0].mean():.1%}  top-3 {x[:, 1].mean():.1%}  "
              f"NLL {x[:, 2].mean():.3f}  (n={len(x)})")  # fmt: skip


if __name__ == "__main__":
    main()
