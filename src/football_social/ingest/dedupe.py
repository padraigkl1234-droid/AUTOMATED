"""Collapse the same story arriving from several outlets, and remember what
we have already published.

Four outlets covering one signing is four Story objects with four headlines.
Posting all four is the fastest way to look like a bot, so near-duplicate
titles are merged and the highest-tier source wins.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rapidfuzz import fuzz

from ..config import state_dir
from ..models import Story

log = logging.getLogger(__name__)

# Two headlines above this token-set similarity are treated as one story.
SIMILARITY_THRESHOLD = 72

LEDGER_DAYS = 14

# Outlets use different names for the same club in headlines -- "Spurs" and
# "Tottenham", "PSG" and "Paris Saint-Germain". Without folding these the
# fuzzy match misses obvious duplicates and the same signing goes out twice.
ALIASES = {
    "spurs": "tottenham",
    "psg": "paris saint germain",
    "paris st germain": "paris saint germain",
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "atletico": "atletico madrid",
    "atleti": "atletico madrid",
    "barca": "barcelona",
    "inter milan": "inter",
    "bayern munich": "bayern",
    "wolves": "wolverhampton",
    "leeds united": "leeds",
    "newcastle united": "newcastle",
    "west ham united": "west ham",
    "brighton and hove albion": "brighton",
    "nottingham forest": "forest",
}

# Words that carry no distinguishing information in a football headline and
# only inflate similarity between unrelated stories.
_STOPWORDS = frozenset(
    {"the", "and", "for", "with", "from", "his", "her", "their", "live",
     "highlights", "watch", "video", "report", "reaction", "updates"}
)


def collapse(stories: list[Story]) -> list[Story]:
    """Merge near-duplicates, keeping the most reliable version of each."""
    kept: list[Story] = []

    for story in sorted(stories, key=lambda s: (int(s.tier), -s.age_hours)):
        match = _find_similar(story, kept)
        if match is None:
            kept.append(story)
            continue

        # Same story, already held at an equal or better tier. Record the
        # corroboration -- multiple outlets on one story is a ranking signal.
        match.data.setdefault("corroborations", [])
        if story.source not in match.data["corroborations"]:
            match.data["corroborations"].append(story.source)

    log.info("collapsed %d stories to %d", len(stories), len(kept))
    return kept


def canonical(title: str) -> str:
    """Fold club aliases and drop noise words before comparing headlines."""
    text = "".join(
        ch if ch.isalnum() or ch.isspace() else " " for ch in title.lower()
    )
    text = " ".join(text.split())

    # Longest aliases first, so "paris st germain" is not half-matched.
    for alias in sorted(ALIASES, key=len, reverse=True):
        if alias in text:
            text = text.replace(alias, ALIASES[alias])

    return " ".join(w for w in text.split() if w not in _STOPWORDS)


def _find_similar(story: Story, pool: list[Story]) -> Story | None:
    mine = canonical(story.title)
    for other in pool:
        if other.kind is not story.kind:
            continue
        if fuzz.token_set_ratio(mine, canonical(other.title)) >= SIMILARITY_THRESHOLD:
            return other
    return None


class Ledger:
    """Append-only record of published fingerprints, so nothing runs twice."""

    def __init__(self, path: Path | None = None):
        self.path = path or (state_dir() / "ledger.json")
        self._entries: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._entries = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            log.warning("ledger corrupt at %s, starting fresh", self.path)
            self._entries = {}
        self._prune()

    def _prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=LEDGER_DAYS)
        self._entries = {
            fp: ts
            for fp, ts in self._entries.items()
            if _parse(ts) > cutoff
        }

    def seen(self, story: Story) -> bool:
        return story.fingerprint in self._entries

    def record(self, story: Story) -> None:
        self._entries[story.fingerprint] = datetime.now(
            timezone.utc
        ).isoformat()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries, indent=2))

    def filter_unseen(self, stories: list[Story]) -> list[Story]:
        fresh = [s for s in stories if not self.seen(s)]
        log.info("%d/%d stories are new", len(fresh), len(stories))
        return fresh


def _parse(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
