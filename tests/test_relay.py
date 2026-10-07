import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass, field

from rag.relay import relay


@dataclass
class Source:
    produced: list[int] = field(default_factory=list[int])
    closed: asyncio.Event = field(default_factory=asyncio.Event)

    async def items(self, count: int) -> AsyncGenerator[int]:
        try:
            for n in range(count):
                self.produced.append(n)
                yield n
                await asyncio.sleep(0)
        finally:
            self.closed.set()


async def test_relay_passes_items_in_order() -> None:
    source = Source()

    assert [n async for n in relay(source.items(5))] == [0, 1, 2, 3, 4]


async def test_closing_the_relay_closes_the_source() -> None:
    source = Source()

    async with aclosing(relay(source.items(1000))) as items:
        async for n in items:
            if n == 2:
                break

    await asyncio.wait_for(source.closed.wait(), 1)
    assert len(source.produced) < 1000


async def test_abandoned_relay_still_runs_the_source_to_the_end() -> None:
    source = Source()
    items = relay(source.items(50))

    assert await anext(items) == 0
    await asyncio.wait_for(source.closed.wait(), 1)
    assert len(source.produced) == 50
