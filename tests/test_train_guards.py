"""Training on self-play data (2026-10-22 review): a batch of capped games only (won 0.5: no
remaining-turns label, all weights 0) gives a finite loss and gradient (0 / 0 was NaN)."""

import sys

import torch

sys.path.insert(0, "scripts")
from train_pv import aux_loss  # noqa: E402


def test_turns_loss_without_labels_is_finite():
    pred = torch.zeros(4, requires_grad=True)
    x = {"turns": torch.tensor([30, 40, 50, 60])}
    sp = torch.zeros(4, 12, 1)
    loss = aux_loss(
        {"turns": pred}, x, sp, torch.tensor([10, 10, 10, 10]), torch.zeros(4), ("turns",)
    )
    loss.backward()
    assert torch.isfinite(loss) and loss.item() == 0.0
    assert torch.isfinite(pred.grad).all()


def test_turns_loss_with_labels_is_unchanged():
    pred = torch.zeros(4, requires_grad=True)
    x = {"turns": torch.tensor([30, 40, 50, 60])}
    w = torch.tensor([1.0, 0.0, 1.0, 0.0])
    loss = aux_loss(
        {"turns": pred}, x, torch.zeros(4, 12, 1), torch.tensor([10] * 4), w, ("turns",)
    )
    y = torch.log1p(torch.tensor([20.0, 40.0]))
    want = torch.nn.functional.smooth_l1_loss(torch.zeros(2), y)
    assert torch.allclose(loss, want)
