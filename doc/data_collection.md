# 数据收集记录（Smogon 统计 + Showdown replay）

日期：2026-10-04。所有数据放在 `data/`（已被 `.gitignore` 忽略，不入库）。

## 1. 抓取规则与礼貌策略

| 站点 | robots.txt | 备注 |
|---|---|---|
| `replay.pokemonshowdown.com` | **404（无 robots.txt）**，未声明任何限制 | 文档里也没有限速/爬取条款（`/rules`、`/faq` 已查）；站点在 Cloudflare 后面 |
| `pokemonshowdown.com` | 仅禁 `/interstice`、`/forum/`、`/mediawiki/` | 我们用的 `/ladder/<fmt>.json` 不在禁止范围内 |
| `www.smogon.com` | 只有 `Amazonbot: Allow: /`，对其他爬虫无限制 | `/stats/` 下是静态文件 |

`alpha_poke.http.PoliteClient`（所有抓取共用）：
- 单连接串行，请求间隔默认 **2 秒**（再加 0–25% 随机抖动），可用 `--interval` 调慢；
- 遵守 `Retry-After`，429/5xx 指数退避（最长 10 分钟）；
- **403 或连续 5 次失败立即中止整个抓取**（`CrawlAbort`），不硬撑；
- User-Agent 只说明用途（个人、非商业、约每 2 秒一个请求），**不含任何个人联系方式**；
- 支持 `--max-requests` / `--max-hours`，Ctrl-C / SIGTERM 会在当前请求结束后干净退出；
- 全程可续抓：状态存在 SQLite 索引里。

> 备注：最初抽取 11 场样本时，临时脚本的 User-Agent 误带了用户邮箱（约 16 个请求，发往 replay 站点）。已更正，正式客户端从不携带。

## 2. Smogon 使用率统计（已完成）

- 脚本：`scripts/fetch_smogon_stats.py`；读取类：`alpha_poke.data.smogon_stats.UsageStats`。
- 已下载 gen9ou 最近 3 个月（2026-07、08、09），每月 4 个评分门槛（0 / 1500 / 1695 / 1825）× 5 类文件（txt、chaos JSON、moveset、leads、metagame），共约 127MB、64 个请求。
- chaos JSON 含：使用率、原始计数、特性/道具/招式/太晶属性分布、努力值配置（`Nature:HP/Atk/Def/SpA/SpD/Spe`）、队友共现、克制关系。
- 2026-09 gen9ou 共 574,541 场对局；评分门槛 0 时 458 个物种，门槛 1825 时 243 个。
- 使用率前列（门槛 1825）：Kingambit 34.3%、Great Tusk 31.8%、Zamazenta 22.1%、Ogerpon-Wellspring 21.8%、Glimmora 21.1%。
- 注意：统计里的招式/道具/特性是 **ID 形式**（小写、无空格，如 `heavydutyboots`），而 replay 里是显示名（`Heavy-Duty Boots`），对照时要统一成 ID。

## 3. Showdown replay 抓取

### 3.1 接口行为（实测）

| 请求 | 行为 |
|---|---|
| `search.json?format=gen9ou` | 每页 **51 条**，最新在前；可用 `before=<uploadtime>` 往回翻页 |
| `search.json?format=gen9ou&user=<name>` | **只返回最近 25 条，不能翻页**（`page=2` 为空，`before` 基本无效） |
| `<id>.json` | 完整观战日志，约 2.3KB gzip |
| `pokemonshowdown.com/ladder/gen9ou.json` | 前 500 名，含 userid、elo、gxe 等 |

由此得到的策略：
- "从 top user 出发"每人最多 25 场，500 人去重后最多约 1 万场，只适合作为**高质量种子**；
- 主力是**全局列表往回翻页**：每个请求带回 51 条元数据，很便宜，把元数据先全部索引，再按条件挑选下载。

### 3.2 数量估算（来自 150 条全局列表样本，粗估）

- Gen9 OU 公开 replay 约 **167 场/小时（≈4000 场/天）**。
- `rating` 字段看起来接近双方赛后评分中较低的一个（样例：双方赛后 1705 / 1645，字段为 1645；语义 `[未验证]`）。
- 评分分布：≥1300 约 32%，≥1500 约 7%，≥1600 约 3%，≥1700 约 2%。
- 因此"5 万场 + 高评分 + 很新"互相冲突，例如：
  - ≥1300、最近约 40 天可得 5 万场；
  - ≥1500 要回溯约半年以上（Gen9 OU 的 metagame 会随禁用/新精灵变化）；
  - 再加天梯前 500 用户的最近对局作为高质量补充。
- 时间成本（2 秒/请求）：列表 90 天约 7–8 千次请求 ≈ 4–5 小时；下载 5 万场 ≈ 30 小时。

### 3.3 工具

- `alpha_poke.replay.crawl.ReplayCrawler`：SQLite 索引（`data/replays/index.sqlite`，表 `replays` / `users` / `meta`）+ 磁盘缓存（`data/replays/<format>/<id>.json.gz`）。
- `scripts/crawl_replays.py` 子命令：`seed-users`、`crawl-users`、`expand-users`（把高分对手加入用户池，用于滚雪球）、`list --mode back|new`、`download --target N --min-rating R --since-days D --order recent|rating`、`status`。
- `scripts/run_crawl_metadata.sh`：第一阶段（仅元数据）的一键脚本，后台运行日志在 `data/replays/crawl_metadata.log`。
- 后续增量：`list --mode new` 拉取比已知更新的元数据，再 `download` 提高目标数。

### 3.4 `replays` 表字段

`id`、`format_id`、`format_name`、`uploadtime`、`p1`、`p2`、`rating`、`private`、`source`（`user` / `listing`）、`discovered_at`、`status`（`pending` / `done` / `missing` / `error`）、`fetched_at`、`bytes`、`error`。

## 4. 已知偏差

- 只有被上传的对局才有 replay，样本偏向愿意保存的玩家。
- 天梯上存在 bot（例如前 500 用户的对手里出现了 `chatot-gpt-pokebot`），目前不做过滤，元数据里有玩家名，后续可按名字或行为筛。
- 评分是对局时的评分；用户名是真实天梯用户名，**不要把原始 replay 提交进仓库**（测试 fixture 已匿名）。
