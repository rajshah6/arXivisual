"""Periodic stale-job reaper.

``queries.reap_stale_jobs`` used to run only inside POST /api/process, so a
row stranded at queued/processing (worker killed mid-run) stayed that way
until the next human submitted a paper. Until then it counted in the KEDA
scale rule (``SELECT COUNT(*) ... status IN ('queued','processing')``) and
kept a 2 vCPU replica billing at the active rate, and Explore showed the
paper as "processing". The 2026-10-20 audit measured ~0.4 extra worker
replicas on average, partly from exactly these phantom-held rows.

The API runs this loop from its lifespan: every ``interval`` seconds, open
a session and reap. The per-submission call stays — it is what guarantees a
re-submission is not blocked by a zombie.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 900.0


def reap_interval_seconds() -> float:
    """``STALE_JOB_REAP_INTERVAL_SECONDS``; 0 (or junk) disables the loop."""
    raw = os.getenv("STALE_JOB_REAP_INTERVAL_SECONDS", str(int(DEFAULT_INTERVAL_SECONDS)))
    try:
        value = float(raw)
    except ValueError:
        logger.warning("STALE_JOB_REAP_INTERVAL_SECONDS=%r is not a number; reaper disabled", raw)
        return 0.0
    return max(0.0, value)


async def reap_forever(
    interval: float,
    session_maker: Callable[[], object],
    reap: Callable[..., Awaitable[int]],
) -> None:
    """Call ``reap(db)`` every ``interval`` seconds until cancelled.

    One failed pass (the database being what is down, say) is logged and
    the loop keeps going; cancellation is the only way out, and it is clean.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_maker() as db:
                reaped = await reap(db)
            if reaped:
                logger.info("Reaped %d stale job(s)", reaped)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Stale-job reaper pass failed; will retry in %ss", interval)
