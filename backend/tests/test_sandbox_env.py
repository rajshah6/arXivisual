"""The subprocesses that execute LLM-generated Manim code must not inherit secrets.

The real render used ``dict(os.environ)`` — database URL, storage keys, the
Langfuse secret, the Temporal address — while the dry-run gate already
scrubbed by prefix. Both now share ``rendering.sandbox_env``: a DENY-list (an
allow-list would break LaTeX/ffmpeg/fontconfig, which CI cannot catch), after
which the runner re-adds only the OpenAI-compatible TTS credentials.
"""

import asyncio
import subprocess
import sys

import pytest

import agents.render_tester as rt_module
from agents.render_tester import RenderTester
from rendering import local_runner
from rendering.sandbox_env import is_secret_env_name, scrubbed_env

SECRET_ENV = {
    "AZURE_OPENAI_API_KEY": "azure-secret",
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
    "S3_ACCESS_KEY": "s3-access",
    "S3_SECRET_KEY": "s3-secret",
    "S3_ENDPOINT": "https://r2.example.com",
    "LANGFUSE_SECRET_KEY": "lf-secret",
    "LANGFUSE_PUBLIC_KEY": "lf-public",
    "DEDALUS_API_KEY": "dedalus",
    "POSTHOG_API_KEY": "phc",
    "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=abc",
    "TURNSTILE_SECRET_KEY": "turnstile",
    "IP_HASH_SECRET": "salt",
    "TEMPORAL_ADDRESS": "temporal.internal:443",
    "RENDER_API_SECRET": "render-secret",
    "OTEL_EXPORTER_OTLP_HEADERS": "authorization=Bearer x",
    "DATABASE_URL": "postgresql+asyncpg://user:pw@db/arxiviz",
    # Injected by Container Apps for the system-assigned identity (AcrPull).
    "IDENTITY_HEADER": "msi-header",
    "IDENTITY_ENDPOINT": "http://localhost:42356/msi/token",
    "MSI_SECRET": "msi-secret",
    # Name-pattern matches with no known prefix.
    "MODAL_TOKEN_ID": "ak-x",
    "GITHUB_TOKEN": "ghp_x",
    "SOME_VENDOR_PASSWORD": "pw",
    "STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https",
    "my_api_key": "lowercase-still-secret",
}

# What a render genuinely needs: an unpredictable, ordinary set.
ORDINARY_ENV = {
    "PATH": "/usr/local/bin:/usr/bin",
    "HOME": "/home/app",
    "LANG": "C.UTF-8",
    "TMPDIR": "/tmp",
    "XDG_CACHE_HOME": "/home/app/.cache",
    "TEXMFVAR": "/home/app/.texmf-var",
    "VIRTUAL_ENV": "/app/.venv",
    "LD_LIBRARY_PATH": "/usr/local/lib",
    "FONTCONFIG_PATH": "/etc/fonts",
    "VOICEOVER_TTS_SERVICE": "openai",
    "VOICEOVER_VOICE_NAME": "nova",
    "VOICEOVER_CACHE_DIR": "/tmp/arxivisual-tts-cache",
    "RENDER_CONCURRENCY": "3",
}


@pytest.fixture()
def full_env(monkeypatch):
    for name, value in {**SECRET_ENV, **ORDINARY_ENV}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)


class TestScrubbedEnv:
    @pytest.mark.parametrize("name", sorted(SECRET_ENV))
    def test_secret_bearing_names_are_dropped(self, full_env, name):
        assert is_secret_env_name(name)
        assert name not in scrubbed_env()

    @pytest.mark.parametrize("name", sorted(ORDINARY_ENV))
    def test_ordinary_names_survive(self, full_env, name):
        assert scrubbed_env()[name] == ORDINARY_ENV[name]

    def test_no_secret_value_survives_under_any_name(self, full_env):
        assert not set(SECRET_ENV.values()) & set(scrubbed_env().values())

    def test_explicit_mapping_is_not_mutated(self):
        source = {"PATH": "/bin", "DATABASE_URL": "postgresql://x"}
        assert scrubbed_env(source) == {"PATH": "/bin"}
        assert "DATABASE_URL" in source


class TestRenderSubprocessEnv:
    def test_secrets_are_absent_and_tts_mapping_is_present(self, full_env):
        env = local_runner._tts_subprocess_env()

        for name in SECRET_ENV:
            assert name not in env, name
        # The one credential the render needs: Azure's OpenAI-compatible TTS.
        assert env["OPENAI_API_KEY"] == "azure-secret"
        assert env["OPENAI_BASE_URL"] == "https://example.openai.azure.com/openai/v1/"
        assert env["OPENAI_API_TYPE"] == "openai"
        # ...and nothing else secret rode along with it.
        leaked = set(SECRET_ENV.values()) - {"azure-secret"}
        assert not leaked & set(env.values())

    def test_path_home_and_voiceover_settings_are_preserved(self, full_env):
        env = local_runner._tts_subprocess_env()
        for name, value in ORDINARY_ENV.items():
            assert env[name] == value

    def test_existing_openai_key_is_respected(self, full_env, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "real-openai-key")
        env = local_runner._tts_subprocess_env()
        assert env["OPENAI_API_KEY"] == "real-openai-key"
        assert "OPENAI_BASE_URL" not in env

    def test_no_tts_credentials_means_no_openai_key(self, full_env, monkeypatch):
        monkeypatch.delenv("AZURE_OPENAI_API_KEY")
        env = local_runner._tts_subprocess_env()
        assert "OPENAI_API_KEY" not in env

    def test_render_subprocess_receives_the_scrubbed_env(self, full_env, monkeypatch, tmp_path):
        # The env handed to subprocess.run is the contract — assert on the
        # real call rather than on the helper alone.
        seen = {}

        def fake_run(cmd, **kwargs):
            seen.update(kwargs["env"])
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        monkeypatch.setenv("VOICEOVER_CACHE_DIR", str(tmp_path / "tts-cache"))
        monkeypatch.setattr(local_runner.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError):
            local_runner._run_manim_subprocess("from manim import *\n", "S", "low_quality")

        assert seen["PATH"] == ORDINARY_ENV["PATH"]
        assert seen["OPENAI_API_KEY"] == "azure-secret"
        for name in SECRET_ENV:
            assert name not in seen, name


class TestDryRunGateEnv:
    # Both gate modes: RENDER_TEST_EXECUTE=0 (import-only) once imported the
    # generated module inside the worker process, bypassing the scrub entirely.
    @pytest.mark.parametrize("execute_flag, import_only", [("1", False), ("0", True)])
    def test_dry_run_child_gets_the_shared_scrub_and_a_placeholder_key(
        self, full_env, monkeypatch, execute_flag, import_only,
    ):
        seen, cmds = {}, []

        def fake_run(cmd, **kwargs):
            cmds.append(cmd)
            seen.update(kwargs["env"])
            return subprocess.CompletedProcess(cmd, 0, stdout=rt_module.SENTINEL_OK, stderr="")

        monkeypatch.setenv("OPENAI_API_KEY", "real-openai-key")
        monkeypatch.setenv("RENDER_TEST_EXECUTE", execute_flag)
        monkeypatch.setattr(rt_module.subprocess, "run", fake_run)
        result = asyncio.run(RenderTester(timeout_seconds=5).test_render(
            "from manim import *\nclass S(Scene):\n    def construct(self):\n        pass\n"
        ))

        assert result.success
        # One subprocess per check, in either mode — never an in-process import.
        assert len(cmds) == 1 and (rt_module.IMPORT_ONLY_FLAG in cmds[0]) is import_only
        for name in SECRET_ENV:
            assert name not in seen, name
        # No real credential reaches the dry run — not even the TTS one.
        assert seen["OPENAI_API_KEY"] == "dry-run-placeholder"
        assert seen["PATH"] == ORDINARY_ENV["PATH"]
        assert seen["HOME"] == ORDINARY_ENV["HOME"]


def test_a_real_child_process_cannot_see_the_secrets(full_env):
    # End to end through the OS: spawn a child with the render env and have it
    # report what it can read.
    probe = "import os, json; print(json.dumps(sorted(os.environ)))"
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, timeout=60,
        env=local_runner._tts_subprocess_env(),
    )
    assert out.returncode == 0, out.stderr
    import json

    names = set(json.loads(out.stdout))
    assert not names & set(SECRET_ENV)
    assert {"PATH", "HOME", "OPENAI_API_KEY"} <= names
