import gzip
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils


MAOYAN_URL = "https://piaofang.maoyan.com/web-heat"
MAOYAN_REFERER = "https://piaofang.maoyan.com/"

try:
    TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
except Exception:
    TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class DramaItem:
    name: str
    platform: str
    online_desc: str


class MaoyanWebHeatParser(HTMLParser):
    """解析猫眼网播热度页面中的剧名和平台上线信息。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current: Optional[str] = None
        self._buffer: List[str] = []
        self.names: List[str] = []
        self.infos: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != "p":
            return

        classes = ""
        for key, value in attrs:
            if key == "class" and value:
                classes = value
                break

        class_list = set(classes.split())
        if "video-name" in class_list:
            self._current = "name"
            self._buffer = []
        elif "web-info" in class_list:
            self._current = "info"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current is not None and data:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "p" or self._current is None:
            return

        text = " ".join("".join(self._buffer).split()).strip()
        if self._current == "name" and text:
            self.names.append(text)
        elif self._current == "info":
            self.infos.append(text)

        self._current = None
        self._buffer = []


class DramaRadar(_PluginBase):
    # 插件名称
    plugin_name = "新剧雷达"
    # 插件描述
    plugin_desc = "监控猫眼网播热度榜，发现新剧后直发 Telegram"
    # 插件图标
    plugin_icon = "Telegram_A.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "mexiaow"
    # 作者主页
    author_url = "https://github.com/mexiaow"
    # 插件配置项ID前缀
    plugin_config_prefix = "dramaradar_"
    # 加载顺序
    plugin_order = 27
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _onlyonce = False
    _bot_token = ""
    _api_base_url = "https://api.telegram.org"
    _chat_id = ""
    _topic_id = 0
    _cron = "0 9 * * *"
    _top_n = 10
    _official_api_base_url = "https://api.telegram.org"
    _retry_times = 2
    _retry_interval = 2
    _fetch_timeout = 15
    _fetch_retries = 3

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._bot_token = (config.get("bot_token") or "").strip()
        self._api_base_url = self.__normalize_api_base_url(
            config.get("api_base_url") or self._official_api_base_url
        )
        self._chat_id = str(config.get("chat_id") or "").strip()
        self._topic_id = self.__to_int(config.get("topic_id"), 0)
        self._cron = (config.get("cron") or self._cron).strip()
        self._top_n = self.__normalize_top_n(config.get("top_n"))

        if self._onlyonce:
            self.scan()
            self._onlyonce = False
            self.__update_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []

        try:
            return [
                {
                    "id": "DramaRadar",
                    "name": "新剧雷达",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.scan,
                    "kwargs": {},
                }
            ]
        except Exception as err:
            logger.error(f"新剧雷达定时任务配置错误：{err}")
            return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
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
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "onlyonce", "label": "立即扫描一次"},
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self.__text_col("bot_token", "Bot Token", "123456:ABCDEF"),
                            self.__text_col("api_base_url", "Telegram API 地址", "https://api.telegram.org"),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self.__text_col("chat_id", "Chat ID", "-1001234567890"),
                            self.__text_col("topic_id", "话题 ID", "10", "number"),
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
                                        "component": "VCronField",
                                        "props": {
                                            "model": "cron",
                                            "label": "执行周期",
                                            "placeholder": "0 9 * * *",
                                        },
                                    }
                                ],
                            },
                            self.__text_col("top_n", "榜单数量", "10", "number"),
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
                                            "text": "首次扫描只建立基线，不发送 Telegram，避免把存量榜单当作新剧刷屏。",
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
            "bot_token": "",
            "api_base_url": self._official_api_base_url,
            "chat_id": "",
            "topic_id": "",
            "cron": "0 9 * * *",
            "top_n": 10,
        }

    def get_page(self) -> List[dict]:
        last_scan = self.get_data("last_scan") or {}
        if not last_scan:
            return [
                {
                    "component": "div",
                    "props": {"class": "text-center"},
                    "text": "暂无扫描记录",
                }
            ]

        return [
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
                                    "type": "success" if last_scan.get("success") else "error",
                                    "variant": "tonal",
                                    "text": self.__build_last_scan_message(last_scan),
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "model-value": last_scan.get("preview") or "",
                                    "label": "最近一次扫描预览",
                                    "readonly": True,
                                    "rows": 14,
                                },
                            }
                        ],
                    },
                ],
            }
        ]

    def stop_service(self):
        pass

    def scan(self):
        """扫描猫眼网播热度榜，发现新剧后发送 Telegram。"""
        try:
            html = self.__fetch_maoyan_html()
            items = self.__parse_drama_items(html)[: self._top_n]
            now = self.__now_shanghai()
            seen_items = self.__load_seen_items()

            if not seen_items:
                self.__save_seen_items(items, now, seen_items)
                message = f"新剧雷达首次扫描已建立基线：count={len(items)}"
                logger.info(message)
                self.__save_last_scan(True, message, items, [])
                return

            new_items = [item for item in items if item.name not in seen_items]
            if new_items:
                logger.info(
                    f"新剧雷达发现新剧：total={len(items)} new={len(new_items)} "
                    f"names={','.join([item.name for item in new_items])}"
                )
                if not self.__send_telegram_message(self.__build_telegram_text(new_items, now)):
                    message = "新剧雷达发送失败：Telegram 请求重试后仍失败"
                    logger.error(message)
                    self.__save_last_scan(False, message, items, new_items)
                    return
            else:
                logger.info(f"新剧雷达本次无新剧：count={len(items)}")

            self.__save_seen_items(items, now, seen_items)
            message = f"新剧雷达扫描完成：count={len(items)} new={len(new_items)}"
            logger.info(message)
            self.__save_last_scan(True, message, items, new_items)
        except Exception as err:
            message = f"新剧雷达扫描异常：{err}"
            logger.error(message, exc_info=True)
            self.__save_last_scan(False, message, [], [])

    def __fetch_maoyan_html(self) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip",
            "Referer": MAOYAN_REFERER,
        }

        last_error: Optional[BaseException] = None
        for attempt in range(1, self._fetch_retries + 1):
            try:
                req = urllib.request.Request(MAOYAN_URL, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=self._fetch_timeout) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                    return raw.decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                last_error = err
                logger.warning(
                    f"新剧雷达抓取失败：attempt={attempt}/{self._fetch_retries} err={err}"
                )
                if attempt < self._fetch_retries:
                    time.sleep(0.8 * attempt)

        raise RuntimeError(f"抓取猫眼网播热度失败：{last_error}")

    def __parse_drama_items(self, html: str) -> List[DramaItem]:
        parser = MaoyanWebHeatParser()
        parser.feed(html)
        if not parser.names:
            raise RuntimeError("未解析到任何片名，可能页面结构已变化或被反爬拦截")

        unique: Dict[str, DramaItem] = {}
        for index, name in enumerate(parser.names):
            if name in unique:
                continue
            raw_info = parser.infos[index] if index < len(parser.infos) else ""
            unique[name] = DramaItem(
                name=name,
                platform=self.__extract_platform(raw_info),
                online_desc=self.__extract_online_desc(raw_info),
            )
        return list(unique.values())

    def __load_seen_items(self) -> Dict[str, Dict[str, str]]:
        seen_items = self.get_data("seen_items") or {}
        if not isinstance(seen_items, dict):
            logger.warning("新剧雷达历史数据格式异常，已按空记录处理")
            return {}
        return seen_items

    def __save_seen_items(
        self,
        items: List[DramaItem],
        dt: datetime,
        seen_items: Dict[str, Dict[str, str]],
    ):
        day = dt.strftime("%Y-%m-%d")
        updated = dict(seen_items)
        for item in items:
            record = updated.get(item.name) or {}
            updated[item.name] = {
                "first_seen": record.get("first_seen") or day,
                "last_seen": day,
                "last_info": item.platform or record.get("last_info") or "",
            }
        self.save_data("seen_items", updated)

    def __send_telegram_message(self, content: str) -> bool:
        if not self._bot_token or not self._chat_id:
            logger.warning("新剧雷达发送失败：Bot Token 或 Chat ID 未配置")
            return False
        return self.__post_telegram("sendMessage", self.__build_text_payload(content))

    def __build_text_payload(self, content: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": content,
            "disable_web_page_preview": True,
        }
        if self._topic_id > 0:
            payload["message_thread_id"] = self._topic_id
        return payload

    def __post_telegram(self, method: str, payload: Dict[str, Any]) -> bool:
        total_attempts = self._retry_times + 1
        url = f"{self._api_base_url}/bot{self._bot_token}/{method}"

        for attempt in range(1, total_attempts + 1):
            response = RequestUtils(
                content_type="application/json",
                accept_type="application/json",
                timeout=20,
            ).post_res(url, json=payload)

            if response is None:
                logger.warning(f"新剧雷达发送无响应：{method} 第 {attempt}/{total_attempts} 次")
                if attempt < total_attempts:
                    time.sleep(self._retry_interval * attempt)
                continue

            try:
                result = response.json()
            except Exception:
                result = {}

            if response.status_code == 200 and result.get("ok") is not False:
                return True

            logger.warning(f"新剧雷达发送失败：{method} {response.status_code} {response.text}")
            if not self.__should_retry(response.status_code) or attempt >= total_attempts:
                break
            time.sleep(self._retry_interval * attempt)

        return False

    def __build_telegram_text(self, new_items: List[DramaItem], dt: datetime) -> str:
        lines = [f"发现猫眼网播热度新剧（{len(new_items)}部）"]
        lines.extend([self.__format_item_for_message(item) for item in new_items])
        lines.append(f"来源：{MAOYAN_URL}")
        lines.append(f"时间：{dt.strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(lines)

    def __save_last_scan(
        self,
        success: bool,
        message: str,
        items: List[DramaItem],
        new_items: List[DramaItem],
    ):
        preview_lines = [f"抓取：{len(items)} 部", f"新增：{len(new_items)} 部"]
        if new_items:
            preview_lines.extend(["", "新增剧集："])
            preview_lines.extend([self.__format_item_for_message(item) for item in new_items])
        elif items:
            preview_lines.extend(["", "本次榜单："])
            preview_lines.extend([self.__format_item_for_message(item) for item in items])

        self.save_data(
            "last_scan",
            {
                "success": success,
                "message": message,
                "preview": "\n".join(preview_lines)[:3000],
                "time": self.__now_shanghai().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

    def __update_config(self):
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "bot_token": self._bot_token,
                "api_base_url": self._api_base_url,
                "chat_id": self._chat_id,
                "topic_id": self._topic_id,
                "cron": self._cron,
                "top_n": self._top_n,
            }
        )

    @staticmethod
    def __text_col(model: str, label: str, placeholder: str, field_type: str = None) -> Dict[str, Any]:
        props = {"model": model, "label": label, "placeholder": placeholder}
        if field_type:
            props["type"] = field_type
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": 6},
            "content": [{"component": "VTextField", "props": props}],
        }

    @staticmethod
    def __format_item_for_message(item: DramaItem) -> str:
        parts = []
        if item.platform:
            parts.append(item.platform)
        if item.online_desc:
            parts.append(item.online_desc)
        if parts:
            return f"- {item.name}（{'；'.join(parts)}）"
        return f"- {item.name}"

    @staticmethod
    def __extract_platform(info: str) -> str:
        if not info:
            return ""
        index = info.find("上线")
        base = info[:index] if index >= 0 else info
        return " ".join(base.split()).strip()

    @staticmethod
    def __extract_online_desc(info: str) -> str:
        if not info:
            return ""
        index = info.find("上线")
        if index < 0:
            return ""
        return " ".join(info[index:].split()).strip()

    @staticmethod
    def __normalize_api_base_url(api_base_url: str) -> str:
        api_base_url = (api_base_url or "").strip().rstrip("/")
        if not api_base_url:
            return DramaRadar._official_api_base_url
        if not api_base_url.startswith(("http://", "https://")):
            return f"https://{api_base_url}"
        return api_base_url

    @staticmethod
    def __normalize_top_n(value: Any) -> int:
        top_n = DramaRadar.__to_int(value, 10)
        if top_n <= 0:
            return 10
        return min(top_n, 100)

    @staticmethod
    def __should_retry(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    @staticmethod
    def __build_last_scan_message(last_scan: Dict[str, Any]) -> str:
        message = last_scan.get("message") or "暂无状态"
        scan_time = last_scan.get("time")
        if scan_time:
            return f"{message}，时间：{scan_time}"
        return message

    @staticmethod
    def __now_shanghai() -> datetime:
        return datetime.now(tz=TZ_SHANGHAI)

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
