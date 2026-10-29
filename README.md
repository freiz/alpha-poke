# alpha-poke

An AI for Pokémon Showdown's Gen 9 OU singles. It plays with information-set Monte Carlo
tree search (ISMCTS) over worlds sampled from a belief about the opponent's hidden sets. The
search runs on a patched [poke-engine](https://github.com/pmariglia/poke-engine) and is guided by
a small transformer policy / value network. The network was trained on about 2.3M human games
and is now being improved by self-play. Showdown's own simulator is the reference for every
rule: a differential-test framework checks the engine and our state reconstruction against it.

Status: a research project, run on one desktop (20 CPU threads, an RTX 4070 Ti). The released
network (human data only) beats [Foul Play](https://github.com/pmariglia/foul-play), the
strongest open-source Showdown bot we know of, 65–67% at equal time per move. Public ladder
results against people are not in yet.

## Contents

- [How it works](#how-it-works)
- [Results](#results)
- [Quick start: play and evaluate the released model](#quick-start)
- [Training from scratch](#training-from-scratch)
- [Self-play](#self-play)
- [Team design](#team-design)
- [Engine correctness](#engine-correctness)
- [Repository layout](#repository-layout), [Tests](#tests), [Data and licenses](#data-and-licenses),
  [Playing on the official server](#playing-on-the-official-server)

## How it works

Gen 9 OU is a two-player zero-sum game with simultaneous moves and hidden information. At team
preview each player sees only the opponent's six species. Moves, items, abilities and tera
types come out during the game, and EVs and natures never do. A turn is roughly a 9 × 9
matrix game with plenty of chance (damage rolls, accuracy, secondary effects, crits).

```
Showdown battle (poke-env: protocol, battle tracking)
  │
  ├─ belief: 32 worlds = the opponent's sets sampled from team-conditioned priors,
  │          updated by what has been revealed, the speed order seen and the damage seen
  ├─ state construction: each world as an exact poke-engine state (timers, PP, volatiles, ...)
  ▼
alpha_search (Rust)
  SO-ISMCTS: one tree over our information set, a different world each iteration
  decoupled PUCT for both sides; priors from the policy network (the opponent's from the
  flipped view), leaves valued by the network
  │
  ▼
the most visited action (any failure: a rule-based fallback player)
```

- **Belief** (`agents/belief_state.py`, `belief/`): set priors conditioned on the whole team.
  They back off from a recognized copied team, to a common core, to species usage. Moves come
  from set archetypes. In battle the belief is updated with revealed moves and items, a model
  of how likely a move would have been shown by now (`belief/reveal.py`), speed tiers
  consistent with the observed move order, and damage-roll evidence.
- **State construction** (`agents/engine_state.py`, `agents/timers.py`): every world becomes a
  full engine state, including sleep and toxic counters, Protect streaks, Wish / Future Sight,
  PP, choice locks and transformed Pokémon. A consistency check against Showdown's request runs
  before every search.
- **Search** (`rust/alpha_search`): single-observer ISMCTS with open-loop chance. Each node is
  keyed by (our action, opponent action). Both sides pick by decoupled PUCT with
  availability-normalized counts. Moves applied along the path are recorded with their real
  outcome (moved, fainted first, blocked) and become the network's history input. On the GPU
  many games' searches share batched inference (tree parallelism with virtual loss); on the
  CPU, root parallelism.
- **Network** (`train/model.py`, Rust inference in `tnet.rs`): about 742k parameters. Its
  input is 12 Pokémon tokens, a global token and 8 history tokens. It has 3 transformer
  layers, d = 128, SwiGLU, RMSNorm and QK-norm. Inputs include matchup calculations made with
  the engine's own damage code: damage ratios, KO thresholds, who moves first. The policy has
  14 action slots and the value is a win probability (a residual over the engine's handcrafted
  evaluation). Auxiliary heads predict the next 3 actions, the opponent's sets and the
  remaining turns. Training and search share one featurizer.
- **Training**: behavior cloning plus game outcomes on human replays. Self-play is expert
  iteration: the search's visit counts are the policy targets and game results the value
  targets. A new network is promoted only when a sequential test says it is clearly better.

The design document (`doc/design.md`, in Chinese) has the decisions and their evidence. Every
number is in `doc/results.md`, and open problems are GitHub issues.

## Results

Paired evaluation: each pair of real-game teams is played twice, with the teams exchanged.
Results are win rates ± 95% CI.

| | result |
|---|---|
| vs Foul Play, 200 ms × 1 thread each per decision (199 pairs) | **65.0% ± 4.1%** |
| vs Foul Play, 5 s × 2 threads each (108 pairs) | **67.1% ± 6.3%** |
| network in the search vs the handcrafted evaluation (500 ms) | 66.3% ± 5.2% (+117 Elo) |
| ISMCTS vs determinized search with the same budget | 57.3% |
| knowing the opponent's true sets (an oracle) | about +8–12 points, nearly all from the moves |
| network, human validation positions | policy top-1 55.9%, value accuracy 71.7% |

Self-play (line r2, from the released network): attempts at 53k and 78k games scored 50.2% ±
3.7% and 52.5% ± 2.1% against their start. Neither cleared the "confidently above 51%"
promotion bar, so self-play continues on the same generation.

## Quick start

Requirements: Linux or WSL2 (developed on WSL2 Ubuntu), [uv](https://docs.astral.sh/uv/),
Node.js ≥ 22.18 (the local Showdown server), a Rust toolchain (the search is built on install),
git. A CUDA GPU is optional: the CPU search is what plays people and Foul Play, while
self-play and the large evaluations batch on the GPU.

```bash
git clone https://github.com/freiz/alpha-poke && cd alpha-poke
uv sync --all-groups                 # all groups: a plain `uv sync` removes torch (train group)
uv run python scripts/fetch_model.py # the released network + belief models (SHA-256 checked)
                                     # and one Smogon usage-statistics file
./scripts/start_showdown.sh 8000     # a local Showdown server (clones it at a pinned commit;
                                     # leave it running, another terminal for the rest)
```

**Watch it play** a few paired games against poke-env's heuristic bot, using CPU search, 200 ms
per move:

```bash
uv run python scripts/eval_pairs.py s_ismcts_ma heuristic --pairs 5 --procs 1 --lanes 2 \
    --ports 8000 --log-dir data/eval/quickstart
```

`s_ismcts_ma` is the search with the network `ALPHA_MODEL_A` (default: the released one).
`ALPHA_SEARCH_MS` and `ALPHA_SEARCH_THREADS` set its time per move. The other bots are listed
in `src/alpha_poke/eval/bots.py`: `g_ma` is the GPU-batched search by iterations, `p_ma` the
network's policy without search, `knowledge` a rule-based player.

**Play against it yourself**: open <http://localhost:8000>, pick a name (say `me`), then:

```bash
uv run python scripts/play_public.py --opponent me --n 3 --difficulty hard
```

Without `--public` this script connects to the local server as `alphapokebot` and accepts
challenges only from `--opponent`. Challenge it to Gen 9 OU with your own team. Its team is
a random one of `teams/pools/ladder_robust` (or `--team`). Difficulties: `easy` is the
rule-based player, `normal` searches 200 ms per move, `hard` 1 s × 4 threads; `--search-ms`
and `--threads` set your own.

**Against Foul Play** (GPL-3.0; installed into `external/` and run as a separate process,
never imported):

```bash
uv run python scripts/setup_foul_play.py install && uv run python scripts/setup_foul_play.py patch
uv run python scripts/setup_foul_play.py cache
uv run python scripts/vs_foulplay.py s_ismcts_ma --pairs 20 --lanes 2 --search-ms 200 --parallelism 2
```

## Training from scratch

Everything below writes under `data/` (git-ignored). The full pipeline needs about 100 GB of
disk and, for the large steps, 30+ GB of RAM. Run those steps under a memory cap
(`systemd-run --user --scope -p MemoryMax=30G ...`): an out-of-memory WSL takes the machine
down with it.

```bash
# 1. replays: Metamon's Gen 9 OU dataset (~2M games, 5.7 GB download, filtered to gen9ou)
uv run python scripts/fetch_metamon.py
#    newer games: the HolidayOugi dump (HF HolidayOugi/pokemon-showdown-replays), by hand for
#    now (#23), to data/raw/replays_hf/gen9ou/*.parquet with Metamon's columns (id, format,
#    players, log, uploadtime, formatid, rating); split big shards with scripts/split_shards.py
# 2. Smogon usage statistics (the belief's fallback and the speed tiers)
uv run python scripts/fetch_smogon_stats.py --months 3
# 3. our own recent replays (polite crawler: ~2 s between requests) and the replay tables
uv run python scripts/crawl_replays.py list --mode new --pages 2000
uv run python scripts/crawl_replays.py download --target 50000 --min-rating 1500
uv run python scripts/build_replay_tables.py
# 4. the belief and reveal models (built on first use; or explicitly)
uv run python scripts/build_reveal_model.py
uv run python -c "from alpha_poke.agents.belief_state import BeliefModel; BeliefModel.load(rebuild=True)"
# 5. training positions: 20 decision points per game, each rebuilt as the engine state the
#    player saw (~46M positions; resumable per shard)
uv run python scripts/build_training_data.py --name v75 --per-game 20 --pool all --heldout --workers 12
# 6. the network (the released recipe; ~2 h on an RTX 4070 Ti; features are cached on the first epoch)
uv run --group train python scripts/train_pv.py --data v75 --run v6arch-pp-v75 \
    --arch transformer --history --mtp 3 --feats reveal,num,movetab,matchup,elo,counter,count \
    --aux oppset,turns --d-ff 171 --ffn swiglu --norm rms --qk-norm --value-residual \
    --value-per-game 4 --epochs 6 --batch 4096 --lr 0.002 --warmup-frac 0.02 --stream 2 \
    --train-only hf- --val-cutoff 1776921722 --export best
```

The run directory (`data/train/v75/runs/<run>`) holds `best.safetensors` and `config.json`
(what the Rust inference loads), the checkpoints and `metrics.jsonl`. Compare two networks with
the search, not offline metrics alone. An input that improves the offline numbers can lose in
search (`doc/results.md` has an example):

```bash
ALPHA_MODEL_A=<run A> ALPHA_MODEL_B=<run B> uv run python scripts/eval_pairs.py g_ma g_mb
```

## Self-play

```bash
uv run python scripts/selfplay.py iterate --gen 0     # needs the GPU and the replay data
```

A generation's loop is: team pairs, then games (10 processes × 24 games, batched GPU search,
1,600-iteration full searches on 25% of the decisions as policy targets), then conversion,
then fine-tuning on all of the generation's games mixed with human data, then a sequential
test against the current network (H0 51%, H1 54%). Without a promotion, the loop plays 50k
more games and tries again. Half of the teams are synthetic: species drawn by usage and
teammate lift, sets refined by Metropolis–Hastings over a teammate-synergy score. The rest
are real teams with their hidden sets completed by the belief, plus forum teams. State and
history are kept in `data/selfplay/state.json`; the single steps (`teams`, `run`, `convert`,
`train`, `eval`) are subcommands. Design: `doc/design.md` D15–D16.

## Team design

For games against people the bot needs teams that win *in its hands* against the *current*
ladder. A team's ladder win rate is mostly its players' skill. `doc/team_design.md` has the
pipeline and its findings:

1. crawl recent replays, measure the metagame's shift (`meta_shift.py`);
2. candidates from forum teams and from teams reconstructed from replays (sets are recovered
   at 96% item / 96% move accuracy against the forum originals), scored against the recent
   metagame by a species matchup model (`build_robust_teams.py`);
3. threat coverage: how many answers each candidate has to every common threat's main builds
   (`threat_check.py`);
4. the decision: our bot plays each candidate against 100 recent ladder teams
   (`sim_team_pool.py`). The cheap measures only shortlist (threats with no answer:
   Spearman −0.34 against the simulated score; the matchup model: none).

The result is `teams/pools/ladder_robust`, the default pool of `play_public.py` and
`ladder.py`.

## Engine correctness

The search is only as good as its simulator. poke-engine 0.0.48 is vendored with our patches
(`rust/patches`, marked "alpha-poke patch"); the Python binding is built from the same source.
Every rule difference is confirmed by two tests that agree: a Showdown test and an engine test
(`tests/test_dual_engine.py`, run through a persistent Node process). Then the Showdown
mechanism is ported. `scripts/difftest.py` compares recorded battles turn by turn against
Showdown, for both the state we build and the engine's transitions, and fails on any
regression from the baseline. Logs: `doc/difftest.md`, `doc/engine-diff.md` (about 250
logged engine fixes), `doc/state-diff.md`.

## Repository layout

```
src/alpha_poke/
  agents/      search player, belief state, engine-state construction, GPU network, damage model
  belief/      set priors and the move-reveal model
  analysis/    replay tables, matchup model, roles
  replay/      replay parser, fetcher and crawler
  train/       network, training positions, loading
  selfplay/    teams (synthetic and real), runner, batched GPU search, conversion, registry
  eval/        arena (paired evaluation), bots, Foul Play
  enginecheck/ differential checks against Showdown
  teams/       forum team catalog, pools, validator
  players/     models of one specific opponent (public replays only)
  paths.py     where every piece of data lives
rust/          alpha_search (ISMCTS, batched search, featurizer, inference) + patched poke-engine
teams/         tracked team data: catalog.jsonl (forum teams), pools/<fixed pool>
scripts/       entry points (each one's docstring has its usage)
tests/         unit tests, including the dual Showdown / engine tests
doc/           design, results ledger, differential-test logs, team design, model card
```

`data/` is git-ignored (layout in `src/alpha_poke/paths.py`): `raw/` holds downloads
(replay datasets, crawled replays, Smogon statistics, the forum cache), `derived/` what
scripts rebuild from them (replay tables, belief models, generated pools), plus `train/`,
`selfplay/` and the run outputs (`eval/`, `difftest/`, `public_games/`, `ladder/`).

## Tests

```bash
uv run pytest -n 8          # ~1,500 tests, about 1 minute with 8 workers; needs Node and the
                            # Showdown checkout (scripts/start_showdown.sh clones it)
uv run ruff check <the files you changed>   # the whole tree still has old long lines (#22)
```

When changing the Rust inference or featurizer, also run `scripts/check_tnet.py` (Rust vs
PyTorch, layer by layer) and `scripts/check_extra.py`.

## Data and licenses

| source | how | notes |
|---|---|---|
| Metamon's Gen 9 OU replays (to 2026-05) | `scripts/fetch_metamon.py` | HF `jakegrigsby/metamon-raw-replays`; usernames pseudonymized |
| HolidayOugi replay dump (to 2026-10) | manual download for now (#23) | HF `HolidayOugi/pokemon-showdown-replays` |
| Showdown replays (newest) | `scripts/crawl_replays.py` | public replays of the official server |
| Smogon usage statistics | `scripts/fetch_smogon_stats.py` | smogon.com/stats |
| Smogon forum teams | `scripts/teams.py` | `teams/catalog.jsonl` (sets only) |

Neither replay dataset states a license. Raw replays (with real usernames) are used locally and
never redistributed: `data/` is not in the repository. The released weights are for
non-commercial research use (`doc/model_card.md`). Foul Play (GPL-3.0) is installed separately
and run as an external process; poke-engine is MIT (`rust/patches/*/LICENSE`).

Every fetch uses a polite client (`alpha_poke.http.PoliteClient`): one connection, about 2 s
between requests with jitter, `Retry-After` honored, exponential backoff on 429 / 5xx, and an
abort on 403 or after 5 failures in a row. Its User-Agent states the purpose with no personal
contact, and its state is resumable.

## Playing on the official server

Evaluation and self-play run on local servers only: `servers.local_server` refuses
non-loopback hosts. `play_public.py` (friendly games against one named user) and `ladder.py`
(rated games, one at a time) connect to play.pokemonshowdown.com only with `--public` and a bot
account in `.env` (`PS_BOT_USERNAME`, `PS_BOT_PASSWORD`). Showdown's bot policy requires the
account to be registered as a bot first: open a help ticket, choose "Something else", then "I
want to register my bot". An unregistered bot can be banned. The scripts never join rooms,
chat, or challenge anyone.
