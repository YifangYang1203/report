# 每日 AI / 科研工具简报

每天自动采集并发送一封中文简报，固定覆盖：Codex、ChatGPT、Google/Gemini、常用 AI skills、数学建模工具、科研工具推荐。

## 这版解决的问题

旧版只搜索 Twitter/X，容易得到账号主页、登录页和广告，而且没有摘要。新版只读取中文 RSS 和中文 Google 新闻 RSS，不调用 OpenAI 或其他翻译 API；每个主题先做关键词相关性筛选、去重，再输出“中文标题/摘要 + 原文入口”。没有可靠结果时会明确写“本轮暂无可靠更新”，不会用无关链接凑数。

## 本地运行

```bash
python -m pip install -r requirements.txt
python report_daily.py
python report_daily.py --send
```

默认每个主题最多 4 条，可用 `ITEMS_PER_TOPIC=3` 调整。单个来源失败不会让其他主题消失；邮件配置不完整时程序会直接失败，避免误以为已经发送。

## GitHub Actions 配置

在仓库 Settings → Secrets and variables → Actions 中配置：

```text
SMTP_HOST       邮箱 SMTP 服务器，例如 smtp.qq.com
SMTP_PORT       通常为 587
SMTP_USER       发件邮箱账号
SMTP_PASSWORD   SMTP 授权码，不是网页登录密码
SMTP_FROM       发件地址，通常与 SMTP_USER 相同
REPORT_TO       接收简报的邮箱地址
```

工作流每天 UTC 23:30 运行，即北京时间 07:30；也可以在 Actions 页面用 `workflow_dispatch` 手动测试。邮件包含纯文本和 HTML 两个版本，正文就是整理后的中文简报，不再只是链接清单。
