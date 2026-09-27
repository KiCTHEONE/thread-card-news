"""RSS 피드에서 최근 정치 기사를 모은다."""
import calendar
import html
import re
import time
from dataclasses import dataclass

import feedparser

USER_AGENT = "Mozilla/5.0 (compatible; thread-card-news/1.0)"


@dataclass
class Article:
    title: str
    summary: str
    link: str
    source: str
    published: float  # unix time


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _normalize_title(title: str) -> str:
    title = re.sub(r"\s+-\s+[^-]+$", "", title)  # 구글뉴스 "제목 - 언론사" 꼬리 제거
    return re.sub(r"[\W_]+", "", title)


def fetch_articles(feeds, lookback_minutes, seen_links, max_articles):
    cutoff = time.time() - lookback_minutes * 60
    articles, titles = [], set()
    for url in feeds:
        try:
            parsed = feedparser.parse(url, agent=USER_AGENT)
        except Exception as e:  # 피드 하나가 실패해도 나머지는 진행
            print(f"[fetch] {url} 실패: {e}")
            continue
        source = _clean(parsed.feed.get("title", "")) or url
        for entry in parsed.entries:
            ts = entry.get("published_parsed") or entry.get("updated_parsed")
            if not ts:
                continue
            published = calendar.timegm(ts)
            link = entry.get("link", "")
            title = _clean(entry.get("title", ""))
            key = _normalize_title(title)
            if published < cutoff or not link or link in seen_links or not key or key in titles:
                continue
            titles.add(key)
            articles.append(Article(
                title=title,
                summary=_clean(entry.get("summary", ""))[:400],
                link=link,
                source=_clean(entry.get("source", {}).get("title", "")) or source,
                published=published,
            ))
        print(f"[fetch] {source}: 누적 {len(articles)}건")
    articles.sort(key=lambda a: a.published, reverse=True)
    return articles[:max_articles]
