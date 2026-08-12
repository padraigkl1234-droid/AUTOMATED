"""Offline tests. Nothing here touches the network or a real API.

Run: PYTHONPATH=src python3 -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_social.generate import captions, hashtags  # noqa: E402
from football_social.ingest import dedupe, rss, score  # noqa: E402
from football_social.models import Kind, Post, Story, Tier  # noqa: E402
from football_social.publish import queue as q  # noqa: E402
from football_social.render import cards  # noqa: E402


def make_story(title="Arsenal sign Declan Rice", **kw) -> Story:
    defaults = dict(
        kind=Kind.TRANSFER,
        tier=Tier.CONFIRMED,
        source="BBC Sport",
        url="https://example.test/1",
        published_at=datetime.now(timezone.utc),
        summary="A summary.",
    )
    defaults.update(kw)
    return Story(title=title, **defaults)


# --- classification -------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Arsenal complete signing of Declan Rice", Kind.TRANSFER),
    ("Chelsea eyeing move for Osimhen", Kind.RUMOUR),
    ("Arsenal 2-1 Chelsea", Kind.RESULT),
    ("Liverpool beat Everton in derby", Kind.RESULT),
    ("The tactical evolution of the false nine", Kind.FEATURE),
])
def test_classify(title, expected):
    assert rss.classify(title) is expected


def test_hedged_headline_is_demoted():
    """A reliable outlet speculating is still speculation."""
    assert rss.adjust_tier(Tier.CONFIRMED, "United could move for Kane",
                           Kind.RUMOUR) is Tier.STRONG


def test_confirmed_headline_keeps_tier():
    assert rss.adjust_tier(Tier.CONFIRMED, "United sign Kane",
                           Kind.TRANSFER) is Tier.CONFIRMED


# --- dedupe ---------------------------------------------------------------

def test_club_aliases_collapse():
    """Spurs/Tottenham and PSG/Paris are the same club to a dedupe pass."""
    a = make_story("Atletico agree £34.2m deal for Tottenham's Romero")
    b = make_story("Atletico agree deal to sign Spurs captain Romero",
                   source="Sky Sports", tier=Tier.STRONG)

    kept = dedupe.collapse([a, b])
    assert len(kept) == 1
    assert "Sky Sports" in kept[0].data["corroborations"]


def test_distinct_stories_survive():
    a = make_story("Arsenal sign Declan Rice")
    b = make_story("Chelsea sign Moises Caicedo")
    assert len(dedupe.collapse([a, b])) == 2


def test_different_kinds_never_merge():
    a = make_story("Arsenal sign Rice", kind=Kind.TRANSFER)
    b = make_story("Arsenal sign Rice", kind=Kind.RESULT)
    assert len(dedupe.collapse([a, b])) == 2


def test_ledger_blocks_repeats(tmp_path):
    ledger = dedupe.Ledger(tmp_path / "l.json")
    story = make_story()

    assert ledger.filter_unseen([story]) == [story]
    ledger.record(story)
    assert ledger.filter_unseen([story]) == []

    # Survives a reload -- the ledger is the only thing preventing a repost
    # after the process restarts.
    assert dedupe.Ledger(tmp_path / "l.json").seen(story)


# --- scoring --------------------------------------------------------------

def test_confirmed_outranks_rumour():
    confirmed = make_story("Arsenal sign Rice", tier=Tier.CONFIRMED)
    rumour = make_story("Arsenal eyeing Rice", tier=Tier.SPECULATIVE,
                        kind=Kind.RUMOUR)
    assert score.score(confirmed) > score.score(rumour)


def test_stale_news_is_penalised():
    fresh = make_story()
    stale = make_story(
        published_at=datetime.now(timezone.utc) - timedelta(hours=30)
    )
    assert score.score(fresh) > score.score(stale)


def test_big_club_bonus():
    big = make_story("Real Madrid sign a midfielder")
    small = make_story("Luton Town sign a midfielder")
    assert score.score(big) > score.score(small)


def test_slot_prefers_matching_kind():
    result = make_story("Arsenal 3-0 Spurs", kind=Kind.RESULT)
    transfer = make_story("Arsenal sign Rice", kind=Kind.TRANSFER)
    score.score_all([result, transfer])

    picked = score.pick_for_slot([result, transfer], ["result"])
    assert picked is result


def test_slot_falls_back_rather_than_returning_nothing():
    """An empty slot costs more than a slightly off-format post."""
    transfer = make_story("Arsenal sign Rice", kind=Kind.TRANSFER)
    score.score_all([transfer])
    assert score.pick_for_slot([transfer], ["result"]) is transfer


# --- copy -----------------------------------------------------------------

def test_fallback_never_dangles_a_preposition():
    out = captions._split_headline("Atletico agree £34.2m deal for Romero")
    assert not out["headline"].split()[-1].lower() in captions._DANGLING


def test_fallback_uses_authors_own_break():
    out = captions._split_headline("Super Cup: PSG beat Aston Villa on penalties")
    assert out["headline"] == "SUPER CUP"


def test_banned_phrases_are_stripped():
    story = make_story(tier=Tier.SPECULATIVE)
    cleaned = captions._sanitise(
        "You won't believe this. Arsenal want him. Thoughts?",
        ["You won't believe", "Thoughts?"], story,
    )
    assert "believe" not in cleaned.lower()
    assert "Thoughts" not in cleaned


def test_breaking_allowed_only_on_confirmed():
    banned = ["BREAKING"]
    confirmed = captions._sanitise("BREAKING: he signs.", banned,
                                   make_story(tier=Tier.CONFIRMED))
    rumour = captions._sanitise("BREAKING: he might sign.", banned,
                                make_story(tier=Tier.SPECULATIVE))
    assert "BREAKING" in confirmed
    assert "BREAKING" not in rumour


def test_captions_carry_no_hashtags():
    """Hashtags are appended once, from the tag builder -- never inline."""
    out = captions._sanitise("Arsenal sign Rice #afc #transfer", [], make_story())
    assert "#" not in out


def test_hashtags_stay_within_cap():
    tags = hashtags.build(make_story("Manchester United beat Liverpool"))
    assert len(tags) <= 6
    assert len(tags) == len(set(tags))
    assert "#mufc" in tags


# --- render ---------------------------------------------------------------

def test_card_renders_at_platform_size(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_UPLOAD_DIR", str(tmp_path))

    story = make_story()
    story.data.update(captions.fallback(story))
    post = Post(story=story, template="transfer_card",
                caption="Arsenal have signed Declan Rice.",
                hashtags=["#football"])

    path = cards.render(post, size="story")

    from PIL import Image
    assert Image.open(path).size == (1080, 1920)


def test_every_template_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_UPLOAD_DIR", str(tmp_path))

    story = make_story("Arsenal 3-1 Chelsea", kind=Kind.RESULT)
    story.data.update({
        "home": "Arsenal", "away": "Chelsea",
        "home_goals": 3, "away_goals": 1, "competition": "Premier League",
        **captions.fallback(story),
    })

    for template in ("score_card", "transfer_card", "quote_card"):
        post = Post(story=story, template=template, caption="c", hashtags=[])
        assert cards.render(post, size="story").exists()


# --- rate governor --------------------------------------------------------

def test_daily_cap_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "state_dir", lambda: tmp_path)

    now = datetime.now(timezone.utc)
    (tmp_path / "post_history.json").write_text(
        __import__("json").dumps(
            [(now - timedelta(minutes=90 * i)).isoformat() for i in range(9)]
        )
    )
    ok, why = q.can_post_now()
    assert not ok and "daily cap" in why


def test_minimum_gap_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "state_dir", lambda: tmp_path)

    (tmp_path / "post_history.json").write_text(
        __import__("json").dumps([datetime.now(timezone.utc).isoformat()])
    )
    ok, why = q.can_post_now()
    assert not ok and "since last post" in why


def test_governor_allows_when_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "state_dir", lambda: tmp_path)
    ok, _ = q.can_post_now()
    assert ok


# --- queue round trip -----------------------------------------------------

def test_queue_round_trip(tmp_path):
    queue = q.Queue(tmp_path)
    story = make_story()
    post = Post(story=story, template="transfer_card", caption="c",
                hashtags=["#football"], image_path="/tmp/x.png")

    queue.add(post, "evening_news")
    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0]["slot_id"] == "evening_news"

    queue.mark_published(story.fingerprint, {"instagram": "123"})
    assert queue.list_pending() == []
    assert (tmp_path / "published" / f"{story.fingerprint}.json").exists()
