# AI 新闻推送（Telegram）

每天从 [橘鸦 AI 早报 RSS](https://daily.juya.uk/rss.xml) 拉取当天新闻，
直接推送到 Telegram（不含摘要，原文链接推送）。
用 GitHub Actions 定时触发，**你的电脑开不开机都没关系**。

## 文件

- `.github/workflows/ai-news.yml` — 定时工作流（全天每 10 分钟触发一次）
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

## 推送策略

RSS 每天早报发布后只推一次，**不限制时间**：
当日首条新条目出现即推送，并把已推送条目标记为已读，之后当天不再重复推送。
调度全天每 10 分钟触发一次，能容忍 GitHub Actions 的 schedule 触发延迟；
核心保证是「当天内只推一次」，靠日期过滤 + 去重实现。

## 手动触发测试

到仓库 **Actions → AI News Push → Run workflow** 手动运行一次：
- 若当天内容尚未推送过，会正常推送到 Telegram。
- 若当天已推送过，会打印 `Skipping already-pushed` / `No new items for today` 并成功退出。

（脚本用环境变量 `RSS_FEED_URL`、`SEND_SILENT` 支持自定义，默认即可。）