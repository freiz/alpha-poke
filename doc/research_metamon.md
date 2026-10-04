# Metamon 技术调研报告（面向 alpha-poke：Gen9 OU 单打）

| | |
|---|---|
| 调研日期 | 2026-10-04 |
| 被调研对象 | `UT-Austin-RPL/metamon`（commit `0a00a75`，2026-05-22，pyproject 版本 `1.6.0`）；论文 arXiv 2504.04395（RLC 2025）；PokéAgent Challenge 论文 arXiv 2603.15563 |
| 方法 | 浅克隆仓库并读源码（路径均相对仓库根目录；本机副本在 scratchpad `metamon_repo/`）；读 poke-env 分叉与 amago v3.4.0 源码；读 arXiv HTML、HF 数据集/模型卡与文件列表；GitHub API 看 issue/PR 列表 |
| 约定 | **[代码]** = 读源码确认；**[论文]** = 论文原文；**[自报]** = 作者自己报告、未经第三方复现；**UNVERIFIED** = 没有证据或只是我的推断 |
| 未做的事 | 没有安装、没有运行 Metamon、没有下载任何权重或数据（本机另有基准在跑，且约束不允许）。所有“能不能跑”“多快”类结论都是读代码得出的，**没有实测** |

---

## 0. 结论速览（TL;DR）

1. **Metamon 是目前公开可得、与我们目标赛制（Gen9 OU）直接相关的最完整的“离线 RL + 自博弈”体系**：代码 MIT、数据集 CC-BY-NC-4.0、权重 HF 标注 Apache-2.0。最强公开 checkpoint 是 **Kakuna（142M，2025-12）**。
2. **Gen9 OU 实力**：自报人类天梯 GXE 约 **71%**（用 <30 支专家样板队，累计 >700 局、跨 5 个世代，Gen9 单世代样本量应只有约百局量级，置信区间宽，UNVERIFIED）。对比：Foul Play 自报 Gen9 OU GXE >80%、峰值 Glicko 1879；PokéAgent Challenge Gen9 OU 决赛 Foul Play 50–14 击败基于 Metamon 的 RL 队伍 Q。**Metamon 的 Gen9 OU 仍明显弱于 Foul Play（MCTS + 对手配置推断）**。
3. **它的核心价值不是“直接当我们的最终模型”，而是三样东西**：(a) 现成的、可复现的强基线/评测对手；(b) 约 20GB 的 Gen9 OU 人类对局“重建”数据 + 约 55GB 自博弈数据（已解析成后端无关的 `UniversalState` JSON，可换观测空间/奖励）；(c) 一套经过多轮迭代验证的架构与训练配方（AMAGO：Perceiver 回合编码器 + 因果 Transformer + 二热分类 critic + 过滤式行为克隆）。
4. **最大的工程风险是依赖**：Metamon 依赖 **UT-Austin-RPL 的 poke-env 冻结分叉（版本 0.8.3.3，基于 2024-12 的上游）**，与我们钉死的 `poke-env 0.16.1` **同名包 `poke_env`、API 不兼容**（`OpenAIGymEnv`、`poke_env.environment.Battle` 等在 0.16.1 中不存在）。**不能装进同一个 venv**。要用就必须开独立环境，并通过 Showdown 协议（挑战/接受）与我们的 bot 对打。
5. **推荐路线**：
   - **(a) 评测对手：立刻做**，独立 venv + `challenge` 评测模式作为 acceptor（1–3 人日，主要风险是 flash-attn/CUDA 安装）。
   - **(b) 预训练来源：复用数据而非代码**。直接读取 `metamon-parsed-replays/gen9ou` 的 `UniversalState` JSON，用我们自己的观测编码训练 BC/离线 RL；不要重写 4k+ 行的 replay parser。
   - **(c) 架构参考：借鉴设计，不借鉴 token 化细节**。其观测空间有明显信息损失（见 §2.5），Gen9 OU 上我们有改进空间。
6. **不要指望 Metamon 单靠自身追平 Foul Play**；若目标是“超越 pro”，需要在它之上加（i）对手配置信念模型与（ii）测试时搜索，这与 `design.md` 的结论一致。

---

## 1. 仓库布局与架构

### 1.1 目录与职责（均为 [代码]）

```
metamon/
  interface.py          1647 行  UniversalState/Pokemon/Move/Action + ObservationSpace/ActionSpace/RewardFunction 及注册表（核心接口层）
  config.py                     SUPPORTED_BATTLE_FORMATS、FORMAT_ALIASES（gen9oulongtimer->gen9ou）、METAMON_CACHE_DIR
  backend/
    replay_parser/      forward.py(1601) backward.py(369) checks.py(333) replay_state.py(988) parse_replays.py __main__.py
                        # 把 spectator 视角的 replay 日志“重建”成第一人称轨迹（Showdown sim 协议的 Python 重实现）
    showdown_dex/       从 poke-env 复制并打补丁的 Pokédex/招式/特性数据（13MB），gen1-2 无特性等修正
    team_prediction/    usage_stats/(Smogon 使用率读取)、predictor.py(NaiveUsagePredictor/ReplayPredictor)、
                        prediction_model.py + iterative_decoder.py(实验性 TeamPredictionModel, MaskGIT 式并行解码)
    team_preview/       preview.py(Gen9 选首发模型，Perceiver 交叉注意力) + gen9ou_high_elo_v4/best_model.pt
    team_construction/  cli.py(2483 行)等：组队流水线（build-pool→simulate→逻辑回归→坐标上升→受限博弈均衡），2026-05 新增
  env/
    metamon_battle.py   MetamonBackendBattle / PokeAgentBackendBattle：用 replay parser 替换 poke-env 的协议解释
    metamon_player.py   MetamonPlayer(poke_env.Player 子类)：覆盖 _create_battle/_handle_battle_message/teampreview
    wrappers.py         TeamSet、PokeEnvWrapper(OpenAIGymEnv 子类)、BattleAgainstBaseline、QueueOnLocalLadder、ChallengeByUsername、PokeAgentLadder
  data/                 download.py(HF 下载/版本)、parsed_replay_dset.py(MetamonDataset/ParsedReplayDataset/SelfPlayDataset)、raw_replay_util.py
  tokenizer/            DefaultObservationSpace-v0/v1.json（词表），tokenizer.py
  rl/                   metamon_to_amago.py(1406)、pretrained.py(1548)、train.py、finetune.py、custom_agent.py、dataset_config.py
    configs/{models,training,datasets}/*.gin|yaml
    evaluate/           __main__.py(评测入口)、h2h/、sweep/、ladder_self_play/(自博弈数据生成)、serve_matchup.py
    experimental/ensemble/  测试时多模型集成（PastaMittens/Exeggcute，手调路由器）
  il/                   旧的玩具 BC-RNN（已标记 Deprecated）
  baselines/            heuristic/(basic.py, kaizo.py, kaizoplus.py)、model_based/(BaseRNN 等)
server/pokemon-showdown 子模块，固定在 d62d3a3（2026-05）
tools/                  数据修补/分析脚本（如 patch_pokeagent_gen9ou_trajs.py）
```

### 1.2 数据流（把各部分串起来）

```
Showdown 原始 replay JSON (HF: metamon-raw-replays, 2.68M 局, v6 截至 2026-05-19)
   │  replay_parser.forward.forward_fill()   —— spectator 视角逐消息重放，得到双方“已揭示”的状态
   │  replay_parser.backward.backward_fill() —— 对对局结束时仍缺失的队伍信息用 TeamPredictor 补全，
   │                                           再沿时间轴向前回填；分别输出 P1/P2 两个第一人称视角
   ▼
UniversalState 序列 + 动作序列  (HF: metamon-parsed-replays，*.json.lz4，后端无关)
   │  ObservationSpace.state_to_obs()  (数字向量 + 文本词) → TokenizedObservationSpace(词表 -> int ids)
   │  RewardFunction(s_t, s_{t+1}) → 标量；ActionSpace → 13 个离散动作
   ▼
MetamonAMAGODataset → AMAGO Experiment（离线 RL / IL） → checkpoint(policy_epoch_N.pt)
   ▲                                                       │
   │  自博弈：ladder_self_play 启动多个 agent 上本地 Showdown 天梯，
   │  online 轨迹用同一格式存盘（save_trajectories_to），再混入下一轮训练
   └───────────────────────────────────────────────────────┘
```

### 1.3 三种 “battle backend”（[代码] `README.md`「Battle Backends」；`env/metamon_battle.py`）

| backend | 做法 | 已知问题 | 谁用 |
|---|---|---|---|
| `poke-env` | 用 poke-env 的 `Battle` 解释在线对局（论文版） | 与 replay parser 存在 sim2sim 差距；**PP 计数与太晶属性是坏的** | 论文 Gen1-4 策略（SmallRL…SyntheticRLV2） |
| `pokeagent` | 用 Metamon replay parser 替换 poke-env 的消息解析（`PokeAgentBackendBattle`，`metamon_battle.py:707`） | Gen9 在 Beta 期，**己方太晶属性被记录为 missing（“notype”）** | PokéAgent 时期的 Abra、Kadabra*、Minikazam、SmallRLGen9Beta |
| `metamon` | 同上，最新版，且利用在线 `request` 消息拿到己方完整队伍/PP（`MetamonBackendBattle._update_turn_from_request`，`metamon_battle.py:120`） | — | Alakazam、Superkazam、Kakuna、之后的新训练 |

要点：**Metamon 在 2025-06 以后已经不再让 poke-env 解释协议**，在线观测与离线重建共用同一份 `forward.SimProtocol`（`metamon_battle.py:44`），从根上缩小 sim2sim 差距；poke-env 只剩 websocket 连接、`Player` 骨架、`BattleOrder` 等外壳。这对我们有两层含义：(1) 好处是观测一致性设计值得借鉴；(2) 代价是它的 `Player`/`Battle` 层深度耦合在旧版 poke-env 的内部 API 上（见 §6）。

---

## 2. 观测空间、动作空间、奖励（逐项）

### 2.1 一个“时间步”是什么

[代码] `interface.UniversalState`（`interface.py:483`）。每次需要玩家做决定时产生一个状态（含强制换人、复活祝福等），不是每个“回合”一个。第一人称视角，**己方完整信息 + 对手仅可见信息**。

字段（全部）：
`format, player_active_pokemon, opponent_active_pokemon, available_switches[≤5], player_prev_move, opponent_prev_move, opponents_remaining, player_conditions, opponent_conditions, weather, battle_field, forced_switch, battle_won, battle_lost, can_tera, opponent_teampreview`。

`UniversalPokemon`（`interface.py:273`）：
`name, hp_pct, types, item, ability, lvl, status, effect, moves[≤4: UniversalMove], atk/spa/def/spd/spe/accuracy/evasion_boost, base_atk/spa/def/spd/spe/hp, tera_type, base_species`。
`UniversalMove`（`interface.py:215`）：`name, move_type, category, base_power, accuracy, priority, current_pp, max_pp`。

### 2.2 文本 + 数字的混合表示（核心设计）

观测 = `{"text": 以空格分隔的词序列, "numbers": float32 向量}`（`DefaultObservationSpace`，`interface.py:1011`）。文本词经词表映射为整数 id（`TokenizedObservationSpace`，`interface.py:1599`），词表是“从全部 replay 里出现过的词统计出来”的封闭词表（**v1 词表 2541 词**；v0 1454；allreplaysv3 1407；未知词 = `UNKNOWN_TOKEN=-1`，`tokenizer/tokenizer.py:11`）。**宝可梦、招式、道具、特性、天气、场地等全部是“文本 token”（类别型，学习嵌入），数值型只有 HP 比例、等级、种族值/255、能力等级/6、威力/200、命中、优先度/5、PP 档位等。**

**`DefaultObservationSpace`（论文版）：87 个词 + 48 维数字**
文本顺序（`state_to_obs`，`interface.py:1115` 起）：
```
<gen9ou> <forcedswitch|anychoice>
<player> 己方出场: name item ability types(2词) effect status          # 6 词(types 占 2)
<move>×4  每个: name move_type category                                  # 己方 4 招，按名称字母序，不足补 <blank>
<switch>×5 每个: name item ability <moveset> (4招 name 各一词)           # 己方可换入的后备，按物种名字母序，不足补 <blank>
<opponent> 对手出场: name item ability types effect status               # 同己方出场
<conditions> weather player_conditions opponent_conditions
<player_prev> 己方上一招  <opp_prev> 对手上一招
```
数字（48）：`opponents_remaining/6`；己方出场 `hp_pct, lvl/100, 6 个种族值/255, 7 个能力等级/6`；己方 4 招各 `bp/200, accuracy, priority/5`；5 个后备各 `hp_pct`；对手出场同己方出场的 15 维。缺位用 `-2.0` 填充。此外 AMAGO 自动把 **上一步动作的 one-hot 与上一步奖励** 作为 `rl2s` 输入（论文 E.2；`MetamonTstepEncoder.inner_forward` 把 `symlog(rl2s)` 过线性层后拼到数字特征，`metamon_to_amago.py:611`）。

**`ExpandedObservationSpace`（`interface.py:1185`）**：在 Default 上加
- 每个宝可梦文本多一个 `tera_type`（己方 6 只 + 对手 1 只 = 13 词，已含在“87+13”）；
- 4 个招式的 **PP 档位**（`(pp_ratio>=0.5)+(>=0.25)+(>0)`，故意离散化以减小 off-by-one 的 sim2sim 误差）；
- 2 个标志 `any_opponent_asleep / any_opponent_frozen`（睡眠/冰冻条款，需要跨步状态，`reset()` 每局清空）+ `can_tera`；→ 数字 48+7=55 维；
- **“已揭示的对手物种”**列表（跨步累积，补 `<blank>` 到 6 个词）。

**`TeamPreviewObservationSpace`（`:1285`）**：再加 6 个词 = 队伍预览阶段看到的对手 6 只物种（Gen9 专用，其他世代为空）。→ 87+13+6 = 106 词。
**`OpponentMoveObservationSpace`（`:1304`）**：把招式的 `category` 词去掉（省 4 词），给**对手出场**加 4 个“已揭示招式”词。→ 仍是 106 词/55 数字。**Alakazam / Superkazam / Kakuna / Kadabra2-4 / Minikazam 用的就是它**（`pretrained.py`）。
**`GroupedObservationSpace`（`:1331`）**：按实体分组（己方出场、5 个后备、对手出场、misc），每只宝可梦 12 词 + 31 数字（含 4 招的 bp/acc/pri/pp），misc 20 词 + 4 数字；配合 `MetamonGroupedTstepEncoderV2`（`metamon_to_amago.py:977`）做共享宝可梦编码器，Post-PokéAgent 的 TaurosV0 等使用。
**`PAC-*` 前缀空间**（`PatchPokeAgentTeraBug`，`:1549`）：故意把己方 tera_type 全设成 `notype`，让 pokeagent 时期训练的模型在新 backend 上保持训练时的输入分布。

### 2.3 Gen9 / 隐藏信息 的具体处理

| 问题 | Metamon 的做法 | 出处 |
|---|---|---|
| 未知道具/特性 | 文本词 `unknownitem` / `unknownability`；无道具/无特性是另外的 `noitem`/`noability`（`ReplayNothing`） | `UniversalPokemon.universal_items/abilities`，`interface.py:~297-330` |
| 对手招式 | 默认只在 `moves` 里出现已揭示的招式（`OpponentMoveObservationSpace` 才把它们编码到对手出场；更早的空间不编码，靠记忆） | `interface.py:1304` |
| 对手后备 | **不编码**对手后备的血量/状态/招式；只有 `opponents_remaining`（6−已倒下数）与“已揭示物种集合”；其余靠序列记忆 | `state_to_obs`；论文 §4/E.2 明确这是设计取舍（降低维度与分布偏移） |
| 队伍预览 | 只有对手 6 只物种的词（`opponent_teampreview`）；**己方首发选择不在策略的动作空间内**，默认随机，可外挂 `team_preview_model`（见 §3.7） | `MetamonPlayer.teampreview`，`env/metamon_player.py` |
| 太晶 | `can_tera` 标志；己方每只的 `tera_type`；对手太晶后才可见；动作 9–12 = 带太晶出招；非法太晶请求会被环境“善意修正”（`wants_tera and can_tera`） | `UniversalAction.action_idx_to_BattleOrder`，`interface.py:~735` |
| 己方真实配置 | 在线时从 Showdown `request` 消息拿到己方完整队伍、PP、技能（`metamon` backend）；**离线（replay）时己方 EV/性格/未使用招式/道具特性是“预测”的** | `metamon_battle.py:120`；`backward.py: fill_missing_team_info` |
| 努力值/性格/实际数值 | **完全不进入观测**：只有种族值/255 与 hp_pct；己方也看不到自己的实际 HP 数值或实际能力值 | `UniversalPokemon` 无相关字段 |
| 场地状态 | **每个类别只取一个 token**：`player_conditions/opponent_conditions` 取“最近设置的那一个侧场地”（`max(..., key=...)`），`weather`、`battle_field`（地形等）也各取一个；`effect` 同理只取一个 | `UniversalState.universal_conditions/universal_field/universal_weather`，`interface.py:~513-540`；`UniversalPokemon.from_*Pokemon` 的 `most_recent_effect` |
| 回合数/计时器 | 无（不在字段里） | `UniversalState` |

> **评论（我的判断，非作者原话）**：上表后三行对 Gen9 OU 是真实的信息缺口——ST/钉子/毒菱叠加、多层场地、实际数值（决定速度线与伤害区间）都被压缩或缺失，模型只能靠历史去“记”。论文承认过 PP 耗尽输局是最明显缺陷之一（附录 E.2），但对 hazards 压缩没有讨论。这是我们自己做观测空间时最值得改进的地方。

### 2.4 历史/上下文处理

- 每个时间步先经“回合编码器”（`MetamonTstepEncoder` 或 `MetamonPerceiverTstepEncoder`）压成一个向量，再喂给跨时间步的因果 Transformer。
- `max_seq_len=128`（`superkazam.gin`），**PAC 时代模型用滑动窗口注意力 `FlashAttention.window_size=(96,0)`**（`alakazam2/4.gin`、`superkazam.gin`；SmallRLGen9Beta/Abra/Kadabra 在 `pretrained.py:628-632` 覆盖为 (32,0)）。即有效记忆约 32–96 个决策步，不是论文里“整局历史”。README 也说明 PAC 时代“降低了对长期记忆的强调”。
- 数据增强 `token_mask_aug`：训练时随机把一部分文本 token 置为 `UNKNOWN`，迫使模型从前面步骤恢复信息（`unknown_token_mask`，`metamon_to_amago.py:543`）。
- 观测空间可有跨步状态（Expanded 的睡眠/冰冻/已揭示物种），所以 `ObservationSpace.reset()` 在每局开始必须调用。

### 2.5 动作空间与合法性掩码

[代码] `UniversalAction`（`interface.py:648`）、`DefaultActionSpace`（`:816`，13 个离散动作）：
- `0–3`：当前出场宝可梦的招式，**按招式名字母序**；
- `4–8`：切换到其余宝可梦，**按物种名字母序**（强制换人时也用这些）；
- `9–12`：Gen9 带太晶出招（字母序同上）。
- `MinimalActionSpace`（9 个）：论文版，把 ≥9 的动作折回；
- 特例：`Struggle`/`Recharge`/Gen1 的 `Fight` 全部映射到索引 0（`action_idx_to_BattleOrder`，`interface.py:~700-725`）。

合法性：环境在 `info["legal_actions"]` 给出，由 `MetamonAMAGOWrapper` 放进观测 `illegal_actions`（`metamon_to_amago.py:290`）；`MetamonMaskedActor/MetamonMaskedResidualActor` 把非法动作 logit 置 `-inf`（`:427, :453`；若全非法则不遮罩，防止崩溃，已知与 Gen9 复活祝福有关）。**论文时代的模型是在“无遮罩”下训练的**（见该类 docstring），遮罩后加入；非法动作在环境侧回退为随机合法动作（`on_invalid_order` → `choose_random_move`，`wrappers.py:~337`）。论文称 RL 策略对启发式对手有效动作率 97–99%、对人类 95–98%。

### 2.6 奖励函数

[代码] `DefaultShapedReward`（`interface.py:871`，论文版）：
```
r = 1.0*(damage_done + hp_gain)                     # 对手出场被削的 HP 比例 + 己方出场回复的 HP 比例（0-1 尺度）
  + 0.5*(gave_status - took_status)                 # 本步新造成/受到的异常状态
  + 1.0*(removed_pokemon - lost_pokemon)            # 本步击倒数 - 被击倒数
  + 100*victory                                      # ±100 胜负（胜=+1, 负=-1）
```
- `BinaryReward`：只有 ±100。
- `AggressiveShapedReward`（`:927`）：去掉状态项，**胜 +200 / 负 0**，击倒/被击倒系数 2.0；README/docstring 说明动机是抑制“死守输局”的毛病。**PAC 之后所有大模型（Minikazam、Kadabra2-4、Alakazam、Superkazam、Kakuna）都用它**。
- 训练时 AMAGO 再乘 `reward_multiplier=10`（`training/*.gin`）；critic 输出 96 个二热分桶，范围 `[-100, 2100]`（Kakuna 的 `superkazam.gin`）。

---

## 3. 模型与算法

### 3.1 总体：AMAGO 的“离线 RL = 优势过滤的行为克隆”

Metamon 并非 Q-learning/PPO。[代码+论文] 它用 AMAGO（`amago` v3.4.0）的 `MultiTaskAgent`：
- 演员损失 = **按优势加权的 BC**：`L_actor = -w(h,a)·log π(a|h)`，权重函数 `w` 来自 critic 优势估计 `A = Q(s,a) − E_{a'~π}[V]`（critic 集成上取均值）。
- critic 损失 = **二热（two-hot）分类** TD 回归（Dreamer-V3/MuZero 风格）+ PopArt，**多折扣因子并行训练**。
- 论文 Table 1 的几种 `w`：IL（w=1）、Exponential（AWAC，`exp(βA)`）、Binary（CRR，`A>0`）、Binary+MaxQ（再加 λ·Q 项）。论文结论：不同 `w` 在小模型上差别不大；最终（SynRL-V2）用 **Binary + 二热分类 critic**，理由是 critic 更准 → 过滤更“悲观”，适合数据以初中级人类对局为主的情况。

amago 默认 `Multigammas.discrete = [.1,.9,.95,.97,.99,.995]`，另加主折扣 `gamma=0.999` 共 7 个（`amago/agent.py:85-125, 655`）；IL 配置关闭 multigamma（`training/il.gin`）。

### 3.2 网络结构（Kakuna = `superkazam.gin`，[代码]）

| 组件 | 配置 |
|---|---|
| 回合编码器 | `MetamonPerceiverTstepEncoder`：token 维度 `d_model=168`，10 层，8 头，`latent_tokens=8`，`numerical_tokens=6`（把数字向量投成 6 个 token），`token_mask_aug=True`，dropout 0.08，`extra_emb_dim=18`（上一步动作/奖励），`max_tokens_per_turn=128`；Perceiver 式交叉注意力（实现于 `metamon_to_amago.py:688-975`，含 flex-attention 的块对角变体） |
| 序列模型 | `TformerTrajEncoder`：10 层，12 头，`d_model=900`，`d_ff=3600`，NormFormer norms + σReparam + head scaling，LayerNorm，LeakyReLU，**FlashAttention 滑窗 (96,0)**，`max_seq_len=128` |
| 演员 | `MetamonMaskedResidualActor`：特征 500，残差块 3×800，LeakyReLU，带非法动作遮罩 |
| critic | `NCriticsTwoHot`：6 个 critic，3 层 700 隐层，96 个二热 bin，`[-100,2100]`，不用 symlog；PopArt 开 |
| 规模 | HF 上 `kakuna/ckpts/policy_weights/policy_epoch_*.pt` 571.6MB（fp32 ≈ 143M 张量元素）。**该文件的 state_dict 含 target critic 与 6 个 critic，所以“142M”不等于推理时用到的参数量**；骨干（编码器+Transformer+actor）我估计约 100–110M（UNVERIFIED，仅按层维度估算） |

其他规模（读 `pretrained.py` + `configs/models/*.gin` + HF 文件大小）：

| 名称 | 配置 | 观测空间 | 奖励 | backend | 权重文件 |
|---|---|---|---|---|---|
| SmallIL/SmallRL/MediumRL/LargeRL（论文，Gen1-4） | small/medium/large_agent.gin；Large=9 层 Transformer、d_model 1280 | Default（87 词+48 数） | Default | poke-env | 约 15M/50M/200M |
| SyntheticRLV2（论文最终，Gen1-4） | `synthetic_multitaskagent.gin`（9 层、1280、20 头、d_ff 5120；`MetamonTstepEncoder` 5 层 d=160、11 个 scratch token）+ `binary_rl.gin` | Default | Default | poke-env | 200M |
| SmallRLGen9Beta | small_multitaskagent.gin + exp_rl.gin | PAC-TeamPreview | — | pokeagent | 56.6MB/epoch 文件 |
| **Abra**（2025-07，首个 Gen9） | medium_multitaskagent.gin + binary_rl.gin | PAC-TeamPreview | Default | pokeagent | 230.5MB（57M） |
| Kadabra/2/3/4 | medium_multitask / alakazam2/4.gin（Perceiver 编码器：d=108，8 层；Transformer d=768，8 层，d_ff 3072）+ alakazam3.gin | PAC-OpponentMove | Aggressive | pokeagent | 304MB（README 称 57M；我按文件大小推断含 target，UNVERIFIED） |
| Alakazam（修太晶 bug 后微调自 Kadabra4） | alakazam4.gin | OpponentMove（非 PAC） | Aggressive | metamon | 304MB |
| Minikazam | `minikazam.gin`：GRU 轨迹编码器（2×400）、Perceiver d=64/3 层、4 个 critic、普通 `Agent` | PAC-OpponentMove | Aggressive | pokeagent | 19MB（4.7M） |
| Superkazam | superkazam.gin + alakazam3.gin，PAC 数据集（11.6M 自博弈 + 4M 人类） | OpponentMove | Aggressive | metamon | 571.6MB |
| **Kakuna** | superkazam.gin + `kakuna.gin`，Superkazam 继续训练于 +7.8M 高温度探索自博弈（pac-exploratory），降低人类 replay 采样权重 | OpponentMove | Aggressive | metamon | 571.6MB |
| TaurosV0（Gen1 专用 50M） | grouped_v2_50m.gin | Grouped | — | — | Gen1 专用，与我们无关 |

### 3.3 训练超参（逐项）

**论文 Table 3**（Small/Medium/Large）：LR 1e-4，warmup 1000，target τ=0.004，TD 损失系数 10，grad clip 1.5，L2 1e-4，batch 32/40/48（“Synthetic”模型 48→96 条序列），critic 集成 4，Perceiver/摘要 token 数 4/6/11，max context 200/200/128。**算力：[论文] “single 8×NVIDIA A5000 GPU machine，至少 1M 梯度步”，默认取第 1M 步 checkpoint（= 开源权重的 epoch 40；一个 epoch = 25k 步，每 2 epoch 存一次）**；SyntheticRL-V2 约 1.2M 步仍在提升，因时间受限停止。**GPU 小时数论文没有给**，PAC 时代模型的算力未在论文/README/HF 卡片中说明（UNVERIFIED）。

**Kakuna 的训练配置（[代码] `configs/training/kakuna.gin`）**：
```
reward_multiplier = 10, tau(target) = 0.008
num_actions_for_value_in_critic_loss = 5, in_actor_loss = 4       # MultiTaskAgent 对 E_{a~π}[Q] 的采样数
online_coeff = 0.25, offline_coeff = 1.0                           # 含一点 -Q(s,a~π) 的“在线”项
fbc_filter_func = leaky_relu_filter(beta=.3, tau=1e-3, neg_slope=.05, clip_weights=[1e-3, 15])
learning_rate = 1e-4, grad_clip = 1.0, l2 = 1e-4, lr_warmup_steps = 10000, critic_loss_weight = 12.5
```
对比 `alakazam3.gin`（Superkazam/Kadabra3-4/Alakazam）：critic 采样 4、online 0.2、filter β=.4、LR 1.25e-4、warmup 2000；`binary_rl.gin`（Abra/Kadabra/Synthetic V2）：τ=0.004、critic 采样 3、online 0、`binary_filter`、LR 1.5e-4；`exp_rl.gin`（SmallRL）：`exp_filter(β=1, clip 100)`；`il.gin`：`fake_filter=True`、关闭 multigamma。
**训练 batch size 没有记录在公开 gin 里**（`rl/train.py` CLI 默认 `--batch_size_per_gpu 12`，8 卡则 96；Kakuna 具体值 UNVERIFIED）。`train.py` 的 `epochs=100, steps_per_epoch=25_000, ckpt_interval=2`；`padded_sampling="none"`；`mixed_precision="no"`（训练为 fp32，推理 FlashAttention 内部转 bf16，见 `amago/nets/transformer.py:~170`）。

### 3.4 IL 与离线 RL 的区别（只在“演员权重 w”与 critic 是否参与）

| 变体 | 实现 | 文件 |
|---|---|---|
| IL | `fake_filter=True`（权重恒 1）、关 multigamma、其余结构相同 | `training/il.gin` |
| 指数 RL | `exp(βA)`，β=1 或 .5，clip | `exp_rl.gin` |
| 二值 RL | `A>0`，可选加 MaxQ 项 | `binary_rl.gin`/`binary_maxq_rl.gin` |
| leaky ReLU 过滤 | 平滑版二值过滤，负优势仍留 5% 权重 | `alakazam*.gin`/`kakuna.gin` |
| 微调（post-PAC） | `MetamonFinetuneAgent`：慢 EMA “tortoise”影子网络 + 冻结基础模型 + 重要性采样修正 `ISAdvantageFilter`（序列级 sigmoid 权重） | `rl/custom_agent.py:227`，`training/finetune.gin` |

**缺失动作标签**：replay 里有些动作对战局无影响而不被记录，处理为：RL 管线里这些步的 actor/critic 损失被 `missing_action_mask` 屏蔽（`metamon_to_amago.py:1373-1393`）；论文早期是用小 BC-RNN 填补（附录 D.1）。

### 3.5 自博弈/合成数据生成

[代码+论文+README] 
- 流程：把多个 checkpoint/温度/队伍集组成的 agent 同时挂到**本地 Showdown 天梯**，由天梯随机撮合；每个 agent 是一个进程（`python -m metamon.rl.evaluate.ladder_self_play --config ... --format gen9ou --gpus ... --save_trajectories_to ...`，`rl/evaluate/ladder_self_play/launch_models.py`）。agent 每次启动随机抽取 checkpoint 与温度（配置示例温度 `[1.0,1.25,1.5,2.0]`），`--n_challenges 50` 局后重启，重启间隔 80 秒、超时 2700 秒；崩溃自动重启。轨迹以与 parsed-replays 相同的格式落盘。
- **高温度采样替代 ε-greedy**（`MetamonDiscrete`，`metamon_to_amago.py:337`）：logit/温度，概率裁剪 [0.001, 0.99]，因为有非法动作遮罩。
- 论文 §5.3 的核心经验：**“故意不真实”的多样化自博弈数据（Variety Set，每世代/分级 1k 支程序化生成的、首发很怪的队伍）比“真实队伍的自博弈”更能提升对人类的胜率**，因为不会让模型误以为自己在和自己玩（SynRL-V1+SelfPlay 对自己更强，但对人类提升不稳定）。后来的 PAC/Kakuna 数据集用 modern_replays / gl_05_26 等真实队伍集，规模到 11M+7M。
- **吞吐/服务器数量/GPU 时：均无公开数字**。仓库只有 `_StatsTracker` 打印 battles/hr（`launch_models.py:19`），没有公布结果；README 只说“批量收集”。ladder 环境固定连 `LocalhostServerConfiguration`（端口 8000，`wrappers.py:334`）。**“并行多少个 Showdown 服务器”无证据（UNVERIFIED）**。PAC 阶段 4thLesson 的写法（附录 E.1.3）给出一个量级：用 19 个基线模型本地天梯对战，每个小/中/大模型 3万/4万/5–10万局，合计约 80 万局 + 自己 checkpoint 之间 30–40 万局。
- 迭代：论文 SynRL-V0(2M 轨迹)→V1(3M)→V1+SP(5M)→V1++(5M，含不现实队伍与 IL 对手)→V2(从零训练，5M 合成 + 5万新人类局)；PAC 阶段 Abra→Kadabra→…→Kadabra4（数据 >11M）→Alakazam→Superkazam→Kakuna（再 +7.8M 高温度）；PA-Agent 的做法是 6 轮迭代、人类数据比例 100%→10%。

### 3.6 数据混合（`rl/dataset_config.py`、`configs/datasets/self_play_dset.yaml`）

```yaml
replay_weight: 0.05          # 人类 replay 的采样权重
self_play: {pac-base: 0.6, pac-exploratory: 0.35}
```
即现行配方中**人类重建数据只占 5% 的采样权重**，自博弈占 95%（与“almost all improvement … driven by self-play”一致）。

### 3.7 Team preview 模型（Gen9 专用）

`backend/team_preview/preview.py`：12 个输入（己方 6 + 对手 6）→ 预测 1 个首发；Perceiver 交叉注意力；训练集 `min_rating=1300` 的 Gen9 OU 人类 replay（`TeamPreviewDataset`）；仓库带一个 `gen9ou_high_elo_v4/best_model.pt`。接入方式 `--team_preview_checkpoint ... --team_preview_use_argmax`，**仅 `metamon` backend 有效**。不加该模型时 `MetamonPlayer.random_teampreview`，**即 Gen9 首发是随机的**——这是评测 Kakuna Gen9 时必须注意的隐含条件；README 的 71% GXE 是否使用了该模型 **UNVERIFIED**（README 评测命令示例不带该参数）。

### 3.8 测试时集成（实验性）

`rl/experimental/ensemble/`：`PastaMittens`（Kakuna 路由器家族）、`Exeggcute`（Tauros 家族）。启发式“提议者/评委”路由器（用 GXE 先验、每步不确定度、专家分歧选动作），**不训练**。作者称 KakunaEnsemble 是首个登顶人类 Showdown 天梯的 Metamon agent（**Gen1OU**）。对 Gen9 无公开数据。

---

## 4. 数据管线

### 4.1 获取与规模

| 数据集（HF `jakegrigsby/…`） | 内容/规模 | 许可 | 备注 |
|---|---|---|---|
| `metamon-raw-replays` | Showdown replay JSON（parquet），**2,681,841 局**，解压 22.6GB / 下载 5.7GB（v6，截至 2026-05-19）。版本：v1 536k；v3 加 **1.2M 局 Gen9 OU**（至 2025-06-16）；v4 +177k；v5 +389k；v6 +300k。用户名已化名 | **卡片未标许可**（UNVERIFIED；原始日志是 Showdown 用户上传内容） | 2021-2024 年因 replay 数据库故障缺口，该期多为比赛服 |
| `metamon-parsed-replays` | 重建后的轨迹；README 称 5.3M 条；**`gen9ou.tar.gz` 20.4GB**，gen1ou 1.26GB，gen2ou 0.72GB，gen3ou 2.69GB，gen4ou 1.91GB，另有 `revealed_teams.tar.gz`(1.0GB)、`replay_stats.tar.gz`；版本 v0…v6 | **CC-BY-NC-4.0**（卡片 tags/cardData） | 文件名 `{battle_id}_{ELO}_{pov用户}_vs_{对手}_{DD-MM-YYYY}_{WIN/LOSS}.json.lz4`；用户名已化名；每局两个视角各一条 |
| `metamon-parsed-pile` | 自博弈：`pac-base` 11M（Gen9OU lz4 tar 35.8GB）、`pac-exploratory` 7M（Gen9OU 18.9GB）、`pac-tauros` 4M（仅 Gen1） | **卡片未标许可**（UNVERIFIED；PokéAgent 卡片写“parsed format 可能因 bug 被废弃”） | 压缩 tar + sqlite 索引（Gen9OU 索引 1.2G+0.7G） |
| `metamon-teams` | 队伍集：`competitive`（<30 支/世代，Gen9 也是）、`modern_replays(_v2)`（Gen9 158k）、`gl_05_26`（Gen9 139k）、`hl_05_26`（Gen9 43k）等 | 未标 | **队伍只保证在生成时的 Showdown 版本下合法**，需在本地服务器上验证 |
| `metamon-usage-stats` | 按月、按评分分层的 Smogon 使用率（v4 起按 rating 分桶；v5 至 2026-04） | 未标 | 用于队伍预测 |

### 4.2 Replay 重建（[代码]）

1. **forward 阶段**（`replay_parser/forward.py`，`SimProtocol.interpret_message`，`:1320`）：对 spectator 日志逐条解释（`|switch|`、`|move|`、`|-terastallize|` 等，Gen9 的太晶见 `_parse_terastallize`，`:984`）。大量“显式不支持”会抛 `ForwardException`（`exceptions.py:17-157`：Zoroark 幻象、Mimic 未命中、未实现的 swapboost/招式特效、`NoSpeciesClause`、`Scalemons` 等）→ 整局丢弃。
2. **backward 阶段**（`backward.py`）：
   - `add_filled_final_turn`：对每一方，用 `fill_missing_team_info()` 把“对局结束时仍缺失的信息”（没出场的宝可梦、未揭示的招式/道具/特性/太晶属性/EV）用 **TeamPredictor** 补全，得到一个“全知的最终回合”；
   - 然后把这份信息 **沿时间轴向前回填**（`backfill_info`、`fresh_like`），所以己方在第 1 回合就“知道”自己整队（模拟第一人称）；对手一侧保持 spectator 视角（只含当时已揭示的信息）。
   - 处理变身/Zoroark 的特殊修正（`POVReplay._resolve_transforms/_resolve_zoroark`）。
   - **关键事实：玩家自己的未揭示配置是“预测”出来的，不是真值**——人类当时是在知道自己真实配置的前提下决策，因此这是数据中固有的噪声（论文附录 D.1 明确承认）。
3. **一致性检查**（`checks.py`）：`check_finished`（对局需有胜者且 ≥5 回合）、`check_replay_rules`（必须有 Species Clause，否则丢弃）、`check_forward_consistency`、`check_name_permanence`、`check_noun_spelling`、`check_info_filled`、`check_action_alignment`、`check_action_idxs`（动作能映射到 13 维动作）、`check_tera_consistency`（`MultipleTera` 等）、`check_forced_switching`。
4. **队伍预测器**（`team_prediction/predictor.py`，`TeamPredictor.get_legacy_team_builder`：按战斗日期分半年窗口 + 按玩家评分选 Smogon 评分档，`predictor.py:36-100`）：
   - `NaiveUsagePredictor`（`:121`，论文版）：对每个未知项独立地从使用率分布采样；
   - `ReplayPredictor`（`:245`，v1 数据集起）：从“历史 replay 里与已揭示信息一致的队伍/配置”候选中按评分采样，条件化更好；`__main__` 的 `--team_predictor` 默认仍是 `NaiveUsagePredictor`（`replay_parser/__main__.py:~110`），**重建 Gen9 数据集时应显式选 `ReplayPredictor`**（README 称现行数据用的是它，数据卡也写 v1 起换成 ReplayPredictor）。
   - 实验性 `TeamPredictionModel`（Team2Seq + MaskGIT 式并行解码，`prediction_model.py`、`iterative_decoder.py`）**尚未接入 parser**（README 明说）。
5. **过滤规则（训练时）**：`ParsedReplayDataset` 支持 `min_rating/max_rating/min_date/max_date/赢输过滤`（`data/parsed_replay_dset.py:272-322`；未评分对局按 1000 处理）；默认不过滤评分。论文指出人类数据“主要是初中级水平的决策”。

### 4.3 如果要为 Gen9 OU 自行重建数据集需要什么

- 原始 replay：`python -m metamon.data.download raw-replays`（5.7GB 下载，含所有世代），或自己爬 Showdown replay API（HF 数据已替你做了并化名）。
- 使用率统计：`metamon-usage-stats`（需与 replay 日期/评分匹配）。
- 命令：`python -m metamon.backend.replay_parser --format gen9ou --raw_replay_dir ... --output_dir ... --team_predictor ReplayPredictor --processes N`。解析耗时 **UNVERIFIED**（无公开数字；1.2M+ Gen9 局，纯 Python 多进程）。
- 依赖：该 parser 的数据类型 `pe_datatypes.py` 直接 `from poke_env.environment import Effect, Field, Move, SideCondition, Status, Weather, STACKABLE_CONDITIONS`——**需要 UT 的 poke-env 分叉**（该文件头注释说明了这一点，并建议“把分叉里的枚举复制粘贴进此文件”以完全脱离 poke-env）。
- **结论：不建议自己重建，除非要换观测内容；直接消费已解析的 `UniversalState` JSON（见 §9）。**

### 4.4 数据格式（读取接口）

`MetamonDataset.load_filename`（`parsed_replay_dset.py:466`）返回 `(obs 字典列表, {"chosen","legal","missing"}, rewards, dones)`；磁盘上是 lz4 JSON：`{"states": [UniversalState.to_dict()…], "actions": [int…]}`。由于存的是**结构化状态而非特征**，观测空间、奖励函数可以随时换——这是 Metamon 最值得借鉴的工程决策。

---

## 5. 已发布模型与结果

### 5.1 检查点清单（HF `jakegrigsby/metamon`，卡片声明 `license: apache-2.0`，`library_name: amago`）

目录（`model_tree.json`）含：`small/medium/large-il|rl*`、`synthetic-rl-v0|v1|v1++|v1+sp|v2`、`small-rl-gen9beta`、`abra`、`kadabra|2|3|4`、`alakazam`、`superkazam`、`minikazam`、`kakuna`、`tauros-v0`、`v2_*`（Gen1 小模型消融）。**每个 checkpoint 目录含全部 epoch 的 `policy_weights/policy_epoch_N.pt`（Kakuna 571.6MB×21），部分还有 `training_states/`（优化器状态，Abra 每个 epoch 388MB + 230MB 的 safetensors），可用于继续训练**。格式：PyTorch `torch.load` 的 state_dict（`.pt`），加载入口 `PretrainedModel.initialize_agent`（`pretrained.py:~200`）——严格校验 key/shape。`default_checkpoint`：Kakuna=34，Superkazam=50，Alakazam=8，Kadabra4=50，Abra=40，Minikazam=40。

### 5.2 评分（务必区分口径）

| 模型 | Gen9 OU 人类天梯 GXE | 其他世代 | 口径/可信度 |
|---|---|---|---|
| Abra（57M） | **50%** | — | [自报] 竞争队伍集（sample teams），README/PAC 论文 Table 1 |
| Kadabra3（57M） | **64%** | G1 80% | [自报]；作为组织者基线在 PAC 资格赛 Gen1 #1、Gen9 #2（仅次于 FoulPlay）——README 称“若公开的话” |
| **Kakuna（142M）** | **71%** | G1 82 / G2 70 / G3 63 / G4 64 | [自报]：“>700 局、约一个月”，**用 `competitive` 队伍集（<30 支样板队）**；GXE 受玩家池与时间影响，单世代样本量小（我估约百局，UNVERIFIED），**没有给 Glicko/Elo 或置信区间** |
| SyntheticRLV2（200M，论文） | 论文：Gen1 GXE 79.9%/Glicko-1 1761±35、Gen1 最高世界第 31；README 表 77%（后来重测）；Gen2-4：64–80% 区间，Gen3 两度进前 300 | 论文 [论文，估计在“前 10% 活跃用户”内]；论文自述对手池受锦标赛使 Glicko 通缩影响 |
| 本地内部榜（相对，**与公共天梯无关**） | Kakuna 76%/74%（competitive / modern_replays 队伍集），Superkazam、Kadabra4 75%/73%，Abra 61%/57%，Minikazam 50%/50%，论文模型 29–38% | README 明说“relative strength… no connection to ratings on the public ladder” |

**与 Foul Play / 启发式 / LLM 的比较**
- [论文 §5.4，Gen1-4，各 300 局，replay 队伍集] SynRL-V2 vs Foul Play：Gen1 胜、Gen2 相当、Gen3/4 平。——**这是 Gen1-4**，Foul Play 当时（2025-01）刚加入早期世代支持。
- [PAC 论文 附录 E.1.2，自报] Foul Play 在 Gen9 OU 自报 GXE >80%、峰值评分 1879，PAC Gen9 OU 排行榜第 1、决赛 50–14 击败 Q（基于 Metamon 的 50M Actor-Critic）。
- **Metamon 自己最强的公开 Gen9 OU 模型（Kakuna，71%）和 Foul Play 在 Gen9 OU 上没有公开的直接对战数据**（PAC 论文有 Head-to-head 热图，我只读到文字描述，数值 UNVERIFIED）。
- PAC 论文：组织者基线 Gen9 OU 中，FoulPlay 在所有指标上都胜过 **私有** 组织者基线；16 个晋级席位中 13 个是扩展 Metamon 公开基线的队伍。
- 启发式：PokeEnvHeuristic 在公共天梯上胜率很低（论文表 2：Gen1OU 21%、Gen3OU 23%、Gen4OU 37%，Gen9 随机对战 47%），Metamon 的 6 个启发式在 `baselines/heuristic/`。
- LLM：PokéLLMon（GPT-4o）在 Gen1-4 的长时程里明显劣于 SynRL-V2（75 局）；PAC 论文也认为 LLM/RL 差距仍大。

### 5.3 PokéAgent Challenge 结果与 Metamon 的角色（arXiv 2603.15563）

- Battling Track 有 Gen1 OU / Gen9 OU 两个赛道，百余支队伍；Metamon 与 PokéChamp 为组织者基线。
- Gen1 OU：**PA-Agent（基于 Metamon 的离线 RL，6 轮迭代、人类数据比例 100%→10%、从 Smogon/Metamon/社区队伍里锦标赛式筛队，资格赛 GXE 80.35%）夺冠**，决赛 50–28 胜 4thLesson（后者基于 SyntheticRLV2，用 Kron 优化器与 AID 激活替换 AdamW/LeakyReLU）。
- Gen9 OU：**FoulPlay（MCTS+poke-engine+对手配置推断）夺冠**；Q（50M，两阶段课程：先对启发式学“机制”，再对教练/自己迭代 v0→v6，Competitive v1 队伍集上胜率约 0.8）为亚军；PA-Agent、piploop 构成“追赶包”，介于最佳公开与私有基线之间；Porygon2AI（#8）是独立 RL。
- 对我们的启示：**赛场上能战胜 Metamon 公开基线的方法，在 Gen9 是“搜索+信念推断”，不是更大的 RL。**

### 5.4 已知弱点（Gen9 OU 视角，混合了文档与我的判断）

1. **首发随机**（默认无 team preview 模型）；Gen9 的队伍预览只给对手 6 个物种词，策略层面没有“选首发”这个动作（§3.7）。
2. **对队伍集高度敏感/过拟合**：README 明说 Metamon “overfit to” competitive 样板队；Kadabra 系列主要收益来自多样队伍评测（modern_replays_v2）。我们若用自己的队伍池，效果与 71% 不可直接类比。
3. **观测信息缺口**（§2.3 末尾）：单 token 的场地/天气/效果、无回合数、无实际数值、对手后备不编码。
4. **sim2sim 间隙**：replay 数据中“己方配置”是预测的；README 的原话是“replay data is perhaps best viewed as pretraining data for an offline-to-online finetuning problem”。
5. **PP 耗尽**（论文 E.2）、**输局死守**（AggressiveShapedReward 的动机）、长局累计错误（论文 §5.5）。
6. **没有搜索、没有显式对手配置推断**；全靠序列记忆。
7. **词表封闭**（v1：2541 词）；新机制/新宝可梦会变成 `UNKNOWN`。数据最新到 2026-05，而 Showdown OU 规则/禁用名单会变；`metamon-teams` 页面明确提醒队伍可能在新版本非法。
8. 已知实现 bug（PR/文档）：pokeagent backend 太晶属性缺失（PR #54，已在 Alakazam 起修复，旧模型靠 `PAC-*` 观测空间维持兼容）；`poke-env` backend 的 PP 计数/太晶损坏；Gen9 复活祝福引起“无合法动作”边界情况（`MetamonMaskedActor` 注释）。

---

## 6. 实际使用

### 6.1 安装要求（[代码]）

`pyproject.toml`：
```
requires-python >= 3.10   (README：“written and tested for linux and python 3.10+”，示例 conda python==3.10)
gymnasium>=0.26,<=0.29.1  torch>=2.6  numpy  gin-config  wandb  einops  tqdm  lz4  termcolor  rich
huggingface_hub  datasets  ratarmountcore
poke-env @ git+https://github.com/UT-Austin-RPL/poke-env.git       # 分叉，未固定 commit
amago    @ git+https://github.com/UT-Austin-RPL/amago@v3.4.0       # amago: torch>=2.5,<3, accelerate>=1.0, gym, gymnasium<=0.29.1
```
- **Python 3.12：[UNVERIFIED]** 无任何声明或 CI，仅“3.10+”。torch≥2.6 本身支持 3.12；`ratarmountcore`、`datasets` 通常也支持，但没人验证过。
- **flash-attn 事实上是 PAC 以后所有大模型的硬依赖**：`pretrained.py`/`*.gin` 为 Abra 起的模型显式设置 `amago.nets.transformer.FlashAttention`，而 `FlashAttention.__init__` 断言 `flash_attn is not None`（`amago/nets/transformer.py:163`）。需要 `pip install amago[flash]`（`ninja`, `packaging`, `flash-attn`），**需要匹配 torch/CUDA/Python 的轮子或本地编译（nvcc）**。RTX 4070 Ti 是 Ada（sm_89），flash-attn 2 支持。若 flash-attn 装不上，能否改成 `VanillaAttention` + 等价滑窗并保证数值一致 **UNVERIFIED**（`SmallRLGen9Beta` 的注释写“temporarily forced to flash attention until we can verify numerical stability of a switch to a standard pytorch sliding window inference alternative”，说明作者自己也没验证）。
- `torch.compile`：`MetamonTstepEncoder.inner_forward` 带 `@torch.compile`（`metamon_to_amago.py:610`），首次调用需编译（需要可用的 C++ 编译器/Triton）。
- `torch.nn.attention.flex_attention` 被 import（`metamon_to_amago.py:11`），需要较新的 torch。
- Showdown：子模块固定在 `d62d3a3`（2026-05）。我们项目 vendor 的 Showdown 是 2026-10-03 的 `9fb3a5b`，**较新；Metamon 的 replay parser/协议解释对新版本消息的兼容性 UNVERIFIED**（README：“Showdown undergoes constant updates… breaking changes are rare, but do happen”）。
- 工程质量信号：问题 #63（`ResidualActor.__init__() got an unexpected keyword argument 'discrete_dist_type'`）说明 amago 版本不匹配会直接报错——**务必精确固定 amago v3.4.0 与 poke-env 分叉的 commit**。

### 6.2 与 vanilla poke-env 的关系（直接回答“兼容吗”）

**不兼容。** 依据：
1. 分叉 `UT-Austin-RPL/poke-env`：版本 `0.8.3.3`，基于 2024-12 的上游（`git log`：最近上游合并为 `0c1430d Up version to 0.8.3`，2024-12-15，其后全是 Metamon 补丁）；`requirements.txt` 固定 `websockets==12.0`，`gymnasium`（不限版）。最近提交 `e1268d2` 2026-04-02 “fix fight mechanic in move”。相对当前上游 master 有 174 个文件差异。
2. Metamon 代码使用的 API（[代码] grep）：`from poke_env.player import OpenAIGymEnv, Player, BattleOrder`、`from poke_env.environment import Battle, AbstractBattle, Pokemon, Move, Effect, SideCondition, Status, Weather, ...`、`poke_env.concurrency.POKE_LOOP`、`Player._handle_battle_message/_create_battle/_battle_count_queue` 等私有属性、`poke_env.data.GenData`。我们的 `.venv` 里的 `poke-env 0.16.1`：**没有 `OpenAIGymEnv`**（只有 `environment/{env.py, singles_env.py, doubles_env.py}` 的 `PokeEnv`/`SinglesEnv`，基于 PettingZoo），`Battle` 类已挪到 `poke_env.battle`，对应的 import 会直接 `ImportError`。
3. 两者都叫 `poke_env`、依赖 gymnasium 版本冲突（Metamon `<=0.29.1` vs 我们 lock 的 `gymnasium 1.3.0`、numpy 2.5.3；Metamon 的 `pettingzoo` 无关）。
4. 论文/README 也承认：“we use a frozen fork of poke-env to maintain the performance of our original models”（`pe_datatypes.py` 文件头）。

**可行的替代方式（我的建议，未实测）**：把 Metamon 当作“外部进程”，不与我们的代码共享 Python 环境，通过 Showdown 协议（用户名/挑战）互联——见 §6.4。

### 6.3 在本地 Showdown 上跑一个 checkpoint（官方命令，[README/evaluate README]）

前置：独立环境（建议 conda/uv，**不要**用项目 venv）+ `export METAMON_CACHE_DIR=/path/with/space`（模型下载到 `$METAMON_CACHE_DIR/pretrained_models`）。启动 Showdown：
```bash
cd server/pokemon-showdown && npm install
node pokemon-showdown start --no-security          # 默认端口 8000
```
评测命令（仓库自带）：
```bash
# 对 6 个启发式基线（Gen9 OU）
python -m metamon.rl.evaluate --eval_type heuristic --agent Kakuna --gens 9 --formats ou --total_battles 100
# 上本地天梯，与任何在线 bot/人对打
python -m metamon.rl.evaluate --eval_type ladder --agent Kakuna --gens 9 --formats ou \
    --total_battles 50 --username MyUsername --team_set competitive
# 指名挑战（head-to-head）：两个进程，角色相反
python -m metamon.rl.evaluate --eval_type challenge --agent Kakuna --username PlayerA \
    --opponent_username PlayerB --role acceptor --gens 9 --formats ou --total_battles 50
```
可选：`--team_preview_checkpoint metamon/backend/team_preview/gen9ou_high_elo_v4/best_model.pt --team_preview_use_argmax`、`--temperature`、`--checkpoints`、`--battle_backend`、`--save_results_to`。
**端口硬编码为 8000**：`PokeEnvWrapper.server_configuration` 返回 `LocalhostServerConfiguration`（`env/wrappers.py:334`）。要用其他端口必须子类化覆盖（我们本机另有基准占 8000–8003，需注意）；PokéAgent 天梯是 `PokeAgentServerConfiguration`（wss://battling.pokeagentchallenge.com，**我们不应连接公共服务器**）。

### 6.4 如何与我们的 poke-env 0.16.1 bot 做 head-to-head（建议方案，未实测）

`ChallengeByUsername`（`wrappers.py:572`）的 `acceptor` 角色会 `await self.agent.accept_challenges(opponent_username, 1, None)`——只要对方用约定好的用户名在同一 Showdown 上发起 gen9ou 挑战即可，**对方不需要是 Metamon**。因此：
1. 独立环境里运行 Metamon 的 `--eval_type challenge --role acceptor --username KakunaBot --opponent_username OurBot --gens 9 --formats ou --total_battles N`；
2. 我们的 0.16.1 bot 用 `OurBot` 去 `send_challenges("KakunaBot", n, ...)`；
3. 队伍：Metamon 一侧用 `--team_set competitive`（<30 支样板队）；为公平，我们的 bot 也从这批 `.gen9ou_team` 文件里采样（`TeamSet` 文件扩展名需为 `.{format}_team`，`README` Team Sets 一节），或 Metamon 一侧传我们自己的队伍目录（`TeamSet("/path", "gen9ou")`，需写小脚本）；
4. 注意 Metamon 的 acceptor 每次只接受一场、依次进行（`_accept_challenge_loop` 注释），不能并行多场。若要并行，启动多对用户名（`h2h` launcher 就是这么做的，`rl/evaluate/h2h/`）。

### 6.5 推理开销（**均无实测数据，下面是推断**）

- 显存：Kakuna 权重 572MB（fp32 state_dict，含 critic 与 target），12GB 的 4070 Ti 绰绰有余；`agent.parallel_actors=1`、`env_mode="sync"`（`evaluate/common.py:101-102`）。
- 每决策延迟：回合编码器（~106 个 token，8 个 latent）+ 1 个 token 通过 10 层 d=900 的 Transformer（FlashAttention KV 缓存 `flash_attn_with_kvcache`，`amago/nets/transformer.py:181`）。纯计算量很小，**我估计单步 10–30ms 级（kernel 启动/Python 开销为主），UNVERIFIED**；远小于 Showdown 的网络往返与 poke-env 开销。
- 因此 Kakuna 在 4070 Ti 上**推理完全可行**；瓶颈会是 Showdown 单线程 Node 与 Python 解析（Metamon 的 `forward.SimProtocol` 是纯 Python，1.6k 行，每条消息都要走）。
- CPU 推理：`PretrainedModel` 的 `PokeAgent`/旧 backend 路径有“CPU & non-Ampere inference”支持（PR #4 标题），但 PAC 以后的模型硬依赖 flash-attn（CUDA），CPU 推理 **UNVERIFIED**。
- 训练：论文用 8×A5000(24GB)；README 称“Larger runs take days”。4070 Ti 12GB 上训练 Minikazam(4.7M GRU)/Small(15M) 级可行，57M 级需小 batch（默认 `--batch_size_per_gpu 12`）— **UNVERIFIED**；Kakuna 级别（142M，批 96 条×128 步）不建议本机训练，应租云（≥1×80GB 或多卡）。

---

## 7. 代码质量、维护状态与已知问题

- **活跃度**：clone 内 163 个提交；GitHub API：141 stars、36 forks、`pushed_at 2026-07-23`；**默认分支最近提交 2026-05-22（release/may-2026，#86）**；2026-08-11 有一个已关闭的 PR #88 “test time search + online training”（说明作者在尝试加搜索，**未合入默认分支**）；还有 1 个开放 PR #87 “Add gen7 compatibility”（2026-06-10，外部贡献）。提交按月：2025-06/07 高峰，2025-12 一波（PAC 更新），2026-01/03/05 各一批。
- **贡献者**：`jakegrigsby` 554 次，另外 `xieleo5` 4、`stevenstuff` 1、`yukezhu` 1——**本质是一人项目**，README 自称“hobby project … sporadic development and maintenance”。
- **测试**：**没有单元测试**（`find` 无 `test_*.py`；CI 只有 `black-fix.yml`）。`python -m metamon.env` 与 `team_construction/cli.py checks` 是仅有的自检。
- **API 稳定性**：`backend/README.md` 明写“Anything in this module is subject to change at any time :)”。观测特征改动会降低旧模型性能，所以用“backend 版本化”来维持兼容（§1.3）。
- **Issue 概况**（API 仅拉到 issue/PR 列表，评论仅读了部分）：真正的 issue 很少，值得关注的有：
  - #23（2025-06）“RL hangs in `init_envs()`，IL crashes on batch-size mismatch”——已修复；
  - #44（2025-07，8 条评论）“meet error when training”——WSL2 上并行 actor 卡在第一回合，**换 `async_env_mp_context="fork"` 解决**（作者后来把它做成 CLI 参数）。我们的开发环境正是 WSL2，**训练时留意**；
  - #50 “inference”（想逐步看动作概率），#63 `ResidualActor… discrete_dist_type`（amago 版本不匹配）、#80 `Cannot import metamon: circular import`（2026-03，已修）。
  - **没有找到公开 issue 讨论 “sim2sim gap/PP 计数/太晶 bug”**，这些只存在于 README「Battle Backends」表、PR #54、`tools/patch_pokeagent_gen9ou_trajs.py` 和论文附录中。
- **文档化的限制**：见 §5.4；README 的 “Known Bugs” 一栏。
- **潜在维护风险**：作者个人精力；Showdown 子模块与 poke-env 分叉都不会自动跟进上游；`gen7` 兼容 PR 久未处理。

---

## 8. 许可与复用分析

> 我不是律师；以下是基于仓库/HF 卡片文字的工程性判断，**商业用途前需另行法务确认**。

| 资产 | 许可（证据） | 能否用于我们 | 备注 |
|---|---|---|---|
| Metamon 代码 | **MIT**（`pyproject.toml`，GitHub license API `mit`） | 可以任意复用/修改，保留版权声明 | — |
| poke-env 分叉 | MIT（上游）；README 说明基于 hsahovic/poke-env | 同上 | 仅为运行 Metamon 需要 |
| amago | MIT（v3.4.0 pyproject） | 同上 | — |
| Pokémon Showdown | MIT（上游子模块） | 我们已在用 | — |
| **模型权重** | HF 卡片 `license: apache-2.0` | 技术上可以用作基线/对手/初始化 | **权重是用 CC-BY-NC 数据 + Showdown 用户 replay 训出来的，衍生关系的法律地位 UNVERIFIED**；Apache-2.0 声明与数据许可之间存在张力，若有商业计划需单独咨询 |
| `metamon-parsed-replays` | **CC-BY-NC-4.0** | **非商业**研究/个人项目可用，需署名；不得商用 | 数据卡含用户名化名处理 |
| `metamon-raw-replays` | 卡片**无许可声明**；原始内容是 Showdown 公开 replay | 研究使用通常没问题，二次分发/商用 UNVERIFIED | 与 Showdown/Smogon 站点条款相关 |
| `metamon-parsed-pile`/`teams`/`usage-stats` | 卡片**无许可声明** | 同上，建议按 NC 对待 | Smogon 使用率本身是公开统计 |

**实际可复用清单**
- **按原样复用**：Showdown 协议解析的“思路与测试数据”、`UniversalState` 字段设计、解析后的人类/自博弈数据（Gen9 OU 20.4GB + 54.7GB）、使用率统计、`team_preview` 的数据构造、`Kakuna/Superkazam/Alakazam/Abra` 权重作为对手/基线。
- **可改写后复用**：观测编码（强烈建议重做，见 §9）、奖励函数、训练配置（AMAGO 的 gin）、`team_construction`（组队流水线，但它依赖 Metamon agent 在本地服务器对战产生数据，吞吐低）。
- **不建议复用**：replay parser 本体（forward.py 1.6k 行 + replay_state 988 行 + 大量 Gen1-4 特例，与 poke-env 分叉的枚举纠缠；除非我们要重建数据）、`MetamonPlayer`/`PokeEnvWrapper`（绑死旧版 poke-env 内部 API）、`il/`（已弃用）。

---

## 9. 对我们项目的启示 / Recommendations

### 9.1 总体判断（有立场的）

1. **Metamon 是“强基线 + 数据/配方宝库”，不是我们的终局架构。** 71% GXE 的 Gen9 OU 水平大致对应“强业余/中高分段”（我对分位数没有证据，README 自称 90–99 百分位“取决于规则集”，**Gen9 的具体百分位 UNVERIFIED**），距离“超越 pro”还有明显差距；PAC 决赛的结果也表明搜索+配置推断路线在 Gen9 OU 更强。
2. **它没有解决我们最关心的两个模块**：对手配置信念推断、测试时搜索（`PR #88` 说明作者在尝试，但未发布）。
3. **最有价值的“可迁移资产”是数据与流程设计**：(i) 后端无关的 `UniversalState` 存储；(ii) 离线→自博弈迭代配方（高温度探索、降低人类数据权重、leaky-relu 过滤）；(iii) Perceiver 回合编码器 + 因果 Transformer + 二热 critic。

### 9.2 复用 / 重写 / 弃用

| 项 | 建议 | 理由与工作量（我的估计，单人，含调试） |
|---|---|---|
| Kakuna/Superkazam 等权重作评测对手 | **复用（立即）** | 独立 venv + challenge acceptor：**1–3 人日**。主要风险：flash-attn 轮子/CUDA、`torch.compile`、Python 3.10/3.11 环境、Showdown 版本漂移 |
| `metamon-parsed-replays/gen9ou` + `pile/gen9ou` 数据 | **复用数据格式** | 读取 JSON 不需要 Metamon 其余代码（`UniversalState.from_dict` 约 100 行可抄）。下载 ~20GB + ~55GB。**注意：数据中己方配置是预测值，太晶属性在 pokeagent 时期自博弈数据里是 `notype`（需用 `tools/patch_pokeagent_gen9ou_trajs.py` 补）**。工作量：写数据加载+自有观测编码 **3–5 人日** |
| 观测空间 | **重写** | 现有版本把场地/天气/效果压成单 token、无回合数、无实际数值/EV；Gen9 OU 最该补：多层 hazards、两侧全部屏障、速度档/已推断的对手实际数值、对手后备队伍信念、回合数、己方实际 HP 数值、太晶是否已用。保留“文本类别 + 数值”混合与稳定排序（字母序）、`rl2s` 上一步动作/奖励输入。**1–2 周**（含与 poke-env 0.16.1 `Battle` 对接并做离线/在线一致性测试） |
| replay parser | **不重写，只消费其输出** | 重写≈4k+ 行并需大量 Gen9 边缘情况验证；若将来需要新特征（如全部 hazards 层数），再考虑 fork 它并 vendoring 枚举（它自己建议这么做）。**从零重写 ≥ 3–4 周 + 持续维护** |
| 训练框架 AMAGO | **谨慎采用 / 参考** | AMAGO 是同作者库，MIT；Metamon 的 gin 配置可直接复现。但引入 AMAGO（accelerate、flash-attn、gin）会增加依赖面；若我们自己写 PyTorch 训练循环，实现 “优势加权 BC + 二热 critic + PopArt + multi-gamma” **约 1–2 周**。建议先用其 `finetune.py` 在 Minikazam/Abra 级别验证流程，再决定 |
| 队伍预览/首发模型 | **复用思路**，数据我们自己构造 | 模型很小（交叉注意力，输入 12 个物种 + 己方招/特性/道具）；`min_rating=1300` 的 Gen9 OU 数据。**1 周** |
| team_construction（组队） | **参考** | 它是“模拟→逻辑回归（含队内/对位交互项）→坐标上升/受限博弈均衡（double oracle）”，与我们 D5/M5 的目标一致；但需要大量本地对战产生 win 标签，吞吐受限于 Showdown。先读代码当方法参考。 |
| `MetamonPlayer`/`wrappers.py` | **弃用** | 绑定旧 poke-env 内部 API |

### 9.3 三种角色

**(a) 评测对手（推荐，立即）**
- 梯队：`Kakuna`（最强）→ `Superkazam/Kadabra4/Alakazam`（~73–75% 本地 GXE）→ `Abra`（弱）→ 6 个启发式（`PokeEnvHeuristic` 等，可只当 sanity check，用 poke-env 自带即可）。把 Metamon 当作“固定强度的外部参考”，比天梯更可复现。
- 必须固定的变量：队伍集（建议同一批 `.gen9ou_team`，`competitive` 是它最擅长的，所以会**高估它**；再加一组 `gl_05_26`/`hl_05_26` 看泛化）、`--temperature`（默认 1.0，采样策略；确定性 argmax 版本需自己改，**UNVERIFIED**）、首发（建议同时测“随机首发”和“加 team_preview_checkpoint”两种）、checkpoint 版本。
- 谨慎解读：Metamon 在 Gen9 OU 上自报 71% 是对人类天梯；**它对我们 bot 的胜率不能换算成 GXE/Elo**。按我们的 `design.md` D7 也别连公共服务器。
- 另一个有用的对手：Foul Play（同一个 poke-env 外壳，已在我们的待办里）。**Metamon vs Foul Play 在 Gen9 OU 的 head-to-head 我们可以自己测**，这将直接回答“BC/RL 路线与搜索路线差多少”。

**(b) BC / 离线 RL 预训练来源（推荐，数据层面）**
- 事实：现行配方里人类数据只占 5% 采样权重，真正提升来自 18M+ 自博弈；人类数据本身是“初中级决策 + 预测的己方配置”。**我们不应指望用 20GB 人类数据 BC 出强 agent。** 但它是很好的“行为先验/初始化/动作掩码合法性数据/队伍分布先验”。
- 建议流程：①用 `parsed-replays/gen9ou` 过滤 `min_rating≥1500`（或按赢方）做 BC 预训练（Metamon 的 IL 在论文里弱于 RL，但作为初始化够用）；②用 Kakuna 在**我们自己的队伍池**上本地自博弈生成数据（≈ `ladder_self_play` 的做法，但吞吐受 Showdown 限制，**无公开吞吐数字，我们需实测**）；③在我们自己的观测编码上做离线 RL/微调。
- 对于“Kakuna 的自博弈数据 + 我们自己的观测”：因为 `UniversalState` 已存，只要保存字段齐全就能转；但缺的信息（回合数、实际数值、全部 hazards、对手后备）**数据里根本没有**，这些要新观测就必须自己重新采集（重放 replay 或重新自博弈）。→ **重大限制，要提前决策：如果观测要重做，数据复用率会下降很多。**
- 初始化权重（用 Kakuna 当 BC 教师做蒸馏）：可行；但“蒸馏出来的上限=Kakuna”，除非后续有搜索/RL 提升环节。

**(c) 架构参考（推荐，部分采用）**
- 采纳：Perceiver 回合编码器（把 ~100 个类别 token + 数值压成固定向量，8 个 latent）；跨回合 Transformer（窗口 32–96，不是整局）；输出 13 动作 + 合法性遮罩；二热 critic + PopArt + multi-gamma；Binary/leaky-relu 优势过滤的 BC；高温度采样做探索；token mask 增强；稳定的字母序动作索引（让 `0–3` = 按名排序的招式）。
- 重新考虑：太晶当作 4 个额外动作（还是拆成“出招+太晶开关”）；是否把队伍预览/选首发纳入策略；是否加对手配置信念头（辅助损失：预测对手道具/特性/招式，类似 Foul Play 的推断）；加搜索（`PR #88` 的方向）。
- 规模参考：Minikazam（4.7M GRU）≈本地 GXE 50%，Abra（57M）≈61%，Alakazam/Kadabra4（~57–76M）≈73–75%，Kakuna(142M)≈76%。**数据多样性与自博弈迭代带来的提升大于参数量**（Superkazam→Kakuna 的提升来自数据，而非结构）。

### 9.4 主要风险

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 依赖冲突/不可同环境（poke-env 分叉 vs 0.16.1） | **高（必然）** | 独立环境 + 协议层互联；绝不 `pip install metamon` 到项目 venv |
| flash-attn/CUDA 在 WSL2+Python 3.12 上装不上 | 中 | 用 Python 3.10/3.11 独立环境；预编译轮子；退路是租云机跑对手服务 |
| Showdown 版本漂移导致 Metamon parser 报错 | 中 | 用 Metamon 子模块固定的 `d62d3a3` 起一个**独立**的 Showdown 供对战（不要与我们的 `9fb3a5b` 混用）；队伍需在该版本下合法 |
| 单人维护、无测试、分叉不跟上游 | 中 | 把我们依赖的部分（数据格式、权重）冻结；不指望上游持续更新 |
| 基线强度被误读（71% GXE 的口径） | 中 | 所有对比在同一队伍集/首发规则下自测；报告里分开写“自报/自测” |
| 数据许可（NC）与权重（Apache-2.0）不一致 | 低（研究）/高（商用） | 项目定位为研究；任何商业化前法务确认 |
| 观测重做导致数据复用率低 | 中 | 先评估“只改模型、不改观测”的方案（能直接用 20GB+55GB 数据）与“重做观测+重采集”的收益比 |
| 吞吐瓶颈（Showdown/Python 解析）限制自博弈规模 | **高** | 无公开吞吐数据；我们需实测（与 `design.md` D2 一致） |

### 9.5 建议的下一步（按优先级）

1. **（1–3 天）起一个独立的 Metamon 环境，用 challenge acceptor 跑 Kakuna，并让我们的 bot 去挑战**；先对启发式 sanity check，再对我们的 baseline bot，记录对局速度（局/小时、每步延迟）——**这是唯一能把本报告里所有 UNVERIFIED 的推理开销补成实测的办法**。
2. **（并行，1 天）下载 `metamon-parsed-replays/gen9ou` 的一个小切片**（先看 JSON 结构与几个 `UniversalState`），评估信息缺口（回合数/hazard 层数/EV）对我们需要的特征是否致命。
3. **（1 周）自测 Kakuna vs Foul Play（Gen9 OU，同队伍集，≥300 局，随机首发 vs team_preview 两种）**，得到 BC/RL 路线与搜索路线的本地相对强度。
4. 根据 1–3 的结果决定：是“在 Metamon 数据/Kakuna 之上做微调 + 加搜索”，还是“用自己的观测与自博弈从头做”。**我的倾向：混合——数据与教师用 Metamon，观测与搜索自己做。**

### 9.6 证据缺口（诚实声明）

- 没有安装/运行 Metamon，无任何实测延迟、吞吐、显存数字。
- Kakuna Gen9 OU 的 71% GXE 的样本量、置信区间、是否使用 team preview 模型、对手池构成均未公开（README/PAC 论文只有点估计）；Gen9 OU 的 Glicko/Elo 没有给出。
- Metamon vs Foul Play 在 Gen9 OU 的直接对战数值没有读到（只读到 PAC 文字摘要）。
- 自博弈数据生成的并行度、吞吐、GPU 小时，以及 PAC/Kakuna 的训练算力与 batch size：论文/README/HF 卡/issue 均无（论文只给出 8×A5000、≥1M 步的论文期模型）。
- Python 3.12 兼容性、无 flash-attn 时的替代、CPU 推理：无证据。
- 模型权重与 NC 数据之间的法律关系：无结论。
- 仓库 issue 的评论我只读了 #23/#44 与标题列表（GitHub API 限流）；PR #54 的细节仅通过代码与文档侧面确认。
- `team_construction` 模块（2026-05 新增）没有对应的论文或评测数字，其有效性 UNVERIFIED。
- Google Sheets 的详细评测表（README 引用）无法访问。

---

## 附录 A：关键代码索引

| 主题 | 位置 |
|---|---|
| `UniversalPokemon/State/Action` | `metamon/interface.py:273 / 483 / 648` |
| 动作空间/奖励 | `interface.py:816 (DefaultActionSpace) / 834 (Minimal) / 871 (DefaultShapedReward) / 927 (Aggressive) / 967 (Binary)` |
| 观测空间 | `interface.py:1011 (Default) / 1185 (Expanded) / 1285 (TeamPreview) / 1304 (OpponentMove) / 1331 (Grouped) / 1549 (PAC tera patch) / 1599 (Tokenized)` |
| 词表 | `metamon/tokenizer/DefaultObservationSpace-v1.json`（2541 词） |
| 模型注册与加载 | `metamon/rl/pretrained.py:105 (PretrainedModel)`；Kakuna `:878`；Abra `:667`；Alakazam `:816`；Superkazam `:848` |
| AMAGO 适配 | `metamon/rl/metamon_to_amago.py:270 (wrapper) / 337 (MetamonDiscrete) / 390,453 (Masked actors) / 566,626 (tstep encoders) / 1259 (Dataset) / 1346 (Experiment)` |
| 训练/微调 | `metamon/rl/train.py`、`finetune.py`、`custom_agent.py:227 (MetamonFinetuneAgent)` |
| 配置 | `metamon/rl/configs/models/superkazam.gin`、`configs/training/kakuna.gin`、`configs/datasets/self_play_dset.yaml` |
| 评测/自博弈 | `metamon/rl/evaluate/__main__.py`、`ladder_self_play/launch_models.py`、`h2h/`、`serve_matchup.py` |
| 在线环境 | `metamon/env/wrappers.py:170 (PokeEnvWrapper) / 334 (server_configuration) / 572 (ChallengeByUsername)`；`metamon_battle.py:19,707`；`metamon_player.py` |
| replay 解析 | `backend/replay_parser/forward.py:1320`、`backward.py`、`checks.py`、`parse_replays.py`、`__main__.py` |
| 队伍预测 | `backend/team_prediction/predictor.py:121,245`、`usage_stats/stat_reader.py:106` |
| 数据加载 | `metamon/data/parsed_replay_dset.py:272 (过滤) / 466 (load_filename)`、`data/download.py` |
| 队伍预览模型 | `backend/team_preview/preview.py` |
| 组队流水线 | `backend/team_construction/cli.py`（`build-pool/simulate/fit-*/best-response/equilibrium`） |

## 附录 B：外部来源

- 论文：arXiv 2504.04395（HTML v2，Table 3/4，附录 D/E，§5.3-5.5）；arXiv 2603.15563（Table 1、附录 B/D.1.2/E.1）。
- 仓库：https://github.com/UT-Austin-RPL/metamon ；poke-env 分叉：https://github.com/UT-Austin-RPL/poke-env ；amago：https://github.com/UT-Austin-RPL/amago（v3.4.0）。
- HF：`jakegrigsby/metamon`（模型）、`metamon-raw-replays`、`metamon-parsed-replays`（CC-BY-NC-4.0）、`metamon-parsed-pile`、`metamon-teams`、`metamon-usage-stats`。
- GitHub API：仓库元数据、贡献者、issue/PR 列表（#23、#44 评论）。
