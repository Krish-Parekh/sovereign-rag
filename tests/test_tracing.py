import re

import httpx
from fastapi import FastAPI
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag.tracing import current_trace_id, flush_spans, flushing, tracer


def test_trace_id_is_none_outside_a_span() -> None:
    assert current_trace_id() is None


def test_trace_id_uses_xray_format_inside_a_span() -> None:
    with tracer.start_as_current_span("step"):
        trace_id = current_trace_id()

    assert trace_id is not None
    assert re.fullmatch(r"1-[0-9a-f]{8}-[0-9a-f]{24}", trace_id)


def test_flush_sends_finished_spans(spans: InMemorySpanExporter) -> None:
    with tracer.start_as_current_span("step"):
        pass

    flush_spans()

    assert [s.name for s in spans.get_finished_spans()] == ["step"]


async def test_flushing_wrapper_passes_requests_through() -> None:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> str:
        return "pong"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=flushing(app)), base_url="http://test") as client:
        response = await client.get("/ping")

    assert response.json() == "pong"
