# 局面构造差分：玩家视角还原的引擎状态 vs Showdown 真实状态

搜索的根状态和训练数据的输入，都是我们从玩家收到的协议（日志 + request）还原出来的引擎状态：poke-env 解析日志，`agents/timers.py` 数日志里的计数，`agents/engine_state.build_state` 拼成 poke-engine 的 `State`。引擎差分（`doc/engine-diff.md`）只验证"从真实状态出发，引擎的推演和 Showdown 一致"，**不验证这一步**：它直接用 Showdown 内部的完整状态构造引擎状态。这份文档追踪还原这一步的一致性。

## 结论（2026-10-23）

- 600 局真实 OU 对局（队伍目录的随机配对），45,219 个决策点：
  - v7.3 数据构建时的代码（`102e1fe`）：**42.6%** 的决策点至少一处不一致，其中 **10.5%** 落在核心字段（HP、异常状态、能力等级、招式与 PP、道具、特性、出场宝可梦、场地）；最大的一项是对方后备宝可梦的 HP（Regenerator 的回复、Zoroark 伪装期间的记账）。
  - 现在：**0.17%**（核心字段 0.02%）。
- 百万级（每轮约 108 万个决策点，OU + 40 组 fixtures + 30 组 big）：首轮 0.23% → 第七轮（新种子）**0.0010%**（11 个决策点），核心字段 **0.0002%**，即一致率 99.999%。
- 回放路径（spectator，训练数据用的那条）：第二轮（新种子）**0.011%**；`enginecheck/replaybuild.py`、`scripts/check_state_build.py --path replay`——按 `train/positions.py` 的方式从观战者日志构造（整局解析的 SpectatorSide），双方隐藏的配置都换成真实配置。首轮百万级 0.66% / 0.65% / 0.43%（OU / fixtures / big），修复 S143–S145 及比较框架后，例子局全部一致（见下）。未覆盖：真实天梯回放的 HP 是百分比（差分里是精确值）。原句：回放路径共用 poke-env、计时器和大部分 `build_state`，它特有的部分（整局已知配置、回放里的 Illusion）当时还未单独对照，见"后续"。
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

## 后续

- 规模：百万级决策点（第四轮进行中）。
- 回放路径（spectator）单独对照：训练数据的质量直接取决于它。
- 因果性检查：训练样本的历史 / 暴露信息必须等于截至该决策点的日志所能给出的（计划 B）。
- 统一转换层：poke-env 的"自身 / 当前"取值收拢到一层（计划 C）。
