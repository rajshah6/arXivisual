"""CORS allow-list: the fixed production origins plus whatever
``CORS_EXTRA_ORIGINS`` names (comma-separated), so a new frontend host (the
frontend Container App's own FQDN, a staging host) can be admitted by config
instead of a code change and redeploy."""

import pytest

from api.cors import DEFAULT_ORIGINS, allowed_origins, canonical_origin


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


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        # CORSMiddleware matches by string equality, so entries must be
        # spelled exactly as a browser sends the Origin header.
        ("HTTPS://Web.Example.ORG", "https://web.example.org"),
        ("https://web.example.org:443", "https://web.example.org"),
        ("http://web.example.org:80", "http://web.example.org"),
        ("https://web.example.org:8443", "https://web.example.org:8443"),
        ("http://[::1]:3000", "http://[::1]:3000"),
    ],
)
def test_entries_are_canonicalized_like_a_browser_origin(entry, expected):
    assert canonical_origin(entry) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "https://bad.example/app",  # path
        "https://bad.example/?x=1",  # query
        "https://bad.example/#frag",  # fragment
        "https://user:pw@bad.example",  # userinfo
        "https://bad.example:notaport",  # non-numeric port
        "ftp://bad.example",  # scheme browsers never send as an origin
        "bad.example",  # no scheme
        "*",  # allow-all — with allow_credentials=True this would be a hole
        "https://*.example.org",
    ],
)
def test_non_origins_are_refused_loudly(bad, monkeypatch):
    # A misconfiguration must fail at startup, not ship a policy that looks
    # configured while matching nothing (or matching everything).
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", f"https://good.example, {bad}")
    with pytest.raises(ValueError) as excinfo:
        allowed_origins()
    assert bad in str(excinfo.value)
