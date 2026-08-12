"""Caption and on-graphic copy, written by Claude against the brand voice.

Two separate asks, because they are different jobs: the card needs three or
four words that read at thumbnail size, the caption needs a short paragraph
that survives being read in full.
"""

from __future__ import annotations

import json
import logging
import re

from anthropic import Anthropic

from ..config import env, load
from ..models import TIER_LANGUAGE, Kind, Story, Tier

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
MAX_CAPTION_CHARS = 400


def _client() -> Anthropic:
    return Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def write(story: Story) -> dict[str, str]:
    """Return {headline, subhead, caption} for a story.

    Falls back to deterministic template copy if the API is unavailable, so a
    scheduled run never dies for want of a caption.
    """
    try:
        return _generate(story)
    except Exception as exc:
        log.error("caption generation failed (%s), using fallback", exc)
        return fallback(story)


def _generate(story: Story) -> dict[str, str]:
    brand = load("brand")
    voice = brand["voice"]

    system = _system_prompt(brand, voice)
    user = _user_prompt(story)

    resp = _client().messages.create(
        model=MODEL,
        max_tokens=700,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(
        block.text for block in resp.content if block.type == "text"
    )
    parsed = _parse_json(text)

    return {
        "headline": _cap(parsed.get("headline", ""), 42),
        "subhead": _cap(parsed.get("subhead", ""), 70),
        "caption": _sanitise(
            parsed.get("caption", ""), voice.get("banned_phrases", []), story
        ),
    }


def _system_prompt(brand: dict, voice: dict) -> str:
    rules = "\n".join(f"- {r}" for r in voice.get("rules", []))
    banned = ", ".join(voice.get("banned_phrases", []))
    return f"""You write copy for {brand['name']} ({brand['handle']}), a football \
(soccer) news account on Instagram and TikTok.

VOICE
{voice['persona']}

RULES
{rules}

Never use these phrases: {banned}

ACCURACY IS THE PRODUCT. You are given a headline and summary from a named
source. Write only what those support. If a detail is not in the input --
a fee, a contract length, a medical, a quote, a date -- it does not go in
the copy. An account that invents details dies the first time it is caught.

Return ONLY a JSON object, no prose around it:
{{
  "headline": "3-6 words for the graphic. All caps reads best at thumbnail size.",
  "subhead": "one supporting line, under 70 characters",
  "caption": "2-4 sentences for the post body. No hashtags -- they are added separately."
}}"""


def _user_prompt(story: Story) -> str:
    tier_rule = TIER_LANGUAGE[Tier(story.tier)]
    extras = ""
    if story.kind is Kind.RESULT and story.data:
        d = story.data
        extras = (
            f"\nSTRUCTURED RESULT: {d.get('home')} {d.get('home_goals')}"
            f"-{d.get('away_goals')} {d.get('away')} in {d.get('competition')}."
            " These numbers are verified; use them exactly."
        )

    return f"""CONTENT TYPE: {story.kind.value}
SOURCE: {story.source}
CERTAINTY: {tier_rule}

HEADLINE: {story.title}
SUMMARY: {story.summary or '(none supplied)'}{extras}

Write the graphic copy and caption."""


def _parse_json(text: str) -> dict:
    """Models occasionally wrap JSON in prose or a code fence. Handle both."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.S)
        if brace:
            text = brace.group(0)
    return json.loads(text)


def _sanitise(caption: str, banned: list[str], story: Story) -> str:
    """Last line of defence between the model and the account."""
    caption = " ".join(caption.split())

    for phrase in banned:
        # BREAKING is allowed, but only on confirmed news.
        if phrase.upper() == "BREAKING" and story.tier == Tier.CONFIRMED:
            continue
        caption = re.sub(re.escape(phrase), "", caption, flags=re.I).strip()

    caption = re.sub(r"#\w+", "", caption).strip()  # hashtags added separately

    if len(caption) > MAX_CAPTION_CHARS:
        cut = caption[:MAX_CAPTION_CHARS].rsplit(".", 1)[0]
        caption = (cut + ".") if cut else caption[:MAX_CAPTION_CHARS]

    return " ".join(caption.split())


def _cap(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]


def fallback(story: Story) -> dict[str, str]:
    """Deterministic copy from the story itself -- dull but never wrong."""
    if story.kind is Kind.RESULT and story.data:
        d = story.data
        return {
            "headline": f"{d['home_goals']}-{d['away_goals']}",
            "subhead": f"{d['home']} v {d['away']}",
            "caption": (
                f"{d['home']} {d['home_goals']}-{d['away_goals']} {d['away']} "
                f"in the {d['competition']}."
            ),
        }

    return {**_split_headline(story.title), "caption": story.title}


# Words a headline should never end on -- breaking here leaves the graphic
# reading like it was cut off mid-thought, which it was.
_DANGLING = frozenset(
    {"for", "to", "of", "in", "on", "at", "with", "as", "by", "from", "the",
     "a", "an", "and", "but", "or", "after", "over", "into", "amid"}
)


def _split_headline(title: str, target: int = 5) -> dict[str, str]:
    """Break a headline into graphic headline + subhead at a clean boundary.

    Prefers punctuation, then backs off the split point until it does not
    leave a preposition or article stranded at the end of the headline.
    """
    words = title.split()
    if len(words) <= target:
        return {"headline": title.upper(), "subhead": ""}

    # A colon or dash is the author's own structural break -- trust it.
    for i, word in enumerate(words[:target + 3]):
        if word.rstrip().endswith((":", "–", "—", "-")) and i >= 1:
            return {
                "headline": " ".join(words[: i + 1]).rstrip(":–—- ").upper(),
                "subhead": " ".join(words[i + 1:][:12]),
            }

    cut = min(target, len(words) - 1)
    while cut > 1 and words[cut - 1].lower().strip(",.") in _DANGLING:
        cut -= 1

    return {
        "headline": " ".join(words[:cut]).upper(),
        "subhead": " ".join(words[cut:][:12]),
    }
