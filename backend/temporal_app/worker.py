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

from temporalio.client import Client
from temporalio.worker import Worker

from temporal_app.activities import (
    finalize_job,
    generate_visualizations_for_paper,
    ingest_paper,
    mark_job_failed,
    render_visualization,
    update_render_progress,
)
from temporal_app.workflows import RENDER_TASK_QUEUE, TASK_QUEUE, PaperPipelineWorkflow
from jobs.worker import parse_render_concurrency

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
    client = await Client.connect(address, namespace=namespace, tls=use_tls)
    logger.info("Connected. Render concurrency: %d", render_concurrency)

    pipeline_worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[PaperPipelineWorkflow],
        activities=[
            ingest_paper,
            generate_visualizations_for_paper,
            update_render_progress,
            finalize_job,
            mark_job_failed,
        ],
    )
    render_worker = Worker(
        client,
        task_queue=RENDER_TASK_QUEUE,
        activities=[render_visualization],
        max_concurrent_activities=render_concurrency,
    )

    logger.info(
        "Workers running: %s (pipeline), %s (render, max %d concurrent)",
        TASK_QUEUE, RENDER_TASK_QUEUE, render_concurrency,
    )
    await asyncio.gather(pipeline_worker.run(), render_worker.run())


if __name__ == "__main__":
    asyncio.run(main())
