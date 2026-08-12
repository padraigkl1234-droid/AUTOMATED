# Runbook

Operational detail that does not belong in the README: platform access,
what breaks, and how to grow the account without getting it restricted.

---

## 1. Platform access — read before building

### TikTok is the long pole. Start it first.

The Content Posting API is free, but the audit is the gate:

- **Direct Post requires your app to pass TikTok's audit.** Until it does,
  every post is forced to `SELF_ONLY` — visible to nobody but you. It is not
  a soft limit you can work around.
- The audit takes **2–4 weeks** and usually needs several rounds of feedback.
- It has a hard UI requirement: before posting, your app must display the
  creator's username and avatar. A headless cron job cannot satisfy that by
  itself — which is exactly why the review queue exists.

So `TikTokClient` defaults to `mode="inbox"`. Inbox upload needs **no audit**:
content lands as a draft in your TikTok inbox and you tap publish in the app.
That is the honest way to run the first month anyway, and it costs you about
thirty seconds a day.

Flip to `mode="direct"` in `pipeline.publish()` only after you pass.

**One trap:** TikTok rotates the refresh token on use. If you do not persist
the new value back to your secret store, auth breaks silently. The client
logs a warning when it sees a new one — do not ignore it.

### Instagram

1. Convert the account to **Business** or **Creator**.
2. Link it to a Facebook Page (required, even if the Page stays empty).
3. Create a Meta app, add Instagram Graph API, request
   `instagram_content_publish` and `instagram_basic`.
4. Generate a **long-lived** token (60 days) and refresh it before expiry.
   A short-lived token will work in testing and then die in week one.

Two behaviours that surprise people:

- **No file uploads.** You pass a public URL; Instagram fetches it. If
  `MEDIA_BASE_URL` is wrong or the host is slow, container creation fails
  with an unhelpful error.
- **Publishing is two calls,** and video containers need transcode time. The
  client polls `status_code` rather than sleeping a fixed interval.

Check headroom any time with `python -m football_social quota`.

---

## 2. Daily operation

```bash
export PYTHONPATH=src

python -m football_social queue                 # review what's pending
python -m football_social approve <fingerprint> # ship it
python -m football_social reject  <fingerprint> --reason "caption is off"
```

Rejecting is as valuable as approving. Every rejection should turn into
either a new banned phrase in `brand.yaml` or a scoring tweak — otherwise you
will reject the same shape of post forever.

### Breaking news

`python -m football_social breaking` publishes only if something clears the
score floor (default 85). Wire it to a 30-minute cron during a transfer
window. It is capped at 3/day and 45 minutes apart so deadline day cannot
flood the feed.

---

## 3. When it breaks

| Symptom | Cause | Fix |
|---|---|---|
| `preview` returns nothing | Feeds unreachable, or everything already in the ledger | Check the feed URLs by hand; inspect `state/ledger.json` |
| Same story posted twice | Ledger not persisted between CI runs | Confirm the workflow's commit-back step ran |
| Captions are bland/repetitive | Falling back — no `ANTHROPIC_API_KEY` | Check logs for `caption generation failed` |
| TikTok posts invisible | App not audited | Expected. Use inbox mode |
| IG container `ERROR` | Media URL unreachable | `curl` your `MEDIA_BASE_URL` from outside your network |
| Cards look generic | No brand fonts | Drop TTFs into `assets/fonts/` |
| Rate governor blocking | Working as designed | `python -m football_social quota` |

Every publish failure is caught per-platform: Instagram failing never blocks
TikTok, and vice versa. Errors land in the queue JSON as
`instagram_error` / `tiktok_error`.

---

## 4. Growing the account

The automation gets you consistency and speed. Neither of those is a reason
to follow, so be clear-eyed about what this system does and does not do.

**What volume buys you.** Four posts a day is enough surface area to learn
what works within a few weeks. It is not, by itself, growth. The accounts
you named — 433, Romano — are not big because they post often. 433 built on
licensed and UGC video with genuine production value; Romano is one man with
sources nobody else has, and the format ("Here we go") is the packaging, not
the product.

**What this system cannot give you.** Neither original sourcing nor original
footage. So the honest positioning for an automated account is *speed and
clarity on public information*: be the fastest clean summary with the best
graphic, and be scrupulously accurate about what is confirmed versus what is
noise. The `CONFIRMED / REPORTED / RUMOUR` pill is the single most
differentiating thing in this repo — most aggregator accounts blur that line
deliberately, and being the one that doesn't is a real position.

**The first ninety days, concretely:**

1. **Weeks 1–2** — `drafts` mode. Approve manually. Every rejection becomes a
   config change. You are training the filter, not building an audience.
2. **Weeks 3–4** — Watch which of the four slots earns saves and shares. Kill
   or move the worst slot rather than adding a fifth.
3. **Month 2** — Add one thing the automation cannot do: a weekly human
   take, a recurring format, a voiceover. Automated feeds plateau at
   "useful"; the human layer is what converts followers.
4. **Month 3** — Only now consider `auto` mode, and only for the content type
   with the cleanest record (usually results — the data is structured, so the
   copy is verifiable).

**Things that get accounts restricted,** all of which this repo avoids by
design: reposting others' footage, music you have not licensed, engagement
bait ("Thoughts?" is a banned phrase for a reason), and posting the same
asset to both platforms with platform-specific watermarks left on.

**Cross-posting caveat.** The same graphic works on both, but TikTok rewards
native-feeling motion and on-screen text far more than Instagram does. If one
platform pulls ahead, stop treating them as identical and give TikTok longer
videos with more text-on-screen beats. The renderer is already separated from
the publishers to make that change small.

---

## 5. Cost

| Item | Approx monthly |
|---|---|
| Claude captions (4–8/day, Sonnet) | $1–3 |
| football-data.org free tier | $0 |
| Media hosting (R2/S3, a few hundred MB) | $0–1 |
| GitHub Actions (public repo) | $0 |

Under $5/month. The expensive input is your attention during the drafts
period, and that is the part worth spending.
