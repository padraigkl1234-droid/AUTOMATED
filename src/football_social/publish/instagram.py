"""Instagram publishing via the Graph API.

Two things about this API surprise people, so they are handled explicitly:

1. It does not accept file uploads. You give it a publicly reachable URL and
   Instagram fetches the media itself. MEDIA_BASE_URL must point at a host
   that serves your out/ directory.
2. Publishing is two calls -- create a container, then publish it -- and for
   video the container needs time to transcode. We poll status_code rather
   than sleeping a fixed amount, because a six-second Reel and a sixty-second
   one are not the same wait.

Account must be Business or Creator and linked to a Facebook Page.
"""

from __future__ import annotations

import logging
import time

import requests

from ..config import env
from ..models import Post

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"
TIMEOUT = 30
POLL_INTERVAL = 5
POLL_MAX = 60  # 5 minutes


class InstagramError(RuntimeError):
    pass


class InstagramClient:
    def __init__(self, user_id: str | None = None, token: str | None = None):
        self.user_id = user_id or env("IG_USER_ID", required=True)
        self.token = token or env("IG_ACCESS_TOKEN", required=True)

    # ---- public -----------------------------------------------------

    def publish(self, post: Post) -> str:
        """Publish a Reel if we have video, otherwise a feed image."""
        if post.video_path:
            container = self._create_reel(post)
        elif post.image_path:
            container = self._create_image(post)
        else:
            raise InstagramError("post has no media to publish")

        self._await_ready(container)
        media_id = self._publish(container)
        log.info("instagram published %s", media_id)
        return media_id

    def remaining_quota(self) -> int:
        """Publishes left in the rolling 24h window (limit is 100)."""
        data = self._get(
            f"{GRAPH}/{self.user_id}/content_publishing_limit",
            {"fields": "quota_usage,config"},
        )
        entries = data.get("data") or [{}]
        used = entries[0].get("quota_usage", 0)
        cap = entries[0].get("config", {}).get("quota_total", 100)
        return max(0, cap - used)

    # ---- containers -------------------------------------------------

    def _create_reel(self, post: Post) -> str:
        data = self._post(
            f"{GRAPH}/{self.user_id}/media",
            {
                "media_type": "REELS",
                "video_url": _public_url(post.video_path),
                "caption": post.full_caption,
                "share_to_feed": "true",
            },
        )
        return data["id"]

    def _create_image(self, post: Post) -> str:
        data = self._post(
            f"{GRAPH}/{self.user_id}/media",
            {
                "image_url": _public_url(post.image_path),
                "caption": post.full_caption,
            },
        )
        return data["id"]

    def _await_ready(self, container_id: str) -> None:
        """Poll until the container finishes transcoding."""
        for attempt in range(POLL_MAX):
            data = self._get(
                f"{GRAPH}/{container_id}", {"fields": "status_code,status"}
            )
            status = data.get("status_code")

            if status == "FINISHED":
                return
            if status == "ERROR":
                raise InstagramError(
                    f"container failed: {data.get('status', 'no detail')}"
                )

            log.debug("container %s: %s (%d)", container_id, status, attempt)
            time.sleep(POLL_INTERVAL)

        raise InstagramError(
            f"container {container_id} not ready after "
            f"{POLL_INTERVAL * POLL_MAX}s"
        )

    def _publish(self, container_id: str) -> str:
        data = self._post(
            f"{GRAPH}/{self.user_id}/media_publish", {"creation_id": container_id}
        )
        return data["id"]

    # ---- transport --------------------------------------------------

    def _post(self, url: str, params: dict) -> dict:
        resp = requests.post(
            url, params={**params, "access_token": self.token}, timeout=TIMEOUT
        )
        return _unwrap(resp)

    def _get(self, url: str, params: dict) -> dict:
        resp = requests.get(
            url, params={**params, "access_token": self.token}, timeout=TIMEOUT
        )
        return _unwrap(resp)


def _unwrap(resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        raise InstagramError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    if "error" in body:
        err = body["error"]
        raise InstagramError(
            f"{err.get('type')} {err.get('code')}: {err.get('message')}"
        )
    if not resp.ok:
        raise InstagramError(f"HTTP {resp.status_code}: {body}")

    return body


def _public_url(local_path: str) -> str:
    base = env("MEDIA_BASE_URL", required=True).rstrip("/")
    from pathlib import Path

    return f"{base}/{Path(local_path).name}"
