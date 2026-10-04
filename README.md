# alpha-poke

Machine learning / reinforcement learning agents for competitive Pokémon battles, built on
[poke-env](https://github.com/hsahovic/poke-env). Goal: an agent that approaches or surpasses
human pro-level play. Everything is trained and evaluated locally against a Pokémon Showdown server.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Node.js (for the local Showdown server).

```bash
uv sync                          # install Python deps
./scripts/start_showdown.sh      # clone + start local Showdown on :8000 (first run installs it)
uv run pytest                    # tests
uv run python scripts/baseline_match.py --n 50      # baseline round-robin (local server only)
uv run python scripts/bench_poke_env.py --battles 100 --concurrency 10   # throughput benchmark
```

## Layout

```
src/alpha_poke/
  agents/     battle agents (baselines, learned policies, search)
  envs/       observation / action / reward wrappers over poke-env
  training/   training algorithms and loops
  eval/       win-rate benchmarks, Elo / ladder tracking
configs/      experiment configs; configs/teams/ = human-built Gen9 OU team pool
scripts/      helper scripts (local Showdown server, ...)
tests/
```

## Notes

- Everything connects to a **local** Showdown server only (`alpha_poke.servers.local_server` refuses non-loopback hosts). The public ladder is intentionally off-limits for now.
- Design, research notes and baseline deep-dives are in `doc/`.
