"""Lazy, cached Temporal client for the API process.

The API only ever *starts* workflows — all execution happens on the worker
Container App. Kept in its own module so importing routes never touches
Temporal when USE_TEMPORAL is off.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import TypeVar

from temporalio.client import Client
from temporalio.service import RPCError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Memo key naming the job a workflow run belongs to (see retried_start_is_ours).
JOB_ID_MEMO_KEY = "job_id"

_client: Client | None = None


def temporal_enabled() -> bool:
    return os.getenv("USE_TEMPORAL", "0") == "1"


def reset_temporal_client() -> None:
    """Drop the cached client so the next call reconnects."""
    global _client  # noqa: PLW0603 — lazy singleton cache
    _client = None


async def get_temporal_client() -> Client:
    global _client  # noqa: PLW0603 — lazy singleton cache
    if _client is None:
        _client = await Client.connect(
            os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
            namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            # Container Apps fronts gRPC with HTTP/2 ingress behind TLS (:443);
            # raw TCP ingress proved unroutable on this environment.
            tls=os.getenv("TEMPORAL_TLS", "0") == "1",
        )
    return _client


async def call_with_reconnect(call: Callable[[Client], Awaitable[T]]) -> T:
    """Run ``call(client)``; on a connect failure or RPCError, reconnect and retry ONCE.

    The cached client outlives the connection it was built on: after the
    Temporal app restarted, every start_workflow on the old client raised
    "tcp connect error" until the API itself restarted, and 36 jobs in 10 days
    silently ran on the in-process fallback. A failed client is therefore never
    left in the cache — not after the retry either, so the NEXT request starts
    from a fresh connection too.

    Only transport-level trouble is retried. Everything else — notably
    WorkflowAlreadyStartedError, which is an answer, not an outage —
    propagates untouched from the first attempt.

    An RPCError does NOT prove the call never arrived (deadline exceeded,
    connection reset after send): the retry may be the second delivery. A
    caller whose call is not idempotent has to cope with that — for the start
    in routes.py, see ``retried_start_is_ours``.
    """
    for attempt in (1, 2):
        try:
            client = await get_temporal_client()
        except Exception as exc:
            reset_temporal_client()
            if attempt == 2:
                raise
            logger.warning("Temporal connect failed (%r) — retrying once", exc)
            continue
        try:
            return await call(client)
        except RPCError as exc:
            reset_temporal_client()
            if attempt == 2:
                raise
            logger.warning(
                "Temporal call failed on the cached client (%r) — reconnecting and retrying once", exc
            )
    raise AssertionError("unreachable")  # pragma: no cover


async def retried_start_is_ours(workflow_id: str, job_id: str) -> bool:
    """After a RETRIED start was answered "already started": is that run ``job_id``'s?

    The retry is a new start call with a new request id, so when the first call
    reached the server and only its response was lost, the server rejects the
    retry because of the workflow this very job started. Treating that as a
    duplicate retired the job row of a paper that was being processed. Every
    start carries ``memo={JOB_ID_MEMO_KEY: job_id}``; only a different (or
    missing — a run started before the memo existed) job id is a real duplicate.

    If the memo cannot be read either, the answer is True: a workflow for this
    paper IS running, and right after a lost start response it is almost
    certainly this job's. A wrongly kept row is failed by the stale-job reaper;
    a wrongly retired one shows the user a failure for a paper in progress.
    """

    async def _memo_job_id(client: Client) -> str | None:
        description = await client.get_workflow_handle(workflow_id).describe()
        return (await description.memo()).get(JOB_ID_MEMO_KEY)

    try:
        owner = await call_with_reconnect(_memo_job_id)
    except Exception as exc:
        logger.warning(
            "Ownership of running workflow %s could not be confirmed (%r) — keeping job %s",
            workflow_id, exc, job_id,
        )
        return True
    return owner == job_id
