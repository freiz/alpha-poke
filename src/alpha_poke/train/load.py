"""Load a trained policy / value run (best.pt) as the PyTorch module (scripts, GPU search)."""

import json
from pathlib import Path

import torch

from alpha_poke.train.model import TransformerPV


def load_run(run: Path, device) -> torch.nn.Module:
    """The run's network in eval mode: the weights of ``best.safetensors`` (the exported ones,
    what the Rust inference loads: with ``--export last`` the last step, not ``best.pt``),
    sizes and options from ``best.pt``, or from ``config.json`` when the run has no ``best.pt``
    (a released model: scripts/fetch_model.py)."""
    run = Path(run)
    exported = run / "best.safetensors"
    if (run / "best.pt").exists():
        ck = torch.load(run / "best.pt", weights_only=False, map_location="cpu")
    else:
        ck = json.loads((run / "config.json").read_text())
        ck["model"] = None
    if exported.exists():
        from safetensors.torch import load_file

        ck["model"] = load_file(exported)
    assert ck.get("arch") == "transformer", f"{run}: not a Transformer run"
    model = TransformerPV(ck["dims"], **ck["size"], history=ck.get("history", False),
                          mtp=ck.get("mtp", 0), feats=tuple(ck.get("feats", ())),
                          aux_heads=tuple(ck.get("aux_heads", ())),
                          mask_hidden=ck.get("mask_hidden", False),
                          arch=ck.get("arch_opts", {}))  # fmt: skip
    # the export drops the "emb." prefix of the shared tables (the Rust loader's names)
    names = set(model.state_dict()) | {"residual"}
    sd = {("emb." + k if k not in names and "emb." + k in names else k): v
          for k, v in ck["model"].items()}  # fmt: skip
    model.residual = None
    if "residual" in sd:
        model.residual = torch.nn.Parameter(sd["residual"].clone())
    model.load_state_dict(sd)
    return model.to(device).eval()
