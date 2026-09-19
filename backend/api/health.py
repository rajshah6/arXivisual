"""
Dependency checks behind GET /api/health.

The endpoint is polled (deploy verification, uptime monitors), so nothing here
may block the event loop or do real work per request:

- ``manim --version`` costs 1-2 s of interpreter start-up. It used to run as a
  blocking ``subprocess.run`` inside the async handler on EVERY request; it now
  runs once, in a worker thread, and a success is cached for the life of the
  process (the binary does not change under a running container).
- The database and R2 checks are cached for a short TTL; R2 (boto3, sync) runs
  in a worker thread.
- Callers get generic strings. Raw exception text names hosts, users and key
  ids; the detail goes to the server log instead.
"""

import asyncio
import logging
import os
import subprocess
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import text

logger = logging.getLogger(__name__)

_DB_CHECK_TIMEOUT_SECONDS = 5.0
_FOREVER = float("inf")


def _ttl_seconds() -> float:
    return float(os.getenv("HEALTH_CACHE_TTL_SECONDS", "20"))


class _CachedCheck:
    """Single-flight, TTL-cached async check returning a status string."""

    def __init__(self, name: str):
        self.name = name
        self._value: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._value = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def expire(self) -> None:
        self._expires_at = 0.0

    async def get(self, probe: Callable[[], Awaitable[tuple[str, float]]]) -> str:
        """``probe`` returns (status, seconds to keep it)."""
        if self._value is not None and time.monotonic() < self._expires_at:
            return self._value
        async with self._lock:
            if self._value is not None and time.monotonic() < self._expires_at:
                return self._value
            self._value, keep_for = await probe()
            self._expires_at = time.monotonic() + keep_for
            return self._value


_manim = _CachedCheck("manim")
_database = _CachedCheck("database")
_storage = _CachedCheck("storage")
_CHECKS = (_manim, _database, _storage)


def reset_cache() -> None:
    """Forget every cached result (tests)."""
    for check in _CHECKS:
        check.reset()


def expire_cache() -> None:
    """Make every cached result stale, as if its TTL had passed (tests)."""
    for check in _CHECKS:
        check.expire()


def commit_sha() -> str:
    """The commit baked into the image (APP_COMMIT_SHA); the deploy workflow
    polls /api/health until this matches the sha it just built."""
    return os.getenv("APP_COMMIT_SHA", "").strip() or "unknown"


def database_dialect(db) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:
        return "unknown"


def _probe_manim_sync() -> tuple[str, float]:
    manim_exe = os.getenv("MANIM_EXECUTABLE", "manim")
    try:
        result = subprocess.run(
            [manim_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return "not installed", _ttl_seconds()
    except Exception as exc:
        # Includes TimeoutExpired: under CPU load that says nothing about the
        # install, so it is retried after the TTL rather than cached for good.
        logger.warning("Health: manim probe failed: %r", exc)
        return "error", _ttl_seconds()
    if result.returncode == 0:
        version = result.stdout.strip().split("\n")[0]
        return f"available ({version})", _FOREVER
    logger.warning(
        "Health: manim --version exited %s: %s",
        result.returncode, (result.stderr.strip() or result.stdout.strip())[-500:],
    )
    return "error", _ttl_seconds()


async def manim_status() -> str:
    return await _manim.get(lambda: asyncio.to_thread(_probe_manim_sync))


async def database_status(db) -> str:
    async def probe() -> tuple[str, float]:
        try:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=_DB_CHECK_TIMEOUT_SECONDS)
            return "connected", _ttl_seconds()
        except Exception as exc:
            logger.warning("Health: database check failed: %r", exc)
            return "error", _ttl_seconds()

    return await _database.get(probe)


def _probe_storage_sync() -> tuple[str, float]:
    import rendering.storage as storage

    if storage.STORAGE_MODE != "r2":
        return "local", _ttl_seconds()
    try:
        backend = storage.get_backend()
        if not hasattr(backend, "check_connectivity"):
            return "r2: configured", _ttl_seconds()
        return ("r2: connected" if backend.check_connectivity() else "r2: unreachable"), _ttl_seconds()
    except Exception as exc:
        logger.warning("Health: R2 check failed: %r", exc)
        return "r2: error", _ttl_seconds()


async def storage_status() -> str:
    return await _storage.get(lambda: asyncio.to_thread(_probe_storage_sync))
