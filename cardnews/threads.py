"""Threads Graph API로 카드뉴스(캐러셀)와 출처 답글을 올린다.

https://developers.facebook.com/docs/threads/posts
"""
import time

import requests

API = "https://graph.threads.net/v1.0"
TEXT_LIMIT = 500


class ThreadsClient:
    def __init__(self, access_token):
        self.token = access_token
        # 사용자 ID는 토큰에서 직접 조회한다 (앱 ID를 잘못 넣는 실수 방지)
        resp = requests.get(f"{API}/me", params={"fields": "id,username", "access_token": access_token}, timeout=30)
        if not resp.ok:
            raise RuntimeError(
                "Threads 토큰이 올바르지 않습니다. 앱 시크릿이 아니라 User Token Generator에서 "
                f"발급한 액세스 토큰을 THREADS_ACCESS_TOKEN에 넣으세요. ({resp.status_code}): {resp.text[:300]}"
            )
        me = resp.json()
        self.user_id = me["id"]
        print(f"[threads] @{me.get('username')} 계정으로 게시합니다.")

    def _post(self, path, **params):
        resp = requests.post(f"{API}/{path}", data={**params, "access_token": self.token}, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"Threads API {path} 실패 ({resp.status_code}): {resp.text}")
        return resp.json()["id"]

    def _wait_ready(self, container_id, timeout=300):
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = requests.get(
                f"{API}/{container_id}",
                params={"fields": "status,error_message", "access_token": self.token},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") == "FINISHED":
                return
            if body.get("status") in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"컨테이너 {container_id} 처리 실패: {body}")
            time.sleep(5)
        raise TimeoutError(f"컨테이너 {container_id}가 {timeout}초 안에 준비되지 않았습니다.")

    def _publish(self, container_id):
        self._wait_ready(container_id)
        return self._post(f"{self.user_id}/threads_publish", creation_id=container_id)

    def post_carousel(self, image_urls, text):
        if not 2 <= len(image_urls) <= 20:
            raise ValueError("캐러셀은 이미지 2~20장이 필요합니다.")
        children = [
            self._post(f"{self.user_id}/threads", media_type="IMAGE", image_url=url, is_carousel_item="true")
            for url in image_urls
        ]
        for child in children:
            self._wait_ready(child)
        carousel = self._post(
            f"{self.user_id}/threads",
            media_type="CAROUSEL",
            children=",".join(children),
            text=truncate(text),
        )
        return self._publish(carousel)

    def reply_text(self, reply_to_id, text):
        container = self._post(
            f"{self.user_id}/threads", media_type="TEXT", text=truncate(text), reply_to_id=reply_to_id
        )
        return self._publish(container)


def truncate(text, limit=TEXT_LIMIT):
    return text if len(text) <= limit else text[: limit - 1] + "…"
