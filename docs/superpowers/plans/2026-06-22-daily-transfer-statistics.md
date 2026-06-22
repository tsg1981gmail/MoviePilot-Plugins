# 每日上传下载统计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `brushflowlowfreq` 插件增加只统计插件托管任务的每日上传/下载增量，并在插件数据页展示今日和历史记录。

**Architecture:** 在现有 `check()` 流程中，基于托管任务累计 `uploaded` / `downloaded` 做差分统计，并保存到新的 `daily_statistic` 数据键。页面仍使用现有 `get_page()` Vuetify JSON 结构渲染，不新增 API。

**Tech Stack:** Python、MoviePilot 插件持久化 `get_data` / `save_data`、Vuetify 组件 JSON、`unittest`。

---

## 文件结构

- 修改 `plugins.v2/brushflowlowfreq/__init__.py`
  - 新增每日统计读取、日期生成、差分累计和页面元素 helper。
  - 在 `check()` 状态更新后接入每日统计。
  - 在 `get_page()` 增加每日统计区域。
  - 在 `__clear_tasks()` 清空 `daily_statistic`。
- 修改 `tests/test_brushflowlowfreq_features.py`
  - 增加每日统计单元测试。
  - 测试通过 monkeypatch `get_data` / `save_data` 使用内存存储，不依赖真实 MoviePilot。
- 创建 `docs/superpowers/plans/2026-06-22-daily-transfer-statistics.md`
  - 记录本实施计划。

---

### Task 1: 每日统计核心逻辑

**Files:**
- Modify: `tests/test_brushflowlowfreq_features.py`
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`

- [ ] **Step 1: 写失败测试：首次统计只建基线**

在 `BrushFlowLowFreqFeatureTests` 中增加内存存储 helper，并新增测试：

```python
def test_daily_transfer_statistics_first_run_only_initializes_baseline(self):
    plugin = self._new_plugin({})
    store = {}
    plugin.get_data = lambda key, *args: store.get(key)
    plugin.save_data = lambda key, value, *args: store.__setitem__(key, value)
    tasks = {
        "hash1": {
            "uploaded": 1000,
            "downloaded": 2000,
        }
    }

    plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
        torrent_tasks=tasks,
        now=datetime(2026, 6, 22, 10, 0, 0),
    )

    self.assertEqual(store["daily_statistic"], {})
    self.assertEqual(tasks["hash1"]["daily_stat_last_date"], "2026-06-22")
    self.assertEqual(tasks["hash1"]["daily_stat_last_uploaded"], 1000)
    self.assertEqual(tasks["hash1"]["daily_stat_last_downloaded"], 2000)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py::BrushFlowLowFreqFeatureTests::test_daily_transfer_statistics_first_run_only_initializes_baseline -q`

Expected: FAIL，原因是 `__update_daily_transfer_statistics` 尚不存在。

- [ ] **Step 3: 实现最小 helper**

在 `plugins.v2/brushflowlowfreq/__init__.py` 统计区域附近新增：

```python
def __get_daily_stat_date(self, now: Optional[datetime] = None) -> str:
    if now:
        return now.strftime("%Y-%m-%d")
    try:
        return datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def __get_daily_statistic_info(self) -> Dict[str, dict]:
    statistic = self.get_data("daily_statistic") or {}
    return statistic if isinstance(statistic, dict) else {}

def __update_daily_transfer_statistics(self, torrent_tasks: Dict[str, dict], now: Optional[datetime] = None) -> None:
    # 最小实现：缺基线时只补基线并保存空 daily_statistic。
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py::BrushFlowLowFreqFeatureTests::test_daily_transfer_statistics_first_run_only_initializes_baseline -q`

Expected: PASS。

- [ ] **Step 5: 写失败测试：同日增量累计**

新增测试：首次调用建立基线，第二次同日 `uploaded/downloaded` 增加后，`daily_statistic["2026-06-22"]` 分别累计上传和下载增量。

- [ ] **Step 6: 运行测试确认失败**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py::BrushFlowLowFreqFeatureTests::test_daily_transfer_statistics_accumulates_same_day_deltas -q`

Expected: FAIL，原因是增量累计未实现。

- [ ] **Step 7: 实现同日差分累计**

在 `__update_daily_transfer_statistics` 中：

- 跳过缺少数字累计值的任务。
- 计算当前日期。
- 获取/创建当天记录。
- 正增量累加到当天记录。
- 更新 `updated_at`。
- 保存 `daily_statistic`。

- [ ] **Step 8: 运行两个核心测试**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py -q`

Expected: 当前新增测试通过；如已有测试失败，修复回归。

---

### Task 2: 边界行为

**Files:**
- Modify: `tests/test_brushflowlowfreq_features.py`
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`

- [ ] **Step 1: 写失败测试：多任务汇总**

两个任务同日都有正增量，断言同一日期记录的上传/下载为两者之和，`task_count` 为 2。

- [ ] **Step 2: 写失败测试：负增量只刷新基线**

任务当前累计值小于基线时，断言每日统计不减少，任务基线刷新为当前值。

- [ ] **Step 3: 写失败测试：跨天新建日期记录**

任务在 `2026-06-22` 建基线，`2026-06-23` 有新增累计值，断言新增量进入 `2026-06-23`，不会导入全部历史累计量。

- [ ] **Step 4: 运行边界测试确认失败**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py -q`

Expected: 新增边界测试失败。

- [ ] **Step 5: 完善统计逻辑**

更新 `__update_daily_transfer_statistics`：

- 处理多任务。
- 负增量跳过统计并刷新基线。
- 跨天用旧基线继续做差，把检查间增量计入当前日期。
- 当前运行内用集合去重计算 `task_count`，再与当天已有 `task_count` 做合理合并。

- [ ] **Step 6: 运行完整测试文件**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py -q`

Expected: PASS。

---

### Task 3: 清除统计和页面展示

**Files:**
- Modify: `tests/test_brushflowlowfreq_features.py`
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`

- [ ] **Step 1: 写失败测试：清除每日统计**

用内存 store 预置 `daily_statistic`，调用 `__clear_tasks()`，断言 `daily_statistic` 被保存为空字典。

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py::BrushFlowLowFreqFeatureTests::test_clear_tasks_clears_daily_statistic -q`

Expected: FAIL。

- [ ] **Step 3: 更新 `__clear_tasks()`**

在清除现有数据时增加：

```python
self.save_data("daily_statistic", {})
```

- [ ] **Step 4: 写失败测试：页面包含每日统计区域**

预置一个 torrent 和一条 `daily_statistic`，调用 `get_page()`，把返回结构转成 JSON 字符串，断言包含 `每日流量统计`、日期、上传/下载文本。

- [ ] **Step 5: 写失败测试：无每日统计时显示空状态**

预置一个 torrent 但不预置 `daily_statistic`，调用 `get_page()`，断言包含 `暂无每日流量统计`。

- [ ] **Step 6: 实现页面元素 helper**

新增 `__get_daily_transfer_elements()`，返回一个 `VCol` 包含：

- 标题 `每日流量统计`
- 今日上传 / 今日下载摘要
- 最近 30 条历史表
- 空状态

在 `get_page()` 的 `VRow` content 中，把每日统计元素放在种子明细表之前。

- [ ] **Step 7: 运行页面测试**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py -q`

Expected: PASS。

---

### Task 4: 接入 check 流程和最终验证

**Files:**
- Modify: `plugins.v2/brushflowlowfreq/__init__.py`
- Modify: `tests/test_brushflowlowfreq_features.py`

- [ ] **Step 1: 写失败测试或代码搜索确认接入点**

确认 `check()` 在 `__update_torrent_tasks_state(...)` 之后调用 `__update_daily_transfer_statistics(torrent_tasks)`。

- [ ] **Step 2: 接入 `check()`**

在 `check()` 中 `self.__update_torrent_tasks_state(torrents=check_torrents, torrent_tasks=torrent_tasks)` 后增加每日统计更新。

- [ ] **Step 3: 运行完整测试**

Run: `python3 -m pytest tests/test_brushflowlowfreq_features.py -q`

Expected: PASS。

- [ ] **Step 4: 查看 diff**

Run: `git diff -- plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py docs/superpowers/plans/2026-06-22-daily-transfer-statistics.md`

Expected: 只包含本功能相关改动。

- [ ] **Step 5: 最终提交**

```bash
git add plugins.v2/brushflowlowfreq/__init__.py tests/test_brushflowlowfreq_features.py docs/superpowers/plans/2026-06-22-daily-transfer-statistics.md
git commit -m "feat: add daily transfer statistics"
```
