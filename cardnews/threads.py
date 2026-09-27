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
        # 쓰레드 서버 일시 오류(5xx, is_transient)는 잠시 기다렸다 다시 시도한다
        for attempt in range(4):
            resp = requests.post(f"{API}/{path}", data={**params, "access_token": self.token}, timeout=60)
            if resp.ok:
                return resp.json()["id"]
            transient = resp.status_code >= 500 or '"is_transient":true' in resp.text
            if not transient or attempt == 3:
                raise RuntimeError(f"Threads API {path} 실패 ({resp.status_code}): {resp.text}")
            wait = 15 * (attempt + 1)
            print(f"[threads] 일시 오류({resp.status_code}), {wait}초 후 재시도")
            time.sleep(wait)

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
        # 상태가 FINISHED여도 바로 게시하면 "Media Not Found"(code 24)가 가끔 나서 기다렸다가 재시도한다
        for attempt in range(4):
            time.sleep(10 * (attempt + 1))
            try:
                return self._post(f"{self.user_id}/threads_publish", creation_id=container_id)
            except RuntimeError as e:
                if '"code":24' not in str(e) or attempt == 3:
                    raise
                print(f"[threads] 게시 준비 중, 재시도합니다 ({attempt + 1}/3)")

    def post_carousel(self, image_urls, text, topic_tag=""):
        if not 2 <= len(image_urls) <= 20:
            raise ValueError("캐러셀은 이미지 2~20장이 필요합니다.")
        children = [
            self._post(f"{self.user_id}/threads", media_type="IMAGE", image_url=url, is_carousel_item="true")
            for url in image_urls
        ]
        for child in children:
            self._wait_ready(child)
        params = {"media_type": "CAROUSEL", "children": ",".join(children), "text": truncate(text)}
        if topic_tag:
            # 본문에 해시태그를 넣지 않고 게시물 주제 태그로 붙인다
            try:
                carousel = self._post(f"{self.user_id}/threads", **params, topic_tag=topic_tag)
            except RuntimeError as e:
                print(f"[threads] 주제 태그 없이 다시 시도합니다: {e}")
                carousel = self._post(f"{self.user_id}/threads", **params)
        else:
            carousel = self._post(f"{self.user_id}/threads", **params)
        return self._publish(carousel)

    def reply_text(self, reply_to_id, text):
        container = self._post(
            f"{self.user_id}/threads", media_type="TEXT", text=truncate(text), reply_to_id=reply_to_id
        )
        return self._publish(container)


def truncate(text, limit=TEXT_LIMIT):
    return text if len(text) <= limit else text[: limit - 1] + "…"
