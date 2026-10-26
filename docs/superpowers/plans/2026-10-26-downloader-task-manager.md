# DownloaderTaskManager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 MoviePilot v2 下载器任务管理插件，支持 qBittorrent 和 Transmission 单任务及当前下载器全部任务的开始、暂停。

**Architecture:** 将纯数据适配、下载器动作编排和 MoviePilot 插件入口分成三个模块。`runtime.py` 负责无宿主依赖的状态和字段归一化；`service.py` 通过注入的 `DownloaderHelper` 发现下载器并执行动作；`__init__.py` 只负责配置、Vuetify JSON 页面和 Bear API 注册。

**Tech Stack:** Python 3、MoviePilot v2 `_PluginBase`、`DownloaderHelper`、Vuetify JSON、FastAPI `Body`、unittest/pytest。

---

### Task 1: 任务字段与状态归一化

**Files:**
- Create: `plugins.v2/downloadertaskmanager/runtime.py`
- Create: `tests/test_downloadertaskmanager.py`
- Test: `tests/test_downloadertaskmanager.py`

**Skill:** `@test-driven-development`

- [ ] **Step 1: 写失败测试**

在 `tests/test_downloadertaskmanager.py` 中加入以下测试：

```python
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins.v2"))
from downloadertaskmanager.runtime import normalize_torrent, normalize_status


class RuntimeTests(unittest.TestCase):
    def test_normalize_qbittorrent_torrent(self):
        torrent = {
            "hash": "ABCDEF",
            "name": "qb-task",
            "state": "pausedDL",
            "progress": 0.5,
            "size": 1024,
            "dlspeed": 100,
            "upspeed": 20,
            "category": "电影",
            "added_on": 100,
        }

        result = normalize_torrent(torrent, "qbittorrent")

        self.assertEqual("abcdef", result["hash"])
        self.assertEqual("paused", result["status"])
        self.assertTrue(result["paused"])
        self.assertEqual(50.0, result["progress"])

    def test_normalize_transmission_torrent(self):
        torrent = type("Torrent", (), {
            "hashString": "FEDCBA",
            "name": "tr-task",
            "status": "downloading",
            "progress": 25.0,
            "total_size": 2048,
            "rateDownload": 200,
            "rateUpload": 30,
            "download_dir": "/downloads",
            "labels": ["刷流", "电影"],
            "date_added": None,
        })()

        result = normalize_torrent(torrent, "transmission")

        self.assertEqual("fedcba", result["hash"])
        self.assertEqual("downloading", result["status"])
        self.assertFalse(result["paused"])
        self.assertEqual(25.0, result["progress"])
        self.assertEqual("刷流,电影", result["category"])

    def test_unknown_status_is_not_guessed(self):
        self.assertEqual("unknown", normalize_status("mystery", "qbittorrent"))
        self.assertEqual("unknown", normalize_status("mystery", "transmission"))

    def test_error_and_state_text_are_normalized(self):
        self.assertEqual("error", normalize_status("missingFiles", "qbittorrent"))
        self.assertEqual("error", normalize_status("error", "transmission"))

        result = normalize_torrent({
            "hash": "abc",
            "name": "errored",
            "state": "missingFiles",
            "progress": 0,
        }, "qbittorrent")

        self.assertEqual("error", result["status"])
        self.assertEqual("错误", result["state_text"])
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: FAIL，提示 `downloadertaskmanager.runtime` 不存在。

- [ ] **Step 3: 实现最小运行时模块**

`runtime.py` 必须包含：

```python
SUPPORTED_DOWNLOADERS = {"qbittorrent", "transmission"}
PAUSED_STATES = {"paused", "pauseddl", "pausedup", "stopped", "stoppeddl", "stoppedup"}
DOWNLOADING_STATES = {
    "downloading", "download_pending", "forceddl", "forcedmetadl",
    "metadl", "stalleddl", "queueddl",
}
UPLOADING_STATES = {"uploading", "seeding", "seed_pending", "forcedup", "stalledup", "queuedup"}
CHECKING_STATES = {
    "checking", "checkingdl", "checkingup", "checkingresumedata",
    "check_pending",
}
QUEUED_STATES = {"queued", "download_wait", "seed_wait"}
ERROR_STATES = {"error", "missingfiles"}
STATE_TEXT = {
    "paused": "已暂停",
    "downloading": "下载中",
    "uploading": "做种中",
    "checking": "校验中",
    "queued": "排队中",
    "error": "错误",
    "unknown": "未知",
}

def get_value(source, *keys, default=None):
    """从字典或对象读取第一个存在的字段。"""

def normalize_status(value, downloader_type):
    """将下载器原始状态转换为统一状态。"""

def normalize_torrent(source, downloader_type):
    """将 qBittorrent/Transmission 任务转换为统一字典。"""
```

实现细节：

- `get_value` 先用 `isinstance(source, dict)` 走 `source.get`，否则用 `getattr`。
- qBittorrent 哈希读取 `hash`，Transmission 读取 `hashString`。
- qBittorrent 进度乘以 100；Transmission 保持 0 到 100。
- qBittorrent 分类读取 `category`；Transmission 优先 `labels`，其次 `download_dir`。
- 合法哈希去掉首尾空白并转小写。
- 没有合法哈希的任务返回 `None`。
- `added_at` 可以是数值、`datetime` 或 `None`，统一转换为 Unix 时间戳或 `None`。
- `state_text` 必须从 `STATE_TEXT` 取值，不允许在页面层重复映射。
- qBittorrent 的 `error`、`missingFiles` 和 Transmission 的 `error` 必须映射为
  `error`；无法识别的状态才映射为 `unknown`。
- 状态判断顺序固定为：暂停、校验、错误、下载、做种、排队、未知。
- “合法哈希”定义为去除首尾空白后仍非空、再转为小写的字符串；不校验固定
  长度，测试中的短哈希同样有效。

- [ ] **Step 4: 再次运行测试**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add plugins.v2/downloadertaskmanager/runtime.py tests/test_downloadertaskmanager.py
git commit -m "feat: normalize downloader task fields"
```

---

### Task 2: 下载器发现与动作执行

**Files:**
- Create: `plugins.v2/downloadertaskmanager/service.py`
- Modify: `tests/test_downloadertaskmanager.py`

**Skill:** `@test-driven-development`

- [ ] **Step 1: 写失败测试**

增加 qBittorrent/Transmission 动作测试：

```python
class FakeInstance:
    def __init__(self, torrents=None, inactive=False):
        self.torrents = torrents or []
        self.inactive = inactive
        self.started = []
        self.stopped = []

    def is_inactive(self):
        return self.inactive

    def get_torrents(self):
        return self.torrents, False

    def start_torrents(self, ids):
        self.started.append(list(ids))
        return True

    def stop_torrents(self, ids):
        self.stopped.append(list(ids))
        return True


class FakeHelper:
    def __init__(self, services):
        self.services = services

    def get_services(self):
        return self.services

    def get_service(self, name):
        return self.services.get(name)
```

测试必须覆盖：

- 单任务开始调用 `start_torrents(["hash"])`。
- 单任务暂停调用 `stop_torrents(["hash"])`。
- `scope=all` 读取全部任务后调用动作方法。
- 全量开关关闭时拒绝 `scope=all`。
- 空哈希、非法 scope/action、未知下载器、未连接下载器均返回 `success=false`。
- `scope=all` 但下载器没有任务时返回 `success=false`、`affected=0`。
- `get_torrents()` 返回错误标记或抛出异常时，`list_views()` 返回
  `available=false` 和中文 `error`，不能中断其他下载器。
- `scope=all` 时 `get_torrents()` 返回错误标记或抛出异常也返回
  `success=false`、`affected=0`。
- 未连接或类型不受支持的下载器也必须出现在 `list_views()` 结果中，返回
  `available=false`、中文 `error` 和空任务列表。
- 动作方法返回 `False` 时返回失败结果。
- 动作方法抛出异常时同样返回 `success=false`、`affected=0` 和中文错误，
  不得让异常穿透到页面。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: FAIL，提示 `downloadertaskmanager.service` 不存在。

- [ ] **Step 3: 实现服务层**

`service.py` 定义：

```python
class DownloaderTaskService:
    """封装下载器任务查询和开始暂停操作。"""

    def __init__(self, helper, allow_bulk_actions=False):
        """保存下载器帮助类与全量操作开关。"""

    def list_views(self):
        """返回所有已启用下载器的任务视图。"""

    def execute(self, payload):
        """校验动作请求并执行单任务或当前下载器全量动作。"""
```

`list_views()` 返回：

```python
{
    "name": "下载器名称",
    "type": "qbittorrent",
    "available": True,
    "error": "",
    "tasks": [...],
}
```

`execute()` 返回：

```python
{
    "success": True,
    "message": "已开始 3 个任务",
    "affected": 3,
}
```

实现约束：

- 下载器类型从 `service.type` 读取，再回退到 `service.config.type`。
- 只接受 `SUPPORTED_DOWNLOADERS`。
- 使用 `service.instance.is_inactive()` 判断连接状态。
- 类型不受支持或实例未连接时仍保留下载器视图，但设置
  `available=false` 和中文 `error`，不调用任务动作。
- `get_torrents()` 返回值按 `(torrents, error)` 解析；异常也在 `list_views()`
  内捕获，并只影响当前下载器。
- `scope=task` 使用请求中的哈希，不重新查询。
- `scope=all` 重新调用 `get_torrents()`，从每个任务归一化哈希。
- 哈希先去重、去空白、转小写。
- `normalize_torrent()` 返回 `None` 的任务必须在构建列表时过滤。
- 动作前的最终哈希列表为空时返回 `success=false`、`affected=0` 和明确中文提示。
- 捕获 `start_torrents()` / `stop_torrents()` 异常并返回失败结果。
- 所有预期业务错误返回 `success=false`，不抛异常给页面。

- [ ] **Step 4: 运行服务层测试**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add plugins.v2/downloadertaskmanager/service.py tests/test_downloadertaskmanager.py
git commit -m "feat: add downloader task action service"
```

---

### Task 3: MoviePilot 插件配置、页面和 API

**Files:**
- Create: `plugins.v2/downloadertaskmanager/__init__.py`
- Modify: `tests/test_downloadertaskmanager.py`

- [ ] **Step 1: 写插件契约失败测试**

在测试文件安装最小 MoviePilot 桩后导入插件，验证：

- `plugin_version == "1.0.0"`。
- `get_state()` 跟随 `enabled`。
- `get_form()` 默认包含 `enabled=False`、`allow_bulk_actions=False`。
- 未启用时页面返回启用提示。
- 页面按下载器分组。
- 任务按钮包含 `events.click`。
- 单任务事件参数为 `hashes`。
- 七种归一化状态按固定映射显示“开始”“暂停”或无按钮。
- 全量按钮只在 `allow_bulk_actions=True` 时出现。
- `get_api()` 返回 `/action`、`POST`、`auth="bear"`。
- 调用 `action(payload)` 后保存最近动作结果。
- 最近动作结果写入 `save_data("last_action_result", result)`，页面通过
  `get_data("last_action_result")` 读取。
- 插件未启用时，`action(payload)` 直接返回 `success=false`，不访问下载器。

页面事件断言示例：

```python
event = find_event(page, "single-start")
self.assertEqual("plugin/DownloaderTaskManager/action", event["api"])
self.assertEqual("POST", event["method"])
self.assertEqual(["abcdef"], event["params"]["hashes"])
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: FAIL，提示 `downloadertaskmanager` 没有插件类。

- [ ] **Step 3: 实现插件入口**

实现元数据：

```python
class DownloaderTaskManager(_PluginBase):
    """MoviePilot 下载器任务管理插件。"""

    plugin_name = "下载器任务管理"
    plugin_desc = "管理已启用下载器的单个任务和当前下载器全部任务的开始与暂停。"
    plugin_icon = "Qbittorrent_A.png"
    plugin_version = "1.0.0"
    plugin_author = "tsg1981gmail"
    author_url = "https://github.com/tsg1981gmail"
    plugin_config_prefix = "downloadertaskmanager_"
    plugin_order = 50
    auth_level = 1
```

生命周期：

```python
def init_plugin(self, config=None):
    """读取配置并初始化下载器任务服务。"""

def get_state(self):
    """返回插件启用状态。"""

def get_command():
    """不注册远程命令。"""

def get_api(self):
    """注册 Bear 鉴权的任务动作接口。"""

def get_form(self):
    """返回启用与全量操作配置表单。"""

def get_page(self):
    """返回按下载器分组的任务管理页面。"""

def action(self, payload):
    """执行任务开始或暂停并保存最近动作结果。"""

def stop_service(self):
    """插件没有后台服务，无需清理资源。"""
```

`action()` 首先检查 `self._enabled`。未启用时返回
`{"success": False, "message": "插件未启用", "affected": 0}`，并保存该结果，
不得实例化或调用下载器。

`action()` 对成功和失败结果统一调用：

```python
self.save_data("last_action_result", result)
```

`get_page()` 每次调用 `self.get_data("last_action_result")` 读取结果，不使用
仅在内存中保存的结果字段。

API 注册：

```python
{
    "path": "/action",
    "endpoint": self.action,
    "methods": ["POST"],
    "auth": "bear",
    "summary": "开始或暂停下载器任务",
    "description": "支持单个任务和当前下载器的全部任务。",
}
```

`get_page()` 使用相对路径：

```python
API_PATH = f"plugin/{self.__class__.__name__}/action"
```

页面结构：

- `VAlert` 显示最近动作结果。
- 每个下载器一个 `VCard`。
- 下载器头部显示名称、类型、任务数。
- 开启全量操作时显示“全部开始”“全部暂停”按钮。
- 任务表头为“名称、状态、进度、下载速度、上传速度、分类/标签、操作”。
- 每个任务只显示当前状态对应的“开始”或“暂停”按钮。
- 失败下载器在卡片内显示红色 `VAlert`。

任务按钮映射固定为：

- `paused`、`error`：开始。
- `downloading`、`uploading`、`checking`、`queued`：暂停。
- `unknown`：不显示单任务动作按钮。

UI 辅助函数必须全部带中文 docstring：

```python
def _build_button(self, text, action, downloader, hashes=None, scope="task"):
    """构建带插件 API 点击事件的 Vuetify 按钮。"""

def _build_downloader_card(self, view):
    """构建单个下载器任务卡片。"""

def _build_task_row(self, downloader, task):
    """构建单个任务表格行。"""
```

- [ ] **Step 4: 运行插件测试**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: PASS。

- [ ] **Step 5: 语法检查**

Run:

```bash
python3 -m py_compile \
  plugins.v2/downloadertaskmanager/runtime.py \
  plugins.v2/downloadertaskmanager/service.py \
  plugins.v2/downloadertaskmanager/__init__.py
```

Expected: exit code 0。

- [ ] **Step 6: 提交**

```bash
git add plugins.v2/downloadertaskmanager/__init__.py tests/test_downloadertaskmanager.py
git commit -m "feat: add downloader task manager plugin"
```

---

### Task 4: 包元数据与使用文档

**Files:**
- Modify: `package.v2.json`
- Create: `plugins.v2/downloadertaskmanager/README.md`
- Modify: `tests/test_downloadertaskmanager.py`

- [ ] **Step 1: 写版本一致性失败测试**

验证：

```python
self.assertEqual(
    "1.0.0",
    package["DownloaderTaskManager"]["version"],
)
self.assertEqual(
    "下载器任务管理",
    package["DownloaderTaskManager"]["name"],
)
self.assertIn("BrushFlowLowFreq", package)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: FAIL，包索引中不存在 `DownloaderTaskManager`。

- [ ] **Step 3: 更新包索引**

在 `package.v2.json` 追加：

```json
{
  "DownloaderTaskManager": {
    "name": "下载器任务管理",
    "description": "管理已启用下载器的单个任务和当前下载器全部任务的开始与暂停。",
    "labels": "下载管理,Qbittorrent,Transmission",
    "version": "1.0.0",
    "icon": "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/Qbittorrent_A.png",
    "author": "tsg1981gmail",
    "level": 1,
    "system_version": ">=2.12.0,<3",
    "history": {
      "v1.0.0": "初始版本：按下载器展示任务，支持单任务及当前下载器全部任务的开始与暂停"
    }
  }
}
```

必须保留 `BrushFlowLowFreq` 完整条目。

- [ ] **Step 4: 写插件 README**

README 必须说明：

- 自动读取所有已启用下载器。
- 支持 qBittorrent 和 Transmission。
- 默认关闭全量操作。
- 全量操作仅作用于单个下载器。
- 只开始或暂停任务，不删除任务和文件。
- 数据页按钮需要 MoviePilot v2。

- [ ] **Step 5: 运行测试**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add package.v2.json plugins.v2/downloadertaskmanager/README.md tests/test_downloadertaskmanager.py
git commit -m "docs: publish downloader task manager metadata"
```

---

### Task 5: 全量验证与 GitHub 发布

**Files:**
- Modify: none

**Skill:** `@verification-before-completion`

- [ ] **Step 1: 运行插件测试**

Run:

```bash
python3 -m pytest tests/test_downloadertaskmanager.py -v
```

Expected: 全部 PASS。

- [ ] **Step 2: 运行语法检查**

Run:

```bash
python3 -m py_compile \
  plugins.v2/downloadertaskmanager/runtime.py \
  plugins.v2/downloadertaskmanager/service.py \
  plugins.v2/downloadertaskmanager/__init__.py
```

Expected: exit code 0。

- [ ] **Step 3: 校验包索引 JSON**

Run:

```bash
python3 -m json.tool package.v2.json >/dev/null
python3 - <<'PY'
import json
from pathlib import Path

package = json.loads(Path("package.v2.json").read_text())
assert "BrushFlowLowFreq" in package
assert package["DownloaderTaskManager"]["version"] == "1.0.0"
print("package.v2.json OK")
PY
```

Expected: `package.v2.json OK`。

- [ ] **Step 4: 检查代码差异**

Run:

```bash
git diff --check
git status --short
```

Expected: 无空白错误；只包含本插件、测试、包索引和文档变更。

- [ ] **Step 5: 预览 GitHub 发布差异**

使用 MoviePilot 发布脚本对
`tsg1981gmail/MoviePilot-Plugins` 执行 `preview`，确认只新增或修改：

- `plugins.v2/downloadertaskmanager/`
- `tests/test_downloadertaskmanager.py`
- `package.v2.json`
- 设计文档和计划文档

不得删除或覆盖 `BrushFlowLowFreq`。

- [ ] **Step 6: 推送到 main**

使用 GitHub Contents API 发布到 `tsg1981gmail/MoviePilot-Plugins/main`。
推送后读取远端 `package.v2.json` 和插件入口，确认：

- 远端版本为 `1.0.0`。
- `BrushFlowLowFreq` 仍存在。
- 远端插件目录包含 `__init__.py`、`runtime.py`、`service.py`、`README.md`。

