# brushflowlowfreq 独立诊断记录库设计

## 目标

为 `brushflowlowfreq` 增加一套完全独立的诊断记录能力，在 30 天滚动窗口内保留可分析数据，不改变任何现有刷流、检查、上传保护、删种或统计行为。

诊断数据用于回答以下问题：

- 哪些候选种子被添加，哪些被拒绝，为什么。
- 每个托管种子的上传窗口出现在什么时间，峰值多高，何时衰减。
- 上传发生在下载阶段还是完成后的做种阶段。
- 删除时机是否过早或过晚。
- 两个下载器的负载、上传速度和任务数是否成为瓶颈。

## 非目标

- 不参与任何业务判断。
- 不改变现有任务的判断、保存和删除结果。
- 不添加固定 7 天分析周期。
- 不记录下载器中所有非托管种子。
- 不为候选种子记录完整生命周期；候选种子只记录决策快照。

## 总体架构

- 新增 `DiagnosticRecorder` 私有类，使用 Python 标准库 `sqlite3`。
- 数据库与现有 MoviePilot 插件数据完全分离，默认路径为 MoviePilot 可写日志/数据目录下的 `brushflowlowfreq_diagnostics.db`。
- 增加配置开关 `diagnostic_enabled`，默认关闭。部署诊断版本时由部署流程自动开启。
- 增加配置 `diagnostic_retention_days`，默认 `30`，只影响旧数据清理，不影响业务。
- 所有诊断写入都在业务结果产生后执行，并且任何 SQLite 异常都不向外抛出。
- 数据库被删除、损坏或目录不可写时，插件继续正常运行，只记录一次失败诊断日志。

## 数据范围

### 已托管种子：完整生命周期

对每个被插件托管的种子，从添加开始记录：

- 添加时间和候选来源指标。
- 每个检查周期的下载量、上传量、检查间上下行速度、进度、状态、做种时间。
- 首次下载时间、首次上传时间、完成时间。
- 上传保护阶段、低速/无上传/达标连续计数。
- 删除类型、删除原因、删除时最终上传/下载/分享率。
- 归档时间和归档前最后快照。

### 候选种子：只记录决策快照

对每次刷流看到的候选种子，只记录：

- 种子标题、详情页地址、种子大小。
- 做种人数、下载人数（站点数据可用时）。
- 免费状态和免费剩余时间。
- 被添加或被拒绝，拒绝原因。
- 被拒绝时准备使用的下载器。

### 下载器：每轮检查快照

每个检查周期对实际操作的下载器记录：

- 托管任务数、下载中任务数、上传中任务数。
- 总上传速度、总下载速度。
- 是否连接异常。

## SQLite Schema

### `brush_runs`

```sql
CREATE TABLE IF NOT EXISTS brush_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL NOT NULL,
  finished_at REAL,
  site TEXT NOT NULL,
  pages INTEGER NOT NULL DEFAULT 0,
  candidates_seen INTEGER NOT NULL DEFAULT 0,
  added INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,
  scan_ms INTEGER NOT NULL DEFAULT 0
);
```

### `torrent_catalog`

```sql
CREATE TABLE IF NOT EXISTS torrent_catalog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT NOT NULL,
  page_url TEXT NOT NULL,
  torrent_key TEXT NOT NULL,
  title TEXT NOT NULL,
  first_seen_at REAL NOT NULL,
  last_seen_at REAL NOT NULL,
  seen_count INTEGER NOT NULL DEFAULT 0,
  size_bytes INTEGER,
  UNIQUE(site, torrent_key)
);
```

### `candidate_snapshots`

```sql
CREATE TABLE IF NOT EXISTS candidate_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES brush_runs(id) ON DELETE CASCADE,
  torrent_id INTEGER NOT NULL REFERENCES torrent_catalog(id),
  seen_at REAL NOT NULL,
  size_bytes INTEGER,
  seeders INTEGER,
  leechers INTEGER,
  is_free INTEGER,
  free_remaining_minutes REAL,
  decision TEXT NOT NULL,
  reject_reason TEXT,
  downloader TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_seen_at
  ON candidate_snapshots(seen_at);
CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_torrent_id
  ON candidate_snapshots(torrent_id);
```

### `task_profiles`

```sql
CREATE TABLE IF NOT EXISTS task_profiles (
  task_hash TEXT PRIMARY KEY,
  site TEXT NOT NULL,
  title TEXT NOT NULL,
  size_bytes INTEGER,
  downloader TEXT,
  added_at REAL NOT NULL,
  first_downloaded_at REAL,
  first_uploaded_at REAL,
  completion_on REAL,
  deleted_at REAL,
  deleted_type TEXT,
  deleted_reason TEXT,
  archived_at REAL,
  final_uploaded INTEGER,
  final_downloaded INTEGER,
  final_ratio REAL,
  final_seeding_time INTEGER
);
```

### `task_samples`

```sql
CREATE TABLE IF NOT EXISTS task_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_hash TEXT NOT NULL REFERENCES task_profiles(task_hash) ON DELETE CASCADE,
  sampled_at REAL NOT NULL,
  downloader TEXT,
  state TEXT,
  downloaded INTEGER,
  uploaded INTEGER,
  progress REAL,
  dl_speed REAL,
  up_speed REAL,
  interval_downloaded INTEGER,
  interval_uploaded INTEGER,
  interval_downspeed REAL,
  interval_upspeed REAL,
  seeding_time INTEGER,
  completion_on REAL,
  upload_protection_stage TEXT,
  upload_protection_low_streak INTEGER,
  upload_protection_no_upload_streak INTEGER,
  upload_protection_good_streak INTEGER
);
CREATE INDEX IF NOT EXISTS idx_task_samples_hash_time
  ON task_samples(task_hash, sampled_at);
CREATE INDEX IF NOT EXISTS idx_task_samples_time
  ON task_samples(sampled_at);
```

### `task_events`

```sql
CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_hash TEXT NOT NULL REFERENCES task_profiles(task_hash) ON DELETE CASCADE,
  event_at REAL NOT NULL,
  event_type TEXT NOT NULL,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_events_hash_time
  ON task_events(task_hash, event_at);
CREATE INDEX IF NOT EXISTS idx_task_events_time
  ON task_events(event_at);
```

### `downloader_samples`

```sql
CREATE TABLE IF NOT EXISTS downloader_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sampled_at REAL NOT NULL,
  downloader TEXT NOT NULL,
  active_count INTEGER,
  downloading_count INTEGER,
  uploading_count INTEGER,
  upload_speed REAL,
  download_speed REAL,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_downloader_samples_time
  ON downloader_samples(sampled_at, downloader);
```

### `diagnostic_meta`

```sql
CREATE TABLE IF NOT EXISTS diagnostic_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

`diagnostic_meta` 保存 schema 版本、插件版本、首次记录时间和数据库创建时间。

## 记录点

以下记录点全部在业务判断完成后调用，不影响判断结果：

1. 刷流开始时创建 `brush_runs`。
2. 刷流结束后更新 `finished_at`、`candidates_seen`、`added`、`rejected`、`scan_ms`。
3. 每个候选种子判断完成后写入 `torrent_catalog` 与 `candidate_snapshots`。
4. 任务添加成功后写入 `task_profiles` 与 `task_events(added)`。
5. `__update_torrent_tasks_state()` 更新完成后，对当前下载器托管的每个任务写入 `task_samples`。
6. 首次上传/首次下载/完成时间确定时更新 `task_profiles`，并在完成时写 `task_events(completed)`。
7. 上传保护执行限速、恢复、放开时写 `task_events(upload_action)`。
8. 删除成功后更新 `task_profiles` 最终字段，并写 `task_events(deleted)`。
9. 归档时写 `task_events(archived)`。
10. 每个下载器 `check()` 获取到下载器列表后写 `downloader_samples`。

## 隔离与安全

- 默认 `diagnostic_enabled=false` 时，不创建数据库、不打开连接、不产生任何写入。
- 开启诊断时，所有写操作包在 `try/except` 中；失败只记录一条日志，不影响原流程。
- 使用模块级锁保护 SQLite 写入，避免刷流和检查并发写入冲突。
- 每个检查周期后批量提交，不在每个业务步骤内提交，控制磁盘开销。
- 不保存 Cookie、站点密码、下载器密码等敏感字段。

## 保留与清理

- 默认保留 30 天。
- 每次插件启动和每次数据库写入达到清理阈值时，删除早于 `now - retention_days` 的旧数据。
- 只清理快照和事件表；当前仍在活跃的 `task_profiles` 即使添加时间超过 30 天也保留，避免丢失活跃任务上下文。
- 清理完成后更新 `diagnostic_meta`。

## 查看与输出 API

新增只读 API，全部不修改数据库内容：

- `GET /diagnostic/status`：数据库路径、schema 版本、保留天数、最早/最新记录。
- `GET /diagnostic/summary`：支持 `days`、`from`、`to` 参数，返回候选、添加、删除、任务上传/下载汇总。
- `GET /diagnostic/candidates`：按时间范围、站点、决策类型查询候选快照。
- `GET /diagnostic/tasks`：按时间范围、站点、下载器、hash 查询任务档案。
- `GET /diagnostic/samples`：按任务 hash、时间范围查询完整任务时间线。
- `GET /diagnostic/events`：按任务 hash、事件类型查询生命周期事件。
- `GET /diagnostic/downloaders`：按时间范围查询下载器快照。
- `GET /diagnostic/export`：支持 `days` 或 `from/to`，返回可下载的 JSONL 或 CSV。

导出不限定 7 天；任何 `days`、`from`、`to` 组合都按 SQL 时间范围过滤。

## 运行与升级

- 版本升级到 `4.3.93`。
- 配置项写入 `BrushConfig` 和配置页，不改变旧配置语义。
- 部署时把 `diagnostic_enabled` 自动设为 `true`，保留天数设为 `30`。
- 没有固定分析周期；由用户或 Codex 在任意日期范围主动分析。

## 测试计划

- 默认关闭时，业务测试完全不受影响。
- 开启后不改变候选判断、任务状态、上传保护和删种返回结果。
- SQLite schema 初始化、索引和批量写入正确。
- 候选快照、任务样本、生命周期事件和下载器快照可查询。
- 30 天滚动清理只删除过期数据，不删除活跃任务档案。
- API 支持任意 `days`/`from`/`to` 输出。
- 数据库写入失败不向外抛出异常，插件继续运行。
- 全量测试继续通过。

## 分析能力示例

运行一段时间后可以执行以下分析：

- 每个任务的“上传窗口”：从 `added_at` 到 `first_uploaded_at` 的时间，以及 `task_samples` 中上传速度的峰值位置。
- 下载阶段与做种阶段上传对比：用 `completion_on` 前后聚合上传增量。
- 删除是否过早：对比被删除任务完成进度与删除后的继续上传潜力。
- 候选筛选问题：按 `reject_reason`、`seeders`、`leechers` 聚合，寻找被拒绝但后续上传好的同源种子。
- 下载器瓶颈：按 `downloader_samples` 检查上传速度是否在任务数很高时反而下降。
- 任意天数回放：例如只导出最近 1、3、7、15 或 30 天。
