"""
飞牛影视双 NAS 播放记录同步 - 核心逻辑

本模块不依赖 MoviePilot 运行环境，可独立测试。
封装：飞牛接口客户端、影片匹配、基线驱动的双向同步引擎。

已确认的接口（来自 MoviePilot 内置 trimemedia/api.py 与开源 FnosSync 插件）：
  登录       POST /api/v1/login              {username, password, app_name}
  媒体列表   POST /api/v1/item/list          {tags, page, page_size, ...}
  媒体详情   GET  /api/v1/item/{guid}
  继续观看   GET  /api/v1/play/list
  播放流     GET  /api/v1/stream/list/{guid}
  选流       POST /api/v1/play/info          {item_guid}
  写进度     POST /api/v1/play/record        {media_guid, item_guid, ts}
  清进度     DELETE /api/v1/play/record      {item_guid}
  标已看完   POST /api/v1/item/watched       {item_guid}
  取消已看完 DELETE /api/v1/item/watched     {item_guid}
"""

import hashlib
import json
import os
import random
import re
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import requests

    requests.packages.urllib3.disable_warnings()
except ImportError:
    requests = None

# 飞牛公开常量（所有官方客户端共用，非用户凭据）
API_KEY = "16CCEB3D-AB42-077D-36A1-F355324E4237"
SIGN_SALT = "NDzZTVxnRKP8Z0jXg1VAMonaG8akvh"


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def build_authx(api_path: str, body: str) -> str:
    """飞牛接口签名，与 MoviePilot 内置客户端一致。"""
    if not api_path.startswith("/v"):
        api_path = "/v" + api_path
    nonce = str(random.randint(100000, 999999))
    ts = str(int(time.time() * 1000))
    data_hash = md5_hex(body or "")
    raw = "_".join([SIGN_SALT, api_path, nonce, ts, data_hash, API_KEY])
    return f"nonce={nonce}&timestamp={ts}&sign={md5_hex(raw)}"


def resolve_secret(value: str) -> str:
    """支持用 ${环境变量名} 引用密码，避免明文落库。

    写成 ${FNV_PASS_A} 时从环境变量取；普通字符串原样返回。
    变量不存在时返回空串，由上层报「密码没有填全」，不会拿字面量去登录。
    """
    text = str(value or "").strip()
    if text.startswith("${") and text.endswith("}") and len(text) > 3:
        return os.environ.get(text[2:-1].strip(), "")
    return value or ""


def cert_fingerprint(host: str, timeout: float = 8.0) -> str:
    """取 HTTPS 证书的 SHA256 指纹（十六进制）。

    连接前单独握手一次拿证书，和 requests 的连接互不干扰；
    失败时返回空串，由上层决定是跳过还是放行。
    """
    try:
        parsed = urlparse(host if "://" in host else "https://" + host)
        if parsed.scheme != "https":
            return ""
        hostname = parsed.hostname
        port = parsed.port or 443
        if not hostname:
            return ""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as tls:
                der = tls.getpeercert(binary_form=True)
        return hashlib.sha256(der or b"").hexdigest()
    except Exception:
        return ""


def normalize_title(text: str) -> str:
    """标题归一化：去标点、空格、大小写，用于跨库匹配。"""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    return text


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def strip_season_suffix(text: str) -> str:
    """剥离标题里的季数后缀，让「庆余年 第二季」与「庆余年」对齐。

    季集号本身由 season/episode 字段表达，标题里的季数只是冗余信息。
    """
    if not text:
        return ""
    result = text.strip()
    patterns = [
        r"[SeasonSeries\s]*(\d+)\s*$",
        r"第\s*([0-9一二三四五六七八九十]+)\s*季\s*$",
        r"S(\d+)\s*$",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, result, flags=re.IGNORECASE)
        if not match:
            continue
        if index == 1:
            token = match.group(1)
            number = _CN_NUM.get(token, None) or (int(token) if token.isdigit() else 0)
            if not number:
                continue
        # 只剥离带明确季标志的后缀；纯数字结尾可能是片名一部分，谨慎处理
        if index != 0 or re.search(r"(season|series|第|s)\s*\d+\s*$", result, re.IGNORECASE):
            result = result[:match.start()].strip(" \t-—·:：")
    return result


def extract_year(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(19|20)\d{2}", text)
    return m.group(0) if m else ""


@dataclass
class MediaState:
    """单条媒体的播放状态。"""

    guid: str
    title: str = ""
    media_type: str = ""
    imdb_id: str = ""
    tmdb_id: str = ""
    season: int = 0
    episode: int = 0
    watched: bool = False
    ts: int = 0
    duration: int = 0
    media_guid: str = ""
    # 父级标识：写后抽样回读时要按它拉子级列表
    parent_guid: str = ""
    # 本地集数：用来判断这一季/这部剧有没有新增集
    ep_count: int = 0

    def state_tuple(self) -> Tuple[bool, int]:
        """用于基线比较的状态快照。"""
        return (self.watched, self.ts)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MediaState):
            return False
        return self.state_tuple() == other.state_tuple()


class FnClient:
    """单台飞牛 NAS 的接口客户端。"""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        access_code: str = "",
        use_sha256: bool = False,
        timeout: int = 20,
        logger=None,
        login_mode: str = "auto",
        token: str = "",
        fingerprint: str = "",
        trust_cert: bool = False,
    ):
        self.host = host.rstrip("/")
        if not self.host.endswith("/v"):
            self.host += "/v"
        self.username = username
        self.password = resolve_secret(password)
        self.access_code = access_code
        self.use_sha256 = use_sha256
        self.login_mode = login_mode or "auto"
        self.timeout = timeout
        self.log = logger or self._default_logger
        # 复用上次的令牌可以省掉一次登录往返；失效时 request() 会自动重登
        self.token = token or ""
        # 证书指纹：首次连接学习，之后每轮比对
        self.fingerprint = fingerprint or ""
        self.learned_fingerprint = ""
        self.trust_cert = bool(trust_cert)
        self._tls_checked = False
        # 多线程读目录树时每个线程用自己的连接，requests 的 Session 不是线程安全的
        self._local = threading.local()
        self._sessions: List[Any] = []
        self._session_lock = threading.Lock()
        self._media_guid_cache: Dict[str, str] = {}
        self.last_error = ""
        # 最近一次请求是否成功：写入接口成功时返回 data 可能是空，不能只看返回值
        self.last_ok = False
        # 运行统计，供结构化日志使用
        self.stats: Dict[str, int] = {
            "requests": 0, "bytes": 0, "errors": 0, "login": 0, "reused_token": 0,
            "ms": 0,
        }

    @staticmethod
    def _default_logger(level: str, message: str) -> None:
        print(f"[{level}] {message}")

    def _http(self):
        session = getattr(self._local, "session", None)
        if session is not None:
            return session
        if requests is None:
            raise RuntimeError("缺少 requests 库")
        session = requests.Session()
        session.verify = False
        self._local.session = session
        with self._session_lock:
            self._sessions.append(session)
        return session

    def request(
        self,
        api: str,
        method: str = "GET",
        data: Optional[dict] = None,
        retry: bool = True,
        _tries: int = 0,
    ) -> Optional[Any]:
        """统一请求入口，自动处理签名与令牌过期重试。"""
        self.last_ok = False
        if not api.startswith("/"):
            api = "/" + api
        # login 接口已经带完整 /api/v1 或 /api/v2 前缀，其他接口才补 /api/v1
        api_path = api if api.startswith("/api/") else "/api/v1" + api
        url = self.host + api_path

        if method == "GET":
            body = ""
        else:
            body = json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))

        headers = {
            "Accept": "application/json",
            "Referer": self.host,
            "Authorization": self.token,
            "authx": build_authx(api_path, body),
        }
        if data is not None and method != "GET":
            headers["Content-Type"] = "application/json"

        try:
            session = self._http()
            self.stats["requests"] += 1
            started = time.time()
            response = session.request(
                method, url, headers=headers, data=body if body else None,
                timeout=self.timeout,
            )
            self.stats["ms"] += int((time.time() - started) * 1000)
            self.stats["bytes"] += len(response.content or b"")
            text = response.text or ""
            try:
                payload = response.json()
            except Exception:
                snippet = " ".join(text.split())[:200]
                raise ValueError(
                    f"HTTP {response.status_code} 返回的不是 JSON：{snippet or '<空响应>'}"
                )
            if not isinstance(payload, dict):
                raise ValueError(f"HTTP {response.status_code} 返回结构异常：{str(payload)[:200]}")
            code = int(payload.get("code", -1))
            if code == 0:
                self.last_ok = True
                return payload.get("data")
            if code == -5 and method == "GET" and _tries < 2:
                # 读取偶发失败可以退避重试；写入的 -5 是条目/媒体标识在目标端不存在，
                # 重试不会变好，只会白等并把真实原因埋掉
                time.sleep(0.4 + 0.4 * _tries)
                return self.request(api, method, data, retry=retry, _tries=_tries + 1)
            if retry and code in (-2, -15, -401):
                self.token = ""
                if self.login():
                    return self.request(api, method, data, retry=False)
            hint = "（目标端不存在该条目或媒体文件标识）" if code == -5 and method != "GET" else ""
            self.stats["errors"] += 1
            self.last_error = f"{method} {api} 返回 {code}: {payload.get('msg', '')}{hint}"
            self.log("ERROR", self.last_error)
        except Exception as exc:
            self.stats["errors"] += 1
            self.last_error = f"{method} {api} 异常: {exc}"
            self.log("ERROR", self.last_error)
        return None

    def _verify_access_code(self) -> bool:
        if not self.access_code:
            return True
        root = self.host[:-2] if self.host.endswith("/v") else self.host
        try:
            response = self._http().get(
                f"{root}/c/{self.access_code}",
                allow_redirects=True, timeout=self.timeout, verify=False,
            )
            if response.status_code == 200:
                return True
            self.log("ERROR", f"访问码校验失败，HTTP {response.status_code}")
        except Exception as exc:
            self.log("ERROR", f"访问码校验异常: {exc}")
        return False

    def check_certificate(self) -> bool:
        """比对 HTTPS 证书指纹（首次连接时学习并记录）。

        requests 这里一直是 verify=False（飞牛多为自签证书），
        只靠加密通道不校验身份，理论上可被中间人顶替。
        这里在登录前单独握手取证书算 SHA256：首次记下来，之后每轮比对，
        指纹变了就拒绝连接，把证书被换掉这件事变成看得见的错误。
        """
        if self._tls_checked:
            return True
        self._tls_checked = True
        current = cert_fingerprint(self.host, timeout=min(8.0, float(self.timeout)))
        if not current:
            # 非 HTTPS、或环境不允许直接握手：不阻断，只记一条，避免误伤内网纯 HTTP 部署
            return True
        self.learned_fingerprint = current
        if not self.fingerprint or self.trust_cert:
            self.log("INFO", f"证书指纹已记录: {self.host} {current[:16]}…")
            return True
        if current.lower() != self.fingerprint.lower():
            self.stats["errors"] += 1
            self.last_error = (
                f"证书指纹与上次不一致（当前 {current[:16]}…，记录 {self.fingerprint[:16]}…）。"
                f"可能换了证书，也可能有人在中间冒充。确认是正常换证后，"
                f"勾选「重新信任证书」并保存即可重新学习"
            )
            self.log("ERROR", self.last_error)
            return False
        return True

    def login(self) -> bool:
        """登录，兼容 v1 明文与 v2 SHA256 两种密码方式。

        login_mode: auto 先试 v1 再试 v2；v1 / v2 只试指定方式（省一次失败尝试，避免触发账号锁定）。
        已有可用令牌时直接复用，省掉一次登录往返；令牌失效由 request() 自动重登兜底。
        """
        if not self.check_certificate():
            return False
        if not self._verify_access_code():
            self.last_error = "访问码校验失败"
            return False
        if self.token:
            self.stats["reused_token"] = 1
            self.log("INFO", f"复用已保存的登录令牌: {self.host}")
            return True
        self.stats["login"] += 1
        if self.login_mode in ("v1", "v2"):
            self.use_sha256 = self.login_mode == "v2"
            return self._login_once()
        self.use_sha256 = False
        if self._login_once():
            return True
        self.log("INFO", "v1 登录失败，尝试 v2 方式")
        self.use_sha256 = True
        if self._login_once():
            return True
        self.last_error = (
            f"{self.last_error or '登录失败'}（地址 {self.host}，账号 {self.username}，"
            f"请检查地址、账号密码与访问码；连续失败可能触发账号临时锁定）"
        )
        self.log("ERROR", self.last_error)
        return False

    def _login_once(self) -> bool:
        """按当前 use_sha256 指定的方式登录一次。"""
        password = (
            hashlib.sha256(self.password.encode("utf-8")).hexdigest()
            if self.use_sha256 else self.password
        )
        endpoint = "/api/v2/user/loginByPassword" if self.use_sha256 else "/api/v1/login"
        payload = (
            {"username": self.username, "password": password, "remember": False}
            if self.use_sha256
            else {"username": self.username, "password": password,
                  "app_name": "trimemedia-web"}
        )
        result = self.request(endpoint, "POST", payload, retry=False)
        if isinstance(result, dict) and result.get("token"):
            self.token = result["token"]
            self.login_mode = "v2" if self.use_sha256 else "v1"
            self.log("INFO", f"登录成功: {self.host}")
            return True
        return False

    def close(self) -> None:
        with self._session_lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass
        self._local = threading.local()

    # ---------- 读取 ----------

    def get_all_items(self, page_size: int = 1000, max_pages: int = 20) -> List[MediaState]:
        """遍历媒体库，返回全部影片与分集的播放状态。"""
        rows: List[MediaState] = []
        seen = set()
        for page in range(1, max_pages + 1):
            payload = {
                "tags": {},
                "sort_type": "DESC",
                "sort_column": "create_time",
                "page": page,
                "page_size": page_size,
                "exclude_grouped_video": 1,
            }
            data = self.request("/item/list", "POST", payload)
            if not isinstance(data, dict):
                break
            batch = data.get("list") or []
            total = int(data.get("total") or data.get("total_count") or 0)
            for row in batch:
                guid = row.get("guid")
                if not guid or guid in seen:
                    continue
                seen.add(guid)
                rows.append(self._to_state(row))
            if len(rows) >= total or not batch:
                break
        self.log("INFO", f"{self.host} 读取媒体 {len(rows)} 条")
        return rows

    def get_play_list(self) -> List[MediaState]:
        """读取继续观看列表（含播放进度）。"""
        data = self.request("/play/list")
        if not isinstance(data, list):
            return []
        return [self._to_state(row) for row in data if row.get("guid")]

    def get_children(self, parent_guid: str, page_size: int = 500,
                     max_pages: int = 6) -> List[MediaState]:
        """按父级标识取下一层：剧集取到季，季取到分集，目录取到里面的影片。"""
        if not parent_guid:
            return []
        rows: List[MediaState] = []
        seen = set()
        for page in range(1, max_pages + 1):
            data = self.request("/item/list", "POST", {
                "tags": {},
                "sort_type": "ASC",
                "sort_column": "create_time",
                "page": page,
                "page_size": page_size,
                "parent_guid": parent_guid,
            })
            if not isinstance(data, dict):
                break
            batch = data.get("list") or []
            total = int(data.get("total") or data.get("total_count") or 0)
            for row in batch:
                guid = row.get("guid")
                if not guid or guid in seen:
                    continue
                seen.add(guid)
                rows.append(self._to_state(row))
            if len(rows) >= total or not batch:
                break
        return rows

    def _to_state(self, row: dict) -> MediaState:
        raw_type = str(row.get("type") or "").lower()
        trim_id = str(row.get("trim_id") or "")
        tmdb_id = ""
        if trim_id[:2] in ("tt", "tm") and trim_id[2:].isdigit():
            tmdb_id = trim_id[2:]
        watched_value = row.get("watched", row.get("is_watched", 0))
        ts_value = row.get("ts", row.get("watched_ts", 0)) or 0
        try:
            ts = max(0, int(ts_value))
        except (TypeError, ValueError):
            ts = 0
        return MediaState(
            guid=str(row.get("guid") or ""),
            title=str(row.get("title") or row.get("tv_title") or ""),
            media_type=raw_type,
            imdb_id=str(row.get("imdb_id") or ""),
            tmdb_id=tmdb_id,
            season=int(row.get("season_number") or 0),
            episode=int(row.get("episode_number") or 0),
            watched=bool(watched_value) and int(watched_value or 0) != 0,
            ts=ts,
            duration=int(row.get("duration") or 0),
            # 继续观看列表自带媒体文件标识，带上就能省掉写入前的解析请求
            media_guid=str(row.get("media_guid") or ""),
            parent_guid=str(row.get("parent_guid") or ""),
            # 本地集数用来判断树里有没有新增集，有变化才需要逐集展开
            ep_count=int(row.get("local_number_of_episodes")
                         or row.get("number_of_episodes") or 0),
        )

    # ---------- 写入 ----------

    def remember_media_guid(self, item_guid: str, media_guid: str) -> None:
        """记下条目对应的媒体文件标识，后续写入不用再查流列表。"""
        if item_guid and media_guid:
            self._media_guid_cache[item_guid] = media_guid

    def _resolve_media_guid(self, item_guid: str) -> Optional[str]:
        """分集或有多文件时，解析出用于上报进度的媒体文件标识。"""
        if item_guid in self._media_guid_cache:
            return self._media_guid_cache[item_guid]
        streams = self.request(f"/stream/list/{item_guid}")
        files = []
        if isinstance(streams, dict):
            files = streams.get("files") or []
        elif isinstance(streams, list):
            files = streams
        candidates = [
            f for f in files
            if f.get("guid") and (not f.get("can_play") or bool(f.get("can_play")))
        ]
        media_guid = ""
        if len(candidates) == 1:
            media_guid = str(candidates[0]["guid"])
        elif len(candidates) > 1:
            selected = self.request("/play/info", "POST", {"item_guid": item_guid})
            if isinstance(selected, dict):
                media_guid = str(selected.get("media_guid") or "")
        if media_guid:
            self._media_guid_cache[item_guid] = media_guid
        return media_guid or None

    def set_progress(self, state: MediaState) -> bool:
        """写入播放进度。"""
        if state.ts <= 0:
            return self.clear_progress(state.guid)
        media_guid = state.media_guid or self._resolve_media_guid(state.guid)
        if not media_guid:
            self.log("ERROR", f"无法解析媒体文件标识: {state.guid} {state.title}")
            return False
        self.request("/play/record", "POST", {
            "media_guid": media_guid,
            "item_guid": state.guid,
            "ts": int(state.ts),
        })
        return self.last_ok

    def clear_progress(self, item_guid: str) -> bool:
        """清空播放进度。"""
        self.request("/play/record", "DELETE", {"item_guid": item_guid})
        return self.last_ok

    def set_watched(self, item_guid: str, watched: bool) -> bool:
        """设置或取消已看完标记。"""
        self.request(
            "/item/watched", "POST" if watched else "DELETE",
            {"item_guid": item_guid},
        )
        return self.last_ok


class MediaMatcher:
    """跨 NAS 影片匹配：IMDb > TMDB > 标题年份；剧集叠加季集。"""

    def __init__(self, logger=None):
        self.log = logger or FnClient._default_logger

    def keys_of(self, state: MediaState) -> List[str]:
        """一条媒体可能有多个等价键（IMDb / TMDB / 标题年份）。

        两台 NAS 刮削源不同是常态：A 有 IMDb、B 只有标题时，靠多键交叉命中。
        """
        suffix = ""
        if state.season or state.episode:
            suffix = f"|S{state.season:02d}E{state.episode:02d}"
        keys: List[str] = []
        if state.imdb_id and state.imdb_id.startswith("tt"):
            keys.append("imdb:" + state.imdb_id + suffix)
        if state.tmdb_id:
            keys.append("tmdb:" + state.tmdb_id + suffix)
        # 标题键用原始标题 + 去季数后缀标题，两个都进索引
        raw_title = normalize_title(state.title)
        if raw_title:
            keys.append(f"name:{raw_title}|{extract_year(state.title)}{suffix}")
        if state.season or state.episode:
            stripped = normalize_title(strip_season_suffix(state.title))
            if stripped and stripped != raw_title:
                keys.append(f"name:{stripped}|{extract_year(state.title)}{suffix}")
        return keys

    def key_of(self, state: MediaState) -> str:
        keys = self.keys_of(state)
        return keys[0] if keys else ""

    def build_index(self, items: List[MediaState]) -> Dict[str, Dict[str, MediaState]]:
        """键 -> {条目 ID: 条目}。

        必须按条目 ID 去重：MediaState 的相等只比较「已看完 + 进度」，
        两条不同条目只要状态相同就会被判成同一条，导致本该模糊跳过的被错配。
        """
        index: Dict[str, Dict[str, MediaState]] = {}
        for item in items:
            for key in self.keys_of(item):
                index.setdefault(key, {})[item.guid] = item
        return index

    def match(self, list_a: List[MediaState], list_b: List[MediaState]) -> Tuple[
        List[Tuple[MediaState, MediaState]], int
    ]:
        """返回唯一匹配的配对数量，以及因歧义跳过的数量。

        多键取并集；仅当所有候选都指向同一个 B 条目时才认定为唯一匹配，
        避免同一部片子被重复配对。
        """
        index_b = self.build_index(list_b)
        pairs = []
        ambiguous = 0
        matched_b = set()
        for item_a in list_a:
            candidates: Dict[str, MediaState] = {}
            for key in self.keys_of(item_a):
                for guid, candidate in index_b.get(key, {}).items():
                    candidates[guid] = candidate
            if len(candidates) == 1:
                target = next(iter(candidates.values()))
                if target.guid in matched_b:
                    ambiguous += 1
                    continue
                pairs.append((item_a, target))
                matched_b.add(target.guid)
            elif len(candidates) > 1:
                ambiguous += 1
        return pairs, ambiguous


class SyncEngine:
    """基线驱动的双向同步：只推送相对基线发生变化的一端。"""

    def __init__(
        self,
        client_a: FnClient,
        client_b: FnClient,
        matcher: MediaMatcher,
        baseline: Optional[dict] = None,
        sync_watched: bool = True,
        conflict_strategy: str = "keep",
        logger=None,
        direction: str = "both",
        workers: int = 4,
        deep: bool = False,
    ):
        self.client_a = client_a
        self.client_b = client_b
        self.matcher = matcher
        # 必须用同一字典引用，否则外部持久化的基线不会更新（空字典也不能被 or 替换）
        self.baseline = baseline if baseline is not None else {}
        self.sync_watched = sync_watched
        self.conflict_strategy = conflict_strategy
        self.log = logger or FnClient._default_logger
        self.direction = direction or "both"
        self.workers = max(1, int(workers or 1))
        # deep=True 时不做「顶层没变就跳过」的省请求判断，逐集完整展开一次
        self.deep = bool(deep)
        # 基线是否有改动，没有改动就不必整份写回存储
        self.baseline_dirty = False
        # 条目映射：全量轮填充，增量轮据此把变化的条目对到另一端
        self.guid_map: Dict[str, Dict[str, str]] = {"a": {}, "b": {}}
        # 全量轮结束时两端的继续观看指纹，直接给下一轮增量用
        self.play_snapshot: Dict[str, Dict[str, list]] = {"a": {}, "b": {}}
        # 一轮内已取过的子级，避免重复请求
        self._children_cache: Dict[Tuple[str, str], List[MediaState]] = {}
        # 写入节流：连续成功就缩短间隔，失败后拉长
        self._write_gap = 0.05
        # 本轮写过的条目，收尾时抽样回读确认真写进去了
        self._writes: List[Tuple[str, str, str, MediaState]] = []
        self.children_requests = 0
        self.skipped_expand = 0

    def _can_write(self, target: FnClient) -> bool:
        if self.direction == "a_to_b":
            return target is self.client_b
        if self.direction == "b_to_a":
            return target is self.client_a
        return True

    def _children(self, tag: str, state: MediaState) -> List[MediaState]:
        """取子级，优先命中本轮预取结果。"""
        cached = self._children_cache.get((tag, state.guid))
        if cached is not None:
            return cached
        children = self._children_of(tag, state.guid)
        self._children_cache[(tag, state.guid)] = children
        return children

    def _children_of(self, tag: str, guid: str) -> List[MediaState]:
        client = self.client_a if tag == "a" else self.client_b
        return client.get_children(guid)

    # ---------- 该不该往下展开 ----------

    @staticmethod
    def _parent_key(state_a: MediaState, state_b: MediaState) -> str:
        return f"P:{state_a.guid}|{state_b.guid}"

    @staticmethod
    def _expand_signature(state_a: MediaState, state_b: MediaState) -> list:
        """父级展开判断用的指纹：只看顶层能看到的东西。"""
        return [bool(state_a.watched), int(state_a.ts), int(state_a.ep_count),
                bool(state_b.watched), int(state_b.ts), int(state_b.ep_count)]

    def _need_expand(self, state_a: MediaState, state_b: MediaState) -> bool:
        """这部剧/这一季要不要往下拉分集。

        全量扫描的请求几乎全花在逐季逐集上（实测 89 次里 80 多次是子级）。
        绝大多数剧在两个库之间早就一致，每轮重拉一遍纯属浪费，这里按四条判断：

        1. 两端整剧都已看完、集数也一致 —— 分集层必然一致，直接跳过；
        2. 本轮是深度轮 —— 无条件完整展开，防止下面两条漏掉东西；
        3. 两端顶层状态不同 —— 有差异，必须展开定位到分集；
        4. 上一轮展开后顶层指纹没变 —— 没人动过，跳过。

        代价：分集层的手动改动而顶层毫无变化时，要等深度轮（默认 24 小时）才补上。
        """
        if state_a.watched and state_b.watched and state_a.ep_count == state_b.ep_count:
            return False
        if self.deep:
            return True
        if state_a.state_tuple() != state_b.state_tuple():
            return True
        record = self.baseline.get(self._parent_key(state_a, state_b)) or {}
        return record.get("sig") != self._expand_signature(state_a, state_b)

    def _mark_expanded(self, state_a: MediaState, state_b: MediaState) -> None:
        """记下「这部剧这一轮已经完整比对过」，下一轮顶层没变就不用再展开。"""
        key = self._parent_key(state_a, state_b)
        sig = self._expand_signature(state_a, state_b)
        record = self.baseline.get(key) or {}
        if record.get("sig") == sig:
            return
        record["sig"] = sig
        record["title"] = state_a.title
        self.baseline[key] = record
        self.baseline_dirty = True

    def prefetch_children(self, pairs: List[Tuple[MediaState, MediaState]],
                          depth: int = 3) -> int:
        """并发预取需要展开的子级。

        目录树结构在两次运行之间基本不变，逐层串行读是纯等待；
        这里按层并发取，请求数不变，墙钟时间降到 1/4 左右。
        返回发出的请求数。
        """
        pending: Dict[str, List[str]] = {"a": [], "b": []}
        for state_a, state_b in pairs:
            is_tree = (state_a.media_type in self._TREE_TYPES
                       or state_b.media_type in self._TREE_TYPES)
            if not is_tree:
                continue
            if not self._need_expand(state_a, state_b):
                self.skipped_expand += 1
                continue
            if state_a.media_type in self._TREE_TYPES:
                pending["a"].append(state_a.guid)
            if state_b.media_type in self._TREE_TYPES:
                pending["b"].append(state_b.guid)
        requested = 0
        for _ in range(max(0, depth)):
            jobs = [(tag, guid) for tag in ("a", "b") for guid in pending[tag]
                    if (tag, guid) not in self._children_cache]
            if not jobs:
                break
            if len(jobs) == 1 or self.workers <= 1:
                results = [(job, self._children_of(*job)) for job in jobs]
            else:
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    results = list(pool.map(lambda job: (job, self._children_of(*job)), jobs))
            requested += len(jobs)
            for job, children in results:
                self._children_cache[job] = children
            # 下一层：子项仍在树里的，按它所属的那一端继续展开
            pending = {"a": [], "b": []}
            for (tag, _guid), children in list(self._children_cache.items()):
                for child in children:
                    if (child.media_type in self._TREE_TYPES
                            and (tag, child.guid) not in self._children_cache):
                        pending[tag].append(child.guid)
        self.children_requests += requested
        return requested

    def _target_of(self, state: MediaState, source: FnClient) -> FnClient:
        return self.client_b if source is self.client_a else self.client_a

    @staticmethod
    def _retarget(state: MediaState, guid: str) -> MediaState:
        """复制一份状态并换上接收端自己的 guid。

        来源端的 media_guid 是那台机器上的媒体文件标识，带过来在另一台无效，
        直接提交飞牛会回 -5 Permission Error，必须清空后按接收端重新解析。
        """
        return MediaState(
            guid=guid,
            title=state.title,
            media_type=state.media_type,
            imdb_id=state.imdb_id,
            tmdb_id=state.tmdb_id,
            season=state.season,
            episode=state.episode,
            watched=state.watched,
            ts=state.ts,
            duration=state.duration,
            media_guid="",
        )

    def _apply(self, target: FnClient, source_state: MediaState,
               base_state: Optional[MediaState], target_guid: str,
               target_parent: str = "") -> Optional[bool]:
        """把来源状态写入目标端，按变化项精确写入。

        target_guid 必须是接收端自己的条目标识，不能用来源端的。
        返回 True 成功 / False 失败 / None 被单向同步规则拦下（未写、也不该记基线）。
        """
        if not self._can_write(target):
            return None
        if not target_guid:
            self.log("ERROR", f"缺少接收端标识，跳过写入: {source_state.title}")
            return False
        ok = True
        if base_state is None or source_state.ts != base_state.ts:
            ok = target.set_progress(self._retarget(source_state, target_guid)) and ok
        if self.sync_watched and (
            base_state is None or source_state.watched != base_state.watched
        ):
            ok = target.set_watched(target_guid, source_state.watched) and ok
        # 节流自适应：连续成功就加快，遇到失败再拉长间隔，兼顾速度与服务端压力
        if ok:
            self._write_gap = max(0.02, self._write_gap * 0.8)
        else:
            self._write_gap = min(0.5, max(0.2, self._write_gap * 3))
        if ok and target_parent:
            # 留一条待回读：分集写入最难肉眼发现，尤其「已看完」写错会让条目
            # 直接从继续观看列表里消失，看不出异常
            tag = "b" if target is self.client_b else "a"
            self._writes.append(
                (tag, target_guid, target_parent,
                 self._retarget(source_state, target_guid))
            )
        time.sleep(self._write_gap)
        return ok

    def verify_samples(self, limit: int = 2) -> dict:
        """写后抽样回读：拉父级子列表，确认「已看完」真的落到了对端。

        飞牛写入接口成功只代表请求被接受，偶尔会出现返回成功但状态没变的情况；
        全部回读太贵，这里每轮抽 1～2 条，一次请求能覆盖一条。
        """
        report = {"checked": 0, "mismatch": 0, "detail": []}
        seen = set()
        for tag, guid, parent, expect in self._writes:
            if report["checked"] >= limit:
                break
            if (tag, guid) in seen:
                continue
            seen.add((tag, guid))
            client = self.client_a if tag == "a" else self.client_b
            rows = client.get_children(parent)
            found = next((row for row in rows if row.guid == guid), None)
            report["checked"] += 1
            if found is None:
                continue
            same_watched = bool(found.watched) == bool(expect.watched)
            same_ts = expect.ts <= 0 or abs(int(found.ts) - int(expect.ts)) <= 2
            if same_watched and same_ts:
                continue
            report["mismatch"] += 1
            report["detail"].append(
                f"{expect.title}: 写入 {expect.watched}/{expect.ts}秒，"
                f"回读 {found.watched}/{found.ts}秒"
            )
            self.log("WARN", f"写后回读不一致 - {report['detail'][-1]}")
        return report

    @staticmethod
    def _note(result: dict, title: str, direction: str, ts: int, action: str) -> None:
        """同时记一条纯文本和一条结构化变更，页面表格用后者的片名。"""
        result.setdefault("changes", []).append(
            f"{title}: {direction} {ts}秒" if action == "send" else f"{title}: {direction}"
        )
        result.setdefault("items", []).append({
            "title": title or "(无标题)", "direction": direction,
            "ts": int(ts or 0), "action": action,
        })

    def collect_stats(self) -> dict:
        """汇总本轮两端的请求开销，写成一行结构化日志。"""
        stat_a = self.client_a.stats
        stat_b = self.client_b.stats
        total_bytes = int(stat_a.get("bytes", 0)) + int(stat_b.get("bytes", 0))
        return {
            "requests": int(stat_a.get("requests", 0)) + int(stat_b.get("requests", 0)),
            "bytes": total_bytes,
            "kb": round(total_bytes / 1024.0, 1),
            "ms": int(stat_a.get("ms", 0)) + int(stat_b.get("ms", 0)),
            "errors": int(stat_a.get("errors", 0)) + int(stat_b.get("errors", 0)),
            "login": int(stat_a.get("login", 0)) + int(stat_b.get("login", 0)),
            "reused_token": int(stat_a.get("reused_token", 0)) + int(stat_b.get("reused_token", 0)),
            "children_requests": self.children_requests,
            "skipped_expand": self.skipped_expand,
        }

    def run(self, dry_run: bool = False) -> dict:
        result = {
            "total_pairs": 0, "synced": 0, "skipped": 0,
            "conflicts": 0, "ambiguous": 0, "failed": 0, "changes": [], "items": [],
        }
        self.guid_map = {"a": {}, "b": {}}
        items_a = self.client_a.get_all_items()
        items_b = self.client_b.get_all_items()
        # 读不到东西不能当成「两端都没条目」继续跑，否则会把映射和基线清成空
        if not items_a:
            raise RuntimeError(
                f"NAS A 读取媒体库为空：{self.client_a.last_error or '没有返回任何条目'}")
        if not items_b:
            raise RuntimeError(
                f"NAS B 读取媒体库为空：{self.client_b.last_error or '没有返回任何条目'}")
        # 继续观看列表补全：部分版本 item/list 不返回进度，另外带上媒体文件标识
        self.play_snapshot["a"] = self._merge_play_list(items_a, self.client_a)
        self.play_snapshot["b"] = self._merge_play_list(items_b, self.client_b)

        pairs, ambiguous = self.matcher.match(items_a, items_b)
        result["total_pairs"] = len(pairs)
        result["ambiguous"] = ambiguous

        # 先把要展开的目录树并发取回来，后面逐条同步时直接命中缓存
        self.prefetch_children(pairs)

        for state_a, state_b in pairs:
            self._sync_pair(state_a, state_b, result, dry_run, 0)
        return result

    @staticmethod
    def _merge_play_list(items: List[MediaState], client: FnClient) -> Dict[str, list]:
        """把继续观看列表的进度与媒体文件标识并进主列表，同时返回指纹。"""
        index = {item.guid: item for item in items}
        snapshot: Dict[str, list] = {}
        for state in client.get_play_list():
            snapshot[state.guid] = [state.ts, bool(state.watched)]
            # 分集不在顶层列表里，但这份标识对分集同样有效，先记下省掉解析请求
            client.remember_media_guid(state.guid, state.media_guid)
            item = index.get(state.guid)
            if item is None:
                continue
            item.ts = state.ts
            # 列表自带媒体文件标识，写入时就不用再查一次流列表
            if not item.media_guid and state.media_guid:
                item.media_guid = state.media_guid
        return snapshot

    def run_incremental(self, snapshot: dict, guid_map: dict,
                        dry_run: bool = False) -> Tuple[dict, dict, bool]:
        """轻量轮询：只读两端「继续观看」列表，不动整库。

        snapshot: {"a": {guid: [进度, 已看完]}, "b": {...}} 上一轮的指纹
        guid_map: {"a": {A 条目: B 条目}, "b": {B 条目: A 条目}}，全量轮维护
        返回 (结果, 新指纹, 是否需要改跑一次全量)
        说明：手动点「已看完」不会出现在继续观看列表里，必须靠低频全量兜底。
        """
        result = {
            "total_pairs": 0, "synced": 0, "skipped": 0,
            "conflicts": 0, "ambiguous": 0, "failed": 0, "changes": [], "items": [],
            "mode": "incremental",
        }
        errors_before = self.client_a.stats.get("errors", 0) + self.client_b.stats.get("errors", 0)
        play_a = self.client_a.get_play_list()
        play_b = self.client_b.get_play_list()
        errors_after = self.client_a.stats.get("errors", 0) + self.client_b.stats.get("errors", 0)
        if errors_after > errors_before and not (play_a or play_b):
            raise RuntimeError(
                "读取继续观看列表失败："
                f"{self.client_a.last_error or self.client_b.last_error or '未知原因'}")
        index_a = {s.guid: s for s in play_a}
        index_b = {s.guid: s for s in play_b}

        new_snapshot: Dict[str, Dict[str, list]] = {"a": {}, "b": {}}
        changed: Dict[str, Dict[str, MediaState]] = {"a": {}, "b": {}}
        need_full = False
        for tag, states in (("a", play_a), ("b", play_b)):
            before = (snapshot or {}).get(tag) or {}
            mapping = (guid_map or {}).get(tag) or {}
            for state in states:
                fingerprint = [state.ts, bool(state.watched)]
                new_snapshot[tag][state.guid] = fingerprint
                if before.get(state.guid) == fingerprint:
                    continue
                changed[tag][state.guid] = state
                # 这一条在映射表里没有对端，说明是新片或刮削变了，只能走全量重新配对
                if state.guid not in mapping:
                    need_full = True
        if need_full:
            return result, new_snapshot, True

        result["total_pairs"] = len(index_a)
        for tag in ("a", "b"):
            other = "b" if tag == "a" else "a"
            peer_index = index_b if other == "b" else index_a
            target = self.client_b if tag == "a" else self.client_a
            mapping = (guid_map or {}).get(tag) or {}
            for guid, state in changed[tag].items():
                target_guid = mapping.get(guid)
                if not target_guid:
                    continue
                peer = peer_index.get(target_guid)
                if (peer is not None and peer.ts == state.ts
                        and bool(peer.watched) == bool(state.watched)):
                    # 对端已经是这个状态（例如刚被手动改回来），不必再写一次
                    result["skipped"] += 1
                    continue
                if target_guid in changed[other]:
                    if peer is None:
                        peer = MediaState(guid=target_guid)
                    chosen = (self._resolve_conflict(state, peer) if tag == "a"
                              else self._resolve_conflict(peer, state))
                    if chosen != tag:
                        result["skipped"] += 1
                        continue
                    result["conflicts"] += 1
                before = ((snapshot or {}).get(tag) or {}).get(guid)
                base = (MediaState(guid=guid, ts=int(before[0]), watched=bool(before[1]))
                        if before else None)
                if dry_run:
                    result["synced"] += 1
                    self._note(result, state.title, f"{tag.upper()}→{other.upper()}",
                               state.ts, "send")
                    continue
                applied = self._count(result, self._apply(
                    target, state, base, target_guid,
                    peer.parent_guid if peer is not None else ""))
                if not applied:
                    continue
                self._note(result, state.title, f"{tag.upper()}→{other.upper()}",
                           state.ts, "send")
                # 写入后两端都等于来源值，各自保留自己的条目标识
                if tag == "a":
                    a_state, b_state = state, self._retarget(state, target_guid)
                else:
                    a_state, b_state = self._retarget(state, target_guid), state
                self._save_baseline(f"{a_state.guid}|{b_state.guid}", a_state, b_state)
        return result, new_snapshot, False

    # 需要向下展开的类型：剧集、季、目录、合集
    _TREE_TYPES = {"tv", "show", "series", "season", "directory", "folder", "collection"}

    def _sync_pair(self, state_a: MediaState, state_b: MediaState,
                   result: dict, dry_run: bool, depth: int) -> None:
        """条目级配对：能展开的往下展开，分集按季集号对应，其余按标题匹配。"""
        is_tree = (state_a.media_type in self._TREE_TYPES
                   or state_b.media_type in self._TREE_TYPES)
        if depth < 4 and is_tree and self._need_expand(state_a, state_b):
            children_a = self._children("a", state_a)
            children_b = self._children("b", state_b)
            if children_a and children_b:
                self._sync_children(children_a, children_b, result, dry_run, depth + 1)
                # 记下已完整比对过，下一轮顶层没变就直接跳过这一整棵树
                self._mark_expanded(state_a, state_b)
                return
        self._sync_leaf(state_a, state_b, result, dry_run)

    def _sync_children(self, children_a: List[MediaState], children_b: List[MediaState],
                       result: dict, dry_run: bool, depth: int) -> None:
        eps_a = {(c.season, c.episode): c for c in children_a
                 if c.media_type == "episode" and (c.season or c.episode)}
        eps_b = {(c.season, c.episode): c for c in children_b
                 if c.media_type == "episode" and (c.season or c.episode)}
        for key in sorted(set(eps_a) & set(eps_b)):
            self._sync_leaf(eps_a[key], eps_b[key], result, dry_run)

        rest_a = [c for c in children_a if c.media_type != "episode"]
        rest_b = [c for c in children_b if c.media_type != "episode"]
        if rest_a and rest_b:
            pairs, _ = self.matcher.match(rest_a, rest_b)
            for state_a, state_b in pairs:
                self._sync_pair(state_a, state_b, result, dry_run, depth)

    def _sync_leaf(self, state_a: MediaState, state_b: MediaState,
                   result: dict, dry_run: bool) -> None:
        """叶子条目：按基线判断哪一端变了，然后推给对方。"""
        # 顺手记下条目对应关系，供下一轮增量轮询直接定位对端
        self.guid_map["a"][state_a.guid] = state_b.guid
        self.guid_map["b"][state_b.guid] = state_a.guid
        # 基线键用两端 guid 组合，刮削源变化也不会让基线失效
        key = f"{state_a.guid}|{state_b.guid}"
        record = self.baseline.get(key)
        base_a = self._restore(record.get("a")) if record else None
        base_b = self._restore(record.get("b")) if record else None

        a_changed = base_a is not None and state_a != base_a
        b_changed = base_b is not None and state_b != base_b

        if record is None:
            # 首次遇到：两端不一致时按冲突策略拉齐一次，一致就只记基线
            if state_a != state_b:
                after = self._first_sight_sync(state_a, state_b, result, dry_run)
                # 写入失败不记基线，下次还会重试，避免失败被基线掩盖
                if after:
                    self._save_baseline(key, *after)
            else:
                result["skipped"] += 1
                self._save_baseline(key, state_a, state_b)
            return

        if not a_changed and not b_changed:
            result["skipped"] += 1
            return

        applied = True
        after = (state_a, state_b)
        if a_changed and b_changed:
            if state_a == state_b:
                result["skipped"] += 1
            else:
                result["conflicts"] += 1
                chosen = self._resolve_conflict(state_a, state_b)
                if chosen is None:
                    # 保留冲突：不更新基线，下次仍能识别为同一冲突
                    result["skipped"] += 1
                    return
                if chosen == "a":
                    target, source_state, target_guid = self.client_b, state_a, state_b.guid
                    target_parent = state_b.parent_guid
                else:
                    target, source_state, target_guid = self.client_a, state_b, state_a.guid
                    target_parent = state_a.parent_guid
                if not dry_run:
                    applied = self._count(result, self._apply(
                        target, source_state,
                        self._restore(record.get("b" if chosen == "a" else "a")),
                        target_guid, target_parent))
                else:
                    result["synced"] += 1
                after = self._sides_after(state_a, state_b, source_state, chosen)
                self._note(result, state_a.title, f"冲突按 {chosen.upper()} 端", 0, "conflict")
        else:
            if a_changed:
                target, source_state = self.client_b, state_a
                target_guid, prev = state_b.guid, base_a
                target_parent = state_b.parent_guid
                direction = "A→B"
            else:
                target, source_state = self.client_a, state_b
                target_guid, prev = state_a.guid, base_b
                target_parent = state_a.parent_guid
                direction = "B→A"
            if not dry_run:
                applied = self._count(result, self._apply(
                    target, source_state, prev, target_guid, target_parent))
            else:
                result["synced"] += 1
            after = self._sides_after(state_a, state_b, source_state,
                                      "a" if a_changed else "b")
            self._note(result, state_a.title, direction, source_state.ts, "send")

        if applied:
            self._save_baseline(key, *after)

    def _first_sight_sync(self, state_a: MediaState, state_b: MediaState,
                          result: dict, dry_run: bool):
        """首次配对且两端状态不同：按冲突策略决定要不要拉齐。

        返回写入后两端应有的状态；返回 None 表示本次不记基线。
        """
        chosen = self._resolve_conflict(state_a, state_b)
        if chosen is None:
            result["skipped"] += 1
            return None
        if chosen == "a":
            target, source_state, target_guid = self.client_b, state_a, state_b.guid
            target_parent = state_b.parent_guid
        else:
            target, source_state, target_guid = self.client_a, state_b, state_a.guid
            target_parent = state_a.parent_guid
        if dry_run:
            applied = True
            result["synced"] += 1
        else:
            applied = self._count(result, self._apply(
                target, source_state, None, target_guid, target_parent))
        self._note(result, state_a.title, f"首次拉齐按 {chosen.upper()} 端",
                   source_state.ts, "first")
        if not applied:
            return None
        return self._sides_after(state_a, state_b, source_state, chosen)

    def _sides_after(self, state_a: MediaState, state_b: MediaState,
                     source_state: MediaState, chosen: str):
        """写入成功后两端都应等于来源端的值，各自保留自己的 guid。"""
        if chosen == "a":
            return source_state, self._retarget(source_state, state_b.guid)
        return self._retarget(source_state, state_a.guid), state_b

    @staticmethod
    def _count(result: dict, outcome: Optional[bool]) -> bool:
        """按写入结果计数，返回是否应该记基线。None 表示被单向规则拦下。"""
        if outcome is None:
            result["skipped"] += 1
            return False
        result["synced" if outcome else "failed"] += 1
        return bool(outcome)

    def _save_baseline(self, key: str, state_a: MediaState, state_b: MediaState) -> None:
        self.baseline_dirty = True
        self.baseline[key] = {
            "a": self._snapshot(state_a),
            "b": self._snapshot(state_b),
            "title": state_a.title,
        }

    def _resolve_conflict(self, a: MediaState, b: MediaState) -> Optional[str]:
        if self.conflict_strategy == "a":
            return "a"
        if self.conflict_strategy == "b":
            return "b"
        if self.conflict_strategy == "progress":
            if a.watched != b.watched:
                return "a" if a.watched else "b"
            return "a" if a.ts >= b.ts else "b"
        return None

    @staticmethod
    def _snapshot(state: MediaState) -> dict:
        return {"watched": state.watched, "ts": state.ts, "guid": state.guid}

    @staticmethod
    def _restore(data: Optional[dict]) -> Optional[MediaState]:
        if not isinstance(data, dict):
            return None
        return MediaState(
            guid=str(data.get("guid") or ""),
            watched=bool(data.get("watched")),
            ts=int(data.get("ts") or 0),
        )
