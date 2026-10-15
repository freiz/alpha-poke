"""Load a trained policy / value run (best.pt) as the PyTorch module (scripts, GPU search)."""

from pathlib import Path

import torch

from alpha_poke.train.model import TransformerPV

EMB = ("species.", "item.", "ability.", "ptype.", "move.")


def load_run(run: Path, device) -> torch.nn.Module:
    """The run's network in eval mode: the weights of ``best.safetensors`` (the exported ones,
    what the Rust inference loads: with ``--export last`` the last step, not ``best.pt``),
    sizes and options from ``best.pt``."""
    ck = torch.load(Path(run) / "best.pt", weights_only=False, map_location="cpu")
    exported = Path(run) / "best.safetensors"
    if exported.exists():
        from safetensors.torch import load_file

        names = set(ck["model"])  # the export drops the "emb." prefix of the shared tables
        ck["model"] = {("emb." + k if "emb." + k in names else k): v
                       for k, v in load_file(exported).items()}  # fmt: skip
    assert ck.get("arch") == "transformer", f"{run}: not a Transformer run"
    model = TransformerPV(ck["dims"], **ck["size"], history=ck.get("history", False),
                          mtp=ck.get("mtp", 0), feats=tuple(ck.get("feats", ())),
                          aux_heads=tuple(ck.get("aux_heads", ())),
                          mask_hidden=ck.get("mask_hidden", False),
                          arch=ck.get("arch_opts", {}))  # fmt: skip
    sd = {("emb." + k if k.startswith(EMB) else k): v for k, v in ck["model"].items()}
    model.residual = None
    if "residual" in sd:
        model.residual = torch.nn.Parameter(sd["residual"].clone())
    model.load_state_dict(sd)
    return model.to(device).eval()
