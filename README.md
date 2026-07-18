# Daily AI / Research Report

这个仓库会每天生成一份包含以下主题内容的日报：
- codex
- chatgpt
- Google
- 常用的 skills
- 数学建模好用的东西
- 科研工具推荐

每个主题抓取 3 条公开结果，并整理为 Markdown 报告。

## 运行方式

生成日报：

```bash
python3 report_daily.py
```

生成并发送邮件：

```bash
python3 report_daily.py --send
```

## 配置邮件发送

在运行前设置下面这些环境变量：

```bash
export SMTP_HOST='smtp.example.com'
export SMTP_PORT='587'
export SMTP_USER='your@example.com'
export SMTP_PASSWORD='your-password'
export SMTP_FROM='your@example.com'
export REPORT_TO='recipient@example.com'
```

然后执行：

```bash
python3 report_daily.py --send
```

## 定时执行

如果你的环境支持 cron，可以加入下面这条任务，让它每天早上 7:30 自动执行：

```bash
30 7 * * * /workspaces/report/run_daily_report.sh >> /workspaces/report/cron.log 2>&1
```

如果你希望我继续把它改成直接支持 Gmail/Outlook/163 等常见邮箱服务的版本，我也可以继续补上。