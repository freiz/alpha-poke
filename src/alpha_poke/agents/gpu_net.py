"""The transformer network on the GPU for the batched search (design D13; rust bsearch).

``GpuNet(run)(batch)`` takes the arrays of ``alpha_search.BatchSearch.collect`` and returns
(value logits, policy logits, remaining turns or None) as ``BatchSearch.apply`` takes them: the
same PyTorch module as in training, float32 (TF32 off), the value residual on the handcrafted
evaluation included; the remaining turns (expm1 of the head) for a network with the
remaining-turns head (v6).
With ``graphs`` (default on CUDA) the forward pass runs as a captured CUDA graph per padded
batch size (SIZES; the padding rows repeat the first row and are dropped): one launch instead
of hundreds of small kernels. Falls back to eager execution if a capture fails.
``launch(batch)`` / ``result(handle)``: the same, asynchronous (inputs through pinned staging
buffers, outputs copied back to pinned memory, an event to wait on), so that the next batch
can be collected on the CPU meanwhile. One launch in flight at a time.
"""

import os
import threading

import alpha_search
import numpy as np
import torch

from alpha_poke.train.load import load_run

D = alpha_search.feature_dims()


SIZES = (32, 64, 128, 256, 512, 1024)
# several GpuNets in one process (an evaluation: one per network, each driven by its own batcher
# thread) must not capture graphs at the same time: one capture at a time, thread-local mode
_CAPTURE = threading.Lock()


class GpuNet:
    def __init__(self, run: str, device: str = "cuda", graphs: bool = True,
                 compile: bool | None = None, dtype: str | None = None):  # fmt: skip
        """``dtype``: "bf16" (default since 2026-10-10: autocast, matmuls and attention in
        bfloat16, the reductions autocast keeps in float32, the outputs float32; the training
        runs in bf16 autocast too) or "fp32" (as the CPU reference, for parity checks);
        ALPHA_GPU_DTYPE if not given; always fp32 on the CPU. bf16 vs fp32 on 16,384 rows:
        win probability |diff| 0.0016 mean / 0.012 max, policy KL 5e-5, the same top action
        99.4%; 1.55x faster at 256 rows (self-play's usual padded size), 1.9x at 1,024."""
        torch.backends.cuda.matmul.allow_tf32 = False  # float32, as the CPU reference
        self.dtype = dtype or os.environ.get("ALPHA_GPU_DTYPE", "bf16")
        assert self.dtype in ("fp32", "bf16"), self.dtype
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        if self.device.type != "cuda":
            self.dtype = "fp32"
        if self.device.type == "cuda":
            # the CPU side is only copies: PyTorch's CPU thread pool (one per core, spinning
            # while idle) took the CPU from the searches (2026-10-08: 6 self-play processes x
            # 10 spinning threads, a third less throughput on 20 logical CPUs than on 10)
            torch.set_num_threads(1)
        self.model = load_run(run, self.device).float()
        self.has_turns = "turns" in getattr(self.model, "aux_heads", ())
        # torch.compile (fused kernels; one compile per padded batch size at its first use, then
        # captured in the CUDA graph): ALPHA_GPU_COMPILE=1 or compile=True
        if compile is None:
            compile = os.environ.get("ALPHA_GPU_COMPILE", "0") == "1"
        self.net = (torch.compile(self.model, dynamic=False)
                    if compile and self.device.type == "cuda" else self.model)  # fmt: skip
        self.use_graphs = graphs and self.device.type == "cuda"
        self.graphs: dict = {}  # padded size -> (graph, static inputs, static outputs)

    def tensors(self, b: dict) -> tuple:
        n, e = b["rows"], D["entities"]

        def t(key, dt, shape, cast=None):
            a = np.frombuffer(b[key], dt).reshape(shape)
            a = a.astype(cast) if cast is not None else a.copy()  # writable for torch
            return torch.from_numpy(a).to(self.device, non_blocking=True)

        args = (
            t("sparse", np.int32, (n, e, D["sparse"]), np.int64),
            t("dense", np.float32, (n, e, D["dense"])),
            t("global", np.float32, (n, D["global"])),
            t("mask", np.uint8, (n, D["actions"]), bool),
            t("hsparse", np.int32, (n, D["hist"], D["hist_sparse"]), np.int64),
            t("hdense", np.float32, (n, D["hist"], D["hist_dense"])),
        )
        x = {
            "reveal": t("reveal", np.uint8, (n, e), np.int64),
            "ent2": t("ent2", np.float32, (n, e, D["ent_extra"])),
            "glob2": t("glob2", np.float32, (n, D["global_extra"])),
            "ent3": t("ent3", np.float32, (n, e, D["ent_count"])),
            "glob3": t("glob3", np.float32, (n, D["global_count"])),
            "turn": t("turn", np.int32, (n,), np.int64),
            "rating": t("rating", np.int32, (n, 2), np.int64),
        }
        return args, x, t("eval", np.float32, (n,))

    def forward(self, args, x, ev):
        """-> (value logits, policy logits, remaining turns or None)"""
        kw = {"turns": True} if self.has_turns else {}
        if self.dtype == "bf16":
            with torch.autocast(self.device.type, dtype=torch.bfloat16):
                out = self.net(*args, x=x, **kw)
            out = tuple(o.float() for o in out)
        else:
            out = self.net(*args, x=x, **kw)
        logits, v = out[0], out[1]
        if self.model.residual is not None:
            v = self.model.residual[0] * ev / 100 + self.model.residual[1] + v
        turns = torch.expm1(out[2].clamp(max=6)).clamp(min=0) if self.has_turns else None
        return v, logits, turns

    @staticmethod
    def pad(t: torch.Tensor, size: int) -> torch.Tensor:
        n = t.shape[0]
        if n == size:
            return t
        return torch.cat([t, t[:1].expand(size - n, *t.shape[1:])])

    def graph(self, size: int, args, x, ev):
        """Capture the forward pass for `size` rows (shapes of these example inputs)."""
        sa = [self.pad(a, size).clone() for a in args]
        sx = {k: self.pad(v, size).clone() for k, v in x.items()}
        static = (sa, sx, self.pad(ev, size).clone())
        with _CAPTURE:
            stream = torch.cuda.Stream()
            stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(stream):
                for _ in range(3):  # warm-up before the capture
                    self.forward(*static)
            torch.cuda.current_stream().wait_stream(stream)
            g = torch.cuda.CUDAGraph()
            with torch.cuda.graph(g, capture_error_mode="thread_local"):
                out = self.forward(*static)
        return g, static, out

    KEYS = (("sparse", np.int32, np.int64), ("dense", np.float32, None),
            ("global", np.float32, None), ("mask", np.uint8, bool), ("hsparse", np.int32, np.int64),
            ("hdense", np.float32, None))  # fmt: skip
    XKEYS = (("reveal", np.uint8, np.int64), ("ent2", np.float32, None),
             ("glob2", np.float32, None), ("ent3", np.float32, None),
             ("glob3", np.float32, None), ("turn", np.int32, np.int64),
             ("rating", np.int32, np.int64))  # fmt: skip

    @torch.no_grad()
    def launch(self, b: dict):
        """Start the forward pass of a batch; returns a handle for ``result``."""
        n = b["rows"]
        size = next((s for s in SIZES if s >= n), None)
        if not (self.use_graphs and size is not None):
            return ("sync", self(b))
        if size not in self.graphs:
            args, x, ev = self.tensors(b)
            self.graphs[size] = self.graph(size, args, x, ev)
        g, (sa, sx, se), (v, logits, turns) = self.graphs[size]
        dsts = list(sa) + [sx[k] for k, _, _ in self.XKEYS] + [se]
        specs = list(self.KEYS) + list(self.XKEYS) + [("eval", np.float32, None)]
        for dst, (key, dt, cast) in zip(dsts, specs, strict=True):
            a = np.frombuffer(b[key], dt).reshape((n, *dst.shape[1:]))
            a = a.astype(cast) if cast is not None else a.copy()  # writable for torch
            stage = self._stage(key, dst, size)
            stage[:n].copy_(torch.from_numpy(a))
            dst[:n].copy_(stage[:n], non_blocking=True)
            if n < size:  # padding rows: copies of the first row
                dst[n:].copy_(dst[:1].expand(size - n, *dst.shape[1:]))
        g.replay()
        hv, hl, ht = self._out(size, v, logits)
        hv[:n].copy_(v[:n], non_blocking=True)
        hl[:n].copy_(logits[:n], non_blocking=True)
        if turns is not None:
            ht[:n].copy_(turns[:n], non_blocking=True)
        ev = torch.cuda.Event()
        ev.record()
        return ("async", (ev, n, hv, hl, ht if turns is not None else None))

    def result(self, handle) -> tuple:
        """-> (value logits, policy logits, remaining turns or None)"""
        kind, h = handle
        if kind == "sync":
            return h
        ev, n, hv, hl, ht = h
        ev.synchronize()
        turns = ht[:n].numpy().copy() if ht is not None else None
        return hv[:n].numpy().copy(), hl[:n].numpy().reshape(-1).copy(), turns

    def _stage(self, key: str, like: torch.Tensor, size: int) -> torch.Tensor:
        st = getattr(self, "_stages", None)
        if st is None:
            st = self._stages = {}
        t = st.get(key)
        if t is None or t.shape[0] < size:
            t = st[key] = torch.empty((SIZES[-1], *like.shape[1:]), dtype=like.dtype).pin_memory()
        return t

    def _out(self, size: int, v: torch.Tensor, logits: torch.Tensor):
        o = getattr(self, "_outs", None)
        if o is None:
            o = self._outs = (torch.empty(SIZES[-1]).pin_memory(),
                              torch.empty((SIZES[-1], logits.shape[1])).pin_memory(),
                              torch.empty(SIZES[-1]).pin_memory())  # fmt: skip
        return o

    @torch.no_grad()
    def __call__(self, b: dict) -> tuple:
        args, x, ev = self.tensors(b)
        n = b["rows"]
        size = next((s for s in SIZES if s >= n), None)
        if self.use_graphs and size is not None:
            try:
                if size not in self.graphs:
                    self.graphs[size] = self.graph(size, args, x, ev)
                g, (sa, sx, se), out = self.graphs[size]
                for dst, src in zip(sa, args, strict=True):
                    dst.copy_(self.pad(src, size))
                for k in sx:
                    sx[k].copy_(self.pad(x[k], size))
                se.copy_(self.pad(ev, size))
                g.replay()
                return self._numpy(out, n)
            except RuntimeError:  # a capture that does not work: eager from now on
                self.use_graphs = False
        return self._numpy(self.forward(args, x, ev), b["rows"])

    @staticmethod
    def _numpy(out, n: int) -> tuple:
        v, logits, turns = out
        return (v[:n].float().cpu().numpy(), logits[:n].float().cpu().numpy().reshape(-1),
                turns[:n].float().cpu().numpy() if turns is not None else None)  # fmt: skip
