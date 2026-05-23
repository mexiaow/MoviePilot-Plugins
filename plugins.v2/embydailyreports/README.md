# Emby入库日报

定时统计 MoviePilot 入库记录，并通过 Telegram Bot 发送到指定群组或话题。

插件不会启动 Telegram 长轮询，也不提供交互命令。它只在 cron 触发或手动“立即发送一次”时生成日报并调用 Telegram Bot API 发送消息。

## 配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后按 cron 定时发送 |
| 立即发送一次 | 保存配置后立刻生成并发送一次，发送后会自动关闭 |
| 只统计成功入库 | 默认开启，只统计转移成功的历史记录 |
| Bot Token | Telegram Bot Token |
| Telegram API 地址 | 默认 `https://api.telegram.org`，有反代时填写反代基础地址 |
| Chat ID | Telegram 群组或频道 ID |
| 话题 ID | Telegram `message_thread_id`，为空或 0 时发送到默认话题 |
| 执行周期 | 5 位 cron 表达式，例如 `45 23 * * *` |
| 查询数量 | 每次最多统计多少条入库记录 |

## 推荐配置

```yaml
enabled: true
bot_token: "123456:ABCDEF"
api_base_url: "https://api.telegram.org"
chat_id: "-1001234567890"
topic_id: 10
cron: "45 23 * * *"
count: 90
only_success: true
```

## 发送内容

日报会按电影、剧集、动漫分组，展示标题、季集和文件大小。

动漫判断沿用原项目规则：二级分类为 `国漫`、`日漫`、`日番` 时归入动漫；类型为 `电影` 时归入电影；其它记录归入剧集。

## 注意事项

- 执行周期使用 MoviePilot 插件服务的 cron 调度。
- 插件读取 MoviePilot 转移历史，不需要额外填写 MoviePilot API 地址或 Token。
- Telegram 消息使用 HTML 模式，插件会转义媒体标题中的特殊字符。
- 日报过长时会按行拆分为多条 Telegram 消息发送。
