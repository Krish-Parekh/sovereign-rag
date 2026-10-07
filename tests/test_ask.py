import asyncio
import contextlib
import gc
import io
import json
import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import anyio
import boto3
import httpx
import pytest
from botocore.stub import Stubber
from fakes import MODEL, FakeBedrock
from moto import mock_aws
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel
from starlette.types import Message, Scope
from types_boto3_dynamodb.service_resource import Table

from ask.main import app, get_deps
from rag.answering import answer
from rag.config import get_settings
from rag.deps import Deps
from rag.schemas import AskRequest, Caller, DoneEvent, MetaEvent, SourcesEvent, TokenEvent, Turn, new_id
from rag.telemetry import logger

QUESTION = "How do I connect a domain?"
RESULTS: list[dict[str, object]] = [
    {
        "content": {"text": text, "type": "TEXT"},
        "metadata": {"article_id": f"a{n}", "url": f"https://wix.com/a{n}", "x-amz-bedrock-kb-chunk-id": f"chunk-{n}"},
        "score": 0.9 - 0.1 * n,
    }
    for n, text in [(1, "Open Settings, then Domains."), (2, "Connect a domain you already own.")]
]
EVENT_TYPES: dict[str, type[BaseModel]] = {
    "meta": MetaEvent,
    "sources": SourcesEvent,
    "token": TokenEvent,
    "done": DoneEvent,
}


def context(sub: str) -> str:
    return json.dumps({"requestId": "api-1", "authorizer": {"claims": {"sub": sub, "scope": "sovereign-rag/ask"}}})


@dataclass
class Stream:
    names: list[str]
    meta: MetaEvent
    sources: SourcesEvent | None
    tokens: list[TokenEvent]
    done: DoneEvent

    @property
    def text(self) -> str:
        return "".join(t.text for t in self.tokens)


def _parse(body: str) -> Stream:
    names: list[str] = []
    events: list[BaseModel] = []
    for block in body.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        names.append(fields["event"])
        events.append(EVENT_TYPES[fields["event"]].model_validate(json.loads(fields["data"])))
    meta, done = events[0], events[-1]
    assert isinstance(meta, MetaEvent)
    assert isinstance(done, DoneEvent)
    sources = next((e for e in events if isinstance(e, SourcesEvent)), None)
    tokens = [e for e in events if isinstance(e, TokenEvent)]
    return Stream(names=names, meta=meta, sources=sources, tokens=tokens, done=done)


@dataclass
class Harness:
    fake: FakeBedrock
    deps: Deps
    stub: Stubber
    client: httpx.AsyncClient

    def expect_retrieve(self, query: str, results: list[dict[str, object]] | None = None) -> None:
        self.stub.add_response(
            "retrieve",
            {"retrievalResults": RESULTS if results is None else results},
            {
                "knowledgeBaseId": "KB12345678",
                "retrievalQuery": {"text": query},
                "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 5}},
            },
        )

    async def ask(self, question: str, conversation_id: str | None = None, sub: str = "sub-a") -> Stream:
        response = await self.client.post(
            "/ask",
            json={"question": question, "conversation_id": conversation_id},
            headers={"x-amzn-request-context": context(sub)},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return _parse(response.text)

    def turns(self, conversation_id: str, sub: str = "sub-a") -> list[Turn]:
        items = self.deps.table.scan().get("Items", [])
        turns = [Turn.model_validate(i) for i in items if i["pk"] == f"USER#{sub}#CONV#{conversation_id}"]
        return sorted(turns, key=lambda t: t.sk)


def _table() -> Table:
    return boto3.resource("dynamodb").create_table(
        TableName="chat",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def aws() -> Iterator[None]:
    with mock_aws():
        yield


def _deps(fake: FakeBedrock, *, table: bool = True, answer_timeout_s: float | None = None) -> Deps:
    settings = get_settings()
    if answer_timeout_s is not None:
        settings = settings.model_copy(update={"answer_timeout_s": answer_timeout_s})
    return Deps(
        settings=settings,
        chat=fake.client(),
        knowledge=boto3.client("bedrock-agent-runtime"),
        table=_table() if table else boto3.resource("dynamodb").Table("missing"),
    )


async def _harness(fake: FakeBedrock, deps: Deps | None = None) -> AsyncIterator[Harness]:
    deps = deps or _deps(fake)

    def override() -> Deps:
        return deps

    app.dependency_overrides[get_deps] = override
    with Stubber(deps.knowledge) as stub:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield Harness(fake=fake, deps=deps, stub=stub, client=client)
    app.dependency_overrides.clear()


@pytest.fixture
async def harness(aws: None) -> AsyncIterator[Harness]:
    async for h in _harness(FakeBedrock()):
        yield h


@pytest.fixture
async def broken(aws: None) -> AsyncIterator[Harness]:
    async for h in _harness(FakeBedrock(chat_status=400)):
        yield h


@pytest.fixture
async def slow(aws: None) -> AsyncIterator[Harness]:
    fake = FakeBedrock(first_token_delay_s=5)
    async for h in _harness(fake, _deps(fake, answer_timeout_s=0.3)):
        yield h


@pytest.fixture
async def no_table(aws: None) -> AsyncIterator[Harness]:
    fake = FakeBedrock()
    async for h in _harness(fake, _deps(fake, table=False)):
        yield h


async def test_first_question_streams_meta_sources_tokens_done(harness: Harness) -> None:
    harness.expect_retrieve(QUESTION)

    stream = await harness.ask(QUESTION)

    assert stream.names == ["meta", "sources", "token", "token", "token", "token", "done"]
    assert stream.text == "Open Settings then Domains [1]."
    assert stream.sources is not None
    assert [s.url for s in stream.sources.sources] == ["https://wix.com/a1", "https://wix.com/a2"]
    assert stream.done.status == "complete"
    assert stream.done.tokens_out == 4
    assert stream.done.ttft_ms is not None


async def test_citations_are_only_retrieved_urls(harness: Harness) -> None:
    harness.fake.tokens = ["See ", "[2] ", "and ", "[9]."]
    harness.expect_retrieve(QUESTION)

    stream = await harness.ask(QUESTION)

    assert stream.done.citations == ["https://wix.com/a2"]


async def test_both_turns_are_saved_under_the_callers_partition(harness: Harness) -> None:
    harness.expect_retrieve(QUESTION)

    stream = await harness.ask(QUESTION)

    user, assistant = harness.turns(stream.meta.conversation_id)
    assert (user.role, user.content, user.request_id) == ("user", QUESTION, stream.meta.request_id)
    assert assistant.content == stream.text
    assert assistant.status == "complete"
    assert assistant.citations == ["https://wix.com/a1"]
    assert [r.key for r in assistant.retrieved] == ["chunk-1", "chunk-2"]
    assert (assistant.model, assistant.tokens_out) == (MODEL, 4)
    assert assistant.pk == f"USER#sub-a#CONV#{stream.meta.conversation_id}"


async def test_generation_uses_spec_settings(harness: Harness) -> None:
    harness.expect_retrieve(QUESTION)

    await harness.ask(QUESTION)

    [generate] = harness.fake.generations()
    assert harness.fake.rewrites() == []
    assert generate.model == MODEL
    assert generate.temperature == 0.2
    assert generate.max_tokens == 1024
    assert generate.stream_options is not None
    assert generate.stream_options.include_usage
    assert generate.chat_template_kwargs is not None
    assert generate.chat_template_kwargs.enable_thinking is False
    assert "<context>" in generate.messages[-1].content


async def test_follow_up_is_rewritten_before_retrieval(harness: Harness) -> None:
    harness.expect_retrieve(QUESTION)
    first = await harness.ask(QUESTION)
    harness.expect_retrieve(harness.fake.rewrite)

    second = await harness.ask("and on mobile?", first.meta.conversation_id)

    [rewrite] = harness.fake.rewrites()
    assert second.meta.conversation_id == first.meta.conversation_id
    assert (rewrite.temperature, rewrite.max_tokens) == (0, 128)
    assert [m.role for m in harness.fake.generations()[-1].messages] == ["system", "user", "assistant", "user"]
    assert len(harness.turns(first.meta.conversation_id)) == 4


async def test_unknown_conversation_is_a_first_question(harness: Harness) -> None:
    conversation_id = new_id()
    harness.expect_retrieve(QUESTION)

    stream = await harness.ask(QUESTION, conversation_id)

    assert stream.meta.conversation_id == conversation_id
    assert harness.fake.rewrites() == []


async def test_other_users_conversation_starts_fresh(harness: Harness) -> None:
    harness.expect_retrieve(QUESTION)
    owner = await harness.ask(QUESTION, sub="sub-a")
    harness.expect_retrieve("and on mobile?")

    intruder = await harness.ask("and on mobile?", owner.meta.conversation_id, sub="sub-b")

    assert harness.fake.rewrites() == []
    assert len(harness.turns(owner.meta.conversation_id, sub="sub-a")) == 2
    assert len(harness.turns(intruder.meta.conversation_id, sub="sub-b")) == 2


async def test_model_failure_ends_stream_incomplete(broken: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    broken.expect_retrieve(QUESTION)

    stream = await broken.ask(QUESTION)

    assert stream.names == ["meta", "sources", "done"]
    assert stream.done.status == "incomplete"
    assert stream.done.citations == []
    _, assistant = broken.turns(stream.meta.conversation_id)
    assert assistant.status == "incomplete"
    assert '"AskErrors"' in capsys.readouterr().out


async def test_missing_usage_leaves_tokens_out_empty(harness: Harness) -> None:
    harness.fake.usage = False
    harness.expect_retrieve(QUESTION)

    stream = await harness.ask(QUESTION)

    assert stream.done.status == "complete"
    assert stream.done.tokens_out is None


async def test_no_hits_still_answers(harness: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    harness.fake.tokens = ["I ", "don't ", "know."]
    harness.expect_retrieve(QUESTION, results=[])

    stream = await harness.ask(QUESTION)

    assert stream.sources is not None
    assert stream.sources.sources == []
    assert stream.done.status == "complete"
    assert stream.done.citations == []
    assert '"TopScore"' not in capsys.readouterr().out


@pytest.mark.parametrize(
    "body", [{"question": "  "}, {}, {"question": "hi", "conversation_id": "x"}, {"question": "x" * 2001}]
)
async def test_invalid_request_is_rejected(harness: Harness, body: dict[str, str]) -> None:
    response = await harness.client.post("/ask", json=body, headers={"x-amzn-request-context": context("sub-a")})

    assert response.status_code == 422
    assert harness.fake.calls == []


async def test_missing_identity_is_unauthorised(harness: Harness) -> None:
    response = await harness.client.post("/ask", json={"question": QUESTION})

    assert response.status_code == 401
    assert harness.fake.calls == []


async def test_request_id_comes_from_lambda_context(harness: Harness) -> None:
    harness.expect_retrieve(QUESTION)

    response = await harness.client.post(
        "/ask",
        json={"question": QUESTION},
        headers={
            "x-amzn-request-context": context("sub-a"),
            "x-amzn-lambda-context": json.dumps({"request_id": "lambda-req-9", "deadline": 0}),
        },
    )

    stream = _parse(response.text)
    assert stream.meta.request_id == "lambda-req-9"
    assert harness.turns(stream.meta.conversation_id)[0].request_id == "lambda-req-9"


async def test_answer_past_its_time_budget_ends_incomplete(slow: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    slow.expect_retrieve(QUESTION)

    stream = await slow.ask(QUESTION)

    assert stream.names == ["meta", "sources", "done"]
    assert stream.done.status == "incomplete"
    assert stream.done.total_ms < 3000
    _, assistant = slow.turns(stream.meta.conversation_id)
    assert assistant.status == "incomplete"
    assert '"AskErrors"' in capsys.readouterr().out


async def test_chat_store_failure_still_ends_with_done(no_table: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    stream = await no_table.ask(QUESTION)

    assert stream.names == ["meta", "done"]
    assert stream.done.status == "incomplete"
    assert '"AskErrors"' in capsys.readouterr().out


async def test_client_disconnect_still_saves_incomplete_turn(harness: Harness) -> None:
    harness.fake.token_delay_s = 0.05
    harness.expect_retrieve(QUESTION)
    conversation_id = ""

    with anyio.CancelScope() as scope:
        async for event in answer(harness.deps, Caller(sub="sub-a"), AskRequest(question=QUESTION), "req-cancel"):
            if isinstance(event, MetaEvent):
                conversation_id = event.conversation_id
            if isinstance(event, TokenEvent):
                scope.cancel()

    _, assistant = harness.turns(conversation_id)
    assert assistant.status == "incomplete"
    assert assistant.content == "Open "


async def test_spans_name_each_step_and_carry_no_content(harness: Harness, spans: InMemorySpanExporter) -> None:
    harness.expect_retrieve(QUESTION)
    first = await harness.ask(QUESTION)
    harness.expect_retrieve(harness.fake.rewrite)
    await harness.ask("and on mobile?", first.meta.conversation_id)

    finished = spans.get_finished_spans()
    by_name = {s.name: s for s in finished}
    assert {"rewrite", "retrieve", "generate"} <= by_name.keys()
    generate = by_name["generate"].attributes
    assert generate is not None
    assert generate["gen_ai.request.model"] == MODEL
    assert generate["gen_ai.system"] == "aws.bedrock"
    assert generate["gen_ai.usage.output_tokens"] == 4
    assert by_name["retrieve"].attributes is not None
    assert by_name["retrieve"].attributes["hits"] == 2
    values = [str(v) for s in finished for v in (s.attributes or {}).values()]
    assert not any(QUESTION in v or "mobile" in v or "Open Settings" in v for v in values)


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logger.registered_formatter)
    logging.getLogger("sovereign-rag").addHandler(handler)
    yield stream
    logging.getLogger("sovereign-rag").removeHandler(handler)


async def test_logs_carry_no_question_or_answer(harness: Harness, log_stream: io.StringIO) -> None:
    harness.expect_retrieve(QUESTION)

    await harness.ask(QUESTION)

    out = log_stream.getvalue()
    assert QUESTION not in out
    assert "Open Settings" not in out
    assert '"request_id"' in out


async def test_disconnect_through_the_app_still_saves_the_assistant_turn(harness: Harness) -> None:
    harness.fake.tokens = [f"t{n} " for n in range(50)]
    harness.expect_retrieve(QUESTION)
    pending: list[Message] = [{"type": "http.request", "body": json.dumps({"question": QUESTION}).encode()}]
    disconnected = asyncio.Event()
    sent: list[Message] = []
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/ask",
        "raw_path": b"/ask",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"x-amzn-request-context", context("sub-a").encode())],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "state": {},
    }

    async def receive() -> Message:
        if pending:
            return pending.pop()
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body":
            sent.append(message)
            await asyncio.sleep(0.1)
            if len(sent) > 3:
                disconnected.set()
                raise OSError("client gone")

    gc.disable()
    try:
        with contextlib.suppress(Exception):
            await app(scope, receive, send)
        roles: list[str] = []
        for _ in range(20):
            roles = [str(item["role"]) for item in harness.deps.table.scan().get("Items", [])]
            if "assistant" in roles:
                break
            await asyncio.sleep(0.05)
    finally:
        gc.enable()

    assert sorted(roles) == ["assistant", "user"]


async def test_failed_retrieval_keeps_retrieved_text_out_of_spans(
    harness: Harness, spans: InMemorySpanExporter
) -> None:
    broken: dict[str, object] = {
        "content": {"text": "SECRET corpus text", "type": "TEXT"},
        "metadata": {"article_id": "a1", "url": "https://wix.com/a1"},
    }
    harness.expect_retrieve(QUESTION, results=[broken])

    stream = await harness.ask(QUESTION)

    assert stream.done.status == "incomplete"
    messages = [
        event.attributes.get("exception.message")
        for span in spans.get_finished_spans()
        for event in span.events
        if event.attributes is not None
    ]
    assert [m for m in messages if m is not None] == []
    assert [s.status.description for s in spans.get_finished_spans() if s.status.description] == []
