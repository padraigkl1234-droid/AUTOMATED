"""Core data types passed between pipeline stages.

A Story is something that happened. A Post is a decision to publish something
about it, in a specific format, to specific platforms. Keeping them separate
means one story can become a feed card now and a Reel later without the
dedupe layer losing track of it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Kind(str, Enum):
    TRANSFER = "transfer"
    RUMOUR = "rumour"
    RESULT = "result"
    FEATURE = "feature"


class Tier(int, Enum):
    """Source reliability. Drives the language the caption may use."""

    CONFIRMED = 1
    STRONG = 2
    SPECULATIVE = 3


# The single place that decides how certain we are allowed to sound.
TIER_LANGUAGE: dict[Tier, str] = {
    Tier.CONFIRMED: (
        "This is confirmed. You may state it as fact: 'signs', 'completed', "
        "'confirmed'. You may use the word BREAKING."
    ),
    Tier.STRONG: (
        "This is strong reporting but not official. Hedge: 'set to', "
        "'agreement reached', 'expected to'. Do not say confirmed or signed."
    ),
    Tier.SPECULATIVE: (
        "This is speculation. Hedge hard and attribute: 'linked with', "
        "'reported interest', 'according to <source>'. Never imply a done deal."
    ),
}


@dataclass
class Story:
    """A candidate for publication, normalised across all ingest sources."""

    title: str
    kind: Kind
    tier: Tier
    source: str
    url: str
    published_at: datetime
    summary: str = ""
    # Structured extras. Results carry scores; transfers carry player/clubs.
    data: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    @property
    def fingerprint(self) -> str:
        """Stable id for dedupe and for the 'already posted' ledger.

        Built from normalised title words rather than the URL, because the
        same story arrives from four outlets with four URLs.
        """
        words = sorted(
            w for w in _normalise(self.title).split() if len(w) > 3
        )
        basis = f"{self.kind.value}:{' '.join(words[:8])}"
        return hashlib.sha256(basis.encode()).hexdigest()[:16]

    @property
    def age_hours(self) -> float:
        now = datetime.now(timezone.utc)
        published = self.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return max(0.0, (now - published).total_seconds() / 3600)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["tier"] = int(self.tier)
        d["published_at"] = self.published_at.isoformat()
        d["fingerprint"] = self.fingerprint
        return d


@dataclass
class Post:
    """A rendered, captioned unit ready for one or more platforms."""

    story: Story
    template: str
    caption: str
    hashtags: list[str]
    # Absolute paths on disk, produced by the render stage.
    image_path: str | None = None
    video_path: str | None = None
    # Populated by publishers: {"instagram": "<media_id>", "tiktok": "<id>"}
    published: dict[str, str] = field(default_factory=dict)
    slot_id: str = ""

    @property
    def full_caption(self) -> str:
        tags = " ".join(self.hashtags)
        credit = f"\n\n📰 {self.story.source}"
        return f"{self.caption}{credit}\n\n{tags}".strip()


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() or ch.isspace() else " ")
    return " ".join("".join(out).split())
