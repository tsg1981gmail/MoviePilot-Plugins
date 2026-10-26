import json
import inspect
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins.v2"))


def _install_module(name):
    """安装测试所需的 MoviePilot 模块桩。"""
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


class _PluginBase:
    """提供插件测试所需的配置和数据存储接口。"""

    def __init__(self):
        """初始化内存数据存储。"""
        self.saved_data = {}
        self.updated_config = None

    def save_data(self, key, value, plugin_id=None):
        """保存测试数据。"""
        self.saved_data[key] = value

    def get_data(self, key=None, plugin_id=None):
        """读取测试数据。"""
        if key is None:
            return self.saved_data
        return self.saved_data.get(key)

    def update_config(self, config, plugin_id=None):
        """记录插件配置。"""
        self.updated_config = config
        return True


class _DownloaderHelper:
    """提供插件导入所需的空下载器帮助类。"""

    def get_services(self):
        """返回空服务映射。"""
        return {}


app_module = _install_module("app")
helper_module = _install_module("app.helper")
downloader_helper_module = _install_module("app.helper.downloader")
plugins_module = _install_module("app.plugins")
downloader_helper_module.DownloaderHelper = _DownloaderHelper
plugins_module._PluginBase = _PluginBase
app_module.helper = helper_module
app_module.plugins = plugins_module

import downloadertaskmanager
from downloadertaskmanager import DownloaderTaskManager
from downloadertaskmanager.runtime import normalize_status, normalize_torrent
from downloadertaskmanager.service import DownloaderTaskService


class FakeDownloaderInstance:
    """模拟 MoviePilot 下载器实例。"""

    def __init__(self, torrents=None, inactive=False, query_error=None, action_error=None):
        """保存模拟任务、连接状态和异常配置。"""
        self.torrents = list(torrents or [])
        self.inactive = inactive
        self.query_error = query_error
        self.action_error = action_error
        self.started = []
        self.stopped = []

    def is_inactive(self):
        """返回模拟连接状态。"""
        return self.inactive

    def get_torrents(self):
        """返回模拟任务列表和查询状态。"""
        if self.query_error is not None:
            if isinstance(self.query_error, Exception):
                raise self.query_error
            return [], self.query_error
        return list(self.torrents), False

    def start_torrents(self, ids):
        """记录开始任务请求。"""
        if self.action_error is not None:
            raise self.action_error
        self.started.append(list(ids))
        return True

    def stop_torrents(self, ids):
        """记录暂停任务请求。"""
        if self.action_error is not None:
            raise self.action_error
        self.stopped.append(list(ids))
        return True


class FakeDownloaderService:
    """模拟 MoviePilot 服务信息。"""

    def __init__(self, name, downloader_type, instance):
        """保存服务名称、类型和实例。"""
        self.name = name
        self.type = downloader_type
        self.config = None
        self.instance = instance


class FakeDownloaderHelper:
    """模拟 DownloaderHelper。"""

    def __init__(self, services):
        """保存服务映射。"""
        self.services = services

    def get_services(self):
        """返回全部模拟服务。"""
        return self.services

    def get_service(self, name):
        """按名称返回模拟服务。"""
        return self.services.get(name)


def _walk_components(node):
    """递归遍历页面组件节点。"""
    if isinstance(node, list):
        for item in node:
            yield from _walk_components(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    yield from _walk_components(node.get("content") or [])


def _button_events(page):
    """提取页面按钮文本和点击事件。"""
    events = []
    for node in _walk_components(page):
        if node.get("component") != "VBtn":
            continue
        event = (node.get("events") or {}).get("click")
        if event:
            events.append((str(node.get("text") or ""), event))
    return events


def _component_text(node):
    """读取组件的直接文本或 text 属性。"""
    return str(node.get("text") or (node.get("props") or {}).get("text") or "")


class DownloaderRuntimeTests(unittest.TestCase):
    """验证下载器任务字段归一化。"""

    def test_normalize_qbittorrent_torrent(self):
        """将 qBittorrent 字典任务转换为统一结构。"""
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
        self.assertEqual("qb-task", result["name"])
        self.assertEqual("paused", result["status"])
        self.assertEqual("已暂停", result["state_text"])
        self.assertTrue(result["paused"])
        self.assertEqual(50.0, result["progress"])
        self.assertEqual(1024, result["size"])
        self.assertEqual(100, result["download_speed"])
        self.assertEqual(20, result["upload_speed"])
        self.assertEqual("电影", result["category"])
        self.assertEqual(100, result["added_at"])

    def test_normalize_transmission_torrent(self):
        """将 Transmission 属性任务转换为统一结构。"""
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
        self.assertEqual("tr-task", result["name"])
        self.assertEqual("downloading", result["status"])
        self.assertEqual("下载中", result["state_text"])
        self.assertFalse(result["paused"])
        self.assertEqual(25.0, result["progress"])
        self.assertEqual(2048, result["size"])
        self.assertEqual(200, result["download_speed"])
        self.assertEqual(30, result["upload_speed"])
        self.assertEqual("刷流,电影", result["category"])
        self.assertIsNone(result["added_at"])

    def test_transmission_status_matrix(self):
        """覆盖 Transmission 全部文档状态。"""
        cases = {
            "stopped": "paused",
            "downloading": "downloading",
            "download_pending": "downloading",
            "seeding": "uploading",
            "seed_pending": "uploading",
            "checking": "checking",
            "check_pending": "checking",
            "error": "error",
        }

        for raw_status, expected in cases.items():
            with self.subTest(raw_status=raw_status):
                self.assertEqual(
                    expected,
                    normalize_status(raw_status, "transmission"),
                )

    def test_unknown_status_is_not_guessed(self):
        """未知状态归为 unknown 且不标记为暂停。"""
        self.assertEqual("unknown", normalize_status("mystery", "qbittorrent"))
        self.assertEqual("unknown", normalize_status("mystery", "transmission"))

        result = normalize_torrent({
            "hash": "abc",
            "name": "unknown",
            "state": "mystery",
            "progress": 0,
        }, "qbittorrent")

        self.assertEqual("unknown", result["status"])
        self.assertEqual("未知", result["state_text"])
        self.assertFalse(result["paused"])

    def test_error_status_and_state_text_are_normalized(self):
        """错误状态归为 error 并显示中文。"""
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

    def test_invalid_hash_returns_none(self):
        """缺失或空白哈希的任务不进入页面。"""
        self.assertIsNone(normalize_torrent({"hash": "  "}, "qbittorrent"))
        self.assertIsNone(normalize_torrent({}, "transmission"))


class DownloaderTaskServiceTests(unittest.TestCase):
    """验证下载器发现和任务动作编排。"""

    @staticmethod
    def _qb_torrent(torrent_hash="abcdef", state="pausedDL"):
        """构造 qBittorrent 测试任务。"""
        return {
            "hash": torrent_hash,
            "name": "task",
            "state": state,
            "progress": 0.5,
            "size": 1024,
        }

    def _service(self, instance=None, allow_bulk=True, downloader_type="qbittorrent"):
        """构造带一个下载器的服务层。"""
        instance = instance or FakeDownloaderInstance([self._qb_torrent()])
        helper = FakeDownloaderHelper({
            "QB": FakeDownloaderService("QB", downloader_type, instance),
        })
        return DownloaderTaskService(helper, allow_bulk_actions=allow_bulk), instance

    def test_list_views_normalizes_tasks_and_keeps_error_views(self):
        """列出任务，同时保留未连接和不支持的下载器。"""
        inactive = FakeDownloaderInstance([self._qb_torrent()], inactive=True)
        unsupported = FakeDownloaderInstance([self._qb_torrent()])
        broken = FakeDownloaderInstance(query_error=True)
        helper = FakeDownloaderHelper({
            "QB": FakeDownloaderService("QB", "qbittorrent", inactive),
            "TR": FakeDownloaderService("TR", "transmission", broken),
            "RT": FakeDownloaderService("RT", "rtorrent", unsupported),
        })
        service = DownloaderTaskService(helper, allow_bulk_actions=True)

        views = {view["name"]: view for view in service.list_views()}

        self.assertFalse(views["QB"]["available"])
        self.assertTrue(views["QB"]["error"])
        self.assertFalse(views["TR"]["available"])
        self.assertTrue(views["TR"]["error"])
        self.assertFalse(views["RT"]["available"])
        self.assertIn("不支持", views["RT"]["error"])
        self.assertEqual([], views["RT"]["tasks"])

    def test_list_views_filters_invalid_tasks_and_catches_exception(self):
        """正常任务保留，无效任务过滤，查询异常只影响当前下载器。"""
        instance = FakeDownloaderInstance([
            self._qb_torrent("ABCDEF"),
            {"hash": " ", "name": "invalid"},
        ])
        throwing = FakeDownloaderInstance(query_error=RuntimeError("connection failed"))
        helper = FakeDownloaderHelper({
            "QB": FakeDownloaderService("QB", "qbittorrent", instance),
            "QB2": FakeDownloaderService("QB2", "qbittorrent", throwing),
        })
        service = DownloaderTaskService(helper, allow_bulk_actions=True)

        views = {view["name"]: view for view in service.list_views()}

        self.assertTrue(views["QB"]["available"])
        self.assertEqual(["abcdef"], [task["hash"] for task in views["QB"]["tasks"]])
        self.assertFalse(views["QB2"]["available"])
        self.assertIn("connection failed", views["QB2"]["error"])

    def test_execute_starts_and_stops_single_task(self):
        """单任务开始和暂停使用去重后的哈希。"""
        service, instance = self._service()

        started = service.execute({
            "downloader": "QB",
            "scope": "task",
            "action": "start",
            "hashes": [" ABCDEF ", "abcdef"],
        })
        stopped = service.execute({
            "downloader": "QB",
            "scope": "task",
            "action": "stop",
            "hashes": ["ABCDEF"],
        })

        self.assertTrue(started["success"])
        self.assertEqual(1, started["affected"])
        self.assertEqual([["abcdef"]], instance.started)
        self.assertTrue(stopped["success"])
        self.assertEqual([["abcdef"]], instance.stopped)

    def test_execute_all_uses_current_downloader_hashes(self):
        """全量操作读取当前下载器全部有效任务。"""
        instance = FakeDownloaderInstance([
            self._qb_torrent("one"),
            self._qb_torrent("two"),
            {"hash": " "},
        ])
        service, _ = self._service(instance=instance)

        result = service.execute({
            "downloader": "QB",
            "scope": "all",
            "action": "start",
        })

        self.assertTrue(result["success"])
        self.assertEqual(2, result["affected"])
        self.assertEqual([["one", "two"]], instance.started)

    def test_execute_all_requires_bulk_option(self):
        """未开启全量操作时拒绝全部任务动作。"""
        service, instance = self._service(allow_bulk=False)

        result = service.execute({
            "downloader": "QB",
            "scope": "all",
            "action": "stop",
        })

        self.assertFalse(result["success"])
        self.assertEqual(0, result["affected"])
        self.assertEqual([], instance.stopped)

    def test_execute_all_rejects_empty_query_error_and_exception(self):
        """全量操作拒绝空列表、查询错误和查询异常。"""
        empty_service, empty_instance = self._service(
            instance=FakeDownloaderInstance([])
        )
        error_service, error_instance = self._service(
            instance=FakeDownloaderInstance(query_error=True)
        )
        throw_service, throw_instance = self._service(
            instance=FakeDownloaderInstance(query_error=RuntimeError("query failed"))
        )
        payload = {"downloader": "QB", "scope": "all", "action": "start"}

        for service, instance in (
            (empty_service, empty_instance),
            (error_service, error_instance),
            (throw_service, throw_instance),
        ):
            result = service.execute(payload)
            self.assertFalse(result["success"])
            self.assertEqual(0, result["affected"])
            self.assertEqual([], instance.started)

    def test_execute_rejects_invalid_payloads_and_downloaders(self):
        """拒绝非法字段、未知下载器、不支持类型和未连接实例。"""
        inactive = FakeDownloaderInstance([], inactive=True)
        inactive_helper = FakeDownloaderHelper({
            "QB": FakeDownloaderService("QB", "qbittorrent", inactive),
        })
        inactive_service = DownloaderTaskService(inactive_helper, allow_bulk_actions=True)

        cases = [
            ({}, "QB"),
            ({"downloader": "missing", "scope": "task", "action": "start", "hashes": ["a"]}, ""),
            ({"downloader": "QB", "scope": "bad", "action": "start", "hashes": ["a"]}, "QB"),
            ({"downloader": "QB", "scope": "task", "action": "bad", "hashes": ["a"]}, "QB"),
            ({"downloader": "QB", "scope": "task", "action": "start", "hashes": []}, "QB"),
        ]
        service, _ = self._service()

        for payload, downloader in cases:
            target = inactive_service if downloader == "" else service
            result = target.execute(payload)
            self.assertFalse(result["success"])
            self.assertEqual(0, result["affected"])

        unsupported_service, _ = self._service(downloader_type="rtorrent")
        unsupported = unsupported_service.execute({
            "downloader": "QB",
            "scope": "task",
            "action": "start",
            "hashes": ["a"],
        })
        unavailable = inactive_service.execute({
            "downloader": "QB",
            "scope": "task",
            "action": "start",
            "hashes": ["a"],
        })

        self.assertFalse(unsupported["success"])
        self.assertFalse(unavailable["success"])

    def test_execute_handles_false_and_exception_from_action(self):
        """动作返回 False 或抛异常时返回失败结果。"""
        false_instance = FakeDownloaderInstance([self._qb_torrent()])
        false_instance.start_torrents = lambda ids: False
        false_service, _ = self._service(instance=false_instance)

        throw_instance = FakeDownloaderInstance(
            [self._qb_torrent()],
            action_error=RuntimeError("action failed"),
        )
        throw_service, _ = self._service(instance=throw_instance)

        payload = {
            "downloader": "QB",
            "scope": "task",
            "action": "start",
            "hashes": ["abcdef"],
        }

        self.assertFalse(false_service.execute(payload)["success"])
        failed = throw_service.execute(payload)
        self.assertFalse(failed["success"])
        self.assertIn("action failed", failed["message"])


class DownloaderTaskManagerPluginTests(unittest.TestCase):
    """验证 MoviePilot 插件配置、页面和 API 契约。"""

    def setUp(self):
        """安装可配置下载器帮助类。"""
        self.original_helper = downloadertaskmanager.DownloaderHelper
        self.helper = FakeDownloaderHelper({})
        downloadertaskmanager.DownloaderHelper = lambda: self.helper

    def tearDown(self):
        """恢复下载器帮助类。"""
        downloadertaskmanager.DownloaderHelper = self.original_helper

    @staticmethod
    def _raw_qb(torrent_hash, state, name=None):
        """构造页面测试任务。"""
        return {
            "hash": torrent_hash,
            "name": name or torrent_hash,
            "state": state,
            "progress": 0.5,
            "size": 1024 * 1024,
            "dlspeed": 1024,
            "upspeed": 2048,
            "category": "电影",
        }

    def _enabled_plugin(self, allow_bulk=True):
        """构造已启用插件。"""
        plugin = DownloaderTaskManager()
        plugin.init_plugin({
            "enabled": True,
            "allow_bulk_actions": allow_bulk,
        })
        return plugin

    def test_form_defaults_and_api_contract(self):
        """配置默认值和动作 API 契约正确。"""
        plugin = DownloaderTaskManager()
        form, defaults = plugin.get_form()
        api = plugin.get_api()

        self.assertFalse(defaults["enabled"])
        self.assertFalse(defaults["allow_bulk_actions"])
        self.assertGreater(len(form), 0)
        self.assertEqual("/action", api[0]["path"])
        self.assertEqual(["POST"], api[0]["methods"])
        self.assertEqual("bear", api[0]["auth"])

    def test_disabled_plugin_rejects_action_and_shows_prompt(self):
        """禁用插件时拒绝动作且不调用下载器。"""
        plugin = DownloaderTaskManager()
        plugin.init_plugin({"enabled": False, "allow_bulk_actions": False})
        plugin._service = type("ExplodingService", (), {
            "execute": lambda self, payload: self.fail("不应调用下载器"),
        })()

        result = plugin.action({
            "downloader": "QB",
            "scope": "task",
            "action": "start",
            "hashes": ["abc"],
        })
        page = plugin.get_page()
        alerts = [
            node for node in _walk_components(page)
            if node.get("component") == "VAlert"
        ]

        self.assertFalse(result["success"])
        self.assertEqual(result, plugin.saved_data["last_action_result"])
        self.assertTrue(any("未启用" in _component_text(alert) for alert in alerts))

    def test_page_renders_all_task_action_states(self):
        """七种状态按固定规则显示任务按钮。"""
        tasks = [
            self._raw_qb("paused", "pausedDL"),
            self._raw_qb("error", "missingFiles"),
            self._raw_qb("downloading", "downloading"),
            self._raw_qb("uploading", "uploading"),
            self._raw_qb("checking", "checking"),
            self._raw_qb("queued", "queuedDL"),
            self._raw_qb("unknown", "mystery"),
        ]
        instance = FakeDownloaderInstance(tasks)
        self.helper.services = {
            "QB": FakeDownloaderService("QB", "qbittorrent", instance),
        }
        plugin = self._enabled_plugin(allow_bulk=True)

        page = plugin.get_page()
        buttons = _button_events(page)
        task_actions = {
            event["params"]["hashes"][0]: text
            for text, event in buttons
            if event.get("params", {}).get("hashes")
        }

        self.assertEqual("开始", task_actions["paused"])
        self.assertEqual("开始", task_actions["error"])
        self.assertEqual("暂停", task_actions["downloading"])
        self.assertEqual("暂停", task_actions["uploading"])
        self.assertEqual("暂停", task_actions["checking"])
        self.assertEqual("暂停", task_actions["queued"])
        self.assertNotIn("unknown", task_actions)
        self.assertIn("全部开始", [text for text, _ in buttons])
        self.assertIn("全部暂停", [text for text, _ in buttons])

        for _, event in buttons:
            self.assertEqual(
                "plugin/DownloaderTaskManager/action",
                event["api"],
            )
            self.assertEqual("POST", event["method"])

    def test_page_hides_bulk_buttons_when_disabled(self):
        """未开启全量操作时不显示全量按钮。"""
        instance = FakeDownloaderInstance([self._raw_qb("abc", "pausedDL")])
        self.helper.services = {
            "QB": FakeDownloaderService("QB", "qbittorrent", instance),
        }
        plugin = self._enabled_plugin(allow_bulk=False)

        texts = [text for text, _ in _button_events(plugin.get_page())]

        self.assertNotIn("全部开始", texts)
        self.assertNotIn("全部暂停", texts)

    def test_action_result_is_persisted_and_rendered(self):
        """动作结果持久化并在页面显示。"""
        plugin = self._enabled_plugin()
        result = {
            "success": True,
            "message": "已开始 1 个任务",
            "affected": 1,
        }
        plugin._service = type("FakeService", (), {
            "list_views": lambda self: [],
            "execute": lambda self, payload: result,
        })()

        returned = plugin.action({
            "downloader": "QB",
            "scope": "task",
            "action": "start",
            "hashes": ["abc"],
        })
        page = plugin.get_page()
        alerts = [
            node for node in _walk_components(page)
            if node.get("component") == "VAlert"
        ]

        self.assertEqual(result, returned)
        self.assertEqual(result, plugin.saved_data["last_action_result"])
        self.assertTrue(any(_component_text(alert) == result["message"] for alert in alerts))

    def test_page_shows_downloader_discovery_error(self):
        """下载器枚举异常显示为全局错误而非空配置。"""
        class BrokenHelper:
            """模拟下载器枚举失败。"""

            def get_services(self):
                """抛出服务发现异常。"""
                raise RuntimeError("service discovery failed")

        downloadertaskmanager.DownloaderHelper = BrokenHelper
        plugin = self._enabled_plugin()
        page = plugin.get_page()
        alerts = [
            node for node in _walk_components(page)
            if node.get("component") == "VAlert"
        ]

        self.assertTrue(any(
            "获取下载器列表失败" in _component_text(alert)
            and "service discovery failed" in _component_text(alert)
            for alert in alerts
        ))

    def test_api_endpoint_accepts_payload_mapping(self):
        """动态 API 端点保留 payload 请求体参数。"""
        plugin = DownloaderTaskManager()
        api = plugin.get_api()[0]
        signature = inspect.signature(api["endpoint"])

        self.assertEqual(plugin.action, api["endpoint"])
        self.assertIn("payload", signature.parameters)


class DownloaderTaskManagerPackageTests(unittest.TestCase):
    """验证插件市场元数据和说明文档。"""

    def test_package_metadata_matches_plugin(self):
        """包索引保留旧插件并同步新插件版本信息。"""
        package = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
        metadata = package["DownloaderTaskManager"]

        self.assertIn("BrushFlowLowFreq", package)
        self.assertEqual("1.0.0", metadata["version"])
        self.assertEqual("下载器任务管理", metadata["name"])
        self.assertEqual("下载管理,Qbittorrent,Transmission", metadata["labels"])
        self.assertEqual(">=2.12.0,<3", metadata["system_version"])
        self.assertEqual(
            DownloaderTaskManager.plugin_version,
            metadata["version"],
        )

    def test_plugin_readme_exists(self):
        """插件目录包含使用说明。"""
        readme = ROOT / "plugins.v2" / "downloadertaskmanager" / "README.md"
        self.assertTrue(readme.is_file())
        self.assertIn("全量操作", readme.read_text(encoding="utf-8"))

    def test_action_route_with_fastapi_when_available(self):
        """宿主安装 FastAPI 时验证动态 API 的 JSON 请求体。"""
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("FastAPI 未安装")

        plugin = DownloaderTaskManager()
        api = plugin.get_api()[0]
        app = FastAPI()
        app.add_api_route(
            api["path"],
            api["endpoint"],
            methods=api["methods"],
        )
        client = TestClient(app)

        response = client.post(api["path"], json={
            "downloader": "QB",
            "scope": "task",
            "action": "start",
            "hashes": ["abc"],
        })

        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json()["success"])
        self.assertEqual("插件未启用", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
