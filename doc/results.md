# Results ledger (training and evaluation)

A summary of the numbers, kept for later comparisons. The "key results" below are written by hand (with setup and conclusions); the tables at the end are regenerated from the logs by
`uv run python scripts/results_table.py --write` (`data/eval/*.jsonl`,
`data/train/*/runs/*`). Since 2026-10-06 every arena run writes `<log>.meta.json` (commit,
`ALPHA_*` environment variables, arguments, bot definitions, summary), so the generated tables carry the setup automatically.

Conventions: all win rates are side A's paired win rate ± 95% confidence interval (each pair of teams is played twice, sides swapped); "heldout" = the belief model does not include the evaluation team pool;
local Showdown server, 40-team pool (`data/teams/pools/replay40`). Elo ≈ 400·log10(p / (1 − p)).

## Offline: policy / value network (v1 data, 2026-10-06)

Data: Metamon Gen9 OU, 2,036,999 games × 4 decision points per game = 8.12M positions (train 7.88M, validation = the newest 3% of games, 244k).

| model | params | policy CE | top-1 | top-3 | value BCE | value accuracy | early / mid / late | ECE |
|---|---|---|---|---|---|---|---|---|
| uniform policy / constant 0.5 | — | 2.309 | — | — | 0.693 | — | — | — |
| handcrafted eval (fitted scaling sigmoid(a·eval/100+b)) | — | — | — | — | 0.5946 | 66.5% | — | — |
| handcrafted eval (the search's scaling 1.25·eval/100) | — | — | — | — | 0.6254 | — | — | — |
| v1 small (residual) | 208k | 1.445 | 47.7% | 82.4% | 0.5668 | 69.1% | 63.6 / 74.2 / 76.3% | 0.004 |
| **v1 medium (residual)** | 468k | **1.413** | **48.9%** | **83.2%** | **0.5625** | **69.5%** | 64.2 / 74.4 / 76.6% | 0.009 |
| v1 medium (plain value) | 468k | 1.418 | 48.8% | 83.1% | 0.5653 | 69.3% | 63.8 / 74.3 / 76.6% | 0.011 |
| v1 large (residual) | 1431k | 1.420 | 48.8% | 83.2% | 0.5634 | 69.6% | 64.3 / 74.4 / 76.9% | 0.020 (overfits, train−validation gap 0.135) |

Inference (Rust, CPU f32, single thread): forward pass 51 µs (value only 41 µs), featurization 1 µs; matches PyTorch (value difference 2e-6, policy difference 1e-5).

## Offline: v2 architecture comparison (small sample v2s, 2026-10-06)

Data v2s: 10% of the games (204k games) × about 12 positions per game = 2.42M; medium size, 6 epochs, residual value, the value loss counts at most 4 positions per game.
Anchor validation set: the 6,042 games / 71,777 positions of v2s uploaded at or after the v1 validation cutoff (1776921722) -- no model (v1 included) was trained on them (`scripts/eval_pv.py`, deleted).

| model | params | policy CE | top-1 | top-3 | switch top-1 | switch CE | value BCE | value accuracy | ECE | train−validation gap (policy / value) | GPU training samples/s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v1 medium MLP (full 2.04M games × 4) | 468k | 1.415 | 48.9% | 83.1% | 21.8% | 2.274 | **0.5629** | **69.3%** | 0.013 | 0.053 / 0.005 | 360k |
| v2s MLP | 468k | 1.532 | 44.4% | 79.9% | 18.2% | 2.421 | 0.5757 | 68.4% | 0.025 | 0.084 / 0.026 | 320k |
| v2s MLP + history | 525k | 1.495 | 45.7% | 80.6% | 20.2% | 2.355 | 0.5741 | 68.5% | 0.023 | 0.076 / 0.022 | 300k |
| v2s Transformer | 573k | 1.473 | 46.9% | 81.7% | 21.9% | 2.343 | 0.5754 | 68.7% | 0.030 | 0.120 / 0.034 | 130k |
| **v2s Transformer + history** | 598k | **1.419** | **49.0%** | 82.9% | **25.1%** | **2.225** | 0.5739 | 68.6% | 0.030 | 0.127 / 0.031 | 85k |

### History length (v2h: the same games and sampling as v2s, up to 32 history steps stored; anchor validation set as above, 71,773 positions)

| model | history steps | policy CE | top-1 | switch top-1 | value BCE | value accuracy | GPU training samples/s |
|---|---|---|---|---|---|---|---|
| Transformer + history | 8 | 1.418 | 49.1% | 25.3% | 0.5745 | 68.8% | 87k |
| Transformer + history | 16 | 1.418 | 49.0% | 25.2% | 0.5762 | 68.5% | 66k |
| Transformer + history | 32 | 1.415 | 49.1% | 24.6% | 0.5729 | 68.6% | 43k |
| MLP + history | 32 | 1.505 | 45.2% | 20.8% | 0.5747 | 68.6% | 208k |
| (control) v2s Transformer + history | 8 | 1.418 | 49.1% | 25.1% | 0.5741 | 68.6% | 85k |

Saturates after 8 steps: the 16 / 32-step differences (≤ 0.003) are the same size as the difference between repeated trainings (v2s and v2h differ by 0.0004 at 8 steps, but their data is nearly identical; the real seed variance was not measured), while the compute doubles / triples. MLP with 32 steps is no better than with 8 either (1.505 vs 1.495).

### MTP: multi-token action prediction (v2m: the same games and sampling as v2h, reproducible with PYTHONHASHSEED=0; Transformer + 8 history steps, MTP weight 0.5; anchor validation set, 71,776 positions)

| model | policy CE | top-1 | switch top-1 | switch CE | value BCE | value accuracy | ECE | train−validation gap (policy / value) | opponent current-action accuracy |
|---|---|---|---|---|---|---|---|---|---|
| baseline (no MTP) | **1.418** | **49.0%** | 24.8% | 2.229 | 0.5752 | 68.5% | 0.030 | 0.130 / 0.031 | — |
| + opponent's current action (mtp=1) | 1.438 | 47.9% | **25.9%** | **2.209** | 0.5710 | 68.7% | **0.013** | 0.089 / 0.009 | 37.9% |
| + both sides' next 3 steps (mtp=3) | 1.423 | 48.7% | 25.4% | 2.211 | **0.5679** | **69.0%** | 0.022 | 0.110 / 0.019 | 33.4% |
| (control) v2h 8 steps | 1.419 | 49.1% | 25.4% | 2.229 | 0.5744 | 68.7% | 0.027 | | |
| (reference) v1 full-data MLP | 1.414 | 49.0% | 21.8% | 2.273 | 0.5631 | 69.4% | 0.013 | | |

### MTP tuning (v2m, anchor validation set; the same data and seed)

| model | policy CE | top-1 | top-3 | top-5 | switch top-1 / top-3 | switch CE | value BCE | value accuracy | ECE | opponent action top-1 / top-3 |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline (6 epochs) | 1.418 | 49.0% | 83.1% | 93.8% | 24.6 / 58.6% | 2.229 | 0.5752 | 68.5% | 0.030 | — |
| MTP-3 weight 0.5 | 1.423 | 48.7% | 82.9% | 93.6% | 25.4 / 58.3% | 2.211 | 0.5679 | 69.0% | 0.022 | 33.4 / 62.7% |
| **MTP-3 weight 0.2** | **1.414** | **49.1%** | **83.2%** | 93.8% | 25.3 / **59.1%** | 2.215 | 0.5707 | 68.7% | 0.029 | 31.8 / 60.3% |
| **MTP-3 weight 0.5, per-step decay 0.5^k** | 1.420 | 48.8% | 82.8% | 93.6% | **26.3** / 58.5% | **2.198** | **0.5671** | **69.0%** | 0.022 | **36.0 / 65.7%** |
| baseline 10 epochs | 1.420 | 48.7% | 83.0% | 93.8% | 23.9 / 56.5% | 2.274 | 0.5755 | 68.7% | 0.032 | — |
| MTP-3 weight 0.2, 10 epochs | 1.418 | 48.7% | 83.0% | 93.7% | 24.0 / 57.9% | 2.213 | 0.5721 | 68.7% | 0.029 | 31.4 / 60.0% |

10 epochs overfit on 10% of the data (best at step 2500 / 5730, value train−validation gap 0.05–0.06).

### MTP seed variance (v2m, 3 seeds 0 / 1 / 2 per configuration, anchor validation set; mean ± standard deviation, Δ relative to the baseline, SE = standard error of the mean difference)

| configuration | policy CE | top-1 | top-3 | switch top-1 | switch CE | value BCE | value accuracy | opponent action top-1 / top-3 |
|---|---|---|---|---|---|---|---|---|
| baseline | 1.4182 ± 0.0032 | 48.9% | 83.1% | 25.0% | 2.225 ± 0.008 | 0.5728 ± 0.0027 | 68.6% | — |
| **MTP-3 weight 0.5 + decay 0.5^k (adopted)** | 1.4175 (Δ −0.001, 0.2 SE) | 48.9% | 82.9% | 25.7% | **2.199** (Δ −0.026, 5.5 SE) | **0.5672** (Δ −0.0056, 2.5 SE) | **69.1%** (+0.5, 4.6 SE) | **35.7 / 65.4%** |
| MTP-3 weight 0.2 | **1.4107** (Δ −0.0075, 2.7 SE) | **49.2%** (+0.3, 2.5 SE) | 83.2% | 25.5% | 2.204 (Δ −0.022, 2.9 SE) | 0.5706 (Δ −0.0022, 1.2 SE) | 68.9% | 31.5 / 60.3% |

Seed standard deviation: policy CE about 0.003–0.004, value BCE about 0.002–0.003 -- single-run differences below 0.005 are not trustworthy.

### Opponent prior: flipped view vs the MTP opponent head (`scripts/eval_opp_prior.py`, deleted; v2m anchor set, 62,572 positions)

Predicts the opponent's actual action this turn, projected onto the options of that position's world (one belief sample), tera merged (10 classes); the opponent's actual action is among the world's options in 79.9% of positions.

| opponent prior | top-1 | top-3 | NLL | forward passes per node |
|---|---|---|---|---|
| flipped-view main policy head (baseline model; what the search uses now) | **48.6%** | **82.6%** | **1.409** | 2 |
| MTP opponent head (our view, MTP-3 weight 0.5) | 43.6% | 77.8% | 1.571 | 1 |

### Network v3, first batch: features and auxiliary outputs (v3s = the same games and positions as v2m, plus the v3 columns; 3 seeds per group, anchor validation set; baseline = v2m's MTP-3 weight 0.5 + decay, 3 seeds)

A = public-information flags + global scalars + move property table; B = matchup calculations (damage / KO thresholds, effective speed, who moves first, entry hazard damage); C = auxiliary outputs (opponent sets, fainting this step, difference in remaining Pokémon, remaining turns). In parentheses: the difference from the baseline (in standard errors). "Value BCE (≥12 turns)" counts only positions from turn 12 on (the opening is close to a coin flip, see below).

| group | policy CE | top-1 | top-3 | switch top-1 | switch CE | value BCE | value BCE (≥12 turns) | value accuracy | ECE | opponent action top-1 |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 1.4175 | 48.9% | 82.9% | 25.7% | 2.199 | 0.5672 | 0.4979 | 69.1% | 0.024 | 35.7% |
| A | 1.3980 (−0.020, 4.5) | 49.7% | 83.5% | 26.0% | 2.181 | 0.5690 (+0.002, 1.1) | 0.5000 | 68.8% | 0.019 | 36.3% |
| B | 1.3673 (−0.050, 19) | 50.9% | 84.1% | 26.5% | 2.169 (−0.030, 6.7) | 0.5652 (−0.002, 1.1) | 0.4952 (−0.003, 1.5) | 69.3% | 0.023 | 36.6% |
| C | 1.4151 (−0.003, 0.8) | 49.0% | 83.1% | 25.6% | 2.193 | 0.5676 (+0.000) | 0.5002 | 69.1% | 0.022 | 35.7% |
| **ABC** | **1.3566 (−0.061, 17)** | **51.4% (+2.5)** | **84.4%** | **26.8% (+1.1)** | **2.153 (−0.046, 33)** | 0.5654 (−0.002, 0.7) | 0.4949 (−0.003, 1.5) | 69.2% | 0.030 | **37.0% (+1.3)** |

Opponent set head (C / ABC), only fields not yet revealed at prediction time, compared with a single belief sample in the position (favours the network: the network takes the most likely value, and a belief sample is among its inputs):

| | item | ability | tera type | moves (unrevealed, hit rate) |
|---|---|---|---|---|
| network (ABC) | 63.8% | 96.3% | 40.7% | 63.5% |
| single belief sample | 48.3% | 89.8% | 31.6% | 61.8% |

Other auxiliary heads (ABC): fainting-this-step accuracy 88.0%, difference in remaining Pokémon (13 classes) 23.9%, remaining-turns mean error 5.5 turns.

Value by game phase (baseline model / the handcrafted eval alone, a and b fitted on the anchor set): turns 0–5 0.658 / 0.675, turns 6–11 0.575 / 0.599, turns 12–19 0.507 / 0.544, turns 20–29 0.493 / 0.535, turns 30+ 0.468 / 0.511. Overall: constant 0.692, handcrafted eval 0.5956, model 0.567; without the network term, only a·eval + b, 0.598 (network term standard deviation 0.92 logit, correlation with the handcrafted eval 0.47).

### Full-data training (v5 = all 2.04M games, 20 positions per game drawn from a pool built from all decision points, 40.06M positions in total; `--stream 4`, 6 epochs)

Anchor set: all 61,121 games / 1.2M positions of v5 uploaded at or after 1776921722 (no model was trained on them). "All" metrics include every decision point, each kind in its real proportion.

| model | turn-start CE (all) | value BCE (all) | value BCE (biased subset) | value accuracy | ECE | voluntary switch top-1 / CE | forced switch top-1 | opponent action top-1 | opponent sets: item / tera / moves |
|---|---|---|---|---|---|---|---|---|---|
| v1 medium MLP (in use in the search) | 1.319 | 0.5575 | 0.5627 | 69.5% | 0.009 | 22.3% / 2.264 | 43.1% | — | — |
| v2m Transformer + history + MTP (10%) | 1.323 | 0.5631 | 0.5691 | 69.0% | 0.021 | 26.6% / 2.182 | 42.9% | 35.9% | — |
| v4s baseline, + A / B features (10%) | 1.274 | 0.5685 | 0.5691 | 69.0% | 0.023 | 26.6% / 2.156 | 42.7% | 37.0% | 68.0% / 45.3% / 66.3% |
| v4w final configuration (10%) | 1.236 | 0.5556 | 0.5699 | 69.3% | 0.036 | 23.0% / 2.301 | 55.1% | 37.5% | 68.6% / 46.4% / 67.2% |
| v5-nofeat same data, no v3 / v4 features (full) | 1.149 | 0.5320 | 0.5455 | 71.1% | 0.014 | 26.6% / 2.094 | 57.2% | 41.4% | — |
| **v5-final final configuration (full)** | **1.129** | **0.5277** | **0.5408** | **71.4%** | 0.013 | **27.3% / 2.075** | **57.7%** | **42.1%** | **71.2% / 49.7% / 70.2%** |

top-1 / top-3 (turn starts with a recorded move): v1 48.6% / 83.0%, v2m 48.6% / 82.8%, v4s 51.0% / 84.3%, v4w 51.4% / 84.5%, v5-nofeat 54.7% / 86.9%, **v5-final 55.6% / 87.4%** (top-5 95.8%); opponent action top-3: v5-final 73.2%. On the full data the v3 / v4 features gain less than on 10% of the data (policy CE −0.020 vs −0.06), but the gain is still certain.

v5-final: Transformer (d=128, 3 layers, 740k parameters, about 600k of them used at inference) + 8 history steps + MTP-3 (weight 0.5, decay 0.5) + features reveal / num / movetab / matchup / elo / counter + opponent set head, all decision points; training 99 minutes (including 28 minutes of cache building), about 59k samples/s.

### Network v6: an ablation of the counter features (`count`) (2026-10-15; v6 data = the same games as v5 reconverted with the current state construction, 45.98M positions; small model d 96 × 2 layers, 15,000 steps, same seed, anchor validation set 500k)

Positions "where the counters matter" = either side has a nonzero counter (Protect, Substitute, Wish, Future Sight, turns left of a lasting condition), a disabled move, sleep turns, or our active Pokémon has a move with ≤ 4 PP left: 9.7% of the validation set.

| metric | with count | without count | difference |
|---|---|---|---|
| policy CE (turn starts where the counters matter) | 1.1564 | 1.1649 | **−0.0085** (every checkpoint from step 4,000 on at −0.008 ~ −0.009) |
| value BCE (where the counters matter) | 0.5301 | 0.5321 | −0.0020 |
| policy CE (all turn starts, weighted) | 1.1903 | 1.1917 | −0.0014 |
| value BCE (all, weighted) | 0.5547 | 0.5549 | −0.0002 |
| remaining-turns mean error | 5.55 | 5.63 | −0.08 turns |
| MTP loss / opponent move hit rate | 2.797 / 66.8% | 2.789 / 67.2% | slightly worse (capacity / noise) |

Conclusion: the new features steadily improve the policy in the positions where they matter (about 1/6 of the v3 matchup feature group's overall gain); overall only −0.0014 because such positions are rare; kept.

### Network v6: human-data pretraining and self-play training (2026-10-15)

- **v6-h** (v5-glu's recipe + `count` + the remaining-turns head; v6 human data, HF games in training only, 6 epochs, 65,589 steps, 113 minutes) vs v5-glu (anchor validation set, the same games): policy CE (turn starts, weighted) 1.1227 / 1.1345, value BCE (all, weighted) 0.5409 / 0.5439, top-1 56.2% / 55.9%, ECE 0.0124 / 0.0134, opponent action 42.7% / 42.2%, remaining-turns error 5.25 turns. (v6-h also has the HF games as training data, so not all of it is the new features' credit.)
- **v6-s** (from v6-h, all self-play data sp0–sp7: 15.85M positions (at most 50 per game), policy targets 3 passes; 20% human; 13,806 steps, lr 4e-4; `--sp-stream 1500000`). Value schedule comparison (each result learned only once):

| | v6-h (start) | first | spread |
|---|---|---|---|
| self-play value BCE | 0.4822 | 0.4530 | **0.4387** (root q: 0.4350) |
| self-play policy CE / top-1 | 1.4720 / 63.5% | 1.2890 / 72.6% | 1.2904 / 72.5% |
| human value BCE (weighted) | 0.5409 | **0.5453** | 0.5485 |
| human policy CE (weighted) | 1.1227 | 1.1636 | 1.1639 |
| remaining-turns error (self-play) | 6.81 | 5.57 | 5.57 |

spread's self-play value is clearly better (cumulative value weight about 3 times first's), its human value slightly worse; the policy is the same.
- Games (1,600 iterations, GPU pipeline, no fallback): **spread vs first 52.38% ± 2.60%** (600 pairs, wide1000; interval 49.8%–55.0%, leaning to spread, not significant); **v6-s-spread vs sp-gen7 49.67% ± 2.45%** (600 pairs, ab600b; interval 47.2%–52.1%, even): one training from scratch (human pretraining + all the self-play data, about 2.5 hours) matched the network trained generation by generation over 8 generations.
- **Remaining-turns term (fast wins, v6-s-spread on vs off, 1,600 iterations, 600 pairs)**: ml1 (slope 0.005 / turn, cap 0.03, threshold 0.5, both sides) **51.58% ± 2.53%** (wide1000), games won by the side with it on average 32.3 turns (median 26) vs 38.1 (28); ml2 (0.01, 0.05, 0.3, both sides) **51.33% ± 2.35%** (ab600b), 33.8 (26) vs 38.9 (28). But 8 / 6 games reached the 300-turn cap (with it off on the same pool, 2–5 / 2 per 1,200 games): the cap counts as a draw, so "the side behind prefers longer" means stalling to the cap; added an option for the side ahead only (`edd72a4`). ml3 (ml1's parameters, side ahead only) **50.96% ± 2.42%** (new pool wide600c), games won 33.7 (26) vs 36.3 (27); 5 games at the cap (one pair hit the cap in both games, a structural team pair where both sides stall; the other 3 games are in line with the baseline). ml3 adopted as v6's default (`SEARCH_ML`).
- **vs Foul Play (2026-10-15, 200 ms each, wide200, 200 pairs, same day and conditions, fast-win term off)**: **v6-s-spread 64.32% ± 4.27%** (199 pairs), **sp-gen7 63.69% ± 4.08%** (199 pairs; sp-gen6 on 10-13 was 64.3% ± 4.6%): outside the self-play environment it is as strong as sp-gen7.
- Training speed: all 8 generations of self-play data memory-mapped come to 42 GB, and random disk reads ran at only 1/30 of normal speed (about 1,000 samples/s, stopped); after switching to chunked streaming reads (`SpStream`), about 40,000 samples/s.

### Network v7 input-group ablation (2026-10-19; v7 data = the same games reconverted with the current state construction, including the two fixes for fallback matchups / available slots, 45.98M positions; small model d 96 × 2 layers, 15,000 steps, seed 0, anchor validation set 500k; design in design.md, appendix to D13)

Baseline = v6's 7 groups (`reveal, num, movetab, matchup, elo, counter, count`); each row adds one group to the baseline. Subsets (`v7_subsets` in `train_pv.py`): ko2 = our active Pokémon has a 2HKO but no OHKO, or a priority KO (30%); tera = we can still terastallize (61%); tera turns = the player terastallized on this step (2.5%); endgame = ≤ 6 Pokémon alive on both sides combined (18%); post = the belief worlds disagree on the consequences for our active Pokémon (some probability between 0.1 and 0.9, 26%).

| group | policy CE (turn starts, weighted) | value BCE (all, weighted) | top-1 | ECE | ko2 subset CE | tera-turn CE / top-1 | endgame BCE / CE | post subset CE | best_val_loss |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 1.195 | 0.5540 | 53.4% | 0.0113 | 1.181 | 3.01 / 7.7% | 0.4175 / 0.938 | 1.227 | 1.749 |
| + ko2 (F3a) | −0.002 | +0.0045 | 0 | 0.0108 | −0.003 | −0.03 / 8.9% | +0.0056 / −0.004 | −0.002 | 1.751 |
| + tera (F6) | −0.010 | +0.0044 | +0.3% | 0.0108 | −0.013 | **−0.22 / 12.4%** | +0.0048 / −0.013 | −0.012 | 1.744 |
| + team (F5) | −0.005 | +0.0016 | +0.2% | 0.0109 | −0.003 | −0.03 / 8.7% | +0.0010 / −0.007 | −0.006 | 1.746 |
| + post (F2) | **−0.028** | −0.0018 | +1.5% | 0.0106 | −0.032 | −0.05 / 9.2% | −0.0029 / −0.032 | −0.046 | 1.719 |
| all | **−0.040** | **−0.0024** | **+1.8%** | **0.0100** | −0.048 | **−0.29 / 13.3%** | −0.0027 / −0.043 | −0.059 | **1.706** |
| all − ko2 | −0.039 | −0.0016 | +1.8% | 0.0109 | −0.046 | −0.28 / 13.1% | −0.0020 / −0.044 | −0.060 | 1.708 |

- On the policy every group gains, roughly additively; post the most, tera concentrated on tera decisions (tera-turn top-1 from 7.7% to 12.4%).
- ko2 / tera / team alone each make the value 0.002–0.0045 worse than the baseline, while post alone and all groups together make it better: probably initialization noise from the changed input dimension under the same seed (v7's 45-dim entity columns are added as a whole when any group is on, and masked only per group); no multiple seeds, no conclusion.
- ko2 alone shows no gain; all groups minus ko2 is slightly worse on value, ECE and the ko2 subset (the gaps within noise, the direction consistent), the compute cost is small, v0 keeps all groups.
- post samples the opponent sets only from the information revealed at the time (the same belief as the single world in the network's input); it reads no future information.

### Network v0-post: human pretraining on v7 data, with F2 `post` (2026-10-19; far ahead offline, weaker with search, dropped; the current v0 is in the next section)

v6-h's recipe (medium, d 128 × 3 layers, d_ff 171, 6 epochs, 65,590 steps) + all v7 input groups (`ko2, tera, team, post`), v7 data, `--stream 3` (memory cap 38G; with `--stream 4` it was killed once by system memory pressure), 121 minutes. Anchor validation set: the same games from the two conversions, position counts differ by less than 1 in 10,000.

| metric | v0 | v6-h | difference |
|---|---|---|---|
| policy CE (turn starts, weighted) | **1.0799** | 1.1227 | **−0.043** |
| value BCE (all, weighted) | **0.5309** | 0.5409 | **−0.010** |
| top-1 | **58.2%** | 56.2% | +2.0% |
| value accuracy / ECE | 72.5% / **0.0091** | 71.8% / 0.0124 | |
| switch-turn CE / top-1 | 2.014 / 28.7% | 2.036 / 28.2% | |
| CE in positions where the counters matter | 1.051 | 1.089 | −0.038 |
| remaining-turns error | **4.85** | 5.25 | −0.40 turns |
| opponent action hit rate | 42.9% | 42.7% | even |
| opponent set head (item / tera) | 70.8% / 48.8% | 70.9% / 49.2% | even |
| tera-turn CE / top-1 | 2.394 / 20.9% | — | |
| best_val_loss | **1.611** | 1.664 | |

The policy gain on the medium model is the same as in the small-model ablation (−0.040), the value gain larger (−0.010 vs −0.0024). `check_tnet`: Rust = PyTorch to 1.5e-5 (4,000 positions, both views, top choice 100% the same); `check_batch_search`: GPU = CPU to 2e-5, top choice the same as the unbatched CPU search 90% of the time (82% between two CPU seeds).

Search cost (`check_batch_search`, 60 positions, 2,000 iterations, 8 worlds): GPU batched v0 7,110 leaves / s vs v6-h 9,142 (**22% slower**, the v7 inputs' damage calculations run on the CPU); CPU single thread 3,148 vs 3,460 (9% slower).

**Games (wide1000)**: with search (GPU batched, 1,600 iterations, ml3) v0-post vs v6-h **46.79% ± 2.59%** (530 pairs, about −22 Elo, significantly weaker); without search (`p_m*`, the network's own policy, averaged over 4 belief worlds, tau 0.05, 500 pairs) **55.15% ± 2.60%** (about +36 Elo, significantly stronger). The same comparison with small models (v7-small-*, wide1000):

| A vs B | without search (500 pairs) | with search (1,600 iterations, 300 pairs) |
|---|---|---|
| v7 baseline vs v6 baseline (v6-small-count, same recipe, only the data changed) | — | 51.75% ± 3.42% |
| all groups vs baseline | **53.50% ± 2.66%** | **46.25% ± 3.65%** |
| post vs baseline | 50.40% ± 2.66% | 48.92% ± 3.43% |
| tera vs baseline | — | 50.67% ± 3.34% |

The network itself is stronger, but weaker with search, and the v7 data itself is fine. The cause is how `post` enters the search (in-tree check: 5 positions, 14k leaf rows, ent4 / post 100% nonzero, the root rows bit-identical to the reference features; no input is lost):

- `post` is computed once at the root from all the root worlds and reused through the whole tree (not updated in the tree). v0-post leans on it heavily: on the same 6,000 human positions, with `post` replaced by the one from the same game and side's previous decision point (simulating one step of staleness in the tree), value BCE 0.5148 → 0.5264, policy CE 1.144 → 1.276, the win-probability estimate shifts by 0.049 on average; with all zeros, 0.5661 / 1.792. The whole post group's offline gain is only about 0.03 policy CE, and the values of leaves in the tree are systematically biased.
- At nodes in the opponent's view, the opponent's "own" set slots hold our posterior (fractions); in training one's own side never had fractions (from v7.1 on).
- In the v7 data the 3 extra belief worlds also resampled our unrevealed sets, so our posterior rows were fractions (found in review, fixed in v7.1); in real games our sets are known, only 0 / 1.

Conclusion: `post` stays out of v0; to use it, its in-tree use needs a redesign (leaves recompute the consequence columns from their own world; training mixes 1-world and 4-world posteriors), see issue #11.

### Network v0: human pretraining on v7.1 data, without `post` (2026-10-20; the starting point of the self-play restart)

v6-h's recipe (medium, d 128 × 3 layers, 6 epochs) + `ko2, tera, team` (no `post`), v7.1 data (`--pool all --per-game 20 --heldout`, streamed out), `--stream 3`, memory cap 36G, 115.6 minutes. Model `data/train/v71/runs/v0-v71` (renamed 2026-10-20: the v7.2 v0 is at `data/train/v72/runs/v0`).

| metric | v0 | v0-post | v6-h |
|---|---|---|---|
| policy CE (turn starts, weighted) | 1.1136 | 1.0799 | 1.1227 |
| value BCE (all, weighted) | 0.5372 | 0.5309 | 0.5409 |
| top-1 | 56.4% | 58.2% | 56.2% |
| value ECE | 0.0109 | 0.0091 | 0.0124 |
| switch-turn CE | 2.041 | 2.014 | 2.036 |
| remaining-turns error | 5.26 | 4.85 | 5.25 |
| opponent action hit rate | 43.0% | 42.9% | 42.7% |
| tera-turn CE / top-1 | 2.458 / 20.9% | 2.394 / 20.9% | — |
| best_val_loss | 1.651 | 1.611 | 1.664 |

Offline slightly better than v6-h (policy −0.009, value −0.004); the post part of the gain is gone. `check_tnet` and `check_batch_search` pass.

**Games (vs v6-h)**:
- Without search (`p_m*`, averaged over 4 belief worlds, tau 0.05, wide1000, 500 pairs): 49.5% ± 2.66%.
- With search (GPU batched, 1,600 iterations, ml3): wide1000 **51.92% ± 2.49%** (600 pairs); ab600b 49.83% ± 2.35% (597 pairs, stopped short of the last few pairs).
- Combined **50.9% ± 1.7%** (1,197 pairs, about +6 Elo, not significant); 0 search fallbacks on either side (after the L229 fix).

Note: v0 uses the v7.1 inputs (`EXTRA_VERSION` 2). After review the features were fixed (v7.2, see the next section) and the entity input went from 45 to 50 dims; this v0 cannot read the new inputs directly and has to be retrained on the new data.

Conclusion: v0 is as strong as v6-h. Its value is that it is clean: its inputs match the current state construction (tera type convention, fallback matchups, L1–L229), and its policy targets do not come from searches on the old engine. It is the starting point of the self-play restart and is not mixed with the old self-play data of generations 0–8.

### Network v0 (v7.2): human pretraining on v7.2 data (2026-10-21; the starting point of the self-play restart)

The v7.1 v0's recipe with the data changed to v7.2 (`EXTRA_VERSION` 3, see the next section; 2,348,551 games, 46,050,050 positions, 5.1 hours to build the data), `--stream 2` (3 went over the 36G cap and was killed once: the entity input is 50 dims), 116 minutes. Model `data/train/v72/runs/v0`.

| metric | v0 (v7.2) | v0-v71 | v6-h |
|---|---|---|---|
| policy CE (turn starts, weighted) | **1.1103** | 1.1136 | 1.1227 |
| value BCE (all, weighted) | 0.5395 | **0.5372** | 0.5409 |
| top-1 | **56.6%** | 56.4% | 56.2% |
| tera-turn CE / top-1 | **2.428 / 21.6%** | 2.458 / 20.9% | — |
| switch-turn CE | **2.027** | 2.041 | 2.036 |
| best_val_loss | **1.649** | 1.651 | 1.664 |

`check_tnet`: Rust = PyTorch to 1.1e-5, top choice 100% the same; `check_batch_search` passes. Search speed (60 positions, 2,000 iterations, 8 worlds): GPU batched 3,539 leaves / s vs v6-h 5,676 (**38% slower**), CPU single thread 2,366 vs 3,373 (30% slower).

Games (vs v6-h, GPU batched search, ml3, wide1000, 600 pairs each):
- The same 1,600 iterations: **48.92% ± 2.37%**;
- Equal time (by the speed ratio, v0 1,000 iterations vs v6-h 1,600): **49.21% ± 2.44%**.

Even with v6-h (v0-v71 was 50.9% ± 1.7%; the difference is within noise): the fixed features brought no visible change in strength, and 38% fewer iterations did not make it weaker either. 3 searches fell back to the heuristic (out of 2,400 games; on both sides): the engine's evaluation hit a +7 stat stage (`Invalid boost value: 7`); not reproduced (158k random steps, all 1.03M move combinations with stat stages at their limits, combinations of abilities such as Contrary / Simple: none went out of bounds); diagnostics added: the search checks stat stages before evaluating and prints the position when out of bounds (`evaluate_checked` in `bsearch.rs`), and when a batched search fails, all the root's worlds are written to `data/selfplay/diag/search_failures.jsonl`.

### Network v6arch-pp-v75: human pretraining on v7.5 data (2026-10-26; the starting point of r2 self-play)

v6arch-pp's recipe (v6's 7 input groups, 6 epochs, lr 0.002) with the data changed to v7.5 (the state construction of 2026-10-26: after S158–S159; 2,347,512 games, 46,071,040 positions, train 44,866,526 / validation 500,000), 65,722 steps, 110 minutes. Model `data/train/v75/runs/v6arch-pp-v75`.

| metric (validation set) | v6arch-pp-v75 | v6arch-pp (v7.3) |
|---|---|---|
| policy CE | 1.219 | **1.206** |
| top-1 | 55.95% | **56.21%** |
| value BCE | 0.5381 | **0.5354** |
| value accuracy | 71.61% | **71.88%** |

Slightly worse offline (the validation set was also converted with the new construction, so not quite the same yardstick). Vs Foul Play (200 ms × 1 each, wide200): v75 **65.0% ± 4.1%** (199 pairs), v7.3 **68.4% ± 4.1%** (200 pairs), paired difference −3.7 ± 5.1, not significant. r2 self-play starts from v75: its inputs match the current code's state construction.

### Public position key `phase_key` (2026-10-22)

`phase_key` splits child nodes one level further by the public position after the outcome (both sides' active Pokémon, whether either side must switch), so that, for example, a damage roll that KOs and one that does not go to different nodes (search review section 2, "Search self-review" below). A/B setup: v6-h vs v6-h, side A with it on, GPU batched search, 1,600 iterations, ml3.

| pool | side A (on) win rate |
|---|---|
| wide1000 (600 pairs) | 52.08% ± 2.37% |
| ab600b (600 pairs) | 49.33% ± 2.37% |
| combined (1,200 pairs) | about 50.7% ± 1.7% |

No gain; the default stays off. This agrees with the conclusion in D12, where "splitting by observable outcome" was removed: open-loop merging at this level (4.6% repeated visits) matters little for strength. The two sets of 1,200 games took 4,224 s and 4,219 s; moving the child lookup within the GPU descent did not slow the search.

In the ab600b set the side with it off had 2 search failures, from the engine's +7 stat stage (`engine-diff.md` L231, fixed). The 3 unreproduced fallbacks of 10-21 had the same error (`Invalid boost value: 7`) and very likely the same cause, but the positions were not saved then, so it cannot be confirmed.

### Search self-review (2026-10-21 / 22, formerly `search_review.md`)

6 points from an external review plus 4 from a re-review, each verified in the code and fixed (17 items in total, in `rust/alpha_search`'s ismcts.rs / bsearch.rs, search_player, batcher): the root prior is now the mean over all worlds (it used to come only from the first world: mean L1 to the 16-world mean 0.042, maximum 0.229) and is renormalized over the available options; the CPU-cached logits did not line up with the options; position evaluation panicked at a +7 stat stage (Dauntless Shield / Intrepid Sword still boost at +6, engine L231); the root noise was added only to the last world's options; the opponent's root prior is now conditioned on the current world; the GPU root evaluation broke the batch size limit; the CPU timing left out the root evaluation (200 ms was actually about 261 ms); the alignment of in-tree history and turn count in the pivot / switch phases (items 11–17, including Struggle having no action slot). The items not yet fixed (open-loop merging of different public positions, the opponent seeing through our sets in the tree, only the most-visited pure strategy taken at the end, non-root priors set only once) moved to GitHub issues #7, #8, #10. Verification tools: `scripts/check_search_worlds.py`, `tests/test_search_worlds.py`, the ignored tests `measure_cached_logits_fit` and `matrix_games` in ismcts.rs.

### Vs Foul Play: after the search review fixes (2026-10-22)

The same conditions as 10-15 (`data/selfplay/diag/run_fp_v72.sh`): our CPU search `s_ismcts_ma`, 200 ms × 1 each side, wide200, 200 pairs, fast-win term off. The search includes the fixes for the root prior mean and the CPU-cached logits (`1ae1b66`, `217f32f`).

| network | vs Foul Play |
|---|---|
| v6-s-spread (anchor; 10-15 with the old search 64.32% ± 4.27%) | **67.59% ± 4.11%** (199 pairs) |
| v6-h | 65.66% ± 4.11% (198 pairs) |
| v0 (v7.2) | 65.75% ± 4.37% (200 pairs) |
| v6arch | 65.03% ± 4.58% (198 pairs) |

- **This round was not at equal time (10-22 re-review)**: the CPU search's timing left out the root evaluation and checked the clock only every 256 iterations, so our side actually took about 250–270 ms per move (Foul Play 200 ms). The 10-15 anchor also overran its time, so "the anchor is 3.3 points higher than before the fixes" cannot be counted as the effect of the search fixes; withdrawn.
- The four networks are within 2.6 points of each other, inside the ±4.3% interval. Against an outside opponent no gain from the v7.2 networks shows either, the same conclusion as the self-play A/B.
- No search fallbacks in 1,595 games. 5 games failed, all from Foul Play process crashes (`can_z` AttributeError, also seen on 10-13; `Total of weights must be greater than zero`), removed by pair.

**Strict equal-time rerun (10-22 afternoon, `run_fp_v72b.sh`)**: the timing includes the root evaluation and checks the clock every 16 iterations (a 200 ms budget measured 203–207 ms), and the re-review's fixes are in (the opponent's root prior conditioned per world, root noise covering all options, the root evaluation batched).

| network | vs Foul Play |
|---|---|
| v6-s-spread | **70.37% ± 4.05%** (200 pairs) |
| v6-h | 64.82% ± 4.12% (199 pairs) |
| v0, v6arch | not finished: stopped to deal with the third re-review's issues first |

Our side had about 20% less time and the results did not drop. v6-s-spread (trained with self-play data from generations 0–7) is 5.6 points above v6-h, at the edge of significance.

### Policy / value cross-evaluation: which half of v0 (v7.2) helps (2026-10-22)

`gpu_net.CrossNet`: one side's priors come from one network and its leaf values from another. GPU batched search, 1,600 iterations, ml3, wide1000, 600 pairs each, the opponent always v6-h; the search includes the root prior mean fix.

| side A (policy + value) | vs v6-h |
|---|---|
| v0's policy + v6-h's value | 50.88% ± 2.42% |
| v6-h's policy + v0's value | 50.33% ± 2.39% |

Neither half swapped in alone gives a visible gain, consistent with the whole network's 48.92% ± 2.37% vs v6-h: v0's policy CE is 0.012 better and its value BCE 0.0014 better, and under this search none of these offline improvements shows up as strength. No search fallbacks in 2,400 games.

### Search review fixes: root prior as the mean over all worlds, the GPU path passes the configuration (2026-10-21)

The fourth review pointed out six problems; each was checked in the code and all hold. This section fixes two of them:
- The root prior used to come only from the first belief world (`bsearch.rs` evaluates the root only once, `ismcts.rs` sets the prior only at the first expansion); it is now the mean of the network priors over all worlds. When an option is not in a world, that world counts it as 0. PUCT selection renormalizes the prior over the available options.
- The GPU search did not pass `ml` / `policy_opponent` to `BatchSearch`; now it does. The defaults are the same as before, so existing games are unaffected.

Test: `tests/test_search_worlds.py` builds two worlds A, B (in B the opponent's lead has double the speed); on both the GPU and the CPU path, the root priors of [A, B] and [B, A] are the same and equal the mean of the two.

The check on real belief worlds, `scripts/check_search_worlds.py`: v6arch, 100 replay positions, 16 worlds each, drawn the way the training data is, 1,600 iterations.

| comparison | visit distribution TV | same top choice |
|---|---|---|
| different seed (the search's own noise) | 0.069 | 88% |
| shuffled world order (same seed) | 0.067 | 90% |

Shuffling the order matters about as much as seed noise. The old way's error (L1 between the first world's prior and the 16-world mean) averages 0.042, median 0.033, maximum 0.229. The problem is real but small on average, so there was no separate strength A/B (the resolution of 600 pairs is about ±2.4%).

### Is it the data: v6's input groups + v7.2 data (v6arch, 2026-10-21)

v6-h's recipe and input groups (`reveal, num, movetab, matchup, elo, counter, count`, without v7's `ko2 / tera / team`), with the data changed to v7.2 (the v3 inputs also the fixed `EXTRA_VERSION` 3), `--stream 2`, 143.5 minutes. Model `data/train/v72/runs/v6arch`.

| metric | v6arch | v0 (v7.2) | v6-h |
|---|---|---|---|
| policy CE (turn starts, weighted) | 1.1173 | **1.1103** | 1.1227 |
| value BCE (all, weighted) | 0.5400 | **0.5395** | 0.5409 |
| top-1 | 56.2% | **56.6%** | 56.2% |

Games (GPU batched search, 1,600 iterations, ml3, wide1000, 600 pairs each):
- v6arch vs v6-h (only the data differs): **50.54% ± 2.41%**;
- v6arch vs v0 (v7.2) (same data, only v7's three input groups differ): **50.04% ± 2.39%**.

Conclusion: it is not the data; the new data (along with the fixed v3 feature definitions) is neither worse nor better than the old; v7's three input groups are slightly better offline (policy CE −0.007), show no visible gain with search, and make the search 38% slower. The three networks are at the same level: under the current training recipe and the current search, the v7.2 network improvements showed no gain in strength; this does not show that the features are useless or that human pretraining has hit its ceiling (the search has a few flaws that may swallow network improvements, still to be looked at: the root prior from only one world, public outcomes not split into nodes under open loop, the opponent seeing through our sets; the 2026-10-21 review, issue #18). No search fallbacks in these 2,400 games, and the bounds check printed no position.

### Feature assertion checks (2026-10-20; `EXTRA_VERSION` 3, design.md, appendix to D13 "v7.2 inputs", doc/engine-diff.md L230 / lesson 11)

It started from another model's review. Each point was first reproduced in Showdown (`tests/test_feature_claims.py` uses the same positions), and the old features were all wrong:
- Endeavor into Normal-type Blissey: Showdown 478, feature 0; into Ghost-type Dusknoir: Showdown 0, feature 102. Final Gambit was reversed the same way.
- Two Super Fangs / Ruinations: Showdown 714 → 357 → 179, ko2 judged "possible 2HKO".
- Tera Normal Toxapex holding Black Sludge: Showdown takes 1/8 per turn and two Seismic Tosses KO; ko2 treated it as healing and judged no.
- Slush Rush Cetitan in snow vs Jolly Garchomp: in Showdown Cetitan moves first, the feature judged the opponent moves first.
- Also found: multi-hit moves counted as one hit (Scale Shot 114, Showdown hits 4 times for 329); always-crit moves counted as not critting; charge moves, Future Sight and Fake Out (usable only on the first turn out) also counted as immediate KOs; KOs ignored Substitute and Focus Sash.
- `team`'s "answer" (survives a hit and 2HKOs) ignored speed and the free hit taken on the switch-in: Kingambit vs Garchomp (slower, losing 82% per hit, dealing 51%) was judged an answer; in Showdown it loses.

Causes: the features copied the engine's rules (the copy lagged behind engine fixes), the borrowed fixed-damage branch was not on the transition path (and the damage differential test happened to exclude Endeavor), and the combined claims had never been compared with actual outcomes.

**Check method** (`scripts/check_feature_claims.py`): on real positions (1,000 positions from real games, both views), each claim of the features is put under its own assumptions and verified with engine transitions (100% consistent with Showdown): no chance events (engine switch `set_no_chance`: no crits, no misses, no full paralysis, no chance-based secondary effects), the target does not act (OHKO / 2HKO), each side uses one fixed move (trading hits). "Certain" claims must hold 100% in the transition; "possible" claims must have a branch where they hold.

| claim | checks | false (claimed yes, the transition does not hold) | missed (claimed no, always holds in the transition) | unknown | unverifiable |
|---|---|---|---|---|---|
| who moves first | 1,582 | 0.63% | — | — | — |
| certain OHKO | 3,698 | 0.22% | 0.43% | — | — |
| possible OHKO | 3,698 | 0.46% | — | — | — |
| certain KO within two hits | 3,347 | 0.54% | 1.70% | — | — |
| possible KO within two hits | 3,347 | 0.57% | — | — | 74 |
| reliable switch-in answer | 6,001 | 0.62% | 1.98% | 24.3% | — |
| possible switch-in answer | 6,001 | 0.70% | — | 24.2% | 197 |
| reliably wins a head-on trade | 1,546 | 0.97% | 2.07% | 17.5% | — |
| reliable revenge kill | 6,473 | 0.93% | 2.58% | 0.2% | — |

- A second review (same day) found 4 more in the exchange simulation, each reproduced with a concrete position and fixed, with combined regression tests added (`tests/test_feature_claims.py`): a multi-hit move breaking a Substitute passed the whole overflow on to the Pokémon (Dragonite whose Dragon Darts break a Substitute: the old judgment "possible KO", Showdown leaves 48 HP); on the switch-in turn Sucker Punch was treated as hitting (Enamorus switching into Kingambit: the closest game is won with only 2 HP left; one more hit and it loses); over multiple turns the first turn's end-of-turn change was reused (Toxic at a constant 1/16 per turn: Clefable vs Jolteon's head-on trade judged a loss, Showdown wins); `eot_on` returned early without restoring the HP it had changed.
- A third review found 3 more, each reproduced and fixed: the end of turn was precomputed together "for both sides' j-th Pokémon" (Cloud Nine and the like depend on the specific opponent: in a sandstorm, only swapping the slots of the opponent's two reserves Golduck and Snorlax turned the switch-in answer for the same matchup from a win into a loss) -- now cached by the actual matchup's context, with a structural test added (swapping reserve slots must only permute the inputs, not change the values: 12,000 checks on 3,000 real positions; the previous commit failed on real positions at once); ko2 did not track the attacker's HP (an Earthquake from a 1 HP Life Orb holder was judged a 2HKO; in fact it faints after the first hit); the end of turn measured the net change at 3/4 HP (a 400 HP Wish restoring 200 measured only 100, judged a 2HKO; in fact 80 left after two hits) -- now recovery and damage are separate and measured on unclamped HP. Also the "only one answer" flag was replaced by "how many have an unknown outcome", and "the only answer" renamed "the only confirmed answer". The numbers in the table are from after the third round of fixes (little changed: the fixes are for rare combinations, but they made the inputs vary with team order).
- "Unknown" is the result of the second round's tightening: a head-on trade that meets an unsupported mechanic (`unsupported`, design.md, appendix to D13) gives no win or loss. Most of the remaining "unknown" comes from Booster Energy not yet activated (4.7% of Pokémon), Weak Armor (1.4%), Libero / Protean (2.1%), Red Card / Eject Button / Eject Pack (1.6%), Defiant / Weakness Policy / Speed Boost and so on; a few go beyond 4 turns. Support follows item by item by frequency. Air Balloon (3.7%), items removed by Knock Off, resist berries and Sitrus Berry are supported (at the first tightening "unknown" was 35%).
**Showdown directly as the ground truth** (`scripts/check_feature_claims_sd.py`, 2026-10-20): random battles (the differential test's team pairs, 300 games); every 4 decision points the whole Showdown battle is serialized, and in that battle each claim is played out under its own assumptions (`enginecheck/showdown_claims.js`: moves always hit; `randomChance` is true only when certain -- no crits, no paralysis, no chance-based secondary effects or abilities; damage rolls and hit counts fixed per claim, "certain / reliable" with our lowest and the opponent's highest, "possible" the other way round). Each claim gets one deterministic game, and two-hit "possible" claims can be verified too (the "unverifiable" part of the engine check).

| claim | checks | false | missed | unknown |
|---|---|---|---|---|
| who moves first | 4,532 | 0.09% | — | — |
| certain / possible OHKO | 10,865 / 10,886 | 0.12% / 0.28% | 0.17% | — |
| certain / possible KO within two hits | 10,003 / 10,024 | 0.38% / 0.66% | 0.41% | — |
| reliable / possible switch-in answer | 14,120 / 14,105 | 0.56% / 1.13% | 0.28% | 28% |
| reliably wins a head-on trade | 4,614 | 0.35% | 0.33% | 18% |

- It found several problems the engine check could not see, all fixed: pivot moves (U-turn and the like) treated as usable twice in a row / as the fixed move of a head-on trade (in Showdown the user switches out after using one); Future Sight counted as one hit within two turns (it hits only after the end of its second turn); switch-in entry effects were left out of head-on trades -- Intimidate, Intrepid Sword / Dauntless Shield, Sticky Web's speed drop; now the stat stages are read from the engine's switch-in entry, and entries that change weather / terrain give unknown; Explosion / Self-Destruct make the user faint; two-hit "possible" did not include "certain" (Sitrus Berry makes the highest roll fail to KO); Flame / Toxic Orbs not yet activated give unknown (Guts after the burn, halving).
- Two problems in the check script itself also came out here and were corrected: Showdown's secondary effects use `random(100)` rather than `randomChance` (they need separate filtering); after tera the species name changes, so matching is now by team slot.
- **Invariant and metamorphic tests** (`invariants` in `extra.rs`; the `--ignored` version runs thousands each on real positions and random-battle positions): certain ⇒ possible (OHKO, 2HKO, priority, tera, threat), OHKO ⇒ within two hits, reliable ⇒ possible answer, confirmed + unknown ≤ number alive, and when the opponent's HP drops, the KO flags and the number of reliable answers do not decrease (excluding the cases where the rule itself is not monotonic: HP-dependent moves and abilities, draining moves capped by the target's HP, HP-triggered berries). 5,290 views of real positions and 7,968 views of random battles, no violations (the first run found 4: 1 a feature problem, "possible" not including "certain"; 3 where the rule itself is not monotonic, now excluded from the check).

- "Missed" is monitored separately: it keeps "reliable" a lower bound, but the number of answers and the only answer get undercounted. Mostly the lowest damage estimated at the 85% roll comes out too low for Leftovers / Life Orb / Rocky Helmet and the like, plus Knock Off combinations. The check script breaks false and missed claims down by move / ability / item (`breakdown` in `feature_claims.json`).
- During the fixes, the first version of the check had a 9–17% error rate. Half came from the check itself (moves that need the opponent to attack, like Sucker Punch; full paralysis; end-of-turn chip damage), the other half were feature problems, fixed one by one: Substitute, the hit counts of Triple Axel and Bullet Seed, charge moves, Fake Out, Knock Off removing items, self-lowering moves (Draco Meteor, Close Combat), recoil / Life Orb / Rough Skin, Contrary, Salt Cure and binding end-of-turn damage, guaranteed secondary stat drops.
- "Unverifiable": "possible" claims where only the two hits together KO. The engine branches exactly over the 16 damage rolls on whether one hit KOs, and averages a hit that does not KO, so the case where two high rolls are needed to KO has no branch in the transition.
- The remaining errors are documented approximations: abilities and items that react to attacks (Weakness Policy, Weak Armor, Eject Button, White Herb timing), moves that retaliate by the damage taken such as Counter / Metal Burst, Libero changing type, Quick Claw / Custap Berry, Booster Energy activating mid-turn.
- Feature cost (Rust, single position): v3 about 20 µs, v7 about 121 µs (the exchange simulation about 81 µs, including the matchup-context end of turn and the turn-by-turn sequence); v7.1 estimated about 70 µs. The effect on search speed to be measured after retraining.

### F1: damage evidence updates the opponent's sets (2026-10-19; `scripts/check_damage_belief.py` (deleted 2026-10-28), 600 games of generation 8 self-play, both sides' true sets known)

2,855 Pokémon, 8,515 clean hits (the first move of the turn, single-hit, no crit / Substitute / Focus Sash or other survival effects, only switches before it). Candidates = the belief's top 8 items × the possible abilities × the top 12 EV spreads.

| | prior | posterior |
|---|---|---|
| probability of the true item | 0.435 | **0.503** |
| probability of the true ability | 0.616 | 0.652 |
| probability of the stats involved in the hit (true set) | 0.183 | **0.284** |
| the most likely item is the true item | 51.6% | **57.4%** |

Hits where the true set's likelihood is 0 (they would be eliminated without a floor): 0.41% (7.4% before fixing the old positions' tera type convention, our own tera, Dragon Darts, the view, and Knock Off on items already lost); the posterior has a floor of 1e-3 × prior, so nothing is really eliminated. Real-game smoke test (CPU search, 2 games): 13–15 clean hits per game, 0 fallbacks.

Game A/B (network unchanged: v6-h on both sides, GPU batched search, 1,600 iterations, ml3, wide1000, 600 pairs; A with F1 on, B off): **52.29% ± 2.43%** (about +16 Elo, leaning to on, not significant, lower bound of the interval 49.9%); kept on by default. In these games the two sides had 51 searches in total crash on L229 (a leaked saved move in the engine, doc/engine-diff.md) and fall back to the heuristic; fixed since. Two problems found in review were fixed at the same time: the side being hit was still counted at full HP after taking hazard damage on entry (Multiscale / Shadow Shield: Bullet Punch at most 61 at full HP, at most 123 at 88% HP; the 600-game acceptance numbers are unchanged, this is rare here), and items drawn from the damage posterior are now reweighted by set type (consistent with the revealed moves).

### Network v4: Elo, history outcomes, switch counters, new decision points (v4s = the same turn-start positions as v3s + at most 8 new decision points per game; 3 seeds each, anchor validation set)

Baseline = v3's A + B features + opponent set head + MTP-3. "Biased" metrics count only turn-start positions with a recorded move (comparable with v3, but missing the turns where the Pokémon was KOed by a faster move / blocked, turns in which the player certainly chose a move); "all" includes the turns with no visible action, counted with partial labels. Note: new decision points are sampled at a higher rate (about 60%) than turn-start positions (about 28%), which also affects the "all" metrics (sampling weights come next).

| group | policy CE (biased) | voluntary switch CE | forced switch top-1 / CE | turn-start CE (all) | CE on turns with no visible action | value BCE (biased) | value BCE (all) | value BCE (turns with no visible action) | ECE (biased) | opponent action top-1 |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 1.3576 | 2.160 | 42.2% / 1.240 | 1.2127 | 0.537 | 0.5655 | 0.5617 | 0.5407 | 0.023 | 37.1% |
| + Elo | 1.3532 | 2.161 | 42.3% / 1.234 | 1.2073 | 0.527 | 0.5634 | 0.5586 | 0.5400 | 0.016 | 37.0% |
| + history outcomes (after the fix) | 1.3542 | 2.156 | 42.2% / 1.257 | 1.2152 | 0.567 | 0.5643 | 0.5592 | 0.5362 | 0.019 | 37.3% |
| + switch counters | 1.3510 | 2.148 | 43.5% / 1.216 | 1.2066 | 0.533 | 0.5638 | 0.5552 | 0.5393 | 0.017 | 37.1% |
| + forced / U-turn switches | 1.3475 | 2.136 | 53.4% / 1.034 | 1.2042 | 0.536 | 0.5656 | 0.5513 | 0.5377 | 0.031 | 37.3% |
| + new decision points (including turns with no visible action) | 1.3614 | 2.323 | 53.5% / 1.035 | 1.1651 | 0.250 | 0.5776 | 0.5557 | 0.5000 | 0.046 | 37.2% |
| all combined | 1.3528 | 2.301 | 54.5% / 1.016 | 1.1581 | 0.250 | 0.5690 | 0.5474 | 0.4920 | 0.038 | 37.6% |

The first history-outcomes experiment (`v4s-hresbug-*`) had a bug: the cache stored the damage column as uint8, truncating it to 0; the results after the fix are in the table above.

### Sampling weights (v4w = v4s plus a sampling weight per position; full configuration A + B + Elo + switch counters + opponent set head, all decision points; 3 seeds each)

"Weighted" metrics use the sampling weights to restore the proportions of each kind of decision point in real games (checkpoints are also chosen by them).

| training | voluntary switch top-1 / CE | forced switch top-1 | turn-start CE (weighted) | CE on turns with no visible action | value BCE (biased subset) | value BCE (all, weighted) | ECE (biased subset) |
|---|---|---|---|---|---|---|---|
| unweighted | 22.2% / 2.322 | 54.2% | **1.2631** | 0.244 | 0.5740 | 0.5789 | 0.043 |
| weighted | 24.0% / 2.258 | 53.3% | 1.2693 | 0.300 | 0.5671 | 0.5732 | 0.034 |
| weighted, without turns with no visible action | 27.1% / 2.155 | 53.1% | 1.2884 | 0.524 | 0.5641 | 0.5744 | 0.027 |

Weighting only partly corrects the underestimation of voluntary switches, and is slightly worse on the real-proportion metrics (smaller effective sample size). For the full data, sampling is now uniform from one pool built from all decision points of each game (`--pool all`), so the proportions are naturally right and need no weights.

### Belief samples in the input vs masked as "unknown" (v3s, A + C, 3 seeds each, anchor validation set)

| input | policy CE | switch CE | value BCE | value BCE (≥12 turns) | opponent action top-1 | set head: item / ability / tera / moves (unrevealed fields) |
|---|---|---|---|---|---|---|
| belief sample (`v3s-AC`) | 1.3986 | 2.185 | 0.5683 | 0.4987 | 36.3% | 63.7% / 96.2% / 41.3% / 63.5% |
| masked as unknown (`v3s-AC-mask`) | 1.3979 | 2.187 | 0.5679 | 0.4995 | 36.6% | 64.9% / 96.7% / 42.1% / 63.6% |
| single sample from the belief model | | | | | | 48.3% / 89.8% / 31.6% / 61.8% |

The belief sample gives the network no extra information; the network inferring the opponent's sets on its own is no worse than the belief model (the remaining unfairness: the network takes the most likely value, the belief is one random sample).

### Network architecture (equal parameter count, v4w, all of baseline-v5's features / outputs / decision points, 6 epochs, 3 seeds each; 2026-10-08)

base is exactly v5-final's architecture (PyTorch `TransformerEncoderLayer`, pre-LN, ReLU feed-forward 256, 3 layers, d = 128, 4 heads, 737k parameters), only the data is 10%. The other groups adjust d_ff / width to keep the parameter count the same (736k–738k).

**The value head starts to overfit after 1,500–3,500 steps on 10% of the data**, while the policy keeps improving, so a checkpoint chosen by "policy + value sum" is best at neither (for example glu-s2: the sum picks step 3,500, ce 1.2713; the best policy is 1.2600). In the table below policy and value **each take their own best validation point**.

| architecture | policy ce_turn_w | value bce_all_w | Δpolicy | Δvalue | top-1 | forced switch top-1 | best value step |
|---|---|---|---|---|---|---|---|
| base | 1.2642 ± 0.0020 | 0.5689 ± 0.0019 | — | — | 51.5% | 54.2% | 2,000–3,500 |
| glu: SwiGLU (d_ff 171) + RMSNorm + QK-norm | **1.2585 ± 0.0019** | 0.5682 ± 0.0016 | **−0.0057** | −0.0007 | 51.7% | 54.6% | 1,500–3,500 |
| deep: 6 layers, d = 96, d_ff 192 | 1.2643 ± 0.0026 | 0.5670 ± 0.0022 | +0.0001 | −0.0019 | 51.4% | 54.3% | 2,000–3,000 |
| smolgen 64 (d_ff 160) | 1.2727 ± 0.0014 | 0.5720 ± 0.0031 | +0.0085 | +0.0031 | 51.2% | 53.5% | 1,500–2,000 |
| all: glu + smolgen (d_ff 105) | 1.2698 ± 0.0012 | 0.5731 ± 0.0013 | +0.0056 | +0.0043 | 51.3% | 53.8% | 1,500 |
| gluNoQK: SwiGLU + RMSNorm, without QK-norm | 1.2609 ± 0.0049 | 0.5709 ± 0.0010 | −0.0033 | +0.0020 | 51.7% | 54.2% | 2,000–2,500 |

- All 3 glu seeds have a better policy than base's best seed; no difference in value.
- Without QK-norm the spread between seeds grows 2–3 times (policy 1.2553 / 1.2636 / 1.2638), and the value clearly overfits on all 3 seeds (at the end 0.010 / 0.035 / 0.023 above the best point; base and glu each have only 1 seed like that): both the gain and training stability depend on QK-norm.
- On the full data (v5-final) the value does not overfit: policy and value are both best at the last step (1.1429 / 0.5466). Overfitting is a 10%-data phenomenon.
- deep is within noise on both.
- smolgen is worse on both, and the value overfits earlier (the path that generates attention biases from the whole position has a large capacity; Lc0 has thousands of times our data); in the combination it cancels glu's gain.

Inference speed (only 3 attention blocks, T = 21; measured with the machine idle, PyTorch):

| architecture | CPU single | CPU batch 32 | GPU batch 32 (eager) | **GPU batch 32 (CUDA graph, what the search actually uses)** | GPU batch 256 (CUDA graph) | one training step (batch 1024) |
|---|---|---|---|---|---|---|
| base (PyTorch layer) | 332 µs | 5.94 ms | 613 µs | 201 µs | 855 µs | 12.9 ms |
| base (our own Block) | 0.96× | 1.01× | 1.01× | 0.93× | 0.90× | 0.74× |
| SwiGLU | 1.03× | 0.90× | 1.11× | 0.93× | 0.95× | 0.81× |
| SwiGLU + RMSNorm | 1.20× | 0.90× | 1.13× | 0.92× | 0.91× | 0.79× |
| glu (+ QK-norm) | 1.44× | 0.95× | 1.30× | **1.14×** | 1.11× | 0.95× |

The compute is the same (at CPU batch 32 glu is not slower); what slows down is small-op overhead, and **all the extra cost comes from QK-norm** (two more unfused RMSNorms per layer). SwiGLU + RMSNorm is not slower.

**Full-data confirmation (`v5-glu`, exactly v5-final's settings with only the architecture changed; single seed, 2026-10-08)**:

| full data, final checkpoint (56,924 steps) | v5-final | v5-glu | difference |
|---|---|---|---|
| policy ce_turn_w / ce_turn | 1.1429 / 1.1269 | **1.1345 / 1.1188** | −0.0084 / −0.0081 |
| value bce_all_w / bce_all | 0.5466 / 0.5282 | **0.5439 / 0.5249** | −0.0027 / −0.0033 |
| top-1 / top-3 | 55.6% / 87.4% | 55.9% / 87.6% | +0.3 / +0.2 |
| forced switch top-1 | 57.7% | 57.9% | +0.25 |
| value ECE | 0.0126 | 0.0134 | |
| training time | 99 minutes | 107 minutes | +8% |

The gain on the full data (policy −0.008) is even larger than on 10% of the data (−0.006), and the value improves slightly too; it leads throughout training (−0.010 at 10k steps, −0.008 at 30k, −0.0085 at 50k).

**Rust inference (`tnet.rs`, 2026-10-08)**:

| check | v5-final | v5-glu |
|---|---|---|
| `check_tnet` (4,000 positions, PyTorch vs Rust): max logit difference / value difference, our / opponent's view | 1.05e-5 / 3.8e-6, 1.0e-5 / 4.3e-6 (exactly as before the change) | 9.5e-6 / 6.7e-6, 7.6e-6 / 8.7e-6; argmax 100% the same |
| `check_batch_search` (GPU vs Rust, leaves of real searches): value difference / logit difference | 6.8e-6 / 8.6e-6 | 7.4e-6 / 1.05e-5 (CUDA graph fine) |
| one single-thread forward pass (8 history steps, median of 3) | 202 µs | **207 µs (+2.5%)** |
| CPU search (30 positions × 1,500 iterations, 8 worlds, twice) | 2,975 / 2,946 leaves/s | **2,962 / 2,942 leaves/s (−0.3%)** |

Speed during the implementation: inner dimension padded to 192 with scalar exp: 232 µs (+15%); a polynomial exp that was not vectorized: 242 µs; **padded to 176 (the two halves together exactly 11 blocks of 32) + AVX-512 silu**: 207 µs. Feed-forward 21.7 µs per layer (old architecture 19.6 µs).

**Smoke test in search (`s_ismcts_glu` vs `s_ismcts_tf`, CPU, 500 ms per move, heldout, 10 games, 2026-10-08)**: 6 wins, 4 losses (10 games mean nothing statistically; only a check for anomalies). No fallbacks, failed games or team mismatches; median iterations per move 1,536 vs 1,536, median time 0.54 vs 0.55 s (longest 0.61 s). The decisions with over 100k iterations (glu 12, tf 9) all came when the opponent had only its last Pokémon left: the tree quickly reaches terminal states and stops calling the network, which is normal.

After fusion (`torch.compile` + CUDA graph, output within ≤ 1.2e-6 of the uncompiled one):

| architecture | GPU batch 32 | GPU batch 256 |
|---|---|---|
| base (PyTorch layer, what is used live now, uncompiled) | 198 µs | 858 µs |
| base (our own Block, compiled) | 148 µs (0.75×) | 584 µs (0.68×) |
| SwiGLU + RMSNorm (compiled) | 156 µs (0.79×) | 748 µs (0.87×) |
| glu (compiled) | 165 µs (0.84×) | 628 µs (0.73×) |

Against an equally optimized base, glu costs 11% more at batch 32 and 7.5% more at batch 256 (attention blocks only, not counting the input embedding and the output heads). Also, compilation by itself makes the current base 25% (batch 32) to 32% (batch 256) faster on the GPU.

## Offline: belief model

The first row's setup (2026-10-04; formerly `belief_prior_eval.md`; `scripts/eval_belief_priors.py`): the 8,289 high-rated replays downloaded then (about 1740–2049), split by time: the 6,631 before 2026-08-24 build the prior, the 1,658 after it test; given only the opponent's 6 from team preview, predict the items / tera types / moves revealed later (8,448 / 2,502 / 35,709 of them). The prior backs off level by level (Smogon marginals → this species' replays → the same largest core → the identical 6, Dirichlet α=5): conditioning on the whole team is best, its gain mostly from recognizing copied popular teams (about 40% at high ratings); on unseen teams core conditioning is still clearly better than species marginals; replays themselves also beat Smogon stats. Limits: only information that gets revealed can be scored (quiet items such as Choice Specs are almost unmeasurable), and only high ratings.

| measure | value |
|---|---|
| Time-split high-rated replays (2026-10-04): whole-team prior, item top-1 / tera top-1 / moves recall@4 | 76.6% / 68.2% / 84.3% (Smogon marginals 55.4% / 50.4% / 73.3%; seen teams 92.1% / 83.3% / 94.7%) |
| After rebuilding on 50k games (40k train / 10k test): moves recall@4 / item / tera | 84.8% (seen teams 95.8%) / 79.5% / 70.5% |
| Sampled 4 moves covering the moves revealed later: archetype / whole-team marginal / archetype × whole team (β=1) / β=2 / β=3 | 61.7% / 76.3% / **77.3%** / 81.1% / 82.6% |
| True moves among the 4 sampled on pool teams (heldout): β=0 / β=2 | 2.37 / 2.76 (with nothing revealed, all 4 right about 20%) |
| Negative evidence (on the field t times without using a move): coverage without / with (at t ≥ 4) | 85.1% / 85.2% (80.4% / 80.9%) -- almost no gain |

## Throughput and speed

| item | value |
|---|---|
| poke-env → 4 servers × 8 clients (random policy, 2026-10-03) | 3,767 turns/s (one server caps at about 1.3k; 8 servers only 3,057) |
| Driving `BattleStream` directly × 8 node processes | 6,261 turns/s |
| poke-engine MCTS / alpha_search's ISMCTS (handwritten eval, single thread) | about 430–520k / about 220k iterations/s; ISMCTS 4 threads 790k |
| ISMCTS + network (single thread): value only / own prior / both priors | 21.8k / 18.7k / 14.2k iterations/s (depth 5 / 6 / 10) |
| Python overhead of one decision | building one world about 0.9 ms (N=32 about 30 ms, 6% of 500 ms) |

## Team data (`scripts/teams.py`, 2026-10-08; design in D5-T)

Smogon forum crawl: 1,785 thread pages + 1,660 pokepastes (all still up); 3,199 teams found (1,660 from pokepastes, 1,304 pasted directly in posts). Normalized, nicknames removed, deduplicated: 2,572 distinct teams, of which 1,189 are legal today (the catalog keeps only these); the 1,383 illegal ones are dropped. Skipped: 17 whose pokepaste notes name another format, 23 that are not 6 Pokémon.

| source | distinct teams (incl. illegal) | legal + complete | of these, the 6 species seen in replays | seen ≥ 10 times |
|---|---|---|---|---|
| `sample` (SV OU Sample Teams) | 196 | 108 | 71% | 54 |
| `teams_of_week` | 161 | 49 | 12% | 1 |
| `tour_bazaar` | 9 | 6 | 100% | 2 |
| `rmt` (Rate My Team first posts) | 2,257 | 1,046 | 23% | 106 |
| total | 2,572 | 1,183 (997 distinct species sets) | | |

- Illegal mostly because of later bans: Tera Blast (427 teams), species moved up to Ubers (Roaring Moon, Baxcalibur, Volcarona, Sneasler, etc.), Sleep Moves Clause (Spore); about 100 more have misspelled move names.
- Legal + complete teams by year of first post: 2022 87, 2023 351, 2024 271, 2025 222, 2026 252.
- RMT quality varies widely; 408 claim a peak / rating / rank in the title.
- Sample teams are copied a lot: 71% appear in replays. 14 of `replay40`'s 40 teams have their original sets in the catalog, usable to check how accurate replay reconstruction and the belief model's completion are.
- Pool: `forum_curated` = the 162 legal, complete teams of sample + teams_of_week + tour_bazaar.

## Against a specific opponent: offline steps 1 and 2 (`scripts/player.py`, design in D5-O; 2026-10-08)

Target opponent: 57 public Gen9 OU replays (2026-07-17 to 08-30, ladder about 1000–1200). The evaluation is rolling: games 1..i−1 predict game i, from game 11 on, 47 games in all.

**Step 1, team (species level)**: predict which species they bring next game. "Bits per species" is the mean of log2(p/6) (higher is better); recall is the fraction of their next game's 6 that fall in the model's top 10.

| model | bits per species | recall @10 |
|---|---|---|
| Ladder usage (Smogon gen9ou-0 / 1500) | −6.07 / −5.98 | 36% / 34% |
| Their own frequencies, unsmoothed, not time-weighted | −6.01 | 49% |
| Decay by time (best: half-life 3 days, k = 2) | −4.94 | 66% |
| **Decay by games (best: half-life 2 games, k = 1)** | **−4.82** | **70%** |

- Decay by games is better, and it does not fall back to the ladder prior after a long break, so it is the one used.
- 38% of games use a complete team used before; 28 of the 47 games share at least 5 Pokémon with some earlier team. They use the same or a similar team for stretches.
- The optimum is at the grid's edge: half-life 2 games, k = 1. With one opponent and 47 games the hyperparameters may overfit; they should be chosen over many players (see TODO).

**Step 1, sets**: personalized belief = the general belief prior (weight k) + the values they have revealed, compared with the general belief.

| field (number revealed) | general belief: log-likelihood / hit | personalized (k = 1–4) |
|---|---|---|
| item (107) | −1.00 / top-1 66% | −0.88 / 71% |
| tera (38) | −1.96 / top-1 47% | −1.59 / 55% |
| moves (462) | −1.99 / top-4 recall 76% | −1.84 / 83% |

Their own data alone (k = 0) is worse than the general belief; a prior is needed.

**Step 2, play**: v5-final's policy, fitting the rating input r and the temperature τ. The first 2/3 of the games (1,115 decisions) fit, the last 1/3 (475) test.

| setting | fit-set cross-entropy | test-set cross-entropy | top-1 (fit / test) |
|---|---|---|---|
| This game's true rating (about 1100), τ = 1 | 1.371 | **1.220** | 50% / 55% |
| Rating unknown, τ = 1 | 1.377 | 1.225 | 50% / 54% |
| Fitted: r = 1100, τ = 1.1 | 1.365 | 1.228 | 50% / 55% |

- The fitted r (1100) is their true rating. The higher the rating input, the worse it explains their choices: at r = 2000 the cross-entropy is 1.457, 0.09 above 1100. So the network's rating conditioning did learn different levels of play.
- Fitting brought no test-set gain: their true rating as input is already a good model of their play; 57 games are not enough data for more personalization.
- Reference: their opponents in the same games (similar ratings) have cross-entropy 1.295, top-1 53%; they are about as predictable as people at their level.

## Against a specific opponent: team choice (`scripts/counter_team.py`, 2026-10-08)

**Candidates**:
- The matchup model trained on 2M games (`analysis/matchups.py`: rating difference + species strength + species vs species, 837k games since 2025-05; held-out log loss: ratings only 0.6906, + species strength 0.6846, + species matchups 0.6805) scores the catalog's 998 species sets: expected win rate against their recent teams (equal skill on both sides).
- The top 12 + one from the middle of the ranking as a control; their teams: the 8 weighted by recent use, sets completed with the values revealed across all their games (the rest from Smogon gen9ou-0), validated.

**Stage 1** (both sides `pol`: network policy, rating input 1100, τ 1.1, no search; successive halving, games doubled each round; about 1,480 games, a few minutes):
- Round 1 (40 games each): the top ones 92.5% / 87.5% / 87.5%, the control 50%; two teams the matchup model rated highly only 45% and 47.5% (species alone mislead).
- Last round (280 games each): team_11 83.2%, team_09 81.8%, team_07 78.6% (within error).

**Stage 2**:
- Our side the search bot (`s_ismcts_tf`, 200 ms), theirs `pol`: all three about 99% (440 games); the opponent is too weak to separate them.
- Both sides the search bot (`s_ismcts_tf`, 200 ms, rating input unknown on both = "them playing very well"); each round drops those significantly behind the leader (one-sided test p < 0.05), the rest double their games:

| candidate | record | |
|---|---|---|
| **team_09**: Corviknight / Iron Valiant / Kingambit / Ogerpon-Wellspring / Raging Bolt / Slowking-Galar | **32 / 34 = 94.1%** | chosen (`counter/team_00`) |
| team_11: Gholdengo / Iron Moth / Kingambit / Manaphy / Ogerpon-Wellspring / Ribombee | 44 / 60 = 73.3% (round 1 18 / 20, round 2 26 / 40) | backup (`counter/team_01`) |
| team_07: Hatterene / Iron Treads / Kingambit / Ogerpon-Cornerstone / Okidogi / Zapdos | 11 / 20 = 55% | dropped in round 1 |

- Teams ranked high in the policy-only stage spread apart when both sides search (team_07: 78.6% → 55%): against an opponent who plays well, some teams' edge came from the opponent's mistakes.
- Limits: their unrevealed sets are completed; the opponent is a search version of "them", stronger than the real one; real results to be added later.

## Self-play (design in D15)

**Generation 0 (2026-10-08, validating the pipeline)**: 2,000 games; teams: 2,805 completed from real games / 1,195 complete catalog teams (30%); search 25% × 3,000 iterations (target) + 75% × 600, root noise 0.1 / 10, moves drawn from the visit distribution, network v5-glu.
- Generation: 2 → 4 processes, about 36k leaves/s, about 1,400 games/hour (restarted midway to switch in the damage features for speed and after fixing team packing). Median 26 turns, 90th percentile 50; 1 game reached the 300-turn cap; 118 fallbacks (0.08%); first player's win rate 50.8%.
- Conversion: 148,709 decisions → 148,145 training positions (99.6%); the moves in the logs agree with the records 99.57%; 34,633 policy targets from full searches.
- Training (warm-started from v5-glu, human : self-play = 1 : 1, 145 steps, each self-play position about 2 times, lr 3e-4, 2 warmup steps):

| validation set | before training | step 50 | after training |
|---|---|---|---|
| self-play: KL(search ‖ network) | 0.344 | 0.305 | 0.300 |
| self-play: top choice agrees with search | 65.7% | 66.8% | 67.0% |
| self-play: value BCE (root q: 0.525) | 0.546 | 0.523 | 0.527 |
| human: policy ce_turn_w | 1.134 | 1.145 | 1.145 (+0.011) |
| human: value bce_all_w / ECE | 0.544 / 0.013 | 0.556 / 0.030 | 0.557 / 0.033 (+0.013) |

  Nearly all of the human validation drift is in the first 50 steps, flat afterwards: on a warm start AdamW's state is fresh, and warmup was only 2 steps. Changed afterwards to lr 1e-4, 20% warmup.
- Evaluation: sp-gen0 vs v5-glu, equal time (CPU, 500 ms), 200 games: **50.25% ± 5.7%**, not significantly worse → promoted.

**Generation 1 (2026-10-08)**: 5,000 games (under v5-glu, see the note below), 369,349 positions; trained on sp0+sp1, 460 steps, lr 1e-4, 20% warmup, 45% human (each self-play position drawn about 2.1 times on average, human data about 0.02 epochs); KL to the start only 0.002; vs sp-gen0, 100 games, 50.0% ± 9.7%, promoted.

**Generation 1 retrained: bigger updates (same start sp-gen0, same data, self-play 55% of each 4,096 batch; 2026-10-08)**

| run | lr | passes | KL to start | self-play KL(search‖network) | self-play top-choice agreement | self-play value BCE | human value BCE | hce_true | opponent move prediction |
|---|---|---|---|---|---|---|---|---|---|
| start sp-gen0 | — | — | 0 | 0.295 | 68.3% | 0.458 | 0.557 | 1.2285 | 41.8% |
| sp-gen1 (original) | 1e-4 | 2 | 0.002 | 0.287 | 68.5% | **0.455** | 0.552 | 1.2298 | 41.8% |
| lr2e-4-p3 | 2e-4 | 3 | 0.006 | 0.282 | 68.8% | 0.458 | 0.554 | 1.2311 | 41.8% |
| lr4e-4-p3 | 4e-4 | 3 | 0.010 | 0.279 | 69.0% | 0.465 | 0.558 | 1.2329 | 41.7% |
| lr2e-4-p6 | 2e-4 | 6 | 0.009 | 0.278 | 69.1% | 0.465 | 0.558 | 1.2316 | 41.7% |
| **lr4e-4-p3-v1** (self-play value trained for 1 pass only) | 4e-4 | 3 | 0.009 | **0.278** | **69.2%** | 0.462 | **0.547** | 1.2318 | 41.8% |

- The policy keeps moving toward the search distribution as the updates grow; lr2e-4-p6's second half barely changes (0.281 → 0.278), the movement stalls at 0.009.
- Self-play value BCE is lowest at about 1.2 passes and worse after (the value target is one result per game, about 7,000 games); `--sp-value-passes 1` (a position's result counts in the value loss only the first time it is drawn) recovers only a small part; the self-play validation set is only about 350 games, the gap close to noise.
- Match: **lr4e-4-p3-v1 vs sp-gen1, equal time 500 ms, 100 pairs, 200 games: 56.5% ± 6.6%** (paired; z ≈ 1.93, two-sided p ≈ 0.05, one-sided ≈ 0.03). During the evaluation 3 match lines got stuck on the first game's challenge (arena had no per-game timeout; a 1-hour timeout was added); the 12 missing pairs were played separately into the same log.
- Conclusion: the earlier updates were too conservative; the per-generation default is now lr 4e-4, 3 passes, self-play value trained for 1 pass only; lr4e-4-p3-v1 becomes the current network under "promote unless significantly worse".

**Note**: the games of generations 0, 1 and 2 (gen2 stopped at 262 games) were all played under **v5-glu**: `selfplay.py run`'s `--model` default was hardcoded to v5-glu, and `loop` / `cycle` did not pass the current network either (found 2026-10-08; it now defaults to the current network in state.json, and refuses to run when the directory already holds games played under another network).

**Offline validation of luck correction (AIVAT-style control variates, `scripts/luck.py`, 1,000 random gen1 games, 2026-10-08)**: on each turn where both sides decide at the start of the turn, both sides' records are merged into a perfect-information position, all random outcomes of this pair of moves are listed with the engine's transition model, luck = V(the branch that actually happened) − Σ pᵢ·V(branchᵢ), the actual branch matched by the next record; V = v5-glu's value head. Corrected score = result − Σ luck.

| setting | corrected variance / raw variance |
|---|---|
| Engine default branches (critical hits, accuracy, secondary effects, etc.; damage averaged) | 0.944 |
| Plus damage roll branches (KO thresholds) | 0.897 |
| Same, V averaged over both sides' views | **0.882** |
| Plus self-play's move-sampling luck (Q(chosen) − E_π[Q], Q = search root mean) | 0.906 (worse: the fast search's Q is noisy) |
| Both terms at the regression-optimal coefficients (in-sample, an upper reference) | 0.825 |

- Unbiasedness check: mean luck per turn 0.0006 ± 0.0004, close to 0; about 20 correctable turns per game.
- The value head's prediction of the result along the game: BCE 0.508, correlation 0.55. The explainable part is limited, so the variance falls only about 12% (equivalent to about 12% fewer games). By comparison, paired games cut variance about 33% (generation 0's evaluation ±6.9% → ±5.7%).
- Conclusion: luck correction gains far less than AIVAT in poker (DeepStack cut the standard deviation by about 85%). Most of Pokémon's randomness cannot be isolated as "one draw on one turn" (damage rolls branch only at KO thresholds, information asymmetry, the search's own noise); not wired into promotion evaluation for now; sequential tests and result-independent decision quality measures come first.

**r2 generation 0 (2026-10-26 / 27, start v6arch-pp-v75, `selfplay.py iterate`)**: promote only when confidently better -- sequential test H0 = +13.9 Elo (52%), H1 = +34.9 Elo (55%), α 0.05, β 0.1, at most 2,000 pairs, 1,600 iterations, a new team pool for each attempt; on failure the same network plays another 25,000 games and is fine-tuned again on all the games so far. Teams: half synthetic (selfplay.teams.Composer + Metropolis-Hastings over teammate combinations across teams, design.md D16), completed real ones 43%, catalog 6%.
- Generation: 10 processes × 24 games, about 3,500 games/hour (6 processes about 3,000; each process is bound by Python's single core, GPU about 30%). Turns: mean 32.0, median 26, p90 51; 46 games hit the cap; 73.1 decisions per game; synthetic + synthetic 31.9 turns, real + real 30.6 (no systematic difference), catalog teams run longer (catalog + catalog 45.6). 134 games (0.25%) had request / engine state mismatches (mostly the opponent's Imprison, Transform after Imprison, issue #3).
- Attempt 1 (52,959 games): 3.86M positions converted, action agreement 99.89%; 2.52M after at most 50 positions per game, 930k policy targets; trained 3,501 steps (50% human, lr 4e-4, 3 passes, `--stream 1`: `--stream 2` used 31 GB, over the 30 GB cap, and was killed). Self-play validation: CE 1.304 → 1.253, top choice 71.5% → 73.5%, value BCE 0.4675 → 0.4394; human validation: CE 1.129 → 1.139, hce_true +0.010 (the drift guard triggered), opponent action 42.4% flat; KL to the start 0.033.
- **Match: r2-gen0a1 vs v6arch-pp-v75, 50.22% ± 3.71%** (232 pairs, LLR −2.76 → H0), not promoted; 155 pairs (67%) split one game each. Attempt 2's games continue (paused at 53,691 games).

### Plasticity diagnostics (`scripts/plasticity.py`, 2026-10-09; 4,096 rows of real positions, both sides' views; CPU)

| network | dormant unit fraction, FFN layers 1 / 2 / 3 (τ = 0.025 / 0.1) | move head / switch head hidden layer | trunk feature effective rank (global / entity, full 128) | parameter norm |
|---|---|---|---|---|
| random init (same architecture) | 0 / 0 / 0 | 0.14 / 0.28, 0.20 / 0.33 | 124 / 122 | 311 |
| v5-glu | 0 / 0 / 0 | 0.00 / 0.05, 0.05 / 0.08 | 124 / 124 | 439 |
| sp-gen0 … sp-gen3 (old round) | 0 / 0 / 0 | same as above (±0.02) | 124 / 124 | 439 |

No sign of plasticity loss: the SwiGLU feed-forward layers have no dormant units (the gating is smooth); the output heads' ReLU hidden layers have even fewer dormant units than at random init; the feature effective rank is nearly full, no collapse. The parameter norm grew from 311 to 439 (+41%) in supervised training and barely changes across the self-play generations, consistent with each generation's tiny updates (about 1% relative weight change). So the small per-generation progress is not "the network can no longer learn"; more likely it comes from warm-start generalization, the data or intransitivity.

### Diagnostic pools for the team distribution (design in D16, 2026-10-09; 200 pairs per cell, paired, sides swapped)

sp-gen1 = generation 1 after the restart (two generations of self-play). Off-meta pool `offmeta200`: real games where both sides are off-meta (on average 4.94 per team outside the top 40 by usage); random pool `random200`: teams drawn at random by usage^0.5 (3.25); ladder pool `wide200`: 2.44.

| opponent | ladder pool | off-meta pool | random pool |
|---|---|---|---|
| v5-glu (GPU batched search, 3,000 iterations) | **54.6% ± 3.9%** | 51.6% ± 4.2% (193 pairs: interrupted by a WSL crash) | 51.8% ± 4.5% |
| Foul Play (ours CPU 200 ms vs 200 ms × 1) | **59.1% ± 4.4%** (198 pairs) | **63.3% ± 4.4%** | **60.8% ± 4.3%** |

- Self-play's progress (vs v5-glu) is clearest on the ladder pool (about +32 Elo, significant), on the off-meta / random pools only about a third of it (+11 / +12 Elo, not significant); but the pools differ by about 3 points, and the difference's 95% interval is about ±6 points: **not significant**. The direction agrees with "self-play's progress is mainly on common teams"; no regression on off-meta / random teams.
- Overall strength against Foul Play is **not weaker** on off-meta / random teams (slightly higher): both sides infer the opponent's sets from ladder stats, so Foul Play suffers against off-meta teams too. By comparison: sp-gen0 on the ladder pool 56.1% ± 4.5%.
- Problems fixed along the way: Foul Play crashing on field effects such as Magic Room, and on a division by zero (local patch, `research_foul_play.md` 6.3); the evaluation waiting forever when the opponent crashed / a challenge went unaccepted (per-game timeout, opponent process watchdog, whole-line restart, resume); when the evaluation loaded teams, the trailing spaces of export lines stayed in nicknames, and long-named Pokémon without an item went over 18 characters and were rejected by the server (2 pairs of the off-meta pool got stuck every time).

### Check of generation 3 after the restart (2026-10-10)

| comparison | result |
|---|---|
| sp-gen3 vs sp-gen2 (promotion evaluation, 3,000 iterations, 400 pairs) | 47.8% ± 3.0%, not promoted |
| sp-gen2 vs sp-gen0 (cumulative check, 3,000 iterations, 400 pairs) | 49.3% ± 2.9%, no measurable progress (1 stall) |
| sp-gen2 vs sp-gen0 (policy only, tau 0.05, wide1000, 1,000 pairs) | **52.4% ± 1.9%** (about +17 Elo, significant) |

- The prior is getting stronger (policy only is significantly better), but under 3,000-iteration search the edge disappears: self-play mostly pulls the policy toward the search's choices, which deep search makes anyway; deep search's strength depends on the value head, whose BCE on new games falls only about 0.005 per generation. The same phenomenon as the first round's "four generations without measurable progress".
- The 51.6% / 51.9% at single-generation promotion are the scores where SPRT stopped on crossing the line, systematically high (stopped at a peak); refitting Elo gives sp-gen1 / sp-gen2 = 1494 / 1496 (v5-glu = 1500).
- Offline: sp-gen3 self-play KL −0.007, value BCE −0.003 (smaller than the previous generation's); `hce_unk` (cross-entropy on human moves with the rating input "unknown") rises generation by generation, 1.2612 → 1.2841 → 1.3023 (self-play positions all have the rating input "unknown", which pulls the policy under this input toward the bot), `hce_true` only +0.003 / generation.

### Action consistency in self-play (`scripts/check_actions.py` (deleted 2026-10-28), generation 5's 9,000 games, 640k decisions; 2026-10-11)

Each record's choice (`names[slot]`) checked against the action that actually happened in that turn in the server log:

| category | share |
|---|---|
| agrees (main action) | 79.67% |
| agrees (forced / mid-turn switch) | 12.67% |
| did not act: fainted first / hit itself in confusion / the game ended first | 6.08% / 0.07% / 0.02% |
| cannot act (`cant`: sleep, paralysis, flinch…) | 1.34% |
| move changed by the opponent's faster Encore | 0.09% |
| removed before acting by Eject Button / Red Card / Whirlwind | 0.04% |
| Illusion (Zoroark-Hisui disguised as another Pokémon) | 0.02% |
| true mismatch | **0.0006%** (4 records) |

The 4 true mismatches: 3 are switches rejected by the server (trapped by an unrevealed ability such as Magnet Pull) and then rechosen, which leaves two records in the same turn, and the conversion took the rejected first one; 1 is out of PP with only Struggle left, the record still the move the search chose (`engine_move_to_order` sends the move directly when only one usable move remains). Tera: every choice of tera terastallized, no other did. Conclusion: the actions recorded in self-play are the actions the server executed.

### GPU inference precision: BF16 vs FP32 (`scripts/bench_precision.py`, sp-gen2, 2026-10-10; GPU idle, compilation and CUDA graphs on)

16,384 rows of real positions (the root positions of generation 3's decisions, both views): win probability |diff| mean 0.0016, 99th percentile 0.0070, max 0.012; policy KL mean 4.7e-5; same top action 99.4%.

| batch size (rows) | 64 | 128 | 256 | 512 | 1,024 |
|---|---|---|---|---|---|
| FP32 (ms) | 0.83 | 0.94 | 1.34 | 2.82 | 4.24 |
| BF16 (ms) | 0.77 | 0.86 | 0.87 | 2.20 | 2.26 |
| speedup | 1.07 | 1.09 | **1.55** | 1.28 | **1.88** |

Self-play averages about 165 rows per round (padded to 256): inference about 1.5 times faster. Training already uses BF16 automatic mixed precision, so BF16 inference matches training; BF16 is the default since 2026-10-10 (FP32 when `check_batch_search.py` compares against the CPU reference). No strength comparison (the differences are far below search noise).

### Value head experiments: pv_bench (`scripts/pv_bench.py`, 2026-10-10 / 11; design in design.md P0 value head)

Test set (2/3; 1,027 self-play positions / 1,016 human). Value = value-only search (uniform prior, 800 iterations); with prior = 800 iterations. Each cell: top-choice agreement with the reference / rank correlation ρ of the option means / mean decision loss (the win-probability gap between the reference's best option and the chosen one, in percentage points; options the reference barely searched count as its worst reliable option). The standard error of top-choice agreement is about 1.5 points. The variants are all trained from sp-gen2 (the start of A = sp-gen4; generation 3 was not promoted), with sp-gen4's (A) recipe.

| network | self-play BCE | slope | prior top choice | self-play: value | self-play: with prior | human BCE | human: loss with prior |
|---|---|---|---|---|---|---|---|
| handwritten eval | 0.580 | 3.05 | — | 46.4% / 0.483 / 1.80 | 66.4% / 0.533 / 1.63 | 0.629 | 1.52 |
| v5-glu | 0.470 | 1.15 | 54.9% | 52.1% / 0.591 / 1.46 | 72.0% / 0.686 / 1.35 | 0.547 | 1.09 |
| sp-gen0 | 0.451 | 1.15 | 59.0% | 53.8% / 0.589 / 1.35 | 74.1% / 0.700 / 1.32 | 0.547 | 1.05 |
| sp-gen1 | 0.443 | 1.07 | 60.0% | 53.4% / 0.596 / 1.43 | 75.0% / 0.704 / 1.23 | 0.550 | 1.04 |
| sp-gen2 | 0.437 | 1.06 | 61.5% | 52.7% / 0.583 / 1.50 | 76.1% / 0.705 / 1.19 | 0.549 | 0.99 |
| sp-gen3 | 0.434 | 1.03 | 61.4% | 52.6% / 0.579 / 1.47 | 75.9% / 0.701 / 1.17 | 0.549 | 1.01 |
| sp-gen4 (A) | 0.433 | 1.05 | 61.2% | 52.5% / 0.583 / 1.45 | 75.3% / 0.694 / 1.20 | 0.549 | 0.98 |
| F value hidden layer 256 | 0.432 | 1.05 | 61.7% | 53.8% / 0.584 | 76.1% / 0.698 | 0.549 | |
| C λ 0.9 | 0.437 | 1.11 | 61.0% | 53.5% / 0.589 | 75.5% / 0.702 | 0.549 | |
| D λ 0.7 | 0.439 | 1.14 | 61.3% | 54.4% / 0.594 | 75.3% / 0.702 | 0.549 | |
| B 8 value positions per game | 0.432 | 1.05 | 61.5% | 53.5% / 0.584 | 74.8% / 0.698 | 0.548 | |
| E value 3 passes | 0.426 | 1.00 | 61.6% | 51.9% / 0.579 | 75.8% / 0.684 | 0.548 | |
| children: regression | 0.431 | 1.06 | 61.1% | 54.8% / 0.598 | 75.8% / 0.708 | 0.551 | |
| children: ranking | 0.439 | 1.34 | 60.7% | 51.1% / 0.581 | 72.5% / 0.676 | 0.553 | |
| children: both | 0.431 | 1.12 | 60.9% | 53.4% / 0.593 | 73.7% / 0.695 | 0.553 | |
| child regression ×2 | 0.430 | 1.05 | 61.2% | 54.0% / 0.590 | 75.5% / 0.695 | 0.552 | |
| child regression ×4 | 0.431 | 1.04 | 60.7% | 53.5% / 0.588 | 74.9% / 0.699 | 0.553 | |
| child regression ×8 | 0.431 | 1.04 | 59.9% | 53.9% / 0.596 | 74.8% / 0.695 | 0.554 | |

- Self-play BCE falls generation by generation; telling the options apart (value only) does not change; the handwritten eval is much worse, so the measure is sensitive. F, B–E make no difference; E has the best BCE but the worst move choice.
- Child regression is the best on value only (dev set 56.2%), but **in matches vs A 49.1% ± 2.9%** (3,000 iterations, 400 pairs, wide pool): a few points of offline difference do not predict matches. No dose effect from larger weights, and human BCE and the prior get worse; the ranking loss breaks calibration (slope 1.34); its code was deleted (2026-10-11), only regression kept.
- Decision loss (with prior) falls along the lineage from v5-glu's 1.35 to sp-gen3's 1.17 (human 1.09 → 0.98), the same direction as the matches (v5-glu < generations 0–2), but generations 2–4 differ within error (standard error about 0.08), consistent with the flat matches; computed later (self-play / human test set, with prior): F 1.18 / 1.00, child regression 1.18 / 1.00, A 1.20 / 0.98 (value only: F 1.40 / 1.18, child regression 1.47 / 1.18, A 1.45 / 1.19). Child regression's +2 points of top-choice agreement do not exist in decision loss, consistent with the 49.1% in matches: decision loss is less easily misled than top-choice agreement by positions that "pick the reference's top choice, but where the options differ very little".

### Large network G (`scripts/exp_capacity.py --g-only`, 2026-10-11)

G = the `large` trunk (width 192, 4 layers, 6 heads, SwiGLU 256, about 2.3 times the compute) + value hidden layer 256, trained from scratch on all the human data with v5-glu's recipe (the newly added hf games go only into the training set: about 15% more data than v5-glu), 65,589 steps (batch 4,096, the same samples per step as v5-glu, so comparable step by step). Human validation set (v5-glu's):

| step | G policy ce | v5-glu | G top1 | v5-glu | G value bce | v5-glu | G ECE | v5-glu |
|---|---|---|---|---|---|---|---|---|
| 10,000 | 1.171 | 1.191 | 54.6% | 53.9% | 0.555 | 0.556 | 0.021 | 0.007 |
| 30,000 | 1.130 | 1.155 | 56.1% | 55.2% | 0.571 | 0.555 | 0.047 | 0.027 |
| 52,000 (G's best) | 1.102 | 1.136 | 57.1% | 55.9% | 0.562 | 0.545 | 0.040 | 0.014 |
| last | 1.097 | 1.135 | 57.3% | 55.9% | 0.568 | 0.544 | 0.047 | 0.013 |

- Policy: the large network leads from about step 8,000 on; at the end ce −0.038, top1 +1.4 points.
- Value: **overfits**. Training value bce reaches 0.43 (v5-glu 0.52); validation bce swings widely between 0.553 and 0.727 (ECE 0.13 at the spikes), returns to 0.568 after the learning rate decays, still 0.024 worse than v5-glu. Each game has only one result signal, and 2M games are not many for the value; the large network memorizes game results first. Capacity is not the value's bottleneck (consistent with F).
- Self-play fine-tuning: from G's best checkpoint (`--init-ckpt best`), A's recipe (sp0–sp4, 4,013 steps): human ce 1.125 (A 1.159), value bce 0.594 (A 0.548), ECE 0.065; self-play ce 1.308 / top choice 71.1% (A 1.286 / 73.9%), self-play value bce 0.446 (A 0.441). A accumulated through per-generation fine-tuning (lineage sp-gen0 → 1 → 2 → 4, 6,716 steps in all; generation 3 was not promoted and is not in the lineage), so a single fine-tune of A's length is unfair to G; changed to 8,500 steps (`--g-ft-steps lineage`, exp-G-large-ft8500; at the time the unpromoted generation 3 was mistakenly counted too, about 27% more than A's 6,716 steps, no effect on the conclusion; it now sums along the warm-start chain) before comparing on pv_bench and in matches.
- pv_bench (test set; each cell top-choice agreement / ρ / decision loss):

| network | self-play: with prior | human: with prior | prior-only loss (self-play / human) | self-play BCE | human BCE |
|---|---|---|---|---|---|
| A = sp-gen4 | **75.3% / 0.694 / 1.20** | **72.8% / 0.696 / 0.98** | 2.02 / 2.06 | 0.433 | 0.549 |
| G 4,013 steps | 71.2% / 0.634 / 1.31 | 66.2% / 0.561 / 1.21 | 1.92 / 1.96 | 0.429 | 0.562 |
| G 8,500 steps | 71.3% / 0.640 / 1.29 | 67.4% / 0.611 / 1.18 | 1.90 / 2.02 | 0.443 | 0.539 |
| G 8,500 steps + child regression | 72.2% / 0.643 / 1.28 | 68.8% / 0.613 / 1.14 | 1.91 / 2.02 | 0.425 | 0.544 |

- With more fine-tuning steps, self-play top-choice agreement stops at 71.5% after about 5,000 steps (A 73.9%): the gap is not the amount of training.
- **Match: G (8,500 steps) vs A, both 3,000 iterations, 400 pairs, wide pool: 49.8% ± 2.9%**, even. On pv_bench G with prior trails by 3–6 points, ρ 0.05–0.08 lower, loss about 0.1 higher, yet it does not lose the match: **pv_bench (and the self-play validation set) favour the lineage the reference comes from** (reference = deep searches of v5-glu and sp-gen2; A was fine-tuned all the way along the same lineage), so they cannot compare independently trained architectures; they only suit comparing variants within one lineage.
- Conclusion: the large network with 2.3 times the compute is not stronger than A at the same number of iterations (at the same time it can only be worse); its policy is clearly better on human data, its value is not, matches are even, consistent with "the value is the bottleneck".

### Win-margin auxiliary head (`scripts/exp_margin.py`, 2026-10-11)

sp-gen5's training (same start sp-gen4, same data, 3,280 steps) plus an auxiliary head for the difference in remaining Pokémon (13 classes, auxiliary loss weight 0.3; not used by the search). Margin head accuracy 22.9% (13 classes). Human ce 1.166 / bce 0.550 (sp-gen5 1.164 / 0.549), self-play top choice 75.1% / BCE 0.4426 (75.5% / 0.4415); pv_bench loss with prior self-play 1.15 / human 1.02 (1.18 / 1.07), value-only top choice 53.4% (54.2%). **Match vs sp-gen5: 50.1% ± 2.9%** (398 pairs, 3,000 iterations, wide pool; both sides with the search after the timer fixes). Not adopted: as a pure auxiliary loss it does not help the value; using it would mean the search using the score directly (KataGo-style), a big change.

### Source of value data: games without search (`scripts/exp_value_source.py` / `exp_value_scale.py` / `exp_value_only.py`, 2026-10-11 / 12; design in design.md P0 value data)

Games without search = sampling from the network prior (`selfplay.py run --policy-only`, value labels only), 12 processes about 100k games/hour. pv_bench test set, each cell: result BCE / value-only decision loss / decision loss with prior (standard errors: BCE about 0.016, loss about 0.08). Head A = a two-layer MLP (256) on a frozen trunk, B = A + one value-only Transformer block, BU = B + the trunk's top block unfrozen (`--policy-anchor 1` keeps the policy).

| network | data | self-play test | human test |
|---|---|---|---|
| sp-gen5 | — | 0.429 / 1.44 / 1.18 | 0.547 / 1.17 / 1.07 |
| VS-S (sp-gen5's recipe, joint training) | 50k search games (generation 5) | 0.433 / 1.43 / 1.19 | 0.548 / 1.17 / 1.00 |
| VS-P (same) | 50k games without search | 0.440 / 1.38 / 1.25 | 0.551 / 1.22 / 0.97 |
| VH-A-S (frozen trunk) | search games | 0.430 / 1.44 / 1.13 | 0.547 / 1.15 / 0.97 |
| VH-A-P / VH-B-P | games without search | 0.430 / 1.44 / 1.19, 0.432 / 1.42 / 1.16 | 0.547 / 1.21 / 1.01, 0.548 / 1.19 / 1.02 |
| VX-A4 / A1 / B4 / B4U1 (mixed with human data, sp_frac 0.75, value counted once, 3,280 steps) | 400k games without search, 4 (A1: 1) positions per game | 0.430 / 1.45–1.49 / 1.15–1.22 | 0.547 / 1.14–1.18 / 0.95–1.00 |
| VO-A / B / BU (new positions only, sp_frac 1, counted every time drawn, chosen by BCE on held-out no-search positions) | same as above (about 1.52M training positions, 3 passes) | 0.431–0.434 / 1.45–1.50 / 1.15–1.16 | 0.549–0.555 / 1.19–1.26 / 0.99–1.03 |

- Value BCE on held-out no-search positions (start sp-gen5 0.4424): VX's lowest during training 0.4392 (step 656), then back near the start (mixed with human data and value counted once, the later steps learn only the human value); after the fix VO-A 0.4392, VO-B 0.4371, VO-BU 0.4370, topping out after 300–600 steps, training BCE matching validation (not overfitting: the floor set by label noise). Human value BCE gets worse by 0.002–0.008 along with it.
- Matches (1,600 iterations each, wide pool, paired): VH-A-S vs sp-gen5 49.7% ± 2.9% (400 pairs); VX-B4 49.6% ± 2.9% (400 pairs); VO-A 46.2% ± 3.8% (210 pairs, stopped midway to start generation 6).
- Conclusion: **value labels from games without search bring no measurable gain**. The BCE drop of 0.003–0.005 is only calibration to the result distribution of no-search games and did not turn into better decisions (the value-only loss is even slightly worse).

### Stall loops: games at the 300-turn cap (2026-10-14; generation 6's 199 games + generation 7's 200, about 0.2% of the games, about 2% of the self-play compute)

| category (last 100 turns) | games | share | games with Regenerator still on the field |
|---|---|---|---|
| both sides switch all the time | 312 | 78% | 304 |
| one side switches all the time, the other attacks | 53 | 13% | 48 |
| attack / recovery attrition | 27 | 7% | 22 |
| almost no damage | 7 | 2% | 6 |

- What remains is mostly stall team members (Corviknight, Alomomola, Gliscor, Dondozo, Toxapex, Blissey, Slowking-Galar, Clodsire).
- The value is accurate: of the 477 games decided at turns 150–299, the side with value 0.8–1.0 at turns 100–140 wins 94%, 0.6–0.8 wins 73%, 0.4–0.6 wins 48%. But among generation 6's games at the cap, in 31% one side has value ≥ 0.9 and in 29% 0.75–0.9; only in 40% are both sides close: **the winner does not close it out** (example: the opponent has only a Latios at 1% HP and a Corviknight left, and the side with all 6 keeps switching).
- Mechanism (generation 6's 61,666 decisions after turn 150): in the both-sides-switch category, the median difference between the means of moves and switches is −0.004 (77% within 0.02); the switches' visit share 0.71 ≈ their prior share 0.69 (the search barely changes the prior); the late temperature 0.25 makes 88% pick a switch. The winner's value is saturated (all options about 1), with no "win faster" gradient; games at the cap have no value labels while their policy targets train as usual, self-reinforcing "against stall, switch".
- Loop detection (one side has had no Pokémon faint for 20 turns and switched 6 times in the last 8 turns): on generation 6's data it catches every game at the cap, and touches only 1.6% of the games / 0.46% of the decisions of normal games.
- The tiebreak (`agents/tiebreak.py`) changes 12 of the 28 decisions in 4 "far ahead but keeps switching" games, all to moves that make progress (Spikes, Toxic, Infestation, Scald, Bulldoze).

### Match A/B of the engine state fixes (2026-10-11, design in D17)

The same sp-gen5; side A with the fixes, side B with the engine state from before them (`ALPHA_STATE_FIXES_B=0`), 1,600 iterations, wide pool; the confusion patch is in the engine, so both sides have it.

| side A's fixes | result |
|---|---|
| Timers (sleep / Rest, Toxic, consecutive Protect, Wish, confusion / Taunt / Encore / Yawn) + vanished items not resampled (3,000 iterations) | 45.2% ± 5.4% (115 pairs, stopped): the Protosynthesis / Quark Drive boost was never passed to the engine, the old item resampling happened to make up for it, and fixing items alone removed that |
| The above + stat boosts and other volatile statuses + Future Sight | **56.2% ± 2.5%** (598 pairs; about +43 Elo) |

| All fixes (tier 2: + Revival Blessing searched over candidates, PP from the request, Eject Button / Red Card, opponent speed inference) vs the previous row's version (tier 1) | **51.96% ± 2.43%** (600 pairs; interval 49.5%–54.4%: not worse, about +14 Elo, not significant); fallbacks A 0 / B 4 (B's Revival Blessing takes the old path) |
| (stopped midway) all fixes vs all off | 57.2% ± 5.9% (97 pairs) |
| Tier 3 (2026-10-13: must recharge, opponent PP, Perish Song / Disable, Heal Block / Magnet Rise / Throat Chop timers, Substitutes that have been hit, extender items, new items by name, Illusion) vs tier 2, sp-gen6; that day's engine patches on both sides | 48.96% ± 2.43% (600 pairs; void: this version had two bugs, fixed after code review (`bb066b0`): poke-env's must-recharge flag was not cleared after the recharge turn, so a Pokémon done recharging was treated as still having to recharge; Perish Song's old count was passed in as well) |
| Tier 3 (after the review fixes, `bb066b0`) vs tier 2, sp-gen6 | **52.08% ± 1.66%** (1,200 pairs: wide1000's first 600 pairs 51.46% ± 2.40%, the new 600 pairs (wide1000 600–999 + wide200) 52.67% ± 2.29%; interval 50.4%–53.7%, significant, about +14 Elo; fallbacks 0 / 0) |
| Context in the search tree (2026-10-14, merged `96a7770`: a move counts as used / revealed only by the engine's `Acted` flag; not acting is recorded as "fainted before acting" / "prevented"; the forced switch after a faint is not a new turn) vs the old context (`ALPHA_LEGACY_CONTEXT_B=1`), sp-gen7 | **51.33% ± 1.65%** (1,200 pairs: wide1000 51.62% ± 2.32%, ab600b 51.08% ± 2.35%; interval 49.7%–53.0%: both batches point the same way, slightly better, not significant, not worse; fallbacks 0 / 0) |
| Tiebreak (`agents/tiebreak.py` defaults: root value ≥ 0.85, mean difference ≤ 0.01, visits ≥ 5%, progress ≥ 0.1 more) on vs off, sp-gen7 | **48.75% ± 1.66%** (1,200 pairs: wide1000 48.17% ± 2.38%, ab600b 49.33% ± 2.31%; interval 47.1%–50.4%, both batches low, about −9 Elo, not significant but no help). It fires often: in 766 of 2,400 games (32%), 2,687 times in all; A wins 91.5% of the games where it fired (games that were already ahead), and games did not get shorter (games won by A / by B average about 33 turns); 0 games at the cap (the evaluation itself rarely loops). Kept off |

For comparison: recent self-play generations score 50–51% each.

### Engine accuracy's effect on decisions (2026-10-18; before and after the differential work L1–L228, doc/engine-diff.md)

Question: before the differential work, the engine's per-turn agreement was only about 86%. Was it the bottleneck of self-play progress?

Method:
- The old version is `6fbfde5` (10-15), from before the differential work started. Only its alpha_search plus the old engine are compiled separately as `alpha_search_old`, in the same process as the new version. The two versions' search code (ismcts / tnet / BatchSearch) is identical; the changes to features.rs keep the meanings the network was trained with; the old engine parses the new state string format without problems. So the comparison isolates the engine alone. The damage features the network gets from the engine also change with the engine; that part counts as the engine's effect.
- Positions: the decision points at turn start in 120 games of generation 8 self-play (old code, network v6-s-spread), merged from both sides' records into perfect-information positions, 5,288 in all.
- Each position runs: 2 single-world PUCT searches of 800 iterations each with the new and with the old engine (different seeds), plus one 16,000-iteration deep search with the new engine as the reference.
- Confidence intervals by cluster bootstrap over games.

| measure | value [95% interval] |
|---|---|
| top choice differs: new vs new (seeds only, i.e. search noise) | 7.4% [6.5, 8.5] |
| top choice differs: old vs new | 10.1% [8.8, 11.6] |
| **flip rate beyond noise** | **2.7% [1.9, 3.5]**; 185 flips stable across both seeds (3.5%), mostly move↔move and switch↔move, only 8 involving tera |
| total variation of the visit distributions: new vs new / old vs new | 0.054 / 0.072 |
| root network prior's top choice differs | 1.1% |
| agrees with the deep search's top choice: new / old | 75.8% / 74.3% |
| regret per decision under the reference search (win probability): new / old | 0.0049 / 0.0056 |
| **old's extra regret over new** | **0.0007 [0.0003, 0.0012]** / decision; the same when sampling from the visit distribution (τ = 1) |

Conclusions:
- The old engine's errors do make decisions worse, significantly, but only slightly. About 0.07% win probability lost per decision; with about 22 decisions per side per game, summed step by step about 1.5% win probability, on the order of +10 Elo (+5 to +18).
- **Match A/B check** (the user questioned this: "errors accumulate over many steps in a game"): the same v6-s-spread, both sides GPU batched search, 1,600 iterations, ml3; A with the current engine, B with the old one (B's Batcher uses `alpha_search_old`). Result: wide1000 **52.58% ± 2.43%** (600 pairs), ab600b **52.17% ± 2.39%** (600 pairs), together **52.38% ± 1.70%** (1,200 pairs, **+16.5 Elo**, interval +4.7 to +28.4); 0 failures, 0 fallbacks. Both batches point the same way, and the result is significant. The whole-game result is slightly above the step-sum estimate (+16.5 vs +10), but the confidence intervals overlap: errors over many steps do add up, but they do not grow by an order of magnitude. This fits the analysis that "win-probability losses add up per step": an earlier step's mistake shows in the values of the later positions; the losses do not multiply. What was measured is the gain from swapping the engine once with a fixed network, search budget and team distribution: neither an upper bound on the gains of all engine improvements nor, strictly, a lower bound on the gain after retraining. The network was trained on the old engine's search targets and may have adapted to the old engine's biases, which would make the measured gain low; the effect on the network's training signal was not measured this time.
- The loss is highly concentrated: the top 1% of positions contribute the whole net difference; the other positions cancel out and are noise. In the examples with the largest regret, the old and new engines have the same transition on the current turn; the difference is in turns deeper in the tree. So the effect comes from chain effects in a few key positions, not from a widespread bias.
- By comparison: under the same reference, the 800-iteration search itself has a regret of 0.0049, about 7 times the engine error; the search's seed noise (7.4%) is also nearly 3 times the engine flips (2.7%). The 10-11 fix of "the position passed to the engine" (timers, stat stages, volatile statuses) brought +43 Elo. So the main bottleneck behind the earlier slow self-play progress was not engine accuracy but the search budget and the network's quality, and second whether the position passed to the engine is accurate. Engine accuracy brings about +16 Elo: real, about one or two generations of self-play progress, but not the main bottleneck.
- Limits:
  - the reference search itself uses the new engine, which favours the new version;
  - the positions are perfect-information single worlds, while real games use 32 belief worlds;
  - the positions come from the old system's own games, so their distribution is set by the old system;
  - converting single steps to Elo is crude; the match A/B is the direct whole-game measurement (above).

### Match A/B of a batch of state / engine fixes, 2026-10-25 (`819ea86` vs `c2d8711`)

All the fixes since the previous A/B (B6, `c2d8711`): state construction (B8; S157; S158a–d: natures and EVs, the opponent's Choice lock, hidden formes, a disguised Zoroark's tera type and level, Transform-locked slots, a pending Healing Wish, the order of Toxic Spikes, the Rage Fist count, Revival Blessing uses, one-time abilities after Transform, the Stellar flag) and the engine (L243–L247: 0 PP while locked, moves Sleep Talk should not call, no further resolution once the game is decided, Cursed Body per hit, Magic Bounce before the accuracy check). Both state construction and the engine changed, and one process cannot hold two copies, so a new split evaluation is used (`scripts/eval_pairs.py --other`: side B is run by a worktree of the old version with its own venv; the split's own A/A 8 / 16).

The same v6-h, both sides GPU batched search, 1,600 iterations, ml3: wide1000 **49.33% ± 2.38%** (600 pairs), ab600b **50.88% ± 2.41%** (600 pairs), together about **50.1% ± 1.7%**: even; 0 failures, 0 fallbacks on both sides, all teams matched. As expected: each of these fixes affects few positions (most of `state_chain`'s 9,475 cases sit in a few fields and a few games), and the whole old engine's error was worth only +16.5 Elo (above). The log's `switch greninja: not a live benched mon` is a false alarm of the consistency check (the order layer matches Greninja-Bond back to the request by prefix, fixed 2026-10-24, and the check had not followed; both versions have it, 867 times on the old version's side); fixed.

### Regression check of the code cleanup (2026-10-14, `dde3ef0` / `2e71ed3` / `7575f7a`)

- Deterministic checks (fixed seeds) identical before and after: the validation metrics of 40 sp-gen7 training steps (weight difference < 7e-9); 27 engine states of a test game; search results (UCB1, CPU network PUCT, batched search, 2 positions); `check_tnet` error < 7e-6.
- End-to-end match: sp-gen7 vs sp-gen6, GPU pipeline, 1,600 iterations, wide1000: **50.83% ± 2.44%** (600 pairs; 49.83% ± 2.64% at promotion, consistent); fallbacks 0 / 0, failed games 0.

## Key match results

### Search + network (ISMCTS, heldout, 500 ms per move single-threaded, 32 worlds, 300 games)

| A | B | A win rate | Elo | notes |
|---|---|---|---|---|
| value network + both priors (`s_ismcts_pv`) | handwritten eval (`s_ismcts`) | **66.3% ± 5.2%** | +117 | the total effect of the network entering the search |
| value network only (`s_ismcts_net`, UCB1) | handwritten eval | 37.0% ± 5.3% | −92 | about 10 times fewer iterations + the absolute win rate compresses the gap |
| value network + both priors | value network only | **73.0% ± 5.0%** | +173 | the policy prior's contribution |
| value network + both priors | prior + handwritten eval (`s_ismcts_p`) | **56.7% ± 5.3%** | +47 | the value network still contributes with priors (implied: prior + handwritten vs handwritten about +70 Elo) |

Iterations per move (500 ms, 32 worlds, 8 processes running concurrently): handwritten about 93k, value only about 9k, value + prior about 6k, prior + handwritten about 11k (the prior is computed only on a node's second visit). Median of the largest root visit share: handwritten 0.57, value only 0.26, value + prior 0.66, prior + handwritten 0.68.

### The full Transformer in the search (heldout, 500 ms per move single-threaded, 32 worlds, 300 games; 2026-10-07)

| A | B | A win rate | Elo | notes |
|---|---|---|---|---|
| Transformer v5-final (`s_ismcts_tf`, Rust CPU inference) | v1 medium MLP (`s_ismcts_pv`) | **58.0% ± 5.5%** | +56 | about 1.5k–3.6k iterations per move vs about 6.6k; both priors + value |
| the same network, GPU tree-parallel search (`s_ismcts_tfg`, batch 32 × 5 threads, pipelined) | the same network, CPU search (`s_ismcts_tf`) | **60.8%** (paired 61.3% ± 8.2%) | about +80 | stopped after 107 games (2 games in parallel, the GPU version only used 5 threads); `20261007-140457` |

### Proxy measures of search quality (the same 0.5 s, 40 positions, 32 identical worlds; root top choice and visit distribution compared with a single-tree 16,000-iteration deep search)

| search | leaves per move | top-choice agreement | total variation |
|---|---|---|---|
| two deep searches (different seeds): ceiling | 16,000 | 82% | 0.148 |
| CPU single tree 1k / 2k / 4k / 8k iterations (no time limit) | — | 55% / 62% / 78% / 82% | 0.290 / 0.249 / 0.200 / 0.148 |
| CPU single thread, 0.5 s | 3,600–3,750 | 65% | 0.254–0.261 |
| GPU root-parallel 8 trees × batch 16 | 17,698 | 62% | 0.271 |
| GPU tree-parallel, batch 32 × 8 threads | 11,203 | 75% | 0.204 |
| GPU tree-parallel + pipelining, batch 16 / 32 / 48 | 12,021 / 16,161 / 16,759 | 72% / 70% / 78% | 0.196 / 0.195 / 0.213 |
| GPU tree-parallel, batch 64 / 128 (vl 3) | 13,657 / 16,025 | 70% / 57% | 0.214 / 0.288 |

### Search settings for self-play (`scripts/check_search_targets.py`, 60 positions, compared with a single-tree 16,000-iteration noiseless deep search; 2026-10-07)

| search | top-choice agreement | total variation | single-thread time / search |
|---|---|---|---|
| the network prior itself | 47% | 0.406 | — |
| 500 / 1,000 / 2,000 / 3,000 / 4,000 iterations | 57% / 63% / 70% / 73% / 78% | 0.300 / 0.272 / 0.230 / 0.204 / 0.184 | 0.19 / 0.39 / 0.78 / 1.16 / 1.54 s |

(47% is the agreement with the deep search's top choice, not with human actions: the latter is the top-1 of 55.6%.)

Root Dirichlet noise (3,000 iterations; exploration = the fraction of moves with prior < 5% that get ≥ 10% of the visits, "useful" = the fraction of those to which the deep search also gives ≥ 10%):

| ε \ total concentration | 3 | 10 | 30 |
|---|---|---|---|
| 0 | 72% / 0.201 / 4.4% / 78% (no noise) | | |
| 0.10 | 72% / 0.224 / 4.6% / 68% | **82% / 0.180 / 5.3% / 77%** | 80% / 0.194 / 5.3% / 73% |
| 0.25 | 70% / 0.247 / 5.1% / 67% | 72% / 0.228 / 5.1% / 62% | 72% / 0.222 / 5.8% / 58% |
| 0.40 | 68% / 0.273 / 6.5% / 48% | 73% / 0.245 / 5.1% / 62% | 68% / 0.258 / 5.6% / 65% |

(Each cell: top-choice agreement / total variation / exploration / useful.) Chosen: ε = 0.10, total concentration 10.

### ISMCTS vs determinization (heldout, 300 games)

| A | B | setting | A win rate |
|---|---|---|---|
| ISMCTS N=32 (`s_ismcts`) | determinization K=4 (`s_computed`) | 500 ms | **57.3% ± 5.3%** |
| ISMCTS N=1 (`s_ismcts_n1`) | poke-engine MCTS K=1 (`s_c_k1`) | 500 ms | 50.7% ± 5.4% (implementation correctness: even) |
| ISMCTS closed-loop for the first 2 levels (`s_ismcts_cl2`) | ISMCTS open-loop | 500 ms | 48.2% ± 5.1% (no gain) |
| ISMCTS | determinization K=2 | 200 ms (`normal` level) | 48.3% ± 5.4% (even) |
| ISMCTS | determinization | 1000 ms × 4 (`hard` level) | 36.4%, only 46 games, aborted, for reference only |

### Breakdown of the determinized search (`s_computed` as B, 500 ms × 4, 300 games)

| A | A win rate | notes |
|---|---|---|
| knows the opponent's sets fully (`s_c_oracle`) | 58.3% ± 5.5% | the total value of the hidden information |
| knows moves only | 57.5% ± 5.1% | mostly from the moves |
| knows EV spreads only | 53.2% ± 5.1% | |
| knows items only | 51.3% ± 5.2% | |
| knows tera only | 49.8% ± 5.2% | |
| K=1 / 2 / 8 / 16 samples | 44.2 / 45.0 / 49.8 / 45.0% | inverted U, best K=4–8 |
| moves β=1 / 2 / 3 (heldout) | 53.7 / 52.2 / 47.7% | default β=1 |
| after the 1 HP bug fix vs before (`d93802d`) | 58.5% ± 6.2% (200 games) | |

### LLM plans (2026-10-05, 500 ms × 4)

| A | B | A win rate |
|---|---|---|
| LLM lead (`s_llmplan`) | rule-based lead (`s_computed`) | 47.3% ± 6.6% (186 games; no value) |
| LLM plan as prior (`s_llmplan_prior`) | `s_llmplan` | 46.8% ± 7.3% (174 games; no gain) |
| knows the opponent's true sets (`s_oracle`) | `s_llmplan` | 61.8% ± 6.4% (186 games) |

### Against Foul Play (external baseline)

| A | opponent level | A win rate |
|---|---|---|
| heuristic knowledge bot (`k_llmplan`) | 1000 ms × 4 | about 10% (6 rounds × 20 games: 5–20%) |
| heuristic knowledge bot | 100 / 30 / 10 ms × 1 | 20% / 27.5% / 42.5% (20–40 games each) |
| determinized search (`s_llmplan`) | 10 ms × 1 | 65.0% (40 games) |
| determinized search | 1000 ms × 4 | 15.0% (20 games) |
| **`s_ismcts_tfg` (baseline-v5: full Transformer + GPU tree parallelism, 1.9 s per move, 6 threads)** | **1000 ms × 4 (actually about 1.65–1.9 s per move)** | **49.5% (paired 49.0% ± 7.7%, 101 games, heldout)**; `20261007-150729`, stopped at 101 games. Ours about 41k iterations per move, Foul Play about 3.5M (independent trees of 8 worlds). The information asymmetry favours Foul Play: about 80% of its set predictions come from a "complete teams" database, which very likely knows the copied popular teams in the pool, while we use the heldout belief. |
| `s_ismcts_ma` sp-gen1 (CPU 200 ms, wide200) | 200 ms × 1 | 59.1% ± 4.4% (198 pairs, 2026-10-09) |
| `s_ismcts_ma` sp-gen5 (before the fixes) | 200 ms × 1 | 61.7% ± 4.2% (199 pairs, 2026-10-11) |
| **`s_ismcts_ma` sp-gen5 + all engine state fixes (`best-2026-10-11`)** | 200 ms × 1 | **63.5% ± 4.4%** (200 pairs, 2026-10-11): +1.8 over before the fixes, not significant (in the self-play A/B the fixes were worth about +43 Elo; here the 200 ms CPU search per move runs far fewer iterations, and the opponent plays differently) |
| `s_ismcts_ma` sp-gen6 (generation 6 + the Transform fix) | 200 ms × 1 | **64.3% ± 4.6%** (198 pairs, 397 games, 2026-10-13; the last 3 games were stopped after getting stuck when Foul Play itself crashed (`format_decision`'s `can_z` AttributeError)): even with sp-gen5. Our measured iterations per move (8 lines concurrently, traces of 8 wide200 pairs): median 768, p10 512, p90 768 (in batches of 256; the mean of 1,523 is pulled up by endgames), time median 0.25 s; promotion and self-play use 1,600 |
| `s_ismcts_ma` sp-gen6 | 1,000 ms × 1 (1 second for each side) | **62.6% ± 4.5%** (200 pairs, 2026-10-13; our iterations per move median 3,072, p10 2,816, p90 4,352): even with the 64.3% at 200 ms (difference −1.7, not significant); with 5 times the time the relative edge does not change noticeably. 1 fallback (a must-recharge turn, see design.md D17 pending fix K) |
| `s_ismcts_ma` v6arch-pp (v7.3) | 200 ms × 1 | **68.4% ± 4.1%** (200 pairs, wide200, 2026-10-26) |
| `s_ismcts_ma` v6arch-pp-v75 | 200 ms × 1 | **65.0% ± 4.1%** (199 pairs, wide200, 2026-10-26): paired difference with v7.3 −3.7 ± 5.1, not significant |
| `s_ismcts_ma` v6arch-pp-v75 | **5,000 ms × 2** (5 seconds per move for both sides: ours 2 threads, Foul Play 2 sampled worlds; 4 lines, 16 threads in all) | **67.1% ± 6.3%** (108 pairs, 220 games, the start of wide1000, 2026-10-27, stopped early as planned): even with 200 ms -- adding time to both sides together leaves the relative edge unchanged. About 36 turns and 6.5 minutes per game (Foul Play doubles its sampling when most of the opponent's moves are unknown); 1 game failed: Foul Play's own Keldeo turned into Keldeo-Resolute during the game and it could not find it (`Could not find keldeoresolute in team_dict`, restarted after the crash); that pair is not counted |

### Heuristic knowledge bot (2026-10-04, 2000 games each)

| A | B | A win rate |
|---|---|---|
| `knowledge` | `heuristic` | 65.3% ± 2.0% (heldout 65.8%) |
| `knowledge` | no belief / no plan / no lead / random lead | 51.6 / 49.0 / 50.2 / 49.9% |

<!-- BEGIN GENERATED -->

### Training runs (generated)

| run | params | positions (train / val) | epochs | min | val policy CE | top-1 | top-3 | val value BCE | value acc | early / mid / late | ECE | train−val gap (policy / value) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| test0/20261006-140749_test0_small | 208k | 0.23M / 7k | 0.0 | 0.3 | 1.925 | 24.5% | 63.2% | 0.6035 | 66.7% | 60.0% / 72.2% / 76.4% | 0.014 | — |
| v1/v1-large-residual | 1431k | 7.88M / 244k | 6.0 | 3.0 | 1.420 | 48.8% | 83.2% | 0.5634 | 69.6% | 64.3% / 74.4% / 76.9% | 0.020 | 0.135 / 0.021 |
| v1/v1-medium-plain | 468k | 7.88M / 244k | 6.0 | 2.6 | 1.418 | 48.8% | 83.1% | 0.5653 | 69.3% | 63.8% / 74.3% / 76.6% | 0.011 | 0.055 / 0.009 |
| v1/v1-medium-residual | 468k | 7.88M / 244k | 6.0 | 6.9 | 1.413 | 48.9% | 83.2% | 0.5625 | 69.5% | 64.2% / 74.4% / 76.6% | 0.009 | 0.053 / 0.005 |
| v1/v1-small-residual | 208k | 7.88M / 244k | 6.0 | 2.5 | 1.445 | 47.7% | 82.4% | 0.5668 | 69.1% | 63.6% / 74.2% / 76.3% | 0.004 | 0.021 / -0.001 |
| v2h/v2h-mlp-h32 | 599k | 2.35M / 73k | 5.9 | 1.3 | 1.505 | 45.2% | 80.4% | 0.5741 | 68.7% | 63.3% / 73.6% / 75.6% | 0.023 | 0.082 / 0.024 |
| v2h/v2h-transformer-h16 | 599k | 2.35M / 73k | 5.9 | 3.7 | 1.418 | 49.0% | 83.0% | 0.5758 | 68.5% | 63.0% / 73.5% / 75.5% | 0.029 | 0.120 / 0.031 |
| v2h/v2h-transformer-h32 | 601k | 2.35M / 73k | 5.9 | 5.6 | 1.415 | 49.1% | 83.1% | 0.5722 | 68.6% | 62.8% / 74.0% / 75.9% | 0.025 | 0.123 / 0.023 |
| v2h/v2h-transformer-h8 | 598k | 2.35M / 73k | 5.9 | 5.1 | 1.418 | 49.1% | 82.9% | 0.5739 | 68.8% | 63.2% / 74.0% / 75.6% | 0.026 | 0.128 / 0.030 |
| v2m/v2m-mtp0-e10 | 598k | 2.35M / 73k | 9.9 | 4.9 | 1.420 | 48.7% | 83.0% | 0.5752 | 68.7% | 63.1% / 73.8% / 75.9% | 0.032 | 0.220 / 0.064 |
| v2m/v2m-mtp0-s1 | 598k | 2.35M / 73k | 5.9 | 2.9 | 1.422 | 48.7% | 82.9% | 0.5728 | 68.6% | 63.0% / 73.7% / 75.9% | 0.017 | 0.124 / 0.014 |
| v2m/v2m-mtp0-s2 | 598k | 2.35M / 73k | 5.9 | 3.3 | 1.415 | 49.0% | 83.2% | 0.5693 | 68.8% | 63.2% / 74.0% / 75.5% | 0.019 | 0.123 / 0.015 |
| v2m/v2m-mtp3-w0.2-e10 | 637k | 2.35M / 73k | 9.9 | 5.3 | 1.418 | 48.6% | 83.0% | 0.5715 | 68.7% | 62.7% / 74.2% / 76.4% | 0.029 | 0.213 / 0.051 |
| v2m/v2m-mtp3-w0.2-s1 | 637k | 2.35M / 73k | 5.9 | 3.4 | 1.407 | 49.3% | 83.3% | 0.5683 | 69.2% | 63.5% / 74.4% / 76.7% | 0.025 | 0.122 / 0.027 |
| v2m/v2m-mtp3-w0.2-s2 | 637k | 2.35M / 73k | 5.9 | 3.4 | 1.411 | 49.2% | 83.2% | 0.5716 | 68.9% | 63.4% / 74.0% / 76.1% | 0.033 | 0.119 / 0.037 |
| v2m/v2m-mtp3-w0.2 | 637k | 2.35M / 73k | 5.9 | 3.3 | 1.414 | 49.1% | 83.1% | 0.5700 | 68.8% | 63.0% / 74.1% / 75.8% | 0.028 | 0.124 / 0.028 |
| v2m/v2m-mtp3-w0.5-d0.5-s1 | 637k | 2.35M / 73k | 5.9 | 3.2 | 1.413 | 49.0% | 83.2% | 0.5695 | 69.1% | 63.3% / 74.2% / 77.2% | 0.030 | 0.098 / 0.034 |
| v2m/v2m-mtp3-w0.5-d0.5-s2 | 637k | 2.35M / 73k | 5.9 | 4.1 | 1.420 | 48.9% | 82.8% | 0.5640 | 69.3% | 63.7% / 74.3% / 77.0% | 0.020 | 0.101 / 0.018 |
| v2m/v2m-mtp3-w0.5-d0.5 | 637k | 2.35M / 73k | 5.9 | 3.6 | 1.421 | 48.7% | 82.8% | 0.5666 | 69.1% | 63.5% / 74.2% / 76.1% | 0.022 | 0.103 / 0.021 |
| v2m/v2m-transformer-h8-mtp0 | 598k | 2.35M / 73k | 5.9 | 5.0 | 1.418 | 49.0% | 83.1% | 0.5748 | 68.6% | 62.8% / 73.9% / 75.9% | 0.029 | 0.130 / 0.031 |
| v2m/v2m-transformer-h8-mtp1 | 636k | 2.35M / 73k | 5.9 | 3.0 | 1.438 | 47.9% | 82.5% | 0.5704 | 68.8% | 63.0% / 73.9% / 76.8% | 0.012 | 0.089 / 0.009 |
| v2m/v2m-transformer-h8-mtp3 | 637k | 2.35M / 73k | 5.9 | 3.1 | 1.423 | 48.7% | 82.9% | 0.5674 | 69.0% | 63.6% / 73.9% / 76.0% | 0.022 | 0.110 / 0.019 |
| v2s/v2s-mlp-hist | 525k | 2.35M / 73k | 5.9 | 0.9 | 1.495 | 45.7% | 80.5% | 0.5737 | 68.5% | 63.1% / 73.5% / 75.2% | 0.022 | 0.076 / 0.022 |
| v2s/v2s-mlp | 468k | 2.35M / 73k | 5.9 | 2.9 | 1.532 | 44.3% | 79.9% | 0.5751 | 68.5% | 63.2% / 73.3% / 75.2% | 0.025 | 0.084 / 0.026 |
| v2s/v2s-transformer-hist | 598k | 2.35M / 73k | 5.9 | 2.8 | 1.418 | 49.0% | 82.9% | 0.5734 | 68.7% | 63.1% / 73.9% / 75.4% | 0.030 | 0.127 / 0.031 |
| v2s/v2s-transformer | 573k | 2.35M / 73k | 5.9 | 1.9 | 1.473 | 46.8% | 81.7% | 0.5749 | 68.7% | 62.9% / 74.0% / 76.3% | 0.030 | 0.120 / 0.034 |

### Evaluation runs (generated; runs with ≥ 20 games)

| run (log) | A | B | games | A win | paired ± 95% | fallbacks | commit | settings |
|---|---|---|---|---|---|---|---|---|
| 20261004-210553 | knowledge | heuristic | 40 | 62.5% | 62.5% ± 14.0% | — | — | — |
| 20261004-210635 | knowledge | knowledge_twin | 60 | 53.3% | 53.3% ± 11.7% | — | — | — |
| 20261004-210723 | knowledge | knowledge_twin | 2000 | 48.7% | 48.7% ± 1.7% | — | — | — |
| 20261004-210838 | knowledge | heuristic | 2000 | 65.3% | 65.3% ± 2.0% | — | — | — |
| 20261004-210904 | k_none | heuristic | 2000 | 63.7% | 63.7% ± 1.9% | — | — | — |
| 20261004-210923 | knowledge | k_nobelief | 2000 | 51.6% | 51.6% ± 1.9% | — | — | — |
| 20261004-211027 | knowledge | k_noplan | 2000 | 49.0% | 49.0% ± 1.9% | — | — | — |
| 20261004-211118 | knowledge | k_nolead | 2000 | 50.2% | 50.2% ± 1.8% | — | — | — |
| 20261004-211234 | knowledge | k_randlead | 2000 | 49.9% | 49.9% ± 1.8% | — | — | — |
| 20261004-211346 | knowledge | k_uniformlead | 2000 | 50.3% | 50.3% ± 1.7% | — | — | — |
| 20261004-211459 | knowledge | k_none | 2000 | 52.0% | 52.0% ± 2.0% | — | — | — |
| 20261004-211545 | knowledge | k_nobelief | 2000 | 50.2% | 50.2% ± 1.8% | — | — | heldout |
| 20261004-211644 | knowledge | heuristic | 2000 | 65.8% | 65.8% ± 2.0% | — | — | heldout |
| 20261004-211920 | knowledge | knowledge_twin | 40 | 45.0% | 45.0% ± 9.8% | — | — | — |
| 20261004-213508 | k_llmplan | knowledge | 20 | 60.0% | 60.0% ± 13.1% | — | — | — |
| 20261004-213528 | k_llmplan | heuristic | 20 | 75.0% | 75.0% ± 16.3% | — | — | — |
| 20261004-213809 | k_llmplan | knowledge | 20 | 70.0% | 70.0% ± 16.0% | — | — | — |
| 20261004-213829 | k_llmplan | heuristic | 20 | 85.0% | 85.0% ± 15.0% | — | — | — |
| 20261005-121440 | k_llmplan | knowledge | 20 | 70.0% | 70.0% ± 21.7% | — | — | — |
| 20261005-121443 | k_llmplan | heuristic | 20 | 65.0% | 65.0% ± 15.0% | — | — | — |
| 20261005-121541 | k_llmplan | knowledge | 20 | 80.0% | 80.0% ± 16.0% | — | — | — |
| 20261005-121544 | k_llmplan | heuristic | 20 | 90.0% | 90.0% ± 13.1% | — | — | — |
| 20261005-121857 | k_llmplan | knowledge | 20 | 65.0% | 65.0% ± 25.5% | — | — | — |
| 20261005-121859 | k_llmplan | heuristic | 20 | 75.0% | 75.0% ± 16.3% | — | — | — |
| 20261005-122018 | k_llmplan | knowledge | 20 | 75.0% | 75.0% ± 16.3% | — | — | — |
| 20261005-122230 | k_llmplan | heuristic | 20 | 70.0% | 70.0% ± 16.0% | — | — | — |
| 20261005-122322 | k_llmplan | knowledge | 20 | 55.0% | 55.0% ± 22.9% | — | — | — |
| 20261005-122325 | k_llmplan | heuristic | 20 | 65.0% | 65.0% ± 15.0% | — | — | — |
| 20261005-123412 | k_llmplan | knowledge | 20 | 45.0% | 45.0% ± 27.1% | — | — | — |
| 20261005-123440 | k_llmplan | heuristic | 20 | 75.0% | 75.0% ± 21.9% | — | — | — |
| 20261005-123526 | k_llmplan | knowledge | 20 | 40.0% | 40.0% ± 13.1% | — | — | — |
| 20261005-123529 | k_llmplan | heuristic | 20 | 85.0% | 85.0% ± 15.0% | — | — | — |
| 20261005-123530 | k_llmplan | knowledge | 20 | 55.0% | 55.0% ± 17.6% | — | — | — |
| 20261005-123554 | k_llmplan | heuristic | 20 | 60.0% | 60.0% ± 19.6% | — | — | — |
| 20261005-123621 | k_llmplan | knowledge | 20 | 50.0% | 50.0% ± 25.3% | — | — | — |
| 20261005-123624 | k_llmplan | heuristic | 20 | 65.0% | 65.0% ± 15.0% | — | — | — |
| 20261005-123625 | k_llmplan | knowledge | 20 | 55.0% | 55.0% ± 22.9% | — | — | — |
| 20261005-123628 | k_llmplan | heuristic | 20 | 75.0% | 75.0% ± 16.3% | — | — | — |
| 20261005-123741 | k_llmplan | knowledge | 200 | 53.0% | 53.0% ± 6.2% | — | — | — |
| 20261005-123928 | k_llmplan | knowledge | 200 | 49.5% | 49.5% ± 6.8% | — | — | — |
| 20261005-124203 | k_llmplan | k_noplan | 200 | 54.5% | 54.5% ± 5.9% | — | — | — |
| 20261005-124210 | knowledge | k_noplan | 200 | 55.5% | 55.5% ± 6.0% | — | — | — |
| 20261005-124217 | k_llmplan | k_noplan | 200 | 63.5% | 63.5% ± 6.4% | — | — | — |
| 20261005-124223 | knowledge | k_noplan | 200 | 52.0% | 52.0% ± 7.1% | — | — | — |
| 20261005-125304 | k_llmplan | foulplay1000x4 | 20 | 5.0% | 5.0% ± 9.8% | — | — | — |
| 20261005-133025 | k_llmplan | foulplay1000x4 | 20 | 10.0% | 10.0% ± 13.1% | — | — | — |
| 20261005-140209 | k_llmplan | foulplay1000x4 | 20 | 10.0% | 10.0% ± 13.1% | — | — | — |
| 20261005-141714 | k_llmplan | foulplay1000x4 | 20 | 20.0% | 20.0% ± 16.0% | — | — | — |
| 20261005-143134 | k_llmplan | foulplay1000x4 | 20 | 10.0% | 10.0% ± 13.1% | — | — | — |
| 20261005-144804 | k_llmplan | foulplay1000x4 | 20 | 10.0% | 10.0% ± 13.1% | — | — | — |
| 20261005-163405 | k_llmplan | foulplay100x1 | 20 | 20.0% | 20.0% ± 16.0% | — | — | — |
| 20261005-163550 | k_llmplan | foulplay30x1 | 40 | 27.5% | 27.5% ± 13.2% | — | — | — |
| 20261005-163825 | k_llmplan | foulplay10x1 | 40 | 42.5% | 42.5% ± 19.2% | — | — | — |
| 20261005-164430 | k_llmplan | k_llmplan | 40 | 77.5% | 77.5% ± 11.2% | — | — | — |
| 20261005-164515 | k_llmplan | k_llmplan | 40 | 70.0% | 70.0% ± 11.0% | — | — | — |
| 20261005-165253 | s_llmplan | foulplay10x1 | 40 | 65.0% | 65.0% ± 12.5% | — | — | — |
| 20261005-170107 | s_llmplan | foulplay1000x4 | 20 | 15.0% | 15.0% ± 15.0% | — | — | — |
| 20261005-194605 | s_llmplan | s_computed | 187 | 47.1% | 47.3% ± 6.6% | — | — | — |
| 20261005-204712 | s_llmplan_prior | s_llmplan | 175 | 47.1% | 46.8% ± 7.3% | — | — | — |
| 20261005-224954 | s_oracle | s_llmplan | 186 | 61.8% | 61.8% ± 6.4% | — | — | — |
| 20261005-235652 | s_c_oracle | s_computed | 300 | 58.3% | 58.3% ± 5.5% | — | — | — |
| 20261006-003447 | s_c_oracle_item | s_computed | 300 | 51.3% | 51.3% ± 5.2% | — | — | — |
| 20261006-011520 | s_c_oracle_moves | s_computed | 300 | 57.5% | 57.5% ± 5.1% | — | — | — |
| 20261006-015815 | s_c_oracle_tera | s_computed | 300 | 49.8% | 49.8% ± 5.2% | — | — | — |
| 20261006-023316 | s_c_oracle_spread | s_computed | 300 | 53.2% | 53.2% ± 5.1% | — | — | — |
| 20261006-032703 | s_c_k1 | s_computed | 300 | 44.2% | 44.2% ± 5.1% | — | — | — |
| 20261006-041054 | s_c_k2 | s_computed | 300 | 45.0% | 45.0% ± 5.1% | — | — | — |
| 20261006-044521 | s_c_k8 | s_computed | 300 | 49.8% | 49.8% ± 5.1% | — | — | — |
| 20261006-053030 | s_c_k16 | s_computed | 300 | 45.0% | 45.0% ± 5.5% | — | — | — |
| 20261006-081125 | s_c_tm2 | s_computed | 300 | 52.2% | 52.2% ± 5.1% | — | — | heldout |
| 20261006-090010 | s_c_tm1 | s_computed | 300 | 53.7% | 53.7% ± 5.3% | — | — | heldout |
| 20261006-093824 | s_c_tm3 | s_computed | 300 | 47.7% | 47.7% ± 5.7% | — | — | heldout |
| 20261006-104913 | s_ismcts | s_computed | 300 | 57.3% | 57.3% ± 5.3% | — | — | heldout |
| 20261006-112342 | s_ismcts_n1 | s_c_k1 | 300 | 50.7% | 50.7% ± 5.4% | — | — | heldout |
| 20261006-115945 | s_ismcts_cl2 | s_ismcts | 300 | 48.2% | 48.2% ± 5.1% | — | — | heldout |
| 20261006-124344 | s_ismcts | s_computed | 300 | 48.3% | 48.3% ± 5.4% | — | — | heldout |
| 20261006-125636 | s_ismcts | s_computed | 46 | 37.0% | 36.4% ± 13.2% | — | — | heldout |
| 20261006-133235 | s_computed | s_computed | 200 | 58.5% | 58.5% ± 6.2% | — | — | — |
| 20261006-161739 | s_ismcts_pv | s_ismcts | 300 | 66.3% | 66.3% ± 5.2% | — | — | heldout |
| 20261006-164718 | s_ismcts_net | s_ismcts | 300 | 37.0% | 37.0% ± 5.3% | — | — | heldout |
| 20261006-171513 | s_ismcts_pv | s_ismcts_net | 300 | 73.0% | 73.0% ± 5.0% | — | — | heldout |
| 20261006-174744 | s_ismcts_pv | s_ismcts_p | 300 | 56.7% | 56.7% ± 5.3% | — | — | heldout |

<!-- END GENERATED -->
