from __future__ import annotations


def row_or_none(response) -> dict | None:
    """Unwrap a `.maybe_single().execute()` result, which is None (not an empty response) on zero rows."""
    return response.data if response is not None else None
