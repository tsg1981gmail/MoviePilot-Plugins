# brushflowlowfreq 动态调度第一阶段诊断实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为未来动态下载器调度补齐配置、下载器资源、swarm、影子决策和任务传输时序数据，同时不改变任何现有业务行为。

**Architecture:** 继续使用 v2 诊断数据库，将 schema 升级到 `2.1`，新增独立记录表和 API。影子调度只计算和记录推荐下载器，不执行分配。实际刷流继续使用当前大小分流逻辑。

**Tech Stack:** Python 3、MoviePilot v2、Python 标准库 `sqlite3`、`unittest`。

---

## 文件结构

- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `DiagnosticRecorder` schema 与记录方法
  - `init_plugin()` 下载器配置快照
  - `check()` 下载器资源采样
  - `__brush_site_torrents()` swarm 与影子决策
  - `__update_torrent_tasks_state()` 任务传输事件
  - 诊断 API 与数据页
- Modify: `tests/test_brushflowlowfreq_features.py`
- Modify: `package.v2.json`
- Modify: `plugins.v2/brushflowlowfreq/README.md`

---

## Task 1: Schema 2.1 与下载器配置快照

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

验证 v2 数据库初始化后存在：

- `downloader_config_snapshots`
- `downloader_resource_samples`
- `task_swarm_samples`
- `scheduler_shadow_decisions`
- `task_transfer_events`

```python
def test_diagnostic_v21_schema_tables(self):
    recorder = self.module.DiagnosticRecorder(temp_db_path, retention_days=30)
    tables = {
        row["name"] for row in recorder.fetch_rows(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    self.assertIn("downloader_config_snapshots", tables)
    self.assertIn("downloader_resource_samples", tables)
    self.assertIn("task_swarm_samples", tables)
    self.assertIn("scheduler_shadow_decisions", tables)
    self.assertIn("task_transfer_events", tables)
    self.assertEqual(
        recorder.fetch_rows(
            "SELECT value FROM diagnostic_meta WHERE key='schema_version'"
        )[0]["value"],
        "2.1",
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_diagnostic_v21_schema_tables -v`

Expected: FAIL。

- [ ] **Step 3: 新增 v2.1 表**

在 `_init_schema()` 中加入 spec 中的五张表及相关索引。

将 meta 更新为：

```python
"schema_version": "2.1",
"plugin_version": "4.3.97",
```

- [ ] **Step 4: 在 `init_plugin()` 记录配置快照**

诊断记录器启动后调用：

```python
self.__record_downloader_config_snapshot()
```

方法内容：

```python
def __record_downloader_config_snapshot(self):
    recorder = self.__diagnostic_recorder_or_none()
    if not recorder:
        return
    brush_config = self._brush_config
    if not brush_config:
        return
    for name in self.__configured_downloader_names():
        profile = self.__get_downloader_profile(name)
        data = {
            "enabled": bool(profile.get("enabled")),
            "is_default": name == brush_config.downloader,
            "maxdlcount": profile.get("maxdlcount") or brush_config.maxdlcount,
            "maxupspeed": profile.get("maxupspeed") or brush_config.maxupspeed,
            "maxdlspeed": profile.get("maxdlspeed") or brush_config.maxdlspeed,
            "disksize": profile.get("disksize") or brush_config.disksize,
            "up_speed": profile.get("up_speed") or brush_config.up_speed,
            "dl_speed": profile.get("dl_speed") or brush_config.dl_speed,
            "save_path": profile.get("save_path") or brush_config.save_path,
            "qb_category": profile.get("qb_category") or brush_config.qb_category,
            "raw_json": json.dumps(profile, ensure_ascii=False, default=str),
        }
        self.__diagnostic("record_downloader_config", name, data)
```

- [ ] **Step 5: 实现 `record_downloader_config()`**

```python
def record_downloader_config(self, downloader, data=None):
    data = data or {}
    self._safe_execute(
        """
        INSERT INTO downloader_config_snapshots(
          sampled_at, downloader, enabled, is_default, maxdlcount,
          maxupspeed, maxdlspeed, disksize, up_speed, dl_speed,
          save_path, qb_category, raw_json
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            time.time(), str(downloader or ""),
            self._number(data.get("enabled")),
            self._number(data.get("is_default")),
            self._number(data.get("maxdlcount")),
            self._number(data.get("maxupspeed")),
            self._number(data.get("maxdlspeed")),
            self._number(data.get("disksize")),
            self._number(data.get("up_speed")),
            self._number(data.get("dl_speed")),
            str(data.get("save_path") or "") or None,
            str(data.get("qb_category") or "") or None,
            str(data.get("raw_json") or "") or None,
        ),
    )
```

- [ ] **Step 6: 运行测试**

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 诊断 schema 2.1 与下载器配置快照"
```

---

## Task 2: 下载器资源快照

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

验证资源记录能区分全局与托管任务，并正确处理下载状态。

```python
def test_diagnostic_records_downloader_resource_snapshot(self):
    recorder = self.module.DiagnosticRecorder(temp_db_path, retention_days=30)
    recorder.record_downloader_resource("QB-1", {
        "global_total": 10,
        "global_downloading": 2,
        "global_queued": 1,
        "managed_total": 4,
        "managed_downloading": 1,
        "global_up_speed": 100,
        "global_dl_speed": 200,
    })
    recorder.commit()
    rows = recorder.fetch_rows("SELECT * FROM downloader_resource_samples")
    self.assertEqual(rows[0]["global_total"], 10)
    self.assertEqual(rows[0]["managed_downloading"], 1)
    recorder.close()
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现状态标准化**

新增辅助函数：

```python
@staticmethod
def diagnostic_is_downloading_state(state, progress=None, completion_on=None,
                                    seeding_time=None):
    state = str(state or "").lower()
    if completion_on is not None and float(completion_on or 0) > 0:
        return False
    if seeding_time is not None and float(seeding_time or 0) > 0:
        return False
    if "downloading" in state or "stalleddl" in state or "metadl" in state:
        return True
    if state in {"queueddl", "checkingdl", "forceddl", "allocating", "moving"}:
        return True
    if progress is not None:
        try:
            value = float(progress)
            if value > 1:
                value = value / 100.0
            return value < 1.0
        except (TypeError, ValueError):
            return False
    return False
```

- [ ] **Step 4: 实现 `record_downloader_resource()`**

保存 spec 中的 global/managed 字段。磁盘字段无法获取时写 NULL。

- [ ] **Step 5: 在 `check()` 中采集全局与托管快照**

使用当前下载器返回的完整 torrent 列表：

- global 统计所有 torrent。
- managed 只统计当前插件任务。
- 使用真实 state、progress、completion_on、seeding_time。
- 不再用 `progress < 100` 作为唯一判断。

在现有 `record_downloader_sample()` 后新增资源快照。

- [ ] **Step 6: 运行测试和全量回归**

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 记录下载器全局与托管资源快照"
```

---

## Task 3: 任务 swarm 时序

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`

- [ ] **Step 1: 写失败测试**

```python
def test_diagnostic_records_task_swarm_sample(self):
    recorder = self.module.DiagnosticRecorder(temp_db_path, retention_days=30)
    recorder.record_task_added("hash1", {"site_name": "天空", "title": "t"})
    recorder.record_task_swarm_sample(
        task_hash="hash1",
        site="天空",
        torrent_key="details.php?id=1",
        seeders=1,
        leechers=18,
        is_free=1,
        free_remaining_minutes=60,
        rank_position=3,
    )
    rows = recorder.fetch_rows("SELECT * FROM task_swarm_samples")
    self.assertEqual(rows[0]["leechers"], 18)
    recorder.close()
```

- [ ] **Step 2: 实现 `record_task_swarm_sample()`**

- [ ] **Step 3: 在刷流列表中匹配托管任务**

使用 `site + page_url` 或标题匹配，匹配成功后写 swarm 样本。

只使用本轮已经获取的站点列表，不增加详情页请求。

- [ ] **Step 4: 运行测试**

- [ ] **Step 5: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 记录托管任务swarm时序"
```

---

## Task 4: 影子调度决策

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`

- [ ] **Step 1: 写失败测试**

验证影子决策不会调用下载器，且会记录推荐下载器和实际下载器。

```python
def test_shadow_scheduler_does_not_change_actual_downloader(self):
    plugin = self._new_plugin({
        "downloader": "QB-1",
        "multi_downloader_enabled": True,
    })
    calls = []
    plugin._BrushFlowLowFreq__record_shadow_decision = (
        lambda **kwargs: calls.append(kwargs)
    )
    actual = "QB-1"
    plugin._BrushFlowLowFreq__evaluate_shadow_scheduler(
        candidate={"size": 1024, "leechers": 20, "seeders": 1},
        actual_downloader=actual,
        torrent_key="details.php?id=1",
    )
    self.assertEqual(actual, "QB-1")
    self.assertEqual(len(calls), 1)
    self.assertEqual(calls[0]["actual_downloader"], "QB-1")
```

- [ ] **Step 2: 实现影子决策输入**

决策函数接收：

- candidate 指标
- 实际下载器
- 当前下载器资源快照
- 下载器配置
- 任务来源信息

返回推荐下载器和分数。

- [ ] **Step 3: 硬约束过滤**

实现：

```python
hard_constraints = {
    "online": True,
    "enabled": True,
    "slot_ok": True,
    "upload_headroom_ok": True,
    "download_headroom_ok": True,
    "disk_ok": True,
}
```

无法获取的指标写 NULL，并降低决策置信度，不抛出异常。

- [ ] **Step 4: 评分**

候选分：

```python
predicted_upload_score = (
    leechers / max(seeders + 1, 1)
) * freshness_factor * size_factor * history_factor
```

资源分：

```python
resource_score = (
    upload_headroom
    * download_headroom
    * slot_headroom
    * disk_headroom
    * recent_upload_efficiency
)
```

具体系数先使用规则常量，第一阶段不调参。

- [ ] **Step 5: 接入添加流程**

在候选通过全部条件后、实际 `__download()` 前执行影子决策。

不得修改 `downloader_name`，不得切换 `_active_downloader_name`，不得调用下载器。

- [ ] **Step 6: 记录决策**

写入 `scheduler_shadow_decisions`，包含：

- actual_downloader
- recommended_downloader
- hard_constraint_json
- downloader_scores_json
- decision_reason
- decision_ms
- mode=`shadow`

- [ ] **Step 7: 运行测试和全量回归**

- [ ] **Step 8: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 记录影子调度决策"
```

---

## Task 5: 任务传输事件

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`

- [ ] **Step 1: 写失败测试**

验证以下事件可记录和查询：

- `add_requested`
- `download_started`
- `first_uploaded`
- `completed`
- `deleted`
- `archived`

- [ ] **Step 2: 实现 `record_transfer_event()`**

写入 `task_transfer_events`。

- [ ] **Step 3: 接入生命周期**

在下列路径后记录：

- `__download()` 返回 hash
- 首次下载量增加
- 首次上传量增加
- 真实完成
- 删除成功
- 归档

- [ ] **Step 4: 保证幂等**

每条事件只记录一次，除 `deleted`/`archived` 外不重复。

- [ ] **Step 5: 运行测试**

- [ ] **Step 6: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 记录任务传输生命周期事件"
```

---

## Task 6: API、数据页和导出

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

验证 `get_api()` 新增：

- `/diagnostic/downloader-config`
- `/diagnostic/downloader-resources`
- `/diagnostic/swarm`
- `/diagnostic/scheduler`

验证数据页显示新表记录数。

- [ ] **Step 2: 实现只读 API**

全部支持 `days`、`start`、`end`、`limit`。

- [ ] **Step 3: 扩展 export**

新增可选块：

- `downloader_configs`
- `downloader_resources`
- `swarm_samples`
- `scheduler_decisions`
- `transfer_events`

- [ ] **Step 4: 数据页增加统计项**

显示：

- 下载器配置快照数
- 下载器资源快照数
- swarm 样本数
- 影子调度决策数
- 传输事件数

- [ ] **Step 5: 运行测试**

- [ ] **Step 6: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 暴露动态调度诊断数据"
```

---

## Task 7: 30 天清理、版本和部署

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `package.v2.json`
- Modify: `plugins.v2/brushflowlowfreq/README.md`

- [ ] **Step 1: 扩展 cleanup**

清理以下表中早于保留期的数据：

- `downloader_config_snapshots`
- `downloader_resource_samples`
- `task_swarm_samples`
- `scheduler_shadow_decisions`
- `task_transfer_events`

活跃 `task_profiles` 继续保留。

- [ ] **Step 2: 版本升到 4.3.97**

- [ ] **Step 3: 全量回归**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: 全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add package.v2.json plugins.v2/brushflowlowfreq/README.md plugins.v2/brushflowlowfreq/__init__.py
git commit -m "chore: bump version to v4.3.97"
```

- [ ] **Step 5: 合并并部署**

- 合并到 main 并推送 GitHub
- 部署到远端 MoviePilot
- 保持现有业务配置不变
- 验证 schema_version=2.1 和新表写入
- 开始至少 14 天观察

---

## 验收标准

- 不改变任何现有刷流、检查、上传保护和删种行为。
- schema_version 为 `2.1`。
- 五张新增表持续写入。
- 影子调度只记录推荐下载器，不影响实际下载器。
- 能按任意日期范围导出新增数据。
- 远端连续运行至少 14 天后再进入调度规则设计阶段。
