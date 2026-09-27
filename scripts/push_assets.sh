#!/usr/bin/env bash
# assets/ 디렉터리(최신 카드 + state.json)를 단일 커밋으로 assets 브랜치에 강제 푸시한다.
# Threads는 게시 시 이미지를 복사해 가므로 이전 카드는 남겨둘 필요가 없고,
# 매번 히스토리를 새로 만들어 저장소 용량이 늘지 않게 한다.
set -euo pipefail
MESSAGE="${1:-update assets}"
BRANCH="${ASSETS_BRANCH:-assets}"
REMOTE_URL="$(git remote get-url origin)"
AUTH_HEADER="$(git config --get http.https://github.com/.extraheader || true)"

cd assets
rm -rf .git
git init -q -b "$BRANCH"
git add -A
git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit -q -m "$MESSAGE"
git -c http.https://github.com/.extraheader="$AUTH_HEADER" push -q -f "$REMOTE_URL" "HEAD:$BRANCH"
rm -rf .git
