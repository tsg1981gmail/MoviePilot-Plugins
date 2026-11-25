"""
飞牛影视双 NAS 播放记录同步插件（MoviePilot V2）

在两台飞牛影视之间同步相同影片的播放进度与已看完标记。
只处理两边都存在的影片，靠 IMDb / TMDB / 标题年份匹配，分集叠加季集号。
"""

import json
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.log import logger
from app.plugins import _PluginBase

try:
    from .fnvsync_core import (
        FnClient, MediaMatcher, SyncEngine, normalize_title,
    )
except ImportError:
    import importlib.util
    import os

    _spec = importlib.util.spec_from_file_location(
        "fnvsync_core",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fnvsync_core.py"),
    )
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    FnClient = _module.FnClient
    MediaMatcher = _module.MediaMatcher
    SyncEngine = _module.SyncEngine
    normalize_title = _module.normalize_title


class FnVsync(_PluginBase):
    """飞牛影视双 NAS 播放记录同步。"""

    plugin_name = "飞牛播放记录同步插件"
    plugin_desc = "同步两台飞牛影视中相同影片的播放进度和已看完标记，支持双向。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.2"
    plugin_author = "田树刚"
    author_url = ""
    plugin_config_prefix = "fnvsync_"
    plugin_order = 80
    auth_level = 1

    _enabled = False
    _run_now = False
    _last_result: Optional[dict] = None
    _last_time = ""
    _history: List[dict] = []
    _lock = threading.RLock()

    # 配置字段
    _host_a = ""
    _user_a = ""
    _pass_a = ""
    _code_a = ""
    _host_b = ""
    _user_b = ""
    _pass_b = ""
    _code_b = ""
    _direction = "both"
    _sync_watched = True
    _conflict = "keep"
    _interval = 15
    _notify = True

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._run_now = bool(config.get("run_now"))
        self._host_a = config.get("host_a") or ""
        self._user_a = config.get("user_a") or ""
        self._pass_a = config.get("pass_a") or ""
        self._code_a = config.get("code_a") or ""
        self._host_b = config.get("host_b") or ""
        self._user_b = config.get("user_b") or ""
        self._pass_b = config.get("pass_b") or ""
        self._code_b = config.get("code_b") or ""
        self._direction = config.get("direction") or "both"
        self._sync_watched = bool(config.get("sync_watched", True))
        self._conflict = config.get("conflict") or "keep"
        try:
            self._interval = max(5, int(config.get("interval") or 15))
        except (TypeError, ValueError):
            self._interval = 15
        self._notify = bool(config.get("notify", True))
        self._last_result = self.get_data("last_result")
        self._history = self.get_data("history") or []

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/fnvsync",
                "event": "PluginAction",
                "desc": "立即执行一次飞牛双机播放记录同步",
                "category": "插件命令",
                "data": {"action": "fnvsync_run"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/run",
                "endpoint": self.api_run,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即同步",
                "description": "手动触发一次双 NAS 播放记录同步",
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "同步状态",
                "description": "返回最近一次同步结果与历史",
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        if self._run_now:
            return [
                {
                    "id": "FnVsync.Once",
                    "name": "飞牛播放记录同步插件（立即运行一次）",
                    "trigger": DateTrigger(run_date=datetime.now() + timedelta(seconds=3)),
                    "func": self._run_once,
                    "kwargs": {},
                }
            ]
        return [
            {
                "id": "FnVsync.Sync",
                "name": "飞牛播放记录同步插件",
                "trigger": IntervalTrigger(minutes=self._interval),
                "func": self.sync,
                "kwargs": {},
            }
        ]

    def _run_once(self) -> None:
        """立即运行一次后，自动关闭一次性开关，恢复按间隔定时运行。"""
        try:
            self.sync()
        finally:
            self._run_now = False
            try:
                self.update_config({"run_now": False})
            except Exception as exc:
                logger.error(f"飞牛播放记录同步：关闭立即运行开关失败 - {exc}")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        def field(model: str, label: str, cols: int = 6, password: bool = False):
            component = "VTextField"
            props = {"model": model, "label": label, "variant": "underlined",
                     "density": "compact", "hideDetails": True}
            if password:
                props["type"] = "password"
            return {
                "component": "VCol",
                "props": {"cols": 12, "md": cols},
                "content": [{"component": component, "props": props}],
            }

        def select(model: str, label: str, items: List[dict], cols: int = 6):
            return {
                "component": "VCol",
                "props": {"cols": 12, "md": cols},
                "content": [{
                    "component": "VSelect",
                    "props": {"model": model, "label": label, "items": items,
                              "variant": "underlined", "density": "compact",
                              "hideDetails": True},
                }],
            }

        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "run_now",
                                              "label": "立即运行一次",
                                              "hint": "勾选并保存后马上同步一次，之后自动恢复按间隔运行"},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VDivider",
                        "props": {"class": "my-3"},
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VAlert",
                                    "props": {"type": "info", "variant": "tonal",
                                              "text": "NAS A 与 NAS B：两台飞牛影视的地址、账号、密码。地址格式如 https://192.168.1.10:5666，应用会自动补 /v。", "density": "compact"},
                                }],
                            },
                            field("host_a", "NAS A 地址", 12),
                            field("user_a", "NAS A 用户名", 6),
                            field("pass_a", "NAS A 密码", 6, password=True),
                            field("code_a", "NAS A 访问码（未开启留空）", 6),
                            field("host_b", "NAS B 地址", 12),
                            field("user_b", "NAS B 用户名", 6),
                            field("pass_b", "NAS B 密码", 6, password=True),
                            field("code_b", "NAS B 访问码（未开启留空）", 6),
                            {
                                "component": "VDivider",
                                "props": {"class": "my-3"},
                            },
                            select("direction", "同步方向", [
                                {"title": "双向同步（A ⇄ B）", "value": "both"},
                                {"title": "仅 A → B", "value": "a_to_b"},
                                {"title": "仅 B → A", "value": "b_to_a"},
                            ]),
                            select("conflict", "两边都改动时", [
                                {"title": "保留冲突，不覆盖", "value": "keep"},
                                {"title": "进度大的优先", "value": "progress"},
                                {"title": "以 A 为准", "value": "a"},
                                {"title": "以 B 为准", "value": "b"},
                            ]),
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "sync_watched",
                                              "label": "同步已看完标记"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "notify",
                                              "label": "同步完成后通知"},
                                }],
                            },
                            field("interval", "同步间隔（分钟，最小 5）", 6),
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "run_now": False,
            "host_a": "", "user_a": "", "pass_a": "", "code_a": "",
            "host_b": "", "user_b": "", "pass_b": "", "code_b": "",
            "direction": "both", "conflict": "keep", "sync_watched": True,
            "notify": True, "interval": 15,
        }

    def get_page(self) -> List[dict]:
        status = self._last_result or {}
        lines = []
        if self._last_time:
            lines.append(f"上次同步：{self._last_time}")
            lines.append(
                f"匹配 {status.get('total_pairs', 0)} 部 · "
                f"同步 {status.get('synced', 0)} · "
                f"冲突 {status.get('conflicts', 0)} · "
                f"模糊跳过 {status.get('ambiguous', 0)} · "
                f"失败 {status.get('failed', 0)}"
            )
        else:
            lines.append("尚未执行过同步。保存配置后可在服务中手动触发，或等待定时任务。")

        changes = status.get("changes") or []
        content = [
            {
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal",
                          "text": " ".join(lines) + "。手动同步：设定 → 服务中点运行，或发命令 /fnvsync",
                          "density": "compact"},
            },
        ]
        if changes:
            content.append({
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-3"},
                "content": [{
                    "component": "VCardText",
                    "content": [
                        {"component": "div", "props": {"class": "text-caption"},
                         "content": [str(line)]}
                        for line in changes[:30]
                    ],
                }],
            })
        return content

    # ---------- 同步执行 ----------

    def _build_clients(self) -> Tuple[Optional[FnClient], Optional[FnClient]]:
        if not all([self._host_a, self._user_a, self._pass_a,
                    self._host_b, self._user_b, self._pass_b]):
            logger.error("飞牛双机同步：两台 NAS 的地址、账号、密码必须填写完整")
            return None, None
        client_a = FnClient(self._host_a, self._user_a, self._pass_a,
                            self._code_a, logger=logger)
        client_b = FnClient(self._host_b, self._user_b, self._pass_b,
                            self._code_b, logger=logger)
        if not client_a.login():
            logger.error(f"飞牛双机同步：NAS A 登录失败 - {client_a.last_error}")
            client_a.close()
            return None, None
        if not client_b.login():
            logger.error(f"飞牛双机同步：NAS B 登录失败 - {client_b.last_error}")
            client_a.close()
            client_b.close()
            return None, None
        return client_a, client_b

    def sync(self, dry_run: bool = False) -> Optional[dict]:
        if not self._enabled:
            return None
        client_a = client_b = None
        with self._lock:
            try:
                client_a, client_b = self._build_clients()
                if client_a is None or client_b is None:
                    return None

                baseline = self.get_data("baseline") or {}
                matcher = MediaMatcher(logger=logger)
                direction = self._direction
                # 单向模式下，把对端客户端传成同一实例由引擎策略处理：
                # 这里通过替换 _apply 目标实现更稳妥，简化为按方向决定是否允许写入
                engine = SyncEngine(
                    client_a, client_b, matcher, baseline,
                    sync_watched=self._sync_watched,
                    conflict_strategy=self._conflict,
                    logger=logger,
                )

                if direction != "both":
                    self._limit_direction(engine, direction)

                result = engine.run(dry_run=dry_run)
                self._last_result = result
                self._last_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_data("last_result", result)
                self.save_data("baseline", baseline)

                record = dict(result)
                record["time"] = self._last_time
                self._history.insert(0, record)
                self._history = self._history[:50]
                self.save_data("history", self._history)

                message = (
                    f"飞牛双机同步完成：匹配 {result['total_pairs']} 部，"
                    f"同步 {result['synced']}，冲突 {result['conflicts']}，"
                    f"失败 {result['failed']}"
                )
                logger.info(message)
                if self._notify:
                    self.post_message(title="飞牛双机同步", text=message)
                return result
            except Exception as exc:
                logger.error(f"飞牛双机同步异常：{exc}")
                return None
            finally:
                try:
                    client_a.close()
                    client_b.close()
                except Exception:
                    pass

    def _limit_direction(self, engine: SyncEngine, direction: str) -> None:
        """单向模式下屏蔽反向写入。"""
        original_apply = engine._apply

        def guarded(target, source_state, base_state):
            if direction == "a_to_b" and target is not engine.client_a:
                return True
            if direction == "b_to_a" and target is not engine.client_b:
                return True
            return original_apply(target, source_state, base_state)

        engine._apply = guarded

    def api_run(self) -> dict:
        result = self.sync()
        return {"success": result is not None, "data": result}

    def api_status(self) -> dict:
        return {
            "success": True,
            "data": {
                "last_time": self._last_time,
                "last_result": self._last_result,
                "history": self._history[:20],
            },
        }

    def stop_service(self):
        pass
