"""Head-swap runs (2026-10-30, agents.gpu_net.make_hybrid): one network's policy with another's
value (its residual and remaining turns), for locating which head of a new network changes its
play -- here on the CPU with the tiny fixture network and a perturbed copy of it."""

import shutil
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file

from alpha_poke.agents.gpu_net import D, GpuNet, hybrid_of, make_hybrid

TINY = Path(__file__).resolve().parent / "fixtures" / "tiny_net"


def inputs(n: int = 3):
    e = D["entities"]
    args = (torch.zeros(n, e, D["sparse"], dtype=torch.int64), torch.rand(n, e, D["dense"]),
            torch.rand(n, D["global"]), torch.ones(n, D["actions"], dtype=torch.bool),
            torch.zeros(n, D["hist"], D["hist_sparse"], dtype=torch.int64),
            torch.rand(n, D["hist"], D["hist_dense"]))  # fmt: skip
    x = {"reveal": torch.zeros(n, e, dtype=torch.int64), "ent2": torch.rand(n, e, D["ent_extra"]),
         "glob2": torch.rand(n, D["global_extra"]), "ent3": torch.rand(n, e, D["ent_count"]),
         "glob3": torch.rand(n, D["global_count"]), "ent4": torch.rand(n, e, D["ent_new"]),
         "post": torch.rand(n, e, D["post"]), "turn": torch.ones(n, dtype=torch.int64),
         "rating": torch.zeros(n, 2, dtype=torch.int64)}  # fmt: skip
    return args, x, torch.rand(n) * 100


def test_a_hybrid_takes_each_head_from_its_network(tmp_path):
    other = tmp_path / "other"
    shutil.copytree(TINY, other)
    w = load_file(TINY / "best.safetensors")
    save_file(
        {k: v * 1.1 if v.is_floating_point() else v for k, v in w.items()},
        other / "best.safetensors",
    )
    hy = make_hybrid(str(tmp_path / "hy"), policy=str(other), value=str(TINY))
    assert (
        hybrid_of(hy) == {"policy": str(other), "value": str(TINY)} and hybrid_of(str(TINY)) is None
    )
    torch.manual_seed(0)
    args, x, ev = inputs()
    with torch.no_grad():
        nets = {k: GpuNet(r, device="cpu", graphs=False, compile=False) for k, r in
                (("tiny", str(TINY)), ("other", str(other)), ("hy", hy))}  # fmt: skip
        out = {k: n.forward(args, x, ev) for k, n in nets.items()}
    v_hy, logits_hy, turns_hy = out["hy"]
    assert torch.allclose(logits_hy, out["other"][1]) and not torch.allclose(
        logits_hy, out["tiny"][1]
    )
    assert torch.allclose(v_hy, out["tiny"][0]) and not torch.allclose(v_hy, out["other"][0])
    if turns_hy is not None:
        assert torch.allclose(turns_hy, out["tiny"][2])
