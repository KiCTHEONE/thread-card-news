"""Claude로 한 시간치 정치 기사를 카드뉴스용으로 종합한다."""
import json
from datetime import datetime, timezone, timedelta

import anthropic

KST = timezone(timedelta(hours=9))

SYSTEM_PROMPT = """당신은 한국 정치 뉴스를 매시간 정리하는 중립적인 뉴스 에디터입니다.
주어진 기사 목록(제목, 요약, 언론사)만 근거로 지난 한 시간의 주요 정치 이슈를 카드뉴스로 정리합니다.

원칙:
- 기사에 없는 사실, 수치, 발언을 만들어내지 않는다. 불확실하면 쓰지 않는다.
- 특정 정당이나 인물을 편들거나 평가하지 않는다. 양측 입장이 있으면 둘 다 짧게 적는다.
- 같은 사건을 다룬 기사는 하나의 카드로 묶는다. 중요도 순으로 3~6장.
- 문장은 짧고 명확하게, '~했다/~이다' 체로 쓴다. 이모지는 쓰지 않는다.
- 기사를 그대로 베끼지 말고 자신의 문장으로 요약한다.

필드 규칙:
- headline: 표지 제목, 20자 이내. 이번 시간 가장 큰 흐름을 담는다.
- cards[].tag: 분야 한 단어(예: 국회, 대통령실, 여당, 야당, 선거, 외교안보, 사법).
- cards[].title: 22자 이내.
- cards[].body: 90~120자, 2~3문장.
- cards[].source_ids: 근거 기사 번호 목록.
- thread_text: 쓰레드 본문. 400자 이내. 첫 줄에 시간대 표시 없이 핵심 한 줄, 이어서 '•'로 시작하는 항목 3~5개.
- topic_tag: 쓰레드 주제 태그 하나(공백 없이, # 없이). 예: 정치뉴스
- worth_posting: 정치 기사가 너무 적거나 의미 있는 내용이 없으면 false."""

SCHEMA = {
    "type": "object",
    "properties": {
        "worth_posting": {"type": "boolean"},
        "headline": {"type": "string"},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["tag", "title", "body", "source_ids"],
                "additionalProperties": False,
            },
        },
        "thread_text": {"type": "string"},
        "topic_tag": {"type": "string"},
    },
    "required": ["worth_posting", "headline", "cards", "thread_text", "topic_tag"],
    "additionalProperties": False,
}


def _format_articles(articles):
    lines = []
    for i, a in enumerate(articles, 1):
        t = datetime.fromtimestamp(a.published, KST).strftime("%H:%M")
        lines.append(f"[{i}] ({a.source}, {t}) {a.title}\n    {a.summary}")
    return "\n".join(lines)


def summarize(articles, model, now=None):
    now = now or datetime.now(KST)
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{
            "role": "user",
            "content": f"현재 시각: {now:%Y-%m-%d %H:%M} (KST)\n\n기사 목록:\n{_format_articles(articles)}",
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"요약 요청이 거절되었습니다: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("요약 응답이 max_tokens에서 잘렸습니다.")
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)

    # 모델이 규칙을 넘겨도 카드/쓰레드 제약은 코드에서 보장한다
    data["cards"] = data["cards"][:6]
    for card in data["cards"]:
        card["source_ids"] = [i for i in card["source_ids"] if 1 <= i <= len(articles)]
    return data
