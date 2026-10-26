import copy
from datetime import datetime
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

from app.helper.downloader import DownloaderHelper
from app.plugins import _PluginBase

from .runtime import SUPPORTED_DOWNLOADERS, downloader_key, schedule_field
from .service import DownloaderScheduleService


class DownloaderTaskManager(_PluginBase):
    """按下载器执行一次性定时开始或暂停。"""

    plugin_name = "下载器定时任务"
    plugin_desc = "按下载器在指定时间全部开始或暂停未完成的下载任务。"
    plugin_icon = "Qbittorrent_A.png"
    plugin_version = "1.1.0"
    plugin_author = "tsg1981gmail"
    author_url = "https://github.com/tsg1981gmail"
    plugin_config_prefix = "downloadertaskmanager_"
    plugin_label = "下载管理"
    plugin_order = 50
    auth_level = 1

    def __init__(self):
        """初始化插件状态。"""
        super().__init__()
        self._enabled = False
        self._config = {}
        self._timezone = ZoneInfo("Asia/Shanghai")
        self._schedule_service = None

    def init_plugin(self, config: dict = None) -> None:
        """初始化计划服务并迁移旧配置。"""
        config = copy.deepcopy(config or {})
        migrated = "allow_bulk_actions" in config
        config.pop("allow_bulk_actions", None)
        self._config = config
        self._enabled = bool(config.get("enabled"))
        self._timezone = self._resolve_timezone()

        registry = self.get_data("schedule_registry") or {}
        results = self.get_data("schedule_results") or {}
        helper = DownloaderHelper()
        self._schedule_service = DownloaderScheduleService(
            helper=helper,
            config=self._config,
            registry=registry,
            results=results,
            now_fn=lambda: datetime.now(self._timezone),
            timezone=self._timezone,
            persist_config=self._persist_config,
            save_registry=lambda value: self.save_data(
                "schedule_registry",
                value,
            ),
            save_results=lambda value: self.save_data(
                "schedule_results",
                value,
            ),
        )
        try:
            self._schedule_service.refresh_registry()
        except Exception:
            pass
        if migrated:
            self._persist_config(self._config)

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """不注册手动远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """不注册手动任务 API。"""
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回每个下载器的开始和暂停时间配置。"""
        content = [{
            "component": "VSwitch",
            "props": {
                "model": "enabled",
                "label": "启用插件",
            },
        }]
        defaults = {
            "enabled": bool(self._config.get("enabled")),
        }
        services = {}
        try:
            services = self._schedule_service.helper.get_services() or {}
        except Exception as error:
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "error",
                    "variant": "tonal",
                    "text": f"获取下载器列表失败：{error}",
                },
            })

        seen_keys = set()
        for service_key, service in services.items():
            name = str(getattr(service, "name", "") or service_key or "").strip()
            downloader_type = str(
                getattr(service, "type", "") or ""
            ).strip().lower()
            if not name or downloader_type not in SUPPORTED_DOWNLOADERS:
                continue
            key = downloader_key(downloader_type, name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            start_field = schedule_field(key, "start")
            stop_field = schedule_field(key, "stop")
            defaults[start_field] = str(self._config.get(start_field) or "")
            defaults[stop_field] = str(self._config.get(stop_field) or "")
            content.append({
                "component": "VCard",
                "props": {"variant": "outlined", "class": "mt-3"},
                "content": [{
                    "component": "VCardText",
                    "content": [
                        {
                            "component": "div",
                            "props": {
                                "class": "text-subtitle-1 font-weight-medium mb-2"
                            },
                            "text": f"{name} · {self._type_text(downloader_type)}",
                        },
                        {
                            "component": "VRow",
                            "content": [
                                self._date_field(
                                    start_field,
                                    "全部开始时间",
                                ),
                                self._date_field(
                                    stop_field,
                                    "全部暂停时间",
                                ),
                            ],
                        },
                    ],
                }],
            })

        for field, value in self._config.items():
            if (
                    isinstance(field, str)
                    and field.startswith("schedule_")
                    and (field.endswith("_start_at") or field.endswith("_pause_at"))
            ):
                defaults.setdefault(field, str(value or ""))

        return [{
            "component": "VForm",
            "content": content,
        }], defaults

    def get_page(self) -> List[dict]:
        """返回不带种子明细的计划状态页。"""
        if not self._enabled:
            return [{
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "插件未启用",
                },
            }]

        try:
            plans = self._schedule_service.list_plans()
        except Exception as error:
            return [{
                "component": "VAlert",
                "props": {
                    "type": "error",
                    "variant": "tonal",
                    "text": f"读取定时计划失败：{error}",
                },
            }]

        rows = []
        now = datetime.now(self._timezone)
        configured = {(plan["key"], plan["action"]) for plan in plans}
        for plan in plans:
            rows.append(self._plan_card(plan, now))

        for key, action_results in self._schedule_service.results.items():
            if not isinstance(action_results, dict):
                continue
            for action, result in action_results.items():
                if (key, action) in configured:
                    continue
                if not isinstance(result, dict) or not result.get("success"):
                    continue
                snapshot = self._schedule_service.registry.get(key) or {}
                rows.append(self._result_card(key, action, result, snapshot))

        if not rows:
            return [{
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "暂无定时计划",
                },
            }]
        return rows

    def get_service(self) -> List[Dict[str, Any]]:
        """注册每 5 分钟运行的计划检查服务。"""
        if not self._enabled:
            return []
        return [{
            "id": "DownloaderTaskManagerSchedules",
            "name": "下载器定时任务检查",
            "trigger": "interval",
            "func": self.check_schedules,
            "kwargs": {"seconds": 300},
        }]

    def check_schedules(self) -> List[dict]:
        """执行所有到期计划。"""
        if not self._enabled or not self._schedule_service:
            return []
        return self._schedule_service.run_due()

    def stop_service(self) -> None:
        """停止插件时释放服务引用。"""
        self._schedule_service = None

    def _persist_config(self, config: dict) -> None:
        """保存插件配置。"""
        self._config = config
        self.update_config(self._config)

    @staticmethod
    def _resolve_timezone() -> ZoneInfo:
        """解析 MoviePilot 配置时区。"""
        try:
            from app.core.config import settings
            timezone_name = str(getattr(settings, "TZ", "") or "")
        except Exception:
            timezone_name = ""
        try:
            return ZoneInfo(timezone_name or "Asia/Shanghai")
        except Exception:
            return ZoneInfo("Asia/Shanghai")

    @staticmethod
    def _date_field(model: str, label: str) -> dict:
        """构建本地日期时间输入框。"""
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": 6},
            "content": [{
                "component": "VTextField",
                "props": {
                    "model": model,
                    "label": label,
                    "type": "datetime-local",
                },
            }],
        }

    def _plan_card(self, plan: dict, now: datetime) -> dict:
        """构建单个计划状态卡片。"""
        if plan["error"]:
            color = "error"
            status = f"配置错误：{plan['error']}"
        elif plan["scheduled_at"] and plan["scheduled_at"] > now:
            color = "info"
            status = "已计划"
        else:
            result = self._matching_result(plan)
            if result and not result.get("success"):
                color = "warning"
                status = "等待重试"
            elif result and result.get("success"):
                color = "success"
                status = "已执行"
            else:
                color = "info"
                status = "待执行"

        action_text = "全部开始" if plan["action"] == "start" else "全部暂停"
        title = f"{plan.get('name') or '未知下载器'} · {action_text}"
        lines = [
            f"计划时间：{plan.get('scheduled_at') or plan.get('raw_value') or '-'}",
            f"状态：{status}",
        ]
        result = self._matching_result(plan)
        if result:
            lines.append(
                f"最近结果：{result.get('message') or '-'}，"
                f"{result.get('affected', 0)} 个任务"
            )
        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-3"},
            "content": [{
                "component": "VCardText",
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "text-subtitle-1 font-weight-medium"},
                        "text": title,
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": color,
                            "variant": "tonal",
                            "class": "mt-2",
                            "text": "\n".join(lines),
                        },
                    },
                ],
            }],
        }

    def _matching_result(self, plan: dict) -> dict:
        """读取与当前计划时间匹配的结果。"""
        result = (
            (self._schedule_service.results.get(plan["key"]) or {})
            .get(plan["action"]) or {}
        )
        if result.get("scheduled_at") != plan["scheduled_text"]:
            return {}
        return result

    def _result_card(
            self,
            key: str,
            action: str,
            result: dict,
            snapshot: dict,
    ) -> dict:
        """构建已成功清理计划的执行结果卡片。"""
        action_text = "全部开始" if action == "start" else "全部暂停"
        name = snapshot.get("name") or result.get("downloader") or "未知下载器"
        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-3"},
            "content": [{
                "component": "VCardText",
                "content": [{
                    "component": "VAlert",
                    "props": {
                        "type": "success",
                        "variant": "tonal",
                        "text": (
                            f"{name} · {action_text} · 已执行\n"
                            f"计划时间：{result.get('scheduled_at') or '-'}\n"
                            f"结果：{result.get('message') or '-'}，"
                            f"{result.get('affected', 0)} 个任务"
                        ),
                    },
                }],
            }],
        }

    @staticmethod
    def _type_text(downloader_type: str) -> str:
        """返回下载器类型名称。"""
        return {
            "qbittorrent": "qBittorrent",
            "transmission": "Transmission",
        }.get(downloader_type, downloader_type or "未知类型")
