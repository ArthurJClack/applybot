# Live apply

Fill application forms inside **your own Firefox** instead of ApplyBot's separate browser. Firefox keeps
doing what it already does (saved logins, cookies, sign-in sessions), so you sign in the way you always do,
and ApplyBot only fills the application fields.

## What it does

- Fills every field ApplyBot has an answer for and attaches the tailored resume and cover letter
- Outlines what it filled in green and what still needs you in yellow, with a small panel listing those
- Lets Claude see the open form and type answers into it while you watch (`live_status`, `live_fill`)
- When the "thanks for applying" page appears: marks the job applied, **saves every answer you typed by
  hand** so the next form fills it automatically, and opens the next job in the queue in the same tab

## What it never does

- Read, store, type or even look at password fields. Sign-ins are yours (or Firefox's autofill)
- Click submit. You submit every application
- Replay "I agree" checkboxes, or let Claude answer legal / EEO / work-authorization questions without
  you confirming the answer
- Talk to anything except `127.0.0.1`. The bridge refuses requests from web pages

## Install (about a minute)

1. Pull this branch and restart the Claude desktop app so ApplyBot reloads
2. In Firefox open `about:debugging#/runtime/this-firefox`
3. Click **Load Temporary Add-on…** and pick `applybot/live/extension/manifest.json`
4. Ask Claude to "start live apply" (it calls `live_start`, then `live_open` with a list of jobs)

A temporary add-on is removed when Firefox restarts, so repeat step 2-3 after a restart. To make it
permanent, sign it once with `web-ext sign` (free Mozilla account) and install the signed `.xpi`.

The toolbar button runs ApplyBot on a page whose site is not in the built-in list.

## Settings

`config.yaml`:

```yaml
live:
  port: 8765
```
