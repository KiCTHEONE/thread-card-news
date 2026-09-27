"""출처(언론사) 필터. 방송사 기사만 쓰도록 거른다.

구글 뉴스의 언론사 표기는 "KBS 뉴스", "대구MBC", "JTBC News"처럼 제각각이라
공백을 없애고 소문자로 바꾼 뒤 방송사 이름이 들어 있는지로 판단한다.
"""
import re


# 이름에 들어 있으면 방송사로 보는 표기 (다른 언론사 이름과 겹칠 일이 없는 것만)
BROADCASTER_TOKENS = [
    # 공영·지상파
    "kbs", "mbc", "ebs", "sbs",
    # 종합편성·보도전문 채널
    "jtbc", "tv조선", "채널a", "mbn", "ytn", "연합뉴스tv",
    # 지역 민영방송
    "knn", "tbc", "tjb", "kbc", "jibs", "cjb", "jtv", "g1방송", "ubc울산", "obs",
    # 라디오·종교방송
    "cbs", "노컷뉴스", "bbs", "cpbc", "평화방송", "불교방송", "극동방송", "tbs",
    # 경제 방송
    "한국경제tv", "서울경제tv", "머니투데이방송", "mtn", "이데일리tv", "매일경제tv", "sbsbiz",
]


def _norm(name):
    return "".join(name.split()).lower()


def is_broadcaster(source):
    name = _norm(source)
    return any(token in name for token in BROADCASTER_TOKENS)


def source_allowed(source, policy, extra_allowed=()):
    if policy == "broadcast":
        return is_broadcaster(source) or source in extra_allowed
    if policy == "list":
        return source in extra_allowed
    return True


# 구글 뉴스에서 방송사 기사만 검색할 때 쓰는 도메인 (site: 검색)
BROADCASTER_DOMAINS = [
    "kbs.co.kr", "imbc.com", "sbs.co.kr", "ebs.co.kr",
    "jtbc.co.kr", "tvchosun.com", "ichannela.com", "mbn.co.kr", "ytn.co.kr", "yonhapnewstv.co.kr",
    "nocutnews.co.kr", "obsnews.co.kr", "knn.co.kr", "tbc.co.kr", "tjb.co.kr", "ikbc.co.kr",
    "g1tv.co.kr", "jibs.co.kr", "ubc.co.kr", "cjb.co.kr", "jtv.co.kr",
    "busanmbc.co.kr", "dgmbc.com", "kjmbc.co.kr", "tjmbc.co.kr", "mbcgn.kr", "jmbc.co.kr",
]


# 구글 뉴스가 언론사 이름 대신 도메인을 주는 경우 보기 좋은 이름으로 바꾼다
DOMAIN_NAMES = {
    "kbs.co.kr": "KBS", "imbc.com": "MBC", "sbs.co.kr": "SBS", "ebs.co.kr": "EBS",
    "jtbc.co.kr": "JTBC", "tvchosun.com": "TV조선", "ichannela.com": "채널A", "mbn.co.kr": "MBN",
    "ytn.co.kr": "YTN", "yonhapnewstv.co.kr": "연합뉴스TV", "yna.co.kr": "연합뉴스", "news1.kr": "뉴스1",
    "nocutnews.co.kr": "CBS노컷뉴스",
}


def display_name(source):
    name = source.strip().lower()
    for domain, label in DOMAIN_NAMES.items():
        if name == domain or name.endswith("." + domain):
            return label
    return source


# 해외 기사로 쓸 언론사 (구글 뉴스 표기 → 카드에 쓸 한국어 이름)
FOREIGN_OUTLETS = [
    ("reuters", "로이터"), ("associated press", "AP"), ("ap news", "AP"), ("bbc", "BBC"), ("cnn", "CNN"),
    ("new york times", "뉴욕타임스"), ("wall street journal", "월스트리트저널"), ("wsj", "월스트리트저널"),
    ("washington post", "워싱턴포스트"), ("bloomberg", "블룸버그"), ("financial times", "파이낸셜타임스"),
    ("the guardian", "가디언"), ("al jazeera", "알자지라"), ("nhk", "NHK"), ("kyodo", "교도통신"),
    ("nikkei", "닛케이"), ("npr", "NPR"), ("politico", "폴리티코"), ("the economist", "이코노미스트"),
    ("france 24", "프랑스24"), ("deutsche welle", "DW"), ("voice of america", "VOA"), ("voa", "VOA"),
    ("abc news", "ABC뉴스"), ("cbs news", "CBS뉴스"), ("nbc news", "NBC뉴스"), ("axios", "악시오스"),
    ("time", "타임"), ("the diplomat", "디플로맷"), ("south china morning post", "SCMP"),
    ("japan times", "재팬타임스"), ("nk news", "NK뉴스"), ("afp", "AFP"), ("the hill", "더힐"),
]


def foreign_outlet_name(source):
    """허용된 해외 언론사면 한국어 이름을, 아니면 None을 돌려준다.

    단어 단위로 비교한다 ("Yonhap News"가 "ap news"로, "Korea Times"가 "time"으로 잡히지 않게).
    """
    name = " ".join(source.lower().split())
    for token, label in FOREIGN_OUTLETS:
        if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", name):
            return label
    return None
