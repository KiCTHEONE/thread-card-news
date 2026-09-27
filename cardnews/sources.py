"""출처(언론사) 필터. 방송사 기사만 쓰도록 거른다.

구글 뉴스의 언론사 표기는 "KBS 뉴스", "대구MBC", "JTBC News"처럼 제각각이라
공백을 없애고 소문자로 바꾼 뒤 방송사 이름이 들어 있는지로 판단한다.
"""

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
