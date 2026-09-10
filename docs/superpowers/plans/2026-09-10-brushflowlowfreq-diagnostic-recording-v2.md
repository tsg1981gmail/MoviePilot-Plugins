# brushflowlowfreq 诊断记录 v2 增强方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在完全不改变刷流、检查、上传保护、删种和下载器分配行为的前提下，把诊断记录升级为更适合后续优化的 v2 版本，再继续观察至少 7 天。

**Architecture:** 保留现有插件单文件结构，新建独立 SQLite v2 诊断库。v1 诊断库继续保留为历史样本，不迁移、不覆盖。诊断记录器仍只在业务结果产生后写入，所有记录失败不影响原功能。

**Tech Stack:** Python 3、MoviePilot v2、Python 标准库 `sqlite3`、`unittest`。

---

## 背景

v1 诊断库运行约 17.6 小时后发现以下记录质量问题：

- 490 轮刷流产生 97,900 条候选快照，但唯一种子只有 312 个，重复记录占比约 98.9%。
- 候选“添加成功”没有关联到任务 hash，无法直接做“候选指标 -> 最终上传结果”的闭环分析。
- 部分任务的完成状态被 qBittorrent 的 `completion_on=-1` 等占位值干扰，无法准确区分下载阶段与做种阶段上传。
- 下载器快照的 `downloading_count` 在部分下载器返回缺少 `progress` 字段时误等于活跃任务数。
- 任务被删时没有保存最终进度、最终状态和上传窗口峰值，后续只能从海量样本里倒推。

## 非目标

- 不改变任何业务判断。
- 不改变现有刷流、检查、上传保护、删种或下载器选择逻辑。
- 不调整当前种子大小分流、做种人数过滤、无上传价值删种等配置。
- 不迁移 v1 历史库，也不删除 v1 数据。
- 本方案只做“记录什么、怎么存、怎么查”，不做最终优化规则。

## 存储方案

### 新建 v2 数据库

- 新文件：`/config/logs/plugins/brushflowlowfreq_diagnostics_v2.db`
- v1 文件：`brushflowlowfreq_diagnostics.db` 保留不覆盖。
- `diagnostic_meta.schema_version = 2`
- 仍默认保留 30 天滚动记录。

### Schema 关键变化

1. `candidate_snapshots` 增加：

   - `task_hash TEXT`
   - `decision_changed INTEGER`
   - `source_added_at REAL`

   添加成功时把任务 hash 写回对应的候选快照。

2. `task_profiles` 增加候选来源与上传窗口字段：

   - `source_seeders`
   - `source_leechers`
   - `source_free`
   - `source_free_remaining_minutes`
   - `source_size_bytes`
   - `first_real_completed_at`
   - `completion_uploaded`
   - `completion_downloaded`
   - `upload_before_complete`
   - `download_before_complete`
   - `upload_after_complete`
   - `download_after_complete`
   - `peak_interval_upspeed`
   - `peak_interval_upspeed_at`
   - `last_upload_at`
   - `final_state`
   - `final_progress`

3. 新增候选汇总表：

   - `candidate_run_summary`
   - 每次刷流记录一次，按原因统计候选命中数量，不再把相同种子重复写入详情。

4. `torrent_catalog` 增加最新指标：

   - `latest_seeders`
   - `latest_leechers`
   - `latest_free_remaining_minutes`
   - `latest_seen_at`

   每个唯一种子每次刷流只更新最新指标，不新增快照。

5. `task_events` 对完成事件增加真实完成时间：

   - `completed` 事件只在真实完成时记录。
   - `detail.completion_on > 0` 时才允许写完成事件。

## 候选记录规则

新规则只影响诊断写入，不影响刷流：

- 唯一种子第一次出现：写完整 `candidate_snapshots`。
- 决策发生变化，例如从“非免费”变为“免费”或从“可添加”变为“重复种子”：写一条新快照。
- 候选被成功添加：写回 `task_hash`，并把候选指标复制到 `task_profiles`。
- 其它情况：只更新 `torrent_catalog.latest_*` 和写入 `candidate_run_summary`。

这样 30 天库不会因为同一批 200 个旧种子反复出现而膨胀，但仍保留：

- 每个种子首次出现时的指标
- 决策变化历史
- 每次刷流的汇总拒绝原因
- 添加任务与候选指标的关联

## 生命周期计算规则

所有字段都在诊断记录层计算，不参与删种或限速：

1. 任务添加后写 `added` 事件，并把候选快照指标复制进 `task_profiles`。
2. 每次状态更新只记录 `task_samples`。
3. 仅当下载器返回的真实 `completion_on > 0` 时：

   - 记录 `completed` 事件
   - 保存当时的累计上传/下载到 `completion_uploaded/completion_downloaded`
   - 更新 `first_real_completed_at`

4. 每次样本记录后计算：

   - `peak_interval_upspeed`
   - `peak_interval_upspeed_at`
   - `last_upload_at`

5. 删除/归档前更新：

   - `final_state`
   - `final_progress`
   - `upload_before_complete`
   - `upload_after_complete`
   - 删除类型与最终原因

6. 对旧任务或首次诊断前已完成的任务，不补造完成事件，避免污染上传窗口统计。

## 下载器快照修复

- 使用下载器实时 torrent 信息中的真实 `state`、`progress`、`upspeed`、`dlspeed`。
- 只有 `progress < 100` 或状态属于下载中的任务才计入 `downloading_count`。
- `active_count` 与 `downloading_count` 不再允许因字段缺失而相等。
- 记录 `uploading_count` 时只统计 `upspeed > 0`。

## 版本号

升级到 `v4.3.96`。

- `package.v2.json` 更新版本与更新日志。
- `plugin_version = "4.3.96"`。
- README 增加诊断 v2 说明。

## API 与导出

新增 API：

- `GET /diagnostic/status`
- `GET /diagnostic/summary`
- `GET /diagnostic/candidates`
- `GET /diagnostic/tasks`
- `GET /diagnostic/samples`
- `GET /diagnostic/events`
- `GET /diagnostic/downloaders`
- `GET /diagnostic/export`

v2 中这些 API 继续支持任意 `days`、`start`、`end`。

导出内容新增：

- 候选快照关联的 `task_hash`
- 任务来源 leechers/seeders
- 上传窗口字段
- 下载器真实下载中数量

## 实施任务

### Task 1: 新建 v2 Schema 与配置

- 新建 v2 数据库路径与 schema_version=2。
- 保留 v1 数据库逻辑，不删除旧文件。
- 增加配置版本字段。
- 测试：v2 建表成功，v1 文件不受影响。

### Task 2: 候选快照去重与关联

- 实现唯一种子 upsert。
- 实现 `candidate_run_summary`。
- 实现候选添加时写回 `task_hash`。
- 测试：同一种子在多轮刷流中不产生重复详情。

### Task 3: 任务来源与上传窗口

- 实现任务添加时复制候选指标。
- 修复真实完成事件判断。
- 实现完成时累计上传/下载快照。
- 实现峰值、最后上传、删除前最终状态等字段。
- 测试：下载阶段与做种阶段上传可区分。

### Task 4: 下载器快照修复

- 修复 `downloading_count` 计算。
- 测试：缺少 progress 的 torrent 不误算为下载中。

### Task 5: API/导出兼容

- 更新 API 字段与导出。
- 保留任意日期范围查询。
- 测试：导出字段包含候选关联与上传窗口。

### Task 6: 版本号、README 与回归

- 升到 `4.3.96`。
- 更新 README 与 package 更新日志。
- 全量测试通过。

## 观察计划

- 部署到远端 MoviePilot 后开启 v2 记录。
- 不改变当前业务配置，继续运行至少 7 天。
- v1 库保留，便于与新版本交叉验证。
- 7 天后根据 v2 数据做第二次深度分析，再决定是否开始规则优化。

## 验收标准

- 业务测试全部通过，v4.3.96 不改变任何刷流/检查/删种/上传保护行为。
- v2 库和 v1 库同时存在。
- 候选详情不再因重复种子每轮无限增长。
- 添加成功候选与任务 hash 关联完整。
- 完成事件只在真实完成时出现。
- 下载阶段和做种阶段上传可分离开。
- 下载器 `downloading_count` 准确。
- 30 天导出按任意日期范围可用。
