#!/usr/bin/env python3
"""Generate a focused Chinese daily brief and optionally send it by email."""

from __future__ import annotations

import html
import json
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from html.parser import HTMLParser
from typing import Iterable
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "20"))
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
    score: int = 0


TOPICS = {
    "Codex": {
        "description": "OpenAI Codex 的官方更新、发布和工程实践",
        "terms": ("codex", "agent", "coding", "软件工程", "开发者"),
        "sources": (
            Source("OpenAI Codex Releases", "https://github.com/openai/codex/releases.atom"),
            Source("OpenAI News", "https://openai.com/news/rss.xml"),
        ),
    },
    "ChatGPT": {
        "description": "ChatGPT 的官方功能、模型、工作流和使用方法",
        "terms": ("chatgpt", "gpt-", "model", "memory", "deep research", "openai"),
        "sources": (
            Source("OpenAI News", "https://openai.com/news/rss.xml"),
            Source("OpenAI Cookbook", "https://github.com/openai/openai-cookbook/releases.atom"),
        ),
    },
    "Google": {
        "description": "Google、Gemini、Google Research 和开发者产品的重点更新",
        "terms": ("google", "gemini", "deepmind", "android", "cloud", "research"),
        "sources": (
            Source("Google AI Blog", "https://blog.google/technology/ai/rss/"),
            Source("Google Research", "https://research.google/blog/rss/"),
        ),
    },
    "常用 Skills": {
        "description": "可直接复用的 AI skills、智能体工具和自动化工作流",
        "terms": ("skill", "agent", "mcp", "automation", "workflow", "copilot"),
        "sources": (
            Source("GitHub AI repositories", "https://api.github.com/search/repositories?q=topic%3Aai+OR+topic%3Amcp+OR+topic%3Aagent&sort=updated&order=desc&per_page=20", "github"),
            Source("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
        ),
    },
    "数学建模": {
        "description": "数学建模、优化、仿真、数据分析和竞赛中可落地的工具",
        "terms": ("optimization", "simulation", "modeling", "mathematical", "科学计算", "solver", "forecast"),
        "sources": (
            Source("arXiv AI/ML", "https://export.arxiv.org/rss/cs.LG"),
            Source("GitHub modeling repositories", "https://api.github.com/search/repositories?q=mathematical+modeling+OR+optimization+OR+simulation&sort=updated&order=desc&per_page=20", "github"),
        ),
    },
    "科研工具": {
        "description": "文献检索、论文阅读、数据分析、可重复研究和科研协作工具",
        "terms": ("research", "scientific", "paper", "dataset", "reproduc", "literature", "科研", "scholar"),
        "sources": (
            Source("Nature Methods", "https://www.nature.com/nmeth.rss"),
            Source("Papers with Code", "https://paperswithcode.com/feeds/latest"),
            Source("arXiv Research", "https://export.arxiv.org/rss/cs.DL"),
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
        published = clean_text(child_text(node, {"pubdate", "published", "updated", "date"}), 40)
        if title and link:
            result.append(Item("", title, link.strip(), summary, source.name, published))
    return result


def github_items(source: Source) -> list[Item]:
    import json
    payload = json.loads(fetch_url(source.url, {"Accept": "application/vnd.github+json"}))
    return [Item("", clean_text(repo.get("full_name", ""), 180), repo.get("html_url", ""), clean_text(repo.get("description", "")) or "近期更新的开源项目，可进一步查看 README、示例和许可证。", source.name, repo.get("updated_at", "")) for repo in payload.get("items", [])[:30]]


def relevance(item: Item, terms: tuple[str, ...]) -> int:
    haystack = f"{item.title} {item.summary}".lower()
    return sum(2 if term.lower() in item.title.lower() else 1 for term in terms if term.lower() in haystack)


def collect_topic(topic: str, config: dict, per_topic: int = 4) -> list[Item]:
    candidates: list[Item] = []
    errors: list[str] = []
    for source in config["sources"]:
        try:
            fetched = github_items(source) if source.kind == "github" else feed_items(source)
            for item in fetched:
                item.topic = topic
                item.score = relevance(item, config["terms"])
                if item.score > 0:
                    candidates.append(item)
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")
    result: list[Item] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in sorted(candidates, key=lambda x: (x.score, x.published), reverse=True):
        title_key = re.sub(r"[^a-z0-9]+", "", item.title.lower())
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


def _response_text(payload: dict) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    parts: list[str] = []
    for output in payload.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "\n".join(parts)


def translate_items(items: list[Item]) -> None:
    """Translate titles and summaries in one API call so the email is Chinese."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        if "--send" in sys.argv[1:] and os.getenv("REQUIRE_CHINESE", "1") == "1":
            raise RuntimeError("要发送中文简报，请配置 OPENAI_API_KEY；它与 SMTP_PASSWORD 是两项不同的密钥。")
        return
    source_items = [{"id": index, "title": item.title, "summary": item.summary} for index, item in enumerate(items)]
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "store": False,
        "instructions": "你是中文科技简报编辑。把给定的英文标题和摘要翻译并压缩成自然、准确、易懂的简体中文。不要添加原文没有的事实。只返回 JSON 数组，每项字段必须是 id、title_zh、summary_zh。摘要最多两句话。",
        "input": json.dumps(source_items, ensure_ascii=False),
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
        text = _response_text(payload).strip()
        match = re.search(r"\[[\s\S]*\]", text)
        translated = json.loads(match.group(0) if match else text)
        by_id = {int(entry["id"]): entry for entry in translated}
        for index, item in enumerate(items):
            entry = by_id.get(index)
            if entry:
                item.title = clean_text(str(entry.get("title_zh", item.title)), 180)
                item.summary = clean_text(str(entry.get("summary_zh", item.summary)))
    except Exception as exc:
        if os.getenv("REQUIRE_CHINESE", "1") == "1":
            raise RuntimeError(f"中文翻译失败，已停止发送以避免发出英文简报：{exc}") from exc
        print(f"Chinese translation skipped: {exc}")


def build_report(when: datetime, per_topic: int = 4) -> str:
    lines = ["# 每日 AI / 科研工具简报", f"生成时间：{when.astimezone().strftime('%Y-%m-%d %H:%M %Z')}", "", "本简报只保留与指定主题直接相关的内容；每条均含一句摘要，链接仅作为原文核验入口。", ""]
    all_items: list[Item] = []
    topic_items: list[tuple[str, dict, list[Item]]] = []
    for topic, config in TOPICS.items():
        items = collect_topic(topic, config, per_topic)
        all_items.extend(items)
        topic_items.append((topic, config, items))
    translate_items(all_items)
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
