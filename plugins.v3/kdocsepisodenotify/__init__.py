"""
金山文档新剧提醒（MoviePilot V3 插件）

从金山文档（KDocs）追剧表里解析「本月更新【国产剧】」「本月更新【国外剧】」两个区段，
只对新出现的剧集发送 Telegram 提醒：发过的不再重复，跟更新到第几集无关。

设计原则（保持轻量）：
  1. 只监控国产剧、国外剧两个区段，需要变动直接改 WATCH_SECTIONS；
  2. 配置项只有 8 个，其余行为全部写死；
  3. 去重完全依赖插件自己的已提醒记录，与 MoviePilot 订阅无关；
  4. V3 规范：app.sdk.* 稳定接口、get_service 托管定时、save_data 存状态。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from app.sdk import scheduler as scheduler_sdk
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.sdk.plugin import _PluginBase


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 需要监控的区段（文档里写作「本月更新【国产剧】」）。
#: 以后想加动漫，在这里加 "热门动漫" 之类即可（包含匹配）。
WATCH_SECTIONS: Tuple[str, ...] = ("国产剧", "国外剧")

#: 金山文档下载接口
KDOCS_DOWNLOAD_API = "https://www.kdocs.cn/api/v3/office/file/{file_id}/download"

#: 默认文档与兜底 File ID（doc_url 解析失败时使用）
DEFAULT_DOC_URL = "https://www.kdocs.cn/l/cgqWkD4v1nHK"
DEFAULT_FILE_ID = "206871482430"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

#: 已提醒记录保留天数（超过且已从文档消失才清理）
RETAIN_DAYS = 180
#: 单次最多提醒条数，防文档大改时刷屏
MAX_NOTIFY = 30
#: 单条消息长度上限（Telegram 4096，留余量）
MESSAGE_LIMIT = 3800

# 区段标题：「🟨🟩🟦丨本月更新【国产剧】丨…」
_HEADER_RE = re.compile(r"本月更新\s*【([^】]{1,20})】")
# 条目行：以「【4K国产剧】」开头
_TAG_RE = re.compile(r"^【([^】]{1,20})】")
# 年份：(2026) / （2026） / (2020-2025)
_YEAR_RE = re.compile(r"[（(]\s*((?:19|20)\d{2}(?:\s*[-–~至]\s*(?:\d{4}|\d{2}))?)\s*[)）]")
# 名称截止符：技术标签、属性括号、分隔符
_NAME_SPLIT_RE = re.compile(r"[\[［（(丨|｜.。]")

_CN_NUMS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
}

_SEASON_PATTERNS = (
    re.compile(r"第\s*(\d{1,2})\s*季\s*$"),
    re.compile(r"第\s*([一二三四五六七八九十]{1,3})\s*季\s*$"),
    re.compile(r"[Ss]eason\s*(\d{1,2})\s*$"),
    re.compile(r"(?<![A-Za-z0-9])[Ss](\d{1,2})(?:\s*[Ee]\d+)?\s*$"),
)
# 名称里没有季数时，回退看独立的「[第八季]」「（第3季）」
_SEASON_BRACKET_RE = re.compile(
    r"[\[（(]\s*第\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*季\s*[\]）)]"
)

#: 总集数：「共40集」「共 12 期」「40集全」
_TOTAL_RE = re.compile(
    r"共\s*(?:\d{1,4}\s*[-–]\s*)?(\d{1,4})\s*[集期]|(\d{1,4})\s*[集期]\s*全"
)

#: 行内是否带更新痕迹：既是「这行是剧集条目」的旁证，也是区段结束的判断依据
_PROGRESS_RE = re.compile(r"更新|更至|更\s*\d|共\s*\d+\s*[集期]|\d+\s*[集期]\s*全")

#: 非剧集标签，命中直接忽略
_IGNORE_TAGS = ("游戏", "演唱会", "无损音乐", "合集")

#: 进入合集/公告区的标志，命中即结束当前区段
_STOP_KEYWORDS = (
    "明星合集专区", "置底查找", "温馨提示", "交流群", "订阅群",
    "免责声明", "公众号", "腾讯频道",
)

try:
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # 少数宿主缺少 tzdata 时退化为固定东八区
    _TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


# ---------------------------------------------------------------------------
# 解析工具（纯函数，便于单测）
# ---------------------------------------------------------------------------


@dataclass
class DocItem:
    """文档中解析出的一条剧集条目。"""

    category: str
    tag: str
    name: str
    raw: str
    year: Optional[str] = None
    season: Optional[int] = None
    #: 文档里写的总集数，仅用于详情页展示（不参与任何提醒判定）
    total: Optional[int] = None

    @property
    def key(self) -> str:
        """去重键：只由名称+季数决定，与分类、集数无关。"""
        return build_item_key(self.name, self.season)

    @property
    def season_label(self) -> str:
        """季数的展示文本。"""
        return f" S{self.season}" if self.season else ""


def normalize_spaces(text: str) -> str:
    """压缩空白字符。"""
    return re.sub(r"\s+", " ", (text or "").replace("\u3000", " ")).strip()


def normalize_name_key(name: str) -> str:
    """名称归一化：去空白、去尾部标点、统一大小写，避免写法漂移导致重复提醒。"""
    cleaned = re.sub(r"\s+", "", name or "")
    cleaned = re.sub(r"[\.。\,，、·:：!！\?？\-_]+$", "", cleaned)
    return cleaned.casefold()


def build_item_key(name: str, season: Optional[int]) -> str:
    """构造去重键，季数缺省按第 1 季处理。"""
    return f"{normalize_name_key(name)}|S{season or 1}"


def parse_header_category(text: str) -> Optional[str]:
    """从区段标题行提取分类名，如「本月更新【国产剧】」→ 国产剧。"""
    match = _HEADER_RE.search(text or "")
    return match.group(1).strip() if match else None


def resolve_season(name: str, full_text: str = "") -> Tuple[Optional[int], str]:
    """从名称（必要时回退全文的独立括号）提取季数，并从名称中剥离。"""
    for pattern in _SEASON_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        raw = match.group(1)
        season = int(raw) if raw.isdigit() else _CN_NUMS.get(raw)
        if season:
            return season, name[: match.start()].strip()
    if full_text:
        match = _SEASON_BRACKET_RE.search(full_text)
        if match:
            raw = match.group(1)
            season = int(raw) if raw.isdigit() else _CN_NUMS.get(raw)
            if season:
                return season, name
    return None, name


def parse_item_row(text: str) -> Optional[DocItem]:
    """
    把一行数据解析成 DocItem；无法识别为剧集条目时返回 None。

    条件是：以「【标签】」开头，且要么带年份，要么带更新/集数痕迹。
    集数只作为「这行确实是条目」的旁证，不参与任何提醒判定。
    """
    normalized = normalize_spaces(text)
    tag_match = _TAG_RE.match(normalized)
    if not tag_match:
        return None

    tag = tag_match.group(1)
    body = normalized[tag_match.end():]
    year_match = _YEAR_RE.search(body)
    year = year_match.group(1).strip() if year_match else None

    name_part = _NAME_SPLIT_RE.split(body, maxsplit=1)[0].strip()
    name_part = re.sub(r"^[\s\-–—·:：.]+", "", name_part)
    if not name_part:
        return None

    season, name = resolve_season(name_part, normalized)
    name = re.sub(r"[\s\.\,，、·:：]+$", "", name).strip()
    if not name:
        return None

    if not year and not _PROGRESS_RE.search(normalized):
        return None

    total_match = _TOTAL_RE.search(normalized)
    total = None
    if total_match:
        total = int(next(g for g in total_match.groups() if g))

    return DocItem(
        category="",
        tag=tag,
        name=name,
        raw=normalized,
        year=year,
        season=season,
        total=total,
    )


def merge_cell_text(cells: Iterable[Any]) -> str:
    """把一行里的非空单元格拼成一行文本。"""
    parts: List[str] = []
    for cell in cells:
        if cell is None:
            continue
        text = str(cell).strip()
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


def pick_monthly_sheet(sheet_names: List[str]) -> Optional[str]:
    """从 sheet 名里挑出最新月份的月度更新表。"""
    best: Optional[Tuple[int, int, str]] = None
    pattern = re.compile(r"(\d{4})\s*[-年]\s*(\d{1,2})\s*月")
    for name in sheet_names:
        match = pattern.search(name or "")
        if not match:
            continue
        candidate = (int(match.group(1)), int(match.group(2)), name)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else (sheet_names[0] if sheet_names else None)


def select_new_items(
    items: List[DocItem],
    state: Dict[str, Dict[str, Any]],
    category_state: Dict[str, str],
) -> List[DocItem]:
    """
    挑出需要提醒的剧集：只认插件自己的已提醒记录，与 MoviePilot 订阅无关。

    - 键不在记录里 → 这是新剧，提醒；
    - 键已在记录里 → 永不重复提醒；
    - 某个分类第一次被扫描 → 只记基线不提醒（避免首轮刷屏）。
    """
    pending: List[DocItem] = []
    for item in items:
        if item.key in state:
            continue
        if item.category not in category_state:
            logger.info(
                f"金山文档新剧提醒：分类[{item.category}]首次扫描，"
                f"记录基线不提醒：{item.name}{item.season_label}"
            )
            continue
        pending.append(item)
    return pending


def parse_sheet_rows(
    rows: Iterable[Any],
    sections: Tuple[str, ...] = WATCH_SECTIONS,
) -> Tuple[List[DocItem], List[str], int]:
    """
    解析一个工作表：按「本月更新【分类】」切区段，只收集监控中的分类。

    :return: (条目列表, 文档中检测到的区段标题, 被跳过的行数)
    """
    items: List[DocItem] = []
    seen: Dict[str, DocItem] = {}
    headers: List[str] = []
    skipped = 0
    header_category = ""
    watching = False

    for row in rows:
        text = merge_cell_text(row)
        if not text:
            continue
        # 条目文本以该行第一个「【标签】…」单元格为准，避免把链接列拼进名称
        primary = next(
            (
                cell
                for cell in (str(c).strip() for c in row if c is not None)
                if cell.startswith("【")
            ),
            text,
        )

        header = parse_header_category(primary)
        if header:
            header_category = header
            if header not in headers:
                headers.append(header)
            watching = any(keyword in header for keyword in sections)
            continue

        if not header_category:
            continue

        if any(keyword in text for keyword in _STOP_KEYWORDS):
            header_category = ""
            watching = False
            continue

        item = parse_item_row(primary)
        if not item:
            # 无法识别为条目：说明已离开「本月更新」区段（进入合集/说明区）
            # 只有监控中的区段才提示，避免无关区段刷日志
            if watching:
                logger.warning(
                    f"金山文档新剧提醒：区段[{header_category}] 结束于无法解析的行："
                    f"{text[:60]}（若该行其实是剧集，请检查文档格式是否改动）"
                )
            else:
                logger.debug(
                    f"金山文档新剧提醒：区段[{header_category}] 结束于：{text[:40]}"
                )
            header_category = ""
            watching = False
            continue

        if not watching:
            continue
        if any(keyword in item.tag for keyword in _IGNORE_TAGS):
            skipped += 1
            continue

        item.category = header_category
        previous = seen.get(item.key)
        # 同一部剧多行时，优先保留带更新痕迹的那一行（在播行优于合集行）
        if previous is None or (
            _PROGRESS_RE.search(item.raw) and not _PROGRESS_RE.search(previous.raw)
        ):
            seen[item.key] = item

    return list(seen.values()), headers, skipped


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> List[str]:
    """按行切分长消息，避免超过 Telegram 单条上限。"""
    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def escape_html(text: str) -> str:
    """转义 Telegram HTML 模式下的特殊字符。"""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# 插件主体
# ---------------------------------------------------------------------------


class KdocsEpisodeNotify(_PluginBase):
    """金山文档新剧提醒：只提醒新出现的剧集。"""

    plugin_name = "金山文档新剧提醒"
    plugin_desc = "解析金山文档追剧表的国产剧/国外剧区段，只对新剧集发 Telegram 提醒。"
    plugin_icon = "Telegram_A.png"
    plugin_version = "2.1.0"
    plugin_author = "mexiaow"
    author_url = "https://github.com/zoom521241/MoviePilot-Plugins"
    plugin_config_prefix = "kdocsepisodenotify_"
    plugin_order = 20
    auth_level = 1

    # 运行期状态（每次 init_plugin 复位）
    _enabled: bool = False
    _cron: str = "1 21 * * *"
    _doc_url: str = DEFAULT_DOC_URL
    _cookies: str = ""
    _tg_bot_token: str = ""
    _tg_chat_id: str = ""
    _tg_topic_id: str = ""
    _file_id: str = ""
    _detected_headers: List[str] = []

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def init_plugin(self, config: Optional[dict] = None) -> None:
        """读取配置并复位状态，允许重复调用。"""
        self._enabled = False
        self._cron = "1 21 * * *"
        self._doc_url = DEFAULT_DOC_URL
        self._cookies = ""
        self._tg_bot_token = ""
        self._tg_chat_id = ""
        self._tg_topic_id = ""
        self._file_id = ""
        self._detected_headers = []

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._cron = str(config.get("cron") or "1 21 * * *").strip() or "1 21 * * *"
        self._doc_url = str(config.get("doc_url") or DEFAULT_DOC_URL).strip()
        self._cookies = str(config.get("cookies") or "").strip()
        self._tg_bot_token = str(config.get("tg_bot_token") or "").strip()
        self._tg_chat_id = str(config.get("tg_chat_id") or "").strip()
        self._tg_topic_id = str(config.get("tg_topic_id") or "").strip()

        if not self._enabled:
            logger.info("金山文档新剧提醒：插件未启用")
            return
        if not self._cookies:
            logger.warning("金山文档新剧提醒：未配置金山文档 Cookie，无法执行")
            return
        if not self._tg_bot_token or not self._tg_chat_id:
            logger.warning("金山文档新剧提醒：未配置 Telegram Bot Token / Chat ID，无法发提醒")

        logger.info(
            f"金山文档新剧提醒：已启用，监控区段={'、'.join(WATCH_SECTIONS)}，"
            f"cron={self._cron}，记录保留 {RETAIN_DAYS} 天"
        )

        if config.get("onlyonce"):
            if self.__schedule_once():
                payload = dict(config)
                payload["onlyonce"] = False
                self.update_config(payload)

    def get_state(self) -> bool:
        """插件是否处于可运行状态。"""
        return bool(self._enabled and self._cookies)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """本插件不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """本插件不注册 API。"""
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        """注册周期扫描任务，由宿主调度器统一管理。"""
        if not self.get_state():
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except Exception as err:
            logger.error(f"金山文档新剧提醒：cron 表达式无效 [{self._cron}]：{err}")
            return []
        return [
            {
                "id": f"{self.__class__.__name__}.Scan",
                "name": "金山文档新剧提醒",
                "trigger": trigger,
                "func": self.scan,
                "kwargs": {},
            }
        ]

    def stop_service(self) -> None:
        """取消本插件登记的一次性任务。"""
        try:
            scheduler_sdk.remove_plugin_once_job(self.__class__.__name__, "scan_once")
        except Exception as err:  # 调度器未就绪时忽略
            logger.debug(f"金山文档新剧提醒：清理一次性任务失败：{err}")

    # ------------------------------------------------------------------
    # 配置页与详情页
    # ------------------------------------------------------------------
    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """配置页面：只保留 8 个真正会改动的配置项。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "保存后立即执行一次",
                                            "hint": "首次配置后用来确认解析是否正常",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "定时规则（cron）",
                                            "placeholder": "1 21 * * *",
                                            "hint": "5 段 cron：分 时 日 月 周，默认每天 21:01 扫描",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "doc_url",
                                            "label": "金山文档链接",
                                            "placeholder": DEFAULT_DOC_URL,
                                            "hint": "分享链接。换文档只改这里即可，File ID 会自动从链接解析。",
                                            "clearable": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookies",
                                            "label": "金山文档 Cookie",
                                            "placeholder": "浏览器登录 kdocs.cn 后，从开发者工具复制完整 Cookie",
                                            "rows": 3,
                                            "hint": "必填。Cookie 过期后日志会提示，需重新复制。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "tg_bot_token",
                                            "label": "Telegram Bot Token",
                                            "placeholder": "123456:ABCDEF",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "tg_chat_id",
                                            "label": "Telegram Chat ID",
                                            "placeholder": "-1001234567890",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "tg_topic_id",
                                            "label": "话题 ID（可选）",
                                            "placeholder": "如 12",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": (
                                                f"只监控区段：{'、'.join(WATCH_SECTIONS)}（如需变动请改代码里的 WATCH_SECTIONS）。\n"
                                                "只提醒首次出现的剧集，已提醒过的永不重复，与更新到第几集无关。\n"
                                                f"已提醒记录保留 {RETAIN_DAYS} 天；单次最多推送 {MAX_NOTIFY} 条。"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cron": "1 21 * * *",
            "doc_url": DEFAULT_DOC_URL,
            "cookies": "",
            "tg_bot_token": "",
            "tg_chat_id": "",
            "tg_topic_id": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        """展示上次扫描结果，出问题时方便定位。"""
        last = self.get_data("last_scan") or {}
        recent = self.get_data("recent_notified") or []
        snapshot = self.get_data("last_items") or []
        content: List[dict] = []
        if last:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "success" if last.get("ok") else "warning",
                        "variant": "tonal",
                        "text": (
                            f"上次扫描：{last.get('time', '-')}"
                            f"　|　sheet：{last.get('sheet', '-')}"
                            f"　|　命中 {last.get('items', 0)} 条"
                            f"　|　新剧 {last.get('notified', 0)} 条"
                            + (f"　|　错误：{last.get('error')}" if last.get("error") else "")
                        ),
                    },
                }
            )
            if last.get("detected_headers"):
                content.append(
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "文档区段：" + "、".join(last["detected_headers"]),
                        },
                    }
                )
        if snapshot:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "success",
                        "variant": "tonal",
                        "density": "compact",
                        "text": f"本轮识别到 {len(snapshot)} 部剧集（每轮覆盖，用于核对抓取结果）",
                    },
                }
            )
            rows: List[List[str]] = []
            for row in snapshot:
                title = f"{row.get('name', '')}"
                if row.get("season"):
                    title += f" S{row['season']}"
                if row.get("year"):
                    title += f" ({row['year']})"
                rows.append(
                    [
                        str(row.get("category") or "-"),
                        title,
                        f"共{row['total']}集" if row.get("total") else "-",
                        str(row.get("status") or ""),
                    ]
                )
            content.append(self.__build_table(["区段", "剧名", "集数", "状态"], rows))
        if recent:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                        "text": "最近提醒",
                    },
                }
            )
            content.append(
                self.__build_table(
                    ["时间", "区段", "剧名"],
                    [
                        [
                            str(row.get("time") or ""),
                            str(row.get("category") or ""),
                            f"{row.get('name', '')}{row.get('season', '')}",
                        ]
                        for row in recent[:10]
                    ],
                )
            )
        if not content:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "secondary",
                        "variant": "tonal",
                        "text": "暂无扫描记录。填好 Cookie 与 Telegram 后，勾选「保存后立即执行一次」即可验证。",
                    },
                }
            )
        return content

    @staticmethod
    def __build_table(headers: List[str], rows: List[List[str]]) -> dict:
        """
        构造一个只读表格。

        Vuetify 的 VAlert.text 不保留换行，多行数据必须用表格逐行渲染，
        这里沿用官方 V3 插件（autosignin）验证过的 VTable + thead/tbody 写法。
        """
        return {
            "component": "VTable",
            "props": {"hover": True, "density": "compact"},
            "content": [
                {
                    "component": "thead",
                    "content": [
                        {
                            "component": "tr",
                            "content": [
                                {
                                    "component": "th",
                                    "props": {"class": "text-start"},
                                    "text": header,
                                }
                                for header in headers
                            ],
                        }
                    ],
                },
                {
                    "component": "tbody",
                    "content": [
                        {
                            "component": "tr",
                            "content": [
                                {
                                    "component": "td",
                                    "props": {"class": "text-start"},
                                    "text": cell,
                                }
                                for cell in row
                            ],
                        }
                        for row in rows
                    ],
                },
            ],
        }

    # ------------------------------------------------------------------
    # 扫描主流程
    # ------------------------------------------------------------------
    def scan(self) -> Dict[str, Any]:
        """扫描文档并对新剧发送提醒，返回结果摘要。"""
        started = datetime.now(_TZ)
        result: Dict[str, Any] = {
            "ok": False,
            "time": started.strftime("%Y-%m-%d %H:%M:%S"),
            "sheet": "",
            "items": 0,
            "notified": 0,
            "detected_headers": [],
            "error": "",
        }

        if not self._cookies:
            result["error"] = "未配置金山文档 Cookie"
            logger.error(f"金山文档新剧提醒：{result['error']}")
            return result

        openpyxl = self.__load_openpyxl()
        if openpyxl is None:
            result["error"] = "缺少依赖 openpyxl"
            return result

        try:
            xlsx_path = self.__download_workbook()
            if not xlsx_path:
                result["error"] = "文档下载失败"
                self.__save_scan_result(result)
                return result

            sheet_name, items = self.__parse_workbook(xlsx_path, openpyxl)
            result["sheet"] = sheet_name or ""
            result["items"] = len(items)
            result["detected_headers"] = list(self._detected_headers)
            logger.info(
                f"金山文档新剧提醒：解析 sheet[{sheet_name}] 命中 {len(items)} 条"
            )

            state: Dict[str, Dict[str, Any]] = self.get_data("episode_state") or {}
            category_state: Dict[str, str] = self.get_data("category_state") or {}
            new_items = select_new_items(items, state, category_state)

            notified = 0
            skipped_keys: set = set()
            if new_items:
                pending = new_items[:MAX_NOTIFY]
                overflow = len(new_items) - len(pending)
                if overflow > 0:
                    logger.warning(
                        f"金山文档新剧提醒：新剧 {len(new_items)} 条超过上限 {MAX_NOTIFY}，"
                        f"本次先推 {len(pending)} 条，其余下轮继续"
                    )
                if not self.__notify(pending, overflow):
                    result["error"] = "通知发送失败，本轮状态未更新"
                    self.__save_scan_result(result)
                    return result
                notified = len(pending)
                # 超出上限的条目本轮不写状态，下一轮继续推送
                skipped_keys = {item.key for item in new_items[notified:]}
            else:
                logger.info("金山文档新剧提醒：没有新剧，本轮不发送提醒")

            now = started.strftime("%Y-%m-%d %H:%M:%S")
            self.__commit_state(
                items, state, category_state, new_items[:notified], skipped_keys, now
            )
            self.__save_items_snapshot(items, state, new_items[:notified])
            result["ok"] = True
            result["notified"] = notified
            self.__save_scan_result(result)
            return result
        except Exception as err:  # 兜底：不让异常打断宿主调度器
            logger.exception(f"金山文档新剧提醒：扫描异常：{err}")
            result["error"] = str(err)
            self.__save_scan_result(result)
            return result

    # ------------------------------------------------------------------
    # 文档获取
    # ------------------------------------------------------------------
    @staticmethod
    def __load_openpyxl():
        """惰性加载 openpyxl，缺依赖时只影响扫描动作。"""
        try:
            import openpyxl  # noqa: PLC0415 - 刻意延迟导入
            return openpyxl
        except ImportError as err:
            logger.error(
                "金山文档新剧提醒：缺少依赖 openpyxl，无法解析文档，"
                f"请重新安装插件以触发依赖安装（{err}）"
            )
            return None

    def __proxies(self) -> Optional[dict]:
        """跟随宿主代理设置。"""
        return getattr(settings, "PROXY", None) or None

    def __headers(self) -> Dict[str, str]:
        """KDocs 请求头（Cookie 只放内存，不写日志）。"""
        return {
            "User-Agent": DEFAULT_UA,
            "Referer": self._doc_url,
            "Accept": "*/*",
            "Cookie": self._cookies,
        }

    def __resolve_file_id(self) -> str:
        """从分享链接解析文档 File ID，失败时回退默认值。"""
        if self._file_id:
            return self._file_id
        share = re.search(r"/l/([A-Za-z0-9_-]{6,})", self._doc_url or "")
        if share:
            try:
                html = RequestUtils(
                    headers=self.__headers(), timeout=20, proxies=self.__proxies()
                ).get(f"https://www.kdocs.cn/l/{share.group(1)}")
                if html:
                    found = re.search(
                        r"(?:fileid|file_id|fileId)[\"']?\s*[:=]\s*[\"']?(\d{6,})",
                        html,
                    )
                    if found:
                        self._file_id = found.group(1)
                        logger.info(
                            f"金山文档新剧提醒：从文档链接解析到 File ID {self._file_id}"
                        )
                        return self._file_id
            except Exception as err:
                logger.warning(f"金山文档新剧提醒：解析 File ID 失败：{err}")
        self._file_id = DEFAULT_FILE_ID
        logger.info(f"金山文档新剧提醒：使用默认 File ID {self._file_id}")
        return self._file_id

    def __download_workbook(self):
        """从 KDocs 下载 xlsx 到插件数据目录，返回本地路径。"""
        file_id = self.__resolve_file_id()
        api = KDOCS_DOWNLOAD_API.format(file_id=file_id)
        utils = RequestUtils(headers=self.__headers(), timeout=20, proxies=self.__proxies())
        try:
            response = utils.get_res(api)
            if response is None:
                logger.error("金山文档新剧提醒：获取下载链接失败（无响应）")
                return None
            if response.status_code != 200:
                logger.error(
                    f"金山文档新剧提醒：获取下载链接失败 HTTP {response.status_code}，"
                    f"请检查 Cookie 是否过期（响应片段：{response.text[:120]}）"
                )
                return None
            try:
                meta = response.json()
            except Exception:
                logger.error(
                    f"金山文档新剧提醒：下载接口返回非 JSON（片段：{response.text[:120]}）"
                )
                return None
            download_url = meta.get("download_url") or meta.get("url")
            if not download_url:
                logger.error(
                    f"金山文档新剧提醒：下载链接为空（响应键：{list(meta.keys())}）"
                )
                return None

            file_res = RequestUtils(timeout=60, proxies=self.__proxies()).get_res(download_url)
            if file_res is None or file_res.status_code != 200:
                logger.error("金山文档新剧提醒：下载文档内容失败")
                return None
            content = file_res.content or b""
            if not content.startswith(b"PK"):
                logger.error(
                    "金山文档新剧提醒：下载内容不是 xlsx（可能 Cookie 失效或文档权限变化）"
                )
                return None

            target = self.get_data_path() / "doc.xlsx"
            target.write_bytes(content)
            logger.info(
                f"金山文档新剧提醒：文档已更新，{len(content) / 1024:.1f} KB → {target}"
            )
            return target
        except Exception as err:
            logger.error(f"金山文档新剧提醒：下载文档异常：{err}")
            return None

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    def __parse_workbook(self, xlsx_path, openpyxl) -> Tuple[str, List[DocItem]]:
        """解析工作簿，返回 (sheet 名, 条目列表)。"""
        workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
        try:
            sheet_name = pick_monthly_sheet(workbook.sheetnames)
            if not sheet_name:
                logger.error("金山文档新剧提醒：文档中没有可用工作表")
                return "", []
            worksheet = workbook[sheet_name]
            items, headers, skipped = parse_sheet_rows(
                worksheet.iter_rows(values_only=True)
            )
            self._detected_headers = headers
            if skipped:
                logger.debug(f"金山文档新剧提醒：按标签忽略 {skipped} 行")
            if not items:
                logger.warning(
                    "金山文档新剧提醒：监控区段没有解析到条目，"
                    f"文档里检测到的区段为：{'、'.join(headers) or '无'}"
                )
            return sheet_name, items
        finally:
            try:
                workbook.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def __commit_state(
        self,
        items: List[DocItem],
        state: Dict[str, Dict[str, Any]],
        category_state: Dict[str, str],
        notified_items: List[DocItem],
        skipped_keys: set,
        now: str,
    ) -> None:
        """写入已提醒记录并清理过期条目。"""
        notified_keys = {item.key for item in notified_items}
        for item in items:
            if item.key in skipped_keys:
                continue  # 超上限未推送的条目，留给下一轮
            record = state.get(item.key) or {}
            record.update(
                {
                    "name": item.name,
                    "category": item.category,
                    "year": item.year,
                    "season": item.season,
                    "last_seen": now,
                }
            )
            record.setdefault("first_seen", now)
            if item.key in notified_keys:
                record["notified_at"] = now
            state[item.key] = record

        if not skipped_keys:
            for item in items:
                category_state.setdefault(item.category, now)

        # 只清理「早已从文档消失」的记录，仍在文档中的不会因清理而重复提醒
        cutoff = (datetime.now(_TZ) - timedelta(days=RETAIN_DAYS)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        for key in [
            key
            for key, record in state.items()
            if str(record.get("last_seen") or "") < cutoff
        ]:
            state.pop(key, None)

        self.save_data("episode_state", state)
        self.save_data("category_state", category_state)

        if notified_items:
            recent = self.get_data("recent_notified") or []
            for item in notified_items:
                recent.insert(
                    0,
                    {
                        "time": now,
                        "category": item.category,
                        "name": item.name,
                        "season": item.season_label,
                    },
                )
            self.save_data("recent_notified", recent[:20])

    def __save_items_snapshot(
        self,
        items: List[DocItem],
        state: Dict[str, Dict[str, Any]],
        notified_items: List[DocItem],
    ) -> None:
        """
        保存本轮识别到的条目清单，供详情页核对抓取是否正常。

        只做展示用途：每轮覆盖，不参与去重判定。
        """
        notified_keys = {item.key for item in notified_items}
        rows: List[Dict[str, Any]] = []
        for item in items:
            record = state.get(item.key) or {}
            if item.key in notified_keys:
                status = "本次提醒"
            else:
                # 基线记录没有 notified_at，用首次记录时间兜底展示
                seen_at = record.get("notified_at") or record.get("first_seen") or ""
                status = f"已提醒 {str(seen_at)[5:10]}" if seen_at else "已提醒"
            rows.append(
                {
                    "category": item.category,
                    "name": item.name,
                    "season": item.season,
                    "year": item.year,
                    "total": item.total,
                    "status": status,
                }
            )
        try:
            self.save_data("last_items", rows[:300])
        except Exception as err:
            logger.error(f"金山文档新剧提醒：保存识别清单失败：{err}")

    # ------------------------------------------------------------------
    # 通知
    # ------------------------------------------------------------------
    def __build_message(self, items: List[DocItem], overflow: int = 0) -> str:
        """把待提醒条目拼成 Telegram HTML 消息。"""
        grouped: Dict[str, List[DocItem]] = {}
        for item in items:
            grouped.setdefault(item.category, []).append(item)

        lines: List[str] = [
            "📺 <b>金山文档新剧提醒</b>",
            f"🕒 {datetime.now(_TZ).strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for category, group in grouped.items():
            lines.append(f"<b>{escape_html(category)}</b>")
            for item in group:
                label = f"{escape_html(item.name)}{escape_html(item.season_label)}"
                if item.year:
                    label += f" ({escape_html(item.year)})"
                if item.total:
                    label += f" 共{item.total}集"
                lines.append(f"• {label}")
            lines.append("")
        if overflow > 0:
            lines.append(f"（另有 {overflow} 部下轮继续推送）")
        lines.append(f"共 {len(items)} 部新剧")
        return "\n".join(lines).strip()

    def __notify(self, items: List[DocItem], overflow: int = 0) -> bool:
        """发送提醒，返回是否全部成功。"""
        if not self._tg_bot_token or not self._tg_chat_id:
            logger.error("金山文档新剧提醒：未配置 Telegram Bot Token / Chat ID，无法发送")
            return False
        success = True
        for message in split_message(self.__build_message(items, overflow)):
            success = self.__send_telegram(message) and success
        return success

    def __send_telegram(self, message: str) -> bool:
        """调用 Telegram Bot API 直发消息，失败重试 2 次。"""
        payload: Dict[str, Any] = {
            "chat_id": self._tg_chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if self._tg_topic_id:
            try:
                payload["message_thread_id"] = int(self._tg_topic_id)
            except ValueError:
                logger.warning(f"金山文档新剧提醒：话题 ID 非数字，已忽略：{self._tg_topic_id}")

        url = f"https://api.telegram.org/bot{self._tg_bot_token}/sendMessage"
        attempts = 3
        for attempt in range(1, attempts + 1):
            response = RequestUtils(
                content_type="application/json", timeout=20, proxies=self.__proxies()
            ).post_res(url, json=payload)
            if response is None:
                logger.warning(
                    f"金山文档新剧提醒：Telegram 无响应（{attempt}/{attempts}）"
                )
                continue
            try:
                body = response.json()
            except Exception:
                body = {}
            if response.status_code == 200 and body.get("ok") is not False:
                logger.info("金山文档新剧提醒：Telegram 提醒发送成功")
                return True
            logger.warning(
                f"金山文档新剧提醒：Telegram 发送失败 {response.status_code} "
                f"{body.get('description') or response.text[:160]}（{attempt}/{attempts}）"
            )
            if response.status_code not in (429, 500, 502, 503, 504):
                return False
            if attempt < attempts:
                import time as _time

                _time.sleep(1.5 * attempt)
        return False

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def __schedule_once(self) -> bool:
        """通过宿主调度器登记一次性扫描任务。"""
        func = getattr(scheduler_sdk, "add_plugin_once_job", None)
        if func is None:
            logger.warning("金山文档新剧提醒：宿主不支持一次性任务接口，忽略「立即执行」")
            return False
        try:
            return bool(
                func(
                    self.__class__.__name__,
                    "scan_once",
                    self.scan,
                    "金山文档新剧提醒执行一次",
                    delay_seconds=3,
                )
            )
        except Exception as err:
            logger.error(f"金山文档新剧提醒：登记一次性任务失败：{err}")
            return False

    def __save_scan_result(self, result: Dict[str, Any]) -> None:
        """保存最近一次扫描摘要，供详情页展示。"""
        try:
            self.save_data("last_scan", result)
        except Exception as err:
            logger.error(f"金山文档新剧提醒：保存扫描结果失败：{err}")


__all__ = [
    "KdocsEpisodeNotify",
    "DocItem",
    "WATCH_SECTIONS",
    "parse_item_row",
    "parse_header_category",
    "parse_sheet_rows",
    "build_item_key",
    "select_new_items",
    "pick_monthly_sheet",
    "split_message",
    "escape_html",
]
