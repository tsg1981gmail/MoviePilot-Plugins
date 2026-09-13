# brushflowlowfreq 动态调度诊断 v2.2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 v2.1 基础上补齐动态调度所需的候选特征、下载器效率、影子评分拆解和任务结果回填，不执行任何实际调度。

**Architecture:** 继续使用 v2 诊断数据库，通过兼容迁移升级到 schema `2.2`。所有新增字段和表只记录调度输入、影子推荐和后续结果，实际分配继续使用当前大小分流逻辑。

**Tech Stack:** Python 3、MoviePilot v2、标准库 `sqlite3`、`unittest`。

---

## Task 1: Schema 2.2 兼容升级

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

验证旧 v2.1 数据库再次打开后会新增：

- `scheduler_shadow_decisions` 的候选特征与拆解字段
- `downloader_resource_samples` 的 effective limit 和 managed 状态字段
- `downloader_efficiency_samples`
- `task_outcome_samples`
- `schema_version=2.2`

- [ ] **Step 2: 新增兼容迁移**

实现：

```python
def _ensure_column(self, table, column, definition):
    columns = {
        row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
```

在 `_init_schema()` 末尾调用迁移。

- [ ] **Step 3: 新增 v2.2 表和字段**

按 spec 增加：

- `downloader_efficiency_samples`
- `task_outcome_samples`
- `scheduler_shadow_decisions` 新字段
- `downloader_resource_samples` 新字段

- [ ] **Step 4: 更新 meta 为 2.2/4.3.98**

- [ ] **Step 5: 运行测试和全量回归**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git commit -am "feat: 诊断schema升级到2.2"
```

---

## Task 2: 候选特征与影子评分 v2

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

验证影子决策包含：

- `publish_age_minutes`
- `free_remaining_minutes`
- `page_rank`
- `resolution/content_type/release_group`
- `early_upload_score`
- `total_upload_score`
- `predicted_early_upload`
- `predicted_total_upload`
- `expected_download_seconds`
- `downloader_efficiency_score`
- `candidate_feature_json`

- [ ] **Step 2: 实现候选特征提取**

从标题提取：

- 分辨率：`2160p/1080p/1080i/720p/4K`
- 类型：电影/剧集/综艺/动漫
- 发布组：标题最后一段常见 `-GROUP`

发布时间年龄使用现有 `__get_pubminutes()`。

- [ ] **Step 3: 实现早期分**

```python
early_score = (
    normalized_leechers
    * inverse_seeders
    * freshness_score
    * free_window_score
    * page_rank_score
)
```

具体权重以常量实现，第一阶段只记录。

- [ ] **Step 4: 实现总量分**

```python
total_score = early_score + size_curve + content_history_score
```

其中 `content_history_score` 可从已有 task_profiles 中按大小区间、分辨率和 downloader 聚合。

- [ ] **Step 5: 实现预计下载时间**

```text
expected_download_seconds = size_bytes
  / max(同下载器托管下载速度, 最低速度兜底)
```

- [ ] **Step 6: 更新 `record_shadow_decision()`**

接受新增字段并写入数据库。

- [ ] **Step 7: 运行测试**

- [ ] **Step 8: Commit**

```bash
git commit -am "feat: 影子调度v2候选特征与评分拆解"
```

---

## Task 3: 下载器效率滚动样本

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

验证 5/15/60 分钟窗口能写入。

- [ ] **Step 2: 实现 `record_downloader_efficiency()`**

字段：

- `upload_per_downloading`
- `upload_per_task`
- `upload_headroom_ratio`
- `download_headroom_ratio`

没有限速配置时对应 headroom 写 NULL。

- [ ] **Step 3: 接入 check()**

使用当前托管任务的上传/下载总和：

```text
upload_per_downloading =
  managed_up_speed / max(managed_downloading, 1)
```

对 5/15/60 分钟窗口分别计算。

- [ ] **Step 4: 运行测试**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat: 记录下载器托管效率滚动样本"
```

---

## Task 4: 任务结果回填

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

验证 `task_outcome_samples` 能保存：

- 30/60 分钟上传
- 总上传/下载
- 上传峰值
- 首次上传延迟
- 下载开始延迟
- 完成时间
- 删除类型

- [ ] **Step 2: 实现 `record_task_outcome()`**

从：

- `task_samples`
- `task_transfer_events`
- `task_profiles`

聚合计算。

- [ ] **Step 3: 接入更新点**

- 每次任务样本后更新
- 任务完成时更新
- 删除/归档时最终更新

- [ ] **Step 4: 运行测试**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat: 回填任务上传结果特征"
```

---

## Task 5: 传输事件增强与影子决策关联

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`

- [ ] **Step 1: 写失败测试**

验证 `task_transfer_events.detail` 包含：

- `queued_at`
- `started_at`
- `first_uploaded_at`
- `completed_at`
- `source_decision_id`

- [ ] **Step 2: 让 `record_shadow_decision()` 返回决策 ID**

当前返回 None，改为返回 `lastrowid`。

- [ ] **Step 3: 在任务添加成功后绑定决策 ID**

事件 `add_requested.detail.source_decision_id` 写入影子决策 ID。

- [ ] **Step 4: 运行测试**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat: 关联影子决策与任务执行结果"
```

---

## Task 6: API、数据页与导出

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 新增 API**

- `GET /diagnostic/downloader-efficiency`
- `GET /diagnostic/task-outcomes`

- [ ] **Step 2: 扩展 export**

增加：

- `downloader_efficiency`
- `task_outcomes`

- [ ] **Step 3: 数据页增加统计项**

- 下载器效率样本
- 任务结果样本

- [ ] **Step 4: 运行测试**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat: 暴露v2.2调度诊断数据"
```

---

## Task 7: 清理、版本和部署

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `package.v2.json`
- Modify: `plugins.v2/brushflowlowfreq/README.md`

- [ ] **Step 1: 扩展 cleanup**

清理：

- `downloader_efficiency_samples`
- `task_outcome_samples`

两个表按 30 天滚动清理。

- [ ] **Step 2: 升到 v4.3.98**

- [ ] **Step 3: 全量测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: PASS。

- [ ] **Step 4: 合并并部署**

- 合并到 main 并推送 GitHub
- 部署到远端 MoviePilot
- 验证 schema_version=2.2
- 验证影子决策、效率样本和结果样本持续写入

- [ ] **Step 5: 继续观察**

保持现有业务配置不变，至少观察 7-14 天。

---

## 验收标准

- 业务行为保持不变。
- schema_version 为 `2.2`。
- 影子决策记录候选特征、早期分、总量分和预计下载时间。
- 每个下载器持续记录 5/15/60 分钟托管效率。
- 每个新任务有 30/60 分钟和最终上传结果。
- 推荐下载器与实际结果可以通过任务 hash 和决策 ID直接关联。
- 不使用磁盘容量或全局任务总数参与评分。
