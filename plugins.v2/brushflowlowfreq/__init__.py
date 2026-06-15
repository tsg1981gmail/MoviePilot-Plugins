import base64
import hashlib
import html
import json
import random
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional, Union, Set
from urllib.parse import urlparse, parse_qs, unquote, parse_qsl, urlencode, urlunparse

import pytz
from app.helper.sites import SitesHelper
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.chain.torrents import TorrentsChain
from app.core.config import settings
from app.core.context import MediaInfo
from app.core.metainfo import MetaInfo
from app.db.site_oper import SiteOper
from app.db.subscribe_oper import SubscribeOper
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import NotificationType, TorrentInfo, MediaType, ServiceInfo
from app.schemas.types import EventType
from app.utils.http import RequestUtils
from app.utils.string import StringUtils

lock = threading.Lock()


class BrushConfig:
    """
    刷流配置
    """

    def __init__(self, config: dict, process_site_config=True):
        self.enabled = config.get("enabled", False)
        self.notify = config.get("notify", True)
        self.onlyonce = config.get("onlyonce", False)
        self.brushsites = config.get("brushsites", [])
        self.downloader = config.get("downloader")
        self.disksize = self.__parse_number(config.get("disksize"))
        self.freeleech = config.get("freeleech", "free")
        self.hr = config.get("hr", "no")
        self.maxupspeed = self.__parse_number(config.get("maxupspeed"))
        self.maxdlspeed = self.__parse_number(config.get("maxdlspeed"))
        self.maxdlcount = self.__parse_number(config.get("maxdlcount"))
        self.include = config.get("include")
        self.exclude = config.get("exclude")
        self.size = config.get("size")
        self.seeder = config.get("seeder")
        self.pubtime = config.get("pubtime")
        self.free_remaining_time = self.__parse_number(config.get("free_remaining_time"))
        self.free_remaining_time_skip_range = config.get("free_remaining_time_skip_range")
        self.seed_time = self.__parse_number(config.get("seed_time"))
        self.hr_seed_time = self.__parse_number(config.get("hr_seed_time"))
        self.seed_ratio = self.__parse_number(config.get("seed_ratio"))
        self.seed_ratio_check_minutes = self.__parse_number(config.get("seed_ratio_check_minutes"))
        self.seed_ratio_min_30m = self.__parse_number(config.get("seed_ratio_min_30m"))
        self.seed_size = self.__parse_number(config.get("seed_size"))
        self.download_time = self.__parse_number(config.get("download_time"))
        self.seed_avgspeed = self.__parse_number(config.get("seed_avgspeed"))
        self.interval_upspeed = self.__parse_number(config.get("interval_upspeed"))
        self.interval_upspeed_check_count = self.__parse_number(config.get("interval_upspeed_check_count"))
        self.interval_upspeed_low_count = self.__parse_number(config.get("interval_upspeed_low_count"))
        self.interval_upspeed_start_minutes = self.__parse_number(config.get("interval_upspeed_start_minutes"))
        self.interval_upspeed_continuous = config.get("interval_upspeed_continuous", False)
        self.interval_upspeed_rehearsal = config.get("interval_upspeed_rehearsal", False)
        self.seed_inactivetime = self.__parse_number(config.get("seed_inactivetime"))
        self.delete_size_range = config.get("delete_size_range")
        self.up_speed = self.__parse_number(config.get("up_speed"))
        self.dl_speed = self.__parse_number(config.get("dl_speed"))
        self.auto_archive_days = self.__parse_number(config.get("auto_archive_days"))
        self.save_path = config.get("save_path")
        self.clear_task = config.get("clear_task", False)
        self.delete_except_tags = config.get("delete_except_tags")
        self.except_subscribe = config.get("except_subscribe", True)
        self.brush_sequential = config.get("brush_sequential", False)
        self.proxy_delete = config.get("proxy_delete", False)
        self.filter_seeding_torrents = config.get("filter_seeding_torrents", True)
        self.delete_when_no_free = config.get("delete_when_no_free", False)
        self.delete_free_remaining_minutes = self.__parse_number(config.get("delete_free_remaining_minutes", 5))
        self.active_time_range = config.get("active_time_range")
        self.cron = config.get("cron")
        self.qb_category = config.get("qb_category")
        self.site_hr_active = config.get("site_hr_active", False)
        self.site_skip_tips = config.get("site_skip_tips", False)
        self.include_second_page = config.get("include_second_page", False)
        self.skip_rules_downloading_threshold = self.__parse_number(config.get("skip_rules_downloading_threshold", 0)) or 0
        self.seed_ratio_speed_protect = self.__parse_number(config.get("seed_ratio_speed_protect", 0)) or 0
        self.yield_guard_enabled = config.get("yield_guard_enabled", False)
        self.yield_guard_high_download_kbs = self.__parse_number(config.get("yield_guard_high_download_kbs", 2048))
        self.yield_guard_low_upload_kbs = self.__parse_number(config.get("yield_guard_low_upload_kbs", 200))
        self.yield_guard_low_ratio_percent = self.__parse_number(config.get("yield_guard_low_ratio_percent", 8))
        self.yield_guard_ratio_min_download_kbs = self.__parse_number(
            config.get("yield_guard_ratio_min_download_kbs", 500)
        )
        self.yield_guard_ratio_protect_upload_kbs = self.__parse_number(
            config.get("yield_guard_ratio_protect_upload_kbs", 0)
        )
        self.yield_guard_bad_checks = self.__parse_number(config.get("yield_guard_bad_checks", 2))
        self.yield_guard_min_downloaded_gb = self.__parse_number(config.get("yield_guard_min_downloaded_gb", 2))
        self.yield_guard_min_progress_percent = self.__parse_number(config.get("yield_guard_min_progress_percent", 10))
        self.yield_guard_first_action = config.get("yield_guard_first_action", "limit")
        self.yield_guard_second_action = config.get("yield_guard_second_action", "pause")
        self.yield_guard_final_action = config.get("yield_guard_final_action", "delete")
        self.yield_guard_download_limit_kbs = self.__parse_number(config.get("yield_guard_download_limit_kbs", 512))
        self.yield_guard_fast_fail_minutes = self.__parse_number(config.get("yield_guard_fast_fail_minutes", 10))
        self.yield_guard_good_upload_kbs = self.__parse_number(config.get("yield_guard_good_upload_kbs", 500))
        self.yield_guard_good_avg_upload_kbs = self.__parse_number(config.get("yield_guard_good_avg_upload_kbs", 500))
        self.yield_guard_protect_delete_rules = config.get("yield_guard_protect_delete_rules", True)
        self.yield_guard_stop_brush_when_good_pool = config.get("yield_guard_stop_brush_when_good_pool", True)
        self.yield_guard_good_pool_min_count = self.__parse_number(config.get("yield_guard_good_pool_min_count", 2))
        self.yield_guard_probe_slots = self.__parse_number(config.get("yield_guard_probe_slots", 1))
        self.yield_guard_probe_interval_minutes = self.__parse_number(config.get("yield_guard_probe_interval_minutes", 10))
        self.yield_guard_promising_pubtime_minutes = self.__parse_number(
            config.get("yield_guard_promising_pubtime_minutes", 15)
        )
        self.yield_guard_rehearsal = config.get("yield_guard_rehearsal", True)
        self.yield_guard_detail_log = config.get("yield_guard_detail_log", False)

        self.brush_tag = "刷流"
        # 站点独立配置
        self.enable_site_config = config.get("enable_site_config", False)
        self.site_config = config.get("site_config", "[]")
        self.group_site_configs = {}

        # 如果开启了独立站点配置，那么则初始化，否则判断配置是否为空，如果为空，则恢复默认配置
        if process_site_config:
            if self.enable_site_config:
                self.__initialize_site_config()
            elif not self.site_config:
                self.site_config = self.get_demo_site_config()

    def __initialize_site_config(self):
        if not self.site_config:
            logger.error(f"没有设置站点配置，已关闭站点独立配置并恢复默认配置示例，请检查配置项")
            self.site_config = self.get_demo_site_config()
            self.group_site_configs = {}
            self.enable_site_config = False
            return

        # 定义允许覆盖的字段列表
        allowed_fields = {
            "freeleech",
            "hr",
            "include",
            "exclude",
            "size",
            "seeder",
            "pubtime",
            "free_remaining_time",
            "free_remaining_time_skip_range",
            "seed_time",
            "hr_seed_time",
            "seed_ratio",
            "seed_ratio_check_minutes",
            "seed_ratio_min_30m",
            "seed_size",
            "download_time",
            "seed_avgspeed",
            "interval_upspeed",
            "interval_upspeed_check_count",
            "interval_upspeed_low_count",
            "interval_upspeed_start_minutes",
            "interval_upspeed_continuous",
            "interval_upspeed_rehearsal",
            "seed_inactivetime",
            "save_path",
            "proxy_delete",
            "filter_seeding_torrents",
            "delete_when_no_free",
            "delete_free_remaining_minutes",
            "qb_category",
            "site_hr_active",
            "site_skip_tips",
            "include_second_page",
            "skip_rules_downloading_threshold",
            "seed_ratio_speed_protect",
            "yield_guard_enabled",
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
            "yield_guard_promising_pubtime_minutes",
            "yield_guard_rehearsal",
            "yield_guard_detail_log"
            # 当新增支持字段时，仅在此处添加字段名
        }
        try:
            # site_config中去掉以//开始的行
            site_config = re.sub(r'//.*?\n', '', self.site_config).strip()
            site_configs = json.loads(site_config)
            self.group_site_configs = {}
            for config in site_configs:
                sitename = config.get("sitename")
                if not sitename:
                    continue

                # 只从站点特定配置中获取允许的字段
                site_specific_config = {key: config[key] for key in allowed_fields & set(config.keys())}

                full_config = {key: getattr(self, key) for key in vars(self) if
                               key not in ["group_site_configs", "site_config"]}
                full_config.update(site_specific_config)

                self.group_site_configs[sitename] = BrushConfig(config=full_config, process_site_config=False)
        except Exception as e:
            logger.error(f"解析站点配置失败，已停用插件并关闭站点独立配置，请检查配置项，错误详情: {e}")
            self.group_site_configs = {}
            self.enable_site_config = False
            self.enabled = False

    @staticmethod
    def get_demo_site_config() -> str:
        desc = (
            "// 以下为配置示例，请参考：https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/plugins.v2/brushflowlowfreq/README.md 进行配置\n"
            "// 如与全局保持一致的配置项，请勿在站点配置中配置\n"
            "// 注意无关内容需使用 // 注释\n")
        config = """[{
    "sitename": "站点1",
    "seed_time": 96,
    "hr_seed_time": 144
}, {
    "sitename": "站点2",
    "hr": "yes",
    "size": "10-500",
    "seeder": "5-10",
    "pubtime": "5-120",
    "seed_time": 96,
    "save_path": "/downloads/site2",
    "hr_seed_time": 144
}, {
    "sitename": "站点3",
    "freeleech": "free",
    "hr": "yes",
    "include": "",
    "exclude": "",
    "size": "10-500",
    "seeder": "1",
    "pubtime": "5-120",
    "free_remaining_time": 120,
    "free_remaining_time_skip_range": "",
    "seed_time": 120,
    "hr_seed_time": 144,
    "seed_ratio": "",
    "seed_ratio_check_minutes": 30,
    "seed_ratio_min_30m": "",
    "seed_size": "",
    "download_time": "",
    "seed_avgspeed": "",
    "interval_upspeed": "",
    "interval_upspeed_check_count": 3,
    "interval_upspeed_low_count": 2,
    "interval_upspeed_start_minutes": 30,
    "interval_upspeed_continuous": false,
    "interval_upspeed_rehearsal": false,
    "seed_inactivetime": "",
    "save_path": "/downloads/site1",
    "proxy_delete": false,
    "filter_seeding_torrents": true,
    "delete_when_no_free": false,
    "delete_free_remaining_minutes": 5,
    "qb_category": "刷流",
    "site_hr_active": true,
    "site_skip_tips": true,
    "include_second_page": false,
    "skip_rules_downloading_threshold": 0,
    "seed_ratio_speed_protect": 0,
    "yield_guard_enabled": false,
    "yield_guard_high_download_kbs": 2048,
    "yield_guard_low_upload_kbs": 200,
    "yield_guard_low_ratio_percent": 8,
    "yield_guard_ratio_min_download_kbs": 500,
    "yield_guard_ratio_protect_upload_kbs": 0,
    "yield_guard_bad_checks": 2,
    "yield_guard_min_downloaded_gb": 2,
    "yield_guard_min_progress_percent": 10,
    "yield_guard_first_action": "limit",
    "yield_guard_second_action": "pause",
    "yield_guard_final_action": "delete",
    "yield_guard_download_limit_kbs": 512,
    "yield_guard_fast_fail_minutes": 10,
    "yield_guard_good_upload_kbs": 500,
    "yield_guard_good_avg_upload_kbs": 500,
    "yield_guard_protect_delete_rules": true,
    "yield_guard_stop_brush_when_good_pool": true,
    "yield_guard_good_pool_min_count": 2,
    "yield_guard_probe_slots": 1,
    "yield_guard_probe_interval_minutes": 10,
    "yield_guard_promising_pubtime_minutes": 15,
    "yield_guard_rehearsal": true,
    "yield_guard_detail_log": false
}]"""
        return desc + config

    def get_site_config(self, sitename):
        """
        根据站点名称获取特定的BrushConfig实例。如果没有找到站点特定的配置，则返回全局的BrushConfig实例。
        """
        if not self.enable_site_config:
            return self
        return self if not sitename else self.group_site_configs.get(sitename, self)

    @staticmethod
    def __parse_number(value):
        if value is None or value == "":  # 更精确地检查None或空字符串
            return value
        elif isinstance(value, int):  # 直接判断是否为int
            return value
        elif isinstance(value, float):  # 直接判断是否为float
            return value
        else:
            try:
                number = float(value)
                # 检查number是否等于其整数形式
                if number == int(number):
                    return int(number)
                else:
                    return number
            except (ValueError, TypeError):
                return 0

    def __format_value(self, v):
        """
        Format the value to mimic JSON serialization. This is now an instance method.
        """
        if isinstance(v, str):
            return f'"{v}"'
        elif isinstance(v, (int, float, bool)):
            return str(v).lower() if isinstance(v, bool) else str(v)
        elif isinstance(v, list):
            return '[' + ', '.join(self.__format_value(i) for i in v) + ']'
        elif isinstance(v, dict):
            return '{' + ', '.join(f'"{k}": {self.__format_value(val)}' for k, val in v.items()) + '}'
        else:
            return str(v)

    def __str__(self):
        attrs = vars(self)
        # Note the use of self.format_value(v) here to call the instance method
        attrs_str = ', '.join(f'"{k}": {self.__format_value(v)}' for k, v in attrs.items())
        return f'{{ {attrs_str} }}'

    def __repr__(self):
        return self.__str__()


class BrushFlowLowFreq(_PluginBase):
    # region 全局定义

    # 插件名称
    plugin_name = "shualiu"
    # 插件描述
    plugin_desc = "自动托管刷流，将会提高对应站点的访问频率。（基于官方插件BrushFlow二次开发）"
    # 插件图标
    plugin_icon = "brush.jpg"
    # 插件版本
    plugin_version = "4.3.38"
    # 插件作者
    plugin_author = "jxxghp,InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "brushflowlowfreq_"
    # 加载顺序
    plugin_order = 22
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    sites_helper = None
    site_oper = None
    torrents_chain = None
    subscribe_oper = None
    downloader_helper = None
    # 刷流配置
    _brush_config = None
    # Brush任务是否启动
    _task_brush_enable = False
    # 订阅缓存信息
    _subscribe_infos = None
    # Brush定时
    _brush_interval = 10
    # Check定时
    _check_interval = 150
    # 退出事件
    _event = threading.Event()
    _scheduler = None
    # tabs
    _tabs = None

    # endregion

    def init_plugin(self, config: dict = None):
        self.sites_helper = SitesHelper()
        self.site_oper = SiteOper()
        self.torrents_chain = TorrentsChain()
        self.subscribe_oper = SubscribeOper()
        self.downloader_helper = DownloaderHelper()
        self._task_brush_enable = False

        if not config:
            logger.info("站点刷流任务出错，无法获取插件配置")
            return False

        self._tabs = config.get("_tabs", None)

        # 如果配置校验没有通过，那么这里修改配置文件后退出
        if not self.__validate_and_fix_config(config=config):
            self._brush_config = BrushConfig(config=config)
            self._brush_config.enabled = False
            self.__update_config()
            return

        self._brush_config = BrushConfig(config=config)

        brush_config = self._brush_config

        # 判断是否存在插件冲突，如果存在则停用
        if not self.__check_and_resolve_plugin_conflict():
            self._brush_config.enabled = False
            self.__update_config()
            return

        # 这里先过滤掉已删除的站点并保存，特别注意的是，这里保留了界面选择站点时的顺序，以便后续站点随机刷流或顺序刷流
        if brush_config.brushsites:
            site_id_to_public_status = {site.get("id"): site.get("public") for site in self.sites_helper.get_indexers()}
            brush_config.brushsites = [
                site_id for site_id in brush_config.brushsites
                if site_id in site_id_to_public_status and not site_id_to_public_status[site_id]
            ]

        self.__update_config()

        if brush_config.clear_task:
            self.__clear_tasks()
            brush_config.clear_task = False
            self.__update_config()

        # 同步官方插件
        self.__sync_official(config=config)

        if brush_config.enable_site_config:
            logger.debug(f"已开启站点独立配置，配置信息：{brush_config}")
        else:
            logger.debug(f"没有开启站点独立配置，配置信息：{brush_config}")

        # 停止现有任务
        self.stop_service()

        # 如果站点都没有配置，则不开启定时刷流服务
        if not brush_config.brushsites:
            logger.info(f"站点刷流定时服务停止，没有配置站点")

        # 如果开启&存在站点时，才需要启用后台任务
        self._task_brush_enable = brush_config.enabled and brush_config.brushsites

        # 如果下载器都没有配置，那么这里也不需要继续
        if not brush_config.downloader:
            brush_config.enabled = False
            self.__update_config()
            logger.info(f"站点刷流服务停止，没有配置下载器")
            return

        if not self.service_info:
            return

        # 检查是否启用了一次性任务
        if brush_config.onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)

            logger.info(f"站点刷流服务启动，立即运行一次")
            self._scheduler.add_job(self.brush, "date",
                                    run_date=datetime.now(
                                        tz=pytz.timezone(settings.TZ)
                                    ) + timedelta(seconds=3),
                                    name="shualiu服务")

            logger.info(f"站点刷流检查服务启动，立即运行一次")
            self._scheduler.add_job(self.check, "date",
                                    run_date=datetime.now(
                                        tz=pytz.timezone(settings.TZ)
                                    ) + timedelta(seconds=3),
                                    name="shualiu检查服务")

            # 关闭一次性开关
            brush_config.onlyonce = False
            self.__update_config()

            # 存在任务则启动任务
            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    @property
    def service_info(self) -> Optional[ServiceInfo]:
        """
        服务信息
        """
        brush_config = self.__get_brush_config()
        service = self.downloader_helper.get_service(name=brush_config.downloader)
        if not service:
            self.__log_and_notify_error("站点刷流任务出错，获取下载器实例失败，请检查配置")
            return None

        if service.instance.is_inactive():
            self.__log_and_notify_error("站点刷流任务出错，下载器未连接")
            return None

        return service

    @property
    def downloader(self) -> Optional[Union[Qbittorrent, Transmission]]:
        """
        下载器实例
        """
        return self.service_info.instance if self.service_info else None

    def get_state(self) -> bool:
        brush_config = self.__get_brush_config()
        return True if brush_config and brush_config.enabled else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        services = []

        brush_config = self.__get_brush_config()
        if not brush_config:
            return services

        # 判断是否存在插件冲突，如果存在则停用
        if not self.__check_and_resolve_plugin_conflict():
            return services

        if self._task_brush_enable:
            if brush_config.cron:
                values = brush_config.cron.split()
                values[0] = f"{datetime.now().minute % 10}/10"
                cron = " ".join(values)
                logger.info(f"站点刷流定时服务启动，执行周期 {cron}")
                cron_trigger = CronTrigger.from_crontab(cron)
                services.append({
                    "id": "BrushFlowLowFreq",
                    "name": "shualiu服务",
                    "trigger": cron_trigger,
                    "func": self.brush
                })
            else:
                logger.info(f"站点刷流定时服务启动，时间间隔 {self._brush_interval} 分钟")
                services.append({
                    "id": "BrushFlowLowFreq",
                    "name": "shualiu服务",
                    "trigger": "interval",
                    "func": self.brush,
                    "kwargs": {"minutes": self._brush_interval}
                })

        if brush_config.enabled:
            logger.info(f"站点刷流检查定时服务启动，时间间隔 {self._check_interval} 秒")
            services.append({
                "id": "BrushFlowLowFreqCheck",
                "name": "shualiu检查服务",
                "trigger": "interval",
                "func": self.check,
                "kwargs": {"seconds": self._check_interval}
            })

        if not services:
            logger.info("站点刷流服务未开启")

        return services

    def __get_total_elements(self) -> List[dict]:
        """
        组装汇总元素
        """
        # 统计数据
        statistic_info = self.__get_statistic_info()
        # 总上传量
        total_uploaded = StringUtils.str_filesize(statistic_info.get("uploaded") or 0)
        # 总下载量
        total_downloaded = StringUtils.str_filesize(statistic_info.get("downloaded") or 0)
        # 下载种子数
        total_count = statistic_info.get("count") or 0
        # 删除种子数
        total_deleted = statistic_info.get("deleted") or 0
        # 待归档种子数
        total_unarchived = statistic_info.get("unarchived") or 0
        # 活跃种子数
        total_active = statistic_info.get("active") or 0
        # 活跃上传量
        total_active_uploaded = StringUtils.str_filesize(statistic_info.get("active_uploaded") or 0)
        # 活跃下载量
        total_active_downloaded = StringUtils.str_filesize(statistic_info.get("active_downloaded") or 0)

        return [
            # 总上传量
            {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 3,
                    'sm': 6
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                        },
                        'content': [
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'd-flex align-center',
                                },
                                'content': [
                                    {
                                        'component': 'VAvatar',
                                        'props': {
                                            'rounded': True,
                                            'variant': 'text',
                                            'class': 'me-3'
                                        },
                                        'content': [
                                            {
                                                'component': 'VImg',
                                                'props': {
                                                    'src': '/plugin_icon/upload.png'
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'div',
                                        'content': [
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'text-caption'
                                                },
                                                'text': '总上传量 / 活跃'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'd-flex align-center flex-wrap'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-h6'
                                                        },
                                                        'text': f"{total_uploaded} / {total_active_uploaded}"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            },
            # 总下载量
            {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 3,
                    'sm': 6
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                        },
                        'content': [
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'd-flex align-center',
                                },
                                'content': [
                                    {
                                        'component': 'VAvatar',
                                        'props': {
                                            'rounded': True,
                                            'variant': 'text',
                                            'class': 'me-3'
                                        },
                                        'content': [
                                            {
                                                'component': 'VImg',
                                                'props': {
                                                    'src': '/plugin_icon/download.png'
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'div',
                                        'content': [
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'text-caption'
                                                },
                                                'text': '总下载量 / 活跃'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'd-flex align-center flex-wrap'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-h6'
                                                        },
                                                        'text': f"{total_downloaded} / {total_active_downloaded}"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            },
            # 下载种子数
            {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 3,
                    'sm': 6
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                        },
                        'content': [
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'd-flex align-center',
                                },
                                'content': [
                                    {
                                        'component': 'VAvatar',
                                        'props': {
                                            'rounded': True,
                                            'variant': 'text',
                                            'class': 'me-3'
                                        },
                                        'content': [
                                            {
                                                'component': 'VImg',
                                                'props': {
                                                    'src': '/plugin_icon/seed.png'
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'div',
                                        'content': [
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'text-caption'
                                                },
                                                'text': '下载种子数 / 活跃'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'd-flex align-center flex-wrap'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-h6'
                                                        },
                                                        'text': f"{total_count} / {total_active}"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            },
            # 删除种子数
            {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 3,
                    'sm': 6
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                        },
                        'content': [
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'd-flex align-center',
                                },
                                'content': [
                                    {
                                        'component': 'VAvatar',
                                        'props': {
                                            'rounded': True,
                                            'variant': 'text',
                                            'class': 'me-3'
                                        },
                                        'content': [
                                            {
                                                'component': 'VImg',
                                                'props': {
                                                    'src': '/plugin_icon/delete.png'
                                                }
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'div',
                                        'content': [
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'text-caption'
                                                },
                                                'text': '删除种子数 / 待归档'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'd-flex align-center flex-wrap'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-h6'
                                                        },
                                                        'text': f"{total_deleted} / {total_unarchived}"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
        ]

    def get_dashboard(self, key: str, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]]:
        """
        获取插件仪表盘页面，需要返回：1、仪表板col配置字典；2、全局配置（自动刷新等）；3、仪表板页面元素配置json（含数据）
        1、col配置参考：
        {
            "cols": 12, "md": 6
        }
        2、全局配置参考：
        {
            "refresh": 10 // 自动刷新时间，单位秒
        }
        3、页面配置使用Vuetify组件拼装，参考：https://vuetifyjs.com/
        """
        # 列配置
        cols = {
            "cols": 12
        }
        # 全局配置
        attrs = {}
        # 拼装页面元素
        elements = [
            {
                'component': 'VRow',
                'content': self.__get_total_elements()
            }
        ]
        return cols, attrs, elements

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """

        # 站点选项
        site_options = [{"title": site.get("name"), "value": site.get("id")}
                        for site in self.sites_helper.get_indexers()]
        # 下载器选项
        downloader_options = [{"title": config.name, "value": config.name}
                              for config in self.downloader_helper.get_configs().values()]
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'brushsites',
                                            'label': '刷流站点',
                                            'items': site_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 3
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'downloader',
                                            'label': '下载器',
                                            'items': downloader_options
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 3
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '如：0 0-1 * * FRI,SUN'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'active_time_range',
                                            'label': '开启时间段',
                                            'placeholder': '如：00:00-08:00'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 3
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'delete_size_range',
                                            'label': '动态删种阈值（GB）',
                                            'placeholder': '如：500 或 500-1000，达到后删除任务'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VTabs',
                        'props': {
                            'model': '_tabs',
                            'style': {
                                'margin-top': '8px',
                                'margin-bottom': '16px'
                            },
                            'stacked': True,
                            'fixed-tabs': True
                        },
                        'content': [
                            {
                                'component': 'VTab',
                                'props': {
                                    'value': 'base_tab'
                                },
                                'text': '基本配置'
                            }, {
                                'component': 'VTab',
                                'props': {
                                    'value': 'download_tab'
                                },
                                'text': '选种规则'
                            }, {
                                'component': 'VTab',
                                'props': {
                                    'value': 'delete_tab'
                                },
                                'text': '删除规则'
                            }, {
                                'component': 'VTab',
                                'props': {
                                    'value': 'other_tab'
                                },
                                'text': '更多配置'
                            }
                        ]
                    },
                    {
                        'component': 'VWindow',
                        'props': {
                            'model': '_tabs'
                        },
                        'content': [
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'base_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '0px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'maxdlcount',
                                                            'label': '同时下载任务数',
                                                            'placeholder': '达到后停止新增任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'disksize',
                                                            'label': '保种体积（GB）',
                                                            'placeholder': '如：500，达到后停止新增任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'qb_category',
                                                            'label': '种子分类',
                                                            'placeholder': '仅支持qBittorrent，需提前创建'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'free_remaining_time_skip_range',
                                                            'label': '免费时间过滤例外时段',
                                                            'placeholder': '如：00:00-08:00，留空不跳过'
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'maxupspeed',
                                                            'label': '总上传带宽（KB/s）',
                                                            'placeholder': '达到后停止新增任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'maxdlspeed',
                                                            'label': '总下载带宽（KB/s）',
                                                            'placeholder': '达到后停止新增任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'save_path',
                                                            'label': '保存目录',
                                                            'placeholder': '留空自动'
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'up_speed',
                                                            'label': '单任务上传限速（KB/s）',
                                                            'placeholder': '种子上传限速'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'dl_speed',
                                                            'label': '单任务下载限速（KB/s）',
                                                            'placeholder': '种子下载限速'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'auto_archive_days',
                                                            'label': '自动归档记录天数',
                                                            'placeholder': '超过此天数后自动归档',
                                                            'type': 'number',
                                                            "min": "0"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'download_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '0px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'hr',
                                                            'label': '排除H&R',
                                                            'items': [
                                                                {'title': '是', 'value': 'yes'},
                                                                {'title': '否', 'value': 'no'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'delete_free_remaining_minutes',
                                                            'label': '免费临期删种阈值（分钟）',
                                                            'placeholder': '默认5，开启失去免费即删种后生效'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'freeleech',
                                                            'label': '促销',
                                                            'items': [
                                                                {'title': '全部（包括普通）', 'value': ''},
                                                                {'title': '免费', 'value': 'free'},
                                                                {'title': '2X免费', 'value': '2xfree'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'pubtime',
                                                            'label': '发布时间（分钟）',
                                                            'placeholder': '如：5 或 5-10'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'free_remaining_time',
                                                            'label': '免费剩余时间（分钟）',
                                                            'placeholder': '如：120，留空则不限制'
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'size',
                                                            'label': '种子大小（GB）',
                                                            'placeholder': '如：5 或 5-10'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seeder',
                                                            'label': '做种人数',
                                                            'placeholder': '如：5 或 5-10'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'include',
                                                            'label': '包含规则',
                                                            'placeholder': '支持正式表达式'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'exclude',
                                                            'label': '排除规则',
                                                            'placeholder': '支持正式表达式'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'delete_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '0px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_time',
                                                            'label': '做种时间（小时）',
                                                            'placeholder': '达到后删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'hr_seed_time',
                                                            'label': 'H&R做种时间（小时）',
                                                            'placeholder': '达到后删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_ratio',
                                                            'label': '分享率',
                                                            'placeholder': '达到后删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_ratio_check_minutes',
                                                            'label': '有下载数据后分钟数',
                                                            'placeholder': '如：30，首次有下载数据后开始判断低分享率'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_ratio_min_30m',
                                                            'label': '任务添加后最低分享率',
                                                            'placeholder': '达到上述分钟数后，低于时删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_ratio_speed_protect',
                                                            'label': '分享率保护速度阈值（KB/s）',
                                                            'placeholder': '如：100，平均上传速度≥100KB/s时即使分享率低也不删，0=关闭'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'filter_seeding_torrents',
                                                            'label': '是否筛选已做种？',
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_size',
                                                            'label': '上传量（GB）',
                                                            'placeholder': '达到后删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_avgspeed',
                                                            'label': '平均上传速度（KB/s）',
                                                            'placeholder': '低于时删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'download_time',
                                                            'label': '下载超时时间（小时）',
                                                            'placeholder': '达到后删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'seed_inactivetime',
                                                            'label': '未活动时间（分钟）',
                                                            'placeholder': '超过时删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'interval_upspeed',
                                                            'label': '检查间上传速度阈值（KB/s）',
                                                            'placeholder': '低于时计入低速命中'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'interval_upspeed_check_count',
                                                            'label': '检查间低速观察次数',
                                                            'placeholder': '如：3，统计最近3次检查'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'interval_upspeed_low_count',
                                                            'label': '检查间低速命中次数',
                                                            'placeholder': '如：2，达到后删除任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'interval_upspeed_start_minutes',
                                                            'label': '有上传数据后开始低速统计分钟数',
                                                            'placeholder': '如：30，首次有上传数据后开始记录'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'delete_except_tags',
                                                            'label': '删除排除标签',
                                                            'placeholder': '如：MOVIEPILOT,H&R'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'interval_upspeed_continuous',
                                                            'label': '检查间低速按连续命中判定',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'interval_upspeed_rehearsal',
                                                            'label': '检查间低速演练模式（只提醒不删）',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'skip_rules_downloading_threshold',
                                                            'label': '下载保护阈值',
                                                            'placeholder': '如：3，下载中种子数≤3时跳过分享率和上传速度检查，0=关闭'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                    , {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'yield_guard_enabled',
                                                            'label': '上传收益保护'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'yield_guard_rehearsal',
                                                            'label': '上传收益保护演练模式'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'yield_guard_detail_log',
                                                            'label': '上传收益保护详细日志'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'yield_guard_protect_delete_rules',
                                                            'label': '保护高上传任务'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_high_download_kbs',
                                                            'label': '收益保护高下载阈值（KB/s）',
                                                            'placeholder': '如：2048，检查间下载达到后参与判断'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_low_upload_kbs',
                                                            'label': '收益保护低上传阈值（KB/s）',
                                                            'placeholder': '如：200，检查间上传低于时计入低收益'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_low_ratio_percent',
                                                            'label': '收益保护低收益比阈值（%）',
                                                            'placeholder': '如：8，检查间上传/下载低于该比例'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_ratio_min_download_kbs',
                                                            'label': '收益比判断最小下载速度（KB/s）',
                                                            'placeholder': '如：500，下载达到后才判断收益比'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_ratio_protect_upload_kbs',
                                                            'label': '收益比保护上传阈值（KB/s）',
                                                            'placeholder': '如：200，收益比低但上传达到该值时继续观察'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_bad_checks',
                                                            'label': '低收益连续命中次数',
                                                            'placeholder': '如：2，连续命中后执行动作'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_min_downloaded_gb',
                                                            'label': '收益保护最小下载量（GB）',
                                                            'placeholder': '如：2，达到后才处理'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_min_progress_percent',
                                                            'label': '收益保护最小进度（%）',
                                                            'placeholder': '如：10，达到后才处理'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_fast_fail_minutes',
                                                            'label': '快速淘汰窗口（分钟）',
                                                            'placeholder': '如：10，窗口内不直接删除'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_promising_pubtime_minutes',
                                                            'label': '新发布短窗保护（分钟）',
                                                            'placeholder': '如：15，发布时间内不直接删除'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_download_limit_kbs',
                                                            'label': '低收益下载限速（KB/s）',
                                                            'placeholder': '如：512，低收益限速动作使用'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_good_upload_kbs',
                                                            'label': '高上传保护阈值（KB/s）',
                                                            'placeholder': '如：500，检查间上传达到后保护'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_good_avg_upload_kbs',
                                                            'label': '高平均上传保护阈值（KB/s）',
                                                            'placeholder': '如：500，平均上传达到后保护'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'yield_guard_first_action',
                                                            'label': '低收益首次动作',
                                                            'items': [
                                                                {'title': '不处理', 'value': 'none'},
                                                                {'title': '下载限速', 'value': 'limit'},
                                                                {'title': '暂停', 'value': 'pause'},
                                                                {'title': '删除', 'value': 'delete'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'yield_guard_second_action',
                                                            'label': '低收益二次动作',
                                                            'items': [
                                                                {'title': '不处理', 'value': 'none'},
                                                                {'title': '暂停', 'value': 'pause'},
                                                                {'title': '删除', 'value': 'delete'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'yield_guard_final_action',
                                                            'label': '短窗后最终动作',
                                                            'items': [
                                                                {'title': '不处理', 'value': 'none'},
                                                                {'title': '删除', 'value': 'delete'},
                                                            ]
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'yield_guard_stop_brush_when_good_pool',
                                                            'label': '高收益池满时停止新增'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_good_pool_min_count',
                                                            'label': '高收益池最小数量',
                                                            'placeholder': '如：2，达到后减少新增'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_probe_slots',
                                                            'label': '收益保护探测名额',
                                                            'placeholder': '如：1，保留新增探测任务数'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'yield_guard_probe_interval_minutes',
                                                            'label': '收益保护探测间隔（分钟）',
                                                            'placeholder': '如：10，两次探测新增的最小间隔'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'other_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'style': {
                                                'margin-top': '-16px'
                                            }
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'brush_sequential',
                                                            'label': '站点顺序刷流',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'except_subscribe',
                                                            'label': '排除订阅（实验性功能）',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'proxy_delete',
                                                            'label': '动态删除种子（实验性功能）',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'include_second_page',
                                                            'label': '选种包含第二页',
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'delete_when_no_free',
                                                            'label': '失去免费即删种',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'clear_task',
                                                            'label': '清除统计数据',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'enable_site_config',
                                                            'label': '站点独立配置',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {
                                                    "cols": 12,
                                                    "md": 4
                                                },
                                                "content": [
                                                    {
                                                        "component": "VSwitch",
                                                        "props": {
                                                            "model": "dialog_closed",
                                                            "label": "打开站点配置窗口"
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        "content": [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'sync_official',
                                                            'label': '双向同步官方数据',
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {
                            'style': {
                                'margin-top': '12px'
                            },
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'success',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                                'component': 'span',
                                                'text': '注意：详细配置说明以及刷流规则请参考：'
                                            },
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': 'https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/plugins.v2/brushflowlowfreq/README.md',
                                                    'target': '_blank'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'u',
                                                        'text': 'README'
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'text': '注意：启用官方刷流插件时，本插件无法正常使用，可尝试停用官方插件后通过双向同步官方数据再开启使用，请不要同时启用两个插件，否则可能导致种子异常甚至数据丢失'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'error',
                                            'variant': 'tonal',
                                            'text': '注意：排除H&R并不保证能完全适配所有站点（部分站点在列表页不显示H&R标志，但实际上是有H&R的），请注意核对使用'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VDialog",
                        "props": {
                            "model": "dialog_closed",
                            "max-width": "65rem",
                            "overlay-class": "v-dialog--scrollable v-overlay--scroll-blocked",
                            "content-class": "v-card v-card--density-default v-card--variant-elevated rounded-t"
                        },
                        "content": [
                            {
                                "component": "VCard",
                                "props": {
                                    "title": "设置站点配置"
                                },
                                "content": [
                                    {
                                        "component": "VDialogCloseBtn",
                                        "props": {
                                            "model": "dialog_closed"
                                        }
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {},
                                        "content": [
                                            {
                                                'component': 'VRow',
                                                'content': [
                                                    {
                                                        'component': 'VCol',
                                                        'props': {
                                                            'cols': 12,
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VAceEditor',
                                                                'props': {
                                                                    'modelvalue': 'site_config',
                                                                    'lang': 'json',
                                                                    'theme': 'monokai',
                                                                    'style': 'height: 30rem',
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VRow',
                                                'content': [
                                                    {
                                                        'component': 'VCol',
                                                        'props': {
                                                            'cols': 12,
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VAlert',
                                                                'props': {
                                                                    'type': 'info',
                                                                    'variant': 'tonal'
                                                                },
                                                                'content': [
                                                                    {
                                                                        'component': 'span',
                                                                        'text': '注意：只有启用站点独立配置时，该配置项才会生效，详细配置参考：'
                                                                    },
                                                                    {
                                                                        'component': 'a',
                                                                        'props': {
                                                                            'href': 'https://github.com/InfinityPacer/MoviePilot-Plugins/blob/main/plugins.v2/brushflowlowfreq/README.md',
                                                                            'target': '_blank'
                                                                        },
                                                                        'content': [
                                                                            {
                                                                                'component': 'u',
                                                                                'text': 'README'
                                                                            }
                                                                        ]
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "clear_task": False,
            "delete_except_tags": f"{settings.TORRENT_TAG},H&R" if settings.TORRENT_TAG else "H&R",
            "except_subscribe": True,
            "brush_sequential": False,
            "proxy_delete": False,
            "filter_seeding_torrents": True,
            "delete_when_no_free": False,
            "delete_free_remaining_minutes": 5,
            "include_second_page": False,
            "free_remaining_time_skip_range": "",
            "interval_upspeed": "",
            "interval_upspeed_check_count": 3,
            "interval_upspeed_low_count": 2,
            "interval_upspeed_start_minutes": 30,
            "interval_upspeed_continuous": False,
            "interval_upspeed_rehearsal": False,
            "skip_rules_downloading_threshold": 0,
            "seed_ratio_speed_protect": 0,
            "yield_guard_enabled": False,
            "yield_guard_high_download_kbs": 2048,
            "yield_guard_low_upload_kbs": 200,
            "yield_guard_low_ratio_percent": 8,
            "yield_guard_ratio_min_download_kbs": 500,
            "yield_guard_bad_checks": 2,
            "yield_guard_min_downloaded_gb": 2,
            "yield_guard_min_progress_percent": 10,
            "yield_guard_first_action": "limit",
            "yield_guard_second_action": "pause",
            "yield_guard_final_action": "delete",
            "yield_guard_download_limit_kbs": 512,
            "yield_guard_fast_fail_minutes": 10,
            "yield_guard_good_upload_kbs": 500,
            "yield_guard_good_avg_upload_kbs": 500,
            "yield_guard_protect_delete_rules": True,
            "yield_guard_stop_brush_when_good_pool": True,
            "yield_guard_good_pool_min_count": 2,
            "yield_guard_probe_slots": 1,
            "yield_guard_probe_interval_minutes": 10,
            "yield_guard_promising_pubtime_minutes": 15,
            "yield_guard_rehearsal": True,
            "yield_guard_detail_log": False,
            "freeleech": "free",
            "hr": "yes",
            "enable_site_config": False,
            "site_config": BrushConfig.get_demo_site_config()
        }

    def get_page(self) -> List[dict]:
        # 种子明细
        torrents = self.get_data("torrents") or {}

        if not torrents:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        else:
            data_list = torrents.values()
            # 按time倒序排序
            data_list = sorted(data_list, key=lambda x: x.get("time") or 0, reverse=True)

        # 种子数据明细
        torrent_trs = [
            {
                'component': 'tr',
                'props': {
                    'class': 'text-sm'
                },
                'content': [
                    {
                        'component': 'td',
                        'props': {
                            'class': 'whitespace-nowrap break-keep text-high-emphasis'
                        },
                        'text': data.get("site_name")
                    },
                    {
                        'component': 'td',
                        'html': f'<span style="font-size: .85rem;">{data.get("title")}</span>' +
                                (f'<br><span style="font-size: 0.75rem;">{data.get("description")}</span>' if data.get(
                                    "description") else "")

                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("size"))
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("uploaded") or 0)
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("downloaded") or 0)
                    },
                    {
                        'component': 'td',
                        'text': round(data.get('ratio') or 0, 2)
                    },
                    {
                        'component': 'td',
                        'text': "是" if data.get("hit_and_run") else "否"
                    },
                    {
                        'component': 'td',
                        'text': f"{data.get('seeding_time') / 3600:.1f}" if data.get('seeding_time') else "N/A"
                    },
                    {
                        'component': 'td',
                        'props': {
                            'class': 'text-no-wrap'
                        },
                        'text': "已删除" if data.get("deleted") else "正常"
                    }
                ]
            } for data in data_list
        ]

        # 拼装页面
        return [
            {
                'component': 'VRow',
                'content': self.__get_total_elements() + [
                    # 种子明细
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                        },
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'props': {
                                            'class': 'text-no-wrap'
                                        },
                                        'content': [
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '站点'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '标题'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '大小'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '上传量'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '下载量'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '分享率'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': 'HR'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '做种时间'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '状态'
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': torrent_trs
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    # region Brush

    def brush(self):
        """
        定时刷流，添加下载任务
        """
        if not self.__check_and_resolve_plugin_conflict():
            return

        brush_config = self.__get_brush_config()

        if not brush_config.brushsites or not brush_config.downloader or not self.downloader:
            return

        if not self.__is_current_time_in_range():
            logger.info(f"当前不在指定的刷流时间区间内，刷流操作将暂时暂停")
            return

        with lock:
            logger.info(f"开始执行刷流任务 ...")

            torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}
            self.__normalize_task_hash_keys(torrent_tasks)
            torrents_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)

            # 判断能否通过保种体积前置条件
            size_condition_passed, reason = self.__evaluate_size_condition_for_brush(torrents_size=torrents_size)
            self.__log_brush_conditions(passed=size_condition_passed, reason=reason)
            if not size_condition_passed:
                logger.info(f"刷流任务执行完成")
                return

            # 判断能否通过刷流前置条件
            pre_condition_passed, reason = self.__evaluate_pre_conditions_for_brush(include_yield_guard=False)
            self.__log_brush_conditions(passed=pre_condition_passed, reason=reason)
            if not pre_condition_passed:
                logger.info(f"刷流任务执行完成")
                return

            statistic_info = self.__get_statistic_info()

            # 获取所有站点的信息，并过滤掉不存在的站点
            site_infos = []
            for siteid in brush_config.brushsites:
                siteinfo = self.site_oper.get(siteid)
                if siteinfo:
                    site_infos.append(siteinfo)

            # 根据是否开启顺序刷流来决定是否需要打乱顺序
            if not brush_config.brush_sequential:
                random.shuffle(site_infos)

            logger.info(f"即将针对站点 {', '.join(site.name for site in site_infos)} 开始刷流")

            # 获取订阅标题
            subscribe_titles = self.__get_subscribe_titles()

            # 处理所有站点
            for site in site_infos:
                # 如果站点刷流没有正确响应，说明没有通过前置条件，其他站点也不需要继续刷流了
                if not self.__brush_site_torrents(siteid=site.id, torrent_tasks=torrent_tasks,
                                                  statistic_info=statistic_info,
                                                  subscribe_titles=subscribe_titles):
                    logger.info(f"站点 {site.name} 刷流中途结束，停止后续刷流")
                    break
                else:
                    logger.info(f"站点 {site.name} 刷流完成")

            # 保存数据
            self.save_data("torrents", torrent_tasks)
            # 保存统计数据
            self.save_data("statistic", statistic_info)
            logger.info(f"刷流任务执行完成")

    def __brush_site_torrents(self, siteid, torrent_tasks: Dict[str, dict], statistic_info: Dict[str, int],
                              subscribe_titles: Set[str]) -> bool:
        """
        针对站点进行刷流
        """
        siteinfo = self.site_oper.get(siteid)
        if not siteinfo:
            logger.warning(f"站点不存在：{siteid}")
            return True

        brush_config = self.__get_brush_config(sitename=siteinfo.name)

        logger.info(f"开始获取站点 {siteinfo.name} 的新种子 ...")
        if brush_config.include_second_page:
            torrents = []
            for page in range(2):
                page_torrents = self.torrents_chain.browse(domain=siteinfo.domain, page=page)
                if page_torrents:
                    torrents.extend(page_torrents)
                    logger.info(f"站点 {siteinfo.name} 第{page + 1}页获取到 {len(page_torrents)} 个种子")
                else:
                    break
        else:
            torrents = self.torrents_chain.browse(domain=siteinfo.domain)
        if not torrents:
            logger.info(f"站点 {siteinfo.name} 没有获取到种子")
            return True

        if brush_config.site_hr_active:
            logger.info(f"站点 {siteinfo.name} 已开启全站H&R选项，所有种子设置为H&R种子")

        # 排除包含订阅的种子
        if brush_config.except_subscribe:
            torrents = self.__filter_torrents_contains_subscribe(torrents=torrents, subscribe_titles=subscribe_titles)

        # 按发布日期降序排列
        torrents.sort(key=lambda x: x.pubdate or '', reverse=True)

        torrents_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)

        logger.info(f"正在准备种子刷流，数量 {len(torrents)}")

        # 过滤种子
        for torrent in torrents:
            # 判断能否通过刷流前置条件
            pre_condition_passed, reason = self.__evaluate_pre_conditions_for_brush(
                sitename=siteinfo.name,
                include_network_conditions=False
            )
            self.__log_brush_conditions(passed=pre_condition_passed, reason=reason)
            if not pre_condition_passed:
                return False

            logger.debug(f"种子详情：{torrent}")

            # 判断能否通过保种体积刷流条件
            size_condition_passed, reason = self.__evaluate_size_condition_for_brush(torrents_size=torrents_size,
                                                                                     add_torrent_size=torrent.size)
            self.__log_brush_conditions(passed=size_condition_passed, reason=reason, torrent=torrent)
            if not size_condition_passed:
                continue

            # 判断能否通过刷流条件
            condition_passed, reason = self.__evaluate_conditions_for_brush(torrent=torrent,
                                                                            torrent_tasks=torrent_tasks)
            self.__log_brush_conditions(passed=condition_passed, reason=reason, torrent=torrent)
            if not condition_passed:
                continue

            # 添加下载任务
            hash_string = self.__download(torrent=torrent)
            if not hash_string:
                logger.warning(f"{torrent.title} 添加刷流任务失败！")
                continue
            hash_string = self.__normalize_hash(hash_string)

            # 触发刷流下载时间并保存任务信息
            torrent_task = {
                "site": siteinfo.id,
                "site_name": siteinfo.name,
                "title": torrent.title,
                "size": torrent.size,
                "pubdate": torrent.pubdate,
                # "site_cookie": torrent.site_cookie,
                # "site_ua": torrent.site_ua,
                # "site_proxy": torrent.site_proxy,
                # "site_order": torrent.site_order,
                "description": torrent.description,
                "imdbid": torrent.imdbid,
                # "enclosure": torrent.enclosure,
                "page_url": torrent.page_url,
                # "seeders": torrent.seeders,
                # "peers": torrent.peers,
                # "grabs": torrent.grabs,
                "date_elapsed": torrent.date_elapsed,
                "freedate": torrent.freedate,
                "uploadvolumefactor": torrent.uploadvolumefactor,
                "downloadvolumefactor": torrent.downloadvolumefactor,
                "hit_and_run": torrent.hit_and_run or brush_config.site_hr_active,
                "volume_factor": torrent.volume_factor,
                "freedate_diff": torrent.freedate_diff,
                # "labels": torrent.labels,
                # "pri_order": torrent.pri_order,
                # "category": torrent.category,
                "ratio": 0,
                "downloaded": 0,
                "total_size": torrent.size,
                "uploaded": 0,
                "seeding_time": 0,
                "last_check_time": None,
                "last_check_uploaded": None,
                "last_check_interval_upspeed": None,
                "last_check_interval_seconds": None,
                "last_check_interval_uploaded": None,
                "last_check_interval_upspeed_valid": False,
                "last_check_interval_reason": "首次检查，暂不计算检查间上传速度",
                "interval_upspeed_hit_records": [],
                "first_downloaded_time": None,
                "first_uploaded_time": None,
                "deleted": False,
                "time": time.time()
            }
            torrent_task.update(self.__get_default_yield_guard_task_state())
            if brush_config.yield_guard_enabled and brush_config.yield_guard_stop_brush_when_good_pool:
                torrent_task["yield_guard_last_probe_time"] = time.time()

            self.eventmanager.send_event(etype=EventType.PluginTriggered, data={
                "plugin_id": self.__class__.__name__,
                "event_name": "brushflow_download_added",
                "hash": hash_string,
                "data": torrent_task,
                "downloader": self.service_info.name
            })
            torrent_tasks[hash_string] = torrent_task

            # 统计数据
            torrents_size += torrent.size
            statistic_info["count"] += 1
            logger.info(f"站点 {siteinfo.name}，新增刷流种子下载：{torrent.title}|{torrent.description}")
            self.__send_add_message(torrent)

        return True

    def __evaluate_size_condition_for_brush(self, torrents_size: float,
                                            add_torrent_size: float = 0.0) -> Tuple[bool, Optional[str]]:
        """
        过滤体积不符合条件的种子
        """
        brush_config = self.__get_brush_config()

        # 如果没有明确指定增加的种子大小，则检查配置中是否有种子大小下限，如果有，使用这个大小作为增加的种子大小
        preset_condition = False
        if not add_torrent_size and brush_config.size:
            size_limits = [float(size) * 1024 ** 3 for size in brush_config.size.split("-")]
            add_torrent_size = size_limits[0]  # 使用配置的种子大小下限
            preset_condition = True

        total_size = self.__bytes_to_gb(torrents_size + add_torrent_size)  # 预计总做种体积

        def generate_message(config):
            if add_torrent_size:
                if preset_condition:
                    return (f"当前做种体积 {self.__bytes_to_gb(torrents_size):.1f} GB，"
                            f"刷流种子下限 {self.__bytes_to_gb(add_torrent_size):.1f} GB，"
                            f"预计做种体积 {total_size:.1f} GB，"
                            f"超过设定的保种体积 {config} GB，暂时停止新增任务")
                else:
                    return (f"当前做种体积 {self.__bytes_to_gb(torrents_size):.1f} GB，"
                            f"刷流种子大小 {self.__bytes_to_gb(add_torrent_size):.1f} GB，"
                            f"预计做种体积 {total_size:.1f} GB，"
                            f"超过设定的保种体积 {config} GB")
            else:
                return (f"当前做种体积 {self.__bytes_to_gb(torrents_size):.1f} GB，"
                        f"超过设定的保种体积 {config} GB，暂时停止新增任务")

        reasons = [
            ("disksize",
             lambda config: torrents_size + add_torrent_size > float(config) * 1024 ** 3, generate_message)
        ]

        for condition, check, message in reasons:
            config_value = getattr(brush_config, condition, None)
            if config_value and check(config_value):
                reason = message(config_value)
                return False, reason

        return True, None

    def __evaluate_pre_conditions_for_brush(self, sitename: str = None, include_network_conditions: bool = True,
                                            include_yield_guard: bool = True) \
            -> Tuple[bool, Optional[str]]:
        """
        前置过滤不符合条件的种子
        """
        reasons = [
            ("maxdlcount", lambda config: self.__get_downloading_count() >= int(config),
             lambda config: f"当前同时下载任务数已达到最大值 {config}，暂时停止新增任务")
        ]

        if include_network_conditions:
            # 获取平均带宽
            avg_upload_speed, avg_download_speed = self.__get_average_bandwidth()
            if avg_upload_speed is not None and avg_download_speed is not None:
                reasons.extend([
                    ("maxupspeed", lambda config: avg_upload_speed >= float(config) * 1024,
                     lambda config: f"当前总上传带宽 {StringUtils.str_filesize(avg_upload_speed)}，"
                                    f"已达到最大值 {config} KB/s，暂时停止新增任务"),
                    ("maxdlspeed", lambda config: avg_download_speed >= float(config) * 1024,
                     lambda config: f"当前总下载带宽 {StringUtils.str_filesize(avg_download_speed)}，"
                                    f"已达到最大值 {config} KB/s，暂时停止新增任务"),
                ])

        brush_config = self.__get_brush_config(sitename=sitename)
        if include_yield_guard:
            yield_guard_passed, yield_guard_reason = self.__evaluate_yield_guard_brush_pre_condition(
                brush_config=brush_config,
                sitename=sitename
            )
            if not yield_guard_passed:
                return False, yield_guard_reason

        for condition, check, message in reasons:
            config_value = getattr(brush_config, condition, None)
            if config_value and check(config_value):
                reason = message(config_value)
                return False, reason

        return True, None

    def __evaluate_yield_guard_brush_pre_condition(self, brush_config: BrushConfig,
                                                   sitename: str = None) -> Tuple[bool, Optional[str]]:
        if (not brush_config.yield_guard_enabled
                or not brush_config.yield_guard_stop_brush_when_good_pool):
            return True, None

        torrent_tasks = self.get_data("torrents") or {}
        if not torrent_tasks:
            return True, None

        now = time.time()
        good_pool_count = 0
        probe_count = 0
        recent_probe_seconds = int(self.__yield_guard_positive_number(
            brush_config.yield_guard_probe_interval_minutes, 10
        ) * 60)
        recent_probe_exists = False
        for task in torrent_tasks.values():
            if not isinstance(task, dict) or task.get("deleted"):
                continue
            if sitename and task.get("site_name") != sitename:
                continue
            if task.get("yield_guard_good_protected"):
                good_pool_count += 1
            else:
                probe_count += 1
                last_probe_time = self.__number_or_none(task.get("yield_guard_last_probe_time"))
                if (recent_probe_seconds > 0 and last_probe_time is not None
                        and now - float(last_probe_time) < recent_probe_seconds):
                    recent_probe_exists = True

        good_pool_min = max(0, int(self.__yield_guard_positive_number(
            brush_config.yield_guard_good_pool_min_count, 2
        )))
        if good_pool_min <= 0 or good_pool_count < good_pool_min:
            return True, None

        probe_slots = int(self.__yield_guard_positive_number(brush_config.yield_guard_probe_slots, 1))
        if probe_slots <= 0:
            return False, (f"上传收益保护：高收益任务池 {good_pool_count} 个已达到阈值 {good_pool_min}，"
                           f"探测名额已关闭，暂时停止新增任务")

        if probe_count < probe_slots and not recent_probe_exists:
            return True, None

        return False, (f"上传收益保护：高收益任务池 {good_pool_count} 个已达到阈值 {good_pool_min}，"
                       f"探测任务 {probe_count} 个已达到名额 {probe_slots}，或最近探测间隔未到，暂时停止新增任务")

    def __evaluate_conditions_for_brush(self, torrent, torrent_tasks) -> Tuple[bool, Optional[str]]:
        """
        过滤不符合条件的种子
        """
        brush_config = self.__get_brush_config(torrent.site_name)

        # 排除重复种子
        # 默认根据标题和站点名称进行排除
        task_key = f"{torrent.site_name}{torrent.title}"
        if any(task_key == f"{task.get('site_name')}{task.get('title')}" for task in torrent_tasks.values()):
            return False, "重复种子"

        # 部分站点标题会上新时携带后缀，这里进一步根据种子详情地址进行排除
        if torrent.page_url:
            task_page_url = f"{torrent.site_name}{torrent.page_url}"
            if any(task_page_url == f"{task.get('site_name')}{task.get('page_url')}" for task in
                   torrent_tasks.values()):
                return False, "重复种子"

        # 不同站点如果遇到相同种子，判断前一个种子是否已经在做种，否则排除处理
        if torrent.title:
            if any(torrent.site_name != f"{task.get('site_name')}" and torrent.title == f"{task.get('title')}"
                   and not task.get("seed_time") for task in torrent_tasks.values()):
                return False, "其他站点存在尚未下载完成的相同种子"

        # 发布时间（优先判断，超出后直接排除）
        pubdate_minutes = self.__get_pubminutes(torrent.pubdate)
        # 已支持独立站点配置，取消单独适配站点时区逻辑，可通过配置项「pubtime」自行适配
        # pubdate_minutes = self.__adjust_site_pubminutes(pubdate_minutes, torrent)
        if brush_config.pubtime:
            pubtimes = [float(n) for n in brush_config.pubtime.split("-")]
            if len(pubtimes) == 1:
                # 单个值：选择发布时间小于等于该值的种子
                if pubdate_minutes > pubtimes[0]:
                    return False, f"发布时间 {torrent.pubdate}，{pubdate_minutes:.0f} 分钟前，不符合条件"
            else:
                # 范围值：选择发布时间在范围内的种子
                if not (pubtimes[0] <= pubdate_minutes <= pubtimes[1]):
                    return False, f"发布时间 {torrent.pubdate}，{pubdate_minutes:.0f} 分钟前，不在指定范围内"

        # 促销条件
        if brush_config.freeleech and not self.__is_free_torrent(torrent):
            return False, "非免费种子"
        if brush_config.freeleech == "2xfree" and not self.__is_2x_torrent(torrent):
            return False, "非双倍上传种子"

        # H&R
        if brush_config.hr == "yes" and torrent.hit_and_run:
            return False, "存在H&R"

        # 包含规则
        if brush_config.include and not (
                re.search(brush_config.include, torrent.title, re.I) or re.search(brush_config.include,
                                                                                  torrent.description, re.I)):
            return False, "不符合包含规则"

        # 排除规则
        if brush_config.exclude and (
                re.search(brush_config.exclude, torrent.title, re.I) or re.search(brush_config.exclude,
                                                                                  torrent.description, re.I)):
            return False, "符合排除规则"

        # 种子大小（GB）
        if brush_config.size:
            sizes = [float(size) * 1024 ** 3 for size in brush_config.size.split("-")]
            if len(sizes) == 1 and torrent.size < sizes[0]:
                return False, f"种子大小 {self.__bytes_to_gb(torrent.size):.1f} GB，不符合条件"
            elif len(sizes) > 1 and not sizes[0] <= torrent.size <= sizes[1]:
                return False, f"种子大小 {self.__bytes_to_gb(torrent.size):.1f} GB，不在指定范围内"

        # 做种人数
        if brush_config.seeder:
            seeders_range = [float(n) for n in brush_config.seeder.split("-")]
            # 检查是否仅指定了一个数字，即做种人数需要小于等于该数字
            if len(seeders_range) == 1:
                # 当做种人数大于该数字时，不符合条件
                if torrent.seeders > seeders_range[0]:
                    return False, f"做种人数 {torrent.seeders}，超过单个指定值"
            # 如果指定了一个范围
            elif len(seeders_range) > 1:
                # 检查做种人数是否在指定的范围内（包括边界）
                if not (seeders_range[0] <= torrent.seeders <= seeders_range[1]):
                    return False, f"做种人数 {torrent.seeders}，不在指定范围内"

        # 免费剩余时间（最后判断）
        if brush_config.free_remaining_time and self.__is_free_torrent(torrent):
            if self.__should_skip_free_remaining_time_filter(brush_config=brush_config):
                logger.info(f"免费剩余时间校验：当前处于例外时段 {brush_config.free_remaining_time_skip_range}，"
                            f"跳过该条件，种子：{torrent.title}")
                return True, None

            free_remaining_threshold = float(brush_config.free_remaining_time)
            free_remaining_minutes = self.__get_free_remaining_minutes(
                freedate=torrent.freedate,
                freedate_diff=torrent.freedate_diff,
                title=torrent.title,
                description=torrent.description
            )

            detail_parse_reason = ""
            if free_remaining_minutes is None:
                detail_page_text, detail_parse_reason = self.__get_torrent_detail_page_text(
                    site_id=getattr(torrent, "site", None),
                    page_url=torrent.page_url
                )
                if detail_page_text:
                    free_remaining_minutes = self.__get_free_remaining_minutes(
                        freedate=torrent.freedate,
                        freedate_diff=torrent.freedate_diff,
                        title=torrent.title,
                        description=detail_page_text
                    )
                    if free_remaining_minutes is not None:
                        logger.info(f"免费剩余时间校验：已通过详情页兜底解析，剩余 {free_remaining_minutes:.0f} 分钟，"
                                    f"种子：{torrent.title}")

            if free_remaining_minutes is None:
                reason = (f"无法识别免费剩余时间（截止：{torrent.freedate or '未知'}，"
                          f"剩余：{torrent.freedate_diff or '未知'}）")
                if detail_parse_reason:
                    reason = f"{reason}，详情页解析失败：{detail_parse_reason}"
                return False, f"{reason}，按阈值策略跳过"
            logger.info(f"免费剩余时间校验：剩余 {free_remaining_minutes:.0f} 分钟，"
                        f"阈值 {free_remaining_threshold:.0f} 分钟，种子：{torrent.title}")
            if free_remaining_minutes < free_remaining_threshold:
                return False, (f"免费剩余时间 {free_remaining_minutes:.0f} 分钟，"
                               f"低于设置的 {free_remaining_threshold:.0f} 分钟")

        return True, None

    @staticmethod
    def __log_brush_conditions(passed: bool, reason: str, torrent: Any = None):
        """
        记录刷流日志
        """
        if not passed:
            if not torrent:
                logger.warning(f"没有通过前置刷流条件校验，原因：{reason}")
            else:
                # 与免费相关的过滤建议默认可见，便于排查“为何仍下载不到免费种”
                if any(keyword in reason for keyword in ["免费剩余时间", "无法识别免费", "非免费种子"]):
                    logger.info(f"种子没有通过刷流条件校验，原因：{reason} 种子：{torrent.title}|{torrent.description}")
                else:
                    logger.debug(f"种子没有通过刷流条件校验，原因：{reason} 种子：{torrent.title}|{torrent.description}")

    # endregion

    # region Check

    def check(self):
        """
        定时检查，删除下载任务
        """
        if not self.__check_and_resolve_plugin_conflict():
            return

        brush_config = self.__get_brush_config()

        if not brush_config.downloader or not self.downloader:
            return

        with lock:
            logger.info("开始检查刷流下载任务 ...")
            torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}
            unmanaged_tasks: Dict[str, dict] = self.get_data("unmanaged") or {}
            self.__normalize_task_hash_keys(torrent_tasks)
            self.__normalize_task_hash_keys(unmanaged_tasks)

            downloader = self.downloader
            seeding_torrents, error = downloader.get_torrents()
            if error:
                logger.warning("连接下载器出错，将在下个时间周期重试")
                return

            seeding_torrents_dict = {self.__get_hash(torrent): torrent for torrent in seeding_torrents}
            seeding_torrents_dict = {hash_value: torrent for hash_value, torrent in seeding_torrents_dict.items()
                                     if hash_value}

            # 检查种子刷流标签变更情况
            self.__update_seeding_tasks_based_on_tags(torrent_tasks=torrent_tasks, unmanaged_tasks=unmanaged_tasks,
                                                      seeding_torrents_dict=seeding_torrents_dict)
            self.__normalize_task_hash_keys(torrent_tasks)
            self.__normalize_task_hash_keys(unmanaged_tasks)

            torrent_check_hashes = list(torrent_tasks.keys())
            if not torrent_tasks or not torrent_check_hashes:
                logger.info("没有需要检查的刷流下载任务")
                return
            for torrent_task in torrent_tasks.values():
                self.__clear_yield_guard_check_cache(torrent_task)

            logger.info(f"共有 {len(torrent_check_hashes)} 个任务正在刷流，开始检查任务状态")

            # 获取到当前所有做种数据中需要被检查的种子数据
            check_torrents = [seeding_torrents_dict[th] for th in torrent_check_hashes if th in seeding_torrents_dict]

            # 先更新刷流任务的最新状态，上下传，分享率
            self.__update_torrent_tasks_state(torrents=check_torrents, torrent_tasks=torrent_tasks)

            # 更新刷流任务列表中在下载器中删除的种子为删除状态
            self.__update_undeleted_torrents_missing_in_downloader(torrent_tasks, torrent_check_hashes, seeding_torrents)

            # 根据配置的标签进行种子排除
            if check_torrents:
                logger.info(f"当前刷流任务共 {len(check_torrents)} 个有效种子，正在准备按设定的种子标签进行排除")
                # 初始化一个空的列表来存储需要排除的标签
                tags_to_exclude = set()
                # 如果 delete_except_tags 非空且不是纯空白，则添加到排除列表中
                if brush_config.delete_except_tags and brush_config.delete_except_tags.strip():
                    tags_to_exclude.update(tag.strip() for tag in brush_config.delete_except_tags.split(','))
                # 将所有需要排除的标签组合成一个字符串，每个标签之间用逗号分隔
                combined_tags = ",".join(tags_to_exclude)
                if combined_tags:  # 确保有标签需要排除
                    pre_filter_count = len(check_torrents)  # 获取过滤前的任务数量
                    check_torrents = self.__filter_torrents_by_tag(torrents=check_torrents, exclude_tag=combined_tags)
                    post_filter_count = len(check_torrents)  # 获取过滤后的任务数量
                    excluded_count = pre_filter_count - post_filter_count  # 计算被排除的任务数量
                    logger.info(
                        f"有效种子数 {pre_filter_count}，排除标签 '{combined_tags}' 后，"
                        f"剩余种子数 {post_filter_count}，排除种子数 {excluded_count}")
                else:
                    logger.info("没有配置有效的排除标签，所有种子均参与后续处理")

            # 种子删除检查
            if not check_torrents:
                logger.info("没有需要检查的任务，跳过")
            else:
                need_delete_hashes = []
                delete_message_map = {}
                delete_summary_messages = []

                # 统计托管种子中正在下载的个数（用下载器实时数据，不用缓存）
                downloading_count = self.__count_managed_downloading_torrents(
                    torrent_tasks=torrent_tasks,
                    seeding_torrents_dict=seeding_torrents_dict
                )

                # 上传收益保护的限速/暂停动作先执行，最终删除仍交给后续删种流程统一处理
                self.__apply_yield_guard_actions(torrents=check_torrents, torrent_tasks=torrent_tasks)

                # 如果配置了动态删除以及删种阈值，则根据动态删种进行分组处理
                if brush_config.proxy_delete and brush_config.delete_size_range:
                    logger.info("已开启动态删种，按系统默认动态删种条件开始检查任务")
                    # 在动态删种模式下，先执行“失去免费即删种”，避免受动态阈值影响而漏删
                    no_free_delete_hashes = self.__delete_torrent_for_no_free(torrents=check_torrents,
                                                                              torrent_tasks=torrent_tasks,
                                                                              delete_message_map=delete_message_map) or []
                    need_delete_hashes.extend(no_free_delete_hashes)
                    no_free_delete_hash_set = set(no_free_delete_hashes)
                    proxy_check_torrents = [torrent for torrent in check_torrents
                                            if self.__get_hash(torrent) not in no_free_delete_hash_set]
                    yield_guard_delete_hashes = self.__delete_torrent_for_yield_guard(torrents=proxy_check_torrents,
                                                                                      torrent_tasks=torrent_tasks,
                                                                                      delete_message_map=delete_message_map) or []
                    need_delete_hashes.extend(yield_guard_delete_hashes)
                    forced_delete_hash_set = no_free_delete_hash_set | set(yield_guard_delete_hashes)
                    proxy_check_torrents = [torrent for torrent in check_torrents
                                            if self.__get_hash(torrent) not in forced_delete_hash_set]

                    proxy_delete_hashes = self.__delete_torrent_for_proxy(torrents=proxy_check_torrents,
                                                                          torrent_tasks=torrent_tasks,
                                                                          delete_message_map=delete_message_map,
                                                                          delete_summary_messages=delete_summary_messages,
                                                                          downloading_count=downloading_count) or []
                    need_delete_hashes.extend(proxy_delete_hashes)
                # 否则均认为是没有开启动态删种
                else:
                    logger.info("没有开启动态删种，按用户设置删种条件开始检查任务")
                    not_proxy_delete_hashes = self.__delete_torrent_for_evaluate_conditions(torrents=check_torrents,
                                                                                            torrent_tasks=torrent_tasks,
                                                                                            delete_message_map=delete_message_map,
                                                                                            downloading_count=downloading_count) or []
                    need_delete_hashes.extend(not_proxy_delete_hashes)

                if need_delete_hashes:
                    need_delete_hashes = list(dict.fromkeys([hash_value for hash_value in need_delete_hashes if hash_value]))
                    # 如果是QB，则重新汇报Tracker
                    if self.downloader_helper.is_downloader("qbittorrent", service=self.service_info):
                        self.__qb_torrents_reannounce(torrent_hashes=need_delete_hashes)
                    # 删除种子
                    deleted_hashes = []
                    failed_hashes = []
                    if downloader.delete_torrents(ids=need_delete_hashes, delete_file=True):
                        deleted_hashes = list(need_delete_hashes)
                        latest_torrents, latest_error = downloader.get_torrents()
                        if latest_torrents is not None:
                            latest_hash_set = set(self.__get_all_hashes(latest_torrents))
                            failed_hashes = [torrent_hash for torrent_hash in need_delete_hashes
                                             if torrent_hash in latest_hash_set]
                            deleted_hashes = [torrent_hash for torrent_hash in need_delete_hashes
                                              if torrent_hash not in latest_hash_set]
                            if failed_hashes:
                                logger.error(
                                    f"删种后校验发现仍有 {len(failed_hashes)} 个种子残留（应删除含文件），"
                                    f"hash={','.join(failed_hashes[:10])}")
                        elif latest_error:
                            logger.warning(f"删种后校验失败：{latest_error}，将按删除接口返回结果处理")
                    else:
                        failed_hashes = list(need_delete_hashes)
                        logger.error(
                            f"下载器返回删种失败，删除目标（含文件）共 {len(failed_hashes)} 个，"
                            f"hash={','.join(failed_hashes[:10])}")

                    if deleted_hashes:
                        for torrent_hash in deleted_hashes:
                            if torrent_hash in torrent_tasks:
                                torrent_tasks[torrent_hash]["deleted"] = True
                                torrent_tasks[torrent_hash]["deleted_time"] = time.time()
                        self.__send_delete_messages_after_success(delete_hashes=deleted_hashes,
                                                                  delete_message_map=delete_message_map,
                                                                  torrent_tasks=torrent_tasks)
                        self.__send_delete_summary_messages_after_success(delete_hashes=deleted_hashes,
                                                                          delete_summary_messages=delete_summary_messages)

                    if failed_hashes:
                        self.__send_delete_failed_message(failed_hashes=failed_hashes, torrent_tasks=torrent_tasks)

            # 归档数据
            self.__auto_archive_tasks(torrent_tasks=torrent_tasks)

            self.__update_and_save_statistic_info(torrent_tasks)

            self.save_data("torrents", torrent_tasks)

            logger.info("刷流下载任务检查完成")

    def __update_torrent_tasks_state(self, torrents: List[Any], torrent_tasks: Dict[str, dict]):
        """
        更新刷流任务的最新状态，上下传，分享率
        """
        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)
            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue

            torrent_info = self.__get_torrent_info(torrent)
            check_time = int(time.time())
            uploaded = torrent_info.get("uploaded") or 0
            downloaded = torrent_info.get("downloaded") or 0

            # 记录首次有下载数据的时间（存量迁移 + 新种子追踪）
            if torrent_task.get("first_downloaded_time") is None and downloaded > 0:
                torrent_task["first_downloaded_time"] = check_time
            # 记录首次有上传数据的时间（存量迁移 + 新种子追踪）
            if torrent_task.get("first_uploaded_time") is None and uploaded > 0:
                torrent_task["first_uploaded_time"] = check_time

            last_check_uploaded = torrent_task.get("last_check_uploaded")
            last_check_downloaded = torrent_task.get("last_check_downloaded")
            last_check_time = torrent_task.get("last_check_time")

            interval_speed = None
            interval_seconds = None
            interval_uploaded = None
            interval_valid = False
            interval_reason = "首次检查，暂不计算检查间上传速度"
            interval_downspeed = None
            interval_downloaded = None
            interval_downspeed_valid = False
            interval_downspeed_reason = "首次检查，暂不计算检查间下载速度"

            if isinstance(last_check_uploaded, (int, float)) and isinstance(last_check_time, (int, float)):
                try:
                    interval_seconds = check_time - int(float(last_check_time))
                    interval_uploaded = float(uploaded) - float(last_check_uploaded)
                    if interval_seconds <= 0:
                        interval_reason = "检查间隔异常，已跳过本次低速统计"
                    elif interval_uploaded < 0:
                        interval_reason = "上传量出现回退，已跳过本次低速统计"
                    else:
                        interval_speed = float(interval_uploaded) / interval_seconds
                        interval_valid = True
                        interval_reason = ""
                except (TypeError, ValueError):
                    interval_reason = "检查间基线异常，已跳过本次低速统计"

            if isinstance(last_check_downloaded, (int, float)) and isinstance(last_check_time, (int, float)):
                try:
                    down_interval_seconds = check_time - int(float(last_check_time))
                    interval_downloaded = float(downloaded) - float(last_check_downloaded)
                    if down_interval_seconds <= 0:
                        interval_downspeed_reason = "检查间隔异常，已跳过本次下载速度统计"
                    elif interval_downloaded < 0:
                        interval_downspeed_reason = "下载量出现回退，已跳过本次下载速度统计"
                    else:
                        interval_downspeed = float(interval_downloaded) / down_interval_seconds
                        interval_downspeed_valid = True
                        interval_downspeed_reason = ""
                except (TypeError, ValueError):
                    interval_downspeed_reason = "检查间下载基线异常，已跳过本次下载速度统计"

            # 更新上传量、下载量
            torrent_task.update({
                "downloaded": torrent_info.get("downloaded"),
                "total_size": torrent_info.get("total_size"),
                "uploaded": uploaded,
                "ratio": torrent_info.get("ratio"),
                "seeding_time": torrent_info.get("seeding_time"),
                "last_check_time": check_time,
                "last_check_uploaded": uploaded,
                "last_check_downloaded": downloaded,
                "last_check_interval_upspeed": interval_speed,
                "last_check_interval_seconds": interval_seconds,
                "last_check_interval_uploaded": interval_uploaded,
                "last_check_interval_upspeed_valid": interval_valid,
                "last_check_interval_reason": interval_reason,
                "last_check_interval_downloaded": interval_downloaded,
                "last_check_interval_downspeed": interval_downspeed,
                "last_check_interval_downspeed_valid": interval_downspeed_valid,
                "last_check_interval_downspeed_reason": interval_downspeed_reason
            })

    def __apply_yield_guard_actions(self, torrents: List[Any], torrent_tasks: Dict[str, dict]):
        """
        根据最新采样对低收益任务执行限速/暂停动作。delete 动作由现有删除流程统一处理。
        """
        if not torrents:
            return

        evaluated_count = 0
        action_count = 0
        delete_count = 0
        good_protected_count = 0
        low_yield_count = 0
        reason_samples = []
        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash)
            if not torrent_hash or not torrent_task or torrent_task.get("deleted"):
                continue
            self.__clear_yield_guard_check_cache(torrent_task)

            site_name = torrent_task.get("site_name", "")
            brush_config = self.__get_brush_config(sitename=site_name)
            if not brush_config.yield_guard_enabled:
                continue

            torrent_info = self.__get_torrent_info(torrent)
            if not self.__is_yield_guard_applicable_torrent(torrent_info=torrent_info):
                self.__reset_yield_guard_runtime_state_for_skip(torrent_task)
                continue

            should_delete, reason = self.__evaluate_yield_guard_for_delete(
                site_name=site_name,
                brush_config=brush_config,
                torrent_info=torrent_info,
                torrent_task=torrent_task
            )
            torrent_task["yield_guard_evaluated_in_check"] = True
            torrent_task["yield_guard_should_delete"] = bool(should_delete)
            evaluated_count += 1
            if torrent_task.get("yield_guard_good_protected"):
                good_protected_count += 1
            if torrent_task.get("yield_guard_bad_streak"):
                low_yield_count += 1
            self.__log_yield_guard_detail_if_enabled(
                site_name=site_name,
                brush_config=brush_config,
                torrent_hash=torrent_hash,
                torrent_info=torrent_info,
                torrent_task=torrent_task,
                should_delete=should_delete,
                reason=reason
            )
            if reason and len(reason_samples) < 5:
                reason_samples.append(
                    f"{torrent_task.get('title', '') or torrent_hash}：{reason}"
                )
            if should_delete:
                delete_count += 1
                continue

            stage = torrent_task.get("yield_guard_stage")
            action = None
            if torrent_task.get("yield_guard_restore_download_limit"):
                action = "restore_limit"
            elif stage == "limited":
                action = "limit"
            elif stage == "paused":
                action = "pause"

            if action:
                if self.__apply_yield_guard_action_for_task(torrent_hash=torrent_hash,
                                                            torrent_task=torrent_task,
                                                            action=action,
                                                            brush_config=brush_config,
                                                            site_name=site_name,
                                                            reason=reason):
                    if not brush_config.yield_guard_rehearsal:
                        logger.info(f"站点：{site_name}，{reason}，已执行上传收益保护动作：{action}")
                    action_count += 1

        if evaluated_count > 0:
            sample_text = "；".join(reason_samples)
            logger.info(
                f"上传收益保护：本轮检查已评估 {evaluated_count} 个任务，"
                f"高收益保护 {good_protected_count} 个，低收益命中 {low_yield_count} 个，"
                f"待删除 {delete_count} 个，已记录/执行动作 {action_count} 个"
                f"{'；样例：' + sample_text if sample_text else ''}"
            )

    def __log_yield_guard_detail_if_enabled(self, site_name: str, brush_config: BrushConfig, torrent_hash: str,
                                            torrent_info: dict, torrent_task: dict, should_delete: bool,
                                            reason: str) -> None:
        if not brush_config.yield_guard_detail_log:
            return

        interval_downspeed = self.__number_or_none(torrent_task.get("last_check_interval_downspeed"))
        interval_upspeed = self.__number_or_none(torrent_task.get("last_check_interval_upspeed"))
        avg_upspeed = self.__number_or_none(torrent_info.get("avg_upspeed"))
        downloaded = self.__number_or_none(torrent_info.get("downloaded")) or 0
        total_size = self.__number_or_none(torrent_info.get("total_size")) or 0
        progress_percent = (downloaded / total_size * 100) if total_size > 0 else 0

        high_download_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_high_download_kbs) * 1024
        low_upload_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_low_upload_kbs) * 1024
        low_ratio_percent = self.__yield_guard_positive_number(brush_config.yield_guard_low_ratio_percent)
        ratio_min_download_bytes = (
                self.__yield_guard_positive_number(brush_config.yield_guard_ratio_min_download_kbs) * 1024
        )
        ratio_protect_upload_bytes = (
                self.__yield_guard_positive_number(brush_config.yield_guard_ratio_protect_upload_kbs) * 1024
        )
        min_downloaded_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_min_downloaded_gb) * 1024 ** 3
        min_progress_percent = self.__yield_guard_positive_number(brush_config.yield_guard_min_progress_percent)
        bad_checks = max(1, int(self.__yield_guard_positive_number(brush_config.yield_guard_bad_checks, 2)))

        downspeed_valid = bool(torrent_task.get("last_check_interval_downspeed_valid",
                                                torrent_info.get("last_check_interval_downspeed_valid", False)))
        upspeed_valid = bool(torrent_task.get("last_check_interval_upspeed_valid",
                                              torrent_info.get("last_check_interval_upspeed_valid", False)))
        is_high_download = high_download_bytes > 0 and interval_downspeed is not None and interval_downspeed >= high_download_bytes
        is_low_upload = interval_upspeed is not None and interval_upspeed <= low_upload_bytes
        yield_ratio_percent = self.__calculate_yield_guard_ratio_percent(
            interval_upspeed=interval_upspeed,
            interval_downspeed=interval_downspeed
        )
        has_ratio_download = (
                ratio_min_download_bytes > 0
                and interval_downspeed is not None
                and interval_downspeed >= ratio_min_download_bytes
        )
        is_low_ratio = (
                low_ratio_percent > 0
                and has_ratio_download
                and yield_ratio_percent is not None
                and yield_ratio_percent <= low_ratio_percent
        )
        is_absolute_low_yield = is_high_download and is_low_upload
        is_ratio_upload_protected = (
                is_low_ratio
                and ratio_protect_upload_bytes > 0
                and interval_upspeed is not None
                and interval_upspeed >= ratio_protect_upload_bytes
        )
        is_limited_low_upload = torrent_task.get("yield_guard_stage") == "limited" and is_low_upload
        sample_checks = []
        if min_downloaded_bytes > 0:
            sample_checks.append(downloaded >= min_downloaded_bytes)
        if min_progress_percent > 0:
            sample_checks.append(progress_percent >= min_progress_percent)
        has_enough_sample = any(sample_checks) if sample_checks else True

        if torrent_task.get("yield_guard_good_protected"):
            decision = "高收益保护"
        elif should_delete:
            decision = "低收益待删除"
        elif torrent_task.get("yield_guard_bad_streak"):
            decision = "低收益观察/动作"
        elif not (downspeed_valid and upspeed_valid):
            decision = "采样未就绪"
        else:
            decision = "未命中低收益"

        decision_reasons = []
        if decision in {"未命中低收益", "采样未就绪", "低收益观察/动作"}:
            if not (downspeed_valid and upspeed_valid):
                decision_reasons.append("采样未就绪")
            else:
                if is_absolute_low_yield:
                    decision_reasons.append(
                        f"检查间下载 {self.__format_speed_kbs(interval_downspeed)} 达到高下载阈值 "
                        f"{brush_config.yield_guard_high_download_kbs} KB/s，"
                        f"检查间上传 {self.__format_speed_kbs(interval_upspeed)} 低于低上传阈值 "
                        f"{brush_config.yield_guard_low_upload_kbs} KB/s"
                    )
                if is_low_ratio:
                    decision_reasons.append(
                        f"收益比 {self.__format_percent(yield_ratio_percent)} 低于低收益比阈值 "
                        f"{brush_config.yield_guard_low_ratio_percent}%"
                    )
                if is_ratio_upload_protected:
                    decision_reasons.append(
                        f"检查间上传 {self.__format_speed_kbs(interval_upspeed)} 达到收益比保护上传阈值 "
                        f"{brush_config.yield_guard_ratio_protect_upload_kbs} KB/s，继续观察"
                    )
                if is_limited_low_upload and not is_high_download and not is_low_ratio:
                    decision_reasons.append("任务已限速且上传仍低，保持收益保护并继续按低收益处理")
                if not is_high_download and not is_low_ratio and not is_limited_low_upload:
                    decision_reasons.append(
                        f"检查间下载 {self.__format_speed_kbs(interval_downspeed)} 低于高下载阈值 "
                        f"{brush_config.yield_guard_high_download_kbs} KB/s"
                    )
                if not is_low_upload and not is_low_ratio:
                    decision_reasons.append(
                        f"检查间上传 {self.__format_speed_kbs(interval_upspeed)} 高于低上传阈值 "
                        f"{brush_config.yield_guard_low_upload_kbs} KB/s"
                    )
                if not is_low_ratio:
                    if not has_ratio_download:
                        decision_reasons.append(
                            f"检查间下载 {self.__format_speed_kbs(interval_downspeed)} 低于收益比判断最小下载速度 "
                            f"{brush_config.yield_guard_ratio_min_download_kbs} KB/s"
                        )
                    elif yield_ratio_percent is None:
                        decision_reasons.append("收益比无法计算")
                    else:
                        decision_reasons.append(
                            f"收益比 {self.__format_percent(yield_ratio_percent)} 高于低收益比阈值 "
                            f"{brush_config.yield_guard_low_ratio_percent}%"
                        )
                if not has_enough_sample:
                    decision_reasons.append("下载量和进度未达到收益保护最小样本门槛")
                if (
                        is_absolute_low_yield
                        or (is_low_ratio and not is_ratio_upload_protected)
                        or is_limited_low_upload
                ) and has_enough_sample:
                    bad_streak = int(self.__yield_guard_positive_number(torrent_task.get("yield_guard_bad_streak"), 0))
                    if bad_streak < bad_checks:
                        decision_reasons.append(f"低收益连续命中 {bad_streak}/{bad_checks}，仍在观察")
        decision_reason = "；".join(decision_reasons) if decision_reasons else (reason or "已命中保护/动作条件")

        stage = torrent_task.get("yield_guard_stage") or "normal"
        planned_action = "delete" if should_delete else "none"
        if not should_delete:
            if torrent_task.get("yield_guard_restore_download_limit"):
                planned_action = "restore_limit"
            elif stage == "limited":
                planned_action = "limit"
            elif stage == "paused":
                planned_action = "pause"

        logger.info(
            f"站点：{site_name}，上传收益保护详细日志："
            f"hash={torrent_hash}，任务={torrent_task.get('title', '')}|{torrent_task.get('description', '')}，"
            f"判定={decision}，判定原因={decision_reason}，意图={planned_action}，阶段={stage}，"
            f"检查间下载 {self.__format_speed_kbs(interval_downspeed)}，"
            f"检查间上传 {self.__format_speed_kbs(interval_upspeed)}，"
            f"平均上传 {self.__format_speed_kbs(avg_upspeed)}，"
            f"已下载 {downloaded / 1024 ** 3:.2f} GB，进度 {progress_percent:.1f}%，"
            f"连续低收益 {int(self.__yield_guard_positive_number(torrent_task.get('yield_guard_bad_streak'), 0))}/{bad_checks}，"
            f"条件：采样={'是' if downspeed_valid and upspeed_valid else '否'}，"
            f"高下载={'是' if is_high_download else '否'}(阈值 {brush_config.yield_guard_high_download_kbs} KB/s)，"
            f"低上传={'是' if is_low_upload else '否'}(阈值 {brush_config.yield_guard_low_upload_kbs} KB/s)，"
            f"收益比 {self.__format_percent(yield_ratio_percent)}，"
            f"低收益比={'是' if is_low_ratio else '否'}"
            f"(阈值 {brush_config.yield_guard_low_ratio_percent}%/"
            f"最小下载 {brush_config.yield_guard_ratio_min_download_kbs} KB/s)，"
            f"低收益比上传保护={'是' if is_ratio_upload_protected else '否'}"
            f"(阈值 {brush_config.yield_guard_ratio_protect_upload_kbs} KB/s)，"
            f"限速后低上传={'是' if is_limited_low_upload else '否'}，"
            f"样本足够={'是' if has_enough_sample else '否'}"
            f"(下载阈值 {brush_config.yield_guard_min_downloaded_gb} GB/进度阈值 {brush_config.yield_guard_min_progress_percent}%)，"
            f"原因：{reason or '无'}"
        )

    @staticmethod
    def __format_speed_kbs(speed_bytes: Optional[float]) -> str:
        if speed_bytes is None:
            return "未知"
        return f"{speed_bytes / 1024:.1f} KB/s"

    @staticmethod
    def __format_percent(percent: Optional[float]) -> str:
        if percent is None:
            return "未知"
        return f"{percent:.1f}%"

    @staticmethod
    def __calculate_yield_guard_ratio_percent(interval_upspeed: Optional[float],
                                             interval_downspeed: Optional[float]) -> Optional[float]:
        if interval_upspeed is None or interval_downspeed is None or interval_downspeed <= 0:
            return None
        return max(0.0, float(interval_upspeed)) / float(interval_downspeed) * 100

    @staticmethod
    def __clear_yield_guard_check_cache(torrent_task: dict) -> None:
        if not isinstance(torrent_task, dict):
            return
        torrent_task.pop("yield_guard_evaluated_in_check", None)
        torrent_task.pop("yield_guard_should_delete", None)

    @classmethod
    def __normalize_hash(cls, hash_value: Any) -> str:
        """
        统一种子hash格式，避免下载器返回大小写不同导致任务匹配失败。
        """
        return str(hash_value).strip().lower() if hash_value else ""

    @classmethod
    def __extract_hash_from_magnet(cls, magnet_url: str) -> str:
        """
        从磁力链接中提取BTIH v1 hash，作为qB标签反查失败时的确定性兜底。
        """
        if not magnet_url or not str(magnet_url).startswith("magnet:"):
            return ""
        try:
            query_params = parse_qs(urlparse(str(magnet_url)).query)
            xt_values = query_params.get("xt") or []
            for xt_value in xt_values:
                match = re.search(r"urn:btih:([a-fA-F0-9]{40})", xt_value)
                if match:
                    return cls.__normalize_hash(match.group(1))
                match = re.search(r"urn:btih:([a-zA-Z2-7]{32})", xt_value)
                if match:
                    return base64.b32decode(match.group(1).upper()).hex()
        except Exception:
            return ""
        return ""

    @classmethod
    def __bencoded_value_end(cls, data: bytes, start: int) -> int:
        """
        返回从 start 开始的 bencode 值结束位置，用于提取 .torrent info 字典原始字节。
        """
        if start < 0 or start >= len(data):
            return -1

        token = data[start:start + 1]
        if token == b"i":
            end = data.find(b"e", start + 1)
            return end + 1 if end != -1 else -1

        if token in (b"l", b"d"):
            index = start + 1
            while index < len(data) and data[index:index + 1] != b"e":
                index = cls.__bencoded_value_end(data, index)
                if index == -1:
                    return -1
            return index + 1 if index < len(data) else -1

        if token.isdigit():
            colon = data.find(b":", start)
            if colon == -1:
                return -1
            try:
                length = int(data[start:colon])
            except ValueError:
                return -1
            end = colon + 1 + length
            return end if end <= len(data) else -1

        return -1

    @classmethod
    def __extract_info_hash_from_torrent_content(cls, torrent_content: Any) -> str:
        """
        从 .torrent bencode 内容中提取 v1 infohash。
        """
        if not isinstance(torrent_content, (bytes, bytearray)):
            return ""

        data = bytes(torrent_content)
        if not data.startswith(b"d"):
            return ""

        index = 1
        while index < len(data) and data[index:index + 1] != b"e":
            if not data[index:index + 1].isdigit():
                return ""

            colon = data.find(b":", index)
            if colon == -1:
                return ""
            try:
                key_length = int(data[index:colon])
            except ValueError:
                return ""

            key_start = colon + 1
            key_end = key_start + key_length
            if key_end > len(data):
                return ""

            key = data[key_start:key_end]
            value_start = key_end
            value_end = cls.__bencoded_value_end(data, value_start)
            if value_end == -1:
                return ""

            if key == b"info":
                return hashlib.sha1(data[value_start:value_end]).hexdigest()

            index = value_end

        return ""

    @classmethod
    def __extract_hash_from_download_content(cls, torrent_content: Any) -> str:
        """
        从添加给下载器的内容中提取可确定的 hash。磁力链接和 .torrent 文件均可兜底。
        """
        magnet_hash = cls.__extract_hash_from_magnet(torrent_content) if isinstance(torrent_content, str) else ""
        if magnet_hash:
            return magnet_hash
        return cls.__extract_info_hash_from_torrent_content(torrent_content)

    @classmethod
    def __merge_torrent_task(cls, existing_task: dict, incoming_task: dict) -> dict:
        """
        合并大小写不同但实际相同hash的任务记录。保留原任务的站点/详情页等元数据，
        同时吸收新记录中的实时统计字段。
        """
        if not existing_task:
            return incoming_task or {}
        if not incoming_task:
            return existing_task

        merged_task = dict(existing_task)
        for key, value in incoming_task.items():
            if value in (None, ""):
                continue
            if key == "deleted":
                merged_task[key] = bool(existing_task.get("deleted")) and bool(value)
                continue
            if key == "deleted_time" and not merged_task.get("deleted"):
                continue
            if merged_task.get(key) in (None, "", 0, [], {}):
                merged_task[key] = value
                continue
            if key in {
                "downloaded", "uploaded", "ratio", "seeding_time", "total_size",
                "last_check_time", "last_check_uploaded", "last_check_interval_upspeed",
                "last_check_interval_seconds", "last_check_interval_uploaded",
                "last_check_interval_upspeed_valid", "last_check_interval_reason",
                "interval_upspeed_hit_records", "first_downloaded_time",
                "first_uploaded_time"
            }:
                merged_task[key] = value
        return merged_task

    def __normalize_task_hash_keys(self, torrent_tasks: Dict[str, dict]) -> None:
        """
        就地规范化任务字典的hash键，并合并大小写不同的重复任务。
        """
        if not torrent_tasks:
            return

        normalized_tasks = {}
        for hash_value, task in list(torrent_tasks.items()):
            normalized_hash = self.__normalize_hash(hash_value)
            if not normalized_hash:
                continue
            if normalized_hash in normalized_tasks:
                normalized_tasks[normalized_hash] = self.__merge_torrent_task(
                    normalized_tasks[normalized_hash],
                    task
                )
            else:
                normalized_tasks[normalized_hash] = task

        torrent_tasks.clear()
        torrent_tasks.update(normalized_tasks)

    def __count_managed_downloading_torrents(self, torrent_tasks: Dict[str, dict],
                                             seeding_torrents_dict: Dict[str, Any]) -> int:
        """
        从下载器实时数据中统计插件托管且未完成下载的任务数量。
        """
        if not torrent_tasks or not seeding_torrents_dict:
            return 0

        downloading_count = 0
        for torrent_hash, task in torrent_tasks.items():
            if task.get("deleted"):
                continue
            live = seeding_torrents_dict.get(self.__normalize_hash(torrent_hash))
            if not live:
                continue
            live_info = self.__get_torrent_info(live)
            total_size = live_info.get("total_size") or 0
            downloaded = live_info.get("downloaded") or 0
            if total_size > 0 and downloaded < total_size:
                downloading_count += 1
        return downloading_count

    def __get_downloader_hash_snapshot(self, downloader) -> Optional[Set[str]]:
        """
        获取下载器当前 hash 集。下载器不支持或连接异常时返回 None。
        """
        if not downloader or not hasattr(downloader, "get_torrents"):
            return None

        try:
            torrents_result = downloader.get_torrents()
            if isinstance(torrents_result, tuple):
                torrents = torrents_result[0] if len(torrents_result) > 0 else []
                error = torrents_result[1] if len(torrents_result) > 1 else None
                if error:
                    logger.warning(f"获取下载器种子列表失败，无法通过新增hash差集定位任务：{error}")
                    return None
            else:
                torrents = torrents_result

            return set(self.__get_all_hashes(torrents or []))
        except Exception as e:
            logger.warning(f"获取下载器种子列表异常，无法通过新增hash差集定位任务：{str(e)}")
            return None

    def __get_added_hash_by_snapshot_diff(self, downloader, before_hashes: Optional[Set[str]],
                                          retries: int = 5, interval: int = 1) -> str:
        """
        qB 标签异步未刷新时，通过添加前后下载器全量 hash 差集定位新增任务。
        """
        if before_hashes is None:
            return ""

        for retry_index in range(retries):
            after_hashes = self.__get_downloader_hash_snapshot(downloader=downloader)
            if after_hashes is None:
                return ""

            added_hashes = sorted(hash_value for hash_value in after_hashes - before_hashes if hash_value)
            if len(added_hashes) == 1:
                return added_hashes[0]
            if len(added_hashes) > 1:
                logger.warning(
                    f"qB添加任务后发现多个新增hash，无法唯一定位刷流任务：{','.join(added_hashes[:10])}"
                )
                return ""
            if retry_index < retries - 1:
                time.sleep(interval)

        return ""

    def __update_seeding_tasks_based_on_tags(self, torrent_tasks: Dict[str, dict], unmanaged_tasks: Dict[str, dict],
                                             seeding_torrents_dict: Dict[str, Any]):
        brush_config = self.__get_brush_config()

        if not self.downloader_helper.is_downloader("qbittorrent", service=self.service_info):
            logger.info("同步种子刷流标签记录目前仅支持qbittorrent")
            return

        # 初始化汇总信息
        added_tasks = []
        reset_tasks = []
        removed_tasks = []
        # 基于 seeding_torrents_dict 的信息更新或添加到 torrent_tasks
        for torrent_hash, torrent in seeding_torrents_dict.items():
            tags = self.__get_label(torrent=torrent)
            # 判断是否包含刷流标签
            if brush_config.brush_tag in tags:
                # 如果包含刷流标签又不在刷流任务中，则需要加入管理
                if torrent_hash not in torrent_tasks:
                    # 检查该种子是否在 unmanaged_tasks 中
                    if torrent_hash in unmanaged_tasks:
                        # 如果在 unmanaged_tasks 中，移除并转移到 torrent_tasks
                        torrent_task = unmanaged_tasks.pop(torrent_hash)
                        torrent_tasks[torrent_hash] = torrent_task
                        added_tasks.append(torrent_task)
                        logger.info(f"站点 {torrent_task.get('site_name')}，"
                                    f"刷流任务种子再次加入：{torrent_task.get('title')}|{torrent_task.get('description')}")
                    else:
                        # 否则，创建一个新的任务
                        torrent_task = self.__convert_torrent_info_to_task(torrent)
                        torrent_tasks[torrent_hash] = torrent_task
                        added_tasks.append(torrent_task)
                        logger.info(f"站点 {torrent_task.get('site_name')}，"
                                    f"刷流任务种子加入：{torrent_task.get('title')}|{torrent_task.get('description')}")
                # 包含刷流标签又在刷流任务中，这里额外处理一个特殊逻辑，就是种子在刷流任务中可能被标记删除但实际上又还在下载器中，这里进行重置
                else:
                    torrent_task = torrent_tasks[torrent_hash]
                    if torrent_task.get("deleted"):
                        torrent_task["deleted"] = False
                        reset_tasks.append(torrent_task)
                        logger.info(
                            f"站点 {torrent_task.get('site_name')}，在下载器中找到已标记删除的刷流任务对应的种子信息，"
                            f"更新刷流任务状态为正常：{torrent_task.get('title')}|{torrent_task.get('description')}")
            else:
                # 不包含刷流标签但又在刷流任务中，则移除管理
                if torrent_hash in torrent_tasks:
                    # 如果种子不符合刷流条件但在 torrent_tasks 中，移除并加入 unmanaged_tasks
                    torrent_task = torrent_tasks.pop(torrent_hash)
                    unmanaged_tasks[torrent_hash] = torrent_task
                    removed_tasks.append(torrent_task)
                    logger.info(f"站点 {torrent_task.get('site_name')}，"
                                f"刷流任务种子移除：{torrent_task.get('title')}|{torrent_task.get('description')}")

        self.save_data("torrents", torrent_tasks)
        self.save_data("unmanaged", unmanaged_tasks)

        # 发送汇总消息
        if added_tasks:
            self.__log_and_send_torrent_task_update_message(title="【刷流任务种子加入】", status="纳入刷流管理",
                                                            reason="刷流标签添加", torrent_tasks=added_tasks)
        if removed_tasks:
            self.__log_and_send_torrent_task_update_message(title="【刷流任务种子移除】", status="移除刷流管理",
                                                            reason="刷流标签移除", torrent_tasks=removed_tasks)
        if reset_tasks:
            self.__log_and_send_torrent_task_update_message(title="【刷流任务状态更新】", status="更新刷流状态为正常",
                                                            reason="在下载器中找到已标记删除的刷流任务对应的种子信息",
                                                            torrent_tasks=reset_tasks)

    def __group_torrents_by_proxy_delete(self, torrents: List[Any], torrent_tasks: Dict[str, dict]):
        """
        根据是否启用动态删种进行分组
        """
        proxy_delete_torrents = []
        not_proxy_delete_torrents = []

        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)

            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue

            site_name = torrent_task.get("site_name", "")

            brush_config = self.__get_brush_config(site_name)
            if brush_config.proxy_delete:
                proxy_delete_torrents.append(torrent)
            else:
                not_proxy_delete_torrents.append(torrent)

        return proxy_delete_torrents, not_proxy_delete_torrents

    @staticmethod
    def __number_or_none(value) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def __is_torrent_seeding_or_completed(self, torrent_info: dict) -> bool:
        """
        判断下载器中的任务是否已进入做种/完成状态。
        """
        seeding_time = self.__number_or_none(torrent_info.get("seeding_time")) or 0
        if seeding_time > 0:
            return True

        downloaded = self.__number_or_none(torrent_info.get("downloaded"))
        total_size = self.__number_or_none(torrent_info.get("total_size"))
        return downloaded is not None and total_size is not None and total_size > 0 and downloaded >= total_size

    def __is_yield_guard_applicable_torrent(self, torrent_info: dict) -> bool:
        """
        上传收益保护只处理正在下载的种子；已完成做种种子交给常规做种删种规则。
        """
        return not self.__is_torrent_seeding_or_completed(torrent_info=torrent_info)

    def __reset_yield_guard_runtime_state_for_skip(self, torrent_task: dict) -> None:
        if not isinstance(torrent_task, dict):
            return
        self.__clear_yield_guard_check_cache(torrent_task)
        torrent_task["yield_guard_good_protected"] = False
        torrent_task["yield_guard_promising_protected"] = False
        torrent_task["yield_guard_bad_streak"] = 0
        torrent_task["yield_guard_stage"] = "normal"
        torrent_task["yield_guard_restore_download_limit"] = False
        torrent_task["yield_guard_last_reason"] = "上传收益保护：已完成做种，跳过"

    @staticmethod
    def __yield_guard_action_value(action: Any, default_value: str) -> str:
        action = str(action or "").strip().lower()
        return action if action in {"none", "limit", "pause", "delete"} else default_value

    @staticmethod
    def __yield_guard_positive_number(value: Any, default_value: float = 0.0) -> float:
        try:
            if value in (None, ""):
                return default_value
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return default_value

    @staticmethod
    def __yield_guard_rehearsal_reason(reason: str) -> str:
        return f"上传收益保护演练模式：{reason}，不实际执行"

    def __evaluate_yield_guard_for_delete(self, site_name: str, brush_config: BrushConfig,
                                          torrent_info: dict, torrent_task: dict) -> Tuple[bool, str]:
        """
        评估上传收益保护。这里返回 True 表示应交给现有删种流程删除。
        限速/暂停动作在 check() 的动作层处理；本函数只维护状态和给出决策原因。
        """
        if not brush_config.yield_guard_enabled:
            self.__clear_yield_guard_check_cache(torrent_task)
            torrent_task["yield_guard_good_protected"] = False
            torrent_task["yield_guard_promising_protected"] = False
            return False, ""

        if not self.__is_yield_guard_applicable_torrent(torrent_info=torrent_info):
            self.__reset_yield_guard_runtime_state_for_skip(torrent_task)
            return False, ""

        interval_upspeed = self.__number_or_none(torrent_task.get("last_check_interval_upspeed"))
        if interval_upspeed is None:
            interval_upspeed = self.__number_or_none(torrent_info.get("last_check_interval_upspeed"))
        avg_upspeed = self.__number_or_none(torrent_info.get("avg_upspeed"))

        good_upload_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_good_upload_kbs) * 1024
        good_avg_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_good_avg_upload_kbs) * 1024
        good_protected = False
        if good_upload_bytes > 0 and interval_upspeed is not None and interval_upspeed >= good_upload_bytes:
            good_protected = True
        if good_avg_bytes > 0 and avg_upspeed is not None and avg_upspeed >= good_avg_bytes:
            good_protected = True
        torrent_task["yield_guard_good_protected"] = good_protected
        if good_protected:
            if torrent_task.get("yield_guard_stage") == "limited":
                torrent_task["yield_guard_stage"] = "normal"
                torrent_task["yield_guard_restore_download_limit"] = True
            torrent_task["yield_guard_bad_streak"] = 0
            torrent_task["yield_guard_last_reason"] = "上传收益保护：上传表现达标，跳过易误伤删种规则"
            return False, torrent_task["yield_guard_last_reason"]

        short_window, short_window_reason = self.__evaluate_yield_guard_short_window(
            brush_config=brush_config,
            torrent_task=torrent_task
        )
        torrent_task["yield_guard_promising_protected"] = short_window

        bad_checks = max(1, int(self.__yield_guard_positive_number(brush_config.yield_guard_bad_checks, 2)))
        bad_streak = int(self.__yield_guard_positive_number(torrent_task.get("yield_guard_bad_streak"), 0))
        stage = torrent_task.get("yield_guard_stage") or "normal"
        first_transfer_time = torrent_task.get("first_downloaded_time")
        if first_transfer_time is None:
            first_transfer_time = torrent_task.get("first_uploaded_time")
        transfer_elapsed_minutes = self.__get_task_elapsed_minutes(first_transfer_time) if first_transfer_time is not None else None
        fast_fail_minutes = self.__yield_guard_positive_number(brush_config.yield_guard_fast_fail_minutes, 10)

        if stage == "paused" and bad_streak >= bad_checks:
            if short_window:
                torrent_task["yield_guard_last_reason"] = short_window_reason or "上传收益保护：仍处于短窗保护"
                return False, torrent_task["yield_guard_last_reason"]
            if fast_fail_minutes <= 0 or (transfer_elapsed_minutes is not None and transfer_elapsed_minutes >= fast_fail_minutes):
                final_action = self.__yield_guard_action_value(brush_config.yield_guard_final_action, "delete")
                if final_action == "delete":
                    reason = f"上传收益保护：低收益，已超过快速淘汰窗口，连续 {bad_streak} 次，最终删除"
                    if brush_config.yield_guard_rehearsal:
                        reason = self.__yield_guard_rehearsal_reason(reason)
                        torrent_task["yield_guard_last_reason"] = reason
                        logger.info(f"站点：{site_name}，{reason}")
                        return False, reason
                    torrent_task["yield_guard_last_reason"] = reason
                    return True, reason
                reason = f"上传收益保护：低收益，已超过快速淘汰窗口，动作 {final_action}"
                torrent_task["yield_guard_last_reason"] = reason
                return False, reason
            torrent_task["yield_guard_last_reason"] = "上传收益保护：已暂停，但尚未超过快速淘汰窗口"
            return False, torrent_task["yield_guard_last_reason"]

        interval_downspeed = self.__number_or_none(torrent_task.get("last_check_interval_downspeed"))
        if interval_downspeed is None:
            interval_downspeed = self.__number_or_none(torrent_info.get("last_check_interval_downspeed"))
        downspeed_valid = bool(torrent_task.get("last_check_interval_downspeed_valid",
                                                torrent_info.get("last_check_interval_downspeed_valid", False)))
        upspeed_valid = bool(torrent_task.get("last_check_interval_upspeed_valid",
                                              torrent_info.get("last_check_interval_upspeed_valid", False)))
        if not (downspeed_valid and upspeed_valid):
            torrent_task["yield_guard_bad_streak"] = 0
            torrent_task["yield_guard_last_reason"] = "上传收益保护：采样未就绪"
            return False, torrent_task["yield_guard_last_reason"]

        high_download_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_high_download_kbs) * 1024
        low_upload_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_low_upload_kbs) * 1024
        is_high_download = high_download_bytes > 0 and interval_downspeed is not None and interval_downspeed >= high_download_bytes
        is_low_upload = interval_upspeed is not None and interval_upspeed <= low_upload_bytes
        low_ratio_percent = self.__yield_guard_positive_number(brush_config.yield_guard_low_ratio_percent)
        ratio_min_download_bytes = (
                self.__yield_guard_positive_number(brush_config.yield_guard_ratio_min_download_kbs) * 1024
        )
        ratio_protect_upload_bytes = (
                self.__yield_guard_positive_number(brush_config.yield_guard_ratio_protect_upload_kbs) * 1024
        )
        yield_ratio_percent = self.__calculate_yield_guard_ratio_percent(
            interval_upspeed=interval_upspeed,
            interval_downspeed=interval_downspeed
        )
        is_low_ratio = (
                low_ratio_percent > 0
                and ratio_min_download_bytes > 0
                and interval_downspeed is not None
                and interval_downspeed >= ratio_min_download_bytes
                and yield_ratio_percent is not None
                and yield_ratio_percent <= low_ratio_percent
        )
        is_ratio_upload_protected = (
                is_low_ratio
                and ratio_protect_upload_bytes > 0
                and interval_upspeed is not None
                and interval_upspeed >= ratio_protect_upload_bytes
        )
        is_limited_low_upload = (torrent_task.get("yield_guard_stage") == "limited" and is_low_upload)
        is_low_yield = (is_high_download and is_low_upload) or (is_low_ratio and not is_ratio_upload_protected) or is_limited_low_upload

        downloaded = self.__number_or_none(torrent_info.get("downloaded")) or 0
        total_size = self.__number_or_none(torrent_info.get("total_size")) or 0
        min_downloaded_bytes = self.__yield_guard_positive_number(brush_config.yield_guard_min_downloaded_gb) * 1024 ** 3
        min_progress_percent = self.__yield_guard_positive_number(brush_config.yield_guard_min_progress_percent)
        progress_percent = (downloaded / total_size * 100) if total_size > 0 else 0
        sample_checks = []
        if min_downloaded_bytes > 0:
            sample_checks.append(downloaded >= min_downloaded_bytes)
        if min_progress_percent > 0:
            sample_checks.append(progress_percent >= min_progress_percent)
        has_enough_sample = any(sample_checks) if sample_checks else True

        if not (is_low_yield and has_enough_sample):
            torrent_task["yield_guard_bad_streak"] = 0
            if torrent_task.get("yield_guard_stage") == "limited":
                torrent_task["yield_guard_stage"] = "normal"
                torrent_task["yield_guard_restore_download_limit"] = True
            if is_ratio_upload_protected:
                torrent_task["yield_guard_last_reason"] = (
                    f"上传收益保护：收益比偏低但检查间上传 {interval_upspeed / 1024:.1f} KB/s "
                    f"达到收益比保护上传阈值 {brush_config.yield_guard_ratio_protect_upload_kbs} KB/s，继续观察"
                )
            else:
                torrent_task["yield_guard_last_reason"] = "上传收益保护：未命中低收益条件"
            return False, torrent_task["yield_guard_last_reason"]

        bad_streak = int(self.__yield_guard_positive_number(torrent_task.get("yield_guard_bad_streak"), 0)) + 1
        torrent_task["yield_guard_bad_streak"] = bad_streak
        records = torrent_task.get("yield_guard_bad_records")
        if not isinstance(records, list):
            records = []
        records.append(1)
        torrent_task["yield_guard_bad_records"] = records[-20:]

        if bad_streak < bad_checks:
            reason = f"上传收益保护：低收益命中 {bad_streak}/{bad_checks} 次，继续观察"
            torrent_task["yield_guard_last_reason"] = reason
            return False, reason

        in_short_window = short_window

        stage = torrent_task.get("yield_guard_stage") or "normal"
        if stage == "normal":
            action = self.__yield_guard_action_value(brush_config.yield_guard_first_action, "limit")
        elif stage == "limited":
            action = self.__yield_guard_action_value(brush_config.yield_guard_second_action, "pause")
        else:
            action = self.__yield_guard_action_value(brush_config.yield_guard_final_action, "delete")

        if in_short_window and action == "delete":
            action = "pause"

        reason = (f"上传收益保护：低收益，下载 {interval_downspeed / 1024:.1f} KB/s，"
                  f"上传 {interval_upspeed / 1024:.1f} KB/s，连续 {bad_streak} 次，动作 {action}")
        torrent_task["yield_guard_last_reason"] = reason

        if action == "limit":
            torrent_task["yield_guard_stage"] = "limited"
            return False, reason
        if action == "pause":
            torrent_task["yield_guard_stage"] = "paused"
            torrent_task["yield_guard_paused_time"] = time.time()
            return False, reason
        if action == "delete":
            if brush_config.yield_guard_rehearsal:
                reason = self.__yield_guard_rehearsal_reason(reason)
                torrent_task["yield_guard_last_reason"] = reason
                logger.info(f"站点：{site_name}，{reason}")
                return False, reason
            return True, reason
        return False, reason

    def __evaluate_yield_guard_short_window(self, brush_config: BrushConfig, torrent_task: dict) -> Tuple[bool, str]:
        """
        判断当前是否仍处于上传收益保护短窗期。
        """
        promising_pub_minutes = int(self.__yield_guard_positive_number(
            brush_config.yield_guard_promising_pubtime_minutes, 15
        ))
        pubdate = torrent_task.get("pubdate")
        if promising_pub_minutes > 0 and pubdate:
            pubdate_minutes = self.__get_pubminutes(str(pubdate))
            if 0 < pubdate_minutes <= promising_pub_minutes:
                return True, f"上传收益保护：发布时间 {pubdate_minutes:.0f} 分钟内，仍处于短窗保护"

        fast_fail_minutes = self.__yield_guard_positive_number(brush_config.yield_guard_fast_fail_minutes, 10)
        first_transfer_time = torrent_task.get("first_downloaded_time")
        if first_transfer_time is None:
            first_transfer_time = torrent_task.get("first_uploaded_time")
        transfer_elapsed_minutes = self.__get_task_elapsed_minutes(first_transfer_time) if first_transfer_time is not None else None
        if fast_fail_minutes > 0 and transfer_elapsed_minutes is not None and transfer_elapsed_minutes < fast_fail_minutes:
            return True, f"上传收益保护：首次实际传输 {transfer_elapsed_minutes:.0f} 分钟内，仍处于短窗保护"

        return False, ""

    def __evaluate_conditions_for_delete(self, site_name: str, torrent_info: dict, torrent_task: dict,
                                          downloading_count: int = 0) \
            -> Tuple[bool, str]:
        """
        评估删除条件并返回是否应删除种子及其原因
        """
        brush_config = self.__get_brush_config(sitename=site_name)
        seeding_time = torrent_info.get("seeding_time")
        ratio = torrent_info.get("ratio")

        if (not brush_config.filter_seeding_torrents
                and self.__is_torrent_seeding_or_completed(torrent_info=torrent_info)):
            seeding_seconds = self.__number_or_none(seeding_time)
            if (brush_config.seed_time and seeding_seconds is not None
                    and seeding_seconds >= float(brush_config.seed_time) * 3600):
                return True, f"做种时间 {seeding_seconds / 3600:.1f} 小时，大于 {brush_config.seed_time} 小时"
            return False, "已做种种子仅按做种时间筛选，跳过其它删种规则"

        # 规则：检测到种子已失去免费后，直接彻底删除
        no_free_should_delete, no_free_reason = self.__evaluate_no_free_condition_for_delete(
            site_name=site_name,
            torrent_task=torrent_task
        )
        if no_free_should_delete:
            return True, no_free_reason
        if no_free_reason and no_free_reason.startswith("失去免费删种检测跳过"):
            logger.debug(f"站点：{site_name}，{no_free_reason}")

        if brush_config.yield_guard_enabled and torrent_task.get("yield_guard_evaluated_in_check"):
            yield_guard_should_delete = bool(torrent_task.get("yield_guard_should_delete"))
            yield_guard_reason = torrent_task.get("yield_guard_last_reason", "")
        else:
            yield_guard_should_delete, yield_guard_reason = self.__evaluate_yield_guard_for_delete(
                site_name=site_name,
                brush_config=brush_config,
                torrent_info=torrent_info,
                torrent_task=torrent_task
            )
        if yield_guard_should_delete:
            return True, yield_guard_reason
        yield_guard_good_protected = (
                brush_config.yield_guard_enabled
                and brush_config.yield_guard_protect_delete_rules
                and bool(torrent_task.get("yield_guard_good_protected"))
        )

        task_elapsed_minutes = self.__get_task_elapsed_minutes(torrent_task.get("time"))
        ratio_check_minutes = brush_config.seed_ratio_check_minutes if brush_config.seed_ratio_check_minutes else 30
        # 基于首次有下载数据的时间计算已过分钟数（无下载数据时返回 0，规则不触发）
        first_downloaded_time = torrent_task.get("first_downloaded_time")
        downloaded_elapsed_minutes = self.__get_task_elapsed_minutes(first_downloaded_time) if first_downloaded_time else 0
        # 基于首次有上传数据的时间计算已过分钟数（无上传数据时返回 0，规则不触发）
        first_uploaded_time = torrent_task.get("first_uploaded_time")
        uploaded_elapsed_minutes = self.__get_task_elapsed_minutes(first_uploaded_time) if first_uploaded_time else 0
        # 下载保护：使用 check() 中从下载器实时数据统计的下载中种子数
        if brush_config.skip_rules_downloading_threshold > 0:
            download_protection_active = downloading_count <= brush_config.skip_rules_downloading_threshold
        else:
            download_protection_active = False
        if download_protection_active:
            logger.info(
                f"下载中种子数 {downloading_count} ≤ 阈值 {brush_config.skip_rules_downloading_threshold}，"
                f"最低分享率/检查间上传速度规则已跳过（站点：{site_name}）"
            )
        # 分享率速度保护：avg_upspeed 达标时豁免最低分享率规则
        speed_protection_active = False
        if (brush_config.seed_ratio_speed_protect and brush_config.seed_ratio_speed_protect > 0
                and torrent_info.get("avg_upspeed") is not None):
            avg_upspeed_kb = float(torrent_info.get("avg_upspeed")) / 1024
            if avg_upspeed_kb >= float(brush_config.seed_ratio_speed_protect):
                speed_protection_active = True
        interval_should_delete, interval_reason = self.__evaluate_interval_upspeed_condition_for_delete(
            site_name=site_name,
            brush_config=brush_config,
            torrent_task=torrent_task,
            task_elapsed_minutes=uploaded_elapsed_minutes if not download_protection_active else 0
        )
        if download_protection_active:
            interval_should_delete = False
            interval_reason = "下载保护已跳过检查间上传速度规则"

        reason = "未能满足设置的删除条件"

        # 当配置了H&R做种时间/分享率时，则H&R种子只有达到预期行为时，才会进行删除，如果没有配置H&R做种时间/分享率，则普通种子的删除规则也适用于H&R种子
        # 判断是否为H&R种子并且是否配置了特定的H&R条件
        hit_and_run = torrent_task.get("hit_and_run", False)
        hr_specific_conditions_configured = hit_and_run and (
                brush_config.hr_seed_time or brush_config.seed_ratio or brush_config.seed_ratio_min_30m
        )
        if hr_specific_conditions_configured:
            if (brush_config.hr_seed_time and seeding_time
                    >= float(brush_config.hr_seed_time) * 3600):
                return True, (f"H&R种子，做种时间 {seeding_time / 3600:.1f} 小时，"
                              f"大于 {brush_config.hr_seed_time} 小时")
            if brush_config.seed_ratio and ratio is not None and ratio >= float(brush_config.seed_ratio):
                return True, f"H&R种子，分享率 {ratio:.2f}，大于 {brush_config.seed_ratio}"
            if (brush_config.seed_ratio_min_30m and not download_protection_active
                    and not yield_guard_good_protected
                    and not speed_protection_active
                    and downloaded_elapsed_minutes is not None
                    and downloaded_elapsed_minutes >= float(ratio_check_minutes)
                    and ratio is not None and ratio < float(brush_config.seed_ratio_min_30m)):
                return True, (f"H&R种子，有下载数据 {downloaded_elapsed_minutes:.0f} 分钟后分享率 {ratio:.2f}，"
                              f"低于 {brush_config.seed_ratio_min_30m}")
            return False, "H&R种子，未能满足设置的H&R删除条件"

        # 处理其他场景，1. 不是H&R种子；2. 是H&R种子但没有特定条件配置
        reason = reason if not hit_and_run else "H&R种子（未设置H&R条件），未能满足设置的删除条件"
        if brush_config.seed_time and seeding_time and seeding_time >= float(brush_config.seed_time) * 3600:
            reason = f"做种时间 {seeding_time / 3600:.1f} 小时，大于 {brush_config.seed_time} 小时"
        elif brush_config.seed_ratio and ratio is not None and ratio >= float(brush_config.seed_ratio):
            reason = f"分享率 {ratio:.2f}，大于 {brush_config.seed_ratio}"
        elif (brush_config.seed_ratio_min_30m and not download_protection_active
              and not yield_guard_good_protected
              and not speed_protection_active
              and downloaded_elapsed_minutes is not None
              and downloaded_elapsed_minutes >= float(ratio_check_minutes)
              and ratio is not None and ratio < float(brush_config.seed_ratio_min_30m)):
            reason = (f"有下载数据 {downloaded_elapsed_minutes:.0f} 分钟后分享率 {ratio:.2f}，"
                      f"低于 {brush_config.seed_ratio_min_30m}")
        elif brush_config.seed_size and torrent_info.get("uploaded") >= float(brush_config.seed_size) * 1024 ** 3:
            reason = f"上传量 {torrent_info.get('uploaded') / 1024 ** 3:.1f} GB，大于 {brush_config.seed_size} GB"
        elif brush_config.download_time and torrent_info.get("downloaded") < torrent_info.get(
                "total_size") and torrent_info.get("dltime") >= float(brush_config.download_time) * 3600:
            reason = f"下载耗时 {torrent_info.get('dltime') / 3600:.1f} 小时，大于 {brush_config.download_time} 小时"
        elif (brush_config.seed_avgspeed and not yield_guard_good_protected
              and torrent_info.get("avg_upspeed") <= float(brush_config.seed_avgspeed) * 1024
              and torrent_info.get("seeding_time") >= 30 * 60):
            reason = f"平均上传速度 {torrent_info.get('avg_upspeed') / 1024:.1f} KB/s，低于 {brush_config.seed_avgspeed} KB/s"
        elif interval_should_delete and not yield_guard_good_protected:
            reason = interval_reason
        elif brush_config.seed_inactivetime and torrent_info.get("iatime") >= float(
                brush_config.seed_inactivetime) * 60:
            reason = f"未活动时间 {torrent_info.get('iatime') / 60:.0f} 分钟，大于 {brush_config.seed_inactivetime} 分钟"
        else:
            if yield_guard_good_protected:
                return False, torrent_task.get("yield_guard_last_reason") or "上传收益保护已跳过易误伤删种规则"
            if yield_guard_reason:
                return False, yield_guard_reason
            return False, interval_reason if interval_reason else reason

        return True, reason if not hit_and_run else "H&R种子（未设置H&R条件），" + reason

    def __evaluate_no_free_condition_for_delete(self, site_name: str, torrent_task: dict) -> Tuple[bool, str]:
        """
        评估“失去免费即删种”规则
        """
        brush_config = self.__get_brush_config(sitename=site_name)
        if not brush_config.delete_when_no_free:
            return False, ""

        # 仅对原本免费加入的任务生效
        if not self.__is_free_torrent(torrent_task):
            return False, ""

        is_still_free, free_reason, free_remaining_minutes = self.__check_torrent_current_free_status(
            torrent_task=torrent_task
        )
        if is_still_free is False:
            return True, "检测到种子已不免费，按配置执行彻底删除"
        if is_still_free is None:
            return False, f"失去免费删种检测跳过，原因：{free_reason}"

        threshold_minutes = self.__get_delete_free_remaining_threshold(brush_config=brush_config)
        if free_remaining_minutes is None:
            return False, "仍为免费种子"
        if free_remaining_minutes < threshold_minutes:
            return True, (f"免费剩余时间 {free_remaining_minutes:.0f} 分钟，不足 "
                          f"{threshold_minutes:.0f} 分钟，按配置执行彻底删除")
        return False, (f"仍为免费种子，免费剩余时间 {free_remaining_minutes:.0f} 分钟，"
                       f"不低于 {threshold_minutes:.0f} 分钟")

    def __delete_torrent_for_no_free(self, torrents: List[Any], torrent_tasks: Dict[str, dict],
                                     delete_message_map: Optional[Dict[str, List[dict]]] = None) -> List:
        """
        根据“失去免费即删种”规则删除种子并获取已删除列表
        """
        delete_hashes = []

        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)
            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue

            site_name = torrent_task.get("site_name", "")
            torrent_title = torrent_task.get("title", "")
            torrent_desc = torrent_task.get("description", "")
            should_delete, reason = self.__evaluate_no_free_condition_for_delete(site_name=site_name,
                                                                                  torrent_task=torrent_task)
            if should_delete:
                delete_hashes.append(torrent_hash)
                self.__append_delete_message(delete_message_map=delete_message_map, torrent_hash=torrent_hash,
                                             site_name=site_name, torrent_title=torrent_title,
                                             torrent_desc=torrent_desc, reason=reason)
                logger.info(f"站点：{site_name}，{reason}，命中删除条件：{torrent_title}|{torrent_desc}")
            elif reason and reason.startswith("失去免费删种检测跳过"):
                logger.debug(f"站点：{site_name}，{reason}，不删除种子：{torrent_title}|{torrent_desc}")

        return delete_hashes

    def __delete_torrent_for_yield_guard(self, torrents: List[Any], torrent_tasks: Dict[str, dict],
                                         delete_message_map: Optional[Dict[str, List[dict]]] = None) -> List:
        """
        根据上传收益保护已缓存的删除决策获取待删列表，不受动态删种体积阈值影响。
        """
        delete_hashes = []

        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)
            if not torrent_task:
                continue

            site_name = torrent_task.get("site_name", "")
            brush_config = self.__get_brush_config(sitename=site_name)
            if not brush_config.yield_guard_enabled:
                continue
            if not torrent_task.get("yield_guard_evaluated_in_check"):
                continue
            if not torrent_task.get("yield_guard_should_delete"):
                continue

            torrent_title = torrent_task.get("title", "")
            torrent_desc = torrent_task.get("description", "")
            reason = torrent_task.get("yield_guard_last_reason") or "上传收益保护：低收益，最终删除"
            delete_hashes.append(torrent_hash)
            self.__append_delete_message(delete_message_map=delete_message_map, torrent_hash=torrent_hash,
                                         site_name=site_name, torrent_title=torrent_title,
                                         torrent_desc=torrent_desc, reason=reason)
            logger.info(f"站点：{site_name}，{reason}，命中删除条件：{torrent_title}|{torrent_desc}")

        return delete_hashes

    def __evaluate_interval_upspeed_condition_for_delete(self, site_name: str, brush_config: BrushConfig,
                                                         torrent_task: dict, task_elapsed_minutes: Optional[float]) \
            -> Tuple[bool, str]:
        """
        评估检查间上传速度删除条件
        """
        if brush_config.interval_upspeed in (None, ""):
            return False, ""

        try:
            threshold_kb = float(brush_config.interval_upspeed)
        except (TypeError, ValueError):
            return False, "检查间上传速度阈值配置无效，已跳过低速统计"

        if threshold_kb < 0:
            return False, "检查间上传速度阈值不能小于0，已跳过低速统计"

        def _to_positive_int(value: Any, default_value: int) -> int:
            try:
                if value in (None, ""):
                    return default_value
                return max(1, int(float(value)))
            except (TypeError, ValueError):
                return default_value

        check_count = _to_positive_int(brush_config.interval_upspeed_check_count, 3)
        low_count = _to_positive_int(brush_config.interval_upspeed_low_count, 2)
        low_count = min(low_count, check_count)
        require_continuous = bool(brush_config.interval_upspeed_continuous)
        rehearsal_mode = bool(brush_config.interval_upspeed_rehearsal)

        try:
            start_minutes = float(brush_config.interval_upspeed_start_minutes) \
                if brush_config.interval_upspeed_start_minutes not in (None, "") else 30.0
        except (TypeError, ValueError):
            start_minutes = 30.0
        start_minutes = max(0.0, start_minutes)

        if task_elapsed_minutes is None:
            return False, "检查间上传速度：有上传数据时间无效，已跳过低速统计"

        if task_elapsed_minutes < start_minutes:
            return False, (f"检查间上传速度：有上传数据 {task_elapsed_minutes:.0f} 分钟，"
                           f"未到统计起始 {start_minutes:.0f} 分钟")

        interval_valid = bool(torrent_task.get("last_check_interval_upspeed_valid"))
        if not interval_valid:
            reason = torrent_task.get("last_check_interval_reason") or "采样尚未就绪"
            return False, f"检查间上传速度：{reason}"

        interval_speed = torrent_task.get("last_check_interval_upspeed")
        if not isinstance(interval_speed, (int, float)):
            return False, "检查间上传速度：采样异常，已跳过低速统计"

        threshold_bytes = threshold_kb * 1024
        is_low_speed = interval_speed <= threshold_bytes

        records = torrent_task.get("interval_upspeed_hit_records")
        if not isinstance(records, list):
            records = []
        records = [1 if bool(record) else 0 for record in records if isinstance(record, (int, float, bool))]
        records.append(1 if is_low_speed else 0)
        max_keep = max(check_count, low_count, 20)
        if len(records) > max_keep:
            records = records[-max_keep:]
        torrent_task["interval_upspeed_hit_records"] = records

        recent_records = records[-check_count:]
        hit_count = int(sum(recent_records))
        consecutive_hit_count = 0
        for record in reversed(recent_records):
            if record == 1:
                consecutive_hit_count += 1
            else:
                break

        if require_continuous:
            required_samples = min(low_count, check_count)
            if len(recent_records) < required_samples:
                return False, (f"检查间上传速度：连续低速命中 {consecutive_hit_count}/{required_samples} 次，"
                               f"等待收集足够检查样本后再判定")

            if consecutive_hit_count >= low_count:
                reason = (f"检查间上传速度 {interval_speed / 1024:.1f} KB/s，低于阈值 {threshold_kb:.1f} KB/s；"
                          f"最近连续命中 {consecutive_hit_count} 次（阈值 {low_count} 次）")
                if rehearsal_mode:
                    return False, f"演练模式命中删除条件，{reason}"
                return True, reason

            return False, (f"检查间上传速度 {interval_speed / 1024:.1f} KB/s；"
                           f"最近连续命中 {consecutive_hit_count} 次，未达到删除阈值 {low_count} 次")

        if len(recent_records) < check_count:
            return False, (f"检查间上传速度：低速命中 {hit_count}/{len(recent_records)} 次，"
                           f"等待收集满 {check_count} 次检查后再判定")

        if hit_count >= low_count:
            reason = (f"检查间上传速度 {interval_speed / 1024:.1f} KB/s，低于阈值 {threshold_kb:.1f} KB/s；"
                      f"最近 {check_count} 次命中 {hit_count} 次（阈值 {low_count} 次）")
            if rehearsal_mode:
                return False, f"演练模式命中删除条件，{reason}"
            return True, reason

        return False, (f"检查间上传速度 {interval_speed / 1024:.1f} KB/s；最近 {check_count} 次命中 {hit_count} 次，"
                       f"未达到删除阈值 {low_count} 次")

    def __evaluate_proxy_pre_conditions_for_delete(self, site_name: str, torrent_info: dict) -> Tuple[bool, str]:
        """
        评估动态删除前置条件并返回是否应删除种子及其原因
        """
        brush_config = self.__get_brush_config(sitename=site_name)

        reason = "未能满足动态删除设置的前置删除条件"

        if brush_config.download_time and torrent_info.get("downloaded") < torrent_info.get(
                "total_size") and torrent_info.get("dltime") >= float(brush_config.download_time) * 3600:
            reason = f"下载耗时 {torrent_info.get('dltime') / 3600:.1f} 小时，大于 {brush_config.download_time} 小时"
        else:
            return False, reason

        return True, reason

    def __check_torrent_current_free_status(self, torrent_task: dict) -> Tuple[Optional[bool], str, Optional[float]]:
        """
        检查种子当前是否仍为免费状态
        """
        page_text, error_reason = self.__get_torrent_detail_page_text(
            site_id=torrent_task.get("site"),
            page_url=torrent_task.get("page_url")
        )
        if not page_text:
            return None, error_reason, None

        page_free_status = self.__parse_free_status_from_page(page_text)
        if page_free_status is None:
            return None, "页面内容无法判断免费状态", None

        if not page_free_status:
            return False, "已失去免费", 0

        free_remaining_minutes = self.__get_free_remaining_minutes(
            freedate=torrent_task.get("freedate"),
            freedate_diff=torrent_task.get("freedate_diff"),
            title=torrent_task.get("title"),
            description=page_text
        )
        return True, "仍为免费种子", free_remaining_minutes

    def __get_torrent_detail_page_text(self, site_id: Any, page_url: str) -> Tuple[Optional[str], str]:
        """
        获取种子详情页HTML
        """
        if not site_id or not page_url:
            return None, "缺少站点ID或种子详情地址"

        site_info = self.site_oper.get(site_id)
        if not site_info:
            return None, f"未找到站点配置（ID: {site_id}）"

        base_url = getattr(site_info, "url", None)
        if not base_url:
            return None, "站点地址为空"

        detail_url = str(page_url).strip()
        if not detail_url.startswith("http"):
            detail_url = f"{str(base_url).rstrip('/')}/{detail_url.lstrip('/')}"

        try:
            response = RequestUtils(
                ua=getattr(site_info, "ua", None),
                cookies=getattr(site_info, "cookie", None),
                proxies=settings.PROXY if bool(getattr(site_info, "proxy", False)) else None
            ).get_res(url=detail_url)
        except Exception as e:
            return None, f"请求详情页异常：{str(e)}"

        if not response or not getattr(response, "ok", False):
            return None, "请求详情页失败"

        page_text = response.text if getattr(response, "text", None) else ""
        if not page_text:
            return None, "详情页内容为空"

        return page_text, ""

    @staticmethod
    def __parse_free_status_from_page(page_text: str) -> Optional[bool]:
        """
        从种子详情页中解析免费状态
        """
        if not page_text:
            return None

        text = html.unescape(page_text)
        text_lower = text.lower()

        # 遇到登录页、验证页等非详情页场景时跳过判断，避免误删
        challenge_keywords = [
            "login.php", "name=\"username\"", "name='username'",
            "cloudflare", "cf-browser-verification", "turnstile", "captcha", "验证"
        ]
        if any(keyword in text_lower for keyword in challenge_keywords):
            return None

        # 基础详情页特征，不满足则不做免费状态判断
        detail_patterns = [
            r"download\.php\?id=",
            r"<h1[^>]*id=[\"']top[\"']",
            r"rowhead[^>]*>\s*下载"
        ]
        if not any(re.search(pattern, text, re.IGNORECASE) for pattern in detail_patterns):
            return None

        free_patterns = [
            r"class\s*=\s*[\"']pro_free[\"']",
            r"class\s*=\s*[\"']free[\"']",
            r"优惠剩余时间",
            r"免费剩余时间",
            r">\s*免费\s*<",
            r"2x\s*免费",
            r"2xfree"
        ]
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in free_patterns):
            return True

        return False

    def __delete_torrent_for_evaluate_conditions(self, torrents: List[Any], torrent_tasks: Dict[str, dict],
                                                 proxy_delete: bool = False,
                                                 delete_message_map: Optional[Dict[str, List[dict]]] = None,
                                                 downloading_count: int = 0) -> List:
        """
        根据条件删除种子并获取已删除列表
        """
        delete_hashes = []

        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)
            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue
            site_name = torrent_task.get("site_name", "")
            torrent_title = torrent_task.get("title", "")
            torrent_desc = torrent_task.get("description", "")

            torrent_info = self.__get_torrent_info(torrent)

            # 删除种子的具体实现可能会根据实际情况略有不同
            should_delete, reason = self.__evaluate_conditions_for_delete(site_name=site_name,
                                                                          torrent_info=torrent_info,
                                                                          torrent_task=torrent_task,
                                                                          downloading_count=downloading_count)
            if should_delete:
                delete_hashes.append(torrent_hash)
                reason = "触发动态删除阈值，" + reason if proxy_delete else reason
                self.__append_delete_message(delete_message_map=delete_message_map, torrent_hash=torrent_hash,
                                             site_name=site_name, torrent_title=torrent_title,
                                             torrent_desc=torrent_desc, reason=reason)
                logger.info(f"站点：{site_name}，{reason}，命中删除条件：{torrent_title}|{torrent_desc}")
            else:
                if reason and reason.startswith("演练模式命中删除条件"):
                    self.__send_delete_message(site_name=site_name, torrent_title=torrent_title,
                                               torrent_desc=torrent_desc, reason=reason,
                                               title="【刷流任务删种演练】")
                    logger.info(f"站点：{site_name}，{reason}，演练模式不删除种子：{torrent_title}|{torrent_desc}")
                else:
                    logger.debug(f"站点：{site_name}，{reason}，不删除种子：{torrent_title}|{torrent_desc}")

        return delete_hashes

    def __delete_torrent_for_evaluate_proxy_pre_conditions(self, torrents: List[Any],
                                                           torrent_tasks: Dict[str, dict],
                                                           delete_message_map: Optional[Dict[str, List[dict]]] = None) -> List:
        """
        根据动态删除前置条件排除H&R种子后删除种子并获取已删除列表
        """
        delete_hashes = []

        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            torrent_task = torrent_tasks.get(torrent_hash, None)
            # 如果找不到种子任务，说明不在管理的种子范围内，直接跳过
            if not torrent_task:
                continue

            # 如果是H&R种子，前置条件中不进行处理
            if torrent_task.get('hit_and_run', False):
                continue

            site_name = torrent_task.get("site_name", "")
            torrent_title = torrent_task.get("title", "")
            torrent_desc = torrent_task.get("description", "")

            torrent_info = self.__get_torrent_info(torrent)

            # 删除种子的具体实现可能会根据实际情况略有不同
            should_delete, reason = self.__evaluate_proxy_pre_conditions_for_delete(site_name=site_name,
                                                                                    torrent_info=torrent_info)
            if should_delete:
                delete_hashes.append(torrent_hash)
                self.__append_delete_message(delete_message_map=delete_message_map, torrent_hash=torrent_hash,
                                             site_name=site_name, torrent_title=torrent_title,
                                             torrent_desc=torrent_desc, reason=reason)
                logger.info(f"站点：{site_name}，{reason}，命中删除条件：{torrent_title}|{torrent_desc}")
            else:
                logger.debug(f"站点：{site_name}，{reason}，不删除种子：{torrent_title}|{torrent_desc}")

        return delete_hashes

    def __delete_torrent_for_proxy(self, torrents: List[Any], torrent_tasks: Dict[str, dict],
                                   delete_message_map: Optional[Dict[str, List[dict]]] = None,
                                   delete_summary_messages: Optional[List[dict]] = None,
                                   downloading_count: int = 0) -> List:
        """
        动态删除种子，删除规则如下；
        - 不管做种体积是否超过设定的动态删除阈值，默认优先执行排除H&R种子后满足「下载超时时间」的种子
        - 上述规则执行完成后，当做种体积依旧超过设定的动态删除阈值时，继续执行下述种子删除规则
        - 优先删除满足用户设置删除规则的全部种子，即便在删除过程中已经低于了阈值下限，也会继续删除
        - 若删除后还没有达到阈值，则在已完成种子中排除H&R种子后按做种时间倒序进行删除
        - 动态删除阈值：100，当做种体积 > 100G 时，则开始删除种子，直至降低至 100G
        - 动态删除阈值：50-100，当做种体积 > 100G 时，则开始删除种子，直至降至为 50G
        """
        brush_config = self.__get_brush_config()

        # 如果没有启用动态删除或没有设置删除阈值，则不执行删除操作
        if not (brush_config.proxy_delete and brush_config.delete_size_range):
            return []

        # 获取种子信息Map
        torrent_info_map = {self.__get_hash(torrent): self.__get_torrent_info(torrent=torrent) for torrent in torrents}

        # 计算当前总做种体积
        total_torrent_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)

        logger.info(
            f"当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB，正在准备计算满足动态前置删除条件的种子")

        # 执行排除H&R种子后满足前置删除条件的种子
        pre_delete_hashes = self.__delete_torrent_for_evaluate_proxy_pre_conditions(torrents=torrents,
                                                                                    torrent_tasks=torrent_tasks,
                                                                                    delete_message_map=delete_message_map) or []

        # 如果存在前置删除种子，这里进行额外判断，总做种体积排除前置删除种子的体积
        if pre_delete_hashes:
            pre_delete_total_size = sum(torrent_info_map[self.__get_hash(torrent)].get("total_size", 0)
                                        for torrent in torrents if self.__get_hash(torrent) in pre_delete_hashes)
            total_torrent_size = total_torrent_size - pre_delete_total_size
            torrents = [torrent for torrent in torrents if self.__get_hash(torrent) not in pre_delete_hashes]
            logger.info(
                f"满足动态删除前置条件的种子共 {len(pre_delete_hashes)} 个，体积 {self.__bytes_to_gb(pre_delete_total_size):.1f} GB，"
                f"删除种子后，当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB")
        else:
            logger.info(f"没有找到任何满足动态删除前置条件的种子")

        # 解析删除阈值范围
        sizes = [float(size) * 1024 ** 3 for size in brush_config.delete_size_range.split("-")]
        min_size = sizes[0]  # 至少需要达到的做种体积
        max_size = sizes[1] if len(sizes) > 1 else sizes[0]  # 触发删除操作的做种体积上限

        # 判断是否为区间删除
        proxy_size_range = len(sizes) > 1

        # 当总体积未超过最大阈值时，不需要执行删除操作
        if total_torrent_size < max_size:
            logger.info(
                f"当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB，上限 {self.__bytes_to_gb(max_size):.1f} GB，"
                f"下限 {self.__bytes_to_gb(min_size):.1f} GB，未进一步触发动态删除")
            return pre_delete_hashes or []
        else:
            logger.info(
                f"当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB，上限 {self.__bytes_to_gb(max_size):.1f} GB，"
                f"下限 {self.__bytes_to_gb(min_size):.1f} GB，进一步触发动态删除")

        need_delete_hashes = []
        need_delete_hashes.extend(pre_delete_hashes)

        # 即使开了动态删除，但是也有可能部分站点单独设置了关闭，这里根据种子托管进行分组，先处理不需要托管的种子，按设置的规则进行删除
        proxy_delete_torrents, not_proxy_delete_torrents = self.__group_torrents_by_proxy_delete(torrents=torrents,
                                                                                                 torrent_tasks=torrent_tasks)
        logger.info(f"托管种子数 {len(proxy_delete_torrents)}，未托管种子数 {len(not_proxy_delete_torrents)}")
        if not_proxy_delete_torrents:
            not_proxy_delete_hashes = self.__delete_torrent_for_evaluate_conditions(torrents=not_proxy_delete_torrents,
                                                                                    torrent_tasks=torrent_tasks,
                                                                                    delete_message_map=delete_message_map,
                                                                                    downloading_count=downloading_count) or []
            need_delete_hashes.extend(not_proxy_delete_hashes)
            total_torrent_size -= sum(
                torrent_info_map[self.__get_hash(torrent)].get("total_size", 0) for torrent in not_proxy_delete_torrents
                if self.__get_hash(torrent) in not_proxy_delete_hashes)

        # 如果删除非托管种子后仍未达到最小体积要求，则处理托管种子
        if total_torrent_size > min_size and proxy_delete_torrents:
            proxy_delete_hashes = self.__delete_torrent_for_evaluate_conditions(torrents=proxy_delete_torrents,
                                                                                torrent_tasks=torrent_tasks,
                                                                                proxy_delete=True,
                                                                                delete_message_map=delete_message_map,
                                                                                downloading_count=downloading_count) or []
            need_delete_hashes.extend(proxy_delete_hashes)
            total_torrent_size -= sum(
                torrent_info_map[self.__get_hash(torrent)].get("total_size", 0) for torrent in proxy_delete_torrents if
                self.__get_hash(torrent) in proxy_delete_hashes)

        # 在完成初始删除步骤后，如果总体积仍然超过最小阈值，则进一步找到已完成种子并排除HR种子后按做种时间正序进行删除
        if total_torrent_size > min_size:
            # 重新计算当前的种子列表，排除已删除的种子
            remaining_hashes = list(
                {self.__get_hash(torrent) for torrent in proxy_delete_torrents} - set(need_delete_hashes))
            # 这里根据排除后的种子列表，再次从下载器中找到已完成的任务
            downloader = self.downloader
            completed_torrents = downloader.get_completed_torrents(ids=remaining_hashes)
            remaining_hashes = {self.__get_hash(torrent) for torrent in completed_torrents}
            remaining_torrents = [(_hash, torrent_info_map[_hash]) for _hash in remaining_hashes]

            # 准备一个列表，用于存放满足条件的种子，即非HR种子且有明确做种时间
            filtered_torrents = [(_hash, info['seeding_time']) for _hash, info in remaining_torrents if
                                 not torrent_tasks[_hash].get("hit_and_run", False)]
            sorted_torrents = sorted(filtered_torrents, key=lambda x: x[1], reverse=True)

            # 进行额外的删除操作，直到满足最小阈值或没有更多种子可删除
            for torrent_hash, _ in sorted_torrents:
                if total_torrent_size <= min_size:
                    break
                torrent_task = torrent_tasks.get(torrent_hash, None)
                torrent_info = torrent_info_map.get(torrent_hash, None)
                if not torrent_task or not torrent_info:
                    continue
                site_name = torrent_task.get("site_name", "")
                site_brush_config = self.__get_brush_config(sitename=site_name)
                if (site_brush_config.yield_guard_enabled
                        and site_brush_config.yield_guard_protect_delete_rules
                        and torrent_task.get("yield_guard_good_protected")):
                    logger.debug(
                        f"站点：{site_name}，上传收益保护：高上传任务跳过动态删除兜底，"
                        f"不删除种子：{torrent_task.get('title', '')}|{torrent_task.get('description', '')}"
                    )
                    continue

                need_delete_hashes.append(torrent_hash)
                total_torrent_size -= torrent_info.get("total_size", 0)

                torrent_title = torrent_task.get("title", "")
                torrent_desc = torrent_task.get("description", "")
                seeding_time = torrent_task.get("seeding_time", 0)
                if seeding_time:
                    reason = (f"触发动态删除阈值，系统自动删除，做种时间 {seeding_time / 3600:.1f} 小时，"
                              f"当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB")
                    self.__append_delete_message(delete_message_map=delete_message_map, torrent_hash=torrent_hash,
                                                 site_name=site_name, torrent_title=torrent_title,
                                                 torrent_desc=torrent_desc, reason=reason)
                    logger.info(f"站点：{site_name}，{reason}，命中删除条件：{torrent_title}|{torrent_desc}")

        need_delete_hashes = list(dict.fromkeys([hash_value for hash_value in need_delete_hashes if hash_value]))

        delete_sites = {torrent_tasks[hash_key].get('site_name', '') for hash_key in need_delete_hashes if
                        hash_key in torrent_tasks}
        msg = (f"站点：{'，'.join(delete_sites)}\n内容：已命中 {len(need_delete_hashes)} 个待删种子，"
               f"当前做种体积 {self.__bytes_to_gb(total_torrent_size):.1f} GB\n原因：触发动态删除阈值，等待下载器执行删除")
        logger.info(msg)

        # 如果是区间删除，这里记录统一推送，待删种成功后再发送
        if proxy_size_range:
            if delete_summary_messages is not None:
                delete_summary_messages.append({
                    "title": "【刷流任务种子删除】",
                    "text": msg,
                    "hashes": list(dict.fromkeys(need_delete_hashes))
                })
            else:
                self.__send_message(title="【刷流任务种子删除】", text=msg)

        # 返回所有需要删除的种子的哈希列表
        return need_delete_hashes

    @staticmethod
    def __append_delete_message(delete_message_map: Optional[Dict[str, List[dict]]], torrent_hash: str,
                                site_name: str, torrent_title: str, torrent_desc: str, reason: str,
                                title: str = "【刷流任务种子删除】"):
        """
        追加待发送的删种消息（仅在真正删种成功后发送）
        """
        if delete_message_map is None or not torrent_hash:
            return
        payload = {
            "site_name": site_name,
            "torrent_title": torrent_title,
            "torrent_desc": torrent_desc,
            "reason": reason,
            "title": title
        }
        delete_message_map.setdefault(torrent_hash, []).append(payload)

    def __send_delete_messages_after_success(self, delete_hashes: List[str],
                                             delete_message_map: Optional[Dict[str, List[dict]]],
                                             torrent_tasks: Dict[str, dict]):
        """
        仅对真实删除成功的种子发送删种消息
        """
        if not delete_hashes:
            return
        sent_messages = set()
        for torrent_hash in delete_hashes:
            payloads = (delete_message_map or {}).get(torrent_hash) or []
            if not payloads and torrent_hash in torrent_tasks:
                torrent_task = torrent_tasks.get(torrent_hash, {})
                payloads = [{
                    "site_name": torrent_task.get("site_name", ""),
                    "torrent_title": torrent_task.get("title", ""),
                    "torrent_desc": torrent_task.get("description", ""),
                    "reason": "满足删除条件并已执行彻底删除（含下载文件）",
                    "title": "【刷流任务种子删除】"
                }]

            for payload in payloads:
                title = payload.get("title") or "【刷流任务种子删除】"
                reason = payload.get("reason") or "满足删除条件并已执行彻底删除（含下载文件）"
                message_key = f"{torrent_hash}|{title}|{reason}"
                if message_key in sent_messages:
                    continue
                sent_messages.add(message_key)
                self.__send_delete_message(site_name=payload.get("site_name", ""),
                                           torrent_title=payload.get("torrent_title", ""),
                                           torrent_desc=payload.get("torrent_desc", ""),
                                           reason=reason,
                                           title=title)

    def __send_delete_summary_messages_after_success(self, delete_hashes: List[str],
                                                     delete_summary_messages: Optional[List[dict]]):
        """
        仅在真实删除成功后发送汇总消息
        """
        if not delete_hashes or not delete_summary_messages:
            return
        deleted_hash_set = set(delete_hashes)
        for summary_message in delete_summary_messages:
            related_hashes = set(summary_message.get("hashes", []))
            if not related_hashes:
                continue
            success_count = len(deleted_hash_set.intersection(related_hashes))
            if success_count <= 0:
                continue
            summary_text = summary_message.get("text", "")
            summary_text = f"{summary_text}\n结果：下载器已完成 {success_count} 个种子彻底删除（含下载文件）"
            self.__send_message(title=summary_message.get("title", "【刷流任务种子删除】"), text=summary_text)

    def __send_delete_failed_message(self, failed_hashes: List[str], torrent_tasks: Dict[str, dict]):
        """
        发送删种失败消息，明确提示“删除种子并删除文件”失败
        """
        if not failed_hashes:
            return
        failed_hashes = list(dict.fromkeys([hash_value for hash_value in failed_hashes if hash_value]))
        if not failed_hashes:
            return

        failed_tasks = [torrent_tasks.get(hash_value, {}) for hash_value in failed_hashes]
        site_names = sorted({task.get("site_name", "") for task in failed_tasks if task.get("site_name", "")})
        titles = [task.get("title", "") for task in failed_tasks if task.get("title", "")]
        title_preview = "；".join(titles[:3]) if titles else ""
        msg_text = (f"站点：{'，'.join(site_names) if site_names else '未知'}\n"
                    f"内容：共 {len(failed_hashes)} 个种子未能完成彻底删除（含下载文件）")
        if title_preview:
            msg_text = f"{msg_text}\n示例：{title_preview}"
        msg_text = (f"{msg_text}\n原因：下载器未成功执行“删除种子并删除文件”，"
                    f"请检查下载器权限、保存路径权限或连接状态后重试")
        self.__send_message(title="【刷流任务删种失败】", text=msg_text)

    def __update_undeleted_torrents_missing_in_downloader(self, torrent_tasks, torrent_check_hashes, torrents):
        """
        处理已经被删除，但是任务记录中还没有被标记删除的种子
        """
        # 先通过获取的全量种子，判断已经被删除，但是任务记录中还没有被标记删除的种子
        torrent_all_hashes = set(self.__get_all_hashes(torrents))
        missing_hashes = [hash_value for hash_value in torrent_check_hashes
                          if self.__normalize_hash(hash_value) not in torrent_all_hashes]
        undeleted_hashes = [hash_value for hash_value in missing_hashes if
                            self.__normalize_hash(hash_value) in torrent_tasks
                            and not torrent_tasks[self.__normalize_hash(hash_value)].get("deleted")]

        if not undeleted_hashes:
            return

        # 初始化汇总信息
        delete_tasks = []
        for hash_value in undeleted_hashes:
            hash_value = self.__normalize_hash(hash_value)
            # 获取对应的任务信息
            torrent_task = torrent_tasks[hash_value]
            # 标记为已删除
            torrent_task["deleted"] = True
            torrent_task["deleted_time"] = time.time()
            # 处理日志相关内容
            delete_tasks.append(torrent_task)
            site_name = torrent_task.get("site_name", "")
            torrent_title = torrent_task.get("title", "")
            torrent_desc = torrent_task.get("description", "")
            logger.info(
                f"站点：{site_name}，无法在下载器中找到对应种子信息，更新刷流任务状态为已删除，种子：{torrent_title}|{torrent_desc}")

        self.__log_and_send_torrent_task_update_message(title="【刷流任务状态更新】", status="更新刷流状态为已删除",
                                                        reason="无法在下载器中找到对应的种子信息",
                                                        torrent_tasks=delete_tasks)

    def __convert_torrent_info_to_task(self, torrent: Any) -> dict:
        """
        根据torrent_info转换成torrent_task
        """
        torrent_info = self.__get_torrent_info(torrent=torrent)

        site_id, site_name = self.__get_site_by_torrent(torrent=torrent)

        torrent_task = {
            "site": site_id,
            "site_name": site_name,
            "title": torrent_info.get("title", ""),
            "size": torrent_info.get("total_size", 0),  # 假设total_size对应于size
            "pubdate": None,
            "description": None,
            "imdbid": None,
            "page_url": None,
            "date_elapsed": None,
            "freedate": None,
            "uploadvolumefactor": None,
            "downloadvolumefactor": None,
            "hit_and_run": None,
            "volume_factor": None,
            "freedate_diff": None,  # 假设无法从torrent_info直接获取
            "ratio": torrent_info.get("ratio", 0),
            "downloaded": torrent_info.get("downloaded", 0),
            "total_size": torrent_info.get("total_size", 0),
            "uploaded": torrent_info.get("uploaded", 0),
            "last_check_time": None,
            "last_check_uploaded": None,
            "last_check_interval_upspeed": None,
            "last_check_interval_seconds": None,
            "last_check_interval_uploaded": None,
            "last_check_interval_upspeed_valid": False,
            "last_check_interval_reason": "首次检查，暂不计算检查间上传速度",
            "interval_upspeed_hit_records": [],
            "first_downloaded_time": None,
            "first_uploaded_time": None,
            "deleted": False,
            "time": torrent_info.get("add_on", time.time())
        }
        torrent_task.update(self.__get_default_yield_guard_task_state())
        return torrent_task

    @staticmethod
    def __get_default_yield_guard_task_state() -> Dict[str, Any]:
        return {
            "last_check_downloaded": None,
            "last_check_interval_downloaded": None,
            "last_check_interval_downspeed": None,
            "last_check_interval_downspeed_valid": False,
            "yield_guard_bad_records": [],
            "yield_guard_bad_streak": 0,
            "yield_guard_stage": "normal",
            "yield_guard_last_action_time": None,
            "yield_guard_paused_time": None,
            "yield_guard_last_probe_time": None,
            "yield_guard_good_protected": False,
            "yield_guard_promising_protected": False,
            "yield_guard_restore_download_limit": False,
            "yield_guard_last_reason": ""
        }

    # endregion

    def __update_and_save_statistic_info(self, torrent_tasks):
        """
        更新并保存统计信息
        """
        total_count, total_uploaded, total_downloaded, total_deleted = 0, 0, 0, 0
        active_uploaded, active_downloaded, active_count, total_unarchived = 0, 0, 0, 0

        statistic_info = self.__get_statistic_info()
        archived_tasks = self.get_data("archived") or {}
        combined_tasks = {**torrent_tasks, **archived_tasks}

        for task in combined_tasks.values():
            if task.get("deleted", False):
                total_deleted += 1
            total_downloaded += task.get("downloaded", 0)
            total_uploaded += task.get("uploaded", 0)

        # 计算torrent_tasks中未标记为删除的活跃任务的统计信息，及待归档的任务数
        for task in torrent_tasks.values():
            if not task.get("deleted", False):
                active_uploaded += task.get("uploaded", 0)
                active_downloaded += task.get("downloaded", 0)
                active_count += 1
            else:
                total_unarchived += 1

        # 更新统计信息
        total_count = len(combined_tasks)
        statistic_info.update({
            "uploaded": total_uploaded,
            "downloaded": total_downloaded,
            "deleted": total_deleted,
            "unarchived": total_unarchived,
            "count": total_count,
            "active": active_count,
            "active_uploaded": active_uploaded,
            "active_downloaded": active_downloaded
        })

        logger.info(f"刷流任务统计数据，总任务数：{total_count}，活跃任务数：{active_count}，已删除：{total_deleted}，"
                    f"待归档：{total_unarchived}，"
                    f"活跃上传量：{StringUtils.str_filesize(active_uploaded)}，"
                    f"活跃下载量：{StringUtils.str_filesize(active_downloaded)}，"
                    f"总上传量：{StringUtils.str_filesize(total_uploaded)}，"
                    f"总下载量：{StringUtils.str_filesize(total_downloaded)}")

        self.save_data("statistic", statistic_info)
        self.save_data("torrents", torrent_tasks)

    def __get_brush_config(self, sitename: str = None) -> BrushConfig:
        """
        获取BrushConfig
        """
        return self._brush_config if not sitename else self._brush_config.get_site_config(sitename=sitename)

    def __validate_and_fix_config(self, config: dict = None) -> bool:
        """
        检查并修正配置值
        """
        if config is None:
            logger.error("配置为None，无法验证和修正")
            return False

        # 设置一个标志，用于跟踪是否发现校验错误
        found_error = False

        config_number_attr_to_desc = {
            "disksize": "保种体积",
            "maxupspeed": "总上传带宽",
            "maxdlspeed": "总下载带宽",
            "maxdlcount": "同时下载任务数",
            "free_remaining_time": "免费剩余时间",
            "delete_free_remaining_minutes": "免费临期删种阈值",
            "seed_time": "做种时间",
            "hr_seed_time": "H&R做种时间",
            "seed_ratio": "分享率",
            "seed_ratio_check_minutes": "任务添加后分钟数",
            "seed_ratio_min_30m": "任务添加后最低分享率",
            "seed_size": "上传量",
            "download_time": "下载超时时间",
            "seed_avgspeed": "平均上传速度",
            "interval_upspeed": "检查间上传速度阈值",
            "interval_upspeed_check_count": "检查间低速观察次数",
            "interval_upspeed_low_count": "检查间低速命中次数",
            "interval_upspeed_start_minutes": "有上传数据后开始低速统计分钟数",
            "skip_rules_downloading_threshold": "下载保护阈值",
            "seed_ratio_speed_protect": "分享率保护速度阈值",
            "seed_inactivetime": "未活动时间",
            "up_speed": "单任务上传限速",
            "dl_speed": "单任务下载限速",
            "auto_archive_days": "自动清理记录天数",
            "yield_guard_high_download_kbs": "收益保护高下载阈值",
            "yield_guard_low_upload_kbs": "收益保护低上传阈值",
            "yield_guard_low_ratio_percent": "收益保护低收益比阈值",
            "yield_guard_ratio_min_download_kbs": "收益比判断最小下载速度",
            "yield_guard_ratio_protect_upload_kbs": "收益比保护上传阈值",
            "yield_guard_bad_checks": "低收益连续命中次数",
            "yield_guard_min_downloaded_gb": "收益保护最小下载量",
            "yield_guard_min_progress_percent": "收益保护最小进度",
            "yield_guard_download_limit_kbs": "低收益下载限速",
            "yield_guard_fast_fail_minutes": "快速淘汰窗口",
            "yield_guard_good_upload_kbs": "高上传保护阈值",
            "yield_guard_good_avg_upload_kbs": "高平均上传保护阈值",
            "yield_guard_good_pool_min_count": "高收益池最小数量",
            "yield_guard_probe_slots": "收益保护探测名额",
            "yield_guard_probe_interval_minutes": "收益保护探测间隔",
            "yield_guard_promising_pubtime_minutes": "新发布短窗保护"
        }

        config_range_number_attr_to_desc = {
            "pubtime": "发布时间",
            "size": "种子大小",
            "seeder": "做种人数",
            "delete_size_range": "动态删种阈值"
        }

        for attr, desc in config_number_attr_to_desc.items():
            value = config.get(attr)
            if value and not self.__is_number(value):
                self.__log_and_notify_error(f"站点刷流任务出错，{desc}设置错误：{value}")
                config[attr] = None
                found_error = True  # 更新错误标志

        for attr, desc in config_range_number_attr_to_desc.items():
            value = config.get(attr)
            # 检查 value 是否存在且是否符合数字或数字-数字的模式
            if value and not self.__is_number_or_range(str(value)):
                self.__log_and_notify_error(f"站点刷流任务出错，{desc}设置错误：{value}")
                config[attr] = None
                found_error = True  # 更新错误标志

        yield_guard_action_defaults = {
            "yield_guard_first_action": ("低收益首次动作", "limit", {"none", "limit", "pause", "delete"}),
            "yield_guard_second_action": ("低收益二次动作", "pause", {"none", "pause", "delete"}),
            "yield_guard_final_action": ("短窗后最终动作", "delete", {"none", "delete"}),
        }
        for attr, (desc, default_value, allowed_values) in yield_guard_action_defaults.items():
            value = config.get(attr)
            if value in (None, ""):
                continue
            normalized_value = str(value).strip().lower()
            if normalized_value not in allowed_values:
                self.__log_and_notify_error(f"站点刷流任务出错，{desc}设置错误：{value}")
                config[attr] = default_value
                found_error = True
            else:
                config[attr] = normalized_value

        active_time_range = config.get("active_time_range")
        if active_time_range and not self.__is_valid_time_range(time_range=active_time_range):
            self.__log_and_notify_error(f"站点刷流任务出错，开启时间段设置错误：{active_time_range}")
            config["active_time_range"] = None
            found_error = True  # 更新错误标志

        free_remaining_time_skip_range = config.get("free_remaining_time_skip_range")
        if (free_remaining_time_skip_range
                and not self.__is_valid_time_range(time_range=free_remaining_time_skip_range)):
            self.__log_and_notify_error(f"站点刷流任务出错，免费时间过滤例外时段设置错误：{free_remaining_time_skip_range}")
            config["free_remaining_time_skip_range"] = None
            found_error = True  # 更新错误标志

        # 如果发现任何错误，返回False；否则返回True
        return not found_error

    def __update_config(self, brush_config: BrushConfig = None):
        """
        根据传入的BrushConfig实例更新配置
        """
        if brush_config is None:
            brush_config = self._brush_config

        if brush_config is None:
            return

        # 创建一个将配置属性名称映射到BrushConfig属性值的字典
        config_mapping = {
            "onlyonce": brush_config.onlyonce,
            "enabled": brush_config.enabled,
            "notify": brush_config.notify,
            "brushsites": brush_config.brushsites,
            "downloader": brush_config.downloader,
            "disksize": brush_config.disksize,
            "freeleech": brush_config.freeleech,
            "hr": brush_config.hr,
            "maxupspeed": brush_config.maxupspeed,
            "maxdlspeed": brush_config.maxdlspeed,
            "maxdlcount": brush_config.maxdlcount,
            "include": brush_config.include,
            "exclude": brush_config.exclude,
            "size": brush_config.size,
            "seeder": brush_config.seeder,
            "pubtime": brush_config.pubtime,
            "free_remaining_time": brush_config.free_remaining_time,
            "free_remaining_time_skip_range": brush_config.free_remaining_time_skip_range,
            "seed_time": brush_config.seed_time,
            "hr_seed_time": brush_config.hr_seed_time,
            "seed_ratio": brush_config.seed_ratio,
            "seed_ratio_check_minutes": brush_config.seed_ratio_check_minutes,
            "skip_rules_downloading_threshold": brush_config.skip_rules_downloading_threshold,
            "seed_ratio_speed_protect": brush_config.seed_ratio_speed_protect,
            "yield_guard_enabled": brush_config.yield_guard_enabled,
            "yield_guard_high_download_kbs": brush_config.yield_guard_high_download_kbs,
            "yield_guard_low_upload_kbs": brush_config.yield_guard_low_upload_kbs,
            "yield_guard_low_ratio_percent": brush_config.yield_guard_low_ratio_percent,
            "yield_guard_ratio_min_download_kbs": brush_config.yield_guard_ratio_min_download_kbs,
            "yield_guard_ratio_protect_upload_kbs": brush_config.yield_guard_ratio_protect_upload_kbs,
            "yield_guard_bad_checks": brush_config.yield_guard_bad_checks,
            "yield_guard_min_downloaded_gb": brush_config.yield_guard_min_downloaded_gb,
            "yield_guard_min_progress_percent": brush_config.yield_guard_min_progress_percent,
            "yield_guard_first_action": brush_config.yield_guard_first_action,
            "yield_guard_second_action": brush_config.yield_guard_second_action,
            "yield_guard_final_action": brush_config.yield_guard_final_action,
            "yield_guard_download_limit_kbs": brush_config.yield_guard_download_limit_kbs,
            "yield_guard_fast_fail_minutes": brush_config.yield_guard_fast_fail_minutes,
            "yield_guard_good_upload_kbs": brush_config.yield_guard_good_upload_kbs,
            "yield_guard_good_avg_upload_kbs": brush_config.yield_guard_good_avg_upload_kbs,
            "yield_guard_protect_delete_rules": brush_config.yield_guard_protect_delete_rules,
            "yield_guard_stop_brush_when_good_pool": brush_config.yield_guard_stop_brush_when_good_pool,
            "yield_guard_good_pool_min_count": brush_config.yield_guard_good_pool_min_count,
            "yield_guard_probe_slots": brush_config.yield_guard_probe_slots,
            "yield_guard_probe_interval_minutes": brush_config.yield_guard_probe_interval_minutes,
            "yield_guard_promising_pubtime_minutes": brush_config.yield_guard_promising_pubtime_minutes,
            "yield_guard_rehearsal": brush_config.yield_guard_rehearsal,
            "yield_guard_detail_log": brush_config.yield_guard_detail_log,
            "seed_ratio_min_30m": brush_config.seed_ratio_min_30m,
            "seed_size": brush_config.seed_size,
            "download_time": brush_config.download_time,
            "seed_avgspeed": brush_config.seed_avgspeed,
            "interval_upspeed": brush_config.interval_upspeed,
            "interval_upspeed_check_count": brush_config.interval_upspeed_check_count,
            "interval_upspeed_low_count": brush_config.interval_upspeed_low_count,
            "interval_upspeed_start_minutes": brush_config.interval_upspeed_start_minutes,
            "interval_upspeed_continuous": brush_config.interval_upspeed_continuous,
            "interval_upspeed_rehearsal": brush_config.interval_upspeed_rehearsal,
            "seed_inactivetime": brush_config.seed_inactivetime,
            "delete_size_range": brush_config.delete_size_range,
            "up_speed": brush_config.up_speed,
            "dl_speed": brush_config.dl_speed,
            "auto_archive_days": brush_config.auto_archive_days,
            "save_path": brush_config.save_path,
            "clear_task": brush_config.clear_task,
            "delete_except_tags": brush_config.delete_except_tags,
            "except_subscribe": brush_config.except_subscribe,
            "brush_sequential": brush_config.brush_sequential,
            "proxy_delete": brush_config.proxy_delete,
            "filter_seeding_torrents": brush_config.filter_seeding_torrents,
            "include_second_page": brush_config.include_second_page,
            "delete_when_no_free": brush_config.delete_when_no_free,
            "delete_free_remaining_minutes": brush_config.delete_free_remaining_minutes,
            "active_time_range": brush_config.active_time_range,
            "cron": brush_config.cron,
            "qb_category": brush_config.qb_category,
            "enable_site_config": brush_config.enable_site_config,
            "site_config": brush_config.site_config,
            "_tabs": self._tabs
        }

        # 使用update_config方法或其等效方法更新配置
        self.update_config(config_mapping)

    @staticmethod
    def __get_redict_url(url: str, proxies: str = None, ua: str = None, cookie: str = None) -> Optional[str]:
        """
        获取下载链接， url格式：[base64]url
        """
        # 获取[]中的内容
        m = re.search(r"\[(.*)](.*)", url)
        if m:
            # 参数
            base64_str = m.group(1)
            # URL
            url = m.group(2)
            if not base64_str:
                return url
            # 解码参数
            req_str = base64.b64decode(base64_str.encode('utf-8')).decode('utf-8')
            req_params: Dict[str, dict] = json.loads(req_str)
            # 是否使用cookie
            if not req_params.get('cookie'):
                cookie = None
            # 请求头
            if req_params.get('header'):
                headers = req_params.get('header')
            else:
                headers = None
            if req_params.get('method') == 'get':
                # GET请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).get_res(url, params=req_params.get('params'))
            else:
                # POST请求
                res = RequestUtils(
                    ua=ua,
                    proxies=proxies,
                    cookies=cookie,
                    headers=headers
                ).post_res(url, params=req_params.get('params'))
            if not res:
                return None
            if not req_params.get('result'):
                return res.text
            else:
                data = res.json()
                for key in str(req_params.get('result')).split("."):
                    data = data.get(key)
                    if not data:
                        return None
                logger.debug(f"获取到下载地址：{data}")
                return data
        return None

    def __reset_download_url(self, torrent_url, site_id) -> str:
        """
        处理下载地址
        """
        try:
            # 检查 torrent_url 是否为有效的下载 URL，并且 site 是 NexusPHP
            if not torrent_url or torrent_url.startswith("magnet"):
                return torrent_url

            indexers = self.sites_helper.get_indexers()
            if not indexers:
                return torrent_url

            unsupported_sites = {"天空"}
            site = next((item for item in indexers if item.get("id") == site_id), None)
            if site.get("name") in unsupported_sites or not site.get("schema", "").startswith("Nexus"):
                return torrent_url

            # 解析 URL
            parsed_url = urlparse(torrent_url)

            # 如果 URL 中已有查询参数，使用 urlencode 进行拼接
            query_params = dict(parse_qsl(parsed_url.query))
            query_params["letdown"] = "1"

            # 重新构造带有新参数的 URL
            new_query = urlencode(query_params)
            new_url = str(urlunparse(parsed_url._replace(query=new_query)))
            return new_url
        except Exception as e:
            logger.error(f"Error while resetting downloader URL for torrent: {torrent_url}. Error: {str(e)}")
            return torrent_url

    def __download(self, torrent: TorrentInfo) -> Optional[str]:
        """
        添加下载任务
        """
        if not torrent.enclosure:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return None

        brush_config = self.__get_brush_config(torrent.site_name)

        # 上传限速
        up_speed = int(brush_config.up_speed) if brush_config.up_speed else None
        # 下载限速
        down_speed = int(brush_config.dl_speed) if brush_config.dl_speed else None
        # 保存地址
        download_dir = brush_config.save_path or None
        # 获取下载链接
        torrent_content = torrent.enclosure
        # proxies
        proxies = settings.PROXY if torrent.site_proxy else None
        # cookie
        cookies = torrent.site_cookie
        if torrent_content.startswith("["):
            torrent_content = self.__get_redict_url(url=torrent_content,
                                                    proxies=proxies,
                                                    ua=torrent.site_ua,
                                                    cookie=cookies)
            # 目前馒头请求实际种子时，不能传入Cookie
            cookies = None
        if not torrent_content:
            logger.error(f"获取下载链接失败：{torrent.title}")
            return None

        if brush_config.site_skip_tips:
            torrent_content = self.__reset_download_url(torrent_url=torrent_content, site_id=torrent.site)
            logger.debug(f"站点 {torrent.site_name} 已启用自动跳过提示，种子下载地址更新为 {torrent_content}")

        downloader = self.downloader
        if not downloader:
            return None

        if self.downloader_helper.is_downloader("qbittorrent", service=self.service_info):
            # 限速值转为bytes
            up_speed = up_speed * 1024 if up_speed else None
            down_speed = down_speed * 1024 if down_speed else None
            # 生成随机Tag
            tag = StringUtils.generate_random_str(10)
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            if not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=cookies,
                                        proxies=proxies,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error("尝试通过MP下载种子失败，继续尝试传递种子地址到下载器进行下载")
            if torrent_content:
                before_hashes = self.__get_downloader_hash_snapshot(downloader=downloader)
                content_hash = self.__extract_hash_from_download_content(torrent_content=torrent_content)
                state = downloader.add_torrent(content=torrent_content,
                                               download_dir=download_dir,
                                               cookie=cookies,
                                               category=brush_config.qb_category,
                                               tag=["已整理", brush_config.brush_tag, tag],
                                               upload_limit=up_speed,
                                               download_limit=down_speed)
                if not state:
                    return None
                else:
                    # 获取种子Hash
                    torrent_hash = None
                    for retry_index in range(5):
                        torrent_hash = downloader.get_torrent_id_by_tag(tags=tag)
                        if torrent_hash:
                            break
                        if retry_index < 4:
                            time.sleep(1)
                    if not torrent_hash:
                        torrent_hash = self.__get_added_hash_by_snapshot_diff(
                            downloader=downloader,
                            before_hashes=before_hashes
                        )
                    if not torrent_hash:
                        torrent_hash = content_hash
                    if not torrent_hash:
                        logger.error(f"{brush_config.downloader} 获取种子Hash失败，详细信息请查看 README")
                        return None
                    return self.__normalize_hash(torrent_hash)
            return None

        elif self.downloader_helper.is_downloader("transmission", service=self.service_info):
            # 如果开启代理下载以及种子地址不是磁力地址，则请求种子到内存再传入下载器
            if not torrent_content.startswith("magnet"):
                response = RequestUtils(cookies=cookies,
                                        proxies=proxies,
                                        ua=torrent.site_ua).get_res(url=torrent_content)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error("尝试通过MP下载种子失败，继续尝试传递种子地址到下载器进行下载")
            if torrent_content:
                torrent = downloader.add_torrent(content=torrent_content,
                                                 download_dir=download_dir,
                                                 cookie=cookies,
                                                 labels=["已整理", brush_config.brush_tag])
                if not torrent:
                    return None
                else:
                    if brush_config.up_speed or brush_config.dl_speed:
                        downloader.change_torrent(hash_string=torrent.hashString,
                                                  upload_limit=up_speed,
                                                  download_limit=down_speed)
                    return self.__normalize_hash(torrent.hashString)
        return None

    def __qb_torrents_reannounce(self, torrent_hashes: List[str]):
        """强制重新汇报"""
        downloader = self.downloader
        if not downloader:
            return

        if not downloader.qbc:
            return

        if not torrent_hashes:
            return

        try:
            # 重新汇报
            downloader.qbc.torrents_reannounce(torrent_hashes=torrent_hashes)
        except Exception as err:
            logger.error(f"强制重新汇报失败：{str(err)}")

    def __apply_qb_yield_guard_action(self, torrent_hash: str, action: str, brush_config: BrushConfig,
                                      site_name: str = "", reason: str = "") -> bool:
        """
        执行上传收益保护的 qBittorrent 动作。delete 动作由现有删种流程处理。
        """
        if not torrent_hash or not brush_config.yield_guard_enabled:
            return False
        raw_action = str(action or "").strip().lower()
        action = "restore_limit" if raw_action == "restore_limit" else self.__yield_guard_action_value(action, "none")
        if action in ("none", "delete"):
            return False
        action_reason = reason or f"上传收益保护动作 {action}"
        if brush_config.yield_guard_rehearsal:
            if site_name:
                logger.info(f"站点：{site_name}，{action_reason}，上传收益保护演练模式：hash={torrent_hash}，动作={action}，不实际执行")
            else:
                logger.info(f"上传收益保护演练模式：hash={torrent_hash}，动作={action}，原因：{action_reason}，不实际执行")
            return False

        downloader = self.downloader
        if not downloader:
            return False

        try:
            if action == "limit":
                download_limit = int(self.__yield_guard_positive_number(
                    brush_config.yield_guard_download_limit_kbs, 512
                ) * 1024)
                if getattr(downloader, "qbc", None) and hasattr(downloader.qbc, "torrents_set_download_limit"):
                    downloader.qbc.torrents_set_download_limit(
                        limit=download_limit,
                        torrent_hashes=[torrent_hash]
                    )
                    return True
                if hasattr(downloader, "change_torrent"):
                    downloader.change_torrent(hash_string=torrent_hash, download_limit=download_limit)
                    return True
            if action == "restore_limit":
                download_limit = int(self.__yield_guard_positive_number(brush_config.dl_speed, 0) * 1024)
                if getattr(downloader, "qbc", None) and hasattr(downloader.qbc, "torrents_set_download_limit"):
                    downloader.qbc.torrents_set_download_limit(
                        limit=download_limit,
                        torrent_hashes=[torrent_hash]
                    )
                    return True
                if hasattr(downloader, "change_torrent"):
                    downloader.change_torrent(hash_string=torrent_hash, download_limit=download_limit)
                    return True
            if action == "pause":
                if getattr(downloader, "qbc", None) and hasattr(downloader.qbc, "torrents_pause"):
                    downloader.qbc.torrents_pause([torrent_hash])
                    return True
                if hasattr(downloader, "pause_torrent"):
                    downloader.pause_torrent(hash_string=torrent_hash)
                    return True
        except Exception as err:
            logger.error(f"上传收益保护执行 qB 动作失败，hash={torrent_hash}，动作={action}，错误：{err}")
        return False

    def __apply_yield_guard_action_for_task(self, torrent_hash: str, torrent_task: dict, action: str,
                                            brush_config: BrushConfig, site_name: str = "",
                                            reason: str = "") -> bool:
        """
        处理收益保护动作的任务状态。演练模式视为已记录动作，但不执行 qB。
        """
        if not torrent_hash or not torrent_task or not brush_config.yield_guard_enabled:
            return False

        handled = self.__apply_qb_yield_guard_action(
            torrent_hash=torrent_hash,
            action=action,
            brush_config=brush_config,
            site_name=site_name,
            reason=reason
        )
        if not handled and not brush_config.yield_guard_rehearsal:
            return False

        torrent_task["yield_guard_last_action_time"] = time.time()
        if action == "restore_limit" and not brush_config.yield_guard_rehearsal:
            torrent_task["yield_guard_restore_download_limit"] = False
        return True

    def __get_hash(self, torrent: Any):
        """
        获取种子hash
        """
        try:
            hash_value = torrent.get("hash") if self.downloader_helper.is_downloader("qbittorrent", service=self.service_info) \
                else torrent.hashString
            return self.__normalize_hash(hash_value)
        except Exception as e:
            print(str(e))
            return ""

    def __get_all_hashes(self, torrents):
        """
        获取torrents列表中所有种子的Hash值

        :param torrents: 包含种子信息的列表
        :return: 包含所有Hash值的列表
        """
        try:
            all_hashes = []
            for torrent in torrents:
                # 根据下载器类型获取Hash值
                hash_value = torrent.get("hash") if self.downloader_helper.is_downloader("qbittorrent",
                                                                                         service=self.service_info) \
                    else torrent.hashString
                hash_value = self.__normalize_hash(hash_value)
                if hash_value:
                    all_hashes.append(hash_value)
            return all_hashes
        except Exception as e:
            print(str(e))
            return []

    def __get_label(self, torrent: Any):
        """
        获取种子标签
        """
        try:
            return [str(tag).strip() for tag in torrent.get("tags").split(',')] \
                if self.downloader_helper.is_downloader("qbittorrent",
                                                        service=self.service_info) else torrent.labels or []
        except Exception as e:
            print(str(e))
            return []

    def __get_torrent_info(self, torrent: Any) -> dict:
        """
        获取种子信息
        """
        date_now = int(time.time())
        # QB
        if self.downloader_helper.is_downloader("qbittorrent", service=self.service_info):
            """
            {
              "added_on": 1693359031,
              "amount_left": 0,
              "auto_tmm": false,
              "availability": -1,
              "category": "tJU",
              "completed": 67759229411,
              "completion_on": 1693609350,
              "content_path": "/mnt/sdb/qb/downloads/Steel.Division.2.Men.of.Steel-RUNE",
              "dl_limit": -1,
              "dlspeed": 0,
              "download_path": "",
              "downloaded": 67767365851,
              "downloaded_session": 0,
              "eta": 8640000,
              "f_l_piece_prio": false,
              "force_start": false,
              "hash": "116bc6f3efa6f3b21a06ce8f1cc71875",
              "infohash_v1": "116bc6f306c40e072bde8f1cc71875",
              "infohash_v2": "",
              "last_activity": 1693609350,
              "magnet_uri": "magnet:?xt=",
              "max_ratio": -1,
              "max_seeding_time": -1,
              "name": "Steel.Division.2.Men.of.Steel-RUNE",
              "num_complete": 1,
              "num_incomplete": 0,
              "num_leechs": 0,
              "num_seeds": 0,
              "priority": 0,
              "progress": 1,
              "ratio": 0,
              "ratio_limit": -2,
              "save_path": "/mnt/sdb/qb/downloads",
              "seeding_time": 615035,
              "seeding_time_limit": -2,
              "seen_complete": 1693609350,
              "seq_dl": false,
              "size": 67759229411,
              "state": "stalledUP",
              "super_seeding": false,
              "tags": "",
              "time_active": 865354,
              "total_size": 67759229411,
              "tracker": "https://tracker",
              "trackers_count": 2,
              "up_limit": -1,
              "uploaded": 0,
              "uploaded_session": 0,
              "upspeed": 0
            }
            """
            # ID
            torrent_id = torrent.get("hash")
            # 标题
            torrent_title = torrent.get("name")
            # 下载时间
            if (not torrent.get("added_on")
                    or torrent.get("added_on") < 0):
                dltime = 0
            else:
                dltime = date_now - torrent.get("added_on")
            # 做种时间
            if (not torrent.get("completion_on")
                    or torrent.get("completion_on") < 0):
                seeding_time = 0
            else:
                seeding_time = date_now - torrent.get("completion_on")
            # 分享率
            ratio = torrent.get("ratio") or 0
            # 上传量
            uploaded = torrent.get("uploaded") or 0
            # 平均上传速度 Byte/s
            if dltime:
                avg_upspeed = int(uploaded / dltime)
            else:
                avg_upspeed = uploaded
            # 已未活动 秒
            if (not torrent.get("last_activity")
                    or torrent.get("last_activity") < 0):
                iatime = 0
            else:
                iatime = date_now - torrent.get("last_activity")
            # 下载量
            downloaded = torrent.get("downloaded")
            # 种子大小
            total_size = torrent.get("total_size")
            # 添加时间
            add_on = (torrent.get("added_on") or 0)
            add_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(add_on))
            # 种子标签
            tags = torrent.get("tags")
            # tracker
            tracker = torrent.get("tracker")
        # TR
        else:
            # ID
            torrent_id = torrent.hashString
            # 标题
            torrent_title = torrent.name
            # 做种时间
            if (not torrent.date_done
                    or torrent.date_done.timestamp() < 1):
                seeding_time = 0
            else:
                seeding_time = date_now - int(torrent.date_done.timestamp())
            # 下载耗时
            if (not torrent.date_added
                    or torrent.date_added.timestamp() < 1):
                dltime = 0
            else:
                dltime = date_now - int(torrent.date_added.timestamp())
            # 下载量
            downloaded = int(torrent.total_size * torrent.progress / 100)
            # 分享率
            ratio = torrent.ratio or 0
            # 上传量
            uploaded = int(downloaded * torrent.ratio)
            # 平均上传速度
            if dltime:
                avg_upspeed = int(uploaded / dltime)
            else:
                avg_upspeed = uploaded
            # 未活动时间
            if (not torrent.date_active
                    or torrent.date_active.timestamp() < 1):
                iatime = 0
            else:
                iatime = date_now - int(torrent.date_active.timestamp())
            # 种子大小
            total_size = torrent.total_size
            # 添加时间
            add_on = (torrent.date_added.timestamp() if torrent.date_added else 0)
            add_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(add_on))
            # 种子标签
            tags = torrent.get("tags")
            # tracker
            tracker = torrent.get("tracker")

        return {
            "hash": torrent_id,
            "title": torrent_title,
            "seeding_time": seeding_time,
            "ratio": ratio,
            "uploaded": uploaded,
            "downloaded": downloaded,
            "avg_upspeed": avg_upspeed,
            "iatime": iatime,
            "dltime": dltime,
            "total_size": total_size,
            "add_time": add_time,
            "add_on": add_on,
            "tags": tags,
            "tracker": tracker
        }

    def __log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message, title="shualiu")

    def __send_delete_message(self, site_name: str, torrent_title: str, torrent_desc: str, reason: str,
                              title: str = "【刷流任务种子删除】"):
        """
        发送删除种子的消息
        """
        brush_config = self.__get_brush_config()
        if not brush_config.notify:
            return
        msg_text = ""
        if site_name:
            msg_text = f"站点：{site_name}"
        if torrent_title:
            msg_text = f"{msg_text}\n标题：{torrent_title}"
        if torrent_desc:
            msg_text = f"{msg_text}\n内容：{torrent_desc}"
        if reason:
            msg_text = f"{msg_text}\n原因：{reason}"

        self.post_message(mtype=NotificationType.SiteMessage, title=title, text=msg_text)

    @staticmethod
    def __build_add_message_text(torrent):
        """
        构建消息文本，兼容TorrentInfo对象和torrent_task字典
        """

        # 定义一个辅助函数来统一获取数据的方式
        def get_data(_key, default=None):
            if isinstance(torrent, dict):
                return torrent.get(_key, default)
            else:
                return getattr(torrent, _key, default)

        # 构造消息文本，确保使用中文标签
        msg_parts = []
        label_mapping = {
            "site_name": "站点",
            "title": "标题",
            "description": "内容",
            "size": "大小",
            "pubdate": "发布时间",
            "seeders": "做种数",
            "volume_factor": "促销",
            "freedate_diff": "免费剩余",
            "hit_and_run": "Hit&Run"
        }
        for key in label_mapping:
            value = get_data(key)
            if key == "size" and value and str(value).replace(".", "", 1).isdigit():
                value = StringUtils.str_filesize(value)
            if value:
                msg_parts.append(f"{label_mapping[key]}：{'是' if key == 'hit_and_run' and value else value}")

        return "\n".join(msg_parts)

    def __send_add_message(self, torrent, title: str = "【刷流任务种子下载】"):
        """
        发送添加下载的消息
        """
        brush_config = self.__get_brush_config()
        if not brush_config.notify:
            return

        # 使用辅助方法构建消息文本
        msg_text = self.__build_add_message_text(torrent)
        self.post_message(mtype=NotificationType.SiteMessage, title=title, text=msg_text)

    def __send_message(self, title: str, text: str):
        """
        发送消息
        """
        brush_config = self.__get_brush_config()
        if not brush_config.notify:
            return

        self.post_message(mtype=NotificationType.SiteMessage, title=title, text=text)

    def __log_and_send_torrent_task_update_message(self, title: str, status: str, reason: str,
                                                   torrent_tasks: List[dict]):
        """
        记录和发送刷流任务更新消息
        """
        if torrent_tasks:
            sites_names = ', '.join({task.get("site_name", "N/A") for task in torrent_tasks})
            first_title = torrent_tasks[0].get('title', 'N/A')
            count = len(torrent_tasks)
            msg = f"站点：{sites_names}\n内容：{first_title} 等 {count} 个种子已经{status}\n原因：{reason}"
            logger.info(f"{title}，{msg}")
            self.__send_message(title=title, text=msg)

    def __get_torrents_size(self) -> int:
        """
        获取任务中的种子总大小
        """
        # 读取种子记录
        task_info = self.get_data("torrents") or {}
        if not task_info:
            return 0
        total_size = sum([task.get("size") or 0 for task in task_info.values()])
        return total_size

    def __get_average_bandwidth(self, sample_count: int = 5, interval: float = 3.0) \
            -> Tuple[Optional[float], Optional[float]]:
        """
        多次采样上传和下载带宽，取平均值
        """
        upload_speeds = []
        download_speeds = []
        start_time = time.time()
        for _ in range(sample_count):
            downloader_info = self.__get_downloader_info()
            if downloader_info:
                upload_speeds.append(downloader_info.upload_speed or 0)
                download_speeds.append(downloader_info.download_speed or 0)
            # 采样间隔
            time.sleep(interval)
        end_time = time.time()
        total_duration = end_time - start_time
        if not upload_speeds or not download_speeds:
            return None, None
        avg_upload_speed = sum(upload_speeds) / len(upload_speeds) if upload_speeds else 0
        avg_download_speed = sum(download_speeds) / len(download_speeds) if download_speeds else 0
        logger.debug(f"平均上传带宽 {StringUtils.str_filesize(avg_upload_speed)}, "
                     f"平均下载带宽 {StringUtils.str_filesize(avg_download_speed)}, "
                     f"采样次数={sample_count}, 时长={total_duration:.2f} 秒")
        return avg_upload_speed, avg_download_speed

    def __get_downloader_info(self) -> schemas.DownloaderInfo:
        """
        获取下载器实时信息（所有下载器）
        """
        ret_info = schemas.DownloaderInfo()

        downloader = self.downloader
        if not downloader:
            return ret_info

        transfer_infos = self.chain.run_module("downloader_info")
        if transfer_infos:
            for transfer_info in transfer_infos:
                ret_info.download_speed += transfer_info.download_speed
                ret_info.upload_speed += transfer_info.upload_speed
                ret_info.download_size += transfer_info.download_size
                ret_info.upload_size += transfer_info.upload_size

        return ret_info

    def __get_downloading_count(self) -> int:
        """
        获取正在下载的任务数量
        """
        try:
            brush_config = self.__get_brush_config()
            downloader = self.downloader
            if not downloader:
                return 0

            torrents = downloader.get_downloading_torrents(tags=brush_config.brush_tag)
            if torrents is None:
                logger.warning("获取下载数量失败，可能是下载器连接发生异常")
                return 0

            return len(torrents)
        except Exception as e:
            logger.error(f"获取下载数量发生异常: {e}")
            return 0

    @staticmethod
    def __get_pubminutes(pubdate: str) -> float:
        """
        将字符串转换为时间，并计算与当前时间差）（分钟）
        """
        try:
            if not pubdate:
                return 0
            pubdate = pubdate.replace("T", " ").replace("Z", "")
            pubdate = datetime.strptime(pubdate, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            return (now - pubdate).total_seconds() // 60
        except Exception as e:
            logger.error(f"发布时间 {pubdate} 获取分钟失败，错误详情: {e}")
            return 0

    @classmethod
    def __parse_duration_minutes(cls, time_text: str) -> Optional[float]:
        """
        解析常见的剩余时间文本，返回分钟数
        """
        if not time_text:
            return None
        text = html.unescape(str(time_text)).strip().lower()
        if not text:
            return None

        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = cls.__normalize_chinese_duration_text(text)

        # 永久免费场景默认放行
        if any(keyword in text for keyword in ["永久", "forever", "long-term", "unlimited", "无限"]):
            return None

        total_minutes = 0.0
        matched = False
        patterns = [
            (r"(\d+(?:\.\d+)?)\s*(?:天|日|day|days)", 1440),
            (r"(\d+(?:\.\d+)?)\s*(?:小时|小時|时|時|hour|hours|hr|hrs|h)", 60),
            (r"(\d+(?:\.\d+)?)\s*(?:分钟|分鐘|分|min|mins|minute|minutes|m)", 1),
            (r"(\d+(?:\.\d+)?)\s*(?:秒|second|seconds|sec|secs|s)", 1 / 60),
        ]

        for pattern, factor in patterns:
            values = re.findall(pattern, text, re.IGNORECASE)
            if not values:
                continue
            matched = True
            total_minutes += sum(float(value) for value in values) * factor

        if matched:
            return max(0, total_minutes)

        # 兼容 01:20:30 / 12:40 等格式
        if re.match(r"^\d{1,3}:\d{1,2}(:\d{1,2})?$", text):
            parts = [int(part) for part in text.split(":")]
            if len(parts) == 2:
                return max(0, parts[0] * 60 + parts[1])
            return max(0, parts[0] * 60 + parts[1] + parts[2] / 60)

        # 纯数字默认按分钟处理
        if re.match(r"^\d+(?:\.\d+)?$", text):
            return max(0, float(text))

        return None

    @classmethod
    def __normalize_chinese_duration_text(cls, text: str) -> str:
        """
        将“free三天”“两小时”等中文数字时长表达标准化为可解析的数字表达
        """
        if not text:
            return text

        pattern = r"([零〇一二两三四五六七八九十百千半]+)(?=\s*(?:天|日|小时|小時|时|時|分钟|分鐘|分|秒))"

        def repl(match):
            converted = cls.__chinese_number_to_float(match.group(1))
            if converted is None:
                return match.group(1)
            if converted.is_integer():
                return str(int(converted))
            return str(converted)

        return re.sub(pattern, repl, text)

    @staticmethod
    def __chinese_number_to_float(value: str) -> Optional[float]:
        """
        支持常见中文数字（含“半”）转换
        """
        if not value:
            return None

        raw = str(value).strip()
        if not raw:
            return None

        if re.match(r"^\d+(?:\.\d+)?$", raw):
            return float(raw)

        digits = {
            "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9
        }
        units = {"十": 10, "百": 100, "千": 1000}

        if raw == "半":
            return 0.5

        bonus = 0.0
        if raw.endswith("半"):
            bonus = 0.5
            raw = raw[:-1]
            if not raw:
                return bonus

        total = 0
        current = 0
        for char in raw:
            if char in digits:
                current = digits[char]
            elif char in units:
                unit = units[char]
                if current == 0:
                    current = 1
                total += current * unit
                current = 0
            else:
                return None
        total += current

        if total == 0 and raw:
            return None
        return float(total) + bonus

    @staticmethod
    def __get_task_elapsed_minutes(task_time: Any) -> Optional[float]:
        """
        获取任务从添加到当前的分钟数
        """
        if task_time is None:
            return None
        try:
            elapsed_minutes = (time.time() - float(task_time)) / 60
            return max(0, elapsed_minutes)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def __has_free_markers(*texts: Any) -> bool:
        """
        通过文本特征判断是否存在免费标记（用于兜底）
        """
        merged = " ".join([html.unescape(str(text)) for text in texts if text]).strip()
        if not merged:
            return False

        patterns = [
            r"优惠剩余时间",
            r"免费剩余时间",
            r"免费剩余",
            r"2x\s*免费",
            r"2xfree",
            r"\bfree\s*(?:\d|[零〇一二两三四五六七八九十百千半])",
            r"class\s*=\s*[\"']pro_free[\"']",
            r">\s*免费\s*<"
        ]
        return any(re.search(pattern, merged, re.IGNORECASE) for pattern in patterns)

    @classmethod
    def __is_free_torrent(cls, torrent: Any) -> bool:
        """
        兼容不同站点返回格式，判断是否免费种
        """
        if isinstance(torrent, dict):
            factor = torrent.get("downloadvolumefactor", None)
            freedate = torrent.get("freedate", None)
            freedate_diff = torrent.get("freedate_diff", None)
            title = torrent.get("title", None)
            description = torrent.get("description", None)
        else:
            factor = getattr(torrent, "downloadvolumefactor", None)
            freedate = getattr(torrent, "freedate", None)
            freedate_diff = getattr(torrent, "freedate_diff", None)
            title = getattr(torrent, "title", None)
            description = getattr(torrent, "description", None)

        marker_free = cls.__has_free_markers(freedate, freedate_diff, title, description)

        if factor is None:
            return bool(freedate or freedate_diff or marker_free)

        try:
            if float(factor) == 0:
                return True
        except (TypeError, ValueError):
            value = str(factor).strip().lower()
            if value in {"0", "0.0", "0.00", "free", "免费"}:
                return True

        # 兜底：部分站点/版本存在下载因子解析不准，但标题/副标题已明确标注免费
        return marker_free

    @staticmethod
    def __is_2x_torrent(torrent: Any) -> bool:
        """
        兼容不同站点返回格式，判断是否双倍上传
        """
        factor = torrent.get("uploadvolumefactor", None) if isinstance(torrent, dict) \
            else getattr(torrent, "uploadvolumefactor", None)
        try:
            return float(factor) == 2
        except (TypeError, ValueError):
            value = str(factor).strip().lower()
            return value in {"2", "2.0", "2.00", "2x", "double"}

    @staticmethod
    def __extract_free_time_snippets(text: Any) -> List[str]:
        """
        从标题/副标题等文本中提取与免费剩余时间相关的片段
        """
        if not text:
            return []

        raw_text = html.unescape(str(text))
        plain_text = re.sub(r"<[^>]+>", " ", raw_text)
        plain_text = re.sub(r"\s+", " ", plain_text).strip()

        snippets = []
        keyword_patterns = [
            r"(?:优惠剩余时间|免费剩余时间|免费剩余|剩余时间)\s*[:：]?\s*[^]\[|；;，,。]{0,60}",
            r"free\s*[零〇一二两三四五六七八九十百千半\d\.]+\s*(?:天|日|小时|小時|时|時|分钟|分鐘|分|hour|hours|hr|hrs|min|m)"
        ]

        for pattern in keyword_patterns:
            for matched in re.findall(pattern, plain_text, re.IGNORECASE):
                candidate = matched.strip()
                if candidate:
                    snippets.append(candidate)

        if re.search(r"(?:天|日|小时|小時|时|時|分钟|分鐘|分|hour|hours|hr|hrs|min|m)", plain_text, re.IGNORECASE):
            if len(plain_text) <= 32:
                snippets.append(plain_text)

        for matched in re.findall(r"title\s*=\s*[\"'](\d{4}[-/.]\d{2}[-/.]\d{2}[ T]\d{2}:\d{2}:\d{2})[\"']",
                                  raw_text, re.IGNORECASE):
            snippets.append(matched.strip())

        return list(dict.fromkeys([snippet for snippet in snippets if snippet]))

    @classmethod
    def __parse_deadline_to_minutes(cls, deadline_text: Any) -> Optional[float]:
        """
        将截止时间文本解析为剩余分钟数
        """
        if not deadline_text:
            return None

        text = html.unescape(str(deadline_text)).strip()
        if not text:
            return None

        timestamps = []

        if re.match(r"^\d{10,13}$", text):
            ts_value = float(text)
            if len(text) == 13:
                ts_value /= 1000
            timestamps.append(ts_value)

        ts_from_stringutils = StringUtils.str_to_timestamp(text)
        if ts_from_stringutils:
            timestamps.append(float(ts_from_stringutils))

        normalized_text = text.replace("T", " ").replace("Z", "").split(".")[0].strip()
        normalized_text = normalized_text.replace("/", "-").replace(".", "-")
        if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$", normalized_text):
            try:
                naive_dt = datetime.strptime(normalized_text, "%Y-%m-%d %H:%M:%S")
                timestamps.append(naive_dt.timestamp())
                timestamps.append(naive_dt.replace(tzinfo=pytz.UTC).timestamp())
            except Exception:
                pass

        if not timestamps:
            return None

        now_ts = time.time()
        remaining_candidates = [(ts - now_ts) / 60 for ts in timestamps]
        positive_remaining = [minute for minute in remaining_candidates if minute >= 0]
        if positive_remaining:
            return min(positive_remaining)
        return 0

    @classmethod
    def __get_free_remaining_minutes(cls, freedate: Any = None, freedate_diff: Optional[str] = None,
                                     title: Optional[str] = None, description: Optional[str] = None) \
            -> Optional[float]:
        """
        获取免费剩余分钟数
        """
        # 优先使用显式剩余时长字段，避免截止时间时区差异导致误判
        parsed_from_diff = cls.__parse_duration_minutes(freedate_diff or "")
        if parsed_from_diff is not None:
            return parsed_from_diff

        candidate_texts = []

        if freedate:
            candidate_texts.append(str(freedate))

        candidate_texts.extend(cls.__extract_free_time_snippets(description))
        candidate_texts.extend(cls.__extract_free_time_snippets(title))

        if not candidate_texts:
            return None

        duration_candidates = []
        deadline_candidates = []
        for candidate_text in candidate_texts:
            parsed_duration = cls.__parse_duration_minutes(candidate_text)
            if parsed_duration is not None:
                duration_candidates.append(parsed_duration)

            parsed_deadline = cls.__parse_deadline_to_minutes(candidate_text)
            if parsed_deadline is not None:
                deadline_candidates.append(parsed_deadline)

        if duration_candidates:
            positive_durations = [minute for minute in duration_candidates if minute >= 0]
            if positive_durations:
                # 多个时长候选时，优先取更宽松值，避免因噪声文本误杀
                return max(positive_durations)
            return 0

        if deadline_candidates:
            positive_deadlines = [minute for minute in deadline_candidates if minute >= 0]
            if positive_deadlines:
                return min(positive_deadlines)
            return 0

        return None

    @staticmethod
    def __adjust_site_pubminutes(pub_minutes: float, torrent: TorrentInfo) -> float:
        """
        处理部分站点的时区逻辑
        """
        try:
            if not torrent:
                return pub_minutes

            if torrent.site_name == "我堡":
                # 获取当前时区的UTC偏移量（以秒为单位）
                utc_offset_seconds = time.timezone

                # 将UTC偏移量转换为分钟
                utc_offset_minutes = utc_offset_seconds / 60

                # 增加UTC偏移量到pub_minutes
                adjusted_pub_minutes = pub_minutes + utc_offset_minutes

                return adjusted_pub_minutes

            return pub_minutes
        except Exception as e:
            logger.error(str(e))
            return 0

    def __filter_torrents_by_tag(self, torrents: List[Any], exclude_tag: str) -> List[Any]:
        """
        根据标签过滤torrents，排除标签格式为逗号分隔的字符串，例如 "MOVIEPILOT, H&R"
        """
        # 如果排除标签字符串为空，则返回原始列表
        if not exclude_tag:
            return torrents

        # 将 exclude_tag 字符串分割成一个集合，并去除每个标签两端的空白，忽略空白标签并自动去重
        exclude_tags = set(tag.strip() for tag in exclude_tag.split(',') if tag.strip())

        filter_torrents = []
        for torrent in torrents:
            # 使用 __get_label 方法获取每个 torrent 的标签列表
            labels = self.__get_label(torrent)
            # 检查是否有任何一个排除标签存在于标签列表中
            if not any(exclude in labels for exclude in exclude_tags):
                filter_torrents.append(torrent)
        return filter_torrents

    def __get_subscribe_titles(self) -> Set[str]:
        """
        获取当前订阅的所有标题，返回一个不包含None和空白字符的集合
        """
        brush_config = self.__get_brush_config()
        if not brush_config.except_subscribe:
            logger.info("没有开启排除订阅，取消订阅标题匹配")
            return set()

        logger.info("已开启排除订阅，正在准备订阅标题匹配 ...")

        if not self._subscribe_infos:
            self._subscribe_infos = {}

        subscribes = self.subscribe_oper.list()
        if subscribes:
            # 遍历订阅
            for subscribe in subscribes:
                # 判断当前订阅是否已经在缓存中，如果已经处理过，那么这里直接跳过
                subscribe_key = f"{subscribe.id}_{subscribe.name}"
                if subscribe_key in self._subscribe_infos:
                    continue

                subscribe_titles = [subscribe.name]
                try:
                    # 生成元数据
                    meta = MetaInfo(subscribe.name)
                    meta.year = subscribe.year
                    meta.begin_season = subscribe.season or None
                    meta.type = MediaType(subscribe.type)
                    # 识别媒体信息
                    mediainfo: MediaInfo = self.chain.recognize_media(meta=meta, mtype=meta.type,
                                                                      tmdbid=subscribe.tmdbid,
                                                                      doubanid=subscribe.doubanid,
                                                                      cache=True)
                    if mediainfo:
                        logger.info(f"订阅 {subscribe.name} 已识别到媒体信息")
                        logger.debug(f"subscribe {subscribe.name} {mediainfo.to_dict()}")
                        subscribe_titles.extend(mediainfo.names)
                        subscribe_titles = [title.strip() for title in subscribe_titles if title and title.strip()]
                        self._subscribe_infos[subscribe_key] = subscribe_titles
                    else:
                        logger.info(f"订阅 {subscribe.name} 没有识别到媒体信息，跳过订阅标题匹配")
                except Exception as e:
                    logger.error(f"识别订阅 {subscribe.name} 媒体信息失败，错误详情: {e}")

            # 移除不再存在的订阅
            current_keys = {f"{subscribe.id}_{subscribe.name}" for subscribe in subscribes}
            for key in set(self._subscribe_infos) - current_keys:
                del self._subscribe_infos[key]

        logger.info("订阅标题匹配完成")
        logger.debug(f"当前订阅的标题集合为：{self._subscribe_infos}")
        unique_titles = {title for titles in self._subscribe_infos.values() for title in titles}
        return unique_titles

    @staticmethod
    def __filter_torrents_contains_subscribe(torrents: Any, subscribe_titles: Set[str]):
        # 初始化两个列表，一个用于收集未被排除的种子，一个用于记录被排除的种子
        included_torrents = []
        excluded_torrents = []

        # 单次遍历处理
        for torrent in torrents:
            # 确保title和description至少是空字符串
            title = torrent.title or ''
            description = torrent.description or ''

            if any(subscribe_title in title or subscribe_title in description for subscribe_title in subscribe_titles):
                # 如果种子的标题或描述包含订阅标题中的任一项，则记录为被排除
                excluded_torrents.append(torrent)
                logger.info(f"命中订阅内容，排除种子：{title}|{description}")
            else:
                # 否则，收集为未被排除的种子
                included_torrents.append(torrent)

        if not excluded_torrents:
            logger.info(f"没有命中订阅内容，不需要排除种子")

        # 返回未被排除的种子列表
        return included_torrents

    @staticmethod
    def __bytes_to_gb(size_in_bytes: float) -> float:
        """
        将字节单位的大小转换为千兆字节（GB）。

        :param size_in_bytes: 文件大小，单位为字节。
        :return: 文件大小，单位为千兆字节（GB）。
        """
        if not size_in_bytes:
            return 0.0
        return size_in_bytes / (1024 ** 3)

    @staticmethod
    def __is_number_or_range(value):
        """
        检查字符串是否表示单个数字或数字范围（如'5', '5.5', '5-10' 或 '5.5-10.2'）
        """
        return bool(re.match(r"^\d+(\.\d+)?(-\d+(\.\d+)?)?$", value))

    @staticmethod
    def __is_number(value):
        """
        检查给定的值是否可以被转换为数字（整数或浮点数）
        """
        try:
            float(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def __get_delete_free_remaining_threshold(brush_config: BrushConfig) -> float:
        """
        获取失去免费/临期删种阈值，未配置或配置异常时使用默认5分钟。
        """
        try:
            threshold = float(brush_config.delete_free_remaining_minutes)
        except (TypeError, ValueError):
            return 5.0
        return threshold if threshold >= 0 else 5.0

    @staticmethod
    def __calculate_seeding_torrents_size(torrent_tasks: Dict[str, dict]) -> float:
        """
        计算保种种子体积
        """
        return sum(task.get("size", 0) for task in torrent_tasks.values() if not task.get("deleted", False))

    def __auto_archive_tasks(self, torrent_tasks: Dict[str, dict]) -> None:
        """
       自动归档已经删除的种子数据
       """
        if not self._brush_config.auto_archive_days or self._brush_config.auto_archive_days <= 0:
            logger.info("自动归档记录天数小于等于0，取消自动归档")
            return

        # 用于存储已删除的数据
        archived_tasks: Dict[str, dict] = self.get_data("archived") or {}

        current_time = time.time()
        archive_threshold_seconds = self._brush_config.auto_archive_days * 86400  # 将天数转换为秒数

        # 准备一个列表，记录所有需要从原始数据中删除的键
        keys_to_delete = set()

        # 遍历所有 torrent 条目
        for key, value in torrent_tasks.items():
            deleted_time = value.get("deleted_time")
            # 场景 1: 检查任务是否已被标记为删除且超出保留天数
            if (value.get("deleted") and isinstance(deleted_time, (int, float)) and
                    current_time - deleted_time > archive_threshold_seconds):
                keys_to_delete.add(key)
                archived_tasks[key] = value
                continue

            # 场景 2: 检查没有明确删除时间的历史数据
            if value.get("deleted") and deleted_time is None:
                keys_to_delete.add(key)
                archived_tasks[key] = value
                continue

        # 从原始字典中移除已删除的条目
        for key in keys_to_delete:
            del torrent_tasks[key]

        self.save_data("archived", archived_tasks)

    def __clear_tasks(self):
        """
        清除统计数据
        彻底重置所有刷流数据，如当前还存在正在做种的刷流任务，待定时检查任务执行后，会自动纳入刷流管理
        """
        self.save_data("torrents", {})
        self.save_data("archived", {})
        self.save_data("unmanaged", {})
        self.save_data("statistic", {})

    def __get_statistic_info(self) -> Dict[str, int]:
        """
        获取统计数据
        """
        statistic_info = self.get_data("statistic") or {
            "count": 0,
            "deleted": 0,
            "uploaded": 0,
            "downloaded": 0,
            "unarchived": 0,
            "active": 0,
            "active_uploaded": 0,
            "active_downloaded": 0
        }
        return statistic_info

    @staticmethod
    def __is_valid_time_range(time_range: str) -> bool:
        """检查时间范围字符串是否有效：格式为"HH:MM-HH:MM"，且时间有效"""
        if not time_range:
            return False

        # 使用正则表达式匹配格式
        pattern = re.compile(r'^\d{2}:\d{2}-\d{2}:\d{2}$')
        if not pattern.match(time_range):
            return False

        try:
            start_str, end_str = time_range.split('-')
            datetime.strptime(start_str, '%H:%M').time()
            datetime.strptime(end_str, '%H:%M').time()
        except Exception as e:
            print(str(e))
            return False

        return True

    @classmethod
    def __is_now_in_time_range(cls, time_range: str) -> bool:
        """判断当前时间是否在指定时间区间内"""
        if not cls.__is_valid_time_range(time_range):
            return False

        start_str, end_str = time_range.split('-')
        start_time = datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.strptime(end_str, '%H:%M').time()
        now = datetime.now().time()

        if start_time <= end_time:
            # 情况1: 时间段不跨越午夜
            return start_time <= now <= end_time
        else:
            # 情况2: 时间段跨越午夜
            return now >= start_time or now <= end_time

    def __is_current_time_in_range(self) -> bool:
        """判断当前时间是否在开启时间区间内"""

        brush_config = self.__get_brush_config()
        active_time_range = brush_config.active_time_range

        if not self.__is_valid_time_range(active_time_range):
            # 如果时间范围格式不正确或不存在，说明当前没有开启时间段，返回True
            return True

        return self.__is_now_in_time_range(active_time_range)

    def __should_skip_free_remaining_time_filter(self, brush_config: BrushConfig) -> bool:
        """判断当前是否处于免费剩余时间过滤例外时段"""
        return self.__is_now_in_time_range(brush_config.free_remaining_time_skip_range)

    def __get_site_by_torrent(self, torrent: Any) -> Tuple[int, str]:
        """
        根据tracker获取站点信息
        """
        trackers = []
        try:
            tracker_url = torrent.get("tracker")
            if tracker_url:
                trackers.append(tracker_url)

            magnet_link = torrent.get("magnet_uri")
            if magnet_link:
                query_params: dict = parse_qs(urlparse(magnet_link).query)
                encoded_tracker_urls = query_params.get('tr', [])
                # 解码tracker URLs然后扩展到trackers列表中
                decoded_tracker_urls = [unquote(url) for url in encoded_tracker_urls]
                trackers.extend(decoded_tracker_urls)
        except Exception as e:
            logger.error(e)

        domain = "未知"
        if not trackers:
            return 0, domain

        # 特定tracker到域名的映射
        tracker_mappings = {
            "chdbits.xyz": "ptchdbits.co",
            "agsvpt.trackers.work": "agsvpt.com",
            "tracker.cinefiles.info": "audiences.me",
        }

        for tracker in trackers:
            if not tracker:
                continue
            # 检查tracker是否包含特定的关键字，并进行相应的映射
            for key, mapped_domain in tracker_mappings.items():
                if key in tracker:
                    domain = mapped_domain
                    break
            else:
                # 使用StringUtils工具类获取tracker的域名
                domain = StringUtils.get_url_domain(tracker)

            site_info = self.sites_helper.get_indexer(domain)
            if site_info:
                return site_info.get("id"), site_info.get("name")

        # 当找不到对应的站点信息时，返回一个默认值
        return 0, domain

    def __sync_official(self, config: dict):
        """
        双向同步官方插件数据
        """
        if not config:
            return

        # 双向数据同步官方插件数据，以本地插件的数据为准
        if config.get("sync_official"):
            # 获取本地数据
            from_torrents = self.get_data("torrents") or {}
            from_archived = self.get_data("archived") or {}
            from_unmanaged = self.get_data("unmanaged") or {}

            # 获取官方插件数据
            to_torrents = self.get_data("torrents", "BrushFlow") or {}
            to_archived = self.get_data("archived", "BrushFlow") or {}
            to_unmanaged = self.get_data("unmanaged", "BrushFlow") or {}

            # 合并插件数据
            merged_torrents = {**to_torrents, **from_torrents}
            merged_archived = {**to_archived, **from_archived}
            merged_unmanaged = {**to_unmanaged, **from_unmanaged}

            # 双向保存插件数据
            self.save_data("torrents", merged_torrents)
            self.save_data("archived", merged_archived)
            self.save_data("unmanaged", merged_unmanaged)
            self.save_data("torrents", merged_torrents, "BrushFlow")
            self.save_data("archived", merged_archived, "BrushFlow")
            self.save_data("unmanaged", merged_unmanaged, "BrushFlow")

    def __check_and_resolve_plugin_conflict(self) -> bool:
        """
        判断是否存在插件冲突
        """
        brush_config = self.__get_brush_config()
        if not brush_config:
            return True

        official_config = self.get_config("BrushFlow")
        if not official_config:
            return True

        official_enabled = official_config.get("enabled")
        if official_enabled and brush_config.enabled:
            logger.warning("官方插件与当前插件只能同时启用一个，请重新配置")
            return False

        return True
