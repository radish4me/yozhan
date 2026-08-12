---
name: web-browse
version: 0.1.0
description: Open a web page in a real browser and read its rendered text, links, or title.
capabilities: [web, browser]
tags: [core, web]
depends_on: []
tool: true
# Needs network access and a connection to the browser service, neither of
# which the network-isolated sandbox provides.
elevated: true
---

# web-browse

Fetches a page through a real headless Chromium, so JavaScript-rendered
content is visible. A plain HTTP fetch returns the empty shell of a modern
site; this returns what a person would actually see.

## Actions

- `text` — the rendered visible text (default)
- `links` — every link on the page, as `text -> url`
- `title` — just the page title
- `html` — the rendered HTML, truncated

## Requirements

The browser runs as a **separate container**, not inside the runtime: a
Chromium install is several hundred megabytes and would bloat the runtime
image on a small VPS. Start it with the `browser` compose profile and set
`YOZHAN_BROWSER_URL`. Without it, this tool returns a clear message saying so
rather than failing obscurely.

## Signing in

Pass `login` with the **name** of a stored credential to sign in first:

    web_browse(url="https://github.com/notifications", login="github")

You never handle the password. It is stored encrypted server-side, injected
straight into the page, and bound to one site — a credential stored for
`github.com` is refused on any other host, including lookalikes such as
`github.com.evil.com`. That binding is what stops a page you are reading from
talking you into signing in somewhere it shouldn't.

Manage them with `/credential list|add|remove`, or from the dashboard.

## Limits

- Public HTTP/HTTPS only. Requests to localhost and private network ranges are
  refused, so a prompt cannot use this to reach services inside your network.
- Output is truncated; this is for reading pages, not downloading files.
- Sign-in handles an ordinary username/password form only. CAPTCHAs, two-factor
  prompts and multi-step flows are out of scope and will say so.
- Beyond signing in, this is read-only: no clicking through, no form filling,
  no purchases. Anything that changes state on a website is a decision a person
  should make.
