from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BlitzSession(BaseModel):
    id: UUID
    guild_id: str
    created_by: UUID | None

    technology: str
    tech_category: str
    goal: str
    deliverable_type: str

    duration_hours: int
    started_at: datetime | None
    ends_at: datetime | None
    extended_hours: int

    status: str

    announce_msg_id: str | None
    guild_channel_id: str | None

    completed_at: datetime | None
    cancelled_at: datetime | None


class BlitzCreate(BaseModel):
    guild_id: str
    created_by: UUID
    technology: str
    tech_category: str
    goal: str
    deliverable_type: str = "any"
    duration_hours: int = 48
    guild_channel_id: str | None = None


class BlitzParticipant(BaseModel):
    id: UUID
    blitz_id: UUID
    member_id: UUID
    joined_at: datetime | None


class BlitzCheckin(BaseModel):
    id: UUID
    blitz_id: UUID
    member_id: UUID
    content: str
    media_url: str | None
    mood: int | None
    posted_at: datetime | None


class BlitzShowcase(BaseModel):
    id: UUID
    blitz_id: UUID
    member_id: UUID
    title: str
    description: str
    repo_url: str | None
    demo_url: str | None
    submitted_at: datetime | None
    vote_count: int


class BlitzMilestone(BaseModel):
    id: UUID
    blitz_id: UUID
    milestone: str
    fired_at: datetime | None