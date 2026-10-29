"""The value hidden layer (``value_hidden``): added to a trained network it leaves its outputs
unchanged at first (the value MLP's output layer starts at zero)."""

import json
import sys
from pathlib import Path

import numpy as np
import torch

from alpha_poke.train.load import load_run
from alpha_poke.train.model import TransformerPV

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# a randomly initialized network with the released one's inputs, 64 feature rows of the v75 data
# (tests/make_fixture_data.py)
RUN = FIXTURES / "tiny_net"
SHARD = FIXTURES / "features_v75.npz"


def test_value_hidden_keeps_a_warm_start():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from train_pv import to_torch

    base = load_run(RUN, "cpu")
    ck = json.loads((RUN / "config.json").read_text())
    model = TransformerPV(ck["dims"], **ck["size"], history=ck["history"], mtp=ck.get("mtp", 0),
                          feats=tuple(ck.get("feats", ())),
                          aux_heads=tuple(ck.get("aux_heads", ())),
                          mask_hidden=ck.get("mask_hidden", False),
                          arch=dict(ck.get("arch_opts", {})) | {"value_hidden": 64})  # fmt: skip
    model.residual = torch.nn.Parameter(base.residual.detach().clone())
    missing, unexpected = model.load_state_dict(base.state_dict(), strict=False)
    assert not unexpected and missing and all(k.startswith("value_mlp.") for k in missing)
    model.eval()
    with np.load(SHARD) as z:
        d = {k: z[k][:64] for k in z.files}
    sp, de, gl, ma, _, _, _, hs, hd, _, _, x = to_torch(d, np.arange(64), "cpu")
    with torch.no_grad():
        a = base(sp, de, gl, ma, hs, hd, x=x)
        b = model(sp, de, gl, ma, hs, hd, x=x)
    assert torch.allclose(a[0], b[0]) and torch.allclose(a[1], b[1])  # policy, value
