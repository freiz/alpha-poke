# alpha-poke research notes

> This file collects the **source material** on Pokémon battle AI: papers, open-source projects, simulators, datasets, evaluation methods.
> Design trade-offs and open decisions are in [`design.md`](design.md).
>
> - Survey date: 2026-10-03 (some ladder data fetched on 2026-10-04).
> - The material comes from web search; pages were read through a small model's summaries, so the numbers are "the numbers the summaries report", not checked word for word against the full text.
> - `[unverified]`: only from search summaries or memory; the original was not opened. `[self-reported]`: the author's own claim (forum post, blog, README), not peer-reviewed or reproduced by a third party.
> - Several numbers conflict between sources; they are collected in section 11.
> - Ladder data (Elo/GXE) is **not directly comparable** across formats or across time.

## Contents

1. State of the art at a glance
2. Papers and research results
3. Open- and closed-source bot projects
4. Simulators and infrastructure
5. Datasets
6. Teams and static data
7. Format comparison
8. Transferable methods (from game AI in general)
9. Evaluation methods
10. Engineering lessons
11. Unverified / conflicting information
12. Reference links

---

## 1. State of the art at a glance (TL;DR)

1. **Existing systems reach or come close to top humans on the ladder, but the strongest few are closed-source personal projects [self-reported]**
   - **Jaxcalibur**: Gen9 Random Battle, peak Elo 2557 / GXE 95.3, at #1 several times in August 2026, roughly level with the strongest human (MichaelderBeste2, GXE 95.5).
   - **mikumiku37**: Champions VGC Reg M-C, #1 on the ladder on 2026-10-01 (Elo 1857, GXE 81.2%).
   - **Neither** has released code or weights.
2. **The strongest public, reproducible approaches are two**
   - **Metamon** (UT Austin, MIT): offline RL on human battle replays + self-play, transformer, no search. An ensemble once reached #1 on the Gen1 OU ladder.
   - **Foul Play** (GPL-3.0): sampled opponent sets + MCTS (Decoupled UCT) + a Rust engine; won the Gen9 OU track of the NeurIPS 2025 PokéAgent challenge.
3. **The recipe things have recently converged on**: a small to medium transformer (8–200M parameters) + a very fast simulator (bringing game counts to the order of 10^8) + self-play (PPO/league) + test-time search (pUCT/CFR over sampled "hidden worlds"; about +100–150 Elo by Jaxcalibur's own account).
4. **LLMs alone are clearly weaker as online policies** (PokéLLMon, PokéChamp: about 1300–1500 Elo); the top 8 of the PokéAgent finals were all RL or MCTS.
5. **Team building has almost no mature research**; VGC-Bench explicitly leaves it to future work.
6. **The training compute needed is modest**: Jaxcalibur about 1 H100 × 1 week (about 100M games); mikumiku37 about 1 RTX 5090 × 48 hours (about 330M games). **The key bottleneck is simulator speed**, not the GPU.
7. **poke-env + a Showdown server is the slowest training path** (see 4.1); it suits evaluation/deployment better.

---

## 2. Papers and research results

### 2.1 Battle AI

| Work | Year/venue | Format | Method | Key results | Open source |
|---|---|---|---|---|---|
| **Metamon** — Grigsby et al. [arXiv 2504.04395](https://arxiv.org/abs/2504.04395) | RLC 2025 | Gen1–4 OU (later extended to Gen9 OU) | First-person trajectories reconstructed from 475k human replays; AMAGO-style transformer actor-critic (15/50/200M); offline RL + self-play data | 200M model Gen1 GXE 79.9% (Glicko-1 1761±35, peak rank 31), roughly the top 10% of active players | Yes (MIT) |
| **PokéAgent Challenge** — Karten, Grigsby et al. [arXiv 2603.15563](https://arxiv.org/abs/2603.15563) | NeurIPS 2025 competition | Gen1 OU, Gen9 OU (+ a speedrun track) | Benchmark + competition; scored with Full-History Bradley-Terry | Gen1 winner PA-Agent (extends Metamon), Gen9 winner Foul Play; 13 of the 16 qualifying teams extended the public Metamon baseline; the top 8 all used RL/MCTS | Data and baselines public |
| **PokaiTrainer** — Max Yu [arXiv 2608.29197](https://arxiv.org/abs/2608.29197) | 2026-08 (v2 2026-09) | VGC 2026 Reg M-B (doubles, OTS) | Student-of-Games-style CFR, solving a "Bayesian matrix game with simultaneous moves" at decision time; Rust engine; 5.4M-parameter transformer | Steady 1350–1400 Elo, peak 1492 (top 500); 59% win rate over 150 Bo3 matches; the policy network alone loses 71% to a shallow heuristic search, **the strength comes mainly from search**; the hidden-attribute belief summary adds +8–12 percentage points | The engine is meant to be open-sourced, weights not released; **single-author preprint** |
| **VGC-Bench** — Angliss, Cui, Hu, Rahman, Stone [arXiv 2506.10326](https://arxiv.org/abs/2506.10326) | AAMAS 2026 | Gen9 VGC doubles (OTS) | BC, PPO self-play, fictitious play (FP), double oracle (DO) and BC-initialized variants; 8×A40, about 5M steps per configuration | Single-team BCSP beats intermediate/advanced players in a small-sample test (the authors call it "intentionally anecdotal"); more teams → better generalization, worse in-distribution play; about 100% exploitable by a targeted best response | Yes (MIT) |
| **PokéChamp** — Karten et al. [arXiv 2503.04094](https://arxiv.org/abs/2503.04094) | ICML 2025 spotlight | Gen9 OU | An LLM replaces minimax's action sampling, opponent modeling and leaf evaluation; no training | 76% against PokéLLMon; projected ladder Elo 1300–1500 (top 30%–10%); about 1/3 of games lost on the timer | Yes (license NOASSERTION; read the LICENSE before reuse) |
| **PokéLLMon** — Hu, Huang, Liu [arXiv 2402.01118](https://arxiv.org/abs/2402.01118) | 2024 | Gen8 Random Battle ([unverified]) | GPT-4 prompting + knowledge augmentation + consistent action generation | 49% ladder win rate, 56% in invitational games ("average human level") | Yes (stale) |
| **Huang & Lee** [CoG 2019](https://ieee-cog.org/2019/papers/paper_175.pdf) | 2019 | Gen7 Random Battle | PPO+GAE self-play, entity embeddings; 3.84M games, about 6 days, about $91 (GCP) | Glicko-1 1677 (about 72% against random ladder opponents) | Paper |
| **Sarantinos** [arXiv 2212.13338](https://arxiv.org/abs/2212.13338) | 2022/23 | Gen7 Random Battle | Distributed search (4×48-core AWS), not RL | 643 games against humans, peak 33rd in the world | No |
| **PokeJAX / "Automatic Generation of High-Performance RL Environments"** — Karten, Appapogu, Jin [arXiv 2603.12145](https://arxiv.org/abs/2603.12145) | 2026-03 | (generations/formats covered not stated) | LLM agents help translate Showdown into JAX (about 56k lines) | 1×RTX 5090: 500M steps/s with random actions, PPO about 15.2M steps/s; the paper claims equivalent win rates when policies are transferred back to Showdown | **The paper gives no code address [unverified]** |
| Kalose et al. | 2018 Stanford course report | Own simplified simulator | Tabular Q-learning | 70% against a random agent | No (historical reference only) |

Other work seen only as metadata `[unverified]`: Simões et al. 2020 (ICARSC, WPL/GIGA competitive RL on their own simulator), Rossi et al. 2024 (SBGames, an RL benchmark on poke-env), Lee & Togelius 2017 (a Showdown AI competition proposal), a Springer 2024 paper on neuroevolution for VGC, Jett Wang's MIT MEng thesis 2024 (Random Battles + RL).

LLM work of low relevance: Jain et al. [arXiv 2512.17308](https://arxiv.org/abs/2512.17308), a multi-agent LLM tournament [arXiv 2508.01623](https://arxiv.org/abs/2508.01623), Porimon [arXiv 2609.32544](https://arxiv.org/abs/2609.32544). The search found **no** 2026 paper that fine-tunes an LLM with RL (e.g. GRPO) for Pokémon battles; this can be taken as a gap.

**poke-env itself has no academic paper**; it is only a GitHub library (usually cited as the repository).

### 2.2 Key details of each work

**Metamon**
- Observation: about 87 text tokens + 48 numeric features per timestep, with a Pokémon-specific vocabulary; 9 actions (4 moves + 5 switches) with an action mask; the reward is mainly win/loss with light shaping (damage, recovery).
- Algorithm: a behavior-cloning term − λ·a Q-maximization term; variants IL, Exp, Binary, Binary+MaxQ; trained with several γ, evaluated with γ=0.999; later a two-hot classification critic (from AMAGO-2).
- Data: see 5.2.
- Released models (README): SyntheticRLV2 200M (2024-09); Abra 57M (2025-07, the strongest public Gen9 OU model during the challenge); Kadabra3 57M; **Kakuna 142M** (2025-12, GXE Gen1/2/3/4/9 = 82/70/63/64/71); **TaurosV0 62M** (2026-05, Gen1 OU specialist, GXE 83%). The README says KakunaEnsemble / TaurosEnsemble reached #1 on the human Gen1 OU ladder `[self-reported, not independently confirmed on the ladder page]`.
- Limitations (the authors' own): a sim-to-sim gap between replay reconstruction and the real server; errors accumulate past 100+ turns; weaker against rare teams; 1–5% invalid actions; early generations have few players, so Elo is noisy.
- Training compute: the paper gives no GPU hours `[unverified]`; the README says the large models take "days, several GPUs".

**Foul Play / poke-engine**
- Keeps a large library of candidate opponent sets (from Smogon usage, crawled teams, replays, with likelihood weights), filtered by evidence as the game goes on (EVs/nature inferred back from damage, speed tiers from move order, items from weather/terrain behavior, movesets from status moves).
- Each decision: sample several complete "worlds" (the hidden attributes filled in, i.e. determinization / PIMC), run MCTS in each world, then aggregate.
- Search: Decoupled UCT (with simultaneous moves each side picks independently), implemented in Rust, root parallelism; **damage-roll clustering**: instead of enumerating the 16 rolls, it branches only on "KO or not", which raises the search depth from about 5 turns with expectiminimax to about 10 turns.
- The author considers opponent set prediction "as important as search speed, or more".
- Results `[self-reported]`: Gen9 OU GXE 80%, peak Elo 1879 (blog) / "1930+" (forum post; the two disagree); Gen9 Random Battle 88% / 2341; Gen4 Random Battle 85% / 1728.
- Weaknesses: defensive teams, long-term planning beyond about 10 turns, a handwritten evaluation function, independent searches per world. In theory PIMC suffers from strategy fusion, and DUCT is not guaranteed to converge to a Nash equilibrium.
- Compute: 16GB RAM / 4 cores, about 7 seconds per move.

**Jaxcalibur `[self-reported]`** ([website](https://jaxcalibur.github.io/), [Smogon thread](https://www.smogon.com/forums/threads/jaxcalibur-a-gen-9-randbats-bot-that-reached-1-on-the-ladder.3787537/))
- A Gen9 Random Battle engine rewritten in pure JAX.
- Model: 8.5M-parameter non-causal transformer (positional MoE), 66 input tokens (field 1, active 2, moves 5, own team 6, opponent's team 6, event history 16, matchup calculations 24); outputs action logits, win probability, the opponent's action, and predictions of the opponent's items/abilities/moves (auxiliary losses).
- Training: PPO + GAE + entropy regularization + a "zero-avoiding" KL-to-uniform term; no search during training; 1×H100 about 1 week, about 100M games; the author says total development took 6+ months and reproducing it needs "a few hundred dollars of GPU + expertise" (the training time differs between the website and the forum thread, see section 11).
- Test-time search: a pUCT variant for simultaneous moves (edges sampled from a mix of positive regrets and the network prior), 32 sampled opponent-set "worlds", depth 4, 20,480 rollouts, estimated 100–150 Elo above the plain policy; the plain policy is about 2400 Elo on a laptop.
- Results: peak Elo 2557, GXE 95.3, 68% against top players; held #1 for about 20% of the observed period vs about 50% for the strongest human, so "level", not "clearly beyond".
- The author declines to release code/weights (to protect the integrity of the ladder and tournaments); most of the community is against releasing them.

**mikumiku37 `[self-reported]`** ([Smogon thread](https://www.smogon.com/forums/threads/mikumiku37-a-self-play-vgc-bot-reached-1-on-the-vgc-reg-m-c-ladder.3789199/))
- 8.7M-parameter transformer, PPO self-play against a league (past versions), from scratch (no human replays), about 1,260 public tournament teams; 1×RTX 5090 × 48.3 hours, about 330M games; the input is the state from its own side + static Pokédex data, **without** a damage calculator / usage stats / speed checker.
- Decision: 1-turn lookahead, 16 sampled worlds, a payoff table of its top 8 joint actions × the opponent's top 8 replies, solved for a mixed strategy.
- Results: Elo 1857, GXE 81.2%, Glicko 1775±25, 248–110 (358 games), #1. Note: this format's ladder is new and the top human is only about 1875 Elo / GXE 74% (see section 7), so the bar for "#1" is lower than in OU/Random Battle.
- Code, engine and weights are all unreleased.

**PokéAgent Challenge**
- Battle tracks: Gen1 OU, Gen9 OU, on a dedicated agent-only Showdown server (https://battling.pokeagentchallenge.com); timer: the standard 30 seconds to start + 3 seconds per turn (capped at 8 seconds), relaxed to 60–90 seconds for the LLM variant.
- Scoring: mainly FH-BT, with Glicko-1 and GXE also recorded; at least 250 games.
- Data: 4M+ human trajectories, 18M synthetic self-play trajectories, 200k+ team files.
- Conclusions: RL and search are clearly better than LLMs; the top RL baselines reach about 80% GXE on the human ladder, "comparable to top humans but not superhuman"; LLM failure modes include "panic switching" and memory contamination.
- The winning teams' detailed methods/compute (appendix) `[unverified]`.

---

## 3. Open- and closed-source bot projects

| Project | Address | Language | Method | Format | Strength (source) | Activity | License |
|---|---|---|---|---|---|---|---|
| **Metamon** | [UT-Austin-RPL/metamon](https://github.com/UT-Austin-RPL/metamon); HF `jakegrigsby/metamon` | Python (`amago`) | transformer offline RL + self-play | Gen1–4 OU, Gen9 OU (singles only) | See 2.2 | 2026-07 (the author calls it a hobby project, irregular updates) | MIT |
| **Foul Play** | [pmariglia/foul-play](https://github.com/pmariglia/foul-play) | Python + Rust | sampled sets + MCTS | Singles, all generations (no Dynamax/Z-Moves) | See 2.2 | Active on 2026-10-03 | **GPL-3.0** (copyleft if the code is reused) |
| **poke-engine** | [pmariglia/poke-engine](https://github.com/pmariglia/poke-engine) | Rust + Python bindings | Approximate engine for search (expectiminimax / DUCT) | Singles only | — | 2026-10-03 | MIT |
| **VGC-Bench** | [cameronangliss/vgc-bench](https://github.com/cameronangliss/vgc-bench) | Python (poke-env + PettingZoo) | BC / PPO / FP / DO | VGC doubles OTS | See 2.1 | 2026-07 | MIT |
| **PokéChamp** | [sethkarten/pokechamp](https://github.com/sethkarten/pokechamp) | Python (uv, poke-env) | LLM minimax | Gen1–9 | See 2.1 | 2026-03 | NOASSERTION |
| **PokéLLMon** | [git-disl/PokeLLMon](https://github.com/git-disl/PokeLLMon) | Python | LLM | Gen8 Random Battle | 49% ladder win rate | 2024-10 (stale) | None |
| **Technical Machine** | [davidstone/technical-machine](https://github.com/davidstone/technical-machine) | C++ | expectimax + team builder | Mainly Gen1–4 | No strength data | 2026-08 | BSL-1.0 |
| **Laplace** | [trylaplaceai.com](https://www.trylaplaceai.com) / GitHub influxtion/Pokemon-Showdown-AI | Python/PyTorch + poke-engine | 8 sampled worlds × MCTS + a small 368-dimensional network to break ties | Gen9 Random Battle | Self-reported peak 2231 Elo, rank about 150, GXE 83.3 (800+ games) | Unverified | Open source |
| Jaxcalibur | See above | JAX | PPO + pUCT | Gen9 Random Battle | Elo 2557 / GXE 95.3 | — | **Closed source** |
| mikumiku37 | See above | — | PPO league + 1-turn solve | Champions VGC Reg M-C | Elo 1857 / GXE 81.2 | — | **Closed source** |
| philmantatsky/VGC-Pokemon-Showdown-AI | [GitHub](https://github.com/philmantatsky/VGC-Pokemon-Showdown-AI) | Python | BC init + PPO transformer + fictitious play | VGC Reg M-B | Self-reported peak 1365 Elo | `[unverified]` | MIT |
| taylorhansen/pokemonshowdown-ai | [GitHub](https://github.com/taylorhansen/pokemonshowdown-ai) | TS/TF | PPO/DQN | Gen4 Random Battle | Stale (2024-01) | — | MIT |

Other small projects seen only through README summaries, unverified: PsyMew (LLM bot, forked from Foul Play), Nolelle/pokemon-vgc-ai, akkshay0107/p0, Blueshadow0107/showdown-brain, Novapool/pokemon-showdown-ai, RotomAI.

**Observations**
1. The current evidence of "level with top humans" (Jaxcalibur, mikumiku37) comes from closed-source projects; the open, reproducible ones are Metamon (strong in Gen1, only about 71% GXE in Gen9 OU) and Foul Play (search, about 80% GXE in Gen9 OU).
2. **Gen9 OU (with team building, Terastallization, 1000+ species) has no public RL agent at top-human level**.
3. The gap in training throughput (Showdown + poke-env at a few hundred steps/s vs custom engines at 745k–15.2M steps/s) is the main reason the top bot authors all rewrote the engine themselves.

---

## 4. Simulators and infrastructure

### 4.1 poke-env

- Repository: [hsahovic/poke-env](https://github.com/hsahovic/poke-env), docs https://poke-env.readthedocs.io ; MIT; PyPI 0.16.1 (2026-08-23, the version this project currently depends on); still had commits on 2026-10-02; still labeled `Development Status :: 3 - Alpha`.
- **What it is**: a websocket client for a Showdown server that parses the protocol into Python objects (`Battle`, `DoubleBattle`, `Pokemon`, `Move`, `GenData`, etc.) and tracks what is known about the opponent. asyncio; one process can run several games at once through `max_concurrent_battles`.
- **Player API**: subclass `Player` and implement `choose_move(battle)`; built-in RandomPlayer, MaxBasePowerPlayer, SimpleHeuristicsPlayer; `battle_against`, `send_challenges`, `accept_challenges`, `ladder`; `Teambuilder` (packs team strings); 0.16 added a team-building example based on Smogon usage.
- **RL API**: `PokeEnv` is a PettingZoo `ParallelEnv` (`agent1/agent2`, native self-play support), with subclasses `SinglesEnv` / `DoublesEnv`; `SingleAgentWrapper` wraps it as a single-agent Gymnasium environment. Users override `embed_battle`, `calc_reward` and set `observation_spaces`. The singles action space is `Discrete(26)` (generation 9: 0–5 switches, 6–9 moves, then blocks of 4 for mega / Z / Dynamax / tera); `get_action_mask` is provided.
- Pinned dependencies: gymnasium==1.3.0, websockets==16.1.1, pettingzoo>=1.24.3, numpy>=2.0.2, orjson. The examples use stable-baselines3 + supersuit.
- **Known limitations** (from the issue list):
  - Unfixed bugs in old-generation mechanics (#753 Gen1, #964 Gen3 Flash Fire);
  - Thin doubles support/docs (#458);
  - Duplicate Pokémon/nicknames not supported (#770, #415);
  - Cannot start a game from an arbitrary state (#618) -- key for "searching from a given position";
  - No ladder support inside PokeEnv (#809);
  - Battle parsing performance (#921), startup/reset overhead (#907, a proposal for an in-process BattleStream backend, no maintainer response).
  - Metamon reports PP-counting and tera type bugs in the poke-env backend and a sim-to-sim gap with its replay parser, so it ships its own parser and backend.
- **Throughput** (no official numbers): the PokeJAX paper measured about 681 steps/s for a PPO loop through PokeEnv vs about 21k steps/s for bare Showdown (that paper's authors have a motive for the comparison); a blog reports about 209–242 games/minute (20 concurrent, `[unverified]`). **Needs measuring on this machine**.
- **Local parallelism**: ① several concurrent games in one Player; ② several environment processes (SubprocVecEnv / ray), each with its own account, on one server; ③ several Showdown servers on different ports (VGC-Bench's train.sh starts several automatically).
- Conclusion: poke-env goes faithfully through the real protocol (required to deploy on the ladder), but is **not suited as the simulator for large-scale training**.

### 4.2 Pokémon Showdown (ground truth)

- [smogon/pokemon-showdown](https://github.com/smogon/pokemon-showdown); MIT; TypeScript; 0.11.11 (2026-07-28); needs Node ≥ 22.18.
- Covers singles/doubles/triples, Gen1–9; includes the `champions` and `championsregmb` mods (Pokémon Champions formats: VGC 2026 Reg M-B/M-C, BSS, OU, etc.).
- Running locally: `node pokemon-showdown start --no-security` (removes throttling and passwords); the script is `scripts/start_showdown.sh`.
- Bottleneck: single-threaded Node; `subprocesses.simulator` in `config.js` defaults to 1. It is more efficient to bypass the server and the websocket and drive `BattleStream` directly (the `pokemon-showdown simulate-battle` command line, `sim/README`). The pkmn/engine docs warn that BattleStream's Promise handling has races that can distort benchmarks.
- Command-line tools: `simulate-battle`, `generate-team`, `validate-team`, `pack-team`.

### 4.3 Faster simulators

| Name | Description | Speed | Fidelity | Status/caveats |
|---|---|---|---|---|
| **pkmn/engine** ([GitHub](https://github.com/pkmn/engine), Zig, MIT) | Claims over 1000× faster than a patched Showdown, bug-for-bug compatible; bindings for C/Zig/Node(WASM) | >1000× (self-reported) | Compatibility mode | **WIP** (README: "wait for v0.1"); stage 1 is RBY and GSC (in progress), ADV/DPP later, **no Gen9** |
| **advsim** ([zkingston/advsim](https://github.com/zkingston/advsim), Python/NVIDIA Warp, MIT) | GPU engine for Gen3 Random Battle, one game per thread; includes PPO league training and GPU determinized simultaneous-move MCTS | RTX 4070 about 745k decisions/s (smoke PPO) | Validated against Showdown 0.11.11 on 100k+ full games, 6.8M decision points, 10M damage cases, 0 divergences | **Just created on 2026-10-02**, 0 stars; Gen3 random singles only |
| **PokeJAX** (arXiv 2603.12145) | A JAX translation of Showdown | 1×RTX 5090, PPO 15.2M steps/s | The paper claims equivalent win rates after policy transfer | **Whether the code is public `[unverified]`**; coverage not stated |
| **minimon** ([spktrm/minimon](https://github.com/spktrm/minimon), JAX, MIT) | A Pokémon-"analogue" environment (procedurally generated types/moves/items), simultaneous moves, hidden information, with Nash tools | Not quantified | **Not faithful to Showdown** (by design) | Good for algorithm research, cannot train a ladder bot |
| Jaxcalibur / mikumiku37's engines | Private JAX engines | Not published | Not published | **Closed source** |
| pokemon-showdown-rs ([vjeux](https://github.com/vjeux/pokemon-showdown-rs), Rust) | 1:1 port of Gen9 Random Battle, with consistency tests against Showdown | About 50 games/s, about 2,400 turns/s (single thread) | Consistency tests | No license file; no updates since 2026-01; only slightly faster than Node |
| poke-engine (see section 3) | Approximate Rust engine for search | Fast | The README itself says "far less complete than Showdown" | Generation coverage differs between README and changelog `[unverified]` |
| PokaiEngine (used by PokaiTrainer) | Rust; enumerates the full outcome distribution of joint actions | Median turn 0.08 ms vs Showdown 2.0 ms (26×) | About 99% behavioral agreement | The author says he plans to open-source it |
| pokejax(JerJer2465), ninjax, psvm, Novapool, etc. | Experimental/abandoned | — | — | `[unverified]` |

**Conclusion**: there is currently **no** open-source fast Gen9 / VGC / doubles engine with verified fidelity. What is usable: pkmn/engine (Gen1/2, WIP) and advsim (Gen3 Random Battle). The authors of strong bots all wrote their own engines (Jaxcalibur, mikumiku37, PokaiTrainer).

### 4.4 General RL infrastructure (only what is relevant to "single-machine imperfect-information self-play")

| Name | License | Notes |
|---|---|---|
| Stable-Baselines3 / sb3-contrib (MaskablePPO) | MIT | Used by the poke-env examples; simple but unfriendly to transformers/leagues |
| PettingZoo / Gymnasium | MIT | poke-env's multi-agent interface |
| **PufferLib** | MIT | High-throughput vectorization (C environments, shared memory) + its own PPO; PyPI stable 3.0.0 (2025-06), GitHub release tag "5.0-experiments" (2026-09), versions diverge; no Pokémon battle environment found; suits the "write your own environment in C/Zig" route |
| CleanRL | MIT | Single-file PPO reference implementations (including JAX); a template rather than a framework |
| Ray RLlib | Apache-2.0 | Multi-agent/league examples, heavyweight |
| Sample Factory | MIT | APPO, asynchronous sampling, aimed at high SPS on one machine; supports multi-agent/PBT |
| TorchRL | MIT | Composable environments/collectors/losses, has a PettingZoo wrapper |
| JAX / gymnax / Pgx | Apache-2.0 | The basis of all the GPU engines; Pgx has had no updates since 2025-03 and has only perfect-information board games |
| **mctx** (DeepMind) | Apache-2.0 | Batched MCTS in JAX; assumes sequential, perfect-information trees, needs adapting for simultaneous moves + hidden information (Jaxcalibur used a modified pUCT) |
| **OpenSpiel** | Apache-2.0 | Algorithm references for CFR, NFSP, PSRO, R-NaD, simultaneous-move games, etc.; usable for exploitability evaluation; too slow for the main training loop |
| **AMAGO** | MIT | The long-context transformer RL library behind Metamon; can load Metamon checkpoints directly |

---

## 5. Datasets

### 5.1 Raw Showdown replays

- Only saved games have replays; **a replay is the spectator's view**: it does not contain either side's full team, only what was revealed; exact HP, EVs, unrevealed moves/items are all missing and must be reconstructed.
- Endpoints (tested working on 2026-10-04):
  - `https://replay.pokemonshowdown.com/search.json?format=gen9ou` (`&user=`, `&user2=`, `&before=<uploadtime>` can be added; at most 51 entries per request, page with `before`; docs [WEB-API.md](https://github.com/smogon/pokemon-showdown-client/blob/master/WEB-API.md)); `rating` is null for some formats.
  - `https://replay.pokemonshowdown.com/<id>.json` returns `{id,format,players,log,uploadtime,views,formatid,rating,private,password}`; there is also `.log`.
  - `<id>.inputlog` is **accessible only for Random Battles** (the rest return access denied) -- which means Random Battles can be replayed exactly, with **complete information**, from the seed + both sides' choices `[only the denial message seen; completeness unverified]`.
- Rate limits/ToS: no documented rate limit or crawling terms found (checked `/rules`, `/pages/faq`); the site is behind Cloudflare. Access politely; prefer the HF mirrors.
- Metamon's raw replays have a coverage hole between 2021 and 2024 ("replay database outage").

### 5.2 The Metamon datasets (best organized, directly usable for RL)

- `jakegrigsby/metamon-raw-replays`: 2,681,841 replays, 5.7 GB Parquet, v6 (2026-05-19); usernames replaced by randomized pseudonyms.
- `jakegrigsby/metamon-parsed-replays`: about 5.3M trajectories (two per game, one from each side's view), from about 2.7M games; format `.json.lz4` organized by generation/year-month; **CC-BY-NC-4.0 (non-commercial)**; covers Gen1–4 OU/NU/UU/Ubers and Gen9 OU, **no Random Battles and no VGC**. The size on the HF page (about 1M, 28.5GB) disagrees with the README's 5.3M; trust the actual download.
- Self-play: `jakegrigsby/metamon-parsed-pile` (pac-base 11M, pac-exploratory 7M, pac-tauros 4M); the README's overall figure is "5M+ human, 20M+ self-play trajectories".
- Teams: `jakegrigsby/metamon-teams` (competitive, `gl_05_26` regular ladder: G1 29k / G2 10k / G3 107k / G4 48k / G9 139k; `hl_05_26` high ladder; procedurally generated diverse teams, etc.).
- Usage-stats mirror: `jakegrigsby/metamon-usage-stats`.
- **Partially observable reconstruction**: a Showdown protocol rewritten in Python turns spectator logs into each player's first-person view, simulates the `request` messages the player would have received, and uses usage stats to sample/predict unrevealed team information, filled back across the whole trajectory; ambiguous games are conservatively dropped. The authors say plainly that a sim2sim gap remains and that the replay data is "better as pretraining for offline-to-online fine-tuning"; the battle backends are versioned (`poke-env` / `pokeagent` / `metamon`), because fixing observation bugs makes old checkpoints worse.
- Paper scale: 475k games → 950k sequences / 38M timesteps; 3.5M trajectories after adding Gen9.

### 5.3 Other public datasets

| Dataset | Size | Format | Notes |
|---|---|---|---|
| [`HolidayOugi/pokemon-showdown-replays`](https://huggingface.co/datasets/HolidayOugi/pokemon-showdown-replays) | 34.19M rows, 71.9GB Parquet; Gen9 Random Battle 1.99M, Gen9 OU 2.49M, VGC 2026 710k | All formats, 2005–2026 | Raw spectator logs + rating + players; **license not stated `[unverified]`**; the largest and most recent, includes Random Battles |
| [`milkkarten/pokechamp`](https://huggingface.co/datasets/milkkarten/pokechamp) | 2M cleaned games (from 3M+, 500k+ high-rated) | 37+ formats, Elo 1000–1800+, 2024–2025 | From PokéChamp |
| [`cameronangliss/vgc-battle-logs`](https://huggingface.co/datasets/cameronangliss/vgc-battle-logs) | 88,905 logs, MIT | Champions Reg M-A/M-B (including Bo3), OTS only, latest 2026-06-20 | Obtained with the vgc-bench crawling tools |
| VGC-Bench paper data | 330k+ (v2) / 700k+ (v3), filtered to rating ≥ 1200 | Gen9 VGC (SV era) | |
| `stevenkhan/pokemon-showdown-battle-sft` | Derived from pokechamp, Elo≥1400 | | SFT-style, of little value for RL |
| Kaggle | No dataset of substance found | | `[absence unverified]` |

The PokéAgent site says "2.4M+ replays, 4M+ RL trajectories, 200k+ team sets", while the paper says "4M+ human trajectories, 18M synthetic, 100k+ community games"; the figures differ slightly.

### 5.4 Smogon usage stats as game-count data

- `https://www.smogon.com/stats/YYYY-MM/` (latest 2026-09). Total games per format in 2026-09: gen9ou 574,541; Champions VGC Reg M-C 1,631,943; Reg M-B 326,464; Reg M-C Bo3 223,477; gen9doublesou 196,031; gen3ou 195,470; championsou 145,642; championsbss Reg M-C 69,462; gen4ou 57,675; gen1ou 11,702; gen2ou 4,433; gen9vgc2024regg 9,911.
- **Random Battles are not in the stats** (the files 404). Usable as a proxy for each format's human population.

---

## 6. Teams and static data

- **Smogon stats**: under `.../stats/YYYY-MM/`, `<format>-<cutoff>.txt`, `chaos/<format>-<cutoff>.json`, `moveset/`, `leads/`, `metagame/`, `monotype/`. Cutoffs are mostly 0/1500/1630/1760 (OU: 0/1500/1695/1825). The chaos JSON has `Raw count`, `Abilities`, `Items`, `Spreads`, `Moves`, `Tera Types`, `Teammates`, `Checks and Counters`, `usage`, etc. Uses: sampling opponent sets / the belief model, predicting information missing from replays (Metamon's approach), species embeddings.
- **Showdown `data/`**: `pokedex.ts`, `moves.ts`, `typechart.ts`, `learnsets.ts`, `formats-data.ts`, `items.ts`, `abilities.ts`, `natures.ts`, `conditions.ts`, `rulesets.ts`, `mods/` (including Champions), `text/`. Usable for static features: base stats / types / move power and accuracy / priority / learnable moves, etc.
- **Random Battle sets**: `data/random-battles/gen9/sets.json` (267KB), `doubles-sets.json`, `bss-factory-sets.json`, `factory-sets.json`, etc., plus `teams.ts` (the generator). In Random Battles the opponent's possible sets can be enumerated (a few sets per species, by role); **this makes belief tracking far easier than in OU**, and is one reason Foul Play does so well in Random Battles.
- **Pikalytics** (VGC usage, from Pokémon HOME + Showdown + RK9): has a markdown "AI" API; terms and rate limits `[unverified]`.
- **VGCPastes**: a spreadsheet of tournament teams + Pokepaste links; VGC-Bench, PokaiTrainer (663 teams) and mikumiku37 (about 1,260 teams) all build their team pools from it.
- **Pokepaste format** ([syntax](https://pokepast.es/syntax.html)) = Showdown's team export format, supported by both poke-env and Metamon.
- Smogon sample team threads: Metamon's `competitive` set (<30 teams per format); the authors say they once overfit to it.
- Text embeddings: no paper was confirmed to embed move/ability descriptions with an LLM; Metamon uses text tokens + numeric features, Jaxcalibur/mikumiku37 use static Pokédex features. This is a design choice, not verified prior work.

---

## 7. Format comparison

Top of the human ladders (`https://pokemonshowdown.com/ladder/<format>.json`, fetched 2026-10-04, top 500):

| Format | #1 Elo / GXE | #10 | #100 | #500 | Notes |
|---|---|---|---|---|---|
| gen9randombattle | 2533 / 94.7 (26.8k games) | 2405 / 90.6 | 2262 / 84.5 | 2111 / 82.5 | Large population; Jaxcalibur peak 2557/95.3; Foul Play 2341/88 |
| gen9ou | 1966 / 85.7 | 1883 / 84.3 | 1755 / 84.1 | 1633 / 73.3 | Foul Play peak 1879, top 100 |
| gen1ou | 1602 / 82.1 | 1547 | 1499 | 1336 | A Metamon ensemble reached #1; only about 11.7k games a month |
| gen2ou | 1544 | 1500 | 1365 | 1125 | Very small population (4.4k games a month) |
| gen3ou | 1814 | 1757 | 1650 | 1543 | |
| gen4ou | 1703 | 1613 | 1518 | 1473 | |
| gen9championsvgc2026regmc | 1875 / 74.0 | 1795 | 1711 | 1605 | 1.63M games a month; mikumiku37 1857 |
| …regmc Bo3 | 1704 / 81.9 | 1614 | 1516 | 1403 | |
| gen9championsbssregmc | 1573 / 73 | 1513 | 1408 | 1252 | 69k games a month |
| gen9doublesou | 1914 | 1825 | 1659 | 1544 | |

> The ladder appears to reflect a recent time window (Showdown ladder seasons are 3 months); whether Elo resets each season `[unverified]`.

**Format by format**

- **Gen9 Random Battle**: no team building; the opponent's sets can be enumerated from `sets.json`; `inputlog` is public; lots of data (about 2M replays); a huge human population. The clearest evidence of "beyond top humans" (Jaxcalibur). Downsides: no official professional events; the skill ceiling includes a large share of luck, and "pro" differentiation lies mainly in in-game decisions.
- **Gen1–4 OU**: Metamon's home ground; very small populations, thin ladders, #1 relatively easy; Gen3/4 are harder for bots (GXE about 63–64%); teams are fairly fixed, team building is simple, hidden information is large. Not the most prestigious formats.
- **Gen9 OU (6v6 singles, with team building)**: the largest "official" singles population (about 570k games a month); the hardest of the singles formats -- team building, Terastallization, a huge hidden space. Strongest bots: Foul Play peak 1879, GXE 80%, about top 100; Kakuna 71%; PokéChamp about 1300–1500. Strongest human 1966 / 85.7. The gap is moderate and measurable. **No public RL reaches top-human level**.
- **VGC doubles (now Pokémon Champions Reg M-x)**: the hardest -- a large joint action space (107 actions per Pokémon in VGC-Bench), pick-4 team preview, OTS, Bo3; there are real professional events (2026 World Championships 8/28–30, champion Takuma Yamazaki). Evidence of machines vs pros is thin (see 9.5); every season's rule change quickly makes data stale; the top human's GXE is only 74% (the ladder is "young").
- **BSS (Battle Stadium Singles)**: 3v3 with OTS; almost no dedicated ML work; small population. Not recommended as the main target.

**Preliminary observation (not a decision)**: for a clear yardstick of "beating human pros", the Random Battle and Gen9 OU ladders are the clearest; VGC has a real pro scene but weak evaluation and fast-aging data. The actual choice and trade-offs are in `design.md`.

---

## 8. Transferable methods (from game AI in general)

### 8.1 Self-play / populations / regularized equilibrium learning

| Method | Authors/year | Link | Relation to Pokémon |
|---|---|---|---|
| **Ataraxos** (superhuman Stratego, Nature 2026-09-30) | Sokota, Vinitsky, Hu, Kolter, Farina | [arXiv 2511.07312](https://arxiv.org/abs/2511.07312) | **The closest template**: MMD self-play + "dynamic damping" + a 57M-parameter belief network + at test time rollouts over about 1000 sampled hidden worlds and a one-step regularized update at the root; under $8,000 (16×H100×1 week + 4×H100×4 days). Differences: Stratego has sequential moves and no chance nodes (Pokémon has simultaneous-move matrices + chance nodes such as damage rolls) |
| Magnetic Mirror Descent (MMD) | Sokota et al. 2022 | [arXiv 2206.05825](https://arxiv.org/abs/2206.05825) | Adds a KL term toward a "magnet policy" + an entropy term to a PPO/actor-critic loss; roughly a one-line change |
| DeepNash / R-NaD | Perolat et al. 2022 | [arXiv 2206.15378](https://arxiv.org/abs/2206.15378) | A reward transformation with KL to a periodically updated reference policy, so self-play converges instead of cycling; Pokémon's team matchups have many rock-paper-scissors cycles, and this is a targeted mitigation |
| The shortcomings of GAE in imperfect-information self-play / VRPO | Fan & Farina 2026 | [arXiv 2605.19235](https://arxiv.org/abs/2605.19235) | GAE's multi-step action sampling adds extra variance in balanced self-play; directly relevant to PPO self-play (only the abstract read) |
| AlphaStar league | Vinyals et al. 2019 | [Nature](https://www.nature.com/articles/s41586-019-1724-z) | Main agents + main exploiters + league exploiters + prioritized fictitious self-play; RL after SL initialization; a mini version (1 main + 1–2 exploiters + past checkpoints) is feasible on one machine |
| OpenAI Five | Berner et al. 2019 | [arXiv 1912.06680](https://arxiv.org/abs/1912.06680) | Very large-scale PPO self-play; plain PPO is a viable baseline, but risks cycling |
| PSRO / double oracle | Lanctot et al. 2017 | [arXiv 1711.00832](https://arxiv.org/abs/1711.00832) | Trains best responses to the pool's meta-Nash mixture; used by VGC-Bench; the evaluation cost is affordable with N≈10–30 agents |
| NFSP | Heinrich & Silver 2016 | [arXiv 1603.01121](https://arxiv.org/abs/1603.01121) | Expensive in samples, largely superseded |
| DouZero | Zha et al. 2021 | [arXiv 2106.06135](https://arxiv.org/abs/2106.06135) | MC returns + action encoding + parallel actors, one 4-GPU machine; shows a single machine is enough |
| Suphx | Li et al. 2020 | [arXiv 2003.13590](https://arxiv.org/abs/2003.13590) | **Oracle guiding** (a teacher's features that see the hidden state during training, gradually faded out) applies directly; global reward prediction can replace handcrafted reward shaping |

### 8.2 Search with imperfect information / simultaneous moves

- **ReBeL** (Brown et al. NeurIPS 2020, [arXiv 2007.13544](https://arxiv.org/abs/2007.13544)): self-play RL on public belief states (PBS) + CFR subgames; the PBS dimension grows with hidden information, so Pokémon needs a compressed belief (PokaiTrainer's candidate menus, Ataraxos's sampling).
- **Student of Games** (Schmid et al. 2023, [arXiv 2112.03178](https://arxiv.org/abs/2112.03178)): growing-tree CFR + counterfactual value/policy networks; PokaiTrainer is an adaptation of it (only the abstract read).
- **Update-Equivalence Framework** (Sokota et al. ICLR 2024, [arXiv 2304.13138](https://arxiv.org/abs/2304.13138)): instead of subgame solving, a decision-time algorithm replicates the updates of a "last-iterate convergent" algorithm (e.g. MMD); the basis of Ataraxos's test-time step; well suited when hidden information is huge (only the abstract read).
- **LAMIR** (Kubicek & Lisy, ICLR 2026, [arXiv 2510.05048](https://arxiv.org/abs/2510.05048)): a learned abstract model in simultaneous-move form + continual-resolving CFR+; **cannot model chance nodes**, validated only on small benchmark games; with a real simulator a learned model is usually unnecessary.
- **Test-time RL in imperfect-information games** (Kubicek, Lisy, Sandholm, [arXiv 2608.30635](https://arxiv.org/abs/2608.30635)): test-time policy gradient with regularization guarantees (abstract only).
- **Pluribus** (Brown & Sandholm 2019): in depth-limited search, leaves assume the opponent can choose among several continuation strategies, for robustness -- can be borrowed as "value leaves under several styles (aggressive/defensive)"; compute figures `[unverified]`.
- **Simultaneous-move MCTS** (Lanctot, Lisy, Winands, et al.): Decoupled UCT (best in practice but without convergence guarantees), Exp3, Regret Matching (Hannan-consistent, the average strategy converges to Nash). To be hard to exploit, the final move should come from the **average strategy** of regret matching/Exp3, not the argmax of DUCT's visit counts.
- **ISMCTS / PIMC / determinization**: Foul Play's top-level approach; known problems are strategy fusion and non-locality `[original not opened]`.
- **The MuZero family** (Sampled MuZero [arXiv 2104.06303](https://arxiv.org/abs/2104.06303), Stochastic MuZero): designed for perfect-information, sequential moves; Pokémon singles has ≤9 actions and a real simulator, so the relevance is weak.
- **ESCHER** ([arXiv 2206.04122](https://arxiv.org/abs/2206.04122)), **DREAM** ([arXiv 2006.10410](https://arxiv.org/abs/2006.10410)): model-free deep CFR variants for when there is no simulator; with a simulator the MMD/R-NaD kind is simpler.
- **Approximate exploitability / ISMCTS-BR** (Timbers et al. IJCAI 2022, [arXiv 2004.09677](https://arxiv.org/abs/2004.09677)): usable as an exploitability proxy -- train an RL exploiter against the frozen agent and report its win rate.

### 8.3 Offline RL / sequence models / BC + RL

- **Decision Transformer** ([arXiv 2106.01345](https://arxiv.org/abs/2106.01345)): a return-conditioned sequence model; Metamon deliberately chose actor-critic + BC-regularized offline RL, because the data quality is mixed and the return is binary.
- **AMAGO** (ICLR 2024, [arXiv 2310.09971](https://arxiv.org/abs/2310.09971)), **AMAGO-2** (NeurIPS 2024, [arXiv 2411.11188](https://arxiv.org/abs/2411.11188)): in-context RL with long-sequence transformers; AMAGO-2 makes the actor/critic objectives classification-style (independent of the return scale). Metamon's engine.
- **BC → RL fine-tuning**: AlphaStar, Suphx, PokaiTrainer, VGC-Bench (RL after BC beats pure RL), Metamon all found that initializing from human data greatly eases the cold start. Risk: replays are biased toward low-rated players; filter/weight by rating.
- **Distillation**: distill a slow, strong teacher (search with belief sampling, Metamon ensembles) into a student that runs within the timer; the Metamon README says the ensembles are the strongest on the ladder.
- **Transformers for partial observability**: Metamon shows that memory of the whole history is crucial (truncating it hurts) and lets the model infer the opponent's sets implicitly; PokaiTrainer shows that an explicit belief summary still adds +8–12 percentage points on top of search.

### 8.4 LLM agents

- PokéLLMon, PokéChamp: LLM + minimax is stronger than prompting alone, but both stop at about 1300–1500 Elo / top 10–30%, and need very long timers.
- PokéAgent's conclusion: Pokémon battle GXE is nearly orthogonal to standard LLM benchmarks (max Spearman 0.77, mean |ρ| 0.45); RL/search specialists dominate.
- For a single-machine project: LLMs are better used **offline** (data labeling, team proposals, explanations, generating candidate sets) than as the online policy.

### 8.5 Team building

- Very little academic literature: VGC-Bench leaves it to future work; neither Metamon nor PokaiTrainer does team building (they use pools of human / procedurally generated / fixed teams).
- Community projects (non-academic): [FutureSightML](https://github.com/HotHams/FutureSightML) (transformer encoding + pairwise matchup matrix + XGBoost win-rate prediction + a genetic-algorithm team builder, 129 formats), Smogon "Algorithmic Team Generation [Peaked 1457]", Poke2Vec vectorization + beam search, [Machine-Learning-Pokemon](https://github.com/gahogg/Machine-Learning-Pokemon) (genetic algorithm).
- Methodology worth considering (synthesized inference, not verified): treat teams as strategies in a meta-game and use PSRO/double oracle to find an unexploitable mixture of teams; pretrain an autoregressive set generator on the ~139k human teams, then fine-tune it with a win-rate reward from a pool of battle agents; screen with a FutureSight-style surrogate model; adversarial team building = max-min over a (team, agent) payoff matrix.

---

## 9. Evaluation methods

### 9.1 Showdown ratings

- Three numbers: Elo (ranking), Glicko-1, GXE (the estimated win rate against a random ladder opponent). [Official explanation](https://pokemonshowdown.com/pages/ladderhelp).
- Elo starts at 1000 with a floor of 1000, a dynamic K, and decay; Glicko-1 starts at R=1500, RD=130. The public server's exact K/decay code is private `[unverified]` (the open-source `ladders-local.ts` does not fully match the official explanation).
- Because Elo has a floor, an asymmetric K and decay, **comparisons across time should prefer Glicko-1/GXE or your own Bradley-Terry fit**.
- The ladder shows only the top 500, refreshed about every 4 hours.

### 9.2 How prior work estimated "human level"

- Metamon: 400–613 games per generation against anonymous humans on the public ladder, reporting GXE + Glicko-1 + rank; percentiles computed over 14,022 active usernames (Gen1–4). The authors have since been more cautious about laddering.
- PokéChamp: "projected Elo 1300–1500 = top 30%–10%", extrapolated.
- PokéLLMon: 49% on the ladder, 56% in invitational games (a very low bar for "human level").
- Foul Play: GXE + peak Elo + peak rank.
- Jaxcalibur: peak Elo/GXE and the share of time at #1.
- VGC-Bench: win rate against humans, anecdotal (5 games per person), noting that the ladder is unsuitable for evaluating in-distribution team performance because the opponents' teams cannot be controlled.
- PokaiTrainer: 150 Bo3 matches on a new account, opponents averaging about 1320 Elo.
- Sarantinos: argues for percentiles (Showdown only shows the top 500).

### 9.3 Local evaluation baselines

- poke-env: `RandomPlayer`, `MaxBasePowerPlayer`, `SimpleHeuristicsPlayer`.
- Metamon: 6 heuristics + 40+ checkpoints; `python -m metamon.rl.evaluate --eval_type {heuristic,il,ladder,pokeagent,challenge}`; `h2h` pairwise win-rate matrix. **Its local GXE does not correspond to public-ladder GXE** (the authors say so explicitly).
- Foul Play: a strong search baseline (singles, all generations, no VGC); PokéChamp: an LLM baseline; VGC baselines: VGC-Bench's BC/SP/FP/DO.
- PokéAgent server: after registering an account, bots can queue for bot-vs-bot ranked games, scored with BT; formats include Gen1–4 OU, Gen9 OU, Gen9 VGC; no human players.

### 9.4 Population-level evaluation and sample sizes

- Prefer FH-BT + bootstrap confidence intervals (when game counts are uneven); Nash averaging (Balduzzi et al. NeurIPS 2018, [arXiv 1806.02643](https://arxiv.org/abs/1806.02643)) keeps clones in a league from inflating ratings. Pokémon has non-transitive cycles of team matchups: fix the team pool and report the win-rate matrix + Nash/BT. No prior work uses TrueSkill `[unverified]`.
- Evaluation teams must be controlled: both sides use fixed sampled teams and swap seats, to separate "team-building luck" from "play skill".
- Binomial 95% confidence interval half-width (p=0.5, my calculation):

| Games | Half-width (percentage points) | Approx. Elo half-width |
|---|---|---|
| 50 | 13.9 | 99 |
| 100 | 9.8 | 69 |
| 200 | 6.9 | 48 |
| 400 | 4.9 | 34 |
| 1000 | 3.1 | 22 |
| 2000 | 2.2 | 15 |
| 5000 | 1.4 | 10 |

  Testing 55% vs 50% (one-sided α=0.05, 80% power) takes about 615 games; 52% about 3,857 games; 60% about 152 games. Ladder estimates carry extra variance (drift of the opponent pool, non-stationary Glicko RD).

### 9.5 Human pro benchmarks

- VGC World Championships 2026: San Francisco, August 28–30; champion Takuma Yamazaki, runner-up Hiroshi Onishi; Reg M-B, Pokémon Champions, Bo3, level 50.
- The only "beat a pro" claim comes from VGC-Bench v3: Aaron Traylor (a multiple-time Worlds competitor) "won at least one game against the AI"; the evaluation was "intentionally anecdotal" and experts could adapt game by game, so the evidence is very weak. **No official human-vs-machine exhibition against a World Champion was found**.
- On the Smogon side: the top ladder players are the de facto benchmark (MichaelderBeste2, Random Battle GXE 94.7, 26.8k games). No human-vs-machine exhibition in Smogon tournaments found. The Smogon community is generally hostile to releasing the strongest bots.
- The PokéAgent paper's framing: Pokémon battling is an "unsolved benchmark", and current systems are "not yet superhuman".

### 9.6 Ladder etiquette / ToS

- Showdown's rules and FAQ have **no explicit bot clause**. The policy is scattered across Smogon forum threads: a moderator said "if a bot harms the human experience, it will be permabanned"; another said banning bots is "not feasible at any level" and they cannot be detected reliably; 2025-11 data show bot teams distorting usage (one bot accounted for 56% of Torkoal's usage, 38% of Excadrill's). There is no bot registration/labeling mechanism.
- Practice (inferred from the above + community norms, not official rules): use a clearly named bot account; do not run 200+ games a day on low-population ladders or during suspect tests; do not manipulate usage tiers through bots; respect the timer; do not use bots to assist humans in competition (the community strongly objects).
- Rate limits: the official server throttles logins/laddering; the poke-env docs recommend your own server for training; laddering needs a registered account with a password; the exact limits `[unverified]`.
- Recommendation: train 100% locally; use the PokéAgent server for bot-vs-bot evaluation; evaluate on the public ladder only the final checkpoint, a few hundred games on a new, clearly labeled account.

---

## 10. Engineering lessons

1. **Engine throughput is the first bottleneck**: PokaiEngine median turn 0.08 ms vs Showdown 2.0 ms; Foul Play reached about 10 turns of search depth after rewriting its Python engine in Rust; Metamon generates self-play on a local Showdown ladder (exact but slow). Verify engine consistency before training (advsim's validation -- full-game comparison + decision-point comparison + damage cases -- is a model to follow).
2. **Observation encoding**: Metamon uses "text tokens + numeric features + a transformer across time"; VGC-Bench/PokaiTrainer use "entity tokens" (12 Pokémon tokens / 14 tokens with the field); Jaxcalibur uses 66 tokens. A natural hybrid: per-turn entity tokens (own 6, opponent's 6 with belief embeddings for unknown attributes, field/side conditions) + a causal transformer across turns; shared species/move/item/ability embeddings; "revealed" and "inferred" information represented separately. (A design suggestion, not from a single source.)
3. **Action masking**: Huang & Ontañón ([arXiv 2006.14171](https://arxiv.org/abs/2006.14171)) show that masking is sound for policy gradients; singles has about 9 actions, doubles uses factored per-slot heads.
4. **Reward**: Metamon uses sparse win/loss + light shaping; its multi-γ analysis shows a long horizon γ≈0.999 helps; Suphx uses learned global reward prediction. Handcrafted HP-difference shaping can teach odd "chip damage" habits -- keep shaping small and anneal it.
5. **Sample efficiency**: BC/offline pretraining, search to raise data quality, classification critics, variance-reduced advantage estimates, search distillation. Ataraxos reached a better level than DeepNash with less than 1/100 of its training samples (news reports, partly verified).
6. **Batched inference**: many CPU engine processes + one GPU doing batched policy/value inference for all games in progress (the inference-server pattern); keep the model small (5–60M: PokaiTrainer 5.4M, Jaxcalibur 8.5M, mikumiku37 8.7M, Abra 57M, Tauros 62M) so that leaf evaluation in search is fast enough.
7. **Opponent pool / league**: AlphaStar league (main + exploiters), PSRO/DO/FP (VGC-Bench), Metamon (many checkpoints + deliberately unrealistic teams for robustness), PokéAgent Porygon2AI. Keep anchors trained on human data in the pool so it does not drift into self-play conventions only; add heuristic bots as sanity checks.
8. **Exploitability proxies**: (a) FH-BT/Glicko/GXE; (b) round robins against past checkpoints and Foul Play, Metamon, PokéChamp; (c) a trained exploiter's win rate against the frozen agent; (d) an (agent, team) PSRO payoff matrix; (e) human evaluation. Also track value-network calibration by turn (PokaiTrainer reports Brier 0.22 over the first 3 turns, 0.10 after turn 8, i.e. optimistic early).
9. **Time limits**: PokéAgent's standard 30 seconds to start + 3 seconds per turn (capped at 8 seconds); Foul Play about 7 seconds per move; budget search by wall clock (DUCT/regret matching are anytime algorithms).
10. **Known failure modes**: defensive/stall teams and long-term planning (Foul Play, PokéChamp); inference from closed team sheets (unsolved in PokaiTrainer); non-transitivity of team matchups (VGC-Bench); the sim2sim gap between replays and the real server (Metamon); early value optimism (PokaiTrainer); LLM panic switching and timeouts.

---

## 11. Unverified / conflicting information

- Metamon's training compute (GPU hours), context length.
- Appendix details of the PokéAgent winners' methods; the live leaderboard.
- Whether PokeJAX is open source, which generations/formats it covers.
- poke-engine's actual generation coverage (README and changelog disagree).
- Details of the Laplace repository, Technical Machine's strength, the quality of the various small GitHub projects.
- **Jaxcalibur**: the website page shows the year 2024 while the forum thread is dated 2026 (judging from the fetched results, 2026 is right); training time "about 1 week (website)" vs "six months (forum thread, possibly total development time)"; first #1 "May" vs "August" disagree. The **mikumiku37** page's date shows the same 2024 error in the summary.
- Metamon SyntheticRLV2's Gen1 GXE: paper 79.9% vs README 77%, both the project's own numbers.
- Foul Play's Gen9 OU peak Elo: blog 1879 vs forum thread "1930+".
- The Metamon ensemble "reaching #1 on the Gen1 OU ladder" comes only from the README, not independently confirmed on the ladder page.
- Elo's exact K, whether ladder seasons reset Elo, the official rate limits.
- Several papers read only as abstracts (SoG, Update-Equivalence, Test-time RL, GAE/VRPO) and unopened classics (ISMCTS, Libratus, Obscuro, the compute figures of AlphaStar/Pluribus/OpenAI Five).
- Ataraxos's Nature page needs a login; details are taken from the arXiv HTML and news reports.

---

## 12. Reference links

**Battle AI and papers**
- Metamon: https://github.com/UT-Austin-RPL/metamon · https://arxiv.org/abs/2504.04395 · https://huggingface.co/jakegrigsby
- PokéAgent Challenge: https://arxiv.org/abs/2603.15563 · https://pokeagentchallenge.com · https://battling.pokeagentchallenge.com
- VGC-Bench: https://arxiv.org/abs/2506.10326 · https://github.com/cameronangliss/vgc-bench
- PokaiTrainer: https://arxiv.org/abs/2608.29197
- PokéChamp: https://arxiv.org/abs/2503.04094 · https://github.com/sethkarten/pokechamp · https://huggingface.co/datasets/milkkarten/pokechamp
- PokéLLMon: https://arxiv.org/abs/2402.01118
- Foul Play: https://github.com/pmariglia/foul-play · https://pmariglia.github.io/posts/foul-play/ · https://www.smogon.com/forums/threads/re-introducing-foul-play-a-competitive-pokemon-battle-bot.3767378/
- Jaxcalibur: https://jaxcalibur.github.io/ · https://www.smogon.com/forums/threads/jaxcalibur-a-gen-9-randbats-bot-that-reached-1-on-the-ladder.3787537/
- mikumiku37: https://www.smogon.com/forums/threads/mikumiku37-a-self-play-vgc-bot-reached-1-on-the-vgc-reg-m-c-ladder.3789199/
- Huang & Lee 2019: https://ieee-cog.org/2019/papers/paper_175.pdf
- Sarantinos: https://arxiv.org/abs/2212.13338

**Simulators / engines**
- Pokémon Showdown: https://github.com/smogon/pokemon-showdown
- pkmn/engine: https://github.com/pkmn/engine · pkmn/ps: https://github.com/pkmn/ps
- advsim: https://github.com/zkingston/advsim
- PokeJAX: https://arxiv.org/abs/2603.12145
- minimon: https://github.com/spktrm/minimon
- poke-engine: https://github.com/pmariglia/poke-engine
- pokemon-showdown-rs: https://github.com/vjeux/pokemon-showdown-rs
- poke-env: https://github.com/hsahovic/poke-env · https://poke-env.readthedocs.io

**Data**
- Replay API: https://replay.pokemonshowdown.com/search.json · https://github.com/smogon/pokemon-showdown-client/blob/master/WEB-API.md
- Ladder JSON: `https://pokemonshowdown.com/ladder/<format>.json`; explanation: https://pokemonshowdown.com/pages/ladderhelp
- Smogon stats: https://www.smogon.com/stats/
- HF datasets: https://huggingface.co/datasets/HolidayOugi/pokemon-showdown-replays · https://huggingface.co/datasets/cameronangliss/vgc-battle-logs
- Pokepaste syntax: https://pokepast.es/syntax.html

**General methods**
- Ataraxos: https://arxiv.org/abs/2511.07312 · MMD: https://arxiv.org/abs/2206.05825 · R-NaD: https://arxiv.org/abs/2206.15378
- ReBeL: https://arxiv.org/abs/2007.13544 · SoG: https://arxiv.org/abs/2112.03178 · Update-Equivalence: https://arxiv.org/abs/2304.13138
- LAMIR: https://arxiv.org/abs/2510.05048 · Test-time RL: https://arxiv.org/abs/2608.30635 · VRPO: https://arxiv.org/abs/2605.19235
- AMAGO: https://arxiv.org/abs/2310.09971 · AMAGO-2: https://arxiv.org/abs/2411.11188
- Nash averaging: https://arxiv.org/abs/1806.02643 · Action masking: https://arxiv.org/abs/2006.14171
