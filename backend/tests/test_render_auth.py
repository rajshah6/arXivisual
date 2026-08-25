"""Tests for the POST /api/render authorization guard.

The endpoint executes caller-supplied Python, so it must be unreachable in
production without an explicit shared secret, while staying open in dev.
"""

import pytest
from fastapi import HTTPException

from api.routes import _authorize_render


def test_dev_allows_render_without_secret(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)  # defaults to development
    _authorize_render(None)  # should not raise


def test_explicit_development_allows_render(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    _authorize_render(None)


def test_production_blocks_render_without_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RENDER_API_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        _authorize_render(None)
    # 404, not 403 — don't advertise the endpoint's existence.
    assert exc.value.status_code == 404


def test_production_blocks_render_with_wrong_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER_API_SECRET", "correct-horse")
    with pytest.raises(HTTPException) as exc:
        _authorize_render("wrong")
    assert exc.value.status_code == 404


def test_production_allows_render_with_matching_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER_API_SECRET", "correct-horse")
    _authorize_render("correct-horse")  # should not raise


def test_production_rejects_near_miss_secret(monkeypatch):
    # Exercises the timing-safe hmac.compare_digest path + the None guard.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RENDER_API_SECRET", "correct-horse")
    with pytest.raises(HTTPException):
        _authorize_render("correct-hors")  # one char short
    with pytest.raises(HTTPException):
        _authorize_render(None)


def test_production_without_secret_configured_stays_closed(monkeypatch):
    # If no secret is configured in prod, the endpoint is fully disabled even
    # if a caller sends some header value.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RENDER_API_SECRET", raising=False)
    with pytest.raises(HTTPException):
        _authorize_render("anything")
