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
own entity tokens. ``mtp`` > 0 adds multi-step action prediction heads (training-time auxiliary
targets, design D13): for each future decision step k < mtp and side (own / opponent; own step
0 is the policy label itself and is skipped), the kind of action (none / move / switch), the move
(tied to the move embedding table) and the switch-in (a pointer over that side's entity tokens).
v3 (design D13, network v3 first batch; TransformerPV only), inputs ``x`` from the data
(scripts/train_pv.py) in groups that can be switched off (``feats``) for ablations:
  * reveal: 8 public-information bits per entity (positions.REVEAL_BITS) -> entity inputs;
  * num: global extras (alpha_search.featurize_extra: living mons, HP, tera used, last move per
    side) + the turn -> global token;
  * movetab: the static move table (alpha_search.move_table) projected onto the move embeddings;
  * matchup: per entity speed vs the opposing active, the threat from it, the active's moves'
    damage vs the opposing active (also fed to the move-slot scores), entry hazard damage of the
    benched mons, who moves first;
  * elo (v4): both players' ratings before the game ((r - 1500) / 300, the difference, known
    flags; 0 = unknown) -> global token;
  * hres (v4): the history steps' outcomes (damage, crit, miss, KO, acted first, prevented,
    fainted first); without it the step inputs are the v2 ones;
  * counter (v4): per benched entity the damage taken from the opposing active's predicted move
    and its own best damage against the opposing active.
``mask_hidden`` (needs the reveal bits): the opponent's fields not revealed yet (item, ability,
tera type, unused moves) are replaced by an "unknown" id (the last of each table) instead of the
belief sample -- the input without the belief model.
Auxiliary heads (``aux_heads``, training-time only): oppset (the opponent's sets as revealed by
the end: item / ability / tera type / moves, from the opponent entity tokens), faint (each
active faints this turn), margin (mons left at the end, own - opponent, 13 classes), turns
(remaining turns, log1p).
"""

import alpha_search
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

# dense feature indices (rust/alpha_search/src/features.rs)
D_ALIVE, D_ACTIVE, D_USABLE = 1, 2, slice(17, 21)
FEATS = ("reveal", "num", "movetab", "matchup", "elo", "hres", "counter")
AUX_HEADS = ("oppset", "faint", "margin", "turns")
N_REVEAL = 8
# global extras (extra.rs): 0-15 per side numbers, 16-17 who moves first / speed ratio
# ("matchup"), 18-19 weather / terrain turns ("num")
NUM_IDX, MATCHUP_IDX = [*range(16), 18, 19], [16, 17]


N_ELO = 5


def elo_features(rating):
    """rating [B,2] (own, opponent; 0 = unknown) -> [B,5]: both normalized, their difference
    (when both are known), known flags."""
    r = rating.float()
    known = (r > 0).float()
    z = (r - 1500) / 300 * known
    diff = (z[:, :1] - z[:, 1:]) * known[:, :1] * known[:, 1:]
    return torch.cat([z, diff, known], dim=-1)


def mlp(*sizes: int) -> nn.Sequential:
    layers: list[nn.Module] = []
    for a, b in zip(sizes[:-1], sizes[1:], strict=True):
        layers += [nn.Linear(a, b), nn.ReLU()]
    return nn.Sequential(*layers[:-1])  # no activation after the last layer


class Embeddings(nn.Module):
    """Entity inputs (ids -> embeddings + dense) and history step inputs, shared tables."""

    def __init__(self, dims: dict, feats: tuple = ()):
        super().__init__()
        self.feats = set(feats)
        v_species, v_item, v_ability, v_type, v_move = dims["vocab"]
        self.species = nn.Embedding(v_species, 32)
        self.item = nn.Embedding(v_item, 16)
        self.ability = nn.Embedding(v_ability, 16)
        self.ptype = nn.Embedding(v_type, 8)  # not "type": nn.Module.type()
        self.move = nn.Embedding(v_move, 32)
        self.d_entity = 32 + 16 + 16 + 3 * 8 + 32 + dims["dense"]
        # history step inputs: the v2 ones (7 dense) unless the outcomes are fed (hres)
        self.n_hdense = dims.get("hist_dense", 7) if "hres" in self.feats else 7
        self.d_step = 6 * 32 + self.n_hdense
        self.v3 = bool(self.feats)
        # entity extras: 22 (v3) unless the switch-in counters are fed (counter)
        self.n_ent2 = dims.get("ent_extra", 22) if "counter" in self.feats else 22
        if self.v3:
            self.d_entity += N_REVEAL + self.n_ent2
        if "movetab" in self.feats:
            table = np.frombuffer(alpha_search.move_table(), np.float32).reshape(v_move, -1)
            self.register_buffer("move_table", torch.from_numpy(table.copy()), persistent=False)
            self.move_proj = nn.Linear(table.shape[1], 32)

    def move_vec(self, ids):
        """Move embeddings (+ the projected static properties with the movetab group)."""
        e = self.move(ids)
        if "movetab" in self.feats:
            e = e + self.move_proj(self.move_table[ids])
        return e

    def move_matrix(self):
        """[V_move, 32]: every move's vector (tied output layer of move predictions)."""
        w = self.move.weight
        if "movetab" in self.feats:
            w = w + self.move_proj(self.move_table)
        return w

    def entities(self, sparse, dense, x=None):
        """-> (entity inputs [B,12,d_entity], move embeddings [B,12,4,32])"""
        moves = self.move_vec(sparse[..., 6:10])
        if self.v3:
            bits = (x["reveal"][..., None] >> torch.arange(N_REVEAL, device=dense.device)) & 1
            bits = bits.float() * float("reveal" in self.feats)
            ent2 = x["ent2"][..., : self.n_ent2] * float("matchup" in self.feats)
            dense = torch.cat([dense, bits, ent2], dim=-1)
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
            self.move_vec(hsparse[..., 1]),
            self.species(hsparse[..., 2]),
            self.species(hsparse[..., 3]),
            self.move_vec(hsparse[..., 4]),
            self.species(hsparse[..., 5]),
        ]
        return torch.cat(e + [hdense[..., : self.n_hdense]], dim=-1)


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
        self.hist_len = dims.get("hist", 8)  # most recent steps used (the data may hold more)
        d_h = 0
        if history:
            self.step = nn.Sequential(mlp(self.emb.d_step, 64, 48), nn.ReLU())
            self.hist = nn.Sequential(nn.Linear(dims["hist"] * 48, d_hist), nn.ReLU())
            d_h = d_hist
        self.trunk = nn.Sequential(mlp(6 * d_ent + d_global + d_h, d_trunk, d_trunk), nn.ReLU())
        self.value = nn.Linear(d_trunk, 1)
        self.move_head = mlp(d_trunk + 32 + 1, 64, 2)  # (move, move + tera) per slot
        self.switch_head = mlp(d_trunk + d_ent, 64, 1)

    def forward(self, sparse, dense, glob, mask, hsparse=None, hdense=None, aux=False):
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
            k = self.hist_len
            st = self.step(self.emb.steps(hsparse[:, :k], hdense[:, :k]))  # [B,S,48]
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


class Block(nn.Module):
    """Pre-norm Transformer block with the architecture options of ``TransformerPV`` (``opts``):
    ffn "relu" (d_ff hidden) / "swiglu" (gated, d_ff hidden), norm "ln" / "rms", qk_norm
    (RMS-normalized queries and keys per head), smolgen > 0: a dynamic per-head attention bias
    over the token pairs generated from the whole position (Leela Chess Zero's smolgen): the
    normed tokens compressed to 8 dims each -> hidden ``smolgen`` -> per head 32 -> the shared
    ``gen`` projection to T x T, added to the attention logits."""

    def __init__(self, d: int, heads: int, d_ff: int, n_tok: int, opts: dict, gen=None):
        super().__init__()
        self.heads, self.n_tok = heads, n_tok
        norm = nn.RMSNorm if opts.get("norm") == "rms" else nn.LayerNorm
        self.norm1, self.norm2 = norm(d), norm(d)
        self.qkv = nn.Linear(d, 3 * d)
        self.out = nn.Linear(d, d)
        self.qk_norm = opts.get("qk_norm", False)
        if self.qk_norm:
            self.q_norm, self.k_norm = nn.RMSNorm(d // heads), nn.RMSNorm(d // heads)
        self.swiglu = opts.get("ffn") == "swiglu"
        if self.swiglu:
            self.w12 = nn.Linear(d, 2 * d_ff)
            self.w3 = nn.Linear(d_ff, d)
        else:
            self.ff1, self.ff2 = nn.Linear(d, d_ff), nn.Linear(d_ff, d)
        self.smolgen = opts.get("smolgen", 0)
        if self.smolgen:
            self.sg_compress = nn.Linear(d, 8, bias=False)
            self.sg_hidden = nn.Sequential(nn.Linear(n_tok * 8, self.smolgen), nn.SiLU(),
                                           nn.LayerNorm(self.smolgen))  # fmt: skip
            self.sg_heads = nn.Linear(self.smolgen, heads * 32)
            self.gen = gen  # shared across the blocks (not a submodule of this one)

    def forward(self, z, pad):
        b, t, d = z.shape
        h = self.heads
        y = self.norm1(z)
        q, k, v = self.qkv(y).view(b, t, 3, h, d // h).permute(2, 0, 3, 1, 4)  # [B,H,T,hd]
        if self.qk_norm:
            q, k = self.q_norm(q), self.k_norm(k)
        mask = torch.zeros(b, 1, 1, t, device=z.device, dtype=q.dtype)
        mask = mask.masked_fill(pad[:, None, None, :], float("-inf"))
        if self.smolgen:
            c = self.sg_compress(y).reshape(b, t * 8)
            g = self.sg_heads(self.sg_hidden(c)).view(b, h, 32)
            mask = mask + self.gen[0](g).view(b, h, t, t)
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        z = z + self.out(a.transpose(1, 2).reshape(b, t, d))
        y = self.norm2(z)
        if self.swiglu:
            g1, g2 = self.w12(y).chunk(2, dim=-1)
            z = z + self.w3(F.silu(g1) * g2)
        else:
            z = z + self.ff2(F.relu(self.ff1(y)))
        return z


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
        mtp: int = 0,
        feats: tuple = (),
        aux_heads: tuple = (),
        mask_hidden: bool = False,
        arch: dict | None = None,
    ):
        """``arch`` (architecture experiments, design D13): ffn "relu" / "swiglu", norm "ln" /
        "rms", qk_norm, smolgen (hidden size, 0 = off), value_hidden (a hidden layer for the
        value, 0 = off); empty / None = PyTorch's encoder layer
        (the checkpoints before the experiments)."""
        super().__init__()
        assert not mask_hidden or feats, "mask_hidden needs the v3 inputs (reveal bits)"
        self.arch = {k: v for k, v in (arch or {}).items() if v not in (None, False, 0, "relu",
                                                                         "ln")}  # fmt: skip
        self.mask_hidden = mask_hidden
        self.unknown = [v - 1 for v in dims["vocab"]]  # species, item, ability, type, move
        assert set(feats) <= set(FEATS) and set(aux_heads) <= set(AUX_HEADS), (feats, aux_heads)
        self.emb = Embeddings(dims, feats)
        self.feats, self.aux_heads = tuple(feats), tuple(aux_heads)
        self.history = history
        self.hist_len = dims.get("hist", 8)
        self.mtp = mtp
        if mtp:
            self.mtp_query = nn.Embedding(2 * mtp, d_model)  # (step, side)
            self.mtp_body = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU())
            self.mtp_kind = nn.Linear(d_model, 3)
            self.mtp_move = nn.Linear(d_model, 32)  # dot with the move embeddings
            self.mtp_switch = nn.Linear(d_model, d_model)  # dot with the entity tokens
        v_species, v_item, v_ability, v_type, v_move = dims["vocab"]
        if "oppset" in aux_heads:
            self.set_item = nn.Linear(d_model, v_item)
            self.set_ability = nn.Linear(d_model, v_ability)
            self.set_tera = nn.Linear(d_model, v_type)
            self.set_move = nn.Linear(d_model, 32)  # dot with the move vectors
        if "faint" in aux_heads:
            self.faint_head = nn.Linear(d_model, 2)
        if "margin" in aux_heads:
            self.margin_head = nn.Linear(d_model, 13)
        if "turns" in aux_heads:
            self.turns_head = nn.Linear(d_model, 1)
        # index / token-type tensors on the module's device (no host copies in the forward pass,
        # so it can be captured as a CUDA graph); not part of the weights
        self.register_buffer("num_idx", torch.tensor(NUM_IDX), persistent=False)
        self.register_buffer("matchup_idx", torch.tensor(MATCHUP_IDX), persistent=False)
        types = [0] * 6 + [1] * 6 + [2] + [3 + k for k in range(dims.get("hist", 8))]
        self.register_buffer("tok_types", torch.tensor(types), persistent=False)
        self.ent_in = nn.Linear(self.emb.d_entity, d_model)
        d_glob = dims["global"] + (dims["global_extra"] + 1 if feats else 0)
        d_glob += N_ELO if "elo" in feats else 0
        self.glob_in = nn.Linear(d_glob, d_model)
        self.step_in = nn.Linear(self.emb.d_step, d_model) if history else None
        self.tok_type = nn.Embedding(3 + dims.get("hist", 8), d_model)  # own, opp, global, h_k
        if self.arch:
            n_tok = 13 + (self.hist_len if history else 0)
            # smolgen's last projection, shared by all blocks (as in Leela Chess Zero)
            gen = [nn.Linear(32, n_tok * n_tok)] if self.arch.get("smolgen") else None
            if gen:
                self.smolgen_gen = gen[0]
            self.blocks = nn.ModuleList(
                [Block(d_model, n_heads, d_ff, n_tok, self.arch, gen) for _ in range(n_layers)]
            )
            self.norm = nn.RMSNorm(d_model) if self.arch.get("norm") == "rms" else nn.LayerNorm(
                d_model)  # fmt: skip
        else:
            layer = nn.TransformerEncoderLayer(
                d_model, n_heads, d_ff, dropout=0.0, batch_first=True, norm_first=True
            )
            self.encoder = nn.TransformerEncoder(layer, n_layers, enable_nested_tensor=False)
            self.norm = nn.LayerNorm(d_model)
        self.value = nn.Linear(d_model, 1)
        # value_hidden > 0 (arch): a hidden layer on top of the linear value readout, its output
        # layer zero-initialized (adding it to a trained network keeps its outputs at first)
        vh = self.arch.get("value_hidden", 0)
        if vh:
            # value_dropout (arch): dropout on the hidden layer (training only), against the value
            # overfitting (one outcome per game for all its positions)
            self.value_mlp = nn.Sequential(nn.Linear(d_model, vh), nn.SiLU(),
                                           nn.Dropout(self.arch.get("value_dropout", 0.0)),
                                           nn.Linear(vh, 1))  # fmt: skip
            nn.init.zeros_(self.value_mlp[3].weight)
            nn.init.zeros_(self.value_mlp[3].bias)
        self.move_head = mlp(d_model + 32 + 1 + (4 if feats else 0), 64, 2)
        self.switch_head = mlp(2 * d_model, 64, 1)

    def forward(self, sparse, dense, glob, mask, hsparse=None, hdense=None, aux=False, x=None):
        """``x`` (v3): reveal uint8 [B,12], ent2 [B,12,E], glob2 [B,G2], turn [B]. With ``aux``
        also (MTP heads or None, dict of the auxiliary heads' outputs)."""
        xin = x
        if self.mask_hidden:
            sparse = self.hide(sparse, xin["reveal"])
        x, moves = self.emb.entities(sparse, dense, xin)
        b = x.shape[0]
        if self.feats:
            g2 = xin["glob2"]
            num = torch.cat([g2[:, self.num_idx], (xin["turn"].float() / 50)[:, None]], dim=-1)
            mu = g2[:, self.matchup_idx] * float("matchup" in self.feats)
            glob = torch.cat([glob, num * float("num" in self.feats), mu], dim=-1)
            if "elo" in self.feats:
                glob = torch.cat([glob, elo_features(xin["rating"])], dim=-1)
        types = self.tok_types[:13]
        toks = [self.ent_in(x), self.glob_in(glob)[:, None]]
        pad = torch.zeros(b, 13, dtype=torch.bool, device=x.device)
        if self.history:
            s = self.hist_len
            hsparse, hdense = hsparse[:, :s], hdense[:, :s]
            toks.append(self.step_in(self.emb.steps(hsparse, hdense)))
            types = self.tok_types[: 13 + s]
            pad = torch.cat([pad, hdense[..., 0] == 0], dim=1)  # missing steps
        z = torch.cat(toks, dim=1) + self.tok_type(types)
        if self.arch:
            for blk in self.blocks:
                z = blk(z, pad)
            z = self.norm(z)
        else:
            z = self.norm(self.encoder(z, src_key_padding_mask=pad))
        h, t = z[:, :12], z[:, 12]
        value = self.value(t).squeeze(-1)
        if self.arch.get("value_hidden", 0):
            value = value + self.value_mlp(t).squeeze(-1)
        own_active = dense[:, :6, D_ACTIVE]
        am = (moves[:, :6] * own_active[..., None, None]).sum(1)
        usable = (dense[:, :6, D_USABLE] * own_active[..., None]).sum(1)
        tt = t[:, None, :].expand(-1, 4, -1)
        parts = [tt, am, usable[..., None]]
        if self.feats:  # the active's moves vs the opposing active (damage, KO, effectiveness)
            mv = (xin["ent2"][:, :6, 4:20] * own_active[..., None]).sum(1).view(b, 4, 4)
            parts.append(mv * float("matchup" in self.feats))
        mh = self.move_head(torch.cat(parts, dim=-1))
        sw = self.switch_head(torch.cat([t[:, None, :].expand(-1, 6, -1), h[:, :6]], dim=-1))
        logits = torch.cat([mh[..., 0], mh[..., 1], sw.squeeze(-1)], dim=-1)
        logits = logits.masked_fill(~mask, float("-inf"))
        if not aux:
            return logits, value
        return logits, value, self.mtp_heads(t, h) if self.mtp else None, self.aux_out(t, h)

    def hide(self, sparse, reveal):
        """Opponent fields not revealed yet -> the unknown id (see ``mask_hidden``)."""
        sparse = sparse.clone()
        opp = sparse[:, 6:12]
        bits = (reveal[:, 6:12, None] >> torch.arange(8, device=sparse.device)) & 1  # [B,6,8]
        _, u_item, u_ability, u_type, u_move = self.unknown
        for col, bit, unk in ((1, 1, u_item), (2, 2, u_ability), (3, 3, u_type)):
            opp[..., col] = torch.where(bits[..., bit] == 1, opp[..., col], unk)
        mv = opp[..., 6:10]
        opp[..., 6:10] = torch.where((bits[..., 4:8] == 1) | (mv == 0), mv, u_move)
        sparse[:, 6:12] = opp
        return sparse

    def aux_out(self, t, h) -> dict:
        out = {}
        if "oppset" in self.aux_heads:
            o = h[:, 6:12]
            out["set_item"], out["set_ability"] = self.set_item(o), self.set_ability(o)
            out["set_tera"] = self.set_tera(o)
            out["set_move"] = self.set_move(o) @ self.emb.move_matrix().T  # [B,6,V_move]
        if "faint" in self.aux_heads:
            out["faint"] = self.faint_head(t)
        if "margin" in self.aux_heads:
            out["margin"] = self.margin_head(t)
        if "turns" in self.aux_heads:
            out["turns"] = self.turns_head(t).squeeze(-1)
        return out

    def mtp_heads(self, t, h):
        """-> kind [B,K,2,3], move [B,K,2,V_move], switch [B,K,2,6] (side 0 own, 1 opponent)"""
        b, k = t.shape[0], self.mtp
        q = self.mtp_body(t[:, None, :] + self.mtp_query.weight[None])  # [B,2K,d]
        q = q.view(b, k, 2, -1)
        move = self.mtp_move(q) @ self.emb.move_matrix().T
        sides = torch.stack([h[:, :6], h[:, 6:12]], dim=1)  # [B,2,6,d]
        switch = torch.einsum("bksd,bsed->bkse", self.mtp_switch(q), sides)
        return self.mtp_kind(q), move, switch
