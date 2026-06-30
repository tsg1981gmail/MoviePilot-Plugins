import importlib.util
import hashlib
import json
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace


def _install_module(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def _install_moviepilot_stubs():
    pytz = _install_module("pytz")
    pytz.timezone = lambda name: None

    app = _install_module("app")
    schemas = _install_module("app.schemas")
    app.schemas = schemas

    class DownloaderInfo:
        def __init__(self):
            self.download_speed = 0
            self.upload_speed = 0
            self.download_size = 0
            self.upload_size = 0

    schemas.DownloaderInfo = DownloaderInfo
    schemas.NotificationType = type("NotificationType", (), {})
    schemas.TorrentInfo = type("TorrentInfo", (), {})
    schemas.MediaType = type("MediaType", (), {})
    schemas.ServiceInfo = type("ServiceInfo", (), {})

    helper = _install_module("app.helper")
    helper_sites = _install_module("app.helper.sites")
    helper_sites.SitesHelper = type("SitesHelper", (), {})
    helper_downloader = _install_module("app.helper.downloader")
    helper_downloader.DownloaderHelper = type("DownloaderHelper", (), {})
    app.helper = helper

    core = _install_module("app.core")
    core_config = _install_module("app.core.config")
    core_config.settings = SimpleNamespace(TORRENT_TAG="MOVIEPILOT", TZ="Asia/Shanghai", PROXY=None)
    core_context = _install_module("app.core.context")
    core_context.MediaInfo = type("MediaInfo", (), {})
    core_metainfo = _install_module("app.core.metainfo")
    core_metainfo.MetaInfo = type("MetaInfo", (), {})
    app.core = core

    db = _install_module("app.db")
    db_site_oper = _install_module("app.db.site_oper")
    db_site_oper.SiteOper = type("SiteOper", (), {})
    db_subscribe_oper = _install_module("app.db.subscribe_oper")
    db_subscribe_oper.SubscribeOper = type("SubscribeOper", (), {})
    app.db = db

    chain = _install_module("app.chain")
    chain_torrents = _install_module("app.chain.torrents")
    chain_torrents.TorrentsChain = type("TorrentsChain", (), {})
    app.chain = chain

    log_module = _install_module("app.log")

    class Logger:
        def __init__(self):
            self.debug_messages = []
            self.info_messages = []
            self.warning_messages = []
            self.error_messages = []

        def debug(self, *args, **kwargs):
            self.debug_messages.append(" ".join(str(arg) for arg in args))

        def info(self, *args, **kwargs):
            self.info_messages.append(" ".join(str(arg) for arg in args))

        def warning(self, *args, **kwargs):
            self.warning_messages.append(" ".join(str(arg) for arg in args))

        def error(self, *args, **kwargs):
            self.error_messages.append(" ".join(str(arg) for arg in args))

    log_module.logger = Logger()
    app.log = log_module

    modules = _install_module("app.modules")
    qbittorrent = _install_module("app.modules.qbittorrent")
    qbittorrent.Qbittorrent = type("Qbittorrent", (), {})
    transmission = _install_module("app.modules.transmission")
    transmission.Transmission = type("Transmission", (), {})
    app.modules = modules

    plugins = _install_module("app.plugins")

    class PluginBase:
        def update_config(self, *args, **kwargs):
            pass

    plugins._PluginBase = PluginBase
    app.plugins = plugins

    schemas_types = _install_module("app.schemas.types")
    schemas_types.EventType = type("EventType", (), {"PluginTriggered": "PluginTriggered"})

    utils = _install_module("app.utils")
    utils_http = _install_module("app.utils.http")
    utils_http.RequestUtils = type("RequestUtils", (), {})
    utils_string = _install_module("app.utils.string")
    utils_string.StringUtils = type("StringUtils", (), {
        "str_filesize": staticmethod(lambda value: str(value)),
        "str_to_timestamp": staticmethod(lambda value: None),
        "generate_random_str": staticmethod(lambda length: "RANDOMTAG"),
        "get_url_domain": staticmethod(lambda value: value),
    })
    app.utils = utils

    apscheduler = _install_module("apscheduler")
    schedulers = _install_module("apscheduler.schedulers")
    background = _install_module("apscheduler.schedulers.background")
    background.BackgroundScheduler = type("BackgroundScheduler", (), {})
    triggers = _install_module("apscheduler.triggers")
    cron = _install_module("apscheduler.triggers.cron")
    cron.CronTrigger = type("CronTrigger", (), {"from_crontab": staticmethod(lambda *args, **kwargs: None)})
    apscheduler.schedulers = schedulers
    apscheduler.triggers = triggers


def _load_plugin_module():
    _install_moviepilot_stubs()
    plugin_path = Path(__file__).resolve().parents[1] / "plugins.v2" / "brushflowlowfreq" / "__init__.py"
    spec = importlib.util.spec_from_file_location("brushflowlowfreq_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BrushFlowLowFreqFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_plugin_module()

    def _new_plugin(self, config):
        plugin = self.module.BrushFlowLowFreq()
        plugin._brush_config = self.module.BrushConfig(config)
        return plugin

    @staticmethod
    def _attach_memory_store(plugin, initial=None):
        store = dict(initial or {})
        plugin.get_data = lambda key, *args: store.get(key)
        plugin.save_data = lambda key, value, *args: store.__setitem__(key, value)
        return store

    def _new_qb_plugin(self, config=None, downloader=None):
        plugin = self._new_plugin({
            "downloader": "qb",
            "freeleech": "",
            "hr": "no",
            "notify": False,
            **(config or {}),
        })

        class FakeHelper:
            def __init__(self, instance):
                self.instance = instance

            def get_service(self, name):
                return SimpleNamespace(
                    name="qbittorrent",
                    instance=self.instance,
                )

            def is_downloader(self, name, service=None):
                return name == "qbittorrent"

        class FakeDownloader:
            def is_inactive(self):
                return False

        plugin.downloader_helper = FakeHelper(downloader or FakeDownloader())
        return plugin

    def test_plugin_version_matches_package_manifest(self):
        package_path = Path(__file__).resolve().parents[1] / "package.v2.json"
        package_info = json.loads(package_path.read_text())

        self.assertEqual(
            package_info["BrushFlowLowFreq"]["version"],
            self.module.BrushFlowLowFreq.plugin_version,
        )

    @staticmethod
    def _free_torrent_task():
        return {
            "site": 1,
            "page_url": "details.php?id=1",
            "site_name": "站点1",
            "title": "free torrent",
            "description": "free",
            "downloadvolumefactor": 0,
            "freedate": "",
            "freedate_diff": "",
        }

    def test_free_remaining_skip_range_bypasses_download_filter(self):
        now = datetime.now()
        start = now - timedelta(minutes=1)
        end = now + timedelta(minutes=1)
        skip_range = f"{start:%H:%M}-{end:%H:%M}"
        plugin = self._new_plugin({
            "free_remaining_time": 120,
            "free_remaining_time_skip_range": skip_range,
        })
        torrent = SimpleNamespace(
            site_name="站点1",
            title="free torrent",
            description="free",
            page_url="details.php?id=1",
            pubdate="",
            downloadvolumefactor=0,
            freedate="",
            freedate_diff="10分钟",
            hit_and_run=False,
            size=10 * 1024 ** 3,
            seeders=1,
        )

        passed, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_brush(torrent=torrent, torrent_tasks={})

        self.assertTrue(passed, reason)

    def test_no_free_delete_uses_remaining_minutes_threshold(self):
        plugin = self._new_plugin({
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
        })

        def fake_detail_page(*, site_id, page_url):
            return "<a href='download.php?id=1'>下载</a>优惠剩余时间：4分钟", ""

        plugin._BrushFlowLowFreq__get_torrent_detail_page_text = fake_detail_page
        torrent_task = self._free_torrent_task()

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_no_free_condition_for_delete(
            site_name="站点1",
            torrent_task=torrent_task,
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("不足 5", reason)

    def test_no_free_delete_skips_when_detail_page_cannot_be_judged(self):
        plugin = self._new_plugin({
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
        })
        start_info_count = len(self.module.logger.info_messages)
        cases = [
            ("request_failed", None, "请求详情页失败"),
            ("login_page", "<form action='login.php'><input name='username'></form>", ""),
            ("captcha_page", "<html><body>captcha 验证</body></html>", ""),
            ("not_detail_page", "<html><body>ordinary page</body></html>", ""),
        ]

        for case_name, page_text, error_reason in cases:
            with self.subTest(case_name=case_name):
                plugin._BrushFlowLowFreq__get_torrent_detail_page_text = (
                    lambda *, site_id, page_url, page_text=page_text, error_reason=error_reason:
                    (page_text, error_reason)
                )

                should_delete, reason = plugin._BrushFlowLowFreq__evaluate_no_free_condition_for_delete(
                    site_name="站点1",
                    torrent_task=self._free_torrent_task(),
                )

                self.assertFalse(should_delete, reason)
                self.assertTrue(reason.startswith("失去免费删种检测跳过"), reason)

        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertTrue(any("失去免费删种检测跳过" in msg for msg in new_logs), new_logs)

    def test_no_free_delete_removes_detail_page_without_free_marker(self):
        plugin = self._new_plugin({
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
        })

        def fake_detail_page(*, site_id, page_url):
            return "<a href='download.php?id=1'>下载</a><h1 id='top'>normal torrent</h1>", ""

        plugin._BrushFlowLowFreq__get_torrent_detail_page_text = fake_detail_page

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_no_free_condition_for_delete(
            site_name="站点1",
            torrent_task=self._free_torrent_task(),
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("已不免费", reason)

    def test_completed_torrents_use_legacy_434_ratio_delete_rule(self):
        plugin = self._new_plugin({
            "seed_ratio": 1.0,
        })
        torrent_info = {
            "seeding_time": 3600,
            "ratio": 2.0,
            "uploaded": 0,
            "downloaded": 100,
            "total_size": 100,
            "dltime": 0,
            "avg_upspeed": 0,
            "iatime": 0,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task={"site_name": "站点1", "time": 0},
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("分享率", reason)

    def test_completed_torrents_use_legacy_434_upload_size_delete_rule(self):
        plugin = self._new_plugin({
            "seed_size": 1,
        })
        torrent_info = {
            "seeding_time": 3600,
            "ratio": 0,
            "uploaded": 2 * 1024 ** 3,
            "downloaded": 100,
            "total_size": 100,
            "dltime": 0,
            "avg_upspeed": 0,
            "iatime": 0,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task={"site_name": "站点1", "time": 0},
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("上传量", reason)

    def test_no_free_delete_is_not_part_of_legacy_434_common_delete_flow(self):
        plugin = self._new_plugin({
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
        })

        def fake_detail_page(*, site_id, page_url):
            return "<a href='download.php?id=1'>下载</a><h1 id='top'>normal torrent</h1>", ""

        plugin._BrushFlowLowFreq__get_torrent_detail_page_text = fake_detail_page
        torrent_info = {
            "seeding_time": 3600,
            "ratio": 0,
            "uploaded": 0,
            "downloaded": 100,
            "total_size": 100,
            "dltime": 0,
            "avg_upspeed": 0,
            "iatime": 0,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task=self._free_torrent_task(),
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("未能满足设置的删除条件", reason)

    def test_check_deletes_torrent_after_free_ends(self):
        class FakeQbc:
            def __init__(self):
                self.reannounced = []

            def torrents_reannounce(self, torrent_hashes):
                self.reannounced.append(torrent_hashes)

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()
                self.deleted = []
                self.torrents = [{
                    "hash": "abcdef",
                    "name": "free ending torrent",
                    "tags": "刷流",
                    "state": "seeding",
                    "progress": 1.0,
                    "downloaded": 100,
                    "uploaded": 0,
                    "total_size": 100,
                    "ratio": 0,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                    "downloadvolumefactor": 0,
                    "freedate": "",
                    "freedate_diff": "10分钟",
                }]

            def is_inactive(self):
                return False

            def get_torrents(self):
                return list(self.torrents), None

            def delete_torrents(self, ids, delete_file=True):
                self.deleted = ids
                self.delete_file = delete_file
                self.torrents = [torrent for torrent in self.torrents if torrent.get("hash") not in ids]
                return True

        plugin = self._new_qb_plugin({
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.subscribe_oper = SimpleNamespace(list=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        plugin._BrushFlowLowFreq__get_torrent_detail_page_text = (
            lambda *, site_id, page_url: (
                "<a href='download.php?id=1'>下载</a><h1 id='top'>normal torrent</h1>",
                ""
            )
        )
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "free ending torrent",
                "description": "desc",
                "page_url": "details.php?id=1",
                "time": 0,
                "downloaded": 100,
                "uploaded": 0,
                "total_size": 100,
                "ratio": 0,
                "seeding_time": 3600,
                "hit_and_run": False,
                "freedate": "",
                "freedate_diff": "10分钟",
                "downloadvolumefactor": 0,
                "deleted": False,
                "first_downloaded_time": 1,
                "first_uploaded_time": 1,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 0,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {},
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None

        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual(["abcdef"], plugin.downloader.deleted)
        self.assertTrue(plugin.downloader.delete_file)
        self.assertTrue(torrent_tasks["abcdef"].get("deleted"))
        self.assertIn("已不免费", "".join(self.module.logger.info_messages))

    def test_legacy_434_allows_seed_time_for_seeding_torrents(self):
        plugin = self._new_plugin({
            "seed_time": 1,
            "seed_ratio": 1.0,
        })
        torrent_info = {
            "seeding_time": 7200,
            "ratio": 0,
            "uploaded": 0,
            "downloaded": 100,
            "total_size": 100,
            "dltime": 0,
            "avg_upspeed": 0,
            "iatime": 0,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task={"site_name": "站点1", "time": 0},
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("做种时间", reason)

    def test_legacy_434_keeps_download_timeout_for_incomplete_torrents(self):
        plugin = self._new_plugin({
            "download_time": 1,
        })
        torrent_info = {
            "seeding_time": 0,
            "ratio": 0,
            "uploaded": 0,
            "downloaded": 50,
            "total_size": 100,
            "dltime": 7200,
            "avg_upspeed": 0,
            "iatime": 0,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task={"site_name": "站点1", "time": 0},
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("下载耗时", reason)

    def test_downloading_torrent_uses_legacy_434_delete_rules_without_upload_protection_overlap(self):
        plugin = self._new_plugin({
            "seed_time": 1,
            "seed_size": 1,
            "seed_avgspeed": 100,
            "seed_inactivetime": 1,
        })
        torrent_info = {
            "seeding_time": 0,
            "ratio": 0,
            "uploaded": 2 * 1024 ** 3,
            "downloaded": 50,
            "total_size": 100,
            "dltime": 0,
            "avg_upspeed": 0,
            "iatime": 3600,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task={"site_name": "站点1", "time": 0, "hit_and_run": False},
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("上传量", reason)

    def test_hash_normalization_prevents_case_sensitive_missing_detection(self):
        plugin = self._new_qb_plugin()
        torrent_tasks = {
            "ABCDEF": {
                "site_name": "站点1",
                "title": "case torrent",
                "description": "",
                "deleted": False,
            }
        }

        plugin._BrushFlowLowFreq__update_undeleted_torrents_missing_in_downloader(
            torrent_tasks=torrent_tasks,
            torrent_check_hashes=["ABCDEF"],
            torrents=[{"hash": "abcdef"}],
        )

        self.assertFalse(torrent_tasks["ABCDEF"].get("deleted"), torrent_tasks)

    def test_normalize_hash_keys_merges_duplicate_case_variants(self):
        plugin = self._new_qb_plugin()
        torrent_tasks = {
            "ABCDEF": {
                "site_name": "站点1",
                "title": "original",
                "page_url": "details.php?id=1",
                "deleted": False,
                "downloaded": 0,
            },
            "abcdef": {
                "site_name": "tracker.example",
                "title": "from downloader",
                "deleted": False,
                "downloaded": 100,
                "total_size": 1000,
            },
        }

        plugin._BrushFlowLowFreq__normalize_task_hash_keys(torrent_tasks)

        self.assertEqual(["abcdef"], list(torrent_tasks.keys()))
        self.assertEqual("details.php?id=1", torrent_tasks["abcdef"].get("page_url"))
        self.assertEqual(100, torrent_tasks["abcdef"].get("downloaded"))
        self.assertFalse(torrent_tasks["abcdef"].get("deleted"))

    def test_yield_guard_numeric_defaults_are_disabled_and_configurable(self):
        brush_config = self.module.BrushConfig({})

        self.assertFalse(brush_config.yield_guard_enabled)
        self.assertEqual(2048, brush_config.yield_guard_high_download_kbs)
        self.assertEqual(200, brush_config.yield_guard_low_upload_kbs)
        self.assertEqual(8, brush_config.yield_guard_low_ratio_percent)
        self.assertEqual(500, brush_config.yield_guard_ratio_min_download_kbs)
        self.assertEqual(0, brush_config.yield_guard_ratio_protect_upload_kbs)
        self.assertEqual(2, brush_config.yield_guard_bad_checks)
        self.assertEqual(2, brush_config.yield_guard_min_downloaded_gb)
        self.assertEqual(10, brush_config.yield_guard_min_progress_percent)
        self.assertEqual(512, brush_config.yield_guard_download_limit_kbs)
        self.assertEqual(10, brush_config.yield_guard_fast_fail_minutes)
        self.assertEqual(500, brush_config.yield_guard_good_upload_kbs)
        self.assertEqual(500, brush_config.yield_guard_good_avg_upload_kbs)
        self.assertTrue(brush_config.yield_guard_stop_brush_when_good_pool)
        self.assertEqual(2, brush_config.yield_guard_good_pool_min_count)
        self.assertEqual(1, brush_config.yield_guard_probe_slots)
        self.assertEqual(10, brush_config.yield_guard_probe_interval_minutes)
        self.assertTrue(brush_config.yield_guard_bandwidth_arbitration_enabled)
        self.assertEqual(85, brush_config.yield_guard_high_pressure_percent)
        self.assertEqual(45, brush_config.yield_guard_idle_pressure_percent)
        self.assertEqual(2, brush_config.yield_guard_idle_release_checks)
        self.assertEqual(1024, brush_config.yield_guard_relax_download_limit_kbs)
        self.assertEqual(2048, brush_config.yield_guard_half_open_download_limit_kbs)
        self.assertEqual(15, brush_config.yield_guard_promising_pubtime_minutes)
        self.assertEqual("auto", brush_config.yield_guard_pressure_strategy)
        self.assertEqual("auto", brush_config.yield_guard_small_pool_brush_strategy)
        self.assertTrue(brush_config.yield_guard_rehearsal)
        self.assertFalse(brush_config.yield_guard_detail_log)

    def test_log_mode_defaults_to_full(self):
        brush_config = self.module.BrushConfig({})

        self.assertEqual("full", brush_config.log_mode)

    def test_log_mode_unknown_values_fall_back_to_full(self):
        brush_config = self.module.BrushConfig({"log_mode": "unexpected"})

        self.assertEqual("full", brush_config.log_mode)

    def test_summary_log_mode_does_not_change_task_decision_output(self):
        full_plugin = self._new_plugin({
            "brushsites": ["站点1"],
            "freeleech": "free",
            "hr": "no",
            "include": "",
            "exclude": "",
            "log_mode": "full",
        })
        summary_plugin = self._new_plugin({
            "brushsites": ["站点1"],
            "freeleech": "free",
            "hr": "no",
            "include": "",
            "exclude": "",
            "log_mode": "summary",
        })
        torrent = SimpleNamespace(
            site_name="站点1",
            title="free torrent",
            description="free",
            page_url="details.php?id=1",
            pubdate="",
            downloadvolumefactor=0,
            freedate="",
            freedate_diff="10分钟",
            hit_and_run=False,
            size=10 * 1024 ** 3,
            seeders=1,
        )

        full_result = full_plugin._BrushFlowLowFreq__evaluate_conditions_for_brush(torrent=torrent, torrent_tasks={})
        summary_result = summary_plugin._BrushFlowLowFreq__evaluate_conditions_for_brush(torrent=torrent, torrent_tasks={})

        self.assertEqual(full_result, summary_result)

    def test_summary_log_mode_suppresses_routine_logs_but_keeps_key_events(self):
        plugin = self._new_qb_plugin({
            "log_mode": "summary",
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
            "freeleech": "",
            "hr": "no",
            "upload_protection_enabled": True,
            "upload_protection_detail_log": False,
        })
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.subscribe_oper = SimpleNamespace(list=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        plugin._BrushFlowLowFreq__get_torrent_detail_page_text = (
            lambda *, site_id, page_url: ("<a href='download.php?id=1'>下载</a><h1 id='top'>normal torrent</h1>", "")
        )
        plugin._BrushFlowLowFreq__get_torrent_info = lambda torrent: {
            "title": torrent.get("name", ""),
            "total_size": torrent.get("total_size", 100),
            "downloaded": torrent.get("downloaded", 100),
            "uploaded": torrent.get("uploaded", 0),
            "ratio": torrent.get("ratio", 0),
            "seeding_time": torrent.get("seeding_time", 3600),
            "avg_upspeed": 0,
            "avg_downspeed": 0,
            "completion_on": 0,
            "add_on": 1,
        }
        torrent = {
            "hash": "abcdef",
            "name": "summary torrent",
            "tags": "刷流",
            "state": "downloading",
            "downloaded": 100,
            "uploaded": 0,
            "total_size": 100,
            "ratio": 0,
            "added_on": 1,
            "completion_on": 0,
            "last_activity": 1,
            "tracker": "tracker",
            "downloadvolumefactor": 0,
            "freedate": "",
            "freedate_diff": "10分钟",
        }
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "summary torrent",
                "description": "desc",
                "page_url": "details.php?id=1",
                "time": 0,
                "downloaded": 100,
                "uploaded": 0,
                "total_size": 100,
                "ratio": 0,
                "seeding_time": 3600,
                "hit_and_run": False,
                "freedate": "",
                "freedate_diff": "10分钟",
                "downloadvolumefactor": 0,
                "deleted": False,
                "first_downloaded_time": 1,
                "first_uploaded_time": 1,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 0,
            }
        }
        start_info_count = len(self.module.logger.info_messages)
        start_debug_count = len(self.module.logger.debug_messages)
        plugin._BrushFlowLowFreq__evaluate_no_free_condition_for_delete("站点1", torrent_tasks["abcdef"])
        plugin._BrushFlowLowFreq__delete_torrent_for_no_free([torrent], torrent_tasks, {})
        plugin._BrushFlowLowFreq__apply_upload_protection_actions([torrent], torrent_tasks, {})
        plugin._BrushFlowLowFreq__log_summary_routine("routine probe")
        plugin._BrushFlowLowFreq__log_summary_key("key probe")

        new_info_logs = self.module.logger.info_messages[start_info_count:]
        new_debug_logs = self.module.logger.debug_messages[start_debug_count:]
        self.assertFalse(any("自动归档未配置" in msg for msg in new_info_logs))
        self.assertFalse(any("没有开启排除订阅" in msg for msg in new_info_logs))
        self.assertFalse(any("失去免费删种评估" in msg for msg in new_info_logs))
        self.assertTrue(any("routine probe" in msg for msg in new_debug_logs))
        self.assertTrue(any("key probe" in msg for msg in new_info_logs))

    def test_silent_log_mode_keeps_key_events_but_hides_routine_logs(self):
        plugin = self._new_qb_plugin({
            "log_mode": "silent",
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
            "freeleech": "",
            "hr": "no",
        })
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        plugin._BrushFlowLowFreq__get_torrent_detail_page_text = (
            lambda *, site_id, page_url: ("<a href='download.php?id=1'>下载</a><h1 id='top'>normal torrent</h1>", "")
        )
        torrent_task = self._free_torrent_task()
        torrent_task["site_name"] = "站点1"
        torrent_task["site"] = 1

        start_info_count = len(self.module.logger.info_messages)
        plugin._BrushFlowLowFreq__evaluate_no_free_condition_for_delete("站点1", torrent_task)
        new_info_logs = self.module.logger.info_messages[start_info_count:]
        self.assertFalse(any("失去免费删种评估" in msg for msg in new_info_logs))
        self.assertFalse(any("失去免费删种检测跳过" in msg for msg in new_info_logs))

    def test_low_ratio_limit_options_default_disabled_and_configurable(self):
        default_config = self.module.BrushConfig({})
        custom_config = self.module.BrushConfig({
            "seed_ratio_limit_download_kbs": 256,
            "seed_ratio_limit_restore_upspeed_kbs": 128,
            "seed_ratio_limit_restore_count": 2,
        })

        self.assertEqual(0, default_config.seed_ratio_limit_download_kbs)
        self.assertEqual(0, default_config.seed_ratio_limit_restore_upspeed_kbs)
        self.assertEqual(3, default_config.seed_ratio_limit_restore_count)
        self.assertEqual(256, custom_config.seed_ratio_limit_download_kbs)
        self.assertEqual(128, custom_config.seed_ratio_limit_restore_upspeed_kbs)
        self.assertEqual(2, custom_config.seed_ratio_limit_restore_count)

    def test_completed_torrent_uses_legacy_434_min_ratio_rule_and_ignores_low_ratio_limit(self):
        plugin = self._new_qb_plugin({
            "seed_ratio_check_minutes": 30,
            "seed_ratio_min_30m": 0.5,
            "seed_ratio_limit_download_kbs": 256,
            "seed_ratio_limit_restore_upspeed_kbs": 100,
            "seed_ratio_limit_restore_count": 2,
            "interval_upspeed": "",
        })
        torrent_info = {
            "seeding_time": 3600,
            "ratio": 0.1,
            "uploaded": 100,
            "downloaded": 1000,
            "total_size": 1000,
            "dltime": 3600,
            "avg_upspeed": 0,
            "iatime": 0,
        }
        torrent_task = {
            "site_name": "站点1",
            "time": 0,
            "first_downloaded_time": 1,
            "first_uploaded_time": 1,
            "hit_and_run": False,
        }
        original_get_task_elapsed_minutes = plugin._BrushFlowLowFreq__get_task_elapsed_minutes
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
                site_name="站点1",
                torrent_info=torrent_info,
                torrent_task=torrent_task,
            )
        finally:
            plugin._BrushFlowLowFreq__get_task_elapsed_minutes = original_get_task_elapsed_minutes

        self.assertTrue(should_delete, reason)
        self.assertIn("做种30分钟后分享率", reason)
        self.assertIsNone(torrent_task.get("seed_ratio_once_checked"))
        self.assertIsNone(torrent_task.get("seed_ratio_limit_pending_action"))

    def test_low_ratio_limit_action_calls_qb_download_limit(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "seed_ratio_limit_download_kbs": 256,
        }, downloader=downloader)
        torrent_task = {
            "seed_ratio_limit_active": True,
            "seed_ratio_limit_pending_action": "limit",
        }

        applied = plugin._BrushFlowLowFreq__apply_seed_ratio_limit_action_for_task(
            torrent_hash="abcdef",
            torrent_task=torrent_task,
            brush_config=plugin._brush_config,
            site_name="站点1",
            reason="低分享率一次性检测未达标",
        )

        self.assertTrue(applied)
        self.assertEqual([(["abcdef"], 256 * 1024)], downloader.qbc.download_limits)
        self.assertIsNone(torrent_task.get("seed_ratio_limit_pending_action"))

    def test_completed_torrent_uses_legacy_434_rule_and_ignores_stale_yield_guard_runtime_stage(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "seed_ratio_check_minutes": 30,
            "seed_ratio_min_30m": 0.5,
            "seed_ratio_limit_download_kbs": 256,
        })
        torrent_info = {
            "seeding_time": 3600,
            "ratio": 0.1,
            "uploaded": 100,
            "downloaded": 1000,
            "total_size": 1000,
            "dltime": 3600,
            "avg_upspeed": 0,
            "iatime": 0,
        }
        torrent_task = {
            "site_name": "站点1",
            "first_downloaded_time": 1,
            "first_uploaded_time": 1,
            "yield_guard_evaluated_in_check": True,
            "yield_guard_should_delete": False,
            "yield_guard_good_protected": False,
            "yield_guard_stage": "limited",
            "yield_guard_last_reason": "上传收益保护：低收益，动作 limit",
        }
        original_get_task_elapsed_minutes = plugin._BrushFlowLowFreq__get_task_elapsed_minutes
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
                site_name="站点1",
                torrent_info=torrent_info,
                torrent_task=torrent_task,
            )
        finally:
            plugin._BrushFlowLowFreq__get_task_elapsed_minutes = original_get_task_elapsed_minutes

        self.assertTrue(should_delete, reason)
        self.assertIsNone(torrent_task.get("seed_ratio_limit_pending_action"))
        self.assertFalse(torrent_task.get("seed_ratio_limit_active"))
        self.assertIn("做种30分钟后分享率", reason)

    def test_low_ratio_pending_limit_does_not_evaluate_restore_before_action_applies(self):
        plugin = self._new_qb_plugin({
            "seed_ratio_limit_download_kbs": 256,
            "seed_ratio_limit_restore_upspeed_kbs": 100,
            "seed_ratio_limit_restore_count": 1,
        })
        torrent_task = {
            "seed_ratio_limit_active": False,
            "seed_ratio_limit_pending_action": "limit",
            "last_check_interval_upspeed": 120 * 1024,
            "last_check_interval_upspeed_valid": True,
        }

        restored, reason = plugin._BrushFlowLowFreq__evaluate_seed_ratio_limit_restore(
            brush_config=plugin._brush_config,
            torrent_task=torrent_task,
        )

        self.assertFalse(restored, reason)
        self.assertEqual("limit", torrent_task.get("seed_ratio_limit_pending_action"))
        self.assertEqual([], torrent_task.get("seed_ratio_limit_restore_hit_records", []))

    def test_low_ratio_limit_restores_after_consecutive_good_interval_uploads(self):
        plugin = self._new_qb_plugin({
            "seed_ratio_limit_download_kbs": 256,
            "seed_ratio_limit_restore_upspeed_kbs": 100,
            "seed_ratio_limit_restore_count": 2,
        })
        torrent_task = {
            "seed_ratio_limit_active": True,
            "seed_ratio_once_checked": True,
            "seed_ratio_once_passed": False,
            "last_check_interval_upspeed": 120 * 1024,
            "last_check_interval_upspeed_valid": True,
            "seed_ratio_limit_restore_hit_records": [1],
        }

        restored, reason = plugin._BrushFlowLowFreq__evaluate_seed_ratio_limit_restore(
            brush_config=plugin._brush_config,
            torrent_task=torrent_task,
        )

        self.assertTrue(restored, reason)
        self.assertEqual([1, 1], torrent_task.get("seed_ratio_limit_restore_hit_records"))
        self.assertEqual("restore_limit", torrent_task.get("seed_ratio_limit_pending_action"))
        self.assertIn("连续达标 2/2 次", reason)

    def test_yield_guard_site_config_values_are_ignored_after_upload_protection_rewrite(self):
        brush_config = self.module.BrushConfig({
            "yield_guard_enabled": True,
            "yield_guard_fast_fail_minutes": 12,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_ratio_protect_upload_kbs": 0,
            "yield_guard_pressure_strategy": "aggressive",
            "yield_guard_small_pool_brush_strategy": "strict",
            "yield_guard_detail_log": False,
            "enable_site_config": True,
            "site_config": '[{"sitename": "站点1", "yield_guard_fast_fail_minutes": 3, '
                           '"yield_guard_enabled": false, "yield_guard_low_ratio_percent": 5, '
                           '"yield_guard_ratio_min_download_kbs": 800, '
                           '"yield_guard_ratio_protect_upload_kbs": 200, '
                           '"yield_guard_pressure_strategy": "conservative", '
                           '"yield_guard_small_pool_brush_strategy": "aggressive", '
                           '"yield_guard_detail_log": true}]',
        })

        site_config = brush_config.get_site_config("站点1")
        self.assertTrue(site_config.yield_guard_enabled)
        self.assertEqual(12, site_config.yield_guard_fast_fail_minutes)
        self.assertEqual(8, site_config.yield_guard_low_ratio_percent)
        self.assertEqual(500, site_config.yield_guard_ratio_min_download_kbs)
        self.assertEqual(0, site_config.yield_guard_ratio_protect_upload_kbs)
        self.assertEqual("aggressive", site_config.yield_guard_pressure_strategy)
        self.assertEqual("strict", site_config.yield_guard_small_pool_brush_strategy)
        self.assertFalse(site_config.yield_guard_detail_log)
        self.assertEqual(12, brush_config.yield_guard_fast_fail_minutes)
        self.assertEqual(8, brush_config.yield_guard_low_ratio_percent)
        self.assertEqual(500, brush_config.yield_guard_ratio_min_download_kbs)
        self.assertEqual(0, brush_config.yield_guard_ratio_protect_upload_kbs)
        self.assertEqual("aggressive", brush_config.yield_guard_pressure_strategy)
        self.assertEqual("strict", brush_config.yield_guard_small_pool_brush_strategy)

    def test_update_config_drops_old_yield_guard_values(self):
        plugin = self._new_plugin({
            "enabled": True,
            "notify": False,
            "downloader": "qb",
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1024,
            "yield_guard_low_upload_kbs": 128,
            "yield_guard_low_ratio_percent": 6,
            "yield_guard_ratio_min_download_kbs": 600,
            "yield_guard_ratio_protect_upload_kbs": 200,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_first_action": "pause",
            "yield_guard_second_action": "delete",
            "yield_guard_final_action": "none",
            "yield_guard_download_limit_kbs": 256,
            "yield_guard_fast_fail_minutes": 3,
            "yield_guard_good_upload_kbs": 300,
            "yield_guard_good_avg_upload_kbs": 350,
            "yield_guard_protect_delete_rules": False,
            "yield_guard_stop_brush_when_good_pool": False,
            "yield_guard_good_pool_min_count": 4,
            "yield_guard_probe_slots": 2,
            "yield_guard_probe_interval_minutes": 5,
            "yield_guard_bandwidth_arbitration_enabled": True,
            "yield_guard_high_pressure_percent": 80,
            "yield_guard_idle_pressure_percent": 35,
            "yield_guard_idle_release_checks": 3,
            "yield_guard_relax_download_limit_kbs": 1024,
            "yield_guard_half_open_download_limit_kbs": 4096,
            "yield_guard_promising_pubtime_minutes": 6,
            "yield_guard_pressure_strategy": "competition",
            "yield_guard_small_pool_brush_strategy": "aggressive",
            "yield_guard_detail_log": True,
        })
        saved_config = {}
        plugin.update_config = lambda config: saved_config.update(config)

        plugin._BrushFlowLowFreq__update_config()

        removed_keys = {
            "yield_guard_enabled",
            "yield_guard_rehearsal",
            "yield_guard_high_download_kbs",
            "yield_guard_low_upload_kbs",
            "yield_guard_low_ratio_percent",
            "yield_guard_ratio_min_download_kbs",
            "yield_guard_ratio_protect_upload_kbs",
            "yield_guard_bad_checks",
            "yield_guard_min_downloaded_gb",
            "yield_guard_min_progress_percent",
            "yield_guard_first_action",
            "yield_guard_second_action",
            "yield_guard_final_action",
            "yield_guard_download_limit_kbs",
            "yield_guard_fast_fail_minutes",
            "yield_guard_good_upload_kbs",
            "yield_guard_good_avg_upload_kbs",
            "yield_guard_protect_delete_rules",
            "yield_guard_stop_brush_when_good_pool",
            "yield_guard_good_pool_min_count",
            "yield_guard_probe_slots",
            "yield_guard_probe_interval_minutes",
            "yield_guard_bandwidth_arbitration_enabled",
            "yield_guard_high_pressure_percent",
            "yield_guard_idle_pressure_percent",
            "yield_guard_idle_release_checks",
            "yield_guard_relax_download_limit_kbs",
            "yield_guard_half_open_download_limit_kbs",
            "yield_guard_promising_pubtime_minutes",
            "yield_guard_pressure_strategy",
            "yield_guard_small_pool_brush_strategy",
            "yield_guard_detail_log",
        }
        for key in removed_keys:
            with self.subTest(key=key):
                self.assertNotIn(key, saved_config)

    def test_update_config_logs_detailed_config_snapshot(self):
        plugin = self._new_plugin({
            "enabled": True,
            "notify": False,
            "downloader": "qb",
            "upload_protection_enabled": True,
            "upload_protection_rehearsal": True,
            "yield_guard_enabled": True,
        })
        plugin.update_config = lambda config: None
        start_info_count = len(self.module.logger.info_messages)

        plugin._BrushFlowLowFreq__update_config()

        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertTrue(any("插件配置快照[配置写回]" in msg for msg in new_logs), new_logs)
        joined_logs = "\n".join(new_logs)
        self.assertIn('"upload_protection_enabled": true', joined_logs)
        self.assertIn('"yield_guard_enabled": true', joined_logs)
        self.assertIn('"site_config_count": 0', joined_logs)

    def test_validate_and_fix_config_reports_invalid_yield_guard_values(self):
        plugin = self._new_plugin({"enabled": True})
        plugin.systemmessage = SimpleNamespace(put=lambda *args, **kwargs: None)
        config = {
            "yield_guard_high_download_kbs": "fast",
            "yield_guard_low_ratio_percent": "bad",
            "yield_guard_ratio_min_download_kbs": "slow",
            "yield_guard_ratio_protect_upload_kbs": "medium",
            "yield_guard_bad_checks": "twice",
            "yield_guard_first_action": "throttle",
            "yield_guard_final_action": "remove",
            "yield_guard_pressure_strategy": "random",
            "yield_guard_small_pool_brush_strategy": "always",
        }
        start_error_count = len(self.module.logger.error_messages)

        valid = plugin._BrushFlowLowFreq__validate_and_fix_config(config=config)

        self.assertFalse(valid)
        self.assertIsNone(config.get("yield_guard_high_download_kbs"))
        self.assertIsNone(config.get("yield_guard_low_ratio_percent"))
        self.assertIsNone(config.get("yield_guard_ratio_min_download_kbs"))
        self.assertIsNone(config.get("yield_guard_ratio_protect_upload_kbs"))
        self.assertIsNone(config.get("yield_guard_bad_checks"))
        self.assertEqual("limit", config.get("yield_guard_first_action"))
        self.assertEqual("delete", config.get("yield_guard_final_action"))
        self.assertEqual("auto", config.get("yield_guard_pressure_strategy"))
        self.assertEqual("auto", config.get("yield_guard_small_pool_brush_strategy"))
        new_errors = self.module.logger.error_messages[start_error_count:]
        self.assertTrue(any("收益保护高下载阈值" in msg for msg in new_errors))
        self.assertTrue(any("收益保护低收益比阈值" in msg for msg in new_errors))
        self.assertTrue(any("收益比判断最小下载速度" in msg for msg in new_errors))
        self.assertTrue(any("收益比保护上传阈值" in msg for msg in new_errors))
        self.assertTrue(any("低收益首次动作" in msg for msg in new_errors))
        self.assertTrue(any("上传收益保护压力策略" in msg for msg in new_errors))
        self.assertTrue(any("任务少时新增策略" in msg for msg in new_errors))

    def test_new_torrent_task_initializes_yield_guard_fields(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def add_torrent(self, **kwargs):
                return True

            def get_torrent_id_by_tag(self, tags):
                return "ABCDEF"

        plugin = self._new_qb_plugin(downloader=FakeDownloader())
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.site_oper = SimpleNamespace(get=lambda siteid: SimpleNamespace(id=siteid,
                                                                              name="站点1",
                                                                              domain="site1.test"))
        plugin.torrents_chain = SimpleNamespace(browse=lambda domain: [
            SimpleNamespace(
                site=1,
                site_name="站点1",
                site_proxy=False,
                site_cookie="",
                site_ua="ua",
                title="new torrent",
                description="desc",
                imdbid=None,
                page_url="details.php?id=1",
                pubdate="",
                date_elapsed=None,
                freedate="",
                uploadvolumefactor=1,
                downloadvolumefactor=1,
                hit_and_run=False,
                volume_factor="",
                freedate_diff="",
                enclosure="magnet:?xt=urn:btih:ABCDEF",
                size=1234,
                seeders=1,
            )
        ])

        torrent_tasks = {}
        statistic_info = {"count": 0}
        plugin._BrushFlowLowFreq__brush_site_torrents(
            siteid=1,
            torrent_tasks=torrent_tasks,
            statistic_info=statistic_info,
            subscribe_titles=set(),
        )

        task = torrent_tasks["abcdef"]
        self.assertIsNone(task.get("last_check_downloaded"))
        self.assertIsNone(task.get("last_check_interval_downloaded"))
        self.assertIsNone(task.get("last_check_interval_downspeed"))
        self.assertFalse(task.get("last_check_interval_downspeed_valid"))
        self.assertEqual([], task.get("yield_guard_bad_records"))
        self.assertEqual(0, task.get("yield_guard_bad_streak"))
        self.assertEqual("normal", task.get("yield_guard_stage"))
        self.assertIsNone(task.get("yield_guard_last_action_time"))
        self.assertIsNone(task.get("yield_guard_paused_time"))
        self.assertIsNone(task.get("yield_guard_last_probe_time"))
        self.assertFalse(task.get("yield_guard_good_protected"))
        self.assertFalse(task.get("yield_guard_promising_protected"))
        self.assertEqual(0, task.get("yield_guard_idle_release_streak"))
        self.assertEqual("none", task.get("yield_guard_release_level"))
        self.assertEqual("", task.get("yield_guard_last_reason"))

    def test_update_torrent_tasks_state_computes_interval_downspeed(self):
        plugin = self._new_qb_plugin()
        torrent = {
            "hash": "abcdef",
            "uploaded": 1000,
            "downloaded": 1000,
            "total_size": 10000,
            "ratio": 1,
            "seeding_time": 0,
            "dltime": 1,
            "avg_upspeed": 1000,
            "iatime": 0,
        }
        torrent_tasks = {
            "abcdef": {
                "last_check_time": 100,
                "last_check_uploaded": 100,
                "last_check_downloaded": 100,
                "first_downloaded_time": 1,
                "first_uploaded_time": 1,
            }
        }
        original_time = self.module.time.time
        self.module.time.time = lambda: 110
        try:
            plugin._BrushFlowLowFreq__update_torrent_tasks_state(
                torrents=[torrent],
                torrent_tasks=torrent_tasks,
            )
        finally:
            self.module.time.time = original_time

        task = torrent_tasks["abcdef"]
        self.assertEqual(900, task.get("last_check_interval_downloaded"))
        self.assertEqual(90, task.get("last_check_interval_downspeed"))
        self.assertTrue(task.get("last_check_interval_downspeed_valid"))
        self.assertEqual(1000, task.get("last_check_downloaded"))

    def test_update_torrent_tasks_state_rejects_download_regression_sample(self):
        plugin = self._new_qb_plugin()
        torrent = {
            "hash": "abcdef",
            "uploaded": 1000,
            "downloaded": 50,
            "total_size": 10000,
            "ratio": 1,
            "seeding_time": 0,
            "dltime": 1,
            "avg_upspeed": 1000,
            "iatime": 0,
        }
        torrent_tasks = {
            "abcdef": {
                "last_check_time": 100,
                "last_check_uploaded": 100,
                "last_check_downloaded": 100,
                "first_downloaded_time": 1,
                "first_uploaded_time": 1,
            }
        }
        original_time = self.module.time.time
        self.module.time.time = lambda: 110
        try:
            plugin._BrushFlowLowFreq__update_torrent_tasks_state(
                torrents=[torrent],
                torrent_tasks=torrent_tasks,
            )
        finally:
            self.module.time.time = original_time

        task = torrent_tasks["abcdef"]
        self.assertFalse(task.get("last_check_interval_downspeed_valid"))
        self.assertIsNone(task.get("last_check_interval_downspeed"))
        self.assertIn("下载量出现回退", task.get("last_check_interval_downspeed_reason"))

    def test_yield_guard_limit_action_is_selected_for_early_low_yield(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_fast_fail_minutes": 10,
        })
        torrent_info = {
            "seeding_time": 0,
            "ratio": 0.1,
            "uploaded": 100,
            "downloaded": 1000,
            "total_size": 2000,
            "dltime": 120,
            "avg_upspeed": 50,
            "iatime": 0,
            "last_check_interval_downspeed": 5 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 10 * 1024,
            "last_check_interval_upspeed_valid": True,
        }
        torrent_task = {
            "site_name": "站点1",
            "time": 0,
            "first_downloaded_time": 1,
            "first_uploaded_time": 1,
            "last_check_time": 0,
            "last_check_uploaded": 0,
            "last_check_downloaded": 0,
            "last_check_interval_downspeed": 5 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 10 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("未能满足设置的删除条件", reason)

    def test_yield_guard_good_protected_skips_low_ratio_delete(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_good_upload_kbs": 1,
            "yield_guard_protect_delete_rules": True,
            "seed_ratio_check_minutes": 0,
            "seed_ratio_min_30m": 0.5,
        })
        torrent_info = {
            "seeding_time": 0,
            "ratio": 0.1,
            "uploaded": 100,
            "downloaded": 1000,
            "total_size": 2000,
            "dltime": 120,
            "avg_upspeed": 2 * 1024,
            "iatime": 0,
            "last_check_interval_upspeed": 2 * 1024,
            "last_check_interval_upspeed_valid": True,
        }
        torrent_task = {
            "site_name": "站点1",
            "time": 0,
            "first_downloaded_time": 1,
            "first_uploaded_time": 1,
            "last_check_interval_upspeed": 2 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_good_protected": True,
            "yield_guard_promising_protected": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("未能满足设置的删除条件", reason)

    def test_completed_torrent_is_not_yield_guard_good_protected(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_good_upload_kbs": 1,
            "yield_guard_good_avg_upload_kbs": 1,
            "yield_guard_protect_delete_rules": True,
            "seed_ratio_check_minutes": 30,
            "seed_ratio_min_30m": 0.5,
        })
        torrent_info = {
            "seeding_time": 3600,
            "ratio": 0.1,
            "uploaded": 100 * 1024 * 1024,
            "downloaded": 1000,
            "total_size": 1000,
            "dltime": 3600,
            "avg_upspeed": 2 * 1024,
            "iatime": 0,
            "last_check_interval_upspeed": 2 * 1024,
            "last_check_interval_upspeed_valid": True,
        }
        torrent_task = {
            "site_name": "站点1",
            "time": 0,
            "first_downloaded_time": 1,
            "first_uploaded_time": 1,
            "last_check_interval_upspeed": 2 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }
        original_get_task_elapsed_minutes = plugin._BrushFlowLowFreq__get_task_elapsed_minutes
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
                site_name="站点1",
                torrent_info=torrent_info,
                torrent_task=torrent_task,
            )
        finally:
            plugin._BrushFlowLowFreq__get_task_elapsed_minutes = original_get_task_elapsed_minutes

        self.assertTrue(should_delete, reason)
        self.assertIn("做种30分钟后分享率", reason)
        self.assertFalse(torrent_task.get("yield_guard_good_protected"))

    def test_yield_guard_good_protected_resets_limited_stage_and_marks_limit_restore(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_good_upload_kbs": 1,
        })
        torrent_task = {
            "last_check_interval_upspeed": 2 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_stage": "limited",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "avg_upspeed": 0,
                "downloaded": 1000,
                "total_size": 2000,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("normal", torrent_task.get("yield_guard_stage"))
        self.assertTrue(torrent_task.get("yield_guard_restore_download_limit"))

    def test_yield_guard_disabled_ignores_stale_check_delete_cache(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": False,
            "seed_ratio": "",
            "seed_ratio_min_30m": "",
        })
        torrent_task = {
            "site_name": "站点1",
            "time": 0,
            "first_downloaded_time": 0,
            "first_uploaded_time": 0,
            "hit_and_run": False,
            "yield_guard_evaluated_in_check": True,
            "yield_guard_should_delete": True,
            "yield_guard_last_reason": "stale yield guard delete",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
            site_name="站点1",
            torrent_info={
                "seeding_time": 0,
                "ratio": 0,
                "uploaded": 0,
                "downloaded": 0,
                "total_size": 1000,
                "dltime": 0,
                "avg_upspeed": 0,
                "iatime": 0,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertNotEqual("stale yield guard delete", reason)

    def test_yield_guard_limited_task_restores_limit_when_low_yield_clears(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 1000,
            "yield_guard_low_upload_kbs": 300,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": 100,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 400 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 1,
            "yield_guard_stage": "limited",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 1000,
                "total_size": 10000,
                "avg_upspeed": 0,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("normal", torrent_task.get("yield_guard_stage"))
        self.assertTrue(torrent_task.get("yield_guard_restore_download_limit"))

    def test_yield_guard_limited_task_keeps_limit_when_ratio_only_barely_recovers(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": int(313.9 * 1024),
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": int(29.2 * 1024),
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 2,
            "yield_guard_stage": "limited",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 2 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 180 * 1024,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("保持限速", reason)
        self.assertEqual(0, torrent_task.get("yield_guard_bad_streak"))
        self.assertEqual("limited", torrent_task.get("yield_guard_stage"))
        self.assertFalse(torrent_task.get("yield_guard_restore_download_limit"))

    def test_yield_guard_limited_task_keeps_limit_when_only_download_drops_below_threshold(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 256,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 256,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_second_action": "pause",
        })
        torrent_task = {
            "last_check_interval_downspeed": int(246.3 * 1024),
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": int(1.0 * 1024),
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 2,
            "yield_guard_stage": "limited",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": int(7.7 * 1024 ** 3),
                "total_size": int(9.4 * 1024 ** 3),
                "avg_upspeed": 38 * 1024,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("低收益", reason)
        self.assertEqual("strict_limited", torrent_task.get("yield_guard_stage"))
        self.assertFalse(torrent_task.get("yield_guard_restore_download_limit"))

    def test_yield_guard_idle_bandwidth_releases_limited_task_one_step(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": 200 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 30 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 1,
            "yield_guard_stage": "limited",
            "yield_guard_idle_release_streak": 1,
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 5 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 80 * 1024,
            },
            torrent_task=torrent_task,
            yield_guard_bandwidth_state={"pressure": "idle", "usage_percent": 35.0},
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("下载带宽空闲", reason)
        self.assertEqual("relaxed_limited", torrent_task.get("yield_guard_stage"))
        self.assertEqual("relax_limit", torrent_task.get("yield_guard_pending_action"))
        self.assertEqual(2, torrent_task.get("yield_guard_idle_release_streak"))

    def test_yield_guard_high_pressure_rolls_relaxed_task_back_one_step(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": 100 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 20 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "relaxed_limited",
            "yield_guard_idle_release_streak": 3,
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 5 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 80 * 1024,
            },
            torrent_task=torrent_task,
            yield_guard_bandwidth_state={"pressure": "high", "usage_percent": 92.0},
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("下载带宽高压", reason)
        self.assertEqual("limited", torrent_task.get("yield_guard_stage"))
        self.assertEqual("limit", torrent_task.get("yield_guard_pending_action"))
        self.assertEqual(0, torrent_task.get("yield_guard_idle_release_streak"))

    def test_yield_guard_healthy_ratio_does_not_count_as_low_yield_when_upload_is_below_low_threshold(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": int(437.6 * 1024),
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": int(140.3 * 1024),
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 1,
            "yield_guard_stage": "normal",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 5 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 70 * 1024,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("未命中", reason)
        self.assertEqual(0, torrent_task.get("yield_guard_bad_streak"))
        self.assertEqual("normal", torrent_task.get("yield_guard_stage"))

    def test_yield_guard_persistent_low_ratio_moves_limited_task_to_strict_limit_before_pause(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_second_action": "pause",
        })
        torrent_task = {
            "last_check_interval_downspeed": 2 * 1024 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 20 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 2,
            "yield_guard_stage": "limited",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 5 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 30 * 1024,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("严格限速", reason)
        self.assertEqual("strict_limited", torrent_task.get("yield_guard_stage"))

    def test_yield_guard_strict_limited_task_pauses_after_persistent_near_zero_upload(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": 128 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 1 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 3,
            "yield_guard_stage": "strict_limited",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 5 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 5 * 1024,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("暂停", reason)
        self.assertEqual("paused", torrent_task.get("yield_guard_stage"))

    def test_yield_guard_paused_task_waits_for_pause_window_before_probe(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 10,
            "yield_guard_final_action": "delete",
        })
        torrent_task = {
            "first_downloaded_time": 1,
            "yield_guard_paused_time": 1000,
            "last_check_interval_downspeed": 0,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 0,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 2,
            "yield_guard_stage": "paused",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }
        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 5 * 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
                site_name="站点1",
                brush_config=plugin._brush_config,
                torrent_info={
                    "downloaded": 1000,
                    "total_size": 2000,
                    "avg_upspeed": 0,
                },
                torrent_task=torrent_task,
            )
        finally:
            self.module.time.time = original_time

        self.assertFalse(should_delete, reason)
        self.assertIn("尚未超过", reason)
        self.assertEqual("paused", torrent_task.get("yield_guard_stage"))
        self.assertFalse(torrent_task.get("yield_guard_probe_started", False))

    def test_yield_guard_paused_task_enters_probe_before_final_delete(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 1,
            "yield_guard_final_action": "delete",
        })
        torrent_task = {
            "first_downloaded_time": 1,
            "yield_guard_paused_time": 1000,
            "last_check_interval_downspeed": 0,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 0,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 2,
            "yield_guard_stage": "paused",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }
        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 2 * 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
                site_name="站点1",
                brush_config=plugin._brush_config,
                torrent_info={
                    "downloaded": 1000,
                    "total_size": 2000,
                    "avg_upspeed": 0,
                },
                torrent_task=torrent_task,
            )
        finally:
            self.module.time.time = original_time

        self.assertFalse(should_delete, reason)
        self.assertIn("恢复探测", reason)
        self.assertEqual("probing", torrent_task.get("yield_guard_stage"))
        self.assertTrue(torrent_task.get("yield_guard_probe_started"))
        self.assertEqual(1000 + 2 * 60, torrent_task.get("yield_guard_probe_started_time"))

    def test_yield_guard_probe_failure_waits_for_probe_window_before_final_delete(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 10,
            "yield_guard_final_action": "delete",
        })
        torrent_task = {
            "last_check_interval_downspeed": 128 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 1 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 3,
            "yield_guard_stage": "probing",
            "yield_guard_probe_started": True,
            "yield_guard_probe_started_time": 1000,
            "yield_guard_restore_download_limit": False,
        }
        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 5 * 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
                site_name="站点1",
                brush_config=plugin._brush_config,
                torrent_info={
                    "downloaded": 5 * 1024 ** 3,
                    "total_size": 20 * 1024 ** 3,
                    "avg_upspeed": 5 * 1024,
                },
                torrent_task=torrent_task,
            )
        finally:
            self.module.time.time = original_time

        self.assertFalse(should_delete, reason)
        self.assertIn("恢复探测中", reason)
        self.assertEqual("probing", torrent_task.get("yield_guard_stage"))

    def test_yield_guard_probe_failure_allows_final_delete_after_probe_window(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 10,
            "yield_guard_final_action": "delete",
        })
        torrent_task = {
            "last_check_interval_downspeed": 128 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 1 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 3,
            "yield_guard_stage": "probing",
            "yield_guard_probe_started": True,
            "yield_guard_probe_started_time": 1000,
            "yield_guard_restore_download_limit": False,
        }

        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 11 * 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
                site_name="站点1",
                brush_config=plugin._brush_config,
                torrent_info={
                    "downloaded": 5 * 1024 ** 3,
                    "total_size": 20 * 1024 ** 3,
                    "avg_upspeed": 5 * 1024,
                },
                torrent_task=torrent_task,
            )
        finally:
            self.module.time.time = original_time

        self.assertTrue(should_delete, reason)
        self.assertIn("探测失败", reason)

    def test_yield_guard_low_ratio_triggers_when_download_below_high_download_threshold(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 3500,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_fast_fail_minutes": 10,
        })
        torrent_task = {
            "first_downloaded_time": 1,
            "last_check_interval_downspeed": 925 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 37 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 5 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 0,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("低收益", reason)
        self.assertEqual("limited", torrent_task.get("yield_guard_stage"))

    def test_yield_guard_persistent_low_yield_triggers_even_when_current_download_is_low(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_good_avg_upload_kbs": 500,
            "yield_guard_fast_fail_minutes": 10,
        })
        torrent_task = {
            "last_check_interval_downspeed": 120 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 4 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 3,
            "yield_guard_stage": "normal",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 10 * 1024 ** 3,
                "uploaded": 200 * 1024 ** 2,
                "total_size": 50 * 1024 ** 3,
                "avg_upspeed": 20 * 1024,
            },
            torrent_task=torrent_task,
            yield_guard_pool_state={"mode": "balanced", "reason": "任务池平衡"},
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("持续低收益", reason)
        self.assertEqual("limited", torrent_task.get("yield_guard_stage"))
        self.assertEqual("持续低收益", torrent_task.get("yield_guard_low_yield_kind"))

    def test_yield_guard_loose_pool_observes_persistent_low_yield_for_more_rounds(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_good_avg_upload_kbs": 500,
            "yield_guard_fast_fail_minutes": 10,
        })
        torrent_task = {
            "last_check_interval_downspeed": 120 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 4 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 3,
            "yield_guard_stage": "normal",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 10 * 1024 ** 3,
                "uploaded": 200 * 1024 ** 2,
                "total_size": 50 * 1024 ** 3,
                "avg_upspeed": 20 * 1024,
            },
            torrent_task=torrent_task,
            yield_guard_pool_state={"mode": "loose", "reason": "活跃任务少"},
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("继续观察", reason)
        self.assertEqual("normal", torrent_task.get("yield_guard_stage"))
        self.assertEqual("loose", torrent_task.get("yield_guard_pool_mode"))
        self.assertGreater(torrent_task.get("yield_guard_effective_bad_checks"), 4)

    def test_yield_guard_competition_pool_tightens_low_yield_observation(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_good_avg_upload_kbs": 500,
            "yield_guard_fast_fail_minutes": 10,
        })
        torrent_task = {
            "last_check_interval_downspeed": 900 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 10 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 2 * 1024 ** 3,
                "uploaded": 20 * 1024 ** 2,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 20 * 1024,
            },
            torrent_task=torrent_task,
            yield_guard_pool_state={"mode": "competition", "reason": "低收益任务占用下载带宽"},
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("limited", torrent_task.get("yield_guard_stage"))
        self.assertIn("低收益", reason)
        self.assertEqual(1, torrent_task.get("yield_guard_effective_bad_checks"))

    def test_yield_guard_conservative_strategy_observes_log_replay_low_yield_longer(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_pressure_strategy": "conservative",
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": int(508.3 * 1024),
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": int(7.0 * 1024),
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 1,
            "yield_guard_stage": "normal",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="天空",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": int(1.02 * 1024 ** 3),
                "uploaded": int(15 * 1024 ** 2),
                "total_size": int(10.6 * 1024 ** 3),
                "avg_upspeed": int(5.7 * 1024),
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("继续观察", reason)
        self.assertEqual("normal", torrent_task.get("yield_guard_stage"))
        self.assertEqual("conservative", torrent_task.get("yield_guard_pool_mode"))
        self.assertEqual(3, torrent_task.get("yield_guard_effective_bad_checks"))

    def test_yield_guard_aggressive_strategy_limits_first_cctv_log_low_yield_hit(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_pressure_strategy": "aggressive",
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": int(555.3 * 1024),
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": int(7.3 * 1024),
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="天空",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": int(0.55 * 1024 ** 3),
                "uploaded": int(7 * 1024 ** 2),
                "total_size": int(8.5 * 1024 ** 3),
                "avg_upspeed": int(16.8 * 1024),
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("低收益", reason)
        self.assertEqual("limited", torrent_task.get("yield_guard_stage"))
        self.assertEqual("aggressive", torrent_task.get("yield_guard_pool_mode"))
        self.assertEqual(1, torrent_task.get("yield_guard_effective_bad_checks"))

    def test_yield_guard_scream_log_replay_keeps_high_average_upload_protected(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_pressure_strategy": "aggressive",
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_bad_checks": 2,
            "yield_guard_good_avg_upload_kbs": 500,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": int(734.4 * 1024),
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": int(7.8 * 1024),
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="天空",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": int(6.10 * 1024 ** 3),
                "uploaded": int(1.8 * 1024 ** 3),
                "total_size": int(22.2 * 1024 ** 3),
                "avg_upspeed": int(710.2 * 1024),
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("上传表现达标", reason)
        self.assertTrue(torrent_task.get("yield_guard_good_protected"))
        self.assertEqual(0, torrent_task.get("yield_guard_bad_streak"))

    def test_yield_guard_low_ratio_is_observed_when_interval_upload_reaches_ratio_protect_threshold(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 300,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 300,
            "yield_guard_ratio_protect_upload_kbs": 200,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": int(5498.5 * 1024),
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": int(248.6 * 1024),
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 1,
            "yield_guard_stage": "normal",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 2 * 1024 ** 3,
                "total_size": 36 * 1024 ** 3,
                "avg_upspeed": int(127.9 * 1024),
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("收益比保护上传阈值", reason)
        self.assertEqual(0, torrent_task.get("yield_guard_bad_streak"))
        self.assertEqual("normal", torrent_task.get("yield_guard_stage"))
        self.assertFalse(torrent_task.get("yield_guard_restore_download_limit"))

    def test_yield_guard_ratio_does_not_trigger_below_ratio_download_floor(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 3500,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
        })
        torrent_task = {
            "last_check_interval_downspeed": 300 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 1 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 1,
            "yield_guard_stage": "normal",
            "yield_guard_restore_download_limit": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 5 * 1024 ** 3,
                "total_size": 20 * 1024 ** 3,
                "avg_upspeed": 0,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("未命中", reason)
        self.assertEqual("normal", torrent_task.get("yield_guard_stage"))
        self.assertFalse(torrent_task.get("yield_guard_restore_download_limit"))

    def test_yield_guard_min_sample_accepts_downloaded_or_progress_threshold(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 2,
            "yield_guard_min_progress_percent": 10,
            "yield_guard_fast_fail_minutes": 0,
            "yield_guard_promising_pubtime_minutes": 0,
        })
        torrent_task = {
            "first_downloaded_time": 1,
            "last_check_interval_downspeed": 5 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 10 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": int(0.5 * 1024 ** 3),
                "total_size": int(1 * 1024 ** 3),
                "avg_upspeed": 0,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("低收益", reason)
        self.assertEqual("limited", torrent_task.get("yield_guard_stage"))

    def test_yield_guard_short_window_keeps_paused_task_for_probe_after_fast_fail_minutes(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_fast_fail_minutes": 1,
        })
        torrent_info = {
            "seeding_time": 0,
            "ratio": 0.1,
            "uploaded": 100,
            "downloaded": 1000,
            "total_size": 2000,
            "dltime": 120,
            "avg_upspeed": 50,
            "iatime": 0,
            "last_check_interval_downspeed": 5 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 10 * 1024,
            "last_check_interval_upspeed_valid": True,
        }
        torrent_task = {
            "site_name": "站点1",
            "time": 0,
            "first_downloaded_time": 0,
            "first_uploaded_time": 0,
            "last_check_time": 0,
            "last_check_uploaded": 0,
            "last_check_downloaded": 0,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "paused",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": True,
        }
        original_get_task_elapsed_minutes = plugin._BrushFlowLowFreq__get_task_elapsed_minutes
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 5
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
                site_name="站点1",
                torrent_info=torrent_info,
                torrent_task=torrent_task,
            )
        finally:
            plugin._BrushFlowLowFreq__get_task_elapsed_minutes = original_get_task_elapsed_minutes

        self.assertFalse(should_delete, reason)
        self.assertEqual("未能满足设置的删除条件", reason)

    def test_yield_guard_limit_action_calls_qb_download_limit(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_download_limit_kbs": 512,
        }, downloader=downloader)

        applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="limit",
            brush_config=plugin._brush_config,
        )

        self.assertTrue(applied)
        self.assertEqual([(["abcdef"], 512 * 1024)], downloader.qbc.download_limits)

    def test_yield_guard_strict_limit_action_calls_qb_download_limit_with_tighter_limit(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_download_limit_kbs": 512,
        }, downloader=downloader)

        applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="strict_limit",
            brush_config=plugin._brush_config,
        )

        self.assertTrue(applied)
        self.assertEqual([(["abcdef"], 128 * 1024)], downloader.qbc.download_limits)

    def test_yield_guard_idle_release_actions_call_qb_download_limits(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_download_limit_kbs": 512,
            "yield_guard_relax_download_limit_kbs": 1024,
            "yield_guard_half_open_download_limit_kbs": 4096,
        }, downloader=downloader)

        relax_applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="relax_limit",
            brush_config=plugin._brush_config,
        )
        half_applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="half_limit",
            brush_config=plugin._brush_config,
        )

        self.assertTrue(relax_applied)
        self.assertTrue(half_applied)
        self.assertEqual(
            [(["abcdef"], 1024 * 1024), (["abcdef"], 4096 * 1024)],
            downloader.qbc.download_limits,
        )

    def test_yield_guard_probe_action_resumes_and_applies_normal_download_limit(self):
        class FakeQbc:
            def __init__(self):
                self.resumed = []
                self.download_limits = []

            def torrents_resume(self, torrent_hashes):
                self.resumed.append(torrent_hashes)

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_download_limit_kbs": 512,
        }, downloader=downloader)

        applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="probe",
            brush_config=plugin._brush_config,
        )

        self.assertTrue(applied)
        self.assertEqual([["abcdef"]], downloader.qbc.resumed)
        self.assertEqual([(["abcdef"], 512 * 1024)], downloader.qbc.download_limits)

    def test_yield_guard_restore_limit_action_calls_qb_download_limit_with_configured_default(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "dl_speed": 2048,
        }, downloader=downloader)

        applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="restore_limit",
            brush_config=plugin._brush_config,
        )

        self.assertTrue(applied)
        self.assertEqual([(["abcdef"], 2048 * 1024)], downloader.qbc.download_limits)

    def test_yield_guard_rehearsal_marks_action_observed_without_qb_call(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": True,
            "yield_guard_download_limit_kbs": 512,
        }, downloader=downloader)
        torrent_task = {
            "yield_guard_stage": "limited",
            "yield_guard_restore_download_limit": False,
            "yield_guard_last_reason": "上传收益保护：低收益，动作 limit",
        }
        original_time = self.module.time.time
        self.module.time.time = lambda: 100
        try:
            handled = plugin._BrushFlowLowFreq__apply_yield_guard_action_for_task(
                torrent_hash="abcdef",
                torrent_task=torrent_task,
                action="limit",
                brush_config=plugin._brush_config,
                site_name="站点1",
                reason=torrent_task["yield_guard_last_reason"],
            )
        finally:
            self.module.time.time = original_time

        self.assertTrue(handled)
        self.assertEqual([], downloader.qbc.download_limits)
        self.assertEqual(100, torrent_task.get("yield_guard_last_action_time"))

    def test_yield_guard_rehearsal_does_not_clear_pending_restore_limit(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": True,
        }, downloader=downloader)
        torrent_task = {
            "yield_guard_stage": "normal",
            "yield_guard_restore_download_limit": True,
            "yield_guard_last_reason": "上传收益保护：上传表现达标，跳过易误伤删种规则",
        }

        handled = plugin._BrushFlowLowFreq__apply_yield_guard_action_for_task(
            torrent_hash="abcdef",
            torrent_task=torrent_task,
            action="restore_limit",
            brush_config=plugin._brush_config,
            site_name="站点1",
            reason=torrent_task["yield_guard_last_reason"],
        )

        self.assertTrue(handled)
        self.assertEqual([], downloader.qbc.download_limits)
        self.assertTrue(torrent_task.get("yield_guard_restore_download_limit"))

    def test_yield_guard_pause_action_calls_qb_pause(self):
        class FakeQbc:
            def __init__(self):
                self.paused = []

            def torrents_pause(self, torrent_hashes):
                self.paused.append(torrent_hashes)

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
        }, downloader=downloader)

        applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="pause",
            brush_config=plugin._brush_config,
        )

        self.assertTrue(applied)
        self.assertEqual([["abcdef"]], downloader.qbc.paused)

    def test_check_does_not_repeat_pause_action_while_pause_window_open(self):
        class FakeQbc:
            def __init__(self):
                self.paused = []

            def torrents_pause(self, torrent_hashes):
                self.paused.append(torrent_hashes)

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

            def get_torrents(self):
                return [{
                    "hash": "abcdef",
                    "name": "paused yield torrent",
                    "tags": "刷流",
                    "state": "pausedDL",
                    "progress": 0.1,
                    "downloaded": 1024 ** 3,
                    "uploaded": 0,
                    "total_size": 10 * 1024 ** 3,
                    "ratio": 0,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }], None

            def delete_torrents(self, ids, delete_file=True):
                self.deleted = ids
                return True

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 10,
            "yield_guard_final_action": "delete",
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "paused yield torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 1024 ** 3,
                "uploaded": 0,
                "total_size": 10 * 1024 ** 3,
                "ratio": 0,
                "seeding_time": 0,
                "last_check_time": 1000,
                "last_check_uploaded": 0,
                "last_check_downloaded": 1024 ** 3,
                "first_downloaded_time": 1,
                "yield_guard_bad_streak": 4,
                "yield_guard_stage": "paused",
                "yield_guard_paused_time": 1000,
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None

        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 5 * 60
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([], plugin.downloader.qbc.paused)
        self.assertEqual("paused", torrent_tasks["abcdef"].get("yield_guard_stage"))

    def test_check_does_not_repeat_probe_action_while_probe_window_open(self):
        class FakeQbc:
            def __init__(self):
                self.resumed = []
                self.download_limits = []

            def torrents_resume(self, torrent_hashes):
                self.resumed.append(torrent_hashes)

            def torrents_set_download_limit(self, limit=None, torrent_hashes=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

            def get_torrents(self):
                return [{
                    "hash": "abcdef",
                    "name": "probing yield torrent",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.05,
                    "downloaded": 32 * 1024 ** 2,
                    "uploaded": 512,
                    "total_size": 1024 ** 3,
                    "ratio": 0,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }], None

            def delete_torrents(self, ids, delete_file=True):
                self.deleted = ids
                return True

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 10,
            "yield_guard_final_action": "delete",
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 3,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "probing yield torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 30 * 1024 ** 2,
                "uploaded": 0,
                "total_size": 1024 ** 3,
                "ratio": 0,
                "seeding_time": 0,
                "last_check_time": 1000,
                "last_check_uploaded": 0,
                "last_check_downloaded": 30 * 1024 ** 2,
                "first_downloaded_time": 1,
                "yield_guard_bad_streak": 4,
                "yield_guard_stage": "probing",
                "yield_guard_probe_started": True,
                "yield_guard_probe_started_time": 1000,
                "yield_guard_restore_download_limit": False,
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None

        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 5 * 60
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([], plugin.downloader.qbc.resumed)
        self.assertEqual([], plugin.downloader.qbc.download_limits)
        self.assertEqual("probing", torrent_tasks["abcdef"].get("yield_guard_stage"))

    def test_yield_guard_rehearsal_does_not_call_qb_action(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": True,
        }, downloader=downloader)

        applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="limit",
            brush_config=plugin._brush_config,
        )

        self.assertFalse(applied)
        self.assertEqual([], downloader.qbc.download_limits)

    def test_yield_guard_rehearsal_logs_qb_action_details(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": True,
            "yield_guard_download_limit_kbs": 512,
        }, downloader=downloader)
        start_info_count = len(self.module.logger.info_messages)

        applied = plugin._BrushFlowLowFreq__apply_qb_yield_guard_action(
            torrent_hash="abcdef",
            action="limit",
            brush_config=plugin._brush_config,
            site_name="站点1",
            reason="上传收益保护：低收益，下载 5.0 KB/s，上传 10.0 KB/s，连续 1 次，动作 limit",
        )

        self.assertFalse(applied)
        self.assertEqual([], downloader.qbc.download_limits)
        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertTrue(any("站点：站点1" in msg and "abcdef" in msg and "动作 limit" in msg
                            and "上传收益保护：低收益" in msg for msg in new_logs))

    def test_check_no_longer_applies_legacy_yield_guard_action_before_delete_rules(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []
                self.paused = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

            def torrents_pause(self, torrent_hashes):
                self.paused.append(torrent_hashes)

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

            def get_torrents(self):
                torrent = {
                    "hash": "abcdef",
                    "name": "yield torrent",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.2,
                    "downloaded": 200000,
                    "uploaded": 10,
                    "total_size": 1000000,
                    "ratio": 0.1,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

            def delete_torrents(self, ids, delete_file=True):
                self.deleted = ids
                return True

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_download_limit_kbs": 512,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "yield torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 1000,
                "uploaded": 10,
                "total_size": 10000,
                "ratio": 0.1,
                "seeding_time": 120,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 0,
                "last_check_interval_upspeed": 10,
                "last_check_interval_upspeed_valid": True,
                "last_check_interval_downspeed": 5 * 1024,
                "last_check_interval_downspeed_valid": True,
                "yield_guard_bad_streak": 0,
                "yield_guard_stage": "normal",
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None

        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([], plugin.downloader.qbc.download_limits)
        self.assertEqual("normal", torrent_tasks["abcdef"].get("yield_guard_stage"))
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_evaluated_in_check"))

    def test_check_no_longer_logs_legacy_yield_guard_summary_even_when_config_exists(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def get_torrents(self):
                torrent = {
                    "hash": "abcdef",
                    "name": "yield pending sample",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.1,
                    "downloaded": 1000,
                    "uploaded": 0,
                    "total_size": 10000,
                    "ratio": 0,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "yield pending sample",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 0,
                "uploaded": 0,
                "total_size": 10000,
                "ratio": 0,
                "seeding_time": 0,
                "yield_guard_bad_streak": 0,
                "yield_guard_stage": "normal",
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        start_info_count = len(self.module.logger.info_messages)

        plugin.check()

        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertFalse(any("上传收益保护：本轮检查已评估" in msg for msg in new_logs), new_logs)
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_evaluated_in_check"))

    def test_check_no_longer_logs_legacy_yield_guard_detail_when_enabled(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def get_torrents(self):
                torrent = {
                    "hash": "abcdef",
                    "name": "good yield sample",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.5,
                    "downloaded": 6 * 1024 * 1024,
                    "uploaded": 2 * 1024 * 1024,
                    "total_size": 10 * 1024 * 1024,
                    "ratio": 0.3,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_detail_log": True,
            "yield_guard_good_upload_kbs": 500,
            "yield_guard_good_avg_upload_kbs": 500,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "good yield sample",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 5 * 1024 * 1024,
                "uploaded": 1 * 1024 * 1024,
                "total_size": 10 * 1024 * 1024,
                "ratio": 0.2,
                "seeding_time": 0,
                "last_check_time": 1,
                "last_check_uploaded": 1 * 1024 * 1024,
                "last_check_downloaded": 5 * 1024 * 1024,
                "yield_guard_bad_streak": 0,
                "yield_guard_stage": "normal",
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        start_info_count = len(self.module.logger.info_messages)

        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertFalse(any("上传收益保护详细日志" in msg for msg in new_logs), new_logs)
        self.assertFalse(any("高收益保护" in msg for msg in new_logs), new_logs)
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_evaluated_in_check"))

    def test_check_no_longer_logs_legacy_yield_guard_detail_miss_reason(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def get_torrents(self):
                torrent = {
                    "hash": "abcdef",
                    "name": "low upload sample",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.1,
                    "downloaded": 5 * 1024 * 1024 + 100 * 1024,
                    "uploaded": 10 * 1024,
                    "total_size": 10 * 1024 * 1024,
                    "ratio": 0.02,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_detail_log": True,
            "yield_guard_good_upload_kbs": 500,
            "yield_guard_good_avg_upload_kbs": 500,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "low upload sample",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 5 * 1024 * 1024,
                "uploaded": 0,
                "total_size": 10 * 1024 * 1024,
                "ratio": 0.01,
                "seeding_time": 0,
                "last_check_time": 999,
                "last_check_uploaded": 0,
                "last_check_downloaded": 5 * 1024 * 1024,
                "yield_guard_bad_streak": 0,
                "yield_guard_stage": "normal",
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        start_info_count = len(self.module.logger.info_messages)

        original_time = self.module.time.time
        self.module.time.time = lambda: 1000
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertFalse(any("上传收益保护详细日志" in msg for msg in new_logs), new_logs)
        self.assertFalse(any("原因=上传收益保护" in msg for msg in new_logs), new_logs)
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_evaluated_in_check"))

    def test_check_no_longer_logs_legacy_yield_guard_detail_for_low_ratio_hit(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def get_torrents(self):
                torrent = {
                    "hash": "abcdef",
                    "name": "low ratio sample",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.4,
                    "downloaded": 5 * 1024 * 1024 + 925 * 1024,
                    "uploaded": 37 * 1024,
                    "total_size": 10 * 1024 * 1024,
                    "ratio": 0.01,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_detail_log": True,
            "yield_guard_high_download_kbs": 3500,
            "yield_guard_low_upload_kbs": 150,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_good_upload_kbs": 500,
            "yield_guard_good_avg_upload_kbs": 500,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "low ratio sample",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 5 * 1024 * 1024,
                "uploaded": 0,
                "total_size": 10 * 1024 * 1024,
                "ratio": 0,
                "seeding_time": 0,
                "last_check_time": 999,
                "last_check_uploaded": 0,
                "last_check_downloaded": 5 * 1024 * 1024,
                "yield_guard_bad_streak": 0,
                "yield_guard_stage": "normal",
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        start_info_count = len(self.module.logger.info_messages)

        original_time = self.module.time.time
        self.module.time.time = lambda: 1000
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertFalse(any("上传收益保护详细日志" in msg for msg in new_logs), new_logs)
        self.assertFalse(any("判定=低收益观察/动作" in msg for msg in new_logs), new_logs)
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_evaluated_in_check"))

    def test_check_skips_yield_guard_for_completed_torrents(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def get_torrents(self):
                torrent = {
                    "hash": "abcdef",
                    "name": "completed yield sample",
                    "tags": "刷流",
                    "state": "stalledUP",
                    "progress": 1.0,
                    "downloaded": 10 * 1024 * 1024,
                    "uploaded": 4 * 1024 * 1024,
                    "total_size": 10 * 1024 * 1024,
                    "ratio": 0.4,
                    "added_on": 1,
                    "completion_on": 1,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_detail_log": True,
            "yield_guard_good_upload_kbs": 1,
            "yield_guard_good_avg_upload_kbs": 1,
            "freeleech": "",
            "hr": "no",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "completed yield sample",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 10 * 1024 * 1024,
                "uploaded": 1 * 1024 * 1024,
                "total_size": 10 * 1024 * 1024,
                "ratio": 0.1,
                "seeding_time": 3600,
                "last_check_time": 1,
                "last_check_uploaded": 1 * 1024 * 1024,
                "last_check_downloaded": 10 * 1024 * 1024,
                "yield_guard_bad_streak": 1,
                "yield_guard_stage": "normal",
                "yield_guard_good_protected": True,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        start_info_count = len(self.module.logger.info_messages)

        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertFalse(any("上传收益保护：本轮检查已评估" in msg for msg in new_logs), new_logs)
        self.assertFalse(any("上传收益保护详细日志" in msg for msg in new_logs), new_logs)
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_evaluated_in_check"))
        self.assertTrue(torrent_tasks["abcdef"].get("yield_guard_good_protected"))
        self.assertEqual(1, torrent_tasks["abcdef"].get("yield_guard_bad_streak"))

    def test_check_skips_low_ratio_delete_when_good_protected(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def get_torrents(self):
                torrent = {
                    "hash": "abcdef",
                    "name": "good torrent",
                    "tags": "刷流",
                    "state": "seeding",
                    "progress": 1.0,
                    "downloaded": 10000,
                    "uploaded": 1000,
                    "total_size": 10000,
                    "ratio": 0.1,
                    "added_on": 1,
                    "completion_on": 1,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

            def delete_torrents(self, ids, delete_file=True):
                self.deleted = ids
                return True

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_good_upload_kbs": 1,
            "yield_guard_protect_delete_rules": True,
            "seed_ratio": 0.5,
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        plugin.get_data = lambda key: {
            "torrents": {
                "abcdef": {
                    "site": 1,
                    "site_name": "站点1",
                    "title": "good torrent",
                    "description": "desc",
                    "hit_and_run": False,
                    "time": 0,
                    "downloaded": 10000,
                    "uploaded": 1000,
                    "total_size": 10000,
                    "ratio": 0.1,
                    "seeding_time": 3600,
                    "last_check_time": 0,
                    "last_check_uploaded": 0,
                    "last_check_downloaded": 0,
                    "last_check_interval_upspeed": 2 * 1024,
                    "last_check_interval_upspeed_valid": True,
                    "last_check_interval_downspeed": 5 * 1024,
                    "last_check_interval_downspeed_valid": True,
                    "yield_guard_good_protected": True,
                    "yield_guard_promising_protected": False,
                    "deleted": False,
                }
            },
            "unmanaged": {}
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None

        plugin.check()

        self.assertFalse(getattr(plugin.downloader, "deleted", None))

    def test_check_no_longer_deletes_legacy_yield_guard_probe_failure_when_dynamic_threshold_not_reached(self):
        class FakeDownloader:
            def __init__(self):
                self.deleted = []
                self.reannounced = []

            def is_inactive(self):
                return False

            def get_torrents(self):
                if self.deleted:
                    return [], None
                torrent = {
                    "hash": "bad",
                    "name": "bad torrent",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.5,
                    "downloaded": 50 * 1024 ** 3,
                    "uploaded": 0,
                    "total_size": 100 * 1024 ** 3,
                    "ratio": 0,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }
                return [torrent], None

            def delete_torrents(self, ids, delete_file=True):
                self.deleted = ids
                return True

            @property
            def qbc(self):
                class FakeQbc:
                    def __init__(self, parent):
                        self.parent = parent

                    def torrents_reannounce(self, torrent_hashes):
                        self.parent.reannounced.append(torrent_hashes)

                return FakeQbc(self)

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_first_action": "delete",
            "yield_guard_fast_fail_minutes": 0,
            "yield_guard_promising_pubtime_minutes": 0,
            "proxy_delete": True,
            "delete_size_range": "1000",
            "freeleech": "",
            "hr": "no",
        }, downloader=downloader)
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "bad": {
                "site": 1,
                "site_name": "站点1",
                "title": "bad torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "size": 100 * 1024 ** 3,
                "downloaded": 0,
                "uploaded": 0,
                "total_size": 100 * 1024 ** 3,
                "ratio": 0,
                "seeding_time": 0,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 0,
                "yield_guard_bad_streak": 2,
                "yield_guard_stage": "probing",
                "yield_guard_probe_started": True,
                "yield_guard_good_protected": False,
                "yield_guard_promising_protected": False,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {},
            "statistic": {},
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None

        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([], downloader.deleted)
        self.assertFalse(torrent_tasks["bad"].get("deleted"))
        self.assertFalse(torrent_tasks["bad"].get("yield_guard_evaluated_in_check"))

    def test_dynamic_fallback_no_longer_skips_yield_guard_good_protected_torrents(self):
        class FakeDownloader:
            def __init__(self):
                self.deleted = []

            def is_inactive(self):
                return False

            def get_completed_torrents(self, ids):
                return [
                    {
                        "hash": "good",
                        "name": "good torrent",
                        "tags": "刷流",
                        "downloaded": 100 * 1024 ** 3,
                        "total_size": 100 * 1024 ** 3,
                        "uploaded": 1000 * 1024 ** 3,
                        "ratio": 10,
                        "added_on": 1,
                        "completion_on": 1,
                        "last_activity": 1,
                        "tracker": "tracker",
                    }
                ]

        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_protect_delete_rules": True,
            "proxy_delete": True,
            "delete_size_range": "1",
        }, downloader=FakeDownloader())
        plugin._BrushFlowLowFreq__calculate_seeding_torrents_size = lambda torrent_tasks: 100 * 1024 ** 3
        torrent = {
            "hash": "good",
            "name": "good torrent",
            "tags": "刷流",
            "downloaded": 100 * 1024 ** 3,
            "total_size": 100 * 1024 ** 3,
            "uploaded": 1000 * 1024 ** 3,
            "ratio": 10,
            "added_on": 1,
            "completion_on": 1,
            "last_activity": 1,
            "tracker": "tracker",
        }
        torrent_tasks = {
            "good": {
                "site_name": "站点1",
                "title": "good torrent",
                "description": "desc",
                "hit_and_run": False,
                "seeding_time": 3600,
                "last_check_interval_upspeed": 2 * 1024 * 1024,
                "last_check_interval_upspeed_valid": True,
                "yield_guard_good_protected": True,
            }
        }

        delete_hashes = plugin._BrushFlowLowFreq__delete_torrent_for_proxy(
            torrents=[torrent],
            torrent_tasks=torrent_tasks,
            delete_message_map={},
            delete_summary_messages=[],
        )

        self.assertEqual(["good"], delete_hashes)

    def test_yield_guard_good_pool_soft_stop_allows_new_brush_when_task_pool_is_small(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
        })
        plugin.get_data = lambda key: {
            "torrents": {
                "abc": {
                    "deleted": False,
                    "yield_guard_good_protected": True,
                }
            }
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            include_network_conditions=False,
            include_yield_guard=True
        )

        self.assertTrue(passed, reason)

    def test_yield_guard_good_pool_soft_stop_blocks_new_brush_when_task_pool_is_busy(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
        })
        busy_tasks = {
            "good": {
                "deleted": False,
                "yield_guard_good_protected": True,
            }
        }
        for index in range(6):
            busy_tasks[f"probe{index}"] = {
                "deleted": False,
                "yield_guard_good_protected": False,
            }
        plugin.get_data = lambda key: {
            "torrents": busy_tasks
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            include_network_conditions=False,
            include_yield_guard=True
        )

        self.assertFalse(passed)
        self.assertIn("高收益", reason)

    def test_yield_guard_strict_small_pool_strategy_blocks_even_when_task_pool_is_small(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
            "yield_guard_small_pool_brush_strategy": "strict",
        })
        plugin.get_data = lambda key: {
            "torrents": {
                "abc": {
                    "deleted": False,
                    "yield_guard_good_protected": True,
                }
            }
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            include_network_conditions=False,
            include_yield_guard=True
        )

        self.assertFalse(passed)
        self.assertIn("高收益", reason)

    def test_yield_guard_aggressive_small_pool_strategy_allows_more_probe_tasks(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
            "yield_guard_small_pool_brush_strategy": "aggressive",
        })
        tasks = {
            "good": {
                "deleted": False,
                "yield_guard_good_protected": True,
            }
        }
        for index in range(6):
            tasks[f"probe{index}"] = {
                "deleted": False,
                "yield_guard_good_protected": False,
            }
        plugin.get_data = lambda key: {
            "torrents": tasks
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            include_network_conditions=False,
            include_yield_guard=True
        )

        self.assertTrue(passed, reason)

    def test_yield_guard_aggressive_small_pool_strategy_still_blocks_recent_probe(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
            "yield_guard_probe_interval_minutes": 10,
            "yield_guard_small_pool_brush_strategy": "aggressive",
        })
        original_time = self.module.time.time
        self.module.time.time = lambda: 1000
        try:
            plugin.get_data = lambda key: {
                "torrents": {
                    "good": {
                        "deleted": False,
                        "yield_guard_good_protected": True,
                    },
                    "probe": {
                        "deleted": False,
                        "yield_guard_good_protected": False,
                        "yield_guard_last_probe_time": 700,
                    },
                }
            }.get(key, {})

            passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
                include_network_conditions=False,
                include_yield_guard=True
            )
        finally:
            self.module.time.time = original_time

        self.assertFalse(passed)
        self.assertIn("探测间隔", reason)

    def test_yield_guard_aggressive_small_pool_strategy_still_blocks_when_auto_pool_is_crowded(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
            "yield_guard_pressure_strategy": "aggressive",
            "yield_guard_small_pool_brush_strategy": "aggressive",
        })
        tasks = {
            "good": {
                "deleted": False,
                "yield_guard_good_protected": True,
            }
        }
        for index in range(12):
            tasks[f"probe{index}"] = {
                "deleted": False,
                "yield_guard_good_protected": False,
            }
        plugin.get_data = lambda key: {
            "torrents": tasks
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            include_network_conditions=False,
            include_yield_guard=True
        )

        self.assertFalse(passed)
        self.assertIn("高收益", reason)

    def test_yield_guard_probe_slot_allows_new_brush_when_pool_is_full(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 1,
            "yield_guard_probe_interval_minutes": 10,
        })
        plugin.get_data = lambda key: {
            "torrents": {
                "abc": {
                    "deleted": False,
                    "yield_guard_good_protected": True,
                }
            }
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            include_network_conditions=False,
            include_yield_guard=True
        )

        self.assertTrue(passed, reason)

    def test_yield_guard_probe_interval_blocks_recent_probe_even_with_free_slot(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 2,
            "yield_guard_probe_interval_minutes": 10,
        })
        original_time = self.module.time.time
        self.module.time.time = lambda: 1000
        try:
            plugin.get_data = lambda key: {
                "torrents": {
                    "good": {
                        "deleted": False,
                        "yield_guard_good_protected": True,
                    },
                    "probe": {
                        "deleted": False,
                        "yield_guard_good_protected": False,
                        "yield_guard_last_probe_time": 700,
                    },
                }
            }.get(key, {})

            passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
                include_network_conditions=False,
                include_yield_guard=True
            )
        finally:
            self.module.time.time = original_time

        self.assertFalse(passed)
        self.assertIn("探测间隔", reason)

    def test_yield_guard_good_pool_uses_current_site_tasks_only(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
        })
        plugin.get_data = lambda key: {
            "torrents": {
                "site1good": {
                    "site_name": "站点1",
                    "deleted": False,
                    "yield_guard_good_protected": True,
                }
            }
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            sitename="站点2",
            include_network_conditions=False
        )

        self.assertTrue(passed, reason)

    def test_brush_global_precondition_does_not_use_cross_site_yield_guard_pool(self):
        plugin = self._new_qb_plugin({
            "enabled": True,
            "brushsites": [2],
            "brush_sequential": True,
            "except_subscribe": False,
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
        })
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin._BrushFlowLowFreq__is_current_time_in_range = lambda: True
        plugin._BrushFlowLowFreq__calculate_seeding_torrents_size = lambda torrent_tasks: 0
        plugin._BrushFlowLowFreq__get_average_bandwidth = lambda: (0, 0)
        plugin.get_data = lambda key: {
            "torrents": {
                "site1good": {
                    "site_name": "站点1",
                    "deleted": False,
                    "yield_guard_good_protected": True,
                }
            },
            "statistic": {},
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        plugin.site_oper = SimpleNamespace(
            get=lambda siteid: SimpleNamespace(id=siteid, name=f"站点{siteid}", domain=f"site{siteid}.test")
        )
        called_sites = []
        plugin._BrushFlowLowFreq__brush_site_torrents = (
            lambda siteid, torrent_tasks, statistic_info, subscribe_titles:
            called_sites.append(siteid) or True
        )

        plugin.brush()

        self.assertEqual([2], called_sites)

    def test_site_config_disables_yield_guard_good_pool_for_that_site(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
            "enable_site_config": True,
            "site_config": '[{"sitename": "站点2", "yield_guard_enabled": false}]',
        })
        plugin.get_data = lambda key: {
            "torrents": {
                "site2good": {
                    "site_name": "站点2",
                    "deleted": False,
                    "yield_guard_good_protected": True,
                }
            }
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            sitename="站点2",
            include_network_conditions=False
        )

        self.assertTrue(passed, reason)

    def test_yield_guard_promising_pubtime_suppresses_delete_action(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_first_action": "delete",
            "yield_guard_fast_fail_minutes": 0,
            "yield_guard_promising_pubtime_minutes": 15,
        })
        original_get_pubminutes = plugin._BrushFlowLowFreq__get_pubminutes
        plugin._BrushFlowLowFreq__get_pubminutes = lambda pubdate: 5
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
                site_name="站点1",
                brush_config=plugin._brush_config,
                torrent_info={
                    "downloaded": 1000,
                    "total_size": 2000,
                    "avg_upspeed": 0,
                },
                torrent_task={
                    "pubdate": "2026-06-14 00:00:00",
                    "first_downloaded_time": 1,
                    "last_check_interval_downspeed": 5 * 1024,
                    "last_check_interval_downspeed_valid": True,
                    "last_check_interval_upspeed": 10 * 1024,
                    "last_check_interval_upspeed_valid": True,
                    "yield_guard_bad_streak": 0,
                    "yield_guard_stage": "normal",
                },
            )
        finally:
            plugin._BrushFlowLowFreq__get_pubminutes = original_get_pubminutes

        self.assertFalse(should_delete, reason)
        self.assertIn("动作 暂停", reason)

    def test_yield_guard_paused_task_final_delete_after_window_without_downspeed(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 1,
            "yield_guard_final_action": "delete",
        })
        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 5 * 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
                site_name="站点1",
                brush_config=plugin._brush_config,
                torrent_info={
                    "downloaded": 1000,
                    "total_size": 2000,
                    "avg_upspeed": 0,
                },
                torrent_task={
                    "first_downloaded_time": 1,
                    "yield_guard_paused_time": 1000,
                    "last_check_interval_downspeed": 0,
                    "last_check_interval_downspeed_valid": True,
                    "last_check_interval_upspeed": 0,
                    "last_check_interval_upspeed_valid": True,
                    "yield_guard_bad_streak": 2,
                    "yield_guard_stage": "paused",
                    "yield_guard_good_protected": False,
                    "yield_guard_promising_protected": False,
                },
            )
        finally:
            self.module.time.time = original_time

        self.assertFalse(should_delete, reason)
        self.assertIn("恢复探测", reason)

    def test_yield_guard_rehearsal_blocks_paused_final_delete(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": True,
            "yield_guard_bad_checks": 2,
            "yield_guard_fast_fail_minutes": 1,
            "yield_guard_final_action": "delete",
        })
        original_time = self.module.time.time
        self.module.time.time = lambda: 1000 + 5 * 60
        torrent_task = {
            "first_downloaded_time": 1,
            "yield_guard_paused_time": 1000,
            "last_check_interval_downspeed": 0,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 0,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 2,
            "yield_guard_stage": "paused",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
                site_name="站点1",
                brush_config=plugin._brush_config,
                torrent_info={
                    "downloaded": 1000,
                    "total_size": 2000,
                    "avg_upspeed": 0,
                },
                torrent_task=torrent_task,
            )
        finally:
            self.module.time.time = original_time

        self.assertFalse(should_delete, reason)
        self.assertIn("恢复探测", reason)
        self.assertEqual(reason, torrent_task.get("yield_guard_last_reason"))

    def test_yield_guard_rehearsal_blocks_immediate_delete_action(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": True,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "yield_guard_first_action": "delete",
            "yield_guard_fast_fail_minutes": 0,
            "yield_guard_promising_pubtime_minutes": 0,
        })
        start_info_count = len(self.module.logger.info_messages)
        torrent_task = {
            "first_downloaded_time": 1,
            "last_check_interval_downspeed": 5 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_upspeed": 10 * 1024,
            "last_check_interval_upspeed_valid": True,
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_yield_guard_for_delete(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={
                "downloaded": 1000,
                "total_size": 2000,
                "avg_upspeed": 0,
            },
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertIn("动作 暂停", reason)
        self.assertEqual("paused", torrent_task.get("yield_guard_stage"))
        self.assertEqual(reason, torrent_task.get("yield_guard_last_reason"))
        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertFalse(any("动作=delete" in msg for msg in new_logs))

    def test_get_form_exposes_upload_protection_controls(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, _defaults = plugin.get_form()

        def collect_models(node):
            models = set()
            if isinstance(node, dict):
                props = node.get("props") or {}
                for key in ("model", "modelvalue"):
                    if props.get(key):
                        models.add(props[key])
                for child in node.get("content") or []:
                    models.update(collect_models(child))
            elif isinstance(node, list):
                for child in node:
                    models.update(collect_models(child))
            return models

        models = collect_models(form)
        expected_models = {
            "upload_protection_enabled",
            "upload_protection_rehearsal",
            "upload_protection_detail_log",
            "upload_protection_low_upspeed_kbs",
            "upload_protection_good_upspeed_kbs",
            "upload_protection_low_limit_checks",
            "upload_protection_low_strict_checks",
            "upload_protection_good_restore_checks",
            "upload_protection_good_release_checks",
            "upload_protection_download_limit_kbs",
            "upload_protection_no_upload_kbs",
            "upload_protection_no_upload_checks",
            "upload_protection_min_elapsed_minutes",
            "upload_protection_min_downloaded_gb",
            "upload_protection_skip_when_downloading_le",
        }
        self.assertTrue(expected_models.issubset(models), expected_models - models)

    def test_get_form_places_upload_protection_speed_controls_together(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, _defaults = plugin.get_form()

        def collect_models_in_order(node):
            models = []
            if isinstance(node, dict):
                props = node.get("props") or {}
                for key in ("model", "modelvalue"):
                    if props.get(key):
                        models.append(props[key])
                for child in node.get("content") or []:
                    models.extend(collect_models_in_order(child))
            elif isinstance(node, list):
                for child in node:
                    models.extend(collect_models_in_order(child))
            return models

        models = collect_models_in_order(form)

        self.assertLess(
            models.index("upload_protection_low_upspeed_kbs"),
            models.index("upload_protection_good_upspeed_kbs")
        )
        self.assertEqual(
            models.index("upload_protection_good_upspeed_kbs") + 1,
            models.index("upload_protection_download_limit_kbs")
        )
        self.assertEqual(
            models.index("upload_protection_low_limit_checks") + 1,
            models.index("upload_protection_low_strict_checks")
        )
        self.assertEqual(
            models.index("upload_protection_good_restore_checks") + 1,
            models.index("upload_protection_good_release_checks")
        )

    def test_empty_new_numeric_options_default_to_zero(self):
        brush_config = self.module.BrushConfig({
            "skip_rules_downloading_threshold": "",
            "seed_ratio_speed_protect": "",
        })

        self.assertEqual(0, brush_config.skip_rules_downloading_threshold)
        self.assertEqual(0, brush_config.seed_ratio_speed_protect)

    def test_brush_interval_minutes_defaults_and_is_configurable(self):
        self.assertEqual(10, self.module.BrushConfig({}).brush_interval_minutes)
        self.assertEqual(3, self.module.BrushConfig({"brush_interval_minutes": 3}).brush_interval_minutes)
        self.assertEqual(10, self.module.BrushConfig({"brush_interval_minutes": ""}).brush_interval_minutes)
        self.assertEqual(10, self.module.BrushConfig({"brush_interval_minutes": "bad"}).brush_interval_minutes)
        self.assertEqual(10, self.module.BrushConfig({"brush_interval_minutes": 0}).brush_interval_minutes)
        self.assertEqual(10, self.module.BrushConfig({"brush_interval_minutes": -1}).brush_interval_minutes)
        self.assertEqual(59, self.module.BrushConfig({"brush_interval_minutes": 120}).brush_interval_minutes)

    def test_brush_interval_minutes_controls_interval_service(self):
        plugin = self._new_qb_plugin({
            "enabled": True,
            "brushsites": [1],
            "downloader": "qb",
            "brush_interval_minutes": 3,
            "cron": "",
        })
        plugin._task_brush_enable = True
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True

        services = plugin.get_service()
        brush_service = next(service for service in services if service["id"] == "BrushFlowLowFreq")

        self.assertEqual("interval", brush_service["trigger"])
        self.assertEqual({"minutes": 3}, brush_service["kwargs"])

    def test_brush_interval_minutes_controls_cron_minute_step(self):
        captured = []

        class FakeCronTrigger:
            @staticmethod
            def from_crontab(cron):
                captured.append(cron)
                return {"cron": cron}

        original_cron_trigger = self.module.CronTrigger
        self.module.CronTrigger = FakeCronTrigger
        plugin = self._new_qb_plugin({
            "enabled": True,
            "brushsites": [1],
            "downloader": "qb",
            "brush_interval_minutes": 3,
            "cron": "0 0-8 * * *",
        })
        plugin._task_brush_enable = True
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        try:
            services = plugin.get_service()
        finally:
            self.module.CronTrigger = original_cron_trigger

        brush_service = next(service for service in services if service["id"] == "BrushFlowLowFreq")
        self.assertEqual({"cron": captured[0]}, brush_service["trigger"])
        self.assertRegex(captured[0].split()[0], r"^\d+/3$")
        self.assertNotIn("/10", captured[0].split()[0])

    def test_get_form_exposes_brush_interval_minutes(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, defaults = plugin.get_form()

        def collect_models(node):
            models = set()
            if isinstance(node, dict):
                props = node.get("props") or {}
                model = props.get("model")
                if model:
                    models.add(model)
                for child in node.get("content") or []:
                    models.update(collect_models(child))
            elif isinstance(node, list):
                for child in node:
                    models.update(collect_models(child))
            return models

        self.assertIn("brush_interval_minutes", collect_models(form))
        self.assertEqual(10, defaults.get("brush_interval_minutes"))

    def test_get_form_places_log_mode_in_more_config_tab(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, defaults = plugin.get_form()

        def find_window_item(node, value):
            if isinstance(node, dict):
                if node.get("component") == "VWindowItem" and (node.get("props") or {}).get("value") == value:
                    return node
                for child in node.get("content") or []:
                    found = find_window_item(child, value)
                    if found:
                        return found
            elif isinstance(node, list):
                for child in node:
                    found = find_window_item(child, value)
                    if found:
                        return found
            return None

        def collect_models(node):
            models = set()
            if isinstance(node, dict):
                props = node.get("props") or {}
                model = props.get("model")
                if model:
                    models.add(model)
                for child in node.get("content") or []:
                    models.update(collect_models(child))
            elif isinstance(node, list):
                for child in node:
                    models.update(collect_models(child))
            return models

        other_tab = find_window_item(form, "other_tab")
        delete_tab = find_window_item(form, "delete_tab")

        self.assertIsNotNone(other_tab)
        self.assertIsNotNone(delete_tab)
        self.assertIn("log_mode", collect_models(other_tab))
        self.assertNotIn("log_mode", collect_models(delete_tab))
        self.assertEqual("full", defaults.get("log_mode"))

    def test_upload_protection_defaults_are_disabled_and_configurable(self):
        default_config = self.module.BrushConfig({})
        custom_config = self.module.BrushConfig({
            "upload_protection_enabled": True,
            "upload_protection_low_upspeed_kbs": 120,
            "upload_protection_good_upspeed_kbs": 180,
            "upload_protection_download_limit_kbs": 400,
        })

        self.assertFalse(default_config.upload_protection_enabled)
        self.assertFalse(default_config.upload_protection_rehearsal)
        self.assertEqual(150, default_config.upload_protection_low_upspeed_kbs)
        self.assertEqual(150, default_config.upload_protection_good_upspeed_kbs)
        self.assertEqual(2, default_config.upload_protection_low_limit_checks)
        self.assertEqual(3, default_config.upload_protection_low_strict_checks)
        self.assertEqual(2, default_config.upload_protection_good_restore_checks)
        self.assertEqual(3, default_config.upload_protection_good_release_checks)
        self.assertEqual(512, default_config.upload_protection_download_limit_kbs)
        self.assertEqual(5, default_config.upload_protection_no_upload_kbs)
        self.assertEqual(6, default_config.upload_protection_no_upload_checks)
        self.assertEqual(10, default_config.upload_protection_min_elapsed_minutes)
        self.assertEqual(0, default_config.upload_protection_min_downloaded_gb)
        self.assertFalse(default_config.upload_protection_detail_log)
        self.assertEqual(0, default_config.upload_protection_skip_when_downloading_le)
        self.assertTrue(custom_config.upload_protection_enabled)
        self.assertEqual(120, custom_config.upload_protection_low_upspeed_kbs)
        self.assertEqual(180, custom_config.upload_protection_good_upspeed_kbs)
        self.assertEqual(400, custom_config.upload_protection_download_limit_kbs)

    def test_upload_protection_site_config_overrides_global_values(self):
        brush_config = self.module.BrushConfig({
            "enable_site_config": True,
            "upload_protection_enabled": False,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_good_upspeed_kbs": 180,
            "upload_protection_download_limit_kbs": 512,
            "upload_protection_min_elapsed_minutes": 10,
            "upload_protection_skip_when_downloading_le": 0,
            "site_config": (
                '[{"sitename": "站点1", '
                '"upload_protection_enabled": true, '
                '"upload_protection_low_upspeed_kbs": 90, '
                '"upload_protection_good_upspeed_kbs": 220, '
                '"upload_protection_download_limit_kbs": 384, '
                '"upload_protection_min_elapsed_minutes": 0, '
                '"upload_protection_skip_when_downloading_le": 2}]'
            ),
        })

        site_config = brush_config.get_site_config("站点1")

        self.assertFalse(brush_config.upload_protection_enabled)
        self.assertEqual(150, brush_config.upload_protection_low_upspeed_kbs)
        self.assertTrue(site_config.upload_protection_enabled)
        self.assertEqual(90, site_config.upload_protection_low_upspeed_kbs)
        self.assertEqual(220, site_config.upload_protection_good_upspeed_kbs)
        self.assertEqual(384, site_config.upload_protection_download_limit_kbs)
        self.assertEqual(0, site_config.upload_protection_min_elapsed_minutes)
        self.assertEqual(2, site_config.upload_protection_skip_when_downloading_le)

    def test_site_config_allows_legacy_434_delete_fields_but_ignores_removed_delete_and_upload_strategy_fields(self):
        brush_config = self.module.BrushConfig({
            "enable_site_config": True,
            "seed_ratio_check_minutes": 30,
            "seed_size": 10,
            "seed_avgspeed": 20,
            "seed_inactivetime": 30,
            "filter_seeding_torrents": True,
            "delete_when_no_free": False,
            "delete_free_remaining_minutes": 5,
            "yield_guard_enabled": False,
            "upload_protection_enabled": False,
            "site_config": (
                '[{"sitename": "站点1", '
                '"seed_ratio_check_minutes": 5, '
                '"seed_size": 99, '
                '"seed_avgspeed": 88, '
                '"seed_inactivetime": 77, '
                '"filter_seeding_torrents": false, '
                '"delete_when_no_free": true, '
                '"delete_free_remaining_minutes": 3, '
                '"yield_guard_enabled": true, '
                '"upload_protection_enabled": true}]'
            ),
        })

        site_config = brush_config.get_site_config("站点1")

        self.assertEqual(99, site_config.seed_size)
        self.assertEqual(88, site_config.seed_avgspeed)
        self.assertEqual(77, site_config.seed_inactivetime)
        self.assertEqual(30, site_config.seed_ratio_check_minutes)
        self.assertTrue(site_config.filter_seeding_torrents)
        self.assertTrue(site_config.delete_when_no_free)
        self.assertEqual(3, site_config.delete_free_remaining_minutes)
        self.assertFalse(site_config.yield_guard_enabled)
        self.assertTrue(site_config.upload_protection_enabled)

    def test_update_config_persists_upload_protection_and_drops_old_upload_models(self):
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_rehearsal": True,
            "upload_protection_low_upspeed_kbs": 120,
            "upload_protection_download_limit_kbs": 400,
            "upload_protection_skip_when_downloading_le": 2,
            "seed_ratio_check_minutes": 30,
            "filter_seeding_torrents": False,
            "delete_when_no_free": True,
            "delete_free_remaining_minutes": 5,
            "yield_guard_enabled": True,
            "interval_upspeed": 150,
            "seed_ratio_limit_download_kbs": 256,
            "skip_rules_downloading_threshold": 1,
            "seed_size": 10,
        })
        captured = []
        plugin.update_config = lambda config: captured.append(config)

        plugin._BrushFlowLowFreq__update_config()

        config = captured[0]
        self.assertTrue(config.get("upload_protection_enabled"))
        self.assertTrue(config.get("upload_protection_rehearsal"))
        self.assertEqual(120, config.get("upload_protection_low_upspeed_kbs"))
        self.assertEqual(400, config.get("upload_protection_download_limit_kbs"))
        self.assertEqual(2, config.get("upload_protection_skip_when_downloading_le"))
        self.assertEqual(10, config.get("seed_size"))
        self.assertTrue(config.get("delete_when_no_free"))
        self.assertEqual(5, config.get("delete_free_remaining_minutes"))
        self.assertNotIn("seed_ratio_check_minutes", config)
        self.assertNotIn("filter_seeding_torrents", config)
        self.assertNotIn("yield_guard_enabled", config)
        self.assertNotIn("interval_upspeed", config)
        self.assertNotIn("seed_ratio_limit_download_kbs", config)
        self.assertNotIn("skip_rules_downloading_threshold", config)

    def test_get_form_has_upload_protection_tab_and_hides_removed_upload_models(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, defaults = plugin.get_form()

        def collect_texts(node):
            texts = []
            if isinstance(node, dict):
                if "text" in node:
                    texts.append(node.get("text"))
                props = node.get("props") or {}
                if "text" in props:
                    texts.append(props.get("text"))
                for child in node.get("content") or []:
                    texts.extend(collect_texts(child))
            elif isinstance(node, list):
                for child in node:
                    texts.extend(collect_texts(child))
            return texts

        def collect_models(node):
            models = set()
            if isinstance(node, dict):
                props = node.get("props") or {}
                model = props.get("model") or props.get("modelvalue")
                if model:
                    models.add(model)
                for child in node.get("content") or []:
                    models.update(collect_models(child))
            elif isinstance(node, list):
                for child in node:
                    models.update(collect_models(child))
            return models

        models = collect_models(form)
        removed_models = {
            "seed_ratio_check_minutes",
            "filter_seeding_torrents",
            "interval_upspeed",
            "interval_upspeed_check_count",
            "interval_upspeed_low_count",
            "interval_upspeed_start_minutes",
            "interval_upspeed_continuous",
            "interval_upspeed_rehearsal",
            "skip_rules_downloading_threshold",
            "seed_ratio_speed_protect",
            "seed_ratio_limit_download_kbs",
            "seed_ratio_limit_restore_upspeed_kbs",
            "seed_ratio_limit_restore_count",
            "yield_guard_enabled",
        }
        legacy_434_delete_models = {
            "seed_time",
            "hr_seed_time",
            "seed_ratio",
            "seed_ratio_min_30m",
            "seed_size",
            "download_time",
            "seed_avgspeed",
            "seed_inactivetime",
            "delete_except_tags",
            "delete_when_no_free",
            "delete_free_remaining_minutes",
        }

        self.assertIn("上传保护", collect_texts(form))
        self.assertIn("upload_protection_enabled", models)
        self.assertIn("upload_protection_download_limit_kbs", models)
        self.assertIn("upload_protection_skip_when_downloading_le", models)
        self.assertEqual(False, defaults.get("upload_protection_enabled"))
        self.assertEqual(512, defaults.get("upload_protection_download_limit_kbs"))
        self.assertEqual(0, defaults.get("upload_protection_skip_when_downloading_le"))
        self.assertTrue(legacy_434_delete_models.issubset(models), legacy_434_delete_models - models)
        self.assertTrue(removed_models.isdisjoint(models), removed_models & models)

    def test_get_form_delete_tab_hides_legacy_upload_delete_models(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, _ = plugin.get_form()

        def collect_models(node):
            models = set()
            if isinstance(node, dict):
                props = node.get("props") or {}
                model = props.get("model") or props.get("modelvalue")
                if model:
                    models.add(model)
                for child in node.get("content") or []:
                    models.update(collect_models(child))
            elif isinstance(node, list):
                for child in node:
                    models.update(collect_models(child))
            return models

        models = collect_models(form)

        retained_delete_models = {
            "seed_time",
            "hr_seed_time",
            "download_time",
            "delete_size_range",
            "delete_except_tags",
            "proxy_delete",
        }
        legacy_434_delete_models = {
            "seed_ratio",
            "seed_ratio_min_30m",
            "seed_size",
            "seed_avgspeed",
            "seed_inactivetime",
        }
        removed_upload_strategy_models = {
            "seed_ratio_check_minutes",
            "filter_seeding_torrents",
            "seed_ratio_speed_protect",
            "seed_ratio_limit_download_kbs",
            "seed_ratio_limit_restore_upspeed_kbs",
            "seed_ratio_limit_restore_count",
            "interval_upspeed",
            "interval_upspeed_check_count",
            "interval_upspeed_low_count",
            "interval_upspeed_start_minutes",
            "interval_upspeed_continuous",
            "interval_upspeed_rehearsal",
            "skip_rules_downloading_threshold",
        }

        self.assertTrue(retained_delete_models.issubset(models))
        self.assertTrue(legacy_434_delete_models.issubset(models), legacy_434_delete_models - models)
        self.assertTrue(removed_upload_strategy_models.isdisjoint(models),
                        removed_upload_strategy_models & models)

    def test_get_form_groups_selection_delete_and_other_controls_by_tab(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, _ = plugin.get_form()

        def collect_models(node):
            models = []
            if isinstance(node, dict):
                props = node.get("props") or {}
                model = props.get("model") or props.get("modelvalue")
                if model:
                    models.append(model)
                for child in node.get("content") or []:
                    models.extend(collect_models(child))
            elif isinstance(node, list):
                for child in node:
                    models.extend(collect_models(child))
            return models

        def find_component(node, component):
            if isinstance(node, dict):
                if node.get("component") == component:
                    return node
                for child in node.get("content") or []:
                    found = find_component(child, component)
                    if found:
                        return found
            elif isinstance(node, list):
                for child in node:
                    found = find_component(child, component)
                    if found:
                        return found
            return None

        window = find_component(form, "VWindow")
        models_by_tab = {
            item.get("props", {}).get("value"): collect_models(item)
            for item in window.get("content", [])
        }
        row_children_by_tab = {
            tab: [
                child.get("component")
                for row in item.get("content", [])
                if isinstance(row, dict) and row.get("component") == "VRow"
                for child in row.get("content", [])
                if isinstance(child, dict)
            ]
            for tab, item in (
                (item.get("props", {}).get("value"), item)
                for item in window.get("content", [])
            )
        }

        self.assertTrue({
            "free_remaining_time_skip_range",
            "include_second_page",
        }.issubset(models_by_tab["download_tab"]))
        self.assertTrue({
            "delete_size_range",
            "proxy_delete",
            "delete_when_no_free",
            "delete_free_remaining_minutes",
        }.issubset(models_by_tab["delete_tab"]))
        self.assertTrue({
            "brush_sequential",
            "except_subscribe",
            "clear_task",
            "enable_site_config",
            "dialog_closed",
            "sync_official",
        }.issubset(models_by_tab["other_tab"]))
        self.assertNotIn("free_remaining_time_skip_range", models_by_tab["base_tab"])
        self.assertNotIn("delete_size_range", models_by_tab["base_tab"])
        self.assertNotIn("include_second_page", models_by_tab["other_tab"])
        self.assertNotIn("proxy_delete", models_by_tab["other_tab"])
        self.assertTrue(all(component == "VCol" for component in row_children_by_tab["download_tab"]))
        self.assertTrue(all(component == "VCol" for component in row_children_by_tab["delete_tab"]))

    def test_get_form_prunes_empty_form_layout_nodes(self):
        plugin = self._new_qb_plugin()
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.downloader_helper.get_configs = lambda: {}

        form, _ = plugin.get_form()

        def find_component(node, component):
            if isinstance(node, dict):
                if node.get("component") == component:
                    return node
                for child in node.get("content") or []:
                    found = find_component(child, component)
                    if found:
                        return found
            elif isinstance(node, list):
                for child in node:
                    found = find_component(child, component)
                    if found:
                        return found
            return None

        def has_empty_layout(node):
            if isinstance(node, dict):
                component = node.get("component")
                content = node.get("content")
                if component in {"VRow", "VCol"} and not content:
                    return True
                if isinstance(content, list):
                    return any(has_empty_layout(child) for child in content)
            elif isinstance(node, list):
                return any(has_empty_layout(child) for child in node)
            return False

        window = find_component(form, "VWindow")
        self.assertFalse(has_empty_layout(window))

    def test_get_page_download_dashboard_uses_popover_dialogs_without_anchor_targets(self):
        now = datetime.now()
        today_completed = int((now - timedelta(hours=1)).timestamp())
        yesterday_completed = int((now - timedelta(days=1, hours=1)).timestamp())
        plugin = self._new_qb_plugin()
        self._attach_memory_store(plugin, {
            "torrents": {
                "downloading": {
                    "site_name": "站点1",
                    "title": "正在下载任务",
                    "description": "下载中",
                    "size": 100,
                    "downloaded": 50,
                    "total_size": 100,
                    "uploaded": 10,
                    "seeding_time": 0,
                    "first_downloaded_time": int((now - timedelta(minutes=30)).timestamp()),
                    "first_uploaded_time": int((now - timedelta(minutes=20)).timestamp()),
                    "avg_downspeed": 2048,
                    "avg_upspeed": 1024,
                    "last_check_interval_upspeed": 512,
                    "last_check_interval_downspeed": 4096,
                    "upload_protection_stage": "limited",
                    "upload_protection_last_reason": "上传保护：继续观察",
                    "upload_protection_interval_records": [{
                        "time": int((now - timedelta(minutes=10)).timestamp()),
                        "interval_seconds": 120,
                        "interval_uploaded": 10 * 1024,
                        "interval_downloaded": 60 * 1024,
                        "interval_upspeed": 85 * 1024,
                        "interval_downspeed": 512 * 1024,
                        "low_streak": 2,
                        "good_streak": 0,
                        "no_upload_streak": 0,
                        "planned_action": "limit",
                        "should_delete": False,
                        "reason": "检查间低速，准备限速",
                    }],
                    "upload_protection_action_records": [{
                        "time": int((now - timedelta(minutes=9)).timestamp()),
                        "action": "limit",
                        "executed": True,
                        "rehearsal": False,
                        "reason": "检查间低速，执行限速",
                    }],
                },
                "today_completed": {
                    "site_name": "站点1",
                    "title": "今日完成任务",
                    "description": "已完成",
                    "size": 100,
                    "downloaded": 100,
                    "total_size": 100,
                    "uploaded": 20,
                    "seeding_time": 60,
                    "download_dashboard_completed_time": today_completed,
                    "avg_downspeed": 4096,
                    "avg_upspeed": 2048,
                    "upload_protection_stage": "released",
                    "upload_protection_last_reason": "上传保护：完全放开下载限速",
                    "deleted": True,
                },
                "old_completed": {
                    "site_name": "站点1",
                    "title": "昨日完成任务",
                    "downloaded": 100,
                    "total_size": 100,
                    "seeding_time": 86400,
                    "download_dashboard_completed_time": yesterday_completed,
                },
                "deleted": {
                    "site_name": "站点1",
                    "title": "已删除任务",
                    "downloaded": 10,
                    "total_size": 100,
                    "deleted": True,
                },
            }
        })

        page = plugin.get_page()

        def collect_text(node):
            texts = []
            if isinstance(node, dict):
                for key in ("text", "html"):
                    value = node.get(key)
                    if value is not None:
                        texts.append(str(value))
                props = node.get("props")
                if isinstance(props, dict):
                    for key in ("label", "title"):
                        value = props.get(key)
                        if value is not None:
                            texts.append(str(value))
                content = node.get("content")
                if isinstance(content, list):
                    for child in content:
                        texts.append(collect_text(child))
            elif isinstance(node, list):
                for child in node:
                    texts.append(collect_text(child))
            return "\n".join(texts)

        def collect_components(node):
            components = []
            if isinstance(node, dict):
                component = node.get("component")
                if component:
                    components.append(component)
                content = node.get("content")
                if isinstance(content, list):
                    for child in content:
                        components.extend(collect_components(child))
            elif isinstance(node, list):
                for child in node:
                    components.extend(collect_components(child))
            return components

        def collect_props(node, component_name):
            props_list = []
            if isinstance(node, dict):
                if node.get("component") == component_name:
                    props_list.append(node.get("props") or {})
                content = node.get("content")
                if isinstance(content, list):
                    for child in content:
                        props_list.extend(collect_props(child, component_name))
            elif isinstance(node, list):
                for child in node:
                    props_list.extend(collect_props(child, component_name))
            return props_list

        def collect_table_rows(node):
            rows = []
            if isinstance(node, dict):
                if node.get("component") == "tr":
                    rows.append(node)
                content = node.get("content")
                if isinstance(content, list):
                    for child in content:
                        rows.extend(collect_table_rows(child))
            elif isinstance(node, list):
                for child in node:
                    rows.extend(collect_table_rows(child))
            return rows

        text = collect_text(page)
        components = collect_components(page)
        button_props = collect_props(page, "button")
        popover_props = [
            props for props in collect_props(page, "div")
            if "brush-dashboard-popover" in str(props.get("class", ""))
        ]
        rows = collect_table_rows(page)
        downloading_row = next(row for row in rows if "正在下载任务" in collect_text(row))
        self.assertIn("下载任务看板", text)
        self.assertIn("正在下载中", text)
        self.assertIn("今日已完成", text)
        self.assertIn("正在下载任务", text)
        self.assertIn("今日完成任务", text)
        self.assertIn("有数据上传时间", text)
        self.assertIn("平均下载速度", text)
        self.assertIn("查看最近原因", text)
        self.assertIn("查看详细记录", text)
        self.assertIn("检查间低速，准备限速", text)
        self.assertIn("检查间低速，执行限速", text)
        self.assertIn("动作 降低下载速度", text)
        self.assertNotIn("VSwitch", collect_components(downloading_row))
        self.assertNotIn("VDialog", collect_components(downloading_row))
        self.assertNotIn("VExpansionPanels", components)
        self.assertNotIn("template", components)
        self.assertGreaterEqual(len(popover_props), 4)
        self.assertTrue(any(props.get("for", "").startswith("download_dashboard_reason_")
                            for props in collect_props(page, "label")))
        self.assertTrue(any(props.get("for", "").startswith("download_dashboard_records_")
                            for props in collect_props(page, "label")))
        self.assertFalse(any(str(props.get("href", "")).startswith("#download_dashboard_")
                             for props in collect_props(page, "a")))
        self.assertTrue(any("brush-dashboard-popover-toggle" in str(props.get("class", ""))
                            for props in collect_props(page, "input")))
        self.assertIn("查看最近原因", collect_text(downloading_row))
        self.assertIn("查看详细记录", collect_text(downloading_row))
        self.assertNotIn("检查间低速，准备限速", collect_text(downloading_row))
        self.assertNotIn("动作 降低下载速度", collect_text(downloading_row))
        self.assertNotIn("昨日完成任务", text)
        self.assertNotIn("已删除任务", text)

    def test_upload_protection_detail_log_records_interval_and_action_history(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_detail_log": True,
            "upload_protection_rehearsal": False,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_low_limit_checks": 2,
            "upload_protection_min_elapsed_minutes": 0,
        }, downloader=downloader)
        plugin._is_qb = True
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60
        torrent = {
            "hash": "abcdef",
            "name": "detail torrent",
            "tags": "刷流",
            "state": "downloading",
            "downloaded": 50,
            "uploaded": 10,
            "total_size": 100,
            "ratio": 0.2,
            "added_on": int((datetime.now() - timedelta(minutes=30)).timestamp()),
            "completion_on": 0,
            "last_activity": int(datetime.now().timestamp()),
            "tracker": "https://tracker.example",
        }
        torrent_task = {
            "site_name": "站点1",
            "title": "detail torrent",
            "first_downloaded_time": 1,
            "last_check_interval_upspeed": 100 * 1024,
            "last_check_interval_upspeed_valid": True,
            "last_check_interval_uploaded": 1000,
            "last_check_interval_downspeed": 300 * 1024,
            "last_check_interval_downspeed_valid": True,
            "last_check_interval_downloaded": 3000,
            "last_check_interval_seconds": 10,
            "upload_protection_low_streak": 2,
            "upload_protection_stage": "normal",
        }

        plugin._BrushFlowLowFreq__apply_upload_protection_actions(
            torrents=[torrent],
            torrent_tasks={"abcdef": torrent_task},
            delete_message_map={},
        )

        interval_records = torrent_task.get("upload_protection_interval_records") or []
        action_records = torrent_task.get("upload_protection_action_records") or []
        self.assertEqual(1, len(interval_records))
        self.assertEqual("limit", interval_records[-1].get("planned_action"))
        self.assertIn("降低下载速度", interval_records[-1].get("reason", ""))
        self.assertEqual(1, len(action_records))
        self.assertEqual("limit", action_records[-1].get("action"))
        self.assertTrue(action_records[-1].get("executed"))

    def test_prune_download_dashboard_history_keeps_only_downloading_and_today_completed(self):
        now = datetime(2026, 6, 26, 12, 0, 0)
        today_completed = int((now - timedelta(hours=1)).timestamp())
        yesterday_completed = int((now - timedelta(days=1)).timestamp())
        plugin = self._new_qb_plugin()
        torrent_tasks = {
            "downloading": {
                "downloaded": 50,
                "total_size": 100,
                "seeding_time": 0,
                "upload_protection_interval_records": [{"id": "keep-downloading"}],
                "upload_protection_action_records": [{"id": "keep-downloading"}],
            },
            "today_completed": {
                "downloaded": 100,
                "total_size": 100,
                "seeding_time": 60,
                "download_dashboard_completed_time": today_completed,
                "deleted": True,
                "upload_protection_interval_records": [{"id": "keep-today"}],
                "upload_protection_action_records": [{"id": "keep-today"}],
            },
            "old_completed": {
                "downloaded": 100,
                "total_size": 100,
                "seeding_time": 86400,
                "download_dashboard_completed_time": yesterday_completed,
                "upload_protection_interval_records": [{"id": "drop-old"}],
                "upload_protection_action_records": [{"id": "drop-old"}],
            },
        }

        plugin._BrushFlowLowFreq__prune_download_dashboard_history(torrent_tasks, now=now.timestamp())

        self.assertEqual([{"id": "keep-downloading"}],
                         torrent_tasks["downloading"].get("upload_protection_interval_records"))
        self.assertEqual([{"id": "keep-today"}],
                         torrent_tasks["today_completed"].get("upload_protection_interval_records"))
        self.assertEqual([], torrent_tasks["old_completed"].get("upload_protection_interval_records"))
        self.assertEqual([], torrent_tasks["old_completed"].get("upload_protection_action_records"))

    def test_download_dashboard_completed_time_prefers_downloader_completion_time(self):
        plugin = self._new_qb_plugin()
        completion_on = 1700000000
        torrent = {
            "hash": "abcdef",
            "name": "completed torrent",
            "tags": "刷流",
            "downloaded": 100,
            "total_size": 100,
            "uploaded": 10,
            "ratio": 0.1,
            "added_on": completion_on - 3600,
            "completion_on": completion_on,
            "last_activity": completion_on,
            "tracker": "tracker",
        }

        original_time = self.module.time.time
        self.module.time.time = lambda: completion_on + 600
        try:
            torrent_info = plugin._BrushFlowLowFreq__get_torrent_info(torrent)
            completed_time = plugin._BrushFlowLowFreq__get_download_dashboard_completed_time(
                torrent_task={},
                torrent_info=torrent_info,
                now=completion_on + 600,
            )
        finally:
            self.module.time.time = original_time

        self.assertEqual(completion_on, completed_time)

    def test_qb_torrent_info_keeps_downloader_completion_time_for_dashboard(self):
        plugin = self._new_qb_plugin()
        completion_on = 1700000000
        torrent_info = plugin._BrushFlowLowFreq__get_torrent_info({
            "hash": "abcdef",
            "name": "completed torrent",
            "added_on": completion_on - 3600,
            "completion_on": completion_on,
            "downloaded": 100,
            "total_size": 100,
            "uploaded": 10,
            "ratio": 0.1,
            "last_activity": completion_on,
            "tracker": "tracker",
        })

        completed_time = plugin._BrushFlowLowFreq__get_download_dashboard_completed_time(
            torrent_task={},
            torrent_info=torrent_info,
            now=completion_on + 600,
        )

        self.assertEqual(completion_on, torrent_info.get("completion_on"))
        self.assertEqual(completion_on, completed_time)

    def test_upload_protection_low_speed_limits_then_strict_limits(self):
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_low_limit_checks": 2,
            "upload_protection_low_strict_checks": 3,
            "upload_protection_min_elapsed_minutes": 0,
        })
        torrent_info = {"downloaded": 50, "total_size": 100, "seeding_time": 0}
        torrent_task = {
            "first_downloaded_time": 1,
            "last_check_interval_upspeed": 100 * 1024,
            "last_check_interval_upspeed_valid": True,
            "upload_protection_low_streak": 1,
            "upload_protection_stage": "normal",
        }
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_upload_protection(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("limited", torrent_task.get("upload_protection_stage"))
        self.assertEqual("limit", torrent_task.get("upload_protection_pending_action"))

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_upload_protection(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("strict_limited", torrent_task.get("upload_protection_stage"))
        self.assertEqual("strict_limit", torrent_task.get("upload_protection_pending_action"))

    def test_upload_protection_good_speed_restores_then_releases_without_resetting_streak(self):
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_good_upspeed_kbs": 150,
            "upload_protection_good_restore_checks": 2,
            "upload_protection_good_release_checks": 3,
            "upload_protection_min_elapsed_minutes": 0,
        })
        torrent_info = {"downloaded": 50, "total_size": 100, "seeding_time": 0}
        torrent_task = {
            "first_downloaded_time": 1,
            "last_check_interval_upspeed": 200 * 1024,
            "last_check_interval_upspeed_valid": True,
            "upload_protection_good_streak": 1,
            "upload_protection_stage": "limited",
        }
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_upload_protection(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("normal", torrent_task.get("upload_protection_stage"))
        self.assertEqual("restore_limit", torrent_task.get("upload_protection_pending_action"))
        self.assertEqual(2, torrent_task.get("upload_protection_good_streak"))
        self.assertTrue(torrent_task.get("upload_protection_release_eligible"))

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_upload_protection(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("released", torrent_task.get("upload_protection_stage"))
        self.assertEqual("release_limit", torrent_task.get("upload_protection_pending_action"))
        self.assertEqual(3, torrent_task.get("upload_protection_good_streak"))

    def test_upload_protection_53kbps_does_not_restore_or_delete_with_150kbps_thresholds(self):
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_good_upspeed_kbs": 150,
            "upload_protection_low_limit_checks": 3,
            "upload_protection_good_restore_checks": 1,
            "upload_protection_no_upload_kbs": 50,
            "upload_protection_no_upload_checks": 1,
            "upload_protection_min_elapsed_minutes": 0,
        })
        torrent_info = {"downloaded": 50, "total_size": 100, "seeding_time": 0}
        torrent_task = {
            "first_downloaded_time": 1,
            "last_check_interval_upspeed": int(53.3 * 1024),
            "last_check_interval_upspeed_valid": True,
            "upload_protection_low_streak": 0,
            "upload_protection_good_streak": 0,
            "upload_protection_no_upload_streak": 0,
            "upload_protection_stage": "limited",
        }
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_upload_protection(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("limited", torrent_task.get("upload_protection_stage"))
        self.assertEqual(1, torrent_task.get("upload_protection_low_streak"))
        self.assertEqual(0, torrent_task.get("upload_protection_good_streak"))
        self.assertNotEqual("restore_limit", torrent_task.get("upload_protection_pending_action"))
        self.assertIn("继续观察", reason)

    def test_upload_protection_zero_speed_does_not_restore_with_150kbps_thresholds(self):
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_good_upspeed_kbs": 150,
            "upload_protection_low_limit_checks": 3,
            "upload_protection_good_restore_checks": 1,
            "upload_protection_no_upload_kbs": 0,
            "upload_protection_min_elapsed_minutes": 0,
        })
        torrent_info = {"downloaded": 50, "total_size": 100, "seeding_time": 0}
        torrent_task = {
            "first_downloaded_time": 1,
            "last_check_interval_upspeed": 0,
            "last_check_interval_upspeed_valid": True,
            "upload_protection_low_streak": 0,
            "upload_protection_good_streak": 0,
            "upload_protection_stage": "limited",
        }
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_upload_protection(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info=torrent_info,
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertEqual("limited", torrent_task.get("upload_protection_stage"))
        self.assertEqual(1, torrent_task.get("upload_protection_low_streak"))
        self.assertEqual(0, torrent_task.get("upload_protection_good_streak"))
        self.assertNotEqual("restore_limit", torrent_task.get("upload_protection_pending_action"))

    def test_upload_protection_skips_completed_torrents_without_updating_streaks(self):
        plugin = self._new_qb_plugin({"upload_protection_enabled": True})
        torrent_task = {
            "last_check_interval_upspeed": 0,
            "last_check_interval_upspeed_valid": True,
            "upload_protection_low_streak": 2,
            "upload_protection_stage": "limited",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_upload_protection(
            site_name="站点1",
            brush_config=plugin._brush_config,
            torrent_info={"downloaded": 100, "total_size": 100, "seeding_time": 3600},
            torrent_task=torrent_task,
        )

        self.assertFalse(should_delete, reason)
        self.assertFalse(torrent_task.get("upload_protection_evaluated_in_check"))
        self.assertEqual(2, torrent_task.get("upload_protection_low_streak"))
        self.assertEqual("limited", torrent_task.get("upload_protection_stage"))

    def test_upload_protection_qb_actions_apply_expected_download_limits(self):
        class FakeQbc:
            def __init__(self):
                self.calls = []

            def torrents_set_download_limit(self, **kwargs):
                self.calls.append(kwargs)

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_rehearsal": False,
            "upload_protection_download_limit_kbs": 512,
            "dl_speed": 128,
        }, downloader=downloader)

        self.assertTrue(plugin._BrushFlowLowFreq__apply_qb_upload_protection_action(
            torrent_hash="abc",
            action="limit",
            brush_config=plugin._brush_config,
            torrent_task={},
        ))
        self.assertTrue(plugin._BrushFlowLowFreq__apply_qb_upload_protection_action(
            torrent_hash="abc",
            action="strict_limit",
            brush_config=plugin._brush_config,
            torrent_task={},
        ))
        self.assertTrue(plugin._BrushFlowLowFreq__apply_qb_upload_protection_action(
            torrent_hash="abc",
            action="restore_limit",
            brush_config=plugin._brush_config,
            torrent_task={},
        ))
        self.assertTrue(plugin._BrushFlowLowFreq__apply_qb_upload_protection_action(
            torrent_hash="abc",
            action="release_limit",
            brush_config=plugin._brush_config,
            torrent_task={},
        ))

        self.assertEqual(512 * 1024, downloader.qbc.calls[0]["limit"])
        self.assertEqual(256 * 1024, downloader.qbc.calls[1]["limit"])
        self.assertEqual(128 * 1024, downloader.qbc.calls[2]["limit"])
        self.assertEqual(0, downloader.qbc.calls[3]["limit"])

    def test_upload_protection_restore_limit_prefers_original_download_limit_snapshot(self):
        class FakeQbc:
            def __init__(self):
                self.calls = []

            def torrents_set_download_limit(self, **kwargs):
                self.calls.append(kwargs)

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_rehearsal": False,
            "upload_protection_download_limit_kbs": 512,
            "dl_speed": 60,
        }, downloader=downloader)
        torrent_task = {
            "download_limit": 200 * 1024,
        }

        self.assertTrue(plugin._BrushFlowLowFreq__apply_qb_upload_protection_action(
            torrent_hash="abc",
            action="limit",
            brush_config=plugin._brush_config,
            torrent_task=torrent_task,
        ))
        self.assertEqual(200 * 1024, torrent_task.get("upload_protection_original_download_limit"))

        self.assertTrue(plugin._BrushFlowLowFreq__apply_qb_upload_protection_action(
            torrent_hash="abc",
            action="restore_limit",
            brush_config=plugin._brush_config,
            torrent_task=torrent_task,
        ))
        self.assertEqual(200 * 1024, downloader.qbc.calls[-1]["limit"])

    def test_check_applies_upload_protection_to_downloading_managed_torrents(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

            def get_torrents(self):
                return [{
                    "hash": "abcdef",
                    "name": "upload protection torrent",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.5,
                    "downloaded": 200000,
                    "uploaded": 10,
                    "total_size": 1000000,
                    "ratio": 0.1,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }], None

            def delete_torrents(self, ids, delete_file=True):
                return True

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_rehearsal": False,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_low_limit_checks": 2,
            "upload_protection_download_limit_kbs": 512,
            "upload_protection_min_elapsed_minutes": 0,
            "freeleech": "",
            "hr": "no",
        }, downloader=downloader)
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "upload protection torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 1000,
                "uploaded": 0,
                "total_size": 1000000,
                "ratio": 0.1,
                "seeding_time": 0,
                "first_downloaded_time": 1,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 0,
                "upload_protection_low_streak": 1,
                "upload_protection_stage": "normal",
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {},
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        start_info_count = len(self.module.logger.info_messages)
        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([(["abcdef"], 512 * 1024)], downloader.qbc.download_limits)
        self.assertEqual("limited", torrent_tasks["abcdef"].get("upload_protection_stage"))
        self.assertTrue(torrent_tasks["abcdef"].get("upload_protection_evaluated_in_check"))

    def test_check_upload_protection_small_pool_exception_releases_existing_limits(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

            def get_torrents(self):
                return [{
                    "hash": "abcdef",
                    "name": "upload protection torrent",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.5,
                    "downloaded": 200000,
                    "uploaded": 10,
                    "total_size": 1000000,
                    "ratio": 0.1,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }], None

            def delete_torrents(self, ids, delete_file=True):
                return True

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_rehearsal": False,
            "upload_protection_skip_when_downloading_le": 1,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_low_limit_checks": 1,
            "upload_protection_no_upload_kbs": 150,
            "upload_protection_no_upload_checks": 1,
            "upload_protection_min_elapsed_minutes": 0,
            "upload_protection_min_downloaded_gb": 0,
            "freeleech": "",
            "hr": "no",
        }, downloader=downloader)
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "upload protection torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 1000,
                "uploaded": 0,
                "total_size": 1000000,
                "ratio": 0.1,
                "seeding_time": 0,
                "first_downloaded_time": 1,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 0,
                "upload_protection_low_streak": 3,
                "upload_protection_no_upload_streak": 3,
                "upload_protection_stage": "limited",
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {},
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        start_info_count = len(self.module.logger.info_messages)
        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([(["abcdef"], 0)], downloader.qbc.download_limits)
        self.assertEqual("released", torrent_tasks["abcdef"].get("upload_protection_stage"))
        self.assertFalse(torrent_tasks["abcdef"].get("upload_protection_evaluated_in_check"))
        self.assertFalse(torrent_tasks["abcdef"].get("deleted"))
        self.assertIn("下载中任务数 1 小于等于例外阈值 1",
                      torrent_tasks["abcdef"].get("upload_protection_last_reason", ""))
        new_logs = self.module.logger.info_messages[start_info_count:]
        self.assertTrue(any("下载中任务数 1 小于等于例外阈值 1" in msg and "放开下载限速" in msg
                            for msg in new_logs), new_logs)

    def test_check_skips_upload_protection_for_completed_managed_torrents(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes, limit):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

            def get_torrents(self):
                return [{
                    "hash": "abcdef",
                    "name": "completed upload protection torrent",
                    "tags": "刷流",
                    "state": "stalledUP",
                    "progress": 1.0,
                    "downloaded": 1000000,
                    "uploaded": 10,
                    "total_size": 1000000,
                    "ratio": 0.1,
                    "added_on": 1,
                    "completion_on": 1,
                    "last_activity": 1,
                    "tracker": "tracker",
                }], None

            def delete_torrents(self, ids, delete_file=True):
                return True

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": True,
            "upload_protection_rehearsal": False,
            "upload_protection_low_upspeed_kbs": 150,
            "upload_protection_low_limit_checks": 2,
            "upload_protection_download_limit_kbs": 512,
            "upload_protection_min_elapsed_minutes": 0,
            "freeleech": "",
            "hr": "no",
        }, downloader=downloader)
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "completed upload protection torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 1000000,
                "uploaded": 0,
                "total_size": 1000000,
                "ratio": 0.1,
                "seeding_time": 3600,
                "first_downloaded_time": 1,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 1000000,
                "upload_protection_low_streak": 1,
                "upload_protection_stage": "normal",
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {},
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([], downloader.qbc.download_limits)
        self.assertEqual("normal", torrent_tasks["abcdef"].get("upload_protection_stage"))
        self.assertFalse(torrent_tasks["abcdef"].get("upload_protection_evaluated_in_check"))
        self.assertEqual(1, torrent_tasks["abcdef"].get("upload_protection_low_streak"))

    def test_check_does_not_run_legacy_yield_guard_when_new_upload_protection_disabled(self):
        class FakeQbc:
            def __init__(self):
                self.download_limits = []

            def torrents_set_download_limit(self, torrent_hashes=None, limit=None):
                self.download_limits.append((torrent_hashes, limit))

        class FakeDownloader:
            def __init__(self):
                self.qbc = FakeQbc()

            def is_inactive(self):
                return False

            def get_torrents(self):
                return [{
                    "hash": "abcdef",
                    "name": "legacy yield guard torrent",
                    "tags": "刷流",
                    "state": "downloading",
                    "progress": 0.5,
                    "downloaded": 800000,
                    "uploaded": 0,
                    "total_size": 1000000,
                    "ratio": 0,
                    "dlspeed": 2048 * 1024,
                    "upspeed": 0,
                    "added_on": 1,
                    "completion_on": 0,
                    "last_activity": 1,
                    "tracker": "tracker",
                }], None

            def delete_torrents(self, ids, delete_file=True):
                return True

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin({
            "upload_protection_enabled": False,
            "yield_guard_enabled": True,
            "yield_guard_rehearsal": False,
            "yield_guard_high_download_kbs": 1,
            "yield_guard_low_upload_kbs": 500,
            "yield_guard_bad_checks": 1,
            "yield_guard_min_downloaded_gb": 0,
            "yield_guard_min_progress_percent": 0,
            "freeleech": "",
            "hr": "no",
        }, downloader=downloader)
        plugin._BrushFlowLowFreq__check_and_resolve_plugin_conflict = lambda: True
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        torrent_tasks = {
            "abcdef": {
                "site": 1,
                "site_name": "站点1",
                "title": "legacy yield guard torrent",
                "description": "desc",
                "hit_and_run": False,
                "time": 0,
                "downloaded": 1,
                "uploaded": 0,
                "total_size": 1000000,
                "ratio": 0,
                "seeding_time": 0,
                "first_downloaded_time": 1,
                "first_uploaded_time": 1,
                "last_check_time": 1,
                "last_check_uploaded": 0,
                "last_check_downloaded": 0,
                "deleted": False,
            }
        }
        plugin.get_data = lambda key: {
            "torrents": torrent_tasks,
            "unmanaged": {},
        }.get(key, {})
        plugin.save_data = lambda *args, **kwargs: None
        original_time = self.module.time.time
        self.module.time.time = lambda: 2
        try:
            plugin.check()
        finally:
            self.module.time.time = original_time

        self.assertEqual([], downloader.qbc.download_limits)
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_evaluated_in_check"))
        self.assertIsNone(torrent_tasks["abcdef"].get("yield_guard_pending_action"))
        self.assertFalse(torrent_tasks["abcdef"].get("deleted"))

    def test_legacy_yield_guard_pool_no_longer_blocks_new_brush_precondition(self):
        plugin = self._new_qb_plugin({
            "yield_guard_enabled": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 1,
            "yield_guard_probe_slots": 0,
        })
        busy_tasks = {
            "good": {
                "deleted": False,
                "yield_guard_good_protected": True,
            }
        }
        for index in range(6):
            busy_tasks[f"probe{index}"] = {
                "deleted": False,
                "yield_guard_good_protected": False,
            }
        plugin.get_data = lambda key: {
            "torrents": busy_tasks
        }.get(key, {})

        passed, reason = plugin._BrushFlowLowFreq__evaluate_pre_conditions_for_brush(
            include_network_conditions=False
        )

        self.assertTrue(passed, reason)

    def test_managed_downloading_count_uses_live_data_without_global_threshold(self):
        plugin = self._new_qb_plugin({"skip_rules_downloading_threshold": 0})
        torrent_tasks = {
            "ABC": {"deleted": False},
            "DEF": {"deleted": False},
            "GHI": {"deleted": True},
        }
        seeding_torrents = {
            "abc": {"hash": "abc", "downloaded": 50, "total_size": 100},
            "def": {"hash": "def", "downloaded": 100, "total_size": 100},
            "ghi": {"hash": "ghi", "downloaded": 1, "total_size": 100},
        }

        count = plugin._BrushFlowLowFreq__count_managed_downloading_torrents(
            torrent_tasks=torrent_tasks,
            seeding_torrents_dict=seeding_torrents,
        )

        self.assertEqual(1, count)

    def test_completed_torrent_ignores_removed_download_protection_fields(self):
        plugin = self._new_qb_plugin({
            "skip_rules_downloading_threshold": 1,
            "interval_upspeed": 150,
            "interval_upspeed_check_count": 5,
            "interval_upspeed_low_count": 3,
            "interval_upspeed_start_minutes": 0,
        })
        torrent_info = {
            "seeding_time": 3600,
            "ratio": 1,
            "uploaded": 100,
            "downloaded": 100,
            "total_size": 100,
            "dltime": 3600,
            "avg_upspeed": 2 * 1024,
            "iatime": 0,
        }
        torrent_task = {
            "site_name": "天空",
            "first_uploaded_time": 1,
            "last_check_interval_upspeed": int(2.3 * 1024),
            "last_check_interval_upspeed_valid": True,
            "interval_upspeed_hit_records": [1, 1, 1, 1],
        }
        original_get_task_elapsed_minutes = plugin._BrushFlowLowFreq__get_task_elapsed_minutes
        plugin._BrushFlowLowFreq__get_task_elapsed_minutes = lambda value: 60
        try:
            should_delete, reason = plugin._BrushFlowLowFreq__evaluate_conditions_for_delete(
                site_name="天空",
                torrent_info=torrent_info,
                torrent_task=torrent_task,
                downloading_count=1,
            )
        finally:
            plugin._BrushFlowLowFreq__get_task_elapsed_minutes = original_get_task_elapsed_minutes

        self.assertFalse(should_delete, reason)
        self.assertEqual("未能满足设置的删除条件", reason)
        self.assertNotIn("命中删除条件", reason)

    def test_brush_added_task_includes_live_count_and_timer_fields(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def add_torrent(self, **kwargs):
                return True

            def get_torrent_id_by_tag(self, tags):
                return "ABCDEF"

        plugin = self._new_qb_plugin(downloader=FakeDownloader())
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kwargs: None)
        plugin.sites_helper = SimpleNamespace(get_indexers=lambda: [])
        plugin.site_oper = SimpleNamespace(get=lambda siteid: SimpleNamespace(id=siteid, name="站点1", domain="site1.test"))
        plugin.torrents_chain = SimpleNamespace(browse=lambda domain: [
            SimpleNamespace(
                site=1,
                site_name="站点1",
                site_proxy=False,
                site_cookie="",
                site_ua="ua",
                title="new torrent",
                description="desc",
                imdbid=None,
                page_url="details.php?id=1",
                pubdate="",
                date_elapsed=None,
                freedate="",
                uploadvolumefactor=1,
                downloadvolumefactor=1,
                hit_and_run=False,
                volume_factor="",
                freedate_diff="",
                enclosure="magnet:?xt=urn:btih:ABCDEF",
                size=1234,
                seeders=1,
            )
        ])

        torrent_tasks = {}
        statistic_info = {"count": 0}
        plugin._BrushFlowLowFreq__brush_site_torrents(
            siteid=1,
            torrent_tasks=torrent_tasks,
            statistic_info=statistic_info,
            subscribe_titles=set(),
        )

        self.assertIn("abcdef", torrent_tasks)
        task = torrent_tasks["abcdef"]
        self.assertEqual(1234, task.get("total_size"))
        self.assertIsNone(task.get("first_downloaded_time"))
        self.assertIsNone(task.get("first_uploaded_time"))
        self.assertEqual([], task.get("interval_upspeed_hit_records"))

    def test_qb_download_retries_hash_lookup_by_tag(self):
        class FakeDownloader:
            def __init__(self):
                self.lookups = 0

            def is_inactive(self):
                return False

            def add_torrent(self, **kwargs):
                return True

            def get_torrent_id_by_tag(self, tags):
                self.lookups += 1
                return None if self.lookups == 1 else "ABCDEF"

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin(downloader=downloader)
        torrent = SimpleNamespace(
            site_name="站点1",
            site_proxy=False,
            site_cookie="",
            site_ua="ua",
            site=1,
            title="retry torrent",
            enclosure="magnet:?xt=urn:btih:ABCDEF",
        )
        original_sleep = self.module.time.sleep
        self.module.time.sleep = lambda seconds: None
        try:
            torrent_hash = plugin._BrushFlowLowFreq__download(torrent)
        finally:
            self.module.time.sleep = original_sleep

        self.assertEqual("abcdef", torrent_hash)
        self.assertEqual(2, downloader.lookups)

    def test_qb_download_falls_back_to_magnet_hash_when_tag_lookup_fails(self):
        class FakeDownloader:
            def is_inactive(self):
                return False

            def add_torrent(self, **kwargs):
                return True

            def get_torrent_id_by_tag(self, tags):
                return None

        plugin = self._new_qb_plugin(downloader=FakeDownloader())
        torrent = SimpleNamespace(
            site_name="站点1",
            site_proxy=False,
            site_cookie="",
            site_ua="ua",
            site=1,
            title="fallback torrent",
            enclosure="magnet:?xt=urn:btih:ABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD",
        )
        original_sleep = self.module.time.sleep
        self.module.time.sleep = lambda seconds: None
        try:
            torrent_hash = plugin._BrushFlowLowFreq__download(torrent)
        finally:
            self.module.time.sleep = original_sleep

        self.assertEqual("abcdefabcdefabcdefabcdefabcdefabcdefabcd", torrent_hash)

    def test_qb_download_uses_added_hash_diff_when_tag_lookup_fails_for_download_url(self):
        class FakeDownloader:
            def __init__(self):
                self.added = False

            def is_inactive(self):
                return False

            def get_torrents(self):
                torrents = [{"hash": "OLDHASH"}]
                if self.added:
                    torrents.append({"hash": "NEWHASH"})
                return torrents, None

            def add_torrent(self, **kwargs):
                self.added = True
                self.added_content = kwargs.get("content")
                return True

            def get_torrent_id_by_tag(self, tags):
                return None

        class FakeRequestUtils:
            def __init__(self, **kwargs):
                pass

            def get_res(self, url):
                return SimpleNamespace(ok=True, content=b"not-a-bencoded-torrent")

        downloader = FakeDownloader()
        plugin = self._new_qb_plugin(downloader=downloader)
        torrent = SimpleNamespace(
            site_name="站点1",
            site_proxy=False,
            site_cookie="",
            site_ua="ua",
            site=1,
            title="url torrent",
            enclosure="https://tracker.example/download.php?id=1",
        )
        original_request_utils = self.module.RequestUtils
        original_sleep = self.module.time.sleep
        self.module.RequestUtils = FakeRequestUtils
        self.module.time.sleep = lambda seconds: None
        try:
            torrent_hash = plugin._BrushFlowLowFreq__download(torrent)
        finally:
            self.module.RequestUtils = original_request_utils
            self.module.time.sleep = original_sleep

        self.assertEqual(b"not-a-bencoded-torrent", downloader.added_content)
        self.assertEqual("newhash", torrent_hash)

    def test_qb_download_extracts_torrent_file_info_hash_when_tag_lookup_fails(self):
        info_dict = b"d4:name4:test12:piece lengthi16384e6:pieces20:abcdefghijklmnopqrste"
        torrent_bytes = b"d4:infod4:name4:test12:piece lengthi16384e6:pieces20:abcdefghijklmnopqrstee"
        expected_hash = hashlib.sha1(info_dict).hexdigest()

        class FakeDownloader:
            def is_inactive(self):
                return False

            def add_torrent(self, **kwargs):
                return True

            def get_torrent_id_by_tag(self, tags):
                return None

        class FakeRequestUtils:
            def __init__(self, **kwargs):
                pass

            def get_res(self, url):
                return SimpleNamespace(ok=True, content=torrent_bytes)

        plugin = self._new_qb_plugin(downloader=FakeDownloader())
        torrent = SimpleNamespace(
            site_name="站点1",
            site_proxy=False,
            site_cookie="",
            site_ua="ua",
            site=1,
            title="torrent file",
            enclosure="https://tracker.example/download.php?id=2",
        )
        original_request_utils = self.module.RequestUtils
        original_sleep = self.module.time.sleep
        self.module.RequestUtils = FakeRequestUtils
        self.module.time.sleep = lambda seconds: None
        try:
            torrent_hash = plugin._BrushFlowLowFreq__download(torrent)
        finally:
            self.module.RequestUtils = original_request_utils
            self.module.time.sleep = original_sleep

        self.assertEqual(expected_hash, torrent_hash)

    def test_daily_transfer_statistics_first_run_only_initializes_baseline(self):
        plugin = self._new_plugin({})
        store = self._attach_memory_store(plugin)
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

        self.assertEqual({}, store["daily_statistic"])
        self.assertEqual("2026-06-22", tasks["hash1"]["daily_stat_last_date"])
        self.assertEqual(1000, tasks["hash1"]["daily_stat_last_uploaded"])
        self.assertEqual(2000, tasks["hash1"]["daily_stat_last_downloaded"])

    def test_daily_transfer_statistics_accumulates_same_day_deltas(self):
        plugin = self._new_plugin({})
        store = self._attach_memory_store(plugin)
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

        tasks["hash1"]["uploaded"] = 1500
        tasks["hash1"]["downloaded"] = 2600
        plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
            torrent_tasks=tasks,
            now=datetime(2026, 6, 22, 10, 5, 0),
        )

        daily = store["daily_statistic"]["2026-06-22"]
        self.assertEqual(500, daily["uploaded"])
        self.assertEqual(600, daily["downloaded"])
        self.assertEqual(1, daily["task_count"])
        self.assertEqual("2026-06-22", tasks["hash1"]["daily_stat_counted_date"])

        tasks["hash1"]["uploaded"] = 1700
        tasks["hash1"]["downloaded"] = 2900
        plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
            torrent_tasks=tasks,
            now=datetime(2026, 6, 22, 10, 10, 0),
        )

        daily = store["daily_statistic"]["2026-06-22"]
        self.assertEqual(700, daily["uploaded"])
        self.assertEqual(900, daily["downloaded"])
        self.assertEqual(1, daily["task_count"])

    def test_daily_transfer_statistics_aggregates_multiple_tasks(self):
        plugin = self._new_plugin({})
        store = self._attach_memory_store(plugin)
        tasks = {
            "hash1": {"uploaded": 1000, "downloaded": 2000},
            "hash2": {"uploaded": 3000, "downloaded": 4000},
        }
        plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
            torrent_tasks=tasks,
            now=datetime(2026, 6, 22, 10, 0, 0),
        )

        tasks["hash1"].update({"uploaded": 1300, "downloaded": 2400})
        tasks["hash2"].update({"uploaded": 3800, "downloaded": 4500})
        plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
            torrent_tasks=tasks,
            now=datetime(2026, 6, 22, 10, 5, 0),
        )

        daily = store["daily_statistic"]["2026-06-22"]
        self.assertEqual(1100, daily["uploaded"])
        self.assertEqual(900, daily["downloaded"])
        self.assertEqual(2, daily["task_count"])

    def test_daily_transfer_statistics_refreshes_baseline_on_counter_reset(self):
        plugin = self._new_plugin({})
        store = self._attach_memory_store(plugin, {
            "daily_statistic": {
                "2026-06-22": {
                    "date": "2026-06-22",
                    "uploaded": 500,
                    "downloaded": 600,
                    "task_count": 1,
                    "updated_at": 1,
                }
            }
        })
        tasks = {
            "hash1": {
                "uploaded": 900,
                "downloaded": 1800,
                "daily_stat_last_date": "2026-06-22",
                "daily_stat_last_uploaded": 1000,
                "daily_stat_last_downloaded": 2000,
                "daily_stat_counted_date": "2026-06-22",
            }
        }

        plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
            torrent_tasks=tasks,
            now=datetime(2026, 6, 22, 10, 5, 0),
        )

        daily = store["daily_statistic"]["2026-06-22"]
        self.assertEqual(500, daily["uploaded"])
        self.assertEqual(600, daily["downloaded"])
        self.assertEqual(900, tasks["hash1"]["daily_stat_last_uploaded"])
        self.assertEqual(1800, tasks["hash1"]["daily_stat_last_downloaded"])

    def test_daily_transfer_statistics_creates_new_record_after_date_change(self):
        plugin = self._new_plugin({})
        store = self._attach_memory_store(plugin)
        tasks = {
            "hash1": {
                "uploaded": 1000,
                "downloaded": 2000,
            }
        }
        plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
            torrent_tasks=tasks,
            now=datetime(2026, 6, 22, 23, 59, 0),
        )

        tasks["hash1"]["uploaded"] = 1300
        tasks["hash1"]["downloaded"] = 2400
        plugin._BrushFlowLowFreq__update_daily_transfer_statistics(
            torrent_tasks=tasks,
            now=datetime(2026, 6, 23, 0, 1, 0),
        )

        self.assertNotIn("2026-06-22", store["daily_statistic"])
        daily = store["daily_statistic"]["2026-06-23"]
        self.assertEqual(300, daily["uploaded"])
        self.assertEqual(400, daily["downloaded"])
        self.assertEqual(1, daily["task_count"])
        self.assertEqual("2026-06-23", tasks["hash1"]["daily_stat_last_date"])

    def test_clear_tasks_clears_daily_statistic(self):
        plugin = self._new_plugin({})
        store = self._attach_memory_store(plugin, {
            "daily_statistic": {
                "2026-06-22": {
                    "date": "2026-06-22",
                    "uploaded": 100,
                    "downloaded": 200,
                    "task_count": 1,
                    "updated_at": 1,
                }
            }
        })

        plugin._BrushFlowLowFreq__clear_tasks()

        self.assertEqual({}, store["daily_statistic"])

    def test_get_page_includes_daily_transfer_history(self):
        plugin = self._new_plugin({})
        self._attach_memory_store(plugin, {
            "torrents": {
                "hash1": {
                    "site_name": "站点1",
                    "title": "torrent",
                    "size": 100,
                    "uploaded": 1000,
                    "downloaded": 2000,
                    "ratio": 0.5,
                    "hit_and_run": False,
                    "seeding_time": 3600,
                    "deleted": False,
                    "time": 1,
                }
            },
            "daily_statistic": {
                "2026-06-22": {
                    "date": "2026-06-22",
                    "uploaded": 123,
                    "downloaded": 456,
                    "task_count": 1,
                    "updated_at": 1782067200,
                }
            }
        })

        page_text = json.dumps(plugin.get_page(), ensure_ascii=False)

        self.assertIn("每日流量统计", page_text)
        self.assertIn("今日上传量", page_text)
        self.assertIn("今日下载量", page_text)
        self.assertIn("2026-06-22", page_text)
        self.assertIn("123", page_text)
        self.assertIn("456", page_text)

    def test_get_page_shows_daily_transfer_empty_state(self):
        plugin = self._new_plugin({})
        self._attach_memory_store(plugin, {
            "torrents": {
                "hash1": {
                    "site_name": "站点1",
                    "title": "torrent",
                    "size": 100,
                    "uploaded": 1000,
                    "downloaded": 2000,
                    "ratio": 0.5,
                    "hit_and_run": False,
                    "seeding_time": 3600,
                    "deleted": False,
                    "time": 1,
                }
            },
            "daily_statistic": {}
        })

        page_text = json.dumps(plugin.get_page(), ensure_ascii=False)

        self.assertIn("每日流量统计", page_text)
        self.assertIn("暂无每日流量统计", page_text)


if __name__ == "__main__":
    unittest.main()
