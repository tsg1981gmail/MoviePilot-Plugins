# DownloaderTaskManager Scheduled Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `DownloaderTaskManager` 升级到 1.1.0，按下载器配置一次性全部开始或暂停时间，只处理未完成的下载任务。

**Architecture:** `runtime.py` 负责时间、键、进度、状态和候选任务过滤；`service.py` 负责计划注册表、到期计划排序、下载器调用和重试结果；`__init__.py` 负责动态配置页、状态页和每 5 分钟一次的 MoviePilot 服务。v1.0.0 的种子列表和手动动作 API 全部移除。

**Tech Stack:** Python 3、MoviePilot v2 `_PluginBase`、`DownloaderHelper`、`zoneinfo`、Vuetify JSON、pytest。

---

### Task 1: 时间、键和任务过滤运行时

**Files:**
- Modify: `plugins.v2/downloadertaskmanager/runtime.py`
- Modify: `tests/test_downloadertaskmanager.py`

**Skill:** `@test-driven-development`

- [ ] **Step 1: 写失败测试**

覆盖：

```python
def test_downloader_key_includes_type_and_name():
    assert downloader_key("qbittorrent", "QB") != downloader_key("transmission", "QB")
    assert downloader_key("qbittorrent", "QB") == "c70ff5f613c1"
    assert schedule_field("c70ff5f613c1", "start") == "schedule_c70ff5f613c1_start_at"
    assert schedule_field("c70ff5f613c1", "stop") == "schedule_c70ff5f613c1_pause_at"


def test_parse_schedule_time_accepts_two_formats():
    timezone = ZoneInfo("Asia/Shanghai")
    first = parse_schedule_time("2026-10-27T02:00", timezone)
    second = parse_schedule_time("2026-10-27 02:00", timezone)
    assert first == second
    assert first.utcoffset().total_seconds() == 8 * 3600
```

同一测试文件还要覆盖：

- 非法时间为 `None`。
- qBittorrent 进度 `0.999` 归一化为 `99.9`，`1.0` 归一化为 `100.0`。
- Transmission 进度 `99.9`、`100.0` 保持不变。
- 进度小于 0 限制为 0，大于 100 限制为 100，非数值为 0。
- 开始只选择 `paused` 且进度小于 100。
- 暂停只选择 `downloading`、`checking`、`queued` 且进度小于 100。
- `uploading`、`error`、`unknown` 和进度 100 永不选择。
- 七种归一化状态的完整映射。

- [ ] **Step 2: 运行失败测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: FAIL，缺少新函数或旧行为不匹配。

- [ ] **Step 3: 实现运行时函数**

`runtime.py` 必须包含：

```python
def downloader_key(downloader_type: str, downloader_name: str) -> str:
    """生成下载器计划稳定键。"""

def schedule_field(key: str, action: str) -> str:
    """返回计划配置字段名。"""

def parse_schedule_time(value: str, timezone: ZoneInfo) -> Optional[datetime]:
    """解析本地一次性计划时间。"""

def normalize_progress(value: Any, downloader_type: str) -> float:
    """将下载器进度归一化为 0 到 100。"""

def normalize_status(value: Any, downloader_type: str) -> str:
    """将下载器状态归一化为计划支持的状态。"""

def normalize_torrent(source: Any, downloader_type: str) -> Optional[dict]:
    """将下载器任务转换为计划过滤结构。"""

def task_eligible(task: dict, action: str) -> bool:
    """判断任务是否允许被计划动作处理。"""
```

状态映射严格按规格。`normalize_torrent` 输出：

```python
{
    "hash": "...",
    "status": "paused",
    "progress_percent": 50.0,
}
```

`task_eligible`：

```python
if action == "start":
    return status == "paused" and progress < 100
if action == "stop":
    return status in {"downloading", "checking", "queued"} and progress < 100
return False
```

动作标识统一为 `start` 和 `stop`。`schedule_field()` 仅在生成暂停字段名时把
`stop` 映射为 `pause_at`。

- [ ] **Step 4: 运行测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: 当前运行时测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add plugins.v2/downloadertaskmanager/runtime.py tests/test_downloadertaskmanager.py
git commit -m "feat: add downloader schedule runtime"
```

---

### Task 2: 计划注册表、到期排序和执行服务

**Files:**
- Modify: `plugins.v2/downloadertaskmanager/service.py`
- Modify: `tests/test_downloadertaskmanager.py`

**Skill:** `@test-driven-development`

- [ ] **Step 1: 写失败测试**

测试 `DownloaderScheduleService`：

- `refresh_registry()` 保存 `key -> name/type`，且不删除旧快照。
- 读取 start/pause 字段，产生正确动作和计划时间。
- 只返回 `scheduled_at <= now` 的计划。
- 按 `(scheduled_at, key, action)` 确定性排序。
- 同一下载器开始和暂停时间相同时两个计划均标记配置错误。
- 重复类型/名称组合标记配置错误。
- 失败计划不阻止后续计划。
- 重试继续尝试失败计划。
- 成功和“0 个任务”都清空对应字段。
- `schedule_results[key][action]` 独立保存。
- `scheduled_at` 不匹配当前配置时间的旧结果不参与状态。
- `run_due()` 使用 `threading.RLock`，重叠调用不能同时进入执行区。

测试替身接口固定为：

```text
helper.get_services() -> Mapping[name, ServiceInfo]
ServiceInfo.name: str
ServiceInfo.type: "qbittorrent" | "transmission"
ServiceInfo.instance.get_torrents() -> (list[task], bool)
ServiceInfo.instance.is_inactive() -> bool
ServiceInfo.instance.start_torrents(ids=list[str]) -> bool
ServiceInfo.instance.stop_torrents(ids=list[str]) -> bool
```

qBittorrent 任务按 Mapping 读取 `hash`、`state`、`progress`；Transmission
任务按属性读取 `hashString`、`status`、`progress`。

测试用 `FakeInstance` 提供：

```python
def get_torrents(self):
    """返回任务列表和错误标记。"""

def start_torrents(self, ids):
    """记录开始哈希。"""

def stop_torrents(self, ids):
    """记录暂停哈希。"""
```

- [ ] **Step 2: 运行失败测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: FAIL，旧手动动作服务不满足计划接口。

- [ ] **Step 3: 实现计划服务**

`service.py` 提供：

```python
class DownloaderScheduleService:
    """管理下载器一次性计划并执行到期动作。"""

    def __init__(
        self,
        helper,
        config,
        registry,
        results,
        now_fn,
        timezone,
        persist_config,
        save_registry,
        save_results,
    ):
        """保存运行依赖和持久化回调。"""

    def refresh_registry(self, services=None) -> dict:
        """刷新当前下载器名称快照。"""

    def list_plans(self) -> list[dict]:
        """列出合法、冲突和遗留计划。"""

    def due_plans(self, now=None) -> list[dict]:
        """返回到期且合法的计划。"""

    def execute_plan(self, plan) -> dict:
        """执行单个计划并返回结构化结果。"""

    def run_due(self, now=None) -> list[dict]:
        """依次执行所有到期计划。"""
```

构造函数创建 `threading.RLock()`；`run_due()` 的整个扫描和执行过程持有该锁。

执行约束：

- 下载器通过名称解析；类型必须与快照一致。
- 类型不一致视为下载器不存在并保留计划。
- `get_torrents()` 错误、异常、动作 `False` 和动作异常均保留计划。
- 成功或没有候选任务都清空配置字段并持久化。
- 失败不影响本轮其他计划。
- 未配置、已禁用、类型不匹配或离线下载器保留计划并返回失败结果。
- 结果 `affected` 只在动作返回 `True` 时使用候选哈希数。
- 不保存种子名称或内容。

- [ ] **Step 4: 运行测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: 计划服务测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add plugins.v2/downloadertaskmanager/service.py tests/test_downloadertaskmanager.py
git commit -m "feat: schedule downloader bulk actions"
```

---

### Task 3: 插件配置页、状态页和定时服务

**Files:**
- Modify: `plugins.v2/downloadertaskmanager/__init__.py`
- Modify: `tests/test_downloadertaskmanager.py`

- [ ] **Step 1: 写失败测试**

覆盖：

- `plugin_version == "1.1.0"`。
- 配置页为每个受支持下载器生成开始和暂停 `VTextField`，类型为 `datetime-local`。
- 未启用时页面显示提示。
- 状态页不出现任务表格或种子名称。
- 每个动作独立显示计划时间、状态和最近结果。
- 状态页逐项覆盖无计划、已计划、待执行、等待重试、已执行和无效时间。
- 配置错误优先级高于普通计划状态。
- `get_api()` 返回 `[]`。
- `get_command()` 返回 `[]`。
- `get_service()` 仅在启用时返回一个 `interval` 300 秒服务。
- `check_schedules()` 调用计划服务。
- `init_plugin()` 删除旧配置 `allow_bulk_actions` 并忽略 `last_action_result`。

- [ ] **Step 2: 运行失败测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: FAIL，插件仍暴露 v1.0.0 配置、数据页或 API。

- [ ] **Step 3: 重写插件入口**

插件元数据：

```python
plugin_version = "1.1.0"
```

配置页：

- `enabled` 开关。
- 每个下载器两组 `VTextField`。
- 字段值来自 `schedule_<key>_start_at`、`schedule_<key>_pause_at`。

状态页：

- 不展示种子或任务表格。
- 显示下载器、类型、两类计划、状态和最近结果。
- 配置错误使用红色 `VAlert`。

生命周期：

```python
def init_plugin(self, config=None):
    """初始化计划服务并迁移旧配置。"""

def get_service(self):
    """注册每 5 分钟运行的计划检查服务。"""

def check_schedules(self):
    """执行所有到期计划。"""

def get_api(self):
    """不注册手动任务 API。"""
    return []

@staticmethod
def get_command():
    """不注册手动远程命令。"""
    return []
```

`update_config()` 和 `save_data()` 作为计划服务持久化回调。注册表和结果使用：

```text
schedule_registry
schedule_results
```

- [ ] **Step 4: 运行插件测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: PASS。

- [ ] **Step 5: 语法检查**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -c \
  'from pathlib import Path; files=[Path("plugins.v2/downloadertaskmanager/__init__.py"),Path("plugins.v2/downloadertaskmanager/runtime.py"),Path("plugins.v2/downloadertaskmanager/service.py")]; [compile(p.read_text(encoding="utf-8"),str(p),"exec") for p in files]'
```

Expected: exit code 0。

- [ ] **Step 6: 提交**

```bash
git add plugins.v2/downloadertaskmanager/__init__.py tests/test_downloadertaskmanager.py
git commit -m "feat: add one-time downloader schedules"
```

---

### Task 4: 1.1.0 元数据与文档

**Files:**
- Modify: `package.v2.json`
- Modify: `plugins.v2/downloadertaskmanager/README.md`
- Modify: `tests/test_downloadertaskmanager.py`

- [ ] **Step 1: 写失败测试**

验证：

- 包索引版本为 `1.1.0`。
- 包版本等于类版本。
- `history["v1.1.0"]` 描述一次性定时调度。
- `BrushFlowLowFreq` 条目仍存在。
- README 说明每个下载器独立时间、只操作未完成任务、5 分钟重试和无种子列表。

- [ ] **Step 2: 运行失败测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: FAIL，包索引仍为 `1.0.0`。

- [ ] **Step 3: 更新元数据和 README**

包索引：

```json
{
  "version": "1.1.0",
  "history": {
    "v1.1.0": "改为按下载器一次性定时全部开始或暂停，仅处理未完成下载任务，失败每5分钟重试"
  }
}
```

README 明确：

- 不展示种子。
- 每个下载器可设开始/暂停时间。
- 已做种、100%、错误和未知任务不操作。
- 失败保留计划并重试。

- [ ] **Step 4: 运行测试**

```bash
python3 -m pytest -s -q -p no:cacheprovider tests/test_downloadertaskmanager.py
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add package.v2.json plugins.v2/downloadertaskmanager/README.md tests/test_downloadertaskmanager.py
git commit -m "docs: release downloader schedules 1.1.0"
```

---

### Task 5: 回归验证和发布 1.1.0

**Files:**
- Modify: local code only if verification exposes a defect
- Remote update: plugin files, `package.v2.json`, tests, spec and plan

**Skill:** `@verification-before-completion`

- [ ] **Step 1: 运行完整回归**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -s -q -p no:cacheprovider \
  tests/test_downloadertaskmanager.py \
  tests/test_brushflowlowfreq_features.py
```

Expected: 全部 PASS。

- [ ] **Step 2: 校验语法和 JSON**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -c \
  'from pathlib import Path; files=[Path("plugins.v2/downloadertaskmanager/__init__.py"),Path("plugins.v2/downloadertaskmanager/runtime.py"),Path("plugins.v2/downloadertaskmanager/service.py")]; [compile(p.read_text(encoding="utf-8"),str(p),"exec") for p in files]; print("compile OK")'
python3 -m json.tool package.v2.json >/dev/null
git diff --check
```

Expected: 三条命令均成功。

- [ ] **Step 3: 预览 GitHub 差异**

先确认发布前置条件：

```bash
test -f /tmp/publish_plugin.py
gh auth status
```

Expected: 发布脚本存在，GitHub CLI 已登录。若脚本不存在，从
`jxxghp/MoviePilot:v2` 的发布技能目录重新下载后再继续。

```bash
GH_TOKEN=$(gh auth token) python3 /tmp/publish_plugin.py preview \
  --repo tsg1981gmail/MoviePilot-Plugins \
  --plugin-id DownloaderTaskManager \
  --local-repo . \
  --package-version v2 \
  --branch main
```

Expected: 只更新 `plugins.v2/downloadertaskmanager/` 和
`package.v2.json`，无冲突、无删除。

- [ ] **Step 4: 发布**

```bash
GH_TOKEN=$(gh auth token) python3 /tmp/publish_plugin.py push \
  --repo tsg1981gmail/MoviePilot-Plugins \
  --plugin-id DownloaderTaskManager \
  --local-repo . \
  --package-version v2 \
  --branch main \
  --message "Publish DownloaderTaskManager v1.1.0"
```

Expected: `success: true`，远端版本 `1.1.0`。

- [ ] **Step 5: 同步测试和文档**

通过 GitHub Contents API 更新：

- `tests/test_downloadertaskmanager.py`
- `docs/superpowers/specs/2026-10-26-downloader-task-manager-design.md`
- `docs/superpowers/plans/2026-10-26-downloader-task-manager.md`

