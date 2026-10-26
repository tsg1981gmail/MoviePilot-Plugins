import copy
import re
import threading
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable, List, Optional
from zoneinfo import ZoneInfo

from .runtime import (
    SUPPORTED_DOWNLOADERS,
    downloader_key,
    normalize_torrent,
    parse_schedule_time,
    schedule_field,
    task_eligible,
)


PLAN_FIELD_PATTERN = re.compile(
    r"^schedule_(?P<key>[0-9a-f]{12})_(?P<field>start_at|pause_at)$"
)


def _result(
        plan: dict,
        *,
        success: bool,
        affected: int,
        message: str,
        executed_at: datetime,
) -> dict:
    """构建计划执行结果。"""
    return {
        "key": plan["key"],
        "downloader": plan.get("name") or "",
        "type": plan.get("type") or "",
        "action": plan["action"],
        "scheduled_at": plan["scheduled_text"],
        "executed_at": executed_at.isoformat(timespec="seconds"),
        "success": success,
        "affected": affected,
        "message": message,
    }


class DownloaderScheduleService:
    """管理下载器一次性计划并执行到期动作。"""

    def __init__(
            self,
            helper: Any,
            config: dict,
            registry: dict,
            results: dict,
            now_fn: Callable[[], datetime],
            timezone: ZoneInfo,
            persist_config: Callable[[dict], None],
            save_registry: Callable[[dict], None],
            save_results: Callable[[dict], None],
    ):
        """保存运行依赖和持久化回调。"""
        self.helper = helper
        self.config = config
        self.registry = registry if isinstance(registry, dict) else {}
        self.results = results if isinstance(results, dict) else {}
        self.now_fn = now_fn
        self.timezone = timezone
        self.persist_config = persist_config
        self.save_registry = save_registry
        self.save_results = save_results
        self.lock = threading.RLock()
        self._duplicate_keys = set()

    def _now(self) -> datetime:
        """返回带时区的当前时间。"""
        now = self.now_fn()
        if now.tzinfo is None:
            return now.replace(tzinfo=self.timezone)
        return now.astimezone(self.timezone)

    def refresh_registry(self, services: Optional[Mapping] = None) -> dict:
        """刷新当前下载器名称快照。"""
        services = services if services is not None else self.helper.get_services()
        services = services or {}
        pairs = Counter()
        current_keys = set()

        if isinstance(services, Mapping):
            iterable = services.items()
        else:
            iterable = ((None, service) for service in services)

        for service_key, service in iterable:
            name = str(getattr(service, "name", "") or service_key or "").strip()
            downloader_type = str(getattr(service, "type", "") or "").strip().lower()
            if not name or downloader_type not in SUPPORTED_DOWNLOADERS:
                continue
            pair = (downloader_type, name)
            pairs[pair] += 1
            key = downloader_key(downloader_type, name)
            current_keys.add(key)
            self.registry[key] = {
                "name": name,
                "type": downloader_type,
            }

        self._duplicate_keys = {
            downloader_key(downloader_type, name)
            for (downloader_type, name), count in pairs.items()
            if count > 1
        }
        self.save_registry(self.registry)
        return self.registry

    def list_plans(self) -> List[dict]:
        """列出合法、冲突和遗留计划。"""
        plans = []
        for field, raw_value in self.config.items():
            if not isinstance(field, str):
                continue
            match = PLAN_FIELD_PATTERN.match(field)
            if not match:
                continue
            if not str(raw_value or "").strip():
                continue
            key = match.group("key")
            action = "start" if match.group("field") == "start_at" else "stop"
            snapshot = self.registry.get(key) or {}
            name = str(snapshot.get("name") or "")
            downloader_type = str(snapshot.get("type") or "").lower()
            scheduled_at = parse_schedule_time(raw_value, self.timezone)
            error = ""
            if not snapshot:
                error = "缺少下载器快照"
            elif downloader_type not in SUPPORTED_DOWNLOADERS:
                error = "下载器类型不受支持"
            elif key in self._duplicate_keys:
                error = "存在重复的下载器类型和名称"
            elif scheduled_at is None:
                error = "计划时间格式无效"

            plans.append({
                "key": key,
                "name": name,
                "type": downloader_type,
                "action": action,
                "field": field,
                "raw_value": str(raw_value or ""),
                "scheduled_at": scheduled_at,
                "scheduled_text": (
                    scheduled_at.strftime("%Y-%m-%dT%H:%M")
                    if scheduled_at else str(raw_value or "")
                ),
                "error": error,
            })

        by_key = {}
        for plan in plans:
            by_key.setdefault(plan["key"], []).append(plan)
        for key_plans in by_key.values():
            start = next(
                (plan for plan in key_plans if plan["action"] == "start"),
                None,
            )
            stop = next(
                (plan for plan in key_plans if plan["action"] == "stop"),
                None,
            )
            if (
                    start
                    and stop
                    and start["scheduled_at"]
                    and start["scheduled_at"] == stop["scheduled_at"]
            ):
                start["error"] = "开始和暂停时间不能相同"
                stop["error"] = "开始和暂停时间不能相同"

        plans.sort(key=lambda plan: (
            plan["scheduled_at"] or datetime.max.replace(tzinfo=self.timezone),
            plan["key"],
            plan["action"],
        ))
        return plans

    def due_plans(self, now: Optional[datetime] = None) -> List[dict]:
        """返回到期且合法的计划。"""
        now = now or self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.timezone)
        else:
            now = now.astimezone(self.timezone)
        return [
            plan for plan in self.list_plans()
            if not plan["error"]
            and plan["scheduled_at"]
            and plan["scheduled_at"] <= now
            and not self._already_completed(plan)
        ]

    def execute_plan(self, plan: dict) -> dict:
        """执行单个计划并返回结构化结果。"""
        executed_at = self._now()
        if plan.get("error"):
            result = _result(
                plan,
                success=False,
                affected=0,
                message=plan["error"],
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        try:
            service = self.helper.get_service(plan["name"])
        except Exception as error:
            service = None
            service_error = str(error)
        else:
            service_error = ""
        if not service:
            result = _result(
                plan,
                success=False,
                affected=0,
                message=f"下载器不存在或未启用：{service_error or plan['name']}",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        current_type = str(getattr(service, "type", "") or "").lower()
        if current_type != plan["type"]:
            result = _result(
                plan,
                success=False,
                affected=0,
                message="下载器类型与计划快照不一致",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        instance = getattr(service, "instance", None)
        if instance is None:
            result = _result(
                plan,
                success=False,
                affected=0,
                message="下载器实例不可用",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        try:
            if instance.is_inactive():
                result = _result(
                    plan,
                    success=False,
                    affected=0,
                    message="下载器未连接",
                    executed_at=executed_at,
                )
                self._store_result(result)
                return result
            query_result = instance.get_torrents()
        except Exception as error:
            result = _result(
                plan,
                success=False,
                affected=0,
                message=f"查询任务失败：{error}",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        if not isinstance(query_result, tuple) or len(query_result) != 2:
            result = _result(
                plan,
                success=False,
                affected=0,
                message="查询任务失败：下载器返回格式无效",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        torrents, query_error = query_result
        if query_error:
            result = _result(
                plan,
                success=False,
                affected=0,
                message="查询任务失败",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        hashes = []
        seen = set()
        for torrent in torrents or []:
            normalized = normalize_torrent(torrent, plan["type"])
            if (
                    normalized
                    and task_eligible(normalized, plan["action"])
                    and normalized["hash"] not in seen
            ):
                hashes.append(normalized["hash"])
                seen.add(normalized["hash"])

        if not hashes:
            result = _result(
                plan,
                success=True,
                affected=0,
                message="已执行，0 个任务",
                executed_at=executed_at,
            )
            self._complete_plan(plan, result)
            return result

        method_name = (
            "start_torrents" if plan["action"] == "start"
            else "stop_torrents"
        )
        method = getattr(instance, method_name, None)
        if not callable(method):
            result = _result(
                plan,
                success=False,
                affected=0,
                message=f"下载器不支持 {method_name}",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        try:
            succeeded = bool(method(ids=hashes))
        except Exception as error:
            result = _result(
                plan,
                success=False,
                affected=0,
                message=f"执行任务动作失败：{error}",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        if not succeeded:
            result = _result(
                plan,
                success=False,
                affected=0,
                message="下载器执行任务动作失败",
                executed_at=executed_at,
            )
            self._store_result(result)
            return result

        action_text = "开始" if plan["action"] == "start" else "暂停"
        result = _result(
            plan,
            success=True,
            affected=len(hashes),
            message=f"已{action_text} {len(hashes)} 个任务",
            executed_at=executed_at,
        )
        self._complete_plan(plan, result)
        return result

    def run_due(self, now: Optional[datetime] = None) -> List[dict]:
        """依次执行所有到期计划。"""
        with self.lock:
            results = []
            for plan in self.due_plans(now=now):
                results.append(self.execute_plan(plan))
            return results

    def _store_result(self, result: dict) -> None:
        """按下载器和动作保存结果。"""
        key_results = self.results.setdefault(result["key"], {})
        key_results[result["action"]] = copy.deepcopy(result)
        try:
            self.save_results(self.results)
        except Exception:
            pass

    def _complete_plan(self, plan: dict, result: dict) -> None:
        """持久化成功结果并清空计划字段。"""
        field = plan["field"]
        old_value = self.config.get(field)
        self._store_result(result)
        self.config.pop(field, None)
        try:
            self.persist_config(self.config)
        except Exception as error:
            if old_value is not None:
                self.config[field] = old_value
            result["message"] = (
                f"{result['message']}；计划字段清理失败：{error}"
            )
            self._store_result(result)

    def _already_completed(self, plan: dict) -> bool:
        """判断当前计划时间是否已有成功执行结果。"""
        result = (
            (self.results.get(plan["key"]) or {})
            .get(plan["action"]) or {}
        )
        return bool(
            result.get("success")
            and result.get("scheduled_at") == plan["scheduled_text"]
        )
