# Team data

Tracked, curated team data; everything generated goes to `data/derived/teams/` (git-ignored).
A pool by name: `alpha_poke.paths.pool(name)` looks here first, then in the generated pools.

| file / pool | what | used by |
|---|---|---|
| `catalog.jsonl` | 1,176 complete, legal Gen 9 OU teams from the Smogon forum (sample teams, teams of the week, the tournament bazaar, Rate My Team), deduplicated; each with its sources (thread, post, paste; no poster names) | `scripts/teams.py build`; self-play's catalog sides, team design |
| `pools/ladder_robust` | 5 teams for games against people: team design's stage 2 (`doc/team_design.md`) | `play_public.py`, `ladder.py` |
| `pools/wide200` | 200 team pairs from real games, sampled like self-play's (seed 9001) | `eval_pairs.py` (default), Foul Play evaluations |
| `pools/ab600b` | 600 more pairs (wide1000's pairs 600-999 + wide200's): an A/B test's second batch when the first is inconclusive | `eval_pairs.py --pool` |
| `pools/replay40`, `pools/replay40b` | 40 teams each, widely copied ladder teams reconstructed from replays (frozen 2026-10) | the belief's held-out evaluation pool (`teams.DEFAULT_POOL`), early evaluations |
| `pools/forum_curated` | the 162 legal, complete teams of the council-picked forum sources | evaluations, team design |

A pool is a directory of Showdown-export team files (`team_*.txt`, or `pair<k>_a.txt` /
`pair<k>_b.txt` for fixed pairs) with `meta.json` (how it was made) and, for team pools,
`index.json` (file -> species).
