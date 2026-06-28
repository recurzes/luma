from __future__ import annotations
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel


class JournalEntry(BaseModel):
    id: UUID
    member_id: UUID | None
    project_id: UUID | None
    entry_type: str
    content: str
    mood: int | None
    tags: list[str]
    created_at: datetime


class JournalEntryCreate(BaseModel):
    member_id: UUID
    project_id: UUID | None = None
    entry_type: str = "freeform"
    content: str
    mood: int | None = None
    tags: list[str] = []


class ADR(BaseModel):
    id: UUID
    entry_id: UUID | None
    project_id: UUID | None
    sequence: int
    title: str
    context: str
    decision: str
    alternatives: str | None
    status: str
    superseded_by: UUID | None
