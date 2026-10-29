# alpha-poke

A Gen 9 OU (Pokémon Showdown singles) agent: information-set MCTS over belief-sampled worlds on a
patched poke-engine, a transformer policy / value network trained on ~2M human games, then
self-play. Showdown's simulator is the reference for every rule; a differential-test framework
keeps the engine and our state construction honest against it.

Design: `doc/design.md` · results ledger: `doc/results.md` · differential tests: `doc/difftest.md`,
`doc/engine-diff.md`, `doc/state-diff.md` · teams for human games: `doc/team_design.md` · research
notes: `doc/research.md`, `doc/research_foul_play.md`.

## Setup

Requires [uv](https://docs.astral.sh/uv/), Node.js (local Showdown) and a Rust toolchain (the
engine and the search, `rust/`).

```bash
uv sync --all-groups             # all groups: a plain `uv sync` removes torch (the train group)
./scripts/start_showdown.sh 8000 # local Showdown server (also 8001-8003 for parallel games)
uv run pytest -n 8               # tests: 8 workers, ~1.5 min (one process: ~7 min)
```

## Layout

```
src/alpha_poke/
  agents/      search player, belief, state construction for the engine, GPU network, damage model
  belief/      set priors and the move-reveal model
  analysis/    replay tables (games_lite), matchup model, roles
  replay/      replay parser, fetcher and crawler
  train/       network, training positions
  selfplay/    self-play: teams, runner, batched GPU search, conversion, registry
  eval/        arena (paired evaluation), bots, Foul Play / split-checkout evaluations
  enginecheck/ engine / state-construction differentials against Showdown
  teams/       team catalog (forum), pools, validator
  players/     models of one specific opponent
rust/          alpha_search (ISMCTS, batched search, features) + patched poke-engine
scripts/       entry points (below)
tests/         unit tests, incl. the dual Showdown / engine tests
doc/           design, results, differential-test logs, team design, research
```

Entry points: `scripts/selfplay.py` (teams, run, convert, train, eval, iterate), `scripts/train_pv.py`,
`scripts/build_training_data.py`, `scripts/difftest.py`, `scripts/eval_pairs.py`,
`scripts/vs_foulplay.py`, `scripts/play_public.py` / `scripts/ladder.py` (official server, `--public`
only), the team-design pipeline in `doc/team_design.md`.

## Data (all under `data/`, git-ignored; never commit replays: real usernames)

| source | how | notes |
|---|---|---|
| Metamon's Gen 9 OU replays (to 2026-05) + the HolidayOugi HF dump (to 2026-10) | `scripts/fetch_metamon.py` | ~2.3M games; `analysis/games_lite` scans them into `data/parsed/gen9ou_games_lite.parquet` |
| Showdown replays (newest) | `scripts/crawl_replays.py list --mode new` then `download --min-rating 1500` | `data/replays/` (SQLite index + json.gz) |
| Smogon usage statistics | `scripts/fetch_smogon_stats.py` | monthly chaos JSON; ids, not display names |
| Smogon forum teams | `scripts/teams.py` | `data/teams/catalog.jsonl` (complete teams), pools |

Crawling etiquette (`alpha_poke.http.PoliteClient`, every fetch): one connection, ~2 s between
requests (+ jitter), `Retry-After` honored, exponential backoff on 429 / 5xx, abort on 403 or 5
failures in a row, a User-Agent stating the purpose and no personal contact, resumable state.
Measured Showdown endpoints: `replay.pokemonshowdown.com/search.json?format=gen9ou` pages of 51,
newest first (`before=<uploadtime>`); with `user=` only the latest 25; `<id>.json` the full log;
`pokemonshowdown.com/ladder/gen9ou.json` the top 500. Only saved replays exist (a selection), and
the ladder has bots among the players.

## Rules of the house

- Evaluation and self-play run on **local** Showdown servers only (`servers.local_server` refuses
  non-loopback hosts); the official server only with `--public` and the registered bot account
  (PS bot policy, 2026-10: an unregistered bot is bannable).
- Showdown is the reference: an engine or state issue is confirmed by a Showdown test and an engine
  test that agree before it is fixed (`tests/test_dual_engine.py`).
