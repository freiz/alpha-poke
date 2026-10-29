# Foul Play and poke-engine: a technical study

> Date: 2026-10-04. Purpose: choose the technical route for "building a strong Gen9 OU singles AI locally" (Python / uv / poke-env 0.16.1 / AM5 CPU + RTX 4070 Ti + 64GB).
>
> **Method**: shallow clones of the two repositories, then reading the source directly (foul-play `8f541f8`, 2026-10-03; poke-engine `c2dbbda`, 2026-10-03; both `--depth 50`, so the history is incomplete), supplemented by the blog, the Smogon thread, the PokéAgent paper (the HTML full text of arXiv 2603.15563, text extracted by a script and then searched), GitHub issue / PR pages, the PyPI / GitHub APIs. **Every code claim in this report gives a file path and a function name / line number**; line numbers refer to the commits above.
>
> **Markers**: `[self-reported]` = the author's own statement (blog / forum / README / an appendix the author wrote in the paper), no third-party reproduction; `[external]` = given by the organizers or a third party; `[UNVERIFIED]` = not verified this time, a guess or second-hand information. The blog / Smogon thread / some issues were read through a small model's WebFetch summary; their numbers are "the numbers the summary reported", not checked word for word.
>
> **Not done (task constraints)**: no compiling of the Rust engine, no pip / uv install of any dependency, no Showdown started, no battles on any public server; the only network access was the HTTP download of two static JSON files from `data.foulplay.cc` to measure the data's size. Hence **no performance number (nodes/s, per-move latency) was measured**.

---

## 0. Summary (TL;DR)

1. **Foul Play = a Python client (its own websocket code, no poke-env) + the Rust engine poke-engine + "sample opponent sets -> run DUCT-MCTS on each sampled world -> sum the visit counts"**. Search leaves get no rollout but a **hand-written heuristic evaluation** (squashed with a sigmoid). No neural network, no training.
2. **Opponent modeling is the key to its strength**: Smogon usage stats + complete sets scraped from the forum / replays + about 10 hard-coded inference rules (speed ranges, Choice item locking, Heavy-Duty Boots, Assault Vest, damage back-calculation, etc.). Filtering is **hard elimination from a discrete candidate set**, not a Bayesian posterior; sampling from the "complete set library" is **uniform** (deliberately not weighted by count), sampling from the Smogon marginals is weighted by their product.
3. **Strength**: Gen9 OU self-reported peak Elo 1879 / GXE 80% / top 100 `[self-reported]`; PokéAgent Challenge qualifier #1 seed, won the final 50–14 against Team Q `[external, paper]`, beat the organizers' private RL baselines `[external]`. Known weaknesses: defensive / stall teams, long-term planning, moves with delayed payoff (Toxic), "exploitable once you know it is a bot" `[self-reported]`.
4. **poke-engine is MIT-licensed**, Foul Play itself is **GPL-3.0**. This difference decides the reuse strategy: **the engine can be depended on / vendored / forked freely; Foul Play's Python code is only fit as an opponent in a separate process or as a "reference for ideas", and should not be imported into our core.**
5. **The engine's fidelity is limited and there are no tests against Showdown** (no Showdown consistency tests in `tests/` or `src/`; 6 unmerged mechanics-fix PRs / issues, including Mean Look / Block / Spider Web trapping, Protect, sleep moves, Doom Desire, Destiny Bond). Fit as "an approximate model for search", **not as a ground-truth simulator for training**.
6. **Installation / running pitfalls**: (a) dependency conflict with poke-env 0.16.1 (`websockets==14.1` vs `==16.1.1`), a separate venv is required; (b) PyPI only has an sdist, a Rust toolchain is needed, and the build is per generation via features: Gen9 needs the `terastallization` feature; (c) the default team file path does not work for `gen9ou`: `--team-name gen9/ou` is needed; (d) at run time it fetches 4 kinds of external data over the network (Smogon stats, `data.foulplay.cc`, `play.pokemonshowdown.com/data/sets`, and `play.pokemonshowdown.com/action.php` for login); running locally offline needs pre-filled caches and a patch to `login()`; (e) the defaults `--search-time-ms 100 --search-parallelism 1` are a **weak configuration**; the author plays with about 7 seconds × 8~14 states.
7. **Recommendations for us (details in section 9)**: ① use Foul Play right away as an **evaluation opponent in an external process** (0.5~1 day); ② use poke-engine as **a dependency of the search / evaluation layer**, writing our own state conversion and belief sampling on poke-env (the Laplace project shows this route works); ③ **clean-room rewrite** of the set inference rules, no copying of `fp/` code; ④ the hybrid "learned policy / value + search over sampled worlds" needs a fork of the engine (MIT allows it) adding PUCT priors and batched NN evaluation, about 2~4 weeks.

---

## 1. Overview and architecture

### 1.1 Code size and structure

foul-play: `fp/` about 6,200 lines of Python (`protocol.py` 2375 lines, `inference.py` 800, `state.py` 827), tests ~737 `def test` (`tests/test_battle_modifiers.py` alone is 7340 lines); CI is ruff + pytest (`.github/workflows/ci.yml`, Python 3.13).

```
run.py                       entry point: asyncio.run(run_foul_play())
fp/config.py                 argparse configuration (singleton FoulPlayConfig) -- no .env
fp/main.py                   run_foul_play(): login -> loop over games
fp/websocket_client.py       PSWebsocketClient: its own websocket client (websockets + requests)
fp/run_battle.py             pokemon_battle(): the per-game main loop
fp/battle/state.py           Battle / Battler / Pokemon / Move
fp/battle/protocol.py        Showdown protocol message parsing (~60 handlers)
fp/battle/inference.py       speed / Choice Scarf / Boots / damage back-calculation inference
fp/data/sets/*.py            Smogon stats / team datasets / randbats datasets
fp/search/*.py               sampling opponent worlds + calling the engine
fp/modes/*.py                random / standard / battle_factory / bss modes
fp/generations.py            mechanics switches for Gen1–9 + gen9champions
fp/teams/                    bundled teams (text export format) and packed conversion
```

### 1.2 Connection to Showdown

- **No poke-env**. `fp/websocket_client.py: PSWebsocketClient` connects to `ws://…/showdown/websocket` with `websockets` directly and sends `/trn`, `/utm`, `/challenge`, `/search`, `/choose`, `/team`, `/timer on` and other commands itself (`create()`, `login()`, `update_team()`, `challenge_user()`, `accept_challenge()`, `search_for_match()`).
- **Login always goes to the public login server**: `login()` (`websocket_client.py:89`) without a password POSTs `https://play.pokemonshowdown.com/action.php?` for a guest assertion, with a password POSTs `https://play.pokemonshowdown.com/api/login`; then sends `/trn name,0,assertion`. This happens even against a local server -> an offline setup needs a patch (see 6.3).
- Configuration is command-line arguments only (`fp/config.py: _FoulPlayConfig.configure`), **no .env**. `--websocket-uri` accepts the shorthands `ps`/`pokemonshowdown` -> `wss://sim3.psim.us/showdown/websocket`, `local`/`localhost` -> `ws://localhost:8000/showdown/websocket` (`get_websocket`, port hard-coded to 8000).

### 1.3 Options (`fp/config.py`)

| option | default | meaning |
|---|---|---|
| `--websocket-uri` `--ps-username` `--ps-password` `--ps-avatar` | required/None | connection and account; no password = guest |
| `--bot-mode` | required | `challenge_user` / `accept_challenge` / `search_ladder` |
| `--user-to-challenge` | None | required in challenge mode |
| `--pokemon-format` | required | e.g. `gen9ou`; `FormatSpec` parses generation, random/battlefactory/bss/champions/blitz/nationaldex with regexes (`fp/format_spec.py`)|
| `--smogon-stats-format` | =format | overrides which Smogon stats file is used |
| `--search-time-ms` | **100** | MCTS time **per sampled state** |
| `--search-parallelism` | **1** | number of sampled states searched at once (processes)|
| `--search-threads` | 1 | threads within each state (the engine's shared-tree MCTS, ≥0.0.47)|
| `--team-preview-search-time-ms/-parallelism` | =the two above | **used only in BSS mode** (`fp/search/bss.py:80-90`); team preview in standard Gen9 OU goes through `standard_battle.search_params` and uses `--search-time-ms/--search-parallelism` (with the sample count ×2 at preview)|
| `--team-name` / `--team-list` | =format | team file / folder (a folder: one drawn at random per game) / a list rotated in order |
| `--run-count` | 1 | how many games before exiting |
| `--save-replay` | never | always/on_loss/on_win |
| `--room-name` | None | room joined first in accept_challenge mode |
| `--log-level` `--log-to-file` | DEBUG / off | logging |

### 1.4 Supported formats

README: **singles** in all generations, no Dynamax and no Z-moves (the code still has leftover `can_dynamax`/`can_z` branches, `modes/base.py: format_decision`, Dynamax only used on the last Pokémon). `fp/modes/__init__.py` registers 4 modes: `RandomBattleMode`, `StandardBattleMode`, `BattleFactoryMode`, `BSSMode`; plus `gen9champions` (Champions rules, added only in 2026-07, commit `a338d59`). Mechanics differences are carried by a set of switches in `fp/generations.py: GenerationMechanics` (whether Heavy-Duty Boots exist, the paralysis Speed divisor, whether there is team preview, whether damage back-calculation is supported, etc.).

### 1.5 The per-game decision loop

`fp/run_battle.py: pokemon_battle()`:
1. `start_battle()`: `battle_mode(...).start_battle()` does the initial handshake, then sends `hf` and `/timer on` (it turns the timer on itself).
2. Loop `receive_message()` -> `async_update_battle(battle, msg)` (`fp/battle/protocol.py:2374`). It returns `action_required` only on `|request|`; other lines go into `battle.msg_list` and in `process_battle_updates()` (`protocol.py:2290`) are dispatched **line by line in a batch** through the `battle_modifiers_lookup` dict to ~60 handlers, calling the inference functions `check_speed_ranges`, `check_choicescarf`, `update_dataset_possibilities`, `check_heavydutyboots` and others.
3. When a decision is needed, `async_pick_move(battle)` (`fp/modes/base.py`): `deepcopy(battle)`, `user.update_from_request_json(request_json)` (our side's information is taken from the request JSON), run `find_best_move` (`fp/search/main.py:58`) in a `ThreadPoolExecutor`, then `format_decision` into `/choose move X [terastallize]` or `/switch N`, with the `rqid`.
4. At the end of the game it sends `gg`, saves per `--save-replay`, `/leave`.

### 1.6 Battle state tracking

`fp/battle/state.py`: `Battle` (weather, terrain, Trick Room, Gravity, `turn`, `rqid`, `request_json`, `time_remaining`), `Battler` (`active`/`reserve`, side_conditions, wish, future_sight, `last_used_move`/`last_selected_move`), `Pokemon` (`stats`/`evs`/`nature`, `speed_range`, `impossible_items`, `impossible_abilities`, `can_have_choice_item`, `item_inferred`, `hidden_power_possibilities`, `terastallized`/`tera_type`, `volatile_statuses` and their durations…), `Move` (PP computed per generation). Our side's nature / EVs come from the team file (`Battler.initialize_first_turn_user_from_json` reads `team_dict`), because the request JSON only gives final stats.

### 1.7 Teams and team preview (Gen9 OU)

- **Teams**: `fp/teams/load_team.py: load_team(name)` reads `fp/teams/teams/<name>` (Showdown text export format), `team_converter.export_to_packed` converts it to packed, then `/utm`. The repository **ships only 1 sample Gen9 OU team** (`fp/teams/teams/gen9/ou/example`: Ting-Lu / Pelipper / Amoonguss / Dragapult / Iron Treads / Iron Valiant). The default `--team-name` equals the format string `gen9ou`, while the actual path is `gen9/ou`: **`--team-name gen9/ou` must be passed explicitly** (otherwise `load_team` raises `ValueError("Path must be file or dir")`). The teams used in the competition / on the ladder are the author's own, **not published `[UNVERIFIED]`**; the forum thread says testing was mostly offense / balanced offense `[self-reported]`. Foul Play itself **does no teambuilding**.
- **Team preview**: `fp/modes/base.py: handle_team_preview()` builds a Battle with "dummy actives on both sides, `team_preview=True`" and reuses the same sampling + MCTS, **choosing only the lead**: in the `team_preview` state, the engine's candidate actions for both sides are "send in the i-th Pokémon" (`poke-engine/src/genx/state.rs: root_get_all_options`, about lines 1148–1171); the result is sent as `/team {lead}{the rest in original order}`. The opponent's 6 are known (visible at preview), their sets sampled as usual. The opponent's lead is also modeled as a DUCT opponent choosing 1 of 6.
- `fp/battle/state.py: smart_team_preview` substitutes forms that preview does not reveal, e.g. Urshifu (`gen9ou: urshifu → urshifurapidstrike`).

---

## 2. Opponent modeling / set prediction

### 2.1 Data sources (`fp/data/sets/`)

| source | file / function | content | how obtained |
|---|---|---|---|
| Smogon monthly stats (chaos JSON) | `smogon.py: SmogonSets._get_smogon_stats_file_name` | uses **last month's** `…/stats/{Y}-{M}/chaos/{format}-0.json` (`-0` = no rating cutoff, code comment "the higher ladder is for noobs"); on 404 falls back to two months ago | HTTP at run time, cached in `fp/data/smogon_stats_cache/` |
| complete set library `pokemon_full_sets.json` | `team_datasets.py: PKMN_SETS_REMOTE_BASE_URL = https://data.foulplay.cc/{mode}/{file}` | key `tera|ability|item|nature|evs|move1|…` -> count. Our measurement of the gen9ou file: 349 species, 4,738 distinct complete sets, total count 7,894 | HTTP at run time (the author's S3 site), cached in `fp/data/pkmn_sets_cache/<format>/` |
| replay move combinations `replay_moves.json` | same as above | `move1\|move2…` -> count. gen9ou measured: 522 species, 31,607 move combinations, total count 587,660 (presumably from public replays; the build script is **not in the repository**)| same as above |
| Showdown's official sets | `team_datasets.py: get_ps_sets_file` -> `play.pokemonshowdown.com/data/sets/{format}.json` | merged into the complete set library (counts added)| same as above |
| Random Battle sets | `fp/data/sets/randbats.py` -> `pkmn.github.io/randbats/data/full/{format}.json` | the known sets of random battles | same as above |
| static pokedex / moves | `fp/data/pokedex.json`, `moves.json` + `fp/data/mods/*_mods.json` | generated by `fp/data/scripts/update_*.py` compiling Showdown's `moves.ts` with `tsc`+`node`; a GitHub Action opens a PR automatically every day at 00:00 (`.github/workflows/update-data.yml`)| in the repository |

> Important: **`data.foulplay.cc` is data hosted by a third party (the author)**, license not stated `[UNVERIFIED]`; the cache directory is inside the package (`DATA_DIR/pkmn_sets_cache`); offline use needs it warmed in advance.

### 2.2 Generating and weighting candidate sets

Two data structures (`fp/data/sets/base.py`):
- `PokemonSet`: ability/item/nature/evs/count/tera_type (a "trait combination");
- `PredictedPokemonSet` = `PokemonSet` + `PokemonMoveset` (a "complete set").

**Smogon data -> trait combinations** (`smogon.py: SmogonSets._initialize`): the **Cartesian product** of the stats' Spreads / Abilities / Items / Tera Types, `count = ability_p × item_p × spread_p × tera_p` (i.e. **the four are assumed independent**);
- Spreads are first merged by `spreads_are_alike` (same nature and each EV within max_ev/4), top 20 kept; Items top 10; Tera top 6; Moves top 100 (used only as marginal usage, **not tied to sets**);
- `_pokemon_set_makes_sense` filters clearly unreasonable combinations (Choice Band requires Attack EVs ≥ 50% of max; Specs likewise Special Attack; Scarf requires Speed EVs ≥ 80%; Life Orb / Expert Belt require offensive EVs).

**Illogical-set filter** (`base.py: PredictedPokemonSet.set_makes_logical_sense`): Light Clay requires a screen move; Toxic / Flame Orb require the matching ability; Choice items allow at most 1 "move of the other category" (except Trick / U-turn / Volt Switch / Flip Turn); Life Orb requires offensive EVs; Assault Vest forbids status moves; Poison Heal ⇒ Toxic Orb; physical / special "setup moves" require the matching EVs / nature / item; Protect does not coexist with Choice; Baton Pass requires a setup move; Trick / Switcheroo require a Trick-able item; non-"utility" attacking moves may not sit on a set with the opposite offensive EVs (the `damaging_move_is_utility` whitelist: U-turn, Volt Switch, Flip Turn, Nuzzle, self-destructing moves, Knock Off, priority moves).

### 2.3 In-game "filters" (hard elimination + exclusion sets)

All inference happens in the batch processing of `fp/battle/protocol.py: process_battle_updates`:

| inference | where | logic |
|---|---|---|
| **Speed range** | `inference.py: check_speed_ranges` | When both sides moved at the same priority with no switch / `cant` / confusion self-hit / Custap / Quick Claw / Quick Draw, our actual Speed (with boosts, Tailwind, paralysis, Scarf, Protosynthesis / Quark Drive) sets the min or max of `opponent.speed_range` (reversed under Trick Room). Skipped if the opponent may have Prankster / Unburden / a weather Speed ability, etc. `PokemonSet.speed_check` eliminates candidates by comparing this range with the Speed computed from nature / EVs (including Scarf ×1.5) |
| **Scarf** | `inference.py: check_choicescarf` | The opponent should move second (we are faster) but moves first, and no Speed modifier is possible ⇒ if even "max Speed Jolly 252 Spe" (under Trick Room, "slowest") would still be slower than us ⇒ it is judged to hold Choice Scarf, `item="choicescarf"`, `item_inferred=True` |
| **Damage back-calculation (EVs / nature / item / ability)** | `inference.py: update_dataset_possibilities`/`_do_check` | For each candidate set: write its ability / item / nature / EVs into a copy of the opponent, call **the engine's `calculate_damage`** (`search/poke_engine_helpers.py: poke_engine_get_damage_rolls`) for the damage range `[0.85·max, max]`; if the observed damage (HP% × max HP) is below `0.975·lower bound − level/20` or above `1.025·upper bound + level/20` (the crit maximum for a crit), the set is eliminated. When the damage ≈ the remaining HP, the lower bound is not checked (overkill). Excluded: status moves, multi-hit moves, Hidden Power, Pursuit / Counter / Mirror Coat / Metal Burst / Foul Play / Future Sight and ~13 moves in all, plus Ditto / Shedinja / Terapagos / Meloetta. **Done in both directions**: `damage_dealt` (opponent hits us, inferring its offensive side) and `damage_received` (we hit the opponent, inferring its defensive side)|
| **Choice item exclusion** | `protocol.py: move()` (about lines 816–835), `unlikely_to_have_choice_item` (line 70)| The same Pokémon using two different moves in a row ⇒ `can_have_choice_item=False`; using a boosting status move or Substitute / Roost / Recover ⇒ the same |
| **Assault Vest / Gems / Life Orb** | `protocol.py: move()` (about lines 840–900)| used a status move ⇒ `impossible_items += assaultvest`; used an attacking move of some type ⇒ `impossible_items += {type}gem`; used an attacking move and the ability is not Sheer Force / Magic Guard ⇒ Life Orb excluded |
| **Heavy-Duty Boots** | `inference.py: check_heavydutyboots` | Switched in with Stealth Rock / Spikes / Toxic Spikes / Sticky Web up but took no matching damage / poison / Speed drop ⇒ judged to hold Boots; took damage ⇒ added to `impossible_items` |
| **Leftovers / Black Sludge / Flame & Toxic Orb** | `protocol.py: upkeep()` (about lines 2190–2204)| HP < max at end of turn ⇒ Leftovers / Black Sludge excluded; no status ⇒ Flame / Toxic Orb excluded |
| **Ability** | `protocol.py: switch_or_drag` (about lines 430–480), `immune`, `update_ability` | "On-entry abilities" that did not trigger on switch-in are added to `impossible_abilities` (weather / Intimidate etc. under conditions); `-immune` and `-ability` messages set it directly |
| **Weather duration ⇒ item** | `protocol.py: weather()` (lines 1302–1417)| Weather counts as 5 turns by default; not ended when due ⇒ 3 more turns, and if the weather came from the opponent and its item is unknown, it is presumed to hold the matching weather-extending rock (Heat / Damp / Smooth / Icy Rock, `pkmn.item = item`); when the rock is known, 8 turns |
| **Hidden Power type** | `inference.py: check_opponent_hiddenpower` | narrows `hidden_power_possibilities` by the effectiveness (resisted / super effective / neutral) |
| **Tera type** | `protocol.py: terastallize()` (1098)| on `-terastallize`, writes `tera_type`; in `set_makes_sense`, if already Terastallized and the candidate's tera differs, it is eliminated |
| **Zoroark / Illusion** | `modes/base.py: _switch_active_with_zoroark_from_reserves`, `protocol.py: illusion_end` | "inferring Zoroark from moves" only in Battle Factory mode; standard mode relies on the `-end Illusion` message to correct |

**Fallback**: if `_do_check` would eliminate all candidates it eliminates none (`"Would remove all possibilities, not removing any"`); in standard battle mode the complete set library has `allow_emptying=True` (`modes/standard_battle.py: dataset_possibilities` returns `True`); once it is emptied, sampling moves to the fallback path; the Smogon trait library is never emptied.

**Limitations**: this is **hard elimination on a discrete set**, with no likelihood / Bayesian update; "why the opponent chose this move" (behavioral information) is hardly used to infer sets, only "what appeared"; the damage back-calculation depends on the fidelity of the engine's damage calculation.

### 2.4 Sampling "complete worlds" (`fp/search/standard_battles.py`)

`prepare_battles(battle, num_battles)` (line 296): `num_battles` iterations, each `deepcopy(battle)`, calling `sample_pokemon` on **the opponent's active and all living reserves**, finally `opponent.lock_moves()`, each world weighted `1/num_battles`. Older generations without team preview (Gen1–4) additionally fill in unseen teammates with `populate_standardbattle_unrevealed_pkmn`: `predict_team_likelihood` uses Smogon's `Teammates` co-occurrence counts, ranks by the mean conditional probability given the seen members, and samples weighted from the top 50. **Gen9 OU has team preview, all 6 are known, this path is not used.**

Per-Pokémon `_sample_pokemon` (line 168), three levels of fallback:
1. All sets in the **complete set library** consistent with the current observations (`get_all_remaining_sets`: ability / item / speed range / tera checks + the known moves are a subset of the set). If non-empty and (no move seen yet **or** with 75% probability, `random.random() < 0.75`) -> `random.choice`, **uniform sampling, not weighted by count** (comment: the counts do not reflect the real distribution).
2. The complete library still has sets whose "traits are logically sound" but whose moves conflict -> sample a trait set, then fill in moves with `sample_pokemon_moveset_with_known_pkmn_set`: first from the replay move-combination library weighted by count (combinations containing more known moves weighted ×2/×3), then, if still short of 4 moves, filled from Smogon move usage, the usage corrected by `adjust_probabilities_for_sampling`: `1-(1-rate)^(1/num_moves)` as an approximate "choose k without replacement" probability correction.
3. Fall back to **Smogon trait combinations** (`get_all_remaining_trait_combinations` + `get_filtered_smogon_sets`) weighted by the product count, then fill in moves.

Other: `pokemon_guaranteed_move` (moves forced by species, e.g. Zacian), `set_most_likely_hidden_power`, Mega (only Gen6/7/NatDex/Champions).

### 2.5 Sample count and time budget

- Number of sampled states = `--search-parallelism` (`modes/standard_battle.py: search_params`, line 136); **×2 at team preview, when the opponent's active has <3 known moves, or when it has HP but 0 known moves**, unless `time_remaining ≤ 60 seconds` (parsed from `|inactive|` messages, `protocol.py: inactive`), in which case it is not doubled.
- Each state is searched for `--search-time-ms`; the process pool is `ProcessPoolExecutor(max_workers=parallelism)` (`search/main.py:71`), **so with sample count = 2×parallelism the work runs in two serial batches ⇒ the actual time is about 2×search_time (`[UNVERIFIED]`, inferred from the code, not measured)**.
- The author's advice: about 7 seconds per move, diminishing returns beyond parallelism 8 `[self-reported, Smogon thread]`; one user reached 1930+ on the gen9ou ladder with a "7000+14" setting `[second-hand]`; another user in issue #346 used "7s/8 states".
- Aggregation (`select_move_from_mcts_results`, `search/main.py:16`): for each world, the **visit share** of each `side_one` action, multiplied by `1/N` and summed; candidates ≥ 75% of the top one are kept, then **one is drawn at random weighted by probability** (a touch of mixed strategy, harder to predict).

---

## 3. Search

### 3.1 Algorithm: Decoupled UCT (DUCT) MCTS, root-parallel over sampled worlds

- Foul Play **uses only MCTS**: `search/main.py: get_result_from_mcts` calls `poke_engine.monte_carlo_tree_search(state, search_time_ms, threads=threads)`. The engine still has expectiminimax / iterative deepening (`src/search.rs`, Python `iterative_deepening_expectiminimax`, CLI), but Foul Play does not call them.
- The engine's single-threaded version `src/mcts.rs`: each node keeps **a separate `MoveNode{total_score, visits}` per side** for s1/s2 (`s1_options`/`s2_options`); in selection each side **independently** takes `argmax UCB1` (`maximize_ucb_for_side`), giving the joint action `(i,j)`; that joint action maps to a set of chance-outcome nodes (`children: HashMap<(parent_ptr, i, j), Box<[Node]>>`), one outcome is sampled by probability to continue down (`sample_node`). This is DUCT: no payoff matrix is built and no statistics are kept on joint actions, only on marginal actions.
- UCB1: `avg + sqrt(2·ln(N_parent)/n)` (`mcts.rs:213 MoveNode::ucb1`). The s2 side accumulates `1 - score` (`backpropagate`). **No priors, no temperature, no PUCT.**
- **No rollout**: `Node::rollout` (`mcts.rs:190`) returns 1/0 if the battle is over, otherwise `sigmoid(evaluate(state) - root_eval)`, `sigmoid(x)=1/(1+exp(-0.0125x))` ("~200 points ≈ 1.0"). That is, **one expansion + one static evaluation**, the evaluation taken relative to the root's baseline.
- After each iteration, `reverse_instructions` undoes the state changes -- **no state copies** (see 4.2).
- Parallelism:
  - The main parallelism is **root-parallel in the Python layer**: one process per sampled world (`ProcessPoolExecutor`), each with its own tree. (The engine's PyO3 bindings do not release the GIL: no `allow_threads`/`detach` in `poke-engine-py/src/lib.rs` -> hence multiprocessing.)
  - Engine ≥0.0.47 (2026-06-13, commit `e8bda75` "Multi-threaded search") added a multi-threaded version with **a shared tree + virtual loss (`VIRTUAL_LOSS_VISITS=3`)**, `src/mcts_threaded.rs: perform_mcts_shared_tree` (a global `DashMap` child table), which Foul Play enables via `--search-threads`. **The engine at competition time (2025-10/11) was v0.0.46, presumably single-threaded `[inferred, UNVERIFIED]`**, so the paper's "root-parallelized" refers to parallelism across worlds.
- Iteration budget: Python binding `monte_carlo_tree_search(state, duration_ms, iterations=0, threads=1)`; with `iterations>0` a fixed iteration count is used (usable for **reproducible evaluation**); with only 1 legal action, `iterations=100` is forced for a quick return (`poke-engine-py/src/lib.rs: mcts`); a single tree is capped at 10,000,000 iterations. Time is checked every 1000 iterations.
- Depth: the blog / paper say promising lines go 10+ turns, the rest 2–3 turns (versus the old expectiminimax, which in practice reached only ~5 turns) `[self-reported]`. Engine README example: 100ms single-threaded about 25,000 iterations (`README.md` "monte-carlo-tree-search" example, hardware not stated, **not measured**).

### 3.2 expectiminimax / iterative deepening (kept in the engine, not used by Foul Play)

`src/search.rs`: `expectiminimax_search` expands every instruction branch for each (s1,s2) action pair; subgames use `pick_safest` (**pure-strategy maximin: for each of our actions take the opponent's worst response, then the maximum**); optional alpha-beta pruning; `iterative_deepen_expectiminimax` uses a thread + `sleep(max_time)` as the stop signal, returns the previous depth's result, and reorders our actions by the previous round's worst payoff. **maximin is not a mixed-strategy Nash equilibrium and is too pessimistic for "guessing games"**, one of the reasons the author moved to MCTS.

### 3.3 Evaluation function (`poke-engine/src/genx/evaluate.rs`, shared by Gen4–9; Gen1/2/3 each have their own file)

`evaluate(state) = Σ(ours alive) − Σ(theirs alive)` plus a few field terms. The constants (all from that file):

| term | value | note |
|---|---|---|
| living Pokémon `POKEMON_ALIVE` | +30 | **independent of species** (no distinction between core and filler)|
| HP `POKEMON_HP` | +100 × hp/maxhp | |
| holding an item | +10 | any item counts, regardless of kind |
| status | freeze −40; sleep −25; paralysis −25; toxic −30; poison −10; burn = −25 × (number of physical moves), halved if Sp. Atk > Atk; Poison Heal +15; Guts / Marvel Scale / Quick Feet / Toxic Boost / Magic Guard when poisoned +10; Guts / Marvel Scale / Quick Feet when burned = +50 | `evaluate_poison`, `evaluate_burned` |
| per-Pokémon score floor | `score<0 → 0`, then +30 | keeps low-HP Pokémon from scoring negative, which would push the opponent to keep them alive |
| stat boosts (active only) | Attack ×30, Sp. Atk ×30, Speed ×30, Defense ×15, Sp. Def ×15, times `boost_multiplier`: +6=3.3, +5=3.15, +4=3.0, +3=2.5, +2=2.0, +1=1.0, 0=0, −1=−1.0, −2=−2.0, −3=−2.5, −4=−3.0, −5=−3.15, −6=−3.3 | nonlinear, symmetric |
| Leech Seed | −30 | active |
| Substitute | +75 | active (the Gen9 engine's `misc: substitute 40→75` shows the tuning)|
| confusion | −20 | active |
| Stealth Rock / Spikes / Toxic Spikes / Sticky Web | −10×layers / −7×layers / −7×layers / −25 | summed over every living Pokémon; Heavy-Duty Boots immune; Magic Guard immune to Rocks and Spikes; Spikes / Toxic Spikes / Web only for grounded Pokémon |
| Reflect / Light Screen / Aurora Veil / Safeguard / Tailwind / Healing Wish | +20 / +20 / +40 / +5 / +7 / +30 (× the turns / layers field)| positive for our side, negative for theirs |
| **Terastallized (`USED_TERA`)** | **−75** (−75 if we used it, +75 if they did)| favors "keeping tera"; changelog "Tera penalty 50 → 75" |
| game end | our win = 1, loss = 0 (MCTS node value); expectiminimax uses `±100×remaining depth + evaluate` | |

**Key observation**: no "species value", "win condition", "replaceability", "turn count / tempo", no modeling of "whether there is Rapid Spin / Defog" or "whether a key type resistance is present"; the evaluation is **a pure linear heuristic of material + status + field**, relying on search depth to make up for it. All weights were "hand-tuned from an understanding of the metagame and tested by self-play" `[self-reported, Smogon thread]`.

### 3.4 Randomness and branch compression (`src/genx/generate_instructions.rs`)

Core interface: `generate_instructions_from_move_pair(state, s1_move, s2_move, branch_on_damage) -> Vec<StateInstructions>` (line 4035). Each outcome is `StateInstructions{percentage, instruction_list}`, percentages summing to 100.

- **Damage roll grouping** (`generate_instructions_from_move`, line 2023; the damage branches about 2391–2470): the 16 rolls are not enumerated. With `max_damage` the engine's maximum damage, `avg = ⌊0.925·max⌋`, `min = ⌊0.85·max⌋`:
  - if `branch_on_damage` and `max ≥ the target's current HP > min` (a possible KO): split into a "KO branch" (probability `(1−crit)·kill_rolls/16 + crit`, damage = the target's current HP) and a "no-KO branch" (damage = the mean of the non-KO rolls, `compare_health_with_damage_multiples`);
  - if `branch_on_damage` and `max < HP`: split into a crit branch (probability `crit_rate`, damage `0.925·crit max`) and a normal branch (`0.925·max`);
  - otherwise: average damage only, **no crit branch** (except for moves that always crit).
  - Crit rate: Gen4–6 1/16; Gen7+ (including Gen9) 1/24 (`BASE_CRIT_CHANCE`); high-crit moves 1/8; Battle / Shell Armor 0.
- **Branch depth**: single-threaded MCTS branches on damage only at **the root and its children** (`mcts.rs:143 should_branch_on_damage = self.root || (*self.parent).root`); the shared-tree version at `depth < MCTS_DAMAGE_BRANCH_DEPTH(=2)`. Deeper nodes use average damage only, saving branches.
- **Hit / miss**: `check_move_hit_or_miss` (line 1194) branches by `accuracy × accuracy stage`; **secondary effects** (stat drops, status, flinch, etc.) branch by probability (`secondary.chance`, about lines 1059–1075); multi-hit moves approximate with a fixed hit count ("Average is 3.2 so this is a fine approximation", about line 2368); "branching is not implemented here so the engine assumes it always lasts 3 turns" (about line 3266, probably Outrage / sleep).
- **Priority / Speed / speed ties**: `moves_first` (line 2593): switches first (switching goes before moves, Pursuit excepted) -> priority -> Custap Berry -> effective Speed (`get_effective_speed`, with weather / terrain abilities, Tailwind, paralysis, Scarf, boosts, Trick Room reversal) -> **equal Speed ⇒ `SideMovesFirst::SpeedTie`, a 50% branch for each side** (line 4270).
- **Consecutive Protect**: `CONSECUTIVE_PROTECT_CHANCE = 1/3` (Gen6+), success probability `(1/3)^n` (about line 2009).
- **Simultaneous moves**: handled by DUCT at the "selection" level; switches / forced switches (`force_switch`), switching after U-turn (`slow_uturn_move`, `switch_out_move_second_saved_move`) are modeled with side flags.
- `remove_low_chance_instructions` is a compile feature (off by default) that drops low-probability branches.

### 3.5 Known theoretical weaknesses

1. **Determinization**: inside each sampled world the game is **a perfect-information game**; the search treats "the opponent's sets" as known to both sides; hence it cannot value "information / bluffing", and strategy fusion occurs. Summing visit counts across worlds is only an approximate average at the root.
2. **The opponent is "the same DUCT player"**, not a model of human behavior; no prior on "lines humans commonly play".
3. **Shallow evaluation** (see 3.3), poor judgment of stall / recovery loops / preservation (long-term resources) -- the author admits "Long term decisions are hard to reason about with a search based engine that can only see perhaps 10 turns ahead", "underestimates moves like toxic" `[self-reported]`.
4. **UCB1 + DUCT is not guaranteed to converge to Nash in games**; the final "75% threshold + weighted random" mixing is an engineering measure, not a theoretical guarantee.
5. **Damage averaging**: deeper nodes use the average roll only, inaccurate for "low-HP endgames that need exact rolls"; KO branches only near the root.
6. **Set filtering is hard elimination**: once an inference rule errs (e.g. excludes a rare set), later worlds lack that possibility forever; there is a fallback but no soft weights.
7. **"Exploitable if the opponent knows it is playing a bot"** `[self-reported]`.

---

## 4. poke-engine in detail

### 4.1 Overview

- Repository `pmariglia/poke-engine`, **MIT** (`LICENSE`, Copyright 2024 pmariglia; `Cargo.toml` `license-file`; GitHub SPDX=MIT). Version 0.0.48 (2026-07-19), same version on PyPI, **sdist only** (`poke_engine-0.0.48.tar.gz`), so any install compiles locally.
- About 62.7k lines of Rust (`src/choices.rs` 20.7k lines of hand-written move table, `genx/generate_instructions.rs` 10.9k, `genx/abilities.rs` 2.9k, `genx/items.rs` 1.5k, `genx/choice_effects.rs` 1.8k, `genx/damage_calc.rs` 1.1k); about 1,054 `#[test]` (`src/` + `tests/`).
- Very few dependencies: `dashmap`, `clap`, `rand` (`Cargo.toml`); Python bindings `poke-engine-py` (PyO3 0.29, built with maturin, `pyproject.toml`: `requires = maturin>=1.0,<2.0`).

### 4.2 State representation and the "instruction" system

- `State` (`src/state.rs:1321`): `side_one`/`side_two`/`weather`/`terrain`/`trick_room`/`team_preview`/`use_last_used_move`/`use_damage_dealt`.
- `Side` (1056): a fixed 6 Pokémon × 4 moves (`pokemon: SidePokemon`), `active_index`, side_conditions, `volatile_statuses` (bitset), `volatile_status_durations`, **stat boosts stored on the Side, not on each Pokémon** (cleared on switching, as the rules say), `substitute_health`, wish, future_sight, `last_used_move`, `damage_dealt` (for Counter / Mirror Coat), etc.
- `Pokemon` (`src/state.rs:852`): id/level/types/base_types/hp/maxhp/ability/base_ability/item/nature/evs/the five final stats/status/rest_turns/sleep_turns/weight/`terastallized`/`tera_type`/`mega_evolved`/moves. Species, moves, abilities and items are all **compile-time enums** (`PokemonName`, `Choices`, `Abilities`, `Items`); an unknown species just `panic!("Base stats not implemented for …")` (`genx/base_stats.rs:128`) -- meaning **new species / moves need a new engine release**.
- Serialization: `State::serialize/deserialize` (the doctest in `state.rs` is the format's ground truth, from about line 2238); in Python `State.from_string/to_string`.
- **The instruction system**: `generate_instructions` does not return new states but `Vec<StateInstructions>`, each with a probability and a `Vec<Instruction>` (`src/instruction.rs`: Switch, Damage, Heal, Boost, ChangeStatus, ChangeSideCondition, ChangeWeather, ChangeItem, DecrementPP, ToggleTrickRoom… about 50 kinds). `State::apply_instructions` / `reverse_instructions` apply and undo in place ⇒ zero-copy search tree traversal (the blog says the same). Both the CLI and Python expose `generate_instructions(state, s1_move, s2_move)`.

### 4.3 Generations and mechanics coverage

- Compile features select the generation exclusively (`Cargo.toml`: `gen1`…`gen9`, `terastallization`(→gen9), `champions`, `bss`). `gen1/2/3` have their own directories; `genx/` (Gen4–9) is shared, with `cfg` distinguishing them (crit rate, Protect probability, sleep turns, etc.). The Makefile target `tera` = `gen9,terastallization`; Foul Play's pin for Gen9 is `poke-engine/terastallization` (`requirements.txt`). Note **`gen9` and `terastallization` are two features**; `gen9` alone has no tera (`genx/state.rs:1069` `can_use_tera()` returns false; only the `#[cfg(feature="terastallization")]` version returns "this side has no Terastallized Pokémon yet").
- Gen9 specifics: Terastallization (the `MoveTera(idx)` action; Tera Blast, STAB 2.25 and Adaptability, "BP floor of 60 for Tera-type moves", Stellar, Revelation Dance etc., see the Tera entries in `CHANGELOG.md`), ~298 abilities (counted in `genx/abilities.rs`), ~1.5k lines of item logic, Protosynthesis / Quark Drive, Booster Energy, etc.
- The README says plainly **"This is not a perfect engine"**, "nowhere near as complete or robust as PokemonShowdown".

**Known gaps / approximations (from code comments and open PRs / issues)**:
- Trapping (Mean Look / Block / Spider Web) not implemented (open PR #15); Protect fix (#12); sleep moves (#14); Doom Desire (#17); Substitute HP not cleared on switching (#22); Destiny Bond's final mutual-KO check (issue #6).
- Multi-hit moves use a fixed hit count; some durations use fixed values; `damage_dealt`/`last_used_move` need the `use_*` flags; opponent Illusion, Transform etc. need special handling in the Foul Play client; Substitute HP is approximated by the client (`poke_engine_helpers.py: battler_to_poke_engine_side`: "1/10 max HP if hit else 1/4").
- The opponent's Tera type **is known** in a sampled world (set by the sampling), not a hidden variable.
- The compression into average damage + KO / crit branches makes the engine **not point-wise equivalent to Showdown** but an approximation that preserves expectations.

### 4.4 Data sources

- The engine's `choices.rs` (move table), `abilities.rs`, `items.rs`, `base_stats.rs` are **hand-written / semi-hand-written Rust source**; whether a generator script exists is not in the repository `[UNVERIFIED]`.
- Foul Play's `pokedex.json`/`moves.json` are synced daily from `smogon/pokemon-showdown` automatically (2.1 above); but **the engine's enums are not updated automatically**; the two meet through Foul Play's `poke_engine_helpers.py` via string ids.

### 4.5 Rust / Python API

Python package `poke_engine` (`poke-engine-py/python/poke_engine/__init__.py` + `poke_engine.pyi`):
- data classes: `State`, `Side`, `Pokemon`, `Move`, `SideConditions`, `VolatileStatusDurations`;
- `monte_carlo_tree_search(state, duration_ms=1000, iterations=0, threads=1) -> MctsResult` (with `visits`/`total_score` for each s1/s2 action, `total_visits`);
- `iterative_deepening_expectiminimax(state, duration_ms)`;
- `generate_instructions(state, s1_move, s2_move) -> list[StateInstructions]`; `State.apply_instructions/reverse_instructions`;
- **`calculate_damage(state, s1_move, s2_move, s1_moves_first) -> (rolls_s1, rolls_s2)`** -- usable directly as **a Python damage calculator** (Foul Play's damage back-calculation uses it).
- Rust public API (`src/lib.rs`): `state`, `mcts`, `mcts_threaded`, `search`, `io` (CLI parsing), `instruction`, `choices`. Library name `poke_engine`, usable as a `cargo` dependency.
- Build requirements: a Rust toolchain (the Dockerfile uses `rust:1.89`; `LazyLock` needs ≥1.80; this machine has `rustc 1.95.0` installed), maturin. Per-generation build: `pip install … --config-settings="build-args=--features poke-engine/terastallization --no-default-features"`.

### 4.6 Performance and benchmarks

- The repository has a benchmark program `data/benchmark.rs` (`cargo run --release --bin benchmark -f gen9randombattle.txt -i 250000 -n <threads>`), fed a number of state strings from `data/gen9randombattle.txt`; **no published nodes/s number in the repository**. The only number: the README example `-t 100` ⇒ "Total Iterations: 25000" (on the order of 250k per second per thread, hardware unknown). **Not measured this time (task constraints)**. The CHANGELOG has several "MCTS Performance Improvements" / "Performance" entries: performance is an ongoing optimization item.
- The `Cargo.toml` release profile only has `debug = 1`, no LTO / codegen-units set: room for further speedup `[inferred]`.

### 4.7 Correctness tests: checked against Showdown?

- `grep -ri showdown tests src poke-engine-py/python` gives **zero hits**: **no consistency / differential tests against Showdown**. The tests are hand-written unit tests (`tests/test_battle_mechanics.rs`, `test_damage_dealt.rs`, `test_gen1/2/3.rs`, `test_bss_mechanics.rs`, about 1,054 inline `#[test]` in `src/**`) and Python `poke-engine-py/python/tests/test_poke_engine.py`.
- Foul Play has `tests/test_poke_engine_serialization.py`, which only tests the serialization round trip.
- Conclusion: **fidelity rests on "the author hand-writing Showdown's behavior + fixing bugs found in play"**; outside contributors (Henauxg, SPGesus, kelvinfkr, etc.) keep adding mechanics fixes.

### 4.6a Multithreading

See 3.1: single-threaded `perform_mcts`; multi-threaded `perform_mcts_shared_tree` (shared `DashMap` children, virtual loss, atomic scoring). Python calls do not release the GIL.

---

## 5. Strength and evidence

### 5.1 Ladder results (by format, self-reported vs external)

| format | GXE | peak Elo | peak rank | source / reliability |
|---|---|---|---|---|
| **Gen9 OU** | 80% | 1879 | Top 100 | blog, `[self-reported]`; paper appendix E.1.2 repeats "over 80% GXE … (peak rating 1879)" `[self-reported, written by the author]` |
| Gen9 OU (Smogon thread summary) | — | "≈1930+, Silver Badge" | — | a claim in the thread; whose it is (the author or a user) the summary leaves unclear, and it disagrees with the blog's 1879 `[self-reported/second-hand, conflicting]` |
| Gen9 OU (third-party account) | 51.5% | 1190 | — | search result summary: the current numbers of the account `FoulPlay-Jp-Bot` on its pokemonshowdown.com user page; configuration / team / search time unknown, **not representative of the tuned ceiling `[UNVERIFIED]`** |
| Gen5 OU | 76% | ~1600 | Top 200 | blog `[self-reported]` |
| Gen3 OU | 71% | 1815 | #4 | blog `[self-reported]`; the author calls it "a lucky run" in the thread |
| Gen9 Random | 88% (the paper says "over 90%") | 2341 | Top 50 | blog / paper, **the two numbers disagree** `[self-reported]` |
| Gen9 Random Blitz | 84% | 2018 | #1 | blog |
| Gen9 Battle Factory | 81% | 1624 | #1 | blog |
| Gen9 LC | ~76–77% | peak 1486 (Top 50)| — | results of **someone else** using Foul Play, in a Smogon discussion thread, reporting 11 losses to disconnects `[external/second-hand]` |

(All GXE values are estimates after the Glicko deviation is <50, see the blog's footnote.)

### 5.2 PokéAgent Challenge (NeurIPS 2025) `[external: the organizers' paper; its appendix E written by the participants]`

- Gen9 OU: FoulPlay was the qualifier's **#1 seed**, "outperformed private baselines by all metrics" (paper B.2); Q, PA-Agent, piploop were the "chasing pack", between the best public baseline and the best private baseline.
- Knockout stage (B.3): each pairing bo99 (first to 50 wins). **Final: FoulPlay 50–14 Team Q**; the semifinal was a "close match" against PA-Agent (the exact score is in figure 9, not given in the text, not extracted this time).
- 13 of the 16 qualifying slots went to extensions of the organizers' public RL baselines (the Metamon family); **FoulPlay (Gen9 #1, Gen1 #8) and Porygon2AI (Gen9 #8) are independent approaches**.
- Team Q (runner-up): a 50M-parameter Actor-Critic, a two-stage curriculum (Mechanics Phase against heuristic bots -> Strategy Phase self-play against a fixed "coach" and past versions).
- Baseline reference (paper Table 1, GXE against the human ladder): Metamon Abra (57M, Gen9) 50%; Kadabra3 (57M, Gen9) 64%; Kakuna (142M, 2025-12, Gen9) 71%. FoulPlay self-reports 80%, **but the two are not the same yardstick** (the organizers' FH-BT differs from Showdown GXE; the opponent pools differ).
- The paper **gives no FH-BT / Elo value for FoulPlay in the text** (only figures 6/8, not extractable as text) `[UNVERIFIED]`; the competition team, search time / parallelism and hardware are not in the paper `[UNVERIFIED]`.
- What the comparison means: these are **games against RL / LLM bots on the same AI-only ladder**, not the same as against strong humans.

### 5.3 Known weaknesses

- Defensive / stall teams, long-term decisions (the search sees about 10 turns), moves with delayed payoff (Toxic) `[self-reported]`; abilities like Unaware not handled explicitly, team-size handling bug issue #264 (team size in formats without team preview).
- In older generations without team preview (Gen3), its prediction of hidden Pokémon is "unscientific" (Smogon thread summary).
- Crash issues in play: Revival Blessing crash (#244), new Mega forms crash in natdex (#351), an opponent's `/hideroom` renames the room and commands go to the wrong room (#323, **irrelevant to a local server**).
- Compared with Metamon: Metamon is purely learned, no search, better at modeling "behavior / human style"; Foul Play is search + heuristics, stronger at "exact mechanics calculation and information inference", weaker at "strategic long-term plans / stall". The paper's conclusion: "specialist RL and search methods outperform LLM approaches".

### 5.4 Which teams it uses

The repository has only 1 sample Gen9 OU team (see 1.7); the paper / forum did not publish the competition teams. **No team selection / optimization logic**. -> Directly for us: as an evaluation opponent, **we decide its teams**, and its strength depends on how well the team fits its "offense-friendly" preference.

---

## 6. Practical use

### 6.1 Installation requirements

- Python ≥3.11 (README; CI / Docker use 3.13); a Rust toolchain; `requirements.txt`: `requests==2.33.0`, `websockets==14.1`, `python-dateutil==2.8.0`, `poke-engine==0.0.48 --config-settings="build-args=--features poke-engine/terastallization --no-default-features"`.
- **Conflict with our project**: poke-env 0.16.1 depends on `websockets==16.1.1`, `gymnasium==1.3.0`, `numpy>=2.0.2`, `orjson`, `pettingzoo` (checked in the PyPI metadata); Foul Play pins `websockets==14.1`, `python-dateutil==2.8.0`. **A separate virtual environment is required** (e.g. in `~/tools/foul-play/.venv`), not installed into the project venv. The project has `requires-python >=3.12`, this machine Python 3.14.4: whether Foul Play works on 3.14 (including the PyO3 0.29 build) `[UNVERIFIED]`; suggested: have uv use 3.13 (matching its CI / Docker).
- **uv compatibility `[UNVERIFIED]`**: the "inline `--config-settings`" in requirements.txt is pip syntax; uv's equivalent option is `-C/--config-setting`, suggested form `uv pip install "poke-engine==0.0.48" -C "build-args=--features poke-engine/terastallization --no-default-features"`, then `uv pip install requests websockets==14.1 python-dateutil`. Needs testing.
- The Docker path works: `make docker GEN=gen9` (the Dockerfile replaces the requirements' feature with `poke-engine/${GEN}`; **note GEN=gen9 builds an engine without tera, pass `GEN=terastallization`**; the README example is `gen4`, the right value for Gen9 `[UNVERIFIED]`).
- Build time: 20k+ lines of Rust in large match tables, a release build expected to take several minutes `[UNVERIFIED, not compiled]`.

### 6.2 Resources and latency

- The author says "16GB RAM + a mid-range 4-core CPU from nearly 5 years ago" is enough `[self-reported]`. Our machine is a multi-core AM5 (10 logical cores visible in WSL) / 64GB; the GPU is not used.
- Time per move ≈ `search_time_ms × ⌈sampled states / parallelism⌉` + Python overhead (per move a `deepcopy(Battle)`, a new process pool, serializing State strings); the overhead's size is **not measured**. With `--search-time-ms 1000 --search-parallelism 8`, an estimated 1~2 seconds per move; the "full" 7000ms×14, about 7~14 seconds (may exceed Showdown's local timer; needs a `--timer` setting).
- **Evaluation fairness**: Foul Play's search is **time-based**; CPU taken by other load (our benchmarks / training) directly lowers its strength; for evaluation, pin cores (`taskset`) or switch to an iteration budget (needs our own change to `search/main.py` to pass `iterations` to `monte_carlo_tree_search`; the Python binding already supports the parameter).

### 6.3 Running against a local Showdown (**not executed, steps only**)

Precondition: the local Showdown port **avoids 8000–8003** (currently used by the benchmarks; and Foul Play's `local` shorthand hard-codes 8000, so give the full URI explicitly).

```bash
# 1) a separate environment (not the project venv)
uv venv --python 3.13 ~/tools/foul-play/.venv
cd ~/tools/foul-play && git clone https://github.com/pmariglia/foul-play && cd foul-play
uv pip install -p ~/tools/foul-play/.venv "poke-engine==0.0.48" \
   -C "build-args=--features poke-engine/terastallization --no-default-features"   # [UNVERIFIED syntax]
uv pip install -p ~/tools/foul-play/.venv requests==2.33.0 websockets==14.1 python-dateutil==2.8.0

# 2) warm the data caches (online once): first fetch, by any networked means other than Showdown
#    https://data.foulplay.cc/gen9ou/{pokemon_full_sets,replay_moves}.json
#    https://play.pokemonshowdown.com/data/sets/gen9ou.json
#    https://www.smogon.com/stats/<last month>/chaos/gen9ou-0.json
#    into fp/data/pkmn_sets_cache/gen9ou/ and fp/data/smogon_stats_cache/ (file names: see get_sets_file / _get_smogon_stats_json)

# 3) as the challenged opponent (our poke-env player challenges it)
python run.py \
  --websocket-uri ws://localhost:<PORT>/showdown/websocket \
  --ps-username FoulPlayBot --bot-mode accept_challenge \
  --pokemon-format gen9ou --team-name gen9/ou \
  --search-time-ms 1000 --search-parallelism 8 --run-count 200
# 4) or have it challenge us: --bot-mode challenge_user --user-to-challenge <our username>
```

Points to handle:
1. **Login patch**: `PSWebsocketClient.login()` unconditionally fetches an assertion from `play.pokemonshowdown.com`. For local offline use, `login()` should send `/trn <name>,0,` instead for `ws://localhost` (poke-env does exactly this for a local server). Whether a local server also accepts this when online `[UNVERIFIED]`.
2. `accept_challenge` accepts a challenge from **any** user whose format matches exactly (`websocket_client.py: accept_challenge`, parses `|pm|` and `split_msg[5] == battle_format`).
3. Teams: `--team-name gen9/ou` (a folder: one drawn at random per game; `--team-list` can rotate instead). For fair games, **both sides should use the same team pool and swap teams**.
4. Foul Play sends `hf`/`gg` chat and `/timer on` itself; the local server's timer policy affects it (it halves the sample count only when `time_remaining ≤ 60`).
5. Local Showdown games loop per `--run-count`; `leave_battle` after each game.
6. Never connect it to the public server / ladder for testing (task constraint).

**Local fixes (2026-10-09, changes only to the code in `external/foul-play`, not in this repository; the patch is `external/foul-play-local-fixes.patch`, not yet fixed upstream as of 8f541f8)**:
- Field parsing: `fieldstart` / `fieldend` in `fp/battle/protocol.py` store every field effect other than Trick Room and Gravity as terrain; when the position is handed to poke-engine, `get_terrain_string` raises `ValueError` on `magicroom` (Magic Room and the like), and the process exits. Changed to: only the four real terrains are stored as terrain, other field effects are logged and ignored (poke-engine does not simulate them anyway; the same as our `engine_state.py`); their end is likewise ignored and does not clear a terrain that is up at the same time.
- When `fp/search/main.py` prints the search result, a chosen option with 0 visits divides by zero (`ZeroDivisionError`); changed to divide by max(visits, 1).
- This only affects games that used to crash; in all other games Foul Play's behavior is unchanged, so results before and after the fix are comparable. First exposed by: the Foul Play evaluation on the off-meta pool (`offmeta200`), where 2 of 8 lines crashed because of it.

### 6.4 Can it be called as a library?

**It is not designed as a library**: `FoulPlayConfig` is a global singleton filled by `argparse` from `sys.argv` (`config.py: configure`), the datasets are process-wide singletons in the mode objects (`BattleMode.__deepcopy__` returns self, `modes/base.py`), `apply_mods` rewrites the global `pokedex`/`all_move_json` in place (`main.py: check_dictionaries_are_unmodified` does `exit(1)` when they are changed). Technically one can set `FoulPlayConfig.*` by hand and call `fp.search.main.find_best_move(battle)` directly (the tests' `conftest.py` does exactly that), feeding poke-env's raw messages to `fp.battle.protocol.async_update_battle`, but: (a) this is **an import of GPL code** (see section 8); (b) the global state makes running games in parallel hard. **Recommended: "a separate process + websocket"**.

---

## 7. Code quality and maintenance

| item | foul-play | poke-engine |
|---|---|---|
| latest commit | 2026-10-03 (the bot's daily data sync PR #352); latest human commit 2026-09-06 | 2026-10-03 |
| created | 2019-03 | 2020-03 |
| stars / forks | 383 / 222 (API, 2026-10-04) | 52 / 27 |
| contributors (GitHub contributors API) | pmariglia 815; github-actions[bot] 38; Andyloris 15; jpf4e 6; … | pmariglia 880; jpf4e 5; Henauxg 3; kelvinfkr 2; SPGesus 2 |
| open issues / PRs | 5 issues (#351 natdex new Mega crash, #323 /hideroom renames room, #264 team size, #244 Revival Blessing crash, #3 old KeyError)| 7 (including 6 community mechanics-fix PRs + #6 Destiny Bond)|
| activity | still frequent in 2026 (Champions / BSS refactor `a338d59`, 2026-07)| 68 commits since 2026-01; v0.0.47 -> v0.0.48 in one month |
| tests | ~737 pytest; CI (ruff+pytest)| ~1,054 Rust tests; CI runs `make ci` (all of it per generation feature)|
| releases | no GitHub Releases; depends on a pinned PyPI engine version | CHANGELOG (git-cliff), PyPI sdist |

The maintainer is essentially **a one-person project** (bus factor 1), but extremely active; recent work focuses on the new Champions / BSS formats, Gen9 OU fixes still continue (e.g. "lifeorb requires at least a little bit of offensive investment", 2026-07). One signal worth noting: in issue #346 (2026-08) someone is building their own bot on poke-engine and wants stock foul-play as a calibration baseline -- the engine is already used as a third-party search base. An outside example: **Laplace** (trylaplaceai.com, Gen9 Random, self-reported Elo 2231 / GXE 83.3) states "search design starts from Foul Play", tracks state with poke-env, samples 8 worlds and calls poke-engine MCTS for ~150ms each, then uses a small 368-feature network to rerank only the 5–10% of turns that are "near ties" `[self-reported, web page summary]`.

---

## 8. License and reuse analysis (not legal advice)

| component | license | basis |
|---|---|---|
| Foul Play (`fp/`, `run.py`, etc.) | **GPL-3.0** | the repository's `LICENSE` (full GPL v3 text); GitHub SPDX=GPL-3.0; the README says nothing else |
| poke-engine (Rust + Python bindings) | **MIT** | `LICENSE`; Cargo `license-file`; GitHub SPDX=MIT (the PyPI metadata's `license` field is empty)|
| `data.foulplay.cc` data | **not stated** `[UNVERIFIED]` | the author's S3 site, no data license statement in the repository |
| Smogon monthly stats | public data (no explicit license) | smogon.com/stats |
| Showdown data (`pokedex.json` etc.) | Showdown is MIT | `smogon/pokemon-showdown` |

**What this means for us** (assuming our project is not eventually released under the GPL):

1. **As an evaluation opponent in a separate process** (connecting to our local server over websocket): **safe**. Running a GPL program and communicating with it does not make our code a derivative work; GPL obligations only trigger on **distribution**. Internal use of a modified version (e.g. the login patch) does not trigger distribution obligations either.
2. **Importing `fp.*` into our own package** (`find_best_move`, `Battle`, inference functions): our combined work would be treated as containing GPL code; **once distributed / released**, the whole would have to be open-sourced under GPL-3.0. Purely internal private use has no distribution obligation, but burdens future open-sourcing / publication. **Not recommended** as a core dependency.
3. **Borrowing ideas / algorithms, rewriting ourselves**: ideas, algorithms and mechanics facts (e.g. "took no Stealth Rock damage ⇒ may hold Boots", speed range inference) are not protected by copyright; **what is protected is the concrete code expression**. Approach: understand the rules -> implement independently on our data structures (poke-env `Pokemon`), not a line-by-line translation; the rule list (section 2.3) itself can serve as requirements.
4. **poke-engine (MIT)**: can be depended on, vendored, forked, modified (including adding PUCT / NN evaluation) and redistributed, keeping only the copyright and license notice. The friendliest thing to reuse.
5. Data: the `data.foulplay.cc` JSON can be cached locally for evaluation, but **should not be bundled in anything we distribute** (unclear license); we can **rebuild the same kind of data ourselves from Smogon stats / replays** along the same lines (needs our own replay extraction pipeline).

Reusable roles:

| role | how reused | license risk | fidelity / limits |
|---|---|---|---|
| (a) evaluation opponent | external process, `accept_challenge` | none | strength depends on time budget and team; time-based search is sensitive to CPU contention |
| (b) reference design for search / belief | read the code, clean-room rewrite | low (do not copy code)| design worth borrowing: sampled worlds + DUCT + evaluation |
| (c) source of set inference logic | borrow only the rule list / ideas, implement ourselves | low | limited rule coverage, and depends on damage calculation fidelity |
| (d) simulator for search / training data | depend on poke-engine (MIT)| none | **insufficient fidelity**: not checked against Showdown; known Gen9 gaps; fine as a "search model", needs differential testing first before use as RL training ground truth |

---

## 9. Implications for our project / Recommendations

### 9.1 Overall judgment

- Foul Play's value is not "a bot we can directly surpass" but **a high-quality reference for information inference + sampled search, validated on the ladder and in competition**, and it gives a complete engineering example of the hardest part of our hybrid system to hand-write -- **the belief over opponent sets**.
- The paper and the blog agree: in open-teambuilding formats like OU, **set prediction may matter as much as the search itself** (blog results: Random Battle with known sets reaches 88%+ GXE, OU only 80%/1879). This complements our "learned policy / value + search" route: **belief model + search is the shared "test-time search" part of systems like Jaxcalibur / PokaiTrainer / Ataraxos** (consistent with the project's `doc/research.md`), and Foul Play is the only open-source, readable complete implementation among them.

### 9.2 Concrete recommendations (by priority)

**P0 (do now, 0.5~1 day): use Foul Play as an external evaluation opponent.**
- Separate venv + locally compiled engine + login patch + warmed caches (see 6.3).
- Set **two budget levels**: fast (1s × 8 states) for daily regression; full (~7s × 8–14 states, local timer extended) as the "ceiling reference". Record a "win rate vs budget" curve, not a single number.
- Teams: do not use only the 1 bundled with the repository. Use the same team pool + swap teams; report at least three classes separately, "offense / balance / stall" (stall is its known weakness, and a possible niche for our AI).
- Pin CPU affinity during evaluation so it does not compete with our benchmarks / training (its search is time-based).

**P1 (about 3~5 days): build our own "Foul Play-style" baseline on poke-env, depending on poke-engine directly.**
- Write **a poke-env `Battle` -> `poke_engine.State` converter** (our own, following the engine's Python API and the `State` serialization doctest, not copying `poke_engine_helpers.py`);
- Write **a belief sampler**: Smogon stats (last month's `-0.json`) × logical filters + a self-built or downloaded complete set library;
- `monte_carlo_tree_search(..., iterations=N)` for **a reproducible iteration budget**;
- This route = Laplace's approach, which shows it works; it yields a search agent of the same kind as Foul Play but **native to our poke-env stack**, reusable by later learning modules.

**P2 (about 1~2 weeks): clean-room set inference, with the engine as the damage calculator.**
- Priority (best value first): speed range inference -> Choice item locking / exclusion (including the Scarf check) -> Heavy-Duty Boots check -> Assault Vest / Life Orb / Leftovers / Flame&Toxic Orb exclusion -> **damage back-calculation filter** (`poke_engine.calculate_damage` ready to use; mind the ±2.5% and level/20 tolerances, no lower-bound check on overkill) -> Tera type -> ability exclusion.
- **Improvements (over Foul Play)**: **soft weights (likelihoods)** instead of hard elimination; likelihood updates from the opponent's behavior (which move it chose, when it switched); sampling the complete set library **weighted by count**, smoothed with uniform sampling; correcting Smogon's product-independence assumption (the joint distribution in replays can be used). This is the real room for beating its heuristics.
- Data: no dependence on `data.foulplay.cc`; build a joint set library ourselves from Smogon stats + replays (the Metamon dataset / replay sources the project already follows).

**P3 (about 2~4 weeks): combine with a learned policy / value network.**
- Pattern (as in Jaxcalibur / PokaiTrainer / Ataraxos): **a learned policy as prior + a value network for leaf evaluation + DUCT/PUCT over K sampled worlds, aggregating visit counts**.
- On poke-engine this needs **a fork (MIT allows it)**: ① add a prior `p` to `MoveNode`, replace UCB1 with PUCT (`mcts.rs`/`mcts_threaded.rs`); ② replace `evaluate()` with a pluggable evaluator, and **collect leaves in batches** for a GPU value network (a Python callback per leaf would be dragged down by PyO3 round trips and the GIL); ③ keep DUCT's "independent selection per side".
- First validate the value with the cheapest version: **keep the engine's hand-written evaluation as the main evaluator and use a small network only to rerank "near ties"** (Laplace's approach, affecting about 5–10% of turns), or bias the root with the network's policy prior; this can be done without changing the engine.
- Foul Play itself can serve as **a teacher / data source**: distill a policy from its search visit distributions (output data is not bound by the GPL, but keep its code out of anything we release).

**What not to do**
- Do not import `fp/` into the core package or copy its inference code (GPL contagion and trouble with future publication / open-sourcing).
- Do not use poke-engine as the RL training "ground-truth environment": without differential tests against Showdown, engine deviations will be exploited by the policy (reward hacking by simulator bug). The training environment should be Showdown (the project already has `vendor/pokemon-showdown`); the engine only serves as **the approximate model inside search**.

### 9.3 Risks

| risk | description | mitigation |
|---|---|---|
| engine fidelity | not checked against Showdown; known Gen9 gaps (trapping, Protect, sleep, Doom Desire…); average-damage compression | **random-state differential tests** with our local Showdown (generate a state -> one step on each side -> compare distributions); down-weight or patch (MIT) the moves with gaps in search |
| single maintainer / pinned versions | Foul Play pins `poke-engine==0.0.48`; new species / moves need a release; enum panics | we fork and vendor a fixed version; add new Gen9 content ourselves |
| external data dependencies | `data.foulplay.cc`, the Smogon stats URLs, PS sets are all fetched at run time | warm caches; our own data pipeline |
| evaluation function ceiling | hand-written linear heuristic, species-independent; weak against stall | replace / rerank with a value network; cover stall games specifically in training |
| determinization flaws | strategy fusion, no value of information | multi-world aggregation + mixed strategy; long term consider ISMCTS / belief-state search |
| evaluation reproducibility | time-based search is sensitive to CPU contention | pinned cores / iteration budget |
| license | GPL | process isolation; clean-room |

### 9.4 Effort estimates (one person, rough)

| task | estimate |
|---|---|
| separate venv + engine build + login patch + data warm-up + battle script against poke-env | 0.5~1 day |
| poke-env -> engine state conversion + basic belief sampling + MCTS agent | 3~5 days |
| set inference (clean-room, including damage back-calculation, speed ranges and 8~10 rules in all) + tests | 1~2 weeks |
| engine vs Showdown differential test framework (Gen9 OU scope) | 1 week |
| engine fork: PUCT priors + pluggable batched evaluation + Python / GPU interface | 2~4 weeks |
| self-built joint set library (replay extraction) + learned belief model | 2~4 weeks (depending on the replay data source)|

### 9.5 Evidence gaps (stated honestly)

1. **No performance number was measured**: engine nodes/s, Foul Play's actual per-move latency, build time -- no data from this machine.
2. The paper's text has no FH-BT / Elo value for FoulPlay, nor its competition team, search budget, hardware; the semifinal score was not extracted.
3. Gen9 OU's "1879 / 80% GXE" and "~1930+" are self-reported and inconsistent with each other; the configuration of the third-party account's 1190 / 51.5% is unknown; no independent reproduction.
4. Blog / forum thread / issue content went through a small model's summary, not checked word for word; "the login flow that may cause offline problems" is inferred from the code only, **not verified on a local server**.
5. The two serial batches when the sample count exceeds the parallelism (inferred from the code), uv's `-C build-args` syntax, Python 3.14 compatibility: all `[UNVERIFIED]`.
6. How the engine's data files (`choices.rs` etc.) are generated, and their item-by-item coverage of Showdown's current Gen9 OU rules, were not audited.
7. The numbers on Jaxcalibur etc. in our existing `doc/research.md` are `[self-reported]`; this report did not re-check them.

---

## Appendix A: key files

| topic | path |
|---|---|
| CLI / configuration | `foul-play/fp/config.py`; `fp/format_spec.py`; `fp/generations.py` |
| connection / login | `foul-play/fp/websocket_client.py` (`login` line 89)|
| main loop | `foul-play/fp/main.py: run_foul_play`; `fp/run_battle.py: pokemon_battle` |
| decisions | `foul-play/fp/modes/base.py: async_pick_move/format_decision/handle_team_preview` |
| state | `foul-play/fp/battle/state.py`; `fp/battle/protocol.py: process_battle_updates` (2290)|
| inference | `foul-play/fp/battle/inference.py` (`check_speed_ranges` 133, `check_choicescarf` 344, `_do_check` 465, `update_dataset_possibilities` 545, `check_heavydutyboots` 648)|
| set data | `foul-play/fp/data/sets/{smogon,team_datasets,base,randbats}.py` |
| sampling | `foul-play/fp/search/standard_battles.py: _sample_pokemon` (168), `prepare_battles` (296)|
| search entry point | `foul-play/fp/search/main.py: find_best_move` (58), `select_move_from_mcts_results` (16)|
| state conversion | `foul-play/fp/search/poke_engine_helpers.py: battle_to_poke_engine_state` |
| engine MCTS | `poke-engine/src/mcts.rs`; `src/mcts_threaded.rs` |
| engine evaluation | `poke-engine/src/genx/evaluate.rs` (Gen1/2/3 each in `src/genN/evaluate.rs`)|
| engine instruction generation | `poke-engine/src/genx/generate_instructions.rs` (`generate_instructions_from_move_pair` 4035, `moves_first` 2593)|
| engine state | `poke-engine/src/state.rs`; `src/instruction.rs`; `src/genx/state.rs: root_get_all_options` |
| Python bindings | `poke-engine/poke-engine-py/src/lib.rs`; `python/poke_engine/__init__.py` |
| benchmark | `poke-engine/data/benchmark.rs` |

## Appendix B: main external sources

- Foul Play repository https://github.com/pmariglia/foul-play ; blog https://pmariglia.github.io/posts/foul-play/ ; Smogon thread https://www.smogon.com/forums/threads/re-introducing-foul-play-a-competitive-pokemon-battle-bot.3767378/
- poke-engine repository https://github.com/pmariglia/poke-engine ; docs https://poke-engine.readthedocs.io/
- PokéAgent Challenge: arXiv 2603.15563 (appendices B.2/B.3, D.1.2, E.1.2, E.1.4)
- Laplace (third party, built on poke-engine) https://www.trylaplaceai.com/
- The Smogon thread "Bots are now capable of suspect reqs" (the outside record of Foul Play used in Gen9 LC)
