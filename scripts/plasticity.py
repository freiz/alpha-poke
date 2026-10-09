"""Plasticity diagnostics of trained networks (design TODO, 2026-10-09): on the same real
positions, per network
  * dormant units (ReDo, Sokar et al. 2023): a hidden unit's mean |activation| over the batch,
    divided by the layer's mean; dormant if <= tau (0.025, and 0.1). Feed-forward hidden units
    of every block (SwiGLU: silu(gate) * value) and the hidden ReLU layer of the move / switch
    heads;
  * effective rank (srank, Kumar et al. 2021) of the trunk's output features: the global token
    and the entity tokens, the smallest k with 99% of the singular-value mass;
  * the parameter norm.
A freshly initialised network of the same architecture is the reference (no training).

  uv run --group train python scripts/plasticity.py --runs data/train/v5/runs/v5-glu ...
"""

import argparse
import json
from pathlib import Path

import alpha_search
import numpy as np
import torch

from alpha_poke.agents.gpu_net import GpuNet
from alpha_poke.train.load import load_run
from alpha_poke.train.model import TransformerPV


def batches(decisions: str, n: int):
    """GpuNet input batches of n root positions (both views) from self-play records."""
    import glob

    recs = []
    for f in sorted(glob.glob(decisions)):
        for i, line in enumerate(open(f)):
            if i % 7 == 0 and len(recs) < n:
                recs.append(json.loads(line))
    out = []
    for k in range(0, len(recs), 256):
        chunk = recs[k : k + 256]
        searches = [alpha_search.BatchSearch(
            [d["state"]] * 4,
            [(d["reveal"], tuple(d["ratings"]), d["ctx_turn"], d["history"])] * 4,
            seed=j, threads=1, vl=1) for j, d in enumerate(chunk)]  # fmt: skip
        b, _, _ = alpha_search.collect_many(searches, 1, 4)
        out.append(b)
    return out


def srank(x: np.ndarray, delta: float = 0.01) -> int:
    s = np.linalg.svd(x - x.mean(0), compute_uv=False)
    c = np.cumsum(s) / s.sum()
    return int(np.searchsorted(c, 1 - delta) + 1)


@torch.no_grad()
def diagnose(model, net: GpuNet, data: list) -> dict:
    acts: dict[str, list] = {}
    feats: dict[str, list] = {"global": [], "entities": []}

    def pre(name):  # the FFN hidden units: the input of w3
        return lambda _m, inp: acts.setdefault(name, []).append(inp[0].abs().flatten(0, -2))

    def post(name):  # the heads' hidden ReLU layer
        return lambda _m, _inp, out: acts.setdefault(name, []).append(out.abs().flatten(0, -2))

    hooks = [blk.w3.register_forward_pre_hook(pre(f"ffn{i}")) for i, blk in enumerate(model.blocks)]
    hooks += [
        getattr(model, n)[1].register_forward_hook(post(n)) for n in ("move_head", "switch_head")
    ]

    def trunk(_m, _inp, out):  # returns None: the output stays as it is
        feats["global"].append(out[:, 12])
        feats["entities"].append(out[:, :12].flatten(0, 1))

    hooks.append(model.norm.register_forward_hook(trunk))
    for b in data:
        args, x, _ = net.tensors(b)
        model(*args, x=x)
    for h in hooks:
        h.remove()
    out = {}
    for name, a in acts.items():
        score = torch.cat(a).mean(0)
        score = score / score.mean().clamp_min(1e-12)
        out[name] = {"units": len(score),
                     "dormant_0.025": round(float((score <= 0.025).float().mean()), 4),
                     "dormant_0.1": round(float((score <= 0.1).float().mean()), 4)}  # fmt: skip
    for name, f in feats.items():
        out[f"srank_{name}"] = srank(torch.cat(f).float().cpu().numpy())
    out["param_norm"] = round(
        float(sum(p.float().norm() ** 2 for p in model.parameters()) ** 0.5), 2
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--decisions", default="data/selfplay/gen0/decisions-w*.jsonl")
    ap.add_argument("--n", type=int, default=2048)
    a = ap.parse_args()
    torch.manual_seed(0)
    first = GpuNet(a.runs[0], device="cpu", graphs=False)
    data = batches(a.decisions, a.n)
    print(f"{sum(b['rows'] for b in data)} rows")
    # reference: the first run's architecture, freshly initialised
    ck = torch.load(Path(a.runs[0]) / "best.pt", weights_only=False, map_location="cpu")
    fresh = TransformerPV(ck["dims"], **ck["size"], history=ck.get("history", False),
                          mtp=ck.get("mtp", 0), feats=tuple(ck.get("feats", ())),
                          aux_heads=tuple(ck.get("aux_heads", ())),
                          arch=ck.get("arch_opts", {})).eval()  # fmt: skip
    fresh.residual = None
    results = {"fresh init": diagnose(fresh, first, data)}
    for run in a.runs:
        results[Path(run).name] = diagnose(load_run(Path(run), "cpu").float(), first, data)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
