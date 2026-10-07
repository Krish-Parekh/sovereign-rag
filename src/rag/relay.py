import asyncio
import math
from collections.abc import AsyncGenerator
from contextlib import aclosing

import anyio
from anyio.streams.memory import MemoryObjectSendStream

PUMPS: set[asyncio.Task[None]] = set()


async def relay[T](source: AsyncGenerator[T]) -> AsyncGenerator[T]:
    send, receive = anyio.create_memory_object_stream[T](math.inf)
    pump = asyncio.create_task(_pump(source, send))
    PUMPS.add(pump)
    pump.add_done_callback(PUMPS.discard)
    async with receive:
        async for item in receive:
            yield item


async def _pump[T](source: AsyncGenerator[T], send: MemoryObjectSendStream[T]) -> None:
    async with send, aclosing(source) as items:
        try:
            async for item in items:
                await send.send(item)
        except anyio.BrokenResourceError:
            return
