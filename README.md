# alpha-poke

Machine learning / reinforcement learning agents for competitive Pokémon battles, built on
[poke-env](https://github.com/hsahovic/poke-env). Goal: an agent that approaches or surpasses
human pro-level play. Everything is trained and evaluated locally against a Pokémon Showdown server.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Node.js (for the local Showdown server).

```bash
uv sync                          # install Python deps
./scripts/start_showdown.sh      # clone + start local Showdown on :8000 (first run installs it)
uv run pytest                    # smoke tests
```

## Layout

```
src/alpha_poke/
  agents/     battle agents (baselines, learned policies, search)
  envs/       observation / action / reward wrappers over poke-env
  training/   training algorithms and loops
  eval/       win-rate benchmarks, Elo / ladder tracking
configs/      experiment configs
scripts/      helper scripts (local Showdown server, ...)
tests/
```
