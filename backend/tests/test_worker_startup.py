"""Entry points configure logging BEFORE telemetry.

``telemetry.configure()`` reports what it did with logger.info ("Application
Insights telemetry on", "Langfuse tracing isolated ..."). The worker called it
before ``logging.basicConfig``, so the root logger was still at WARNING with no
handler and both confirmation lines were dropped — the only evidence that the
worker's tracing was set up correctly. main.py already had the right order.
"""

import ast
import logging
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _top_level_call_lines(path: Path) -> dict[str, int]:
    """Line of each top-level ``a.b(...)`` expression/assignment call in a module."""
    lines: dict[str, int] = {}
    for node in ast.parse(path.read_text()).body:
        value = getattr(node, "value", None)
        if isinstance(node, ast.Expr | ast.Assign) and isinstance(value, ast.Call):
            lines.setdefault(ast.unparse(value.func), node.lineno)
    return lines


@pytest.mark.parametrize("entrypoint", ["main.py", "temporal_app/worker.py"])
def test_logging_is_configured_before_telemetry(entrypoint):
    calls = _top_level_call_lines(BACKEND_ROOT / entrypoint)
    assert "logging.basicConfig" in calls and "telemetry.configure" in calls
    assert calls["logging.basicConfig"] < calls["telemetry.configure"]


def test_worker_logs_the_deployed_commit_at_startup(monkeypatch, caplog):
    from temporal_app import worker

    monkeypatch.setenv("APP_COMMIT_SHA", "21baa13deadbeef")
    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        worker.log_startup()
    assert "commit=21baa13deadbeef" in caplog.text

    caplog.clear()
    monkeypatch.delenv("APP_COMMIT_SHA")
    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        worker.log_startup()
    assert "commit=unknown" in caplog.text
