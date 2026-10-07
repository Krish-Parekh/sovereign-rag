import os

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

os.environ.update(
    {
        "AWS_DEFAULT_REGION": "ap-southeast-2",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "KNOWLEDGE_BASE_ID": "KB12345678",
        "CHAT_TABLE": "chat",
        "POWERTOOLS_METRICS_NAMESPACE": "SovereignRag",
    }
)

EXPORTER = InMemorySpanExporter()
PROVIDER = TracerProvider()
PROVIDER.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(PROVIDER)


@pytest.fixture
def spans() -> InMemorySpanExporter:
    EXPORTER.clear()
    return EXPORTER
