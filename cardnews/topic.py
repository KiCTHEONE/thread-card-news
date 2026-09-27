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
    return topic if topic.get("enabled") else None


def google_news_feeds(queries, lookback_minutes):
    # 구글 뉴스 검색 RSS. when: 연산자로 최근 기사만 받는다
    days = max(1, -(-lookback_minutes // 1440))
    return [
        f"https://news.google.com/rss/search?q={quote(q + f' when:{days}d')}&hl=ko&gl=KR&ceid=KR:ko"
        for q in queries
    ]


def matches(article, keywords):
    text = f"{article.title} {article.summary}"
    return any(k in text for k in keywords)
