"""매시간 정치 뉴스 카드뉴스를 만들고 Threads에 올린다.

  python -m cardnews build --state-dir assets --out assets/cards/20260927-14
  python -m cardnews post  --state-dir assets --dir assets/cards/20260927-14 --base-url https://...
  python -m cardnews demo  --out output/demo     # API 호출 없이 샘플 카드 렌더링
"""
import argparse
import json
import os
import re
from itertools import zip_longest
import sys
import time
from datetime import datetime

from . import config
from .fetch import Article, dedupe, fetch_articles, resolve_google_links
from .hosting import upload_image
from .render import render_all
from .summarize import KST, summarize
from .sources import BROADCASTER_DOMAINS, source_allowed
from .topic import google_news_feeds, load_topic, matches
from .threads import TEXT_LIMIT, ThreadsClient, truncate
from .token_store import current_token, refresh_if_needed

STATE_FILE = "state.json"
STATE_RETENTION_DAYS = 3


def slot_time(now):
    """실행 시각을 30분 단위로 내림 (예약 실행이 몇 분 늦어도 23:30처럼 표시)."""
    return now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0)


def load_state(state_dir):
    path = os.path.join(state_dir, STATE_FILE)
    if not os.path.exists(path):
        return {"seen": {}, "posts": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(state_dir, state):
    cutoff = time.time() - STATE_RETENTION_DAYS * 86400
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    state["posts"] = state["posts"][-200:]
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, STATE_FILE), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def set_output(name, value):
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    print(f"{name}={value}")


def _format_bullets(text):
    # 모델이 항목을 한 줄에 이어 쓰는 경우가 있어 '•' 앞에서 줄을 바꾼다
    text = re.sub(r"\s*•\s*", "\n• ", text.strip())
    return re.sub(r"\n{2,}", "\n", text).strip()


def compose_text(data, now, topic=None):
    label = topic["label"] if topic else "정치 브리핑"
    header = f"[{now:%m.%d} {slot_time(now):%H:%M} {label}]"
    tag_name = topic["tag"] if topic else data["topic_tag"]
    tag = "#" + tag_name.lstrip("#").replace(" ", "")
    body_limit = TEXT_LIMIT - len(header) - len(tag) - 4
    return f"{header}\n{truncate(_format_bullets(data['thread_text']), body_limit)}\n\n{tag}"


def compose_reply(data, articles):
    ids = []
    for card in data["cards"]:
        for i in card["source_ids"]:
            if i not in ids:
                ids.append(i)
    text = "출처"
    links = 0
    count = 0
    for i in ids:
        a = articles[i - 1]
        # 원문 주소로 바꾸지 못한 구글 뉴스 링크는 수백 자짜리 리디렉트 주소라 제목만 적는다
        # Threads는 게시물당 링크 5개, 500자 제한
        with_link = "news.google.com" not in a.link and links < 5
        title = a.title if len(a.title) <= 30 else a.title[:29] + "…"
        item = f"\n\n{a.source} · {title}" + (f"\n{a.link}" if with_link else "")
        if len(text) + len(item) > TEXT_LIMIT:
            continue
        text += item
        count += 1
        links += with_link
    return text if count else ""


def build_post(data, articles, now, out_dir, topic=None):
    used = {i for card in data["cards"] for i in card["source_ids"]}
    # 중복 판정은 수집 당시 주소(구글 뉴스 주소)로 하므로 원문 주소로 바꾸기 전에 적어 둔다
    used_links = [articles[i - 1].link for i in sorted(used)]
    resolve_google_links([articles[i - 1] for i in sorted(used)])
    label = topic["label"] if topic else "정치 브리핑"
    images = render_all(data, articles, now, out_dir, config.ACCOUNT_HANDLE, config.FONT_PATH, label)
    manifest = {
        "created_at": now.isoformat(),
        "images": [os.path.basename(p) for p in images],
        "text": compose_text(data, now, topic),
        "reply": compose_reply(data, articles),
        # 카드에 실제로 쓴 기사만 '사용함'으로 기록해, 이번에 빠진 기사는 다음 회차에 다시 후보가 된다
        "pending_links": used_links,
        "card_titles": [c["title"] for c in data["cards"]],
        "summary": data,
    }
    with open(os.path.join(out_dir, "post.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return manifest


def cmd_build(args):
    key_name = "GEMINI_API_KEY" if config.LLM_PROVIDER == "gemini" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_name):
        sys.exit(f"{key_name} 가 설정되지 않았습니다. GitHub Settings → Secrets and variables → Actions 에 추가하세요.")
    now = datetime.now(KST)
    state = load_state(args.state_dir)
    if os.environ.get("IGNORE_SEEN") == "true":
        print("[build] 테스트: 이미 올린 기사 기록을 무시합니다.")
        state["seen"] = {}
    topic = load_topic()
    if topic:
        # 수동 실행에서 LOOKBACK_MINUTES를 따로 주지 않으면 주제 설정값을 쓴다
        lookback = int(os.environ.get("LOOKBACK_MINUTES_OVERRIDE") or topic.get("lookback_minutes", 1440))
        print(f"[build] 주제 모드: {topic['label']} (최근 {lookback}분)")
        # 주제 검색 결과는 출처만 거르고(무관한 기사는 AI가 걸러냄), 일반 정치 피드는 키워드로도 거른다
        # 검색어마다 따로 모아 개수를 제한해야 기사가 많은 주제(예: 특검)가 다른 주제를 밀어내지 않는다
        per_query = int(topic.get("per_query_limit", 8))
        policy = topic.get("source_policy", "all")
        extra = topic.get("extra_sources", [])

        def allowed(items):
            kept = [a for a in items if source_allowed(a.source, policy, extra)]
            for a in items:
                if a not in kept:
                    print(f"  x 출처 제외: ({a.source}) {a.title}")
            return kept

        per_feed = []
        sites = BROADCASTER_DOMAINS + topic.get("extra_domains", []) if policy == "broadcast" else ()
        # 방송사 도메인 검색과 일반 검색(지역 방송사 등 도메인 목록 밖 방송사용)을 함께 쓴다
        for site_feed, plain_feed in zip(google_news_feeds(topic["search_queries"], lookback, sites),
                                         google_news_feeds(topic["search_queries"], lookback)):
            feeds = [site_feed, plain_feed] if sites else [plain_feed]
            per_feed.append(dedupe(allowed(fetch_articles(feeds, lookback, state["seen"], 500)))[:per_query])
        # 검색어별 결과를 번갈아 섞어야 기사 수 상한에서 뒤쪽 주제(예: 정당)가 잘려 나가지 않는다
        searched = [a for group in zip_longest(*per_feed) for a in group if a]
        general = fetch_articles(config.FEEDS, lookback, state["seen"], 500)
        general = allowed([a for a in general if matches(a, topic["keywords"])])[:per_query]
        articles = dedupe(searched + general)[: int(topic.get("max_articles", config.MAX_ARTICLES))]
        for a in articles:
            print(f"  - ({a.source}) {a.title}")
        min_articles = int(topic.get("min_articles", 2))
    else:
        articles = fetch_articles(config.FEEDS, config.LOOKBACK_MINUTES, state["seen"], config.MAX_ARTICLES)
        min_articles = config.MIN_ARTICLES
    print(f"[build] 새 기사 {len(articles)}건")
    if len(articles) < min_articles:
        print("[build] 기사가 부족해 이번 회차는 건너뜁니다.")
        set_output("post_dir", "")
        return
    recent = [t for p in state["posts"][-6:] for t in p.get("card_titles", [])]
    data = summarize(articles, config.LLM_PROVIDER, config.LLM_MODEL, now, topic, recent)
    if not data["worth_posting"] or len(data["cards"]) < 1:
        print("[build] 올릴 만한 내용이 없다고 판단해 건너뜁니다.")
        set_output("post_dir", "")
        return
    manifest = build_post(data, articles, now, args.out, topic)
    print(manifest["text"])
    set_output("post_dir", args.out)


def cmd_post(args):
    with open(os.path.join(args.dir, "post.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    if args.base_url:
        base = args.base_url.rstrip("/")
        urls = [f"{base}/{name}" for name in manifest["images"]]
    else:
        urls = [upload_image(os.path.join(args.dir, name)) for name in manifest["images"]]
    if args.dry_run:
        print(json.dumps({"image_urls": urls, "text": manifest["text"], "reply": manifest["reply"]},
                         ensure_ascii=False, indent=1))
        return
    if not config.THREADS_ACCESS_TOKEN:
        sys.exit("THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")

    client = ThreadsClient(current_token(args.state_dir, config.THREADS_ACCESS_TOKEN))
    post_id = client.post_carousel(urls, manifest["text"])
    print(f"[post] 게시 완료: {post_id}")
    if manifest["reply"]:
        try:
            client.reply_text(post_id, manifest["reply"])
        except Exception as e:  # 본문은 이미 올라갔으므로 답글 실패로 전체를 실패 처리하지 않는다
            print(f"[post] 출처 답글 실패: {e}")

    state = load_state(args.state_dir)
    now = time.time()
    state["seen"].update({link: now for link in manifest["pending_links"]})
    state["posts"].append({"id": post_id, "created_at": manifest["created_at"],
                           "card_titles": manifest.get("card_titles", [])})
    save_state(args.state_dir, state)


def cmd_refresh_token(args):
    if not config.THREADS_ACCESS_TOKEN:
        sys.exit("THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")
    changed = refresh_if_needed(args.state_dir, config.THREADS_ACCESS_TOKEN, force=args.force)
    set_output("changed", "true" if changed else "false")


def cmd_demo(args):
    now = datetime.now(KST)
    t = time.time()
    articles = [
        Article("여야, 내년도 예산안 심사 일정 합의", "", "https://example.com/1", "연합뉴스", t),
        Article("대통령실, 국정과제 점검회의 개최", "", "https://example.com/2", "한겨레", t),
        Article("국회 법사위, 개정안 두고 공방", "", "https://example.com/3", "경향신문", t),
        Article("외교부, 한미 고위급 협의 결과 발표", "", "https://example.com/4", "동아일보", t),
    ]
    data = {
        "worth_posting": True,
        "headline": "예산 심사 본격화, 법사위는 대치 계속",
        "topic_tag": "정치뉴스",
        "thread_text": "이번 시간 정치권은 예산안 심사 일정 합의와 법사위 공방이 이어졌다.\n"
                       "• 여야, 예산안 심사 일정 합의\n• 대통령실 국정과제 점검\n• 법사위 개정안 공방\n• 한미 고위급 협의",
        "cards": [
            {"tag": "국회", "title": "여야, 예산안 심사 일정 합의",
             "body": "여야 원내대표가 내년도 예산안 심사 일정에 합의했다. 상임위 예비심사를 다음 주까지 마치고 예결위 종합심사에 들어간다.",
             "source_ids": [1]},
            {"tag": "대통령실", "title": "국정과제 점검회의 개최",
             "body": "대통령실이 주요 국정과제 추진 상황을 점검하는 회의를 열었다. 부처별 이행 현황과 후속 과제를 논의했다.",
             "source_ids": [2]},
            {"tag": "사법", "title": "법사위, 개정안 두고 여야 공방",
             "body": "법제사법위원회에서 개정안 처리를 두고 여야가 맞섰다. 여당은 신속 처리를, 야당은 추가 논의를 주장했다.",
             "source_ids": [3, 1]},
            {"tag": "외교안보", "title": "한미 고위급 협의 결과 발표",
             "body": "외교부가 한미 고위급 협의 결과를 발표했다. 양측은 공급망과 안보 협력 방안을 논의했다고 밝혔다.",
             "source_ids": [4]},
        ],
    }
    manifest = build_post(data, articles, now, args.out)
    print(manifest["text"], "\n---\n", manifest["reply"], sep="")
    print(f"[demo] {args.out} 에 {len(manifest['images'])}장 생성")


def main():
    parser = argparse.ArgumentParser(prog="cardnews")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="기사 수집 → 요약 → 카드 이미지 생성")
    b.add_argument("--state-dir", default="assets")
    b.add_argument("--out", required=True)
    b.set_defaults(func=cmd_build)

    p = sub.add_parser("post", help="생성된 카드를 Threads에 게시")
    p.add_argument("--state-dir", default="assets")
    p.add_argument("--dir", required=True)
    p.add_argument("--base-url", default="", help="이미지가 공개된 URL 경로. 비우면 무료 이미지 호스팅에 업로드")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_post)

    r = sub.add_parser("refresh-token", help="Threads 토큰을 필요할 때 갱신")
    r.add_argument("--state-dir", default="assets")
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_refresh_token)

    d = sub.add_parser("demo", help="샘플 데이터로 카드 이미지만 렌더링")
    d.add_argument("--out", default="output/demo")
    d.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
