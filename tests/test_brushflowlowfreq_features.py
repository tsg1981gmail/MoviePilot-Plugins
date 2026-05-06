import importlib.util
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
        torrent_task = {
            "site": 1,
            "page_url": "details.php?id=1",
            "site_name": "站点1",
            "title": "free torrent",
            "description": "free",
            "downloadvolumefactor": 0,
            "freedate": "",
            "freedate_diff": "",
        }

        should_delete, reason = plugin._BrushFlowLowFreq__evaluate_no_free_condition_for_delete(
            site_name="站点1",
            torrent_task=torrent_task,
        )

        self.assertTrue(should_delete, reason)
        self.assertIn("不足 5", reason)


if __name__ == "__main__":
    unittest.main()
