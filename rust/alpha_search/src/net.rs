//! CPU inference of the policy / value network (alpha_poke/train/model.py, design D13).
//!
//! Weights come from the training run's `best.safetensors` (+ `config.json` for the sizes). The
//! forward pass mirrors the PyTorch model exactly (checked against it from Python):
//!   entity encoder (shared by the 12 mons) -> pooling (each side: active, bench mean, bench
//!   max) + global features -> trunk -> value logit (+ residual a * eval / 100 + b) and pointer
//!   policy logits (move slots from the active mon's move embeddings, switch slots from the
//!   entity encodings; illegal slots = -inf).
//! Single position, f32, plain loops over row-major weights (auto-vectorized); read-only and
//! shared between search threads.

use crate::features::{Features, DENSE, GLOBAL, N_ACTIONS, N_ENTITIES, SPARSE};
use safetensors::SafeTensors;
use std::collections::HashMap;
use std::path::Path;

const D_ALIVE: usize = 1;
const D_ACTIVE: usize = 2;
const D_USABLE: usize = 17;

pub struct Linear {
    w: Vec<f32>, // [out, in] row-major
    b: Vec<f32>,
    pub n_in: usize,
    pub n_out: usize,
}

/// Dot product with 8 independent accumulators: a single running sum fixes the order of the
/// float additions and keeps the compiler from vectorizing (it was 10x slower).
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

impl Linear {
    /// y = W x + b, optionally followed by ReLU
    fn apply(&self, x: &[f32], y: &mut [f32], relu: bool) {
        debug_assert_eq!(x.len(), self.n_in);
        for (o, yo) in y.iter_mut().enumerate().take(self.n_out) {
            let s = self.b[o] + dot(&self.w[o * self.n_in..(o + 1) * self.n_in], x);
            *yo = if relu { s.max(0.0) } else { s };
        }
    }
}

pub struct Embedding {
    w: Vec<f32>,
    pub dim: usize,
}

impl Embedding {
    fn row(&self, i: i32) -> &[f32] {
        let i = i.max(0) as usize;
        &self.w[i * self.dim..(i + 1) * self.dim]
    }
}

pub struct Net {
    species: Embedding,
    item: Embedding,
    ability: Embedding,
    ptype: Embedding,
    moves: Embedding,
    ent1: Linear,
    ent2: Linear,
    glob: Linear,
    trunk1: Linear,
    trunk2: Linear,
    value: Linear,
    move1: Linear,
    move2: Linear,
    switch1: Linear,
    switch2: Linear,
    /// value residual (a, b): logit = a * eval / 100 + b + value head; None = plain value
    residual: Option<(f32, f32)>,
}

pub struct Output {
    pub logits: [f32; N_ACTIONS],
    /// logit of P(side one wins)
    pub value: f32,
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

impl Net {
    /// Load `<dir>/best.safetensors` (sizes are read from the tensor shapes).
    pub fn load(dir: &Path) -> Result<Net, String> {
        let bytes = std::fs::read(dir.join("best.safetensors")).map_err(|e| e.to_string())?;
        let st = SafeTensors::deserialize(&bytes).map_err(|e| e.to_string())?;
        let emb = |name: &str| -> Result<Embedding, String> {
            let (w, shape) = tensor(&st, &format!("{name}.weight"))?;
            Ok(Embedding { w, dim: shape[1] })
        };
        let lin = |name: &str| -> Result<Linear, String> {
            let (w, shape) = tensor(&st, &format!("{name}.weight"))?;
            let (b, _) = tensor(&st, &format!("{name}.bias"))?;
            Ok(Linear {
                w,
                b,
                n_in: shape[1],
                n_out: shape[0],
            })
        };
        let residual = match tensor(&st, "residual") {
            Ok((r, _)) => Some((r[0], r[1])),
            Err(_) => None,
        };
        let net = Net {
            species: emb("species")?,
            item: emb("item")?,
            ability: emb("ability")?,
            ptype: emb("ptype")?,
            moves: emb("move")?,
            ent1: lin("entity.0.0")?,
            ent2: lin("entity.0.2")?,
            glob: lin("glob.0")?,
            trunk1: lin("trunk.0.0")?,
            trunk2: lin("trunk.0.2")?,
            value: lin("value")?,
            move1: lin("move_head.0")?,
            move2: lin("move_head.2")?,
            switch1: lin("switch_head.0")?,
            switch2: lin("switch_head.2")?,
            residual,
        };
        let d_in = net.species.dim
            + net.item.dim
            + net.ability.dim
            + 3 * net.ptype.dim
            + net.moves.dim
            + DENSE;
        if net.ent1.n_in != d_in || net.glob.n_in != GLOBAL {
            return Err(format!(
                "feature size mismatch: entity input {} vs {d_in}, global {} vs {GLOBAL}",
                net.ent1.n_in, net.glob.n_in
            ));
        }
        Ok(net)
    }

    pub fn has_residual(&self) -> bool {
        self.residual.is_some()
    }

    /// Entity encodings [12 * d_ent] and the trunk output.
    fn trunk(&self, f: &Features) -> (Vec<f32>, Vec<f32>) {
        let d_ent = self.ent2.n_out;
        let dm = self.moves.dim;
        // entity encoder
        let mut x = vec![0.0f32; self.ent1.n_in];
        let mut hid = vec![0.0f32; self.ent1.n_out];
        let mut h = vec![0.0f32; N_ENTITIES * d_ent];
        for e in 0..N_ENTITIES {
            let ids = &f.sparse[e * SPARSE..(e + 1) * SPARSE];
            let mut k = 0;
            for (emb, id) in [
                (&self.species, ids[0]),
                (&self.item, ids[1]),
                (&self.ability, ids[2]),
                (&self.ptype, ids[3]),
                (&self.ptype, ids[4]),
                (&self.ptype, ids[5]),
            ] {
                x[k..k + emb.dim].copy_from_slice(emb.row(id));
                k += emb.dim;
            }
            x[k..k + dm].iter_mut().for_each(|v| *v = 0.0);
            for &mid in &ids[6..10] {
                for (xv, wv) in x[k..k + dm].iter_mut().zip(self.moves.row(mid)) {
                    *xv += wv;
                }
            }
            k += dm;
            x[k..k + DENSE].copy_from_slice(&f.dense[e * DENSE..(e + 1) * DENSE]);
            self.ent1.apply(&x, &mut hid, true);
            self.ent2
                .apply(&hid, &mut h[e * d_ent..(e + 1) * d_ent], true);
        }
        // pooling: per side active, bench mean, bench max; then the global features
        let mut pooled = vec![0.0f32; self.trunk1.n_in];
        for (si, side) in [0..6usize, 6..12].into_iter().enumerate() {
            let base = si * 3 * d_ent;
            let (mut n_bench, mut maxv) = (0.0f32, vec![0.0f32; d_ent]);
            for e in side {
                let alive = f.dense[e * DENSE + D_ALIVE];
                let active = f.dense[e * DENSE + D_ACTIVE];
                let bench = alive * (1.0 - active);
                let he = &h[e * d_ent..(e + 1) * d_ent];
                for j in 0..d_ent {
                    pooled[base + j] += he[j] * active;
                    pooled[base + d_ent + j] += he[j] * bench;
                    if bench > 0.0 && he[j] > maxv[j] {
                        maxv[j] = he[j];
                    }
                }
                n_bench += bench;
            }
            let denom = n_bench.max(1.0);
            for j in 0..d_ent {
                pooled[base + d_ent + j] /= denom;
            }
            pooled[base + 2 * d_ent..base + 3 * d_ent].copy_from_slice(&maxv);
        }
        let g0 = 6 * d_ent;
        self.glob
            .apply(&f.global, &mut pooled[g0..g0 + self.glob.n_out], true);
        let mut t1 = vec![0.0f32; self.trunk1.n_out];
        let mut t = vec![0.0f32; self.trunk2.n_out];
        self.trunk1.apply(&pooled, &mut t1, true);
        self.trunk2.apply(&t1, &mut t, true);
        (t, h)
    }

    /// Value logit only (search leaves): the shared trunk + value head, no policy heads.
    pub fn value(&self, f: &Features, eval: f32) -> f32 {
        let (t, _) = self.trunk(f);
        self.value_from(&t, eval)
    }

    fn value_from(&self, t: &[f32], eval: f32) -> f32 {
        let mut v = [0.0f32];
        self.value.apply(t, &mut v, false);
        match self.residual {
            Some((a, b)) => v[0] + a * eval / 100.0 + b,
            None => v[0],
        }
    }

    /// One position. `eval` is poke-engine's handcrafted evaluation (used by the residual).
    pub fn forward(&self, f: &Features, eval: f32) -> Output {
        let (t, h) = self.trunk(f);
        let value = self.value_from(&t, eval);
        let d_ent = self.ent2.n_out;
        let dm = self.moves.dim;
        // policy: move slots from the own active mon's moves, switch slots from own entities
        let mut logits = [f32::NEG_INFINITY; N_ACTIONS];
        let own_active = (0..6).find(|&e| f.dense[e * DENSE + D_ACTIVE] > 0.5);
        let dt = t.len();
        let mut mx = vec![0.0f32; self.move1.n_in];
        mx[..dt].copy_from_slice(&t);
        let mut mh = vec![0.0f32; self.move1.n_out];
        let mut mo = [0.0f32; 2];
        for i in 0..4 {
            if f.mask[i] == 0 && f.mask[4 + i] == 0 {
                continue;
            }
            match own_active {
                Some(e) => {
                    let mid = f.sparse[e * SPARSE + 6 + i];
                    mx[dt..dt + dm].copy_from_slice(self.moves.row(mid));
                    mx[dt + dm] = f.dense[e * DENSE + D_USABLE + i];
                }
                None => mx[dt..].iter_mut().for_each(|v| *v = 0.0),
            }
            self.move1.apply(&mx, &mut mh, true);
            self.move2.apply(&mh, &mut mo, false);
            if f.mask[i] == 1 {
                logits[i] = mo[0];
            }
            if f.mask[4 + i] == 1 {
                logits[4 + i] = mo[1];
            }
        }
        let mut sx = vec![0.0f32; self.switch1.n_in];
        sx[..dt].copy_from_slice(&t);
        let mut sh = vec![0.0f32; self.switch1.n_out];
        let mut so = [0.0f32];
        for j in 0..6 {
            if f.mask[8 + j] == 0 {
                continue;
            }
            sx[dt..].copy_from_slice(&h[j * d_ent..(j + 1) * d_ent]);
            self.switch1.apply(&sx, &mut sh, true);
            self.switch2.apply(&sh, &mut so, false);
            logits[8 + j] = so[0];
        }
        Output { logits, value }
    }
}

/// Loaded networks, shared by all searches in the process (keyed by model directory).
pub fn shared(dir: &str) -> Result<std::sync::Arc<Net>, String> {
    use std::sync::{Arc, Mutex, OnceLock};
    static NETS: OnceLock<Mutex<HashMap<String, Arc<Net>>>> = OnceLock::new();
    let nets = NETS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut g = nets.lock().unwrap();
    if let Some(n) = g.get(dir) {
        return Ok(n.clone());
    }
    let n = Arc::new(Net::load(Path::new(dir))?);
    g.insert(dir.to_string(), n.clone());
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURE: &str = include_str!("../../../tests/fixtures/engine_state_6v6.txt");
    const MODEL: &str = "../../data/train/v1/runs/v1-medium-residual";

    #[test]
    fn forward_speed() {
        let Ok(net) = Net::load(Path::new(MODEL)) else {
            return; // no trained model in this checkout
        };
        let st = poke_engine::state::State::deserialize(FIXTURE.lines().next().unwrap());
        let f = crate::features::featurize(&st);
        let n = 2000;
        let t0 = std::time::Instant::now();
        let mut acc = 0.0;
        for _ in 0..n {
            acc += net.forward(&f, 0.0).value;
        }
        let us = t0.elapsed().as_secs_f64() * 1e6 / n as f64;
        let t1 = std::time::Instant::now();
        for _ in 0..n {
            acc += net.value(&f, 0.0);
        }
        let us_v = t1.elapsed().as_secs_f64() * 1e6 / n as f64;
        let t2 = std::time::Instant::now();
        for _ in 0..n {
            acc += crate::features::featurize(&st).global[0];
        }
        let us_f = t2.elapsed().as_secs_f64() * 1e6 / n as f64;
        eprintln!("forward: {us:.1} us, value only: {us_v:.1} us, featurize: {us_f:.1} us ({acc})");
        assert!((net.forward(&f, 0.0).value - net.value(&f, 0.0)).abs() < 1e-5);
    }
}
