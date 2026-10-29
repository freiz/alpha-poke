"""Build tests/fixtures/data/: the small, fixed data the unit tests run on (tests/conftest.py
copies it into a temporary ALPHA_DATA directory; the tests never read the local data/).

  uv run python tests/make_fixture_data.py      # from the local data/ (the full datasets)

- raw/smogon/2026-09/chaos/gen9ou-{0,1500,1825}.json.gz: the month the released belief was built
  from, trimmed (no checks and counters; the 30 most common spreads, the 60 most common
  teammates of each species; abilities, items, moves, tera types whole);
- derived/parsed/gen9ou_mons.parquet: the per-mon replay table of 5,000 games (seed 0) without the
  players' names, what BeliefModel.build reads.

And next to it, in tests/fixtures/:
- replays_gen9ou.jsonl.gz: 200 rated games of the newest HF replay shard, anonymized: the two
  players renamed everywhere in the log (Player A / Player B), chat / join / leave / raw lines
  dropped, synthetic ids;
- state_build_ou_pairs.jsonl: the 60 catalog team pairs of test_state_build's OU baseline;
- tiny_net/: a randomly initialized TransformerPV (seed 0) with the released network's inputs
  and heads but d 32 x 1 layer: tests of the search and the network code, not of play;
- positions_v75.parquet / features_v75.npz: 50 training positions and 64 feature rows of the
  v75 data (states, contexts, featurized inputs; no names).
"""

import gzip
import json
import re
import sys

import numpy as np
import pandas as pd

from alpha_poke import paths

OUT = paths.ROOT / "tests" / "fixtures" / "data"
MONTH, CUTOFFS = "2026-09", (0, 1500, 1825)
SPREADS, TEAMMATES, GAMES = 30, 60, 5000


def top(d: dict, n: int) -> dict:
    return dict(sorted(d.items(), key=lambda kv: -kv[1])[:n])


def anonymized_replays(n: int = 200) -> None:
    import pyarrow.parquet as pq

    src = sorted((paths.REPLAYS_HF / "gen9ou").glob("*.parquet"))[-1]
    rows = pq.ParquetFile(src).read_row_group(0).to_pylist()
    drop = re.compile(r"^\|(c|c:|chat|j|J|l|L|n|N|raw|html|uhtml|uhtmlchange|inactive|inactiveoff)\|")
    out = []
    for r in rows:
        if len(out) == n:
            break
        names = [x for x in r["players"] if x]
        if len(names) != 2 or not str(r["rating"] or "").isdigit():
            continue
        log = "\n".join(line for line in r["log"].split("\n") if not drop.match(line))
        for name, new in sorted(zip(names, ("Player A", "Player B")), key=lambda x: -len(x[0])):
            log = log.replace(name, new)
        if any(len(x) >= 3 and x.lower() in log.lower() for x in names):
            continue  # a name left in another spelling: skip the game
        out.append({"id": f"gen9ou-fixture{len(out)}", "format": r["format"],
                    "players": ["Player A", "Player B"], "log": log, "rating": r["rating"],
                    "uploadtime": r["uploadtime"], "formatid": r["formatid"]})  # fmt: skip
    path = paths.ROOT / "tests" / "fixtures" / "replays_gen9ou.jsonl.gz"
    path.write_bytes(gzip.compress("".join(json.dumps(x) + "\n" for x in out).encode(), mtime=0))
    print(path.relative_to(paths.ROOT), path.stat().st_size // 1024, "KB,", len(out), "games")


def ou_pairs(n: int = 60) -> None:
    lines = (paths.TEAM_DATA / "statebuild_catalog_pairs.jsonl").read_text().splitlines()[:n]
    path = paths.ROOT / "tests" / "fixtures" / "state_build_ou_pairs.jsonl"
    path.write_text("\n".join(lines) + "\n")
    print(path.relative_to(paths.ROOT), path.stat().st_size // 1024, "KB")


def tiny_net() -> None:
    import torch
    from safetensors.torch import save_file

    from alpha_poke.selfplay.runner import MODEL
    from alpha_poke.train.model import TransformerPV

    cfg = json.loads((paths.ROOT / MODEL / "config.json").read_text())
    size = {"d_model": 32, "n_layers": 1, "n_heads": 2, "d_ff": 43}
    torch.manual_seed(0)
    model = TransformerPV(cfg["dims"], **size, history=cfg["history"], mtp=cfg["mtp"],
                          feats=tuple(cfg["feats"]), aux_heads=tuple(cfg["aux_heads"]),
                          arch=cfg["arch_opts"])  # fmt: skip
    model.residual = torch.nn.Parameter(torch.tensor([0.714, 0.078]))
    out = paths.ROOT / "tests" / "fixtures" / "tiny_net"
    out.mkdir(parents=True, exist_ok=True)
    save_file({k.removeprefix("emb."): v.float().contiguous() for k, v in model.state_dict().items()}
              | {"residual": model.residual.detach().clone()}, out / "best.safetensors")  # fmt: skip
    keep = ("dims", "arch", "history", "mtp", "feats", "aux_heads", "arch_opts")
    (out / "config.json").write_text(json.dumps({k: cfg[k] for k in keep} | {"size": size, "step": 0},
                                                indent=2))  # fmt: skip
    print(out.relative_to(paths.ROOT), (out / "best.safetensors").stat().st_size // 1024, "KB")


def positions(n: int = 50, rows: int = 64) -> None:
    import pyarrow.parquet as pq

    cols = ["state", "reveal", "rating_own", "rating_opp", "turn", "history"]
    t = pq.ParquetFile(paths.TRAIN / "v75" / "hf-part11.parquet").read_row_group(0, columns=cols)
    path = paths.ROOT / "tests" / "fixtures" / "positions_v75.parquet"
    pq.write_table(t.slice(0, n), path)
    with np.load(paths.TRAIN / "v75" / "features" / "hf-part11.npz") as z:
        d = {k: z[k][:rows] for k in z.files}
    np.savez_compressed(paths.ROOT / "tests" / "fixtures" / "features_v75.npz", **d)
    print(path.relative_to(paths.ROOT), path.stat().st_size // 1024, "KB; features_v75.npz")


def main() -> int:
    for c in CUTOFFS:
        raw = json.loads((paths.SMOGON / MONTH / "chaos" / f"gen9ou-{c}.json").read_text())
        for d in raw["data"].values():
            for k in ("Checks and Counters", "Happiness", "Viability Ceiling"):
                d.pop(k, None)
            d["Spreads"] = top(d.get("Spreads", {}), SPREADS)
            d["Teammates"] = top(d.get("Teammates", {}), TEAMMATES)
        out = OUT / "raw" / "smogon" / MONTH / "chaos" / f"gen9ou-{c}.json.gz"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(gzip.compress(json.dumps(raw, separators=(",", ":")).encode(), mtime=0))
        print(out.relative_to(paths.ROOT), out.stat().st_size // 1024, "KB")
    m = pd.read_parquet(paths.PARSED / "gen9ou_mons.parquet")
    ids = np.sort(m.id.unique())
    keep = set(np.random.default_rng(0).choice(ids, GAMES, replace=False))
    m = m[m.id.isin(keep)].drop(columns=["player"]).reset_index(drop=True)
    out = OUT / "derived" / "parsed" / "gen9ou_mons.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    m.to_parquet(out, index=False)
    print(out.relative_to(paths.ROOT), out.stat().st_size // 1024, "KB,", len(m), "rows")
    anonymized_replays()
    ou_pairs()
    tiny_net()
    positions()
    return 0


if __name__ == "__main__":
    sys.exit(main())
