from __future__ import annotations

import asyncio


async def run_query(query):
    """Execute a Supabase query builder off the event loop.

    The client is synchronous: calling `.execute()` directly inside a coroutine stalls
    every command and the gateway heartbeat for the length of the HTTP round trip.
    """
    return await asyncio.to_thread(query.execute)


def row_or_none(response) -> dict | None:
    """Unwrap a `.maybe_single().execute()` result, which is None (not an empty response) on zero rows."""
    return response.data if response is not None else None
