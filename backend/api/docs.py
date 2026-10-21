"""Where FastAPI's interactive docs live, by environment.

The 2026-10-20 audit found /docs, /redoc and /openapi.json served publicly
from production: a complete, machine-readable map of every route, including
the admission-controlled POST /api/process and the secret-gated POST
/api/render, for anyone probing the API. Nothing consumes the schema in
production (the frontend has hand-written types, CI never fetches it), so
production serves none of the three. Local and CI keep them.
"""

from __future__ import annotations


def docs_urls(environment: str | None) -> dict[str, str | None]:
    """Return the ``docs_url`` / ``redoc_url`` / ``openapi_url`` kwargs for
    ``FastAPI(...)``: all ``None`` in production, the defaults elsewhere.

    ``environment`` is the ``ENVIRONMENT`` env var; the comparison matches
    the one that locks POST /api/render (api/routes.py).
    """
    if (environment or "development").strip().lower() == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
