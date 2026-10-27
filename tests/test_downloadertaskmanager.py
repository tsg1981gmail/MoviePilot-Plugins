import copy
import json
import sys
import threading
import time
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins.v2"))
TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 27, 10, 0, tzinfo=TZ)


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
        self.updated_config = {}

    def update_config(self, config, plugin_id=None):
        """保存配置。"""
        self.updated_config = copy.deepcopy(config)
        return True

    def save_data(self, key, value, plugin_id=None):
        """保存数据。"""
        self.saved_data[key] = copy.deepcopy(value)

    def get_data(self, key=None, plugin_id=None):
        """读取数据。"""
        if key is None:
            return copy.deepcopy(self.saved_data)
        return copy.deepcopy(self.saved_data.get(key))


class _DownloaderHelper:
    """提供插件导入所需的空下载器帮助类。"""

    def get_services(self):
        """返回空服务映射。"""
        return {}

    def get_service(self, name):
        """返回空下载器。"""
        return None


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
from downloadertaskmanager.runtime import (
    downloader_key,
    normalize_progress,
    normalize_status,
    normalize_torrent,
    parse_schedule_time,
    schedule_field,
    task_eligible,
)
from downloadertaskmanager.service import DownloaderScheduleService


def _walk_components(node):
    """递归遍历页面组件。"""
    if isinstance(node, list):
        for item in node:
            yield from _walk_components(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    yield from _walk_components(node.get("content") or [])


def _component_text(node):
    """读取组件节点中的文本。"""
    props = node.get("props") or {}
    return str(node.get("text") or props.get("text") or "")


class RuntimeTests(unittest.TestCase):
    """验证调度运行时纯函数。"""

    KEY = "c70ff5f613c1"

    def test_downloader_key_and_fields_are_stable(self):
        """稳定键和字段名匹配规格算法。"""
        self.assertEqual(
            self.KEY,
            downloader_key("qbittorrent", "QB"),
        )
        self.assertNotEqual(
            downloader_key("qbittorrent", "QB"),
            downloader_key("transmission", "QB"),
        )
        self.assertEqual(
            f"schedule_{self.KEY}_start_at",
            schedule_field(self.KEY, "start"),
        )
        self.assertEqual(
            f"schedule_{self.KEY}_pause_at",
            schedule_field(self.KEY, "stop"),
        )

    def test_parse_schedule_time(self):
        """解析两种本地时间格式并拒绝非法值。"""
        first = parse_schedule_time("2026-10-27T02:00", TZ)
        second = parse_schedule_time("2026-10-27 02:00", TZ)

        self.assertEqual(first, second)
        self.assertEqual(first.utcoffset(), timedelta(hours=8))
        self.assertIsNone(parse_schedule_time("bad", TZ))
        self.assertIsNone(parse_schedule_time("", TZ))

    def test_progress_normalization(self):
        """按下载器类型归一化并限制进度。"""
        self.assertEqual(99.9, normalize_progress(0.999, "qbittorrent"))
        self.assertEqual(100.0, normalize_progress(1.0, "qbittorrent"))
        self.assertEqual(99.9, normalize_progress(99.9, "transmission"))
        self.assertEqual(100.0, normalize_progress(100.0, "transmission"))
        self.assertLess(
            normalize_progress(0.9999, "qbittorrent"),
            100.0,
        )
        self.assertEqual(0.0, normalize_progress(-1, "transmission"))
        self.assertEqual(100.0, normalize_progress(101, "transmission"))
        self.assertEqual(0.0, normalize_progress("bad", "transmission"))

    def test_status_matrix(self):
        """覆盖 qBittorrent 与 Transmission 状态映射。"""
        cases = [
            ("pausedDL", "qbittorrent", "paused"),
            ("stoppedUP", "qbittorrent", "paused"),
            ("forcedMetaDL", "qbittorrent", "downloading"),
            ("checkingResumeData", "qbittorrent", "checking"),
            ("queuedDL", "qbittorrent", "queued"),
            ("queuedUP", "qbittorrent", "uploading"),
            ("missingFiles", "qbittorrent", "error"),
            ("stopped", "transmission", "paused"),
            ("download_pending", "transmission", "downloading"),
            ("check_pending", "transmission", "checking"),
            ("download_wait", "transmission", "queued"),
            ("seed_pending", "transmission", "uploading"),
            ("error", "transmission", "error"),
            ("mystery", "transmission", "unknown"),
        ]

        for raw, downloader_type, expected in cases:
            with self.subTest(raw=raw, downloader_type=downloader_type):
                self.assertEqual(
                    expected,
                    normalize_status(raw, downloader_type),
                )

    def test_normalize_torrent_and_eligibility(self):
        """开始只选暂停任务，暂停只选未完成的活动任务。"""
        paused = normalize_torrent({
            "hash": "ABC",
            "state": "pausedDL",
            "progress": 0.5,
        }, "qbittorrent")
        downloading = normalize_torrent({
            "hash": "DEF",
            "state": "downloading",
            "progress": 0.25,
        }, "qbittorrent")
        seeding = normalize_torrent({
            "hash": "GHI",
            "state": "uploading",
            "progress": 1.0,
        }, "qbittorrent")
        transmission = normalize_torrent(type("Torrent", (), {
            "hashString": "JKL",
            "status": "download_pending",
            "progress": 40.0,
        })(), "transmission")

        self.assertTrue(task_eligible(paused, "start"))
        self.assertFalse(task_eligible(paused, "stop"))
        self.assertTrue(task_eligible(downloading, "stop"))
        self.assertFalse(task_eligible(seeding, "start"))
        self.assertFalse(task_eligible(seeding, "stop"))
        self.assertTrue(task_eligible(transmission, "stop"))
        self.assertFalse(task_eligible(transmission, "start"))


class FakeInstance:
    """模拟下载器实例。"""

    def __init__(self, torrents=None, inactive=False, query_error=False,
                 action_result=True, action_error=None, delay=0):
        """保存测试状态。"""
        self.torrents = list(torrents or [])
        self.inactive = inactive
        self.query_error = query_error
        self.action_result = action_result
        self.action_error = action_error
        self.delay = delay
        self.started = []
        self.stopped = []

    def is_inactive(self):
        """返回连接状态。"""
        return self.inactive

    def get_torrents(self):
        """返回任务列表和是否失败。"""
        if isinstance(self.query_error, Exception):
            raise self.query_error
        return copy.deepcopy(self.torrents), bool(self.query_error)

    def start_torrents(self, ids):
        """记录开始请求。"""
        if self.delay:
            time.sleep(self.delay)
        if self.action_error:
            raise self.action_error
        self.started.append(list(ids))
        return self.action_result

    def stop_torrents(self, ids):
        """记录暂停请求。"""
        if self.action_error:
            raise self.action_error
        self.stopped.append(list(ids))
        return self.action_result


class FakeService:
    """模拟 MoviePilot ServiceInfo。"""

    def __init__(self, name, service_type, instance):
        """保存服务信息。"""
        self.name = name
        self.type = service_type
        self.instance = instance


class FakeHelper:
    """模拟 DownloaderHelper。"""

    def __init__(self, services=None):
        """保存服务映射。"""
        self.services = services or {}

    def get_services(self):
        """返回服务映射。"""
        return self.services

    def get_service(self, name):
        """按名称返回服务。"""
        return self.services.get(name)


class ScheduleServiceTests(unittest.TestCase):
    """验证一次性计划注册、排序和执行。"""

    KEY = "c70ff5f613c1"

    def _new_service(self, config, instance, now=NOW, invalidate=False):
        """构造计划服务。"""
        helper = FakeHelper({
            "QB": FakeService("QB", "qbittorrent", instance),
        })
        self.config = copy.deepcopy(config)
        self.config_snapshots = []
        self.registry_snapshots = []
        self.result_snapshots = []
        self.now_value = now
        service = DownloaderScheduleService(
            helper=helper,
            config=self.config,
            registry={},
            results={},
            now_fn=lambda: self.now_value,
            timezone=TZ,
            persist_config=self._persist_config,
            save_registry=self._save_registry,
            save_results=self._save_results,
        )
        service.refresh_registry()
        if invalidate:
            service.helper.services["QB"].instance.inactive = True
        return service

    def _persist_config(self, config):
        """记录配置持久化。"""
        self.config_snapshots.append(copy.deepcopy(config))

    def _save_registry(self, registry):
        """记录注册表持久化。"""
        self.registry_snapshots.append(copy.deepcopy(registry))

    def _save_results(self, results):
        """记录结果持久化。"""
        self.result_snapshots.append(copy.deepcopy(results))

    def test_registry_refresh_preserves_old_snapshots(self):
        """刷新注册表保留旧下载器快照。"""
        service = self._new_service({}, FakeInstance())
        service.registry["old"] = {"name": "Old", "type": "transmission"}

        registry = service.refresh_registry()

        self.assertIn(self.KEY, registry)
        self.assertIn("old", registry)
        self.assertEqual("QB", registry[self.KEY]["name"])

    def test_duplicate_type_and_name_is_config_error(self):
        """重复下载器名称和类型时计划不执行。"""
        helper = FakeHelper({
            "A": FakeService("QB", "qbittorrent", FakeInstance()),
            "B": FakeService("QB", "qbittorrent", FakeInstance()),
        })
        config = {
            schedule_field(self.KEY, "start"): "2026-10-27T09:00",
        }
        service = DownloaderScheduleService(
            helper=helper,
            config=config,
            registry={},
            results={},
            now_fn=lambda: NOW,
            timezone=TZ,
            persist_config=lambda value: None,
            save_registry=lambda value: None,
            save_results=lambda value: None,
        )
        service.refresh_registry()

        plans = service.list_plans()

        self.assertTrue(plans[0]["error"])
        self.assertIn("重复", plans[0]["error"])
        self.assertEqual([], service.due_plans())

    def test_list_plans_and_due_sorting(self):
        """计划和到期列表使用 start/stop 动作并稳定排序。"""
        start = "2026-10-27T09:00"
        stop = "2026-10-27T11:00"
        service = self._new_service({
            schedule_field(self.KEY, "start"): start,
            schedule_field(self.KEY, "stop"): stop,
        }, FakeInstance())

        plans = service.list_plans()
        due = service.due_plans()

        self.assertEqual({"start", "stop"}, {plan["action"] for plan in plans})
        self.assertEqual(["start"], [plan["action"] for plan in due])
        self.assertEqual("QB", due[0]["name"])

    def test_empty_schedule_fields_mean_no_plan(self):
        """空时间字段表示未设置，不产生配置错误。"""
        service = self._new_service({
            schedule_field(self.KEY, "start"): "",
            schedule_field(self.KEY, "stop"): "",
        }, FakeInstance())

        self.assertEqual([], service.list_plans())
        self.assertEqual([], service.due_plans())

    def test_same_time_and_missing_snapshot_are_config_errors(self):
        """同时间和缺失快照产生配置错误。"""
        same = "2026-10-27T09:00"
        missing_field = schedule_field("abcdef123456", "start")
        service = self._new_service({
            schedule_field(self.KEY, "start"): same,
            schedule_field(self.KEY, "stop"): same,
            missing_field: same,
        }, FakeInstance())

        plans = service.list_plans()

        self.assertTrue(all(plan["error"] for plan in plans))
        self.assertTrue(any("相同" in plan["error"] for plan in plans))
        self.assertTrue(any("快照" in plan["error"] for plan in plans))

    def test_execute_start_only_selects_paused_incomplete(self):
        """开始计划只启动暂停且未完成任务。"""
        instance = FakeInstance([
            {"hash": "A", "state": "pausedDL", "progress": 0.5},
            {"hash": "B", "state": "pausedUP", "progress": 1.0},
            {"hash": "C", "state": "downloading", "progress": 0.5},
        ])
        service = self._new_service({
            schedule_field(self.KEY, "start"): "2026-10-27T09:00",
        }, instance)

        result = service.run_due()[0]

        self.assertTrue(result["success"])
        self.assertEqual(1, result["affected"])
        self.assertEqual([["a"]], instance.started)
        self.assertNotIn(schedule_field(self.KEY, "start"), self.config)

    def test_execute_stop_only_selects_active_incomplete(self):
        """暂停计划只停止活动且未完成任务。"""
        instance = FakeInstance([
            {"hash": "A", "state": "downloading", "progress": 0.5},
            {"hash": "B", "state": "queuedDL", "progress": 0.2},
            {"hash": "C", "state": "uploading", "progress": 1.0},
            {"hash": "D", "state": "pausedDL", "progress": 0.5},
        ])
        service = self._new_service({
            schedule_field(self.KEY, "stop"): "2026-10-27T09:00",
        }, instance)

        result = service.run_due()[0]

        self.assertTrue(result["success"])
        self.assertEqual(["a", "b"], instance.stopped[0])
        self.assertEqual(2, result["affected"])

    def test_zero_candidates_succeeds_and_clears(self):
        """没有候选任务时成功并清空计划。"""
        service = self._new_service({
            schedule_field(self.KEY, "start"): "2026-10-27T09:00",
        }, FakeInstance([
            {"hash": "A", "state": "uploading", "progress": 1.0},
        ]))

        result = service.run_due()[0]

        self.assertTrue(result["success"])
        self.assertEqual(0, result["affected"])
        self.assertNotIn(schedule_field(self.KEY, "start"), self.config)

    def test_failure_keeps_plan_and_retries(self):
        """失败保留计划，下一周期继续尝试。"""
        instance = FakeInstance(
            [{"hash": "A", "state": "pausedDL", "progress": 0.5}],
            inactive=True,
        )
        service = self._new_service({
            schedule_field(self.KEY, "start"): "2026-10-27T09:00",
        }, instance)

        first = service.run_due()[0]
        self.assertFalse(first["success"])
        self.assertIn(schedule_field(self.KEY, "start"), self.config)
        service.helper.services["QB"].instance.inactive = False
        self.now_value = NOW + timedelta(minutes=4)
        self.assertEqual([], service.run_due())
        self.now_value = NOW + timedelta(minutes=5)
        second = service.run_due()[0]

        self.assertTrue(second["success"])
        self.assertNotIn(schedule_field(self.KEY, "start"), self.config)

    def test_action_false_and_exception_keep_plan(self):
        """动作 False 和异常都保留计划。"""
        for instance in (
            FakeInstance(
                [{"hash": "A", "state": "pausedDL", "progress": 0.5}],
                action_result=False,
            ),
            FakeInstance(
                [{"hash": "A", "state": "pausedDL", "progress": 0.5}],
                action_error=RuntimeError("boom"),
            ),
        ):
            service = self._new_service({
                schedule_field(self.KEY, "start"): "2026-10-27T09:00",
            }, instance)
            result = service.run_due()[0]
            self.assertFalse(result["success"])
            self.assertIn(schedule_field(self.KEY, "start"), self.config)

    def test_results_are_stored_per_action(self):
        """开始和暂停结果独立保存。"""
        instance = FakeInstance([
            {"hash": "A", "state": "pausedDL", "progress": 0.5},
            {"hash": "B", "state": "downloading", "progress": 0.5},
        ])
        service = self._new_service({
            schedule_field(self.KEY, "start"): "2026-10-27T09:00",
            schedule_field(self.KEY, "stop"): "2026-10-27T08:00",
        }, instance)

        results = service.run_due()

        self.assertEqual(2, len(results))
        self.assertIn("start", service.results[self.KEY])
        self.assertIn("stop", service.results[self.KEY])
        self.assertEqual(["b"], instance.stopped[0])
        self.assertEqual([["a"]], instance.started)

    def test_run_due_is_serialized_by_lock(self):
        """重叠 run_due 调用不会同时执行。"""
        service = self._new_service({
            schedule_field(self.KEY, "start"): "2026-10-27T09:00",
        }, FakeInstance(
            [{"hash": "A", "state": "pausedDL", "progress": 0.5}],
            delay=0.05,
        ))
        original_execute = service.execute_plan
        active = []
        max_active = []

        def tracked_execute(plan):
            active.append(1)
            max_active.append(len(active))
            try:
                return original_execute(plan)
            finally:
                active.pop()

        service.execute_plan = tracked_execute
        threads = [threading.Thread(target=service.run_due) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, max(max_active))

    def test_result_save_failure_does_not_block_other_plans(self):
        """单个结果持久化失败不阻止后续计划执行。"""
        key2 = downloader_key("qbittorrent", "QB2")
        instance1 = FakeInstance([
            {"hash": "A", "state": "pausedDL", "progress": 0.5},
        ])
        instance2 = FakeInstance([
            {"hash": "B", "state": "pausedDL", "progress": 0.5},
        ])
        helper = FakeHelper({
            "QB": FakeService("QB", "qbittorrent", instance1),
            "QB2": FakeService("QB2", "qbittorrent", instance2),
        })
        config = {
            schedule_field(self.KEY, "start"): "2026-10-27T08:00",
            schedule_field(key2, "start"): "2026-10-27T09:00",
        }
        registry = {
            self.KEY: {"name": "QB", "type": "qbittorrent"},
            key2: {"name": "QB2", "type": "qbittorrent"},
        }
        service = DownloaderScheduleService(
            helper=helper,
            config=config,
            registry=registry,
            results={},
            now_fn=lambda: NOW,
            timezone=TZ,
            persist_config=lambda value: None,
            save_registry=lambda value: None,
            save_results=lambda value: (_ for _ in ()).throw(
                RuntimeError("result storage failed")
            ),
        )

        results = service.run_due()

        self.assertEqual(2, len(results))
        self.assertEqual([["a"]], instance1.started)
        self.assertEqual([["b"]], instance2.started)

    def test_successful_action_does_not_retry_when_config_save_fails(self):
        """已执行成功的计划不会因配置清理失败而重复执行。"""
        instance = FakeInstance([
            {"hash": "A", "state": "pausedDL", "progress": 0.5},
        ])
        config = {
            schedule_field(self.KEY, "start"): "2026-10-27T08:00",
        }

        def fail_persist(value):
            """模拟配置持久化失败。"""
            raise RuntimeError("config storage failed")

        service = DownloaderScheduleService(
            helper=FakeHelper({
                "QB": FakeService("QB", "qbittorrent", instance),
            }),
            config=config,
            registry={
                self.KEY: {"name": "QB", "type": "qbittorrent"},
            },
            results={},
            now_fn=lambda: NOW,
            timezone=TZ,
            persist_config=fail_persist,
            save_registry=lambda value: None,
            save_results=lambda value: None,
        )

        first = service.run_due()
        second = service.run_due()

        self.assertTrue(first[0]["success"])
        self.assertEqual([], second)
        self.assertEqual([["a"]], instance.started)
        self.assertIn(schedule_field(self.KEY, "start"), config)


class PluginTests(unittest.TestCase):
    """验证动态配置页、状态页和 MoviePilot 服务。"""

    KEY = "c70ff5f613c1"

    def setUp(self):
        """安装下载器帮助类桩。"""
        self.original_helper = downloadertaskmanager.DownloaderHelper
        self.instance = FakeInstance([
            {"hash": "A", "state": "pausedDL", "progress": 0.5},
        ])
        self.helper = FakeHelper({
            "QB": FakeService("QB", "qbittorrent", self.instance),
        })
        downloadertaskmanager.DownloaderHelper = lambda: self.helper

    def tearDown(self):
        """恢复下载器帮助类。"""
        downloadertaskmanager.DownloaderHelper = self.original_helper

    def _plugin(self, config=None, enabled=True):
        """构造插件。"""
        plugin = DownloaderTaskManager()
        plugin.init_plugin({
            "enabled": enabled,
            **(config or {}),
        })
        return plugin

    def test_version_form_and_removed_api(self):
        """版本、动态配置字段和接口移除符合规格。"""
        plugin = self._plugin({
            schedule_field(self.KEY, "start"): "2000-01-01T00:00",
        })
        form, defaults = plugin.get_form()
        components = list(_walk_components(form))
        date_fields = [
            node for node in components
            if node.get("component") == "VTextField"
            and (node.get("props") or {}).get("type") == "datetime-local"
        ]

        self.assertEqual("1.1.2", plugin.plugin_version)
        self.assertEqual(2, len(date_fields))
        self.assertIn(schedule_field(self.KEY, "start"), defaults)
        self.assertEqual([], plugin.get_api())
        self.assertEqual([], plugin.get_command())

    def test_form_keeps_legacy_schedule_defaults(self):
        """隐藏的遗留计划保留在表单默认值中。"""
        legacy_key = downloader_key("transmission", "Missing")
        legacy_field = schedule_field(legacy_key, "start")
        plugin = self._plugin({
            legacy_field: "2026-10-27T09:00",
        })

        _, defaults = plugin.get_form()

        self.assertEqual("2026-10-27T09:00", defaults[legacy_field])

    def test_service_registration_and_check(self):
        """计划注册为精确 date 服务，并保留五分钟重试服务。"""
        plugin = self._plugin({
            schedule_field(self.KEY, "start"): "2099-10-27T09:00",
        })
        services = plugin.get_service()
        called = []
        plugin._schedule_service.retry_due = lambda: called.append(True)

        plugin.check_retries()

        date_services = [
            service for service in services
            if service["trigger"] == "date"
        ]
        retry_services = [
            service for service in services
            if service["trigger"] == "interval"
        ]
        self.assertEqual(1, len(date_services))
        self.assertEqual(1, len(retry_services))
        self.assertEqual(30, retry_services[0]["kwargs"]["seconds"])
        self.assertIsInstance(
            date_services[0]["kwargs"]["run_date"],
            datetime,
        )
        self.assertEqual(
            "2099-10-27T09:00",
            plugin._schedule_service.list_plans()[0]["scheduled_text"],
        )
        self.assertEqual([True], called)
        self.assertEqual([], self._plugin(enabled=False).get_service())

    def test_date_service_executes_bound_plan(self):
        """date 服务直接执行对应下载器和动作。"""
        plugin = self._plugin({
            schedule_field(self.KEY, "start"): "2000-01-01T00:00",
        })
        service = next(
            item for item in plugin.get_service()
            if item["trigger"] == "date"
        )

        service["func"](job_id="scheduler-job")

        self.assertEqual([["a"]], self.instance.started)

    def test_page_has_no_torrent_rows_and_shows_plan_status(self):
        """状态页不显示种子，只显示计划和结果。"""
        plugin = self._plugin({
            schedule_field(self.KEY, "start"): "2099-10-27T11:00",
        })
        page = plugin.get_page()
        components = list(_walk_components(page))
        text = "\n".join(_component_text(node) for node in components)

        self.assertFalse(any(
            node.get("component") == "VTable"
            for node in components
        ))
        self.assertNotIn("task-name", text)
        self.assertIn("QB", text)
        self.assertIn("已计划", text)

    def test_disabled_page_and_legacy_migration(self):
        """禁用提示和旧配置迁移生效。"""
        plugin = self._plugin({
            "allow_bulk_actions": True,
        }, enabled=False)
        page = plugin.get_page()
        text = "\n".join(
            _component_text(node)
            for node in _walk_components(page)
        )

        self.assertNotIn("allow_bulk_actions", plugin.updated_config)
        self.assertIn("插件未启用", text)

    def test_schedule_registry_and_results_persist(self):
        """注册表和结果写入插件数据。"""
        plugin = self._plugin({
            schedule_field(self.KEY, "start"): "2000-01-01T00:00",
        })
        plugin.check_schedules()

        self.assertIn(self.KEY, plugin.saved_data["schedule_registry"])
        self.assertIn("start", plugin.saved_data["schedule_results"][self.KEY])


class PackageTests(unittest.TestCase):
    """验证市场元数据和文档。"""

    def test_package_and_readme(self):
        """版本保持同步且 README 描述定时功能。"""
        package = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
        metadata = package["DownloaderTaskManager"]
        readme = (ROOT / "plugins.v2" / "downloadertaskmanager" / "README.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual("1.1.2", metadata["version"])
        self.assertEqual(DownloaderTaskManager.plugin_version, metadata["version"])
        self.assertIn("v1.1.0", metadata["history"])
        self.assertIn("BrushFlowLowFreq", package)
        self.assertIn("一次", readme)
        self.assertIn("不展示种子", readme)


if __name__ == "__main__":
    unittest.main()
