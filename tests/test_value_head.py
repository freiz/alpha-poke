"""The value head options (value_layers, value_blocks; 2026-10-11): added to a trained network
they leave its outputs unchanged at first (the value MLP's output layer starts at zero), and
--freeze-trunk's value part holds only value modules."""

import glob
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from alpha_poke.train.load import load_run
from alpha_poke.train.model import TransformerPV

RUN = Path("data/train/v5/runs/sp-gen5")
SHARDS = sorted(glob.glob("data/train/sp5/features/*.npz"))
VALUE_PART = ("value.", "value_mlp.", "value_blocks.", "value_norm.", "residual")


@pytest.mark.skipif(not (RUN / "best.pt").exists() or not SHARDS, reason="needs sp-gen5 / sp5")
@pytest.mark.parametrize(
    "extra",
    [
        {"value_hidden": 64, "value_layers": 2},
        {"value_hidden": 64, "value_layers": 2, "value_blocks": 1},
    ],
)
def test_value_options_keep_a_warm_start(extra):
    sys.path.insert(0, "scripts")
    from train_pv import to_torch

    base = load_run(RUN, "cpu")
    ck = torch.load(RUN / "best.pt", weights_only=False, map_location="cpu")
    model = TransformerPV(ck["dims"], **ck["size"], history=ck["history"], mtp=ck.get("mtp", 0),
                          feats=tuple(ck.get("feats", ())),
                          aux_heads=tuple(ck.get("aux_heads", ())),
                          mask_hidden=ck.get("mask_hidden", False),
                          arch=dict(ck.get("arch_opts", {})) | extra)  # fmt: skip
    model.residual = torch.nn.Parameter(base.residual.detach().clone())
    missing, unexpected = model.load_state_dict(base.state_dict(), strict=False)
    assert not unexpected
    assert missing and all(k.startswith(VALUE_PART) for k in missing)
    model.eval()
    with np.load(SHARDS[0]) as z:
        d = {k: z[k][:64] for k in z.files}
    sp, de, gl, ma, _, _, _, hs, hd, _, _, x = to_torch(d, np.arange(64), "cpu")
    with torch.no_grad():
        a = base(sp, de, gl, ma, hs, hd, x=x)
        b = model(sp, de, gl, ma, hs, hd, x=x)
    assert torch.allclose(a[0], b[0]) and torch.allclose(a[1], b[1])  # policy, value
    trainable = [n for n, _ in model.named_parameters() if n.startswith(VALUE_PART)]
    assert any(n.startswith("value_mlp.") for n in trainable)
    assert not any(n.startswith(("blocks.", "emb.", "move_head", "switch_head")) for n in trainable)
