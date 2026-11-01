"""What the network's rating input does (2026-11-01): on held-out human positions (games after
the training's validation cutoff), the policy's and the value's losses with the rating input set
to the game's own ratings, unknown (0, 0), or one rating for both sides -- by the mover's actual
rating. If the input carries skill, a high rating predicts the strong players' moves better and
the weak players' worse (and the reverse for a low one); if it barely moves the losses, the
network ignores it.

  uv run python scripts/check_rating_input.py [--model RUN ...] [--max 120000]

Positions: turn starts with a visible action (kind 0) for the policy, all for the value; the
confidence intervals by a bootstrap over games (a game's positions are not independent).
"""

import argparse
import collections
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))

SHARD = "data/train/v75/features/hf-part13-2.npz"  # (all after v75's validation cutoff)
CONDITIONS = {"actual": None, "unknown": (0, 0), "1500": (1500, 1500), "1800": (1800, 1800),
              "2100": (2100, 2100), "own 1800": ("1800", None)}  # fmt: skip
BANDS = (("< 1300", 0, 1300), ("1300-1600", 1300, 1600), (">= 1600", 1600, 10_000))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", nargs="+", default=["data/train/v75/runs/v6arch-pp-v75",
                                                   "data/train/v75/runs/r2-gen0a3"])  # fmt: skip
    ap.add_argument("--max", type=int, default=120_000, help="positions sampled (whole games)")
    ap.add_argument("--boot", type=int, default=300)
    a = ap.parse_args()

    import train_pv

    from alpha_poke.train.load import load_run

    keys = ("sparse", "dense", "glob", "mask", "hsp", "hde", "hdmg", "fsp", "fde", "action", "won",
            "evalv", "game", *train_pv.V3_KEYS)  # fmt: skip
    z = np.load(SHARD)
    d = {k: z[k] for k in keys if k in z.files}
    rating = d["rating"]
    known = (rating[:, 0] > 0) & (rating[:, 1] > 0)
    games = np.unique(d["game"][known])
    rng = np.random.default_rng(0)
    rng.shuffle(games)
    keep = set(games[: max(1, int(len(games) * a.max / known.sum()))].tolist())
    idx = np.flatnonzero(known & np.isin(d["game"], list(keep)))
    print(f"{len(idx)} positions from {len(keep)} games (both ratings known)", flush=True)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    for run in a.model:
        model = load_run(Path(run), dev)
        model.eval()
        losses = {}
        for name, cond in CONDITIONS.items():
            pl, vl, hit = [], [], []
            for i in range(0, len(idx), 4096):
                b = idx[i : i + 4096]
                t = list(train_pv.to_torch(d, b, dev))
                x = t[-1]
                r = x["rating"].clone()
                if cond is not None and cond[1] is None:  # (own only; the opponent's actual)
                    r[:, 0] = int(cond[0])
                elif cond is not None:
                    r[:, 0], r[:, 1] = cond
                x["rating"] = r
                sp, de, gl, ma, act, won, ev, hs, hd = t[:9]
                with (
                    torch.no_grad(),
                    torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"),
                ):
                    o = model(sp, de, gl, ma, hs, hd, x=x)
                lg = o[0].float()
                pl.append(train_pv.policy_loss(lg, act, ma, reduction="none").cpu().numpy())
                hit.append((lg.argmax(-1) == act).cpu().numpy())
                with torch.no_grad():
                    v = train_pv.value_logit(model, o[1].float(), ev)
                vl.append(
                    F.binary_cross_entropy_with_logits(v, won, reduction="none").cpu().numpy()
                )
            losses[name] = (np.concatenate(pl), np.concatenate(hit), np.concatenate(vl))
        kind = d["kind"][idx]
        own = rating[idx, 0]
        game = d["game"][idx]
        print(f"\n== {run}")
        print("policy CE on the move played, minus the 'actual' condition's (negative: predicts the players better);"
              " value BCE likewise; 95% CI by games")  # fmt: skip
        for band, lo, hi in BANDS:
            sel = (own >= lo) & (own < hi)
            pol = sel & (kind == 0)
            gs = np.unique(game[sel])
            base_p, base_h, base_v = losses["actual"]
            print(f"  mover {band}: {pol.sum()} turn starts, {sel.sum()} positions, {len(gs)} games;"
                  f" actual: CE {base_p[pol].mean():.4f} top-1 {base_h[pol].mean():.1%} value BCE {base_v[sel].mean():.4f}")  # fmt: skip
            by_game = collections.defaultdict(list)
            for j in np.flatnonzero(sel):
                by_game[game[j]].append(j)
            groups = [np.asarray(v) for v in by_game.values()]
            for name in CONDITIONS:
                if name == "actual":
                    continue
                p, h, v = losses[name]
                dp = p - base_p
                dv = v - base_v
                boots = []
                for _ in range(a.boot):
                    pick = np.concatenate(
                        [groups[k] for k in rng.integers(0, len(groups), len(groups))]
                    )
                    pp = pick[kind[pick] == 0]
                    boots.append((dp[pp].mean(), dv[pick].mean()))
                lo_p, hi_p = np.percentile([b[0] for b in boots], [2.5, 97.5])
                lo_v, hi_v = np.percentile([b[1] for b in boots], [2.5, 97.5])
                print(f"    {name:9} CE {dp[pol].mean():+.4f} [{lo_p:+.4f}, {hi_p:+.4f}]  top-1 {h[pol].mean() - base_h[pol].mean():+.2%}"
                      f"  value BCE {dv[sel].mean():+.4f} [{lo_v:+.4f}, {hi_v:+.4f}]")  # fmt: skip


if __name__ == "__main__":
    main()
