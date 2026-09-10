"""CORS allow-list: the fixed production origins plus whatever
``CORS_EXTRA_ORIGINS`` names (comma-separated), so a new frontend host (the
Azure Container Apps FQDN during the Vercel cut-over, a staging host later)
can be admitted by config instead of a code change and redeploy."""

from api.cors import DEFAULT_ORIGINS, allowed_origins


def test_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("CORS_EXTRA_ORIGINS", raising=False)
    assert allowed_origins() == list(DEFAULT_ORIGINS)
    assert "https://arxivisual.org" in DEFAULT_ORIGINS
    assert "https://www.arxivisual.org" in DEFAULT_ORIGINS
    assert "http://localhost:3000" in DEFAULT_ORIGINS


def test_extra_origins_appended_trimmed_and_deduped(monkeypatch):
    monkeypatch.setenv(
        "CORS_EXTRA_ORIGINS",
        " https://arxivisual-web.example.azurecontainerapps.io/ ,, https://arxivisual.org , http://localhost:3001",
    )
    origins = allowed_origins()
    assert origins[: len(DEFAULT_ORIGINS)] == list(DEFAULT_ORIGINS)
    # trailing slash stripped (an Origin header never carries one), blanks
    # dropped, a duplicate of a default not repeated
    assert origins[len(DEFAULT_ORIGINS) :] == [
        "https://arxivisual-web.example.azurecontainerapps.io",
        "http://localhost:3001",
    ]


def test_extra_origin_must_be_an_origin_not_a_url(monkeypatch):
    # A path or wildcard is a misconfiguration that would silently never
    # match a browser Origin header — refuse it loudly rather than ship a
    # CORS policy that looks configured but is not.
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", "https://good.example, https://bad.example/app")
    try:
        allowed_origins()
    except ValueError as e:
        assert "https://bad.example/app" in str(e)
    else:
        raise AssertionError("expected ValueError for an origin with a path")
