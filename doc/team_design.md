# Team design for the ladder / friendly-game bot

What the bot brings when it plays humans (scripts/ladder.py, scripts/play_public.py). Started
2026-10-27/28. Self-play's own team sampling (synthetic teams, D16) is a different problem: it wants
variety; this wants teams that win *in our bot's hands* against the *current* ladder.

## Update procedure (re-run when the metagame moves; every few weeks)

```bash
# 1. fresh replays (polite: 2 s between requests; ~1.5 h listing + up to a few hours download)
uv run python scripts/crawl_replays.py --max-hours 1.5 list --mode new --pages 2000
uv run python scripts/crawl_replays.py --max-hours 5 download --target <done + N> --min-rating 1500 --since-days 25
# 2. how the metagame moved (and the crawler's sample checked against the lite scan)
uv run python scripts/meta_shift.py --recent 21
# 3. stage 1: candidates scored against the recent metagame -> data/derived/teams/pools/robust_candidates
uv run python scripts/build_robust_teams.py --score-pool data/derived/teams/pools/<current pool>
# 4. threat coverage and role slots of the candidates (threats: the recent metagame's top 15)
uv run python scripts/threat_check.py data/derived/teams/pools/robust_candidates
# 5. stage 2 (GPU, not with self-play): our bot plays each candidate against 100 recent ladder teams
uv run python scripts/sim_team_pool.py --candidates data/derived/teams/pools/robust_candidates --keep 5
# 6. scripts/ladder.py / play_public.py --pool data/derived/teams/pools/<the kept pool>
```

Sets that only replays show (no forum original) are reconstructed; their accuracy:
`scripts/check_team_reconstruction.py` (cross-validation against the forum's own teams).

## Scripts

| script | what |
|---|---|
| `crawl_replays.py` | the replay crawler (data/raw/replays/gen9ou/*.json.gz; index.sqlite) |
| `meta_shift.py` | species usage, recent vs before; the crawler's sampling bias check |
| `top_ladder_teams.py` | compositions by time-weighted ladder win rate (players >= 1600, >= 5 players); set reconstruction from replays (`reconstruct`, `forum_spread`, `fit_spread`, `trick_item`) |
| `check_team_reconstruction.py` | the reconstruction cross-validated against complete forum teams |
| `build_robust_teams.py` | stage 1: matchup model + recent metagame -> mean / CVaR / worst threat; forum + ladder candidates |
| `threat_check.py` | answers (check / revenge) to the top threats across their main builds; role slots |
| `sim_team_pool.py` | stage 2: our bot's results with each candidate against recent ladder teams |
| `ladder.py`, `play_public.py` | play on the official server (registered bot account; --public) |

## Findings (2026-10-28)

- **A team's ladder win rate is mostly its players'.** The stall team with the best ladder record
  (Blissey / Clodsire / Corviknight / Dondozo / Gliscor / Toxapex, 66.5%, 49 players >= 1600) scores
  46% expected against the current metagame on the matchup model once ratings are factored out
  (Elo-adjusted margin only +6%). Rank by expected score against the metagame, not by win rate;
  require several distinct players when using win rates at all (`--min-players 5`).
- **The matchup model is weak but usable as a filter.** Species strength + species-vs-species on
  1.14M games: validation log loss 0.680 vs 0.690 with ratings only, 0.693 constant. Teams matter
  little per game; use it to rank, decide with simulations.
- **The metagame moved in October 2026** (last 21 days vs the 30 before; the crawler's sample matched
  the lite scan within 0.5 points on the same days): Zamazenta 17.6 -> 28.8%, Ogerpon-Wellspring
  17 -> 28%, Gholdengo 21.5 -> 30.4%, Dragonite 14.7 -> 24%, Iron Treads 11.4 -> 20.3%, Ceruledge
  7 -> 13%; Slowking-Galar 16.6 -> 10.4%, Cinderace 15.5 -> 10%, Rillaboom 11 -> 6%, Landorus-T,
  Corviknight down. Iron Valiant 14.5 -> 16.9% (9th). Use the recent window (21 days, half-life 14)
  for the metagame, the threats and the simulated opponents.
- **Reconstructing sets from replays** (60 forum teams the ladder played >= 30 times, 360 sets):
  item 95.6%, ability 98.9%, tera 84.2%, moves 96.3% (Smogon's most common: 56.7 / 96.7 / 40.8 /
  68.9%). Natures / EVs are never shown: borrowing the forum's closest set (same species and item,
  >= 2 moves shared) gives nature 75% (vs 67%), EV L1 0.158 (vs 0.224). Pitfalls fixed: moves of
  different variants mixed (one variant per species: its most common item's games); a Trick user's
  replay item is the opponent's (give it a choice item); attacking spreads only for clearly
  offensive sets (Jolly / Timid raise Speed, not Attack).
- **Threat coverage needs the threats' several builds and counts of answers.** "At least one answer
  to each threat" passed the team that lost the first friendly game; against each threat's main
  builds (belief archetypes >= 15%) it had 2 threats unanswered and 5 with a single answer -- and in
  that game the single answer (Zapdos) was worn down. Count none / one; a special build of Iron
  Valiant (Aura Sphere) beats the Iron Treads that "checks" the physical one.
- **How humans build** (Smogon practice): a core / win condition, a threat list of the metagame's
  common Pokemon, defensive synergy, the role slots (hazards, removal, speed control, pivoting),
  no auto-losses to the common archetypes (rain, sun, stall, hyper offense), then ladder testing.
  The working hypothesis (the user's): a high expected score while avoiding bad matchups beats
  picking counters. Tested in stage 2 (below): threat coverage (no unanswered threats) predicts
  the bot's results somewhat; the matchup model's CVaR does not.

## Stage 2's validation (2026-10-28)

17 teams (stage 1's 12 finalists + the earlier win-rate top 5), each against the same 100 teams of
the last 21 days' ladder (players >= 1500, sets completed by the belief), our network on both
sides (1,600 iterations), each pair twice with the bots exchanged: 3,400 games, 35 failed (34 of
them the stall team's games over the 20-minute cap). The bot's scores 49-75% (about +-7% each:
the opponents' completed sets are weaker than real ones, so only the ranking means anything):
the stall team 75% (but its long games time out, and bots may handle stall worse than people),
the earlier top 5's Darkrai / Garganacl / Iron Treads / Moltres / Ogerpon-W / Zamazenta and
Dragonite / Gholdengo / Glimmora / Ogerpon-W / Ting-Lu / Zamazenta 71%, the forum's Alomomola /
Great Tusk / Iron Crown / Sinistcha / Ting-Lu / Zamazenta 70.5%; stage 1's first 67.5%, its
seventh 49%. Which measure predicts the bot's score (Spearman over the 17): threats with no
answer -0.34 (the right direction, the most useful), only one answer -0.10, role slots 0.00, the
matchup model's expected score -0.23 and CVaR -0.22 (the wrong direction). Per simulated pair
the matchup model's prediction correlates +0.06 with the result (log loss 0.679 vs 0.693): a
model of people's ladder results says little about the teams in our bot's hands -- stage 2 is
the decision, stage 1 only a candidate list; threat coverage is a cheap filter worth keeping.
(`scripts/validate_team_measures.py`; the log data/eval/teamsim/20261028-172553_g_ma_vs_g_mb.jsonl.)

**The pool in use** (`data/derived/teams/pools/ladder_robust`, the default of `ladder.py` and
`play_public.py`; 2026-10-28): stage 2's top 5 with the stall team replaced by the sixth --
Darkrai / Garganacl / Iron Treads / Moltres / Ogerpon-W / Zamazenta; Dragonite / Gholdengo /
Glimmora / Ogerpon-W / Ting-Lu / Zamazenta; Alomomola / Great Tusk / Iron Crown / Sinistcha /
Ting-Lu / Zamazenta; Dragonite / Iron Treads / Kyurem / Pecharunt / Samurott-H / Zamazenta; Iron
Treads / Ogerpon / Okidogi / Pecharunt / Raging Bolt / Ting-Lu.

## The first friendly game (2026-10-28, r2-gen0a2, 3 s x 4 threads, team ladder_top5/team_04)

Lost in 49 turns to a 1300 player's Blaziken / Alomomola / Ting-Lu / Corviknight / Ogerpon-W /
Iron Valiant. The bot's errors: its +2 Ogerpon stayed in against Speed Boost Blaziken (Protect,
then +1 Speed, Tera Fighting Close Combat) instead of switching to Zapdos; Zamazenta terastallized
to Fire (Stealth Rock 2x, Ground weak); four Body Presses into Alomomola's Protect; a 40% Zapdos
stayed in against a faster Iron Valiant; a 40% Tera-Fire Zamazenta switched into Stealth Rock and
Aura Sphere. Two of them misjudged the opponent's Speed (to check: the belief's speed spreads).
The team had nothing reliable against Iron Valiant late. Replay and traces:
data/public_games/20261028/.
