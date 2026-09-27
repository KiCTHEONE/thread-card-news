"""AI(Gemini 또는 Claude)로 한 시간치 정치 기사를 카드뉴스용으로 종합한다."""
import json
import time
from datetime import datetime, timezone, timedelta

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
        mark = ", 해외·영문" if getattr(a, "foreign", False) else ""
        lines.append(f"[{i}] ({a.source}{mark}, {t}) {a.title}\n    {a.summary}")
    return "\n".join(lines)


GEMINI_FALLBACK_MODEL = "gemini-flash-lite-latest"


def _call_gemini(user_content, model):
    from google import genai
    from google.genai import errors, types

    client = genai.Client()  # GEMINI_API_KEY 환경변수 사용
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=SCHEMA,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    # 무료 등급은 일시적인 한도 초과(429)나 과부하(503)가 잦아 재시도하고,
    # 그래도 안 되면 더 가벼운 모델로 한 번 더 시도한다
    models = [model] + ([GEMINI_FALLBACK_MODEL] if model != GEMINI_FALLBACK_MODEL else [])
    for m in models:
        for attempt in range(3):
            try:
                response = client.models.generate_content(model=m, contents=user_content, config=config)
                if not response.text:
                    raise RuntimeError(f"Gemini 응답이 비어 있습니다: {response.candidates}")
                print(f"[summarize] gemini / {m} 사용")
                return response.text
            except errors.APIError as e:
                if e.code not in (429, 500, 503):
                    raise
                if attempt == 2:
                    print(f"[summarize] {m} 계속 {e.code} 오류")
                    break
                wait = 20 * (attempt + 1)
                print(f"[summarize] {m} {e.code} 오류, {wait}초 후 재시도")
                time.sleep(wait)
    raise RuntimeError("Gemini가 계속 응답하지 않아 이번 회차를 건너뜁니다.")


def _call_claude(user_content, model):
    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"요약 요청이 거절되었습니다: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("요약 응답이 max_tokens에서 잘렸습니다.")
    return next(b.text for b in response.content if b.type == "text")


TOPIC_INSTRUCTIONS = """

[주제 모드]
이번에는 아래 주제에 관한 내용만 정리한다: {description}
- 주제와 관련 없는 기사는 무시한다.
- 중요한 이슈부터 카드로 나눈다. 여러 분야(선거, 특검, 군사·안보, 정당 등)에 소식이 있으면 한 분야에 몰지 말고 고르게 담는다. 관련 내용이 적으면 2장까지 줄여도 된다.
- 선관위·정당·후보 등 각 주체의 입장은 기사에 나온 대로만 전한다.
- 의혹이나 주장(예: 부정선거 주장)은 사실처럼 쓰지 말고 누가 주장했는지 밝힌다. 수사·재판 중인 사안은 결론을 단정하지 않는다.
- '해외·영문' 기사는 한국어로 옮겨 요약하고, 본문에 해외 보도임을 밝힌다 (예: "로이터에 따르면"). 고유명사는 국내에서 통용되는 한국어 표기를 쓴다.
- 여론조사는 기사에 나온 조사기관·수치만 그대로 쓰고, 수치를 계산하거나 바꾸지 않는다."""


def summarize(articles, provider, model, now=None, topic=None, recent_titles=()):
    now = now or datetime.now(KST)
    user_content = f"현재 시각: {now:%Y-%m-%d %H:%M} (KST)\n\n기사 목록:\n{_format_articles(articles)}"
    if topic:
        user_content += TOPIC_INSTRUCTIONS.format(description=topic["description"])
        if topic.get("categories"):
            user_content += "\n- cards[].tag는 다음 분류 중 하나만 쓴다: " + ", ".join(topic["categories"])
    if recent_titles:
        user_content += (
            "\n\n[최근 24시간 동안 이미 올린 소식]\n" + "\n".join(f"- {t}" for t in recent_titles)
            + "\n위 소식과 같은 사건은 다루지 않는다. 남은 기사 중 다른 사건만 카드로 만들고,"
            " 다룰 만한 새 사건이 없으면 worth_posting을 false로 한다."
        )
    if provider == "gemini":
        text = _call_gemini(user_content, model)
    elif provider == "claude":
        text = _call_claude(user_content, model)
    else:
        raise ValueError(f"알 수 없는 LLM_PROVIDER: {provider} (gemini 또는 claude)")
    data = json.loads(text)

    # 모델이 규칙을 넘겨도 카드/쓰레드 제약은 코드에서 보장한다
    data["cards"] = data["cards"][:6]
    for card in data["cards"]:
        card["source_ids"] = [i for i in card["source_ids"] if 1 <= i <= len(articles)]
    return data
