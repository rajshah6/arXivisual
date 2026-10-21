"""SIGTERM drains both Temporal workers instead of being ignored by PID 1."""

import asyncio
import os
import signal
from datetime import timedelta

import pytest

from temporal_app import worker as worker_module


class FakeWorker:
    def __init__(self) -> None:
        self.shutdown_calls = 0
        self.finished = asyncio.Event()

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.finished.set()


async def _send_and_settle(sig: signal.Signals) -> None:
    os.kill(os.getpid(), sig)
    # Let the signal handler and the shutdown tasks it schedules run.
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
async def test_signal_drains_every_worker_once(sig):
    loop = asyncio.get_running_loop()
    workers = [FakeWorker(), FakeWorker()]
    worker_module.install_shutdown_handlers(loop, workers, signals=(sig,))
    try:
        await _send_and_settle(sig)
        await asyncio.wait_for(asyncio.gather(*(w.finished.wait() for w in workers)), 2)
        # A repeated signal must not start a second drain.
        await _send_and_settle(sig)
        assert [w.shutdown_calls for w in workers] == [1, 1]
    finally:
        loop.remove_signal_handler(sig)


def test_drain_fits_inside_the_container_grace_period():
    # infra/container_apps.tf gives the worker 600 s before SIGKILL; the drain
    # must give up before that, or the platform kills renders anyway.
    assert timedelta(0) < worker_module.GRACEFUL_SHUTDOWN < timedelta(seconds=600)


def test_main_passes_the_drain_timeout_to_both_workers(monkeypatch):
    built = []

    class RecordingWorker:
        def __init__(self, *args, **kwargs):
            built.append(kwargs)

        async def run(self):
            return None

        async def shutdown(self):
            return None

    class FakeClient:
        @staticmethod
        async def connect(*args, **kwargs):
            return object()

    monkeypatch.setattr(worker_module, "Worker", RecordingWorker)
    monkeypatch.setattr(worker_module, "Client", FakeClient)
    monkeypatch.setattr(worker_module.analytics, "shutdown", lambda: None)
    asyncio.run(worker_module.main())
    assert len(built) == 2
    assert all(kw["graceful_shutdown_timeout"] == worker_module.GRACEFUL_SHUTDOWN for kw in built)
