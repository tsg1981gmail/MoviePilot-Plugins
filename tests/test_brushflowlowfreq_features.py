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

    def test_filter_seeding_torrents_on_keeps_all_delete_rules(self):
        plugin = self._new_plugin({
            "filter_seeding_torrents": True,
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

    def test_filter_seeding_torrents_off_only_seed_time_for_seeding_torrents(self):
        plugin = self._new_plugin({
            "filter_seeding_torrents": False,
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

        self.assertFalse(should_delete, reason)
        self.assertIn("已做种", reason)

    def test_filter_seeding_torrents_off_skips_no_free_delete_for_seeding_torrents(self):
        plugin = self._new_plugin({
            "filter_seeding_torrents": False,
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
        self.assertIn("已做种", reason)

    def test_filter_seeding_torrents_off_allows_seed_time_for_seeding_torrents(self):
        plugin = self._new_plugin({
            "filter_seeding_torrents": False,
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

    def test_filter_seeding_torrents_off_keeps_download_timeout_for_incomplete_torrents(self):
        plugin = self._new_plugin({
            "filter_seeding_torrents": False,
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
        self.assertEqual(15, brush_config.yield_guard_promising_pubtime_minutes)
        self.assertTrue(brush_config.yield_guard_rehearsal)
        self.assertFalse(brush_config.yield_guard_detail_log)

    def test_yield_guard_site_config_overrides_global_values(self):
        brush_config = self.module.BrushConfig({
            "yield_guard_enabled": True,
            "yield_guard_fast_fail_minutes": 12,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_ratio_protect_upload_kbs": 0,
            "yield_guard_detail_log": False,
            "enable_site_config": True,
            "site_config": '[{"sitename": "站点1", "yield_guard_fast_fail_minutes": 3, '
                           '"yield_guard_enabled": false, "yield_guard_low_ratio_percent": 5, '
                           '"yield_guard_ratio_min_download_kbs": 800, '
                           '"yield_guard_ratio_protect_upload_kbs": 200, "yield_guard_detail_log": true}]',
        })

        site_config = brush_config.get_site_config("站点1")
        self.assertFalse(site_config.yield_guard_enabled)
        self.assertEqual(3, site_config.yield_guard_fast_fail_minutes)
        self.assertEqual(5, site_config.yield_guard_low_ratio_percent)
        self.assertEqual(800, site_config.yield_guard_ratio_min_download_kbs)
        self.assertEqual(200, site_config.yield_guard_ratio_protect_upload_kbs)
        self.assertTrue(site_config.yield_guard_detail_log)
        self.assertEqual(12, brush_config.yield_guard_fast_fail_minutes)
        self.assertEqual(8, brush_config.yield_guard_low_ratio_percent)
        self.assertEqual(500, brush_config.yield_guard_ratio_min_download_kbs)
        self.assertEqual(0, brush_config.yield_guard_ratio_protect_upload_kbs)

    def test_update_config_persists_yield_guard_values(self):
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
            "yield_guard_promising_pubtime_minutes": 6,
            "yield_guard_detail_log": True,
        })
        saved_config = {}
        plugin.update_config = lambda config: saved_config.update(config)

        plugin._BrushFlowLowFreq__update_config()

        expected_values = {
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
            "yield_guard_promising_pubtime_minutes": 6,
            "yield_guard_detail_log": True,
        }
        for key, expected_value in expected_values.items():
            with self.subTest(key=key):
                self.assertIn(key, saved_config)
                self.assertEqual(expected_value, saved_config.get(key))

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
        new_errors = self.module.logger.error_messages[start_error_count:]
        self.assertTrue(any("收益保护高下载阈值" in msg for msg in new_errors))
        self.assertTrue(any("收益保护低收益比阈值" in msg for msg in new_errors))
        self.assertTrue(any("收益比判断最小下载速度" in msg for msg in new_errors))
        self.assertTrue(any("收益比保护上传阈值" in msg for msg in new_errors))
        self.assertTrue(any("低收益首次动作" in msg for msg in new_errors))

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
        self.assertIn("低收益", reason)

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
        self.assertIn("保护", reason)

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
        self.assertIn("分享率", reason)
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
        self.assertIn("暂停", reason)

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

    def test_check_applies_yield_guard_action_before_delete_rules(self):
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

        self.assertEqual([(["abcdef"], 512 * 1024)], plugin.downloader.qbc.download_limits)
        self.assertEqual("limited", torrent_tasks["abcdef"].get("yield_guard_stage"))

    def test_check_logs_yield_guard_summary_even_without_action(self):
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
        self.assertTrue(any("上传收益保护：本轮检查已评估 1 个任务" in msg for msg in new_logs))
        self.assertTrue(any("采样未就绪" in msg for msg in new_logs))

    def test_check_logs_yield_guard_detail_when_enabled(self):
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
        self.assertTrue(any("上传收益保护详细日志" in msg for msg in new_logs), new_logs)
        self.assertTrue(any("检查间上传 1024.0 KB/s" in msg for msg in new_logs), new_logs)
        self.assertTrue(any("判定=高收益保护" in msg for msg in new_logs), new_logs)
        self.assertTrue(any("高收益保护 1 个" in msg for msg in new_logs), new_logs)

    def test_check_logs_yield_guard_detail_miss_reason_when_upload_is_low_but_download_not_high(self):
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
        self.assertTrue(
            any("判定原因=检查间下载" in msg and "低于高下载阈值" in msg for msg in new_logs),
            new_logs
        )
        self.assertTrue(any("高下载=否" in msg for msg in new_logs), new_logs)

    def test_check_logs_yield_guard_detail_for_low_ratio_hit(self):
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
        self.assertTrue(any("判定=低收益观察/动作" in msg for msg in new_logs), new_logs)
        self.assertTrue(any("判定原因=收益比 4.0% 低于低收益比阈值 8%" in msg for msg in new_logs), new_logs)
        self.assertTrue(any("收益比 4.0%" in msg and "阈值 8%" in msg for msg in new_logs), new_logs)
        self.assertTrue(any("低收益比=是" in msg for msg in new_logs), new_logs)

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
        self.assertFalse(torrent_tasks["abcdef"].get("yield_guard_good_protected"))
        self.assertEqual(0, torrent_tasks["abcdef"].get("yield_guard_bad_streak"))

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

    def test_check_deletes_yield_guard_probe_failure_even_when_dynamic_threshold_not_reached(self):
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

        self.assertEqual(["bad"], downloader.deleted)
        self.assertTrue(torrent_tasks["bad"].get("deleted"))

    def test_dynamic_fallback_skips_yield_guard_good_protected_torrents(self):
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

    def test_yield_guard_good_pool_soft_stop_blocks_new_brush_without_probe_slot(self):
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
            include_network_conditions=False
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
            include_network_conditions=False
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
                include_network_conditions=False
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

    def test_get_form_exposes_yield_guard_controls(self):
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
            "yield_guard_enabled",
            "yield_guard_rehearsal",
            "yield_guard_detail_log",
            "yield_guard_high_download_kbs",
            "yield_guard_low_upload_kbs",
            "yield_guard_low_ratio_percent",
            "yield_guard_ratio_min_download_kbs",
            "yield_guard_ratio_protect_upload_kbs",
            "yield_guard_bad_checks",
            "yield_guard_fast_fail_minutes",
            "yield_guard_first_action",
            "yield_guard_second_action",
            "yield_guard_final_action",
            "yield_guard_download_limit_kbs",
            "yield_guard_good_upload_kbs",
            "yield_guard_stop_brush_when_good_pool",
        }
        self.assertTrue(expected_models.issubset(models), expected_models - models)

    def test_get_form_places_ratio_upload_protection_next_to_ratio_controls(self):
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
            models.index("yield_guard_low_ratio_percent"),
            models.index("yield_guard_ratio_min_download_kbs")
        )
        self.assertEqual(
            models.index("yield_guard_ratio_min_download_kbs") + 1,
            models.index("yield_guard_ratio_protect_upload_kbs")
        )

    def test_empty_new_numeric_options_default_to_zero(self):
        brush_config = self.module.BrushConfig({
            "skip_rules_downloading_threshold": "",
            "seed_ratio_speed_protect": "",
        })

        self.assertEqual(0, brush_config.skip_rules_downloading_threshold)
        self.assertEqual(0, brush_config.seed_ratio_speed_protect)

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


if __name__ == "__main__":
    unittest.main()
