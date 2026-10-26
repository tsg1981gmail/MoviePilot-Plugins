from typing import Any, Dict, List, Optional, Tuple

from app.helper.downloader import DownloaderHelper
from app.plugins import _PluginBase

from .service import DownloaderTaskService


class DownloaderTaskManager(_PluginBase):
    """MoviePilot 下载器任务管理插件。"""

    plugin_name = "下载器任务管理"
    plugin_desc = "管理已启用下载器的单个任务和当前下载器全部任务的开始与暂停。"
    plugin_icon = "Qbittorrent_A.png"
    plugin_version = "1.0.0"
    plugin_author = "tsg1981gmail"
    author_url = "https://github.com/tsg1981gmail"
    plugin_config_prefix = "downloadertaskmanager_"
    plugin_label = "下载管理"
    plugin_order = 50
    auth_level = 1

    def __init__(self):
        """初始化插件运行状态。"""
        super().__init__()
        self._enabled = False
        self._allow_bulk_actions = False
        self._service: Optional[DownloaderTaskService] = None

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并初始化下载器任务服务。"""
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._allow_bulk_actions = bool(config.get("allow_bulk_actions"))
        helper = DownloaderHelper()
        self._service = DownloaderTaskService(
            helper=helper,
            allow_bulk_actions=self._allow_bulk_actions,
        )

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册 Bear 鉴权的任务动作接口。"""
        return [
            {
                "path": "/action",
                "endpoint": self.action,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "开始或暂停下载器任务",
                "description": "支持单个任务和当前下载器的全部任务。",
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回启用与全量操作配置表单。"""
        form = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "allow_bulk_actions",
                                            "label": "允许全量操作",
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
        defaults = {
            "enabled": False,
            "allow_bulk_actions": False,
        }
        return form, defaults

    def get_page(self) -> List[dict]:
        """返回按下载器分组的任务管理页面。"""
        content = []
        last_result = self.get_data("last_action_result")
        if isinstance(last_result, dict) and last_result.get("message"):
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "success" if last_result.get("success") else "error",
                    "variant": "tonal",
                    "text": str(last_result.get("message")),
                },
            })

        if not self._enabled:
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "插件未启用，请先在配置中启用。",
                },
            })
            return content

        views = []
        if self._service:
            try:
                views = self._service.list_views()
            except Exception as error:
                content.append({
                    "component": "VAlert",
                    "props": {
                        "type": "error",
                        "variant": "tonal",
                        "text": f"获取下载器列表失败：{error}",
                    },
                })
                return content
        if not views:
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "没有已启用的 qBittorrent 或 Transmission 下载器。",
                },
            })
            return content

        content.extend(self._build_downloader_card(view) for view in views)
        return content

    def action(self, payload: dict) -> Dict[str, Any]:
        """执行任务开始或暂停并保存最近动作结果。"""
        if not self._enabled:
            result = {
                "success": False,
                "message": "插件未启用",
                "affected": 0,
            }
        elif not self._service:
            result = {
                "success": False,
                "message": "下载器服务未初始化",
                "affected": 0,
            }
        else:
            try:
                result = self._service.execute(payload)
            except Exception as error:
                result = {
                    "success": False,
                    "message": f"执行任务动作失败：{error}",
                    "affected": 0,
                }

        self.save_data("last_action_result", result)
        return result

    def stop_service(self) -> None:
        """插件没有后台服务，无需清理资源。"""
        self._service = None

    def _build_button(
            self,
            text: str,
            action: str,
            downloader: str,
            hashes: Optional[List[str]] = None,
            scope: str = "task",
    ) -> dict:
        """构建带插件 API 点击事件的 Vuetify 按钮。"""
        params = {
            "downloader": downloader,
            "scope": scope,
            "action": action,
        }
        if hashes:
            params["hashes"] = hashes
        return {
            "component": "VBtn",
            "props": {
                "size": "small",
                "variant": "tonal",
                "color": "primary" if action == "start" else "warning",
                "prepend-icon": "mdi-play" if action == "start" else "mdi-pause",
            },
            "events": {
                "click": {
                    "api": f"plugin/{self.__class__.__name__}/action",
                    "method": "POST",
                    "params": params,
                }
            },
            "text": text,
        }

    def _build_downloader_card(self, view: dict) -> dict:
        """构建单个下载器任务卡片。"""
        name = str(view.get("name") or "")
        downloader_type = str(view.get("type") or "")
        tasks = view.get("tasks") or []
        header_content = [{
            "component": "div",
            "props": {"class": "text-subtitle-1 font-weight-medium"},
            "text": f"{name} · {self._type_text(downloader_type)} · {len(tasks)} 个任务",
        }]

        if view.get("available") and self._allow_bulk_actions and tasks:
            header_content.append({
                "component": "div",
                "props": {"class": "d-flex flex-wrap ga-2 mt-2"},
                "content": [
                    self._build_button("全部开始", "start", name, scope="all"),
                    self._build_button("全部暂停", "stop", name, scope="all"),
                ],
            })

        content = [{
            "component": "VCardText",
            "content": header_content,
        }]
        if not view.get("available"):
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "error",
                    "variant": "tonal",
                    "text": str(view.get("error") or "下载器不可用"),
                },
            })
        elif tasks:
            content.append(self._build_task_table(name, tasks))
        else:
            content.append({
                "component": "VCardText",
                "props": {"class": "text-medium-emphasis"},
                "text": "暂无任务",
            })

        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mb-3"},
            "content": content,
        }

    def _build_task_table(self, downloader: str, tasks: List[dict]) -> dict:
        """构建单个下载器的任务表格。"""
        headers = [
            "名称",
            "状态",
            "进度",
            "下载速度",
            "上传速度",
            "分类/标签",
            "操作",
        ]
        return {
            "component": "VTable",
            "props": {"hover": True, "density": "compact"},
            "content": [
                {
                    "component": "thead",
                    "content": [{
                        "component": "tr",
                        "content": [
                            {
                                "component": "th",
                                "props": {"class": "text-start"},
                                "text": header,
                            }
                            for header in headers
                        ],
                    }],
                },
                {
                    "component": "tbody",
                    "content": [
                        self._build_task_row(downloader, task)
                        for task in tasks
                    ],
                },
            ],
        }

    def _build_task_row(self, downloader: str, task: dict) -> dict:
        """构建单个任务表格行。"""
        status = str(task.get("status") or "unknown")
        action = self._task_action(status)
        action_content = []
        if action:
            action_content.append(
                self._build_button(
                    "开始" if action == "start" else "暂停",
                    action,
                    downloader,
                    hashes=[str(task.get("hash") or "")],
                )
            )
        return {
            "component": "tr",
            "content": [
                {
                    "component": "td",
                    "props": {"class": "text-body-2"},
                    "text": str(task.get("name") or task.get("hash") or ""),
                },
                {
                    "component": "td",
                    "text": str(task.get("state_text") or "未知"),
                },
                {
                    "component": "td",
                    "text": f"{float(task.get('progress') or 0):.1f}%",
                },
                {
                    "component": "td",
                    "text": self._format_speed(task.get("download_speed")),
                },
                {
                    "component": "td",
                    "text": self._format_speed(task.get("upload_speed")),
                },
                {
                    "component": "td",
                    "text": str(task.get("category") or ""),
                },
                {
                    "component": "td",
                    "content": action_content,
                    "text": "" if action_content else "无",
                },
            ],
        }

    @staticmethod
    def _task_action(status: str) -> Optional[str]:
        """根据归一化状态返回任务动作。"""
        if status in {"paused", "error"}:
            return "start"
        if status in {"downloading", "uploading", "checking", "queued"}:
            return "stop"
        return None

    @staticmethod
    def _type_text(downloader_type: str) -> str:
        """返回下载器类型展示文本。"""
        return {
            "qbittorrent": "qBittorrent",
            "transmission": "Transmission",
        }.get(downloader_type, downloader_type or "未知类型")

    @staticmethod
    def _format_speed(value: Any) -> str:
        """将字节速度格式化为可读文本。"""
        try:
            speed = float(value or 0)
        except (TypeError, ValueError):
            speed = 0.0
        units = ("B/s", "KB/s", "MB/s", "GB/s")
        unit_index = 0
        while speed >= 1024 and unit_index < len(units) - 1:
            speed /= 1024
            unit_index += 1
        if unit_index == 0:
            return f"{int(speed)} {units[unit_index]}"
        return f"{speed:.1f} {units[unit_index]}"
