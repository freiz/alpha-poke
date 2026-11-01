"""Who predicts the opponent's hidden set better: the belief (the worlds the search samples) or the
network's opponent-set head (``oppset``)? (2026-10-31: the search's worlds come from the belief
alone; the head is trained but unused.) On held-out replays (after the training cutoff), at
turn-start positions from the player's view, against the parts of the opponent's sets the game
shows by its end but not yet at the position:

  belief  W worlds of the position (positions_from_replay(worlds=W): what a search draws): each
          option's frequency among them; its best guess the k most frequent (k = the free move
          slots), the most frequent item / tera type
  network the head's logits on the position's own world (as the training data gives it), the
          revealed moves excluded; its best guess the k likeliest

Both by their best guesses (not one sampled world against the head's argmax, as the training
log's net_* / belief_* counters compare them) and by the mean log-probability of the hidden
truth (the belief smoothed: an option absent from every world gets 1 / (2 W)). The labels are the
game's reveals: a move held but never used counts nowhere (both sides alike).

  uv run python scripts/check_set_prediction.py [--games 400] [--worlds 64] [--model RUN]

--selfplay G: generation G's self-play games instead, where one side's team is a complete forum
team (the catalog's: built by people, not completed by the belief), seen from the other side --
the labels that side's whole true sets: every hidden move, item and tera type, used or not (the
replays' labels count only what the game shows: items that never show -- Heavy-Duty Boots,
Choice items -- are under-represented there, and the network is trained on that label).
"""

import argparse
import collections
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

SHARDS = (
    "data/raw/replays_hf/gen9ou/hf-part13-1.parquet",
    "data/raw/replays_hf/gen9ou/hf-part13-2.parquet",
)


def _truth_label(text: str) -> dict[str, str]:
    """A team export -> species id -> its set as positions' opp_sets labels it (ITEM|ABILITY|TERA|
    MOVE,MOVE,...: engine ids, upper case)."""
    from alpha_poke.coach.team import parse_team

    out = {}
    for sid, k in parse_team(text).items():
        out[sid] = "|".join([(k.item or "").upper(), (k.ability or "").upper(), (k.tera or "").upper(),
                             ",".join(m.upper() for m in k.moves)])  # fmt: skip
    return out


def build(args) -> list[tuple[dict, list]]:
    """(the position's row without its worlds, per opponent slot the worlds' (moves, item, tera))."""
    rows, worlds, per_game, seed = args
    import poke_engine as pe

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.train.positions import positions_from_replay

    belief = BeliefModel.load(heldout_pool=None)
    out = []
    for row in rows:
        try:
            ps = positions_from_replay(row, belief, random.Random(seed), per_game=per_game, worlds=worlds,
                                       side=row.get("_side"))  # fmt: skip
        except Exception:  # noqa: BLE001 - a log the parser refuses: skipped
            continue
        for p in ps:
            if p.kind != 0:
                continue
            if row.get("_truth"):  # (self-play: the opponent's whole true sets as the labels)
                from alpha_poke.analysis.roles import to_id

                labels = []
                for m in pe.State.from_string(p.state).side_two.pokemon[:6]:
                    sid = to_id(str(m.id))
                    labels.append(
                        next(
                            (
                                v
                                for k, v in row["_truth"].items()
                                if sid.startswith(k) or k.startswith(sid)
                            ),
                            "",
                        )
                    )
                p.opp_sets = ";".join(labels)
            per_slot = [[] for _ in range(6)]
            for w in p.worlds:
                for j, m in enumerate(pe.State.from_string(w).side_two.pokemon[:6]):
                    per_slot[j].append(([mv.id for mv in m.moves], m.item, str(m.tera_type)))
            d = asdict(p)
            d.pop("worlds", None)
            d.pop("post", None)
            out.append((d, per_slot))
    return out


def selfplay_rows(gen: int, n: int) -> list[dict]:
    """Generation ``gen``'s games with exactly one forum (catalog) team, as replay rows seen from
    the other side ("_side"), with the forum team's true sets ("_truth")."""
    import json

    from alpha_poke.selfplay import SELFPLAY_DIR

    gd = SELFPLAY_DIR / f"gen{gen}"
    teams = [json.loads(line) for line in open(gd / "teams.jsonl", encoding="utf-8")]

    def lines(pattern):
        for f in sorted(gd.glob(pattern)):
            for line in open(f, encoding="utf-8"):
                try:
                    yield json.loads(line)
                except ValueError:  # (a line cut by a stop)
                    continue

    logs = {(r["pair"], r.get("attempt")): r["log"] for r in lines("logs-w*.jsonl")}
    rows = []
    for g in lines("games-w*.jsonl"):
        log = logs.get((g["pair"], g.get("attempt")))
        cat = [s for s in ("p1", "p2") if g.get(f"{s}_kind") == "catalog"]
        if not log or len(cat) != 1:
            continue
        rows.append({"id": f"sp{gen}-{g['pair']}", "log": log, "rating": None, "uploadtime": 0,
                     "_side": "p2" if cat[0] == "p1" else "p1",
                     "_truth": _truth_label(teams[g["pair"]][cat[0]]["text"])})  # fmt: skip
        if len(rows) >= n:
            break
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--per-game", type=int, default=4)
    ap.add_argument("--worlds", type=int, default=64)
    ap.add_argument("--model", default="data/train/v75/runs/r2-gen0a3")
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--out", default="data/selfplay/diag/set_prediction")
    ap.add_argument(
        "--selfplay", type=int, default=None, help="a generation's games, a forum team's side"
    )
    a = ap.parse_args()

    import alpha_search
    import torch
    import train_pv

    from alpha_poke.train.load import load_run

    rows = []
    if a.selfplay is not None:
        rows = selfplay_rows(a.selfplay, a.games)
    else:
        for f in SHARDS:
            rows += [r for r in pq.read_table(f).to_pylist() if r.get("log")]
            if len(rows) >= a.games:
                break
    rows = rows[: a.games]
    chunks = [(rows[i :: a.procs], a.worlds, a.per_game, 0) for i in range(a.procs)]
    with ProcessPoolExecutor(a.procs) as ex:
        built = [x for part in ex.map(build, chunks) for x in part]
    print(f"{len(built)} positions from {len(rows)} games", flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shard = out / "positions.parquet"
    pq.write_table(pa.Table.from_pylist([d for d, _ in built]), shard)
    cache = out / "positions.npz"
    cache.unlink(missing_ok=True)
    train_pv.featurize_shard(shard, cache)
    data = dict(np.load(cache))
    model = load_run(Path(a.model), "cpu")
    model.eval()
    logits = {"move": [], "item": [], "tera": []}
    with torch.no_grad():
        for i in range(0, len(built), 256):
            idx = np.arange(i, min(i + 256, len(built)))
            t = train_pv.to_torch(data, idx, "cpu")
            sp, de, gl, ma, hs, hd, x = t[0], t[1], t[2], t[3], t[7], t[8], t[-1]
            o = model(sp, de, gl, ma, hs, hd, aux=True, x=x)[3]
            for k in logits:
                logits[k].append(o[f"set_{k}"].float()[:, 6:12] if o[f"set_{k}"].shape[1] == 12
                                 else o[f"set_{k}"].float())  # fmt: skip
    lg = {k: torch.cat(v).log_softmax(-1).numpy() for k, v in logits.items()}

    eps = 1 / (2 * a.worlds)
    stats = collections.defaultdict(lambda: collections.defaultdict(float))
    for n, (d, per_slot) in enumerate(built):
        phase = "5-6" if d["left_opp"] >= 5 else "3-4" if d["left_opp"] >= 3 else "1-2"
        reveal = data["reveal"][n, 6:12]
        st_moves = data["sparse"][n, 6:12, 6:10] if data["sparse"].shape[2] >= 10 else None
        for j in range(6):
            bits = int(reveal[j])
            # -- moves: the labels not revealed at the position
            lab = [int(v) for v in data["set_move"][n, j] if v > 0]
            if lab and st_moves is not None:
                rev = {
                    int(st_moves[j, s])
                    for s in range(4)
                    if bits >> (4 + s) & 1 and st_moves[j, s] > 0
                }
                hidden = [m for m in lab if m not in rev]
                k = 4 - len(rev)
                if hidden and k > 0:
                    cnt = collections.Counter()
                    for moves, _, _ in per_slot[j]:
                        for mid in alpha_search.encode_ids("move", moves):
                            if mid > 0 and mid not in rev:
                                cnt[mid] += 1
                    tot = sum(cnt.values()) or 1
                    top_b = {m for m, _ in cnt.most_common(k)}
                    net = lg["move"][n, j].copy()
                    net[list(rev) + [0]] = -np.inf
                    net = net - np.logaddexp.reduce(net[np.isfinite(net)])
                    top_n = set(np.argsort(-net)[:k].tolist())
                    s = stats[("move", phase)]
                    for m in hidden:
                        s["n"] += 1
                        s["belief_hit"] += m in top_b
                        s["net_hit"] += m in top_n
                        s["belief_ll"] += math.log(max(cnt[m] / tot, eps))
                        s["net_ll"] += float(net[m])
            # -- item / tera: the label, if not revealed yet
            for key, bit, li, col in (("item", 1, "set_item", 1), ("tera", 3, "set_tera", 2)):
                lab = int(data[li][n, j])
                if lab <= 0 or bits >> bit & 1:
                    continue
                vals = [w[col] for w in per_slot[j]]
                ids = alpha_search.encode_ids("item" if key == "item" else "type",
                                              [v.lower() if key == "item" else v.upper() for v in vals])  # fmt: skip
                cnt = collections.Counter(i for i in ids if i > 0)
                tot = sum(cnt.values()) or 1
                s = stats[(key, phase)]
                s["n"] += 1
                s["belief_hit"] += bool(cnt) and cnt.most_common(1)[0][0] == lab
                s["net_hit"] += int(np.argmax(lg[key][n, j])) == lab
                s["belief_ll"] += math.log(max(cnt[lab] / tot, eps))
                s["net_ll"] += float(lg[key][n, j, lab])
    print(
        f"{'what':6} {'opp left':8} {'n':>6}  {'belief hit':>10} {'net hit':>8}  {'belief logp':>11} {'net logp':>9}"
    )
    for key in ("move", "item", "tera"):
        for phase in ("5-6", "3-4", "1-2"):
            s = stats[(key, phase)]
            if s["n"]:
                print(f"{key:6} {phase:8} {int(s['n']):6}  {s['belief_hit'] / s['n']:10.1%} {s['net_hit'] / s['n']:8.1%}  "
                      f"{s['belief_ll'] / s['n']:11.3f} {s['net_ll'] / s['n']:9.3f}")  # fmt: skip


if __name__ == "__main__":
    main()
