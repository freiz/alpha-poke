# Evaluation: bots, team pools, Foul Play

How we compare two players, and how to run the comparisons. Results: [results.md](results.md).

## Paired evaluation

A match is a list of team pairs; each pair is played twice with the teams exchanged, so a pair's
score (0, ½ or 1) does not depend on which team is stronger. Scores are reported as the mean over
pairs ± a 95% confidence interval. Comparisons between two of our networks use a fixed number of
search iterations per decision (the machine's load does not change them); comparisons with Foul
Play use equal time per decision.

```bash
ALPHA_MODEL_A=<run A> ALPHA_MODEL_B=<run B> uv run python scripts/eval_pairs.py g_ma g_mb \
    --pool data/derived/teams/pools/fair1000 --pairs 300
```

## Team pools

Where the pairs come from matters: our first promotion test drew its teams the way self-play
does, and it overstated a self-play network's gain by about half.

| pool | what | built by |
|---|---|---|
| `teambank10k` | 10,000 real ladder teams (games after the training cutoff, both players ≥ 1500, a test half of the games by id); each test draws its own pairs: same month, ratings within 200, every team once. Promotion's default | `scripts/fair_pool.py --bank 10000` |
| `fair1000` | 1,000 fixed pairs, each the two teams of one real game (same filters); the reference for comparing generations on identical teams | `scripts/fair_pool.py --pairs 1000` |
| `wide200`, `wide1000` | real-game pairs drawn the way self-play draws its teams (hidden sets completed by the belief) | `scripts/selfplay.py` |
| `offmeta200`, `random200` | diagnostics: off-meta real games, random teams | `scripts/team_pools.py` |

In the fair pools a side's set keeps what its game revealed; the rest is drawn from Smogon's
usage, weighted by one minus how often that part shows in a game (Leftovers almost always shows,
Heavy-Duty Boots rarely), so an unrevealed item is more likely Boots than Leftovers. They are
never drawn from the search's own belief, so the opponents are not what the networks expect.
Self-play never draws teams from these games. Code: `alpha_poke.selfplay.fair`.

## Bots

`src/alpha_poke/eval/bots.py`; the networks come from `ALPHA_MODEL_A` / `ALPHA_MODEL_B` (default:
the released one).

| bot | what |
|---|---|
| `s_ismcts_ma` / `_mb` | CPU search (32 belief worlds), `ALPHA_SEARCH_MS` per decision, `ALPHA_SEARCH_THREADS` threads |
| `g_ma` / `g_mb` | the same search, many games batched on the GPU, `ALPHA_SEARCH_ITERATIONS` per decision |
| `p_ma` / `p_mb` | the network's policy alone, no search |
| `knowledge` | a rule-based player (also the search's fallback) |
| `heuristic`, `random`, `maxpower` | poke-env's baseline players |

A run directory holding a `hybrid.json` (`agents.gpu_net.make_hybrid`) takes the policy of one
network and the value of another: the head-swap experiments (GPU bots only).

## Against Foul Play

[Foul Play](https://github.com/pmariglia/foul-play) (GPL-3.0) is installed into `external/` and
run as a separate process, never imported:

```bash
uv run python scripts/setup_foul_play.py install && uv run python scripts/setup_foul_play.py patch
uv run python scripts/fetch_smogon_stats.py --months 1   # Foul Play's set data: last month's stats
uv run python scripts/setup_foul_play.py cache
uv run python scripts/vs_foulplay.py s_ismcts_ma --pairs 20 --lanes 2 --search-ms 200 --parallelism 2
```

## Playing against people

`scripts/play_public.py --opponent <name>` accepts challenges from one named user only; without
`--public` it stays on the local server. Difficulties: `easy` (the rule-based player), `normal`
(200 ms per move), `hard` (1 s × 4 threads); `--search-ms` / `--threads` set your own. Its team is
one of `teams/pools/ladder_robust` ([team_design.md](team_design.md)) unless `--team` is given.
On the official server it needs `--public` and a registered bot account (Showdown's bot policy).
