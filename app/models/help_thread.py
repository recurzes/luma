from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HelpThread(BaseModel):
    id: UUID
    requester_id: UUID
    problem: str
    discord_thread_id: str | None
    status: str
    helper_id: UUID | None
    opened_at: datetime
    resolved_at: datetime | None
    escalated_at: datetime | None
    resolution_notes: str | None