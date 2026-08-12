"""Hashtag selection.

Small, relevant sets beat 30-tag blocks on current ranking, and a tag that
matches the post keeps the account legible to the recommender. We mix core
tags, a type pool, and any club names actually present in the story.
"""

from __future__ import annotations

from ..config import load
from ..models import Story

# Club name -> the tag people actually use for it.
CLUB_TAGS = {
    "manchester united": "#mufc",
    "manchester city": "#mcfc",
    "liverpool": "#lfc",
    "arsenal": "#afc",
    "chelsea": "#cfc",
    "tottenham": "#thfc",
    "real madrid": "#realmadrid",
    "barcelona": "#fcbarcelona",
    "bayern": "#fcbayern",
    "paris saint-germain": "#psg",
    "juventus": "#juventus",
    "ac milan": "#acmilan",
    "inter": "#inter",
    "newcastle": "#nufc",
    "aston villa": "#avfc",
}


def build(story: Story) -> list[str]:
    cfg = load("brand")["hashtags"]
    tags: list[str] = list(cfg.get("core", []))

    pool = cfg.get("pools", {}).get(story.kind.value, [])
    if pool:
        tags.append(pool[0])

    tags.extend(_club_tags(story))

    # De-duplicate while preserving priority order.
    seen, out = set(), []
    for tag in tags:
        low = tag.lower()
        if low not in seen:
            seen.add(low)
            out.append(tag)

    return out[: cfg.get("max_total", 6)]


def _club_tags(story: Story) -> list[str]:
    haystack = f"{story.title} {story.summary}".lower()
    return [tag for club, tag in CLUB_TAGS.items() if club in haystack]
