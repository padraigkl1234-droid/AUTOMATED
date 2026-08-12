"""Command line entry point.

    python -m football_social preview          # what would we post right now?
    python -m football_social run <slot>       # produce one post for a slot
    python -m football_social breaking         # fire if something big landed
    python -m football_social queue            # list pending review items
    python -m football_social approve <fp>     # publish a queued item
    python -m football_social reject <fp>      # bin a queued item
    python -m football_social quota            # remaining IG publishes today
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import pipeline
from .config import load, publish_mode
from .ingest import dedupe
from .models import Post, Story
from .publish import queue as q


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="football_social")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preview", help="rank today's stories without posting")

    run = sub.add_parser("run", help="produce one post for a slot")
    run.add_argument("slot")
    run.add_argument("--dry-run", action="store_true")

    sub.add_parser("breaking", help="post only if a story clears the floor")
    sub.add_parser("queue", help="list items awaiting review")
    sub.add_parser("quota", help="remaining Instagram publishes in 24h window")
    sub.add_parser("slots", help="list configured slots")

    approve = sub.add_parser("approve", help="publish a queued item")
    approve.add_argument("fingerprint")

    reject = sub.add_parser("reject", help="discard a queued item")
    reject.add_argument("fingerprint")
    reject.add_argument("--reason", default="")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    return _dispatch(args)


def _dispatch(args) -> int:
    if args.cmd == "preview":
        return _preview()
    if args.cmd == "slots":
        return _slots()
    if args.cmd == "run":
        print(pipeline.run_slot(args.slot, dry_run=args.dry_run))
        return 0
    if args.cmd == "breaking":
        print(pipeline.run_breaking())
        return 0
    if args.cmd == "queue":
        return _queue()
    if args.cmd == "quota":
        return _quota()
    if args.cmd == "approve":
        return _approve(args.fingerprint)
    if args.cmd == "reject":
        q.Queue().reject(args.fingerprint, args.reason)
        return 0
    return 1


def _preview() -> int:
    stories = pipeline.gather()
    if not stories:
        print("No fresh stories. Check feeds and FOOTBALL_DATA_TOKEN.")
        return 0

    print(f"\n{len(stories)} candidates, best first "
          f"(PUBLISH_MODE={publish_mode().value}):\n")
    for s in stories[:15]:
        flag = {1: "CONFIRMED", 2: "REPORTED", 3: "RUMOUR"}[int(s.tier)]
        print(f"  {s.score:6.1f}  {s.kind.value:<9} {flag:<10} "
              f"{s.age_hours:4.1f}h  {s.title[:70]}")
        print(f"          {s.source} · {s.fingerprint}")
    return 0


def _slots() -> int:
    for slot in load("schedule")["slots"]:
        print(f"  {slot['at']}  {slot['id']:<22} {slot['template']:<15} "
              f"prefers={','.join(slot['prefers'])}")
        print(f"         {slot.get('note', '')}")
    return 0


def _queue() -> int:
    items = q.Queue().list_pending()
    if not items:
        print("Queue empty.")
        return 0

    print(f"\n{len(items)} awaiting review:\n")
    for item in items:
        print(f"  {item['fingerprint']}  [{item.get('slot_id', '-')}] "
              f"{item['template']}")
        print(f"    {item['story']['title'][:70]}")
        print(f"    caption: {item['caption'][:100]}")
        print(f"    media:   {item.get('video_path') or item.get('image_path')}")
        print()

    ok, why = q.can_post_now()
    print(f"Rate governor: {'OK' if ok else 'BLOCKED'} -- {why}")
    return 0


def _quota() -> int:
    try:
        from .publish.instagram import InstagramClient

        print(f"Instagram publishes remaining (24h): "
              f"{InstagramClient().remaining_quota()}")
    except Exception as exc:
        print(f"Could not read quota: {exc}", file=sys.stderr)
        return 1

    ok, why = q.can_post_now()
    print(f"Local governor: {'OK' if ok else 'BLOCKED'} -- {why}")
    return 0


def _approve(fingerprint: str) -> int:
    queue = q.Queue()
    item = queue.get(fingerprint)
    if item is None:
        print(f"Nothing pending with fingerprint {fingerprint}", file=sys.stderr)
        return 1

    ok, why = q.can_post_now()
    if not ok:
        print(f"Blocked by rate governor: {why}", file=sys.stderr)
        return 1

    post = _rehydrate(item)
    results = pipeline.publish(post)
    queue.mark_published(fingerprint, results)
    dedupe.Ledger().record(post.story)

    print(json.dumps(results, indent=2))
    return 0 if any(k in results for k in ("instagram", "tiktok")) else 1


def _rehydrate(item: dict) -> Post:
    """Rebuild a Post from its queued JSON."""
    from datetime import datetime

    from .models import Kind, Tier

    s = item["story"]
    story = Story(
        title=s["title"],
        kind=Kind(s["kind"]),
        tier=Tier(s["tier"]),
        source=s["source"],
        url=s["url"],
        published_at=datetime.fromisoformat(s["published_at"]),
        summary=s.get("summary", ""),
        data=s.get("data", {}),
        score=s.get("score", 0.0),
    )
    return Post(
        story=story,
        template=item["template"],
        caption=item["caption"],
        hashtags=item.get("hashtags", []),
        image_path=item.get("image_path"),
        video_path=item.get("video_path"),
        slot_id=item.get("slot_id", ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
