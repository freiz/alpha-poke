# Model card: alpha-poke v6arch-pp-v75 (release v0.1.0)

The policy / value network of alpha-poke, trained on human games only (behavior cloning and
game outcomes; no self-play). It is the starting point of the self-play line r2 and the network
the bot uses when it plays people. `scripts/fetch_model.py` downloads it with the opponent
models the search needs.

## Files

| file | what |
|---|---|
| `best.safetensors` | the network's weights (FP32; the shared embedding tables without the `emb.` prefix, as the Rust inference reads them) |
| `config.json` | input dimensions, sizes, input groups, auxiliary heads, validation metrics |
| `belief_model.pkl` | the opponent-set belief (team-conditioned priors over items, abilities, tera types, moves, spreads; `alpha_poke.agents.belief_state.BeliefModel`), built 2026-10-06 from 50k crawled replays and the Smogon usage statistics of 2026-09 |
| `reveal_model.pkl` | the move-reveal model (how likely a move would have been shown by now; negative evidence for hidden moves, `alpha_poke.belief.reveal`) |

The two `.pkl` files are Python pickles: load them only from this release, through
`fetch_model.py`, which checks every file's SHA-256 against the values in the repository
(a pickle-free format: #24).
They also need the Smogon usage statistics of 2026-09 (`gen9ou-1825`, downloaded from
smogon.com by `fetch_model.py`).

## Network

`TransformerPV` (`src/alpha_poke/train/model.py`), about 742k parameters: 12 Pokémon tokens
(both teams), a global token and 8 history tokens (the last decision steps of both sides);
3 pre-norm layers, d = 128, 4 heads, SwiGLU, RMSNorm, QK-norm.

- **Inputs** (computed by the Rust featurizer, the same function in training and in search):
  species / item / ability / tera / types / moves embeddings, HP, status, stats, boosts, side
  conditions, weather and terrain, what has been revealed, a static move table, matchup
  calculations (damage ratios and KO thresholds of the active Pokémon's moves, who moves
  first), counters (PP, Protect streaks, Substitute HP, sleep and other volatile durations),
  and both players' ratings (unknown in self-play and against people).
  The opponent's hidden fields are filled by a belief sample, not masked.
- **Outputs**: a policy over 14 action slots (4 moves, 4 moves + tera, 6 switches), a win
  probability (`logit = a * eval / 100 + b + net`: a learned residual over the engine's
  handcrafted evaluation), and auxiliary heads: the next 3 decision steps' actions (MTP-3), the
  opponent's sets, the remaining number of turns (used by the search's moves-left term).

## Training data

- Gen 9 OU games from public Pokémon Showdown replays: Metamon's dataset
  (`jakegrigsby/metamon-raw-replays`, to 2026-05) and the HolidayOugi dump
  (`HolidayOugi/pokemon-showdown-replays`, to 2026-10). 2,347,512 games, 46,071,040 positions
  (20 decision points per game, each rebuilt as the engine state seen by the player to act:
  its own team, the opponent's revealed information plus belief samples).
- Validation: the 500,000 positions of the games uploaded from 2026-04-23 on
  (`--val-cutoff 1776921722`); the HF dump only in training.
- Recipe: `scripts/build_training_data.py --name v75 --per-game 20 --since 2022-01-01
  --heldout`, then 6 epochs, batch 4096, lr 0.002, 2% warm-up, value loss capped at 4
  positions' worth per game; 65,722 steps, 110 minutes on an RTX 4070 Ti. Exported checkpoint:
  step 60,000 (best validation loss):

  ```bash
  uv run --group train python scripts/train_pv.py --data v75 --run v6arch-pp-v75 \
      --arch transformer --history --mtp 3 --feats reveal,num,movetab,matchup,elo,counter,count \
      --aux oppset,turns --d-ff 171 --ffn swiglu --norm rms --qk-norm --value-residual \
      --value-per-game 4 --epochs 6 --batch 4096 --lr 0.002 --warmup-frac 0.02 --stream 2 \
      --train-only hf- --val-cutoff 1776921722 --export best
  ```

## Reproducing it

About 100 GB of disk and 30+ GB of RAM for the large steps; run those under a memory cap
(`systemd-run --user --scope -p MemoryMax=30G ...`).

```bash
uv run python scripts/fetch_metamon.py               # Metamon's ~2M Gen 9 OU replays
#   the HolidayOugi dump: by hand for now (#23), to data/raw/replays_hf/gen9ou/*.parquet
uv run python scripts/fetch_smogon_stats.py --months 3
uv run python scripts/build_replay_tables.py         # replay tables (the belief models build on first use)
uv run python scripts/build_training_data.py --name v75 --per-game 20 --pool all --heldout --workers 12
# then scripts/train_pv.py with the recipe above (~2 h on an RTX 4070 Ti)
```

## Evaluation

Validation (human positions of the newest games):

| metric | value |
|---|---|
| policy cross-entropy (uniform over legal actions: 2.314) | 1.219 |
| policy top-1 / top-3 | 55.9% / 87.6% |
| value BCE (constant 0.5: 0.693) | 0.536 |
| value accuracy (early / mid / late game) | 71.7% (66.2 / 76.2 / 79.1%) |
| value calibration error (ECE) | 0.014 |

In search (ISMCTS, 32 belief worlds, CPU), against [Foul Play](https://github.com/pmariglia/foul-play),
paired games on real-game team pairs (each pair played twice, teams exchanged; ± 95% CI):

| time per decision (both sides) | win rate |
|---|---|
| 200 ms × 1 thread (`teams/pools/wide200`, 199 pairs) | 65.0% ± 4.1% |
| 200 ms × 1 thread (fair1000: real ladder teams, hidden sets from usage; 300 pairs, 2026-10-30) | 67.7% ± 3.5% |
| 5 s × 2 threads (wide1000, 108 pairs) | 67.1% ± 6.3% |

These compare two bots on our machine and our team pools; they say little about play against
people. Against people: a handful of friendly games (the first lost, against a ~1300 player);
no data against strong players; public ladder games are pending the bot account's
registration.

## Limitations

- It imitates human play (rating input unknown at inference): the search is what makes the
  bot stronger than the policy alone. It plays the most visited action (a pure strategy), which
  an adaptive opponent can exploit.
- Gen 9 OU only, the metagame and the rules of 2026-10. The belief is from 2026-10-06; the
  metagame has moved since (e.g. Zamazenta, Ogerpon-Wellspring, Gholdengo up), so its guesses
  of the opponent's sets are somewhat stale.
- The search's simulator (a patched poke-engine) approximates Showdown; known differences are
  tracked in the issues (labels `engine`, `state`).

## Use

For research and for playing on local servers or with people who agreed to play a bot. On the
official Showdown server a bot needs a registered bot account (the server's bot policy) and
must not be used for others in rated or tournament play.

The replays the network was trained on are public Showdown games; neither dataset states a
license. The weights are released for non-commercial research use. If you hold rights in this
data and object, please open an issue and we will remove the affected files.
