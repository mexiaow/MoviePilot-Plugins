# 新剧雷达

监控猫眼网播热度榜，发现新剧后通过 Telegram Bot 发送到指定群组或话题。

插件不会常驻轮询，也不接管 MoviePilot 通知渠道。它只在 cron 触发或手动“立即扫描一次”时抓取猫眼页面，并直接调用 Telegram Bot API 发送消息。

## 配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后按 cron 定时扫描 |
| 立即扫描一次 | 保存配置后立刻扫描一次，执行后会自动关闭 |
| Bot Token | Telegram Bot Token |
| Telegram API 地址 | 默认 `https://api.telegram.org`，有反代时填写反代基础地址 |
| Chat ID | Telegram 群组或频道 ID |
| 话题 ID | Telegram `message_thread_id`，为空或 0 时发送到默认话题 |
| 执行周期 | 5 位 cron 表达式，例如 `0 9 * * *` |
| 榜单数量 | 每次读取猫眼网播热度榜前 N 部，范围 1 到 100 |

## 推荐配置

```yaml
enabled: true
bot_token: "123456:ABCDEF"
api_base_url: "https://api.telegram.org"
chat_id: "-1001234567890"
topic_id: 10
cron: "0 9 * * *"
top_n: 10
```

## 发送内容

发现新剧时会发送：

```text
发现猫眼网播热度新剧（2部）
- 某某剧（腾讯视频；上线首日）
- 某某剧（爱奇艺；上线2天）
来源：https://piaofang.maoyan.com/web-heat
时间：2026-05-23 09:00:00
```

## 去重逻辑

插件使用 MoviePilot 插件数据存储保存已见剧名，不创建 SQLite 文件。

首次扫描只建立基线，不发送 Telegram，避免把当前榜单里的存量剧集当成新剧刷屏。后续扫描时，只要榜单中出现未记录过的剧名，就会发送提醒，并更新已见记录。

## 注意事项

- 猫眼页面结构变化或触发反爬时，插件可能无法解析到片名，状态页会记录异常。
- Telegram 消息为普通文本，不使用 Markdown 或 HTML 解析模式。
- 插件直接调用 Telegram Bot API，不复用 MoviePilot 内置通知渠道。
- Bot Token、Chat ID 和话题 ID 配错时，Telegram 通常会直接返回失败，需要修改配置后再试。
