from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Ticket(BaseModel):
    id: UUID
    title: str
    description: str | None
    tier: str
    status: str
    priority: str
    phase: str | None
    assignee_id: UUID | None
    reviewer_id: UUID | None
    created_by: UUID | None
    project_id: UUID | None = None
    deadline: datetime | None
    closed_at: datetime | None
    github_pr: str | None
    discord_msg_id: str | None
    created_at: datetime
    updated_at: datetime


class TicketCreate(BaseModel):
    title: str
    description: str | None = None
    tier: str
    priority: str = "medium"
    phase: str | None = None
    project_id: UUID | None = None
    deadline: datetime | None = None


class TicketUpdate(BaseModel):
    status: str | None = None
    priority: str | None = None
    assignee_id: str | None = None
    reviewer_id: str | None = None
    github_pr: str | None = None
    discord_msg_id: str | None = None


class TierViolationError(Exception):
    def __init__(
            self,
            assignee_name: str,
            requested_tier: str,
            max_tier: str
    ) -> None:
        self.assignee_name = assignee_name
        self.requested_tier = requested_tier
        self.max_tier = max_tier
        super().__init__(
            f"{assignee_name} cannot be assigned a {requested_tier} ticket (max allowed: {max_tier})"
        )