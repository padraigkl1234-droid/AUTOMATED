"""Rank stories so the four daily slots get the four best things available.

The score is deliberately explainable: every component is logged, so when a
post underperforms you can see which signal promoted it. Tune the weights
against your own analytics rather than trusting these defaults forever.
"""

from __future__ import annotations

import logging

from ..config import load
from ..models import Kind, Story, Tier

log = logging.getLogger(__name__)

# Base interest by content type, before any story-specific signals.
KIND_BASE = {
    Kind.TRANSFER: 55.0,
    Kind.RESULT: 40.0,
    Kind.RUMOUR: 35.0,
    Kind.FEATURE: 20.0,
}

# Confirmed news outperforms speculation, and rewarding it keeps the account
# honest as it grows.
TIER_BONUS = {Tier.CONFIRMED: 20.0, Tier.STRONG: 10.0, Tier.SPECULATIVE: 0.0}


def score_all(stories: list[Story]) -> list[Story]:
    for story in stories:
        story.score = score(story)
    return sorted(stories, key=lambda s: s.score, reverse=True)


def score(story: Story) -> float:
    parts = {
        "base": KIND_BASE.get(story.kind, 20.0),
        "tier": TIER_BONUS.get(story.tier, 0.0),
        "club": _club_bonus(story),
        "freshness": _freshness(story),
        "corroboration": _corroboration(story),
        "drama": _drama(story),
    }
    total = max(0.0, sum(parts.values()))
    log.debug("score %.1f %s %s", total, parts, story.title[:60])
    return round(total, 1)


def _club_bonus(story: Story) -> float:
    """Audience is concentrated in a handful of clubs. Reflect that."""
    cfg = load("sources").get("big_clubs", {})
    haystack = f"{story.title} {story.summary}".lower()

    best = 0.0
    for club in cfg.get("weight_2_0", []):
        if club.lower() in haystack:
            best = max(best, 20.0)
    for club in cfg.get("weight_1_5", []):
        if club.lower() in haystack:
            best = max(best, 12.0)
    return best


def _freshness(story: Story) -> float:
    """News decays fast. Six hours old is already stale on these platforms."""
    age = story.age_hours
    if age <= 1:
        return 25.0
    if age <= 3:
        return 18.0
    if age <= 6:
        return 10.0
    if age <= 12:
        return 3.0
    return -10.0  # actively penalised, we are not a history account


def _corroboration(story: Story) -> float:
    others = len(story.data.get("corroborations", []))
    return min(15.0, others * 6.0)


def _drama(story: Story) -> float:
    """Results only: goals and tight margins travel further than 1-0 wins."""
    if story.kind is not Kind.RESULT:
        return 0.0

    goals = story.data.get("goal_total", 0)
    margin = story.data.get("margin", 0)
    weight = story.data.get("competition_weight", 0.5)

    bonus = 0.0
    if goals >= 5:
        bonus += 18.0
    elif goals >= 4:
        bonus += 12.0
    elif goals >= 3:
        bonus += 6.0

    if margin >= 4:
        bonus += 10.0  # a thrashing is its own story
    elif margin == 0:
        bonus += 4.0

    return bonus * weight


def pick_for_slot(
    stories: list[Story], prefers: list[str], *, minimum: float = 0.0
) -> Story | None:
    """Highest-scoring story matching a slot's preferred kinds.

    Falls back to the best remaining story of any kind, because an empty slot
    costs more than a slightly off-format one.
    """
    wanted = {p.lower() for p in prefers}
    ranked = sorted(stories, key=lambda s: s.score, reverse=True)

    for story in ranked:
        if story.kind.value in wanted and story.score >= minimum:
            return story

    for story in ranked:
        if story.score >= minimum:
            log.info("slot fell back to %s (%s)", story.kind.value, story.title[:50])
            return story

    return None
