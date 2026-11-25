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
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
    ):
        self.host = host.rstrip("/")
        if not self.host.endswith("/v"):
            self.host += "/v"
        self.username = username
        self.password = password
        self.access_code = access_code
        self.use_sha256 = use_sha256
        self.login_mode = login_mode or "auto"
        self.timeout = timeout
        self.log = logger or self._default_logger
        self.token = ""
        self._session = None
        self._media_guid_cache: Dict[str, str] = {}
        self.last_error = ""

    @staticmethod
    def _default_logger(level: str, message: str) -> None:
        print(f"[{level}] {message}")

    def _http(self):
        if self._session is not None:
            return self._session
        if requests is None:
            raise RuntimeError("缺少 requests 库")
        self._session = requests.Session()
        self._session.verify = False
        return self._session

    def request(
        self,
        api: str,
        method: str = "GET",
        data: Optional[dict] = None,
        retry: bool = True,
        _tries: int = 0,
    ) -> Optional[Any]:
        """统一请求入口，自动处理签名与令牌过期重试。"""
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
            response = session.request(
                method, url, headers=headers, data=body if body else None,
                timeout=self.timeout,
            )
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
                return payload.get("data")
            if code == -5 and _tries < 2:
                # 连续写入过快时飞牛会回 -5 Permission Error，退避后重试
                time.sleep(0.6 + 0.6 * _tries)
                return self.request(api, method, data, retry=retry, _tries=_tries + 1)
            if retry and code in (-2, -15, -401):
                self.token = ""
                if self.login():
                    return self.request(api, method, data, retry=False)
            self.last_error = f"{method} {api} 返回 {code}: {payload.get('msg', '')}"
            self.log("ERROR", self.last_error)
        except Exception as exc:
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

    def login(self) -> bool:
        """登录，兼容 v1 明文与 v2 SHA256 两种密码方式。

        login_mode: auto 先试 v1 再试 v2；v1 / v2 只试指定方式（省一次失败尝试，避免触发账号锁定）。
        """
        if not self._verify_access_code():
            self.last_error = "访问码校验失败"
            return False
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
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None

    # ---------- 读取 ----------

    def get_all_items(self, page_size: int = 200, max_pages: int = 50) -> List[MediaState]:
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

    def get_children(self, parent_guid: str, page_size: int = 200,
                     max_pages: int = 10) -> List[MediaState]:
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
        )

    # ---------- 写入 ----------

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
        result = self.request("/play/record", "POST", {
            "media_guid": media_guid,
            "item_guid": state.guid,
            "ts": int(state.ts),
        })
        return result is not None

    def clear_progress(self, item_guid: str) -> bool:
        """清空播放进度。"""
        result = self.request("/play/record", "DELETE", {"item_guid": item_guid})
        return result is not None

    def set_watched(self, item_guid: str, watched: bool) -> bool:
        """设置或取消已看完标记。"""
        result = self.request(
            "/item/watched", "POST" if watched else "DELETE",
            {"item_guid": item_guid},
        )
        return result is not None


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

    def build_index(self, items: List[MediaState]) -> Dict[str, List[MediaState]]:
        index: Dict[str, List[MediaState]] = {}
        for item in items:
            for key in self.keys_of(item):
                bucket = index.setdefault(key, [])
                if item not in bucket:
                    bucket.append(item)
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
            candidates = []
            for key in self.keys_of(item_a):
                for candidate in index_b.get(key, []):
                    if candidate not in candidates:
                        candidates.append(candidate)
            if len(candidates) == 1:
                target = candidates[0]
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
    ):
        self.client_a = client_a
        self.client_b = client_b
        self.matcher = matcher
        # 必须用同一字典引用，否则外部持久化的基线不会更新（空字典也不能被 or 替换）
        self.baseline = baseline if baseline is not None else {}
        self.sync_watched = sync_watched
        self.conflict_strategy = conflict_strategy
        self.log = logger or FnClient._default_logger

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
               base_state: Optional[MediaState], target_guid: str) -> bool:
        """把来源状态写入目标端，按变化项精确写入。

        target_guid 必须是接收端自己的条目标识，不能用来源端的。
        """
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
        # 每条之间留一点间隔，连续高速写入会触发服务端 -5
        time.sleep(0.15)
        return ok

    def run(self, dry_run: bool = False) -> dict:
        result = {
            "total_pairs": 0, "synced": 0, "skipped": 0,
            "conflicts": 0, "ambiguous": 0, "failed": 0, "changes": [],
        }
        items_a = self.client_a.get_all_items()
        items_b = self.client_b.get_all_items()
        # 继续观看列表补全：部分版本 item/list 不返回进度
        for state in self.client_a.get_play_list():
            for idx, item in enumerate(items_a):
                if item.guid == state.guid:
                    items_a[idx].ts = state.ts
                    break
        for state in self.client_b.get_play_list():
            for idx, item in enumerate(items_b):
                if item.guid == state.guid:
                    items_b[idx].ts = state.ts
                    break

        pairs, ambiguous = self.matcher.match(items_a, items_b)
        result["total_pairs"] = len(pairs)
        result["ambiguous"] = ambiguous

        for state_a, state_b in pairs:
            self._sync_pair(state_a, state_b, result, dry_run, 0)
        return result

    # 需要向下展开的类型：剧集、季、目录、合集
    _TREE_TYPES = {"tv", "show", "series", "season", "directory", "folder", "collection"}

    def _sync_pair(self, state_a: MediaState, state_b: MediaState,
                   result: dict, dry_run: bool, depth: int) -> None:
        """条目级配对：能展开的往下展开，分集按季集号对应，其余按标题匹配。"""
        if depth < 4 and (state_a.media_type in self._TREE_TYPES
                          or state_b.media_type in self._TREE_TYPES):
            children_a = self.client_a.get_children(state_a.guid)
            children_b = self.client_b.get_children(state_b.guid)
            if children_a and children_b:
                self._sync_children(children_a, children_b, result, dry_run, depth + 1)
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
                else:
                    target, source_state, target_guid = self.client_a, state_b, state_a.guid
                if not dry_run:
                    ok = self._apply(target, source_state,
                                     self._restore(record.get("b" if chosen == "a" else "a")),
                                     target_guid)
                    result["synced" if ok else "failed"] += 1
                    applied = ok
                else:
                    result["synced"] += 1
                after = self._sides_after(state_a, state_b, source_state, chosen)
                result["changes"].append(f"{state_a.title}: 冲突按 {chosen} 端处理")
        else:
            if a_changed:
                target, source_state = self.client_b, state_a
                target_guid, prev = state_b.guid, base_a
                direction = "A→B"
            else:
                target, source_state = self.client_a, state_b
                target_guid, prev = state_a.guid, base_b
                direction = "B→A"
            if not dry_run:
                ok = self._apply(target, source_state, prev, target_guid)
                result["synced" if ok else "failed"] += 1
                applied = ok
            else:
                result["synced"] += 1
            after = self._sides_after(state_a, state_b, source_state,
                                      "a" if a_changed else "b")
            result["changes"].append(f"{state_a.title}: {direction} {source_state.ts}秒")

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
        else:
            target, source_state, target_guid = self.client_a, state_b, state_a.guid
        if dry_run:
            ok = True
            result["synced"] += 1
        else:
            ok = self._apply(target, source_state, None, target_guid)
            result["synced" if ok else "failed"] += 1
        result["changes"].append(f"{state_a.title}: 首次拉齐按 {chosen} 端（{source_state.ts}秒）")
        if not ok:
            return None
        return self._sides_after(state_a, state_b, source_state, chosen)

    def _sides_after(self, state_a: MediaState, state_b: MediaState,
                     source_state: MediaState, chosen: str):
        """写入成功后两端都应等于来源端的值，各自保留自己的 guid。"""
        if chosen == "a":
            return source_state, self._retarget(source_state, state_b.guid)
        return self._retarget(source_state, state_a.guid), state_b

    def _save_baseline(self, key: str, state_a: MediaState, state_b: MediaState) -> None:
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
