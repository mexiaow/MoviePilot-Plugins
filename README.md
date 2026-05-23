# MoviePilot-Plugins

个人 MoviePilot 插件仓库。

## 插件列表

| 插件             | 目录                            | 说明                                             |
| ---------------- | ------------------------------- | ------------------------------------------------ |
| Emby入库日报     | `plugins.v2/embydailyreports/`  | 定时统计 MoviePilot 入库记录并发送到 Telegram 话题 |
| Telegram话题推送 | `plugins.v2/telegramtopicpush/` | 按规则将 MoviePilot 通知推送到 Telegram 群组话题 |

## V2 插件结构

```text
plugins.v2/
├── embydailyreports/
│   ├── __init__.py
│   └── README.md
└── telegramtopicpush/
    ├── __init__.py
    └── README.md
```

插件市场清单：

```text
package.v2.json
```

## 安装

在 MoviePilot 中添加本仓库作为插件仓库。

然后在插件市场安装需要的插件。

## 当前插件

### Emby入库日报

配置说明见：

```text
plugins.v2/embydailyreports/README.md
```

功能：

- 定时统计 MoviePilot 转移历史中的入库记录
- 支持 5 位 cron 表达式配置执行周期
- 支持立即发送一次
- 支持只统计成功入库记录
- 支持填写 Telegram Bot Token、Chat ID 和话题 ID
- 支持自定义 Telegram API 地址
- 支持发送失败重试
- 日报过长时按行拆分发送

### Telegram话题推送

配置说明见：

```text
plugins.v2/telegramtopicpush/README.md
```

功能：

- 监听 MoviePilot 通知事件
- 按关键词匹配话题
- 支持 Telegram `sendMessage`
- 支持 Telegram `sendPhoto`
- 支持自定义 Telegram API 地址
- 支持发送失败重试
- 支持保留“查看详情”链接
- 支持通知类型过滤
- 支持防重复发送

使用时建议关闭 MoviePilot 内置 Telegram 通知，只保留该插件。
