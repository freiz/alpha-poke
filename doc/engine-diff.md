# poke-engine 与 Showdown 的差分实验

## 目的

搜索用 poke-engine（Rust，速度快、能枚举随机结果、能撤销）作为转移模型；对局由 Showdown 的模拟器（TypeScript，`vendor/pokemon-showdown`）裁决，对我们来说它就是标准答案。两者不一致的地方，会让搜索在错误的模型上做决策；我们自己构造局面（`agents/engine_state.py`、`timers.py`）的遗漏，会让搜索从错误的起点出发。自对弈每代提升变小（2026-10-16），这是要排查的原因之一。

差分实验的目标：系统地找出"引擎预测"和"Showdown 实际结果"不一致的地方，按出现频率和影响排序，逐个确认、修复。

## 方法

### 0. 完全信息随机对战差分（主方法，2026-10-16 起）

脚本：`scripts/check_engine_random.py`（runner `enginecheck/random_battle.js`）。在 Showdown 的模拟器里用真实 OU 队伍（自对弈的队伍对）对战，双方从合法选项里随机出招（换人约 15%、太晶化约 10%），每个决策点导出模拟器内部的完整真实状态。每个"本回合开始 → 下回合开始、中间没有其它决策"的回合：用 Showdown 自己的数值构造引擎局面（`engine_state`），引擎对同一对选择的全部分支和下一回合的真实状态比较（`closest(hp=True)`）。

为什么是主方法（用户 2026-10-16 指出）：自对弈记录的差分（下面第 1 节）是两个玩家视角的拼接，场地字段取自一方的视角，对方设置的天气 / 场地的剩余回合是按信念猜的；记录的局面又是当时代码构造的，旧数据带着旧的构造问题。差分要比的是完全信息，不能带任何推测。随机对战的状态直接来自模拟器，没有视角、没有信念；随机出招还覆盖了 bot 很少用的招式和情形。局面构造（`build_state`）单独测：同一场对战里把玩家实际收到的协议和请求喂给它，和真实状态比较（完全信息测试）。

harness 必须把 Showdown 的状态完整映射到引擎，否则不一致来自 harness 而不是引擎。第一次跑（300 场，91.2%）暴露的 harness 缺口：上一次使用的招式（Encore、Fake Out 需要；缺了引擎 panic）、挑衅 / 再来一次 / 哈欠 / 混乱 / 睡眠 / Rest 的计数（Showdown 倒数剩余，引擎正数已过：挑衅 / 再来一次 3 − D，哈欠 2 − D，混乱 5 − time，睡眠 startTime − time，Rest 剩余 time）、守住的连续次数（Showdown stall 计数 3^n）、属性变化（Showdown 不留持续状态，只改属性；比较时统一成"当前属性不同于原属性"）、引擎不认识的道具（按 unknownitem 比较，缺哪些由数据测试列出）、Struggle（引擎没有这个选择，不比较）。补齐后 93.3%。

**每次修复只能是真子集（用户 2026-10-16 要求）**：对局是确定性的（固定的 300 对队伍 `tests/fixtures/random_battle_teams.jsonl`、固定的模拟器种子和出招种子，出招不依赖引擎），所以局面有稳定的编号 `b<场>-t<回合>`。每个不一致记为（编号, 类别），全部存在基线 `tests/fixtures/engine_random_baseline.json`。每次修复后重跑：新的集合必须是基线的子集，出现基线里没有的（编号, 类别）就是 regression，脚本列出编号、差异和那一回合的日志，以失败退出；通过了才用 `--update-baseline` 更新基线（只在是子集时才写；有意的变化，例如 harness 补齐后暴露出更多，要加 `--force` 并在本文档说明）。第一份基线（2026-10-16，L20–L23 之后）：533 个，一致率 93.5%；连跑两次新增 0、修复 0（确定性）。

方法 / harness 的修正（2026-10-16 晚，504 → 419，新增 0，94.9%）：HP 容差的伤害之和只算正的伤害（Pain Split 用"负伤害"表示回复，原来使容差变负，两边相等也判不一致）；吸取 / 反伤招式、Shell Bell 持有者的 HP 跟着它造成的伤害走，容差加上对方伤害的 8.5% × 3/4；Wish 映射到引擎（新版 Showdown 用 startingTurn：在 startingTurn + 2 回合的回合末回复，引擎在计数为 1 的回合末回复；回复量是未取整的 maxhp / 2）。

**验证集（用户 2026-10-16 要求：多起几批新的随机对局验证，不能只对着这 300 场修）**：`scripts/check_engine_random_sets.sh` 跑主集合和四个验证集，各有自己的基线（`tests/fixtures/engine_random_baseline_<集合>.json`），每次修复后五个都必须是子集：`seed10k`（同样的 300 对队伍，种子偏移 10000：`--seed-offset`）、`offmeta`（偏门池 200 对）、`random`（随机池 200 对）、`wide`（天梯池 wide1000 的第 300–599 对）；队伍对在 `tests/fixtures/random_battle_teams_<集合>.jsonl`。L82 之后又加了三个（用户要求多起几批）：`wide2`（wide1000 的第 600–899 对，种子偏移 30000）、`wide200`（wide200 池的第 0–199 对，偏移 40000）、`forum`（论坛精选的 162 支队伍随机配 200 对，偏移 50000）；第一次跑 98.4% / 98.7% / 98.5%（139 / 78 / 111 处），之后每次修复八个集合都必须是子集。2026-10-17 起比较扩大到停在决策点的回合（击倒后的替换、换人招式的换人；原来跳过，约占四成回合）：从回合开始到决策点，引擎也停在那里；倒下的在场宝可梦的能力变化 / volatile 不比较（Showdown 倒下时清掉，引擎在替换时）；倒下的宝可梦的道具也不比较（之后再无作用；Showdown 不让倒下的持有者用掉道具：Weakness Policy、被击倒时的 Knock Off）。基线因此一次性 `--force` 更新（新增的全是决策点回合，普通回合没有新增；wide200 b68-t24 原来就在基线里，只是换了一个最接近的结果）。扩大后八个集合 98.5–99.5%（每个集合约 7,000–10,700 个回合）。第一次跑（L57 之后，主集合 99.2%）：98.6% / 97.6% / 98.3% / 98.5%，比主集合低，说明有主集合没覆盖到的机制（Cursed Body、Magic Bounce、Beat Up、Metronome、Stockpile 等）。

另外两点：binding 的 panic 是 BaseException，必须接住；多进程要用 spawn（fork 出来的 worker 会继承扩展模块线程持有的锁而死锁）。

### 1. 差分统计（找线索）

脚本：`scripts/check_engine_diff.py`。

- **数据**：自对弈对局（`data/selfplay/gen<G>/decisions-w*.jsonl`）。对局在本地 Showdown 上进行，双方都是我们的 bot，每条决策记录里该方己方的信息是精确的（来自 Showdown 的请求）。
- **干净回合**：第 t 回合开始和第 t+1 回合开始双方都有决策记录，中间没有任何其它决策（没有倒下后的换人、没有 U-turn 类的中途换人）。
- **比较**：
  - S_t = 双方第 t 回合记录的合并（`alpha_search.merge_sides`：一方的精确视角拼另一方的精确视角）；
  - 引擎：对 S_t 和双方实际选的动作枚举所有随机结果（`alpha_search.chance_outcomes`，含伤害分支）；
  - 实际：第 t+1 回合双方记录的合并。
- **一致的标准**：
  - 随机性不算不一致：命中 / 未命中、要害、追加效果、速度相同时的先后，引擎都会枚举成带概率的分支，实际结果和任何一个分支一致即可；
  - 离散字段（在场宝可梦、异常状态、能力等级、钉子、墙、持续状态、道具、天气 / 场地）必须和某个分支完全一致；
  - HP：引擎用平均伤害（最大伤害 × 0.925；只在"能否击倒"和"要害"处分支，2–5 段招式固定 3 段），所以实际 HP 允许落在该分支伤害按浮动比例（0.85 / 0.925 到 1 / 0.925）的范围内，外加 1% 最大 HP 的取整余量。
- **数据读取**：一代的决策记录约 33 GB，脚本逐个文件流式读取，同一局的记录在文件里是连续的，凑齐一局就处理、处理完就丢；按局号哈希抽样。运行时必须加内存上限（`systemd-run --user --scope -p MemoryMax=6G -p MemorySwapMax=0`）。2026-10-16 第一版一次读入全部记录，占满内存导致 WSL 重启。

- **HP 不一致的拆分**：按差值（实际 − 引擎）占最大 HP 的比例归到 ±1/16、±1/8、±1/12 等常见分数，分在场 / 后备，每簇记招式组合和例子（`hp_gaps`）。分数本身就是线索：1/16 是剩饭 / 灼伤，1/8 是束缚 / 中毒 / 黑色污泥，1/12 = 1/4 − 1/6 是 Spikes 2 层（L11）。
- **看例子**：`scripts/explain_engine_diff.py --gen G --hp "bench +1/12"`（或 `--kind status`）对每个例子列出那只宝可梦、Showdown 这一回合的协议日志（`logs-w<k>.jsonl`，流式读）、引擎各分支的 HP 变化，基本一眼能看出成因，再去写双引擎测试。
- **新数据**：局面构造的修复只有在修复后打的对局上才看得到（旧数据记录的局面是旧代码构造的）。诊断用的对局放在 `data/selfplay/gen900`（当前网络、当前代码，600 局；`selfplay.py teams/run --gen 900`），不进训练。

### 1b. 数据测试（数据表一致）

`tests/test_engine_data.py`（`alpha_poke.enginecheck.data`，Showdown 侧 `showdown_data.js`，引擎侧 `alpha_search.engine_data` / `engine_base_stats`）：引擎的招式表（类型、命中、分类、威力、优先度、标志、自身 / 目标能力变化、异常 / 持续状态效果（招式本身按 100%、追加效果按概率，两边统一成同一种形式）、吸取、反伤、回复、场地状态、拖人 / 换人）、属性相克表（引擎的 `type_effectiveness_modifier` 逐对调用）、换形态种族值，以及 poke-env 的图鉴 / 招式，和 Showdown 的 Gen 9 `Dex` 比较。所有差异必须列在测试的已知差异表里并写明原因：出现新差异、或列出的差异已经不存在，测试都失败。

差分统计的结果只是线索，里面混着三种来源：引擎的错误、我们构造局面的错误、方法本身的假象（伤害取平均、没记录到的决策、随机拖人等）。

### 1c. 伤害公式差分（2026-10-16 晚）

脚本：`scripts/check_damage_calc.py`（探针 `enginecheck/showdown_damage.js`）。在随机对战（同上 300 场）的每个回合开始，对双方在场宝可梦的每个攻击招式：Showdown 在对战的副本上调它自己的 `getDamage`（随机数固定取最高档、不暴击；先跑 ModifyType / ModifyMove / PrepareHit、目标的 TryHit 和招式的 Try，免疫和 Libero 之类才算进去），引擎用 `calculate_damage` 从同一个状态算最高档，逐点比较（49,726 个（局面, 招式））。不比较的：伤害取决于出手顺序或本回合事件的招式（Payback、Sucker Punch、Future Sight 等）、引擎自己处理的固定伤害（Endeavor）、探针的随机威力（Fickle Beam）、Analytic（探针的行动队列是空的）、Disguise / Ice Face / 替身 / 半无敌（getDamage 看不到）。报告 `data/selfplay/diag/damage_calc.json`（分档、按招式 / 特性 / 道具 / 天气 / 场地分组、例子），每一行 `damage_calc.rows.jsonl`。

| | 逐点一致 | 差 1 | 2% 以内 | 超过 2% |
|---|---|---|---|---|
| 第一次（L30 之后） | 76.2% | 11.4% | 2.9% | 9.4% |
| L31（太晶本系）、L32、L33 之后 | 85.0% | 11.3% | 2.9% | 0.8% |
| L34 第一步（Showdown 的取整顺序） | 92.7% | 4.3% | 2.2% | 0.9% |
| L34 全部、L35 | **99.9%** | 0.0% | 0.0% | 0.1% |

剩下的 0.1%（52 个）：Hydro Steam 在晴天（差 1%）、Metronome 道具的连续使用加成不在伤害计算里、Shell Side Arm 的物理 / 特殊判断、Psychic Terrain 挡先制（探针看不到，引擎在别处处理）等，见下一步。

双引擎测试也因此加了更严格的一类：`alpha_search.damage_rolls` 给出引擎精确的 16 档掷骰，Showdown 实际造成的伤害必须是其中之一（暴击时是暴击的 16 档）；最高档还要逐点等于 Showdown 探针的 getDamage（`run_showdown(..., damage_probe=True)`）。HP 容差（8.5%）的比较测不出 1–3% 的差别，也会被 1.5 倍的暴击分支"碰巧"匹配，单看 HP 的测试要排除暴击分支。

### 2. 双引擎单元测试（确认）

每一条线索，都要构造一个具体场景（双方队伍、动作序列、固定种子），分别在 Showdown 的模拟器和 poke-engine 里运行，比较结果。只有单元测试复现了差别，才算"确认"，并据此归类：

- **引擎**：同一个起始局面，两边结果不同；
- **局面构造**：Showdown 实际状态里有、我们从协议构造的局面里没有（或相反）；
- **方法假象**：不是真正的不一致，改进差分脚本的判定。

确认用的测试留作回归测试；引擎问题的测试在修复前标记为预期失败（`xfail(strict=True)`），修好后转为正常测试。

框架（`alpha_poke.enginecheck`，测试在 `tests/test_dual_engine.py`）：

- `run_showdown(p1, p2, turns, seed, force_random)`：`showdown_case.js` 用 Showdown 的模拟器（`vendor/pokemon-showdown/dist/sim` 的 `Battle`，格式 `gen9customgame`，固定种子；`force_random` 让所有概率判定都成立 / 都不成立）跑指定的回合，输出设置完成后和每回合后的完整状态：双方每只宝可梦（按队伍原始顺序）的 HP、异常状态（含剧毒计数、睡眠回合）、道具、特性、属性、能力值、能力等级、持续状态、招式 PP，场地条件、天气 / 场地及剩余回合、协议日志；
- `engine_state(state)`：用 Showdown 自己算出的数值构造 poke-engine 局面（能力值、HP、PP 都直接取 Showdown 的），排除我们构造局面这一环，测的只是引擎；
- `engine_outcomes(state, c1, c2)`：引擎对同一对动作的全部随机结果；
- `view` / `view_engine` / `closest`：两边状态转成同一种格式，找最接近 Showdown 结果的引擎分支，列出差别（HP 不比：引擎用平均伤害）。
- HP 比较（`closest(..., hp=True)`）：容差 = 这一方在该分支里受到的伤害（引擎指令之和）× 8.5% + 2。最初的框架不比 HP，盐腌、部分束缚的"一致"只在离散状态上成立；补上后重新验证。
- Showdown 等待强制换人（有宝可梦倒下）而给定的动作不是换人时，`showdown_case.js` 就停下，返回到这一步为止的状态。
- 对照测试（两边应一致的场景）证明框架本身判断正确：`test_start_state_is_the_same`、`test_control_spikes_and_roost_agree`、`test_control_volatile_of_engine_state_string`。
- 局面构造的测试（`built_state`）：同一场 Showdown 对战（gen9ou，有队伍预览），把某一方玩家实际收到的协议消息（`player_log`：`|split|` 之后自己那一行是精确 HP）和请求喂给 poke-env，跑我们的 `build_state`，和 Showdown 的真实状态比较；自己视角、对方视角都看。
- 教训（L2）：差分统计里"引擎有、实际没有"的类别，最初一律猜成局面构造漏读；双引擎测试分开之后，三项里两项其实是引擎的问题。差分的类别只能当线索，结论必须来自测试；简单场景复现不出来时，回到差分的例子里找条件（盐腌是"目标有替身"）。
- 注意：poke-engine 的 Python 绑定 `State.apply_instructions` 返回新的局面，不改原局面（2026-10-16 我先按原地修改用错了一次）。
- 注意：Python 绑定的 `Side` 接受任意持续状态名，引擎读到不认识的名字时悄悄变成 NONE。框架判断"引擎认不认识"原来只构造了 `Side`，等于全部认识，Showdown 的 `choicelock` 因此进了比较（L16b 的 Trick 测试暴露）；改为写成局面字符串再读回来，名字还在才算。
- 预知未来：Showdown 新版把它记成目标位置上的 slot condition（`futuremove`，`endingTurn`，第 endingTurn + 1 回合的回合末命中），引擎记在使用方（`future_sight` = (剩余回合, 使用者位置)）；框架做了换算（L15）。

### 3. 修复流程（不直接改）

1. 线索 → 双引擎单元测试确认；
2. 写进本文档的问题表，和用户确认要不要修、怎么修；
3. 修复：引擎问题改 `rust/patches/poke-engine-0.0.48`（"alpha-poke patch" 注释），局面构造问题改 `agents/engine_state.py` / `timers.py`；
4. 回归检查，全部通过才算完成：
   - 确认测试转为通过，其它测试不变；
   - 确定性搜索回归（固定种子的搜索结果，前后对比）；
   - 差分统计重跑，对应类别下降、其它类别不上升；
   - 可能改变行为的修复，做 A/B 对战（不变差）。

## 结果

### 第 8 代，3,000 局，修正方法后（2026-10-16）

方法的三处修正（都由双引擎测试发现：测试复现不出差分里的类别，说明是脚本的问题）：
1. HP 容差按这一方本回合实际受到的伤害（引擎的伤害指令之和）计算，不按 HP 净变化：有回复又有伤害的回合原来几乎全部误判（L5）；
2. 不可比较的回合单独计数、不进分母：回合中有宝可梦倒下（引擎停在要求换人的那一刻，而玩家的换人是下一个决策，只有一个选项时没有记录）、用了 U-turn 类或拖人招式（L6）；
3. 忽略序列化产生的 NONE 持续状态（L4）。

结果：42,611 个可比较回合（另有 2,694 个回合有倒下、700 个有 U-turn 类招式、649 个有拖人招式），一致率 **86.1%**。主要不一致：HP 7.97%、天气 1.67%（L3a）、闪避 1.36%（L1）、诅咒 0.61%（L2a/b）、部分束缚 0.56%（L2c）、道具 0.55%、防御等级 0.51%、异常状态 0.51%、场地 0.37%（L3b）、混乱 0.31%；在场宝可梦只剩 0.08%。

### 第 8 代，3,000 局，46,654 个干净回合（2026-10-16，第一版判定标准，已过时）

一致率 **75.6%**（35,292 个回合）。不一致的类别（一个回合可能同时属于多类）：

| 类别 | 回合 | 比例 | 初步判断（未确认） |
|---|---|---|---|
| HP | 6,982 | 14.97% | 需要按差值拆分：回复类招式（恢复、羽栖）占比最高；回合末残余效果漏算 / 多算（1/16、1/8 等） |
| 在场宝可梦 | 2,953 | 6.33% | 多数应为没记录到的中途决策（只有一个选项的强制换人、U-turn）和随机拖人，属于方法假象，待从统计中分离 |
| 持续状态 `none` | 1,617 | 3.47% | 序列化问题 L4（已确认）：对比时应忽略 NONE，属于方法假象 |
| 天气 | 859 | 1.84% | 多为引擎里天气仍在、实际已结束：天气回合数的追踪 |
| 闪避等级 | 591 | 1.27% | Defog 没有降低目标闪避（引擎 0，实际 −1） |
| 防御 / 攻击等级等 | 每类 < 1% | | 待看 |
| 异常状态 | 371 | 0.80% | 部分和换人有关；"Hurricane / Dragon Tail 后目标麻痹"疑似接触类特性（静电） |
| 道具 | 322 | 0.69% | 待看 |
| 诅咒 / 部分束缚 / 盐腌 | 266 / 235 / 116 | 0.57% / 0.50% / 0.25% | 当初猜都是局面构造漏读；双引擎测试后只有部分束缚是（L2c）。诅咒是引擎的 L2a / L2b，盐腌是引擎的 L2d（替身挡不住）；盐腌和诅咒的局面构造本身是对的（对照测试） |

## 线索与问题表

状态：线索（差分统计）→ 已确认（双引擎测试）→ 已同意（和用户）→ 已修复 → 已验证（回归检查通过）。

| 编号 | 描述 | 来源 | 状态 | 测试 | 修复 |
|---|---|---|---|---|---|
| L1 | Defog 不降低目标闪避（Showdown −1，poke-engine 0） | 引擎 | 已修复 | `test_l1_defog_lowers_evasion` | `choice_effects.rs`：Defog 先对没有替身的目标施加闪避 −1（复用 `apply_boost_instruction`，免疫 / 天邪鬼照常）；没有给 `StatBoosts` 加闪避字段（两百多处字面量，风险大） |
| L1b | L1 的修复没有考虑 Magic Bounce：Defog 被反弹时（Hatterene），Showdown 降的是原使用者的闪避，引擎降的是反弹者的 | 引擎 | 已修复 | `test_l1b_defog_magic_bounce` | `choice_effects.rs`：Defog 降闪避的对象按 `choice.target`（被反弹时 Magic Bounce 把它改成 User） |
| L2a | Ghost 系的 Curse 没有实现：poke-engine 只有非 Ghost 系的版本（自己 +1 攻 / +1 防 / −1 速），Ghost 系使用时不付一半 HP、对方不被诅咒；引擎里也没有诅咒的回合末伤害，即使局面里对方带着 `curse` 也不扣血 | 引擎 | 已修复 | `test_l2a_ghost_curse` | `choice_effects.rs` `modify_choice`：Ghost 系使用时无能力变化、对方挂诅咒（已被诅咒则失败）、自己扣一半最大 HP；`generate_instructions.rs` 回合末：被诅咒的扣 1/4（至少 1） |
| L2b | 非 Ghost 系的 Curse 在使用者身上多挂一个 `curse`（不扣血，只是标记；但网络输入的诅咒位因此被置 1，真实局面不会有） | 引擎 | 已修复 | `test_l2b_non_ghost_curse_no_volatile` | 同上：非 Ghost 系只有能力变化，去掉诅咒标记 |
| L2c | 部分束缚（Infestation、Whirlpool、Fire Spin、Sand Tomb、Magma Storm、Bind、Wrap 等）没有进入我们构造的局面（`build_state` 的持续状态映射里没有它）：搜索里看不到"被困住不能换人"和每回合 1/8 的伤害。引擎本身对部分束缚的处理和 Showdown 一致 | 局面构造 | 已修复 | `test_l2c_built_state_partial_trap` | `engine_state.py`：Bind / Wrap / Fire Spin / Whirlpool / Sand Tomb / Magma Storm / Infestation / Snap Trap / Thunder Cage / Clamp（poke-env 按招式名记）映射为 `partiallytrapped`；引擎已正确处理 Ghost 系与脱壳的例外 |
| L2d | Salt Cure 打在替身上时，引擎仍然给目标挂上盐腌（Showdown 被替身挡住） | 引擎 | 已修复 | `test_l2d_salt_cure_blocked_by_substitute` | `generate_instructions.rs` `run_move`：攻击招式打在替身上时，不对目标施加招式的持续状态 |
| L3a | 构造的天气剩余回合数一直是 4（引擎本身每回合递减、按时结束都和 Showdown 一致）：poke-env 每回合收到天气持续的消息（-weather … [upkeep]）都把开始回合重置为当前回合；碎石等延长道具也因此失效 | 局面构造 | 已修复 | `test_l3a_built_weather_turns` | `timers.py` 记录天气 / 场地开始后经过的回合末（upkeep）数，`engine_state.py` 剩余 = 长度（5，延长道具 8）− 已过；对手的延长道具从不暴露，按信念样本 |
| L3b | 开局特性铺的场地，构造的剩余回合数少 1（第 1 回合还没过回合末就扣了一回合） | 局面构造 | 已修复 | `test_l3b_built_terrain_turns` | 同上（按回合末计数，开局铺的场地不再少 1） |
| L4 | 局面字符串里多出 NONE 持续状态：Python 绑定把持续状态写成 `SALTCURE:`（每个名字后带冒号），解析时多出的空字符串变成 NONE（第 0 位）。真实局面只要有持续状态就带 NONE（gen 8 抽样 2 万个局面中 3,587 个方面），搜索树里持续状态结束后 NONE 还留着；网络输入的第 0 位因此有含义漂移。不是游戏机制问题，影响较小 | 序列化（我们的工具链） | 已修复 | `test_l4_volatile_roundtrip` | `state.rs` 解析持续状态时跳过空字符串；`features.rs` 持续状态第 0 位定义为"有任何持续状态"（网络训练时它就是这个含义）：真实局面的网络输入逐位不变（第 8 代 36,771 个局面的全局 / 实体特征与旧缓存一致），只有搜索树里持续状态结束后的第 0 位不再残留 |
| L5 | 回复类招式回合的 HP 不一致：差分脚本的 HP 容差按净变化算造成的误判（Roost + Earthquake 双引擎一致，引擎也正确模拟了 Roost 失去飞行属性） | 方法假象 | 已确认，脚本已修正 | `test_control_hp_salt_cure_infestation_roost_earthquake` | 差分脚本 |
| L6 | 在场宝可梦不一致（6.3%）：回合中有倒下（1,511 例，包括刚换上来就被击倒）、U-turn 类（158）、拖人（3），引擎都停在下一个决策点，和下一回合开始比较不对；另有逃脱背包等 11 例属 D17 已知近似 | 方法假象 | 已确认，脚本已修正 | `test_control_faint_stops_at_the_forced_switch` | 差分脚本 |
| L7 | 拖人招式（Dragon Tail、Circle Throw）跳过目标的被接触效果：静电、凸凸头盔都不触发（普通接触招两者都正确） | 引擎 | 已修复 | `test_l7_static_on_dragon_tail`、`test_l7_rocky_helmet_on_dragon_tail` | `generate_instructions.rs` `run_move`：拖人招式先结算追加效果（静电、凸凸头盔等挂在使用者招式上的被接触效果），再在每个结算分支上拖人 |
| L8 | 数据表比对：引擎的招式表、属性相克表、换形态种族值，以及我们读的 poke-env 图鉴 / 招式，和 Showdown 的 Gen 9 `Dex` 逐项比较 | 数据 | 已做，测试化 | `tests/test_engine_data.py`（5 个） | 相克表 324 项、换形态种族值 6 个、poke-env 的种族值 / 属性 / 体重 / 特性和招式全部一致。招式表 697 个里起初 44 个不同：真问题修了（L8a–L8c，以及 Swagger 命中 85、Take Down 反伤 1/4、Air Cutter / Blizzard / Fury Cutter 的 wind / slicing 标志、Aromatic Mist / Coaching 在单打不再给自己加能力、Dragon Cheer 威力 0）；其余 33 个是表示方式不同（Showdown 写在代码里、引擎写在数据里或相反）、有意的近似（Triple Axel、Fickle Beam）、单打无效的双打招式、引擎没有闪避能力值、OU 罕见且引擎未实现（Uproar、Revival Blessing），逐个写在测试的已知差异表里并注明原因 |
| L8a | Armor Cannon 没有自降防御 / 特防 | 引擎（数据） | 已修复 | `test_l8a_armor_cannon_self_drops` | `choices.rs`：使用者防御、特防 −1 |
| L8b | Fickle Beam：Showdown 是 30% 威力翻倍、无能力变化，引擎写成了 50% 使用者特攻 +1 | 引擎（数据） | 已修复 | `test_l8b_fickle_beam_no_boost`；`test_l8b_fickle_beam_double_power_branch` | `choices.rs`：去掉特攻 +1；第二步（L30 一起）：威力 80，`generate_instructions.rs` 分支 70% × 1 / 30% × 2（原来取期望 104） |
| L8c | Glaive Rush：引擎有这个持续状态（受到伤害翻倍）却没有招式给使用者挂上，所以从不生效 | 引擎（数据、代码） | 已修复 | `test_l8c_glaive_rush_drawback` | `choices.rs`：使用者挂 `glaiverush`；`generate_instructions.rs`：使用者下一次行动开始时移除（Showdown 的 onBeforeMove，优先于其它判定） |
| L9 | 黑色污泥在非毒系身上：Showdown 每回合扣 1/8（满血也扣），引擎只扣 1/16、满血不扣（非毒系分支是从回血分支照抄的 `min(maxhp/16, maxhp − hp)`） | 引擎 | 已修复 | `test_l9_black_sludge_non_poison` | `items.rs`：非毒系扣 `min(max(maxhp/8, 1), hp)` |
| L10 | 剩下的 HP 不一致里待查的几簇。已拆出并确认：L11（Spikes 层数）、L12（回合末顺序）、L13（束缚持续时间）、L14（Seismic Toss 等固定伤害对 Protect / 替身 / 未命中）、L15（Future Sight）、L16（Pain Split）。仍是线索（双引擎简单场景两边一致，差分例子的成因未查明）：Knock Off 要害伤害约为非要害 3 倍的例子（Dondozo，疑似防御等级 + 要害忽略正向等级）；Neutralizing Gas 下 Iron Hands 的 Supercell Slam 伤害（同时上场、先激活 Quark Drive 再换上两种顺序都一致）；Alolan Ninetales 的 Pyro Ball 伤害（疑似极光幕）；Pickpocket（被接触时偷走对方道具）引擎没有实现；Poison Puppeteer（Pecharunt 让目标中毒时同时混乱）引擎没有实现。已知近似（不算问题）：2–5 段招式固定 3 段（Water Shuriken 实际 2 段）。另见：引擎的 Shed Skin 每回合必定治愈（Showdown 30%），未测 | 待拆分 | 线索 | | |
| L11 | Spikes 2 / 3 层的换入伤害：引擎按"层数 / 8"（2 层 1/4、3 层 3/8），Showdown 是 1/8、1/6、1/4（差分里"后备 +1/12"一簇：1/4 − 1/6） | 引擎 | 已修复 | `test_l11_spikes_two_layers` | `generate_instructions.rs`：最大 HP × [0, 3, 4, 6][层数] / 24（至少 1） |
| L12 | 回合末顺序：引擎先结算异常状态伤害（灼伤 / 中毒），再结算剩饭 / 黑色污泥、寄生种子；Showdown 的顺序是天气类特性（1）、湿润之躯 / 蜕皮（5.3）、剩饭 / 黑色污泥（5.4）、寄生种子（8）、中毒（9）、灼伤（10）。满血被灼伤时，Showdown 剩饭无效、扣 1/16，引擎扣完又回满；血量低时还影响是否倒下 | 引擎 | 已修复 | `test_l12_heal_before_status_damage`（剩饭、寄生种子） | `generate_instructions.rs` 回合末：异常状态伤害之前先结算天气类特性（Solar Power、Ice Body、Rain Dish、Dry Skin）、湿润之躯 / 蜕皮、剩饭 / 黑色污泥、寄生种子；`items.rs` / `abilities.rs` 的回合末函数加阶段参数，其余（宝珠、加速、剧毒治疗等）仍在之后。水流环 / 扎根引擎没有实现，不在此列 |
| L12b | 毒疗（Poison Heal）在剧毒宝珠生效的那个回合就回血：引擎在回合末的最后先让宝珠中毒、马上又按特性回 1/8；Showdown 的毒疗是在中毒伤害那一步（9）把伤害换成回复，宝珠（28）在它之后，所以那一回合不回 | 引擎 | 已修复 | `test_l12b_poison_heal_after_the_orb` | `generate_instructions.rs` 异常状态伤害那一步：毒疗的宝可梦中毒 / 剧毒时回 1/8（对方化学变化气体时不回，回复封锁时不回）；`abilities.rs` 回合末的毒疗分支去掉。引擎自带测试 `test_poisonheal_while_toxiced_still_increases_toxic_count` 的指令顺序随之改了（先回复、后加剧毒计数，结果相同） |
| L13 | 部分束缚不会结束：引擎里束缚一直持续到换人（每回合扣 1/8）；Showdown 持续 4 或 5 个回合末（持续时间 5 或 6，到期的那个回合末解除、不扣血） | 引擎、局面构造 | 已修复 | `test_l13_partial_trap_ends`（引擎每回合；两个视角构造的计数） | 引擎：`VolatileStatusDurations` 加 `partiallytrapped`（经过的回合末数；状态字符串第 10 个字段，旧字符串照常解析），第 5 个回合末解除（取 Showdown 的较短者），双方换人时清零；Python 绑定同步。局面构造：`timers.py` 从束缚开始（-activate）数回合末，`build_state` 如实填入（最多 4：到 4 时引擎在下一个回合末解除，对 Showdown 的 5 正确，对 6 也正确，因为 6 要到过了 5 个还在才看得出）。第一版上限是 3，推理错了（"过了 4 个还在说明是 6"，其实 5 也是），新对局的差分抓到（束缚多扣一回合），测试原来照错误推理写成 `min(计数, 3)`，已改为逐回合等于实际计数。网络输入不变（计数不进特征） |
| L14 | 固定伤害招式（Seismic Toss、Night Shade、Super Fang、Nature's Madness、Ruination、Endeavor）在命中判定、守住、替身之前就扣了目标的 HP：未命中也扣、守住也扣、替身挡不住（直接扣本体）。Blissey / Chansey 的 Seismic Toss、Ting-Lu 的 Ruination 在 OU 都很常见。另外减半招式引擎按 ceil(hp/2)，Showdown 按 floor(hp/2)（至少 1） | 引擎 | 已修复 | `test_l14_fixed_damage_checks`（守住、替身各 2 例，未命中 1 例） | `choice_effects.rs` 新增 `fixed_damage`，把这些招式移出 `choice_special_effect`；`generate_instructions.rs` 把固定伤害当作普通攻击招式的伤害（经过命中、守住、替身、结实 / 挺住），不做伤害浮动和要害分支；接触效果（凸凸头盔等）因此也照常触发 |
| L15 | Future Sight 的伤害不计目标的特防等级（冥想）、进化奇石 / 突击背心、极光幕，属性一致加成看的是当前在场的宝可梦而不是使用者（Chansey 带进化奇石：Showdown 144，引擎 199） | 引擎 | 已修复 | `test_l15_future_sight_defender`；对照 `test_control_future_sight` | `damage_calc.rs` `calculate_futuresight_damage`：目标特防按能力等级、进化奇石 / 突击背心 ÷ 1.5、光墙或极光幕减半、属性一致按使用者。harness 补上 Showdown 的预知未来（挂在目标位置上的 slot condition，新版用 endingTurn）到引擎（使用方的 `future_sight`）的映射 |
| L16a | Pain Split 后使用者的 HP 可以超过最大 HP（Weezing 334/334 与 Ting-Lu 平分后成了 424/334） | 引擎 | 已修复 | `test_l16a_pain_split_max_hp` | `choice_effects.rs`：双方各自不超过自己的最大 HP（Showdown 的 sethp） |
| L16b | `choice_special_effect` 里的招式不受守住影响：Pain Split、Trick / Switcheroo、Counter / Mirror Coat / Metal Burst / Comeuppance、Final Gambit 都能穿透 Protect | 引擎 | 已修复 | `test_l16b_special_moves_blocked_by_protect`（Pain Split、Trick） | `choice_effects.rs` `choice_special_effect`：带 protect 标志的招式遇到守住类状态（Protect、Spiky Shield、Baneful Bunker、Burning Bulwark、Silk Trap）直接返回 |
| L17 | 结实 / 气势披带 / 挺住：引擎只要满血就把伤害减 1（不管能否击倒），而且气势披带撑住后不消耗（搜索里可以反复撑住）；Showdown 只在这一下会击倒时留 1 HP，气势披带随即用掉 | 引擎 | 已修复 | `test_l17_focus_sash_used_up` | `generate_instructions.rs` `generate_instructions_from_damage`：伤害 ≥ 当前 HP 时才留 1 HP；挺住、结实优先（Showdown 的优先度 −10、−30），都不适用时由气势披带撑住并消耗（−40）。引擎自带测试 `test_cannot_ohko_versus_sash` 写死了旧行为，按 Showdown 改了期望 |
| L18 | Dauntless Shield（Zamazenta）：第 9 世代每场只在第一次登场时防御 +1，引擎每次换上都 +1（差分里防御等级不一致的大部分） | 引擎、局面构造 | 已修复 | `test_l18_dauntless_shield_once`（引擎；两个视角的构造） | 引擎没有"每场一次"的标记：用过的记为 `base_ability` = none（`ability` 不变，网络输入不变）。引擎：Dauntless Shield 只在 `base_ability` 也是它时 +1；换下时不把这种情况的特性改回 none。局面构造：`timers.py` 记下发动过的（协议里的 `-ability` Dauntless Shield 加 boost 标记），`build_state` 置 `base_ability` = none。局限：搜索树里第一次换上后不会再标记（没有可撤销的指令改 `base_ability`），树里同一只多次换上很少见 |
| L19 | 回复封锁（Psychic Noise，2 回合）在引擎里只挡回复类招式；Showdown 挡所有回复（`onTryHeal`）：剩饭、黑色污泥、天气类特性、毒疗、青草场地、祈愿、寄生种子的回复方。吸取类招式在第 9 世代直接被禁用（不能选），不在此列 | 引擎 | 已修复 | `test_l19_heal_block_stops_all_healing`（剩饭、黑色污泥） | `items.rs`、`abilities.rs`、`generate_instructions.rs` 回合末各回复点加回复封锁判断。harness 同时补上回复封锁 / 地狱突刺 / 电磁飘浮的剩余回合（Showdown 倒数）到引擎计数（已过回合）的换算 |
| L20 | Good as Gold 挡不住 Trick（引擎照样交换道具）：Good as Gold 只清掉招式的数据效果，`choice_special_effect` 里按招式名执行的交换道具不受影响（同 L16b 的 Protect）。第一版修复用数据里的目标判断，把戏法空间也挡了（引擎的场地招式目标也写成 Opponent），随机差分的回归检查发现（trick_room 类别出现），已改为只挡 Trick / Switcheroo / Pain Split，加对照测试 | 引擎 | 已修复 | `test_l20_good_as_gold_blocks_trick`；`test_control_trick_room_against_good_as_gold` | `choice_effects.rs` `choice_special_effect`：对方 Good as Gold（且攻击方没有破格类特性、化学变化气体）时 Trick / Switcheroo / Pain Split 无效 |
| L21 | Mirror Armor 没有实现：对手造成的能力下降（招式、追加效果、Intimidate）应反弹给对手 | 引擎 | 已修复 | `test_l21_mirror_armor_reflects`（Lunge）、`test_l21_mirror_armor_reflects_intimidate` | `generate_instructions.rs` `get_instructions_from_boosts`：目标有 Mirror Armor（攻击方无破格类）时下降改作用于攻击方，以持有者为来源；`abilities.rs` Intimidate 同样反弹 |
| L22 | 锁招（Outrage 等）没打中时不解除：Showdown 只在命中时续期，未命中 / 免疫 / 无效果 / 被守住的那一回合锁定立即解除（不混乱）；引擎一直锁满 3 回合 | 引擎 | 已修复 | `test_l22_outrage_lock_ends_on_immune_target` | `generate_instructions.rs`：`lock_end_instructions`，用在未命中分支（含属性免疫）、无效果、被守住（招式的锁招效果被 `remove_effects_for_protect` 清掉）三处。harness 补上锁招剩余回合（Showdown 的 trueDuration）到引擎计数的换算 |
| L23 | 锁招自然结束后，引擎让其它招式一直保持禁用（锁招开始时禁用，结束时没恢复；挑衅结束时是恢复的） | 引擎 | 已修复 | `test_l23_moves_usable_after_a_lock_ends`（和 Showdown 下一回合请求里的可用招式比较） | 锁招到期时恢复其它招式（持有讲究系道具时不恢复）。注意：差分的比较原来不看招式可用性，这类问题看不到 |
| L24 | 引擎不认识的道具（读成 UNKNOWNITEM，没有任何效果）：Showdown Gen 9 有对战效果的道具里缺 42 个，外加 6 个延长道具（Showdown 里没有事件函数，由天气 / 场地 / 墙的 durationCallback 读取）。用户要求从 Showdown 源码补齐 | 引擎 | 已修复（全部 48 个） | `test_engine_knows_every_item_with_an_effect`（数据测试：Showdown Gen 9 有效果的道具全部为引擎所知）；`test_l24_duration_items_set_on_switch_in`（5 个）、`test_l24_light_clay`（2 个） | 道具追加在枚举末尾（`repr` 改为 u16：u8 放不下；指令 6 → 8 字节，引擎自带的大小测试按此改；搜索速度 u8 0.138 秒 / u16 0.137–0.141 秒，无差别），`alpha_search` 的 `item_id` 把追加的一律映射为 UNKNOWNITEM（网络输入不变）。延长道具：`extend_field_durations` 在登场特性、招式特殊效果、受击后特性之后把持有者对应道具的 5 回合天气 / 场地改为 8；Light Clay 在墙的持续回合里处理。第一批效果道具（测试 `test_l24_pinch_berries` 等 16 个）：低血量回复果 Figy / Wiki / Mago / Aguav / Iapapa（1/4 以下回 1/3，性格降低对应能力时混乱；回复封锁下不吃）、Oran（1/2 以下回 10），照 Sitrus Berry 在行动前和回合末检查；受击触发 Kee / Maranga（物理 / 特殊，防御 / 特防 +1；Knock Off、Thief / Covet、Bug Bite / Pluck 先拿走时不触发：第一版没处理，随机差分子集检查发现 b191-t5，加测试 `test_l24_kee_berry_knocked_off_first`）、Snowball / Luminous Moss（冰 / 水，攻击 / 特防 +1）、Jaboca / Rowap（物理 / 特殊，攻击方 −1/8）、Enigma（效果绝佳时回 1/4），照 Absorb Bulb 用追加效果；Sticky Barb（回合末 −1/8，接触时转给没有道具的攻击方）；Room Service（戏法空间下登场或开启时速度 −1）；第二批：Scope Lens / Razor Claw（L28）、Ganlon / Apicot / Lansat Berry；加能力的低血量果（含原有的 Liechi / Petaya / Salac）也在回合末检查（原来只在持有者下一次行动前，被后手打到 1/4 时那一回合对不上，`test_l24_pinch_boost_berries` 含 Salac）；第三批：Bright Powder / Zoom Lens（命中 ×3686/4096、后手 ×4915/4096；只对打向目标、会落空的招式：必中招式表 `Choices::always_hits` 由数据测试和 Showdown 比对）、6 个 Power 系道具（速度减半）、Float Stone（体重减半）、Big Root（吸取 / 寄生种子回复 ×5324/4096）、King's Rock / Razor Fang（10% 畏缩：Showdown 的追加效果不走 randomChance，概率用 `enginecheck.showdown_rate` 在 1,000 个种子上统计，种子要散列，相邻小整数种子开头的随机数相关，第一次测出 28.75%）、Utility Umbrella（持有者受到的攻击不受晴雨修正）；第四批：Quick Claw（同优先度档内 1/5 先手：出手顺序原来只有同速时的 50/50 分支，推广成按概率 p 分支）、Focus Band（会被击倒的分支拆出 1/10 以 1 HP 撑住）、Starf Berry（受击降到 1/4 时按还没 +6 的能力均分成分支，各 +2：在 `run_move` 之后处理，Showdown 的 onUpdate 时机）；第五批：Leppa Berry（PP 到 0 时回 10，不超过最大 PP：引擎不记最大 PP，最大 PP 低于 10 的招式表 `Choices::max_pp_below_10` 由数据测试和 Showdown 比对）、Micle Berry（回合末 1/4 时吃，新持续状态 MICLEBERRY，下一招命中 ×4915/4096，2 个回合末后失效；Showdown 走的是 Accuracy 事件，命中探针补上了）、Metronome（同一招连续使用的计数，伤害 ×4915/4096 起到 2 倍；新持续状态 METRONOME 和计数字段；需要上一次使用的招式，带 Metronome 时打开引擎的这个开关）、Mirror Herb（复制对手提升自身的能力，用掉）。状态字符串的持续回合计数为 12 个字段（旧字符串照常解析）；新的持续状态追加在第 104、105 位，网络只读第 1–103 位；最后：Ability Shield（破格类不能无视、化学变化气体不能抑制持有者的特性；改特性的招式 Skill Swap 等引擎本来就没实现，见下一步）、Destiny Knot（持有者着迷时对手也着迷）。harness 补上性格（之前都按 Serious），体重改传物种体重（原来传 Showdown 的 getWeight()，已经算过 Float Stone，掩盖了引擎没处理）。构造问题（待做）：我们的 `build_state` 没有传性格 |
| L25 | 场地招式（Grassy / Electric / Psychic / Misty Terrain）在引擎里没有实现（只有天气招式实现了）；数据测试没有比较招式的 weather / terrain 字段，所以没发现 | 引擎 | 线索 | | |
| L26 | Prankster 的变化招式对恶属性目标无效，引擎把作用于自己 / 己方场地的招式也算进去（Reflect 对 Ting-Lu 失败） | 引擎 | 已修复 | `test_l26_prankster_self_move_against_dark`；对照 `test_control_prankster_move_at_a_dark_type_fails` | `abilities.rs`：只对目标是对方、且不是钉子 / 天气 / 场地 / 全场类的招式生效 |
| L27 | Brick Break、Psychic Fangs 不破墙；Raging Bull 在伤害之后才破墙（伤害已被减半，上游用有墙时威力翻倍来补偿）。L26 修好后，随机差分的子集检查出现一个新增（b117-t11 Brick Break 对 Light Screen：修复前 Light Screen 被错判失败，碰巧和打碎后的结果一致），由此发现 | 引擎 | 已修复 | `test_l27_screen_breakers`（3 个） | `generate_instructions.rs` `screen_break_instructions`：伤害按去掉墙计算（仅为计算临时去掉），命中分支里真正移除，未命中保留；去掉 Raging Bull 原来伤害后的破墙和威力翻倍 |
| L28 | 要害只看招式（普通 1/24、高要害 1/8）：聚气（Focus Energy，+2 级）、超幸运（Super Luck，+1）都没算进去；Scope Lens / Razor Claw（+1）引擎不认识 | 引擎 | 已修复 | `test_crit_chance`（6 个；Showdown 的要害等级由 `enginecheck.crit_stages` 调它自己的 ModifyCritRatio 事件取得：一场对战只看得到一次随机结果，看不出概率） | `generate_instructions.rs`：按 Showdown 的要害等级算概率（1/24、1/8、1/2、必定）：高要害招式 +1、Scope Lens / Razor Claw +1、超幸运 +1、聚气 +2 |
| L29 | 同速（以及现在的 Quick Claw）分支里，两种出手顺序共用同一对可变的招式：第一种顺序计算时道具加到招式上的追加效果（Rocky Helmet 的反伤等）在第二种顺序里又加了一次。Quick Claw 让这个分支常见后，随机差分的子集检查出现新增（b48-t19：Rocky Helmet 算了两次），由此发现 | 引擎 | 已修复 | `test_l29_speed_tie_branches_do_not_share_choices`（两个种子，两种出手顺序都和 Showdown 一致） | `generate_instructions.rs`：第二种顺序用招式的副本 |
| L30 | 2–5 段的连续招式固定按 3 段（Loaded Dice 4 段）；所有段一起暴击或都不暴击；击倒只按总伤害的平均。L24 的道具补齐后，随机差分里两个新增（b117-t40、b219-t17）由此发现 | 引擎 | 已修复 | `test_l30_multi_hit_counts`（Showdown 1,000 个种子的段数分布）；`test_l30_multi_hit_crits_per_hit`；`test_l30_multi_hit_knockout_rolls` | `generate_instructions.rs`：段数分支 2 / 3 / 4 / 5 = 35 / 35 / 15 / 15%（Loaded Dice 4 / 5 各半；Skill Link 5）；每段独立暴击：k 段暴击按二项概率分支，每段伤害取平均；总伤害接近对方 HP 时，用每段 16 个掷骰的卷积算击倒概率（L34 起用精确的掷骰） |
| L31 | 太晶化后丢了原属性的本系加成：harness 和我们的 `build_state` 都把太晶属性当成 `types` 传给引擎（poke-env 的 `type_1` / `type_2` 太晶后返回太晶属性），而引擎的语义是 `types` 保持原属性（太晶属性另在 `tera_type`，防御只看它，本系加成两者都算；引擎自己搜索里太晶化时也不改 `types`）。实战里太晶后的宝可梦用原属性招式时，搜索低估 1/3 的伤害。伤害公式差分（下面 1c）里 3,765 个比例 0.667 的情形由此发现 | 局面构造 + harness | 已修复 | `test_l31_terastallized_keeps_original_stab`（2 个）；`test_terastallized_keeps_original_types`（`build_state`，双方各一） | `engine_state.py` `_types`：用 poke-env 的 `base_types`（不含太晶）；harness 用 Showdown 的 `getTypes(false, true)`（`pre_tera_types`）。网络输入里太晶宝可梦的 type 1 / type 2 由此变成原属性，和搜索树内一致 |
| L32 | 被 Iron Ball / Smack Down 落地的飞行系仍然免疫地面招式（Levitate、Air Balloon、Magnet Rise 同理）。Iron Ball 在 Showdown 里还让持有者对地面招式的所有属性都按一倍算（它的 onEffectiveness 对每个属性返回 0；Smack Down 只去掉飞行的免疫） | 引擎 | 已修复 | `test_l32_grounded_flying_hit_by_ground`（3 个，含对照） | `damage_calc.rs` `grounded_by_effect`、`get_defending_types`；Levitate / Air Balloon / Magnet Rise 遇到落地时不再免疫 |
| L33 | 伤害公式差分找到的三处：灼伤时 Facade 仍被减半（Showdown 第 6 代起不减；Guts 原来用"威力 ×2"抵消减半）；减伤果在出招前就被吃掉，Knock Off 的 1.5 倍因此丢了（Showdown 的 onBasePower 时果子还在）；Rising Voltage 写成对任何目标 1.5 倍（Showdown：电气场地下对着地目标 2 倍） | 引擎 | 已修复 | `test_l33_facade_ignores_burn`；`test_l33_knock_off_boost_with_a_resist_berry`；`test_l33_rising_voltage`（着地 / 飞行各一） | `damage_calc.rs` `burn_modifier`：Guts、Facade 不减半（去掉 Guts 的 ×2）；`items.rs` 减伤果遇到 Knock Off 补回 1.5 倍；`choice_effects.rs` Rising Voltage |
| L34 | 伤害的取整与 Showdown 不同：引擎把所有修正（道具、特性、本系、天气、属性、灼伤……）乘成一个浮点数作用在伤害上，掷骰取最终伤害的 85–100%；Showdown 分步取整（威力和攻防各自乘修正链后取整；基础伤害 → 天气 → 暴击 → 掷骰 → 本系 → 属性（每级 ×2 / 取半）→ 灼伤 → 最终修正链，每步 4096 进制的 modify）。结果约 24% 的伤害差 1 点以上；击倒附近的掷骰概率因此偏（`test_l30_multi_hit_knockout_rolls`：0.856 对 0.78；b32-t47：Showdown 最低一档 50 没打死 51 HP，引擎最低档算成 51）。同时找到：Freeze-Dry 对水系 ×4 加在威力上（应是属性等级 +2）；Expert Belt / Tinted Lens / Filter 等判断"效果绝佳"时没算 Freeze-Dry；Guts 加成了特殊招式；Grassy Terrain 只减半 Earthquake（Bulldoze、Magnitude 也减半，且只对着地目标）；Eruption 类的分数威力没有向下取整（Showdown 的 runEvent 只修正整数）；Supreme Overlord 是 1 + 0.1n、无上限（Showdown 4096 进制、最多 5）；Adaptability 作用在威力上 | 引擎 | 已修复 | `test_l34_damage_is_a_showdown_roll`（16 个情形：Showdown 实际造成的伤害必须是引擎 16 档掷骰之一，`alpha_search.damage_rolls`）；`test_l34_max_damage_matches_showdown`（同样 16 个：最高档逐点等于 Showdown 自己的 getDamage） | `damage_calc.rs`：`DamageRecipe` 按 Showdown 的顺序和取整算 16 档；`Choice` 新增 `attack_modifier` / `defense_modifier` / `damage_modifier`，道具和特性的修正按 Showdown 的阶段放（Choice Band / Huge Power / Guts 等进攻击，AV / Eviolite / Fur Coat 等进防御，Life Orb 5324/4096、Expert Belt、Multiscale、Filter、Tinted Lens、减伤果等进最终修正），倍率换成 4096 进制（1.3 → 5325/4096 等）；击倒分支和连续招式的卷积用精确的 16 档（`damage_rolls`）；Adaptability 移到本系加成 |
| L35 | Future Sight 命中时：用使用者的特攻强化（在场时；引擎用未强化的数值），使用者的道具 / 特性也作用（Life Orb 1.3 倍并扣 1/10 反伤，Choice Specs 等）。L31 给了使用者本系加成后，随机差分里两个新增（b69-t7、b100-t50）由此发现：原来没有本系和没有强化两个错误恰好抵消。另外：Neutralizing Gas 在场时，对方的 Protosynthesis / Quark Drive 加成无效（处理函数检查 ignoringAbility()），Neutralizing Gas 一方出招时也无视目标的特性（Vessel of Ruin 等），Guts 也被压制（灼伤减半照常；b83-t5 由此发现） | 引擎 | 已修复 | `test_l35_future_sight_user_boosts`；`test_l35_future_sight_user_life_orb`；`test_l35_neutralizing_gas_suppresses_quark_drive`；`test_l35_neutralizing_gas_attacker_suppresses_target_ability` | `damage_calc.rs` `calculate_futuresight_damage`（使用者在场时用强化后的特攻，招式带修正）；`generate_instructions.rs` 回合末：使用者在场时套用它的特性 / 道具修正，目标的修正总是套用（原来 AV / Eviolite 的特判去掉），Life Orb 反伤；`damage_calc.rs` `volatile_status_modifiers`、`burn_modifier`；`abilities.rs` `ability_modify_attack_against` |
| L36 | Imposter / Transform 没有实现：Ditto 进场不变身，仍按 Ditto 自己的属性和能力值挨打。L31 修好后随机差分里的新增 b0-t28 由此暴露（Clefable 太晶 Poison 后的 Moonblast 打变身成 Clefable 的 Ditto：原来没有本系加成，碰巧接近 Showdown） | 引擎 + harness + 局面构造 | 已修复 | `test_l36_imposter_transforms_on_switch_in`；`test_l36_transformed_moves_then_switch_back`；`test_transform.py`（`build_state` 加上 transform / typechange） | 引擎：新的可回溯指令 `ChangeMove`（招式槽的招式；Instruction 仍是 8 字节）、新持续状态 TRANSFORM（第 106 位，网络不读）；`transform_into`（Showdown 的 transformInto：目标的属性（不是太晶属性）、HP 以外的能力值、特性、能力变化、招式（各 5 PP）；目标有替身 / 已变身时失败），Imposter 换上时、Transform 招式使用时调用；换下时招式回到 Transform（引擎不保存原招式：Imposter Ditto 的招式），属性、特性照常复原，能力值不重算（引擎没有大多数物种的种族值；Imposter 再换上时会重新复制，在替补席上不用）。harness：Showdown 的 `transformed` 映射成 transform，物种用原来的。实战的 `build_state` 本来就构造变身后的宝可梦，补上了 transform / typechange 两个状态（网络输入里变身宝可梦的 typechange 位因此为 1，和搜索树内一致） |
| L37 | Speed Boost 在换上场的那一回合末也加速（Showdown 要求 activeTurns > 0：本回合换上的为 0；倒下后补上的，到下一回合末已是 1） | 引擎 | 已修复 | `test_l37_speed_boost_not_on_the_switch_in_turn`（含对照） | `abilities.rs`：本回合的指令里有这一方的换人就不加速（倒下后的替补是单独的决策，不在同一个列表里） |
| L38 | Rest 在满 HP 时也能用（Showdown 的 onTry 失败）；Purifying Salt、Sweet Veil、Insomnia / Vital Spirit / Comatose、着地时的 Misty Terrain、晴天的 Leaf Guard 也挡不住；Electric Terrain 不看是否着地 | 引擎 | 已修复 | `test_l38_rest_fails_at_full_hp`（含对照）；`test_l38_rest_fails_with_purifying_salt` | `choice_effects.rs` Rest：按 Showdown 的 onTry 和 setStatus |
| L39 | 双方同时换人时，引擎总是先换 side one；Showdown 按换下去那只的速度（Trick Room 反过来），所以 Intimidate 打到的对象会错（b117-t16 等 3 个） | 引擎 | 已修复 | `test_l39_double_switch_order`（含对照） | `generate_instructions.rs`：两边都换人时按 `get_effective_speed` 排序（同速仍先 side one，近似） |
| L40 | Poison Puppeteer 没有实现：Pecharunt 的招式让对方中毒时对方同时混乱（Showdown 的 onAnyAfterSetStatus） | 引擎 | 已修复 | `test_l40_poison_puppeteer`（Malignant Chain、Toxic） | `generate_instructions.rs` `get_instructions_from_status_effects`：中毒 / 剧毒成功（不是被木子果挡掉）后加混乱；Own Tempo、着地时的 Misty Terrain、已混乱不加 |
| L41 | 第 9 代 Protean / Libero：引擎在出招前（`ability_before_move`）就变属性，冰冻 / 睡眠 / 麻痹不能动、Sucker Punch 失败时也变；且只有不含招式属性时才变（Showdown：当前属性不恰好是招式属性就变，草 / 恶的 Meowscarada 用 Knock Off 变成纯恶）。另外 harness：太晶后的 typechange 不比较（太晶后没有作用；Showdown 一侧本来就不算太晶） | 引擎 + harness | 已修复 | `test_l41_protean`（2 个）；`test_l41_protean_not_when_frozen` | `generate_instructions.rs` `protean_type_change`：在招式真正开始（`Acted`）之后；`enginecheck` `view_engine` |
| L42 | 必定暴击的招式（Flower Trick 等）的击倒：非暴击的最高档打不死时，引擎直接取暴击的平均伤害，不分击倒分支（L41 修好后的新增 b146-t23：Showdown 剩 5 HP，引擎判击倒） | 引擎 | 已修复 | `test_l42_guaranteed_crit_knockout_rolls`（目标 HP 取暴击 16 档的中间，击倒概率等于不小于 HP 的档数 / 16） | `generate_instructions.rs` `finish_move`：必定暴击时用暴击的最高档和 16 档 |
| L43 | harness：替身的 HP 没有传给引擎（引擎里是 0，任何攻击都打破替身） | harness | 已修复 | `test_l43_substitute_hp_mapped`（Seismic Toss 100 打 101 HP 的替身） | `showdown_state.js` 导出替身 HP，`engine_state` 设 `substitute_health` |
| L44 | Red Card 在攻击方没有可换的宝可梦时也被消耗（Showdown 的 canSwitch：不触发）；攻击只打在替身上时 Air Balloon 不破（Showdown 的 onAfterSubDamage 会破） | 引擎 | 已修复 | `test_l44_red_card_needs_a_replacement`；`test_l44_air_balloon_pops_on_a_substitute_hit` | `generate_instructions.rs` |
| L45 | 减伤果被变化招式（地面系的 Spikes、恶系的 Nasty Plot）和固定伤害（Ruination 等）触发（Showdown 在 onSourceModifyDamage：只对造成伤害、不是固定伤害的招式）；Lum Berry 不治混乱（Showdown 的 onUpdate：异常状态或混乱都吃） | 引擎 | 已修复 | `test_l45_lum_berry_cures_confusion`；`test_l45_resist_berry_only_on_a_damaging_hit`（2 个） | `items.rs` `damage_reduction_berry`、Chilan、`lum_berry` |
| L46 | Synchronize 没有实现：对方的招式或特性（Static 等，引擎里是作用于使用者的追加效果）造成的中毒 / 灼伤 / 麻痹传回对方 | 引擎 | 已修复 | `test_l46_synchronize`（麻痹、剧毒、灼伤） | `generate_instructions.rs` `get_instructions_from_status_effects` |
| L47 | harness：Rest 的睡眠被当成普通睡眠（Showdown 的 statusState 只留来源宝可梦、不留来源效果，导出的来源一直是空的），引擎因此按普通睡眠的随机醒来算 | harness | 已修复 | `test_l47_rest_sleep_mapped`（3 个：醒来与否的概率为 1） | `showdown_state.js`：来源是自己 = Rest |
| L48 | harness：等待中的 Healing Wish / Lunar Dance（第 9 代等到需要治疗的宝可梦换上；Showdown 的槽位条件，引擎的场地条件）没有传给引擎。实战的 `build_state` 也没有（poke-env 不记录这个等待状态）：线索 | harness | 已修复（harness）/ 线索（build_state） | `test_l48_healing_wish_waits_mapped` | `engine_state` 的场地条件 |
| L49 | Belly Drum 在攻击 +6 时也扣一半 HP（Showdown 失败） | 引擎 | 已修复 | `test_l49_belly_drum_fails_at_plus_six` | `choice_effects.rs` |
| L50 | 反噬招式（High Jump Kick、Supercell Slam 等）打到免疫的目标时不反噬（Showdown 的 onMoveFail：未命中、免疫、守住都反噬）；连续招式每一段接触都该吃 Rocky Helmet / Rough Skin / Iron Barbs，引擎每个招式只算一次 | 引擎 | 已修复 | `test_l50_crash_into_an_immune_target`；`test_l50_rocky_helmet_per_hit` | `generate_instructions.rs`：`move_has_no_effect` 的路径加反噬；`run_move` 补上第二段起的接触伤害（Magic Guard / Protective Pads 除外） |
| L51 | 非暴击打不死、暴击可能打死时，暴击按平均伤害算：平均到了 HP 就一律击倒（b110-t32：Showdown 暴击 285 没打死 296 HP） | 引擎 | 已修复 | `test_l51_crit_knockout_rolls`（暴击 16 档中间的 HP：击倒概率 = 暴击率 × 不小于 HP 的档数 / 16；修复后才跑通，临时去掉修复确认会失败） | `generate_instructions.rs` `finish_move`：暴击按精确的 16 档拆成击倒和不击倒两支 |
| L52 | Lunar Dance 在引擎里没有任何效果（Showdown：使用者倒下，下一个需要的宝可梦换上时回满） | 引擎 | 已修复 | `test_l52_lunar_dance`（当回合倒下；等待后治疗） | `choices.rs`：同 Healing Wish（回复 PP 的部分没有做）；harness 的 `lunardance` 槽位映射成 healing_wish；数据测试列入已知差异 |
| L53 | Weakness Policy 被固定伤害（Ruination 等）触发（Showdown：`!move.damage && !move.damageCallback`） | 引擎 | 已修复 | `test_l53_weakness_policy_not_by_fixed_damage` | `items.rs` |
| L54 | 混乱自伤：引擎取最高档且灼伤减半；Showdown 的 getConfusionDamage 要掷骰、不因灼伤减半 | 引擎 | 已修复 | `test_l54_confusion_self_hit_burned`（单独比较自伤这一项） | `generate_instructions.rs`：16 档的平均、不减半；poke-engine 自带的 3 个测试按新数值改了期望（35 → 31） |
| L55 | Sheer Force 加成的招式仍吃 Life Orb 的反伤（Showdown 对这些招式不触发 AfterMoveSecondarySelf） | 引擎 | 已修复 | `test_l55_sheer_force_life_orb`（含对照：没有追加效果的 Earthquake 照样反伤） | `items.rs` |
| L56 | Doom Desire 命中时按 Future Sight（超能 120）算：钢系 140，打恶系也有伤害；而且使用当回合就造成伤害（引擎没把它当延迟招式） | 引擎 | 已修复 | `test_l56_doom_desire`；`test_l56_doom_desire_hits_later` | `generate_instructions.rs` 回合末：使用者会 Doom Desire 而不会 Future Sight 时用 Doom Desire 的招式数据（引擎只记录使用者的位置） |
| L57 | 引擎不记录被消耗的道具（Showdown 的 `lastItem`），Harvest（Exeggutor / Tropius 的 Sitrus）无法实现（用户 2026-10-16 要求记下，同日完成）。随机差分里 b137-t20 / t21 / t23 / t26 四处由此而来 | 引擎 + harness | 已修复（Harvest；Recycle / Belch 仍未实现） | `test_l57_harvest`（两个种子：和 Showdown 一致，吃掉后放回的概率 0.5） | `Pokemon.last_item`（状态字符串末尾多一个字段，旧字符串照常解析；夹具 `engine_state_6v6.txt` 按新格式重写）；新指令 `ChangeLastItem`；吃掉 / 用掉道具的地方（`items.rs` 的果子、种子、宝石等，Lum / Chesto 挡状态、Leppa、Custap；Starf 没有）记下它，被 Knock Off 等打掉不记；回合末之后判断 Harvest（晴天必定，否则 50%：复制出一个分支），放回后立即再走一次这一方的道具结算（Showdown 立刻吃）。harness 映射 Showdown 的 `lastItem`。实战的 `build_state` 还没有（poke-env 不记录）：线索 |
| L58 | Triple Axel 每一段各自判定命中（90%）、未命中就停，威力 20 / 40 / 60，引擎是判定一次、3 段各 40；Population Bomb 10 段各自判定（Loaded Dice：判定一次、4–10 段；Skill Link：10 段），引擎固定 6 段 | 引擎 | 已修复 | `test_l58_triple_axel_hits`（含 Skill Link）；`test_l58_population_bomb_hits`（含 Loaded Dice、Skill Link；Showdown 800 个种子的段数分布） | `generate_instructions.rs` 段数分支：Triple Axel k 段按 20, 40, …, 20k 的平均威力；Population Bomb 分成 1–3 / 4–6 / 7–9 / 10 四档，各取档内平均段数（每个段数还要按暴击数分支，不分档分支太多） |
| L59 | 被 Protect 挡住的 Rapid Spin / Mortal Spin 照样清钉子，Defog 照样降闪避、清场地（这些效果按招式 ID 触发，不看被 `remove_effects_for_protect` 清掉的字段；Defog 的降闪避是 L1 加的，当时没考虑 Protect） | 引擎 | 已修复 | `test_l59_protected_move_does_nothing`（Rapid Spin、Defog） | `choices.rs`：`Choice.protected`（被守住时置位）；`choice_effects.rs` `choice_hazard_clear` 遇到它直接返回 |
| L60 | Ogerpon 用面具对应的属性太晶化时，变成 -Tera 形态，特性随之变为 Embody Aspect，对应能力 +1（Wellspring 特防、Hearthflame 攻击、Cornerstone 防御、Teal 速度）；引擎只置太晶标记，特性不变 | 引擎 | 已修复 | `test_l60_embody_aspect_on_tera`（Wellspring、Teal） | `generate_instructions.rs` `embody_aspect_on_tera`：太晶时改特性并 +1 |
| L61 | 锁定招式（Outrage 等）在最后一回合被 Protect / 免疫 / 未命中中断时，Showdown 照样疲劳混乱（lockedmove 的 onEnd 按 trueDuration 判断，不管怎么结束）；L22 一律不混乱 | 引擎 | 已修复 | `test_l61_lock_stopped_on_its_last_turn_confuses`（最后一回合 / 非最后一回合） | `generate_instructions.rs` `lock_end_instructions`：计数为 2（引擎的锁定都是 3 回合）时混乱 |
| L62 | Unburden 在引擎里从不触发（它的状态只在算速度时读，从来没被加上）。实战的 `build_state` 也不会设它（Showdown 不公布）：线索 | 引擎 | 已修复（引擎）/ 线索（build_state） | `test_l62_unburden`（吃掉 Sitrus、被 Knock Off） | `generate_instructions.rs` `unburden_check`：回合末（开头和结尾各一次）按本回合的指令，在场的宝可梦换上后失去了道具就加上 |
| L63 | 声音招式（Parting Shot 等）和 Infiltrator 的招式降低替身后面目标的能力（Showdown 的 bypasssub）；引擎的替身一律挡住 | 引擎 | 已修复 | `test_l63_parting_shot_through_a_substitute` | `generate_instructions.rs` `run_move`：施加这类招式的能力变化时临时去掉状态里的替身（不产生指令） |
| L64 | Red Card 先拖人、追加效果没了（Moonblast 的降特攻）；Showdown 先结算追加效果（onAfterMoveSecondary）。另外被拖走的攻击方不吃 Life Orb 反伤（onAfterMoveSecondarySelf 检查 forceSwitchFlag）：改顺序后由新增 b44-t21 发现 | 引擎 | 已修复 | `test_l64_red_card_after_secondaries`；`test_l64_red_card_stops_life_orb_recoil` | `generate_instructions.rs` `run_move`：同 L7 的拖人招式，先追加效果再在每个分支上拖人，去掉 Life Orb 的反伤 |
| L65 | Covert Cloak 挡掉所有追加效果（Showdown 只挡对持有者的，保留对使用者的：Rapid Spin 的速度 +1；持有者自己的 Static 等接触特性在引擎里也是对使用者的追加效果，也被误挡） | 引擎 | 已修复 | `test_l65_covert_cloak_keeps_self_secondaries` | `generate_instructions.rs`：只去掉对对手的 |
| L66 | Take Heart 在引擎里没有效果（Showdown：特攻、特防 +1，治愈异常状态） | 引擎 | 已修复 | `test_l66_take_heart` | `choices.rs` 加能力变化；`choice_effects.rs` 同 Refresh 治愈；数据测试列入已知差异 |
| L67 | Sacred Sword / Darkest Lariat / Chip Away 无视目标的防御强化（Showdown 的 ignoreDefensive），引擎照算。另外 harness：Endeavor 的目标最后等于使用者的 HP，而使用者的 HP 取决于目标本回合打出的伤害掷骰，目标的 HP 容差要算上它打出的伤害（同 L7 的吸取招式） | 引擎 + harness | 已修复 | `test_l67_sacred_sword_ignores_defense_boosts`（最高档等于 Showdown） | `damage_calc.rs`；`check_engine_random.py` |
| L68 | Healing Wish / Lunar Dance 在没有可换上的宝可梦时失败（Showdown 的 canSwitch，使用者不倒下）；引擎照样倒下 | 引擎 | 已修复 | `test_l68_healing_wish_needs_a_replacement` | `choice_effects.rs` `modify_choice` |
| L69 | Magic Bounce 弹回的 Whirlwind / Roar 应该拖走原使用者一方，引擎拖的还是对方；弹回到 Encore 使用者身上的 Encore 应失败（不能 Encore 一个 Encore），引擎照样施加 | 引擎 | 已修复 | `test_l69_magic_bounce_whirlwind`；`test_l69_encore_bounced_onto_an_encore_user_fails` | `generate_instructions.rs`：拖人按 `choice.target`；`move_has_no_effect` 的 Encore 看它落到的一方，且上一招是 Encore 时失败 |
| L70 | Disable 在引擎里只加一个状态标记，不封招式也没有持续回合；Cursed Body 没有实现（打中持有者的招式 30% 被封）。验证集里最大的簇（26 处） | 引擎 + harness | 已修复 | `test_l70_disable`（4 个：持续回合对齐 Showdown）；`test_l70_cursed_body`（命中后 30%） | `generate_instructions.rs`：施加 Disable 时封住目标上一次用的招式（没有上一招或已被封时失败），本回合稍后选了它也不能用（`cannot_use_move`），回合末计数，4 回合（目标已出过招：5）后解除；`VolatileStatusDurations.disable` 编码「招式槽 × 8 + 计数 + 1」（状态字符串多一个字段，旧字符串照常解析，夹具按新格式重写）；Cursed Body 作为对使用者施加 DISABLE 的 30% 追加效果；场上有 Disable / Cursed Body 时跟踪上一招；harness 导出被封的招式并按编码映射 |
| L71 | Beat Up 在引擎里威力为 0（Showdown：使用者和每只没倒下、没异常的队友各打一段，威力 5 + 该物种攻击种族值 / 10）；引擎的种族值表只有会变形态的物种 | 引擎 | 已修复 | `test_l71_beat_up` | `genx/species_base_stats.rs`：从 Showdown 图鉴生成全部 Gen 9 物种的种族值（`base_stats()` 的兜底；数据测试 `test_engine_base_stats_match_showdown` 核对）；`choice_effects.rs` 威力取打手的平均、段数分支取打手数 |
| L72 | Good as Gold 挡掉了不以对方宝可梦为目标的变化招式：引擎的 MoveTarget 没有「场地」，天气、场地、Trick Room、Haze、Perish Song 等都标成了对手；非鬼系的 Curse 以自己为目标（Showdown 的 onModifyMove） | 引擎 | 已修复 | `test_l72_curse_through_good_as_gold`；数据测试 `test_moves_not_aimed_at_the_foe_match_showdown`（23 个招式，和 Showdown 的 target 比较） | `choices.rs` `Choices::not_aimed_at_foe`；`abilities.rs` Good as Gold；alpha_search 新增 `move_targets` / `not_aimed_at_foe_moves` |
| L73 | Stockpile 只加一个状态（没有层数，也不加防御 / 特防），Spit Up / Swallow 没有效果 | 引擎 + harness | 已修复 | `test_l73_stockpile`（4 个：一层、3 层时失败、Spit Up、Swallow） | `VolatileStatusDurations.stockpile`（层数；状态字符串又多一个字段）；`choice_effects.rs`：每层防御 / 特防 +1，最多 3 层；Spit Up 100 × 层数、Swallow 25 / 50 / 100%，用掉层数和加成；换下清零 |
| L74 | Electromorphosis 没有实现（受到攻击伤害后获得 Charge） | 引擎 | 已修复 | `test_l74_electromorphosis` | `abilities.rs`：对持有者施加 CHARGE 的追加效果 |
| L75 | Sitrus 和半血 / 1/4 血的果子要等到持有者出招（Sitrus 那时按 1/4 判）或回合末才吃（Showdown 的 onUpdate：被打到阈值就吃），中间的回复让果子留了下来；Knock Off / Thief 先拿走果子（它们的 onAfterHit 在果子的 onUpdate 之前） | 引擎 | 已修复 | `test_l75_sitrus_at_once`；`test_l75_knock_off_takes_the_berry_before_it_is_eaten`（断言概率：会心一击的分支也能对上 HP） | `items.rs` `berry_on_damage`（每次伤害后立即判断）；`generate_instructions.rs`：Knock Off / Thief 能拿走道具时跳过；`item_before_move` 的 Sitrus 阈值改为 1/2 |
| L76 | Sticky Web 的降速在引擎里当作自己造成的；Showdown 的来源是对方的在场宝可梦：Clear Body 等挡住，Defiant / Competitive 会触发 | 引擎 | 已修复 | `test_l76_sticky_web_from_the_foe`（Clear Body、Light Metal 两个参数） | `generate_instructions.rs`：降速的来源取对方一侧 |
| L77 | Slow Start 在 Showdown 里是特性状态里的计数（不是 volatile），harness 没有带进引擎的状态：已经在场的 Regigigas 不减半攻击 / 速度；对战里的状态构造也没有。验证集 offmeta 里最大的簇（29 处） | harness + 状态构造 | 已修复 | `test_l77_slow_start_counts_its_turns`（6 回合逐回合比较）；`test_l77_slow_start_from_the_protocol`（`timers.py` 的计数对 Showdown 的计数，首发和中途换上） | `showdown_state.js` 把计数导出成 slowstart volatile，`engine_state` 带上剩余回合；`timers.py`：-start 起 5，从它在场的第一个回合开始每个回合末减 1（Showdown 不算换上的那个回合），-end 清掉；`engine_state.py` 带进状态 |
| L78 | Pickpocket 在引擎里和 Magician 一样算在攻击方身上（持有者打人时拿走对方道具）；Showdown 是被接触招式打中、自己没有道具时拿走攻击方的道具（onAfterMoveSecondary：在 Knock Off 拿走它自己的之后） | 引擎 | 已修复 | `test_l78_pickpocket_after_knock_off`；`test_l78_pickpocket_holder_takes_nothing_when_it_hits` | `abilities.rs` 去掉攻击方的 Pickpocket；`generate_instructions.rs` `run_move`：在 Sticky Barb 之后，被接触且非换人招式打中、活着、没有道具时拿走（攻击方的道具可被拿走、没有 Neutralizing Gas） |
| L79 | Paradox 宝可梦的 Booster Energy 拿不走（Showdown 的 onTakeItem），Knock Off 既不打掉它也没有 1.5 倍；引擎两样都做了（太阳下换上、Booster 留着时） | 引擎 | 已修复 | `test_l79_booster_energy_stays_on_a_paradox`；数据测试 `test_paradox_species_match_showdown`（16 个物种，和 Showdown 的 tags 比较） | `genx/state.rs` `PARADOX`、`item_is_permanent`；alpha_search 新增 `paradox_species` |
| L80 | Neutralizing Gas 不压制目标挡异常的特性（Purifying Salt、Water Veil、Limber 等；Comatose / Shields Down 压不住）和 Synchronize（引擎把灼伤传回了 Weezing）；目标的 Gas 也压制使用者的 Corrosion | 引擎 | 已修复 | `test_l80_neutralizing_gas_lets_a_burn_through_purifying_salt`；`test_l80_neutralizing_gas_stops_synchronize` | `generate_instructions.rs` `immune_to_status`：按被压制后的特性判断（Ability Shield 例外）；Synchronize 同样检查 |
| L81 | Rest 的睡眠立即触发 Lum / Chesto（Showdown 的 onUpdate），本回合稍后的异常能上；引擎等到持有者下次出招前或回合末才吃，中间仍是睡着（免疫） | 引擎 | 已修复 | `test_l81_rest_berry_at_once`（Lum、Chesto 两个参数） | `items.rs` `rest_berry`；`choice_effects.rs` Rest 成功后调用 |
| L82 | Magic Guard 挡不住束缚、Salt Cure、鬼系 Curse 的回合末伤害（Showdown 都是 this.damage，Magic Guard 的 onDamage 挡掉） | 引擎 | 已修复 | `test_l82_magic_guard_stops_residual_damage`（3 个参数，各比较 2 回合） | `generate_instructions.rs` 回合末的 volatile 伤害 |
| L83 | Magic Guard 挡不住 Sticky Barb 和（非毒系持有者的）Black Sludge 的回合末伤害；验证集 forum 里最大的簇（Magic Guard + Sticky Barb 的 Clefable） | 引擎 | 已修复 | `test_l83_magic_guard_stops_item_damage`（2 个参数） | `items.rs` `item_end_of_turn` |
| L84 | Grassy Terrain 的回复在天气伤害之前（满血时没有回复，再吃沙暴）；Showdown 的回合末顺序：天气 1、Future Sight 3、Wish 4、Grassy Terrain 5.2、场地结束 27 | 引擎 | 已修复 | `test_l84_grassy_terrain_heals_after_sand`；`test_l84_grassy_terrain_heals_on_its_last_turn`（最后一回合照样回复，回归保护） | `generate_instructions.rs` `add_end_of_turn_instructions`：场地一段（回复、计数、结束）挪到 Wish 之后、特性 / 道具之前 |
| L85 | Salt Cure、Psychic Noise 的 volatile 在 Showdown 是 100% 的追加效果，Covert Cloak / Shield Dust 能挡；引擎当作招式本身的 volatile | 引擎 | 已修复 | `test_l85_covert_cloak_stops_the_volatile`（2 个参数） | `choices.rs`：两招改为 100% 追加效果（数据测试照样通过） |
| L86 | Smack Down 只对浮空的目标加状态（Showdown 的 onStart：飞行系、Levitate、Magnet Rise；Iron Ball / Ingrain 时不加）；引擎对谁都加 | 引擎 | 已修复 | `test_l86_smack_down_only_grounds_the_airborne`（着地 / 飞行两个参数） | `genx/state.rs` `volatile_status_can_be_applied` |
| L87 | harness 没有把 Perish Song 的计数（Showdown 的 perishsong，剩余回合）带进引擎的 perish<n>：引擎的状态里没有，第二次 Perish Song 又成功 | harness | 已修复 | `test_l87_perish_song_counts_down`（3 回合） | `showdown_state.js`：perishsong 导出成 perish<剩余回合> |
| L88 | 会心一击只去掉对攻击方不利的能力变化（Showdown 的 getDamage：攻击方的负、防御方的正），而且是招式实际用的那项（Body Press：使用者的防御；Foul Play：目标的攻击），Unaware / Sacred Sword 时本来就不算；引擎的会心对这两招用了不加成的数值（+2 时会心比普通还低），也没管 Unaware | 引擎 | 已修复 | `test_l88_body_press_crit_keeps_the_defense_boost`；`test_l88_foul_play_crit_keeps_the_targets_attack_boost`（Scope Lens + Focus Energy 必定会心） | `damage_calc.rs` `get_attacking_and_defending_stats`：会心的两项按实际用的能力和是否计入加成统一算。forum 的 b128-t16 因此新增（`--force`）：Showdown 的掷骰让 Great Tusk 剩 3 HP，引擎的平均伤害 + Salt Cure 打倒它（已知的近似：回合末残伤的击倒按平均伤害）；之前恰好被错误的会心分支（伤害偏低）对上 |
| L89 | Encore 持续 3 回合（目标本回合已出过招：4），在回合末计数（Showdown 的 duration）；引擎数的是被 Encore 的招式次数，在第三次出招开始时就去掉，所以那一回合里的第二次 Encore 成功了（Showdown 失败）；目标已出过招时也少算一回合 | 引擎 + 状态构造 | 已修复 | `test_l89_encore_counts_turns`（Prankster 先手 / 慢速后手两个参数，6 回合逐回合比较，并核对 `timers.py` 的计数 = 3 − Showdown 的剩余回合） | `generate_instructions.rs`：施加时计数从 0（目标已出招：−1）开始，回合末 +1，到 3 结束；去掉出招前的计数；`timers.py`：同样按回合末计数（`acted`：本回合已出招 / 不能动） |
| L90 | Taunt 同 L89（3 回合，目标本回合已出招且不是刚换上：4）；另外被挑衅的攻击打进 Water Absorb / Volt Absorb 等时引擎已经把它改成变化招式，挑衅的检查就挡住了它（Showdown 照样出招） | 引擎 + 状态构造 | 已修复 | `test_l90_taunt_counts_turns`（两个参数，同上）；`test_l90_taunted_attack_into_an_absorbing_ability` | 同 L89；`cannot_use_move` 按招式本来的分类判断；原来挑衅结束时的 `re_enable_disabled_moves` 去掉（它会解开讲究锁定的招式） |
| L91 | Defog（Showdown 的 onHit）只清目标一侧的屏障、Safeguard、Mist（钉子两侧都清）；Good as Gold 挡它，除非使用者是 Mold Breaker / Neutralizing Gas；Mirror Armor 把降闪避弹回去（Mold Breaker / Neutralizing Gas 时不弹）。引擎把使用者自己的屏障也清了，对 Mold Breaker 也让 Good as Gold 挡住，Mirror Armor 看不到这次下降 | 引擎 | 已修复 | `test_l91_defog_keeps_the_users_screens`；`test_l91_defog_evasion_drop`（2 个参数）；`test_l91_neutralizing_gas_defog_through_mirror_armor` | `choice_effects.rs` `choice_hazard_clear`；poke-engine 自带测试 `test_defog_clears_terrain_and_side_conditions` 原来写死了清两侧的 Reflect，按 Showdown 改了期望 |
| L92 | 打在替身上、掷骰跨过替身 HP 的一击，引擎用平均伤害（要么都打破、要么都打不破）；现在按精确的 16 个掷骰拆成打破 / 没打破两支，和击倒一样（L34 / L51） | 引擎 | 已修复 | `test_l92_substitute_break_by_the_rolls`（掷骰 70–82 对 81 HP 的替身：打破的总概率 = 23/24 × 2/16 + 1/24） | `generate_instructions.rs` `finish_move`：拆分的门槛 `target_hp` 在打到替身时取替身的 HP（声音招式、Infiltrator 例外） |
| L93 | Strength Sap 打替身会失败（Showdown：没有 bypasssub）；引擎照样按对方攻击回复 | 引擎 | 已修复 | `test_l93_strength_sap_against_a_substitute` | `choice_effects.rs` |
| L94 | Magic Guard 挡不住 Rough Skin / Iron Barbs 和 Rocky Helmet 的反伤；吸收类特性（Earth Eater、Water / Volt Absorb、Dry Skin）把打向其一侧的招式（Spikes 等，Showdown 的 onTryHit 只对打中它的招式）也吸收了 | 引擎 | 已修复 | `test_l94_magic_guard_against_rough_skin_and_rocky_helmet`；`test_l94_spikes_into_earth_eater` | `abilities.rs`（Rough Skin；四个吸收特性按 `not_aimed_at_foe` 放过）；`items.rs` Rocky Helmet |
| L95 | Rapid Spin / Mortal Spin 还解除使用者的寄生种子和束缚，打到替身也一样（Showdown 的 onAfterHit / onAfterSubDamage）；引擎只清钉子 | 引擎 | 已修复 | `test_l95_rapid_spin_frees_its_user`（寄生种子、束缚、隔着替身三个参数） | `choice_effects.rs` `choice_hazard_clear` |
| L96 | 着地的毒系换上时吸收毒菱，带 Heavy-Duty Boots 也一样（Showdown 先看属性再看鞋）；引擎对穿鞋的跳过 | 引擎 | 已修复 | `test_l96_poison_type_with_boots_absorbs_toxic_spikes` | `generate_instructions.rs` 换上时的钉子 |
| L97 | Leech Seed 不是粉末招式（Overcoat / Safety Goggles 不挡）；引擎为了草系免疫给它加了 powder 标记，而它的 volatile 检查本来就排除草系 | 引擎 | 已修复 | `test_l97_leech_seed_through_overcoat`（Overcoat、Safety Goggles 两个参数）；数据测试的已知差异去掉这一条 | `choices.rs` |
| L98 | Disguise 只在受到伤害的一击时破（Showdown 的 onDamage）：免疫的招式（Extreme Speed 打 Mimikyu）、打在替身上都不破；引擎对任何攻击都破并扣 1/8 | 引擎 | 已修复 | `test_l98_disguise_needs_a_damaging_hit`（免疫、替身两个参数） | `abilities.rs` `ability_before_move`（Scrappy / Mind's Eye 照样破） |
| L99 | Soak 在引擎里没有效果（Showdown：目标变成纯水系；纯水系、已太晶化、隔着替身、被 Water Absorb 等吸收时失败） | 引擎 | 已修复 | `test_l99_soak`（2 回合）；`test_l99_soak_into_water_absorb` | `choice_effects.rs` `choice_special_effect`（Good as Gold 也挡） |
| L100 | Dry Skin 在晴天回合末掉 1/8（Showdown 的 onWeather），大雨也回复；引擎只在下雨时回复 | 引擎 | 已修复 | `test_l100_dry_skin_in_the_sun` | `abilities.rs` `ability_end_of_turn` |
| L101 | 不能动的宝可梦（睡着、冰冻、麻痹不能动、混乱打自己）没有用出招式（Showdown 只在用出招式时设 lastMove）：引擎在检查前就把它的上一招设成了所选招式，于是本回合之后的 Encore 成功了（刚换上、还没出过招时 Showdown 失败）。另外 Encore 对不能重复的招式（Showdown 的 failencore：Sleep Talk、Encore、Copycat、Metronome、Mimic、Sketch、Struggle、Transform）或 PP 为 0 的招式失败 | 引擎 | 已修复 | `test_l101_asleep_has_not_used_its_move`；`test_l101_encore_fails_on_sleep_talk` | `generate_instructions.rs`：`undo_last_used_move` 在各个不能动的分支里撤销这一步（换上 → None，同畏缩的处理）；`move_has_no_effect` 的 Encore |
| L102 | Unnerve / As One 让对方吃不了树果（Showdown 的 onFoeTryEatItem；持有者有 Neutralizing Gas 时不算）；引擎没有 Unnerve | 引擎 | 已修复 | `test_l102_unnerve_stops_berries`（Sitrus、Lum 两个参数） | `items.rs` `unnerved`，在各个吃树果的地方检查：`item_before_move`、`berry_on_damage`、`item_end_of_turn`、`item_modify_attack_against`（防御方的树果）、施加异常时的 Lum / Chesto、Rest 后、Custap、Leppa、Starf |
| L103 | Throat Spray 只在声音招式真正用出后触发（Showdown 的 onAfterMoveSecondarySelf）：HP 不到 1/3 失败的 Clangorous Soul 不触发 | 引擎 | 已修复 | `test_l103_throat_spray_not_on_a_failed_clangorous_soul` | `items.rs` |
| L104 | 宝石只强化攻击招式（Showdown 的 onSourceTryPrimaryHit：变化招式不算）；引擎在 Court Change 上用掉了 Normal Gem | 引擎 | 已修复 | `test_l104_gem_not_on_a_status_move` | `items.rs` `power_up_gem` |
| L105 | 场地招式（Electric / Grassy / Misty / Psychic Terrain）在引擎里没有效果（只有 Surge 特性能开场地）；Showdown：5 回合，Terrain Extender 8 回合 | 引擎 | 已修复 | `test_l105_terrain_moves`（4 个参数，各比较 2 回合） | `choice_effects.rs`，和天气招式一样（`extend_field_durations` 处理 Terrain Extender） |
| L106 | Skill Swap 在引擎里没有效果（Showdown：交换双方特性并触发新特性的登场效果；带 failskillswap 的特性、Ability Shield 时失败；Good as Gold 挡） | 引擎 | 已修复 | `test_l106_skill_swap`（Dauntless Shield、Intimidate、Disguise 失败三个参数）；数据测试 `test_skill_swap_failures_match_showdown`（29 个特性） | `choice_effects.rs` `choice_special_effect`；`abilities.rs` `FAIL_SKILL_SWAP`；Dauntless Shield 的“用过”判断改为 base ability 不是 none（Skill Swap 换来的也触发）；alpha_search 新增 `fail_skill_swap_abilities` |
| L107 | Mean Look / Block / Spider Web 在引擎里没有效果（Showdown：目标被困住，直到使用者离场；幽灵系免疫、替身挡）。另外 harness 现在带上 Showdown 的 trapped volatile | 引擎 + harness | 已修复 | `test_l107_mean_look_traps`（引擎的选项里没有换人）；`test_l107_trap_ends_when_the_trapper_leaves` | `genx/state.rs` 新的 TRAPPED volatile（追加在末尾，网络读的位不变）、`trapped()`；使用者换下时解除；对战的状态构造：`timers.py` 从 `-activate trapped` 起、任一方换下止（`test_l107_trapped_from_the_protocol`） |
| L108 | Spirit Shackle / Anchor Shot 困住目标（100% 追加效果：Covert Cloak / Shield Dust / Sheer Force 时没有），Jaw Lock 困住双方；Prankster 的变化招式对恶系无效也挡住代码实现的效果（Mean Look、Trick、Skill Swap 等，同 Good as Gold）。L107 让 harness 比较 trapped 后暴露出来；offmeta b49-t18（Metronome 随机出了困人招式，引擎无法建模）因此新增，`--force` | 引擎 | 已修复 | `test_l108_trapping_attacks`（3 个参数）；`test_l108_prankster_mean_look_into_a_dark_type` | `choice_effects.rs` `choice_after_damage_hit`、`choice_special_effect` |
| L109 | 掷骰跨过“撑过本回合末”的一击（目标可预期的回合末损失：异常、Salt Cure、寄生种子、束缚、Curse、沙暴、Sticky Barb / Black Sludge，减去 Leftovers 等的回复），引擎用平均伤害，回合末的击倒要么都发生要么都不发生；现在活下来的掷骰在那里再拆成两支（同 L34 的击倒拆分）。估计不准时只是拆得粗一些，每一支本身仍是真实的掷骰和真实的回合末 | 引擎 | 已修复 | `test_l109_end_of_turn_knockout_by_the_rolls`（Salt Cure 下的 Blissey：引擎回合末倒下的总概率 = 按 16 个掷骰和会心算出的 0.281） | `generate_instructions.rs` `expected_residual`、`finish_move`（只在近击倒时多算一次掷骰，多一个分支） |
| L110 | 决策点回合暴露的两处：束缚 / Mean Look 的使用者倒下后效果结束（Showdown：来源不在场），引擎回合末仍造成束缚伤害；harness：Roost 当回合 Showdown 的 getTypes 去掉飞行（纯飞行变一般），不当作属性变化（引擎的 roost volatile 另行比较） | 引擎 + harness | 已修复 | `test_l110_roost_is_no_type_change`；`test_l110_partial_trap_ends_with_its_fainted_user` | `generate_instructions.rs` 回合末 volatile 一段开头；`enginecheck._changed_types`。wide2 b258-t27 换了最接近的结果（`--force`）：这一击自己带来的中毒 + 回合末掷骰决定的击倒，L109 的估计看不到这一击的追加效果 |
| L111 | Battle Bond 只对 Greninja-Bond 有效、每场一次（Showdown 检查物种和 bondTriggered）；引擎对任何持有者每次击倒都加 | 引擎 + harness + 状态构造 | 已修复 | `test_l111_battle_bond`（Greninja-Bond / Greninja 两个参数） | `abilities.rs`；用过的 base ability 为 none（`showdown_state.js` 的 used_once 加上 bondTriggered；`timers.py` 从 `-activate ability: Battle Bond` 记下） |
| L112 | 换人招式的使用者被自己的招式打倒（Rocky Helmet、Rough Skin、反伤）时不换人（Showdown：没有它的换人请求，回合继续：对方的招式没有目标而失败，然后回合末）；引擎停在换人上，并把对方的招式留给替换上来的宝可梦。另外以对方宝可梦为目标的变化招式在对方倒下后失败（[notarget]；场地 / 一侧的招式、非鬼系 Curse 照样） | 引擎 | 已修复 | `test_l112_pivot_user_fainting`；`test_l112_status_move_without_a_target`（Pain Split / Stealth Rock / Curse） | `generate_instructions.rs` `after_move_finish`、`cannot_use_move` |
| L113 | Knock Off 的使用者被这一击的接触伤害（Rocky Helmet、Rough Skin / Iron Barbs）打倒时什么也拿不走（Showdown 的 onAfterHit 要求使用者还有 HP）；另外这些伤害、Rocky Helmet / Life Orb 等的负回复至少 1（Showdown 的 damage；1 HP 的 Shedinja） | 引擎 | 已修复 | `test_l113_knock_off_user_fainting_to_rocky_helmet` | `choice_effects.rs` Knock Off；`abilities.rs` Rough Skin；`generate_instructions.rs` `get_instructions_from_heal` |
| L114 | 招式中途道具的先后：Sticky Barb 先转给没有道具的接触攻击方，Knock Off 之后什么也拿不到（Showdown：Sticky Barb 的 onHit 在击中时，Knock Off 的 onAfterHit 在后）；Pickpocket 拿走的 Life Orb 不再给原持有者反伤（Showdown 的反伤在招式之后，看那时的道具）；Air Balloon 等一次性道具的“用掉”只去掉它自己，不去掉招式中途换来的道具（引擎的这些效果是招式之后的追加效果） | 引擎 | 已修复 | `test_l114_sticky_barb_before_knock_off`；`test_l114_pickpocket_takes_the_life_orb_before_its_recoil`；`test_l114_balloon_pop_leaves_the_stolen_item` | `choice_effects.rs` Knock Off；`generate_instructions.rs` Pickpocket、`Effect::RemoveItem` |
| L115 | Temper Flare / Stomping Tantrum 在使用者上回合招式失败后威力翻倍（Showdown 的 moveLastTurnResult 为 false：没打中、免疫、失败、麻痹不能动 / 睡着 / 畏缩；被 Protect 挡是 null，不算）；引擎没有 | 引擎 + harness + 状态构造 | 已修复 | `test_l115_power_doubles_after_a_failed_move`；`test_l115_failed_move_from_the_protocol`（`timers.py` 对 Showdown） | `genx/state.rs` 新 volatile LASTMOVEFAILED（只来自给定的状态，回合末清掉：搜索里之后的回合假定招式成功）；`choice_effects.rs`；`showdown_state.js` 导出、不参与比较；`timers.py` 从 `-fail` / `-miss` / 目标 `-immune` / `cant` 判断 |
| L116 | Steel Beam 没打中或被挡时也付出一半 HP（Showdown 的 onMoveFail）；引擎只在命中时 | 引擎 | 已修复 | `test_l116_steel_beam_fails_at_a_cost`（没打中、Protect 两个参数） | `choices.rs` 加 crash 0.5（命中时仍是 heal −0.5） |
| L117 | 多段招式在使用者被目标的接触伤害（Rocky Helmet、Rough Skin）打倒的那一下之后停止（Showdown 的多段循环中断）；引擎打满所有段数 | 引擎 | 已修复 | `test_l117_multi_hit_stops_when_the_user_faints`（Skill Link Tail Slap 第 4 下停） | `generate_instructions.rs` `run_move` 开头按每段的接触伤害限制段数 |
| L118 | Flying Press 的属性相克是格斗加飞行（Showdown 的 onEffectiveness 加上飞行的）；引擎只算格斗（对太晶钢系 2 倍而不是 1 倍） | 引擎 | 已修复 | `test_l118_flying_press_is_flying_too` | `damage_calc.rs` 伤害配方和 `move_type_effectiveness`。伤害计算差分（`check_damage_calc.py`）同时把 Libero / Protean 的攻击方排除：引擎在招式开始时变属性（L41，`generate_instructions`），不在 `calculate_damage` 里，探针却跑了 Showdown 的 PrepareHit；排除后超出 2% 的 32 处（之前 38） |
| L119 | 对方已倒下时，出招方照样经过自己的异常状态（睡眠计数和醒来、解冻：Showdown 的 BeforeMove 在目标检查之前）；引擎先判“没有目标”就停了，到点该醒的 Rest 睡眠没有醒 | 引擎 | 已修复 | `test_l119_sleeper_wakes_without_a_target` | `generate_instructions.rs`：`no_target` 从 `cannot_use_move` 移到睡眠处理之后 |
| L120 | Air Balloon 在任何伤害性的一击时破（Showdown 的 onDamagingHit）：Future Sight、Counter / Mirror Coat / Metal Burst、Final Gambit 的也算；引擎只在招式通常的命中（追加效果）时破。另外 Final Gambit 的伤害没有以目标 HP 为上限 | 引擎 | 已修复 | `test_l120_balloon_pops_on_mirror_coat` | `items.rs` `pop_air_balloon`，在 `choice_effects.rs` 和 Future Sight 的命中处调用 |
| L121 | Parting Shot 一项能力都没降低时失败，使用者留在场上（Showdown 的 onHit：没有降低且不是 Mirror Armor；Clear Body / White Smoke / Full Metal Body / Clear Amulet、Mist、已到 −6、Good as Gold）；引擎照样换人 | 引擎 | 已修复 | `test_l121_parting_shot_into_clear_body` | `choice_effects.rs` `modify_choice`：这些情况去掉 pivot（声音招式，替身不挡） |
| L122 | Disguise 挡下的一击也算命中：Red Card / Eject Button 照样触发（Showdown 的 onAfterMoveSecondary 不要求伤害）；引擎把 0 伤害的一击当作没打中 | 引擎 | 已修复 | `test_l122_red_card_through_disguise` | `generate_instructions.rs` `check_move_hit_or_miss`（这一招破了 Disguise 时不算没打中）、`run_move` 的 Red Card / Eject Button 条件 |
| L123 | Custap Berry 只要持有者在 1/4 HP 及以下（Gluttony：1/2）出招就吃，不管双方优先度（Showdown 的 onFractionalPriority 拿到的是分数优先度 0）；它的 +0.1 只在同优先度时决定先后。引擎只在同优先度、且低于 1/4 时吃 | 引擎 | 已修复 | `test_l123_custap_with_endure`（恰好 1/4 的 Araquanid 用 Endure） | `generate_instructions.rs` 出招顺序 |
| L124 | Neutralizing Gas 离场（持有者换下或倒下）时，Protosynthesis / Quark Drive 持有者的 Booster Energy 立即生效（Showdown：特性重新开始）；引擎一直不用 | 引擎 | 已修复 | `test_l124_booster_energy_after_neutralizing_gas` | `abilities.rs` `booster_energy_after_gas`，在换人和 `after_move_finish`（倒下）时调用（只做这一项；其他特性的重新开始没有做） |
| L125 | Lunar Blessing / Jungle Healing 还治愈使用者的异常状态（Showdown 的 onHit：cureStatus）；引擎只回复 | 引擎 | 已修复 | `test_l125_healing_moves_cure_status`（2 个参数） | `choice_effects.rs`，同 Refresh |
| L126 | 睡着 / 冰冻的出招方先经过自己的状态，再被畏缩 / Taunt 挡住（Showdown 的 BeforeMove 顺序：睡眠 / 冰冻 10、畏缩 8、Taunt 5）：当回合可以醒来；引擎先挡，睡眠计数没走 | 引擎 | 已修复 | `test_l126_wakes_before_the_flinch` | `generate_instructions.rs`：`flinched_or_taunted` 对睡着 / 冰冻的出招方在状态处理之后检查 |
| L127 | Mold Breaker 类使用者的变化招式无视可被破格的挡异常特性（Purifying Salt、Limber、Insomnia 等）；引擎的异常免疫没看 Mold Breaker | 引擎 | 已修复 | `test_l127_mold_breaker_through_purifying_salt` | `generate_instructions.rs` `immune_to_status`（`mold_breaker_ignores` 改为 pub） |
| L128 | Magic Bounce 把降能力的变化招式（Parting Shot、Tickle 等）的能力下降也弹回给使用者；被弹回的 Parting Shot 降了能力时，换下场的是反弹者（还没出招的话，它这回合的招式作废），原使用者留在场上。引擎之前只弹回异常 / 状态 / 场地，能力下降仍打在反弹者身上，原使用者照样换人 | 引擎 | 已修复 | `test_l128_magic_bounce_parting_shot`、`test_l128_magic_bounce_parting_shot_switches_the_reflector` | `abilities.rs` 的 MAGICBOUNCE 分支（boost 目标翻转，pivot 取消）；`generate_instructions.rs` 的 finish_move：反弹者照 Eject Button 的方式换人 |
| L129 | 入场时被钉子打倒的宝可梦不发动入场特性和道具（Intimidate、天气、Booster Energy 等；Showdown 先结算钉子，跳过已倒下的入场者）；引擎照样发动 Intimidate | 引擎 | 已修复 | `test_l129_no_intimidate_after_fainting_to_hazards`（随机差分 main b224-t15 的局面） | `generate_instructions.rs`：入场 hp 为 0 时跳过 `ability_on_switch_in` / `item_on_switch_in` |
| L130 | Clear Body / White Smoke / Full Metal Body / Hyper Cutter / Clear Amulet 只挡对手造成的能力下降（Showdown 的 onTryBoost：boost < 0，Contrary 反转之后）；引擎连对手造成的提升也挡（Weakness Policy、Swagger）。替身仍挡对手的所有能力变化 | 引擎 | 已修复 | `test_l130_clear_body_lets_foe_raises_through`（3 个参数）、对照 `test_l130_swagger_into_substitute` | `generate_instructions.rs` `apply_boost_instruction` |
| L131 | Mirror Herb 复制对手的任何能力提升，不论是谁造成的（持有者自己的 Swagger 也算；Showdown 的 onFoeAfterBoost）；引擎只复制对手自己给自己的提升 | 引擎 | 已修复 | `test_l131_mirror_herb_copies_swagger` | `generate_instructions.rs` `get_instructions_from_boosts` |
| L132 | Truant 的偷懒标记在出招开始时设上（Showdown 的 onBeforeMove，优先级 9：睡眠 / 冰冻之后，畏缩、Taunt、混乱、麻痹之前；招式被免疫、没打中也算），Neutralizing Gas 下不设；硬直回合同时清掉偷懒标记（mustrecharge 的 onBeforeMove）。引擎只在打中后设，硬直回合也不清 | 引擎 | 已修复 | `test_l132_truant_after_any_move`（2 个参数） | `generate_instructions.rs` `start_truant`；`choice_effects.rs` `choice_after_damage_hit` 不再设 |
| L133 | 针对对手的变化招式打在替身上会失败，除非有 bypasssub 标记（Showdown 的 substitute onTryPrimaryHit；Infiltrator 例外）：例如 Memento 的使用者不会倒下。引擎没有统一的判断，Memento 照样让使用者倒下 | 引擎 | 已修复 | `test_l133_memento_into_contrary_substitute`，对照 `test_l133_status_moves_into_substitute`（Pain Split、Trick）；数据测试 `test_bypass_substitute_moves_match_showdown` | `choices.rs` `Choices::bypasses_substitute`；`generate_instructions.rs` `move_has_no_effect` |
| L134 | Magician 在自己的 Knock Off 之后什么也偷不到（Showdown：Knock Off 的 onAfterHit 先拿走道具，Magician 的 onAfterMoveSecondarySelf 在后）；引擎的 Magician 在 Knock Off 之前就偷走了道具 | 引擎 | 已修复 | `test_l134_magician_knock_off` | `abilities.rs` `ability_after_damage_hit` 的 MAGICIAN 分支 |
| L135 | Protect 先于吸收类特性挡住招式（Flash Fire、Well-Baked Body、Water Absorb 等；Showdown 里 Protect 的 onTryHit 先结算）；引擎把招式改成吸收效果时清掉了 protect 标记，于是穿过了 Protect。蓄力招式的蓄力回合照旧不受 Protect 影响 | 引擎 | 已修复 | `test_l135_protect_before_absorbing_abilities`（2 个参数），对照 `test_l135_charge_turn_into_protect` | `choices.rs` `remove_all_effects` 保留 protect 标记；`generate_instructions.rs` 蓄力回合清掉它 |
| L136 | 使用 Substitute 会解除自身的部分束缚（Whirlpool 等；Showdown 的 substitute onStart）；引擎保留束缚，回合末照样扣血 | 引擎 | 已修复 | `test_l136_substitute_ends_partial_trap` | `choice_effects.rs` 的 SUBSTITUTE |
| L137 | Heal Block 期间 Sitrus Berry 不会被吃（Showdown 的 onTryEatItem：不能回复；之前只有半血树果检查了）；Heal Block 在回合末结束后立刻吃（Showdown 在 residual 之后的 Update） | 引擎 | 已修复 | `test_l137_heal_block_stops_sitrus`、`test_l137_sitrus_after_heal_block_ends`（随机差分 wide2 b274-t4） | `items.rs` `sitrus_berry`；`generate_instructions.rs` 回合末 Heal Block 结束后调用 `berry_on_damage` |
| L138 | 太晶化后用 Roost 不会得到 roost 状态（Showdown 的 roost onStart 失败：属性不变）；引擎照样加，换人决策点上能看出差别 | 引擎 | 已修复 | `test_l138_roost_after_terastallizing` | `choice_effects.rs` 的 ROOST |
| L139 | 这一击打破了自己的 Air Balloon 之后，Pickpocket 照样偷走攻击方的道具（Showdown：气球在受到伤害时就破，Pickpocket 在招式结束后）；引擎的 Pickpocket 看到气球还在，没有偷 | 引擎 | 已修复 | `test_l139_pickpocket_after_air_balloon` | `generate_instructions.rs` 的 Pickpocket（气球的 RemoveItem 附加效果不动偷来的道具，L114） |
| L140 | Fling：威力和附加效果取决于使用者的道具（Toxic Orb 剧毒、Flame Orb 灼伤、Light Ball 麻痹、Poison Barb 中毒、King's Rock / Razor Fang 畏缩；Showdown 的 onPrepareHit），没打中、被 Protect 挡住也会消耗道具，伤害保留道具的加成但没有 Life Orb 反伤；没有能投掷的道具或 Klutz 时失败。引擎的 Fling 没有威力，也不消耗道具。树果被对手吃掉、White / Mental Herb 的效果没有实现 | 引擎 | 已修复 | `test_l140_fling`（6 个参数）；数据测试 `test_fling_powers_match_showdown` | `items.rs` `Items::fling_power`；`choice_effects.rs` 的 FLING（modify_choice、choice_special_effect） |
| L141 | Protosynthesis / Quark Drive 随太阳 / Electric Terrain 的每次变化而变（Showdown 的 onWeatherChange / onTerrainChange 和 Booster Energy 的 onUpdate）：招式或入场带来太阳时加上；换成别的天气（Chilly Reception 等）或太阳结束时去掉，Booster Energy 给的除外；去掉后若还持有 Booster Energy，立刻用掉，按当时的最高能力重新选。引擎之前只在入场和太阳 / 场地自然结束时处理，持有的 Booster Energy 沿用旧的能力。新增 FROMBOOSTER 状态（对照工具从 Showdown 的 fromBooster 导出，实战从 `-activate ... [fromitem]` 记录）。seed10k b284-t7 原本就不一致（Red Card 拖出的宝可梦不同），只多了 frombooster 这一项，用 `--force` 接受 | 引擎 | 已修复 | `test_l141_protosynthesis_follows_the_weather`（3 个参数）；`tests/test_timers.py::test_protosynthesis_from_booster_energy` | `abilities.rs` `paradox_update`（替换入场时的处理和 `booster_energy_after_gas`）；`generate_instructions.rs`：出招后、入场后、回合末天气 / 场地结束后调用，删掉 `on_weather_end` / `on_terrain_end`；`state.rs` FROMBOOSTER；`showdown_state.js`、`timers.py`、`engine_state.py` |

## 修复与验证（2026-10-16）

修复：L1、L2a–L2d、L3a/L3b、L4、L7、L9（见问题表"修复"一列；引擎修改都在 `rust/patches/poke-engine-0.0.48`，注释 "alpha-poke patch (2026-10-16, doc/engine-diff.md Lx)"）。验证：

- 双引擎测试：原来的 11 个预期失败全部转为通过（作为回归测试保留），对照测试不变；全部测试 139 个通过；poke-engine 自带测试 228 个（其中 4 个原来写死了旧行为——黑色污泥 1/16、Defog 不降闪避——按 Showdown 改了断言）、alpha_search 23 个通过；`check_tnet` 通过。
- 网络输入：真实局面的特征与修复前逐位相同（第 8 代缓存对比，见 L4）。
- 确定性搜索（`data/selfplay/diag/regress/search.py`，固定种子，夹具局面）：不用网络的 UCB 结果逐位不变（这两个局面里引擎的转移没有变化）；用网络的 PUCT / 批量搜索访问数有小幅变化（首选不变），来自树内局面第 0 位不再残留 NONE。
- 差分统计（第 8 代，3,000 局，42,611 个可比较回合）：一致率 86.1% → **88.3%**；闪避 578 → 31、诅咒 262 → 1、盐腌 69 → 15、HP 3,395 → 3,182、攻击 / 防御 / 速度等级 76 / 218 / 103 → 57 / 199 / 84。天气、场地、部分束缚不变：这批数据的局面是修复前的代码构造的，局面构造类的修复要在新对局上才看得到。
- 还没做：对战 A/B。修复前后的引擎是同一个扩展模块，没法在同一个进程里各跑一边（见下一步）。

## 修复与验证，第二轮（2026-10-16 下午）

修复：L1b、L8a–L8c 及数据表的其余问题、L11、L12、L12b、L13、L14、L15、L16a/b、L17、L18、L19（见问题表）。验证：

- 每条先写双引擎测试复现（strict xfail），修好后转为回归测试；全部测试 168 个通过（双引擎 44 个、数据测试 5 个）；poke-engine 自带测试 229 个通过（新增 1 个束缚到期的测试；3 个原来写死了旧行为——束缚计数、气势披带不消耗、毒疗的指令顺序——按 Showdown 改了期望）；alpha_search 23 个通过。
- 状态字符串的持续回合多了一个字段（束缚），旧字符串照常解析；夹具 `engine_state_6v6.txt` 按新格式重写（只多了一个 `;0`）。
- 确定性搜索回归：6 个结果里 5 个变了，预期之内（夹具局面有剩饭持有者，回合末顺序变了，树里的随机路径随之改变）。这项检查只能证明"不该变的没变"，这一轮靠差分统计验证。
- 差分统计：

| 数据 | 可比回合 | 第一轮后 | 第二轮后 |
|---|---|---|---|
| 第 8 代（旧代码构造的局面，3,000 局） | 43,702 | 88.3% | **90.2%**（HP 6.44% → 5.34%，道具 236 → 125，替身 60 → 49；其它类别不变或只差一两例） |
| gen900（L11–L13 后的代码打的 600 局） | 7,976 | — | 92.6% → **93.4%**（HP 5.19% → 4.35%） |
| gen901（全部修复后的代码打的 600 局） | 7,416 | — | **93.4%**；防御等级 0.59% → 0.07%（L18 的构造），束缚 0.24% → 0.12%（L13 上限的修正） |

新对局上旧数据里的天气（1.70%）、场地（0.36%）、束缚（0.74%）大部分消失：那些是旧代码的局面构造问题（L2c、L3）。被困时选换人的报错：gen901 1 次 / 600 局，gen 8 是 58 次 / 5 万局，比例相当，不是新问题。

剩下的主要不一致（gen901）：HP 4.18%；天气 0.46%：对方的延长道具（湿润岩石等）我们只能按信念猜，差分合并局面时天气剩余回合取的是一方视角，属于信息不对称 / 方法，不是引擎问题；混乱 0.39%：已知近似（2026-10-11 的补丁只用一个继续分支，提前解除只体现在自伤概率上，混乱状态要到第 4 次才真正去掉）；属性变化 0.32%、速度等级 0.26% 待看。

## 修复与验证，第三轮（2026-10-16 晚）

修复：L8b 第二步、L30–L35（见问题表）。验证：

- 每条先写双引擎测试（失败），修好后转为回归测试；全部测试 291 个通过（双引擎 162 个）；poke-engine 自带测试 229 个通过（2 个原来写死了浮点近似的伤害 97，按 Showdown 的取整改成 96：本系 35 → 52，× 2）。
- 随机差分：94.9%（419 个）→ **97.0%**（7,046 个可比回合中 6,832 一致；265 个（编号, 类别），修复 155 个）。新增 1 个 b0-t28：Imposter 没有实现（L36），太晶本系修好后暴露，用 `--force` 接受。中间出现过的新增 b32-t47（击倒掷骰）、b69-t7 / b100-t50（Future Sight，L35）、b83-t5（Neutralizing Gas，L35）都查清修好了。
- 伤害公式差分：逐点一致 76.2% → **99.9%**（上面 1c）。
- 网络输入：太晶宝可梦的 type 1 / type 2 变成原属性（L31），和搜索树内引擎自己太晶化后的局面一致；`Choice` 多了三个修正字段，不进网络输入。
- 速度：不用网络的 UCB 搜索（两个夹具局面各 20,000 次迭代，单线程，各取 3 次最好）0.160 秒 → 0.170 秒，慢约 5%（整数的伤害流水线和更大的 `Choice`；击倒附近才算的精确 16 档几乎不占时间；回合末原来每次都复制一份 Future Sight 招式，改成只在命中那回合）。HEAD 在独立的 worktree / venv 里构建对比。

## 修复与验证，第四轮（2026-10-16 夜）

修复：L37–L42。每条先写双引擎测试（失败；L37 的测试是在修复后才跑通的，临时去掉修复确认它会失败），全部测试 304 个、poke-engine 自带测试 229 个通过。随机差分：97.0%（265）→ **97.8%**（6,889 / 7,046；203 个（编号, 类别）），每一步都是子集；中间出现的新增 b146-t23 查清是 L42 后修好。

## 修复与验证，第五轮（2026-10-16 夜）

修复：L43–L47。随机差分 97.8%（203）→ **98.2%**（6,916 / 7,046；172 个），每一步都是子集，新增 0；全部测试 316 个、poke-engine 自带测试 229 个通过。

L48–L51 之后（同一天）：**98.4%**（6,930 / 7,046；157 个），新增 0；全部测试 321 个、poke-engine 自带测试 229 个通过。L52–L55 之后：**98.5%**（6,938；149 个），新增 0。L56 之后：6,941，145 个，新增 0。L58 之后：6,943，143 个，新增 0。L59、L60 之后：**98.7%**（6,957；125 个），新增 0；全部测试 337 个通过。L61–L63 之后：**98.8%**（6,964；114 个），新增 0；全部测试 342 个通过。L64–L66 之后：**98.9%**（6,972；104 个），新增 0。L67 之后：**99.0%**（6,975；101 个），新增 0。L36 之后：**99.1%**（6,985；88 个），新增 0；全部测试 350 个通过。L57 之后：**99.2%**（6,989；84 个），新增 0。L68、L69 之后：主集合 99.2%（78 个），验证集 98.7% / 97.7% / 98.4% / 98.6%，五个都新增 0。L70 之后：主集合 99.3%（74），验证集 98.8% / 97.9% / 98.6% / 98.7%，新增 0。L71–L74 之后：主集合 68 个，验证集 112 / 149 / 92 / 120 个，新增 0。

单看 HP 的双引擎测试有两个陷阱，这一轮都碰到了：`closest` 只要求有一个分支匹配，不看概率（L47 的确定性醒来要断言概率为 1）；Showdown 的追加效果用 `random(100)`，不受 `force_random` 控制（Strange Steam 的混乱，改用必中的 Confuse Ray）。

## 下一步

0. L57 的后续：Recycle / Belch；实战 `build_state` 的 last_item（自己的宝可梦吃掉的果子可以从协议推出）。
0. 伤害公式剩下的（1c）：Hydro Steam 在晴天、Metronome 道具的加成、Shell Side Arm、Sacred Sword 打有 Light Clay 的一方（引擎 2 倍，未查）、Unaware 的 Body Press / Liquidation 打 Mold Breaker（引擎偏高约 1.5 倍，未查）、Gyro Ball / Electro Ball 的速度没算 Choice Scarf 和麻痹；Imposter / Transform（L36）。随机差分剩下的主要类别：HP 94、异常状态 30、属性变化 29（其中 Ditto 相关 11 个）、替身 18。
1. 还没做的（2026-10-16 晚）：场地招式没有实现（L25）；改特性的招式（Skill Swap、Worry Seed、Simple Beam、Entrainment、Gastro Acid、Role Play、Doodle）没有实现；Pickpocket 没有实现；混乱提前解除只是近似；我们的 `build_state` 没有传性格（低血量回复果的混乱用到）；设置天气的宝可梦道具被打掉后，构造按 5 回合算（L3c）；随机对战 runner 用相邻小整数种子，对局之间相关（改了要重建基线）；有倒下 / 中途换人的回合（2,979 个）还不比较。
2. 剩下的 HP 不一致（gen901 4.18%）按簇继续拆：吸取招式的回复量依赖对另一方伤害的浮动（容差没算进去，方法问题）、属性变化（Libero / Protean 等）、速度等级。
3. 线索（L10）：Pickpocket 未实现（Poison Puppeteer 见 L40）；混乱提前解除的精确分支（要像 Sleep Talk 那样递归分支，会增加搜索分支数）。
4. 差分脚本：合并局面时天气 / 场地剩余回合取设置方的视角；吸取回复的容差。
5. 局面构造类修复会改变网络看到的输入（天气剩余回合、束缚位、Zamazenta 的状态），下一代训练后才完全对齐。用户 2026-10-16 说不需要做修复前后的对战 A/B。
6. 人类对局：回放只有旁观者视角（HP 是百分比、对方配置不完整），做不了精确差分；可以只检查可观察的部分（先后手、是否击倒、HP 百分比是否落在范围内），以后再做。
