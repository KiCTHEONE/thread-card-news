"""특정 주제만 다루는 모드 설정 (저장소 루트의 topic.json).

enabled가 false이거나 파일이 없으면 일반 정치 브리핑 모드로 동작한다.
"""
import json
import os
from urllib.parse import quote

TOPIC_FILE = os.environ.get("TOPIC_FILE", "topic.json")


def load_topic():
    if not os.path.exists(TOPIC_FILE):
        return None
    with open(TOPIC_FILE, encoding="utf-8") as f:
        topic = json.load(f)
    if not topic.get("enabled"):
        return None
    # categories가 {분류: [검색어...]} 형태면 검색어 목록을 합쳐 쓴다 (겹치는 검색어는 한 번만)
    if isinstance(topic.get("categories"), dict):
        queries = [q for terms in topic["categories"].values() for q in terms]
        topic["search_queries"] = list(dict.fromkeys(queries + topic.get("search_queries", [])))
    return topic


def google_news_feeds(queries, lookback_minutes, sites=()):
    """구글 뉴스 검색 RSS 주소. when: 으로 최근 기사만, sites가 있으면 해당 도메인에서만 찾는다."""
    days = max(1, -(-lookback_minutes // 1440))
    site_filter = f" ({' OR '.join('site:' + d for d in sites)})" if sites else ""
    return [
        f"https://news.google.com/rss/search?q={quote(q + site_filter + f' when:{days}d')}&hl=ko&gl=KR&ceid=KR:ko"
        for q in queries
    ]


def matches(article, keywords):
    text = f"{article.title} {article.summary}"
    return any(k in text for k in keywords)
