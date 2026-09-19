"""
Environment for subprocesses that execute LLM-generated Manim code.

Both the dry-run gate (agents/render_tester.py) and the real render
(rendering/local_runner.py) run code an LLM wrote — steered by the text of an
arbitrary arXiv paper — so neither child may inherit the parent's secrets.

This is a DENY-list on purpose. LaTeX, ffmpeg, fontconfig, pango and manim read
an unpredictable set of ordinary variables (PATH, HOME, LANG, TMPDIR, XDG_*,
TEXMF*, VIRTUAL_ENV, LD_LIBRARY_PATH, ...); an allow-list that misses one
breaks real renders, and CI never renders video so nothing would catch it.
Everything that is not recognisably secret-bearing passes through untouched.

Not a sandbox: the child still runs as the same user in the same container.
This only removes credentials from the one place generated code can trivially
read them (``os.environ``).
"""

import os
from collections.abc import Mapping

# Whole families that carry credentials or internal topology. IDENTITY_/MSI_
# are injected by Azure Container Apps for the system-assigned identity.
SECRET_ENV_PREFIXES = (
    "AZURE_",
    "S3_",
    "LANGFUSE_",
    "DEDALUS_",
    "POSTHOG_",
    "APPLICATIONINSIGHTS_",
    "TURNSTILE_",
    "IP_HASH_",
    "TEMPORAL_",
    "RENDER_API_",
    "OTEL_EXPORTER_",
    "IDENTITY_",
    "MSI_",
)
# Any name containing one of these is treated as a credential, whatever its
# prefix (OPENAI_API_KEY, MODAL_TOKEN_ID, GITHUB_TOKEN, ...).
SECRET_ENV_NAME_PARTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CONNECTION_STRING")
SECRET_ENV_NAMES = ("DATABASE_URL",)


def is_secret_env_name(name: str) -> bool:
    """True when an environment variable NAME looks secret-bearing."""
    upper = name.upper()
    return (
        upper.startswith(SECRET_ENV_PREFIXES)
        or upper in SECRET_ENV_NAMES
        or any(part in upper for part in SECRET_ENV_NAME_PARTS)
    )


def scrubbed_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy of ``environ`` (default ``os.environ``) without secret-bearing names.

    Callers re-add, explicitly, the few credentials their child really needs.
    """
    source = os.environ if environ is None else environ
    return {name: value for name, value in source.items() if not is_secret_env_name(name)}
