//! CPU inference of `TransformerPV` (alpha_poke/train/model.py, design D13 v3 / v4).
//!
//! Inputs of one position, from the point of view of the side to act (`flip` = side two):
//! the v1 features (`features::featurize_view`), the v3 extras (`extra::featurize_extra`), the
//! public-information bits of the 12 entities, both players' ratings, the turn and the decision
//! steps before the position (`features::history_features`). Model: 12 entity tokens + 1 global
//! token + the present history steps (the missing ones are left out: they are masked as keys in
//! PyTorch and their outputs are never read, so the result is the same) -> pre-norm Transformer
//! encoder -> final LayerNorm -> value (global token, + the residual on the handcrafted
//! evaluation) and pointer policy heads (move slots: global token + the own active mon's move
//! vectors + usability + its damage features; switch slots: global token + entity token).
//! The MTP and auxiliary heads are training-only and not loaded.
//!
//! Weights: `best.safetensors` of the run, `config.json` for the sizes and the feature groups.
//! Read-only after loading, shared between search threads.

use crate::extra::{featurize_extra, move_table, ENT_EXTRA, GLOBAL_EXTRA, MOVE_FEAT};
use crate::features::{
    featurize_view, history_features, Features, Step, DENSE, GLOBAL, HIST, HIST_DENSE, HIST_SPARSE,
    N_ACTIONS, N_ENTITIES, SPARSE, VOCAB,
};
use crate::net::Output;
use poke_engine::state::State;
use safetensors::SafeTensors;
use std::path::Path;

const D_ACTIVE: usize = 2;
const D_USABLE: usize = 17;
const N_REVEAL: usize = 8;
/// global extras (extra.rs): "num" group = per side numbers + weather / terrain turns
const NUM_IDX: [usize; 18] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18, 19];
const MATCHUP_IDX: [usize; 2] = [16, 17];
const N_ELO: usize = 5;

/// Everything the network reads besides the state, for side one of the state (the search's
/// root player). `flip` mirrors it for side two.
#[derive(Clone, Debug, Default)]
pub struct Context {
    /// public-information bits per entity (own 0-5, opponent 6-11; positions.REVEAL_BITS)
    pub reveal: [u8; N_ENTITIES],
    /// ratings before the game (own, opponent; 0 = unknown)
    pub rating: [i32; 2],
    pub turn: i32,
    /// decision steps before the position, oldest first
    pub history: Vec<Step>,
}

/// One position's inputs, in the acting side's view.
pub struct Input {
    pub f: Features,
    pub ent2: Vec<f32>,
    pub glob2: Vec<f32>,
    pub reveal: [u8; N_ENTITIES],
    pub rating: [i32; 2],
    pub turn: i32,
    pub hsparse: Vec<i32>,
    pub hdense: Vec<f32>,
    /// poke-engine's evaluation from this side's view (the value residual)
    pub eval: f32,
}

impl Input {
    pub fn new(state: &State, ctx: &Context, flip: bool, eval_side_one: f32) -> Input {
        let f = featurize_view(state, flip);
        let (ent2, glob2) = featurize_extra(state, flip);
        let (mut hs, mut hd) = (Vec::with_capacity(HIST * HIST_SPARSE), Vec::new());
        history_features(&ctx.history, flip, &mut hs, &mut hd);
        let mut reveal = ctx.reveal;
        let mut rating = ctx.rating;
        if flip {
            reveal.rotate_left(6);
            rating.swap(0, 1);
        }
        Input {
            f,
            ent2,
            glob2,
            reveal,
            rating,
            turn: ctx.turn,
            hsparse: hs,
            hdense: hd,
            eval: if flip { -eval_side_one } else { eval_side_one },
        }
    }

    /// Side two's input from side one's (`self`, built with flip = false): the extras are the
    /// same quantities seen from the other side (halves swapped, who-moves-first and the speed
    /// ratio negated), so the damage calculations are not redone.
    pub fn flipped(&self, state: &State, ctx: &Context) -> Input {
        let f = featurize_view(state, true);
        let mut ent2 = self.ent2.clone();
        ent2.rotate_left(6 * ENT_EXTRA);
        let mut glob2 = self.glob2.clone();
        let side = crate::extra::SIDE_EXTRA;
        glob2[..2 * side].rotate_left(side);
        glob2[2 * side] = -glob2[2 * side];
        glob2[2 * side + 1] = -glob2[2 * side + 1];
        let (mut hs, mut hd) = (Vec::with_capacity(HIST * HIST_SPARSE), Vec::new());
        history_features(&ctx.history, true, &mut hs, &mut hd);
        let mut reveal = self.reveal;
        reveal.rotate_left(6);
        Input {
            f,
            ent2,
            glob2,
            reveal,
            rating: [self.rating[1], self.rating[0]],
            turn: self.turn,
            hsparse: hs,
            hdense: hd,
            eval: -self.eval,
        }
    }
}

struct Lin {
    w: Vec<f32>, // [out, in]
    /// the same weights transposed, [in, out] (rows of many tokens: see `apply_rows`)
    wt: Vec<f32>,
    b: Vec<f32>,
    n_in: usize,
    n_out: usize,
}

fn transpose(w: &[f32], n_out: usize, n_in: usize) -> Vec<f32> {
    let mut t = vec![0.0f32; w.len()];
    for o in 0..n_out {
        for i in 0..n_in {
            t[i * n_out + o] = w[o * n_in + i];
        }
    }
    t
}

/// y[r] = b + x[r] W^T for 4 rows: with AVX-512 a 4 x 32 block of accumulators stays in
/// registers while the inputs are summed over (each weight segment loaded once per 4 rows).
fn rows4(x: [&[f32]; 4], wt: &[f32], b: &[f32], y: [&mut [f32]; 4]) {
    let n_out = b.len();
    let ni = x[0].len();
    assert!(x.iter().all(|r| r.len() == ni) && y.iter().all(|r| r.len() == n_out));
    assert_eq!(wt.len(), ni * n_out);
    let [y0, y1, y2, y3] = y;
    #[cfg(all(target_arch = "x86_64", target_feature = "avx512f"))]
    let j = unsafe {
        let yp = [
            y0.as_mut_ptr(),
            y1.as_mut_ptr(),
            y2.as_mut_ptr(),
            y3.as_mut_ptr(),
        ];
        rows4_avx512(x, wt, b, yp)
    };
    #[cfg(not(all(target_arch = "x86_64", target_feature = "avx512f")))]
    let j = 0;
    for jj in j..n_out {
        let mut s = [b[jj]; 4];
        for k in 0..ni {
            let w = wt[k * n_out + jj];
            for r in 0..4 {
                s[r] += x[r][k] * w;
            }
        }
        y0[jj] = s[0];
        y1[jj] = s[1];
        y2[jj] = s[2];
        y3[jj] = s[3];
    }
}

/// The 32-output blocks of `rows4`; returns the first output not done.
#[cfg(all(target_arch = "x86_64", target_feature = "avx512f"))]
unsafe fn rows4_avx512(x: [&[f32]; 4], wt: &[f32], b: &[f32], y: [*mut f32; 4]) -> usize {
    use std::arch::x86_64::*;
    let n_out = b.len();
    let ni = x[0].len();
    let mut j = 0;
    while j + 32 <= n_out {
        let mut c = [_mm512_setzero_ps(); 8];
        for k in 0..ni {
            let wp = wt.as_ptr().add(k * n_out + j);
            let (w0, w1) = (_mm512_loadu_ps(wp), _mm512_loadu_ps(wp.add(16)));
            for r in 0..4 {
                let a = _mm512_set1_ps(*x[r].get_unchecked(k));
                c[2 * r] = _mm512_fmadd_ps(a, w0, c[2 * r]);
                c[2 * r + 1] = _mm512_fmadd_ps(a, w1, c[2 * r + 1]);
            }
        }
        let (b0, b1) = (
            _mm512_loadu_ps(b.as_ptr().add(j)),
            _mm512_loadu_ps(b.as_ptr().add(j + 16)),
        );
        for r in 0..4 {
            _mm512_storeu_ps(y[r].add(j), _mm512_add_ps(c[2 * r], b0));
            _mm512_storeu_ps(y[r].add(j + 16), _mm512_add_ps(c[2 * r + 1], b1));
        }
        j += 32;
    }
    j
}

#[inline]
fn dot(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = [0.0f32; 8];
    let (ca, cb) = (a.chunks_exact(8), b.chunks_exact(8));
    let (ra, rb) = (ca.remainder(), cb.remainder());
    for (x, y) in ca.zip(cb) {
        for k in 0..8 {
            acc[k] += x[k] * y[k];
        }
    }
    let mut s: f32 = acc.iter().sum();
    for (x, y) in ra.iter().zip(rb) {
        s += x * y;
    }
    s
}

impl Lin {
    /// rows of `x` [t, n_in] -> `y` [t, n_out] (+ ReLU), 4 rows at a time
    fn apply_rows(&self, x: &[f32], t: usize, y: &mut [f32], relu: bool) {
        let (ni, no) = (self.n_in, self.n_out);
        let mut r = 0;
        while r + 4 <= t {
            let xs = [
                &x[r * ni..(r + 1) * ni],
                &x[(r + 1) * ni..(r + 2) * ni],
                &x[(r + 2) * ni..(r + 3) * ni],
                &x[(r + 3) * ni..(r + 4) * ni],
            ];
            let (y0, rest) = y[r * no..(r + 4) * no].split_at_mut(no);
            let (y1, rest) = rest.split_at_mut(no);
            let (y2, y3) = rest.split_at_mut(no);
            rows4(xs, &self.wt, &self.b, [y0, y1, y2, y3]);
            r += 4;
        }
        if r < t {
            // the last 1-3 rows: padded to 4 with copies of the last row
            let left = t - r;
            let mut xp = vec![0.0f32; 4 * ni];
            for q in 0..4 {
                let src = r + q.min(left - 1);
                xp[q * ni..(q + 1) * ni].copy_from_slice(&x[src * ni..(src + 1) * ni]);
            }
            let mut yp = vec![0.0f32; 4 * no];
            {
                let (y0, rest) = yp.split_at_mut(no);
                let (y1, rest) = rest.split_at_mut(no);
                let (y2, y3) = rest.split_at_mut(no);
                let xs = [
                    &xp[..ni],
                    &xp[ni..2 * ni],
                    &xp[2 * ni..3 * ni],
                    &xp[3 * ni..],
                ];
                rows4(xs, &self.wt, &self.b, [y0, y1, y2, y3]);
            }
            y[r * no..t * no].copy_from_slice(&yp[..left * no]);
        }
        if relu {
            y[..t * no].iter_mut().for_each(|v| *v = v.max(0.0));
        }
    }

    fn apply(&self, x: &[f32], y: &mut [f32], relu: bool) {
        debug_assert_eq!(x.len(), self.n_in);
        for (o, yo) in y.iter_mut().enumerate().take(self.n_out) {
            let s = self.b[o] + dot(&self.w[o * self.n_in..(o + 1) * self.n_in], x);
            *yo = if relu { s.max(0.0) } else { s };
        }
    }
}

struct Norm {
    w: Vec<f32>,
    b: Vec<f32>,
}

impl Norm {
    fn apply(&self, x: &[f32], y: &mut [f32]) {
        let n = x.len() as f32;
        let mean = x.iter().sum::<f32>() / n;
        let var = x.iter().map(|v| (v - mean) * (v - mean)).sum::<f32>() / n;
        let inv = 1.0 / (var + 1e-5).sqrt();
        for i in 0..x.len() {
            y[i] = (x[i] - mean) * inv * self.w[i] + self.b[i];
        }
    }
}

struct Layer {
    norm1: Norm,
    qkv: Lin,
    out: Lin,
    norm2: Norm,
    ff1: Lin,
    ff2: Lin,
}

struct Table {
    w: Vec<f32>,
    dim: usize,
}

impl Table {
    fn row(&self, i: i32) -> &[f32] {
        let i = i.max(0) as usize;
        &self.w[i * self.dim..(i + 1) * self.dim]
    }
}

/// Multi-head self-attention over `n` tokens: `qkv` [n, 3d] (q | k | v, heads in d) ->
/// `att` [n, d] (heads concatenated, before the output projection). `sc`: scratch [n].
fn attention(qkv: &[f32], n: usize, d: usize, heads: usize, att: &mut [f32], sc: &mut [f32]) {
    let hd = d / heads;
    let scale = 1.0 / (hd as f32).sqrt();
    for h in 0..heads {
        for t in 0..n {
            let q = &qkv[t * 3 * d + h * hd..t * 3 * d + (h + 1) * hd];
            let mut m = f32::MIN;
            for u in 0..n {
                let k = &qkv[u * 3 * d + d + h * hd..u * 3 * d + d + (h + 1) * hd];
                sc[u] = dot(q, k) * scale;
                m = m.max(sc[u]);
            }
            let mut s = 0.0;
            for v in sc[..n].iter_mut() {
                *v = (*v - m).exp();
                s += *v;
            }
            let a = &mut att[t * d + h * hd..t * d + (h + 1) * hd];
            a.iter_mut().for_each(|v| *v = 0.0);
            for u in 0..n {
                let w = sc[u] / s;
                let v = &qkv[u * 3 * d + 2 * d + h * hd..u * 3 * d + 2 * d + (h + 1) * hd];
                for (ai, vi) in a.iter_mut().zip(v) {
                    *ai += w * vi;
                }
            }
        }
    }
}

pub struct TNet {
    d: usize,
    heads: usize,
    hist_len: usize,
    n_hdense: usize,
    n_ent2: usize,
    reveal: bool,
    num: bool,
    matchup: bool,
    elo: bool,
    species: Table,
    item: Table,
    ability: Table,
    ptype: Table,
    /// move vectors: embedding (+ projected static properties with the movetab group)
    moves: Table,
    ent_in: Lin,
    glob_in: Lin,
    step_in: Lin,
    tok_type: Table,
    layers: Vec<Layer>,
    norm: Norm,
    value: Lin,
    move1: Lin,
    move2: Lin,
    switch1: Lin,
    switch2: Lin,
    residual: Option<(f32, f32)>,
}

fn tensor(st: &SafeTensors, name: &str) -> Result<(Vec<f32>, Vec<usize>), String> {
    let t = st.tensor(name).map_err(|e| format!("{name}: {e}"))?;
    if t.dtype() != safetensors::Dtype::F32 {
        return Err(format!("{name}: expected f32, got {:?}", t.dtype()));
    }
    let data = t
        .data()
        .chunks_exact(4)
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .collect();
    Ok((data, t.shape().to_vec()))
}

impl TNet {
    pub fn load(dir: &Path) -> Result<TNet, String> {
        let cfg: serde_json::Value = serde_json::from_str(
            &std::fs::read_to_string(dir.join("config.json")).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        if cfg["arch"] != "transformer" {
            return Err(format!("{}: not a transformer", dir.display()));
        }
        if cfg["mask_hidden"].as_bool() == Some(true) {
            return Err("mask_hidden models are not supported".into());
        }
        let feats: Vec<String> = cfg["feats"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        let has = |g: &str| feats.iter().any(|f| f == g);
        let dims = &cfg["dims"];
        let size = &cfg["size"];
        let d = size["d_model"].as_u64().unwrap_or(128) as usize;
        let heads = size["n_heads"].as_u64().unwrap_or(4) as usize;
        let n_layers = size["n_layers"].as_u64().unwrap_or(3) as usize;
        let hist_len = dims["hist"].as_u64().unwrap_or(8) as usize;
        let hist_dense = dims["hist_dense"].as_u64().unwrap_or(7) as usize;
        let ent_extra = dims["ent_extra"].as_u64().unwrap_or(22) as usize;
        if cfg["history"].as_bool() != Some(true) || hist_len > HIST || hist_dense > HIST_DENSE {
            return Err("needs a history model within the featurized steps".into());
        }
        if !feats.is_empty() && (ent_extra > ENT_EXTRA || dims["global_extra"] != GLOBAL_EXTRA) {
            return Err("feature sizes differ from this build".into());
        }

        let bytes = std::fs::read(dir.join("best.safetensors")).map_err(|e| e.to_string())?;
        let st = SafeTensors::deserialize(&bytes).map_err(|e| e.to_string())?;
        let table = |name: &str| -> Result<Table, String> {
            let (w, shape) = tensor(&st, &format!("{name}.weight"))?;
            Ok(Table { w, dim: shape[1] })
        };
        let lin = |name: &str| -> Result<Lin, String> {
            let (w, shape) = tensor(&st, &format!("{name}.weight"))?;
            let (b, _) = tensor(&st, &format!("{name}.bias"))?;
            Ok(Lin {
                wt: transpose(&w, shape[0], shape[1]),
                w,
                b,
                n_in: shape[1],
                n_out: shape[0],
            })
        };
        let norm = |name: &str| -> Result<Norm, String> {
            Ok(Norm {
                w: tensor(&st, &format!("{name}.weight"))?.0,
                b: tensor(&st, &format!("{name}.bias"))?.0,
            })
        };
        let mut moves = table("move")?;
        if has("movetab") {
            let proj = lin("move_proj")?;
            let mt = move_table(VOCAB[4]);
            let mut v = vec![0.0f32; proj.n_out];
            for id in 0..VOCAB[4] {
                proj.apply(&mt[id * MOVE_FEAT..(id + 1) * MOVE_FEAT], &mut v, false);
                for (m, p) in moves.w[id * moves.dim..(id + 1) * moves.dim]
                    .iter_mut()
                    .zip(&v)
                {
                    *m += p;
                }
            }
        }
        let mut layers = Vec::new();
        for i in 0..n_layers {
            let p = format!("encoder.layers.{i}");
            layers.push(Layer {
                norm1: norm(&format!("{p}.norm1"))?,
                qkv: {
                    let w = tensor(&st, &format!("{p}.self_attn.in_proj_weight"))?.0;
                    Lin {
                        wt: transpose(&w, 3 * d, d),
                        w,
                        b: tensor(&st, &format!("{p}.self_attn.in_proj_bias"))?.0,
                        n_in: d,
                        n_out: 3 * d,
                    }
                },
                out: lin(&format!("{p}.self_attn.out_proj"))?,
                norm2: norm(&format!("{p}.norm2"))?,
                ff1: lin(&format!("{p}.linear1"))?,
                ff2: lin(&format!("{p}.linear2"))?,
            });
        }
        let residual = tensor(&st, "residual").ok().map(|(r, _)| (r[0], r[1]));
        let net = TNet {
            d,
            heads,
            hist_len,
            n_hdense: if has("hres") { hist_dense } else { 7 },
            n_ent2: if has("counter") {
                ent_extra
            } else {
                22.min(ent_extra)
            },
            reveal: has("reveal"),
            num: has("num"),
            matchup: has("matchup"),
            elo: has("elo"),
            species: table("species")?,
            item: table("item")?,
            ability: table("ability")?,
            ptype: table("ptype")?,
            moves,
            ent_in: lin("ent_in")?,
            glob_in: lin("glob_in")?,
            step_in: lin("step_in")?,
            tok_type: table("tok_type")?,
            layers,
            norm: norm("norm")?,
            value: lin("value")?,
            move1: lin("move_head.0")?,
            move2: lin("move_head.2")?,
            switch1: lin("switch_head.0")?,
            switch2: lin("switch_head.2")?,
            residual,
        };
        let v3 = !feats.is_empty();
        let d_ent = 32 + 16 + 16 + 3 * 8 + 32 + DENSE + if v3 { N_REVEAL + net.n_ent2 } else { 0 };
        let d_glob =
            GLOBAL + if v3 { GLOBAL_EXTRA + 1 } else { 0 } + if net.elo { N_ELO } else { 0 };
        if net.ent_in.n_in != d_ent || net.glob_in.n_in != d_glob {
            return Err(format!(
                "input sizes: entity {} vs {d_ent}, global {} vs {d_glob}",
                net.ent_in.n_in, net.glob_in.n_in
            ));
        }
        if !v3 {
            return Err("only v3+ models (with feature groups) are supported".into());
        }
        Ok(net)
    }

    pub fn has_residual(&self) -> bool {
        self.residual.is_some()
    }

    /// Token inputs -> encoder -> final norm: (tokens [n_tok * d], number of tokens).
    fn encode(&self, x: &Input) -> Vec<f32> {
        let d = self.d;
        let n_steps = (0..self.hist_len)
            .take_while(|&k| x.hdense[k * HIST_DENSE] > 0.0)
            .count();
        let n_tok = N_ENTITIES + 1 + n_steps;
        let mut z = vec![0.0f32; n_tok * d];
        // entity tokens
        let ne = self.ent_in.n_in;
        let mut xall = vec![0.0f32; N_ENTITIES * ne];
        for e in 0..N_ENTITIES {
            let xin = &mut xall[e * ne..(e + 1) * ne];
            let ids = &x.f.sparse[e * SPARSE..(e + 1) * SPARSE];
            let mut k = 0;
            for (t, id) in [
                (&self.species, ids[0]),
                (&self.item, ids[1]),
                (&self.ability, ids[2]),
                (&self.ptype, ids[3]),
                (&self.ptype, ids[4]),
                (&self.ptype, ids[5]),
            ] {
                xin[k..k + t.dim].copy_from_slice(t.row(id));
                k += t.dim;
            }
            let dm = self.moves.dim;
            xin[k..k + dm].iter_mut().for_each(|v| *v = 0.0);
            for &mid in &ids[6..10] {
                for (a, b) in xin[k..k + dm].iter_mut().zip(self.moves.row(mid)) {
                    *a += b;
                }
            }
            k += dm;
            xin[k..k + DENSE].copy_from_slice(&x.f.dense[e * DENSE..(e + 1) * DENSE]);
            k += DENSE;
            for bit in 0..N_REVEAL {
                xin[k + bit] = if self.reveal {
                    ((x.reveal[e] >> bit) & 1) as f32
                } else {
                    0.0
                };
            }
            k += N_REVEAL;
            for j in 0..self.n_ent2 {
                xin[k + j] = if self.matchup {
                    x.ent2[e * ENT_EXTRA + j]
                } else {
                    0.0
                };
            }
        }
        self.ent_in
            .apply_rows(&xall, N_ENTITIES, &mut z[..N_ENTITIES * d], false);
        for e in 0..N_ENTITIES {
            let ty = self.tok_type.row(if e < 6 { 0 } else { 1 });
            z[e * d..(e + 1) * d]
                .iter_mut()
                .zip(ty)
                .for_each(|(a, b)| *a += b);
        }
        // global token
        let mut g = Vec::with_capacity(self.glob_in.n_in);
        g.extend_from_slice(&x.f.global);
        let num = if self.num { 1.0 } else { 0.0 };
        g.extend(NUM_IDX.iter().map(|&i| x.glob2[i] * num));
        g.push(x.turn as f32 / 50.0 * num);
        let mu = if self.matchup { 1.0 } else { 0.0 };
        g.extend(MATCHUP_IDX.iter().map(|&i| x.glob2[i] * mu));
        if self.elo {
            let r = [x.rating[0] as f32, x.rating[1] as f32];
            let known = [(r[0] > 0.0) as u8 as f32, (r[1] > 0.0) as u8 as f32];
            let zs = [
                (r[0] - 1500.0) / 300.0 * known[0],
                (r[1] - 1500.0) / 300.0 * known[1],
            ];
            g.extend_from_slice(&zs);
            g.push((zs[0] - zs[1]) * known[0] * known[1]);
            g.extend_from_slice(&known);
        }
        let gt = &mut z[N_ENTITIES * d..(N_ENTITIES + 1) * d];
        self.glob_in.apply(&g, gt, false);
        gt.iter_mut()
            .zip(self.tok_type.row(2))
            .for_each(|(a, b)| *a += b);
        // history step tokens (the present ones)
        let ns = self.step_in.n_in;
        let mut sall = vec![0.0f32; n_steps.max(1) * ns];
        for s in 0..n_steps {
            let sin = &mut sall[s * ns..(s + 1) * ns];
            let ids = &x.hsparse[s * HIST_SPARSE..(s + 1) * HIST_SPARSE];
            let mut k = 0;
            for (t, id) in [
                (&self.species, ids[0]),
                (&self.moves, ids[1]),
                (&self.species, ids[2]),
                (&self.species, ids[3]),
                (&self.moves, ids[4]),
                (&self.species, ids[5]),
            ] {
                sin[k..k + t.dim].copy_from_slice(t.row(id));
                k += t.dim;
            }
            sin[k..k + self.n_hdense]
                .copy_from_slice(&x.hdense[s * HIST_DENSE..s * HIST_DENSE + self.n_hdense]);
        }
        if n_steps > 0 {
            let base = (N_ENTITIES + 1) * d;
            self.step_in
                .apply_rows(&sall, n_steps, &mut z[base..base + n_steps * d], false);
            for s in 0..n_steps {
                z[base + s * d..base + (s + 1) * d]
                    .iter_mut()
                    .zip(self.tok_type.row(3 + s as i32))
                    .for_each(|(a, b)| *a += b);
            }
        }
        // encoder
        let mut qkv = vec![0.0f32; n_tok * 3 * d];
        let mut att = vec![0.0f32; n_tok * d];
        let f1 = vec![0.0f32; self.layers.first().map_or(0, |l| l.ff1.n_out)];
        let mut sc = vec![0.0f32; n_tok];
        let mut yn = vec![0.0f32; n_tok * d];
        let mut ob = vec![0.0f32; n_tok * d];
        let mut fb = vec![0.0f32; n_tok * f1.len()];
        for l in &self.layers {
            for t in 0..n_tok {
                l.norm1
                    .apply(&z[t * d..(t + 1) * d], &mut yn[t * d..(t + 1) * d]);
            }
            l.qkv.apply_rows(&yn, n_tok, &mut qkv, false);
            attention(&qkv, n_tok, d, self.heads, &mut att, &mut sc);
            l.out.apply_rows(&att, n_tok, &mut ob, false);
            z.iter_mut().zip(&ob).for_each(|(a, b)| *a += b);
            for t in 0..n_tok {
                l.norm2
                    .apply(&z[t * d..(t + 1) * d], &mut yn[t * d..(t + 1) * d]);
            }
            l.ff1.apply_rows(&yn, n_tok, &mut fb, true);
            l.ff2.apply_rows(&fb, n_tok, &mut ob, false);
            z.iter_mut().zip(&ob).for_each(|(a, b)| *a += b);
        }
        let mut out = vec![0.0f32; (N_ENTITIES + 1) * d];
        for t in 0..=N_ENTITIES {
            self.norm
                .apply(&z[t * d..(t + 1) * d], &mut out[t * d..(t + 1) * d]);
        }
        out
    }

    fn value_from(&self, t: &[f32], eval: f32) -> f32 {
        let mut v = [0.0f32];
        self.value.apply(t, &mut v, false);
        match self.residual {
            Some((a, b)) => v[0] + a * eval / 100.0 + b,
            None => v[0],
        }
    }

    pub fn value(&self, x: &Input) -> f32 {
        let z = self.encode(x);
        self.value_from(&z[N_ENTITIES * self.d..(N_ENTITIES + 1) * self.d], x.eval)
    }

    pub fn forward(&self, x: &Input) -> Output {
        let d = self.d;
        let z = self.encode(x);
        let t = &z[N_ENTITIES * d..(N_ENTITIES + 1) * d];
        let value = self.value_from(t, x.eval);
        let mut logits = [f32::NEG_INFINITY; N_ACTIONS];
        let own_active = (0..6).find(|&e| x.f.dense[e * DENSE + D_ACTIVE] > 0.5);
        let dm = self.moves.dim;
        let mut mx = vec![0.0f32; self.move1.n_in];
        mx[..d].copy_from_slice(t);
        let mut mh = vec![0.0f32; self.move1.n_out];
        let mut mo = [0.0f32; 2];
        for i in 0..4 {
            if x.f.mask[i] == 0 && x.f.mask[4 + i] == 0 {
                continue;
            }
            match own_active {
                Some(e) => {
                    let mid = x.f.sparse[e * SPARSE + 6 + i];
                    mx[d..d + dm].copy_from_slice(self.moves.row(mid));
                    mx[d + dm] = x.f.dense[e * DENSE + D_USABLE + i];
                    for j in 0..4 {
                        mx[d + dm + 1 + j] = if self.matchup {
                            x.ent2[e * ENT_EXTRA + 4 + 4 * i + j]
                        } else {
                            0.0
                        };
                    }
                }
                None => mx[d..].iter_mut().for_each(|v| *v = 0.0),
            }
            self.move1.apply(&mx, &mut mh, true);
            self.move2.apply(&mh, &mut mo, false);
            if x.f.mask[i] == 1 {
                logits[i] = mo[0];
            }
            if x.f.mask[4 + i] == 1 {
                logits[4 + i] = mo[1];
            }
        }
        let mut sx = vec![0.0f32; self.switch1.n_in];
        sx[..d].copy_from_slice(t);
        let mut sh = vec![0.0f32; self.switch1.n_out];
        let mut so = [0.0f32];
        for j in 0..6 {
            if x.f.mask[8 + j] == 0 {
                continue;
            }
            sx[d..].copy_from_slice(&z[j * d..(j + 1) * d]);
            self.switch1.apply(&sx, &mut sh, true);
            self.switch2.apply(&sh, &mut so, false);
            logits[8 + j] = so[0];
        }
        Output { logits, value }
    }
}

/// Loaded transformer networks, shared by all searches in the process (keyed by directory).
pub fn shared(dir: &str) -> Result<std::sync::Arc<TNet>, String> {
    use std::collections::HashMap;
    use std::sync::{Arc, Mutex, OnceLock};
    static NETS: OnceLock<Mutex<HashMap<String, Arc<TNet>>>> = OnceLock::new();
    let nets = NETS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut g = nets.lock().unwrap();
    if let Some(n) = g.get(dir) {
        return Ok(n.clone());
    }
    let n = Arc::new(TNet::load(Path::new(dir))?);
    g.insert(dir.to_string(), n.clone());
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::features::parse_history;

    const FIXTURE: &str = include_str!("../../../tests/fixtures/engine_state_6v6.txt");
    const MODEL: &str = "../../data/train/v5/runs/v5-final";

    /// Input::flipped (derived from side one's input) = Input::new(flip = true)
    #[test]
    fn flipped_input_matches() {
        let st = State::deserialize(FIXTURE.lines().next().unwrap());
        let ctx = Context {
            reveal: [1, 3, 0, 0, 17, 0, 1, 0, 0, 0, 0, 33],
            rating: [1400, 1600],
            turn: 7,
            history: parse_history("m:GLIMMORA:POWERGEM:35:f/s:GREATTUSK:KINGAMBIT::"),
        };
        let ev = poke_engine::engine::evaluate::evaluate(&st);
        let a = Input::new(&st, &ctx, false, ev).flipped(&st, &ctx);
        let b = Input::new(&st, &ctx, true, ev);
        assert_eq!(a.f.sparse, b.f.sparse);
        assert_eq!(a.f.mask, b.f.mask);
        assert_eq!(
            (a.reveal, a.rating, a.turn, a.eval),
            (b.reveal, b.rating, b.turn, b.eval)
        );
        assert_eq!((&a.hsparse, &a.hdense), (&b.hsparse, &b.hdense));
        assert_eq!(a.ent2, b.ent2);
        for (x, y) in a.glob2.iter().zip(&b.glob2) {
            assert!((x - y).abs() < 1e-6, "{:?} vs {:?}", a.glob2, b.glob2);
        }
    }

    #[test]
    fn state_size() {
        let st = State::deserialize(FIXTURE.lines().next().unwrap());
        let n = 20000;
        let t0 = std::time::Instant::now();
        let mut acc = 0;
        for _ in 0..n {
            let c = st.clone();
            acc += c.side_one.active_index as usize;
        }
        let ns = t0.elapsed().as_secs_f64() * 1e9 / n as f64;
        let t1 = std::time::Instant::now();
        for _ in 0..2000 {
            acc += crate::extra::featurize_extra(&st, false).0.len();
        }
        let us = t1.elapsed().as_secs_f64() * 1e6 / 2000.0;
        eprintln!(
            "State: {} bytes, clone {ns:.0} ns; featurize_extra {us:.1} us ({acc})",
            std::mem::size_of::<State>()
        );
    }

    /// where the time goes (single thread)
    #[test]
    fn tnet_profile() {
        let Ok(net) = TNet::load(Path::new(MODEL)) else {
            return;
        };
        let time = |name: &str, n: usize, f: &mut dyn FnMut() -> f32| {
            let t0 = std::time::Instant::now();
            let mut acc = 0.0;
            for _ in 0..n {
                acc += f();
            }
            let us = t0.elapsed().as_secs_f64() * 1e6 / n as f64;
            eprintln!("{name:28} {us:8.2} us ({acc:.1})");
        };
        let l = &net.layers[0];
        let x = vec![0.01f32; 21 * 256];
        let mut y = vec![0.0f32; 21 * 384];
        time("qkv rows (21x128->384)", 2000, &mut || {
            l.qkv.apply_rows(&x[..21 * 128], 21, &mut y, false);
            y[7]
        });
        time("qkv per row apply", 2000, &mut || {
            for t in 0..21 {
                l.qkv.apply(
                    &x[t * 128..(t + 1) * 128],
                    &mut y[t * 384..(t + 1) * 384],
                    false,
                );
            }
            y[7]
        });
        time("ff1 rows (21x128->256)", 2000, &mut || {
            l.ff1.apply_rows(&x[..21 * 128], 21, &mut y, true);
            y[7]
        });
        time("ff2 rows (21x256->128)", 2000, &mut || {
            l.ff2.apply_rows(&x[..21 * 256], 21, &mut y, false);
            y[7]
        });
        let qkv = vec![0.013f32; 21 * 384];
        let mut att = vec![0.0f32; 21 * 128];
        let mut sc = vec![0.0f32; 21];
        time("attention (21 tokens, 4 heads)", 2000, &mut || {
            attention(&qkv, 21, 128, 4, &mut att, &mut sc);
            att[5]
        });
        let mut yn = vec![0.0f32; 128];
        let norm = &l.norm1;
        time("layernorm x21", 2000, &mut || {
            for t in 0..21 {
                norm.apply(&x[t * 128..(t + 1) * 128], &mut yn);
            }
            yn[3]
        });
        time("ent_in x12 (176->128)", 2000, &mut || {
            for _ in 0..12 {
                net.ent_in.apply(&x[..176], &mut y[..128], false);
            }
            y[7]
        });
        time("step_in x8 (199->128)", 2000, &mut || {
            for _ in 0..8 {
                net.step_in.apply(&x[..199], &mut y[..128], false);
            }
            y[7]
        });
    }

    /// single-thread speed of one forward pass with a full 8-step history
    #[test]
    fn tnet_speed() {
        let Ok(net) = TNet::load(Path::new(MODEL)) else {
            return; // no trained model in this checkout
        };
        let st = State::deserialize(FIXTURE.lines().next().unwrap());
        let step = "m:GLIMMORA:POWERGEM:35:f/s:GREATTUSK:KINGAMBIT::";
        let ctx = Context {
            reveal: [1; N_ENTITIES],
            rating: [1500, 1500],
            turn: 10,
            history: parse_history(&vec![step; 8].join(";")),
        };
        let ev = poke_engine::engine::evaluate::evaluate(&st);
        let x = Input::new(&st, &ctx, false, ev);
        let n = 2000;
        let t0 = std::time::Instant::now();
        let mut acc = 0.0;
        for _ in 0..n {
            acc += net.forward(&x).value;
        }
        let us = t0.elapsed().as_secs_f64() * 1e6 / n as f64;
        let t1 = std::time::Instant::now();
        for _ in 0..n {
            acc += Input::new(&st, &ctx, false, ev).eval;
        }
        let us_in = t1.elapsed().as_secs_f64() * 1e6 / n as f64;
        eprintln!("tnet forward: {us:.1} us, inputs: {us_in:.1} us ({acc})");
    }
}
