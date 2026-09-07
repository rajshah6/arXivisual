"""Server-side Cloudflare Turnstile verification for POST /api/process.

The widget on the frontend only produces a token; the check that matters is
this one — a script hitting the API directly never renders the widget, so
without server verification proof-of-humanity would be decorative.

Unconfigured (no TURNSTILE_SECRET_KEY) = verification is skipped, so the code
ships inert and activates when the secret is wired in. Once configured it
fails CLOSED: a Cloudflare outage or a malformed token rejects the request
rather than becoming a free pass for whatever is being blocked.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_enabled() -> bool:
    return bool(os.getenv("TURNSTILE_SECRET_KEY"))


async def verify_turnstile(token: str | None, remote_ip: str | None = None) -> bool:
    """True if the token is valid for this site (or verification is off)."""
    secret = os.getenv("TURNSTILE_SECRET_KEY")
    if not secret:
        return True
    if not token:
        return False
    payload = {"secret": secret, "response": token}
    if remote_ip and remote_ip != "unknown":
        payload["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(SITEVERIFY_URL, data=payload)
        body = resp.json()
    except Exception as exc:
        logger.warning("Turnstile siteverify unavailable: %s", exc)
        return False
    if not body.get("success"):
        logger.info("Turnstile rejected token: %s", body.get("error-codes"))
        return False
    return True
