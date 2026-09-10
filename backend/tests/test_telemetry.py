"""Application Insights bootstrap + Langfuse isolation (backend/telemetry.py).

Hermetic: the Azure Monitor distro and the Langfuse client are faked; the
OpenTelemetry SDK itself is real (it ships with langfuse) so the provider and
sampler behaviour under test is the behaviour production gets.
"""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, TraceIdRatioBased

import telemetry

FAKE_CONNECTION_STRING = (
    "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://localhost:1/"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setattr(telemetry, "_configured", False)
    for var in (
        "APPLICATIONINSIGHTS_CONNECTION_STRING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
        "LANGFUSE_TRACING_ENVIRONMENT", "LANGFUSE_RELEASE", "LANGFUSE_SAMPLE_RATE",
    ):
        monkeypatch.delenv(var, raising=False)
    # conftest disables Langfuse export for the suite; tests opt back in explicitly.
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    yield
    telemetry._configured = False


@pytest.fixture
def distro(monkeypatch):
    """Replace configure_azure_monitor; records the kwargs it was called with."""
    import azure.monitor.opentelemetry as amo

    calls: list[dict] = []

    def _fake(**kwargs):
        calls.append(kwargs)
    monkeypatch.setattr(amo, "configure_azure_monitor", _fake)
    return calls


# --- configure(): NO-OP without the connection string ------------------------

class TestConfigure:
    def test_noop_when_unset(self, distro):
        assert telemetry.app_insights_enabled() is False
        assert telemetry.configure() is False
        assert distro == []

    def test_configures_distro_once_with_live_metrics_off(self, distro, monkeypatch):
        monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", FAKE_CONNECTION_STRING)
        assert telemetry.configure() is True
        assert distro == [{"enable_live_metrics": False}]
        assert telemetry.configure() is False  # once per process
        assert len(distro) == 1

    def test_distro_failure_is_contained(self, monkeypatch):
        import azure.monitor.opentelemetry as amo

        def _boom(**kwargs):
            raise ValueError("bad connection string")
        monkeypatch.setattr(amo, "configure_azure_monitor", _boom)
        monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "garbage")
        assert telemetry.configure() is False
        assert telemetry._configured is False

    def test_isolates_langfuse_only_when_langfuse_is_on(self, distro, monkeypatch):
        monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", FAKE_CONNECTION_STRING)
        isolated: list[bool] = []
        monkeypatch.setattr(telemetry, "isolate_langfuse", lambda: isolated.append(True) or True)
        telemetry.configure()
        assert isolated == []  # no Langfuse keys -> nothing to isolate

        telemetry._configured = False
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
        telemetry.configure()
        assert isolated == [True]


class TestLangfuseEnabled:
    def test_needs_both_keys(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        assert telemetry.langfuse_enabled() is False
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        assert telemetry.langfuse_enabled() is True

    def test_respects_kill_switch(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
        assert telemetry.langfuse_enabled() is False


# --- the isolated provider ---------------------------------------------------

class TestLangfuseTracerProvider:
    def test_is_not_the_global_provider_and_always_on(self):
        provider = telemetry.langfuse_tracer_provider()
        assert isinstance(provider, TracerProvider)
        assert trace.get_tracer_provider() is not provider
        assert provider.sampler is ALWAYS_ON

    def test_carries_environment_and_release(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "production")
        monkeypatch.setenv("LANGFUSE_RELEASE", "gh-abc123")
        attrs = telemetry.langfuse_tracer_provider().resource.attributes
        assert attrs["langfuse.environment"] == "production"
        assert attrs["langfuse.release"] == "gh-abc123"

    def test_honours_langfuse_sample_rate(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "0.25")
        sampler = telemetry.langfuse_tracer_provider().sampler
        assert isinstance(sampler, TraceIdRatioBased)
        assert sampler.rate == 0.25

    def test_full_or_garbage_sample_rate_stays_always_on(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "1.0")
        assert telemetry.langfuse_tracer_provider().sampler is ALWAYS_ON
        monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "lots")
        assert telemetry.langfuse_tracer_provider().sampler is ALWAYS_ON

    def test_records_under_a_foreign_parent_that_was_sampled_out(self):
        # The App Insights provider dropped the request span (sampled=false).
        # Langfuse's own default, ParentBased(ALWAYS_ON), would inherit that
        # drop; the isolated provider must not.
        azure_like = TracerProvider(sampler=ALWAYS_OFF)
        parent = azure_like.get_tracer("azure").start_span("GET /api/process")
        assert not parent.is_recording()
        with trace.use_span(parent):
            child = telemetry.langfuse_tracer_provider().get_tracer("langfuse-sdk").start_span("llm")
        assert child.is_recording()
        child.end()
        parent.end()


# --- binding the Langfuse client ---------------------------------------------

class _FakeResources:
    def __init__(self, tracer_provider):
        self.tracer_provider = tracer_provider
        self.score_calls: list[tuple[dict, bool]] = []

    def add_score_task(self, event, *, force_sample=False):
        self.score_calls.append((event, force_sample))


class TestIsolateLangfuse:
    def test_binds_isolated_provider_and_forces_score_sampling(self, monkeypatch):
        import langfuse

        instances: list = []

        class FakeLangfuse:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self._resources = _FakeResources(kwargs["tracer_provider"])
                instances.append(self)
        monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)

        assert telemetry.isolate_langfuse() is True
        (client,) = instances
        provider = client.kwargs["tracer_provider"]
        assert isinstance(provider, TracerProvider)
        assert trace.get_tracer_provider() is not provider
        assert provider.sampler is ALWAYS_ON

        # Score sampling no longer follows the global (Azure) sampler.
        client._resources.add_score_task({"type": "score-create"})
        assert client._resources.score_calls == [({"type": "score-create"}, True)]

    def test_detects_a_client_created_too_early(self, monkeypatch):
        import langfuse

        stale = TracerProvider()

        class AlreadyInitialised:
            def __init__(self, **kwargs):
                self._resources = _FakeResources(stale)  # singleton kept its provider
        monkeypatch.setattr(langfuse, "Langfuse", AlreadyInitialised)
        assert telemetry.isolate_langfuse() is False

    def test_constructor_failure_is_contained(self, monkeypatch):
        import langfuse

        class Broken:
            def __init__(self, **kwargs):
                raise RuntimeError("no keys")
        monkeypatch.setattr(langfuse, "Langfuse", Broken)
        assert telemetry.isolate_langfuse() is False


# --- detached context --------------------------------------------------------

class TestDetachedTraceContext:
    def test_body_runs_with_no_current_span_and_restores_it(self):
        provider = TracerProvider(sampler=ALWAYS_ON)
        request_span = provider.get_tracer("azure").start_span("POST /api/process")
        with trace.use_span(request_span):
            assert trace.get_current_span() is request_span
            with telemetry.detached_trace_context():
                assert trace.get_current_span() is trace.INVALID_SPAN
                root = provider.get_tracer("langfuse-sdk").start_span("process-paper")
                assert root.parent is None  # a real trace root, not a child of the request
                root.end()
            assert trace.get_current_span() is request_span
        request_span.end()
