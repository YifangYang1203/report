#!/usr/bin/env python3
import os
import re
import sys
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import List, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests


BASE_URL = "https://r.jina.ai/http://https://html.duckduckgo.com/html/?q="
TOPICS = [
    {
        "title": "codex",
        "query": 'site:twitter.com codex',
        "description": "Codex-related X/Twitter public mentions",
    },
    {
        "title": "chatgpt",
        "query": 'site:twitter.com chatgpt',
        "description": "ChatGPT-related X/Twitter public mentions",
    },
    {
        "title": "Google",
        "query": 'site:twitter.com Google',
        "description": "Google-related X/Twitter public mentions",
    },
    {
        "title": "常用的 skills",
        "query": 'site:twitter.com "AI skills"',
        "description": "Common AI skill discussions and learning resources",
    },
    {
        "title": "数学建模好用的东西",
        "query": 'site:twitter.com "数学建模" 工具',
        "description": "Useful tools and methods for mathematical modeling",
    },
    {
        "title": "科研工具推荐",
        "query": 'site:twitter.com "科研工具" 推荐',
        "description": "Research tools and workflow recommendations",
    },
]


def build_search_url(query: str) -> str:
    return f"{BASE_URL}{quote(query)}"


def decode_duckduckgo_url(raw_url: str) -> str:
    if not raw_url:
        return raw_url
    if raw_url.startswith("https://duckduckgo.com/l/?uddg="):
        parsed = urlparse(raw_url)
        values = parse_qs(parsed.query).get("uddg", [])
        if values:
            return unquote(values[0])
    return raw_url


def is_relevant_twitter_result(title: str, url: str) -> bool:
    if not url.startswith("http"):
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "twitter.com" not in host and "x.com" not in host:
        return False
    title_lower = title.lower()
    blocked_tokens = [
        "log in",
        "sign in",
        "robots.txt",
        "developer platform",
        "blog.twitter.com",
        "support.twitter.com",
        "help.twitter.com",
        "about.twitter.com",
        "privacy",
        "terms",
        "twitter. it's what's happening",
    ]
    if any(token in title_lower for token in blocked_tokens):
        return False
    if any(token in url.lower() for token in ["/login", "/i/flow", "/robots.txt", "/help", "/support", "/privacy", "/terms"]):
        return False
    return True


def extract_results(text: str, limit: int = 3) -> List[Tuple[str, str]]:
    results: List[Tuple[str, str]] = []
    seen = set()
    patterns = [
        r'^\s*## \[(.*?)\]\((https?://.*?)\)\s*$',
        r'^\s*### \[(.*?)\]\((https?://.*?)\)\s*$',
        r'^\s*# \[(.*?)\]\((https?://.*?)\)\s*$',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE):
            title = re.sub(r'\s+', ' ', match.group(1)).strip()
            url = decode_duckduckgo_url(match.group(2).strip())
            title = title.replace("\u00a0", " ")
            if not is_relevant_twitter_result(title, url):
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append((title, url))
            if len(results) >= limit:
                return results
    # Fallback: capture the first few markdown links that are not internal DuckDuckGo links
    if not results:
        for match in re.finditer(r'\[(.*?)\]\((https?://[^)]+)\)', text):
            title = re.sub(r'\s+', ' ', match.group(1)).strip()
            url = decode_duckduckgo_url(match.group(2).strip())
            if url.startswith("https://duckduckgo.com") or url.startswith("https://html.duckduckgo.com"):
                continue
            if not is_relevant_twitter_result(title, url):
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append((title, url))
            if len(results) >= limit:
                break
    return results


def fetch_query_results(query: str, limit: int = 3) -> List[Tuple[str, str]]:
    url = build_search_url(query)
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        return [(f"Fetch error: {exc}", "")]
    content = response.text
    return extract_results(content, limit=limit)


def build_report(when: datetime) -> str:
    lines = []
    lines.append(f"# Daily AI / Research Report")
    lines.append(f"Generated at: {when.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
    for item in TOPICS:
        lines.append(f"## {item['title']}")
        lines.append(f"- 主题说明：{item['description']}")
        results = fetch_query_results(item['query'], limit=3)
        for idx, (title, url) in enumerate(results, start=1):
            display = title if title else "公开结果"
            if url:
                lines.append(f"{idx}. [{display}]({url})")
            else:
                lines.append(f"{idx}. {display}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def save_report(report_text: str, stamp: str) -> str:
    output_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{stamp}.md")
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(report_text)
    latest_path = os.path.join(output_dir, "latest.md")
    with open(latest_path, "w", encoding="utf-8") as fh:
        fh.write(report_text)
    return output_path


def send_email(report_text: str, stamp: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT") or "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_addr = os.getenv("SMTP_FROM") or smtp_user
    to_addr = os.getenv("REPORT_TO") or os.getenv("SMTP_TO")
    if not (smtp_host and smtp_user and smtp_password and from_addr and to_addr):
        print("SMTP settings are incomplete; report was saved locally only.")
        return

    msg = EmailMessage()
    msg.set_content(report_text)
    msg["Subject"] = f"Daily AI / Research Report {stamp}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    print(f"Email sent to {to_addr}")


def main() -> int:
    when = datetime.now(timezone.utc)
    stamp = when.strftime("%Y-%m-%d")
    report_text = build_report(when)
    output_path = save_report(report_text, stamp)
    print(f"Report saved to {output_path}")
    if len(sys.argv) > 1 and sys.argv[1] == "--send":
        send_email(report_text, stamp)
    else:
        print("Use --send to email the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
