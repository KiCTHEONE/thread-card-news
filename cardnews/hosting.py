"""Threads가 가져갈 수 있도록 카드 이미지를 공개 URL로 올린다.

Threads API는 공개 URL의 이미지만 받는다. 저장소가 private이면 GitHub raw 주소를
쓸 수 없으므로 기본값으로 무료 임시 호스팅(litterbox, 72시간 보관)에 올린다.
Threads는 게시할 때 이미지를 복사해 가므로 원본이 사라져도 게시물에는 영향이 없다.
"""
import requests

LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"
CATBOX_API = "https://catbox.moe/user/api.php"


def _upload(api, path, extra):
    with open(path, "rb") as f:
        resp = requests.post(api, data={"reqtype": "fileupload", **extra},
                             files={"fileToUpload": f}, timeout=120)
    url = resp.text.strip()
    if not resp.ok or not url.startswith("https://"):
        raise RuntimeError(f"{api} 업로드 실패 ({resp.status_code}): {url[:200]}")
    return url


def upload_image(path):
    try:
        return _upload(LITTERBOX_API, path, {"time": "72h"})
    except Exception as e:
        print(f"[hosting] litterbox 실패, catbox로 재시도: {e}")
        return _upload(CATBOX_API, path, {})
