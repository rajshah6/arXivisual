"""Browser origins allowed to call the API.

The production hosts are fixed; ``CORS_EXTRA_ORIGINS`` (comma-separated) adds
more by configuration — the Azure Container Apps frontend FQDN while
arxivisual.org still points at Vercel, a staging host later — so admitting a
new frontend never needs a code change and API redeploy.
"""

import os
from urllib.parse import urlsplit

DEFAULT_ORIGINS: tuple[str, ...] = (
    "https://arxivisual.org",
    "https://www.arxivisual.org",
    "http://localhost:3000",  # local frontend dev
)


def _validate(origin: str) -> str:
    """An origin is scheme://host[:port] and nothing else; a path, query or
    wildcard would never equal a browser's ``Origin`` header, so a policy
    containing one looks configured while matching nothing."""
    parts = urlsplit(origin)
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or parts.path
        or parts.query
        or parts.fragment
        or "*" in origin
    ):
        raise ValueError(
            f"CORS_EXTRA_ORIGINS entry {origin!r} is not an origin "
            "(expected scheme://host[:port], no path)"
        )
    return origin


def allowed_origins() -> list[str]:
    origins = list(DEFAULT_ORIGINS)
    raw = os.getenv("CORS_EXTRA_ORIGINS", "")
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        origin = _validate(origin)
        if origin not in origins:
            origins.append(origin)
    return origins
