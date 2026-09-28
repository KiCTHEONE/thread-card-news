"""Threads·Instagram 액세스 토큰 자동 갱신.

GitHub Actions는 Secret을 스스로 고칠 수 없으므로, 갱신한 토큰은 암호화해서 assets 브랜치의
token.json에 보관한다. 암호화 키는 처음 등록한 THREADS_ACCESS_TOKEN Secret 문자열에서 만든다.
Secret을 새 토큰으로 바꾸면 이전 보관본은 풀리지 않으므로 자연스럽게 새 토큰부터 다시 시작한다.
"""
import base64
import hashlib
import json
import os
import time

import requests
from cryptography.fernet import Fernet, InvalidToken

# 플랫폼별 (보관 파일, 갱신 주소, grant_type). 두 플랫폼 모두 장기 토큰 수명은 60일이다.
PLATFORMS = {
    "threads": ("token.json", "https://graph.threads.net/refresh_access_token", "th_refresh_token"),
    "instagram": ("token_instagram.json", "https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
}
REFRESH_EVERY_DAYS = 7  # 넉넉하게 일주일마다 갱신


def _fernet(secret_token):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_token.encode()).digest()))


def _load(state_dir, secret_token, platform="threads"):
    path = os.path.join(state_dir, PLATFORMS[platform][0])
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    try:
        stored["token"] = _fernet(secret_token).decrypt(stored["encrypted"].encode()).decode()
    except (InvalidToken, KeyError):
        print("[token] 보관된 토큰을 풀 수 없어 Secret 토큰을 사용합니다 (Secret이 바뀐 경우 정상).")
        return None
    return stored


def current_token(state_dir, secret_token, platform="threads"):
    stored = _load(state_dir, secret_token, platform)
    return stored["token"] if stored else secret_token


def refresh_if_needed(state_dir, secret_token, force=False, platform="threads"):
    """필요하면 토큰을 갱신하고, 새로 저장했으면 True를 돌려준다."""
    token_file, refresh_url, grant_type = PLATFORMS[platform]
    stored = _load(state_dir, secret_token, platform)
    if stored and not force and time.time() - stored["refreshed_at"] < REFRESH_EVERY_DAYS * 86400:
        days = (time.time() - stored["refreshed_at"]) / 86400
        print(f"[token:{platform}] {days:.1f}일 전에 갱신됨, 이번엔 건너뜁니다.")
        return False

    token = stored["token"] if stored else secret_token
    resp = requests.get(refresh_url, params={"grant_type": grant_type, "access_token": token}, timeout=30)
    if not resp.ok:
        # 발급 24시간 이내 토큰은 갱신이 안 되는 등 일시적인 이유가 많아 실패해도 게시는 계속한다
        print(f"[token:{platform}] 갱신 실패 ({resp.status_code}): {resp.text[:300]}")
        return False
    body = resp.json()
    new_token = body["access_token"]
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, token_file), "w", encoding="utf-8") as f:
        json.dump({
            "encrypted": _fernet(secret_token).encrypt(new_token.encode()).decode(),
            "refreshed_at": time.time(),
            "expires_in": body.get("expires_in"),
        }, f)
    print(f"[token:{platform}] 갱신 완료, {int(body.get('expires_in', 0)) // 86400}일 유효")
    return True
