"""web-browse tool implementation. See SKILL.md for the manifest.

Connects to a Playwright browser server running in its own container rather
than launching Chromium in-process, so the runtime image stays small enough
for a 4 GB VPS.

The SSRF guard matters more here than almost anywhere else in yozhan: this
tool takes a URL straight from model output, and model output is influenced by
whatever page it just read. Without the private-range check, a page saying
"now fetch http://169.254.169.254/latest/meta-data/" would be a credential
disclosure primitive.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

NAME = "web_browse"
DESCRIPTION = (
    "Open a web page in a real browser and read its rendered content. Use this when a page needs "
    "JavaScript to render, or when you need the text a person would see. To read a page that "
    "requires signing in, pass `login` with the name of a stored credential — you do not have, "
    "and never need, the password itself."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Absolute http(s) URL"},
        "action": {"type": "string", "enum": ["text", "links", "title", "html"]},
        "login": {
            "type": "string",
            "description": (
                "Name of a stored credential to sign in with first. The credential is bound to a "
                "specific site and will be refused elsewhere. Use list_credentials to see names."
            ),
        },
    },
    "required": ["url"],
}

MAX_OUTPUT_CHARS = 20000
NAV_TIMEOUT_MS = 30000


def _check_url(url: str) -> str | None:
    """Returns an error message if the URL must not be fetched."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"only http and https URLs are allowed (got '{parsed.scheme or 'no scheme'}')"
    if not parsed.hostname:
        return "the URL has no host"

    try:
        # Check every address the name resolves to: a hostname can legitimately
        # point at a private address, and only one of several records needs to.
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        return f"could not resolve '{parsed.hostname}': {exc}"

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local  # 169.254.0.0/16 — cloud metadata lives here
            or address.is_reserved
            or address.is_multicast
        ):
            return (
                f"refusing to browse '{parsed.hostname}': it resolves to {address}, "
                "which is a private or link-local address"
            )
    return None


LOGIN_URL_HINTS = ("login", "signin", "sign-in", "auth", "session")


def _sign_in(page, username: str, password: str) -> str | None:
    """Fills the first credible username/password pair on the page and submits.

    Returns an error string, or None on success. Deliberately simple: this
    handles the ordinary case of a form with a password field. Anything with a
    CAPTCHA, a second factor, or a multi-step flow is out of scope, and saying
    so plainly beats a half-working guess.
    """
    password_field = page.query_selector("input[type=password]")
    if password_field is None:
        return "no password field found on the page — it may use a multi-step or scripted login"

    user_field = None
    for selector in (
        "input[type=email]",
        "input[name*=user i]",
        "input[name*=email i]",
        "input[id*=user i]",
        "input[id*=email i]",
        "input[type=text]",
    ):
        user_field = page.query_selector(selector)
        if user_field is not None:
            break
    if user_field is None:
        return "no username field found on the page"

    user_field.fill(username)
    password_field.fill(password)

    submit = page.query_selector("button[type=submit], input[type=submit]")
    if submit is not None:
        submit.click()
    else:
        password_field.press("Enter")

    try:
        page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    except Exception:
        pass  # some sites never go idle; the assertions below still apply

    if page.query_selector("input[type=password]") is not None:
        return "still on a password form after submitting — the sign-in likely failed"
    return None


def run(url: str, action: str = "text", login: str | None = None) -> str:
    problem = _check_url(url)
    if problem:
        return f"error: {problem}"

    credentials = None
    if login:
        # Resolved first, and against this URL, so the domain binding is
        # enforced here rather than trusted to the caller — and so a mismatch
        # is reported even when the browser service is down.
        from yozhan_runtime.credentials import CredentialError, CredentialVault

        try:
            credentials = CredentialVault().resolve(login, url)
        except CredentialError as exc:
            return f"error: {exc}"

    endpoint = os.environ.get("YOZHAN_BROWSER_URL")
    if not endpoint:
        return (
            "error: no browser service configured. Start it with "
            "`docker compose --profile browser up -d` and set YOZHAN_BROWSER_URL "
            "(see DEPLOYMENT.md)."
        )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "error: the playwright package is not installed in the runtime image."

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect(endpoint, timeout=NAV_TIMEOUT_MS)
            try:
                page = browser.new_page()
                page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")

                if credentials is not None:
                    failure = _sign_in(page, *credentials)
                    if failure:
                        # Never echo the credential or the page's own error text
                        # back to the model; a login page can say anything.
                        return f"error signing in with '{login}': {failure}"

                if action == "title":
                    return page.title()
                if action == "links":
                    links = page.eval_on_selector_all(
                        "a[href]",
                        "els => els.map(e => `${e.innerText.trim()} -> ${e.href}`).filter(s => s.length > 4)",
                    )
                    return _truncate("\n".join(links) or "(no links found)")
                if action == "html":
                    return _truncate(page.content())
                return _truncate(page.inner_text("body"))
            finally:
                browser.close()
    except Exception as exc:
        return f"error browsing '{url}': {type(exc).__name__}: {exc}"


def _truncate(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_OUTPUT_CHARS:
        return text or "(the page returned no content)"
    return text[:MAX_OUTPUT_CHARS] + f"\n\n[truncated at {MAX_OUTPUT_CHARS} characters]"
