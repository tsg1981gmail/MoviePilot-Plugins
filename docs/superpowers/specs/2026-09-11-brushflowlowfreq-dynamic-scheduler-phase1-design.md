# brushflowlowfreq 动态调度第一阶段诊断设计

## 背景

当前插件使用多下载器按种子大小分流。v2 诊断数据显示：

- 约 24 小时内添加 176 个任务，`no_value` 删除 105 个。
- 32.31 承担 207 个任务档案、108 个删除；NAS QB 承担 43 个任务档案、28 个删除。
- 当前活跃任务中，32.31 有 99 个，累计上传约 61GB、下载约 302GB；NAS QB 有 15 个，累计上传约 148GB、下载约 655GB。
- 活跃任务的来源 leechers 平均值约 20.5，`no_value` 删除任务约 16.0。
- 首次上传延迟中位数约 157 秒，75% 在约 417 秒内出现。
- 下载器快照中的 `downloading_count` 仍可能错误地等于 `active_count`。

这些数据说明固定按体积分流可能不是最优方案，但在样本充分前不应直接改变业务调度。第一阶段只补齐动态调度所需的数据记录，并记录“如果启用动态调度会如何选择”，实际仍维持现有分配行为。

## 目标

1. 不改变现有刷流、检查、上传保护、删种和下载器分配行为。
2. 补齐每个下载器的配置、真实资源、全局负载、磁盘和状态数据。
3. 记录候选种子在上传窗口内的 swarm 变化。
4. 每次添加新种子时记录影子调度决策。
5. 记录新任务从添加到开始下载、首次上传、完成、删除的完整时序。
6. 继续使用现有 v2 诊断数据库，schema 升级到 `2.1`，历史数据保留。
7. 运行至少 14 天后再设计实际动态调度规则。

## 非目标

- 第一阶段不动态选择下载器。
- 不迁移已经在下载或做种的任务。
- 不改变当前大小分流结果。
- 不修改下载器配置上限。
- 不做机器学习训练、强化学习或自动调参。
- 不删除现有 v1/v2 诊断数据。

## 未来调度边界

未来正式启用动态调度时：

- 只影响新添加的种子。
- 不迁移已有任务。
- 不重新下载已有任务。
- 先影子评估，再小比例试运行。
- H&R、磁盘、带宽和下载器健康仍是硬约束。

## 数据库设计

继续使用：

```text
/config/logs/plugins/brushflowlowfreq_diagnostics_v2.db
```

`diagnostic_meta.schema_version` 更新为 `2.1`。

新增以下表。

### `downloader_config_snapshots`

```sql
CREATE TABLE IF NOT EXISTS downloader_config_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sampled_at REAL NOT NULL,
  downloader TEXT NOT NULL,
  enabled INTEGER,
  is_default INTEGER,
  maxdlcount INTEGER,
  maxupspeed REAL,
  maxdlspeed REAL,
  disksize REAL,
  up_speed REAL,
  dl_speed REAL,
  save_path TEXT,
  qb_category TEXT,
  raw_json TEXT
);
```

记录时机：
- 插件启动加载配置后
- 诊断记录器重新初始化后
- 下载器配置变更时

### `downloader_resource_samples`

```sql
CREATE TABLE IF NOT EXISTS downloader_resource_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sampled_at REAL NOT NULL,
  downloader TEXT NOT NULL,
  global_total INTEGER,
  global_downloading INTEGER,
  global_queued INTEGER,
  global_paused INTEGER,
  global_checking INTEGER,
  global_seeding INTEGER,
  managed_total INTEGER,
  managed_downloading INTEGER,
  managed_seeding INTEGER,
  global_up_speed REAL,
  global_dl_speed REAL,
  managed_up_speed REAL,
  managed_dl_speed REAL,
  global_up_limit REAL,
  global_dl_limit REAL,
  disk_total INTEGER,
  disk_used INTEGER,
  disk_free INTEGER,
  managed_seed_size INTEGER,
  error TEXT
);
```

说明：
- 全局指标统计下载器内所有 torrent。
- managed 指标只统计插件托管任务。
- 磁盘数据无法获取时写 NULL，不影响其它记录。
- 状态分类基于真实 `state`、`progress`、`completion_on` 和 `seeding_time`，不再仅凭 progress 判断。

### `task_swarm_samples`

```sql
CREATE TABLE IF NOT EXISTS task_swarm_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_hash TEXT NOT NULL REFERENCES task_profiles(task_hash) ON DELETE CASCADE,
  site TEXT,
  torrent_key TEXT,
  sampled_at REAL NOT NULL,
  seeders INTEGER,
  leechers INTEGER,
  is_free INTEGER,
  free_remaining_minutes REAL,
  rank_position INTEGER
);
```

记录时机：
- 刷流列表抓到候选后，如果能匹配到已有托管任务，则更新 swarm 样本。
- 新增任务添加成功时记录首个 swarm 样本。
- 不需要为了 swarm 指标额外请求站点详情页。

### `scheduler_shadow_decisions`

```sql
CREATE TABLE IF NOT EXISTS scheduler_shadow_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decided_at REAL NOT NULL,
  candidate_key TEXT NOT NULL,
  torrent_id INTEGER,
  task_hash TEXT,
  actual_downloader TEXT,
  recommended_downloader TEXT,
  candidate_size INTEGER,
  source_seeders INTEGER,
  source_leechers INTEGER,
  predicted_upload_score REAL,
  selected_resource_score REAL,
  hard_constraint_json TEXT,
  downloader_scores_json TEXT,
  decision_reason TEXT,
  decision_ms INTEGER,
  executed INTEGER NOT NULL DEFAULT 0,
  mode TEXT NOT NULL DEFAULT 'shadow'
);
```

影子决策只计算，不改变真实下载器选择。

### `task_transfer_events`

```sql
CREATE TABLE IF NOT EXISTS task_transfer_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_hash TEXT NOT NULL REFERENCES task_profiles(task_hash) ON DELETE CASCADE,
  event_at REAL NOT NULL,
  event_type TEXT NOT NULL,
  downloader TEXT,
  detail TEXT
);
```

事件类型：
- `add_requested`
- `download_started`
- `first_uploaded`
- `completed`
- `deleted`
- `archived`

## 影子调度输入

第一阶段不执行调度，但每次候选被允许添加时计算并记录：

### 候选层

- 发布时间和发布年龄
- 种子大小
- seeders
- leechers
- 免费状态和剩余免费时间
- 站点
- 标题中的分辨率、类型、发布组
- 历史同站点/同类型上传收益

### 下载器层

- 配置并发上限
- 当前托管任务数与全局任务数
- 当前下载中、排队、做种中任务数
- 当前上传/下载速度
- 配置上传/下载上限
- 最近 5/15/60 分钟实际上传速度
- 磁盘总容量、剩余容量和托管保种体积
- 当前健康状态

### 硬约束

- 下载器在线
- 下载器已启用
- 未超过 `maxdlcount`
- 未超过 `maxdlspeed`
- 未超过 `maxupspeed`
- 未超过 `disksize`
- 磁盘剩余空间足够

### 影子评分

第一阶段评分只用于记录，不用于添加：

```text
predicted_upload_score =
  leecher_score
  * freshness_score
  * size_score
  * history_score
```

```text
resource_score =
  upload_headroom
  * download_headroom
  * slot_headroom
  * disk_headroom
  * recent_upload_efficiency
```

评分参数可以先用固定规则，不要求第一阶段调参。

## 需要修正的现有记录

1. `downloading_count`
   - 不把 `progress < 100` 作为唯一条件。
   - `progress` 可能是 0-1，也可能是 0-100，必须按字段来源标准化。
   - 优先使用 `state`，再结合 `completion_on` 和 `seeding_time`。

2. 全局与托管分离
   - 现有只统计插件托管任务的指标不能代表下载器整体负载。
   - 新表必须同时保存 global 和 managed 两组数据。

3. 调度决策可解释
   - 每个影子决策保存所有下载器的 hard constraint 和 score。
   - 不能只记录最终推荐下载器。

## API 与导出

现有诊断 API 继续保留，并新增：

- `GET /diagnostic/downloader-config`
- `GET /diagnostic/downloader-resources`
- `GET /diagnostic/swarm`
- `GET /diagnostic/scheduler`

`/diagnostic/export` 增加可选数据块：

- `downloader_configs`
- `downloader_resources`
- `swarm_samples`
- `scheduler_decisions`
- `transfer_events`

查看和导出继续支持任意 `days`、`start`、`end`。

## 数据保留

- 所有新增表沿用 30 天滚动保留。
- 活跃 `task_profiles` 不因超过 30 天被删除。
- v1 和 v2 原有数据保留。

## 记录隔离

- 所有新增记录都在业务判断完成后写入。
- 诊断异常不得改变刷流、检查、上传保护和删种返回值。
- 影子调度函数不得设置 `_active_downloader_name`，不得调用下载器。
- 影子调度开销需要记录 `decision_ms`，超过阈值时只记录耗时，不影响添加。

## 失败降级

- 无法获取下载器磁盘数据：相应字段写 NULL。
- 无法获取全局速度：使用已有的 transfer 信息；仍无法获取则写 NULL。
- 无法匹配 swarm 种子：跳过该样本。
- 影子评分异常：写 `decision_reason=error:...`，不抛出异常。

## 观察计划

1. 部署 `v4.3.97`，schema `2.1`。
2. 保持现有刷流、删种、上传保护和大小分配配置不变。
3. 连续记录至少 14 天。
4. 每 3 天可导出一次中间检查，但不调整业务规则。
5. 样本期结束后分析：

   - 实际下载器与推荐下载器的差异率
   - 推荐下载器的预测上传收益
   - 32.31 与 NAS QB 在相似候选上的上传效率
   - leechers/seeders 对上传窗口的预测能力
   - 下载器负载与上传效率的关系
   - 磁盘余量、并发数与收益的关系

## 验收标准

- 现有业务测试全部通过。
- 所有新增记录表在 v2 数据库中存在。
- 每个检查周期能记录每个下载器的 global 和 managed 资源快照。
- 候选添加时能记录影子调度决策。
- 新任务的添加、开始下载、首次上传、完成和删除事件可查询。
- 任一诊断写失败不影响刷流。
- 30 天滚动清理覆盖新增表。
- `v4.3.97` 部署后无需修改业务配置即可持续记录。
