# gen9ou 配置原型与配置层面的组合

生成时间：2026-10-04 16:23；脚本 `scripts/mine_sets.py`；数据 8589 场 replay；对照 Smogon 2026-09（门槛 1825）。

方法：每只宝可梦一个潜在类别混合模型（EM，K 由 BIC 选），每场只用实际暴露的道具/特性/太晶/招式，未暴露不计入。招式后的数字是"带这个招式"的粗略估计（4×份额，封顶 1）。

## 1. 配置原型

**Great Tusk**（5279 次有暴露信息，K=5）
- 原型 0（31%）：Booster Energy 78% / Leftovers 7%；太晶 Fighting 37% / Fire 21%；Headlong Rush 100%, Rapid Spin 91%, Close Combat 77%, Ice Spinner 77%, Knock Off 16%, Temper Flare 7%
- 原型 1（22%）：Rocky Helmet 89% / Heavy-Duty Boots 5%；太晶 Steel 34% / Ground 19%；Stealth Rock 100%, Headlong Rush 100%, Rapid Spin 86%, Ice Spinner 79%, Knock Off 8%, Body Press 8%
- 原型 2（22%）：Rocky Helmet 96% / Heavy-Duty Boots 1%；太晶 Steel 37% / Water 17%；Stealth Rock 100%, Rapid Spin 83%, Headlong Rush 80%, Ice Spinner 78%, Body Press 21%, Knock Off 8%
- 原型 3（13%）：Leftovers 81% / Booster Energy 11%；太晶 Poison 36% / Steel 24%；Rapid Spin 100%, Knock Off 62%, Headlong Rush 60%, Ice Spinner 54%, Earthquake 50%, Stealth Rock 42%
- 原型 4（12%）：Booster Energy 98% / Leftovers 1%；太晶 Ghost 43% / Steel 26%；Headlong Rush 100%, Bulk Up 81%, Ice Spinner 53%, Rapid Spin 40%, Head Smash 35%, Taunt 27%

**Kingambit**（4623 次有暴露信息，K=1）
- 原型 0（100%）：Leftovers 70% / Air Balloon 27%；太晶 Ghost 49% / Bug 15%；Sucker Punch 100%, Iron Head 89%, Swords Dance 84%, Kowtow Cleave 83%, Low Kick 39%, Stealth Rock 1%

**Gholdengo**（4116 次有暴露信息，K=4）
- 原型 0（34%）：Air Balloon 89% / Shuca Berry 4%；太晶 Fighting 42% / Flying 33%；Shadow Ball 100%, Make It Rain 93%, Nasty Plot 80%, Focus Blast 31%, Psyshock 20%, Recover 10%
- 原型 1（29%）：Choice Scarf 35% / Leftovers 34%；太晶 Ghost 59% / Steel 33%；Shadow Ball 100%, Trick 100%, Make It Rain 100%, Recover 36%, Nasty Plot 6%, Focus Blast 4%
- 原型 2（25%）：Air Balloon 55% / Rocky Helmet 15%；太晶 Fairy 69% / Water 25%；Shadow Ball 100%, Nasty Plot 85%, Make It Rain 79%, Recover 56%, Dazzling Gleam 25%, Focus Blast 9%
- 原型 3（13%）：Air Balloon 85% / Colbur Berry 4%；太晶 Fairy 71% / Water 14%；Thunder Wave 100%, Hex 100%, Make It Rain 71%, Recover 67%, Focus Blast 17%, Nasty Plot 13%

**Ogerpon-Wellspring**（3473 次有暴露信息，K=2）
- 原型 0（50%）：；太晶 Water 100%；Ivy Cudgel 100%, Knock Off 66%, U-turn 56%, Power Whip 41%, Encore 25%, Spikes 23%
- 原型 1（50%）：；太晶 Water 100%；Ivy Cudgel 100%, Swords Dance 80%, Play Rough 58%, Horn Leech 32%, Trailblaze 29%, Power Whip 18%

**Kyurem**（3251 次有暴露信息，K=3）
- 原型 0（64%）：Assault Vest 50% / Choice Specs 26%；太晶 Ice 64% / Poison 22%；Ice Beam 100%, Freeze-Dry 95%, Earth Power 87%, Blizzard 39%, Draco Meteor 28%, Body Press 10%
- 原型 1（24%）：Leftovers 98% / Heavy-Duty Boots 1%；太晶 Ground 86% / Steel 11%；Freeze-Dry 100%, Earth Power 98%, Substitute 69%, Protect 61%, Ice Beam 29%, Icicle Spear 8%
- 原型 2（12%）：Loaded Dice 71% / Never-Melt Ice 11%；太晶 Ice 39% / Ground 33%；Icicle Spear 100%, Dragon Dance 82%, Freeze-Dry 71%, Earth Power 71%, Scale Shot 27%, Shadow Claw 5%

**Zamazenta-***（3245 次有暴露信息，K=3）
- 原型 0（43%）：Leftovers 93% / Chesto Berry 7%；太晶 Steel 37% / Fire 34%；Body Press 100%, Iron Defense 100%, Crunch 81%, Roar 32%, Substitute 22%, Heavy Slam 13%
- 原型 1（37%）：Life Orb 92% / Heavy-Duty Boots 5%；太晶 Dark 39% / Steel 32%；Close Combat 100%, Crunch 100%, Ice Fang 49%, Stone Edge 41%, Heavy Slam 29%, Psychic Fangs 20%
- 原型 2（20%）：Light Clay 76% / Throat Spray 12%；太晶 Steel 73% / Dark 17%；Light Screen 100%, Reflect 100%, Close Combat 56%, Body Press 33%, Roar 28%, Heavy Slam 18%

**Dragonite**（3086 次有暴露信息，K=5）
- 原型 0（32%）：Heavy-Duty Boots 95% / Weakness Policy 1%；太晶 Normal 99% / Ground 0%；Extreme Speed 100%, Roost 80%, Earthquake 79%, Dragon Tail 69%, Dragon Dance 38%, Low Kick 7%
- 原型 1（25%）：Leftovers 65% / Heavy-Duty Boots 27%；太晶 Ground 98% / Poison 1%；Earthquake 100%, Dragon Dance 100%, Ice Spinner 85%, Roost 56%, Extreme Speed 10%, Encore 4%
- 原型 2（22%）：Heavy-Duty Boots 37% / Weakness Policy 22%；太晶 Normal 99% / Ground 0%；Extreme Speed 100%, Dragon Dance 97%, Earthquake 90%, Roost 38%, Ice Spinner 30%, Hurricane 12%
- 原型 3（11%）：Life Orb 79% / Choice Band 6%；太晶 Fire 71% / Normal 23%；Outrage 100%, Dragon Dance 100%, Extreme Speed 71%, Fire Punch 54%, Earthquake 19%, Ice Spinner 15%
- 原型 4（9%）：Loaded Dice 31% / Leftovers 24%；太晶 Fire 95% / Poison 2%；Dragon Dance 100%, Scale Shot 100%, Fire Punch 83%, Encore 41%, Dragon Claw 29%, Roost 18%

**Raging Bolt**（2619 次有暴露信息，K=3）
- 原型 0（69%）：Booster Energy 85% / Leftovers 12%；太晶 Fairy 36% / Bug 32%；Dragon Pulse 100%, Thunderbolt 100%, Calm Mind 80%, Thunderclap 76%, Taunt 2%, Weather Ball 2%
- 原型 1（21%）：Booster Energy 25% / Heavy-Duty Boots 25%；太晶 Fairy 87% / Dragon 7%；Volt Switch 100%, Draco Meteor 100%, Thunderbolt 67%, Thunderclap 63%, Discharge 6%, Weather Ball 3%
- 原型 2（11%）：Life Orb 47% / Booster Energy 31%；太晶 Fire 42% / Fairy 38%；Weather Ball 100%, Thunderclap 69%, Draco Meteor 59%, Dragon Pulse 54%, Volt Switch 37%, Thunder 25%

**Slowking-Galar**（2454 次有暴露信息，K=3）
- 原型 0（39%）：Black Sludge 44% / Heavy-Duty Boots 27%；太晶 Water 81% / Grass 8%；Chilly Reception 100%, Sludge Bomb 76%, Future Sight 71%, Thunder Wave 32%, Trick 23%, Psychic Noise 22%
- 原型 1（38%）：Rocky Helmet 83% / Shuca Berry 15%；太晶 Fairy 65% / Water 26%；Chilly Reception 100%, Sludge Bomb 100%, Ice Beam 68%, Future Sight 64%, Focus Blast 19%, Flamethrower 8%
- 原型 2（23%）：Assault Vest 91% / Rocky Helmet 5%；太晶 Water 84% / Fairy 9%；Sludge Bomb 100%, Flamethrower 91%, Psyshock 83%, Ice Beam 63%, Psychic Noise 25%, Whirlpool 6%

**Samurott-Hisui**（2370 次有暴露信息，K=1）
- 原型 0（100%）：Assault Vest 33% / Heavy-Duty Boots 27%；太晶 Dark 35% / Poison 27%；Ceaseless Edge 100%, Knock Off 55%, Razor Shell 50%, Sucker Punch 47%, Flip Turn 26%, Aqua Cutter 21%

**Glimmora**（2321 次有暴露信息，K=3）
- 原型 0（57%）：Red Card 92% / Focus Sash 7%；太晶 Ghost 97% / Flying 2%；Stealth Rock 100%, Mortal Spin 89%, Earth Power 83%, Power Gem 49%, Spikes 36%, Sludge Wave 2%
- 原型 1（24%）：Power Herb 99% / Red Card 0%；太晶 Ghost 75% / Fairy 14%；Meteor Beam 100%, Stealth Rock 84%, Earth Power 75%, Mortal Spin 61%, Power Gem 8%, Spikes 8%
- 原型 2（19%）：Focus Sash 92% / Passho Berry 4%；太晶 Fairy 31% / Grass 24%；Stealth Rock 93%, Sludge Wave 86%, Earth Power 83%, Power Gem 54%, Mortal Spin 38%, Energy Ball 36%

**Cinderace**（2224 次有暴露信息，K=2）
- 原型 0（75%）：Heavy-Duty Boots 91% / Focus Sash 6%；太晶 Fire 56% / Ghost 17%；Pyro Ball 100%, U-turn 100%, Court Change 87%, Will-O-Wisp 63%, Gunk Shot 6%, Sucker Punch 4%
- 原型 1（25%）：Heavy-Duty Boots 36% / Normal Gem 24%；太晶 Fire 97% / Grass 1%；Pyro Ball 100%, U-turn 88%, Sucker Punch 48%, Court Change 47%, Gunk Shot 26%, High Jump Kick 23%

**Iron Valiant**（2319 次有暴露信息，K=3）
- 原型 0（52%）：Booster Energy 99% / Choice Specs 1%；太晶 Ghost 77% / Electric 10%；Moonblast 100%, Calm Mind 84%, Shadow Ball 81%, Vacuum Wave 39%, Thunderbolt 19%, Focus Blast 15%
- 原型 1（25%）：Booster Energy 95% / Life Orb 4%；太晶 Fairy 52% / Steel 30%；Moonblast 100%, Knock Off 84%, Close Combat 57%, Destiny Bond 27%, Encore 21%, Taunt 20%
- 原型 2（24%）：Booster Energy 99% / Life Orb 1%；太晶 Steel 69% / Dark 29%；Knock Off 100%, Close Combat 85%, Swords Dance 73%, Moonblast 54%, Encore 33%, Spirit Break 24%

**Gliscor**（2217 次有暴露信息，K=3）
- 原型 0（42%）：Toxic Orb 100%；太晶 Normal 94% / Dark 4%；Protect 100%, Swords Dance 91%, Facade 87%, Knock Off 65%, Earthquake 47%, Agility 7%
- 原型 1（32%）：Toxic Orb 100%；太晶 Water 50% / Fairy 43%；Protect 100%, Earthquake 86%, Toxic 77%, Spikes 40%, Stealth Rock 36%, Knock Off 28%
- 原型 2（25%）：Toxic Orb 100%；太晶 Dark 87% / Ghost 6%；Protect 100%, Knock Off 96%, Toxic 88%, Substitute 61%, Spikes 23%, Earthquake 11%

**Landorus-Therian**（2228 次有暴露信息，K=2）
- 原型 0（54%）：Rocky Helmet 100% / Leftovers 0%；太晶 Ghost 62% / Water 31%；Stealth Rock 100%, U-turn 100%, Earth Power 82%, Taunt 44%, Earthquake 21%, Grass Knot 10%
- 原型 1（46%）：Rocky Helmet 62% / Choice Scarf 23%；太晶 Ground 78% / Fairy 10%；U-turn 100%, Earthquake 100%, Stone Edge 52%, Stealth Rock 47%, Grass Knot 17%, Rock Tomb 4%

**Ting-Lu**（1848 次有暴露信息，K=2）
- 原型 0（85%）：Leftovers 70% / Rocky Helmet 18%；太晶 Water 59% / Poison 23%；Stealth Rock 100%, Earthquake 96%, Ruination 96%, Whirlwind 42%, Spikes 35%, Rest 9%
- 原型 1（15%）：Leftovers 76% / Weakness Policy 21%；太晶 Water 93% / Ghost 5%；Earthquake 100%, Payback 74%, Rest 71%, Sleep Talk 56%, Stealth Rock 36%, Ruination 24%

**Corviknight**（1774 次有暴露信息，K=2）
- 原型 0（60%）：Rocky Helmet 89% / Leftovers 9%；太晶 Dragon 52% / Grass 18%；Roost 100%, U-turn 87%, Body Press 62%, Defog 61%, Iron Defense 43%, Brave Bird 39%
- 原型 1（40%）：Leftovers 96% / Maranga Berry 3%；太晶 Dragon 58% / Dark 29%；Brave Bird 100%, Protect 85%, Roost 84%, Defog 72%, U-turn 26%, Bulk Up 13%

**Iron Moth**（1719 次有暴露信息，K=4）
- 原型 0（40%）：Booster Energy 100% / Heavy-Duty Boots 0%；太晶 Grass 86% / Ghost 9%；Fiery Dance 100%, Sludge Wave 100%, Energy Ball 58%, Substitute 48%, Psychic 4%, Overheat 3%
- 原型 1（34%）：Booster Energy 100% / Heavy-Duty Boots 0%；太晶 Fairy 69% / Ghost 21%；Fiery Dance 100%, Sludge Wave 88%, Toxic Spikes 39%, Dazzling Gleam 33%, Whirlwind 20%, Morning Sun 16%
- 原型 2（20%）：Booster Energy 80% / Heavy-Duty Boots 20%；太晶 Fire 80% / Grass 18%；Fiery Dance 100%, Overheat 95%, Toxic 81%, Morning Sun 60%, Sludge Wave 6%, Energy Ball 5%
- 原型 3（6%）：Power Herb 99% / Booster Energy 1%；太晶 Grass 64% / Fairy 28%；Meteor Beam 100%, Fire Blast 76%, Sludge Wave 68%, Energy Ball 48%, Fiery Dance 21%, Dazzling Gleam 16%

**Moltres**（1575 次有暴露信息，K=2）
- 原型 0（90%）：Heavy-Duty Boots 100% / Life Orb 0%；太晶 Fairy 78% / Ground 12%；Flamethrower 100%, Roost 74%, U-turn 63%, Will-O-Wisp 51%, Scorching Sands 31%, Roar 30%
- 原型 1（10%）：Life Orb 99% / Heavy-Duty Boots 1%；太晶 Ground 93% / Grass 4%；Hurricane 100%, Fire Blast 100%, Agility 80%, Scorching Sands 74%, Flamethrower 5%, U-turn 2%

**Dragapult**（1618 次有暴露信息，K=3）
- 原型 0（45%）：Life Orb 82% / Choice Specs 15%；太晶 Ghost 50% / Dragon 49%；Shadow Ball 100%, Draco Meteor 99%, U-turn 59%, Dragon Darts 49%, Will-O-Wisp 28%, Fire Blast 17%
- 原型 1（33%）：Heavy-Duty Boots 39% / Focus Sash 30%；太晶 Ghost 39% / Dragon 24%；Hex 100%, Will-O-Wisp 85%, U-turn 69%, Thunder Wave 49%, Draco Meteor 45%, Dragon Darts 33%
- 原型 2（22%）：Leftovers 71% / Choice Band 17%；太晶 Ghost 69% / Dragon 24%；Dragon Darts 100%, U-turn 66%, Will-O-Wisp 64%, Hex 51%, Substitute 34%, Astonish 19%

**Iron Treads**（1609 次有暴露信息，K=3）
- 原型 0（51%）：Leftovers 88% / Air Balloon 7%；太晶 Ghost 88% / Normal 10%；Stealth Rock 100%, Earthquake 99%, Knock Off 89%, Rapid Spin 81%, Ice Spinner 12%, Rest 2%
- 原型 1（36%）：Booster Energy 90% / Air Balloon 6%；太晶 Ground 68% / Ghost 30%；Earthquake 100%, Stealth Rock 88%, Rapid Spin 79%, Ice Spinner 63%, Knock Off 17%, Supercell Slam 13%
- 原型 2（13%）：Booster Energy 80% / Air Balloon 19%；太晶 Ghost 83% / Ground 9%；Stealth Rock 100%, Steel Beam 94%, Earth Power 77%, Rapid Spin 58%, Earthquake 5%, Endeavor 4%

**Ceruledge**（1511 次有暴露信息，K=2）
- 原型 0（50%）：Life Orb 70% / Air Balloon 29%；太晶 Ghost 83% / Fairy 8%；Bitter Blade 100%, Swords Dance 98%, Shadow Sneak 91%, Poltergeist 87%, Close Combat 1%, Dragon Claw 1%
- 原型 1（50%）：Air Balloon 73% / Focus Sash 23%；太晶 Fairy 64% / Fighting 25%；Bitter Blade 100%, Swords Dance 100%, Poltergeist 72%, Shadow Sneak 58%, Close Combat 25%, Destiny Bond 14%

**Cresselia**（1490 次有暴露信息，K=4）
- 原型 0（34%）：Leftovers 100% / Covert Cloak 0%；太晶 Fairy 99% / Poison 0%；Calm Mind 100%, Moonblast 100%, Lunar Blessing 61%, Stored Power 61%, Moonlight 11%, Psyshock 4%
- 原型 1（29%）：Leftovers 97% / Covert Cloak 3%；太晶 Electric 99% / Poison 0%；Calm Mind 100%, Ice Beam 92%, Moonlight 77%, Thunderbolt 77%, Thunder 31%, Lunar Blessing 2%
- 原型 2（25%）：Leftovers 86% / Covert Cloak 13%；太晶 Poison 82% / Fairy 12%；Calm Mind 100%, Moonblast 100%, Moonlight 86%, Stored Power 65%, Psyshock 9%, Lunar Blessing 1%
- 原型 3（12%）：Rocky Helmet 55% / Eject Button 43%；太晶 Steel 69% / Electric 11%；Thunder Wave 91%, Lunar Dance 88%, Ice Beam 72%, Moonlight 63%, Trick Room 41%, Reflect 12%

**Darkrai**（1375 次有暴露信息，K=2）
- 原型 0（55%）：Life Orb 47% / Leftovers 29%；太晶 Poison 68% / Ghost 20%；Dark Pulse 100%, Nasty Plot 60%, Focus Blast 59%, Ice Beam 55%, Sludge Bomb 45%, Trick 14%
- 原型 1（45%）：Leftovers 25% / Focus Sash 22%；太晶 Dark 67% / Poison 19%；Dark Pulse 100%, Ice Beam 81%, Knock Off 59%, Will-O-Wisp 46%, Trick 17%, Sludge Bomb 15%

**Hatterene**（1275 次有暴露信息，K=3）
- 原型 0（45%）：Rocky Helmet 56% / Eject Button 17%；太晶 Flying 52% / Water 35%；Nuzzle 100%, Psychic Noise 100%, Draining Kiss 87%, Pain Split 54%, Dazzling Gleam 13%, Future Sight 11%
- 原型 1（28%）：Leftovers 55% / Eject Button 17%；太晶 Water 68% / Steel 18%；Draining Kiss 100%, Psychic Noise 69%, Mystical Fire 60%, Calm Mind 56%, Nuzzle 54%, Psyshock 33%
- 原型 2（27%）：Eject Button 38% / Rocky Helmet 33%；太晶 Steel 62% / Poison 22%；Dazzling Gleam 85%, Psychic Noise 82%, Healing Wish 81%, Trick Room 72%, Nuzzle 45%, Mystical Fire 9%

**Pecharunt**（1169 次有暴露信息，K=3）
- 原型 0（45%）：Heavy-Duty Boots 68% / Rocky Helmet 27%；太晶 Ghost 89% / Grass 6%；Parting Shot 100%, Shadow Ball 91%, Toxic 86%, Recover 83%, Malignant Chain 28%, Hex 1%
- 原型 1（33%）：Heavy-Duty Boots 63% / Air Balloon 26%；太晶 Ghost 67% / Water 30%；Malignant Chain 100%, Shadow Ball 100%, Recover 82%, Nasty Plot 62%, Parting Shot 26%, Hex 3%
- 原型 2（22%）：Heavy-Duty Boots 58% / Rocky Helmet 24%；太晶 Dark 88% / Water 8%；Parting Shot 99%, Recover 86%, Malignant Chain 86%, Foul Play 57%, Toxic 34%, Shadow Ball 33%

**Walking Wake**（1213 次有暴露信息，K=3）
- 原型 0（77%）：Life Orb 57% / Choice Specs 21%；太晶 Water 84% / Dragon 6%；Hydro Steam 100%, Draco Meteor 100%, Flip Turn 32%, Dragon Pulse 28%, Flamethrower 23%, Weather Ball 18%
- 原型 1（12%）：Booster Energy 97% / Choice Specs 1%；太晶 Water 49% / Fairy 23%；Dragon Pulse 100%, Agility 72%, Surf 69%, Substitute 61%, Hydro Pump 46%, Hydro Steam 15%
- 原型 2（11%）：Leftovers 55% / Heavy-Duty Boots 27%；太晶 Water 34% / Dragon 27%；Draco Meteor 100%, Surf 87%, Flip Turn 84%, Knock Off 65%, Scald 27%, Substitute 15%

**Clefable**（1112 次有暴露信息，K=2）
- 原型 0（57%）：Leftovers 63% / Rocky Helmet 29%；太晶 Water 79% / Ice 13%；Moonblast 100%, Stealth Rock 95%, Moonlight 74%, Knock Off 56%, Thunder Wave 40%, Trick 6%
- 原型 1（43%）：Leftovers 94% / Heavy-Duty Boots 4%；太晶 Water 52% / Steel 46%；Moonblast 100%, Moonlight 80%, Calm Mind 80%, Knock Off 60%, Cosmic Power 15%, Thunder Wave 13%

**Alomomola**（981 次有暴露信息，K=2）
- 原型 0（58%）：Rocky Helmet 55% / Heavy-Duty Boots 31%；太晶 Ghost 75% / Steel 16%；Flip Turn 100%, Wish 100%, Protect 64%, Tickle 30%, Scald 18%, Mirror Coat 15%
- 原型 1（42%）：Assault Vest 98% / Rocky Helmet 1%；太晶 Normal 51% / Fairy 41%；Flip Turn 100%, Mirror Coat 58%, Body Slam 58%, Aqua Jet 47%, Scald 26%, Play Rough 15%

**Toxapex**（915 次有暴露信息，K=3）
- 原型 0（50%）：Leftovers 93% / Heavy-Duty Boots 7%；太晶 Steel 59% / Grass 34%；Baneful Bunker 100%, Infestation 100%, Poison Jab 73%, Recover 66%, Toxic 20%, Haze 2%
- 原型 1（40%）：Heavy-Duty Boots 67% / Eject Button 19%；太晶 Fairy 45% / Steel 34%；Toxic 100%, Toxic Spikes 84%, Recover 83%, Haze 76%, Poison Jab 18%, Baneful Bunker 13%
- 原型 2（10%）：Black Sludge 50% / Assault Vest 25%；太晶 Ghost 57% / Steel 18%；Surf 100%, Sludge Bomb 89%, Infestation 55%, Toxic Spikes 52%, Recover 29%, Poison Jab 16%

**Ogerpon**（911 次有暴露信息，K=1）
- 原型 0（100%）：Heavy-Duty Boots 78% / Choice Band 15%；太晶 Grass 100%；Ivy Cudgel 100%, Knock Off 100%, U-turn 87%, Encore 52%, Synthesis 15%, Spikes 7%

**Dondozo**（843 次有暴露信息，K=2）
- 原型 0（55%）：Leftovers 82% / Heavy-Duty Boots 18%；太晶 Fighting 42% / Dark 42%；Waterfall 100%, Rest 92%, Curse 75%, Sleep Talk 62%, Body Press 52%, Avalanche 13%
- 原型 1（45%）：Leftovers 95% / Chesto Berry 4%；太晶 Dark 94% / Fighting 5%；Rest 100%, Curse 97%, Sleep Talk 74%, Crunch 71%, Waterfall 32%, Wave Crash 11%

**Enamorus**（815 次有暴露信息，K=2）
- 原型 0（78%）：Life Orb 70% / Choice Scarf 16%；太晶 Ground 47% / Fairy 40%；Moonblast 100%, Earth Power 86%, Healing Wish 66%, Mystical Fire 27%, Agility 7%, Superpower 7%
- 原型 1（22%）：Life Orb 61% / Leftovers 36%；太晶 Fairy 68% / Ground 28%；Moonblast 100%, Earth Power 95%, Substitute 56%, Draining Kiss 32%, Calm Mind 22%, Taunt 6%

**Zapdos**（826 次有暴露信息，K=3）
- 原型 0（41%）：Heavy-Duty Boots 74% / Rocky Helmet 26%；太晶 Grass 58% / Steel 29%；Discharge 100%, U-turn 100%, Hurricane 96%, Roost 74%, Heat Wave 13%, Volt Switch 1%
- 原型 1（40%）：Heavy-Duty Boots 68% / Rocky Helmet 32%；太晶 Grass 46% / Steel 26%；Hurricane 100%, Volt Switch 100%, Roost 75%, Thunder Wave 70%, Heat Wave 11%, Thunderbolt 2%
- 原型 2（19%）：Heavy-Duty Boots 80% / Rocky Helmet 20%；太晶 Fire 68% / Fairy 16%；Hurricane 100%, Volt Switch 100%, Heat Wave 72%, Roost 47%, Thunderbolt 25%, Discharge 20%

**Garganacl**（826 次有暴露信息，K=3）
- 原型 0（74%）：Leftovers 100%；太晶 Water 60% / Fairy 34%；Salt Cure 100%, Protect 98%, Stealth Rock 91%, Recover 77%, Avalanche 1%, Curse 1%
- 原型 1（19%）：Leftovers 100%；太晶 Water 88% / Fairy 7%；Salt Cure 100%, Recover 82%, Curse 79%, Protect 49%, Earthquake 38%, Block 7%
- 原型 2（7%）：Leftovers 100%；太晶 Fairy 83% / Water 13%；Salt Cure 100%, Iron Defense 100%, Recover 93%, Body Press 66%, Earthquake 9%, Curse 2%

**Deoxys-Speed**（841 次有暴露信息，K=4）
- 原型 0（32%）：Focus Sash 46% / Rocky Helmet 27%；太晶 Fighting 50% / Electric 50%；Stealth Rock 100%, Spikes 100%, Taunt 74%, Pain Split 28%, Thunder Wave 12%, Skill Swap 8%
- 原型 1（28%）：Life Orb 94% / Eject Pack 3%；太晶 Fighting 70% / Electric 30%；Psycho Boost 100%, Nasty Plot 89%, Focus Blast 79%, Shadow Ball 46%, Pain Split 24%, Thunderbolt 20%
- 原型 2（25%）：Eject Pack 67% / Life Orb 25%；太晶 Fighting 93% / Electric 7%；Psycho Boost 100%, Stealth Rock 70%, Knock Off 68%, Superpower 64%, Ice Beam 24%, Spikes 21%
- 原型 3（15%）：Light Clay 89% / Rocky Helmet 2%；太晶 Fighting 50% / Electric 50%；Reflect 100%, Light Screen 100%, Taunt 70%, Teleport 38%, Stealth Rock 33%, Psycho Boost 23%

**Ninetales**（830 次有暴露信息，K=1）
- 原型 0（100%）：Heat Rock 100%；太晶 Ghost 100%；Encore 90%, Overheat 89%, Healing Wish 86%, Will-O-Wisp 83%, Weather Ball 28%, Scorching Sands 14%

**Blissey**（756 次有暴露信息，K=2）
- 原型 0（54%）：Heavy-Duty Boots 55% / Leftovers 45%；太晶 Dark 97% / Poison 3%；Stealth Rock 100%, Seismic Toss 100%, Soft-Boiled 90%, Protect 60%, Thunder Wave 22%, Calm Mind 2%
- 原型 1（46%）：Leftovers 83% / Heavy-Duty Boots 17%；太晶 Dark 53% / Poison 47%；Soft-Boiled 96%, Seismic Toss 92%, Calm Mind 83%, Stealth Rock 70%, Shadow Ball 46%, Flamethrower 8%

**Iron Crown**（746 次有暴露信息，K=2）
- 原型 0（77%）：Assault Vest 51% / Choice Specs 25%；太晶 Steel 60% / Fairy 29%；Tachyon Cutter 100%, Volt Switch 100%, Psychic Noise 48%, Future Sight 36%, Focus Blast 32%, Psyshock 9%
- 原型 1（23%）：Booster Energy 95% / Weakness Policy 4%；太晶 Fighting 89% / Fairy 8%；Tachyon Cutter 100%, Calm Mind 100%, Focus Blast 65%, Psyshock 48%, Psychic Noise 27%, Stored Power 17%

**Araquanid**（718 次有暴露信息，K=1）
- 原型 0（100%）：Custap Berry 62% / Red Card 31%；太晶 Ghost 100%；Sticky Web 100%, Surf 100%, Endeavor 75%, Lunge 49%, Liquidation 8%, Pounce 4%

## 2. 与 Smogon 统计不一致的配置（可能的新技巧）

条件：原型占该宝可梦 ≥10%，且其主要道具/太晶（≥50%）或核心招式（≥60%）在 Smogon 边缘统计中 <5%。

- **Great Tusk 原型 3**（13%）：Great Tusk @ Leftovers [tera Poison]: Rapid Spin / Knock Off / Headlong Rush / Ice Spinner — 道具 Leftovers（Smogon 4%，可能是暴露偏差）
- **Dragapult 原型 2**（22%）：Dragapult @ Leftovers [tera Ghost]: Dragon Darts / U-turn / Will-O-Wisp / Hex — 道具 Leftovers（Smogon 2%，可能是暴露偏差）
- **Cresselia 原型 3**（12%）：Cresselia @ Rocky Helmet [tera Steel]: Thunder Wave / Lunar Dance / Ice Beam / Moonlight — 道具 Rocky Helmet（Smogon 1%，可能是暴露偏差）
- **Walking Wake 原型 0**（77%）：Walking Wake @ Life Orb [tera Water]: Hydro Steam / Draco Meteor / Flip Turn / Dragon Pulse — 道具 Life Orb（Smogon 2%，可能是暴露偏差）
- **Walking Wake 原型 2**（11%）：Walking Wake @ Leftovers [tera Water]: Draco Meteor / Surf / Flip Turn / Knock Off — 道具 Leftovers（Smogon 3%，可能是暴露偏差）

## 3. 配置层面的组合

单位是"宝可梦#原型编号"（后验 ≥0.7 时才认定原型，否则只记物种）。只列出至少包含一个配置原型的核心。

| 组合 | 次数 | lift | 条件概率下限 | 胜率 |
|---|---|---|---|---|
| Great Tusk + Ninetales#0 + Walking Wake#0 | 585 | 54.4 | 0.78 | 54.2% |
| Hydrapple#0 + Jolteon#0 + Moltres#0 + Slowking-Galar#2 | 227 | 8174.6 | 0.72 | 53.7% |
| Hydrapple#0 + Jolteon#0 + Kingambit#0 + Moltres#0 | 290 | 1103.5 | 0.91 | 50.0% |
| Clodsire#0 + Corviknight#1 + Gliscor#2 + Toxapex#0 | 203 | 14935.9 | 0.72 | 51.7% |
| Great Tusk + Ninetales#0 + Venusaur#0 + Walking Wake#0 | 271 | 1215.4 | 0.46 | 52.4% |
| Hydrapple#0 + Jolteon#0 + Kingambit#0 + Slowking-Galar#2 | 220 | 2616.1 | 0.73 | 50.0% |
| Jolteon#0 + Kingambit#0 + Moltres#0 + Slowking-Galar#2 | 220 | 860.8 | 0.72 | 50.0% |
| Hydrapple#0 + Kingambit#0 + Moltres#0 + Slowking-Galar#2 | 227 | 625.2 | 0.71 | 51.1% |
| Ninetales#0 + Slither Wing#0 + Venusaur#0 + Walking Wake#0 | 162 | 7718.8 | 0.55 | 53.7% |
| Great Tusk + Ninetales#0 + Slither Wing#0 + Venusaur#0 | 172 | 2047.2 | 0.59 | 52.9% |
| Great Tusk + Hydrapple#0 + Jolteon#0 + Moltres#0 | 191 | 875.0 | 0.61 | 51.8% |
| Clefable#0 + Corviknight#1 + Gliscor#2 + Toxapex#0 | 127 | 14621.3 | 0.50 | 59.1% |
| Clefable#0 + Clodsire#0 + Corviknight#1 + Toxapex#0 | 136 | 7308.2 | 0.48 | 56.6% |
| Great Tusk + Slither Wing#0 + Venusaur#0 + Walking Wake#0 | 162 | 1655.0 | 0.57 | 53.1% |
| Corviknight#1 + Toxapex#0 | 376 | 23.8 | 0.61 | 54.5% |
| Blissey#0 + Clodsire#0 + Corviknight#0 + Toxapex#1 | 129 | 9620.8 | 0.71 | 63.6% |
| Cinderace#0 + Kingambit#0 + Landorus-Therian#1 + Slowking-Galar#1 | 211 | 262.6 | 0.62 | 45.5% |
| Great Tusk + Hydrapple#0 + Jolteon#0 + Slowking-Galar#2 | 152 | 2176.0 | 0.64 | 54.6% |
| Great Tusk#2 + Hydrapple#0 + Jolteon#0 + Moltres#0 | 124 | 11129.9 | 0.39 | 54.0% |
| Clefable#0 + Clodsire#0 + Gliscor#2 + Toxapex#0 | 120 | 11603.5 | 0.56 | 55.0% |
| Clodsire#0 + Corviknight#1 + Dondozo#1 + Toxapex#0 | 116 | 13467.8 | 0.41 | 48.3% |
| Blissey#0 + Clodsire#0 + Gliscor#0 + Toxapex#1 | 117 | 11042.0 | 0.76 | 65.8% |
| Clefable#0 + Clodsire#0 + Corviknight#1 + Gliscor#2 | 120 | 8229.3 | 0.54 | 56.7% |
| Araquanid#0 + Iron Valiant#0 + Kingambit#0 + Raging Bolt#0 | 205 | 186.7 | 0.70 | 34.1% |
| Blissey#0 + Clodsire#0 + Dondozo#0 + Toxapex#1 | 107 | 18517.6 | 0.70 | 62.6% |
| Cinderace#0 + Kingambit#0 + Kyurem#0 + Slowking-Galar#1 | 219 | 117.6 | 0.52 | 45.7% |
| Ceruledge#1 + Ninetales#0 + Venusaur#0 + Walking Wake#0 | 125 | 3896.3 | 0.43 | 40.0% |
| Clodsire#0 + Corviknight#0 + Gliscor#0 + Toxapex#1 | 127 | 3348.1 | 0.70 | 64.6% |
| Great Tusk + Jolteon#0 + Moltres#0 + Slowking-Galar#2 | 156 | 734.8 | 0.65 | 55.8% |
| Great Tusk#2 + Hydrapple#0 + Jolteon#0 + Kingambit#0 | 125 | 3704.8 | 0.41 | 52.0% |
| Corviknight#1 + Dondozo#1 + Gliscor#2 + Toxapex#0 | 101 | 25122.9 | 0.40 | 50.5% |
| Iron Crown#0 + Lokix#0 + Ursaluna#0 + Zapdos#0 | 104 | 17316.6 | 0.80 | 51.9% |
| Great Tusk + Hydrapple#0 + Jolteon#0 + Kingambit#0 | 178 | 269.3 | 0.59 | 47.8% |
| Cinderace#0 + Iron Crown#0 + Lokix#0 + Ursaluna#0 | 123 | 3159.8 | 0.89 | 52.8% |
| Great Tusk + Hydrapple#0 + Moltres#0 + Slowking-Galar#2 | 156 | 517.3 | 0.62 | 55.8% |
| Clodsire#0 + Corviknight#0 + Dondozo#0 + Toxapex#1 | 113 | 5462.7 | 0.62 | 65.5% |
| Blissey#0 + Corviknight#0 + Gliscor#0 + Toxapex#1 | 107 | 7728.4 | 0.70 | 67.3% |
| Cinderace#0 + Kyurem#0 + Landorus-Therian#1 + Slowking-Galar#1 | 153 | 514.3 | 0.59 | 47.1% |
| Cinderace#0 + Lokix#0 + Ursaluna#0 + Zapdos#0 | 110 | 5803.9 | 0.80 | 50.0% |
| Cinderace#0 + Kingambit#0 + Kyurem#0 + Landorus-Therian#1 | 209 | 89.9 | 0.49 | 47.4% |

原型编号对照：

- `Araquanid#0`：Araquanid @ Custap Berry [tera Ghost]: Sticky Web / Surf / Endeavor / Lunge
- `Blissey#0`：Blissey @ Heavy-Duty Boots [tera Dark]: Stealth Rock / Seismic Toss / Soft-Boiled / Protect
- `Ceruledge#1`：Ceruledge @ Air Balloon [tera Fairy]: Bitter Blade / Swords Dance / Poltergeist / Shadow Sneak
- `Cinderace#0`：Cinderace @ Heavy-Duty Boots [tera Fire]: Pyro Ball / U-turn / Court Change / Will-O-Wisp
- `Clefable#0`：Clefable @ Leftovers [tera Water]: Moonblast / Stealth Rock / Moonlight / Knock Off
- `Clodsire#0`：Clodsire @ Heavy-Duty Boots [tera Steel]: Recover / Earthquake / Spikes / Poison Jab
- `Corviknight#0`：Corviknight @ Rocky Helmet [tera Dragon]: Roost / U-turn / Body Press / Defog
- `Corviknight#1`：Corviknight @ Leftovers [tera Dragon]: Brave Bird / Protect / Roost / Defog
- `Dondozo#0`：Dondozo @ Leftovers [tera Fighting]: Waterfall / Rest / Curse / Sleep Talk
- `Dondozo#1`：Dondozo @ Leftovers [tera Dark]: Rest / Curse / Sleep Talk / Crunch
- `Gliscor#0`：Gliscor @ Toxic Orb [tera Normal]: Protect / Swords Dance / Facade / Knock Off
- `Gliscor#2`：Gliscor @ Toxic Orb [tera Dark]: Protect / Knock Off / Toxic / Substitute
- `Great Tusk#2`：Great Tusk @ Rocky Helmet [tera Steel]: Stealth Rock / Rapid Spin / Headlong Rush / Ice Spinner
- `Hydrapple#0`：Hydrapple @ Heavy-Duty Boots [tera Poison]: Giga Drain / Fickle Beam / Earth Power / Nasty Plot
- `Iron Crown#0`：Iron Crown @ Assault Vest [tera Steel]: Tachyon Cutter / Volt Switch / Psychic Noise / Future Sight
- `Iron Valiant#0`：Iron Valiant @ Booster Energy [tera Ghost]: Moonblast / Calm Mind / Shadow Ball / Vacuum Wave
- `Jolteon#0`：Jolteon @ Heavy-Duty Boots [tera Fairy]: Volt Switch / Thunderbolt / Alluring Voice / Calm Mind
- `Kingambit#0`：Kingambit @ Leftovers [tera Ghost]: Sucker Punch / Iron Head / Swords Dance / Kowtow Cleave
- `Kyurem#0`：Kyurem @ Assault Vest [tera Ice]: Ice Beam / Freeze-Dry / Earth Power / Blizzard
- `Landorus-Therian#1`：Landorus-Therian @ Rocky Helmet [tera Ground]: U-turn / Earthquake / Stone Edge / Stealth Rock
- `Lokix#0`：Lokix @ Choice Band [tera Bug]: First Impression / U-turn / Knock Off / Leech Life
- `Moltres#0`：Moltres @ Heavy-Duty Boots [tera Fairy]: Flamethrower / Roost / U-turn / Will-O-Wisp
- `Ninetales#0`：Ninetales @ Heat Rock [tera Ghost]: Encore / Overheat / Healing Wish / Will-O-Wisp
- `Raging Bolt#0`：Raging Bolt @ Booster Energy [tera Fairy]: Dragon Pulse / Thunderbolt / Calm Mind / Thunderclap
- `Slither Wing#0`：Slither Wing @ Rocky Helmet [tera Fire]: U-turn / First Impression / Close Combat / Flare Blitz
- `Slowking-Galar#1`：Slowking-Galar @ Rocky Helmet [tera Fairy]: Chilly Reception / Sludge Bomb / Ice Beam / Future Sight
- `Slowking-Galar#2`：Slowking-Galar @ Assault Vest [tera Water]: Sludge Bomb / Flamethrower / Psyshock / Ice Beam
- `Toxapex#0`：Toxapex @ Leftovers [tera Steel]: Baneful Bunker / Infestation / Poison Jab / Recover
- `Toxapex#1`：Toxapex @ Heavy-Duty Boots [tera Fairy]: Toxic / Toxic Spikes / Recover / Haze
- `Ursaluna#0`：Ursaluna @ Flame Orb [tera Normal]: Facade / Headlong Rush / Fire Punch / Swords Dance
- `Venusaur#0`：Venusaur @ Life Orb [tera Fire]: Weather Ball / Giga Drain / Growth / Sludge Bomb
- `Walking Wake#0`：Walking Wake @ Life Orb [tera Water]: Hydro Steam / Draco Meteor / Flip Turn / Dragon Pulse
- `Zapdos#0`：Zapdos @ Heavy-Duty Boots [tera Grass]: Discharge / U-turn / Hurricane / Roost
