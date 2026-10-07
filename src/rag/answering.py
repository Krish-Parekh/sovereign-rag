import asyncio
import time
from collections.abc import AsyncIterator

from rag.deps import Deps
from rag.schemas import AskRequest, Caller, DoneEvent, MetaEvent, SseEvent, TokenEvent, new_id

PLACEHOLDER = ["This ", "is ", "a ", "streaming ", "stub."]
STUB_DELAY_S = 0.5


async def answer(deps: Deps, caller: Caller, request: AskRequest, request_id: str) -> AsyncIterator[SseEvent]:
    started = time.perf_counter()
    yield MetaEvent(conversation_id=request.conversation_id or new_id(), request_id=request_id)
    for text in PLACEHOLDER:
        await asyncio.sleep(STUB_DELAY_S)
        yield TokenEvent(text=text)
    yield DoneEvent(
        status="complete",
        citations=[],
        ttft_ms=None,
        total_ms=round((time.perf_counter() - started) * 1000),
        tokens_out=len(PLACEHOLDER),
    )
