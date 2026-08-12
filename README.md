# Football social automation

Automated football (soccer) content for Instagram and TikTok. Ingests news
and results, ranks them, writes original copy in a fixed brand voice, renders
vertical graphics and video, and publishes the same post to both platforms on
a four-slot daily schedule.

```
RSS + football-data.org
        │
        ▼
   dedupe (club aliases, fuzzy titles) ──► ledger: have we posted this?
        │
        ▼
   score (recency, club pull, source tier, drama)
        │
        ▼
   caption (Claude, brand voice, tier-locked certainty)
        │
        ▼
   render (Pillow card ──► ffmpeg 1080x1920 mp4)
        │
        ▼
   review queue ──► approve ──► Instagram Graph API
                            └─► TikTok Content Posting API
```

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in keys as you get them

export PYTHONPATH=src

python -m football_social preview                    # rank today's stories
python -m football_social run evening_news --dry-run # render one post
python -m football_social queue                      # what's awaiting review
python -m football_social approve <fingerprint>      # publish it
```

`preview` works with no credentials at all — it reads public RSS. Start
there and see whether the ranking picks stories you would have picked.

## The three-position safety switch

`PUBLISH_MODE` decides how far a run goes:

| Mode | Renders | Queues | Publishes |
|---|---|---|---|
| `never` (default) | ✅ | ❌ | ❌ |
| `drafts` | ✅ | ✅ | ❌ |
| `auto` | ✅ | ✅ | ✅ |

Run on `drafts` for at least two weeks. You approve each post with one
command, which takes seconds a day, and you will catch the handful of bad
captions that teach you what to fix in `config/brand.yaml`. Flip to `auto`
only once the queue is producing posts you would have written yourself.

## What you need to get working, in order

**1. Data (free, today).** RSS needs nothing. Results need a free
[football-data.org](https://www.football-data.org/client/register) token.

**2. Captions.** An `ANTHROPIC_API_KEY`. Without it the pipeline falls back
to deterministic copy built from the headline — dull, but it never invents
anything and never blocks a run.

**3. Instagram.** Convert the account to Business or Creator, link it to a
Facebook Page, create a Meta app, and get a long-lived token with
`instagram_content_publish`. Note that the Graph API **does not accept file
uploads** — it fetches media from a public URL, so `MEDIA_BASE_URL` must
point at a host serving your `out/` directory (S3, R2, Bunny, GitHub Pages
all work). Publishing is capped at 100 posts per 24h per account; we stay
far below that.

**4. TikTok.** This is the slow one, so start it first. Read
`docs/RUNBOOK.md` before you build anything against it.

## Fonts

Drop `Inter-Black.ttf`, `Inter-Bold.ttf` and `Inter-Regular.ttf` into
`assets/fonts/` (Inter is free under the SIL Open Font License). Without
them the renderer falls back to a system face and warns — legible, but every
account using defaults looks like every other account using defaults. Custom
type is most of what makes a card look like a brand.

## Content and rights

The renderer draws everything from type, colour and geometry. It composites
no match photography and no club crests, because that imagery is licensed
and reposting it is the fastest route to takedowns and a disabled account.
The pipeline summarises headlines in original wording and attributes the
source on the graphic and in the caption.

If you want photography later, license it (Getty, Imago, AP have social
tiers) and add it as a background layer in `render/cards.py`.

Two other rules the code enforces rather than trusts you to remember:

- **Certainty is locked to source tier.** A tier-3 story physically cannot
  be captioned "confirmed" — see `TIER_LANGUAGE` in `models.py`. The card
  carries a `CONFIRMED` / `REPORTED` / `RUMOUR` pill so a reader knows what
  they are looking at before they read a word.
- **The caption prompt forbids invented detail.** No fee, contract length,
  medical, quote or date that was not in the source. An account that invents
  details dies the first time it is caught, and it will be caught.

Video is rendered silent on purpose. Music is the single largest copyright
exposure on both platforms; adding licensed audio from the in-app library at
review time is both safer and better for reach.

## Layout

```
config/          brand.yaml, sources.yaml, schedule.yaml -- tune here first
src/football_social/
  ingest/        rss, fixtures, dedupe, score
  generate/      captions (Claude), hashtags
  render/        cards (Pillow), video (ffmpeg)
  publish/       instagram, tiktok, queue + rate governor
  pipeline.py    the whole run, one slot at a time
  cli.py
.github/workflows/post.yml
state/           ledger + post history (committed on purpose, see .gitignore)
```

## Tests

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

28 tests, no network, no API keys.

## Tuning

Everything worth changing early is in `config/`:

- `brand.yaml` — voice rules, banned phrases, palette, hashtag caps
- `sources.yaml` — feeds and their tiers, club weightings
- `schedule.yaml` — slot times, content type per slot, rate limits

The scoring weights in `ingest/score.py` are starting guesses. Replace them
with what your own analytics tell you after a month; every component is
logged at debug level so you can see which signal promoted a post that
flopped.
