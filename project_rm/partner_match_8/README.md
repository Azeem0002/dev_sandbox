# Partner Match 8

NearSpace-style MVP for broader partner discovery: people opt into location,
show active status, find nearby partners with similar mindset/goals, and form
small teammate groups with an AI helper inside group chat.

## MVP Scope

- Google login, with `dev:user@example.com` accepted for local testing.
- Active status from heartbeat/last-seen time.
- Opt-in location search with coarse distance labels instead of public exact coordinates.
- Partner profiles with mindset tags, curated goal tags, curated sub-goal tags, availability, and what the user is looking for.
- Unique usernames for public identity.
- Verification badge support through `PARTNER_MATCH_VERIFIED_EMAILS`.
- Public shoutout/building posts with text and media URLs for images/videos.
- Likes, comments, follows, partner requests, notifications, and profile visit counts.
- Teammate groups capped by `PARTNER_MATCH_MAX_GROUP_MEMBERS` instead of a buried magic number.
- Group admin add/remove controls.
- Group invite links with expiry/revoke/join flow.
- Group chat with local deterministic AI response when a message starts with `@agent`.
- In-app safety through user/group reports and user blocking.
- Soft account deletion that disables location and revokes sessions.

## Goal Tags

Primary goal tags:

```text
fitness, study, programming, business
```

Sub-goal tags:

```text
backend programming, frontend programming, mobile programming, data science,
ai automation, trading, crypto, sales, marketing, startup, exam prep,
accountability, strength training, weight loss
```

Availability values:

```text
open_to_partner, busy, not_looking
```

## Product Wording

Use `partners` for one-to-one connections. Use `circles` for small trusted groups.
Avoid `friends` because this app is about mindset, accountability, building, and
partnership. Avoid `crew` for now because it feels casual and less professional.

Feed lanes:

```text
shoutout -> quick public update, ask, win, or signal
building -> deeper progress post about what someone is creating or learning
```

## Feed Algorithm

MVP feed ranking is transparent and deterministic:

- boost posts from people the user follows
- boost posts sharing the user's mindset, goal, or sub-goal tags
- boost posts with likes/comments, but cap that boost so popular posts do not dominate forever
- slightly boost `building` posts because they signal serious progress
- decay older posts so the feed stays fresh
- hide posts from users blocked by either side

This is the correct first version. Real ML/AI ranking should come after the app
has enough behavior data: impressions, clicks, likes, follows, comments, hides,
reports, accepted partner requests, and retained conversations.

## Architecture Decision

Use one unified backend API. Web, mobile, and desktop clients should all call the
same FastAPI backend. The frontend stays platform-agnostic because the backend
owns auth, matching, groups, reports, AI routing, and persistence.

SQLite is fine for local MVP and demos. For real users, move the same adapter
surface to managed Postgres before launch.

## Run

```bash
cd /home/az/dev_sandbox/project_rm
uv run --project .. uvicorn partner_match_8.api:app --reload
```

## Local Smoke Test

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/auth/google -H "Content-Type: application/json" -d '{"id_token":"dev:az@example.com"}'
```

Use the returned token as:

```bash
curl http://127.0.0.1:8000/me -H "Authorization: Bearer TOKEN_HERE"
```

## Suggested Features To Review Later

- Interest/mindset compatibility score.
- Admin handoff before leaving a group.
- Paid tier for larger groups, richer AI, or private partner circles.
- Moderation dashboard for reports.

## Developer Contact

For reviews, partner onboarding, custom deployments, or partnership discussions,
show the developer contact in the product/docs through configurable values:

```text
Email: DEV_CONTACT_EMAIL
WhatsApp: DEV_CONTACT_WHATSAPP
```
