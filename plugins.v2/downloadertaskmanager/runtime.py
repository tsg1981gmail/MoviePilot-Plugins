import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo


SUPPORTED_DOWNLOADERS = {"qbittorrent", "transmission"}

PAUSED_STATES = {
    "pauseddl",
    "pausedup",
    "stopped",
    "stoppeddl",
    "stoppedup",
}
DOWNLOADING_STATES = {
    "downloading",
    "download_pending",
    "forceddl",
    "forcedmetadl",
    "metadl",
    "stalleddl",
}
CHECKING_STATES = {
    "checking",
    "check_pending",
    "checkingdl",
    "checkingup",
    "checkingresumedata",
}
QUEUED_STATES = {
    "download_wait",
    "queueddl",
}
UPLOADING_STATES = {
    "seeding",
    "seed_pending",
    "seed_wait",
    "uploading",
    "forcedup",
    "queuedup",
    "stalledup",
}
ERROR_STATES = {
    "error",
    "missingfiles",
}

STATE_TEXT = {
    "paused": "已暂停",
    "downloading": "下载中",
    "checking": "校验中",
    "queued": "排队中",
    "uploading": "做种中",
    "error": "错误",
    "unknown": "未知",
}


def downloader_key(downloader_type: str, downloader_name: str) -> str:
    """生成下载器计划稳定键。"""
    normalized_type = str(downloader_type or "").strip().lower()
    normalized_name = str(downloader_name or "").strip()
    raw = f"{normalized_type}\0{normalized_name}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def schedule_field(key: str, action: str) -> str:
    """返回计划配置字段名。"""
    if action == "start":
        suffix = "start_at"
    elif action == "stop":
        suffix = "pause_at"
    else:
        raise ValueError(f"unsupported schedule action: {action}")
    return f"schedule_{key}_{suffix}"


def parse_schedule_time(value: Any, timezone: ZoneInfo) -> Optional[datetime]:
    """解析本地一次性计划时间。"""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        parsed = None
        for formatter in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(text, formatter)
                break
            except ValueError:
                continue
        if parsed is None:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _get_value(source: Any, *keys: str, default: Any = None) -> Any:
    """从 Mapping 或对象读取第一个非空字段。"""
    if source is None:
        return default
    for key in keys:
        if isinstance(source, Mapping):
            if key in source and source.get(key) is not None:
                return source.get(key)
        elif hasattr(source, key):
            value = getattr(source, key)
            if value is not None:
                return value
    return default


def normalize_progress(value: Any, downloader_type: str) -> float:
    """将下载器进度归一化为 0 到 100。"""
    try:
        progress = float(value)
    except (TypeError, ValueError):
        progress = 0.0
    if downloader_type == "qbittorrent":
        progress *= 100
    return min(100.0, max(0.0, progress))


def normalize_status(value: Any, downloader_type: str) -> str:
    """将下载器状态归一化为计划支持的状态。"""
    raw_value = getattr(value, "name", value)
    state = str(raw_value or "").strip().lower()
    if state in PAUSED_STATES:
        return "paused"
    if state in CHECKING_STATES:
        return "checking"
    if state in DOWNLOADING_STATES:
        return "downloading"
    if state in QUEUED_STATES:
        return "queued"
    if state in UPLOADING_STATES:
        return "uploading"
    if state in ERROR_STATES:
        return "error"
    return "unknown"


def normalize_torrent(source: Any, downloader_type: str) -> Optional[dict]:
    """将下载器任务转换为计划过滤结构。"""
    if downloader_type not in SUPPORTED_DOWNLOADERS:
        return None

    if downloader_type == "qbittorrent":
        raw_hash = _get_value(source, "hash")
        raw_status = _get_value(source, "state", "status")
    else:
        raw_hash = _get_value(source, "hashString", "hash_string", "hash")
        raw_status = _get_value(source, "status", "state")

    torrent_hash = str(raw_hash or "").strip().lower()
    if not torrent_hash:
        return None

    status = normalize_status(raw_status, downloader_type)
    return {
        "hash": torrent_hash,
        "status": status,
        "state_text": STATE_TEXT[status],
        "progress_percent": normalize_progress(
            _get_value(source, "progress", default=0),
            downloader_type,
        ),
    }


def task_eligible(task: dict, action: str) -> bool:
    """判断任务是否允许被计划动作处理。"""
    status = str((task or {}).get("status") or "unknown")
    try:
        progress = float((task or {}).get("progress_percent") or 0)
    except (TypeError, ValueError):
        progress = 0.0
    if progress >= 100:
        return False
    if action == "start":
        return status == "paused"
    if action == "stop":
        return status in {"downloading", "checking", "queued"}
    return False
