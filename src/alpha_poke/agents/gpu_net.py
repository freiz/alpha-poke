"""The transformer network on the GPU for the batched search (design D13; rust bsearch).

``GpuNet(run)(batch)`` takes the arrays of ``alpha_search.BatchSearch.collect`` and returns
(value logits, policy logits) as ``BatchSearch.apply`` takes them: the same PyTorch module as in
training, float32 (TF32 off), the value residual on the handcrafted evaluation included.
With ``graphs`` (default on CUDA) the forward pass runs as a captured CUDA graph per padded
batch size (SIZES; the padding rows repeat the first row and are dropped): one launch instead
of hundreds of small kernels. Falls back to eager execution if a capture fails.
``launch(batch)`` / ``result(handle)``: the same, asynchronous (inputs through pinned staging
buffers, outputs copied back to pinned memory, an event to wait on), so that the next batch
can be collected on the CPU meanwhile. One launch in flight at a time.
"""

import alpha_search
import numpy as np
import torch

from alpha_poke.train.load import load_run

D = alpha_search.feature_dims()


SIZES = (32, 64, 128, 256, 512, 1024)


class GpuNet:
    def __init__(self, run: str, device: str = "cuda", graphs: bool = True):
        torch.backends.cuda.matmul.allow_tf32 = False  # float32, as the CPU reference
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        if self.device.type == "cuda":
            # the CPU side is only copies: PyTorch's CPU thread pool (one per core, spinning
            # while idle) took the CPU from the searches (2026-10-08: 6 self-play processes x
            # 10 spinning threads, a third less throughput on 20 logical CPUs than on 10)
            torch.set_num_threads(1)
        self.model = load_run(run, self.device).float()
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
            "turn": t("turn", np.int32, (n,), np.int64),
            "rating": t("rating", np.int32, (n, 2), np.int64),
        }
        return args, x, t("eval", np.float32, (n,))

    def forward(self, args, x, ev):
        logits, v = self.model(*args, x=x)
        if self.model.residual is not None:
            v = self.model.residual[0] * ev / 100 + self.model.residual[1] + v
        return v, logits

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
        stream = torch.cuda.Stream()
        stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(stream):
            for _ in range(3):  # warm-up before the capture
                self.forward(*static)
        torch.cuda.current_stream().wait_stream(stream)
        g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(g):
            out = self.forward(*static)
        return g, static, out

    KEYS = (("sparse", np.int32, np.int64), ("dense", np.float32, None),
            ("global", np.float32, None), ("mask", np.uint8, bool), ("hsparse", np.int32, np.int64),
            ("hdense", np.float32, None))  # fmt: skip
    XKEYS = (("reveal", np.uint8, np.int64), ("ent2", np.float32, None),
             ("glob2", np.float32, None), ("turn", np.int32, np.int64),
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
        g, (sa, sx, se), (v, logits) = self.graphs[size]
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
        hv, hl = self._out(size, v, logits)
        hv[:n].copy_(v[:n], non_blocking=True)
        hl[:n].copy_(logits[:n], non_blocking=True)
        ev = torch.cuda.Event()
        ev.record()
        return ("async", (ev, n, hv, hl))

    def result(self, handle) -> tuple[np.ndarray, np.ndarray]:
        kind, h = handle
        if kind == "sync":
            return h
        ev, n, hv, hl = h
        ev.synchronize()
        return hv[:n].numpy().copy(), hl[:n].numpy().reshape(-1).copy()

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
                              torch.empty((SIZES[-1], logits.shape[1])).pin_memory())  # fmt: skip
        return o

    @torch.no_grad()
    def __call__(self, b: dict) -> tuple[np.ndarray, np.ndarray]:
        args, x, ev = self.tensors(b)
        n = b["rows"]
        size = next((s for s in SIZES if s >= n), None)
        if self.use_graphs and size is not None:
            try:
                if size not in self.graphs:
                    self.graphs[size] = self.graph(size, args, x, ev)
                g, (sa, sx, se), (v, logits) = self.graphs[size]
                for dst, src in zip(sa, args, strict=True):
                    dst.copy_(self.pad(src, size))
                for k in sx:
                    sx[k].copy_(self.pad(x[k], size))
                se.copy_(self.pad(ev, size))
                g.replay()
                return v[:n].float().cpu().numpy(), logits[:n].float().cpu().numpy().reshape(-1)
            except RuntimeError:  # a capture that does not work: eager from now on
                self.use_graphs = False
        v, logits = self.forward(args, x, ev)
        return v.float().cpu().numpy(), logits.float().cpu().numpy().reshape(-1)
