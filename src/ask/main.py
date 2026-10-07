import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from rag.answering import answer
from rag.auth import caller_from_context, request_id_from_context
from rag.config import get_settings
from rag.deps import Deps, build_deps
from rag.relay import relay
from rag.schemas import AskRequest, Caller
from rag.telemetry import logger
from rag.tracing import current_trace_id, flushing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.deps = await asyncio.to_thread(build_deps, get_settings())
    yield


app = FastAPI(title="sovereign-rag", lifespan=lifespan)
asgi = flushing(app)


def get_deps(request: Request) -> Deps:
    return request.app.state.deps


def get_caller(x_amzn_request_context: Annotated[str | None, Header()] = None) -> Caller:
    caller = caller_from_context(x_amzn_request_context)
    if caller is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return caller


def get_request_id(x_amzn_lambda_context: Annotated[str | None, Header()] = None) -> str:
    return request_id_from_context(x_amzn_lambda_context)


@app.post("/ask", response_class=EventSourceResponse)
async def ask(
    body: AskRequest,
    deps: Annotated[Deps, Depends(get_deps)],
    caller: Annotated[Caller, Depends(get_caller)],
    request_id: Annotated[str, Depends(get_request_id)],
) -> AsyncIterator[ServerSentEvent]:
    logger.append_keys(request_id=request_id, trace_id=current_trace_id())
    async for event in relay(answer(deps, caller, body, request_id)):
        yield ServerSentEvent(data=event, event=event.name)
