# 局面构造差分：玩家视角还原的引擎状态 vs Showdown 真实状态

搜索的根状态和训练数据的输入，都是我们从玩家收到的协议（日志 + request）还原出来的引擎状态：poke-env 解析日志，`agents/timers.py` 数日志里的计数，`agents/engine_state.build_state` 拼成 poke-engine 的 `State`。引擎差分（`doc/engine-diff.md`）只验证"从真实状态出发，引擎的推演和 Showdown 一致"，**不验证这一步**：它直接用 Showdown 内部的完整状态构造引擎状态。这份文档追踪还原这一步的一致性。

## 结论（2026-10-23）

- 600 局真实 OU 对局（队伍目录的随机配对），45,219 个决策点：
  - v7.3 数据构建时的代码（`102e1fe`）：**42.6%** 的决策点至少一处不一致，其中 **10.5%** 落在核心字段（HP、异常状态、能力等级、招式与 PP、道具、特性、出场宝可梦、场地）；最大的一项是对方后备宝可梦的 HP（Regenerator 的回复、Zoroark 伪装期间的记账）。
  - 现在：**0.17%**（核心字段 0.02%）。
- 实战路径（request + 日志）已对照；回放路径（spectator，训练数据用的那条）共用 poke-env、计时器和大部分 `build_state`，它特有的部分（整局已知配置、回放里的 Illusion）**还未单独对照**，见"后续"。
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
  - 一个在混乱中结束的 Outrage 锁定（已经混乱时锁定结束不打日志）。
- **差分框架自身的修正**：回合结束后的换人决策（`|upkeep|` 之后、下一个 `|turn|` 之前），`engine_state` 推算 Future Sight / Wish 用的回合数要加一（引擎差分只比较回合开始，从未碰到）。
- **数据**：`data/teams/statebuild_catalog_pairs.jsonl`（1,176 支真实 OU 队伍随机配对，本地生成）、`tests/fixtures/random_battle_teams*.jsonl`（40 组，1.16 万对）、`data/teams/big/`（30 组，8.7 万对）。同一对队伍换种子就是新对局。
- **流程**：跑一批 → 按"出现在多少局里"排序 → 看例子（日志 + 两边的值）→ 对照 Showdown 源码确认规则 → 修 → 写针对性测试（修复前必须失败）→ 回归（全量测试 + 两个基线 + 引擎差分）→ 记入下表。

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

已知、待查：2 局里我方后备宝可梦每招都按 Pressure 多扣了 1 PP，日志里没有 Pressure。

已知、暂不修：伪装成 Pressure 宝可梦的 Zoroark 挨打时，poke-env 按 Pressure 多扣 1 PP（识破后才能知道，极少见）。

差分之前的复查轮（10-22 至 10-23，第六到第十轮）修的 Disable、延长道具、Sleep Talk 的 PP、变身链路、连续 pivot 的顺序等，见各自的提交和 `tests/test_engine_state.py`、`tests/test_transform.py`。

## 后续

- 规模：百万级决策点（进行中）。
- 回放路径（spectator）单独对照：训练数据的质量直接取决于它。
- 因果性检查：训练样本的历史 / 暴露信息必须等于截至该决策点的日志所能给出的（计划 B）。
- 统一转换层：poke-env 的"自身 / 当前"取值收拢到一层（计划 C）。
