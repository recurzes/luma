from __future__ import annotations

import re
from uuid import UUID

SHORT_ID_LENGTH = 8

_SHORT_ID_RE = re.compile(rf"[0-9a-f]{{{SHORT_ID_LENGTH}}}")


def parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value.strip())
    except (ValueError, AttributeError):
        return None


def parse_short_id(value: str) -> str | None:
    """Return the normalised 8-hex short ID, or None if the input is not one.

    Rejecting anything else keeps LIKE wildcards and one-letter fragments out of lookups.
    """
    candidate = value.strip().strip("`").lower()
    return candidate if _SHORT_ID_RE.fullmatch(candidate) else None
