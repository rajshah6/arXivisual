"""Temporal worker entrypoint.

Runs two workers on one event loop:
- ``paper-pipeline``: the workflow plus the light activities (ingest, generate,
  progress, finalize). Generation is LLM-bound, not CPU-bound, so modest
  concurrency is fine.
- ``paper-render``: the CPU-heavy render activity only, capped at
  RENDER_CONCURRENCY (same knob as the legacy path). Temporal server queues any
  surplus renders — backpressure without shared semaphores.

Deployed as its own Container App (same image as the API, different command),
which also moves rendering OFF the API container — /api/status polling no
longer competes with ffmpeg for CPU.

Run: python -m temporal_app.worker  (from /app inside the container)
Env: TEMPORAL_ADDRESS (host:port), TEMPORAL_NAMESPACE (default "default").
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Application Insights (no-op without APPLICATIONINSIGHTS_CONNECTION_STRING).
# Before the activity/agent imports so Langfuse is bound to its own
# TracerProvider before any client exists (see telemetry.py).
import telemetry

telemetry.configure()

from temporalio.client import Client
from temporalio.worker import Worker

import analytics
from jobs.worker import parse_render_concurrency
from temporal_app.activities import (
    finalize_job,
    generate_visualizations_for_paper,
    ingest_paper,
    mark_job_failed,
    record_render_failure,
    render_visualization,
    repair_visualization_code,
    update_render_progress,
)
from temporal_app.workflows import RENDER_TASK_QUEUE, TASK_QUEUE, PaperPipelineWorkflow

# Module-level so a test can assert every activity the workflow references is
# registered: an activity invoked but not registered fails with NotFoundError
# at runtime, and once that sank whole jobs in the render-failure fallback.
PIPELINE_ACTIVITIES = [
    ingest_paper,
    generate_visualizations_for_paper,
    update_render_progress,
    finalize_job,
    mark_job_failed,
    repair_visualization_code,
    record_render_failure,
]
RENDER_ACTIVITIES = [render_visualization]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    render_concurrency = parse_render_concurrency()

    use_tls = os.getenv("TEMPORAL_TLS", "0") == "1"
    logger.info(
        "Connecting to Temporal at %s (namespace=%s, tls=%s)", address, namespace, use_tls
    )
    # Container Apps fronts gRPC with HTTP/2 ingress behind TLS (:443);
    # raw TCP ingress proved unroutable on this environment.
    # Retry the connect: during a revision rollover the first attempt failed
    # (exit 1, container restarted by the platform 10s later). Exiting on a
    # transient gRPC error just adds a restart to every deploy.
    client = None
    for attempt in range(1, 7):
        try:
            client = await Client.connect(address, namespace=namespace, tls=use_tls)
            break
        except Exception as exc:
            if attempt == 6:
                raise
            logger.warning("Temporal connect attempt %d failed (%s); retrying in %ds", attempt, exc, 5 * attempt)
            await asyncio.sleep(5 * attempt)
    logger.info("Connected. Render concurrency: %d", render_concurrency)

    # Backpressure: observed in production that unbounded concurrent
    # generations (each fanning out 5 LLM tasks + render tests) starve each
    # other on the shared box until the activity timeout fires. Two papers
    # generating at once is the sweet spot for this host; the rest queue on the
    # Temporal server — which is exactly what it's for.
    pipeline_concurrency = max(1, int(os.getenv("PIPELINE_CONCURRENCY", "2")))
    pipeline_worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[PaperPipelineWorkflow],
        activities=PIPELINE_ACTIVITIES,
        max_concurrent_activities=pipeline_concurrency,
    )
    render_worker = Worker(
        client,
        task_queue=RENDER_TASK_QUEUE,
        activities=RENDER_ACTIVITIES,
        max_concurrent_activities=render_concurrency,
    )

    logger.info(
        "Workers running: %s (pipeline), %s (render, max %d concurrent)",
        TASK_QUEUE, RENDER_TASK_QUEUE, render_concurrency,
    )
    try:
        await asyncio.gather(pipeline_worker.run(), render_worker.run())
    finally:
        # Flush queued product events before the process goes away.
        analytics.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
