from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MemberEnrollment(BaseModel):
    id: UUID
    member_id: UUID
    guild_id: str
    guild_name: str
    signed_out_at: datetime | None
    created_at: datetime


class EnrollmentCreate(BaseModel):
    member_id: UUID
    guild_id: str
    guild_name: str
