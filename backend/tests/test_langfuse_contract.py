"""Contract test: the PRIVATE Langfuse internals telemetry.py depends on.

``telemetry.isolate_langfuse`` reaches into the SDK twice:

* ``client._resources.tracer_provider`` — to prove the client really bound the
  isolated TracerProvider (the resource manager is a per-public-key singleton;
  a client created too early keeps the global, App Insights, provider);
* ``resources.add_score_task(event, *, force_sample)`` — overridden per
  instance so scores are not sampled by Azure's sampler.

tests/test_telemetry.py fakes the Langfuse class, so an SDK release that renames
either would sail through CI and degrade production silently (both call sites
are getattr-guarded: they log and carry on). This file asserts against the
REAL installed package — it is what a Dependabot langfuse bump has to pass.

Hermetic: nothing is traced or scored, the base URL is a closed local port, and
every socket connect during the test is recorded and must be empty.

Note: the provider is only bound when tracing is ENABLED (with
``tracing_enabled=False`` the 4.x resource manager leaves ``tracer_provider``
as None), and tests/conftest.py exports LANGFUSE_TRACING_ENABLED=false — so
these tests switch it back on for themselves.
"""

import inspect
import socket
import uuid

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

import telemetry

CLOSED_LOCAL_PORT = "http://127.0.0.1:9"


class _NullExporter(SpanExporter):
    def export(self, spans):
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None


@pytest.fixture()
def no_network(monkeypatch):
    attempts: list = []

    def _refuse(self, address):
        attempts.append(address)
        raise OSError(f"network is off in the Langfuse contract test: {address}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    yield attempts
    assert attempts == [], f"the contract test touched the network: {attempts}"


@pytest.fixture()
def langfuse_env(monkeypatch):
    """A unique public key per test: the resource manager is a per-key singleton."""
    public_key = f"pk-lf-contract-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")  # conftest turns it off
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", public_key)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-contract")
    monkeypatch.setenv("LANGFUSE_HOST", CLOSED_LOCAL_PORT)
    monkeypatch.setenv("LANGFUSE_BASE_URL", CLOSED_LOCAL_PORT)
    yield public_key

    from langfuse._client.resource_manager import LangfuseResourceManager

    instance = LangfuseResourceManager._instances.pop(public_key, None)
    if instance is not None:
        instance.shutdown()


def test_add_score_task_still_takes_event_and_keyword_only_force_sample():
    from langfuse._client.resource_manager import LangfuseResourceManager

    parameters = inspect.signature(LangfuseResourceManager.add_score_task).parameters
    assert list(parameters)[:2] == ["self", "event"]
    assert "force_sample" in parameters, "telemetry._force_score_sampling passes force_sample=True"
    assert parameters["force_sample"].kind is inspect.Parameter.KEYWORD_ONLY
    # Exactly the call telemetry.py makes must bind.
    inspect.signature(LangfuseResourceManager.add_score_task).bind(object(), {"type": "score-create"}, force_sample=True)


def test_constructor_still_accepts_a_tracer_provider():
    from langfuse import Langfuse

    assert "tracer_provider" in inspect.signature(Langfuse.__init__).parameters


def test_client_binds_the_tracer_provider_it_is_given(langfuse_env, no_network):
    from langfuse import Langfuse

    provider = TracerProvider()
    client = Langfuse(
        public_key=langfuse_env, secret_key="sk-lf-contract", base_url=CLOSED_LOCAL_PORT,
        tracer_provider=provider, tracing_enabled=True, span_exporter=_NullExporter(),
    )

    resources = client._resources
    assert resources is not None, "Langfuse._resources is gone or unset"
    assert resources.tracer_provider is provider
    assert callable(resources.add_score_task)


def test_isolate_langfuse_succeeds_against_the_real_sdk(langfuse_env, no_network, caplog):
    # The whole private-API path at once: if either attribute moved,
    # isolate_langfuse() returns False (it only logs) and this fails.
    with caplog.at_level("INFO", logger=telemetry.logger.name):
        assert telemetry.isolate_langfuse() is True
    assert "Langfuse tracing isolated" in caplog.text

    from langfuse import get_client

    resources = get_client(public_key=langfuse_env)._resources
    # Same singleton every later get_client()/@observe call will reuse, with
    # the instance-level score override installed on it.
    assert "add_score_task" in vars(resources)
    assert resources.add_score_task.__name__ == "_always_in_sample"
