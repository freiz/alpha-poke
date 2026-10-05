# gen9ou 套路库

构建时间 2026-10-04 18:51；12236 场高分 replay；命名模型 `google/gemini-3.8-flash`（只允许总结我们挖掘出的数据，英文输出）；LLM 花费 $0.376。脚本 `scripts/build_library.py`，数据 `data/library/`。

## 1. 核心与完整队伍

| 成员 | 次数 | 胜率 | 名称 | 标签 | 胜利路线 |
|---|---|---|---|---|---|
| Clodsire + Corviknight + Dondozo + Gliscor + Toxapex | 774 | 54% | Classic Stall | stall, hazard_stack, setup | Dondozo, Gliscor |
| Cinderace + Kingambit + Kyurem + Landorus-Therian + Ogerpon-Wellspring + Slowking-Galar | 712 | 52% | Bulky Offense Pivot | bulky_offense, volturn, setup, snow | Kingambit, Kyurem, Ogerpon-Wellspring |
| Great Tusk + Hydrapple + Jolteon + Kingambit + Moltres + Slowking-Galar | 466 | 53% | Balance Pivot | balance, volturn, setup | Kingambit, Hydrapple, Jolteon |
| Clefable + Clodsire + Corviknight + Dondozo + Gliscor + Toxapex | 391 | 49% | Pure Stall | stall, hazard_stack, setup | Dondozo, Gliscor |
| Blissey + Clodsire + Corviknight + Dondozo + Gliscor + Toxapex | 359 | 59% | Stall | stall, hazard_stack, setup | Dondozo, Gliscor, Corviknight |
| Cinderace + Kyurem + Slowking-Galar | 1497 | 51% | Snow Pivot Bulky Offense | bulky_offense, balance, snow, volturn | Kyurem, Cinderace |
| Blissey + Corviknight + Dondozo + Gliscor | 602 | 56% | Stall Hazard Stack | stall, hazard_stack, setup | Dondozo, Blissey, Gliscor |
| Araquanid + Gholdengo + Iron Moth + Iron Valiant + Kingambit + Raging Bolt | 513 | 50% | Sticky Web Hyper Offense | hyper_offense, sticky_web, setup | Kingambit, Iron Moth, Iron Valiant, Raging Bolt, Gholdengo |
| Great Tusk + Ninetales + Walking Wake | 1036 | 55% | Sun Bulky Offense | sun, bulky_offense, volturn | Walking Wake, Great Tusk |
| Great Tusk + Ninetales + Venusaur + Walking Wake | 503 | 57% | Sun Offense | sun, hyper_offense, setup | Venusaur, Walking Wake |
| Ceruledge + Great Tusk + Ninetales + Slither Wing + Venusaur + Walking Wake | 254 | 58% | Sun Offense | sun, hyper_offense, setup, volturn | Venusaur, Walking Wake, Ceruledge |
| Alomomola + Cinderace + Iron Crown + Lokix + Ursaluna + Zapdos | 209 | 52% | Pivot Balance | balance, volturn | Lokix, Ursaluna |
| Blissey + Gliscor + Toxapex | 633 | 57% | Stall Hazard Stack | stall, hazard_stack, setup | Gliscor, Blissey |
| Corviknight + Dondozo | 1308 | 53% | Physical Defensive Stall | stall, balance, setup | Corviknight, Dondozo |
| Clefable + Dragonite + Gholdengo + Iron Moth + Skarmory + Ting-Lu | 312 | 49% | Hazard Stack Balance | balance, hazard_stack, setup | Clefable, Dragonite |
| Ceruledge + Great Tusk + Ninetales + Walking Wake | 482 | 56% | Sun Offense | sun, hyper_offense, setup | Ceruledge, Walking Wake |
| Frosmoth + Iron Hands + Pawmot + Pincurchin + Raichu-Alola + Rotom-Wash | 95 | 45% | Electric Terrain Screens Offense | terrain, screens, hyper_offense, setup, volturn | Iron Hands, Frosmoth, Raichu-Alola |
| Kingambit + Kyurem + Landorus-Therian | 1216 | 52% | Dragon-Steel-Ground Balance | balance, bulky_offense, hazard_stack, volturn, setup | Kingambit, Kyurem |
| Blissey + Gliscor + Ogerpon + Pecharunt + Samurott-Hisui + Skarmory | 199 | 54% | Spikes Hazard Stack Stall | stall, hazard_stack, setup | Gliscor, Blissey |
| Ceruledge + Cresselia + Glimmora + Kingambit + Ogerpon-Wellspring + Zamazenta-* | 328 | 56% | Screens Hyper Offense | hyper_offense, screens, setup, hazard_stack | Kingambit, Ceruledge, Cresselia, Ogerpon-Wellspring |
| Dragapult + Iron Crown + Kingambit + Landorus-Therian + Primarina + Samurott-Hisui | 237 | 52% | Bulky Hazard Stack VoltTurn | bulky_offense, hazard_stack, volturn, setup | Kingambit, Dragapult |
| Cinderace + Corviknight + Dondozo + Kyurem + Slowking-Galar + Ting-Lu | 243 | 51% | Balance | balance, volturn, setup | Dondozo, Kyurem |
| Dragonite + Gholdengo + Great Tusk + Samurott-Hisui | 818 | 52% | Bulky Hazard Stack Offense | bulky_offense, hazard_stack, setup | Dragonite, Gholdengo |
| Dragonite + Gholdengo + Great Tusk | 1557 | 51% | Bulky Hazard Control Offense | bulky_offense, setup, hazard_stack | Dragonite, Gholdengo |
| Dragapult + Iron Treads + Moltres + Raging Bolt + Samurott-Hisui + Zamazenta-* | 227 | 51% | Spikes Bulky Offense | bulky_offense, hazard_stack, volturn | Dragapult, Zamazenta-* |
| Excadrill + Tyranitar | 456 | 52% | Sand Bulky Offense | sand, bulky_offense, setup, hazard_stack | Excadrill |
| Ceruledge + Darkrai + Glimmora + Iron Valiant + Ogerpon-Wellspring + Raging Bolt | 223 | 61% | Hyper Offense | hyper_offense, hazard_stack, setup | Ceruledge, Darkrai, Iron Valiant, Ogerpon-Wellspring, Raging Bolt |
| Dragonite + Gholdengo + Great Tusk + Kyurem + Samurott-Hisui | 447 | 51% | Spikes Hazard Stack Bulky Offense | hazard_stack, bulky_offense, setup | Dragonite, Gholdengo, Kyurem |
| Glimmora + Kingambit + Ogerpon-Wellspring | 1030 | 52% | Hyper Offense Hazard Stack | hyper_offense, hazard_stack, setup | Kingambit, Ogerpon-Wellspring |
| Clefable + Dragonite + Ting-Lu | 555 | 50% | Hazard Stack Balance | balance, hazard_stack, setup | Dragonite, Clefable |
| Cresselia + Glimmora + Zamazenta-* | 631 | 50% | Hazard Stack Balance | hazard_stack, balance, setup, screens | Cresselia, Zamazenta-* |
| Ceruledge + Glimmora + Ogerpon-Wellspring | 651 | 57% | Hazard Stack Hyper Offense | hyper_offense, hazard_stack, setup | Ceruledge, Ogerpon-Wellspring |
| Dragonite + Garchomp + Gholdengo + Glimmora + Iron Moth + Umbreon | 129 | 49% | Hazard Stack Offense | hazard_stack, bulky_offense, setup | Dragonite, Garchomp, Iron Moth |
| Ninetales + Raging Bolt + Walking Wake | 403 | 53% | Sun Offense | sun, hyper_offense, setup, volturn | Raging Bolt, Walking Wake |
| Gholdengo + Iron Valiant + Raging Bolt | 880 | 47% | Offensive Setup Spam | hyper_offense, setup | Gholdengo, Iron Valiant, Raging Bolt |
| Araquanid + Gholdengo + Great Tusk + Iron Moth + Iron Valiant + Zarude-Dada | 136 | 54% | Sticky Web Hyper Offense | hyper_offense, sticky_web, setup | Gholdengo, Great Tusk, Iron Moth, Iron Valiant, Zarude-Dada |
| Alomomola + Cinderace + Hoopa-Unbound + Iron Valiant + Landorus-Therian + Pecharunt | 124 | 53% | VoltTurn Bulky Offense | bulky_offense, volturn, balance | Hoopa-Unbound, Iron Valiant, Landorus-Therian |
| Iron Valiant + Kingambit + Raging Bolt | 890 | 47% | Booster Setup Hyper Offense | hyper_offense, setup | Kingambit, Iron Valiant, Raging Bolt |
| Gliscor + Moltres + Ogerpon + Raging Bolt + Samurott-Hisui + Tinkaton | 127 | 46% | Hazard Stack Balance | balance, hazard_stack, volturn, setup | Gliscor, Raging Bolt |
| Fezandipiti + Great Tusk + Kingambit + Samurott-Hisui + Serperior + Zapdos | 107 | 48% | Spikes Bulky Offense | bulky_offense, hazard_stack, volturn, setup | Kingambit, Serperior |
| Enamorus + Glimmora + Kingambit + Ogerpon-Wellspring | 369 | 54% | Hazard Stack Hyper Offense | hyper_offense, hazard_stack, setup | Kingambit, Enamorus, Ogerpon-Wellspring |
| Cinderace + Enamorus + Great Tusk + Kyurem + Ninetales + Walking Wake | 142 | 54% | Sun Offense | sun, bulky_offense, volturn | Walking Wake, Enamorus, Cinderace |
| Dragonite + Gholdengo + Glimmora + Great Tusk + Kyurem + Samurott-Hisui | 239 | 50% | Hazard Stack Hyper Offense | hyper_offense, hazard_stack, setup | Dragonite, Kyurem, Gholdengo |
| Cresselia + Ogerpon-Wellspring + Zamazenta-* | 646 | 53% | Bulky Balance Setup | bulky_offense, balance, setup, screens | Cresselia, Ogerpon-Wellspring, Zamazenta-* |
| Blaziken + Enamorus + Glimmora + Kingambit + Ogerpon-Wellspring + Raging Bolt | 135 | 52% | Hyper Offense | hyper_offense, hazard_stack, setup | Kingambit, Blaziken |
| Glimmora + Ogerpon-Wellspring + Zamazenta-* | 724 | 52% | Hyper Offense Hazard Stack | hyper_offense, hazard_stack, setup, screens | Ogerpon-Wellspring, Zamazenta-* |
| Gliscor + Ogerpon + Samurott-Hisui | 399 | 50% | Hazard Stack Bulky Offense | bulky_offense, hazard_stack, setup, volturn | Gliscor, Ogerpon |
| Excadrill + Garganacl + Moltres + Pecharunt + Tyranitar + Zamazenta-* | 86 | 51% | Sand Balance | sand, balance, setup, volturn | Excadrill, Zamazenta-* |
| Corviknight + Slowking-Galar + Ting-Lu | 436 | 51% | Fat Balance Hazard Stack | balance, hazard_stack, volturn | Corviknight, Ting-Lu |
| Glimmora + Iron Valiant + Kyurem + Moltres + Raging Bolt + Ting-Lu | 146 | 51% | Hazard Stack Bulky Offense | bulky_offense, hazard_stack, setup | Iron Valiant, Kyurem, Raging Bolt |
| Cresselia + Great Tusk + Ninetales + Raging Bolt + Walking Wake | 161 | 52% | Sun Bulky Offense | sun, bulky_offense, setup | Cresselia, Raging Bolt, Walking Wake |
| Cinderace + Corviknight + Ting-Lu | 413 | 50% | Bulky Hazard Control Balance | bulky_offense, balance, hazard_stack, volturn | Cinderace, Corviknight |
| Hawlucha + Raging Bolt + Rillaboom | 225 | 45% | Grassy Terrain Hyper Offense | terrain, hyper_offense, setup | Hawlucha, Raging Bolt |
| Dragonite + Gholdengo + Gliscor + Great Tusk + Samurott-Hisui + Walking Wake | 167 | 48% | Spikes Hazard Stack Balance | balance, hazard_stack, setup, volturn | Dragonite, Walking Wake, Gholdengo |
| Blaziken + Iron Moth + Iron Valiant + Kingambit + Landorus-Therian + Samurott-Hisui | 115 | 39% | Hazard Stack Hyper Offense | hyper_offense, hazard_stack, setup | Blaziken, Kingambit, Iron Valiant |
| Iron Treads + Raging Bolt + Zamazenta-* | 515 | 51% | Bulky Setup Offense | bulky_offense, setup, hazard_stack, screens | Raging Bolt, Zamazenta-* |
| Cinderace + Great Tusk + Kingambit + Kyurem + Slowking-Galar + Zapdos | 153 | 49% | Slowking-Galar + Kyurem Pivot Balance | balance, volturn, snow, setup | Kingambit, Kyurem |
| Glimmora + Hawlucha + Kingambit + Raging Bolt + Rillaboom | 127 | 44% | Grassy Terrain Hyper Offense | terrain, hyper_offense, hazard_stack, setup | Hawlucha, Kingambit, Raging Bolt |
| Gliscor + Moltres + Tinkaton | 225 | 44% | Spikes Balance | balance, hazard_stack, volturn, setup | Gliscor, Moltres |
| Glimmora + Great Tusk + Iron Crown + Moltres + Raging Bolt + Rillaboom | 107 | 50% | Hyper Offense | hyper_offense, hazard_stack, terrain, setup | Great Tusk, Moltres, Raging Bolt, Rillaboom |
| Gliscor + Moltres + Ogerpon | 299 | 48% | Bulky VoltTurn Balance | balance, bulky_offense, volturn, hazard_stack, setup | Gliscor, Ogerpon |
| Cresselia + Dragapult + Garchomp + Kingambit + Ogerpon + Pecharunt | 91 | 43% | Hazard Stack Balance | balance, hazard_stack, setup, volturn | Cresselia, Kingambit, Pecharunt |
| Cresselia + Raging Bolt + Zamazenta-* | 488 | 47% | Bulky Setup Balance | balance, bulky_offense, setup, screens | Cresselia, Raging Bolt, Zamazenta-* |
| Gholdengo + Great Tusk + Iron Valiant + Kingambit + Ogerpon-Wellspring + Raging Bolt | 213 | 41% | Standard Bulky Offense | bulky_offense, setup, volturn | Kingambit, Raging Bolt, Gholdengo |
| Cresselia + Dragapult + Garchomp + Kingambit | 185 | 48% | Hazard Stack Bulky Offense | bulky_offense, hazard_stack, setup | Cresselia, Kingambit |
| Cresselia + Iron Treads + Kyurem + Ogerpon-Wellspring + Wo-Chien + Zamazenta-* | 91 | 57% | Balance | balance, setup | Ogerpon-Wellspring, Zamazenta-* |
| Ceruledge + Cresselia + Hatterene + Raging Bolt + Ursaluna + Zamazenta-* | 89 | 46% | Screens Trick Room Hybrid Offense | hyper_offense, trick_room, screens, setup | Ceruledge, Cresselia, Ursaluna |
| Darkrai + Garganacl + Moltres + Ogerpon-Wellspring | 171 | 57% | Bulky Offense | bulky_offense, balance, setup, volturn | Darkrai, Ogerpon-Wellspring, Garganacl |
| Cresselia + Glimmora + Raging Bolt + Zamazenta-* | 248 | 44% | Hazard Stack Setup Balance | bulky_offense, balance, hazard_stack, setup, screens | Cresselia, Raging Bolt, Zamazenta-* |
| Cresselia + Kingambit + Zamazenta-* | 571 | 52% | Bulky Setup Balance | bulky_offense, balance, setup, screens | Cresselia, Kingambit, Zamazenta-* |
| Ceruledge + Gholdengo + Ogerpon-Cornerstone + Raging Bolt + Ribombee | 94 | 55% | Sticky Web Hyper Offense | hyper_offense, sticky_web, setup | Ceruledge, Gholdengo, Ogerpon-Cornerstone, Raging Bolt |
| Dragonite + Enamorus + Gholdengo + Glimmora + Kingambit + Ogerpon-Wellspring | 130 | 58% | Red Card Glimmora Hyper Offense | hyper_offense, hazard_stack, setup | Dragonite, Kingambit |
| Darkrai + Garganacl + Iron Treads + Moltres + Ogerpon-Wellspring + Zamazenta-* | 87 | 57% | Bulky Offense Balance | balance, bulky_offense, hazard_stack, volturn, setup | Zamazenta-*, Darkrai, Garganacl |
| Cinderace + Great Tusk + Kyurem + Mandibuzz + Ogerpon-Wellspring + Slowking-Galar | 98 | 45% | Snow Balance Pivot | balance, snow, volturn | Kyurem, Ogerpon-Wellspring |
| Cresselia + Hatterene + Ursaluna | 186 | 51% | Trick Room Bulky Offense | trick_room, setup, bulky_offense | Cresselia, Ursaluna |
| Deoxys-Speed + Dragonite + Gholdengo + Great Tusk + Iron Valiant + Zamazenta-* | 129 | 43% | Hyper Offense Hazard Stack | hyper_offense, hazard_stack, setup | Dragonite, Great Tusk |
| Cresselia + Dragapult + Garchomp + Keldeo-Resolute + Kingambit | 81 | 54% | Bulky Offense Hazard Stack | bulky_offense, hazard_stack, volturn, setup | Cresselia, Kingambit |
| Hawlucha + Iron Valiant + Kingambit + Raging Bolt + Rillaboom | 99 | 38% | Grassy Terrain Hyper Offense | terrain, hyper_offense, setup | Hawlucha, Kingambit, Raging Bolt |
| Alomomola + Great Tusk + Lokix + Slowking-Galar | 138 | 48% | RegenVolt Bulky Offense | bulky_offense, balance, volturn, snow | Lokix, Great Tusk |
| Hatterene + Kingambit + Ninetales + Raging Bolt + Walking Wake | 107 | 56% | Sun Offense | sun, hyper_offense, setup | Kingambit, Raging Bolt, Walking Wake |
| Araquanid + Cresselia + Dragapult + Great Tusk + Iron Moth + Kingambit | 88 | 50% | Sticky Web Hyper Offense | hyper_offense, sticky_web, setup | Cresselia, Iron Moth, Kingambit |
| Kingdra + Pelipper | 126 | 45% | Rain Offense | rain, hyper_offense, volturn | Kingdra |
| Iron Treads + Overqwil + Pelipper | 82 | 51% | Rain Bulky Offense | rain, bulky_offense, hazard_stack, volturn | Iron Treads, Overqwil |
| Darkrai + Dragonite + Garganacl + Great Tusk + Moltres + Ogerpon-Wellspring | 84 | 57% | Balance Hazard Stack | balance, hazard_stack, setup | Dragonite, Darkrai |
| Cinderace + Cresselia + Great Tusk + Ninetales + Walking Wake | 95 | 58% | Sun Bulky Offense | sun, bulky_offense, setup, volturn | Walking Wake, Cresselia |
| Great Tusk + Hatterene + Kingambit + Kyurem + Slowking-Galar + Tornadus-Therian | 87 | 42% | Snow Balance | balance, volturn, snow, setup | Kingambit, Kyurem |
| Overqwil + Pelipper + Raging Bolt | 83 | 53% | Rain Bulky Offense | rain, bulky_offense, volturn, setup | Raging Bolt |
| Ceruledge + Great Tusk + Ogerpon-Cornerstone + Ribombee | 88 | 52% | Sticky Web Hyper Offense | hyper_offense, sticky_web, setup | Ceruledge, Ogerpon-Cornerstone |
| Ceruledge + Gholdengo + Ribombee | 185 | 57% | Sticky Web Hyper Offense | hyper_offense, sticky_web, setup | Ceruledge, Gholdengo |
| Ceruledge + Kingambit + Ninetales + Raging Bolt + Walking Wake | 87 | 48% | Sun Offense | sun, hyper_offense, setup | Ceruledge, Kingambit, Raging Bolt, Walking Wake |
| Garganacl + Moltres + Pecharunt | 154 | 53% | Defensive Status Balance | balance, volturn, setup | Garganacl, Pecharunt |
| Iron Treads + Kyurem + Ogerpon-Wellspring + Zamazenta-* | 202 | 52% | Bulky Balance Setup Core | bulky_offense, balance, setup, screens | Ogerpon-Wellspring, Zamazenta-* |
| Darkrai + Dragonite + Garganacl + Great Tusk | 145 | 58% | Balance Hazard Control | balance, setup, hazard_stack | Darkrai, Dragonite |
| Ceruledge + Gholdengo + Great Tusk + Raging Bolt + Ribombee | 93 | 57% | Sticky Web Hyper Offense | hyper_offense, sticky_web, hazard_stack, setup | Ceruledge, Gholdengo, Raging Bolt |
| Clefable + Dragonite + Gholdengo + Gliscor + Samurott-Hisui + Zamazenta-* | 81 | 47% | Spikes Hazard Stack Balance | balance, hazard_stack, setup | Dragonite, Gliscor, Zamazenta-* |
| Dragonite + Gholdengo + Moltres + Ogerpon-Wellspring + Ting-Lu + Zamazenta-* | 88 | 60% | Hazard Stack Balance | balance, hazard_stack, setup | Dragonite, Zamazenta-* |
| Deoxys-Speed + Iron Valiant + Zamazenta-* | 234 | 44% | Hyper Offense | hyper_offense, hazard_stack, setup, screens | Iron Valiant, Zamazenta-* |
| Hatterene + Raging Bolt + Walking Wake | 205 | 58% | Sun Bulky Offense | sun, bulky_offense, setup, volturn | Raging Bolt, Walking Wake |
| Dragonite + Gholdengo + Gliscor + Moltres + Ogerpon | 85 | 47% | Balance Hazard Stack | balance, hazard_stack, setup, volturn | Dragonite, Gholdengo, Gliscor |
| Iron Treads + Kingambit + Pelipper + Raging Bolt | 93 | 47% | Rain Offense | rain, bulky_offense, volturn, setup | Kingambit, Raging Bolt |
| Ceruledge + Dragonite + Hatterene + Ogerpon-Cornerstone | 82 | 46% | Physical Setup Offense | hyper_offense, setup | Ceruledge, Dragonite, Ogerpon-Cornerstone |
| Darkrai + Dragonite + Great Tusk + Hatterene | 145 | 55% | Bulky Setup Offense | bulky_offense, setup | Darkrai, Dragonite |
| Araquanid + Ceruledge + Gholdengo + Great Tusk + Iron Valiant | 84 | 55% | Sticky Web Hyper Offense | hyper_offense, sticky_web, hazard_stack, setup | Ceruledge, Iron Valiant, Gholdengo |
| Alomomola + Corviknight + Great Tusk + Kyurem + Slowking-Galar | 83 | 53% | Snow Pivot Balance | balance, snow, volturn | Kyurem, Corviknight, Great Tusk |
| Kyurem + Landorus-Therian + Pecharunt + Samurott-Hisui + Zamazenta-* | 81 | 52% | Bulky Hazard Stack Balance | balance, bulky_offense, hazard_stack, volturn, setup | Kyurem, Zamazenta-*, Pecharunt |
| Dragonite + Gholdengo + Great Tusk + Kingambit + Ribombee | 94 | 52% | Sticky Web Hyper Offense | hyper_offense, sticky_web, hazard_stack, setup | Dragonite, Kingambit, Gholdengo |
| Darkrai + Great Tusk + Kingambit + Primarina | 106 | 59% | Bulky Balance Offense | bulky_offense, balance, setup | Darkrai, Kingambit, Primarina |
| Darkrai + Dragonite + Great Tusk + Ogerpon-Wellspring | 157 | 55% | Bulky Setup Offense | bulky_offense, setup, volturn | Darkrai, Dragonite, Ogerpon-Wellspring |
| Alomomola + Iron Treads + Tornadus-Therian | 85 | 49% | Regenerator Pivot Balance | balance, bulky_offense, volturn, hazard_stack | Tornadus-Therian, Iron Treads |
| Ceruledge + Dragonite + Hatterene + Kingambit | 108 | 44% | Hyper Offense Setup Spam | hyper_offense, setup | Ceruledge, Dragonite, Kingambit |
| Darkrai + Gholdengo + Hatterene + Ogerpon-Wellspring | 87 | 57% | Bulky Setup Offense | bulky_offense, setup, volturn | Darkrai, Gholdengo, Ogerpon-Wellspring |
| Iron Treads + Iron Valiant + Kingambit + Kyurem | 111 | 42% | Hyper Offense | hyper_offense, hazard_stack, setup | Iron Valiant, Kingambit, Kyurem |

### 说明（前 15 个）

**Classic Stall** — Clodsire + Corviknight + Dondozo + Gliscor + Toxapex

- Game plan: The core aims to completely stonewall opposing offensive threats through passive damage, continuous recovery, and multiple defensive layers. Clodsire, Gliscor, and Toxapex deploy hazards like Spikes, Stealth Rock, and Toxic Spikes while using Toxic to wear down the opposition. Once the opposing team is weakened or neutralized via Haze and entry hazards, Dondozo with Curse or Gliscor with Swords Dance can clean up the remaining members.
- Roles: Clodsire: Special wall and hazard setter; Corviknight: Physical wall, entry hazard remover, and pivot; Dondozo: Physical wall and setup sweeper; Gliscor: Stallbreaker, hazard stacker, and status sponge; Toxapex: Defensive anchor and status spreader
- Weaknesses: The core is heavily vulnerable to powerful wallbreakers capable of bypassing physical defense through special attacks, such as Kyurem or Specs Dragapult. Taunt users and Trick Choice-item lock strategies can severely disrupt their passive defensive cycling. Furthermore, strong Electric- and Ground-type coverage can overload Corviknight, Toxapex, and Clodsire.
- How to play against: Aggressively apply pressure with strong wallbreakers that carry Taunt to shut down Recover, Roost, and Rest. Utilize Knock Off to remove Heavy-Duty Boots and Leftovers, forcing the defensive pieces to take relentless hazard damage. Timing a well-placed Trick or using setup sweepers immune to status, like Gholdengo, can easily dismantle their defensive loops.

**Bulky Offense Pivot** — Cinderace + Kingambit + Kyurem + Landorus-Therian + Ogerpon-Wellspring + Slowking-Galar

- Game plan: The team leverages a robust pivot core using Slowking-Galar's Chilly Reception, Landorus-Therian's U-turn, and Cinderace's U-turn to generate momentum and maintain hazard control with Court Change. Slowking-Galar sets snow via Chilly Reception to bolster Kyurem's Blizzard and Freeze-Dry offenses while pivoting safely. Ultimately, Kingambit with Supreme Overlord and Swords Dance cleans up late-game alongside strong offensive pressure from Ogerpon-Wellspring.
- Roles: Cinderace: Hazard control and pivot; Kingambit: Late-game setup sweeper; Kyurem: Specially offensive wallbreaker and tank; Landorus-Therian: Physical pivot and speed control; Ogerpon-Wellspring: Offensive utility and wallbreaker; Slowking-Galar: Specially defensive pivot and snow setter
- Weaknesses: Fast offensive Ghost- and Dark-types like Dragapult and Darkrai can exploit Slowking-Galar and put immense pressure on Kingambit. Bulky Ground-types like opposing Great Tusk can also disrupt the core if Landorus-Therian is worn down or locked into an unfavorable move.
- How to play against: Maintain entry hazard pressure carefully by preventing Court Change or forcing Cinderace out with faster offensive threats. Chip Kingambit early before it gains maximum Supreme Overlord boosts, and preserve faster Fighting- and Ground-type coverage to exploit the team's defensive gaps.

**Balance Pivot** — Great Tusk + Hydrapple + Jolteon + Kingambit + Moltres + Slowking-Galar

- Game plan: Control the flow of the match using defensive pivots like Moltres, Slowking-Galar, and Great Tusk to absorb hits, spread burns, and control entry hazards. Jolteon maintains momentum with Volt Switch and applies offensive pressure alongside Hydrapple. Once the opposing team is sufficiently weakened, setup sweepers like Kingambit, Hydrapple, or Jolteon close out the game.
- Roles: Great Tusk: Physical wall, entry hazard setter, and spinner; Hydrapple: Bulky special setup sweeper; Jolteon: Fast pivot and special setup sweeper; Kingambit: Late-game physical setup cleaner; Moltres: Physical defensive pivot and status spreader; Slowking-Galar: Special tank and offensive coverage pivot
- Weaknesses: Strong Ground- and Dragon-type wallbreakers can heavily strain the defensive core if Moltres or Great Tusk are chipped down. Without Chilly Reception on Slowking-Galar and relying solely on Jolteon for Volt Switch, the team can sometimes struggle to safely reposition its slower setup threats. Faster revenge killers can exploit Jolteon or Kingambit if priority Sucker Punch fails or is played around.
- How to play against: Apply relentless pressure with Ground-type wallbreakers such as Ting-Lu or Gliscor to deter Jolteon's Volt Switch and force Great Tusk into unfavorable trades. Exploit Slowking-Galar's lack of reliable recovery moves by chipping it with physical attacks or entry hazards. Save a dedicated check to Kingambit, playing around Sucker Punch with Substitute, Encore, or defensive setup moves.

**Pure Stall** — Clefable + Clodsire + Corviknight + Dondozo + Gliscor + Toxapex

- Game plan: The team aims to completely shut down opposing offenses through an impenetrable defensive wall and extensive passive recovery. Hazards are set via Clefable and Clodsire while Gliscor and Toxapex wear down switch-ins with status, Infestation, and item removal via Knock Off. Dondozo acts as the primary endgame win condition by using Curse alongside Rest and Sleep Talk to outlast and sweep neutralized teams.
- Roles: Clefable: Hazard setter and utility wall; Clodsire: Specially defensive hazard setter; Corviknight: Physical wall and hazard removal; Dondozo: Setup sweeper and physical wall; Gliscor: Status spreader and stallbreaker; Toxapex: Trapper and defensive pivot
- Weaknesses: Strong wallbreakers with Taunt, Substitute, or boosting moves like Nasty Plot and Calm Mind can exploit the team's low immediate offensive presence. Powerful wallbreakers such as Kyurem, Gholdengo, and Darkrai can overload Corviknight and Clodsire if hazards are kept off their side.
- How to play against: Preserve high-powered mixed attackers and stallbreakers equipped with Taunt or Trick to disrupt their recovery cycles. Prioritize denying Spikes and Stealth Rock early to prevent passive damage from accumulating, and avoid letting Dondozo accumulate Curse boosts uncontested.

**Stall** — Blissey + Clodsire + Corviknight + Dondozo + Gliscor + Toxapex

- Game plan: The team aims to exhaust the opponent's offensive resources by leveraging immense defensive bulk, passive damage, and reliable recovery. Blissey, Clodsire, and Toxapex deploy hazards like Stealth Rock, Spikes, and Toxic Spikes to wear down opposing teams, while Toxapex neutralizes setup threats with Haze. In the endgame, the team wins through attrition or by sweeping with win conditions such as Curse Dondozo, Swords Dance Gliscor, or Iron Defense Corviknight.
- Roles: Blissey: Special wall and entry hazard setter; Clodsire: Specially defensive hazard setter; Corviknight: Physical wall, hazard removal, and setup sweeper; Dondozo: Physical wall, status absorber, and setup sweeper; Gliscor: Status absorber, item remover, and setup win condition; Toxapex: Defensive disruptor, status spreader, and setup check
- Weaknesses: Heavy wallbreakers with mixed or boosting capabilities, such as Kyurem, Gholdengo, and Hoopa-Unbound, can break past individual defensive pivots. Relentless Knock Off and hazard pressure can eventually chip down boots-reliant members if Corviknight cannot safely use Defog. Trick users carrying Choice items can cripple critical walls like Blissey, Dondozo, or Clodsire.
- How to play against: Aggressively remove Heavy-Duty Boots with Knock Off to force the stall core to take entry hazard damage on every switch. Utilize Taunt and Substitute to prevent recovery, status, and hazard setup. Powerful mixed attackers or setup sweepers paired with Taunt can overload their defensive checks and break the defensive cycle.

**Snow Pivot Bulky Offense** — Cinderace + Kyurem + Slowking-Galar

- Game plan: Slowking-Galar uses Chilly Reception to establish snow and safely pivot offensive threats into play while controlling hazards alongside Cinderace's Court Change and U-turn. Kyurem capitalizes on the snow boost and Slowking-Galar's Future Sight support to punch massive holes using powerful attacks like Ice Beam, Freeze-Dry, and Draco Meteor, or stall out foes behind Substitute. Cinderace cleans up weakened teams with Pyro Ball and Sucker Punch while maintaining momentum and controlling entry hazards.
- Roles: Cinderace: Hazard control, momentum pivot, and cleaner; Kyurem: Wallbreaker and stallbreaker; Slowking-Galar: Specially defensive pivot and snow setter
- Weaknesses: Ground-type attackers such as Great Tusk and Landorus-Therian threaten Slowking-Galar and Cinderace with super effective STAB moves. Fast offensive threats like Darkrai, Dragapult, and Weavile can outspeed the core and exert tremendous offensive pressure before Kyurem or Slowking-Galar can position safely.
- How to play against: Apply relentless physical pressure using Ground- and Dark-types to exploit Slowking-Galar's lower physical bulk and prevent easy Chilly Reception pivots. Keep entry hazards up cautiously, baiting Court Change with aggressive double switches, and force Kyurem into unfavorable Choice locks with Steel- and Fairy-type defensive backbones.

**Stall Hazard Stack** — Blissey + Corviknight + Dondozo + Gliscor

- Game plan: The core aims to completely stonewall opposing offensive threats through an impenetrable defensive backbone while wearing teams down with entry hazards. Blissey and Gliscor set up Stealth Rock and Spikes alongside Toxic and Knock Off to chip away at the opponent and remove crucial items. Defensive pivots Corviknight and Dondozo check physical attackers and clear hazards with Defog or heal with Rest, ultimately enabling setup sweepers like Curse Dondozo, Calm Mind Blissey, or Swords Dance Gliscor to close out the game.
- Roles: Blissey: Special wall and hazard setter; Corviknight: Physical wall and hazard remover; Dondozo: Physical setup tank and wall; Gliscor: Hazard setter, status spreader, and setup sweeper
- Weaknesses: Strong mixed wallbreakers and powerful setup attackers with Taunt or substitute strategies can disrupt the core's recovery cycles. Additionally, without Unaware on Dondozo (running Water Absorb), opposing setup sweepers such as Dragon Dance Roaring Moon or Swords Dance Ogerpon-Wellspring can overwhelm the physical defensive backbone.
- How to play against: Pressure the core early with Taunt, Trick, and aggressive double-switches to prevent Gliscor and Blissey from freely stacking hazards. Exploit the lack of Unaware on Dondozo by setting up with strong physical or mixed sweepers that can break through Corviknight and Dondozo before they accumulate defensive boosts.

**Sticky Web Hyper Offense** — Araquanid + Gholdengo + Iron Moth + Iron Valiant + Kingambit + Raging Bolt

- Game plan: Araquanid sets Sticky Web early, using Custap Berry alongside Endeavor or high-damage Water Bubble Surf to pressure the opponent and create momentum. Gholdengo denies hazard removal with Good as Gold and threatens balance cores with Nasty Plot, Make It Rain, and Shadow Ball. The remaining Booster Energy and Supreme Overlord sweepers capitalize on the opponent's lowered speed to set up with Calm Mind or Swords Dance and overwhelm defensive counterplay.
- Roles: Araquanid: Sticky Web lead and Custap Endeavor user; Gholdengo: Spinblocker and special setup sweeper; Iron Moth: Special setup cleaner and wallbreaker; Iron Valiant: Special setup cleaner; Kingambit: Physical setup cleaner and late-game revenge killer; Raging Bolt: Setup sweeper and priority revenge killer
- Weaknesses: Heavy-Duty Boots users and naturally immune Flying-types or levitators bypass Sticky Web entirely, retaining their speed advantage. Strong priority users like Dragonite, Rillaboom, and opposing Kingambit can pick off damaged sweepers before they attack. The team lacks entry hazard removal of its own, meaning opposing Spikes and Stealth Rock quickly wear down the lineup.
- How to play against: Prevent Araquanid from freely setting hazards by leading with Taunt, fast offensive pressure, or Magic Bounce. Keep entry hazards off your side using Court Change or Heavy-Duty Boots pivots to maintain the speed advantage. Utilize strong priority moves or defensive Unaware Pokemon like Dondozo and Clodsire to halt setup sweeps from Kingambit and Raging Bolt.

**Sun Bulky Offense** — Great Tusk + Ninetales + Walking Wake

- Game plan: Ninetales establishes prolonged harsh sunlight with Heat Rock and Drought, providing utility via Will-O-Wisp, Encore, or Healing Wish to enable its teammates. Great Tusk controls entry hazards with Rapid Spin and Stealth Rock while leveraging Protosynthesis in the sun to output heavy physical damage or wall opposing attackers. Walking Wake acts as the premier wallbreaker and cleaner, capitalizing on sun-boosted Hydro Steam, Protosynthesis boosts, and high-powered attacks like Draco Meteor and Flamethrower.
- Roles: Great Tusk: Hazard remover, hazard setter, physical attacker; Ninetales: Sun setter, supportive pivot; Walking Wake: Special wallbreaker, cleaner, offensive pivot
- Weaknesses: The core relies heavily on sun uptime, making opposing weather setters like Pelipper, Politoed, or Tyranitar disruptive to their primary offensive pressure. Strong specially offensive threats, particularly Dragon- and Fairy-types such as Dragapult, Iron Valiant, or Choice Specs Kyurem, can exploit the core's lack of natural special bulk.
- How to play against: Disrupt Ninetales early to prevent it from freely setting Drought, and contest weather turns using alternative weather setters or slow pivoting. Utilize specially defensive walls that resist Water and Fire to absorb Walking Wake's sun-boosted attacks, and pressure Great Tusk to prevent it from safely clearing hazards.

**Sun Offense** — Great Tusk + Ninetales + Venusaur + Walking Wake

- Game plan: Ninetales sets extended sun with Drought and Heat Rock while supporting the team with Encore, Will-O-Wisp, or Healing Wish. Great Tusk provides entry hazard management using Stealth Rock and Rapid Spin alongside potent offensive or defensive utility. Under active sunlight, Venusaur and Walking Wake break through opposing teams using Growth boosts and boosted Hydro Steam attacks respectively.
- Roles: Great Tusk: Hazard setter and spinner; Ninetales: Sun setter and disruptor; Venusaur: Setup sweeper and wallbreaker; Walking Wake: Special wallbreaker and sweeper
- Weaknesses: Opposing weather setters like Pelipper or Politoed disrupt the core's primary game plan by overriding sun. The team also suffers against priority attackers like Dragonite and strong Choice Scarf users that can revenge kill Venusaur and Walking Wake before they sweep.
- How to play against: Preserve alternative weather setters or stall out the sun turns by cycling bulky defensive walls. Target Ninetales early to restrict sun uptime, and leverage priority moves or hazards to wear down the frail offensive threats.

**Sun Offense** — Ceruledge + Great Tusk + Ninetales + Slither Wing + Venusaur + Walking Wake

- Game plan: Ninetales provides extended sunlight with Drought and Heat Rock, enabling swift offensive pressure across the board while utilizing Encore and Healing Wish to support setup teammates. Great Tusk establishes Stealth Rock and clears opposing hazards with Rapid Spin, while Slither Wing uses Assault Vest alongside U-turn and First Impression to pivot and check threats. Choice Specs Walking Wake unleashes devastating sun-boosted Hydro Steam attacks, creating openings for Venusaur and Ceruledge to sweep with Growth and Swords Dance respectively.
- Roles: Ceruledge: Physical setup sweeper; Great Tusk: Hazard setter and spinner; Ninetales: Sun setter and utility pivot; Slither Wing: Specially defensive pivot and priority revenge killer; Venusaur: Special sun sweeper; Walking Wake: Special wallbreaker
- Weaknesses: Opposing weather setters like Pelipper disrupt the team's entire offensive engine by nullifying Protosynthesis and sun-boosted moves. Bulky Water- and Dragon-type walls such as Toxapex, Clodsire, and specially defensive Ting-Lu or Dragonite can endure hits and stall out turns of sunlight. Furthermore, heavy entry hazards can wear down the team quickly if Great Tusk is prevented from spinning.
- How to play against: Preserve your own weather setter or disrupt Ninetales early to minimize sun uptime. Apply relentless offensive pressure to prevent Ceruledge and Venusaur from safely setting up with Swords Dance or Growth. Utilize strong priority users or sturdy defensive pivots that resist Fire and Water to force Walking Wake and Venusaur into awkward predictions.

**Pivot Balance** — Alomomola + Cinderace + Iron Crown + Lokix + Ursaluna + Zapdos

- Game plan: The team utilizes a relentless pivoting sequence through Alomomola's Flip Turn, Cinderace's and Lokix's U-turn, Iron Crown's Volt Switch, and Zapdos's U-turn to maintain momentum and dictate the pace. Alomomola provides Wish support to keep heavy hitters healthy, while Cinderace ensures entry hazards do not wear the team down via Court Change. Once defensive holes are punched by Ursaluna's devastating Flame Orb-boosted Facade or Iron Crown's special attacks, Lokix cleans up weakened targets using Choice Band-boosted First Impression.
- Roles: Alomomola: Defensive pivot and Wish passer; Cinderace: Hazard controller and fast pivot; Iron Crown: Special tank and offensive pivot; Lokix: Physical revenge killer and priority cleaner; Ursaluna: Wallbreaker; Zapdos: Bulky pivot and defensive utility
- Weaknesses: The team relies heavily on Heavy-Duty Boots to avoid hazard damage, leaving it susceptible to Knock Off spam that strips its boots. Powerful special wallbreakers like Walking Wake, Kyurem, or Darkrai can exploit the team's reliance on Assault Vest Iron Crown and specially defensive Zapdos/Alomomola to punch early holes. Additionally, stall teams with Unaware Dondozo and Gliscor can blunt Ursaluna and Lokix's offensive output.
- How to play against: Remove Heavy-Duty Boots with Knock Off early to punish their frequent pivoting through stealth rocks and spikes. Keep offensive pressure high to prevent Alomomola from safely passing Wishes to Ursaluna. Fast Ghost-types or sturdy physical walls like Great Tusk can absorb Lokix's First Impression and prevent it from freely pivoting or revenge killing.

**Stall Hazard Stack** — Blissey + Gliscor + Toxapex

- Game plan: The core aims to outlast the opponent through an impenetrable defensive backbone while gradually chipping the opposing team. Gliscor and Blissey lay entry hazards like Stealth Rock and Spikes, while Toxapex spreads Toxic or Toxic Spikes and resets opposing boosts with Haze. Once opposing teams are worn down and poisoned, Gliscor can sweep with Swords Dance and Facade, or Blissey can break through remaining threats using Calm Mind.
- Roles: Blissey: Special wall, hazard setter, and setup wincon; Gliscor: Physical wall, hazard stacker, status spreader, and setup sweeper; Toxapex: Mixed defensive pivot, status spreader, and setup check
- Weaknesses: Strong wallbreakers packing Ground- or Psychic-type attacks, such as Great Tusk, Ting-Lu, or Iron Boulder, can overwhelm Toxapex and Blissey. Heavy stallbreakers utilizing Taunt or status immunity via Substitute or Magic Guard can prevent the core from passively whittling down opponents. Trick users or Knock Off spam also threaten their longevity by removing essential items like Heavy-Duty Boots and Leftovers.
- How to play against: Prioritize removing their hazard-preventing Heavy-Duty Boots with Knock Off to force chip damage on switch-ins. Use powerful wallbreakers with Taunt or substitute setup strategies to exploit their passive defensive turns. Aggressively keep entry hazards off your own side with rapid spin or defog to prevent their passive hazard stacking strategy from taking control.

**Physical Defensive Stall** — Corviknight + Dondozo

- Game plan: This core suffocates physical attackers through immense physical bulk and passive recovery. Corviknight controls hazards with Defog and provides pivoting with U-turn, or sets up Defense boosts with Iron Defense or Bulk Up alongside Pressure. Dondozo uses Curse to become an unbreakable physical wall, sustaining through Rest and Sleep Talk while threatening sweeps with Waterfall, Body Press, or Crunch.
- Roles: Corviknight: Physical wall, hazard remover, and pivot; Dondozo: Curse setup sweeper and physical tank
- Weaknesses: Special Electric-types such as Raging Bolt and Zapdos severely threaten both members with powerful STAB moves. Strong special wallbreakers like Iron Valiant or Kyurem can easily bypass the duo's heavy physical investment and break them down.
- How to play against: Apply pressure with special wallbreakers rather than trying to punch through physically. Utilize Taunt or Trick with a Choice item to shut down Dondozo's Curse and Rest cycles while maintaining hazards to wear Corviknight down.

**Hazard Stack Balance** — Clefable + Dragonite + Gholdengo + Iron Moth + Skarmory + Ting-Lu

- Game plan: The team sets entry hazards with Ting-Lu's Stealth Rock and Skarmory's Spikes, using Whirlwind and Dragonite's Dragon Tail to rack up passive damage across the opposing team. Gholdengo blocks hazard removal thanks to Good as Gold and threatens foes with Shadow Ball or Make It Rain. Once the opposing team is weakened by hazards and status, Clefable can sweep with Calm Mind, or Dragonite can clean up using Tera Normal Extreme Speed.
- Roles: Clefable: Calm Mind wincon and utility wall; Dragonite: Priority cleaner and phazer; Gholdengo: Spinblocker and speed control; Iron Moth: Specially offensive pivot and status spreader; Skarmory: Spikes setter and physical wall; Ting-Lu: Stealth Rock setter and special sponge
- Weaknesses: Special Water-types like Walking Wake or Wellspring Ogerpon can heavily pressure the defensive backbone, particularly Ting-Lu and Skarmory. The team lacks its own hazard removal, meaning sustained pressure from opposing Spikes and Toxic Spikes can wear down grounded members like Clefable and Ting-Lu.
- How to play against: Prevent Skarmory and Ting-Lu from freely establishing hazard layers by leading aggressively and applying immediate special pressure. Utilize Taunt or Knock Off to disable defensive recovery and Leftovers, and bring potent wallbreakers such as Kyurem or Darkrai that outspeed and threaten Gholdengo while dismantling the team's defensive core.

## 2. 配置原型

**Great Tusk**
- #0 Booster Energy Rapid Spin Wallbreaker（27%，wallbreaker）：@ Booster Energy；Headlong Rush / Rapid Spin / Close Combat / Ice Spinner。Utilizes Booster Energy with Protosynthesis to boost Speed or Attack, clearing hazards with Rapid Spin and punching holes with dual STAB moves.
- #1 Physically Defensive Stealth Rock Setter（23%，hazard_setter）：@ Rocky Helmet；Stealth Rock / Rapid Spin / Headlong Rush / Ice Spinner。Punishes contact attackers with Rocky Helmet while reliably setting Stealth Rock and clearing hazards with Rapid Spin.
- #2 Rocky Helmet Utility Spinner（20%，hazard_removal）：@ Rocky Helmet；Headlong Rush / Stealth Rock / Rapid Spin / Ice Spinner。Provides hazard compression with Stealth Rock and Rapid Spin, leveraging Rocky Helmet and high physical bulk to check physical attackers.
- #3 Booster Energy Bulk Up Sweeper（19%，setup_sweeper）：@ Booster Energy；Headlong Rush / Rapid Spin / Ice Spinner / Bulk Up。Sets up with Bulk Up alongside Booster Energy to sweep opposing teams, using Headlong Rush and Ice Spinner for broad coverage.
- #4 Leftovers Defensive Spinner（11%，hazard_removal）：@ Leftovers；Rapid Spin / Knock Off / Earthquake / Stealth Rock。Uses Leftovers for sustained recovery, clearing hazards with Rapid Spin and disrupting foes with Knock Off and Earthquake.

**Kingambit**
- #0 Swords Dance Late-Game Sweeper（100%，setup_sweeper）：@ Leftovers；Sucker Punch / Iron Head / Swords Dance / Kowtow Cleave。Acts as a premier win condition, leveraging Supreme Overlord boosts alongside Swords Dance and priority Sucker Punch to clean up weakened teams.

**Gholdengo**
- #0 Air Balloon Nasty Plot Wallbreaker（35%，wallbreaker）：@ Air Balloon；Shadow Ball / Make It Rain / Nasty Plot / Focus Blast。Leverages Air Balloon to dodge Ground-type attacks and sets up with Nasty Plot to break through balance cores with strong Ghost and Steel STABs.
- #1 Choice Scarf Trick Disruptor（28%，revenge_killer）：@ Choice Scarf；Shadow Ball / Trick / Make It Rain / Recover。Uses Choice Scarf to revenge kill faster threats and cripples opposing walls by passing its Choice item with Trick.
- #2 Nasty Plot + Recover Sweeper（26%，setup_sweeper）：@ Air Balloon；Shadow Ball / Nasty Plot / Make It Rain / Recover。Sets up with Nasty Plot while utilizing Recover and Tera Fairy to stay healthy and outlast defensive counterplay.
- #3 Thunder Wave Hex Utility（11%，utility）：@ Air Balloon；Thunder Wave / Hex / Make It Rain / Recover。Spreads paralysis with Thunder Wave to double the base power of Hex while sustaining itself with Recover.

**Ogerpon-Wellspring**
- #0 Offensive Pivot / Wallbreaker（100%，wallbreaker）：@ ?；Ivy Cudgel / Swords Dance / Knock Off / Play Rough。Applies immense pressure with Ivy Cudgel and coverage moves, utilizing Swords Dance to wallbreak or U-turn to maintain momentum.

**Dragonite**
- #0 Bulky Dragon Tail Pivot（35%，utility）：@ Heavy-Duty Boots；Extreme Speed / Earthquake / Roost / Dragon Tail。Uses Heavy-Duty Boots and Roost to maintain health while shuffling foes with Dragon Tail and cleaning weakened teams with Tera Normal Extreme Speed.
- #1 Leftovers Dragon Dance Sweeper（24%，setup_sweeper）：@ Leftovers；Dragon Dance / Earthquake / Ice Spinner / Roost。Sets up with Dragon Dance and Tera Ground Earthquake, relying on Leftovers and Roost to find setup opportunities.
- #2 Dragon Dance Extreme Speed Sweeper（20%，setup_sweeper）：@ Heavy-Duty Boots；Extreme Speed / Dragon Dance / Earthquake / Ice Spinner。Boosts with Dragon Dance to sweep late-game, relying on Tera Normal-boosted Extreme Speed and Earthquake for coverage.
- #3 Life Orb Dragon Dance Wallbreaker（11%，wallbreaker）：@ Life Orb；Outrage / Dragon Dance / Extreme Speed / Fire Punch。Maximizes direct offensive output with Life Orb, tearing through bulkier structures with Outrage and Fire Punch after a Dragon Dance.
- #4 Scale Shot Dragon Dance Sweeper（9%，setup_sweeper）：@ Loaded Dice；Dragon Dance / Scale Shot / Fire Punch / Encore。Utilizes Loaded Dice and Scale Shot alongside Dragon Dance to amplify its Speed and power, breaking physical walls with Fire Punch.

**Zamazenta-***
- #0 Iron Defense + Body Press Sweeper（42%，setup_sweeper）：@ Leftovers；Body Press / Iron Defense / Crunch / Roar。Bolsters its physical Defense with Iron Defense to fire off devastating Body Press attacks while healing passively with Leftovers.
- #1 Life Orb All-Out Attacker（38%，wallbreaker）：@ Life Orb；Close Combat / Crunch / Ice Fang / Stone Edge。Uses Life Orb and a versatile offensive moveset led by Close Combat and Crunch to break through common defensive switch-ins.
- #2 Dual Screens Lead / Setter（20%，lead）：@ Light Clay；Light Screen / Reflect / Close Combat / Body Press。Sets Light Screen and Reflect boosted by Light Clay to provide safe setup opportunities for offensive teammates.

**Kyurem**
- #0 Choice Specs Wallbreaker（36%，wallbreaker）：@ Choice Specs；Ice Beam / Freeze-Dry / Earth Power / Blizzard。Utilizes Choice Specs to fire off overwhelmingly powerful Ice Beam, Freeze-Dry, and Blizzard attacks to shred defensive cores. Earth Power and Draco Meteor provide necessary coverage against Steel- and Dragon-types.
- #1 Assault Vest Pivot（28%，special_wall）：@ Assault Vest；Ice Beam / Earth Power / Freeze-Dry / Body Press。Leverages an Assault Vest alongside defensive Poison or Fairy Tera types to sponge special hits while maintaining broad offensive pressure with Ice Beam and Earth Power. Freeze-Dry prevents Water-types from freely switching in.
- #2 SubProtect Stallbreaker（24%，utility）：@ Leftovers；Freeze-Dry / Earth Power / Substitute / Protect。Uses Substitute, Protect, and Leftovers to stall out turns, PP-stall opposing threats with Pressure, and punish switches with Freeze-Dry and Earth Power. Tera Ground bolsters its Earth Power and provides a key Electric and Rock resistance.
- #3 Dragon Dance Sweeper（12%，setup_sweeper）：@ Loaded Dice；Icicle Spear / Dragon Dance / Freeze-Dry / Earth Power。Sets up with Dragon Dance and utilizes Loaded Dice to deliver multi-hit Icicle Spears with maximum reliability. It often mixes physical and special coverage with Earth Power or Freeze-Dry to bypass physical walls.

**Raging Bolt**
- #0 Calm Mind Sweeper (Tera Fairy / Bug)（40%，setup_sweeper）：@ Booster Energy；Dragon Pulse / Thunderbolt / Calm Mind / Thunderclap。Boosts its offensive and defensive stats with Calm Mind while cleaning up weakened teams using Dragon Pulse, Thunderbolt, and priority Thunderclap. Tera Fairy or Bug flips Dragon, Ground, and Fighting matchups.
- #1 Calm Mind Sweeper (Tera Ghost)（30%，setup_sweeper）：@ Booster Energy；Dragon Pulse / Thunderbolt / Thunderclap / Calm Mind。Sets up Calm Mind with Booster Energy activation, using Tera Ghost to gain an immunity to Normal-type priority and Fighting-type moves. Thunderclap allows it to pick off faster foes after securing a boost.
- #2 Choice Specs Wallbreaker（22%，wallbreaker）：@ Choice Specs；Draco Meteor / Volt Switch / Thunderbolt / Thunderclap。Hits immediately hard with Draco Meteor and Volt Switch, generating momentum or claiming knockouts against neutral targets. Thunderclap provides crucial priority to revenge kill faster threats.
- #3 Sun Offense Attacker（9%，wallbreaker）：@ Life Orb；Weather Ball / Thunderclap / Dragon Pulse / Draco Meteor。Designed for Sun teams to capitalize on Weather Ball and boosted Fire coverage while holding Life Orb or Booster Energy. Delivers strong immediate damage with Draco Meteor and picks off survivors with Thunderclap.

**Slowking-Galar**
- #0 Rocky Helmet Pivot（37%，pivot）：@ Rocky Helmet；Chilly Reception / Sludge Bomb / Ice Beam / Future Sight。Punishes physical attackers with Rocky Helmet while supporting teammates by setting up Future Sight and using Chilly Reception to safely reposition. Sludge Bomb and Ice Beam give it respectable special coverage.
- #1 Boots Utility Pivot（24%，pivot）：@ Heavy-Duty Boots；Chilly Reception / Sludge Bomb / Future Sight / Thunder Wave。Carries Heavy-Duty Boots to ignore hazard damage while spreading paralysis or poison with Thunder Wave and Toxic. Future Sight combined with Chilly Reception creates high-pressure offensive positioning for teammates.
- #2 Assault Vest Tank（21%，special_wall）：@ Assault Vest；Sludge Bomb / Flamethrower / Psyshock / Ice Beam。Trades pivoting moves for maximum special bulk and four attacking moves with Assault Vest. Flamethrower, Psyshock, Sludge Bomb, and Ice Beam allow it to directly counter common special attackers.
- #3 Trick Black Sludge Disruptor（18%，utility）：@ Black Sludge；Chilly Reception / Sludge Bomb / Future Sight / Trick。Pivots using Chilly Reception while threatening to cripple opposing non-Poison switch-ins with Trick and a Black Sludge. Future Sight and Sludge Bomb maintain steady offensive output.

**Samurott-Hisui**
- #0 Spikes Lead & Pivot（100%，hazard_setter）：@ Assault Vest；Ceaseless Edge / Knock Off / Razor Shell / Sucker Punch。Sets Spikes while applying direct damage via its signature Ceaseless Edge, using Focus Sash to guarantee setup or Assault Vest for longevity. Knock Off and Sucker Punch punish opposing threats and secure priority finishes.

**Iron Valiant**
- #0 Booster Calm Mind Sweeper（37%，setup_sweeper）：@ Booster Energy；Moonblast / Shadow Ball / Calm Mind / Vacuum Wave。Uses Booster Energy to boost Special Attack or Speed, setting up with Calm Mind to sweep using Moonblast and Shadow Ball. Vacuum Wave offers priority, while Tera Ghost grants key immunities to Normal- and Fighting-type moves.
- #1 Booster Mixed Attacker（31%，wallbreaker）：@ Booster Energy；Moonblast / Knock Off / Close Combat / Encore。Leverages Booster Energy Speed to wallbreak and clean up with a mixed combination of Moonblast, Knock Off, and Close Combat. Utility options like Encore or Destiny Bond disrupt setups and take down troublesome counters.
- #2 Swords Dance Sweeper（18%，setup_sweeper）：@ Booster Energy；Knock Off / Swords Dance / Close Combat / Spirit Break。Sets up Swords Dance with Booster Energy Speed active to break through defensive walls using boosted Knock Off and Close Combat. Spirit Break or Moonblast provides secondary Fairy-type STAB.
- #3 Tera Electric Special Sweeper（15%，setup_sweeper）：@ Booster Energy；Moonblast / Thunderbolt / Calm Mind / Shadow Ball。Boosts with Calm Mind and leverages Tera Electric-boosted Thunderbolt alongside Moonblast to dismantle traditional Flying- and Water-type answers. Booster Energy ensures it outspeeds or overpowers the opposing team.

**Glimmora**
- #0 Red Card Hazard Lead（55%，hazard_setter）：@ Red Card；Stealth Rock / Mortal Spin / Earth Power / Power Gem。Deploys Stealth Rock or Spikes while using Red Card to disrupt setup attempts and force Toxic Debris poison activations. Mortal Spin clears away opposing hazards while applying poison.
- #1 Power Herb Lead（23%，lead）：@ Power Herb；Meteor Beam / Stealth Rock / Earth Power / Mortal Spin。Uses a Power Herb-boosted Meteor Beam to instantly threaten huge damage and gain a Special Attack boost while setting Stealth Rock. Earth Power and Mortal Spin provide broad coverage and hazard removal.
- #2 Focus Sash Hazard Lead（22%，lead）：@ Focus Sash；Stealth Rock / Earth Power / Sludge Wave / Power Gem。Guarantees the setup of Stealth Rock by surviving any single hit with Focus Sash, laying down Toxic Spikes via Toxic Debris if hit physically. Attacks with high-power STABs like Sludge Wave, Earth Power, or Power Gem.

**Cinderace**
- #0 Utility Pivot（69%，hazard_removal）：@ Heavy-Duty Boots；Pyro Ball / U-turn / Court Change / Will-O-Wisp。Utilizes Court Change and Will-O-Wisp to control entry hazards and cripple physical attackers, pivoting out with U-turn while threatening with Pyro Ball.
- #1 Offensive Pivot（31%，pivot）：@ Heavy-Duty Boots；Pyro Ball / U-turn / Court Change / Sucker Punch。Applies offensive pressure with Pyro Ball and High Jump Kick or Gunk Shot, using Sucker Punch for priority and U-turn to maintain momentum.

**Landorus-Therian**
- #0 Defensive Utility Pivot（55%，hazard_setter）：@ Rocky Helmet；Stealth Rock / U-turn / Earth Power / Taunt。Punishes physical attackers with Rocky Helmet and Intimidate while setting Stealth Rock and disrupting opposing leads with Taunt and Earth Power.
- #1 Offensive Ground Pivot（45%，pivot）：@ Rocky Helmet；U-turn / Earthquake / Stone Edge / Stealth Rock。Pressures teams with powerful STAB Earthquake and Stone Edge while generating momentum with U-turn or occasionally serving as a Choice Scarf revenge killer.

**Gliscor**
- #0 Swords Dance Sweeper（40%，setup_sweeper）：@ Toxic Orb；Protect / Swords Dance / Facade / Knock Off。Sets up Swords Dance behind Poison Heal recovery and Protect, firing off boosted Tera Normal Facades and Knock Off.
- #1 Defensive Hazard Setter（36%，hazard_setter）：@ Toxic Orb；Protect / Earthquake / Toxic / Spikes。Acts as a durable defensive presence that spreads Toxic status and sets Spikes or Stealth Rock while healing with Protect and Poison Heal.
- #2 Toxic Stall（24%，utility）：@ Toxic Orb；Protect / Knock Off / Toxic / Substitute。Utilizes the classic Protect and Substitute sequence to stall turns for Toxic poison damage while removing items with Knock Off.

**Ting-Lu**
- #0 Defensive Hazard Setter（84%，hazard_setter）：@ Leftovers；Stealth Rock / Ruination / Earthquake / Whirlwind。Sets entry hazards like Stealth Rock and Spikes while softening targets with Ruination and phazing setup sweepers with Whirlwind.
- #1 RestTalk Tank（16%，special_wall）：@ Leftovers；Earthquake / Payback / Rest / Sleep Talk。Relies on Rest and Sleep Talk for longevity, absorbing special attacks with Vessel of Ruin and hitting back with Earthquake and Payback.

**Iron Moth**
- #0 Booster Energy Sweeper（55%，setup_sweeper）：@ Booster Energy；Fiery Dance / Sludge Wave / Energy Ball / Substitute。Boosts its offensive stats with Quark Drive, cleaning up with Fiery Dance and Sludge Wave or setting up behind Substitute.
- #1 Tera Fairy All-Out Attacker（21%，wallbreaker）：@ Booster Energy；Fiery Dance / Dazzling Gleam / Sludge Wave / Psychic。Utilizes Dazzling Gleam and Tera Fairy to bypass typical Dark- and Dragon-type switch-ins alongside its dual STAB moves.
- #2 Toxic Stallbreaker（19%，wallbreaker）：@ Booster Energy；Fiery Dance / Overheat / Toxic / Morning Sun。Breaks through defensive cores using Overheat and Fiery Dance, debilitating bulkier switch-ins with Toxic and sustaining with Morning Sun.
- #3 Meteor Beam Wallbreaker（5%，wallbreaker）：@ Power Herb；Meteor Beam / Fire Blast / Sludge Wave / Energy Ball。Uses Power Herb with Meteor Beam to gain an immediate Special Attack boost and punch holes through opposing teams with Fire Blast and Sludge Wave.

**Corviknight**
- #0 Defensive Pivot（62%，physical_wall）：@ Rocky Helmet；Roost / U-turn / Defog / Body Press。Checks physical attackers with Rocky Helmet and Body Press, removing hazards with Defog and safely pivoting teammates in with U-turn.
- #1 Protect Leftovers Wall（38%，hazard_removal）：@ Leftovers；Brave Bird / Protect / Roost / Defog。Maximizes Leftovers recovery using Protect and Roost to continuously clear hazards with Defog and pressure with Brave Bird.

**Iron Treads**
- #0 Defensive Rapid Spin Pivot（50%，hazard_removal）：@ Leftovers；Stealth Rock / Earthquake / Knock Off / Rapid Spin。Utilizes Leftovers and high utility moves like Stealth Rock, Rapid Spin, and Knock Off to clear hazards and support the team. Tera Ghost provides a key immunity to Fighting-type moves and blocks opposing Rapid Spin.
- #1 Booster Energy Offensive Spinner（37%，hazard_removal）：@ Booster Energy；Earthquake / Rapid Spin / Stealth Rock / Ice Spinner。Uses Booster Energy to outspeed or overpower threats while maintaining hazard control with Rapid Spin and Stealth Rock. Strong physical coverage in Earthquake and Ice Spinner allows it to threaten common ground-weak switch-ins.
- #2 Booster Energy Special Hazard Lead（13%，lead）：@ Booster Energy；Stealth Rock / Steel Beam / Earth Power / Rapid Spin。Functions as a fast offensive hazard lead utilizing Steel Beam to deny opposing hazard removal and deal heavy burst damage. Uses Earth Power and Stealth Rock to set an immediate offensive tempo before fainting.

**Dragapult**
- #0 Mixed Life Orb Attacker（43%，wallbreaker）：@ Life Orb；Shadow Ball / Draco Meteor / U-turn / Dragon Darts。Leverages tremendous Speed alongside Life Orb to fire off high-powered Draco Meteors and Shadow Balls. Uses U-turn to pivot and Dragon Darts to hit physically weaker targets.
- #1 Status Pivot Hex（35%，pivot）：@ Heavy-Duty Boots；Hex / Will-O-Wisp / U-turn / Thunder Wave。Spreads burns and paralysis across the opposing team with Will-O-Wisp and Thunder Wave to power up Hex. U-turn allows it to safely reposition and maintain momentum.
- #2 Substitute Leftovers Attacker（22%，utility）：@ Leftovers；Dragon Darts / Will-O-Wisp / U-turn / Hex。Uses Leftovers combined with Will-O-Wisp and Substitute to wear down physical attackers and dodge status. Dragon Darts and Hex provide dual-STAB offensive output.

**Moltres**
- #0 Defensive Pivot（91%，physical_wall）：@ Heavy-Duty Boots；Flamethrower / Roost / U-turn / Will-O-Wisp。Punishes physical attackers with Flame Body and Will-O-Wisp while maintaining longevity with Roost and Heavy-Duty Boots. U-turn gives it safe pivoting, and Flamethrower offers consistent STAB damage.
- #1 Agility Sweeper（9%，setup_sweeper）：@ Life Orb；Hurricane / Fire Blast / Scorching Sands / Agility。Doubles its Speed with Agility and fires off high-base-power Life Orb STAB moves in Hurricane and Fire Blast. Scorching Sands provides crucial coverage against Rock-, Fire-, and Electric-types.

**Ceruledge**
- #0 Swords Dance Weak Armor Sweeper（52%，setup_sweeper）：@ Life Orb；Bitter Blade / Swords Dance / Shadow Sneak / Poltergeist。Sets up Swords Dance and cleans opposing teams using Bitter Blade for recovery and Shadow Sneak for priority. Weak Armor boosts its Speed upon taking a physical hit, making it hard to revenge kill.
- #1 Air Balloon Swords Dance Cleaner（48%，setup_sweeper）：@ Air Balloon；Bitter Blade / Swords Dance / Poltergeist / Shadow Sneak。Utilizes Air Balloon to setup Swords Dance on Ground-type moves safely while utilizing Bitter Blade and Poltergeist for coverage. Moves like Close Combat or Destiny Bond help bypass traditional checks.

**Hatterene**
- #0 Defensive Rocky Helmet Utility（44%，physical_wall）：@ Rocky Helmet；Nuzzle / Psychic Noise / Draining Kiss / Pain Split。Spreads paralysis with Nuzzle and punishes contact moves with Rocky Helmet while stopping recovery using Psychic Noise. Draining Kiss and Pain Split ensure consistent self-sustain.
- #1 Calm Mind Sweeper（29%，setup_sweeper）：@ Leftovers；Draining Kiss / Psychic Noise / Mystical Fire / Calm Mind。Boosts its Special Attack and Special Defense with Calm Mind while using Draining Kiss to stay healthy. Mystical Fire and Psychic Noise provide strong coverage against Steel-types and recovery-reliant walls.
- #2 Trick Room Setter Lead（27%，lead）：@ Eject Button；Healing Wish / Trick Room / Psychic Noise / Dazzling Gleam。Sets up Trick Room and promptly sacrifices itself with Healing Wish to bring in a slow offensive threat at full health. Eject Button and Rocky Helmet punish opposing attacks while setting up team momentum.

**Cresselia**
- #0 Calm Mind Stored Power (Tera Fairy)（34%，setup_sweeper）：@ Leftovers；Calm Mind / Moonblast / Stored Power / Lunar Blessing。Sets up multiple Calm Minds while recovering health and curing status with Lunar Blessing or Moonlight. It breaks through teams with Stored Power alongside Fairy STAB Moonblast.
- #1 BoltBeam Calm Mind (Tera Electric)（28%，setup_sweeper）：@ Leftovers；Calm Mind / Ice Beam / Moonlight / Thunderbolt。Sets up Calm Mind and leverages the classic coverage combination of Thunderbolt and Ice Beam. Tera Electric eliminates weaknesses and boosts Electric-type attacks alongside Levitate to maintain Ground immunity.
- #2 Calm Mind Stored Power (Tera Poison)（24%，setup_sweeper）：@ Leftovers；Calm Mind / Moonblast / Moonlight / Stored Power。Utilizes Calm Mind and Moonlight to build immense defensive and offensive presence with Stored Power and Moonblast. Tera Poison grants complete immunity to Toxic while removing Fairy and Fighting weaknesses.
- #3 Lunar Dance Support（14%，utility）：@ Rocky Helmet；Thunder Wave / Lunar Dance / Ice Beam / Moonlight。Disrupts opposing offenses with Thunder Wave and Ice Beam before sacrificing itself with Lunar Dance to completely heal a teammate. Rocky Helmet and Eject Button facilitate pivots and punish physical attackers.

**Darkrai**
- #0 Nasty Plot Wallbreaker（45%，wallbreaker）：@ Life Orb；Dark Pulse / Nasty Plot / Focus Blast / Ice Beam。Sets up with Nasty Plot and leverages high Special Attack alongside Life Orb to blast through opposing balance cores using Dark Pulse and coverage like Focus Blast or Ice Beam.
- #1 Utility Disruptor（31%，utility）：@ Leftovers；Dark Pulse / Ice Beam / Will-O-Wisp / Knock Off。Cripples physical attackers and switch-ins using Will-O-Wisp and Knock Off while maintaining offensive pressure with Dark Pulse and Ice Beam.
- #2 Trick Pivot（24%，wallbreaker）：@ Leftovers；Dark Pulse / Ice Beam / Trick / Knock Off。Utilizes Trick to disrupt defensive walls and fires off strong Dark-STAB attacks backed by Ice Beam coverage and Sucker Punch priority.

**Pecharunt**
- #0 Physically Defensive Pivot（45%，physical_wall）：@ Heavy-Duty Boots；Parting Shot / Shadow Ball / Recover / Toxic。Spreads status with Toxic and Poison Puppeteer confusion, sustains itself with Recover, and pivots teammates into favorable matchups with Parting Shot.
- #1 Nasty Plot Sweeper（34%，setup_sweeper）：@ Heavy-Duty Boots；Malignant Chain / Shadow Ball / Recover / Nasty Plot。Uses its immense physical bulk to find opportunities to boost with Nasty Plot, breaking teams with Malignant Chain and Shadow Ball while staying healthy with Recover.
- #2 Defensive Foul Play Pivot（22%，physical_wall）：@ Heavy-Duty Boots；Parting Shot / Recover / Malignant Chain / Foul Play。Punishes physical attackers with Foul Play and status while using Parting Shot and Recover to cycle defensively through threats.

**Walking Wake**
- #0 Sun Wallbreaker（72%，wallbreaker）：@ Life Orb；Hydro Steam / Draco Meteor / Flip Turn / Dragon Pulse。Demolishes defensive structures under Sun or with Life Orb boosts using Draco Meteor and Hydro Steam.
- #1 Bulky Pivot（14%，pivot）：@ Leftovers；Draco Meteor / Surf / Flip Turn / Knock Off。Acts as a durable pivot with Leftovers or Heavy-Duty Boots, controlling hazards and items with Knock Off while generating momentum using Flip Turn.
- #2 Agility Cleaner（14%，setup_sweeper）：@ Booster Energy；Dragon Pulse / Agility / Surf / Substitute。Sets up Agility behind a Substitute to activate Protosynthesis via Booster Energy, sweeping weakened teams with Dragon Pulse and powerful Water-type attacks.

**Clefable**
- #0 Calm Mind Sweeper（44%，setup_sweeper）：@ Leftovers；Moonblast / Knock Off / Moonlight / Calm Mind。Accumulates Calm Mind boosts while using Knock Off to strip items and Moonlight to stay healthy, threatening a late-game sweep with Moonblast.
- #1 Stealth Rock Utility（43%，hazard_setter）：@ Leftovers；Moonblast / Stealth Rock / Moonlight / Knock Off。Sets Stealth Rock and spreads paralysis with Thunder Wave while checking dragon- and dark-types with Moonblast and reliable recovery.
- #2 Cosmic Power Wincon（14%，setup_sweeper）：@ Leftovers；Moonblast / Moonlight / Calm Mind / Cosmic Power。Stacks Cosmic Power and Calm Mind boosts to become unkillable, healing with Moonlight and slowly dismantling the opposing team with Moonblast.

**Alomomola**
- #0 Wish Passer（57%，cleric）：@ Rocky Helmet；Flip Turn / Wish / Protect / Tickle。Supports teammates by passing massive Wishes and bringing them in safely using a slow Flip Turn, checking physical threats with high HP and Rocky Helmet.
- #1 Assault Vest Pivot（43%，pivot）：@ Assault Vest；Flip Turn / Body Slam / Mirror Coat / Aqua Jet。Uses Assault Vest and Mirror Coat to take on special attackers by surprise, pivoting out with Flip Turn and spreading status with Body Slam.

**Ogerpon**
- #0 Offensive Pivot（100%，pivot）：@ Heavy-Duty Boots；Ivy Cudgel / Knock Off / U-turn / Encore。Pressures opposing teams with strong Ivy Cudgel and Knock Off, using U-turn to pivot and Encore to disrupt setup sweepers.

**Enamorus**
- #0 Wallbreaker & Healing Wish Support（73%，wallbreaker）：@ Life Orb；Moonblast / Earth Power / Healing Wish / Mystical Fire。Fires off boosted Moonblast and Earth Power with Life Orb before sacrificing itself with Healing Wish to restore a teammate. Can occasionally run Choice Scarf to double as a revenge killer.
- #1 Substitute Calm Mind Sweeper（27%，setup_sweeper）：@ Life Orb；Moonblast / Earth Power / Substitute / Draining Kiss。Uses Substitute to evade status and set up Calm Mind boosts against passive switch-ins. Leverages Moonblast, Earth Power, or Draining Kiss to break through opposing teams.

**Deoxys-Speed**
- #0 Suicide Hazard Lead（33%，hazard_setter）：@ Focus Sash；Stealth Rock / Spikes / Taunt / Pain Split。Focuses on setting both Stealth Rock and Spikes as quickly as possible. Uses Taunt to shut down opposing hazard leads, defoggers, or setup sweepers, often holding Focus Sash to guarantee multiple layers.
- #1 Nasty Plot Sweeper（27%，setup_sweeper）：@ Life Orb；Psycho Boost / Nasty Plot / Focus Blast / Shadow Ball。Boosts its Special Attack with Nasty Plot and tears through teams with high-powered coverage like Psycho Boost, Focus Blast, and Shadow Ball while holding Life Orb.
- #2 Eject Pack Pivot Lead（23%，lead）：@ Eject Pack；Psycho Boost / Stealth Rock / Knock Off / Superpower。Sets Stealth Rock and immediately pivots out using the stat drop from Psycho Boost or Superpower combined with Eject Pack. Disrupts opposing items with Knock Off.
- #3 Dual Screens Lead（17%，lead）：@ Light Clay；Reflect / Light Screen / Taunt / Stealth Rock。Leverages superior Speed to establish Light Screen and Reflect for hyper offense setups. Uses Taunt to deny opposing entry hazards or Teleport to safely bring in a teammate.

**Zapdos**
- #0 Defensive Pivot (U-turn)（41%，pivot）：@ Heavy-Duty Boots；Discharge / U-turn / Hurricane / Roost。Spreads paralysis with Discharge and Static while maintaining momentum via U-turn. Recovers health with Roost and punishes physical attackers with Heavy-Duty Boots or Rocky Helmet.
- #1 Defensive Thunder Wave Pivot（39%，pivot）：@ Heavy-Duty Boots；Volt Switch / Hurricane / Roost / Thunder Wave。Generates momentum with Volt Switch while crippling fast sweepers using Thunder Wave. Relies on Hurricane and Roost to sustain pressure and longevity.
- #2 Offensive Pivot（20%，pivot）：@ Heavy-Duty Boots；Hurricane / Volt Switch / Heat Wave / Roost。Applies high offensive pressure with Hurricane, Volt Switch, and Heat Wave while relying on Heavy-Duty Boots. Roost provides necessary healing between attacks.

**Toxapex**
- #0 Infestation Trapper（48%，physical_wall）：@ Leftovers；Baneful Bunker / Infestation / Poison Jab / Recover。Traps passive switch-ins with Infestation and wears them down with Baneful Bunker and Poison Jab. Keeps itself healthy across long games using Leftovers and Recover.
- #1 Hazard & Status Wall（41%，physical_wall）：@ Heavy-Duty Boots；Toxic / Recover / Toxic Spikes / Haze。Sets Toxic Spikes, spreads status with Toxic, and resets opposing stat boosts with Haze. Recovers reliably with Recover and Heavy-Duty Boots or pivots with Eject Button.
- #2 Offensive Assault Vest / Trapper（11%，utility）：@ Black Sludge；Surf / Sludge Bomb / Infestation / Toxic Spikes。Uses Surf, Sludge Bomb, and Infestation to deal direct damage while setting Toxic Spikes. Leverages Assault Vest or Black Sludge to trade effectively with special attackers.

**Dondozo**
- #0 Curse RestTalk Wall（100%，setup_sweeper）：@ Leftovers；Rest / Curse / Waterfall / Sleep Talk。Boosts its Attack and Defense with Curse, becoming nearly unbreakable physically. Shrugs off status with Rest and stays active with Sleep Talk while attacking with Waterfall or Body Press.

**Rillaboom**
- #0 Swords Dance Sweeper（54%，setup_sweeper）：@ Life Orb；Grassy Glide / Knock Off / Swords Dance / High Horsepower。Sets Grassy Terrain and boosts Attack with Swords Dance to clean up with priority Grassy Glide. Threatens Grass-resistant switch-ins with Knock Off and High Horsepower.
- #1 Offensive Pivot Wallbreaker（46%，wallbreaker）：@ Life Orb；U-turn / Grassy Glide / Knock Off / Wood Hammer。Applies immediate pressure using high-power moves like Wood Hammer and Grassy Glide while pivoting with U-turn. Often holds Life Orb or Choice Band to maximize wallbreaking power.

**Garganacl**
- #0 Specially Defensive Hazard Setter（76%，hazard_setter）：@ Leftovers；Salt Cure / Protect / Stealth Rock / Recover。Sets Stealth Rock and wears down opposing teams using Salt Cure alongside Protect and Leftovers recovery. Utilizes Purifying Salt and defensive Terastallization into Water or Fairy to shrug off status and resist key attacks.
- #1 Curse Setup Sweeper（18%，setup_sweeper）：@ Leftovers；Salt Cure / Curse / Recover / Protect。Boosts its Attack and Defense with Curse while staying healthy using Recover and Salt Cure chip damage. Frequently Terastallizes into Water to turn weaknesses into resistances and sweep late-game.
- #2 Iron Defense + Body Press Wall（6%，physical_wall）：@ Leftovers；Salt Cure / Iron Defense / Recover / Body Press。Boosts its Defense to immense levels with Iron Defense and converts that bulk into offense with Body Press. Sustains itself with Recover while passive damage from Salt Cure wears down switch-ins.

**Ninetales**
- #0 Drought Sun Setter（100%，lead）：@ Heat Rock；Encore / Overheat / Healing Wish / Will-O-Wisp。Summons extended sun with Heat Rock and disrupts opponents with Encore and Will-O-Wisp. Fires off powerful Overheats before sacrificing itself with Healing Wish to bring in a sun-boosted teammate safely.

**Araquanid**
- #0 Sticky Web Lead（100%，lead）：@ Custap Berry；Sticky Web / Surf / Endeavor / Lunge。Sets Sticky Web early and uses Custap Berry or Red Card to survive or disrupt the opposing lead. Weakens foes down to low health with Endeavor or deals damage with Surf and Lunge.

**Iron Crown**
- #0 Assault Vest Pivot（73%，pivot）：@ Assault Vest；Tachyon Cutter / Volt Switch / Psychic Noise / Focus Blast。Uses Assault Vest or Choice Specs to check special attackers and maintain momentum with Volt Switch. Breaks through Focus Sashes and Sturdy with Tachyon Cutter while denying recovery with Psychic Noise.
- #1 Booster Energy Calm Mind Sweeper（27%，setup_sweeper）：@ Booster Energy；Tachyon Cutter / Calm Mind / Focus Blast / Psyshock。Activates Quark Drive with Booster Energy and sets up with Calm Mind to sweep. Uses Focus Blast boosted by Tera Fighting alongside Tachyon Cutter or Psyshock to punch through opposing defensive cores.

**Blissey**
- #0 Calm Mind Special Wall（52%，special_wall）：@ Leftovers；Soft-Boiled / Seismic Toss / Calm Mind / Stealth Rock。Walls special attackers with massive HP and boosts its Special Defense and offensive presence using Calm Mind. Sets Stealth Rock, heals reliably with Soft-Boiled, and deals consistent damage with Seismic Toss or Shadow Ball.
- #1 Utility Special Wall（48%，special_wall）：@ Heavy-Duty Boots；Stealth Rock / Seismic Toss / Soft-Boiled / Protect。Acts as a premier defensive backbone, setting Stealth Rock and spreading paralysis with Thunder Wave. Recovers with Soft-Boiled and stalls out turns or scouts moves with Protect and Seismic Toss.

**Primarina**
- #0 Assault Vest Pivot（60%，pivot）：@ Assault Vest；Moonblast / Surf / Flip Turn / Psychic Noise。Absorbs Water-type moves with Water Absorb and tanks special hits with an Assault Vest. Generates momentum for teammates using Flip Turn while dishing out damage with Moonblast and Surf.
- #1 Calm Mind / Substitute Tank（40%，setup_sweeper）：@ Leftovers；Moonblast / Psychic Noise / Sparkling Aria / Calm Mind。Sets up Calm Mind behind Substitute or utilizes Leftovers recovery to become a resilient win condition. Prevents opposing recovery with Psychic Noise while applying heavy STAB pressure with Moonblast and Sparkling Aria.

**Clodsire**
- #0 Specially Defensive Hazard Setter（100%，special_wall）：@ Heavy-Duty Boots；Recover / Spikes / Earthquake / Poison Jab。Utilizes Water Absorb and reliable recovery to check special threats while laying down Spikes or Stealth Rock. Wears down opponents with Earthquake, Poison Jab, or Toxic while leveraging Tera Steel defensively.

**Skarmory**
- #0 Brave Bird Spikes Setter（50%，physical_wall）：@ Rocky Helmet；Spikes / Brave Bird / Roost / Whirlwind。Punishes physical attackers with Rocky Helmet while reliably setting Spikes and phasing setup sweepers with Whirlwind. Brave Bird ensures it deals solid immediate damage without relying on defense boosts.
- #1 Body Press Hazard Setter（50%，physical_wall）：@ Rocky Helmet；Roost / Body Press / Stealth Rock / Whirlwind。Sets entry hazards like Stealth Rock and Spikes while utilizing Body Press to deal damage scaling with its high physical bulk. Whirlwind deters opposing setup sweepers, and Roost provides consistent longevity.

**Tornadus-Therian**
- #0 Pivot & Utility（80%，pivot）：@ Assault Vest；U-turn / Bleakwind Storm / Knock Off / Heat Wave。Uses Assault Vest or Rocky Helmet to repeatedly switch into threats and generate momentum with U-turn. Bleakwind Storm and Knock Off provide strong utility and consistent damage output.
- #1 Nasty Plot Sweeper（20%，setup_sweeper）：@ Life Orb；Bleakwind Storm / Nasty Plot / Heat Wave / Focus Blast。Boosts its Special Attack with Nasty Plot and leverages Life Orb to break through defensive cores. Uses Bleakwind Storm alongside coverage options like Heat Wave, Focus Blast, or Dark Pulse.

**Hydrapple**
- #0 Bulky Nasty Plot Sweeper（72%，setup_sweeper）：@ Heavy-Duty Boots；Giga Drain / Fickle Beam / Earth Power / Nasty Plot。Leverages Heavy-Duty Boots and natural bulk to find setup opportunities with Nasty Plot. Sustains itself with Giga Drain while firing off powerful Fickle Beam and Earth Power attacks, often using Tera Poison defensively.
- #1 Life Orb Nasty Plot Wallbreaker（28%，wallbreaker）：@ Life Orb；Earth Power / Giga Drain / Draco Meteor / Nasty Plot。Trades durability for pure power with Life Orb, breaking defensive teams using Nasty Plot-boosted Draco Meteor, Leaf Storm, or Earth Power. Giga Drain recovers recoil damage and helps keep it healthy.

**Garchomp**
- #0 Rocky Helmet Tank Lead（63%，hazard_setter）：@ Rocky Helmet；Stealth Rock / Earthquake / Spikes / Dragon Tail。Pairs Rough Skin and Rocky Helmet to punish contact moves while setting Stealth Rock and Spikes. Dragon Tail shuffles opposing Pokemon through hazard damage while Earthquake provides dependable STAB.
- #1 Swords Dance Scale Shot Sweeper（37%，setup_sweeper）：@ Life Orb；Scale Shot / Earthquake / Swords Dance / Stealth Rock。Sets up with Swords Dance and boosts its Speed with Scale Shot, threatening sweeps with Life Orb-boosted Earthquakes. Tera Poison offers defensive utility against Fairy attacks and prevents Toxic poison.

**Weezing-Galar**
- #0 Defog Pivot & Pain Split（57%，hazard_removal）：@ Heavy-Duty Boots；Will-O-Wisp / Defog / Sludge Bomb / Pain Split。Shuts down opposing abilities with Neutralizing Gas while clearing hazards using Defog. Spreads burns with Will-O-Wisp and maintains health through Pain Split.
- #1 Leftovers Defog Utility（42%，hazard_removal）：@ Leftovers；Will-O-Wisp / Defog / Sludge Bomb / Protect。Combines Neutralizing Gas, Will-O-Wisp, and Protect with Leftovers to stall out turns and maximize passive recovery. Acts as a reliable hazard remover with Defog while checking physical attackers.

**Ursaluna**
- #0 Guts Wallbreaker（100%，wallbreaker）：@ Flame Orb；Facade / Headlong Rush / Fire Punch / Swords Dance。Activates Flame Orb to unleash devastating STAB Facade attacks alongside Headlong Rush or Earthquake. It can use Swords Dance to boost its attack power further or Protect to safely trigger its burn.

**Tyranitar**
- #0 Specially Defensive Hazard Setter（100%，hazard_setter）：@ Leftovers；Knock Off / Stealth Rock / Ice Beam / Stone Edge。Sets Stealth Rock and removes opposing items with Knock Off while leveraging Sand Stream's Special Defense boost. It often uses Ice Beam or coverage options like Stone Edge and Low Kick to check common threats.

**Ogerpon-Cornerstone**
- #0 Swords Dance Wallbreaker（100%，wallbreaker）：@ ?；Ivy Cudgel / Swords Dance / Power Whip / Knock Off。Uses Swords Dance to amplify high-critical-hit Ivy Cudgel and STAB Power Whip attacks. Sturdy guarantees survival from full health, and Knock Off provides useful utility against bulky switch-ins.

**Slither Wing**
- #0 Assault Vest Pivot（56%，pivot）：@ Assault Vest；U-turn / First Impression / Close Combat / Flare Blitz。Utilizes Assault Vest to sponge special attacks while offering priority with First Impression and momentum with U-turn. Close Combat and Flare Blitz provide strong offensive coverage.
- #1 Physically Defensive Pivot（36%，physical_wall）：@ Rocky Helmet；U-turn / First Impression / Will-O-Wisp / Morning Sun。Spreads burns with Will-O-Wisp and maintains longevity through Morning Sun while punishing physical attackers with Rocky Helmet. It consistently cycles momentum using U-turn and First Impression.
- #2 Booster Energy Bulk Up Sweeper（8%，setup_sweeper）：@ Booster Energy；Bulk Up / Acrobatics / Earthquake / Morning Sun。Boosts its stats with Booster Energy and Bulk Up before sweeping with itemless Acrobatics and Earthquake coverage. Morning Sun provides reliable recovery to set up on weaker physical attackers.

**Lokix**
- #0 Choice Band Revenge Killer（100%，revenge_killer）：@ Choice Band；First Impression / U-turn / Knock Off / Leech Life。Executes extremely strong priority revenge kills using Tera Bug Choice Band First Impression. U-turn allows it to pivot effectively, while Knock Off and Leech Life provide strong utility and secondary STAB.

**Heatran**
- #0 Magma Storm Trapper（100%，hazard_setter）：@ Leftovers；Magma Storm / Stealth Rock / Earth Power / Will-O-Wisp。Traps and chips down opponents with Magma Storm while reliably setting Stealth Rock. Earth Power and Will-O-Wisp, paired with Taunt, let it dismantle balance structures and cripple physical attackers.

**Ribombee**
- #0 Sticky Web Lead（100%，lead）：@ Focus Sash；Sticky Web / Moonblast / Stun Spore / Skill Swap。Sets Sticky Web with Focus Sash guaranteeing survival, using Moonblast for damage and Stun Spore or Skill Swap to disrupt opposing leads.

**Venusaur**
- #0 Sun Sweeper（100%，setup_sweeper）：@ Life Orb；Weather Ball / Giga Drain / Growth / Sludge Bomb。Functions as a potent Chlorophyll-fueled sweeper under Sun, using Growth to boost its stats and blasting through teams with Weather Ball, Giga Drain, and Sludge Bomb.

**Excadrill**
- #0 Swords Dance Spinner（70%，hazard_removal）：@ Air Balloon；Earthquake / Iron Head / Rapid Spin / Swords Dance。Clears hazards with Rapid Spin while threatening heavy offensive pressure or sweeping opportunities via Swords Dance, Mold Breaker Earthquake, and Iron Head.
- #1 Substitute Spinner（30%，utility）：@ Leftovers；Earthquake / Rapid Spin / Rock Slide / Substitute。Uses Leftovers and Substitute to buy setup and spinning opportunities, utilizing Mold Breaker Earthquake and Rapid Spin for consistent progress.

**Volcanion**
- #0 Offensive Wallbreaker（55%，wallbreaker）：@ Shuca Berry；Steam Eruption / Flamethrower / Earth Power / Sludge Bomb。Wallbreaks using high-powered STAB Steam Eruption and Flamethrower backed by Choice Specs or Shuca Berry, with Earth Power providing crucial coverage.
- #1 Fire Spin Trapper（45%，utility）：@ Leftovers；Steam Eruption / Will-O-Wisp / Flamethrower / Fire Spin。Traps and dismantles defensive answers using Fire Spin, Taunt, and Will-O-Wisp, recovering health with Leftovers and threatening foes with Steam Eruption.

**Weavile**
- #0 Physical Wallbreaker（100%，wallbreaker）：@ Life Orb；Knock Off / Triple Axel / Ice Shard / Swords Dance。Dismantles teams with high-powered Life Orb Knock Off and Triple Axel, utilizing Ice Shard for priority revenge killing and Swords Dance to sweep.

**Tinkaton**
- #0 Utility Hazard Lead（100%，hazard_setter）：@ Air Balloon；Stealth Rock / Gigaton Hammer / Encore / Thunder Wave。Sets Stealth Rock through Magic Bounce using Mold Breaker, locking foes with Encore and disrupting opposing threats with Gigaton Hammer and Thunder Wave.

**Jolteon**
- #0 Calm Mind Pivot（100%，setup_sweeper）：@ Heavy-Duty Boots；Volt Switch / Thunderbolt / Alluring Voice / Calm Mind。Utilizes Heavy-Duty Boots and Volt Absorb to enter the field safely and pivot with Volt Switch, occasionally setting up with Calm Mind and Tera Fairy Alluring Voice to sweep.

**Hoopa-Unbound**
- #0 Physical Wallbreaker（78%，wallbreaker）：@ Leftovers；Hyperspace Fury / Knock Off / Drain Punch / Psychic Noise。Dismantles defensive cores with overwhelming physical Dark-type attacks like Hyperspace Fury and Knock Off, utilizing Leftovers for longevity or Choice Band for immediate power.
- #1 Special Terrain Attacker（22%，wallbreaker）：@ Psychic Seed；Dark Pulse / Focus Blast / Trick Room / Hyperspace Fury。Operates as a terrifying special breaker with Dark Pulse and Focus Blast, often taking advantage of Psychic Terrain with Psychic Seed and Expanding Force or setting up Trick Room.

**Hawlucha**
- #0 Grassy Seed Sweeper（83%，setup_sweeper）：@ Grassy Seed；Acrobatics / Swords Dance / Close Combat / Fire Punch。Consumes a Grassy Seed upon entering Grassy Terrain to double its Acrobatics base power, setting up with Swords Dance to sweep through weakened teams.
- #1 Red Card Defog Utility（17%，hazard_removal）：@ Red Card；Brave Bird / Defog / Swords Dance / Encore。Uses Red Card to phaze offensive setup threats while providing hazard removal with Defog and STAB damage via Brave Bird.

**Blaziken**
- #0 Mixed Speed Boost Attacker（66%，wallbreaker）：@ Life Orb；Protect / Close Combat / Overheat / Knock Off。Guarantees Speed Boost turns with Protect and punches holes through defensive lines using powerful Life Orb-boosted mixed attacks like Overheat and Close Combat.
- #1 Swords Dance Sweeper（34%，setup_sweeper）：@ Air Balloon；Close Combat / Swords Dance / Knock Off / Stone Edge。Leverages Air Balloon to find setup opportunities with Swords Dance, then sweeps opposing teams with Speed Boost-accelerated Close Combat and Stone Edge.

**Scizor**
- #0 Defensive Pivot（70%，pivot）：@ Leftovers；U-turn / Bullet Punch / Knock Off / Defog。Acts as a reliable defensive pivot with U-turn and strong priority in Bullet Punch, disrupting items with Knock Off and removing hazards with Defog.
- #1 Swords Dance Wallbreaker（30%，setup_sweeper）：@ Life Orb；Bullet Punch / Swords Dance / Knock Off / Close Combat。Boosts its Attack with Swords Dance and cleans up late-game with Life Orb-boosted, Tera Steel Bullet Punch and heavy coverage.

**Mandibuzz**
- #0 Physically Defensive Pivot（100%，physical_wall）：@ Heavy-Duty Boots；Foul Play / Roost / Toxic / U-turn。Stalls out physical attackers with Roost, Foul Play, and Toxic, while maintaining momentum and board control using U-turn or Defog.

**Keldeo-Resolute**
- #0 Defensive Pivot（72%，pivot）：@ Rocky Helmet；Surf / Secret Sword / Vacuum Wave / Flip Turn。Utilizes Rocky Helmet to punish physical attackers while generating momentum with Flip Turn and applying pressure with STAB Surf, Secret Sword, and Vacuum Wave priority.
- #1 Calm Mind Sweeper（28%，setup_sweeper）：@ Leftovers；Surf / Secret Sword / Calm Mind / Vacuum Wave。Sets up with Calm Mind behind Leftovers recovery and optional Substitute, breaking through teams with Water- and Fighting-type STAB moves.

**Pelipper**
- #0 Damp Rock Rain Setter（100%，pivot）：@ Damp Rock；U-turn / Weather Ball / Hurricane / Knock Off。Summons extended rain via Drizzle and Damp Rock, pivoting teammates into battle with U-turn while firing off powerful Weather Balls and accurate Hurricanes.

**Torkoal**
- #0 Drought Hazard Setter（100%，hazard_setter）：@ Heat Rock；Stealth Rock / Lava Plume / Rapid Spin / Will-O-Wisp。Enables sun teams with Drought and Heat Rock, laying Stealth Rock, removing opposing hazards with Rapid Spin, and spreading burns with Lava Plume or Will-O-Wisp.

**Iron Hands**
- #0 Booster Energy Swords Dance（54%，setup_sweeper）：@ Booster Energy；Ice Punch / Drain Punch / Swords Dance / Wild Charge。Activates Quark Drive via Booster Energy to bolster its stats, using Swords Dance alongside Drain Punch, Ice Punch, and Electric-type STABs to sweep.
- #1 Quick Claw Swords Dance（46%，setup_sweeper）：@ Quick Claw；Supercell Slam / Drain Punch / Ice Punch / Swords Dance。Aims to boost Attack with Swords Dance and fish for Quick Claw activations to bypass its low Speed, hitting hard with Supercell Slam, Drain Punch, and Ice Punch.

**Meowscarada**
- #0 Offensive Pivot（100%，pivot）：@ Focus Sash；Knock Off / U-turn / Triple Axel / Flower Trick。Pressures opponents with fast Knock Off and Triple Axel while keeping momentum with U-turn, occasionally laying Spikes depending on the matchup.

**Hydreigon**
- #0 Nasty Plot Wallbreaker（65%，setup_sweeper）：@ Leftovers；Dark Pulse / Nasty Plot / Substitute / Flash Cannon。Sets up with Nasty Plot behind Substitute or Leftovers recovery, using Tera Steel alongside Flash Cannon, Dark Pulse, and Draco Meteor to blast through defensive cores.
- #1 Stealth Rock Pivot（35%，hazard_setter）：@ Rocky Helmet；Dark Pulse / Draco Meteor / Stealth Rock / U-turn。Punishes physical attackers with Rocky Helmet while deploying Stealth Rock and dealing heavy immediate damage with Dark Pulse and Draco Meteor before pivoting with U-turn.

**Latios**
- #0 Choice Scarf Revenge Killer（54%，revenge_killer）：@ Choice Scarf；Draco Meteor / Luster Purge / Trick / Flip Turn。Utilizes Choice Scarf with powerful STABs like Draco Meteor and Luster Purge to outspeed and eliminate threats, while leveraging Trick or Flip Turn to disrupt defensive switch-ins and maintain momentum.
- #1 Calm Mind Setup Sweeper（46%，setup_sweeper）：@ Leftovers；Psychic Noise / Draco Meteor / Calm Mind / Recover。Boosts its Special Attack and Special Defense with Calm Mind and uses Recover or Leftovers for longevity, breaking opposing teams with Psychic Noise, Draco Meteor, or Aura Sphere.

**Manaphy**
- #0 Tail Glow Wallbreaker（71%，wallbreaker）：@ Leftovers；Tail Glow / Surf / Alluring Voice / Substitute。Quickly boosts to overwhelming power with Tail Glow and fires off strong Surf or Alluring Voice attacks, often utilizing Substitute or Tera Fairy to safely set up and sweep.
- #1 Take Heart Acid Armor Sweeper（29%，setup_sweeper）：@ Leftovers；Take Heart / Scald / Acid Armor / Stored Power。Accumulates defensive and offensive boosts using Acid Armor and Take Heart alongside Scald and Stored Power, turning into an unkillable win condition backed by Leftovers.

**Serperior**
- #0 SubGlare Wallbreaker（100%，setup_sweeper）：@ Leftovers；Leaf Storm / Glare / Substitute / Leech Seed。Paralyzes switch-ins with Glare and hides behind Substitute to ramp up Special Attack with Leaf Storm, often wearing down checks with Leech Seed.

**Rotom-Wash**
- #0 Defensive Pivot（53%，pivot）：@ Leftovers；Volt Switch / Hydro Pump / Will-O-Wisp / Pain Split。Checks physical attackers with Will-O-Wisp and Levitate, using Volt Switch and Hydro Pump to generate tempo while staying healthy via Leftovers and Pain Split.
- #1 Dual Screens Lead（47%，lead）：@ Light Clay；Volt Switch / Hydro Pump / Reflect / Light Screen。Sets up Reflect and Light Screen enhanced by Light Clay to enable offensive teammates, using Volt Switch to pivot out cleanly after screens are established.

**Zarude-Dada**
- #0 Swords Dance Wallbreaker（62%，wallbreaker）：@ Sitrus Berry；Knock Off / Swords Dance / Power Whip / Trailblaze。Sets up Swords Dance to tear through teams with Knock Off and Power Whip, relying on Sitrus Berry for mid-turn survivability and Tera Fire to flip defensive matchups.
- #1 Bulky Swords Dance Sweeper（38%，setup_sweeper）：@ Leftovers；Knock Off / Swords Dance / Synthesis / Power Whip。Combines Swords Dance with Synthesis and Leftovers for consistent healing, dismantling defensive cores with Knock Off while using Tera Poison defensively.

**Sinistcha**
- #0 Calm Mind Setup Sweeper（100%，setup_sweeper）：@ Heavy-Duty Boots；Matcha Gotcha / Strength Sap / Shadow Ball / Calm Mind。Sets up Calm Mind while staying healthy through Strength Sap and Matcha Gotcha, threatening defensive and offensive teams alike behind Tera Poison.

**Ninetales-Alola**
- #0 Aurora Veil Lead（100%，lead）：@ Light Clay；Aurora Veil / Freeze-Dry / Encore / Blizzard。Sets up Snow Warning and an extended Aurora Veil using Light Clay to support hyper offense teammates. Disrupts setup sweepers with Encore and attacks using Freeze-Dry, Blizzard, or Moonblast.

**Fezandipiti**
- #0 Toxic Chain Pivot（82%，pivot）：@ Leftovers；Beat Up / U-turn / Roost / Play Rough。Uses Beat Up to maximize Toxic Chain poison chances against incoming switch-ins before pivoting out with U-turn. Stays healthy with Roost and leverages Leftovers alongside Play Rough for consistent chip damage.
- #1 Calm Mind Sweeper（18%，setup_sweeper）：@ Leftovers；Moonblast / Calm Mind / Heat Wave / Roost。Boosts its Special Attack and Special Defense with Calm Mind to sweep with Moonblast and Heat Wave. Recovers health via Roost while utilizing Leftovers and Toxic Chain to wear down opposing teams.

**Pawmot**
- #0 Revival Blessing Utility Pivot（81%，cleric）：@ Leppa Berry；Revival Blessing / Nuzzle / Encore / Mach Punch。Restores fallen teammates using Revival Blessing paired with Leppa Berry for multiple uses. Disrupts opponents with Nuzzle paralysis and Encore while picking off weakened foes with Mach Punch.
- #1 RestTalk Revival Blessing（19%，cleric）：@ Leppa Berry；Revival Blessing / Rest / Sleep Talk / Focus Punch。Uses Rest and Sleep Talk to sustain itself and potentially call Revival Blessing or Focus Punch while asleep. Leppa Berry guarantees multiple Revival Blessings to continually bring key team members back to life.

接地检查：配置说明中提到 DATA 以外招式 9 次，核心说明中 20 次。
