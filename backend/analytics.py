"""Product analytics — PostHog server-side events.

A thin wrapper so call sites stay one line and can never fail a job:

- NO-OP unless ``POSTHOG_API_KEY`` (the project token) is set; ``POSTHOG_HOST``
  defaults to PostHog's US ingestion endpoint. Local dev and CI run without a key.
- ``capture()`` never raises and never blocks: the posthog client queues the
  event and a daemon thread batches it out (``posthog.consumer.Consumer``).
  ``shutdown()`` flushes that queue; the FastAPI lifespan and the Temporal
  worker call it at exit.

Events (emitted from api/routes.py, temporal_app/activities.py, jobs/worker.py):

    paper_accepted       distinct_id = the pseudonymous client fingerprint the
                         admission logs already use (api/throttle.py)
    paper_completed      distinct_id = job_id — by the time a job finalizes no
    paper_failed_server  client identity exists (worker or background task)
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://us.i.posthog.com"

_client: Any = None
_lock = threading.Lock()


def enabled() -> bool:
    """Analytics is on iff a PostHog project token is configured."""
    return bool(os.environ.get("POSTHOG_API_KEY"))


def host() -> str:
    """Ingestion host: ``POSTHOG_HOST`` or the US default."""
    return os.environ.get("POSTHOG_HOST", "").strip().rstrip("/") or DEFAULT_HOST


def _get_client():
    """Lazy, thread-safe singleton. Built on the first capture so importing this
    module never starts the background consumer thread."""
    global _client  # noqa: PLW0603 — lazy singleton cache
    if _client is None:
        with _lock:
            if _client is None:
                from posthog import Posthog

                _client = Posthog(
                    project_api_key=os.environ["POSTHOG_API_KEY"],
                    host=host(),
                    # Server-side events only; never let the SDK hook sys.excepthook.
                    enable_exception_autocapture=False,
                    # GeoIP on a hashed fingerprint / job id is meaningless.
                    disable_geoip=True,
                )
    return _client


def capture(event: str, distinct_id: str, properties: dict[str, Any] | None = None) -> None:
    """Queue one event. Does nothing when analytics is off; logs (never raises)
    if the client misbehaves. Returns immediately — the send is asynchronous."""
    if not enabled():
        return
    try:
        _get_client().capture(event, distinct_id=distinct_id, properties=dict(properties or {}))
    except Exception:
        logger.debug("PostHog capture failed for %s", event, exc_info=True)


def duration_seconds(created_at: datetime | None) -> float | None:
    """Seconds from a job row's naive-UTC ``created_at`` (backend convention #6)
    to now; None when the row never had one."""
    if created_at is None:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    return round(max(0.0, (now - created_at).total_seconds()), 1)


def job_outcome(
    *,
    job_id: str,
    arxiv_id: str | None,
    status: str,
    videos_complete: int | None,
    videos_total: int | None,
    created_at: datetime | None,
    error: str | None = None,
) -> None:
    """``paper_completed`` (status == "completed") or ``paper_failed_server``.

    distinct_id is the job id: no client identity reaches the pipeline — the
    fingerprint only exists in the request that accepted the paper.
    """
    props: dict[str, Any] = {
        "arxiv_id": arxiv_id,
        "job_id": job_id,
        "videos_complete": videos_complete,
        "videos_total": videos_total,
        "duration_s": duration_seconds(created_at),
    }
    if status == "completed":
        capture("paper_completed", job_id, props)
        return
    props["error"] = (error or "").strip()[:500] or None
    capture("paper_failed_server", job_id, props)


def shutdown() -> None:
    """Flush queued events and stop the consumer. Safe when analytics never
    started, and safe to call more than once."""
    global _client
    with _lock:
        client, _client = _client, None
    if client is None:
        return
    try:
        client.shutdown()
    except Exception:
        logger.debug("PostHog shutdown failed", exc_info=True)
