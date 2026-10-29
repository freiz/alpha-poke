# alpha-poke design doc

| | |
|---|---|
| Status | **Current-state version** (consolidated 2026-10-28: only the current design and the conclusions that still hold; to-dos are tracked in GitHub issues, not here; finished experiments and superseded settings are in the git history) |
| Numbers | All training / evaluation numbers are in [`results.md`](results.md); this doc only cites the conclusions |
| Companion docs | [`research.md`](research.md) (survey, cited as `R§x.y`), [`research_foul_play.md`](research_foul_play.md), [`results.md`](results.md) (results ledger), [`difftest.md`](difftest.md) / [`engine-diff.md`](engine-diff.md) / [`state-diff.md`](state-diff.md) (differential testing), [`team_design.md`](team_design.md) (team selection for playing people) |

Decision ids follow the old version (code comments cite D5, D11–D17).

---

## 1. Goals and constraints

**Goal**: a strong battle AI for Gen9 OU singles, at or above human pro level; trained and evaluated locally (Python + uv + poke-env + a local Showdown; search and inference in our own Rust crate). Research direction: **hidden information built organically into the search** (D14).

**Non-goals**: an online policy that calls an LLM every turn (R§8.4); doubles / VGC; other generations. Team building is planned but not the current focus (D5).

**Constraints**
- Servers: evaluation and training use only the local Showdown (`alpha_poke.servers.local_server` allows only local addresses). There are only two exceptions, both requiring `--public` and the registered bot account (`.env`; PS's bot policy 2026-10: unregistered bots can be banned): `scripts/play_public.py` (accepts challenges only from whitelisted opponents) and `scripts/ladder.py` (ladder, one game at a time); neither joins rooms, sends messages or challenges anyone.
- Licenses: Foul Play is GPL-3.0 and is used only as an external-process opponent: not imported, no code copied; poke-engine (MIT) is vendored and patched (D17); replay data: the two HF datasets we use, Metamon raw-replays and HolidayOugi, carry no license (Metamon's parsed-replays is labeled CC-BY-NC-4.0); raw replays are used only for local research and not redistributed; the released weights are limited to non-commercial research (`model_card.md`).
- Secrets live in `.env`; never printed, never committed. The user's email appears in no request.
- Environment: `uv sync --all-groups` (a plain `uv sync` uninstalls torch).

## 2. Problem characteristics

Two-player zero-sum, **imperfect information** (the opponent's sets are hidden; team preview shows only the 6 species), **simultaneous moves** (each turn is roughly a 9×9 matrix game whose optimum is often a mixed strategy), lots of chance, a long horizon. Moves, items, abilities and tera come out gradually during the game; EVs / natures are never visible: the belief model of the opponent's sets, and "how to use it in the search", are the core problems.

## 3. Current system

```
poke-env (protocol, battle tracking) ──► SelfPlayPlayer / SearchPlayer (thin Python adapter)
                                 │ build_state: the belief model samples 32 opponent sets (D8), engine state (D17)
                                 ▼
                        alpha_search (Rust)
                        SO-ISMCTS: one tree, a different world each iteration, open-loop chance (D12)
                        PUCT: both sides' priors = the policy network (the opponent's from a flipped-view forward pass)
                        leaves: the value network (residual: a linear term of the handcrafted evaluation + the network)
                                 │ our root visit distribution
                                 ▼
                        the command; any failure → KnowledgePlayer's heuristic decision
Opening: KnowledgePlayer's rule-based plan only decides the lead
```

### Current configuration (2026-10-28)

- **Network**: `data/train/v75/runs/v6arch-pp-v75` (v6's 7 input groups, trained from scratch on the v7.5 human data: 2.34M games, 46.07M positions under the current state construction); the starting point and the current network of self-play line r2 (`current` in `data/selfplay/state.json`, registered in `exp/models.json`).
- **Self-play**: r2 generation 0 is extended step by step under "promote only when clearly better" (D15); two attempts, neither promoted (53k games 50.2%, 78k games 52.5% ± 2.1%); 104k games so far.
- **Engine state**: `build_state` (D17); poke-engine patches and Python bindings from the same source (`rust/patches`).
- **Search**: GPU batched ISMCTS (`selfplay.batcher`), 32 worlds, BF16 inference; evaluation plays the most visited action (`g_ma` / `g_mb`), 1,600 iterations; the CPU version `s_ismcts_ma` (against Foul Play and humans, time-based).
- **Strength reference**: against Foul Play, v75: 200 ms × 1 each (wide200) 65.0% ± 4.1%; 5 s × 2 each (wide1000, 108 pairs) 67.1% ± 6.3% -- more time for both sides leaves the relative edge unchanged. Against humans: one friendly game, lost (a player around 1300, `doc/team_design.md`); the ladder waits for the bot registration to be approved.

## 4. Design decisions

### D1. Target format
Gen9 OU singles: the largest player base, human level is meaningful, no public top-level RL agent.

### D2. Infrastructure
- **Battle environment**: poke-env + several local Showdown servers (started one after another: each start runs `node build`); training, self-play and evaluation share one path. Games run on Showdown; poke-engine is only an approximate model inside the search, not the ground truth.
- **Python / Rust split**: Rust (`rust/alpha_search`, pyo3 + maturin) does the computation repeated at every step (search, featurization, inference); Python does the protocol, battle tracking, belief sampling, training and evaluation. The interface is coarse-grained: one call per step, passing a state string and numpy buffers; a Rust panic becomes an exception on the Python side and falls back to the heuristic.
- After a Rust change `uv run` rebuilds automatically; when a running job depends on the compiled version, make the change in a worktree and merge after the job ends.

### D3. Algorithm
AlphaZero-style: information-set MCTS (D12) + a policy / value network (D13), expert-iteration self-play (D15). Human data first (behavior cloning + outcomes), then self-play. No alpha-beta (simultaneous moves, chance nodes, hidden information). No LLM in the decisions (D11).

### D4. Reuse vs build
The core stack is our own; Foul Play is an external evaluation opponent (`scripts/vs_foulplay.py`); Metamon's data is reused, not its code; the belief inference rules are a clean-room rewrite.

### D5. Teams
- **Evaluation**: each evaluation draws a fresh batch of team pairs from real games (`eval_pool`, the same sampler as self-play, non-overlapping seeds); fixed pools `wide200` / `wide1000` (A/B, Foul Play), diagnostic pools `offmeta200` / `random200` (D16).
- **Self-play** (`selfplay/teams.py`): draw a real game and use both sides' own teams (weighted by recent use, half-life 120 days); unrevealed sets are completed by the belief model (temperature 1.3, more spread than in the search, to avoid "the opponent is too easy to guess"); a local validator checks legality; for 30%, one side is replaced by a complete team from the team catalog (`data/teams/catalog.jsonl`).
- **Team data** (`data/teams`, `scripts/teams.py`): a catalog of complete teams (Smogon forums), team pools reconstructed from replays, replay / Smogon usage statistics.
- **D5-L Teams for playing people** (`doc/team_design.md`, 2026-10-27 / 28): a ladder win rate is mostly the player's, not the team's; rank by the matchup model's expected score against the recent metagame and its worst 20%, plus threat coverage (how many answers there are to each of the main builds of each common threat) and role slots; finally have our bot actually play the candidate teams against recent ladder teams (simulated games) and pick 3–5; sets are reconstructed from replays (EVs borrowed from similar forum sets), with the accuracy cross-validated.
- **D5-O Targeting a specific opponent** (research direction; a pipeline exists, `scripts/counter_pipeline.py`): the opponent's team distribution (exact teams + style, decayed by game count), a personalized belief, a play-style model (the network's rating input is enough); played only within the `play_public.py` whitelist; opponent names are not committed (`data/players/<id>/`).

### D6. Compute
This machine: 20 logical CPUs, 48 GB (WSL), RTX 4070 Ti 12 GB. No training during self-play (they compete for the GPU / CPU); large-memory jobs one at a time, capped with `systemd-run --user --scope -p MemoryMax=...` (an OOM once crashed WSL). Self-play slows down noticeably when games etc. use the GPU.

### D7. Evaluation protocol
- **Paired schedule**: each pair plays one game each way with the teams exchanged; report the paired win rate ± 95% CI (the per-pair score standard deviation is about 0.335: 100 pairs ≈ ±6.6 points). Each run writes `<log>.meta.json`; the arena has a 1-hour timeout per game; the summary includes the counts of heuristic fallbacks and search fallbacks.
- **A/B**: change one thing only (networks via `ALPHA_MODEL_A/B`; behavior changes get a temporary `_A/_B` switch, and the old path is deleted after the verdict), 1,600 iterations, 600 pairs to start; when the result is not significant, add 600 pairs on a fresh batch of team pairs; never re-select on the same batch.
- **External opponent**: Foul Play (200 ms × 1, wide200; or 5 s × 2 each, wide1000, 4 lanes; the local version is complete, only its parameters are weaker than when it played the ladder, `research_foul_play.md`).
- **Offline**: the human anchor validation set (upload time ≥ 1776921722); seed standard deviation about 0.003 for policy CE, 0.0025 for value BCE.
- **Public ladder**: once the bot registration is approved, `scripts/ladder.py` (one game at a time, CPU search, low priority); teams in D5-L.

### D8. Opponent belief model
- `belief/priors.py`: whole-team-conditioned priors (recognize a copied team → core-conditioned → species distribution, backing off level by level); moves = archetype posterior × team-conditioned marginal^β (β = 1); for items / tera the archetype weights and the base marginal are mixed with `ARCH_MIX` 0.6 (2026-10-25); damage evidence updates the opponent's sets (F1, `agents/damage_obs.py`). Built 2026-10-04 from 50k self-crawled replays; evaluation uses the heldout version; to be rebuilt after the October metagame shift (issue #16).
- Conclusions: team-conditioned priors are clearly better than Smogon marginals; of the opponent's actual moves that are missing from the worlds, about 21% were not used before and not guessed by the belief either, so improvement has to come from the belief (D14-3). The weak spot is move uncertainty (the value of perfect information is almost all in the moves, D11).
- Opponent speed: each world draws a speed tier from the sets in the usage statistics, excluding tiers that contradict the observed move order (D17 #14).

### D11. Hidden information and LLMs: settled conclusions
Knowing the opponent's true sets is worth about +8–12 points, almost all of it from the moves; in determinized search the number of worlds and the depth compete for the same budget; ISMCTS against determinization 57.3%; an LLM opening plan has no measurable value; the direction is closed.

### D12. ISMCTS (`rust/alpha_search/src/ismcts.rs`, `bsearch.rs`)
- **SO-ISMCTS**: one tree built on our information set, one world per iteration in rotation, apply / reverse in place; child key = (our action label, opponent action label); decoupled availability PUCT for both sides, FPU = the mean Q of the visited branches; open-loop chance, only the root's instruction table is cached.
- **Priors**: ours from the leaf forward pass, the opponent's from a flipped-view forward pass; value and priors must be used together (priors about +70 Elo, value about +47 Elo).
- **Context in the tree**: the steps along the path are added to the history, recorded by the **actual transition outcome** (the engine patch's `Acted` marker: a move counts as used, and is marked revealed, only once it actually starts; KO'd first is recorded as "fainted before acting", blocked as "blocked", consistent with the training replays); the forced switch after a faint is not a new turn (2026-10-14, A/B 51.3% ± 1.7%, no worse).
- **GPU batching**: the searches of many games share batching threads, tree parallelism (virtual loss), pipelining. **CPU**: root parallelism.
- **Tried, no effect, removed**: a root tie-break (when well ahead and several options have similar means, pick by the progress of a one-step rollout; A/B 48.75% ± 1.66%, code in `0a93698`); chance nodes split by observable outcome (now pure open loop).
- **Known limitations** (issues #7–#10, #18): in the end it plays only the most-visited pure strategy, which an adapting opponent can exploit; the opponent in the tree sees all of our sets (D14-1); the opponent's statistics are averaged across worlds (the proper fix is MO-ISMCTS); no belief update inside the tree (D14-3); open loop merges different public states; the in-tree history has no outcome markers (damage, move order).

### D13. Policy / value network (current v6arch-pp-v75: v6's 7 input groups + a remaining-turns head; the v7 input groups `ko2, tera, team, post` are implemented but not used by the current network)
- **Human data**: about 2.04M Gen9 OU games from Metamon + 310k public HF replays (training set only); `train/positions.py` replays them line by line and builds a one-sided engine state for each sampled decision point; decision steps map one-to-one to the engine's decision nodes (turn start, the switch after U-turn, the switch after a faint), 20 sampled per game.
- **Features** (Rust `features.rs` + `extra.rs` + `counts.rs`, one function shared by training and search; the full list is in "D13 appendix" below): 12 entities, global features, a 14-slot legal-action mask, an 8-step history (both sides' actions per step; the outcome group `hres` is not used by the current network); public-information markers, both sides' pre-game ratings; **matchup calculations** (damage ratios and KO thresholds, who moves first, etc.; the group with the largest gain).
- **Model** (`TransformerPV` in `train/model.py`): 12 entity tokens + a global token + 8 history tokens, pre-norm, 3 layers, d = 128, 4 heads, SwiGLU + RMSNorm + QK-norm, about 740k parameters; value residual `logit = a·eval/100 + b + net`; auxiliary outputs MTP-3, an opponent-set head, remaining turns (v6; also output at inference, used by the quick-win term). v6 added the input group `count` (`counts.rs`: PP, disabled, sleep turns, Protect count, Substitute HP, Wish / Future Sight, durations of volatile conditions).
- **Conclusions that hold**: history and the Transformer together gain more than the sum of the two (saturates at 8 steps); MTP-3 helps the value and switching; only GLU structures improve consistently; inference must not get systematically slower; a large network with 2.3× the compute is not stronger at the same number of iterations (the value overfits); more layers in the value head, a frozen trunk learning the value alone, value labels from games without search, a win-margin auxiliary head: none of them helped.
- **Inference**: Rust CPU (`tnet.rs`, equal to PyTorch layer by layer; after changing inference code run `scripts/check_tnet.py` / `check_extra.py`); GPU (`agents/gpu_net.py`, CUDA Graph + compile).

#### D13 appendix: the current network's input features (v6-s-spread, 2026-10-18)

All features are computed from the world state (a poke-engine state from our view: side one is us); training and search use the same Rust function (`features.rs` / `extra.rs` / `counts.rs`, called from Python via `alpha_search.featurize*`). The opponent's unknown fields (item, ability, tera type, unused moves) are filled with the set the belief model sampled, not with "unknown" (`mask_hidden` off). The network configuration is in `data/train/v6/runs/v6-s-spread/config.json`: `feats = reveal, num, movetab, matchup, elo, counter, count`.

**Entity tokens (12: our team's slots 0–5, then the opponent's slots 0–5; switch action 8 + j corresponds to entity j)**

| group | dims | content |
|---|---|---|
| sparse ids (base) | 10 | species, item, ability, tera type, type 1, type 2, 4 moves; embedding-table lookups (vocabularies 1536 / 256 / 384 / 32 / 1024). Items added by the engine patches (from Eject Button on; not yet present when the network was trained) all map to "unknown" |
| dense (base) | 23 | HP fraction, alive, active, terastallized, status one-hot (7), Atk / Def / SpA / SpD / Spe / max HP (/ 500), whether each of the 4 moves is usable (not disabled and has PP), is ours, level / 100 |
| `reveal` | 8 bits | public information: has been in; item / ability / tera type revealed; each of the 4 move slots revealed. For the opponent's Pokémon, what we have seen; for ours, what the opponent has seen |
| `matchup` | 22 | against the opponent's active Pokémon: speed log2 ratio / 2; the strongest hit of the opponent's active on it: max damage / HP, sure KO, possible KO; for the active one: its 4 moves on the opponent's active: damage / HP, sure KO, possible KO, effectiveness log2 / 2 (immune −1.5); for the bench: entry hazard damage fraction, whether it faints on entry. Damage uses the engine's full Gen 9 damage calculation (`calculate_damage_rolls`) |
| `counter` | 3 | for the bench: damage / HP taken when switching in on the opponent's predicted move (its strongest move against our active), whether it is KO'd; its own strongest hit on the opponent's active: damage / the opponent's HP |
| `count` | 10 | remaining PP of the 4 moves (min(pp, 16) / 16; the opponent's inferred by `build_state`), whether each of the 4 moves is disabled (Choice lock, Disable), Rest turns / 3, other sleep turns / 3 |

**Global token**

| group | dims | content |
|---|---|---|
| base | 277 | weather one-hot (8), terrain one-hot (5), Trick Room and its remaining turns; 131 dims per side: remaining turns / 8 of Reflect / Light Screen / Aurora Veil / Tailwind / Safeguard / Mist, Spikes layers / 3, Toxic Spikes layers / 2, Stealth Rock, Sticky Web, Healing Wish, Lunar Dance, Wish, Future Sight, Substitute, Toxic counter / 8, Baton Pass, Shed Tail, 7 stat stages / 6, forced switch, trapped, 104 volatile-status bits of the active Pokémon (bit 0 keeps its old meaning "has any volatile status") |
| `num` | 19 | per side: alive count / 6, sum of HP fractions / 6, tera used, last move (none or switch / move 0–3, which shows a Choice lock); weather / terrain remaining turns / 8; turn number |
| `matchup` | 2 | which active Pokémon moves first (+1 ours / −1 the opponent's / 0 speed tie; Trick Room included), speed log2 ratio / 2 |
| `elo` | 5 | both pre-game ratings ((r − 1500) / 300), their difference, whether known (0 = unknown in self-play) |
| `count` | 28 | per side: consecutive Protect count / 4, Substitute HP / the active's max HP, Wish remaining turns / 2 and heal amount / max HP, Future Sight remaining turns / 3; durations / 5 of confusion, Encore, locked move, Slow Start, Taunt, Yawn, Heal Block, Magnet Rise, Throat Chop |

**History tokens (8 steps, most recent first; a step is one decision point: both sides' choices at the start of a turn, the switch after a faint, the switch after a pivot move)**

| group | dims | content |
|---|---|---|
| sparse | 6 | ours: the acting species, the move, the species switched in; the same for the opponent (0 = none) |
| dense | 7 | the step exists; our move / switch / tera; the opponent's move / switch / tera |

In training the history comes from the replay; in search from the real game, plus the path inside the tree (recorded in the tree by the engine's actual outcomes, D12).

**Other inputs**

- Legal-action mask (14): 0–3 moves, 4–7 moves + tera, 8–13 switch to a slot.
- `movetab`: a static move table, 53 dims per move, projected and added to the move embedding: type one-hot (20), category (3), power / 150, accuracy / 100, priority / 5, 16 flags (bite, bullet, charge, contact, drag, heal, powder, protect, pulse, punch, recharge, reflectable, slicing, sound, pivot, wind), drain, recoil, crash, heal amount, sum of the stat changes to the user / the target / 2, status, volatile status, own / opposing side condition, the highest secondary-effect chance.
- Value residual: the handcrafted evaluation (the engine's `evaluate`). Value logit = a · eval / 100 + b + network output.

**Input groups added in v7 (2026-10-19; feature candidates F2 / F3a / F5 / F6; the ablation is in `results.md` "Ablation of the network v7 input groups"; v0 uses `ko2, tera, team`, not `post`, for the reason given after the table)**

Entity tokens get 50 more dims (45 in v7.1, with 7 `team` columns; `featurize_extra_full` in `extra.rs`, which shares one damage cache with `featurize_extra`; the whole block is added when any group is on, and the groups that are off are masked to 0), plus 10 dims of `post`. They are computed only for networks that read these inputs (`Context.full`), so the search with older networks does not get slower.

| group | dims | content |
|---|---|---|
| `ko2` (F3a, active) | 10 | its 4 moves on the opponent's active: sure / possible KO within two hits, computed hit by hit (the opponent does not act; the second hit is recomputed from the HP and stat stages after the first -- Super Fang takes half, Draco Meteor lowers SpA; between the two hits the opponent's end-of-turn HP change counts, using the engine's own end-of-turn resolution; Focus Sash / Sturdy, Substitute, the second hit after Knock Off has removed the item; charge moves / Future Sight count one hit only, Fake Out only right after switching in); priority moves of the opponent's active (priority from the engine): sure / possible KO on it (not against a grounded target in Psychic Terrain) |
| `tera` (F6, active) | 28 | while we can still tera: its 4 moves after tera on the opponent: damage / HP, sure KO, possible KO (12), the opponent's strongest hit on it after tera (3); while the opponent can still tera: its 4 moves on the opponent after tera: damage / HP, possible KO (8), the strongest hit of the tera'd opponent on it (3); two flags (we / the opponent can still tera). The opponent's tera type is this world's sample; across worlds that is the posterior. In addition, each move's ko2 (2) + after tera (3 + 2), 7 dims in all, feed the move output head, so the tera and non-tera action groups no longer share one input |
| `team` (F5, each living one) | 12 | against each living opponent (both treated as active, without the active one's stat stages / volatiles; counts / 6): how many it KOs in one hit, how many KO it in one hit; then by the "exchange" simulation (below): as a switch-in, how many it reliably / possibly answers, how many it reliably beats head-to-head, how many it reliably revenge-kills, how many switch-in exchanges are undecided within the round cap; as a threat, how many of the opponent's can reliably switch in to answer it, how many have an unknown switch-in outcome (not the same as losing to it), how many can reliably revenge-kill it; as an answer, for how many threats it is the only confirmed switch-in answer, the only confirmed revenge killer (other, unknown ones may also answer) |
| `post` (F2, each living one) | 10 | averaged at the root over all belief worlds (32; 4 per position in the training data) (a joint posterior, not independent marginals); against the opponent's active: faster than it, KO'd by its strongest hit, can KO it, takes less than half from its hit, a priority move can KO it; own set: has a recovery move, has a setup move, has a phazing / hazard-removal / boost-clearing move, a Choice item, Focus Sash or Sturdy (survives a one-hit KO from full HP). Not updated in the tree; passed down with the context |

`post` is not in v0: it has the largest offline gain but is weaker with search (v0-post against v6-h 46.8% with search, 55.2% without). It is computed once at the root and reused across the whole tree, so it is already stale at the leaves; and the network relies on it heavily (one step stale: value BCE +0.012, policy CE +0.13). At nodes from the opponent's view, the opponent's own set slots are fractions, never seen in training. The column stays in the data (v7.1: the extra worlds no longer resample our sets); using it first needs a redesign of how it is used in the tree (issue #11).

F1 (damage evidence updates the opponent's sets, `agents/damage_obs.py`) is not a network input: it changes the belief worlds, and through them the search's worlds, the inputs of each world and `post`. It is used only in live play (like speed inference); the training data do not change.

**Exchange simulation** (`team`'s three kinds of answers, 2026-10-20, `fight` in `extra.rs`; tightened after the second review): each side uses one fixed move (its highest-damage move against the other; not counting moves usable only on the first turn, moves that hit a turn later, or moves that counter the damage taken; an active Pokémon is bound by its Choice lock), no switching, no recovery, no setup, no tera, no chance events (no crits, no misses, chance secondary effects do not happen).
- Hit by hit: each hit uses the HP, stat stages and item at that moment (Super Fang, Endeavor, Multiscale; the self-drops of Draco Meteor and Close Combat, guaranteed secondary stat drops; after Knock Off removes an item, an Air Balloon pops or a resist berry is eaten, the engine recomputes without the item); it ends as soon as one faints in one hit; after each hit the effects on the user count (recoil, drain, Life Orb, Rough Skin / Rocky Helmet, Contrary / Simple); a Substitute takes damage piece by piece (the overflow of the hit that breaks it does not count); Sitrus Berry / the 1/3-heal berries heal once at their threshold (not eaten under Unnerve / As One).
- Moves that need the opponent to act (Sucker Punch, Thunderclap, Upper Hand): they fail on the switch-in turn; after that they succeed only when the user moves first and the opponent uses an attacking move.
- End of turn: the engine advances 5 ends of turn in a row, carrying the state over to the next (Toxic getting worse turn by turn, Wish / Future Sight resolved only once, weather / terrain expiring), all undone afterwards. Healing and damage are measured separately at each end of turn (measured at 1/4 max HP; when one side has fainted, healing at 1/2 and damage at full HP), and neither is capped by the current HP (the net change used to be measured at 3/4 HP: Wish's half-HP heal was capped to 1/4); in the exchange, healing is added first at the actual HP (up to max HP), then damage is subtracted. HP-triggered berries are removed while measuring (the exchange resolves them itself). Cached by the actual pairing: the same Pokémon is computed separately against different opponents only when the opponent changes its end of turn (Cloud Nine / Air Lock, Neutralizing Gas, Nightmare, an opposing active with Leech Seed on it) (previously computed together by "both sides' j-th Pokémon", so the team order could change the result); one that has lost its item, or has Salt Cure / partial trapping on it, gets its own copy. Ends of turn that only change HP are copied for the remaining ones; the first 2 are computed first and the rest only filled in when the exchange goes further.
- Move order: the engine's priority, then the engine's speed and Trick Room; on a speed tie "reliable" assumes the opponent moves first and "possible" that we do; Psychic Terrain blocks priority moves against grounded targets.
- Unsupported mechanics give "unknown", not a win or a loss (`unsupported`): abilities and items that react to a hit or a turn and change the exchange (Speed Boost, Weak Armor, Stamina, Berserk, Justified, Defiant, Competitive, Moody, Libero / Protean, Color Change, Disguise / Ice Face, Emergency Exit / Wimp Out, Weakness Policy, Eject Button / Eject Pack, Red Card, White Herb, Room Service, other berries), a Booster Energy on a Pokémon not yet in (it activates on entry), a Flame / Toxic Orb not yet activated (Guts after the burn, the halving). How pivot moves (U-turn etc.) and Explosion-type moves are handled when they are not the fixed move: pivot moves are not used as the fixed move, and ko2 counts them once; after an Explosion-type move the user faints. The share of "unknown" and the errors broken down by mechanism are in the assertion checks in `results.md`.
- Switch-in answer: first apply the engine's switch-in, subtracting entry hazards and reading the stat stages after entry (Intimidate, Intrepid Sword, the Sticky Web Speed drop; weather / terrain set on entry gives unknown), then take one free hit from the opponent (Sucker Punch-type moves excluded), then exchange hits in move order; "reliable" uses our lowest damage (85% × the fewest hits) and the opponent's highest, "possible" the reverse.
- Head-to-head: both already active; no entry costs, no free hit, a direct exchange (reliable).
- Revenge kill: free entry after a faint (entry hazards subtracted); it must move first and KO with the first hit (reliable; unknown when the opponent has Disguise / Ice Face).
- ko2 is also hit by hit: it tracks the attacker's HP (recoil, Life Orb, drain, the attacker's own end of turn); if the attacker faints there is no second hit.
- Round cap 4 (`ROUNDS`); beyond it the result is "unknown", counted separately, not a loss.

v7.1 data (2026-10-20, `data/train/v71`, current): fixes 4 issues the review found in v7 -- `post`'s extra worlds resample only the opponent; "has a recovery move" does not count draining moves; "has a setup move" adds Belly Drum / Fillet Away / Clangorous Soul, and a Ghost-type's Curse does not count; `post`'s priority KO takes Psychic Terrain into account like ko2.

v7.2 inputs (2026-10-20, `EXTRA_VERSION` 3, fixes after the review; the data are still to be rebuilt with it, `results.md` "Feature assertion checks"): game rules are no longer copied; the engine is called directly (speed `get_effective_speed`, priority `modify_choice_priority`, switch-in `generate_instructions_from_switch`, end of turn `add_end_of_turn_instructions`, Substitute `hits_substitute`, crits `hit_crit_chance`, all run on a working copy and then undone); the earlier copies lagged behind the engine fixes (Slush Rush in snow, the Power items, Unburden, Cloud Nine, Magic Room), and the end of turn and hazards used the original types (Black Sludge, sandstorm, Salt Cure and Flying-type checks after tera were all wrong). Also fixed: multi-hit moves use the engine's hit count (previously one hit: Scale Shot was undercounted 2–5×), always-crit moves use crit damage (Surging Strikes etc.), immunity to Endeavor / Final Gambit (previously judged as for Ghost-type moves, L230), the KO flags take Focus Sash / Sturdy and Substitute into account, charge moves and Future Sight do not count as a KO on that turn, Fake Out only right after switching in; `ko2` is computed hit by hit, `team` became the exchange simulation (12 columns). Feature cost: about 141 µs per position (v3 20 + v7 121; v7.1 about 91 µs, estimated).

Two input bugs fixed at the same time (P0 / P2, from the v7 data on): hypothetical matchups for the bench no longer carry over the active Pokémon's stat stages / volatiles / Substitute (`EXTRA_VERSION` 2, affects `counter` and the bench's `matchup`); fainted and empty-slot entities have their 4 move-usable bits at 0.

**Computed but not used by the current network**: `hres` (the outcome of each history step: moved first, damage dealt, crit, miss / fail, KO, blocked, fainted before acting; 7 dims per side, present in the data); the auxiliary heads `faint`, `margin` (tried, no gain). The current auxiliary outputs are `oppset` (the opponent's sets), `turns` (remaining turns, for the quick-win term) and MTP-3.

### D15. Self-play pipeline (`scripts/selfplay.py`, code in `alpha_poke/selfplay/`)
- **One generation's flow** (`iterate`): `teams` → `run` → `convert` → `train` → `eval`; if it does not pass, continue with `run` (see "Extending a generation" below); separate commands `stats`, `value` (a value check on new games), `baseline` (against a few generations back), `foulplay`, `diag`. The state is in `state.json`; resuming after a stop only plays the games still missing.
- **Games**: 10 processes × 24 games (about 3,500–4,000 games / hour, limited by the Python overhead per decision, issue #15), batched search across games; 25% of the decisions get a full search (1,600 iterations, producing policy targets), the rest a fast search (400 iterations, 16 worlds); root Dirichlet noise ε = 0.1, concentration 10; temperature 1 for the first 8 turns, 0.25 after; no search when there is only one legal option; the bot's rating input is "unknown"; a 300-turn cap (resign, recorded as capped). **Loop exploration**: when for one side no Pokémon has fainted in 20 turns and it has switched 6 times in the last 8 turns, temperature 1 and noise 0.25 (from generation 8).
- **Recording and conversion** (`convert.py`): for each decision Rust records the root's network inputs, the per-slot visits / means / priors and the root q; labels known only at the end of the game are aligned by the replay pipeline; capped games get the value 0.5 (a draw); decisions more than 10 turns after the last faint are left out of the policy targets.
- **Training** (`train_pv.py --init <current network>`): soft cross-entropy of the policy against the visit distribution, value BCE, MTP and the opponent-set head; data = all of the latest generation + the earlier generations, sampled by game, together 50% of that (`--window 1 --old-share 0.5`), at most 50 positions per game, mixed with human data (human share max(20%, 50% − 5% × generation), no longer lowered once the drift passes the alarm line); lr 4e-4, about 3 epochs, 20% warmup, cosine decay; the value counts once per position, spread evenly over the whole training from generation 8 (`--sp-value-schedule spread`, against first 52.4% ± 2.6%); self-play data are streamed in chunks (`--sp-stream`).
- **Extending a generation until it is clearly better** (since 2026-10-27, `selfplay.py iterate`): each time the current network's games accumulate a chunk (`--chunk`, 50k games since 2026-10-28, 25k before), a candidate (r2-gen<G>a<k>) is fine-tuned on all the games and put through a sequential test H0 = 51%, H1 = 54% (since 2026-10-28; 52% / 55% before), α 0.05, β 0.1, up to 2,000 pairs, a new team pool for each attempt; it is promoted only when the test accepts H1 (or, undecided at the cap, the lower end of the 95% interval is ≥ 51%); otherwise play continues. Generation 0: 53k games 50.2% ± 3.7%, 78k games 52.5% ± 2.1%, neither promoted.
- **Evaluation**: see above (the sequential test with H0 51% / H1 54%; no verdict when fewer than 80% of the pairs are complete); models are registered in `data/selfplay/registry/` (`matches.jsonl`, `models.json`). The old line's "promote when not worse" (H0: 20 Elo weaker) is retired: the small gains from generation to generation could not be measured, and nobody knew how many games would be enough.
- **Monitoring**: validation before and after training for each attempt (self-play / human policy CE, value BCE, KL to the starting point), the human-data drift guard, game statistics (turn counts, grouped by team source), counts of inconsistencies between the request and the engine state.

### D16. Self-play team distribution (under study)
Diagnosis (sp-gen1 against v5-glu: ladder / off-meta / random pools 54.6% / 51.6% / 51.8%, none significantly different): diversity was not a clear weakness at the time. Current: popularity flattened (weights further multiplied by 1 / composition count^0.3), team catalog share 15%, half synthetic teams (below); the diagnostic pools are run by hand when needed (`selfplay.py diag`).

**Synthetic teams (2026-10-26, `selfplay/teams.py` Composer / `synthetic`, `selfplay/synergy.py`)**: half of self-play's teams (`--synth-frac 0.5`) are synthetic: species are drawn one by one by Smogon usage and lift with the teammates already picked (γ 0.7, Species Clause by base species, ε 0.1 flattening noise); sets are first completed by the belief, then each move slot / item / ability / tera is redrawn with probability 0.1 from the Smogon distribution (square-root flattened); then 12 Metropolis-Hastings steps: each step redraws one member's set and accepts with exp(β·change in the cross-teammate synergy score) (β 0.5; synergy score = the sum of the log lifts of feature pairs between teammates, minus what the species themselves explain; `scripts/build_synergy.py`, statistics of the revealed sets in 120k games); finally the local validator. Diagnosis (`scripts/check_synthetic_teams.py`, 1,000 teams): 92% of the compositions never appeared on the ladder, 99.8% are distinct; the frequencies of the top 200 teammate pairs correlate 0.80 with the ladder (0.63 with independent draws); the share with a second Trick Room setter 0.17 → 0.46 (β 1.0: 0.53; revealed on the ladder: 0.53), the item distribution's TV to Smogon 0.23 → 0.17; all pass validation (2–4% redrawn). Abilities that are never shown (Chlorophyll, Swift Swim) cannot be seen in the ladder statistics, so the synergy score cannot learn them.

### D17. Engine state and rule simulation (`agents/engine_state.py`, `agents/timers.py`, `rust/patches`)
Engine = poke-engine 0.0.48 + the alpha-poke patches (commented "alpha-poke patch"); the Python bindings are built from the same source. Before every search `agents/consistency.py` checks the request against the engine state. Verification tools: `scripts/difftest.py` (differential tests of the state construction and the engine against Showdown; the old check_actions / check_timers / check_speed were deleted on 2026-10-28), `tests/test_engine_patches.py`, `test_timers.py`, `test_engine_state.py`, `test_transform.py`.

**Simulated**: switches by slot number; sleep / Rest, Toxic, consecutive Protect, Wish, Future Sight, confusion / Taunt / Encore / Yawn, Heal Block / Magnet Rise / Throat Chop (including its ban on sound moves), Perish Song, Disable, the must-recharge counter; items that are gone are not resampled; stat boosts and volatile conditions; Revival Blessing (one search per candidate); exact PP from the request, the opponent's PP by use count; Eject Button / Red Card / Eject Pack / Emergency Exit / Wimp Out; status berries, Persim Berry, Mental Herb, Safety Goggles, Early Bird; Charge ends after use; a Substitute that has been hit counts as half; duration-extending items (8 turns); opponent speed inference; Transform; Illusion (by probability).

**To fix**: the approximations listed earlier on the engine side have been implemented as in Showdown during the differential work (`engine-diff.md` L1–L247); what remains is in the issues (labels `engine` / `state` / `difftest`: #1–#3, #5, #6, #21).

### D14. Research direction: hidden information in the search (each item to be validated; check the literature before starting; issues #18, #19, #10)
1. **Two-way information modeling (first choice)**: the flipped-view forward pass for the opponent's prior masks the information about us that it cannot see (the masking mechanism `--mask-hidden` exists); validation: battle comparisons + the timing of tera / key-move reveals.
2. **Identity conditioning + sparring partners**: input our / the opponent's identity (`human@rating`, `bot@generation g`, unknown); self-play sparring partners drawn from past bots and "human@rating"; an opponent-identity auxiliary head.
3. **Learned belief + consistency filtering**: the network's opponent-set head is more accurate on unrevealed fields than a single belief sample; route: the network reweights the belief's candidates → a generative set model → remove worlds contradicted by the move order and the damage.
4. **Game-theoretic search for simultaneous moves**: regret matching to produce mixed strategies.

## 5. Roadmap and to-dos

The to-dos are all in GitHub issues (`gh issue list`; priority labels P0–P3, area labels engine / state / difftest / search / network / training / selfplay / belief / eval / team / research). When one is done, close the issue, write the conclusion into the matching D section and the numbers into `results.md`.

The current main lines (2026-10-28):
1. Playing people: the team-selection process (`team_design.md`) produces a set of teams; the ladder once the bot registration is approved (#20); known problems against humans: the pure strategy can be exploited (#7), speed judgments (#4).
2. Self-play r2 generation 0 keeps extending until clearly better (D15); throughput (#15), the belief rebuilt for the new metagame (#16).
3. States and engine: #1–#3.

Basis of the ordering (measurements of 2026-10-18, `results.md` "Effect of engine accuracy on decisions"): switching the engine to the version after the differential work +16.5 Elo, fixing the states passed to the engine +43 Elo, the regret of the 800-iteration search itself about 7× the engine error -- the main levers of playing strength are the network, the search, the belief and the accuracy of the state.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Self-play converges on "beating itself", cycles / forgetting | human-data anchor; sampling of earlier generations; a cumulative check every 3 generations, the Foul Play reference; sparring partners (D14-2) |
| Slow decline (each generation slightly weaker, but not measurably) | promote only when clearly better (H0 51%); `baseline` against a few generations back |
| The value learns slowly / overfits / is pulled off by human data | the value schedule (v6); a value check on new games every generation |
| Inputs differ between search and training | one function for the features; in-tree context recorded by actual outcomes (D12); consistency checks after inference changes |
| Inference slows the search | structural changes constrained by leaf speed |
| Evaluation noise | paired schedule + confidence intervals + SPRT; when an A/B is not significant, add new team pairs; never re-select on the same batch |
| poke-engine is not faithful | used only as an approximate model in the search; games run on Showdown; the D17 problem table; fallback accounting |
| Metagame changes (ban lists, new Pokémon) | team sampling weighted by time, the validator on today's rules; add new data |
| Licenses / rules | the replay data carry no license: local use only, weights limited to non-commercial research; Foul Play is GPL; PS's bot policy (2026-10): register first, humans play bots by choice, using AI in a tournament counts as having someone else play for you |
