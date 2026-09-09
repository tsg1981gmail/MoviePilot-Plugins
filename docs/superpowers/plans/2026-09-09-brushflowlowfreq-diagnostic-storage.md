# brushflowlowfreq 独立诊断记录库实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有刷流、检查、上传保护、删种行为的前提下，为 `brushflowlowfreq` 增加 SQLite 独立诊断库，记录 30 天滚动数据并提供只读查看与任意日期范围导出 API。

**Architecture:** 在插件单文件内新增 `DiagnosticRecorder` 私有类，使用标准库 `sqlite3`。所有记录点都在业务判断完成后调用，任何诊断异常都不影响原流程。新增配置 `diagnostic_enabled` 与 `diagnostic_retention_days`。

**Tech Stack:** Python 3、MoviePilot v2、Python 标准库 `sqlite3`、`unittest`。

---

## 文件结构

- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - 新增 `DiagnosticRecorder`。
  - 修改 `BrushConfig`、`get_form()`、`init_plugin()`、`stop_service()`。
  - 修改 `__brush_site_torrents()`、`__download()`、`check()`、`__update_torrent_tasks_state()`、`__apply_upload_protection_actions()`、删除与归档路径。
- Modify: `tests/test_brushflowlowfreq_features.py`
- Modify: `package.v2.json`
- Modify: `plugins.v2/brushflowlowfreq/README.md`

---

## Task 1: 配置与 SQLite 基础设施

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `BrushConfig.__init__`
  - `get_form()`
  - `init_plugin()` / `stop_service()`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试，验证配置默认关闭且保留 30 天**

```python
def test_diagnostic_config_defaults_are_off_and_30_days(self):
    config = self.module.BrushConfig({})
    self.assertFalse(config.diagnostic_enabled)
    self.assertEqual(config.diagnostic_retention_days, 30)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_diagnostic_config_defaults_are_off_and_30_days -v`

Expected: FAIL，字段尚不存在。

- [ ] **Step 3: 在 `BrushConfig` 增加配置字段**

在 `log_mode` 附近新增：

```python
self.diagnostic_enabled = bool(config.get("diagnostic_enabled", False))
self.diagnostic_retention_days = int(self.__parse_number(
    config.get("diagnostic_retention_days", 30)
) or 30)
self.diagnostic_retention_days = max(1, self.diagnostic_retention_days)
```

- [ ] **Step 4: 在表单默认值中增加字段**

在 `get_form()` 的默认配置字典与诊断 UI 需要的位置加入：

```python
"diagnostic_enabled": False,
"diagnostic_retention_days": 30,
```

在“更多配置”区域增加一个 VRow，包含：

- `VSwitch model=diagnostic_enabled`，文案“独立诊断记录”
- `VTextField model=diagnostic_retention_days`，label“诊断保留天数”，hint“默认 30 天，只清理诊断库”

- [ ] **Step 5: 写失败测试，验证默认关闭时不创建数据库**

```python
def test_diagnostic_disabled_does_not_open_database(self):
    plugin = self._new_plugin({})
    self.assertIsNone(plugin._BrushFlowLowFreq__diagnostic_recorder)
```

- [ ] **Step 6: 新增 `DiagnosticRecorder`**

在类外新增：

```python
class DiagnosticRecorder:
    """独立诊断记录器，失败时只记日志，不参与业务。"""

    def __init__(self, db_path, retention_days=30):
        self.db_path = str(db_path)
        self.retention_days = max(1, int(retention_days or 30))
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._init_schema()
        self._set_meta()
```

实现 `_init_schema()`，按 spec 中的 `CREATE TABLE IF NOT EXISTS` 建表。

`DiagnosticRecorder` 提供以下方法，全部内部捕获异常：

```python
def record_brush_start(self, site, started_at)
def record_brush_end(self, run_id, finished_at, pages, candidates_seen, added, rejected, scan_ms)
def record_candidate(self, run_id, site, torrent, decision, reject_reason=None, downloader=None)
def record_task_added(self, task_hash, torrent_task)
def record_task_sample(self, task_hash, sampled_at, downloader, torrent_info, torrent_task)
def record_task_event(self, task_hash, event_at, event_type, detail=None)
def record_downloader_sample(self, sampled_at, downloader, counts)
def finalize_task(self, task_hash, torrent_task, deleted_type=None, deleted_reason=None)
def cleanup(self)
def close(self)
```

- [ ] **Step 7: 在插件实例上初始化和关闭 recorder**

在 `init_plugin()` 中：

```python
self.__diagnostic_recorder = None
if self._brush_config.diagnostic_enabled:
    self.__diagnostic_recorder = DiagnosticRecorder(
        db_path=self.__diagnostic_db_path(),
        retention_days=self._brush_config.diagnostic_retention_days,
    )
```

在 `stop_service()` 中：

```python
if getattr(self, "__diagnostic_recorder", None):
    self.__diagnostic_recorder.close()
    self.__diagnostic_recorder = None
```

`__diagnostic_db_path()` 返回：

```python
base = getattr(settings, "LOG_PATH", None) or getattr(settings, "CONFIG_PATH", "")
diagnostic_dir = Path(str(base)).parent / "plugins" if not str(base).endswith("plugins") else Path(str(base))
diagnostic_dir.mkdir(parents=True, exist_ok=True)
return diagnostic_dir / "brushflowlowfreq_diagnostics.db"
```

实际实现时按运行环境修正目录，测试使用临时目录。

- [ ] **Step 8: 增加 recorder 辅助方法包装**

插件内提供：

```python
def __diagnostic(self, method_name, *args, **kwargs):
    recorder = getattr(self, "__diagnostic_recorder", None)
    if not recorder:
        return None
    try:
        return getattr(recorder, method_name)(*args, **kwargs)
    except Exception:
        logger.warning("brushflowlowfreq 诊断记录失败", exc_info=True)
        return None
```

- [ ] **Step 9: 运行测试**

Run: 上述两个新测试及 `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: PASS。

- [ ] **Step 10: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 增加独立诊断记录器与配置开关"
```

---

## Task 2: 刷流候选与刷流周期记录

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `__brush_site_torrents()`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试，验证候选被记录**

```python
def test_diagnostic_records_candidate_and_brush_run(self):
    recorder = self.module.DiagnosticRecorder(temp_db_path, retention_days=30)
    run_id = recorder.record_brush_start("天空", time.time())
    recorder.record_brush_end(
        run_id, time.time(), pages=2,
        candidates_seen=1, added=1, rejected=0, scan_ms=10,
    )
    counts = recorder.query_counts()
    self.assertEqual(counts["brush_runs"], 1)
    recorder.close()
```

`query_counts()` 是供测试使用的汇总方法。

- [ ] **Step 2: 运行测试确认失败**

Expected: FAIL，`record_brush_start`/`query_counts` 尚不存在。

- [ ] **Step 3: 实现 brush run 与 candidate 写入**

在 `__brush_site_torrents()` 开始时：

```python
diagnostic_run_id = self.__diagnostic("record_brush_start", siteinfo.name, time.time())
diagnostic_seen = 0
diagnostic_added = 0
diagnostic_rejected = 0
diagnostic_started_at = time.time()
```

每个种子完成过滤后，无论是否添加，都记录：

```python
diagnostic_seen += 1
self.__diagnostic(
    "record_candidate",
    diagnostic_run_id,
    siteinfo.name,
    torrent,
    decision="added" if added else "rejected",
    reject_reason=reject_reason,
    downloader=downloader_name,
)
```

函数返回前：

```python
self.__diagnostic(
    "record_brush_end",
    diagnostic_run_id,
    time.time(),
    pages=len(torrents_pages),
    candidates_seen=diagnostic_seen,
    added=diagnostic_added,
    rejected=diagnostic_rejected,
    scan_ms=int((time.time() - diagnostic_started_at) * 1000),
)
```

`record_candidate()` 负责 upsert `torrent_catalog` 并插入 `candidate_snapshots`。

- [ ] **Step 4: 运行测试**

Run: 新测试及 `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 记录刷流候选快照与刷流周期"
```

---

## Task 3: 托管任务全生命周期记录

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `__download()` 成功返回处
  - `__update_torrent_tasks_state()`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试，验证任务样本可查询**

```python
def test_diagnostic_records_task_added_and_samples(self):
    recorder = self.module.DiagnosticRecorder(temp_db_path, retention_days=30)
    task = {"site_name": "天空", "title": "test", "size": 1024}
    recorder.record_task_added("hash1", task)
    recorder.record_task_sample(
        "hash1", time.time(), "NAS QB",
        {"downloaded": 10, "uploaded": 20, "state": "downloading"},
        {"last_check_interval_upspeed": 100},
    )
    rows = recorder.query_task_samples("hash1")
    self.assertEqual(len(rows), 1)
    recorder.close()
```

- [ ] **Step 2: 运行测试确认失败**

Expected: FAIL。

- [ ] **Step 3: 在任务添加成功后写档案**

在 `torrent_tasks[hash_string] = torrent_task` 后：

```python
self.__diagnostic("record_task_added", hash_string, torrent_task)
```

- [ ] **Step 4: 在状态更新后写样本**

在 `__update_torrent_tasks_state()` 更新每个 `torrent_task` 字段完成后：

```python
self.__diagnostic(
    "record_task_sample",
    torrent_hash,
    time.time(),
    self._active_downloader_name,
    torrent_info,
    torrent_task,
)
```

同时用已有字段更新 `task_profiles`：

- `first_downloaded_time`
- `first_uploaded_time`
- `completion_on`

当任务完成时写入 `task_events(event_type="completed")`。

- [ ] **Step 5: 运行测试**

Run: 新测试及全量测试。

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 记录托管任务档案与检查周期样本"
```

---

## Task 4: 上传保护、删种、归档和下载器快照

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `__apply_upload_protection_actions()`
  - 删除成功路径
  - `__auto_archive_tasks()`
  - `check()` 下载器快照
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试，验证事件与下载器样本**

```python
def test_diagnostic_records_events_and_downloader(self):
    recorder = self.module.DiagnosticRecorder(temp_db_path, retention_days=30)
    recorder.record_task_added("hash1", {"site_name": "天空", "title": "t", "size": 1})
    recorder.record_task_event("hash1", time.time(), "deleted", {"type": "no_value"})
    recorder.record_downloader_sample(time.time(), "NAS QB", {
        "active_count": 3,
        "downloading_count": 1,
        "upload_speed": 100,
    })
    self.assertEqual(recorder.query_events("hash1")[0]["event_type"], "deleted")
    self.assertEqual(recorder.query_downloader_samples("NAS QB")[0]["active_count"], 3)
    recorder.close()
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 记录上传保护动作**

在 `__apply_upload_protection_actions()` 实际执行动作成功后记录：

```python
self.__diagnostic(
    "record_task_event",
    torrent_hash,
    time.time(),
    "upload_action",
    {
        "action": action,
        "stage": torrent_task.get("upload_protection_stage"),
        "reason": reason,
    },
)
```

小池子例外释放路径同样记录。

- [ ] **Step 4: 记录删种与归档**

在删除确认成功后：

```python
self.__diagnostic("finalize_task", torrent_hash, torrent_tasks[torrent_hash])
self.__diagnostic(
    "record_task_event",
    torrent_hash,
    time.time(),
    "deleted",
    {"delete_type": delete_type},
)
```

在 `__auto_archive_tasks()` 中归档已删除任务时写 `archived` 事件。

- [ ] **Step 5: 记录下载器快照**

在 `check()` 获取到 `seeding_torrents` 后，对当前下载器统计：

- 当前组内活跃任务数
- 正在下载任务数
- 当前正在上传任务数
- 所有任务的上传/下载速度合计

然后：

```python
self.__diagnostic("record_downloader_sample", time.time(), downloader_name, snapshot)
```

- [ ] **Step 6: 运行测试与全量回归**

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 记录上传保护动作、删种归档与下载器快照"
```

---

## Task 5: 30 天滚动清理

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

```python
def test_diagnostic_retention_deletes_only_expired_rows(self):
    recorder = self.module.DiagnosticRecorder(temp_db_path, retention_days=30)
    old_ts = time.time() - 31 * 86400
    recorder.record_task_added("hash_old", {"site_name": "天空", "title": "old"})
    recorder.insert_task_sample("hash_old", old_ts, {})
    recorder.record_task_added("hash_new", {"site_name": "天空", "title": "new"})
    recorder.insert_task_sample("hash_new", time.time(), {})
    recorder.cleanup()
    self.assertEqual(recorder.count_samples("hash_new"), 1)
    self.assertEqual(recorder.count_samples("hash_old"), 0)
    recorder.close()
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 cleanup**

```python
def cleanup(self):
    cutoff = time.time() - self.retention_days * 86400
    with self._lock:
        self._conn.execute("DELETE FROM candidate_snapshots WHERE seen_at < ?", (cutoff,))
        self._conn.execute(
            "DELETE FROM brush_runs WHERE started_at < ? AND NOT EXISTS ("
            "SELECT 1 FROM candidate_snapshots s WHERE s.run_id = brush_runs.id)",
            (cutoff,),
        )
        self._conn.execute("DELETE FROM task_samples WHERE sampled_at < ?", (cutoff,))
        self._conn.execute("DELETE FROM task_events WHERE event_at < ?", (cutoff,))
        self._conn.execute("DELETE FROM downloader_samples WHERE sampled_at < ?", (cutoff,))
        self._conn.commit()
```

活跃 `task_profiles` 不删除。

- [ ] **Step 4: 运行测试**

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 诊断库按保留天数滚动清理"
```

---

## Task 6: 只读诊断 API

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `get_api()`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

```python
def test_get_api_includes_diagnostic_endpoints(self):
    plugin = self._new_plugin({})
    paths = [item["path"] for item in plugin.get_api()]
    self.assertIn("/diagnostic/status", paths)
    self.assertIn("/diagnostic/summary", paths)
    self.assertIn("/diagnostic/samples", paths)
    self.assertIn("/diagnostic/export", paths)
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 新增 endpoint**

`get_api()` 新增：

```python
{
    "path": "/diagnostic/status",
    "endpoint": self.__diagnostic_status,
    "methods": ["GET"],
},
```

同 spec 增加 `summary`、`candidates`、`tasks`、`samples`、`events`、`downloaders`、`export`。

所有端点只读，默认只查询最近 `30` 天；支持 `days`、`from`、`to` 参数。

`export` 支持：

- `format=jsonl`
- `format=csv`

数据不足时不报错，返回空结果。

- [ ] **Step 4: 运行测试与全量回归**

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 新增诊断只读 API 与任意日期导出"
```

---

## Task 7: 版本号、文档与部署说明

**Files:**
- Modify: `package.v2.json`
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `plugins.v2/brushflowlowfreq/README.md`

- [ ] **Step 1: 升到 4.3.93**

- `package.v2.json`
- `plugin_version`
- README 新增版本说明

README 增加：

```markdown
- v4.3.93
  - **独立诊断库**：新增默认关闭的 SQLite 诊断记录，30 天滚动保留
  - 诊断不参与刷流、检查、上传保护或删种判断
  - 新增只读诊断 API 与任意日期范围导出
```

- [ ] **Step 2: 运行版本一致性测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_plugin_version_matches_package_manifest -v`

Expected: PASS。

- [ ] **Step 3: 全量测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: 全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add package.v2.json plugins.v2/brushflowlowfreq/__init__.py plugins.v2/brushflowlowfreq/README.md
git commit -m "chore: bump version to v4.3.93"
```

---

## 验收标准

- 默认关闭诊断时，数据库不创建，现有 221+ 测试全部通过。
- 开启诊断后，业务判断、删种、限速结果与关闭时完全一致。
- 每个已托管任务有从添加到删除/归档的完整检查样本。
- 每个候选种子有决策快照，但不保留后续生命周期。
- SQLite 默认保留 30 天，可按 `days`、`from`、`to` 任意导出。
- 诊断写失败不会导致插件任务失败。
- 版本号为 `4.3.93`。
