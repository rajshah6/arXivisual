"""Shared test configuration.

Keeps the test suite offline: disables Langfuse tracing so decorated pipeline
functions don't try to export spans to the network during unit tests. (A fuller
socket-blocking fixture is tracked in the backlog under Testing & CI.)
"""

import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
# Product analytics (PostHog) and Application Insights are NO-OPs without
# their env vars; make sure a developer's shell never switches them on here.
os.environ.pop("POSTHOG_API_KEY", None)
os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)


def make_fake_http_client(responses: dict):
    """Factory for a stand-in ``httpx.AsyncClient`` (monkeypatch it onto the
    module under test). ``responses`` maps URL -> (status, headers) for HEAD
    and URL -> (status, json) for POST; unknown URLs raise RequestError."""
    import httpx

    class _Resp:
        def __init__(self, status, payload):
            self.status_code = status
            self.headers = payload if isinstance(payload, dict) and "location" in payload else {}
            self._json = payload

        def json(self):
            return self._json

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def head(self, url):
            if url not in responses:
                raise httpx.RequestError(f"no fake for {url}")
            return _Resp(*responses[url])

        async def post(self, url, **k):
            if url not in responses:
                raise httpx.RequestError(f"no fake for {url}")
            return _Resp(*responses[url])

    return _Client
