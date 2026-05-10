from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class BadgeDefinition(BaseModel):
    id: UUID
    key: str
    name: str
    description: str
    emoji: str
    trigger: str


class BadgeEarned(BaseModel):
    id: UUID
    member_id: UUID
    badge_id: UUID
    earned_at: datetime


class Badge(BaseModel):
    id: UUID
    member_id: UUID
    badge_id: UUID
    key: str
    name: str
    description: str
    emoji: str
    earned_at: datetime