"""Load a trained policy / value run (best.pt) as the PyTorch module (scripts, GPU search)."""

from pathlib import Path

import torch

from alpha_poke.train.model import PolicyValueNet, TransformerPV

EMB = ("species.", "item.", "ability.", "ptype.", "move.")


def load_run(run: Path, device) -> torch.nn.Module:
    """The run's best checkpoint in eval mode (v1 checkpoints: the MLP without history, the
    embedding tables at the top level)."""
    ck = torch.load(Path(run) / "best.pt", weights_only=False, map_location="cpu")
    arch, history = ck.get("arch", "mlp"), ck.get("history", False)
    cls = TransformerPV if arch == "transformer" else PolicyValueNet
    kw = {}
    if arch == "transformer":
        kw = {"mtp": ck.get("mtp", 0), "feats": tuple(ck.get("feats", ())),
              "aux_heads": tuple(ck.get("aux_heads", ())),
              "mask_hidden": ck.get("mask_hidden", False)}  # fmt: skip
    model = cls(ck["dims"], **ck["size"], history=history, **kw)
    sd = {("emb." + k if k.startswith(EMB) else k): v for k, v in ck["model"].items()}
    model.residual = None
    if "residual" in sd:
        model.residual = torch.nn.Parameter(sd["residual"].clone())
    model.load_state_dict(sd)
    return model.to(device).eval()
