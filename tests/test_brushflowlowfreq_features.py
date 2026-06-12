import importlib.util
import hashlib
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
        def debug(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

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
