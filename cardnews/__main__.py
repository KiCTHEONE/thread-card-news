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
from .similar import is_repeat
from .sources import BROADCASTER_DOMAINS, foreign_outlet_name, source_allowed
from .topic import google_news_feeds, load_topic, matches
from .instagram import InstagramClient, compose_caption
from .threads import TEXT_LIMIT, ThreadsClient, truncate
from .token_store import current_token, refresh_if_needed

STATE_FILE = "state.json"
STATE_RETENTION_DAYS = 3
REPEAT_WINDOW_HOURS = 24   # 이 시간 안에 올린 소식과 같은 사건이면 다시 올리지 않는다
REPEAT_THRESHOLD = 0.3     # 제목 유사도 (cardnews/similar.py)


def slot_time(now):
    """실행 시각을 30분 단위로 내림 (예약 실행이 몇 분 늦어도 23:30처럼 표시)."""
    return now.replace(minute=now.minute // 30 * 30, second=0, microsecond=0)


def recent_titles(state):
    """최근 REPEAT_WINDOW_HOURS 동안 올린 기사 제목과 카드 제목."""
    cutoff = time.time() - REPEAT_WINDOW_HOURS * 3600
    titles = [h["title"] for h in state.get("history", []) if h["t"] >= cutoff]
    for p in state.get("posts", []):
        try:
            posted = datetime.fromisoformat(p["created_at"]).timestamp()
        except (KeyError, ValueError):
            continue
        if posted >= cutoff:
            titles += p.get("card_titles", [])
    return list(dict.fromkeys(titles))


def _last_threads_post_time(state):
    for p in reversed(state.get("posts", [])):
        if p.get("id"):
            try:
                return datetime.fromisoformat(p["created_at"]).timestamp()
            except (KeyError, ValueError):
                return 0
    return 0


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
    state["history"] = [h for h in state.get("history", []) if h["t"] >= time.time() - REPEAT_WINDOW_HOURS * 3600]
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, STATE_FILE), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def set_output(name, value):
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    print(f"{name}={value}")


def _split_bullets(text):
    """'•' 항목 목록으로 나눈다. 첫 항목 앞의 문장은 도입문으로 돌려준다."""
    parts = [p.strip() for p in re.split(r"\s*•\s*", text.strip())]
    intro, bullets = parts[0], [p for p in parts[1:] if p]
    return intro, bullets


def compose_text(data, now, topic=None):
    """쓰레드 본문 양식:

    [한카뉴 이슈 브리핑]
    도입 한 줄

    • 항목

    • 항목

    - 한카뉴
    """
    brand = (topic or {}).get("brand", "한카뉴")
    label = topic["label"] if topic else "정치 브리핑"
    header = f"[{brand} {label}]"
    footer = f"- {brand}"
    intro, bullets = _split_bullets(data["thread_text"])

    def build(items):
        body = "\n\n".join(f"• {b}" for b in items)
        return f"{header}\n{intro}\n\n{body}\n\n{footer}" if items else f"{header}\n{intro}\n\n{footer}"

    # 500자를 넘으면 문장 중간에서 자르지 않고 뒤쪽 항목부터 뺀다
    while len(bullets) > 1 and len(build(bullets)) > TEXT_LIMIT:
        bullets = bullets[:-1]
    return truncate(build(bullets))


def topic_tag(data, topic=None):
    return ((topic or {}).get("tag") or data.get("topic_tag", "")).lstrip("#").replace(" ", "")


def compose_reply(data, articles, max_links=4):
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
        with_link = "news.google.com" not in a.link and links < max_links
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
        "topic_tag": topic_tag(data, topic),
        "reply": compose_reply(data, articles),
        "reply_fallbacks": [compose_reply(data, articles, n) for n in (2, 0)],
        # 카드에 실제로 쓴 기사만 '사용함'으로 기록해, 이번에 빠진 기사는 다음 회차에 다시 후보가 된다
        "pending_links": used_links,
        "card_titles": [c["title"] for c in data["cards"]],
        "used_titles": [articles[i - 1].title for i in sorted(used)],
        "instagram_caption": compose_caption(
            compose_text(data, now, topic),
            [f"{articles[i - 1].source} · {articles[i - 1].title}" for i in sorted(used)][:8],
            ((topic or {}).get("instagram") or {}).get("hashtags", [])),
        "instagram_interval_minutes": ((topic or {}).get("instagram") or {}).get("min_interval_minutes", 60),
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
    interval = int((topic or {}).get("post_interval_minutes", 0))
    if interval and not os.environ.get("LOOKBACK_MINUTES_OVERRIDE"):
        last = _last_threads_post_time(state)
        since = (time.time() - last) / 60
        # 예약 실행이 몇 분 밀려도 주기가 유지되도록 5분 여유를 둔다
        if since < interval - 5:
            print(f"[build] 게시 간격 {interval}분: 마지막 게시 {since:.0f}분 전이라 이번엔 건너뜁니다.")
            set_output("post_dir", "")
            return
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
        # 방송사 정책이면 방송사·허용 언론사 도메인에서만 검색한다 (검색 횟수를 줄여 구글 차단을 피함)
        for feed in google_news_feeds(topic["search_queries"], lookback, sites):
            per_feed.append(dedupe(allowed(fetch_articles([feed], lookback, state["seen"], 500)))[:per_query])

        # 해외 언론 영문 기사 (허용된 해외 언론사만, 요약 단계에서 한국어로 옮김)
        foreign = topic.get("foreign", {})
        if foreign.get("enabled"):
            f_limit = int(foreign.get("per_query_limit", 3))
            # 해외 기사는 국내보다 드문드문 나오므로 더 긴 기간에서 찾는다 (이미 쓴 기사는 seen으로 제외)
            f_lookback = max(lookback, int(foreign.get("lookback_minutes", lookback)))
            for feed in google_news_feeds(foreign["queries"], f_lookback, lang="en"):
                kept = []
                for a in fetch_articles([feed], f_lookback, state["seen"], 500):
                    name = foreign_outlet_name(a.source)
                    if name:
                        a.source, a.foreign = name, True
                        kept.append(a)
                per_feed.append(dedupe(kept)[:f_limit])
        searched = [a for group in zip_longest(*per_feed) for a in group if a]
        general = fetch_articles(config.FEEDS, lookback, state["seen"], 500)
        general = allowed([a for a in general if matches(a, topic["keywords"])])[:per_query]
        excluded = topic.get("exclude_keywords", [])
        candidates = dedupe(searched + general)
        # 스포츠·연예 등 정치와 무관한 기사는 AI에 넘기기 전에 뺀다
        articles = [a for a in candidates if not any(k in a.title for k in excluded)]
        for a in candidates:
            if a not in articles:
                print(f"  x 무관한 기사 제외: ({a.source}) {a.title}")
        articles = articles[: int(topic.get("max_articles", config.MAX_ARTICLES))]
        for a in articles:
            print(f"  - ({a.source}) {a.title}")
        min_articles = int(topic.get("min_articles", 2))
    else:
        articles = fetch_articles(config.FEEDS, config.LOOKBACK_MINUTES, state["seen"], config.MAX_ARTICLES)
        min_articles = config.MIN_ARTICLES
    previous = recent_titles(state)
    fresh = [a for a in articles if not is_repeat(a.title, previous, REPEAT_THRESHOLD)]
    for a in articles:
        if a not in fresh:
            print(f"  = 이미 다룬 소식 제외: ({a.source}) {a.title}")
    articles = fresh
    print(f"[build] 새 기사 {len(articles)}건")
    if len(articles) < min_articles:
        print("[build] 기사가 부족해 이번 회차는 건너뜁니다.")
        set_output("post_dir", "")
        return
    data = summarize(articles, config.LLM_PROVIDER, config.LLM_MODEL, now, topic, previous[-40:])
    kept = [c for c in data["cards"] if not is_repeat(c["title"], previous, REPEAT_THRESHOLD)]
    for c in data["cards"]:
        if c not in kept:
            print(f"  = 이미 다룬 소식이라 카드 제외: {c['title']}")
    for c in kept:  # 잘못된 기사 번호가 섞여도 멈추지 않게
        c["source_ids"] = [i for i in c["source_ids"] if 1 <= i <= len(articles)]
    if topic:
        # 정치 우선: 경제 카드는 뒤로 보내고 개수를 제한한다
        econ_max = int(topic.get("max_economy_cards", 2))
        politics = [c for c in kept if c["tag"] != "경제"]
        economy = [c for c in kept if c["tag"] == "경제"][:econ_max]
        kept = politics + economy
    removed = len(data["cards"]) - len(kept)
    data["cards"] = kept
    intro, bullets = _split_bullets(data["thread_text"])
    if removed:
        # 카드를 뺐으면 본문 항목은 남은 카드 본문 첫 문장으로 다시 만든다 (본문과 카드가 어긋나지 않게)
        bullets = [re.split(r"(?<=[.다])\s", c["body"].strip(), maxsplit=1)[0] for c in kept]
    data["thread_text"] = intro + " " + " ".join(f"• {b}" for b in bullets)
    # AI의 worth_posting 판단보다, 중복을 걸러내고 남은 새 카드가 있는지를 기준으로 한다
    # (가벼운 대체 모델이 새 기사가 있어도 false를 내는 경우가 있었다)
    if not data["worth_posting"] and data["cards"]:
        print(f"[build] AI는 건너뛰자고 했지만 새 카드 {len(data['cards'])}장이 있어 게시합니다.")
    if len(data["cards"]) < 1:
        print("[build] 올릴 만한 내용이 없다고 판단해 건너뜁니다.")
        set_output("post_dir", "")
        return
    manifest = build_post(data, articles, now, args.out, topic)
    print(manifest["text"])
    set_output("post_dir", args.out)


def post_reply(client, post_id, manifest):
    """출처 답글. 링크 수 제한에 걸리면 링크를 줄여 다시 시도한다 (본문은 이미 올라갔으므로 실패해도 넘어간다)."""
    texts = [manifest["reply"]] + manifest.get("reply_fallbacks", [])
    for text in texts:
        try:
            client.reply_text(post_id, text)
            return
        except Exception as e:
            print(f"[post] 출처 답글 실패: {e}")
            if "4279111" not in str(e):  # 링크 개수 초과가 아니면 재시도해도 같은 결과
                return


def cmd_post(args):
    with open(os.path.join(args.dir, "post.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    if args.base_url:
        base = args.base_url.rstrip("/")
        urls = [f"{base}/{name}" for name in manifest["images"]]
    else:
        urls = [upload_image(os.path.join(args.dir, name)) for name in manifest["images"]]
    if args.dry_run:
        print(json.dumps({"image_urls": urls, "text": manifest["text"], "topic_tag": manifest.get("topic_tag"),
                          "reply": manifest["reply"]},
                         ensure_ascii=False, indent=1))
        return
    if not config.THREADS_ACCESS_TOKEN:
        sys.exit("THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")

    # 쓰레드와 인스타그램은 서로 독립적으로 올린다 (한쪽이 실패해도 다른 쪽은 올라가게)
    post_id, threads_error = None, None
    try:
        client = ThreadsClient(current_token(args.state_dir, config.THREADS_ACCESS_TOKEN))
        post_id = client.post_carousel(urls, manifest["text"], manifest.get("topic_tag", ""))
        print(f"[post] 쓰레드 게시 완료: {post_id}")
        if manifest["reply"]:
            post_reply(client, post_id, manifest)
    except Exception as e:
        threads_error = e
        print(f"[post] 쓰레드 게시 실패: {e}")

    ig_id = None
    ig_state = load_state(args.state_dir)
    ig_interval = int(manifest.get("instagram_interval_minutes", 60))
    since_last = (time.time() - ig_state.get("last_instagram_at", 0)) / 60
    # 예약 실행이 몇 분씩 밀려도 한 시간 주기가 유지되도록 5분 여유를 둔다
    ig_due = since_last >= ig_interval - 5
    if config.INSTAGRAM_ACCESS_TOKEN and manifest.get("instagram_caption") and not ig_due:
        print(f"[post] 인스타그램은 {ig_interval}분 간격이라 이번엔 건너뜁니다 (마지막 게시 {since_last:.0f}분 전).")
    if config.INSTAGRAM_ACCESS_TOKEN and manifest.get("instagram_caption") and ig_due:
        try:
            ig = InstagramClient(current_token(args.state_dir, config.INSTAGRAM_ACCESS_TOKEN, "instagram"))
            ig_id = ig.post_carousel(urls, manifest["instagram_caption"])
            print(f"[post] 인스타그램 게시 완료: {ig_id}")
        except Exception as e:
            print(f"[post] 인스타그램 게시 실패: {e}")

    if not post_id and not ig_id:
        raise RuntimeError(f"게시 실패: {threads_error}")

    state = load_state(args.state_dir)
    now = time.time()
    state["seen"].update({link: now for link in manifest["pending_links"]})
    state.setdefault("history", []).extend(
        {"t": now, "title": t} for t in manifest.get("used_titles", []) + manifest.get("card_titles", []))
    if ig_id:
        state["last_instagram_at"] = now
    state["posts"].append({"id": post_id, "instagram_id": ig_id, "created_at": manifest["created_at"],
                           "card_titles": manifest.get("card_titles", [])})
    save_state(args.state_dir, state)


def cmd_post_instagram(args):
    """이미 만든 카드(post.json)를 인스타그램에만 올린다 (수동 실행용)."""
    if not config.INSTAGRAM_ACCESS_TOKEN:
        sys.exit("INSTAGRAM_ACCESS_TOKEN 환경변수가 필요합니다.")
    with open(os.path.join(args.dir, "post.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    if not manifest.get("instagram_caption"):
        sys.exit("이 카드에는 인스타그램 캡션이 없습니다 (주제 모드에서 만든 카드만 가능).")
    base = args.base_url.rstrip("/")
    urls = [f"{base}/{name}" for name in manifest["images"]]
    ig = InstagramClient(current_token(args.state_dir, config.INSTAGRAM_ACCESS_TOKEN, "instagram"))
    ig_id = ig.post_carousel(urls, manifest["instagram_caption"])
    print(f"[post] 인스타그램 게시 완료: {ig_id}")
    state = load_state(args.state_dir)
    state["last_instagram_at"] = time.time()
    save_state(args.state_dir, state)


def cmd_refresh_token(args):
    if not config.THREADS_ACCESS_TOKEN:
        sys.exit("THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")
    changed = refresh_if_needed(args.state_dir, config.THREADS_ACCESS_TOKEN, force=args.force)
    if config.INSTAGRAM_ACCESS_TOKEN:
        changed = refresh_if_needed(args.state_dir, config.INSTAGRAM_ACCESS_TOKEN, args.force, "instagram") or changed
    set_output("changed", "true" if changed else "false")


def cmd_reply(args):
    """이미 올라간 게시물에 답글을 단다 (출처 답글이 실패했을 때 수동으로 보완)."""
    if not config.THREADS_ACCESS_TOKEN:
        sys.exit("THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")
    client = ThreadsClient(current_token(args.state_dir, config.THREADS_ACCESS_TOKEN))
    reply_id = client.reply_text(args.post_id, args.text.replace("\\n", "\n"))
    print(f"[reply] 답글 완료: {reply_id}")


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

    pi = sub.add_parser("post-instagram", help="만들어 둔 카드를 인스타그램에만 게시")
    pi.add_argument("--state-dir", default="assets")
    pi.add_argument("--dir", required=True)
    pi.add_argument("--base-url", required=True)
    pi.set_defaults(func=cmd_post_instagram)

    r = sub.add_parser("refresh-token", help="Threads 토큰을 필요할 때 갱신")
    r.add_argument("--state-dir", default="assets")
    r.add_argument("--force", action="store_true")
    r.set_defaults(func=cmd_refresh_token)

    rp = sub.add_parser("reply", help="게시물에 답글 달기")
    rp.add_argument("--state-dir", default="assets")
    rp.add_argument("--post-id", required=True)
    rp.add_argument("--text", required=True)
    rp.set_defaults(func=cmd_reply)

    d = sub.add_parser("demo", help="샘플 데이터로 카드 이미지만 렌더링")
    d.add_argument("--out", default="output/demo")
    d.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
