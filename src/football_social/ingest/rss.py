"""Pull candidate stories from news RSS feeds.

We take headline, summary and link only, then write our own copy. Source
articles are attributed and linked, never reproduced.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser

from ..config import load
from ..models import Kind, Story, Tier

log = logging.getLogger(__name__)

# Words that suggest the headline is speculation even when the outlet is
# otherwise reliable. Demotes the tier by one step.
_HEDGE_MARKERS = (
    "could", "eyeing", "monitoring", "interested", "linked", "considering",
    "weighing", "target", "rumour", "reportedly", "may", "keen on",
)

_CONFIRM_MARKERS = (
    "signs", "signed", "completes", "completed", "confirmed", "announces",
    "unveiled", "official", "joins", "sealed",
)


def fetch_all(limit_per_feed: int = 25) -> list[Story]:
    """Fetch every configured feed. A dead feed is logged, never fatal."""
    cfg = load("sources")
    stories: list[Story] = []

    for feed in cfg.get("feeds", []):
        try:
            stories.extend(_fetch_one(feed, limit_per_feed))
        except Exception as exc:  # a single bad feed must not stop the run
            log.warning("feed %s failed: %s", feed.get("name"), exc)

    log.info("ingested %d stories from %d feeds",
             len(stories), len(cfg.get("feeds", [])))
    return stories


def _fetch_one(feed: dict, limit: int) -> list[Story]:
    parsed = feedparser.parse(feed["url"])
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"unparseable: {parsed.get('bozo_exception')}")

    base_tier = Tier(feed.get("tier", 3))
    out: list[Story] = []

    for entry in parsed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue

        kind = classify(title)
        out.append(
            Story(
                title=title,
                kind=kind,
                tier=adjust_tier(base_tier, title, kind),
                source=feed.get("attribution", feed.get("name", "")),
                url=entry.get("link", ""),
                published_at=_published(entry),
                summary=_clean(entry.get("summary", ""))[:400],
            )
        )
    return out


def classify(title: str) -> Kind:
    """Bucket a headline into a content type.

    Order matters: a confirmed signing is a transfer even though it also
    contains hedge words in the subheadline.
    """
    low = title.lower()
    cfg = load("sources")
    transfer_words = cfg.get("transfer_keywords", [])

    is_transfer = any(w in low for w in transfer_words)
    if is_transfer:
        hedged = any(m in low for m in _HEDGE_MARKERS)
        return Kind.RUMOUR if hedged else Kind.TRANSFER

    # Scorelines: "Arsenal 2-1 Chelsea" or "beat", "draw", "thrash".
    if _looks_like_result(low):
        return Kind.RESULT

    return Kind.FEATURE


def _looks_like_result(low: str) -> bool:
    if any(w in low for w in ("beat", "draw", "thrash", "win over", "held to")):
        return True
    # A digit-dash-digit pattern is the strongest signal we have.
    for i, ch in enumerate(low):
        if ch == "-" and i > 0 and i < len(low) - 1:
            if low[i - 1].isdigit() and low[i + 1].isdigit():
                return True
    return False


def adjust_tier(base: Tier, title: str, kind: Kind) -> Tier:
    """Nudge the source tier using the headline's own certainty."""
    low = title.lower()

    if any(m in low for m in _CONFIRM_MARKERS) and kind is Kind.TRANSFER:
        return base  # outlet tier already reflects how much we trust it

    if any(m in low for m in _HEDGE_MARKERS):
        return Tier(min(3, int(base) + 1))

    return base


def _published(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _clean(html: str) -> str:
    """Strip tags without pulling in a parser dependency."""
    out, depth = [], 0
    for ch in html:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return " ".join("".join(out).split())
