from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Member(BaseModel):
    id: UUID
    discord_id: str
    discord_name: str
    github_username: str | None
    role: str
    tier_max: str
    created_at: datetime


class MemberCreate(BaseModel):
    discord_id: str
    discord_name: str
    role: str
    tier_max: str


class MemberUpdate(BaseModel):
    github_username: str | None = None
    tier_max: str | None = None


class MemberStats(BaseModel):
    member_id: UUID
    total_xp: int
    level: int
    current_streak: int
    longest_streak: int
    last_activity: datetime | None
    tickets_closed: int
    prs_merged: int
    helps_given: int
    updated_at: datetime