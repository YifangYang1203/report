#!/usr/bin/env python3
"""Generate a focused Chinese daily brief and optionally send it by email."""

from __future__ import annotations

import html
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "20"))
LOOKBACK_HOURS = int(os.getenv("NEWS_LOOKBACK_HOURS", "48"))
USER_AGENT = "daily-ai-research-report/2.0 (+https://github.com/YifangYang1203/report)"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    kind: str = "feed"


@dataclass
class Item:
    topic: str
    title: str
    url: str
    summary: str
    source: str
    published: str = ""
    published_at: datetime | None = None
    score: int = 0


def chinese_news(query: str) -> str:
    return "https://news.google.com/rss/search?q=" + quote_plus(query) + "+when%3A2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"


TOPICS = {
    "Codex": {
        "description": "中文媒体报道的 OpenAI Codex、编程智能体和开发者实践",
        "terms": ("codex", "代码智能体", "编程", "开发者", "软件工程"),
        "sources": (
            Source("中文科技资讯", chinese_news("OpenAI Codex 编程 智能体")),
            Source("机器之心", "https://www.jiqizhixin.com/rss"),
        ),
    },
    "ChatGPT": {
        "description": "中文媒体报道的 ChatGPT 功能、模型和使用方法",
        "terms": ("chatgpt", "gpt", "人工智能", "模型", "智能助手", "openai"),
        "sources": (
            Source("中文 AI 资讯", chinese_news("ChatGPT 更新 功能 使用方法")),
            Source("量子位", "https://www.qbitai.com/feed"),
        ),
    },
    "Google": {
        "description": "中文媒体报道的 Google、Gemini 和 Google Research 动态",
        "terms": ("google", "谷歌", "gemini", "deepmind", "人工智能", "大模型"),
        "sources": (
            Source("中文 Google AI 资讯", chinese_news("Google Gemini 谷歌 人工智能")),
            Source("机器之心", "https://www.jiqizhixin.com/rss"),
        ),
    },
    "常用 Skills": {
        "description": "中文媒体介绍的 AI Skills、MCP、智能体和自动化工作流",
        "terms": ("skill", "技能", "agent", "智能体", "mcp", "工作流", "自动化"),
        "sources": (
            Source("中文 AI 工具资讯", chinese_news("AI Agent MCP Skills 工作流 教程")),
            Source("少数派", "https://sspai.com/feed"),
        ),
    },
    "数学建模": {
        "description": "中文来源中的数学建模、优化、仿真和科学计算工具",
        "terms": ("数学建模", "建模", "优化", "仿真", "科学计算", "求解器", "预测", "数据分析"),
        "sources": (
            Source("中文数学建模资讯", chinese_news("数学建模 工具 优化 仿真 科学计算")),
            Source("中文数据分析资讯", chinese_news("Python 数据分析 数学建模 求解器")),
        ),
    },
    "科研工具": {
        "description": "中文来源中的文献检索、论文阅读、数据分析和科研协作工具",
        "terms": ("科研", "论文", "文献", "数据集", "学术", "研究", "实验", "工具"),
        "sources": (
            Source("中文科研工具资讯", chinese_news("科研工具 文献 论文 数据分析")),
            Source("中文科研资讯", chinese_news("科研 AI 工具 论文阅读")),
        ),
    },
}


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def clean_text(value: str, limit: int = 360) -> str:
    parser = _HTMLText()
    parser.feed(html.unescape(value or ""))
    text = re.sub(r"\s+", " ", parser.text()).strip()
    text = re.sub(r"^\s*(摘要|description|summary)\s*[:：-]\s*", "", text, flags=re.I)
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def child_text(node: ET.Element, names: Iterable[str]) -> str:
    for child in list(node):
        if child.tag.rsplit("}", 1)[-1].lower() in names:
            return "".join(child.itertext()).strip()
    return ""


def parse_published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def fetch_url(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def feed_items(source: Source) -> list[Item]:
    root = ET.fromstring(fetch_url(source.url))
    nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    result: list[Item] = []
    for node in nodes[:30]:
        title = clean_text(child_text(node, {"title"}), 180)
        summary = clean_text(child_text(node, {"description", "summary", "content", "encoded"}))
        if not summary:
            summary = f"来自 {source.name} 的最新条目，建议打开原文确认具体更新内容。"
        link = child_text(node, {"link"})
        if not link:
            for child in list(node):
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        published = clean_text(child_text(node, {"pubdate", "published", "updated", "date"}), 80)
        published_at = parse_published(published)
        if title and link and published_at:
            result.append(Item("", title, link.strip(), summary, source.name, published, published_at))
    return result


def github_items(source: Source) -> list[Item]:
    import json
    payload = json.loads(fetch_url(source.url, {"Accept": "application/vnd.github+json"}))
    return [Item("", clean_text(repo.get("full_name", ""), 180), repo.get("html_url", ""), clean_text(repo.get("description", "")) or "近期更新的开源项目，可进一步查看 README、示例和许可证。", source.name, repo.get("updated_at", ""), parse_published(repo.get("updated_at", ""))) for repo in payload.get("items", [])[:30]]


def relevance(item: Item, terms: tuple[str, ...]) -> int:
    haystack = f"{item.title} {item.summary}".lower()
    return sum(2 if term.lower() in item.title.lower() else 1 for term in terms if term.lower() in haystack)


def is_low_value_title(title: str) -> bool:
    blocked = ("登录", "注册", "广告", "招聘", "优惠", "抽奖", "转载授权", "免责声明")
    return any(token in title for token in blocked)


def collect_topic(topic: str, config: dict, per_topic: int = 4) -> list[Item]:
    candidates: list[Item] = []
    errors: list[str] = []
    for source in config["sources"]:
        try:
            fetched = github_items(source) if source.kind == "github" else feed_items(source)
            for item in fetched:
                if not item.published_at or item.published_at < datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS):
                    continue
                if is_low_value_title(item.title):
                    continue
                item.topic = topic
                age_hours = max(0.0, (datetime.now(timezone.utc) - item.published_at).total_seconds() / 3600)
                item.score = relevance(item, config["terms"]) * 10 + max(0, int(LOOKBACK_HOURS - age_hours))
                if item.score > 0:
                    candidates.append(item)
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")
    result: list[Item] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in sorted(candidates, key=lambda x: (x.score, x.published_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True):
        title_key = re.sub(r"\W+", "", item.title.lower(), flags=re.UNICODE)
        if item.url not in seen_urls and title_key not in seen_titles:
            result.append(item)
            seen_urls.add(item.url)
            seen_titles.add(title_key)
        if len(result) >= per_topic:
            break
    if not result:
        note = "本轮没有找到通过主题筛选的可靠新内容，已跳过无关链接。"
        if errors:
            note += " 来源暂时不可用：" + "; ".join(errors[:2])
        result.append(Item(topic, "本轮暂无可靠更新", "", note, "筛选器"))
    return result


def build_report(when: datetime, per_topic: int = 4) -> str:
    lines = ["# 每日 AI / 科研工具简报", f"生成时间：{when.astimezone().strftime('%Y-%m-%d %H:%M %Z')}", "", "本简报只保留与指定主题直接相关的内容；每条均含一句摘要，链接仅作为原文核验入口。", ""]
    topic_items: list[tuple[str, dict, list[Item]]] = []
    for topic, config in TOPICS.items():
        items = collect_topic(topic, config, per_topic)
        topic_items.append((topic, config, items))
    for topic, config, items in topic_items:
        lines.extend([f"## {topic}", config["description"], ""])
        for index, item in enumerate(items, 1):
            line = f"{index}. **{item.title}**\n   - 摘要：{item.summary}"
            if item.url:
                line += f"\n   - 原文：{item.url}"
            lines.extend([line, ""])
    return "\n".join(lines).strip() + "\n"


def markdown_to_html(report: str) -> str:
    escaped = html.escape(report)
    escaped = re.sub(r"^### (.+)$", r"<h3>\1</h3>", escaped, flags=re.M)
    escaped = re.sub(r"^## (.+)$", r"<h2>\1</h2>", escaped, flags=re.M)
    escaped = re.sub(r"^# (.+)$", r"<h1>\1</h1>", escaped, flags=re.M)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', escaped)
    return "<html><body style='font-family:Arial,sans-serif;line-height:1.65;max-width:900px'>" + escaped.replace("\n\n", "<br><br>").replace("\n", "<br>") + "</body></html>"


def save_report(report_text: str, stamp: str) -> str:
    output_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{stamp}.md")
    for path in (output_path, os.path.join(output_dir, "latest.md")):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report_text)
    return output_path


def send_email(report_text: str, stamp: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT") or "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_addr = os.getenv("SMTP_FROM") or smtp_user
    to_addr = os.getenv("REPORT_TO") or os.getenv("SMTP_TO")
    if not all((smtp_host, smtp_user, smtp_password, from_addr, to_addr)):
        raise RuntimeError("SMTP_HOST/SMTP_USER/SMTP_PASSWORD/SMTP_FROM/REPORT_TO 未配置，拒绝假装发送。")
    msg = EmailMessage()
    msg["Subject"] = f"每日 AI / 科研工具简报｜{stamp}"
    msg["From"], msg["To"] = from_addr, to_addr
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg.set_content(report_text)
    msg.add_alternative(markdown_to_html(report_text), subtype="html")
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        if smtp_port != 25:
            server.starttls()
            server.ehlo()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    print(f"Email sent to {to_addr}")


def main() -> int:
    when = datetime.now(timezone.utc)
    stamp = when.strftime("%Y-%m-%d")
    report_text = build_report(when, int(os.getenv("ITEMS_PER_TOPIC", "4")))
    output_path = save_report(report_text, stamp)
    print(f"Report saved to {output_path}")
    if "--send" in sys.argv[1:]:
        send_email(report_text, stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
