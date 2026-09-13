# brushflowlowfreq 动态调度诊断 v2.2 设计

## 目标

在现有 v2.1 诊断数据基础上，补齐动态调度需要的最终输入变量、影子评分拆解和结果标签，继续只记录、不执行调度。

本版本继续遵守：

- 只影响新添加的种子。
- 不迁移已有任务。
- 不改变当前刷流、检查、上传保护、删种和大小分配行为。
- 暂时不启用自动下载器选择。

## 关键约束

根据现有诊断结论：

- 不使用磁盘总量、磁盘剩余或保种体积作为关键调度变量。磁盘足够，不作为调度核心。
- 不使用下载器全局任务总数作为关键调度变量。其它长期做种任务上传量低，不代表插件托管任务负载。
- 只使用托管任务数、托管下载中任务数、托管做种中任务数、托管上传/下载速度和配置上限。
- 调度目标是最大化新任务带来的上传量，尤其是前 30 分钟上传和任务总上传。

## 现有数据评估

当前 v2.1 数据已经能支持：

- `candidate_size/seeders/leechers/free` 基础候选特征。
- 影子推荐下载器与实际下载器记录。
- 每个下载器的托管任务负载与上传/下载速度。
- 任务从添加、开始下载、首次上传、完成到删除的时序。
- 每个任务的上传/下载累计、检查间速度、峰值和删种结果。
- swarm 变化：收到时 seeders 低，中位约 33 分钟后升至 50，约 65 分钟后升至 100。

当前数据不足：

- 下载器配置中的实际上传/下载总限速大量为空，无法判断带宽余量。
- 候选缺少发布时间、发布年龄、页面排名、免费剩余分钟和标题特征。
- 影子评分只有最终总分，没有候选潜力、下载器效率、下载耗时和窗口收益的拆解。
- 调度决策与最终上传结果的直接关联还不完整。
- 需要在 v2.2 中新增这些字段后重新校准。

## 调度只用变量

### 候选变量

- `size_bytes`
- `seeders`
- `leechers`
- `free_remaining_minutes`
- `publish_age_minutes`
- `page_rank`
- `resolution`
- `content_type`
- `release_group`
- `site`

### 托管任务变量

- `managed_total`
- `managed_downloading`
- `managed_seeding`
- `managed_up_speed`
- `managed_dl_speed`
- `maxdlcount`
- `maxupspeed`
- `maxdlspeed`

### 结果变量

- `uploaded_at_30m`
- `uploaded_at_60m`
- `uploaded_after_30m`
- `uploaded_after_60m`
- `peak_interval_upspeed`
- `total_uploaded`
- `total_downloaded`
- `first_upload_delay`
- `download_start_delay`
- `first_real_completed_at`
- `final_delete_type`

## v2.2 数据表变化

### 1. 扩展 `scheduler_shadow_decisions`

新增字段：

```sql
ALTER TABLE scheduler_shadow_decisions ADD COLUMN publish_age_minutes REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN free_remaining_minutes REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN page_rank INTEGER;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN resolution TEXT;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN content_type TEXT;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN release_group TEXT;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN early_upload_score REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN total_upload_score REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN predicted_early_upload REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN predicted_total_upload REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN expected_download_seconds REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN downloader_efficiency_score REAL;
ALTER TABLE scheduler_shadow_decisions ADD COLUMN candidate_feature_json TEXT;
```

v2.1 数据库存在时执行兼容升级；新库直接使用完整 schema。

### 2. 扩展 `downloader_resource_samples`

新增字段：

```sql
ALTER TABLE downloader_resource_samples ADD COLUMN effective_up_limit REAL;
ALTER TABLE downloader_resource_samples ADD COLUMN effective_dl_limit REAL;
ALTER TABLE downloader_resource_samples ADD COLUMN managed_uploading INTEGER;
ALTER TABLE downloader_resource_samples ADD COLUMN managed_paused INTEGER;
ALTER TABLE downloader_resource_samples ADD COLUMN managed_queued INTEGER;
ALTER TABLE downloader_resource_samples ADD COLUMN managed_checking INTEGER;
```

旧字段 `global_total/global_*` 继续保留用于兼容，但动态调度评分不使用。

### 3. `downloader_efficiency_samples`

```sql
CREATE TABLE IF NOT EXISTS downloader_efficiency_samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sampled_at REAL NOT NULL,
  downloader TEXT NOT NULL,
  window_minutes INTEGER NOT NULL,
  managed_total INTEGER,
  managed_downloading INTEGER,
  managed_seeding INTEGER,
  managed_up_speed REAL,
  managed_dl_speed REAL,
  upload_per_downloading REAL,
  upload_per_task REAL,
  upload_headroom_ratio REAL,
  download_headroom_ratio REAL
);
```

每个检查周期记录 5/15/60 分钟滚动指标，用于比较不同下载器在当前负载下的实际上传效率。

### 4. `task_outcome_samples`

```sql
CREATE TABLE IF NOT EXISTS task_outcome_samples (
  task_hash TEXT PRIMARY KEY REFERENCES task_profiles(task_hash) ON DELETE CASCADE,
  updated_at REAL NOT NULL,
  uploaded_at_30m INTEGER,
  uploaded_at_60m INTEGER,
  uploaded_after_30m INTEGER,
  uploaded_after_60m INTEGER,
  peak_interval_upspeed REAL,
  total_uploaded INTEGER,
  total_downloaded INTEGER,
  first_upload_delay REAL,
  download_start_delay REAL,
  first_real_completed_at REAL,
  final_delete_type TEXT,
  final_uploaded INTEGER,
  final_downloaded INTEGER
);
```

任务样本更新或删除/归档时刷新，不用每次全量重算。

### 5. 任务事件补充

`task_transfer_events.detail` 增加：

- `queued_at`
- `started_at`
- `first_uploaded_at`
- `completed_at`
- `downloader`
- `source_decision_id`

不新增 JSON 字段，沿用 detail JSON。

## 影子调度 v2

### 候选分

早期上传分：

```text
early_score =
  w1 * normalized(leechers)
  + w2 * inverse_score(seeders)
  + w3 * freshness_score(publish_age)
  + w4 * free_window_score(free_remaining_minutes)
  + w5 * page_rank_score
```

总量上传分：

```text
total_score =
  early_score
  + w6 * size_curve(size_bytes)
  + w7 * content_history_score
```

第一版权重使用规则常量：

- leechers 主要影响早期上传。
- seeders 越低，早期机会越大。
- publish age 越新，窗口越靠前。
- 大小用于总量和下载成本，不直接决定下载器。

### 下载器分

```text
downloader_score =
  early_score * managed_upload_efficiency
  * concurrency_headroom
  * upload_headroom
  * download_headroom
```

其中：

- `managed_upload_efficiency = managed_up_speed / max(managed_downloading, 1)`
- `concurrency_headroom = max(0, 1 - managed_downloading / maxdlcount)`
- `upload_headroom = max(0, 1 - managed_up_speed / maxupspeed)`
- `download_headroom = max(0, 1 - managed_dl_speed / maxdlspeed)`
- 不使用全局任务总数、磁盘总量或磁盘剩余。

### 硬约束

- 下载器已启用且健康。
- `managed_downloading < maxdlcount`。
- 托管下载速度未超过 `maxdlspeed`。
- 托管上传速度未超过 `maxupspeed`。
- 无法获取某项上限时，该项不参与打分，并记录缺失原因。

## 结果回填

每轮检查时更新 `task_outcome_samples`：

- 30/60 分钟上传量
- 总上传/下载量
- 峰值检查间上传速度
- 添加→开始下载耗时
- 添加→首次上传耗时
- 完成时间
- 删除类型

影子决策 ID 通过任务 hash 回填到任务事件，用于评估推荐是否有效。

## API 与导出

新增：

- `GET /diagnostic/downloader-efficiency`
- `GET /diagnostic/task-outcomes`

`/diagnostic/export` 增加：

- `downloader_efficiency`
- `task_outcomes`

调度分析 API 需支持：

- 按推荐下载器筛选
- 按实际下载器筛选
- 按删除类型筛选
- 按大小/leechers 区间筛选

## 验收标准

### 数据完整性

- 每次检查写入 5/15/60 分钟下载器效率样本。
- 每个影子决策记录候选特征、早期分、总量分、预计下载耗时和推荐理由。
- 每个新增任务能回填 30/60 分钟上传和最终结果。
- 托管任务与下载器效率数据可关联。

### 模型校准

运行至少 7 天后计算：

- 预测早期上传与实际 30 分钟上传的相关性。
- 预测总上传与实际总上传的相关性。
- 推荐下载器与实际最佳下载器的差异。
- 托管下载中任务数与任务上传的负相关是否稳定。
- leechers、seeders、大小和发布时间对早期上传的解释度。

只有影子模型明显优于当前固定大小分流，才进入下一阶段实盘调度。

## 非目标

- 不在 v2.2 中执行调度。
- 不迁移已有任务。
- 不调整现有下载器配置。
- 不使用磁盘容量作为调度关键项。
- 不使用全局任务数作为调度关键项。
