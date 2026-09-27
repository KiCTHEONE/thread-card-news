"""같은 사건을 다룬 기사·카드인지 제목으로 판별한다.

언론사마다 제목 표현이 달라 단어 단위 비교는 잘 안 맞으므로, 공백·기호를 뺀 글자 2개씩(바이그램)의
겹침 정도를 본다. 짧은 쪽 제목의 바이그램이 긴 쪽에 얼마나 들어 있는지(포함도)를 쓴다.
"""
import re

# 거의 모든 정치 기사에 나오는 말은 비교에서 뺀다
STOPWORDS = ["여야", "정부", "대통령", "국회", "의원", "관련", "논란", "속보", "단독", "종합"]


def _bigrams(text):
    text = re.sub(r"\[[^\]]*\]", "", text)  # [포토], [속보] 같은 말머리
    for w in STOPWORDS:
        text = text.replace(w, "")
    text = re.sub(r"[^0-9A-Za-z가-힣一-鿿]", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def similarity(a, b):
    x, y = _bigrams(a), _bigrams(b)
    if not x or not y:
        return 0.0
    return len(x & y) / min(len(x), len(y))


def is_repeat(title, previous, threshold=0.5):
    return any(similarity(title, p) >= threshold for p in previous)
