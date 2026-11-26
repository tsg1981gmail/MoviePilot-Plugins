"""
飞牛影视双 NAS 播放记录同步插件（MoviePilot V2）

在两台飞牛影视之间同步相同影片的播放进度与已看完标记。
只处理两边都存在的影片，靠 IMDb / TMDB / 标题年份匹配，分集叠加季集号。
"""

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.log import logger
from app.plugins import _PluginBase

try:
    from .fnvsync_core import (
        FnClient, MediaMatcher, SyncEngine, normalize_title, resolve_secret,
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
    resolve_secret = _module.resolve_secret


def _fnv_log(level: str, message: str) -> None:
    """把 MoviePilot 日志对象适配成核心逻辑需要的可调用日志函数。"""
    text = str(message)
    lv = str(level or "INFO").upper()
    try:
        if lv in ("ERROR", "CRITICAL", "FATAL"):
            logger.error(text)
        elif lv in ("WARN", "WARNING"):
            logger.warning(text)
        else:
            logger.info(text)
    except Exception:
        pass


class FnVsync(_PluginBase):
    """飞牛影视双 NAS 播放记录同步。"""

    plugin_name = "飞牛播放记录同步插件"
    plugin_desc = "同步两台飞牛影视中相同影片的播放进度和已看完标记，支持双向。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.21"
    plugin_author = "田树刚"
    author_url = ""
    plugin_config_prefix = "fnvsync_"
    plugin_order = 80
    auth_level = 1

    _enabled = False
    _run_now = False
    _check_now = False
    _reset_baseline = False
    _trust_cert = False
    _last_result: Optional[dict] = None
    _last_dryrun: Optional[dict] = None
    _last_time = ""
    _conn_status: Optional[dict] = None
    _history: List[dict] = []
    _last_attempt: Optional[dict] = None
    _lock = threading.RLock()
    # init_plugin 收到的原始配置快照，用于 update_config 整份回写时保留全部字段
    _config_snapshot: Dict[str, Any] = {}

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
    _full_interval = 6
    _notify = True
    _login_mode = "auto"
    # 深度轮间隔（小时）：平时跳过顶层没变化的整棵树，每隔这么久完整比对一次兜底
    _deep_interval = 24
    # 保存的登录令牌最长复用多久（小时），超时主动重登，避免一直拿着过期令牌
    _token_ttl = 12

    def init_plugin(self, config: dict = None):
        config = config or {}
        # 原样保存一份配置快照：update_config 是整份覆盖，
        # 后续要改单个开关时必须基于这份快照回写，否则会把其他字段（地址、密码）清空
        self._config_snapshot = dict(config)
        self._enabled = bool(config.get("enabled"))
        self._run_now = bool(config.get("run_now"))
        self._check_now = bool(config.get("check_now"))
        self._reset_baseline = bool(config.get("reset_baseline"))
        self._trust_cert = bool(config.get("trust_cert"))
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
        try:
            self._full_interval = max(1, int(config.get("full_interval") or 6))
        except (TypeError, ValueError):
            self._full_interval = 6
        mode = str(config.get("login_mode") or "auto")
        self._login_mode = mode if mode in ("auto", "v1", "v2") else "auto"
        self._last_result = self.get_data("last_result")
        self._last_time = (self._last_result or {}).get("time") or ""
        self._history = self.get_data("history") or []
        # 旧版本把每次的全部变更都存进历史，单条能到几十 KB，这里统一截断
        for record in self._history:
            if isinstance(record, dict) and len(record.get("changes") or []) > 20:
                record["changes"] = record["changes"][:20]
        self._conn_status = self.get_data("conn_status")
        self._last_attempt = self.get_data("last_attempt")
        self._last_dryrun = self.get_data("last_dryrun")

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
                "path": "/syncall",
                "endpoint": self.api_run_full,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即全量扫描",
                "description": "忽略增量，完整扫描两台媒体库并同步一次",
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "同步状态",
                "description": "返回最近一次同步结果与历史",
            },
            {
                "path": "/test",
                "endpoint": self.api_test,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "检查连接",
                "description": "只登录两台 NAS 验证地址与账号密码，不同步播放记录",
            },
            {
                "path": "/dryrun",
                "endpoint": self.api_dryrun,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "试运行",
                "description": "完整比对两端但一条都不写，返回将要同步的清单",
            },
            {
                "path": "/export",
                "endpoint": self.api_export,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "导出配置与基线",
                "description": "导出同步基线、条目映射与配置（不含密码），换机时可直接导入",
            },
            {
                "path": "/import",
                "endpoint": self.api_import,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "导入配置与基线",
                "description": "导入 /export 导出的内容，免去重新全量扫描",
            },
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """返回本插件要注册的定时任务。

        定时任务必须始终返回，不能和「立即运行一次」互斥：
        MoviePilot 只在插件加载时调用一次本方法，勾一次一次性开关后如果只注册了
        一次性任务，那个任务执行完、开关自动关闭时也没有任何回调会重新注册定时任务，
        结果就是整天不再自动同步（实测踩过）。

        只有一个周期任务：全量扫描不再单独占一个 30 分钟的轮询任务，
        而是在增量任务里按「距上次全量多久」判断，到点这一轮直接跑全量。
        这样任务列表少一个，每天少 48 次纯空转唤醒，全量最多晚一个增量间隔触发。
        """
        services: List[Dict[str, Any]] = []
        if self._enabled:
            services.append({
                "id": "FnVsync.Sync",
                "name": "飞牛播放记录同步插件",
                "trigger": IntervalTrigger(minutes=self._interval),
                "func": self.sync,
                "kwargs": {},
            })
        if self._run_now and self._enabled:
            services.append({
                "id": "FnVsync.Once",
                "name": "飞牛播放记录同步插件（立即运行一次）",
                "trigger": DateTrigger(run_date=datetime.now() + timedelta(seconds=3)),
                "func": self._run_once,
                "kwargs": {},
            })
        # 连接检查只登录不同步，未启用插件时也允许执行，方便先验证地址与账号
        if self._check_now:
            services.append({
                "id": "FnVsync.Check",
                "name": "飞牛播放记录同步插件（检查连接）",
                "trigger": DateTrigger(run_date=datetime.now() + timedelta(seconds=2)),
                "func": self._check_once,
                "kwargs": {},
            })
        return services

    def _base_config(self) -> Dict[str, Any]:
        """基于配置快照拼出完整的配置字典，供整份回写使用。"""
        config = dict(getattr(self, "_config_snapshot", None) or {})
        config.update({
            "enabled": self._enabled,
            "host_a": self._host_a,
            "user_a": self._user_a,
            "pass_a": self._pass_a,
            "code_a": self._code_a,
            "host_b": self._host_b,
            "user_b": self._user_b,
            "pass_b": self._pass_b,
            "code_b": self._code_b,
            "direction": self._direction,
            "sync_watched": self._sync_watched,
            "conflict": self._conflict,
            "interval": self._interval,
            "full_interval": self._full_interval,
            "notify": self._notify,
            "login_mode": self._login_mode,
            "reset_baseline": self._reset_baseline,
            "trust_cert": self._trust_cert,
        })
        return config

    def _write_back_config(self) -> None:
        """把一次性开关关掉并整份回写配置。

        MoviePilot 的 update_config 是整份覆盖，只传开关会把地址、账号、密码一起清空，
        所以必须带全所有字段。
        """
        config = self._base_config()
        config["run_now"] = False
        config["check_now"] = False
        config["reset_baseline"] = False
        config["trust_cert"] = False
        self._reset_baseline = False
        self._trust_cert = False
        self._config_snapshot = dict(config)
        self.update_config(config)

    def _run_once(self) -> None:
        """立即运行一次后，自动关闭一次性开关，恢复按间隔定时运行。"""
        try:
            self.sync()
        finally:
            self._run_now = False
            try:
                self._write_back_config()
            except Exception as exc:
                logger.error(f"飞牛播放记录同步：关闭立即运行开关失败 - {exc}")

    def _check_once(self) -> None:
        """保存后只检查两台 NAS 能否登录，不读写播放记录。"""
        try:
            self.test_connection()
        finally:
            self._check_now = False
            try:
                self._write_back_config()
            except Exception as exc:
                logger.error(f"飞牛播放记录同步：关闭连接检查开关失败 - {exc}")

    def test_connection(self) -> Dict[str, Any]:
        """逐台登录验证，结果写日志并保存到插件数据。"""
        result: Dict[str, Any] = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        for key, name, host, user, password, code in (
            ("a", "NAS A", self._host_a, self._user_a, self._pass_a, self._code_a),
            ("b", "NAS B", self._host_b, self._user_b, self._pass_b, self._code_b),
        ):
            if not all([host, user, password]):
                item = {"ok": False, "host": host, "error": "地址、用户名或密码没有填全"}
            elif not resolve_secret(password):
                item = {"ok": False, "host": host,
                        "error": "密码为空：若用了 ${环境变量} 写法，请确认该变量已设置"}
            else:
                client = self._client(host, user, password, code, key)
                try:
                    ok = client.login()
                    item = {
                        "ok": ok,
                        "host": client.host,
                        "error": "" if ok else (client.last_error or "登录失败"),
                        "fingerprint": (client.learned_fingerprint or "")[:16],
                    }
                    if ok:
                        self._persist_client(key, client)
                except Exception as exc:
                    item = {"ok": False, "host": client.host, "error": str(exc)}
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass
            result[key] = item
            if item["ok"]:
                logger.info(f"飞牛连接检查：{name} 登录成功 - {item['host']}")
            else:
                logger.error(f"飞牛连接检查：{name} 登录失败 - {item['error']}")
        self._conn_status = result
        try:
            if result.get("a", {}).get("ok") and result.get("b", {}).get("ok"):
                self.save_data("login_block_until", "")
            self.save_data("conn_status", result)
        except Exception as exc:
            logger.error(f"飞牛连接检查：保存检查结果失败 - {exc}")
        return result

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        def field(model: str, label: str, cols: int = 6, password: bool = False,
                  hint: str = ""):
            component = "VTextField"
            props = {"model": model, "label": label, "variant": "underlined",
                     "density": "compact", "hideDetails": True}
            if password:
                props["type"] = "password"
            if hint:
                props["hint"] = hint
                props["persistentHint"] = True
                props["hideDetails"] = "auto"
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
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "run_now",
                                              "label": "立即运行一次",
                                              "hint": "勾选并保存后马上同步一次，之后自动恢复按间隔运行"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "check_now",
                                              "label": "保存后检查连接",
                                              "hint": "只登录两台 NAS 验证地址和账号密码，不同步数据；结果写在日志和插件页"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "reset_baseline",
                                              "label": "重置同步基线",
                                              "hint": "清空历史比对记录，下次运行按首次配对重新拉齐两端；勾选并保存后一次性生效"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "trust_cert",
                                              "label": "重新信任证书",
                                              "hint": "NAS 换了 HTTPS 证书导致指纹不一致、同步被拦时勾选一次；勾选并保存后一次性生效"},
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
                            field("pass_a", "NAS A 密码", 6, password=True,
                                  hint="掩码显示。不想明文落库时填 ${环境变量名}，"
                                       "在 MoviePilot 容器里设置该变量即可"),
                            field("code_a", "NAS A 访问码（未开启留空）", 6),
                            field("host_b", "NAS B 地址", 12),
                            field("user_b", "NAS B 用户名", 6),
                            field("pass_b", "NAS B 密码", 6, password=True,
                                  hint="掩码显示。不想明文落库时填 ${环境变量名}"),
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
                            field("interval", "增量检查间隔（分钟，最小 5）", 6),
                            field("full_interval", "全量扫描间隔（小时，最小 1）", 6),
                            select("login_mode", "登录方式", [
                                {"title": "自动（先试 v1，再试 v2）", "value": "auto"},
                                {"title": "只用 v1 明文密码", "value": "v1"},
                                {"title": "只用 v2 SHA256 密码", "value": "v2"},
                            ]),
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "run_now": False,
            "check_now": False,
            "reset_baseline": False,
            "trust_cert": False,
            "host_a": "", "user_a": "", "pass_a": "", "code_a": "",
            "host_b": "", "user_b": "", "pass_b": "", "code_b": "",
            "direction": "both", "conflict": "keep", "sync_watched": True,
            "notify": True, "interval": 15, "full_interval": 6, "login_mode": "auto",
        }

    def get_page(self) -> List[dict]:
        status = self._last_result or {}
        lines = []
        if self._last_time:
            mode = "全量扫描" if status.get("mode") == "full" else "增量检查"
            if status.get("deep"):
                mode += "（深度）"
            lines.append(f"上次{mode}：{self._last_time}")
            lines.append(
                f"匹配 {status.get('total_pairs', 0)} 部 · "
                f"同步 {status.get('synced', 0)} · "
                f"冲突 {status.get('conflicts', 0)} · "
                f"模糊跳过 {status.get('ambiguous', 0)} · "
                f"失败 {status.get('failed', 0)}"
            )
            # 定时服务如果没注册，这里能第一时间看出来，保存一次配置即可重新注册
            try:
                gap_hours = (datetime.now() - datetime.strptime(
                    self._last_time, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
                if gap_hours > max(1.0, self._interval * 3 / 60):
                    lines.append(
                        f"注意：距上次同步已 {gap_hours:.1f} 小时，"
                        f"若长时间不再自动运行，请在本页点一次「保存」重新注册定时服务"
                    )
            except (TypeError, ValueError):
                pass
            lines.append(self._cost_text(status))
        else:
            lines.append("尚未执行过同步。保存配置后可在服务中手动触发，或等待定时任务。")

        attempt = self._last_attempt or {}
        if attempt.get("time") and not str(attempt.get("result", "")).startswith(
                ("完成", "试运行完成")):
            lines.append(
                f"最近一次触发 {attempt['time']} 未执行：{attempt.get('result') or '原因未知'}"
            )

        verify = status.get("verify") or {}
        if verify.get("mismatch"):
            lines.append(
                f"写后回读有 {verify['mismatch']} 条不一致，"
                f"对端可能没真正接受写入：{'；'.join(verify.get('detail') or [])}"
            )

        content = []
        conn = self._conn_status or {}
        if conn.get("time"):
            parts = []
            for key, name in (("a", "NAS A"), ("b", "NAS B")):
                item = conn.get(key) or {}
                if item.get("ok"):
                    parts.append(f"{name} 连接正常")
                else:
                    parts.append(f"{name} 连不上：{item.get('error') or '未知原因'}")
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "success" if all((conn.get(k) or {}).get("ok") for k in ("a", "b")) else "error",
                    "variant": "tonal", "density": "compact",
                    "text": f"连接检查 {conn['time']}：" + "；".join(parts),
                },
            })
        content.append(
            {
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal",
                          "text": "；".join(lines) + "。手动同步：设定 → 服务中点运行，或发命令 /fnvsync",
                          "density": "compact"},
            }
        )

        items = status.get("items") or []
        if items:
            content.append(self._changes_card(
                "上次同步的变更（显示片名，最多 15 条）", items, "text-caption"))

        dry = self._last_dryrun or {}
        if dry.get("time"):
            dry_items = dry.get("items") or []
            content.append(self._changes_card(
                f"最近一次试运行 {dry['time']}：预计同步 "
                f"{dry.get('synced', 0)} 条，未写入任何数据",
                dry_items, "text-caption font-italic"))
        return content

    @staticmethod
    def _cost_text(status: dict) -> str:
        """把一轮的请求开销压缩成一句话。"""
        stats = status.get("stats") or {}
        if not stats.get("requests"):
            return ""
        parts = [f"开销：{stats['requests']} 次请求"]
        if stats.get("kb") is not None:
            parts.append(f"{stats['kb']} KB")
        if status.get("elapsed"):
            parts.append(f"{status['elapsed']} 秒")
        if stats.get("ms"):
            parts.append(f"其中网络 {stats['ms']} 毫秒")
        if stats.get("children_requests"):
            parts.append(f"其中展开分集 {stats['children_requests']} 次")
        if stats.get("skipped_expand"):
            parts.append(f"跳过未变化的剧集树 {stats['skipped_expand']} 棵")
        if stats.get("reused_token"):
            parts.append("复用了登录令牌")
        return " · ".join(parts)

    @staticmethod
    def _changes_card(title: str, items: List[dict], text_class: str) -> dict:
        """把变更清单排成三列表格：片名 / 方向 / 进度。"""
        def cell(text: str, cols: int) -> dict:
            return {"component": "VCol", "props": {"cols": cols, "class": text_class},
                    "content": [str(text)]}

        def row(parts: Tuple[str, str, str]) -> dict:
            return {"component": "VRow", "props": {"class": "py-0"},
                    "content": [cell(parts[0], 7), cell(parts[1], 3), cell(parts[2], 2)]}

        rows = [{"component": "div", "props": {"class": "text-subtitle-2 mb-2"},
                 "content": [title]}]
        if not items:
            rows.append({"component": "div", "props": {"class": text_class},
                         "content": ["两端状态一致，没有需要写入的条目。"]})
            return {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-3"},
                "content": [{"component": "VCardText", "content": rows}],
            }
        rows.append(row(("片名", "方向", "进度")))
        for item in items[:15]:
            ts = int(item.get("ts") or 0)
            progress = f"{ts // 60} 分 {ts % 60} 秒" if ts > 0 else "标记状态"
            rows.append(row((item.get("title") or "(无标题)",
                             item.get("direction") or "", progress)))
        return {
            "component": "VCard",
            "props": {"variant": "tonal", "class": "mb-3"},
            "content": [{"component": "VCardText", "content": rows}],
        }

    # ---------- 同步执行 ----------

    def _client(self, host: str, user: str, password: str, code: str,
                tag: str = "") -> FnClient:
        """构造客户端，带上上次保存的登录令牌与证书指纹。"""
        return FnClient(
            host, user, password, code, logger=_fnv_log,
            login_mode=self._login_mode,
            token=self._saved_token(tag, host, user),
            fingerprint=self._saved_fingerprint(tag, host),
            trust_cert=self._trust_cert,
        )

    @staticmethod
    def _norm_host(host: str) -> str:
        """统一地址写法：客户端会补 /v，配置里通常没有，比对前先拉齐。"""
        text = str(host or "").strip().rstrip("/")
        return text[:-2] if text.endswith("/v") else text

    def _saved_token(self, tag: str, host: str, user: str) -> str:
        """取可复用的登录令牌；换了地址或账号就当没有。"""
        if not tag:
            return ""
        record = (self.get_data("tokens") or {}).get(tag) or {}
        if (self._norm_host(record.get("host")) != self._norm_host(host)
                or record.get("user") != user):
            return ""
        saved_at = record.get("ts") or 0
        if not saved_at or (time.time() - float(saved_at)) > self._token_ttl * 3600:
            return ""
        return record.get("token") or ""

    def _saved_fingerprint(self, tag: str, host: str) -> str:
        if not tag:
            return ""
        record = (self.get_data("tls_fp") or {}).get(tag) or {}
        if self._norm_host(record.get("host")) != self._norm_host(host):
            return ""
        return record.get("fp") or ""

    def _persist_client(self, tag: str, client: FnClient) -> None:
        """把令牌与证书指纹存下来，下一轮就不用重新登录、也能比对证书。

        只在真的换了新令牌或新指纹时才写存储：复用令牌的那一轮写进去等于没变，
        但每次 save_data 都要整份重写插件数据，白白增加开销。
        """
        if not tag or client is None:
            return
        try:
            if client.token:
                tokens = dict(self.get_data("tokens") or {})
                stored = tokens.get(tag) or {}
                if stored.get("token") != client.token:
                    tokens[tag] = {"host": self._norm_host(client.host),
                                   "user": client.username,
                                   "token": client.token, "ts": time.time()}
                    self.save_data("tokens", tokens)
            if client.learned_fingerprint:
                fps = dict(self.get_data("tls_fp") or {})
                stored_fp = fps.get(tag) or {}
                if stored_fp.get("fp") != client.learned_fingerprint:
                    fps[tag] = {"host": self._norm_host(client.host),
                                "fp": client.learned_fingerprint}
                    self.save_data("tls_fp", fps)
        except Exception as exc:
            logger.error(f"飞牛双机同步：保存登录令牌失败 - {exc}")

    def _login_blocked(self) -> str:
        """登录被拒后暂停一段时间的截止时间，避免反复失败把账号彻底锁死。"""
        until = self.get_data("login_block_until") or ""
        if until and until > datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
            return until
        if until:
            self.save_data("login_block_until", "")
        return ""

    def _mark_login_blocked(self, error: str) -> None:
        if "-15" not in str(error):
            return
        until = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        self.save_data("login_block_until", until)
        logger.error(
            f"飞牛双机同步：账号密码被拒，暂停登录到 {until}，"
            f"期间不再重试，避免连续失败把账号锁死。改好配置后勾「保存后检查连接」可立即单独验证"
        )

    def _build_clients(self) -> Tuple[Optional[FnClient], Optional[FnClient]]:
        if not all([self._host_a, self._user_a, self._pass_a,
                    self._host_b, self._user_b, self._pass_b]):
            logger.error("飞牛双机同步：两台 NAS 的地址、账号、密码必须填写完整")
            return None, None
        if not all([resolve_secret(self._pass_a), resolve_secret(self._pass_b)]):
            logger.error(
                "飞牛双机同步：密码为空 —— 若用的是 ${环境变量} 写法，"
                "请确认该环境变量已经在 MoviePilot 容器里设置"
            )
            return None, None
        client_a = self._client(self._host_a, self._user_a, self._pass_a,
                                self._code_a, "a")
        client_b = self._client(self._host_b, self._user_b, self._pass_b,
                                self._code_b, "b")
        if not client_a.login():
            logger.error(f"飞牛双机同步：NAS A 登录失败 - {client_a.last_error}")
            self._mark_login_blocked(client_a.last_error)
            client_a.close()
            return None, None
        # 登录成功后立刻存令牌，后面就算本轮出错，下一轮也能直接复用
        self._persist_client("a", client_a)
        if not client_b.login():
            logger.error(f"飞牛双机同步：NAS B 登录失败 - {client_b.last_error}")
            self._mark_login_blocked(client_b.last_error)
            client_a.close()
            client_b.close()
            return None, None
        self._persist_client("b", client_b)
        return client_a, client_b

    def _load_guid_map(self) -> Dict[str, Dict[str, str]]:
        """条目映射只存 A→B 单向，运行时装成双向，省一半存储。"""
        forward = (self.get_data("guid_map") or {}).get("a_to_b") or {}
        return {"a": dict(forward), "b": {v: k for k, v in forward.items()}}

    def _save_guid_map(self, mapping: Dict[str, Dict[str, str]]) -> None:
        """合并写回条目映射，不能整份覆盖。

        全量轮里被跳过展开的剧集树不会重新登记分集映射，
        如果整份覆盖，增量轮就再也找不到这些分集的对端，反而每轮都判定「需要全量」。
        """
        forward = dict((self.get_data("guid_map") or {}).get("a_to_b") or {})
        forward.update(mapping.get("a") or {})
        self.save_data("guid_map", {"a_to_b": forward})

    def _run_full(self) -> Optional[dict]:
        """低频全量扫描：补齐「已看完」标记与新片配对。"""
        return self.sync(full=True)

    def _hours_since(self, key: str) -> Optional[float]:
        """读某个时间戳字段距今多少小时；没有或格式不对返回 None。"""
        raw = self.get_data(key) or ""
        if not raw:
            return None
        try:
            return (datetime.now() - datetime.strptime(
                raw, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600.0
        except (TypeError, ValueError):
            return None

    def _save_unmapped(self, mapping: Dict[str, int]) -> None:
        """保存「配不上对」的计数，只留最近的若干条，避免无限增长。"""
        if not mapping:
            return
        try:
            data = mapping
            if len(data) > 300:
                data = dict(list(data.items())[-300:])
            self.save_data("unmapped", data)
        except Exception as exc:
            logger.error(f"飞牛双机同步：保存未配对记录失败 - {exc}")

    def _full_due(self) -> bool:
        """全量扫描是否到期。

        用「距上次全量多久」自己算，不用固定间隔的触发器：
        那样每次重启 MoviePilot 都会把计时清零，重启频繁就永远等不到全量。
        """
        gap = self._hours_since("last_full_time")
        if gap is None:
            return True
        return gap >= self._full_interval

    def _deep_due(self) -> bool:
        """深度轮是否到期。

        平时为了省请求会跳过「顶层没变化」的整棵树；深度轮不做这个判断，
        逐集完整比对一次，兜住分集层的手动改动。默认 24 小时一次。
        """
        gap = self._hours_since("last_deep_time")
        if gap is None:
            return True
        return gap >= self._deep_interval

    def _attempt_done(self, attempt: dict, reason: str) -> None:
        """记下这一次被调用但没真正执行的原因，便于排查「为什么不自动同步」。"""
        attempt["result"] = reason
        self._last_attempt = attempt
        try:
            self.save_data("last_attempt", attempt)
        except Exception:
            pass

    def sync(self, dry_run: bool = False, full: bool = False) -> Optional[dict]:
        started = time.time()
        attempt = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "全量" if full else "增量",
            "enabled": bool(self._enabled),
        }
        if not self._enabled:
            self._attempt_done(attempt, "插件未启用，未执行")
            return None
        blocked = self._login_blocked()
        if blocked:
            logger.info(f"飞牛双机同步：登录被拒后的冷却期内，{blocked} 之后再试，本次跳过")
            self._attempt_done(attempt, f"登录冷却中，到 {blocked} 才恢复")
            return None
        client_a = client_b = None
        reset_baseline = bool(self._reset_baseline)
        with self._lock:
            try:
                client_a, client_b = self._build_clients()
                if client_a is None or client_b is None:
                    self._attempt_done(attempt, "两台 NAS 的地址/账号/密码不完整或登录失败")
                    return None

                if reset_baseline:
                    logger.info("飞牛双机同步：按配置重置同步基线，本轮按首次配对重新拉齐")
                    baseline = {}
                    self._reset_baseline = False
                    full = True
                    # 映射、指纹、深度轮时间都是按旧配对建的，一起清掉
                    self.save_data("baseline", {})
                    self.save_data("guid_map", {})
                    self.save_data("play_snapshot", {})
                    self.save_data("last_full_time", "")
                    self.save_data("last_deep_time", "")
                    self.save_data("unmapped", {})
                else:
                    baseline = self.get_data("baseline") or {}

                # 全量到期就在这一轮直接跑，不再靠独立的轮询任务空转
                if not full and self._full_due():
                    full = True
                    logger.info(
                        "飞牛双机同步：距上次全量已超过配置间隔 "
                        f"{self._full_interval} 小时，本轮改跑全量扫描")
                deep = bool(full and self._deep_due())
                attempt["mode"] = "全量" if full else "增量"

                engine = SyncEngine(
                    client_a, client_b, MediaMatcher(logger=_fnv_log), baseline,
                    sync_watched=self._sync_watched,
                    conflict_strategy=self._conflict,
                    logger=_fnv_log,
                    direction=self._direction,
                    deep=deep,
                    unmapped=self.get_data("unmapped") or {},
                )

                if not full:
                    snapshot = self.get_data("play_snapshot") or {}
                    result, new_snapshot, need_full = engine.run_incremental(
                        snapshot, self._load_guid_map(), dry_run)
                    if not need_full:
                        if result["synced"] or result["failed"] or result["skipped"]:
                            if not dry_run:
                                self.save_data("play_snapshot", new_snapshot)
                        return self._wrap_result(result, engine, baseline,
                                                 attempt, dry_run, started)
                    logger.info("飞牛双机同步：出现尚未配对的新条目，本轮改跑全量扫描")
                    # 这条是映射表里没有的新条目，很可能藏在被跳过展开的剧集树里；
                    # 不强制深度展开就会「扫了全量却没扫到它」，下一轮又重复触发
                    engine.deep = True

                result = engine.run(dry_run=dry_run)
                result["mode"] = "full"
                if not dry_run:
                    self.save_data("play_snapshot", engine.play_snapshot)
                    self._save_guid_map(engine.guid_map)
                return self._wrap_result(result, engine, baseline, attempt,
                                         dry_run, started, deep=deep)
            except Exception as exc:
                logger.error(f"飞牛双机同步异常：{exc}")
                self._attempt_done(attempt, f"执行异常：{exc}")
                return None
            finally:
                try:
                    client_a.close()
                    client_b.close()
                except Exception:
                    pass
                if reset_baseline:
                    # 重置是勾选生效的一次性开关，用完立刻落盘关掉，避免每次运行都清基线
                    try:
                        self._write_back_config()
                    except Exception as exc:
                        logger.error(f"飞牛播放记录同步：关闭重置基线开关失败 - {exc}")

    def _wrap_result(self, result: dict, engine: SyncEngine, baseline: dict,
                     attempt: Optional[dict], dry_run: bool, started: float,
                     deep: bool = False) -> dict:
        """补上写后回读、请求统计与耗时，然后统一收尾。"""
        if not dry_run:
            verify = engine.verify_samples(2)
            if verify.get("checked"):
                result["verify"] = verify
            self._save_unmapped(engine.unmapped)
        # 首次全量可能有几百条变更，全量存下来太占地方，只留足够页面展示的量
        result["items"] = (result.get("items") or [])[:20]
        result["changes"] = (result.get("changes") or [])[:30]
        result["stats"] = engine.collect_stats()
        result["elapsed"] = round(time.time() - started, 2)
        # 以引擎实际状态为准：新条目缺失映射时会被强制升级成深度轮
        result["deep"] = bool(engine.deep)
        result["dry_run"] = bool(dry_run)
        return self._finish(result, engine, baseline, attempt)

    def _log_summary(self, result: dict) -> None:
        """每次运行打一行中文摘要；细分开销只在调试级输出，免得刷屏看不懂。"""
        stats = result.get("stats") or {}
        mode = result.get("mode") or "incremental"
        if mode == "full":
            mode_text = "全量深度核对" if result.get("deep") else "全量核对"
        else:
            mode_text = "增量核对"

        parts = [f"配对 {int(result.get('total_pairs') or 0)} 部",
                 f"同步 {int(result.get('synced') or 0)} 条"]
        for label, key in (("跳过", "skipped"), ("冲突", "conflicts"),
                           ("失败", "failed")):
            val = int(result.get(key) or 0)
            if val:
                parts.append(f"{label} {val} 条")
        elapsed = float(result.get("elapsed") or 0)
        parts.append(f"用时 {elapsed:.1f} 秒")
        requests = int(stats.get("requests") or 0)
        if requests:
            parts.append(f"共 {requests} 次请求")
        # 试运行时 _finish 里已单独打过一句，这里不重复刷一行
        if not result.get("dry_run"):
            try:
                logger.info(f"飞牛同步完成（{mode_text}）：" + "，".join(parts))
            except Exception:
                pass

        detail = []
        kb = stats.get("kb")
        if kb:
            detail.append(f"数据量 {kb} KB")
        net_ms = int(stats.get("ms") or 0)
        if net_ms:
            detail.append(f"两端网络等待合计 {net_ms / 1000.0:.1f} 秒")
        detail.append(f"重新登录 {int(stats.get('login') or 0)} 次、"
                      f"复用上次令牌 {int(stats.get('reused_token') or 0)} 次")
        detail.append(f"展开剧集分集 {int(stats.get('children_requests') or 0)} 次、"
                      f"按指纹跳过整部 {int(stats.get('skipped_expand') or 0)} 次")
        verify = result.get("verify") or {}
        if verify.get("checked"):
            detail.append(f"写完抽样回读，不一致 "
                          f"{int(verify.get('mismatch') or 0)} 条")
        errors = int(stats.get("errors") or 0)
        if errors:
            detail.append(f"接口报错 {errors} 次")
        try:
            logger.debug("飞牛同步明细：" + "；".join(detail))
        except Exception:
            pass

    def _finish(self, result: dict, engine: SyncEngine, baseline: dict,
                attempt: Optional[dict] = None) -> dict:
        """统一收尾：落盘、历史、通知。没有写入就不重复写存储。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if result.get("dry_run"):
            # 试运行只出差异清单，不动基线、不动「上次同步时间」，免得把真实进度盖掉
            payload = dict(result)
            payload["time"] = now
            self._last_dryrun = payload
            try:
                self.save_data("last_dryrun", payload)
            except Exception as exc:
                logger.error(f"飞牛播放记录同步：保存试运行结果失败 - {exc}")
            self._log_summary(payload)
            if attempt is not None:
                attempt["mode"] = "试运行"
                attempt["result"] = (
                    f"试运行完成：预计同步 {result['synced']}，失败 {result['failed']}")
                self._last_attempt = attempt
                try:
                    self.save_data("last_attempt", attempt)
                except Exception:
                    pass
            logger.info(
                f"飞牛双机同步试运行：匹配 {result['total_pairs']} 部，"
                f"预计同步 {result['synced']}，冲突 {result['conflicts']}，"
                f"失败 {result['failed']}（未写入任何数据）"
            )
            return result

        self._last_result = result
        self._last_time = now
        # 时间戳跟着结果一起存，重载插件后页面不会又变回「尚未执行过同步」
        result["time"] = now
        self.save_data("last_result", result)
        if getattr(engine, "baseline_dirty", False):
            self.save_data("baseline", baseline)

        if result.get("mode") == "full":
            self.save_data("last_full_time", self._last_time)
            if result.get("deep"):
                self.save_data("last_deep_time", self._last_time)

        record = dict(result)
        record["time"] = self._last_time
        record["changes"] = (result.get("changes") or [])[:20]
        record["items"] = (result.get("items") or [])[:20]
        self._history.insert(0, record)
        self._history = self._history[:20]
        self.save_data("history", self._history)

        self._log_summary(result)

        mode = "全量" if result.get("mode") == "full" else "增量"
        message = (
            f"飞牛双机同步完成（{mode}）：匹配 {result['total_pairs']} 部，"
            f"同步 {result['synced']}，冲突 {result['conflicts']}，失败 {result['failed']}"
        )
        if attempt is not None:
            attempt["result"] = f"完成：同步 {result['synced']}，失败 {result['failed']}"
            self._last_attempt = attempt
            try:
                self.save_data("last_attempt", attempt)
            except Exception:
                pass
        logger.info(message)
        # 没有实际写入就不发通知，避免每轮都打扰
        if self._notify and (result.get("synced") or result.get("failed")):
            self.post_message(title="飞牛双机同步", text=message)
        return result

    def api_run(self) -> dict:
        """立即同步：有映射时走增量，出现未配对的新条目会自动转全量。"""
        result = self.sync()
        return {"success": result is not None, "data": result}

    def api_run_full(self) -> dict:
        """强制完整扫描一次，用于补「已看完」标记或大改刮削后重新对齐。"""
        result = self.sync(full=True)
        return {"success": result is not None, "data": result}

    def api_test(self) -> dict:
        result = self.test_connection()
        ok = bool(result.get("a", {}).get("ok") and result.get("b", {}).get("ok"))
        return {"success": ok, "data": result}

    def api_dryrun(self) -> dict:
        """完整比对但不写：用来在看不清风险时先看清单。"""
        result = self.sync(dry_run=True)
        if result is None:
            return {"success": False, "data": {"error": self._last_attempt or "试运行未执行"}}
        return {"success": True, "data": result}

    def api_export(self) -> dict:
        """导出配置与基线，密码一律不导出。"""
        config = dict(self._config_snapshot or {})
        for key in ("pass_a", "pass_b"):
            config.pop(key, None)
        return {
            "success": True,
            "data": {
                "plugin": "FnVsync",
                "version": self.plugin_version,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "config": config,
                "baseline": self.get_data("baseline") or {},
                "guid_map": self.get_data("guid_map") or {},
                "play_snapshot": self.get_data("play_snapshot") or {},
            },
        }

    def api_import(self, payload: Dict[str, Any] = None, **kwargs) -> dict:
        """导入基线，省掉首次全量重新配对；配置只导不含密码的那部分。"""
        data = payload if isinstance(payload, dict) else None
        if data is None and kwargs:
            # 有的版本把请求体直接展开成关键字参数传进来
            inner = kwargs.get("payload")
            data = inner if isinstance(inner, dict) else kwargs
        if not isinstance(data, dict) or data.get("plugin") != "FnVsync":
            return {"success": False, "data": {"error": "不是本插件导出的内容"}}
        written = []
        for key in ("baseline", "guid_map", "play_snapshot"):
            value = data.get(key)
            if isinstance(value, dict) and value:
                self.save_data(key, value)
                written.append(key)
        config = data.get("config") or {}
        if isinstance(config, dict) and config:
            merged = dict(self._config_snapshot or {})
            # 密码不跟着导入，避免把对端的密码写进来
            for key, value in config.items():
                if key in ("pass_a", "pass_b"):
                    continue
                merged[key] = value
            try:
                self.update_config(merged)
                written.append("config")
            except Exception as exc:
                logger.error(f"飞牛播放记录同步：导入配置失败 - {exc}")
        logger.info(f"飞牛播放记录同步：已导入 {', '.join(written) or '空内容'}")
        return {"success": bool(written), "data": {"imported": written}}

    def api_status(self) -> dict:
        return {
            "success": True,
            "data": {
                "last_time": self._last_time,
                "last_result": self._last_result,
                "last_dryrun": self._last_dryrun,
                "last_attempt": self._last_attempt,
                "history": self._history[:20],
                "full_interval": self._full_interval,
                "deep_interval": self._deep_interval,
                "hours_since_full": self._hours_since("last_full_time"),
                "hours_since_deep": self._hours_since("last_deep_time"),
            },
        }

    def stop_service(self):
        pass
