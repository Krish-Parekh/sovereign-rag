import asyncio

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from starlette.types import ASGIApp, Receive, Scope, Send

tracer = trace.get_tracer("sovereign-rag")


def flush_spans() -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.force_flush()


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    hex_id = format(context.trace_id, "032x")
    return f"1-{hex_id[:8]}-{hex_id[8:]}"


def flushing(app: ASGIApp) -> ASGIApp:
    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await app(scope, receive, send)
        finally:
            if scope["type"] == "http":
                await asyncio.to_thread(flush_spans)

    return wrapped
