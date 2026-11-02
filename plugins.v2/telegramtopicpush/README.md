# Telegram话题推送

监听 MoviePilot 通知事件，按关键词把通知分流到 Telegram 群组的不同话题。

## 功能

- 按顺序匹配关键词，命中后发送到对应话题；未命中时发送到兜底话题
- 支持 `sendMessage` 与 `sendPhoto`
- 支持通知类型过滤与防重复发送
- 支持自定义 Telegram Bot API 地址（反代）
- 429/5xx 自动重试；自定义地址无响应时回退官方地址
- MoviePilot 通知带链接时，消息中保留“查看详情”

## 配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后开始处理通知 |
| Bot Token | Telegram Bot Token |
| Telegram API 地址 | 默认 `https://api.telegram.org`，有反代时填写基础地址 |
| Chat ID | Telegram 群组 ID |
| 兜底 Topic ID | 未命中规则时发送的话题 ID |
| 防重复发送 | 开启时只处理未指定通知渠道的消息 |
| 接管哪些通知类型 | 空表示全部；选中则只处理选中的类型 |
| 分流规则 | 关键词与话题的对应关系 |
| 测试发送 | 保存后向兜底话题发送一条测试消息，随后自动关闭 |

## 分流规则

`rules` 为 JSON 数组，按顺序匹配，第一条命中生效；匹配文本为「通知标题 + 换行 + 通知正文」。

```json
[
  {
    "name": "下载",
    "topic_id": 4,
    "keywords": ["下载完成", "开始下载", "下载"]
  },
  {
    "name": "订阅",
    "topic_id": 8,
    "keywords": ["已添加订阅", "已完成订阅", "订阅"]
  }
]
```

| 字段 | 说明 |
| --- | --- |
| `name` | 规则名称，仅用于识别 |
| `topic_id` | 命中后发送到的话题 ID |
| `keywords` | 关键词列表 |

## 获取话题 ID

话题 ID 即 Telegram 的 `message_thread_id`：

1. 在目标话题中发送一条消息；
2. 访问 `https://api.telegram.org/bot<BotToken>/getUpdates`；
3. 响应中的 `message.chat.id` 填到 Chat ID，`message.message_thread_id` 填到 `topic_id`。

## 注意事项

- 插件不会拦截 MoviePilot 内置 Telegram 通知。两者同时开启会收到重复消息，建议只保留一种。
- 图片通知走 `sendPhoto`，`disable_web_page_preview` 仅对文本消息有效。
- Bot Token、Chat ID、Topic ID 配置错误时重试无意义，需要修改配置。
