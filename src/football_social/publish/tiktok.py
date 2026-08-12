"""TikTok publishing via the Content Posting API.

Read this before wiring it up, because it is the part of the plan most
likely to bite:

* Direct Post requires your app to pass TikTok's audit. Until it does,
  everything you publish is forced to SELF_ONLY -- visible to nobody but
  you. The audit takes weeks and usually needs a couple of rounds.
* The audit has a hard UI requirement: before posting, your app must show
  the creator's username and avatar. A headless cron job cannot satisfy that
  on its own, which is why the review queue in queue.py exists and why the
  approval UI surfaces creator_info.
* Until you are audited, use `upload` (inbox) rather than `direct_post`.
  Content lands as a draft in the creator's TikTok inbox and a human taps
  publish. That path needs no audit and is the honest way to run for the
  first few weeks anyway.

So: `mode="inbox"` is the default. Flip to "direct" only after audit.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from ..config import env
from ..models import Post

log = logging.getLogger(__name__)

API = "https://open.tiktokapis.com/v2"
TIMEOUT = 60
CHUNK = 10 * 1024 * 1024  # 10 MB; TikTok's minimum chunk for multi-part


class TikTokError(RuntimeError):
    pass


class TikTokClient:
    def __init__(self, mode: str = "inbox"):
        if mode not in ("inbox", "direct"):
            raise ValueError("mode must be 'inbox' or 'direct'")
        self.mode = mode
        self.client_key = env("TIKTOK_CLIENT_KEY", required=True)
        self.client_secret = env("TIKTOK_CLIENT_SECRET", required=True)
        self.refresh_token = env("TIKTOK_REFRESH_TOKEN", required=True)
        self._token: str | None = None
        self._token_expires: float = 0.0

    # ---- auth -------------------------------------------------------

    @property
    def token(self) -> str:
        """Access tokens last 24h. Refresh lazily, with a safety margin."""
        if self._token and time.time() < self._token_expires - 300:
            return self._token

        resp = requests.post(
            f"{API}/oauth/token/",
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT,
        )
        body = resp.json()
        if "access_token" not in body:
            raise TikTokError(f"token refresh failed: {body}")

        self._token = body["access_token"]
        self._token_expires = time.time() + body.get("expires_in", 86400)

        # TikTok rotates the refresh token. Persisting the new one is on you
        # -- store it back into your secret manager or the next run fails.
        if body.get("refresh_token") and body["refresh_token"] != self.refresh_token:
            log.warning(
                "TikTok issued a new refresh token. Update TIKTOK_REFRESH_TOKEN "
                "or authentication will break within 365 days."
            )
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    # ---- public -----------------------------------------------------

    def creator_info(self) -> dict:
        """Nickname, avatar and posting limits.

        Required by the audit before any post, and worth calling anyway --
        it returns the account's current privacy options.
        """
        resp = requests.post(
            f"{API}/post/publish/creator_info/query/",
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        return _unwrap(resp).get("data", {})

    def publish(self, post: Post) -> str:
        if not post.video_path:
            raise TikTokError("TikTok publishing requires a video file")

        path = Path(post.video_path)
        size = path.stat().st_size

        init = self._init(post, size)
        publish_id = init["publish_id"]

        self._upload(init["upload_url"], path, size)
        log.info("tiktok uploaded, publish_id=%s (mode=%s)", publish_id, self.mode)
        return publish_id

    def status(self, publish_id: str) -> dict:
        resp = requests.post(
            f"{API}/post/publish/status/fetch/",
            headers=self._headers(),
            json={"publish_id": publish_id},
            timeout=TIMEOUT,
        )
        return _unwrap(resp).get("data", {})

    # ---- internals --------------------------------------------------

    def _init(self, post: Post, size: int) -> dict:
        source = {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": min(size, CHUNK),
            "total_chunk_count": max(1, -(-size // CHUNK)),
        }

        if self.mode == "direct":
            endpoint = f"{API}/post/publish/video/init/"
            payload = {
                "post_info": {
                    "title": _title(post),
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "disable_comment": False,
                    "disable_duet": False,
                    "disable_stitch": False,
                },
                "source_info": source,
            }
        else:
            # Inbox upload: no post_info, creator finishes the post in-app.
            endpoint = f"{API}/post/publish/inbox/video/init/"
            payload = {"source_info": source}

        return _unwrap(
            requests.post(endpoint, headers=self._headers(), json=payload,
                          timeout=TIMEOUT)
        ).get("data", {})

    def _upload(self, upload_url: str, path: Path, size: int) -> None:
        """Single PUT for files under the chunk size, which ours always are."""
        with path.open("rb") as fh:
            resp = requests.put(
                upload_url,
                data=fh,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{size - 1}/{size}",
                    "Content-Length": str(size),
                },
                timeout=TIMEOUT * 5,
            )
        if not resp.ok:
            raise TikTokError(f"upload failed HTTP {resp.status_code}: {resp.text[:300]}")


def _title(post: Post) -> str:
    """TikTok captions cap at 2200 chars but read best far shorter."""
    return post.full_caption[:150]


def _unwrap(resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        raise TikTokError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    error = body.get("error", {})
    if error and error.get("code") not in ("ok", None):
        raise TikTokError(
            f"{error.get('code')}: {error.get('message')} "
            f"(log_id={error.get('log_id')})"
        )
    if not resp.ok:
        raise TikTokError(f"HTTP {resp.status_code}: {body}")

    return body
