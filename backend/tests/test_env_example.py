"""backend/.env.example is what every fresh local setup copies.

It shipped with ``RENDER_MODE=modal`` as an ACTIVE line, pointing at a Modal
app that was never deployed: every render failed and the local RenderTester
gate (disabled under modal) was off from the first run.
"""

import re
from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def _lines() -> list[str]:
    return ENV_EXAMPLE.read_text().splitlines()


def _active() -> dict[str, str]:
    pairs = (line.split("=", 1) for line in _lines() if line and not line.startswith("#") and "=" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def _documented() -> set[str]:
    """Every variable the template names, active or commented out."""
    return {m.group(1) for line in _lines() if (m := re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=", line))}


def test_local_rendering_is_the_default_and_modal_is_not_active():
    active = _active()
    assert active.get("RENDER_MODE") == "local"
    assert not [key for key in active if key.startswith("MODAL_")]


def test_the_settings_a_deployment_needs_are_documented():
    expected = {
        "DATABASE_URL", "USE_TEMPORAL", "TEMPORAL_ADDRESS", "TEMPORAL_NAMESPACE", "TEMPORAL_TLS",
        "ENABLE_VISUAL_QA", "VISUAL_QA_REPAIR", "RENDER_API_SECRET", "ENVIRONMENT",
        "RENDER_CONCURRENCY", "APP_COMMIT_SHA",
    }
    assert expected <= _documented(), sorted(expected - _documented())


def test_secret_bearing_entries_are_placeholders_or_commented():
    # Active lines may only carry obvious placeholders; everything else secret
    # stays commented out so a copied .env never contains a plausible value.
    active = _active()
    assert active["AZURE_OPENAI_API_KEY"].startswith("your-")
    for key in ("DATABASE_URL", "S3_SECRET_KEY", "LANGFUSE_SECRET_KEY", "RENDER_API_SECRET", "TURNSTILE_SECRET_KEY"):
        assert key not in active


def test_the_stale_example_domain_is_gone():
    assert "arxiviz.org" not in ENV_EXAMPLE.read_text()
