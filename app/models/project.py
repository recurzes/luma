from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Project(BaseModel):
    id: UUID
    name: str
    description: str | None
    type: str
    status: str
    github_repo_url: str | None
    owner_id: UUID | None
    discord_guild_id: str
    created_at: datetime
    archived_at: datetime | None


class ProjectCreate(BaseModel):
    name: str
    type: str
    description: str | None = None
    github_repo_url: str | None = None
    guild_id: str


class ProjectMember(BaseModel):
    id: UUID
    project_id: UUID
    member_id: UUID
    role: str
    joined_at: datetime


class MemberContext(BaseModel):
    member_id: UUID
    active_project_id: UUID | None
    updated_at: datetime