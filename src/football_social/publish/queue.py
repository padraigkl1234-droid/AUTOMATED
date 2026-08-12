"""The review queue and the rate governor.

Two jobs:

1. Hold rendered posts as JSON for a human to approve. This is the default
   path and the reason a bad caption never reaches the account. Approving is
   a one-line CLI call, so it costs seconds a day rather than minutes.
2. Enforce our own posting limits -- daily cap and minimum gap -- which sit
   well inside Instagram's 100/day so we never collide with their throttle.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import load, state_dir
from ..models import Post

log = logging.getLogger(__name__)


class Queue:
    """Review queue rooted at a state directory.

    `root` is the state base, not the queue folder, so a queue and the rate
    governor it feeds always share one directory. Passing a temp path
    therefore isolates *all* of a queue's writes -- otherwise marking a post
    published in a test writes a real entry into the live post history.
    """

    def __init__(self, root: Path | None = None):
        self.root = root or state_dir()
        self.pending = self.root / "queue" / "pending"
        self.done = self.root / "queue" / "published"
        for d in (self.pending, self.done):
            d.mkdir(parents=True, exist_ok=True)

    # ---- queue operations -------------------------------------------

    def add(self, post: Post, slot_id: str = "") -> Path:
        post.slot_id = slot_id
        path = self.pending / f"{post.story.fingerprint}.json"
        path.write_text(json.dumps(_serialise(post), indent=2))
        log.info("queued %s for review", path.name)
        return path

    def list_pending(self) -> list[dict]:
        out = []
        for path in sorted(self.pending.glob("*.json")):
            try:
                out.append({**json.loads(path.read_text()), "_path": str(path)})
            except json.JSONDecodeError:
                log.warning("skipping unreadable queue item %s", path.name)
        return out

    def get(self, fingerprint: str) -> dict | None:
        path = self.pending / f"{fingerprint}.json"
        if not path.exists():
            return None
        return {**json.loads(path.read_text()), "_path": str(path)}

    def mark_published(self, fingerprint: str, results: dict[str, str]) -> None:
        src = self.pending / f"{fingerprint}.json"
        if not src.exists():
            log.warning("nothing pending with fingerprint %s", fingerprint)
            return

        item = json.loads(src.read_text())
        item["published"] = results
        item["published_at"] = datetime.now(timezone.utc).isoformat()

        (self.done / src.name).write_text(json.dumps(item, indent=2))
        src.unlink()
        _record_post_time(self.root)
        log.info("marked %s published: %s", fingerprint, results)

    def reject(self, fingerprint: str, reason: str = "") -> None:
        path = self.pending / f"{fingerprint}.json"
        if path.exists():
            path.unlink()
            log.info("rejected %s%s", fingerprint, f" ({reason})" if reason else "")


# --------------------------------------------------------------------------
# Rate governor
# --------------------------------------------------------------------------

_HISTORY = "post_history.json"


def can_post_now(root: Path | None = None) -> tuple[bool, str]:
    """Check our own limits before spending an API publish."""
    cfg = load("schedule").get("limits", {})
    history = _history(root)
    now = datetime.now(timezone.utc)

    day_ago = now - timedelta(hours=24)
    today = [t for t in history if t > day_ago]

    cap = cfg.get("max_posts_per_day", 8)
    if len(today) >= cap:
        return False, f"daily cap reached ({len(today)}/{cap} in last 24h)"

    gap = cfg.get("min_minutes_between_posts", 45)
    if today:
        since = (now - max(today)).total_seconds() / 60
        if since < gap:
            return False, f"only {since:.0f}m since last post, need {gap}m"

    return True, f"ok ({len(today)}/{cap} used in last 24h)"


def _history(root: Path | None = None) -> list[datetime]:
    path = (root or state_dir()) / _HISTORY
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []

    out = []
    for ts in raw:
        try:
            dt = datetime.fromisoformat(ts)
            out.append(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
        except ValueError:
            continue
    return out


def _record_post_time(root: Path | None = None) -> None:
    base = root or state_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / _HISTORY
    history = _history(base)
    history.append(datetime.now(timezone.utc))

    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    path.write_text(
        json.dumps([t.isoformat() for t in history if t > cutoff], indent=2)
    )


def _serialise(post: Post) -> dict:
    return {
        "fingerprint": post.story.fingerprint,
        "slot_id": post.slot_id,
        "template": post.template,
        "caption": post.caption,
        "full_caption": post.full_caption,
        "hashtags": post.hashtags,
        "image_path": post.image_path,
        "video_path": post.video_path,
        "story": post.story.to_dict(),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
