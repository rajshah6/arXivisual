"""Process-level telemetry bootstrap: Azure Application Insights next to Langfuse.

``configure()`` runs ONCE at process start — ``main.py`` (API) and
``temporal_app/worker.py`` (Temporal worker) call it before the FastAPI app or
the worker exists and before anything touches Langfuse. It is a NO-OP unless
``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set, so local dev and CI never
load the Azure Monitor distro.

Why Langfuse gets its own TracerProvider
----------------------------------------
Both integrations are OpenTelemetry-based and both want the process-global
TracerProvider:

* ``configure_azure_monitor`` builds a provider with the App Insights sampler
  (``OTEL_TRACES_SAMPLER`` / ``OTEL_TRACES_SAMPLER_ARG``) and exporter and
  registers it globally; the bundled FastAPI/httpx/requests/urllib3
  instrumentations only ever use that global provider
  (azure/monitor/opentelemetry/_configure.py:_setup_tracing).
* Langfuse, when no ``tracer_provider`` is passed, adopts an already-registered
  global provider as-is — sampler and exporters included
  (langfuse/_client/resource_manager.py:_init_tracer_provider).

Left alone, Langfuse would attach its span processor to Azure's provider:
every ``@observe`` span and every ``langfuse.openai`` generation — prompts and
completions included — would ALSO be exported to Application Insights
(ingestion cost, prompt data in a second store), and Azure's sampler would drop
most Langfuse spans before Langfuse saw them (at 20% sampling, 80% of LLM
traces vanish). Nothing flows the other way: Langfuse's default export filter
only forwards Langfuse/GenAI spans (langfuse/_client/span_filter.py).

So when App Insights is on, Langfuse is initialised eagerly on an isolated,
never-global TracerProvider whose sampler is ALWAYS_ON (``LANGFUSE_SAMPLE_RATE``
still applies) — the setup Langfuse documents for existing OTel installations
(https://langfuse.com/faq/all/existing-otel-setup). Every later
``get_client()`` / ``@observe`` / ``langfuse.openai`` call reuses that instance:
the resource manager is a per-public-key singleton.

Two Langfuse-side caveats remain, both handled here:

* OTel *context* is shared between providers, so a Langfuse span started inside
  an Azure request span would inherit it as parent — an orphan in Langfuse, and
  with a parent-based sampler it would inherit Azure's drop decision.
  ALWAYS_ON covers the sampling half; ``detached_trace_context()`` gives the
  legacy in-process pipeline (a Starlette background task, which runs INSIDE
  the request's ASGI span) a fresh root. The Temporal worker has no server
  spans to inherit.
* Langfuse samples *scores* with the GLOBAL provider's sampler
  (resource_manager.py:add_score_task) — Azure's, once it is registered.
  Scores are forced in-sample so ``visual_qa_defect`` keeps the same 100%
  coverage as the always-on Langfuse provider.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_configured = False


def app_insights_enabled() -> bool:
    """Application Insights is on iff a connection string is configured."""
    return bool(os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"))


def langfuse_enabled() -> bool:
    """Same rule as agents/base.py (both keys) plus the tests' kill switch."""
    keys = bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))
    disabled = os.environ.get("LANGFUSE_TRACING_ENABLED", "true").strip().lower() in ("false", "0")
    return keys and not disabled


def configure() -> bool:
    """Wire Application Insights (and isolate Langfuse from it) once per process.

    Returns True when the distro was configured on this call. A broken
    connection string logs and returns False rather than crash-looping the
    app: telemetry must never take the site down.
    """
    global _configured  # noqa: PLW0603 — once-per-process guard
    if _configured or not app_insights_enabled():
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        # Reads APPLICATIONINSIGHTS_CONNECTION_STRING + OTEL_* from the env.
        # Live metrics is a preview feature that keeps a websocket open to
        # Azure; the always-on API replica does not need it.
        configure_azure_monitor(enable_live_metrics=False)
    except Exception:
        logger.exception("Application Insights setup failed; continuing without it")
        # The distro registers the global TracerProvider early (_setup_tracing)
        # and may fail later (logging/instrumentation setup). If a real SDK
        # provider is already global, Langfuse would adopt it — and with it
        # Azure's exporter and sampler — so isolate it anyway.
        if langfuse_enabled():
            from opentelemetry import trace as otel_trace

            if not isinstance(otel_trace.get_tracer_provider(), otel_trace.ProxyTracerProvider):
                isolate_langfuse()
        return False
    _configured = True
    logger.info(
        "Application Insights telemetry on (OTEL_TRACES_SAMPLER=%s, OTEL_TRACES_SAMPLER_ARG=%s)",
        os.environ.get("OTEL_TRACES_SAMPLER", "<distro default: rate limited>"),
        os.environ.get("OTEL_TRACES_SAMPLER_ARG", "<default>"),
    )
    if langfuse_enabled():
        isolate_langfuse()
    return True


def langfuse_tracer_provider():
    """A TracerProvider for Langfuse only — never registered as global.

    Mirrors what Langfuse builds for itself (resource attributes for
    environment/release, ``LANGFUSE_SAMPLE_RATE`` as a TraceIdRatioBased
    sampler) with one deliberate difference: the default sampler is ALWAYS_ON,
    not the SDK's ParentBased(ALWAYS_ON), so a Langfuse span whose parent is an
    Azure-instrumented request span that App Insights sampled out is still
    recorded.
    """
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON, TraceIdRatioBased

    attributes: dict[str, str] = {}
    environment = os.environ.get("LANGFUSE_TRACING_ENVIRONMENT")
    if environment:
        attributes["langfuse.environment"] = environment
    release = os.environ.get("LANGFUSE_RELEASE")
    if release:
        attributes["langfuse.release"] = release

    sampler: Any = ALWAYS_ON
    raw_rate = os.environ.get("LANGFUSE_SAMPLE_RATE", "").strip()
    if raw_rate:
        try:
            rate = float(raw_rate)
        except ValueError:
            logger.warning("Ignoring non-numeric LANGFUSE_SAMPLE_RATE=%r", raw_rate)
        else:
            if 0.0 <= rate < 1.0:
                sampler = TraceIdRatioBased(rate)

    return TracerProvider(resource=Resource.create(attributes), sampler=sampler)


def isolate_langfuse() -> bool:
    """Bind the process's Langfuse client to its own TracerProvider.

    Must run before any ``get_client()`` / ``@observe`` / ``langfuse.openai``
    call: the first client for a public key wins, later ones reuse it.
    Returns True when Langfuse ended up on the isolated provider.
    """
    try:
        from langfuse import Langfuse
    except ImportError:  # pragma: no cover — langfuse is a hard dependency
        return False
    provider = langfuse_tracer_provider()
    try:
        client = Langfuse(tracer_provider=provider)
    except Exception:
        logger.exception("Langfuse could not be initialised on an isolated TracerProvider")
        return False

    resources = getattr(client, "_resources", None)
    if getattr(resources, "tracer_provider", None) is not provider:
        logger.warning(
            "Langfuse was initialised before telemetry.configure(); its spans share the "
            "global (Application Insights) TracerProvider and sampler"
        )
        return False
    _force_score_sampling(resources)
    logger.info("Langfuse tracing isolated from Application Insights (own TracerProvider)")
    return True


def _force_score_sampling(resources: Any) -> None:
    """Langfuse decides whether to send a score by asking the GLOBAL provider's
    sampler (resource_manager.py:add_score_task) so scores follow trace sampling.
    Our traces live on the always-on isolated provider, so the matching decision
    is "always"; without this, Azure's sampler would silently drop most
    ``visual_qa_defect`` scores. Instance-level override, guarded so a future
    SDK rename degrades to a log line rather than an error."""
    original = getattr(resources, "add_score_task", None)
    if original is None:
        logger.warning("Langfuse resource manager has no add_score_task; scores follow the global sampler")
        return

    def _always_in_sample(event: dict, *, force_sample: bool = False) -> None:
        del force_sample  # the caller's decision came from the global sampler
        return original(event, force_sample=True)

    resources.add_score_task = _always_in_sample


@contextlib.contextmanager
def detached_trace_context() -> Iterator[None]:
    """Run the body with no current OpenTelemetry span.

    Spans started inside become trace roots instead of children of whatever
    span is current in the calling context — e.g. the request's ASGI span,
    which Starlette keeps open while it runs BackgroundTasks. Also drops any
    propagated baggage; callers set their own (``propagate_attributes``).
    """
    try:
        from opentelemetry import context as otel_context
    except ImportError:  # pragma: no cover — opentelemetry-api ships with langfuse
        yield
        return
    token = otel_context.attach(otel_context.Context())
    try:
        yield
    finally:
        otel_context.detach(token)
