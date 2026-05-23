# Telegram话题推送

按规则将 MoviePilot 通知推送到 Telegram 群组话题。

插件监听 MoviePilot 的通知事件，再按关键词把消息分流到 Telegram 群组的不同话题。

不使用 HTTP 代理。

## 适用场景

一个 Telegram 群组里开了多个话题，例如：

- 下载
- 订阅
- 入库统计
- 播放
- 其他通知

插件收到 MoviePilot 通知后，会按规则判断应该发到哪个话题。

## 安装路径

```text
plugins.v2/telegramtopicpush/
```

插件市场清单需要包含：

```text
package.v2.json -> TelegramTopicPush
```

## 配置

在 MoviePilot 插件配置页填写。

```yaml
enabled: true
bot_token: "123456:ABCDEF"
api_base_url: "https://api.telegram.org"
chat_id: "-1001234567890"
default_topic_id: 2
only_when_channel_empty: true
msgtypes: []
rules:
  - name: 下载
    topic_id: 4
    keywords:
      - 下载完成
      - 开始下载
      - 下载
  - name: 订阅
    topic_id: 8
    keywords:
      - 已添加订阅
      - 已完成订阅
      - 已订阅
      - 订阅
  - name: 入库统计
    topic_id: 10
    keywords:
      - 已入库
      - 入库
      - 统计
  - name: 播放
    topic_id: 12
    keywords:
      - 开始播放剧集
      - 开始播放电影
      - 开始播放
      - 播放
```

## 配置项说明

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否启用插件 |
| `bot_token` | Telegram Bot Token |
| `api_base_url` | Telegram API 基础地址 |
| `chat_id` | Telegram 群组 ID |
| `default_topic_id` | 未命中规则时使用的话题 ID |
| `only_when_channel_empty` | 只处理未指定通知渠道的 MoviePilot 通知 |
| `msgtypes` | 通知类型过滤，空数组表示不过滤 |
| `rules` | 有序分流规则 |

## default_topic_id 是什么

`default_topic_id` 是兜底话题 ID。

通知没有命中任何规则时，会发到这个话题。

建议建一个“其他通知”话题，然后把它的 ID 填到这里。

## api_base_url 是什么

`api_base_url` 是 Telegram Bot API 的基础地址。

默认值：

```text
https://api.telegram.org
```

插件实际请求地址会拼成：

```text
<api_base_url>/bot<bot_token>/sendMessage
<api_base_url>/bot<bot_token>/sendPhoto
```

如果你有可用的 Telegram Bot API 反代地址，可以填到这里。

示例：

```yaml
api_base_url: "https://tg.example.com"
```

注意不要在这里填完整的 `sendMessage` 地址。

也不要填带 `/bot<token>` 的地址。

## rules 写法

配置页里的 `rules` 是 JSON 数组。

每条规则包含：

```json
{
  "name": "下载",
  "topic_id": 4,
  "keywords": ["下载完成", "开始下载", "下载"]
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `name` | 规则名称，只用于识别 |
| `topic_id` | 命中后发送到哪个 Telegram 话题 |
| `keywords` | 关键词列表 |

匹配顺序从上到下。

第一条命中的规则优先。

匹配文本是：

```text
通知标题 + 换行 + 通知正文
```

## 完整 rules 示例

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
    "keywords": ["已添加订阅", "已完成订阅", "已订阅", "订阅"]
  },
  {
    "name": "入库统计",
    "topic_id": 10,
    "keywords": ["已入库", "入库", "统计"]
  },
  {
    "name": "播放",
    "topic_id": 12,
    "keywords": ["开始播放剧集", "开始播放电影", "开始播放", "播放"]
  }
]
```

把示例里的 `topic_id` 改成自己群组里的真实话题 ID。

## 获取 Telegram 话题 ID

Telegram 群组话题 ID 就是 `message_thread_id`。

常见获取方式：

1. 在目标话题里随便发一条消息。
2. 用 Bot API `getUpdates` 查看更新。
3. 找到这条消息里的 `message_thread_id`。

请求地址：

```text
https://api.telegram.org/bot<你的BotToken>/getUpdates
```

返回里类似：

```json
{
  "message": {
    "chat": {
      "id": -1001234567890
    },
    "message_thread_id": 4,
    "text": "test"
  }
}
```

这里：

- `chat.id` 填到 `chat_id`
- `message_thread_id` 填到对应规则的 `topic_id`

## 发送逻辑

1. 收到 MoviePilot 通知事件。
2. 插件未启用则忽略。
3. 没有标题、正文、图片则忽略。
4. 如果配置了 `msgtypes`，只处理选中的通知类型。
5. 如果 `only_when_channel_empty=true`，只处理未指定通知渠道的消息。
6. 按 `rules` 顺序匹配关键词。
7. 命中后发送到对应 `topic_id`。
8. 未命中时发送到 `default_topic_id`。
9. 有图片时调用 Telegram `sendPhoto`。
10. 无图片时调用 Telegram `sendMessage`。

## 重复推送

插件不会拦截 MoviePilot 内置 Telegram 通知。

如果 MoviePilot 内置 Telegram 通知仍然开启，同一条通知可能会发送两次。

正式使用时建议关闭 MoviePilot 内置 Telegram 通知，只保留本插件。

## 测试发送

配置页里有“测试发送一次”开关。

打开后保存配置，插件会向 `default_topic_id` 发送一条测试消息。

发送后开关会自动恢复为关闭。

## 常见问题

### 插件没有发消息

检查：

- `enabled` 是否开启
- `bot_token` 是否正确
- `chat_id` 是否是群组 ID
- Bot 是否已经加入群组
- Bot 是否有发送消息权限
- `topic_id` 是否是真实的话题 ID

### 只收到部分通知

检查：

- `msgtypes` 是否配置了过滤
- `only_when_channel_empty` 是否开启
- MoviePilot 发出的通知是否已经指定了其他通知渠道

### 消息都进了默认话题

说明没有命中任何规则。

检查：

- 关键词是否出现在通知标题或正文里
- `rules` 是否是合法 JSON
- 规则顺序是否符合预期

### 图片消息没有预览链接开关

图片消息走 Telegram `sendPhoto`。

Telegram 的 `disable_web_page_preview` 只用于文本消息。
