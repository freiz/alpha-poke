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
v2 (design D13): ``history=True`` adds the last decision steps (alpha_search.featurize_history):
each step's own / opponent actor species, move and switch-in species (embeddings shared with the
entity encoder) + flags -> a step encoding; the steps, in recency order, -> one vector for the
trunk. ``TransformerPV``: the same inputs as tokens (12 entities, 1 global, the history steps)
through a small pre-norm Transformer; value and policy read the global token, switch slots the
own entity tokens.
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


class Embeddings(nn.Module):
    """Entity inputs (ids -> embeddings + dense) and history step inputs, shared tables."""

    def __init__(self, dims: dict):
        super().__init__()
        v_species, v_item, v_ability, v_type, v_move = dims["vocab"]
        self.species = nn.Embedding(v_species, 32)
        self.item = nn.Embedding(v_item, 16)
        self.ability = nn.Embedding(v_ability, 16)
        self.ptype = nn.Embedding(v_type, 8)  # not "type": nn.Module.type()
        self.move = nn.Embedding(v_move, 32)
        self.d_entity = 32 + 16 + 16 + 3 * 8 + 32 + dims["dense"]
        self.d_step = 6 * 32 + dims.get("hist_dense", 7)

    def entities(self, sparse, dense):
        """-> (entity inputs [B,12,d_entity], move embeddings [B,12,4,32])"""
        moves = self.move(sparse[..., 6:10])
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
        return x, moves

    def steps(self, hsparse, hdense):
        """hsparse long [B,S,6] (own actor, own move, own switch-in, the same for the
        opponent), hdense float [B,S,7] -> step inputs [B,S,d_step]"""
        e = [
            self.species(hsparse[..., 0]),
            self.move(hsparse[..., 1]),
            self.species(hsparse[..., 2]),
            self.species(hsparse[..., 3]),
            self.move(hsparse[..., 4]),
            self.species(hsparse[..., 5]),
        ]
        return torch.cat(e + [hdense], dim=-1)


class PolicyValueNet(nn.Module):
    def __init__(
        self,
        dims: dict,
        d_ent: int = 128,
        d_trunk: int = 256,
        d_global: int = 64,
        history: bool = False,
        d_hist: int = 64,
    ):
        super().__init__()
        self.emb = Embeddings(dims)
        self.entity = nn.Sequential(mlp(self.emb.d_entity, d_ent, d_ent), nn.ReLU())
        self.glob = nn.Sequential(nn.Linear(dims["global"], d_global), nn.ReLU())
        self.history = history
        d_h = 0
        if history:
            self.step = nn.Sequential(mlp(self.emb.d_step, 64, 48), nn.ReLU())
            self.hist = nn.Sequential(nn.Linear(dims["hist"] * 48, d_hist), nn.ReLU())
            d_h = d_hist
        self.trunk = nn.Sequential(mlp(6 * d_ent + d_global + d_h, d_trunk, d_trunk), nn.ReLU())
        self.value = nn.Linear(d_trunk, 1)
        self.move_head = mlp(d_trunk + 32 + 1, 64, 2)  # (move, move + tera) per slot
        self.switch_head = mlp(d_trunk + d_ent, 64, 1)

    def forward(self, sparse, dense, glob, mask, hsparse=None, hdense=None):
        """sparse long [B,12,10], dense float [B,12,23], glob float [B,G], mask bool [B,14]
        (+ history hsparse long [B,S,6], hdense float [B,S,7]) -> (policy logits [B,14] with
        -inf on illegal slots, value logit [B])."""
        x, moves = self.emb.entities(sparse, dense)
        h = self.entity(x)  # [B,12,d]
        alive, active = dense[..., D_ALIVE], dense[..., D_ACTIVE]
        pooled = []
        for side in (slice(0, 6), slice(6, 12)):
            hs, act = h[:, side], active[:, side]
            bench = alive[:, side] * (1 - act)
            pooled.append((hs * act[..., None]).sum(1))
            pooled.append((hs * bench[..., None]).sum(1) / bench.sum(1, keepdim=True).clamp(min=1))
            pooled.append(hs.masked_fill(bench[..., None] == 0, -1e4).amax(1).clamp(min=0))
        if self.history:
            st = self.step(self.emb.steps(hsparse, hdense))  # [B,S,48]
            pooled.append(self.hist(st.flatten(1)))
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


class TransformerPV(nn.Module):
    """Tokens: 12 entities (type own / opponent), 1 global, the history steps (type = recency);
    pre-norm Transformer encoder; heads as PolicyValueNet's with t = the global token."""

    def __init__(
        self,
        dims: dict,
        d_model: int = 128,
        n_layers: int = 3,
        n_heads: int = 4,
        d_ff: int = 256,
        history: bool = True,
    ):
        super().__init__()
        self.emb = Embeddings(dims)
        self.history = history
        self.ent_in = nn.Linear(self.emb.d_entity, d_model)
        self.glob_in = nn.Linear(dims["global"], d_model)
        self.step_in = nn.Linear(self.emb.d_step, d_model) if history else None
        self.tok_type = nn.Embedding(3 + dims.get("hist", 8), d_model)  # own, opp, global, h_k
        layer = nn.TransformerEncoderLayer(
            d_model, n_heads, d_ff, dropout=0.0, batch_first=True, norm_first=True
        )
        self.encoder = nn.TransformerEncoder(layer, n_layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d_model)
        self.value = nn.Linear(d_model, 1)
        self.move_head = mlp(d_model + 32 + 1, 64, 2)
        self.switch_head = mlp(2 * d_model, 64, 1)

    def forward(self, sparse, dense, glob, mask, hsparse=None, hdense=None):
        x, moves = self.emb.entities(sparse, dense)
        b = x.shape[0]
        types = torch.tensor([0] * 6 + [1] * 6 + [2], device=x.device)
        toks = [self.ent_in(x), self.glob_in(glob)[:, None]]
        pad = torch.zeros(b, 13, dtype=torch.bool, device=x.device)
        if self.history:
            s = hsparse.shape[1]
            toks.append(self.step_in(self.emb.steps(hsparse, hdense)))
            types = torch.cat([types, 3 + torch.arange(s, device=x.device)])
            pad = torch.cat([pad, hdense[..., 0] == 0], dim=1)  # missing steps
        z = torch.cat(toks, dim=1) + self.tok_type(types)
        z = self.norm(self.encoder(z, src_key_padding_mask=pad))
        h, t = z[:, :12], z[:, 12]
        value = self.value(t).squeeze(-1)
        own_active = dense[:, :6, D_ACTIVE]
        am = (moves[:, :6] * own_active[..., None, None]).sum(1)
        usable = (dense[:, :6, D_USABLE] * own_active[..., None]).sum(1)
        tt = t[:, None, :].expand(-1, 4, -1)
        mh = self.move_head(torch.cat([tt, am, usable[..., None]], dim=-1))
        sw = self.switch_head(torch.cat([t[:, None, :].expand(-1, 6, -1), h[:, :6]], dim=-1))
        logits = torch.cat([mh[..., 0], mh[..., 1], sw.squeeze(-1)], dim=-1)
        return logits.masked_fill(~mask, float("-inf")), value
