"""End-to-end run: ingest -> dedupe -> score -> write -> render -> queue.

One slot per invocation. The scheduler calls this four times a day with a
different slot id; breaking news calls it with slot_id=None and a score
floor. Keeping it to one post per invocation means a failure costs one post,
not a day's worth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import load, publish_mode
from .generate import captions, hashtags
from .ingest import dedupe, fixtures, rss, score as scoring
from .models import Post, Story
from .publish import queue as q
from .publish.instagram import InstagramClient, InstagramError
from .publish.tiktok import TikTokClient, TikTokError
from .render import cards, video

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    story: Story | None = None
    post: Post | None = None
    queued: bool = False
    published: dict[str, str] | None = None
    skipped: str = ""

    def __str__(self) -> str:
        if self.skipped:
            return f"skipped: {self.skipped}"
        title = self.story.title[:60] if self.story else "?"
        if self.published:
            return f"published {title} -> {self.published}"
        if self.queued:
            return f"queued for review: {title}"
        return f"rendered (not queued): {title}"


def gather() -> list[Story]:
    """All ingest sources, deduped, scored, newest-relevant first."""
    stories = rss.fetch_all() + fixtures.fetch_results()
    stories = dedupe.collapse(stories)
    stories = dedupe.Ledger().filter_unseen(stories)
    return scoring.score_all(stories)


def run_slot(slot_id: str, *, dry_run: bool = False) -> RunResult:
    """Produce and handle one post for a named slot."""
    slots = {s["id"]: s for s in load("schedule")["slots"]}
    if slot_id not in slots:
        raise KeyError(f"unknown slot {slot_id!r}; have {sorted(slots)}")

    slot = slots[slot_id]
    stories = gather()
    if not stories:
        return RunResult(skipped="no fresh stories from any source")

    story = scoring.pick_for_slot(stories, slot.get("prefers", []))
    if story is None:
        return RunResult(skipped="nothing cleared the score floor")

    return _build_and_handle(story, slot["template"], slot_id, dry_run=dry_run)


def run_breaking() -> RunResult:
    """Fire outside the schedule when something big and confirmed lands."""
    cfg = load("schedule").get("breaking", {})
    if not cfg.get("enabled", False):
        return RunResult(skipped="breaking runs disabled in schedule.yaml")

    stories = gather()
    floor = cfg.get("min_score", 85)
    top = next((s for s in stories if s.score >= floor), None)
    if top is None:
        best = stories[0].score if stories else 0
        return RunResult(skipped=f"top score {best} below breaking floor {floor}")

    return _build_and_handle(top, "transfer_card", "breaking")


def _build_and_handle(
    story: Story, template: str, slot_id: str, *, dry_run: bool = False
) -> RunResult:
    mode = publish_mode()

    copy = captions.write(story)
    # Stash graphic copy on the story so templates can read it.
    story.data.update(copy)

    post = Post(
        story=story,
        template=template,
        caption=copy["caption"],
        hashtags=hashtags.build(story),
        slot_id=slot_id,
    )

    post.image_path = str(cards.render(post, size="story"))
    try:
        post.video_path = str(video.from_card(Path(post.image_path)))
    except (video.FFmpegMissing, RuntimeError) as exc:
        # An image-only post still works on Instagram; TikTok will be skipped.
        log.warning("video render skipped: %s", exc)

    result = RunResult(story=story, post=post)

    if dry_run or not mode.queues:
        log.info("dry run / PUBLISH_MODE=never -- stopping after render")
        return result

    ok, why = q.can_post_now()
    if not ok:
        result.skipped = f"rate limit: {why}"
        return result

    queue = q.Queue()
    queue.add(post, slot_id)
    result.queued = True

    if mode.publishes:
        result.published = publish(post)
        queue.mark_published(story.fingerprint, result.published)
        dedupe.Ledger().record(story)

    return result


def publish(post: Post) -> dict[str, str]:
    """Push to every platform enabled in PLATFORMS.

    One platform failing must not block the other -- each is wrapped
    independently. A platform left out of PLATFORMS (e.g. while TikTok is
    still mid-audit) is skipped outright rather than attempted and logged
    as a failure.
    """
    from .config import platforms as enabled_platforms

    wanted = enabled_platforms()
    results: dict[str, str] = {}

    if "instagram" in wanted:
        try:
            results["instagram"] = InstagramClient().publish(post)
        except (InstagramError, Exception) as exc:
            log.error("instagram publish failed: %s", exc)
            results["instagram_error"] = str(exc)[:200]
    else:
        log.info("instagram skipped (not in PLATFORMS)")

    if "tiktok" in wanted:
        if post.video_path:
            try:
                results["tiktok"] = TikTokClient(mode="inbox").publish(post)
            except (TikTokError, Exception) as exc:
                log.error("tiktok publish failed: %s", exc)
                results["tiktok_error"] = str(exc)[:200]
        else:
            results["tiktok_error"] = "no video rendered (ffmpeg unavailable)"
    else:
        log.info("tiktok skipped (not in PLATFORMS)")

    return results
