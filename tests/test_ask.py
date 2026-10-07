import json
from collections.abc import AsyncIterator

import httpx
import pytest

from ask.main import app, get_deps
from rag.config import get_settings
from rag.deps import Deps, build_deps

CONTEXT = json.dumps({"requestId": "api-1", "authorizer": {"claims": {"sub": "sub-a"}}})


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    deps = build_deps(get_settings())

    def override() -> Deps:
        return deps

    app.dependency_overrides[get_deps] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_request_without_identity_is_unauthorised(client: httpx.AsyncClient) -> None:
    response = await client.post("/ask", json={"question": "hi"})

    assert response.status_code == 401


async def test_stub_streams_meta_tokens_done(client: httpx.AsyncClient) -> None:
    response = await client.post("/ask", json={"question": "hi"}, headers={"x-amzn-request-context": CONTEXT})

    events = [line.removeprefix("event: ") for line in response.text.splitlines() if line.startswith("event: ")]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events[0] == "meta"
    assert events[-1] == "done"
    assert events.count("token") >= 3


async def test_invalid_request_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/ask", json={"question": " "}, headers={"x-amzn-request-context": CONTEXT})

    assert response.status_code == 422
