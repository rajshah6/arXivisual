"""Cost protection for the public processing endpoint.

Every ``POST /api/process`` run costs real money (LLM generation + rendering,
roughly $0.10/paper) and minutes of the container's 2 vCPUs — and the endpoint
is public with real traffic. Two guards:

- Sliding-window rate limits: per-client-IP and a global cap across all clients.
- A short-TTL recent-jobs map used for duplicate-submit detection during the
  window before the worker links ``job.paper_id`` (it's NULL at creation to
  avoid an FK violation, so a DB lookup alone misses immediate double-clicks).

State is in-memory and per-replica. With Container Apps at 1-2 replicas that
bounds cost within a small factor of the configured limits, which is the goal —
this is a cost fuse, not billing-grade accounting. A shared store (Redis) is the
upgrade path if replicas grow.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from fastapi import Request


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


class SlidingWindowLimiter:
    """Thread-safe sliding-window counter. ``max_events == 0`` disables it."""

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Drop all recorded events (used by tests)."""
        with self._lock:
            self._events.clear()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record-and-check. Returns (allowed, retry_after_seconds)."""
        if self.max_events == 0:
            return True, 0
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.max_events:
                retry_after = int(q[0] + self.window_seconds - now) + 1
                return False, max(1, retry_after)
            q.append(now)
            # Opportunistic cleanup so the map doesn't grow unboundedly.
            if len(self._events) > 10_000:
                dead = [k for k, v in self._events.items() if not v or v[-1] <= cutoff]
                for k in dead:
                    del self._events[k]
            return True, 0


class RecentJobs:
    """arxiv_id -> job_id remembered for a short TTL, for duplicate submits."""

    def __init__(self, ttl_seconds: float = 600):
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, arxiv_id: str, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        with self._lock:
            entry = self._jobs.get(arxiv_id)
            if not entry:
                return None
            job_id, ts = entry
            if now - ts > self.ttl_seconds:
                del self._jobs[arxiv_id]
                return None
            return job_id

    def put(self, arxiv_id: str, job_id: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._jobs[arxiv_id] = (job_id, now)
            if len(self._jobs) > 10_000:
                cutoff = now - self.ttl_seconds
                for k in [k for k, (_, ts) in self._jobs.items() if ts <= cutoff]:
                    del self._jobs[k]

    def clear(self, arxiv_id: str) -> None:
        with self._lock:
            self._jobs.pop(arxiv_id, None)


def client_ip(request: Request) -> str:
    """Client IP, honoring the ingress proxy's X-Forwarded-For (first hop)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


# Defaults: a person exploring the site can start 5 papers an hour; the whole
# world combined is capped at 30/hour (~$3/hour worst-case LLM+render spend).
# Set either env to 0 to disable that limiter.
per_ip_limiter = SlidingWindowLimiter(
    max_events=_int_env("RATE_LIMIT_PROCESS_PER_IP", 5),
    window_seconds=_int_env("RATE_LIMIT_PROCESS_WINDOW_SECONDS", 3600),
)
global_limiter = SlidingWindowLimiter(
    max_events=_int_env("RATE_LIMIT_PROCESS_GLOBAL", 30),
    window_seconds=_int_env("RATE_LIMIT_PROCESS_WINDOW_SECONDS", 3600),
)
recent_jobs = RecentJobs(ttl_seconds=_int_env("PROCESS_DEDUPE_TTL_SECONDS", 600))

# Feedback is cheap to store but still abusable; own bucket AND own window —
# tuning the /api/process cost fuse must not silently retune feedback.
feedback_limiter = SlidingWindowLimiter(
    max_events=_int_env("RATE_LIMIT_FEEDBACK_PER_IP", 30),
    window_seconds=_int_env("RATE_LIMIT_FEEDBACK_WINDOW_SECONDS", 3600),
)
