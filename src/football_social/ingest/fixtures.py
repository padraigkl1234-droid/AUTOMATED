"""Match results and fixtures from football-data.org.

Results are the one content type we can render with total confidence, because
the data is structured rather than inferred from a headline. They are always
tier 1.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

from ..config import env, load
from ..models import Kind, Story, Tier

log = logging.getLogger(__name__)

API = "https://api.football-data.org/v4"
TIMEOUT = 20


def fetch_results(hours_back: int = 18) -> list[Story]:
    """Finished matches across configured competitions."""
    token = env("FOOTBALL_DATA_TOKEN")
    if not token:
        log.warning("FOOTBALL_DATA_TOKEN unset -- skipping results ingest")
        return []

    cfg = load("sources")
    since = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).date()
    today = datetime.now(timezone.utc).date()

    stories: list[Story] = []
    for comp in cfg.get("competitions", []):
        try:
            stories.extend(
                _fetch_competition(comp, token, since, today)
            )
        except Exception as exc:
            log.warning("competition %s failed: %s", comp.get("code"), exc)

    log.info("ingested %d finished matches", len(stories))
    return stories


def _fetch_competition(comp: dict, token: str, since, until) -> list[Story]:
    resp = requests.get(
        f"{API}/competitions/{comp['code']}/matches",
        headers={"X-Auth-Token": token},
        params={
            "dateFrom": since.isoformat(),
            "dateTo": until.isoformat(),
            "status": "FINISHED",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()

    out: list[Story] = []
    for match in resp.json().get("matches", []):
        story = _to_story(match, comp)
        if story:
            out.append(story)
    return out


def _to_story(match: dict, comp: dict) -> Story | None:
    home = match.get("homeTeam", {}).get("shortName") or \
        match.get("homeTeam", {}).get("name")
    away = match.get("awayTeam", {}).get("shortName") or \
        match.get("awayTeam", {}).get("name")
    full = match.get("score", {}).get("fullTime", {})
    hg, ag = full.get("home"), full.get("away")

    if not (home and away) or hg is None or ag is None:
        return None

    kicked_off = match.get("utcDate", "")
    try:
        when = datetime.fromisoformat(kicked_off.replace("Z", "+00:00"))
    except ValueError:
        when = datetime.now(timezone.utc)

    return Story(
        title=f"{home} {hg}-{ag} {away}",
        kind=Kind.RESULT,
        tier=Tier.CONFIRMED,
        source=comp["name"],
        url=f"https://www.football-data.org/",
        published_at=when,
        summary=f"{comp['name']} — full time.",
        data={
            "home": home,
            "away": away,
            "home_goals": hg,
            "away_goals": ag,
            "competition": comp["name"],
            "competition_weight": comp.get("weight", 0.5),
            "matchday": match.get("matchday"),
            "goal_total": hg + ag,
            "margin": abs(hg - ag),
        },
    )
