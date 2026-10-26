# 下载器任务管理插件设计

## 目标

为 MoviePilot v2 提供一个轻量的下载器任务管理插件。插件自动读取
MoviePilot 设置中所有已启用的 qBittorrent 和 Transmission，在插件数据页按
下载器展示任务，并支持开始、暂停单个任务以及当前下载器的全部任务。

## 范围

- 插件 ID：`DownloaderTaskManager`
- 插件目录：`plugins.v2/downloadertaskmanager/`
- 初始版本：`1.0.0`
- UI 模式：Vuetify JSON
- 支持的下载器：qBittorrent、Transmission
- 不提供删除任务、文件操作、限速、重新校验或跨下载器全局操作

## 配置

配置页包含两个开关：

- `启用插件`：控制插件是否提供任务查询和操作能力。
- `允许全量操作`：默认关闭。开启后才显示并允许执行当前下载器的全部开始、
  全部暂停操作。

插件不保存下载器地址或账号，也不维护下载器白名单。运行时通过
`DownloaderHelper` 自动读取 MoviePilot 设置中所有已启用且受支持的下载器。

## 数据页

数据页按下载器分组，每个下载器区域包含：

- 下载器名称、类型、连接状态和任务数量。
- 当前下载器的“全部开始”和“全部暂停”按钮；仅在允许全量操作时显示。
- 任务表格，列为名称、状态、进度、下载速度、上传速度、分类或标签、操作。
- 每个任务根据归一化状态显示“开始”或“暂停”按钮。
- 最近一次操作结果提示。

单个下载器连接或查询失败时，其他下载器区域继续展示。失败信息显示在对应
下载器区域内。

## 任务数据归一化

qBittorrent 与 Transmission 的原始对象转换为统一任务结构：

- `hash`：任务唯一标识。qBittorrent 读取 `hash`，Transmission 读取
  `hashString`，统一转为小写；后续开始和暂停操作也只使用该哈希。
- `name`：任务名称。
- `status`：归一化状态，只允许 `paused`、`downloading`、`uploading`、
  `checking`、`queued`、`error`、`unknown`。
- `state_text`：中文状态。
- `paused`：是否处于暂停或停止状态。
- `progress`：0 到 100 的进度。
- `size`：任务总大小。
- `download_speed`：字节/秒。
- `upload_speed`：字节/秒。
- `category`：分类、目录或标签摘要。
- `added_at`：添加时间戳，无法获取时为空。

暂停判断兼容 qBittorrent 的 `paused*`、`stopped*` 状态和 Transmission 的
`stopped` 状态。字段读取必须同时兼容字典对象和 Transmission 属性对象。

状态归一化规则：

- qBittorrent：`paused*`、`stopped*` 映射为 `paused`；下载、元数据和下载队列
  状态映射为 `downloading`；做种及其队列状态映射为 `uploading`；校验状态映射
  为 `checking`；错误和文件缺失映射为 `error`。
- Transmission：`stopped` 映射为 `paused`；`downloading`、
  `download_pending` 映射为 `downloading`；`seeding`、`seed_pending` 映射为
  `uploading`；`checking`、`check_pending` 映射为 `checking`；`error` 映射为
  `error`。
- 未识别的状态统一为 `unknown`，页面显示“未知”，不猜测暂停状态。

Transmission 的 `progress` 原始值为 0 到 100；qBittorrent 的 `progress`
原始值为 0 到 1。输出统一为 0 到 100。

任务动作按钮映射：

- `paused`、`error`：显示“开始”。
- `downloading`、`uploading`、`checking`、`queued`：显示“暂停”。
- `unknown`：不显示单任务动作按钮，避免猜测安全状态。

## 插件 API

注册一个 Bear 鉴权接口。MoviePilot v2 插件 API 的公开路径为：

```text
POST /api/v1/plugin/DownloaderTaskManager/action
```

页面事件使用前端 API 客户端可解析的相对路径：
`plugin/DownloaderTaskManager/action`。

请求体：

```json
{
  "downloader": "下载器名称",
  "scope": "task",
  "action": "start",
  "hashes": ["任务哈希"]
}
```

- `scope` 只允许 `task` 或 `all`。
- `action` 只允许 `start` 或 `stop`。
- `scope=task` 必须提供非空 `hashes`。
- `scope=all` 必须开启“允许全量操作”，后端会重新读取当前下载器全部任务哈希。
- 下载器必须位于当前已启用、受支持的下载器列表中。

接口始终返回结构化结果：

```json
{
  "success": true,
  "message": "已开始 3 个任务",
  "affected": 3
}
```

操作结果保存到插件数据，数据页重新加载后显示最近结果。

数据页按钮使用 MoviePilot `PageRender` 支持的 `events` 结构：

```json
{
  "events": {
    "click": {
      "api": "plugin/DownloaderTaskManager/action",
      "method": "POST",
      "params": {
        "downloader": "下载器名称",
        "scope": "task",
        "action": "start",
        "hashes": ["任务哈希"]
      }
    }
  }
}
```

请求字段由 `ids` 改为 `hashes`，避免把下载器内部数字 ID 误当成稳定标识。

## 操作流程

1. 配置页保存启用状态和全量操作开关。
2. 数据页调用 `DownloaderHelper().get_services()` 获取已启用下载器。
3. 过滤出 qBittorrent 和 Transmission；未连接、不支持的下载器作为错误区域展示。
4. 对每个可用下载器调用 `get_torrents()`，归一化并按状态和名称排序。
5. 单任务操作通过 `start_torrents(ids=[hash])` 或
   `stop_torrents(ids=[hash])` 执行。
6. 全量操作读取当前下载器所有任务哈希，再调用同一动作方法。
7. 动作成功后保存结构化结果；页面刷新展示结果和最新任务状态。

## 错误处理

- 未启用插件时拒绝动作请求。
- 下载器不存在、未启用、未连接或类型不受支持时拒绝动作。
- 全量操作开关关闭时拒绝 `scope=all`，即使请求绕过页面直接调用 API。
- 非法动作、非法范围、空任务列表返回失败结果。
- 下载器方法返回 `False` 或抛出异常时返回失败结果，不中断其他下载器页面加载。
- 接口对预期业务错误返回 HTTP 200 和 `success=false`，以便页面刷新并展示错误；
  鉴权失败继续由 MoviePilot 宿主处理。

## 测试

使用 pytest 和 MoviePilot 依赖桩覆盖：

- qBittorrent 字典任务归一化。
- Transmission 属性任务归一化。
- 单任务开始和暂停分发。
- 当前下载器全部开始和全部暂停。
- 全量操作开关关闭时拒绝操作。
- 不支持、未连接、空任务等错误路径。
- 页面结构包含按下载器分组、单任务按钮和全量按钮条件。
- 页面按钮的 `events.click` 使用相对 API 路径、POST 方法和正确动作参数。
- qBittorrent 与 Transmission 的任务哈希均作为动作请求字段。
- 插件版本与 `package.v2.json` 一致。

发布前运行：

```bash
python3 -m py_compile plugins.v2/downloadertaskmanager/__init__.py
python3 -m pytest tests/test_downloadertaskmanager.py
git diff --check
```

## 发布

- 在 `package.v2.json` 中新增 `DownloaderTaskManager` 条目。
- 保留现有 `BrushFlowLowFreq` 条目和版本。
- 推送 `package.v2.json`、插件目录、测试和设计文档到
  `tsg1981gmail/MoviePilot-Plugins` 的 `main` 分支。
