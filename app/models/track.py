from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Track(BaseModel):
    id: UUID
    name: str
    description: str | None
    level: str | None
    created_by: UUID | None
    is_builtin: bool
    created_at: datetime


class Checkpoint(BaseModel):
    id: UUID
    track_id: UUID
    sequence: int
    title: str
    resource_url: str | None
    exercise: str | None
    knowledge_check: str | None
    answer_hash: str | None
    xp_value: int
    created_at: datetime | None


class TrackProgress(BaseModel):
    id: UUID
    member_id: UUID
    track_id: UUID
    enrolled_at: datetime | None
    completed_at: datetime | None
    checkpoints_done: int


class CheckpointCompletion(BaseModel):
    id: UUID
    member_id: UUID
    checkpoint_id: UUID
    completed_at: datetime | None