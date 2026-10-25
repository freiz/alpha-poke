# 局面构造差分：玩家视角还原的引擎状态 vs Showdown 真实状态

搜索的根状态和训练数据的输入，都是我们从玩家收到的协议（日志 + request）还原出来的引擎状态：poke-env 解析日志，`agents/timers.py` 数日志里的计数，`agents/engine_state.build_state` 拼成 poke-engine 的 `State`。引擎差分（`doc/engine-diff.md`）只验证"从真实状态出发，引擎的推演和 Showdown 一致"，**不验证这一步**：它直接用 Showdown 内部的完整状态构造引擎状态。这份文档追踪还原这一步的一致性。

## 结论（2026-10-24）

- 600 局真实 OU 对局（队伍目录的随机配对），45,219 个决策点：
  - v7.3 数据构建时的代码（`b207e8a`）：**42.6%** 的决策点至少一处不一致，其中 **10.5%** 落在核心字段（HP、异常状态、能力等级、招式与 PP、道具、特性、出场宝可梦、场地）；最大的一项是对方后备宝可梦的 HP（Regenerator 的回复、Zoroark 伪装期间的记账）。
  - 现在：**0.17%**（核心字段 0.02%）。
- 百万级（每轮约 108 万个决策点，OU + 40 组 fixtures + 30 组 big）：首轮 0.23% → 第七轮（新种子）**0.0010%**（11 个决策点），核心字段 **0.0002%**，即一致率 99.999%。
- 回放路径（spectator，训练数据用的那条）：第二轮（新种子）**0.011%**；`enginecheck/replaybuild.py`、`scripts/check_state_build.py --path replay`——按 `train/positions.py` 的方式从观战者日志构造（整局解析的 SpectatorSide），双方隐藏的配置都换成真实配置。首轮百万级 0.66% / 0.65% / 0.43%（OU / fixtures / big），修复 S143–S145 及比较框架后，例子局全部一致（见下）。未覆盖：真实天梯回放的 HP 是百分比（差分里是精确值）。原句：回放路径共用 poke-env、计时器和大部分 `build_state`，它特有的部分（整局已知配置、回放里的 Illusion）当时还未单独对照，见"后续"。
- 因果性（计划 B，10-24）：训练样本的历史 / 暴露标记 / 评分 / 回合 = 截至该决策点的日志在实战路径上算出的，3,000 局真实回放 0 处差异；搜索树内扩展的历史与日志一致，2,000 局 64,098 步里结构字段只剩 0.24%（Illusion、Minior 的颜色、Revival Blessing，见下）；树里不填结果字段（伤害、先手等），补上须经搜索 A/B。途中修了解析器的 C5–C10（训练和实战共用）。
- 统一转换层（计划 C，10-24）：poke-env 的读取收拢到 `agents/pokeview`（自身 / 当前分开，AST 测试强制），动作只有一种表示（`agents/slots`，槽位只由 Rust 算）；往返检查进了 A 的每个决策点。顺带修了抽样出 Assault Vest + 变化招式的不可能配置（P1）和 Greninja-Bond 转不成指令（P2）。
- 开始时定下的值（计划 D，10-24）：按 Showdown 源码逐项核对，需要还原的都按事件发生时记下；剩下的是引擎缺口（束缚道具、连续使用倍率、Laser Focus、Stockpile 在 +6 时、Uproar 的锁定）。
- 测试：`tests/test_state_build.py` 把 60 局随机配置和 60 局 OU 对局（`data/teams/statebuild_catalog_pairs.jsonl`，本地生成、不提交）钉在基线上（`tests/fixtures/state_build_baseline*.json`：不许出现新类别，各类别次数不许变多）；每条修复另有针对性测试（`tests/test_timers.py`、`tests/test_engine_state.py`）。

### 一致率历程

| 日期 | 阶段 | 数据 | 结果 |
|---|---|---|---|
| 10-23 | 第一版检测器，8 局 | 569 个决策点 | 首轮几十处，修到 0 |
| 10-23 | 120 局（基础队伍） | 8,796 个决策点 | 390 → 82 处 |
| 10-23 | 8 组队伍各 100 局 | 约 5.8 万个决策点 | 约 1,100 → 约 650 处 |
| 10-23 | 3,000 局 OU + 40 组 fixtures + 30 组 big，共 8,500 局 | 约 51 万个决策点 | 约 7,000 → 约 1,400 处 |
| 10-23 | 600 局 OU，按决策点统计（与 v7.3 代码对比） | 45,219 个决策点 | 42.6% → 0.17% |
| 10-23 | 百万级首轮：8,000 局 OU（1 万对新配对）+ 40 组 fixtures + 30 组 big，换新种子，共 14,400 局 | 1,085,812 个决策点 | 有差异 0.23%（核心字段 0.08%）；查出一处实战会崩溃的问题（S43） |
| 10-23 | 百万级第二轮（S43–S51 之后） | 1,085,812 个决策点 | 有差异 0.22%（核心字段 0.07%）；查出 S48 引入的我方回归（S52） |
| 10-23 | 百万级第三轮（S52–S54 之后） | 1,085,812 个决策点 | 有差异 0.26%（核心字段 0.06%）；上一个道具在约 70 局里出错，是 S52 的别名在换回场时没跟上（S55）；之后 S55–S82 把这一轮的 219 个例子局修到只剩已知的两类 PP |
| 10-23 | 百万级第四轮（S55–S82 之后） | 1,085,812 个决策点 | 有差异 **0.068%**（核心字段 0.043%，大半是已知的 PP 三局）。（更正：当时说"S82–S88 之后这一轮的 69 个例子局全部一致"不对——复查工具取队伍配对时用了 `seed % 文件长度`，而 `check_state_build` 取的是 `pairs[seed - 偏移]`；偏移不为 0 时 300 对的 fixtures 和 big 文件取到的是别的对局，OU 和 200 对的文件不受影响。之前修的问题都是在真实复现的对局里确认过的，但 fixtures / big 那部分的"已修完"是对错了局；报告现在记下 `seed_offset`，工具按它取） |
| 10-23 | 百万级第五轮：换新种子（OU 偏移 50000，fixtures / big 偏移 2000），共 14,400 局 | 1,087,510 个决策点 | 有差异 **0.034%**（核心字段 0.014%）；S89–S111 之后，第三到第五轮的 323 个例子局只剩约 12 局；S112–S123 之后全部一致 |
| 10-23 | 百万级第六轮：又一批新种子（OU 偏移 60000，fixtures / big 偏移 3000） | 1,085,967 个决策点 | 有差异 **0.010%**（112 个决策点；核心字段 **0.0036%**）；S124–S137 之后，第三到第六轮的 342 个例子局全部一致 |
| 10-23 | 回放路径百万级首轮（OU 偏移 70000，fixtures / big 偏移 4000） | 1,086,816 个决策点 | 有差异 OU 0.66%、fixtures 0.65%、big 0.43%：大部分是比较框架（未识破的伪装没排除；镜像对局里先知替换按队伍名分不清两边；形态不同的种族名对不上——实战路径的先知替换同样修了；变身后上一招的格位是记法），其余 S143–S145；之后这一轮的 55 个例子局全部一致 |
| 10-23 | 回放路径百万级第二轮：新种子（OU 偏移 80000，fixtures / big 偏移 5000） | 1,086,136 个决策点 | 有差异 **0.011%**（115 个决策点）；S146–S151 及比较框架之后，只剩一局：Zoroark 伪装成最大 HP 相同的 Ditto（见"已知"） |
| 10-23 | 百万级第七轮：又一批新种子（OU 偏移 70000，fixtures / big 偏移 4000） | 1,086,825 个决策点 | 有差异 **0.0010%**（11 个决策点，5 局；核心字段 0.0002%）；S138–S142 之后第三到第七轮的 347 个例子局全部一致 |
| 10-23 | 回放路径百万级第三轮：新种子（OU 偏移 90000，fixtures / big 偏移 6000） | 1,086,608 个决策点 | 有差异 **0.0012%**（13 个决策点），核心字段 0；另有一局是测试框架选招出错（不是构造问题） |

## 方法

- **怎么比**：`scripts/check_state_build.py`（`enginecheck/statebuild.py`；runner 仍是 `enginecheck/random_battle.js`，加了 `views`：每个玩家视角的协议行（Showdown 的 `|split|` 已解开）和每个决策点的 request）。每个决策点，按服务器的实际顺序（先日志，后 request：`server/room-battle.ts` 先 `update` 再 `sideupdate`）喂给 poke-env，调 `build_state`，和 `enginecheck.engine_state(真实状态)` 比较。
- **先知模式（默认）**：对方隐藏的配置（道具、特性、招式、能力值、太晶属性）换成真实配置（`statebuild._oracle`），信念抽样带来的差异全部消失，剩下的一定是构造错误；对方的隐藏字段因此也能比。`--belief` 关闭它。
- **比较什么**：我方整侧（每只的 HP、能力值、异常、道具、当前 / 基础特性、招式与 PP 和禁用、太晶、睡眠计数、变身备份、上一个道具；一侧的 volatile 及计数、场地状态及剩余回合、能力等级、替身、Wish / Future Sight、上一招），对方的公开部分（同上，先知模式下加隐藏部分），场地（天气 / 场地 / 各种空间及剩余回合）。
- **不计为错误（玩家本来无从得知，或两边只是写法不同）**：
  - Showdown 随机抽的持续时间（混乱、束缚、连续招式的长度：`HIDDEN_LENGTH`），只比有无；
  - 变身后复制来的能力值（request 只给自身的）；挨过打的替身剩多少 HP；
  - 对方伪装中的 Zoroark（这个世界是否抽中它，是信念的抽样）；没被识破就换下的伪装（真实对战里 HP 是百分比，看不出来）；
  - 已倒下的宝可梦的其余字段（形态已还原，什么都不读它）；要换下的出场宝可梦和"必须休息"回合的禁用标记（Showdown 的标记是上一次招式请求时的）；
  - Future Sight 的使用者按种族比（两边的队伍顺序不同）；太晶标记的"本方已用过太晶"按一侧比；Greninja-Bond 当作 Greninja；引擎不认识的道具都当作 UNKNOWNITEM；
  - 一个在混乱中结束的 Outrage 锁定（已经混乱时锁定结束不打日志）；Own Tempo 的宝可梦的锁定结束（不会混乱，同样不打日志）；
  - 畏缩（flinch）：随机判定，静默加上，只有挡下招式时才显示。
  - 伪装中倒下的 Zoroark：日志的 faint 写的是伪装的名字，那时无从得知。
- **差分框架自身的修正（续）**：先知模式注入对方真实配置时，Power Trick 下 Showdown 的能力值已交换，注入未交换的（与变身时取 backup 一样）。
- **差分框架自身的修正**：回合结束后的换人决策（`|upkeep|` 之后、下一个 `|turn|` 之前），`engine_state` 推算 Future Sight / Wish 用的回合数要加一（引擎差分只比较回合开始，从未碰到）。
- **数据**：`data/teams/statebuild_catalog_pairs.jsonl`（1,176 支真实 OU 队伍随机配对，本地生成）、`tests/fixtures/random_battle_teams*.jsonl`（40 组，1.16 万对）、`data/teams/big/`（30 组，8.7 万对）。同一对队伍换种子就是新对局。
- **流程**：跑一批 → 按"出现在多少局里"排序 → 看例子（日志 + 两边的值）→ 对照 Showdown 源码确认规则 → 修 → 写针对性测试（修复前必须失败）→ 回归（全量测试 + 两个基线 + 引擎差分）→ 记入下表。
- **脚本**：百万级扫描 `scripts/state_build_sweep.sh <live|replay> <OU 种子偏移> <fixtures / big 种子偏移> <标签>`（每轮换新种子）；复查报告里的例子局 `scripts/rerun_state_build.py <报告…> [--list 类别]`（按 `pairs[种子 − 偏移]` 取队伍配对，与扫描一致）。

## 问题表

"路径"：实 = 实战（request），回 = 回放（spectator），两者共用的写"两"。测试列是针对性测试的名字（同名多个用例的写函数名）。

| # | 问题 | 路径 | 修复 | 测试 |
|---|---|---|---|---|
| S1 | request 里 Taunt / Heal Block / Throat Chop / Assault Vest / Gigaton Hammer / 必须休息 / 蓄力第二回合 / PP 用尽造成的禁用，被写成招式的禁用标记；引擎从不清除自己没设的标记（Assault Vest 被打掉后变化招仍然不能用） | 实 | 这些由引擎自己推出，不写标记；规则与差分框架共用 `engine_state.derived_disable`（锁定、Disable、Encore 的标记照写；锁定优先于 Taunt，并持续到休息回合之后） | `test_a_disable_the_engine_derives_is_no_flag`、`test_out_of_pp_and_encore_flags` |
| S2 | `-fail` 写的是目标（对已中毒的对手用 Toxic），失败没记给出招方 | 两 | 记给刚出招的一方；带 `[from]` 的是特性挡下附加效果，不算 | `test_a_fail_on_the_target_is_the_movers` |
| S3 | 变化招的能力变化全是 0（+6 时的剑舞）也是失败，日志没有 `-fail` | 两 | 紧跟招式行的能力变化全为 0 → 失败；有一项不为 0（龙舞）→ 不算；回合末特性（加速）的提升不算招式的 | `test_a_status_move_changing_no_stage_failed`、`test_more_of_the_logs_facts` |
| S4 | 被 Magic Bounce / Magic Coat 弹回的那一行被当成反弹方自己的出招 | 两 | 不算反弹方的行动；原使用者记失败；反弹回的招式是反弹方本回合的结果 | `test_a_reflected_move_is_not_the_reflectors` |
| S5 | 守住被 Feint / Phantom Force 打破后，stall 计数还在 | 两 | 第 6 世代起打破即清零（battle-actions） | `test_a_broken_protect_resets_the_count` |
| S6 | Trick Room / Gravity / Magic Room / 墙 / Tailwind 按 poke-env 的开始回合推算，回合结束后的强制换人差一回合 | 两 | 计时器数回合结束（`fields_elapsed` / `side_elapsed`） | `test_rooms_and_screens_count_their_ends_of_turn` |
| S7 | Safeguard、Mist 从未传给引擎 | 两 | 传入 | 基线 |
| S8 | 蓄力招式的第二回合（`-prepare`）没有对应的 volatile | 两 | 加 volatile（瞬发的 `-anim` 除外） | `test_charging_and_locking_moves`、`test_a_charging_and_a_locked_active` |
| S9 | 连续招式（Outrage）的锁定没有传：`lockedmove`、计数、其他招式的标记 | 两 | 加入；长度由每个世界抽（50%）；第一次没打中不算锁定；被守住 / 落空 / 混乱自伤结束；用满 3 次结束；回合结束时还睡着才结束 | 同上、`test_the_logs_facts_fourth_batch` |
| S10 | 对方后备的 Regenerator 宝可梦换下时的回复（日志不显示），poke-env 只在已知特性时才加 | 两 | 这个世界的特性是 Regenerator 就补上 1/3；换下时特性被换走 / 压制 / Neutralizing Gas 生效则不补 | `test_a_benched_regenerator_healed` |
| S11 | 形态变化后种族 id 仍是原形态（Ogerpon 太晶形态、Palafin-Hero、Mimikyu-Busted、Cramorant 吞食）；Battle Bond Greninja 不是 Greninja-Bond，引擎的 Battle Bond 不触发 | 两 | 种族取计时器记的当前形态（临时形态只对在场、未倒下的）；带 Battle Bond 的 Greninja 用 greninjabond | `test_formes_and_more_volatiles_reach_the_engine`、`test_formes_from_the_log` |
| S12 | Protean / Libero 的 volatile 依赖 poke-env 知道特性，它常不知道 | 两 | 看日志的 `typechange [from] ability: Protean/Libero` | `test_more_of_the_logs_facts` |
| S13 | Unburden 的 volatile 从未传 | 两 | 本次上场失去过道具且这个世界的特性是 Unburden | 基线 |
| S14 | 挣扎标记（L232 的 STRUGGLED）从未传；挣扎后被锁定时上一招应是锁定的招 | 两 | 加入 | 基线 |
| S15 | 被吸收类特性吸收的招式（Flash Fire、Water Absorb、Storm Drain，Wind Rider 的 `-ability` 写法……）没记失败；Flash Fire 的 volatile 没传 | 两 | 记失败，加 volatile | `test_more_of_the_logs_facts` |
| S16 | Showdown 返回 NOT_FAIL 的 `-fail`（满血 Synthesis）被记成失败；Substitute 的、无人可换的 Healing Wish 的要记 | 两 | 名单 `timers.NOT_FAIL`（按真实数据核过） | `test_more_of_the_logs_facts` |
| S17 | 守住失败时 stall 计数要当场清零（回合中途的决策看到旧值） | 两 | 清零 | 同上 |
| S18 | 回合末 Future Sight 打中时的 `-immune` 被算成上一招失败 | 两 | 延迟招式结算时清掉"刚出招的一方" | 同上 |
| S19 | Destiny Bond、Roost（回合内）、Metronome 道具的连续计数没传 | 两 | 加入 | 同上 |
| S20 | 我方伪装中的 Zoroark 缺 `illusion`；对方抽中 Zoroark 的世界同样 | 两 | 加入 | 基线 |
| S21 | Illusion 的记账：poke-env 把伪装期间的 HP、招式、PP、能力变化、用掉的道具、上一招、太晶都记给被伪装的宝可梦，识破后不还原 | 两（实战我方由 request 纠正） | 计时器按"每次上场"记账，识破或抽中时整体划给 Zoroark；被伪装方的 HP 回到伪装前，直到它自己再次上场 | `test_the_logs_facts_fourth_batch`、基线 |
| S22 | "刚换上"的上一招（Fake Out 用）：回合中途换上的、伪装上场的漏判；行动被阻止（畏缩、混乱自伤）后应是 none | 两 | 计时器的 `fresh` | `test_more_of_the_logs_facts` |
| S23 | Revival Blessing 复活的宝可梦不再太晶 | 两 | 去掉太晶标记（一侧的已用太晶标记保留，L185） | 基线 |
| S24 | Lunar Dance 回满 PP（第 9 世代） | 两 | 之后的使用重新计数 | `test_the_logs_facts_third_batch` |
| S25 | 设下效果时道具被压制（Magic Room、Embargo、Klutz）仍按延长算；Court Change 交换后计数、设下者没跟着换 | 两 | 记为无道具；交换 | `test_the_logs_facts_fourth_batch` |
| S26 | 剧毒计数上限：引擎是 15（L181），我们封 14 | 两 | 15 | 基线 |
| S27 | Shed Tail / Baton Pass 传过来的替身没传 | 两 | 加入（HP 为使用者最大 HP 的 1/4） | 基线 |
| S28 | 属性变化：形态带来的（Meloetta-Pirouette）要 typechange；太晶之后的变化无效、之前的保留；变身只在属性真变时加；变身复制到的无效特性（Neutralizing Gas）记为 none | 两 | 照差分框架的规则（`NO_TRANSFORM` 共用） | `test_the_logs_facts_third_batch` |
| S29 | 回合中途的决策缺本回合的 Protect / Endure / Baneful Bunker 等 volatile | 两 | 加入 | 基线 |
| S30 | Uproar（含计数，锁定由引擎推）、Stockpile（层数）、Truant（出招后下回合偷懒）、Minimize 没传 | 两 | 加入 | 基线 |
| S31 | 束缚方倒下后束缚没解除 | 两 | 解除 | 基线 |
| S32 | 混乱自伤：算本回合已行动（Encore / Taunt 计数）、算失败、结束锁定 | 两 | 加入 | `test_the_logs_facts_third_batch` |
| S33 | poke-env 在 Neutralizing Gas 下（或 Pressure 方中 Gastro Acid）仍按 Pressure 扣 2 PP | 两 | `agents/poke_env_fixes.py`（导入 `engine_state` 时生效） | `test_pressure_under_neutralizing_gas_takes_one_pp` |
| S34 | 上一个道具（lastItem：Harvest、Recycle、Cud Chew 用）从未传（`doc/engine-diff.md` 记的遗留项） | 两 | 计时器记"用掉 / 吃掉"的道具（含宝石、Fling；不含被拿走的、打破的气球）；Harvest / Recycle 清除 | `test_the_logs_facts_third_batch`、`..._fourth_batch` |
| S35 | Spite / Eerie Spell 扣的 PP 没记 | 两 | 计时器记 | 同上 |
| S36 | 变化招打在替身上（`-fail` 使用者）不算失败；攻击招（Sucker Punch）的失败要算 | 两 | 加入 | `test_the_logs_facts_third_batch` |
| S37 | Psychic Terrain / Queenly Majesty / Dazzling / Armor Tail 挡下先制招式，出招方算失败 | 两 | 加入 | 同上 |
| S38 | 招式 / 特性改了特性（Simple Beam、Worry Seed、Skill Swap、Mummy……）、Gastro Acid 压制，poke-env 不记为临时特性 | 两 | 计时器记当前特性；Gastro Acid 加 volatile、特性 none | 同上 |
| S39 | Cud Chew 的计数没传 | 两 | 2（回合末吃的是 1），它自己再吃那次不再计 | 同上 |
| S40 | 变身后 PP 用尽，request 只给 Struggle：复制招式丢失；讲究锁定的标记也要保留 | 实 | 回退到目标的招式和 poke-env 记的 PP，带锁定标记 | 基线 |
| S41 | 我方的太晶属性 / 标记被伪装上场的 `tera:` 写到了别的宝可梦 | 实 | 以 request 为准 | 基线 |
| S42 | Synchronize 等特性自己的 `-fail` 被算成出招失败 | 两 | 跳过紧跟特性 `-activate` 的 `-fail` | `test_the_logs_facts_fourth_batch` |
| S43 | **我方 pivot、对方招式待执行时，`_with_saved_move` 按"倒数第 6 个字段"写入对方暂存的招式；一侧末尾的可选字段（`tera_used`、`future_doom`）出现时位置漂移，招式名写进布尔字段，引擎解析时 panic（实战会让这一步搜索崩溃）** | 两 | 按引擎反序列化的固定位置（第 24 个字段） | `test_a_saved_move_with_the_sides_optional_fields` |
| S44 | Doom Desire 从未记为待命中的延迟攻击 | 两 | 与 Future Sight 一起记，带引擎的 `future_doom` | `test_the_logs_facts_fifth_batch` |
| S45 | 本回合守住成功后，回合中途的决策（复活选择、pivot）里 Protect 计数还没加 | 两 | 当场计入（Showdown 的 stall 计数） | 同上 |
| S46 | 上一招应是宝可梦自己选的招（Metronome 调用出的蓄力招结束后是 Metronome），poke-env 找不到 | 两 | 计时器记自己选的招，poke-env 没有时用它 | 同上 |
| S47 | Trick 换来的讲究道具不锁定换来之前用的招（L228），我们按"道具是讲究 + 上一招"当成锁定 | 实 | 记"出招后才拿到道具" | 同上 |
| S48 | 计时器的键随永久形态变化（`detailschange`）改变，构造时却用 poke-env 不变的种族名查：Eiscue-Noice 用掉的道具、睡眠计数、异常状态都会查不到 | 两 | 键始终跟 poke-env 的种族名（只有换入行的新 details 才改，并把记录一起搬过去）；当前形态另记 | `test_formes_from_the_log` |
| S49 | Imprison 的 volatile 从未传 | 两 | 加入 | `test_the_logs_facts_fifth_batch` |
| S50 | 第 1 回合的能力变化标记（L222）按当前能力等级判断，被 Haze 等清掉后就丢了 | 两 | 按日志里第 1 回合是否发生过 | 同上 |
| S51 | Sleep Clause 挡下催眠招要算失败；传过来的替身挡下变化招不算；Double Shock / Burn Up 没有对应属性时不算，Shed Tail 体力不足算 | 两 | 加入 | 同上 |
| S52 | S48 只照顾了对方：我方宝可梦的种族名随 request 的 details 变（Mimikyu-Busted），计时器的键不变，查不到用掉的道具、睡眠计数 | 两 | 计时器记"形态名 → 键"的别名（`SideTimers.k`），所有按种族查计时器的地方都经过它 | 基线 |
| S53 | Metronome 调出的蓄力招在第二回合锁定执行，Showdown 把它写进 lastMove；它不是自己的招，上一招应为 none | 两 | 记最后一次锁定执行的招 | 基线 |
| S54 | 禁用规则的先后：Encore 的标记不能盖过 Taunt / Assault Vest 这类引擎自己推出的（差分框架的顺序），蓄力 / 休息 / PP 用尽 / Uproar 只在没有其他标记理由时才不写 | 实 | `derived_disable` 按这个顺序 | `test_out_of_pp_and_encore_flags` |
| S55 | S52 的别名没跟上换回场：以新形态的 details 换回场时键搬到新形态，别名却还指向旧键，Mimikyu-Busted 的 Red Card、Eiscue-Noice 的树果、Terapagos 的睡眠计数都查不到 | 两 | 键搬家时别名一起改，新形态不再指向旧键 | `test_formes_from_the_log` |
| S56 | 首回合上场、行动被阻止（冻住 / 睡着的 `cant`）后回合中途的决策：poke-env 的 `first_turn` 只按回合数算，上一招仍写成 switch | 两 | 有计时器时只认计时器的计数 | `test_last_move_sets_encore_move_or_drops_encore` |
| S57 | Armor Tail / Dazzling / Queenly Majesty / Damp 挡下先制招时，Showdown 的 `cant` 写的是特性持有者、`[of]` 才是出招方：失败记错了一方 | 两 | 带 `[of]` 的 `cant` 记给 `[of]` 一方 | `test_the_logs_facts_sixth_batch` |
| S58 | 变身后的 Transform 自己是上一招（L187：引擎记在备份招式的格位上），poke-env 只剩目标的招式，上一招丢了 | 两 | 计时器记的招在备份招式里时，取它的格位 | `test_last_move_sets_encore_move_or_drops_encore` |
| S59 | 变身后讲究锁定的招 PP 用尽、改用 Struggle：poke-env 的上一招是 Struggle，锁定标记丢了 | 实 | 用计时器记的自己选的招 | `test_our_struggling_choice_locked_ditto_keeps_the_locks_flags` |
| S60 | Illusion 被识破时，poke-env 让伪装换下（清掉 volatile），Zoroark 一个都没有：同回合打在伪装上的 Salt Cure 丢了 | 两 | `poke_env_fixes`：识破时 volatile 转给 Zoroark | `test_a_broken_illusion_keeps_its_volatiles` |
| S61 | Baneful Bunker / King's Shield / Spiky Shield / Silk Trap / Burning Bulwark / Obstruct 的日志写的是 "Protect"，volatile 被写成 protect | 两 | 取紧前的出招行里的招（Detect 仍是 protect） | `test_the_logs_facts_sixth_batch` |
| S62 | 变身成 Ogerpon / Terapagos 后不能太晶（引擎的 notera，L227）从未传 | 两 | 加入 | `test_transformed_into_an_ogerpon_cannot_terastallize` |
| S63 | Dry Skin 回合末在雨天的回复被当成"特性吸收了对方的招"，对方记失败 | 两 | 吸收的回复带 `[of]` 出招方，只认这种 | `test_the_logs_facts_sixth_batch` |
| S64 | Perish Song 有目标免疫（Good as Gold）或落空不算失败（它的 onHitField 仍返回成功） | 两 | 跳过 Perish Song 的 `-immune` / `-miss` | 同上 |
| S65 | 行动被阻止（`cant`）时 Destiny Bond 结束（onMoveAborted），我们留着它 | 两 | `cant` 时结束 | 同上 |
| S66 | 暂时形态（`-formechange`：Meloetta-Pirouette、Cramorant、Morpeko-Hangry）换下后 poke-env 仍保留那个形态的属性和能力值（重新上场的 details 没变，它不更新） | 两 | `poke_env_fixes`：换下时恢复本来种族的属性和能力值；`detailschange` 的永久形态不动 | `test_a_temporary_forme_ends_with_its_switch_out` |
| S67 | Morpeko-Hangry 太晶后，Showdown 把它的 baseSpecies 设成 Hangry（静默，没有 detailschange）：换下后仍是 Hangry | 两 | 太晶时 Morpeko 的暂时形态转为永久 | `test_the_logs_facts_sixth_batch` |
| S68 | 实战：我方 Zoroark 伪装上场，当回合打在伪装上的能力变化 / volatile（Sticky Web 的减速），在 poke-env 按 request 纠正出场时被清掉；开局伪装时 Zoroark 甚至还不在 poke-env 的队伍里 | 实 | `poke_env_fixes`：纠正时转给 request 的出场宝可梦 | `test_a_broken_illusion_keeps_its_volatiles` |
| S69 | Revival Blessing 复活过的宝可梦之后再太晶，"复活过 → 不再是太晶状态"的标记还在，把它的太晶清掉了，太晶记到了一只倒下的宝可梦上 | 两 | 太晶时清掉复活标记 | `test_the_logs_facts_sixth_batch` |
| S70 | 我方讲究锁定的招 PP 用尽后 Struggle，又中了 Taunt：锁定的招丢了，变化招的标记按 Taunt 推导成"不写" | 实 | Struggle 后用计时器记的自己选的招 | `test_a_struggling_choice_lock_keeps_its_flags_under_a_taunt` |
| S71 | Neutralizing Gas / Gastro Acid 下出招的 Truant 宝可梦下回合不偷懒（它的 onBeforeMove 不运行） | 两 | 特性被压制时不记 | `test_the_logs_facts_sixth_batch` |
| S72 | Trick 换来新的讲究道具后，Showdown 解除原来的锁定，随后的 Struggle 不锁定任何招：上一招应为 none | 两 | Struggle 不清"出招后才拿到道具"；Struggle 后的锁定要求没有这个标记 | 同上 |
| S73 | Court Change 换过来的墙，setter 只按种族记；两边都有 Dragapult 时，查到了自己这边那只的道具（Choice Specs），Light Clay 的 8 回合变成 5 回合 | 两 | 记哪些 setter 来自对面 | 同上 |
| S74 | 这个 Showdown 版本的 Slow Start 是特性自己的计数，Neutralizing Gas 下不减 | 两 | Gas / Gastro Acid 下不数 | 同上 |
| S75 | 混乱自伤同样触发 onMoveAborted：蓄力招的第二回合、Destiny Bond 结束；Truant（BeforeMove 优先级 9）先于畏缩 / Disable / 麻痹 / 混乱运行，这些情况下下回合仍偷懒，睡眠 / 冰冻 / 需要休息则不 | 两 | 按 Showdown 的顺序 | 同上 |
| S76 | Neutralizing Gas 结束时其他特性重新开始：Truant 的 onStart 给本回合已经行动（或回合已结束）的宝可梦加上偷懒（S71 之后漏了这一条） | 两 | Gas 结束时补上 | 同上 |
| S77 | Intimidate 被替身挡下的 `-immune` 被算成刚 U-turn 换下的宝可梦的失败 | 两 | 紧跟特性行的 `-immune` 不算招式的 | 同上 |
| S78 | 守住被打破（Hyperspace Fury 等 `[broken]`）后它的 volatile 还在 | 两 | 一起清掉 | 同上 |
| S79 | 变身后的宝可梦用复制来的 Protean 改了属性（日志写明），Protean 的 volatile 没有传（变身的一律排除了） | 两 | 日志写明时加上 | `test_a_transformed_mons_copied_protean` |
| S80 | Forest's Curse / Trick-or-Treat 的附加属性：Showdown 的属性里有它，引擎的 typechange 没有传 | 两 | poke-env 的 TYPEADD 记为 typechange | `test_an_added_type_is_a_type_change` |
| S81 | 实战：我方伪装中的 Zoroark 被识破，那回合打在伪装上的能力变化丢了（对方 / 回放走计时器的 `illusion_boosts`） | 实 | `poke_env_fixes`：实战时识破一并转移能力变化 | `test_a_broken_illusion_keeps_its_volatiles` |
| S82 | （撤回）以为 request 纠正后日志写伪装名字的能力变化会丢；其实 poke-env 的 `get_pokemon` 本身就把我方出场位解析到出场的 Zoroark，当时的实验是测试数据给每只宝可梦都设了 Illusion 特性 | — | 撤回，测试数据改正 | `test_a_broken_illusion_keeps_its_volatiles` |
| S83 | Showdown 每次换入会发一条只为显示的 `-start typechange …|[silent]`（第 7 世代起的外观属性）；伪装时是伪装对象的属性（已太晶成 Water 的 Hatterene），被记成了 Zoroark 的属性改变 | 两 | 我方出场的是 Zoroark 时跳过；识破 / 纠正时这条带来的 typechange 不转给 Zoroark | 同上 |
| S84 | Lunar Dance 回满 PP 后，计时器按"每招 1 点"重新计数，Pressure 下多扣的那 1 点没算 | 两 | `poke_env_fixes`：Lunar Dance 时把 poke-env 的 PP 恢复满（之后它自己的计数含 Pressure）；去掉计时器的这套计数；Spite 扣掉的也一并恢复 | `test_lunar_dance_and_skill_swap_pp` |
| S85 | Skill Swap 时 poke-env 没记下 `[of]` 一方原本的特性（使用者换到的那个），之后宣告的 Pressure 被当成它的本来特性，此后每次对它出招都扣 2 PP | 两 | 记下 | 同上 |
| S86 | 实战：我方 Zoroark 伪装上场，当回合 poke-env 以为上场的是伪装对象（伪装成 Pressure 宝可梦时对方多扣 PP，HP 也写到了伪装对象上）；换入行显示的最大 HP 其实是 Zoroark 的 | 实 | `poke_env_fixes`：按最大 HP 认出是 Zoroark，让 poke-env 换入 Zoroark（日志原样保留，计时器照旧认得出伪装） | `test_a_broken_illusion_keeps_its_volatiles` |
| S87 | 回合结束后换上的宝可梦 Wind Rider 的 `-ability … boost` 被当成特性吸收了对方本回合的招 | 两 | 回合结束时清掉"刚出招" | `test_the_logs_facts_sixth_batch` |
| S88 | 我方伪装中的 Zoroark 用掉的道具（开局伪装的 Throat Spray）记在伪装对象名下 | 两 | 构造时按本次上场记录把道具挪给 Zoroark（与识破时计时器的做法一致） | `test_our_disguised_zoroarks_used_item_is_its_own` |
| S89 | Misty Terrain / Electric Terrain / Safeguard 挡下异常状态招（`-activate … move: Misty Terrain`），Showdown 算招式失败；回合末 Yawn 生效时的 `-activate` 不算 | 两 | 加入 BLOCKERS，排除紧跟 Yawn `-end` 的 | `test_the_logs_facts_seventh_batch` |
| S90 | 回合末 Yawn 生效时触发的 Sleep Clause 消息被算成最后出招一方的失败 | 两 | 紧跟 Yawn `-end` 的不算 | 同上 |
| S91 | Aroma Veil 等特性的 `-block`（挡下 Taunt / Encore）算招式失败 | 两 | 加入 | 同上 |
| S92 | 替身持有者倒下后替身还在（之后的变化招 `-fail` 被当成"打在替身上"）；Shed Tail 传来的替身也是 | 两 | 倒下时清掉 `sub_on` / `sub_passed` | 同上 |
| S93 | 变化招打在替身上的 `-fail` 与 Infiltrator 穿过替身后失败的日志完全一样（模拟器实测：前者 moveLastTurnResult 为真） | 两 | 计时器单独记下，构造时按这个世界出招方的特性（Infiltrator）决定 | 同上 |
| S94 | 变身后锁定招式（Outrage）的 request 只列出那一招、不带 PP：Ditto 只剩一招、0 PP | 实 | request 没列全时用目标的招式和 poke-env 记的 PP | `test_our_locked_dittos_request_lists_one_move` |
| S95 | 变身后的招式标记没走 `derived_disable`（PP 用尽 / Taunt 等引擎自己推出的也写成了标记）；只剩 Struggle 且锁定时，锁定的招 PP 必为 0 | 实 | 与未变身时同一套规则 | 基线、`test_our_struggling_choice_locked_ditto_keeps_the_locks_flags` |
| S96 | 上一个锁定在混乱中静默结束，下回合重新选的 Outrage 被当成第 3 次而结束锁定 | 两 | 不带 `[from] lockedmove` 的一律重新计数 | `test_the_logs_facts_sixth_batch` |
| S97 | Showdown 换入时只为显示的 `typechange [silent]`（变身成同属性的 Ditto、伪装）被 poke-env 记成属性改变 | 两 | `poke_env_fixes`：这类显示行 poke-env 一律不处理（S83 的特殊处理随之简化） | `test_a_broken_illusion_keeps_its_volatiles` |
| S98 | 太晶后形态变化（Meloetta-Pirouette）：Showdown 改掉的是太晶前的属性，引擎的 typechange 应保留，我们按"太晶后的属性变化无效"删了 | 两 | 形态带来的属性变化不受太晶影响 | `test_a_formes_type_change_after_terastallizing` |
| S99 | 打伪装成 Pressure 宝可梦的对方 Zoroark 时 poke-env 扣了 2 PP；识破后可知只该 1 | 两 | `poke_env_fixes`：按目标记下 Pressure 多扣的，识破时退还 | `test_lunar_dance_and_skill_swap_pp` |
| S100 | Gastro Acid 的压制在日志里是 `-endability`，poke-env 不记，Pressure 照扣 2 PP | 两 | `poke_env_fixes`：`-endability` 记为 Gastro Acid | 同上 |
| S101 | 锁定的 Outrage 被 Cursed Body 封住：锁定的 request 仍列出它，Showdown 的格位是禁用的 | 实 | 被 Disable 的招即使在 request 里也写标记（引擎给出 No Move，与 Showdown 的 `cant … Disable` 一致） | `test_a_disabled_locked_move_and_power_trick` |
| S102 | Unburden：引擎的 volatile 在本次上场失去过道具后一直在（只在无道具时加速，L226）；我们拿到新道具就清掉；Trick 交换没有 `-enditem`，失去的一方没记 | 两 | 不清；交换时双方都记失去 | `test_the_logs_facts_sixth_batch` |
| S103 | 对方 Imprison 后变身成我方：我方招式全被封（request 只说 maybeDisabled），我们照常可用 | 实 | 对方 Imprison 时，它出场宝可梦也会的招写标记 | `test_an_imprisoning_foes_shared_moves_are_disabled` |
| S104 | Yawn 在 onTryHit 里先查目标的异常状态（早于替身）：打在已有异常、有替身的目标上算失败 | 两 | 替身例外里排除这种 Yawn | `test_the_logs_facts_seventh_batch` |
| S105 | Synchronize 把异常传给火属性对手时的 `-immune` 被算成招式失败 | 两 | 紧跟特性 `-activate` 的 `-immune` 不算 | 同上 |
| S106 | Take Heart 在 +6 时能力不变但治好了异常，不算失败 | 两 | 紧跟的 `-curestatus` 撤销失败 | 同上 |
| S107 | Rest 被自己的 Insomnia 挡下（`-fail … [from] ability`）是失败（带 `[from]` 的一律跳过了） | 两 | 出招方自己的特性挡下自己的变化招：失败 | 同上 |
| S108 | Effect Spore 在接触时被 Sleep Clause 挡下，消息被算成攻击方招式的失败 | 两 | 只认出招方的变化招 | 同上 |
| S109 | Illusion 被识破时，伪装名下的异常 / 睡眠记录没挪给 Zoroark（replace 行写的是 Zoroark 自己，按它查不到），剧毒计数丢了 | 两 | 从伪装的键挪 | 同上 |
| S110 | 我方伪装中的 Zoroark 被催眠，睡眠计数记在伪装名下 | 实 | 构造时 request 说 Zoroark 睡着、伪装对象没睡时挪过来 | `test_our_disguised_zoroarks_sleep_is_its_own` |
| S111 | Power Trick 的 volatile 和攻防交换从未传（引擎状态里是交换后的值加 volatile） | 两 | 加入 | `test_a_disabled_locked_move_and_power_trick` |
| S112 | Simple Beam 打在 Dry Skin 宝可梦上：`-ability|…|Simple|Dry Skin|[from] move: Simple Beam` 被"特性吸收"的分支截走（第 5 个字段是 Dry Skin），特性没变还记了一次失败 | 两 | 带 `[from] move:` 的不算吸收 | `test_the_logs_facts_seventh_batch` |
| S113 | 识破后的 Zoroark 用 White Herb 清掉负面能力变化，计时器补上的伪装期间的那份没清 | 两 | 清能力变化时一并清 | 同上 |
| S114 | Neutralizing Gas 下 Truant 的处理不运行：上回合留下的偷懒标记既不加也不去（S71 把它清掉了） | 两 | 被压制时保持原值 | 同上 |
| S115 | poke-env 看到 HP 行里的睡眠就结束 Yawn（自己用 Rest 睡着也算）；Showdown 留到它自己的 `-end` | 两 | `poke_env_fixes`：只有 `-end` 或离场才结束（日志和 request 两处） | `test_lunar_dance_and_skill_swap_pp` |
| S116 | Skill Swap 换走 Protean 后，Protean 的"已用过"标记还在（Showdown 的特性状态重置） | 两 | 特性变化时清掉 | `test_the_logs_facts_seventh_batch` |
| S117 | Copycat / Metronome 调出的 Outrage 同样锁定，我们把带 `[from] move:` 的排除了 | 两 | 加入 | 同上 |
| S118 | 倒下离场的宝可梦没有 Regenerator：Revival Blessing 复活后被多补了 1/3 | 两 | 倒下时记入不再生 | 同上 |
| S119 | 我方 Zoroark 在更早一次伪装上场时睡着，睡眠计数记在那次伪装的名下（S110 只管这次上场） | 实 | request 说 Zoroark 睡着而无记录、某个没睡着的宝可梦名下有一条时挪过来 | 基线 |
| S120 | 打在 Protect 上的招结果是 null（不是 false）：Metronome 道具的连续计数要清零 | 两 | 另记"什么都没做" | `test_the_logs_facts_seventh_batch` |
| S121 | As One 宣告时会连带它包含的特性（Unnerve / Chilling Neigh），poke-env 留下后者；变身成 Calyrex 的 Ditto 也是 | 两 | 以配置里的 As One 为准 | `test_as_one_and_a_type_change_after_terastallizing` |
| S122 | S98 把"属性 ≠ 种族属性"都当成形态造成的：太晶后 Double Shock 的属性变化（实际无效）也被留下了 | 两 | 只认计时器记下的形态 | 同上 |
| S123 | S109 的补充：伪装的键与真正的那只宝可梦共用，识破时把真 Suicune 自己的 Rest 睡眠也挪给了 Zoroark | 两 | 每次上场记下原有记录，识破时只挪这次上场改变的部分 | `test_the_logs_facts_seventh_batch` |
| S124 | 形态变化（Showdown 的 setSpecies）会重设属性：之前的 Soak 被冲掉，poke-env 还留着 typechange（Ogerpon 先被改成水属性再太晶成 Teal-Tera） | 两 | `poke_env_fixes`：形态变化时清掉 | `test_the_sixth_runs_construction_facts` |
| S125 | Haze（`-clearallboost`，不带宝可梦名）在计时器里没走到清除，识破后的 Zoroark 带来的能力变化还在 | 两 | 提前处理 | `test_the_logs_facts_eighth_batch` |
| S126 | 回合末结算中才出现的场地（Future Sight 命中触发 Seed Sower）：Showdown 的结算在开始前就收集好了，这次回合末不扣它；只到 `|upkeep|` 为止 | 两 | 结算中出现的从 −1 起数 | 同上 |
| S127 | 我方 Zoroark 在更早一次伪装上场时用掉的道具（之后没被识破就换下了）仍记在伪装名下（S88 只管还在场的） | 实 | 每次上场记下换入行显示的最大 HP；构造时显示的是 Zoroark 的最大 HP、不是那只宝可梦自己的上场，道具挪给 Zoroark | 同上、`test_our_disguised_zoroarks_used_item_is_its_own` |
| S128 | Perish Song 当回合 `[silent]` 写的 perish3，在 Showdown 里到回合末之前是 4：回合中途的决策（Chilly Reception）差 1 | 两 | 记下，回合末前算 4 | `test_the_logs_facts_eighth_batch` |
| S129 | 没有目标的招（`[notarget]`）之后的 `-fail` 是失败，被 Double Shock 的"无对应属性不算失败"例外放过了 | 两 | 无目标时不走例外 | 同上 |
| S130 | Protean / Libero 的 volatile 有一条"poke-env 的特性是它就算"的后备；Skill Swap 换回来时特性状态已经重置 | 两 | 只认日志里的使用（S116 会清） | 基线 |
| S131 | Spite / Eerie Spell 扣掉变身后复制招式的 PP 没算 | 两 | 加入 | `test_the_sixth_runs_construction_facts` |
| S132 | Metronome 道具被打掉后，Showdown 的 volatile 和计数要等它下次出招才清 | 两 | 记下"道具刚丢" | `test_the_logs_facts_eighth_batch` |
| S133 | S91 的 `-block` 也挡下了攻击招的附加效果（Psychic Noise 的 Heal Block）：招本身是成功的 | 两 | 只认变化招 | 同上 |
| S134 | Imprison 等对自己使用、带 mustpressure 的招：Pressure 看的是对方出场宝可梦，poke-env 看的是使用者自己 | 两 | `poke_env_fixes`：查对方 | `test_imprison_pressure_glaive_rush_and_a_transforms_types` |
| S135 | Glaive Rush 的弱点（BeforeMove 优先级 100）在任何被阻止的行动之前就结束 | 两 | `poke_env_fixes`：`cant` 时去掉 | 同上 |
| S136 | 变身复制的是目标当时的属性（Libero 改成的 Normal），poke-env 复制的是种族属性；构造时也改用变身者自己的属性（目标之后可能换下、属性恢复）；太晶不改变太晶前的属性，poke-env 却清掉了 | 两 | `poke_env_fixes` 两处；`_as_transformed` 用变身者的属性 | 同上 |
| S137 | 变成自己原本的属性（纯 Ghost 的 Banette 用 Libero 放 Poltergeist）：Showdown 比较的是属性，没有 typechange | 两 | 属性与种族相同时不加（附加属性、变身、Roost 除外） | `test_a_type_change_to_its_own_types_is_none` |
| S138 | 变身后用掉的道具（Focus Sash）：`_as_transformed` 重建引擎宝可梦时没带上一个道具 | 两 | 带上 | `test_a_transformed_foes_last_item` |
| S139 | S95 的补充：只剩 Struggle 且锁定时，锁定的招也可能是被 Heal Block / Throat Chop / Assault Vest 封住的（不一定没 PP） | 实 | 这些原因时不改 PP | 基线 |
| S140 | S103 的补充：Imprison 看的是施放者的全部招式，不只已暴露的（这个世界的配置）；变身中的只看复制来的 | 实 | 用这个世界的配置 | 基线 |
| S141 | 只降能力的变化招（Tickle）被 Clear Body 全部挡下：失败（Defog、Parting Shot 等还有别的效果，不算） | 两 | 加入 | `test_the_logs_facts_eighth_batch` |
| S142 | S107 误伤：Intimidate 被 Own Tempo 挡下的 `-fail … unboost … [from] ability`，被算成那只宝可梦自己招式的失败 | 两 | 排除 unboost | 同上 |
| S143 | 回放路径：识破后的 Illusion 记账按"用了几次"把 PP 记给 Zoroark，伪装期间打带 Pressure 的对手每次实际扣 2 | 两 | 计时器按 poke-env 同一套规则记每次使用的扣点（Pressure 已宣告、未被压制），记账按扣点 | `test_a_replays_illusion_and_transform_records` |
| S144 | 回放路径：变身时 poke-env 不知道目标的特性（没有 request），留下了它带来的 Imposter | 回 | 此时用这个世界里目标的特性 | `test_a_copied_ability_poke_env_never_knew` |
| S145 | 变身成 Regenerator 宝可梦后换下，复制来的 Regenerator 回 1/3：poke-env 只在知道目标特性时才补（实战知道，回放不知道） | 两 | 计时器记下换下时变身的目标；构造时目标在这个世界里是 Regenerator、poke-env 又不知道时补上 | 同上 |
| S146 | Illusion 识破时，伪装期间显示的异常状态是 Zoroark 的；真宝可梦自己恰好也是同一异常时（S123 按"有变化才挪"）没给 Zoroark | 两 | 异常状态一律给 Zoroark，伪装对象恢复原值 | `test_the_replay_paths_second_run_facts` |
| S147 | Psych Up：`-copyboost|使用者|目标` 是使用者复制目标的能力变化，poke-env 写反了（实战也有，扫描里没碰到） | 两 | `poke_env_fixes`：接管 | `test_a_replays_illusion_and_transform_records` |
| S148 | 打在伪装上的 Soak（属性改变）是 Zoroark 的：识破 / request 纠正时只转了 volatile，没转临时属性，S137 又把 typechange 去掉了 | 两 | 一并转临时属性 | `test_the_replay_paths_second_run_facts` |
| S149 | S141 误伤：Sticky Web 的减速被 Clear Body 挡下，算成了把它吹上场的 Whirlwind 的失败 | 两 | 只认配置数据里带降能力的招 | 同上 |
| S150 | 睡着 / 冻住时 Truant 的处理不运行（它们的 BeforeMove 在前）：偷懒标记保持原值（S75 把它清掉了）；需要休息的那回合由 Showdown 的 mustrecharge 自己清掉（复查时抓到的回归） | 两 | 保持；需要休息时清 | 同上 |
| S151 | Defog 在闪避已到 −6 时能力不变（算失败），但它清掉了钉子，是成功的 | 两 | 由这招带来的 `-sideend` 撤销失败 | 同上 |

已知、比较器漏掉的隐藏信息：回放路径里 Zoroark 伪装成最大 HP 恰好相同的宝可梦（Ditto 和 Zoroark 都是 261）时，比较器靠最大 HP 认不出伪装，伪装期间的 HP / PP 混在一起被算成差异——观战者本就无从得知（回放 1 局）。

已知、待查：无（之前的两局 PP 是 S84 / S85，伪装成 Pressure 宝可梦的我方 Zoroark 是 S86；对方伪装时多扣的 PP 仍是玩家无从得知的，属隐藏信息）。

差分之前的复查轮（10-22 至 10-23，第六到第十轮）修的 Disable、延长道具、Sleep Talk 的 PP、变身链路、连续 pivot 的顺序等，见各自的提交和 `tests/test_engine_state.py`、`tests/test_transform.py`。

## 因果性检查（计划 B）

**B1：训练样本的输入 = 截至该决策点的日志在实战路径上算出的输入。** `scripts/check_causality.py`：每局真实回放按数据构建的方式生成全部决策点的训练样本（`train/positions.positions_from_replay`）；每个样本构造的那一刻，同一个 battle（此时只解析了日志前缀）交给实战路径的 `agents/net_context.contexts`（搜索喂给网络的东西），逐项比较历史、暴露标记、评分、回合。（状态本身由 A 的回放路径差分负责；`faint`、`turns`、`left_*`、`opp_sets` 是辅助头的标签，本来就用整局。）

| 日期 | 数据 | 结果 |
|---|---|---|
| 10-23 | 3,000 局真实回放，166,290 个样本 | 191 处（0.11%）：全在历史 |
| 10-23 | 修复后：同样 3,000 局 + 另 3,000 局 | 0 / 166,303、0 / 168,835 |

| # | 问题 | 修复 | 测试 |
|---|---|---|---|
| C1 | 未来泄漏：对方 pivot（Chilly Reception）换人之后才发生的"我方被麻痹不能动"，被放进本回合第一步——pivot 换人决策点的训练历史里已经有它 | 解析器给 `cant` 记下在本回合行动中的顺序；被阻止的行动发生在对方 pivot 之后时，放进那个 pivot 的步骤（与普通行动相同） | `test_a_prevented_action_after_a_pivot_is_in_the_pivots_step` |
| C2 | 同上，"出招前已倒下"与"被弹出"两种也没有顺序号 | 倒下记顺序；弹出取弹出换人的顺序 | `test_a_faint_or_an_eject_after_a_pivot_is_in_the_pivots_step` |
| C3 | 实战路径落后：Eject Button 已发动、换人行还没出现时（就是那个换人决策点），实战历史里没有"被弹出"，训练历史（日志里后来有换人）和搜索树都有 | 解析器把等待中的弹出交出来，算作被弹出 | `test_an_eject_before_its_switch_is_already_a_blind` |
| C4 | 训练路径丢信息：被 Revival Blessing 复活、后来再次倒下的宝可梦，整局解析只记最后一次倒下，第一次的"出招前已倒下"丢了 | 记下每次倒下 | `test_a_revived_mons_first_faint_is_a_blind` |

检测框架本身的一处：回放日志没有 `|title|` 行，poke-env 不知道对手用户名，实战函数里扮演对手的 shadow battle 拿错了一方（本地 Showdown 实战时会发这一行，不受影响）；检测器从 `|player|` 行补上。

**B2：搜索树内扩展的历史 = 日志随后给出的历史。** 根以下，搜索按树里走的步骤扩展历史（`rust/alpha_search` 的 PathCtx：`push` / `settle`）。`alpha_search.tree_steps` 对一次联合行动的每个结果分支给出树会记下的那一步，并用同一个 `Act::parse` 解析日志那一步；`scripts/check_tree_history.py` 在 A 的随机对局上，对每个双方都做了选择的回合，比较两者。结构字段（行动类型、太晶、出手者、目标、被阻止、先倒下）必须与某个分支一致；结果字段单独统计。

| 日期 | 数据 | 结果 |
|---|---|---|
| 10-23 | 40 局，1,342 步 | 结构字段约 2.6% 的步对不上 |
| 10-24 | 修复后：同样 40 局 | 0 |
| 10-24 | 40 组 fixtures 各 50 局（新种子，偏移 7000），2,000 局 64,098 步（跳过分出胜负的最后一回合：最后一击之后的招式永远不会出，引擎照样推演；之后没有任何输入） | 首轮约 2.6% 的步；修复 T1–T10、C6–C9 后 **151 步（0.24%）**，全部是下面"已知、未修"的三类（Illusion、Minior 的核心颜色、Revival Blessing），另两步不是历史的问题（Metronome 随机召出的招；引擎按平均伤害算，混乱自伤在所有分支里都倒下） |

树一侧的修复（`rust/alpha_search` 的 PathCtx，`features::entry_forme`；引擎加了只给树读的无操作标记 `Turn` / `HitItself` / `NoTarget`，比较指令时与 `Acted` 一样滤掉，引擎 cargo 229 不变）：

| # | 问题 | 修复 |
|---|---|---|
| T1 | 锁定 / 蓄力中的回合（Outrage 之后的回合、Phantom Force / Meteor Beam 的第二回合）：日志的招式行带 `[from]lockedmove`，不算行动；树记成出招 | 选招时已锁定（`LOCKEDMOVE`、`active_is_charging_move`）：出了招记空，被阻止 / 先倒下照常 |
| T2 | 需要休息的回合：日志 `cant … recharge`（被阻止），先倒下则"先倒下"；树写空 | 休息回合按待定的招式处理：引擎在它轮到时发 `Turn` |
| T3 | Encore 在本回合改变了实际出招：日志记实际用的招，树记选的招 | 取 `Acted` 之前扣 PP 的格位作为实际用的招，暴露位也按它 |
| T4 | 没有目标的招式（对方已被 Healing Wish 等打倒；引擎提前返回，没有 `Acted`）：日志是那招（失败），树当成被阻止 / 先倒下 | 扣了 PP 或引擎发 `NoTarget` 即算用了招；锁定中的（`[from]lockedmove|[notarget]`）记空 |
| T5 | 先行动的一方被冰冻 / 麻痹挡住、随后被对方打倒：日志"被阻止"，树看整步结束后的 HP 记成"先倒下"；被换人方先手、之后在回合末倒下的同理 | 引擎在这一方活着轮到自己的招式时发 `Turn`：有 `Turn` 而没出招 = 被阻止（之后倒下也是） |
| T6 | 混乱自伤：日志没有 `cant`，自伤倒下记"先倒下"，没倒下记空；树记成被阻止 | 引擎在自伤分支发 `HitItself` |
| T7 | 被 Whirlwind / Dragon Tail 拖下场、还没出招：日志空，树记被阻止 | 没有 `Turn`、还活着：空；但自己被弹出（Eject Button / Emergency Exit，一侧 `force_switch`）的是"被弹出"（被阻止） |
| T8 | U-turn 先手打倒了对方，对方的招式被存到换人之后：树记空，日志"先倒下" | 先看是否倒下 |
| T9 | Truant 偷懒的回合（引擎在倒下检查之前就返回）：树没有 `Turn` | 偷懒处也发 `Turn` |
| T10 | 出手者 / 换人目标的种族：日志（训练与实战的历史）用第一次见到时的名字——队伍预览隐藏的形态写基础种族（`Urshifu-*`、`Dudunsparce-*`、`Greninja-*`…，Showdown 的 onTeamPreview）、对战中才变的形态写变之前的（太晶后的 Ogerpon、Busted Mimikyu、Hero Palafin、Crowned Zacian…，Showdown 的 battleOnly）；树用引擎的当前形态 | `entry_forme` 映射回去 |

同时查出的解析器错误（训练和实战的历史都受影响，两边一致，所以 B1 看不出）：

| # | 问题 | 修复 | 测试 |
|---|---|---|---|
| C5 | 太晶后、出招前就被先制招击倒，它"待用的太晶"没清，下一只的下一招被记成太晶招 | 倒下时清 | `test_a_tera_whose_mon_fainted_first_is_no_later_mons` |
| C6 | 太晶后被挑衅挡住（`cant`），待用的太晶留到下一回合的招上 | 每回合开始清（太晶只属于本回合的招） | `test_a_tera_whose_move_was_stopped_is_no_later_moves` |
| C7 | Magic Bounce 把 Parting Shot 弹回，弹回者被换下（`switch …|[from] Parting Shot`），被当成它自己选的换人；它自己的招没了 | 带 `[from]` 的换人都不是选的（Showdown 的 switchIn 带来源效果）：算 pivot，没有自己的行动时为"被弹出" | `test_a_switch_a_bounced_parting_shot_made_is_no_chosen_switch` |
| C8 | 剩 1/307 HP（Focus Sash）四舍五入成 0%，下一回合开始被当成已倒下，出招前被打倒时没有"先倒下" | 活着至少 1% | `test_a_mon_left_at_one_hp_that_fainted_first_is_a_blind` |
| C9 | 锁定中的 Outrage 出了招（`[from]lockedmove`：不是决策，不算行动），之后被打倒：被记成"出招前已倒下"（没有自己的行动、又倒下了）；树记空，与其他锁定回合一样 | 解析器记下锁定招式的使用，`blind_sides` 把它当作有行动 | `test_a_locked_move_then_a_faint_is_no_blind` |

- 结果字段：**树里一律不填**（伤害、先手、击倒、未命中、暴击都是 0），训练历史里都有——网络在根以下的节点上看到的最近几步历史总是"没造成伤害"，与训练分布不同。补上会改变搜索的输入，须经搜索 A/B 才能采用（"Validate features with search A/B"），未改。
- 已知、未修（只影响树，不影响训练数据）：未识破的 Illusion（日志写伪装的名字，树写 Zoroark）和 Minior 的核心颜色（树写 Meteor 形态）——引擎状态里没有这个信息，要由根的 Context 带上每个格位在日志里的名字；Revival Blessing（Showdown 在复活时中途请求选择，引擎把对方的招存到选择之后，日志和训练历史里没有这一步）。
- 测试：`tests/test_tree_history.py`（14 局，每类问题出现过的对局：结构字段 0）；`ismcts.rs` 的 `the_tree_step_is_the_logs`。

## 统一转换层（计划 C）

- **读 poke-env 的一层**：`agents/pokeview.py`。poke-env 把自身的值和当前的值混在一起（变身后 `moves`、`base_stats`、`weight` 是目标的，有临时特性时 `ability` 是临时的），这是复查轮里反复出现的错误来源。这一层的每个函数都写明读的是哪个：`own_*`（自身的、配置里的）和 `current_*`（现在在对战中的）——`own_moves` / `current_moves`、`own_base_stats`、`own_weight`、`own_stats`、`own_ability` / `current_ability`、`engine_ability`（引擎用的：临时的优先）、`copied_ability`、`copied_pp`、`last_used_move`。`agents/engine_state.py` 原来的同名辅助函数搬过来，直接读取都改成调用它们（行为不变）。
- **检查**：`tests/test_pokeview.py` 用 AST 扫 `engine_state.py`：`moves`、`ability`、`base_ability`、`base_stats`、`stats`、`weight`、`temporary_ability` 等只能在引擎 / 配置对象上读（列出的接收者，逐个确认过不是 poke-env 的宝可梦；同名的引擎对象改了名：`engine_mon`、`em`、`setter`）。新加一处直接读取就会失败。
- **动作的唯一表示**：`agents/slots.py`。动作的名字（引擎选项名："earthquake"、"earthquake-tera"、"switch greattusk"、"struggle"）是网络的槽位、搜索的标签、对战指令之间唯一的中间表示；槽位只在 Rust 里算（`features::slot` / `slot_in`），Python 按名字在 `slot_names` 里查。训练数据（`train/positions`）原来自己再算一遍（招式下标 + 4 表示太晶、8 + 队伍下标表示换人，不管是不是合法选项），已删除；`engine_move_to_order` 改为 `slots.order_of` 的别名。
- **往返检查**：A 的每个决策点（`enginecheck/statebuild.option_diffs`）：构造状态的选项名集合 = 真实状态的（Greninja-Bond 按 Greninja 比，与比较器一致）；每个选项名都能转成这场对局的指令。基线测试钉住它的类别。

| 日期 | 数据 | 结果 |
|---|---|---|
| 10-24 | 训练样本的槽位，新旧两种算法，1,000 局真实回放、52,886 个样本 | 13 个（0.025%）的动作不是我们状态里的合法选项，10 个是抽样出的不可能配置（下面 P1）；修复后 3 个（Illusion、被 Trick 换来的 Assault Vest），按名字查找时丢掉（原来照样给槽位，网络学着把概率放在被屏蔽的槽位上） |
| 10-24 | A 的往返检查，120 局 8,683 个决策点 | 选项集合全部一致；转不成指令两类：Greninja-Bond（P2）、Uproar 锁定（引擎缺口，见 D） |

| # | 问题 | 修复 | 测试 |
|---|---|---|---|
| P1 | 抽样出携带 Assault Vest 却会变化招式的配置（原型的道具和招式分开抽）：回放里我方 Slowking-Galar 已知 Toxic / Future Sight / Sludge Bomb，抽到 Assault Vest，它实际用了的 Toxic 不是选项；实战给对手抽样同样会这样 | 已知变化招式时不抽 Assault Vest；持有 Assault Vest 时补抽的招式不含变化招式；伤害后验选道具时同样 | `tests/test_sample_set.py`（没有这条检查时 3,000 次抽到 4 次） |
| P2 | 实战：搜索选了换上 Battle Bond Greninja（引擎名 "greninjabond"），poke-env 按日志叫它 "greninja"，转不成指令，退回次优 | 按名字找不到时按前缀找唯一的一只（Species Clause 保证同一队基础种族不重复） | `test_a_switch_order_by_the_engines_forme_name` |

数据源：Radical Red 服务器的回放（改版游戏的 Gen 9 OU，自己的种族、能力值和招式；约 1,000 局，三分之一含图鉴里没有的种族）从训练数据构建中排除（`scripts/build_training_data.py`）。

## 差分测试框架查出的（10-24）

`doc/difftest.md` 的框架（场景 + 链式引擎差分 + 信念真值检查 + 变异测试）第一轮在 `full` 语料上查出、已修的：

| # | 问题 | 影响 | 修复 | 守住它的 |
|---|---|---|---|---|
| S154 | 变身中的宝可梦体重取了目标"现在"的形态（Imposter Ditto 复制了已 Tera Shift 的 Terapagos，16 kg，我们给它的基础形态 6.5 kg；目标之后太晶成 Stellar 形态，又给了 77 kg）。Showdown 的 transformInto 在变身那一刻复制体重 | 训练数据 | 计时器在 `-transform` 时记下目标当时的形态（`copied_forme`），体重按它 | 场景 `transform/imposter-into-a-forme`、`transform/target-forme-after`；变异两条 |
| S155 | 变身复制来的招式还没用过时 PP 一律当 5：Showdown 是 min(5, 招式的 PP)，Revival Blessing 是 1 | 训练数据（回放路径） | `pokeview.copied_pp` | `test_a_copied_moves_pp_before_its_first_use`；场景 `transform/copied-one-pp`；变异 |
| B1 | 速度观测用对方"现在"的道具解释：Switcheroo 拿到 Choice Scarf 的 Glalie，换手之前那几回合的先后被按围巾算，真实速度被排除（实战信念） | 实战搜索 | 观测记下当时的道具阶段（`Obs.item_then`，与 F1 共用 `damage_obs._Items`）；道具换过手时，原道具阶段的观测带上原道具（被揭示时），否则丢弃 | `test_an_observation_is_read_with_the_item_held_then`；场景 `speed/scarf-knocked-off`；变异 |
| B2 | 速度观测排除了真实速度（`full` 语料 990 个决策点，51 个对局视角 / 宝可梦）。逐个对照 Showdown 当回合的真实状态分类，全部是观测或推断读错了“当时”的值：我方道具按现在的（Trick 换走的 Choice Scarf，27 个）；对方的形态按现在的（Minior 的 Meteor / 核心、Eiscue 的 Noice，候选速度按当时形态的基础速度算：`Obs.base_spe`、`consistent` 的 `stat_of`）；变身中的任一方（速度是目标的）；Healing Wish 治好的麻痹（只体现在 `-heal` 的 HP 字段里，追踪器没看到）；被 Encore 在出手前换掉招式的后手（原选招式的优先级未知）；Mycelium Might 的变化招式、Stall（同优先级里最后出手）；Zoroark 的 Illusion（Showdown 的规则：换上时交换位置后，伪装成排在它后面、最后一只未倒下的宝可梦；`damage_obs._Illusion` 按队伍预览与换人算出每次上场是否可能是它，可能的那段不用）；我方形态和现在不同的回合（我方努力值不在 poke-env 里） | 实战信念（速度抽样、F1 的速度过滤） | `agents/speed.py`、`engine_state.py`（两处 `consistent` 传 `stat_of`） | `tests/test_speed.py` 6 个；场景 `belief/*`（百分比格式）；信念检查的速度：990 → 0；变异 |
| B3 | F1 的伤害证据排除了真实配置（57 处）：Pain Split 的 `-sethp` 没更新命中前的 HP；变身中的 Ditto 的命中（能力值是目标的；候选能力值也改用自己的基础能力值 `own_base_stats`）；在另一形态打出的命中（Palafin-Zero，按昵称认作同一只）；Zoroark 的 Illusion（被识破前的命中作废，我方的也是；可能是伪装的上场不用：同 B2 的 `_Illusion`）；Stakeout 对本回合换上的目标（`set_damage_rolls` 给防守方的是 Splash：引擎的 Stakeout 看防守方是否换人）。另：检查本身在状态构造失败时是静默的（`decisions` 的错误没并入），已修：一处 `active_index` 的类型错误曾让每个命中都失败 | 实战信念（F1） | `agents/damage_obs.py`、`alpha_search` 的 `set_damage_rolls`、`enginecheck/beliefcheck.py` | `tests/test_damage_obs.py` 4 个；场景 `belief/*`；信念检查的伤害：57 → 0；变异 |
| S156 | 已太晶的宝可梦用 Double Shock：Showdown 的 `setType` 失败、属性不变，但仍打印 `-start|typechange|Electric`（太晶属性），poke-env 照此把属性改成电系，我们的状态丢了格斗属性——引擎按原属性给本系加成，Close Combat 少 1.5 倍（搜索里的伤害也是）。未太晶时 Double Shock 的 `???` 在 poke-env 里叫 THREE_QUESTION_MARKS，我们原样传给引擎，真值是 typeless。状态比较器原来根本不比较 `types` / `base_types`，现在比较（按集合） | 实战、训练数据 | `engine_state.py`（太晶后无效的属性变化恢复原属性；`_types` 的 `???`） | 状态检查比较属性（两条路径 0）；场景 `types/doubleshock-*`；变异 |
| B4 | 信念先验的支撑（软约束 8,623 处）。按原因分三类：A 物种不在 gen9ou 统计里（约 91%，测试语料的随机对战队伍）；B 物种在 OU、这个值没人用过（约 3%）；C 统计里有、抽样时却是 0（约 5%）——两个真问题。C1：表格名在 Smogon 统计里另有键（Maushold-Four 记在 Maushold 下），最底层查空；回退到种族值与属性完全相同的形态（`priors._same_in_battle`；不把 Tauros-Paldea-Combat 当关东 Tauros）。另：检查的太晶支撑用了 poke-env 的物种 id，不是抽样用的表格名（检查自己的错）。C2：套路原型从人类对局挖出，对局只显示会暴露自己的道具（Leftovers、Rocky Helmet、Focus Sash……），Heavy-Duty Boots、Soul Dew 几乎从不出现；太晶属性只在用了才显示。抽样按原型权重抽道具 / 太晶：Latias 的 Soul Dew（统计 36%）、Cramorant 的 Boots（25%）从来抽不到。改为原型权重与基础边缘分布（带队伍先验与 Smogon 统计各一半）混合，`ARCH_MIX` = 0.6；F1 的候选道具先验同一个基础分布。在本地 1,170 支论坛完整 OU 队伍上评估（暴露两个招式）：道具 NLL 1.93 → 1.65、top-1 0.48 → 0.51、真值为 0 的比例 5.6% → 1.2%；太晶 NLL 2.49 → 2.14、为 0 的 12% → 3.3% | 实战信念（搜索的世界、F1） | `engine_state.base_marginal` / `arch_mix` / `sample_set`、`damage_obs._candidates`、`belief/priors.py`；单边开关 `ALPHA_ARCH_MIX`（0 = 旧信念，A/B） | `test_an_item_replays_never_show_is_drawn`、`test_a_cosmetic_formes_prior_is_its_base_species`；信念检查软约束 8,598 → 8,047；变异；搜索 A/B（v6-h 对 v6-h，1,600 次迭代，wide1000 590 对后停）paired 49.3% ± 2.4%：持平 |
| B5 | 2026-10-25 review（用 Showdown 的真实日志复现）：值在“另一只”身上改变时，阶段没跟上。一是 Magician / Covet / Bestow 只打印拿到道具一方的 `-item … [of] 失主`，失主没有 `-enditem`（Showdown 的 takeItem 不打印）：Choice Scarf Latios 先手的回合被按无道具解释，真实速度被排除（F1 同理）。二是 F1 用现在的特性解释过去的命中：Huge Power Azumarill 打出伤害后被 Skill Swap 换成 Synchronize，候选只剩 Synchronize，真配置落到下限。三是 Lingering Aroma / Mummy 的实际格式是 `-activate|持有者|ability: X|接触者|[ability] 旧特性`，没有 `-ability` 行：状态里 Azumarill 仍是 Huge Power。四是信念检查直接代入真实特性、绕过 `_candidates`，Skill Swap 场景零发现。顺带：速度观测也用现在的特性（我方 Skill Swap 走了 Slow Start、对方被换上 Slow Start）；Role Play / Entrainment 的 `[of]` 是来源，它自己的特性没变，却被记成换过（Regenerator 换下不回血） | 实战搜索（F1、速度、状态） | 失主的道具阶段（`_Items`）；特性阶段 `damage_obs._Abilities`（按 Showdown 的 setAbility / skillSwap：`-ability 新 旧 [from]`、Mummy / Lingering Aroma 的 `-activate`、Skill Swap（含 Wandering Spirit）、`-endability`；换下即恢复），每次命中记 `Hit.ability_then`，候选按初始特性（日志给出时就是它，未知时按物种的分布，`species_ability_probs`）；速度观测的快照记双方当时的特性；`timers` 处理 Mummy / Lingering Aroma 的 `-activate`，Role Play 的 `[of]` 不再标记；信念检查经 `_candidates` 取候选，真实初始特性不在其中时报硬约束 `belief:candidates` | `test_a_takers_victim_lost_its_item`、`test_each_hit_is_explained_with_its_ability_then`、`test_a_contact_with_lingering_aroma_or_mummy_changes_the_hitters_ability`、`test_each_turn_read_with_the_abilities_then`；场景 `belief/magician-scarf`、`belief/skillswap-after-hit`、`belief/lingeringaroma-contact`、`belief/mummy-contact`、`belief/slowstart-swapped-*`、`abilities/*`；变异 |
| B6 | 信念先验的支撑（B4 之后软约束 8,047 处）。A：物种不在 gen9ou 统计里（约 91%）——整个先验为空；B：物种在 OU、这个值没人用过（约 3%）——永远抽不到，证据也救不回来 | 实战搜索（对手的冷门配置） | A：回退先验 `SmogonPrior.fallback`（Showdown 随机对战的招式池 / 太晶属性，没有时按 Gen 9 学习表与全部属性；道具用 OU 全体的道具分布 `global_item`，旧 pickle 由统计文件补算）；B：`base_marginal` 下垫 `FLOOR = 1e-3`（OU 全体道具 + 专属道具 `signature_items`、全部太晶属性），招式下垫学习表其余招式（`_move_floor`）；形态必需的道具（`required_item`，Zamazenta-Crowned、Ogerpon 面具）直接确定 | `test_sample_set.py`（回退先验、下限）；信念检查软约束 8,047 → 0；变异；搜索 A/B（2026-10-25，`42a5a7f`，C2 + B6 + B7 对 `ALPHA_ARCH_MIX_B=0`，v6-h，1,600 次迭代）：wide1000 600 对 **51.3% ± 2.5%**，ab600b 190 对后停 48.6% ± 4.5%：持平，0 失败 / 0 回退 |
| B7 | 2026-10-25 复查 B5 / B6 / 框架修复（独立复查）：速度观测在回合结束时才取"我方现在的上场者"作特性的键（濒死替补已在场：草稿里 Prankster 的回合按别的宝可梦的特性读，留下了）；Illusion 被识破的 `replace` 没进 `ability_changes` / `item_changes` / 速度观测（变化记在伪装对象名下，候选只剩 Illusion）；`--only` 不写基线时也因 `#compared` 变少报回归；信念检查的招式支撑自己重算（并进整张学习表），没走采样器——改走 `engine_state.move_weights` 后查出 `_move_floor` 跳过权重为 0 的招式（原型词表里多数招式是 0：那一原型永远抽不到，full 语料 10 处）；回退先验不受 mix 0（A/B 的旧信念）控制；OU 全体道具给任何物种 Booster Energy（7%）、Ogerpon 的面具（4%）；Arceus 形态的必需道具在 `requiredItems`（复数）；`test_l3b` 放宽后过弱 | 实战搜索、信念检查、差分框架 | `snap["our_key"]`；三处跟随 `replace`；`regressions(subset=)`；`move_weights`（采样器与检查共用），`_move_floor` 按权重 ≤ 0；`priors.FALLBACK`（`_prior` 按 mix 设定）；`items_for`（专属道具只给其主人，Booster Energy 只给 Protosynthesis / Quark Drive）；`standard_items`；`test_l3b` 加两个确定的世界（对手已公告的 Air Balloon 5 回合、我方 Terrain Extender 8 回合） | `test_our_ability_then_is_the_snapshots_mon`、`test_an_illusions_changes_are_the_real_mons`（Showdown 真实日志）、`test_the_fallback_is_off_at_mix_0`、`test_a_species_gets_only_the_items_it_can_use`、`test_an_arceus_formes_plate_is_its_item`、`test_the_move_floor_lifts_a_0_weight`、框架测试的 `--only`；变异 `B6 the moves' floor` |
| B8 | 2026-10-25 复查（Showdown 真实对局复现）：一是对方原特性未知时被设成别的特性（Worry Seed、Entrainment、Simple Beam、Role Play、Doodle、Trace；Mummy / Lingering Aroma），poke-env 把第一次见到的新特性当成它的原始特性——当前特性对，换下后（搜索里）仍是 Insomnia，Showdown 已恢复 Huge Power；先知模式的 state 检查用真实配置，看不见。二是 Sleep Talk 调出的 Rollout 被构建成锁定（rollout 1，换人和太晶被拿掉）：Showdown 的 onModifyMove 在使用者睡着时不加状态，引擎侧有这个条件，`timers` 的规则漏了（实战、回放两条路径） | 实战搜索、训练数据 | `poke_env_fixes._ability_set`：这类行给出的旧特性在原始特性未知时就是原始特性，新特性为临时特性；`timers`：Rollout 按出招当时是否睡着 | `test_an_ability_set_over_an_unknown_one_keeps_it_as_its_own`（Worry Seed、Mummy；非先知的 `built_state`）、`test_a_sleep_talks_rollout_locks_nothing`（双方视角）；场景 `ends/sleeptalk-rollout`；变异（Sleep Talk 1；原始特性那条先知模式下抓不到，待非先知的检查） |
| S157 | Terapagos-Stellar 的 Stellar 加成被记成“每种属性一次”：Showdown 的 `species.name !== 'Terapagos-Stellar'` 时才记录（它每次都加成），引擎也是；我们从日志里给它记上了用过的属性，之后的加成少算。`state_chain` 查出（state 检查不比较这个字段） | 实战搜索、训练数据 | `engine_state._counted`：Terapagos 不记 | 场景 `transform/target-forme-after`（`state_chain`）；变异 |
| S158 | `state_chain` 首次跑 full 语料（2026-10-25）查出的构建缺口，待逐类修：我们的状态从不填性格（引擎在形态变化重算能力值、混乱果时要用：Palafin-Hero、Terapagos 的能力值差几点，混乱果从不让人混乱；7,513 处）；未上场的 Zacian / Zamazenta-Crowned、Urshifu 等按基础形态构建（能力值、属性、体重都错）；对手的 Choice 锁定疑似没传（可选项多出，约 370）；我方待生效的 Healing Wish 没传（132）；未上场对手的等级（49）；先知注入个别没对上（招式顺序、太晶属性、最大 HP，约 60，含我方一只的招式顺序）；对手 PP 少 1（37）；零散若干 | 实战搜索、训练数据 | 待修（`design.md` TODO“差分框架补强”） | `state_chain` 的基线 |

## 效果开始时定下的值（计划 D）

Showdown 里有一类值在效果开始的那一刻就定下，之后不再随状态变化：`durationCallback`（持续回合按开始时的道具 / 特性）、`onStart` 里写进 `effectState` 的值（替身的 HP、Wish 的回复量、锁定的招式……）。还原时如果按"现在"的状态去算，就会错（例如 Light Clay 的 Reflect 之后道具被打掉，剩余回合按 5 算——10-23 复查修过）。清单由 Showdown 源码扫出（`data/moves.ts`、`conditions.ts`、`abilities.ts`、`items.ts` 中所有 `durationCallback` 和对 `this.effectState.*` 的赋值，139 项），逐项对照我们的记法；"A 比较"指状态构造差分（计划 A）比较这个字段，百万级已到 99.999%。

| 值 | Showdown 在何时定下 | 我们 | A 比较 | 结论 |
|---|---|---|---|---|
| 天气 / 场地 / 屏障的回合数（Damp / Heat / Smooth / Icy Rock、Terrain Extender、Light Clay：8） | 开始时设置者的道具（`durationCallback`） | `timers.set_items`：设置那一刻记下设置者的道具；之后道具变化、被压制（Magic Room、Embargo）都按当时 | 剩余回合 | 一致 |
| Trick Room、Gravity、Magic / Wonder Room、Tailwind、Safeguard、Aurora Veil 的回合数 | `durationCallback` 只给第四代的 Persistent 加回合 | 固定回合 | 剩余回合 | 第九代无关 |
| Taunt 的回合数 | 开始时目标本回合已行动则 +1（`onStart`） | `taunt = -1`（已行动时） | 剩余回合 | 一致 |
| Heal Block 的回合数 | Psychic Noise 2，其余 5 | 引擎只有 2（只有 Psychic Noise） | 有无 | 引擎限制，第九代只有 Psychic Noise |
| Wish 的回复量 | 使用者最大 HP 的一半（使用时）、生效回合 | 记下使用者和回合，按使用者的最大 HP | Wish | 一致 |
| 替身的 HP | 开始时最大 HP 的 1/4 | 同 | 有无（挨过打后剩多少玩家无从得知） | 一致 |
| Encore / Disable / 讲究锁定的招式 | 开始时（`onStart: move`） | 计时器记下当时的招式 | 是 | 一致 |
| Stockpile 的层数和实际提升的防御 / 特防 | 每层开始时记下实际提升的级数（`effectState.def / spd`），Spit Up / Swallow 撤销这么多 | 层数（`-start stockpileN`）；引擎撤销的级数等于层数 | 层数 | 层数一致；**引擎缺口**：在 +6 时叠的那层没有提升，Showdown 不撤，引擎照撤（少见） |
| Protosynthesis / Quark Drive 提升哪一项、是否来自 Booster Energy | 激活时的最高能力、来源 | `frombooster`；提升哪一项由 `-activate` 的能力名给出 | 是 | 一致 |
| Metronome 道具的连续次数 | 每次使用时 | `consecutive`、`metronome_gone` | 是 | 一致 |
| Slow Start 的剩余回合 | 出场时 5 | `slowstart` | 是 | 一致 |
| Supreme Overlord 的倒下数 | 出场时（`onStart: fallen`） | 当前倒下数 | 是 | 单打里在场期间队友不会倒下，等于出场时的数 |
| 剧毒的层数、连续 Protect 的计数、Future Sight 的回合与格位 | 开始时 / 每次 | 计时器 | 是 | 一致 |
| 混乱、睡眠、连续招式（Outrage）、束缚的长度 | 开始时随机 | 只记有无与已过的回合 | 有无 | 隐藏信息，引擎按概率展开 |
| 束缚的回合数和伤害（Grip Claw：8 回合；Binding Band：1/6） | 开始时施放者的道具（`durationCallback`、`boundDivisor`） | 引擎固定 5 回合、1/8 | — | **引擎缺口**（未建模） |
| Fury Cutter / Echoed Voice 的倍率、Rollout / Ice Ball 的段数 | 每次连续使用时累加 | 引擎只有招式数据 | — | **引擎缺口**（未建模；这些招在 OU / 随机对战里少见） |
| Laser Focus（下一回合必定会心） | 开始时 | 引擎有 volatile，没有必定会心 | — | **引擎缺口** |
| Uproar 的锁定（3 回合，期间被困住、不能换人） | 开始时 | 引擎只有 volatile，不锁定、不困住：会给出换人选项（C 的往返检查查出：这时转不成指令） | — | **引擎缺口** |
| Magic Coat 的 Prankster、Roost 的属性、Counter / Mirror Coat 的伤害、Focus Punch / Shell Trap、Helping Hand、Opportunist / Mirror Herb / White Herb 的能力变化、Eject Pack | 本回合 / 当下 | 不跨决策点 | — | 无需还原 |
| Dragon Cheer、Ally Switch、Dynamax、G-Max、Bide | — | — | — | 双打或非第九代 |

结论：跨决策点、我们需要还原的值都按事件发生时记下，A 的百万级差分覆盖了其中可观察的部分；剩下的是引擎没有建模的几项（束缚的道具、连续使用的倍率、Laser Focus、Stockpile 在 +6 时的那层），属引擎缺口，按"引擎问题先写双测试"的规则另行处理（另：C 的往返检查查出 Uproar 的锁定，也是引擎缺口）。

## 复查（10-24）

外部复查查出的 5 处（各有确定性场景复现），都已修复：

| # | 问题 | 影响 | 修复 | 测试 |
|---|---|---|---|---|
| R1 | 树内历史取"实际用的招"时看本步第一个扣这一方 PP 的指令：对方先手的 Eerie Spell（及 Spite）扣掉的上一招 PP 被当成这一方用的招（Roost 记成 Brave Bird），这一方被阻止时还会被当成用了招 | 搜索 | 只看这一方自己出招的区间：它的 `Turn` 到它的 `Acted`（没有 `Acted` 时到对方的下一个 `Turn`） | `ismcts.rs` 的 `a_foes_eerie_spell_is_not_the_targets_move`（修复前失败） |
| R2 | F1 的伤害证据：道具换手（Trick）之后，用现在的道具解释换手之前的命中（Choice Specs 的 Surf 按 Life Orb 算，真实特攻被排除） | 实战搜索的信念（回放路径不用 F1） | `damage_obs.item_changes`：换手前的道具（Trick / Switcheroo：对方收到的那个；Thief / Covet / Magician / Pickpocket：没有道具），候选按它；不知道时用信念的候选，不用现在的道具 | `tests/test_damage_obs.py` |
| R3 | 变身结束后体重仍是复制目标的（poke-env 换下不恢复）：Ditto 复制 Copperajah 换下后 650 kg，Showdown 4 kg。另：形态改变时体重是新形态的（Minior 的 Meteor 40 kg，核心 0.3 kg），我们一直按出场形态 | **训练数据**（0.9% 的局有变身者换下又上场） | `pokeview.own_weight` 一律按自身种族；`_formes` 改形态时一并改体重；差分加比较体重和变身备份里的体重（以前不比，所以漏了） | `test_a_mons_own_weight_after_its_transform_ended`；12 局含 Ditto 的对局：修复前 474 处体重差异，修复后 0 |
| R4 | 延长道具被 Klutz 抵消的判断看设置者现在的特性：设下日照后被 Skill Swap 换成 Regenerator，Heat Rock 被算成生效（剩 7 回合，Showdown 4） | 训练数据（极少） | 计时器在设置时记下设置者被招式 / 特性改变后的特性（`set_ability`，Court Change 时一起交换）；没有改变过就是它自己的特性 | `test_a_klutz_setters_weather_is_not_extended_after_its_ability_changed`（设置后变、设置前变两种） |
| R5 | 引擎的 Spite 不扣 PP | 搜索 | 见 `doc/engine-diff.md` L233 | 双测试两个 |

第二轮复查（同日）指出上面三处修得不完整，都是只修了报告的那条路径、没有按机制修：

| # | 遗漏 | 修复 | 测试 |
|---|---|---|---|
| R5' | 引擎只在"已知会读上一招"的机制在场时才跟踪上一招（Encore、Fake Out、Metronome 道具、Cursed Body…），Spite 不在列表里：没有别的触发时 Spite 读到的上一招是换上场，不扣 PP。R5 的测试恰好带了 Cursed Body，掩盖了它。列表之外还有读上一招的边缘逻辑（讲究锁定 / 挣扎 / 一意孤行的 L228、L232 情形），开关关着时在树里读到根节点的旧值——单步差分从真实状态出发，根节点的值是对的，所以测不出 | 一直跟踪（`set_last_used_move_flag`）；代价约 4% 的搜索迭代（每秒 14.5 万 → 13.9 万，56 个局面） | `test_spite_after_its_targets_move_in_the_same_turn`（Infiltrator Spiritomb，无其他触发，修复前 23 vs 19）；R1 的 Rust 测试去掉手动打开的开关 |
| R2' | 一个"换手前的道具"不能解释跨多个道具阶段的命中：Choice Specs 命中 → 被 Knock Off → Magician 拿到 Assault Vest，换手前道具记成 none，戴眼镜的命中按无道具算 | `damage_obs._Items`：每只宝可梦的道具时间线（开局的道具——候选，被揭示时为揭示的那个；-enditem 后为 none；-item 换手后为日志写明的那个；Frisk / 宣告不算换手），每次命中记下当时的道具（`Hit.item_then`），换手后的命中也保留 | `test_each_hit_is_explained_with_its_own_items_phase` |
| R4' | 道具是否生效的快照漏了两条路径：已有道具快照（之后被 Knock Off）时直接返回，跳过了 Klutz 判断；Neutralizing Gas 在场时 Klutz 被压制，道具照常生效 | 设下时一并记下 Neutralizing Gas 是否在场（`set_gas`）；`set_with` 先做同一个判断（当时的特性是 Klutz 且没被毒气压制 → 道具无效），再取道具快照 / 现在的道具 | `test_a_klutz_setters_weather_after_its_item_is_gone_and_under_neutralizing_gas`（两种场景） |

复查回归中（新种子、两条路径各 1,000 局）又查出两处回放第三轮就有、一直没查的（新加的选项比较把第一处标为核心差异：多给了换人选项）：

| # | 问题 | 修复 | 测试 |
|---|---|---|---|
| S152 | 锁定中的 Outrage 打在 Endure 上（`-activate|…|move: Endure`：命中了，对方撑住）被当成"对方守住、招式没起作用"，锁定结束——第三回合的锁定没了，换人选项多给（我方实战的 request 其实说了） | 守住的判断不含 Endure（它只用于连续守住的计数） | `test_an_outrage_into_endure_keeps_its_lock` |
| S153 | Slow Start 从 `-start` 之后的第一个回合开始才倒数：Showdown 是"在场时间 > 0"就倒数，上一回合就在场、这回合用 Transform 复制来 Slow Start 的 Ditto 本回合末就减一（我们晚一回合） | 开始时若本回合不是刚上场，立即开始倒数 | `test_a_slow_start_copied_by_a_mon_in_since_last_turn_counts_down_at_once` |

另：C 的往返检查在已经混乱时悄悄结束的锁定上报了选项差异（比较器早已把这种锁定结束当作隐藏信息），选项比较同样排除（`_silent_lock_end`）。

## 后续

- 因果性检查（计划 B）：见上；B2 的结果字段待搜索 A/B；Illusion / Minior 的名字要由 Context 带上。
- 引擎缺口（计划 D）：束缚的 Grip Claw / Binding Band、连续使用的倍率、Laser Focus、Stockpile 在 +6 时的那层、Uproar 的锁定。
