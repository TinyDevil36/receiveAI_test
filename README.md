# AI 新闻推送（Telegram）

每天 08:00–10:00（北京时间）从 [橘鸦 AI 早报 RSS](https://daily.juya.uk/rss.xml)
拉取当天新闻，直接推送到 Telegram（不含摘要，原文链接推送）。
用 GitHub Actions 定时触发，**你的电脑开不开机都没关系**。

## 文件

- `.github/workflows/ai-news.yml` — 定时工作流（每 10 分钟触发一次窗口内检查）
- `scripts/ai_news.py` — 主逻辑（拉 RSS → 过滤当天 → 去重 → 发送 Telegram）
- `scripts/requirements.txt` — Python 依赖

## 配置（只需一次）

在 GitHub 仓库 **Settings → Secrets and variables → Actions** 里配置：

| 位置 | 名字 | 值 |
|------|------|----|
| **Secrets** | `TELEGRAM_BOT_TOKEN` | Telegram bot token（`@BotFather` → `/newbot` 获得） |
| **Secrets** | `TELEGRAM_CHAT_ID` | 要接收消息的 chat id（见下方） |

> 两个都放 **Secrets**，GitHub 会脱敏显示，不会出现在日志里。

### 获取 chat_id

- 推给自己：在 Telegram 给 `@userinfobot` 发任意消息，它会回复 `Id: <数字>`，那个数字填进 `TELEGRAM_CHAT_ID`。
- 推送到群：把 bot 拉进群再加一次群消息，然后访问
  `https://api.telegram.org/bot<你的token>/getUpdates`，找 `chat.id`（负数）填进去。

## 时间窗口

RSS 每天早报发布后只推一次。调度按**北京时间** 07:00–11:00 每 10 分钟触发，
当日首条新条目出现即推送，并把已推送条目标记为已读，之后不再重复推送。
窗口放宽是为了容忍 GitHub Actions 的 schedule 触发延迟（常达 1–2 小时）；
核心保证是「当天内只推一次」，靠日期过滤 + 去重实现。
脚本默认窗口 07:00–11:00，可用环境变量 `PUSH_START_HOUR`、`PUSH_END_HOUR` 调整。

## 手动触发测试

到仓库 **Actions → AI News Push → Run workflow** 手动运行一次：
- 若现在不在推送窗口（默认 07:00–11:00 北京时间），会打印 `Outside push window` 并成功退出（用于验证配置没坏）。
- 想在窗口外真正测一次推送，在 workflow 手动运行时的输入框里把 `force_window` 设为
  `true` 可跳过窗口检查（改完记得撤销）。

（脚本用环境变量 `RSS_FEED_URL`、`PUSH_START_HOUR`、`PUSH_END_HOUR`、`SEND_SILENT` 支持自定义，默认即可。）