from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class XPLedgerEntry(BaseModel):
    id: UUID
    member_id: UUID
    action: str
    xp: int
    metadata: dict | None
    awarded_at: datetime


class LeaderboardEntry(BaseModel):
    rank: int
    member_id: UUID
    discord_id: str
    discord_name: str
    total_xp: int
    level: int
    current_streak: int