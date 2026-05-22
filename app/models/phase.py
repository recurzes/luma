from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Phase(BaseModel):
    id: UUID
    key: str
    name: str
    description: Optional[str] = None
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PhaseCriteria(BaseModel):
    id: UUID
    phase_id: UUID
    description: str
    checked: bool = False
    checked_by: Optional[UUID] = None
    checked_at: Optional[datetime] = None