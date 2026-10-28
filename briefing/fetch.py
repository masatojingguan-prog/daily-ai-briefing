"""RSS / Atom フィードから直近の記事を集める。"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from calendar import timegm

import feedparser
import requests

USER_AGENT = "daily-ai-briefing/1.0 (+https://github.com/masatojingguan-prog/daily-ai-briefing)"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class Article:
    source: str
    category: str
    title: str
    url: str
    published: datetime
    excerpt: str


def _clean(text: str, limit: int) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
    return None


def fetch_feed(feed: dict, since: datetime, max_items: int, summary_chars: int) -> list[Article]:
    resp = requests.get(feed["url"], headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    articles = []
    for entry in parsed.entries:
        published = _published(entry)
        if published is None or published < since:
            continue
        body = entry.get("summary") or ""
        if not body and entry.get("content"):
            body = entry["content"][0].get("value", "")
        articles.append(
            Article(
                source=feed["name"],
                category=feed.get("category", "misc"),
                title=_clean(entry.get("title", "(no title)"), 200),
                url=entry.get("link", ""),
                published=published,
                excerpt=_clean(body, summary_chars),
            )
        )
    articles.sort(key=lambda a: a.published, reverse=True)
    return articles[:max_items]


def collect(config: dict) -> tuple[list[Article], list[str]]:
    """全フィードを取得し、(記事一覧, 失敗したフィード名) を返す。"""
    settings = config.get("settings", {})
    since = datetime.now(timezone.utc) - timedelta(hours=settings.get("hours_back", 26))
    max_items = settings.get("max_items_per_feed", 15)
    summary_chars = settings.get("summary_chars", 400)

    articles: list[Article] = []
    failures: list[str] = []
    seen_urls: set[str] = set()
    for feed in config["feeds"]:
        try:
            items = fetch_feed(feed, since, max_items, summary_chars)
        except Exception as e:  # 1つのフィードの失敗で全体を止めない
            print(f"[warn] {feed['name']}: {e}")
            failures.append(feed["name"])
            continue
        for a in items:
            if a.url and a.url not in seen_urls:
                seen_urls.add(a.url)
                articles.append(a)
        print(f"[info] {feed['name']}: {len(items)} 件")
    return articles, failures
