import json
import time
import re
from typing import Any, Dict, List, Tuple

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class TelegramTopicPush(_PluginBase):
    # 插件名称
    plugin_name = "Telegram话题推送"
    # 插件描述
    plugin_desc = "按规则将 MoviePilot 通知推送到 Telegram 群组话题"
    # 插件图标
    plugin_icon = "Telegram_A.png"
    # 插件版本
    plugin_version = "1.0.1"
    # 插件作者
    plugin_author = "mexiaow"
    # 作者主页
    author_url = "https://github.com/mexiaow"
    # 插件配置项ID前缀
    plugin_config_prefix = "telegramtopicpush_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _bot_token = ""
    _api_base_url = "https://api.telegram.org"
    _chat_id = ""
    _default_topic_id = 2
    _only_when_channel_empty = True
    _msgtypes: List[str] = []
    _rules: List[Dict[str, Any]] = []
    _official_api_base_url = "https://api.telegram.org"
    _retry_times = 2
    _retry_interval = 2

    _default_rules = [
        {
            "name": "下载",
            "topic_id": 4,
            "keywords": ["下载完成", "开始下载", "下载"],
        },
        {
            "name": "订阅",
            "topic_id": 8,
            "keywords": ["已添加订阅", "已完成订阅", "已订阅", "订阅"],
        },
        {
            "name": "入库统计",
            "topic_id": 10,
            "keywords": ["已入库", "入库", "统计"],
        },
        {
            "name": "播放",
            "topic_id": 12,
            "keywords": ["开始播放剧集", "开始播放电影", "开始播放", "播放"],
        },
    ]

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._bot_token = (config.get("bot_token") or "").strip()
        self._api_base_url = self.__normalize_api_base_url(
            config.get("api_base_url") or self._official_api_base_url
        )
        self._chat_id = str(config.get("chat_id") or "").strip()
        self._default_topic_id = self.__to_int(config.get("default_topic_id"), 2)
        self._only_when_channel_empty = bool(
            config.get("only_when_channel_empty", True)
        )
        self._msgtypes = self.__normalize_list(config.get("msgtypes"))
        self._rules = self.__parse_rules(config.get("rules"))

        if config.get("onlyonce"):
            self.__send_test_message()
            self.update_config(
                {
                    "enabled": self._enabled,
                    "onlyonce": False,
                    "bot_token": self._bot_token,
                    "api_base_url": self._api_base_url,
                    "chat_id": self._chat_id,
                    "default_topic_id": self._default_topic_id,
                    "only_when_channel_empty": self._only_when_channel_empty,
                    "msgtypes": self._msgtypes,
                    "rules": self.__rules_to_text(self._rules),
                }
            )

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        msgtype_items = [
            {"title": item.value, "value": item.value} for item in NotificationType
        ]

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
                                            "model": "only_when_channel_empty",
                                            "label": "防重复发送",
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
                                            "label": "测试发送",
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
                                            "text": "防重复发送开启后，已经指定微信、Telegram、Web 等渠道的通知不会再被本插件转发。正常建议开启。",
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
                                            "model": "default_topic_id",
                                            "label": "兜底 Topic ID",
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
                                        "component": "VSelect",
                                        "props": {
                                            "model": "msgtypes",
                                            "label": "接管哪些通知类型，不选就是全部",
                                            "items": msgtype_items,
                                            "multiple": True,
                                            "chips": True,
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
                                            "model": "rules",
                                            "label": "分流规则：关键词 -> 话题ID",
                                            "rows": 14,
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
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "text": "如果 MoviePilot 内置 Telegram 通知仍然开启，建议保持“防重复发送”开启，或者关闭内置 Telegram 通知。",
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
            "default_topic_id": 2,
            "only_when_channel_empty": True,
            "msgtypes": [],
            "rules": self.__rules_to_text(self._default_rules),
        }

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        pass

    @eventmanager.register(EventType.NoticeMessage)
    def notice_message(self, event: Event = None):
        if not self._enabled:
            return

        event_data = event.event_data if event else {}
        if not event_data:
            return

        message = event_data.get("message") if isinstance(event_data, dict) else None
        notice = message or event_data

        channel = self.__get_notice_value(notice, "channel")
        if self._only_when_channel_empty and channel:
            return

        msgtype = self.__value_to_str(
            self.__get_notice_value(notice, "type")
            or self.__get_notice_value(notice, "mtype")
            or event_data.get("msgstr")
        )
        if self._msgtypes and msgtype not in self._msgtypes:
            return

        title = self.__value_to_str(self.__get_notice_value(notice, "title")).strip()
        text = self.__value_to_str(self.__get_notice_value(notice, "text")).strip()
        image = self.__value_to_str(self.__get_notice_value(notice, "image")).strip()
        link = self.__value_to_str(self.__get_notice_value(notice, "link")).strip()
        buttons = self.__parse_buttons(self.__get_notice_value(notice, "buttons"))

        if not title and not text and not image:
            return

        topic_id = self.__match_topic_id(f"{title}\n{text}")
        content = self.__build_content(
            title=title,
            text=text,
            link=link,
            buttons=buttons,
        )
        disable_preview = bool(
            self.__get_notice_value(notice, "disable_web_page_preview", True)
        )

        self.__send_telegram_message(
            topic_id=topic_id,
            content=content,
            image=image,
            buttons=buttons,
            disable_web_page_preview=disable_preview,
        )

    def __send_test_message(self):
        if not self._bot_token or not self._chat_id:
            logger.warning("Telegram话题推送测试失败：Bot Token 或 Chat ID 未配置")
            return
        self.__send_telegram_message(
            topic_id=self._default_topic_id,
            content="Telegram话题推送测试消息",
            image="",
            disable_web_page_preview=True,
        )

    def __send_telegram_message(
        self,
        topic_id: int,
        content: str,
        image: str = "",
        buttons: List[Dict[str, str]] = None,
        disable_web_page_preview: bool = True,
    ):
        if not self._bot_token or not self._chat_id:
            logger.warning("Telegram话题推送失败：Bot Token 或 Chat ID 未配置")
            return

        api_bases = self.__get_api_base_urls()
        if image:
            photo_payload = self.__build_photo_payload(
                topic_id=topic_id,
                content=content,
                image=image,
                buttons=buttons,
            )
            if self.__post_telegram(
                method="sendPhoto",
                payload=photo_payload,
                api_bases=api_bases,
            ):
                logger.info(f"Telegram话题推送成功：topic_id={topic_id}")
                return

            logger.warning("Telegram话题推送图片失败，降级为文本消息")
            content = f"{content}\n\n图片：{image}"

        text_payload = self.__build_text_payload(
            topic_id=topic_id,
            content=content,
            disable_web_page_preview=disable_web_page_preview,
            buttons=buttons,
        )
        if self.__post_telegram(
            method="sendMessage",
            payload=text_payload,
            api_bases=api_bases,
        ):
            logger.info(f"Telegram话题推送成功：topic_id={topic_id}")
            return

        logger.error("Telegram话题推送失败：重试和兜底发送均失败")

    def __post_telegram(
        self,
        method: str,
        payload: Dict[str, Any],
        api_bases: List[str],
    ) -> bool:
        total_attempts = self._retry_times + 1

        for api_base in api_bases:
            url = f"{api_base}/bot{self._bot_token}/{method}"
            for attempt in range(1, total_attempts + 1):
                response = RequestUtils(
                    content_type="application/json",
                    accept_type="application/json",
                    timeout=20,
                ).post_res(url, json=payload)

                if response is None:
                    logger.warning(
                        f"Telegram话题推送无响应：{method} "
                        f"{api_base} 第 {attempt}/{total_attempts} 次"
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
                    f"Telegram话题推送失败：{method} {api_base} "
                    f"{response.status_code} {response.text}"
                )

                if (
                    not self.__should_retry(response.status_code)
                    or attempt >= total_attempts
                ):
                    break

                time.sleep(self._retry_interval * attempt)

        return False

    def __build_text_payload(
        self,
        topic_id: int,
        content: str,
        disable_web_page_preview: bool,
        buttons: List[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "chat_id": self._chat_id,
            "message_thread_id": topic_id,
            "parse_mode": "MarkdownV2",
            "text": content,
            "disable_web_page_preview": disable_web_page_preview,
        }
        reply_markup = self.__build_reply_markup(buttons)
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return payload

    def __build_photo_payload(
        self,
        topic_id: int,
        content: str,
        image: str,
        buttons: List[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "chat_id": self._chat_id,
            "message_thread_id": topic_id,
            "parse_mode": "MarkdownV2",
            "photo": image,
            "caption": content,
        }
        reply_markup = self.__build_reply_markup(buttons)
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return payload

    def __get_api_base_urls(self) -> List[str]:
        api_bases = [self._api_base_url]
        if self._api_base_url != self._official_api_base_url:
            api_bases.append(self._official_api_base_url)
        return api_bases

    @staticmethod
    def __normalize_api_base_url(api_base_url: str) -> str:
        api_base_url = (api_base_url or "").strip().rstrip("/")
        if not api_base_url:
            return TelegramTopicPush._official_api_base_url
        if not api_base_url.startswith(("http://", "https://")):
            return f"https://{api_base_url}"
        return api_base_url

    @staticmethod
    def __should_retry(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    def __match_topic_id(self, text: str) -> int:
        for rule in self._rules:
            topic_id = self.__to_int(rule.get("topic_id"), 0)
            if not topic_id:
                continue
            for keyword in self.__normalize_list(rule.get("keywords")):
                if keyword and keyword in text:
                    return topic_id
        return self._default_topic_id

    @staticmethod
    def __build_content(
        title: str,
        text: str,
        link: str,
        buttons: List[Dict[str, str]] = None,
    ) -> str:
        parts = []
        if title:
            parts.append(TelegramTopicPush.__format_markdown_v2_text(title))
        if text:
            parts.append(TelegramTopicPush.__escape_markdown_v2(text))
        if link:
            parts.append(TelegramTopicPush.__build_markdown_v2_link("查看详情", link))
        for button in buttons or []:
            button_text = button.get("text") or "查看详情"
            button_url = button.get("url")
            if button_url and button_url != link:
                parts.append(
                    TelegramTopicPush.__build_markdown_v2_link(button_text, button_url)
                )
        return "\n\n".join(parts) or " "

    @staticmethod
    def __format_markdown_v2_text(text: str) -> str:
        pattern = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)\)")
        parts = []
        last_end = 0
        for match in pattern.finditer(text):
            parts.append(TelegramTopicPush.__escape_markdown_v2(text[last_end:match.start()]))
            parts.append(
                TelegramTopicPush.__build_markdown_v2_link(
                    match.group(1),
                    match.group(2),
                )
            )
            last_end = match.end()
        parts.append(TelegramTopicPush.__escape_markdown_v2(text[last_end:]))
        return "".join(parts)

    @staticmethod
    def __build_markdown_v2_link(text: str, url: str) -> str:
        escaped_text = TelegramTopicPush.__escape_markdown_v2(text)
        escaped_url = TelegramTopicPush.__escape_markdown_v2_url(url)
        return f"[{escaped_text}]({escaped_url})"

    @staticmethod
    def __escape_markdown_v2(text: str) -> str:
        return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", text or "")

    @staticmethod
    def __escape_markdown_v2_url(url: str) -> str:
        return (url or "").replace("\\", "\\\\").replace(")", "\\)")

    @staticmethod
    def __build_reply_markup(buttons: List[Dict[str, str]] = None) -> dict:
        inline_keyboard = []
        for button in buttons or []:
            text = button.get("text") or "查看详情"
            url = button.get("url")
            if text and url:
                inline_keyboard.append([{"text": text, "url": url}])
        return {"inline_keyboard": inline_keyboard} if inline_keyboard else {}

    def __parse_buttons(self, buttons: Any) -> List[Dict[str, str]]:
        parsed_buttons = []
        for button in self.__iter_buttons(buttons):
            if not isinstance(button, dict):
                continue
            text = (
                button.get("text")
                or button.get("title")
                or button.get("name")
                or "查看详情"
            )
            url = button.get("url") or button.get("href") or button.get("link")
            if url:
                parsed_buttons.append(
                    {
                        "text": self.__value_to_str(text).strip() or "查看详情",
                        "url": self.__value_to_str(url).strip(),
                    }
                )
        return parsed_buttons

    def __iter_buttons(self, buttons: Any) -> List[Any]:
        if not buttons:
            return []
        if isinstance(buttons, str):
            try:
                buttons = json.loads(buttons)
            except Exception:
                return []
        if isinstance(buttons, dict):
            if isinstance(buttons.get("inline_keyboard"), list):
                return self.__flatten_buttons(buttons.get("inline_keyboard"))
            return [buttons]
        if isinstance(buttons, list):
            return self.__flatten_buttons(buttons)
        return []

    def __flatten_buttons(self, buttons: List[Any]) -> List[Any]:
        flattened = []
        for button in buttons:
            if isinstance(button, list):
                flattened.extend(self.__flatten_buttons(button))
            else:
                flattened.append(button)
        return flattened

    @staticmethod
    def __get_notice_value(notice: Any, key: str, default: Any = None) -> Any:
        if notice is None:
            return default
        if isinstance(notice, dict):
            return notice.get(key, default)
        return getattr(notice, key, default)

    def __parse_rules(self, rules: Any) -> List[Dict[str, Any]]:
        if rules in (None, ""):
            return self._default_rules
        if isinstance(rules, list):
            return rules
        if not isinstance(rules, str):
            logger.error("Telegram话题推送规则解析失败：rules 必须是 JSON 字符串或列表")
            return self._rules or self._default_rules

        try:
            parsed = json.loads(rules)
        except Exception as err:
            logger.error(f"Telegram话题推送规则解析失败：{err}")
            return self._rules or self._default_rules

        if not isinstance(parsed, list):
            logger.error("Telegram话题推送规则解析失败：JSON 根节点必须是数组")
            return self._rules or self._default_rules
        return parsed

    @staticmethod
    def __rules_to_text(rules: List[Dict[str, Any]]) -> str:
        return json.dumps(rules, ensure_ascii=False, indent=2)

    @staticmethod
    def __normalize_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [
                TelegramTopicPush.__value_to_str(item).strip()
                for item in value
                if item is not None
            ]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [TelegramTopicPush.__value_to_str(value).strip()]

    @staticmethod
    def __value_to_str(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
