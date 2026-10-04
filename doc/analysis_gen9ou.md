# gen9ou replay 分析报告

生成时间：2026-10-04 16:10；脚本 `scripts/analyze_replays.py`。

## 1. 数据概况

- 对局数：**8254**（2026-07-06 ～ 2026-10-04），队伍数 16508
- replay `rating` 字段：最小 1738，中位 1785，最大 2049
- 回合数：中位 26，平均 31.7，90% 分位 52
- p1 胜率 50.9%；无胜者 9 场
- 赛前评分差 ≥50 时，评分高的一方胜率 **41.4%**（n=4057）

> **选择偏差**：下载按 `rating` 字段从高到低进行，而该字段接近双方赛后评分中较低者，
> 因此优先选中了"低分方获胜、评分上涨"的对局（上面那个低于 50% 的数字就是症状）。
> 胜率类结论都受此影响，只能作参考；使用率、搭配、配招类统计受影响较小。

## 2. 使用率、首发率与胜率

对照：Smogon 2026-09 使用率统计（门槛 1825）。

| # | 宝可梦 | 出现率 | Smogon | 首发率 | 上场率 | 胜率（95% CI） |
|---|---|---|---|---|---|---|
| 1 | Great Tusk | 34.5% | 31.8% | 10.2% | 92.2% | 50.2% ±1.3 |
| 2 | Kingambit | 31.7% | 34.3% | 2.0% | 85.9% | 49.9% ±1.4 |
| 3 | Gholdengo | 27.6% | 20.6% | 8.1% | 91.3% | 48.9% ±1.5 |
| 4 | Ogerpon-Wellspring | 23.0% | 21.8% | 24.6% | 93.1% | 51.4% ±1.6 |
| 5 | Zamazenta-* | 21.5% | 22.1% | 9.9% | 87.7% | 48.9% ±1.6 |
| 6 | Dragonite | 21.5% | 20.5% | 2.5% | 87.1% | 50.1% ±1.6 |
| 7 | Kyurem | 20.1% | 17.7% | 34.0% | 94.1% | 49.8% ±1.7 |
| 8 | Raging Bolt | 17.8% | 15.5% | 11.2% | 87.2% | 50.0% ±1.8 |
| 9 | Samurott-Hisui | 15.8% | 17.0% | 26.2% | 95.7% | 49.8% ±1.9 |
| 10 | Slowking-Galar | 15.7% | 16.0% | 21.5% | 96.3% | 49.2% ±1.9 |
| 11 | Iron Valiant | 15.5% | 18.1% | 8.3% | 87.3% | 49.4% ±1.9 |
| 12 | Cinderace | 14.9% | 13.7% | 13.8% | 92.7% | 51.6% ±2.0 |
| 13 | Glimmora | 14.8% | 21.1% | 25.8% | 95.9% | 50.8% ±2.0 |
| 14 | Gliscor | 13.8% | 10.5% | 46.5% | 95.4% | 51.9% ±2.1 |
| 15 | Landorus-Therian | 13.6% | 19.4% | 21.9% | 95.2% | 49.9% ±2.1 |
| 16 | Corviknight | 11.4% | 10.0% | 2.4% | 91.4% | 51.0% ±2.3 |
| 17 | Ting-Lu | 11.2% | 9.5% | 21.9% | 95.1% | 48.3% ±2.3 |
| 18 | Iron Moth | 11.2% | 8.8% | 5.4% | 91.2% | 48.5% ±2.3 |
| 19 | Moltres | 10.8% | 5.9% | 7.3% | 93.0% | 49.6% ±2.3 |
| 20 | Dragapult | 10.8% | 15.1% | 28.8% | 92.2% | 48.8% ±2.3 |
| 21 | Ceruledge | 10.3% | 7.1% | 5.1% | 88.6% | 52.7% ±2.4 |
| 22 | Iron Treads | 10.2% | 11.7% | 25.3% | 94.8% | 49.2% ±2.4 |
| 23 | Cresselia | 10.2% | 9.4% | 2.4% | 87.9% | 51.4% ±2.4 |
| 24 | Darkrai | 9.1% | 9.3% | 31.5% | 93.0% | 50.9% ±2.5 |
| 25 | Hatterene | 8.7% | 8.8% | 13.6% | 94.0% | 49.1% ±2.6 |

**最常见首发**：Kyurem 6.8%、Gliscor 6.4%、Ogerpon-Wellspring 5.7%、Samurott-Hisui 4.1%、Glimmora 3.8%、Great Tusk 3.5%、Slowking-Galar 3.4%、Dragapult 3.1%、Araquanid 3.1%、Landorus-Therian 3.0%、Darkrai 2.9%、Iron Treads 2.6%

## 3. L1 角色（Smogon 先验的保守下界 + replay 已暴露信息）

每支队伍的角色数 = 6 只宝可梦该角色概率之和；下表是所有队伍的平均值。

| 角色 | 每队平均 | 至少 1 只的队伍比例（≥0.5） |
|---|---|---|
| setup_sweeper | 2.07 | 96.8% |
| reliable_recovery | 1.70 | 84.1% |
| pivot | 1.48 | 75.1% |
| hazard_setter | 1.33 | 86.8% |
| item_control | 1.26 | 81.6% |
| priority | 1.21 | 78.8% |
| anti_setup | 1.02 | 70.9% |
| status_spreader | 0.97 | 64.4% |
| hazard_removal | 0.89 | 73.6% |
| choice_locked | 0.78 | 72.3% |
| physical_wall | 0.64 | 49.6% |
| booster_paradox | 0.62 | 36.3% |
| special_wall | 0.40 | 32.0% |
| weather_terrain_setter | 0.29 | 30.1% |
| weather_abuser | 0.21 | 11.7% |
| screens | 0.12 | 6.1% |

## 4. L2 核心与完整队伍（最大核心，2–6 只）

只保留"最大核心"：每个成员在其余成员出现时的条件概率 ≥0.35、lift ≥3，且没有被一个出现次数 ≥60% 的超集吸收。6 只的核心就是被大量照搬的完整队伍。

核心数量（按大小）：2 只 1 个，3 只 28 个，4 只 15 个，5 只 7 个，6 只 18 个

| 大小 | 成员 | 次数 | 条件概率下限 | 胜率 | 子核心数 |
|---|---|---|---|---|---|
| 5 | Clodsire + Corviknight + Dondozo + Gliscor + Toxapex | 605 | 0.82 | 53.9% | 0 |
| 6 | Great Tusk + Hydrapple + Jolteon + Kingambit + Moltres + Slowking-Galar | 402 | 1.00 | 50.7% | 0 |
| 6 | Blissey + Clodsire + Corviknight + Dondozo + Gliscor + Toxapex | 304 | 0.50 | 59.2% | 3 |
| 6 | Cinderace + Kingambit + Kyurem + Landorus-Therian + Ogerpon-Wellspring + Slowking-Galar | 499 | 0.89 | 52.3% | 2 |
| 6 | Clefable + Clodsire + Corviknight + Dondozo + Gliscor + Toxapex | 279 | 0.46 | 49.1% | 1 |
| 6 | Araquanid + Gholdengo + Iron Moth + Iron Valiant + Kingambit + Raging Bolt | 372 | 0.98 | 49.5% | 0 |
| 3 | Great Tusk + Ninetales + Walking Wake | 763 | 0.73 | 54.9% | 0 |
| 3 | Cinderace + Kyurem + Slowking-Galar | 1011 | 0.74 | 51.4% | 0 |
| 4 | Great Tusk + Ninetales + Venusaur + Walking Wake | 370 | 0.48 | 57.6% | 1 |
| 3 | Blissey + Dondozo + Gliscor | 559 | 0.64 | 56.2% | 0 |
| 6 | Ceruledge + Great Tusk + Ninetales + Slither Wing + Venusaur + Walking Wake | 201 | 0.71 | 59.7% | 3 |
| 3 | Blissey + Gliscor + Toxapex | 512 | 0.58 | 58.0% | 0 |
| 6 | Alomomola + Cinderace + Iron Crown + Lokix + Ursaluna + Zapdos | 159 | 0.99 | 52.8% | 0 |
| 6 | Clefable + Dragonite + Gholdengo + Iron Moth + Skarmory + Ting-Lu | 235 | 0.78 | 48.5% | 0 |
| 6 | Dragapult + Iron Crown + Kingambit + Landorus-Therian + Primarina + Samurott-Hisui | 206 | 1.00 | 49.0% | 0 |
| 4 | Ceruledge + Great Tusk + Ninetales + Walking Wake | 354 | 0.46 | 56.2% | 1 |
| 6 | Ceruledge + Cresselia + Glimmora + Kingambit + Ogerpon-Wellspring + Zamazenta-* | 239 | 0.67 | 58.2% | 7 |
| 6 | Blissey + Gliscor + Ogerpon + Pecharunt + Samurott-Hisui + Skarmory | 143 | 0.95 | 55.2% | 1 |
| 3 | Kingambit + Kyurem + Landorus-Therian | 834 | 0.54 | 52.3% | 0 |
| 6 | Dragapult + Iron Treads + Moltres + Raging Bolt + Samurott-Hisui + Zamazenta-* | 171 | 0.99 | 50.3% | 1 |
| 6 | Ceruledge + Darkrai + Glimmora + Iron Valiant + Ogerpon-Wellspring + Raging Bolt | 175 | 0.97 | 60.0% | 2 |
| 3 | Dragonite + Gholdengo + Great Tusk | 1070 | 0.46 | 51.5% | 0 |
| 5 | Dragonite + Gholdengo + Great Tusk + Kyurem + Samurott-Hisui | 340 | 0.60 | 52.4% | 2 |
| 6 | Cinderace + Corviknight + Dondozo + Kyurem + Slowking-Galar + Ting-Lu | 147 | 0.72 | 50.3% | 3 |
| 3 | Glimmora + Kingambit + Ogerpon-Wellspring | 749 | 0.40 | 53.0% | 0 |
| 2 | Excadrill + Tyranitar | 279 | 0.73 | 49.1% | 0 |
| 3 | Cresselia + Glimmora + Zamazenta-* | 462 | 0.53 | 52.4% | 0 |
| 3 | Ceruledge + Glimmora + Ogerpon-Wellspring | 472 | 0.39 | 58.3% | 0 |
| 3 | Ninetales + Raging Bolt + Walking Wake | 296 | 0.36 | 54.4% | 0 |
| 5 | Gliscor + Moltres + Ogerpon + Samurott-Hisui + Tinkaton | 120 | 0.88 | 45.8% | 2 |

### 4.1 被照搬的完整队伍

使用 ≥50 次的相同 6 只队伍有 **54** 支，覆盖 **39.8%** 的队伍。同一队伍的使用者配置几乎一致，把多场 replay 中零散暴露的信息汇总即可重建完整配置（下面是前 5 支）。

**Cinderace/Kingambit/Kyurem/Landorus-Therian/Ogerpon-Wellspring/Slowking-Galar**（499 次）
- Cinderace：Heavy-Duty Boots 97% / Black Sludge 3%；太晶 Grass 50% / Fire 25%；招式 Pyro Ball 63%, U-turn 58%, Court Change 50%, Will-O-Wisp 35%, Sucker Punch 1%
- Kingambit：Leftovers 100% / Rocky Helmet 0%；太晶 Bug 64% / Ghost 29%；招式 Sucker Punch 50%, Swords Dance 46%, Iron Head 45%, Kowtow Cleave 40%, Low Kick 18%
- Kyurem：Assault Vest 55% / Choice Specs 30%；太晶 Ice 73% / Fairy 14%；招式 Freeze-Dry 51%, Earth Power 43%, Ice Beam 31%, Blizzard 27%, Draco Meteor 14%
- Landorus-Therian：Choice Scarf 51% / Rocky Helmet 48%；太晶 Ground 89% / Fairy 11%；招式 U-turn 66%, Earthquake 49%, Stone Edge 22%, Grass Knot 7%, Stealth Rock 7%
- Ogerpon-Wellspring：；太晶 Water 100%；招式 Ivy Cudgel 75%, Play Rough 36%, Power Whip 24%, Encore 22%, Synthesis 13%
- Slowking-Galar：Rocky Helmet 97% / Heavy-Duty Boots 2%；太晶 Fairy 70% / Water 25%；招式 Chilly Reception 72%, Sludge Bomb 52%, Ice Beam 35%, Future Sight 30%, Focus Blast 15%

**Great Tusk/Hydrapple/Jolteon/Kingambit/Moltres/Slowking-Galar**（402 次）
- Great Tusk：Rocky Helmet 100% / Choice Scarf 0%；太晶 Water 100%；招式 Stealth Rock 74%, Body Press 39%, Ice Spinner 37%, Rapid Spin 28%, Earthquake 5%
- Hydrapple：Heavy-Duty Boots 99% / Rocky Helmet 1%；太晶 Poison 98% / Water 2%；招式 Giga Drain 63%, Fickle Beam 62%, Earth Power 45%, Nasty Plot 43%
- Jolteon：Heavy-Duty Boots 100%；太晶 Fairy 100%；招式 Volt Switch 59%, Thunderbolt 54%, Alluring Voice 50%, Calm Mind 36%
- Kingambit：Leftovers 100%；太晶 Ghost 100%；招式 Sucker Punch 54%, Kowtow Cleave 51%, Iron Head 37%, Swords Dance 31%
- Moltres：Heavy-Duty Boots 97% / Rocky Helmet 2%；太晶 Fairy 100%；招式 Will-O-Wisp 58%, Flamethrower 57%, Roost 42%, Scorching Sands 36%, Roar 0%
- Slowking-Galar：Assault Vest 97% / Rocky Helmet 3%；太晶 Water 100%；招式 Sludge Bomb 67%, Psyshock 48%, Flamethrower 40%, Ice Beam 35%

**Araquanid/Gholdengo/Iron Moth/Iron Valiant/Kingambit/Raging Bolt**（372 次）
- Araquanid：Custap Berry 99% / Black Sludge 1%；太晶 Ghost 100%；招式 Sticky Web 75%, Surf 49%, Endeavor 38%, Lunge 34%
- Gholdengo：Air Balloon 100%；太晶 Flying 100%；招式 Shadow Ball 68%, Nasty Plot 51%, Make It Rain 38%, Psyshock 16%, Focus Blast 1%
- Iron Moth：Booster Energy 100%；太晶 Grass 100%；招式 Fiery Dance 76%, Sludge Wave 51%, Energy Ball 29%, Substitute 22%
- Iron Valiant：Booster Energy 100%；太晶 Ghost 100%；招式 Moonblast 65%, Shadow Ball 47%, Calm Mind 47%, Vacuum Wave 37%
- Kingambit：Air Balloon 100%；太晶 Ghost 98% / Fire 2%；招式 Iron Head 57%, Sucker Punch 47%, Swords Dance 45%, Low Kick 41%, Kowtow Cleave 1%
- Raging Bolt：Booster Energy 100%；太晶 Ghost 95% / Flying 2%；招式 Dragon Pulse 61%, Thunderbolt 50%, Calm Mind 47%, Thunderclap 33%

**Blissey/Clodsire/Corviknight/Dondozo/Gliscor/Toxapex**（304 次）
- Blissey：Heavy-Duty Boots 95% / Sticky Barb 5%；太晶 Dark 93% / Water 7%；招式 Stealth Rock 76%, Seismic Toss 68%, Soft-Boiled 65%, Protect 57%, Calm Mind 5%
- Clodsire：Heavy-Duty Boots 94% / Choice Scarf 6%；太晶 Steel 100%；招式 Spikes 64%, Recover 55%, Earthquake 41%, Poison Jab 35%, Amnesia 12%
- Corviknight：Rocky Helmet 81% / Leftovers 19%；太晶 Dragon 70% / Fighting 30%；招式 Roost 62%, Body Press 46%, Defog 41%, Iron Defense 36%, Protect 13%
- Dondozo：Heavy-Duty Boots 100%；太晶 Fighting 89% / Dragon 5%；招式 Waterfall 65%, Rest 53%, Sleep Talk 46%, Curse 41%, Body Press 1%
- Gliscor：Toxic Orb 100%；太晶 Normal 92% / Water 4%；招式 Protect 90%, Knock Off 77%, Facade 58%, Swords Dance 49%, Toxic 10%
- Toxapex：Heavy-Duty Boots 99% / Black Sludge 1%；太晶 Steel 78% / Grass 11%；招式 Toxic 70%, Toxic Spikes 58%, Recover 53%, Haze 40%, Baneful Bunker 17%

**Clefable/Clodsire/Corviknight/Dondozo/Gliscor/Toxapex**（279 次）
- Clefable：Leftovers 67% / Sticky Barb 33%；太晶 Water 92% / Ice 8%；招式 Moonblast 60%, Stealth Rock 50%, Moonlight 45%, Knock Off 42%, Thunder Wave 11%
- Clodsire：Heavy-Duty Boots 71% / Leftovers 25%；太晶 Steel 100%；招式 Recover 57%, Earthquake 55%, Spikes 51%, Poison Jab 41%, Stealth Rock 8%
- Corviknight：Leftovers 100%；太晶 Dragon 100%；招式 Protect 82%, Brave Bird 73%, Roost 57%, Defog 55%, Substitute 1%
- Dondozo：Leftovers 98% / Heavy-Duty Boots 2%；太晶 Dark 100%；招式 Crunch 56%, Rest 52%, Curse 52%, Sleep Talk 44%, Waterfall 9%
- Gliscor：Toxic Orb 100% / Leftovers 0%；太晶 Dark 100%；招式 Protect 91%, Knock Off 82%, Toxic 67%, Substitute 62%, Spikes 6%
- Toxapex：Leftovers 99% / Heavy-Duty Boots 1%；太晶 Steel 73% / Grass 27%；招式 Baneful Bunker 88%, Infestation 82%, Poison Jab 53%, Recover 46%, Toxic 7%

## 5. L3 队伍类型（NMF 软聚类，k=20）

每支队伍得到各类型的混合比例；"质量"= 所有队伍在该类型上的比例之和。第二大类型占比 ≥30% 的队伍：12.7%。名字需人工或 LLM 解读。

| 类型 | 质量 | 主导队伍数 | 加权胜率 | 主要成员（载荷） |
|---|---|---|---|---|
| 2 | 1740 | 1832 | 51.2% | Glimmora 1.00, Ogerpon-Wellspring 0.69, Ceruledge 0.66, Cresselia 0.58, Darkrai 0.55, Zamazenta-* 0.48 |
| 8 | 1661 | 1714 | 50.0% | Kyurem 1.00, Cinderace 0.97, Slowking-Galar 0.86, Landorus-Therian 0.72, Ogerpon-Wellspring 0.45, Kingambit 0.38 |
| 1 | 1366 | 1324 | 49.6% | Ting-Lu 1.00, Skarmory 0.99, Clefable 0.86, Dragonite 0.81, Gholdengo 0.60, Iron Moth 0.33 |
| 3 | 1165 | 991 | 49.5% | Araquanid 1.00, Iron Moth 0.81, Iron Valiant 0.72, Zarude-Dada 0.48, Raging Bolt 0.39, Gholdengo 0.38 |
| 17 | 1120 | 1068 | 53.5% | Toxapex 1.00, Dondozo 0.99, Clodsire 0.91, Corviknight 0.80, Blissey 0.76, Gliscor 0.75 |
| 14 | 975 | 928 | 48.7% | Ogerpon 1.00, Tinkaton 0.84, Samurott-Hisui 0.62, Pecharunt 0.54, Gliscor 0.53, Moltres 0.37 |
| 19 | 953 | 778 | 49.2% | Primarina 1.00, Dragapult 0.73, Iron Crown 0.63, Landorus-Therian 0.49, Kingambit 0.31, Samurott-Hisui 0.31 |
| 0 | 951 | 1012 | 49.4% | Iron Treads 1.00, Wo-Chien 0.68, Zamazenta-* 0.60, Cresselia 0.24, Hydreigon 0.24, Sinistcha-Masterpiece 0.18 |
| 12 | 932 | 1085 | 53.7% | Ninetales 1.00, Walking Wake 0.98, Venusaur 0.91, Slither Wing 0.73, Ceruledge 0.46, Great Tusk 0.41 |
| 18 | 874 | 911 | 49.4% | Tornadus-Therian 1.00, Garganacl 0.99, Weezing-Galar 0.64, Heatran 0.44, Hatterene 0.36, Darkrai 0.32 |
| 11 | 782 | 589 | 49.6% | Jolteon 1.00, Hydrapple 0.98, Moltres 0.64, Slowking-Galar 0.49, Great Tusk 0.33, Kingambit 0.28 |
| 15 | 692 | 705 | 50.0% | Lokix 1.00, Alomomola 0.93, Ursaluna 0.83, Zapdos 0.52, Iron Crown 0.50, Cinderace 0.33 |
| 5 | 685 | 536 | 49.2% | Ribombee 1.00, Tentacruel 0.51, Manaphy 0.51, Ogerpon-Cornerstone 0.43, Gholdengo 0.35, Great Tusk 0.28 |
| 10 | 668 | 987 | 49.3% | Enamorus 1.00, Blaziken 0.66, Scizor 0.42, Cramorant 0.35, Meowscarada 0.25, Kingambit 0.16 |
| 13 | 488 | 539 | 45.5% | Rillaboom 1.00, Hawlucha 0.91, Deoxys-Speed 0.24, Iron Jugulis 0.21 |
| 16 | 414 | 291 | 49.1% | Serperior 1.00, Fezandipiti 0.96, Zapdos 0.52, Samurott-Hisui 0.27, Empoleon 0.26, Great Tusk 0.22 |
| 6 | 376 | 497 | 50.0% | Garchomp 1.00, Umbreon 0.69, Keldeo-Resolute 0.40, Cresselia 0.17, Gholdengo 0.15 |
| 4 | 344 | 363 | 50.1% | Tyranitar 1.00, Excadrill 0.99, Pecharunt 0.20, Quaquaval 0.16 |
| 9 | 192 | 220 | 50.0% | Pelipper 1.00, Kingdra 0.67, Quaquaval 0.61, Overqwil 0.56, Barraskewda 0.55, Goodra-Hisui 0.29 |
| 7 | 129 | 138 | 39.6% | Raichu-Alola 1.00, Pincurchin 0.98, Frosmoth 0.97, Pawmot 0.88, Rotom-Wash 0.79, Iron Hands 0.72 |

## 5. 常见配置（仅统计 replay 中暴露出来的信息）

百分比的分母是该宝可梦上场的次数；未暴露的部分不计入，所以招式比例偏低。

**Great Tusk**（上场 5249 次）
- 道具（暴露 52.5%）：Rocky Helmet 22.5%、Booster Energy 20.3%、Leftovers 6.6%、Heavy-Duty Boots 1.2%
- 特性（暴露 37.7%）：Protosynthesis 37.6%、Pickpocket 0.2%
- 太晶（使用 6.9%）：Steel 1.6%、Fighting 1.0%、Ghost 0.9%、Fire 0.9%
- 招式：Headlong Rush 48.4%、Rapid Spin 40.4%、Ice Spinner 34.7%、Stealth Rock 27.9%、Close Combat 13.5%、Knock Off 8.2%、Bulk Up 6.4%、Earthquake 4.3%

**Kingambit**（上场 4487 次）
- 道具（暴露 74.7%）：Leftovers 52.7%、Air Balloon 19.8%、Shuca Berry 0.7%、Lum Berry 0.4%
- 特性（暴露 86.9%）：Supreme Overlord 86.2%、Defiant 0.6%
- 太晶（使用 21.1%）：Ghost 10.2%、Bug 3.1%、Dark 2.4%、Fire 2.0%
- 招式：Sucker Punch 49.4%、Iron Head 41.6%、Swords Dance 39.4%、Kowtow Cleave 38.9%、Low Kick 18.4%、Stealth Rock 0.3%、Iron Defense 0.1%、Protect 0.0%

**Gholdengo**（上场 4157 次）
- 道具（暴露 55.9%）：Air Balloon 35.3%、Leftovers 4.9%、Choice Scarf 3.8%、Rocky Helmet 3.3%
- 特性（暴露 7.5%）：Good as Gold 7.5%
- 太晶（使用 13.6%）：Fairy 4.6%、Steel 1.9%、Fighting 1.9%、Ghost 1.9%
- 招式：Shadow Ball 54.5%、Make It Rain 40.0%、Nasty Plot 22.3%、Recover 17.1%、Trick 16.2%、Thunder Wave 8.9%、Focus Blast 7.0%、Hex 7.0%

**Ogerpon-Wellspring**（上场 3543 次）
- 道具（暴露 0.0%）：
- 特性（暴露 21.2%）：Embody Aspect (Wellspring) 16.0%、Water Absorb 5.2%
- 太晶（使用 16.9%）：Water 16.9%
- 招式：Ivy Cudgel 71.5%、Swords Dance 21.9%、Knock Off 19.3%、Play Rough 17.5%、Power Whip 15.4%、U-turn 15.4%、Horn Leech 10.2%、Synthesis 8.7%

**Zamazenta-***（上场 3116 次）
- 道具（暴露 56.2%）：Leftovers 33.2%、Life Orb 16.0%、Chesto Berry 2.3%、Light Clay 2.3%
- 特性（暴露 100.0%）：Dauntless Shield 100.0%
- 太晶（使用 9.6%）：Steel 3.7%、Fire 2.6%、Dark 1.5%、Electric 0.8%
- 招式：Crunch 37.1%、Body Press 35.6%、Close Combat 31.8%、Iron Defense 25.5%、Light Screen 15.7%、Reflect 15.1%、Roar 11.3%、Heavy Slam 10.0%

**Dragonite**（上场 3090 次）
- 道具（暴露 18.3%）：Heavy-Duty Boots 8.2%、Leftovers 4.1%、Life Orb 3.2%、Weakness Policy 0.9%
- 特性（暴露 0.1%）：Pickpocket 0.1%
- 太晶（使用 32.8%）：Normal 18.1%、Ground 9.2%、Fire 4.9%、Poison 0.2%
- 招式：Dragon Dance 48.3%、Earthquake 43.8%、Extreme Speed 42.1%、Roost 28.1%、Ice Spinner 16.8%、Dragon Tail 12.4%、Fire Punch 7.8%、Outrage 6.6%

**Kyurem**（上场 3129 次）
- 道具（暴露 21.2%）：Leftovers 12.8%、Assault Vest 3.7%、Choice Specs 1.9%、Choice Scarf 1.0%
- 特性（暴露 100.0%）：Pressure 100.0%
- 太晶（使用 19.3%）：Ice 8.4%、Ground 5.4%、Poison 2.6%、Fairy 1.2%
- 招式：Freeze-Dry 45.3%、Earth Power 40.1%、Ice Beam 39.9%、Blizzard 10.4%、Substitute 9.0%、Icicle Spear 8.6%、Protect 7.9%、Draco Meteor 7.4%

**Raging Bolt**（上场 2567 次）
- 道具（暴露 71.9%）：Booster Energy 55.0%、Leftovers 7.9%、Life Orb 3.7%、Sitrus Berry 1.6%
- 特性（暴露 69.3%）：Protosynthesis 69.3%
- 太晶（使用 21.0%）：Fairy 9.8%、Bug 4.7%、Ghost 3.5%、Flying 1.5%
- 招式：Dragon Pulse 44.2%、Thunderbolt 42.9%、Thunderclap 34.0%、Calm Mind 26.4%、Draco Meteor 15.2%、Volt Switch 14.1%、Weather Ball 5.6%、Thunder 1.6%

**Samurott-Hisui**（上场 2488 次）
- 道具（暴露 8.2%）：Assault Vest 2.7%、Heavy-Duty Boots 2.1%、Focus Sash 1.9%、Black Glasses 0.4%
- 特性（暴露 0.8%）：Water Absorb 0.6%、Pickpocket 0.2%
- 太晶（使用 6.6%）：Dark 2.3%、Poison 1.8%、Ghost 1.2%、Water 1.0%
- 招式：Ceaseless Edge 75.2%、Knock Off 25.2%、Razor Shell 23.0%、Sucker Punch 21.8%、Flip Turn 11.8%、Aqua Cutter 9.8%、Encore 7.5%、Aqua Jet 3.4%

**Slowking-Galar**（上场 2497 次）
- 道具（暴露 39.4%）：Rocky Helmet 17.2%、Black Sludge 6.2%、Assault Vest 4.9%、Heavy-Duty Boots 4.0%
- 特性（暴露 0.0%）：
- 太晶（使用 9.1%）：Water 5.3%、Fairy 2.6%、Grass 0.4%、Poison 0.2%
- 招式：Chilly Reception 51.2%、Sludge Bomb 48.9%、Future Sight 26.5%、Ice Beam 21.1%、Flamethrower 13.6%、Psyshock 10.1%、Psychic Noise 7.7%、Thunder Wave 6.8%

**Iron Valiant**（上场 2233 次）
- 道具（暴露 85.5%）：Booster Energy 83.7%、Life Orb 0.9%、Choice Specs 0.6%、Choice Scarf 0.1%
- 特性（暴露 84.0%）：Quark Drive 83.9%、Pickpocket 0.0%
- 太晶（使用 15.5%）：Ghost 7.8%、Steel 3.4%、Fairy 2.0%、Electric 1.1%
- 招式：Moonblast 59.1%、Knock Off 22.6%、Calm Mind 20.9%、Shadow Ball 20.2%、Close Combat 16.6%、Vacuum Wave 9.5%、Swords Dance 8.6%、Encore 7.8%

**Cinderace**（上场 2278 次）
- 道具（暴露 9.4%）：Heavy-Duty Boots 7.1%、Focus Sash 0.7%、Normal Gem 0.6%、Choice Band 0.4%
- 特性（暴露 30.1%）：Libero 30.1%、Pressure 0.0%
- 太晶（使用 5.8%）：Fire 4.2%、Ghost 0.6%、Grass 0.5%、Flying 0.5%
- 招式：Pyro Ball 62.9%、U-turn 55.7%、Court Change 38.3%、Will-O-Wisp 24.2%、Sucker Punch 7.2%、Gunk Shot 5.3%、High Jump Kick 2.9%、Swords Dance 1.6%

**Glimmora**（上场 2343 次）
- 道具（暴露 63.2%）：Red Card 33.2%、Power Herb 18.3%、Focus Sash 10.5%、Passho Berry 0.3%
- 特性（暴露 68.7%）：Toxic Debris 68.7%
- 太晶（使用 5.6%）：Ghost 4.6%、Fairy 0.4%、Grass 0.2%、Ground 0.2%
- 招式：Stealth Rock 46.3%、Earth Power 32.7%、Mortal Spin 28.4%、Meteor Beam 17.8%、Power Gem 15.6%、Spikes 8.6%、Sludge Wave 7.2%、Energy Ball 2.9%

**Gliscor**（上场 2177 次）
- 道具（暴露 96.6%）：Toxic Orb 96.6%、Leftovers 0.0%
- 特性（暴露 84.7%）：Poison Heal 84.4%、Pickpocket 0.3%
- 太晶（使用 24.9%）：Normal 13.4%、Dark 5.4%、Water 3.2%、Fairy 2.3%
- 招式：Protect 77.0%、Knock Off 43.1%、Earthquake 34.6%、Toxic 32.2%、Swords Dance 27.7%、Facade 26.3%、Spikes 12.6%、Substitute 11.4%

**Landorus-Therian**（上场 2138 次）
- 道具（暴露 46.9%）：Rocky Helmet 41.2%、Choice Scarf 3.1%、Leftovers 2.2%、Light Ball 0.1%
- 特性（暴露 99.9%）：Intimidate 99.9%
- 太晶（使用 4.1%）：Ground 1.9%、Ghost 1.2%、Water 0.6%、Fairy 0.3%
- 招式：U-turn 59.6%、Stealth Rock 41.3%、Earthquake 32.3%、Earth Power 22.5%、Taunt 12.5%、Stone Edge 10.8%、Grass Knot 6.2%、Rock Tomb 3.0%

## 7. 太晶与信息暴露

- 使用太晶的队伍：73.1%；太晶回合中位数 17
- 太晶属性：Ghost 1819、Water 1601、Fairy 1556、Normal 951、Steel 867、Ground 726、Fire 720、Poison 659、Dark 638、Grass 561
- 上场的宝可梦平均暴露招式 1.98/4，道具 47.2%，特性 42.0%，太晶 13.3%
- 一局中未上场的宝可梦比例：8.3%
