import html
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.log import logger
from app.plugins import _PluginBase
from app.db.transferhistory_oper import TransferHistoryOper
from app.utils.http import RequestUtils


class EmbyDailyReports(_PluginBase):
    # 插件名称
    plugin_name = "Emby入库日报"
    # 插件描述
    plugin_desc = "定时统计 MoviePilot 入库记录并发送到 Telegram 话题"
    # 插件图标
    plugin_icon = "Telegram_A.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "mexiaow"
    # 作者主页
    author_url = "https://github.com/mexiaow"
    # 插件配置项ID前缀
    plugin_config_prefix = "embydailyreports_"
    # 加载顺序
    plugin_order = 26
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _onlyonce = False
    _bot_token = ""
    _api_base_url = "https://api.telegram.org"
    _chat_id = ""
    _topic_id = 0
    _cron = "45 23 * * *"
    _count = 90
    _days_ago = 0
    _only_success = True
    _official_api_base_url = "https://api.telegram.org"
    _retry_times = 2
    _retry_interval = 2
    _max_message_length = 3900
    _anime_categories = ["国漫", "日漫", "日番"]

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
        self._count = max(self.__to_int(config.get("count"), 90), 1)
        self._days_ago = max(self.__to_int(config.get("days_ago"), 0), 0)
        self._only_success = bool(config.get("only_success", True))

        if self._onlyonce:
            self.send_report()
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
                    "id": "EmbyDailyReports",
                    "name": "Emby入库日报",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.send_report,
                    "kwargs": {},
                }
            ]
        except Exception as err:
            logger.error(f"Emby入库日报定时任务配置错误：{err}")
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即发送一次",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "only_success",
                                            "label": "只统计成功入库",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "bot_token",
                                            "label": "Bot Token",
                                            "placeholder": "123456:ABCDEF",
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
                                            "model": "api_base_url",
                                            "label": "Telegram API 地址",
                                            "placeholder": "https://api.telegram.org",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "chat_id",
                                            "label": "Chat ID",
                                            "placeholder": "-1001234567890",
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
                                            "model": "topic_id",
                                            "label": "话题 ID",
                                            "type": "number",
                                            "placeholder": "10",
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VCronField",
                                        "props": {
                                            "model": "cron",
                                            "label": "执行周期",
                                            "placeholder": "45 23 * * *",
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
                                            "model": "count",
                                            "label": "查询数量",
                                            "type": "number",
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
                                            "text": "执行周期使用 5 位 cron 表达式，例如 45 23 * * * 表示每天 23:45 发送。话题 ID 为空或 0 时发送到群组默认话题。",
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
            "only_success": True,
            "bot_token": "",
            "api_base_url": self._official_api_base_url,
            "chat_id": "",
            "topic_id": "",
            "cron": "45 23 * * *",
            "count": 90,
            "days_ago": 0,
        }

    def get_page(self) -> List[dict]:
        last_report = self.get_data("last_report") or {}
        if not last_report:
            return [
                {
                    "component": "div",
                    "props": {"class": "text-center"},
                    "text": "暂无发送记录",
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
                                    "type": "success" if last_report.get("success") else "error",
                                    "variant": "tonal",
                                    "text": self.__build_last_report_message(last_report),
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
                                    "model-value": last_report.get("preview") or "",
                                    "label": "最近一次日报预览",
                                    "readonly": True,
                                    "rows": 16,
                                },
                            }
                        ],
                    },
                ],
            }
        ]

    def stop_service(self):
        pass

    def send_report(self):
        """生成入库日报并发送到 Telegram。"""
        if not self._bot_token or not self._chat_id:
            message = "Emby入库日报发送失败：Bot Token 或 Chat ID 未配置"
            logger.warning(message)
            self.__save_last_report(False, message, "")
            return

        try:
            target_date = datetime.now().date() - timedelta(days=self._days_ago)
            records = self.__get_transfer_records(target_date)
            report = self.__format_report(records, target_date)

            if self.__send_telegram_message(report):
                message = (
                    f"Emby入库日报发送成功：date={target_date} "
                    f"records={len(records)} topic_id={self._topic_id or 'default'}"
                )
                logger.info(message)
                self.__save_last_report(True, message, report)
                return

            message = "Emby入库日报发送失败：Telegram 请求重试后仍失败"
            logger.error(message)
            self.__save_last_report(False, message, report)
        except Exception as err:
            message = f"Emby入库日报发送异常：{err}"
            logger.error(message, exc_info=True)
            self.__save_last_report(False, message, "")

    def __get_transfer_records(self, target_date) -> List[Any]:
        start_time = f"{target_date.strftime('%Y-%m-%d')} 00:00:00"
        records = TransferHistoryOper().list_by_date(start_time)
        date_records = []
        for record in records or []:
            if self._only_success and not bool(self.__get_record_value(record, "status", True)):
                continue

            record_date = self.__parse_record_date(
                self.__get_record_value(record, "date", "")
            )
            if record_date and record_date < target_date:
                break
            if record_date == target_date:
                date_records.append(record)
            if len(date_records) >= self._count:
                break

        logger.info(
            f"Emby入库日报获取入库记录：target_date={target_date} "
            f"count={self._count} matched={len(date_records)}"
        )
        return date_records

    def __format_report(self, records: List[Any], target_date) -> str:
        date_str = target_date.strftime("%Y-%m-%d")
        report = f"<b>{html.escape(date_str)} 媒体入库统计</b>\n"
        report += "====================\n\n"

        if not records:
            return report + "没有找到当日的入库记录"

        groups: Dict[str, List[Any]] = {}
        for record in records:
            display_type = self.__get_display_type(record)
            groups.setdefault(display_type, []).append(record)

        for display_type in ["电影", "剧集", "动漫"]:
            items = groups.get(display_type)
            if not items:
                continue

            report += f"<b>{display_type}</b> ({len(items)}项)\n"
            for record in items:
                title = html.escape(
                    str(self.__get_record_value(record, "title", "未知标题") or "未知标题")
                )
                episode = self.__build_episode_text(record)
                size_text = self.__build_size_text(record)
                report += f"  - {title}{episode}{size_text}\n"
            report += "\n"

        return report.rstrip()

    def __get_display_type(self, record: Any) -> str:
        category = str(self.__get_record_value(record, "category", "") or "")
        media_type = str(self.__get_record_value(record, "type", "") or "")

        if category in self._anime_categories:
            return "动漫"
        if media_type == "电影":
            return "电影"
        return "剧集"

    def __build_episode_text(self, record: Any) -> str:
        seasons = self.__get_record_value(record, "seasons", "")
        episodes = self.__get_record_value(record, "episodes", "")
        if seasons and episodes:
            return f" {html.escape(str(seasons))}{html.escape(str(episodes))}"
        return ""

    def __build_size_text(self, record: Any) -> str:
        size = self.__get_record_size(record)
        if not size:
            return ""
        size_gb = round(size / (1024 ** 3), 2)
        return f" - {size_gb}GB"

    def __get_record_size(self, record: Any) -> int:
        dest_fileitem = self.__get_record_value(record, "dest_fileitem")
        if isinstance(dest_fileitem, dict) and dest_fileitem.get("size"):
            return self.__to_int(dest_fileitem.get("size"), 0)

        files = self.__get_record_value(record, "files")
        if not files:
            return 0
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except Exception:
                return 0
        if not isinstance(files, list):
            return 0

        total_size = 0
        for file_item in files:
            if isinstance(file_item, dict):
                total_size += self.__to_int(file_item.get("size"), 0)
            else:
                total_size += self.__to_int(getattr(file_item, "size", 0), 0)
        return total_size

    def __send_telegram_message(self, content: str) -> bool:
        for chunk in self.__split_message(content):
            if not self.__post_telegram(
                method="sendMessage",
                payload=self.__build_text_payload(chunk),
            ):
                return False
        return True

    def __build_text_payload(self, content: str) -> Dict[str, Any]:
        payload = {
            "chat_id": self._chat_id,
            "parse_mode": "HTML",
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
                logger.warning(
                    f"Emby入库日报发送无响应：{method} 第 {attempt}/{total_attempts} 次"
                )
                if attempt < total_attempts:
                    time.sleep(self._retry_interval * attempt)
                continue

            try:
                result = response.json()
            except Exception:
                result = {}

            if response.status_code == 200 and result.get("ok") is not False:
                return True

            logger.warning(
                f"Emby入库日报发送失败：{method} {response.status_code} {response.text}"
            )
            if not self.__should_retry(response.status_code) or attempt >= total_attempts:
                break

            time.sleep(self._retry_interval * attempt)

        return False

    def __split_message(self, content: str) -> List[str]:
        if len(content) <= self._max_message_length:
            return [content]

        chunks = []
        current_lines = []
        current_length = 0
        for line in content.splitlines():
            line_length = len(line) + 1
            if current_lines and current_length + line_length > self._max_message_length:
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_length = 0

            if line_length > self._max_message_length:
                chunks.append(line[: self._max_message_length])
                continue

            current_lines.append(line)
            current_length += line_length

        if current_lines:
            chunks.append("\n".join(current_lines))
        return chunks

    def __save_last_report(self, success: bool, message: str, preview: str):
        self.save_data(
            "last_report",
            {
                "success": success,
                "message": message,
                "preview": self.__strip_html(preview)[:3000],
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

    def __update_config(self):
        self.update_config(
            {
                "enabled": self._enabled,
                "onlyonce": self._onlyonce,
                "only_success": self._only_success,
                "bot_token": self._bot_token,
                "api_base_url": self._api_base_url,
                "chat_id": self._chat_id,
                "topic_id": self._topic_id,
                "cron": self._cron,
                "count": self._count,
                "days_ago": self._days_ago,
            }
        )

    @staticmethod
    def __get_record_value(record: Any, key: str, default: Any = None) -> Any:
        if record is None:
            return default
        if isinstance(record, dict):
            return record.get(key, default)
        return getattr(record, key, default)

    @staticmethod
    def __parse_record_date(value: Any):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
            except ValueError:
                return None

    @staticmethod
    def __normalize_api_base_url(api_base_url: str) -> str:
        api_base_url = (api_base_url or "").strip().rstrip("/")
        if not api_base_url:
            return EmbyDailyReports._official_api_base_url
        if not api_base_url.startswith(("http://", "https://")):
            return f"https://{api_base_url}"
        return api_base_url

    @staticmethod
    def __should_retry(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    @staticmethod
    def __strip_html(value: str) -> str:
        return (value or "").replace("<b>", "").replace("</b>", "")

    @staticmethod
    def __build_last_report_message(last_report: Dict[str, Any]) -> str:
        message = last_report.get("message") or "暂无状态"
        report_time = last_report.get("time")
        if report_time:
            return f"{message}，时间：{report_time}"
        return message

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
