# Foul Play 与 poke-engine 技术调研报告

> 调研日期：2026-10-04。目的：为「本地构建强 Gen9 OU 单打 AI」（Python / uv / poke-env 0.16.1 / AM5 CPU + RTX 4070 Ti + 64GB）决定技术路线。
>
> **方法**：浅克隆两个仓库后直接读源码（foul-play `8f541f8`，2026-10-03；poke-engine `c2dbbda`，2026-10-03；均 `--depth 50`，历史不完整），辅以博客、Smogon 帖、PokéAgent 论文（arXiv 2603.15563 的 HTML 全文，用脚本抽取文本后检索）、GitHub issue/PR 页面、PyPI/GitHub API。本报告中的**代码主张都给出文件路径和函数名/行号**，行号以上述 commit 为准。
>
> **标记约定**：`[自报]` = 作者本人说法（博客/论坛/README/论文中作者自写的附录），无第三方复现；`[外部]` = 组织方或第三方给出；`[UNVERIFIED]` = 本次未能核实，仅为推测或二手信息。博客/Smogon 帖/部分 issue 经 WebFetch 的小模型摘要后阅读，其中的数字是"摘要所报告的数字"，不是逐字核对。
>
> **未做的事（按任务约束）**：没有编译 Rust 引擎、没有 pip/uv 安装任何依赖、没有启动 Showdown、没有连接任何公共服务器的对战；仅对 `data.foulplay.cc` 做了两个静态 JSON 文件的 HTTP 下载以统计数据规模。因此**所有性能数字（nodes/s、单步延迟）都没有实测**。

---

## 0. 结论速览（TL;DR）

1. **Foul Play = Python 客户端（自写 websocket，不用 poke-env）+ Rust 引擎 poke-engine + 「采样对手配置 → 对每个采样世界跑 DUCT-MCTS → 汇总访问次数」**。搜索叶子不做 rollout，直接用**手写启发式估值函数**（sigmoid 压缩）。无神经网络、无训练。
2. **对手建模是它强的关键**：Smogon 使用率 + 论坛/replay 抓取的完整配置 + 约 10 条硬编码推理规则（速度区间、选择道具锁定、Heavy-Duty Boots、Assault Vest、反推伤害等）。过滤是**离散候选集的硬淘汰**，不是贝叶斯后验；采样时对"完整配置库"**均匀抽样**（刻意不按 count 加权），对 Smogon 边缘分布按乘积加权。
3. **强度**：Gen9 OU 自报峰值 Elo 1879 / GXE 80% / 前 100 `[自报]`；PokéAgent Challenge 资格赛 #1 种子，决赛 50–14 击败 Team Q `[外部，论文]`，胜过组织方私有 RL 基线 `[外部]`。已知弱点：防守/stall 队、长期规划、延迟收益招式（Toxic）、"知道对面是 bot 就可被利用" `[自报]`。
4. **poke-engine 是 MIT 许可**，Foul Play 本体是 **GPL-3.0**。这个许可差异决定了复用策略：**引擎可以放心依赖/vendor/fork；Foul Play 的 Python 代码只适合作为独立进程的对手或作为"思路参考"，不应 import 进我们的核心。**
5. **引擎保真度有限且没有与 Showdown 的对拍测试**（`tests/`、`src/` 中无 showdown 一致性测试；有 6 个未合并的机制修复 PR/issue，含 Mean Look/Block/Spider Web 禁换、Protect、催眠类招式、Doom Desire、Destiny Bond）。适合做"搜索用的近似模型"，**不适合当训练用的真值模拟器**。
6. **安装/运行的坑**：(a) 与 poke-env 0.16.1 依赖冲突（`websockets==14.1` vs `==16.1.1`），必须独立 venv；(b) PyPI 只有 sdist，需 Rust 工具链，且按世代用 feature 编译，Gen9 需 `terastallization` feature；(c) 团队文件默认路径对 `gen9ou` 不成立，需 `--team-name gen9/ou`；(d) 运行时联网拉 4 类外部数据（Smogon stats、`data.foulplay.cc`、`play.pokemonshowdown.com/data/sets`、登录用的 `play.pokemonshowdown.com/action.php`），本地离线运行需预置缓存并给 `login()` 打补丁；(e) 默认 `--search-time-ms 100 --search-parallelism 1` 是**弱配置**，作者实战用约 7 秒 × 8~14 个状态。
7. **对我们的建议（详见第 9 节）**：①立刻把 Foul Play 作为**外部进程评测对手**（0.5~1 天）；②把 poke-engine 当作**搜索/估值层的依赖**，在 poke-env 上自己写状态转换与信念采样（Laplace 项目已证明这条路可行）；③**clean-room 重写**集合推断规则，不复制 `fp/` 代码；④"学习型策略/价值 + 对采样世界做搜索"的混合需要 fork 引擎（MIT 允许）加 PUCT 先验与批量 NN 评估，约 2~4 周。

---

## 1. 概览与架构

### 1.1 代码规模与结构

foul-play：`fp/` 约 6,200 行 Python（`protocol.py` 2375 行、`inference.py` 800、`state.py` 827），测试 ~737 个 `def test`（`tests/test_battle_modifiers.py` 单文件 7340 行）；CI 为 ruff + pytest（`.github/workflows/ci.yml`，Python 3.13）。

```
run.py                       入口：asyncio.run(run_foul_play())
fp/config.py                 argparse 配置（单例 FoulPlayConfig）——没有 .env
fp/main.py                   run_foul_play(): 登录→循环对局
fp/websocket_client.py       PSWebsocketClient：自写 websocket 客户端（websockets + requests）
fp/run_battle.py             pokemon_battle(): 单局主循环
fp/battle/state.py           Battle / Battler / Pokemon / Move
fp/battle/protocol.py        Showdown 协议消息解析（~60 个 handler）
fp/battle/inference.py       速度/选择围巾/Boots/反推伤害等推理
fp/data/sets/*.py            Smogon stats / team datasets / randbats 数据集
fp/search/*.py               采样对手世界 + 调用引擎
fp/modes/*.py                random / standard / battle_factory / bss 模式
fp/generations.py            Gen1–9 + gen9champions 的机制差异开关
fp/teams/                    自带队伍（文本导出格式）与 packed 转换
```

### 1.2 与 Showdown 的连接

- **不使用 poke-env**。`fp/websocket_client.py: PSWebsocketClient` 直接用 `websockets` 连 `ws://…/showdown/websocket`，自己发 `/trn`、`/utm`、`/challenge`、`/search`、`/choose`、`/team`、`/timer on` 等命令（`create()`、`login()`、`update_team()`、`challenge_user()`、`accept_challenge()`、`search_for_match()`）。
- **登录总是访问公共登录服务器**：`login()`（`websocket_client.py:89`）无密码时 POST `https://play.pokemonshowdown.com/action.php?` 取 guest assertion，有密码时 POST `https://play.pokemonshowdown.com/api/login`；然后发送 `/trn name,0,assertion`。即使连本地服务器也会走这一步 → 离线环境需要打补丁（见 6.3）。
- 配置只有命令行参数（`fp/config.py: _FoulPlayConfig.configure`），**没有 .env**。`--websocket-uri` 支持简写 `ps`/`pokemonshowdown` → `wss://sim3.psim.us/showdown/websocket`，`local`/`localhost` → `ws://localhost:8000/showdown/websocket`（`get_websocket`，端口写死 8000）。

### 1.3 配置项（`fp/config.py`）

| 参数 | 默认 | 含义 |
|---|---|---|
| `--websocket-uri` `--ps-username` `--ps-password` `--ps-avatar` | 必填/None | 连接与账号；无密码=guest |
| `--bot-mode` | 必填 | `challenge_user` / `accept_challenge` / `search_ladder` |
| `--user-to-challenge` | None | challenge 模式必填 |
| `--pokemon-format` | 必填 | 如 `gen9ou`；`FormatSpec` 用正则解析世代、random/battlefactory/bss/champions/blitz/nationaldex（`fp/format_spec.py`）|
| `--smogon-stats-format` | =format | 覆盖用哪个 Smogon stats 文件 |
| `--search-time-ms` | **100** | **每个采样状态**的 MCTS 时间 |
| `--search-parallelism` | **1** | 同时搜索的采样状态数（进程数）|
| `--search-threads` | 1 | 每个状态内的线程数（引擎 ≥0.0.47 的共享树 MCTS）|
| `--team-preview-search-time-ms/-parallelism` | =上两项 | **仅 BSS 模式使用**（`fp/search/bss.py:80-90`）；标准 Gen9 OU 的队伍预览走 `standard_battle.search_params`，用 `--search-time-ms/--search-parallelism`（预览时采样数 ×2）|
| `--team-name` / `--team-list` | =format | 队伍文件/文件夹（文件夹则每局随机抽一个）/ 按顺序轮换的清单 |
| `--run-count` | 1 | 打几局后退出 |
| `--save-replay` | never | always/on_loss/on_win |
| `--room-name` | None | accept_challenge 模式时先加入的房间 |
| `--log-level` `--log-to-file` | DEBUG / off | 日志 |

### 1.4 支持的赛制

README：所有世代的**单打**，不支持 Dynamax 与 Z 招式（代码里仍残留 `can_dynamax`/`can_z` 分支，`modes/base.py: format_decision`，Dynamax 只在最后一只时使用）。`fp/modes/__init__.py` 注册 4 种模式：`RandomBattleMode`、`StandardBattleMode`、`BattleFactoryMode`、`BSSMode`；另有 `gen9champions`（Champions 规则，2026-07 才加入，commit `a338d59`）。机制差异由 `fp/generations.py: GenerationMechanics` 的一组开关承载（Heavy-Duty Boots 是否存在、麻痹速度除数、是否有队伍预览、是否支持反推伤害等）。

### 1.5 单局决策循环

`fp/run_battle.py: pokemon_battle()`：
1. `start_battle()`：`battle_mode(...).start_battle()` 完成首次握手，随后发送 `hf` 与 `/timer on`（自己开计时器）。
2. 循环 `receive_message()` → `async_update_battle(battle, msg)`（`fp/battle/protocol.py:2374`）。遇到 `|request|` 才返回 `action_required`；其它行进入 `battle.msg_list`，在 `process_battle_updates()`（`protocol.py:2290`）中**按行批量**经 `battle_modifiers_lookup` 字典分发给 ~60 个 handler，并调用 `check_speed_ranges`、`check_choicescarf`、`update_dataset_possibilities`、`check_heavydutyboots` 等推理函数。
3. 需要决策时 `async_pick_move(battle)`（`fp/modes/base.py`）：`deepcopy(battle)`，`user.update_from_request_json(request_json)`（我方信息以请求 JSON 为准），在 `ThreadPoolExecutor` 中跑 `find_best_move`（`fp/search/main.py:58`），再 `format_decision` 成 `/choose move X [terastallize]` 或 `/switch N`，附带 `rqid`。
4. 比赛结束发 `gg`，按 `--save-replay` 保存，`/leave`。

### 1.6 战斗状态跟踪

`fp/battle/state.py`：`Battle`（天气、场地、Trick Room、Gravity、`turn`、`rqid`、`request_json`、`time_remaining`）、`Battler`（`active`/`reserve`、side_conditions、wish、future_sight、`last_used_move`/`last_selected_move`）、`Pokemon`（`stats`/`evs`/`nature`、`speed_range`、`impossible_items`、`impossible_abilities`、`can_have_choice_item`、`item_inferred`、`hidden_power_possibilities`、`terastallized`/`tera_type`、`volatile_statuses` 及持续回合…）、`Move`（PP 按世代算）。我方的 nature/EV 来自队伍文件（`Battler.initialize_first_turn_user_from_json` 读 `team_dict`），因为请求 JSON 只给最终数值。

### 1.7 队伍与队伍预览（Gen9 OU）

- **队伍**：`fp/teams/load_team.py: load_team(name)` 读 `fp/teams/teams/<name>`（Showdown 文本导出格式），`team_converter.export_to_packed` 转 packed 后 `/utm`。仓库**只带 1 支 Gen9 OU 示例队**（`fp/teams/teams/gen9/ou/example`：Ting-Lu / Pelipper / Amoonguss / Dragapult / Iron Treads / Iron Valiant）。默认 `--team-name` 等于 format 字符串 `gen9ou`，而实际路径是 `gen9/ou`，**必须显式传 `--team-name gen9/ou`**（否则 `load_team` 抛 `ValueError("Path must be file or dir")`）。竞赛/天梯用的是作者自己的队，**未公开 `[UNVERIFIED]`**；论坛帖称测试多为 offense/balanced offense `[自报]`。Foul Play 本身**不做组队**。
- **队伍预览**：`fp/modes/base.py: handle_team_preview()` 构造"双方 active 为 dummy、`team_preview=True`"的 Battle，复用同一套采样+MCTS，**只选首发**：引擎在 `team_preview` 状态下，双方的候选动作就是"换上第 i 只"（`poke-engine/src/genx/state.rs: root_get_all_options`，约 1148–1171 行）；结果发 `/team {首发}{其余按原顺序}`。对手 6 只已知（预览可见），其配置照常采样。对手首发也被建模为 6 选 1 的 DUCT 对手。
- `fp/battle/state.py: smart_team_preview` 对 Urshifu 等预览不揭示形态的情况做替换（`gen9ou: urshifu → urshifurapidstrike`）。

---

## 2. 对手建模 / 集合预测

### 2.1 数据来源（`fp/data/sets/`）

| 来源 | 文件/函数 | 内容 | 获取方式 |
|---|---|---|---|
| Smogon 月度 stats（chaos JSON） | `smogon.py: SmogonSets._get_smogon_stats_file_name` | 用**上个月**的 `…/stats/{Y}-{M}/chaos/{format}-0.json`（`-0` = 不设评分门槛，代码注释"the higher ladder is for noobs"）；404 则回退两个月前 | 运行时 HTTP，缓存到 `fp/data/smogon_stats_cache/` |
| 团队完整配置库 `pokemon_full_sets.json` | `team_datasets.py: PKMN_SETS_REMOTE_BASE_URL = https://data.foulplay.cc/{mode}/{file}` | 键 `tera|ability|item|nature|evs|move1|…` → count。我们实测 gen9ou 文件：349 个物种、4,738 条不同完整配置、总 count 7,894 | 运行时 HTTP（作者的 S3 站），缓存到 `fp/data/pkmn_sets_cache/<format>/` |
| replay 移动组合 `replay_moves.json` | 同上 | `move1\|move2…` → count。gen9ou 实测：522 个物种、31,607 种移动组合、总 count 587,660（来源应为公开 replay；构建脚本**不在仓库**）| 同上 |
| Showdown 官方 sets | `team_datasets.py: get_ps_sets_file` → `play.pokemonshowdown.com/data/sets/{format}.json` | 合并进完整配置库（count 累加）| 同上 |
| Random Battle 集合 | `fp/data/sets/randbats.py` → `pkmn.github.io/randbats/data/full/{format}.json` | 随机对战的已知集合 | 同上 |
| 静态 pokedex/moves | `fp/data/pokedex.json`、`moves.json` + `fp/data/mods/*_mods.json` | 由 `fp/data/scripts/update_*.py` 用 `tsc`+`node` 编译 Showdown `moves.ts` 生成；GitHub Action 每天 00:00 自动提 PR（`.github/workflows/update-data.yml`）| 入库 |

> 重要：**`data.foulplay.cc` 是第三方（作者）托管的数据**，许可未声明 `[UNVERIFIED]`；缓存目录在包内（`DATA_DIR/pkmn_sets_cache`），离线使用需提前预热。

### 2.2 候选配置的生成与加权

两套数据结构（`fp/data/sets/base.py`）：
- `PokemonSet`：ability/item/nature/evs/count/tera_type（"特质组合"）；
- `PredictedPokemonSet` = `PokemonSet` + `PokemonMoveset`（"完整配置"）。

**Smogon 数据 → 特质组合**（`smogon.py: SmogonSets._initialize`）：把 stats 的 Spreads / Abilities / Items / Tera Types 做**笛卡尔积**，`count = ability_p × item_p × spread_p × tera_p`（即**假设四者相互独立**）；
- Spreads 先按 `spreads_are_alike`（同 nature 且各项 EV 相差 ≤ max_ev/4）合并，取前 20；Items 前 10；Tera 前 6；Moves 前 100（仅作边缘使用率，**不与配置关联**）；
- `_pokemon_set_makes_sense` 过滤明显不合理组合（Choice Band 要求攻击 EV ≥ 50% max；Specs 同理特攻；Scarf 要求速度 EV ≥ 80%；Life Orb/Expert Belt 要求有进攻 EV）。

**不合逻辑过滤**（`base.py: PredictedPokemonSet.set_makes_logical_sense`）：Light Clay 必须带屏障招；Toxic/Flame Orb 需要对应特性；Choice 道具最多 1 个"非对应类别招式"（Trick/U-turn/Volt Switch/Flip Turn 除外）；Life Orb 需要进攻 EV；Assault Vest 不得有变化招；Poison Heal ⇒ Toxic Orb；物理/特殊"强化招"要求对应 EV/性格/道具；Protect 不与 Choice 共存；Baton Pass 需要自强化招；Trick/Switcheroo 需要可被 Trick 的道具；非"功能性"攻击招不得放在对立进攻 EV 的配置上（`damaging_move_is_utility` 白名单：U-turn、Volt Switch、Flip Turn、Nuzzle、自爆类、Knock Off、先制技）。

### 2.3 对局中的"过滤器"（硬淘汰 + 排除集）

所有推断都发生在 `fp/battle/protocol.py: process_battle_updates` 批处理时：

| 推断 | 位置 | 逻辑 |
|---|---|---|
| **速度区间** | `inference.py: check_speed_ranges` | 同优先级、双方都出招且无换人/`cant`/混乱自伤/Custap/Quick Claw/Quick Draw 时，用我方实际速度（含能力等级、顺风、麻痹、围巾、Protosynthesis/Quark Drive）反推 `opponent.speed_range` 的 min 或 max（Trick Room 反向）。若对手可能有 Prankster/Unburden/天气加速特性等则跳过。`PokemonSet.speed_check` 按此区间与 nature/EV 算出的速度（含 Scarf ×1.5）淘汰候选 |
| **围巾** | `inference.py: check_choicescarf` | 对手后手方（我方更快）却先动，且没有速度修正可能 ⇒ 假设对手"最大速度 Jolly 252 速"（Trick Room 下"最慢"）仍比我们慢 ⇒ 判定其为 Choice Scarf，`item="choicescarf"`、`item_inferred=True` |
| **反推伤害（EV/性格/道具/特性）** | `inference.py: update_dataset_possibilities`/`_do_check` | 对每个候选配置：把它的 ability/item/nature/EV 写入对手副本，调用**引擎的 `calculate_damage`**（`search/poke_engine_helpers.py: poke_engine_get_damage_rolls`）算伤害区间 `[0.85·max, max]`；若实测伤害（HP% × max HP）低于 `0.975·下界 − level/20` 或高于 `1.025·上界 + level/20`（暴击用暴击最大值）则淘汰。伤害≈剩余 HP 时不检查下界（overkill）。排除：状态招、多段命中、Hidden Power、Pursuit/Counter/Mirror Coat/Metal Burst/Foul Play/未来预知等 ~13 招，以及 Ditto/Shedinja/Terapagos/Meloetta。**两个方向都做**：`damage_dealt`（对手打我方，推其攻击侧）与 `damage_received`（我方打对手，推其防御侧）|
| **选择道具排除** | `protocol.py: move()`（约 816–835 行）、`unlikely_to_have_choice_item`（70 行）| 同一只连续使用两个不同招式 ⇒ `can_have_choice_item=False`；使用带能力提升的变化招或 Substitute/Roost/Recover ⇒ 同样 |
| **突击背心 / 宝石 / Life Orb** | `protocol.py: move()`（约 840–900 行）| 用过变化招 ⇒ `impossible_items += assaultvest`；用过某属性攻击招 ⇒ `impossible_items += {type}gem`；用过攻击招且特性非 Sheer Force/Magic Guard ⇒ 排除 Life Orb |
| **Heavy-Duty Boots** | `inference.py: check_heavydutyboots` | 换入时场上有隐形岩/撒菱/毒菱/黏黏网而没有对应受伤/中毒/降速 ⇒ 判定带 Boots；受伤了 ⇒ 加入 `impossible_items` |
| **剩饭/黑泥/火毒宝珠** | `protocol.py: upkeep()`（约 2190–2204 行）| 回合末 HP < max ⇒ 排除 Leftovers/Black Sludge；无异常状态 ⇒ 排除 Flame/Toxic Orb |
| **特性** | `protocol.py: switch_or_drag`（约 430–480 行）、`immune`、`update_ability` | 换入时没触发的"入场特性"加入 `impossible_abilities`（天气/Intimidate 等有条件）；`-immune`、`-ability` 消息直接设定 |
| **天气持续时间 ⇒ 道具** | `protocol.py: weather()`（1302–1417 行）| 天气默认按 5 回合计；到期未结束 ⇒ 额外给 3 回合，并若天气来源是对手且其道具未知，则推定其持有对应天气延长石（Heat/Damp/Smooth/Icy Rock，`pkmn.item = item`）；已知持有该石头时按 8 回合计 |
| **Hidden Power 类型** | `inference.py: check_opponent_hiddenpower` | 根据效果（抵抗/克制/普通）缩小 `hidden_power_possibilities` |
| **Tera 属性** | `protocol.py: terastallize()`（1098）| 看到 `-terastallize` 则写入 `tera_type`；`set_makes_sense` 中若已太晶化且候选 tera 不同则淘汰 |
| **Zoroark/幻觉** | `modes/base.py: _switch_active_with_zoroark_from_reserves`、`protocol.py: illusion_end` | 仅在 Battle Factory 模式做"由招式推断 Zoroark"；标准模式靠 `-end Illusion` 消息修正 |

**兜底**：`_do_check` 若会淘汰全部候选则不淘汰（`"Would remove all possibilities, not removing any"`）；标准对战模式的完整配置库 `allow_emptying=True`（`modes/standard_battle.py: dataset_possibilities` 返回 `True`），清空后采样转入后备路径；Smogon 特质库永不清空。

**局限**：这是**离散集合上的硬淘汰**，没有似然/贝叶斯更新；对手"为什么选这招"（行为信息）基本不用来推配置，只用"出现了什么"；伤害反推依赖引擎伤害计算的保真度。

### 2.4 采样"完整世界"（`fp/search/standard_battles.py`）

`prepare_battles(battle, num_battles)`（296 行）：`num_battles` 次循环，每次 `deepcopy(battle)`，对**对手 active 与所有存活的后备**调用 `sample_pokemon`，最后 `opponent.lock_moves()`，每个世界权重 `1/num_battles`。无队伍预览的旧世代（Gen1–4）再用 `populate_standardbattle_unrevealed_pkmn` 补齐未见过的同伴：`predict_team_likelihood` 用 Smogon 的 `Teammates` 共现计数，按已见成员的平均条件概率排序，取前 50 加权抽样。**Gen9 OU 有队伍预览，6 只已知，不走该路径。**

单只 `_sample_pokemon`（168 行）三级回退：
1. **团队完整配置库**中与当前观测一致的全部配置（`get_all_remaining_sets`：ability/item/速度区间/tera 校验 + 已知招式是配置子集）。若非空且（尚未见任何招式 **或** 75% 概率，`random.random() < 0.75`）→ `random.choice`，**均匀抽样、不按 count 加权**（注释：count 并不代表真实分布）。
2. 完整库中仍有"特质+逻辑上合理"的配置但招式冲突 → 抽一个特质集合，再 `sample_pokemon_moveset_with_known_pkmn_set` 补招式：先从 replay 移动组合库按 count 加权（含更多已知招式的组合权重 ×2/×3），仍不足 4 招则用 Smogon 招式使用率补齐，使用率经 `adjust_probabilities_for_sampling`：`1-(1-rate)^(1/num_moves)` 做近似的"无放回 k 选"概率修正。
3. 退到 **Smogon 特质组合**（`get_all_remaining_trait_combinations` + `get_filtered_smogon_sets`）按乘积 count 加权，再补招式。

其它：`pokemon_guaranteed_move`（物种强制招式如 Zacian）、`set_most_likely_hidden_power`、Mega（仅 Gen6/7/NatDex/Champions）。

### 2.5 采样数量与时间预算

- 采样状态数 = `--search-parallelism`（`modes/standard_battle.py: search_params`，136 行）；**队伍预览、对手 active 招式 <3 个、或有血却 0 招已知时 ×2**，除非 `time_remaining ≤ 60 秒`（由 `|inactive|` 消息解析，`protocol.py: inactive`）才不翻倍。
- 每个状态搜索 `--search-time-ms`；进程池 `ProcessPoolExecutor(max_workers=parallelism)`（`search/main.py:71`），**所以采样数 = 2×parallelism 时会分两批串行跑 ⇒ 实际耗时约 2×search_time（`[UNVERIFIED]`，源于对代码的推断，未实测）**。
- 作者建议：约 7 秒/步、并行度 8 以后收益递减 `[自报，Smogon 帖]`；一位用户用"7000+14"设置在 gen9ou 天梯达 1930+ `[二手]`；issue #346 里另一位用户用"7s/8 states"。
- 汇总（`select_move_from_mcts_results`，`search/main.py:16`）：每个世界取 `side_one` 各动作的**访问次数占比**，乘 `1/N` 累加；保留 ≥ 最高者 75% 的候选，再**按概率加权随机抽取**（带混合策略色彩，降低被预测）。

---

## 3. 搜索

### 3.1 算法：Decoupled UCT（DUCT）MCTS，对采样世界做 root-parallel

- Foul Play **只用 MCTS**：`search/main.py: get_result_from_mcts` 调 `poke_engine.monte_carlo_tree_search(state, search_time_ms, threads=threads)`。引擎里仍保留 expectiminimax / iterative deepening（`src/search.rs`、Python `iterative_deepening_expectiminimax`、CLI），但 Foul Play 不调用。
- 引擎单线程版 `src/mcts.rs`：节点对 s1/s2 **各自维护 `MoveNode{total_score, visits}`**（`s1_options`/`s2_options`），选择阶段两侧**各自独立** `argmax UCB1`（`maximize_ucb_for_side`），得到联合动作 `(i,j)`；该联合动作对应一组随机结果节点（`children: HashMap<(parent_ptr, i, j), Box<[Node]>>`），按概率采样一个结果继续下行（`sample_node`）。这就是 DUCT：不构造收益矩阵，也不对联合动作做统计，只对边缘动作做统计。
- UCB1：`avg + sqrt(2·ln(N_parent)/n)`（`mcts.rs:213 MoveNode::ucb1`）。s2 一侧累积 `1 - score`（`backpropagate`）。**无先验、无温度、无 PUCT。**
- **没有 rollout**：`Node::rollout`（`mcts.rs:190`）若战斗结束返回 1/0，否则返回 `sigmoid(evaluate(state) - root_eval)`，`sigmoid(x)=1/(1+exp(-0.0125x))`（"~200 分≈1.0"）。即**一次扩展 + 一次静态估值**，估值相对根节点基线做差。
- 每次迭代结束后用 `reverse_instructions` 撤销状态变化——**不复制状态**（见 4.2）。
- 并行：
  - 主并行是 **Python 层 root-parallel**：N 个采样世界各开一个进程（`ProcessPoolExecutor`），各自独立树。（引擎的 PyO3 绑定未释放 GIL：`poke-engine-py/src/lib.rs` 里没有 `allow_threads`/`detach` → 因此用多进程。）
  - 引擎 ≥0.0.47（2026-06-13，commit `e8bda75` "Multi-threaded search"）新增 **共享树 + virtual loss（`VIRTUAL_LOSS_VISITS=3`）** 的多线程版 `src/mcts_threaded.rs: perform_mcts_shared_tree`（`DashMap` 全局子节点表），Foul Play 通过 `--search-threads` 启用。**竞赛时（2025-10/11）的引擎是 v0.0.46，应为单线程版 `[推断，UNVERIFIED]`**，因此论文称的 "root-parallelized" 指跨世界并行。
- 迭代预算：Python 绑定 `monte_carlo_tree_search(state, duration_ms, iterations=0, threads=1)`；`iterations>0` 时用固定迭代数（可用于**可复现评测**）；只有 1 个合法动作时强制 `iterations=100` 快速返回（`poke-engine-py/src/lib.rs: mcts`）；单树上限 10,000,000 次迭代。时间检查每 1000 次迭代一次。
- 深度：博客/论文称有希望的线路 10+ 回合，其余 2–3 回合（对比旧 expectiminimax 实际只能到 ~5 回合）`[自报]`。引擎 README 示例：100ms 单线程约 25,000 次迭代（`README.md` "monte-carlo-tree-search" 示例，硬件未说明，**未实测**）。

### 3.2 expectiminimax / iterative deepening（引擎内保留，Foul Play 不用）

`src/search.rs`：`expectiminimax_search` 对每个 (s1,s2) 动作对展开所有 instruction 分支；子博弈用 `pick_safest`（**纯策略 maximin：对每个己方动作取对手最坏回应，再取最大**）；可选 alpha-beta 剪枝；`iterative_deepen_expectiminimax` 用线程 + `sleep(max_time)` 停止信号，返回上一深度结果，并按上一轮最坏收益给己方动作重排序。**maximin 不是混合策略纳什，对"猜招博弈"过于悲观**，这是作者转向 MCTS 的原因之一。

### 3.3 估值函数（`poke-engine/src/genx/evaluate.rs`，Gen4–9 共用；Gen1/2/3 各有独立文件）

`evaluate(state) = Σ(己方存活) − Σ(对方存活)` 加若干场地项。常量如下（全部来自该文件）：

| 项 | 值 | 备注 |
|---|---|---|
| 存活宝可梦 `POKEMON_ALIVE` | +30 | **与物种无关**（不区分核心/垃圾）|
| 血量 `POKEMON_HP` | +100 × hp/maxhp | |
| 持有道具 | +10 | 有道具即加，不管种类 |
| 状态 | 冰冻 −40；睡眠 −25；麻痹 −25；剧毒 −30；中毒 −10；烧伤 = −25 × (物理招数) ，特攻>攻击则减半；Poison Heal +15；Guts/Marvel Scale/Quick Feet/Toxic Boost/Magic Guard 中毒 +10；Guts/Marvel Scale/Quick Feet 烧伤 = +50 | `evaluate_poison`、`evaluate_burned` |
| 单只得分下限 | `score<0 → 0` 后再 +30 | 防止低血量得负分诱导对手保活 |
| 能力等级（仅 active） | 攻击×30、特攻×30、速度×30、防御×15、特防×15，乘以 `boost_multiplier`：+6=3.3，+5=3.15，+4=3.0，+3=2.5，+2=2.0，+1=1.0，0=0，−1=−1.0，−2=−2.0，−3=−2.5，−4=−3.0，−5=−3.15，−6=−3.3 | 非线性、对称 |
| 寄生种子 | −30 | active |
| 替身 | +75 | active（Gen9 引擎 `misc: substitute 40→75` 可见调参）|
| 混乱 | −20 | active |
| 隐形岩 / 撒菱 / 毒菱 / 黏黏网 | −10×层 / −7×层 / −7×层 / −25 | 对每只存活宝可梦累加；Heavy-Duty Boots 免疫；Magic Guard 免疫岩与撒菱；撒菱/毒菱/网仅接地 |
| 反射壁 / 光墙 / 极光幕 / 神秘守护 / 顺风 / 治愈之愿 | +20 / +20 / +40 / +5 / +7 / +30（×回合/层数字段）| 己方为正、对方为负 |
| **已太晶化（`USED_TERA`）** | **−75**（己方用了 −75，对方用了 +75）| 倾向"留着太晶"；changelog "Tera penalty 50 → 75" |
| 终局 | 己方胜 = 1，负 = 0（MCTS 节点值）；expectiminimax 用 `±100×剩余深度 + evaluate` | |

**关键观察**：没有"物种价值""胜利条件""可替换性""回合数/节奏"、没有对"是否有 Rapid Spin/Defog""是否持有关键属性抗性"的建模；估值是**纯材料+状态+场地的线性启发式**，靠搜索深度弥补。所有权重"凭对元游戏的理解手调并通过自我对战测试"`[自报，Smogon 帖]`。

### 3.4 随机性与分支压缩（`src/genx/generate_instructions.rs`）

核心接口：`generate_instructions_from_move_pair(state, s1_move, s2_move, branch_on_damage) -> Vec<StateInstructions>`（4035 行）。每个结果 `StateInstructions{percentage, instruction_list}`，percentage 总和 100。

- **伤害 roll 分组**（`generate_instructions_from_move`，2023 行；伤害分支约 2391–2470）：不枚举 16 个 roll。令 `max_damage` 为引擎算出的最大伤害，`avg = ⌊0.925·max⌋`，`min = ⌊0.85·max⌋`：
  - 若 `branch_on_damage` 且 `max ≥ 对方当前HP > min`（可能击杀）：拆成"击杀分支"（概率 `(1−crit)·kill_rolls/16 + crit`，伤害 = 对方当前 HP）和"未击杀分支"（伤害 = 未击杀 roll 的平均，`compare_health_with_damage_multiples`）；
  - 若 `branch_on_damage` 且 `max < HP`：拆成暴击分支（概率 `crit_rate`，伤害 `0.925·暴击max`）与普通分支（`0.925·max`）；
  - 否则：只用平均伤害，**不分支暴击**（必暴击招例外）。
  - 暴击率：Gen4–6 1/16；Gen7+（含 Gen9）1/24（`BASE_CRIT_CHANCE`）；高暴击率招 1/8；Battle/Shell Armor 为 0。
- **分支深度**：单线程 MCTS 仅 **root 及其子节点** 做伤害分支（`mcts.rs:143 should_branch_on_damage = self.root || (*self.parent).root`）；共享树版 `depth < MCTS_DAMAGE_BRANCH_DEPTH(=2)`。更深处只用平均伤害，节省分支。
- **命中/未命中**：`check_move_hit_or_miss`（1194 行）按 `accuracy × 命中等级` 拆分支；**次要效果**（降能力、附状态、畏缩等）按概率拆分支（`secondary.chance`，约 1059–1075 行）；多段招式近似取固定段数（"Average is 3.2 so this is a fine approximation"，约 2368 行）；"branching is not implemented here so the engine assumes it always lasts 3 turns"（约 3266 行，疑为 Outrage/睡眠类）。
- **优先度/速度/平速**：`moves_first`（2593 行）：先看换人（换人先于出招，Pursuit 例外）→ 优先度 → Custap Berry → 有效速度（`get_effective_speed`，含天气/场地特性、顺风、麻痹、围巾、能力等级、Trick Room 反转）→ **速度相同 ⇒ `SideMovesFirst::SpeedTie`，两侧各 50% 分支**（4270 行）。
- **Protect 连续使用**：`CONSECUTIVE_PROTECT_CHANCE = 1/3`（Gen6+），成功概率 `(1/3)^n`（约 2009 行）。
- **同时行动**：由 DUCT 在"选择"层面处理；换人/强制换人（`force_switch`）、U-turn 后换人（`slow_uturn_move`、`switch_out_move_second_saved_move`）通过 side 标志建模。
- `remove_low_chance_instructions` 是编译 feature（默认不开），丢弃低概率分支。

### 3.5 已知理论弱点

1. **Determinization（确定化）**：每个采样世界内部是**完美信息博弈**，搜索把"对手配置"当作双方都已知；因此无法评估"信息价值/虚张声势"，也存在 strategy fusion。跨世界按访问数求和只是 root 层面的近似平均。
2. **对手是"同款 DUCT 玩家"**，不是人类行为模型；没有对"人类常用线路"的先验。
3. **估值函数浅**（见 3.3），对 stall/回血循环/保险（长期资源）判断差——作者承认"Long term decisions are hard to reason about with a search based engine that can only see perhaps 10 turns ahead""underestimates moves like toxic" `[自报]`。
4. **UCB1 + DUCT 在博弈中不保证收敛到纳什**；最终靠"75% 阈值 + 加权随机"做混合，是工程手段而非理论保证。
5. **伤害平均化**：深层只用平均 roll，对"需要精确 roll 的残血博弈"不准；击杀分支只在 root 近处。
6. **集合过滤是硬淘汰**：一旦推理规则出错（如把罕见配置排除）后续世界永远缺失该可能；有兜底但没有软权重。
7. **"Exploitable if the opponent knows it is playing a bot"** `[自报]`。

---

## 4. poke-engine 详解

### 4.1 概览

- 仓库 `pmariglia/poke-engine`，**MIT**（`LICENSE`，Copyright 2024 pmariglia；`Cargo.toml` `license-file`；GitHub SPDX=MIT）。版本 0.0.48（2026-07-19），PyPI 同版本，**仅 sdist**（`poke_engine-0.0.48.tar.gz`），故任何安装都要本地编译。
- 约 62.7k 行 Rust（`src/choices.rs` 20.7k 行手写招式表，`genx/generate_instructions.rs` 10.9k，`genx/abilities.rs` 2.9k，`genx/items.rs` 1.5k，`genx/choice_effects.rs` 1.8k，`genx/damage_calc.rs` 1.1k）；`#[test]` 约 1,054 个（`src/` + `tests/`）。
- 依赖极少：`dashmap`、`clap`、`rand`（`Cargo.toml`）；Python 绑定 `poke-engine-py`（PyO3 0.29，maturin 构建，`pyproject.toml`：`requires = maturin>=1.0,<2.0`）。

### 4.2 状态表示与"instruction"系统

- `State`（`src/state.rs:1321`）：`side_one`/`side_two`/`weather`/`terrain`/`trick_room`/`team_preview`/`use_last_used_move`/`use_damage_dealt`。
- `Side`（1056）：固定 6 只 × 4 招（`pokemon: SidePokemon`）、`active_index`、side_conditions、`volatile_statuses`（bitset）、`volatile_status_durations`、**能力等级存在 Side 上而不是每只宝可梦上**（换人即清零，符合规则）、`substitute_health`、wish、future_sight、`last_used_move`、`damage_dealt`（供 Counter/Mirror Coat）等。
- `Pokemon`（`src/state.rs:852`）：id/level/types/base_types/hp/maxhp/ability/base_ability/item/nature/evs/五项最终数值/status/rest_turns/sleep_turns/weight/`terastallized`/`tera_type`/`mega_evolved`/moves。物种、招式、特性、道具均为**编译期枚举**（`PokemonName`、`Choices`、`Abilities`、`Items`），未知物种直接 `panic!("Base stats not implemented for …")`（`genx/base_stats.rs:128`）——意味着**新物种/新招式必须发新版引擎**。
- 序列化：`State::serialize/deserialize`（`state.rs` doctest 是格式真值，约 2238 行起）；Python 里 `State.from_string/to_string`。
- **Instruction 系统**：`generate_instructions` 不返回新状态，而返回 `Vec<StateInstructions>`，每个含概率与 `Vec<Instruction>`（`src/instruction.rs`：Switch、Damage、Heal、Boost、ChangeStatus、ChangeSideCondition、ChangeWeather、ChangeItem、DecrementPP、ToggleTrickRoom… 约 50 种）。`State::apply_instructions` / `reverse_instructions` 可就地应用与撤销 ⇒ 搜索树遍历零拷贝（博客同述）。CLI 与 Python 都暴露 `generate_instructions(state, s1_move, s2_move)`。

### 4.3 世代与机制覆盖

- 编译 feature 互斥选择世代（`Cargo.toml`：`gen1`…`gen9`、`terastallization`(→gen9)、`champions`、`bss`）。`gen1/2/3` 有独立目录实现；`genx/`（Gen4–9）共用并用 `cfg` 区分（暴击率、Protect 概率、睡眠回合等）。Makefile 目标 `tera` = `gen9,terastallization`；Foul Play 对 Gen9 的 pin 为 `poke-engine/terastallization`（`requirements.txt`）。注意 **`gen9` 与 `terastallization` 是两个 feature**，`gen9` 本身不含太晶（`genx/state.rs:1069` `can_use_tera()` 返回 false，`#[cfg(feature="terastallization")]` 版才返回"该侧还没有太晶化过的宝可梦"）。
- Gen9 特色：太晶化（`MoveTera(idx)` 动作；Tera Blast、STAB 2.25 与适应力、"太晶属性招式 BP 下限 60"、Stellar、Revelation Dance 等见 `CHANGELOG.md` 的 Tera 条目）、~298 个特性（`genx/abilities.rs` 计数）、~1.5k 行道具逻辑、Protosynthesis/Quark Drive、Booster Energy 等。
- README 明说 **"This is not a perfect engine"**，"nowhere near as complete or robust as PokemonShowdown"。

**已知缺口 / 近似（来自代码注释与 open PR/issue）**：
- 禁换类（Mean Look / Block / Spider Web）未实现（open PR #15）；Protect 修复（#12）；催眠类招式（#14）；Doom Desire（#17）；替身 HP 换人不清除（#22）；Destiny Bond 最终同归于尽判定（issue #6）。
- 多段招式取固定段数；某些持续回合取固定值；`damage_dealt`/`last_used_move` 需 `use_*` 标志；对手 Illusion、Transform 等需 Foul Play 客户端特殊处理；Substitute 血量由客户端近似（`poke_engine_helpers.py: battler_to_poke_engine_side`："1/10 max HP if hit else 1/4"）。
- 对手的 Tera 属性在采样世界中**是已知的**（由采样决定），不是隐藏变量。
- 平均伤害 + 击杀/暴击分支的压缩使引擎**不是对 Showdown 的逐点等价**，而是期望保持的近似。

### 4.4 数据来源

- 引擎的 `choices.rs`（招式表）、`abilities.rs`、`items.rs`、`base_stats.rs` 是**手写/半手写的 Rust 源码**，是否有生成脚本不在仓库 `[UNVERIFIED]`。
- Foul Play 侧的 `pokedex.json`/`moves.json` 每日从 `smogon/pokemon-showdown` 自动同步（上文 2.1）；但**引擎枚举不会自动更新**，二者靠 Foul Play 的 `poke_engine_helpers.py` 用字符串 id 对接。

### 4.5 Rust / Python API

Python 包 `poke_engine`（`poke-engine-py/python/poke_engine/__init__.py` + `poke_engine.pyi`）：
- 数据类：`State`、`Side`、`Pokemon`、`Move`、`SideConditions`、`VolatileStatusDurations`；
- `monte_carlo_tree_search(state, duration_ms=1000, iterations=0, threads=1) -> MctsResult`（含各 s1/s2 动作 `visits`/`total_score`、`total_visits`）；
- `iterative_deepening_expectiminimax(state, duration_ms)`；
- `generate_instructions(state, s1_move, s2_move) -> list[StateInstructions]`；`State.apply_instructions/reverse_instructions`；
- **`calculate_damage(state, s1_move, s2_move, s1_moves_first) -> (rolls_s1, rolls_s2)`**——可直接当 **Python 伤害计算器**用（Foul Play 的反推伤害就用它）。
- Rust 公共 API（`src/lib.rs`）：`state`、`mcts`、`mcts_threaded`、`search`、`io`（CLI 解析）、`instruction`、`choices`。库名 `poke_engine`，可 `cargo` 依赖。
- 构建要求：Rust 工具链（Dockerfile 用 `rust:1.89`；`LazyLock` 需 ≥1.80；本机 `rustc 1.95.0` 已装）、maturin。按世代构建：`pip install … --config-settings="build-args=--features poke-engine/terastallization --no-default-features"`。

### 4.6 性能与基准

- 仓库自带基准程序 `data/benchmark.rs`（`cargo run --release --bin benchmark -f gen9randombattle.txt -i 250000 -n <threads>`），输入 `data/gen9randombattle.txt` 的若干状态串；**仓库内无已发布的 nodes/s 数字**。仅有的数字：README 示例 `-t 100` ⇒ "Total Iterations: 25000"（约 250k 次/秒/线程量级，硬件未知）。**本次未实测（任务约束）**。CHANGELOG 有多次 "MCTS Performance Improvements"/"Performance" 条目，说明性能是持续优化项。
- `Cargo.toml` release profile 仅 `debug = 1`，未设 LTO / codegen-units，存在进一步提速空间 `[推断]`。

### 4.7 正确性测试：与 Showdown 对拍？

- `grep -ri showdown tests src poke-engine-py/python` **零命中**：**没有与 Showdown 的一致性/差分测试**。测试是手写单元测试（`tests/test_battle_mechanics.rs`、`test_damage_dealt.rs`、`test_gen1/2/3.rs`、`test_bss_mechanics.rs`、`src/**` 内联 `#[test]` 约 1,054 个）与 Python `poke-engine-py/python/tests/test_poke_engine.py`。
- Foul Play 侧有 `tests/test_poke_engine_serialization.py`，只测序列化往返。
- 结论：**保真度由"作者按 Showdown 行为手写 + 实战发现 bug 再修"保证**，外部贡献者（Henauxg、SPGesus、kelvinfkr 等）持续补机制修复。

### 4.6a 多线程

见 3.1：单线程 `perform_mcts`；多线程 `perform_mcts_shared_tree`（共享 `DashMap` 子节点、virtual loss、原子计分）。Python 调用不释放 GIL。

---

## 5. 强度与证据

### 5.1 天梯成绩（按赛制，区分自报与外部）

| 赛制 | GXE | 峰值 Elo | 峰值排名 | 来源/可信度 |
|---|---|---|---|---|
| **Gen9 OU** | 80% | 1879 | Top 100 | 博客，`[自报]`；论文附录 E.1.2 复述 "over 80% GXE … (peak rating 1879)" `[自报，作者本人撰写]` |
| Gen9 OU（Smogon 帖摘要） | — | "≈1930+，Silver Badge" | — | 帖内说法，归属（作者还是用户）摘要不清，且与博客 1879 不一致 `[自报/二手，冲突]` |
| Gen9 OU（第三方账号） | 51.5% | 1190 | — | 搜索结果摘要：账号 `FoulPlay-Jp-Bot` 在 pokemonshowdown.com 用户页的当前数字；配置/队伍/搜索时间未知，**不能代表调优后的上限 `[UNVERIFIED]`** |
| Gen5 OU | 76% | ~1600 | Top 200 | 博客 `[自报]` |
| Gen3 OU | 71% | 1815 | #4 | 博客 `[自报]`；作者在帖中称"幸运的一次" |
| Gen9 Random | 88%（论文称 "over 90%"） | 2341 | Top 50 | 博客 / 论文，**两处数字不一致** `[自报]` |
| Gen9 Random Blitz | 84% | 2018 | #1 | 博客 |
| Gen9 Battle Factory | 81% | 1624 | #1 | 博客 |
| Gen9 LC | ~76–77% | 峰值 1486（Top 50）| — | Smogon 讨论帖中**他人**使用 Foul Play 的结果，称有 11 次掉线败 `[外部/二手]` |

（GXE 均为 Glicko 偏差 <50 后的估计，见博客脚注。）

### 5.2 PokéAgent Challenge（NeurIPS 2025）`[外部：组织方论文；其中附录 E 为选手自写]`

- Gen9 OU：FoulPlay 为资格赛 **#1 种子**，"outperformed private baselines by all metrics"（论文 B.2）；Q、PA-Agent、piploop 为"追赶集团"，处于最佳公开基线与最佳私有基线之间。
- 淘汰赛（B.3）：每对 bo99（先到 50 胜）。**决赛 FoulPlay 50–14 Team Q**；半决赛"close match"对 PA-Agent（具体比分在图 9，文本未给，本次未提取）。
- 16 个晋级名额中 13 个是扩展组织方公开 RL 基线（Metamon 系），**FoulPlay（Gen9 #1、Gen1 #8）和 Porygon2AI（Gen9 #8）是独立路线**。
- Team Q（亚军）：50M 参数 Actor-Critic，两阶段课程学习（Mechanics Phase 对启发式 bot → Strategy Phase 对固定"教练"与历史版本自我对战）。
- 基线参照（论文 Table 1，对人类天梯 GXE）：Metamon Abra（57M，Gen9）50%；Kadabra3（57M，Gen9）64%；Kakuna（142M，2025-12，Gen9）71%。FoulPlay 自报 80%，**但两者不是同一把尺子**（组织方 FH-BT 与 Showdown GXE 不同；各自面对的对手池不同）。
- 论文**没有在正文给出 FoulPlay 的 FH-BT/Elo 数值**（只有图 6/8，文本抽取不到）`[UNVERIFIED]`；比赛用的队伍、搜索时间/并行度、硬件论文没写 `[UNVERIFIED]`。
- 对比的重要含义：这是**在同一 AI 专用天梯上与 RL/LLM bot 的对战**，不等同于对高水平人类。

### 5.3 已知弱点

- 防守/stall 队、长期决策（搜索可见约 10 回合）、延迟收益招式（Toxic）`[自报]`；未显式处理 Unaware 等特性、队伍规模处理缺陷 issue #264（非队伍预览格式的队伍人数处理）。
- 无队伍预览的旧世代（Gen3）对隐藏宝可梦的预测"不科学"（Smogon 帖摘要）。
- 实战崩溃类 issue：Revival Blessing 崩溃（#244）、新 Mega 形态在 natdex 崩溃（#351）、对手 `/hideroom` 导致房间重命名后命令发错房间（#323，**与本地服务器无关**）。
- 与 Metamon 的对比：Metamon 是纯学习、无搜索、对"行为/人类风格"建模更强；Foul Play 是搜索 + 启发式，对"机制精确计算与信息推断"更强，对"策略层面的长期计划/stall"更弱。论文结论"specialist RL and search methods outperform LLM approaches"。

### 5.4 使用什么队伍

仓库仅 1 支 Gen9 OU 样例队（见 1.7）；论文/论坛未公开比赛用队。**没有队伍选择/优化逻辑**。→ 对我们的直接含义：作为评测对手时，**队伍由我们决定**，其强度取决于队伍与其"offense-friendly"偏好的契合度。

---

## 6. 实际使用

### 6.1 安装要求

- Python ≥3.11（README；CI/Docker 用 3.13）；Rust 工具链；`requirements.txt`：`requests==2.33.0`、`websockets==14.1`、`python-dateutil==2.8.0`、`poke-engine==0.0.48 --config-settings="build-args=--features poke-engine/terastallization --no-default-features"`。
- **与我们项目的冲突**：poke-env 0.16.1 依赖 `websockets==16.1.1`、`gymnasium==1.3.0`、`numpy>=2.0.2`、`orjson`、`pettingzoo`（PyPI 元数据实测）；Foul Play 固定 `websockets==14.1`、`python-dateutil==2.8.0`。**必须独立虚拟环境**（例如放在 `~/tools/foul-play/.venv`），不要装进项目 venv。项目 `requires-python >=3.12`，本机 Python 3.14.4：Foul Play 在 3.14 上是否可用（含 PyO3 0.29 构建）`[UNVERIFIED]`，建议 uv 指定 3.13（与其 CI/Docker 一致）。
- **uv 兼容性 `[UNVERIFIED]`**：requirements.txt 中的"行内 `--config-settings`"是 pip 语法；uv 对应参数为 `-C/--config-setting`，推荐形式 `uv pip install "poke-engine==0.0.48" -C "build-args=--features poke-engine/terastallization --no-default-features"`，再 `uv pip install requests websockets==14.1 python-dateutil`。需实测。
- Docker 路径可用：`make docker GEN=gen9`（Dockerfile 里把 requirements 的 feature 替换为 `poke-engine/${GEN}`，**注意 GEN=gen9 会编出不带太晶的引擎，应传 `GEN=terastallization`**，README 示例是 `gen4`，Gen9 的正确传法 `[UNVERIFIED]`）。
- 构建时间：大型 match 表的 20k+ 行 Rust，release 编译预计数分钟 `[UNVERIFIED，未编译]`。

### 6.2 资源与延迟

- 作者称"16GB RAM + 4 核近 5 年的中档 CPU"足够 `[自报]`。我们的机器是 AM5 多核（WSL 可见 10 逻辑核）/64GB，GPU 不被用到。
- 每步耗时 ≈ `search_time_ms × ⌈采样状态数 / parallelism⌉` + Python 开销（每步 `deepcopy(Battle)`、新建进程池、序列化 State 字符串）；开销量级**未测**。以 `--search-time-ms 1000 --search-parallelism 8` 估计每步约 1~2 秒；"满配" 7000ms×14 约 7~14 秒（可能超出 Showdown 本地计时器，需 `--timer` 设置）。
- **评测公平性**：Foul Play 是**时间制**搜索，CPU 被其它负载（我们的基准/训练）抢占会直接降低其强度；评测时应固定核心（`taskset`）或改用迭代数预算（需自己改 `search/main.py` 把 `iterations` 传给 `monte_carlo_tree_search`，该参数 Python 绑定已支持）。

### 6.3 对本地 Showdown 运行（**未执行，仅给出步骤**）

前提：本地 Showdown 端口**避开 8000–8003**（当前被基准占用；且 Foul Play 的 `local` 简写写死 8000，所以需显式给完整 URI）。

```bash
# 1) 独立环境（不要用项目 venv）
uv venv --python 3.13 ~/tools/foul-play/.venv
cd ~/tools/foul-play && git clone https://github.com/pmariglia/foul-play && cd foul-play
uv pip install -p ~/tools/foul-play/.venv "poke-engine==0.0.48" \
   -C "build-args=--features poke-engine/terastallization --no-default-features"   # [UNVERIFIED 语法]
uv pip install -p ~/tools/foul-play/.venv requests==2.33.0 websockets==14.1 python-dateutil==2.8.0

# 2) 预热数据缓存（联网一次）：先对任意可联网的 Showdown 之外的方式拉取
#    https://data.foulplay.cc/gen9ou/{pokemon_full_sets,replay_moves}.json
#    https://play.pokemonshowdown.com/data/sets/gen9ou.json
#    https://www.smogon.com/stats/<上月>/chaos/gen9ou-0.json
#    放入 fp/data/pkmn_sets_cache/gen9ou/ 与 fp/data/smogon_stats_cache/（文件名见 get_sets_file / _get_smogon_stats_json）

# 3) 作为被挑战的对手（我方 poke-env 玩家 challenge 它）
python run.py \
  --websocket-uri ws://localhost:<PORT>/showdown/websocket \
  --ps-username FoulPlayBot --bot-mode accept_challenge \
  --pokemon-format gen9ou --team-name gen9/ou \
  --search-time-ms 1000 --search-parallelism 8 --run-count 200
# 4) 或让它主动挑战我方：--bot-mode challenge_user --user-to-challenge <我方用户名>
```

需要处理的点：
1. **登录补丁**：`PSWebsocketClient.login()` 无条件向 `play.pokemonshowdown.com` 取 assertion。本地离线时应在 `login()` 里对 `ws://localhost` 改发 `/trn <name>,0,`（poke-env 对本地服务器就这么做）。这是否在联网情况下也能被本地服务器接受 `[UNVERIFIED]`。
2. `accept_challenge` 会接受**任何**用户发来的、format 完全匹配的挑战（`websocket_client.py: accept_challenge`，解析 `|pm|` 且 `split_msg[5] == battle_format`）。
3. 队伍：`--team-name gen9/ou`（文件夹则每局随机抽；也可用 `--team-list` 轮换）。公平对战时建议**双方使用同一队伍池并交换持队**。
4. Foul Play 自己发 `hf`/`gg` 聊天和 `/timer on`；本地服务器计时器策略会影响它（它仅在 `time_remaining ≤ 60` 时减半采样数）。
5. Showdown 本地对战以 `--run-count` 循环；每局结束后 `leave_battle`。
6. 绝不要把它接到公共服务器/天梯做测试（任务约束）。

**本地修复（2026-10-09，只改 `external/foul-play` 里的代码，不进本仓库；补丁在 `external/foul-play-local-fixes.patch`，上游 8f541f8 时尚未修复）**：
- 场地解析：`fp/battle/protocol.py` 的 `fieldstart` / `fieldend` 把戏法空间、重力以外的所有场地效果都当成 terrain 存下，局面交给 poke-engine 时 `get_terrain_string` 遇到 `magicroom`（奇妙空间等同理）就抛 `ValueError`，进程退出。改为：只有四种真正的场地才存成 terrain，其余场地效果记日志后忽略（poke-engine 本来也不模拟它们，与我们 `engine_state.py` 的处理相同）；其结束同样忽略，不会清掉同时存在的场地。
- `fp/search/main.py` 打印搜索结果时，被选中的选项访问数为 0 会除零（`ZeroDivisionError`），改为除以 max(访问数, 1)。
- 只影响原先会崩溃的对局，其余对局里 Foul Play 的行为不变，修复前后的成绩可比。第一次暴露：偏门池（`offmeta200`）的 Foul Play 评估，8 条线里 2 条因此崩溃。

### 6.4 能否作为库调用

**不是为库设计的**：`FoulPlayConfig` 是全局单例并由 `argparse` 从 `sys.argv` 填充（`config.py: configure`），数据集在模式对象里是进程级单例（`BattleMode.__deepcopy__` 返回 self，`modes/base.py`），`apply_mods` 会就地改写全局 `pokedex`/`all_move_json`（`main.py: check_dictionaries_are_unmodified` 会在被改动时 `exit(1)`）。技术上可以手工设置 `FoulPlayConfig.*` 后直接调用 `fp.search.main.find_best_move(battle)`（测试里的 `conftest.py` 就这么干），并把 poke-env 的原始消息喂给 `fp.battle.protocol.async_update_battle`，但：(a) 这是**GPL 代码的 import**（见 8 节）；(b) 全局状态使多局并行困难。**推荐用"独立进程 + websocket"**。

---

## 7. 代码质量与维护

| 项 | foul-play | poke-engine |
|---|---|---|
| 最近提交 | 2026-10-03（bot 每日数据同步 PR #352）；人工提交 2026-09-06 | 2026-10-03 |
| 创建 | 2019-03 | 2020-03 |
| 星/分叉 | 383 / 222（API，2026-10-04） | 52 / 27 |
| 贡献者（GitHub contributors API） | pmariglia 815；github-actions[bot] 38；Andyloris 15；jpf4e 6；… | pmariglia 880；jpf4e 5；Henauxg 3；kelvinfkr 2；SPGesus 2 |
| 开放 issue/PR | 5 个 issue（#351 natdex 新 Mega 崩溃、#323 /hideroom 改房名、#264 队伍人数、#244 Revival Blessing 崩溃、#3 旧 KeyError）| 7（含 6 个社区机制修复 PR + #6 Destiny Bond）|
| 活跃度 | 2026 年仍高频（Champions/BSS 重构 `a338d59`，2026-07）| 2026-01 起 68 个提交；v0.0.47 → v0.0.48 一个月 |
| 测试 | ~737 个 pytest；CI（ruff+pytest）| ~1,054 个 Rust 测试；CI 跑 `make ci`（每世代 feature 全跑）|
| 发布 | 无 GitHub Release；依赖固定的 PyPI 引擎版本 | CHANGELOG（git-cliff）、PyPI sdist |

维护者基本是**单人项目**（巴士因子 1），但极其活跃；近期工作重心偏 Champions/BSS 新赛制，Gen9 OU 相关修复仍在进行（如 "lifeorb requires at least a little bit of offensive investment"，2026-07）。一个值得注意的信号：issue #346（2026-08）有人用 poke-engine 做自己的 bot，并想以 stock foul-play 作校准基线——说明该引擎已被当作第三方搜索底座使用。外部例子：**Laplace**（trylaplaceai.com，Gen9 Random，自报 Elo 2231/GXE 83.3）声明"search design starts from Foul Play"，用 poke-env 追踪状态，采样 8 个世界、各 ~150ms 调 poke-engine MCTS，再用 368 特征小网络仅对"近似平局"的 5–10% 回合重排序 `[自报，网页摘要]`。

---

## 8. 许可与复用分析（非法律意见）

| 组件 | 许可 | 依据 |
|---|---|---|
| Foul Play（`fp/`、`run.py` 等） | **GPL-3.0** | 仓库 `LICENSE`（GPL v3 全文）；GitHub SPDX=GPL-3.0；README 未另有说明 |
| poke-engine（Rust + Python 绑定） | **MIT** | `LICENSE`；Cargo `license-file`；GitHub SPDX=MIT（PyPI 元数据 `license` 字段为空）|
| `data.foulplay.cc` 数据 | **未声明** `[UNVERIFIED]` | 作者 S3 站，仓库无数据许可声明 |
| Smogon 月度 stats | 公开数据（无明确许可） | smogon.com/stats |
| Showdown 数据（`pokedex.json` 等） | Showdown 为 MIT | `smogon/pokemon-showdown` |

**这对我们意味着什么**（假设我们的项目最终不以 GPL 发布）：

1. **作为独立进程的评测对手**（websocket 连我们的本地服务器）：**安全**。运行 GPL 程序、与之通信并不使我们的代码成为其衍生作品；GPL 义务只在**分发**时触发。内部使用修改版（如登录补丁）也不触发分发义务。
2. **import `fp.*` 到我们自己的包**（`find_best_move`、`Battle`、推理函数）：我们的合成作品将被视为包含 GPL 代码；**一旦分发/发布**就需整体按 GPL-3.0 开源。仅内部私用则无分发义务，但会给未来开源/发表带来负担。**不建议**作为核心依赖。
3. **借鉴思路/算法，自己重写**：思想、算法、机制事实（如"没受 Stealth Rock 伤害 ⇒ 可能有 Boots"、速度区间推断）不受版权保护；**受保护的是具体代码表达**。做法：读懂规则→用我们的数据结构（poke-env `Pokemon`）独立实现，不逐行翻译；规则清单（2.3 节）本身可以作为需求。
4. **poke-engine（MIT）**：可依赖、vendor、fork、修改（含加入 PUCT/NN 评估）、再分发，只需保留版权与许可声明。这是最友好的复用对象。
5. 数据：`data.foulplay.cc` 的 JSON 可用于本地缓存做评测，但**不应在对外分发物中打包**（许可不明）；我们可以按同样思路**自己从 Smogon stats / replay 重建**同类数据（需要自己的 replay 抽取管线）。

可复用角色对照：

| 角色 | 复用方式 | 许可风险 | 保真/限制 |
|---|---|---|---|
| (a) 评测对手 | 外部进程，`accept_challenge` | 无 | 强度取决于时间预算与队伍；时间制搜索对 CPU 争用敏感 |
| (b) 搜索/信念参考设计 | 读代码，clean-room 重写 | 低（别抄代码）| 设计可借鉴：采样世界 + DUCT + 估值 |
| (c) 集合推断逻辑来源 | 只借规则清单/思路，自己实现 | 低 | 规则覆盖面有限，且依赖伤害计算保真 |
| (d) 搜索/训练数据模拟器 | 依赖 poke-engine（MIT）| 无 | **保真度不足**：无 Showdown 对拍；Gen9 有已知缺口；用作"搜索模型"可，用作 RL 训练真值需先做差分测试 |

---

## 9. 对我们项目的启示 / Recommendations

### 9.1 总体判断

- Foul Play 的价值不是"一个我们能直接超越的 bot"，而是**一个高质量的、已被天梯与竞赛验证的信息推断 + 采样搜索参照物**，且它给出了我们混合系统里最难手写的一环——**对手配置信念**——的完整工程范例。
- 论文与博客一致认为：在 OU 这类开放组队赛制，**集合预测的重要性可能不亚于搜索本身**（博客结果：已知集合的 Random Battle 达 88%+ GXE，OU 只有 80%/1879）。这与我们"学习型策略/价值 + 搜索"的路线互补：**信念模型 + 搜索是 Jaxcalibur/PokaiTrainer/Ataraxos 一类系统共同的"测试时搜索"部分**（与项目 `doc/research.md` 一致），Foul Play 是其中唯一开源、可读的完整实现。

### 9.2 具体建议（按优先级）

**P0（立刻做，0.5~1 天）：把 Foul Play 作为外部评测对手。**
- 独立 venv + 本地编译引擎 + 登录补丁 + 预热缓存（见 6.3）。
- 设置**两档预算**：快档（1s × 8 状态）用于日常回归；满档（~7s × 8–14 状态，需延长本地计时器）作为"上限参照"。记录"胜率 vs 预算"曲线，而不是单点数字。
- 队伍：不要只用仓库自带的 1 支。用同一队伍池 + 互换持队；至少分"进攻队/平衡队/stall 队"三类统计（stall 是其已知弱点，也是我们 AI 可能的利基）。
- 评测时固定 CPU 亲和性，避免与我们的基准/训练争抢（其搜索是时间制）。

**P1（约 3~5 天）：在 poke-env 上自己搭"Foul Play 式"基线，直接依赖 poke-engine。**
- 写 **poke-env `Battle` → `poke_engine.State` 的转换器**（自己写，参考引擎 Python API 与 `State` 序列化 doctest，不复制 `poke_engine_helpers.py`）；
- 写**信念采样器**：Smogon stats（上月 `-0.json`）× 逻辑过滤 + 自建或下载的完整配置库；
- `monte_carlo_tree_search(..., iterations=N)` 做**可复现的迭代数预算**；
- 这条路线 = Laplace 的做法，说明可行；产出一个与 Foul Play 同类、但**原生于我们的 poke-env 栈**的搜索 agent，可被后续学习模块复用。

**P2（约 1~2 周）：clean-room 实现集合推断，并用引擎当伤害计算器。**
- 优先级（性价比由高到低）：速度区间推断 → 选择道具锁定/排除（含围巾判定）→ Heavy-Duty Boots 判定 → Assault Vest / Life Orb / Leftovers / Flame&Toxic Orb 排除 → **反推伤害过滤**（`poke_engine.calculate_damage` 现成可用，注意 ±2.5% 与 level/20 的容差、overkill 不查下界）→ Tera 属性 → 特性排除。
- **改进点（相对 Foul Play）**：用**软权重（似然）**取代硬淘汰；用对手行为（选择了哪招、何时换人）做似然更新；采样时对完整配置库**按计数加权**并与均匀抽样做平滑；对 Smogon 乘积独立假设做修正（可用 replay 中的联合分布）。这些是我们可以超越其启发式的真实空间。
- 数据：不依赖 `data.foulplay.cc`；自行从 Smogon stats + replay（项目已关注的 Metamon 数据集/replay 源）构建联合配置库。

**P3（约 2~4 周）：与学习型策略/价值网络结合。**
- 模式（对应 Jaxcalibur/PokaiTrainer/Ataraxos）：**学习策略做先验 + 价值网络做叶子评估 + 对 K 个采样世界做 DUCT/PUCT，聚合访问数**。
- 在 poke-engine 上需要 **fork（MIT 允许）**：①`MoveNode` 增加先验 `p`，把 UCB1 换成 PUCT（`mcts.rs`/`mcts_threaded.rs`）；②把 `evaluate()` 换成可插拔评估器，并**批量收集叶子**交给 GPU 价值网络（直接在 Python 回调每个叶子会被 PyO3 往返与 GIL 拖垮）；③保持 DUCT 的"各侧独立选择"。
- 先用最低成本的版本验证价值：**保留引擎手写估值做主评估，用小网络仅在"近似平局"时重排序**（Laplace 的做法，影响约 5–10% 回合），或用网络输出的策略先验给 root 加偏置；这能在不改引擎的情况下完成。
- Foul Play 本身可作为**教师/数据源**：用其搜索访问分布蒸馏策略（输出数据不受 GPL 约束，但注意避免把其代码混入我们的发布物）。

**不要做的事**
- 不要把 `fp/` import 进核心包或复制其推理代码（GPL 传染与未来发表/开源的麻烦）。
- 不要把 poke-engine 当 RL 训练的"真值环境"：在没有对 Showdown 的差分测试前，引擎偏差会被策略利用（reward hacking by simulator bug）。训练环境应是 Showdown（项目已有 `vendor/pokemon-showdown`），引擎只做**搜索内部的近似模型**。

### 9.3 风险清单

| 风险 | 说明 | 缓解 |
|---|---|---|
| 引擎保真度 | 无 Showdown 对拍；Gen9 已知缺口（禁换、Protect、催眠、Doom Desire…）；平均伤害压缩 | 用我们的本地 Showdown 做**随机状态差分测试**（生成状态→两边各走一步→比较分布）；对缺口招式在搜索中降权或打补丁（MIT）|
| 单人维护/版本固定 | Foul Play 钉死 `poke-engine==0.0.48`；新物种/招式需发版；枚举 panic | 我们 fork 并 vendor 固定版本；自行补 Gen9 新增内容 |
| 外部数据依赖 | `data.foulplay.cc`、Smogon stats 网址、PS sets 均为运行时联网 | 预热缓存；自建数据管线 |
| 估值函数天花板 | 手写线性启发式，物种无关；stall 弱 | 价值网络替换/重排序；训练时重点覆盖 stall 对局 |
| 确定化缺陷 | strategy fusion，不评估信息价值 | 多世界聚合 + 混合策略；长期可考虑 ISMCTS / 信念状态搜索 |
| 评测可复现性 | 时间制搜索对 CPU 争用敏感 | 固定核/迭代数预算 |
| 许可 | GPL | 进程隔离；clean-room |

### 9.4 工作量估计（单人，粗略）

| 任务 | 估计 |
|---|---|
| 独立 venv + 编译引擎 + 登录补丁 + 数据预热 + 与 poke-env 对战脚本 | 0.5~1 天 |
| poke-env→engine 状态转换 + 基础信念采样 + MCTS agent | 3~5 天 |
| 集合推断（clean-room，含伤害反推、速度区间等 8~10 条规则）+ 测试 | 1~2 周 |
| 引擎 vs Showdown 差分测试框架（Gen9 OU 范围） | 1 周 |
| fork 引擎：PUCT 先验 + 可插拔批量评估 + Python/GPU 接口 | 2~4 周 |
| 自建联合配置库（replay 抽取）+ 学习型信念模型 | 2~4 周（取决于 replay 数据来源）|

### 9.5 证据缺口（诚实声明）

1. **性能数字全部未实测**：引擎 nodes/s、Foul Play 每步实际延迟、编译时间均无本机数据。
2. 论文正文没有 FoulPlay 的 FH-BT/Elo 具体数值，也没有其比赛用队、搜索预算、硬件；半决赛比分未提取。
3. Gen9 OU 的"1879 / 80% GXE"和"~1930+"是自报且相互不一致；第三方账号 1190 / 51.5% 的配置未知；无独立复现。
4. 博客/论坛帖/issue 内容经小模型摘要，非逐字核对；"可能带来离线问题的登录流程"仅从代码推断，**未在本地服务器上验证**。
5. 采样数超过并行度时的两批串行耗时（由代码推断）、uv 的 `-C build-args` 语法、Python 3.14 兼容性，均 `[UNVERIFIED]`。
6. 引擎数据文件（`choices.rs` 等）的生成方式、与 Showdown 当前 Gen9 OU 规则的逐项覆盖率未做审计。
7. 我方已有的 `doc/research.md` 中关于 Jaxcalibur 等的数字属 `[自报]`，本报告未重新核验。

---

## 附录 A：关键文件速查

| 主题 | 路径 |
|---|---|
| CLI/配置 | `foul-play/fp/config.py`；`fp/format_spec.py`；`fp/generations.py` |
| 连接/登录 | `foul-play/fp/websocket_client.py`（`login` 89 行）|
| 主循环 | `foul-play/fp/main.py: run_foul_play`；`fp/run_battle.py: pokemon_battle` |
| 决策 | `foul-play/fp/modes/base.py: async_pick_move/format_decision/handle_team_preview` |
| 状态 | `foul-play/fp/battle/state.py`；`fp/battle/protocol.py: process_battle_updates`（2290）|
| 推断 | `foul-play/fp/battle/inference.py`（`check_speed_ranges` 133、`check_choicescarf` 344、`_do_check` 465、`update_dataset_possibilities` 545、`check_heavydutyboots` 648）|
| 集合数据 | `foul-play/fp/data/sets/{smogon,team_datasets,base,randbats}.py` |
| 采样 | `foul-play/fp/search/standard_battles.py: _sample_pokemon`（168）、`prepare_battles`（296）|
| 搜索入口 | `foul-play/fp/search/main.py: find_best_move`（58）、`select_move_from_mcts_results`（16）|
| 状态转换 | `foul-play/fp/search/poke_engine_helpers.py: battle_to_poke_engine_state` |
| 引擎 MCTS | `poke-engine/src/mcts.rs`；`src/mcts_threaded.rs` |
| 引擎估值 | `poke-engine/src/genx/evaluate.rs`（Gen1/2/3 各自 `src/genN/evaluate.rs`）|
| 引擎指令生成 | `poke-engine/src/genx/generate_instructions.rs`（`generate_instructions_from_move_pair` 4035，`moves_first` 2593）|
| 引擎状态 | `poke-engine/src/state.rs`；`src/instruction.rs`；`src/genx/state.rs: root_get_all_options` |
| Python 绑定 | `poke-engine/poke-engine-py/src/lib.rs`；`python/poke_engine/__init__.py` |
| 基准 | `poke-engine/data/benchmark.rs` |

## 附录 B：主要外部来源

- Foul Play 仓库 https://github.com/pmariglia/foul-play ；博客 https://pmariglia.github.io/posts/foul-play/ ；Smogon 帖 https://www.smogon.com/forums/threads/re-introducing-foul-play-a-competitive-pokemon-battle-bot.3767378/
- poke-engine 仓库 https://github.com/pmariglia/poke-engine ；文档 https://poke-engine.readthedocs.io/
- PokéAgent Challenge：arXiv 2603.15563（附录 B.2/B.3、D.1.2、E.1.2、E.1.4）
- Laplace（第三方，基于 poke-engine）https://www.trylaplaceai.com/
- Smogon "Bots are now capable of suspect reqs" 帖（Gen9 LC 使用 Foul Play 的外部记录）
