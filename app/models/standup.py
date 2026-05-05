from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StandupSession(BaseModel):
    id: UUID
    date: str
    posted_at: datetime | None
    created_at: datetime


class StandupResponse(BaseModel):
    id: UUID
    session_id: UUID
    member_id: UUID
    yesterday: str | None
    today: str | None
    blockers: str | None
    responded_at: datetime