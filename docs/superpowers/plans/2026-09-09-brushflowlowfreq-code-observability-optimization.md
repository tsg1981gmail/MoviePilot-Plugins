# brushflowlowfreq 代码与可观测性优化实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复多下载器模式下检查收尾重复执行、缺少分下载器统计与下载器上下文日志，以及小池子例外释放清空无上传价值计数的问题。

**Architecture:** 保留现有单文件插件结构。把 `check()` 末尾的“归档/统计/保存”收敛到统一收尾方法，多下载器由外层只收尾一次；统计信息中新增 `downloaders` 分组并输出分下载器摘要。所有新增任务、上传保护动作和例外释放日志补充当前下载器名。小池子例外释放只清理限速状态，不再清空 `upload_protection_no_upload_streak`。

**Tech Stack:** Python 3，MoviePilot v2 插件，内置 `unittest` 测试（`tests/test_brushflowlowfreq_features.py`）。

---

## 背景

2026-09-09 全量日志分析发现：

- `__check_multi_downloaders()` 每轮调用 `check()` 两次，而 `check()` 末尾每次都会执行归档、统计和保存。日志里完整检查周期约 1082 次，但 `刷流任务统计数据` 和 `自动归档未配置` 各有 2164 条，全部为重复输出。
- `统计` 没有分下载器输出；新增任务日志和上传保护动作日志不包含下载器名，纯日志无法审计大小分流是否正确。
- `__release_upload_protection_for_small_pool()` 会把 `upload_protection_no_upload_streak` 重置为 0。日志中出现了“删种后下载中任务数降到 2，例外立即释放剩余低价值任务”的场景，且清零会让后续无上传价值观察从头累计。

本计划不修改 `log_mode`、`auto_archive_days`、上传保护阈值等配置，只做代码与功能侧优化。

## 文件结构

- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - 新增 `__finalize_check_cycle()`，收敛多下载器收尾。
  - 修改 `check()`、`__check_multi_downloaders()` 和 `__update_and_save_statistic_info()`。
  - 修改新增任务日志、上传保护动作日志和小池子例外释放逻辑。
- Modify: `tests/test_brushflowlowfreq_features.py`
  - 新增或修改多下载器收尾、分下载器统计、下载器上下文日志和小池子计数保留测试。
- Modify: `package.v2.json`
- Modify: `plugins.v2/brushflowlowfreq/README.md`

---

## Task 1: 多下载器检查收尾只执行一次，并保存分下载器统计

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `__check_multi_downloaders`：约 5521-5560
  - `check`：签名 5562，收尾 5796-5805
  - `__update_and_save_statistic_info`：9189-9235
- Modify: `tests/test_brushflowlowfreq_features.py`
  - 多下载器分组测试：8532-8572
  - 新增分下载器统计测试

- [ ] **Step 1: 写失败测试，证明多下载器应只收尾一次**

在 `tests/test_brushflowlowfreq_features.py` 中新增：

```python
def test_multi_downloader_check_finalizes_once(self):
    plugin = self._new_plugin({
        "downloader": "QB-1",
        "multi_downloader_enabled": True,
        "notify": False,
    })
    self._attach_memory_store(plugin, {
        "torrents": {
            "hash1": {"deleted": False, "downloader": "QB-1"},
            "hash2": {"deleted": False, "downloader": "TR-1"},
        },
        "statistic": {},
        "archived": {},
    })
    check_calls = []
    final_calls = []
    plugin.check = lambda **kwargs: check_calls.append(kwargs)
    plugin._BrushFlowLowFreq__finalize_check_cycle = lambda **kwargs: final_calls.append(kwargs)
    plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
    plugin._BrushFlowLowFreq__configured_downloader_names = lambda: ["QB-1", "TR-1"]

    class FakeDownloader:
        def is_inactive(self):
            return False

    class FakeHelper:
        def get_service(self, name):
            return SimpleNamespace(name=name, instance=FakeDownloader())

        def is_downloader(self, name, service=None):
            return name == "qbittorrent"

    plugin.downloader_helper = FakeHelper()
    plugin._BrushFlowLowFreq__check_multi_downloaders()

    self.assertEqual(len(check_calls), 2)
    self.assertTrue(all(call.get("finalize") is False for call in check_calls))
    self.assertEqual(len(final_calls), 1)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_multi_downloader_check_finalizes_once -v`

Expected: FAIL，当前 `check()` 不接受 `finalize` 关键字参数，也没有 `__finalize_check_cycle()`。

- [ ] **Step 3: 新增统一收尾方法**

在 `__check_multi_downloaders()` 前插入：

```python
def __finalize_check_cycle(self, torrent_tasks: Optional[Dict[str, dict]] = None) -> None:
    """单次完整检查（可能是多下载器多轮分组）结束后统一归档并保存统计。"""
    if torrent_tasks is None:
        torrent_tasks = self.get_data("torrents") or {}
    self.__auto_archive_tasks(torrent_tasks=torrent_tasks)
    self.__prune_download_dashboard_history(torrent_tasks=torrent_tasks)
    self.__update_and_save_statistic_info(torrent_tasks)
    self.__log_status("刷流下载任务检查完成")
```

- [ ] **Step 4: 修改 `check()` 支持延迟收尾**

签名改为：

```python
def check(self, downloader_name: str = None, group_hashes: Optional[Set[str]] = None,
          finalize: bool = True):
```

把 5796-5805 替换为：

```python
            if finalize:
                self.__finalize_check_cycle(torrent_tasks=torrent_tasks)
            else:
                self.save_data("torrents", torrent_tasks)
```

- [ ] **Step 5: 修改多下载器外层只在最后收尾一次**

把 `__check_multi_downloaders()` 的分组循环改为：

```python
            checked_any = False
            for downloader_name in check_names:
                torrent_hashes = groups.get(downloader_name, [])
                previous_name = self._active_downloader_name
                self._active_downloader_name = str(downloader_name)
                try:
                    if not self.downloader:
                        continue
                    checked_any = True
                    self.check(
                        downloader_name=str(downloader_name),
                        group_hashes=set(torrent_hashes),
                        finalize=False,
                    )
                finally:
                    self._active_downloader_name = previous_name

            if checked_any:
                self.__finalize_check_cycle()
```

- [ ] **Step 6: 写失败测试，证明统计中保存了分下载器摘要**

```python
def test_per_downloader_statistic_is_persisted(self):
    plugin = self._new_plugin({
        "downloader": "QB-1",
        "multi_downloader_enabled": True,
    })
    store = self._attach_memory_store(plugin, {
        "torrents": {
            "h1": {
                "deleted": False,
                "downloader": "QB-1",
                "uploaded": 10,
                "downloaded": 20,
            },
            "h2": {
                "deleted": False,
                "downloader": "TR-1",
                "uploaded": 30,
                "downloaded": 40,
            },
            "h3": {
                "deleted": True,
                "downloader": "QB-1",
                "uploaded": 5,
                "downloaded": 7,
            },
        },
        "statistic": {},
        "archived": {},
    })

    plugin._BrushFlowLowFreq__update_and_save_statistic_info(store["torrents"])

    by_downloader = store["statistic"]["downloaders"]
    self.assertEqual(by_downloader["QB-1"]["total_count"], 2)
    self.assertEqual(by_downloader["QB-1"]["active_count"], 1)
    self.assertEqual(by_downloader["QB-1"]["deleted"], 1)
    self.assertEqual(by_downloader["TR-1"]["active_count"], 1)
```

- [ ] **Step 7: 运行测试，确认失败**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_per_downloader_statistic_is_persisted -v`

Expected: FAIL，`downloaders` 尚不存在。

- [ ] **Step 8: 在 `__update_and_save_statistic_info()` 中加入分下载器聚合**

初始化部分加入：

```python
        default_name = str(getattr(self._brush_config, "downloader", "") or "未知")
        downloader_stats = {}

        def _bucket(name):
            key = str(name or default_name or "未知")
            bucket = downloader_stats.get(key)
            if bucket is None:
                bucket = {
                    "downloader": key,
                    "total_count": 0,
                    "uploaded": 0,
                    "downloaded": 0,
                    "deleted": 0,
                    "active_count": 0,
                    "unarchived": 0,
                    "active_uploaded": 0,
                    "active_downloaded": 0,
                }
                downloader_stats[key] = bucket
            return bucket
```

把两处统计循环分别加入桶累计：

```python
        for task in combined_tasks.values():
            if task.get("deleted", False):
                total_deleted += 1
            total_downloaded += task.get("downloaded", 0)
            total_uploaded += task.get("uploaded", 0)
            bucket = _bucket(task.get("downloader") or default_name)
            bucket["total_count"] += 1
            bucket["uploaded"] += task.get("uploaded", 0)
            bucket["downloaded"] += task.get("downloaded", 0)
            if task.get("deleted", False):
                bucket["deleted"] += 1

        for task in torrent_tasks.values():
            bucket = _bucket(task.get("downloader") or default_name)
            if not task.get("deleted", False):
                active_uploaded += task.get("uploaded", 0)
                active_downloaded += task.get("downloaded", 0)
                active_count += 1
                bucket["active_count"] += 1
                bucket["active_uploaded"] += task.get("uploaded", 0)
                bucket["active_downloaded"] += task.get("downloaded", 0)
            else:
                total_unarchived += 1
                bucket["unarchived"] += 1
```

在 `statistic_info.update(...)` 后增加：

```python
        statistic_info["downloaders"] = downloader_stats
```

在全局统计日志后增加分下载器日志：

```python
        for downloader_name in sorted(downloader_stats):
            bucket = downloader_stats[downloader_name]
            if not bucket.get("total_count"):
                continue
            self.__log_status(
                f"下载器 {downloader_name} 统计，总任务数：{bucket['total_count']}，"
                f"活跃任务数：{bucket['active_count']}，已删除：{bucket['deleted']}，"
                f"待归档：{bucket['unarchived']}，"
                f"活跃上传量：{StringUtils.str_filesize(bucket['active_uploaded'])}，"
                f"活跃下载量：{StringUtils.str_filesize(bucket['active_downloaded'])}，"
                f"总上传量：{StringUtils.str_filesize(bucket['uploaded'])}，"
                f"总下载量：{StringUtils.str_filesize(bucket['downloaded'])}"
            )
```

- [ ] **Step 9: 运行新增测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_per_downloader_statistic_is_persisted -v`

Expected: PASS。

- [ ] **Step 10: 回归测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: 全部 PASS。若 `test_multi_downloader_check_groups_tasks_by_downloader` 报错，按新 `finalize` 参数调整测试替身。

- [ ] **Step 11: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 多下载器检查统一收尾并增加分下载器统计"
```

---

## Task 2: 新增任务与上传保护动作日志带下载器上下文

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - 新增任务日志：4961-4962
  - `__apply_qb_upload_protection_action`：10511-10592
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试，验证新增任务日志包含下载器**

```python
def test_added_torrent_log_includes_downloader(self):
    plugin = self._new_plugin({"downloader": "QB-1"})
    start_info_count = len(self.module.logger.info_messages)
    siteinfo = SimpleNamespace(name="天空")
    torrent = SimpleNamespace(
        size=6 * 1024 ** 3,
        title="下载器审计种子",
        description="description",
    )

    plugin._BrushFlowLowFreq__log_added_torrent(
        siteinfo=siteinfo,
        torrent=torrent,
        downloader_name="QB-1",
    )

    new_info_logs = self.module.logger.info_messages[start_info_count:]
    self.assertTrue(
        any("下载器 QB-1" in msg and "新增刷流种子下载" in msg for msg in new_info_logs),
        new_info_logs,
    )
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_added_torrent_log_includes_downloader -v`

Expected: FAIL，`__log_added_torrent()` 不存在。

- [ ] **Step 3: 新增任务日志辅助方法并替换原日志**

在类中新增：

```python
def __log_added_torrent(self, siteinfo, torrent, downloader_name=None):
    display_name = (
        downloader_name
        or self._active_downloader_name
        or getattr(self._brush_config, "downloader", "")
        or ""
    )
    logger.info(
        f"站点 {siteinfo.name}，下载器 {display_name}，新增刷流种子下载"
        f"（大小 {self.__bytes_to_gb(torrent.size or 0):.2f} GB）："
        f"{self.__format_title_desc(torrent.title, torrent.description)}"
    )
```

把 4961-4962 的 `logger.info(...)` 替换为：

```python
            self.__log_added_torrent(
                siteinfo=siteinfo,
                torrent=torrent,
                downloader_name=downloader_name,
            )
```

- [ ] **Step 4: 扩展上传保护动作日志测试**

在现有 `test_full_log_mode_keeps_upload_protection_success_log` 中追加断言：

```python
        plugin._active_downloader_name = "QB-1"
        ...
        self.assertTrue(any("下载器 QB-1" in msg for msg in new_info_logs))
```

- [ ] **Step 5: 实现下载器上下文**

在 `__apply_qb_upload_protection_action()` 开头增加：

```python
        downloader_name = self._active_downloader_name or brush_config.downloader or ""
```

将该方法内 10528、10566、10581、10591 的日志文本统一改为以 `下载器 {downloader_name}，站点：{site_name}` 开头。

- [ ] **Step 6: 运行测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_added_torrent_log_includes_downloader tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_full_log_mode_keeps_upload_protection_success_log -v`

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "feat: 日志补充下载器上下文便于审计分流"
```

---

## Task 3: 小池子例外释放保留无上传价值观察计数

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
  - `__release_upload_protection_for_small_pool`：7093-7147
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试**

```python
def test_small_pool_release_preserves_no_upload_streak(self):
    calls = []

    class FakeQbc:
        def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
            calls.append((limit, torrent_hashes))

    plugin = self._new_qb_plugin(
        {
            "upload_protection_enabled": True,
            "upload_protection_skip_when_downloading_le": 1,
        },
        downloader=SimpleNamespace(qbc=FakeQbc(), is_inactive=lambda: False),
    )
    plugin._active_downloader_name = "QB-1"
    brush_config = self.module.BrushConfig({
        "upload_protection_enabled": True,
        "upload_protection_skip_when_downloading_le": 1,
    })
    torrent_task = {
        "title": "仍有观察记录的低价值任务",
        "upload_protection_stage": "strict_limited",
        "upload_protection_pending_action": "strict_limit",
        "upload_protection_low_streak": 12,
        "upload_protection_good_streak": 0,
        "upload_protection_no_upload_streak": 39,
    }

    plugin._BrushFlowLowFreq__release_upload_protection_for_small_pool(
        torrent_hash="hash1",
        torrent_task=torrent_task,
        brush_config=brush_config,
        site_name="天空",
        downloading_count=1,
        skip_threshold=1,
    )

    self.assertEqual([(0, ["hash1"])], calls)
    self.assertEqual("released", torrent_task.get("upload_protection_stage"))
    self.assertEqual(39, torrent_task.get("upload_protection_no_upload_streak"))
    self.assertEqual(0, torrent_task.get("upload_protection_low_streak"))
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_small_pool_release_preserves_no_upload_streak -v`

Expected: FAIL，`no_upload_streak` 当前被重置为 0。

- [ ] **Step 3: 修改小池子释放逻辑**

保留计数，把 7138-7141 改为：

```python
        torrent_task["upload_protection_stage"] = "released"
        torrent_task["upload_protection_low_streak"] = 0
        torrent_task["upload_protection_good_streak"] = 0
        torrent_task["upload_protection_no_upload_streak"] = self.__positive_int(
            torrent_task.get("upload_protection_no_upload_streak"), 0
        )
```

同时把 7099 的原因和 7131-7135 的例行日志补充当前下载器名：

```python
        # 在 __ensure_upload_protection_task_state(torrent_task) 之后插入
        downloader_name = self._active_downloader_name or brush_config.downloader or ""
        reason = (
            f"上传保护：下载器 {downloader_name}，下载中任务数 {downloading_count} "
            f"小于等于例外阈值 {skip_threshold}，跳过限速及删种并放开下载限速"
        )
```

把 7131-7135 的例行日志文本改为以 `下载器 {downloader_name}，上传保护放开限速评估：站点：{site_name}` 开头。

- [ ] **Step 4: 运行测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_small_pool_release_preserves_no_upload_streak -v`

Expected: PASS。

- [ ] **Step 5: 回归测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features -v`

Expected: 全部 PASS。若日志断言因新文本变化失败，同步修正断言文本。

- [ ] **Step 6: Commit**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py
git commit -m "fix: 小池子例外释放不再清空无上传价值观察计数"
```

---

## Task 4: 版本号与更新日志

**Files:**
- Modify: `package.v2.json`
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `plugins.v2/brushflowlowfreq/README.md`

- [ ] **Step 1: 版本升到 4.3.92**

把以下三处 `4.3.91` 改为 `4.3.92`：

- `package.v2.json` 的 `version`
- `package.v2.json` 的 `history.v4.3.92`（新增条目）
- `plugins.v2/brushflowlowfreq/__init__.py` 的 `plugin_version`

- [ ] **Step 2: 更新 README 顶部版本说明**

在 README `v4.3.91` 上方新增：

```markdown
- v4.3.92
  - **检查收尾优化**：多下载器完整检查只归档/统计/保存一次，并输出分下载器统计摘要
  - **审计日志**：新增任务与上传保护动作日志显示下载器，便于核对大小分流
  - **上传保护**：小池子例外释放保留无上传价值观察次数，避免低价值任务反复从头计数
```

- [ ] **Step 3: 运行版本一致性测试**

Run: `python3 -m unittest tests.test_brushflowlowfreq_features.BrushFlowLowFreqFeatureTests.test_plugin_version_matches_package_manifest -v`

Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add package.v2.json plugins.v2/brushflowlowfreq/__init__.py plugins.v2/brushflowlowfreq/README.md
git commit -m "chore: bump version to v4.3.92"
```

---

## 验收标准

- 多下载器模式一个完整检查周期只出现一次 `刷流下载任务检查完成` 和一次全局统计。
- `statistic.downloaders` 能按下载器读取任务、上传、下载、删除和待归档数量。
- 新增任务日志包含下载器与种子大小；上传保护动作和例外释放日志包含下载器。
- 小池子例外释放后 `upload_protection_no_upload_streak` 不再被清零。
- `package.v2.json` 与插件 `plugin_version` 均为 `4.3.92`。
- 全量测试：`python3 -m unittest tests.test_brushflowlowfreq_features -v` 全部通过。
