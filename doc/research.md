# alpha-poke 调研资料（Research Notes）

> 本文件收集与「宝可梦对战 AI」相关的论文、开源项目、模拟器、数据集、评测方法等**原始资料**。
> 设计取舍与待决策问题见 [`design.md`](design.md)。
>
> - 调研日期：2026-10-03（部分天梯数据抓取于 2026-10-04）。
> - 资料由网络检索得到，网页内容经小模型摘要后阅读，数字是"摘要所报告的数字"，不是对全文的逐字核对。
> - `[未验证]`：只来自搜索摘要或记忆，未打开原文。`[自报]`：作者本人（论坛帖、博客、README）的说法，未经同行评审或第三方复现。
> - 不同来源之间有若干相互冲突的数字，集中列在第 11 节。
> - 天梯数据（Elo/GXE）在不同赛制、不同时间之间**不可直接比较**。

## 目录

1. 现状一览
2. 论文与研究成果
3. 开源/闭源 bot 项目
4. 模拟器与基础设施
5. 数据集
6. 队伍与静态数据
7. 赛制选择对比
8. 可迁移的方法库（来自一般博弈 AI）
9. 评测方法
10. 工程经验
11. 未验证 / 相互冲突的信息
12. 参考链接

---

## 1. 现状一览（TL;DR）

1. **已有系统在天梯上达到或接近顶尖人类，但最强的几个是闭源个人项目 [自报]**
   - **Jaxcalibur**：Gen9 随机对战（Random Battle），峰值 Elo 2557 / GXE 95.3，2026 年 8 月多次登顶，与最强人类（MichaelderBeste2，GXE 95.5）基本持平。
   - **mikumiku37**：Champions VGC Reg M-C，2026-10-01 登顶天梯（Elo 1857，GXE 81.2%）。
   - 两者都**没有**开源代码或权重。
2. **最强的公开、可复现路线有两条**
   - **Metamon**（UT Austin，MIT）：基于人类对战 replay 的离线 RL + 自博弈，transformer，无搜索。Gen1 OU 上集成模型曾登顶天梯。
   - **Foul Play**（GPL-3.0）：采样对手配置 + MCTS（Decoupled UCT）+ Rust 引擎，赢得 NeurIPS 2025 PokéAgent 的 Gen9 OU 赛道。
3. **近期收敛的"配方"**：小到中型 transformer（8–200M 参数）+ 极快的模拟器（让对局量达到 10^8 量级）+ 自博弈（PPO/league）+ 测试时搜索（对采样的"隐藏世界"做 pUCT/CFR，据 Jaxcalibur 自报约 +100–150 Elo）。
4. **LLM 单独做在线策略明显更弱**（PokéLLMon、PokéChamp：约 1300–1500 Elo），PokéAgent 决赛前 8 名都是 RL 或 MCTS。
5. **组队（team building）几乎没有成熟研究**，VGC-Bench 明确留作未来工作。
6. **训练算力要求不高**：Jaxcalibur 约 1 张 H100 × 1 周（约 1 亿局）；mikumiku37 约 1 张 RTX 5090 × 48 小时（约 3.3 亿局）。**关键瓶颈是模拟器速度**，不是 GPU。
7. **poke-env + Showdown 服务器是最慢的训练路径**（见 4.1），更适合作为评测/部署接口。

---

## 2. 论文与研究成果

### 2.1 对战 AI 专项

| 工作 | 年份/出处 | 赛制 | 方法 | 关键结果 | 开源 |
|---|---|---|---|---|---|
| **Metamon** — Grigsby 等 [arXiv 2504.04395](https://arxiv.org/abs/2504.04395) | RLC 2025 | Gen1–4 OU（后扩展 Gen9 OU） | 从 47.5 万场人类 replay 重建第一人称轨迹，AMAGO 风格 transformer actor-critic（15/50/200M），离线 RL + 自博弈数据 | 200M 模型 Gen1 GXE 79.9%（Glicko-1 1761±35，峰值第 31 名），约进入活跃玩家前 10% | 是（MIT） |
| **PokéAgent Challenge** — Karten, Grigsby 等 [arXiv 2603.15563](https://arxiv.org/abs/2603.15563) | NeurIPS 2025 竞赛 | Gen1 OU、Gen9 OU（+ 速通赛道） | 基准 + 竞赛；评分用 Full-History Bradley-Terry | Gen1 冠军 PA-Agent（扩展 Metamon），Gen9 冠军 Foul Play；16 个晋级队伍中 13 个扩展了公开的 Metamon 基线；前 8 名均用 RL/MCTS | 数据与基线公开 |
| **PokaiTrainer** — Max Yu [arXiv 2608.29197](https://arxiv.org/abs/2608.29197) | 2026-08（v2 2026-09） | VGC 2026 Reg M-B（双打，OTS） | Student-of-Games 风格 CFR，对"同时动作的贝叶斯矩阵博弈"做决策时求解；Rust 引擎；5.4M 参数 transformer | 稳定 1350–1400 Elo，峰值 1492（前 500）；150 场 Bo3 胜率 59%；策略网络单独用会输给浅层启发式搜索 71%，**强度主要来自搜索**；隐藏属性信念摘要贡献 +8–12 个百分点 | 引擎有意开源，权重未放出；**单作者预印本** |
| **VGC-Bench** — Angliss, Cui, Hu, Rahman, Stone [arXiv 2506.10326](https://arxiv.org/abs/2506.10326) | AAMAS 2026 | Gen9 VGC 双打（OTS） | BC、PPO 自博弈、虚拟博弈（FP）、double oracle（DO）及 BC 初始化变体；8×A40，每配置约 500 万步 | 单队 BCSP 胜过中级/高级玩家的小样本测试（作者称"有意为轶事性质"）；队伍数增加→泛化提升、同分布表现下降，对针对性最佳响应约 100% 可被利用 | 是（MIT） |
| **PokéChamp** — Karten 等 [arXiv 2503.04094](https://arxiv.org/abs/2503.04094) | ICML 2025 spotlight | Gen9 OU | LLM 替换 minimax 的动作采样、对手建模、叶节点估值，无需训练 | 对 PokéLLMon 76%；预测天梯 Elo 1300–1500（前 30%–10%）；约 1/3 对局因计时器超时输掉 | 是（许可证 NOASSERTION，复用前需看 LICENSE） |
| **PokéLLMon** — Hu, Huang, Liu [arXiv 2402.01118](https://arxiv.org/abs/2402.01118) | 2024 | Gen8 随机对战（[未验证]） | GPT-4 提示 + 知识增强 + 一致性动作生成 | 天梯胜率 49%，邀请赛 56%（"人类平均水平"） | 是（已陈旧） |
| **Huang & Lee** [CoG 2019](https://ieee-cog.org/2019/papers/paper_175.pdf) | 2019 | Gen7 随机对战 | PPO+GAE 自博弈，实体 embedding；384 万局，约 6 天、约 91 美元（GCP） | Glicko-1 1677（约 72% 对随机天梯对手） | 论文 |
| **Sarantinos** [arXiv 2212.13338](https://arxiv.org/abs/2212.13338) | 2022/23 | Gen7 随机对战 | 分布式搜索（4×48 核 AWS），非 RL | 643 场对人类，峰值世界第 33 | 否 |
| **PokeJAX / "Automatic Generation of High-Performance RL Environments"** — Karten, Appapogu, Jin [arXiv 2603.12145](https://arxiv.org/abs/2603.12145) | 2026-03 | （覆盖的世代/赛制未说明） | LLM 智能体辅助把 Showdown 翻译成 JAX（约 5.6 万行） | 1×RTX 5090：随机动作 5 亿步/秒，PPO 约 1520 万步/秒；论文称策略迁移回 Showdown 后胜率等价 | **论文未给出代码地址 [未验证]** |
| Kalose 等 | 2018 斯坦福课程报告 | 自写简化模拟器 | 表格 Q-learning | 对随机 agent 70% | 否（仅作历史参考） |

另有只看到元数据的工作 `[未验证]`：Simões 等 2020（ICARSC，自写模拟器上的 WPL/GIGA 竞争 RL）、Rossi 等 2024（SBGames，poke-env 上的 RL 基准）、Lee & Togelius 2017（Showdown AI 竞赛提案）、Springer 2024 VGC 神经进化论文、Jett Wang MIT MEng 硕士论文 2024（Random Battles + RL）。

LLM 方向的低相关性工作：Jain 等 [arXiv 2512.17308](https://arxiv.org/abs/2512.17308)、多智能体 LLM 锦标赛 [arXiv 2508.01623](https://arxiv.org/abs/2508.01623)、Porimon [arXiv 2609.32544](https://arxiv.org/abs/2609.32544)。检索中**没有**发现 2026 年用 RL（如 GRPO）微调 LLM 做宝可梦对战的论文，可视为空白。

**poke-env 本身没有学术论文**，只是 GitHub 库（常以仓库形式被引用）。

### 2.2 各工作的关键细节

**Metamon**
- 观测：每个时间步约 87 个文本 token + 48 个数值特征，使用宝可梦专用词表；动作 9 个（4 招 + 5 换人），带动作掩码；奖励以胜负为主、辅以轻量塑形（伤害、回复）。
- 算法：行为克隆项 − λ·Q 最大化项；变体有 IL、Exp、Binary、Binary+MaxQ；多 γ 训练，评测用 γ=0.999；后期用 two-hot 分类式 critic（来自 AMAGO-2）。
- 数据：见 5.2。
- 公开模型（README）：SyntheticRLV2 200M（2024-09）；Abra 57M（2025-07，挑战赛期间最强的 Gen9 OU 公开模型）；Kadabra3 57M；**Kakuna 142M**（2025-12，GXE Gen1/2/3/4/9 = 82/70/63/64/71）；**TaurosV0 62M**（2026-05，Gen1 OU 专精，GXE 83%）。README 称 KakunaEnsemble / TaurosEnsemble 曾登顶人类天梯 Gen1 OU `[自报，未在榜单页独立确认]`。
- 局限（作者自述）：replay 重建与真实服务器之间有 sim-to-sim 差距；100+ 回合时误差累积；对罕见队伍较弱；1–5% 无效动作；早期世代玩家少，Elo 噪声大。
- 训练算力：论文未给出 GPU 小时数 `[未验证]`；README 称大模型需"数天、多卡"。

**Foul Play / poke-engine**
- 维护一个很大的对手候选配置库（来自 Smogon 使用率、爬取队伍、replay，带似然权重），随对局进行用证据过滤（用伤害反推努力值/性格、用先后手反推速度档、用天气/场地行为推断道具、用状态招式推断招式组）。
- 每次决策：采样多个完整"世界"（对隐藏属性做填充，即 determinization / PIMC），在每个世界里跑 MCTS，再汇总。
- 搜索：Decoupled UCT（同时动作下双方各自独立选），Rust 实现，根并行；**伤害浮动聚类**——不枚举 16 档，只按"是否击杀"分支，使搜索深度从 expectiminimax 的约 5 回合提升到约 10 回合。
- 作者认为对手配置预测"与搜索速度同等重要甚至更重要"。
- 成绩 `[自报]`：Gen9 OU GXE 80%、峰值 Elo 1879（博客）/"1930+"（论坛帖，二者不一致）；Gen9 随机对战 88% / 2341；Gen4 随机对战 85% / 1728。
- 弱点：偏重防守的队伍、超过约 10 回合的长期规划、手写估值函数、各世界独立搜索。理论上 PIMC 存在 strategy fusion，DUCT 不保证收敛到纳什均衡。
- 算力：16GB 内存 / 4 核，每步约 7 秒。

**Jaxcalibur `[自报]`**（[网站](https://jaxcalibur.github.io/)、[Smogon 帖](https://www.smogon.com/forums/threads/jaxcalibur-a-gen-9-randbats-bot-that-reached-1-on-the-ladder.3787537/)）
- 纯 JAX 重写的 Gen9 随机对战引擎。
- 模型：8.5M 参数非因果 transformer（位置式 MoE），66 个输入 token（场地 1、在场 2、招式 5、己方队伍 6、对方队伍 6、事件历史 16、对阵计算 24）；输出动作 logits、胜率、对手动作、对手道具/特性/招式预测（辅助损失）。
- 训练：PPO + GAE + 熵正则 + "zero-avoiding"的 KL-to-uniform 项；无搜索训练；1×H100 约 1 周，约 1 亿局；作者称总开发 6 个月以上，复现需"数百美元 GPU + 专业知识"（训练时长在网站与论坛帖之间说法不一，见第 11 节）。
- 测试时搜索：针对同时动作的 pUCT 变体（用正遗憾与网络先验的混合来采样边），采样 32 个对手配置"世界"，深度 4，20,480 次 rollout，估计比纯策略高 100–150 Elo；纯策略在笔记本上约 2400 Elo。
- 成绩：峰值 Elo 2557，GXE 95.3，对顶尖玩家胜率 68%；约 20% 的观察期占据第 1，最强人类约 50%，所以是"持平"而非"明显超越"。
- 作者拒绝放出代码/权重（保护天梯与赛事的完整性），社区多数反对放出。

**mikumiku37 `[自报]`**（[Smogon 帖](https://www.smogon.com/forums/threads/mikumiku37-a-self-play-vgc-bot-reached-1-on-the-vgc-reg-m-c-ladder.3789199/)）
- 8.7M 参数 transformer，PPO 自博弈对 league（历史版本）、从零开始（不使用人类 replay），约 1,260 支公开比赛队伍；1×RTX 5090 × 48.3 小时，约 3.3 亿局；输入为己方视角状态 + 静态图鉴数据，**不含**伤害计算器/使用率/速度判定器。
- 决策：1 回合前瞻，采样 16 个世界，己方前 8 个联合动作 × 对手前 8 个应对构成收益表，解混合策略。
- 成绩：Elo 1857、GXE 81.2%、Glicko 1775±25、248–110（358 场）登顶。注意：该赛制天梯较新，榜首人类只有约 1875 Elo / GXE 74%（见第 7 节），"登顶"的门槛比 OU/随机对战低。
- 代码、引擎、权重均未放出。

**PokéAgent Challenge**
- 战斗赛道：Gen1 OU、Gen9 OU，专用 agent-only Showdown 服务器（https://battling.pokeagentchallenge.com）；计时：标准 30 秒起始 + 每回合 3 秒（上限 8 秒），LLM 变体放宽到 60–90 秒。
- 评分：FH-BT 为主，同时记录 Glicko-1 与 GXE，最少 250 场。
- 数据：4M+ 人类轨迹、18M 合成自博弈轨迹、20 万+ 队伍文件。
- 结论：RL 与搜索显著优于 LLM；顶级 RL 基线在人类天梯上约 80% GXE，"与顶尖人类相当但非超人"；LLM 失败模式含"恐慌换人"和记忆污染。
- 获奖队伍的详细方法/算力（附录）`[未验证]`。

---

## 3. 开源/闭源 bot 项目

| 项目 | 地址 | 语言 | 方法 | 赛制 | 强度（来源） | 活跃度 | 许可 |
|---|---|---|---|---|---|---|---|
| **Metamon** | [UT-Austin-RPL/metamon](https://github.com/UT-Austin-RPL/metamon)；HF `jakegrigsby/metamon` | Python（`amago`） | transformer 离线 RL + 自博弈 | Gen1–4 OU、Gen9 OU（仅单打） | 见 2.2 | 2026-07（作者称为兴趣项目，更新不规律） | MIT |
| **Foul Play** | [pmariglia/foul-play](https://github.com/pmariglia/foul-play) | Python + Rust | 采样配置 + MCTS | 单打、各世代（无极巨化/Z 招式） | 见 2.2 | 2026-10-03 活跃 | **GPL-3.0**（复用代码有传染性） |
| **poke-engine** | [pmariglia/poke-engine](https://github.com/pmariglia/poke-engine) | Rust + Python 绑定 | 搜索用近似引擎（expectiminimax / DUCT） | 仅单打 | — | 2026-10-03 | MIT |
| **VGC-Bench** | [cameronangliss/vgc-bench](https://github.com/cameronangliss/vgc-bench) | Python（poke-env + PettingZoo） | BC / PPO / FP / DO | VGC 双打 OTS | 见 2.1 | 2026-07 | MIT |
| **PokéChamp** | [sethkarten/pokechamp](https://github.com/sethkarten/pokechamp) | Python（uv、poke-env） | LLM minimax | Gen1–9 | 见 2.1 | 2026-03 | NOASSERTION |
| **PokéLLMon** | [git-disl/PokeLLMon](https://github.com/git-disl/PokeLLMon) | Python | LLM | Gen8 随机对战 | 49% 天梯胜率 | 2024-10（陈旧） | 无 |
| **Technical Machine** | [davidstone/technical-machine](https://github.com/davidstone/technical-machine) | C++ | expectimax + 组队器 | 主要 Gen1–4 | 无强度数据 | 2026-08 | BSL-1.0 |
| **Laplace** | [trylaplaceai.com](https://www.trylaplaceai.com) / GitHub influxtion/Pokemon-Showdown-AI | Python/PyTorch + poke-engine | 8 个采样世界 × MCTS + 368 维小网络打破平局 | Gen9 随机对战 | 自报峰值 2231 Elo、排名约 150、GXE 83.3（800+ 场） | 未验证 | 开源 |
| Jaxcalibur | 见上 | JAX | PPO + pUCT | Gen9 随机对战 | Elo 2557 / GXE 95.3 | — | **闭源** |
| mikumiku37 | 见上 | — | PPO league + 1 回合求解 | Champions VGC Reg M-C | Elo 1857 / GXE 81.2 | — | **闭源** |
| philmantatsky/VGC-Pokemon-Showdown-AI | [GitHub](https://github.com/philmantatsky/VGC-Pokemon-Showdown-AI) | Python | BC 初始化 + PPO transformer + 虚拟博弈 | VGC Reg M-B | 自报峰值 1365 Elo | `[未验证]` | MIT |
| taylorhansen/pokemonshowdown-ai | [GitHub](https://github.com/taylorhansen/pokemonshowdown-ai) | TS/TF | PPO/DQN | Gen4 随机对战 | 陈旧（2024-01） | — | MIT |

其它仅见 README 摘要、未验证的小项目：PsyMew（LLM bot，fork 自 Foul Play）、Nolelle/pokemon-vgc-ai、akkshay0107/p0、Blueshadow0107/showdown-brain、Novapool/pokemon-showdown-ai、RotomAI。

**观察**
1. 目前"持平顶尖人类"的证据（Jaxcalibur、mikumiku37）来自闭源项目；开源可复现的是 Metamon（Gen1 强、Gen9 OU 仅约 71% GXE）和 Foul Play（搜索，Gen9 OU 约 80% GXE）。
2. **Gen9 OU（含组队、太晶、1000+ 物种）没有公开的、顶尖人类水平的 RL agent**。
3. 训练吞吐的鸿沟（Showdown + poke-env 约数百步/秒 vs 自写引擎 74.5 万–1520 万步/秒）是顶尖 bot 作者都自己重写引擎的主要原因。

---

## 4. 模拟器与基础设施

### 4.1 poke-env

- 仓库：[hsahovic/poke-env](https://github.com/hsahovic/poke-env)，文档 https://poke-env.readthedocs.io ；MIT；PyPI 0.16.1（2026-08-23，即本项目当前依赖）；2026-10-02 仍有提交；仍标注 `Development Status :: 3 - Alpha`。
- **本质**：连接 Showdown 服务器的 websocket 客户端，把协议解析成 Python 对象（`Battle`、`DoubleBattle`、`Pokemon`、`Move`、`GenData` 等）并追踪对手已知信息。asyncio；一个进程可通过 `max_concurrent_battles` 同时跑多局。
- **Player API**：继承 `Player` 并实现 `choose_move(battle)`；自带 RandomPlayer、MaxBasePowerPlayer、SimpleHeuristicsPlayer；`battle_against`、`send_challenges`、`accept_challenges`、`ladder`；`Teambuilder`（打包队伍字符串）；0.16 新增基于 Smogon 使用率的队伍构建示例。
- **RL API**：`PokeEnv` 是 PettingZoo `ParallelEnv`（`agent1/agent2`，原生支持自博弈），子类 `SinglesEnv` / `DoublesEnv`；`SingleAgentWrapper` 包成单智能体 Gymnasium 环境。用户需重写 `embed_battle`、`calc_reward`，并设置 `observation_spaces`。单打动作空间 `Discrete(26)`（第 9 世代：0–5 换人、6–9 出招，其后每 4 个为 mega / Z / 极巨 / 太晶块）；提供 `get_action_mask`。
- 依赖固定：gymnasium==1.3.0、websockets==16.1.1、pettingzoo>=1.24.3、numpy>=2.0.2、orjson。示例用 stable-baselines3 + supersuit。
- **已知局限**（来自 issue 列表）：
  - 老世代机制有未修复 bug（#753 Gen1、#964 Gen3 Flash Fire）；
  - 双打支持/文档较薄（#458）；
  - 重复宝可梦/昵称不支持（#770、#415）；
  - 无法从任意状态开始对局（#618）——这对"从某个局面开始搜索"很关键；
  - PokeEnv 内无天梯支持（#809）；
  - 对局解析性能（#921）、启动/重置开销（#907，提议加进程内 BattleStream 后端，未获维护者回应）。
  - Metamon 报告 poke-env 后端存在 PP 计数、太晶属性 bug 及与 replay 解析器之间的 sim-to-sim 差距，因此自带了解析器与后端。
- **吞吐**（无官方数字）：PokeJAX 论文测得经 PokeEnv 的 PPO 回路约 681 步/秒，而裸 Showdown 约 2.1 万步/秒（该论文作者有对比动机）；某博客约 209–242 局/分钟（并发 20，`[未验证]`）。**需要在本机实测**。
- **本地并行方式**：① 单 Player 内多并发对局；② 多个环境进程（SubprocVecEnv / ray）各用独立账号连同一个服务器；③ 多个 Showdown 服务器不同端口（VGC-Bench 的 train.sh 会自动起多个）。
- 结论：poke-env 保真地走真实协议（部署上天梯必需），但**不适合做大规模训练的模拟器**。

### 4.2 Pokémon Showdown（真值）

- [smogon/pokemon-showdown](https://github.com/smogon/pokemon-showdown)；MIT；TypeScript；0.11.11（2026-07-28）；需要 Node ≥ 22.18。
- 覆盖单打/双打/三打、Gen1–9；包含 `champions`、`championsregmb` mod（Pokémon Champions 赛制：VGC 2026 Reg M-B/M-C、BSS、OU 等）。
- 本地运行：`node pokemon-showdown start --no-security`（去除节流与密码），脚本见 `scripts/start_showdown.sh`。
- 瓶颈：单线程 Node；`config.js` 的 `subprocesses.simulator` 默认 1。更高效的方式是绕过服务器和 websocket，直接驱动 `BattleStream`（`pokemon-showdown simulate-battle` 命令行、`sim/README`）。pkmn/engine 文档提醒 BattleStream 的 Promise 处理存在竞态，可能让基准失真。
- 命令行工具：`simulate-battle`、`generate-team`、`validate-team`、`pack-team`。

### 4.3 更快的模拟器

| 名称 | 说明 | 速度 | 保真度 | 状态/注意 |
|---|---|---|---|---|
| **pkmn/engine**（[GitHub](https://github.com/pkmn/engine)，Zig，MIT） | 声称比打补丁的 Showdown 快 1000× 以上，bug-for-bug 兼容；绑定 C/Zig/Node(WASM) | >1000×（自报） | 兼容模式 | **WIP**（README："等 v0.1"）；阶段 1 为 RBY 与 GSC（进行中），ADV/DPP 在后，**无 Gen9** |
| **advsim**（[zkingston/advsim](https://github.com/zkingston/advsim)，Python/NVIDIA Warp，MIT） | Gen3 随机对战的 GPU 引擎，每线程一局；含 PPO league 训练、GPU 确定化同时动作 MCTS | RTX 4070 约 74.5 万决策/秒（冒烟 PPO） | 对 Showdown 0.11.11 做了 10 万+ 整局、680 万决策点、1000 万伤害用例验证，0 分歧 | **2026-10-02 刚创建**，0 star；仅 Gen3 随机单打 |
| **PokeJAX**（arXiv 2603.12145） | Showdown 的 JAX 翻译 | 1×RTX 5090，PPO 1520 万步/秒 | 论文称策略迁移后胜率等价 | **代码是否公开 `[未验证]`**；覆盖范围未说明 |
| **minimon**（[spktrm/minimon](https://github.com/spktrm/minimon)，JAX，MIT） | 宝可梦"类比"环境（程序生成的属性/招式/道具），同时动作、隐藏信息，带纳什工具 | 未量化 | **不忠实于 Showdown**（设计如此） | 适合做算法研究，不能训练天梯 bot |
| Jaxcalibur / mikumiku37 的引擎 | 私有 JAX 引擎 | 未公布 | 未公布 | **闭源** |
| pokemon-showdown-rs（[vjeux](https://github.com/vjeux/pokemon-showdown-rs)，Rust） | Gen9 随机对战 1:1 移植，与 Showdown 做一致性测试 | 约 50 局/秒、约 2,400 回合/秒（单线程） | 一致性测试 | 无许可证文件；2026-01 后停更；仅比 Node 略快 |
| poke-engine（见第 3 节） | 搜索用近似 Rust 引擎 | 快 | README 自称"远不如 Showdown 完整" | 世代覆盖 README 与 changelog 不一致 `[未验证]` |
| PokaiEngine（PokaiTrainer 用） | Rust；枚举联合动作的完整结果分布 | 中位回合 0.08 ms vs Showdown 2.0 ms（26×） | 约 99% 行为一致 | 作者称计划开源 |
| pokejax(JerJer2465)、ninjax、psvm、Novapool 等 | 实验性/停更 | — | — | `[未验证]` |

**结论**：目前**没有**开源、已验证保真的快速 Gen9 / VGC / 双打引擎。可用的是 pkmn/engine（Gen1/2，WIP）和 advsim（Gen3 随机对战）。强力 bot 的作者都自己写引擎（Jaxcalibur、mikumiku37、PokaiTrainer）。

### 4.4 通用 RL 基础设施（仅列与"单机不完全信息自博弈"相关的）

| 名称 | 许可 | 备注 |
|---|---|---|
| Stable-Baselines3 / sb3-contrib（MaskablePPO） | MIT | poke-env 示例所用；简单但对 transformer/league 不友好 |
| PettingZoo / Gymnasium | MIT | poke-env 的多智能体接口 |
| **PufferLib** | MIT | 高吞吐向量化（C 环境、共享内存）+ 自带 PPO；PyPI 稳定版 3.0.0（2025-06），GitHub 发布标签为 "5.0-experiments"（2026-09），版本分歧；未发现宝可梦对战环境；适合"自己用 C/Zig 写环境"的路线 |
| CleanRL | MIT | 单文件 PPO 参考实现（含 JAX），做模板而非框架 |
| Ray RLlib | Apache-2.0 | 多智能体/league 示例，较重 |
| Sample Factory | MIT | APPO，异步采样，面向单机高 SPS；支持多智能体/PBT |
| TorchRL | MIT | 可组合环境/采集器/损失，有 PettingZoo 封装 |
| JAX / gymnax / Pgx | Apache-2.0 | 所有 GPU 引擎的基础；Pgx 自 2025-03 无更新、仅完美信息棋类 |
| **mctx**（DeepMind） | Apache-2.0 | JAX 批量 MCTS；假设顺序、完美信息树，用于同时动作 + 隐藏信息需改造（Jaxcalibur 用了修改版 pUCT） |
| **OpenSpiel** | Apache-2.0 | CFR、NFSP、PSRO、R-NaD、同时动作博弈等算法参考；可用于可利用度评测；太慢，不适合做主训练循环 |
| **AMAGO** | MIT | Metamon 背后的长上下文 transformer RL 库，可直接加载 Metamon checkpoint |

---

## 5. 数据集

### 5.1 Showdown 原始 replay

- 只有被保存的对局才有 replay；**replay 是观战者视角**，不含双方完整队伍，只有已被揭示的信息；精确 HP、努力值、未揭示招式/道具都缺失，需重建。
- 接口（2026-10-04 实测可用）：
  - `https://replay.pokemonshowdown.com/search.json?format=gen9ou`（可加 `&user=`、`&user2=`、`&before=<uploadtime>`；每次最多 51 条，用 `before` 翻页；文档 [WEB-API.md](https://github.com/smogon/pokemon-showdown-client/blob/master/WEB-API.md)）；某些赛制 `rating` 为 null。
  - `https://replay.pokemonshowdown.com/<id>.json` 返回 `{id,format,players,log,uploadtime,views,formatid,rating,private,password}`；另有 `.log`。
  - `<id>.inputlog` **仅随机对战可访问**（其余返回 access denied）——意味着随机对战可用 seed + 双方选择做**完全信息**的精确重放 `[仅见到拒绝提示，完整性未验证]`。
- 限速/ToS：未找到文档化的限速或爬取条款（已查 `/rules`、`/pages/faq`）；站点在 Cloudflare 后面。应礼貌访问，优先用 HF 镜像。
- Metamon 的原始 replay 在 2021–2024 间有覆盖空洞（"replay 数据库故障"）。

### 5.2 Metamon 数据集（整理最好、RL 可直接用）

- `jakegrigsby/metamon-raw-replays`：2,681,841 条 replay，5.7 GB Parquet，v6（2026-05-19）；用户名已替换为随机化假名。
- `jakegrigsby/metamon-parsed-replays`：约 530 万条轨迹（每场两条，每方视角各一），来自约 270 万场；格式为按世代/年月组织的 `.json.lz4`；**CC-BY-NC-4.0（非商业）**；覆盖 Gen1–4 的 OU/NU/UU/Ubers 与 Gen9 OU，**不含随机对战与 VGC**。HF 页面标注的体量（约 100 万、28.5GB）与 README 的 530 万不一致，以实际下载为准。
- 自博弈：`jakegrigsby/metamon-parsed-pile`（pac-base 1100 万、pac-exploratory 700 万、pac-tauros 400 万条）；README 总述"5M+ 人类、20M+ 自博弈轨迹"。
- 队伍：`jakegrigsby/metamon-teams`（competitive、`gl_05_26` 普通天梯：G1 2.9 万 / G2 1 万 / G3 10.7 万 / G4 4.8 万 / G9 13.9 万；`hl_05_26` 高分天梯；程序生成的多样化队伍等）。
- 使用率统计镜像：`jakegrigsby/metamon-usage-stats`。
- **部分可观测重建**：用 Python 重写的 Showdown 协议，把观战日志转成每位玩家的第一人称视角，模拟玩家会收到的 `request` 消息，并用使用率统计采样/预测未揭示的队伍信息，回填到整条轨迹；有歧义的对局保守丢弃。作者明确说仍有 sim2sim 差距，replay 数据"更适合作为离线到在线微调的预训练"；战斗后端有版本号（`poke-env` / `pokeagent` / `metamon`），因为修观测 bug 会让旧 checkpoint 变差。
- 论文规模：47.5 万场 → 95 万序列 / 3800 万时间步；加入 Gen9 后 350 万条轨迹。

### 5.3 其它公开数据集

| 数据集 | 规模 | 赛制 | 备注 |
|---|---|---|---|
| [`HolidayOugi/pokemon-showdown-replays`](https://huggingface.co/datasets/HolidayOugi/pokemon-showdown-replays) | 3419 万行，71.9GB Parquet；Gen9 随机对战 199 万、Gen9 OU 249 万、VGC 2026 71 万 | 全赛制，2005–2026 | 原始观战日志 + rating + 玩家；**许可未注明 `[未验证]`**；最大最新，含随机对战 |
| [`milkkarten/pokechamp`](https://huggingface.co/datasets/milkkarten/pokechamp) | 200 万清洗后对局（来自 300 万+，50 万+ 高分） | 37+ 赛制，Elo 1000–1800+，2024–2025 | 来自 PokéChamp |
| [`cameronangliss/vgc-battle-logs`](https://huggingface.co/datasets/cameronangliss/vgc-battle-logs) | 88,905 条日志，MIT | Champions Reg M-A/M-B（含 Bo3），仅 OTS，最新 2026-06-20 | 用 vgc-bench 爬取工具得到 |
| VGC-Bench 论文数据 | 33 万+（v2）/ 70 万+（v3），过滤 rating ≥ 1200 | Gen9 VGC（SV 时期） | |
| `stevenkhan/pokemon-showdown-battle-sft` | 派生自 pokechamp，Elo≥1400 | | SFT 风格，对 RL 价值低 |
| Kaggle | 未发现有分量的数据集 | | `[未验证其不存在]` |

PokéAgent 站点称"2.4M+ replay、4M+ RL 轨迹、20 万+ 队伍集合"，论文则称"4M+ 人类轨迹、18M 合成、10 万+ 社区对局"，口径略有出入。

### 5.4 Smogon 使用率统计作为对局侧数据

- `https://www.smogon.com/stats/YYYY-MM/`（最新 2026-09）。2026-09 各赛制总对局数：gen9ou 574,541；Champions VGC Reg M-C 1,631,943；Reg M-B 326,464；Reg M-C Bo3 223,477；gen9doublesou 196,031；gen3ou 195,470；championsou 145,642；championsbss Reg M-C 69,462；gen4ou 57,675；gen1ou 11,702；gen2ou 4,433；gen9vgc2024regg 9,911。
- **随机对战不在统计里**（文件 404）。可作为各赛制人类人口规模的代理。

---

## 6. 队伍与静态数据

- **Smogon stats**：`.../stats/YYYY-MM/` 下的 `<format>-<cutoff>.txt`、`chaos/<format>-<cutoff>.json`、`moveset/`、`leads/`、`metagame/`、`monotype/`。cutoff 多为 0/1500/1630/1760（OU：0/1500/1695/1825）。chaos JSON 含 `Raw count`、`Abilities`、`Items`、`Spreads`、`Moves`、`Tera Types`、`Teammates`、`Checks and Counters`、`usage` 等。可用于：采样对手配置/信念模型、预测 replay 缺失信息（Metamon 的做法）、物种 embedding。
- **Showdown `data/`**：`pokedex.ts`、`moves.ts`、`typechart.ts`、`learnsets.ts`、`formats-data.ts`、`items.ts`、`abilities.ts`、`natures.ts`、`conditions.ts`、`rulesets.ts`、`mods/`（含 Champions）、`text/`。可做种族值/属性/招式威力命中/优先度/可学招式等静态特征。
- **随机对战配置**：`data/random-battles/gen9/sets.json`（267KB）、`doubles-sets.json`、`bss-factory-sets.json`、`factory-sets.json` 等，另有 `teams.ts`（生成器）。随机对战中对手的可能配置可枚举（按角色分的少量配置/物种），**这使信念追踪远比 OU 容易**，也是 Foul Play 在随机对战上表现很好的原因之一。
- **Pikalytics**（VGC 使用率，来自 Pokémon HOME + Showdown + RK9）：有 markdown "AI" API；条款与限速 `[未验证]`。
- **VGCPastes**：锦标赛队伍表 + Pokepaste 链接；VGC-Bench、PokaiTrainer（663 支）、mikumiku37（约 1,260 支）都用它建队伍池。
- **Pokepaste 格式**（[语法](https://pokepast.es/syntax.html)）= Showdown 队伍导出格式，poke-env 与 Metamon 都支持。
- Smogon 样例队伍帖：Metamon `competitive` 集（每赛制 <30 支），作者称曾对其过拟合。
- 文本 embedding：没有核实到论文使用 LLM 对招式/特性描述做 embedding；Metamon 用文本 token + 数值特征，Jaxcalibur/mikumiku37 用静态图鉴特征。这属于设计选择，而非已验证的前人工作。

---

## 7. 赛制选择对比

人类天梯榜首数据（`https://pokemonshowdown.com/ladder/<format>.json`，2026-10-04 抓取，前 500 名）：

| 赛制 | #1 Elo / GXE | #10 | #100 | #500 | 备注 |
|---|---|---|---|---|---|
| gen9randombattle | 2533 / 94.7（26.8k 场） | 2405 / 90.6 | 2262 / 84.5 | 2111 / 82.5 | 人口大；Jaxcalibur 峰值 2557/95.3；Foul Play 2341/88 |
| gen9ou | 1966 / 85.7 | 1883 / 84.3 | 1755 / 84.1 | 1633 / 73.3 | Foul Play 峰值 1879，前 100 |
| gen1ou | 1602 / 82.1 | 1547 | 1499 | 1336 | Metamon 集成模型曾登顶；月对局仅约 1.17 万 |
| gen2ou | 1544 | 1500 | 1365 | 1125 | 极小人口（月 4.4k 局） |
| gen3ou | 1814 | 1757 | 1650 | 1543 | |
| gen4ou | 1703 | 1613 | 1518 | 1473 | |
| gen9championsvgc2026regmc | 1875 / 74.0 | 1795 | 1711 | 1605 | 月 163 万局；mikumiku37 1857 |
| …regmc Bo3 | 1704 / 81.9 | 1614 | 1516 | 1403 | |
| gen9championsbssregmc | 1573 / 73 | 1513 | 1408 | 1252 | 月 6.9 万局 |
| gen9doublesou | 1914 | 1825 | 1659 | 1544 | |

> 榜单看起来反映的是最近一个时间窗口（Showdown 天梯赛季为 3 个月）；Elo 是否每赛季重置 `[未验证]`。

**逐赛制评估**

- **Gen9 随机对战**：无组队；对手配置可由 `sets.json` 枚举；`inputlog` 公开；数据量大（约 200 万 replay）；人类人口庞大。"超越顶尖人类"的证据最清晰（Jaxcalibur）。缺点：没有官方职业赛事；技能上限里含较多运气成分，"pro"区分度主要在对局内决策。
- **Gen1–4 OU**：Metamon 的主场；人口很小，天梯很薄、榜首较易；Gen3/4 对 bot 更难（GXE 约 63–64%）；队伍相对固定，组队简单，隐藏信息大。不是最有声望的赛制。
- **Gen9 OU（6v6 单打，含组队）**：最大的"官方"单打人口（月约 57 万局）；单打里最难——组队、太晶、庞大的隐藏空间。最强 bot：Foul Play 峰值 1879、GXE 80%，前约 100；Kakuna 71%；PokéChamp 约 1300–1500。最强人类 1966 / 85.7。差距适中、可测量。**无公开 RL 达到顶尖人类水平**。
- **VGC 双打（现为 Pokémon Champions Reg M-x）**：最难——联合动作空间大（VGC-Bench 每只宝可梦 107 个动作）、队伍预览四选一、OTS、Bo3；有真实的职业赛事（2026 年世锦赛 8/28–30，冠军 Takuma Yamazaki）。机器 vs 职业选手的证据薄弱（见 9.5）；每个赛季规则一变，数据快速过期；榜首人类 GXE 仅 74%（天梯较"年轻"）。
- **BSS（Battle Stadium Singles）**：3v3 带 OTS；几乎没有专门的 ML 工作；人口小。不建议作为主目标。

**初步观察（非决策）**：若要对"击败人类职业选手"有清晰标尺，随机对战与 Gen9 OU 的天梯最清晰；VGC 有真实职业圈但评估薄弱且数据过期快。具体选择与权衡见 `design.md`。

---

## 8. 可迁移的方法库（来自一般博弈 AI）

### 8.1 自博弈 / 种群 / 正则化均衡学习

| 方法 | 作者/年份 | 链接 | 与宝可梦的关系 |
|---|---|---|---|
| **Ataraxos**（Stratego 超人类，Nature 2026-09-30） | Sokota, Vinitsky, Hu, Kolter, Farina | [arXiv 2511.07312](https://arxiv.org/abs/2511.07312) | **最接近的模板**：MMD 自博弈 + "动态阻尼" + 57M 参数信念网络 + 测试时对约 1000 个采样的隐藏世界做 rollout 并在根节点做一步正则化更新；不到 8,000 美元（16×H100×1 周 + 4×H100×4 天）。差异：Stratego 是顺序动作、无随机节点（宝可梦有同时动作矩阵 + 伤害浮动等机会节点） |
| Magnetic Mirror Descent (MMD) | Sokota 等 2022 | [arXiv 2206.05825](https://arxiv.org/abs/2206.05825) | 对 PPO/actor-critic 损失加一个朝"磁铁策略"的 KL + 熵项；可近似一行改动 |
| DeepNash / R-NaD | Perolat 等 2022 | [arXiv 2206.15378](https://arxiv.org/abs/2206.15378) | 对周期性更新的参考策略做 KL 的奖励变换，使自博弈收敛而非循环；宝可梦的队伍相克有大量石头剪刀布式循环，这是针对性的缓解 |
| GAE 在不完全信息自博弈中的不足 / VRPO | Fan & Farina 2026 | [arXiv 2605.19235](https://arxiv.org/abs/2605.19235) | 平衡自博弈中 GAE 多步动作采样引入额外方差；与 PPO 自博弈直接相关（仅读到摘要） |
| AlphaStar league | Vinyals 等 2019 | [Nature](https://www.nature.com/articles/s41586-019-1724-z) | 主 agent + 主利用者 + league 利用者 + 优先虚拟自博弈；SL 初始化后 RL；迷你版（1 个主 + 1–2 个利用者 + 历史 checkpoint）单机可行 |
| OpenAI Five | Berner 等 2019 | [arXiv 1912.06680](https://arxiv.org/abs/1912.06680) | 超大规模 PPO 自博弈；纯 PPO 方案是可行基线，但有循环风险 |
| PSRO / double oracle | Lanctot 等 2017 | [arXiv 1711.00832](https://arxiv.org/abs/1711.00832) | 对池子的元纳什混合训练最佳响应；VGC-Bench 用过；N≈10–30 个 agent 时评测代价可承受 |
| NFSP | Heinrich & Silver 2016 | [arXiv 1603.01121](https://arxiv.org/abs/1603.01121) | 样本代价高，已基本被取代 |
| DouZero | Zha 等 2021 | [arXiv 2106.06135](https://arxiv.org/abs/2106.06135) | MC 回报 + 动作编码 + 并行 actor，4 卡单机；证明单机可行 |
| Suphx | Li 等 2020 | [arXiv 2003.13590](https://arxiv.org/abs/2003.13590) | **Oracle guiding**（训练时用看得到隐藏状态的教师特征，逐步淡出）直接适用；全局奖励预测可替代手工奖励塑形 |

### 8.2 不完全信息 / 同时动作下的搜索

- **ReBeL**（Brown 等 NeurIPS 2020，[arXiv 2007.13544](https://arxiv.org/abs/2007.13544)）：公共信念状态（PBS）上的自博弈 RL + CFR 子博弈；PBS 维度随隐藏信息增长，宝可梦需要压缩信念（PokaiTrainer 的候选菜单、Ataraxos 的采样）。
- **Student of Games**（Schmid 等 2023，[arXiv 2112.03178](https://arxiv.org/abs/2112.03178)）：growing-tree CFR + 反事实价值/策略网络；PokaiTrainer 即其改编（仅读到摘要）。
- **Update-Equivalence Framework**（Sokota 等 ICLR 2024，[arXiv 2304.13138](https://arxiv.org/abs/2304.13138)）：不做子博弈求解，而是用决策时算法复刻"最后迭代收敛"算法（如 MMD）的更新，是 Ataraxos 测试时那一步的基础；隐藏信息巨大时很合适（仅读到摘要）。
- **LAMIR**（Kubicek & Lisy，ICLR 2026，[arXiv 2510.05048](https://arxiv.org/abs/2510.05048)）：同时动作形式的学习抽象模型 + continual-resolving CFR+；**不能建模机会节点**，只在小型基准博弈上验证；有真实模拟器时通常无需学习模型。
- **Test-time RL in imperfect-information games**（Kubicek, Lisy, Sandholm，[arXiv 2608.30635](https://arxiv.org/abs/2608.30635)）：测试时带正则保证的策略梯度（仅摘要）。
- **Pluribus**（Brown & Sandholm 2019）：深度受限搜索中叶节点假设对手可从多个后续策略中选择，以获得鲁棒性——可借鉴为"叶节点在几种风格（强攻/防守）下估值"；算力数字 `[未验证]`。
- **同时动作 MCTS**（Lanctot、Lisy、Winands 等）：Decoupled UCT（实践最好但无收敛保证）、Exp3、Regret Matching（Hannan 一致，平均策略收敛到纳什）。若要不易被利用，最终出招应取 regret matching/Exp3 的**平均策略**而非 DUCT 的访问次数 argmax。
- **ISMCTS / PIMC / 确定化**：Foul Play 的顶层做法；已知问题为 strategy fusion 与 non-locality `[未打开原文]`。
- **MuZero 系**（Sampled MuZero [arXiv 2104.06303](https://arxiv.org/abs/2104.06303)、Stochastic MuZero）：为完美信息、顺序动作设计；宝可梦单打动作空间 ≤9 且有真实模拟器，关联弱。
- **ESCHER**（[arXiv 2206.04122](https://arxiv.org/abs/2206.04122)）、**DREAM**（[arXiv 2006.10410](https://arxiv.org/abs/2006.10410)）：无模拟器时的无模型深度 CFR 变体；有模拟器时 MMD/R-NaD 类更简单。
- **近似可利用度 / ISMCTS-BR**（Timbers 等 IJCAI 2022，[arXiv 2004.09677](https://arxiv.org/abs/2004.09677)）：可做可利用度代理——训练 RL 利用者去打冻结的 agent，报告其胜率。

### 8.3 离线 RL / 序列模型 / BC + RL

- **Decision Transformer**（[arXiv 2106.01345](https://arxiv.org/abs/2106.01345)）：回报条件序列模型；Metamon 刻意选 actor-critic + BC 正则的离线 RL，因为数据质量混杂、回报为二值。
- **AMAGO**（ICLR 2024，[arXiv 2310.09971](https://arxiv.org/abs/2310.09971)）、**AMAGO-2**（NeurIPS 2024，[arXiv 2411.11188](https://arxiv.org/abs/2411.11188)）：长序列 transformer 的 in-context RL；AMAGO-2 把 actor/critic 目标变成分类形式（与回报尺度无关）。Metamon 的引擎。
- **BC → RL 微调**：AlphaStar、Suphx、PokaiTrainer、VGC-Bench（BC 后 RL 优于纯 RL）、Metamon 一致发现：人类数据初始化大幅缓解冷启动。风险：replay 偏向低分玩家，可按 rating 过滤/加权。
- **蒸馏**：把慢而强的教师（带信念采样的搜索、Metamon 集成）蒸馏成能在计时器内运行的学生；Metamon README 称集成模型是天梯上最强的。
- **偏部分可观测的 transformer**：Metamon 表明整段历史记忆至关重要（截断会变差），能隐式推断对手配置；PokaiTrainer 表明显式信念摘要在搜索之上仍有 +8–12 个百分点。

### 8.4 LLM 智能体

- PokéLLMon、PokéChamp：LLM + minimax 比纯提示更强，但都停在约 1300–1500 Elo / 前 10–30%，且需要很长的计时。
- PokéAgent 结论：宝可梦对战 GXE 与常规 LLM 基准近乎正交（最大 Spearman 0.77，平均 |ρ| 0.45）；RL/搜索专才占优。
- 对单机项目的含义：LLM 更适合**离线**使用（数据标注、组队提案、解释、生成候选配置），而不是在线策略。

### 8.5 组队（Team building）

- 学术文献很少：VGC-Bench 留作未来工作；Metamon/PokaiTrainer 都不含组队（用人类/程序生成/固定队伍池）。
- 社区项目（非学术）：[FutureSightML](https://github.com/HotHams/FutureSightML)（transformer 编码 + 两两对阵矩阵 + XGBoost 胜率预测 + 遗传算法组队器，129 个赛制）、Smogon "Algorithmic Team Generation [Peaked 1457]"、Poke2Vec 向量化 + beam search、[Machine-Learning-Pokemon](https://github.com/gahogg/Machine-Learning-Pokemon)（遗传算法）。
- 可考虑的方法论（综合推断，非已验证）：把队伍视为元博弈中的策略，用 PSRO/double oracle 求队伍的不可利用混合；基于 13.9 万级人类队伍预训练自回归集合生成器，再用对战 agent 池做胜率奖励微调；用 FutureSight 式代理模型筛选；对抗式组队 = (队伍, agent) 收益矩阵的 max-min。

---

## 9. 评测方法

### 9.1 Showdown 评分

- 三个数字：Elo（排名）、Glicko-1、GXE（对随机天梯对手的预估胜率）。[官方说明](https://pokemonshowdown.com/pages/ladderhelp)。
- Elo 初始 1000 且有下限 1000，K 值动态、有衰减；Glicko-1 初始 R=1500、RD=130。公开服务器的确切 K 值/衰减代码是私有的 `[未验证]`（开源的 `ladders-local.ts` 与官方说明不完全一致）。
- 因 Elo 有下限、K 不对称且有衰减，**跨期比较应优先用 Glicko-1/GXE 或自己的 Bradley-Terry 拟合**。
- 天梯只显示前 500 名，约每 4 小时刷新。

### 9.2 前人如何估计"人类水平"

- Metamon：公共天梯上每世代 400–613 场对匿名人类，报告 GXE + Glicko-1 + 排名；分位数用 14,022 个活跃用户名（Gen1–4）计算。此后作者对上天梯更谨慎。
- PokéChamp："预测 Elo 1300–1500 = 前 30%–10%"，外推得到。
- PokéLLMon：天梯 49%、邀请赛 56%（"人类水平"门槛很低）。
- Foul Play：GXE + 峰值 Elo + 峰值排名。
- Jaxcalibur：峰值 Elo/GXE 与占据第 1 的时间比例。
- VGC-Bench：对人类的胜率，轶事性质（每人 5 局），并指出天梯不适合评估同分布队伍表现，因为无法控制对手队伍。
- PokaiTrainer：新账号上 150 场 Bo3，对手平均约 1320 Elo。
- Sarantinos：主张用百分位（Showdown 只显示前 500 名）。

### 9.3 本地评测基线

- poke-env：`RandomPlayer`、`MaxBasePowerPlayer`、`SimpleHeuristicsPlayer`。
- Metamon：6 个启发式 + 40+ checkpoint；`python -m metamon.rl.evaluate --eval_type {heuristic,il,ladder,pokeagent,challenge}`；`h2h` 两两对战胜率矩阵。**其本地 GXE 与公共天梯 GXE 没有对应关系**（作者明确说明）。
- Foul Play：强搜索基线（单打各世代，不含 VGC）；PokéChamp：LLM 基线；VGC 基线：VGC-Bench 的 BC/SP/FP/DO。
- PokéAgent 服务器：注册账号后可排队 bot-vs-bot 排位，用 BT 评分；赛制含 Gen1–4 OU、Gen9 OU、Gen9 VGC，没有人类玩家。

### 9.4 种群级评测与样本量

- 偏好 FH-BT + bootstrap 置信区间（对局数分布不均时）；Nash averaging（Balduzzi 等 NeurIPS 2018，[arXiv 1806.02643](https://arxiv.org/abs/1806.02643)）可避免 league 中克隆体抬高评分。宝可梦存在队伍相克的非传递环，应固定队伍池，汇报胜率矩阵 + Nash/BT。TrueSkill 无前人使用 `[未验证]`。
- 评测队伍要受控：双方用固定抽样队伍并互换座位，以分离"组队运气"与"操作水平"。
- 二项分布 95% 置信区间半宽（p=0.5，我的计算）：

| 局数 | 半宽（百分点） | 约 Elo 半宽 |
|---|---|---|
| 50 | 13.9 | 99 |
| 100 | 9.8 | 69 |
| 200 | 6.9 | 48 |
| 400 | 4.9 | 34 |
| 1000 | 3.1 | 22 |
| 2000 | 2.2 | 15 |
| 5000 | 1.4 | 10 |

  检验 55% vs 50%（单侧 α=0.05、80% 功效）约需 615 局；52% 约 3,857 局；60% 约 152 局。天梯估计还有额外方差（对手池漂移、Glicko RD 非平稳）。

### 9.5 人类 pro 基准

- VGC 世锦赛 2026：旧金山，8 月 28–30 日；冠军 Takuma Yamazaki，亚军 Hiroshi Onishi；Reg M-B，Pokémon Champions，Bo3，50 级。
- 唯一"击败职业选手"的说法来自 VGC-Bench v3：Aaron Traylor（多次世锦赛选手）"至少赢了 AI 一局"，评测"有意为轶事性质"，专家可逐局适应，因此证据很弱。**未发现任何与世锦赛冠军的官方人机表演赛**。
- Smogon 侧：顶尖天梯玩家是事实上的基准（MichaelderBeste2，随机对战 GXE 94.7，2.68 万场）。未发现 Smogon 锦标赛中人机表演。Smogon 社区总体对公开最强 bot 持敌意。
- PokéAgent 论文定位：宝可梦对战是"未解决的基准"，现有系统"尚非超人"。

### 9.6 天梯礼仪 / ToS

- Showdown 规则与 FAQ 中**没有明确的 bot 条款**。政策散见于 Smogon 论坛帖：管理员称"若 bot 损害人类体验，将永封"；另一位管理员称封禁 bot"在任何层面都不可行"、也无法可靠检测；2025-11 数据显示 bot 队伍会扭曲使用率（某 bot 贡献了 Torkoal 使用率的 56%、Excadrill 的 38%）。没有 bot 注册/标识机制。
- 实际做法（推断自上述 + 社区惯例，非官方规定）：使用明确命名的 bot 账号；不要在低人口天梯或 suspect 测试期间每天跑 200+ 局；不要通过 bot 操纵使用率分层；遵守计时器；不要用 bot 辅助人类参赛（社区强烈反对）。
- 限速：官方服务器有登录/天梯节流；poke-env 文档建议自建服务器做训练；天梯需要注册账号并使用密码，具体限制 `[未验证]`。
- 建议：100% 本地训练；bot-vs-bot 评测用 PokéAgent 服务器；公共天梯评测仅对最终 checkpoint 用新开、明确标注的账号跑几百局。

---

## 10. 工程经验

1. **引擎吞吐是第一瓶颈**：PokaiEngine 中位回合 0.08 ms vs Showdown 2.0 ms；Foul Play 把 Python 引擎改写成 Rust 后搜索深度达约 10 回合；Metamon 用本地 Showdown 天梯生成自博弈（精确但慢）。训练前应验证引擎一致性（advsim 的验证方式——整局比对 + 决策点比对 + 伤害用例——可作为范例）。
2. **观测编码**：Metamon 用"文本 token + 数值特征 + 跨时间的 transformer"；VGC-Bench/PokaiTrainer 用"实体 token"（12 个宝可梦 token / 14 token 含场地）；Jaxcalibur 用 66 个 token。一种自然的混合：每回合实体 token（己方 6、对方 6 并为未知属性做信念 embedding、场地/一侧条件）+ 跨回合因果 transformer；species/move/item/ability 共享 embedding；分开表示"已揭示"与"推断"信息。（设计建议，非单一来源。）
3. **动作掩码**：Huang & Ontañón（[arXiv 2006.14171](https://arxiv.org/abs/2006.14171)）证明掩码对策略梯度是合理的；单打约 9 个动作，双打用每槽位因子化头。
4. **奖励**：Metamon 用稀疏胜负 + 轻量塑形；多 γ 分析表明长时程 γ≈0.999 有益；Suphx 用学习的全局奖励预测。手工 HP 差塑形可能教出"拖血量"的怪习惯——塑形要小并退火。
5. **样本效率**：BC/离线预训练、搜索提升数据质量、分类式 critic、方差缩减的优势估计、搜索蒸馏。Ataraxos 用不到 DeepNash 1/100 的训练样本达到更好水平（新闻报道，部分验证）。
6. **批量推理**：多 CPU 引擎进程 + 单 GPU 对所有进行中对局做批量策略/价值推理（推理服务器模式）；模型保持小（5–60M：PokaiTrainer 5.4M、Jaxcalibur 8.5M、mikumiku37 8.7M、Abra 57M、Tauros 62M）以便搜索叶节点评估足够快。
7. **对手池 / league**：AlphaStar league（主 + 利用者）、PSRO/DO/FP（VGC-Bench）、Metamon（多 checkpoint + 刻意不现实的队伍以提升鲁棒性）、PokéAgent Porygon2AI。池中保留人类数据训练的锚点，避免只在自博弈约定里漂移；加入启发式 bot 做健全性检查。
8. **可利用度代理**：(a) FH-BT/Glicko/GXE；(b) 与历史 checkpoint 及 Foul Play、Metamon、PokéChamp 的循环赛；(c) 训练利用者对冻结 agent 的胜率；(d) (agent, team) PSRO 收益矩阵；(e) 人类评测。另需按回合追踪价值网络校准（PokaiTrainer 报告前 3 回合的 Brier 0.22，第 8 回合后 0.10，即早期乐观）。
9. **时间限制**：PokéAgent 标准 30 秒起始 + 每回合 3 秒（上限 8 秒）；Foul Play 每步约 7 秒；搜索按墙钟预算（DUCT/regret matching 是 anytime 算法）。
10. **已知失败模式**：防守/stall 队伍与长期规划（Foul Play、PokéChamp）；闭队伍表推断（PokaiTrainer 未解决）；队伍相克的非传递性（VGC-Bench）；replay 与真实服务器的 sim2sim 差距（Metamon）；早期价值乐观（PokaiTrainer）；LLM 的恐慌换人与超时。

---

## 11. 未验证 / 相互冲突的信息

- Metamon 训练算力（GPU 小时）、上下文长度。
- PokéAgent 获奖方法的附录细节；实时排行榜。
- PokeJAX 是否开源、覆盖哪个世代/赛制。
- poke-engine 的实际世代覆盖（README 与 changelog 不一致）。
- Laplace 仓库细节、Technical Machine 的强度、各种小型 GitHub 项目质量。
- **Jaxcalibur**：网站页面显示 2024 年份、论坛帖时间为 2026 年（据抓取结果判断以 2026 为准）；训练时长"约 1 周（网站）"与"六个月（论坛帖，可能指总开发时间）"；首次登顶时间"5 月"与"8 月"不一致。**mikumiku37** 页面日期同样出现 2024 的摘要错误。
- Metamon SyntheticRLV2 的 Gen1 GXE：论文 79.9% vs README 77%，两者都是项目自己的数字。
- Foul Play Gen9 OU 峰值 Elo：博客 1879 vs 论坛帖"1930+"。
- Metamon 集成模型"登顶 Gen1 OU 天梯"仅来自 README，未在榜单页独立确认。
- Elo 的确切 K 值、天梯赛季是否重置 Elo、官方速率限制。
- 若干只看到摘要的论文（SoG、Update-Equivalence、Test-time RL、GAE/VRPO）与未打开的经典工作（ISMCTS、Libratus、Obscuro、AlphaStar/Pluribus/OpenAI Five 的算力数字）。
- Ataraxos 的 Nature 页面需登录，细节取自 arXiv HTML 与新闻报道。

---

## 12. 参考链接

**对战 AI 与论文**
- Metamon：https://github.com/UT-Austin-RPL/metamon · https://arxiv.org/abs/2504.04395 · https://huggingface.co/jakegrigsby
- PokéAgent Challenge：https://arxiv.org/abs/2603.15563 · https://pokeagentchallenge.com · https://battling.pokeagentchallenge.com
- VGC-Bench：https://arxiv.org/abs/2506.10326 · https://github.com/cameronangliss/vgc-bench
- PokaiTrainer：https://arxiv.org/abs/2608.29197
- PokéChamp：https://arxiv.org/abs/2503.04094 · https://github.com/sethkarten/pokechamp · https://huggingface.co/datasets/milkkarten/pokechamp
- PokéLLMon：https://arxiv.org/abs/2402.01118
- Foul Play：https://github.com/pmariglia/foul-play · https://pmariglia.github.io/posts/foul-play/ · https://www.smogon.com/forums/threads/re-introducing-foul-play-a-competitive-pokemon-battle-bot.3767378/
- Jaxcalibur：https://jaxcalibur.github.io/ · https://www.smogon.com/forums/threads/jaxcalibur-a-gen-9-randbats-bot-that-reached-1-on-the-ladder.3787537/
- mikumiku37：https://www.smogon.com/forums/threads/mikumiku37-a-self-play-vgc-bot-reached-1-on-the-vgc-reg-m-c-ladder.3789199/
- Huang & Lee 2019：https://ieee-cog.org/2019/papers/paper_175.pdf
- Sarantinos：https://arxiv.org/abs/2212.13338

**模拟器 / 引擎**
- Pokémon Showdown：https://github.com/smogon/pokemon-showdown
- pkmn/engine：https://github.com/pkmn/engine · pkmn/ps：https://github.com/pkmn/ps
- advsim：https://github.com/zkingston/advsim
- PokeJAX：https://arxiv.org/abs/2603.12145
- minimon：https://github.com/spktrm/minimon
- poke-engine：https://github.com/pmariglia/poke-engine
- pokemon-showdown-rs：https://github.com/vjeux/pokemon-showdown-rs
- poke-env：https://github.com/hsahovic/poke-env · https://poke-env.readthedocs.io

**数据**
- Replay API：https://replay.pokemonshowdown.com/search.json · https://github.com/smogon/pokemon-showdown-client/blob/master/WEB-API.md
- 天梯 JSON：`https://pokemonshowdown.com/ladder/<format>.json`；说明：https://pokemonshowdown.com/pages/ladderhelp
- Smogon 统计：https://www.smogon.com/stats/
- HF 数据集：https://huggingface.co/datasets/HolidayOugi/pokemon-showdown-replays · https://huggingface.co/datasets/cameronangliss/vgc-battle-logs
- Pokepaste 语法：https://pokepast.es/syntax.html

**通用方法**
- Ataraxos：https://arxiv.org/abs/2511.07312 · MMD：https://arxiv.org/abs/2206.05825 · R-NaD：https://arxiv.org/abs/2206.15378
- ReBeL：https://arxiv.org/abs/2007.13544 · SoG：https://arxiv.org/abs/2112.03178 · Update-Equivalence：https://arxiv.org/abs/2304.13138
- LAMIR：https://arxiv.org/abs/2510.05048 · Test-time RL：https://arxiv.org/abs/2608.30635 · VRPO：https://arxiv.org/abs/2605.19235
- AMAGO：https://arxiv.org/abs/2310.09971 · AMAGO-2：https://arxiv.org/abs/2411.11188
- Nash averaging：https://arxiv.org/abs/1806.02643 · 动作掩码：https://arxiv.org/abs/2006.14171
