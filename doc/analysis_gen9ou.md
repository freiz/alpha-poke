# gen9ou replay 分析报告

生成时间：2026-10-04 16:04；脚本 `scripts/analyze_replays.py`。

## 1. 数据概况

- 对局数：**8100**（2026-07-06 ～ 2026-10-04），队伍数 16200
- replay `rating` 字段：最小 1740，中位 1786，最大 2049
- 回合数：中位 26，平均 31.7，90% 分位 52
- p1 胜率 50.8%；无胜者 9 场
- 赛前评分差 ≥50 时，评分高的一方胜率 **41.5%**（n=3967）

> **选择偏差**：下载按 `rating` 字段从高到低进行，而该字段接近双方赛后评分中较低者，
> 因此优先选中了"低分方获胜、评分上涨"的对局（上面那个低于 50% 的数字就是症状）。
> 胜率类结论都受此影响，只能作参考；使用率、搭配、配招类统计受影响较小。

## 2. 使用率、首发率与胜率

对照：Smogon 2026-09 使用率统计（门槛 1825）。

| # | 宝可梦 | 出现率 | Smogon | 首发率 | 上场率 | 胜率（95% CI） |
|---|---|---|---|---|---|---|
| 1 | Great Tusk | 34.4% | 31.8% | 10.2% | 92.2% | 50.2% ±1.3 |
| 2 | Kingambit | 31.6% | 34.3% | 2.0% | 85.9% | 50.0% ±1.4 |
| 3 | Gholdengo | 27.5% | 20.6% | 8.1% | 91.3% | 48.9% ±1.5 |
| 4 | Ogerpon-Wellspring | 23.1% | 21.8% | 24.7% | 93.2% | 51.4% ±1.6 |
| 5 | Zamazenta-* | 21.6% | 22.1% | 9.8% | 87.7% | 48.9% ±1.7 |
| 6 | Dragonite | 21.5% | 20.5% | 2.5% | 87.0% | 50.0% ±1.7 |
| 7 | Kyurem | 20.1% | 17.7% | 33.8% | 94.2% | 49.7% ±1.7 |
| 8 | Raging Bolt | 17.8% | 15.5% | 10.9% | 87.2% | 50.1% ±1.8 |
| 9 | Samurott-Hisui | 15.8% | 17.0% | 26.2% | 95.6% | 50.0% ±1.9 |
| 10 | Slowking-Galar | 15.7% | 16.0% | 21.5% | 96.2% | 49.3% ±1.9 |
| 11 | Iron Valiant | 15.4% | 18.1% | 8.3% | 87.3% | 49.5% ±2.0 |
| 12 | Cinderace | 14.9% | 13.7% | 13.7% | 92.6% | 51.7% ±2.0 |
| 13 | Glimmora | 14.8% | 21.1% | 25.8% | 96.0% | 50.9% ±2.0 |
| 14 | Gliscor | 13.8% | 10.5% | 46.5% | 95.5% | 51.8% ±2.1 |
| 15 | Landorus-Therian | 13.6% | 19.4% | 21.9% | 95.3% | 50.1% ±2.1 |
| 16 | Corviknight | 11.4% | 10.0% | 2.4% | 91.4% | 51.0% ±2.3 |
| 17 | Iron Moth | 11.2% | 8.8% | 5.4% | 91.2% | 48.6% ±2.3 |
| 18 | Ting-Lu | 11.2% | 9.5% | 21.7% | 95.1% | 48.3% ±2.3 |
| 19 | Moltres | 10.9% | 5.9% | 7.3% | 92.9% | 49.6% ±2.3 |
| 20 | Dragapult | 10.8% | 15.1% | 28.6% | 92.3% | 48.8% ±2.3 |
| 21 | Ceruledge | 10.3% | 7.1% | 5.1% | 88.6% | 52.8% ±2.4 |
| 22 | Iron Treads | 10.3% | 11.7% | 25.2% | 94.7% | 49.2% ±2.4 |
| 23 | Cresselia | 10.2% | 9.4% | 2.5% | 87.7% | 51.1% ±2.4 |
| 24 | Darkrai | 9.2% | 9.3% | 31.5% | 93.0% | 51.1% ±2.5 |
| 25 | Hatterene | 8.6% | 8.8% | 13.5% | 94.1% | 49.1% ±2.6 |

**最常见首发**：Kyurem 6.8%、Gliscor 6.4%、Ogerpon-Wellspring 5.7%、Samurott-Hisui 4.1%、Glimmora 3.8%、Great Tusk 3.5%、Slowking-Galar 3.4%、Dragapult 3.1%、Araquanid 3.0%、Landorus-Therian 3.0%、Darkrai 2.9%、Iron Treads 2.6%

## 3. 核心搭配（lift 最高的组合，出现 ≥150 次）

lift = 实际共同出现次数 ÷ 独立时的期望次数，越高说明越是刻意的搭配。

| 组合 | 次数 | lift |
|---|---|---|
| Excadrill + Tyranitar | 277 | 37.0 |
| Hydrapple + Jolteon | 402 | 23.2 |
| Slither Wing + Venusaur | 207 | 20.0 |
| Ninetales + Venusaur | 376 | 18.2 |
| Hawlucha + Rillaboom | 194 | 17.9 |
| Lokix + Ursaluna | 156 | 14.7 |
| Clodsire + Toxapex | 667 | 13.1 |
| Alomomola + Lokix | 360 | 13.1 |
| Ninetales + Walking Wake | 818 | 12.5 |
| Venusaur + Walking Wake | 393 | 12.4 |
| Dondozo + Toxapex | 775 | 12.0 |
| Ninetales + Slither Wing | 249 | 11.7 |
| Clodsire + Dondozo | 645 | 11.6 |
| Blissey + Toxapex | 505 | 9.8 |
| Blissey + Dondozo | 552 | 9.8 |
| Jolteon + Moltres | 402 | 9.1 |
| Slither Wing + Walking Wake | 293 | 9.0 |
| Blissey + Clodsire | 355 | 8.0 |
| Iron Crown + Lokix | 172 | 8.0 |
| Iron Crown + Ursaluna | 157 | 7.7 |

## 4. 队伍类型（按物种组成聚类，k=24）

"特征"= 在该类中常见且明显多于整体平均的宝可梦。名字需要人工或 LLM 解读。

| 类 | 队伍数 | 胜率 | 特征 | 常见成员 |
|---|---|---|---|---|
| 17 | 1557 | 50.5% ±2.5 | Cinderace, Kyurem, Slowking-Galar, Landorus-Therian | Kyurem, Cinderace, Slowking-Galar, Kingambit, Ogerpon-Wellspring, Landorus-Therian |
| 16 | 1295 | 52.9% ±2.7 | Glimmora, Ceruledge, Ogerpon-Wellspring, Raging Bolt | Glimmora, Ogerpon-Wellspring, Ceruledge, Raging Bolt, Kingambit, Zamazenta-* |
| 4 | 1272 | 50.6% ±2.7 | Samurott-Hisui, Gholdengo, Dragonite, Great Tusk | Gholdengo, Dragonite, Great Tusk, Samurott-Hisui, Kyurem, Glimmora |
| 22 | 1038 | 53.3% ±3.0 | Toxapex, Dondozo, Gliscor, Clodsire | Gliscor, Toxapex, Corviknight, Dondozo, Clodsire, Blissey |
| 9 | 991 | 49.8% ±3.1 | Iron Treads, Zamazenta-*, Moltres, Wo-Chien | Iron Treads, Zamazenta-*, Raging Bolt, Ogerpon-Wellspring, Moltres, Samurott-Hisui |
| 1 | 963 | 48.7% ±3.2 | Ogerpon, Gliscor, Pecharunt, Moltres | Gliscor, Ogerpon, Moltres, Pecharunt, Samurott-Hisui, Garganacl |
| 2 | 820 | 53.8% ±3.4 | Ninetales, Walking Wake, Venusaur, Great Tusk | Ninetales, Walking Wake, Great Tusk, Ceruledge, Venusaur, Raging Bolt |
| 3 | 817 | 49.3% ±3.4 | Araquanid, Iron Moth, Iron Valiant, Gholdengo | Gholdengo, Araquanid, Iron Valiant, Iron Moth, Kingambit, Raging Bolt |
| 7 | 749 | 49.5% ±3.6 | Ting-Lu, Skarmory, Clefable, Dragonite | Ting-Lu, Dragonite, Gholdengo, Clefable, Skarmory, Iron Moth |
| 15 | 721 | 49.0% ±3.6 | Enamorus, Blaziken, Ogerpon-Wellspring, Kingambit | Enamorus, Kingambit, Ogerpon-Wellspring, Glimmora, Gholdengo, Great Tusk |
| 10 | 694 | 44.5% ±3.7 | Deoxys-Speed, Dragonite, Zamazenta-*, Iron Valiant | Deoxys-Speed, Gholdengo, Dragonite, Zamazenta-*, Great Tusk, Iron Valiant |
| 12 | 670 | 48.8% ±3.8 | Primarina, Landorus-Therian, Iron Crown, Kingambit | Primarina, Kingambit, Landorus-Therian, Dragapult, Iron Crown, Samurott-Hisui |
| 5 | 578 | 45.7% ±4.1 | Lokix, Ursaluna, Alomomola, Zapdos | Lokix, Alomomola, Ursaluna, Zapdos, Great Tusk, Cinderace |
| 11 | 521 | 47.4% ±4.3 | Weezing-Galar, Tornadus-Therian, Alomomola, Garganacl | Weezing-Galar, Tornadus-Therian, Alomomola, Garganacl, Great Tusk, Ting-Lu |
| 13 | 472 | 46.8% ±4.5 | Volcanion, Weavile, Maushold-Four, Cetitan | Volcanion, Great Tusk, Weavile, Gholdengo, Hatterene, Kingambit |
| 23 | 454 | 49.3% ±4.6 | Garchomp, Umbreon, Keldeo-Resolute, Cresselia | Garchomp, Gholdengo, Kingambit, Cresselia, Dragapult, Dragonite |
| 14 | 408 | 55.4% ±4.9 | Heatran, Slither Wing, Skeledirge, Grimmsnarl | Heatran, Great Tusk, Ogerpon-Wellspring, Zamazenta-*, Hatterene, Pecharunt |
| 19 | 406 | 50.5% ±4.9 | Jolteon, Hydrapple, Moltres, Slowking-Galar | Great Tusk, Kingambit, Slowking-Galar, Moltres, Jolteon, Hydrapple |
| 20 | 376 | 51.1% ±5.1 | Torkoal, Tyranitar, Excadrill, Walking Wake | Great Tusk, Torkoal, Walking Wake, Tyranitar, Raging Bolt, Excadrill |
| 0 | 370 | 48.4% ±5.1 | Hoopa-Unbound, Alomomola, Scizor, Landorus-Therian | Hoopa-Unbound, Landorus-Therian, Iron Valiant, Cinderace, Alomomola, Pecharunt |
| 21 | 362 | 48.3% ±5.2 | Iron Crown, Iron Hands, Glimmora, Rillaboom | Iron Crown, Glimmora, Great Tusk, Rillaboom, Iron Hands, Raging Bolt |
| 6 | 249 | 49.0% ±6.2 | Hydrapple, Slowking-Galar, Mamoswine, Meloetta | Hydrapple, Slowking-Galar, Cinderace, Alomomola, Zamazenta-*, Moltres |
| 8 | 215 | 50.7% ±6.7 | Ninetales-Alola, Sinistcha-Masterpiece, Klefki, Iron Valiant | Iron Valiant, Ninetales-Alola, Kyurem, Samurott-Hisui, Sinistcha-Masterpiece, Iron Treads |
| 18 | 202 | 50.5% ±6.9 | Pelipper, Kingdra, Overqwil, Quaquaval | Pelipper, Raging Bolt, Iron Treads, Kingdra, Kingambit, Zamazenta-* |

## 5. 常见配置（仅统计 replay 中暴露出来的信息）

百分比的分母是该宝可梦上场的次数；未暴露的部分不计入，所以招式比例偏低。

**Great Tusk**（上场 5142 次）
- 道具（暴露 52.3%）：Rocky Helmet 22.6%、Booster Energy 20.2%、Leftovers 6.5%、Heavy-Duty Boots 1.3%
- 特性（暴露 37.7%）：Protosynthesis 37.6%、Pickpocket 0.2%
- 太晶（使用 7.0%）：Steel 1.6%、Fighting 1.1%、Fire 0.9%、Ghost 0.9%
- 招式：Headlong Rush 48.2%、Rapid Spin 40.4%、Ice Spinner 34.8%、Stealth Rock 27.7%、Close Combat 13.5%、Knock Off 8.1%、Bulk Up 6.4%、Earthquake 4.2%

**Kingambit**（上场 4404 次）
- 道具（暴露 74.8%）：Leftovers 52.7%、Air Balloon 19.9%、Shuca Berry 0.7%、Lum Berry 0.4%
- 特性（暴露 87.0%）：Supreme Overlord 86.3%、Defiant 0.6%
- 太晶（使用 21.2%）：Ghost 10.1%、Bug 3.2%、Dark 2.4%、Fire 2.1%
- 招式：Sucker Punch 49.3%、Iron Head 41.5%、Swords Dance 39.4%、Kowtow Cleave 39.0%、Low Kick 18.6%、Stealth Rock 0.3%、Iron Defense 0.1%、Protect 0.0%

**Gholdengo**（上场 4070 次）
- 道具（暴露 55.8%）：Air Balloon 35.4%、Leftovers 5.0%、Choice Scarf 3.7%、Rocky Helmet 3.3%
- 特性（暴露 7.5%）：Good as Gold 7.5%
- 太晶（使用 13.6%）：Fairy 4.6%、Steel 1.9%、Fighting 1.9%、Ghost 1.8%
- 招式：Shadow Ball 54.4%、Make It Rain 39.8%、Nasty Plot 22.4%、Recover 17.1%、Trick 16.1%、Thunder Wave 9.0%、Focus Blast 7.1%、Hex 7.1%

**Ogerpon-Wellspring**（上场 3487 次）
- 道具（暴露 0.0%）：
- 特性（暴露 21.4%）：Embody Aspect (Wellspring) 16.1%、Water Absorb 5.2%
- 太晶（使用 17.0%）：Water 17.0%
- 招式：Ivy Cudgel 71.5%、Swords Dance 22.0%、Knock Off 19.4%、Play Rough 17.4%、U-turn 15.3%、Power Whip 15.3%、Horn Leech 10.2%、Synthesis 8.7%

**Zamazenta-***（上场 3063 次）
- 道具（暴露 56.3%）：Leftovers 33.3%、Life Orb 16.1%、Chesto Berry 2.4%、Light Clay 2.3%
- 特性（暴露 100.0%）：Dauntless Shield 100.0%
- 太晶（使用 9.6%）：Steel 3.8%、Fire 2.6%、Dark 1.5%、Electric 0.8%
- 招式：Crunch 37.2%、Body Press 35.6%、Close Combat 31.8%、Iron Defense 25.6%、Light Screen 15.6%、Reflect 15.0%、Roar 11.2%、Heavy Slam 10.1%

**Dragonite**（上场 3030 次）
- 道具（暴露 18.1%）：Heavy-Duty Boots 8.3%、Leftovers 4.1%、Life Orb 3.1%、Weakness Policy 0.9%
- 特性（暴露 0.1%）：Pickpocket 0.1%
- 太晶（使用 32.7%）：Normal 18.1%、Ground 9.1%、Fire 4.9%、Poison 0.2%
- 招式：Dragon Dance 48.4%、Earthquake 43.6%、Extreme Speed 42.2%、Roost 28.3%、Ice Spinner 16.9%、Dragon Tail 12.2%、Fire Punch 7.9%、Outrage 6.5%

**Kyurem**（上场 3069 次）
- 道具（暴露 21.2%）：Leftovers 12.7%、Assault Vest 3.7%、Choice Specs 2.0%、Choice Scarf 0.9%
- 特性（暴露 100.0%）：Pressure 100.0%
- 太晶（使用 19.3%）：Ice 8.4%、Ground 5.3%、Poison 2.6%、Fairy 1.2%
- 招式：Freeze-Dry 45.3%、Earth Power 40.2%、Ice Beam 40.1%、Blizzard 10.3%、Substitute 9.0%、Icicle Spear 8.5%、Protect 7.8%、Draco Meteor 7.4%

**Raging Bolt**（上场 2510 次）
- 道具（暴露 72.0%）：Booster Energy 55.2%、Leftovers 7.8%、Life Orb 3.7%、Sitrus Berry 1.6%
- 特性（暴露 69.5%）：Protosynthesis 69.5%
- 太晶（使用 21.0%）：Fairy 9.7%、Bug 4.7%、Ghost 3.5%、Flying 1.5%
- 招式：Dragon Pulse 44.2%、Thunderbolt 43.0%、Thunderclap 34.3%、Calm Mind 26.3%、Draco Meteor 15.0%、Volt Switch 14.1%、Weather Ball 5.6%、Thunder 1.6%

**Samurott-Hisui**（上场 2442 次）
- 道具（暴露 8.2%）：Assault Vest 2.6%、Heavy-Duty Boots 2.1%、Focus Sash 2.0%、Choice Band 0.4%
- 特性（暴露 0.8%）：Water Absorb 0.6%、Pickpocket 0.2%
- 太晶（使用 6.8%）：Dark 2.3%、Poison 1.8%、Ghost 1.2%、Water 1.0%
- 招式：Ceaseless Edge 75.5%、Knock Off 25.2%、Razor Shell 23.1%、Sucker Punch 21.7%、Flip Turn 11.7%、Aqua Cutter 9.8%、Encore 7.6%、Aqua Jet 3.4%

**Slowking-Galar**（上场 2452 次）
- 道具（暴露 39.3%）：Rocky Helmet 17.1%、Black Sludge 6.2%、Assault Vest 5.0%、Heavy-Duty Boots 4.0%
- 特性（暴露 0.0%）：
- 太晶（使用 9.1%）：Water 5.3%、Fairy 2.6%、Grass 0.4%、Ice 0.2%
- 招式：Chilly Reception 51.1%、Sludge Bomb 48.8%、Future Sight 26.5%、Ice Beam 21.2%、Flamethrower 13.7%、Psyshock 10.3%、Psychic Noise 7.5%、Thunder Wave 6.9%

**Iron Valiant**（上场 2177 次）
- 道具（暴露 85.7%）：Booster Energy 83.8%、Life Orb 0.9%、Choice Specs 0.6%、Choice Scarf 0.1%
- 特性（暴露 84.1%）：Quark Drive 84.0%、Pickpocket 0.0%
- 太晶（使用 15.5%）：Ghost 7.9%、Steel 3.3%、Fairy 2.0%、Electric 1.1%
- 招式：Moonblast 59.4%、Knock Off 22.5%、Calm Mind 20.9%、Shadow Ball 20.3%、Close Combat 16.7%、Vacuum Wave 9.4%、Swords Dance 8.6%、Encore 7.7%

**Cinderace**（上场 2234 次）
- 道具（暴露 9.2%）：Heavy-Duty Boots 6.9%、Focus Sash 0.7%、Normal Gem 0.6%、Choice Band 0.4%
- 特性（暴露 30.2%）：Libero 30.2%、Pressure 0.0%
- 太晶（使用 5.9%）：Fire 4.3%、Ghost 0.5%、Grass 0.5%、Flying 0.5%
- 招式：Pyro Ball 62.6%、U-turn 55.6%、Court Change 38.1%、Will-O-Wisp 24.3%、Sucker Punch 7.3%、Gunk Shot 5.4%、High Jump Kick 2.8%、Swords Dance 1.6%

**Glimmora**（上场 2304 次）
- 道具（暴露 63.2%）：Red Card 33.3%、Power Herb 18.4%、Focus Sash 10.4%、Passho Berry 0.3%
- 特性（暴露 68.6%）：Toxic Debris 68.6%
- 太晶（使用 5.6%）：Ghost 4.6%、Fairy 0.4%、Grass 0.2%、Ground 0.2%
- 招式：Stealth Rock 46.3%、Earth Power 32.8%、Mortal Spin 28.5%、Meteor Beam 17.8%、Power Gem 15.6%、Spikes 8.5%、Sludge Wave 7.3%、Energy Ball 2.9%

**Gliscor**（上场 2141 次）
- 道具（暴露 96.6%）：Toxic Orb 96.6%、Leftovers 0.0%
- 特性（暴露 84.7%）：Poison Heal 84.4%、Pickpocket 0.3%
- 太晶（使用 24.9%）：Normal 13.3%、Dark 5.5%、Water 3.2%、Fairy 2.3%
- 招式：Protect 77.1%、Knock Off 43.0%、Earthquake 34.6%、Toxic 32.2%、Swords Dance 27.7%、Facade 26.3%、Spikes 12.7%、Substitute 11.3%

**Landorus-Therian**（上场 2106 次）
- 道具（暴露 47.1%）：Rocky Helmet 41.3%、Choice Scarf 3.1%、Leftovers 2.2%、Light Ball 0.1%
- 特性（暴露 99.9%）：Intimidate 99.9%
- 太晶（使用 4.0%）：Ground 1.8%、Ghost 1.1%、Water 0.6%、Fairy 0.3%
- 招式：U-turn 59.6%、Stealth Rock 41.3%、Earthquake 32.4%、Earth Power 22.4%、Taunt 12.5%、Stone Edge 10.7%、Grass Knot 6.1%、Rock Tomb 3.0%

## 6. 太晶与信息暴露

- 使用太晶的队伍：73.0%；太晶回合中位数 17
- 太晶属性：Ghost 1780、Water 1578、Fairy 1519、Normal 929、Steel 848、Fire 713、Ground 706、Poison 650、Dark 631、Grass 551
- 上场的宝可梦平均暴露招式 1.98/4，道具 47.2%，特性 42.0%，太晶 13.3%
- 一局中未上场的宝可梦比例：8.4%
