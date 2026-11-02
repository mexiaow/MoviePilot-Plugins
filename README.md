# MoviePilot-Plugins

MoviePilot 插件集合，同时提供 V3 与 V2 两套实现。

## 插件列表

| 插件 | 目录 | 说明 |
| --- | --- | --- |
| 金山文档新剧提醒 | `plugins.v3/kdocsepisodenotify/` | 解析金山文档追剧表，新剧出现时发送 Telegram 提醒 |
| Emby入库日报 | `plugins.v2/embydailyreports/` | 定时统计入库记录并发送到 Telegram 话题 |
| Telegram话题推送 | `plugins.v2/telegramtopicpush/` | 按关键词把 MoviePilot 通知分流到 Telegram 话题 |
| 新剧雷达 | `plugins.v2/dramaradar/` | 监控猫眼网播热度榜，新剧出现时发送 Telegram 提醒 |

各插件的配置项与行为说明见对应目录下的 `README.md`。

## 目录结构

```text
plugins.v3/
└── kdocsepisodenotify/
    ├── __init__.py
    ├── pyproject.toml        # 额外依赖
    └── README.md

plugins.v2/
├── dramaradar/
├── embydailyreports/
└── telegramtopicpush/

tests/v3/kdocsepisodenotify/  # V3 插件单测

package.v3.json               # V3 插件市场索引
package.v2.json               # V2 插件市场索引
```

## 安装

在 MoviePilot 中添加本仓库地址作为插件仓库，然后在插件市场安装需要的插件。

## 更新

插件市场 → 检查更新。新版本发布时会同步修改插件类中的 `plugin_version`、
`package.v3.json` 中的 `version` 与 `history`。

## 开发说明

- V3 插件遵循 [MoviePilot 插件开发指南（V3）](https://github.com/jxxghp/MoviePilot-Plugins/blob/main/docs/Plugin_Development.md)：
  使用 `app.sdk.*` 稳定接口、`get_service()` 托管定时任务、`save_data()` 保存运行状态。
- V3 插件单测位于 `tests/v3/<plugin_id>/`，需在 MoviePilot 宿主虚拟环境中运行：
  `python -m pytest tests/v3/kdocsepisodenotify`
- V2 插件保留原有实现，可在 V3 宿主中运行。
