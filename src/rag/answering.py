import asyncio
import time
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field

import anyio
from opentelemetry.trace import StatusCode

from rag.chat_store import load_history, save_turn
from rag.deps import Deps
from rag.knowledge import retrieve, top_score
from rag.prompts import answer_messages, cited_urls, rewrite_messages
from rag.schemas import (
    AskRequest,
    Caller,
    DoneEvent,
    Hit,
    MetaEvent,
    Retrieved,
    Source,
    SourcesEvent,
    SseEvent,
    Status,
    TokenEvent,
    Turn,
    new_id,
)
from rag.telemetry import Metric, logger, metrics, record
from rag.tracing import flush_spans, tracer

HISTORY_MESSAGES = 6
TEMPERATURE = 0.2
MAX_TOKENS = 1024
REWRITE_MAX_TOKENS = 128
NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}


@dataclass
class Run:
    request_id: str
    conversation_id: str
    budget_s: float
    started: float = field(default_factory=time.perf_counter)
    hits: list[Hit] = field(default_factory=list[Hit])
    parts: list[str] = field(default_factory=list[str])
    ttft_ms: int | None = None
    tokens_out: int | None = None
    status: Status = "incomplete"

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def elapsed_ms(self) -> int:
        return _ms(self.started)

    async def within[T](self, step: Awaitable[T]) -> T:
        return await asyncio.wait_for(step, max(self.started + self.budget_s - time.perf_counter(), 0))


async def answer(deps: Deps, caller: Caller, request: AskRequest, request_id: str) -> AsyncIterator[SseEvent]:
    run = Run(
        request_id=request_id,
        conversation_id=request.conversation_id or new_id(),
        budget_s=deps.settings.answer_timeout_s,
    )
    logger.append_keys(conversation_id=run.conversation_id)
    yield MetaEvent(conversation_id=run.conversation_id, request_id=request_id)
    try:
        async for event in _generate(deps, caller, request.question, run):
            yield event
        run.status = "complete"
    except Exception as exc:
        logger.error("ask failed", extra={"error": type(exc).__name__})
        record(Metric.ASK_ERRORS, 1)
    finally:
        with anyio.CancelScope(shield=True):
            await _finish(deps, caller, run)
    yield DoneEvent(
        status=run.status,
        citations=cited_urls(run.text, run.hits),
        ttft_ms=run.ttft_ms,
        total_ms=run.elapsed_ms(),
        tokens_out=run.tokens_out,
    )


async def _generate(deps: Deps, caller: Caller, question: str, run: Run) -> AsyncIterator[SseEvent]:
    history = await run.within(
        asyncio.to_thread(load_history, deps.table, caller.sub, run.conversation_id, HISTORY_MESSAGES)
    )
    user = Turn(
        user_sub=caller.sub,
        conversation_id=run.conversation_id,
        role="user",
        content=question,
        request_id=run.request_id,
    )
    await run.within(asyncio.to_thread(save_turn, deps.table, user))
    query = await run.within(_rewrite(deps, history, question, run)) if history else question
    run.hits = await run.within(_retrieve(deps, query, run))
    yield SourcesEvent(
        sources=[
            Source(n=n, url=hit.url, article_id=hit.article_id, score=hit.score) for n, hit in enumerate(run.hits, 1)
        ]
    )
    async for event in _stream(deps, history, question, run):
        yield event


async def _rewrite(deps: Deps, history: list[Turn], question: str, run: Run) -> str:
    started = time.perf_counter()
    with tracer.start_as_current_span("rewrite", attributes=_model_attributes(deps, run)) as span:
        completion = await deps.chat.chat.completions.create(
            model=deps.settings.chat_model,
            messages=rewrite_messages(history, question),
            temperature=0,
            max_tokens=REWRITE_MAX_TOKENS,
            extra_body=NO_THINKING,
        )
        rewritten = (completion.choices[0].message.content or "").strip() or question
        span.set_attribute("query_chars", len(rewritten))
    logger.info("rewrite", extra={"ms": _ms(started), "history_messages": len(history), "query_chars": len(rewritten)})
    return rewritten


async def _retrieve(deps: Deps, query: str, run: Run) -> list[Hit]:
    started = time.perf_counter()
    with tracer.start_as_current_span("retrieve", attributes=_ids(run)) as span:
        hits = await asyncio.to_thread(retrieve, deps.knowledge, deps.settings.knowledge_base_id, query)
        span.set_attribute("hits", len(hits))
        if hits:
            span.set_attribute("top_score", top_score(hits))
    retrieve_ms = _ms(started)
    record(Metric.RETRIEVE_MS, retrieve_ms)
    if hits:
        record(Metric.TOP_SCORE, top_score(hits))
    logger.info(
        "retrieve",
        extra={"ms": retrieve_ms, "hits": len(hits), "top_score": top_score(hits) if hits else None},
    )
    return hits


async def _stream(deps: Deps, history: list[Turn], question: str, run: Run) -> AsyncIterator[TokenEvent]:
    started = time.perf_counter()
    span = tracer.start_span("generate", attributes=_model_attributes(deps, run))
    try:
        stream = await run.within(
            deps.chat.chat.completions.create(
                model=deps.settings.chat_model,
                messages=answer_messages(history, question, run.hits),
                stream=True,
                stream_options={"include_usage": True},
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                extra_body=NO_THINKING,
            )
        )
        chunks = aiter(stream)
        while True:
            try:
                chunk = await run.within(anext(chunks))
            except StopAsyncIteration:
                break
            if chunk.usage is not None:
                run.tokens_out = chunk.usage.completion_tokens
            text = chunk.choices[0].delta.content if chunk.choices else None
            if text:
                if run.ttft_ms is None:
                    run.ttft_ms = run.elapsed_ms()
                    record(Metric.TTFT_MS, run.ttft_ms)
                    span.set_attribute("ttft_ms", run.ttft_ms)
                run.parts.append(text)
                yield TokenEvent(text=text)
        if run.tokens_out is not None:
            span.set_attribute("gen_ai.usage.output_tokens", run.tokens_out)
    except Exception:
        span.set_status(StatusCode.ERROR)
        raise
    finally:
        span.end()
    generate_ms = _ms(started)
    record(Metric.GENERATE_MS, generate_ms)
    logger.info("generate", extra={"ms": generate_ms, "ttft_ms": run.ttft_ms, "tokens_out": run.tokens_out})


async def _finish(deps: Deps, caller: Caller, run: Run) -> None:
    total_ms = run.elapsed_ms()
    turn = Turn(
        user_sub=caller.sub,
        conversation_id=run.conversation_id,
        role="assistant",
        content=run.text,
        citations=cited_urls(run.text, run.hits),
        retrieved=[Retrieved(key=hit.key, score=hit.score) for hit in run.hits],
        model=deps.settings.chat_model,
        ttft_ms=run.ttft_ms,
        total_ms=total_ms,
        tokens_out=run.tokens_out,
        request_id=run.request_id,
        status=run.status,
    )
    try:
        await asyncio.to_thread(save_turn, deps.table, turn)
    except Exception as exc:
        logger.error("saving the assistant turn failed", extra={"error": type(exc).__name__})
        record(Metric.ASK_ERRORS, 1)
    finally:
        record(Metric.TOTAL_MS, total_ms)
        if run.tokens_out is not None:
            record(Metric.TOKENS_OUT, run.tokens_out)
        logger.info(
            "done",
            extra={
                "status": run.status,
                "ms": total_ms,
                "answer_chars": len(turn.content),
                "cited": len(turn.citations),
            },
        )
        metrics.flush_metrics()
        await asyncio.to_thread(flush_spans)


def _ids(run: Run) -> dict[str, str]:
    return {"request_id": run.request_id, "conversation_id": run.conversation_id}


def _model_attributes(deps: Deps, run: Run) -> dict[str, str]:
    return {**_ids(run), "gen_ai.system": "aws.bedrock", "gen_ai.request.model": deps.settings.chat_model}


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
