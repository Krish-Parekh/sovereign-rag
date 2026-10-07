import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx2
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import Choice as ChunkChoice
from openai.types.chat.chat_completion_chunk import ChoiceDelta
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.completion_usage import CompletionUsage
from pydantic import BaseModel

MODEL = "qwen.qwen3-32b-v1:0"


class Message(BaseModel):
    role: str
    content: str


class TemplateKwargs(BaseModel):
    enable_thinking: bool


class StreamOptions(BaseModel):
    include_usage: bool


class ChatBody(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None
    stream_options: StreamOptions | None = None
    chat_template_kwargs: TemplateKwargs | None = None


@dataclass
class FakeBedrock:
    tokens: list[str] = field(default_factory=lambda: ["Open ", "Settings ", "then ", "Domains [1]."])
    rewrite: str = "how do I connect a domain to my site"
    first_token_delay_s: float = 0.0
    token_delay_s: float = 0.0
    chat_status: int = 200
    usage: bool = True
    calls: list[ChatBody] = field(default_factory=list[ChatBody])

    def client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="test",
            base_url="https://bedrock.test/openai/v1",
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle)),
        )

    def rewrites(self) -> list[ChatBody]:
        return [c for c in self.calls if not c.stream]

    def generations(self) -> list[ChatBody]:
        return [c for c in self.calls if c.stream]

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        chat = ChatBody.model_validate_json(request.content)
        self.calls.append(chat)
        if self.chat_status != 200:
            return httpx2.Response(self.chat_status, json={"message": "The provided model identifier is invalid."})
        if chat.stream:
            return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=self._stream())
        return httpx2.Response(200, content=_completion(self.rewrite).model_dump_json())

    async def _stream(self) -> AsyncIterator[bytes]:
        await asyncio.sleep(self.first_token_delay_s)
        for token in self.tokens:
            await asyncio.sleep(self.token_delay_s)
            yield _sse(_chunk([ChunkChoice(index=0, delta=ChoiceDelta(content=token))]))
        if self.usage:
            usage = CompletionUsage(
                prompt_tokens=50, completion_tokens=len(self.tokens), total_tokens=50 + len(self.tokens)
            )
            yield _sse(_chunk([], usage))
        yield b"data: [DONE]\n\n"


def _completion(text: str) -> ChatCompletion:
    return ChatCompletion(
        id="c",
        object="chat.completion",
        created=0,
        model=MODEL,
        choices=[Choice(index=0, finish_reason="stop", message=ChatCompletionMessage(role="assistant", content=text))],
    )


def _chunk(choices: list[ChunkChoice], usage: CompletionUsage | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="c", object="chat.completion.chunk", created=0, model=MODEL, choices=choices, usage=usage
    )


def _sse(chunk: ChatCompletionChunk) -> bytes:
    return f"data: {chunk.model_dump_json()}\n\n".encode()
