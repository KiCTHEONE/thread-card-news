"""RSS 피드에서 최근 정치 기사를 모은다."""
import calendar
import html
import re
import time
from dataclasses import dataclass

import feedparser

from .sources import display_name

USER_AGENT = "Mozilla/5.0 (compatible; thread-card-news/1.0)"

# 피드 제목 대신 카드에 짧게 표시할 언론사 이름
SOURCE_NAMES = {
    "yna.co.kr": "연합뉴스",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "donga.com": "동아일보",
    "mk.co.kr": "매일경제",
}


def _source_name(url, fallback):
    for domain, name in SOURCE_NAMES.items():
        if domain in url:
            return name
    return fallback


@dataclass
class Article:
    title: str
    summary: str
    link: str
    source: str
    published: float  # unix time
    foreign: bool = False  # 해외 언론 영문 기사 (요약할 때 한국어로 옮김)


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
        source = _source_name(url, _clean(parsed.feed.get("title", "")) or url)
        before = len(articles)
        for entry in parsed.entries:
            ts = entry.get("published_parsed") or entry.get("updated_parsed")
            if not ts:
                continue
            published = calendar.timegm(ts)
            link = entry.get("link", "")
            title = _clean(entry.get("title", ""))
            outlet = display_name(_clean(entry.get("source", {}).get("title", "")))
            if outlet and title.endswith(f" - {outlet}"):
                title = title[: -len(outlet) - 3]  # 구글뉴스 "제목 - 언론사" 꼬리 제거
            key = _normalize_title(title)
            if published < cutoff or not link or link in seen_links or not key or key in titles:
                continue
            titles.add(key)
            articles.append(Article(
                title=title,
                summary=_clean(entry.get("summary", ""))[:400],
                link=link,
                source=outlet or source,
                published=published,
            ))
        print(f"[fetch] {source}: 전체 {len(parsed.entries)}건 중 새 기사 {len(articles) - before}건")
    articles.sort(key=lambda a: a.published, reverse=True)
    return articles[:max_articles]


def dedupe(articles):
    """여러 번 수집한 기사 목록에서 링크·제목이 겹치는 기사를 뺀다."""
    seen, out = set(), []
    for a in articles:
        key = _normalize_title(a.title)
        if a.link in seen or key in seen:
            continue
        seen.update((a.link, key))
        out.append(a)
    return out


def resolve_google_links(articles):
    """구글 뉴스 리디렉트 주소(news.google.com/rss/articles/...)를 언론사 원문 주소로 바꾼다.

    실패한 기사는 원래 주소를 그대로 둔다 (출처 답글에서 링크 없이 제목만 표시됨).
    """
    targets = [a for a in articles if "news.google.com" in a.link]
    if not targets:
        return
    try:
        from googlenewsdecoder import gnewsdecoder

        results = gnewsdecoder([a.link for a in targets], timeout=15)
    except Exception as e:
        print(f"[fetch] 구글 뉴스 원문 주소 변환 실패: {e}")
        return
    for a, r in zip(targets, results):
        if r.get("success") and r.get("decoded_url", "").startswith("http"):
            a.link = r["decoded_url"]
        else:
            print(f"[fetch] 원문 주소 변환 실패 ({a.source}) {a.title}: {r.get('message')}")
