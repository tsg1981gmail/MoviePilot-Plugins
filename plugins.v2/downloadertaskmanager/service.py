from typing import Any, Dict, List, Tuple

from .runtime import (
    SUPPORTED_DOWNLOADERS,
    get_value,
    normalize_torrent,
)


STATUS_ORDER = {
    "paused": 0,
    "downloading": 1,
    "uploading": 2,
    "checking": 3,
    "queued": 4,
    "error": 5,
    "unknown": 6,
}


def _failure(message: str, affected: int = 0) -> Dict[str, Any]:
    """构建统一失败结果。"""
    return {
        "success": False,
        "message": message,
        "affected": affected,
    }


def _success(message: str, affected: int) -> Dict[str, Any]:
    """构建统一成功结果。"""
    return {
        "success": True,
        "message": message,
        "affected": affected,
    }


def _downloader_type(service: Any) -> str:
    """读取服务类型并回退到服务配置类型。"""
    service_type = get_value(service, "type")
    if not service_type:
        config = get_value(service, "config")
        service_type = get_value(config, "type")
    return str(service_type or "").strip().lower()


def _error_text(error: Any) -> str:
    """将查询错误转换为可读信息。"""
    if isinstance(error, str) and error.strip():
        return error.strip()
    return ""


def _normalize_hashes(values: Any) -> List[str]:
    """将动作哈希去重、去空白并转为小写。"""
    if not isinstance(values, (list, tuple, set)):
        return []
    hashes = []
    seen = set()
    for value in values:
        torrent_hash = str(value or "").strip().lower()
        if torrent_hash and torrent_hash not in seen:
            hashes.append(torrent_hash)
            seen.add(torrent_hash)
    return hashes


def _query_tasks(instance: Any, downloader_type: str) -> Tuple[List[dict], str]:
    """查询并归一化下载器任务。"""
    try:
        result = instance.get_torrents()
    except Exception as error:
        return [], f"获取任务失败：{error}"

    if not isinstance(result, tuple) or len(result) != 2:
        return [], "获取任务失败：下载器返回格式无效"

    torrents, error = result
    if error:
        detail = _error_text(error)
        return [], f"获取任务失败：{detail}" if detail else "获取任务失败"

    tasks = []
    for torrent in torrents or []:
        normalized = normalize_torrent(torrent, downloader_type)
        if normalized:
            tasks.append(normalized)
    tasks.sort(key=lambda task: (
        STATUS_ORDER.get(task.get("status"), 99),
        str(task.get("name") or "").lower(),
    ))
    return tasks, ""


class DownloaderTaskService:
    """封装下载器任务查询和开始暂停操作。"""

    def __init__(self, helper: Any, allow_bulk_actions: bool = False):
        """保存下载器帮助类与全量操作开关。"""
        self.helper = helper
        self.allow_bulk_actions = bool(allow_bulk_actions)

    def list_views(self) -> List[dict]:
        """返回所有已启用下载器的任务视图。"""
        services = self.helper.get_services() or {}

        views = []
        for service_key, service in services.items():
            name = str(get_value(service, "name", default=service_key) or service_key)
            downloader_type = _downloader_type(service)
            view = {
                "name": name,
                "type": downloader_type or "unknown",
                "available": False,
                "error": "",
                "tasks": [],
            }
            if downloader_type not in SUPPORTED_DOWNLOADERS:
                view["error"] = f"不支持的下载器类型：{downloader_type or 'unknown'}"
                views.append(view)
                continue

            instance = get_value(service, "instance")
            if not instance:
                view["error"] = "下载器实例不可用"
                views.append(view)
                continue
            try:
                inactive = bool(instance.is_inactive())
            except Exception as error:
                view["error"] = f"检查下载器状态失败：{error}"
                views.append(view)
                continue
            if inactive:
                view["error"] = "下载器未连接"
                views.append(view)
                continue

            tasks, query_error = _query_tasks(instance, downloader_type)
            if query_error:
                view["error"] = query_error
                views.append(view)
                continue

            view["available"] = True
            view["tasks"] = tasks
            views.append(view)
        return views

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """校验动作请求并执行单任务或当前下载器全量动作。"""
        if not isinstance(payload, dict):
            return _failure("请求格式无效")

        downloader = str(payload.get("downloader") or "").strip()
        scope = str(payload.get("scope") or "").strip().lower()
        action = str(payload.get("action") or "").strip().lower()

        if not downloader:
            return _failure("缺少下载器名称")
        if scope not in {"task", "all"}:
            return _failure("不支持的操作范围")
        if action not in {"start", "stop"}:
            return _failure("不支持的任务动作")
        if scope == "all" and not self.allow_bulk_actions:
            return _failure("全量操作未开启")

        try:
            service = self.helper.get_service(downloader)
        except Exception as error:
            return _failure(f"获取下载器失败：{error}")
        if not service:
            return _failure(f"下载器不存在或未启用：{downloader}")

        downloader_type = _downloader_type(service)
        if downloader_type not in SUPPORTED_DOWNLOADERS:
            return _failure(f"不支持的下载器类型：{downloader_type or 'unknown'}")

        instance = get_value(service, "instance")
        if not instance:
            return _failure("下载器实例不可用")
        try:
            if instance.is_inactive():
                return _failure("下载器未连接")
        except Exception as error:
            return _failure(f"检查下载器状态失败：{error}")

        if scope == "task":
            hashes = _normalize_hashes(payload.get("hashes"))
            if not hashes:
                return _failure("请选择要操作的任务")
        else:
            tasks, query_error = _query_tasks(instance, downloader_type)
            if query_error:
                return _failure(query_error)
            hashes = [task["hash"] for task in tasks]
            if not hashes:
                return _failure("当前下载器没有可操作的任务")

        method_name = "start_torrents" if action == "start" else "stop_torrents"
        method = getattr(instance, method_name, None)
        if not callable(method):
            return _failure(f"下载器不支持 {method_name}")
        try:
            succeeded = bool(method(ids=hashes))
        except Exception as error:
            return _failure(f"执行任务动作失败：{error}")
        if not succeeded:
            return _failure("下载器执行任务动作失败")

        action_text = "开始" if action == "start" else "暂停"
        return _success(f"已{action_text} {len(hashes)} 个任务", len(hashes))
