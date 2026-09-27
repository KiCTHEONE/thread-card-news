import os

# 정치 기사 RSS 피드 목록. FEEDS 환경변수(쉼표 구분)로 덮어쓸 수 있다.
DEFAULT_FEEDS = [
    "https://www.yna.co.kr/rss/politics.xml",
    "https://www.hani.co.kr/rss/politics/",
    "https://www.khan.co.kr/rss/rssdata/politic_news.xml",
    "https://rss.donga.com/politics.xml",
    "https://www.mk.co.kr/rss/30200030/",
    "https://news.google.com/rss/headlines/section/topic/NATION?hl=ko&gl=KR&ceid=KR:ko",
]

FEEDS = [f.strip() for f in os.environ.get("FEEDS", "").split(",") if f.strip()] or DEFAULT_FEEDS

# 몇 분 이내 기사를 모을지 (한 시간 주기 + 여유분)
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "90"))
# 이 개수보다 새 기사가 적으면 이번 회차는 건너뛴다
MIN_ARTICLES = int(os.environ.get("MIN_ARTICLES", "3"))
MAX_ARTICLES = int(os.environ.get("MAX_ARTICLES", "40"))

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")

THREADS_USER_ID = os.environ.get("THREADS_USER_ID", "")
THREADS_ACCESS_TOKEN = os.environ.get("THREADS_ACCESS_TOKEN", "")

ACCOUNT_HANDLE = os.environ.get("ACCOUNT_HANDLE", "@politics_hourly")
FONT_PATH = os.environ.get("CARD_FONT_PATH", "")
