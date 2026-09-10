"""Browser origins allowed to call the API.

The production hosts are fixed; ``CORS_EXTRA_ORIGINS`` (comma-separated) adds
more by configuration — the frontend Container App's own
``azurecontainerapps.io`` FQDN, a staging host — so admitting a new frontend
never needs a code change and API redeploy.
"""

import os
from urllib.parse import urlsplit

DEFAULT_ORIGINS: tuple[str, ...] = (
    "https://arxivisual.org",
    "https://www.arxivisual.org",
    "http://localhost:3000",  # local frontend dev
)

_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_origin(origin: str) -> str:
    """Return ``origin`` exactly as a browser would send it in the ``Origin``
    header: lowercase scheme and host, default port omitted, nothing else.

    CORSMiddleware compares origins by string equality, so an entry that is
    merely *equivalent* (``HTTPS://Host:443``) would look configured while
    matching nothing. Anything that cannot be an origin at all — a path,
    query, fragment, userinfo, wildcard, or non-numeric port — raises.
    """
    if "*" in origin:
        raise ValueError(f"CORS_EXTRA_ORIGINS entry {origin!r}: wildcards are not origins")
    parts = urlsplit(origin)
    scheme = parts.scheme.lower()
    try:
        port = parts.port  # None when absent; ValueError when not numeric
    except ValueError as e:
        raise ValueError(f"CORS_EXTRA_ORIGINS entry {origin!r}: invalid port") from e
    if (
        scheme not in _DEFAULT_PORTS
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            f"CORS_EXTRA_ORIGINS entry {origin!r} is not an origin "
            "(expected scheme://host[:port], no path/query/userinfo)"
        )
    host = parts.hostname.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def allowed_origins() -> list[str]:
    origins = list(DEFAULT_ORIGINS)
    raw = os.getenv("CORS_EXTRA_ORIGINS", "")
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        origin = canonical_origin(entry)
        if origin not in origins:
            origins.append(origin)
    return origins
