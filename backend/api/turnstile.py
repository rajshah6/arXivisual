"""Server-side Cloudflare Turnstile verification for POST /api/process.

The widget on the frontend only produces a token; the check that matters is
this one — a script hitting the API directly never renders the widget, so
without server verification proof-of-humanity would be decorative.

Unconfigured (no TURNSTILE_SECRET_KEY) = verification is skipped, so the code
ships inert and activates when the secret is wired in. Once configured it
fails CLOSED: a Cloudflare outage (after one retry) or a bad token rejects the
request rather than becoming a free pass for whatever is being blocked.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_DEFAULT_HOSTNAMES = "arxivisual.org,www.arxivisual.org,localhost"

# The widget mints every token with this action and the paper id as cData
# (frontend/components/TurnstileWidget.tsx mirrors both), so a token is only
# good for starting THAT paper: one solved challenge cannot be replayed
# across ids, and a token minted for anything else is refused.
TURNSTILE_ACTION = "start-paper"
_CDATA_MAX = 255
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


def turnstile_cdata(arxiv_id: str) -> str:
    """Encode an arXiv id into Turnstile's cData alphabet ([A-Za-z0-9_-],
    max 255): '.' -> '_', '/' -> '-', anything else dropped. Deterministic on
    both sides, so ambiguity does not matter — only equality does."""
    out = arxiv_id.replace(".", "_").replace("/", "-")
    return re.sub(r"[^A-Za-z0-9_-]", "", out)[:_CDATA_MAX]


@dataclass(frozen=True)
class TurnstileVerdict:
    ok: bool
    reason: str | None = None
    token_age_s: float | None = None


def _allowed_hostnames() -> set[str]:
    raw = os.getenv("TURNSTILE_ALLOWED_HOSTNAMES", _DEFAULT_HOSTNAMES)
    return {h.strip() for h in raw.split(",") if h.strip()}


async def verify_turnstile_detailed(
    token: str | None, remote_ip: str | None = None, *, expected_cdata: str | None = None,
) -> TurnstileVerdict:
    """Verify with Cloudflare; when ``expected_cdata`` is given the token must
    also carry our action and that cData (a trailing arXiv version suffix
    on either side is ignored, the API normalizes ids). Token age comes
    from siteverify's challenge_ts: a script submits at a near-constant
    delay after minting, people vary."""
    secret = os.getenv("TURNSTILE_SECRET_KEY")
    if not secret:
        return TurnstileVerdict(True)
    if not token:
        return TurnstileVerdict(False, "missing token")
    payload = {"secret": secret, "response": token}
    if remote_ip and remote_ip != "unknown":
        payload["remoteip"] = remote_ip

    body = None
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(SITEVERIFY_URL, data=payload)
            body = resp.json()
            break
        except Exception as exc:
            logger.warning("Turnstile siteverify unavailable (attempt %d): %s", attempt, exc)
    if body is None:
        return TurnstileVerdict(False, "siteverify unavailable")
    if not body.get("success"):
        logger.info("Turnstile rejected token: %s", body.get("error-codes"))
        return TurnstileVerdict(False, f"rejected {body.get('error-codes')}")
    # A token minted on another site is valid to Cloudflare but not to us.
    hostname = body.get("hostname")
    if hostname and hostname not in _allowed_hostnames():
        logger.warning("Turnstile token for unexpected hostname %r", hostname)
        return TurnstileVerdict(False, f"hostname {hostname!r}")
    if expected_cdata is not None:
        if body.get("action") != TURNSTILE_ACTION:
            return TurnstileVerdict(False, f"action {body.get('action')!r}")
        got = _VERSION_SUFFIX_RE.sub("", str(body.get("cdata") or ""))
        if got != _VERSION_SUFFIX_RE.sub("", expected_cdata):
            return TurnstileVerdict(False, f"cdata {body.get('cdata')!r} != {expected_cdata!r}")
    return TurnstileVerdict(True, None, _token_age_s(body.get("challenge_ts")))


def _token_age_s(challenge_ts: str | None) -> float | None:
    if not challenge_ts:
        return None
    try:
        minted = datetime.fromisoformat(str(challenge_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if minted.tzinfo is None:
        minted = minted.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - minted).total_seconds())


async def verify_turnstile(
    token: str | None, remote_ip: str | None = None, *, expected_cdata: str | None = None,
) -> bool:
    """True if the token is valid for this site (or verification is off)."""
    return (await verify_turnstile_detailed(token, remote_ip, expected_cdata=expected_cdata)).ok
