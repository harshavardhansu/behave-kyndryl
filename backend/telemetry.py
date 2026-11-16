"""Traces of agent runs, tool calls and Tool Gateway decisions, sent to Azure Monitor (Application Insights).

Turned on by ``APPLICATIONINSIGHTS_CONNECTION_STRING``. Without it every helper here does nothing, so
the app behaves the same with or without tracing.

Spans follow the OpenTelemetry GenAI conventions (``gen_ai.operation.name``, ``gen_ai.agent.name``,
``gen_ai.tool.name``, ``gen_ai.usage.*``), which is what the Azure AI Foundry tracing view and
Application Insights understand. Only metadata is recorded: no prompts, ticket text, code or logs.
"""

import contextlib
import logging
from typing import Any, Callable, Iterator, TypeVar

log = logging.getLogger("behave.telemetry")
_state: dict[str, Any] = {"tracer": None, "provider": None}
Result = TypeVar("Result")


def configure(connection_string: str, service_name: str = "behave-kyndryl") -> bool:
    """Send spans to Application Insights. Returns False (and keeps tracing off) if anything is missing."""
    if not connection_string or _state["tracer"] is not None:
        return _state["tracer"] is not None
    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as error:
        log.warning("Tracing is off: %s", error)
        return False
    try:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=connection_string)))
        trace.set_tracer_provider(provider)
    except Exception as error:  # noqa: BLE001 - a bad connection string must never stop the app
        log.warning("Tracing is off: %s", type(error).__name__)
        return False
    _state.update(tracer=trace.get_tracer("behave.agents"), provider=provider)
    log.warning("Tracing on: spans go to Application Insights.")
    return True


def enabled() -> bool:
    return _state["tracer"] is not None


def shutdown() -> None:
    provider = _state.get("provider")
    if provider is not None:
        with contextlib.suppress(Exception):
            provider.shutdown()


class _NoSpan:
    def set_attribute(self, *_: Any) -> None:
        return None

    def add_event(self, *_: Any, **__: Any) -> None:
        return None

    def record_exception(self, *_: Any) -> None:
        return None


def _clean(attributes: dict) -> dict:
    clean = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            clean[key] = value[:300] if isinstance(value, str) else value
        elif isinstance(value, (list, tuple)):
            clean[key] = [str(item)[:120] for item in value][:20]
    return clean


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """A span, or a stand-in that ignores everything when tracing is off. Keys use dots, e.g. ``gen_ai.agent.name``."""
    tracer = _state["tracer"]
    if tracer is None:
        yield _NoSpan()
        return
    with tracer.start_as_current_span(name, attributes=_clean(attributes)) as current:
        try:
            yield current
        except Exception as error:
            current.record_exception(error)
            from opentelemetry.trace import Status, StatusCode

            current.set_status(Status(StatusCode.ERROR, type(error).__name__))
            raise


def carry(function: Callable[..., Result]) -> Callable[..., Result]:
    """Run ``function`` in another thread under the current span (worker threads do not inherit it)."""
    if _state["tracer"] is None:
        return function
    from opentelemetry import context

    captured = context.get_current()

    def run(*args: Any, **kwargs: Any) -> Result:
        token = context.attach(captured)
        try:
            return function(*args, **kwargs)
        finally:
            context.detach(token)

    return run
