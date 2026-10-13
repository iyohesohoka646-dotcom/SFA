"""Cancel an application's awaitable when its HTTP caller disconnects."""
import asyncio
from contextlib import suppress


async def await_connected(request,awaitable):
    operation=asyncio.ensure_future(awaitable)
    async def monitor():
        while not operation.done():
            if await request.is_disconnected():operation.cancel();return
            await asyncio.sleep(.1)
    watching=asyncio.create_task(monitor())
    try:return await operation
    finally:
        watching.cancel()
        with suppress(asyncio.CancelledError):await watching
