# thread-card-news

매시간 한국 정치 기사를 모아 **카드뉴스 이미지 + 요약 본문**으로 정리하고 Threads에 자동으로 올립니다.

```
RSS 수집 (최근 90분, 이미 쓴 기사 제외)
  → AI(기본 Gemini, 선택 Claude)로 이슈별 종합 요약 (JSON)
  → 카드 이미지 생성 (표지 1장 + 이슈 3~6장, 1080x1350)
  → Threads 캐러셀 게시 + 출처 링크 답글
```

GitHub Actions(`.github/workflows/hourly.yml`)가 매시 7분에 실행합니다.

## 설정

### 1. Threads API 토큰 발급
1. [Meta for Developers](https://developers.facebook.com/)에서 앱을 만들고 **Threads API** 사용 사례를 추가합니다.
2. 권한 `threads_basic`, `threads_content_publish`를 요청하고, 올릴 계정을 테스터로 추가합니다.
3. 액세스 토큰을 발급받아 **장기 토큰(60일)** 으로 교환합니다.
4. `GET https://graph.threads.net/v1.0/me?fields=id&access_token=...` 으로 사용자 ID를 확인합니다.

> 장기 토큰은 60일 뒤 만료됩니다. 만료 전에
> `GET https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=<토큰>`
> 으로 갱신하고 Secret을 업데이트하세요.

### 2. AI API 키 발급
- **Gemini (기본, 무료 등급)**: https://aistudio.google.com 에 구글 계정으로 로그인 → **Get API key** → 키 생성
- **Claude (선택, 유료)**: https://platform.claude.com → Billing에서 크레딧 충전 → API Keys에서 키 생성

### 3. GitHub 저장소 설정
**Settings → Secrets and variables → Actions**

| 종류 | 이름 | 설명 |
|---|---|---|
| Secret | `GEMINI_API_KEY` | Gemini API 키 (기본) |
| Secret | `ANTHROPIC_API_KEY` | Claude API 키 (`LLM_PROVIDER=claude`일 때만) |
| Secret | `THREADS_USER_ID` | Threads 사용자 ID |
| Secret | `THREADS_ACCESS_TOKEN` | Threads 장기 액세스 토큰 |
| Variable (선택) | `ACCOUNT_HANDLE` | 카드 하단에 표시할 계정명 (예: `@my_politics`) |
| Variable (선택) | `LLM_PROVIDER` | `gemini`(기본) 또는 `claude` |
| Variable (선택) | `GEMINI_MODEL` | 기본값 `gemini-flash-latest` |
| Variable (선택) | `CLAUDE_MODEL` | 기본값 `claude-opus-5` |
| Variable (선택) | `IMAGE_BASE_URL` | 이미지를 다른 곳에 올릴 때의 공개 URL |

### 4. 이미지 호스팅
Threads API는 이미지를 **공개 URL**로만 받습니다. 기본 설정은 카드 이미지를 `assets` 브랜치에 올리고
`raw.githubusercontent.com` 주소를 넘기므로 **저장소가 public이어야 합니다.**
`assets` 브랜치는 매번 커밋 하나로 강제 푸시되어(최신 카드 + `state.json`만 보관) 저장소 용량이 늘지 않습니다.
저장소를 private로 두려면 이미지를 S3/Cloudflare R2 등에 올리고 `IMAGE_BASE_URL`을 지정하세요.

### 5. 테스트
Actions 탭 → **Hourly politics card news** → *Run workflow* 에서 `dry_run`을 켜고 실행하면
게시 없이 카드만 만들어 Artifacts(`cards`)로 받아볼 수 있습니다.

## 로컬 실행

```bash
pip install -r requirements.txt
sudo apt-get install fonts-noto-cjk   # 한글 폰트 (또는 CARD_FONT_PATH 지정)

python -m cardnews demo --out output/demo                 # API 없이 카드 디자인 확인
python -m cardnews build --state-dir assets --out output/run   # 수집 + 요약 + 렌더링
python -m cardnews post --state-dir assets --dir output/run --base-url https://... --dry-run
```

## 커스터마이징
- **뉴스 소스**: `cardnews/config.py`의 `DEFAULT_FEEDS` 또는 `FEEDS` 환경변수(쉼표 구분)
- **요약 톤·분량**: `cardnews/summarize.py`의 `SYSTEM_PROMPT`
- **카드 디자인**: `cardnews/render.py`의 색상 상수와 `render_cover` / `render_card`
- **수집 범위**: `LOOKBACK_MINUTES`(기본 90), `MIN_ARTICLES`(기본 3, 이보다 적으면 건너뜀)

## 참고
- 요약은 중립·사실 위주로 쓰도록 지시하고, 기사를 베끼지 않고 재서술하며 출처 링크를 답글로 남깁니다.
  정치 콘텐츠 특성상 초기에는 dry run으로 결과를 확인한 뒤 자동 게시를 켜는 것을 권장합니다.
- Gemini 무료 등급은 한도 초과(429)·과부하(503) 시 최대 3번 재시도하고, 그래도 실패하면 그 회차는 실패로 남습니다.
  무료 등급에서는 입력 내용이 구글 서비스 개선에 쓰일 수 있습니다(공개 기사만 보냅니다).
- Claude를 쓰는 경우 요청이 거절되면 `fallbacks: "default"`(서버 측 폴백)로 다른 모델이 이어받습니다.
- Threads API 게시 한도는 24시간 250건이며, 이 워크플로는 하루 최대 48건(본문+답글)을 사용합니다.
