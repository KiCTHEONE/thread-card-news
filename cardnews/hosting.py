"""Threads가 가져갈 수 있도록 카드 이미지를 공개 URL로 올린다.

Threads API는 공개 URL의 이미지만 받는다. IMGBB_API_KEY가 있으면 ImgBB(무료)에 올리고,
없으면 워크플로가 public 저장소의 assets 브랜치 raw URL을 --base-url로 넘긴다.
Threads는 게시할 때 이미지를 복사해 가므로 원본이 사라져도 게시물에는 영향이 없다.
"""
import base64
import os

import requests

IMGBB_API = "https://api.imgbb.com/1/upload"
IMGBB_EXPIRATION = 60 * 60 * 24 * 3  # 3일 뒤 자동 삭제


def upload_image(path):
    key = os.environ.get("IMGBB_API_KEY")
    if not key:
        raise RuntimeError("이미지를 올릴 곳이 없습니다. IMGBB_API_KEY를 설정하거나 저장소를 public으로 바꾸세요.")
    with open(path, "rb") as f:
        image = base64.b64encode(f.read()).decode()
    resp = requests.post(IMGBB_API, params={"key": key, "expiration": IMGBB_EXPIRATION},
                         data={"image": image}, timeout=120)
    if not resp.ok:
        raise RuntimeError(f"ImgBB 업로드 실패 ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["data"]["url"]
