"""Instagram Graph API(Instagram 로그인 방식)로 카드뉴스 캐러셀을 올린다.

https://developers.facebook.com/docs/instagram-platform/content-publishing
- 이미지는 공개 URL의 JPEG, 캐러셀은 2~10장, 모든 장의 비율이 같아야 한다 (1080x1350 4:5).
- 캡션은 2,200자, 해시태그는 30개까지. 캡션 속 링크는 눌리지 않으므로 출처는 이름만 적는다.
"""
import time

import requests

API = "https://graph.instagram.com/v21.0"
CAPTION_LIMIT = 2200


class InstagramClient:
    def __init__(self, access_token):
        self.token = access_token
        resp = requests.get(f"{API}/me", params={"fields": "user_id,username", "access_token": access_token},
                            timeout=30)
        if not resp.ok:
            raise RuntimeError(f"Instagram 토큰이 올바르지 않습니다 ({resp.status_code}): {resp.text[:300]}")
        me = resp.json()
        self.user_id = me.get("user_id") or me["id"]
        print(f"[instagram] @{me.get('username')} 계정으로 게시합니다.")

    def _post(self, path, **params):
        for attempt in range(4):
            resp = requests.post(f"{API}/{path}", data={**params, "access_token": self.token}, timeout=60)
            if resp.ok:
                return resp.json()["id"]
            transient = resp.status_code >= 500 or '"is_transient":true' in resp.text
            if not transient or attempt == 3:
                raise RuntimeError(f"Instagram API {path} 실패 ({resp.status_code}): {resp.text}")
            time.sleep(15 * (attempt + 1))

    def _wait_ready(self, container_id, timeout=300):
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = requests.get(f"{API}/{container_id}",
                                params={"fields": "status_code,status", "access_token": self.token}, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            if body.get("status_code") == "FINISHED":
                return
            if body.get("status_code") in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram 컨테이너 {container_id} 처리 실패: {body}")
            time.sleep(5)
        raise TimeoutError(f"Instagram 컨테이너 {container_id}가 {timeout}초 안에 준비되지 않았습니다.")

    def post_carousel(self, image_urls, caption):
        image_urls = image_urls[:10]
        children = [self._post(f"{self.user_id}/media", image_url=url, is_carousel_item="true")
                    for url in image_urls]
        for child in children:
            self._wait_ready(child)
        carousel = self._post(f"{self.user_id}/media", media_type="CAROUSEL",
                              children=",".join(children), caption=caption[:CAPTION_LIMIT])
        self._wait_ready(carousel)
        for attempt in range(4):
            time.sleep(5 * (attempt + 1))
            try:
                return self._post(f"{self.user_id}/media_publish", creation_id=carousel)
            except RuntimeError as e:
                if attempt == 3:
                    raise
                print(f"[instagram] 게시 재시도 ({attempt + 1}/3): {e}")


def compose_caption(text, sources, hashtags):
    """쓰레드 본문 + 출처(이름·제목) + 해시태그."""
    caption = text
    if sources:
        caption += "\n\n출처\n" + "\n".join(f"· {s}" for s in sources)
    tags = " ".join("#" + h.lstrip("#").replace(" ", "") for h in hashtags[:30])
    return f"{caption}\n\n{tags}".strip()
