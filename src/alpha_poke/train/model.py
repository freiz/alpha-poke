"""Policy / value network on the Rust features (design D13; inputs: alpha_search.featurize).

Small MLP family, meant to run inside the search later (exported weights, Rust inference):
  * entity encoder shared by the 12 mons (NNUE-style feature transformer): embeddings of species,
    item, ability, tera type, types and the sum of the move embeddings, plus the dense features;
  * pooling: own active, opponent active, mean / max of each side's living bench;
  * trunk MLP over the pooled vectors and the global features;
  * value head: logit of P(side one wins);
  * policy head over the 14 action slots, pointer style: each move slot is scored from the trunk
    and that move's embedding (+ usability), once without and once with tera; each switch slot j
    from the trunk and entity j's encoding. Illegal slots are masked.
"""

import torch
from torch import nn

# dense feature indices (rust/alpha_search/src/features.rs)
D_ALIVE, D_ACTIVE, D_USABLE = 1, 2, slice(17, 21)


def mlp(*sizes: int) -> nn.Sequential:
    layers: list[nn.Module] = []
    for a, b in zip(sizes[:-1], sizes[1:], strict=True):
        layers += [nn.Linear(a, b), nn.ReLU()]
    return nn.Sequential(*layers[:-1])  # no activation after the last layer


class PolicyValueNet(nn.Module):
    def __init__(self, dims: dict, d_ent: int = 128, d_trunk: int = 256, d_global: int = 64):
        super().__init__()
        v_species, v_item, v_ability, v_type, v_move = dims["vocab"]
        self.species = nn.Embedding(v_species, 32)
        self.item = nn.Embedding(v_item, 16)
        self.ability = nn.Embedding(v_ability, 16)
        self.ptype = nn.Embedding(v_type, 8)  # not "type": nn.Module.type()
        self.move = nn.Embedding(v_move, 32)
        d_in = 32 + 16 + 16 + 3 * 8 + 32 + dims["dense"]
        self.entity = nn.Sequential(mlp(d_in, d_ent, d_ent), nn.ReLU())
        self.glob = nn.Sequential(nn.Linear(dims["global"], d_global), nn.ReLU())
        self.trunk = nn.Sequential(mlp(6 * d_ent + d_global, d_trunk, d_trunk), nn.ReLU())
        self.value = nn.Linear(d_trunk, 1)
        self.move_head = mlp(d_trunk + 32 + 1, 64, 2)  # (move, move + tera) per slot
        self.switch_head = mlp(d_trunk + d_ent, 64, 1)

    def forward(self, sparse, dense, glob, mask):
        """sparse long [B,12,10], dense float [B,12,23], glob float [B,G], mask bool [B,14] ->
        (policy logits [B,14] with -inf on illegal slots, value logit [B])."""
        moves = self.move(sparse[..., 6:10])  # [B,12,4,32]
        x = torch.cat(
            [
                self.species(sparse[..., 0]),
                self.item(sparse[..., 1]),
                self.ability(sparse[..., 2]),
                self.ptype(sparse[..., 3]),
                self.ptype(sparse[..., 4]),
                self.ptype(sparse[..., 5]),
                moves.sum(2),
                dense,
            ],
            dim=-1,
        )
        h = self.entity(x)  # [B,12,d]
        alive, active = dense[..., D_ALIVE], dense[..., D_ACTIVE]
        pooled = []
        for side in (slice(0, 6), slice(6, 12)):
            hs, act = h[:, side], active[:, side]
            bench = alive[:, side] * (1 - act)
            pooled.append((hs * act[..., None]).sum(1))
            pooled.append((hs * bench[..., None]).sum(1) / bench.sum(1, keepdim=True).clamp(min=1))
            pooled.append(hs.masked_fill(bench[..., None] == 0, -1e4).amax(1).clamp(min=0))
        t = self.trunk(torch.cat(pooled + [self.glob(glob)], dim=-1))  # [B,T]
        value = self.value(t).squeeze(-1)
        own_active = active[:, :6]
        am = (moves[:, :6] * own_active[..., None, None]).sum(1)  # [B,4,32]
        usable = (dense[:, :6, D_USABLE] * own_active[..., None]).sum(1)  # [B,4]
        tt = t[:, None, :].expand(-1, 4, -1)
        mh = self.move_head(torch.cat([tt, am, usable[..., None]], dim=-1))  # [B,4,2]
        sw = self.switch_head(torch.cat([t[:, None, :].expand(-1, 6, -1), h[:, :6]], dim=-1))
        logits = torch.cat([mh[..., 0], mh[..., 1], sw.squeeze(-1)], dim=-1)  # [B,14]
        return logits.masked_fill(~mask, float("-inf")), value
