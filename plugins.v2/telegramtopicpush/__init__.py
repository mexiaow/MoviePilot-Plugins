import json
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
        self._api_base_url = (
            (config.get("api_base_url") or "https://api.telegram.org")
            .strip()
            .rstrip("/")
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
                                            "label": "只处理默认通知",
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
                                            "label": "测试发送一次",
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
                                            "model": "default_topic_id",
                                            "label": "默认 Topic ID",
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
                                            "label": "通知类型过滤",
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
                                            "label": "话题分流规则 JSON",
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
                                            "text": "启用前建议关闭 MoviePilot 内置 Telegram 通知，否则同一通知会重复发送。",
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
            "api_base_url": "https://api.telegram.org",
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

        if self._only_when_channel_empty and event_data.get("channel"):
            return

        msgtype = self.__value_to_str(event_data.get("type"))
        if self._msgtypes and msgtype not in self._msgtypes:
            return

        title = self.__value_to_str(event_data.get("title")).strip()
        text = self.__value_to_str(event_data.get("text")).strip()
        image = self.__value_to_str(event_data.get("image")).strip()
        link = self.__value_to_str(event_data.get("link")).strip()

        if not title and not text and not image:
            return

        topic_id = self.__match_topic_id(f"{title}\n{text}")
        content = self.__build_content(title=title, text=text, link=link)
        disable_preview = bool(event_data.get("disable_web_page_preview", True))

        self.__send_telegram_message(
            topic_id=topic_id,
            content=content,
            image=image,
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
        disable_web_page_preview: bool = True,
    ):
        if not self._bot_token or not self._chat_id:
            logger.warning("Telegram话题推送失败：Bot Token 或 Chat ID 未配置")
            return

        method = "sendPhoto" if image else "sendMessage"
        url = f"{self._api_base_url}/bot{self._bot_token}/{method}"
        payload = {
            "chat_id": self._chat_id,
            "message_thread_id": topic_id,
            "parse_mode": "Markdown",
        }

        if image:
            payload.update(
                {
                    "photo": image,
                    "caption": content,
                }
            )
        else:
            payload.update(
                {
                    "text": content,
                    "disable_web_page_preview": disable_web_page_preview,
                }
            )

        response = RequestUtils(
            content_type="application/json",
            accept_type="application/json",
            timeout=20,
        ).post_res(url, json=payload)

        if not response:
            logger.error("Telegram话题推送失败：Telegram API 无响应")
            return

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code != 200 or result.get("ok") is False:
            logger.error(
                f"Telegram话题推送失败：{response.status_code} {response.text}"
            )
            return

        logger.info(f"Telegram话题推送成功：topic_id={topic_id}")

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
    def __build_content(title: str, text: str, link: str) -> str:
        parts = []
        if title:
            parts.append(title)
        if text:
            parts.append(text)
        if link:
            parts.append(link)
        return "\n\n".join(parts) or " "

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
