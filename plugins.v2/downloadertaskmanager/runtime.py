from datetime import datetime
from typing import Any, Optional


SUPPORTED_DOWNLOADERS = {"qbittorrent", "transmission"}

PAUSED_STATES = {
    "paused",
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
    "queueddl",
}
UPLOADING_STATES = {
    "uploading",
    "seeding",
    "seed_pending",
    "forcedup",
    "stalledup",
    "queuedup",
}
CHECKING_STATES = {
    "checking",
    "checkingdl",
    "checkingup",
    "checkingresumedata",
    "check_pending",
}
QUEUED_STATES = {
    "queued",
    "download_wait",
    "seed_wait",
}
ERROR_STATES = {
    "error",
    "missingfiles",
}

STATE_TEXT = {
    "paused": "已暂停",
    "downloading": "下载中",
    "uploading": "做种中",
    "checking": "校验中",
    "queued": "排队中",
    "error": "错误",
    "unknown": "未知",
}


def get_value(source: Any, *keys: str, default: Any = None) -> Any:
    """从字典或对象中读取第一个非空字段。"""
    if source is None:
        return default
    for key in keys:
        if isinstance(source, dict):
            if key in source and source.get(key) is not None:
                return source.get(key)
        elif hasattr(source, key):
            value = getattr(source, key)
            if value is not None:
                return value
    return default


def normalize_status(value: Any, downloader_type: str) -> str:
    """将下载器原始状态转换为统一状态。"""
    raw_value = getattr(value, "name", value)
    state = str(raw_value or "").strip().lower()
    if state in PAUSED_STATES:
        return "paused"
    if state in CHECKING_STATES:
        return "checking"
    if state in ERROR_STATES:
        return "error"
    if state in DOWNLOADING_STATES:
        return "downloading"
    if state in UPLOADING_STATES:
        return "uploading"
    if state in QUEUED_STATES:
        return "queued"
    return "unknown"


def _number(value: Any, default: Any = 0) -> Any:
    """将字段转换为数字，无法转换时返回默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timestamp(value: Any) -> Optional[float]:
    """将时间字段转换为 Unix 时间戳。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    number = _number(value, default=None)
    return number if number is not None else None


def _category(source: Any, downloader_type: str) -> str:
    """提取分类、标签或下载目录摘要。"""
    if downloader_type == "qbittorrent":
        return str(get_value(source, "category", default="") or "")

    labels = get_value(source, "labels", default=[])
    if isinstance(labels, (list, tuple, set)):
        return ",".join(str(label) for label in labels if str(label).strip())
    if labels:
        return str(labels)
    return str(get_value(source, "download_dir", default="") or "")


def normalize_torrent(source: Any, downloader_type: str) -> Optional[dict]:
    """将 qBittorrent 或 Transmission 任务转换为统一字典。"""
    if downloader_type not in SUPPORTED_DOWNLOADERS:
        return None

    if downloader_type == "qbittorrent":
        raw_hash = get_value(source, "hash")
    else:
        raw_hash = get_value(source, "hashString", "hash_string", "hash")
    torrent_hash = str(raw_hash or "").strip().lower()
    if not torrent_hash:
        return None

    if downloader_type == "qbittorrent":
        raw_status = get_value(source, "state", "status")
        raw_progress = get_value(source, "progress", default=0)
        progress = _number(raw_progress) * 100
    else:
        raw_status = get_value(source, "status", "state")
        progress = _number(get_value(source, "progress", default=0))

    status = normalize_status(raw_status, downloader_type)
    progress = max(0.0, min(100.0, progress))

    if downloader_type == "qbittorrent":
        size = _number(get_value(source, "size", "total_size"), default=0)
        download_speed = _number(get_value(source, "dlspeed"), default=0)
        upload_speed = _number(get_value(source, "upspeed"), default=0)
        added_at = _timestamp(get_value(source, "added_on"))
    else:
        size = _number(get_value(source, "total_size", "size"), default=0)
        download_speed = _number(get_value(source, "rateDownload"), default=0)
        upload_speed = _number(get_value(source, "rateUpload"), default=0)
        added_at = _timestamp(get_value(source, "date_added"))

    return {
        "hash": torrent_hash,
        "name": str(get_value(source, "name", default=torrent_hash) or torrent_hash),
        "status": status,
        "state_text": STATE_TEXT[status],
        "paused": status == "paused",
        "progress": round(progress, 1),
        "size": size,
        "download_speed": download_speed,
        "upload_speed": upload_speed,
        "category": _category(source, downloader_type),
        "added_at": added_at,
    }
